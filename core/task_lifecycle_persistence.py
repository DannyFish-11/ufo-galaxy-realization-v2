#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/task_lifecycle_persistence.py
=====================================
Durable file-backed persistence store for in-flight task lifecycle state.

Background
----------
The :class:`~core.task_envelope_lifecycle_registry.TaskEnvelopeLifecycleRegistry`
is an in-memory store.  Without a persistence layer, every process restart
silently discards all in-flight task records, forcing the task source to replay
work from scratch.  This module provides the durable backing layer so that
in-flight task lifecycle state survives across restarts.

Design principles
-----------------
- **Additive only** — this module does not modify any existing module.
- **Graceful degradation** — all I/O is wrapped so that storage errors never
  propagate to callers; a warning is logged instead.
- **Explicit recovery classification** — the :data:`TASK_RECOVERY_POLICY` and
  :data:`TASK_STATE_RECOVERY_CLASSIFICATION` constants document which lifecycle
  states are resumable, replay-only, re-issuable, or terminal after interruption.
- **Idempotent writes** — writing the same record twice is safe; the latest
  version wins.

Storage format
--------------
Records are stored as a JSON file (an object keyed by task_id) in
``<store_dir>/in_flight_tasks.json``.  On recovery, the file is read back
and each record is returned as a :class:`~core.task_envelope_lifecycle_registry
.PendingEnvelopeRecord`.

Policy sentinels
----------------
:data:`IN_FLIGHT_TASK_LIFECYCLE_IS_DURABLE_POLICY`
    Declares that in-flight task lifecycle state is now durably stored.
:data:`TASK_STATE_RECOVERY_CLASSIFICATION`
    Documents the post-interruption classification for each known lifecycle
    state.
:data:`TASK_RECOVERY_POLICY`
    Human-readable summary of recovery semantics.

Public API
----------
Classes:
    :class:`TaskLifecyclePersistenceStore`
Functions:
    :func:`get_task_lifecycle_persistence_store`
    :func:`reset_task_lifecycle_persistence_store`
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.TaskLifecyclePersistence")

__all__ = [
    # Sentinels
    "IN_FLIGHT_TASK_LIFECYCLE_IS_DURABLE_POLICY",
    "TASK_STATE_RECOVERY_CLASSIFICATION",
    "TASK_RECOVERY_POLICY",
    # Classes
    "TaskLifecyclePersistenceStore",
    # Functions
    "get_task_lifecycle_persistence_store",
    "reset_task_lifecycle_persistence_store",
]

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

IN_FLIGHT_TASK_LIFECYCLE_IS_DURABLE_POLICY: str = (
    "POLICY::IN_FLIGHT_TASK_LIFECYCLE_IS_DURABLE: In-flight task envelope "
    "lifecycle state is now persisted to "
    "core.task_lifecycle_persistence.TaskLifecyclePersistenceStore "
    "(file-backed JSON store).  On process restart, the "
    "RuntimeRestartRecoveryCoordinator reconstructs interrupted in-flight "
    "records so that operators can inspect, replay, or explicitly terminate "
    "them rather than having them silently disappear."
)

TASK_STATE_RECOVERY_CLASSIFICATION: Dict[str, str] = {
    # owner stage → post-interruption classification
    "gateway_ingress": "replay_required",
    "routing": "replay_required",
    "device_dispatch": "resumable_if_device_reconnects",
    "cross_device": "resumable_if_device_reconnects",
    "result_completion": "terminal_presumed_complete",
    # Fallback for any unrecognised owner stage
    "_unknown": "replay_required",
}
"""Mapping from :class:`~core.task_envelope_lifecycle_registry.LifecycleOwner`
value strings to post-interruption recovery classification.

Classification values
---------------------
``replay_required``
    The task had not been dispatched to a device yet (or the dispatch result
    is unknown).  The task source **must** re-issue the original request.
``resumable_if_device_reconnects``
    The task was already dispatched; if the target device reconnects it may
    resume or acknowledge completion.  The operator should surface this task
    via :meth:`~core.task_envelope_lifecycle_registry
    .TaskEnvelopeLifecycleRegistry.resume_for_device`.
``terminal_presumed_complete``
    The result had already arrived and was being written back.  The task is
    presumed complete; no re-dispatch is needed.
"""

TASK_RECOVERY_POLICY: str = (
    "POLICY::TASK_RECOVERY: After a process restart, in-flight tasks are "
    "reconstructed from the durable lifecycle store with the lifecycle owner "
    "stage used to classify each task. "
    "gateway_ingress/routing tasks are classified as replay_required; "
    "device_dispatch/cross_device tasks are classified as "
    "resumable_if_device_reconnects (they may be re-surfaced when the target "
    "device reconnects); "
    "result_completion tasks are classified as terminal_presumed_complete. "
    "Tasks that have exceeded their declared timeout at recovery time are "
    "always classified as terminal and are NOT re-registered. "
    "Duplicate task_ids already present in the live registry are skipped "
    "(idempotency invariant)."
)

# ---------------------------------------------------------------------------
# Default paths
# ---------------------------------------------------------------------------

_DEFAULT_STORE_DIR = os.path.join(os.getcwd(), "data")
_STORE_FILENAME = "in_flight_tasks.json"


# ---------------------------------------------------------------------------
# TaskLifecyclePersistenceStore
# ---------------------------------------------------------------------------

class TaskLifecyclePersistenceStore:
    """File-backed persistence store for in-flight task lifecycle records.

    Parameters
    ----------
    store_dir:
        Directory where the JSON store file is kept.  Defaults to
        ``<cwd>/data``.  The directory is created on first write if it does
        not already exist.

    Thread-safety
    -------------
    This class is **not** thread-safe.  It is intended to be used from the
    same asyncio event loop thread as the
    :class:`~core.task_envelope_lifecycle_registry.TaskEnvelopeLifecycleRegistry`.
    """

    def __init__(self, store_dir: Optional[str] = None) -> None:
        self._store_dir = store_dir or _DEFAULT_STORE_DIR
        self._store_path = os.path.join(self._store_dir, _STORE_FILENAME)

    # ── Writes ───────────────────────────────────────────────────────────────

    def save(self, record_dict: Dict[str, Any]) -> None:
        """Persist a single in-flight record.

        The record is merged into the existing store file.  If the task_id
        already exists, the entry is overwritten (latest-wins semantics).

        Parameters
        ----------
        record_dict:
            A JSON-serialisable dict as returned by
            :meth:`~core.task_envelope_lifecycle_registry
            .PendingEnvelopeRecord.to_dict`.
        """
        task_id = record_dict.get("task_id", "")
        if not task_id:
            logger.warning("TaskLifecyclePersistence.save: record has no task_id; skipped")
            return
        try:
            current = self._load_raw()
            current[task_id] = record_dict
            self._write_raw(current)
            logger.debug("TaskLifecyclePersistence.save: task_id=%s persisted", task_id)
        except Exception as exc:
            logger.warning(
                "TaskLifecyclePersistence.save failed for task_id=%s: %s", task_id, exc
            )

    def delete(self, task_id: str) -> bool:
        """Remove a task record from the store (on completion or terminal state).

        Parameters
        ----------
        task_id:
            The task to remove.

        Returns
        -------
        bool
            ``True`` if the record was present and removed; ``False`` if it
            was not found.
        """
        try:
            current = self._load_raw()
            if task_id not in current:
                return False
            del current[task_id]
            self._write_raw(current)
            logger.debug("TaskLifecyclePersistence.delete: task_id=%s removed", task_id)
            return True
        except Exception as exc:
            logger.warning(
                "TaskLifecyclePersistence.delete failed for task_id=%s: %s", task_id, exc
            )
            return False

    def clear(self) -> int:
        """Remove all persisted records and return the number removed."""
        try:
            current = self._load_raw()
            count = len(current)
            self._write_raw({})
            logger.debug("TaskLifecyclePersistence.clear: removed %d records", count)
            return count
        except Exception as exc:
            logger.warning("TaskLifecyclePersistence.clear failed: %s", exc)
            return 0

    # ── Reads ────────────────────────────────────────────────────────────────

    def load_all(self) -> List[Dict[str, Any]]:
        """Return all persisted in-flight records as a list of dicts.

        Never raises; returns an empty list on I/O or parse errors.
        """
        try:
            raw = self._load_raw()
            return list(raw.values())
        except Exception as exc:
            logger.warning("TaskLifecyclePersistence.load_all failed: %s", exc)
            return []

    def record_count(self) -> int:
        """Return the number of persisted records."""
        return len(self._load_raw_safe())

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _load_raw(self) -> Dict[str, Any]:
        """Return the raw store dict; raises on parse errors."""
        if not os.path.exists(self._store_path):
            return {}
        try:
            with open(self._store_path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"TaskLifecyclePersistence: failed to parse store at "
                f"{self._store_path!r}: {exc}"
            ) from exc

    def _load_raw_safe(self) -> Dict[str, Any]:
        """Return the raw store dict; returns {} on any error."""
        try:
            return self._load_raw()
        except Exception:
            return {}

    def _write_raw(self, data: Dict[str, Any]) -> None:
        """Write the raw store dict atomically (write-then-rename)."""
        os.makedirs(self._store_dir, exist_ok=True)
        tmp_path = self._store_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp_path, self._store_path)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_store_instance: Optional[TaskLifecyclePersistenceStore] = None


def get_task_lifecycle_persistence_store(
    store_dir: Optional[str] = None,
) -> TaskLifecyclePersistenceStore:
    """Return (or lazily create) the process-level singleton store.

    Parameters
    ----------
    store_dir:
        Override the store directory.  Only used when creating the singleton
        for the first time; ignored on subsequent calls.
    """
    global _store_instance
    if _store_instance is None:
        _store_instance = TaskLifecyclePersistenceStore(store_dir=store_dir)
    return _store_instance


def reset_task_lifecycle_persistence_store() -> None:
    """Reset the singleton (for testing)."""
    global _store_instance
    _store_instance = None
