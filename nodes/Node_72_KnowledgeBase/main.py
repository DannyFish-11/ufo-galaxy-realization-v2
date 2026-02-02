"""Node 72: KnowledgeBase - RAG 知识库"""
import os, hashlib, json
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node 72 - KnowledgeBase", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# 尝试导入向量数据库
chromadb = None
try:
    import chromadb as _chromadb
    chromadb = _chromadb
except ImportError:
    pass

# 内存存储作为 fallback
memory_store: Dict[str, Dict] = {}

class AddDocRequest(BaseModel):
    content: str
    metadata: Optional[Dict[str, Any]] = None
    collection: str = "default"

class SearchRequest(BaseModel):
    query: str
    limit: int = 5
    collection: str = "default"

@app.get("/health")
async def health():
    return {"status": "healthy", "node_id": "72", "name": "KnowledgeBase", "chromadb_available": chromadb is not None, "storage": "chromadb" if chromadb else "memory", "timestamp": datetime.now().isoformat()}

@app.post("/add")
async def add_document(request: AddDocRequest):
    doc_id = hashlib.md5(request.content.encode()).hexdigest()[:12]
    
    if chromadb:
        try:
            client = chromadb.Client()
            collection = client.get_or_create_collection(request.collection)
            collection.add(documents=[request.content], metadatas=[request.metadata or {}], ids=[doc_id])
            return {"success": True, "id": doc_id, "storage": "chromadb"}
        except Exception as e:
            pass
    
    # Fallback to memory
    if request.collection not in memory_store:
        memory_store[request.collection] = {}
    memory_store[request.collection][doc_id] = {"content": request.content, "metadata": request.metadata or {}, "created_at": datetime.now().isoformat()}
    return {"success": True, "id": doc_id, "storage": "memory"}

@app.post("/search")
async def search(request: SearchRequest):
    if chromadb:
        try:
            client = chromadb.Client()
            collection = client.get_or_create_collection(request.collection)
            results = collection.query(query_texts=[request.query], n_results=request.limit)
            return {"success": True, "results": [{"id": id, "content": doc, "metadata": meta} for id, doc, meta in zip(results["ids"][0], results["documents"][0], results["metadatas"][0])], "storage": "chromadb"}
        except Exception as e:
            pass
    
    # Fallback: simple keyword search
    if request.collection not in memory_store:
        return {"success": True, "results": [], "storage": "memory"}
    
    results = []
    query_lower = request.query.lower()
    for doc_id, doc in memory_store[request.collection].items():
        if query_lower in doc["content"].lower():
            results.append({"id": doc_id, "content": doc["content"], "metadata": doc["metadata"]})
            if len(results) >= request.limit:
                break
    return {"success": True, "results": results, "storage": "memory"}

@app.delete("/delete/{collection}/{doc_id}")
async def delete_document(collection: str, doc_id: str):
    if chromadb:
        try:
            client = chromadb.Client()
            coll = client.get_or_create_collection(collection)
            coll.delete(ids=[doc_id])
            return {"success": True, "id": doc_id}
        except:
            pass
    
    if collection in memory_store and doc_id in memory_store[collection]:
        del memory_store[collection][doc_id]
        return {"success": True, "id": doc_id}
    raise HTTPException(status_code=404, detail="Document not found")

@app.post("/mcp/call")
async def mcp_call(request: dict):
    tool = request.get("tool", "")
    params = request.get("params", {})
    if tool == "add": return await add_document(AddDocRequest(**params))
    elif tool == "search": return await search(SearchRequest(**params))
    elif tool == "delete": return await delete_document(params.get("collection", "default"), params.get("doc_id"))
    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8072)
