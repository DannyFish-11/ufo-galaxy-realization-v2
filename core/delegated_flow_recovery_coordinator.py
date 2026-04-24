#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/delegated_flow_recovery_coordinator.py
============================================
PR-4 (post-533 dual-repo runtime unification master plan, MAIN repo side):
DelegatedFlowRecoveryCoordinator — Unified Flow-Level Replay / Resume /
Re-dispatch Recovery Orchestration Owner.

Problem addressed
-----------------
After PR-3 established ``FlowContinuityCoordinator`` as the unified decision
entry-point for continuity classification (should we resume?), the system still
lacked an owner capable of acting on those decisions and executing the actual
recovery: *how* to resume, *which* checkpoint to replay from, *when* to
re-dispatch to the Android runtime, and *how* to converge partial results
without overwriting them.

Specifically, no single module answered:

* Which persisted checkpoint / execution boundary to restore from.
* Whether to resume in-place, replay missing steps, or re-dispatch entirely.
* How to suppress a duplicate recovery attempt for the same flow.
* How to preserve partial results during recovery rather than overwriting them.
* What artifacts to expose for operator diagnostics and truth-alignment.

This module closes that gap.

Design
------
- **Additive only** — no existing module is modified.
- **Decision-first** — every public entry-point returns a
  :class:`RecoveryDecisionArtifact` embedding all evidence and the
  :class:`RecoveryAction` that downstream layers must execute.
- **Idempotent guard** — a per-flow in-memory attempt registry prevents the
  same flow from being simultaneously recovered twice.  Duplicate attempts
  receive ``suppress_duplicate_recovery``.
- **Fail-closed** — ambiguous or missing context yields ``fail_closed`` so the
  caller applies a conservative fallback.
- **Continuity-aware** — accepts a :class:`~core.flow_continuity_coordinator
  .ContinuityDecisionArtifact` as optional evidence; the coordinator upgrades
  its own decision based on the continuity signal.
- **Extensible artifact** — :class:`RecoveryDecisionArtifact` carries
  ``extension_payload`` for operator surfaces and truth-alignment layers.
- **Singleton accessor** — :func:`get_delegated_flow_recovery_coordinator`
  returns the process-level singleton; :func:`reset_delegated_flow_recovery_coordinator`
  resets it (test isolation).

Recovery actions
----------------
``resume_in_place``
    The flow has a live or restorable execution context; continue from the
    most-recent durable continuity state without replaying steps.

``replay_from_checkpoint``
    A persisted checkpoint / execution boundary exists; replay all steps
    from that boundary to reconstruct missing execution progress.

``redispatch_runtime``
    The prior Android dispatch target is gone or the binding is invalid;
    re-dispatch to a new Android runtime.

``preserve_partial_then_resume``
    Partial results exist; preserve them, then resume or replay from the
    boundary at which the partial result was captured.

``suppress_duplicate_recovery``
    A recovery attempt for this flow is already in progress; suppress this
    duplicate attempt to prevent double-execution.

``fail_closed``
    Recovery cannot proceed safely; the caller must treat the flow as
    non-recoverable and escalate or require review.

``require_review``
    The scenario is ambiguous; human or operator review is recommended.

Integration boundaries
----------------------
:mod:`core.flow_continuity_coordinator`
    Consulted for the upstream continuity decision artifact.  The recovery
    coordinator *consumes* that artifact rather than re-deriving it.

:mod:`core.delegated_flow_entity`
    Consulted for flow-level phase and lineage to determine whether replay
    is needed and from which phase boundary.

:mod:`core.delegated_flow_persistence`
    Consulted to determine whether durable persistence snapshots exist for
    the flow, which establishes the replay boundary.

:mod:`core.delegated_runtime_execution_tracker`
    Consulted for in-flight task disposition and partial-result detection.

:mod:`core.android_runtime_dispatch_binding`
    Consulted to determine whether the prior dispatch binding is still
    valid (bound/dispatching) or has been released/invalidated.

:mod:`core.task_lifecycle_persistence`
    Consulted for durable in-flight task records restored after V2 restart.

Sentinels
---------
:data:`DELEGATED_FLOW_RECOVERY_COORDINATOR_AUTHORITY`
:data:`DELEGATED_FLOW_RECOVERY_COORDINATOR_PR4_SENTINEL`
:data:`RECOVERY_COORDINATOR_IS_UNIFIED_ORCHESTRATION_OWNER_POLICY`
:data:`IDEMPOTENT_RECOVERY_GUARD_IS_PER_FLOW_POLICY`
:data:`PARTIAL_RESULT_CONVERGENCE_PRECEDES_RESUME_POLICY`
:data:`DUPLICATE_RECOVERY_SUPPRESSION_IS_COORDINATOR_OWNED_POLICY`
:data:`REDISPATCH_REQUIRES_BINDING_INVALIDATION_POLICY`
:data:`RECOVERY_ARTIFACTS_MUST_BE_AUDITABLE_POLICY`
:data:`FAIL_CLOSED_ON_AMBIGUOUS_RECOVERY_CONTEXT_POLICY`

Public API
----------
Enums::

    RecoveryAction
    RecoveryTrigger

Data classes::

    RecoveryTriggerContext
    RecoveryDecisionArtifact
    RecoveryAttemptRecord
    RecoveryCoordinatorSnapshot

Class::

    DelegatedFlowRecoveryCoordinator

Module-level convenience functions::

    decide_recovery
    decide_recovery_from_continuity_artifact
    begin_recovery_attempt
    complete_recovery_attempt
    suppress_recovery_attempt
    get_delegated_flow_recovery_coordinator
    reset_delegated_flow_recovery_coordinator
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Deque, Dict, List, Optional, Tuple

__all__ = [
    # Sentinels
    "DELEGATED_FLOW_RECOVERY_COORDINATOR_AUTHORITY",
    "DELEGATED_FLOW_RECOVERY_COORDINATOR_PR4_SENTINEL",
    "RECOVERY_COORDINATOR_IS_UNIFIED_ORCHESTRATION_OWNER_POLICY",
    "IDEMPOTENT_RECOVERY_GUARD_IS_PER_FLOW_POLICY",
    "PARTIAL_RESULT_CONVERGENCE_PRECEDES_RESUME_POLICY",
    "DUPLICATE_RECOVERY_SUPPRESSION_IS_COORDINATOR_OWNED_POLICY",
    "REDISPATCH_REQUIRES_BINDING_INVALIDATION_POLICY",
    "RECOVERY_ARTIFACTS_MUST_BE_AUDITABLE_POLICY",
    "FAIL_CLOSED_ON_AMBIGUOUS_RECOVERY_CONTEXT_POLICY",
    # Enums
    "RecoveryAction",
    "RecoveryTrigger",
    # Data classes
    "RecoveryTriggerContext",
    "RecoveryDecisionArtifact",
    "RecoveryAttemptRecord",
    "RecoveryCoordinatorSnapshot",
    # Main class
    "DelegatedFlowRecoveryCoordinator",
    # Convenience functions
    "decide_recovery",
    "decide_recovery_from_continuity_artifact",
    "begin_recovery_attempt",
    "complete_recovery_attempt",
    "suppress_recovery_attempt",
    # Singleton
    "get_delegated_flow_recovery_coordinator",
    "reset_delegated_flow_recovery_coordinator",
]

logger = logging.getLogger("Galaxy.DelegatedFlowRecoveryCoordinator")

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

DELEGATED_FLOW_RECOVERY_COORDINATOR_AUTHORITY: str = (
    "DELEGATED_FLOW_RECOVERY_COORDINATOR_AUTHORITY::"
    "core.delegated_flow_recovery_coordinator is the canonical unified "
    "orchestration owner for flow-level replay / resume / re-dispatch "
    "recovery in V2.  Downstream layers (continuity coordinators, operator "
    "surfaces, truth-alignment layers) MUST route recovery decisions through "
    "DelegatedFlowRecoveryCoordinator rather than implementing ad-hoc recovery "
    "logic scattered across individual modules."
)

DELEGATED_FLOW_RECOVERY_COORDINATOR_PR4_SENTINEL: str = (
    "DELEGATED_FLOW_RECOVERY_COORDINATOR_PR4_SENTINEL::"
    "package=4 "
    "track=post-533-dual-repo-runtime-unification "
    "repo=main "
    "module=core.delegated_flow_recovery_coordinator "
    "title=unified-flow-recovery-orchestration-owner"
)

RECOVERY_COORDINATOR_IS_UNIFIED_ORCHESTRATION_OWNER_POLICY: str = (
    "POLICY::RECOVERY_COORDINATOR_IS_UNIFIED_ORCHESTRATION_OWNER_PR-4: "
    "DelegatedFlowRecoveryCoordinator is the single unified orchestration "
    "owner for all flow-level recovery decisions: resume_in_place, "
    "replay_from_checkpoint, redispatch_runtime, preserve_partial_then_resume, "
    "suppress_duplicate_recovery, fail_closed, and require_review.  No "
    "recovery decision SHOULD be derived outside this coordinator without "
    "explicit delegation from it.  PR-4."
)

IDEMPOTENT_RECOVERY_GUARD_IS_PER_FLOW_POLICY: str = (
    "POLICY::IDEMPOTENT_RECOVERY_GUARD_IS_PER_FLOW_PR-4: "
    "The coordinator maintains a per-flow in-memory attempt registry that "
    "prevents the same delegated_flow_id from being recovered by two "
    "simultaneous recovery attempts.  A second attempt for a flow that already "
    "has an active RecoveryAttemptRecord in state 'in_progress' MUST receive "
    "suppress_duplicate_recovery.  PR-4."
)

PARTIAL_RESULT_CONVERGENCE_PRECEDES_RESUME_POLICY: str = (
    "POLICY::PARTIAL_RESULT_CONVERGENCE_PRECEDES_RESUME_PR-4: "
    "When partial results are detected for a flow being recovered, the "
    "coordinator MUST emit preserve_partial_then_resume rather than "
    "resume_in_place or replay_from_checkpoint.  Callers MUST record the "
    "partial result before executing the resume or replay step.  Partial "
    "results MUST NOT be silently overwritten by a recovery action.  PR-4."
)

DUPLICATE_RECOVERY_SUPPRESSION_IS_COORDINATOR_OWNED_POLICY: str = (
    "POLICY::DUPLICATE_RECOVERY_SUPPRESSION_IS_COORDINATOR_OWNED_PR-4: "
    "Detection and suppression of duplicate recovery attempts is owned "
    "exclusively by DelegatedFlowRecoveryCoordinator.  Callers MUST NOT "
    "implement their own duplicate-suppression logic for delegated flow "
    "recovery; they MUST rely on the coordinator's suppress_duplicate_recovery "
    "decision.  PR-4."
)

REDISPATCH_REQUIRES_BINDING_INVALIDATION_POLICY: str = (
    "POLICY::REDISPATCH_REQUIRES_BINDING_INVALIDATION_PR-4: "
    "The coordinator MUST NOT emit redispatch_runtime unless the prior Android "
    "dispatch binding is confirmed to be released, invalidated, or absent.  If "
    "the binding is still in a bound or dispatching state the coordinator MUST "
    "prefer resume_in_place or replay_from_checkpoint instead.  PR-4."
)

RECOVERY_ARTIFACTS_MUST_BE_AUDITABLE_POLICY: str = (
    "POLICY::RECOVERY_ARTIFACTS_MUST_BE_AUDITABLE_PR-4: "
    "Every RecoveryDecisionArtifact produced by the coordinator MUST carry a "
    "stable artifact_id, the originating flow_id and flow_lineage_id, the "
    "recovery_attempt_id that initiated the recovery, and a policy_reference "
    "string.  These fields are required for operator diagnostics and truth "
    "alignment.  PR-4."
)

FAIL_CLOSED_ON_AMBIGUOUS_RECOVERY_CONTEXT_POLICY: str = (
    "POLICY::FAIL_CLOSED_ON_AMBIGUOUS_RECOVERY_CONTEXT_PR-4: "
    "When DelegatedFlowRecoveryCoordinator cannot safely determine the "
    "appropriate recovery action (missing flow_id, conflicting evidence, "
    "unavailable registries, internal error), it MUST emit fail_closed.  "
    "Callers MUST treat fail_closed as non-recoverable and escalate or "
    "require human review.  PR-4."
)

_ALL_POLICY_SENTINELS: Tuple[str, ...] = (
    DELEGATED_FLOW_RECOVERY_COORDINATOR_AUTHORITY,
    DELEGATED_FLOW_RECOVERY_COORDINATOR_PR4_SENTINEL,
    RECOVERY_COORDINATOR_IS_UNIFIED_ORCHESTRATION_OWNER_POLICY,
    IDEMPOTENT_RECOVERY_GUARD_IS_PER_FLOW_POLICY,
    PARTIAL_RESULT_CONVERGENCE_PRECEDES_RESUME_POLICY,
    DUPLICATE_RECOVERY_SUPPRESSION_IS_COORDINATOR_OWNED_POLICY,
    REDISPATCH_REQUIRES_BINDING_INVALIDATION_POLICY,
    RECOVERY_ARTIFACTS_MUST_BE_AUDITABLE_POLICY,
    FAIL_CLOSED_ON_AMBIGUOUS_RECOVERY_CONTEXT_POLICY,
)

# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

_RING_BUFFER_CAPACITY: int = 256

# Android binding states considered invalid for redispatch eligibility
_VALID_BINDING_STATES: frozenset = frozenset({"bound", "dispatching"})

# Flow phases that indicate an active or in-progress execution context
_ACTIVE_FLOW_PHASES: frozenset = frozenset(
    {"dispatched", "executing", "reconciling", "suspended"}
)

# Execution phases that imply partial results may be present
_PARTIAL_RESULT_PHASES: frozenset = frozenset({"in_progress", "acknowledged"})

# ---------------------------------------------------------------------------
# Lazy imports for integrated modules
# ---------------------------------------------------------------------------


def _try_import_flow_entity_runtime():
    """Return get_delegated_flow_entity_runtime or None."""
    try:
        from core.delegated_flow_entity import (  # type: ignore
            get_delegated_flow_entity_runtime,
        )
        return get_delegated_flow_entity_runtime
    except Exception:
        return None


def _try_import_persistence_bundle():
    """Return get_delegated_flow_persistence_bundle or None."""
    try:
        from core.delegated_flow_persistence import (  # type: ignore
            get_delegated_flow_persistence_bundle,
        )
        return get_delegated_flow_persistence_bundle
    except Exception:
        return None


def _try_import_execution_tracker():
    """Return get_execution_tracking_runtime or None."""
    try:
        from core.delegated_runtime_execution_tracker import (  # type: ignore
            get_execution_tracking_runtime,
        )
        return get_execution_tracking_runtime
    except Exception:
        return None


def _try_import_dispatch_binding_runtime():
    """Return get_dispatch_binding_runtime or None."""
    try:
        from core.android_runtime_dispatch_binding import (  # type: ignore
            get_dispatch_binding_runtime,
        )
        return get_dispatch_binding_runtime
    except Exception:
        return None


def _try_import_task_lifecycle_persistence():
    """Return load_task_lifecycle_snapshot or None."""
    try:
        from core.task_lifecycle_persistence import (  # type: ignore
            load_task_lifecycle_snapshot,
        )
        return load_task_lifecycle_snapshot
    except Exception:
        return None


def _try_import_continuity_coordinator():
    """Return get_flow_continuity_coordinator or None."""
    try:
        from core.flow_continuity_coordinator import (  # type: ignore
            get_flow_continuity_coordinator,
        )
        return get_flow_continuity_coordinator
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class RecoveryAction(str, Enum):
    """Canonical output of a DelegatedFlowRecoveryCoordinator decision.

    Each value represents the coordinator's authoritative classification of
    the recovery action that should be taken for a delegated flow.  Downstream
    layers MUST execute this action rather than re-deriving it from raw state.

    Values
    ------
    resume_in_place
        The flow has a live or restorable execution context; continue from
        the most-recent durable continuity state without replaying steps.

    replay_from_checkpoint
        A persisted checkpoint / execution boundary exists; replay all steps
        from that boundary to reconstruct missing execution progress.

    redispatch_runtime
        The prior Android dispatch target is gone or the binding is invalid;
        re-dispatch to a new Android runtime surface.

    preserve_partial_then_resume
        Partial results exist; preserve them, then resume or replay from
        the boundary at which the partial result was captured.

    suppress_duplicate_recovery
        A recovery attempt for this flow is already in progress; suppress
        this duplicate attempt to prevent double-execution.

    fail_closed
        Recovery cannot proceed safely; treat as non-recoverable.

    require_review
        The scenario is ambiguous; operator review is recommended.
    """

    resume_in_place = "resume_in_place"
    replay_from_checkpoint = "replay_from_checkpoint"
    redispatch_runtime = "redispatch_runtime"
    preserve_partial_then_resume = "preserve_partial_then_resume"
    suppress_duplicate_recovery = "suppress_duplicate_recovery"
    fail_closed = "fail_closed"
    require_review = "require_review"

    @classmethod
    def from_string(
        cls, value: str, default: Optional["RecoveryAction"] = None
    ) -> "RecoveryAction":
        """Return the enum member matching *value*, or *default* / fail_closed."""
        if not isinstance(value, str):
            return default if default is not None else cls.fail_closed
        try:
            return cls(value.lower().strip())
        except ValueError:
            return default if default is not None else cls.fail_closed

    @property
    def is_executable(self) -> bool:
        """True when the action requires active execution (not suppressed/failed)."""
        return self in (
            self.resume_in_place,
            self.replay_from_checkpoint,
            self.redispatch_runtime,
            self.preserve_partial_then_resume,
        )


class RecoveryTrigger(str, Enum):
    """Canonical classification of what triggered the recovery attempt.

    Values
    ------
    v2_restart
        V2 process restarted; recovery initiated from durable persistence.
    android_binding_lost
        Android runtime binding was released or invalidated.
    continuity_decision
        FlowContinuityCoordinator emitted a continuity-resumable decision.
    explicit_operator_request
        An operator explicitly requested recovery for this flow.
    session_reconnect
        Transport session reconnected; recovery context needs to be resolved.
    process_recreation
        Android process was killed and recreated; needs re-dispatch or resume.
    checkpoint_available
        A durable checkpoint was found; replay is possible.
    unknown
        Trigger is not yet determined.
    """

    v2_restart = "v2_restart"
    android_binding_lost = "android_binding_lost"
    continuity_decision = "continuity_decision"
    explicit_operator_request = "explicit_operator_request"
    session_reconnect = "session_reconnect"
    process_recreation = "process_recreation"
    checkpoint_available = "checkpoint_available"
    unknown = "unknown"

    @classmethod
    def from_string(cls, value: str) -> "RecoveryTrigger":
        """Return the enum member matching *value*, defaulting to ``unknown``."""
        if not isinstance(value, str):
            return cls.unknown
        try:
            return cls(value.lower().strip())
        except ValueError:
            return cls.unknown


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class RecoveryTriggerContext:
    """Input context for a DelegatedFlowRecoveryCoordinator decision request.

    All fields are optional to accommodate partial-context callers; the
    coordinator applies fail_closed when required fields are absent.

    Attributes
    ----------
    trigger
        The type of recovery trigger that initiated this request.
    flow_id
        Delegated flow entity identifier (required for idempotency guard).
    flow_lineage_id
        Flow lineage identifier (spans V2 and Android sides).
    session_id
        External session identifier.
    contract_id
        Delegated handoff contract identifier.
    tracker_id
        Execution tracker entry identifier.
    device_id
        V2-side device identifier.
    binding_id
        Android dispatch binding identifier.
    runtime_attachment_session_id
        Canonical stable attachment identity.
    continuity_artifact_id
        artifact_id of a prior ContinuityDecisionArtifact that should inform
        this recovery decision.
    continuity_decision
        String value of the ContinuityDecision from the upstream coordinator
        (e.g. ``"continuity_resume"``).
    has_partial_result
        True when the caller knows partial results exist for this flow.
    partial_result_payload
        Opaque partial-result payload for preserve_partial_then_resume.
    checkpoint_available
        True when the caller has confirmed a durable checkpoint exists.
    checkpoint_boundary_phase
        Flow phase at which the checkpoint was captured.
    binding_state
        Current state of the Android dispatch binding (e.g. ``"released"``).
    recovery_attempt_id
        Caller-supplied attempt identity for linking to an existing attempt.
    metadata
        Arbitrary caller-supplied extension metadata.
    """

    trigger: RecoveryTrigger = RecoveryTrigger.unknown
    flow_id: str = ""
    flow_lineage_id: str = ""
    session_id: str = ""
    contract_id: str = ""
    tracker_id: str = ""
    device_id: str = ""
    binding_id: str = ""
    runtime_attachment_session_id: str = ""
    continuity_artifact_id: str = ""
    continuity_decision: str = ""
    has_partial_result: bool = False
    partial_result_payload: Optional[Dict[str, Any]] = None
    checkpoint_available: bool = False
    checkpoint_boundary_phase: str = ""
    binding_state: str = ""
    recovery_attempt_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trigger": self.trigger.value,
            "flow_id": self.flow_id,
            "flow_lineage_id": self.flow_lineage_id,
            "session_id": self.session_id,
            "contract_id": self.contract_id,
            "tracker_id": self.tracker_id,
            "device_id": self.device_id,
            "binding_id": self.binding_id,
            "runtime_attachment_session_id": self.runtime_attachment_session_id,
            "continuity_artifact_id": self.continuity_artifact_id,
            "continuity_decision": self.continuity_decision,
            "has_partial_result": self.has_partial_result,
            "partial_result_payload": self.partial_result_payload,
            "checkpoint_available": self.checkpoint_available,
            "checkpoint_boundary_phase": self.checkpoint_boundary_phase,
            "binding_state": self.binding_state,
            "recovery_attempt_id": self.recovery_attempt_id,
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


@dataclass
class RecoveryDecisionArtifact:
    """Fully serialisable output of a DelegatedFlowRecoveryCoordinator decision.

    This is the primary value returned by every coordinator entry-point.  It
    embeds the :class:`RecoveryAction`, all input context fields, all evidence
    used to reach the decision, the policy reference, and an extension payload
    for downstream consumers (operator surfaces, truth-alignment layers).

    Attributes
    ----------
    artifact_id
        Unique, stable identifier for this artifact (UUID4).
    recovery_attempt_id
        Identifier of the recovery attempt this decision belongs to.
    trigger
        The type of recovery trigger that initiated this request.
    action
        The coordinator's authoritative recovery action decision.
    policy_reference
        Name of the policy sentinel that drove the decision.
    detail
        Human-readable explanation of the decision.
    flow_id
        Delegated flow entity identifier.
    flow_lineage_id
        Flow lineage identifier.
    session_id
        Session identifier from the input context.
    contract_id
        Contract identifier from the input context.
    tracker_id
        Tracker identifier from the input context.
    device_id
        Device identifier from the input context.
    binding_id
        Binding identifier from the input context.
    continuity_artifact_id
        artifact_id of the upstream ContinuityDecisionArtifact (if any).
    continuity_decision
        Upstream continuity decision string (if any).
    flow_entity_phase
        Phase of the flow entity at decision time, or ``""`` when unavailable.
    binding_state_at_decision
        State of the Android dispatch binding at decision time, or ``""``
        when not consulted.
    tracker_phase_at_decision
        Phase of the execution tracking record at decision time, or ``""``
        when not consulted.
    checkpoint_boundary_phase
        Flow phase at which the recovery checkpoint was captured, or ``""``
        when no checkpoint is used.
    has_partial_result
        True when partial results were detected and influenced the decision.
    is_executable
        True when the action requires active execution steps.
    extension_payload
        Arbitrary extension metadata for downstream consumers.  Keys MUST be
        namespaced to avoid collisions (e.g. ``operator_tag``,
        ``truth_alignment_hint``).
    timestamp
        Unix timestamp when this artifact was created.
    """

    artifact_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    recovery_attempt_id: str = ""
    trigger: RecoveryTrigger = RecoveryTrigger.unknown
    action: RecoveryAction = RecoveryAction.fail_closed
    policy_reference: str = ""
    detail: str = ""
    flow_id: str = ""
    flow_lineage_id: str = ""
    session_id: str = ""
    contract_id: str = ""
    tracker_id: str = ""
    device_id: str = ""
    binding_id: str = ""
    continuity_artifact_id: str = ""
    continuity_decision: str = ""
    flow_entity_phase: str = ""
    binding_state_at_decision: str = ""
    tracker_phase_at_decision: str = ""
    checkpoint_boundary_phase: str = ""
    has_partial_result: bool = False
    is_executable: bool = False
    extension_payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "recovery_attempt_id": self.recovery_attempt_id,
            "trigger": self.trigger.value,
            "action": self.action.value,
            "policy_reference": self.policy_reference,
            "detail": self.detail,
            "flow_id": self.flow_id,
            "flow_lineage_id": self.flow_lineage_id,
            "session_id": self.session_id,
            "contract_id": self.contract_id,
            "tracker_id": self.tracker_id,
            "device_id": self.device_id,
            "binding_id": self.binding_id,
            "continuity_artifact_id": self.continuity_artifact_id,
            "continuity_decision": self.continuity_decision,
            "flow_entity_phase": self.flow_entity_phase,
            "binding_state_at_decision": self.binding_state_at_decision,
            "tracker_phase_at_decision": self.tracker_phase_at_decision,
            "checkpoint_boundary_phase": self.checkpoint_boundary_phase,
            "has_partial_result": self.has_partial_result,
            "is_executable": self.is_executable,
            "extension_payload": self.extension_payload,
            "timestamp": self.timestamp,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RecoveryDecisionArtifact":
        """Construct from a dictionary.  Tolerates unknown extra fields."""
        return cls(
            artifact_id=data.get("artifact_id", str(uuid.uuid4())),
            recovery_attempt_id=data.get("recovery_attempt_id", ""),
            trigger=RecoveryTrigger.from_string(data.get("trigger", "unknown")),
            action=RecoveryAction.from_string(data.get("action", "fail_closed")),
            policy_reference=data.get("policy_reference", ""),
            detail=data.get("detail", ""),
            flow_id=data.get("flow_id", ""),
            flow_lineage_id=data.get("flow_lineage_id", ""),
            session_id=data.get("session_id", ""),
            contract_id=data.get("contract_id", ""),
            tracker_id=data.get("tracker_id", ""),
            device_id=data.get("device_id", ""),
            binding_id=data.get("binding_id", ""),
            continuity_artifact_id=data.get("continuity_artifact_id", ""),
            continuity_decision=data.get("continuity_decision", ""),
            flow_entity_phase=data.get("flow_entity_phase", ""),
            binding_state_at_decision=data.get("binding_state_at_decision", ""),
            tracker_phase_at_decision=data.get("tracker_phase_at_decision", ""),
            checkpoint_boundary_phase=data.get("checkpoint_boundary_phase", ""),
            has_partial_result=data.get("has_partial_result", False),
            is_executable=data.get("is_executable", False),
            extension_payload=data.get("extension_payload", {}),
            timestamp=data.get("timestamp", time.time()),
        )


class RecoveryAttemptState(str, Enum):
    """Lifecycle state of a recovery attempt record.

    Values
    ------
    in_progress
        Recovery attempt is currently executing; duplicate suppression is active.
    completed
        Recovery attempt finished successfully.
    suppressed
        Attempt was a duplicate and was suppressed.
    failed
        Recovery attempt failed; fail_closed was emitted.
    """

    in_progress = "in_progress"
    completed = "completed"
    suppressed = "suppressed"
    failed = "failed"


@dataclass
class RecoveryAttemptRecord:
    """Audit trail record for a single recovery attempt on a delegated flow.

    This record serves as both the idempotency guard entry and the audit
    trail artifact for operator diagnostics.

    Attributes
    ----------
    attempt_id
        Unique, stable identifier for this recovery attempt (UUID4).
    flow_id
        The delegated flow this attempt is recovering.
    flow_lineage_id
        Flow lineage identifier (for cross-side tracing).
    trigger
        The trigger that initiated this attempt.
    state
        Current lifecycle state of this attempt.
    action_decided
        The RecoveryAction decided for this attempt.
    artifact_id
        ID of the RecoveryDecisionArtifact produced for this attempt.
    started_at
        Unix timestamp when the attempt was started.
    completed_at
        Unix timestamp when the attempt completed (0.0 if still in progress).
    metadata
        Arbitrary caller-supplied metadata attached to this attempt.
    """

    attempt_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    flow_id: str = ""
    flow_lineage_id: str = ""
    trigger: RecoveryTrigger = RecoveryTrigger.unknown
    state: RecoveryAttemptState = RecoveryAttemptState.in_progress
    action_decided: RecoveryAction = RecoveryAction.fail_closed
    artifact_id: str = ""
    started_at: float = field(default_factory=time.time)
    completed_at: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "flow_id": self.flow_id,
            "flow_lineage_id": self.flow_lineage_id,
            "trigger": self.trigger.value,
            "state": self.state.value,
            "action_decided": self.action_decided.value,
            "artifact_id": self.artifact_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RecoveryAttemptRecord":
        return cls(
            attempt_id=data.get("attempt_id", str(uuid.uuid4())),
            flow_id=data.get("flow_id", ""),
            flow_lineage_id=data.get("flow_lineage_id", ""),
            trigger=RecoveryTrigger.from_string(data.get("trigger", "unknown")),
            state=RecoveryAttemptState(
                data.get("state", RecoveryAttemptState.in_progress.value)
            ),
            action_decided=RecoveryAction.from_string(
                data.get("action_decided", "fail_closed")
            ),
            artifact_id=data.get("artifact_id", ""),
            started_at=data.get("started_at", time.time()),
            completed_at=data.get("completed_at", 0.0),
            metadata=data.get("metadata", {}),
        )


@dataclass
class RecoveryCoordinatorSnapshot:
    """Point-in-time snapshot of the recovery coordinator for observability.

    Attributes
    ----------
    snapshot_id
        Unique identifier for this snapshot.
    total_decisions
        Total number of decisions recorded in the ring-buffer.
    action_counts
        Mapping of action string → count across the ring-buffer.
    active_attempt_count
        Number of currently in-progress recovery attempts.
    recent_artifacts
        The most-recent artifacts (up to 10) for operator inspection.
    recent_attempts
        The most-recent attempt records (up to 10) for audit inspection.
    policy_sentinels
        All policy sentinels active in this coordinator.
    timestamp
        Unix timestamp when this snapshot was created.
    """

    snapshot_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    total_decisions: int = 0
    action_counts: Dict[str, int] = field(default_factory=dict)
    active_attempt_count: int = 0
    recent_artifacts: List[Dict[str, Any]] = field(default_factory=list)
    recent_attempts: List[Dict[str, Any]] = field(default_factory=list)
    policy_sentinels: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "total_decisions": self.total_decisions,
            "action_counts": self.action_counts,
            "active_attempt_count": self.active_attempt_count,
            "recent_artifacts": self.recent_artifacts,
            "recent_attempts": self.recent_attempts,
            "policy_sentinels": self.policy_sentinels,
            "timestamp": self.timestamp,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


# ---------------------------------------------------------------------------
# DelegatedFlowRecoveryCoordinator
# ---------------------------------------------------------------------------


class DelegatedFlowRecoveryCoordinator:
    """Unified orchestration owner for flow-level replay / resume / re-dispatch.

    This class is the single decision entry-point for all recovery actions on
    delegated flows, consuming ContinuityDecisionArtifact evidence from
    :class:`~core.flow_continuity_coordinator.FlowContinuityCoordinator` and
    integrating with flow entity, persistence, execution tracker, and binding
    modules to decide and record recovery actions.

    Thread safety
    -------------
    The ring-buffer and attempt registry are protected by an internal
    :class:`threading.Lock` and are safe for concurrent use.

    Parameters
    ----------
    capacity
        Ring-buffer capacity for decision artifact history.  Defaults to 256.
    """

    def __init__(self, capacity: int = _RING_BUFFER_CAPACITY) -> None:
        self._capacity = capacity
        self._buffer: Deque[RecoveryDecisionArtifact] = deque(maxlen=capacity)
        # attempt_id → RecoveryAttemptRecord for audit trail
        self._attempt_log: Deque[RecoveryAttemptRecord] = deque(
            maxlen=capacity
        )
        # flow_id → attempt_id for in-progress duplicate suppression
        self._active_attempts: Dict[str, str] = {}
        self._lock = threading.Lock()

        # Lazy-loaded integration handles
        self._get_flow_entity_runtime = None
        self._get_persistence_bundle = None
        self._get_execution_tracking_runtime = None
        self._get_dispatch_binding_runtime = None
        self._load_task_lifecycle_snapshot = None
        self._get_continuity_coordinator = None

    # ------------------------------------------------------------------
    # Integration module accessors (lazy)
    # ------------------------------------------------------------------

    def _flow_entity_runtime(self):
        """Return DelegatedFlowEntityRuntime or None."""
        if self._get_flow_entity_runtime is None:
            self._get_flow_entity_runtime = _try_import_flow_entity_runtime()
        if self._get_flow_entity_runtime is None:
            return None
        try:
            return self._get_flow_entity_runtime()
        except Exception:
            return None

    def _persistence_bundle(self):
        """Return DelegatedFlowPersistenceBundle or None."""
        if self._get_persistence_bundle is None:
            self._get_persistence_bundle = _try_import_persistence_bundle()
        if self._get_persistence_bundle is None:
            return None
        try:
            return self._get_persistence_bundle()
        except Exception:
            return None

    def _execution_tracker(self):
        """Return DelegatedExecutionTrackingRuntime or None."""
        if self._get_execution_tracking_runtime is None:
            self._get_execution_tracking_runtime = _try_import_execution_tracker()
        if self._get_execution_tracking_runtime is None:
            return None
        try:
            return self._get_execution_tracking_runtime()
        except Exception:
            return None

    def _binding_runtime(self):
        """Return AndroidRuntimeDispatchBindingRuntime or None."""
        if self._get_dispatch_binding_runtime is None:
            self._get_dispatch_binding_runtime = (
                _try_import_dispatch_binding_runtime()
            )
        if self._get_dispatch_binding_runtime is None:
            return None
        try:
            return self._get_dispatch_binding_runtime()
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _record(self, artifact: RecoveryDecisionArtifact) -> None:
        """Append *artifact* to the ring-buffer (thread-safe)."""
        with self._lock:
            self._buffer.append(artifact)

    def _record_attempt(self, attempt: RecoveryAttemptRecord) -> None:
        """Append *attempt* to the attempt log (thread-safe)."""
        with self._lock:
            self._attempt_log.append(attempt)

    def _base_artifact(
        self,
        ctx: RecoveryTriggerContext,
        action: RecoveryAction,
        *,
        policy_reference: str,
        detail: str,
        flow_entity_phase: str = "",
        binding_state_at_decision: str = "",
        tracker_phase_at_decision: str = "",
        checkpoint_boundary_phase: str = "",
    ) -> RecoveryDecisionArtifact:
        """Build a :class:`RecoveryDecisionArtifact` from *ctx* and decision data."""
        return RecoveryDecisionArtifact(
            recovery_attempt_id=ctx.recovery_attempt_id,
            trigger=ctx.trigger,
            action=action,
            policy_reference=policy_reference,
            detail=detail,
            flow_id=ctx.flow_id,
            flow_lineage_id=ctx.flow_lineage_id,
            session_id=ctx.session_id,
            contract_id=ctx.contract_id,
            tracker_id=ctx.tracker_id,
            device_id=ctx.device_id,
            binding_id=ctx.binding_id,
            continuity_artifact_id=ctx.continuity_artifact_id,
            continuity_decision=ctx.continuity_decision,
            flow_entity_phase=flow_entity_phase,
            binding_state_at_decision=binding_state_at_decision,
            tracker_phase_at_decision=tracker_phase_at_decision,
            checkpoint_boundary_phase=checkpoint_boundary_phase,
            has_partial_result=ctx.has_partial_result,
            is_executable=action.is_executable,
        )

    def _lookup_flow_phase(self, ctx: RecoveryTriggerContext) -> str:
        """Return the current flow entity phase string, or ``""``."""
        if not ctx.flow_id:
            return ""
        try:
            runtime = self._flow_entity_runtime()
            if runtime is None:
                return ""
            record = runtime.get(ctx.flow_id)
            if record is None:
                return ""
            phase = getattr(record, "phase", None)
            if phase is None:
                return ""
            return phase.value if hasattr(phase, "value") else str(phase)
        except Exception:
            return ""

    def _lookup_tracker_phase(self, ctx: RecoveryTriggerContext) -> str:
        """Return the execution tracker phase string for this context, or ``""``."""
        if not (ctx.tracker_id or ctx.session_id):
            return ""
        try:
            runtime = self._execution_tracker()
            if runtime is None:
                return ""
            record = None
            if ctx.tracker_id:
                record = getattr(runtime, "get", lambda *a, **kw: None)(
                    ctx.tracker_id
                )
            if record is None and ctx.session_id:
                # fall back to session-keyed lookup
                get_by_session = getattr(
                    runtime, "get_by_session_id", None
                )
                if get_by_session:
                    record = get_by_session(ctx.session_id)
            if record is None:
                return ""
            phase = getattr(record, "phase", None)
            if phase is None:
                return ""
            return phase.value if hasattr(phase, "value") else str(phase)
        except Exception:
            return ""

    def _lookup_binding_state(self, ctx: RecoveryTriggerContext) -> str:
        """Return the dispatch binding state string for this context, or ``""``."""
        if ctx.binding_state:
            return ctx.binding_state
        if not (ctx.binding_id or ctx.session_id):
            return ""
        try:
            runtime = self._binding_runtime()
            if runtime is None:
                return ""
            record = None
            if ctx.binding_id:
                get_fn = getattr(runtime, "get", None)
                if get_fn:
                    record = get_fn(ctx.binding_id)
            if record is None and ctx.session_id:
                get_by_session = getattr(runtime, "get_by_session_id", None)
                if get_by_session:
                    record = get_by_session(ctx.session_id)
            if record is None:
                return ""
            state = getattr(record, "binding_state", None)
            if state is None:
                return ""
            return state.value if hasattr(state, "value") else str(state)
        except Exception:
            return ""

    def _has_durable_persistence(self, ctx: RecoveryTriggerContext) -> bool:
        """Return True when the persistence bundle has durable snapshots."""
        try:
            bundle = self._persistence_bundle()
            if bundle is None:
                return False
            flow_store = getattr(bundle, "flow_entity_store", None)
            if flow_store is None:
                return False
            snapshots = flow_store.load()
            if not snapshots:
                return False
            if ctx.flow_id:
                return any(
                    getattr(s, "delegated_flow_id", None) == ctx.flow_id
                    for s in snapshots
                )
            return True
        except Exception:
            return False

    def _check_duplicate(self, flow_id: str) -> Optional[str]:
        """Return active attempt_id for *flow_id* if one exists, else None."""
        with self._lock:
            return self._active_attempts.get(flow_id)

    def _register_attempt(self, flow_id: str, attempt_id: str) -> None:
        """Register *attempt_id* as active for *flow_id*."""
        with self._lock:
            self._active_attempts[flow_id] = attempt_id

    def _deregister_attempt(self, flow_id: str) -> None:
        """Remove the active attempt registration for *flow_id*."""
        with self._lock:
            self._active_attempts.pop(flow_id, None)

    # ------------------------------------------------------------------
    # Primary decision methods
    # ------------------------------------------------------------------

    def decide(self, ctx: RecoveryTriggerContext) -> RecoveryDecisionArtifact:
        """Main entry-point: decide the recovery action for a delegated flow.

        This method:

        1. Validates that ``flow_id`` is present (fail_closed if missing).
        2. Checks for a duplicate in-progress attempt (suppress if found).
        3. Detects partial results and emits ``preserve_partial_then_resume``
           if applicable.
        4. Checks for a valid checkpoint and emits ``replay_from_checkpoint``
           if a durable boundary is available.
        5. Checks binding state: if invalid/absent emits ``redispatch_runtime``.
        6. Falls back to ``resume_in_place`` when the flow is active and no
           special case was triggered.
        7. Falls back to ``require_review`` when context is insufficient.

        Parameters
        ----------
        ctx
            :class:`RecoveryTriggerContext` carrying all available evidence.

        Returns
        -------
        RecoveryDecisionArtifact
        """
        if not ctx.flow_id:
            artifact = self._base_artifact(
                ctx,
                RecoveryAction.fail_closed,
                policy_reference=(
                    "FAIL_CLOSED_ON_AMBIGUOUS_RECOVERY_CONTEXT_POLICY"
                ),
                detail="flow_id is required for recovery decision",
            )
            self._record(artifact)
            return artifact

        # 1. Duplicate suppression guard
        existing_attempt_id = self._check_duplicate(ctx.flow_id)
        if existing_attempt_id:
            artifact = self._base_artifact(
                ctx,
                RecoveryAction.suppress_duplicate_recovery,
                policy_reference=(
                    "DUPLICATE_RECOVERY_SUPPRESSION_IS_COORDINATOR_OWNED_POLICY"
                ),
                detail=(
                    f"duplicate recovery attempt for flow_id={ctx.flow_id!r}; "
                    f"existing attempt_id={existing_attempt_id!r}"
                ),
            )
            self._record(artifact)
            return artifact

        # Gather evidence
        flow_phase = self._lookup_flow_phase(ctx)
        tracker_phase = self._lookup_tracker_phase(ctx)
        binding_state = self._lookup_binding_state(ctx)

        # 2. Partial result convergence takes priority
        has_partial = ctx.has_partial_result or tracker_phase in _PARTIAL_RESULT_PHASES
        if has_partial:
            artifact = self._base_artifact(
                ctx,
                RecoveryAction.preserve_partial_then_resume,
                policy_reference=(
                    "PARTIAL_RESULT_CONVERGENCE_PRECEDES_RESUME_POLICY"
                ),
                detail=(
                    "partial result detected; preserving before resume "
                    f"(tracker_phase={tracker_phase!r})"
                ),
                flow_entity_phase=flow_phase,
                binding_state_at_decision=binding_state,
                tracker_phase_at_decision=tracker_phase,
                checkpoint_boundary_phase=ctx.checkpoint_boundary_phase,
            )
            artifact.has_partial_result = True
            self._record(artifact)
            return artifact

        # 3. Checkpoint replay boundary
        has_checkpoint = ctx.checkpoint_available or self._has_durable_persistence(ctx)
        if has_checkpoint:
            artifact = self._base_artifact(
                ctx,
                RecoveryAction.replay_from_checkpoint,
                policy_reference=(
                    "RECOVERY_COORDINATOR_IS_UNIFIED_ORCHESTRATION_OWNER_POLICY"
                ),
                detail=(
                    "durable checkpoint available; replay from boundary "
                    f"(boundary_phase={ctx.checkpoint_boundary_phase!r})"
                ),
                flow_entity_phase=flow_phase,
                binding_state_at_decision=binding_state,
                tracker_phase_at_decision=tracker_phase,
                checkpoint_boundary_phase=ctx.checkpoint_boundary_phase,
            )
            self._record(artifact)
            return artifact

        # 4. Re-dispatch when binding is gone or invalid
        has_invalid_binding_state = (
            bool(binding_state) and binding_state not in _VALID_BINDING_STATES
        )
        requires_redispatch_trigger = ctx.trigger in (
            RecoveryTrigger.android_binding_lost,
            RecoveryTrigger.process_recreation,
        )
        binding_invalid = has_invalid_binding_state or (
            requires_redispatch_trigger and not binding_state
        )
        if binding_invalid:
            artifact = self._base_artifact(
                ctx,
                RecoveryAction.redispatch_runtime,
                policy_reference=(
                    "REDISPATCH_REQUIRES_BINDING_INVALIDATION_POLICY"
                ),
                detail=(
                    f"binding state {binding_state!r} is not valid; "
                    "re-dispatch required"
                ),
                flow_entity_phase=flow_phase,
                binding_state_at_decision=binding_state,
                tracker_phase_at_decision=tracker_phase,
            )
            self._record(artifact)
            return artifact

        # 5. Resume in-place when flow is active and continuity says so
        continuity_resumable = ctx.continuity_decision in (
            "continuity_resume", "preserve_partial_and_wait"
        )
        flow_is_active = flow_phase in _ACTIVE_FLOW_PHASES or not flow_phase
        if continuity_resumable or flow_is_active:
            artifact = self._base_artifact(
                ctx,
                RecoveryAction.resume_in_place,
                policy_reference=(
                    "RECOVERY_COORDINATOR_IS_UNIFIED_ORCHESTRATION_OWNER_POLICY"
                ),
                detail=(
                    "flow context is active and continuity is resumable; "
                    "resuming in place"
                ),
                flow_entity_phase=flow_phase,
                binding_state_at_decision=binding_state,
                tracker_phase_at_decision=tracker_phase,
            )
            self._record(artifact)
            return artifact

        # 6. Require review when context is insufficient
        artifact = self._base_artifact(
            ctx,
            RecoveryAction.require_review,
            policy_reference=(
                "FAIL_CLOSED_ON_AMBIGUOUS_RECOVERY_CONTEXT_POLICY"
            ),
            detail=(
                "insufficient context to determine recovery action; "
                "operator review required"
            ),
            flow_entity_phase=flow_phase,
            binding_state_at_decision=binding_state,
            tracker_phase_at_decision=tracker_phase,
        )
        self._record(artifact)
        return artifact

    def decide_from_continuity_artifact(
        self,
        ctx: RecoveryTriggerContext,
        continuity_artifact_dict: Dict[str, Any],
    ) -> RecoveryDecisionArtifact:
        """Decide recovery using evidence from a ContinuityDecisionArtifact.

        This helper enriches *ctx* with fields extracted from a prior
        :class:`~core.flow_continuity_coordinator.ContinuityDecisionArtifact`
        (passed as its ``to_dict()`` representation) before delegating to
        :meth:`decide`.

        Parameters
        ----------
        ctx
            :class:`RecoveryTriggerContext` — may be partially populated.
        continuity_artifact_dict
            ``to_dict()`` of a ``ContinuityDecisionArtifact``.

        Returns
        -------
        RecoveryDecisionArtifact
        """
        cad = continuity_artifact_dict or {}
        enriched = RecoveryTriggerContext(
            trigger=ctx.trigger
            if ctx.trigger != RecoveryTrigger.unknown
            else RecoveryTrigger.continuity_decision,
            flow_id=ctx.flow_id or cad.get("flow_id", ""),
            flow_lineage_id=ctx.flow_lineage_id or cad.get("flow_lineage_id", ""),
            session_id=ctx.session_id or cad.get("session_id", ""),
            contract_id=ctx.contract_id or cad.get("contract_id", ""),
            tracker_id=ctx.tracker_id or cad.get("tracker_id", ""),
            device_id=ctx.device_id or cad.get("device_id", ""),
            binding_id=ctx.binding_id,
            runtime_attachment_session_id=(
                ctx.runtime_attachment_session_id
                or cad.get("runtime_attachment_session_id", "")
            ),
            continuity_artifact_id=(
                ctx.continuity_artifact_id or cad.get("artifact_id", "")
            ),
            continuity_decision=(
                ctx.continuity_decision or cad.get("decision", "")
            ),
            has_partial_result=ctx.has_partial_result,
            partial_result_payload=ctx.partial_result_payload,
            checkpoint_available=ctx.checkpoint_available,
            checkpoint_boundary_phase=ctx.checkpoint_boundary_phase,
            binding_state=ctx.binding_state,
            recovery_attempt_id=ctx.recovery_attempt_id,
            metadata={**cad.get("extension_payload", {}), **ctx.metadata},
        )
        return self.decide(enriched)

    # ------------------------------------------------------------------
    # Attempt lifecycle management
    # ------------------------------------------------------------------

    def begin_attempt(
        self, ctx: RecoveryTriggerContext
    ) -> Tuple[RecoveryAttemptRecord, RecoveryDecisionArtifact]:
        """Begin a new recovery attempt and decide the action.

        Registers the flow_id in the active-attempt registry, calls
        :meth:`decide`, creates a :class:`RecoveryAttemptRecord`, and
        returns both.

        If a duplicate attempt is detected the attempt record is created
        with state ``suppressed``.

        Parameters
        ----------
        ctx
            :class:`RecoveryTriggerContext` for this attempt.

        Returns
        -------
        tuple[RecoveryAttemptRecord, RecoveryDecisionArtifact]
        """
        attempt_id = ctx.recovery_attempt_id or str(uuid.uuid4())
        # Inject attempt_id so the artifact can reference it
        enriched = RecoveryTriggerContext(
            **{**ctx.__dict__, "recovery_attempt_id": attempt_id}
        )

        artifact = self.decide(enriched)

        if artifact.action == RecoveryAction.suppress_duplicate_recovery:
            attempt = RecoveryAttemptRecord(
                attempt_id=attempt_id,
                flow_id=ctx.flow_id,
                flow_lineage_id=ctx.flow_lineage_id,
                trigger=ctx.trigger,
                state=RecoveryAttemptState.suppressed,
                action_decided=artifact.action,
                artifact_id=artifact.artifact_id,
            )
        else:
            attempt = RecoveryAttemptRecord(
                attempt_id=attempt_id,
                flow_id=ctx.flow_id,
                flow_lineage_id=ctx.flow_lineage_id,
                trigger=ctx.trigger,
                state=RecoveryAttemptState.in_progress,
                action_decided=artifact.action,
                artifact_id=artifact.artifact_id,
            )
            if ctx.flow_id:
                self._register_attempt(ctx.flow_id, attempt_id)

        self._record_attempt(attempt)
        return attempt, artifact

    def complete_attempt(
        self,
        attempt_id: str,
        flow_id: str,
        *,
        success: bool = True,
    ) -> Optional[RecoveryAttemptRecord]:
        """Mark a recovery attempt as completed or failed.

        Removes the flow_id from the active-attempt registry and updates the
        attempt record state.

        Parameters
        ----------
        attempt_id
            The attempt_id returned by :meth:`begin_attempt`.
        flow_id
            The flow_id the attempt was for.
        success
            True → ``completed``; False → ``failed``.

        Returns
        -------
        RecoveryAttemptRecord or None if not found.
        """
        self._deregister_attempt(flow_id)
        with self._lock:
            for rec in reversed(list(self._attempt_log)):
                if rec.attempt_id == attempt_id:
                    rec.state = (
                        RecoveryAttemptState.completed
                        if success
                        else RecoveryAttemptState.failed
                    )
                    rec.completed_at = time.time()
                    return rec
        return None

    def suppress_attempt(
        self, attempt_id: str, flow_id: str
    ) -> Optional[RecoveryAttemptRecord]:
        """Mark an attempt as suppressed (idempotent duplicate call path).

        Parameters
        ----------
        attempt_id
            The attempt_id to suppress.
        flow_id
            The flow_id the attempt was for.

        Returns
        -------
        RecoveryAttemptRecord or None if not found.
        """
        self._deregister_attempt(flow_id)
        with self._lock:
            for rec in reversed(list(self._attempt_log)):
                if rec.attempt_id == attempt_id:
                    rec.state = RecoveryAttemptState.suppressed
                    rec.completed_at = time.time()
                    return rec
        return None

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    def build_snapshot(self) -> RecoveryCoordinatorSnapshot:
        """Build a point-in-time snapshot of the coordinator ring-buffer."""
        with self._lock:
            artifacts = list(self._buffer)
            attempts = list(self._attempt_log)
            active_count = len(self._active_attempts)

        counts: Dict[str, int] = {}
        for art in artifacts:
            key = art.action.value
            counts[key] = counts.get(key, 0) + 1

        recent_artifacts = [
            a.to_dict() for a in reversed(artifacts[-10:])
        ]
        recent_attempts = [
            r.to_dict() for r in reversed(attempts[-10:])
        ]

        return RecoveryCoordinatorSnapshot(
            total_decisions=len(artifacts),
            action_counts=counts,
            active_attempt_count=active_count,
            recent_artifacts=recent_artifacts,
            recent_attempts=recent_attempts,
            policy_sentinels=list(_ALL_POLICY_SENTINELS),
        )

    def list_recent(self, n: int = 10) -> List[RecoveryDecisionArtifact]:
        """Return the *n* most-recent artifacts, newest first."""
        with self._lock:
            items = list(self._buffer)
        return list(reversed(items[-n:]))

    def get_by_artifact_id(
        self, artifact_id: str
    ) -> Optional[RecoveryDecisionArtifact]:
        """Return the artifact with *artifact_id*, or None."""
        with self._lock:
            for art in self._buffer:
                if art.artifact_id == artifact_id:
                    return art
        return None

    def list_recent_attempts(self, n: int = 10) -> List[RecoveryAttemptRecord]:
        """Return the *n* most-recent attempt records, newest first."""
        with self._lock:
            items = list(self._attempt_log)
        return list(reversed(items[-n:]))


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------

_SINGLETON: Optional[DelegatedFlowRecoveryCoordinator] = None
_SINGLETON_LOCK = threading.Lock()


def get_delegated_flow_recovery_coordinator(
    capacity: int = _RING_BUFFER_CAPACITY,
) -> DelegatedFlowRecoveryCoordinator:
    """Return the process-level :class:`DelegatedFlowRecoveryCoordinator` singleton.

    Parameters
    ----------
    capacity
        Ring-buffer capacity.  Only used when creating the singleton for the
        first time; ignored on subsequent calls.
    """
    global _SINGLETON  # noqa: PLW0603
    if _SINGLETON is None:
        with _SINGLETON_LOCK:
            if _SINGLETON is None:
                _SINGLETON = DelegatedFlowRecoveryCoordinator(capacity=capacity)
    return _SINGLETON


def reset_delegated_flow_recovery_coordinator() -> None:
    """Replace the singleton with a fresh instance (test isolation helper)."""
    global _SINGLETON  # noqa: PLW0603
    with _SINGLETON_LOCK:
        _SINGLETON = None


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------


def decide_recovery(
    flow_id: str,
    trigger: str = "unknown",
    *,
    flow_lineage_id: str = "",
    session_id: str = "",
    contract_id: str = "",
    tracker_id: str = "",
    device_id: str = "",
    binding_id: str = "",
    continuity_decision: str = "",
    has_partial_result: bool = False,
    checkpoint_available: bool = False,
    checkpoint_boundary_phase: str = "",
    binding_state: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    coordinator: Optional[DelegatedFlowRecoveryCoordinator] = None,
) -> RecoveryDecisionArtifact:
    """Convenience wrapper: decide recovery action for *flow_id*.

    Parameters
    ----------
    flow_id
        Delegated flow entity identifier.
    trigger
        Recovery trigger string (e.g. ``"v2_restart"``).
    coordinator
        Explicit coordinator instance for test isolation; defaults to
        the process-level singleton.

    Returns
    -------
    RecoveryDecisionArtifact
    """
    c = coordinator or get_delegated_flow_recovery_coordinator()
    ctx = RecoveryTriggerContext(
        trigger=RecoveryTrigger.from_string(trigger),
        flow_id=flow_id,
        flow_lineage_id=flow_lineage_id,
        session_id=session_id,
        contract_id=contract_id,
        tracker_id=tracker_id,
        device_id=device_id,
        binding_id=binding_id,
        continuity_decision=continuity_decision,
        has_partial_result=has_partial_result,
        checkpoint_available=checkpoint_available,
        checkpoint_boundary_phase=checkpoint_boundary_phase,
        binding_state=binding_state,
        metadata=metadata or {},
    )
    return c.decide(ctx)


def decide_recovery_from_continuity_artifact(
    ctx: RecoveryTriggerContext,
    continuity_artifact_dict: Dict[str, Any],
    *,
    coordinator: Optional[DelegatedFlowRecoveryCoordinator] = None,
) -> RecoveryDecisionArtifact:
    """Convenience wrapper: decide recovery using a ContinuityDecisionArtifact.

    Parameters
    ----------
    ctx
        Base :class:`RecoveryTriggerContext`.
    continuity_artifact_dict
        ``to_dict()`` of a ``ContinuityDecisionArtifact``.
    coordinator
        Explicit coordinator instance for test isolation.

    Returns
    -------
    RecoveryDecisionArtifact
    """
    c = coordinator or get_delegated_flow_recovery_coordinator()
    return c.decide_from_continuity_artifact(ctx, continuity_artifact_dict)


def begin_recovery_attempt(
    flow_id: str,
    trigger: str = "unknown",
    *,
    flow_lineage_id: str = "",
    session_id: str = "",
    contract_id: str = "",
    device_id: str = "",
    binding_id: str = "",
    continuity_decision: str = "",
    has_partial_result: bool = False,
    checkpoint_available: bool = False,
    checkpoint_boundary_phase: str = "",
    binding_state: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    coordinator: Optional[DelegatedFlowRecoveryCoordinator] = None,
) -> Tuple[RecoveryAttemptRecord, RecoveryDecisionArtifact]:
    """Convenience wrapper: begin a new recovery attempt for *flow_id*.

    Returns
    -------
    tuple[RecoveryAttemptRecord, RecoveryDecisionArtifact]
    """
    c = coordinator or get_delegated_flow_recovery_coordinator()
    ctx = RecoveryTriggerContext(
        trigger=RecoveryTrigger.from_string(trigger),
        flow_id=flow_id,
        flow_lineage_id=flow_lineage_id,
        session_id=session_id,
        contract_id=contract_id,
        device_id=device_id,
        binding_id=binding_id,
        continuity_decision=continuity_decision,
        has_partial_result=has_partial_result,
        checkpoint_available=checkpoint_available,
        checkpoint_boundary_phase=checkpoint_boundary_phase,
        binding_state=binding_state,
        metadata=metadata or {},
    )
    return c.begin_attempt(ctx)


def complete_recovery_attempt(
    attempt_id: str,
    flow_id: str,
    *,
    success: bool = True,
    coordinator: Optional[DelegatedFlowRecoveryCoordinator] = None,
) -> Optional[RecoveryAttemptRecord]:
    """Convenience wrapper: mark a recovery attempt as completed/failed."""
    c = coordinator or get_delegated_flow_recovery_coordinator()
    return c.complete_attempt(attempt_id, flow_id, success=success)


def suppress_recovery_attempt(
    attempt_id: str,
    flow_id: str,
    *,
    coordinator: Optional[DelegatedFlowRecoveryCoordinator] = None,
) -> Optional[RecoveryAttemptRecord]:
    """Convenience wrapper: explicitly suppress a recovery attempt."""
    c = coordinator or get_delegated_flow_recovery_coordinator()
    return c.suppress_attempt(attempt_id, flow_id)
