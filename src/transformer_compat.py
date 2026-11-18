"""Compatibility for CodeRankEmbed's encoder-only legacy attention-mask call."""
from types import MethodType


def encoder_attention_mask(self, attention_mask, input_shape, dtype=None):
    import torch
    if getattr(self.config, 'is_decoder', False):
        raise ValueError('The legacy compatibility mask supports bidirectional encoders only')
    if attention_mask.dim() == 3:
        extended = attention_mask[:, None, :, :]
    elif attention_mask.dim() == 2:
        extended = attention_mask[:, None, None, :]
    else:
        raise ValueError(f'Unsupported attention-mask shape: {attention_mask.shape}')
    dtype = self.dtype if dtype is None else dtype
    return (1.0 - extended.to(dtype=dtype)) * torch.finfo(dtype).min


def prepare_coderank(model):
    encoder = model[0].auto_model
    if encoder.__class__.__name__ == 'NomicBertModel' and not hasattr(encoder, 'get_extended_attention_mask'):
        encoder.get_extended_attention_mask = MethodType(encoder_attention_mask, encoder)
