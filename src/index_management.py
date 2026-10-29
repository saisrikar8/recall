from pathlib import Path

from sqlalchemy import delete, select

from src.database import get_db
from src.models import Collection, File, Function


def _file_path(root, file):
    path = (Path(root) / file).resolve()
    try:
        return str(path.relative_to(Path(root)))
    except ValueError:
        raise ValueError('File must be inside the selected collection.') from None


def _collection(session, root):
    collection = session.scalar(select(Collection).where(
        Collection.root_path == str(Path(root).resolve())))
    if collection is None:
        raise ValueError(f'Collection not indexed: {root}')
    return collection


def _file(session, collection, path):
    file = session.scalar(select(File).where(
        File.collection_id == collection.id,
        File.relative_path == _file_path(collection.root_path, path)))
    if file is None:
        raise ValueError(f'File not indexed: {path}')
    return file


def _file_collection(session, path):
    """Resolve a filesystem path against saved records, including deleted files."""
    absolute = Path(path).expanduser().resolve()
    matches = []
    for collection in session.scalars(select(Collection).order_by(Collection.root_path)):
        try:
            relative = str(absolute.relative_to(Path(collection.root_path)))
        except ValueError:
            continue
        if session.scalar(select(File.id).where(
                File.collection_id == collection.id, File.relative_path == relative)) is not None:
            matches.append(collection)
    if not matches:
        raise ValueError(f'File not indexed: {absolute}')
    if len(matches) > 1:
        roots = ', '.join(item.root_path for item in matches)
        raise ValueError(f'File is indexed in multiple collections; specify --collection: {roots}')
    return matches[0], str(absolute)


def list_index(collection=None, file=None):
    with get_db() as session:
        if file is not None and collection is None:
            inferred, file = _file_collection(session, file)
            collection = inferred.root_path
        collections = [_collection(session, collection)] if collection else session.scalars(
            select(Collection).order_by(Collection.root_path)).all()
        result = []
        for item in collections:
            files = [_file(session, item, file)] if file else session.scalars(
                select(File).where(File.collection_id == item.id).order_by(File.relative_path)).all()
            records = []
            for entry in files:
                functions = session.execute(select(
                    Function.id, Function.name, Function.start_line, Function.end_line
                ).where(Function.file_id == entry.id).order_by(Function.start_line, Function.id))
                records.append({'path': entry.relative_path,
                                'functions': [dict(row._mapping) for row in functions]})
            result.append({'root': item.root_path, 'files': records})
        return result


def remove_index(collection=None, file=None, function=None, function_id=None):
    if function_id is not None:
        if any(value is not None for value in (collection, file, function)):
            raise ValueError('--function-id cannot be combined with collection, file, or function.')
        if function_id < 1:
            raise ValueError('--function-id must be positive.')
    elif (collection is None and file is None) or (function is not None and file is None):
        raise ValueError('Select --collection, optionally --file and --function, or --function-id.')
    with get_db() as session, session.begin():
        if function_id is not None:
            target = session.get(Function, function_id)
            if target is None:
                raise ValueError(f'Function ID not indexed: {function_id}')
            target.file.content_hash = None
            session.delete(target)
            return 'Removed 1 function from the index.'
        if collection is None and file is not None:
            root, file = _file_collection(session, file)
        else:
            root = _collection(session, collection)
        if file is not None:
            entry = _file(session, root, file)
            if function is not None:
                matches = session.scalars(select(Function).where(
                    Function.file_id == entry.id, Function.name == function)).all()
                if len(matches) != 1:
                    raise ValueError('Function not found or name is ambiguous; use list and --function-id.')
                entry.content_hash = None
                session.delete(matches[0])
                return 'Removed 1 function from the index.'
            session.execute(delete(Function).where(Function.file_id == entry.id))
            session.delete(entry)
            return 'Removed 1 file and its functions from the index.'
        files = select(File.id).where(File.collection_id == root.id)
        session.execute(delete(Function).where(Function.file_id.in_(files)))
        session.execute(delete(File).where(File.collection_id == root.id))
        session.delete(root)
        return 'Removed 1 collection and its files and functions from the index.'


def print_index(records, collection=None, file=None, tree=False):
    if not records:
        print('No collections indexed.')
    for root in records:
        print(root['root'])
        if tree or collection or file:
            for entry in root['files']:
                print(f"  {entry['path']}")
                if tree or file:
                    for function in entry['functions']:
                        print(f"    [{function['id']}] {function['name']}  "
                              f":{function['start_line']}-{function['end_line']}")


def get_function(function_id):
    if function_id < 1:
        raise ValueError('--function-id must be positive.')
    with get_db() as session:
        function = session.get(Function, function_id)
        if function is None:
            raise ValueError(f'Function ID not indexed: {function_id}')
        file = function.file
        return {'id': function.id, 'name': function.name,
                'path': str(Path(file.collection.root_path) / file.relative_path),
                'start_line': function.start_line, 'end_line': function.end_line,
                'source': function.source}


def print_function(function):
    print(f"[{function['id']}] {function['name']}  "
          f"{function['path']}:{function['start_line']}-{function['end_line']}")
    print(function['source'])
