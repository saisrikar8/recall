"""Freeze the current index for read-only, repeatable evaluation."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from sqlalchemy import select,create_engine
from sqlalchemy.orm import Session
from src.models import Collection,File,Extraction,Entity,Chunk
from src.settings import DATABASE_PATH


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('/tmp/recall-collection-eval'))
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    target=args.output/'snapshot.db'
    if target.resolve()==DATABASE_PATH.resolve():raise ValueError('Snapshot must differ from the live index')
    with closing(sqlite3.connect(DATABASE_PATH.as_uri()+'?mode=ro',uri=True)) as source,closing(sqlite3.connect(target)) as dest:source.backup(dest)
    engine=create_engine('sqlite:///'+str(target.resolve()));items=[]
    with Session(engine) as session:
        statement=select(Collection.root_path,File,Entity,Chunk).join(File,File.collection_id==Collection.id).join(Extraction,Extraction.file_id==File.id).join(Entity,Entity.extraction_id==Extraction.id).join(Chunk,Chunk.entity_id==Entity.id).where(Extraction.is_active.is_(True))
        for root,file,entity,chunk in session.execute(statement):
            items.append(dict(collection=root,file=file.relative_path,entity=entity.name,kind=entity.kind,page=chunk.start_page or entity.start_page,line=chunk.start_line or entity.start_line,chunk=chunk.id,doc=entity.docstring,text=chunk.text[:6000]))
    engine.dispose();(args.output/'content.json').write_text(json.dumps(items)+'\n')
    print(target)

if __name__=='__main__':main()
