"""Read-only, global retrieval benchmark over frozen collection question sets."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import time


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--split',choices=['tune','evaluation','all'],default='all')
    args=parser.parse_args()
    import torch
    torch.set_num_threads(2)
    from src.retrieval import search
    from src import semantic_search,visual,scene_search
    from src.query_routing import route_query
    from src.settings import DATABASE_PATH
    # Account separately for startup: measure warm interactive latency thereafter.
    startup=time.perf_counter()
    semantic_search.get_query_embedding('Recall evaluation warmup')
    visual.embed_query('Recall evaluation warmup')
    scene_search.encode_query('Recall evaluation warmup')
    from src.document_search import rerank_text
    rerank_text('Recall evaluation warmup',['A remembered note'])
    startup=time.perf_counter()-startup
    results=[]
    cases=[]
    for file in sorted(Path(__file__).parent.glob('*.json')):
        data=json.loads(file.read_text())
        if 'questions' in data:cases.extend((file.stem,q) for q in data['questions'] if args.split=='all' or q['split']==args.split)
    print('READY',len(cases),'startup',round(startup,2),flush=True)
    for collection,q in cases:
        start=time.perf_counter()
        try:
            raw=search(q['query'],limit=60,threshold=.3)
            rows=[];seen=set()
            for r in raw:
                key=(r['path'],r.get('page'))
                if key not in seen:rows.append(r);seen.add(key)
                if len(rows)>=10:break
            def relevant(r):
                return any(r['collection']==gold['collection'] and r['relative_path']==gold['file'] and
                    (gold.get('page') is None or r.get('page')==gold['page']) for gold in q['expected'])
            rank=next((i for i,r in enumerate(rows,1) if relevant(r)),None)
            item=dict(collection=collection,id=q['id'],split=q['split'],category=q['category'],rank=rank,
                seconds=round(time.perf_counter()-start,4),results=[{k:r.get(k) for k in ('relative_path','collection','name','page','match_type')} for r in rows])
        except Exception as error:item=dict(collection=collection,id=q['id'],split=q['split'],category=q['category'],rank=None,error=str(error),seconds=round(time.perf_counter()-start,4))
        results.append(item)
        print(collection,q['id'],item['rank'],item['seconds'],flush=True)
        summary={}
        for name in sorted({r['collection'] for r in results}):
            subset=[r for r in results if r['collection']==name];times=sorted(r['seconds'] for r in subset)
            summary[name]=dict(count=len(subset),hit1=sum(r['rank']==1 for r in subset)/len(subset),
                hit5=sum(r['rank'] is not None and r['rank']<=5 for r in subset)/len(subset),
                mrr=sum(1/r['rank'] if r['rank'] else 0 for r in subset)/len(subset),
                median_seconds=statistics.median(times),p95_seconds=times[min(len(times)-1,int(.95*len(times)))])
        args.output.write_text(json.dumps(dict(startup_seconds=startup,implementation_sha256=hashlib.sha256(Path(__import__('inspect').getsourcefile(search)).read_bytes()).hexdigest(),summary=summary,results=results),indent=2)+'\n')
    print('SUMMARY',json.dumps(summary),flush=True)

if __name__=='__main__':main()
