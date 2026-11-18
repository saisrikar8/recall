import unittest
from types import SimpleNamespace
import torch
from src.transformer_compat import encoder_attention_mask, prepare_coderank


class TransformerCompatibilityTests(unittest.TestCase):
    def test_encoder_padding_masks_keep_legacy_semantics(self):
        model = SimpleNamespace(config=SimpleNamespace(is_decoder=False), dtype=torch.float32)
        mask = encoder_attention_mask(model, torch.tensor([[1, 0]]), (1, 2))
        self.assertEqual(tuple(mask.shape), (1, 1, 1, 2))
        self.assertEqual(mask[0, 0, 0, 0], 0.)
        self.assertEqual(mask[0, 0, 0, 1], torch.finfo(torch.float32).min)

    def test_only_missing_nomic_encoder_method_is_added(self):
        Nomic = type('NomicBertModel', (), {})
        encoder = Nomic()
        encoder.config = SimpleNamespace(is_decoder=False)
        encoder.dtype = torch.float32
        prepare_coderank([SimpleNamespace(auto_model=encoder)])
        self.assertEqual(tuple(encoder.get_extended_attention_mask(torch.ones(1, 2), (1, 2)).shape), (1, 1, 1, 2))
        other = SimpleNamespace()
        prepare_coderank([SimpleNamespace(auto_model=other)])
        self.assertFalse(hasattr(other, 'get_extended_attention_mask'))
