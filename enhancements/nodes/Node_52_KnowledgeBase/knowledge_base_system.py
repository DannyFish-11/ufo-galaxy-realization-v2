"""
UFO³ Galaxy 知识库系统 - Node 52

功能：
1. 向量数据库存储（使用 ChromaDB）
2. RAG（检索增强生成）
3. 知识检索和语义搜索
4. 知识更新和管理
5. 与 NLU 引擎集成

作者：Manus AI
日期：2025-01-20
"""

import json
import time
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import hashlib

# 注意：实际部署时需要安装 chromadb 和 sentence-transformers
# pip install chromadb sentence-transformers

@dataclass
class KnowledgeEntry:
    """知识条目"""
    id: str
    content: str
    metadata: Dict[str, Any]
    embedding: Optional[List[float]] = None
    timestamp: float = 0.0

class KnowledgeBaseSystem:
    """知识库系统"""
    
    def __init__(self, persist_directory: str = "./knowledge_db"):
        """
        初始化知识库
        
        Args:
            persist_directory: 持久化目录
        """
        self.persist_directory = persist_directory
        self.knowledge_entries: Dict[str, KnowledgeEntry] = {}
        
        # 在实际部署时，这里会初始化 ChromaDB
        # self.chroma_client = chromadb.Client(Settings(
        #     chroma_db_impl="duckdb+parquet",
        #     persist_directory=persist_directory
        # ))
        # self.collection = self.chroma_client.create_collection("ufo_galaxy_knowledge")
        
        print(f"知识库系统已初始化，持久化目录: {persist_directory}")
    
    def add_knowledge(self, content: str, metadata: Dict[str, Any] = None) -> str:
        """
        添加知识到知识库
        
        Args:
            content: 知识内容
            metadata: 元数据（来源、类型、标签等）
        
        Returns:
            知识条目 ID
        """
        # 生成唯一 ID
        entry_id = hashlib.md5(content.encode()).hexdigest()
        
        # 创建知识条目
        entry = KnowledgeEntry(
            id=entry_id,
            content=content,
            metadata=metadata or {},
            timestamp=time.time()
        )
        
        # 存储到内存（实际部署时会存储到 ChromaDB）
        self.knowledge_entries[entry_id] = entry
        
        print(f"✅ 已添加知识: {content[:50]}...")
        
        return entry_id
    
    def search(self, query: str, top_k: int = 5) -> List[KnowledgeEntry]:
        """
        搜索相关知识
        
        Args:
            query: 查询文本
            top_k: 返回前 k 个结果
        
        Returns:
            相关知识列表
        """
        # 简化版：基于关键词匹配
        # 实际部署时会使用向量相似度搜索
        
        results = []
        query_lower = query.lower()
        
        for entry in self.knowledge_entries.values():
            if query_lower in entry.content.lower():
                results.append(entry)
        
        # 返回前 k 个结果
        return results[:top_k]
    
    def rag_query(self, query: str, context_size: int = 3) -> Dict[str, Any]:
        """
        RAG 查询（检索增强生成）
        
        Args:
            query: 用户查询
            context_size: 上下文大小
        
        Returns:
            包含检索结果和生成答案的字典
        """
        # 检索相关知识
        relevant_knowledge = self.search(query, top_k=context_size)
        
        # 构建上下文
        context = "\n\n".join([entry.content for entry in relevant_knowledge])
        
        # 在实际部署时，这里会调用 LLM 生成答案
        # 现在返回检索结果
        return {
            "query": query,
            "relevant_knowledge": [
                {
                    "content": entry.content,
                    "metadata": entry.metadata,
                    "timestamp": entry.timestamp
                }
                for entry in relevant_knowledge
            ],
            "context": context,
            "answer": f"基于知识库检索到 {len(relevant_knowledge)} 条相关知识。"
        }
    
    def update_knowledge(self, entry_id: str, new_content: str) -> bool:
        """
        更新知识条目
        
        Args:
            entry_id: 条目 ID
            new_content: 新内容
        
        Returns:
            是否成功
        """
        if entry_id in self.knowledge_entries:
            self.knowledge_entries[entry_id].content = new_content
            self.knowledge_entries[entry_id].timestamp = time.time()
            print(f"✅ 已更新知识: {entry_id}")
            return True
        else:
            print(f"❌ 未找到知识: {entry_id}")
            return False
    
    def delete_knowledge(self, entry_id: str) -> bool:
        """
        删除知识条目
        
        Args:
            entry_id: 条目 ID
        
        Returns:
            是否成功
        """
        if entry_id in self.knowledge_entries:
            del self.knowledge_entries[entry_id]
            print(f"✅ 已删除知识: {entry_id}")
            return True
        else:
            print(f"❌ 未找到知识: {entry_id}")
            return False
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取知识库统计信息"""
        return {
            "total_entries": len(self.knowledge_entries),
            "categories": self._get_categories(),
            "last_updated": max([e.timestamp for e in self.knowledge_entries.values()]) if self.knowledge_entries else 0
        }
    
    def _get_categories(self) -> Dict[str, int]:
        """获取知识分类统计"""
        categories = {}
        for entry in self.knowledge_entries.values():
            category = entry.metadata.get("category", "未分类")
            categories[category] = categories.get(category, 0) + 1
        return categories
    
    def export_knowledge(self, output_file: str):
        """导出知识库到文件"""
        data = {
            "entries": [
                {
                    "id": entry.id,
                    "content": entry.content,
                    "metadata": entry.metadata,
                    "timestamp": entry.timestamp
                }
                for entry in self.knowledge_entries.values()
            ]
        }
        
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        print(f"✅ 知识库已导出到: {output_file}")
    
    def import_knowledge(self, input_file: str):
        """从文件导入知识库"""
        with open(input_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        for entry_data in data.get("entries", []):
            entry = KnowledgeEntry(
                id=entry_data["id"],
                content=entry_data["content"],
                metadata=entry_data["metadata"],
                timestamp=entry_data["timestamp"]
            )
            self.knowledge_entries[entry.id] = entry
        
        print(f"✅ 已从 {input_file} 导入 {len(data.get('entries', []))} 条知识")

# 使用示例
if __name__ == "__main__":
    # 创建知识库
    kb = KnowledgeBaseSystem()
    
    # 添加知识
    kb.add_knowledge(
        "拓竹 3D 打印机的最佳打印温度是 220°C（PLA 材料）",
        metadata={"category": "3D打印", "source": "用户手册"}
    )
    
    kb.add_knowledge(
        "DJI 无人机在飞行前需要检查电池电量，确保至少有 30% 的电量",
        metadata={"category": "无人机", "source": "安全指南"}
    )
    
    kb.add_knowledge(
        "Node 50 NLU 引擎支持中文和英文的自然语言理解",
        metadata={"category": "系统", "source": "开发文档"}
    )
    
    # 搜索知识
    print("\n=== 搜索：打印机 ===")
    results = kb.search("打印机")
    for entry in results:
        print(f"- {entry.content}")
    
    # RAG 查询
    print("\n=== RAG 查询：无人机电量 ===")
    rag_result = kb.rag_query("无人机飞行前需要注意什么")
    print(json.dumps(rag_result, indent=2, ensure_ascii=False))
    
    # 统计信息
    print("\n=== 知识库统计 ===")
    stats = kb.get_statistics()
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    
    # 导出知识库
    kb.export_knowledge("/tmp/knowledge_export.json")
