"""Warm only the search channels needed by this library, off the UI thread."""
import logging
import time

from sqlalchemy import select
from src import database as db
from src.models import Chunk, Embedding, Entity, Extraction, VisualEmbedding

logger = logging.getLogger(__name__)


def warmup_models():
    from src import semantic_search, visual, scene_search, document_search
    import psutil
    process = psutil.Process()
    started = time.perf_counter()
    tasks = [('text', lambda: semantic_search.get_query_embedding('Find a remembered note'))]
    # Empty/new libraries do not pay for unused image models.
    with db.get_db() as session:
        visual_present = session.scalar(select(VisualEmbedding.id)
            .join(VisualEmbedding.chunk).join(Chunk.entity).join(Entity.extraction)
            .where(Extraction.is_active.is_(True), VisualEmbedding.model_key == visual.MODEL_KEY).limit(1))
        scene_present = session.scalar(select(Embedding.id)
            .join(Embedding.chunk).join(Chunk.entity).join(Entity.extraction)
            .where(Extraction.is_active.is_(True), Embedding.model_key == scene_search.MODEL_KEY).limit(1))
    with db.get_db() as session:
        has_content=session.scalar(select(Extraction.id).where(Extraction.is_active.is_(True)).limit(1))
    if has_content:
        tasks.append(('reranker',lambda:document_search.rerank_text('Find a remembered note',['A remembered note'])))
    if visual_present:
        tasks.append(('document', lambda: visual.embed_query('Find a diagram')))
    if scene_present:
        tasks.append(('scene', lambda: scene_search.encode_query('An illustration')))
    channels = {}
    for name, operation in tasks:
        try:
            operation()
            channels[name] = 'ready'
        except Exception as error:
            # Failed downloads must not prevent browsing, previewing, or retries.
            channels[name] = 'unavailable'
            logger.warning('Recall %s warmup failed: %s', name, error)
    result = dict(channels=channels, seconds=round(time.perf_counter()-started, 3),
                  worker_rss_mib=round(process.memory_info().rss / 1024**2, 1))
    logger.info('Recall model warmup: %s', result)
    return result
