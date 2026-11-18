import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, event, select

from src import database as db, indexing, semantic_search
from src.extraction import ExtractionError, extract_document
from src.models import Base, File, Function


SAMPLES = {
    'add.js': ('javascript', 'function add(a,b) { return a+b; }'),
    'add.ts': ('typescript', 'function add(a: number,b: number): number { return a+b; }'),
    'View.jsx': ('javascript', 'export const View = () => <div>Hello</div>;'),
    'View.tsx': ('typescript', 'export const View = (props: {name: string}) => <div>{props.name}</div>;'),
    'Main.java': ('java', 'class Main { int add(int a,int b) { return a+b; } }'),
    'add.go': ('go', 'package main\nfunc add(a int,b int) int { return a+b }'),
    'add.rs': ('rust', 'fn add(a:i32,b:i32)->i32 { a+b }'),
    'add.c': ('c', 'int add(int a,int b) { return a+b; }'),
    'add.cpp': ('cpp', 'int Calculator::add(int a,int b) { return a+b; }'),
    'Main.cs': ('csharp', 'class Main { int Add(int a,int b) { return a+b; } }'),
    'add.rb': ('ruby', 'def add(a,b)\n a+b\nend'),
    'add.php': ('php', '<?php function add($a,$b) { return $a+$b; }'),
    'add.kt': ('kotlin', 'fun add(a: Int,b: Int): Int { return a+b }'),
    'add.swift': ('swift', 'func add(_ a: Int,_ b: Int) -> Int { return a+b }'),
    'add.sh': ('bash', 'add() { echo hello; }'),
    'add.lua': ('lua', 'local function add(a,b) return a+b end'),
}


class CodeLanguageTests(unittest.TestCase):
    def test_real_parser_for_every_advertised_language(self):
        for filename, (language, text) in SAMPLES.items():
            with self.subTest(filename=filename):
                doc = extract_document(filename, text.encode())
                self.assertEqual(doc.format, language)
                self.assertEqual(len(doc.units), 1)
                unit = doc.units[0]
                self.assertTrue(unit.name)
                self.assertIn(unit.text, text)
                self.assertGreaterEqual(unit.start_line, 1)
                self.assertGreaterEqual(unit.end_line, unit.start_line)

    def test_methods_arrows_nested_functions_comments_and_utf8_locations(self):
        text = '// useful documentation\nfunction outer() {\n function inner() { return "caf\u00e9"; }\n}\nconst arrow = () => 1;\nclass C { method() { return 2; } }\n'
        doc = extract_document('source.js', text.encode())
        self.assertEqual([u.name for u in doc.units], ['outer', 'inner', 'arrow', 'method'])
        self.assertEqual(doc.units[0].docstring, '// useful documentation')
        self.assertEqual(doc.units[1].start_line, 3)
        self.assertIn('caf\u00e9', doc.units[1].text)

    def test_bom_encodings_and_invalid_syntax(self):
        text = 'function add() { return 1; }'
        for content in (text.encode('utf-16'), text.encode('utf-8-sig')):
            self.assertEqual(extract_document('source.js', content).units[0].name, 'add')
        with self.assertRaises(ExtractionError):
            extract_document('broken.js', b'function broken( {')

    def test_index_search_update_delete_and_same_line_collisions(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(io.StringIO()):
            root = Path(temporary)
            for filename, (_, text) in SAMPLES.items():
                (root / filename).write_text(text)
            (root / 'same.js').write_text('const a = () => 1, b = () => 2;')
            engine = create_engine('sqlite://')
            event.listen(engine, 'connect', db.register_functions)
            try:
                Base.metadata.create_all(engine)
                with patch.object(db, 'engine', engine), \
                     patch.object(indexing, 'get_code_embedding', return_value=[1., 0.]), \
                     patch.object(semantic_search, 'get_query_embedding', return_value=[1., 0.]):
                    counts = indexing.update_index(root)
                    self.assertEqual(counts['new'], len(SAMPLES) + 1)
                    results = db.search_db('add numbers', limit=100)
                    self.assertEqual(len([r for r in results if r['kind'] in {'function', 'method'}]), len(SAMPLES) + 2)
                    self.assertTrue({'a', 'b'} <= {r['name'] for r in results})
                    self.assertEqual(indexing.update_index(root)['unchanged'], len(SAMPLES) + 1)
                    path = root / 'add.js'
                    path.write_text('function changed() { return 9; }')
                    indexing.update_index(root)
                    self.assertIn('changed', [r['name'] for r in db.search_db('add', limit=100)])
                    path.write_text('function broken( {')
                    self.assertEqual(indexing.update_index(root)['failed'], 1)
                    self.assertIn('changed', [r['name'] for r in db.search_db('add', limit=100)])
                    path.unlink()
                    self.assertEqual(indexing.update_index(root)['deleted'], 1)
                    with db.get_db() as session:
                        self.assertEqual(len(session.scalars(select(File)).all()), len(SAMPLES))
            finally:
                engine.dispose()
