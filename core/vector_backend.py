"""
UFO Galaxy - 统一向量后端
==========================

支持多种向量引擎，按优先级自动检测并降级：

  KB_VECTOR_BACKEND=chroma|qdrant|local  (默认 local)

  若 backend=chroma：尝试导入 chromadb，失败则降级为 local
  若 backend=qdrant：尝试连接 QDRANT_URL，失败则降级为 local
  若 backend=local： 直接使用 Jaccard 关键词搜索（无外部依赖）

环境变量：
  KB_VECTOR_BACKEND   向量引擎选择：chroma | qdrant | local（默认 local）
  QDRANT_URL          Qdrant 服务器地址，例如 http://localhost:6333
  CHROMA_PERSIST_DIR  ChromaDB 持久化目录（默认 ./chroma_db）
  KB_COLLECTION       向量集合名称（默认 ufo_galaxy_knowledge）
  KB_VECTOR_SIZE      向量维度（默认 384）

接口（所有后端统一）：
  backend.add_document(doc_id, content, metadata=None)
  backend.search(query, top_k=5)  -> List[SearchResult]
  backend.delete_document(doc_id)
  backend.backend_name  -> str
  backend.is_vector_mode -> bool
"""

import hashlib
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("UFO-Galaxy.VectorBackend")

# ---------------------------------------------------------------------------
# 结果数据类
# ---------------------------------------------------------------------------

@dataclass
class SearchResult:
    """统一搜索结果"""
    doc_id: str
    content: str
    score: float
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "content": self.content[:200],
            "score": round(self.score, 4),
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# 本地关键词后端（无依赖，始终可用）
# ---------------------------------------------------------------------------

class _LocalKeywordBackend:
    """本地 Jaccard 关键词搜索后端（零外部依赖）"""

    name = "local"

    def __init__(self):
        self._index: Dict[str, Dict[str, Any]] = {}

    def add_document(self, doc_id: str, content: str, metadata: Optional[Dict] = None):
        words = set(content.lower().split())
        self._index[doc_id] = {
            "content": content,
            "words": words,
            "metadata": metadata or {},
            "indexed_at": time.time(),
        }

    def search(self, query: str, top_k: int = 5) -> List[SearchResult]:
        query_words = set(query.lower().split())
        scores = []
        for doc_id, doc in self._index.items():
            intersection = query_words & doc["words"]
            union = query_words | doc["words"]
            score = len(intersection) / max(len(union), 1)
            if score > 0:
                scores.append(SearchResult(
                    doc_id=doc_id,
                    content=doc["content"],
                    score=score,
                    metadata=doc["metadata"],
                ))
        scores.sort(key=lambda x: x.score, reverse=True)
        return scores[:top_k]

    def delete_document(self, doc_id: str):
        self._index.pop(doc_id, None)

    @property
    def document_count(self) -> int:
        return len(self._index)

    @property
    def is_vector_mode(self) -> bool:
        return False


# ---------------------------------------------------------------------------
# ChromaDB 后端
# ---------------------------------------------------------------------------

class _ChromaBackend:
    """ChromaDB 向量后端"""

    name = "chroma"

    def __init__(self, persist_dir: str, collection_name: str, vector_size: int):
        self._persist_dir = persist_dir
        self._collection_name = collection_name
        self._vector_size = vector_size
        self._client = None
        self._collection = None
        self._ready = False
        self._fallback = _LocalKeywordBackend()

    def _try_init(self) -> bool:
        """尝试初始化 ChromaDB，失败返回 False"""
        try:
            import chromadb  # type: ignore

            os.makedirs(self._persist_dir, exist_ok=True)
            self._client = chromadb.PersistentClient(path=self._persist_dir)
            self._collection = self._client.get_or_create_collection(
                name=self._collection_name,
                metadata={"hnsw:space": "cosine"},
            )
            self._ready = True
            logger.info(f"ChromaDB 已连接，集合: {self._collection_name}，目录: {self._persist_dir}")
            return True
        except ImportError:
            logger.info("chromadb 未安装，降级为本地关键词搜索（pip install chromadb）")
            return False
        except Exception as exc:
            logger.warning(f"ChromaDB 初始化失败: {exc}，降级为本地关键词搜索")
            return False

    def add_document(self, doc_id: str, content: str, metadata: Optional[Dict] = None):
        if not self._ready:
            self._fallback.add_document(doc_id, content, metadata)
            return
        try:
            _id = _stable_id(doc_id)
            self._collection.upsert(
                ids=[_id],
                documents=[content],
                metadatas=[{**(metadata or {}), "_doc_id": doc_id}],
            )
        except Exception as exc:
            logger.warning(f"ChromaDB add_document 失败: {exc}，写入本地索引")
            self._fallback.add_document(doc_id, content, metadata)

    def search(self, query: str, top_k: int = 5) -> List[SearchResult]:
        if not self._ready:
            return self._fallback.search(query, top_k)
        try:
            results = self._collection.query(
                query_texts=[query],
                n_results=min(top_k, max(self._collection.count(), 1)),
                include=["documents", "metadatas", "distances"],
            )
            output = []
            docs = results.get("documents", [[]])[0]
            metas = results.get("metadatas", [[]])[0]
            dists = results.get("distances", [[]])[0]
            for doc, meta, dist in zip(docs, metas, dists):
                score = max(0.0, 1.0 - dist)
                doc_id = meta.pop("_doc_id", "") if meta else ""
                output.append(SearchResult(
                    doc_id=doc_id,
                    content=doc,
                    score=score,
                    metadata=meta or {},
                ))
            return output
        except Exception as exc:
            logger.warning(f"ChromaDB search 失败: {exc}，使用本地搜索")
            return self._fallback.search(query, top_k)

    def delete_document(self, doc_id: str):
        if not self._ready:
            self._fallback.delete_document(doc_id)
            return
        try:
            self._collection.delete(ids=[_stable_id(doc_id)])
        except Exception as exc:
            logger.warning(f"ChromaDB delete_document 失败: {exc}")

    @property
    def document_count(self) -> int:
        if self._ready and self._collection is not None:
            try:
                return self._collection.count()
            except Exception:
                pass
        return self._fallback.document_count

    @property
    def is_vector_mode(self) -> bool:
        return self._ready


# ---------------------------------------------------------------------------
# Qdrant 后端
# ---------------------------------------------------------------------------

class _QdrantBackend:
    """Qdrant 向量后端"""

    name = "qdrant"

    def __init__(self, url: str, collection_name: str, vector_size: int):
        self._url = url
        self._collection_name = collection_name
        self._vector_size = vector_size
        self._client = None
        self._ready = False
        self._fallback = _LocalKeywordBackend()

    def _try_init(self) -> bool:
        """尝试连接 Qdrant，失败返回 False"""
        if not self._url:
            logger.info("QDRANT_URL 未设置，降级为本地关键词搜索")
            return False
        try:
            from qdrant_client import QdrantClient  # type: ignore
            from qdrant_client.models import Distance, VectorParams  # type: ignore

            self._client = QdrantClient(url=self._url, timeout=5)
            self._client.get_collections()  # 连接测试

            collections = [c.name for c in self._client.get_collections().collections]
            if self._collection_name not in collections:
                self._client.create_collection(
                    collection_name=self._collection_name,
                    vectors_config=VectorParams(size=self._vector_size, distance=Distance.COSINE),
                )
            self._ready = True
            logger.info(f"Qdrant 已连接: {self._url}，集合: {self._collection_name}")
            return True
        except ImportError:
            logger.info("qdrant-client 未安装，降级为本地关键词搜索（pip install qdrant-client）")
            return False
        except Exception as exc:
            logger.info(f"Qdrant 不可用 ({exc})，降级为本地关键词搜索")
            return False

    def add_document(self, doc_id: str, content: str, metadata: Optional[Dict] = None):
        if not self._ready:
            self._fallback.add_document(doc_id, content, metadata)
            return
        # 无向量时退到本地存储，等待上层传入向量后调用 add_document_vector
        self._fallback.add_document(doc_id, content, metadata)

    def add_document_vector(self, doc_id: str, content: str, vector: List[float], metadata: Optional[Dict] = None):
        """带向量的索引（Qdrant 专用）"""
        if not self._ready or not self._client:
            self._fallback.add_document(doc_id, content, metadata)
            return
        try:
            from qdrant_client.models import PointStruct  # type: ignore
            self._client.upsert(
                collection_name=self._collection_name,
                points=[PointStruct(
                    id=_int_id(doc_id),
                    vector=vector,
                    payload={"doc_id": doc_id, "content": content, **(metadata or {})},
                )],
            )
        except Exception as exc:
            logger.warning(f"Qdrant upsert 失败: {exc}，写入本地索引")
            self._fallback.add_document(doc_id, content, metadata)

    def search(self, query: str, top_k: int = 5) -> List[SearchResult]:
        # Qdrant 无文本查询接口，回退到本地关键词
        return self._fallback.search(query, top_k)

    def search_vector(self, query_vector: List[float], top_k: int = 5) -> List[SearchResult]:
        """向量相似度搜索"""
        if not self._ready or not self._client:
            return []
        try:
            results = self._client.search(
                collection_name=self._collection_name,
                query_vector=query_vector,
                limit=top_k,
            )
            return [
                SearchResult(
                    doc_id=r.payload.get("doc_id", ""),
                    content=r.payload.get("content", ""),
                    score=round(r.score, 4),
                    metadata={k: v for k, v in r.payload.items() if k not in ("doc_id", "content")},
                )
                for r in results
            ]
        except Exception as exc:
            logger.warning(f"Qdrant search 失败: {exc}")
            return []

    def delete_document(self, doc_id: str):
        self._fallback.delete_document(doc_id)
        if self._ready and self._client:
            try:
                from qdrant_client.models import PointIdsList  # type: ignore
                self._client.delete(
                    collection_name=self._collection_name,
                    points_selector=PointIdsList(points=[_int_id(doc_id)]),
                )
            except Exception as exc:
                logger.warning(f"Qdrant delete 失败: {exc}")

    @property
    def document_count(self) -> int:
        return self._fallback.document_count

    @property
    def is_vector_mode(self) -> bool:
        return self._ready


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _stable_id(doc_id: str) -> str:
    """为 ChromaDB 生成稳定字符串 ID"""
    return hashlib.sha256(doc_id.encode()).hexdigest()


def _int_id(doc_id: str) -> int:
    """为 Qdrant 生成稳定整数 ID"""
    return int(hashlib.sha256(doc_id.encode()).hexdigest(), 16) & 0x7FFFFFFFFFFFFFFF


# ---------------------------------------------------------------------------
# 工厂函数
# ---------------------------------------------------------------------------

def create_vector_backend(
    backend: Optional[str] = None,
    qdrant_url: Optional[str] = None,
    chroma_persist_dir: Optional[str] = None,
    collection_name: Optional[str] = None,
    vector_size: Optional[int] = None,
):
    """
    创建向量后端实例（含自动检测与降级）。

    参数优先级：函数参数 > 环境变量 > 默认值

    Args:
        backend: 后端类型 chroma|qdrant|local（默认读 KB_VECTOR_BACKEND，fallback local）
        qdrant_url: Qdrant 服务器地址（默认读 QDRANT_URL）
        chroma_persist_dir: ChromaDB 持久化目录（默认读 CHROMA_PERSIST_DIR，fallback ./chroma_db）
        collection_name: 集合/索引名（默认读 KB_COLLECTION，fallback ufo_galaxy_knowledge）
        vector_size: 向量维度（默认读 KB_VECTOR_SIZE，fallback 384）

    Returns:
        已初始化的后端实例（_LocalKeywordBackend / _ChromaBackend / _QdrantBackend）
    """
    _backend = (backend or os.environ.get("KB_VECTOR_BACKEND", "local")).strip().lower()
    _qdrant_url = qdrant_url or os.environ.get("QDRANT_URL", "")
    _chroma_dir = chroma_persist_dir or os.environ.get("CHROMA_PERSIST_DIR", "./chroma_db")
    _collection = collection_name or os.environ.get("KB_COLLECTION", "ufo_galaxy_knowledge")
    _vsize = int(vector_size or os.environ.get("KB_VECTOR_SIZE", "384"))

    if _backend == "chroma":
        inst = _ChromaBackend(_chroma_dir, _collection, _vsize)
        if inst._try_init():
            return inst
        logger.info("ChromaDB 不可用，降级为 local 后端")
        return _LocalKeywordBackend()

    if _backend == "qdrant":
        inst = _QdrantBackend(_qdrant_url, _collection, _vsize)
        if inst._try_init():
            return inst
        logger.info("Qdrant 不可用，降级为 local 后端")
        return _LocalKeywordBackend()

    # local（默认）
    return _LocalKeywordBackend()


# ---------------------------------------------------------------------------
# 模块级单例（惰性初始化，供各节点直接 import 使用）
# ---------------------------------------------------------------------------

_shared_backend = None


def get_shared_backend():
    """获取模块级共享向量后端（惰性初始化）"""
    global _shared_backend
    if _shared_backend is None:
        _shared_backend = create_vector_backend()
    return _shared_backend
