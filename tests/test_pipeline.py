import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, event, func, select, text

from src import database as db, indexing, pipeline, semantic_search
from src.models import Chunk, Embedding, Entity, Extraction, File


class PipelineTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.enterContext(patch('src.scene_search.encode_images', side_effect=lambda images: [[1., 0.] for _ in images]))
        self.enterContext(patch('src.scene_search.encode_query', return_value=__import__('numpy').array([1., 0.])))
        self.engine = create_engine('sqlite://')
        self.addCleanup(self.engine.dispose)
        event.listen(self.engine, 'connect', db.register_functions)
        self.enterContext(patch.object(db, 'engine', self.engine))
        self.enterContext(patch('src.visual.embed_image', return_value=[1., 0.]))
        self.enterContext(patch('src.visual.embed_images', side_effect=lambda images: [[1., 0.] for _ in images]))
        self.enterContext(patch('src.visual.embed_query', return_value=[1., 0.]))
        self.enterContext(patch('src.visual.ocr_image', return_value=''))
        self.encoder = self.enterContext(patch.object(indexing, 'get_code_embedding', return_value=[1., 0.]))
        self.enterContext(patch.object(semantic_search, 'get_query_embedding', return_value=[1., 0.]))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))

    def write(self, source, name='client.py'):
        path = self.root / name
        path.write_text(source)
        return path

    def active(self):
        with db.get_db() as session:
            return session.scalar(select(Extraction.id).where(Extraction.is_active.is_(True)))

    def test_full_hierarchy_chunks_gold_and_fts(self):
        self.write('class Client:\n    timeout = 30\n    def request(self):\n        return self.timeout\n')
        self.assertEqual(indexing.update_index(self.root)['new'], 1)
        with db.get_db() as session:
            method = session.scalar(select(Entity).where(Entity.kind == 'method'))
            self.assertEqual(method.parent.name, 'Client')
            self.assertEqual(method.parent.parent.kind, 'file')
            self.assertEqual(method.chunks[0].embeddings[0].dimensions, 2)
            self.assertGreater(session.scalar(text('SELECT count(*) FROM chunk_fts')), 0)
            self.assertEqual(session.scalar(select(Extraction.status)), 'complete')
        result = db.search_db('timeout', limit=10)
        self.assertTrue(any(row.get('match_line') == 2 for row in result))
        self.assertEqual(db.search_db('which class handles requests')[0]['kind'], 'class')

    def test_failed_gold_preserves_old_results_and_retry_reuses_silver(self):
        path = self.write('def before(): return 1\n')
        indexing.update_index(self.root)
        original = self.active()
        path.write_text('def after(): return 2\n')
        self.encoder.side_effect = [[1., 0.], RuntimeError('model unavailable')]
        self.assertEqual(indexing.update_index(self.root)['failed'], 1)
        self.assertEqual(self.active(), original)
        self.assertIn('before', [row['name'] for row in db.search_db('before')])
        with db.get_db() as session:
            failed = session.scalar(select(Extraction).where(Extraction.status == 'failed'))
            self.assertTrue(failed.configuration['silver_complete'])
            self.assertEqual(session.scalar(select(func.count()).select_from(Extraction)), 2)
        self.encoder.side_effect = None
        with patch.object(pipeline, 'extract_document', side_effect=AssertionError('must reuse Silver')):
            self.assertEqual(indexing.update_index(self.root)['changed'], 1)
        self.assertNotEqual(self.active(), original)
        self.assertIn('after', [row['name'] for row in db.search_db('after')])
        with db.get_db() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(Extraction)), 1)

    def test_model_rebuild_uses_saved_silver(self):
        self.write('def demo(): return 1\n')
        indexing.update_index(self.root)
        with patch.object(pipeline, 'MODEL_KEY', 'new-model-config'), \
             patch.object(pipeline, 'extract_document', side_effect=AssertionError('must reuse Silver')):
            self.assertEqual(indexing.update_index(self.root)['changed'], 1)
        with db.get_db() as session:
            self.assertEqual(set(session.scalars(select(Embedding.model_key))), {'new-model-config'})

    def test_source_change_during_embedding_does_not_publish(self):
        path = self.write('def before(): return 1\n')
        indexing.update_index(self.root)
        original = self.active()
        path.write_text('def middle(): return 2\n')
        def change_source(source):
            path.write_text('def latest(): return 3\n')
            return [1., 0.]
        self.encoder.side_effect = change_source
        self.assertEqual(indexing.update_index(self.root)['failed'], 1)
        self.assertEqual(self.active(), original)
        self.encoder.side_effect = None
        indexing.update_index(self.root)
        self.assertIn('latest', [row['name'] for row in db.search_db('latest')])

    def test_deletion_cleans_all_layers_and_fts(self):
        path = self.write('def demo(): return 1\n')
        indexing.update_index(self.root)
        path.unlink()
        self.assertEqual(indexing.update_index(self.root)['deleted'], 1)
        with db.get_db() as session:
            for model in (File, Extraction, Entity, Chunk, Embedding):
                self.assertEqual(session.scalar(select(func.count()).select_from(model)), 0)
            self.assertEqual(session.scalar(text('SELECT count(*) FROM chunk_fts')), 0)

    def test_markdown_and_text_are_searchable_and_chunked(self):
        self.write('# Networking\nSockets connect machines\n', 'notes.md')
        self.write('An example paragraph\n' * 400, 'notes.txt')
        self.assertEqual(indexing.update_index(self.root)['new'], 2)
        results = db.search_db('Sockets', limit=10)
        self.assertTrue(any(row['relative_path'] == 'notes.md' for row in results))
        with db.get_db() as session:
            self.assertTrue(all(len(chunk.text) <= 3000 for chunk in session.scalars(select(Chunk))))

    def test_each_completed_file_commits_before_next(self):
        self.write('def a(): return 1\n', 'a.py')
        self.write('def b(): return 2\n', 'b.py')
        def report(message):
            if 'Checking b.py' in message:
                raise RuntimeError('interrupted')
        with self.assertRaisesRegex(RuntimeError, 'interrupted'):
            indexing.update_index(self.root, report=report)
        self.assertIn('a', [row['name'] for row in db.search_db('a')])

    def test_long_function_returns_specific_line_with_provenance(self):
        self.write('def configure():\n    a = 1\n    b = 2\n    request_timeout = 30\n    c = 3\n    d = 4\n    return request_timeout\n')
        indexing.update_index(self.root)
        results = db.search_db('request_timeout', limit=10)
        result = next(row for row in results if row['name'] == 'configure')
        self.assertEqual(result['match_line'], 4)
        self.assertIn('request_timeout = 30', result['source'])
        self.assertIn('chunk_start_line', result)

    def test_javascript_globals_classes_and_fields_are_searchable(self):
        self.write('const GLOBAL_TIMEOUT = 30;\nclass Client {\n timeout = 20;\n request() { return this.timeout; }\n}\n', 'client.js')
        indexing.update_index(self.root)
        results = db.search_db('GLOBAL_TIMEOUT', limit=20)
        self.assertTrue(any('GLOBAL_TIMEOUT = 30' in row['source'] for row in results))
        with db.get_db() as session:
            method = session.scalar(select(Entity).where(Entity.kind == 'method'))
            self.assertEqual(method.parent.name, 'Client')
            self.assertTrue(any('timeout' in entity.name for entity in method.parent.children if entity.kind == 'block'))

    def test_pdf_results_retain_page_attribution(self):
        from pypdf import PdfWriter
        from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
        writer = PdfWriter()
        page = writer.add_blank_page(width=300, height=300)
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({
            NameObject('/F1'): DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})})})
        stream = DecodedStreamObject(); stream.set_data(b'BT /F1 12 Tf 20 100 Td (Virtual memory lecture) Tj ET')
        page[NameObject('/Contents')] = writer._add_object(stream)
        data = io.BytesIO(); writer.write(data)
        (self.root / 'lecture.pdf').write_bytes(data.getvalue())
        self.assertEqual(indexing.update_index(self.root)['new'], 1)
        results = db.search_db('Virtual memory', limit=10)
        passage = next(result for result in results if result['kind'] == 'passage')
        self.assertEqual(passage['page'], 1)
        self.assertIn('Virtual memory', passage['source'])

    def test_legacy_and_entity_references_cannot_collide(self):
        from src.index_management import get_function, remove_index
        from src.models import Collection, Function
        self.write('def demo(): return 1\n')
        indexing.update_index(self.root)
        with db.get_db() as session, session.begin():
            entity = session.scalar(select(Entity).where(Entity.kind == 'function'))
            entity_id = entity.id
            file = File(collection=Collection(root_path='/legacy'), relative_path='old.py')
            session.add(Function(id=entity_id, file=file, name='legacy', start_line=1, end_line=1,
                                 docstring='', source='def legacy(): pass'))
        self.assertEqual(get_function(entity_id)['name'], 'legacy')
        self.assertEqual(get_function(f'e:{entity_id}')['name'], 'demo')
        remove_index(function_id=entity_id)
        self.assertEqual(get_function(f'e:{entity_id}')['name'], 'demo')

    def test_go_receiver_method_links_to_struct(self):
        self.write('package main\ntype Client struct { Timeout int }\nfunc (c *Client) Request() int { return c.Timeout }\n', 'client.go')
        self.assertEqual(indexing.update_index(self.root)['new'], 1)
        with db.get_db() as session:
            method = session.scalar(select(Entity).where(Entity.kind == 'method'))
            self.assertEqual(method.name, 'Request')
            self.assertEqual(method.parent.name, 'Client')
