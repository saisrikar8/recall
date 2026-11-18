"""Local parallel OCR and ColSmol document/query token embeddings."""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import os
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import threading

IMAGE_SUFFIXES = frozenset({'.png', '.jpg', '.jpeg', '.webp', '.tif', '.tiff', '.bmp'})
VISUAL_SUFFIXES = IMAGE_SUFFIXES | {'.pdf'}
OCR_VERSION = 'conditional-geometry-tesseract-eng-v2'
MODEL_NAME = 'vidore/colSmol-256M'
MODEL_REVISION = 'c79b633e17e060cc109b11aa2bf92a1517d3bd6f'
BASE_NAME = 'vidore/ColSmolVLM-Instruct-256M-base'
BASE_REVISION = '99ca96f1f6b95b3a69e6abef74a2416cb738fed0'
PAGE_EDGE = 1280
VISUAL_DETAIL = os.environ.get('RECALL_VISUAL_DETAIL', 'fast').strip().lower()
if VISUAL_DETAIL not in {'fast', 'balanced'}:
    raise ValueError('RECALL_VISUAL_DETAIL must be fast or balanced')
PROCESSOR_EDGE = 512 if VISUAL_DETAIL == 'fast' else 1024
SPLIT_IMAGES = VISUAL_DETAIL == 'balanced'
MODEL_CONFIGURATION = dict(model=MODEL_NAME, revision=MODEL_REVISION,
                           base_revision=BASE_REVISION, modality='multi-vector', preprocessing='pil-colsmol-v3', detail=VISUAL_DETAIL, processor_edge=PROCESSOR_EDGE, split_images=SPLIT_IMAGES)
MODEL_KEY = hashlib.sha256(json.dumps(MODEL_CONFIGURATION, sort_keys=True).encode()).hexdigest()
_model = _processor = None
_model_lock = threading.RLock()


def is_visual(path):
    return Path(path).suffix.lower() in VISUAL_SUFFIXES


def iter_pages(path, content, max_pages=1000):
    """Yield (one-based page, RGB image, native text); close each image on resume."""
    from src.extraction import ExtractionError
    try:
        from PIL import Image, ImageOps
        if Path(path).suffix.lower() == '.pdf':
            import pymupdf
            with pymupdf.open(stream=content, filetype='pdf') as document:
                if document.needs_pass:
                    raise ExtractionError('Encrypted PDFs require an unlocked copy')
                if document.page_count > max_pages:
                    raise ExtractionError(f'PDF exceeds the {max_pages}-page limit')
                for number, page in enumerate(document, 1):
                    longest = max(page.rect.width, page.rect.height)
                    scale = min(2.5, 2000 / max(1, longest))
                    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale),
                                             colorspace=pymupdf.csRGB, alpha=False)
                    image = Image.frombytes('RGB', (pixmap.width, pixmap.height), pixmap.samples)
                    del pixmap
                    try:
                        yield number, image, page.get_text()
                    finally:
                        image.close()
        else:
            with Image.open(io.BytesIO(content)) as document:
                count = getattr(document, 'n_frames', 1)
                if count > max_pages:
                    raise ExtractionError(f'Image exceeds the {max_pages}-page limit')
                for number in range(count):
                    document.seek(number)
                    if document.width * document.height > 40_000_000:
                        raise ExtractionError('Image exceeds the 40-megapixel limit')
                    image = ImageOps.exif_transpose(document).convert('RGB')
                    image.thumbnail((2000, 2000))
                    try:
                        yield number + 1, image, ''
                    finally:
                        image.close()
    except ExtractionError:
        raise
    except ImportError as error:
        raise ExtractionError('PDF/image indexing needs Pillow and PyMuPDF. Reinstall the updated Recall package.') from error
    except Exception as error:
        raise ExtractionError(f'PDF/image processing failed: {error}') from error


def ocr_image(image):
    from src.extraction import ExtractionError
    executable = os.environ.get('RECALL_TESSERACT') or shutil.which('tesseract')
    if executable is None:
        raise ExtractionError('Automatic OCR needs Tesseract. On macOS run: brew install tesseract, then retry indexing.')
    data = io.BytesIO()
    image.save(data, format='PNG')
    try:
        result = subprocess.run([executable, 'stdin', 'stdout', '-l', 'eng', '--psm', '3'],
                                input=data.getvalue(), capture_output=True, timeout=90, check=True,
                                env={**os.environ, 'OMP_THREAD_LIMIT': '1', 'OMP_NUM_THREADS': '1'})
        return result.stdout.decode('utf-8').strip()
    except subprocess.TimeoutExpired as error:
        raise ExtractionError('OCR exceeded the 90-second page limit') from error
    except subprocess.CalledProcessError as error:
        raise ExtractionError('OCR failed: ' + error.stderr.decode('utf-8', errors='replace')[:400]) from error


def merge_text(native, ocr):
    """Preserve native text; append OCR lines not already present, ignoring spacing/case."""
    normalize = lambda line: ' '.join(line.casefold().split())
    lines = native.strip().splitlines()
    known = {normalize(line) for line in lines}
    for line in ocr.splitlines():
        key = normalize(line)
        if key and key not in known:
            lines.append(line)
            known.add(key)
    return '\n'.join(lines)


def ocr_worker_count():
    """Use a conservative CPU budget; allow an explicit local override."""
    available = len(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else (os.cpu_count() or 1)
    default = min(4, max(1, available // 2))
    raw = os.environ.get('RECALL_OCR_WORKERS')
    if raw is None:
        return default
    try:
        count = int(raw)
        if not 1 <= count <= 8:
            raise ValueError
    except ValueError:
        from src.extraction import ExtractionError
        raise ExtractionError('RECALL_OCR_WORKERS must be an integer between 1 and 8') from None
    return min(count, available)


def _ocr_owned(image):
    try:
        return ocr_image(image)
    finally:
        image.close()


def _render_ocr(page, clip=None):
    import pymupdf
    from PIL import Image
    longest = max(page.rect.width, page.rect.height)
    scale = min(2.5, 2000 / max(1, longest))
    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), clip=clip,
                             colorspace=pymupdf.csRGB, alpha=False)
    return Image.frombytes('RGB', (pixmap.width, pixmap.height), pixmap.samples)


def iter_ocr_pages(path, content, max_pages):
    """Do not rasterize readable PDF pages. A selected page/crop is worker-owned."""
    from src.ocr_policy import OCRDecision, classify_page
    from src.extraction import ExtractionError
    if Path(path).suffix.lower() != '.pdf':
        for number, image, native in iter_pages(path, content, max_pages):
            yield number, native, OCRDecision('page', 'image_input'), [image.copy()]
        return
    import pymupdf
    try:
        with pymupdf.open(stream=content, filetype='pdf') as document:
            if document.needs_pass:
                raise ExtractionError('Encrypted PDFs require an unlocked copy')
            if len(document) > max_pages:
                raise ExtractionError(f'PDF exceeds the {max_pages}-page limit')
            for number, page in enumerate(document, 1):
                decision = classify_page(page)
                native = '' if decision.reason == 'broken_native_text' else page.get_text()
                # Rasterize one selected region at a time; no document-sized image queue.
                if decision.mode == 'none':
                    yield number, native, decision, []
                elif decision.mode == 'page':
                    yield number, native, decision, [_render_ocr(page)]
                else:
                    for index, region in enumerate(decision.regions):
                        yield number, native if index == 0 else '', decision, [_render_ocr(page, pymupdf.Rect(region))]
    except ExtractionError:
        raise
    except Exception as error:
        raise ExtractionError(f'PDF OCR processing failed: {error}') from error


def extract_units(path, content, max_chars, max_pages, report=print, *, audit=None):
    from src.extraction import ExtractedUnit, _text_units
    units, warnings, page_text, decisions = [], [], {}, {}
    workers = ocr_worker_count()
    pending = deque()

    def collect():
        number, future = pending.popleft()
        page_text[number] = merge_text(page_text[number], future.result())
        report(f'OCR {Path(path).name}: page {number} complete')

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix='recall-ocr') as pool:
        for number, native, decision, images in iter_ocr_pages(path, content, max_pages):
            page_text[number] = merge_text(page_text.get(number, ''), native)
            if number not in decisions:
                decisions[number] = dict(page=number, mode=decision.mode, reason=decision.reason,
                                         regions=len(decision.regions), native_chars=len(native.strip()))
                report(f'{Path(path).name}: page {number}: ' + (
                    f'OCR {decision.mode} ({decision.reason})' if decision.mode != 'none' else
                    f'using native text ({decision.reason})'))
            for image in images:
                try:
                    future = pool.submit(_ocr_owned, image)
                except BaseException:
                    image.close()
                    raise
                pending.append((number, future))
                if len(pending) >= workers:
                    collect()
        while pending:
            collect()
    for number in sorted(page_text):
        text = page_text[number]
        units.append(ExtractedUnit('', 'visual_page', page=number))
        units.extend(_text_units(text, max_chars, kind='native' if decisions[number]['mode'] == 'none' else 'ocr', page=number))
        if not text.strip():
            warnings.append(f'Page {number}: no readable text; visual search is available')
    if audit is not None:
        audit['ocr_pages'] = list(decisions.values())
        audit['ocr_summary'] = {mode: sum(row['mode'] == mode for row in decisions.values())
                                for mode in ['none', 'page', 'regions']}
    return tuple(units), tuple(warnings)


def prepare_page(image):
    page = image.convert('RGB')
    page.thumbnail((PAGE_EDGE, PAGE_EDGE))
    return page


def _load():
    global _model
    if _model is None:
        import json
        import tempfile
        import torch
        from huggingface_hub import snapshot_download
        from sentence_transformers import MultiVectorEncoder
        from src.profiling import measure
        device = 'mps' if torch.backends.mps.is_available() else 'cpu'
        with measure('visual-model-load', model=MODEL_NAME):
            base = snapshot_download(BASE_NAME, revision=BASE_REVISION)
            adapter = snapshot_download(MODEL_NAME, revision=MODEL_REVISION)
            # Pin the adapter's otherwise-unversioned base reference without modifying HF cache files.
            with tempfile.TemporaryDirectory(prefix='recall-colsmol-') as temporary:
                local = Path(temporary) / 'adapter'
                shutil.copytree(adapter, local)
                config = json.loads((local / 'adapter_config.json').read_text())
                config['base_model_name_or_path'] = base
                (local / 'adapter_config.json').write_text(json.dumps(config))
                processor_config = json.loads((local / 'preprocessor_config.json').read_text())
                processor_config['image_processor_type'] = 'Idefics3ImageProcessorPil'
                processor_config['size'] = {'longest_edge': PROCESSOR_EDGE}
                processor_config['do_image_splitting'] = SPLIT_IMAGES
                (local / 'preprocessor_config.json').write_text(json.dumps(processor_config))
                model = MultiVectorEncoder(str(local), device=device,
                    model_kwargs={'dtype': torch.float16 if device == 'mps' else torch.float32,
                                  'attn_implementation': 'sdpa'})
                if device == 'mps':
                    model.half()
            _model = model
    return _model


def embed_images(images):
    if not images:
        return []
    from src.profiling import measure
    from src.multivector import matrix
    prepared = [prepare_page(image) for image in images]
    try:
        with _model_lock, measure('visual-embedding-batch', pages=len(images)):
            model = _load()
            batch_size = 2 if model.device.type == 'mps' else 1
            values = model.encode_document(prepared, batch_size=batch_size, show_progress_bar=False)
            return [matrix(value) for value in values]
    finally:
        for image in prepared:
            image.close()


def embed_image(image):
    return embed_images([image])[0]


def embed_query(query):
    from src.multivector import matrix
    with _model_lock:
        return matrix(_load().encode_query([query], batch_size=1, show_progress_bar=False)[0])
