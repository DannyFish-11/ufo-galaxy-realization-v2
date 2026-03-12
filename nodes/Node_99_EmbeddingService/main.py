"""
Node 99: EmbeddingService
==========================
Generates text/document embeddings using OpenAI's embedding API.
Supports batch embedding, cosine similarity, and semantic ranking.
Optional Redis caching is available when REDIS_URL is configured.
"""

import os
import json
import hashlib
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

try:
    from nodes.common.cors_config import get_cors_origins
except Exception:
    def get_cors_origins():
        return ["*"]

try:
    from core.port_config import get_node_port
    _DEFAULT_PORT = get_node_port("Node_99_EmbeddingService")
except Exception:
    _DEFAULT_PORT = 8099

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

NODE_ID = "99"
NODE_NAME = "EmbeddingService"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

_start_time = datetime.now()

# In-process embedding cache (fallback when Redis is unavailable)
_local_cache: Dict[str, List[float]] = {}

app = FastAPI(title=f"Node {NODE_ID} - {NODE_NAME}", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Redis cache helpers (optional)
# ---------------------------------------------------------------------------

_redis_client = None

def _get_redis():
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        import redis
        _redis_client = redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=2)
        _redis_client.ping()
        logger.info("✅ Redis cache connected")
    except Exception:
        _redis_client = None
    return _redis_client


def _cache_key(text: str, model: str) -> str:
    return hashlib.sha256(f"{model}:{text}".encode()).hexdigest()


def _cache_get(key: str) -> Optional[List[float]]:
    r = _get_redis()
    if r:
        try:
            raw = r.get(f"emb:{key}")
            if raw:
                return json.loads(raw)
        except Exception:
            pass
    return _local_cache.get(key)


def _cache_set(key: str, vector: List[float]) -> None:
    r = _get_redis()
    if r:
        try:
            r.setex(f"emb:{key}", 86400, json.dumps(vector))
            return
        except Exception:
            pass
    _local_cache[key] = vector

# ---------------------------------------------------------------------------
# OpenAI embedding helper
# ---------------------------------------------------------------------------

_BATCH_SIZE = 96  # OpenAI recommended batch ceiling

async def _fetch_embeddings(texts: List[str], model: str) -> List[List[float]]:
    """Call OpenAI embeddings endpoint for a list of texts."""
    if not OPENAI_API_KEY:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY not configured.")
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {"model": model, "input": texts}
    async with httpx.AsyncClient(base_url=OPENAI_BASE_URL, timeout=60.0) as client:
        resp = await client.post("/embeddings", headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()["data"]
    # data is sorted by index
    return [item["embedding"] for item in sorted(data, key=lambda x: x["index"])]


async def _get_embeddings(texts: List[str], model: str) -> List[List[float]]:
    """Return embeddings with cache look-up / population."""
    results: List[Optional[List[float]]] = [None] * len(texts)
    uncached_indices: List[int] = []
    uncached_texts: List[str] = []

    for i, text in enumerate(texts):
        key = _cache_key(text, model)
        cached = _cache_get(key)
        if cached is not None:
            results[i] = cached
        else:
            uncached_indices.append(i)
            uncached_texts.append(text)

    # Fetch uncached in batches
    for batch_start in range(0, len(uncached_texts), _BATCH_SIZE):
        batch = uncached_texts[batch_start: batch_start + _BATCH_SIZE]
        vectors = await _fetch_embeddings(batch, model)
        for j, vector in enumerate(vectors):
            idx = uncached_indices[batch_start + j]
            results[idx] = vector
            _cache_set(_cache_key(texts[idx], model), vector)

    return results  # type: ignore[return-value]

# ---------------------------------------------------------------------------
# Cosine similarity
# ---------------------------------------------------------------------------

def _cosine_similarity(a: List[float], b: List[float]) -> float:
    va, vb = np.array(a), np.array(b)
    denom = np.linalg.norm(va) * np.linalg.norm(vb)
    if denom == 0:
        return 0.0
    return float(np.dot(va, vb) / denom)

# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class EmbedRequest(BaseModel):
    texts: List[str]
    model: Optional[str] = None

class SimilarityRequest(BaseModel):
    text1: str
    text2: str
    model: Optional[str] = None

class RankRequest(BaseModel):
    query: str
    candidates: List[str]
    model: Optional[str] = None

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "node": "Node_99_EmbeddingService",
        "version": "1.0.0",
        "openai_configured": bool(OPENAI_API_KEY),
        "model": OPENAI_EMBEDDING_MODEL,
    }


@app.get("/status")
async def status():
    uptime = (datetime.now() - _start_time).total_seconds()
    redis_ok = False
    try:
        r = _get_redis()
        redis_ok = r is not None
    except Exception:
        pass
    return {
        "node_id": NODE_ID,
        "node_name": NODE_NAME,
        "status": "running",
        "uptime_seconds": round(uptime, 1),
        "openai_configured": bool(OPENAI_API_KEY),
        "default_model": OPENAI_EMBEDDING_MODEL,
        "redis_connected": redis_ok,
        "local_cache_size": len(_local_cache),
        "capabilities": ["embed", "embed_batch", "similarity", "rank"],
    }


@app.post("/embed")
async def embed(req: EmbedRequest):
    """Return embedding vectors for a list of texts."""
    if not req.texts:
        raise HTTPException(status_code=400, detail="texts must not be empty.")
    model = req.model or OPENAI_EMBEDDING_MODEL
    vectors = await _get_embeddings(req.texts, model)
    return {
        "success": True,
        "model": model,
        "count": len(vectors),
        "embeddings": vectors,
    }


@app.post("/embed_batch")
async def embed_batch(req: EmbedRequest):
    """
    Batch-optimised embedding: identical to /embed but explicitly chunks
    large inputs to respect OpenAI's batch limits.
    """
    if not req.texts:
        raise HTTPException(status_code=400, detail="texts must not be empty.")
    model = req.model or OPENAI_EMBEDDING_MODEL
    all_vectors: List[List[float]] = []
    for chunk_start in range(0, len(req.texts), _BATCH_SIZE):
        chunk = req.texts[chunk_start: chunk_start + _BATCH_SIZE]
        vectors = await _get_embeddings(chunk, model)
        all_vectors.extend(vectors)
    return {
        "success": True,
        "model": model,
        "count": len(all_vectors),
        "embeddings": all_vectors,
    }


@app.post("/similarity")
async def similarity(req: SimilarityRequest):
    """Return cosine similarity between two texts (0.0 – 1.0)."""
    model = req.model or OPENAI_EMBEDDING_MODEL
    vectors = await _get_embeddings([req.text1, req.text2], model)
    score = _cosine_similarity(vectors[0], vectors[1])
    return {
        "success": True,
        "model": model,
        "similarity": round(score, 6),
    }


@app.post("/rank")
async def rank(req: RankRequest):
    """Rank candidates by cosine similarity to the query."""
    if not req.candidates:
        raise HTTPException(status_code=400, detail="candidates must not be empty.")
    model = req.model or OPENAI_EMBEDDING_MODEL
    all_texts = [req.query] + req.candidates
    vectors = await _get_embeddings(all_texts, model)
    query_vec = vectors[0]
    scored = [
        {"text": req.candidates[i], "score": round(_cosine_similarity(query_vec, vectors[i + 1]), 6)}
        for i in range(len(req.candidates))
    ]
    scored.sort(key=lambda x: x["score"], reverse=True)
    return {
        "success": True,
        "model": model,
        "query": req.query,
        "ranked": scored,
    }


@app.post("/mcp/call")
async def mcp_call(request: Dict[str, Any]):
    tool = request.get("tool", "")
    params = request.get("params", {})
    if tool == "embed":
        return await embed(EmbedRequest(**params))
    elif tool == "embed_batch":
        return await embed_batch(EmbedRequest(**params))
    elif tool == "similarity":
        return await similarity(SimilarityRequest(**params))
    elif tool == "rank":
        return await rank(RankRequest(**params))
    elif tool == "health":
        return await health()
    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("NODE_99_PORT", str(_DEFAULT_PORT)))
    logger.info(f"Starting {NODE_NAME} on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
