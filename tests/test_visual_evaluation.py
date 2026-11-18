"""Ranking and corpus preparation tests without model downloads."""
import json
from pathlib import Path
import tempfile
import unittest

from evaluation.visual.run import fuse, metrics, prepare
from evaluation.visual.routing import route_query, selective_rankings


class VisualEvaluationTests(unittest.TestCase):
    def test_fusion_uses_ranks_and_keeps_pages_from_either_channel(self):
        self.assertEqual(fuse(['a', 'b'], ['b', 'c']), ['b', 'a', 'c'])
        self.assertEqual(fuse([], ['b']), ['b'])

    def test_metrics_ignore_unjudged_and_count_misses(self):
        result = metrics({'a': ['x', 'y'], 'b': ['x'], 'c': []},
                         [{'id': 'a', 'relevant': ['y']}, {'id': 'b', 'relevant': ['z']},
                          {'id': 'c', 'relevant': []}])
        self.assertEqual(result, dict(judged_queries=2, hit_at_1=0, hit_at_5=.5, mrr=.25))
        self.assertEqual(metrics({}, []), {'judged_queries': 0})

    def test_preparation_keeps_page_identity_and_limits_images(self):
        try:
            import pymupdf
        except ImportError:
            self.skipTest('Install visual-evaluation extra')
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            with pymupdf.open() as doc:
                for text in ['first page', 'second page']:
                    page = doc.new_page(width=1800, height=1200)
                    page.insert_text((40, 40), text)
                doc.save(root / 'slides.pdf')
            output = root / 'out'
            output.mkdir()
            pages = prepare(root, output, 1, False)
            self.assertEqual(len(pages), 1)
            self.assertEqual(pages[0]['id'], 'slides.pdf#page=1')
            self.assertEqual(pages[0]['text'], 'first page')
            from PIL import Image
            with Image.open(output / pages[0]['image']) as image:
                self.assertLessEqual(max(image.size), 1200)
            self.assertEqual(json.loads((output / 'pages.json').read_text()), pages)


class VisualRoutingTests(unittest.TestCase):
    def test_explicit_visual_requests(self):
        for query in ['Find me a diagram of a cell', 'SHOW THE PHOTO of a mountain',
                      'An illustration of a spacecraft', 'screenshot of the settings panel',
                      'a graph of temperature over time', 'Where is the picture of a moon?',
                      'Which screenshot shows settings?', 'Explain this screenshot',
                      'What evidence is in the image?', 'Why does this diagram show an ocean?',
                      'Where can I find pictures of Mars?']:
            with self.subTest(query=query):
                self.assertEqual(route_query(query).channel, 'combined')

    def test_facts_and_ambiguous_queries_preserve_text(self):
        for query in ['How do I draw a graph?', 'photosynthesis', 'graph theory',
                      'Europa interior', '', 'How can we plot a graph?']:
            with self.subTest(query=query):
                self.assertEqual(route_query(query).channel, 'text')

    def test_routing_ignores_judgments_and_reports_reason(self):
        queries = [{'id': 'a', 'text': 'Why is Europa warm?', 'category': 'visual',
                    'relevant': ['wrong']},
                   {'id': 'b', 'text': 'A diagram of Europa', 'category': 'text'}]
        rankings, routes = selective_rankings(queries, {'a': ['t'], 'b': ['t']},
                                              {'a': ['v'], 'b': ['v']})
        self.assertEqual(rankings, {'a': ['t'], 'b': ['v']})
        self.assertEqual(routes['a']['channel'], 'text')
        self.assertTrue(routes['b']['reason'])
