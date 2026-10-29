import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from src import embedding_service as service, semantic_search as semantic


class EmbeddingServiceTests(unittest.TestCase):
    def test_worker_reuses_encoder_across_clients_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'worker.sock'
            calls = []
            def encode(text, name):
                calls.append(text)
                return [1., 0.]
            # Run the actual worker, stopping its serve loop after two requests.
            def two_requests(server):
                server.handle_request()
                server.handle_request()
            with patch.dict(os.environ, {'RECALL_EMBEDDING_SOCKET': str(path)}):
                with patch.object(service.socketserver.UnixStreamServer, 'serve_forever', two_requests):
                    errors = []
                    def run():
                        try:
                            service.serve(encode)
                        except Exception as error:
                            errors.append(error)
                    worker = threading.Thread(target=run, daemon=True)
                    worker.start()
                    import time
                    deadline = time.monotonic() + 5
                    while not path.exists() and time.monotonic() < deadline:
                        time.sleep(.01)
                    self.assertTrue(path.exists())
                    self.assertEqual(path.stat().st_mode & 0o777, 0o700)
                    for _ in range(2):
                        result = subprocess.run([sys.executable, '-c',
                            'from src.semantic_search import get_code_embedding; '
                            'from src.profiling import capture; '
                            '\nwith capture(True): print(get_code_embedding("example"))'],
                            capture_output=True, text=True, timeout=10, check=True)
                        self.assertIn('[1.0, 0.0]', result.stdout)
                        self.assertIn('worker-request', result.stderr)
                        self.assertIn('\"process\": \"worker\"', result.stderr)
                    worker.join(timeout=5)
                    self.assertFalse(worker.is_alive())
                    self.assertEqual(errors, [])
                    self.assertFalse(path.exists())
                    self.assertEqual(calls, ['Recall model warmup', 'example', 'example'])

    def test_no_worker_falls_back_to_local_encoder(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.dict(os.environ, {'RECALL_EMBEDDING_SOCKET': str(Path(temporary) / 'none.sock')}):
                with patch.object(semantic, '_encode_local', return_value=[.5]) as encode:
                    self.assertEqual(semantic.get_code_embedding('code'), [.5])
                    encode.assert_called_once_with('code', semantic.DEFAULT_MODEL)

    def test_cli_help_does_not_import_model_dependencies(self):
        result = subprocess.run([sys.executable, '-c',
            'import sys; from src import main; '
            'sys.argv=["recall", "--help"]; '
            '\ntry: main.main()\nexcept SystemExit: pass\n'
            'assert "torch" not in sys.modules; '
            'assert "sentence_transformers" not in sys.modules'],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
