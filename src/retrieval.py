"""Retrieve active text/OCR chunks and compatible visual page embeddings."""
import heapq
import json
import math
from pathlib import Path
import re

from sqlalchemy import exists, func, inspect, select, text, or_, case, literal

from src import database as db, semantic_search, visual, scene_search
from src.models import Chunk, Collection, Embedding, Entity, Extraction, File, Function, VisualEmbedding
from src.query_routing import route_query, scene_intent
from src.search_signals import terms as query_terms, excluded_file_ids, reference_chunks, filename_chunks


def _record(chunk, entity, file, owner, score, match_type='semantic'):
    return {'name': entity.name, 'path': str(Path(owner.root_path) / file.relative_path),
        'relative_path': file.relative_path, 'collection': owner.root_path,
        'start-line': chunk.start_line or entity.start_line,
        'end-line': chunk.end_line or entity.end_line,
        'page': chunk.start_page or entity.start_page,
        'docstring': entity.docstring, 'source': chunk.text, 'score': score if score is not None else 0.,
        'kind': entity.kind, 'entity_id': entity.id, 'chunk_id': chunk.id,
        'qualified_name': entity.qualified_name, 'embedding': None,
        'embedding-model': visual.MODEL_NAME if match_type == 'visual' else semantic_search.DEFAULT_MODEL,
        'match_type': match_type}


def _layers(score, model_key, root):
    statement = (select(Chunk, Entity, File, Collection, score)
        .join(Chunk.entity).join(Entity.extraction).join(Extraction.file).join(File.collection)
        .join(Embedding, Embedding.chunk_id == Chunk.id)
        .where(Extraction.is_active.is_(True), Extraction.status == 'complete',
               Embedding.model_key == model_key))
    return statement.where(Collection.root_path == root) if root else statement


def _keywords(session, query, root):
    # Prefer all meaningful terms; weaker OR matches supplement semantic recall.
    terms = query_terms(query)
    if any(not term.isdigit() for term in terms):
        terms = [term for term in terms if not term.isdigit()]
    if not terms or not inspect(session.connection()).has_table('chunk_fts'):
        return {}, False
    expression = ' AND '.join('"' + term.replace('"', '""') + '"' for term in terms)
    scope = ' AND collections.root_path=:root' if root else ''
    statement = ('SELECT chunk_fts.rowid FROM chunk_fts '
        'JOIN chunks ON chunks.id=chunk_fts.rowid JOIN entities ON entities.id=chunks.entity_id '
        'JOIN extractions ON extractions.id=entities.extraction_id '
        'JOIN files ON files.id=extractions.file_id JOIN collections ON collections.id=files.collection_id '
        "WHERE chunk_fts MATCH :query AND extractions.is_active=1 AND extractions.status='complete'" + scope +
        ' ORDER BY bm25(chunk_fts) LIMIT 100')
    rows = session.execute(text(statement), {'query': expression, 'root': root}).all()
    strict = bool(rows)
    if not rows and len(terms)>1:
        expression = ' OR '.join('"' + term + '"' for term in terms)
        rows = session.execute(text(statement), {'query': expression, 'root': root}).all()
    return {row[0]: position for position, row in enumerate(rows, 1)}, strict


def search(query, limit=5, threshold=.4, collection=None):
    if not query.strip() or limit < 1 or not math.isfinite(threshold) or not -1 <= threshold <= 1:
        raise ValueError('Provide a query, positive limit, and threshold between -1 and 1.')
    root = str(Path(collection).expanduser().resolve()) if collection is not None else None
    with db.get_db() as session:
        if root is not None and session.scalar(select(Collection.id).where(Collection.root_path == root)) is None:
            raise ValueError(f'Collection not indexed: {root}')
        has_layers = inspect(session.connection()).has_table('extractions')
        records, lexical = [], {}
        strict_lexical = False
        excluded = excluded_file_ids(session, root)
        references = reference_chunks(session, query, root) if has_layers else {}
        filenames = filename_chunks(session, query, root) if has_layers else set()
        if filenames and re.search(r'\.[A-Za-z0-9]{1,12}$',query.strip().strip("\"'")):
            statement=(select(Chunk,Entity,File,Collection,literal(1.).label('score'))
                .join(Chunk.entity).join(Entity.extraction).join(Extraction.file).join(File.collection)
                .where(Chunk.id.in_(filenames),File.id.not_in(excluded),Extraction.is_active.is_(True),Extraction.status=='complete')
                .order_by(File.relative_path,File.id).limit(limit))
            matches=[]
            for row in session.execute(statement):
                record=_record(*row,match_type='filename');record['embedding-model']=None;matches.append(record)
            if matches:return matches
        vector = semantic_search.get_query_embedding(query)
        if vector is None:
            raise ValueError('Could not embed query.')
        query_json = json.dumps(vector)
        pool = max(limit * 20, 100)
        if has_layers:
            from src.pipeline import MODEL_KEY
            lexical, strict_lexical = _keywords(session, query, root)
            from src.vector_cache import candidates
            scores=candidates(session,MODEL_KEY,vector,root,pool,threshold,
                extra=set(lexical)|set(references)|filenames,excluded=excluded)
            statement=_layers(literal(0.).label('score'),MODEL_KEY,root).where(Chunk.id.in_(scores),File.id.not_in(excluded))
            for row in session.execute(statement):
                record = _record(*row, match_type='keyword' if row[0].id in lexical else 'semantic')
                record['score']=scores.get(row[0].id,0.)
                if row[0].id in filenames:
                    record['_filename'] = True
                if row[0].id in references:
                    record['reference_path'] = references[row[0].id]['path']
                    record['_reference_strength'] = references[row[0].id]['strength']
                    record['match_type'] = 'reference'
                records.append(record)
        score = func.vector_similarity(query_json, Function.embedding).label('score')
        legacy = (select(Function, score).join(Function.file).join(File.collection)
            .where(Function.embedding_model == semantic_search.DEFAULT_MODEL, score >= threshold, File.id.not_in(excluded)))
        if has_layers:
            legacy = legacy.where(~exists(select(Extraction.id).where(
                Extraction.file_id == Function.file_id, Extraction.is_active.is_(True))))
        if root is not None:
            legacy = legacy.where(Collection.root_path == root)
        for function, rank in session.execute(legacy.order_by(score.desc(), Function.id).limit(pool)):
            records.append({'name': function.name,
                'path': str(Path(function.file.collection.root_path) / function.file.relative_path),
                'relative_path': function.file.relative_path, 'collection': function.file.collection.root_path,
                'start-line': function.start_line, 'end-line': function.end_line,
                'docstring': function.docstring, 'source': function.source, 'score': rank,
                'kind': 'function', 'embedding': function.embedding, 'embedding-model': semantic_search.DEFAULT_MODEL,
                'match_type': 'semantic'})
        requested = 'class' if re.search(r'\b(class|struct|interface)\b', query, re.I) else (
            'file' if re.search(r'\b(file|module)\b', query, re.I) else None)
        records.sort(key=lambda r: (-r['score'], 0 if r['kind'] in {'function', 'method', 'section', 'passage', 'block'} else 1, r['path'], r['start-line'] or 0))
        for position, record in enumerate(records, 1):
            rank = 1 / (60 + position) if record['score'] >= threshold else 0
            if record.get('chunk_id') in lexical:
                rank += (1. if strict_lexical else .25) / (60 + lexical[record['chunk_id']])
            if requested and record['kind'] == requested:
                rank += .02
            if (not re.search(r'\btests?\b',query,re.I) and
                    {'test','tests'} & set(Path(record['relative_path']).parts)):
                rank *= .55
            if (record.get('chunk_id') in lexical and
                    re.search(r'\b(?:vs|versus|compare|difference|differences)\b',query,re.I) and
                    Path(record['path']).suffix.lower() in {'.md','.markdown','.txt','.pdf'}):
                rank += .015
            if record.pop('_filename',False):
                rank += 1.
            if record.get('reference_path'):
                rank += .1 * record.pop('_reference_strength', 1.)
            record['_rank'] = rank
        records.sort(key=lambda r: (-r['_rank'], -r['score'], r['path']))
        text_records = _deduplicate(records)
        visual_records = []
        visual_intent = route_query(query).channel == 'combined'
        if (not visual_intent and not strict_lexical and not references and not filenames
                and re.match(r'^(?:how|what|why|explain|describe)\b',query.strip(),re.I)):
            from src.search_reranker import rerank
            text_records=rerank(session,query,text_records)
        if (has_layers
                and inspect(session.connection()).has_table('visual_embeddings')):
            statement = (select(VisualEmbedding, Chunk, Entity, File, Collection)
                .join(VisualEmbedding.chunk).join(Chunk.entity).join(Entity.extraction)
                .join(Extraction.file).join(File.collection)
                .where(VisualEmbedding.model_key == visual.MODEL_KEY,
                       Extraction.is_active.is_(True), Extraction.status == 'complete',File.id.not_in(excluded)))
            if root:
                statement = statement.where(Collection.root_path == root)
            if session.execute(statement.limit(1)).first() is not None:
                from src.multivector import matrix, score as maxsim, unpack
                visual_query = matrix(visual.embed_query(query))
                best = []
                for position, (embedding, chunk, entity, file, owner) in enumerate(
                        session.execute(statement.execution_options(yield_per=4))):
                    document = unpack(embedding.vectors, embedding.token_count, embedding.dimensions)
                    rank = maxsim(visual_query, document)
                    record = _record(chunk, entity, file, owner, rank, match_type='visual')
                    record['source'] = 'Visual match to page ' + str(record['page']) + '. Open the original to view it.'
                    item = (rank, -position, record)
                    if len(best) < pool:
                        heapq.heappush(best, item)
                    elif item[:2] > best[0][:2]:
                        heapq.heapreplace(best, item)
                visual_records = [record for _, _, record in sorted(best, key=lambda item: item[:2], reverse=True)]
        scene_records = []
        if (has_layers and (not visual_intent or scene_intent(query)) and session.execute(
                _layers(Embedding.id, scene_search.MODEL_KEY, root).where(File.id.not_in(excluded)).limit(1)).first() is not None):
            from src.vector_cache import candidates
            scene_scores=candidates(session,scene_search.MODEL_KEY,scene_search.encode_query(query),root,pool,-1.,excluded=excluded)
            statement=_layers(literal(0.).label('score'),scene_search.MODEL_KEY,root).where(Chunk.id.in_(scene_scores),File.id.not_in(excluded))
            for row in session.execute(statement):
                record = _record(*row, match_type='visual')
                record['score']=scene_scores.get(row[0].id,0.)
                record['embedding-model'] = scene_search.MODEL_NAME
                record['visual_source'] = 'scene'
                record['source'] = 'Visual match to page ' + str(record['page']) + '. Open the original to view it.'
                scene_records.append(record)
            scene_records.sort(key=lambda row:(-row['score'],row['chunk_id']))
        # Every query can describe an image or handwriting without saying "image".
        # Fuse channel ranks, never unlike cosine/MaxSim scores. Keep the leading
        # evidence from each channel visible so text-rich PDF consensus cannot
        # bury a relevant image with no readable OCR text.
        merged = {}
        channels = ((text_records, visual_records) if visual_intent and not scene_intent(query)
                    else (text_records, visual_records, scene_records))
        for channel in channels:
            weight = 3. if not visual_intent and channel is text_records else 1.
            for position, record in enumerate(_deduplicate(channel), 1):
                key = _identity(record)
                if key not in merged:
                    merged[key] = [dict(record), 0.]
                if record['match_type'] == 'visual' and merged[key][0]['match_type'] != 'visual':
                    merged[key][0]['match_type'] = 'hybrid'
                    merged[key][0]['visual_score'] = record['score']
                merged[key][1] += weight / (60 + position)
        fused = [value[0] for value in sorted(merged.values(), key=lambda value: -value[1])]
        if scene_intent(query):
            leaders = scene_records[:1]
        elif visual_intent:
            leaders = []
        else:
            # Factual/code text leaders retain their position; image evidence is
            # independently eligible even when text hits already exist.
            corroborated_visual = (not strict_lexical and not references and not filenames and
                visual_records and scene_records and _identity(visual_records[0]) == _identity(scene_records[0]))
            # Cross-model agreement can surface OCR-free handwriting; a single
            # visual channel no longer gets an unconditional reserved position.
            leaders = visual_records[:1] + text_records[:1] if corroborated_visual else text_records[:1]
        selected = _deduplicate(leaders + fused)
        return [_refine(query, record) for record in selected[:limit]]


def _identity(record):
    return (record['path'], ('page', record['page']) if record.get('page') else
            ('entity', record.get('entity_id', record['name'])))


def _deduplicate(records):
    selected, seen = [], set()
    for record in records:
        key = _identity(record)
        if key not in seen:
            seen.add(key)
            record.pop('_rank', None)
            selected.append(record)
    return selected

def _refine(query, record):
    """Locate lexical evidence inside a semantic hit, retaining chunk provenance."""
    if record['kind'] in {'file', 'class', 'page'} or record.get('start-line') is None:
        return record
    stop = {'where', 'what', 'which', 'the', 'is', 'are', 'does', 'how', 'a', 'an',
            'to', 'for', 'find', 'show', 'me', 'in', 'of', 'function', 'method'}
    terms = {token.lower() for token in re.findall(r'[\w]+', query) if token.lower() not in stop}
    lines = record['source'].splitlines()
    evidence = []
    for index, line in enumerate(lines):
        words = {token.lower() for token in re.findall(r'[\w]+', line)}
        words |= {part for word in words for part in word.split('_')}
        evidence.append((len(terms & words), index))
    if not evidence:
        return record
    best, index = max(evidence, key=lambda value: (value[0], -value[1]))
    if best == 0:
        return record
    record['match_line'] = record['start-line'] + index
    if len(lines) > 5:
        begin, end = max(0, index - 1), min(len(lines), index + 2)
        record['chunk_start_line'], record['chunk_end_line'] = record['start-line'], record['end-line']
        record['source'] = '\n'.join(lines[begin:end])
        record['start-line'] += begin
        record['end-line'] = record['start-line'] + end - begin - 1
    return record
