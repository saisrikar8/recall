import contextlib
import io
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import main
from src.main import match_fxns


def process_file(path):
    return [{k: v for k, v in f.items() if k not in {'embedding', 'embedding-model'}}
            for entry in main.process_file(path).values() for f in entry['functions']]


def process_file_or_dir(path):
    return [f for entry in main.process_file_or_dir(path).values() for f in entry["functions"]]


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
        self.root = Path(self.temp.name).resolve()
        self.enterContext(patch.object(main, 'get_code_embedding', return_value=[1., 0.]))

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


class CLITests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        # Copy only source: run the real module from a clean project root.
        shutil.copytree(PROJECT_ROOT / 'src', self.root / 'src',
                        ignore=shutil.ignore_patterns('__pycache__'))

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def run_cli(self, *args):
        env = os.environ.copy()
        env.pop('PYTHONPATH', None)
        env['RECALL_DB_PATH'] = str(self.root / 'index/index.db')
        return subprocess.run([sys.executable, '-m', 'src.main', *args],
                              cwd=self.root, env=env, capture_output=True,
                              text=True, timeout=10)

    def success(self, *args):
        result = self.run_cli(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('Traceback', result.stderr)
        return result.stdout

    def search(self, query, *args):
        return self.success('search', '-q', query, *args)

    def snapshot(self):
        with contextlib.closing(sqlite3.connect(self.root / 'index/index.db')) as db:
            return {table: db.execute(f'SELECT * FROM {table} ORDER BY id').fetchall()
                    for table in ('collections', 'files', 'functions')}

    def test_index_then_search_saved_source(self):
        path = self.write('repo/a.py', 'def fetch():\n    return 42\n')
        self.success('index', '-f', 'repo')
        self.assertTrue((self.root / 'index/index.db').is_file())
        path.unlink()
        output = self.search('fetch')
        self.assertIn('sample.py' if path.name == 'sample.py' else path.name, output)
        self.assertIn('a.py:1-2', output)
        self.assertIn('return 42', output)

    def test_edit_reindex_and_delete(self):
        path = self.write('repo/a.py', 'def original():\n    return 1\n')
        self.success('index', '-f', 'repo')
        self.assertIn('1 unchanged', self.success('index', '-f', 'repo'))
        path.write_text('def replacement():\n    return 99\n')
        self.assertIn('1 changed', self.success('index', '-f', 'repo'))
        self.assertIn('return 99', self.search('replacement'))
        self.assertNotIn('  original\n', self.search('original'))
        path.unlink()
        self.assertIn('1 deleted', self.success('index', '-f', 'repo'))
        self.assertIn('Function not found', self.search('replacement'))
        self.assertEqual(self.snapshot()['functions'], [])

    def test_broken_file_preserves_results_and_retries(self):
        path = self.write('repo/a.py', 'def original():\n    pass\n')
        self.success('index', '-f', 'repo')
        before = self.snapshot()
        path.write_text('def broken(:\n')
        for _ in range(2):
            self.assertIn('1 failed', self.success('index', '-f', 'repo'))
            self.assertIn('original', self.search('original'))
            after = self.snapshot()
            self.assertEqual(after['functions'], before['functions'])
            self.assertEqual(after['files'][0][3], before['files'][0][3])
        path.write_text('def repaired():\n    pass\n')
        self.assertIn('1 changed', self.success('index', '-f', 'repo'))
        self.assertIn('repaired', self.search('repaired'))
        self.assertNotIn('  original\n', self.search('original'))

    def test_single_file_update_preserves_siblings(self):
        path = self.write('repo/a.py', 'def first():\n    pass\n')
        self.write('repo/b.py', 'def sibling():\n    pass\n')
        self.success('index', '-f', 'repo')
        path.write_text('def edited():\n    pass\n')
        self.success('index', '-f', 'repo/a.py')
        self.assertIn('edited', self.search('edited'))
        self.assertIn('sibling', self.search('sibling'))
        self.assertIn('1 unchanged', self.success('index', '-f', 'repo/a.py'))

    def test_missing_path_preserves_database(self):
        self.write('repo/a.py', 'def first():\n    pass\n')
        self.success('index', '-f', 'repo')
        before = self.snapshot()
        result = self.run_cli('index', '-f', 'missing')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('not found', result.stderr.lower())
        self.assertEqual(self.snapshot(), before)

    def test_collections_are_independent(self):
        self.write('one/a.py', 'def first():\n    pass\n')
        self.write('two/a.py', 'def second():\n    pass\n')
        self.success('index', '-f', 'one')
        self.success('index', '-f', 'two')
        self.assertIn('first', self.search('first'))
        self.assertIn('second', self.search('second'))
        self.assertEqual(len(self.snapshot()['collections']), 2)

    def test_ranking_limit_and_literal_search(self):
        self.write('repo/a.py', 'def fetch_more():\n    pass\ndef fetch():\n    pass\n')
        self.success('index', '-f', 'repo')
        output = self.search('FETCH', '--limit', '1')
        self.assertIn('  fetch\n', output)
        self.assertNotIn('fetch_more', output)
        self.assertIn('fetch_more', self.search('fetch_more', '--min-threshold', '-1'))
        self.assertIn('Function not found', self.search('unrelated', '--min-threshold', '1'))

    def test_skips_virtual_environment_and_handles_broken_new_file(self):
        self.write('repo/.venv/a.py', 'def hidden():\n    pass\n')
        self.write('repo/broken.py', 'def broken(:\n')
        self.write('repo/nested/good.py', 'async def visible():\n    pass\n')
        output = self.success('index', '-f', 'repo')
        self.assertIn('1 failed', output)
        self.assertIn('visible', self.search('visible'))
        self.assertNotIn('  hidden\n', self.search('hidden'))

    def test_rejects_invalid_arguments(self):
        for limit in ['0', '-1', 'abc']:
            with self.subTest(limit=limit):
                result = self.run_cli('search', '-q', 'fetch', '--limit', limit)
                self.assertEqual(result.returncode, 2)
                expected = 'invalid int value' if limit == 'abc' else '--limit must be at least 1'
                self.assertIn(expected, result.stderr)
        for args in [(), ('-q', ''), ('-q', '   ')]:
            with self.subTest(args=args):
                result = self.run_cli('search', *args)
                self.assertEqual(result.returncode, 2)
                self.assertIn('search requires a non-empty --query', result.stderr)

    def test_search_before_indexing_gives_actionable_message(self):
        result = self.run_cli('search', '-q', 'fetch')
        self.assertNotIn('Traceback', result.stderr)
        output = (result.stdout + result.stderr).lower()
        self.assertIn('index', output)
        self.assertIn('run', output, 'Tell the user to run indexing first')

    def test_corrupted_database_is_reported_without_traceback(self):
        path = self.write('index/index.db', 'not a sqlite database')
        result = self.run_cli('search', '-q', 'fetch')
        self.assertNotIn('Traceback', result.stderr)
        self.assertIn('database', (result.stdout + result.stderr).lower())
        self.assertEqual(path.read_text(), 'not a sqlite database')


if __name__ == '__main__':
    unittest.main()
