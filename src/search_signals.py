"""Model-free search signals: query terms, indexed-file eligibility and references."""
from functools import lru_cache
from collections import Counter
from pathlib import Path
import re
from sqlalchemy import select, or_
from src.models import Chunk, Entity, Extraction, File, Collection
from src.discovery import classify_directory

STOP_WORDS = frozenset('where what which the is are does how a an to for find show me in of why do can was were i my about notes note function method code project question problem vs versus compare comparison difference differences between and or with from'.split())


def terms(query):
    return list(dict.fromkeys(word.casefold() for word in re.findall(r'\w+', query)
                             if word.casefold() not in STOP_WORDS))[:32]


def excluded_file_ids(session, root):
    """Apply current discovery policy to old records without changing the index."""
    @lru_cache(maxsize=None)
    def excluded(directory, owner):
        path = Path(directory)
        try:
            if path.is_dir() and classify_directory(path).skip:
                return True
        except OSError:
            return False
        return path != Path(owner) and path.parent != path and excluded(str(path.parent), owner)
    statement = select(File.id,File.relative_path,Collection.root_path).join(File.collection)
    if root: statement=statement.where(Collection.root_path==root)
    return [identity for identity,relative,owner in session.execute(statement)
            if excluded(str((Path(owner)/relative).parent),owner)]


def reference_chunks(session, query, root):
    """Follow numbered test references to existing same-project declarations.

    This does not infer an assignment statement. It surfaces the implementation
    referenced by the matching numbered tests, with the test as provenance.
    """
    match = re.search(r'\b(?:question|problem|q)\s*0*(\d+)\b',query,re.I)
    if not match:return {}
    number=int(match[1])
    rows=session.execute(select(File,Collection).join(File.collection))
    selected=[]
    query_terms=set(terms(query))
    for file,owner in rows:
        if root and owner.root_path!=root:continue
        path=Path(file.relative_path)
        if not re.fullmatch(rf'(?:q|question[_-]?|problem[_-]?)0*{number}',path.stem,re.I):continue
        parts=path.parts
        project=Path(*parts[:next((i for i,p in enumerate(parts) if p in {'test','tests'}),len(parts)-1)])
        overlap=len(query_terms & set(re.findall(r'\w+',str(project).casefold())))
        selected.append((overlap,file,owner,str(project)))
    if not selected:return {}
    best=max(item[0] for item in selected)
    # Do not choose arbitrarily between similarly numbered unrelated projects.
    if best==0 and len({(item[2].id,item[3]) for item in selected})>1:return {}
    references={}
    for overlap,file,owner,project in selected:
        if overlap!=best:continue
        chunks=session.scalars(select(Chunk).join(Chunk.entity).join(Entity.extraction).where(
            Extraction.file_id==file.id,Extraction.is_active.is_(True)))
        symbols=Counter()
        for chunk in chunks:
            # Named class/constructor references are strong implementation links.
            symbols.update(re.findall(r'\b[A-Z][A-Za-z0-9_]+\b',chunk.text))
        if not symbols:continue
        targets=session.execute(select(Chunk.id,File.relative_path,Entity.qualified_name).join(Chunk.entity).join(Entity.extraction)
            .join(Extraction.file).where(Extraction.is_active.is_(True),File.collection_id==owner.id,
                or_(Entity.name.in_(symbols),Entity.parent.has(Entity.name.in_(symbols))),
                Entity.kind.in_(['class','function','method']))).all()
        strongest=max((max((symbols[part] for part in name.split('.')),default=0) for _,_,name in targets),default=0) or 1
        for chunk_id,relative,name in targets:
            path=Path(relative)
            if {'test','tests'} & set(path.parts):continue
            if project!='.' and not path.is_relative_to(Path(project)):continue
            # The main subject is typically referenced more than setup helpers.
            strength=max((symbols[part] for part in name.split('.')),default=0)/strongest
            if strength>=.6:
                references[chunk_id]=dict(path=str(Path(owner.root_path)/file.relative_path),strength=strength)
    return references


def filename_chunks(session, query, root):
    value=query.strip().strip('"\'').casefold()
    statement=select(File.id,File.relative_path).join(File.collection)
    if root:statement=statement.where(Collection.root_path==root)
    files=[identity for identity,relative in session.execute(statement)
           if value in {relative.casefold(),Path(relative).name.casefold(),Path(relative).stem.casefold()}]
    if not files:return set()
    return set(session.scalars(select(Chunk.id).join(Chunk.entity).join(Entity.extraction).where(
        Extraction.is_active.is_(True),Extraction.file_id.in_(files),Entity.kind=='file',Chunk.kind=='overview')))
