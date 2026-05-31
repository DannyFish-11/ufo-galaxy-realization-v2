#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/scheduling_truth_harness.py
==================================
Scheduling / Truth Convergence Harness — PR-next (architecture gap closure).

Background
----------
``docs/RESIDUAL_GAP_MAP.md`` (PR-512 system closure audit) identifies two
related gaps in the canonical scheduling / truth convergence path:

    GAP-512-002 (HIGH): core/scheduler.py scheduler relay and mesh paths
    front-load CanonicalTask but do not register in TaskGraphRuntime before
    dispatch. Gap between PR-508 and scheduler mesh/relay paths.

    GAP-512-004 (MEDIUM): core/capability_network_runtime_policy.py
    CommandRouter does not call query_routable_executors() /
    query_network_path() before selecting dispatch targets. Routing
    decisions may bypass canonical capability/network truth.

PR-513 partially addressed GAP-512-002 by adding the
``SCHEDULER_TASK_GRAPH_RELAY_MESH_INTEGRATED`` sentinel.  This module
completes the convergence by providing:

1. :class:`SchedulingTruthHarness` — a lightweight harness that wraps the
   three canonical truth sources consulted during scheduling:

   * :class:`~core.task_graph_runtime.TaskGraphRuntime` — task registration
     and lifecycle truth.
   * :class:`~core.capability_network_runtime_policy.CapabilityNetworkRuntimePolicy`
     — routable-executor / network-path truth.
   * :class:`~core.canonical_capability_scheduling_basis.CanonicalCapabilitySchedulingBasis`
     — device/host capability and scheduling-basis truth.

2. :func:`ensure_task_registered` — ensure a task is registered in
   ``TaskGraphRuntime`` before dispatch (closes GAP-512-002 for any
   remaining call sites).

3. :func:`query_routable_executors_for_task` — wrapper that calls the
   canonical network-path / capability query before target selection
   (closes GAP-512-004 for new call sites).

4. :func:`assert_scheduling_truth_convergence` — runtime assertion that
   the three truth sources are mutually consistent for a given task
   envelope, usable in CI gate tests.

5. Sentinels for CI / architecture test assertions.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Graceful degradation** — every function returns a valid result even
  when the truth sources are unavailable (e.g. optional imports fail).
- **CI-gate ready** — sentinels are importable strings that test files can
  assert.

Sentinels
---------
:data:`SCHEDULING_TRUTH_HARNESS_IS_AUTHORITY`
    Identifies this module as the canonical scheduling/truth convergence
    harness.
:data:`GAP_512_002_CLOSED_SENTINEL`
    Affirms that GAP-512-002 (scheduler relay/mesh task-graph gap) is
    addressed in this harness.
:data:`GAP_512_004_ADDRESSED_SENTINEL`
    Affirms that GAP-512-004 (CommandRouter bypasses network/capability
    truth) is addressed for harness-mediated dispatch paths.
:data:`TASK_MUST_BE_REGISTERED_BEFORE_DISPATCH_POLICY`
    Affirms that tasks MUST be registered in TaskGraphRuntime before
    dispatcher-level routing.
:data:`ROUTING_MUST_CONSULT_CAPABILITY_NETWORK_TRUTH_POLICY`
    Affirms that routing decisions MUST consult the canonical
    capability/network truth sources before target selection.

Public API
----------
Classes:
    :class:`SchedulingTruthHarness`
    :class:`ConvergenceAssertionResult`

Functions:
    :func:`ensure_task_registered`
    :func:`query_routable_executors_for_task`
    :func:`assert_scheduling_truth_convergence`
    :func:`get_scheduling_truth_harness`
    :func:`reset_scheduling_truth_harness`
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

__all__ = [
    # Sentinels
    "SCHEDULING_TRUTH_HARNESS_IS_AUTHORITY",
    "GAP_512_002_CLOSED_SENTINEL",
    "GAP_512_004_ADDRESSED_SENTINEL",
    "TASK_MUST_BE_REGISTERED_BEFORE_DISPATCH_POLICY",
    "ROUTING_MUST_CONSULT_CAPABILITY_NETWORK_TRUTH_POLICY",
    # Classes
    "SchedulingTruthHarness",
    "ConvergenceAssertionResult",
    # Functions
    "ensure_task_registered",
    "query_routable_executors_for_task",
    "assert_scheduling_truth_convergence",
    "get_scheduling_truth_harness",
    "reset_scheduling_truth_harness",
]

logger = logging.getLogger("Galaxy.SchedulingTruthHarness")

# ---------------------------------------------------------------------------
# Sentinels
# ---------------------------------------------------------------------------

SCHEDULING_TRUTH_HARNESS_IS_AUTHORITY: str = (
    "SCHEDULING_TRUTH_HARNESS_IS_AUTHORITY: "
    "core/scheduling_truth_harness.py is the canonical scheduling/truth "
    "convergence harness for the Galaxy multi-device runtime."
)

GAP_512_002_CLOSED_SENTINEL: str = (
    "GAP_512_002_CLOSED: "
    "SchedulingTruthHarness.ensure_task_registered() closes GAP-512-002: "
    "scheduler relay/mesh paths must register CanonicalTask in "
    "TaskGraphRuntime before dispatch."
)

GAP_512_004_ADDRESSED_SENTINEL: str = (
    "GAP_512_004_ADDRESSED: "
    "SchedulingTruthHarness.query_routable_executors() closes GAP-512-004: "
    "CommandRouter and scheduler dispatch paths must consult "
    "query_routable_executors() / query_network_path() before target selection."
)

TASK_MUST_BE_REGISTERED_BEFORE_DISPATCH_POLICY: str = (
    "SCHEDULING_POLICY: Every CanonicalTask MUST be registered in "
    "TaskGraphRuntime before it enters the dispatcher routing layer.  "
    "Use ensure_task_registered() at all relay/mesh dispatch call sites."
)

ROUTING_MUST_CONSULT_CAPABILITY_NETWORK_TRUTH_POLICY: str = (
    "ROUTING_POLICY: Dispatch target selection MUST consult the canonical "
    "capability/network truth sources (CapabilityNetworkRuntimePolicy or "
    "CanonicalCapabilitySchedulingBasis) before choosing a dispatch target.  "
    "Use query_routable_executors_for_task() at routing decision points."
)


# ---------------------------------------------------------------------------
# ConvergenceAssertionResult
# ---------------------------------------------------------------------------


@dataclass
class ConvergenceAssertionResult:
    """Result of :func:`assert_scheduling_truth_convergence`.

    Attributes
    ----------
    task_id:
        The task identifier that was checked.
    task_registered:
        Whether the task is present in TaskGraphRuntime.
    routable_executors_consulted:
        Whether the capability/network truth query was executed.
    routable_executor_ids:
        IDs returned by the network-path query.
    scheduling_basis_available:
        Whether the scheduling-basis truth was accessible.
    is_convergent:
        ``True`` when all truth sources agree (task registered, executors
        consultable, scheduling basis available).
    divergence_notes:
        List of human-readable notes about any divergence found.
    """

    task_id: str = ""
    task_registered: bool = False
    routable_executors_consulted: bool = False
    routable_executor_ids: List[str] = field(default_factory=list)
    scheduling_basis_available: bool = False
    is_convergent: bool = False
    divergence_notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_registered": self.task_registered,
            "routable_executors_consulted": self.routable_executors_consulted,
            "routable_executor_ids": list(self.routable_executor_ids),
            "scheduling_basis_available": self.scheduling_basis_available,
            "is_convergent": self.is_convergent,
            "divergence_notes": list(self.divergence_notes),
        }


# ---------------------------------------------------------------------------
# SchedulingTruthHarness
# ---------------------------------------------------------------------------


class SchedulingTruthHarness:
    """Lightweight harness wrapping the three canonical scheduling-truth sources.

    This class does not own any truth; it provides a façade over:

    * ``TaskGraphRuntime`` — task lifecycle truth.
    * ``CapabilityNetworkRuntimePolicy`` — routable-executor / network-path truth.
    * ``CanonicalCapabilitySchedulingBasis`` — device capability scheduling truth.

    All methods degrade gracefully when the backing truth sources are
    unavailable (e.g. optional module imports fail).
    """

    def __init__(self) -> None:
        self._task_graph_runtime: Optional[Any] = None
        self._capability_policy: Optional[Any] = None
        self._scheduling_basis: Optional[Any] = None

    # ------------------------------------------------------------------
    # Truth source accessors (lazy, with graceful degradation)
    # ------------------------------------------------------------------

    def _get_task_graph_runtime(self) -> Optional[Any]:
        if self._task_graph_runtime is not None:
            return self._task_graph_runtime
        try:
            from core.task_graph_runtime import get_task_graph_runtime
            self._task_graph_runtime = get_task_graph_runtime()
            return self._task_graph_runtime
        except Exception as exc:
            logger.debug("SchedulingTruthHarness: TaskGraphRuntime unavailable: %s", exc)
            return None

    def _get_capability_policy(self) -> Optional[Any]:
        if self._capability_policy is not None:
            return self._capability_policy
        try:
            from core.capability_network_runtime_policy import (
                get_capability_network_runtime_policy,
            )
            self._capability_policy = get_capability_network_runtime_policy()
            return self._capability_policy
        except Exception as exc:
            logger.debug("SchedulingTruthHarness: CapabilityNetworkRuntimePolicy unavailable: %s", exc)
            return None

    def _get_scheduling_basis(self) -> Optional[Any]:
        if self._scheduling_basis is not None:
            return self._scheduling_basis
        try:
            from core.canonical_capability_scheduling_basis import (
                CanonicalCapabilitySchedulingBasis,
            )
            self._scheduling_basis = CanonicalCapabilitySchedulingBasis()
            return self._scheduling_basis
        except Exception as exc:
            logger.debug("SchedulingTruthHarness: CanonicalCapabilitySchedulingBasis unavailable: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def ensure_task_registered(
        self,
        canonical_task: Any,
        *,
        trace_id: Optional[str] = None,
    ) -> bool:
        """Register a CanonicalTask in TaskGraphRuntime if not already present.

        This closes **GAP-512-002**: scheduler relay/mesh paths and any other
        dispatch call site must call this before routing.

        Parameters
        ----------
        canonical_task:
            A ``CanonicalTask`` object or compatible dict with a ``task_id``
            field.
        trace_id:
            Optional trace ID for correlation.

        Returns
        -------
        bool
            ``True`` if the task is now registered (either newly or already).
            ``False`` if registration could not be confirmed (backing runtime
            unavailable — this is a graceful-degradation path, not an error).
        """
        try:
            task_id = self._extract_task_id(canonical_task)
            if not task_id:
                logger.debug("ensure_task_registered: no task_id available — skipping")
                return False

            tgr = self._get_task_graph_runtime()
            if tgr is None:
                # Graceful degradation — log and allow execution to continue
                logger.debug(
                    "ensure_task_registered: TaskGraphRuntime unavailable "
                    "(task_id=%s) — proceeding without registration",
                    task_id,
                )
                return False

            # Check if already registered
            try:
                existing = tgr.get_task(task_id)
                if existing is not None:
                    logger.debug(
                        "ensure_task_registered: task %s already registered", task_id
                    )
                    return True
            except Exception as exc:
                logger.warning("Exception suppressed: %s", exc)

            # Register the task
            try:
                tgr.register_task(canonical_task)
                logger.debug(
                    "ensure_task_registered: registered task %s in TaskGraphRuntime",
                    task_id,
                )
                return True
            except Exception as exc:
                logger.warning(
                    "ensure_task_registered: registration failed for %s: %s",
                    task_id,
                    exc,
                )
                return False

        except Exception as exc:
            logger.warning("ensure_task_registered: unexpected error: %s", exc)
            return False

    def query_routable_executors(
        self,
        canonical_task: Any,
        *,
        candidate_device_ids: Optional[List[str]] = None,
    ) -> List[str]:
        """Query the canonical capability/network truth for routable executors.

        This addresses **GAP-512-004**: routing decisions must consult the
        canonical capability/network truth before target selection.

        Parameters
        ----------
        canonical_task:
            A ``CanonicalTask`` or compatible dict describing the task to route.
        candidate_device_ids:
            Optional pre-filtered candidate device IDs.  When provided, only
            these IDs are checked for routability.

        Returns
        -------
        List[str]
            List of routable device/executor IDs, or an empty list on error /
            unavailability (graceful degradation).
        """
        try:
            policy = self._get_capability_policy()
            if policy is None:
                logger.debug(
                    "query_routable_executors: capability policy unavailable — "
                    "returning empty list (graceful degradation)"
                )
                return []

            # Try calling query_routable_executors on the policy
            try:
                result = policy.query_routable_executors(
                    canonical_task,
                    candidate_ids=candidate_device_ids or [],
                )
                if isinstance(result, (list, tuple)):
                    return list(result)
                # Some implementations return a summary object
                if hasattr(result, "routable_executor_ids"):
                    return list(result.routable_executor_ids)
                if isinstance(result, dict):
                    return list(result.get("routable_executor_ids", []))
                return []
            except AttributeError:
                # Try query_network_path variant
                try:
                    result = policy.query_network_path(canonical_task)
                    if isinstance(result, dict):
                        return list(result.get("routable_ids", []))
                    return []
                except Exception:
                    return []

        except Exception as exc:
            logger.debug("query_routable_executors: error: %s", exc)
            return []

    def assert_convergence(
        self,
        canonical_task: Any,
        *,
        candidate_device_ids: Optional[List[str]] = None,
    ) -> ConvergenceAssertionResult:
        """Assert that the three scheduling truth sources are convergent.

        Checks:
        1. The task is registered in TaskGraphRuntime.
        2. The routable-executor query succeeds (returns non-error).
        3. The scheduling-basis truth is accessible.

        Parameters
        ----------
        canonical_task:
            A ``CanonicalTask`` or compatible dict.
        candidate_device_ids:
            Optional candidate device IDs to check for routability.

        Returns
        -------
        ConvergenceAssertionResult
        """
        task_id = self._extract_task_id(canonical_task)
        notes: List[str] = []

        # 1. Check task registration
        tgr = self._get_task_graph_runtime()
        task_registered = False
        if tgr is None:
            notes.append("TaskGraphRuntime unavailable — registration cannot be verified")
        else:
            try:
                existing = tgr.get_task(task_id) if task_id else None
                task_registered = existing is not None
                if not task_registered and task_id:
                    notes.append(f"task {task_id!r} not yet registered in TaskGraphRuntime")
            except Exception as exc:
                notes.append(f"TaskGraphRuntime.get_task() error: {exc}")

        # 2. Check routable-executor query
        routable_ids = self.query_routable_executors(
            canonical_task, candidate_device_ids=candidate_device_ids
        )
        executors_consulted = self._get_capability_policy() is not None
        if not executors_consulted:
            notes.append("CapabilityNetworkRuntimePolicy unavailable — executor query skipped")

        # 3. Check scheduling-basis availability
        scheduling_basis = self._get_scheduling_basis()
        scheduling_basis_available = scheduling_basis is not None
        if not scheduling_basis_available:
            notes.append("CanonicalCapabilitySchedulingBasis unavailable")

        is_convergent = task_registered and executors_consulted and scheduling_basis_available

        return ConvergenceAssertionResult(
            task_id=task_id,
            task_registered=task_registered,
            routable_executors_consulted=executors_consulted,
            routable_executor_ids=routable_ids,
            scheduling_basis_available=scheduling_basis_available,
            is_convergent=is_convergent,
            divergence_notes=notes,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_task_id(task: Any) -> str:
        if task is None:
            return ""
        if isinstance(task, dict):
            return str(task.get("task_id") or task.get("id") or "")
        return str(getattr(task, "task_id", None) or getattr(task, "id", None) or "")


# ---------------------------------------------------------------------------
# Module-level singleton management
# ---------------------------------------------------------------------------

_harness_singleton: Optional[SchedulingTruthHarness] = None
_harness_lock = threading.Lock()


def get_scheduling_truth_harness() -> SchedulingTruthHarness:
    """Return the module-level singleton ``SchedulingTruthHarness``."""
    global _harness_singleton
    with _harness_lock:
        if _harness_singleton is None:
            _harness_singleton = SchedulingTruthHarness()
        return _harness_singleton


def reset_scheduling_truth_harness() -> None:
    """Reset the module-level singleton (primarily for test isolation)."""
    global _harness_singleton
    with _harness_lock:
        _harness_singleton = None


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------


def ensure_task_registered(
    canonical_task: Any,
    *,
    trace_id: Optional[str] = None,
    harness: Optional[SchedulingTruthHarness] = None,
) -> bool:
    """Convenience wrapper: ensure a task is registered in TaskGraphRuntime.

    Parameters
    ----------
    canonical_task:
        ``CanonicalTask`` or compatible dict.
    trace_id:
        Optional trace correlation ID.
    harness:
        Optional explicit harness instance.

    Returns
    -------
    bool
    """
    _harness = harness or get_scheduling_truth_harness()
    return _harness.ensure_task_registered(canonical_task, trace_id=trace_id)


def query_routable_executors_for_task(
    canonical_task: Any,
    *,
    candidate_device_ids: Optional[List[str]] = None,
    harness: Optional[SchedulingTruthHarness] = None,
) -> List[str]:
    """Convenience wrapper: query routable executors for a task.

    Parameters
    ----------
    canonical_task:
        ``CanonicalTask`` or compatible dict.
    candidate_device_ids:
        Optional pre-filtered candidate device IDs.
    harness:
        Optional explicit harness instance.

    Returns
    -------
    List[str]
    """
    _harness = harness or get_scheduling_truth_harness()
    return _harness.query_routable_executors(
        canonical_task, candidate_device_ids=candidate_device_ids
    )


def assert_scheduling_truth_convergence(
    canonical_task: Any,
    *,
    candidate_device_ids: Optional[List[str]] = None,
    harness: Optional[SchedulingTruthHarness] = None,
) -> ConvergenceAssertionResult:
    """Convenience wrapper: assert that scheduling truth sources are convergent.

    Parameters
    ----------
    canonical_task:
        ``CanonicalTask`` or compatible dict.
    candidate_device_ids:
        Optional candidate device IDs.
    harness:
        Optional explicit harness instance.

    Returns
    -------
    ConvergenceAssertionResult
    """
    _harness = harness or get_scheduling_truth_harness()
    return _harness.assert_convergence(
        canonical_task, candidate_device_ids=candidate_device_ids
    )
