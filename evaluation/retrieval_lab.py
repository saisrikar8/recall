"""Ablate visual crops, document retrieval, candidate union and rerankers locally."""
import argparse
from collections import defaultdict
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from unittest.mock import patch

import numpy as np
from sqlalchemy import create_engine,event
from src import database as db,document_search,visual
from src.multivector import pack,unpack,score
from src.query_routing import QueryRoute,route_query
from src.retrieval import search
from src.visual_regions import iter_regions,REGION_VERSION


def save(path,value):
    path.write_text(json.dumps(value,indent=2)+'\n')


def identity(path,page):
    return str(path)+'#page='+str(page)


def legacy_route(query):
    import re
    if re.match(r'^(why|how|what|which|when|where|who|explain|describe|compare)\b',query,re.I):
        return QueryRoute('text','Legacy factual prefix')
    return route_query(query)


def expected(item,label):
    return any(part in Path(item['path']).name for part in label['files']) and (
        not label.get('pages') or item['page'] in label['pages'])


def rank_of(ids,pages,label):
    return next((i for i,key in enumerate(ids,1) if expected(pages[key],label)),None)


def rrf(channels,limit=None):
    votes=defaultdict(float)
    for ranking in channels:
        for position,key in enumerate(dict.fromkeys(ranking),1):votes[key]+=1/(60+position)
    ranked=sorted(votes,key=lambda key:(-votes[key],key))
    return ranked if limit is None else ranked[:limit]


def load_corpus(connection):
    pages={}
    sql='''SELECT chunks.id, chunks.text, files.relative_path,collections.root_path,entities.start_page,
           chunks.kind FROM chunks JOIN entities ON entities.id=chunks.entity_id
           JOIN extractions ON extractions.id=entities.extraction_id JOIN files ON files.id=extractions.file_id
           JOIN collections ON collections.id=files.collection_id WHERE extractions.is_active=1 ORDER BY chunks.id'''
    chunks=[]
    for chunk,text,relative,root,page,kind in connection.execute(sql):
        if page is None:continue
        path=str(Path(root)/relative);key=identity(path,page)
        pages.setdefault(key,dict(path=path,page=page,text='',chunk_ids=[]))
        if kind=='body':
            pages[key]['text']+=text+'\n'
            pages[key]['chunk_ids'].append(chunk)
            words=text.split()
            for position, first in enumerate(range(0,len(words),140)):
                chunks.append(dict(id=chunk*1000+position,source_id=chunk,key=key,
                    text=Path(path).name+'\n'+' '.join(words[first:first+180])))
    vectors={}
    sql='''SELECT visual_embeddings.vectors,visual_embeddings.token_count,visual_embeddings.dimensions,
           files.relative_path,collections.root_path,entities.start_page
           FROM visual_embeddings JOIN chunks ON chunks.id=visual_embeddings.chunk_id
           JOIN entities ON entities.id=chunks.entity_id JOIN extractions ON extractions.id=entities.extraction_id
           JOIN files ON files.id=extractions.file_id JOIN collections ON collections.id=files.collection_id
           WHERE extractions.is_active=1 AND visual_embeddings.model_key=?'''
    for data,tokens,dims,relative,root,page in connection.execute(sql,(visual.MODEL_KEY,)):
        vectors[identity(Path(root)/relative,page)]=unpack(data,tokens,dims)
    return pages,chunks,vectors


def build_regions(connection,pages):
    connection.execute('CREATE TABLE IF NOT EXISTS lab_meta(key TEXT PRIMARY KEY,value TEXT)')
    tag=REGION_VERSION+visual.MODEL_KEY
    previous=connection.execute("SELECT value FROM lab_meta WHERE key='region_version'").fetchone()
    if previous is None or previous[0]!=tag:
        connection.execute('DROP TABLE IF EXISTS lab_regions')
        connection.execute("INSERT OR REPLACE INTO lab_meta VALUES('region_version',?)",(tag,))
        connection.commit()
    connection.execute('''CREATE TABLE IF NOT EXISTS lab_regions(
        key TEXT PRIMARY KEY,page_key TEXT,bbox TEXT,kind TEXT,tokens INT,dimensions INT,vectors BLOB)''')
    paths=sorted({page['path'] for page in pages.values()});pending=[];created=0
    def flush():
        nonlocal created
        if not pending:return
        try:
            vectors=visual.embed_images([item[-1] for item in pending])
            for (key,page_key,region,_),value in zip(pending,vectors):
                tokens,dims,packed=pack(value)
                connection.execute('INSERT OR REPLACE INTO lab_regions VALUES(?,?,?,?,?,?,?)',
                    (key,page_key,json.dumps(region.bbox),region.kind,tokens,dims,packed));created+=1
            connection.commit()
        finally:
            for *_,image in pending:image.close()
            pending.clear()
    for path in paths:
        content=Path(path).read_bytes();digest=hashlib.sha256(content).hexdigest()
        for region,image in iter_regions(path,content):
            key=hashlib.sha256((digest+str(region)+visual.MODEL_KEY+REGION_VERSION).encode()).hexdigest()
            page_key=identity(path,region.page)
            # Include the file identity in cache keys: identical documents still map to both paths.
            key=hashlib.sha256((key+path).encode()).hexdigest()
            if connection.execute('SELECT 1 FROM lab_regions WHERE key=?',(key,)).fetchone():continue
            pending.append((key,page_key,region,image.copy()))
            if len(pending)==4:flush()
        print('REGIONS',Path(path).name,created,flush=True)
    flush()
    return [(page_key,json.loads(bbox),kind,unpack(data,tokens,dims)) for page_key,bbox,kind,tokens,dims,data in
            connection.execute('SELECT page_key,bbox,kind,tokens,dimensions,vectors FROM lab_regions')]


def build_text(connection,chunks):
    connection.execute('CREATE TABLE IF NOT EXISTS lab_text(chunk_id INT PRIMARY KEY,model TEXT,vectors BLOB)')
    todo=[c for c in chunks if not connection.execute('SELECT 1 FROM lab_text WHERE chunk_id=? AND model=?',
        (c['id'],document_search.MODEL_REVISION)).fetchone()]
    for first in range(0,len(todo),32):
        batch=todo[first:first+32]
        vectors=document_search.encode_documents([c['text'] for c in batch])
        for c,value in zip(batch,vectors):connection.execute('INSERT OR REPLACE INTO lab_text VALUES(?,?,?)',
            (c['id'],document_search.MODEL_REVISION,value.astype('<f4').tobytes()))
        connection.commit()
    saved={c:np.frombuffer(value,dtype='<f4') for c,value in connection.execute('SELECT chunk_id,vectors FROM lab_text')}
    return np.stack([saved[c['id']] for c in chunks])


def lexical(connection,query,chunks):
    import re
    stop={'a','an','the','of','on','in','to','is','are','was','how','what','where','which','why','can','do','does','i','me','find','show','with','and'}
    terms=[term for term in re.findall(r'\w+',query.lower()) if term not in stop][:24]
    if not terms:return []
    expression=' OR '.join('"'+term+'"' for term in terms)
    matches=connection.execute('SELECT rowid FROM chunk_fts WHERE chunk_fts MATCH ? ORDER BY bm25(chunk_fts) LIMIT 100',(expression,)).fetchall()
    mapping={c['source_id']:c['key'] for c in chunks}
    return list(dict.fromkeys(mapping[c] for c, in matches if c in mapping))


def render_candidate(page,bbox=None):
    import pymupdf
    from PIL import Image
    with pymupdf.open(page['path']) as document:
        source=document[page['page']-1]
        rect=pymupdf.Rect(bbox) if bbox else source.rect
        scale=min(2.,768/max(rect.width,rect.height))
        pix=source.get_pixmap(matrix=pymupdf.Matrix(scale,scale),clip=rect,alpha=False)
        return Image.frombytes('RGB',(pix.width,pix.height),pix.samples)


def run(name,source,output,labels,image_rerank):
    target=output/(name+'.db')
    if not target.exists():
        with sqlite3.connect(source) as original,sqlite3.connect(target) as copy:original.backup(copy)
    connection=sqlite3.connect(target)
    pages,chunks,whole=load_corpus(connection)
    started=time.perf_counter();regions=build_regions(connection,pages);region_seconds=time.perf_counter()-started
    started=time.perf_counter();text_vectors=build_text(connection,chunks);text_seconds=time.perf_counter()-started
    engine=create_engine('sqlite:///'+str(target));event.listen(engine,'connect',db.register_functions)
    results=[]
    with patch.object(db,'engine',engine):
        for label in labels:
            query=label['query'];case=dict(query=query,variants={})
            for mode,router in [('baseline',legacy_route),('routing',route_query)]:
                started=time.perf_counter()
                with patch('src.retrieval.route_query',router):hits=search(query,limit=10,threshold=.3)
                keys=[identity(hit['path'],hit['page']) for hit in hits if hit.get('page')]
                case['variants'][mode]=dict(rank=rank_of(keys,pages,label),seconds=time.perf_counter()-started,top=keys[:10])
            started=time.perf_counter()
            vq=visual.embed_query(query)
            whole_scores={key:score(vq,value) for key,value in whole.items()}
            whole_rank=sorted(whole_scores,key=whole_scores.get,reverse=True)
            region_scores={};best_bbox={}
            for key,bbox,kind,value in regions:
                value=score(vq,value)
                if value>region_scores.get(key,-1e9):region_scores[key]=value;best_bbox[key]=bbox
            region_rank=sorted(region_scores,key=region_scores.get,reverse=True)
            crop_scores={key:max(whole_scores.get(key,-1e9),region_scores.get(key,-1e9)) for key in whole_scores|region_scores}
            crops=sorted(crop_scores,key=crop_scores.get,reverse=True)
            visual_seconds=time.perf_counter()-started
            started=time.perf_counter();tq=document_search.encode_query(query);similarity=text_vectors@tq
            best_text={}
            for i in np.argsort(-similarity):best_text.setdefault(chunks[int(i)]['key'],chunks[int(i)]['text'])
            text_rank=list(best_text)
            text_query_seconds=time.perf_counter()-started
            keywords=lexical(connection,query,chunks)
            visual_intent=route_query(query).channel=='combined'
            doc_only=rrf([text_rank[:100],keywords,whole_rank[:100]]) if visual_intent else rrf([text_rank[:100],keywords])
            # Broad candidate union is measured before cutting down to reranking budgets.
            union=rrf([text_rank[:100],keywords,whole_rank[:160],region_rank[:100]])
            variants={'crops':crops,'document_encoder':doc_only,'candidate_union':union}
            for mode,keys in variants.items():
                case['variants'][mode]=dict(rank=rank_of(keys,pages,label),seconds=visual_seconds+text_query_seconds,top=keys[:10],candidate_recall_at_100=rank_of(keys[:100],pages,label) is not None)
            shortlist=union[:40]
            started=time.perf_counter()
            scores=document_search.rerank_text(query,[best_text.get(key,pages[key]['text'][:1800]) for key in shortlist])
            reranked=[key for _,key in sorted(zip(scores,shortlist),reverse=True)]+union[40:]
            case['variants']['text_reranker']=dict(rank=rank_of(reranked,pages,label),seconds=time.perf_counter()-started,top=reranked[:10],reranked=40)
            if image_rerank and (label.get('visual') or 'picture' in query.lower()):
                # A diverse, bounded shortlist without injecting any expected pages.
                image_shortlist=list(dict.fromkeys(rrf([crops[:8],text_rank[:8],reranked[:8]])))[:8]
                images=[]
                try:
                    for key in image_shortlist:
                        image=render_candidate(pages[key],best_bbox.get(key));images.append(image)
                    documents=[{'image':image,'text':best_text.get(key,pages[key]['text'][:1600])} for key,image in zip(image_shortlist,images)]
                    started=time.perf_counter();scores=document_search.rerank_images(query,documents)
                    keys=[key for _,key in sorted(zip(scores,image_shortlist),reverse=True)]
                    case['variants']['image_reranker']=dict(rank=rank_of(keys,pages,label),seconds=time.perf_counter()-started,top=keys,shortlist_contains_target=rank_of(image_shortlist,pages,label) is not None)
                except Exception as error:
                    case['variants']['image_reranker']=dict(error=str(error))
                finally:
                    for image in images:image.close()
            results.append(case)
            print('QUERY',name,query,{key:value.get('rank') for key,value in case['variants'].items()},flush=True)
            save(output/(name+'-results.json'),dict(corpus=name,regions=len(regions),region_index_seconds=region_seconds,
                document_index_seconds=text_seconds,queries=results))
    connection.close();engine.dispose()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=Path('/tmp/recall-conditional-corpora'))
    parser.add_argument('--output',type=Path,default=Path('/tmp/recall-retrieval-lab'))
    parser.add_argument('--corpora',nargs='+',default=['math','slides'])
    parser.add_argument('--image-rerank',action='store_true')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    import os,torch
    os.environ['RECALL_EMBEDDING_SOCKET']=str(args.output/'no-worker.sock')
    torch.set_num_threads(2)
    labels=json.loads(Path('evaluation/pipeline_queries.json').read_text())
    for name in args.corpora:run(name,args.source/(name+'.db'),args.output,labels[name],args.image_rerank)


if __name__=='__main__':main()
