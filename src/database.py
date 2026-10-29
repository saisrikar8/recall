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
import os
from platformdirs import user_data_path

override = os.environ.get("RECALL_DB_PATH")

if override:
    DATABASE_PATH = Path(override).expanduser().resolve()
else:
    DATABASE_PATH = user_data_path(
        "recall", appauthor=False
    ) / "index.db"

DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

DATABASE_URL = URL.create(
    "sqlite",
    database=str(DATABASE_PATH),
)

engine = create_engine(DATABASE_URL)

@event.listens_for(engine, "connect")
def register_functions(connection, _):
    connection.create_function(
        "vector_similarity",
        2,
        vector_similarity,
    )

def initialize_database():
    Base.metadata.create_all(engine)


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

def search_db(query: str, limit: int = 5, threshold=0.4, collection: str | None = None):
    if not query.strip() or limit < 1 or not math.isfinite(threshold) or not -1 <= threshold <= 1:
        raise ValueError('Provide a query, positive limit, and threshold between -1 and 1.')
    root = str(Path(collection).resolve()) if collection is not None else None
    with get_db() as session:
        if root is not None and session.scalar(select(Collection.id).where(Collection.root_path == root)) is None:
            raise ValueError(f'Collection not indexed: {root}')
        query_vector = semantic_search.get_query_embedding(query)
        if query_vector is None:
            raise ValueError('Could not embed query.')
        score = func.vector_similarity(json.dumps(query_vector), Function.embedding).label('score')
        statement = (select(Function, score).join(Function.file).join(File.collection)
            .where(Function.embedding_model == semantic_search.DEFAULT_MODEL, score >= threshold))
        if root is not None:
            statement = statement.where(Collection.root_path == root)
        statement = statement.order_by(score.desc(), Collection.root_path,
                                       File.relative_path, Function.start_line).limit(limit)
        return [{
            'name': x.name,
            'path': str(Path(x.file.collection.root_path) / x.file.relative_path),
            'relative_path': x.file.relative_path,
            'collection': x.file.collection.root_path,
            'start-line': x.start_line, 'end-line': x.end_line,
            'docstring': x.docstring, 'source': x.source, 'score': rank,
            'embedding': x.embedding, 'embedding-model': x.embedding_model,
        } for x, rank in session.execute(statement)]
