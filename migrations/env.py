"""Migration target uses the same settings as the application."""
from logging.config import fileConfig
from alembic import context
from sqlalchemy import create_engine, pool
from src.models import Base
from src.settings import DATABASE_URL, DATABASE_PATH

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def run_migrations_offline():
    context.configure(url=DATABASE_URL, target_metadata=Base.metadata,
                      literal_binds=True, dialect_opts={'paramstyle': 'named'})
    with context.begin_transaction():
        context.run_migrations()


def migrate(connection):
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connection = config.attributes.get('connection')
    if connection is not None:
        migrate(connection)
        return
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(DATABASE_URL, poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            migrate(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
