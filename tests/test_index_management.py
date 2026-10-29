import contextlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, select, func

from src import database as db, main
from src.index_management import get_function, list_index, remove_index
from src.models import Base, Collection, File, Function


class IndexManagementTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.engine = create_engine('sqlite://')
        self.addCleanup(self.engine.dispose)
        self.enterContext(patch.object(db, 'engine', self.engine))
        self.enterContext(patch.object(main, 'get_code_embedding', return_value=[1., 0.]))
        Base.metadata.create_all(self.engine)
        self.source = self.root / 'a.py'
        self.source.write_text('def demo():\n    return 1\n')
        main.update_index(self.root)

    def test_list_hierarchy_and_scoped_functions(self):
        records = list_index(str(self.root), 'a.py')
        self.assertEqual(records[0]['root'], str(self.root))
        self.assertEqual(records[0]['files'][0]['functions'][0]['name'], 'demo')
        with self.assertRaises(ValueError):
            list_index(str(self.root), '../outside.py')

    def test_remove_function_and_reindex_restores_it(self):
        function = list_index()[0]['files'][0]['functions'][0]
        remove_index(function_id=function['id'])
        self.assertEqual(list_index()[0]['files'][0]['functions'], [])
        with db.get_db() as session:
            self.assertIsNone(session.scalar(select(File)).content_hash)
        self.assertEqual(main.update_index(self.root)['changed'], 1)
        self.assertEqual(len(list_index()[0]['files'][0]['functions']), 1)
        self.assertTrue(self.source.exists())

    def test_remove_file_and_collection_cascade(self):
        remove_index(str(self.root), 'a.py')
        self.assertEqual(list_index()[0]['files'], [])
        main.update_index(self.root)
        remove_index(str(self.root))
        self.assertEqual(list_index(), [])
        with db.get_db() as session:
            for model in (Collection, File, Function):
                self.assertEqual(session.scalar(select(func.count()).select_from(model)), 0)
        self.assertTrue(self.source.exists())

    def test_ambiguous_name_does_not_delete(self):
        self.source.write_text('class A:\n    def demo(self): pass\nclass B:\n    def demo(self): pass\n')
        main.update_index(self.root)
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            remove_index(str(self.root), 'a.py', 'demo')
        self.assertEqual(len(list_index()[0]['files'][0]['functions']), 2)

    def test_named_removal_and_invalid_selectors(self):
        for kwargs in ({}, {'function': 'demo'}, {'function_id': 1, 'collection': str(self.root)}, {'function_id': 999}):
            with self.assertRaises(ValueError):
                remove_index(**kwargs)
        remove_index(str(self.root), 'a.py', 'demo')
        self.assertEqual(list_index()[0]['files'][0]['functions'], [])

    def test_direct_absolute_and_relative_file_listing(self):
        self.assertEqual(list_index(file=str(self.source))[0]['files'][0]['path'], 'a.py')
        with contextlib.chdir(self.root):
            self.assertEqual(list_index(file='./a.py')[0]['files'][0]['functions'][0]['name'], 'demo')
        self.source.unlink()
        self.assertEqual(list_index(file=str(self.source))[0]['files'][0]['path'], 'a.py')
        with self.assertRaisesRegex(ValueError, 'File not indexed'):
            list_index(file=str(self.root / 'missing.py'))

    def test_direct_file_and_named_function_removal(self):
        with contextlib.chdir(self.root):
            remove_index(file='./a.py', function='demo')
        self.assertEqual(list_index(file=str(self.source))[0]['files'][0]['functions'], [])
        main.update_index(self.root)
        remove_index(file=str(self.source))
        self.assertEqual(list_index()[0]['files'], [])
        self.assertTrue(self.source.exists())

    def test_overlapping_collections_require_explicit_root(self):
        nested = self.root / 'nested'
        nested.mkdir()
        self.source = nested / 'b.py'
        self.source.write_text('def demo(): return 1\n')
        main.update_index(self.root)
        main.update_index(nested)
        for operation in (list_index, remove_index):
            with self.assertRaisesRegex(ValueError, 'multiple collections'):
                operation(file=str(self.source))
        self.assertEqual(len(list_index()), 2)
        self.assertEqual(list_index(str(self.root), 'nested/b.py')[0]['files'][0]['path'], 'nested/b.py')

    def test_function_id_lookup_and_cli(self):
        import io
        import sys
        function_id = list_index()[0]['files'][0]['functions'][0]['id']
        record = get_function(function_id)
        self.assertEqual(record['source'], 'def demo():\n    return 1')
        database_path = self.root / 'exists.db'
        database_path.touch()
        for command in ('list', 'search'):
            with patch.object(main, 'DATABASE_PATH', database_path), patch.object(sys, 'argv', ['recall', command, '--function-id', str(function_id)]):
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    main.main()
                self.assertIn(str(self.source), output.getvalue())
                self.assertIn('return 1', output.getvalue())
        for function_id in (-1, 999):
            with self.assertRaises(ValueError):
                get_function(function_id)

    def test_id_lookup_rejects_conflicting_selectors(self):
        import sys
        for command in ('list', 'search'):
            with patch.object(sys, 'argv', ['recall', command, '--function-id', '1', '--file', 'a.py']):
                with contextlib.redirect_stderr(__import__('io').StringIO()):
                    with self.assertRaises(SystemExit) as error:
                        main.main()
                self.assertEqual(error.exception.code, 2)
