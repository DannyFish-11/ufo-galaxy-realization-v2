#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/mesh/mesh_session_persistence.py
========================================
Durable Mesh Session Persistence Store — PR-next (architecture gap closure).

Background
----------
The existing ``MeshSessionCoordinator`` (PR-37) and ``MeshSession`` contract
(PR-33) are contract-first: they provide a rich, serialisable data model but
do not persist state across process restarts or device disconnects.

The critical gap identified in ``MULTI_DEVICE_RUNTIME_MATURITY.md`` is:

    "Session persistence: MeshSession objects are rebuilt from
    BodyMeshRegistry each time — no durable store ensures continuity
    across process restarts or device disconnects."

This module closes that gap by providing:

1. :class:`MeshSessionPersistenceStore` — a thread-safe, pluggable store
   that saves coordinator snapshots to a local JSON file (default) and can
   be extended with any backend.

2. :func:`save_mesh_session_snapshot` — convenience entry point: serialise
   and durably persist a coordinator state.

3. :func:`load_mesh_session_snapshot` — load a stored coordinator snapshot
   by session_id.

4. :func:`recover_mesh_sessions` — re-hydrate all snapshots that were saved
   but not completed (i.e. whose ``overall_status`` is not terminal), so that
   the coordinator can resume tracking without starting from scratch.

5. :func:`list_recoverable_sessions` — lightweight scan for sessions that
   are present on-disk but have not reached a terminal state.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Graceful degradation** — every function returns a valid result even
  when the backing store is unavailable or returns bad data.
- **Schema-stable** — snapshots are stored as plain dicts (JSON) so future
  contract evolution does not silently corrupt existing snapshots; unrecognised
  fields are passed through without error.
- **Thread-safe** — a per-store :class:`threading.Lock` guards all reads
  and writes to the file index.
- **Pluggable** — :class:`MeshSessionPersistenceStore` uses a ``BaseBackend``
  protocol so any compatible backend (Redis, S3, SQLite, etc.) can be
  substituted without changing the public API.

Sentinels
---------
:data:`MESH_SESSION_PERSISTENCE_IS_AUTHORITY`
    Affirms this module is the canonical durable-state layer for mesh sessions.
:data:`MESH_SESSION_PERSISTENCE_GAP_CLOSURE_SENTINEL`
    Affirms this module directly closes the gap identified in
    ``MULTI_DEVICE_RUNTIME_MATURITY.md`` § "MeshSession — persistence".
:data:`RECOVERY_RESTORES_NON_TERMINAL_SESSIONS_POLICY`
    Affirms that recovery only restores sessions whose ``overall_status``
    is not terminal (not ``completed`` / ``failed`` / ``timed_out``).
:data:`PERSISTENCE_DOES_NOT_OWN_RUNTIME_TRUTH_POLICY`
    Affirms this module does not replace or shadow ``UDM`` or the canonical
    coordinator runtime; it is a durable snapshot layer, not a truth source.

Public API
----------
Classes:
    :class:`SnapshotRecord`
    :class:`MeshSessionPersistenceStore`

Functions:
    :func:`save_mesh_session_snapshot`
    :func:`load_mesh_session_snapshot`
    :func:`recover_mesh_sessions`
    :func:`list_recoverable_sessions`
    :func:`get_persistence_store`
    :func:`reset_persistence_store`
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

__all__ = [
    # Sentinels
    "MESH_SESSION_PERSISTENCE_IS_AUTHORITY",
    "MESH_SESSION_PERSISTENCE_GAP_CLOSURE_SENTINEL",
    "RECOVERY_RESTORES_NON_TERMINAL_SESSIONS_POLICY",
    "PERSISTENCE_DOES_NOT_OWN_RUNTIME_TRUTH_POLICY",
    # Classes
    "SnapshotRecord",
    "MeshSessionPersistenceStore",
    # Functions
    "save_mesh_session_snapshot",
    "load_mesh_session_snapshot",
    "recover_mesh_sessions",
    "list_recoverable_sessions",
    "get_persistence_store",
    "reset_persistence_store",
]

logger = logging.getLogger("Galaxy.Mesh.Persistence")

# ---------------------------------------------------------------------------
# Sentinels — machine-checkable policy assertions
# ---------------------------------------------------------------------------

MESH_SESSION_PERSISTENCE_IS_AUTHORITY: str = (
    "MESH_SESSION_PERSISTENCE_IS_AUTHORITY: "
    "core/mesh/mesh_session_persistence.py is the canonical durable-state "
    "layer for MeshSession / MeshSessionCoordinatorState snapshots."
)

MESH_SESSION_PERSISTENCE_GAP_CLOSURE_SENTINEL: str = (
    "MESH_SESSION_PERSISTENCE_GAP_CLOSURE: "
    "This module directly closes the persistence gap identified in "
    "docs/MULTI_DEVICE_RUNTIME_MATURITY.md §MeshSession — 'no durable store "
    "ensures continuity across process restarts or device disconnects'."
)

RECOVERY_RESTORES_NON_TERMINAL_SESSIONS_POLICY: str = (
    "RECOVERY_POLICY: recover_mesh_sessions() only re-hydrates sessions "
    "whose overall_status is not terminal (not completed/failed/timed_out)."
)

PERSISTENCE_DOES_NOT_OWN_RUNTIME_TRUTH_POLICY: str = (
    "PERSISTENCE_BOUNDARY: MeshSessionPersistenceStore is a snapshot layer. "
    "It does not replace UDM, BodyMeshRegistry, or any canonical truth source. "
    "It provides durable continuity only."
)

# ---------------------------------------------------------------------------
# Terminal statuses — sessions in these states are not recovered
# ---------------------------------------------------------------------------

_TERMINAL_STATUSES = frozenset({"completed", "failed", "timed_out", "cancelled"})

# Default directory for JSON file-backed persistence
_DEFAULT_STORE_DIR = os.path.join(
    os.environ.get("GALAXY_DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "data")),
    "mesh_sessions",
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class SnapshotRecord:
    """A persisted snapshot of a single mesh session coordinator state.

    Attributes
    ----------
    session_id:
        Stable identifier for the mesh session (matches
        ``MeshSessionCoordinatorState.session_id``).
    coordinator_id:
        Identifier of the coordinator state object instance.
    overall_status:
        Status string at snapshot time (e.g. ``"coordinating"``,
        ``"completed"``).
    snapshot_dict:
        The full ``to_dict()`` serialisation of
        ``MeshSessionCoordinatorState`` at snapshot time.
    saved_at:
        Unix timestamp when this snapshot was last written.
    version:
        Monotonically increasing counter for this session_id, for ordering
        snapshots when multiple exist.
    """

    session_id: str
    coordinator_id: str
    overall_status: str
    snapshot_dict: Dict[str, Any]
    saved_at: float = field(default_factory=time.time)
    version: int = 0

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "coordinator_id": self.coordinator_id,
            "overall_status": self.overall_status,
            "snapshot_dict": self.snapshot_dict,
            "saved_at": self.saved_at,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SnapshotRecord":
        return cls(
            session_id=d.get("session_id", ""),
            coordinator_id=d.get("coordinator_id", ""),
            overall_status=d.get("overall_status", "unknown"),
            snapshot_dict=d.get("snapshot_dict", {}),
            saved_at=d.get("saved_at", 0.0),
            version=d.get("version", 0),
        )

    def is_terminal(self) -> bool:
        """Return ``True`` if this snapshot's status is terminal."""
        return self.overall_status in _TERMINAL_STATUSES

    def is_recoverable(self) -> bool:
        """Return ``True`` if this session is a candidate for recovery."""
        return not self.is_terminal() and bool(self.session_id)


# ---------------------------------------------------------------------------
# MeshSessionPersistenceStore
# ---------------------------------------------------------------------------


class MeshSessionPersistenceStore:
    """Thread-safe, file-backed persistence store for mesh session snapshots.

    Each session's latest snapshot is stored as a single JSON file in
    ``store_dir``.  The filename is ``<session_id>.json``.

    The store can be subclassed or wrapped to use a different backend
    (Redis, SQLite, S3, etc.) by overriding :meth:`_write_record` and
    :meth:`_read_record`.

    Parameters
    ----------
    store_dir:
        Directory in which to persist JSON snapshot files.  Created
        automatically if it does not exist.  Defaults to
        ``data/mesh_sessions/`` relative to the repository root.
    """

    def __init__(self, store_dir: Optional[str] = None) -> None:
        self._store_dir = store_dir or _DEFAULT_STORE_DIR
        self._lock = threading.Lock()
        self._memory_cache: Dict[str, SnapshotRecord] = {}
        self._ensure_dir()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def save(self, coordinator_state: Any) -> Optional[SnapshotRecord]:
        """Persist a coordinator state snapshot.

        Parameters
        ----------
        coordinator_state:
            A ``MeshSessionCoordinatorState`` instance or a compatible dict
            (must expose ``session_id``, ``coordinator_id``,
            ``overall_status``, and ``to_dict()`` / be a dict).

        Returns
        -------
        SnapshotRecord
            The persisted record, or ``None`` if persistence failed.
        """
        try:
            snap_dict, session_id, coordinator_id, status = self._extract_fields(
                coordinator_state
            )
            if not session_id:
                logger.warning("save: coordinator_state has no session_id — skipping")
                return None

            with self._lock:
                existing = self._memory_cache.get(session_id)
                version = (existing.version + 1) if existing else 0

                record = SnapshotRecord(
                    session_id=session_id,
                    coordinator_id=coordinator_id,
                    overall_status=status,
                    snapshot_dict=snap_dict,
                    saved_at=time.time(),
                    version=version,
                )
                self._write_record(record)
                self._memory_cache[session_id] = record
                logger.debug(
                    "Persisted mesh session snapshot: session_id=%s status=%s v=%d",
                    session_id,
                    status,
                    version,
                )
                return record
        except Exception as exc:
            logger.warning("save: failed to persist session snapshot: %s", exc)
            return None

    def load(self, session_id: str) -> Optional[SnapshotRecord]:
        """Load the latest snapshot for a session.

        Parameters
        ----------
        session_id:
            Session identifier to load.

        Returns
        -------
        SnapshotRecord or None
            The latest snapshot, or ``None`` if not found.
        """
        try:
            with self._lock:
                if session_id in self._memory_cache:
                    return self._memory_cache[session_id]
                record = self._read_record(session_id)
                if record is not None:
                    self._memory_cache[session_id] = record
                return record
        except Exception as exc:
            logger.warning("load: failed to load session %s: %s", session_id, exc)
            return None

    def list_recoverable(self) -> List[SnapshotRecord]:
        """Return all persisted snapshots that are candidates for recovery.

        A snapshot is recoverable when its ``overall_status`` is not
        terminal (not ``completed`` / ``failed`` / ``timed_out``).

        Returns
        -------
        List[SnapshotRecord]
            Records sorted by ``saved_at`` ascending (oldest first).
        """
        try:
            all_records = self._scan_all_records()
            recoverable = [r for r in all_records if r.is_recoverable()]
            recoverable.sort(key=lambda r: r.saved_at)
            return recoverable
        except Exception as exc:
            logger.warning("list_recoverable: scan failed: %s", exc)
            return []

    def delete(self, session_id: str) -> bool:
        """Remove the snapshot for a session.

        Parameters
        ----------
        session_id:
            Session identifier to remove.

        Returns
        -------
        bool
            ``True`` if the record was removed, ``False`` otherwise.
        """
        try:
            with self._lock:
                self._memory_cache.pop(session_id, None)
                path = self._session_path(session_id)
                if os.path.exists(path):
                    os.remove(path)
                    logger.debug("Deleted mesh session snapshot: %s", session_id)
                    return True
            return False
        except Exception as exc:
            logger.warning("delete: failed for %s: %s", session_id, exc)
            return False

    def mark_terminal(self, session_id: str, status: str = "completed") -> bool:
        """Mark a session snapshot as terminal (not recoverable).

        Parameters
        ----------
        session_id:
            Session to mark.
        status:
            Terminal status string (default: ``"completed"``).

        Returns
        -------
        bool
            ``True`` if the record was updated.
        """
        try:
            record = self.load(session_id)
            if record is None:
                return False
            updated = SnapshotRecord(
                session_id=record.session_id,
                coordinator_id=record.coordinator_id,
                overall_status=status,
                snapshot_dict=record.snapshot_dict,
                saved_at=time.time(),
                version=record.version + 1,
            )
            with self._lock:
                self._write_record(updated)
                self._memory_cache[session_id] = updated
            return True
        except Exception as exc:
            logger.warning("mark_terminal: failed for %s: %s", session_id, exc)
            return False

    # ------------------------------------------------------------------
    # Overridable backend helpers
    # ------------------------------------------------------------------

    def _write_record(self, record: SnapshotRecord) -> None:
        """Write a ``SnapshotRecord`` to the file backend."""
        path = self._session_path(record.session_id)
        tmp_path = path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(record.to_dict(), fh, indent=2, default=str)
            os.replace(tmp_path, path)
        except Exception:
            # Clean up tmp file on error
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise

    def _read_record(self, session_id: str) -> Optional[SnapshotRecord]:
        """Read a ``SnapshotRecord`` from the file backend."""
        path = self._session_path(session_id)
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return SnapshotRecord.from_dict(data)

    def _scan_all_records(self) -> List[SnapshotRecord]:
        """Scan the file backend for all persisted records."""
        records: List[SnapshotRecord] = []
        try:
            for filename in os.listdir(self._store_dir):
                if not filename.endswith(".json"):
                    continue
                session_id = filename[:-5]  # strip .json
                try:
                    record = self._read_record(session_id)
                    if record is not None:
                        records.append(record)
                except Exception as inner:
                    logger.debug("_scan_all_records: skipping %s: %s", filename, inner)
        except OSError as exc:
            logger.debug("_scan_all_records: store_dir not accessible: %s", exc)
        return records

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_dir(self) -> None:
        try:
            os.makedirs(self._store_dir, exist_ok=True)
        except OSError as exc:
            logger.warning("MeshSessionPersistenceStore: cannot create store_dir %s: %s",
                           self._store_dir, exc)

    def _session_path(self, session_id: str) -> str:
        # Sanitise session_id to avoid path traversal
        safe_id = "".join(c if c.isalnum() or c in "-_." else "_" for c in session_id)
        return os.path.join(self._store_dir, f"{safe_id}.json")

    @staticmethod
    def _extract_fields(
        coordinator_state: Any,
    ) -> tuple[Dict[str, Any], str, str, str]:
        """Extract serialisable fields from a coordinator state."""
        if coordinator_state is None:
            return {}, "", "", "unknown"

        if isinstance(coordinator_state, dict):
            snap_dict = coordinator_state
            session_id = str(coordinator_state.get("session_id") or "")
            coordinator_id = str(coordinator_state.get("coordinator_id") or "")
            status = str(coordinator_state.get("overall_status") or "unknown")
        else:
            # Pydantic model or dataclass
            try:
                snap_dict = coordinator_state.to_dict()
            except AttributeError:
                try:
                    snap_dict = coordinator_state.model_dump()
                except AttributeError:
                    snap_dict = vars(coordinator_state) if hasattr(coordinator_state, "__dict__") else {}
            session_id = str(getattr(coordinator_state, "session_id", "") or "")
            coordinator_id = str(getattr(coordinator_state, "coordinator_id", "") or "")
            status = str(getattr(coordinator_state, "overall_status", "unknown") or "unknown")

        return snap_dict, session_id, coordinator_id, status


# ---------------------------------------------------------------------------
# Module-level singleton management
# ---------------------------------------------------------------------------

_store_singleton: Optional[MeshSessionPersistenceStore] = None
_store_lock = threading.Lock()


def get_persistence_store(
    store_dir: Optional[str] = None,
) -> MeshSessionPersistenceStore:
    """Return the module-level singleton persistence store.

    Parameters
    ----------
    store_dir:
        Override the store directory.  Only used on first call (when the
        singleton is being initialised).

    Returns
    -------
    MeshSessionPersistenceStore
    """
    global _store_singleton
    with _store_lock:
        if _store_singleton is None:
            _store_singleton = MeshSessionPersistenceStore(store_dir=store_dir)
        return _store_singleton


def reset_persistence_store() -> None:
    """Reset the module-level singleton (primarily for test isolation)."""
    global _store_singleton
    with _store_lock:
        _store_singleton = None


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------


def save_mesh_session_snapshot(
    coordinator_state: Any,
    *,
    store: Optional[MeshSessionPersistenceStore] = None,
) -> Optional[SnapshotRecord]:
    """Persist a coordinator state snapshot.

    Parameters
    ----------
    coordinator_state:
        ``MeshSessionCoordinatorState`` or compatible dict.
    store:
        Optional explicit store instance.  Uses the module singleton when
        not provided.

    Returns
    -------
    SnapshotRecord or None
    """
    _store = store or get_persistence_store()
    return _store.save(coordinator_state)


def load_mesh_session_snapshot(
    session_id: str,
    *,
    store: Optional[MeshSessionPersistenceStore] = None,
) -> Optional[SnapshotRecord]:
    """Load the latest snapshot for a session.

    Parameters
    ----------
    session_id:
        Mesh session identifier.
    store:
        Optional explicit store instance.

    Returns
    -------
    SnapshotRecord or None
    """
    _store = store or get_persistence_store()
    return _store.load(session_id)


def recover_mesh_sessions(
    *,
    store: Optional[MeshSessionPersistenceStore] = None,
) -> List[SnapshotRecord]:
    """Return all non-terminal snapshots that are candidates for recovery.

    Callers can iterate the returned records and re-hydrate coordinator
    state using ``from_dict`` helpers in the contracts layer.

    Only sessions whose ``overall_status`` is not in
    ``{completed, failed, timed_out, cancelled}`` are returned.

    Parameters
    ----------
    store:
        Optional explicit store instance.

    Returns
    -------
    List[SnapshotRecord]
        Recoverable snapshots sorted oldest-first.
    """
    _store = store or get_persistence_store()
    records = _store.list_recoverable()
    logger.info("recover_mesh_sessions: found %d recoverable session(s)", len(records))
    return records


def list_recoverable_sessions(
    *,
    store: Optional[MeshSessionPersistenceStore] = None,
) -> List[str]:
    """Return a list of session IDs that are recoverable.

    Lightweight scan — returns only the IDs.

    Parameters
    ----------
    store:
        Optional explicit store instance.

    Returns
    -------
    List[str]
    """
    records = recover_mesh_sessions(store=store)
    return [r.session_id for r in records]
