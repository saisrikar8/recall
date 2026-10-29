import argparse
import ast
import hashlib
import io
import os
import tokenize
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.exc import DatabaseError

from src.database import DATABASE_PATH, get_db, initialize_database, process_file_index, search_db
from src.models import Collection, File, Function
from src.semantic_search import get_code_embedding, DEFAULT_MODEL

SKIP_DIRS = [".git", ".venv", "venv", "__pycache__", '.idea']

def process_file(file: str, content: bytes | None = None) -> dict:
    if not file.endswith(".py"):
        return {}
    try:
        if content is None:
            with open(file, "rb") as pfile:
                content = pfile.read()
        encoding, _ = tokenize.detect_encoding(io.BytesIO(content).readline)
        code = content.decode(encoding)
        code_tree = ast.parse(code, filename=file)
        return {
            file: {
                'hash': hashlib.sha256(content).hexdigest(),
                'functions': [{
                    'name': node.name,
                    'path': file,
                    'start-line': node.lineno,
                    'end-line': node.end_lineno,
                    'docstring': ast.get_docstring(node) or '',
                    'source': ast.get_source_segment(code, node) or '',
                    'embedding': get_code_embedding(ast.get_source_segment(code, node)),
                    'embedding-model': DEFAULT_MODEL
                } for node in ast.walk(code_tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
            }
        }
    except (OSError, UnicodeError, SyntaxError) as error:
        print(f'Encountered error: {error}')
        return {}


def discover_files(file_or_dir: str) -> list[str]:
    """Finish discovery successfully before allowing deletion cleanup."""
    path = Path(file_or_dir).resolve()
    if not path.exists():
        raise FileNotFoundError(f"File/directory not found: {path}")
    if path.is_file():
        if path.suffix != '.py':
            raise ValueError("Please provide a Python file or directory")
        return [str(path)]
    if not path.is_dir():
        raise ValueError(f"Not a file or directory: {path}")

    def fail_on_error(error):
        raise error

    paths = []
    for root, dirs, files in os.walk(path, onerror=fail_on_error):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        paths.extend(str(Path(root) / name) for name in files if name.endswith('.py'))
    return sorted(paths)


def process_file_or_dir(file_or_dir: str) -> dict:
    records = {}
    for path in discover_files(file_or_dir):
        records.update(process_file(path))
    return records

# Deprecated method of matching functions without semantic search
def match_fxns(fxns: list[dict], query:str, limit:int) -> list[dict]:
    scores = list()
    for fxn in fxns:
        name, path, start_line, end_line, docstring, source = fxn.values()
        score = 0
        if query.lower() == name.lower():
            score = 3
        if query.lower() in name.lower() or query.lower() in docstring.lower():
            score += 2
        if query.lower() in source.lower():
            score += 1
        scores.append({
            'name': name,
            'path': path,
            'start-line': start_line,
            'end-line': end_line,
            'docstring': docstring,
            'source': source,
            'score': score,
        })
    return [fxn for fxn in sorted(scores, key=lambda fxn: fxn['score'], reverse=True)[:limit] if fxn['score'] > 0]

def print_fxn(fxn: dict):
    path = fxn.get('relative_path', fxn['path'])
    print(f"{fxn['score']:.3f}  {path}:{fxn['start-line']}-{fxn['end-line']}  {fxn['name']}")
    if fxn.get('collection'):
        print(f"  Collection: {fxn['collection']}")
    lines = fxn['source'].splitlines()
    for line in lines[:6]:
        print(f"    {line[:160]}")
    if len(lines) > 6:
        print('    …')
    print()

def search_index(limit: int, query : str, threshold: float, collection: str | None = None) -> None:
    try:
        if not DATABASE_PATH.is_file():
            raise FileNotFoundError(f"Index not found. Rerun the index command.")
        fxns = search_db(query, limit, threshold, collection)
        for fxn in fxns:
            print_fxn(fxn)
        if len(fxns) == 0:
            print('Function not found')
    except DatabaseError as error:
        print("Index corrupted. Rerun index command. Error: " + str(error))
    except (FileNotFoundError, ValueError) as error:
        print(error)


def update_index(file_or_dir):
    target = Path(file_or_dir).resolve()
    # Complete discovery before deleting any saved records.
    paths = discover_files(str(target))
    single_file = target.is_file()
    root = target.parent if single_file else target
    initialize_database()
    counts = dict(new=0, changed=0, unchanged=0, deleted=0, failed=0)

    with get_db() as session, session.begin():
        collection = session.scalar(select(Collection).where(Collection.root_path == str(root)))
        if collection is None:
            collection = Collection(root_path=str(root))
            session.add(collection)
            session.flush()
        old_files = {file.relative_path: file for file in session.scalars(
            select(File).where(File.collection_id == collection.id))}
        seen = set()
        for path in paths:
            relative = str(Path(path).relative_to(root))
            seen.add(relative)
            old = old_files.get(relative)
            try:
                content = Path(path).read_bytes()
                fingerprint = hashlib.sha256(content).hexdigest()
            except OSError as error:
                print(f'Skipping {path}: {error}')
                if old is not None:
                    old.last_error = str(error)
                counts['failed'] += 1
                continue
            if old is not None and old.content_hash == fingerprint:
                old.last_error = None
                counts['unchanged'] += 1
                continue
            result = process_file(path, content)
            if not result:
                if old is not None:
                    old.last_error = 'Extraction failed; previous indexed contents retained.'
                counts['failed'] += 1
                continue

            # The existing helper inserts a file and its functions. Remove the
            # previous rows explicitly, since the models have no delete cascade.
            if old is not None:
                session.execute(delete(Function).where(Function.file_id == old.id))
                session.execute(delete(File).where(File.id == old.id))
                session.flush()
            process_file_index(session, collection, result[path], relative)
            session.flush()
            saved = session.scalar(select(File).where(
                File.collection_id == collection.id, File.relative_path == relative))
            saved.indexed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            saved.last_error = None
            counts['changed' if old is not None else 'new'] += 1

        # A single-file request must not delete its sibling file records.
        if not single_file:
            for relative in old_files.keys() - seen:
                old = old_files[relative]
                session.execute(delete(Function).where(Function.file_id == old.id))
                session.execute(delete(File).where(File.id == old.id))
                counts['deleted'] += 1
    print('Indexed: ' + ', '.join(f'{value} {name}' for name, value in counts.items()))
    return counts

def main():
    parser = argparse.ArgumentParser(
        prog='Recall',
        description='Searches code files and provides enhanced search on your code'
    )
    parser.add_argument('-f', '--file', help='File/directory to index, or indexed file relative to --collection')
    parser.add_argument('-q', '--query', help='Query to search for')
    parser.add_argument('-l', '--limit', type=int, default=5, help='Limit of results')
    parser.add_argument('--min-threshold', type=float, default=0.4, help='Minimum cosine similarity threshold for search')
    parser.add_argument('--collection', help='Indexed collection root to search')
    parser.add_argument('cmd', choices=['index', 'search', 'serve', 'list', 'remove'])
    parser.add_argument('--tree', action='store_true', help='List collections, files, and functions')
    parser.add_argument('--function', help='Function name to remove from the selected file')
    parser.add_argument('--function-id', type=int, help='Unique indexed function ID to list, search, or remove')
    args = parser.parse_args()
    if args.tree and args.cmd != 'list':
        parser.error('--tree is only valid for list')
    if args.function is not None and args.cmd != 'remove':
        parser.error('--function is only valid for remove')
    if args.function_id is not None:
        if args.cmd not in ('list', 'search', 'remove'):
            parser.error('--function-id is only valid for list, search, or remove')
        if args.function_id < 1:
            parser.error('--function-id must be positive')
        if any(value is not None for value in (args.collection, args.file, args.function, args.query)) or args.tree:
            parser.error('--function-id cannot be combined with --collection, --file, --function, --query, or --tree')
    if args.limit < 1:
        parser.error("--limit must be at least 1")
    if args.cmd == "search" and args.function_id is None and not (args.query or "").strip():
        parser.error("search requires a non-empty --query")
    if not -1.0 <= args.min_threshold <= 1.0:
        parser.error("--min-threshold must be between -1 and 1")
    file_or_dir = args.file if args.file is not None else '.'
    query = args.query
    cmd = args.cmd

    if cmd in ('list', 'search') and args.function_id is not None:
        from src.index_management import get_function, print_function
        try:
            if not DATABASE_PATH.is_file():
                raise ValueError('Index not found. Run the index command first.')
            print_function(get_function(args.function_id))
        except (ValueError, DatabaseError) as error:
            parser.error(str(error))
    elif cmd in ('list', 'remove'):
        from src.index_management import list_index, print_index, remove_index
        try:
            if not DATABASE_PATH.is_file():
                if cmd == 'list' and args.collection is None and args.file is None:
                    print('No collections indexed.')
                    return
                raise ValueError('Index not found. Run the index command first.')
            if cmd == 'list':
                records = list_index(args.collection, args.file)
                print_index(records, args.collection, args.file, args.tree)
            else:
                print(remove_index(args.collection, args.file, args.function, args.function_id))
        except (ValueError, DatabaseError) as error:
            parser.error(str(error))
    elif cmd == 'serve':
        from src.embedding_service import serve
        serve()
    elif cmd == 'index':
        try:
            update_index(file_or_dir)
        except (OSError, ValueError) as error:
            parser.error(str(error))
    elif cmd == 'search':
        search_index(args.limit, query, args.min_threshold, args.collection)



if __name__ == '__main__':
    main()
