"""Node 08: Fetch - HTTP 客户端"""
import os, requests
from datetime import datetime
from typing import Dict, Any, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node 08 - Fetch", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

class FetchRequest(BaseModel):
    url: str
    method: str = "GET"
    headers: Optional[Dict[str, str]] = None
    data: Optional[Dict[str, Any]] = None
    timeout: int = 30

@app.get("/health")
async def health():
    return {"status": "healthy", "node_id": "08", "name": "Fetch", "timestamp": datetime.now().isoformat()}

@app.post("/fetch")
async def fetch(request: FetchRequest):
    try:
        response = requests.request(
            method=request.method,
            url=request.url,
            headers=request.headers,
            json=request.data if request.method in ["POST", "PUT", "PATCH"] else None,
            params=request.data if request.method == "GET" else None,
            timeout=request.timeout
        )
        return {"success": True, "status_code": response.status_code, "headers": dict(response.headers), "body": response.text[:10000]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/download")
async def download(url: str, save_path: str):
    try:
        response = requests.get(url, stream=True, timeout=60)
        response.raise_for_status()
        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return {"success": True, "path": save_path, "size": os.path.getsize(save_path)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/mcp/call")
async def mcp_call(request: dict):
    tool = request.get("tool", "")
    params = request.get("params", {})
    if tool == "fetch":
        return await fetch(FetchRequest(**params))
    elif tool == "download":
        return await download(params.get("url"), params.get("save_path"))
    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8008)
