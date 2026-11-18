"""Bounded natural-question reranking; exact lookups stay on the fast path."""
import logging
import math
import time
from sqlalchemy import select
from src.models import Chunk
from src import document_search

_retry_after=0.
logger=logging.getLogger(__name__)


def rerank(session,query,records,limit=25):
    global _retry_after
    if len(records)<2 or time.monotonic()<_retry_after:return records
    candidates=records[:limit]
    ids=[r['chunk_id'] for r in candidates if r.get('chunk_id')]
    bodies=dict(session.execute(select(Chunk.id,Chunk.text).where(Chunk.id.in_(ids))).all())
    texts=[r['relative_path']+'\n'+r['name']+'\n'+bodies.get(r.get('chunk_id'),r['source'])[:2200] for r in candidates]
    try:
        values=document_search.rerank_text(query,texts)
        if len(values)!=len(candidates) or not all(math.isfinite(value) for value in values):raise ValueError('Invalid reranker scores')
    except Exception as error:
        _retry_after=time.monotonic()+60
        logger.warning('Optional search reranking unavailable; retaining base ranking: %s',error)
        return records
    ordered=sorted(zip(values,range(len(candidates)),candidates),key=lambda item:(-item[0],item[1]))
    return [item[2] for item in ordered]+records[len(candidates):]
