import json
import math
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, func, select, event, URL
from sqlalchemy.orm import Session

from src import semantic_search
from src.models import Base, Collection, File, Function
from src.semantic_search import vector_similarity
from tqdm import tqdm
from src.settings import DATABASE_PATH, DATABASE_URL

DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(DATABASE_URL)

@event.listens_for(engine, "connect")
def register_functions(connection, _):
    connection.execute("PRAGMA foreign_keys=ON")
    connection.create_function(
        "vector_similarity",
        2,
        vector_similarity,
    )

def initialize_database():
    from src.schema import ensure_schema
    ensure_schema(engine)


def get_db() -> Session:
    return Session(engine)

def init_index(index) -> None:
    with get_db() as session:
        collection = Collection(root_path=index['root'])
        session.add(collection)
        for path, props in index['files'].items():
            process_file_index(session, collection, props, path)
        session.commit()

def process_file_index(session: Session,collection: Collection, file_index: dict, relative_path: str) -> None:
    file = File(
        collection=collection,
        relative_path=relative_path,
        content_hash=file_index['hash']
    )
    session.add(file)
    for fxn in tqdm(file_index['functions'], desc=f'processing index for {relative_path}', colour= 'yellow'):
        session.add(
            Function(
                file=file,
                name=fxn['name'],
                start_line=fxn['start-line'],
                end_line=fxn['end-line'],
                docstring=fxn['docstring'],
                source=fxn['source'],
                embedding=fxn.get('embedding'),
                embedding_model=fxn.get('embedding-model'),
            )
        )

def add_file(root_path, relative_path, file_index) -> None:
    q = select(Collection).where(Collection.root_path == root_path)
    with get_db() as session:
        collection = session.scalars(q).first()
        process_file_index(session, collection, file_index, relative_path)
        session.commit()

def update_file(file_index: dict, root_path: str, relative_path: str) -> None:
    q1 = select(Collection).where(Collection.root_path == root_path)
    with get_db() as session:
        collection = session.scalars(q1).first()
        if not collection:
            print("The project in the specified root path doesn't exist.")
            return
        q2 = select(File).where(File.collection == collection, File.relative_path == relative_path)
        file = session.scalars(q2).first()

        if file:
            file.content_hash = file_index['hash']
            incoming_ranges = {
                (fxn['start-line'], fxn['end-line'])
                for fxn in file_index['functions']
            }
            # Remove obsolete functions before inserting rows at new locations.
            for obj in tqdm(list(file.functions), desc='removing obsolete entries', colour='red'):
                if (obj.start_line, obj.end_line) not in incoming_ranges:
                    session.delete(obj)
            session.flush()

            for fxn in tqdm(file_index['functions'], desc='updating existing remaining entries', colour='green'):
                obj = session.scalars(select(Function).where(
                    Function.file == file,
                    Function.start_line == fxn['start-line'],
                    Function.end_line == fxn['end-line'],
                )).first()
                if not obj:
                    obj = Function(file=file)
                    session.add(obj)
                obj.name = fxn['name']
                obj.start_line = fxn['start-line']
                obj.end_line = fxn['end-line']
                obj.docstring = fxn['docstring']
                if obj.source != fxn['source'] or 'embedding' in fxn:
                    obj.embedding = fxn.get('embedding')
                    obj.embedding_model = fxn.get('embedding-model')
                obj.source = fxn['source']

            file.indexed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            file.last_error = None
            session.commit()
        else:
            print("The specified file path doesn't exist. Adding file...")
            # Reuse the insertion helper in this session, so there is one commit.
            process_file_index(session, collection, file_index, relative_path)
            session.commit()

def search_db(query: str, limit: int = 5, threshold=.4, collection: str | None = None):
    from src.retrieval import search
    return search(query, limit, threshold, collection)
