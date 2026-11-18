import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from src.extraction import ExtractionError, extract_document, iter_documents


class ExtractionTests(unittest.TestCase):
    def test_python_encoding_async_nested_and_locations(self):
        content = b'# coding: latin-1\nclass C:\n    async def run(self):\n        """caf\xe9"""\n        def inner(): pass\n'
        doc = extract_document('example.py', content)
        self.assertEqual([x.name for x in doc.units], ['run', 'inner'])
        self.assertEqual(doc.units[0].docstring, 'caf\u00e9')
        self.assertEqual((doc.units[0].start_line, doc.units[0].end_line), (3, 5))
        self.assertEqual(len(doc.content_hash), 64)

    def test_text_units_are_bounded_and_source_offsets_roundtrip(self):
        text = 'First line\n' + 'a' * 25 + '\nLast line\n'
        doc = extract_document('note.txt', text.encode(), max_chars=10)
        self.assertEqual(''.join(x.text for x in doc.units), text)
        for unit in doc.units:
            self.assertLessEqual(len(unit.text), 10)
            self.assertEqual(unit.text, text[unit.start_char:unit.end_char])
            self.assertIsNotNone(unit.start_line)

    def test_markdown_sections_and_fenced_headings(self):
        text = '# Real\nParagraph\n```python\n# Not a heading\n```\n## Second\nBody\n'
        doc = extract_document('note.md', text.encode())
        self.assertEqual([x.name for x in doc.units], ['Real', 'Second'])
        self.assertIn('# Not a heading', doc.units[0].text)
        self.assertEqual(doc.units[1].start_line, 6)

    def test_unicode_boms_and_empty_documents(self):
        for content in ('Hello'.encode('utf-16'), b'\xef\xbb\xbfHello'):
            self.assertEqual(extract_document('note.txt', content).units[0].text, 'Hello')
        for path in ('empty.py', 'empty.md', 'empty.txt'):
            self.assertEqual(extract_document(path, b'').units, ())

    def test_clear_errors_for_invalid_unsupported_and_oversized_input(self):
        for path, content in [('x.bin', b''), ('x.py', b'def broken(:'),
                              ('x.txt', b'\xff'), ('x.txt', b'a\x00b')]:
            with self.subTest(path=path, content=content), self.assertRaises(ExtractionError):
                extract_document(path, content)
        with self.assertRaises(ExtractionError):
            extract_document('x.txt', b'12345', max_bytes=4)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'large.txt'
            path.write_bytes(b'12345')
            with self.assertRaises(ExtractionError):
                extract_document(path, max_bytes=4)
        with self.assertRaises(ValueError):
            extract_document('x.txt', b'', max_chars=0)

    def test_pdf_pages_blank_warnings_and_limits(self):
        from pypdf import PdfWriter
        from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
        writer = PdfWriter()
        page = writer.add_blank_page(width=300, height=300)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                                 NameObject('/Subtype'): NameObject('/Type1'),
                                 NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
        stream = DecodedStreamObject()
        stream.set_data(b'BT /F1 12 Tf 20 100 Td (Lecture notes) Tj ET')
        page[NameObject('/Contents')] = writer._add_object(stream)
        writer.add_blank_page(width=300, height=300)
        output = io.BytesIO(); writer.write(output)
        doc = extract_document('lecture.pdf', output.getvalue())
        self.assertIn('Lecture notes', doc.units[0].text)
        self.assertEqual(doc.units[0].page, 1)
        self.assertIn('Page 2', doc.warnings[0])
        with self.assertRaisesRegex(ExtractionError, 'page limit'):
            extract_document('lecture.pdf', output.getvalue(), max_pages=1)
        writer.encrypt('password')
        output = io.BytesIO(); writer.write(output)
        with self.assertRaisesRegex(ExtractionError, 'Encrypted'):
            extract_document('lecture.pdf', output.getvalue())
        with self.assertRaisesRegex(ExtractionError, 'PDF extraction failed'):
            extract_document('broken.pdf', b'not a pdf')

    def test_extraction_and_discovery_import_without_third_party_packages(self):
        result = subprocess.run([sys.executable, '-S', '-c',
            'from src.extraction import extract_document; from src.discovery import discover_files; '
            'assert extract_document("note.txt", b"hello").units[0].text == "hello"'],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_mixed_format_discovery_is_opt_in_and_extracts_without_embedding(self):
        from src.discovery import discover_files
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'code.py').write_text('def hello(): pass')
            (root / 'note.md').write_text('# Notes\nUseful content')
            (root / 'plain.txt').write_text('A note')
            (root / 'unsupported.zip').write_bytes(b'not parsed')
            self.assertEqual(len(discover_files(root)), 1)
            documents = list(iter_documents(root))
            self.assertEqual({d.format for d in documents}, {'python', 'markdown', 'text'})
