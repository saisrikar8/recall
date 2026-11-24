"""Private Electron JSON-lines bridge. Stdout is reserved for framed responses."""
import base64
import json
from pathlib import Path
import re
import sys
from concurrent.futures import ThreadPoolExecutor
import threading

from sqlalchemy import select, or_
from src import database as db
from src.models import File, Collection
from src.ui import Jobs, index_operation, search_operation, open_indexed_file


def indexed_path(raw):
    if not isinstance(raw, str) or not raw:
        raise ValueError('Select an indexed file.')
    target = Path(raw).expanduser().resolve()
    with db.get_db() as session:
        allowed = any((Path(root) / relative).resolve() == target
                      for root, relative in session.execute(select(Collection.root_path, File.relative_path).join(File.collection)))
    if not allowed or not target.is_file():
        raise ValueError('This file is unavailable or has not been indexed.')
    return target


def library():
    with db.get_db() as session:
        rows = session.execute(select(File, Collection).join(File.collection).where(or_(File.content_hash.is_not(None),File.last_error.is_not(None))).order_by(File.indexed_at.desc(), File.id.desc())).all()
        collections = session.scalars(select(Collection).order_by(Collection.root_path)).all()
        files = []
        for file, collection in rows:
            path = Path(collection.root_path) / file.relative_path
            files.append(dict(id=file.id, path=str(path), name=path.name,
                collection=collection.root_path, relative_path=file.relative_path,
                extension=path.suffix.lower(), indexed_at=file.indexed_at.isoformat() + 'Z' if file.indexed_at else None,
                error=file.last_error))
        return dict(files=files, collections=[dict(path=c.root_path, name=Path(c.root_path).name,
            count=sum(f['collection'] == c.root_path for f in files)) for c in collections])


def preview(data):
    path = indexed_path(data.get('path'))
    suffix = path.suffix.lower()
    query = str(data.get('query', ''))[:1000]
    terms = list(dict.fromkeys(re.findall(r'[\w-]{3,}', query)))[:24]
    stop = {'the', 'what', 'where', 'which', 'show', 'find', 'with', 'that', 'this', 'does', 'how', 'and', 'for', 'from'}
    terms = [term for term in terms if term.casefold() not in stop]
    result = dict(path=str(path), name=path.name, extension=suffix, terms=terms, bytes=path.stat().st_size)
    if suffix == '.pdf':
        import pymupdf
        with pymupdf.open(path) as document:
            if document.needs_pass:
                raise ValueError('This PDF is encrypted. Preview an unlocked copy.')
            page_number = max(1, min(int(data.get('page') or 1), len(document)))
            page = document[page_number - 1]
            scale = min(2, 1400 / max(page.rect.width, page.rect.height))
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
            bounds = []
            for term in terms:
                for rect in page.search_for(term)[:100]:
                    bounds.append(dict(x=(rect.x0-page.rect.x0)/page.rect.width, y=(rect.y0-page.rect.y0)/page.rect.height,
                        width=rect.width/page.rect.width, height=rect.height/page.rect.height))
            result.update(kind='pdf', page=page_number, pages=len(document),
                image='data:image/png;base64,' + base64.b64encode(pixmap.tobytes('png')).decode(), highlights=bounds,
                text=page.get_text()[:100000])
    else:
        from src.visual import IMAGE_SUFFIXES
        from src.extraction import read_content, _decode_text
        if suffix in IMAGE_SUFFIXES:
            from PIL import Image, ImageOps
            import io
            with Image.open(path) as source:
                if source.width * source.height > 40_000_000:
                    raise ValueError('Image is too large to preview safely.')
                image = ImageOps.exif_transpose(source).convert('RGB')
                try:
                    image.thumbnail((1800, 1800))
                    output = io.BytesIO(); image.save(output, format='PNG')
                    result.update(kind='image', image='data:image/png;base64,' + base64.b64encode(output.getvalue()).decode())
                finally:
                    image.close()
        else:
            content = read_content(path)
            text = _decode_text(content)
            lines = text.splitlines()
            target = max(1, int(data.get('line') or 1))
            # Bound large code previews but retain the matched line and real numbering.
            start = max(0, min(target - 150, len(lines) - 1200))
            result.update(kind='markdown' if suffix in {'.md', '.markdown'} else 'code',
                text='\n'.join(lines[start:start + 1200]), first_line=start + 1,
                total_lines=len(lines), match_line=target if data.get('line') else None,
                truncated=start > 0 or len(lines) > 1200)
    return result


def remove_collection(data):
    return remove_saved_index(collection=data.get('collection'))


def remove_file(data):
    raw = data.get('path')
    if not isinstance(raw, str) or not raw.strip() or not Path(raw).is_absolute():
        raise ValueError('Select an indexed file.')
    return remove_saved_index(file=raw)


def remove_saved_index(collection=None, file=None):
    from contextlib import nullcontext
    from filelock import FileLock, Timeout
    from src.index_management import remove_index
    if file is None and (not isinstance(collection, str) or not collection.strip()):
        raise ValueError('Select a collection to remove.')
    database = db.engine.url.database
    lock = FileLock(database + '.lock', timeout=0) if database and database != ':memory:' else nullcontext()
    try:
        with lock:
            return remove_index(collection=collection, file=file)
    except Timeout:
        raise ValueError('An indexing run is active. Wait for it to finish before removing items.') from None


def main():
    output = sys.stdout
    # Third-party model progress must never corrupt the protocol.
    sys.stdout = sys.stderr
    db.initialize_database()
    jobs = Jobs()
    from src.desktop_warmup import warmup_models
    # Serialize startup inference with later model operations. Metadata/previews
    # remain responsive and searches queue safely behind this one warmup.
    warmup = jobs.executor.submit(warmup_models)
    pool = ThreadPoolExecutor(max_workers=3)
    lock = threading.Lock()
    def respond(message):
        identity = message.get('id')
        try:
            method, data = message['method'], message.get('data', {})
            if method == 'engine-status':
                value = warmup.result() if warmup.done() else dict(channels={}, warming=True)
            elif method == 'library': value = library()
            elif method == 'preview': value = preview(data)
            elif method == 'validate': value = str(indexed_path(data.get('path')))
            elif method == 'open': open_indexed_file(data.get('path')); value = True
            elif method == 'job': value = jobs.snapshot(data['id'])
            elif method == 'search': value = dict(id=jobs.submit(lambda report: search_operation(data)))
            elif method == 'remove-file': value = dict(id=jobs.submit(lambda report: remove_file(data)))
            elif method == 'remove-collection': value = dict(id=jobs.submit(lambda report: remove_collection(data)))
            elif method == 'index': value = dict(id=jobs.submit(lambda report: index_operation(data, report)))
            else: raise ValueError('Unknown operation.')
            reply = dict(id=identity, result=value)
        except Exception as error:
            reply = dict(id=identity, error=str(error))
        with lock:
            output.write(json.dumps(reply, allow_nan=False) + '\n'); output.flush()
    try:
        for line in sys.stdin:
            if len(line) > 65536: continue
            try: message = json.loads(line)
            except ValueError: continue
            if isinstance(message, dict): pool.submit(respond, message)
    finally:
        pool.shutdown(wait=True); jobs.close()

if __name__ == '__main__':
    main()
