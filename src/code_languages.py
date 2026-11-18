"""Explicit code language registry; no parser/model imports at module load."""
from dataclasses import dataclass


@dataclass(frozen=True)
class CodeLanguage:
    name: str
    parser: str
    function_nodes: frozenset[str]


def _language(name, parser, *nodes):
    return CodeLanguage(name, parser, frozenset(nodes))


JS = _language('javascript', 'javascript', 'function_declaration', 'generator_function_declaration',
               'function_expression', 'generator_function', 'arrow_function', 'method_definition')
TS = _language('typescript', 'typescript', *JS.function_nodes)
TSX = _language('typescript', 'tsx', *JS.function_nodes)
CPP = _language('cpp', 'cpp', 'function_definition')

CODE_LANGUAGES = {
    '.py': None,  # Python keeps its stdlib AST extractor and source encodings.
    **dict.fromkeys(('.js', '.jsx', '.mjs', '.cjs'), JS),
    **dict.fromkeys(('.ts', '.mts', '.cts'), TS),
    '.tsx': TSX,
    '.java': _language('java', 'java', 'method_declaration', 'constructor_declaration'),
    '.go': _language('go', 'go', 'function_declaration', 'method_declaration'),
    '.rs': _language('rust', 'rust', 'function_item'),
    '.c': _language('c', 'c', 'function_definition'),
    **dict.fromkeys(('.cpp', '.cc', '.cxx', '.h', '.hpp', '.hh', '.hxx'), CPP),
    '.cs': _language('csharp', 'csharp', 'method_declaration', 'constructor_declaration', 'local_function_statement'),
    '.rb': _language('ruby', 'ruby', 'method', 'singleton_method'),
    '.php': _language('php', 'php', 'function_definition', 'method_declaration'),
    **dict.fromkeys(('.kt', '.kts'), _language('kotlin', 'kotlin', 'function_declaration')),
    '.swift': _language('swift', 'swift', 'function_declaration'),
    **dict.fromkeys(('.sh', '.bash'), _language('bash', 'bash', 'function_definition')),
    '.lua': _language('lua', 'lua', 'function_declaration', 'function_definition'),
}
CODE_SUFFIXES = frozenset(CODE_LANGUAGES)


def extract_code(content: bytes, language: CodeLanguage):
    from src.extraction import ExtractedUnit, ExtractionError
    try:
        from tree_sitter_language_pack import get_parser
    except ImportError as error:
        raise ExtractionError('Code parser dependency missing; reinstall Recall to install its bundled grammars') from error
    # Normalize supported BOM encodings before parsing; byte offsets below refer
    # to normalized UTF-8, while public locations are original source line numbers.
    text = content.decode('utf-16') if content.startswith((b'\xff\xfe', b'\xfe\xff')) else content.decode('utf-8-sig')
    source = text.encode('utf-8')
    if '\x00' in text:
        raise ExtractionError('NUL bytes in source; unsupported source encoding')
    tree = get_parser(language.parser).parse(source)
    if tree.root_node.has_error:
        raise ExtractionError(f'{language.name} parser reported invalid or unsupported syntax')

    def node_text(node):
        return source[node.start_byte:node.end_byte].decode('utf-8')

    def function_name(node):
        name = node.child_by_field_name('name')
        if name is not None:
            return node_text(name), node
        if language.parser in {'c', 'cpp'}:
            declarator = node.child_by_field_name('declarator')
            while declarator is not None:
                if declarator.type in {'identifier', 'field_identifier', 'qualified_identifier',
                                       'destructor_name', 'operator_name'}:
                    return node_text(declarator), node
                declarator = declarator.child_by_field_name('declarator')
        if language.parser == 'kotlin':
            name = next((child for child in node.named_children if child.type == 'simple_identifier'), None)
            if name is not None:
                return node_text(name), node
        parent = node.parent
        if parent is not None and parent.type in {'variable_declarator', 'assignment_expression', 'pair', 'field_definition', 'public_field_definition', 'assignment_statement'}:
            name = (parent.child_by_field_name('name') or parent.child_by_field_name('left')
                    or parent.child_by_field_name('key'))
            if name is not None:
                return node_text(name), parent
        if parent is not None and parent.type == 'export_statement':
            return 'default', node
        return None, node  # Anonymous callbacks are not standalone named functions.

    units, stack = [], [tree.root_node]
    while stack:
        node = stack.pop()
        stack.extend(reversed(node.named_children))
        if node.type not in language.function_nodes:
            continue
        name, span = function_name(node)
        if name is None:
            continue
        previous = span.prev_named_sibling
        comment = ''
        if previous is not None and previous.type in {'comment', 'line_comment', 'block_comment'} and previous.end_point.row >= span.start_point.row - 1:
            comment = node_text(previous)
        end_line = span.end_point.row + (1 if span.end_point.column else 0)
        units.append(ExtractedUnit(text=node_text(span), kind=f'{language.name}_function',
                                   name=name, docstring=comment,
                                   start_line=span.start_point.row + 1,
                                   end_line=max(span.start_point.row + 1, end_line)))
    return tuple(units)
