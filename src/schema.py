"""Versioned, additive SQLite upgrades, including validated legacy adoption."""
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from contextlib import closing

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from src.models import Base

HEAD = 'c41e7ab20316'
CORE = {'collections', 'files', 'functions'}
LAYERS = {'extractions', 'entities', 'chunks', 'embeddings'}
VISUAL = {'visual_embeddings'}


def migration_config(connection=None):
    config = Config()
    config.set_main_option('script_location', str(Path(__file__).resolve().parent.parent / 'migrations'))
    if connection is not None:
        config.attributes['connection'] = connection
    return config


def _validate(connection, names, *, initial=False):
    inspector = inspect(connection)
    for name in names:
        expected = {c.name for c in Base.metadata.tables[name].columns}
        if initial and name == 'functions':
            expected -= {'embedding', 'embedding_model'}
        actual = {c['name'] for c in inspector.get_columns(name)}
        if actual != expected:
            raise ValueError(f'Cannot adopt unfamiliar schema for {name}; back up and inspect it before migrating')
        for column in inspector.get_columns(name):
            expected_column = Base.metadata.tables[name].columns[column['name']]
            if not isinstance(column['type'], type(expected_column.type)):
                raise ValueError(f'Unexpected column type in {name}.{column["name"]}')
        if inspector.get_pk_constraint(name)['constrained_columns'] != ['id']:
            raise ValueError(f'Unexpected primary key in {name}')
        if name in LAYERS | VISUAL:
            expected_fks = {(tuple(c.parent.name for c in constraint.elements),
                             constraint.referred_table.name,
                             tuple(c.column.name for c in constraint.elements))
                            for constraint in Base.metadata.tables[name].foreign_key_constraints}
            actual_fks = {(tuple(c['constrained_columns']), c['referred_table'], tuple(c['referred_columns']))
                          for c in inspector.get_foreign_keys(name)}
            if not expected_fks <= actual_fks:
                raise ValueError(f'Missing foreign keys in {name}')
            wanted = {tuple(c.name for c in constraint.columns)
                      for constraint in Base.metadata.tables[name].constraints
                      if constraint.__class__.__name__ == 'UniqueConstraint'}
            found = {tuple(c['column_names']) for c in inspector.get_unique_constraints(name)}
            if not wanted <= found:
                raise ValueError(f'Missing uniqueness constraints in {name}')


def _backup(connection, engine):
    database = engine.url.database
    if database and database != ':memory:' and Path(database).is_file():
        source = Path(database)
        suffix = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
        target = source.with_name(source.name + f'.before-schema-{suffix}.db')
        with closing(sqlite3.connect(target)) as backup:
            connection.connection.driver_connection.backup(backup)


def ensure_schema(engine):
    with engine.begin() as connection:
        connection.exec_driver_sql('PRAGMA foreign_keys=ON')
        tables = set(inspect(connection).get_table_names())
        version = connection.scalar(text('SELECT version_num FROM alembic_version')) if 'alembic_version' in tables else None
        config = migration_config(connection)
        if version == HEAD:
            return
        if not tables & CORE:
            if tables - {'alembic_version'}:
                raise ValueError('Database has an unfamiliar schema; refusing automatic initialization')
            command.upgrade(config, 'head')
            return
        if not CORE <= tables:
            raise ValueError('Incomplete legacy schema; refusing automatic migration')
        initial = 'embedding' not in {c['name'] for c in inspect(connection).get_columns('functions')}
        _validate(connection, CORE, initial=initial)
        _backup(connection, engine)
        if tables & LAYERS:
            if not LAYERS <= tables:
                raise ValueError('Partial layered schema; refusing automatic adoption')
            _validate(connection, LAYERS)
            # Previous development builds created these tables via create_all.
            # Adopt only the fully recognized layout, then ensure its FTS objects.
            from src.pipeline import ensure_fts
            ensure_fts(connection)
            if VISUAL <= tables:
                _validate(connection, VISUAL)
                command.stamp(config, HEAD)
            else:
                command.stamp(config, '8f3a2c7d910b')
                command.upgrade(config, 'head')
        else:
            if version is None:
                command.stamp(config, '21d4074c0106' if initial else '0460bbc41a8e')
            command.upgrade(config, 'head')
