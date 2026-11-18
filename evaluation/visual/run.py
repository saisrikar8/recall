"""Compare existing text embeddings with CLIP page embeddings and rank fusion."""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from evaluation.visual.routing import selective_rankings


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def fuse(*rankings):
    scores = {}
    for ranking in rankings:
        for rank, page in enumerate(ranking, 1):
            scores[page] = scores.get(page, 0) + 1 / (60 + rank)
    return sorted(scores, key=lambda page: (-scores[page], page))


def metrics(rankings, queries):
    labeled = [q for q in queries if q.get('relevant')]
    if not labeled:
        return {'judged_queries': 0}
    positions = [next((i for i, p in enumerate(rankings[q['id']], 1)
                       if p in q['relevant']), 0) for q in labeled]
    return {'judged_queries': len(labeled),
            'hit_at_1': sum(p == 1 for p in positions) / len(labeled),
            'hit_at_5': sum(0 < p <= 5 for p in positions) / len(labeled),
            'mrr': sum(1 / p if p else 0 for p in positions) / len(labeled)}


def prepare(folder, output, max_pages, ocr, pattern="*.pdf"):
    import pymupdf
    from src.profiling import MemorySample
    pages = []
    with MemorySample() as sample:
        for path in sorted(folder.glob(pattern)):
            source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            with pymupdf.open(path) as doc:
                if doc.needs_pass:
                    raise ValueError(f'Encrypted PDF: {path.name}')
                for number, page in enumerate(doc, 1):
                    if len(pages) >= max_pages:
                        break
                    identity = f'{path.name}#page={number}'
                    image_name = hashlib.sha256(identity.encode()).hexdigest()[:20] + '.png'
                    image_path = output / image_name
                    # Bound the longest dimension; do not retain document images in RAM.
                    scale = min(1.5, 1200 / max(page.rect.width, page.rect.height))
                    page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).save(image_path)
                    text = page.get_text().strip()
                    method = 'pdf-text'
                    if ocr and len(text) < 30:
                        result = subprocess.run(['tesseract', str(image_path), 'stdout'],
                                                capture_output=True, text=True, check=True, timeout=60)
                        text, method = result.stdout.strip(), 'tesseract'
                    pages.append(dict(id=identity, image=image_name, text=text, text_method=method,
                                      source_sha256=source_hash))
                    print(f'Prepared {len(pages)}: {identity}', flush=True)
            if len(pages) >= max_pages:
                break
    if not pages:
        raise ValueError('No PDF pages found')
    write_json(output / 'pages.json', pages)
    write_json(output / 'prepare-profile.json', sample.record('prepare'))
    return pages


def worker(mode, output, queries_path):
    from src.profiling import MemorySample
    with MemorySample() as total:
        import torch
        torch.set_num_threads(2)
        pages = json.loads((output / 'pages.json').read_text())
        queries = json.loads(queries_path.read_text())['queries']
        vectors, query_vectors = [], []
        with MemorySample() as loading:
            if mode == 'text':
                from sentence_transformers import SentenceTransformer
                from src.semantic_search import DEFAULT_MODEL, EMBED_QUERY
                model = SentenceTransformer(DEFAULT_MODEL, trust_remote_code=True, device='cpu',
                                            revision='3c4b60807d71f79b43f3c4363786d9493691f8b1')
                from src.transformer_compat import prepare_coderank
                prepare_coderank(model)
                model.max_seq_length = 512
            else:
                from transformers import CLIPModel, CLIPProcessor
                model = CLIPModel.from_pretrained('openai/clip-vit-base-patch32',
                                                 revision='3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268').eval()
                processor = CLIPProcessor.from_pretrained('openai/clip-vit-base-patch32',
                                                         revision='3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268')
        with MemorySample() as encoding, torch.inference_mode():
            for page in pages:
                if mode == 'text':
                    # Batch one, bounded token input. Best passage score preserves page identity.
                    words = page['text'].split()
                    passages = [' '.join(words[i:i+200]) for i in range(0, len(words), 160)]
                    vectors.append(model.encode(passages, batch_size=1, normalize_embeddings=True,
                                                convert_to_tensor=True) if passages else None)
                else:
                    from PIL import Image, ImageOps
                    with Image.open(output / page['image']) as image:
                        # Letterbox instead of center cropping away document edges.
                        image = ImageOps.pad(image.convert('RGB'), (224, 224), color='white')
                        inputs = processor(images=image, return_tensors='pt')
                        value = model.get_image_features(**inputs)
                        value = value if isinstance(value, torch.Tensor) else value.pooler_output
                        vectors.append(torch.nn.functional.normalize(value, dim=-1))
                print(f'{mode}: {len(vectors)}/{len(pages)} pages', flush=True)
            for query in queries:
                if mode == 'text':
                    value = model.encode(EMBED_QUERY + ' ' + query['text'], normalize_embeddings=True,
                                         convert_to_tensor=True).reshape(1, -1)
                else:
                    inputs = processor(text=[query['text']], return_tensors='pt', truncation=True)
                    value = model.get_text_features(**inputs)
                    value = value if isinstance(value, torch.Tensor) else value.pooler_output
                    value = torch.nn.functional.normalize(value, dim=-1)
                query_vectors.append(value)
        rankings = {}
        for query, value in zip(queries, query_vectors):
            scores = [(page['id'], float((matrix @ value.T).max()))
                      for page, matrix in zip(pages, vectors) if matrix is not None]
            rankings[query['id']] = [identity for identity, _ in sorted(scores, key=lambda x: (-x[1], x[0]))]
        revision = getattr(model.config, '_commit_hash', None) if mode != 'text' else getattr(model[0].auto_model.config, '_commit_hash', None)
    write_json(output / f'{mode}.json', dict(rankings=rankings, metrics=metrics(rankings, queries),
               model_revision=revision, profiles=[loading.record('load'), encoding.record('encode'), total.record('total')]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder', type=Path, default=Path('example_pdfs'))
    parser.add_argument('--output', type=Path, default=Path('/tmp/recall-visual-evaluation'))
    parser.add_argument('--queries', type=Path, default=Path('evaluation/visual/queries.json'))
    parser.add_argument('--max-pages', type=int, default=80)
    parser.add_argument('--pdf', default='*.pdf', help='PDF filename glob within folder')
    parser.add_argument('--ocr', action='store_true', help='OCR pages with little embedded text; needs tesseract')
    parser.add_argument('--worker', choices=['text', 'visual'], help=argparse.SUPPRESS)
    parser.add_argument('--reuse-pages', action='store_true')
    args = parser.parse_args()
    if args.worker:
        worker(args.worker, args.output, args.queries)
        return
    if args.max_pages < 1:
        parser.error('--max-pages must be positive')
    queries = json.loads(args.queries.read_text())['queries']
    if not queries or len({q['id'] for q in queries}) != len(queries):
        parser.error('Queries must have distinct IDs and contain at least one query')
    args.output.mkdir(parents=True, exist_ok=True)
    pages = json.loads((args.output / 'pages.json').read_text()) if args.reuse_pages else prepare(
        args.folder, args.output, args.max_pages, args.ocr, args.pdf)
    missing = {p for q in queries for p in q.get('relevant', [])} - {p['id'] for p in pages}
    if missing:
        parser.error(f'Expected pages absent from corpus: {sorted(missing)}; increase --max-pages')
    # Separate processes release all model memory between modes; no main index or worker.
    for mode in ['text', 'visual']:
        subprocess.run([sys.executable, '-m', __package__ + '.run', '--worker', mode,
                        '--output', str(args.output), '--queries', str(args.queries)], check=True)
    text, visual = [json.loads((args.output / f'{mode}.json').read_text()) for mode in ['text', 'visual']]
    combined = {q['id']: fuse(text['rankings'][q['id']], visual['rankings'][q['id']]) for q in queries}
    selective, routes = selective_rankings(queries, text['rankings'], combined)
    report = dict(pages=len(pages), queries=queries, text=text, visual=visual,
                  combined=dict(rankings=combined, metrics=metrics(combined, queries)),
                  selective=dict(rankings=selective, metrics=metrics(selective, queries), routes=routes),
                  notes=['Exploratory development set; judgments may be incomplete.',
                         'CLIP is a small general-image baseline, not a handwriting-specialized model.',
                         'Memory is sampled process RSS, not system-wide or GPU memory.',
                         'Text uses current CodeRankEmbed with bounded passages; OCR is optional.',
                         'Rank fusion does not compare scores between incompatible vector spaces.'])
    for mode in ['text', 'visual', 'combined', 'selective']:
        report[mode]['by_category'] = {
            category: metrics(report[mode]['rankings'], [q for q in queries if q.get('category', 'other') == category])
            for category in sorted({q.get('category', 'other') for q in queries})
        }
    write_json(args.output / 'results.json', report)
    for mode in ['text', 'visual', 'combined', 'selective']:
        print(mode, report[mode]['metrics'])
    print('Full results:', args.output / 'results.json')


if __name__ == '__main__':
    main()
