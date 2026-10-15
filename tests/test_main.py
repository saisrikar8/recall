import contextlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from src.main import match_fxns, process_file, process_file_or_dir


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def record(name, docstring='', body='pass'):
    return {
        'name': name,
        'path': 'sample.py',
        'start-line': 1,
        'end-line': 2,
        'docstring': docstring,
        'source': f'def {name}():\n    {body}',
    }


class SearchTests(unittest.TestCase):
    def test_exact_name_ranks_before_partial_name(self):
        records = [record('fetch_more', 'fetch'), record('fetch')]
        results = match_fxns(records, 'fetch', 5)
        self.assertEqual([r['name'] for r in results], ['fetch', 'fetch_more'])

    def test_partial_name_ranks_before_body_only_match(self):
        records = [record('load', body='fetch()'), record('fetch_more')]
        results = match_fxns(records, 'fetch', 5)
        self.assertEqual([r['name'] for r in results], ['fetch_more', 'load'])

    def test_searches_name_docstring_and_body_case_insensitively(self):
        for item, query in [
            (record('fetch'), 'FETCH'),
            (record('load', 'Download a resource'), 'DOWNLOAD'),
            (record('load', body='requests.get(url)'), 'REQUESTS.GET'),
        ]:
            with self.subTest(query=query):
                results = match_fxns([item], query, 5)
                self.assertEqual([r['name'] for r in results], [item['name']])

    def test_limit_keeps_best_result(self):
        results = match_fxns([record('fetch_more'), record('fetch')], 'fetch', 1)
        self.assertEqual([r['name'] for r in results], ['fetch'])

    def test_no_match_returns_empty_list(self):
        self.assertEqual(match_fxns([record('fetch')], 'unrelated', 5), [])

    def test_empty_index_returns_empty_list(self):
        self.assertEqual(match_fxns([], 'fetch', 5), [])


class FileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, relative, source):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding='utf-8')
        return str(path)

    def test_extracts_source_docstring_and_line_numbers(self):
        source = '\ndef greet(name):\n    """Say hello."""\n    return name\n'
        path = self.write('sample.py', source)
        self.assertEqual(process_file(path), [{
            'name': 'greet', 'path': path, 'start-line': 2, 'end-line': 4,
            'docstring': 'Say hello.', 'source': source.strip(),
        }])

    def test_extracts_methods_nested_and_async_functions(self):
        path = self.write('sample.py',
            'def outer():\n    def inner():\n        pass\n'
            'class Client:\n    def fetch(self):\n        pass\n'
            '    async def send(self):\n        pass\n'
            'async def run():\n    pass\n')
        results = process_file(path)
        self.assertCountEqual([r['name'] for r in results],
                              ['outer', 'inner', 'fetch', 'send', 'run'])
        self.assertTrue(all(r['docstring'] == '' for r in results))

    def test_empty_python_and_non_python_files_return_no_functions(self):
        for filename, source in [('empty.py', ''), ('notes.txt', 'def fake():\n    pass\n')]:
            with self.subTest(filename=filename):
                self.assertEqual(process_file(self.write(filename, source)), [])

    def test_invalid_missing_and_undecodable_files_are_reported(self):
        invalid = self.write('broken.py', 'def broken(:\n')
        undecodable = self.root / 'bytes.py'
        undecodable.write_bytes(b'\xff\xfe\xff')
        for path in [invalid, str(self.root / 'missing.py'), str(undecodable)]:
            with self.subTest(path=path), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(process_file(path), [])
                self.assertTrue(output.getvalue().strip())

    def test_permission_error_is_reported(self):
        # Mock the failure because chmod behaves differently across environments.
        with patch('builtins.open', side_effect=PermissionError('denied')):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(process_file('private.py'), [])
                self.assertIn('denied', output.getvalue())

    def test_scans_nested_folders_and_accepts_single_file(self):
        first = self.write('first.py', 'def first():\n    pass\n')
        self.write('nested/second.py', 'def second():\n    pass\n')
        self.assertCountEqual([r['name'] for r in process_file_or_dir(str(self.root))],
                              ['first', 'second'])
        self.assertEqual([r['name'] for r in process_file_or_dir(first)], ['first'])

    def test_skips_excluded_folders_at_multiple_depths(self):
        self.write('keep.py', 'def keep():\n    pass\n')
        for folder in ['.git', '.venv', 'venv', '__pycache__', '.idea']:
            for prefix in ['', 'nested/']:
                self.write(f'{prefix}{folder}/hidden.py', 'def hidden():\n    pass\n')
        self.assertEqual([r['name'] for r in process_file_or_dir(str(self.root))], ['keep'])

    def test_broken_file_does_not_stop_folder_scan(self):
        self.write('broken.py', 'def broken(:\n')
        self.write('valid.py', 'def valid():\n    pass\n')
        with contextlib.redirect_stdout(io.StringIO()) as output:
            results = process_file_or_dir(str(self.root))
        self.assertEqual([r['name'] for r in results], ['valid'])
        self.assertTrue(output.getvalue().strip())

    def test_cli_search_displays_location_and_source(self):
        path = self.write('sample.py', 'def fetch():\n    return 42\n')
        result = self.run_cli(path, 'fetch')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(path, result.stdout)
        self.assertIn('lines 1 - 2', result.stdout)
        self.assertIn('return 42', result.stdout)

    def test_cli_reports_no_matches(self):
        path = self.write('sample.py', 'def fetch():\n    pass\n')
        result = self.run_cli(path, 'unrelated')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Function not found', result.stdout)

    def test_cli_rejects_invalid_limits(self):
        for limit in ['0', '-1', 'abc']:
            with self.subTest(limit=limit):
                result = self.run_cli(str(self.root), 'fetch', '--limit', limit)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('error:', result.stderr)

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, str(PROJECT_ROOT / 'src/main.py'), *args],
            capture_output=True, text=True, cwd=PROJECT_ROOT, timeout=10,
        )


if __name__ == '__main__':
    unittest.main()
