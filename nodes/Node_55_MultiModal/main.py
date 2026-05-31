"""
Node 55: MultiModal - Multimodal AI Processing Node
"""
import os
import base64
import io
import statistics
from datetime import datetime
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from nodes.common.cors_config import get_cors_origins

try:
    from core.port_config import get_node_port
    PORT = get_node_port("Node_55_MultiModal")
except Exception as exc:
    logger.debug("Fallback triggered: %s", exc)
    PORT = int(os.getenv("PORT", "8055"))

try:
    from transformers import pipeline as hf_pipeline, AutoTokenizer, AutoModel
    TRANSFORMERS_AVAILABLE = True
except ImportError:
    hf_pipeline = None
    AutoTokenizer = None
    AutoModel = None
    TRANSFORMERS_AVAILABLE = False

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    Image = None
    PIL_AVAILABLE = False

try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    torch = None
    TORCH_AVAILABLE = False

app = FastAPI(title="Node 55 - MultiModal", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=get_cors_origins(), allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

_ERR_NO_TRANSFORMERS = "transformers not installed. Run: pip install transformers torch"

# Cached pipelines
_pipelines: Dict[str, Any] = {}

AVAILABLE_MODELS = [
    {"name": "text-generation", "type": "text", "description": "Generate text from prompt", "requires": ["transformers"]},
    {"name": "sentiment-analysis", "type": "text", "description": "Classify sentiment of text", "requires": ["transformers"]},
    {"name": "zero-shot-classification", "type": "text", "description": "Classify text into arbitrary categories", "requires": ["transformers"]},
    {"name": "image-classification", "type": "image", "description": "Classify images", "requires": ["transformers", "PIL"]},
    {"name": "image-captioning", "type": "image", "description": "Generate captions for images", "requires": ["transformers", "PIL"]},
    {"name": "visual-question-answering", "type": "multimodal", "description": "Answer questions about images", "requires": ["transformers", "PIL"]},
]

def decode_image(image_b64: str) -> "Image.Image":
    """Decode base64 image to PIL Image."""
    data = base64.b64decode(image_b64)
    return Image.open(io.BytesIO(data))

class ProcessRequest(BaseModel):
    text: Optional[str] = None
    image_b64: Optional[str] = None  # base64 encoded image
    task: str = "sentiment-analysis"
    model: Optional[str] = None
    params: Optional[Dict[str, Any]] = None

class EmbedRequest(BaseModel):
    text: Optional[str] = None
    image_b64: Optional[str] = None
    model: Optional[str] = None

@app.get("/health")
async def health():
    available = TRANSFORMERS_AVAILABLE and PIL_AVAILABLE and TORCH_AVAILABLE
    return {
        "status": "healthy" if TRANSFORMERS_AVAILABLE else "degraded",
        "node_id": "55",
        "name": "MultiModal",
        "transformers_available": TRANSFORMERS_AVAILABLE,
        "pil_available": PIL_AVAILABLE,
        "torch_available": TORCH_AVAILABLE,
        "degraded": not TRANSFORMERS_AVAILABLE,
        "degraded_reason": None if TRANSFORMERS_AVAILABLE else "transformers not installed",
        "cached_pipelines": list(_pipelines.keys()),
        "timestamp": datetime.now().isoformat()
    }

@app.get("/status")
async def status():
    return {
        "status": "running",
        "node_id": "55",
        "name": "MultiModal",
        "transformers_available": TRANSFORMERS_AVAILABLE,
        "pil_available": PIL_AVAILABLE,
        "torch_available": TORCH_AVAILABLE,
        "cached_pipelines": list(_pipelines.keys()),
        "timestamp": datetime.now().isoformat()
    }

@app.get("/models")
async def list_models():
    models = []
    for m in AVAILABLE_MODELS:
        available = True
        missing = []
        for req in m["requires"]:
            if req == "transformers" and not TRANSFORMERS_AVAILABLE:
                available = False
                missing.append("transformers")
            elif req == "PIL" and not PIL_AVAILABLE:
                available = False
                missing.append("Pillow")
        models.append({**m, "available": available, "missing_deps": missing})
    return {"success": True, "models": models, "count": len(models)}

@app.post("/process")
async def process(request: ProcessRequest):
    if not TRANSFORMERS_AVAILABLE:
        return {"success": False, "error": _ERR_NO_TRANSFORMERS}

    try:
        task = request.task
        params = request.params or {}

        # Build or retrieve pipeline
        cache_key = f"{task}:{request.model or 'default'}"
        if cache_key not in _pipelines:
            kwargs = {"task": task}
            if request.model:
                kwargs["model"] = request.model
            if TORCH_AVAILABLE:
                kwargs["device"] = 0 if torch.cuda.is_available() else -1
            _pipelines[cache_key] = hf_pipeline(**kwargs)

        pipe = _pipelines[cache_key]

        if request.image_b64 and PIL_AVAILABLE:
            image = decode_image(request.image_b64)
            if request.text:
                result = pipe(request.text, image, **params)
            else:
                result = pipe(image, **params)
        elif request.text:
            result = pipe(request.text, **params)
        else:
            return {"success": False, "error": "Either text or image_b64 is required"}

        return {"success": True, "task": task, "result": result}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/embed")
async def embed(request: EmbedRequest):
    if not TRANSFORMERS_AVAILABLE:
        return {"success": False, "error": _ERR_NO_TRANSFORMERS}
    try:
        model_name = request.model or "sentence-transformers/all-MiniLM-L6-v2"

        cache_key = f"embed:{model_name}"
        if cache_key not in _pipelines:
            _pipelines[cache_key] = hf_pipeline("feature-extraction", model=model_name)

        pipe = _pipelines[cache_key]

        if request.text:
            result = pipe(request.text)
            # Flatten to 1D embedding (mean pool)
            flat = result[0]  # shape: (seq_len, hidden_size)
            if isinstance(flat[0], list):
                embedding = [statistics.mean(x[i] for x in flat) for i in range(len(flat[0]))]
            else:
                embedding = flat
            return {"success": True, "embedding": embedding, "dimensions": len(embedding) if isinstance(embedding, list) else None}
        else:
            return {"success": False, "error": "Text is required for embedding (image embedding requires specialized models)"}
    except Exception as e:
        return {"success": False, "error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
