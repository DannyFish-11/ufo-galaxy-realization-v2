"""
galaxy_gateway/session_roaming.py — Session Roaming Manager
  (Legacy Compatibility Module — PR-M)

.. deprecated:: PR-M
    This module (``galaxy_gateway.session_roaming``) is a **legacy
    compatibility surface** retained for backward compatibility only.

    ``SessionRoamingManager`` manages session migration between devices by
    directly instantiating ``CrossDeviceCoordinator`` (a legacy fallback
    coordinator, PR-S3) and calling ``core.device_communication.send_command``
    outside the canonical
    ``CanonicalTask → TaskEnvelope → CommandRouter.route_envelope()`` spine.
    This makes it a parallel session-migration authority that bypasses
    canonical dispatch and truth ownership.

    Canonical replacement::

        core.canonical_session_axis  (canonical session ownership)
        core.attached_runtime_session  (runtime session lifecycle)
        → CommandRouter.route_envelope(TaskEnvelope)  (canonical dispatch)

    New code must not use ``SessionRoamingManager`` as a primary session
    migration authority.  Session continuity and cross-device handoff must
    go through the canonical session axis and attached-runtime session layer.

    See ``core.orchestration_authority.legacy_paths`` for the registry entry
    (``galaxy_gateway.session_roaming.SessionRoamingManager``).

Session Roaming Manager - 会话漫游管理器（Legacy Compat — 仅保留向后兼容性）

核心功能：
- 会话创建与跟踪：在唤醒时创建会话，记录对话上下文、任务状态
- 会话迁移：支持将活跃会话从设备A迁移到设备B
- 自动迁移触发：当用户注意力从一个设备转移到另一个设备时自动迁移会话
- 会话持久化：使用 cross_device_coordinator.set_shared_data() 存储会话快照

Author: UFO Galaxy Team
Version: 1.0
"""

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable

logger = logging.getLogger("UFO-Galaxy.SessionRoaming")

# 持久化存储目录（JSON 文件）
PERSISTENCE_DIR = Path(os.path.expanduser("~")) / ".galaxy" / "session_roaming"
PERSISTENCE_FILE = PERSISTENCE_DIR / "sessions.json"


# =============================================================================
# 数据模型
# =============================================================================

class SessionState(Enum):
    """会话状态"""
    ACTIVE = "active"         # 正在进行
    MIGRATING = "migrating"   # 迁移中
    IDLE = "idle"             # 空闲（无设备处理）
    CLOSED = "closed"         # 已关闭


@dataclass
class ConversationTurn:
    """一轮对话记录"""
    role: str                        # "user" | "assistant"
    content: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        return {"role": self.role, "content": self.content, "timestamp": self.timestamp}

    @classmethod
    def from_dict(cls, d: Dict) -> "ConversationTurn":
        return cls(role=d["role"], content=d["content"], timestamp=d.get("timestamp", 0))


@dataclass
class SessionContext:
    """会话上下文（可序列化，用于跨设备迁移）"""
    session_id: str
    created_at: float = field(default_factory=time.time)
    # 对话历史
    history: List[ConversationTurn] = field(default_factory=list)
    # 当前任务状态（由 Agent 写入，业务相关）
    task_state: Dict[str, Any] = field(default_factory=dict)
    # 元数据（唤醒词、设备等）
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "history": [t.to_dict() for t in self.history],
            "task_state": self.task_state,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "SessionContext":
        ctx = cls(
            session_id=d["session_id"],
            created_at=d.get("created_at", time.time()),
            task_state=d.get("task_state", {}),
            meta=d.get("meta", {}),
        )
        ctx.history = [ConversationTurn.from_dict(t) for t in d.get("history", [])]
        return ctx


@dataclass
class Session:
    """一个完整的会话对象"""
    session_id: str
    device_id: str                    # 当前响应设备
    state: SessionState = SessionState.ACTIVE
    context: SessionContext = field(default_factory=lambda: SessionContext(
        session_id="__placeholder__"
    ))
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)

    def __post_init__(self):
        if self.context.session_id == "__placeholder__":
            self.context = SessionContext(session_id=self.session_id)

    def to_dict(self) -> Dict:
        return {
            "session_id": self.session_id,
            "device_id": self.device_id,
            "state": self.state.value,
            "context": self.context.to_dict(),
            "created_at": self.created_at,
            "last_active": self.last_active,
        }


# =============================================================================
# DEPRECATION GUARD (PR-ROAMING-LEGACY)
# =============================================================================
# SessionRoamingManager is a **legacy compatibility layer**.
# The canonical session management authority is:
#     core/routes/sessions.py  (REST API)
#     core.desktop_presence_runtime.DesktopPresenceRuntime  (runtime session)
#
# New code MUST NOT add features here.  For session migration, use:
#     POST /api/v1/sessions/{session_id}/migrate
#
# This module is preserved only so existing Android clients that call
# the legacy roaming endpoints continue to work.  It may be removed
# in a future release.
# =============================================================================
SESSION_ROAMING_LEGACY_GUARD = (
    "SESSION_ROAMING::LEGACY_COMPATIBILITY_LAYER:: "
    "canonical_session_management_is_core_routes_sessions"
)

# =============================================================================
# 会话漫游管理器
# =============================================================================

class SessionRoamingManager:
    """Legacy compatibility session migration manager (PR-M).

    .. deprecated:: PR-M
        ``SessionRoamingManager`` is a LEGACY COMPAT SESSION MANAGER.
        It migrates sessions between devices by directly using
        ``CrossDeviceCoordinator`` (a legacy fallback coordinator) and
        ``core.device_communication.send_command``, bypassing the canonical
        ``CanonicalTask → TaskEnvelope → CommandRouter.route_envelope()``
        spine.  New session continuity and cross-device handoff must use the
        canonical session axis (``core.canonical_session_axis``) and
        attached-runtime session layer (``core.attached_runtime_session``).

    会话漫游管理器（legacy compat — 仅保留向后兼容性）

    负责会话的完整生命周期管理，包括创建、跟踪、迁移和关闭。
    通过 cross_device_coordinator 的共享数据存储实现持久化快照。
    通过 core.device_communication.send_command 将会话上下文推送到目标设备。
    """

    # 会话空闲超时（秒），超时后自动标记为 IDLE
    IDLE_TIMEOUT: float = 300.0
    # 快照存储键前缀
    SNAPSHOT_KEY_PREFIX: str = "session_snapshot:"

    def __init__(self):
        try:
            from core.orchestration_authority.legacy_paths import emit_legacy_guardrail
            emit_legacy_guardrail(
                "galaxy_gateway.session_roaming.SessionRoamingManager"
            )
        except Exception:
            pass
        self._sessions: Dict[str, Session] = {}
        # 设备 → 当前会话 ID 映射
        self._device_session_map: Dict[str, str] = {}
        # 注意力焦点变化回调（device_id -> session_id 迁移）
        self._on_migrated: Optional[Callable[[str, str, str], Any]] = None

        # 从磁盘加载持久化会话
        self._load_sessions_from_disk()

        logger.info("SessionRoamingManager initialized")

    def _load_sessions_from_disk(self):
        """从磁盘 JSON 文件加载会话数据。"""
        try:
            if PERSISTENCE_FILE.exists():
                data = json.loads(PERSISTENCE_FILE.read_text(encoding="utf-8"))
                for sid, sdict in data.get("sessions", {}).items():
                    try:
                        session = Session(
                            session_id=sdict["session_id"],
                            device_id=sdict["device_id"],
                            state=SessionState(sdict["state"]),
                            context=SessionContext.from_dict(sdict["context"]),
                            created_at=sdict.get("created_at", time.time()),
                            last_active=sdict.get("last_active", time.time()),
                        )
                        self._sessions[sid] = session
                    except Exception as e:
                        logger.warning(f"[SessionRoaming] 跳过低效会话: {e}")
                self._device_session_map = data.get("device_session_map", {})
                logger.info(f"[SessionRoaming] 从磁盘加载 {len(self._sessions)} 个会话")
        except Exception as e:
            logger.warning(f"[SessionRoaming] 从磁盘加载会话失败: {e}")

    def _save_sessions_to_disk(self):
        """将会话数据持久化到磁盘 JSON 文件。"""
        try:
            PERSISTENCE_DIR.mkdir(parents=True, exist_ok=True)
            data = {
                "sessions": {
                    sid: s.to_dict() for sid, s in self._sessions.items()
                },
                "device_session_map": dict(self._device_session_map),
                "saved_at": datetime.now().isoformat(),
            }
            # 先写入临时文件，再原子重命名，防止写断
            tmp_file = PERSISTENCE_FILE.with_suffix(".tmp")
            tmp_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp_file.replace(PERSISTENCE_FILE)
        except Exception as e:
            logger.warning(f"[SessionRoaming] 持久化到磁盘失败: {e}")

    # ------------------------------------------------------------------
    # 会话生命周期
    # ------------------------------------------------------------------

    def create_session(
        self,
        device_id: str,
        wake_word: str = "",
        meta: Optional[Dict] = None,
    ) -> Session:
        """
        创建新会话

        Args:
            device_id: 响应该唤醒事件的设备 ID
            wake_word: 触发唤醒的词语
            meta: 附加元数据

        Returns:
            新建的 Session 对象
        """
        session_id = str(uuid.uuid4())[:12]
        ctx = SessionContext(
            session_id=session_id,
            meta={"wake_word": wake_word, "initial_device": device_id, **(meta or {})},
        )
        session = Session(
            session_id=session_id,
            device_id=device_id,
            context=ctx,
        )
        self._sessions[session_id] = session
        self._device_session_map[device_id] = session_id
        self._save_sessions_to_disk()
        logger.info(f"[SessionRoaming] 会话创建: session_id={session_id} device={device_id}")
        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        """根据 session_id 获取会话"""
        return self._sessions.get(session_id)

    def get_session_by_device(self, device_id: str) -> Optional[Session]:
        """根据设备 ID 获取当前关联会话"""
        session_id = self._device_session_map.get(device_id)
        if session_id:
            return self._sessions.get(session_id)
        return None

    def add_turn(self, session_id: str, role: str, content: str):
        """向会话添加一轮对话"""
        session = self._sessions.get(session_id)
        if not session:
            logger.warning(f"[SessionRoaming] 会话不存在: {session_id}")
            return
        session.context.history.append(ConversationTurn(role=role, content=content))
        session.last_active = time.time()
        self._save_sessions_to_disk()

    def update_task_state(self, session_id: str, task_state: Dict):
        """更新会话的任务状态"""
        session = self._sessions.get(session_id)
        if not session:
            return
        session.context.task_state.update(task_state)
        session.last_active = time.time()
        self._save_sessions_to_disk()

    def close_session(self, session_id: str):
        """关闭会话"""
        session = self._sessions.get(session_id)
        if not session:
            return
        session.state = SessionState.CLOSED
        # 移除设备映射
        if self._device_session_map.get(session.device_id) == session_id:
            del self._device_session_map[session.device_id]
        self._save_sessions_to_disk()
        logger.info(f"[SessionRoaming] 会话关闭: session_id={session_id}")

    # ------------------------------------------------------------------
    # 会话迁移
    # ------------------------------------------------------------------

    async def migrate_session(self, session_id: str, target_device_id: str) -> bool:
        """
        将活跃会话从当前设备迁移到目标设备

        流程：
        1. 序列化上下文
        2. 通过 cross_device_coordinator 持久化快照
        3. 通过 WebSocket 推送上下文到目标设备
        4. 更新设备映射

        Args:
            session_id: 要迁移的会话 ID
            target_device_id: 目标设备 ID

        Returns:
            是否成功
        """
        session = self._sessions.get(session_id)
        if not session:
            logger.warning(f"[SessionRoaming] 迁移失败，会话不存在: {session_id}")
            return False

        if session.state == SessionState.CLOSED:
            logger.warning(f"[SessionRoaming] 迁移失败，会话已关闭: {session_id}")
            return False

        old_device_id = session.device_id
        logger.info(
            f"[SessionRoaming] 开始迁移: session_id={session_id} "
            f"{old_device_id} -> {target_device_id}"
        )

        session.state = SessionState.MIGRATING

        # 保存原始状态用于回滚
        original_device_id = session.device_id

        try:
            # 步骤 1：序列化上下文
            context_snapshot = session.context.to_dict()

            # 步骤 2：持久化快照到磁盘
            self._persist_snapshot(session_id, context_snapshot)

            # 步骤 3：推送到目标设备（必须成功，否则回滚）
            push_ok = await self._push_context_to_device(
                target_device_id, session_id, context_snapshot
            )
            if not push_ok:
                # 推送失败：回滚所有状态变更
                logger.error(
                    f"[SessionRoaming] 推送上下文失败，迁移回滚: "
                    f"session_id={session_id} target={target_device_id}"
                )
                session.device_id = original_device_id
                session.state = SessionState.ACTIVE
                return False

            # 步骤 4：推送成功，提交状态变更（两阶段提交）
            if self._device_session_map.get(old_device_id) == session_id:
                del self._device_session_map[old_device_id]
            session.device_id = target_device_id
            self._device_session_map[target_device_id] = session_id
            session.state = SessionState.ACTIVE
            session.last_active = time.time()
            self._save_sessions_to_disk()

            logger.info(
                f"[SessionRoaming] 迁移成功: session_id={session_id} "
                f"-> device={target_device_id}"
            )

            # 触发回调
            if self._on_migrated:
                try:
                    result = self._on_migrated(session_id, old_device_id, target_device_id)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception as e:
                    logger.error(f"[SessionRoaming] 迁移回调异常: {e}")

            return True

        except Exception as e:
            logger.error(f"[SessionRoaming] 迁移异常: {e}")
            # 异常回滚：恢复原始设备 ID 和状态
            session.device_id = original_device_id
            session.state = SessionState.ACTIVE
            self._save_sessions_to_disk()
            return False

    async def auto_migrate_on_attention_shift(
        self,
        device_attention_map: Dict[str, bool],
    ):
        """
        根据用户注意力焦点变化自动迁移会话

        Args:
            device_attention_map: {device_id: is_focused}，True 表示该设备正在被用户关注
        """
        focused_devices = [d for d, f in device_attention_map.items() if f]
        if not focused_devices:
            return

        # 找出当前有活跃会话的设备
        for device_id, session_id in list(self._device_session_map.items()):
            session = self._sessions.get(session_id)
            if not session or session.state != SessionState.ACTIVE:
                continue

            # 当前设备没有获得注意力焦点，且有其它设备获得了注意力
            if device_id not in focused_devices:
                target = focused_devices[0]
                if target != device_id:
                    logger.info(
                        f"[SessionRoaming] 检测到注意力转移，自动迁移: "
                        f"{device_id} -> {target}"
                    )
                    await self.migrate_session(session_id, target)

    def set_migration_callback(
        self, callback: Callable[[str, str, str], Any]
    ):
        """
        设置迁移完成回调

        callback(session_id, old_device_id, new_device_id)
        """
        self._on_migrated = callback

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------

    def _persist_snapshot(self, session_id: str, snapshot: Dict):
        """将会话快照持久化到磁盘（替代纯内存存储，防止进程重启丢数据）。"""
        try:
            PERSISTENCE_DIR.mkdir(parents=True, exist_ok=True)
            snapshot_file = PERSISTENCE_DIR / f"snapshot_{session_id}.json"
            # 先写临时文件再原子重命名，防止写断
            tmp_file = snapshot_file.with_suffix(".tmp")
            tmp_file.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp_file.replace(snapshot_file)
            logger.debug(f"[SessionRoaming] 快照持久化到磁盘: {snapshot_file}")
        except Exception as e:
            logger.warning(f"[SessionRoaming] 快照持久化失败: {e}")

    def load_snapshot(self, session_id: str) -> Optional[Dict]:
        """从磁盘加载会话快照。"""
        try:
            snapshot_file = PERSISTENCE_DIR / f"snapshot_{session_id}.json"
            if snapshot_file.exists():
                return json.loads(snapshot_file.read_text(encoding="utf-8"))
            return None
        except Exception as e:
            logger.warning(f"[SessionRoaming] 加载快照失败: {e}")
            return None

    # ------------------------------------------------------------------
    # 推送上下文到目标设备
    # ------------------------------------------------------------------

    async def _push_context_to_device(
        self,
        device_id: str,
        session_id: str,
        context_snapshot: Dict,
    ) -> bool:
        """通过 device_communication.send_command 将会话上下文推送到目标设备"""
        try:
            from core.device_communication import device_comm
            result = await device_comm.send_command(
                device_id,
                "session_restore",
                {
                    "session_id": session_id,
                    "context": context_snapshot,
                },
                timeout=10.0,
            )
            return bool(result and result.get("success", True))
        except Exception as e:
            logger.warning(f"[SessionRoaming] 推送失败: device={device_id} error={e}")
            return False

    # ------------------------------------------------------------------
    # 查询接口
    # ------------------------------------------------------------------

    def list_sessions(self, state: Optional[SessionState] = None) -> List[Dict]:
        """列出所有（或指定状态的）会话"""
        sessions = self._sessions.values()
        if state is not None:
            sessions = [s for s in sessions if s.state == state]  # type: ignore
        return [s.to_dict() for s in sessions]  # type: ignore

    def get_stats(self) -> Dict:
        """获取统计信息"""
        total = len(self._sessions)
        by_state: Dict[str, int] = {}
        for s in self._sessions.values():
            by_state[s.state.value] = by_state.get(s.state.value, 0) + 1
        return {
            "total_sessions": total,
            "by_state": by_state,
            "device_session_map": dict(self._device_session_map),
        }


# 模块级单例
session_roaming = SessionRoamingManager()

__all__ = [
    "SessionRoamingManager",
    "Session",
    "SessionContext",
    "ConversationTurn",
    "SessionState",
    "session_roaming",
]
