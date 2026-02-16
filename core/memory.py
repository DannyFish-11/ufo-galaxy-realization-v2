"""
Galaxy - 记忆系统
支持对话历史、用户偏好、上下文记忆的持久化存储
"""

import os
import json
import logging
import time
import hashlib
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("Galaxy.Memory")

# ============================================================================
# 配置
# ============================================================================

@dataclass
class MemoryConfig:
    """记忆配置"""
    # 存储路径
    storage_path: str = "data/memory"
    
    # 对话历史
    max_history_per_session: int = 100      # 每个会话最大历史数
    max_sessions: int = 10                   # 最大会话数
    
    # 长期记忆
    enable_long_term_memory: bool = True     # 启用长期记忆
    long_term_memory_file: str = "long_term_memory.json"
    
    # 用户偏好
    enable_user_preferences: bool = True     # 启用用户偏好
    user_preferences_file: str = "user_preferences.json"
    
    # 上下文
    context_expire_hours: int = 24           # 上下文过期时间（小时）

# ============================================================================
# 数据模型
# ============================================================================

@dataclass
class ConversationMessage:
    """对话消息"""
    role: str                    # user / assistant / system
    content: str                 # 内容
    timestamp: str               # 时间戳
    metadata: Dict[str, Any] = field(default_factory=dict)  # 元数据

@dataclass
class ConversationSession:
    """对话会话"""
    session_id: str
    user_id: str
    messages: List[ConversationMessage] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.updated_at:
            self.updated_at = datetime.now().isoformat()

@dataclass
class LongTermMemory:
    """长期记忆"""
    memory_id: str
    content: str                 # 记忆内容
    memory_type: str             # 类型: fact / preference / event / knowledge
    importance: float = 0.5      # 重要性 0-1
    access_count: int = 0        # 访问次数
    created_at: str = ""
    last_accessed: str = ""
    tags: List[str] = field(default_factory=list)
    embedding: List[float] = field(default_factory=list)  # 向量嵌入（可选）

@dataclass
class UserPreference:
    """用户偏好"""
    key: str                     # 偏好键
    value: Any                   # 偏好值
    category: str = "general"    # 类别
    updated_at: str = ""

# ============================================================================
# 记忆管理器
# ============================================================================

class MemoryManager:
    """记忆管理器"""
    
    def __init__(self, config: MemoryConfig = None):
        self.config = config or MemoryConfig()
        self.storage_path = Path(self.config.storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        # 内存缓存
        self.sessions: Dict[str, ConversationSession] = {}
        self.long_term_memories: Dict[str, LongTermMemory] = {}
        self.user_preferences: Dict[str, UserPreference] = {}
        
        # 加载持久化数据
        self._load_from_disk()
        
        logger.info(f"记忆系统初始化完成，存储路径: {self.storage_path}")
    
    # ========================================================================
    # 对话历史
    # ========================================================================
    
    def add_message(self, session_id: str, user_id: str, role: str, content: str, metadata: Dict = None):
        """添加消息到对话历史"""
        
        # 获取或创建会话
        session = self._get_or_create_session(session_id, user_id)
        
        # 创建消息
        message = ConversationMessage(
            role=role,
            content=content,
            timestamp=datetime.now().isoformat(),
            metadata=metadata or {}
        )
        
        # 添加到会话
        session.messages.append(message)
        session.updated_at = datetime.now().isoformat()
        
        # 限制历史数量
        if len(session.messages) > self.config.max_history_per_session:
            session.messages = session.messages[-self.config.max_history_per_session:]
        
        # 保存
        self._save_session(session)
        
        logger.debug(f"添加消息到会话 {session_id}: {role} - {content[:50]}...")
    
    def get_history(self, session_id: str, limit: int = 10) -> List[Dict]:
        """获取对话历史"""
        if session_id not in self.sessions:
            return []
        
        session = self.sessions[session_id]
        messages = session.messages[-limit:]
        
        return [asdict(msg) for msg in messages]
    
    def get_context(self, session_id: str) -> Dict[str, Any]:
        """获取会话上下文"""
        if session_id not in self.sessions:
            return {}
        
        return self.sessions[session_id].context
    
    def update_context(self, session_id: str, context: Dict[str, Any]):
        """更新会话上下文"""
        if session_id in self.sessions:
            self.sessions[session_id].context.update(context)
            self.sessions[session_id].updated_at = datetime.now().isoformat()
            self._save_session(self.sessions[session_id])
    
    def _get_or_create_session(self, session_id: str, user_id: str) -> ConversationSession:
        """获取或创建会话"""
        if session_id not in self.sessions:
            session = ConversationSession(
                session_id=session_id,
                user_id=user_id
            )
            self.sessions[session_id] = session
            self._save_session(session)
        
        return self.sessions[session_id]
    
    # ========================================================================
    # 长期记忆
    # ========================================================================
    
    def add_memory(self, content: str, memory_type: str = "fact", 
                   importance: float = 0.5, tags: List[str] = None) -> str:
        """添加长期记忆"""
        
        memory_id = hashlib.md5(f"{content}{time.time()}".encode()).hexdigest()[:12]
        
        memory = LongTermMemory(
            memory_id=memory_id,
            content=content,
            memory_type=memory_type,
            importance=importance,
            created_at=datetime.now().isoformat(),
            last_accessed=datetime.now().isoformat(),
            tags=tags or []
        )
        
        self.long_term_memories[memory_id] = memory
        self._save_long_term_memories()
        
        logger.info(f"添加长期记忆: {content[:50]}... (类型: {memory_type})")
        
        return memory_id
    
    def search_memories(self, query: str, limit: int = 5) -> List[Dict]:
        """搜索记忆"""
        results = []
        query_lower = query.lower()
        
        for memory in self.long_term_memories.values():
            # 简单的关键词匹配
            if query_lower in memory.content.lower():
                results.append({
                    "memory_id": memory.memory_id,
                    "content": memory.content,
                    "type": memory.memory_type,
                    "importance": memory.importance,
                    "relevance": 1.0 if query_lower == memory.content.lower() else 0.5
                })
                
                # 更新访问
                memory.access_count += 1
                memory.last_accessed = datetime.now().isoformat()
        
        # 按重要性排序
        results.sort(key=lambda x: x["importance"], reverse=True)
        
        self._save_long_term_memories()
        
        return results[:limit]
    
    def get_recent_memories(self, limit: int = 10) -> List[Dict]:
        """获取最近的记忆"""
        memories = sorted(
            self.long_term_memories.values(),
            key=lambda m: m.created_at,
            reverse=True
        )
        
        return [asdict(m) for m in memories[:limit]]
    
    # ========================================================================
    # 用户偏好
    # ========================================================================
    
    def set_preference(self, key: str, value: Any, category: str = "general"):
        """设置用户偏好"""
        self.user_preferences[key] = UserPreference(
            key=key,
            value=value,
            category=category,
            updated_at=datetime.now().isoformat()
        )
        
        self._save_user_preferences()
        
        logger.info(f"设置用户偏好: {key} = {value}")
    
    def get_preference(self, key: str, default: Any = None) -> Any:
        """获取用户偏好"""
        if key in self.user_preferences:
            return self.user_preferences[key].value
        return default
    
    def get_all_preferences(self) -> Dict[str, Any]:
        """获取所有用户偏好"""
        return {k: v.value for k, v in self.user_preferences.items()}
    
    # ========================================================================
    # 持久化
    # ========================================================================
    
    def _load_from_disk(self):
        """从磁盘加载数据"""
        
        # 加载长期记忆
        memory_file = self.storage_path / self.config.long_term_memory_file
        if memory_file.exists():
            try:
                with open(memory_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for item in data:
                        memory = LongTermMemory(**item)
                        self.long_term_memories[memory.memory_id] = memory
                logger.info(f"加载了 {len(self.long_term_memories)} 条长期记忆")
            except Exception as e:
                logger.error(f"加载长期记忆失败: {e}")
        
        # 加载用户偏好
        pref_file = self.storage_path / self.config.user_preferences_file
        if pref_file.exists():
            try:
                with open(pref_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for item in data:
                        pref = UserPreference(**item)
                        self.user_preferences[pref.key] = pref
                logger.info(f"加载了 {len(self.user_preferences)} 个用户偏好")
            except Exception as e:
                logger.error(f"加载用户偏好失败: {e}")
        
        # 加载会话
        sessions_dir = self.storage_path / "sessions"
        if sessions_dir.exists():
            for session_file in sessions_dir.glob("*.json"):
                try:
                    with open(session_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        messages = [ConversationMessage(**m) for m in data.get("messages", [])]
                        session = ConversationSession(
                            session_id=data["session_id"],
                            user_id=data["user_id"],
                            messages=messages,
                            context=data.get("context", {}),
                            created_at=data.get("created_at", ""),
                            updated_at=data.get("updated_at", "")
                        )
                        self.sessions[session.session_id] = session
                except Exception as e:
                    logger.error(f"加载会话 {session_file} 失败: {e}")
            
            logger.info(f"加载了 {len(self.sessions)} 个会话")
    
    def _save_session(self, session: ConversationSession):
        """保存会话"""
        sessions_dir = self.storage_path / "sessions"
        sessions_dir.mkdir(exist_ok=True)
        
        session_file = sessions_dir / f"{session.session_id}.json"
        
        try:
            with open(session_file, 'w', encoding='utf-8') as f:
                json.dump(asdict(session), f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存会话失败: {e}")
    
    def _save_long_term_memories(self):
        """保存长期记忆"""
        memory_file = self.storage_path / self.config.long_term_memory_file
        
        try:
            with open(memory_file, 'w', encoding='utf-8') as f:
                json.dump([asdict(m) for m in self.long_term_memories.values()], 
                         f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存长期记忆失败: {e}")
    
    def _save_user_preferences(self):
        """保存用户偏好"""
        pref_file = self.storage_path / self.config.user_preferences_file
        
        try:
            with open(pref_file, 'w', encoding='utf-8') as f:
                json.dump([asdict(p) for p in self.user_preferences.values()], 
                         f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存用户偏好失败: {e}")
    
    # ========================================================================
    # 统计
    # ========================================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """获取记忆统计"""
        return {
            "sessions_count": len(self.sessions),
            "total_messages": sum(len(s.messages) for s in self.sessions.values()),
            "long_term_memories_count": len(self.long_term_memories),
            "user_preferences_count": len(self.user_preferences),
            "storage_path": str(self.storage_path)
        }

# ============================================================================
# 全局实例
# ============================================================================

_memory_manager: Optional[MemoryManager] = None

def get_memory_manager() -> MemoryManager:
    """获取全局记忆管理器"""
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager()
    return _memory_manager

# ============================================================================
# 便捷函数
# ============================================================================

def remember(content: str, memory_type: str = "fact", importance: float = 0.5) -> str:
    """记住某事"""
    return get_memory_manager().add_memory(content, memory_type, importance)

def recall(query: str, limit: int = 5) -> List[Dict]:
    """回忆某事"""
    return get_memory_manager().search_memories(query, limit)

def set_pref(key: str, value: Any):
    """设置偏好"""
    get_memory_manager().set_preference(key, value)

def get_pref(key: str, default: Any = None) -> Any:
    """获取偏好"""
    return get_memory_manager().get_preference(key, default)
