import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from src import database as db, main, semantic_search as semantic
from src.models import Base, Collection, File, Function


class SemanticWorkflowTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.enterContext(contextlib.chdir(self.root))
        self.engine = create_engine('sqlite://')
        event.listen(self.engine, 'connect', db.register_functions)
        self.addCleanup(self.engine.dispose)
        self.enterContext(patch.object(db, 'engine', self.engine))
        Base.metadata.create_all(self.engine)
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.embed = self.enterContext(patch.object(main, 'get_code_embedding',
            side_effect=lambda source: [0., 1.] if 'return 2' in source else [1., 0.]))
        self.query = self.enterContext(patch.object(semantic, 'get_query_embedding', return_value=[1., 0.]))

    def index(self, source):
        path = self.root / 'repo/a.py'
        path.parent.mkdir(exist_ok=True)
        path.write_text(source)
        main.update_index(path.parent)
        return path

    def test_change_replaces_embedding_unchanged_skips_and_delete_removes(self):
        path = self.index('def demo():\n    return 1\n')
        self.assertEqual(self.embed.call_count, 1)
        main.update_index(path.parent)
        self.assertEqual(self.embed.call_count, 1)
        self.index('def demo():\n    return 2\n')
        self.assertEqual(self.embed.call_count, 2)
        with Session(self.engine) as session:
            self.assertEqual(session.scalar(select(Function)).embedding, [0., 1.])
        path.unlink()
        main.update_index(path.parent)
        with Session(self.engine) as session:
            self.assertIsNone(session.scalar(select(Function)))

    def test_cli_search_uses_configured_database_from_another_directory(self):
        path = self.index('def demo():\n    return 1\n')
        database_path = self.root / 'configured.db'
        database_path.touch()
        elsewhere = self.root / 'elsewhere'
        elsewhere.mkdir()
        with patch.object(main, 'DATABASE_PATH', database_path), contextlib.chdir(elsewhere):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                main.search_index(5, 'example', .4)
        self.assertIn('demo', output.getvalue())
        self.query.assert_called_once_with('example')

    def test_cli_search_reports_missing_configured_database(self):
        with patch.object(main, 'DATABASE_PATH', self.root / 'missing.db'):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                main.search_index(5, 'example', .4)
        self.assertIn('Index not found', output.getvalue())
        self.query.assert_not_called()

    def test_query_encoded_once_and_threshold_inclusive(self):
        self.index('def a():\n    return 1\ndef b():\n    return 2\n')
        results = db.search_db('example', threshold=1.)
        self.query.assert_called_once_with('example')
        self.assertEqual([r['name'] for r in results], ['a'])
        self.assertEqual(db.search_db('example', threshold=0., limit=1)[0]['name'], 'a')

    def test_collection_filter_and_unknown_collection(self):
        self.index('def a():\n    return 1\n')
        other = self.root / 'other'; other.mkdir()
        (other / 'b.py').write_text('def b():\n    return 1\n')
        main.update_index(other)
        results = db.search_db('example', collection=str(other))
        self.assertEqual([r['name'] for r in results], ['b'])
        self.assertEqual(results[0]['relative_path'], 'b.py')
        with self.assertRaisesRegex(ValueError, 'not indexed'):
            db.search_db('example', collection='missing')

    def test_missing_wrong_model_and_malformed_vectors_are_excluded(self):
        self.index('def a():\n    return 1\n')
        with Session(self.engine) as session:
            f = session.scalar(select(Function))
            f.embedding_model = 'another-model'; session.commit()
        self.assertEqual(db.search_db('example'), [])
        for vector in [None, [], [1.], [0., 0.]]:
            with Session(self.engine) as session:
                f = session.scalar(select(Function))
                f.embedding_model = semantic.DEFAULT_MODEL
                f.embedding = vector; session.commit()
            self.assertEqual(db.search_db('example'), [])

    def test_update_helper_invalidates_stale_embedding(self):
        path = self.index('def a():\n    return 1\n')
        record = {'hash': 'changed', 'functions': [{'name':'a', 'start-line':1,
                  'end-line':2, 'docstring':'', 'source':'def a():\n    return 2'}]}
        db.update_file(record, str(path.parent), path.name)
        with Session(self.engine) as session:
            f = session.scalar(select(Function))
            self.assertIsNone(f.embedding)
            self.assertIsNone(f.embedding_model)

    def test_preview_is_bounded(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            main.print_fxn({'path':'/repo/a.py', 'relative_path':'a.py', 'name':'a',
                            'start-line':1,'end-line':10,'score':.875,
                            'source':'\n'.join(str(i) for i in range(10))})
        text = output.getvalue()
        self.assertIn('0.875  a.py:1-10', text)
        self.assertIn('…', text)
        self.assertNotIn('    9', text)

    def test_pure_similarity_edges(self):
        self.assertEqual(semantic.vector_similarity('[1,0]', '[1,0]'), 1.)
        self.assertEqual(semantic.vector_similarity('[1,0]', '[-1,0]'), -1.)
        for value in ['null', '[]', '[0,0]', '[1]', 'invalid']:
            self.assertIsNone(semantic.vector_similarity('[1,0]', value))

    def test_threshold_validation(self):
        for threshold in [2., -2., float('nan')]:
            with self.assertRaises(ValueError):
                db.search_db('example', threshold=threshold)
