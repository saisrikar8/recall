"""Source -> persisted Silver -> model-specific Gold -> atomic publication."""
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import math

from sqlalchemy import delete, select, text as sql_text

from src import database as db, semantic_search, visual, scene_search
from src.extraction import extract_document, read_content
from src.models import Chunk, Embedding, Entity, Extraction, File, Function, VisualEmbedding
from src.profiling import measure
from src.structure import build_structure, chunks_for, EXTRACTOR_VERSION, CHUNKER_VERSION

MODEL_CONFIGURATION = {'model': semantic_search.DEFAULT_MODEL,
                       'revision': None, 'input_format': 'context-source-v1'}
MODEL_KEY = hashlib.sha256(json.dumps(MODEL_CONFIGURATION, sort_keys=True).encode()).hexdigest()


def ensure_fts(connection):
    connection.exec_driver_sql('CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(text, context)')
    connection.exec_driver_sql('CREATE TRIGGER IF NOT EXISTS chunks_fts_delete AFTER DELETE ON chunks BEGIN DELETE FROM chunk_fts WHERE rowid=old.id; END')


def current(file_id, content_hash):
    with db.get_db() as session:
        extraction = session.scalar(select(Extraction).where(
            Extraction.file_id == file_id, Extraction.content_hash == content_hash,
            Extraction.extractor_version == EXTRACTOR_VERSION,
            Extraction.chunker_version == CHUNKER_VERSION,
            Extraction.status == 'complete', Extraction.is_active.is_(True),
            Extraction.configuration['model_key'].as_string() == MODEL_KEY))
        if extraction is None:
            return False
        file = session.get(File, file_id)
        return (not visual.is_visual(file.relative_path) or
                (extraction.configuration.get('ocr_version') == visual.OCR_VERSION and
                 extraction.configuration.get('visual_model_key') == visual.MODEL_KEY and
                 extraction.configuration.get('scene_model_key') == scene_search.MODEL_KEY))


def fail(prepared, error, report=print):
    with db.get_db() as session, session.begin():
        extraction = session.get(Extraction, prepared.extraction_id)
        if extraction is not None:
            extraction.status, extraction.error = 'failed', str(error)
        file = session.get(File, prepared.file_id)
        if file is not None:
            file.last_error = str(error)
    report(f'Failed {prepared.path}: {error}; previous published results retained')


@dataclass(frozen=True)
class Prepared:
    file_id: int
    path: str
    extraction_id: int
    fingerprint: str
    source_signature: tuple | None


def prepare(file_id, path, content, *, report=print, source_signature=None):
    """Persist extraction/OCR without loading either embedding model."""
    fingerprint = hashlib.sha256(content).hexdigest()
    with db.get_db() as session, session.begin():
        file = session.get(File, file_id)
        candidate = session.scalar(select(Extraction).where(
            Extraction.file_id == file_id, Extraction.content_hash == fingerprint,
            Extraction.extractor_version == EXTRACTOR_VERSION,
            Extraction.chunker_version == CHUNKER_VERSION,
            Extraction.is_active.is_(False)).order_by(Extraction.id.desc()))
        if candidate is None:
            candidate = Extraction(file_id=file_id, content_hash=fingerprint,
                extractor_name='recall', extractor_version=EXTRACTOR_VERSION,
                chunker_version=CHUNKER_VERSION, status='processing', configuration={'silver_complete': False})
            session.add(candidate); session.flush()
            published = session.scalar(select(Extraction).where(
                Extraction.file_id == file_id, Extraction.is_active.is_(True),
                Extraction.content_hash == fingerprint,
                Extraction.extractor_version == EXTRACTOR_VERSION,
                Extraction.chunker_version == CHUNKER_VERSION))
            if (published is not None and file.content_hash == fingerprint
                    and (not visual.is_visual(path) or published.configuration.get('ocr_version') == visual.OCR_VERSION)):
                # A model-only rebuild copies saved Silver into an unpublished
                # generation so partially generated new vectors stay invisible.
                mapping = {}
                for old in sorted(published.entities, key=lambda entity: entity.id):
                    values = {column.name: getattr(old, column.name)
                              for column in Entity.__table__.columns
                              if column.name not in {'id', 'extraction_id', 'parent_id'}}
                    entity = Entity(extraction=candidate, parent=mapping.get(old.parent_id), **values)
                    session.add(entity); session.flush()
                    mapping[old.id] = entity
                    for old_chunk in old.chunks:
                        values = {column.name: getattr(old_chunk, column.name)
                                  for column in Chunk.__table__.columns
                                  if column.name not in {'id', 'entity_id'}}
                        chunk = Chunk(entity=entity, **values)
                        session.add(chunk); session.flush()
                        # A visual-only rebuild must not recompute unchanged text embeddings.
                        for saved in old_chunk.embeddings:
                            if (saved.model_key == scene_search.MODEL_KEY or
                                (saved.model_key == MODEL_KEY and not (visual.is_visual(path) and old.kind in {'file', 'page'}))):
                                values = {column.name: getattr(saved, column.name)
                                          for column in Embedding.__table__.columns
                                          if column.name not in {'id', 'chunk_id'}}
                                session.add(Embedding(chunk=chunk, **values))
                        for saved in old_chunk.visual_embeddings:
                            if saved.model_key == visual.MODEL_KEY:
                                values = {column.name: getattr(saved, column.name)
                                          for column in VisualEmbedding.__table__.columns
                                          if column.name not in {'id', 'chunk_id'}}
                                session.add(VisualEmbedding(chunk=chunk, **values))
                candidate.configuration = {**published.configuration, 'silver_complete': True}
        extraction_id = candidate.id
        silver_complete = candidate.configuration.get('silver_complete', False)
        if visual.is_visual(path) and candidate.configuration.get('ocr_version') != visual.OCR_VERSION:
            silver_complete = False
        candidate.status, candidate.error = 'processing', None
        if visual.is_visual(path):
            session.execute(delete(VisualEmbedding).where(
                VisualEmbedding.chunk_id.in_(select(Chunk.id).join(Chunk.entity).where(
                    Entity.extraction_id == extraction_id)),
                VisualEmbedding.model_key != visual.MODEL_KEY))
        session.execute(delete(Extraction).where(Extraction.file_id == file_id, Extraction.is_active.is_(False), Extraction.id != extraction_id))
    try:
        if not silver_complete:
            document = extract_document(path, content, visual=True, report=report)
            structure = build_structure(document, content)
            with db.get_db() as session, session.begin():
                extraction = session.get(Extraction, extraction_id)
                session.execute(delete(Entity).where(Entity.extraction_id == extraction_id))
                entities = {}
                for item in structure:
                    entity = Entity(extraction=extraction, entity_key=item.key,
                        parent=entities.get(item.parent_key), kind=item.kind, name=item.name,
                        qualified_name=item.qualified_name, language=document.format,
                        docstring=item.docstring, start_line=item.start_line, end_line=item.end_line,
                        start_page=item.page, end_page=item.page)
                    session.add(entity); session.flush()
                    entities[item.key] = entity
                    for position, (kind, text, first, last, begin, end) in enumerate(chunks_for(item)):
                        context = f'{path}\n{item.kind} {item.qualified_name}'
                        session.add(Chunk(entity=entity, position=position, kind=kind, text=text,
                            content_hash=hashlib.sha256(text.encode()).hexdigest(), context=context,
                            start_line=first, end_line=last, start_page=item.page, end_page=item.page,
                            start_char=begin, end_char=end))
                extraction.configuration = {'silver_complete': True, 'warnings': list(document.warnings), **document.metadata,
                    **({'ocr_version': visual.OCR_VERSION} if visual.is_visual(path) else {})}
            for warning in document.warnings:
                report(f'{path}: {warning}')
        return Prepared(file_id, str(path), extraction_id, fingerprint, source_signature)
    except Exception as error:
        fail(Prepared(file_id, str(path), extraction_id, fingerprint, source_signature), error, report)
        return None


def _embed_visual(prepared, report):
    path, fingerprint, extraction_id = prepared.path, prepared.fingerprint, prepared.extraction_id
    content = read_content(path)
    if hashlib.sha256(content).hexdigest() != fingerprint:
        raise ValueError('Source changed during processing; rerun indexing')
    if visual.is_visual(path):
        # Anchor image vectors to page overview chunks, separate from text's model key.
        # Render from the exact bytes that produced Silver, not a possibly changed file.
        with db.get_db() as session:
            pages = dict(session.execute(select(Entity.start_page, Chunk.id).join(Chunk.entity).where(
                Entity.extraction_id == extraction_id, Entity.kind == 'page', Chunk.kind == 'overview')).all())
        completed = set()
        for page, image, _ in visual.iter_pages(path, content):
            if page not in pages:
                raise ValueError(f'No saved page entity for visual page {page}')
            chunk_id = pages[page]
            input_hash = hashlib.sha256(f'{fingerprint}:{page}:{visual.MODEL_KEY}'.encode()).hexdigest()
            with db.get_db() as session:
                exists = session.scalar(select(VisualEmbedding.id).where(VisualEmbedding.chunk_id == chunk_id,
                    VisualEmbedding.model_key == visual.MODEL_KEY, VisualEmbedding.input_hash == input_hash))
            if exists is None:
                report(f'Visual embedding {path}: page {page}')
                vector = visual.embed_image(image)
                with db.get_db() as session, session.begin():
                    store_visual(session, chunk_id, vector, input_hash)
            completed.add(page)
        if completed != set(pages):
            raise ValueError('Visual page count does not match saved extraction')

def complete(prepared, *, encoder=None, report=print, visual_ready=False):
    """Embed text and atomically publish a prepared file; failures keep old Gold."""
    encoder = encoder or semantic_search.get_code_embedding
    file_id, path = prepared.file_id, prepared.path
    extraction_id, fingerprint = prepared.extraction_id, prepared.fingerprint
    source_signature = prepared.source_signature
    try:
        if visual.is_visual(path) and not visual_ready:
            _embed_visual(prepared, report)
            if prepared.file_id in embed_scene_group([prepared],report=report):
                return False
        # Read saved Silver: retries and model changes need not rerun extraction.
        with db.get_db() as session:
            statement = select(Chunk.id, Chunk.text, Chunk.context,
                Entity.name, Entity.kind).join(Chunk.entity).where(Entity.extraction_id == extraction_id)
            if visual.is_visual(path):
                # Page/file placeholders carry no actual content. OCR passages provide
                # text retrieval; page overviews carry the visual matrices instead.
                statement = statement.where(Entity.kind.not_in(['file', 'page']))
            rows = session.execute(statement).all()
        report(f'Text embeddings {path}: {len(rows)} passages')
        pending=[]
        with db.get_db() as session:
            saved={row.chunk_id:row.input_hash for row in session.execute(select(Embedding.chunk_id,Embedding.input_hash)
                .join(Embedding.chunk).join(Chunk.entity).where(Entity.extraction_id==extraction_id,Embedding.model_key==MODEL_KEY))}
        for chunk_id,text,context,name,kind in rows:
            input_text=context+'\n\n'+text
            input_hash=hashlib.sha256(input_text.encode()).hexdigest()
            if saved.get(chunk_id)!=input_hash:pending.append((chunk_id,input_text,input_hash,name,kind))
        use_batches=encoder is semantic_search.get_code_embedding
        import os
        if use_batches:
            import torch
            default_size='4' if torch.backends.mps.is_available() or torch.cuda.is_available() else '2'
            size=max(1,min(16,int(os.environ.get('RECALL_TEXT_BATCH_SIZE',default_size))))
        else:size=1
        if use_batches:pending.sort(key=lambda item:len(item[1]))
        for offset in range(0,len(pending),size):
            batch=pending[offset:offset+size]
            with measure('text-embedding-batch',path=str(path),items=len(batch)):
                vectors=semantic_search.get_code_embeddings([item[1] for item in batch]) if use_batches else [encoder(item[1]) for item in batch]
            if len(vectors)!=len(batch):raise ValueError('Wrong number of text embeddings')
            for vector in vectors:
                if not isinstance(vector,list) or not vector or any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in vector):
                    raise ValueError('Embedding model returned an invalid vector')
            with db.get_db() as session,session.begin():
                for (chunk_id,_,input_hash,_,_),vector in zip(batch,vectors):
                    session.add(Embedding(chunk_id=chunk_id,model_key=MODEL_KEY,
                        model_name=semantic_search.DEFAULT_MODEL,model_revision=None,
                        configuration=MODEL_CONFIGURATION,dimensions=len(vector),vector=vector,input_hash=input_hash))
        if source_signature is not None:
            from pathlib import Path
            current_stat = Path(path).stat()
            if (current_stat.st_mtime_ns, current_stat.st_size) != source_signature:
                from src.extraction import read_content
                if hashlib.sha256(read_content(path)).hexdigest() != fingerprint:
                    raise ValueError('Source changed during processing; rerun indexing')
        # Publish only after all Gold rows are complete. Prior generations and
        # failed Silver remain available for diagnostics; search filters active.
        with db.get_db() as session, session.begin():
            file = session.get(File, file_id)
            previous = session.scalars(select(Extraction).where(
                Extraction.file_id == file_id, Extraction.is_active.is_(True))).all()
            for old in previous:
                session.execute(sql_text('DELETE FROM chunk_fts WHERE rowid IN '
                    '(SELECT chunks.id FROM chunks JOIN entities ON entities.id=chunks.entity_id WHERE entities.extraction_id=:id)'), {'id': old.id})
                old.is_active = False
            session.flush()
            extraction = session.get(Extraction, extraction_id)
            extraction.status = 'complete'
            extraction.is_active = True
            extraction.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            extraction.configuration = {**extraction.configuration, 'model_key': MODEL_KEY,
                **({'visual_model_key': visual.MODEL_KEY, 'scene_model_key':scene_search.MODEL_KEY} if visual.is_visual(path) else {})}
            chunks = session.execute(select(Chunk.id, Chunk.text, Chunk.context).join(Chunk.entity).where(Entity.extraction_id == extraction_id))
            for chunk_id, text, context in chunks:
                session.execute(sql_text('INSERT OR REPLACE INTO chunk_fts(rowid,text,context) VALUES (:id,:text,:context)'),
                                {'id': chunk_id, 'text': text, 'context': context})
            # Drop the old compatibility records once their replacement is visible.
            session.execute(delete(Function).where(Function.file_id == file_id))
            session.flush()
            session.execute(delete(Extraction).where(Extraction.file_id == file_id, Extraction.id != extraction_id))
            file.content_hash = fingerprint
            file.indexed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            file.last_error = None
        return True
    except Exception as error:
        fail(prepared, error, report)
        return False


def process(file_id, path, content, *, encoder=None, report=print, source_signature=None):
    """One-file interface; directory indexing can defer PDF embedding as a group."""
    prepared = prepare(file_id, path, content, report=report, source_signature=source_signature)
    return prepared is not None and complete(prepared, encoder=encoder, report=report)


def embed_visual_group(prepared_files, *, report=print, batch_size=4):
    """Stream visual pages across files into small batches; return failed file IDs."""
    if batch_size < 1:
        raise ValueError('batch_size must be positive')
    pending, failed = [], set()

    def failure(prepared, error):
        if prepared.file_id not in failed:
            fail(prepared, error, report)
            failed.add(prepared.file_id)

    def flush():
        if not pending:
            return
        try:
            report(f'Embedding PDF page batch ({len(pending)} pages)')
            try:
                vectors = visual.embed_images([item[-1] for item in pending])
                if len(vectors) != len(pending):
                    raise ValueError('Visual model returned the wrong number of vectors')
            except Exception:
                # Isolate a bad page or recover from a batch too large for the device.
                vectors = []
                for prepared, _, _, image in pending:
                    try:
                        vectors.append(visual.embed_image(image))
                    except Exception as error:
                        failure(prepared, error)
                        vectors.append(None)
            for (prepared, chunk_id, input_hash, _), vector in zip(pending, vectors):
                if prepared.file_id in failed:
                    continue
                try:
                    with db.get_db() as session, session.begin():
                        store_visual(session, chunk_id, vector, input_hash)
                except Exception as error:
                    failure(prepared, error)
        finally:
            for *_, image in pending:
                image.close()
            pending.clear()

    try:
        for prepared in prepared_files:
            try:
                content = read_content(prepared.path)
                if hashlib.sha256(content).hexdigest() != prepared.fingerprint:
                    raise ValueError('Source changed during processing; rerun indexing')
                with db.get_db() as session:
                    pages = dict(session.execute(select(Entity.start_page, Chunk.id).join(Chunk.entity).where(
                        Entity.extraction_id == prepared.extraction_id, Entity.kind == 'page',
                        Chunk.kind == 'overview')).all())
                    existing = {row.chunk_id: row.input_hash for row in session.execute(
                        select(VisualEmbedding.chunk_id, VisualEmbedding.input_hash).join(VisualEmbedding.chunk).join(Chunk.entity).where(
                            Entity.extraction_id == prepared.extraction_id, VisualEmbedding.model_key == visual.MODEL_KEY))}
                if pages and all(existing.get(chunk_id)==hashlib.sha256(
                        f'{prepared.fingerprint}:{page}:{visual.MODEL_KEY}'.encode()).hexdigest()
                        for page,chunk_id in pages.items()):
                    report(f'Reused {len(pages)} visual pages: {prepared.path}')
                    continue
                completed = set()
                for page, image, _ in visual.iter_pages(prepared.path, content):
                    if prepared.file_id in failed:
                        break
                    if page not in pages:
                        raise ValueError(f'No saved page entity for visual page {page}')
                    chunk_id = pages[page]
                    input_hash = hashlib.sha256(f'{prepared.fingerprint}:{page}:{visual.MODEL_KEY}'.encode()).hexdigest()
                    if existing.get(chunk_id) != input_hash:
                        # Retain only bounded, aspect-preserving page images between documents.
                        thumbnail = visual.prepare_page(image)
                        pending.append((prepared, chunk_id, input_hash, thumbnail))
                        if len(pending) >= batch_size:
                            flush()
                    completed.add(page)
                if prepared.file_id not in failed and completed != set(pages):
                    raise ValueError('Visual page count does not match saved extraction')
            except Exception as error:
                failure(prepared, error)
        flush()
    finally:
        for *_, image in pending:
            image.close()
    return failed


def store_visual(session, chunk_id, vectors, input_hash):
    from src.multivector import pack
    tokens, dimensions, packed = pack(vectors)
    session.add(VisualEmbedding(chunk_id=chunk_id, model_key=visual.MODEL_KEY,
        model_name=visual.MODEL_NAME, model_revision=visual.MODEL_REVISION,
        configuration=visual.MODEL_CONFIGURATION, dimensions=dimensions, token_count=tokens,
        vectors=packed, input_hash=input_hash))


def embed_scene_group(prepared_files, *, report=print, batch_size=8):
    """Add cheap whole-page scene vectors; retain old text and ColSmol on upgrades."""
    if batch_size<1:
        raise ValueError('batch_size must be positive')
    pending,failed=[],set()
    def flush():
        if not pending:return
        try:
            report(f'Embedding scene batch ({len(pending)} pages)')
            try:
                vectors=scene_search.encode_images([item[-1] for item in pending])
                if len(vectors)!=len(pending):raise ValueError('Wrong number of scene vectors')
                for (prepared,chunk_id,input_hash,_),vector in zip(pending,vectors):
                    value=vector.tolist() if hasattr(vector,'tolist') else vector
                    with db.get_db() as session,session.begin():
                        session.add(Embedding(chunk_id=chunk_id,model_key=scene_search.MODEL_KEY,
                            model_name=scene_search.MODEL_NAME,model_revision=scene_search.MODEL_REVISION,
                            configuration=scene_search.MODEL_CONFIGURATION,dimensions=len(value),
                            vector=value,input_hash=input_hash))
            except Exception as error:
                for prepared,*_ in pending:
                    if prepared.file_id not in failed:
                        fail(prepared,error,report);failed.add(prepared.file_id)
        finally:
            for *_,image in pending:image.close()
            pending.clear()
    try:
        for prepared in prepared_files:
            try:
                content=read_content(prepared.path)
                if hashlib.sha256(content).hexdigest()!=prepared.fingerprint:
                    raise ValueError('Source changed during processing; rerun indexing')
                with db.get_db() as session:
                    pages=dict(session.execute(select(Entity.start_page,Chunk.id).join(Chunk.entity).where(
                        Entity.extraction_id==prepared.extraction_id,Entity.kind=='page',Chunk.kind=='overview')).all())
                    saved={r.chunk_id:r.input_hash for r in session.execute(select(Embedding.chunk_id,Embedding.input_hash)
                        .join(Embedding.chunk).join(Chunk.entity).where(Entity.extraction_id==prepared.extraction_id,
                            Embedding.model_key==scene_search.MODEL_KEY))}
                missing={page:chunk for page,chunk in pages.items() if saved.get(chunk)!=hashlib.sha256(
                    f'{prepared.fingerprint}:{page}:{scene_search.MODEL_KEY}'.encode()).hexdigest()}
                if not missing:continue
                for page,image,_ in visual.iter_pages(prepared.path,content):
                    if page not in missing or prepared.file_id in failed:continue
                    input_hash=hashlib.sha256(f'{prepared.fingerprint}:{page}:{scene_search.MODEL_KEY}'.encode()).hexdigest()
                    pending.append((prepared,missing.pop(page),input_hash,scene_search.prepare_image(image)))
                    if len(pending)>=batch_size:flush()
                if missing:raise ValueError('Missing scene pages')
            except Exception as error:
                if prepared.file_id not in failed:
                    fail(prepared,error,report);failed.add(prepared.file_id)
        flush()
    finally:
        for *_,image in pending:image.close()
    return failed
