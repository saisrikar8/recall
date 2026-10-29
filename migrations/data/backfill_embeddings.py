from sqlalchemy import select

from src.database import get_db
from src.models import Function
from src.semantic_search import get_code_embedding, DEFAULT_MODEL

with get_db() as session:
    functions = session.scalars(select(Function)).all()

    for function in functions:
        if function.embedding is not None:
            continue

        embedding = get_code_embedding(function.source)

        if embedding is None:
            continue

        function.embedding = embedding
        function.embedding_model = DEFAULT_MODEL

    session.commit()