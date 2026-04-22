#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/task_lifecycle_persistence.py
====================================
Durable In-Flight Task Lifecycle Persistence — PR-D1 (lifecycle durability gap closure).

Background
----------
``TaskEnvelopeLifecycleRegistry`` is the canonical in-memory registry for every
in-flight task envelope from gateway ingress through device dispatch to result
completion.  Prior to this module, that registry was **purely in-memory**: a
process restart or crash silently discarded every pending record, requiring the
task source to replay or re-issue all work from scratch.

This module closes that durability gap by providing:

1. :class:`InFlightTaskDisposition` — canonical classification of what should
   happen to a task after interruption:

   * ``RESUMABLE`` — task was dispatched to a device; can be re-dispatched after
     the device reconnects.
   * ``REPLAY_ONLY`` — task was still being routed; must be replayed through the
     routing layer.
   * ``REISSUABLE`` — task was at gateway ingress; can be re-issued from the
     original source.
   * ``TERMINAL_ON_INTERRUPT`` — task was in result-completion (result may
     already have been delivered); treat as terminal after interruption.

2. :data:`DISPOSITION_BY_OWNER` — mapping from :class:`LifecycleOwner` enum
   values to :class:`InFlightTaskDisposition`, making the policy machine-readable
   and reviewable.

3. :class:`TaskLifecycleSnapshotRecord` — a serialisable point-in-time snapshot
   of all pending envelope records and their assigned dispositions.

4. :class:`TaskLifecyclePersistenceStore` — a thread-safe, file-backed durable
   store that atomically writes and reads snapshots using a write-then-rename
   pattern.  Follows the same design principles as
   :mod:`core.mesh.mesh_session_persistence`.

5. :func:`save_task_lifecycle_snapshot` / :func:`load_task_lifecycle_snapshot` —
   convenience wrappers over the process-level singleton store.

6. :func:`restore_inflight_tasks_from_snapshot` — recover function called by
   :class:`~core.runtime_restart_recovery.RuntimeRestartRecoveryCoordinator`
   during startup recovery.  Each restored record is annotated with its
   :class:`InFlightTaskDisposition` so the caller can decide how to handle it.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Graceful degradation** — every function returns a valid result even when
  the backing store is unavailable or contains bad data.
- **Atomic writes** — snapshots are written to a temp file and then renamed so
  a partial write never corrupts the previous snapshot.
- **Thread-safe** — a per-store :class:`threading.Lock` guards all reads and
  writes.
- **Pluggable store directory** — callers can pass an explicit ``store_path`` to
  isolate tests or use a custom data directory.
- **Does not replace registry** — this is a durable *snapshot layer*, not a
  runtime truth source.  The :class:`~core.task_envelope_lifecycle_registry
  .TaskEnvelopeLifecycleRegistry` remains the canonical runtime authority.

Sentinels
---------
:data:`TASK_LIFECYCLE_PERSISTENCE_IS_AUTHORITY`
    Affirms this module is the canonical durable snapshot layer for in-flight
    task lifecycle records.
:data:`TASK_LIFECYCLE_PERSISTENCE_GAP_CLOSURE_SENTINEL`
    Affirms this module directly closes the in-flight task durability gap.
:data:`DISPOSITION_POLICY_IS_EXPLICIT`
    Affirms that every :class:`LifecycleOwner` value maps to a well-defined
    :class:`InFlightTaskDisposition`.
:data:`RECOVERY_RESTORES_INTERRUPTED_RECORDS_POLICY`
    Affirms that recovery re-hydrates records with ``interrupted_at`` set and
    does *not* silently discard them.

Public API
----------
Classes:
    :class:`InFlightTaskDisposition`
    :class:`TaskLifecycleSnapshotRecord`
    :class:`RestoredTaskRecord`
    :class:`TaskLifecyclePersistenceStore`

Functions:
    :func:`classify_disposition`
    :func:`save_task_lifecycle_snapshot`
    :func:`load_task_lifecycle_snapshot`
    :func:`restore_inflight_tasks_from_snapshot`
    :func:`get_task_lifecycle_store`
    :func:`reset_task_lifecycle_store`
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
from enum import Enum
from typing import Any, Dict, List, Optional

__all__ = [
    # Sentinels
    "TASK_LIFECYCLE_PERSISTENCE_IS_AUTHORITY",
    "TASK_LIFECYCLE_PERSISTENCE_GAP_CLOSURE_SENTINEL",
    "DISPOSITION_POLICY_IS_EXPLICIT",
    "RECOVERY_RESTORES_INTERRUPTED_RECORDS_POLICY",
    # Enums
    "InFlightTaskDisposition",
    # Data classes
    "TaskLifecycleSnapshotRecord",
    "RestoredTaskRecord",
    # Main store
    "TaskLifecyclePersistenceStore",
    # Functions
    "classify_disposition",
    "save_task_lifecycle_snapshot",
    "load_task_lifecycle_snapshot",
    "restore_inflight_tasks_from_snapshot",
    "get_task_lifecycle_store",
    "reset_task_lifecycle_store",
    # Mapping constant
    "DISPOSITION_BY_OWNER",
]

logger = logging.getLogger("Galaxy.TaskLifecyclePersistence")

# ---------------------------------------------------------------------------
# Sentinels
# ---------------------------------------------------------------------------

TASK_LIFECYCLE_PERSISTENCE_IS_AUTHORITY: str = (
    "TASK_LIFECYCLE_PERSISTENCE_IS_AUTHORITY: "
    "core/task_lifecycle_persistence.py is the canonical durable snapshot layer "
    "for in-flight task envelope lifecycle records.  It does not replace the "
    "TaskEnvelopeLifecycleRegistry runtime authority; it provides durable "
    "backing so records can be reconstructed after process restart. (PR-D1)"
)

TASK_LIFECYCLE_PERSISTENCE_GAP_CLOSURE_SENTINEL: str = (
    "TASK_LIFECYCLE_PERSISTENCE_GAP_CLOSURE::in-flight-task-durability-pr-d1-v1: "
    "This module directly closes the in-flight task lifecycle durability gap "
    "identified in the AHE review — problem D1/D3/D9 (tasks lost on restart, "
    "no checkpoint/resume semantics, long tasks must restart entirely)."
)

DISPOSITION_POLICY_IS_EXPLICIT: str = (
    "POLICY::DISPOSITION_POLICY_IS_EXPLICIT: Every LifecycleOwner value maps "
    "to a well-defined InFlightTaskDisposition.  The mapping is stored in "
    "DISPOSITION_BY_OWNER and is machine-readable and reviewable."
)

RECOVERY_RESTORES_INTERRUPTED_RECORDS_POLICY: str = (
    "POLICY::RECOVERY_RESTORES_INTERRUPTED_RECORDS: On process restart, "
    "restore_inflight_tasks_from_snapshot() re-hydrates all records from the "
    "most recent durable snapshot and annotates each with 'interrupted_at' and "
    "its InFlightTaskDisposition.  Records are NOT silently discarded; callers "
    "can decide per-disposition whether to resume, replay, re-issue, or terminate."
)

# ---------------------------------------------------------------------------
# Default store path
# ---------------------------------------------------------------------------

_DEFAULT_STORE_PATH = os.path.join(
    os.environ.get("GALAXY_DATA_DIR", "data"),
    "task_lifecycle_snapshot.json",
)

# ---------------------------------------------------------------------------
# InFlightTaskDisposition
# ---------------------------------------------------------------------------


class InFlightTaskDisposition(str, Enum):
    """Canonical classification of what should happen to a task after interruption.

    Used during restart recovery to decide whether a previously in-flight task
    can be resumed, must be replayed, can be re-issued, or should be treated as
    terminal.

    Values
    ------
    RESUMABLE
        The task was in ``device_dispatch`` or ``cross_device`` ownership — it
        had been sent to a device and the server was awaiting a result.  After
        the device reconnects it can be re-dispatched with the same task_id so
        the device can match the result.
    REPLAY_ONLY
        The task was in ``routing`` ownership — it had been admitted through the
        gateway but routing had not yet selected a device.  It must be replayed
        through the routing layer so a fresh device-selection decision is made.
    REISSUABLE
        The task was in ``gateway_ingress`` ownership — it was registered but
        had not yet entered routing.  The original source can safely re-issue
        the request.
    TERMINAL_ON_INTERRUPT
        The task was in ``result_completion`` ownership — the result had arrived
        and was being written back to the caller.  The result may already have
        been delivered; treating the task as terminal avoids duplicate delivery.
    """

    RESUMABLE = "resumable"
    REPLAY_ONLY = "replay_only"
    REISSUABLE = "reissuable"
    TERMINAL_ON_INTERRUPT = "terminal_on_interrupt"


# ---------------------------------------------------------------------------
# Disposition mapping
# ---------------------------------------------------------------------------

DISPOSITION_BY_OWNER: Dict[str, InFlightTaskDisposition] = {
    "gateway_ingress": InFlightTaskDisposition.REISSUABLE,
    "routing": InFlightTaskDisposition.REPLAY_ONLY,
    "device_dispatch": InFlightTaskDisposition.RESUMABLE,
    "cross_device": InFlightTaskDisposition.RESUMABLE,
    "result_completion": InFlightTaskDisposition.TERMINAL_ON_INTERRUPT,
}


def classify_disposition(owner: str) -> InFlightTaskDisposition:
    """Return the :class:`InFlightTaskDisposition` for the given *owner* value.

    Falls back to :attr:`InFlightTaskDisposition.REPLAY_ONLY` for any unknown
    owner value so that unknown tasks are conservatively replayed rather than
    silently dropped or assumed-resumable.

    Parameters
    ----------
    owner:
        The :class:`~core.task_envelope_lifecycle_registry.LifecycleOwner`
        string value (e.g. ``"device_dispatch"``).

    Returns
    -------
    InFlightTaskDisposition
    """
    return DISPOSITION_BY_OWNER.get(owner, InFlightTaskDisposition.REPLAY_ONLY)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class TaskLifecycleSnapshotRecord:
    """A durable snapshot of all pending in-flight task records.

    Parameters
    ----------
    snapshot_id:
        Unique identifier for this snapshot.
    created_at:
        Unix epoch seconds when the snapshot was written.
    process_pid:
        PID of the process that wrote the snapshot (informational).
    records:
        List of serialised :class:`~core.task_envelope_lifecycle_registry
        .PendingEnvelopeRecord` dicts.
    """

    snapshot_id: str = field(
        default_factory=lambda: f"tls_{uuid.uuid4().hex[:12]}"
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
    def from_dict(cls, d: Dict[str, Any]) -> "TaskLifecycleSnapshotRecord":
        """Reconstruct from a serialised dict."""
        return cls(
            snapshot_id=d.get("snapshot_id", f"tls_{uuid.uuid4().hex[:12]}"),
            created_at=float(d.get("created_at", time.time())),
            process_pid=int(d.get("process_pid", 0)),
            records=list(d.get("records", [])),
        )


@dataclass
class RestoredTaskRecord:
    """A task lifecycle record recovered from durable storage after restart.

    Wraps a ``PendingEnvelopeRecord``-compatible dict with recovery metadata.

    Parameters
    ----------
    task_id:
        Canonical task identifier.
    trace_id:
        Distributed trace identifier.
    target_device_id:
        Primary target device at interruption time.
    tool_name:
        Tool / command being invoked.
    owner:
        Lifecycle owner at the time of interruption.
    timeout:
        Original timeout in seconds.
    registered_at:
        Unix epoch when the task was first registered.
    interrupted_at:
        Unix epoch when the recovery snapshot was loaded (i.e. when the
        interruption was observed).
    disposition:
        How this task should be handled after interruption.
    metadata:
        Arbitrary extra fields from the original record.
    snapshot_id:
        Identifier of the snapshot this record was recovered from.
    """

    task_id: str
    trace_id: str
    target_device_id: str
    tool_name: str
    owner: str
    timeout: float
    registered_at: float
    interrupted_at: float
    disposition: InFlightTaskDisposition
    metadata: Dict[str, Any] = field(default_factory=dict)
    snapshot_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a JSON-safe dict."""
        return {
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "target_device_id": self.target_device_id,
            "tool_name": self.tool_name,
            "owner": self.owner,
            "timeout": self.timeout,
            "registered_at": self.registered_at,
            "interrupted_at": self.interrupted_at,
            "disposition": self.disposition.value,
            "metadata": dict(self.metadata),
            "snapshot_id": self.snapshot_id,
        }

    @classmethod
    def from_record_dict(
        cls,
        record_dict: Dict[str, Any],
        *,
        interrupted_at: float,
        snapshot_id: str = "",
    ) -> "RestoredTaskRecord":
        """Build a :class:`RestoredTaskRecord` from a serialised record dict."""
        owner = record_dict.get("owner", "gateway_ingress")
        return cls(
            task_id=record_dict.get("task_id", ""),
            trace_id=record_dict.get("trace_id", ""),
            target_device_id=record_dict.get("target_device_id", ""),
            tool_name=record_dict.get("tool_name", ""),
            owner=owner,
            timeout=float(record_dict.get("timeout", 30.0)),
            registered_at=float(record_dict.get("registered_at", time.time())),
            interrupted_at=interrupted_at,
            disposition=classify_disposition(owner),
            metadata=dict(record_dict.get("metadata", {})),
            snapshot_id=snapshot_id,
        )


# ---------------------------------------------------------------------------
# TaskLifecyclePersistenceStore
# ---------------------------------------------------------------------------


class TaskLifecyclePersistenceStore:
    """Thread-safe, file-backed durable store for in-flight task lifecycle snapshots.

    Snapshots are written atomically: the payload is first written to a
    temporary file in the same directory, then renamed over the target path so
    a partial write never corrupts the previous good snapshot.

    Parameters
    ----------
    store_path:
        Absolute or relative path to the JSON snapshot file.  Defaults to
        ``data/task_lifecycle_snapshot.json``.
    """

    def __init__(self, store_path: Optional[str] = None) -> None:
        self._store_path = store_path or _DEFAULT_STORE_PATH
        self._lock = threading.Lock()
        # Ensure the directory exists eagerly so callers don't have to worry
        # about it.
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self._store_path)), exist_ok=True)
        except Exception as exc:
            logger.warning(
                "TaskLifecyclePersistence: could not create store directory: %s", exc
            )

    # ── Write ────────────────────────────────────────────────────────────────

    def save(self, snapshot: TaskLifecycleSnapshotRecord) -> bool:
        """Atomically persist *snapshot* to disk.

        Parameters
        ----------
        snapshot:
            The :class:`TaskLifecycleSnapshotRecord` to save.

        Returns
        -------
        bool
            ``True`` on success; ``False`` if the write failed (error is logged).
        """
        try:
            payload = json.dumps(snapshot.to_dict(), indent=2, ensure_ascii=False)
            store_dir = os.path.dirname(os.path.abspath(self._store_path))
            with self._lock:
                fd, tmp_path = tempfile.mkstemp(dir=store_dir, suffix=".tmp")
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as fh:
                        fh.write(payload)
                    os.replace(tmp_path, self._store_path)
                except Exception:
                    # Clean up the tmp file if rename failed
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
                    raise
            logger.debug(
                "TaskLifecyclePersistence: saved snapshot %s (%d records)",
                snapshot.snapshot_id,
                len(snapshot.records),
            )
            return True
        except Exception as exc:
            logger.warning(
                "TaskLifecyclePersistence: failed to save snapshot: %s", exc
            )
            return False

    # ── Read ─────────────────────────────────────────────────────────────────

    def load(self) -> Optional[TaskLifecycleSnapshotRecord]:
        """Load the most recent snapshot from disk.

        Returns
        -------
        TaskLifecycleSnapshotRecord or None
            ``None`` if no snapshot exists or the file cannot be read.
        """
        with self._lock:
            if not os.path.exists(self._store_path):
                return None
            try:
                with open(self._store_path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                return TaskLifecycleSnapshotRecord.from_dict(data)
            except Exception as exc:
                logger.warning(
                    "TaskLifecyclePersistence: failed to load snapshot: %s", exc
                )
                return None

    # ── Clear ────────────────────────────────────────────────────────────────

    def clear(self) -> bool:
        """Remove the snapshot file from disk.

        Safe to call even when no snapshot exists.

        Returns
        -------
        bool
            ``True`` if the file was deleted (or did not exist); ``False`` on error.
        """
        with self._lock:
            if not os.path.exists(self._store_path):
                return True
            try:
                os.unlink(self._store_path)
                logger.debug("TaskLifecyclePersistence: snapshot cleared")
                return True
            except Exception as exc:
                logger.warning(
                    "TaskLifecyclePersistence: failed to clear snapshot: %s", exc
                )
                return False

    @property
    def store_path(self) -> str:
        """Absolute path to the snapshot file."""
        return self._store_path


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------

_store_instance: Optional[TaskLifecyclePersistenceStore] = None
_store_lock = threading.Lock()


def get_task_lifecycle_store(
    store_path: Optional[str] = None,
) -> TaskLifecyclePersistenceStore:
    """Return (or lazily create) the process-level :class:`TaskLifecyclePersistenceStore`.

    If *store_path* is provided and the singleton has not yet been created,
    the singleton is initialised with that path.  Subsequent calls with a
    different *store_path* return the existing singleton unchanged (to avoid
    accidentally creating multiple stores pointing at different files).

    Parameters
    ----------
    store_path:
        Optional path override for the snapshot file.

    Returns
    -------
    TaskLifecyclePersistenceStore
    """
    global _store_instance
    with _store_lock:
        if _store_instance is None:
            _store_instance = TaskLifecyclePersistenceStore(store_path=store_path)
    return _store_instance


def reset_task_lifecycle_store() -> None:
    """Reset the process-level singleton (for test isolation)."""
    global _store_instance
    with _store_lock:
        _store_instance = None


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------


def save_task_lifecycle_snapshot(
    records: List[Dict[str, Any]],
    *,
    store: Optional[TaskLifecyclePersistenceStore] = None,
) -> TaskLifecycleSnapshotRecord:
    """Persist a list of serialised pending-record dicts to the durable store.

    Parameters
    ----------
    records:
        List of :meth:`~core.task_envelope_lifecycle_registry.PendingEnvelopeRecord.to_dict`
        dicts representing the currently pending in-flight tasks.
    store:
        Optional explicit store.  Defaults to the process-level singleton.

    Returns
    -------
    TaskLifecycleSnapshotRecord
        The snapshot that was written.
    """
    _store = store or get_task_lifecycle_store()
    snapshot = TaskLifecycleSnapshotRecord(records=list(records))
    _store.save(snapshot)
    return snapshot


def load_task_lifecycle_snapshot(
    *,
    store: Optional[TaskLifecyclePersistenceStore] = None,
) -> Optional[TaskLifecycleSnapshotRecord]:
    """Load the most recent durable snapshot.

    Parameters
    ----------
    store:
        Optional explicit store.  Defaults to the process-level singleton.

    Returns
    -------
    TaskLifecycleSnapshotRecord or None
    """
    _store = store or get_task_lifecycle_store()
    return _store.load()


def restore_inflight_tasks_from_snapshot(
    *,
    store: Optional[TaskLifecyclePersistenceStore] = None,
    now: Optional[float] = None,
) -> List[RestoredTaskRecord]:
    """Recover in-flight task records from the durable lifecycle snapshot.

    Called by :class:`~core.runtime_restart_recovery.RuntimeRestartRecoveryCoordinator`
    during startup recovery (Step 5).

    Each record in the snapshot is wrapped in a :class:`RestoredTaskRecord`
    with:

    * ``interrupted_at`` set to *now* (the restart observation time).
    * ``disposition`` assigned according to :func:`classify_disposition`.

    The snapshot file is **not** deleted after loading — it remains on disk
    until :class:`TaskEnvelopeLifecycleRegistry` writes a new (empty) snapshot
    after the registry reinitialises.  This prevents a partial recovery from
    losing records.

    Parameters
    ----------
    store:
        Optional explicit store.  Defaults to the process-level singleton.
    now:
        Wall-clock time to use as ``interrupted_at``.  Defaults to
        :func:`time.time`.

    Returns
    -------
    list of RestoredTaskRecord
        All records from the snapshot.  Returns an empty list if no snapshot
        exists or the file is unreadable.
    """
    _store = store or get_task_lifecycle_store()
    _now = now if now is not None else time.time()

    snapshot = _store.load()
    if snapshot is None:
        logger.debug(
            "TaskLifecyclePersistence: no lifecycle snapshot found; "
            "nothing to restore"
        )
        return []

    restored: List[RestoredTaskRecord] = []
    for raw in snapshot.records:
        try:
            rec = RestoredTaskRecord.from_record_dict(
                raw,
                interrupted_at=_now,
                snapshot_id=snapshot.snapshot_id,
            )
            restored.append(rec)
        except Exception as exc:
            logger.warning(
                "TaskLifecyclePersistence: skipping malformed record in "
                "snapshot %s: %s",
                snapshot.snapshot_id,
                exc,
            )

    logger.info(
        "TaskLifecyclePersistence: restored %d in-flight task records from "
        "snapshot %s (written by pid=%d at %.0f)",
        len(restored),
        snapshot.snapshot_id,
        snapshot.process_pid,
        snapshot.created_at,
    )
    return restored
