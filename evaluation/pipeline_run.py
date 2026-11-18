"""Full real-model pipeline checks against local corpora, never the saved index."""
import argparse
from collections import Counter
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import time

from sqlalchemy import create_engine, event, func, select
from src import database as db, indexing
from src.discovery import discover_files
from src.extraction import DOCUMENT_SUFFIXES, read_content
from src.models import Chunk, Collection, Embedding, Entity, Extraction, File, VisualEmbedding
from src.profiling import MemorySample
from src.retrieval import search


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


@contextmanager
def isolated_database(path):
    previous = db.engine
    engine = create_engine('sqlite:///' + str(path))
    event.listen(engine, 'connect', db.register_functions)
    db.engine = engine
    try:
        yield
    finally:
        db.engine = previous
        engine.dispose()


def run_corpus(name, root, output, judgments, excludes):
    paths = discover_files(root, excludes, supported_suffixes=DOCUMENT_SUFFIXES)
    before = {str(path): hashlib.sha256(read_content(path)).hexdigest() for path in paths}
    def report(message):
        print(f'[{name}] {message}', flush=True)
    with isolated_database(output / f'{name}.db'):
        with MemorySample() as initial:
            counts = indexing.update_index(root, excludes, report=report)
        queries = []
        with MemorySample() as searching:
            for judgment in judgments:
                started = time.perf_counter()
                hits = search(judgment['query'], limit=10, threshold=.3)
                def expected(hit):
                    if 'expected' in judgment:
                        return any(Path(hit['path']).name + ':' + hit['name'] == target for target in judgment['expected'])
                    return (any(part in Path(hit['path']).name for part in judgment['files'])
                            and (not judgment.get('pages') or hit.get('page') in judgment['pages']))
                rank = next((i for i, hit in enumerate(hits, 1) if expected(hit)), None)
                record = dict(query=judgment['query'], rank=rank, seconds=round(time.perf_counter()-started, 3),
                    hits=[{k: hit.get(k) for k in ['path','name','page','kind','match_type','score']} for hit in hits])
                queries.append(record)
                report(f'QUERY rank={rank}: {judgment["query"]}')
        with MemorySample() as repeat:
            second = indexing.update_index(root, excludes, report=report)
        with db.get_db() as session:
            table_counts = {model.__tablename__: session.scalar(select(func.count()).select_from(model))
                            for model in [Collection,File,Extraction,Entity,Chunk,Embedding,VisualEmbedding]}
            errors = session.execute(select(File.relative_path, File.last_error).where(File.last_error.is_not(None))).all()
            ocr = Counter()
            pages = []
            for extraction in session.scalars(select(Extraction).where(Extraction.is_active.is_(True))):
                ocr.update(extraction.configuration.get('ocr_summary', {}))
                for page in extraction.configuration.get('ocr_pages', []):
                    pages.append(dict(file=extraction.file.relative_path, **page))
        unchanged_sources = all(Path(path).is_file() and hashlib.sha256(read_content(path)).hexdigest() == digest
                                for path, digest in before.items())
        labeled = [q for q,j in zip(queries,judgments) if j.get('expected') or j.get('files')]
        metrics = dict(queries=len(labeled), hit_at_1=sum(q['rank']==1 for q in labeled)/len(labeled) if labeled else None,
                       hit_at_5=sum(q['rank'] is not None and q['rank']<=5 for q in labeled)/len(labeled) if labeled else None)
        result = dict(corpus=str(root), discovered=len(paths), unique_content_files=len(set(before.values())), first=counts, repeat=second, counts=table_counts,
            errors=[list(row) for row in errors], sources_unchanged=unchanged_sources,
            ocr_summary=dict(ocr), ocr_pages=pages, queries=queries, retrieval=metrics,
            profiles=[initial.record('index'), searching.record('queries'),repeat.record('unchanged-index')],
            database_bytes=(output / f'{name}.db').stat().st_size)
        result['checks_passed'] = (counts['failed']==0 and len(paths)==table_counts['files']
            and second['unchanged']==len(paths) and not any(second[k] for k in ['new','changed','failed','deleted'])
            and unchanged_sources and table_counts['visual_embeddings']==len(pages))
        save(output / f'{name}-results.json', result)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--corpora', nargs='+', choices=['math','slides','code'], default=['math','slides','code'])
    args = parser.parse_args()
    import torch
    torch.set_num_threads(2)
    root = Path(__file__).resolve().parents[1]
    args.output.mkdir(parents=True, exist_ok=True)
    os.environ['RECALL_EMBEDDING_SOCKET'] = str(args.output / 'isolated-no-worker.sock')
    labels=json.loads((root/'evaluation/pipeline_queries.json').read_text())
    labels['code'] = json.loads((root/'evaluation/queries.json').read_text())
    sources={'math':root/'example_pdfs_2','slides':root/'example_pdfs','code':root}
    summary={}
    for name in args.corpora:
        excludes=[str(root/path) for path in ['example_pdfs','example_pdfs_2','.backups','dist','build']] if name=='code' else []
        summary[name]=run_corpus(name,sources[name],args.output,labels[name],excludes)
        save(args.output/'summary.json',summary)
        print('CORPUS COMPLETE',name,summary[name]['checks_passed'],summary[name]['retrieval'],flush=True)
    print('RESULTS',args.output/'summary.json',flush=True)
    if not all(result['checks_passed'] for result in summary.values()):
        raise SystemExit(1)


if __name__=='__main__':
    main()
