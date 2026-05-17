#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/mesh/android_mesh_lifecycle_store.py
==========================================
PR-13：Android Mesh 生命周期上行事件存储

背景
----
Android GalaxyConnectionService.kt 在 ``parallel_subtask`` 路径中会依次发出
``mesh_join`` → ``mesh_result`` → ``mesh_leave`` 三类消息。此前 V2 侧未将这些
消息作为一级生命周期信号接收，导致 mesh 参与语义在 device/runtime 边界处丢失。

本模块关闭该间隙，提供：

1. :class:`AndroidMeshLifecycleEvent` — 单次事件的不可变数据记录（join/result/leave）。
2. :class:`AndroidMeshSessionRecord` — 对单个 mesh session 完整生命周期的追踪视图。
3. :class:`AndroidMeshLifecycleStore` — 线程安全的进程级单例存储，收纳所有
   Android 发出的 mesh 生命周期事件，支持按设备和 session 查询。
4. 模块级便捷函数 :func:`record_mesh_join` / :func:`record_mesh_result` /
   :func:`record_mesh_leave` / :func:`get_android_mesh_lifecycle_store`。

设计原则
--------
- **仅追加** — 事件一经记录不可修改；会话状态由事件序列推断。
- **线程安全** — 所有写操作持有 ``threading.Lock``。
- **降级安全** — 任何内部异常均被捕获并记录，不向调用方抛出。
- **容量有界** — 每个设备最多保留 :data:`_MAX_SESSIONS_PER_DEVICE` 个历史会话，
  避免无限增长。

公共 API
--------
常量
~~~~
:data:`ANDROID_MESH_LIFECYCLE_STORE_IS_AUTHORITY`

数据类
~~~~~~
:class:`AndroidMeshLifecycleEvent`
:class:`AndroidMeshSessionRecord`

存储类
~~~~~~
:class:`AndroidMeshLifecycleStore`

模块级函数
~~~~~~~~~~
:func:`get_android_mesh_lifecycle_store`
:func:`reset_android_mesh_lifecycle_store`
:func:`record_mesh_join`
:func:`record_mesh_result`
:func:`record_mesh_leave`
:func:`get_sessions_for_device`
:func:`get_all_active_sessions`
:func:`build_android_lifecycle_truth`
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

__all__ = [
    # 哨兵
    "ANDROID_MESH_LIFECYCLE_STORE_IS_AUTHORITY",
    # 枚举
    "AndroidMeshEventKind",
    "AndroidMeshSessionStatus",
    # 数据类
    "AndroidMeshLifecycleEvent",
    "AndroidMeshSessionRecord",
    # 存储类
    "AndroidMeshLifecycleStore",
    # 模块级函数
    "get_android_mesh_lifecycle_store",
    "reset_android_mesh_lifecycle_store",
    "record_mesh_join",
    "record_mesh_result",
    "record_mesh_leave",
    "get_sessions_for_device",
    "get_all_active_sessions",
    "build_android_lifecycle_truth",
]

logger = logging.getLogger("Galaxy.Mesh.AndroidLifecycle")

# ---------------------------------------------------------------------------
# 哨兵
# ---------------------------------------------------------------------------

ANDROID_MESH_LIFECYCLE_STORE_IS_AUTHORITY: str = (
    "ANDROID_MESH_LIFECYCLE_STORE_IS_AUTHORITY: "
    "core/mesh/android_mesh_lifecycle_store.py 是 Android 发出的 mesh 生命周期上行事件"
    "（mesh_join / mesh_result / mesh_leave）的权威持久化存储。"
    "它将 Android 侧 parallel_subtask 路径中的 mesh 参与语义转化为 V2 可追踪、"
    "可查询的一级运行时状态，并通过 /api/v1/mesh/android-lifecycle 真值端点暴露。"
    "PR-13."
)

# ---------------------------------------------------------------------------
# 容量限制
# ---------------------------------------------------------------------------

_MAX_SESSIONS_PER_DEVICE: int = 50
"""每个设备保留的最大历史 session 数量（超出时移除最旧记录）。"""

# ---------------------------------------------------------------------------
# 枚举
# ---------------------------------------------------------------------------


class AndroidMeshEventKind(str, Enum):
    """Android mesh 生命周期事件类型。"""

    JOIN = "mesh_join"
    """设备请求加入 mesh 协作会话。"""

    RESULT = "mesh_result"
    """设备上报 mesh 协作结果。"""

    LEAVE = "mesh_leave"
    """设备离开 mesh 协作会话。"""


class AndroidMeshSessionStatus(str, Enum):
    """Android mesh session 在 V2 侧的生命周期状态。"""

    JOINING = "joining"
    """已收到 mesh_join，等待 mesh_result 或 mesh_leave。"""

    ACTIVE = "active"
    """至少有一个 mesh_result 上报，session 仍处于活跃状态。"""

    LEFT = "left"
    """已收到 mesh_leave，session 终止。"""

    UNKNOWN = "unknown"
    """状态无法确定（无 join 事件）。"""


# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------


@dataclass
class AndroidMeshLifecycleEvent:
    """单次 Android mesh 生命周期事件的不可变记录。"""

    event_id: str
    """唯一事件标识符。"""

    kind: AndroidMeshEventKind
    """事件类型（join / result / leave）。"""

    device_id: str
    """发出事件的 Android 设备 ID。"""

    session_id: str
    """事件关联的 mesh session ID（来自消息 payload 或自动生成）。"""

    received_at: float
    """事件被 V2 收到的 Unix 时间戳。"""

    payload: Dict[str, Any] = field(default_factory=dict)
    """原始 payload（来自 Android 消息 payload 字段）。"""

    correlation_id: Optional[str] = None
    """关联 Android 消息 ID（用于追踪）。"""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "kind": self.kind.value,
            "device_id": self.device_id,
            "session_id": self.session_id,
            "received_at": self.received_at,
            "payload": self.payload,
            "correlation_id": self.correlation_id,
        }


@dataclass
class AndroidMeshSessionRecord:
    """V2 侧对单个 Android mesh session 完整生命周期的追踪视图。"""

    session_id: str
    """mesh session 标识符。"""

    device_id: str
    """发起该 session 的 Android 设备 ID。"""

    status: AndroidMeshSessionStatus
    """session 当前状态。"""

    join_event: Optional[AndroidMeshLifecycleEvent] = None
    """最近收到的 mesh_join 事件。"""

    result_events: List[AndroidMeshLifecycleEvent] = field(default_factory=list)
    """按时间顺序收到的 mesh_result 事件列表。"""

    leave_event: Optional[AndroidMeshLifecycleEvent] = None
    """mesh_leave 事件（存在时表示 session 已终止）。"""

    created_at: float = field(default_factory=time.time)
    """record 首次创建时间。"""

    updated_at: float = field(default_factory=time.time)
    """record 最近更新时间。"""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "device_id": self.device_id,
            "status": self.status.value,
            "join_event": self.join_event.to_dict() if self.join_event else None,
            "result_events": [e.to_dict() for e in self.result_events],
            "leave_event": self.leave_event.to_dict() if self.leave_event else None,
            "result_count": len(self.result_events),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# ---------------------------------------------------------------------------
# 存储类
# ---------------------------------------------------------------------------


class AndroidMeshLifecycleStore:
    """Android mesh 生命周期事件的线程安全进程级存储。

    该类维护：

    * ``_sessions`` — 按 ``session_id`` 索引的 :class:`AndroidMeshSessionRecord` 字典。
    * ``_device_sessions`` — 按 ``device_id`` 索引的 ``session_id`` 有序列表。

    所有写操作均由 :class:`threading.Lock` 保护。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: Dict[str, AndroidMeshSessionRecord] = {}
        # device_id -> [session_id, ...] (按创建顺序)
        self._device_sessions: Dict[str, List[str]] = {}

    # ------------------------------------------------------------------
    # 内部辅助（私有）
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_session_id(
        explicit_id: Optional[str],
        device_id: str,
        payload: Dict[str, Any],
    ) -> str:
        """从显式参数或 payload 字段中解析 session_id，无法提取时自动生成。

        优先级：explicit_id > payload.session_id > payload.mesh_session_id > 自动生成。
        """
        return str(
            explicit_id
            or payload.get("session_id")
            or payload.get("mesh_session_id")
            or f"amesh_{device_id}_{int(time.time() * 1000)}"
        )

    def _register_device_session(self, device_id: str, session_id: str) -> None:
        """（需在持有锁的情况下调用）将 session_id 追加到设备索引，并按容量上限清理最旧记录。"""
        slist = self._device_sessions.setdefault(device_id, [])
        slist.append(session_id)
        if len(slist) > _MAX_SESSIONS_PER_DEVICE:
            oldest = slist.pop(0)
            self._sessions.pop(oldest, None)

    # ------------------------------------------------------------------
    # 核心写入方法
    # ------------------------------------------------------------------

    def record_join(
        self,
        *,
        device_id: str,
        session_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None,
    ) -> AndroidMeshLifecycleEvent:
        """记录 mesh_join 事件，创建或更新对应 session record。

        Parameters
        ----------
        device_id:
            发出 mesh_join 的 Android 设备 ID。
        session_id:
            mesh session 标识符。如果消息未携带，则自动生成一个。
        payload:
            Android 消息的 payload 字段。
        correlation_id:
            Android 消息 ID（用于追踪）。

        Returns
        -------
        AndroidMeshLifecycleEvent
            记录的事件对象。
        """
        payload = payload or {}
        session_id = self._resolve_session_id(session_id, device_id, payload)

        event = AndroidMeshLifecycleEvent(
            event_id=str(uuid.uuid4()),
            kind=AndroidMeshEventKind.JOIN,
            device_id=device_id,
            session_id=session_id,
            received_at=time.time(),
            payload=payload,
            correlation_id=correlation_id,
        )

        with self._lock:
            if session_id not in self._sessions:
                record = AndroidMeshSessionRecord(
                    session_id=session_id,
                    device_id=device_id,
                    status=AndroidMeshSessionStatus.JOINING,
                    join_event=event,
                )
                self._sessions[session_id] = record
                self._register_device_session(device_id, session_id)
            else:
                record = self._sessions[session_id]
                record.join_event = event
                record.status = AndroidMeshSessionStatus.JOINING
                record.updated_at = time.time()

        logger.info(
            "AndroidMeshLifecycleStore: mesh_join recorded device_id=%s session_id=%s",
            device_id,
            session_id,
        )
        return event

    def record_result(
        self,
        *,
        device_id: str,
        session_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None,
    ) -> AndroidMeshLifecycleEvent:
        """记录 mesh_result 事件，更新对应 session record 状态为 ACTIVE。

        如果对应 session 不存在（未收到先前的 join），则自动创建。

        Parameters
        ----------
        device_id:
            发出 mesh_result 的 Android 设备 ID。
        session_id:
            mesh session 标识符。
        payload:
            Android 消息的 payload 字段（包含结果数据）。
        correlation_id:
            Android 消息 ID。

        Returns
        -------
        AndroidMeshLifecycleEvent
        """
        payload = payload or {}
        session_id = self._resolve_session_id(session_id, device_id, payload)

        event = AndroidMeshLifecycleEvent(
            event_id=str(uuid.uuid4()),
            kind=AndroidMeshEventKind.RESULT,
            device_id=device_id,
            session_id=session_id,
            received_at=time.time(),
            payload=payload,
            correlation_id=correlation_id,
        )

        with self._lock:
            if session_id not in self._sessions:
                # 没有先前的 join；创建 UNKNOWN 状态 session 并将其推进为 ACTIVE
                record = AndroidMeshSessionRecord(
                    session_id=session_id,
                    device_id=device_id,
                    status=AndroidMeshSessionStatus.ACTIVE,
                )
                self._sessions[session_id] = record
                self._register_device_session(device_id, session_id)
            else:
                record = self._sessions[session_id]

            record.result_events.append(event)
            record.status = AndroidMeshSessionStatus.ACTIVE
            record.updated_at = time.time()

        logger.info(
            "AndroidMeshLifecycleStore: mesh_result recorded device_id=%s session_id=%s",
            device_id,
            session_id,
        )
        return event

    def record_leave(
        self,
        *,
        device_id: str,
        session_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None,
    ) -> AndroidMeshLifecycleEvent:
        """记录 mesh_leave 事件，将对应 session record 状态更新为 LEFT。

        Parameters
        ----------
        device_id:
            发出 mesh_leave 的 Android 设备 ID。
        session_id:
            mesh session 标识符。
        payload:
            Android 消息的 payload 字段。
        correlation_id:
            Android 消息 ID。

        Returns
        -------
        AndroidMeshLifecycleEvent
        """
        payload = payload or {}
        if not session_id:
            # 如果没有显式 session_id，尝试找到该设备最近的非终止 session
            with self._lock:
                session_id = self._find_latest_active_session_for_device(device_id)
            if not session_id:
                session_id = self._resolve_session_id(None, device_id, payload)

        event = AndroidMeshLifecycleEvent(
            event_id=str(uuid.uuid4()),
            kind=AndroidMeshEventKind.LEAVE,
            device_id=device_id,
            session_id=session_id,
            received_at=time.time(),
            payload=payload,
            correlation_id=correlation_id,
        )

        with self._lock:
            if session_id not in self._sessions:
                record = AndroidMeshSessionRecord(
                    session_id=session_id,
                    device_id=device_id,
                    status=AndroidMeshSessionStatus.LEFT,
                    leave_event=event,
                )
                self._sessions[session_id] = record
                self._register_device_session(device_id, session_id)
            else:
                record = self._sessions[session_id]
                record.leave_event = event
                record.status = AndroidMeshSessionStatus.LEFT
                record.updated_at = time.time()

        logger.info(
            "AndroidMeshLifecycleStore: mesh_leave recorded device_id=%s session_id=%s",
            device_id,
            session_id,
        )
        return event

    # ------------------------------------------------------------------
    # 查询方法
    # ------------------------------------------------------------------

    def get_session(self, session_id: str) -> Optional[AndroidMeshSessionRecord]:
        """按 session_id 获取 session record。"""
        with self._lock:
            return self._sessions.get(session_id)

    def get_sessions_for_device(
        self,
        device_id: str,
        *,
        include_terminal: bool = True,
    ) -> List[AndroidMeshSessionRecord]:
        """获取某设备的所有 session records（按创建顺序）。

        Parameters
        ----------
        device_id:
            Android 设备 ID。
        include_terminal:
            若为 False，则只返回非 LEFT 状态的 session。
        """
        with self._lock:
            sids = list(self._device_sessions.get(device_id, []))

        records = []
        for sid in sids:
            with self._lock:
                rec = self._sessions.get(sid)
            if rec is None:
                continue
            if not include_terminal and rec.status == AndroidMeshSessionStatus.LEFT:
                continue
            records.append(rec)
        return records

    def get_all_active_sessions(self) -> List[AndroidMeshSessionRecord]:
        """获取所有非 LEFT 状态的 session records。"""
        with self._lock:
            return [
                rec
                for rec in self._sessions.values()
                if rec.status != AndroidMeshSessionStatus.LEFT
            ]

    def get_all_sessions(self) -> List[AndroidMeshSessionRecord]:
        """获取全部 session records（含已终止）。"""
        with self._lock:
            return list(self._sessions.values())

    def session_count(self) -> int:
        """返回当前存储的 session 总数。"""
        with self._lock:
            return len(self._sessions)

    def active_session_count(self) -> int:
        """返回活跃（非 LEFT）session 数量。"""
        return len(self.get_all_active_sessions())

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    def _find_latest_active_session_for_device(self, device_id: str) -> Optional[str]:
        """（需在持有锁的情况下调用）返回该设备最近的非 LEFT session id。"""
        sids = self._device_sessions.get(device_id, [])
        for sid in reversed(sids):
            rec = self._sessions.get(sid)
            if rec and rec.status != AndroidMeshSessionStatus.LEFT:
                return sid
        return None


# ---------------------------------------------------------------------------
# 模块级单例管理
# ---------------------------------------------------------------------------

_store_singleton: Optional[AndroidMeshLifecycleStore] = None
_store_lock = threading.Lock()


def get_android_mesh_lifecycle_store() -> AndroidMeshLifecycleStore:
    """返回进程级 :class:`AndroidMeshLifecycleStore` 单例。"""
    global _store_singleton
    if _store_singleton is None:
        with _store_lock:
            if _store_singleton is None:
                _store_singleton = AndroidMeshLifecycleStore()
    return _store_singleton


def reset_android_mesh_lifecycle_store() -> None:
    """重置模块级单例 — **仅供测试使用**。"""
    global _store_singleton
    with _store_lock:
        _store_singleton = None


# ---------------------------------------------------------------------------
# 模块级便捷函数
# ---------------------------------------------------------------------------


def record_mesh_join(
    device_id: str,
    *,
    session_id: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
    correlation_id: Optional[str] = None,
) -> Optional[AndroidMeshLifecycleEvent]:
    """记录 mesh_join 事件（模块级快捷入口）。

    失败时记录日志并返回 ``None``，不向调用方抛出异常。
    """
    try:
        store = get_android_mesh_lifecycle_store()
        return store.record_join(
            device_id=device_id,
            session_id=session_id,
            payload=payload,
            correlation_id=correlation_id,
        )
    except Exception as exc:
        logger.warning("record_mesh_join: non-fatal error: device_id=%s %s", device_id, exc)
        return None


def record_mesh_result(
    device_id: str,
    *,
    session_id: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
    correlation_id: Optional[str] = None,
) -> Optional[AndroidMeshLifecycleEvent]:
    """记录 mesh_result 事件（模块级快捷入口）。

    失败时记录日志并返回 ``None``，不向调用方抛出异常。
    """
    try:
        store = get_android_mesh_lifecycle_store()
        return store.record_result(
            device_id=device_id,
            session_id=session_id,
            payload=payload,
            correlation_id=correlation_id,
        )
    except Exception as exc:
        logger.warning("record_mesh_result: non-fatal error: device_id=%s %s", device_id, exc)
        return None


def record_mesh_leave(
    device_id: str,
    *,
    session_id: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
    correlation_id: Optional[str] = None,
) -> Optional[AndroidMeshLifecycleEvent]:
    """记录 mesh_leave 事件（模块级快捷入口）。

    失败时记录日志并返回 ``None``，不向调用方抛出异常。
    """
    try:
        store = get_android_mesh_lifecycle_store()
        return store.record_leave(
            device_id=device_id,
            session_id=session_id,
            payload=payload,
            correlation_id=correlation_id,
        )
    except Exception as exc:
        logger.warning("record_mesh_leave: non-fatal error: device_id=%s %s", device_id, exc)
        return None


def get_sessions_for_device(
    device_id: str,
    *,
    include_terminal: bool = True,
) -> List[AndroidMeshSessionRecord]:
    """获取某设备的所有 session records（模块级快捷入口）。"""
    try:
        return get_android_mesh_lifecycle_store().get_sessions_for_device(
            device_id, include_terminal=include_terminal
        )
    except Exception as exc:
        logger.warning("get_sessions_for_device: %s", exc)
        return []


def get_all_active_sessions() -> List[AndroidMeshSessionRecord]:
    """获取所有活跃 session records（模块级快捷入口）。"""
    try:
        return get_android_mesh_lifecycle_store().get_all_active_sessions()
    except Exception as exc:
        logger.warning("get_all_active_sessions: %s", exc)
        return []


def build_android_lifecycle_truth() -> Dict[str, Any]:
    """构建供运营端消费的 Android mesh 生命周期真值快照。

    返回的字典包含：

    * ``active_session_count`` — 当前活跃（非 LEFT）session 数量。
    * ``total_session_count`` — 存储中的 session 总数。
    * ``active_sessions`` — 活跃 session 的序列化列表。
    * ``_source`` — 模块标识。
    * ``_timestamp`` — 快照时间戳。
    """
    try:
        store = get_android_mesh_lifecycle_store()
        active = store.get_all_active_sessions()
        total = store.session_count()
        return {
            "active_session_count": len(active),
            "total_session_count": total,
            "active_sessions": [s.to_dict() for s in active],
            "_source": "core.mesh.android_mesh_lifecycle_store.build_android_lifecycle_truth",
            "_timestamp": time.time(),
        }
    except Exception as exc:
        logger.warning("build_android_lifecycle_truth: %s", exc)
        return {
            "active_session_count": 0,
            "total_session_count": 0,
            "active_sessions": [],
            "_source": "core.mesh.android_mesh_lifecycle_store.build_android_lifecycle_truth",
            "_error": str(exc),
            "_timestamp": time.time(),
        }
