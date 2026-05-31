"""
Node 98: MultimodalFusion
==========================
Fuses multiple modalities (text, images, audio transcripts) into unified
representations for downstream AI tasks.

Integrates with:
  - Node_90 (Vision)  for image understanding
  - Node_94 (Audio)   for audio transcription
  - OpenAI            for fusion reasoning
"""

import os
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

try:
    from nodes.common.cors_config import get_cors_origins
except Exception as exc:
    def get_cors_origins():
        return ["*"]

try:
    from core.port_config import get_node_port
    _DEFAULT_PORT = get_node_port("Node_98_MultimodalFusion")
except Exception as exc:
    logger.debug("Fallback triggered: %s", exc)
    _DEFAULT_PORT = 8098

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

NODE_ID = "98"
NODE_NAME = "MultimodalFusion"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
NODE_90_VISION_URL = os.getenv("NODE_90_VISION_URL", "http://localhost:8090")
NODE_94_AUDIO_URL = os.getenv("NODE_94_AUDIO_URL", "http://localhost:8094")

_start_time = datetime.now()

app = FastAPI(title=f"Node {NODE_ID} - {NODE_NAME}", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class FuseRequest(BaseModel):
    texts: Optional[List[str]] = None
    images: Optional[List[str]] = None          # base64-encoded
    audio_transcripts: Optional[List[str]] = None
    task: str = "summarize"                      # summarize | qa | classify
    question: Optional[str] = None              # used when task == "qa"

class EmbedMultimodalRequest(BaseModel):
    texts: Optional[List[str]] = None
    images: Optional[List[str]] = None
    audio_transcripts: Optional[List[str]] = None

class CrossModalSearchRequest(BaseModel):
    query: str
    items: List[Dict[str, Any]]                  # each item: {"type": "text|image|audio", "content": str}
    top_k: int = 5

# ---------------------------------------------------------------------------
# OpenAI helper
# ---------------------------------------------------------------------------

async def _openai_chat(messages: List[Dict[str, Any]], *, max_tokens: int = 1024) -> str:
    """Send messages to OpenAI and return the assistant text."""
    if not OPENAI_API_KEY:
        return "[OpenAI not configured — set OPENAI_API_KEY]"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": OPENAI_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    async with httpx.AsyncClient(base_url=OPENAI_BASE_URL, timeout=60.0) as client:
        resp = await client.post("/chat/completions", headers=headers, json=payload)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


def _build_fusion_prompt(
    texts: List[str],
    images: List[str],
    audio_transcripts: List[str],
    task: str,
    question: Optional[str],
) -> List[Dict[str, Any]]:
    """Build the OpenAI messages payload for a multimodal fusion task."""
    system_msg = (
        "You are a multimodal AI assistant. You receive content from multiple "
        "modalities (text, image descriptions, audio transcripts) and produce a "
        "unified, coherent response for the requested task."
    )
    user_parts: List[str] = []

    if texts:
        user_parts.append("## Text inputs\n" + "\n---\n".join(texts))
    if images:
        user_parts.append(
            f"## Image inputs ({len(images)} image(s) provided as base64)\n"
            "[Images are available but rendered as placeholders in this prompt; "
            "describe and reason about them based on context.]"
        )
    if audio_transcripts:
        user_parts.append("## Audio transcripts\n" + "\n---\n".join(audio_transcripts))

    task_instructions = {
        "summarize": "Task: Produce a unified summary that synthesises all provided modalities.",
        "qa": f"Task: Answer the following question using all provided modalities.\nQuestion: {question or '(none provided)'}",
        "classify": "Task: Classify the overall topic/intent of the multimodal content. Return a JSON object with keys 'category', 'confidence', 'reasoning'.",
    }
    user_parts.append(task_instructions.get(task, f"Task: {task}"))

    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": "\n\n".join(user_parts)},
    ]

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "node": "Node_98_MultimodalFusion",
        "version": "1.0.0",
        "openai_configured": bool(OPENAI_API_KEY),
    }


@app.get("/status")
async def status():
    uptime = (datetime.now() - _start_time).total_seconds()
    return {
        "node_id": NODE_ID,
        "node_name": NODE_NAME,
        "status": "running",
        "uptime_seconds": round(uptime, 1),
        "openai_configured": bool(OPENAI_API_KEY),
        "openai_model": OPENAI_MODEL,
        "connected_nodes": {
            "Node_90_Vision": NODE_90_VISION_URL,
            "Node_94_Audio": NODE_94_AUDIO_URL,
        },
        "capabilities": ["fuse", "embed_multimodal", "cross_modal_search"],
    }


@app.post("/fuse")
async def fuse(req: FuseRequest):
    """
    Fuse text, image, and audio inputs into a unified result.
    Supported tasks: summarize, qa, classify.
    """
    texts = req.texts or []
    images = req.images or []
    audio_transcripts = req.audio_transcripts or []

    if not texts and not images and not audio_transcripts:
        raise HTTPException(status_code=400, detail="At least one modality must be provided.")

    valid_tasks = {"summarize", "qa", "classify"}
    if req.task not in valid_tasks:
        raise HTTPException(status_code=400, detail=f"Unknown task '{req.task}'. Choose from {valid_tasks}.")

    messages = _build_fusion_prompt(texts, images, audio_transcripts, req.task, req.question)
    result_text = await _openai_chat(messages, max_tokens=1024)

    return {
        "success": True,
        "task": req.task,
        "modalities_used": {
            "texts": len(texts),
            "images": len(images),
            "audio_transcripts": len(audio_transcripts),
        },
        "result": result_text,
    }


@app.post("/embed_multimodal")
async def embed_multimodal(req: EmbedMultimodalRequest):
    """
    Create a unified textual embedding description from mixed inputs.
    Returns a rich descriptive string suitable for embedding via Node_99.
    """
    texts = req.texts or []
    images = req.images or []
    audio_transcripts = req.audio_transcripts or []

    if not texts and not images and not audio_transcripts:
        raise HTTPException(status_code=400, detail="At least one modality must be provided.")

    system_msg = (
        "You are a multimodal embedding assistant. Given inputs from multiple "
        "modalities, produce a single dense textual description that captures all "
        "semantically important information. This description will be vectorised."
    )
    user_parts: List[str] = []
    if texts:
        user_parts.append("Texts:\n" + "\n".join(f"- {t}" for t in texts))
    if images:
        user_parts.append(f"Images: {len(images)} image(s) provided (base64 encoded).")
    if audio_transcripts:
        user_parts.append("Audio transcripts:\n" + "\n".join(f"- {a}" for a in audio_transcripts))
    user_parts.append("Produce the unified description now:")

    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": "\n\n".join(user_parts)},
    ]
    description = await _openai_chat(messages, max_tokens=512)

    return {
        "success": True,
        "unified_description": description,
        "modalities_used": {
            "texts": len(texts),
            "images": len(images),
            "audio_transcripts": len(audio_transcripts),
        },
    }


@app.post("/cross_modal_search")
async def cross_modal_search(req: CrossModalSearchRequest):
    """
    Given a text query, rank a list of mixed-media items by relevance.
    Each item should be {"type": "text|image|audio", "content": str}.
    Returns top_k most relevant items with relevance reasoning.
    """
    if not req.items:
        raise HTTPException(status_code=400, detail="items list must not be empty.")

    items_block = "\n".join(
        f"[{i}] ({item.get('type', 'unknown')}) {item.get('content', '')[:300]}"
        for i, item in enumerate(req.items)
    )
    system_msg = (
        "You are a cross-modal search engine. Given a query and a numbered list of "
        "items (text, image descriptions, or audio transcripts), return the indices "
        "of the most relevant items in descending order of relevance, with a brief "
        "reason for each. Respond as JSON: "
        '{"ranked": [{"index": int, "relevance_score": float, "reason": str}, ...]}'
    )
    user_msg = f"Query: {req.query}\n\nItems:\n{items_block}\n\nReturn the top {req.top_k} results."

    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]
    raw = await _openai_chat(messages, max_tokens=512)

    # Attempt JSON parse; fall back to raw string
    import json
    try:
        parsed = json.loads(raw)
        ranked = parsed.get("ranked", [])[:req.top_k]
    except Exception as exc:
        logger.debug("Fallback triggered: %s", exc)
        ranked = []

    return {
        "success": True,
        "query": req.query,
        "total_items": len(req.items),
        "top_k": req.top_k,
        "ranked": ranked,
        "raw_response": raw if not ranked else None,
    }


@app.post("/mcp/call")
async def mcp_call(request: Dict[str, Any]):
    tool = request.get("tool", "")
    params = request.get("params", {})
    if tool == "fuse":
        return await fuse(FuseRequest(**params))
    elif tool == "embed_multimodal":
        return await embed_multimodal(EmbedMultimodalRequest(**params))
    elif tool == "cross_modal_search":
        return await cross_modal_search(CrossModalSearchRequest(**params))
    elif tool == "health":
        return await health()
    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("NODE_98_PORT", str(_DEFAULT_PORT)))
    logger.info(f"Starting {NODE_NAME} on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
