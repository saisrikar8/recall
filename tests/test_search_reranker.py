import unittest
from unittest.mock import MagicMock,patch
from src import search_reranker

class SearchRerankerTests(unittest.TestCase):
    def setUp(self):
        self.session=MagicMock();self.session.execute.return_value.all.return_value=[(1,'First text'),(2,'Second text')]
        self.rows=[dict(chunk_id=i,relative_path=f'{i}.md',name=str(i),source='Snippet') for i in [1,2]]
        self.enterContext(patch.object(search_reranker,'_retry_after',0.))
    def test_pair_scores_reorder_bounded_candidates(self):
        with patch('src.document_search.rerank_text',return_value=[-2.,3.]) as model:
            results=search_reranker.rerank(self.session,'How does this work?',self.rows)
        self.assertEqual(results[0]['chunk_id'],2)
        self.assertIn('Second text',model.call_args.args[1][1])
    def test_model_failure_keeps_search_available_and_backs_off(self):
        with patch('src.document_search.rerank_text',side_effect=RuntimeError('Offline')) as model:
            with self.assertLogs('src.search_reranker',level='WARNING'):
                self.assertEqual(search_reranker.rerank(self.session,'question',self.rows),self.rows)
            self.assertEqual(search_reranker.rerank(self.session,'question',self.rows),self.rows)
            self.assertEqual(model.call_count,1)
