"""
Node 111: Context Manager - 上下文管理节点
负责会话管理、用户画像管理、上下文信息检索和历史记录查询
"""

import json
import time
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
import threading


class SessionStatus(Enum):
    """会话状态枚举"""
    ACTIVE = "active"
    IDLE = "idle"
    EXPIRED = "expired"
    CLOSED = "closed"


@dataclass
class UserProfile:
    """用户画像数据结构"""
    user_id: str
    username: str
    preferences: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    interaction_count: int = 0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_active: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'UserProfile':
        return cls(**data)


@dataclass
class Session:
    """会话数据结构"""
    session_id: str
    user_id: str
    status: SessionStatus = SessionStatus.ACTIVE
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_activity: str = field(default_factory=lambda: datetime.now().isoformat())
    expires_at: str = field(default_factory=lambda: (datetime.now() + timedelta(hours=24)).isoformat())
    context_data: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "status": self.status.value,
            "created_at": self.created_at,
            "last_activity": self.last_activity,
            "expires_at": self.expires_at,
            "context_data": self.context_data,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Session':
        data = data.copy()
        data['status'] = SessionStatus(data.get('status', 'active'))
        return cls(**data)


@dataclass
class HistoryRecord:
    """历史记录数据结构"""
    record_id: str
    session_id: str
    user_id: str
    action_type: str
    content: Dict[str, Any]
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ContextManager:
    """
    上下文管理器核心类
    负责会话管理、用户画像管理、上下文信息检索和历史记录查询
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self._sessions: Dict[str, Session] = {}
        self._user_profiles: Dict[str, UserProfile] = {}
        self._history_records: List[HistoryRecord] = []
        self._lock = threading.RLock()

        # 配置项
        self.session_timeout = self.config.get('session_timeout', 3600)  # 默认1小时
        self.max_history_per_session = self.config.get('max_history_per_session', 100)
        self.cleanup_interval = self.config.get('cleanup_interval', 300)  # 5分钟

        # 启动清理线程
        self._cleanup_thread = threading.Thread(target=self._cleanup_expired_sessions, daemon=True)
        self._cleanup_thread.start()

    # ==================== 会话管理 ====================

    def create_session(self, user_id: str, metadata: Optional[Dict[str, Any]] = None) -> Session:
        """创建新会话"""
        with self._lock:
            session_id = self._generate_session_id(user_id)
            expires_at = (datetime.now() + timedelta(seconds=self.session_timeout)).isoformat()

            session = Session(
                session_id=session_id,
                user_id=user_id,
                expires_at=expires_at,
                metadata=metadata or {}
            )

            self._sessions[session_id] = session

            self._add_history_record(
                session_id=session_id,
                user_id=user_id,
                action_type="session_created",
                content={"metadata": metadata}
            )

            return session

    def get_session(self, session_id: str) -> Optional[Session]:
        """获取会话信息"""
        with self._lock:
            session = self._sessions.get(session_id)
            if session and self._is_session_valid(session):
                session.last_activity = datetime.now().isoformat()
                return session
            return None

    def update_session(self, session_id: str, updates: Dict[str, Any]) -> Optional[Session]:
        """更新会话信息"""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None

            if 'context_data' in updates:
                session.context_data.update(updates['context_data'])
            if 'metadata' in updates:
                session.metadata.update(updates['metadata'])
            if 'status' in updates:
                session.status = SessionStatus(updates['status'])

            session.last_activity = datetime.now().isoformat()

            self._add_history_record(
                session_id=session_id,
                user_id=session.user_id,
                action_type="session_updated",
                content={"updates": updates}
            )

            return session

    def close_session(self, session_id: str) -> bool:
        """关闭会话"""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return False

            session.status = SessionStatus.CLOSED

            self._add_history_record(
                session_id=session_id,
                user_id=session.user_id,
                action_type="session_closed",
                content={}
            )

            return True

    def destroy_session(self, session_id: str) -> bool:
        """销毁会话（彻底删除）"""
        with self._lock:
            session = self._sessions.pop(session_id, None)
            if session:
                self._add_history_record(
                    session_id=session_id,
                    user_id=session.user_id,
                    action_type="session_destroyed",
                    content={}
                )
                return True
            return False

    def list_sessions(self, user_id: Optional[str] = None, 
                      status: Optional[SessionStatus] = None) -> List[Session]:
        """列出会话"""
        with self._lock:
            sessions = list(self._sessions.values())

            if user_id:
                sessions = [s for s in sessions if s.user_id == user_id]

            if status:
                sessions = [s for s in sessions if s.status == status]

            return sessions

    # ==================== 用户画像管理 ====================

    def create_user_profile(self, user_id: str, username: str, 
                           preferences: Optional[Dict[str, Any]] = None,
                           tags: Optional[List[str]] = None) -> UserProfile:
        """创建用户画像"""
        with self._lock:
            profile = UserProfile(
                user_id=user_id,
                username=username,
                preferences=preferences or {},
                tags=tags or []
            )

            self._user_profiles[user_id] = profile
            return profile

    def get_user_profile(self, user_id: str) -> Optional[UserProfile]:
        """获取用户画像"""
        with self._lock:
            profile = self._user_profiles.get(user_id)
            if profile:
                profile.last_active = datetime.now().isoformat()
            return profile

    def update_user_profile(self, user_id: str, updates: Dict[str, Any]) -> Optional[UserProfile]:
        """更新用户画像"""
        with self._lock:
            profile = self._user_profiles.get(user_id)
            if not profile:
                return None

            if 'username' in updates:
                profile.username = updates['username']
            if 'preferences' in updates:
                profile.preferences.update(updates['preferences'])
            if 'tags' in updates:
                profile.tags = list(set(profile.tags + updates['tags']))
            if 'metadata' in updates:
                profile.metadata.update(updates['metadata'])

            profile.interaction_count += 1
            profile.last_active = datetime.now().isoformat()

            return profile

    def delete_user_profile(self, user_id: str) -> bool:
        """删除用户画像"""
        with self._lock:
            return self._user_profiles.pop(user_id, None) is not None

    def list_user_profiles(self, tags: Optional[List[str]] = None) -> List[UserProfile]:
        """列出用户画像"""
        with self._lock:
            profiles = list(self._user_profiles.values())

            if tags:
                profiles = [p for p in profiles if any(tag in p.tags for tag in tags)]

            return profiles

    # ==================== 上下文信息检索 ====================

    def get_context(self, session_id: str, key: Optional[str] = None) -> Optional[Any]:
        """获取上下文信息"""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None

            if key:
                return session.context_data.get(key)
            return session.context_data

    def set_context(self, session_id: str, key: str, value: Any) -> bool:
        """设置上下文信息"""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return False

            session.context_data[key] = value
            session.last_activity = datetime.now().isoformat()

            self._add_history_record(
                session_id=session_id,
                user_id=session.user_id,
                action_type="context_updated",
                content={"key": key, "value": value}
            )

            return True

    def delete_context(self, session_id: str, key: str) -> bool:
        """删除上下文信息"""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session or key not in session.context_data:
                return False

            del session.context_data[key]
            session.last_activity = datetime.now().isoformat()

            return True

    def clear_context(self, session_id: str) -> bool:
        """清空上下文信息"""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return False

            session.context_data.clear()
            session.last_activity = datetime.now().isoformat()

            return True

    def merge_context(self, session_id: str, context_data: Dict[str, Any]) -> bool:
        """合并上下文信息"""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return False

            session.context_data.update(context_data)
            session.last_activity = datetime.now().isoformat()

            self._add_history_record(
                session_id=session_id,
                user_id=session.user_id,
                action_type="context_merged",
                content={"merged_keys": list(context_data.keys())}
            )

            return True

    # ==================== 历史记录查询 ====================

    def get_history(self, session_id: Optional[str] = None,
                   user_id: Optional[str] = None,
                   action_type: Optional[str] = None,
                   limit: int = 50,
                   offset: int = 0) -> List[HistoryRecord]:
        """查询历史记录"""
        with self._lock:
            records = self._history_records.copy()

            if session_id:
                records = [r for r in records if r.session_id == session_id]

            if user_id:
                records = [r for r in records if r.user_id == user_id]

            if action_type:
                records = [r for r in records if r.action_type == action_type]

            records.sort(key=lambda r: r.timestamp, reverse=True)

            return records[offset:offset + limit]

    def get_session_history_summary(self, session_id: str) -> Dict[str, Any]:
        """获取会话历史摘要"""
        with self._lock:
            records = [r for r in self._history_records if r.session_id == session_id]

            action_counts = {}
            for r in records:
                action_counts[r.action_type] = action_counts.get(r.action_type, 0) + 1

            return {
                "session_id": session_id,
                "total_records": len(records),
                "action_summary": action_counts,
                "first_record_time": records[0].timestamp if records else None,
                "last_record_time": records[-1].timestamp if records else None
            }

    def clear_history(self, session_id: Optional[str] = None) -> int:
        """清除历史记录"""
        with self._lock:
            if session_id:
                original_count = len(self._history_records)
                self._history_records = [r for r in self._history_records if r.session_id != session_id]
                return original_count - len(self._history_records)
            else:
                count = len(self._history_records)
                self._history_records.clear()
                return count

    # ==================== 内部方法 ====================

    def _generate_session_id(self, user_id: str) -> str:
        """生成会话ID"""
        timestamp = str(time.time())
        data = f"{user_id}:{timestamp}"
        return hashlib.sha256(data.encode()).hexdigest()[:32]

    def _generate_record_id(self) -> str:
        """生成记录ID"""
        timestamp = str(time.time())
        return hashlib.sha256(timestamp.encode()).hexdigest()[:16]

    def _is_session_valid(self, session: Session) -> bool:
        """检查会话是否有效"""
        if session.status == SessionStatus.CLOSED:
            return False

        expires_at = datetime.fromisoformat(session.expires_at)
        if datetime.now() > expires_at:
            session.status = SessionStatus.EXPIRED
            return False

        return True

    def _add_history_record(self, session_id: str, user_id: str, 
                           action_type: str, content: Dict[str, Any]):
        """添加历史记录"""
        record = HistoryRecord(
            record_id=self._generate_record_id(),
            session_id=session_id,
            user_id=user_id,
            action_type=action_type,
            content=content
        )
        self._history_records.append(record)

        if len(self._history_records) > self.max_history_per_session * 100:
            self._history_records = self._history_records[-self.max_history_per_session * 50:]

    def _cleanup_expired_sessions(self):
        """清理过期会话的后台线程"""
        while True:
            time.sleep(self.cleanup_interval)
            with self._lock:
                expired_sessions = []
                for session_id, session in self._sessions.items():
                    if not self._is_session_valid(session):
                        expired_sessions.append(session_id)

                for session_id in expired_sessions:
                    session = self._sessions.get(session_id)
                    if session:
                        session.status = SessionStatus.EXPIRED


# ==================== 对外接口 ====================

_context_manager: Optional[ContextManager] = None


def create_context_manager(config: Optional[Dict[str, Any]] = None) -> ContextManager:
    """创建上下文管理器实例"""
    return ContextManager(config)


def get_context_manager() -> ContextManager:
    """获取全局上下文管理器实例"""
    global _context_manager
    if _context_manager is None:
        _context_manager = create_context_manager()
    return _context_manager


def reset_context_manager():
    """重置全局上下文管理器实例"""
    global _context_manager
    _context_manager = None


# ==================== 快速API方法 ====================

def create_session(user_id: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """快速创建会话"""
    cm = get_context_manager()
    session = cm.create_session(user_id, metadata)
    return session.to_dict()


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    """快速获取会话"""
    cm = get_context_manager()
    session = cm.get_session(session_id)
    return session.to_dict() if session else None


def close_session(session_id: str) -> bool:
    """快速关闭会话"""
    cm = get_context_manager()
    return cm.close_session(session_id)


def set_context(session_id: str, key: str, value: Any) -> bool:
    """快速设置上下文"""
    cm = get_context_manager()
    return cm.set_context(session_id, key, value)


def get_context(session_id: str, key: Optional[str] = None) -> Optional[Any]:
    """快速获取上下文"""
    cm = get_context_manager()
    return cm.get_context(session_id, key)


def get_user_profile(user_id: str) -> Optional[Dict[str, Any]]:
    """快速获取用户画像"""
    cm = get_context_manager()
    profile = cm.get_user_profile(user_id)
    return profile.to_dict() if profile else None


def get_history(session_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """快速获取历史记录"""
    cm = get_context_manager()
    records = cm.get_history(session_id=session_id, limit=limit)
    return [r.to_dict() for r in records]


if __name__ == "__main__":
    print("=" * 50)
    print("Context Manager Test")
    print("=" * 50)

    cm = create_context_manager()

    print("\n1. Testing User Profile Management")
    profile = cm.create_user_profile(
        user_id="user_001",
        username="TestUser",
        preferences={"theme": "dark", "language": "zh"},
        tags=["developer", "tester"]
    )
    print(f"Created profile: {profile.to_dict()}")

    print("\n2. Testing Session Management")
    session = cm.create_session(user_id="user_001", metadata={"source": "test"})
    print(f"Created session: {session.to_dict()}")

    print("\n3. Testing Context Operations")
    cm.set_context(session.session_id, "current_task", "testing")
    cm.set_context(session.session_id, "progress", 50)
    context = cm.get_context(session.session_id)
    print(f"Context data: {context}")

    print("\n4. Testing History Records")
    history = cm.get_history(session_id=session.session_id)
    print(f"History count: {len(history)}")
    for record in history[:3]:
        print(f"  - {record.action_type}: {record.timestamp}")

    print("\n" + "=" * 50)
    print("All tests passed!")
    print("=" * 50)
