import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from sqlalchemy import create_engine,event
from src import database as db,indexing
from src.index_progress import IndexProgress
from src.ui import Jobs

class IndexProgressTests(unittest.TestCase):
    def test_folder_counts_advance_only_when_files_finish(self):
        events=[]
        def report(message):pass
        report.event=events.append
        progress=IndexProgress(['/tmp/root/a/x.py','/tmp/root/a/b/y.py'],'/tmp/root',report)
        progress.begin('/tmp/root/a/x.py');progress.report('Text embeddings /tmp/root/a/x.py: 10 passages')
        self.assertEqual(events[-1]['completed'],0)
        progress.finish('/tmp/root/a/x.py','new')
        self.assertEqual(events[-1]['completed'],1)
        self.assertEqual(events[-1]['revision'],1)
        progress.finish('/tmp/root/a/b/y.py','failed');progress.done()
        self.assertEqual(events[-1]['completed'],2)
        folders={row['path']:row for row in events[-1]['folders']}
        self.assertEqual((folders['a']['completed'],folders['a']['failed']),(2,1))
        self.assertEqual(folders['a/b']['failed'],1)
        self.assertEqual(events[0]['completed'],0) # Old snapshots never mutate.

    def test_files_are_published_and_visible_before_indexing_finishes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            (root/'a').mkdir();(root/'a/one.py').write_text('def first(): return 1')
            (root/'b').mkdir();(root/'b/two.py').write_text('def second(): return 2')
            engine=create_engine('sqlite://');event.listen(engine,'connect',db.register_functions)
            published=[]
            def report(message):pass
            def observe(progress):
                if progress['revision']:
                    from src.desktop_bridge import library
                    published.append((progress['completed'],len(library()['files'])))
            report.event=observe
            with patch.object(db,'engine',engine),patch.object(indexing,'get_code_embedding',return_value=[1.,0.]):
                result=indexing.update_index(root,report=report)
            self.assertEqual(result['new'],2)
            self.assertIn((1,1),published)
            self.assertIn((2,2),published)
            engine.dispose()
