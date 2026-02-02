"""
Node 20: Qdrant - 向量数据库
"""
import os, uuid
from datetime import datetime
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node 20 - Qdrant", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

qdrant = None
try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, VectorParams, PointStruct
    qdrant = True
except ImportError:
    pass

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
client = None

collections = {}

class CreateCollectionRequest(BaseModel):
    name: str
    vector_size: int = 384
    distance: str = "cosine"

class UpsertRequest(BaseModel):
    collection: str
    vectors: List[List[float]]
    payloads: Optional[List[Dict[str, Any]]] = None
    ids: Optional[List[str]] = None

class SearchRequest(BaseModel):
    collection: str
    vector: List[float]
    limit: int = 10

def get_client():
    global client
    if qdrant and client is None:
        try:
            client = QdrantClient(url=QDRANT_URL)
        except:
            pass
    return client

@app.get("/health")
async def health():
    return {"status": "healthy" if qdrant else "degraded", "node_id": "20", "name": "Qdrant", "qdrant_available": qdrant is not None, "timestamp": datetime.now().isoformat()}

@app.post("/collections")
async def create_collection(request: CreateCollectionRequest):
    c = get_client()
    if c:
        try:
            from qdrant_client.models import Distance, VectorParams
            dist = Distance.COSINE if request.distance == "cosine" else Distance.EUCLID
            c.create_collection(collection_name=request.name, vectors_config=VectorParams(size=request.vector_size, distance=dist))
            return {"success": True, "collection": request.name}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    collections[request.name] = {"vectors": [], "payloads": [], "ids": [], "vector_size": request.vector_size}
    return {"success": True, "collection": request.name, "mode": "in-memory"}

@app.get("/collections")
async def list_collections():
    c = get_client()
    if c:
        try:
            cols = c.get_collections()
            return {"success": True, "collections": [col.name for col in cols.collections]}
        except:
            pass
    return {"success": True, "collections": list(collections.keys()), "mode": "in-memory"}

@app.post("/upsert")
async def upsert(request: UpsertRequest):
    c = get_client()
    ids = request.ids or [str(uuid.uuid4()) for _ in request.vectors]
    payloads = request.payloads or [{} for _ in request.vectors]
    
    if c:
        try:
            from qdrant_client.models import PointStruct
            points = [PointStruct(id=i, vector=v, payload=p) for i, v, p in zip(range(len(ids)), request.vectors, payloads)]
            c.upsert(collection_name=request.collection, points=points)
            return {"success": True, "upserted": len(points)}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    if request.collection not in collections:
        collections[request.collection] = {"vectors": [], "payloads": [], "ids": [], "vector_size": len(request.vectors[0])}
    
    col = collections[request.collection]
    for i, (v, p, id_) in enumerate(zip(request.vectors, payloads, ids)):
        col["vectors"].append(v)
        col["payloads"].append(p)
        col["ids"].append(id_)
    
    return {"success": True, "upserted": len(request.vectors), "mode": "in-memory"}

@app.post("/search")
async def search(request: SearchRequest):
    c = get_client()
    
    if c:
        try:
            results = c.search(collection_name=request.collection, query_vector=request.vector, limit=request.limit)
            return {"success": True, "results": [{"id": r.id, "score": r.score, "payload": r.payload} for r in results]}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    if request.collection not in collections:
        raise HTTPException(status_code=404, detail="Collection not found")
    
    col = collections[request.collection]
    
    def cosine_sim(a, b):
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x ** 2 for x in a) ** 0.5
        norm_b = sum(x ** 2 for x in b) ** 0.5
        return dot / (norm_a * norm_b) if norm_a and norm_b else 0
    
    scores = [(i, cosine_sim(request.vector, v)) for i, v in enumerate(col["vectors"])]
    scores.sort(key=lambda x: -x[1])
    
    results = [{"id": col["ids"][i], "score": s, "payload": col["payloads"][i]} for i, s in scores[:request.limit]]
    return {"success": True, "results": results, "mode": "in-memory"}

@app.post("/mcp/call")
async def mcp_call(request: dict):
    tool = request.get("tool", "")
    params = request.get("params", {})
    if tool == "create_collection": return await create_collection(CreateCollectionRequest(**params))
    elif tool == "list_collections": return await list_collections()
    elif tool == "upsert": return await upsert(UpsertRequest(**params))
    elif tool == "search": return await search(SearchRequest(**params))
    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8020)
