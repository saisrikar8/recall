import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from sqlalchemy import create_engine,event,select
from src import database as db,indexing
from src.models import File
from src.search_signals import terms,excluded_file_ids,reference_chunks

class SearchSignalsTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name).resolve()
        engine=create_engine('sqlite://');self.addCleanup(engine.dispose)
        event.listen(engine,'connect',db.register_functions)
        self.enterContext(patch.object(db,'engine',engine))
        self.enterContext(patch.object(indexing,'get_code_embedding',return_value=[1.,0.]))
        self.enterContext(patch('src.semantic_search.get_query_embedding',return_value=[1.,0.]))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
    def write(self,name,body):
        path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(body);return path
    def test_comparison_words_do_not_block_keyword_hits(self):
        self.assertEqual(terms('What is the difference between append vs extend?'),['append','extend'])
    def test_new_exclusion_policy_filters_old_records_without_deleting_them(self):
        self.write('build/vendor.py','def generated(): return 1')
        self.write('main.py','def useful(): return 2')
        indexing.update_index(self.root)
        self.write('gleam.toml','name = "example"')
        with db.get_db() as s:
            excluded=excluded_file_ids(s,str(self.root))
            self.assertEqual([s.get(File,i).relative_path for i in excluded],['build/vendor.py'])
            self.assertEqual(len(s.scalars(select(File)).all()),2)
    def test_numbered_tests_link_to_their_implementation_with_provenance(self):
        self.write('garden/tests/q07.py','def problem_07():\n    """Testing Basket. Basket() Basket() Helper()"""\n    pass\n')
        self.write('garden/main.py','class Basket:\n    """Holds fruit."""\n    pass\n\nclass Helper:\n    pass\n')
        indexing.update_index(self.root)
        with db.get_db() as s:
            refs=reference_chunks(s,'what is question 7 in garden',str(self.root))
        self.assertTrue(refs)
        self.assertTrue(all(value['path'].endswith('garden/tests/q07.py') for value in refs.values()))
        self.assertEqual(max(value['strength'] for value in refs.values()),1)

    def test_comparison_prefers_explanatory_notes_over_exercise_tests(self):
        from src.retrieval import search
        self.write('notes.md','## Mutable containers\nappend adds one item. extend adds all items from a sequence.\n')
        self.write('tests/q01.py','def check():\n    """append and extend tests"""\n    pass\n')
        indexing.update_index(self.root)
        result=search('append vs extend')
        self.assertEqual(result[0]['relative_path'],'notes.md')

    def test_exact_filename_returns_file_overview(self):
        from src.retrieval import search
        self.write('main.py','def answer(): return 42\n')
        self.write('other.py','def unrelated(): return 0\n')
        indexing.update_index(self.root)
        with patch('src.semantic_search.get_query_embedding',side_effect=AssertionError('Filename lookup must not invoke models')):
            result=search('main.py')
        self.assertEqual((result[0]['relative_path'],result[0]['kind']),('main.py','file'))
