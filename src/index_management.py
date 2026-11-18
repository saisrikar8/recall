from pathlib import Path

from sqlalchemy import delete, select

from src.database import get_db
from src.models import Chunk, Collection, Entity, Extraction, File, Function


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


def _reference(value):
    raw = str(value)
    entity = raw.startswith('e:')
    number = raw[2:] if entity else raw
    if not number.isdigit() or int(number) < 1:
        raise ValueError('Use a positive legacy function ID or an e:<entity-id> reference')
    return entity, int(number)


def _active_entities(session, file_id):
    return session.scalars(select(Entity).join(Entity.extraction).where(
        Extraction.file_id == file_id, Extraction.is_active.is_(True)
    ).order_by(Entity.start_line, Entity.id)).all()


def _entity_target(session, entity_id):
    return session.scalar(select(Entity).join(Entity.extraction).where(
        Entity.id == entity_id, Extraction.is_active.is_(True)))


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
                entities = _active_entities(session, entry.id)
                if entities:
                    data = [{'id': f'e:{e.id}', 'entity_id': e.id, 'name': e.name, 'kind': e.kind, 'parent_id': e.parent_id,
                             'start_line': e.start_line, 'end_line': e.end_line,
                             'page': e.start_page} for e in entities]
                    records.append({'path': entry.relative_path, 'entities': data,
                                    'functions': [e for e in data if e['kind'] in {'function', 'method'}]})
                else:
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
        _reference(function_id)
    elif (collection is None and file is None) or (function is not None and file is None):
        raise ValueError('Select --collection, optionally --file and --function, or --function-id.')
    with get_db() as session, session.begin():
        if function_id is not None:
            is_entity, number = _reference(function_id)
            entity = _entity_target(session, number) if is_entity else None
            if is_entity and entity is None:
                raise ValueError(f'Entity ID not indexed: {number}')
            if entity is not None:
                entity.extraction.file.content_hash = None
                session.delete(entity)
                return 'Removed 1 function from the index.'
            target = session.get(Function, number)
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
                entities = [e for e in _active_entities(session, entry.id)
                            if e.kind in {'function', 'method'} and e.name == function]
                matches = entities or session.scalars(select(Function).where(
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
                    if 'entities' in entry:
                        entities = entry['entities']
                        def render(parent_id, depth):
                            for entity in entities:
                                if entity['parent_id'] != parent_id:
                                    continue
                                if entity['kind'] == 'file':
                                    render(entity['entity_id'], depth)
                                    continue
                                location = f"page {entity['page']}" if entity['page'] else f"{entity['start_line']}-{entity['end_line']}"
                                print('    ' + '  ' * depth + f"[{entity['id']}] {entity['kind']} {entity['name']}  :{location}")
                                render(entity['entity_id'], depth + 1)
                        render(None, 0)
                    else:
                        for function in entry['functions']:
                            print(f"    [{function['id']}] {function['name']}  "
                                  f":{function['start_line']}-{function['end_line']}")


def get_function(function_id):
    is_entity, number = _reference(function_id)
    with get_db() as session:
        entity = _entity_target(session, number) if is_entity else None
        if is_entity and entity is None:
            raise ValueError(f'Entity ID not indexed: {number}')
        if entity is not None:
            file = entity.extraction.file
            chunks = list(entity.chunks)
            source = ''.join(chunk.text for chunk in chunks if chunk.kind == 'body')
            if not source:
                source = '\n'.join(chunk.text for chunk in chunks)
            return {'id': f'e:{entity.id}', 'entity_id': entity.id, 'name': entity.name,
                    'path': str(Path(file.collection.root_path) / file.relative_path),
                    'start_line': entity.start_line, 'end_line': entity.end_line,
                    'page': entity.start_page, 'source': source, 'kind': entity.kind}
        function = session.get(Function, number)
        if function is None:
            raise ValueError(f'Function ID not indexed: {function_id}')
        file = function.file
        return {'id': function.id, 'name': function.name,
                'path': str(Path(file.collection.root_path) / file.relative_path),
                'start_line': function.start_line, 'end_line': function.end_line,
                'source': function.source}


def print_function(function):
    location = f"page {function['page']}" if function.get('page') else f"{function['start_line']}-{function['end_line']}"
    print(f"[{function['id']}] {function['name']}  {function['path']}:{location}")
    print(function['source'])
