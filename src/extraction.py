"""Model-free file extraction. No database or CLI dependencies."""
import ast
from dataclasses import dataclass, field
import hashlib
import io
from pathlib import Path
import re
import tokenize

from src.code_languages import CODE_LANGUAGES, CODE_SUFFIXES, extract_code

DEFAULT_MAX_BYTES = 20 * 1024 * 1024
from src.visual import IMAGE_SUFFIXES

DOCUMENT_SUFFIXES = CODE_SUFFIXES | IMAGE_SUFFIXES | frozenset({'.txt', '.md', '.markdown', '.pdf'})


class ExtractionError(ValueError):
    """A file could not be converted to searchable content."""


@dataclass(frozen=True)
class ExtractedUnit:
    text: str
    kind: str
    name: str = ''
    docstring: str = ''
    start_line: int | None = None
    end_line: int | None = None
    page: int | None = None
    start_char: int | None = None
    end_char: int | None = None


@dataclass(frozen=True)
class ExtractedDocument:
    path: str
    content_hash: str
    format: str
    units: tuple[ExtractedUnit, ...]
    warnings: tuple[str, ...] = ()
    metadata: dict = field(default_factory=dict)


def read_content(path: str | Path, max_bytes: int = DEFAULT_MAX_BYTES) -> bytes:
    """Bound the read itself, including files that grow after stat()."""
    if max_bytes < 1:
        raise ValueError('max_bytes must be positive')
    with open(path, 'rb') as stream:
        content = stream.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise ExtractionError(f'File exceeds the {max_bytes}-byte extraction limit: {path}')
    return content


def extract_python(content: bytes, path: str) -> tuple[ExtractedUnit, ...]:
    encoding, _ = tokenize.detect_encoding(io.BytesIO(content).readline)
    text = content.decode(encoding)
    tree = ast.parse(text, filename=path)
    return tuple(ExtractedUnit(
        text=ast.get_source_segment(text, node) or '', kind='python_function',
        name=node.name, docstring=ast.get_docstring(node) or '',
        start_line=node.lineno, end_line=node.end_lineno,
    ) for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)))


def _decode_text(content):
    if content.startswith((b'\xff\xfe', b'\xfe\xff')):
        text = content.decode('utf-16')
    else:
        text = content.decode('utf-8-sig')
    if '\x00' in text:
        raise ExtractionError('NUL bytes found in a text document; format may be incorrect')
    return text


def _text_units(text, max_chars, *, kind='text', name='', page=None,
                offset=0, full_text=None, line_start=None):
    """Prefer newline boundaries, but also bound individual overlong lines."""
    full_text = text if full_text is None else full_text
    current_line = line_start if line_start is not None else full_text.count("\n", 0, offset) + 1
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            boundary = text.rfind('\n', start, end)
            if boundary > start:
                end = boundary + 1
        part = text[start:end]
        if part.strip():
            absolute_start, absolute_end = offset + start, offset + end
            yield ExtractedUnit(
                text=part, kind=kind, name=name, page=page,
                start_line=current_line,
                end_line=current_line + part[:-1].count('\n'),
                start_char=absolute_start, end_char=absolute_end)
        current_line += part.count("\n")
        start = end


def _markdown_units(text, max_chars):
    start, offset, title, section_line = 0, 0, '', 1
    fence = None
    for number, line in enumerate(text.splitlines(keepends=True), start=1):
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})', line)
        if marker:
            run = marker.group(1)
            if fence is None:
                fence = run
            elif run[0] == fence[0] and len(run) >= len(fence) and not line[marker.end():].strip():
                fence = None
        heading = re.match(r'^ {0,3}#{1,6}\s+(.+?)\s*#*\s*$', line) if fence is None else None
        if heading:
            yield from _text_units(text[start:offset], max_chars, kind='markdown',
                                   name=title, offset=start, full_text=text, line_start=section_line)
            start, title, section_line = offset, heading.group(1), number
        offset += len(line)
    yield from _text_units(text[start:], max_chars, kind='markdown', name=title,
                           offset=start, full_text=text, line_start=section_line)


def _pdf_units(content, max_chars, max_pages):
    try:
        from pypdf import PdfReader
    except ImportError as error:
        raise ExtractionError('PDF extraction requires: pip install "recall-search[documents]"') from error
    try:
        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted:
            raise ExtractionError('Encrypted PDFs require an unlocked copy')
        if len(reader.pages) > max_pages:
            raise ExtractionError(f'PDF exceeds the {max_pages}-page limit')
        units, warnings = [], []
        for number, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ''
            if not text.strip():
                warnings.append(f'Page {number}: no extractable text; it may be blank or require OCR')
            units.extend(_text_units(text, max_chars, kind='pdf', page=number))
        return tuple(units), tuple(warnings)
    except ExtractionError:
        raise
    except Exception as error:
        raise ExtractionError(f'PDF extraction failed: {error}') from error


def extract_document(path: str | Path, content: bytes | None = None, *,
                     max_bytes: int = DEFAULT_MAX_BYTES, max_chars: int = 4000,
                     max_pages: int = 1000, visual: bool = False, report=print) -> ExtractedDocument:
    """Extract one supported document; never embed it or mutate its original."""
    path = Path(path)
    if max_bytes < 1 or max_chars < 1 or max_pages < 1:
        raise ValueError('Extraction limits must be positive')
    suffix = path.suffix.lower()
    if suffix not in DOCUMENT_SUFFIXES:
        raise ExtractionError(f'Unsupported file type: {suffix or "(no extension)"}')
    content = read_content(path, max_bytes) if content is None else content
    if len(content) > max_bytes:
        raise ExtractionError(f'File exceeds the {max_bytes}-byte extraction limit: {path}')
    warnings = ()
    metadata = {}
    try:
        if (visual and suffix == '.pdf') or suffix in IMAGE_SUFFIXES:
            from src.visual import extract_units
            units, warnings = extract_units(path, content, max_chars, max_pages, report, audit=metadata)
            format_name = 'pdf' if suffix == '.pdf' else 'image'
        elif suffix == '.py':
            units, format_name = extract_python(content, str(path)), 'python'
        elif suffix in CODE_LANGUAGES:
            language = CODE_LANGUAGES[suffix]
            units, format_name = extract_code(content, language), language.name
        elif suffix == '.pdf':
            units, warnings = _pdf_units(content, max_chars, max_pages)
            format_name = 'pdf'
        else:
            text = _decode_text(content)
            if suffix in {'.md', '.markdown'}:
                units, format_name = tuple(_markdown_units(text, max_chars)), 'markdown'
            else:
                units, format_name = tuple(_text_units(text, max_chars)), 'text'
    except (UnicodeError, SyntaxError) as error:
        raise ExtractionError(f'Could not extract {path}: {error}') from error
    return ExtractedDocument(str(path), hashlib.sha256(content).hexdigest(),
                             format_name, units, warnings, metadata)


def iter_documents(file_or_dir: str | Path, exclude: list[str] | None = None, **limits):
    """Yield one document at a time; extraction errors propagate to the caller.

    Does not persist or embed anything. Uses the same directory filtering as
    indexing, with extraction's broader set of supported formats.
    """
    from src.discovery import discover_files
    for path in discover_files(str(file_or_dir), exclude, supported_suffixes=DOCUMENT_SUFFIXES):
        yield extract_document(path, **limits)
