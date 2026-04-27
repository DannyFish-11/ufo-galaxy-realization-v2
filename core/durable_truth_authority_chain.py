#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/durable_truth_authority_chain.py
========================================
PR-2: Durable Truth Authority Chain — Unified convergence of session truth,
task lifecycle truth, and result continuity into a single, durable authority chain.

Background
----------
After PR-1 (GAP_V2_TRUTH_PERSISTENCE closure), V2 gained:

* :class:`~core.session_truth_snapshot.SessionTruthSnapshotStore` — durable
  session truth snapshots.
* :class:`~core.task_lifecycle_persistence.TaskLifecyclePersistenceStore` —
  durable in-flight task lifecycle snapshots.
* :class:`~core.durable_result_idempotency.DurableResultIdSet` — durable
  result-ID deduplication across restarts.
* :class:`~core.replay_audit_persistence.DurableAuditStore` — forensic audit
  of truth-merge events.

However, these stores remained **semantically parallel** — each was added
additively and there was no single declaration that they collectively form a
**unified durable truth authority chain**.  The in-process ring buffer of
:class:`~core.canonical_session_truth.CanonicalSessionTruthRuntime` continued
to be described as "the authoritative runtime read surface", which created an
ambiguity:

    *Is the ring buffer the truth source, with durable stores as
    observational sinks?  Or is the durable path the authority, with the
    ring buffer serving as a read-cache?*

This module closes that ambiguity by:

1. Declaring :data:`DURABLE_TRUTH_IS_AUTHORITY_POLICY` — the durable path is
   the canonical authority.  The ring buffer is a **read-cache** populated
   from the durable path at startup, not a competing truth source.

2. Providing :class:`DurableTruthAuthorityChain` — a lightweight façade that
   wires session truth, task lifecycle, and result continuity together and
   exposes a :meth:`~DurableTruthAuthorityChain.convergence_check` that
   verifies all three legs are healthy.

3. Providing :func:`verify_durable_truth_convergence` — a convenience function
   for the recovery coordinator (and tests) to call after startup.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Graceful degradation** — every check degrades to ``False`` rather than
  raising; callers can treat ``False`` as "converge later".
- **Policy-sentinel-first** — every behavioural rule is expressed as a named,
  importable, non-empty string sentinel.

Sentinels
---------
:data:`DURABLE_TRUTH_AUTHORITY_CHAIN_IS_AUTHORITY`
    Module-level authority sentinel.
:data:`DURABLE_TRUTH_IS_AUTHORITY_POLICY`
    Affirms the durable path is the authority; ring buffer is a read-cache.
:data:`RING_BUFFER_IS_READ_CACHE_POLICY`
    Affirms :class:`~core.canonical_session_truth.CanonicalSessionTruthRuntime`
    ring buffer is a read-cache of the durable snapshot, not a competing
    truth authority.
:data:`AUTHORITY_CHAIN_LEGS_POLICY`
    Enumerates the three legs of the durable authority chain.
:data:`CONVERGENCE_REQUIRES_ALL_LEGS_POLICY`
    Affirms convergence is only declared when all three legs are healthy.

Public API
----------
Classes:
    :class:`DurableTruthAuthorityChain`
    :class:`DurableTruthConvergenceResult`

Functions:
    :func:`verify_durable_truth_convergence`
    :func:`get_durable_truth_authority_chain`
    :func:`reset_durable_truth_authority_chain`
"""

from __future__ import annotations

import dataclasses
import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.DurableTruthAuthorityChain")

__all__ = [
    # Authority / policy sentinels
    "DURABLE_TRUTH_AUTHORITY_CHAIN_IS_AUTHORITY",
    "DURABLE_TRUTH_IS_AUTHORITY_POLICY",
    "RING_BUFFER_IS_READ_CACHE_POLICY",
    "AUTHORITY_CHAIN_LEGS_POLICY",
    "CONVERGENCE_REQUIRES_ALL_LEGS_POLICY",
    "DURABLE_TRUTH_AUTHORITY_CHAIN_PR2_SENTINEL",
    # Classes
    "DurableTruthConvergenceResult",
    "DurableTruthAuthorityChain",
    # Functions
    "verify_durable_truth_convergence",
    "get_durable_truth_authority_chain",
    "reset_durable_truth_authority_chain",
]

# ---------------------------------------------------------------------------
# Authority and policy sentinels
# ---------------------------------------------------------------------------

DURABLE_TRUTH_AUTHORITY_CHAIN_IS_AUTHORITY: str = (
    "DURABLE_TRUTH_AUTHORITY_CHAIN::PR2_AUTHORITY_V1: "
    "core.durable_truth_authority_chain is the canonical declaration that "
    "session truth, task lifecycle truth, and result continuity in V2 form "
    "a single unified durable authority chain.  The three legs — "
    "SessionTruthSnapshotStore, TaskLifecyclePersistenceStore, and "
    "DurableResultIdSet — are the authoritative truth sources.  "
    "(PR-2, durable truth authority convergence)"
)
"""Module-level authority sentinel for the durable truth authority chain (PR-2)."""

DURABLE_TRUTH_IS_AUTHORITY_POLICY: str = (
    "DURABLE_TRUTH_AUTHORITY_CHAIN::DURABLE_IS_AUTHORITY_POLICY_V1: "
    "The durable path (SessionTruthSnapshotStore + TaskLifecyclePersistenceStore "
    "+ DurableResultIdSet) IS the canonical truth authority for V2 state that "
    "must survive process restarts.  These stores are the source-of-record; "
    "the in-process ring buffer and lifecycle registry are READ-CACHES populated "
    "from them at startup.  Callers and tests MUST treat durable stores as "
    "authoritative, not the runtime ring buffer.  "
    "(PR-2, durable truth authority convergence)"
)
"""Policy: the durable stores are the authority; ring buffer is a read-cache."""

RING_BUFFER_IS_READ_CACHE_POLICY: str = (
    "DURABLE_TRUTH_AUTHORITY_CHAIN::RING_BUFFER_READ_CACHE_POLICY_V1: "
    "CanonicalSessionTruthRuntime's in-process ring buffer is a READ-CACHE. "
    "At startup, restore_session_truth_from_snapshot() repopulates it from "
    "the durable SessionTruthSnapshotStore.  During runtime, every record "
    "written to the ring buffer is ALSO written to the durable snapshot store. "
    "The ring buffer is NOT a competing truth source — it reflects the durable "
    "state and may be cleared and rebuilt from it at any time.  "
    "This is the authoritative clarification of the relationship between the "
    "ring buffer and the durable snapshot.  (PR-2)"
)
"""Policy: ring buffer is a read-cache, not an independent authority."""

AUTHORITY_CHAIN_LEGS_POLICY: str = (
    "DURABLE_TRUTH_AUTHORITY_CHAIN::LEGS_POLICY_V1: "
    "The unified durable truth authority chain has exactly three legs: "
    "(1) SESSION_TRUTH — SessionTruthSnapshotStore provides durable "
    "CanonicalSessionTruthRecord storage across restarts; "
    "(2) TASK_LIFECYCLE — TaskLifecyclePersistenceStore provides durable "
    "in-flight task record storage across restarts; "
    "(3) RESULT_CONTINUITY — DurableResultIdSet provides durable result-ID "
    "deduplication across restarts.  All three legs must be active for full "
    "convergence.  (PR-2)"
)
"""Policy: the chain has exactly three legs — session truth, task lifecycle, result continuity."""

CONVERGENCE_REQUIRES_ALL_LEGS_POLICY: str = (
    "DURABLE_TRUTH_AUTHORITY_CHAIN::CONVERGENCE_ALL_LEGS_POLICY_V1: "
    "DurableTruthConvergenceResult.converged is True only when all three "
    "chain legs report healthy: session_truth_leg_healthy=True, "
    "task_lifecycle_leg_healthy=True, result_continuity_leg_healthy=True.  "
    "Partial convergence (only some legs healthy) is explicitly tracked and "
    "logged but does NOT produce converged=True.  (PR-2)"
)
"""Policy: convergence requires all three legs to be healthy."""

DURABLE_TRUTH_AUTHORITY_CHAIN_PR2_SENTINEL: str = (
    "DURABLE_TRUTH_AUTHORITY_CHAIN::PR2_INTEGRATED_V1: "
    "PR-2 durable truth authority chain convergence is active.  "
    "DurableTruthAuthorityChain.convergence_check() is called during "
    "RuntimeRestartRecoveryCoordinator.run_recovery() to verify all three "
    "durable legs are healthy before declaring truth convergence."
)
"""Integration sentinel confirming PR-2 durable truth authority chain is live."""


# ---------------------------------------------------------------------------
# DurableTruthConvergenceResult
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class DurableTruthConvergenceResult:
    """Result of a durable truth authority chain convergence check.

    Attributes
    ----------
    check_id:
        Unique identifier for this convergence check.
    converged:
        True only if all three chain legs are healthy.
    session_truth_leg_healthy:
        True if the SessionTruthSnapshotStore is accessible and wired.
    task_lifecycle_leg_healthy:
        True if the TaskLifecyclePersistenceStore is accessible and wired.
    result_continuity_leg_healthy:
        True if the DurableResultIdSet is accessible and wired.
    session_truth_records_available:
        Number of session truth records available in the durable store.
    task_lifecycle_records_available:
        Number of task lifecycle records available in the durable store.
    result_id_count:
        Number of result IDs tracked in the durable store.
    degradation_reasons:
        List of human-readable reasons why a leg is unhealthy, if any.
    timestamp:
        Unix epoch seconds when this check was performed.
    """

    check_id: str = dataclasses.field(
        default_factory=lambda: f"dtc_{uuid.uuid4().hex[:12]}"
    )
    converged: bool = False
    session_truth_leg_healthy: bool = False
    task_lifecycle_leg_healthy: bool = False
    result_continuity_leg_healthy: bool = False
    session_truth_records_available: int = 0
    task_lifecycle_records_available: int = 0
    result_id_count: int = 0
    degradation_reasons: List[str] = dataclasses.field(default_factory=list)
    timestamp: float = dataclasses.field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return {
            "check_id": self.check_id,
            "converged": self.converged,
            "session_truth_leg_healthy": self.session_truth_leg_healthy,
            "task_lifecycle_leg_healthy": self.task_lifecycle_leg_healthy,
            "result_continuity_leg_healthy": self.result_continuity_leg_healthy,
            "session_truth_records_available": self.session_truth_records_available,
            "task_lifecycle_records_available": self.task_lifecycle_records_available,
            "result_id_count": self.result_id_count,
            "degradation_reasons": list(self.degradation_reasons),
            "timestamp": self.timestamp,
            "authority": DURABLE_TRUTH_AUTHORITY_CHAIN_IS_AUTHORITY,
        }


# ---------------------------------------------------------------------------
# DurableTruthAuthorityChain
# ---------------------------------------------------------------------------


class DurableTruthAuthorityChain:
    """Lightweight façade over the three durable truth legs.

    Provides a single :meth:`convergence_check` that verifies all three legs
    are healthy (accessible and wired) without performing any write operations.

    Parameters
    ----------
    session_truth_store:
        Optional explicit :class:`~core.session_truth_snapshot.SessionTruthSnapshotStore`.
        Defaults to the process-level singleton.
    task_lifecycle_store:
        Optional explicit :class:`~core.task_lifecycle_persistence.TaskLifecyclePersistenceStore`.
        Defaults to the process-level singleton.
    result_id_store:
        Optional explicit :class:`~core.durable_result_idempotency.DurableResultIdSet`.
        Defaults to the process-level singleton.
    """

    def __init__(
        self,
        session_truth_store: Any = None,
        task_lifecycle_store: Any = None,
        result_id_store: Any = None,
    ) -> None:
        self._session_truth_store = session_truth_store
        self._task_lifecycle_store = task_lifecycle_store
        self._result_id_store = result_id_store

    def convergence_check(self) -> DurableTruthConvergenceResult:
        """Check that all three durable truth legs are healthy.

        Returns
        -------
        :class:`DurableTruthConvergenceResult`
            Describes the health of each leg and whether full convergence
            is achieved.  Does not raise on any failure — degrades gracefully.
        """
        result = DurableTruthConvergenceResult()

        # ── Leg 1: Session truth ─────────────────────────────────────────
        try:
            store = self._session_truth_store
            if store is None:
                from core.session_truth_snapshot import get_session_truth_snapshot_store
                store = get_session_truth_snapshot_store()
            records = store.load()
            result.session_truth_records_available = len(records) if records else 0
            result.session_truth_leg_healthy = True
        except Exception as exc:
            result.degradation_reasons.append(
                f"session_truth_leg: {exc}"
            )
            logger.debug(
                "DurableTruthAuthorityChain: session truth leg unhealthy: %s", exc
            )

        # ── Leg 2: Task lifecycle ─────────────────────────────────────────
        try:
            store = self._task_lifecycle_store
            if store is None:
                from core.task_lifecycle_persistence import get_task_lifecycle_store
                store = get_task_lifecycle_store()
            snapshot = store.load()
            result.task_lifecycle_records_available = (
                len(snapshot.records) if snapshot and snapshot.records else 0
            )
            result.task_lifecycle_leg_healthy = True
        except Exception as exc:
            result.degradation_reasons.append(
                f"task_lifecycle_leg: {exc}"
            )
            logger.debug(
                "DurableTruthAuthorityChain: task lifecycle leg unhealthy: %s", exc
            )

        # ── Leg 3: Result continuity ──────────────────────────────────────
        try:
            store = self._result_id_store
            if store is None:
                from core.durable_result_idempotency import get_durable_result_id_store
                store = get_durable_result_id_store()
            result.result_id_count = store.size()
            result.result_continuity_leg_healthy = True
        except Exception as exc:
            result.degradation_reasons.append(
                f"result_continuity_leg: {exc}"
            )
            logger.debug(
                "DurableTruthAuthorityChain: result continuity leg unhealthy: %s", exc
            )

        # ── Convergence ───────────────────────────────────────────────────
        result.converged = (
            result.session_truth_leg_healthy
            and result.task_lifecycle_leg_healthy
            and result.result_continuity_leg_healthy
        )

        if result.converged:
            logger.info(
                "DurableTruthAuthorityChain: all three legs healthy — "
                "truth authority converged. "
                "session_records=%d task_records=%d result_ids=%d. "
                "See CONVERGENCE_REQUIRES_ALL_LEGS_POLICY.",
                result.session_truth_records_available,
                result.task_lifecycle_records_available,
                result.result_id_count,
            )
        else:
            logger.warning(
                "DurableTruthAuthorityChain: partial convergence — "
                "session_truth=%s task_lifecycle=%s result_continuity=%s. "
                "Reasons: %s. "
                "See CONVERGENCE_REQUIRES_ALL_LEGS_POLICY.",
                result.session_truth_leg_healthy,
                result.task_lifecycle_leg_healthy,
                result.result_continuity_leg_healthy,
                result.degradation_reasons,
            )

        return result


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------

_chain_instance: Optional[DurableTruthAuthorityChain] = None
_chain_lock: threading.Lock = threading.Lock()


def get_durable_truth_authority_chain(
    session_truth_store: Any = None,
    task_lifecycle_store: Any = None,
    result_id_store: Any = None,
) -> DurableTruthAuthorityChain:
    """Return the process-level :class:`DurableTruthAuthorityChain` singleton.

    If the singleton has not been created yet, creates it with optional
    explicit stores (useful for testing).
    """
    global _chain_instance
    if _chain_instance is None:
        with _chain_lock:
            if _chain_instance is None:
                _chain_instance = DurableTruthAuthorityChain(
                    session_truth_store=session_truth_store,
                    task_lifecycle_store=task_lifecycle_store,
                    result_id_store=result_id_store,
                )
    return _chain_instance


def reset_durable_truth_authority_chain() -> None:
    """Reset the singleton (for testing)."""
    global _chain_instance
    with _chain_lock:
        _chain_instance = None


# ---------------------------------------------------------------------------
# Convenience function for recovery coordinator and tests
# ---------------------------------------------------------------------------


def verify_durable_truth_convergence(
    session_truth_store: Any = None,
    task_lifecycle_store: Any = None,
    result_id_store: Any = None,
) -> DurableTruthConvergenceResult:
    """Run a convergence check against the durable truth authority chain.

    Creates a temporary :class:`DurableTruthAuthorityChain` (does not affect
    the singleton) with the provided stores (or defaults) and returns the
    convergence result.

    Parameters
    ----------
    session_truth_store:
        Optional explicit session truth snapshot store.
    task_lifecycle_store:
        Optional explicit task lifecycle persistence store.
    result_id_store:
        Optional explicit durable result ID store.

    Returns
    -------
    :class:`DurableTruthConvergenceResult`
        Convergence check result.
    """
    chain = DurableTruthAuthorityChain(
        session_truth_store=session_truth_store,
        task_lifecycle_store=task_lifecycle_store,
        result_id_store=result_id_store,
    )
    return chain.convergence_check()
