#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/runtime_restart_recovery.py
===================================
PR-5: Runtime Restart / Recovery Coordinator

Background
----------
After a process restart, device disconnect, or transient infrastructure failure
several runtime-critical state components are lost unless explicitly recovered:

1. **MeshSession state** — coordinator progress, participant status, barrier
   advancement.  Recovered via
   :func:`~core.mesh.mesh_session_persistence.recover_mesh_sessions`.

2. **BodyMeshRegistry state** — device roles, primary-body assignment, session
   associations.  Recovered via
   :func:`~core.mesh.body_mesh_persistence.restore_body_mesh_from_snapshot`.

3. **WebRTC task bindings** — task-scoped transport bindings that were active
   at the time of the restart.  These are in-memory ring-buffer records; they
   are by design **not** durably recovered (the transport itself is gone after
   a restart).  This boundary is made **explicit** by this module.

This module provides a single entry-point —
:class:`RuntimeRestartRecoveryCoordinator` — that orchestrates recovery of the
above components and produces a :class:`RuntimeRecoveryReport` describing what
was recovered, what was intentionally skipped, and any remaining limitations.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Graceful degradation** — every recovery step is independent; failure in
  one step does not prevent others from running.
- **Explicit non-goals** — what is intentionally ephemeral (e.g. WebRTC
  transport bindings) is documented, not silently dropped.
- **Fully serialisable** — :class:`RuntimeRecoveryReport` can be converted to
  a dict for operator observability.

Non-goals (intentionally ephemeral)
------------------------------------
The following runtime artifacts are **not** recovered across restarts because
they are inherently transport-layer or session-layer state that is invalidated
when the underlying connection is lost:

* **WebRTC transport bindings** — transport sessions are gone after restart;
  the in-memory ring buffer is cleared.  New bindings will be created when
  tasks are re-dispatched.
* **In-flight task queues** — tasks pending in memory-only queues at the time
  of restart.  These must be replayed by the task source.
* **Device heartbeat state** — devices re-register on reconnect; stale
  heartbeat state is discarded.

Sentinels
---------
:data:`RUNTIME_RESTART_RECOVERY_IS_AUTHORITY`
    Affirms this module is the canonical restart/recovery entry-point.
:data:`MESH_SESSION_RECOVERY_IS_DURABLE_POLICY`
    Affirms that MeshSession recovery uses the durable persistence store.
:data:`BODY_MESH_RECOVERY_IS_DURABLE_POLICY`
    Affirms that BodyMeshRegistry recovery uses the durable persistence store.
:data:`WEBRTC_BINDINGS_ARE_EPHEMERAL_POLICY`
    Affirms that WebRTC transport bindings are intentionally ephemeral and
    are NOT recovered across process restarts.
:data:`RUNTIME_RESTART_RECOVERY_PR5_SENTINEL`
    Monotonic sentinel string for PR-5 feature identification.

Public API
----------
Classes:
    :class:`RuntimeRecoveryReport`
    :class:`RuntimeRestartRecoveryCoordinator`

Functions:
    :func:`run_startup_recovery`
    :func:`get_recovery_coordinator`
    :func:`reset_recovery_coordinator`
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.RuntimeRestartRecovery")

__all__ = [
    # Sentinels
    "RUNTIME_RESTART_RECOVERY_IS_AUTHORITY",
    "MESH_SESSION_RECOVERY_IS_DURABLE_POLICY",
    "BODY_MESH_RECOVERY_IS_DURABLE_POLICY",
    "WEBRTC_BINDINGS_ARE_EPHEMERAL_POLICY",
    "RUNTIME_RESTART_RECOVERY_PR5_SENTINEL",
    # Classes
    "RuntimeRecoveryReport",
    "RuntimeRestartRecoveryCoordinator",
    # Functions
    "run_startup_recovery",
    "get_recovery_coordinator",
    "reset_recovery_coordinator",
]

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

RUNTIME_RESTART_RECOVERY_IS_AUTHORITY: str = (
    "RUNTIME_RESTART_RECOVERY_IS_AUTHORITY: "
    "core/runtime_restart_recovery.py is the canonical entry-point for "
    "orchestrating Galaxy runtime state recovery after process restart, "
    "device disconnect, or transient infrastructure failure (PR-5)."
)

MESH_SESSION_RECOVERY_IS_DURABLE_POLICY: str = (
    "POLICY::MESH_SESSION_RECOVERY_IS_DURABLE: MeshSession recovery uses "
    "core.mesh.mesh_session_persistence.recover_mesh_sessions() which reads "
    "from the durable file-backed persistence store.  Non-terminal sessions "
    "are re-hydrated; terminal sessions are left as-is."
)

BODY_MESH_RECOVERY_IS_DURABLE_POLICY: str = (
    "POLICY::BODY_MESH_RECOVERY_IS_DURABLE: BodyMeshRegistry recovery uses "
    "core.mesh.body_mesh_persistence.restore_body_mesh_from_snapshot() which "
    "reads from the durable file-backed snapshot store and calls "
    "registry.register() for each recovered entry."
)

WEBRTC_BINDINGS_ARE_EPHEMERAL_POLICY: str = (
    "POLICY::WEBRTC_BINDINGS_ARE_EPHEMERAL: WebRTC transport bindings in "
    "core.webrtc_task_lifecycle are INTENTIONALLY not recovered across process "
    "restarts.  The underlying transport (peer connection, ICE state) is "
    "invalidated by a restart.  New bindings are created when tasks are "
    "re-dispatched.  This is a documented non-goal, not a gap."
)

RUNTIME_RESTART_RECOVERY_PR5_SENTINEL: str = (
    "RUNTIME_RESTART_RECOVERY_PR5::runtime-restart-recovery-coordinator-pr5-v1"
)


# ---------------------------------------------------------------------------
# RuntimeRecoveryReport
# ---------------------------------------------------------------------------


@dataclass
class RuntimeRecoveryReport:
    """Report produced by a recovery run.

    Attributes
    ----------
    recovery_id
        Unique identifier for this recovery run.
    started_at
        Wall-clock timestamp when recovery began.
    completed_at
        Wall-clock timestamp when recovery completed (or None if not yet done).
    mesh_sessions_recovered
        Number of non-terminal mesh sessions restored from durable storage.
    mesh_sessions_skipped
        Number of mesh sessions that were terminal and intentionally skipped.
    body_mesh_entries_restored
        Number of BodyMeshRegistry entries restored from the durable snapshot.
    webrtc_bindings_cleared
        True — WebRTC bindings are always cleared on restart (intentional).
    errors
        List of non-fatal error strings encountered during recovery.
    non_goals
        Explicit list of what is intentionally not recovered (for reviewability).
    """

    recovery_id: str = field(default_factory=lambda: f"rcv_{uuid.uuid4().hex[:12]}")
    started_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    mesh_sessions_recovered: int = 0
    mesh_sessions_skipped: int = 0
    body_mesh_entries_restored: int = 0
    webrtc_bindings_cleared: bool = True
    errors: List[str] = field(default_factory=list)
    non_goals: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return {
            "recovery_id": self.recovery_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "mesh_sessions_recovered": self.mesh_sessions_recovered,
            "mesh_sessions_skipped": self.mesh_sessions_skipped,
            "body_mesh_entries_restored": self.body_mesh_entries_restored,
            "webrtc_bindings_cleared": self.webrtc_bindings_cleared,
            "errors": list(self.errors),
            "non_goals": list(self.non_goals),
        }

    @property
    def duration_seconds(self) -> Optional[float]:
        """Return duration in seconds, or None if recovery is still running."""
        if self.completed_at is None:
            return None
        return self.completed_at - self.started_at

    @property
    def has_errors(self) -> bool:
        """True if any non-fatal errors were encountered."""
        return bool(self.errors)

    @property
    def success(self) -> bool:
        """True if recovery completed without errors."""
        return self.completed_at is not None and not self.errors


# ---------------------------------------------------------------------------
# RuntimeRestartRecoveryCoordinator
# ---------------------------------------------------------------------------


class RuntimeRestartRecoveryCoordinator:
    """Orchestrates recovery of runtime-critical state after restart.

    Call :meth:`run_recovery` once at process startup to restore all
    durable state components.

    Parameters
    ----------
    mesh_session_store:
        Optional :class:`~core.mesh.mesh_session_persistence.MeshSessionPersistenceStore`
        to use for session recovery.  Defaults to the process-level singleton.
    body_mesh_store:
        Optional :class:`~core.mesh.body_mesh_persistence.BodyMeshPersistenceStore`
        to use for body mesh recovery.  Defaults to the process-level singleton.
    body_mesh_registry:
        Optional :class:`~core.mesh.body_mesh_registry.BodyMeshRegistry` to
        populate during body mesh recovery.  Defaults to the process-level
        singleton returned by :func:`~core.mesh.body_mesh_registry.get_body_mesh_registry`.
    """

    def __init__(
        self,
        mesh_session_store=None,
        body_mesh_store=None,
        body_mesh_registry=None,
    ) -> None:
        self._mesh_session_store = mesh_session_store
        self._body_mesh_store = body_mesh_store
        self._body_mesh_registry = body_mesh_registry

    def run_recovery(self) -> RuntimeRecoveryReport:
        """Orchestrate a full recovery pass.

        Steps
        -----
        1. Recover non-terminal MeshSession coordinator states.
        2. Restore BodyMeshRegistry entries from the durable snapshot.
        3. Clear in-memory WebRTC bindings (intentional — transport is gone).

        Returns
        -------
        :class:`RuntimeRecoveryReport`
            Details of what was recovered, what was skipped, and any errors.
        """
        report = RuntimeRecoveryReport()
        report.non_goals = [
            "WebRTC transport bindings are intentionally ephemeral and "
            "are NOT recovered. See WEBRTC_BINDINGS_ARE_EPHEMERAL_POLICY.",
            "In-flight task queues are NOT recovered. Tasks must be replayed "
            "by the task source.",
            "Device heartbeat state is NOT recovered. Devices re-register on "
            "reconnect.",
        ]

        # ----------------------------------------------------------------
        # Step 1: MeshSession recovery
        # ----------------------------------------------------------------
        try:
            self._recover_mesh_sessions(report)
        except Exception as exc:
            err = f"MeshSession recovery failed: {exc}"
            logger.exception("RuntimeRestartRecovery: %s", err)
            report.errors.append(err)

        # ----------------------------------------------------------------
        # Step 2: BodyMeshRegistry recovery
        # ----------------------------------------------------------------
        try:
            self._recover_body_mesh(report)
        except Exception as exc:
            err = f"BodyMesh recovery failed: {exc}"
            logger.exception("RuntimeRestartRecovery: %s", err)
            report.errors.append(err)

        # ----------------------------------------------------------------
        # Step 3: Clear WebRTC in-memory bindings (intentional)
        # ----------------------------------------------------------------
        try:
            self._clear_webrtc_bindings(report)
        except Exception as exc:
            err = f"WebRTC binding clear failed: {exc}"
            logger.warning("RuntimeRestartRecovery: %s", err)
            report.errors.append(err)

        report.completed_at = time.time()
        logger.info(
            "RuntimeRestartRecovery: completed recovery_id=%s "
            "mesh_sessions=%d body_entries=%d errors=%d",
            report.recovery_id,
            report.mesh_sessions_recovered,
            report.body_mesh_entries_restored,
            len(report.errors),
        )
        return report

    def _recover_mesh_sessions(self, report: RuntimeRecoveryReport) -> None:
        """Recover non-terminal mesh session states."""
        from core.mesh.mesh_session_persistence import recover_mesh_sessions
        records = recover_mesh_sessions(store=self._mesh_session_store)
        report.mesh_sessions_recovered = len(records)

        # Count how many were skipped (terminal)
        try:
            from core.mesh.mesh_session_persistence import (
                get_persistence_store,
                MeshSessionPersistenceStore,
            )
            store = self._mesh_session_store or get_persistence_store()
            all_ids_raw = store.list_recoverable()
            # list_recoverable only returns non-terminal; total = records + skipped
            # We can get the total by checking the store's memory cache directly
            # For a conservative estimate: skipped = (total on disk) - recovered
            # But list_recoverable() only returns non-terminal ones, so skipped is unknown
            # without a separate "list_all" API.  Leave at 0 for now.
            report.mesh_sessions_skipped = 0
        except Exception:
            pass

        logger.info(
            "RuntimeRestartRecovery: recovered %d mesh sessions",
            report.mesh_sessions_recovered,
        )

    def _recover_body_mesh(self, report: RuntimeRecoveryReport) -> None:
        """Restore BodyMeshRegistry entries from snapshot."""
        from core.mesh.body_mesh_persistence import restore_body_mesh_from_snapshot

        registry = self._body_mesh_registry
        if registry is None:
            try:
                from core.mesh.body_mesh_registry import get_body_mesh_registry
                registry = get_body_mesh_registry()
            except Exception as exc:
                logger.warning(
                    "RuntimeRestartRecovery: could not get body mesh registry: %s", exc
                )
                return

        restored = restore_body_mesh_from_snapshot(
            registry=registry,
            store=self._body_mesh_store,
        )
        report.body_mesh_entries_restored = restored
        logger.info(
            "RuntimeRestartRecovery: restored %d body mesh entries",
            restored,
        )

    def _clear_webrtc_bindings(self, report: RuntimeRecoveryReport) -> None:
        """Clear in-memory WebRTC task bindings — intentionally ephemeral."""
        try:
            from core.webrtc_task_lifecycle import reset_webrtc_task_session_registry
            reset_webrtc_task_session_registry()
            report.webrtc_bindings_cleared = True
            logger.debug("RuntimeRestartRecovery: WebRTC bindings cleared (intentional)")
        except Exception as exc:
            # Non-fatal — bindings are ephemeral anyway
            logger.debug(
                "RuntimeRestartRecovery: could not clear WebRTC bindings: %s", exc
            )
            report.webrtc_bindings_cleared = False


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------

_coordinator_instance: Optional[RuntimeRestartRecoveryCoordinator] = None


def get_recovery_coordinator(**kwargs) -> RuntimeRestartRecoveryCoordinator:
    """Return the process-level :class:`RuntimeRestartRecoveryCoordinator` singleton."""
    global _coordinator_instance
    if _coordinator_instance is None:
        _coordinator_instance = RuntimeRestartRecoveryCoordinator(**kwargs)
    return _coordinator_instance


def reset_recovery_coordinator() -> None:
    """Reset the singleton (for testing)."""
    global _coordinator_instance
    _coordinator_instance = None


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------


def run_startup_recovery(
    mesh_session_store=None,
    body_mesh_store=None,
    body_mesh_registry=None,
) -> RuntimeRecoveryReport:
    """Run a full startup recovery pass.

    Convenience entry-point for use in process startup code::

        from core.runtime_restart_recovery import run_startup_recovery
        report = run_startup_recovery()
        if report.has_errors:
            logger.warning("Startup recovery had errors: %s", report.errors)

    Parameters
    ----------
    mesh_session_store:
        Optional explicit mesh session persistence store.
    body_mesh_store:
        Optional explicit body mesh persistence store.
    body_mesh_registry:
        Optional explicit body mesh registry to populate.

    Returns
    -------
    :class:`RuntimeRecoveryReport`
    """
    coordinator = RuntimeRestartRecoveryCoordinator(
        mesh_session_store=mesh_session_store,
        body_mesh_store=body_mesh_store,
        body_mesh_registry=body_mesh_registry,
    )
    return coordinator.run_recovery()
