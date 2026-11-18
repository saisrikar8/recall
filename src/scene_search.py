"""Optional general-image channel to complement document-focused ColSmol."""
import threading
import hashlib
import json
MODEL_NAME='openai/clip-vit-base-patch32'
MODEL_REVISION='3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268'
MODEL_CONFIGURATION=dict(model=MODEL_NAME,revision=MODEL_REVISION,preprocessing='rgb-letterbox224-v1')
MODEL_KEY=hashlib.sha256(json.dumps(MODEL_CONFIGURATION,sort_keys=True).encode()).hexdigest()
_model=_processor=None
_lock=threading.RLock()


def _load():
    global _model,_processor
    if _model is None:
        import torch
        from transformers import CLIPModel,CLIPProcessor
        device='mps' if torch.backends.mps.is_available() else 'cpu'
        _processor=CLIPProcessor.from_pretrained(MODEL_NAME,revision=MODEL_REVISION)
        _model=CLIPModel.from_pretrained(MODEL_NAME,revision=MODEL_REVISION).to(device).eval()
    return _model,_processor


def prepare_image(image):
    from PIL import ImageOps
    return ImageOps.pad(image.convert('RGB'),(224,224),color='white')


def encode_images(images):
    import numpy as np
    import torch
    from PIL import ImageOps
    if not images:return np.empty((0,512),dtype=np.float32)
    padded=[]
    try:
        for image in images:padded.append(prepare_image(image))
        with _lock,torch.inference_mode():
            model,processor=_load()
            inputs={key:value.to(model.device) for key,value in processor(images=padded,return_tensors='pt').items()}
            value=model.get_image_features(**inputs)
            value=value if isinstance(value,torch.Tensor) else value.pooler_output
            return torch.nn.functional.normalize(value,dim=-1).cpu().float().numpy()
    finally:
        for image in padded:image.close()


def encode_query(text):
    import torch
    with _lock,torch.inference_mode():
        model,processor=_load()
        inputs={key:value.to(model.device) for key,value in processor(text=[text],return_tensors='pt',truncation=True).items()}
        value=model.get_text_features(**inputs)
        value=value if isinstance(value,torch.Tensor) else value.pooler_output
        return torch.nn.functional.normalize(value,dim=-1)[0].cpu().float().numpy()
