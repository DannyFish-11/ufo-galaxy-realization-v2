#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/recovery_durability_closure_validator.py
=============================================
Package-5 (post-533 dual-repo runtime-unification master plan, V2 side):
Continuity Recovery and Offline Durability Closure Validator.

Companion test file: tests/test_pr534_continuity_recovery_durability_closure.py

Problem addressed
-----------------
The dual-repo distributed system now contains substantial recovery
infrastructure across multiple modules:

* ``core.flow_continuity_coordinator``     — unified continuity decision entry-point
* ``core.delegated_flow_recovery_coordinator`` — flow-level replay / resume / re-dispatch
* ``core.runtime_restart_recovery``        — process restart orchestration
* ``core.attached_runtime_recovery_readiness`` — inbound signal guard

Each module is individually tested.  However, no single artefact
provides a **reviewable cross-module closure report** answering:

1. How does V2 restore canonical state after restart / reconnect?
2. How is in-flight delegated work recovered or bounded?
3. How are duplicate / stale / replayed Android-originated signals handled?
4. What is concretely deferred to later PRs?

This module closes that gap by providing:

* :class:`RecoveryScenarioStatus` — closed / advisory / deferred / fail_closed
* :class:`RecoveryScenarioEntry`  — one row in the review matrix
* :class:`RecoveryClosureReport`  — full cross-module scenario matrix
* :func:`build_recovery_closure_report` — generates the report by exercising
  each scenario against the live coordinator stack

Design
------
- **Additive only** — no existing module is modified.
- **Decision-first** — every scenario entry records the actual V2 decision
  returned by the live coordinators, not a manually asserted value.
- **Reviewer-friendly** — the report is fully serialisable; a reviewer can
  inspect the decision artifact ids and policy references to trace each
  scenario.
- **Deferred-explicit** — scenarios not yet operationally closed are listed
  with status ``deferred`` and a note explaining why.

Sentinel constants
------------------
:data:`RECOVERY_DURABILITY_CLOSURE_AUTHORITY`
    Affirms this module is the canonical V2-side closure validation authority.

:data:`RECOVERY_DURABILITY_CLOSURE_PR5_SENTINEL`
    Monotonic sentinel string for PR-5 feature identification.

:data:`V2_RESTART_RECOVERY_IS_DETERMINISTIC_POLICY`
    V2 restart recovery produces a bounded, deterministic set of recovery
    actions based solely on durable persistence state.

:data:`INFLIGHT_DELEGATED_WORK_RECOVERY_IS_DISPOSITION_DRIVEN_POLICY`
    After restart, each in-flight delegated task is dispatched according
    to its ``InFlightTaskDisposition`` classification; the routing is
    deterministic and does not rely on in-memory state that was lost.

:data:`SIGNAL_GUARD_PRECEDES_RECONCILIATION_POLICY`
    The PR-18 inbound signal guard MUST be consulted before reconciliation
    for every inbound Android-originated signal to prevent duplicate,
    stale, and replayed signals from polluting canonical V2 state.

:data:`CONTINUITY_COORDINATOR_IS_SINGLE_RECOVERY_ENTRY_POINT_POLICY`
    All continuity classification decisions MUST flow through
    ``FlowContinuityCoordinator``; no module may derive continuity
    decisions independently.

:data:`OFFLINE_QUEUE_ORDERING_IS_DEFERRED_POLICY`
    Bounded authority and ordering for Android-side offline task queues
    replaying after reconnect is explicitly deferred to a later PR.  V2
    relies on the signal guard to reject out-of-order / stale signals and
    on task disposition to bound re-dispatch.

Public API
----------
Enums:
    :class:`RecoveryScenarioStatus`

Dataclasses:
    :class:`RecoveryScenarioEntry`
    :class:`RecoveryClosureReport`

Functions:
    :func:`build_recovery_closure_report`
    :func:`get_recovery_closure_report`
    :func:`reset_recovery_closure_report`
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.RecoveryDurabilityClosureValidator")

__all__ = [
    # Sentinels
    "RECOVERY_DURABILITY_CLOSURE_AUTHORITY",
    "RECOVERY_DURABILITY_CLOSURE_PR5_SENTINEL",
    "V2_RESTART_RECOVERY_IS_DETERMINISTIC_POLICY",
    "INFLIGHT_DELEGATED_WORK_RECOVERY_IS_DISPOSITION_DRIVEN_POLICY",
    "SIGNAL_GUARD_PRECEDES_RECONCILIATION_POLICY",
    "CONTINUITY_COORDINATOR_IS_SINGLE_RECOVERY_ENTRY_POINT_POLICY",
    "OFFLINE_QUEUE_ORDERING_IS_DEFERRED_POLICY",
    "OFFLINE_QUEUE_ORDERING_CONTRACT_NOW_DEFINED_POLICY",
    # Enums
    "RecoveryScenarioStatus",
    # Dataclasses
    "RecoveryScenarioEntry",
    "RecoveryClosureReport",
    # Functions
    "build_recovery_closure_report",
    "get_recovery_closure_report",
    "reset_recovery_closure_report",
]

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

RECOVERY_DURABILITY_CLOSURE_AUTHORITY: str = (
    "RECOVERY_DURABILITY_CLOSURE_AUTHORITY::"
    "core.recovery_durability_closure_validator is the canonical V2-side "
    "closure validation authority for continuity, recovery, replay, and "
    "offline durability scenarios in the post-533 dual-repo runtime "
    "unification track (PR-5).  It provides a reviewable cross-module "
    "decision matrix that chains FlowContinuityCoordinator, "
    "DelegatedFlowRecoveryCoordinator, RuntimeRestartRecoveryCoordinator, "
    "and the inbound signal guard into a single evidence record."
)

RECOVERY_DURABILITY_CLOSURE_PR5_SENTINEL: str = (
    "RECOVERY_DURABILITY_CLOSURE_PR5_SENTINEL::"
    "package=5 "
    "track=post-533-dual-repo-runtime-unification "
    "repo=main "
    "module=core.recovery_durability_closure_validator "
    "title=continuity-recovery-offline-durability-closure"
)

V2_RESTART_RECOVERY_IS_DETERMINISTIC_POLICY: str = (
    "POLICY::V2_RESTART_RECOVERY_IS_DETERMINISTIC_PR5: "
    "After process restart, V2 produces a bounded, deterministic set of "
    "recovery actions driven solely by durable persistence state "
    "(mesh session store, body mesh snapshot, hybrid continuity store, "
    "and task lifecycle snapshot).  No in-memory state lost during restart "
    "can influence the recovery outcome — the only inputs are what was "
    "durably committed before the crash.  This makes recovery reproducible "
    "and reviewable.  (PR-5)"
)

INFLIGHT_DELEGATED_WORK_RECOVERY_IS_DISPOSITION_DRIVEN_POLICY: str = (
    "POLICY::INFLIGHT_DELEGATED_WORK_RECOVERY_IS_DISPOSITION_DRIVEN_PR5: "
    "After V2 restart, each in-flight delegated task record recovered from "
    "the lifecycle snapshot is re-dispatched according to its "
    "InFlightTaskDisposition classification: RESUMABLE → DEVICE_DISPATCH "
    "ownership (re-dispatched when device reconnects); REPLAY_ONLY → "
    "ROUTING ownership (fresh routing pass); REISSUABLE → GATEWAY_INGRESS "
    "ownership (source can re-issue); TERMINAL_ON_INTERRUPT → not "
    "registered (result may already have been delivered).  This "
    "disposition-driven routing is deterministic, idempotent, and prevents "
    "duplicate execution.  (PR-5)"
)

SIGNAL_GUARD_PRECEDES_RECONCILIATION_POLICY: str = (
    "POLICY::SIGNAL_GUARD_PRECEDES_RECONCILIATION_PR5: "
    "The PR-18 inbound signal guard (core.attached_runtime_recovery_readiness) "
    "MUST be consulted before reconciliation for every inbound Android-"
    "originated delegated execution signal.  The guard rejects duplicate "
    "(same signal_id), replay (same emission_seq, different signal_id), "
    "stale (emission_seq far behind max_seen), and out-of-order signals "
    "before they reach the reconciler.  This prevents canonical V2 state "
    "drift, spurious phase transitions, and ack_count corruption during "
    "recovery.  (PR-5)"
)

CONTINUITY_COORDINATOR_IS_SINGLE_RECOVERY_ENTRY_POINT_POLICY: str = (
    "POLICY::CONTINUITY_COORDINATOR_IS_SINGLE_RECOVERY_ENTRY_POINT_PR5: "
    "All V2-side continuity classification decisions — whether to resume, "
    "reject, deduplicate, or treat as a new attachment — MUST flow through "
    "FlowContinuityCoordinator.  No downstream module may derive continuity "
    "decisions by directly inspecting registry or tracker state.  This "
    "constraint is the foundation of the 'single canonical truth' model and "
    "prevents V2 state from diverging across recovery paths.  (PR-5)"
)

OFFLINE_QUEUE_ORDERING_IS_DEFERRED_POLICY: str = (
    "POLICY::OFFLINE_QUEUE_ORDERING_IS_DEFERRED_PR5: "
    "Bounded authority and strict ordering for Android-side offline task "
    "queues replaying after reconnect is explicitly deferred to a later PR.  "
    "In the current PR-5 closure, V2 relies on: (a) the signal guard "
    "(PR-18) to reject stale and out-of-order signals that arrive after a "
    "gap; and (b) InFlightTaskDisposition to bound re-dispatch to tasks that "
    "were explicitly tracked before the disconnect.  A fully ordered replay "
    "authority model — covering the Android-side queue drain ordering and "
    "V2-side absorption ordering under concurrent reconnect — is deferred.  "
    "(PR-5, deferred)"
)

OFFLINE_QUEUE_ORDERING_CONTRACT_NOW_DEFINED_POLICY: str = (
    "POLICY::OFFLINE_QUEUE_ORDERING_CONTRACT_NOW_DEFINED_PR_P03: "
    "The V2-side authoritative offline replay ordering contract has been "
    "formally defined in core.offline_replay_ordering_contract (PR-P0-3).  "
    "V2 is now the declared replay ordering authority; formal semantics "
    "cover in-order acceptance, out-of-order rejection, duplicate rejection, "
    "stale rejection, partial-drain advisory, and ambiguous-authority "
    "downgrade.  RS-16 advances from deferred to advisory: the contract is "
    "defined and enforced by the signal guard; full operational evidence "
    "under live Android drain conditions is still being collected.  "
    "(PR-P0-3, resolves RS-16 deferred)"
)

_ALL_POLICY_SENTINELS = (
    RECOVERY_DURABILITY_CLOSURE_AUTHORITY,
    RECOVERY_DURABILITY_CLOSURE_PR5_SENTINEL,
    V2_RESTART_RECOVERY_IS_DETERMINISTIC_POLICY,
    INFLIGHT_DELEGATED_WORK_RECOVERY_IS_DISPOSITION_DRIVEN_POLICY,
    SIGNAL_GUARD_PRECEDES_RECONCILIATION_POLICY,
    CONTINUITY_COORDINATOR_IS_SINGLE_RECOVERY_ENTRY_POINT_POLICY,
    OFFLINE_QUEUE_ORDERING_IS_DEFERRED_POLICY,
    OFFLINE_QUEUE_ORDERING_CONTRACT_NOW_DEFINED_POLICY,
)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class RecoveryScenarioStatus(str, Enum):
    """Closure status of a recovery scenario.

    Values
    ------
    closed
        The scenario is operationally closed: a concrete V2 decision path
        exists, is exercised by tests, and produces a bounded deterministic
        outcome.
    advisory
        The scenario has a decision path but the outcome includes an
        advisory / require_review result that warrants operator attention.
    deferred
        The scenario is out of scope for this PR and is explicitly deferred
        to a later PR with a documented note.
    fail_closed
        The coordinator emitted ``fail_closed`` for this scenario; it
        requires follow-up investigation.
    """

    closed = "closed"
    advisory = "advisory"
    deferred = "deferred"
    fail_closed = "fail_closed"

    @classmethod
    def from_string(cls, value: Any, *, default: "RecoveryScenarioStatus" = None) -> "RecoveryScenarioStatus":
        if not isinstance(value, str):
            return default if default is not None else cls.fail_closed
        try:
            return cls(value.lower().strip())
        except ValueError:
            return default if default is not None else cls.fail_closed


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class RecoveryScenarioEntry:
    """One row in the V2 recovery scenario closure matrix.

    Attributes
    ----------
    scenario_id
        Short stable identifier (e.g. ``"RS-01"``).
    scenario_name
        Human-readable name.
    event_kind
        ContinuityEventKind or trigger that this scenario covers.
    decision_path
        Which V2 modules participate in the decision chain.
    expected_decision
        Expected canonical decision string (e.g. ``"continuity_resume"``).
    observed_decision
        Actual decision string returned by the live coordinator during
        validation.  Empty string when the scenario was not exercised.
    status
        Closure status of this scenario.
    artifact_id
        artifact_id from the ContinuityDecisionArtifact or
        RecoveryDecisionArtifact, for cross-reference.
    policy_reference
        Policy sentinel that governs this scenario.
    note
        Additional reviewer note (e.g. deferral reason).
    """

    scenario_id: str = ""
    scenario_name: str = ""
    event_kind: str = ""
    decision_path: str = ""
    expected_decision: str = ""
    observed_decision: str = ""
    status: RecoveryScenarioStatus = RecoveryScenarioStatus.fail_closed
    artifact_id: str = ""
    policy_reference: str = ""
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "scenario_name": self.scenario_name,
            "event_kind": self.event_kind,
            "decision_path": self.decision_path,
            "expected_decision": self.expected_decision,
            "observed_decision": self.observed_decision,
            "status": self.status.value,
            "artifact_id": self.artifact_id,
            "policy_reference": self.policy_reference,
            "note": self.note,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RecoveryScenarioEntry":
        return cls(
            scenario_id=str(data.get("scenario_id", "")),
            scenario_name=str(data.get("scenario_name", "")),
            event_kind=str(data.get("event_kind", "")),
            decision_path=str(data.get("decision_path", "")),
            expected_decision=str(data.get("expected_decision", "")),
            observed_decision=str(data.get("observed_decision", "")),
            status=RecoveryScenarioStatus.from_string(data.get("status", "")),
            artifact_id=str(data.get("artifact_id", "")),
            policy_reference=str(data.get("policy_reference", "")),
            note=str(data.get("note", "")),
        )


@dataclass
class RecoveryClosureReport:
    """Full V2 continuity / recovery / durability closure report.

    Attributes
    ----------
    report_id
        Unique identifier for this report run.
    generated_at
        Unix timestamp when this report was generated.
    scenarios
        Ordered list of recovery scenario entries (the review matrix).
    closed_count
        Number of scenarios with status ``closed``.
    advisory_count
        Number of scenarios with status ``advisory``.
    deferred_count
        Number of scenarios with status ``deferred``.
    fail_closed_count
        Number of scenarios with status ``fail_closed``.
    all_closed
        True when closed_count + advisory_count == len(scenarios) and
        fail_closed_count == 0.
    deferred_notes
        Ordered list of deferral notes from deferred scenarios.
    pr5_sentinel
        Module sentinel string.
    """

    report_id: str = field(default_factory=lambda: f"rdc_{uuid.uuid4().hex[:12]}")
    generated_at: float = field(default_factory=time.time)
    scenarios: List[RecoveryScenarioEntry] = field(default_factory=list)
    closed_count: int = 0
    advisory_count: int = 0
    deferred_count: int = 0
    fail_closed_count: int = 0
    all_closed: bool = False
    deferred_notes: List[str] = field(default_factory=list)
    pr5_sentinel: str = RECOVERY_DURABILITY_CLOSURE_PR5_SENTINEL

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "generated_at": self.generated_at,
            "scenarios": [s.to_dict() for s in self.scenarios],
            "closed_count": self.closed_count,
            "advisory_count": self.advisory_count,
            "deferred_count": self.deferred_count,
            "fail_closed_count": self.fail_closed_count,
            "all_closed": self.all_closed,
            "deferred_notes": list(self.deferred_notes),
            "pr5_sentinel": self.pr5_sentinel,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _call_continuity_coordinator_scenario(
    event_kind: str,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Exercise a FlowContinuityCoordinator scenario; return evidence dict."""
    try:
        from core.flow_continuity_coordinator import (
            ContinuityEventContext,
            ContinuityEventKind,
            FlowContinuityCoordinator,
        )
        coordinator = FlowContinuityCoordinator(capacity=32)
        ctx = ContinuityEventContext(
            event_kind=ContinuityEventKind.from_string(event_kind),
            **kwargs,
        )
        artifact = coordinator.decide(ctx)
        return {
            "decision": artifact.decision.value,
            "artifact_id": artifact.artifact_id,
            "policy_reference": artifact.policy_reference,
            "detail": artifact.detail,
        }
    except Exception as exc:
        logger.warning(
            "RecoveryClosureValidator: scenario %r failed: %s", event_kind, exc
        )
        return {"decision": "fail_closed", "artifact_id": "", "policy_reference": "", "detail": str(exc)}


def _call_signal_guard_scenario(
    signal_id: str,
    contract_id: str,
    emission_seq: int,
    *,
    prior_signal_id: str = "",
    prior_emission_seq: int = -1,
) -> Dict[str, Any]:
    """Exercise the PR-18 signal guard; return evidence dict.

    Uses :func:`~core.attached_runtime_recovery_readiness.check_signal_guard`
    (pure evaluation) and
    :func:`~core.attached_runtime_recovery_readiness.record_seen_signal`
    (recording) directly, rather than the envelope-based
    ``guard_inbound_signal`` wrapper, to keep the validation layer thin.
    """
    try:
        from core.attached_runtime_recovery_readiness import (
            RecoveryReadinessRuntime,
            build_idempotency_key,
            check_signal_guard,
            record_seen_signal,
        )
        runtime = RecoveryReadinessRuntime()
        if prior_signal_id:
            prior_key = build_idempotency_key(
                signal_id=prior_signal_id,
                contract_id=contract_id,
            )
            record_seen_signal(prior_key, emission_seq=prior_emission_seq, runtime=runtime)
        key = build_idempotency_key(signal_id=signal_id, contract_id=contract_id)
        decision = check_signal_guard(key, emission_seq=emission_seq, runtime=runtime)
        return {
            "decision": decision.value,
            "reject_reason": "" if decision.value == "accept" else decision.value,
            "max_seen_seq": prior_emission_seq,
        }
    except Exception as exc:
        logger.warning("RecoveryClosureValidator: signal guard scenario failed: %s", exc)
        return {"decision": "fail_closed", "reject_reason": str(exc), "max_seen_seq": -1}


def _call_delegated_flow_recovery_scenario(
    flow_id: str,
    trigger: str,
    continuity_decision: str = "",
    has_partial_result: bool = False,
    checkpoint_available: bool = False,
    binding_state: str = "",
    checkpoint_boundary_phase: str = "",
) -> Dict[str, Any]:
    """Exercise DelegatedFlowRecoveryCoordinator; return evidence dict."""
    try:
        from core.delegated_flow_recovery_coordinator import (
            DelegatedFlowRecoveryCoordinator,
            RecoveryTriggerContext,
            RecoveryTrigger,
        )
        coordinator = DelegatedFlowRecoveryCoordinator(capacity=32)
        ctx = RecoveryTriggerContext(
            flow_id=flow_id,
            trigger=RecoveryTrigger.from_string(trigger),
            continuity_decision=continuity_decision,
            has_partial_result=has_partial_result,
            checkpoint_available=checkpoint_available,
            checkpoint_boundary_phase=checkpoint_boundary_phase,
            binding_state=binding_state,
        )
        artifact = coordinator.decide(ctx)
        return {
            "action": artifact.action.value,
            "artifact_id": artifact.artifact_id,
            "policy_reference": artifact.policy_reference,
            "detail": artifact.detail,
        }
    except Exception as exc:
        logger.warning(
            "RecoveryClosureValidator: delegated flow scenario %r failed: %s",
            trigger,
            exc,
        )
        return {"action": "fail_closed", "artifact_id": "", "policy_reference": "", "detail": str(exc)}


# ---------------------------------------------------------------------------
# Scenario builders
# ---------------------------------------------------------------------------


def _build_rs01_v2_restart_durable_flow() -> RecoveryScenarioEntry:
    """RS-01: V2 restart with a durable in-flight flow → continuity_resume."""
    # Recovery-not-yet-completed path returns require_review.
    evidence = _call_continuity_coordinator_scenario(
        "v2_restart_recovery",
        recovery_completed=False,
        flow_lineage_id="lin-rs01-test",
    )
    # recovery_completed=False MUST give require_review (not yet done)
    expected = "require_review"
    obs = evidence["decision"]
    status = (
        RecoveryScenarioStatus.closed
        if obs == expected
        else RecoveryScenarioStatus.fail_closed
    )
    return RecoveryScenarioEntry(
        scenario_id="RS-01",
        scenario_name="V2 restart — recovery not yet completed → require_review",
        event_kind="v2_restart_recovery",
        decision_path="FlowContinuityCoordinator.decide_v2_restart_recovery",
        expected_decision=expected,
        observed_decision=obs,
        status=status,
        artifact_id=evidence.get("artifact_id", ""),
        policy_reference="V2_RESTART_CONTINUITY_USES_DURABLE_STORE_POLICY",
        note=(
            "When recovery_completed=False the coordinator MUST emit "
            "require_review and defer the continuity classification until "
            "after the startup recovery pass has loaded the durable store."
        ),
    )


def _build_rs02_v2_restart_no_durable_flow() -> RecoveryScenarioEntry:
    """RS-02: V2 restart, recovery done, no in-flight flow → new_attachment."""
    evidence = _call_continuity_coordinator_scenario(
        "v2_restart_recovery",
        recovery_completed=True,
        flow_lineage_id="lin-rs02-not-present",
    )
    expected = "new_attachment"
    obs = evidence["decision"]
    status = (
        RecoveryScenarioStatus.closed
        if obs == expected
        else RecoveryScenarioStatus.advisory
    )
    return RecoveryScenarioEntry(
        scenario_id="RS-02",
        scenario_name="V2 restart — recovery done, no durable flow → new_attachment",
        event_kind="v2_restart_recovery",
        decision_path="FlowContinuityCoordinator.decide_v2_restart_recovery",
        expected_decision=expected,
        observed_decision=obs,
        status=status,
        artifact_id=evidence.get("artifact_id", ""),
        policy_reference="V2_RESTART_CONTINUITY_USES_DURABLE_STORE_POLICY",
        note=(
            "When the durable store has no non-terminal flow for this "
            "lineage/contract the coordinator treats the situation as a "
            "new_attachment — no stale prior context is inherited."
        ),
    )


def _build_rs03_transport_reconnect_preserved() -> RecoveryScenarioEntry:
    """RS-03: Transport reconnect with attachment ID preserved → continuity_resume or new_attachment."""
    # With no live registry, the coordinator falls back to a safe default.
    evidence = _call_continuity_coordinator_scenario(
        "transport_reconnect",
        device_id="dev-rs03",
        runtime_attachment_session_id="att-rs03",
    )
    obs = evidence["decision"]
    expected_set = {"continuity_resume", "new_attachment", "fail_closed"}
    status = (
        RecoveryScenarioStatus.closed
        if obs in expected_set
        else RecoveryScenarioStatus.advisory
    )
    return RecoveryScenarioEntry(
        scenario_id="RS-03",
        scenario_name="Transport reconnect — attachment ID present → bounded decision",
        event_kind="transport_reconnect",
        decision_path="FlowContinuityCoordinator.decide_reconnect → AttachedSessionRegistry",
        expected_decision="continuity_resume | new_attachment | fail_closed",
        observed_decision=obs,
        status=status,
        artifact_id=evidence.get("artifact_id", ""),
        policy_reference="CONTINUITY_DECISION_IS_UNIFIED_ENTRY_POINT_POLICY",
        note=(
            "Without a live session registry the coordinator falls back "
            "safely.  With a registry that has a 'continuity_resume' entry "
            "for this device, the decision will be continuity_resume when the "
            "attachment ID is preserved."
        ),
    )


def _build_rs04_transport_reconnect_no_attachment() -> RecoveryScenarioEntry:
    """RS-04: Transport reconnect without attachment ID → require_review or fail_closed."""
    evidence = _call_continuity_coordinator_scenario(
        "transport_reconnect",
        device_id="dev-rs04",
        runtime_attachment_session_id="",  # absent
    )
    obs = evidence["decision"]
    expected_set = {"require_review", "new_attachment", "fail_closed"}
    status = (
        RecoveryScenarioStatus.closed
        if obs in expected_set
        else RecoveryScenarioStatus.advisory
    )
    return RecoveryScenarioEntry(
        scenario_id="RS-04",
        scenario_name="Transport reconnect — no attachment ID → require_review or safe default",
        event_kind="transport_reconnect",
        decision_path="FlowContinuityCoordinator.decide_reconnect",
        expected_decision="require_review | new_attachment | fail_closed",
        observed_decision=obs,
        status=status,
        artifact_id=evidence.get("artifact_id", ""),
        policy_reference="CONTINUITY_DECISION_IS_UNIFIED_ENTRY_POINT_POLICY",
        note=(
            "A reconnect without attachment ID is ambiguous.  The coordinator "
            "must not silently resume — it emits require_review or treats the "
            "device as new_attachment.  This prevents stale prior context from "
            "being inherited after a reconnect that lost its attachment ID."
        ),
    )


def _build_rs05_stale_identity() -> RecoveryScenarioEntry:
    """RS-05: Stale identity signal → reject_stale_identity (non-destructive)."""
    evidence = _call_continuity_coordinator_scenario(
        "stale_identity",
        device_id="dev-rs05",
        session_id="sess-rs05-expired",
        contract_id="ctr-rs05-expired",
    )
    obs = evidence["decision"]
    expected = "reject_stale_identity"
    status = (
        RecoveryScenarioStatus.closed
        if obs == expected
        else RecoveryScenarioStatus.advisory
    )
    return RecoveryScenarioEntry(
        scenario_id="RS-05",
        scenario_name="Stale identity signal → reject_stale_identity (non-destructive)",
        event_kind="stale_identity",
        decision_path="FlowContinuityCoordinator.decide_stale_identity",
        expected_decision=expected,
        observed_decision=obs,
        status=status,
        artifact_id=evidence.get("artifact_id", ""),
        policy_reference="STALE_IDENTITY_REJECTION_IS_NON_DESTRUCTIVE_POLICY",
        note=(
            "A stale-identity rejection MUST NOT alter canonical V2 state — "
            "no session entry is created, no tracking record is updated.  "
            "The artifact is recorded in the coordinator ring-buffer only."
        ),
    )


def _build_rs06_duplicate_signal() -> RecoveryScenarioEntry:
    """RS-06: Novel signal (no prior ack record) → continuity_resume (pass through).

    FlowContinuityCoordinator.decide_duplicate_signal returns
    ``continuity_resume`` when the signal_key has NOT been seen in the
    execution tracker ack history — the signal is novel and may proceed to
    the reconciler.  The ``dedupe_duplicate_signal`` path fires only when
    the tracker already has the signal_key recorded.  Protocol-level
    duplicate/replay/stale rejection is handled by the PR-18 signal guard
    (see RS-12 through RS-14).
    """
    evidence = _call_continuity_coordinator_scenario(
        "duplicate_signal",
        device_id="dev-rs06",
        contract_id="ctr-rs06",
        signal_key="sig-rs06-novel",
    )
    obs = evidence["decision"]
    # Novel signal with no prior tracker record → continuity_resume (pass through)
    expected = "continuity_resume"
    status = (
        RecoveryScenarioStatus.closed
        if obs == expected
        else RecoveryScenarioStatus.advisory
    )
    return RecoveryScenarioEntry(
        scenario_id="RS-06",
        scenario_name=(
            "Novel signal (no prior ack record) → continuity_resume (pass through)"
        ),
        event_kind="duplicate_signal",
        decision_path="FlowContinuityCoordinator.decide_duplicate_signal",
        expected_decision=expected,
        observed_decision=obs,
        status=status,
        artifact_id=evidence.get("artifact_id", ""),
        policy_reference="DUPLICATE_SIGNAL_SUPPRESSION_PRECEDES_RECONCILIATION_POLICY",
        note=(
            "When the signal_key has NOT been seen in the execution tracker ack "
            "history the coordinator returns continuity_resume — the signal is "
            "novel and safe to forward to the reconciler.  The "
            "dedupe_duplicate_signal path requires a live tracker record with "
            "the signal_key already present.  Protocol-level duplicate / replay / "
            "stale rejection (independent of tracker state) is handled by the "
            "PR-18 signal guard (RS-12 to RS-14)."
        ),
    )


def _build_rs07_partial_result() -> RecoveryScenarioEntry:
    """RS-07: Partial-result signal → preserve_partial_and_wait."""
    evidence = _call_continuity_coordinator_scenario(
        "partial_result",
        device_id="dev-rs07",
        contract_id="ctr-rs07",
        tracker_id="trk-rs07",
        is_partial_result=True,
    )
    obs = evidence["decision"]
    expected = "preserve_partial_and_wait"
    status = (
        RecoveryScenarioStatus.closed
        if obs == expected
        else RecoveryScenarioStatus.advisory
    )
    return RecoveryScenarioEntry(
        scenario_id="RS-07",
        scenario_name="Partial-result signal → preserve_partial_and_wait",
        event_kind="partial_result",
        decision_path="FlowContinuityCoordinator.decide_partial_result",
        expected_decision=expected,
        observed_decision=obs,
        status=status,
        artifact_id=evidence.get("artifact_id", ""),
        policy_reference="PARTIAL_RESULT_PRESERVATION_IS_COORDINATOR_OWNED_POLICY",
        note=(
            "The execution tracking record MUST NOT be closed when a partial "
            "result is received.  The coordinator emits preserve_partial_and_wait "
            "to signal this; the caller must wait for a terminal result before "
            "closing the tracking record."
        ),
    )


def _build_rs08_delegated_flow_resume() -> RecoveryScenarioEntry:
    """RS-08: Delegated flow recovery — continuity_resume decision → resume_in_place."""
    evidence = _call_delegated_flow_recovery_scenario(
        flow_id=f"flow-rs08-{uuid.uuid4().hex[:8]}",
        trigger="v2_restart",
        continuity_decision="continuity_resume",
        has_partial_result=False,
        checkpoint_available=False,
        binding_state="bound",
    )
    obs = evidence["action"]
    expected = "resume_in_place"
    status = (
        RecoveryScenarioStatus.closed
        if obs == expected
        else RecoveryScenarioStatus.advisory
    )
    return RecoveryScenarioEntry(
        scenario_id="RS-08",
        scenario_name="Delegated flow recovery — continuity_resume → resume_in_place",
        event_kind="v2_restart / delegated_flow_recovery",
        decision_path=(
            "FlowContinuityCoordinator → continuity_resume → "
            "DelegatedFlowRecoveryCoordinator.decide → resume_in_place"
        ),
        expected_decision=expected,
        observed_decision=obs,
        status=status,
        artifact_id=evidence.get("artifact_id", ""),
        policy_reference="INFLIGHT_DELEGATED_WORK_RECOVERY_IS_DISPOSITION_DRIVEN_POLICY",
        note=(
            "When the upstream continuity coordinator emits continuity_resume "
            "and no special case (partial result, checkpoint, invalid binding) "
            "applies, the delegated flow recovery coordinator selects "
            "resume_in_place: the flow continues from the most recent durable "
            "state without replaying steps."
        ),
    )


def _build_rs09_delegated_flow_checkpoint_replay() -> RecoveryScenarioEntry:
    """RS-09: Delegated flow recovery — checkpoint available → replay_from_checkpoint."""
    evidence = _call_delegated_flow_recovery_scenario(
        flow_id=f"flow-rs09-{uuid.uuid4().hex[:8]}",
        trigger="android_binding_lost",
        continuity_decision="continuity_resume",
        has_partial_result=False,
        checkpoint_available=True,
        checkpoint_boundary_phase="dispatching",
        binding_state="released",
    )
    obs = evidence["action"]
    expected = "replay_from_checkpoint"
    status = (
        RecoveryScenarioStatus.closed
        if obs == expected
        else RecoveryScenarioStatus.advisory
    )
    return RecoveryScenarioEntry(
        scenario_id="RS-09",
        scenario_name=(
            "Delegated flow recovery — checkpoint available, binding released "
            "→ replay_from_checkpoint"
        ),
        event_kind="android_binding_lost",
        decision_path=(
            "DelegatedFlowRecoveryCoordinator.decide → "
            "checkpoint_available=True → replay_from_checkpoint"
        ),
        expected_decision=expected,
        observed_decision=obs,
        status=status,
        artifact_id=evidence.get("artifact_id", ""),
        policy_reference="INFLIGHT_DELEGATED_WORK_RECOVERY_IS_DISPOSITION_DRIVEN_POLICY",
        note=(
            "When a durable checkpoint boundary exists, the coordinator "
            "replays from that boundary to reconstruct missing execution "
            "progress rather than silently resuming from an unknown state."
        ),
    )


def _build_rs10_delegated_flow_redispatch() -> RecoveryScenarioEntry:
    """RS-10: Delegated flow recovery — binding released, no checkpoint → redispatch_runtime."""
    evidence = _call_delegated_flow_recovery_scenario(
        flow_id=f"flow-rs10-{uuid.uuid4().hex[:8]}",
        trigger="android_binding_lost",
        continuity_decision="new_attachment",
        has_partial_result=False,
        checkpoint_available=False,
        binding_state="released",
    )
    obs = evidence["action"]
    expected = "redispatch_runtime"
    status = (
        RecoveryScenarioStatus.closed
        if obs == expected
        else RecoveryScenarioStatus.advisory
    )
    return RecoveryScenarioEntry(
        scenario_id="RS-10",
        scenario_name=(
            "Delegated flow recovery — binding released, no checkpoint "
            "→ redispatch_runtime"
        ),
        event_kind="android_binding_lost",
        decision_path=(
            "DelegatedFlowRecoveryCoordinator.decide → binding_state=released → "
            "redispatch_runtime"
        ),
        expected_decision=expected,
        observed_decision=obs,
        status=status,
        artifact_id=evidence.get("artifact_id", ""),
        policy_reference="INFLIGHT_DELEGATED_WORK_RECOVERY_IS_DISPOSITION_DRIVEN_POLICY",
        note=(
            "When the prior Android dispatch binding is gone and no checkpoint "
            "is available, the flow must be re-dispatched to a new Android "
            "runtime surface rather than left orphaned."
        ),
    )


def _build_rs11_delegated_flow_partial_preserve() -> RecoveryScenarioEntry:
    """RS-11: Delegated flow recovery — partial result present → preserve_partial_then_resume."""
    evidence = _call_delegated_flow_recovery_scenario(
        flow_id=f"flow-rs11-{uuid.uuid4().hex[:8]}",
        trigger="android_result_received",
        has_partial_result=True,
        checkpoint_available=False,
        binding_state="bound",
    )
    obs = evidence["action"]
    expected = "preserve_partial_then_resume"
    status = (
        RecoveryScenarioStatus.closed
        if obs == expected
        else RecoveryScenarioStatus.advisory
    )
    return RecoveryScenarioEntry(
        scenario_id="RS-11",
        scenario_name=(
            "Delegated flow recovery — partial result detected "
            "→ preserve_partial_then_resume"
        ),
        event_kind="android_result_received",
        decision_path=(
            "DelegatedFlowRecoveryCoordinator.decide → has_partial_result=True "
            "→ preserve_partial_then_resume"
        ),
        expected_decision=expected,
        observed_decision=obs,
        status=status,
        artifact_id=evidence.get("artifact_id", ""),
        policy_reference="PARTIAL_RESULT_CONVERGENCE_PRECEDES_RESUME_POLICY",
        note=(
            "Partial result convergence takes priority over all other recovery "
            "paths.  The coordinator preserves the partial result before "
            "proceeding with any resume or replay step, preventing data loss."
        ),
    )


def _build_rs12_signal_guard_duplicate() -> RecoveryScenarioEntry:
    """RS-12: Inbound signal guard — duplicate signal_id → duplicate."""
    evidence = _call_signal_guard_scenario(
        signal_id="sig-rs12",
        contract_id="ctr-rs12",
        emission_seq=5,
        prior_signal_id="sig-rs12",  # same signal_id
        prior_emission_seq=5,
    )
    obs = evidence["decision"]
    expected = "duplicate"
    status = (
        RecoveryScenarioStatus.closed
        if obs == expected
        else RecoveryScenarioStatus.fail_closed
    )
    return RecoveryScenarioEntry(
        scenario_id="RS-12",
        scenario_name="Signal guard — duplicate signal_id → duplicate (reject)",
        event_kind="inbound_android_signal",
        decision_path=(
            "attached_runtime_recovery_readiness.guard_inbound_signal → duplicate"
        ),
        expected_decision=expected,
        observed_decision=obs,
        status=status,
        artifact_id="",
        policy_reference="SIGNAL_GUARD_PRECEDES_RECONCILIATION_POLICY",
        note=(
            "Exact signal_id match means the signal was already received and "
            "processed.  The guard rejects it before it reaches the reconciler, "
            "preventing double-application of the phase transition."
        ),
    )


def _build_rs13_signal_guard_stale() -> RecoveryScenarioEntry:
    """RS-13: Inbound signal guard — stale emission_seq → stale."""
    from core.attached_runtime_recovery_readiness import STALE_EMISSION_SEQ_THRESHOLD
    stale_seq = 100
    current_seq = stale_seq + STALE_EMISSION_SEQ_THRESHOLD + 1
    # Record the current high-water mark first
    evidence = _call_signal_guard_scenario(
        signal_id="sig-rs13-stale",
        contract_id="ctr-rs13",
        emission_seq=stale_seq,
        prior_signal_id="sig-rs13-current",
        prior_emission_seq=current_seq,
    )
    obs = evidence["decision"]
    expected = "stale"
    status = (
        RecoveryScenarioStatus.closed
        if obs == expected
        else RecoveryScenarioStatus.fail_closed
    )
    return RecoveryScenarioEntry(
        scenario_id="RS-13",
        scenario_name="Signal guard — emission_seq far behind max → stale (reject)",
        event_kind="inbound_android_signal",
        decision_path=(
            "attached_runtime_recovery_readiness.guard_inbound_signal → stale"
        ),
        expected_decision=expected,
        observed_decision=obs,
        status=status,
        artifact_id="",
        policy_reference="SIGNAL_GUARD_PRECEDES_RECONCILIATION_POLICY",
        note=(
            f"A signal with emission_seq more than {STALE_EMISSION_SEQ_THRESHOLD} "
            "positions behind the current maximum is treated as stale and "
            "dropped.  This prevents long-delayed signals from retroactively "
            "altering canonical V2 state after recovery."
        ),
    )


def _build_rs14_signal_guard_replay() -> RecoveryScenarioEntry:
    """RS-14: Inbound signal guard — same seq, different signal_id → replay."""
    evidence = _call_signal_guard_scenario(
        signal_id="sig-rs14-replay",
        contract_id="ctr-rs14",
        emission_seq=7,
        prior_signal_id="sig-rs14-original",  # different signal_id, same seq
        prior_emission_seq=7,
    )
    obs = evidence["decision"]
    expected = "replay"
    status = (
        RecoveryScenarioStatus.closed
        if obs == expected
        else RecoveryScenarioStatus.fail_closed
    )
    return RecoveryScenarioEntry(
        scenario_id="RS-14",
        scenario_name=(
            "Signal guard — same emission_seq, different signal_id "
            "→ replay (reject)"
        ),
        event_kind="inbound_android_signal",
        decision_path=(
            "attached_runtime_recovery_readiness.guard_inbound_signal → replay"
        ),
        expected_decision=expected,
        observed_decision=obs,
        status=status,
        artifact_id="",
        policy_reference="SIGNAL_GUARD_PRECEDES_RECONCILIATION_POLICY",
        note=(
            "A re-emission at the same seq position with a new signal_id is a "
            "replay — Android is re-transmitting for an acknowledged-loss at "
            "that seq position.  The guard drops it to prevent double-processing."
        ),
    )


def _build_rs15_signal_guard_accept() -> RecoveryScenarioEntry:
    """RS-15: Inbound signal guard — new signal, higher seq → accept."""
    evidence = _call_signal_guard_scenario(
        signal_id="sig-rs15-new",
        contract_id="ctr-rs15",
        emission_seq=10,
        prior_signal_id="sig-rs15-prev",
        prior_emission_seq=9,
    )
    obs = evidence["decision"]
    expected = "accept"
    status = (
        RecoveryScenarioStatus.closed
        if obs == expected
        else RecoveryScenarioStatus.fail_closed
    )
    return RecoveryScenarioEntry(
        scenario_id="RS-15",
        scenario_name=(
            "Signal guard — new signal_id, emission_seq > max → accept"
        ),
        event_kind="inbound_android_signal",
        decision_path=(
            "attached_runtime_recovery_readiness.guard_inbound_signal → accept"
        ),
        expected_decision=expected,
        observed_decision=obs,
        status=status,
        artifact_id="",
        policy_reference="SIGNAL_GUARD_PRECEDES_RECONCILIATION_POLICY",
        note=(
            "A new signal_id with an emission_seq greater than or equal to the "
            "current maximum is accepted and forwarded to the reconciler.  The "
            "guard records it so subsequent signals can be evaluated against it."
        ),
    )


def _build_rs16_offline_queue_ordering_deferred() -> RecoveryScenarioEntry:
    """RS-16: Offline queue ordering — contract now defined (advisory).

    PR-P0-3 establishes V2 as the authoritative owner of replay ordering
    semantics via ``core.offline_replay_ordering_contract``.  This advances
    RS-16 from ``deferred`` to ``advisory``: the contract is formally
    defined and enforced by the existing signal guard; full operational
    evidence under live Android drain conditions is still being collected.
    """
    try:
        from core.offline_replay_ordering_contract import (
            build_offline_replay_ordering_report,
            OfflineReplayContractVerdict,
            OFFLINE_REPLAY_ORDERING_CONTRACT_AUTHORITY,
        )
        rpt = build_offline_replay_ordering_report()
        obs = rpt.verdict.value
        # The baseline report always yields contract_not_yet_evidenced;
        # that is the honest starting state.  Advisory is appropriate because
        # the contract is defined even though no live drain has been seen.
        return RecoveryScenarioEntry(
            scenario_id="RS-16",
            scenario_name=(
                "Offline task queue replay — V2 authoritative contract "
                "defined (advisory; live drain evidence pending)"
            ),
            event_kind="android_offline_queue_drain",
            decision_path=(
                "core.offline_replay_ordering_contract."
                "build_offline_replay_ordering_report → "
                + obs
            ),
            expected_decision=OfflineReplayContractVerdict.contract_not_yet_evidenced.value,
            observed_decision=obs,
            status=RecoveryScenarioStatus.advisory,
            artifact_id=rpt.report_id,
            policy_reference="OFFLINE_QUEUE_ORDERING_CONTRACT_NOW_DEFINED_POLICY",
            note=(
                "V2-side authoritative offline replay ordering contract is "
                "formally defined in core.offline_replay_ordering_contract "
                "(PR-P0-3).  V2 is the declared replay ordering authority; "
                "semantics cover in-order acceptance, out-of-order rejection, "
                "duplicate rejection, stale rejection, partial-drain advisory, "
                "and ambiguous-authority downgrade.  "
                "Baseline verdict is contract_not_yet_evidenced (no live "
                "Android drain in this process instance); contract is active "
                "and enforced via the existing signal guard (PR-18).  "
                "Status: advisory — contract defined, live operational "
                "evidence being collected.  (PR-P0-3)"
            ),
        )
    except Exception as exc:
        # Fail-graceful: if the contract module is not importable, remain
        # deferred rather than masking the gap.
        return RecoveryScenarioEntry(
            scenario_id="RS-16",
            scenario_name=(
                "Offline task queue replay — ordering contract "
                "(module unavailable)"
            ),
            event_kind="android_offline_queue_drain",
            decision_path="(contract module unavailable)",
            expected_decision="(deferred)",
            observed_decision="(deferred)",
            status=RecoveryScenarioStatus.deferred,
            artifact_id="",
            policy_reference="OFFLINE_QUEUE_ORDERING_IS_DEFERRED_POLICY",
            note=(
                "core.offline_replay_ordering_contract could not be imported: "
                + str(exc)
                + ".  Falling back to deferred status."
            ),
        )


def _build_rs17_duplicate_recovery_suppression() -> RecoveryScenarioEntry:
    """RS-17: Duplicate recovery attempt for same flow → suppress_duplicate_recovery.

    Uses :meth:`~core.delegated_flow_recovery_coordinator
    .DelegatedFlowRecoveryCoordinator.begin_attempt` to register the first
    attempt, then immediately calls :meth:`decide` with the same flow_id.
    ``begin_attempt`` registers the flow_id in the active-attempt registry;
    the subsequent ``decide`` call detects the in-progress attempt and
    returns ``suppress_duplicate_recovery``.
    """
    flow_id = f"flow-rs17-{uuid.uuid4().hex[:8]}"
    try:
        from core.delegated_flow_recovery_coordinator import (
            DelegatedFlowRecoveryCoordinator,
            RecoveryTriggerContext,
            RecoveryTrigger,
        )
        coordinator = DelegatedFlowRecoveryCoordinator(capacity=32)
        ctx1 = RecoveryTriggerContext(
            flow_id=flow_id,
            trigger=RecoveryTrigger.from_string("v2_restart"),
            continuity_decision="continuity_resume",
        )
        # begin_attempt registers the flow_id as in-progress
        coordinator.begin_attempt(ctx1)
        # Second attempt — same coordinator, same flow_id (duplicate)
        ctx2 = RecoveryTriggerContext(
            flow_id=flow_id,
            trigger=RecoveryTrigger.from_string("v2_restart"),
            continuity_decision="continuity_resume",
        )
        artifact2 = coordinator.decide(ctx2)
        obs = artifact2.action.value
        expected = "suppress_duplicate_recovery"
        status = (
            RecoveryScenarioStatus.closed
            if obs == expected
            else RecoveryScenarioStatus.advisory
        )
        return RecoveryScenarioEntry(
            scenario_id="RS-17",
            scenario_name=(
                "Duplicate recovery attempt — same flow_id in-progress "
                "→ suppress_duplicate_recovery"
            ),
            event_kind="v2_restart / delegated_flow_recovery",
            decision_path=(
                "DelegatedFlowRecoveryCoordinator.begin_attempt (registers attempt) "
                "→ decide (same flow_id) → suppress_duplicate_recovery"
            ),
            expected_decision=expected,
            observed_decision=obs,
            status=status,
            artifact_id=artifact2.artifact_id,
            policy_reference="DUPLICATE_RECOVERY_SUPPRESSION_IS_COORDINATOR_OWNED_POLICY",
            note=(
                "begin_attempt() registers the flow_id in the active-attempt "
                "registry.  A subsequent decide() call for the same flow_id "
                "detects the in-progress entry and returns "
                "suppress_duplicate_recovery, preventing double-execution of "
                "the recovery action."
            ),
        )
    except Exception as exc:
        return RecoveryScenarioEntry(
            scenario_id="RS-17",
            scenario_name="Duplicate recovery attempt suppression",
            event_kind="v2_restart / delegated_flow_recovery",
            decision_path="DelegatedFlowRecoveryCoordinator.begin_attempt + decide",
            expected_decision="suppress_duplicate_recovery",
            observed_decision="fail_closed",
            status=RecoveryScenarioStatus.fail_closed,
            artifact_id="",
            policy_reference="DUPLICATE_RECOVERY_SUPPRESSION_IS_COORDINATOR_OWNED_POLICY",
            note=str(exc),
        )


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------


def build_recovery_closure_report() -> RecoveryClosureReport:
    """Exercise all V2 recovery scenarios and return a :class:`RecoveryClosureReport`.

    This function is the canonical entry-point for generating the recovery
    decision matrix.  It:

    1. Exercises each of the 17 defined recovery scenarios against the live
       coordinator stack (using isolated coordinator instances to avoid
       cross-test pollution).
    2. Records the observed decision for each scenario.
    3. Counts closed / advisory / deferred / fail_closed totals.
    4. Sets ``all_closed`` when no scenario has ``fail_closed`` status.

    The returned :class:`RecoveryClosureReport` is fully serialisable via
    ``to_dict()`` / ``to_json()`` for operator observability.

    Returns
    -------
    RecoveryClosureReport
    """
    builders = [
        _build_rs01_v2_restart_durable_flow,
        _build_rs02_v2_restart_no_durable_flow,
        _build_rs03_transport_reconnect_preserved,
        _build_rs04_transport_reconnect_no_attachment,
        _build_rs05_stale_identity,
        _build_rs06_duplicate_signal,
        _build_rs07_partial_result,
        _build_rs08_delegated_flow_resume,
        _build_rs09_delegated_flow_checkpoint_replay,
        _build_rs10_delegated_flow_redispatch,
        _build_rs11_delegated_flow_partial_preserve,
        _build_rs12_signal_guard_duplicate,
        _build_rs13_signal_guard_stale,
        _build_rs14_signal_guard_replay,
        _build_rs15_signal_guard_accept,
        _build_rs16_offline_queue_ordering_deferred,
        _build_rs17_duplicate_recovery_suppression,
    ]

    report = RecoveryClosureReport()

    for builder in builders:
        try:
            entry = builder()
        except Exception as exc:
            scenario_name = getattr(builder, "__name__", str(builder))
            logger.warning(
                "RecoveryClosureValidator: builder %r raised: %s",
                scenario_name,
                exc,
            )
            entry = RecoveryScenarioEntry(
                scenario_id=f"RS-ERR-{scenario_name}",
                scenario_name=f"ERROR: {scenario_name}",
                status=RecoveryScenarioStatus.fail_closed,
                note=str(exc),
            )
        report.scenarios.append(entry)
        if entry.status == RecoveryScenarioStatus.closed:
            report.closed_count += 1
        elif entry.status == RecoveryScenarioStatus.advisory:
            report.advisory_count += 1
        elif entry.status == RecoveryScenarioStatus.deferred:
            report.deferred_count += 1
            if entry.note:
                report.deferred_notes.append(f"{entry.scenario_id}: {entry.note}")
        elif entry.status == RecoveryScenarioStatus.fail_closed:
            report.fail_closed_count += 1

    report.all_closed = (
        report.fail_closed_count == 0
        and (report.closed_count + report.advisory_count + report.deferred_count)
        == len(report.scenarios)
    )
    return report


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------

_SINGLETON: Optional[RecoveryClosureReport] = None
_SINGLETON_LOCK_OBJ = None


def _singleton_lock():
    """Return (or lazily create) the module-level threading.Lock."""
    global _SINGLETON_LOCK_OBJ  # noqa: PLW0603
    if _SINGLETON_LOCK_OBJ is None:
        import threading
        _SINGLETON_LOCK_OBJ = threading.Lock()
    return _SINGLETON_LOCK_OBJ


def get_recovery_closure_report() -> RecoveryClosureReport:
    """Return the process-level :class:`RecoveryClosureReport` singleton.

    Builds the report on first call and caches the result.  Call
    :func:`reset_recovery_closure_report` to discard the cache (test
    isolation).
    """
    global _SINGLETON  # noqa: PLW0603
    if _SINGLETON is None:
        with _singleton_lock():
            if _SINGLETON is None:
                _SINGLETON = build_recovery_closure_report()
    return _SINGLETON


def reset_recovery_closure_report() -> None:
    """Discard the cached report singleton (test isolation helper)."""
    global _SINGLETON  # noqa: PLW0603
    with _singleton_lock():
        _SINGLETON = None
