"""
Node 25: GoogleSearch - Google 搜索 API
"""
import os, requests
from typing import Optional, List
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node 25 - GoogleSearch", version="3.0.0", description="Google Custom Search API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID", "")
GOOGLE_SEARCH_URL = "https://www.googleapis.com/customsearch/v1"

class SearchRequest(BaseModel):
    query: str
    num: int = 10
    start: int = 1
    lang: str = "zh-CN"
    safe: str = "off"

@app.get("/health")
async def health():
    return {
        "status": "healthy" if (GOOGLE_API_KEY and GOOGLE_CSE_ID) else "degraded",
        "node_id": "25",
        "name": "GoogleSearch",
        "api_key_configured": bool(GOOGLE_API_KEY),
        "cse_id_configured": bool(GOOGLE_CSE_ID)
    }

@app.post("/search")
async def search(request: SearchRequest):
    """执行 Google 搜索"""
    if not GOOGLE_API_KEY or not GOOGLE_CSE_ID:
        raise HTTPException(status_code=503, detail="GOOGLE_API_KEY or GOOGLE_CSE_ID not configured")
    
    params = {
        "key": GOOGLE_API_KEY,
        "cx": GOOGLE_CSE_ID,
        "q": request.query,
        "num": min(request.num, 10),
        "start": request.start,
        "lr": f"lang_{request.lang}",
        "safe": request.safe
    }
    
    try:
        response = requests.get(GOOGLE_SEARCH_URL, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        results = []
        for item in data.get("items", []):
            results.append({
                "title": item.get("title", ""),
                "link": item.get("link", ""),
                "snippet": item.get("snippet", ""),
                "displayLink": item.get("displayLink", "")
            })
        
        return {
            "success": True,
            "query": request.query,
            "total_results": int(data.get("searchInformation", {}).get("totalResults", 0)),
            "results": results,
            "count": len(results)
        }
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/mcp/call")
async def mcp_call(request: dict):
    tool = request.get("tool", "")
    params = request.get("params", {})
    if tool == "search": return await search(SearchRequest(**params))
    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8025)
