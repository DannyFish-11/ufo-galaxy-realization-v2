"""
Node 25: GoogleSearch - Google搜索节点
========================================
提供Google搜索、自定义搜索功能
"""
import os
import requests
from datetime import datetime
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node 25 - GoogleSearch", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# Google配置
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID", "")  # Custom Search Engine ID
GOOGLE_API_URL = "https://www.googleapis.com/customsearch/v1"

class SearchRequest(BaseModel):
    query: str
    num: int = 10
    start: int = 1
    search_type: Optional[str] = None  # image

class GoogleSearchManager:
    def __init__(self):
        self.api_key = GOOGLE_API_KEY
        self.cse_id = GOOGLE_CSE_ID
        self.api_url = GOOGLE_API_URL

    def search(self, query: str, num: int = 10, start: int = 1,
               search_type: Optional[str] = None) -> Dict:
        """执行搜索"""
        if not self.api_key or not self.cse_id:
            raise RuntimeError("Google API key or CSE ID not configured")

        params = {
            "key": self.api_key,
            "cx": self.cse_id,
            "q": query,
            "num": min(num, 10),
            "start": start
        }

        if search_type:
            params["searchType"] = search_type

        response = requests.get(self.api_url, params=params, timeout=10)

        if response.status_code != 200:
            raise RuntimeError(f"Google API error: {response.text}")

        data = response.json()

        results = []
        for item in data.get("items", []):
            results.append({
                "title": item.get("title"),
                "url": item.get("link"),
                "description": item.get("snippet"),
                "display_url": item.get("displayLink")
            })

        return {
            "query": query,
            "results": results,
            "total": data.get("searchInformation", {}).get("totalResults", "0"),
            "time": data.get("searchInformation", {}).get("searchTime", 0)
        }

    def search_images(self, query: str, num: int = 10) -> Dict:
        """搜索图片"""
        return self.search(query, num, search_type="image")

# 全局Google搜索管理器
google_manager = GoogleSearchManager()

# ============ API 端点 ============

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "node_id": "25",
        "name": "GoogleSearch",
        "api_configured": bool(GOOGLE_API_KEY and GOOGLE_CSE_ID),
        "timestamp": datetime.now().isoformat()
    }

@app.post("/search")
async def search(request: SearchRequest):
    """执行搜索"""
    try:
        result = google_manager.search(
            query=request.query,
            num=request.num,
            start=request.start,
            search_type=request.search_type
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/search/images")
async def search_images(request: SearchRequest):
    """搜索图片"""
    try:
        result = google_manager.search_images(
            query=request.query,
            num=request.num
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8025)
