"""
UFO Galaxy 知识库系统 - 增强节点 Node 52 (enhancements)

此模块是 nodes/Node_72_KnowledgeBase/knowledge_base_system.py 的轻量代理。
所有功能委托给 Node_72 实现，保持接口完全兼容。

向量后端配置（环境变量，与 Node_72 共享）：
  KB_VECTOR_BACKEND   chroma | qdrant | local（默认 local）
  QDRANT_URL          Qdrant 服务器地址
  CHROMA_PERSIST_DIR  ChromaDB 持久化目录（默认 ./chroma_db）
"""

# 重新导出 Node_72 的完整实现（保持向后兼容接口）
try:
    from nodes.Node_72_KnowledgeBase.knowledge_base_system import (  # noqa: F401
        KnowledgeEntry,
        KnowledgeBaseSystem,
    )
except ImportError:
    # 若 Node_72 不在 path 中，退到本地备用实现
    import json
    import logging
    import time
    import hashlib
    from typing import List, Dict, Any, Optional
    from dataclasses import dataclass

    logger = logging.getLogger("UFO-Galaxy.Node52KB")

    @dataclass
    class KnowledgeEntry:  # type: ignore[no-redef]
        id: str
        content: str
        metadata: Dict[str, Any]
        embedding: Optional[List[float]] = None
        timestamp: float = 0.0

    class KnowledgeBaseSystem:  # type: ignore[no-redef]
        """备用知识库系统（Node_72 不可达时使用）"""

        def __init__(self, persist_directory: str = "./knowledge_db"):
            self.persist_directory = persist_directory
            self.knowledge_entries: Dict[str, KnowledgeEntry] = {}
            self._backend = None
            try:
                from core.vector_backend import get_shared_backend
                self._backend = get_shared_backend()
            except Exception as exc:
                logger.warning(f"vector_backend 不可用: {exc}")
            logger.info(f"知识库系统（备用）初始化，目录: {persist_directory}")

        def add_knowledge(self, content: str, metadata: Dict[str, Any] = None) -> str:
            entry_id = hashlib.sha256(content.encode()).hexdigest()
            self.knowledge_entries[entry_id] = KnowledgeEntry(
                id=entry_id, content=content, metadata=metadata or {}, timestamp=time.time()
            )
            if self._backend:
                try:
                    self._backend.add_document(entry_id, content, metadata)
                except Exception:
                    pass
            return entry_id

        def search(self, query: str, top_k: int = 5) -> List[KnowledgeEntry]:
            if self._backend:
                try:
                    results = self._backend.search(query, top_k)
                    out = []
                    for r in results:
                        if r.doc_id in self.knowledge_entries:
                            out.append(self.knowledge_entries[r.doc_id])
                        else:
                            out.append(KnowledgeEntry(id=r.doc_id, content=r.content, metadata=r.metadata))
                    return out
                except Exception:
                    pass
            ql = query.lower()
            return [e for e in self.knowledge_entries.values() if ql in e.content.lower()][:top_k]

        def rag_query(self, query: str, context_size: int = 3) -> Dict[str, Any]:
            relevant = self.search(query, top_k=context_size)
            return {
                "query": query,
                "relevant_knowledge": [
                    {"content": e.content, "metadata": e.metadata, "timestamp": e.timestamp}
                    for e in relevant
                ],
                "context": "\n\n".join(e.content for e in relevant),
                "answer": f"基于知识库检索到 {len(relevant)} 条相关知识。",
            }

        def update_knowledge(self, entry_id: str, new_content: str) -> bool:
            if entry_id not in self.knowledge_entries:
                return False
            self.knowledge_entries[entry_id].content = new_content
            self.knowledge_entries[entry_id].timestamp = time.time()
            if self._backend:
                try:
                    self._backend.add_document(entry_id, new_content)
                except Exception:
                    pass
            return True

        def delete_knowledge(self, entry_id: str) -> bool:
            if entry_id not in self.knowledge_entries:
                return False
            del self.knowledge_entries[entry_id]
            if self._backend:
                try:
                    self._backend.delete_document(entry_id)
                except Exception:
                    pass
            return True

        def get_statistics(self) -> Dict[str, Any]:
            return {
                "total_entries": len(self.knowledge_entries),
                "vector_backend": getattr(self._backend, "name", "local"),
                "is_vector_mode": getattr(self._backend, "is_vector_mode", False),
                "categories": {},
                "last_updated": 0,
            }
