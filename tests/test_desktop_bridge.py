"""Desktop previews use real originals and reject files outside the index."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, event
from src import database as db
from src.desktop_bridge import indexed_path, preview, library
from src.models import Base, Collection, File


class DesktopBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        engine = create_engine('sqlite://')
        self.addCleanup(engine.dispose)
        event.listen(engine, 'connect', db.register_functions)
        Base.metadata.create_all(engine)
        self.enterContext(patch.object(db, 'engine', engine))
        with db.get_db() as session, session.begin():
            session.add(Collection(root_path=str(self.root)))

    def file(self, name, text=''):
        path = self.root / name
        path.write_text(text)
        with db.get_db() as session, session.begin():
            collection = session.query(Collection).one()
            session.add(File(collection=collection, relative_path=name, content_hash='fixture'))
        return path

    def test_collection_removal_preserves_originals_and_other_collections(self):
        from src.desktop_bridge import remove_collection
        original = self.file('notes.md', '# Original')
        with db.get_db() as session, session.begin():
            other=Collection(root_path=str(self.root / 'other'))
            session.add(File(collection=other,relative_path='kept.md',content_hash='fixture'))
        remove_collection({'collection': str(self.root)})
        self.assertEqual(original.read_text(), '# Original')
        self.assertEqual(len(library()['collections']),1)
        self.assertEqual(library()['files'][0]['name'],'kept.md')
        with self.assertRaises(ValueError):
            remove_collection({'collection':str(self.root)})

    def test_file_removal_preserves_original_neighbors_and_collection(self):
        from src.desktop_bridge import remove_file
        original = self.file('remove.md', '# Keep original')
        kept = self.file('keep.md', '# Still searchable')
        remove_file({'path': str(original)})
        self.assertEqual(original.read_text(), '# Keep original')
        self.assertEqual([row['path'] for row in library()['files']], [str(kept)])
        self.assertEqual(library()['collections'][0]['count'], 1)
        with self.assertRaises(ValueError):
            remove_file({'path': str(original)})

    def test_file_removal_allows_missing_original_and_rejects_unindexed_paths(self):
        from src.desktop_bridge import remove_file
        missing = self.file('missing.md'); missing.unlink()
        for raw in (None, '', 'relative.md', str(self.root / 'unindexed.md')):
            with self.assertRaises(ValueError):
                remove_file({'path': raw})
        self.assertEqual(len(library()['files']), 1)
        remove_file({'path': str(missing)})
        self.assertEqual(library()['files'], [])
        self.assertEqual(len(library()['collections']), 1)

    def test_rejects_unindexed_and_missing_files(self):
        path = self.root / 'secret.txt'; path.write_text('private')
        with self.assertRaises(ValueError): indexed_path(str(path))
        path = self.file('missing.txt'); path.unlink()
        with self.assertRaises(ValueError): indexed_path(str(path))

    def test_code_excerpt_contains_target_and_preserves_line_numbers(self):
        path = self.file('long.py', '\n'.join(f'value = {i}' for i in range(3000)))
        data = preview(dict(path=str(path), line=2500, query='value'))
        self.assertEqual(data['kind'], 'code')
        self.assertTrue(data['truncated'])
        self.assertLessEqual(data['first_line'], 2500)
        self.assertGreaterEqual(data['first_line'] + len(data['text'].splitlines()), 2500)
        self.assertEqual(data['terms'], ['value'])

    def test_markdown_is_returned_as_text_never_executed(self):
        path = self.file('note.md', '# Notes\n<script>alert(1)</script>')
        data = preview(dict(path=str(path)))
        self.assertEqual(data['kind'], 'markdown')
        self.assertIn('<script>', data['text'])

    def test_pdf_renders_requested_page_and_real_text_positions(self):
        import pymupdf
        path = self.file('notes.pdf')
        with pymupdf.open() as document:
            document.new_page().insert_text((72,72),'First page')
            document.new_page().insert_text((72,72),'Recall semantic search')
            document.save(path)
        data = preview(dict(path=str(path), page=2, query='semantic'))
        self.assertEqual((data['page'],data['pages']),(2,2))
        self.assertTrue(data['image'].startswith('data:image/png;base64,'))
        self.assertTrue(data['highlights'])
        rect=data['highlights'][0]
        self.assertTrue(0 <= rect['x'] <= 1 and 0 <= rect['y'] <= 1)
        self.assertEqual(preview(dict(path=str(path), page=900))['page'],2)

    def test_image_preview_is_bounded_png(self):
        from PIL import Image
        path = self.file('photo.png')
        with Image.new('RGB',(2500,1000),'green') as image:image.save(path)
        data = preview(dict(path=str(path)))
        self.assertEqual(data['kind'],'image')
        self.assertTrue(data['image'].startswith('data:image/png;base64,'))

    def test_library_reports_real_files_and_collection(self):
        self.file('notes.md','# Notes')
        data=library()
        self.assertEqual(data['collections'][0]['count'],1)
        self.assertEqual(data['files'][0]['name'],'notes.md')
        self.assertEqual(data['files'][0]['extension'],'.md')
