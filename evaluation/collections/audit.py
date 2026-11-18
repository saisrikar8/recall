"""Source-only judgment audit; does not inspect retrieved rankings."""
import json
from pathlib import Path
import re
ROOT=Path(__file__).parent

def normalized(text):return ' '.join(re.findall(r'\w+',text.casefold()))

def main():
    rows=json.load(open('/tmp/recall-collection-eval/content.json'))
    for name in ['Downloads','cs61a','example_pdfs']:
        path=ROOT/(name+'.json');data=json.loads(path.read_text())
        for q in data['questions']:
            if q['query']=='What is a mutable default argument?':
                q['query']='How do append and extend change a mutable list?'
                q['audit']='Unsupported prompt replaced with a source-supported comparison during tuning.'
            if q['category']=='page topic':
                phrase=normalized(q['query'].removeprefix('Which lecture page explains ').rstrip('?'))
                gold={(r['collection'],r['file'],r['page']) for r in rows if r['file'].endswith('.pdf') and phrase in normalized(r['text'])}
                q['expected']=[dict(collection=c,file=f,page=p) for c,f,p in sorted(gold)] or q['expected']
            elif q['category']=='filename':
                gold={(r['collection'],r['file']) for r in rows if r['kind']=='file' and Path(r['file']).name==q['query'] and '/build/' not in r['file']}
                q['expected']=[dict(collection=c,file=f,page=None) for c,f in sorted(gold)]
            elif q['category']=='docstring paraphrase':
                seed=next((r for r in rows if r['chunk']==q['evidence']['chunk']),None)
                if seed and seed.get('doc'):
                    gold={(r['collection'],r['file']) for r in rows if r.get('doc')==seed['doc'] and '/build/' not in r['file']}
                    q['expected']=[dict(collection=c,file=f,page=None) for c,f in sorted(gold)]
        path.write_text(json.dumps(data,indent=2)+'\n')
if __name__=='__main__':main()
