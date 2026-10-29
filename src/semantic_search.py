from sentence_transformers import SentenceTransformer
from torch import tensor, Tensor
import json
import math

DEFAULT_MODEL = "nomic-ai/CodeRankEmbed"
model = None
loaded_model_name = None
EMBED_QUERY = 'Represent this query for searching relevant code: '

def get_similarity(query_embed: list[float], code_embed: list[float], model_name: str = DEFAULT_MODEL) -> Tensor:
    global model, loaded_model_name
    if model_name == loaded_model_name:
        return model.similarity(tensor(query_embed), tensor(code_embed))
    try:
        model = SentenceTransformer(model_name, trust_remote_code=True)
        loaded_model_name = model_name
        return model.similarity(tensor(query_embed), tensor(code_embed))
    except OSError as e:
        print(f"Model {model_name} could not be loaded: " + str(e))

def get_query_embedding(query: str, model_name: str = DEFAULT_MODEL) -> list[float] | None:
    global model, loaded_model_name
    if model_name == loaded_model_name:
        return model.encode(EMBED_QUERY + " " + query).tolist()
    try:
        model = SentenceTransformer(model_name, trust_remote_code=True)
        loaded_model_name = model_name
        return model.encode(EMBED_QUERY + " " + query).tolist()
    except OSError as e:
        print(f"Model {model_name} could not be loaded: " + str(e))
        return None

def get_code_embedding(code: str | None, model_name: str = DEFAULT_MODEL) -> list[float] | None:
    if code is None:
        print("Code could not be loaded for semantic indexing.")
        return None
    global model, loaded_model_name
    if model_name == loaded_model_name:
        return model.encode(code).tolist()
    try:
        model = SentenceTransformer(model_name, trust_remote_code=True)
        loaded_model_name = model_name
        return model.encode(code).tolist()
    except OSError as e:
        print(f"Model {model_name} could not be loaded: "+str(e))
        return None

# Migrating unindexed functions
def embed_indexed_functions(indexed_functions: list[dict], model_name: str = DEFAULT_MODEL) -> list[dict]:
    global model, loaded_model_name
    if model_name == loaded_model_name:
        print("Default model found!")
    else:
        print("Loading model...")
        try:
            model = SentenceTransformer(model_name, trust_remote_code=True)
            loaded_model_name = model_name
        except OSError as e:
            print(f"Model {model_name} could not be loaded: "+str(e))
    for indexed_function in indexed_functions:
        indexed_function['embedding'] = model.encode(indexed_function['source']).tolist()
        indexed_function['embedding-model'] = loaded_model_name
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
