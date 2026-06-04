"""
Galaxy - 跨设备统一会话管理器
================================

实现"任意设备对话同一个智能体"的核心：
- 会话与 user_id 绑定，多设备共享同一会话
- 会话历史持久化（内存 + JSON 文件）
- 新设备加入时自动同步历史
- WebSocket 广播会话更新到所有关联设备

用法:
    from core.session_manager import get_session_manager

    sm = get_session_manager()
    session = sm.get_or_create_session(user_id="user_001", device_id="phone_01")
    sm.add_message(session.id, "user", "打开微信", device_id="phone_01")
    history = sm.get_history(session.id, max_turns=20)
"""

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.SessionManager")

# 持久化路径
_SESSION_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "sessions.json",
)


@dataclass
class SessionMessage:
    """会话中的一条消息"""
    role: str           # user / assistant / system
    content: str
    device_id: str = ""
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "role": self.role,
            "content": self.content,
            "device_id": self.device_id,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "SessionMessage":
        return cls(
            role=d.get("role", "user"),
            content=d.get("content", ""),
            device_id=d.get("device_id", ""),
            timestamp=d.get("timestamp", time.time()),
            metadata=d.get("metadata", {}),
        )


@dataclass
class Session:
    """统一会话（ConversationSession 语义层）"""
    id: str
    user_id: str
    devices: List[str] = field(default_factory=list)
    active_device: str = ""
    history: List[SessionMessage] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def conversation_session_id(self) -> str:
        """Canonical alias for conversation/history continuity semantics."""
        return self.id

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "devices": self.devices,
            "active_device": self.active_device,
            "history": [m.to_dict() for m in self.history],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }

    def to_summary(self) -> Dict:
        """轻量摘要（不含完整历史）"""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "devices": self.devices,
            "active_device": self.active_device,
            "message_count": len(self.history),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "Session":
        return cls(
            id=d["id"],
            user_id=d["user_id"],
            devices=d.get("devices", []),
            active_device=d.get("active_device", ""),
            history=[SessionMessage.from_dict(m) for m in d.get("history", [])],
            created_at=d.get("created_at", time.time()),
            updated_at=d.get("updated_at", time.time()),
            metadata=d.get("metadata", {}),
        )


class SessionManager:
    """
    跨设备统一会话管理器

    核心设计:
    - 同一个 user_id 默认共享一个活跃会话
    - 任意设备加入会话后立即获得完整历史
    - 会话更新时通过回调通知所有关联设备
    """

    MAX_HISTORY = 200       # 每个会话最大消息数
    MAX_SESSIONS = 100      # 最大会话数

    def __init__(self):
        self._sessions: Dict[str, Session] = {}
        # user_id → active session_id 映射
        self._user_active_session: Dict[str, str] = {}
        # 会话更新回调（用于 WebSocket 广播）
        self._on_update_callback = None
        self._lock = asyncio.Lock()
        self._load_state()
        logger.info("SessionManager 已初始化")

    def set_update_callback(self, callback):
        """设置会话更新回调（用于 WebSocket 广播）"""
        self._on_update_callback = callback

    # ═══════════════════ 会话生命周期 ═══════════════════

    async def create_session(self, user_id: str, device_id: str = "") -> Session:
        """创建新会话"""
        async with self._lock:
            session_id = f"session_{uuid.uuid4().hex[:12]}"
            devices = [device_id] if device_id else []
            session = Session(
                id=session_id,
                user_id=user_id,
                devices=devices,
                active_device=device_id,
            )
            self._sessions[session_id] = session
            self._user_active_session[user_id] = session_id
            self._persist_state()
            logger.info(f"会话已创建: {session_id} (user={user_id}, device={device_id})")
            return session

    async def ensure_session(
        self,
        session_id: str,
        user_id: str = "",
        device_id: str = "",
    ) -> Session:
        """确保指定 ID 的会话存在，并将设备加入该会话。"""
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                owner = user_id or f"session::{session_id}"
                devices = [device_id] if device_id else []
                session = Session(
                    id=session_id,
                    user_id=owner,
                    devices=devices,
                    active_device=device_id,
                )
                self._sessions[session_id] = session
                if owner:
                    self._user_active_session[owner] = session_id
                self._persist_state()
                logger.info(
                    "会话已确保存在: %s (user=%s, device=%s)",
                    session_id,
                    owner,
                    device_id,
                )
                return session

            if user_id:
                self._user_active_session[user_id] = session_id
            if device_id and device_id not in session.devices:
                session.devices.append(device_id)
            if device_id:
                session.active_device = device_id
            session.updated_at = time.time()
            self._persist_state()
            return session

    async def get_or_create_session(
        self, user_id: str, device_id: str = ""
    ) -> Session:
        """
        获取用户的活跃会话，如果不存在则创建。
        设备自动加入会话。
        """
        async with self._lock:
            session_id = self._user_active_session.get(user_id)
            if session_id and session_id in self._sessions:
                session = self._sessions[session_id]
                # 确保设备已加入
                if device_id and device_id not in session.devices:
                    session.devices.append(device_id)
                    logger.info(f"设备 {device_id} 已加入会话 {session_id}")
                if device_id:
                    session.active_device = device_id
                return session

            return await self.create_session(user_id, device_id)

    def get_session(self, session_id: str) -> Optional[Session]:
        """获取会话"""
        return self._sessions.get(session_id)

    async def join_session(self, session_id: str, device_id: str) -> bool:
        """设备加入已有会话"""
        async with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return False
            if device_id not in session.devices:
                session.devices.append(device_id)
            session.active_device = device_id
            session.updated_at = time.time()
            self._persist_state()
            logger.info(f"设备 {device_id} 加入会话 {session_id}")
            return True

    def list_sessions(self, user_id: Optional[str] = None) -> List[Dict]:
        """列出会话（可按 user_id 过滤）"""
        sessions = self._sessions.values()
        if user_id:
            sessions = [s for s in sessions if s.user_id == user_id]
        return [s.to_summary() for s in sessions]

    def list_device_sessions(self, device_id: str) -> List[Dict]:
        """列出设备参与的所有会话"""
        return [
            s.to_summary()
            for s in self._sessions.values()
            if device_id in s.devices
        ]

    # ═══════════════════ 消息管理 ═══════════════════

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        device_id: str = "",
        metadata: Optional[Dict] = None,
    ) -> bool:
        """添加消息到会话"""
        async with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return False

            msg = SessionMessage(
                role=role,
                content=content,
                device_id=device_id,
                metadata=metadata or {},
            )
            session.history.append(msg)
            session.updated_at = time.time()
            if device_id:
                session.active_device = device_id

            # 历史超限时截断
            if len(session.history) > self.MAX_HISTORY:
                session.history = session.history[-self.MAX_HISTORY:]

            self._persist_state()

            # 通知所有关联设备
            if self._on_update_callback:
                try:
                    self._on_update_callback(session_id, msg.to_dict(), session.devices)
                except Exception as e:
                    logger.debug(f"会话更新回调失败: {e}")

            return True

    def get_history(
        self, session_id: str, max_turns: int = 20
    ) -> List[Dict]:
        """获取会话历史（格式兼容 LLM messages）"""
        session = self._sessions.get(session_id)
        if not session:
            return []
        messages = session.history[-max_turns:]
        return [{"role": m.role, "content": m.content} for m in messages]

    def get_full_history(self, session_id: str) -> List[Dict]:
        """获取完整历史（含设备和时间戳）"""
        session = self._sessions.get(session_id)
        if not session:
            return []
        return [m.to_dict() for m in session.history]

    # ═══════════════════ 持久化 ═══════════════════

    def _persist_state(self):
        """持久化会话到 JSON 文件"""
        try:
            os.makedirs(os.path.dirname(_SESSION_FILE), exist_ok=True)
            data = {
                "sessions": {
                    sid: s.to_dict() for sid, s in self._sessions.items()
                },
                "user_active_session": self._user_active_session,
            }
            with open(_SESSION_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.debug(f"会话持久化失败: {e}")

    def _load_state(self):
        """从 JSON 文件恢复会话"""
        if not os.path.exists(_SESSION_FILE):
            return
        try:
            with open(_SESSION_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for sid, sdata in data.get("sessions", {}).items():
                self._sessions[sid] = Session.from_dict(sdata)
            self._user_active_session = data.get("user_active_session", {})
            logger.info(f"已恢复 {len(self._sessions)} 个会话")
        except Exception as e:
            logger.warning(f"会话恢复失败: {e}")


# ═══════════════════ 单例 ═══════════════════

_session_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager
