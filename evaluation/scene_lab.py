"""Test complementary scene vectors and a diverse image-reranking shortlist."""
import argparse,json,sqlite3,time
from pathlib import Path
import numpy as np
import torch
from src import scene_search,document_search,visual
from src.multivector import unpack,score
from evaluation.retrieval_lab import load_corpus,render_candidate,save,rrf,rank_of,build_text,lexical


def run(name,root,labels,rerank):
    connection=sqlite3.connect(root/(name+'.db'))
    pages,chunks,whole=load_corpus(connection)
    connection.execute('CREATE TABLE IF NOT EXISTS lab_scenes(key TEXT PRIMARY KEY,page_key TEXT,bbox TEXT,vector BLOB)')
    pending=[]
    def flush():
        if not pending:return
        try:
            values=scene_search.encode_images([item[-1] for item in pending])
            for (key,page_key,bbox,_),value in zip(pending,values):connection.execute('INSERT OR REPLACE INTO lab_scenes VALUES(?,?,?,?)',
                (key,page_key,json.dumps(bbox),value.astype('<f4').tobytes()))
            connection.commit()
        finally:
            for *_,image in pending:image.close()
            pending.clear()
    started=time.perf_counter()
    for page_key,page in pages.items():
        key=page_key+':whole'
        if not connection.execute('SELECT 1 FROM lab_scenes WHERE key=?',(key,)).fetchone():
            pending.append((key,page_key,None,render_candidate(page)))
        if len(pending)>=16:flush()
    region_rows=connection.execute('SELECT key,page_key,bbox FROM lab_regions').fetchall()
    for key,page_key,bbox in region_rows:
        key='region:'+key
        if not connection.execute('SELECT 1 FROM lab_scenes WHERE key=?',(key,)).fetchone():
            pending.append((key,page_key,json.loads(bbox),render_candidate(pages[page_key],json.loads(bbox))))
        if len(pending)>=16:flush()
    flush()
    index_seconds=time.perf_counter()-started
    scenes=[(key,json.loads(bbox),np.frombuffer(value,dtype='<f4')) for key,bbox,value in
            connection.execute('SELECT page_key,bbox,vector FROM lab_scenes')]
    regions=[(key,unpack(value,tokens,dims))for key,tokens,dims,value in
             connection.execute('SELECT page_key,tokens,dimensions,vectors FROM lab_regions')]
    text_vectors=build_text(connection,chunks)
    results=[]
    for label in labels:
        if not label.get('visual'):continue
        query=label['query'];started=time.perf_counter()
        sq=scene_search.encode_query(query);scene_scores={}
        for key,bbox,value in scenes:scene_scores[key]=max(scene_scores.get(key,-1e9),float(value@sq))
        scene_rank=sorted(scene_scores,key=scene_scores.get,reverse=True)
        vq=visual.embed_query(query);whole_scores={key:score(vq,value)for key,value in whole.items()}
        region_scores={}
        for key,value in regions:region_scores[key]=max(region_scores.get(key,-1e9),score(vq,value))
        whole_rank=sorted(whole_scores,key=whole_scores.get,reverse=True)
        region_rank=sorted(region_scores,key=region_scores.get,reverse=True)
        tq=document_search.encode_query(query);dots=text_vectors@tq
        best_text={}
        for i in np.argsort(-dots):best_text.setdefault(chunks[int(i)]['key'],chunks[int(i)]['text'])
        text_rank=list(best_text);keywords=lexical(connection,query,chunks)
        union=rrf([text_rank[:100],keywords,whole_rank[:160],region_rank[:100]])
        # Keep consensus candidates and leading scene hits; no judgments enter selection.
        shortlist=list(dict.fromkeys(scene_rank[:6]+union[:30]))[:36]
        record=dict(query=query,scene_rank=rank_of(scene_rank,pages,label),union_rank=rank_of(union,pages,label),
            shortlist_contains_target=rank_of(shortlist,pages,label) is not None,retrieval_seconds=time.perf_counter()-started,
            scene_top=scene_rank[:10],shortlist=shortlist)
        if rerank:
            images=[];ranked=[];times=[]
            try:
                for i,key in enumerate(shortlist):
                    image=render_candidate(pages[key]);images.append(image)
                    start=time.perf_counter()
                    value=document_search.rerank_images(query,[{'image':image,'text':best_text.get(key,'')[:1600]}])[0]
                    times.append(time.perf_counter()-start);ranked.append((value,key));image.close();images.pop()
                    print('IMAGE RERANK',name,len(ranked),'/',len(shortlist),round(times[-1],2),flush=True)
                keys=[key for _,key in sorted(ranked,reverse=True)]
                record.update(image_rerank=rank_of(keys,pages,label),image_top=keys[:10],image_seconds=sum(times),per_candidate_seconds=times)
            except Exception as error:record['image_error']=str(error)
            finally:
                for image in images:image.close()
        results.append(record);save(root/(name+'-scenes.json'),dict(scene_index_seconds=index_seconds,scene_vectors=len(scenes),queries=results))
        print('SCENE RESULT',name,record.get('scene_rank'),record.get('image_rerank'),record.get('image_error'),flush=True)
    connection.close()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=Path('/tmp/recall-retrieval-lab'))
    parser.add_argument('--rerank',action='store_true');args=parser.parse_args();torch.set_num_threads(2)
    labels=json.loads(Path('evaluation/pipeline_queries.json').read_text())
    for name in ['math','slides']:run(name,args.root,labels[name],args.rerank)

if __name__=='__main__':main()
