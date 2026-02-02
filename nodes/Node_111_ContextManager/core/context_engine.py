"""
Node_111_ContextManager - 上下文管理引擎

功能：
1. 会话管理 - 跨会话持久化对话历史
2. 用户画像 - 学习用户偏好（调用 Node_73）
3. 上下文注入 - 在任务执行时自动注入相关上下文
4. 知识积累 - 持续积累领域知识
"""

import json
import logging
import requests
import sqlite3
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class Session:
    """会话对象"""
    def __init__(self, session_id: str, user_id: str):
        self.session_id = session_id
        self.user_id = user_id
        self.created_at = datetime.now()
        self.last_active = datetime.now()
        self.messages: List[Dict[str, Any]] = []
        self.metadata: Dict[str, Any] = {}


class UserProfile:
    """用户画像"""
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.preferences: Dict[str, Any] = {}
        self.interaction_history: List[Dict[str, Any]] = []
        self.learned_patterns: Dict[str, Any] = {}
        self.created_at = datetime.now()
        self.updated_at = datetime.now()


class ContextManager:
    """上下文管理引擎"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.node_01_url = config.get("node_01_url", "http://localhost:8001")
        self.node_13_url = config.get("node_13_url", "http://localhost:8013")
        self.node_20_url = config.get("node_20_url", "http://localhost:8020")
        self.node_73_url = config.get("node_73_url", "http://localhost:8073")
        self.node_100_url = config.get("node_100_url", "http://localhost:8100")
        
        self.db_path = config.get("db_path", "context_manager.db")
        self.sessions: Dict[str, Session] = {}
        self.user_profiles: Dict[str, UserProfile] = {}
        
        # 上下文配置
        self.max_context_length = config.get("max_context_length", 10)
        self.context_ttl = config.get("context_ttl", 3600)  # 1小时
        
        # 初始化数据库
        self._init_database()
        
        logger.info("ContextManager initialized")
    
    def _init_database(self):
        """初始化 SQLite 数据库"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 创建会话表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_active TEXT NOT NULL,
                    metadata TEXT
                )
            """)
            
            # 创建消息表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
                )
            """)
            
            # 创建用户画像表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id TEXT PRIMARY KEY,
                    preferences TEXT,
                    learned_patterns TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            
            # 创建上下文索引表（用于快速检索）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS context_index (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    keywords TEXT NOT NULL,
                    embedding_id TEXT,
                    timestamp TEXT NOT NULL
                )
            """)
            
            conn.commit()
            conn.close()
            
            logger.info("Database initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}", exc_info=True)
            raise
    
    async def save_context(
        self,
        session_id: str,
        user_id: str,
        messages: List[Dict[str, str]],
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """保存上下文"""
        try:
            # 创建或更新会话
            if session_id not in self.sessions:
                self.sessions[session_id] = Session(session_id, user_id)
            
            session = self.sessions[session_id]
            session.last_active = datetime.now()
            session.messages.extend(messages)
            if metadata:
                session.metadata.update(metadata)
            
            # 保存到数据库
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT OR REPLACE INTO sessions (session_id, user_id, created_at, last_active, metadata)
                VALUES (?, ?, ?, ?, ?)
            """, (
                session_id,
                user_id,
                session.created_at.isoformat(),
                session.last_active.isoformat(),
                json.dumps(session.metadata)
            ))
            
            for msg in messages:
                cursor.execute("""
                    INSERT INTO messages (session_id, role, content, timestamp)
                    VALUES (?, ?, ?, ?)
                """, (
                    session_id,
                    msg["role"],
                    msg["content"],
                    datetime.now().isoformat()
                ))
            
            conn.commit()
            conn.close()
            
            # 存储嵌入和更新用户画像
            await self._store_context_embeddings(session_id, messages)
            await self._update_user_profile(user_id, messages)
            
            logger.info(f"Context saved for session {session_id}")
            
            return {
                "success": True,
                "session_id": session_id,
                "messages_saved": len(messages)
            }
            
        except Exception as e:
            logger.error(f"Failed to save context: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
    
    async def get_context(self, session_id: str, limit: Optional[int] = None) -> Dict[str, Any]:
        """获取上下文"""
        try:
            # 从内存获取
            if session_id in self.sessions:
                session = self.sessions[session_id]
                messages = session.messages[-limit:] if limit else session.messages
                
                return {
                    "session_id": session_id,
                    "user_id": session.user_id,
                    "messages": messages,
                    "metadata": session.metadata,
                    "created_at": session.created_at.isoformat(),
                    "last_active": session.last_active.isoformat()
                }
            
            # 从数据库获取
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT user_id, created_at, last_active, metadata
                FROM sessions WHERE session_id = ?
            """, (session_id,))
            
            row = cursor.fetchone()
            if not row:
                conn.close()
                return {"success": False, "error": f"Session {session_id} not found"}
            
            user_id, created_at, last_active, metadata = row
            
            query = "SELECT role, content, timestamp FROM messages WHERE session_id = ? ORDER BY timestamp DESC"
            if limit:
                query += f" LIMIT {limit}"
            
            cursor.execute(query, (session_id,))
            messages = [{"role": row[0], "content": row[1], "timestamp": row[2]} for row in cursor.fetchall()]
            messages.reverse()
            
            conn.close()
            
            return {
                "session_id": session_id,
                "user_id": user_id,
                "messages": messages,
                "metadata": json.loads(metadata) if metadata else {},
                "created_at": created_at,
                "last_active": last_active
            }
            
        except Exception as e:
            logger.error(f"Failed to get context: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
    
    async def search_context(self, query: str, user_id: Optional[str] = None, limit: int = 5) -> Dict[str, Any]:
        """搜索相关上下文"""
        try:
            # 调用 Node_20 (Qdrant) 进行向量搜索
            response = requests.post(
                f"{self.node_20_url}/api/v1/search",
                json={
                    "collection": "context_embeddings",
                    "query": query,
                    "limit": limit,
                    "filter": {"user_id": user_id} if user_id else None
                },
                timeout=10
            )
            
            if response.status_code == 200:
                search_results = response.json()
                contexts = []
                
                for result in search_results.get("results", []):
                    session_id = result.get("session_id")
                    if session_id:
                        context = await self.get_context(session_id, limit=3)
                        if context.get("messages"):
                            contexts.append({
                                "session_id": session_id,
                                "relevance_score": result.get("score", 0.0),
                                "messages": context["messages"]
                            })
                
                return {"success": True, "query": query, "results": contexts}
            else:
                return await self._fallback_search(query, user_id, limit)
                
        except Exception as e:
            logger.error(f"Failed to search context: {e}")
            return await self._fallback_search(query, user_id, limit)
    
    async def _fallback_search(self, query: str, user_id: Optional[str], limit: int) -> Dict[str, Any]:
        """后备搜索（SQLite 全文搜索）"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            query_sql = """
                SELECT DISTINCT m.session_id, m.content, m.timestamp
                FROM messages m
                JOIN sessions s ON m.session_id = s.session_id
                WHERE m.content LIKE ?
            """
            params = [f"%{query}%"]
            
            if user_id:
                query_sql += " AND s.user_id = ?"
                params.append(user_id)
            
            query_sql += " ORDER BY m.timestamp DESC LIMIT ?"
            params.append(limit)
            
            cursor.execute(query_sql, params)
            results = [{"session_id": row[0], "content": row[1], "timestamp": row[2], "relevance_score": 0.5} for row in cursor.fetchall()]
            
            conn.close()
            
            return {"success": True, "query": query, "results": results, "fallback": True}
            
        except Exception as e:
            logger.error(f"Fallback search failed: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_user_profile(self, user_id: str) -> Dict[str, Any]:
        """获取用户画像"""
        try:
            if user_id in self.user_profiles:
                profile = self.user_profiles[user_id]
                return {
                    "user_id": user_id,
                    "preferences": profile.preferences,
                    "learned_patterns": profile.learned_patterns,
                    "interaction_count": len(profile.interaction_history),
                    "created_at": profile.created_at.isoformat(),
                    "updated_at": profile.updated_at.isoformat()
                }
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT preferences, learned_patterns, created_at, updated_at
                FROM user_profiles WHERE user_id = ?
            """, (user_id,))
            
            row = cursor.fetchone()
            conn.close()
            
            if row:
                return {
                    "user_id": user_id,
                    "preferences": json.loads(row[0]) if row[0] else {},
                    "learned_patterns": json.loads(row[1]) if row[1] else {},
                    "created_at": row[2],
                    "updated_at": row[3]
                }
            else:
                return {
                    "user_id": user_id,
                    "preferences": {},
                    "learned_patterns": {},
                    "message": "User profile not found, will be created on first interaction"
                }
                
        except Exception as e:
            logger.error(f"Failed to get user profile: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
    
    async def _store_context_embeddings(self, session_id: str, messages: List[Dict[str, str]]):
        """存储上下文嵌入到 Node_20 (Qdrant)"""
        try:
            content = " ".join([msg["content"] for msg in messages])
            
            response = requests.post(
                f"{self.node_20_url}/api/v1/embed",
                json={
                    "collection": "context_embeddings",
                    "text": content,
                    "metadata": {"session_id": session_id, "timestamp": datetime.now().isoformat()}
                },
                timeout=10
            )
            
            if response.status_code == 200:
                logger.info(f"Context embeddings stored for session {session_id}")
            else:
                logger.warning(f"Failed to store embeddings: {response.status_code}")
                
        except Exception as e:
            logger.error(f"Failed to store context embeddings: {e}")
    
    async def _update_user_profile(self, user_id: str, messages: List[Dict[str, str]]):
        """更新用户画像（调用 Node_73 Learning）"""
        try:
            response = requests.post(
                f"{self.node_73_url}/api/v1/learn",
                json={"user_id": user_id, "interactions": messages},
                timeout=10
            )
            
            if response.status_code == 200:
                learned_data = response.json()
                
                if user_id not in self.user_profiles:
                    self.user_profiles[user_id] = UserProfile(user_id)
                
                profile = self.user_profiles[user_id]
                profile.learned_patterns.update(learned_data.get("patterns", {}))
                profile.updated_at = datetime.now()
                
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT OR REPLACE INTO user_profiles (user_id, preferences, learned_patterns, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    user_id,
                    json.dumps(profile.preferences),
                    json.dumps(profile.learned_patterns),
                    profile.created_at.isoformat(),
                    profile.updated_at.isoformat()
                ))
                
                conn.commit()
                conn.close()
                
                logger.info(f"User profile updated for {user_id}")
            else:
                logger.warning(f"Node_73 learning failed: {response.status_code}")
                
        except Exception as e:
            logger.error(f"Failed to update user profile: {e}")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM sessions")
            total_sessions = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM messages")
            total_messages = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM user_profiles")
            total_users = cursor.fetchone()[0]
            
            one_hour_ago = (datetime.now() - timedelta(hours=1)).isoformat()
            cursor.execute("SELECT COUNT(*) FROM sessions WHERE last_active > ?", (one_hour_ago,))
            active_sessions = cursor.fetchone()[0]
            
            conn.close()
            
            return {
                "total_sessions": total_sessions,
                "total_messages": total_messages,
                "total_users": total_users,
                "active_sessions": active_sessions,
                "memory_sessions": len(self.sessions),
                "memory_profiles": len(self.user_profiles)
            }
            
        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return {"error": str(e)}
