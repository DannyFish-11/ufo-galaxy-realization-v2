"""
Node 22: BraveSearch - Brave搜索节点
======================================
提供网页搜索、图片搜索、新闻搜索功能
"""
import os
import requests
from datetime import datetime
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from nodes.common.cors_config import get_cors_origins

from nodes.common.node_auth import install_node_auth

app = FastAPI(title="Node 22 - BraveSearch", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=get_cors_origins(), allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# HTTP 面的身份认证。此前这个节点的 HTTP 面没有任何认证,且绑 0.0.0.0。
# 实现在 nodes.common.node_auth,判定复用 core.auth(网关与 launcher 早就在用)。
install_node_auth(app, "Node_22_BraveSearch")

# Brave配置
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY", "")
BRAVE_API_URL = "https://api.search.brave.com/res/v1"

class SearchRequest(BaseModel):
    query: str
    count: int = 10
    offset: int = 0
    search_type: str = "web"  # web, images, news

class BraveSearchManager:
    def __init__(self):
        self.api_key = BRAVE_API_KEY
        self.api_url = BRAVE_API_URL

    def search(self, query: str, count: int = 10, offset: int = 0, 
               search_type: str = "web") -> Dict:
        """执行搜索"""
        if not self.api_key:
            raise RuntimeError("Brave API key not configured")

        endpoint = f"/{search_type}/search"
        headers = {
            "X-Subscription-Token": self.api_key,
            "Accept": "application/json"
        }
        params = {
            "q": query,
            "count": min(count, 20),
            "offset": offset
        }

        response = requests.get(
            f"{self.api_url}{endpoint}",
            headers=headers,
            params=params,
            timeout=10
        )

        if response.status_code != 200:
            raise RuntimeError(f"Brave API error: {response.text}")

        data = response.json()

        if search_type == "web":
            results = []
            for item in data.get("web", {}).get("results", []):
                results.append({
                    "title": item.get("title"),
                    "url": item.get("url"),
                    "description": item.get("description"),
                    "age": item.get("age")
                })
            return {
                "query": query,
                "results": results,
                "total": data.get("web", {}).get("total", 0)
            }
        elif search_type == "images":
            results = []
            for item in data.get("results", []):
                results.append({
                    "title": item.get("title"),
                    "url": item.get("url"),
                    "thumbnail": item.get("thumbnail", {}).get("src"),
                    "source": item.get("page", {}).get("url")
                })
            return {"query": query, "results": results}
        elif search_type == "news":
            results = []
            for item in data.get("results", []):
                results.append({
                    "title": item.get("title"),
                    "url": item.get("url"),
                    "description": item.get("description"),
                    "published": item.get("age")
                })
            return {"query": query, "results": results}

        return data

    def suggest(self, query: str) -> List[str]:
        """搜索建议"""
        if not self.api_key:
            raise RuntimeError("Brave API key not configured")

        headers = {"X-Subscription-Token": self.api_key}
        params = {"q": query}

        response = requests.get(
            f"{self.api_url}/suggest",
            headers=headers,
            params=params,
            timeout=5
        )

        if response.status_code == 200:
            data = response.json()
            return [s.get("query") for s in data.get("results", [])]
        return []

# 全局Brave搜索管理器
brave_manager = BraveSearchManager()

# ============ API 端点 ============

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "node_id": "22",
        "name": "BraveSearch",
        "api_configured": bool(BRAVE_API_KEY),
        "timestamp": datetime.now().isoformat()
    }

@app.get("/status")
async def node_status():
    """Node status endpoint."""
    return {
        "node_id": "22",
        "name": "BraveSearch",
        "port": 8022,
        "configured": bool(BRAVE_API_KEY),
        "timestamp": datetime.now().isoformat()
    }

@app.post("/search")
async def search(request: SearchRequest):
    """执行搜索"""
    try:
        result = brave_manager.search(
            query=request.query,
            count=request.count,
            offset=request.offset,
            search_type=request.search_type
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/suggest")
async def suggest(query: str):
    """搜索建议"""
    try:
        suggestions = brave_manager.suggest(query)
        return {"suggestions": suggestions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def execute(command: str, **params: Any) -> Dict[str, Any]:
    """统一执行器的入口(``fusion_entry.py`` 在模块上按 process / execute / run / handle 找)。

    此前这个模块一个都没有:进程内调这个节点(模型的 ``node__22__search``、边说边核的联网那一级)永远回
    「No executable method found」—— 联网搜索在进程内从没走通过。缺 Key、搜不到都照实失败,不模拟结果。
    """
    import asyncio

    brave_manager.api_key = os.getenv("BRAVE_API_KEY", "") or brave_manager.api_key  # 面板后配的 Key 也认
    if command not in ("search", "suggest"):
        return {"success": False, "error": f"Unknown action: {command}(支持 search / suggest)"}
    query = str(params.get("query") or params.get("q") or "").strip()
    if not query:
        return {"success": False, "error": "缺 query"}
    if not brave_manager.api_key:
        return {"success": False, "error": "没配 BRAVE_API_KEY,联网搜索用不了"}
    try:
        if command == "suggest":
            return {"success": True, "suggestions": await asyncio.to_thread(brave_manager.suggest, query)}
        data = await asyncio.to_thread(
            brave_manager.search,
            query,
            int(params.get("count") or 10),
            int(params.get("offset") or 0),
            str(params.get("search_type") or "web"),
        )
    except Exception as exc:  # noqa: BLE001 — 网络 / 配额 / 返回不对,照实说
        return {"success": False, "error": f"Brave 搜索失败:{exc}"}
    return {"success": True, **(data if isinstance(data, dict) else {"results": data})}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8022)
