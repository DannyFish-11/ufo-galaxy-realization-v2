"""
Node 20: Qdrant - 向量数据库节点
==================================
提供向量存储、相似度搜索、向量索引功能
"""
import os
import json
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# 尝试导入qdrant_client
try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, VectorParams, PointStruct
    QDRANT_AVAILABLE = True
except ImportError:
    QDRANT_AVAILABLE = False

app = FastAPI(title="Node 20 - Qdrant", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# Qdrant配置
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", None)

class CollectionRequest(BaseModel):
    name: str
    vector_size: int = 1536
    distance: str = "Cosine"  # Cosine, Euclid, Dot

class PointRequest(BaseModel):
    collection: str
    id: Optional[str] = None
    vector: List[float]
    payload: Dict[str, Any] = {}

class SearchRequest(BaseModel):
    collection: str
    vector: List[float]
    limit: int = 10
    score_threshold: Optional[float] = None

class QdrantManager:
    def __init__(self):
        self.client = None
        self._connected = False

    def connect(self):
        """连接Qdrant"""
        if not QDRANT_AVAILABLE:
            raise RuntimeError("qdrant-client not installed. Install with: pip install qdrant-client")

        if not self.client:
            kwargs = {"host": QDRANT_HOST, "port": QDRANT_PORT}
            if QDRANT_API_KEY:
                kwargs["api_key"] = QDRANT_API_KEY
            self.client = QdrantClient(**kwargs)
            self._connected = True

    def create_collection(self, name: str, vector_size: int = 1536, distance: str = "Cosine") -> bool:
        """创建集合"""
        if not self._connected:
            self.connect()

        distance_map = {
            "Cosine": Distance.COSINE,
            "Euclid": Distance.EUCLID,
            "Dot": Distance.DOT
        }

        self.client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=vector_size, distance=distance_map.get(distance, Distance.COSINE))
        )
        return True

    def delete_collection(self, name: str) -> bool:
        """删除集合"""
        if not self._connected:
            self.connect()

        self.client.delete_collection(collection_name=name)
        return True

    def list_collections(self) -> List[str]:
        """列出所有集合"""
        if not self._connected:
            self.connect()

        collections = self.client.get_collections()
        return [c.name for c in collections.collections]

    def upsert_point(self, collection: str, vector: List[float], 
                     point_id: Optional[str] = None, payload: Dict = None) -> str:
        """插入/更新向量点"""
        if not self._connected:
            self.connect()

        point_id = point_id or str(uuid.uuid4())
        point = PointStruct(id=point_id, vector=vector, payload=payload or {})

        self.client.upsert(collection_name=collection, points=[point])
        return point_id

    def search(self, collection: str, vector: List[float], 
               limit: int = 10, score_threshold: Optional[float] = None) -> List[Dict]:
        """向量搜索"""
        if not self._connected:
            self.connect()

        results = self.client.search(
            collection_name=collection,
            query_vector=vector,
            limit=limit,
            score_threshold=score_threshold
        )

        return [{
            "id": r.id,
            "score": r.score,
            "payload": r.payload
        } for r in results]

    def delete_point(self, collection: str, point_id: str) -> bool:
        """删除向量点"""
        if not self._connected:
            self.connect()

        self.client.delete(collection_name=collection, points_selector=[point_id])
        return True

    def get_point(self, collection: str, point_id: str) -> Optional[Dict]:
        """获取向量点"""
        if not self._connected:
            self.connect()

        points = self.client.retrieve(collection_name=collection, ids=[point_id], with_vectors=True)
        if points:
            return {
                "id": points[0].id,
                "vector": points[0].vector,
                "payload": points[0].payload
            }
        return None

# 全局Qdrant管理器
qdrant_manager = QdrantManager()

# ============ API 端点 ============

@app.get("/health")
async def health():
    status = "healthy" if qdrant_manager._connected else "standby"
    return {
        "status": status,
        "node_id": "20",
        "name": "Qdrant",
        "host": QDRANT_HOST,
        "port": QDRANT_PORT,
        "qdrant_available": QDRANT_AVAILABLE,
        "timestamp": datetime.now().isoformat()
    }

@app.post("/collections")
async def create_collection(request: CollectionRequest):
    """创建集合"""
    if not QDRANT_AVAILABLE:
        raise HTTPException(status_code=503, detail="qdrant-client not installed")

    try:
        success = qdrant_manager.create_collection(request.name, request.vector_size, request.distance)
        return {"success": success}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/collections/{name}")
async def delete_collection(name: str):
    """删除集合"""
    if not QDRANT_AVAILABLE:
        raise HTTPException(status_code=503, detail="qdrant-client not installed")

    try:
        success = qdrant_manager.delete_collection(name)
        return {"success": success}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/collections")
async def list_collections():
    """列出所有集合"""
    if not QDRANT_AVAILABLE:
        raise HTTPException(status_code=503, detail="qdrant-client not installed")

    try:
        collections = qdrant_manager.list_collections()
        return {"collections": collections}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/points")
async def upsert_point(request: PointRequest):
    """插入/更新向量点"""
    if not QDRANT_AVAILABLE:
        raise HTTPException(status_code=503, detail="qdrant-client not installed")

    try:
        point_id = qdrant_manager.upsert_point(
            request.collection, request.vector, request.id, request.payload
        )
        return {"id": point_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/search")
async def search_vectors(request: SearchRequest):
    """向量搜索"""
    if not QDRANT_AVAILABLE:
        raise HTTPException(status_code=503, detail="qdrant-client not installed")

    try:
        results = qdrant_manager.search(
            request.collection, request.vector, request.limit, request.score_threshold
        )
        return {"results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/points/{collection}/{point_id}")
async def delete_point(collection: str, point_id: str):
    """删除向量点"""
    if not QDRANT_AVAILABLE:
        raise HTTPException(status_code=503, detail="qdrant-client not installed")

    try:
        success = qdrant_manager.delete_point(collection, point_id)
        return {"success": success}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/points/{collection}/{point_id}")
async def get_point(collection: str, point_id: str):
    """获取向量点"""
    if not QDRANT_AVAILABLE:
        raise HTTPException(status_code=503, detail="qdrant-client not installed")

    try:
        point = qdrant_manager.get_point(collection, point_id)
        if not point:
            raise HTTPException(status_code=404, detail="Point not found")
        return point
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8020)
