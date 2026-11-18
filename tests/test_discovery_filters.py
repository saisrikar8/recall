import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import discovery, indexing, main


class DiscoveryFilterTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.file = self.root / 'a.py'
        self.file.write_text('def demo(): pass\n')

    def test_direct_file_and_parent_exclusions(self):
        self.assertEqual(discovery.discover_files(self.file, [str(self.file)]), [])
        self.assertEqual(discovery.discover_files(self.file, [str(self.root)]), [])
        self.assertEqual(discovery.discover_files(self.root, [str(self.root)]), [])
        self.assertEqual(discovery.discover_files(self.root, [str(self.root / 'absent')]), [str(self.file)])

    def test_git_filters_direct_files_and_directory_walk(self):
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        (self.root / '.gitignore').write_text('a.py\n.grader/\n')
        grader = self.root / '.grader'
        grader.mkdir()
        (grader / 'dep.py').write_text('')
        visible = self.root / 'visible.py'
        visible.write_text('')
        self.assertEqual(discovery.discover_files(self.file), [])
        self.assertEqual(discovery.discover_files(self.root), [str(visible)])
        self.assertEqual(discovery.discover_files(grader), [])

    def test_missing_git_checks_availability_once(self):
        with patch.object(discovery.subprocess, 'run', side_effect=FileNotFoundError) as run:
            self.assertEqual(discovery.discover_files(self.root), [str(self.file)])
        run.assert_called_once()

    def test_unexpected_check_failure_stops_before_database_work(self):
        failure = subprocess.CompletedProcess([], 128, '', 'index unavailable')
        with patch.object(discovery, 'use_git_ignore', return_value=True), \
             patch.object(discovery.subprocess, 'run', return_value=failure), \
             patch.object(indexing, 'initialize_database') as initialize, \
             patch.object(indexing, 'get_code_embedding') as embed:
            with self.assertRaisesRegex(ValueError, 'index unavailable'):
                main.update_index(self.root)
            initialize.assert_not_called()
            embed.assert_not_called()
