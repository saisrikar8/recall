import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from src import main


class DryRunTests(unittest.TestCase):
    def test_exclusions_and_no_database_or_embedding_work(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / 'homework.py').write_text('def demo(): pass\n')
            grader = root / '.grader'
            grader.mkdir()
            (grader / 'dependency.py').write_text('def dep(): pass\n')
            with patch.object(main, 'initialize_database') as initialize, \
                 patch.object(main, 'get_db') as database, \
                 patch.object(main, 'get_code_embedding') as embed, \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main.update_index(root, [str(grader)], True), {})
            initialize.assert_not_called()
            database.assert_not_called()
            embed.assert_not_called()
            self.assertIn('Would scan 1 files:', output.getvalue())
            self.assertIn('homework.py', output.getvalue())
            self.assertNotIn('dependency.py', output.getvalue())

    def test_cli_passes_dry_run_and_exclusions(self):
        with patch.object(sys, 'argv', ['recall', 'index', '-f', './project', '--exclude', './project/.grader', '--dry-run']), \
             patch.object(main, 'update_index') as update:
            main.main()
        update.assert_called_once_with('./project', ['./project/.grader'], True)

    def test_empty_directory(self):
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(main, 'initialize_database') as initialize, \
             contextlib.redirect_stdout(io.StringIO()) as output:
            main.update_index(temporary, dry_run=True)
        self.assertIn('Would scan 0 files:', output.getvalue())
        initialize.assert_not_called()
