#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/session_truth_snapshot.py
================================
Durable, file-backed session truth snapshot store for V2.

Background
----------
:class:`~core.canonical_session_truth.CanonicalSessionTruthRuntime` holds
session truth records in an in-memory ring buffer.  Before this module, a
V2 process restart cleared that ring buffer and all session truth context
was lost.

This module closes that gap by providing a standalone, file-backed snapshot
store that:

1. :class:`SessionTruthSnapshotStore` — thread-safe, file-backed storage for
   :class:`~core.canonical_session_truth.CanonicalSessionTruthRecord` dicts.
   Written atomically (write-then-rename) to prevent corruption.

2. :func:`get_session_truth_snapshot_store` / :func:`reset_session_truth_snapshot_store`
   — process-level singleton management.

3. :func:`restore_session_truth_from_snapshot` — reload snapshot records
   into a :class:`~core.canonical_session_truth.CanonicalSessionTruthRuntime`
   on V2 startup.

Design
------
- **Standalone** — no dependency on ``pydantic`` or other heavy packages.
- **Default-on** — the process-level singleton is created automatically.
- **Atomic writes** — write-then-rename pattern.
- **Bounded** — capped at ``max_records`` to prevent unbounded disk growth.
- **Thread-safe** — a :class:`threading.Lock` guards all reads and writes.

Sentinels
---------
:data:`SESSION_TRUTH_SNAPSHOT_IS_DURABLE_POLICY`
    Confirms this module closes the session truth durability gap.

Public API
----------
Classes:
    :class:`SessionTruthSnapshotStore`

Functions:
    :func:`get_session_truth_snapshot_store`
    :func:`reset_session_truth_snapshot_store`
    :func:`restore_session_truth_from_snapshot`
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.SessionTruthSnapshot")

# ---------------------------------------------------------------------------
# Default persistence path
# ---------------------------------------------------------------------------

_DEFAULT_SESSION_TRUTH_SNAPSHOT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "session_truth_snapshot.json",
)

# ---------------------------------------------------------------------------
# Policy sentinel
# ---------------------------------------------------------------------------

SESSION_TRUTH_SNAPSHOT_IS_DURABLE_POLICY: str = (
    "POLICY::SESSION_TRUTH_SNAPSHOT_DURABILITY_V1: "
    "SessionTruthSnapshotStore persists the most recent session truth records "
    "to a file-backed JSON snapshot so that V2 restart does not erase all "
    "session truth context.  The snapshot is written on every append() call "
    "and is loaded back into CanonicalSessionTruthRuntime on startup via "
    "restore_session_truth_from_snapshot()."
)

# ---------------------------------------------------------------------------
# SessionTruthSnapshotStore
# ---------------------------------------------------------------------------


class SessionTruthSnapshotStore:
    """Thread-safe, file-backed durable snapshot for session truth records.

    Maintains the most recent ``max_records``
    :class:`~core.canonical_session_truth.CanonicalSessionTruthRecord` dicts
    in a JSON file.  Written atomically (write-then-rename) so a partial write
    never corrupts the previous snapshot.

    Parameters
    ----------
    store_path:
        Path to the JSON snapshot file.  Defaults to
        ``data/session_truth_snapshot.json``.
    max_records:
        Maximum number of truth records retained.  Defaults to 200.
    """

    _DEFAULT_MAX = 200

    def __init__(
        self,
        store_path: Optional[str] = None,
        *,
        max_records: int = _DEFAULT_MAX,
    ) -> None:
        self._store_path = store_path or _DEFAULT_SESSION_TRUTH_SNAPSHOT_PATH
        self._max_records = max_records
        self._lock = threading.Lock()
        try:
            os.makedirs(
                os.path.dirname(os.path.abspath(self._store_path)), exist_ok=True
            )
        except Exception as exc:
            logger.warning(
                "SessionTruthSnapshotStore: could not create store directory: %s", exc
            )

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def append(self, record_dict: Dict[str, Any]) -> bool:
        """Append *record_dict* to the snapshot file.

        Loads the current snapshot (if any), appends the new record,
        trims to ``max_records``, then atomically rewrites the file.

        Returns True on success, False on error.
        """
        try:
            with self._lock:
                existing = self._load_locked()
                existing.append(record_dict)
                if len(existing) > self._max_records:
                    existing = existing[-self._max_records:]
                self._save_locked(existing)
            return True
        except Exception as exc:
            logger.warning(
                "SessionTruthSnapshotStore: append failed: %s", exc
            )
            return False

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def load(self) -> List[Dict[str, Any]]:
        """Return the stored session truth record dicts (newest last).

        Returns an empty list if no snapshot exists or loading fails.
        """
        with self._lock:
            return self._load_locked()

    # ------------------------------------------------------------------
    # Clear
    # ------------------------------------------------------------------

    def clear(self) -> bool:
        """Delete the snapshot file.  Safe to call when no file exists."""
        with self._lock:
            if not os.path.exists(self._store_path):
                return True
            try:
                os.unlink(self._store_path)
                return True
            except Exception as exc:
                logger.warning(
                    "SessionTruthSnapshotStore: clear failed: %s", exc
                )
                return False

    @property
    def store_path(self) -> str:
        return self._store_path

    # ------------------------------------------------------------------
    # Internal helpers (caller must hold self._lock)
    # ------------------------------------------------------------------

    def _load_locked(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self._store_path):
            return []
        try:
            with open(self._store_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            records = data.get("records", [])
            if isinstance(records, list):
                return list(records)
            return []
        except Exception as exc:
            logger.warning(
                "SessionTruthSnapshotStore: load failed: %s", exc
            )
            return []

    def _save_locked(self, records: List[Dict[str, Any]]) -> None:
        payload = json.dumps(
            {
                "schema": "session_truth_snapshot_v1",
                "count": len(records),
                "saved_at": time.time(),
                "records": records,
            },
            ensure_ascii=False,
        )
        store_dir = os.path.dirname(os.path.abspath(self._store_path))
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


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------

_snapshot_store_instance: Optional[SessionTruthSnapshotStore] = None
_snapshot_store_lock = threading.Lock()


def get_session_truth_snapshot_store(
    store_path: Optional[str] = None,
) -> SessionTruthSnapshotStore:
    """Return (or create) the process-level :class:`SessionTruthSnapshotStore` singleton."""
    global _snapshot_store_instance
    if _snapshot_store_instance is None:
        with _snapshot_store_lock:
            if _snapshot_store_instance is None:
                _snapshot_store_instance = SessionTruthSnapshotStore(
                    store_path=store_path
                )
    return _snapshot_store_instance


def reset_session_truth_snapshot_store() -> None:
    """Reset the process-level singleton (for test isolation)."""
    global _snapshot_store_instance
    with _snapshot_store_lock:
        _snapshot_store_instance = None


def restore_session_truth_from_snapshot(
    runtime: Optional[Any] = None,
    *,
    store: Optional[SessionTruthSnapshotStore] = None,
) -> int:
    """Reload the most recent session truth records from the snapshot into *runtime*.

    Called during startup recovery to restore the in-memory ring buffer with
    truth records that were persisted before the previous process terminated.

    Parameters
    ----------
    runtime:
        Optional :class:`~core.canonical_session_truth.CanonicalSessionTruthRuntime`
        target.  Defaults to the process-level singleton.
    store:
        Optional explicit :class:`SessionTruthSnapshotStore`.  Defaults to
        the process-level singleton.

    Returns
    -------
    int
        Number of records restored.
    """
    _store = store or get_session_truth_snapshot_store()
    raw_records = _store.load()
    if not raw_records:
        return 0
    if runtime is None:
        try:
            from core.canonical_session_truth import get_canonical_session_truth_runtime
            runtime = get_canonical_session_truth_runtime()
        except Exception as exc:
            logger.warning(
                "restore_session_truth_from_snapshot: could not get runtime: %s", exc
            )
            return 0
    restored = 0
    for rd in raw_records:
        try:
            from core.canonical_session_truth import CanonicalSessionTruthRecord
            rec = CanonicalSessionTruthRecord.from_dict(rd)
            runtime.record(rec)
            restored += 1
        except Exception as exc:
            logger.debug(
                "restore_session_truth_from_snapshot: skipping malformed record: %s",
                exc,
            )
    logger.info(
        "restore_session_truth_from_snapshot: restored %d/%d records",
        restored,
        len(raw_records),
    )
    return restored


__all__ = [
    "SESSION_TRUTH_SNAPSHOT_IS_DURABLE_POLICY",
    "SessionTruthSnapshotStore",
    "get_session_truth_snapshot_store",
    "reset_session_truth_snapshot_store",
    "restore_session_truth_from_snapshot",
]
