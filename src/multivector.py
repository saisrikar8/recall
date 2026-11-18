"""Compact token-vector storage and bounded ColBERT MaxSim scoring."""
import numpy as np


def matrix(value):
    if hasattr(value, 'detach'):
        value = value.detach().cpu().float().numpy()
    result = np.asarray(value, dtype=np.float32)
    if result.ndim == 1:
        result = result[None, :]
    if result.ndim != 2 or min(result.shape) < 1 or not np.isfinite(result).all():
        raise ValueError('Expected a nonempty finite token-vector matrix')
    norms = np.linalg.norm(result, axis=1, keepdims=True)
    if np.any(norms <= 0):
        raise ValueError('Token vectors must have nonzero norms')
    return result / norms


def pack(value):
    value = matrix(value)
    return value.shape[0], value.shape[1], value.astype('<f2').tobytes()


def unpack(data, tokens, dimensions):
    if tokens < 1 or dimensions < 1 or len(data) != tokens * dimensions * 2:
        raise ValueError('Invalid packed token-vector shape')
    value = np.frombuffer(data, dtype='<f2').reshape(tokens, dimensions).astype(np.float32)
    if not np.isfinite(value).all():
        raise ValueError('Invalid packed token-vector values')
    return value


def score(query, document):
    """Sum, over query tokens, the best document-token similarity."""
    query, document = matrix(query), matrix(document)
    if query.shape[1] != document.shape[1]:
        raise ValueError('Token-vector dimensions do not match')
    best = np.full(query.shape[0], -np.inf, dtype=np.float32)
    for start in range(0, document.shape[0], 256):
        best = np.maximum(best, (query @ document[start:start+256].T).max(axis=1))
    return float(best.sum())
