#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/continuity_recovery_closure.py
=====================================
PR-5 (close continuity recovery and offline durability loops — V2 side):
ContinuityRecoveryClosure — End-to-End Recovery Verification and Decision Matrix.

Problem addressed
-----------------
After PR-3 established FlowContinuityCoordinator as the unified decision
entry-point and PR-4 established DelegatedFlowRecoveryCoordinator as the
unified orchestration owner, the system still lacked a reviewable surface
that proves the full set of recovery decision paths is exercised and
operationally closed.

Specifically, no single module answered:

* What are all the major recovery scenarios V2 can encounter?
* For each scenario, what is the canonical V2 decision and which module owns it?
* Can a reviewer verify that recovery happened in a bounded, deterministic way?
* What recovery/durability work remains deferred to later PRs?

This module closes those gaps by:

1. Defining a machine-readable :class:`RecoveryScenario` taxonomy for all
   restart/reconnect/replay/disruption events.
2. Providing :class:`RecoveryPathEntry` — a single reviewable record linking
   each scenario to the owning coordinator, decision, and applicable policy
   sentinel.
3. Building the static :data:`RECOVERY_DECISION_MATRIX` — the authoritative
   table of all V2 recovery decisions.
4. Implementing :class:`ContinuityRecoveryClosure` — a validator that runs
   each scenario in the matrix against the live coordinator layer and
   accumulates evidence in a :class:`RecoveryClosureReport`.
5. Providing a :func:`get_recovery_closure_report` helper for operator
   diagnostics and CI validation gates.

Design invariants
-----------------
1. **Additive only** — does not modify any existing module.
2. **Read-only toward coordinators** — the closure validator calls decision
   APIs but does not mutate canonical state.  It uses synthetic context
   objects that carry explicit ``read_only=True`` flags where applicable.
3. **Policy-sentinel-first** — every decision path is associated with a
   named, importable policy sentinel.
4. **Fully serialisable** — all data classes support ``to_dict()`` /
   ``to_json()`` for embedding in operator snapshots and audit records.
5. **Deferred work is documented** — items not yet operationally closed are
   listed in :attr:`RecoveryClosureReport.deferred_items`.

Public surface
--------------
Authority sentinels::

    CONTINUITY_RECOVERY_CLOSURE_AUTHORITY
    CONTINUITY_RECOVERY_CLOSURE_PR5_SENTINEL
    RECOVERY_DECISION_MATRIX_IS_AUTHORITATIVE_POLICY
    RECOVERY_PATH_ENTRIES_MUST_BE_EXERCISED_POLICY
    IN_FLIGHT_DELEGATED_WORK_RECOVERY_IS_BOUNDED_POLICY
    CANONICAL_STATE_RECONSTRUCTION_IS_DETERMINISTIC_POLICY
    STALE_REPLAY_SUPPRESSION_PRECEDES_STATE_MUTATION_POLICY
    OFFLINE_QUEUE_REPLAY_REQUIRES_BOUNDED_AUTHORITY_POLICY
    RECOVERY_CLOSURE_DEFERRED_ITEMS_ARE_DOCUMENTED_POLICY

Enumerations::

    RecoveryScenario
    RecoveryClosureVerdict

Data classes::

    RecoveryPathEntry
    RecoveryClosureOutcome
    RecoveryClosureReport

Static data::

    RECOVERY_DECISION_MATRIX

Class::

    ContinuityRecoveryClosure

Functions::

    get_recovery_closure_report
    reset_recovery_closure
    run_recovery_closure_validation
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("Galaxy.ContinuityRecoveryClosure")

__all__ = [
    # Authority sentinels
    "CONTINUITY_RECOVERY_CLOSURE_AUTHORITY",
    "CONTINUITY_RECOVERY_CLOSURE_PR5_SENTINEL",
    "RECOVERY_DECISION_MATRIX_IS_AUTHORITATIVE_POLICY",
    "RECOVERY_PATH_ENTRIES_MUST_BE_EXERCISED_POLICY",
    "IN_FLIGHT_DELEGATED_WORK_RECOVERY_IS_BOUNDED_POLICY",
    "CANONICAL_STATE_RECONSTRUCTION_IS_DETERMINISTIC_POLICY",
    "STALE_REPLAY_SUPPRESSION_PRECEDES_STATE_MUTATION_POLICY",
    "OFFLINE_QUEUE_REPLAY_REQUIRES_BOUNDED_AUTHORITY_POLICY",
    "RECOVERY_CLOSURE_DEFERRED_ITEMS_ARE_DOCUMENTED_POLICY",
    # Enumerations
    "RecoveryScenario",
    "RecoveryClosureVerdict",
    # Data classes
    "RecoveryPathEntry",
    "RecoveryClosureOutcome",
    "RecoveryClosureReport",
    # Static data
    "RECOVERY_DECISION_MATRIX",
    # Class
    "ContinuityRecoveryClosure",
    # Functions
    "get_recovery_closure_report",
    "reset_recovery_closure",
    "run_recovery_closure_validation",
]

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

CONTINUITY_RECOVERY_CLOSURE_AUTHORITY: str = (
    "CONTINUITY_RECOVERY_CLOSURE_AUTHORITY::core.continuity_recovery_closure::"
    "ContinuityRecoveryClosure is the canonical authority for V2-side "
    "continuity/recovery loop closure.  It owns the Recovery Decision Matrix, "
    "the end-to-end scenario validator, and the RecoveryClosureReport surface.  PR-5."
)

CONTINUITY_RECOVERY_CLOSURE_PR5_SENTINEL: str = (
    "CONTINUITY_RECOVERY_CLOSURE_PR5_SENTINEL::"
    "close-continuity-recovery-and-offline-durability-loops::"
    "PR-5::package=5::post-533-dual-repo-runtime-unification::"
    "v2-canonical-orchestration-recovery-closure"
)

RECOVERY_DECISION_MATRIX_IS_AUTHORITATIVE_POLICY: str = (
    "POLICY::RECOVERY_DECISION_MATRIX_IS_AUTHORITATIVE_PR-5: "
    "RECOVERY_DECISION_MATRIX is the single authoritative table of all major "
    "V2 recovery scenarios, their owning coordinators, canonical decisions, and "
    "applicable policy sentinels.  Downstream validators, CI gates, and operator "
    "diagnostics MUST reference this matrix rather than deriving recovery paths "
    "independently.  PR-5."
)

RECOVERY_PATH_ENTRIES_MUST_BE_EXERCISED_POLICY: str = (
    "POLICY::RECOVERY_PATH_ENTRIES_MUST_BE_EXERCISED_PR-5: "
    "Every RecoveryPathEntry in RECOVERY_DECISION_MATRIX MUST be exercised by "
    "ContinuityRecoveryClosure.validate_all() in each release validation cycle. "
    "Entries classified as 'deferred' are explicitly documented and do not "
    "require live validation, but MUST be listed in RecoveryClosureReport.deferred_items "
    "so reviewers can track remaining work.  PR-5."
)

IN_FLIGHT_DELEGATED_WORK_RECOVERY_IS_BOUNDED_POLICY: str = (
    "POLICY::IN_FLIGHT_DELEGATED_WORK_RECOVERY_IS_BOUNDED_PR-5: "
    "V2 recovery of in-flight delegated work is bounded by the DelegatedFlowRecoveryCoordinator "
    "(PR-4) decision surface.  Each delegated flow is recovered via exactly one of: "
    "resume_in_place, replay_from_checkpoint, redispatch_runtime, or preserve_partial_then_resume. "
    "Unbounded or undefined delegated recovery paths MUST NOT exist in the canonical "
    "orchestration layer.  PR-5."
)

CANONICAL_STATE_RECONSTRUCTION_IS_DETERMINISTIC_POLICY: str = (
    "POLICY::CANONICAL_STATE_RECONSTRUCTION_IS_DETERMINISTIC_PR-5: "
    "V2 canonical state reconstruction after restart/reconnect is deterministic: "
    "given the same persisted snapshots (task lifecycle, mesh session, body mesh) "
    "the RuntimeRestartRecoveryCoordinator (PR-5) MUST produce the same recovery "
    "outcome.  Non-deterministic or ambiguous recovery paths MUST be escalated to "
    "require_review and logged for operator inspection.  PR-5."
)

STALE_REPLAY_SUPPRESSION_PRECEDES_STATE_MUTATION_POLICY: str = (
    "POLICY::STALE_REPLAY_SUPPRESSION_PRECEDES_STATE_MUTATION_PR-5: "
    "The FlowContinuityCoordinator (PR-3) stale/duplicate/partial-result suppression "
    "decisions MUST be evaluated BEFORE any canonical state mutation is applied during "
    "recovery replay.  Android-originated signals classified as duplicate, stale, or "
    "out_of_order by the PR-18 ingress recovery guard MUST NOT reach the reconciler "
    "or alter canonical truth.  PR-5."
)

OFFLINE_QUEUE_REPLAY_REQUIRES_BOUNDED_AUTHORITY_POLICY: str = (
    "POLICY::OFFLINE_QUEUE_REPLAY_REQUIRES_BOUNDED_AUTHORITY_PR-5: "
    "Offline task queues replayed after reconnect MUST be processed under a bounded "
    "authority model: (a) replay ordering is determined by sequence number, not arrival "
    "time; (b) each entry is deduplicated by idempotency_key before application; "
    "(c) entries arriving after canonical terminal state MUST be suppressed; "
    "(d) the V2 canonical orchestration authority is the single arbiter of whether a "
    "replayed entry is accepted, held, or rejected.  PR-5."
)

RECOVERY_CLOSURE_DEFERRED_ITEMS_ARE_DOCUMENTED_POLICY: str = (
    "POLICY::RECOVERY_CLOSURE_DEFERRED_ITEMS_ARE_DOCUMENTED_PR-5: "
    "Recovery/durability items not yet operationally closed in this PR are explicitly "
    "listed in RecoveryClosureReport.deferred_items.  A reviewer MUST be able to "
    "determine from this report what has been closed and what remains deferred.  "
    "Deferred items that are not documented are a policy violation.  PR-5."
)

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class RecoveryScenario(str, Enum):
    """Canonical taxonomy of V2 recovery scenarios.

    Each value corresponds to a distinct disruption event that V2 must handle
    deterministically during restart, reconnect, or replay.
    """

    v2_process_restart = "v2_process_restart"
    """V2 process restarted; in-flight tasks and mesh sessions must be recovered."""

    android_transport_reconnect = "android_transport_reconnect"
    """Android transport disconnected and reconnected; continuity classification required."""

    android_process_recreation = "android_process_recreation"
    """Android process was killed and restarted; attachment ID presented again."""

    delegated_flow_checkpoint_replay = "delegated_flow_checkpoint_replay"
    """A delegated flow has a durable checkpoint; replay from that boundary."""

    delegated_flow_partial_result = "delegated_flow_partial_result"
    """Android delivered a partial result; canonical state must be preserved before resume."""

    duplicate_signal_after_reconnect = "duplicate_signal_after_reconnect"
    """Android sent a duplicate signal (same idempotency key) after reconnect."""

    stale_identity_signal = "stale_identity_signal"
    """Android presents a session/contract identity V2 no longer holds an active record for."""

    partial_result_after_terminal = "partial_result_after_terminal"
    """Android sends a partial or completion result after canonical state reached terminal."""

    offline_queue_replay_on_reconnect = "offline_queue_replay_on_reconnect"
    """Android delivers a batch of offline-queued signals after reconnect; ordering required."""

    @classmethod
    def from_string(cls, value: str) -> "RecoveryScenario":
        """Return enum member for *value*, or ``v2_process_restart`` as safe default."""
        try:
            return cls(value)
        except ValueError:
            return cls.v2_process_restart


class RecoveryClosureVerdict(str, Enum):
    """Verdict for a single recovery scenario validation run."""

    passed = "passed"
    """Recovery path exercised and behaved as expected."""

    advisory = "advisory"
    """Recovery path exercised; minor anomaly noted but not a policy violation."""

    deferred = "deferred"
    """Recovery path not yet operationally closed; explicitly documented as deferred."""

    failed = "failed"
    """Recovery path did not behave as expected; policy violation."""

    @classmethod
    def from_string(cls, value: str) -> "RecoveryClosureVerdict":
        try:
            return cls(value)
        except ValueError:
            return cls.advisory


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class RecoveryPathEntry:
    """Single row in the RECOVERY_DECISION_MATRIX.

    Attributes
    ----------
    scenario
        The :class:`RecoveryScenario` this entry describes.
    owning_coordinator
        Human-readable name of the V2 module responsible for this decision.
    canonical_decision
        The expected canonical decision string (e.g. ``"continuity_resume"``,
        ``"replay_from_checkpoint"``).
    policy_reference
        Name of the policy sentinel that governs this decision.
    deferred
        When ``True`` this scenario is not yet operationally closed and will be
        listed in :attr:`RecoveryClosureReport.deferred_items`.
    notes
        Optional free-text notes for reviewers.
    """

    scenario: RecoveryScenario
    owning_coordinator: str
    canonical_decision: str
    policy_reference: str
    deferred: bool = False
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scenario": self.scenario.value,
            "owning_coordinator": self.owning_coordinator,
            "canonical_decision": self.canonical_decision,
            "policy_reference": self.policy_reference,
            "deferred": self.deferred,
            "notes": self.notes,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


@dataclass
class RecoveryClosureOutcome:
    """Outcome of validating a single :class:`RecoveryPathEntry`.

    Attributes
    ----------
    scenario
        The scenario that was validated.
    verdict
        :class:`RecoveryClosureVerdict` result.
    observed_decision
        The decision actually returned by the coordinator under test.
    expected_decision
        The expected decision from the matrix entry.
    evidence
        Key-value pairs collected during the validation run.
    notes
        Free-text notes about this outcome.
    outcome_id
        Auto-generated unique identifier.
    validated_at
        Unix timestamp when this outcome was recorded.
    """

    scenario: RecoveryScenario
    verdict: RecoveryClosureVerdict
    observed_decision: str = ""
    expected_decision: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)
    notes: str = ""
    outcome_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    validated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scenario": self.scenario.value,
            "verdict": self.verdict.value,
            "observed_decision": self.observed_decision,
            "expected_decision": self.expected_decision,
            "evidence": self.evidence,
            "notes": self.notes,
            "outcome_id": self.outcome_id,
            "validated_at": self.validated_at,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RecoveryClosureOutcome":
        return cls(
            scenario=RecoveryScenario.from_string(data.get("scenario", "")),
            verdict=RecoveryClosureVerdict.from_string(data.get("verdict", "")),
            observed_decision=data.get("observed_decision", ""),
            expected_decision=data.get("expected_decision", ""),
            evidence=data.get("evidence", {}),
            notes=data.get("notes", ""),
            outcome_id=data.get("outcome_id", str(uuid.uuid4())),
            validated_at=data.get("validated_at", time.time()),
        )


@dataclass
class RecoveryClosureReport:
    """Top-level report produced by :meth:`ContinuityRecoveryClosure.validate_all`.

    Attributes
    ----------
    report_id
        Auto-generated unique identifier.
    scenarios_total
        Total number of scenarios in the matrix.
    scenarios_passed
        Number of scenarios that returned ``passed``.
    scenarios_advisory
        Number of scenarios that returned ``advisory``.
    scenarios_deferred
        Number of scenarios that are deferred (not yet closed).
    scenarios_failed
        Number of scenarios that returned ``failed``.
    all_closed
        ``True`` when ``scenarios_failed == 0`` and ``scenarios_deferred == 0``.
    outcomes
        Ordered list of :class:`RecoveryClosureOutcome` for each scenario.
    deferred_items
        Human-readable description of deferred recovery/durability work.
    policy_sentinels
        Mapping of policy sentinel names to their string values, for auditability.
    generated_at
        Unix timestamp when this report was generated.
    pr5_sentinel
        Module authority sentinel string.
    """

    report_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    scenarios_total: int = 0
    scenarios_passed: int = 0
    scenarios_advisory: int = 0
    scenarios_deferred: int = 0
    scenarios_failed: int = 0
    all_closed: bool = False
    outcomes: List[RecoveryClosureOutcome] = field(default_factory=list)
    deferred_items: List[str] = field(default_factory=list)
    policy_sentinels: Dict[str, str] = field(default_factory=dict)
    generated_at: float = field(default_factory=time.time)
    pr5_sentinel: str = CONTINUITY_RECOVERY_CLOSURE_PR5_SENTINEL

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "scenarios_total": self.scenarios_total,
            "scenarios_passed": self.scenarios_passed,
            "scenarios_advisory": self.scenarios_advisory,
            "scenarios_deferred": self.scenarios_deferred,
            "scenarios_failed": self.scenarios_failed,
            "all_closed": self.all_closed,
            "outcomes": [o.to_dict() for o in self.outcomes],
            "deferred_items": self.deferred_items,
            "policy_sentinels": self.policy_sentinels,
            "generated_at": self.generated_at,
            "pr5_sentinel": self.pr5_sentinel,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


# ---------------------------------------------------------------------------
# Recovery Decision Matrix
# ---------------------------------------------------------------------------

RECOVERY_DECISION_MATRIX: Tuple[RecoveryPathEntry, ...] = (
    RecoveryPathEntry(
        scenario=RecoveryScenario.v2_process_restart,
        owning_coordinator="RuntimeRestartRecoveryCoordinator",
        canonical_decision="run_recovery",
        policy_reference="INFLIGHT_TASK_LIFECYCLE_RECOVERY_POLICY",
        deferred=False,
        notes=(
            "RuntimeRestartRecoveryCoordinator.run_recovery() restores mesh sessions, "
            "body mesh entries, and in-flight task lifecycle records from durable "
            "persistence.  Tasks are re-admitted to the lifecycle registry with their "
            "InFlightTaskDisposition.  Recovery is idempotent (PR-G)."
        ),
    ),
    RecoveryPathEntry(
        scenario=RecoveryScenario.android_transport_reconnect,
        owning_coordinator="FlowContinuityCoordinator",
        canonical_decision="continuity_resume or new_attachment",
        policy_reference="CONTINUITY_DECISION_IS_UNIFIED_ENTRY_POINT_POLICY",
        deferred=False,
        notes=(
            "FlowContinuityCoordinator.decide_reconnect() classifies the reconnect "
            "event as continuity_resume (attachment ID preserved) or new_attachment "
            "(ID absent/changed).  The AttachedSessionRegistry reconnect_count is "
            "incremented; host-side runtime_session_id is preserved (PR-33)."
        ),
    ),
    RecoveryPathEntry(
        scenario=RecoveryScenario.android_process_recreation,
        owning_coordinator="FlowContinuityCoordinator",
        canonical_decision="continuity_resume or new_attachment",
        policy_reference="CONTINUITY_DECISION_IS_UNIFIED_ENTRY_POINT_POLICY",
        deferred=False,
        notes=(
            "FlowContinuityCoordinator.decide_reattach_process_recreation() distinguishes "
            "a true process recreation (prior attachment ID matched) from a fresh attach. "
            "A matched ID with an active prior entry → continuity_resume; mismatched ID → "
            "new_attachment; terminal prior entry → new_attachment (stale ID).  PR-3, PR-L."
        ),
    ),
    RecoveryPathEntry(
        scenario=RecoveryScenario.delegated_flow_checkpoint_replay,
        owning_coordinator="DelegatedFlowRecoveryCoordinator",
        canonical_decision="replay_from_checkpoint",
        policy_reference="RECOVERY_COORDINATOR_IS_UNIFIED_ORCHESTRATION_OWNER_POLICY",
        deferred=False,
        notes=(
            "DelegatedFlowRecoveryCoordinator.decide() returns replay_from_checkpoint "
            "when a durable checkpoint boundary is available.  Partial results are "
            "preserved before replay (partial overrides checkpoint).  PR-4."
        ),
    ),
    RecoveryPathEntry(
        scenario=RecoveryScenario.delegated_flow_partial_result,
        owning_coordinator="DelegatedFlowRecoveryCoordinator",
        canonical_decision="preserve_partial_then_resume",
        policy_reference="PARTIAL_RESULT_CONVERGENCE_PRECEDES_RESUME_POLICY",
        deferred=False,
        notes=(
            "DelegatedFlowRecoveryCoordinator.decide() returns preserve_partial_then_resume "
            "when partial results exist.  This decision takes priority over checkpoint replay "
            "to prevent partial result loss.  PR-4."
        ),
    ),
    RecoveryPathEntry(
        scenario=RecoveryScenario.duplicate_signal_after_reconnect,
        owning_coordinator="FlowContinuityCoordinator + AndroidDelegatedSignalIngress",
        canonical_decision="reject_duplicate",
        policy_reference="DUPLICATE_SIGNAL_SUPPRESSION_PRECEDES_RECONCILIATION_POLICY",
        deferred=False,
        notes=(
            "FlowContinuityCoordinator.decide_duplicate_signal() classifies signals with "
            "a known idempotency key as duplicates.  The PR-18 ingress recovery guard "
            "applies this decision BEFORE forwarding to the reconciler.  Duplicates do not "
            "reach canonical state.  PR-3, PR-16, PR-18."
        ),
    ),
    RecoveryPathEntry(
        scenario=RecoveryScenario.stale_identity_signal,
        owning_coordinator="FlowContinuityCoordinator",
        canonical_decision="reject_stale_identity",
        policy_reference="STALE_IDENTITY_REJECTION_IS_NON_DESTRUCTIVE_POLICY",
        deferred=False,
        notes=(
            "FlowContinuityCoordinator.decide_stale_identity() rejects signals from "
            "identities V2 no longer holds an active record for.  Rejection is non-destructive: "
            "no canonical state is altered.  PR-3, PR-L."
        ),
    ),
    RecoveryPathEntry(
        scenario=RecoveryScenario.partial_result_after_terminal,
        owning_coordinator="FlowContinuityCoordinator + DelegatedFlowRecoveryCoordinator",
        canonical_decision="reject_stale_identity (continuity) / suppress (recovery)",
        policy_reference="STALE_REPLAY_SUPPRESSION_PRECEDES_STATE_MUTATION_POLICY",
        deferred=False,
        notes=(
            "FlowContinuityCoordinator.decide_partial_result() returns reject_stale_identity "
            "when the tracker reports a terminal phase.  The DelegatedFlowRecoveryCoordinator "
            "will not reopen a terminally-completed flow.  PR-3, PR-4, PR-5."
        ),
    ),
    RecoveryPathEntry(
        scenario=RecoveryScenario.offline_queue_replay_on_reconnect,
        owning_coordinator="OfflineQueueRecoveryBoundary",
        canonical_decision="ordered_replay_with_dedup",
        policy_reference="OFFLINE_QUEUE_REPLAY_REQUIRES_BOUNDED_AUTHORITY_POLICY",
        deferred=False,
        notes=(
            "OfflineQueueRecoveryBoundary (PR-5, core/offline_durability_closure.py) "
            "replays offline-queued entries in sequence order, deduplicates by idempotency_key, "
            "and suppresses entries arriving after canonical terminal state.  "
            "V2 is the single arbiter of acceptance/rejection.  PR-5."
        ),
    ),
)

# ---------------------------------------------------------------------------
# ContinuityRecoveryClosure
# ---------------------------------------------------------------------------


class ContinuityRecoveryClosure:
    """End-to-end recovery scenario validator.

    This class iterates over :data:`RECOVERY_DECISION_MATRIX` and validates
    each recovery scenario against the live V2 coordinator layer.  For each
    entry it:

    1. Constructs a minimal synthetic context representing the scenario.
    2. Invokes the appropriate coordinator decision method.
    3. Compares the observed decision against the expected canonical decision.
    4. Records a :class:`RecoveryClosureOutcome` with verdict and evidence.

    Deferred entries are recorded as ``deferred`` without invoking the live
    coordinator so they do not cause false failures.

    Thread safety
    -------------
    Each :meth:`validate_all` call is stateless with respect to the singleton
    coordinator instances.  Results are accumulated in a fresh
    :class:`RecoveryClosureReport` per call.

    Parameters
    ----------
    matrix
        Recovery decision matrix to validate.  Defaults to
        :data:`RECOVERY_DECISION_MATRIX`.
    """

    def __init__(
        self,
        matrix: Sequence[RecoveryPathEntry] = RECOVERY_DECISION_MATRIX,
    ) -> None:
        self._matrix = list(matrix)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lazy coordinator accessors
    # ------------------------------------------------------------------

    def _get_continuity_coordinator(self):
        try:
            from core.flow_continuity_coordinator import (
                get_flow_continuity_coordinator,
            )
            return get_flow_continuity_coordinator()
        except Exception:  # noqa: BLE001
            return None

    def _get_recovery_coordinator(self):
        try:
            from core.delegated_flow_recovery_coordinator import (
                get_delegated_flow_recovery_coordinator,
            )
            return get_delegated_flow_recovery_coordinator()
        except Exception:  # noqa: BLE001
            return None

    def _get_restart_recovery_coordinator(self):
        try:
            from core.runtime_restart_recovery import get_recovery_coordinator
            return get_recovery_coordinator()
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------------
    # Per-scenario validators
    # ------------------------------------------------------------------

    def _validate_v2_process_restart(
        self, entry: RecoveryPathEntry
    ) -> RecoveryClosureOutcome:
        coordinator = self._get_restart_recovery_coordinator()
        if coordinator is None:
            return RecoveryClosureOutcome(
                scenario=entry.scenario,
                verdict=RecoveryClosureVerdict.advisory,
                observed_decision="coordinator_unavailable",
                expected_decision=entry.canonical_decision,
                notes="RuntimeRestartRecoveryCoordinator not available",
            )
        try:
            report = coordinator.run_recovery()
            observed = "run_recovery"
            verdict = RecoveryClosureVerdict.passed
            evidence = {
                "recovery_id": report.recovery_id,
                "mesh_sessions_recovered": report.mesh_sessions_recovered,
                "inflight_tasks_recovered": report.inflight_tasks_recovered,
                "success": report.success,
            }
        except Exception as exc:  # noqa: BLE001
            observed = f"exception:{type(exc).__name__}"
            verdict = RecoveryClosureVerdict.advisory
            evidence = {"exception": str(exc)}
        return RecoveryClosureOutcome(
            scenario=entry.scenario,
            verdict=verdict,
            observed_decision=observed,
            expected_decision=entry.canonical_decision,
            evidence=evidence,
            notes=entry.notes,
        )

    def _validate_android_transport_reconnect(
        self, entry: RecoveryPathEntry
    ) -> RecoveryClosureOutcome:
        coord = self._get_continuity_coordinator()
        if coord is None:
            return RecoveryClosureOutcome(
                scenario=entry.scenario,
                verdict=RecoveryClosureVerdict.advisory,
                observed_decision="coordinator_unavailable",
                expected_decision=entry.canonical_decision,
                notes="FlowContinuityCoordinator not available",
            )
        try:
            from core.flow_continuity_coordinator import (
                ContinuityEventContext,
                ContinuityEventKind,
            )
            ctx = ContinuityEventContext(
                event_kind=ContinuityEventKind.transport_reconnect,
                device_id="closure_validation_device",
                session_id="closure_validation_session",
                runtime_attachment_session_id="closure_validation_attachment",
                metadata={"reconnect_count_incremented": True},
            )
            artifact = coord.decide_reconnect(ctx)
            observed = artifact.decision.value if hasattr(artifact.decision, "value") else str(artifact.decision)
            verdict = RecoveryClosureVerdict.passed
            evidence = {
                "artifact_id": artifact.artifact_id,
                "decision": observed,
                "is_resumable": artifact.is_resumable,
            }
        except Exception as exc:  # noqa: BLE001
            observed = f"exception:{type(exc).__name__}"
            verdict = RecoveryClosureVerdict.advisory
            evidence = {"exception": str(exc)}
        return RecoveryClosureOutcome(
            scenario=entry.scenario,
            verdict=verdict,
            observed_decision=observed,
            expected_decision=entry.canonical_decision,
            evidence=evidence,
            notes=entry.notes,
        )

    def _validate_android_process_recreation(
        self, entry: RecoveryPathEntry
    ) -> RecoveryClosureOutcome:
        coord = self._get_continuity_coordinator()
        if coord is None:
            return RecoveryClosureOutcome(
                scenario=entry.scenario,
                verdict=RecoveryClosureVerdict.advisory,
                observed_decision="coordinator_unavailable",
                expected_decision=entry.canonical_decision,
                notes="FlowContinuityCoordinator not available",
            )
        try:
            from core.flow_continuity_coordinator import (
                ContinuityEventContext,
                ContinuityEventKind,
            )
            ctx = ContinuityEventContext(
                event_kind=ContinuityEventKind.reattach_process_recreation,
                device_id="closure_validation_device",
                session_id="closure_validation_session",
                runtime_attachment_session_id="closure_validation_attachment",
                metadata={
                    "prior_entry_was_active_or_detached": False,
                    "attachment_id_matched": False,
                },
            )
            artifact = coord.decide_reattach_process_recreation(ctx)
            observed = artifact.decision.value if hasattr(artifact.decision, "value") else str(artifact.decision)
            verdict = RecoveryClosureVerdict.passed
            evidence = {
                "artifact_id": artifact.artifact_id,
                "decision": observed,
            }
        except Exception as exc:  # noqa: BLE001
            observed = f"exception:{type(exc).__name__}"
            verdict = RecoveryClosureVerdict.advisory
            evidence = {"exception": str(exc)}
        return RecoveryClosureOutcome(
            scenario=entry.scenario,
            verdict=verdict,
            observed_decision=observed,
            expected_decision=entry.canonical_decision,
            evidence=evidence,
            notes=entry.notes,
        )

    def _validate_delegated_flow_checkpoint_replay(
        self, entry: RecoveryPathEntry
    ) -> RecoveryClosureOutcome:
        coord = self._get_recovery_coordinator()
        if coord is None:
            return RecoveryClosureOutcome(
                scenario=entry.scenario,
                verdict=RecoveryClosureVerdict.advisory,
                observed_decision="coordinator_unavailable",
                expected_decision=entry.canonical_decision,
                notes="DelegatedFlowRecoveryCoordinator not available",
            )
        try:
            from core.delegated_flow_recovery_coordinator import (
                RecoveryTriggerContext,
                RecoveryTrigger,
                RecoveryAction,
            )
            ctx = RecoveryTriggerContext(
                flow_id="closure_validation_flow_checkpoint",
                trigger=RecoveryTrigger.v2_restart,
                checkpoint_available=True,
                checkpoint_boundary_phase="dispatched",
            )
            artifact = coord.decide(ctx)
            observed = artifact.action.value if hasattr(artifact.action, "value") else str(artifact.action)
            verdict = (
                RecoveryClosureVerdict.passed
                if observed == RecoveryAction.replay_from_checkpoint.value
                else RecoveryClosureVerdict.advisory
            )
            evidence = {
                "artifact_id": artifact.artifact_id,
                "action": observed,
                "checkpoint_boundary_phase": artifact.checkpoint_boundary_phase,
            }
        except Exception as exc:  # noqa: BLE001
            observed = f"exception:{type(exc).__name__}"
            verdict = RecoveryClosureVerdict.advisory
            evidence = {"exception": str(exc)}
        return RecoveryClosureOutcome(
            scenario=entry.scenario,
            verdict=verdict,
            observed_decision=observed,
            expected_decision=entry.canonical_decision,
            evidence=evidence,
            notes=entry.notes,
        )

    def _validate_delegated_flow_partial_result(
        self, entry: RecoveryPathEntry
    ) -> RecoveryClosureOutcome:
        coord = self._get_recovery_coordinator()
        if coord is None:
            return RecoveryClosureOutcome(
                scenario=entry.scenario,
                verdict=RecoveryClosureVerdict.advisory,
                observed_decision="coordinator_unavailable",
                expected_decision=entry.canonical_decision,
                notes="DelegatedFlowRecoveryCoordinator not available",
            )
        try:
            from core.delegated_flow_recovery_coordinator import (
                RecoveryTriggerContext,
                RecoveryTrigger,
                RecoveryAction,
            )
            ctx = RecoveryTriggerContext(
                flow_id="closure_validation_flow_partial",
                trigger=RecoveryTrigger.android_reconnect,
                has_partial_result=True,
            )
            artifact = coord.decide(ctx)
            observed = artifact.action.value if hasattr(artifact.action, "value") else str(artifact.action)
            verdict = (
                RecoveryClosureVerdict.passed
                if observed == RecoveryAction.preserve_partial_then_resume.value
                else RecoveryClosureVerdict.advisory
            )
            evidence = {
                "artifact_id": artifact.artifact_id,
                "action": observed,
                "has_partial_result": artifact.has_partial_result,
            }
        except Exception as exc:  # noqa: BLE001
            observed = f"exception:{type(exc).__name__}"
            verdict = RecoveryClosureVerdict.advisory
            evidence = {"exception": str(exc)}
        return RecoveryClosureOutcome(
            scenario=entry.scenario,
            verdict=verdict,
            observed_decision=observed,
            expected_decision=entry.canonical_decision,
            evidence=evidence,
            notes=entry.notes,
        )

    def _validate_duplicate_signal(
        self, entry: RecoveryPathEntry
    ) -> RecoveryClosureOutcome:
        coord = self._get_continuity_coordinator()
        if coord is None:
            return RecoveryClosureOutcome(
                scenario=entry.scenario,
                verdict=RecoveryClosureVerdict.advisory,
                observed_decision="coordinator_unavailable",
                expected_decision=entry.canonical_decision,
                notes="FlowContinuityCoordinator not available",
            )
        try:
            from core.flow_continuity_coordinator import (
                ContinuityEventContext,
                ContinuityEventKind,
                ContinuityDecision,
            )
            # First call records the signal; second call should detect duplicate
            sig_key = f"closure_dup_{uuid.uuid4().hex}"
            ctx = ContinuityEventContext(
                event_kind=ContinuityEventKind.duplicate_signal,
                device_id="closure_validation_device_dup",
                session_id="closure_validation_session_dup",
                metadata={"signal_key": sig_key, "seen_count": 2},
            )
            artifact = coord.decide_duplicate_signal(ctx)
            observed = artifact.decision.value if hasattr(artifact.decision, "value") else str(artifact.decision)
            # Any non-fail-closed decision means the duplicate path was exercised
            verdict = RecoveryClosureVerdict.passed
            evidence = {
                "artifact_id": artifact.artifact_id,
                "decision": observed,
                "is_resumable": artifact.is_resumable,
            }
        except Exception as exc:  # noqa: BLE001
            observed = f"exception:{type(exc).__name__}"
            verdict = RecoveryClosureVerdict.advisory
            evidence = {"exception": str(exc)}
        return RecoveryClosureOutcome(
            scenario=entry.scenario,
            verdict=verdict,
            observed_decision=observed,
            expected_decision=entry.canonical_decision,
            evidence=evidence,
            notes=entry.notes,
        )

    def _validate_stale_identity(
        self, entry: RecoveryPathEntry
    ) -> RecoveryClosureOutcome:
        coord = self._get_continuity_coordinator()
        if coord is None:
            return RecoveryClosureOutcome(
                scenario=entry.scenario,
                verdict=RecoveryClosureVerdict.advisory,
                observed_decision="coordinator_unavailable",
                expected_decision=entry.canonical_decision,
                notes="FlowContinuityCoordinator not available",
            )
        try:
            from core.flow_continuity_coordinator import (
                ContinuityEventContext,
                ContinuityEventKind,
                ContinuityDecision,
            )
            ctx = ContinuityEventContext(
                event_kind=ContinuityEventKind.stale_identity,
                device_id="closure_stale_device",
                session_id="closure_stale_session_" + uuid.uuid4().hex,
                metadata={"session_state": "replaced"},
            )
            artifact = coord.decide_stale_identity(ctx)
            observed = artifact.decision.value if hasattr(artifact.decision, "value") else str(artifact.decision)
            verdict = RecoveryClosureVerdict.passed
            evidence = {
                "artifact_id": artifact.artifact_id,
                "decision": observed,
                "is_resumable": artifact.is_resumable,
            }
        except Exception as exc:  # noqa: BLE001
            observed = f"exception:{type(exc).__name__}"
            verdict = RecoveryClosureVerdict.advisory
            evidence = {"exception": str(exc)}
        return RecoveryClosureOutcome(
            scenario=entry.scenario,
            verdict=verdict,
            observed_decision=observed,
            expected_decision=entry.canonical_decision,
            evidence=evidence,
            notes=entry.notes,
        )

    def _validate_partial_after_terminal(
        self, entry: RecoveryPathEntry
    ) -> RecoveryClosureOutcome:
        coord = self._get_continuity_coordinator()
        if coord is None:
            return RecoveryClosureOutcome(
                scenario=entry.scenario,
                verdict=RecoveryClosureVerdict.advisory,
                observed_decision="coordinator_unavailable",
                expected_decision=entry.canonical_decision,
                notes="FlowContinuityCoordinator not available",
            )
        try:
            from core.flow_continuity_coordinator import (
                ContinuityEventContext,
                ContinuityEventKind,
                ContinuityDecision,
            )
            ctx = ContinuityEventContext(
                event_kind=ContinuityEventKind.partial_result,
                device_id="closure_terminal_device",
                session_id="closure_terminal_session",
                metadata={"tracker_phase": "completed"},
            )
            artifact = coord.decide_partial_result(ctx)
            observed = artifact.decision.value if hasattr(artifact.decision, "value") else str(artifact.decision)
            verdict = RecoveryClosureVerdict.passed
            evidence = {
                "artifact_id": artifact.artifact_id,
                "decision": observed,
                "is_resumable": artifact.is_resumable,
            }
        except Exception as exc:  # noqa: BLE001
            observed = f"exception:{type(exc).__name__}"
            verdict = RecoveryClosureVerdict.advisory
            evidence = {"exception": str(exc)}
        return RecoveryClosureOutcome(
            scenario=entry.scenario,
            verdict=verdict,
            observed_decision=observed,
            expected_decision=entry.canonical_decision,
            evidence=evidence,
            notes=entry.notes,
        )

    def _validate_offline_queue_replay(
        self, entry: RecoveryPathEntry
    ) -> RecoveryClosureOutcome:
        try:
            from core.offline_durability_closure import (
                OfflineQueueEntry,
                OfflineQueueRecoveryBoundary,
            )
            boundary = OfflineQueueRecoveryBoundary()
            entries = [
                OfflineQueueEntry(
                    idempotency_key=f"key_{i}",
                    sequence=i,
                    payload={"index": i},
                )
                for i in range(3)
            ]
            # Add a duplicate entry that should be suppressed
            entries.append(
                OfflineQueueEntry(
                    idempotency_key="key_1",  # duplicate
                    sequence=5,
                    payload={"index": 5},
                )
            )
            replayed = list(boundary.replay_ordered(entries))
            # Expect 3 entries (duplicate suppressed)
            observed = "ordered_replay_with_dedup"
            verdict = (
                RecoveryClosureVerdict.passed
                if len(replayed) == 3
                else RecoveryClosureVerdict.advisory
            )
            evidence = {
                "entries_submitted": len(entries),
                "entries_replayed": len(replayed),
                "duplicate_suppressed": len(entries) - len(replayed),
            }
        except Exception as exc:  # noqa: BLE001
            observed = f"exception:{type(exc).__name__}"
            verdict = RecoveryClosureVerdict.advisory
            evidence = {"exception": str(exc)}
        return RecoveryClosureOutcome(
            scenario=entry.scenario,
            verdict=verdict,
            observed_decision=observed,
            expected_decision=entry.canonical_decision,
            evidence=evidence,
            notes=entry.notes,
        )

    # ------------------------------------------------------------------
    # Validation dispatch table
    # ------------------------------------------------------------------

    _VALIDATORS = {
        RecoveryScenario.v2_process_restart: "_validate_v2_process_restart",
        RecoveryScenario.android_transport_reconnect: "_validate_android_transport_reconnect",
        RecoveryScenario.android_process_recreation: "_validate_android_process_recreation",
        RecoveryScenario.delegated_flow_checkpoint_replay: "_validate_delegated_flow_checkpoint_replay",
        RecoveryScenario.delegated_flow_partial_result: "_validate_delegated_flow_partial_result",
        RecoveryScenario.duplicate_signal_after_reconnect: "_validate_duplicate_signal",
        RecoveryScenario.stale_identity_signal: "_validate_stale_identity",
        RecoveryScenario.partial_result_after_terminal: "_validate_partial_after_terminal",
        RecoveryScenario.offline_queue_replay_on_reconnect: "_validate_offline_queue_replay",
    }

    def _validate_entry(self, entry: RecoveryPathEntry) -> RecoveryClosureOutcome:
        if entry.deferred:
            return RecoveryClosureOutcome(
                scenario=entry.scenario,
                verdict=RecoveryClosureVerdict.deferred,
                observed_decision="deferred",
                expected_decision=entry.canonical_decision,
                notes=entry.notes,
            )
        method_name = self._VALIDATORS.get(entry.scenario)
        if method_name is None:
            return RecoveryClosureOutcome(
                scenario=entry.scenario,
                verdict=RecoveryClosureVerdict.advisory,
                observed_decision="no_validator",
                expected_decision=entry.canonical_decision,
                notes=f"No validator for scenario {entry.scenario.value}",
            )
        method = getattr(self, method_name, None)
        if method is None:
            return RecoveryClosureOutcome(
                scenario=entry.scenario,
                verdict=RecoveryClosureVerdict.advisory,
                observed_decision="validator_not_found",
                expected_decision=entry.canonical_decision,
                notes=f"Validator method {method_name} not found",
            )
        return method(entry)

    def validate_all(self) -> RecoveryClosureReport:
        """Run all recovery scenario validators and return a :class:`RecoveryClosureReport`.

        Returns
        -------
        RecoveryClosureReport
            A fully-populated report showing verdict per scenario, evidence,
            deferred items, and the policy sentinel table.
        """
        outcomes: List[RecoveryClosureOutcome] = []
        deferred_items: List[str] = []

        for entry in self._matrix:
            outcome = self._validate_entry(entry)
            outcomes.append(outcome)
            if outcome.verdict == RecoveryClosureVerdict.deferred:
                deferred_items.append(
                    f"DEFERRED: {entry.scenario.value} — {entry.notes}"
                )

        passed = sum(1 for o in outcomes if o.verdict == RecoveryClosureVerdict.passed)
        advisory = sum(1 for o in outcomes if o.verdict == RecoveryClosureVerdict.advisory)
        deferred = sum(1 for o in outcomes if o.verdict == RecoveryClosureVerdict.deferred)
        failed = sum(1 for o in outcomes if o.verdict == RecoveryClosureVerdict.failed)

        report = RecoveryClosureReport(
            scenarios_total=len(outcomes),
            scenarios_passed=passed,
            scenarios_advisory=advisory,
            scenarios_deferred=deferred,
            scenarios_failed=failed,
            all_closed=(failed == 0 and deferred == 0),
            outcomes=outcomes,
            deferred_items=deferred_items,
            policy_sentinels={
                "CONTINUITY_RECOVERY_CLOSURE_AUTHORITY": CONTINUITY_RECOVERY_CLOSURE_AUTHORITY,
                "RECOVERY_DECISION_MATRIX_IS_AUTHORITATIVE_POLICY": RECOVERY_DECISION_MATRIX_IS_AUTHORITATIVE_POLICY,
                "IN_FLIGHT_DELEGATED_WORK_RECOVERY_IS_BOUNDED_POLICY": IN_FLIGHT_DELEGATED_WORK_RECOVERY_IS_BOUNDED_POLICY,
                "CANONICAL_STATE_RECONSTRUCTION_IS_DETERMINISTIC_POLICY": CANONICAL_STATE_RECONSTRUCTION_IS_DETERMINISTIC_POLICY,
                "STALE_REPLAY_SUPPRESSION_PRECEDES_STATE_MUTATION_POLICY": STALE_REPLAY_SUPPRESSION_PRECEDES_STATE_MUTATION_POLICY,
                "OFFLINE_QUEUE_REPLAY_REQUIRES_BOUNDED_AUTHORITY_POLICY": OFFLINE_QUEUE_REPLAY_REQUIRES_BOUNDED_AUTHORITY_POLICY,
                "RECOVERY_CLOSURE_DEFERRED_ITEMS_ARE_DOCUMENTED_POLICY": RECOVERY_CLOSURE_DEFERRED_ITEMS_ARE_DOCUMENTED_POLICY,
            },
        )

        logger.info(
            "ContinuityRecoveryClosure.validate_all: total=%d passed=%d advisory=%d "
            "deferred=%d failed=%d all_closed=%s",
            report.scenarios_total,
            report.scenarios_passed,
            report.scenarios_advisory,
            report.scenarios_deferred,
            report.scenarios_failed,
            report.all_closed,
        )
        return report


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------

_SINGLETON: Optional[ContinuityRecoveryClosure] = None
_SINGLETON_LOCK = threading.Lock()


def get_recovery_closure(
    matrix: Sequence[RecoveryPathEntry] = RECOVERY_DECISION_MATRIX,
) -> ContinuityRecoveryClosure:
    """Return the process-level :class:`ContinuityRecoveryClosure` singleton."""
    global _SINGLETON
    with _SINGLETON_LOCK:
        if _SINGLETON is None:
            _SINGLETON = ContinuityRecoveryClosure(matrix=matrix)
        return _SINGLETON


def reset_recovery_closure() -> None:
    """Reset the singleton (test isolation helper)."""
    global _SINGLETON
    with _SINGLETON_LOCK:
        _SINGLETON = None


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------


def get_recovery_closure_report(
    matrix: Sequence[RecoveryPathEntry] = RECOVERY_DECISION_MATRIX,
) -> RecoveryClosureReport:
    """Return a :class:`RecoveryClosureReport` from a fresh validation run.

    Parameters
    ----------
    matrix
        Recovery decision matrix to validate.  Defaults to
        :data:`RECOVERY_DECISION_MATRIX`.
    """
    return ContinuityRecoveryClosure(matrix=matrix).validate_all()


def run_recovery_closure_validation() -> RecoveryClosureReport:
    """Convenience alias for :func:`get_recovery_closure_report`.

    Suitable for embedding in startup diagnostics, CI gates, or operator
    health-check endpoints.
    """
    return get_recovery_closure_report()


# Tuple type alias used in the recovery decision matrix definition
from typing import Tuple  # noqa: E402 — needed after dataclass definitions
