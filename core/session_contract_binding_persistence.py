#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/session_contract_binding_persistence.py
=============================================
Durable Persistence Foundation — Session / Contract / Binding / Flow Metadata
(PR-B2-V2: session-contract-binding durability gap closure).

Background
----------
``AttachedRuntimeSessionRuntime``, ``DelegatedHandoffContractRuntime``,
``AndroidRuntimeDispatchBindingRuntime``, and ``DelegatedFlowEntityRuntime``
were previously ring-buffer-only in-memory structures.  A V2 process restart,
crash, or OOM silently discarded:

- the ``attached`` session truth (which devices are cross-device participants),
- the handoff-contract truth (which contracts are pending/sealed/dispatched),
- the dispatch-binding truth (which bindings are active on which devices), and
- the delegated-flow-metadata relationship (which flow spans which objects).

This module closes those four durability gaps by providing file-backed,
write-then-rename atomic snapshot stores for each runtime, following the
same design principles as :mod:`core.task_lifecycle_persistence` and
:mod:`core.mesh.mesh_session_persistence`.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Atomic writes** — snapshots are written to a temp file and renamed so a
  partial write never corrupts the previous good snapshot.
- **Thread-safe** — a per-store :class:`threading.Lock` guards all reads and
  writes.
- **Graceful degradation** — every function returns a valid result (empty list
  or ``None``) when the backing store is unavailable or contains bad data.
- **Pluggable store directory** — callers can pass an explicit ``store_path``
  to isolate tests or use a custom data directory.
- **Ring buffer preserved** — the ring-buffer runtimes remain the primary
  in-process fast-access view; this module adds a durable snapshot layer on
  top, not a replacement.
- **Restore populates ring buffer** — the ``restore_*_from_snapshot`` helpers
  re-populate the corresponding ring-buffer singleton so the rest of the
  system can continue using the normal runtime API after recovery.

Persistence stores
------------------
1. :class:`AttachedRuntimeSessionPersistenceStore`
   Snapshots :class:`~core.attached_runtime_session.AttachedRuntimeSessionRecord`
   objects.  Default file: ``data/attached_session_snapshot.json``.

2. :class:`HandoffContractPersistenceStore`
   Snapshots :class:`~core.delegated_runtime_handoff_contract.DelegatedHandoffContractRecord`
   objects.  Default file: ``data/handoff_contract_snapshot.json``.

3. :class:`DispatchBindingPersistenceStore`
   Snapshots :class:`~core.android_runtime_dispatch_binding.AndroidRuntimeDispatchBindingRecord`
   objects.  Default file: ``data/dispatch_binding_snapshot.json``.

4. :class:`DelegatedFlowEntityPersistenceStore`
   Snapshots :class:`~core.delegated_flow_entity.DelegatedFlowEntity` objects.
   Default file: ``data/delegated_flow_entity_snapshot.json``.

Public API
----------
Classes:
    :class:`AttachedSessionSnapshotRecord`
    :class:`AttachedRuntimeSessionPersistenceStore`
    :class:`HandoffContractSnapshotRecord`
    :class:`HandoffContractPersistenceStore`
    :class:`DispatchBindingSnapshotRecord`
    :class:`DispatchBindingPersistenceStore`
    :class:`DelegatedFlowEntitySnapshotRecord`
    :class:`DelegatedFlowEntityPersistenceStore`

Functions:
    :func:`save_attached_session_snapshot`
    :func:`load_attached_session_snapshot`
    :func:`restore_sessions_from_snapshot`
    :func:`get_attached_session_store`
    :func:`reset_attached_session_store`

    :func:`save_handoff_contract_snapshot`
    :func:`load_handoff_contract_snapshot`
    :func:`restore_contracts_from_snapshot`
    :func:`get_handoff_contract_store`
    :func:`reset_handoff_contract_store`

    :func:`save_dispatch_binding_snapshot`
    :func:`load_dispatch_binding_snapshot`
    :func:`restore_bindings_from_snapshot`
    :func:`get_dispatch_binding_store`
    :func:`reset_dispatch_binding_store`

    :func:`save_delegated_flow_snapshot`
    :func:`load_delegated_flow_snapshot`
    :func:`restore_flows_from_snapshot`
    :func:`get_delegated_flow_store`
    :func:`reset_delegated_flow_store`

Sentinels
---------
:data:`SESSION_CONTRACT_BINDING_PERSISTENCE_IS_AUTHORITY`
    Affirms this module is the canonical durable snapshot layer for session /
    contract / binding / flow-metadata records.
:data:`SESSION_CONTRACT_BINDING_GAP_CLOSURE_SENTINEL`
    Affirms that this module directly closes the four persistence gaps.
:data:`RING_BUFFER_REMAINS_FAST_PATH_POLICY`
    Affirms that ring-buffer runtimes remain the primary in-process read
    surface; this module adds durability, not a replacement.
:data:`RESTORE_POPULATES_RING_BUFFER_POLICY`
    Affirms that restore functions re-populate the corresponding ring-buffer
    singleton so the runtime API is usable after recovery.
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
    "SESSION_CONTRACT_BINDING_PERSISTENCE_IS_AUTHORITY",
    "SESSION_CONTRACT_BINDING_GAP_CLOSURE_SENTINEL",
    "RING_BUFFER_REMAINS_FAST_PATH_POLICY",
    "RESTORE_POPULATES_RING_BUFFER_POLICY",
    # Snapshot records
    "AttachedSessionSnapshotRecord",
    "HandoffContractSnapshotRecord",
    "DispatchBindingSnapshotRecord",
    "DelegatedFlowEntitySnapshotRecord",
    # Persistence stores
    "AttachedRuntimeSessionPersistenceStore",
    "HandoffContractPersistenceStore",
    "DispatchBindingPersistenceStore",
    "DelegatedFlowEntityPersistenceStore",
    # Session store functions
    "save_attached_session_snapshot",
    "load_attached_session_snapshot",
    "restore_sessions_from_snapshot",
    "get_attached_session_store",
    "reset_attached_session_store",
    # Contract store functions
    "save_handoff_contract_snapshot",
    "load_handoff_contract_snapshot",
    "restore_contracts_from_snapshot",
    "get_handoff_contract_store",
    "reset_handoff_contract_store",
    # Binding store functions
    "save_dispatch_binding_snapshot",
    "load_dispatch_binding_snapshot",
    "restore_bindings_from_snapshot",
    "get_dispatch_binding_store",
    "reset_dispatch_binding_store",
    # Flow entity store functions
    "save_delegated_flow_snapshot",
    "load_delegated_flow_snapshot",
    "restore_flows_from_snapshot",
    "get_delegated_flow_store",
    "reset_delegated_flow_store",
]

logger = logging.getLogger("Galaxy.SessionContractBindingPersistence")

# ---------------------------------------------------------------------------
# Sentinels
# ---------------------------------------------------------------------------

SESSION_CONTRACT_BINDING_PERSISTENCE_IS_AUTHORITY: str = (
    "SESSION_CONTRACT_BINDING_PERSISTENCE_IS_AUTHORITY: "
    "core/session_contract_binding_persistence.py is the canonical durable "
    "snapshot layer for attached-session, handoff-contract, dispatch-binding, "
    "and delegated-flow-metadata records.  It does not replace the "
    "corresponding ring-buffer runtimes; it provides durable backing so "
    "records can be reconstructed after process restart.  (PR-B2-V2)"
)

SESSION_CONTRACT_BINDING_GAP_CLOSURE_SENTINEL: str = (
    "SESSION_CONTRACT_BINDING_GAP_CLOSURE::session-contract-binding-durability-pr-b2-v2: "
    "This module directly closes four persistence gaps identified in the V2 "
    "architecture review: (1) attached-session truth lost on restart, "
    "(2) handoff-contract truth lost on restart, "
    "(3) dispatch-binding truth lost on restart, "
    "(4) delegated-flow metadata relationship lost on restart."
)

RING_BUFFER_REMAINS_FAST_PATH_POLICY: str = (
    "POLICY::RING_BUFFER_REMAINS_FAST_PATH: The ring-buffer runtimes "
    "(AttachedRuntimeSessionRuntime, DelegatedHandoffContractRuntime, "
    "AndroidRuntimeDispatchBindingRuntime, DelegatedFlowEntityRuntime) remain "
    "the canonical in-process fast-access and observability surfaces.  The "
    "durable stores in this module add crash-safe persistence on top; they do "
    "not replace the ring-buffer runtimes.  Callers MUST continue to use the "
    "existing ring-buffer APIs for all runtime reads and writes.  The durable "
    "stores are used only for checkpoint/restore operations."
)

RESTORE_POPULATES_RING_BUFFER_POLICY: str = (
    "POLICY::RESTORE_POPULATES_RING_BUFFER: The restore_*_from_snapshot() "
    "functions in this module re-populate the corresponding ring-buffer "
    "singleton after loading from the durable store, so that normal runtime "
    "API callers do not need to be aware of the recovery path.  The ring "
    "buffer holds at most its configured capacity (128 records); records "
    "beyond that capacity are silently evicted (oldest first) as in normal "
    "operation.  The durable snapshot is NOT deleted after a restore — it "
    "remains on disk until the next checkpoint overwrites it."
)

# ---------------------------------------------------------------------------
# Default store paths
# ---------------------------------------------------------------------------

_DATA_DIR = os.environ.get("GALAXY_DATA_DIR", "data")

_DEFAULT_SESSION_STORE_PATH = os.path.join(_DATA_DIR, "attached_session_snapshot.json")
_DEFAULT_CONTRACT_STORE_PATH = os.path.join(_DATA_DIR, "handoff_contract_snapshot.json")
_DEFAULT_BINDING_STORE_PATH = os.path.join(_DATA_DIR, "dispatch_binding_snapshot.json")
_DEFAULT_FLOW_STORE_PATH = os.path.join(_DATA_DIR, "delegated_flow_entity_snapshot.json")


# ---------------------------------------------------------------------------
# Internal base store  (shared implementation pattern)
# ---------------------------------------------------------------------------


class _BasePersistenceStore:
    """Thread-safe, file-backed durable store.

    Subclasses supply only the snapshot class; all I/O is handled here.
    """

    _store_name: str = "BasePersistence"

    def __init__(self, store_path: str) -> None:
        self._store_path = store_path
        self._lock = threading.Lock()
        try:
            os.makedirs(
                os.path.dirname(os.path.abspath(self._store_path)), exist_ok=True
            )
        except Exception as exc:  # pragma: no cover
            logger.warning(
                "%s: could not create store directory: %s", self._store_name, exc
            )

    def _save_dict(self, payload_dict: Dict[str, Any]) -> bool:
        """Atomically write *payload_dict* as JSON to the store file."""
        try:
            payload = json.dumps(payload_dict, indent=2, ensure_ascii=False)
            store_dir = os.path.dirname(os.path.abspath(self._store_path))
            with self._lock:
                fd, tmp_path = tempfile.mkstemp(dir=store_dir, suffix=".tmp")
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as fh:
                        fh.write(payload)
                    os.replace(tmp_path, self._store_path)
                except Exception:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
                    raise
            return True
        except Exception as exc:
            logger.warning("%s: failed to save snapshot: %s", self._store_name, exc)
            return False

    def _load_dict(self) -> Optional[Dict[str, Any]]:
        """Load and return the JSON snapshot dict, or None."""
        with self._lock:
            if not os.path.exists(self._store_path):
                return None
            try:
                with open(self._store_path, "r", encoding="utf-8") as fh:
                    return json.load(fh)
            except Exception as exc:
                logger.warning(
                    "%s: failed to load snapshot: %s", self._store_name, exc
                )
                return None

    def clear(self) -> bool:
        """Remove the snapshot file from disk.

        Safe to call even when no snapshot exists.

        Returns
        -------
        bool
            ``True`` if the file was deleted (or did not exist); ``False``
            on error.
        """
        with self._lock:
            if not os.path.exists(self._store_path):
                return True
            try:
                os.unlink(self._store_path)
                logger.debug("%s: snapshot cleared", self._store_name)
                return True
            except Exception as exc:
                logger.warning(
                    "%s: failed to clear snapshot: %s", self._store_name, exc
                )
                return False

    @property
    def store_path(self) -> str:
        """Absolute path to the snapshot file."""
        return self._store_path


# ---------------------------------------------------------------------------
# 1. Attached-session persistence
# ---------------------------------------------------------------------------


@dataclass
class AttachedSessionSnapshotRecord:
    """Durable snapshot of attached-runtime session records.

    Parameters
    ----------
    snapshot_id
        Unique identifier for this snapshot.
    created_at
        Unix epoch seconds when the snapshot was written.
    process_pid
        PID of the writing process (informational).
    records
        List of serialised :class:`~core.attached_runtime_session
        .AttachedRuntimeSessionRecord` dicts.
    """

    snapshot_id: str = field(
        default_factory=lambda: f"sess_{uuid.uuid4().hex[:12]}"
    )
    created_at: float = field(default_factory=time.time)
    process_pid: int = field(default_factory=os.getpid)
    records: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "created_at": self.created_at,
            "process_pid": self.process_pid,
            "records": list(self.records),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AttachedSessionSnapshotRecord":
        return cls(
            snapshot_id=d.get("snapshot_id", f"sess_{uuid.uuid4().hex[:12]}"),
            created_at=float(d.get("created_at", time.time())),
            process_pid=int(d.get("process_pid", 0)),
            records=list(d.get("records", [])),
        )


class AttachedRuntimeSessionPersistenceStore(_BasePersistenceStore):
    """Thread-safe, file-backed durable store for attached-runtime session snapshots.

    Snapshots are written atomically: the payload is first written to a
    temporary file in the same directory, then renamed over the target path so
    a partial write never corrupts the previous good snapshot.

    Parameters
    ----------
    store_path
        Absolute or relative path to the JSON snapshot file.  Defaults to
        ``data/attached_session_snapshot.json``.
    """

    _store_name = "AttachedSessionPersistence"

    def __init__(self, store_path: Optional[str] = None) -> None:
        super().__init__(store_path or _DEFAULT_SESSION_STORE_PATH)

    def save(self, snapshot: AttachedSessionSnapshotRecord) -> bool:
        """Atomically persist *snapshot* to disk.

        Returns
        -------
        bool
            ``True`` on success; ``False`` if the write failed (error is
            logged).
        """
        ok = self._save_dict(snapshot.to_dict())
        if ok:
            logger.debug(
                "%s: saved snapshot %s (%d records)",
                self._store_name,
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
        data = self._load_dict()
        if data is None:
            return None
        try:
            return AttachedSessionSnapshotRecord.from_dict(data)
        except Exception as exc:
            logger.warning("%s: failed to parse snapshot: %s", self._store_name, exc)
            return None


# Session store singleton
_session_store_instance: Optional[AttachedRuntimeSessionPersistenceStore] = None
_session_store_lock = threading.Lock()


def get_attached_session_store(
    store_path: Optional[str] = None,
) -> AttachedRuntimeSessionPersistenceStore:
    """Return (or lazily create) the process-level :class:`AttachedRuntimeSessionPersistenceStore`."""
    global _session_store_instance
    with _session_store_lock:
        if _session_store_instance is None:
            _session_store_instance = AttachedRuntimeSessionPersistenceStore(
                store_path=store_path
            )
    return _session_store_instance


def reset_attached_session_store() -> None:
    """Reset the process-level singleton (for test isolation)."""
    global _session_store_instance
    with _session_store_lock:
        _session_store_instance = None


def save_attached_session_snapshot(
    records: List[Dict[str, Any]],
    *,
    store: Optional[AttachedRuntimeSessionPersistenceStore] = None,
) -> AttachedSessionSnapshotRecord:
    """Persist a list of serialised session record dicts to the durable store.

    Parameters
    ----------
    records
        List of :meth:`~core.attached_runtime_session.AttachedRuntimeSessionRecord.to_dict`
        dicts.
    store
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
    store: Optional[AttachedRuntimeSessionPersistenceStore] = None,
) -> Optional[AttachedSessionSnapshotRecord]:
    """Load the most recent attached-session durable snapshot.

    Returns
    -------
    AttachedSessionSnapshotRecord or None
    """
    _store = store or get_attached_session_store()
    return _store.load()


def restore_sessions_from_snapshot(
    *,
    store: Optional[AttachedRuntimeSessionPersistenceStore] = None,
    populate_runtime: bool = True,
) -> List[Any]:
    """Recover attached-session records from the durable snapshot.

    Deserialises each record from the snapshot and optionally re-populates
    the module-level ring-buffer singleton so normal runtime API callers are
    unaffected by the recovery path.

    Parameters
    ----------
    store
        Optional explicit store.  Defaults to the process-level singleton.
    populate_runtime
        When ``True`` (default), each recovered record is pushed into the
        :func:`~core.attached_runtime_session.get_attached_runtime_session_runtime`
        ring-buffer singleton.

    Returns
    -------
    list of AttachedRuntimeSessionRecord
        All records recovered from the snapshot.  Returns an empty list when
        no snapshot exists or the file is unreadable.
    """
    from core.attached_runtime_session import (
        AttachedRuntimeSessionRecord,
        get_attached_runtime_session_runtime,
    )

    _store = store or get_attached_session_store()
    snapshot = _store.load()
    if snapshot is None:
        logger.debug(
            "SessionPersistence: no attached-session snapshot found; nothing to restore"
        )
        return []

    restored: List[AttachedRuntimeSessionRecord] = []
    runtime = get_attached_runtime_session_runtime() if populate_runtime else None

    for raw in snapshot.records:
        try:
            record = AttachedRuntimeSessionRecord.from_dict(raw)
        except Exception as exc:
            logger.warning(
                "SessionPersistence: skipping malformed session record in "
                "snapshot %s: %s",
                snapshot.snapshot_id,
                exc,
            )
            continue
        restored.append(record)
        if runtime is not None:
            runtime.push(record)

    logger.info(
        "SessionPersistence: restored %d attached-session records from "
        "snapshot %s (written by pid=%d at %.0f)",
        len(restored),
        snapshot.snapshot_id,
        snapshot.process_pid,
        snapshot.created_at,
    )
    return restored


# ---------------------------------------------------------------------------
# 2. Handoff-contract persistence
# ---------------------------------------------------------------------------


@dataclass
class HandoffContractSnapshotRecord:
    """Durable snapshot of delegated handoff contract records.

    Parameters
    ----------
    snapshot_id
        Unique identifier for this snapshot.
    created_at
        Unix epoch seconds when the snapshot was written.
    process_pid
        PID of the writing process (informational).
    records
        List of serialised :class:`~core.delegated_runtime_handoff_contract
        .DelegatedHandoffContractRecord` dicts.
    """

    snapshot_id: str = field(
        default_factory=lambda: f"hc_{uuid.uuid4().hex[:12]}"
    )
    created_at: float = field(default_factory=time.time)
    process_pid: int = field(default_factory=os.getpid)
    records: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "created_at": self.created_at,
            "process_pid": self.process_pid,
            "records": list(self.records),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "HandoffContractSnapshotRecord":
        return cls(
            snapshot_id=d.get("snapshot_id", f"hc_{uuid.uuid4().hex[:12]}"),
            created_at=float(d.get("created_at", time.time())),
            process_pid=int(d.get("process_pid", 0)),
            records=list(d.get("records", [])),
        )


class HandoffContractPersistenceStore(_BasePersistenceStore):
    """Thread-safe, file-backed durable store for handoff contract snapshots.

    Parameters
    ----------
    store_path
        Absolute or relative path to the JSON snapshot file.  Defaults to
        ``data/handoff_contract_snapshot.json``.
    """

    _store_name = "HandoffContractPersistence"

    def __init__(self, store_path: Optional[str] = None) -> None:
        super().__init__(store_path or _DEFAULT_CONTRACT_STORE_PATH)

    def save(self, snapshot: HandoffContractSnapshotRecord) -> bool:
        """Atomically persist *snapshot* to disk."""
        ok = self._save_dict(snapshot.to_dict())
        if ok:
            logger.debug(
                "%s: saved snapshot %s (%d records)",
                self._store_name,
                snapshot.snapshot_id,
                len(snapshot.records),
            )
        return ok

    def load(self) -> Optional[HandoffContractSnapshotRecord]:
        """Load the most recent snapshot from disk."""
        data = self._load_dict()
        if data is None:
            return None
        try:
            return HandoffContractSnapshotRecord.from_dict(data)
        except Exception as exc:
            logger.warning("%s: failed to parse snapshot: %s", self._store_name, exc)
            return None


# Contract store singleton
_contract_store_instance: Optional[HandoffContractPersistenceStore] = None
_contract_store_lock = threading.Lock()


def get_handoff_contract_store(
    store_path: Optional[str] = None,
) -> HandoffContractPersistenceStore:
    """Return (or lazily create) the process-level :class:`HandoffContractPersistenceStore`."""
    global _contract_store_instance
    with _contract_store_lock:
        if _contract_store_instance is None:
            _contract_store_instance = HandoffContractPersistenceStore(
                store_path=store_path
            )
    return _contract_store_instance


def reset_handoff_contract_store() -> None:
    """Reset the process-level singleton (for test isolation)."""
    global _contract_store_instance
    with _contract_store_lock:
        _contract_store_instance = None


def save_handoff_contract_snapshot(
    records: List[Dict[str, Any]],
    *,
    store: Optional[HandoffContractPersistenceStore] = None,
) -> HandoffContractSnapshotRecord:
    """Persist a list of serialised handoff contract dicts to the durable store."""
    _store = store or get_handoff_contract_store()
    snapshot = HandoffContractSnapshotRecord(records=list(records))
    _store.save(snapshot)
    return snapshot


def load_handoff_contract_snapshot(
    *,
    store: Optional[HandoffContractPersistenceStore] = None,
) -> Optional[HandoffContractSnapshotRecord]:
    """Load the most recent handoff-contract durable snapshot."""
    _store = store or get_handoff_contract_store()
    return _store.load()


def restore_contracts_from_snapshot(
    *,
    store: Optional[HandoffContractPersistenceStore] = None,
    populate_runtime: bool = True,
) -> List[Any]:
    """Recover handoff-contract records from the durable snapshot.

    Parameters
    ----------
    store
        Optional explicit store.
    populate_runtime
        When ``True`` (default), each recovered record is pushed into the
        :func:`~core.delegated_runtime_handoff_contract.get_handoff_contract_runtime`
        ring-buffer singleton.

    Returns
    -------
    list of DelegatedHandoffContractRecord
    """
    from core.delegated_runtime_handoff_contract import (
        DelegatedHandoffContractRecord,
        get_handoff_contract_runtime,
    )

    _store = store or get_handoff_contract_store()
    snapshot = _store.load()
    if snapshot is None:
        logger.debug(
            "ContractPersistence: no handoff-contract snapshot found; nothing to restore"
        )
        return []

    restored: List[DelegatedHandoffContractRecord] = []
    runtime = get_handoff_contract_runtime() if populate_runtime else None

    for raw in snapshot.records:
        try:
            record = DelegatedHandoffContractRecord.from_dict(raw)
        except Exception as exc:
            logger.warning(
                "ContractPersistence: skipping malformed contract record in "
                "snapshot %s: %s",
                snapshot.snapshot_id,
                exc,
            )
            continue
        restored.append(record)
        if runtime is not None:
            runtime.push(record)

    logger.info(
        "ContractPersistence: restored %d handoff-contract records from "
        "snapshot %s (written by pid=%d at %.0f)",
        len(restored),
        snapshot.snapshot_id,
        snapshot.process_pid,
        snapshot.created_at,
    )
    return restored


# ---------------------------------------------------------------------------
# 3. Dispatch-binding persistence
# ---------------------------------------------------------------------------


@dataclass
class DispatchBindingSnapshotRecord:
    """Durable snapshot of Android dispatch binding records.

    Parameters
    ----------
    snapshot_id
        Unique identifier for this snapshot.
    created_at
        Unix epoch seconds when the snapshot was written.
    process_pid
        PID of the writing process (informational).
    records
        List of serialised :class:`~core.android_runtime_dispatch_binding
        .AndroidRuntimeDispatchBindingRecord` dicts.
    """

    snapshot_id: str = field(
        default_factory=lambda: f"db_{uuid.uuid4().hex[:12]}"
    )
    created_at: float = field(default_factory=time.time)
    process_pid: int = field(default_factory=os.getpid)
    records: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "created_at": self.created_at,
            "process_pid": self.process_pid,
            "records": list(self.records),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "DispatchBindingSnapshotRecord":
        return cls(
            snapshot_id=d.get("snapshot_id", f"db_{uuid.uuid4().hex[:12]}"),
            created_at=float(d.get("created_at", time.time())),
            process_pid=int(d.get("process_pid", 0)),
            records=list(d.get("records", [])),
        )


class DispatchBindingPersistenceStore(_BasePersistenceStore):
    """Thread-safe, file-backed durable store for dispatch-binding snapshots.

    Parameters
    ----------
    store_path
        Absolute or relative path to the JSON snapshot file.  Defaults to
        ``data/dispatch_binding_snapshot.json``.
    """

    _store_name = "DispatchBindingPersistence"

    def __init__(self, store_path: Optional[str] = None) -> None:
        super().__init__(store_path or _DEFAULT_BINDING_STORE_PATH)

    def save(self, snapshot: DispatchBindingSnapshotRecord) -> bool:
        """Atomically persist *snapshot* to disk."""
        ok = self._save_dict(snapshot.to_dict())
        if ok:
            logger.debug(
                "%s: saved snapshot %s (%d records)",
                self._store_name,
                snapshot.snapshot_id,
                len(snapshot.records),
            )
        return ok

    def load(self) -> Optional[DispatchBindingSnapshotRecord]:
        """Load the most recent snapshot from disk."""
        data = self._load_dict()
        if data is None:
            return None
        try:
            return DispatchBindingSnapshotRecord.from_dict(data)
        except Exception as exc:
            logger.warning("%s: failed to parse snapshot: %s", self._store_name, exc)
            return None


# Binding store singleton
_binding_store_instance: Optional[DispatchBindingPersistenceStore] = None
_binding_store_lock = threading.Lock()


def get_dispatch_binding_store(
    store_path: Optional[str] = None,
) -> DispatchBindingPersistenceStore:
    """Return (or lazily create) the process-level :class:`DispatchBindingPersistenceStore`."""
    global _binding_store_instance
    with _binding_store_lock:
        if _binding_store_instance is None:
            _binding_store_instance = DispatchBindingPersistenceStore(
                store_path=store_path
            )
    return _binding_store_instance


def reset_dispatch_binding_store() -> None:
    """Reset the process-level singleton (for test isolation)."""
    global _binding_store_instance
    with _binding_store_lock:
        _binding_store_instance = None


def save_dispatch_binding_snapshot(
    records: List[Dict[str, Any]],
    *,
    store: Optional[DispatchBindingPersistenceStore] = None,
) -> DispatchBindingSnapshotRecord:
    """Persist a list of serialised dispatch-binding dicts to the durable store."""
    _store = store or get_dispatch_binding_store()
    snapshot = DispatchBindingSnapshotRecord(records=list(records))
    _store.save(snapshot)
    return snapshot


def load_dispatch_binding_snapshot(
    *,
    store: Optional[DispatchBindingPersistenceStore] = None,
) -> Optional[DispatchBindingSnapshotRecord]:
    """Load the most recent dispatch-binding durable snapshot."""
    _store = store or get_dispatch_binding_store()
    return _store.load()


def restore_bindings_from_snapshot(
    *,
    store: Optional[DispatchBindingPersistenceStore] = None,
    populate_runtime: bool = True,
) -> List[Any]:
    """Recover dispatch-binding records from the durable snapshot.

    Parameters
    ----------
    store
        Optional explicit store.
    populate_runtime
        When ``True`` (default), each recovered record is pushed into the
        :func:`~core.android_runtime_dispatch_binding.get_dispatch_binding_runtime`
        ring-buffer singleton.

    Returns
    -------
    list of AndroidRuntimeDispatchBindingRecord
    """
    from core.android_runtime_dispatch_binding import (
        AndroidRuntimeDispatchBindingRecord,
        get_dispatch_binding_runtime,
    )

    _store = store or get_dispatch_binding_store()
    snapshot = _store.load()
    if snapshot is None:
        logger.debug(
            "BindingPersistence: no dispatch-binding snapshot found; nothing to restore"
        )
        return []

    restored: List[AndroidRuntimeDispatchBindingRecord] = []
    runtime = get_dispatch_binding_runtime() if populate_runtime else None

    for raw in snapshot.records:
        try:
            record = AndroidRuntimeDispatchBindingRecord.from_dict(raw)
        except Exception as exc:
            logger.warning(
                "BindingPersistence: skipping malformed binding record in "
                "snapshot %s: %s",
                snapshot.snapshot_id,
                exc,
            )
            continue
        restored.append(record)
        if runtime is not None:
            runtime.push(record)

    logger.info(
        "BindingPersistence: restored %d dispatch-binding records from "
        "snapshot %s (written by pid=%d at %.0f)",
        len(restored),
        snapshot.snapshot_id,
        snapshot.process_pid,
        snapshot.created_at,
    )
    return restored


# ---------------------------------------------------------------------------
# 4. Delegated-flow-entity persistence
# ---------------------------------------------------------------------------


@dataclass
class DelegatedFlowEntitySnapshotRecord:
    """Durable snapshot of delegated flow entity records.

    Parameters
    ----------
    snapshot_id
        Unique identifier for this snapshot.
    created_at
        Unix epoch seconds when the snapshot was written.
    process_pid
        PID of the writing process (informational).
    records
        List of serialised :class:`~core.delegated_flow_entity
        .DelegatedFlowEntity` dicts.
    """

    snapshot_id: str = field(
        default_factory=lambda: f"dfe_{uuid.uuid4().hex[:12]}"
    )
    created_at: float = field(default_factory=time.time)
    process_pid: int = field(default_factory=os.getpid)
    records: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "created_at": self.created_at,
            "process_pid": self.process_pid,
            "records": list(self.records),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "DelegatedFlowEntitySnapshotRecord":
        return cls(
            snapshot_id=d.get("snapshot_id", f"dfe_{uuid.uuid4().hex[:12]}"),
            created_at=float(d.get("created_at", time.time())),
            process_pid=int(d.get("process_pid", 0)),
            records=list(d.get("records", [])),
        )


class DelegatedFlowEntityPersistenceStore(_BasePersistenceStore):
    """Thread-safe, file-backed durable store for delegated-flow-entity snapshots.

    Parameters
    ----------
    store_path
        Absolute or relative path to the JSON snapshot file.  Defaults to
        ``data/delegated_flow_entity_snapshot.json``.
    """

    _store_name = "DelegatedFlowEntityPersistence"

    def __init__(self, store_path: Optional[str] = None) -> None:
        super().__init__(store_path or _DEFAULT_FLOW_STORE_PATH)

    def save(self, snapshot: DelegatedFlowEntitySnapshotRecord) -> bool:
        """Atomically persist *snapshot* to disk."""
        ok = self._save_dict(snapshot.to_dict())
        if ok:
            logger.debug(
                "%s: saved snapshot %s (%d records)",
                self._store_name,
                snapshot.snapshot_id,
                len(snapshot.records),
            )
        return ok

    def load(self) -> Optional[DelegatedFlowEntitySnapshotRecord]:
        """Load the most recent snapshot from disk."""
        data = self._load_dict()
        if data is None:
            return None
        try:
            return DelegatedFlowEntitySnapshotRecord.from_dict(data)
        except Exception as exc:
            logger.warning("%s: failed to parse snapshot: %s", self._store_name, exc)
            return None


# Flow entity store singleton
_flow_store_instance: Optional[DelegatedFlowEntityPersistenceStore] = None
_flow_store_lock = threading.Lock()


def get_delegated_flow_store(
    store_path: Optional[str] = None,
) -> DelegatedFlowEntityPersistenceStore:
    """Return (or lazily create) the process-level :class:`DelegatedFlowEntityPersistenceStore`."""
    global _flow_store_instance
    with _flow_store_lock:
        if _flow_store_instance is None:
            _flow_store_instance = DelegatedFlowEntityPersistenceStore(
                store_path=store_path
            )
    return _flow_store_instance


def reset_delegated_flow_store() -> None:
    """Reset the process-level singleton (for test isolation)."""
    global _flow_store_instance
    with _flow_store_lock:
        _flow_store_instance = None


def save_delegated_flow_snapshot(
    records: List[Dict[str, Any]],
    *,
    store: Optional[DelegatedFlowEntityPersistenceStore] = None,
) -> DelegatedFlowEntitySnapshotRecord:
    """Persist a list of serialised delegated-flow-entity dicts to the durable store."""
    _store = store or get_delegated_flow_store()
    snapshot = DelegatedFlowEntitySnapshotRecord(records=list(records))
    _store.save(snapshot)
    return snapshot


def load_delegated_flow_snapshot(
    *,
    store: Optional[DelegatedFlowEntityPersistenceStore] = None,
) -> Optional[DelegatedFlowEntitySnapshotRecord]:
    """Load the most recent delegated-flow-entity durable snapshot."""
    _store = store or get_delegated_flow_store()
    return _store.load()


def restore_flows_from_snapshot(
    *,
    store: Optional[DelegatedFlowEntityPersistenceStore] = None,
    populate_runtime: bool = True,
) -> List[Any]:
    """Recover delegated-flow-entity records from the durable snapshot.

    Parameters
    ----------
    store
        Optional explicit store.
    populate_runtime
        When ``True`` (default), each recovered entity is loaded into the
        :func:`~core.delegated_flow_entity.get_delegated_flow_entity_runtime`
        ring-buffer singleton.

    Returns
    -------
    list of DelegatedFlowEntity
    """
    from core.delegated_flow_entity import (
        DelegatedFlowEntity,
        get_delegated_flow_entity_runtime,
    )

    _store = store or get_delegated_flow_store()
    snapshot = _store.load()
    if snapshot is None:
        logger.debug(
            "FlowPersistence: no delegated-flow snapshot found; nothing to restore"
        )
        return []

    restored: List[DelegatedFlowEntity] = []
    runtime = get_delegated_flow_entity_runtime() if populate_runtime else None

    for raw in snapshot.records:
        try:
            entity = DelegatedFlowEntity.from_dict(raw)
        except Exception as exc:
            logger.warning(
                "FlowPersistence: skipping malformed flow entity in "
                "snapshot %s: %s",
                snapshot.snapshot_id,
                exc,
            )
            continue
        restored.append(entity)
        if runtime is not None:
            runtime.put(entity)

    logger.info(
        "FlowPersistence: restored %d delegated-flow entities from "
        "snapshot %s (written by pid=%d at %.0f)",
        len(restored),
        snapshot.snapshot_id,
        snapshot.process_pid,
        snapshot.created_at,
    )
    return restored
