"""Evaluate Recall source in a temporary index; never touches index/index.db."""
import argparse
import contextlib
import io
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, event

from src import database as db, main, semantic_search
from src.models import Base


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='evaluation/results.json')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    cases = json.loads((root / 'evaluation/queries.json').read_text())
    with tempfile.TemporaryDirectory() as temporary:
        engine = create_engine(f'sqlite:///{Path(temporary) / "evaluation.db"}')
        event.listen(engine, 'connect', db.register_functions)
        Base.metadata.create_all(engine)
        try:
            records = {}
            for name in ['main.py', 'database.py', 'semantic_search.py']:
                print(f'Embedding {name}', flush=True)
                extracted = main.process_file(str(root / 'src' / name))
                records[name] = next(iter(extracted.values()))
            report = {'model': semantic_search.DEFAULT_MODEL, 'cases': [], 'summary': {}}
            with patch.object(db, 'engine', engine):
                with contextlib.redirect_stderr(io.StringIO()):
                    db.init_index({'root': str(root / 'src'), 'files': records})
                for case in cases:
                    results = db.search_db(case['query'], threshold=-1., limit=5)
                    hits = [{'symbol': f"{r['relative_path']}:{r['name']}", 'score':r['score']} for r in results]
                    report['cases'].append({**case, 'results':hits})
                    print(case['query'], '->', hits[0]['symbol'] if hits else 'none', flush=True)
            for threshold in [.3, .4, .5]:
                positive = [c for c in report['cases'] if c['expected']]
                negative = [c for c in report['cases'] if not c['expected']]
                correct = sum(any(r['symbol'] in c['expected'] and r['score'] >= threshold
                                  for r in c['results']) for c in positive)
                false_matches = sum(any(r['score'] >= threshold for r in c['results']) for c in negative)
                report['summary'][str(threshold)] = {'hit_at_5':correct/len(positive),
                    'correct_queries':correct, 'positive_queries':len(positive),
                    'no_match_queries_with_results':false_matches, 'no_match_queries':len(negative)}
            Path(args.output).write_text(json.dumps(report, indent=2))
            print(json.dumps(report['summary'], indent=2))
        finally:
            engine.dispose()


if __name__ == '__main__':
    run()
