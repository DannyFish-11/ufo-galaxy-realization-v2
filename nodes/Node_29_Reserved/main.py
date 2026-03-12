"""
Node 29: Extension Registry - 扩展注册节点
============================================
HTTP 扩展/钩子系统：其他节点可注册回调 URL 并接收事件通知
"""
import os
import logging
from collections import deque
from datetime import datetime
from typing import Dict, Any, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from nodes.common.cors_config import get_cors_origins

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Node_29_ExtensionRegistry")

PORT = 8029
NODE_ID = "29"
NODE_NAME = os.getenv("NODE_29_NAME", "ExtensionRegistry")
MAX_HOOK_RETRIES = int(os.getenv("MAX_HOOK_RETRIES", "3"))
MAX_HISTORY = 1000

app = FastAPI(title=f"Node {NODE_ID} - {NODE_NAME}", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-memory stores ──────────────────────────────────────────────────────────

class ExtensionRecord:
    def __init__(self, name: str, version: str, callback_url: str, events: List[str]):
        self.name = name
        self.version = version
        self.callback_url = callback_url
        self.events = events  # empty list = subscribe to all
        self.registered_at = datetime.now().isoformat()
        self.dispatch_count = 0
        self.fail_count = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "callback_url": self.callback_url,
            "events": self.events,
            "registered_at": self.registered_at,
            "dispatch_count": self.dispatch_count,
            "fail_count": self.fail_count,
        }


extensions: Dict[str, ExtensionRecord] = {}
event_history: deque = deque(maxlen=MAX_HISTORY)
global_stats = {"events_dispatched": 0, "failed_dispatches": 0}

# ── Pydantic models ───────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    name: str
    version: str = "1.0.0"
    callback_url: str
    events: List[str] = []

class DispatchRequest(BaseModel):
    event_type: str
    payload: Dict[str, Any] = {}

class PingRequest(BaseModel):
    name: str

# ── Dispatch helper ───────────────────────────────────────────────────────────

async def _dispatch_to_extension(ext: ExtensionRecord, event_type: str, payload: Dict[str, Any],
                                 event_timestamp: str) -> bool:
    """POST event to a single extension callback URL. Returns True on success."""
    if not HTTPX_AVAILABLE:
        logger.warning("httpx not installed; cannot dispatch events")
        return False

    body = {"event_type": event_type, "payload": payload, "timestamp": event_timestamp}
    for attempt in range(1, MAX_HOOK_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(ext.callback_url, json=body)
                resp.raise_for_status()
            ext.dispatch_count += 1
            return True
        except Exception as exc:
            logger.warning("Dispatch attempt %d/%d to %s failed: %s",
                           attempt, MAX_HOOK_RETRIES, ext.callback_url, exc)
    ext.fail_count += 1
    return False


async def _dispatch_event(event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch event to all subscribed extensions."""
    event_timestamp = datetime.now().isoformat()
    recipients = [
        ext for ext in extensions.values()
        if not ext.events or event_type in ext.events
    ]

    results = {}
    for ext in recipients:
        ok = await _dispatch_to_extension(ext, event_type, payload, event_timestamp)
        results[ext.name] = "delivered" if ok else "failed"
        if ok:
            global_stats["events_dispatched"] += 1
        else:
            global_stats["failed_dispatches"] += 1

    history_entry = {
        "event_type": event_type,
        "payload": payload,
        "timestamp": event_timestamp,
        "recipients": list(results.keys()),
        "results": results,
    }
    event_history.appendleft(history_entry)

    return results

# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "success": True,
        "status": "healthy",
        "node_id": NODE_ID,
        "name": NODE_NAME,
        "port": PORT,
        "extensions_count": len(extensions),
        "httpx_available": HTTPX_AVAILABLE,
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/status")
async def status():
    return {
        "success": True,
        "node_id": NODE_ID,
        "name": NODE_NAME,
        "configured": True,
        "config_summary": {"max_hook_retries": MAX_HOOK_RETRIES},
        "stats": {
            "total_extensions": len(extensions),
            "events_dispatched": global_stats["events_dispatched"],
            "failed_dispatches": global_stats["failed_dispatches"],
            "history_size": len(event_history),
        },
        "timestamp": datetime.now().isoformat(),
    }


@app.post("/extensions/register")
async def register_extension(request: RegisterRequest):
    ext = ExtensionRecord(
        name=request.name,
        version=request.version,
        callback_url=request.callback_url,
        events=request.events,
    )
    extensions[ext.name] = ext
    return {"success": True, "message": f"Extension '{ext.name}' registered", "extension": ext.to_dict()}


@app.delete("/extensions/{name}")
async def unregister_extension(name: str):
    if name not in extensions:
        raise HTTPException(status_code=404, detail=f"Extension '{name}' not found")
    del extensions[name]
    return {"success": True, "message": f"Extension '{name}' unregistered"}


@app.get("/extensions")
async def list_extensions():
    return {
        "success": True,
        "extensions": [e.to_dict() for e in extensions.values()],
        "total": len(extensions),
    }


@app.get("/extensions/{name}")
async def get_extension(name: str):
    if name not in extensions:
        raise HTTPException(status_code=404, detail=f"Extension '{name}' not found")
    return {"success": True, "extension": extensions[name].to_dict()}


@app.post("/events/dispatch")
async def dispatch_event(request: DispatchRequest):
    results = await _dispatch_event(request.event_type, request.payload)
    return {
        "success": True,
        "event_type": request.event_type,
        "dispatched_to": len(results),
        "results": results,
        "timestamp": datetime.now().isoformat(),
    }


@app.post("/events/dispatch/{event_type}")
async def dispatch_event_shorthand(event_type: str, payload: Optional[Dict[str, Any]] = None):
    results = await _dispatch_event(event_type, payload or {})
    return {
        "success": True,
        "event_type": event_type,
        "dispatched_to": len(results),
        "results": results,
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/events/history")
async def get_event_history(limit: int = 50):
    limit = max(1, min(limit, MAX_HISTORY))
    return {
        "success": True,
        "history": list(event_history)[:limit],
        "total_recorded": len(event_history),
        "limit": limit,
    }


@app.post("/extensions/ping")
async def ping_extension(request: PingRequest):
    if request.name not in extensions:
        raise HTTPException(status_code=404, detail=f"Extension '{request.name}' not found")
    if not HTTPX_AVAILABLE:
        raise HTTPException(status_code=503, detail="httpx not installed")

    ext = extensions[request.name]
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(ext.callback_url)
        reachable = resp.status_code < 500
    except Exception as exc:
        return {"success": True, "name": request.name, "reachable": False, "error": str(exc)}

    return {"success": True, "name": request.name, "reachable": reachable,
            "status_code": resp.status_code}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
