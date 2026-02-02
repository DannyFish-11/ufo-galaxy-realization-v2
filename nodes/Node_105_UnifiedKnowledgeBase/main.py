"""
Node 105: Unified Knowledge Base
==================================
统一知识库管理系统

功能：
1. 统一数据源（本地文件、URL、GitHub、Memos）
2. 增强 RAG（多种 Embedding 模型和向量数据库）
3. 代码知识库（代码问答和语义搜索）
4. 混合搜索（关键词 + 向量）

作者：Manus AI
日期：2026-01-22
"""

import os
import json
import time
import hashlib
import asyncio
import httpx
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import subprocess

app = FastAPI(title="Node 105 - Unified Knowledge Base", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# ============================================================================
# 数据模型
# ============================================================================

@dataclass
class KnowledgeEntry:
    """知识条目"""
    id: str
    content: str
    source_type: str  # file, url, github, memos
    source: str
    metadata: Dict[str, Any]
    embedding: Optional[List[float]] = None
    timestamp: float = 0.0

class AddKnowledgeRequest(BaseModel):
    source_type: str  # file, url, github, memos
    source: str
    content: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class SearchRequest(BaseModel):
    query: str
    top_k: int = 5
    search_type: str = "hybrid"  # keyword, vector, hybrid

class AskRequest(BaseModel):
    question: str
    top_k: int = 3

# ============================================================================
# 统一知识库系统
# ============================================================================

class UnifiedKnowledgeBase:
    """统一知识库系统"""
    
    def __init__(self, persist_dir: str = "./unified_kb"):
        self.persist_dir = persist_dir
        self.knowledge_entries: Dict[str, KnowledgeEntry] = {}
        self.use_mock = True  # Mock 模式（无需安装向量数据库）
        
        os.makedirs(persist_dir, exist_ok=True)
        
        # 加载已有知识
        self._load_knowledge()
        
        print(f"✅ 统一知识库已初始化 (Mock 模式: {self.use_mock})")
    
    def _load_knowledge(self):
        """加载已有知识"""
        kb_file = os.path.join(self.persist_dir, "knowledge.json")
        if os.path.exists(kb_file):
            try:
                with open(kb_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for entry_dict in data:
                        entry = KnowledgeEntry(**entry_dict)
                        self.knowledge_entries[entry.id] = entry
                print(f"✅ 已加载 {len(self.knowledge_entries)} 条知识")
            except Exception as e:
                print(f"⚠️ 加载知识失败: {e}")
    
    def _save_knowledge(self):
        """保存知识到磁盘"""
        kb_file = os.path.join(self.persist_dir, "knowledge.json")
        try:
            data = [asdict(entry) for entry in self.knowledge_entries.values()]
            with open(kb_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ 保存知识失败: {e}")
    
    def _generate_id(self, content: str, source: str) -> str:
        """生成唯一 ID"""
        unique_str = f"{content[:100]}{source}{time.time()}"
        return hashlib.md5(unique_str.encode()).hexdigest()
    
    async def add_from_file(self, file_path: str, metadata: Dict[str, Any] = None) -> str:
        """从文件添加知识"""
        if not os.path.exists(file_path):
            raise ValueError(f"文件不存在: {file_path}")
        
        # 读取文件内容
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            raise ValueError(f"读取文件失败: {e}")
        
        # 创建知识条目
        entry_id = self._generate_id(content, file_path)
        entry = KnowledgeEntry(
            id=entry_id,
            content=content,
            source_type="file",
            source=file_path,
            metadata=metadata or {},
            timestamp=time.time()
        )
        
        self.knowledge_entries[entry_id] = entry
        self._save_knowledge()
        
        return entry_id
    
    async def add_from_url(self, url: str, metadata: Dict[str, Any] = None) -> str:
        """从 URL 添加知识"""
        # 抓取网页内容
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url)
                response.raise_for_status()
                content = response.text
        except Exception as e:
            raise ValueError(f"抓取网页失败: {e}")
        
        # 创建知识条目
        entry_id = self._generate_id(content, url)
        entry = KnowledgeEntry(
            id=entry_id,
            content=content,
            source_type="url",
            source=url,
            metadata=metadata or {},
            timestamp=time.time()
        )
        
        self.knowledge_entries[entry_id] = entry
        self._save_knowledge()
        
        return entry_id
    
    async def add_from_github(self, repo_url: str, metadata: Dict[str, Any] = None) -> str:
        """从 GitHub 仓库添加知识"""
        # 克隆仓库到临时目录
        repo_name = repo_url.split('/')[-1].replace('.git', '')
        clone_dir = os.path.join(self.persist_dir, "github_repos", repo_name)
        
        if not os.path.exists(clone_dir):
            try:
                result = subprocess.run(
                    ['git', 'clone', '--depth', '1', repo_url, clone_dir],
                    capture_output=True,
                    text=True,
                    timeout=300
                )
                if result.returncode != 0:
                    raise ValueError(f"克隆仓库失败: {result.stderr}")
            except Exception as e:
                raise ValueError(f"克隆仓库失败: {e}")
        
        # 遍历代码文件
        code_files = []
        for root, dirs, files in os.walk(clone_dir):
            # 跳过 .git 目录
            if '.git' in root:
                continue
            for file in files:
                if file.endswith(('.py', '.js', '.java', '.cpp', '.c', '.go', '.rs', '.md')):
                    file_path = os.path.join(root, file)
                    code_files.append(file_path)
        
        # 为每个代码文件创建知识条目
        entry_ids = []
        for file_path in code_files[:100]:  # 限制前 100 个文件
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                rel_path = os.path.relpath(file_path, clone_dir)
                entry_id = self._generate_id(content, f"{repo_url}/{rel_path}")
                entry = KnowledgeEntry(
                    id=entry_id,
                    content=content,
                    source_type="github",
                    source=f"{repo_url}/{rel_path}",
                    metadata={**(metadata or {}), "repo": repo_url, "file": rel_path},
                    timestamp=time.time()
                )
                
                self.knowledge_entries[entry_id] = entry
                entry_ids.append(entry_id)
            except Exception as e:
                print(f"⚠️ 读取文件失败 {file_path}: {e}")
        
        self._save_knowledge()
        
        return f"已添加 {len(entry_ids)} 个代码文件"
    
    async def add_from_memos(self, memos_url: str, tag: str = None, metadata: Dict[str, Any] = None) -> str:
        """从 Memos 添加知识"""
        # 调用 Memos API 获取笔记
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # 假设 Memos API 端点
                api_url = f"{memos_url}/api/v1/memos"
                if tag:
                    api_url += f"?tag={tag}"
                
                response = await client.get(api_url)
                response.raise_for_status()
                memos = response.json()
        except Exception as e:
            raise ValueError(f"获取 Memos 失败: {e}")
        
        # 为每个笔记创建知识条目
        entry_ids = []
        for memo in memos:
            content = memo.get('content', '')
            memo_id = memo.get('id', '')
            
            entry_id = self._generate_id(content, f"{memos_url}/memo/{memo_id}")
            entry = KnowledgeEntry(
                id=entry_id,
                content=content,
                source_type="memos",
                source=f"{memos_url}/memo/{memo_id}",
                metadata={**(metadata or {}), "memo_id": memo_id},
                timestamp=time.time()
            )
            
            self.knowledge_entries[entry_id] = entry
            entry_ids.append(entry_id)
        
        self._save_knowledge()
        
        return f"已添加 {len(entry_ids)} 条 Memos 笔记"
    
    def search_keyword(self, query: str, top_k: int = 5) -> List[KnowledgeEntry]:
        """关键词搜索"""
        query_lower = query.lower()
        results = []
        
        for entry in self.knowledge_entries.values():
            if query_lower in entry.content.lower():
                results.append(entry)
        
        # 按时间戳排序
        results.sort(key=lambda x: x.timestamp, reverse=True)
        
        return results[:top_k]
    
    def search_vector(self, query: str, top_k: int = 5) -> List[KnowledgeEntry]:
        """向量搜索（Mock 模式：退化为关键词搜索）"""
        # 在 Mock 模式下，向量搜索退化为关键词搜索
        if self.use_mock:
            return self.search_keyword(query, top_k)
        
        # 真实模式：使用向量数据库（Chroma）
        try:
            import chromadb
            from chromadb.utils import embedding_functions
            
            # 初始化 Chroma
            client = chromadb.PersistentClient(path=self.persist_dir)
            embedding_function = embedding_functions.DefaultEmbeddingFunction()
            collection = client.get_or_create_collection(
                name="unified_kb",
                embedding_function=embedding_function
            )
            
            # 搜索
            results = collection.query(
                query_texts=[query],
                n_results=top_k
            )
            
            # 转换为 KnowledgeEntry
            entries = []
            if results['ids'] and results['ids'][0]:
                for i, entry_id in enumerate(results['ids'][0]):
                    if entry_id in self.knowledge_entries:
                        entries.append(self.knowledge_entries[entry_id])
            
            return entries
        except ImportError:
            print("⚠️ Chroma 未安装，降级为关键词搜索")
            return self.search_keyword(query, top_k)
        except Exception as e:
            print(f"⚠️ 向量搜索失败: {e}，降级为关键词搜索")
            return self.search_keyword(query, top_k)
    
    def search_hybrid(self, query: str, top_k: int = 5) -> List[KnowledgeEntry]:
        """混合搜索"""
        # 简单实现：合并关键词和向量搜索结果
        keyword_results = self.search_keyword(query, top_k)
        vector_results = self.search_vector(query, top_k)
        
        # 去重
        seen_ids = set()
        results = []
        for entry in keyword_results + vector_results:
            if entry.id not in seen_ids:
                results.append(entry)
                seen_ids.add(entry.id)
        
        return results[:top_k]
    
    def ask(self, question: str, top_k: int = 3) -> Dict[str, Any]:
        """RAG 问答"""
        # 检索相关知识
        relevant_entries = self.search_hybrid(question, top_k)
        
        if not relevant_entries:
            return {
                "answer": "抱歉，我在知识库中没有找到相关信息。",
                "sources": []
            }
        
        # 构建上下文
        context = "\n\n".join([
            f"来源: {entry.source}\n内容: {entry.content[:500]}..."
            for entry in relevant_entries
        ])
        
        # Mock 模式：返回简单答案
        if self.use_mock:
            answer = f"根据知识库中的 {len(relevant_entries)} 条相关信息，我找到了以下内容：\n\n{context}"
        else:
            # 真实模式：调用 LLM 生成答案（通过 Node_50 或 Gemini）
            try:
                # 尝试调用 Gemini API
                import os
                gemini_key = os.getenv("GEMINI_API_KEY")
                if gemini_key:
                    from google import genai
                    client = genai.Client(api_key=gemini_key)
                    prompt = f"问题：{question}\n\n相关知识：\n{context}\n\n请根据上述知识回答问题。"
                    response = client.models.generate_content(
                        model="gemini-2.0-flash-exp",
                        contents=prompt
                    )
                    answer = response.text
                else:
                    answer = f"根据知识库中的 {len(relevant_entries)} 条相关信息：\n\n{context}\n\n（未配置 LLM，无法生成智能答案）"
            except Exception as e:
                answer = f"根据知识库中的 {len(relevant_entries)} 条相关信息：\n\n{context}\n\n（LLM 调用失败: {str(e)}）"
        
        return {
            "answer": answer,
            "sources": [entry.source for entry in relevant_entries]
        }

# ============================================================================
# 全局实例
# ============================================================================

kb = UnifiedKnowledgeBase()

# ============================================================================
# API 端点
# ============================================================================

@app.get("/health")
async def health():
    """健康检查"""
    return {
        "status": "healthy",
        "node_id": "105",
        "name": "Unified Knowledge Base",
        "knowledge_count": len(kb.knowledge_entries),
        "mock_mode": kb.use_mock
    }

@app.post("/add")
async def add_knowledge(request: AddKnowledgeRequest, background_tasks: BackgroundTasks):
    """添加知识"""
    try:
        if request.source_type == "file":
            entry_id = await kb.add_from_file(request.source, request.metadata)
            return {"success": True, "entry_id": entry_id}
        
        elif request.source_type == "url":
            entry_id = await kb.add_from_url(request.source, request.metadata)
            return {"success": True, "entry_id": entry_id}
        
        elif request.source_type == "github":
            # GitHub 仓库较大，放到后台任务
            background_tasks.add_task(kb.add_from_github, request.source, request.metadata)
            return {"success": True, "message": "GitHub 仓库正在后台处理"}
        
        elif request.source_type == "memos":
            entry_id = await kb.add_from_memos(request.source, metadata=request.metadata)
            return {"success": True, "message": entry_id}
        
        elif request.source_type == "text":
            # 直接添加文本
            if not request.content:
                raise HTTPException(status_code=400, detail="content 不能为空")
            
            entry_id = kb._generate_id(request.content, "text")
            entry = KnowledgeEntry(
                id=entry_id,
                content=request.content,
                source_type="text",
                source="direct_input",
                metadata=request.metadata or {},
                timestamp=time.time()
            )
            kb.knowledge_entries[entry_id] = entry
            kb._save_knowledge()
            
            return {"success": True, "entry_id": entry_id}
        
        else:
            raise HTTPException(status_code=400, detail=f"不支持的 source_type: {request.source_type}")
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/search")
async def search(request: SearchRequest):
    """搜索知识"""
    try:
        if request.search_type == "keyword":
            results = kb.search_keyword(request.query, request.top_k)
        elif request.search_type == "vector":
            results = kb.search_vector(request.query, request.top_k)
        elif request.search_type == "hybrid":
            results = kb.search_hybrid(request.query, request.top_k)
        else:
            raise HTTPException(status_code=400, detail=f"不支持的 search_type: {request.search_type}")
        
        return {
            "success": True,
            "count": len(results),
            "results": [
                {
                    "id": entry.id,
                    "content": entry.content[:200] + "..." if len(entry.content) > 200 else entry.content,
                    "source_type": entry.source_type,
                    "source": entry.source,
                    "metadata": entry.metadata,
                    "timestamp": entry.timestamp
                }
                for entry in results
            ]
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/ask")
async def ask(request: AskRequest):
    """RAG 问答"""
    try:
        result = kb.ask(request.question, request.top_k)
        return {"success": True, **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/stats")
async def stats():
    """统计信息"""
    source_types = {}
    for entry in kb.knowledge_entries.values():
        source_types[entry.source_type] = source_types.get(entry.source_type, 0) + 1
    
    return {
        "total_entries": len(kb.knowledge_entries),
        "source_types": source_types,
        "persist_dir": kb.persist_dir,
        "mock_mode": kb.use_mock
    }

@app.delete("/clear")
async def clear():
    """清空知识库"""
    kb.knowledge_entries.clear()
    kb._save_knowledge()
    return {"success": True, "message": "知识库已清空"}

# ============================================================================
# 启动服务
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8105)
