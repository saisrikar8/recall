"""Build transparent, source-grounded development search sets from an index snapshot."""
import hashlib
import json
from pathlib import Path
import re

OUTPUT=Path(__file__).parent
CONTENT=Path('/tmp/recall-collection-eval/content.json')

def split(family):
    return 'tune' if int(hashlib.sha256(family.encode()).hexdigest()[:8],16)%5<2 else 'evaluation'

def main():
    rows=json.loads(CONTENT.read_text())
    roots={Path(row['collection']).name:row['collection'] for row in rows}
    sets={name:[] for name in roots}
    def add(name,query,row,category,family=None):
        if any(x['query'].casefold()==query.casefold() for x in sets[name]):return
        family=family or row['file']
        sets[name].append(dict(id=f'{name}-{len(sets[name])+1:03}',query=query,
            category=category,family=family,split=split(family),expected=[dict(collection=row['collection'],file=row['file'],page=row['page'] if row['file'].endswith('.pdf') else None)],
            evidence=dict(chunk=row['chunk'],text=row['text'][:500]),source='source-grounded template'))
    # Natural concept queries authored from existing CS61A notes and code.
    concepts=[
      ('append vs extend','2.4 - Mutable Data'),('How is mutation different from rebinding a name?','2.4 - Mutable Data'),
      ('What are higher order functions?','1.6 - Higher Order Functions'),('How do closures remember their enclosing environment?','1.6 - Higher Order Functions'),
      ('How does currying turn a two argument function into nested functions?','1.6 - Higher Order Functions'),
      ('How does a recursive function reach its base case?','1.7 - Recursive Functions'),('How does tree recursion branch into smaller problems?','1.7 - Recursive Functions'),
      ('What is the difference between an expression and a statement?','1.2 - Elements'),('How are function arguments evaluated?','1.2 - Elements'),
      ('How does a call expression work?','1.2 - Elements'),('What are local frames in an environment diagram?','1.3 - Defining'),
      ('How do I design a function with one clear purpose?','1.4 Designing'),('How does a while statement repeat a computation?','1.5 - Control'),
      ('What does short circuit evaluation mean?','1.5 - Control'),('How do list comprehensions filter a sequence?','2.2 - Sequences'),
      ('How does sequence unpacking assign values?','2.2 - Sequences'),('How do I slice a list?','2.2 - Sequences'),
      ('How does a data abstraction hide its representation?','2.3 Compound Data'),('How do append and extend change a mutable list?','2.4 - Mutable Data'),
      ('How do two variables share the same list?','2.4 - Mutable Data'),('What is the difference between a class and an instance?','2.5 - Object Oriented'),
      ('How do inherited methods work?','2.5 - Object Oriented'),('What is lazy evaluation?','2.8 - Lazy Evaluation'),
      ('Why do generators delay computation?','2.8 - Lazy Evaluation'),('How does memoization avoid repeated work?','2.9 - Efficiency'),
      ('How do I compare algorithm running times?','2.9 - Efficiency'),('How do linked lists represent recursive data?','2.3 Compound Data'),
      ('How do I count the ways to make change?','hw03.py'),('store digits in a linked list','lab04.py'),
      ('How does accumulate combine a sequence?','hw02.py'),('How does a TankAnt attack bees while protecting another ant?','proj/ants/ants.py'),
      ('what was question 9 in the ants project','proj/ants/ants.py')]
    cs=[r for r in rows if r['collection']==roots.get('cs61a')]
    for query,part in concepts:
        matches=[r for r in cs if part in r['file'] and r['kind'] not in {'file','page'}]
        if matches:
            # These file-level judgments are authored; evidence remains reviewable.
            add('cs61a',query,matches[0],'concept')
    # Function descriptions supply additional evidence-grounded natural questions.
    used=set()
    for r in cs:
        if len(sets['cs61a'])>=75:break
        if r['kind']!='function' or not r.get('doc') or '/tests/' in r['file'] or '/build/' in r['file']:continue
        if r['entity'] in used or r['entity'].startswith('_'):continue
        doc=r['doc'].split('>>>')[0].strip().split('\n\n')[0]
        if len(doc)<35 or 'LOCKED' in doc:continue
        used.add(r['entity'])
        add('cs61a','Where is the code that '+doc[:200].rstrip('.').removeprefix('Return ').removeprefix('Returns ')+'?',r,'docstring paraphrase')
    used=set()
    for r in cs:
        if len(sets['cs61a'])>=100:break
        if r['kind']!='file' or r['file'] in used or '/build/' in r['file'] or '/tests/' in r['file']:continue
        used.add(r['file']);add('cs61a',Path(r['file']).name,r,'filename')
    # Ten slide decks: ten distinct page topics per deck, with exact page evidence.
    pdf=[r for r in rows if r['collection']==roots.get('example_pdfs') and r['kind']=='passage' and len(r['text'])>100]
    files=sorted({r['file'] for r in pdf})
    for file in files:
        candidates=[]
        for r in pdf:
            if r['file']!=file:continue
            lines=[line.strip(' •\t') for line in r['text'].splitlines() if line.strip()]
            if not lines:continue
            title=' '.join(lines[:2])
            if any(x in title.casefold() for x in ['course plan','midterm','topic calendar','announcements','https://','http://']):continue
            if len(title)<18 or len(title)>180:continue
            candidates.append((r,title))
        selected=[]
        for r,title in candidates:
            if any(abs(r['page']-other['page'])<3 for other,_ in selected):continue
            selected.append((r,title))
            if len(selected)==10:break
        if len(selected)<10:
            for item in candidates:
                if item not in selected:selected.append(item)
                if len(selected)==10:break
        for r,title in selected[:10]:
            add('example_pdfs','Which lecture page explains '+title.rstrip('?.')+'?',r,'page topic',family=file)
    # The single Downloads image cannot yield independent visual subjects.
    image=next(r for r in rows if r['collection']==roots.get('Downloads') and r['kind']=='page')
    descriptions=[
      'handwritten matrices P and C','two two-by-two matrices written on graph paper',
      'a matrix P with 1 and minus 1 on its diagonal','a matrix C containing 1, minus 2, 2, and 1',
      'black handwritten linear algebra on a pale squared background',
      'a small handwritten linear algebra calculation','a diagonal matrix and a second square matrix',
      'P equals one zero zero negative one','C equals one negative two two one',
      'two matrices labeled P and C']
    templates=['Where are my notes showing {}?','Find the image of {}.','Show me {}.','I am looking for {}.']
    for i,template in enumerate(templates):
        for description in descriptions:
            add('Downloads',template.format(description),image,'single-image paraphrase',family='one-handwritten-image')
    # Sixty grounded cross-collection distractors: should retrieve elsewhere, not Downloads.
    others=sets['cs61a'][:30]+sets['example_pdfs'][:30]
    for source in others:
        item=dict(source);item.update(id=f'Downloads-{len(sets["Downloads"])+1:03}',category='cross-collection distractor',
            split=split(source['family']),focus_negative=True)
        sets['Downloads'].append(item)
    for name,items in sets.items():
        assert len(items)==100,(name,len(items))
        assert len({item['query'].casefold() for item in items})==100,name
        for q in items:
            if q['category']=='filename':
                matches={(r['collection'],r['file']) for r in rows if r['kind']=='file' and Path(r['file']).name==q['query'] and '/build/' not in r['file']}
                q['expected']=[dict(collection=root,file=file,page=None) for root,file in sorted(matches)]
        (OUTPUT/(name+'.json')).write_text(json.dumps(dict(collection=roots[name],questions=items),indent=2)+'\n')
        print(name,len(items),{s:sum(q['split']==s for q in items) for s in ['tune','evaluation']})

if __name__=='__main__':main()
