import os
import threading
import time
import unittest
from unittest.mock import patch

from src import visual
from src.extraction import ExtractionError


class ParallelOCRTests(unittest.TestCase):
    def test_workers_are_bounded_and_overrides_validated(self):
        with patch.dict(os.environ, {'RECALL_OCR_WORKERS': '2'}):
            self.assertLessEqual(visual.ocr_worker_count(), 2)
        for value in ['0', '9', 'many']:
            with patch.dict(os.environ, {'RECALL_OCR_WORKERS': value}):
                with self.assertRaises(ExtractionError):
                    visual.ocr_worker_count()

    def test_pages_overlap_keep_order_and_release_copies(self):
        from PIL import Image
        active, peak = 0, 0
        lock = threading.Lock()
        two_started = threading.Event()
        copies = []
        def pages(*args):
            for number in range(1, 6):
                with Image.new('RGB', (10, 10), (number, 0, 0)) as image:
                    from src.ocr_policy import OCRDecision
                    yield number, '', OCRDecision('page', 'test_scan'), [image.copy()]
        def ocr(image):
            nonlocal active, peak
            copies.append(image)
            number = image.getpixel((0, 0))[0]
            with lock:
                active += 1
                peak = max(peak, active)
                if active == 2:
                    two_started.set()
            if number <= 2:
                self.assertTrue(two_started.wait(2), 'Two pages must be running at once')
            with lock:
                active -= 1
            return 'Page ' + str(number)
        with patch.object(visual, 'iter_ocr_pages', pages), patch.object(visual, 'ocr_image', ocr), \
             patch.object(visual, 'ocr_worker_count', return_value=2):
            units, warnings = visual.extract_units('test.pdf', b'', 4000, 1000, report=lambda _: None)
        self.assertEqual(peak, 2)
        self.assertEqual([u.text for u in units if u.kind == 'ocr'],
                         ['Page 1', 'Page 2', 'Page 3', 'Page 4', 'Page 5'])
        self.assertEqual(warnings, ())
        for image in copies:
            with self.assertRaises(ValueError):
                image.getpixel((0, 0))

    def test_ocr_subprocess_gets_one_thread_without_changing_parent_environment(self):
        from PIL import Image
        from types import SimpleNamespace
        with Image.new('RGB', (10, 10)) as image, \
             patch.object(visual.shutil, 'which', return_value='/bin/tesseract'), \
             patch.object(visual.subprocess, 'run', return_value=SimpleNamespace(stdout=b'text')) as run, \
             patch.dict(os.environ, {'OMP_THREAD_LIMIT': '16'}):
            self.assertEqual(visual.ocr_image(image), 'text')
            self.assertEqual(run.call_args.kwargs['env']['OMP_THREAD_LIMIT'], '1')
            self.assertEqual(os.environ['OMP_THREAD_LIMIT'], '16')

    def test_worker_error_propagates_and_closes_owned_image(self):
        from PIL import Image
        image = Image.new('RGB', (10, 10))
        with patch.object(visual, 'ocr_image', side_effect=ExtractionError('OCR failed')):
            with self.assertRaises(ExtractionError):
                visual._ocr_owned(image)
        with self.assertRaises(ValueError):
            image.getpixel((0, 0))
