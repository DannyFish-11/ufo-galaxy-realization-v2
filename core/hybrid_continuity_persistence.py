#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/hybrid_continuity_persistence.py
======================================
Durable Hybrid Orchestration Continuity Persistence — PR-59 gap closure.

Background
----------
:class:`~core.hybrid_orchestration_continuity.HybridOrchestrationContinuityRegistry`
is the canonical in-memory registry for hybrid execution lifecycle records.
Prior to this module the registry was **purely in-memory**: a process restart
discarded all hybrid execution records, so the restart/recovery coordinator
had nothing to mark as ``interrupted`` — even though the policy existed.

This module closes that durability gap by providing a file-backed snapshot
layer for hybrid continuity records, following the same pattern established
by :mod:`core.task_lifecycle_persistence` for in-flight task records.

What this module provides
-------------------------

1. :class:`HybridContinuitySnapshot` — a serialisable point-in-time snapshot
   of all registered hybrid execution records.

2. :class:`HybridContinuityPersistenceStore` — a thread-safe, file-backed
   durable store that atomically writes and reads continuity snapshots using
   a write-then-rename pattern.

3. :func:`save_hybrid_continuity_snapshot` /
   :func:`load_hybrid_continuity_snapshot` — convenience wrappers over the
   process-level singleton store.

4. :func:`restore_hybrid_continuity_from_snapshot` — recover function called
   by :class:`~core.runtime_restart_recovery.RuntimeRestartRecoveryCoordinator`
   during startup recovery.  The function re-populates the continuity registry
   from the most recent durable snapshot so that
   :meth:`~core.hybrid_orchestration_continuity
   .HybridOrchestrationContinuityRegistry.mark_all_running_as_interrupted`
   can then transition in-flight records to ``interrupted`` as intended.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Snapshot layer, not runtime authority** — the
  :class:`~core.hybrid_orchestration_continuity
  .HybridOrchestrationContinuityRegistry` remains the canonical in-process
  runtime truth source.  This module provides *durable backing* only.
- **Graceful degradation** — every function returns a valid result even when
  the backing store is unavailable or contains bad data.
- **Atomic writes** — snapshots are written to a temp file and then renamed
  so a partial write never corrupts the previous snapshot.
- **Thread-safe** — a per-store :class:`threading.Lock` guards all reads
  and writes.
- **Partial-result preservation** — :class:`~core.hybrid_orchestration_continuity
  .HybridPartialResult` records are included in the snapshot so preserved
  and mergeable partial results survive restart and can be inspected during
  recovery.

Durability boundary
-------------------
Survives restart (via this store):
  - All fields of :class:`~core.hybrid_orchestration_continuity
    .HybridOrchestrationRecord` including lifecycle state, partial results,
    and resume count.

Does NOT survive restart (intentional — see
:data:`~core.hybrid_orchestration_continuity
.HYBRID_TRANSPORT_HANDLES_ARE_EPHEMERAL_POLICY`):
  - Live A2A transport handles, GUI automation state, VLM screenshot buffers.

Sentinels
---------
:data:`HYBRID_CONTINUITY_PERSISTENCE_IS_AUTHORITY`
    Affirms this module is the canonical durable snapshot layer for hybrid
    orchestration continuity records.
:data:`HYBRID_CONTINUITY_PERSISTENCE_GAP_CLOSURE_SENTINEL`
    Affirms this module closes the hybrid continuity persistence gap.
:data:`HYBRID_CONTINUITY_RECOVERY_RESTORES_RECORDS_POLICY`
    Affirms that recovery re-hydrates records into the in-process registry
    before the restart coordinator marks them as interrupted.

Public API
----------
Classes:
    :class:`HybridContinuitySnapshot`
    :class:`HybridContinuityPersistenceStore`

Functions:
    :func:`save_hybrid_continuity_snapshot`
    :func:`load_hybrid_continuity_snapshot`
    :func:`restore_hybrid_continuity_from_snapshot`
    :func:`get_hybrid_continuity_store`
    :func:`reset_hybrid_continuity_store`
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

logger = logging.getLogger("Galaxy.HybridContinuityPersistence")

__all__ = [
    # Sentinels
    "HYBRID_CONTINUITY_PERSISTENCE_IS_AUTHORITY",
    "HYBRID_CONTINUITY_PERSISTENCE_GAP_CLOSURE_SENTINEL",
    "HYBRID_CONTINUITY_RECOVERY_RESTORES_RECORDS_POLICY",
    # Classes
    "HybridContinuitySnapshot",
    "HybridContinuityPersistenceStore",
    # Functions
    "save_hybrid_continuity_snapshot",
    "load_hybrid_continuity_snapshot",
    "restore_hybrid_continuity_from_snapshot",
    "get_hybrid_continuity_store",
    "reset_hybrid_continuity_store",
]

# ---------------------------------------------------------------------------
# Sentinels
# ---------------------------------------------------------------------------

HYBRID_CONTINUITY_PERSISTENCE_IS_AUTHORITY: str = (
    "HYBRID_CONTINUITY_PERSISTENCE_IS_AUTHORITY: "
    "core/hybrid_continuity_persistence.py is the canonical durable snapshot "
    "layer for hybrid orchestration continuity records.  It does not replace "
    "the HybridOrchestrationContinuityRegistry runtime authority; it provides "
    "durable backing so records (including partial results) can be "
    "reconstructed after process restart."
)

HYBRID_CONTINUITY_PERSISTENCE_GAP_CLOSURE_SENTINEL: str = (
    "HYBRID_CONTINUITY_PERSISTENCE_GAP_CLOSURE::"
    "hybrid-continuity-persistence-restart-recovery-pr59-v2: "
    "This module closes the hybrid orchestration continuity persistence gap — "
    "before this module, the in-process registry was purely in-memory and all "
    "hybrid execution records were silently lost on restart, leaving the "
    "recovery coordinator with nothing to mark as interrupted."
)

HYBRID_CONTINUITY_RECOVERY_RESTORES_RECORDS_POLICY: str = (
    "POLICY::HYBRID_CONTINUITY_RECOVERY_RESTORES_RECORDS: On process restart, "
    "restore_hybrid_continuity_from_snapshot() re-hydrates all records from the "
    "most recent durable snapshot into the in-process "
    "HybridOrchestrationContinuityRegistry.  Once restored, "
    "HybridOrchestrationContinuityRegistry.mark_all_running_as_interrupted() "
    "transitions non-terminal records to 'interrupted', making restart "
    "disruption observable.  Partial results with status PRESERVED or MERGEABLE "
    "survive restart and are available for recovery-assisted resumption."
)

# ---------------------------------------------------------------------------
# Default store path
# ---------------------------------------------------------------------------

_DEFAULT_STORE_PATH: str = os.path.join(
    os.environ.get("GALAXY_DATA_DIR", "data"),
    "hybrid_continuity_snapshot.json",
)


# ---------------------------------------------------------------------------
# HybridContinuitySnapshot
# ---------------------------------------------------------------------------


@dataclass
class HybridContinuitySnapshot:
    """Serialisable snapshot of all hybrid orchestration continuity records.

    Parameters
    ----------
    snapshot_id:
        Unique identifier for this snapshot.
    created_at:
        Unix epoch seconds when the snapshot was written.
    process_pid:
        PID of the process that wrote the snapshot (informational).
    records:
        List of serialised :class:`~core.hybrid_orchestration_continuity
        .HybridOrchestrationRecord` dicts (via ``to_dict()``).
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
    def from_dict(cls, d: Dict[str, Any]) -> "HybridContinuitySnapshot":
        """Reconstruct from a serialised dict."""
        return cls(
            snapshot_id=d.get("snapshot_id", f"hcs_{uuid.uuid4().hex[:12]}"),
            created_at=float(d.get("created_at", time.time())),
            process_pid=int(d.get("process_pid", 0)),
            records=list(d.get("records", [])),
        )


# ---------------------------------------------------------------------------
# HybridContinuityPersistenceStore
# ---------------------------------------------------------------------------


class HybridContinuityPersistenceStore:
    """Thread-safe, file-backed durable store for hybrid continuity snapshots.

    Snapshots are written atomically: the data is first written to a temporary
    file in the same directory, then renamed over the target path.  This
    ensures the stored file is always complete and consistent even if the
    process is interrupted during a write.

    Parameters
    ----------
    store_path:
        Absolute path to the JSON snapshot file.  The parent directory must
        exist (or be creatable) before any write operations are attempted.
    """

    def __init__(self, store_path: Optional[str] = None) -> None:
        self._path = store_path or _DEFAULT_STORE_PATH
        self._lock = threading.Lock()

    @property
    def store_path(self) -> str:
        """Return the path of the backing file."""
        return self._path

    def save(self, snapshot: HybridContinuitySnapshot) -> None:
        """Atomically persist *snapshot* to the backing file.

        Parameters
        ----------
        snapshot:
            :class:`HybridContinuitySnapshot` to persist.
        """
        data = snapshot.to_dict()
        dir_path = os.path.dirname(self._path) or "."
        os.makedirs(dir_path, exist_ok=True)
        with self._lock:
            try:
                fd, tmp_path = tempfile.mkstemp(
                    dir=dir_path, suffix=".tmp"
                )
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as fh:
                        json.dump(data, fh, indent=2)
                    os.replace(tmp_path, self._path)
                except Exception:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
                    raise
            except Exception as exc:
                logger.warning(
                    "HybridContinuityPersistenceStore: save failed: %s", exc
                )
                raise

    def load(self) -> Optional[HybridContinuitySnapshot]:
        """Load and return the most recent snapshot, or ``None`` if unavailable.

        Returns ``None`` (rather than raising) when the file does not exist or
        contains invalid JSON so callers can degrade gracefully.
        """
        with self._lock:
            try:
                with open(self._path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                return HybridContinuitySnapshot.from_dict(data)
            except FileNotFoundError:
                return None
            except Exception as exc:
                logger.warning(
                    "HybridContinuityPersistenceStore: load failed: %s", exc
                )
                return None

    def delete(self) -> bool:
        """Remove the snapshot file.

        Returns
        -------
        bool
            True if the file was deleted; False if it did not exist or removal
            failed.
        """
        with self._lock:
            try:
                os.unlink(self._path)
                return True
            except OSError:
                return False


# ---------------------------------------------------------------------------
# Convenience wrappers
# ---------------------------------------------------------------------------


def save_hybrid_continuity_snapshot(
    records: List[Any],
    *,
    store: Optional[HybridContinuityPersistenceStore] = None,
) -> HybridContinuitySnapshot:
    """Snapshot *records* to the durable store and return the snapshot.

    Parameters
    ----------
    records:
        An iterable of objects that have a ``to_dict()`` method (specifically
        :class:`~core.hybrid_orchestration_continuity.HybridOrchestrationRecord`
        instances), or plain dicts.
    store:
        Optional explicit store.  Defaults to the process-level singleton.

    Returns
    -------
    :class:`HybridContinuitySnapshot`
        The snapshot that was written.
    """
    _store = store or get_hybrid_continuity_store()
    serialised: List[Dict[str, Any]] = []
    for rec in records:
        if isinstance(rec, dict):
            serialised.append(rec)
        else:
            try:
                serialised.append(rec.to_dict())
            except Exception as exc:
                logger.warning(
                    "save_hybrid_continuity_snapshot: skipping record "
                    "that could not be serialised: %s",
                    exc,
                )
    snapshot = HybridContinuitySnapshot(records=serialised)
    _store.save(snapshot)
    logger.info(
        "save_hybrid_continuity_snapshot: saved %d records (snapshot_id=%s)",
        len(serialised),
        snapshot.snapshot_id,
    )
    return snapshot


def load_hybrid_continuity_snapshot(
    *,
    store: Optional[HybridContinuityPersistenceStore] = None,
) -> Optional[HybridContinuitySnapshot]:
    """Load and return the most recent snapshot, or ``None`` if unavailable.

    Parameters
    ----------
    store:
        Optional explicit store.  Defaults to the process-level singleton.
    """
    _store = store or get_hybrid_continuity_store()
    return _store.load()


def restore_hybrid_continuity_from_snapshot(
    registry: Any = None,
    *,
    store: Optional[HybridContinuityPersistenceStore] = None,
) -> int:
    """Re-hydrate hybrid continuity records from the durable snapshot.

    Loads the most recent :class:`HybridContinuitySnapshot` and registers all
    non-terminal records into *registry* (or the process-level singleton
    :class:`~core.hybrid_orchestration_continuity
    .HybridOrchestrationContinuityRegistry`).  Callers should then call
    ``registry.mark_all_running_as_interrupted()`` to transition in-flight
    records to ``interrupted``.

    Terminal records are re-registered as well (for audit completeness) but
    the subsequent ``mark_all_running_as_interrupted`` call leaves them
    unchanged.

    Parameters
    ----------
    registry:
        The :class:`~core.hybrid_orchestration_continuity
        .HybridOrchestrationContinuityRegistry` to populate.  Defaults to the
        process-level singleton returned by
        :func:`~core.hybrid_orchestration_continuity.get_continuity_registry`.
    store:
        Optional explicit persistence store.  Defaults to the process-level
        singleton.

    Returns
    -------
    int
        Number of records re-hydrated into the registry.
    """
    from core.hybrid_orchestration_continuity import (
        HybridOrchestrationRecord,
        get_continuity_registry,
    )

    _registry = registry if registry is not None else get_continuity_registry()
    _store = store or get_hybrid_continuity_store()

    snapshot = _store.load()
    if snapshot is None:
        logger.info(
            "restore_hybrid_continuity_from_snapshot: no snapshot found "
            "(nothing to restore)"
        )
        return 0

    count = 0
    for rec_dict in snapshot.records:
        if not isinstance(rec_dict, dict):
            continue
        try:
            record = HybridOrchestrationRecord.from_dict(rec_dict)
            _registry.register(record)
            count += 1
        except Exception as exc:
            logger.warning(
                "restore_hybrid_continuity_from_snapshot: could not "
                "restore record: %s",
                exc,
            )

    logger.info(
        "restore_hybrid_continuity_from_snapshot: restored %d records "
        "from snapshot_id=%s",
        count,
        snapshot.snapshot_id,
    )
    return count


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------

_store_instance: Optional[HybridContinuityPersistenceStore] = None


def get_hybrid_continuity_store(
    store_path: Optional[str] = None,
) -> HybridContinuityPersistenceStore:
    """Return the process-level :class:`HybridContinuityPersistenceStore` singleton.

    Parameters
    ----------
    store_path:
        Optional path override.  Only used when creating the singleton for
        the first time.
    """
    global _store_instance
    if _store_instance is None:
        _store_instance = HybridContinuityPersistenceStore(
            store_path=store_path
        )
    return _store_instance


def reset_hybrid_continuity_store() -> None:
    """Reset the singleton (for testing)."""
    global _store_instance
    _store_instance = None
