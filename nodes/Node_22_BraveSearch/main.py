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

app = FastAPI(title="Node 22 - BraveSearch", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8022)
