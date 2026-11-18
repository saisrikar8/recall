"""Exercise the actual local HTTP interface against a disposable index."""
import http.client
import json
from pathlib import Path
import re
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, event
from src import database as db, indexing, semantic_search
from src.ui import make_server


class UITests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        engine = create_engine('sqlite:///' + str(self.root / 'test.db'))
        self.addCleanup(engine.dispose)
        event.listen(engine, 'connect', db.register_functions)
        self.enterContext(patch.object(db, 'engine', engine))
        self.enterContext(patch.object(indexing, 'get_code_embedding', return_value=[1., 0.]))
        self.enterContext(patch.object(semantic_search, 'get_query_embedding', return_value=[1., 0.]))
        db.initialize_database()
        self.server = make_server(0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)
        status, page = self.request('GET', '/', auth=False)
        self.assertEqual(status, 200)
        self.token = re.search("const token='([^']+)'", page).group(1)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.server.jobs.close()
        self.thread.join()

    def request(self, method, path, data=None, auth=True, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        self.addCleanup(connection.close)
        values = {'Content-Type': 'application/json'}
        if auth:
            values['X-Recall-Token'] = self.token
        values.update(headers or {})
        connection.request(method, path, body=json.dumps(data) if data is not None else None, headers=values)
        response = connection.getresponse()
        body = response.read().decode()
        return response.status, body if path == '/' else json.loads(body)

    def operation(self, endpoint, data):
        status, result = self.request('POST', endpoint, data)
        self.assertEqual(status, 202, result)
        for _ in range(200):
            _, job = self.request('GET', '/api/jobs/' + result['id'])
            if job['status'] != 'running':
                return job
            time.sleep(.01)
        self.fail('Job did not finish')

    def test_index_search_browse_entity_and_remove(self):
        path = self.root / 'client.py'
        path.write_text('def retry_request():\n    return "retry"\n')
        job = self.operation('/api/index', {'path': str(path)})
        self.assertEqual(job['status'], 'complete', job)
        self.assertEqual(job['result']['new'], 1)
        self.assertTrue(job['messages'])
        _, records = self.request('GET', '/api/collections')
        entry = records[0]['files'][0]
        self.assertEqual(entry['path'], 'client.py')
        identity = next(e['id'] for e in entry['entities'] if e['name'] == 'retry_request')
        _, entity = self.request('GET', '/api/entity/' + identity)
        self.assertIn('return "retry"', entity['source'])
        job = self.operation('/api/search', {'query': 'retry requests'})
        self.assertEqual(job['status'], 'complete', job)
        self.assertTrue(job['result'])
        job = self.operation('/api/remove', {'collection': records[0]['root']})
        self.assertEqual(job['status'], 'complete', job)
        self.assertTrue(path.exists())
        self.assertEqual(self.request('GET', '/api/collections')[1], [])

    def test_rejects_foreign_origin_bad_host_and_missing_token(self):
        self.assertEqual(self.request('GET', '/api/collections', auth=False)[0], 403)
        self.assertEqual(self.request('POST', '/api/index', {'path': '/tmp'},
                                     headers={'Origin': 'https://example.com'})[0], 403)
        self.assertEqual(self.request('GET', '/', headers={'Host': 'evil.example'})[0], 403)
        self.assertEqual(self.request('POST', '/api/open', {'path': '/etc/passwd'})[0], 400)

    def test_failed_job_does_not_break_next_operation(self):
        job = self.operation('/api/search', {'query': ''})
        self.assertEqual(job['status'], 'failed')
        self.assertIn('question', job['error'])
        job = self.operation('/api/index', {'path': str(self.root), 'dry_run': True})
        self.assertEqual(job['status'], 'complete')

    def test_concurrent_job_is_rejected_instead_of_loading_two_models(self):
        release = threading.Event()
        self.addCleanup(release.set)
        self.server.jobs.submit(lambda report: release.wait(3))
        status, result = self.request('POST', '/api/search', {'query': 'retry'})
        self.assertEqual(status, 409)
        self.assertIn('already running', result['error'])
        release.set()
