#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/mesh/mesh_session_lifecycle.py
======================================
PR-1: Mesh Session Durable Runtime Foundation — Lifecycle Manager.

This module provides the **center-side durable session lifecycle manager**:
:class:`MeshSessionLifecycleManager`.  It is the bridge between the
stateless coordinator layer (:mod:`core.mesh.mesh_session_coordinator`) and
the persistent backing store (:mod:`core.mesh.mesh_session_persistence`), so
that every explicit session lifecycle transition is durably recorded.

Problem addressed
-----------------
The existing persistence store (:class:`~core.mesh.mesh_session_persistence.\
MeshSessionPersistenceStore`) provides raw save/load/recover operations, but
there is no component that:

1. Enforces the explicit session lifecycle model (create → activate →
   suspend → restore → terminate).
2. Automatically persists state on each transition.
3. Exposes a queryable summary of active/suspended sessions for truth
   projection purposes.
4. Provides a stable authority base for future restore / roaming / rebalance
   work to build on.

This module closes that gap.

Lifecycle model
---------------
::

    ┌────────────┐  create_session   ┌─────────────┐
    │  (none)    │ ────────────────► │   PENDING   │
    └────────────┘                   └──────┬──────┘
                                            │ activate_session
                                            ▼
                                     ┌─────────────┐
                         ◄───────── │   ACTIVE    │ ─────────────►
                    restore_session  └──────┬──────┘  suspend_session
                                            │
                                     ┌──────▼──────┐
                                     │  SUSPENDED  │
                                     └──────┬──────┘
                                            │ restore_session
                                            ▼
                                     ┌─────────────┐
                                     │  RESTORING  │
                                     └──────┬──────┘
                                            │ (completes → ACTIVE)
                                            ▼
                                     ┌─────────────┐
                                     │   ACTIVE    │
                                     └─────────────┘

    Any state → terminate_session → COMPLETED / FAILED / CANCELLED

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Persistence on every transition** — each lifecycle method calls the
  persistence store so that recovery has a stable, up-to-date anchor.
- **Graceful degradation** — every public method returns a valid result even
  when the persistence backend is unavailable.
- **No runtime truth ownership** — the manager does not replace any canonical
  truth source.  It provides a summary for truth projection but does not own
  the truth pipeline.
- **Thread-safe** — all session registry mutations are guarded by a lock.

Sentinels
---------
:data:`MESH_SESSION_LIFECYCLE_AUTHORITY`
    Affirms this module is the canonical lifecycle-to-persistence bridge.
:data:`LIFECYCLE_PERSISTS_ON_EVERY_TRANSITION_POLICY`
    Affirms that each lifecycle method triggers a persistence save.
:data:`LIFECYCLE_DOES_NOT_OWN_RUNTIME_TRUTH_POLICY`
    Affirms this module does not own or replace the outward truth pipeline;
    it exposes a read-only summary for downstream truth consumers.
:data:`DURABLE_FOUNDATION_FOR_RESTORE_ROAMING_REBALANCE_SENTINEL`
    Affirms this module provides the durable base that future restore,
    roaming, and rebalance work can build on.

Public API
----------
Classes:
    :class:`SessionRegistryEntry`
    :class:`MeshSessionLifecycleManager`

Functions:
    :func:`get_lifecycle_manager`
    :func:`reset_lifecycle_manager`
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.Mesh.Lifecycle")

__all__ = [
    # Sentinels
    "MESH_SESSION_LIFECYCLE_AUTHORITY",
    "LIFECYCLE_PERSISTS_ON_EVERY_TRANSITION_POLICY",
    "LIFECYCLE_DOES_NOT_OWN_RUNTIME_TRUTH_POLICY",
    "DURABLE_FOUNDATION_FOR_RESTORE_ROAMING_REBALANCE_SENTINEL",
    # Classes
    "SessionRegistryEntry",
    "MeshSessionLifecycleManager",
    # Functions
    "get_lifecycle_manager",
    "reset_lifecycle_manager",
]

# ---------------------------------------------------------------------------
# Sentinels
# ---------------------------------------------------------------------------

MESH_SESSION_LIFECYCLE_AUTHORITY: str = (
    "MESH_SESSION_LIFECYCLE_AUTHORITY::PR1_DURABLE_FOUNDATION_V1: "
    "core/mesh/mesh_session_lifecycle.py is the canonical lifecycle-to-persistence "
    "bridge for MeshSession / MeshSessionCoordinatorState.  Every explicit "
    "lifecycle transition MUST flow through MeshSessionLifecycleManager so that "
    "durable state is maintained without relying solely on transient coordinator memory."
)

LIFECYCLE_PERSISTS_ON_EVERY_TRANSITION_POLICY: str = (
    "LIFECYCLE_PERSIST_ON_TRANSITION::PR1_V1: "
    "Every call to create_session(), activate_session(), suspend_session(), "
    "restore_session(), and terminate_session() MUST trigger a save to the "
    "MeshSessionPersistenceStore so that the recovery chain always has a "
    "stable, up-to-date snapshot of session state."
)

LIFECYCLE_DOES_NOT_OWN_RUNTIME_TRUTH_POLICY: str = (
    "LIFECYCLE_TRUTH_BOUNDARY::PR1_V1: "
    "MeshSessionLifecycleManager does not own, replace, or shadow the "
    "canonical outward runtime truth pipeline.  It exposes a read-only "
    "active_session_summary() for truth projection consumers but does not "
    "modify TruthIntegrationLayer, OutwardRuntimeTruth, or any other canonical "
    "truth source."
)

DURABLE_FOUNDATION_FOR_RESTORE_ROAMING_REBALANCE_SENTINEL: str = (
    "DURABLE_FOUNDATION::PR1_V1: "
    "MeshSessionLifecycleManager establishes the durable foundation that "
    "future restore, roaming, and rebalance PRs can build on.  The lifecycle "
    "state persisted here is the authoritative anchor for session recovery "
    "across process restarts, device disconnects, and topology changes."
)

# ---------------------------------------------------------------------------
# Terminal status constants (matches persistence layer)
# ---------------------------------------------------------------------------

_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "timed_out"})


# ---------------------------------------------------------------------------
# SessionRegistryEntry
# ---------------------------------------------------------------------------


@dataclass
class SessionRegistryEntry:
    """In-memory record for a session tracked by the lifecycle manager.

    This is a lightweight, ephemeral complement to the durable
    :class:`~core.mesh.mesh_session_persistence.SnapshotRecord`.  It holds
    the current coordinator state reference and lifecycle metadata for fast
    in-process lookups.

    Attributes
    ----------
    session_id:
        Stable mesh session identifier.
    coordinator_state:
        The most recent coordinator state dict or object for this session.
    lifecycle_status:
        Current lifecycle status string (e.g. ``"pending"``, ``"active"``,
        ``"suspended"``, ``"restoring"``).
    created_at:
        Unix timestamp when this entry was created.
    updated_at:
        Unix timestamp of the most recent lifecycle transition.
    transition_log:
        Ordered list of ``(timestamp, status)`` tuples recording each
        lifecycle transition for diagnostics and replay.
    """

    session_id: str
    coordinator_state: Any
    lifecycle_status: str
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    transition_log: List[tuple] = field(default_factory=list)

    def record_transition(self, new_status: str) -> None:
        """Append *new_status* to the transition log and update timestamps."""
        self.transition_log.append((time.time(), new_status))
        self.lifecycle_status = new_status
        self.updated_at = time.time()

    def to_summary_dict(self) -> Dict[str, Any]:
        """Return a compact summary dict suitable for truth projection."""
        return {
            "session_id": self.session_id,
            "lifecycle_status": self.lifecycle_status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "transition_count": len(self.transition_log),
        }


# ---------------------------------------------------------------------------
# MeshSessionLifecycleManager
# ---------------------------------------------------------------------------


class MeshSessionLifecycleManager:
    """Center-side durable mesh session lifecycle manager.

    Bridges the coordinator layer with the persistence store so that every
    explicit session lifecycle transition is durably recorded.  Exposes a
    queryable in-memory registry of active and suspended sessions for truth
    projection purposes.

    Parameters
    ----------
    persistence_store:
        Optional explicit persistence store.  Uses the module singleton from
        :mod:`core.mesh.mesh_session_persistence` when not provided.
    """

    def __init__(self, persistence_store: Any = None) -> None:
        self._persistence: Any = persistence_store
        self._registry: Dict[str, SessionRegistryEntry] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lazy persistence accessor
    # ------------------------------------------------------------------

    def _get_store(self) -> Any:
        if self._persistence is not None:
            return self._persistence
        try:
            from core.mesh.mesh_session_persistence import get_persistence_store
            return get_persistence_store()
        except Exception as exc:
            logger.warning("MeshSessionLifecycleManager: persistence unavailable: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Lifecycle transitions
    # ------------------------------------------------------------------

    def create_session(
        self,
        coordinator_state: Any,
        *,
        session_id: Optional[str] = None,
    ) -> Optional[SessionRegistryEntry]:
        """Register a newly created mesh session and persist its initial state.

        Parameters
        ----------
        coordinator_state:
            A ``MeshSessionCoordinatorState`` or compatible dict representing
            the initial state of the session.
        session_id:
            Optional explicit session ID override.  If not provided, the ID
            is extracted from ``coordinator_state``.

        Returns
        -------
        SessionRegistryEntry or None
            The registry entry for the new session, or ``None`` if the session
            could not be registered (e.g. missing session_id).
        """
        try:
            sid = session_id or _extract_session_id(coordinator_state)
            if not sid:
                logger.warning("create_session: coordinator_state has no session_id — skipping")
                return None

            entry = SessionRegistryEntry(
                session_id=sid,
                coordinator_state=coordinator_state,
                lifecycle_status="pending",
            )
            entry.record_transition("pending")

            with self._lock:
                self._registry[sid] = entry

            self._persist(coordinator_state, expected_session_id=sid)
            logger.debug("create_session: registered session %s", sid)
            return entry
        except Exception as exc:
            logger.warning("create_session: failed for session %s: %s", session_id, exc)
            return None

    def activate_session(
        self,
        coordinator_state: Any,
        *,
        session_id: Optional[str] = None,
    ) -> Optional[SessionRegistryEntry]:
        """Transition a session to the ACTIVE lifecycle state.

        Parameters
        ----------
        coordinator_state:
            Updated coordinator state reflecting the active session.
        session_id:
            Optional explicit session ID override.

        Returns
        -------
        SessionRegistryEntry or None
        """
        return self._transition(
            coordinator_state,
            new_status="active",
            session_id=session_id,
            transition_name="activate_session",
        )

    def suspend_session(
        self,
        coordinator_state: Any,
        *,
        session_id: Optional[str] = None,
    ) -> Optional[SessionRegistryEntry]:
        """Durably suspend a session (transition to SUSPENDED).

        The session state is persisted so it can be restored later.  Suspended
        sessions retain their identity, topology, and participant records in
        the durable store and are not treated as terminal.

        Parameters
        ----------
        coordinator_state:
            Coordinator state snapshot at the time of suspension.
        session_id:
            Optional explicit session ID override.

        Returns
        -------
        SessionRegistryEntry or None
        """
        return self._transition(
            coordinator_state,
            new_status="suspended",
            session_id=session_id,
            transition_name="suspend_session",
        )

    def restore_session(
        self,
        coordinator_state: Any,
        *,
        session_id: Optional[str] = None,
    ) -> Optional[SessionRegistryEntry]:
        """Begin restoring a session from durable state (transition to RESTORING).

        The session enters the transient RESTORING state while the coordinator
        re-hydrates session identity, topology, and subtask assignments from
        the persistence store.  Call :meth:`activate_session` once restoration
        is complete to transition to ACTIVE.

        Parameters
        ----------
        coordinator_state:
            Coordinator state being re-hydrated (may be partially populated
            from the persistence snapshot).
        session_id:
            Optional explicit session ID override.

        Returns
        -------
        SessionRegistryEntry or None
        """
        return self._transition(
            coordinator_state,
            new_status="restoring",
            session_id=session_id,
            transition_name="restore_session",
        )

    def terminate_session(
        self,
        coordinator_state: Any,
        *,
        terminal_status: str = "completed",
        session_id: Optional[str] = None,
    ) -> Optional[SessionRegistryEntry]:
        """Terminate a session with a terminal status.

        The persistence store is updated to reflect the terminal status so the
        session is no longer included in recovery scans.

        Parameters
        ----------
        coordinator_state:
            Final coordinator state.
        terminal_status:
            One of ``"completed"``, ``"failed"``, or ``"cancelled"``.
            Defaults to ``"completed"``.
        session_id:
            Optional explicit session ID override.

        Returns
        -------
        SessionRegistryEntry or None
        """
        entry = self._transition(
            coordinator_state,
            new_status=terminal_status,
            session_id=session_id,
            transition_name="terminate_session",
        )
        if entry is not None:
            store = self._get_store()
            if store is not None:
                try:
                    store.mark_terminal(entry.session_id, status=terminal_status)
                except Exception as exc:
                    logger.warning(
                        "terminate_session: mark_terminal failed for %s: %s",
                        entry.session_id,
                        exc,
                    )
        return entry

    # ------------------------------------------------------------------
    # Registry queries
    # ------------------------------------------------------------------

    def get_session(self, session_id: str) -> Optional[SessionRegistryEntry]:
        """Return the registry entry for *session_id*, or ``None``."""
        with self._lock:
            return self._registry.get(session_id)

    def list_active_sessions(self) -> List[SessionRegistryEntry]:
        """Return all sessions in the ACTIVE lifecycle state."""
        with self._lock:
            return [e for e in self._registry.values() if e.lifecycle_status == "active"]

    def list_suspended_sessions(self) -> List[SessionRegistryEntry]:
        """Return all sessions in the SUSPENDED lifecycle state."""
        with self._lock:
            return [e for e in self._registry.values() if e.lifecycle_status == "suspended"]

    def list_restoring_sessions(self) -> List[SessionRegistryEntry]:
        """Return all sessions in the RESTORING lifecycle state."""
        with self._lock:
            return [e for e in self._registry.values() if e.lifecycle_status == "restoring"]

    def active_session_summary(self) -> Dict[str, Any]:
        """Return a compact read-only summary for truth projection consumers.

        This is the designated bridge between the lifecycle manager and the
        outward truth pipeline.  The outward truth layer reads from this
        summary rather than from coordinator memory directly.

        Returns
        -------
        dict
            Keys: ``active_count``, ``suspended_count``, ``restoring_count``,
            ``total_tracked``, ``sessions``.
        """
        with self._lock:
            entries = list(self._registry.values())

        active = [e for e in entries if e.lifecycle_status == "active"]
        suspended = [e for e in entries if e.lifecycle_status == "suspended"]
        restoring = [e for e in entries if e.lifecycle_status == "restoring"]

        return {
            "active_count": len(active),
            "suspended_count": len(suspended),
            "restoring_count": len(restoring),
            "total_tracked": len(entries),
            "sessions": [e.to_summary_dict() for e in entries],
            "authority": MESH_SESSION_LIFECYCLE_AUTHORITY,
        }

    def restore_from_persistence(self) -> int:
        """Re-hydrate all non-terminal sessions from the durable store.

        Loads every recoverable snapshot from the persistence store and
        registers it with lifecycle status ``"suspended"`` (it was persisted
        but not running in-process).  Callers should subsequently call
        :meth:`restore_session` / :meth:`activate_session` for sessions they
        wish to resume.

        Returns
        -------
        int
            Number of sessions restored into the registry.
        """
        store = self._get_store()
        if store is None:
            return 0

        try:
            records = store.list_recoverable()
        except Exception as exc:
            logger.warning("restore_from_persistence: scan failed: %s", exc)
            return 0

        restored = 0
        for record in records:
            sid = record.session_id
            with self._lock:
                if sid in self._registry:
                    continue  # already tracked in-process
                # All sessions loaded from persistence start as 'suspended'
                # regardless of their original persisted status (which could be
                # 'active', 'restoring', etc.).  This is intentional: a session
                # recovered from the backing store is not yet running in this
                # process; it is in a paused/dormant state until the caller
                # explicitly calls restore_session() → activate_session() to
                # resume it.  Preserving the original status would incorrectly
                # imply the session is currently executing.
                entry = SessionRegistryEntry(
                    session_id=sid,
                    coordinator_state=record.snapshot_dict,
                    lifecycle_status="suspended",
                    created_at=record.saved_at,
                    updated_at=record.saved_at,
                )
                entry.transition_log.append((record.saved_at, "suspended"))
                self._registry[sid] = entry
            restored += 1
            logger.debug(
                "restore_from_persistence: re-hydrated session %s (status=%s)",
                sid,
                record.overall_status,
            )

        logger.info(
            "restore_from_persistence: re-hydrated %d recoverable session(s)", restored
        )
        return restored

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _transition(
        self,
        coordinator_state: Any,
        *,
        new_status: str,
        session_id: Optional[str],
        transition_name: str,
    ) -> Optional[SessionRegistryEntry]:
        """Apply a lifecycle transition and persist the new state."""
        try:
            sid = session_id or _extract_session_id(coordinator_state)
            if not sid:
                logger.warning(
                    "%s: coordinator_state has no session_id — skipping", transition_name
                )
                return None

            with self._lock:
                entry = self._registry.get(sid)
                if entry is None:
                    # Auto-register sessions that were not explicitly created
                    entry = SessionRegistryEntry(
                        session_id=sid,
                        coordinator_state=coordinator_state,
                        lifecycle_status=new_status,
                    )
                    self._registry[sid] = entry
                else:
                    entry.coordinator_state = coordinator_state

                entry.record_transition(new_status)

            self._persist(coordinator_state, expected_session_id=sid)
            logger.debug("%s: session %s → %s", transition_name, sid, new_status)
            return entry
        except Exception as exc:
            logger.warning("%s: failed for %s: %s", transition_name, session_id, exc)
            return None

    def _persist(self, coordinator_state: Any, *, expected_session_id: str) -> None:
        """Persist coordinator state to the backing store (best-effort)."""
        store = self._get_store()
        if store is None:
            return
        try:
            store.save(coordinator_state)
        except Exception as exc:
            logger.warning(
                "_persist: failed for session %s: %s", expected_session_id, exc
            )


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------


def _extract_session_id(coordinator_state: Any) -> str:
    """Extract the session_id from a coordinator state object or dict."""
    if coordinator_state is None:
        return ""
    if isinstance(coordinator_state, dict):
        return str(coordinator_state.get("session_id") or "")
    return str(getattr(coordinator_state, "session_id", "") or "")


# ---------------------------------------------------------------------------
# Module-level singleton management
# ---------------------------------------------------------------------------

_manager_singleton: Optional[MeshSessionLifecycleManager] = None
_manager_lock = threading.Lock()


def get_lifecycle_manager(
    persistence_store: Any = None,
) -> MeshSessionLifecycleManager:
    """Return the process-level singleton :class:`MeshSessionLifecycleManager`.

    Parameters
    ----------
    persistence_store:
        Optional explicit persistence store override.  Only used when
        initialising the singleton for the first time.

    Returns
    -------
    MeshSessionLifecycleManager
    """
    global _manager_singleton
    with _manager_lock:
        if _manager_singleton is None:
            _manager_singleton = MeshSessionLifecycleManager(
                persistence_store=persistence_store
            )
        return _manager_singleton


def reset_lifecycle_manager() -> None:
    """Reset the module-level singleton — **for testing only**."""
    global _manager_singleton
    with _manager_lock:
        _manager_singleton = None
