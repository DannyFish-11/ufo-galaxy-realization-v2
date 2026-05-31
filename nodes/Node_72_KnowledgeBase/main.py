# -*- coding: utf-8 -*-

"""
Node_72_KnowledgeBase: 知识库管理节点 (FastAPI)

提供知识的存储、检索、管理和维护 REST API。
"""

import dataclasses
import enum
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

# ---------------------------------------------------------------------------
# Port / CORS config (optional dependencies)
# ---------------------------------------------------------------------------

try:
    from core.port_config import get_service_port
    PORT = get_service_port("node_72") or 8072
except Exception as exc:
    logger.debug("Fallback triggered: %s", exc)
    PORT = int(os.getenv("PORT", "8072"))

try:
    from nodes.common.cors_config import get_cors_origins
    CORS_ORIGINS = get_cors_origins()
except Exception as exc:
    logger.debug("Fallback triggered: %s", exc)
    CORS_ORIGINS = ["*"]

# ---------------------------------------------------------------------------
# Configuration & Logging
# ---------------------------------------------------------------------------

KB_CONFIG_PATH = os.getenv("KB_CONFIG_PATH", os.path.join(str(Path.home()), "kb_config.json"))
DEFAULT_KB_PATH = os.getenv("KB_FILE_PATH", os.path.join(str(Path.home()), "knowledge_base.json"))

logging.basicConfig(
    level=logging.INFO,
    format="[Node_72] %(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("Node_72_KnowledgeBase")

# ---------------------------------------------------------------------------
# Enums & Data classes
# ---------------------------------------------------------------------------

class ServiceStatus(enum.Enum):
    STOPPED       = "stopped"
    INITIALIZING  = "initializing"
    RUNNING       = "running"
    DEGRADED      = "degraded"
    ERROR         = "error"


class KnowledgeStatus(enum.Enum):
    ACTIVE   = "active"
    ARCHIVED = "archived"
    PENDING  = "pending"


@dataclasses.dataclass
class KnowledgeBaseConfig:
    node_id: str = "Node_72_KnowledgeBase"
    log_level: str = "INFO"
    kb_file_path: str = DEFAULT_KB_PATH
    embedding_model: str = "mock_embedding_v1"
    max_results: int = 10


@dataclasses.dataclass
class KnowledgeEntry:
    id: str
    title: str
    content: str
    tags: List[str]
    category: str
    source: str
    status: KnowledgeStatus = KnowledgeStatus.ACTIVE
    embedding: Optional[List[float]] = None
    created_at: str = dataclasses.field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = dataclasses.field(default_factory=lambda: datetime.utcnow().isoformat())

# ---------------------------------------------------------------------------
# Core service
# ---------------------------------------------------------------------------

class KnowledgeBaseService:
    """知识库管理主服务"""

    def __init__(self, config: KnowledgeBaseConfig = None):
        self.config = config or KnowledgeBaseConfig()
        self.status = ServiceStatus.RUNNING
        self._kb: Dict[str, KnowledgeEntry] = {}
        self._load_from_disk()

    def _load_from_disk(self):
        """从磁盘加载已持久化的知识条目"""
        try:
            if os.path.exists(self.config.kb_file_path):
                with open(self.config.kb_file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for eid, ed in data.items():
                    ed["status"] = KnowledgeStatus(ed.get("status", "active"))
                    ed.setdefault("title", "")
                    ed.setdefault("tags", [])
                    ed.setdefault("category", "")
                    ed.setdefault("source", "")
                    self._kb[eid] = KnowledgeEntry(**ed)
                logger.info(f"已加载 {len(self._kb)} 条知识")
        except Exception as e:
            logger.warning(f"加载知识库文件失败（将从空库开始）: {e}")

    def _save_to_disk(self):
        """持久化知识库到磁盘"""
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.config.kb_file_path)), exist_ok=True)
            data = {}
            for eid, entry in self._kb.items():
                d = dataclasses.asdict(entry)
                d["status"] = d["status"].value
                data[eid] = d
            with open(self.config.kb_file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"保存知识库失败: {e}")

    def _generate_embedding(self, text: str) -> List[float]:
        """模拟生成文本向量（实际场景替换为真实 embedding 调用）"""
        words = text.split()
        vec = [hash(w) / 1e10 for w in words]
        return (vec + [0.0] * 128)[:128]

    # -- CRUD ----------------------------------------------------------------

    def add_entry(self, title: str, content: str, tags: List[str], category: str, source: str) -> str:
        eid = str(uuid.uuid4())
        entry = KnowledgeEntry(
            id=eid,
            title=title,
            content=content,
            tags=tags,
            category=category,
            source=source,
            embedding=self._generate_embedding(content),
        )
        self._kb[eid] = entry
        self._save_to_disk()
        return eid

    def get_entry(self, eid: str) -> Optional[KnowledgeEntry]:
        return self._kb.get(eid)

    def update_entry(self, eid: str, **kwargs) -> bool:
        if eid not in self._kb:
            return False
        entry = self._kb[eid]
        for k, v in kwargs.items():
            if hasattr(entry, k):
                setattr(entry, k, v)
        entry.updated_at = datetime.utcnow().isoformat()
        if "content" in kwargs:
            entry.embedding = self._generate_embedding(kwargs["content"])
        self._save_to_disk()
        return True

    def delete_entry(self, eid: str) -> bool:
        if eid not in self._kb:
            return False
        del self._kb[eid]
        self._save_to_disk()
        return True

    def list_entries(self, tag: str = None, category: str = None) -> List[KnowledgeEntry]:
        items = list(self._kb.values())
        if tag:
            items = [e for e in items if tag in e.tags]
        if category:
            items = [e for e in items if e.category == category]
        return items

    def search(self, query: str, top_k: int = 5) -> List[Tuple[KnowledgeEntry, float]]:
        """关键字相似度搜索（可替换为向量检索）"""
        query_words = set(query.lower().split())
        scored = []
        for entry in self._kb.values():
            if entry.status != KnowledgeStatus.ACTIVE:
                continue
            content_words = set((entry.title + " " + entry.content).lower().split())
            score = float(len(query_words & content_words))
            if score > 0:
                scored.append((entry, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def bulk_import(self, items: List[Dict[str, Any]]) -> List[str]:
        ids = []
        for item in items:
            eid = self.add_entry(
                title=item.get("title", ""),
                content=item.get("content", ""),
                tags=item.get("tags", []),
                category=item.get("category", ""),
                source=item.get("source", "import"),
            )
            ids.append(eid)
        return ids

    def get_stats(self) -> Dict[str, Any]:
        entries = list(self._kb.values())
        categories: Dict[str, int] = {}
        tags_count: Dict[str, int] = {}
        for e in entries:
            categories[e.category] = categories.get(e.category, 0) + 1
            for t in e.tags:
                tags_count[t] = tags_count.get(t, 0) + 1
        return {
            "total": len(entries),
            "active": sum(1 for e in entries if e.status == KnowledgeStatus.ACTIVE),
            "archived": sum(1 for e in entries if e.status == KnowledgeStatus.ARCHIVED),
            "categories": categories,
            "tags": tags_count,
        }

    def entry_to_dict(self, entry: KnowledgeEntry) -> Dict[str, Any]:
        d = dataclasses.asdict(entry)
        d["status"] = d["status"].value
        d.pop("embedding", None)  # omit embedding from API responses
        return d


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------

class AddKnowledgeRequest(BaseModel):
    title: str = ""
    content: str
    tags: List[str] = []
    category: str = ""
    source: str = ""

class UpdateKnowledgeRequest(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[List[str]] = None
    category: Optional[str] = None
    source: Optional[str] = None
    status: Optional[str] = None

class SearchRequest(BaseModel):
    query: str
    top_k: int = 5

class MCPCallRequest(BaseModel):
    tool: str
    params: Dict[str, Any] = {}

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

_svc = KnowledgeBaseService()

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Node_72_KnowledgeBase FastAPI 启动")
    yield
    logger.info("Node_72_KnowledgeBase FastAPI 关闭")

app = FastAPI(
    title="Node_72_KnowledgeBase",
    description="知识库管理服务 API",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -- routes ------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok", "node": "Node_72_KnowledgeBase", "timestamp": datetime.utcnow().isoformat()}


@app.get("/status")
def status():
    return {
        "status": _svc.status.value,
        "node": "Node_72_KnowledgeBase",
        "knowledge_count": len(_svc._kb),
        "kb_file": _svc.config.kb_file_path,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/knowledge")
def list_knowledge(tag: str = None, category: str = None):
    entries = _svc.list_entries(tag=tag, category=category)
    return {"items": [_svc.entry_to_dict(e) for e in entries], "count": len(entries)}


@app.post("/knowledge", status_code=201)
def add_knowledge(req: AddKnowledgeRequest):
    eid = _svc.add_entry(req.title, req.content, req.tags, req.category, req.source)
    entry = _svc.get_entry(eid)
    return {"id": eid, "entry": _svc.entry_to_dict(entry)}


@app.get("/knowledge/stats")
def knowledge_stats():
    return _svc.get_stats()


@app.get("/knowledge/export")
def export_knowledge():
    items = [_svc.entry_to_dict(e) for e in _svc._kb.values()]
    return {"items": items, "count": len(items)}


@app.post("/knowledge/search")
def search_knowledge(req: SearchRequest):
    results = _svc.search(req.query, req.top_k)
    return {
        "query": req.query,
        "results": [{"score": score, "entry": _svc.entry_to_dict(e)} for e, score in results],
    }


@app.post("/knowledge/import")
def import_knowledge(items: List[AddKnowledgeRequest]):
    ids = _svc.bulk_import([i.dict() for i in items])
    return {"imported": len(ids), "ids": ids}


@app.get("/knowledge/{entry_id}")
def get_knowledge(entry_id: str):
    entry = _svc.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"知识条目不存在: {entry_id}")
    return _svc.entry_to_dict(entry)


@app.put("/knowledge/{entry_id}")
def update_knowledge(entry_id: str, req: UpdateKnowledgeRequest):
    updates = {k: v for k, v in req.dict().items() if v is not None}
    if "status" in updates:
        try:
            updates["status"] = KnowledgeStatus(updates["status"])
        except ValueError:
            raise HTTPException(status_code=400, detail=f"无效的状态值: {updates['status']}")
    ok = _svc.update_entry(entry_id, **updates)
    if not ok:
        raise HTTPException(status_code=404, detail=f"知识条目不存在: {entry_id}")
    return _svc.entry_to_dict(_svc.get_entry(entry_id))


@app.delete("/knowledge/{entry_id}")
def delete_knowledge(entry_id: str):
    ok = _svc.delete_entry(entry_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"知识条目不存在: {entry_id}")
    return {"success": True, "id": entry_id}


@app.post("/mcp/call")
def mcp_call(req: MCPCallRequest):
    p = req.params
    try:
        if req.tool == "add_knowledge":
            eid = _svc.add_entry(p.get("title",""), p["content"], p.get("tags",[]), p.get("category",""), p.get("source",""))
            return {"result": eid}
        elif req.tool == "search_knowledge":
            results = _svc.search(p["query"], p.get("top_k", 5))
            return {"result": [{"score": s, "entry": _svc.entry_to_dict(e)} for e, s in results]}
        elif req.tool == "get_knowledge":
            entry = _svc.get_entry(p["id"])
            if not entry:
                raise HTTPException(status_code=404, detail="not found")
            return {"result": _svc.entry_to_dict(entry)}
        elif req.tool == "delete_knowledge":
            return {"result": _svc.delete_entry(p["id"])}
        elif req.tool == "get_stats":
            return {"result": _svc.get_stats()}
        elif req.tool == "list_knowledge":
            items = _svc.list_entries(tag=p.get("tag"), category=p.get("category"))
            return {"result": [_svc.entry_to_dict(e) for e in items]}
        else:
            raise HTTPException(status_code=404, detail=f"未知工具: {req.tool}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
