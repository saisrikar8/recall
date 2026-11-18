"""Code indexing orchestration, reusable independently of the CLI."""
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, select

from src.database import get_db, initialize_database, process_file_index
from src.discovery import discover_files
from src.code_languages import CODE_SUFFIXES
from src.extraction import ExtractionError, extract_document, read_content
from src.models import Collection, File, Function
from src.semantic_search import DEFAULT_MODEL, get_code_embedding
from src.profiling import measure


def _default_report(message):
    print(message, flush=True)


def process_file(file: str, content: bytes | None = None, *, report=_default_report) -> dict:
    """Adapt model-free code extraction to the current function index schema."""
    file = str(file)
    if Path(file).suffix.lower() not in CODE_SUFFIXES:
        return {}
    try:
        document = extract_document(file, content)
        # The current schema identifies functions by line range. Multiple
        # declarations on one line must share one searchable record until the
        # future chunk schema supports byte/column identities.
        from dataclasses import replace
        units = {}
        source_lines = None
        for unit in document.units:
            key = (unit.start_line, unit.end_line)
            if key in units:
                previous = units[key]
                if source_lines is None:
                    source_lines = (content if content is not None else read_content(file))
                    source_lines = source_lines.decode('utf-16') if source_lines.startswith((b'\xff\xfe', b'\xfe\xff')) else source_lines.decode('utf-8-sig')
                    source_lines = source_lines.splitlines()
                units[key] = replace(previous, name=previous.name + ', ' + unit.name,
                                     text='\n'.join(source_lines[unit.start_line - 1:unit.end_line]))
            else:
                units[key] = unit
        functions = []
        for unit in units.values():
            with measure('function', path=file, function=unit.name,
                         start_line=unit.start_line, input_chars=len(unit.text)):
                embedding = get_code_embedding(unit.text)
            functions.append({
                'name': unit.name, 'path': file,
                'start-line': unit.start_line, 'end-line': unit.end_line,
                'docstring': unit.docstring, 'source': unit.text,
                'embedding': embedding, 'embedding-model': DEFAULT_MODEL,
            })
        return {file: {'hash': document.content_hash, 'functions': functions}}
    except (OSError, ExtractionError) as error:
        report(f'Encountered error: {error}')
        return {}


def process_file_or_dir(file_or_dir: str) -> dict:
    records = {}
    for path in discover_files(file_or_dir, supported_suffixes=CODE_SUFFIXES):
        records.update(process_file(path))
    return records


def _update_index(file_or_dir: str, exclude: list[str] | None = None, dry_run: bool = False, *, report=_default_report) -> dict[str, int]:
    from src import pipeline
    from src.extraction import DOCUMENT_SUFFIXES
    target = Path(file_or_dir).resolve()
    paths = discover_files(str(target), exclude or [], supported_suffixes=DOCUMENT_SUFFIXES)
    single_file = target.is_file()
    root = target.parent if single_file else target
    if dry_run:
        report(f'Would scan {len(paths)} files:')
        for position, path in enumerate(paths, 1):
            report(f'{position}. {Path(path).relative_to(root)}')
        return {}
    report(f'Discovered {len(paths)} supported files')
    initialize_database()
    from src.index_progress import IndexProgress
    progress_state=IndexProgress(paths,target,report)
    report=progress_state.report
    counts = dict(new=0, changed=0, unchanged=0, deleted=0, failed=0)
    with get_db() as session, session.begin():
        collections = session.scalars(select(Collection)).all()
        collection = next(
            (c
             for c in collections or []
             if root.is_relative_to(Path(c.root_path))
             ),
            None
        )
        if collection is None:
            children = [
                c for c in collections
                if Path(c.root_path).is_relative_to(root)
            ]

            collection = Collection(root_path=str(root))
            session.add(collection)
            session.flush()

            seen = {}
            for child in children:
                old_root = Path(child.root_path)
                for file in list(child.files):
                    absolute_path = old_root / file.relative_path
                    new_relative = str(absolute_path.relative_to(root))
                    if new_relative in seen:
                        hash_match = not seen[new_relative] or seen[new_relative].content_hash == file.content_hash
                        for function in list(file.functions):
                            session.delete(function)
                        session.delete(file)
                        if not hash_match:
                            for function in list(seen[new_relative].functions):
                                session.delete(function)
                            session.delete(seen[new_relative])
                            seen[new_relative] = None

                        continue
                    seen[new_relative] = file
                    file.relative_path = new_relative
                    file.collection = collection

                session.flush()
                session.delete(child)

            session.flush()

        collection_id = collection.id
        collection_root = Path(collection.root_path)
        old_files = {file.relative_path: file.id for file in session.scalars(
            select(File).where(File.collection_id == collection_id))}
    seen = set()
    prepared_pdfs = []
    pdf_phase = False
    ordered = [p for p in paths if Path(p).suffix.lower() != '.pdf'] + [p for p in paths if Path(p).suffix.lower() == '.pdf']
    for position, path in enumerate(ordered, 1):
        progress_state.begin(path)
        is_pdf = Path(path).suffix.lower() == '.pdf'
        if is_pdf and not pdf_phase:
            report('PDF phase: extracting text and OCR after other files')
            pdf_phase = True
        relative = str(Path(path).relative_to(collection_root))
        seen.add(relative)
        progress = f'[{position}/{len(paths)}]'
        report(f'{progress} Checking {relative}')
        with get_db() as session, session.begin():
            file = session.scalar(select(File).where(File.collection_id == collection_id, File.relative_path == relative))
            existed = file is not None
            if file is None:
                file = File(collection_id=collection_id, relative_path=relative)
                session.add(file); session.flush()
            file_id, old_hash = file.id, file.content_hash
        try:
            stat = Path(path).stat()
            signature = (stat.st_mtime_ns, stat.st_size)
            content = read_content(path)
            fingerprint = hashlib.sha256(content).hexdigest()
        except (OSError, ExtractionError) as error:
            with get_db() as session, session.begin():
                session.get(File, file_id).last_error = str(error)
            report(f'{progress} Failed {relative}: {error}')
            counts['failed'] += 1
            progress_state.finish(path,'failed')
            continue
        if old_hash == fingerprint and pipeline.current(file_id, fingerprint):
            report(f'{progress} Skipped unchanged {relative}')
            counts['unchanged'] += 1
            progress_state.finish(path,'unchanged')
            continue
        report(f'{progress} Processing {relative}')
        with measure('file-processing', path=relative, file_bytes=len(content)):
            if is_pdf:
                prepared = pipeline.prepare(file_id, path, content, report=report, source_signature=signature)
                if prepared is not None:
                    prepared_pdfs.append((prepared, existed))
                else:
                    counts['failed'] += 1
                    progress_state.finish(path,'failed')
            else:
                succeeded = pipeline.process(file_id, path, content, encoder=get_code_embedding,
                                             report=report, source_signature=signature)
                status=('changed' if existed else 'new') if succeeded else 'failed'
                counts[status] += 1
                progress_state.finish(path,status)
        del content
    if prepared_pdfs:
        report(f'PDF phase: embedding {len(prepared_pdfs)} prepared PDFs together')
        failed = pipeline.embed_visual_group([prepared for prepared, _ in prepared_pdfs], report=report)
        failed.update(pipeline.embed_scene_group([prepared for prepared,_ in prepared_pdfs
            if prepared.file_id not in failed],report=report))
        for prepared, existed in prepared_pdfs:
            succeeded = prepared.file_id not in failed and pipeline.complete(
                prepared, encoder=get_code_embedding, report=report, visual_ready=True)
            status=('changed' if existed else 'new') if succeeded else 'failed'
            counts[status] += 1
            progress_state.finish(prepared.path,status)
    if not single_file:
        with get_db() as session, session.begin():
            for relative, file_id in old_files.items():
                if relative not in seen and (collection_root / relative).is_relative_to(target):
                    session.execute(delete(Function).where(Function.file_id == file_id))
                    session.execute(delete(File).where(File.id == file_id))
                    counts['deleted'] += 1
    progress_state.done()
    report('Indexed: ' + ', '.join(f'{value} {name}' for name, value in counts.items()))
    return counts


def update_index(file_or_dir: str, exclude: list[str] | None = None, dry_run: bool = False, *, report=_default_report):
    """Serialize disk-backed indexing; readers remain free to search old Gold."""
    if dry_run:
        return _update_index(file_or_dir, exclude, True, report=report)
    from contextlib import nullcontext
    from filelock import FileLock, Timeout
    from src import database
    path = database.engine.url.database
    lock = nullcontext()
    if path and path != ':memory:':
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        lock = FileLock(path + '.lock', timeout=0)
    try:
        with lock:
            return _update_index(file_or_dir, exclude, False, report=report)
    except Timeout as error:
        raise ValueError('Another indexing run is active for this database; wait for it to finish') from error
