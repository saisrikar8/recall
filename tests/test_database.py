import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.exc import IntegrityError

from src import database as db
from src.models import Collection, File, Function

def function(name='fetch', start=1, end=3, docstring='', source=None):
    return {'name': name, 'start-line': start, 'end-line': end,
            'docstring': docstring,
            'source': source if source is not None else f'def {name}():\n    pass'}


def file_index(*functions, fingerprint='hash-one'):
    return {'hash': fingerprint, 'functions': list(functions)}


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.enterContext(contextlib.chdir(self.root))
        self.engine = create_engine(f'sqlite:///{self.root / "index/index.db"}')
        event.listen(self.engine, 'connect', db.register_functions)
        self.enterContext(patch.object(db.semantic_search, 'get_query_embedding', return_value=[1., 0.]))
        self.addCleanup(self.engine.dispose)
        self.enterContext(patch.object(db, 'engine', self.engine))
        db.initialize_database()
        self.collection_root = str(self.root / 'project')

    def seed(self, *functions):
        db.init_index({'root': self.collection_root,
                       'files': {'a.py': file_index(*functions)}})

    def snapshot(self):
        with db.get_db() as session:
            return [(f.relative_path, f.content_hash, f.last_error,
                     [(x.name, x.start_line, x.end_line, x.docstring, x.source)
                      for x in sorted(f.functions, key=lambda x: x.start_line)])
                    for f in session.scalars(select(File).order_by(File.relative_path))]

    def test_initialization_is_repeatable(self):
        self.seed(function())
        before = self.snapshot()
        db.initialize_database()
        self.assertEqual(set(inspect(self.engine).get_table_names()),
                         {'collections', 'files', 'functions'})
        self.assertEqual(self.snapshot(), before)

    def test_init_index_persists_relationships(self):
        self.seed(function(), function('save', 5, 8))
        with db.get_db() as session:
            collection = session.scalar(select(Collection))
            self.assertEqual(collection.root_path, self.collection_root)
            self.assertEqual(len(collection.files), 1)
            file = collection.files[0]
            self.assertEqual(file.relative_path, 'a.py')
            self.assertEqual(file.content_hash, 'hash-one')
            self.assertCountEqual([f.name for f in file.functions], ['fetch', 'save'])
            self.assertTrue(all(f.file is file for f in file.functions))

    def test_process_file_index_does_not_commit_callers_transaction(self):
        with db.get_db() as session:
            collection = Collection(root_path=self.collection_root)
            session.add(collection)
            db.process_file_index(session, collection, file_index(function()), 'a.py')
            session.flush()
            session.rollback()
        with db.get_db() as session:
            self.assertIsNone(session.scalar(select(Collection)))
            self.assertIsNone(session.scalar(select(Function)))

    def test_add_file_preserves_existing_file(self):
        self.seed(function())
        db.add_file(self.collection_root, 'b.py', file_index(function('other')))
        self.assertEqual([row[0] for row in self.snapshot()], ['a.py', 'b.py'])

    def test_duplicate_file_is_rejected_without_partial_insert(self):
        self.seed(function())
        before = self.snapshot()
        with self.assertRaises(IntegrityError):
            db.add_file(self.collection_root, 'a.py', file_index(function('duplicate')))
        self.assertEqual(self.snapshot(), before)

    def test_init_index_rolls_back_on_invalid_function(self):
        invalid = function()
        del invalid['source']
        with self.assertRaises(KeyError):
            self.seed(function('valid'), invalid)
        with db.get_db() as session:
            self.assertIsNone(session.scalar(select(Collection)))
            self.assertIsNone(session.scalar(select(File)))

    def test_update_replaces_fields_adds_and_removes_functions(self):
        self.seed(function(), function('obsolete', 5, 8))
        db.update_file(file_index(
            function('renamed', docstring='updated', source='return 42'),
            function('new', 10, 12), fingerprint='hash-two'), self.collection_root, 'a.py')
        row = self.snapshot()[0]
        self.assertEqual(row[1], 'hash-two')
        self.assertEqual(row[3], [('renamed', 1, 3, 'updated', 'return 42'),
                                  ('new', 10, 12, '', 'def new():\n    pass')])

    def test_update_handles_moved_function(self):
        self.seed(function())
        db.update_file(file_index(function(start=7, end=9)), self.collection_root, 'a.py')
        self.assertEqual(self.snapshot()[0][3][0][1:3], (7, 9))
        self.assertEqual(len(self.snapshot()[0][3]), 1)

    def test_update_to_empty_file_removes_all_functions(self):
        self.seed(function())
        db.update_file(file_index(fingerprint='empty'), self.collection_root, 'a.py')
        self.assertEqual(self.snapshot()[0][1], 'empty')
        self.assertEqual(self.snapshot()[0][3], [])

    def test_update_clears_error_and_sets_timestamp(self):
        self.seed(function())
        with db.get_db() as session:
            file = session.scalar(select(File))
            file.last_error = 'previous failure'
            file.indexed_at = None
            session.commit()
        db.update_file(file_index(function()), self.collection_root, 'a.py')
        with db.get_db() as session:
            file = session.scalar(select(File))
            self.assertIsNone(file.last_error)
            self.assertIsNotNone(file.indexed_at)

    def test_update_missing_file_inserts_it(self):
        self.seed(function())
        with contextlib.redirect_stdout(io.StringIO()):
            db.update_file(file_index(function('second')), self.collection_root, 'b.py')
        self.assertEqual(len(self.snapshot()), 2)

    def test_update_missing_collection_leaves_database_unchanged(self):
        self.seed(function())
        before = self.snapshot()
        with contextlib.redirect_stdout(io.StringIO()) as output:
            db.update_file(file_index(function()), '/missing', 'a.py')
        self.assertIn("doesn't exist", output.getvalue())
        self.assertEqual(self.snapshot(), before)

    def test_failed_update_rolls_back_hash_and_function_deletions(self):
        self.seed(function(), function('old', 5, 8))
        before = self.snapshot()
        invalid = function('broken', 10, 12)
        del invalid['source']
        with self.assertRaises(KeyError):
            db.update_file(file_index(invalid, fingerprint='bad'), self.collection_root, 'a.py')
        self.assertEqual(self.snapshot(), before)

    def test_search_ranks_vectors_and_respects_limit(self):
        self.seed(function('weak'), function('strong', 5, 8))
        with db.get_db() as session:
            for f in session.scalars(select(Function)):
                f.embedding = [1., 0.] if f.name == 'strong' else [.6, .8]
                f.embedding_model = db.semantic_search.DEFAULT_MODEL
            session.commit()
        results = db.search_db('query', limit=1)
        self.assertEqual([r['name'] for r in results], ['strong'])
        self.assertAlmostEqual(results[0]['score'], 1.)

    def test_search_returns_source_location(self):
        self.seed(function(docstring='Download a resource'))
        with db.get_db() as session:
            f = session.scalar(select(Function))
            f.embedding = [1., 0.]
            f.embedding_model = db.semantic_search.DEFAULT_MODEL
            session.commit()
        result = db.search_db('download')[0]
        self.assertEqual(result['path'], str(Path(self.collection_root) / 'a.py'))
        self.assertEqual(result['relative_path'], 'a.py')
        self.assertEqual(result['start-line'], 1)
        self.assertEqual(result['end-line'], 3)
        self.assertEqual(result['docstring'], 'Download a resource')
        self.assertEqual(result['source'], 'def fetch():\n    pass')

    def test_search_empty_database(self):
        self.assertEqual(db.search_db('fetch'), [])

    def test_search_ignores_functions_without_embeddings(self):
        self.seed(function())
        self.assertEqual(db.search_db('fetch'), [])


if __name__ == '__main__':
    unittest.main()
