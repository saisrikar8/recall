import io
import unittest
from unittest.mock import patch
import pymupdf
from PIL import Image, ImageDraw

from src.ocr_policy import classify_page, broken_text
from src import visual
from src.extraction import extract_document


def raster():
    with Image.new('RGB', (600, 600), 'white') as image:
        ImageDraw.Draw(image).text((40, 80), 'Scanned material', fill='black')
        stream = io.BytesIO()
        image.save(stream, format='PNG')
        return stream.getvalue()


class OCRPolicyTests(unittest.TestCase):
    def document(self):
        doc = pymupdf.open()
        self.addCleanup(doc.close)
        return doc, doc.new_page(width=600, height=800)

    def test_native_text_skips_ocr_and_does_not_rasterize(self):
        doc, page = self.document()
        page.insert_text((50, 120), 'Readable lecture notes with native PDF text and no scanned regions.')
        self.assertEqual(classify_page(page).mode, 'none')
        with patch.object(visual, 'ocr_image', side_effect=AssertionError('must skip OCR')), \
             patch.object(visual, '_render_ocr', side_effect=AssertionError('must not render')):
            result = extract_document('notes.pdf', doc.tobytes(), visual=True, report=lambda _: None)
        self.assertIn('Readable lecture notes', ''.join(u.text for u in result.units))
        self.assertEqual(result.metadata['ocr_summary']['none'], 1)
        self.assertTrue(any(u.kind == 'visual_page' for u in result.units))

    def test_footer_does_not_disguise_a_scanned_page(self):
        _, page = self.document()
        page.insert_text((50, 790), 'Math 54 Lecture Notes Page 1')
        page.insert_image(pymupdf.Rect(40, 70, 560, 720), stream=raster())
        decision = classify_page(page)
        self.assertEqual(decision.mode, 'page')
        self.assertEqual(decision.reason, 'no_usable_body_text')

    def test_mixed_native_text_and_image_selects_only_image_region(self):
        doc, page = self.document()
        page.insert_text((50, 120), 'A readable paragraph discussing the diagram and other lecture material.')
        region = pymupdf.Rect(80, 300, 520, 650)
        page.insert_image(region, stream=raster(), keep_proportion=False)
        decision = classify_page(page)
        self.assertEqual(decision.mode, 'regions')
        self.assertEqual(decision.regions, (tuple(region),))
        with patch.object(visual, 'ocr_image', return_value='Diagram labels') as ocr:
            result = extract_document('mixed.pdf', doc.tobytes(), visual=True, report=lambda _: None)
        self.assertEqual(ocr.call_count, 1)
        self.assertIn('readable paragraph', ''.join(u.text for u in result.units))
        self.assertIn('Diagram labels', ''.join(u.text for u in result.units))

    def test_existing_usable_ocr_layer_skips_duplicate_ocr(self):
        _, page = self.document()
        page.insert_image(page.rect, stream=raster(), keep_proportion=False)
        for y in range(110, 650, 35):
            page.insert_text((50, y), 'Existing accurate OCR text spread across this scanned document page.', render_mode=3)
        self.assertEqual(classify_page(page).mode, 'none')

    def test_blank_and_sparse_vector_pages_are_distinguished(self):
        _, page = self.document()
        self.assertEqual(classify_page(page).mode, 'none')
        page.insert_text((40, 790), 'Page 1')
        page.draw_line((60, 150), (400, 400))
        self.assertEqual(classify_page(page).mode, 'page')

    def test_broken_text_is_detected_without_rejecting_math(self):
        self.assertTrue(broken_text('bad \ufffd\ufffd'))
        self.assertTrue(broken_text('(cid:1) (cid:2)'))
        self.assertFalse(broken_text('x² + y² = 1; α and β'))

    def test_readable_pdf_needs_no_tesseract_but_scan_still_fails_visibly(self):
        doc, page = self.document()
        page.insert_text((50, 120), 'A readable native paragraph.')
        with patch.object(visual.shutil, 'which', return_value=None):
            extract_document('native.pdf', doc.tobytes(), visual=True, report=lambda _: None)
        page.insert_image(pymupdf.Rect(40, 200, 560, 700), stream=raster(), keep_proportion=False)
        with patch.object(visual.shutil, 'which', return_value=None):
            with self.assertRaisesRegex(ValueError, 'Tesseract'):
                extract_document('scan.pdf', doc.tobytes(), visual=True, report=lambda _: None)

    def test_decorative_banner_with_native_title_does_not_trigger_ocr(self):
        _, page = self.document()
        with Image.new('RGB', (600, 80), 'purple') as image:
            stream = io.BytesIO(); image.save(stream, format='PNG')
        page.insert_image(pymupdf.Rect(0, 0, 600, 80), stream=stream.getvalue())
        page.insert_text((40, 55), 'A title already available as native text')
        page.insert_text((40, 160), 'A readable paragraph containing the body of this lecture slide.')
        self.assertEqual(classify_page(page).mode, 'none')
