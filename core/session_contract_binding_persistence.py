#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/session_contract_binding_persistence.py
============================================
Durable Persistence for Session / Contract / Binding / Delegated Flow
Metadata — PR-D2 (cross-device flow durability gap closure).

Background
----------
``AttachedRuntimeSessionRuntime``, ``DelegatedHandoffContractRuntime``,
``AndroidRuntimeDispatchBindingRuntime``, and ``DelegatedFlowEntityRuntime``
are in-process ring-buffer singletons.  They provide fast, in-process access
to the most recent session attachment records, handoff contracts, dispatch
bindings, and delegated flow entities.  Prior to this module, all four were
**purely in-memory**: a process restart, crash, or OOM silently discarded
every pending record, making it impossible to recover:

- attachment state (which devices are currently attached)
- handoff contract truth (which contracts are draft/sealed/dispatched)
- dispatch binding truth (which bindings are currently active)
- delegated flow metadata (flow phase, object mappings, lineage)

This module closes that durability gap by providing four file-backed,
thread-safe, atomic-write persistence stores — one per ring-buffer — that
can be used to snapshot and restore the runtime state of each.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Mirrors TaskLifecyclePersistenceStore** — same write-then-rename atomic
  write pattern, same per-store :class:`threading.Lock`, same
  ``save()`` / ``load()`` / ``clear()`` API surface.
- **Snapshot-based** — each store persists a full point-in-time snapshot of
  all records from the corresponding ring-buffer.  On recovery, the snapshot
  is loaded and used to re-populate the ring-buffer.
- **Graceful degradation** — every function returns a valid result even when
  the backing store is unavailable or contains bad data.
- **Ring-buffer preserved** — ring-buffers remain the in-process fast access
  layer.  The durable stores are the recovery and truth foundation.
- **Singleton singletons** — each store has a process-level singleton that
  can be overridden in tests via ``reset_X_store()``.

Public API
----------
Sentinels::

    SESSION_CONTRACT_BINDING_PERSISTENCE_AUTHORITY
    SESSION_PERSISTENCE_GAP_CLOSURE_SENTINEL
    CONTRACT_PERSISTENCE_GAP_CLOSURE_SENTINEL
    BINDING_PERSISTENCE_GAP_CLOSURE_SENTINEL
    FLOW_PERSISTENCE_GAP_CLOSURE_SENTINEL
    DURABLE_STORE_IS_RECOVERY_FOUNDATION_POLICY
    RING_BUFFER_REMAINS_FAST_ACCESS_POLICY

Data classes::

    AttachedSessionSnapshotRecord
    HandoffContractSnapshotRecord
    DispatchBindingSnapshotRecord
    DelegatedFlowSnapshotRecord

Store classes::

    AttachedSessionPersistenceStore
    HandoffContractPersistenceStore
    DispatchBindingPersistenceStore
    DelegatedFlowPersistenceStore

Singleton accessors::

    get_attached_session_store(store_path) -> AttachedSessionPersistenceStore
    reset_attached_session_store()
    get_handoff_contract_store(store_path) -> HandoffContractPersistenceStore
    reset_handoff_contract_store()
    get_dispatch_binding_store(store_path) -> DispatchBindingPersistenceStore
    reset_dispatch_binding_store()
    get_delegated_flow_store(store_path) -> DelegatedFlowPersistenceStore
    reset_delegated_flow_store()

Convenience / recovery functions::

    save_attached_session_snapshot(records, *, store) -> AttachedSessionSnapshotRecord
    load_attached_session_snapshot(*, store) -> Optional[AttachedSessionSnapshotRecord]
    restore_attached_sessions_from_snapshot(*, store, runtime) -> int
    save_handoff_contract_snapshot(records, *, store) -> HandoffContractSnapshotRecord
    load_handoff_contract_snapshot(*, store) -> Optional[HandoffContractSnapshotRecord]
    restore_handoff_contracts_from_snapshot(*, store, runtime) -> int
    save_dispatch_binding_snapshot(records, *, store) -> DispatchBindingSnapshotRecord
    load_dispatch_binding_snapshot(*, store) -> Optional[DispatchBindingSnapshotRecord]
    restore_dispatch_bindings_from_snapshot(*, store, runtime) -> int
    save_delegated_flow_snapshot(records, *, store) -> DelegatedFlowSnapshotRecord
    load_delegated_flow_snapshot(*, store) -> Optional[DelegatedFlowSnapshotRecord]
    restore_delegated_flows_from_snapshot(*, store, runtime) -> int
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

__all__ = [
    # Sentinels
    "SESSION_CONTRACT_BINDING_PERSISTENCE_AUTHORITY",
    "SESSION_PERSISTENCE_GAP_CLOSURE_SENTINEL",
    "CONTRACT_PERSISTENCE_GAP_CLOSURE_SENTINEL",
    "BINDING_PERSISTENCE_GAP_CLOSURE_SENTINEL",
    "FLOW_PERSISTENCE_GAP_CLOSURE_SENTINEL",
    "DURABLE_STORE_IS_RECOVERY_FOUNDATION_POLICY",
    "RING_BUFFER_REMAINS_FAST_ACCESS_POLICY",
    # Snapshot data classes
    "AttachedSessionSnapshotRecord",
    "HandoffContractSnapshotRecord",
    "DispatchBindingSnapshotRecord",
    "DelegatedFlowSnapshotRecord",
    # Store classes
    "AttachedSessionPersistenceStore",
    "HandoffContractPersistenceStore",
    "DispatchBindingPersistenceStore",
    "DelegatedFlowPersistenceStore",
    # Singleton accessors
    "get_attached_session_store",
    "reset_attached_session_store",
    "get_handoff_contract_store",
    "reset_handoff_contract_store",
    "get_dispatch_binding_store",
    "reset_dispatch_binding_store",
    "get_delegated_flow_store",
    "reset_delegated_flow_store",
    # Convenience / recovery functions
    "save_attached_session_snapshot",
    "load_attached_session_snapshot",
    "restore_attached_sessions_from_snapshot",
    "save_handoff_contract_snapshot",
    "load_handoff_contract_snapshot",
    "restore_handoff_contracts_from_snapshot",
    "save_dispatch_binding_snapshot",
    "load_dispatch_binding_snapshot",
    "restore_dispatch_bindings_from_snapshot",
    "save_delegated_flow_snapshot",
    "load_delegated_flow_snapshot",
    "restore_delegated_flows_from_snapshot",
]

logger = logging.getLogger("Galaxy.SessionContractBindingPersistence")

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

SESSION_CONTRACT_BINDING_PERSISTENCE_AUTHORITY: str = (
    "SESSION_CONTRACT_BINDING_PERSISTENCE_AUTHORITY: "
    "core/session_contract_binding_persistence.py is the canonical durable "
    "snapshot layer for attached-runtime sessions, delegated handoff contracts, "
    "Android dispatch bindings, and delegated flow entities.  It does not replace "
    "the ring-buffer runtime singletons; it provides durable backing so state "
    "can be reconstructed after process restart. (PR-D2)"
)

SESSION_PERSISTENCE_GAP_CLOSURE_SENTINEL: str = (
    "SESSION_PERSISTENCE_GAP_CLOSURE::attached-session-durability-pr-d2-v1: "
    "This module directly closes the attached-runtime-session durability gap — "
    "attachment state (which devices are currently attached and in what lifecycle "
    "state) is now persisted to disk and can be recovered after V2 process restart."
)

CONTRACT_PERSISTENCE_GAP_CLOSURE_SENTINEL: str = (
    "CONTRACT_PERSISTENCE_GAP_CLOSURE::handoff-contract-durability-pr-d2-v1: "
    "This module directly closes the handoff-contract durability gap — contract "
    "truth (which contracts are draft/sealed/dispatched) is now persisted to disk "
    "and can be recovered after V2 process restart."
)

BINDING_PERSISTENCE_GAP_CLOSURE_SENTINEL: str = (
    "BINDING_PERSISTENCE_GAP_CLOSURE::dispatch-binding-durability-pr-d2-v1: "
    "This module directly closes the dispatch-binding durability gap — binding "
    "truth (which bindings are currently active and which Android runtime surface "
    "they target) is now persisted to disk and can be recovered after process restart."
)

FLOW_PERSISTENCE_GAP_CLOSURE_SENTINEL: str = (
    "FLOW_PERSISTENCE_GAP_CLOSURE::delegated-flow-durability-pr-d2-v1: "
    "This module directly closes the delegated-flow-metadata durability gap — "
    "flow phase, object mappings, and lineage are now persisted to disk and can "
    "be recovered after V2 process restart."
)

DURABLE_STORE_IS_RECOVERY_FOUNDATION_POLICY: str = (
    "POLICY::DURABLE_STORE_IS_RECOVERY_FOUNDATION: The durable persistence stores "
    "introduced by this module are the canonical foundation for post-restart recovery "
    "of session / contract / binding / flow state.  Callers MUST NOT rely solely on "
    "the in-memory ring buffers for continuity guarantees.  On startup, each store "
    "should be loaded and its snapshot used to re-populate the corresponding ring "
    "buffer before accepting new work.  (PR-D2)"
)

RING_BUFFER_REMAINS_FAST_ACCESS_POLICY: str = (
    "POLICY::RING_BUFFER_REMAINS_FAST_ACCESS: The in-process ring-buffer singletons "
    "(AttachedRuntimeSessionRuntime, DelegatedHandoffContractRuntime, "
    "AndroidRuntimeDispatchBindingRuntime, DelegatedFlowEntityRuntime) remain the "
    "canonical fast-access / observability layer.  Writes MUST be directed to both "
    "the ring buffer AND the durable store so that in-process reads remain low-latency "
    "while the durable store provides recovery truth.  (PR-D2)"
)

# ---------------------------------------------------------------------------
# Default store paths
# ---------------------------------------------------------------------------

_DATA_DIR = os.environ.get("GALAXY_DATA_DIR", "data")

_DEFAULT_SESSION_STORE_PATH = os.path.join(
    _DATA_DIR, "attached_session_snapshot.json"
)
_DEFAULT_CONTRACT_STORE_PATH = os.path.join(
    _DATA_DIR, "handoff_contract_snapshot.json"
)
_DEFAULT_BINDING_STORE_PATH = os.path.join(
    _DATA_DIR, "dispatch_binding_snapshot.json"
)
_DEFAULT_FLOW_STORE_PATH = os.path.join(
    _DATA_DIR, "delegated_flow_snapshot.json"
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _atomic_save(store_path: str, payload: str, lock: threading.Lock) -> bool:
    """Write *payload* to *store_path* atomically under *lock*.

    Uses write-to-temp-then-rename so a partial write never corrupts the
    previous good snapshot.

    Returns True on success; False on failure (error is logged).
    """
    store_dir = os.path.dirname(os.path.abspath(store_path))
    try:
        with lock:
            fd, tmp_path = tempfile.mkstemp(dir=store_dir, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(payload)
                os.replace(tmp_path, store_path)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        return True
    except Exception as exc:
        logger.warning("SessionContractBindingPersistence: failed to save %s: %s", store_path, exc)
        return False


def _atomic_load(store_path: str, lock: threading.Lock) -> Optional[Dict[str, Any]]:
    """Load a JSON dict from *store_path* under *lock*.

    Returns the parsed dict, or None if the file does not exist or cannot
    be parsed.
    """
    with lock:
        if not os.path.exists(store_path):
            return None
        try:
            with open(store_path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception as exc:
            logger.warning(
                "SessionContractBindingPersistence: failed to load %s: %s", store_path, exc
            )
            return None


def _atomic_clear(store_path: str, lock: threading.Lock) -> bool:
    """Delete *store_path* under *lock*.

    Safe to call when the file does not exist.  Returns True on success
    (or when the file did not exist); False on error.
    """
    with lock:
        if not os.path.exists(store_path):
            return True
        try:
            os.unlink(store_path)
            return True
        except Exception as exc:
            logger.warning(
                "SessionContractBindingPersistence: failed to clear %s: %s", store_path, exc
            )
            return False


def _ensure_store_dir(store_path: str) -> None:
    """Create the directory for *store_path* if it does not exist."""
    try:
        os.makedirs(os.path.dirname(os.path.abspath(store_path)), exist_ok=True)
    except Exception as exc:
        logger.warning(
            "SessionContractBindingPersistence: could not create store directory for %s: %s",
            store_path,
            exc,
        )


# ---------------------------------------------------------------------------
# AttachedSessionSnapshotRecord
# ---------------------------------------------------------------------------


@dataclass
class AttachedSessionSnapshotRecord:
    """Point-in-time durable snapshot of attached-runtime session records.

    Parameters
    ----------
    snapshot_id:
        Unique identifier for this snapshot.
    created_at:
        Unix epoch seconds when the snapshot was written.
    process_pid:
        PID of the process that wrote the snapshot.
    records:
        List of serialised :class:`~core.attached_runtime_session
        .AttachedRuntimeSessionRecord` dicts.
    """

    snapshot_id: str = field(
        default_factory=lambda: f"ass_{uuid.uuid4().hex[:12]}"
    )
    created_at: float = field(default_factory=time.time)
    process_pid: int = field(default_factory=os.getpid)
    records: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a JSON-safe dict."""
        return {
            "snapshot_id": self.snapshot_id,
            "created_at": self.created_at,
            "process_pid": self.process_pid,
            "records": list(self.records),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AttachedSessionSnapshotRecord":
        """Reconstruct from a serialised dict."""
        return cls(
            snapshot_id=d.get("snapshot_id", f"ass_{uuid.uuid4().hex[:12]}"),
            created_at=float(d.get("created_at", time.time())),
            process_pid=int(d.get("process_pid", 0)),
            records=list(d.get("records", [])),
        )


# ---------------------------------------------------------------------------
# HandoffContractSnapshotRecord
# ---------------------------------------------------------------------------


@dataclass
class HandoffContractSnapshotRecord:
    """Point-in-time durable snapshot of delegated handoff contract records.

    Parameters
    ----------
    snapshot_id:
        Unique identifier for this snapshot.
    created_at:
        Unix epoch seconds when the snapshot was written.
    process_pid:
        PID of the process that wrote the snapshot.
    records:
        List of serialised :class:`~core.delegated_runtime_handoff_contract
        .DelegatedHandoffContractRecord` dicts.
    """

    snapshot_id: str = field(
        default_factory=lambda: f"hcs_{uuid.uuid4().hex[:12]}"
    )
    created_at: float = field(default_factory=time.time)
    process_pid: int = field(default_factory=os.getpid)
    records: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a JSON-safe dict."""
        return {
            "snapshot_id": self.snapshot_id,
            "created_at": self.created_at,
            "process_pid": self.process_pid,
            "records": list(self.records),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "HandoffContractSnapshotRecord":
        """Reconstruct from a serialised dict."""
        return cls(
            snapshot_id=d.get("snapshot_id", f"hcs_{uuid.uuid4().hex[:12]}"),
            created_at=float(d.get("created_at", time.time())),
            process_pid=int(d.get("process_pid", 0)),
            records=list(d.get("records", [])),
        )


# ---------------------------------------------------------------------------
# DispatchBindingSnapshotRecord
# ---------------------------------------------------------------------------


@dataclass
class DispatchBindingSnapshotRecord:
    """Point-in-time durable snapshot of Android dispatch binding records.

    Parameters
    ----------
    snapshot_id:
        Unique identifier for this snapshot.
    created_at:
        Unix epoch seconds when the snapshot was written.
    process_pid:
        PID of the process that wrote the snapshot.
    records:
        List of serialised :class:`~core.android_runtime_dispatch_binding
        .AndroidRuntimeDispatchBindingRecord` dicts.
    """

    snapshot_id: str = field(
        default_factory=lambda: f"dbs_{uuid.uuid4().hex[:12]}"
    )
    created_at: float = field(default_factory=time.time)
    process_pid: int = field(default_factory=os.getpid)
    records: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a JSON-safe dict."""
        return {
            "snapshot_id": self.snapshot_id,
            "created_at": self.created_at,
            "process_pid": self.process_pid,
            "records": list(self.records),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "DispatchBindingSnapshotRecord":
        """Reconstruct from a serialised dict."""
        return cls(
            snapshot_id=d.get("snapshot_id", f"dbs_{uuid.uuid4().hex[:12]}"),
            created_at=float(d.get("created_at", time.time())),
            process_pid=int(d.get("process_pid", 0)),
            records=list(d.get("records", [])),
        )


# ---------------------------------------------------------------------------
# DelegatedFlowSnapshotRecord
# ---------------------------------------------------------------------------


@dataclass
class DelegatedFlowSnapshotRecord:
    """Point-in-time durable snapshot of delegated flow entity records.

    Parameters
    ----------
    snapshot_id:
        Unique identifier for this snapshot.
    created_at:
        Unix epoch seconds when the snapshot was written.
    process_pid:
        PID of the process that wrote the snapshot.
    records:
        List of serialised :class:`~core.delegated_flow_entity
        .DelegatedFlowEntity` dicts.
    """

    snapshot_id: str = field(
        default_factory=lambda: f"dfs_{uuid.uuid4().hex[:12]}"
    )
    created_at: float = field(default_factory=time.time)
    process_pid: int = field(default_factory=os.getpid)
    records: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a JSON-safe dict."""
        return {
            "snapshot_id": self.snapshot_id,
            "created_at": self.created_at,
            "process_pid": self.process_pid,
            "records": list(self.records),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "DelegatedFlowSnapshotRecord":
        """Reconstruct from a serialised dict."""
        return cls(
            snapshot_id=d.get("snapshot_id", f"dfs_{uuid.uuid4().hex[:12]}"),
            created_at=float(d.get("created_at", time.time())),
            process_pid=int(d.get("process_pid", 0)),
            records=list(d.get("records", [])),
        )


# ---------------------------------------------------------------------------
# AttachedSessionPersistenceStore
# ---------------------------------------------------------------------------


class AttachedSessionPersistenceStore:
    """Thread-safe, file-backed durable store for attached-runtime session snapshots.

    Snapshots are written atomically: the payload is first written to a
    temporary file in the same directory, then renamed over the target path so
    a partial write never corrupts the previous good snapshot.

    Parameters
    ----------
    store_path:
        Absolute or relative path to the JSON snapshot file.  Defaults to
        ``data/attached_session_snapshot.json``.
    """

    def __init__(self, store_path: Optional[str] = None) -> None:
        self._store_path = store_path or _DEFAULT_SESSION_STORE_PATH
        self._lock = threading.Lock()
        _ensure_store_dir(self._store_path)

    def save(self, snapshot: AttachedSessionSnapshotRecord) -> bool:
        """Atomically persist *snapshot* to disk.

        Returns
        -------
        bool
            ``True`` on success; ``False`` if the write failed (error is logged).
        """
        payload = json.dumps(snapshot.to_dict(), indent=2, ensure_ascii=False)
        ok = _atomic_save(self._store_path, payload, self._lock)
        if ok:
            logger.debug(
                "AttachedSessionPersistence: saved snapshot %s (%d records)",
                snapshot.snapshot_id,
                len(snapshot.records),
            )
        return ok

    def load(self) -> Optional[AttachedSessionSnapshotRecord]:
        """Load the most recent snapshot from disk.

        Returns
        -------
        AttachedSessionSnapshotRecord or None
            ``None`` if no snapshot exists or the file cannot be read.
        """
        data = _atomic_load(self._store_path, self._lock)
        if data is None:
            return None
        try:
            return AttachedSessionSnapshotRecord.from_dict(data)
        except Exception as exc:
            logger.warning(
                "AttachedSessionPersistence: failed to parse snapshot: %s", exc
            )
            return None

    def clear(self) -> bool:
        """Remove the snapshot file from disk.

        Safe to call even when no snapshot exists.

        Returns
        -------
        bool
            ``True`` if the file was deleted (or did not exist); ``False`` on error.
        """
        ok = _atomic_clear(self._store_path, self._lock)
        if ok:
            logger.debug("AttachedSessionPersistence: snapshot cleared")
        return ok

    @property
    def store_path(self) -> str:
        """Absolute path to the snapshot file."""
        return self._store_path


# ---------------------------------------------------------------------------
# HandoffContractPersistenceStore
# ---------------------------------------------------------------------------


class HandoffContractPersistenceStore:
    """Thread-safe, file-backed durable store for handoff contract snapshots.

    Parameters
    ----------
    store_path:
        Absolute or relative path to the JSON snapshot file.  Defaults to
        ``data/handoff_contract_snapshot.json``.
    """

    def __init__(self, store_path: Optional[str] = None) -> None:
        self._store_path = store_path or _DEFAULT_CONTRACT_STORE_PATH
        self._lock = threading.Lock()
        _ensure_store_dir(self._store_path)

    def save(self, snapshot: HandoffContractSnapshotRecord) -> bool:
        """Atomically persist *snapshot* to disk.

        Returns
        -------
        bool
            ``True`` on success; ``False`` if the write failed.
        """
        payload = json.dumps(snapshot.to_dict(), indent=2, ensure_ascii=False)
        ok = _atomic_save(self._store_path, payload, self._lock)
        if ok:
            logger.debug(
                "HandoffContractPersistence: saved snapshot %s (%d records)",
                snapshot.snapshot_id,
                len(snapshot.records),
            )
        return ok

    def load(self) -> Optional[HandoffContractSnapshotRecord]:
        """Load the most recent snapshot from disk.

        Returns
        -------
        HandoffContractSnapshotRecord or None
        """
        data = _atomic_load(self._store_path, self._lock)
        if data is None:
            return None
        try:
            return HandoffContractSnapshotRecord.from_dict(data)
        except Exception as exc:
            logger.warning(
                "HandoffContractPersistence: failed to parse snapshot: %s", exc
            )
            return None

    def clear(self) -> bool:
        """Remove the snapshot file from disk."""
        ok = _atomic_clear(self._store_path, self._lock)
        if ok:
            logger.debug("HandoffContractPersistence: snapshot cleared")
        return ok

    @property
    def store_path(self) -> str:
        """Absolute path to the snapshot file."""
        return self._store_path


# ---------------------------------------------------------------------------
# DispatchBindingPersistenceStore
# ---------------------------------------------------------------------------


class DispatchBindingPersistenceStore:
    """Thread-safe, file-backed durable store for dispatch binding snapshots.

    Parameters
    ----------
    store_path:
        Absolute or relative path to the JSON snapshot file.  Defaults to
        ``data/dispatch_binding_snapshot.json``.
    """

    def __init__(self, store_path: Optional[str] = None) -> None:
        self._store_path = store_path or _DEFAULT_BINDING_STORE_PATH
        self._lock = threading.Lock()
        _ensure_store_dir(self._store_path)

    def save(self, snapshot: DispatchBindingSnapshotRecord) -> bool:
        """Atomically persist *snapshot* to disk.

        Returns
        -------
        bool
            ``True`` on success; ``False`` if the write failed.
        """
        payload = json.dumps(snapshot.to_dict(), indent=2, ensure_ascii=False)
        ok = _atomic_save(self._store_path, payload, self._lock)
        if ok:
            logger.debug(
                "DispatchBindingPersistence: saved snapshot %s (%d records)",
                snapshot.snapshot_id,
                len(snapshot.records),
            )
        return ok

    def load(self) -> Optional[DispatchBindingSnapshotRecord]:
        """Load the most recent snapshot from disk.

        Returns
        -------
        DispatchBindingSnapshotRecord or None
        """
        data = _atomic_load(self._store_path, self._lock)
        if data is None:
            return None
        try:
            return DispatchBindingSnapshotRecord.from_dict(data)
        except Exception as exc:
            logger.warning(
                "DispatchBindingPersistence: failed to parse snapshot: %s", exc
            )
            return None

    def clear(self) -> bool:
        """Remove the snapshot file from disk."""
        ok = _atomic_clear(self._store_path, self._lock)
        if ok:
            logger.debug("DispatchBindingPersistence: snapshot cleared")
        return ok

    @property
    def store_path(self) -> str:
        """Absolute path to the snapshot file."""
        return self._store_path


# ---------------------------------------------------------------------------
# DelegatedFlowPersistenceStore
# ---------------------------------------------------------------------------


class DelegatedFlowPersistenceStore:
    """Thread-safe, file-backed durable store for delegated flow snapshots.

    Parameters
    ----------
    store_path:
        Absolute or relative path to the JSON snapshot file.  Defaults to
        ``data/delegated_flow_snapshot.json``.
    """

    def __init__(self, store_path: Optional[str] = None) -> None:
        self._store_path = store_path or _DEFAULT_FLOW_STORE_PATH
        self._lock = threading.Lock()
        _ensure_store_dir(self._store_path)

    def save(self, snapshot: DelegatedFlowSnapshotRecord) -> bool:
        """Atomically persist *snapshot* to disk.

        Returns
        -------
        bool
            ``True`` on success; ``False`` if the write failed.
        """
        payload = json.dumps(snapshot.to_dict(), indent=2, ensure_ascii=False)
        ok = _atomic_save(self._store_path, payload, self._lock)
        if ok:
            logger.debug(
                "DelegatedFlowPersistence: saved snapshot %s (%d records)",
                snapshot.snapshot_id,
                len(snapshot.records),
            )
        return ok

    def load(self) -> Optional[DelegatedFlowSnapshotRecord]:
        """Load the most recent snapshot from disk.

        Returns
        -------
        DelegatedFlowSnapshotRecord or None
        """
        data = _atomic_load(self._store_path, self._lock)
        if data is None:
            return None
        try:
            return DelegatedFlowSnapshotRecord.from_dict(data)
        except Exception as exc:
            logger.warning(
                "DelegatedFlowPersistence: failed to parse snapshot: %s", exc
            )
            return None

    def clear(self) -> bool:
        """Remove the snapshot file from disk."""
        ok = _atomic_clear(self._store_path, self._lock)
        if ok:
            logger.debug("DelegatedFlowPersistence: snapshot cleared")
        return ok

    @property
    def store_path(self) -> str:
        """Absolute path to the snapshot file."""
        return self._store_path


# ---------------------------------------------------------------------------
# Singleton management — attached session store
# ---------------------------------------------------------------------------

_session_store_instance: Optional[AttachedSessionPersistenceStore] = None
_session_store_lock = threading.Lock()


def get_attached_session_store(
    store_path: Optional[str] = None,
) -> AttachedSessionPersistenceStore:
    """Return (or lazily create) the process-level :class:`AttachedSessionPersistenceStore`.

    Parameters
    ----------
    store_path:
        Optional path override for the snapshot file.
    """
    global _session_store_instance
    with _session_store_lock:
        if _session_store_instance is None:
            _session_store_instance = AttachedSessionPersistenceStore(store_path=store_path)
    return _session_store_instance


def reset_attached_session_store() -> None:
    """Reset the process-level singleton (for test isolation)."""
    global _session_store_instance
    with _session_store_lock:
        _session_store_instance = None


# ---------------------------------------------------------------------------
# Singleton management — handoff contract store
# ---------------------------------------------------------------------------

_contract_store_instance: Optional[HandoffContractPersistenceStore] = None
_contract_store_lock = threading.Lock()


def get_handoff_contract_store(
    store_path: Optional[str] = None,
) -> HandoffContractPersistenceStore:
    """Return (or lazily create) the process-level :class:`HandoffContractPersistenceStore`.

    Parameters
    ----------
    store_path:
        Optional path override for the snapshot file.
    """
    global _contract_store_instance
    with _contract_store_lock:
        if _contract_store_instance is None:
            _contract_store_instance = HandoffContractPersistenceStore(store_path=store_path)
    return _contract_store_instance


def reset_handoff_contract_store() -> None:
    """Reset the process-level singleton (for test isolation)."""
    global _contract_store_instance
    with _contract_store_lock:
        _contract_store_instance = None


# ---------------------------------------------------------------------------
# Singleton management — dispatch binding store
# ---------------------------------------------------------------------------

_binding_store_instance: Optional[DispatchBindingPersistenceStore] = None
_binding_store_lock = threading.Lock()


def get_dispatch_binding_store(
    store_path: Optional[str] = None,
) -> DispatchBindingPersistenceStore:
    """Return (or lazily create) the process-level :class:`DispatchBindingPersistenceStore`.

    Parameters
    ----------
    store_path:
        Optional path override for the snapshot file.
    """
    global _binding_store_instance
    with _binding_store_lock:
        if _binding_store_instance is None:
            _binding_store_instance = DispatchBindingPersistenceStore(store_path=store_path)
    return _binding_store_instance


def reset_dispatch_binding_store() -> None:
    """Reset the process-level singleton (for test isolation)."""
    global _binding_store_instance
    with _binding_store_lock:
        _binding_store_instance = None


# ---------------------------------------------------------------------------
# Singleton management — delegated flow store
# ---------------------------------------------------------------------------

_flow_store_instance: Optional[DelegatedFlowPersistenceStore] = None
_flow_store_lock = threading.Lock()


def get_delegated_flow_store(
    store_path: Optional[str] = None,
) -> DelegatedFlowPersistenceStore:
    """Return (or lazily create) the process-level :class:`DelegatedFlowPersistenceStore`.

    Parameters
    ----------
    store_path:
        Optional path override for the snapshot file.
    """
    global _flow_store_instance
    with _flow_store_lock:
        if _flow_store_instance is None:
            _flow_store_instance = DelegatedFlowPersistenceStore(store_path=store_path)
    return _flow_store_instance


def reset_delegated_flow_store() -> None:
    """Reset the process-level singleton (for test isolation)."""
    global _flow_store_instance
    with _flow_store_lock:
        _flow_store_instance = None


# ---------------------------------------------------------------------------
# Convenience functions — attached session
# ---------------------------------------------------------------------------


def save_attached_session_snapshot(
    records: List[Dict[str, Any]],
    *,
    store: Optional[AttachedSessionPersistenceStore] = None,
) -> AttachedSessionSnapshotRecord:
    """Persist a list of serialised session record dicts to the durable store.

    Parameters
    ----------
    records:
        List of :meth:`~core.attached_runtime_session.AttachedRuntimeSessionRecord
        .to_dict` dicts representing the current ring-buffer contents.
    store:
        Optional explicit store.  Defaults to the process-level singleton.

    Returns
    -------
    AttachedSessionSnapshotRecord
        The snapshot that was written.
    """
    _store = store or get_attached_session_store()
    snapshot = AttachedSessionSnapshotRecord(records=list(records))
    _store.save(snapshot)
    return snapshot


def load_attached_session_snapshot(
    *,
    store: Optional[AttachedSessionPersistenceStore] = None,
) -> Optional[AttachedSessionSnapshotRecord]:
    """Load the most recent attached-session snapshot from the durable store.

    Parameters
    ----------
    store:
        Optional explicit store.  Defaults to the process-level singleton.

    Returns
    -------
    AttachedSessionSnapshotRecord or None
    """
    _store = store or get_attached_session_store()
    return _store.load()


def restore_attached_sessions_from_snapshot(
    *,
    store: Optional[AttachedSessionPersistenceStore] = None,
    runtime: Any = None,
) -> int:
    """Restore attached-session records from the durable store into *runtime*.

    Loads the most recent snapshot and pushes each record back into the
    provided ring-buffer *runtime* (or the process-level singleton if None).
    Records that cannot be deserialised are skipped with a warning.

    Parameters
    ----------
    store:
        Optional explicit :class:`AttachedSessionPersistenceStore`.
    runtime:
        Optional :class:`~core.attached_runtime_session
        .AttachedRuntimeSessionRuntime` to restore into.  Uses the
        process-level singleton if None.

    Returns
    -------
    int
        Number of records successfully restored.
    """
    snapshot = load_attached_session_snapshot(store=store)
    if snapshot is None:
        return 0

    if runtime is None:
        try:
            from core.attached_runtime_session import (
                get_attached_runtime_session_runtime,
                AttachedRuntimeSessionRecord,
            )
            runtime = get_attached_runtime_session_runtime()
        except ImportError:
            logger.warning(
                "AttachedSessionPersistence: could not import attached_runtime_session module"
            )
            return 0
    else:
        try:
            from core.attached_runtime_session import AttachedRuntimeSessionRecord
        except ImportError:
            logger.warning(
                "AttachedSessionPersistence: could not import AttachedRuntimeSessionRecord"
            )
            return 0

    restored = 0
    for record_dict in snapshot.records:
        if not isinstance(record_dict, dict):
            logger.warning(
                "AttachedSessionPersistence: skipping non-dict record in snapshot %s",
                snapshot.snapshot_id,
            )
            continue
        try:
            record = AttachedRuntimeSessionRecord.from_dict(record_dict)
            runtime.push(record)
            restored += 1
        except Exception as exc:
            logger.warning(
                "AttachedSessionPersistence: failed to restore record from snapshot %s: %s",
                snapshot.snapshot_id,
                exc,
            )

    logger.info(
        "AttachedSessionPersistence: restored %d session records from snapshot %s",
        restored,
        snapshot.snapshot_id,
    )
    return restored


# ---------------------------------------------------------------------------
# Convenience functions — handoff contract
# ---------------------------------------------------------------------------


def save_handoff_contract_snapshot(
    records: List[Dict[str, Any]],
    *,
    store: Optional[HandoffContractPersistenceStore] = None,
) -> HandoffContractSnapshotRecord:
    """Persist a list of serialised handoff contract record dicts to the durable store.

    Parameters
    ----------
    records:
        List of :meth:`~core.delegated_runtime_handoff_contract
        .DelegatedHandoffContractRecord.to_dict` dicts.
    store:
        Optional explicit store.  Defaults to the process-level singleton.

    Returns
    -------
    HandoffContractSnapshotRecord
        The snapshot that was written.
    """
    _store = store or get_handoff_contract_store()
    snapshot = HandoffContractSnapshotRecord(records=list(records))
    _store.save(snapshot)
    return snapshot


def load_handoff_contract_snapshot(
    *,
    store: Optional[HandoffContractPersistenceStore] = None,
) -> Optional[HandoffContractSnapshotRecord]:
    """Load the most recent handoff-contract snapshot from the durable store.

    Parameters
    ----------
    store:
        Optional explicit store.  Defaults to the process-level singleton.

    Returns
    -------
    HandoffContractSnapshotRecord or None
    """
    _store = store or get_handoff_contract_store()
    return _store.load()


def restore_handoff_contracts_from_snapshot(
    *,
    store: Optional[HandoffContractPersistenceStore] = None,
    runtime: Any = None,
) -> int:
    """Restore handoff-contract records from the durable store into *runtime*.

    Parameters
    ----------
    store:
        Optional explicit :class:`HandoffContractPersistenceStore`.
    runtime:
        Optional :class:`~core.delegated_runtime_handoff_contract
        .DelegatedHandoffContractRuntime` to restore into.  Uses the
        process-level singleton if None.

    Returns
    -------
    int
        Number of records successfully restored.
    """
    snapshot = load_handoff_contract_snapshot(store=store)
    if snapshot is None:
        return 0

    if runtime is None:
        try:
            from core.delegated_runtime_handoff_contract import (
                get_handoff_contract_runtime,
                DelegatedHandoffContractRecord,
            )
            runtime = get_handoff_contract_runtime()
        except ImportError:
            logger.warning(
                "HandoffContractPersistence: could not import delegated_runtime_handoff_contract module"
            )
            return 0
    else:
        try:
            from core.delegated_runtime_handoff_contract import DelegatedHandoffContractRecord
        except ImportError:
            logger.warning(
                "HandoffContractPersistence: could not import DelegatedHandoffContractRecord"
            )
            return 0

    restored = 0
    for record_dict in snapshot.records:
        if not isinstance(record_dict, dict):
            logger.warning(
                "HandoffContractPersistence: skipping non-dict record in snapshot %s",
                snapshot.snapshot_id,
            )
            continue
        try:
            record = DelegatedHandoffContractRecord.from_dict(record_dict)
            runtime.push(record)
            restored += 1
        except Exception as exc:
            logger.warning(
                "HandoffContractPersistence: failed to restore record from snapshot %s: %s",
                snapshot.snapshot_id,
                exc,
            )

    logger.info(
        "HandoffContractPersistence: restored %d contract records from snapshot %s",
        restored,
        snapshot.snapshot_id,
    )
    return restored


# ---------------------------------------------------------------------------
# Convenience functions — dispatch binding
# ---------------------------------------------------------------------------


def save_dispatch_binding_snapshot(
    records: List[Dict[str, Any]],
    *,
    store: Optional[DispatchBindingPersistenceStore] = None,
) -> DispatchBindingSnapshotRecord:
    """Persist a list of serialised dispatch binding record dicts to the durable store.

    Parameters
    ----------
    records:
        List of :meth:`~core.android_runtime_dispatch_binding
        .AndroidRuntimeDispatchBindingRecord.to_dict` dicts.
    store:
        Optional explicit store.  Defaults to the process-level singleton.

    Returns
    -------
    DispatchBindingSnapshotRecord
        The snapshot that was written.
    """
    _store = store or get_dispatch_binding_store()
    snapshot = DispatchBindingSnapshotRecord(records=list(records))
    _store.save(snapshot)
    return snapshot


def load_dispatch_binding_snapshot(
    *,
    store: Optional[DispatchBindingPersistenceStore] = None,
) -> Optional[DispatchBindingSnapshotRecord]:
    """Load the most recent dispatch-binding snapshot from the durable store.

    Parameters
    ----------
    store:
        Optional explicit store.  Defaults to the process-level singleton.

    Returns
    -------
    DispatchBindingSnapshotRecord or None
    """
    _store = store or get_dispatch_binding_store()
    return _store.load()


def restore_dispatch_bindings_from_snapshot(
    *,
    store: Optional[DispatchBindingPersistenceStore] = None,
    runtime: Any = None,
) -> int:
    """Restore dispatch-binding records from the durable store into *runtime*.

    Parameters
    ----------
    store:
        Optional explicit :class:`DispatchBindingPersistenceStore`.
    runtime:
        Optional :class:`~core.android_runtime_dispatch_binding
        .AndroidRuntimeDispatchBindingRuntime` to restore into.  Uses the
        process-level singleton if None.

    Returns
    -------
    int
        Number of records successfully restored.
    """
    snapshot = load_dispatch_binding_snapshot(store=store)
    if snapshot is None:
        return 0

    if runtime is None:
        try:
            from core.android_runtime_dispatch_binding import (
                get_dispatch_binding_runtime,
                AndroidRuntimeDispatchBindingRecord,
            )
            runtime = get_dispatch_binding_runtime()
        except ImportError:
            logger.warning(
                "DispatchBindingPersistence: could not import android_runtime_dispatch_binding module"
            )
            return 0
    else:
        try:
            from core.android_runtime_dispatch_binding import AndroidRuntimeDispatchBindingRecord
        except ImportError:
            logger.warning(
                "DispatchBindingPersistence: could not import AndroidRuntimeDispatchBindingRecord"
            )
            return 0

    restored = 0
    for record_dict in snapshot.records:
        if not isinstance(record_dict, dict):
            logger.warning(
                "DispatchBindingPersistence: skipping non-dict record in snapshot %s",
                snapshot.snapshot_id,
            )
            continue
        try:
            record = AndroidRuntimeDispatchBindingRecord.from_dict(record_dict)
            runtime.push(record)
            restored += 1
        except Exception as exc:
            logger.warning(
                "DispatchBindingPersistence: failed to restore record from snapshot %s: %s",
                snapshot.snapshot_id,
                exc,
            )

    logger.info(
        "DispatchBindingPersistence: restored %d binding records from snapshot %s",
        restored,
        snapshot.snapshot_id,
    )
    return restored


# ---------------------------------------------------------------------------
# Convenience functions — delegated flow
# ---------------------------------------------------------------------------


def save_delegated_flow_snapshot(
    records: List[Dict[str, Any]],
    *,
    store: Optional[DelegatedFlowPersistenceStore] = None,
) -> DelegatedFlowSnapshotRecord:
    """Persist a list of serialised delegated flow entity dicts to the durable store.

    Parameters
    ----------
    records:
        List of :meth:`~core.delegated_flow_entity.DelegatedFlowEntity.to_dict`
        dicts.
    store:
        Optional explicit store.  Defaults to the process-level singleton.

    Returns
    -------
    DelegatedFlowSnapshotRecord
        The snapshot that was written.
    """
    _store = store or get_delegated_flow_store()
    snapshot = DelegatedFlowSnapshotRecord(records=list(records))
    _store.save(snapshot)
    return snapshot


def load_delegated_flow_snapshot(
    *,
    store: Optional[DelegatedFlowPersistenceStore] = None,
) -> Optional[DelegatedFlowSnapshotRecord]:
    """Load the most recent delegated-flow snapshot from the durable store.

    Parameters
    ----------
    store:
        Optional explicit store.  Defaults to the process-level singleton.

    Returns
    -------
    DelegatedFlowSnapshotRecord or None
    """
    _store = store or get_delegated_flow_store()
    return _store.load()


def restore_delegated_flows_from_snapshot(
    *,
    store: Optional[DelegatedFlowPersistenceStore] = None,
    runtime: Any = None,
) -> int:
    """Restore delegated-flow entities from the durable store into *runtime*.

    Parameters
    ----------
    store:
        Optional explicit :class:`DelegatedFlowPersistenceStore`.
    runtime:
        Optional :class:`~core.delegated_flow_entity.DelegatedFlowEntityRuntime`
        to restore into.  Uses the process-level singleton if None.

    Returns
    -------
    int
        Number of records successfully restored.
    """
    snapshot = load_delegated_flow_snapshot(store=store)
    if snapshot is None:
        return 0

    if runtime is None:
        try:
            from core.delegated_flow_entity import (
                get_delegated_flow_entity_runtime,
                DelegatedFlowEntity,
            )
            runtime = get_delegated_flow_entity_runtime()
        except ImportError:
            logger.warning(
                "DelegatedFlowPersistence: could not import delegated_flow_entity module"
            )
            return 0
    else:
        try:
            from core.delegated_flow_entity import DelegatedFlowEntity
        except ImportError:
            logger.warning(
                "DelegatedFlowPersistence: could not import DelegatedFlowEntity"
            )
            return 0

    restored = 0
    for record_dict in snapshot.records:
        if not isinstance(record_dict, dict):
            logger.warning(
                "DelegatedFlowPersistence: skipping non-dict record in snapshot %s",
                snapshot.snapshot_id,
            )
            continue
        try:
            entity = DelegatedFlowEntity.from_dict(record_dict)
            runtime.put(entity)
            restored += 1
        except Exception as exc:
            logger.warning(
                "DelegatedFlowPersistence: failed to restore record from snapshot %s: %s",
                snapshot.snapshot_id,
                exc,
            )

    logger.info(
        "DelegatedFlowPersistence: restored %d flow entities from snapshot %s",
        restored,
        snapshot.snapshot_id,
    )
    return restored
