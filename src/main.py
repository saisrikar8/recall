import json
import os
import argparse
from pathlib import Path
import ast


def process_file(file: str) -> list[dict] | list:
    if not file.endswith(".py"):
        return []
    try:
        with open(file) as pfile:
            code = pfile.read()
            code_tree = ast.parse(code)
        return [{
            'name': node.name,
            'path': file,
            'start-line': node.lineno,
            'end-line': node.end_lineno,
            'docstring': ast.get_docstring(node) or '',
            'source': ast.get_source_segment(code, node) or '',
        }
            for node in ast.walk(code_tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
    except (OSError, UnicodeError, SyntaxError) as error:
        print(f'Encountered error: {error}')
        return []


def process_file_or_dir(file_or_dir: str) -> list[dict]:
    if not os.path.exists(file_or_dir):
        print("File/directory not found")
        exit()
    if os.path.isfile(file_or_dir):
        return process_file(file_or_dir)
    fxns = []
    skip_dirs = [".git", ".venv", "venv", "__pycache__", '.idea']
    for root, dirs, files in os.walk(file_or_dir):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for file in files:
            path = Path(str(root)) / str(file)
            fxns += process_file(str(path))
    return fxns

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
    print(f'{fxn['path']} : {fxn["name"]} - lines {fxn["start-line"]} - {fxn["end-line"]}\n{fxn['source']}')


def main():
    parser = argparse.ArgumentParser(
        prog='Recall',
        description='Searches code files and provides enhanced search on your code'
    )
    parser.add_argument('-f', '--file', help='File or directory to search if indexing', default='.')
    parser.add_argument('-q', '--query', help='Query to search for')
    parser.add_argument('-l', '--limit', type=int, default=5, help='Limit of results')
    parser.add_argument('cmd', choices=['index', 'search'])
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be at least 1")
    if args.cmd == "search" and not (args.query or "").strip():
        parser.error("search requires a non-empty --query")
    file_or_dir = args.file
    query = args.query
    cmd = args.cmd

    if cmd == 'index':
        fxns = process_file_or_dir(file_or_dir)
        with open('index.json', 'w') as f:
            json.dump(fxns, f)
    elif cmd == 'search':
        try:
            with open('index.json') as f:
                index = json.load(f)
            fxns = match_fxns(index, query, args.limit)
            for fxn in fxns:
                print_fxn(fxn)
            if len(fxns) == 0:
                print('Function not found')
        except FileNotFoundError:
            print("Index not found. Run the index command first.")
        except json.JSONDecodeError:
            print("Index corrupted. Rerun the index command first.")


if __name__ == '__main__':
    main()
