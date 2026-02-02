"""
Node 80: Memory System
多层记忆系统 - 短期/长期/语义/用户画像

功能：
1. 短期记忆（Redis）- 对话上下文，1小时过期
2. 长期记忆（Memos）- 笔记和文档，持久化存储
3. 语义记忆（ChromaDB）- 向量存储，语义搜索
4. 用户画像（SQLite）- 偏好设置，使用统计

优势：
- 个性化体验
- 上下文连续性
- 知识积累
- 智能推荐

集成：
- 与 Node 79 (Local LLM) 配合实现带记忆的对话
- 与 Node 81 (Orchestrator) 配合实现工作流记忆
"""

import os
import json
import sqlite3
import hashlib
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from enum import Enum

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn
import httpx
import redis.asyncio as redis

# =============================================================================
# Configuration
# =============================================================================

NODE_ID = os.getenv("NODE_ID", "80")
NODE_NAME = os.getenv("NODE_NAME", "MemorySystem")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Redis 配置（短期记忆）
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
REDIS_PREFIX = os.getenv("REDIS_PREFIX", "ufo_galaxy:")
SHORT_TERM_TTL = int(os.getenv("SHORT_TERM_TTL", "3600"))  # 1 小时

# Memos 配置（长期记忆）
MEMOS_URL = os.getenv("MEMOS_URL", "http://localhost:5230")
MEMOS_TOKEN = os.getenv("MEMOS_TOKEN", "")

# ChromaDB 配置（语义记忆）
CHROMA_PATH = os.getenv("CHROMA_PATH", "./chroma_db")
CHROMA_COLLECTION = os.getenv("CHROMA_COLLECTION", "ufo_galaxy_memory")

# SQLite 配置（用户画像）
SQLITE_PATH = os.getenv("SQLITE_PATH", "./user_profile.db")

# 离线模式
OFFLINE_MODE = os.getenv("OFFLINE_MODE", "false").lower() == "true"

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format=f"[Node {NODE_ID}] %(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# =============================================================================
# Models
# =============================================================================

class MemoryType(str, Enum):
    SHORT_TERM = "short_term"  # 短期记忆（Redis）
    LONG_TERM = "long_term"    # 长期记忆（Memos）
    SEMANTIC = "semantic"      # 语义记忆（ChromaDB）
    PROFILE = "profile"        # 用户画像（SQLite）

class SaveMemoryRequest(BaseModel):
    content: str
    memory_type: MemoryType
    tags: Optional[List[str]] = []
    metadata: Optional[Dict[str, Any]] = {}
    session_id: Optional[str] = None  # 用于短期记忆
    user_id: Optional[str] = "default"

class RecallRequest(BaseModel):
    query: str
    memory_type: Optional[MemoryType] = None  # None = 搜索所有类型
    limit: int = Field(default=5, ge=1, le=50)
    session_id: Optional[str] = None
    user_id: Optional[str] = "default"

class Memory(BaseModel):
    id: str
    content: str
    memory_type: MemoryType
    tags: List[str]
    metadata: Dict[str, Any]
    created_at: str
    relevance_score: Optional[float] = None

class ConversationMessage(BaseModel):
    role: str  # user, assistant
    content: str
    timestamp: Optional[str] = None

class SaveConversationRequest(BaseModel):
    session_id: str
    messages: List[ConversationMessage]
    user_id: Optional[str] = "default"

class UserPreference(BaseModel):
    key: str
    value: Any
    user_id: Optional[str] = "default"

# =============================================================================
# Short-Term Memory (Redis)
# =============================================================================

class ShortTermMemory:
    """短期记忆 - Redis"""
    
    def __init__(self, redis_url: str, prefix: str, ttl: int):
        self.redis_url = redis_url
        self.prefix = prefix
        self.ttl = ttl
        self.client: Optional[redis.Redis] = None
    
    async def connect(self):
        """连接 Redis"""
        try:
            self.client = await redis.from_url(self.redis_url, decode_responses=True)
            await self.client.ping()
            logger.info("Connected to Redis")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            if not OFFLINE_MODE:
                raise
    
    async def save(self, session_id: str, content: str, metadata: Dict = None) -> str:
        """保存短期记忆"""
        if not self.client:
            raise HTTPException(status_code=503, detail="Redis not available")
        
        key = f"{self.prefix}session:{session_id}"
        memory_id = hashlib.md5(f"{session_id}:{datetime.now().isoformat()}".encode()).hexdigest()
        
        memory_data = {
            "id": memory_id,
            "content": content,
            "metadata": metadata or {},
            "created_at": datetime.now().isoformat()
        }
        
        # 添加到列表
        await self.client.rpush(key, json.dumps(memory_data))
        
        # 设置过期时间
        await self.client.expire(key, self.ttl)
        
        logger.info(f"Saved short-term memory: {memory_id}")
        return memory_id
    
    async def recall(self, session_id: str, limit: int = 10) -> List[Memory]:
        """回忆短期记忆"""
        if not self.client:
            return []
        
        key = f"{self.prefix}session:{session_id}"
        
        # 获取最近的 N 条记忆
        memories_json = await self.client.lrange(key, -limit, -1)
        
        memories = []
        for mem_json in memories_json:
            mem_data = json.loads(mem_json)
            memories.append(Memory(
                id=mem_data["id"],
                content=mem_data["content"],
                memory_type=MemoryType.SHORT_TERM,
                tags=[],
                metadata=mem_data["metadata"],
                created_at=mem_data["created_at"]
            ))
        
        return memories
    
    async def save_conversation(self, session_id: str, messages: List[ConversationMessage]) -> bool:
        """保存对话历史"""
        if not self.client:
            return False
        
        key = f"{self.prefix}conversation:{session_id}"
        
        for msg in messages:
            msg_data = {
                "role": msg.role,
                "content": msg.content,
                "timestamp": msg.timestamp or datetime.now().isoformat()
            }
            await self.client.rpush(key, json.dumps(msg_data))
        
        # 设置过期时间
        await self.client.expire(key, self.ttl)
        
        logger.info(f"Saved conversation: {session_id}")
        return True
    
    async def get_conversation(self, session_id: str, limit: int = 20) -> List[ConversationMessage]:
        """获取对话历史"""
        if not self.client:
            return []
        
        key = f"{self.prefix}conversation:{session_id}"
        
        # 获取最近的 N 条消息
        messages_json = await self.client.lrange(key, -limit, -1)
        
        messages = []
        for msg_json in messages_json:
            msg_data = json.loads(msg_json)
            messages.append(ConversationMessage(
                role=msg_data["role"],
                content=msg_data["content"],
                timestamp=msg_data.get("timestamp")
            ))
        
        return messages
    
    async def clear_session(self, session_id: str) -> bool:
        """清除会话记忆"""
        if not self.client:
            return False
        
        keys = [
            f"{self.prefix}session:{session_id}",
            f"{self.prefix}conversation:{session_id}"
        ]
        
        for key in keys:
            await self.client.delete(key)
        
        logger.info(f"Cleared session: {session_id}")
        return True
    
    async def close(self):
        """关闭连接"""
        if self.client:
            await self.client.close()

# =============================================================================
# Long-Term Memory (Memos)
# =============================================================================

class LongTermMemory:
    """长期记忆 - Memos"""
    
    def __init__(self, memos_url: str, token: str):
        self.memos_url = memos_url.rstrip("/")
        self.token = token
        self.http_client = httpx.AsyncClient(timeout=30)
    
    async def health_check(self) -> bool:
        """健康检查"""
        try:
            response = await self.http_client.get(f"{self.memos_url}/api/v1/ping")
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Memos health check failed: {e}")
            return False
    
    async def save(self, content: str, tags: List[str] = None, metadata: Dict = None) -> str:
        """保存长期记忆"""
        try:
            # 构建 Memos 格式的内容
            memo_content = content
            
            if tags:
                # 添加标签
                tag_str = " ".join([f"#{tag}" for tag in tags])
                memo_content = f"{content}\n\n{tag_str}"
            
            if metadata:
                # 添加元数据（作为 JSON）
                metadata_str = f"\n\n```json\n{json.dumps(metadata, indent=2)}\n```"
                memo_content += metadata_str
            
            # 调用 Memos API
            headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
            
            response = await self.http_client.post(
                f"{self.memos_url}/api/v1/memos",
                json={"content": memo_content},
                headers=headers
            )
            
            if response.status_code in [200, 201]:
                data = response.json()
                memory_id = str(data.get("id", ""))
                logger.info(f"Saved long-term memory: {memory_id}")
                return memory_id
            else:
                logger.error(f"Failed to save to Memos: {response.status_code}")
                raise HTTPException(status_code=response.status_code, detail="Failed to save to Memos")
        except Exception as e:
            logger.error(f"Error saving to Memos: {e}")
            if not OFFLINE_MODE:
                raise
            return ""
    
    async def recall(self, query: str, limit: int = 5) -> List[Memory]:
        """回忆长期记忆"""
        try:
            headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
            
            # 搜索 Memos
            response = await self.http_client.get(
                f"{self.memos_url}/api/v1/memos",
                params={"limit": limit * 2},  # 多获取一些，然后过滤
                headers=headers
            )
            
            if response.status_code == 200:
                data = response.json()
                memos = data.get("memos", [])
                
                # 简单的关键词匹配
                query_lower = query.lower()
                matched_memories = []
                
                for memo in memos:
                    content = memo.get("content", "")
                    if query_lower in content.lower():
                        # 提取标签
                        tags = [tag.strip("#") for tag in content.split() if tag.startswith("#")]
                        
                        matched_memories.append(Memory(
                            id=str(memo.get("id", "")),
                            content=content,
                            memory_type=MemoryType.LONG_TERM,
                            tags=tags,
                            metadata={},
                            created_at=memo.get("createdTs", "")
                        ))
                
                return matched_memories[:limit]
            else:
                logger.error(f"Failed to recall from Memos: {response.status_code}")
                return []
        except Exception as e:
            logger.error(f"Error recalling from Memos: {e}")
            return []
    
    async def close(self):
        """关闭客户端"""
        await self.http_client.aclose()

# =============================================================================
# Semantic Memory (ChromaDB) - 简化版
# =============================================================================

class SemanticMemory:
    """语义记忆 - ChromaDB (简化版，不依赖 chromadb 库)"""
    
    def __init__(self, chroma_path: str, collection_name: str):
        self.chroma_path = chroma_path
        self.collection_name = collection_name
        self.memories: Dict[str, Dict] = {}  # 简单的内存存储
    
    async def initialize(self):
        """初始化"""
        os.makedirs(self.chroma_path, exist_ok=True)
        logger.info("Initialized semantic memory (simplified)")
    
    async def save(self, content: str, metadata: Dict = None) -> str:
        """保存语义记忆"""
        memory_id = hashlib.md5(f"{content}:{datetime.now().isoformat()}".encode()).hexdigest()
        
        self.memories[memory_id] = {
            "content": content,
            "metadata": metadata or {},
            "created_at": datetime.now().isoformat()
        }
        
        logger.info(f"Saved semantic memory: {memory_id}")
        return memory_id
    
    async def recall(self, query: str, limit: int = 5) -> List[Memory]:
        """回忆语义记忆（简单关键词匹配）"""
        query_lower = query.lower()
        matched = []
        
        for mem_id, mem_data in self.memories.items():
            if query_lower in mem_data["content"].lower():
                matched.append(Memory(
                    id=mem_id,
                    content=mem_data["content"],
                    memory_type=MemoryType.SEMANTIC,
                    tags=[],
                    metadata=mem_data["metadata"],
                    created_at=mem_data["created_at"],
                    relevance_score=0.8
                ))
        
        return matched[:limit]
    
    async def close(self):
        """关闭"""
        pass

# =============================================================================
# User Profile (SQLite)
# =============================================================================

class UserProfile:
    """用户画像 - SQLite"""
    
    def __init__(self, sqlite_path: str):
        self.sqlite_path = sqlite_path
        self.conn: Optional[sqlite3.Connection] = None
    
    async def initialize(self):
        """初始化数据库"""
        self.conn = sqlite3.connect(self.sqlite_path)
        self.conn.row_factory = sqlite3.Row
        
        # 创建表
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS user_preferences (
                user_id TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (user_id, key)
            )
        """)
        
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS user_stats (
                user_id TEXT PRIMARY KEY,
                total_conversations INTEGER DEFAULT 0,
                total_messages INTEGER DEFAULT 0,
                total_memories INTEGER DEFAULT 0,
                last_active TEXT,
                created_at TEXT NOT NULL
            )
        """)
        
        self.conn.commit()
        logger.info("Initialized user profile database")
    
    async def set_preference(self, user_id: str, key: str, value: Any) -> bool:
        """设置用户偏好"""
        if not self.conn:
            return False
        
        value_json = json.dumps(value)
        
        self.conn.execute("""
            INSERT OR REPLACE INTO user_preferences (user_id, key, value, updated_at)
            VALUES (?, ?, ?, ?)
        """, (user_id, key, value_json, datetime.now().isoformat()))
        
        self.conn.commit()
        logger.info(f"Set preference for {user_id}: {key}")
        return True
    
    async def get_preference(self, user_id: str, key: str) -> Optional[Any]:
        """获取用户偏好"""
        if not self.conn:
            return None
        
        cursor = self.conn.execute("""
            SELECT value FROM user_preferences
            WHERE user_id = ? AND key = ?
        """, (user_id, key))
        
        row = cursor.fetchone()
        if row:
            return json.loads(row["value"])
        return None
    
    async def get_all_preferences(self, user_id: str) -> Dict[str, Any]:
        """获取所有用户偏好"""
        if not self.conn:
            return {}
        
        cursor = self.conn.execute("""
            SELECT key, value FROM user_preferences
            WHERE user_id = ?
        """, (user_id,))
        
        preferences = {}
        for row in cursor.fetchall():
            preferences[row["key"]] = json.loads(row["value"])
        
        return preferences
    
    async def update_stats(self, user_id: str, conversations: int = 0, messages: int = 0, memories: int = 0):
        """更新用户统计"""
        if not self.conn:
            return
        
        # 确保用户存在
        self.conn.execute("""
            INSERT OR IGNORE INTO user_stats (user_id, created_at)
            VALUES (?, ?)
        """, (user_id, datetime.now().isoformat()))
        
        # 更新统计
        self.conn.execute("""
            UPDATE user_stats
            SET total_conversations = total_conversations + ?,
                total_messages = total_messages + ?,
                total_memories = total_memories + ?,
                last_active = ?
            WHERE user_id = ?
        """, (conversations, messages, memories, datetime.now().isoformat(), user_id))
        
        self.conn.commit()
    
    async def get_stats(self, user_id: str) -> Dict[str, Any]:
        """获取用户统计"""
        if not self.conn:
            return {}
        
        cursor = self.conn.execute("""
            SELECT * FROM user_stats WHERE user_id = ?
        """, (user_id,))
        
        row = cursor.fetchone()
        if row:
            return dict(row)
        return {}
    
    async def close(self):
        """关闭连接"""
        if self.conn:
            self.conn.close()

# =============================================================================
# Memory System Service
# =============================================================================

class MemorySystemService:
    """记忆系统服务"""
    
    def __init__(self):
        self.short_term = ShortTermMemory(REDIS_URL, REDIS_PREFIX, SHORT_TERM_TTL)
        self.long_term = LongTermMemory(MEMOS_URL, MEMOS_TOKEN)
        self.semantic = SemanticMemory(CHROMA_PATH, CHROMA_COLLECTION)
        self.profile = UserProfile(SQLITE_PATH)
    
    async def initialize(self):
        """初始化所有存储"""
        await self.short_term.connect()
        await self.semantic.initialize()
        await self.profile.initialize()
    
    async def save(self, request: SaveMemoryRequest) -> str:
        """保存记忆"""
        if request.memory_type == MemoryType.SHORT_TERM:
            if not request.session_id:
                raise HTTPException(status_code=400, detail="session_id required for short-term memory")
            memory_id = await self.short_term.save(request.session_id, request.content, request.metadata)
        
        elif request.memory_type == MemoryType.LONG_TERM:
            memory_id = await self.long_term.save(request.content, request.tags, request.metadata)
        
        elif request.memory_type == MemoryType.SEMANTIC:
            memory_id = await self.semantic.save(request.content, request.metadata)
        
        else:
            raise HTTPException(status_code=400, detail="Invalid memory type")
        
        # 更新用户统计
        await self.profile.update_stats(request.user_id, memories=1)
        
        return memory_id
    
    async def recall(self, request: RecallRequest) -> List[Memory]:
        """回忆记忆"""
        all_memories = []
        
        # 根据类型搜索
        if request.memory_type is None or request.memory_type == MemoryType.SHORT_TERM:
            if request.session_id:
                short_memories = await self.short_term.recall(request.session_id, request.limit)
                all_memories.extend(short_memories)
        
        if request.memory_type is None or request.memory_type == MemoryType.LONG_TERM:
            long_memories = await self.long_term.recall(request.query, request.limit)
            all_memories.extend(long_memories)
        
        if request.memory_type is None or request.memory_type == MemoryType.SEMANTIC:
            semantic_memories = await self.semantic.recall(request.query, request.limit)
            all_memories.extend(semantic_memories)
        
        # 按相关性排序（如果有）
        all_memories.sort(key=lambda m: m.relevance_score or 0, reverse=True)
        
        return all_memories[:request.limit]
    
    async def save_conversation(self, request: SaveConversationRequest) -> bool:
        """保存对话"""
        success = await self.short_term.save_conversation(request.session_id, request.messages)
        
        if success:
            await self.profile.update_stats(request.user_id, conversations=1, messages=len(request.messages))
        
        return success
    
    async def get_conversation(self, session_id: str, limit: int = 20) -> List[ConversationMessage]:
        """获取对话历史"""
        return await self.short_term.get_conversation(session_id, limit)
    
    async def set_preference(self, preference: UserPreference) -> bool:
        """设置用户偏好"""
        return await self.profile.set_preference(preference.user_id, preference.key, preference.value)
    
    async def get_preference(self, user_id: str, key: str) -> Optional[Any]:
        """获取用户偏好"""
        return await self.profile.get_preference(user_id, key)
    
    async def get_all_preferences(self, user_id: str) -> Dict[str, Any]:
        """获取所有用户偏好"""
        return await self.profile.get_all_preferences(user_id)
    
    async def get_stats(self, user_id: str) -> Dict[str, Any]:
        """获取用户统计"""
        return await self.profile.get_stats(user_id)
    
    async def close(self):
        """关闭所有连接"""
        await self.short_term.close()
        await self.long_term.close()
        await self.semantic.close()
        await self.profile.close()

# =============================================================================
# FastAPI Application
# =============================================================================

memory_service = MemorySystemService()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    logger.info("Starting Node 80: Memory System")
    
    # 初始化所有存储
    await memory_service.initialize()
    
    yield
    
    # 清理资源
    await memory_service.close()
    logger.info("Node 80 shutdown complete")

app = FastAPI(
    title="Node 80: Memory System",
    description="多层记忆系统 - 短期/长期/语义/用户画像",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# API Endpoints
# =============================================================================

@app.get("/")
async def root():
    return {
        "service": "Node 80: Memory System",
        "status": "running",
        "memory_types": [t.value for t in MemoryType],
        "redis_url": REDIS_URL,
        "memos_url": MEMOS_URL,
        "chroma_path": CHROMA_PATH,
        "offline_mode": OFFLINE_MODE
    }

@app.get("/health")
async def health():
    memos_healthy = await memory_service.long_term.health_check()
    
    return {
        "status": "healthy",
        "redis_available": memory_service.short_term.client is not None,
        "memos_available": memos_healthy,
        "chroma_available": True,  # 简化版总是可用
        "sqlite_available": memory_service.profile.conn is not None,
        "timestamp": datetime.now().isoformat()
    }

@app.post("/memory")
async def save_memory(request: SaveMemoryRequest):
    """保存记忆"""
    memory_id = await memory_service.save(request)
    return {
        "success": True,
        "memory_id": memory_id,
        "memory_type": request.memory_type
    }

@app.post("/memory/recall")
async def recall_memory(request: RecallRequest):
    """回忆记忆"""
    memories = await memory_service.recall(request)
    return {
        "memories": [m.dict() for m in memories],
        "count": len(memories)
    }

@app.post("/conversation")
async def save_conversation(request: SaveConversationRequest):
    """保存对话"""
    success = await memory_service.save_conversation(request)
    return {"success": success}

@app.get("/conversation/{session_id}")
async def get_conversation(session_id: str, limit: int = Query(default=20, ge=1, le=100)):
    """获取对话历史"""
    messages = await memory_service.get_conversation(session_id, limit)
    return {
        "session_id": session_id,
        "messages": [m.dict() for m in messages],
        "count": len(messages)
    }

@app.post("/preference")
async def set_preference(preference: UserPreference):
    """设置用户偏好"""
    success = await memory_service.set_preference(preference)
    return {"success": success}

@app.get("/preference/{user_id}/{key}")
async def get_preference(user_id: str, key: str):
    """获取用户偏好"""
    value = await memory_service.get_preference(user_id, key)
    return {
        "user_id": user_id,
        "key": key,
        "value": value
    }

@app.get("/preference/{user_id}")
async def get_all_preferences(user_id: str):
    """获取所有用户偏好"""
    preferences = await memory_service.get_all_preferences(user_id)
    return {
        "user_id": user_id,
        "preferences": preferences
    }

@app.get("/stats/{user_id}")
async def get_stats(user_id: str):
    """获取用户统计"""
    stats = await memory_service.get_stats(user_id)
    return {
        "user_id": user_id,
        "stats": stats
    }

@app.delete("/session/{session_id}")
async def clear_session(session_id: str):
    """清除会话记忆"""
    success = await memory_service.short_term.clear_session(session_id)
    return {"success": success}

# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)


# =============================================================================
# Academic Extension API Endpoints
# =============================================================================

from academic_extension import academic_manager, PaperNote, CitationNetwork

@app.post("/academic/paper_note")
async def save_academic_paper_note(paper: PaperNote):
    """保存论文笔记"""
    success = await academic_manager.save_paper_note(paper)
    return {
        "success": success,
        "paper_id": paper.paper_id,
        "title": paper.title
    }

@app.get("/academic/paper_notes")
async def search_academic_paper_notes(
    query: str = Query(default="", description="搜索关键词"),
    tags: Optional[str] = Query(default=None, description="标签（逗号分隔）")
):
    """搜索论文笔记"""
    tag_list = tags.split(",") if tags else None
    memos = await academic_manager.search_paper_notes(query, tag_list)
    return {
        "query": query,
        "tags": tag_list,
        "count": len(memos),
        "papers": memos
    }

@app.get("/academic/citation_network/{paper_id}")
async def get_academic_citation_network(paper_id: str):
    """获取论文引用网络"""
    network = await academic_manager.get_citation_network(paper_id)
    return network.dict()

@app.get("/academic/papers_by_tag/{tag}")
async def get_academic_papers_by_tag(tag: str):
    """根据标签获取论文"""
    papers = await academic_manager.get_papers_by_tag(tag)
    return {
        "tag": tag,
        "count": len(papers),
        "papers": papers
    }

@app.get("/academic/recent_papers")
async def get_academic_recent_papers(days: int = Query(default=7, ge=1, le=30)):
    """获取最近的论文笔记"""
    papers = await academic_manager.get_recent_papers(days)
    return {
        "days": days,
        "count": len(papers),
        "papers": papers
    }

@app.post("/academic/export_bibtex")
async def export_academic_bibtex(paper_ids: List[str]):
    """导出论文为 BibTeX 格式"""
    bibtex = await academic_manager.export_papers_to_bibtex(paper_ids)
    return {
        "count": len(paper_ids),
        "bibtex": bibtex
    }
