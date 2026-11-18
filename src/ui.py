"""Small loopback-only web interface, sharing the CLI index and search engine."""
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
import json
from pathlib import Path
import secrets
import subprocess
import sys
import threading
from urllib.parse import urlparse, unquote
import webbrowser


class BusyError(ValueError):
    pass


class Jobs:
    """Serialize model work and mutations; retain only the latest job and bounded logs."""
    def __init__(self):
        self.lock = threading.Lock()
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.job = None

    def submit(self, operation):
        with self.lock:
            if self.job and self.job['status'] == 'running':
                raise BusyError('An operation is already running. Wait for it to finish.')
            identity = secrets.token_hex(12)
            self.job = dict(id=identity, status='running', messages=[], progress=None, result=None, error=None)
        def report(message):
            with self.lock:
                self.job['messages'].append(str(message))
                self.job['messages'] = self.job['messages'][-200:]
        def event(progress):
            with self.lock:
                self.job['progress']=progress
        report.event=event
        def run():
            try:
                result = operation(report)
                with self.lock:
                    self.job.update(status='complete', result=result)
            except Exception as error:
                with self.lock:
                    self.job.update(status='failed', error=str(error))
        self.executor.submit(run)
        return identity

    def snapshot(self, identity):
        with self.lock:
            if not self.job or self.job['id'] != identity:
                raise ValueError('Operation not found. It may have been replaced by a newer operation.')
            return dict(self.job, messages=list(self.job['messages']))

    def close(self):
        self.executor.shutdown(wait=True)


def index_operation(data, report):
    from src.indexing import update_index
    raw = data.get('path', '')
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError('Enter a file or folder path.')
    path = Path(raw).expanduser().resolve()
    if not path.exists():
        raise ValueError('That file or folder does not exist.')
    exclusions = data.get('exclude', [])
    if not isinstance(exclusions, list) or not all(isinstance(x, str) for x in exclusions):
        raise ValueError('Exclusions must be a list of paths.')
    return update_index(str(path), exclusions, bool(data.get('dry_run')), report=report)


def search_operation(data):
    from src.retrieval import search
    query = data.get('query', '')
    if not isinstance(query, str) or not query.strip():
        raise ValueError('Enter a search question.')
    limit = int(data.get('limit', 10))
    if not 1 <= limit <= 100:
        raise ValueError('Result count must be between 1 and 100.')
    candidates = search(query, min(100,limit*3), float(data.get('threshold', .4)), data.get('collection') or None)
    # Desktop rows are files/pages, rather than repeated rows for every code chunk.
    records,seen=[],set()
    for record in candidates:
        key=(record['path'],record.get('page'))
        if key not in seen:
            seen.add(key);records.append(record)
        if len(records)>=limit:break
    return records


def remove_operation(data):
    from src.index_management import remove_index
    return remove_index(collection=data.get('collection') or None,
                        file=data.get('file') or None, function_id=data.get('id') or None)


def open_indexed_file(path):
    """Only open existing files represented in the index; never interpret shell text."""
    from src.index_management import list_index
    if not isinstance(path, str):
        raise ValueError('Select an indexed file.')
    target = Path(path).resolve()
    indexed = {str((Path(c['root']) / f['path']).resolve())
               for c in list_index() for f in c['files']}
    if str(target) not in indexed or not target.is_file():
        raise ValueError('The indexed file is no longer available.')
    if sys.platform == 'darwin':
        command = ['open', str(target)]
    elif sys.platform == 'win32':
        import os
        os.startfile(str(target))
        return
    else:
        command = ['xdg-open', str(target)]
    subprocess.run(command, check=True, timeout=15, capture_output=True)


def make_server(port=8765):
    token = secrets.token_urlsafe(32)
    jobs = Jobs()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send(self, status, value, html=False):
            body = value.encode() if html else json.dumps(value, allow_nan=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'text/html; charset=utf-8' if html else 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'nonce-" + token + "'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(body)

        def authorized(self, api=False):
            allowed = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
            if self.headers.get('Host') not in allowed:
                self.send(403, {'error': 'Local requests only.'})
                return False
            origin = self.headers.get('Origin')
            if origin and origin not in {f'http://{host}' for host in allowed}:
                self.send(403, {'error': 'Request origin rejected.'})
                return False
            if api and not secrets.compare_digest(self.headers.get('X-Recall-Token', ''), token):
                self.send(403, {'error': 'Reload the Recall page to reconnect.'})
                return False
            return True

        def do_GET(self):
            path = urlparse(self.path).path
            if not self.authorized(api=path != '/'):
                return
            try:
                if path == '/':
                    page = files('src').joinpath('ui.html').read_text(encoding='utf-8')
                    self.send(200, page.replace('__RECALL_TOKEN__', token), html=True)
                elif path == '/api/collections':
                    from src.index_management import list_index
                    self.send(200, list_index())
                elif path.startswith('/api/entity/'):
                    from src.index_management import get_function
                    self.send(200, get_function(unquote(path.rsplit('/', 1)[1])))
                elif path.startswith('/api/jobs'):
                    self.send(200, jobs.snapshot(path.rsplit('/', 1)[1]))
                else:
                    self.send(404, {'error': 'Not found.'})
            except Exception as error:
                self.send(400, {'error': str(error)})

        def do_POST(self):
            if not self.authorized(api=True):
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 65536:
                    raise ValueError('Request must contain at most 64 KiB of JSON.')
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError('Expected a JSON object.')
                path = urlparse(self.path).path
                if path == '/api/open':
                    open_indexed_file(data.get('path'))
                    self.send(200, {'ok': True})
                    return
                operations = {'/api/index': lambda report: index_operation(data, report),
                              '/api/search': lambda report: search_operation(data),
                              '/api/remove': lambda report: remove_operation(data)}
                if path not in operations:
                    self.send(404, {'error': 'Not found.'})
                    return
                self.send(202, {'id': jobs.submit(operations[path])})
            except BusyError as error:
                self.send(409, {'error': str(error)})
            except Exception as error:
                self.send(400, {'error': str(error)})

    try:
        server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    except Exception:
        jobs.close()
        raise
    server.jobs = jobs
    server.daemon_threads = True
    return server


def serve(port=8765, open_browser=True):
    from src.database import initialize_database
    initialize_database()
    server = make_server(port)
    url = f'http://127.0.0.1:{server.server_port}'
    print(f'Recall UI: {url}\nPress Ctrl+C to stop. Running work finishes before shutdown.', flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        server.jobs.close()
