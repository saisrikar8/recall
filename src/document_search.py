"""Document-focused retrieval and optional pairwise reranking, separate from code."""
import threading

MODEL_NAME = 'intfloat/e5-small-v2'
MODEL_REVISION = 'ffb93f3bd4047442299a41ebb6fa998a38507c52'
RERANKER_NAME = 'cross-encoder/ms-marco-MiniLM-L6-v2'
RERANKER_REVISION = '233902d25c440f23af6f7d6e94d2946bac0bee0a'
IMAGE_RERANKER_NAME = 'Qwen/Qwen3-VL-Reranker-2B'
IMAGE_RERANKER_REVISION = '4bd860ac4f15ad1897a214615cccc700f8f71818'
_encoder = _reranker = _image_reranker = None
_lock = threading.RLock()


def _device():
    import torch
    return 'mps' if torch.backends.mps.is_available() else 'cpu'


def encode_documents(texts):
    global _encoder
    import numpy as np
    if not texts:
        return np.empty((0,384),dtype=np.float32)
    with _lock:
        if _encoder is None:
            from sentence_transformers import SentenceTransformer
            _encoder = SentenceTransformer(MODEL_NAME, revision=MODEL_REVISION, device=_device())
            _encoder.max_seq_length = 512
        return np.asarray(_encoder.encode(['passage: '+text for text in texts], batch_size=16,
            normalize_embeddings=True, show_progress_bar=False),dtype=np.float32)


def encode_query(text):
    global _encoder
    import numpy as np
    with _lock:
        if _encoder is None:
            encode_documents(['warmup'])
        return np.asarray(_encoder.encode('query: '+text, normalize_embeddings=True,
            show_progress_bar=False),dtype=np.float32)


def rerank_text(query, texts):
    if not texts:
        return []
    global _reranker
    import torch
    with _lock:
        if _reranker is None:
            from sentence_transformers import CrossEncoder
            _reranker = CrossEncoder(RERANKER_NAME, revision=RERANKER_REVISION,
                device=_device(), max_length=512)
        return _reranker.predict([(query,text) for text in texts],batch_size=16,
            activation_fn=torch.nn.Identity(),show_progress_bar=False).tolist()


def rerank_images(query, documents):
    """Expensive image-aware experiment; never invoked by ordinary search implicitly."""
    if not documents:
        return []
    global _image_reranker
    import torch
    with _lock:
        if _image_reranker is None:
            from sentence_transformers import CrossEncoder
            dtype=torch.float16 if _device()=='mps' else torch.float32
            from huggingface_hub import hf_hub_download
            from pathlib import Path
            template=Path(hf_hub_download(IMAGE_RERANKER_NAME,'additional_chat_templates/reranker.jinja',
                revision=IMAGE_RERANKER_REVISION)).read_text()
            _image_reranker = CrossEncoder(IMAGE_RERANKER_NAME,revision=IMAGE_RERANKER_REVISION,
                device=_device(),model_kwargs={'dtype':dtype,'attn_implementation':'sdpa'},
                processor_kwargs={'min_pixels':128*32*32,'max_pixels':384*32*32,
                    'chat_template':{'default':template,'reranker':template}})
        return _image_reranker.predict([(query,document) for document in documents],batch_size=1,
            prompt="Retrieve images or text relevant to the user's query.",
            activation_fn=torch.nn.Identity(),show_progress_bar=False).tolist()
