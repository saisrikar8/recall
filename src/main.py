"""Command-line parsing and presentation for Recall."""
import argparse
import re

from sqlalchemy.exc import DatabaseError

from src.database import DATABASE_PATH, search_db
from src.indexing import process_file, process_file_or_dir, update_index
from src.profiling import capture


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
    location = f"page {fxn['page']}" if fxn.get('page') else f"{fxn['start-line']}-{fxn['end-line']}"
    print(f"{fxn['score']:.3f}  {path}:{location}  {fxn['name']}")
    if fxn.get('match_type'):
        print(f"  Match: {fxn['match_type']}")
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


def main():
    parser = argparse.ArgumentParser(
        prog='Recall',
        description='Searches code files and provides enhanced search on your code'
    )
    parser.add_argument('-f', '--file', help='Supported source file/directory to index, or indexed file relative to --collection')
    parser.add_argument('-q', '--query', help='Query to search for')
    parser.add_argument('-l', '--limit', type=int, default=5, help='Limit of results')
    parser.add_argument('--min-threshold', type=float, default=0.4, help='Minimum cosine similarity threshold for search')
    parser.add_argument('--collection', help='Indexed collection root to search')
    parser.add_argument('cmd', choices=['index', 'search', 'serve', 'list', 'remove', 'ui'])
    parser.add_argument('--tree', action='store_true', help='List collections, files, and functions')
    parser.add_argument('--function', help='Function name to remove from the selected file')
    parser.add_argument('--function-id', help='Unique indexed function ID to list, search, or remove')
    parser.add_argument('--entity-id', type=int, help='Look up or remove a published entity ID')
    parser.add_argument('--profile', action='store_true', help='Report timing and sampled process RSS to stderr (index or serve)')
    parser.add_argument('--dry-run', action='store_true', help='Dry run')
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Exclude a file or directory. Repeat for multiple paths",
    )
    parser.add_argument('--port', type=int, default=8765, help='Local UI port (default: 8765)')
    parser.add_argument('--no-browser', action='store_true', help='Start UI without opening a browser')
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error('--port must be between 0 and 65535')
    if args.cmd != 'ui' and (args.no_browser or args.port != 8765):
        parser.error('--port and --no-browser require ui')
    if args.profile and (args.cmd not in ('index', 'serve') or args.dry_run):
        parser.error('--profile requires index or serve and cannot be combined with --dry-run')
    if args.tree and args.cmd != 'list':
        parser.error('--tree is only valid for list')
    if args.function is not None and args.cmd != 'remove':
        parser.error('--function is only valid for remove')
    if args.entity_id is not None:
        if args.function_id is not None or args.entity_id < 1:
            parser.error('Use either a positive --entity-id or --function-id')
        args.function_id = f'e:{args.entity_id}'
    if args.function_id is not None:
        if args.cmd not in ('list', 'search', 'remove'):
            parser.error('--function-id is only valid for list, search, or remove')
        if not re.fullmatch(r'(e:)?[1-9][0-9]*', str(args.function_id)):
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
    elif cmd == 'ui':
        from src.ui import serve
        try:
            serve(port=args.port, open_browser=not args.no_browser)
        except (OSError, ValueError) as error:
            parser.error(str(error))
    elif cmd == 'serve':
        from src.embedding_service import serve
        serve(profile=args.profile)
    elif cmd == 'index':
        try:
            with capture(args.profile, label='index-command'):
                update_index(file_or_dir, args.exclude, args.dry_run)
        except (OSError, ValueError) as error:
            parser.error(str(error))
    elif cmd == 'search':
        search_index(args.limit, query, args.min_threshold, args.collection)



if __name__ == '__main__':
    main()
