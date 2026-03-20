"""
core.cognitive.long_term_memory — Cross-session Long-term Memory
================================================================

Provides :class:`LongTermMemory`: a persistent, cross-session memory store for
accumulated preferences, factual knowledge, and historical interaction patterns.

Design
------
- **Traceable** — every write records a ``trace_id``, ``session_id``, and
  ``timestamp`` so the origin of each piece of knowledge can be audited.
- **Namespaced** — keys are prefixed with a ``namespace`` (default
  ``"global"``) to prevent collision between different concern domains
  (e.g. ``"preferences"``, ``"facts"``, ``"skills"``).
- **In-memory by default** — suitable for the current single-process
  deployment.  The interface is designed so that a future persistent backend
  (Redis, SQLite, vector DB) can be swapped in without changing callers.
- **Distinct from working memory** — short-lived per-task context lives in
  :class:`~core.cognitive.working_memory.WorkingMemory`; only information
  worth retaining across sessions belongs here.

Configuration (``config.json``)
--------------------------------
- ``enable_cognitive_memory_split`` (bool, default ``true``) — master switch.
- ``long_term_memory_max_entries``  (int, default ``500``) — max total entries
  before oldest-by-timestamp eviction.

Usage::

    from core.cognitive.long_term_memory import get_long_term_memory

    ltm = get_long_term_memory()
    ltm.store(key="user_language", value="zh-CN", namespace="preferences",
              trace_id="trace_abc", session_id="sess_xyz")
    val = ltm.retrieve(key="user_language", namespace="preferences")
    history = ltm.retrieve_all(namespace="preferences")
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger("Galaxy.Cognitive.LongTermMemory")


class LongTermMemoryEntry:
    """Single entry in long-term memory.

    Attributes
    ----------
    key:        Entry key within its namespace.
    value:      Stored value (any JSON-serialisable type).
    namespace:  Logical grouping (``"preferences"``, ``"facts"``, etc.).
    trace_id:   Correlation ID of the write request.
    session_id: Session that produced this entry.
    timestamp:  Unix epoch seconds of the write.
    """

    __slots__ = ("key", "value", "namespace", "trace_id", "session_id", "timestamp")

    def __init__(
        self,
        key: str,
        value: Any,
        namespace: str,
        trace_id: str = "",
        session_id: str = "",
    ) -> None:
        self.key = key
        self.value = value
        self.namespace = namespace
        self.trace_id = trace_id
        self.session_id = session_id
        self.timestamp = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "namespace": self.namespace,
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
        }


class LongTermMemory:
    """Cross-session long-term memory store.

    Parameters
    ----------
    max_entries:
        Maximum total entries across all namespaces before oldest-entry eviction.
    enabled:
        When *False* the store is a no-op; callers fall back to other sources.
    """

    def __init__(
        self,
        max_entries: Optional[int] = None,
        enabled: Optional[bool] = None,
    ) -> None:
        cfg = self._read_config()
        self._max_entries = max_entries if max_entries is not None else int(
            cfg.get("long_term_memory_max_entries", 500)
        )
        self._enabled = enabled if enabled is not None else bool(
            cfg.get("enable_cognitive_memory_split", True)
        )
        # namespace → {key → LongTermMemoryEntry}
        self._store: Dict[str, Dict[str, LongTermMemoryEntry]] = {}
        # Flat list for eviction ordering
        self._insertion_order: List[tuple] = []  # (timestamp, namespace, key)
        self._lock = threading.Lock()
        logger.debug(
            "LongTermMemory init | max_entries=%d enabled=%s",
            self._max_entries,
            self._enabled,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def store(
        self,
        *,
        key: str,
        value: Any,
        namespace: str = "global",
        trace_id: str = "",
        session_id: str = "",
    ) -> None:
        """Store or overwrite a key in the given namespace.

        Parameters
        ----------
        key:        Entry key.
        value:      Value to store.  Must be JSON-serialisable.
        namespace:  Logical partition (default ``"global"``).
        trace_id:   Correlation ID for traceability.
        session_id: Session that produced this entry.
        """
        if not self._enabled:
            return
        entry = LongTermMemoryEntry(
            key=key,
            value=value,
            namespace=namespace,
            trace_id=trace_id,
            session_id=session_id,
        )
        with self._lock:
            if namespace not in self._store:
                self._store[namespace] = {}
            self._store[namespace][key] = entry
            self._insertion_order.append((entry.timestamp, namespace, key))
            self._evict_if_needed()
        logger.debug(
            "LongTermMemory.store ns=%s key=%s trace=%s", namespace, key, trace_id
        )

    def retrieve(
        self, *, key: str, namespace: str = "global", default: Any = None
    ) -> Any:
        """Retrieve the value stored under *key* in *namespace*.

        Returns *default* when disabled or key not found.
        """
        if not self._enabled:
            return default
        with self._lock:
            entry = self._store.get(namespace, {}).get(key)
        if entry is None:
            return default
        return entry.value

    def retrieve_entry(
        self, *, key: str, namespace: str = "global"
    ) -> Optional[Dict[str, Any]]:
        """Retrieve the full :class:`LongTermMemoryEntry` dict or *None*."""
        if not self._enabled:
            return None
        with self._lock:
            entry = self._store.get(namespace, {}).get(key)
        if entry is None:
            return None
        return entry.to_dict()

    def retrieve_all(self, *, namespace: str = "global") -> List[Dict[str, Any]]:
        """Return all entries in *namespace* sorted by timestamp (oldest first)."""
        if not self._enabled:
            return []
        with self._lock:
            ns_store = self._store.get(namespace, {})
            entries = sorted(ns_store.values(), key=lambda e: e.timestamp)
        return [e.to_dict() for e in entries]

    def forget(self, *, key: str, namespace: str = "global") -> bool:
        """Remove a single entry. Returns *True* if the key was present."""
        with self._lock:
            ns = self._store.get(namespace, {})
            if key in ns:
                del ns[key]
                return True
        return False

    def forget_namespace(self, *, namespace: str) -> int:
        """Remove all entries in *namespace*. Returns the number removed."""
        with self._lock:
            ns = self._store.pop(namespace, {})
        return len(ns)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def stats(self) -> Dict[str, Any]:
        """Return observable statistics."""
        with self._lock:
            total = sum(len(ns) for ns in self._store.values())
            namespaces = list(self._store.keys())
        return {
            "total_entries": total,
            "max_entries": self._max_entries,
            "namespaces": namespaces,
            "enabled": self._enabled,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _evict_if_needed(self) -> None:
        """Remove oldest entries when max_entries is exceeded (caller holds lock)."""
        total = sum(len(ns) for ns in self._store.values())
        while total > self._max_entries and self._insertion_order:
            _, ns, key = self._insertion_order.pop(0)
            if ns in self._store and key in self._store[ns]:
                del self._store[ns][key]
                total -= 1

    @staticmethod
    def _read_config() -> Dict[str, Any]:
        try:
            import json
            import pathlib

            return json.loads(
                (pathlib.Path(__file__).parents[2] / "config.json").read_text()
            )
        except Exception:
            return {}


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_ltm_instance: Optional[LongTermMemory] = None
_ltm_lock = threading.Lock()


def get_long_term_memory() -> LongTermMemory:
    """Return the process-wide :class:`LongTermMemory` singleton."""
    global _ltm_instance
    if _ltm_instance is None:
        with _ltm_lock:
            if _ltm_instance is None:
                _ltm_instance = LongTermMemory()
                logger.debug("LongTermMemory singleton initialised")
    return _ltm_instance


def reset_long_term_memory() -> None:
    """Reset the singleton (for testing only)."""
    global _ltm_instance
    with _ltm_lock:
        _ltm_instance = None
