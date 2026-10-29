import json
import math

from src.profiling import measure

DEFAULT_MODEL = "nomic-ai/CodeRankEmbed"
model = None
loaded_model_name = None
EMBED_QUERY = 'Represent this query for searching relevant code: '


def _encode_local(text, model_name=DEFAULT_MODEL):
    global model, loaded_model_name
    if model is None or loaded_model_name != model_name:
        with measure('model-load', model=model_name):
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer(model_name, trust_remote_code=True)
            loaded_model_name = model_name
    with measure('embedding', input_chars=len(text)):
        return model.encode(text).tolist()


def _encode(text, model_name):
    from src.embedding_service import request_embedding
    remote = request_embedding(text, model_name)
    return remote if remote is not None else _encode_local(text, model_name)


def get_query_embedding(query: str, model_name: str = DEFAULT_MODEL) -> list[float] | None:
    return _encode(EMBED_QUERY + " " + query, model_name)


def get_code_embedding(code: str | None, model_name: str = DEFAULT_MODEL) -> list[float] | None:
    if code is None:
        print("Code could not be loaded for semantic indexing.")
        return None
    return _encode(code, model_name)


def get_similarity(query_embed, code_embed, model_name=DEFAULT_MODEL):
    from torch import tensor
    return tensor(vector_similarity(json.dumps(query_embed), json.dumps(code_embed)))


def embed_indexed_functions(indexed_functions: list[dict], model_name: str = DEFAULT_MODEL) -> list[dict]:
    for function in indexed_functions:
        function['embedding'] = get_code_embedding(function['source'], model_name)
        function['embedding-model'] = model_name
    return indexed_functions


def vector_similarity(query_json, code_json) -> float | None:
    """Compare stored vectors; never load or call an embedding model here."""
    if query_json is None or code_json is None:
        return None
    try:
        query = json.loads(query_json)
        code = json.loads(code_json)
        if not query or not code or len(query) != len(code):
            return None
        if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in query + code):
            return None
        norm = math.sqrt(sum(x*x for x in query)) * math.sqrt(sum(x*x for x in code))
        if norm == 0:
            return None
        return max(-1.0, min(1.0, sum(x*y for x, y in zip(query, code)) / norm))
    except (ValueError, TypeError):
        return None
