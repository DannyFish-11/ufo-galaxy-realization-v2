"""
Node 08: Fetch - HTTP 请求服务节点
====================================
提供同步/异步 HTTP 请求、批量请求、连通性检查等功能
"""
import os
import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from nodes.common.cors_config import get_cors_origins

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

# 配置
PORT = 8008
FETCH_MAX_REDIRECTS = int(os.getenv("FETCH_MAX_REDIRECTS", "10"))
FETCH_TIMEOUT = float(os.getenv("FETCH_TIMEOUT", "30"))
FETCH_MAX_RESPONSE_SIZE = int(os.getenv("FETCH_MAX_RESPONSE_SIZE", str(10 * 1024 * 1024)))  # 10 MB

# 统计
stats: Dict[str, int] = {"total_requests": 0, "success_count": 0, "error_count": 0}

app = FastAPI(title="Node 08 - Fetch", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── 请求模型 ────────────────────────────────────────────────────────────────

class FetchRequest(BaseModel):
    url: str
    method: str = "GET"
    headers: Optional[Dict[str, str]] = None
    body: Optional[Any] = None
    timeout: Optional[float] = None
    follow_redirects: bool = True


class BatchFetchRequest(BaseModel):
    requests: List[FetchRequest]
    max_concurrent: int = 5


# ─── 工具函数 ─────────────────────────────────────────────────────────────────

async def _do_fetch(req: FetchRequest) -> Dict[str, Any]:
    """执行单次 HTTP 请求，返回标准化结果。"""
    timeout = req.timeout if req.timeout is not None else FETCH_TIMEOUT
    async with httpx.AsyncClient(
        max_redirects=FETCH_MAX_REDIRECTS,
        timeout=timeout,
        follow_redirects=req.follow_redirects,
    ) as client:
        response = await client.request(
            method=req.method.upper(),
            url=req.url,
            headers=req.headers or {},
            content=req.body if isinstance(req.body, (bytes, str)) else None,
            json=req.body if isinstance(req.body, (dict, list)) else None,
        )

    raw = response.content
    truncated = len(raw) > FETCH_MAX_RESPONSE_SIZE
    if truncated:
        raw = raw[:FETCH_MAX_RESPONSE_SIZE]

    content_type = response.headers.get("content-type", "")
    try:
        content = raw.decode("utf-8", errors="replace") if raw else ""
    except Exception as exc:
        logger.debug("Fallback triggered: %s", exc)
        content = ""

    return {
        "success": True,
        "status_code": response.status_code,
        "headers": dict(response.headers),
        "content": content,
        "content_type": content_type,
        "truncated": truncated,
    }


# ─── 端点 ─────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "node_id": "08",
        "name": "Fetch",
        "port": PORT,
        "httpx_available": HTTPX_AVAILABLE,
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/status")
async def status():
    return {
        "node": "Fetch",
        "port": PORT,
        "config": {
            "timeout": FETCH_TIMEOUT,
            "max_redirects": FETCH_MAX_REDIRECTS,
            "max_response_size": FETCH_MAX_RESPONSE_SIZE,
        },
        "stats": stats,
        "httpx_available": HTTPX_AVAILABLE,
        "timestamp": datetime.now().isoformat(),
    }


@app.post("/fetch")
async def fetch(request: FetchRequest):
    """发送单次 HTTP 请求。"""
    if not HTTPX_AVAILABLE:
        raise HTTPException(status_code=503, detail="httpx not installed. Run: pip install httpx")

    stats["total_requests"] += 1
    try:
        result = await _do_fetch(request)
        stats["success_count"] += 1
        return result
    except httpx.TimeoutException as exc:
        stats["error_count"] += 1
        raise HTTPException(status_code=408, detail=f"Request timed out: {exc}")
    except httpx.RequestError as exc:
        stats["error_count"] += 1
        raise HTTPException(status_code=502, detail=f"Request error: {exc}")
    except Exception as exc:
        logger.debug("Fallback triggered: %s", exc)
        stats["error_count"] += 1
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/fetch/batch")
async def fetch_batch(request: BatchFetchRequest):
    """并行批量 HTTP 请求。"""
    if not HTTPX_AVAILABLE:
        raise HTTPException(status_code=503, detail="httpx not installed. Run: pip install httpx")

    semaphore = asyncio.Semaphore(max(1, request.max_concurrent))

    async def _guarded(req: FetchRequest) -> Dict[str, Any]:
        async with semaphore:
            stats["total_requests"] += 1
            try:
                result = await _do_fetch(req)
                stats["success_count"] += 1
                return result
            except Exception as exc:
                logger.debug("Fallback triggered: %s", exc)
                stats["error_count"] += 1
                return {"success": False, "url": req.url, "error": str(exc)}

    results = await asyncio.gather(*[_guarded(r) for r in request.requests])
    return {
        "success": True,
        "total": len(results),
        "results": results,
    }


@app.get("/fetch/ping")
async def ping(url: str = Query(..., description="要检查的 URL")):
    """快速连通性检查——只取响应状态，不读取正文。"""
    if not HTTPX_AVAILABLE:
        raise HTTPException(status_code=503, detail="httpx not installed. Run: pip install httpx")

    stats["total_requests"] += 1
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            response = await client.head(url)
        stats["success_count"] += 1
        return {
            "success": True,
            "url": url,
            "status_code": response.status_code,
            "reachable": True,
        }
    except Exception as exc:
        logger.debug("Fallback triggered: %s", exc)
        stats["error_count"] += 1
        return {"success": False, "url": url, "reachable": False, "error": str(exc)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
