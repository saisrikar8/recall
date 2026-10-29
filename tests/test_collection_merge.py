"""Collection consolidation regression tests; no model or saved index required."""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, event, select

from src import database as db, main
from src.models import Base, Collection, File, Function


class CollectionMergeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.engine = create_engine('sqlite://')
        event.listen(self.engine, 'connect', db.register_functions)
        self.addCleanup(self.engine.dispose)
        self.enterContext(patch.object(db, 'engine', self.engine))
        self.embed = self.enterContext(patch.object(main, 'get_code_embedding', return_value=[1., 0.]))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        Base.metadata.create_all(self.engine)

    def write(self, name):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('def demo():\n    return 1\n')
        return path

    def snapshot(self):
        with db.get_db() as session:
            return [(f.id, f.collection.root_path, f.relative_path,
                     [(x.id, x.embedding) for x in f.functions])
                    for f in session.scalars(select(File).order_by(File.relative_path))]

    def roots(self):
        with db.get_db() as session:
            return sorted(session.scalars(select(Collection.root_path)))

    def test_children_merge_into_parent_preserving_ids_and_embeddings(self):
        a = self.write('project/homework/a.py')
        b = self.write('project/labs/b.py')
        main.update_index(a.parent)
        main.update_index(b.parent)
        before = self.snapshot()
        self.embed.reset_mock()
        counts = main.update_index(a.parent.parent)
        self.assertEqual(self.roots(), [str(a.parent.parent)])
        self.assertEqual(counts['unchanged'], 2)
        self.embed.assert_not_called()
        after = self.snapshot()
        self.assertEqual({x[0] for x in before}, {x[0] for x in after})
        self.assertEqual({x[3][0][0] for x in before}, {x[3][0][0] for x in after})
        self.assertEqual({x[2] for x in after}, {'homework/a.py', 'labs/b.py'})
        self.assertTrue(all(x[3][0][1] == [1., 0.] for x in after))

    def test_subfolder_reuses_parent_and_preserves_siblings(self):
        a = self.write('project/homework/a.py')
        self.write('project/labs/b.py')
        main.update_index(a.parent.parent)
        before = self.snapshot()
        self.embed.reset_mock()
        main.update_index(a.parent)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.roots(), [str(a.parent.parent)])
        self.embed.assert_not_called()

    def test_subfolder_deletion_preserves_siblings(self):
        a = self.write('project/homework/a.py')
        self.write('project/labs/b.py')
        main.update_index(a.parent.parent)
        a.unlink()
        counts = main.update_index(a.parent)
        self.assertEqual(counts['deleted'], 1)
        self.assertEqual([x[2] for x in self.snapshot()], ['labs/b.py'])

    def test_single_file_update_preserves_siblings(self):
        a = self.write('project/a.py')
        self.write('project/b.py')
        main.update_index(a.parent)
        a.write_text('def changed(): return 2\n')
        main.update_index(a)
        self.assertEqual([x[2] for x in self.snapshot()], ['a.py', 'b.py'])
        self.assertEqual(self.roots(), [str(a.parent)])

    def test_unrelated_and_similarly_named_roots_remain_separate(self):
        for name in ('project', 'project-old', 'other'):
            file = self.write(f'{name}/a.py')
            main.update_index(file.parent)
        self.assertEqual(len(self.roots()), 3)

    def test_legacy_overlapping_children_deduplicate(self):
        a = self.write('project/homework/a.py')
        main.update_index(a.parent)
        # Seed overlap directly: legacy releases allowed nested collections.
        with db.get_db() as session, session.begin():
            legacy = Collection(root_path=str(self.root / 'project'))
            session.add(legacy)
            original = session.scalar(select(File))
            duplicate = File(collection=legacy, relative_path='homework/a.py', content_hash=original.content_hash)
            session.add(duplicate)
            session.add(Function(file=duplicate, name='demo', start_line=1, end_line=2,
                                 docstring='', source='def demo():\n    return 1',
                                 embedding=[1., 0.], embedding_model=main.DEFAULT_MODEL))
        main.update_index(self.root)
        self.assertEqual(self.roots(), [str(self.root)])
        self.assertEqual(len(self.snapshot()), 1)
        self.assertEqual(len(self.snapshot()[0][3]), 1)

    def _conflicting_merge(self, copies):
        source = self.write('project/homework/nested/a.py')
        main.update_index(source.parent)
        parents = [self.root / 'project', self.root / 'project/homework'][:copies - 1]
        with db.get_db() as session, session.begin():
            for number, parent in enumerate(parents):
                collection = Collection(root_path=str(parent))
                session.add(collection)
                file = File(collection=collection,
                            relative_path=str(source.relative_to(parent)),
                            content_hash=f'outdated-{number}')
                session.add(file)
                session.add(Function(file=file, name='old', start_line=1, end_line=2,
                                     docstring='', source='def old(): pass',
                                     embedding=[0., 1.], embedding_model=main.DEFAULT_MODEL))
        main.update_index(self.root)
        records = self.snapshot()
        self.assertEqual(len(records), 1)
        self.assertEqual(len(records[0][3]), 1)
        with db.get_db() as session:
            self.assertEqual(session.scalar(select(Function.name)), 'demo')

    def test_conflicting_hashes_rebuild_from_disk(self):
        self._conflicting_merge(2)

    def test_three_conflicting_copies_rebuild_once(self):
        self._conflicting_merge(3)

    def test_progress_is_printed_before_embedding_and_for_unchanged_files(self):
        self.write('project/a.py')
        self.write('project/b.py')
        with contextlib.redirect_stdout(io.StringIO()) as output:
            def encode(source):
                self.assertIn('Processing', output.getvalue())
                return [1., 0.]
            self.embed.side_effect = encode
            main.update_index(self.root / 'project')
        text = output.getvalue()
        self.assertIn('Discovered 2 Python files', text)
        self.assertIn('[1/2] Processing a.py', text)
        self.assertIn('[2/2] Processing b.py', text)
        self.embed.reset_mock()
        with contextlib.redirect_stdout(io.StringIO()) as output:
            main.update_index(self.root / 'project')
        self.assertIn('[1/2] Skipped unchanged a.py', output.getvalue())
        self.assertIn('[2/2] Skipped unchanged b.py', output.getvalue())
        self.embed.assert_not_called()
