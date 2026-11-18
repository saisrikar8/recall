"""Build Silver entities and bounded chunks without inference or persistence."""
import ast
from dataclasses import dataclass
import io
from pathlib import Path
import tokenize

from src.extraction import ExtractedDocument

EXTRACTOR_VERSION = 'hierarchy-v1'
CHUNKER_VERSION = 'source-passages-v1'
CHUNK_CHARS = 3000


@dataclass
class StructuralItem:
    key: str
    parent_key: str | None
    kind: str
    name: str
    qualified_name: str
    source: str
    start_line: int | None = None
    end_line: int | None = None
    page: int | None = None
    docstring: str = ''
    overview: str = ''


def build_structure(document: ExtractedDocument, content: bytes):
    path = Path(document.path)
    items = [StructuralItem('file', None, 'file', path.name, str(path), '')]
    if document.format == 'python':
        encoding, _ = tokenize.detect_encoding(io.BytesIO(content).readline)
        text = content.decode(encoding)
        tree = ast.parse(text)
        parents = ['file']
        names = []
        parent_kinds = ['file']
        class Visitor(ast.NodeVisitor):
            def visit_symbol(self, node, kind):
                key = f'{kind}:{node.lineno}:{node.col_offset}:{node.end_lineno}:{node.end_col_offset}'
                qualified = '.'.join([*names, node.name])
                items.append(StructuralItem(key, parents[-1], kind, node.name, qualified,
                    (ast.get_source_segment(text, node) or '') if kind != 'class' else '', node.lineno, node.end_lineno,
                    docstring=ast.get_docstring(node) or ''))
                parents.append(key); names.append(node.name); parent_kinds.append(kind)
                if kind == 'class':
                    for statement in node.body:
                        if isinstance(statement, (ast.Assign, ast.AnnAssign)):
                            field_source = ast.get_source_segment(text, statement) or ''
                            field_key = f'field:{statement.lineno}:{statement.col_offset}'
                            field_name = field_source.split('=', 1)[0].strip()
                            items.append(StructuralItem(field_key, key, 'block', field_name,
                                qualified + '.' + field_name, field_source,
                                statement.lineno, statement.end_lineno))
                self.generic_visit(node)
                parents.pop(); names.pop(); parent_kinds.pop()
            def visit_ClassDef(self, node):
                self.visit_symbol(node, 'class')
            def visit_FunctionDef(self, node):
                self.visit_symbol(node, 'method' if parent_kinds[-1] == 'class' else 'function')
            visit_AsyncFunctionDef = visit_FunctionDef
        Visitor().visit(tree)
        items[0].docstring = ast.get_docstring(tree) or ''
        # Retain top-level assignments/imports that aren't inside named symbols.
        spans = [(node.lineno, node.end_lineno) for node in tree.body
                 if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))]
        lines = text.splitlines(keepends=True)
        begin = 0
        for start, end in sorted(spans) + [(len(lines) + 1, len(lines) + 1)]:
            if begin < start - 1:
                body = ''.join(lines[begin:start - 1])
                if body.strip():
                    items.append(StructuralItem(f'block:{begin}', 'file', 'block', 'module code',
                                                f'{path.name}:module', body, begin + 1, start - 1))
            begin = end
        items[0].start_line, items[0].end_line = 1, max(1, len(lines))
    elif document.format in {'text', 'markdown', 'pdf', 'image'}:
        pages = {}
        for position, unit in enumerate(document.units):
            parent_key = 'file'
            if unit.page is not None:
                parent_key = f'page:{unit.page}'
                if parent_key not in pages:
                    pages[parent_key] = True
                    items.append(StructuralItem(parent_key, 'file', 'page', f'Page {unit.page}',
                                                f'{path.name}:page:{unit.page}', '', page=unit.page))
            if unit.kind == 'visual_page':
                continue
            items.append(StructuralItem(f'passage:{position}', parent_key, 'section' if document.format == 'markdown' else 'passage',
                unit.name or f'Passage {position + 1}', unit.name or f'{path.name}:{position}', unit.text,
                unit.start_line, unit.end_line, unit.page))
    else:
        # Named functions from the validated Tree-sitter parse retain exact
        # ranges. Add container symbols directly from the same grammar.
        from src.code_languages import CODE_LANGUAGES
        from tree_sitter_language_pack import get_parser
        text = content.decode('utf-16') if content.startswith((b'\xff\xfe', b'\xfe\xff')) else content.decode('utf-8-sig')
        source = text.encode()
        tree = get_parser(CODE_LANGUAGES[path.suffix.lower()].parser).parse(source)
        containers = []
        stack = [tree.root_node]
        kinds = {'class_declaration', 'class_definition', 'class_specifier', 'struct_specifier',
                 'struct_item', 'enum_item', 'interface_declaration', 'impl_item', 'object_declaration', 'type_spec'}
        while stack:
            node = stack.pop(); stack.extend(reversed(node.named_children))
            if node.type not in kinds:
                continue
            if node.type == 'type_spec':
                declared_type = node.child_by_field_name('type')
                if declared_type is None or declared_type.type not in {'struct_type', 'interface_type'}:
                    continue
            name_node = node.child_by_field_name('name') or node.child_by_field_name('type')
            if name_node is None:
                name_node = next((n for n in node.named_children if n.type in {'type_identifier', 'simple_identifier'}), None)
            if name_node is None:
                continue
            name = source[name_node.start_byte:name_node.end_byte].decode()
            key = f'container:{node.start_byte}'
            parent = next((c for c in reversed(containers) if c[0] <= node.start_byte and c[1] >= node.end_byte), None)
            qualified = f'{parent[3]}.{name}' if parent else name
            items.append(StructuralItem(key, parent[2] if parent else 'file', 'class', name, qualified,
                                       '', node.start_point.row + 1, node.end_point.row + 1))
            containers.append((node.start_byte, node.end_byte, key, qualified, node))
        receivers = {}
        pending = [tree.root_node]
        while pending:
            node = pending.pop(); pending.extend(node.named_children)
            if node.type != 'method_declaration':
                continue
            receiver = node.child_by_field_name('receiver')
            children = [receiver] if receiver is not None else []
            while children:
                child = children.pop()
                if child.type == 'type_identifier':
                    receivers[node.start_point.row + 1] = source[child.start_byte:child.end_byte].decode()
                    break
                children.extend(child.named_children)
        functions = []
        for position, unit in enumerate(document.units):
            container = next((i for i in reversed(items) if i.kind == 'class' and
                              i.start_line <= unit.start_line and i.end_line >= unit.end_line), None)
            receiver = receivers.get(unit.start_line)
            if receiver:
                container = next((i for i in items if i.kind == 'class' and i.name == receiver), container)
            parent_function = next((i for i in reversed(functions) if
                i.start_line <= unit.start_line and i.end_line >= unit.end_line and
                (i.start_line, i.end_line) != (unit.start_line, unit.end_line)), None)
            parent = parent_function or container or items[0]
            item = StructuralItem(f'function:{position}', parent.key,
                'method' if parent.kind == 'class' else 'function', unit.name,
                f'{parent.qualified_name}.{unit.name}' if parent.kind != 'file' else unit.name,
                unit.text, unit.start_line, unit.end_line, docstring=unit.docstring)
            items.append(item); functions.append(item)
        def contains_symbol(node):
            pending = [node]
            while pending:
                current = pending.pop()
                if current.type in kinds or current.type in CODE_LANGUAGES[path.suffix.lower()].function_nodes:
                    return True
                pending.extend(current.named_children)
            return False

        # Preserve global constants, imports, and executable module statements.
        for node in tree.root_node.named_children:
            if node.type in {'comment', 'line_comment', 'block_comment', 'php_tag'} or contains_symbol(node):
                continue
            body = source[node.start_byte:node.end_byte].decode()
            if body.strip():
                label = body.split('=', 1)[0].strip()[:80]
                items.append(StructuralItem(f'module:{node.start_byte}', 'file', 'block', label,
                                           f'{path.name}:module', body,
                                           node.start_point.row + 1, node.end_point.row + 1))
        fields = {'field_definition', 'field_declaration', 'public_field_definition', 'property_declaration',
                  'property_definition', 'class_variable'}
        for _, _, key, qualified, node in containers:
            body = node.child_by_field_name('body')
            if body is None:
                body = next((child for child in node.named_children if child.type in {
                    'class_body', 'declaration_list', 'field_declaration_list'}), None)
            for child in body.named_children if body is not None else []:
                if child.type not in fields or contains_symbol(child):
                    continue
                field_source = source[child.start_byte:child.end_byte].decode()
                label = field_source.split('=', 1)[0].strip()[:80]
                items.append(StructuralItem(f'field:{child.start_byte}', key, 'block', label,
                                           qualified + '.' + label, field_source,
                                           child.start_point.row + 1, child.end_point.row + 1))
        items[0].start_line, items[0].end_line = 1, max(1, len(text.splitlines()))
    child_names = {}
    for item in items:
        child_names.setdefault(item.parent_key, []).append(f'{item.kind} {item.name}')
    for item in items:
        if item.kind in {'file', 'class', 'page'}:
            children = child_names.get(item.key, [])
            item.overview = '\n'.join([f'{item.kind} {item.qualified_name}', item.docstring, *children])[:CHUNK_CHARS]
    return items


def chunks_for(item):
    if item.overview:
        yield 'overview', item.overview, None, None, None, None
    source = item.source if item.kind not in {'file', 'class', 'page'} else ''
    start = 0
    line = item.start_line
    while start < len(source):
        end = min(start + CHUNK_CHARS, len(source))
        if end < len(source):
            boundary = source.rfind('\n', start, end)
            if boundary > start:
                end = boundary + 1
        text = source[start:end]
        end_line = line + text[:-1].count('\n') if line is not None else None
        if text.strip():
            yield 'body', text, line, end_line, start, end
        if line is not None:
            line += text.count('\n')
        start = end
