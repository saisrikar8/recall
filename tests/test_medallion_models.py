"""New schema invariants, exercised with SQLite foreign keys enabled."""
import unittest

from sqlalchemy import create_engine, delete, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.models import Base, Chunk, Collection, Embedding, Entity, Extraction, File, Function


class MedallionModelTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        self.addCleanup(self.engine.dispose)
        @event.listens_for(self.engine, 'connect')
        def enable_constraints(connection, _):
            connection.execute('PRAGMA foreign_keys=ON')
        Base.metadata.create_all(self.engine)
        with Session(self.engine) as session, session.begin():
            file = File(collection=Collection(root_path='/project'), relative_path='client.py')
            extraction = Extraction(file=file, content_hash='source-hash', extractor_version='1')
            root = Entity(extraction=extraction, entity_key='file', kind='file', name='client.py')
            cls = Entity(extraction=extraction, parent=root, entity_key='class:1', kind='class', name='Client')
            method = Entity(extraction=extraction, parent=cls, entity_key='method:3', kind='method', name='request', start_line=3, end_line=6)
            chunk = Chunk(entity=method, position=0, text='return response', content_hash='chunk-hash', start_line=5, end_line=5)
            vector = Embedding(chunk=chunk, model_key='model@revision:config', model_name='model', input_hash='input-hash', dimensions=2, vector=[1., 0.])
            session.add_all([file, vector])
            session.flush()
            self.file_id, self.extraction_id = file.id, extraction.id
            self.root_id, self.method_id, self.chunk_id = root.id, method.id, chunk.id

    def test_roundtrip_hierarchy_locations_and_independent_embeddings(self):
        with Session(self.engine) as session:
            file = session.get(File, self.file_id)
            extraction = file.extractions[0]
            self.assertEqual(extraction.status, 'pending')
            root = session.get(Entity, self.root_id)
            method = root.children[0].children[0]
            self.assertEqual(method.parent.name, 'Client')
            self.assertEqual(method.extraction.id, extraction.id)
            self.assertEqual(method.chunks[0].start_line, 5)
            self.assertEqual(method.chunks[0].embeddings[0].vector, [1., 0.])
            self.assertEqual(file.functions, [])

    def test_multiple_model_versions_can_share_a_chunk(self):
        with Session(self.engine) as session, session.begin():
            session.add(Embedding(chunk_id=self.chunk_id, model_key='another-config', model_name='model', input_hash='other-input', dimensions=3, vector=[1., 0., 0.]))
        with Session(self.engine) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(Embedding)), 2)

    def test_bulk_file_deletion_cascades_all_new_layers(self):
        with Session(self.engine) as session, session.begin():
            session.execute(delete(File).where(File.id == self.file_id))
        with Session(self.engine) as session:
            for model in (Extraction, Entity, Chunk, Embedding):
                self.assertEqual(session.scalar(select(func.count()).select_from(model)), 0)

    def test_orm_subtree_deletion_keeps_ancestors(self):
        with Session(self.engine) as session, session.begin():
            session.delete(session.get(Entity, self.method_id))
        with Session(self.engine) as session:
            self.assertIsNotNone(session.get(Entity, self.root_id))
            self.assertEqual(session.scalar(select(func.count()).select_from(Chunk)), 0)
            self.assertEqual(session.scalar(select(func.count()).select_from(Embedding)), 0)

    def test_invalid_status_and_active_incomplete_are_rejected(self):
        for values in ({'status': 'unknown'}, {'status': 'pending', 'is_active': True}):
            with self.subTest(values=values), self.assertRaises(IntegrityError):
                with Session(self.engine) as session, session.begin():
                    session.add(Extraction(file_id=self.file_id, content_hash='x', extractor_version='1', **values))

    def test_at_most_one_active_extraction_per_file(self):
        with Session(self.engine) as session, session.begin():
            extraction = session.get(Extraction, self.extraction_id)
            extraction.status = 'complete'
            extraction.is_active = True
        with self.assertRaises(IntegrityError):
            with Session(self.engine) as session, session.begin():
                session.add(Extraction(file_id=self.file_id, content_hash='new', extractor_version='1', status='complete', is_active=True))

    def test_parent_cannot_belong_to_another_extraction(self):
        with self.assertRaises(IntegrityError):
            with Session(self.engine) as session, session.begin():
                other = Extraction(file_id=self.file_id, content_hash='other', extractor_version='1')
                session.add(other)
                session.flush()
                session.add(Entity(extraction_id=other.id, parent_id=self.root_id, entity_key='cross', name='bad', kind='method'))

    def test_invalid_locations_and_duplicate_positions_are_rejected(self):
        cases = [{'start_line': 0, 'end_line': 1}, {'start_line': 3, 'end_line': 2},
                 {'start_page': 1}, {'start_char': 10, 'end_char': 5}, {'position': 0}]
        for location in cases:
            values = dict(entity_id=self.method_id, position=1, text='text', content_hash='x')
            values.update(location)
            with self.subTest(location=location), self.assertRaises(IntegrityError):
                with Session(self.engine) as session, session.begin():
                    session.add(Chunk(**values))

    def test_invalid_vectors_dimensions_and_duplicate_models_are_rejected(self):
        for vector in ([], ['text'], [float('nan')], [float('inf')], [True]):
            with self.subTest(vector=vector), self.assertRaises(ValueError):
                Embedding(vector=vector)
        for values in ({'dimensions': 3, 'model_key': 'new'}, {'dimensions': 2, 'model_key': 'model@revision:config'}):
            with self.subTest(values=values), self.assertRaises(IntegrityError):
                with Session(self.engine) as session, session.begin():
                    session.add(Embedding(chunk_id=self.chunk_id, model_name='model', input_hash='x', vector=[1., 0.], **values))
