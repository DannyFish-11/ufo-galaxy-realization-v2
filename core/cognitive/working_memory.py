"""
core.cognitive.working_memory — Per-task Working Memory
=======================================================

Provides :class:`WorkingMemory`: a bounded, short-lived memory store for the
**current task or session context**.  Working memory holds the most recent
conversational turns, tool results, and ephemeral state that are relevant
during active task execution but should not persist to long-term storage.

Design
------
- Capacity-bounded (FIFO eviction when full).
- Keyed by ``session_id`` so multiple concurrent sessions can co-exist.
- All entries carry a ``trace_id`` so they can be correlated with audit events.
- Distinct from :class:`~core.cognitive.long_term_memory.LongTermMemory`
  (which stores cross-session preferences and accumulated knowledge).

Configuration (``config.json``)
--------------------------------
- ``working_memory_capacity``  (int, default ``20``) — max entries per session.
- ``enable_cognitive_memory_split`` (bool, default ``true``) — master switch; when
  *False* this module returns empty results so callers fall back to legacy
  ``_session_memory``.

Usage::

    from core.cognitive.working_memory import get_working_memory

    wm = get_working_memory()
    wm.add(session_id="sess_abc", role="user", content="打开微信",
           trace_id="trace_123")
    entries = wm.get(session_id="sess_abc")
    wm.clear(session_id="sess_abc")
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger("Galaxy.Cognitive.WorkingMemory")


class WorkingMemoryEntry:
    """Single entry in working memory.

    Attributes
    ----------
    role:       ``"user"`` | ``"assistant"`` | ``"tool"`` | ``"system"``.
    content:    Text content of the turn.
    trace_id:   Correlation ID from the originating request.
    metadata:   Opaque extra fields (tool name, device_id, etc.).
    timestamp:  Unix epoch seconds of insertion.
    """

    __slots__ = ("role", "content", "trace_id", "metadata", "timestamp")

    def __init__(
        self,
        role: str,
        content: str,
        trace_id: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.role = role
        self.content = content
        self.trace_id = trace_id
        self.metadata: Dict[str, Any] = metadata or {}
        self.timestamp = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "trace_id": self.trace_id,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
        }


class WorkingMemory:
    """Bounded per-session working memory store.

    Parameters
    ----------
    capacity:
        Maximum entries per session before FIFO eviction.
    enabled:
        When *False* the store is a no-op; callers fall back to legacy memory.
    """

    def __init__(
        self,
        capacity: Optional[int] = None,
        enabled: Optional[bool] = None,
    ) -> None:
        cfg = self._read_config()
        self._capacity = capacity if capacity is not None else int(cfg.get("working_memory_capacity", 20))
        self._enabled = enabled if enabled is not None else bool(cfg.get("enable_cognitive_memory_split", True))
        # session_id → deque of WorkingMemoryEntry
        self._store: Dict[str, Deque[WorkingMemoryEntry]] = {}
        self._lock = threading.Lock()
        logger.debug("WorkingMemory init | capacity=%d enabled=%s", self._capacity, self._enabled)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add(
        self,
        *,
        session_id: str,
        role: str,
        content: str,
        trace_id: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Add an entry to the working memory for *session_id*.

        Evicts the oldest entry when the capacity is exceeded.
        """
        if not self._enabled:
            return
        entry = WorkingMemoryEntry(role=role, content=content, trace_id=trace_id, metadata=metadata)
        with self._lock:
            if session_id not in self._store:
                self._store[session_id] = deque(maxlen=self._capacity)
            self._store[session_id].append(entry)
        logger.debug("WorkingMemory.add session=%s role=%s trace=%s", session_id, role, trace_id)

    def get(self, *, session_id: str, last_n: Optional[int] = None) -> List[Dict[str, Any]]:
        """Return working memory entries for *session_id* as a list of dicts.

        融合(域3):对话轮次的唯一属主是 SessionManager —— 若它认识该会话,
        直接读它的历史(映射成本地 entry 形状),本模块不再保存对话轮次的副本。
        本地 deque 只服务【易失 scratch 会话】(如 ambient 的观察理由滚动日志,
        高频写、刻意不落盘),SessionManager 不认识的会话才走它。

        Parameters
        ----------
        session_id:
            The session to retrieve.
        last_n:
            If provided, return only the *last_n* most recent entries.

        Returns
        -------
        list:
            Empty list when disabled or when *session_id* has no entries.
        """
        if not self._enabled:
            return []
        # 对话会话 → 读唯一属主 SessionManager(内存 dict 读,无 IO)。
        try:
            from core.session_manager import get_session_manager

            sm = get_session_manager()
            if sm.get_session(session_id) is not None:
                history = sm.get_full_history(session_id)
                if last_n is not None:
                    history = history[-last_n:]
                return [
                    {
                        "role": m.get("role", ""),
                        "content": m.get("content", ""),
                        "trace_id": (m.get("metadata") or {}).get("trace_id", ""),
                        "ts": m.get("timestamp", 0.0),
                        "metadata": {
                            **(m.get("metadata") or {}),
                            **({"device_id": m["device_id"]} if m.get("device_id") else {}),
                        },
                    }
                    for m in history
                ]
        except Exception as exc:  # noqa: BLE001 — SM 不可用时退回本地 deque
            logger.debug("WorkingMemory.get SM 读取失败,退本地: %s", exc)
        with self._lock:
            buf = self._store.get(session_id)
            if not buf:
                return []
            entries = list(buf)
        if last_n is not None:
            entries = entries[-last_n:]
        return [e.to_dict() for e in entries]

    def clear(self, *, session_id: str) -> None:
        """Remove all working memory entries for *session_id*."""
        with self._lock:
            self._store.pop(session_id, None)
        logger.debug("WorkingMemory.clear session=%s", session_id)

    def active_sessions(self) -> List[str]:
        """Return a list of session IDs that have working memory entries."""
        with self._lock:
            return list(self._store.keys())

    @property
    def enabled(self) -> bool:
        return self._enabled

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _read_config() -> Dict[str, Any]:
        try:
            import json
            import pathlib

            return json.loads((pathlib.Path(__file__).parents[2] / "config.json").read_text())
        except Exception:
            return {}


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_wm_instance: Optional[WorkingMemory] = None
_wm_lock = threading.Lock()


def get_working_memory() -> WorkingMemory:
    """Return the process-wide :class:`WorkingMemory` singleton."""
    global _wm_instance
    if _wm_instance is None:
        with _wm_lock:
            if _wm_instance is None:
                _wm_instance = WorkingMemory()
                logger.debug("WorkingMemory singleton initialised")
    return _wm_instance


def reset_working_memory() -> None:
    """Reset the singleton (for testing only)."""
    global _wm_instance
    with _wm_lock:
        _wm_instance = None
