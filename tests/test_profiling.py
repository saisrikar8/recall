import contextlib
import io
import sys
import types
import unittest
from unittest.mock import Mock, patch

from src import profiling, semantic_search as semantic


class ProfilingTests(unittest.TestCase):
    def test_disabled_does_not_sample(self):
        with patch.object(profiling, 'MemorySample') as sample:
            with profiling.capture(False):
                with profiling.measure('unused'):
                    pass
        sample.assert_not_called()

    def test_records_memory_and_time_even_on_failure(self):
        with contextlib.redirect_stderr(io.StringIO()) as output:
            with self.assertRaisesRegex(ValueError, 'example'):
                with profiling.capture(True, label='test') as records:
                    with profiling.measure('file', input_chars=12):
                        raise ValueError('example')
        self.assertEqual([r['stage'] for r in records], ['file', 'test'])
        for record in records:
            self.assertGreater(record['sampled_peak_rss_mib'], 0)
            self.assertGreaterEqual(record['seconds'], 0)
        self.assertIn('[profile]', output.getvalue())
        self.assertFalse(profiling.enabled())

    def test_model_load_only_once_and_input_lengths(self):
        fake = Mock()
        fake.encode.return_value.tolist.return_value = [1., 0.]
        constructor = Mock(return_value=fake)
        module = types.SimpleNamespace(SentenceTransformer=constructor)
        with patch.dict(sys.modules, {'sentence_transformers': module}), \
             patch.object(semantic, 'model', None), \
             patch.object(semantic, 'loaded_model_name', None), \
             profiling.capture(True, emit=False) as records:
            semantic._encode_local('hello')
            semantic._encode_local('world!')
        constructor.assert_called_once()
        self.assertEqual(sum(r['stage'] == 'model-load' for r in records), 1)
        self.assertEqual([r['input_chars'] for r in records if r['stage'] == 'embedding'], [5, 6])
        self.assertFalse(any('text' in r or 'source' in r for r in records))

    def test_cli_rejects_profile_for_dry_run_or_unrelated_commands(self):
        from src import main
        for args in (['index', '--profile', '--dry-run'], ['list', '--profile']):
            with patch.object(sys, 'argv', ['recall', *args]), \
                 contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    main.main()
            self.assertEqual(error.exception.code, 2)
