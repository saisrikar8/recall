"""Optional, local-only worker that retains the embedding model between CLI calls."""
import json
import os
from pathlib import Path
import socket
import socketserver

from platformdirs import user_cache_path

MAX_MESSAGE = 16 * 1024 * 1024


def socket_path():
    override = os.environ.get('RECALL_EMBEDDING_SOCKET')
    return Path(override).expanduser().resolve() if override else user_cache_path(
        'recall', appauthor=False) / 'embedding.sock'


def request_embedding(text, model_name):
    path = socket_path()
    if not path.exists():
        return None
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(300)
        try:
            client.connect(str(path))
        except (ConnectionRefusedError, FileNotFoundError):
            # An interrupted worker can leave a socket behind; local inference works.
            return None
        message = json.dumps({'text': text, 'model': model_name}).encode() + b'\n'
        if len(message) > MAX_MESSAGE:
            raise ValueError('Embedding request exceeds the worker message limit.')
        client.sendall(message)
        with client.makefile('rb') as stream:
            response = stream.readline(MAX_MESSAGE + 1)
        if len(response) > MAX_MESSAGE or not response.endswith(b'\n'):
            raise RuntimeError('Invalid response from Recall embedding worker.')
        result = json.loads(response)
        if 'error' in result:
            raise RuntimeError(f"Recall embedding worker: {result['error']}")
        return result['embedding']


def serve(encoder=None):
    if not hasattr(socket, 'AF_UNIX'):
        raise RuntimeError('The embedding worker requires Unix sockets (macOS/Linux).')
    from src.semantic_search import DEFAULT_MODEL, _encode_local
    encode = encoder or _encode_local
    # Warm up before accepting requests, surfacing model errors at startup.
    encode('Recall model warmup', DEFAULT_MODEL)
    path = socket_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.settimeout(1)
            try:
                probe.connect(str(path))
            except ConnectionRefusedError:
                path.unlink()
            else:
                raise RuntimeError('A Recall embedding worker is already running.')

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            self.request.settimeout(300)
            try:
                raw = self.rfile.readline(MAX_MESSAGE + 1)
                if not raw:
                    return
                if len(raw) > MAX_MESSAGE or not raw.endswith(b'\n'):
                    raise ValueError('Embedding request exceeds the worker message limit.')
                request = json.loads(raw)
                if request.get('model') != DEFAULT_MODEL:
                    raise ValueError('Worker only supports the default embedding model.')
                if not isinstance(request.get('text'), str):
                    raise ValueError('Embedding input must be text.')
                result = {'embedding': encode(request['text'], DEFAULT_MODEL)}
            except Exception as error:
                result = {'error': str(error)}
            try:
                self.wfile.write(json.dumps(result).encode() + b'\n')
            except (BrokenPipeError, ConnectionResetError):
                pass

    # Restrict socket access to the current user; no TCP port or pickle protocol.
    previous = os.umask(0o077)
    try:
        server = socketserver.UnixStreamServer(str(path), Handler)
    finally:
        os.umask(previous)
    try:
        print('Recall embedding worker ready. Keep this terminal open; Ctrl-C stops it.', flush=True)
        with server:
            server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        path.unlink(missing_ok=True)
