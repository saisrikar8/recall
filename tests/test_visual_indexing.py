"""Automatic visual indexing, atomic publication, and cross-channel retrieval."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, event, select, func, text
from src import database as db, indexing, semantic_search, visual, pipeline
from src.extraction import ExtractionError, extract_document
from src.visual import ocr_image as real_ocr_image
from src.models import Chunk, Embedding, Entity, Extraction, VisualEmbedding


class VisualIndexingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.enterContext(patch('src.scene_search.encode_images', side_effect=lambda images: [[1., 0.] for _ in images]))
        self.enterContext(patch('src.scene_search.encode_query', return_value=__import__('numpy').array([1., 0.])))
        engine = create_engine('sqlite://')
        self.addCleanup(engine.dispose)
        event.listen(engine, 'connect', db.register_functions)
        self.enterContext(patch.object(db, 'engine', engine))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.text_encoder = self.enterContext(patch.object(indexing, 'get_code_embedding', return_value=[1., 0.]))
        self.enterContext(patch.object(semantic_search, 'get_query_embedding', return_value=[1., 0.]))
        self.enterContext(patch.object(visual, 'ocr_worker_count', return_value=1))
        self.ocr = self.enterContext(patch.object(visual, 'ocr_image', return_value='Cambrian explosion'))
        self.image_encoder = self.enterContext(patch.object(visual, 'embed_image', return_value=[0., 1., 0.]))
        self.batch_encoder = self.enterContext(patch.object(visual, 'embed_images',
            side_effect=lambda images: [self.image_encoder(image) for image in images]))
        self.query_encoder = self.enterContext(patch.object(visual, 'embed_query', return_value=[0., 1., 0.]))

    def image(self, name='scan.png'):
        from PIL import Image
        path = self.root / name
        with Image.new('RGB', (300, 200), 'white') as image:
            image.save(path)
        return path

    def test_images_are_discovered_ocr_and_visually_embedded_by_default(self):
        path = self.image()
        self.assertEqual(indexing.update_index(self.root)['new'], 1)
        self.ocr.assert_called_once()
        self.image_encoder.assert_called_once()
        with db.get_db() as session:
            vectors = session.scalars(select(Embedding)).all()
            self.assertTrue(any(v.model_key == pipeline.MODEL_KEY and v.dimensions == 2 for v in vectors))
            visual_vector = session.scalar(select(VisualEmbedding))
            self.assertEqual(visual_vector.dimensions, 3)
            self.assertEqual(visual_vector.model_key, visual.MODEL_KEY)
        results = db.search_db('cambrian explosion', threshold=1)
        self.assertEqual(results[0]['match_type'], 'keyword')
        self.assertEqual(results[0]['page'], 1)
        self.assertEqual(results[0]['path'], str(path))
        self.assertEqual(indexing.update_index(self.root)['unchanged'], 1)
        self.ocr.assert_called_once()
        self.image_encoder.assert_called_once()

    def test_visual_only_pages_are_searchable_without_ocr_text(self):
        self.ocr.return_value = ''
        self.image()
        indexing.update_index(self.root)
        self.text_encoder.return_value = [-1., 0.]
        with patch.object(semantic_search, 'get_query_embedding', return_value=[-1., 0.]):
            results = db.search_db('An image of a moon with craters', threshold=.9)
        self.assertEqual(results[0]['match_type'], 'visual')
        self.assertEqual(results[0]['page'], 1)
        self.query_encoder.assert_called_once()

    def test_ordinary_query_includes_visual_only_image_despite_text_hits(self):
        self.ocr.return_value = ''
        image = self.image('handwriting.png')
        text = self.root / 'notes.md'
        text.write_text('A text passage about algebra and notation.')
        indexing.update_index(self.root)
        results = db.search_db('linear algebra', limit=5, threshold=.3)
        self.assertTrue(any(row['path'] == str(image) for row in results))
        self.assertTrue(any(row['path'] == str(text) for row in results))
        self.query_encoder.assert_called_once()

    def test_variable_question_retrieves_image_without_ocr(self):
        self.ocr.return_value = ''
        image = self.image('matrices.png')
        results_before = indexing.update_index(self.root)
        self.assertEqual(results_before['new'], 1)
        results = db.search_db('What are P and C equal to?', limit=5)
        self.assertEqual(results[0]['path'], str(image))
        self.assertEqual(results[0]['match_type'], 'visual')

    def test_failed_visual_update_preserves_old_publication_and_retries_saved_ocr(self):
        path = self.image()
        indexing.update_index(self.root)
        with db.get_db() as session:
            old = session.scalar(select(Extraction.id).where(Extraction.is_active.is_(True)))
        from PIL import Image
        with Image.new('RGB', (301, 200), 'black') as image:
            image.save(path)
        self.image_encoder.side_effect = RuntimeError('visual inference failed')
        self.assertEqual(indexing.update_index(self.root)['failed'], 1)
        with db.get_db() as session:
            self.assertEqual(session.scalar(select(Extraction.id).where(Extraction.is_active.is_(True))), old)
        self.image_encoder.side_effect = None
        with patch.object(visual, 'ocr_image', side_effect=AssertionError('must reuse saved OCR')):
            self.assertEqual(indexing.update_index(self.root)['changed'], 1)
        with db.get_db() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(Extraction)), 1)

    def test_visual_model_revision_rebuild_reuses_ocr_for_unchanged_file(self):
        self.image()
        indexing.update_index(self.root)
        with patch.object(visual, 'MODEL_KEY', 'replacement-visual-model'), \
             patch.object(visual, 'ocr_image', side_effect=AssertionError('OCR must not repeat')), \
             patch.object(indexing, 'get_code_embedding', side_effect=AssertionError('text must not repeat')):
            self.assertEqual(indexing.update_index(self.root)['changed'], 1)
            self.assertEqual(indexing.update_index(self.root)['unchanged'], 1)

    def test_scene_upgrade_reuses_ocr_text_and_colsmol(self):
        self.image()
        indexing.update_index(self.root)
        with patch('src.scene_search.MODEL_KEY', 'updated-scene'), \
             patch.object(visual, 'ocr_image', side_effect=AssertionError('OCR repeated')), \
             patch.object(visual, 'embed_images', side_effect=AssertionError('ColSmol repeated')), \
             patch.object(indexing, 'get_code_embedding', side_effect=AssertionError('Text repeated')):
            self.assertEqual(indexing.update_index(self.root)['changed'], 1)
            self.assertEqual(indexing.update_index(self.root)['unchanged'], 1)

    def test_failed_scene_upgrade_keeps_previous_generation_and_retries(self):
        self.image()
        indexing.update_index(self.root)
        with db.get_db() as session:
            old = session.scalar(select(Extraction.id).where(Extraction.is_active.is_(True)))
        with patch('src.scene_search.MODEL_KEY', 'updated-scene'):
            with patch('src.scene_search.encode_images', side_effect=RuntimeError('scene unavailable')):
                self.assertEqual(indexing.update_index(self.root)['failed'], 1)
            with db.get_db() as session:
                self.assertEqual(session.scalar(select(Extraction.id).where(Extraction.is_active.is_(True))), old)
            self.assertEqual(indexing.update_index(self.root)['changed'], 1)

    def test_photo_retrieval_preserves_scene_leader(self):
        self.image('a.png'); self.image('b.png')
        with patch('src.scene_search.encode_images', side_effect=lambda images: [[0., 1.] for _ in images]):
            indexing.update_index(self.root)
        with db.get_db() as session, session.begin():
            from src import scene_search
            vectors = session.scalars(select(Embedding).where(Embedding.model_key == scene_search.MODEL_KEY)).all()
            for vector in vectors:
                if vector.chunk.entity.extraction.file.relative_path == 'b.png':
                    vector.vector = [1., 0.]
        results = db.search_db('An illustration of a spacecraft')
        self.assertTrue(results[0]['path'].endswith('b.png'))
        self.assertEqual(results[0]['visual_source'], 'scene')

    def test_selected_mixed_pages_keep_native_and_ocr_with_page_numbers(self):
        import pymupdf
        path = self.root / 'slides.pdf'
        with pymupdf.open() as document:
            document.new_page().insert_text((50, 50), 'Native heading')
            document.new_page()
            document.save(path)
        from src.ocr_policy import OCRDecision
        self.enterContext(patch('src.ocr_policy.classify_page', return_value=OCRDecision('page', 'test_mixed_content')))
        self.ocr.side_effect = ['Diagram labels', 'Handwritten page two']
        self.assertEqual(indexing.update_index(self.root)['new'], 1)
        self.assertEqual(self.ocr.call_count, 2)
        self.assertEqual(self.image_encoder.call_count, 2)
        with db.get_db() as session:
            passages = session.execute(select(Entity.start_page, Chunk.text).join(Chunk.entity).where(Chunk.kind == 'body')).all()
            self.assertTrue(any(page == 1 and 'Native heading' in value and 'Diagram labels' in value for page, value in passages))
            self.assertTrue(any(page == 2 and 'Handwritten page two' in value for page, value in passages))

    def test_exact_text_bypasses_cosine_cutoff_and_collection_scope_is_respected(self):
        for name in ['one', 'two']:
            root = self.root / name
            root.mkdir()
            (root / 'notes.md').write_text('Cambrian explosion')
            indexing.update_index(root)
        with patch.object(semantic_search, 'get_query_embedding', return_value=[-1., 0.]):
            results = db.search_db('cambrian explosion', threshold=.9, collection=str(self.root / 'two'))
        self.assertTrue(results)
        self.assertTrue(all(r['collection'] == str(self.root / 'two') for r in results))
        self.assertTrue(all(r['match_type'] == 'keyword' for r in results))
        self.query_encoder.assert_not_called()

    def test_removal_cascades_through_both_vector_spaces(self):
        from src.index_management import remove_index
        self.image()
        indexing.update_index(self.root)
        remove_index(collection=str(self.root))
        with db.get_db() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(Embedding)), 0)
            self.assertEqual(session.scalar(select(func.count()).select_from(VisualEmbedding)), 0)
            self.assertEqual(session.scalar(text('SELECT count(*) FROM chunk_fts')), 0)

    def test_missing_tesseract_is_a_visible_failure_not_partial_success(self):
        from PIL import Image
        with patch.object(visual.shutil, 'which', return_value=None), \
             Image.new('RGB', (10, 10)) as image:
            with self.assertRaisesRegex(ExtractionError, 'Tesseract'):
                real_ocr_image(image)

    def test_native_and_ocr_duplicate_lines_are_not_stored_twice(self):
        self.assertEqual(visual.merge_text('Title\nA fact', ' TITLE \nA fact\nDiagram label'),
                         'Title\nA fact\nDiagram label')

    def test_keyword_matches_survive_zero_norm_text_vectors(self):
        (self.root / 'note.txt').write_text('Cambrian explosion')
        self.text_encoder.return_value = [0., 0.]
        indexing.update_index(self.root)
        results = db.search_db('cambrian explosion')
        self.assertTrue(results)
        self.assertEqual(results[0]['match_type'], 'keyword')

    def pdf(self, name, pages):
        import pymupdf
        path = self.root / name
        with pymupdf.open() as document:
            for number in range(pages):
                document.new_page().insert_text((50, 50), f'Lecture page {number + 1}')
            document.save(path)
        return path

    def test_pdfs_run_last_with_all_ocr_before_bounded_cross_file_embedding(self):
        self.pdf('a.pdf', 2)
        self.pdf('b.pdf', 3)
        (self.root / 'z.py').write_text('def code_first(): return 1\n')
        from src.ocr_policy import OCRDecision
        self.enterContext(patch('src.ocr_policy.classify_page', return_value=OCRDecision('page', 'test_ordering')))
        events, sizes, images_seen = [], [], []
        def ocr(image):
            events.append('ocr')
            return 'Cambrian explosion'
        def text_encoder(value):
            events.append('pdf-text' if '.pdf' in value else 'other-text')
            return [1., 0.]
        def batch(images):
            events.append('batch')
            sizes.append(len(images))
            images_seen.extend(images)
            self.assertTrue(all(max(image.size) <= visual.PAGE_EDGE for image in images))
            return [[0., 1., 0.] for _ in images]
        self.ocr.side_effect = ocr
        self.text_encoder.side_effect = text_encoder
        self.batch_encoder.side_effect = batch
        self.assertEqual(indexing.update_index(self.root)['new'], 3)
        self.assertEqual(sizes, [4, 1])
        self.assertLess(max(i for i, e in enumerate(events) if e == 'other-text'), events.index('ocr'))
        self.assertLess(max(i for i, e in enumerate(events) if e == 'ocr'), events.index('batch'))
        self.assertLess(max(i for i, e in enumerate(events) if e == 'batch'), events.index('pdf-text'))
        for image in images_seen:
            with self.assertRaises(ValueError):
                image.getpixel((0, 0))
        self.ocr.reset_mock()
        self.batch_encoder.reset_mock()
        self.assertEqual(indexing.update_index(self.root)['unchanged'], 3)
        self.ocr.assert_not_called()
        self.batch_encoder.assert_not_called()

    def test_failed_batch_falls_back_to_individual_pages(self):
        self.pdf('a.pdf', 1)
        self.pdf('b.pdf', 1)
        self.batch_encoder.side_effect = RuntimeError('batch does not fit in memory')
        counts = indexing.update_index(self.root)
        self.assertEqual(counts['new'], 2)
        self.assertEqual(counts['failed'], 0)
        self.assertEqual(self.image_encoder.call_count, 2)

    def test_source_changed_during_group_does_not_publish_that_pdf(self):
        first = self.pdf('a.pdf', 1)
        self.pdf('b.pdf', 1)
        def batch(images):
            first.write_bytes(first.read_bytes() + b'\n% changed while embedding\n')
            return [[0., 1., 0.] for _ in images]
        self.batch_encoder.side_effect = batch
        counts = indexing.update_index(self.root)
        self.assertEqual(counts['new'], 1)
        self.assertEqual(counts['failed'], 1)
        with db.get_db() as session:
            published = session.scalars(select(Extraction).where(Extraction.is_active.is_(True))).all()
            self.assertEqual(len(published), 1)
            self.assertEqual(published[0].file.relative_path, 'b.pdf')

    def test_pdf_text_embeddings_only_encode_actual_passages(self):
        self.pdf('lecture.pdf', 2)
        indexing.update_index(self.root)
        with db.get_db() as session:
            kinds = session.scalars(select(Entity.kind).join(Chunk.entity).join(Embedding, Embedding.chunk_id == Chunk.id).where(Embedding.model_key == pipeline.MODEL_KEY)).all()
            self.assertEqual(kinds, ['passage', 'passage'])
            self.assertEqual(session.scalar(select(func.count()).select_from(VisualEmbedding)), 2)
        self.assertEqual(self.text_encoder.call_count, 2)

    def test_retry_with_new_visual_profile_discards_only_stale_candidate_vectors(self):
        self.image()
        self.text_encoder.side_effect = RuntimeError('interrupted text inference')
        self.assertEqual(indexing.update_index(self.root)['failed'], 1)
        self.text_encoder.side_effect = None
        with patch.object(visual, 'MODEL_KEY', 'new-fast-profile'), \
             patch.object(visual, 'ocr_image', side_effect=AssertionError('must reuse saved OCR')):
            self.assertEqual(indexing.update_index(self.root)['changed'], 1)
        with db.get_db() as session:
            self.assertEqual(set(session.scalars(select(VisualEmbedding.model_key))), {'new-fast-profile'})
