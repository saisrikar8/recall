"""Read-only relevance check using the same file/page grouping as the desktop."""
import argparse
import json
from pathlib import Path
import time
from src.ui import search_operation


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--collection',required=True)
    parser.add_argument('--output',type=Path,default=Path('/tmp/recall-cs61a-evaluation.json'))
    args=parser.parse_args()
    import torch
    torch.set_num_threads(2)
    labels=json.loads(Path(__file__).with_name('cs61a_queries.json').read_text())
    results=[]
    for label in labels:
        started=time.perf_counter()
        rows=search_operation(dict(query=label['query'],collection=args.collection,limit=10,threshold=.3))
        rank=next((i for i,row in enumerate(rows,1) if any(part in row['relative_path'] for part in label['files'])
                   and (not label.get('name') or row['name']==label['name'])),None)
        results.append(dict(query=label['query'],origin=label['origin'],rank=rank,
            seconds=round(time.perf_counter()-started,3),results=[{key:row.get(key) for key in
            ('relative_path','name','kind','page','match_type','reference_path')} for row in rows]))
        print(label['query'],rank,flush=True)
        args.output.write_text(json.dumps(results,indent=2)+'\n')
    print('Hit@1',sum(row['rank']==1 for row in results),'/',len(results))
    print('Hit@5',sum(row['rank'] is not None and row['rank']<=5 for row in results),'/',len(results))

if __name__=='__main__':main()
