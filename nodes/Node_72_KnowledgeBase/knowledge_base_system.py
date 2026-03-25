"""
Galaxy 知识库系统 - Node 72 (兼容/回退后端)
=============================================

**架构地位: 兼容/轻量回退后端 (Fallback/Compatibility Backend)**

本模块是 Galaxy Knowledge Core 中的轻量兼容后端，提供简单的关键词+向量
知识存储能力。它不是主权威知识来源，而是作为以下情况的回退层：

1. Node_105_UnifiedKnowledgeBase 不可用时的降级后端
2. 轻量本地知识存储场景（无需多源索引的简单用例）
3. 历史遗留知识的兼容访问路径

**正确使用方式**: 上层组件（Agent、Planner、OpenClawd）不应直接调用本模块，
而应通过 `core.rag_memory.RAGMemory` 统一访问知识，由 RAGMemory 按优先级
路由至 Node_105（主后端）或本模块（回退后端）。

功能：
1. 向量数据库存储（通过 core.vector_backend 统一接口）
2. RAG（检索增强生成）
3. 知识检索和语义搜索（支持 ChromaDB / Qdrant / 本地关键词，自动降级）
4. 知识更新和管理
5. 与 NLU 引擎集成

向量后端配置（环境变量）：
  KB_VECTOR_BACKEND   chroma | qdrant | local（默认 local）
  QDRANT_URL          Qdrant 服务器地址
  CHROMA_PERSIST_DIR  ChromaDB 持久化目录（默认 ./chroma_db）
"""

import json
import logging
import os
import time
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import hashlib

logger = logging.getLogger("Galaxy.KnowledgeBase72")

# ============================================================================
# Knowledge Core 角色声明
# ============================================================================

# Node_72 是 Galaxy/OpenClawd Knowledge Core 的兼容/回退后端。
# 它不是主权威知识来源。主后端为 Node_105_UnifiedKnowledgeBase。
# 上层组件应通过 core.rag_memory.RAGMemory 访问知识，由 RAGMemory
# 按优先级路由（Node_105 优先，Node_72 作为回退）。
KNOWLEDGE_BACKEND_ROLE = "fallback"


@dataclass
class KnowledgeEntry:
    """知识条目"""
    id: str
    content: str
    metadata: Dict[str, Any]
    embedding: Optional[List[float]] = None
    timestamp: float = 0.0


def _get_backend():
    """惰性加载统一向量后端"""
    try:
        from core.vector_backend import get_shared_backend
        return get_shared_backend()
    except Exception as exc:
        logger.warning(f"vector_backend 不可用: {exc}，使用内存关键词搜索")
        return None


class KnowledgeBaseSystem:
    """知识库系统（Node 72）"""

    def __init__(self, persist_directory: str = "./knowledge_db"):
        self.persist_directory = persist_directory
        os.makedirs(persist_directory, exist_ok=True)
        self._persist_file = os.path.join(persist_directory, "knowledge_entries.json")
        # 内存索引（当向量后端不可用时使用）
        self.knowledge_entries: Dict[str, KnowledgeEntry] = {}
        self._backend = _get_backend()
        _mode = getattr(self._backend, "name", "local") if self._backend else "local"
        # 从磁盘恢复知识
        self._load_from_disk()
        logger.info(f"知识库系统已初始化，向量后端: {_mode}，持久化目录: {persist_directory}，"
                     f"已有条目: {len(self.knowledge_entries)}")

    def _load_from_disk(self):
        """从持久化文件恢复知识条目"""
        if not os.path.exists(self._persist_file):
            return
        try:
            with open(self._persist_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data.get("entries", []):
                entry = KnowledgeEntry(
                    id=item["id"],
                    content=item["content"],
                    metadata=item.get("metadata", {}),
                    timestamp=item.get("timestamp", 0.0),
                )
                self.knowledge_entries[entry.id] = entry
        except Exception as e:
            logger.warning(f"从磁盘恢复知识失败: {e}")

    def _save_to_disk(self):
        """将知识条目持久化到磁盘（JSON 格式）"""
        try:
            tmp_path = self._persist_file + ".tmp"
            data = {
                "entries": [
                    {
                        "id": e.id,
                        "content": e.content,
                        "metadata": {k: v for k, v in e.metadata.items() if not k.startswith("_")},
                        "timestamp": e.timestamp,
                    }
                    for e in self.knowledge_entries.values()
                ]
            }
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, self._persist_file)  # atomic on POSIX
        except Exception as e:
            logger.error(f"知识库持久化失败: {e}")

    def add_knowledge(self, content: str, metadata: Dict[str, Any] = None) -> str:
        """添加知识到知识库"""
        entry_id = hashlib.sha256(content.encode()).hexdigest()

        entry = KnowledgeEntry(
            id=entry_id,
            content=content,
            metadata=metadata or {},
            timestamp=time.time(),
        )
        self.knowledge_entries[entry_id] = entry

        # 写入向量后端
        if self._backend is not None:
            try:
                self._backend.add_document(entry_id, content, metadata)
            except Exception as exc:
                logger.warning(f"向量后端写入失败: {exc}")

        self._save_to_disk()
        return entry_id

    def search(self, query: str, top_k: int = 5) -> List[KnowledgeEntry]:
        """搜索相关知识（优先使用向量后端）

        返回的每个 KnowledgeEntry 的 metadata 中会包含 ``_search_mode`` 字段，
        值为 ``"vector"`` 或 ``"keyword"``，方便调用方判断搜索降级情况。
        """
        if self._backend is not None:
            try:
                results = self._backend.search(query, top_k)
                entries = []
                for r in results:
                    if r.doc_id in self.knowledge_entries:
                        entry = self.knowledge_entries[r.doc_id]
                        entry.metadata["_search_mode"] = "vector"
                        entries.append(entry)
                    else:
                        entries.append(KnowledgeEntry(
                            id=r.doc_id,
                            content=r.content,
                            metadata={**r.metadata, "_search_mode": "vector"},
                        ))
                return entries
            except Exception as exc:
                logger.warning(f"向量后端搜索失败: {exc}，降级为关键词搜索")

        # 降级：基于关键词匹配
        query_lower = query.lower()
        results = []
        for e in self.knowledge_entries.values():
            if query_lower in e.content.lower():
                e.metadata["_search_mode"] = "keyword"
                results.append(e)
        return results[:top_k]

    def rag_query(self, query: str, context_size: int = 3) -> Dict[str, Any]:
        """RAG 查询（检索增强生成）"""
        relevant_knowledge = self.search(query, top_k=context_size)
        context = "\n\n".join([entry.content for entry in relevant_knowledge])
        return {
            "query": query,
            "relevant_knowledge": [
                {"content": entry.content, "metadata": entry.metadata, "timestamp": entry.timestamp}
                for entry in relevant_knowledge
            ],
            "context": context,
            "answer": f"基于知识库检索到 {len(relevant_knowledge)} 条相关知识。",
        }

    def update_knowledge(self, entry_id: str, new_content: str) -> bool:
        """更新知识条目"""
        if entry_id not in self.knowledge_entries:
            return False
        entry = self.knowledge_entries[entry_id]
        entry.content = new_content
        entry.timestamp = time.time()
        if self._backend is not None:
            try:
                self._backend.add_document(entry_id, new_content, entry.metadata)
            except Exception as exc:
                logger.warning(f"向量后端更新失败: {exc}")
        self._save_to_disk()
        return True

    def delete_knowledge(self, entry_id: str) -> bool:
        """删除知识条目"""
        if entry_id not in self.knowledge_entries:
            return False
        del self.knowledge_entries[entry_id]
        if self._backend is not None:
            try:
                self._backend.delete_document(entry_id)
            except Exception as exc:
                logger.warning(f"向量后端删除失败: {exc}")
        self._save_to_disk()
        return True

    def get_statistics(self) -> Dict[str, Any]:
        """获取知识库统计信息"""
        _cnt = getattr(self._backend, "document_count", len(self.knowledge_entries))
        _mode = getattr(self._backend, "name", "local") if self._backend else "local"
        return {
            "total_entries": _cnt,
            "vector_backend": _mode,
            "is_vector_mode": getattr(self._backend, "is_vector_mode", False),
            "categories": self._get_categories(),
            "last_updated": max(
                (e.timestamp for e in self.knowledge_entries.values()), default=0
            ),
        }

    def _get_categories(self) -> Dict[str, int]:
        categories: Dict[str, int] = {}
        for entry in self.knowledge_entries.values():
            cat = entry.metadata.get("category", "未分类")
            categories[cat] = categories.get(cat, 0) + 1
        return categories

    def export_knowledge(self, output_file: str):
        """导出知识库到 JSON 文件"""
        data = {
            "entries": [
                {
                    "id": e.id,
                    "content": e.content,
                    "metadata": e.metadata,
                    "timestamp": e.timestamp,
                }
                for e in self.knowledge_entries.values()
            ]
        }
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def import_knowledge(self, input_file: str):
        """从 JSON 文件导入知识库"""
        with open(input_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        for entry_data in data.get("entries", []):
            entry = KnowledgeEntry(
                id=entry_data["id"],
                content=entry_data["content"],
                metadata=entry_data["metadata"],
                timestamp=entry_data["timestamp"],
            )
            self.knowledge_entries[entry.id] = entry
            if self._backend is not None:
                try:
                    self._backend.add_document(entry.id, entry.content, entry.metadata)
                except Exception as exc:
                    logger.warning(f"向量后端导入失败: {exc}")

