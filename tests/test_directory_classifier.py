import contextlib
import io
from pathlib import Path
import tempfile
import unittest

from src.main import classify_directory, discover_files


class DirectoryClassifierTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()

    def touch(self, name):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        return path

    def test_known_internals_and_caches(self):
        for name in ('.git', '.hg', '.svn', '.bzr', '__pycache__', '.pytest_cache',
                     '.mypy_cache', '.ruff_cache', '.tox', '.nox', '.idea'):
            with self.subTest(name=name):
                decision = classify_directory(self.root / name)
                self.assertTrue(decision.skip)
                self.assertTrue(decision.reason)
                self.assertTrue(decision.rule)

    def test_arbitrarily_named_environments(self):
        for marker, rule in (('custom/pyvenv.cfg', 'python.venv'),
                             ('another/conda-meta/history', 'python.conda')):
            self.touch(marker)
            self.assertEqual(classify_directory(self.root / marker.split('/')[0]).rule, rule)

    def test_grader_dependencies_pruned_at_root_and_during_walk(self):
        for name in ('pytest', 'pygments'):
            self.touch(f'.grader/{name}-1.0.dist-info/METADATA')
            self.touch(f'.grader/{name}-1.0.dist-info/RECORD')
        self.touch('.grader/pytest/__init__.py')
        wanted = self.touch('homework.py')
        with contextlib.redirect_stderr(io.StringIO()) as output:
            self.assertEqual(discover_files(self.root), [str(wanted)])
            self.assertEqual(discover_files(self.root / '.grader'), [])
        self.assertIn('Installed Python dependencies', output.getvalue())

    def test_metadata_names_alone_do_not_exclude(self):
        self.touch('fixtures/a.dist-info/METADATA')
        self.touch('fixtures/b.dist-info/METADATA')
        self.touch('fixtures/example.py')
        self.assertFalse(classify_directory(self.root / 'fixtures').skip)

    def test_normal_names_and_hidden_notes_are_kept(self):
        for name in ('build', 'target', 'vendor', 'Library', 'tests', '.notes', 'venv', 'node_modules'):
            folder = self.root / name
            folder.mkdir()
            self.assertFalse(classify_directory(folder).skip, name)

    def test_generated_output_requires_context(self):
        cases = [('.next', ['package.json', 'next.config.ts'], 'node.next'),
                 ('target', ['Cargo.toml', 'target/.rustc_info.json'], 'build.rust'),
                 ('obj', ['example.csproj', 'obj/project.assets.json'], 'build.dotnet')]
        for name, markers, rule in cases:
            with self.subTest(name=name):
                folder = self.root / name
                folder.mkdir()
                self.assertFalse(classify_directory(folder).skip)
                for marker in markers:
                    self.touch(marker)
                self.assertEqual(classify_directory(folder).rule, rule)

    def test_node_dependencies_and_app_bundle(self):
        self.touch('node_modules/example/package.json')
        self.assertEqual(classify_directory(self.root / 'node_modules').rule, 'node.dependencies')
        self.touch('Example.app/Contents/Info.plist')
        (self.root / 'Example.app/Contents/MacOS').mkdir()
        self.assertEqual(classify_directory(self.root / 'Example.app').rule, 'bundle.macos-app')

    def test_permission_errors_propagate(self):
        from unittest.mock import patch
        with patch('src.main.os.scandir', side_effect=PermissionError('denied')):
            with self.assertRaises(PermissionError):
                classify_directory(self.root)
