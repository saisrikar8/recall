import os
import argparse
from pathlib import Path

def process_file(file: str) -> list[dict] | list:
    if not file.endswith(".py"):
        return []
    with open(file) as pfile:
        code = pfile.read()
    fxn_names = [(line.split('def ')[1].split('(')[0], line_num+1) for line_num, line in enumerate(code.splitlines()) if line.startswith("def ")]
    return [{'name': name, 'path': file, 'line': line} for name,line in fxn_names]

def process_file_or_dir(file_or_dir:str) -> list[dict]:
    if not os.path.exists(file_or_dir):
        print("File/directory not found")
        exit()
    if os.path.isfile(file_or_dir):
        return process_file(file_or_dir)
    fxns = []
    for root, dirs, files in os.walk(file_or_dir):
        for file in files:
            path =  Path(str(root)) / str(file)
            fxns += process_file(str(path))
    return fxns
def main():
    parser = argparse.ArgumentParser(
        prog='Recall',
        description='Searches code files and provides enhanced search on your code'
    )
    parser.add_argument('file_or_dir')
    parser.add_argument('query')
    args = parser.parse_args()
    file_or_dir = args.file_or_dir
    query = args.query

    fxns = process_file_or_dir(file_or_dir)

    found=False
    for fxn in fxns:
        name, path, line = fxn.values()
        if query.lower() in name.lower():
            print(f'{name} - line {line} in {path}')
            found = True
    if not found:
        print('Function not found')

if __name__ == '__main__':
    main()