import unittest
from unittest.mock import patch, MagicMock

from src.desktop_warmup import warmup_models


class DesktopWarmupTests(unittest.TestCase):
    def setUp(self):
        context = MagicMock()
        self.session = context.__enter__.return_value
        self.enterContext(patch('src.desktop_warmup.db.get_db', return_value=context))
        self.text = self.enterContext(patch('src.semantic_search.get_query_embedding', return_value=[1.]))
        self.document = self.enterContext(patch('src.visual.embed_query', return_value=[[1.]]))
        self.enterContext(patch('src.document_search.rerank_text',return_value=[1.]))
        self.scene = self.enterContext(patch('src.scene_search.encode_query', return_value=[1.]))

    def test_empty_library_warms_text_without_image_models(self):
        self.session.scalar.side_effect = [None, None, None]
        status = warmup_models()
        self.assertEqual(status['channels'], {'text': 'ready'})
        self.text.assert_called_once()
        self.document.assert_not_called()
        self.scene.assert_not_called()
        self.assertGreater(status['worker_rss_mib'], 0)

    def test_visual_library_warms_each_search_channel(self):
        self.session.scalar.side_effect = [1, 2, 1]
        status = warmup_models()
        self.assertEqual(status['channels'], {'text':'ready','reranker':'ready','document':'ready','scene':'ready'})
        self.document.assert_called_once()
        self.scene.assert_called_once()

    def test_failed_channel_does_not_block_other_channels(self):
        self.session.scalar.side_effect = [1, 2, 1]
        self.text.side_effect = RuntimeError('Offline download')
        with self.assertLogs('src.desktop_warmup', level='WARNING'):
            status = warmup_models()
        self.assertEqual(status['channels']['text'], 'unavailable')
        self.assertEqual(status['channels']['scene'], 'ready')
