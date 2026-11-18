import unittest
from unittest.mock import Mock,patch
import numpy as np
from src import document_search


class DocumentSearchTests(unittest.TestCase):
    def test_document_and_query_prefixes_use_matching_model(self):
        model=Mock();model.encode.return_value=np.array([[1.,0.]])
        with patch.object(document_search,'_encoder',model):
            document_search.encode_documents(['Lecture passage'])
            self.assertEqual(model.encode.call_args.args[0],['passage: Lecture passage'])
            self.assertTrue(model.encode.call_args.kwargs['normalize_embeddings'])
            document_search.encode_query('Where are eigenvalues?')
            self.assertEqual(model.encode.call_args.args[0],'query: Where are eigenvalues?')

    def test_empty_inputs_do_not_load_models(self):
        with patch.object(document_search,'_encoder',None), \
             patch.object(document_search,'_reranker',None),patch.object(document_search,'_image_reranker',None):
            self.assertEqual(document_search.encode_documents([]).shape,(0,384))
            self.assertEqual(document_search.rerank_text('q',[]),[])
            self.assertEqual(document_search.rerank_images('q',[]),[])
            self.assertIsNone(document_search._encoder)
            self.assertIsNone(document_search._reranker)
            self.assertIsNone(document_search._image_reranker)

    def test_text_reranker_scores_query_document_pairs(self):
        model=Mock();model.predict.return_value=np.array([2.,-1.])
        with patch.object(document_search,'_reranker',model):
            self.assertEqual(document_search.rerank_text('question',['one','two']),[2.,-1.])
            self.assertEqual(model.predict.call_args.args[0],[('question','one'),('question','two')])

    def test_image_reranker_preserves_multimodal_document_and_bounds_batch(self):
        image=object();document={'image':image,'text':'caption'}
        model=Mock();model.predict.return_value=np.array([1.2])
        with patch.object(document_search,'_image_reranker',model):
            self.assertAlmostEqual(document_search.rerank_images('query',[document])[0],1.2)
            self.assertIs(model.predict.call_args.args[0][0][1]['image'],image)
            self.assertEqual(model.predict.call_args.kwargs['batch_size'],1)
