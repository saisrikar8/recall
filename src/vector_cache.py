"""Bounded, versioned in-memory cosine search over published vectors.

SQLite remains the source of truth. Invalidation uses SQLite's cross-connection
version and this connection's change counter, so publication/removal/editing does
not require a process restart. This cache never persists source text or vectors.
"""
from collections import OrderedDict
import threading
from pathlib import Path
from weakref import WeakKeyDictionary
import numpy as np
from sqlalchemy import select
from src.models import Embedding,Chunk,Entity,Extraction,File,Collection

_lock=threading.RLock()
_cache=OrderedDict()
_versions=WeakKeyDictionary()
MAX_BYTES=64*1024*1024


def _version(session):
    connection=session.connection()
    raw=connection.connection.driver_connection
    engine=connection.engine
    observed=(raw.total_changes,connection.exec_driver_sql('PRAGMA data_version').scalar())
    database=engine.url.database
    files=[]
    if database and database!=':memory:':
        for filename in (database,database+'-wal'):
            try:
                stat=Path(filename).stat();files.append((stat.st_mtime_ns,stat.st_size))
            except FileNotFoundError:files.append(None)
    signature=tuple(files)
    with _lock:
        state=_versions.setdefault(engine,dict(epoch=0,files=signature,connections={}))
        previous=state['connections'].get(id(raw))
        if state['files']!=signature or (previous is not None and previous!=observed):state['epoch']+=1
        state['files']=signature;state['connections'][id(raw)]=observed
        return engine,state['epoch']


def _groups(session,model_key,root):
    key=(_version(session),model_key,root)
    with _lock:
        if key in _cache:
            _cache.move_to_end(key);return _cache[key][0]
        statement=select(Embedding.chunk_id,File.id,Embedding.vector).join(Embedding.chunk).join(Chunk.entity).join(Entity.extraction).join(Extraction.file).join(File.collection).where(
            Embedding.model_key==model_key,Extraction.is_active.is_(True),Extraction.status=='complete')
        if root:statement=statement.where(Collection.root_path==root)
        buckets={}
        for chunk_id,file_id,value in session.execute(statement):
            if not isinstance(value,list) or not value:continue
            try:array=np.asarray(value,dtype=np.float32)
            except (TypeError,ValueError):continue
            if array.ndim!=1 or not np.isfinite(array).all():continue
            norm=np.linalg.norm(array)
            if norm<=0:continue
            buckets.setdefault(len(array),[]).append((chunk_id,file_id,array/norm))
        groups={dimension:(np.array([r[0] for r in rows],dtype=np.int64),
            np.array([r[1] for r in rows],dtype=np.int64),np.stack([r[2] for r in rows])) for dimension,rows in buckets.items()}
        size=sum(sum(item.nbytes for item in group) for group in groups.values())
        # A cache miss is allowed to compute, but oversized collections are not retained.
        if size<=MAX_BYTES:
            # Remove obsolete versions for this engine/model/scope.
            for old in list(_cache):
                if old[0][0] is key[0][0] and old[1:]==key[1:]:_cache.pop(old)
            while _cache and (sum(entry[1] for entry in _cache.values())+size>MAX_BYTES or len(_cache)>=6):_cache.popitem(last=False)
            _cache[key]=(groups,size)
        return groups


def candidates(session,model_key,query,root,limit,threshold,extra=(),excluded=()):
    array=np.asarray(query,dtype=np.float32)
    if array.ndim!=1 or not np.isfinite(array).all() or np.linalg.norm(array)<=0:
        return {int(identity):0. for identity in extra}
    group=_groups(session,model_key,root).get(len(array))
    if group is None:return {int(identity):0. for identity in extra}
    ids,files,matrix=group
    scores=np.clip(matrix@(array/np.linalg.norm(array)),-1,1)
    allowed=~np.isin(files,list(excluded)) if excluded else np.ones(len(ids),dtype=bool)
    positions=np.flatnonzero(allowed & (scores>=threshold))
    order=positions[np.lexsort((ids[positions],-scores[positions]))[:limit]]
    wanted=set(map(int,extra));wanted.update(int(ids[i]) for i in order)
    present=set(map(int,ids))
    return {int(identity):float(value) for identity,value,keep in zip(ids,scores,allowed) if keep and int(identity) in wanted} | {
        int(identity):0. for identity in extra if identity not in present}


def clear():
    with _lock:
        _cache.clear();_versions.clear()
