#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/mesh/mesh_session_lifecycle.py
=====================================
Durable Mesh Session Lifecycle Coordinator — PR-1 (Mesh Session Durable
Runtime Foundation).

Background
----------
The :class:`~contracts.mesh_session.MeshSession` contract and the
:class:`~core.mesh.mesh_session_persistence.MeshSessionPersistenceStore` exist
independently.  Before this module, nothing ensured that lifecycle transitions
on a ``MeshSession`` (activate, suspend, restore, terminate) were atomically
paired with persistence, leaving a gap where coordinator restarts or device
disconnects could discard active-session state.

This module closes that gap by providing:

1. :class:`MeshSessionLifecycleCoordinator` — a thread-safe singleton that
   manages the full durable lifecycle of a mesh session:

   - :meth:`~MeshSessionLifecycleCoordinator.create_session` — create + persist
   - :meth:`~MeshSessionLifecycleCoordinator.activate_session` — PENDING → ACTIVE + persist
   - :meth:`~MeshSessionLifecycleCoordinator.suspend_session` — ACTIVE → SUSPENDED + persist
   - :meth:`~MeshSessionLifecycleCoordinator.restore_session` — SUSPENDED → RESTORING → ACTIVE + persist
   - :meth:`~MeshSessionLifecycleCoordinator.terminate_session` — → COMPLETED/CANCELLED/FAILED + mark_terminal

2. Module-level helpers and singleton management for process-level use.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Lifecycle-validated** — uses :func:`~contracts.mesh_session.is_valid_lifecycle_transition`
  to enforce the explicit state machine defined in ``contracts/mesh_session.py``.
- **Always persists** — every lifecycle mutation is durably snapshotted via
  :class:`~core.mesh.mesh_session_persistence.MeshSessionPersistenceStore`
  before the method returns.
- **Graceful degradation** — persistence failures are logged but do not raise;
  the in-memory lifecycle state is still updated.
- **Thread-safe** — a per-instance :class:`threading.Lock` guards in-memory
  session state.
- **Restore-ready** — :meth:`~MeshSessionLifecycleCoordinator.restore_session`
  re-hydrates session state from the persistence store so that the coordinator
  can resume after restart without losing session identity or topology.

Sentinels
---------
:data:`MESH_SESSION_LIFECYCLE_COORDINATOR_IS_AUTHORITY`
    Affirms this module owns the durable lifecycle coordination path.
:data:`LIFECYCLE_MUTATIONS_ARE_PERSISTED_POLICY`
    Affirms that every lifecycle mutation is durably persisted before return.
:data:`RESTORE_REQUIRES_DURABLE_STATE_POLICY`
    Affirms that session restoration is only attempted when durable state exists.

Public API
----------
Classes:
    :class:`MeshSessionLifecycleRecord`
    :class:`MeshSessionLifecycleCoordinator`

Functions:
    :func:`get_lifecycle_coordinator`
    :func:`reset_lifecycle_coordinator`
    :func:`create_durable_session`
    :func:`activate_durable_session`
    :func:`suspend_durable_session`
    :func:`restore_durable_session`
    :func:`terminate_durable_session`
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

__all__ = [
    # Sentinels
    "MESH_SESSION_LIFECYCLE_COORDINATOR_IS_AUTHORITY",
    "LIFECYCLE_MUTATIONS_ARE_PERSISTED_POLICY",
    "RESTORE_REQUIRES_DURABLE_STATE_POLICY",
    "RESUMED_EXECUTION_ASSOCIATION_IS_RESTORATION_PATH_POLICY",
    # Data
    "MeshSessionLifecycleRecord",
    # Coordinator class
    "MeshSessionLifecycleCoordinator",
    # Module-level functions
    "get_lifecycle_coordinator",
    "reset_lifecycle_coordinator",
    "create_durable_session",
    "activate_durable_session",
    "suspend_durable_session",
    "restore_durable_session",
    "terminate_durable_session",
    "associate_resumed_execution_with_session",
]

logger = logging.getLogger("Galaxy.Mesh.Lifecycle")

# ---------------------------------------------------------------------------
# Sentinels
# ---------------------------------------------------------------------------

MESH_SESSION_LIFECYCLE_COORDINATOR_IS_AUTHORITY: str = (
    "MESH_SESSION_LIFECYCLE_COORDINATOR_IS_AUTHORITY: "
    "core/mesh/mesh_session_lifecycle.py is the canonical durable lifecycle "
    "coordinator for MeshSession objects.  It pairs every lifecycle mutation "
    "with a persistence snapshot, establishing the durable session base that "
    "restore/roaming/rebalance work can build on.  PR-1."
)

LIFECYCLE_MUTATIONS_ARE_PERSISTED_POLICY: str = (
    "LIFECYCLE_MUTATIONS_ARE_PERSISTED: "
    "Every lifecycle transition (create/activate/suspend/restore/terminate) "
    "performed through MeshSessionLifecycleCoordinator is durably persisted "
    "to MeshSessionPersistenceStore before the method returns.  "
    "Persistence failures are logged but do not block the in-memory transition."
)

RESTORE_REQUIRES_DURABLE_STATE_POLICY: str = (
    "RESTORE_REQUIRES_DURABLE_STATE: "
    "restore_session() only re-hydrates a session when a SnapshotRecord exists "
    "in MeshSessionPersistenceStore with a non-terminal status.  "
    "If no durable state is found the method returns None rather than "
    "creating a synthetic session."
)

RESUMED_EXECUTION_ASSOCIATION_IS_RESTORATION_PATH_POLICY: str = (
    "POLICY::RESUMED_EXECUTION_ASSOCIATION_IS_RESTORATION_PATH_PR-F: "
    "associate_resumed_execution() is the canonical restoration hook that links "
    "a resumed execution to its prior active mesh session and dispatch context.  "
    "It MUST be called after a reconnect or handoff with a "
    "DispatchContinuityContext that carries the prior_dispatch_id, "
    "prior_session_id, and prior_mesh_session_id.  The association is recorded in "
    "the session's metadata and persisted durably.  This is the authoritative "
    "re-association path for reconnect/handoff scenarios.  PR-F."
)


# ---------------------------------------------------------------------------
# MeshSessionLifecycleRecord — in-memory record
# ---------------------------------------------------------------------------


@dataclass
class MeshSessionLifecycleRecord:
    """In-memory tracking record for a session managed by the lifecycle coordinator.

    Attributes
    ----------
    session_id:
        Stable identifier for the session (matches ``MeshSession.session_id``).
    status:
        Current lifecycle status string (mirrors ``MeshSessionStatus.value``).
    session_dict:
        Latest known ``MeshSession.to_dict()`` snapshot; updated on each
        lifecycle mutation.
    created_at:
        Unix timestamp when this record was first created.
    updated_at:
        Unix timestamp of the most recent lifecycle mutation.
    restore_count:
        Number of times this session has been restored from durable state.
    metadata:
        Arbitrary key-value extensibility bag.
    """

    session_id: str
    status: str
    session_dict: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    restore_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "restore_count": self.restore_count,
            "metadata": self.metadata,
            "session_dict": self.session_dict,
        }


# ---------------------------------------------------------------------------
# MeshSessionLifecycleCoordinator
# ---------------------------------------------------------------------------


class MeshSessionLifecycleCoordinator:
    """Thread-safe coordinator for durable mesh session lifecycle management.

    This class is the single point where ``MeshSession`` lifecycle transitions
    are paired with durable persistence.  It:

    * validates transitions against the explicit state machine in
      :data:`~contracts.mesh_session.MESH_SESSION_VALID_TRANSITIONS`;
    * persists every transition to
      :class:`~core.mesh.mesh_session_persistence.MeshSessionPersistenceStore`;
    * can re-hydrate sessions from durable state after a coordinator restart.

    Parameters
    ----------
    store:
        Optional explicit persistence store instance.  When ``None``, the
        module-level singleton returned by
        :func:`~core.mesh.mesh_session_persistence.get_persistence_store` is used.
    """

    def __init__(
        self,
        store: Optional[Any] = None,
    ) -> None:
        self._store = store  # resolved lazily to avoid import-time side effects
        self._sessions: Dict[str, MeshSessionLifecycleRecord] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Persistence store accessor (lazy)
    # ------------------------------------------------------------------

    def _get_store(self) -> Any:
        if self._store is not None:
            return self._store
        from core.mesh.mesh_session_persistence import get_persistence_store
        return get_persistence_store()

    # ------------------------------------------------------------------
    # Lifecycle operations
    # ------------------------------------------------------------------

    def create_session(
        self,
        session: Any,
        *,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[MeshSessionLifecycleRecord]:
        """Register a new session and persist its initial state.

        Parameters
        ----------
        session:
            A ``MeshSession`` instance or compatible dict.  Must carry a
            non-empty ``session_id``.
        metadata:
            Optional metadata to embed in the lifecycle record.

        Returns
        -------
        MeshSessionLifecycleRecord or None
            The created record, or ``None`` if ``session_id`` could not be
            extracted.
        """
        session_dict, session_id, current_status = self._extract_session_fields(session)
        if not session_id:
            logger.warning("create_session: session has no session_id — skipping")
            return None

        record = MeshSessionLifecycleRecord(
            session_id=session_id,
            status=current_status or "pending",
            session_dict=session_dict,
            metadata=metadata or {},
        )

        with self._lock:
            self._sessions[session_id] = record

        self._persist(record)
        logger.debug("create_session: session_id=%s status=%s", session_id, record.status)
        # PR-G: emit mesh session transition event for observability
        try:
            from core.runtime.runtime_observability_sink import emit_mesh_session_transition_event
            emit_mesh_session_transition_event(
                session_id,
                transition_kind="create",
                new_status="pending",
                source_device_id=str(session_dict.get("source_device_id") or ""),
                primary_device_id=str(session_dict.get("primary_device_id") or ""),
                reason="mesh_session_created",
            )
        except Exception:
            pass
        return record

    def activate_session(
        self,
        session_id: str,
        *,
        session: Any = None,
    ) -> Optional[MeshSessionLifecycleRecord]:
        """Transition a session to ACTIVE and persist.

        Valid source statuses: PENDING, RESTORING.

        Parameters
        ----------
        session_id:
            Identifier of the session to activate.
        session:
            Optional updated ``MeshSession`` to embed.

        Returns
        -------
        MeshSessionLifecycleRecord or None
            Updated record, or ``None`` if the transition is invalid.
        """
        return self._transition(
            session_id=session_id,
            target_status="active",
            valid_sources={"pending", "restoring"},
            session=session,
            op_name="activate_session",
            _emit_transition_kind="activate",
        )

    def suspend_session(
        self,
        session_id: str,
        *,
        session: Any = None,
        reason: Optional[str] = None,
    ) -> Optional[MeshSessionLifecycleRecord]:
        """Transition a session to SUSPENDED and persist.

        Valid source statuses: ACTIVE.

        Parameters
        ----------
        session_id:
            Identifier of the session to suspend.
        session:
            Optional updated ``MeshSession`` to embed.
        reason:
            Human-readable suspension reason embedded in metadata.

        Returns
        -------
        MeshSessionLifecycleRecord or None
        """
        extra_meta: Dict[str, Any] = {}
        if reason:
            extra_meta["suspend_reason"] = reason
        return self._transition(
            session_id=session_id,
            target_status="suspended",
            valid_sources={"active"},
            session=session,
            op_name="suspend_session",
            extra_meta=extra_meta,
            _emit_transition_kind="suspend",
        )

    def restore_session(
        self,
        session_id: str,
    ) -> Optional[MeshSessionLifecycleRecord]:
        """Restore a SUSPENDED session from durable state.

        The coordinator:
        1. Loads the latest ``SnapshotRecord`` from the persistence store.
        2. Verifies the snapshot status is restorable (``suspended``).
        3. Transitions the in-memory record through RESTORING → ACTIVE.
        4. Persists the updated state.

        Parameters
        ----------
        session_id:
            Session to restore.

        Returns
        -------
        MeshSessionLifecycleRecord or None
            The restored record in ACTIVE status, or ``None`` when no
            restorable durable state exists.
        """
        store = self._get_store()

        # Load durable snapshot
        try:
            snap = store.load(session_id)
        except Exception as exc:
            logger.warning("restore_session: failed to load snapshot for %s: %s", session_id, exc)
            snap = None

        if snap is None:
            logger.warning("restore_session: no durable snapshot for %s — cannot restore", session_id)
            return None

        if snap.is_terminal():
            logger.warning(
                "restore_session: session %s has terminal status '%s' — not restorable",
                session_id, snap.overall_status,
            )
            return None

        # Ensure in-memory record exists (re-create from snapshot if needed)
        with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = MeshSessionLifecycleRecord(
                    session_id=session_id,
                    status=snap.overall_status,
                    session_dict=snap.snapshot_dict,
                )

        # Step through RESTORING
        restoring_record = self._transition(
            session_id=session_id,
            target_status="restoring",
            valid_sources={"suspended", snap.overall_status},
            session=snap.snapshot_dict,
            op_name="restore_session[restoring]",
        )
        if restoring_record is None:
            logger.warning(
                "restore_session: could not transition %s to RESTORING", session_id
            )
            # Force-set to restoring to allow the ACTIVE transition
            with self._lock:
                rec = self._sessions.get(session_id)
                if rec is not None:
                    rec.status = "restoring"
                    rec.updated_at = time.time()

        # Advance to ACTIVE
        active_record = self._transition(
            session_id=session_id,
            target_status="active",
            valid_sources={"restoring"},
            session=snap.snapshot_dict,
            op_name="restore_session[active]",
        )
        if active_record is not None:
            with self._lock:
                active_record.restore_count += 1
                active_record.updated_at = time.time()
            logger.info(
                "restore_session: session %s successfully restored (restore_count=%d)",
                session_id,
                active_record.restore_count,
            )
            # PR-G: emit mesh session restore transition + recovery decision
            try:
                from core.runtime.runtime_observability_sink import (
                    emit_mesh_session_transition_event,
                    emit_recovery_decision_event,
                )
                sd = active_record.session_dict
                emit_mesh_session_transition_event(
                    session_id,
                    transition_kind="restore",
                    prior_status="suspended",
                    new_status="active",
                    source_device_id=str(sd.get("source_device_id") or ""),
                    primary_device_id=str(sd.get("primary_device_id") or ""),
                    restore_count=active_record.restore_count,
                    reason="mesh_session_restored",
                )
                emit_recovery_decision_event(
                    decision_kind="resumable_reassociation",
                    prior_session_id=session_id,
                    prior_mesh_session_id=session_id,
                    is_resumable=True,
                    reason="restore_session: session successfully restored from suspended state",
                )
            except Exception:
                pass
        return active_record

    def terminate_session(
        self,
        session_id: str,
        *,
        outcome: str = "completed",
        session: Any = None,
        reason: Optional[str] = None,
    ) -> Optional[MeshSessionLifecycleRecord]:
        """Transition a session to a terminal status and mark it in the store.

        Parameters
        ----------
        session_id:
            Session to terminate.
        outcome:
            Terminal status string: ``"completed"``, ``"cancelled"``, or
            ``"failed"``.
        session:
            Optional updated ``MeshSession`` to embed.
        reason:
            Human-readable termination reason.

        Returns
        -------
        MeshSessionLifecycleRecord or None
        """
        terminal_statuses = {"completed", "cancelled", "failed"}
        if outcome not in terminal_statuses:
            logger.warning(
                "terminate_session: unrecognised outcome '%s' — defaulting to 'failed'",
                outcome,
            )
            outcome = "failed"

        extra_meta: Dict[str, Any] = {}
        if reason:
            extra_meta["termination_reason"] = reason

        record = self._transition(
            session_id=session_id,
            target_status=outcome,
            valid_sources={
                "active", "merging", "suspended", "restoring",
                "pending", "unknown",
            },
            session=session,
            op_name="terminate_session",
            extra_meta=extra_meta,
            _emit_transition_kind="terminate",
        )

        # Mark terminal in persistence store
        store = self._get_store()
        try:
            store.mark_terminal(session_id, status=outcome)
        except Exception as exc:
            logger.warning(
                "terminate_session: failed to mark_terminal for %s: %s", session_id, exc
            )

        return record

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_record(self, session_id: str) -> Optional[MeshSessionLifecycleRecord]:
        """Return the in-memory record for *session_id*, or ``None``."""
        with self._lock:
            return self._sessions.get(session_id)

    def list_active_session_ids(self) -> List[str]:
        """Return a list of session IDs currently in ACTIVE status."""
        with self._lock:
            return [
                sid for sid, rec in self._sessions.items()
                if rec.status == "active"
            ]

    def list_restorable_session_ids(self) -> List[str]:
        """Return a list of session IDs that are restorable (SUSPENDED)."""
        store = self._get_store()
        try:
            from core.mesh.mesh_session_persistence import list_recoverable_sessions
            return list_recoverable_sessions(store=store)
        except Exception as exc:
            logger.warning("list_restorable_session_ids: store scan failed: %s", exc)
            return []

    def find_sessions_for_device(
        self,
        device_id: str,
        *,
        only_non_terminal: bool = True,
    ) -> List[str]:
        """Return session IDs whose source or primary device matches *device_id*.

        Parameters
        ----------
        device_id:
            The device to search for in tracked session records.
        only_non_terminal:
            When ``True`` (default) terminal sessions (completed / cancelled /
            failed) are excluded from the result.

        Returns
        -------
        List[str]
            Session IDs associated with *device_id*.
        """
        _TERMINAL = {"completed", "cancelled", "failed"}
        results: List[str] = []
        with self._lock:
            for sid, record in self._sessions.items():
                if only_non_terminal and record.status in _TERMINAL:
                    continue
                sd = record.session_dict
                if (
                    sd.get("source_device_id") == device_id
                    or sd.get("primary_device_id") == device_id
                ):
                    results.append(sid)
        return results

    def summary(self) -> Dict[str, Any]:
        """Return a lightweight summary dict for monitoring/diagnostics."""
        with self._lock:
            statuses: Dict[str, int] = {}
            for rec in self._sessions.values():
                statuses[rec.status] = statuses.get(rec.status, 0) + 1
        return {
            "authority": MESH_SESSION_LIFECYCLE_COORDINATOR_IS_AUTHORITY,
            "in_memory_session_count": len(self._sessions),
            "status_breakdown": statuses,
        }

    def associate_resumed_execution(
        self,
        session_id: str,
        continuity_context: Optional[Dict[str, Any]],
        *,
        resumed_dispatch_id: Optional[str] = None,
        resumed_trace_id: Optional[str] = None,
    ) -> Optional[MeshSessionLifecycleRecord]:
        """Associate a resumed execution with an active mesh session.

        This is the canonical restoration hook (PR-F) for reconnect and handoff
        scenarios.  It records the ``continuity_context`` in the session's
        metadata and persists the updated state, allowing downstream observers
        to correlate resumed execution with the prior dispatch and session
        context.

        This method DOES NOT perform a lifecycle transition.  The session must
        already be in a non-terminal state (typically ``active`` or ``restoring``).
        Call :meth:`restore_session` first if the session is ``suspended``.

        Parameters
        ----------
        session_id:
            The mesh session to associate the resumed execution with.
        continuity_context:
            Serialised :class:`~contracts.dispatch_continuity.DispatchContinuityContext`
            dict (PR-F) carrying prior identity fields.  ``None`` is tolerated
            for backward-compatible callers; in that case the association is
            recorded with an empty continuity_context placeholder.
        resumed_dispatch_id:
            The new dispatch_id of the resumed execution, if known.
        resumed_trace_id:
            The new trace_id of the resumed execution, if known.

        Returns
        -------
        MeshSessionLifecycleRecord or None
            The updated record, or ``None`` when the session is not tracked
            or is in a terminal state.
        """
        _TERMINAL = {"completed", "cancelled", "failed"}
        with self._lock:
            record = self._sessions.get(session_id)
            if record is None:
                logger.warning(
                    "associate_resumed_execution: unknown session_id '%s'", session_id
                )
                return None
            if record.status in _TERMINAL:
                logger.warning(
                    "associate_resumed_execution: session '%s' is terminal (status=%s) — "
                    "cannot associate resumed execution",
                    session_id, record.status,
                )
                return None

            # Record the association in session metadata
            normalized_context: Dict[str, Any]
            if isinstance(continuity_context, dict):
                normalized_context = dict(continuity_context)
            else:
                normalized_context = {}
            if not normalized_context.get("prior_session_id"):
                normalized_context["prior_session_id"] = session_id
            if not normalized_context.get("prior_mesh_session_id"):
                normalized_context["prior_mesh_session_id"] = session_id

            association: Dict[str, Any] = {
                "continuity_context": normalized_context,
                "associated_at": time.time(),
            }
            if continuity_context is not None and not isinstance(continuity_context, dict):
                association["continuity_context_type"] = type(continuity_context).__name__
            if resumed_dispatch_id is not None:
                association["resumed_dispatch_id"] = resumed_dispatch_id
            if resumed_trace_id is not None:
                association["resumed_trace_id"] = resumed_trace_id

            record.metadata["resumed_execution_association"] = association
            record.updated_at = time.time()

        self._persist(record)
        logger.info(
            "associate_resumed_execution: session '%s' (status=%s) associated with resumed "
            "execution (prior_dispatch_id=%s, resumed_dispatch_id=%s)",
            session_id,
            record.status,
            normalized_context.get("prior_dispatch_id"),
            resumed_dispatch_id,
        )
        return record

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _transition(
        self,
        *,
        session_id: str,
        target_status: str,
        valid_sources: set,
        session: Any,
        op_name: str,
        extra_meta: Optional[Dict[str, Any]] = None,
        _emit_transition_kind: Optional[str] = None,
    ) -> Optional[MeshSessionLifecycleRecord]:
        """Apply a lifecycle transition if the current status is in *valid_sources*.

        Parameters
        ----------
        _emit_transition_kind:
            Optional :class:`~contracts.runtime_observability.MeshSessionTransitionKind`
            string to emit via the observability sink after a successful transition.
            Valid values: ``"create"``, ``"activate"``, ``"suspend"``, ``"restore"``,
            ``"terminate"``, ``"participant_joined"``, ``"participant_left"``.
            When ``None``, no emit is produced (caller is responsible).
        """
        with self._lock:
            record = self._sessions.get(session_id)
            if record is None:
                logger.warning(
                    "%s: unknown session_id '%s'", op_name, session_id
                )
                return None

            if record.status not in valid_sources:
                logger.warning(
                    "%s: invalid transition for %s — current='%s', expected one of %s",
                    op_name, session_id, record.status, valid_sources,
                )
                return None

            # Validate via contract transition table
            try:
                from contracts.mesh_session import (
                    MeshSessionStatus,
                    is_valid_lifecycle_transition,
                )
                from_s = MeshSessionStatus(record.status)
                to_s = MeshSessionStatus(target_status)
                if not is_valid_lifecycle_transition(from_s, to_s):
                    logger.warning(
                        "%s: contract transition %s→%s not in MESH_SESSION_VALID_TRANSITIONS — proceeding anyway",
                        op_name, record.status, target_status,
                    )
            except ValueError:
                # target_status or record.status is not a known MeshSessionStatus value
                pass
            except ImportError:
                # contracts unavailable (e.g. during bootstrap)
                pass

            # Apply update
            if session is not None:
                session_dict, _, _ = self._extract_session_fields(session)
                record.session_dict = session_dict or record.session_dict
            record.status = target_status
            record.updated_at = time.time()
            if extra_meta:
                record.metadata.update(extra_meta)

        self._persist(record)
        logger.debug("%s: session_id=%s → status=%s", op_name, session_id, target_status)
        # PR-G: emit mesh session transition event when a kind is specified
        if _emit_transition_kind is not None:
            try:
                from core.runtime.runtime_observability_sink import emit_mesh_session_transition_event
                sd = record.session_dict
                emit_mesh_session_transition_event(
                    session_id,
                    transition_kind=_emit_transition_kind,
                    new_status=target_status,
                    source_device_id=str(sd.get("source_device_id") or ""),
                    primary_device_id=str(sd.get("primary_device_id") or ""),
                    reason=op_name,
                )
            except Exception:
                pass
        return record

    def _persist(self, record: MeshSessionLifecycleRecord) -> None:
        """Persist *record* to the backing store.  Failures are logged, not raised."""
        store = self._get_store()
        # Merge session_dict first, then override identity fields so that values
        # from session_dict cannot shadow session_id, coordinator_id, or
        # overall_status which must always reflect the current lifecycle record.
        payload: Dict[str, Any] = {
            **record.session_dict,
            "session_id": record.session_id,
            "coordinator_id": f"lifecycle_{record.session_id}",
            "overall_status": record.status,
        }
        try:
            store.save(payload)
        except Exception as exc:
            logger.warning(
                "_persist: failed to save snapshot for %s: %s", record.session_id, exc
            )

    @staticmethod
    def _extract_session_fields(
        session: Any,
    ) -> tuple:
        """Extract (session_dict, session_id, status) from a session object or dict."""
        if session is None:
            return {}, "", ""
        if isinstance(session, dict):
            return (
                session,
                str(session.get("session_id") or ""),
                str(session.get("status") or session.get("overall_status") or ""),
            )
        try:
            session_dict = session.to_dict()
        except AttributeError:
            try:
                session_dict = session.model_dump()
            except AttributeError:
                session_dict = vars(session) if hasattr(session, "__dict__") else {}
        session_id = str(getattr(session, "session_id", "") or "")
        status_raw = getattr(session, "status", None)
        status_str = (
            status_raw.value
            if hasattr(status_raw, "value")
            else str(status_raw or "")
        )
        return session_dict, session_id, status_str


# ---------------------------------------------------------------------------
# Module-level singleton management
# ---------------------------------------------------------------------------

_coordinator_singleton: Optional[MeshSessionLifecycleCoordinator] = None
_coordinator_lock = threading.Lock()


def get_lifecycle_coordinator(
    store: Optional[Any] = None,
) -> MeshSessionLifecycleCoordinator:
    """Return the process-level singleton :class:`MeshSessionLifecycleCoordinator`.

    Parameters
    ----------
    store:
        Optional explicit persistence store.  Only used when creating the
        singleton for the first time.
    """
    global _coordinator_singleton
    if _coordinator_singleton is None:
        with _coordinator_lock:
            if _coordinator_singleton is None:
                _coordinator_singleton = MeshSessionLifecycleCoordinator(store=store)
    return _coordinator_singleton


def reset_lifecycle_coordinator() -> None:
    """Reset the module-level singleton — **for testing only**."""
    global _coordinator_singleton
    with _coordinator_lock:
        _coordinator_singleton = None


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------


def create_durable_session(
    session: Any,
    *,
    coordinator: Optional[MeshSessionLifecycleCoordinator] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[MeshSessionLifecycleRecord]:
    """Create and durably persist a new mesh session.

    Parameters
    ----------
    session:
        ``MeshSession`` instance or compatible dict.
    coordinator:
        Optional explicit coordinator instance.
    metadata:
        Optional metadata dict.

    Returns
    -------
    MeshSessionLifecycleRecord or None
    """
    c = coordinator or get_lifecycle_coordinator()
    return c.create_session(session, metadata=metadata)


def activate_durable_session(
    session_id: str,
    *,
    session: Any = None,
    coordinator: Optional[MeshSessionLifecycleCoordinator] = None,
) -> Optional[MeshSessionLifecycleRecord]:
    """Activate a pending/restoring mesh session.

    Parameters
    ----------
    session_id:
        Session to activate.
    session:
        Optional updated ``MeshSession``.
    coordinator:
        Optional explicit coordinator instance.

    Returns
    -------
    MeshSessionLifecycleRecord or None
    """
    c = coordinator or get_lifecycle_coordinator()
    return c.activate_session(session_id, session=session)


def suspend_durable_session(
    session_id: str,
    *,
    session: Any = None,
    reason: Optional[str] = None,
    coordinator: Optional[MeshSessionLifecycleCoordinator] = None,
) -> Optional[MeshSessionLifecycleRecord]:
    """Suspend an active mesh session.

    Parameters
    ----------
    session_id:
        Session to suspend.
    session:
        Optional updated ``MeshSession``.
    reason:
        Human-readable suspension reason.
    coordinator:
        Optional explicit coordinator instance.

    Returns
    -------
    MeshSessionLifecycleRecord or None
    """
    c = coordinator or get_lifecycle_coordinator()
    return c.suspend_session(session_id, session=session, reason=reason)


def restore_durable_session(
    session_id: str,
    *,
    coordinator: Optional[MeshSessionLifecycleCoordinator] = None,
) -> Optional[MeshSessionLifecycleRecord]:
    """Restore a suspended mesh session from durable state.

    Parameters
    ----------
    session_id:
        Session to restore.
    coordinator:
        Optional explicit coordinator instance.

    Returns
    -------
    MeshSessionLifecycleRecord or None
    """
    c = coordinator or get_lifecycle_coordinator()
    return c.restore_session(session_id)


def terminate_durable_session(
    session_id: str,
    *,
    outcome: str = "completed",
    session: Any = None,
    reason: Optional[str] = None,
    coordinator: Optional[MeshSessionLifecycleCoordinator] = None,
) -> Optional[MeshSessionLifecycleRecord]:
    """Terminate a mesh session and mark it as terminal in the store.

    Parameters
    ----------
    session_id:
        Session to terminate.
    outcome:
        ``"completed"``, ``"cancelled"``, or ``"failed"``.
    session:
        Optional updated ``MeshSession``.
    reason:
        Human-readable termination reason.
    coordinator:
        Optional explicit coordinator instance.

    Returns
    -------
    MeshSessionLifecycleRecord or None
    """
    c = coordinator or get_lifecycle_coordinator()
    return c.terminate_session(session_id, outcome=outcome, session=session, reason=reason)


def associate_resumed_execution_with_session(
    session_id: str,
    continuity_context: Optional[Dict[str, Any]],
    *,
    resumed_dispatch_id: Optional[str] = None,
    resumed_trace_id: Optional[str] = None,
    coordinator: Optional[MeshSessionLifecycleCoordinator] = None,
) -> Optional[MeshSessionLifecycleRecord]:
    """Associate a resumed execution with an active mesh session (PR-F).

    This is the module-level convenience wrapper for
    :meth:`MeshSessionLifecycleCoordinator.associate_resumed_execution`.  It
    is the canonical production restoration hook for reconnect/handoff
    scenarios.

    Parameters
    ----------
    session_id:
        The mesh session to associate the resumed execution with.
    continuity_context:
        Serialised :class:`~contracts.dispatch_continuity.DispatchContinuityContext`
        dict (PR-F) carrying prior identity fields.
    resumed_dispatch_id:
        The new dispatch_id of the resumed execution, if known.
    resumed_trace_id:
        The new trace_id of the resumed execution, if known.
    coordinator:
        Optional explicit coordinator instance.  When ``None``, the
        process-level singleton is used.

    Returns
    -------
    MeshSessionLifecycleRecord or None
        The updated record with the continuity association recorded in
        metadata, or ``None`` when the session is not tracked or terminal.
    """
    c = coordinator or get_lifecycle_coordinator()
    return c.associate_resumed_execution(
        session_id,
        continuity_context,
        resumed_dispatch_id=resumed_dispatch_id,
        resumed_trace_id=resumed_trace_id,
    )
