"""
core/operational_slo_metrics.py — Galaxy Operational SLO Metrics  (PR-I)
=========================================================================

Exposes structured runtime metrics for key orchestration behaviors so that
important dispatch, recovery, fallback, routing, continuity, and durable-audit
outcomes are **measurable**, **reviewable**, and **trendable** rather than
visible only through ad-hoc log inspection.

This module fills the gap identified in PR-I: while the runtime became more
durable and correct after PRA–PRH, the operational surface needed to quantify
*how* durable and correct it was at a given point in time.

Metric domains
--------------
dispatch
    Counts of task dispatch attempts, successes, and failures (by reason).

route_rejection
    Counts of route rejections by reason string so operators can see which
    rejection class dominates.

fallback
    Counts of fallback triggers by :class:`~core.routing_observability.RoutingFallbackKind`
    string, giving direct visibility into degradation frequency.

recovery
    Counts of recovery attempts, and how each attempt was resolved
    (resumed / replayed / reissued / failed).

startup_recovery
    Counts of tasks scanned and actions taken during the startup recovery pass
    so the recovery coordinator's work is quantifiable.

audit_persistence
    Counts of durable audit record persist successes and failures so operators
    can verify the audit trail is healthy.

All attributes are thread-safe.  No external dependencies beyond the stdlib.

Public API
----------
``get_operational_slo_metrics() -> OperationalSLOMetrics``
    Return the process-level singleton.

``reset_operational_slo_metrics() -> None``
    Reset the singleton (primarily for tests).

OperationalSLOMetrics
    .record_dispatch_attempt(task_id, target)
    .record_dispatch_success(task_id, target)
    .record_dispatch_failure(task_id, reason)

    .record_route_rejection(task_id, reason)

    .record_fallback_triggered(task_id, fallback_kind)

    .record_recovery_attempt()
    .record_recovery_resumed()
    .record_recovery_replayed()
    .record_recovery_reissued()
    .record_recovery_failed(reason)

    .record_startup_recovery_scan(tasks_scanned, actions_taken)

    .record_audit_persist_success()
    .record_audit_persist_failure(reason)

    .snapshot() -> dict
    .prometheus_text() -> str

Sentinels
---------
:data:`OPERATIONAL_SLO_METRICS_IS_AUTHORITY`
    Affirms this module is the canonical operational SLO metrics authority
    for PR-I.
:data:`OPERATIONAL_SLO_METRICS_PR_I_SENTINEL`
    Monotonic sentinel string confirming PR-I metrics surface is active.

Environment variables
---------------------
GALAXY_OPS_REJECTION_REASONS_MAX   Max distinct route-rejection reason strings
                                    tracked (default 200).
GALAXY_OPS_FALLBACK_KINDS_MAX      Max distinct fallback-kind strings tracked
                                    (default 50).
GALAXY_OPS_FAILURE_REASONS_MAX     Max distinct dispatch/recovery failure reason
                                    strings tracked (default 200).
GALAXY_OPS_AUDIT_FAILURE_REASONS_MAX  Max distinct audit-persist failure reason
                                    strings tracked (default 100).
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# Sentinels
# ---------------------------------------------------------------------------

OPERATIONAL_SLO_METRICS_IS_AUTHORITY: str = (
    "OPERATIONAL_SLO_METRICS_IS_AUTHORITY: "
    "core/operational_slo_metrics.py is the canonical operational SLO metrics "
    "authority for PR-I.  It exposes structured, operator-reviewable counts for "
    "dispatch, route rejection, fallback, recovery, startup-recovery scan, and "
    "durable-audit persistence outcomes.  All metric recording MUST go through "
    "this module so the operational surface remains consistent and complete."
)

OPERATIONAL_SLO_METRICS_PR_I_SENTINEL: str = (
    "OPERATIONAL_SLO_METRICS_PR_I_SENTINEL: "
    "PR-I runtime metrics and operational SLO surface is active.  "
    "Structured counters for dispatch, route rejection, fallback, recovery, "
    "startup recovery scan, and audit persistence are defined and ready for "
    "operator inspection via snapshot() and prometheus_text()."
)

# Exposed in __all__ so audit scripts can verify sentinel presence.
__all__ = [
    "OPERATIONAL_SLO_METRICS_IS_AUTHORITY",
    "OPERATIONAL_SLO_METRICS_PR_I_SENTINEL",
    "OperationalSLOMetrics",
    "get_operational_slo_metrics",
    "reset_operational_slo_metrics",
]


# ---------------------------------------------------------------------------
# OperationalSLOMetrics
# ---------------------------------------------------------------------------


class OperationalSLOMetrics:
    """Thread-safe structured operational SLO metric collector.

    Tracks counts for the key orchestration behaviors that matter for
    operator-level health review and SLO-oriented regression analysis.

    Parameters
    ----------
    rejection_reasons_max:
        Maximum number of distinct route-rejection reason strings retained.
    fallback_kinds_max:
        Maximum number of distinct fallback-kind strings retained.
    failure_reasons_max:
        Maximum number of distinct dispatch/recovery failure reason strings
        retained.
    audit_failure_reasons_max:
        Maximum number of distinct audit-persist failure reason strings
        retained.
    """

    def __init__(
        self,
        rejection_reasons_max: int = 200,
        fallback_kinds_max: int = 50,
        failure_reasons_max: int = 200,
        audit_failure_reasons_max: int = 100,
    ) -> None:
        self._lock = threading.Lock()
        self._rejection_reasons_max = rejection_reasons_max
        self._fallback_kinds_max = fallback_kinds_max
        self._failure_reasons_max = failure_reasons_max
        self._audit_failure_reasons_max = audit_failure_reasons_max

        self._reset_counters()

    # ------------------------------------------------------------------
    # Internal reset (called under lock or at init time)
    # ------------------------------------------------------------------

    def _reset_counters(self) -> None:
        # dispatch
        self._dispatch_attempts: int = 0
        self._dispatch_successes: int = 0
        self._dispatch_failures: int = 0
        self._dispatch_failure_reasons: Dict[str, int] = {}

        # route rejection
        self._route_rejections: int = 0
        self._route_rejection_reasons: Dict[str, int] = {}

        # fallback
        self._fallback_triggers: int = 0
        self._fallback_kind_counts: Dict[str, int] = {}

        # recovery
        self._recovery_attempts: int = 0
        self._recovery_resumed: int = 0
        self._recovery_replayed: int = 0
        self._recovery_reissued: int = 0
        self._recovery_failed: int = 0
        self._recovery_failure_reasons: Dict[str, int] = {}

        # startup recovery scan
        self._startup_recovery_tasks_scanned: int = 0
        self._startup_recovery_actions_taken: int = 0

        # audit persistence
        self._audit_persist_successes: int = 0
        self._audit_persist_failures: int = 0
        self._audit_persist_failure_reasons: Dict[str, int] = {}

        # unified-model reliability view (lifecycle + governance aligned)
        self._unified_ingest_total: int = 0
        self._unified_last_sequence_by_subject: Dict[str, int] = {}
        self._unified_subject_state: Dict[str, Dict[str, Any]] = {}

        self._admission_total: int = 0
        self._admission_success_total: int = 0
        self._admission_failure_total: int = 0

        self._readiness_attainment_total: int = 0
        self._readiness_latency_count: int = 0
        self._readiness_latency_sum_ms: float = 0.0

        self._task_initiation_total: int = 0
        self._task_initiation_success_total: int = 0
        self._task_initiation_latency_count: int = 0
        self._task_initiation_latency_sum_ms: float = 0.0

        self._closure_total: int = 0
        self._closure_completed_total: int = 0
        self._closure_outcome_distribution: Dict[str, int] = {}

        self._degraded_mode_entries_total: int = 0

        self._unified_recovery_attempts_total: int = 0
        self._unified_recovery_success_total: int = 0

        self._cross_device_consistency_total: int = 0
        self._cross_device_consistency_success_total: int = 0

        self._session_continuity_events_total: int = 0
        self._session_continuity_breaks_total: int = 0

        self._operator_interventions_total: int = 0
        self._path_switch_total: int = 0
        self._path_switch_outcome_quality_distribution: Dict[str, int] = {}

        self._quality_distribution: Dict[str, int] = {}
        self._verdict_distribution: Dict[str, int] = {}

    def reset(self) -> None:
        """Reset all counters to zero (primarily for tests)."""
        with self._lock:
            self._reset_counters()

    # ------------------------------------------------------------------
    # Dispatch recording
    # ------------------------------------------------------------------

    def record_dispatch_attempt(self, task_id: str = "", target: str = "") -> None:
        """Record one task dispatch attempt.

        Parameters
        ----------
        task_id:
            Optional task identifier (for future per-task breakdowns; currently
            only the aggregate counter is kept).
        target:
            Optional target identifier (device, node, or executor).
        """
        with self._lock:
            self._dispatch_attempts += 1

    def record_dispatch_success(self, task_id: str = "", target: str = "") -> None:
        """Record a successful task dispatch outcome.

        Parameters
        ----------
        task_id:
            Optional task identifier.
        target:
            Optional target identifier.
        """
        with self._lock:
            self._dispatch_successes += 1

    def record_dispatch_failure(self, task_id: str = "", reason: str = "") -> None:
        """Record a failed task dispatch outcome.

        Parameters
        ----------
        task_id:
            Optional task identifier.
        reason:
            Failure reason string (e.g. ``"no_route"``, ``"target_unavailable"``,
            ``"timeout"``).  Bounded by ``failure_reasons_max`` distinct values.
        """
        with self._lock:
            self._dispatch_failures += 1
            if reason and (
                len(self._dispatch_failure_reasons) < self._failure_reasons_max
                or reason in self._dispatch_failure_reasons
            ):
                self._dispatch_failure_reasons[reason] = (
                    self._dispatch_failure_reasons.get(reason, 0) + 1
                )

    # ------------------------------------------------------------------
    # Route rejection recording
    # ------------------------------------------------------------------

    def record_route_rejection(self, task_id: str = "", reason: str = "") -> None:
        """Record one route rejection with its reason.

        Parameters
        ----------
        task_id:
            Optional task identifier.
        reason:
            Rejection reason string (e.g. ``"no_capable_device"``,
            ``"policy_reject"``, ``"formation_mismatch"``).  Bounded by
            ``rejection_reasons_max`` distinct values.
        """
        with self._lock:
            self._route_rejections += 1
            if reason and (
                len(self._route_rejection_reasons) < self._rejection_reasons_max
                or reason in self._route_rejection_reasons
            ):
                self._route_rejection_reasons[reason] = (
                    self._route_rejection_reasons.get(reason, 0) + 1
                )

    # ------------------------------------------------------------------
    # Fallback recording
    # ------------------------------------------------------------------

    def record_fallback_triggered(
        self, task_id: str = "", fallback_kind: str = "other"
    ) -> None:
        """Record one fallback trigger.

        Parameters
        ----------
        task_id:
            Optional task identifier.
        fallback_kind:
            Normalised fallback kind string (e.g. ``"native_multimodal_to_text"``,
            ``"provider_unavailable"``, ``"router_error"``).  Bounded by
            ``fallback_kinds_max`` distinct values.
        """
        with self._lock:
            self._fallback_triggers += 1
            kind = fallback_kind or "other"
            if (
                len(self._fallback_kind_counts) < self._fallback_kinds_max
                or kind in self._fallback_kind_counts
            ):
                self._fallback_kind_counts[kind] = (
                    self._fallback_kind_counts.get(kind, 0) + 1
                )

    # ------------------------------------------------------------------
    # Recovery recording
    # ------------------------------------------------------------------

    def record_recovery_attempt(self) -> None:
        """Record one recovery attempt (regardless of outcome)."""
        with self._lock:
            self._recovery_attempts += 1

    def record_recovery_resumed(self) -> None:
        """Record one recovery that resulted in a resumed execution."""
        with self._lock:
            self._recovery_resumed += 1

    def record_recovery_replayed(self) -> None:
        """Record one recovery that resulted in a replayed execution."""
        with self._lock:
            self._recovery_replayed += 1

    def record_recovery_reissued(self) -> None:
        """Record one recovery that resulted in a reissued dispatch."""
        with self._lock:
            self._recovery_reissued += 1

    def record_recovery_failed(self, reason: str = "") -> None:
        """Record one recovery attempt that failed.

        Parameters
        ----------
        reason:
            Failure reason string.  Bounded by ``failure_reasons_max``
            distinct values.
        """
        with self._lock:
            self._recovery_failed += 1
            if reason and (
                len(self._recovery_failure_reasons) < self._failure_reasons_max
                or reason in self._recovery_failure_reasons
            ):
                self._recovery_failure_reasons[reason] = (
                    self._recovery_failure_reasons.get(reason, 0) + 1
                )

    # ------------------------------------------------------------------
    # Startup recovery scan recording
    # ------------------------------------------------------------------

    def record_startup_recovery_scan(
        self, tasks_scanned: int = 0, actions_taken: int = 0
    ) -> None:
        """Record the outcome of a startup recovery scan.

        Should be called once per process start after
        :func:`~core.runtime_restart_recovery.run_startup_recovery` completes.

        Parameters
        ----------
        tasks_scanned:
            Number of in-flight task records inspected during the scan.
        actions_taken:
            Number of concrete runtime registry actions taken (resumed,
            replayed, reissued) as a result of the scan.
        """
        with self._lock:
            self._startup_recovery_tasks_scanned += max(0, int(tasks_scanned))
            self._startup_recovery_actions_taken += max(0, int(actions_taken))

    # ------------------------------------------------------------------
    # Audit persistence recording
    # ------------------------------------------------------------------

    def record_audit_persist_success(self) -> None:
        """Record one successful durable audit record write."""
        with self._lock:
            self._audit_persist_successes += 1

    def record_audit_persist_failure(self, reason: str = "") -> None:
        """Record one failed durable audit record write.

        Parameters
        ----------
        reason:
            Failure reason string (e.g. ``"io_error"``, ``"store_unavailable"``,
            ``"serialization_error"``).  Bounded by ``audit_failure_reasons_max``
            distinct values.
        """
        with self._lock:
            self._audit_persist_failures += 1
            if reason and (
                len(self._audit_persist_failure_reasons) < self._audit_failure_reasons_max
                or reason in self._audit_persist_failure_reasons
            ):
                self._audit_persist_failure_reasons[reason] = (
                    self._audit_persist_failure_reasons.get(reason, 0) + 1
                )

    # ------------------------------------------------------------------
    # Unified lifecycle/governance reliability ingestion
    # ------------------------------------------------------------------

    def ingest_unified_state_contract(self, state_contract: Optional[Dict[str, Any]]) -> None:
        """Ingest one V2 unified state-contract sample into reliability indicators.

        The ingestion is idempotent per subject + transition sequence:
        transition events that were already processed are ignored.
        """
        if not isinstance(state_contract, dict):
            return

        lifecycle = state_contract.get("lifecycle_hardening") or {}
        if not isinstance(lifecycle, dict) or lifecycle.get("error"):
            return

        transition_lineage = lifecycle.get("transition_lineage") or {}
        if not isinstance(transition_lineage, dict):
            transition_lineage = {}
        subject_id = str(transition_lineage.get("subject_id") or "subject:global")
        latest_sequence = int(transition_lineage.get("latest_sequence") or 0)
        events = transition_lineage.get("events") or []
        if not isinstance(events, list):
            events = []

        with self._lock:
            self._unified_ingest_total += 1
            subject_state = self._unified_subject_state.setdefault(
                subject_id,
                {
                    "initialized_at": None,
                    "readiness_ready_at": None,
                    "pending_initiations": 0,
                    "awaiting_path_switch_outcome": False,
                    "unresolved_blocker_volume": 0,
                },
            )

            raw_signals = state_contract.get("raw_signals") or {}
            derived_state = state_contract.get("derived_state") or {}
            closure_quality_state = state_contract.get("closure_quality_state") or {}

            if isinstance(raw_signals, dict) and isinstance(derived_state, dict):
                cross_device_decision = (
                    (derived_state.get("cross_device_availability") or {}).get("state")
                    if isinstance(derived_state.get("cross_device_availability"), dict)
                    else None
                )
                expected_cross_device = bool(
                    raw_signals.get("android_attached")
                    and raw_signals.get("capability_visible")
                    and int(raw_signals.get("active_session_count", 0)) > 0
                )
                observed_cross_device = cross_device_decision == "available"
                self._cross_device_consistency_total += 1
                if observed_cross_device == expected_cross_device:
                    self._cross_device_consistency_success_total += 1

            if isinstance(closure_quality_state, dict):
                quality_state = (
                    (closure_quality_state.get("success_quality") or {}).get("state")
                    if isinstance(closure_quality_state.get("success_quality"), dict)
                    else None
                )
                verdict_state = (
                    (closure_quality_state.get("verdict_quality") or {}).get("state")
                    if isinstance(closure_quality_state.get("verdict_quality"), dict)
                    else None
                )
                if quality_state:
                    self._quality_distribution[str(quality_state)] = (
                        self._quality_distribution.get(str(quality_state), 0) + 1
                    )
                if verdict_state:
                    self._verdict_distribution[str(verdict_state)] = (
                        self._verdict_distribution.get(str(verdict_state), 0) + 1
                    )

            task_initiation_gate = lifecycle.get("task_initiation_gate") or {}
            lifecycle_blocked = bool(lifecycle.get("lifecycle_blocked"))
            blocking_gates = (
                task_initiation_gate.get("blocking_gates")
                if isinstance(task_initiation_gate, dict)
                else []
            )
            if not isinstance(blocking_gates, list):
                blocking_gates = []
            subject_state["unresolved_blocker_volume"] = (
                len(blocking_gates) if lifecycle_blocked else 0
            )

            previous_sequence = int(self._unified_last_sequence_by_subject.get(subject_id, 0))
            new_events = []
            for event in events:
                if not isinstance(event, dict):
                    continue
                seq = int(event.get("sequence") or 0)
                if seq > previous_sequence:
                    new_events.append(event)

            for event in new_events:
                transition = str(event.get("transition") or "")
                to_state = str(event.get("to_state") or "")
                event_at = float(event.get("event_at") or time.time())

                if transition == "lifecycle_initialized":
                    subject_state["initialized_at"] = event_at

                if transition.startswith("admission_"):
                    if to_state:
                        self._admission_total += 1
                        if to_state in {"admitted", "admitted_degraded"}:
                            self._admission_success_total += 1
                        elif to_state in {"denied", "blocked"}:
                            self._admission_failure_total += 1

                if transition == "readiness_changed" and to_state == "ready":
                    if subject_state.get("readiness_ready_at") is None:
                        subject_state["readiness_ready_at"] = event_at
                        self._readiness_attainment_total += 1
                        initialized_at = subject_state.get("initialized_at")
                        if isinstance(initialized_at, (int, float)) and event_at >= initialized_at:
                            self._readiness_latency_count += 1
                            self._readiness_latency_sum_ms += (event_at - initialized_at) * 1000.0

                if transition == "task_initiated":
                    self._task_initiation_total += 1
                    subject_state["pending_initiations"] = int(subject_state.get("pending_initiations", 0)) + 1
                    readiness_ready_at = subject_state.get("readiness_ready_at")
                    if isinstance(readiness_ready_at, (int, float)) and event_at >= readiness_ready_at:
                        self._task_initiation_latency_count += 1
                        self._task_initiation_latency_sum_ms += (event_at - readiness_ready_at) * 1000.0

                if transition == "degraded_entered":
                    self._degraded_mode_entries_total += 1

                if transition == "recovery_started":
                    self._unified_recovery_attempts_total += 1
                elif transition == "recovery_completed":
                    self._unified_recovery_success_total += 1

                if transition in {"continuity_changed", "continuity_resumed"}:
                    self._session_continuity_events_total += 1
                    if transition != "continuity_resumed" and to_state in {
                        "incomplete",
                        "waiting_dependency",
                        "not_applicable",
                    }:
                        self._session_continuity_breaks_total += 1

                if transition == "operator_intervention_recorded":
                    self._operator_interventions_total += 1

                if transition == "path_switched":
                    self._path_switch_total += 1
                    subject_state["awaiting_path_switch_outcome"] = True

                if transition in {"closure_succeeded", "closure_changed"} and to_state:
                    self._closure_total += 1
                    self._closure_outcome_distribution[to_state] = (
                        self._closure_outcome_distribution.get(to_state, 0) + 1
                    )
                    pending = int(subject_state.get("pending_initiations", 0))
                    if pending > 0:
                        subject_state["pending_initiations"] = pending - 1
                        if to_state in {
                            "success_canonical",
                            "success_degraded",
                            "success_recovery",
                        }:
                            self._task_initiation_success_total += 1
                    if to_state in {"success_canonical", "success_degraded", "success_recovery"}:
                        self._closure_completed_total += 1
                        if subject_state.get("awaiting_path_switch_outcome"):
                            quality_state = (
                                (closure_quality_state.get("success_quality") or {}).get("state")
                                if isinstance(closure_quality_state.get("success_quality"), dict)
                                else ""
                            )
                            quality_key = str(quality_state or to_state)
                            self._path_switch_outcome_quality_distribution[quality_key] = (
                                self._path_switch_outcome_quality_distribution.get(quality_key, 0)
                                + 1
                            )
                            subject_state["awaiting_path_switch_outcome"] = False

            self._unified_last_sequence_by_subject[subject_id] = max(
                previous_sequence,
                latest_sequence,
                max((int(event.get("sequence") or 0) for event in new_events), default=0),
            )

    # ------------------------------------------------------------------
    # Computed properties
    # ------------------------------------------------------------------

    @property
    def dispatch_attempts(self) -> int:
        """Total dispatch attempts since last reset."""
        with self._lock:
            return self._dispatch_attempts

    @property
    def dispatch_success_rate(self) -> float:
        """Fraction of dispatch attempts that succeeded (0.0–1.0).

        Returns ``0.0`` when no attempts have been recorded.
        """
        with self._lock:
            if self._dispatch_attempts == 0:
                return 0.0
            return self._dispatch_successes / self._dispatch_attempts

    @property
    def dispatch_failure_rate(self) -> float:
        """Fraction of dispatch attempts that failed (0.0–1.0).

        Returns ``0.0`` when no attempts have been recorded.
        """
        with self._lock:
            if self._dispatch_attempts == 0:
                return 0.0
            return self._dispatch_failures / self._dispatch_attempts

    @property
    def recovery_success_rate(self) -> float:
        """Fraction of recovery attempts that produced a concrete action.

        A recovery attempt is "successful" if it resulted in a resumed,
        replayed, or reissued execution.  Returns ``0.0`` when no attempts
        have been recorded.
        """
        with self._lock:
            if self._recovery_attempts == 0:
                return 0.0
            succeeded = (
                self._recovery_resumed
                + self._recovery_replayed
                + self._recovery_reissued
            )
            return succeeded / self._recovery_attempts

    @property
    def audit_persist_failure_rate(self) -> float:
        """Fraction of audit persist operations that failed (0.0–1.0).

        Returns ``0.0`` when no persist operations have been recorded.
        """
        with self._lock:
            total = self._audit_persist_successes + self._audit_persist_failures
            if total == 0:
                return 0.0
            return self._audit_persist_failures / total

    # ------------------------------------------------------------------
    # Snapshot / export
    # ------------------------------------------------------------------

    def snapshot(self) -> Dict[str, Any]:
        """Return a JSON-serialisable snapshot of all operational SLO metrics.

        The returned dict is stable and additive — new keys may be added in
        future versions but existing keys will not be removed or renamed.
        """
        with self._lock:
            dispatch_attempts = self._dispatch_attempts
            dispatch_successes = self._dispatch_successes
            dispatch_failures = self._dispatch_failures
            dispatch_failure_reasons = dict(self._dispatch_failure_reasons)

            route_rejections = self._route_rejections
            route_rejection_reasons = dict(self._route_rejection_reasons)

            fallback_triggers = self._fallback_triggers
            fallback_kind_counts = dict(self._fallback_kind_counts)

            recovery_attempts = self._recovery_attempts
            recovery_resumed = self._recovery_resumed
            recovery_replayed = self._recovery_replayed
            recovery_reissued = self._recovery_reissued
            recovery_failed = self._recovery_failed
            recovery_failure_reasons = dict(self._recovery_failure_reasons)

            startup_tasks_scanned = self._startup_recovery_tasks_scanned
            startup_actions_taken = self._startup_recovery_actions_taken

            audit_persist_successes = self._audit_persist_successes
            audit_persist_failures = self._audit_persist_failures
            audit_persist_failure_reasons = dict(self._audit_persist_failure_reasons)

            unified_ingest_total = self._unified_ingest_total
            unified_subject_state = dict(self._unified_subject_state)
            admission_total = self._admission_total
            admission_success_total = self._admission_success_total
            admission_failure_total = self._admission_failure_total
            readiness_attainment_total = self._readiness_attainment_total
            readiness_latency_count = self._readiness_latency_count
            readiness_latency_sum_ms = self._readiness_latency_sum_ms
            task_initiation_total = self._task_initiation_total
            task_initiation_success_total = self._task_initiation_success_total
            task_initiation_latency_count = self._task_initiation_latency_count
            task_initiation_latency_sum_ms = self._task_initiation_latency_sum_ms
            closure_total = self._closure_total
            closure_completed_total = self._closure_completed_total
            closure_outcome_distribution = dict(self._closure_outcome_distribution)
            degraded_mode_entries_total = self._degraded_mode_entries_total
            unified_recovery_attempts_total = self._unified_recovery_attempts_total
            unified_recovery_success_total = self._unified_recovery_success_total
            cross_device_consistency_total = self._cross_device_consistency_total
            cross_device_consistency_success_total = self._cross_device_consistency_success_total
            session_continuity_events_total = self._session_continuity_events_total
            session_continuity_breaks_total = self._session_continuity_breaks_total
            operator_interventions_total = self._operator_interventions_total
            path_switch_total = self._path_switch_total
            path_switch_outcome_quality_distribution = dict(
                self._path_switch_outcome_quality_distribution
            )
            quality_distribution = dict(self._quality_distribution)
            verdict_distribution = dict(self._verdict_distribution)

        dispatch_success_rate = (
            dispatch_successes / dispatch_attempts if dispatch_attempts > 0 else 0.0
        )
        dispatch_failure_rate = (
            dispatch_failures / dispatch_attempts if dispatch_attempts > 0 else 0.0
        )
        recovery_succeeded = recovery_resumed + recovery_replayed + recovery_reissued
        recovery_success_rate = (
            recovery_succeeded / recovery_attempts if recovery_attempts > 0 else 0.0
        )
        audit_total = audit_persist_successes + audit_persist_failures
        audit_persist_failure_rate = (
            audit_persist_failures / audit_total if audit_total > 0 else 0.0
        )
        unresolved_blocker_volume = sum(
            int((item or {}).get("unresolved_blocker_volume", 0))
            for item in unified_subject_state.values()
            if isinstance(item, dict)
        )
        admission_success_rate = (
            admission_success_total / admission_total if admission_total > 0 else 0.0
        )
        admission_failure_rate = (
            admission_failure_total / admission_total if admission_total > 0 else 0.0
        )
        readiness_attainment_rate = (
            readiness_attainment_total / admission_success_total
            if admission_success_total > 0
            else 0.0
        )
        readiness_latency_ms = (
            readiness_latency_sum_ms / readiness_latency_count
            if readiness_latency_count > 0
            else None
        )
        task_initiation_latency_ms = (
            task_initiation_latency_sum_ms / task_initiation_latency_count
            if task_initiation_latency_count > 0
            else None
        )
        task_initiation_success_rate = (
            task_initiation_success_total / task_initiation_total
            if task_initiation_total > 0
            else 0.0
        )
        closure_completion_rate = (
            closure_completed_total / closure_total if closure_total > 0 else 0.0
        )
        degraded_mode_frequency = (
            degraded_mode_entries_total / unified_ingest_total
            if unified_ingest_total > 0
            else 0.0
        )
        unified_recovery_success_rate = (
            unified_recovery_success_total / unified_recovery_attempts_total
            if unified_recovery_attempts_total > 0
            else 0.0
        )
        cross_device_consistency_rate = (
            cross_device_consistency_success_total / cross_device_consistency_total
            if cross_device_consistency_total > 0
            else 0.0
        )
        session_continuity_break_rate = (
            session_continuity_breaks_total / session_continuity_events_total
            if session_continuity_events_total > 0
            else 0.0
        )
        operator_intervention_frequency = (
            operator_interventions_total / unified_ingest_total
            if unified_ingest_total > 0
            else 0.0
        )
        path_switch_frequency = (
            path_switch_total / unified_ingest_total if unified_ingest_total > 0 else 0.0
        )

        return {
            "schema_version": 1,
            "snapshotted_at": time.time(),
            "dispatch": {
                "attempts_total": dispatch_attempts,
                "successes_total": dispatch_successes,
                "failures_total": dispatch_failures,
                "success_rate": round(dispatch_success_rate, 6),
                "failure_rate": round(dispatch_failure_rate, 6),
                "failure_reason_counts": dispatch_failure_reasons,
            },
            "route_rejection": {
                "rejections_total": route_rejections,
                "rejection_reason_counts": route_rejection_reasons,
            },
            "fallback": {
                "triggers_total": fallback_triggers,
                "fallback_kind_counts": fallback_kind_counts,
            },
            "recovery": {
                "attempts_total": recovery_attempts,
                "resumed_total": recovery_resumed,
                "replayed_total": recovery_replayed,
                "reissued_total": recovery_reissued,
                "failed_total": recovery_failed,
                "success_rate": round(recovery_success_rate, 6),
                "failure_reason_counts": recovery_failure_reasons,
            },
            "startup_recovery": {
                "tasks_scanned_total": startup_tasks_scanned,
                "actions_taken_total": startup_actions_taken,
            },
            "audit_persistence": {
                "persist_successes_total": audit_persist_successes,
                "persist_failures_total": audit_persist_failures,
                "persist_failure_rate": round(audit_persist_failure_rate, 6),
                "persist_failure_reason_counts": audit_persist_failure_reasons,
            },
            "unified_reliability": {
                "samples_total": unified_ingest_total,
                "subjects_tracked_total": len(unified_subject_state),
                "admission": {
                    "success_rate": round(admission_success_rate, 6),
                    "failure_rate": round(admission_failure_rate, 6),
                    "successes_total": admission_success_total,
                    "failures_total": admission_failure_total,
                },
                "readiness": {
                    "attainment_rate": round(readiness_attainment_rate, 6),
                    "attained_total": readiness_attainment_total,
                    "latency_avg_ms": (
                        round(readiness_latency_ms, 3)
                        if isinstance(readiness_latency_ms, (int, float))
                        else None
                    ),
                },
                "task_initiation": {
                    "success_rate": round(task_initiation_success_rate, 6),
                    "initiated_total": task_initiation_total,
                    "successes_total": task_initiation_success_total,
                    "latency_avg_ms": (
                        round(task_initiation_latency_ms, 3)
                        if isinstance(task_initiation_latency_ms, (int, float))
                        else None
                    ),
                },
                "closure": {
                    "completion_rate": round(closure_completion_rate, 6),
                    "completed_total": closure_completed_total,
                    "observed_total": closure_total,
                    "outcome_distribution": closure_outcome_distribution,
                },
                "degraded_mode_frequency": round(degraded_mode_frequency, 6),
                "recovery": {
                    "success_rate": round(unified_recovery_success_rate, 6),
                    "attempts_total": unified_recovery_attempts_total,
                    "successes_total": unified_recovery_success_total,
                },
                "cross_device_consistency_rate": round(cross_device_consistency_rate, 6),
                "session_continuity_break_rate": round(session_continuity_break_rate, 6),
                "unresolved_blocker_volume": unresolved_blocker_volume,
                "quality_distribution": quality_distribution,
                "verdict_distribution": verdict_distribution,
                "operator_intervention_frequency": round(operator_intervention_frequency, 6),
                "path_switch": {
                    "frequency": round(path_switch_frequency, 6),
                    "switches_total": path_switch_total,
                    "outcome_quality_distribution": path_switch_outcome_quality_distribution,
                },
                "model_alignment": {
                    "uses_unified_state_contract": True,
                    "uses_lifecycle_hardening": True,
                    "health_buckets": {
                        "healthy": "success_canonical + non-degraded readiness",
                        "degraded": "success_degraded / degraded transitions",
                        "blocked": "lifecycle_blocked + unresolved blockers",
                        "closure_quality": "success_quality + verdict_quality distributions",
                    },
                },
            },
        }

    def prometheus_text(self) -> str:
        """Render operational SLO metrics as a Prometheus text-format string.

        The output follows the Prometheus exposition format:
        each metric has a ``# HELP`` line, a ``# TYPE`` line, and one or more
        value lines.
        """
        lines = []

        def _gauge(name: str, help_text: str, value: float) -> None:
            lines.append(f"# HELP {name} {help_text}")
            lines.append(f"# TYPE {name} gauge")
            lines.append(f"{name} {value}")

        def _counter(name: str, help_text: str, value: int) -> None:
            lines.append(f"# HELP {name} {help_text}")
            lines.append(f"# TYPE {name} counter")
            lines.append(f"{name} {value}")

        snap = self.snapshot()
        d = snap["dispatch"]
        r = snap["route_rejection"]
        fb = snap["fallback"]
        rec = snap["recovery"]
        sr = snap["startup_recovery"]
        ap = snap["audit_persistence"]

        # -- dispatch --
        _counter(
            "galaxy_ops_dispatch_attempts_total",
            "Total task dispatch attempts since last reset",
            d["attempts_total"],
        )
        _counter(
            "galaxy_ops_dispatch_successes_total",
            "Total successful task dispatch outcomes",
            d["successes_total"],
        )
        _counter(
            "galaxy_ops_dispatch_failures_total",
            "Total failed task dispatch outcomes",
            d["failures_total"],
        )
        _gauge(
            "galaxy_ops_dispatch_success_rate",
            "Fraction of dispatch attempts that succeeded (0.0-1.0)",
            round(d["success_rate"], 6),
        )
        _gauge(
            "galaxy_ops_dispatch_failure_rate",
            "Fraction of dispatch attempts that failed (0.0-1.0)",
            round(d["failure_rate"], 6),
        )

        # -- route rejection --
        _counter(
            "galaxy_ops_route_rejections_total",
            "Total route rejections recorded",
            r["rejections_total"],
        )

        # -- fallback --
        _counter(
            "galaxy_ops_fallback_triggers_total",
            "Total fallback triggers recorded",
            fb["triggers_total"],
        )

        # -- recovery --
        _counter(
            "galaxy_ops_recovery_attempts_total",
            "Total recovery attempts (regardless of outcome)",
            rec["attempts_total"],
        )
        _counter(
            "galaxy_ops_recovery_resumed_total",
            "Total recovery attempts that resulted in a resumed execution",
            rec["resumed_total"],
        )
        _counter(
            "galaxy_ops_recovery_replayed_total",
            "Total recovery attempts that resulted in a replayed execution",
            rec["replayed_total"],
        )
        _counter(
            "galaxy_ops_recovery_reissued_total",
            "Total recovery attempts that resulted in a reissued dispatch",
            rec["reissued_total"],
        )
        _counter(
            "galaxy_ops_recovery_failed_total",
            "Total recovery attempts that failed without a concrete action",
            rec["failed_total"],
        )
        _gauge(
            "galaxy_ops_recovery_success_rate",
            "Fraction of recovery attempts that produced a concrete action (0.0-1.0)",
            round(rec["success_rate"], 6),
        )

        ur = snap.get("unified_reliability") or {}
        ur_adm = ur.get("admission") or {}
        ur_readiness = ur.get("readiness") or {}
        ur_task = ur.get("task_initiation") or {}
        ur_closure = ur.get("closure") or {}
        ur_recovery = ur.get("recovery") or {}
        ur_path_switch = ur.get("path_switch") or {}

        _gauge(
            "galaxy_ops_unified_admission_success_rate",
            "Unified lifecycle admission success rate (0.0-1.0)",
            round(float(ur_adm.get("success_rate", 0.0) or 0.0), 6),
        )
        _gauge(
            "galaxy_ops_unified_readiness_attainment_rate",
            "Unified lifecycle readiness attainment rate (0.0-1.0)",
            round(float(ur_readiness.get("attainment_rate", 0.0) or 0.0), 6),
        )
        _gauge(
            "galaxy_ops_unified_task_initiation_success_rate",
            "Unified lifecycle task initiation success rate (0.0-1.0)",
            round(float(ur_task.get("success_rate", 0.0) or 0.0), 6),
        )
        _gauge(
            "galaxy_ops_unified_closure_completion_rate",
            "Unified lifecycle closure completion rate (0.0-1.0)",
            round(float(ur_closure.get("completion_rate", 0.0) or 0.0), 6),
        )
        _gauge(
            "galaxy_ops_unified_recovery_success_rate",
            "Unified lifecycle recovery success rate (0.0-1.0)",
            round(float(ur_recovery.get("success_rate", 0.0) or 0.0), 6),
        )
        _gauge(
            "galaxy_ops_unified_cross_device_consistency_rate",
            "Unified cross-device consistency rate (0.0-1.0)",
            round(float(ur.get("cross_device_consistency_rate", 0.0) or 0.0), 6),
        )
        _gauge(
            "galaxy_ops_unified_session_continuity_break_rate",
            "Unified session continuity break rate (0.0-1.0)",
            round(float(ur.get("session_continuity_break_rate", 0.0) or 0.0), 6),
        )
        _gauge(
            "galaxy_ops_unified_operator_intervention_frequency",
            "Unified operator intervention frequency per sample",
            round(float(ur.get("operator_intervention_frequency", 0.0) or 0.0), 6),
        )
        _gauge(
            "galaxy_ops_unified_path_switch_frequency",
            "Unified path-switch frequency per sample",
            round(float(ur_path_switch.get("frequency", 0.0) or 0.0), 6),
        )
        _gauge(
            "galaxy_ops_unified_unresolved_blocker_volume",
            "Unified unresolved blocker volume across tracked subjects",
            float(ur.get("unresolved_blocker_volume", 0) or 0),
        )

        # -- startup recovery scan --
        _counter(
            "galaxy_ops_startup_recovery_tasks_scanned_total",
            "Total in-flight task records scanned during startup recovery pass",
            sr["tasks_scanned_total"],
        )
        _counter(
            "galaxy_ops_startup_recovery_actions_taken_total",
            "Total runtime registry actions taken by startup recovery pass",
            sr["actions_taken_total"],
        )

        # -- audit persistence --
        _counter(
            "galaxy_ops_audit_persist_successes_total",
            "Total durable audit record writes that succeeded",
            ap["persist_successes_total"],
        )
        _counter(
            "galaxy_ops_audit_persist_failures_total",
            "Total durable audit record writes that failed",
            ap["persist_failures_total"],
        )
        _gauge(
            "galaxy_ops_audit_persist_failure_rate",
            "Fraction of audit persist operations that failed (0.0-1.0)",
            round(ap["persist_failure_rate"], 6),
        )

        return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Process-level singleton
# ---------------------------------------------------------------------------

_ops_metrics: Optional[OperationalSLOMetrics] = None
_ops_lock = threading.Lock()


def get_operational_slo_metrics() -> OperationalSLOMetrics:
    """Return the process-level :class:`OperationalSLOMetrics` singleton.

    The singleton is created lazily on first access.  Capacity limits are
    read from environment variables at creation time:

    ``GALAXY_OPS_REJECTION_REASONS_MAX``   (default 200)
    ``GALAXY_OPS_FALLBACK_KINDS_MAX``      (default 50)
    ``GALAXY_OPS_FAILURE_REASONS_MAX``     (default 200)
    ``GALAXY_OPS_AUDIT_FAILURE_REASONS_MAX`` (default 100)
    """
    global _ops_metrics
    if _ops_metrics is None:
        with _ops_lock:
            if _ops_metrics is None:
                _ops_metrics = OperationalSLOMetrics(
                    rejection_reasons_max=int(
                        os.getenv("GALAXY_OPS_REJECTION_REASONS_MAX", "200")
                    ),
                    fallback_kinds_max=int(
                        os.getenv("GALAXY_OPS_FALLBACK_KINDS_MAX", "50")
                    ),
                    failure_reasons_max=int(
                        os.getenv("GALAXY_OPS_FAILURE_REASONS_MAX", "200")
                    ),
                    audit_failure_reasons_max=int(
                        os.getenv("GALAXY_OPS_AUDIT_FAILURE_REASONS_MAX", "100")
                    ),
                )
    return _ops_metrics


def reset_operational_slo_metrics() -> None:
    """Reset the global :class:`OperationalSLOMetrics` singleton (for tests)."""
    global _ops_metrics
    with _ops_lock:
        _ops_metrics = None
