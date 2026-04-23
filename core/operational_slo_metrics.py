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
            if reason and len(self._dispatch_failure_reasons) < self._failure_reasons_max:
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
            if reason and len(self._route_rejection_reasons) < self._rejection_reasons_max:
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
            if len(self._fallback_kind_counts) < self._fallback_kinds_max:
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
            if reason and len(self._recovery_failure_reasons) < self._failure_reasons_max:
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
            if reason and len(self._audit_persist_failure_reasons) < self._audit_failure_reasons_max:
                self._audit_persist_failure_reasons[reason] = (
                    self._audit_persist_failure_reasons.get(reason, 0) + 1
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
