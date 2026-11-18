from pathlib import Path
import tempfile
import unittest

from alembic import command
from sqlalchemy import create_engine, event, inspect, MetaData, text

from src import database as db
from src.models import Base
from src.schema import ensure_schema, migration_config, HEAD


class SchemaMigrationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.engine = create_engine(f'sqlite:///{self.root / "index.db"}')
        self.addCleanup(self.engine.dispose)
        event.listen(self.engine, 'connect', db.register_functions)

    def legacy(self, versioned=False):
        if versioned:
            with self.engine.begin() as connection:
                command.upgrade(migration_config(connection), '0460bbc41a8e')
        else:
            metadata = MetaData()
            for name in ('collections', 'files', 'functions'):
                Base.metadata.tables[name].to_metadata(metadata)
            metadata.create_all(self.engine)
        with self.engine.begin() as connection:
            connection.execute(text("INSERT INTO collections(id,root_path) VALUES(1,'/example')"))
            connection.execute(text("INSERT INTO files(id,collection_id,relative_path,content_hash) VALUES(1,1,'a.py','hash')"))
            connection.execute(text("INSERT INTO functions(id,file_id,name,start_line,end_line,docstring,source) VALUES(1,1,'demo',1,1,'','def demo(): pass')"))

    def test_fresh_schema_and_repeatable_initialization(self):
        ensure_schema(self.engine)
        ensure_schema(self.engine)
        with self.engine.connect() as connection:
            self.assertEqual(connection.scalar(text('SELECT version_num FROM alembic_version')), HEAD)
            self.assertIn('chunk_fts', inspect(connection).get_table_names())
        self.assertFalse(list(self.root.glob('*.before-schema-*.db')))

    def test_unversioned_legacy_adoption_preserves_rows_and_creates_backup(self):
        self.legacy()
        ensure_schema(self.engine)
        with self.engine.connect() as connection:
            self.assertEqual(connection.scalar(text('SELECT source FROM functions WHERE id=1')), 'def demo(): pass')
            self.assertEqual(connection.scalar(text('SELECT version_num FROM alembic_version')), HEAD)
        self.assertEqual(len(list(self.root.glob('*.before-schema-*.db'))), 1)
        ensure_schema(self.engine)
        self.assertEqual(len(list(self.root.glob('*.before-schema-*.db'))), 1)

    def test_versioned_legacy_upgrade_preserves_rows(self):
        self.legacy(versioned=True)
        ensure_schema(self.engine)
        with self.engine.connect() as connection:
            self.assertEqual(connection.scalar(text('SELECT name FROM functions')), 'demo')
            self.assertEqual(connection.scalar(text('SELECT version_num FROM alembic_version')), HEAD)

    def test_existing_development_models_are_validated_and_adopted(self):
        Base.metadata.create_all(self.engine)
        ensure_schema(self.engine)
        with self.engine.connect() as connection:
            self.assertEqual(connection.scalar(text('SELECT version_num FROM alembic_version')), HEAD)

    def test_unfamiliar_schema_is_rejected_without_modification(self):
        self.legacy()
        with self.engine.begin() as connection:
            connection.execute(text('ALTER TABLE files ADD COLUMN unknown TEXT'))
        with self.assertRaisesRegex(ValueError, 'unfamiliar schema'):
            ensure_schema(self.engine)
        with self.engine.connect() as connection:
            self.assertEqual(connection.scalar(text('SELECT name FROM functions')), 'demo')
            self.assertNotIn('extractions', inspect(connection).get_table_names())

    def test_downgrade_only_removes_new_layers(self):
        self.legacy(versioned=True)
        ensure_schema(self.engine)
        with self.engine.begin() as connection:
            command.downgrade(migration_config(connection), '0460bbc41a8e')
        with self.engine.connect() as connection:
            self.assertEqual(connection.scalar(text('SELECT name FROM functions')), 'demo')
            self.assertNotIn('chunk_fts', inspect(connection).get_table_names())

    def test_existing_layered_index_upgrades_to_visual_storage(self):
        with self.engine.begin() as connection:
            command.upgrade(migration_config(connection), '8f3a2c7d910b')
            connection.exec_driver_sql("INSERT INTO collections(root_path) VALUES('/kept')")
        ensure_schema(self.engine)
        with self.engine.connect() as connection:
            self.assertIn('visual_embeddings', inspect(connection).get_table_names())
            self.assertEqual(connection.exec_driver_sql('SELECT root_path FROM collections').scalar(), '/kept')
            self.assertEqual(connection.exec_driver_sql('SELECT version_num FROM alembic_version').scalar(), HEAD)
