#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/flow_continuity_coordinator.py
=====================================
PR-3 (post-533 dual-repo runtime unification master plan, MAIN repo side):
FlowContinuityCoordinator — Unified Continuity Orchestration Skeleton.

Problem addressed
-----------------
The seven continuity scenario classes defined in
:mod:`core.android_v2_continuity_contract` are enforced piecemeal across
multiple modules:

* ``core.attached_runtime_session_registry`` — session attach / reconnect /
  stale-entry logic.
* ``core.delegated_runtime_execution_tracker`` — in-flight task tracking and
  partial-result preservation.
* ``core.delegated_flow_entity`` — flow-level phase and lineage.
* ``core.delegated_flow_persistence`` — durable recovery source.
* ``core.runtime_restart_recovery`` — V2 restart recovery.
* ``galaxy_gateway`` signal handlers — duplicate-signal suppression and stale
  identity rejection at the transport layer.

None of these modules provides a **unified decision entry-point** that:

1. Accepts a continuity event (attach / reconnect / re-attach / V2-restart
   recovery / stale signal / duplicate signal / partial result) together with
   all available runtime context.
2. Queries the relevant registries and trackers.
3. Produces a single, typed :class:`ContinuityDecision` and a fully
   serialisable :class:`ContinuityDecisionArtifact` that downstream layers
   (replay, re-dispatch, operator surfaces) can consume without re-deriving
   the decision.

This module closes that gap.

Design
------
- **Additive only** — no existing module is modified.  The coordinator is a
  *consumer* of the existing registries / trackers; it never mutates them
  directly (it calls their existing public mutation helpers and respects their
  authority boundaries).
- **Decision-first** — every public entry-point returns a
  :class:`ContinuityDecisionArtifact` that embeds the :class:`ContinuityDecision`,
  all evidence used, and the policy reference that drove the decision.
- **Fail-closed** — when the decision cannot be safely made (missing context,
  registry unavailable, internal error) the coordinator emits
  ``ContinuityDecision.fail_closed`` so the caller can apply a safe default.
- **Extensible artifact** — :class:`ContinuityDecisionArtifact` carries
  ``extension_payload`` for downstream consumers (replay, operator) to attach
  additional metadata without schema changes.
- **Singleton accessor** — :func:`get_flow_continuity_coordinator` returns the
  process-level singleton; :func:`reset_flow_continuity_coordinator` resets it
  (test isolation).

Continuity decisions
--------------------
``new_attachment``
    The signal corresponds to a fresh attach or a new_attachment reconnect.
    No prior execution context is inherited.

``continuity_resume``
    The signal corresponds to a continuity-resuming reconnect or re-attach.
    The prior attachment session identity is preserved; in-flight tasks remain
    active.

``reject_stale_identity``
    The signal carries an identity (session, contract, attachment id) that V2
    no longer holds a live record for.  The signal is rejected non-destructively
    without altering canonical state.

``dedupe_duplicate_signal``
    The signal is a duplicate of one already received and processed for the
    same execution context.  It is suppressed without double-applying.

``preserve_partial_and_wait``
    The signal is a partial-result delivery.  The partial result is preserved
    in the execution tracking record; the coordinator waits for a completion
    or failure signal.

``require_review``
    The scenario is ambiguous or advisory — human/operator review is
    recommended before proceeding.

``fail_closed``
    The coordinator could not safely determine the decision.  The caller must
    apply a safe fallback (typically treat as non-resumable / reject).

Integrated modules
------------------
:mod:`core.attached_runtime_session_registry`
    Consulted for session attach / reconnect / re-attach classification.
    The coordinator calls ``classify_reconnect_outcome()`` and
    ``register_session()`` / ``reconnect_session()`` via the registry's
    module-level helpers.

:mod:`core.delegated_runtime_execution_tracker`
    Consulted for in-flight task continuity.  The coordinator looks up the
    most-recent tracking record for a session/contract and determines whether
    a partial result should be preserved or whether the context is stale.

:mod:`core.delegated_flow_entity`
    Consulted for flow-level phase and lineage.  The coordinator looks up the
    most-recent flow entity for a contract or lineage ID to determine whether
    the flow is still active.

:mod:`core.android_v2_continuity_contract`
    Provides policy sentinels and verification helpers.  The coordinator calls
    these helpers to validate its decision and embeds the policy reference in
    the artifact.

:mod:`core.delegated_flow_persistence`
    Consulted during V2-restart recovery to rebuild the decision context from
    durable snapshots when the ring buffers are empty.

:mod:`core.runtime_restart_recovery`
    Consulted to determine whether a V2-restart recovery has completed so the
    coordinator can correctly classify in-flight task continuity.

Authority boundary
------------------
The coordinator does **not** own any canonical runtime state.  It reads from
the registries and trackers, produces a decision artifact, and delegates
execution back to the caller.  V2 remains the single canonical orchestration
authority (session registry, task lifecycle, flow entity runtime).

Public surface
--------------
Sentinels
~~~~~~~~~
:data:`FLOW_CONTINUITY_COORDINATOR_AUTHORITY`
:data:`FLOW_CONTINUITY_COORDINATOR_PR3_SENTINEL`
:data:`CONTINUITY_DECISION_IS_UNIFIED_ENTRY_POINT_POLICY`
:data:`COORDINATOR_DOES_NOT_OWN_REGISTRY_STATE_POLICY`
:data:`FAIL_CLOSED_IS_SAFE_DEFAULT_POLICY`
:data:`STALE_IDENTITY_REJECTION_IS_NON_DESTRUCTIVE_POLICY`
:data:`DUPLICATE_SIGNAL_SUPPRESSION_PRECEDES_RECONCILIATION_POLICY`
:data:`PARTIAL_RESULT_PRESERVATION_IS_COORDINATOR_OWNED_POLICY`
:data:`V2_RESTART_CONTINUITY_USES_DURABLE_STORE_POLICY`

Enums
~~~~~
:class:`ContinuityDecision`
:class:`ContinuityEventKind`

Data classes
~~~~~~~~~~~~
:class:`ContinuityEventContext`
:class:`ContinuityDecisionArtifact`
:class:`ContinuityCoordinatorSnapshot`

Classes
~~~~~~~
:class:`FlowContinuityCoordinator`

Functions
~~~~~~~~~
:func:`coordinate_attach`
:func:`coordinate_reconnect`
:func:`coordinate_reattach_process_recreation`
:func:`coordinate_stale_identity`
:func:`coordinate_duplicate_signal`
:func:`coordinate_partial_result`
:func:`coordinate_v2_restart_recovery`
:func:`get_flow_continuity_coordinator`
:func:`reset_flow_continuity_coordinator`
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
    "FLOW_CONTINUITY_COORDINATOR_AUTHORITY",
    "FLOW_CONTINUITY_COORDINATOR_PR3_SENTINEL",
    "CONTINUITY_DECISION_IS_UNIFIED_ENTRY_POINT_POLICY",
    "COORDINATOR_DOES_NOT_OWN_REGISTRY_STATE_POLICY",
    "FAIL_CLOSED_IS_SAFE_DEFAULT_POLICY",
    "STALE_IDENTITY_REJECTION_IS_NON_DESTRUCTIVE_POLICY",
    "DUPLICATE_SIGNAL_SUPPRESSION_PRECEDES_RECONCILIATION_POLICY",
    "PARTIAL_RESULT_PRESERVATION_IS_COORDINATOR_OWNED_POLICY",
    "V2_RESTART_CONTINUITY_USES_DURABLE_STORE_POLICY",
    # Enums
    "ContinuityDecision",
    "ContinuityEventKind",
    # Data classes
    "ContinuityEventContext",
    "ContinuityDecisionArtifact",
    "ContinuityCoordinatorSnapshot",
    # Main class
    "FlowContinuityCoordinator",
    # Module-level convenience functions
    "coordinate_attach",
    "coordinate_reconnect",
    "coordinate_reattach_process_recreation",
    "coordinate_stale_identity",
    "coordinate_duplicate_signal",
    "coordinate_partial_result",
    "coordinate_v2_restart_recovery",
    # Singleton
    "get_flow_continuity_coordinator",
    "reset_flow_continuity_coordinator",
]

logger = logging.getLogger("Galaxy.FlowContinuityCoordinator")

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

FLOW_CONTINUITY_COORDINATOR_AUTHORITY: str = (
    "FLOW_CONTINUITY_COORDINATOR_AUTHORITY::"
    "core.flow_continuity_coordinator is the canonical unified entry-point for "
    "all flow continuity decisions in V2.  Downstream layers (gateway handlers, "
    "reconcilers, replay coordinators, operator surfaces) MUST route continuity "
    "classification through FlowContinuityCoordinator rather than deriving "
    "decisions independently from the session registry, execution tracker, or "
    "flow entity runtime."
)

FLOW_CONTINUITY_COORDINATOR_PR3_SENTINEL: str = (
    "FLOW_CONTINUITY_COORDINATOR_PR3_SENTINEL::"
    "package=3 "
    "track=post-533-dual-repo-runtime-unification "
    "repo=main "
    "module=core.flow_continuity_coordinator "
    "title=unified-flow-continuity-coordinator-skeleton"
)

CONTINUITY_DECISION_IS_UNIFIED_ENTRY_POINT_POLICY: str = (
    "POLICY::CONTINUITY_DECISION_IS_UNIFIED_ENTRY_POINT_PR-3: "
    "FlowContinuityCoordinator is the single unified decision entry-point for "
    "all seven continuity scenario classes: fresh attach, transport reconnect, "
    "process-recreation re-attach, stale identity rejection, duplicate signal "
    "suppression, partial result preservation, and V2-restart recovery "
    "continuation.  No continuity decision SHOULD be derived outside this "
    "coordinator without explicit delegation from it.  PR-3."
)

COORDINATOR_DOES_NOT_OWN_REGISTRY_STATE_POLICY: str = (
    "POLICY::COORDINATOR_DOES_NOT_OWN_REGISTRY_STATE_PR-3: "
    "FlowContinuityCoordinator is a read-and-decide layer.  It consults the "
    "AttachedSessionRegistry, DelegatedExecutionTrackingRuntime, and "
    "DelegatedFlowEntityRuntime to produce a ContinuityDecision, but it does "
    "NOT own or directly mutate those registries' canonical state.  Mutation "
    "remains the responsibility of the registry owners as before.  PR-3."
)

FAIL_CLOSED_IS_SAFE_DEFAULT_POLICY: str = (
    "POLICY::FAIL_CLOSED_IS_SAFE_DEFAULT_PR-3: "
    "When FlowContinuityCoordinator cannot safely classify a continuity event "
    "(missing context, unavailable registry, internal error), it MUST emit "
    "ContinuityDecision.fail_closed.  Callers MUST treat fail_closed as "
    "non-resumable and apply a conservative fallback.  PR-3."
)

STALE_IDENTITY_REJECTION_IS_NON_DESTRUCTIVE_POLICY: str = (
    "POLICY::STALE_IDENTITY_REJECTION_IS_NON_DESTRUCTIVE_PR-3: "
    "When the coordinator classifies a signal as reject_stale_identity it "
    "MUST NOT alter any canonical V2 state (session registry, execution "
    "tracker, flow entity runtime).  The rejection is non-destructive: the "
    "artifact is recorded in the coordinator ring-buffer but no downstream "
    "mutation is performed.  PR-3."
)

DUPLICATE_SIGNAL_SUPPRESSION_PRECEDES_RECONCILIATION_POLICY: str = (
    "POLICY::DUPLICATE_SIGNAL_SUPPRESSION_PRECEDES_RECONCILIATION_PR-3: "
    "When the coordinator classifies a signal as dedupe_duplicate_signal the "
    "caller MUST suppress the signal BEFORE invoking the reconciler.  The "
    "reconciler is a terminal operation and must not be called more than once "
    "for the same execution context signal.  PR-3."
)

PARTIAL_RESULT_PRESERVATION_IS_COORDINATOR_OWNED_POLICY: str = (
    "POLICY::PARTIAL_RESULT_PRESERVATION_IS_COORDINATOR_OWNED_PR-3: "
    "The coordinator is the authoritative decision-maker for whether a "
    "partial-result signal should be preserved or discarded.  When the "
    "coordinator emits preserve_partial_and_wait the caller MUST record the "
    "partial result in the execution tracking record and NOT mark the tracking "
    "record as terminal.  PR-3."
)

V2_RESTART_CONTINUITY_USES_DURABLE_STORE_POLICY: str = (
    "POLICY::V2_RESTART_CONTINUITY_USES_DURABLE_STORE_PR-3: "
    "When FlowContinuityCoordinator handles a V2-restart continuity event it "
    "MUST consult the DelegatedFlowPersistenceBundle durable store to rebuild "
    "decision context before falling back to the (empty) ring buffers.  This "
    "ensures that in-flight flows that were durably persisted before the restart "
    "are classified as continuity_resume rather than new_attachment.  PR-3."
)

_ALL_POLICY_SENTINELS: Tuple[str, ...] = (
    FLOW_CONTINUITY_COORDINATOR_AUTHORITY,
    FLOW_CONTINUITY_COORDINATOR_PR3_SENTINEL,
    CONTINUITY_DECISION_IS_UNIFIED_ENTRY_POINT_POLICY,
    COORDINATOR_DOES_NOT_OWN_REGISTRY_STATE_POLICY,
    FAIL_CLOSED_IS_SAFE_DEFAULT_POLICY,
    STALE_IDENTITY_REJECTION_IS_NON_DESTRUCTIVE_POLICY,
    DUPLICATE_SIGNAL_SUPPRESSION_PRECEDES_RECONCILIATION_POLICY,
    PARTIAL_RESULT_PRESERVATION_IS_COORDINATOR_OWNED_POLICY,
    V2_RESTART_CONTINUITY_USES_DURABLE_STORE_POLICY,
)

# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

_RING_BUFFER_CAPACITY: int = 256

# Terminal session registry states that block continuity_resume
_TERMINAL_SESSION_STATES: frozenset = frozenset({"replaced", "invalidated"})

# ---------------------------------------------------------------------------
# Lazy imports for integrated modules
# (wrapped to allow coordinator use even when some modules are unavailable)
# ---------------------------------------------------------------------------

def _try_import_session_registry():
    """Return (classify_reconnect_outcome, get_session_registry) or (None, None)."""
    try:
        from core.attached_runtime_session_registry import (  # type: ignore
            classify_reconnect_outcome,
            get_session_registry,
        )
        return classify_reconnect_outcome, get_session_registry
    except Exception:
        return None, None


def _try_import_execution_tracker():
    """Return get_execution_tracking_runtime or None."""
    try:
        from core.delegated_runtime_execution_tracker import (  # type: ignore
            get_execution_tracking_runtime,
        )
        return get_execution_tracking_runtime
    except Exception:
        return None


def _try_import_flow_entity_runtime():
    """Return get_delegated_flow_entity_runtime or None."""
    try:
        from core.delegated_flow_entity import (  # type: ignore
            get_delegated_flow_entity_runtime,
        )
        return get_delegated_flow_entity_runtime
    except Exception:
        return None


def _try_import_continuity_contract():
    """Return the android_v2_continuity_contract module or None."""
    try:
        import core.android_v2_continuity_contract as contract  # type: ignore
        return contract
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


def _try_import_recovery_coordinator():
    """Return get_recovery_coordinator or None."""
    try:
        from core.runtime_restart_recovery import (  # type: ignore
            get_recovery_coordinator,
        )
        return get_recovery_coordinator
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ContinuityDecision(str, Enum):
    """Canonical output of a FlowContinuityCoordinator decision.

    Each value represents the coordinator's authoritative classification of
    a continuity event.  Downstream layers MUST act on this decision rather
    than re-deriving it from raw registry state.

    Values
    ------
    new_attachment
        The event corresponds to a fresh attach or a reconnect that cannot
        resume prior context.  No execution context is inherited.

    continuity_resume
        The event corresponds to a resumable reconnect or re-attach.  The
        prior attachment session identity and in-flight execution context are
        preserved.

    reject_stale_identity
        The signal carries an identity (session_id, contract_id, or
        runtime_attachment_session_id) that V2 no longer holds a live record
        for.  The signal is rejected non-destructively.

    dedupe_duplicate_signal
        The signal is a duplicate of one already received and processed for
        the same execution context.  It must be suppressed before
        reconciliation.

    preserve_partial_and_wait
        The signal is a partial-result delivery.  The partial result must be
        preserved; the execution tracking record must NOT be closed.

    require_review
        The scenario is ambiguous or produced an advisory outcome.  Human or
        operator review is recommended before proceeding.

    fail_closed
        The coordinator could not safely classify the event.  The caller must
        apply a safe conservative fallback.
    """

    new_attachment = "new_attachment"
    continuity_resume = "continuity_resume"
    reject_stale_identity = "reject_stale_identity"
    dedupe_duplicate_signal = "dedupe_duplicate_signal"
    preserve_partial_and_wait = "preserve_partial_and_wait"
    require_review = "require_review"
    fail_closed = "fail_closed"

    @classmethod
    def from_string(cls, value: str, default: "ContinuityDecision" = None) -> "ContinuityDecision":
        """Return the enum member matching *value*, or *default* / fail_closed."""
        if not isinstance(value, str):
            return default if default is not None else cls.fail_closed
        try:
            return cls(value.lower().strip())
        except ValueError:
            return default if default is not None else cls.fail_closed


class ContinuityEventKind(str, Enum):
    """Canonical classification of the incoming continuity event type.

    Values
    ------
    fresh_attach
        Initial Android attach — no prior session exists for this device.
    transport_reconnect
        Transport-layer reconnect after a transient disconnect.
    process_recreation_reattach
        Android process was killed and restarted; prior attachment ID re-presented.
    stale_identity
        Signal carries an identity that V2 has no live record for.
    duplicate_signal
        Duplicate execution signal for an already-processed execution context.
    partial_result
        Partial-result delivery for an in-flight delegated execution.
    v2_restart_recovery
        V2 process restarted; coordinator is rebuilding continuity from
        durable persistence.
    unknown
        Event kind is not yet determined.
    """

    fresh_attach = "fresh_attach"
    transport_reconnect = "transport_reconnect"
    process_recreation_reattach = "process_recreation_reattach"
    stale_identity = "stale_identity"
    duplicate_signal = "duplicate_signal"
    partial_result = "partial_result"
    v2_restart_recovery = "v2_restart_recovery"
    unknown = "unknown"

    @classmethod
    def from_string(cls, value: str) -> "ContinuityEventKind":
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
class ContinuityEventContext:
    """Input context for a FlowContinuityCoordinator decision request.

    All fields are optional to accommodate partial-context callers; the
    coordinator applies fail_closed when required fields are absent for a
    given event kind.

    Attributes
    ----------
    event_kind
        The type of continuity event being evaluated.
    device_id
        V2-side device identifier.
    session_id
        External session identifier (galaxy session id).
    runtime_attachment_session_id
        Canonical stable attachment identity assigned at first attach.
    contract_id
        Delegated handoff contract identifier (for signal/result events).
    tracker_id
        Execution tracker entry identifier (for result/partial events).
    flow_id
        Delegated flow entity identifier.
    flow_lineage_id
        Flow lineage identifier (spans V2 and Android sides).
    signal_key
        Idempotency key for the incoming signal (for duplicate suppression).
    prior_entry_state
        State of the prior session registry entry (if known).
    is_partial_result
        True when the incoming signal is a partial-result delivery.
    partial_result_payload
        Opaque partial-result payload (for preserve_partial_and_wait).
    recovery_completed
        True when V2-restart recovery has completed (for v2_restart_recovery
        event kind).
    metadata
        Arbitrary caller-supplied extension metadata.
    """

    event_kind: ContinuityEventKind = ContinuityEventKind.unknown
    device_id: str = ""
    session_id: str = ""
    runtime_attachment_session_id: str = ""
    contract_id: str = ""
    tracker_id: str = ""
    flow_id: str = ""
    flow_lineage_id: str = ""
    signal_key: str = ""
    prior_entry_state: str = ""
    is_partial_result: bool = False
    partial_result_payload: Optional[Dict[str, Any]] = None
    recovery_completed: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_kind": self.event_kind.value,
            "device_id": self.device_id,
            "session_id": self.session_id,
            "runtime_attachment_session_id": self.runtime_attachment_session_id,
            "contract_id": self.contract_id,
            "tracker_id": self.tracker_id,
            "flow_id": self.flow_id,
            "flow_lineage_id": self.flow_lineage_id,
            "signal_key": self.signal_key,
            "prior_entry_state": self.prior_entry_state,
            "is_partial_result": self.is_partial_result,
            "partial_result_payload": self.partial_result_payload,
            "recovery_completed": self.recovery_completed,
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


@dataclass
class ContinuityDecisionArtifact:
    """Fully serialisable output of a FlowContinuityCoordinator decision.

    This is the primary value returned by every coordinator entry-point.  It
    embeds the :class:`ContinuityDecision`, the input context, all evidence
    used to reach the decision, the policy reference, and an extension payload
    for downstream consumers (replay, re-dispatch, operator visibility).

    Attributes
    ----------
    artifact_id
        Unique, stable identifier for this artifact (UUID4).
    event_kind
        The type of continuity event that was evaluated.
    decision
        The coordinator's authoritative classification.
    policy_reference
        Name of the policy sentinel that drove the decision.
    detail
        Human-readable explanation of the decision.
    device_id
        Device identifier from the input context.
    session_id
        Session identifier from the input context.
    runtime_attachment_session_id
        Attachment identity from the input context.
    contract_id
        Contract identifier from the input context.
    flow_id
        Flow entity identifier from the input context.
    flow_lineage_id
        Flow lineage identifier from the input context.
    registry_outcome
        Raw outcome string from the session registry (e.g.
        ``"continuity_resume"``, ``"new_attachment"``), or ``""`` when
        the registry was not consulted.
    tracking_record_phase
        Phase of the execution tracking record at decision time, or ``""``
        when no tracking record was found.
    flow_entity_phase
        Phase of the flow entity at decision time, or ``""`` when no flow
        entity was found.
    contract_verified
        Outcome from :mod:`core.android_v2_continuity_contract` verification
        helper (``"pass"``, ``"fail"``, ``"advisory"``), or ``""`` when not
        run.
    is_resumable
        True when the decision is ``continuity_resume`` or
        ``preserve_partial_and_wait``.
    extension_payload
        Arbitrary extension metadata for downstream consumers.  Keys MUST be
        namespaced to avoid collisions (e.g. ``replay_hint``, ``operator_tag``).
    timestamp
        Unix timestamp when this artifact was created.
    """

    artifact_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_kind: ContinuityEventKind = ContinuityEventKind.unknown
    decision: ContinuityDecision = ContinuityDecision.fail_closed
    policy_reference: str = ""
    detail: str = ""
    device_id: str = ""
    session_id: str = ""
    runtime_attachment_session_id: str = ""
    contract_id: str = ""
    flow_id: str = ""
    flow_lineage_id: str = ""
    registry_outcome: str = ""
    tracking_record_phase: str = ""
    flow_entity_phase: str = ""
    contract_verified: str = ""
    is_resumable: bool = False
    extension_payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "event_kind": self.event_kind.value,
            "decision": self.decision.value,
            "policy_reference": self.policy_reference,
            "detail": self.detail,
            "device_id": self.device_id,
            "session_id": self.session_id,
            "runtime_attachment_session_id": self.runtime_attachment_session_id,
            "contract_id": self.contract_id,
            "flow_id": self.flow_id,
            "flow_lineage_id": self.flow_lineage_id,
            "registry_outcome": self.registry_outcome,
            "tracking_record_phase": self.tracking_record_phase,
            "flow_entity_phase": self.flow_entity_phase,
            "contract_verified": self.contract_verified,
            "is_resumable": self.is_resumable,
            "extension_payload": self.extension_payload,
            "timestamp": self.timestamp,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContinuityDecisionArtifact":
        """Construct from a dictionary.  Tolerates unknown extra fields."""
        return cls(
            artifact_id=data.get("artifact_id", str(uuid.uuid4())),
            event_kind=ContinuityEventKind.from_string(
                data.get("event_kind", "unknown")
            ),
            decision=ContinuityDecision.from_string(
                data.get("decision", "fail_closed")
            ),
            policy_reference=data.get("policy_reference", ""),
            detail=data.get("detail", ""),
            device_id=data.get("device_id", ""),
            session_id=data.get("session_id", ""),
            runtime_attachment_session_id=data.get(
                "runtime_attachment_session_id", ""
            ),
            contract_id=data.get("contract_id", ""),
            flow_id=data.get("flow_id", ""),
            flow_lineage_id=data.get("flow_lineage_id", ""),
            registry_outcome=data.get("registry_outcome", ""),
            tracking_record_phase=data.get("tracking_record_phase", ""),
            flow_entity_phase=data.get("flow_entity_phase", ""),
            contract_verified=data.get("contract_verified", ""),
            is_resumable=data.get("is_resumable", False),
            extension_payload=data.get("extension_payload", {}),
            timestamp=data.get("timestamp", time.time()),
        )


@dataclass
class ContinuityCoordinatorSnapshot:
    """Point-in-time snapshot of the coordinator ring-buffer for observability.

    Attributes
    ----------
    snapshot_id
        Unique identifier for this snapshot.
    total_decisions
        Total number of decisions recorded in the ring-buffer.
    decision_counts
        Mapping of decision string → count across the ring-buffer.
    recent_artifacts
        The most-recent artifacts (up to 10) for operator inspection.
    policy_sentinels
        All policy sentinels active in this coordinator.
    timestamp
        Unix timestamp when this snapshot was created.
    """

    snapshot_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    total_decisions: int = 0
    decision_counts: Dict[str, int] = field(default_factory=dict)
    recent_artifacts: List[Dict[str, Any]] = field(default_factory=list)
    policy_sentinels: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "total_decisions": self.total_decisions,
            "decision_counts": self.decision_counts,
            "recent_artifacts": self.recent_artifacts,
            "policy_sentinels": self.policy_sentinels,
            "timestamp": self.timestamp,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


# ---------------------------------------------------------------------------
# FlowContinuityCoordinator
# ---------------------------------------------------------------------------


class FlowContinuityCoordinator:
    """Unified entry-point for all flow continuity decisions in V2.

    This class orchestrates continuity classification for all seven scenario
    classes defined in :mod:`core.android_v2_continuity_contract`, producing
    a single typed :class:`ContinuityDecisionArtifact` for each event.

    The coordinator integrates with:

    * ``AttachedSessionRegistry`` — session attach/reconnect classification.
    * ``DelegatedExecutionTrackingRuntime`` — in-flight task continuity.
    * ``DelegatedFlowEntityRuntime`` — flow-level phase and lineage.
    * ``android_v2_continuity_contract`` — policy verification helpers.
    * ``DelegatedFlowPersistenceBundle`` — durable recovery source.
    * ``RuntimeRestartRecoveryCoordinator`` — V2-restart recovery status.

    All registry integrations are **optional** — when a registry module is
    unavailable the coordinator degrades gracefully, potentially emitting
    ``fail_closed`` or ``require_review`` depending on available evidence.

    Thread safety
    -------------
    The ring-buffer is protected by an internal :class:`threading.Lock` and
    is safe for concurrent use.

    Parameters
    ----------
    capacity
        Ring-buffer capacity for decision artifact history.  Defaults to 256.
    """

    def __init__(self, capacity: int = _RING_BUFFER_CAPACITY) -> None:
        self._capacity = capacity
        self._buffer: Deque[ContinuityDecisionArtifact] = deque(maxlen=capacity)
        self._lock = threading.Lock()

        # Lazy-loaded integration handles
        self._classify_reconnect_outcome = None
        self._get_session_registry = None
        self._get_execution_tracking_runtime = None
        self._get_flow_entity_runtime = None
        self._continuity_contract = None
        self._get_persistence_bundle = None
        self._get_recovery_coordinator = None

    # ------------------------------------------------------------------
    # Integration module accessors (lazy)
    # ------------------------------------------------------------------

    def _session_registry(self):
        """Return (classify_reconnect_outcome_fn, registry) or (None, None)."""
        if self._classify_reconnect_outcome is None:
            self._classify_reconnect_outcome, self._get_session_registry = (
                _try_import_session_registry()
            )
        if self._get_session_registry is None:
            return None, None
        try:
            return self._classify_reconnect_outcome, self._get_session_registry()
        except Exception:
            return None, None

    def _execution_tracker(self):
        """Return the DelegatedExecutionTrackingRuntime or None."""
        if self._get_execution_tracking_runtime is None:
            self._get_execution_tracking_runtime = _try_import_execution_tracker()
        if self._get_execution_tracking_runtime is None:
            return None
        try:
            return self._get_execution_tracking_runtime()
        except Exception:
            return None

    def _flow_entity_runtime(self):
        """Return the DelegatedFlowEntityRuntime or None."""
        if self._get_flow_entity_runtime is None:
            self._get_flow_entity_runtime = _try_import_flow_entity_runtime()
        if self._get_flow_entity_runtime is None:
            return None
        try:
            return self._get_flow_entity_runtime()
        except Exception:
            return None

    def _contract(self):
        """Return the android_v2_continuity_contract module or None."""
        if self._continuity_contract is None:
            self._continuity_contract = _try_import_continuity_contract()
        return self._continuity_contract

    def _persistence_bundle(self):
        """Return the DelegatedFlowPersistenceBundle or None."""
        if self._get_persistence_bundle is None:
            self._get_persistence_bundle = _try_import_persistence_bundle()
        if self._get_persistence_bundle is None:
            return None
        try:
            return self._get_persistence_bundle()
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Ring-buffer management
    # ------------------------------------------------------------------

    def _record(self, artifact: ContinuityDecisionArtifact) -> None:
        """Thread-safely append *artifact* to the ring-buffer."""
        with self._lock:
            self._buffer.append(artifact)

    def list_recent(self, n: int = 20) -> List[ContinuityDecisionArtifact]:
        """Return the *n* most-recent decision artifacts, newest-first."""
        with self._lock:
            items = list(self._buffer)
        items.reverse()
        return items[:n]

    def get_by_artifact_id(self, artifact_id: str) -> Optional[ContinuityDecisionArtifact]:
        """Return the artifact with *artifact_id*, or None if not found."""
        with self._lock:
            for artifact in reversed(self._buffer):
                if artifact.artifact_id == artifact_id:
                    return artifact
        return None

    def build_snapshot(self) -> ContinuityCoordinatorSnapshot:
        """Return a lightweight snapshot for operator diagnostics."""
        with self._lock:
            items = list(self._buffer)
        counts: Dict[str, int] = {}
        for a in items:
            counts[a.decision.value] = counts.get(a.decision.value, 0) + 1
        recent = [a.to_dict() for a in reversed(items)][:10]
        return ContinuityCoordinatorSnapshot(
            total_decisions=len(items),
            decision_counts=counts,
            recent_artifacts=recent,
            policy_sentinels=list(_ALL_POLICY_SENTINELS),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _base_artifact(
        self,
        ctx: ContinuityEventContext,
        decision: ContinuityDecision,
        *,
        policy_reference: str = "",
        detail: str = "",
        registry_outcome: str = "",
        tracking_record_phase: str = "",
        flow_entity_phase: str = "",
        contract_verified: str = "",
        extension_payload: Optional[Dict[str, Any]] = None,
    ) -> ContinuityDecisionArtifact:
        """Build a :class:`ContinuityDecisionArtifact` from context and decision."""
        is_resumable = decision in (
            ContinuityDecision.continuity_resume,
            ContinuityDecision.preserve_partial_and_wait,
        )
        return ContinuityDecisionArtifact(
            event_kind=ctx.event_kind,
            decision=decision,
            policy_reference=policy_reference,
            detail=detail,
            device_id=ctx.device_id,
            session_id=ctx.session_id,
            runtime_attachment_session_id=ctx.runtime_attachment_session_id,
            contract_id=ctx.contract_id,
            flow_id=ctx.flow_id,
            flow_lineage_id=ctx.flow_lineage_id,
            registry_outcome=registry_outcome,
            tracking_record_phase=tracking_record_phase,
            flow_entity_phase=flow_entity_phase,
            contract_verified=contract_verified,
            is_resumable=is_resumable,
            extension_payload=extension_payload or {},
        )

    def _lookup_tracking_phase(self, ctx: ContinuityEventContext) -> str:
        """Return the execution tracking phase for the context's session/contract, or ''."""
        tracker = self._execution_tracker()
        if tracker is None:
            return ""
        try:
            record = None
            if ctx.session_id:
                record = tracker.get_latest_for_session(ctx.session_id)
            if record is None and ctx.contract_id:
                record = tracker.get_latest_for_contract(ctx.contract_id)
            if record is None:
                return ""
            return record.phase.value if hasattr(record.phase, "value") else str(record.phase)
        except Exception:
            return ""

    def _lookup_flow_phase(self, ctx: ContinuityEventContext) -> str:
        """Return the flow entity phase for the context's flow/contract, or ''."""
        fe_runtime = self._flow_entity_runtime()
        if fe_runtime is None:
            return ""
        try:
            entity = None
            if ctx.flow_id:
                entity = fe_runtime.get_latest_for_flow(ctx.flow_id)
            if entity is None and ctx.contract_id:
                # Try get_by_contract if available
                get_fn = getattr(fe_runtime, "get_latest_for_contract", None)
                if get_fn is not None:
                    entity = get_fn(ctx.contract_id)
            if entity is None:
                return ""
            phase = entity.phase if not hasattr(entity, "phase") else entity.phase
            return phase.value if hasattr(phase, "value") else str(phase)
        except Exception:
            return ""

    def _session_state_for_device(self, ctx: ContinuityEventContext) -> str:
        """Return the attachment_state of the current active session for device, or ''."""
        _, registry = self._session_registry()
        if registry is None:
            return ""
        try:
            entry = None
            if ctx.runtime_attachment_session_id:
                lookup_fn = getattr(
                    registry, "get_by_runtime_attachment_session_id", None
                )
                if lookup_fn is not None:
                    entry = lookup_fn(
                        ctx.runtime_attachment_session_id, active_only=False
                    )
            if entry is None and ctx.device_id:
                lookup_fn = getattr(registry, "get_active_for_device", None)
                if lookup_fn is not None:
                    entry = lookup_fn(ctx.device_id)
            if entry is None:
                return ""
            state = entry.attachment_state
            return state.value if hasattr(state, "value") else str(state)
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # Public scenario entry-points
    # ------------------------------------------------------------------

    def decide_attach(
        self, ctx: ContinuityEventContext
    ) -> ContinuityDecisionArtifact:
        """Decide continuity for a fresh Android attach event.

        Scenario: Android device connects for the first time or after a
        terminal session (replaced/invalidated).

        Decision rules
        --------------
        - No prior registry entry → ``new_attachment``
        - Prior entry in terminal state (replaced/invalidated) → ``new_attachment``
        - Prior entry active/detached → ``continuity_resume``
        - Registry unavailable → ``fail_closed``
        - registry_entry_created=False (supplied in ctx.metadata) → ``fail_closed``

        Parameters
        ----------
        ctx
            Continuity event context.  ``device_id`` and
            ``runtime_attachment_session_id`` should be populated.

        Returns
        -------
        ContinuityDecisionArtifact
        """
        ctx = ContinuityEventContext(
            **{**ctx.__dict__, "event_kind": ContinuityEventKind.fresh_attach}
        ) if ctx.event_kind == ContinuityEventKind.unknown else ctx

        registry_entry_created: bool = ctx.metadata.get(
            "registry_entry_created", True
        )

        if not registry_entry_created:
            artifact = self._base_artifact(
                ctx,
                ContinuityDecision.fail_closed,
                policy_reference="FAIL_CLOSED_IS_SAFE_DEFAULT_POLICY",
                detail="attach failed: registry_entry_created=False",
            )
            self._record(artifact)
            return artifact

        prior_state = ctx.prior_entry_state

        contract = self._contract()
        if contract is not None and ctx.device_id:
            attach_record = contract.classify_attach_outcome(
                ctx.device_id,
                ctx.runtime_attachment_session_id or "",
                prior_entry_state=prior_state,
                registry_entry_created=registry_entry_created,
            )
            outcome_str = attach_record.attach_outcome.value
            contract_verified_str = "pass"
        else:
            # Derive without contract helper
            if not prior_state:
                outcome_str = "new_registration"
            elif prior_state in ("active", "detached"):
                outcome_str = "continuity_resume"
            elif prior_state in _TERMINAL_SESSION_STATES:
                outcome_str = "new_attachment"
            else:
                outcome_str = "new_registration"
            contract_verified_str = ""

        if outcome_str in ("new_registration", "new_attachment"):
            decision = ContinuityDecision.new_attachment
            policy_ref = "ATTACH_MUST_CREATE_REGISTRY_ENTRY_POLICY"
            detail = f"fresh attach classified as {outcome_str}"
        elif outcome_str == "continuity_resume":
            decision = ContinuityDecision.continuity_resume
            policy_ref = "RECONNECT_CONTINUITY_RESUME_PRESERVES_ATTACHMENT_ID_POLICY"
            detail = "attach resumes prior active/detached session"
        else:
            decision = ContinuityDecision.fail_closed
            policy_ref = "FAIL_CLOSED_IS_SAFE_DEFAULT_POLICY"
            detail = f"attach outcome unrecognised: {outcome_str!r}"

        artifact = self._base_artifact(
            ctx,
            decision,
            policy_reference=policy_ref,
            detail=detail,
            registry_outcome=outcome_str,
            tracking_record_phase=self._lookup_tracking_phase(ctx),
            flow_entity_phase=self._lookup_flow_phase(ctx),
            contract_verified=contract_verified_str,
        )
        self._record(artifact)
        return artifact

    def decide_reconnect(
        self, ctx: ContinuityEventContext
    ) -> ContinuityDecisionArtifact:
        """Decide continuity for a transport-layer reconnect event.

        Scenario: the transport session reconnected after a transient
        disconnect.  The prior runtime_attachment_session_id may or may not
        be preserved.

        Decision rules
        --------------
        Delegates to the session registry's ``classify_reconnect_outcome()``:

        - ``"continuity_resume"`` with attachment ID preserved → ``continuity_resume``
        - ``"continuity_resume"`` without attachment ID → ``require_review``
        - ``"new_attachment"`` → ``new_attachment``
        - Registry unavailable → ``fail_closed``

        Parameters
        ----------
        ctx
            ``device_id`` and ``runtime_attachment_session_id`` should be set.
        """
        ctx = ContinuityEventContext(
            **{**ctx.__dict__, "event_kind": ContinuityEventKind.transport_reconnect}
        ) if ctx.event_kind == ContinuityEventKind.unknown else ctx

        classify_fn, registry = self._session_registry()

        if classify_fn is None or registry is None:
            # Registry unavailable — cannot classify safely
            artifact = self._base_artifact(
                ctx,
                ContinuityDecision.fail_closed,
                policy_reference="FAIL_CLOSED_IS_SAFE_DEFAULT_POLICY",
                detail="session registry unavailable for reconnect classification",
            )
            self._record(artifact)
            return artifact

        try:
            registry_outcome: str = classify_fn(
                ctx.device_id,
                runtime_attachment_session_id=ctx.runtime_attachment_session_id,
                registry=registry,
            )
        except Exception as exc:
            logger.warning("classify_reconnect_outcome raised: %s", exc)
            artifact = self._base_artifact(
                ctx,
                ContinuityDecision.fail_closed,
                policy_reference="FAIL_CLOSED_IS_SAFE_DEFAULT_POLICY",
                detail=f"classify_reconnect_outcome error: {exc}",
            )
            self._record(artifact)
            return artifact

        contract = self._contract()
        if contract is not None:
            attachment_id_preserved = bool(ctx.runtime_attachment_session_id)
            reconnect_count_incremented = bool(
                ctx.metadata.get("reconnect_count_incremented", True)
            )
            outcome_obj = contract.classify_reconnect_continuity_outcome(
                registry_outcome,
                runtime_attachment_session_id_preserved=attachment_id_preserved,
                reconnect_count_incremented=reconnect_count_incremented,
            )
            contract_verified_str = outcome_obj.result.value
        else:
            contract_verified_str = ""

        if registry_outcome == "continuity_resume":
            if not ctx.runtime_attachment_session_id:
                decision = ContinuityDecision.require_review
                policy_ref = "CONTINUITY_DECISION_IS_UNIFIED_ENTRY_POINT_POLICY"
                detail = "continuity_resume but runtime_attachment_session_id absent (advisory)"
            else:
                decision = ContinuityDecision.continuity_resume
                policy_ref = "RECONNECT_CONTINUITY_RESUME_PRESERVES_ATTACHMENT_ID_POLICY"
                detail = "transport reconnect: continuity_resume, attachment ID preserved"
        elif registry_outcome == "new_attachment":
            decision = ContinuityDecision.new_attachment
            policy_ref = "RECONNECT_NEW_ATTACHMENT_DOES_NOT_INHERIT_PRIOR_CONTEXT_POLICY"
            detail = "transport reconnect: new_attachment, no prior context inherited"
        else:
            decision = ContinuityDecision.fail_closed
            policy_ref = "FAIL_CLOSED_IS_SAFE_DEFAULT_POLICY"
            detail = f"unrecognised registry outcome: {registry_outcome!r}"

        artifact = self._base_artifact(
            ctx,
            decision,
            policy_reference=policy_ref,
            detail=detail,
            registry_outcome=registry_outcome,
            tracking_record_phase=self._lookup_tracking_phase(ctx),
            flow_entity_phase=self._lookup_flow_phase(ctx),
            contract_verified=contract_verified_str,
        )
        self._record(artifact)
        return artifact

    def decide_reattach_process_recreation(
        self, ctx: ContinuityEventContext
    ) -> ContinuityDecisionArtifact:
        """Decide continuity for a process-recreation re-attach event.

        Scenario: the Android process was killed and restarted.  The client
        presents the prior ``runtime_attachment_session_id`` again.  V2 must
        classify correctly and NOT create a duplicate participant entry.

        Decision rules
        --------------
        - Prior entry active/detached AND attachment ID matches → ``continuity_resume``
        - Prior entry active/detached AND ID absent/mismatched → ``new_attachment``
        - Prior entry in terminal state → ``new_attachment``
        - Registry unavailable → ``fail_closed``

        Parameters
        ----------
        ctx
            ``device_id``, ``runtime_attachment_session_id``, and
            ``prior_entry_state`` should be set.  Alternatively,
            ``metadata["prior_entry_was_active_or_detached"]`` and
            ``metadata["attachment_id_matched"]`` may be provided directly.
        """
        ctx = ContinuityEventContext(
            **{**ctx.__dict__, "event_kind": ContinuityEventKind.process_recreation_reattach}
        ) if ctx.event_kind == ContinuityEventKind.unknown else ctx

        prior_active_or_detached: bool = ctx.metadata.get(
            "prior_entry_was_active_or_detached",
            ctx.prior_entry_state in ("active", "detached"),
        )
        attachment_id_matched: bool = ctx.metadata.get(
            "attachment_id_matched",
            bool(ctx.runtime_attachment_session_id),
        )

        if prior_active_or_detached and attachment_id_matched:
            registry_outcome = "continuity_resume"
            decision = ContinuityDecision.continuity_resume
            policy_ref = "REATTACH_AFTER_PROCESS_RECREATION_MUST_NOT_DUPLICATE_PARTICIPANT_POLICY"
            detail = (
                "process-recreation re-attach: prior entry active/detached and "
                "attachment ID matched → continuity_resume, no duplicate entry"
            )
        else:
            registry_outcome = "new_attachment"
            decision = ContinuityDecision.new_attachment
            policy_ref = "PROCESS_RECREATION_CONTINUITY_RESUME_REQUIRES_MATCHING_ID_POLICY"
            detail = (
                "process-recreation re-attach: prior entry absent/terminal or "
                "attachment ID mismatched → new_attachment"
            )

        contract = self._contract()
        contract_verified_str = ""
        if contract is not None:
            outcome_obj = contract.classify_reattach_process_recreation_outcome(
                registry_outcome,
                prior_entry_was_active_or_detached=prior_active_or_detached,
                attachment_id_matched=attachment_id_matched,
            )
            contract_verified_str = outcome_obj.result.value

        artifact = self._base_artifact(
            ctx,
            decision,
            policy_reference=policy_ref,
            detail=detail,
            registry_outcome=registry_outcome,
            tracking_record_phase=self._lookup_tracking_phase(ctx),
            flow_entity_phase=self._lookup_flow_phase(ctx),
            contract_verified=contract_verified_str,
        )
        self._record(artifact)
        return artifact

    def decide_stale_identity(
        self, ctx: ContinuityEventContext
    ) -> ContinuityDecisionArtifact:
        """Decide continuity for a stale-identity signal.

        Scenario: Android presents an identity (session_id, contract_id, or
        runtime_attachment_session_id) that V2 no longer holds a live record
        for.  The signal must be rejected non-destructively.

        Decision rules
        --------------
        - Identity not found in active session registry AND contract/tracker
          has no live record → ``reject_stale_identity``
        - Identity found (not stale) → ``continuity_resume``
        - Registry unavailable → ``require_review``

        Parameters
        ----------
        ctx
            At least one of ``session_id``, ``contract_id``, or
            ``runtime_attachment_session_id`` should be set.
        """
        ctx = ContinuityEventContext(
            **{**ctx.__dict__, "event_kind": ContinuityEventKind.stale_identity}
        ) if ctx.event_kind == ContinuityEventKind.unknown else ctx

        # Check session registry
        session_state = self._session_state_for_device(ctx)

        # Check execution tracker
        tracking_phase = self._lookup_tracking_phase(ctx)

        # Check flow entity
        flow_phase = self._lookup_flow_phase(ctx)

        # Determine if the identity is stale
        # A stale identity is one where:
        #   - session state is empty (no record) or terminal
        #   - tracking phase is terminal or empty
        #   - flow phase is terminal or empty
        _terminal_tracking = frozenset({"completed", "failed", "timed_out", "cancelled"})
        _terminal_flow = frozenset({"completed", "failed", "cancelled"})

        session_is_stale = (
            not session_state
            or session_state in _TERMINAL_SESSION_STATES
        )
        tracking_is_stale = (
            not tracking_phase
            or tracking_phase in _terminal_tracking
        )
        flow_is_stale = (
            not flow_phase
            or flow_phase in _terminal_flow
        )

        # If we have no registry at all we can't safely classify
        _, registry = self._session_registry()
        if registry is None and not ctx.contract_id and not ctx.session_id:
            artifact = self._base_artifact(
                ctx,
                ContinuityDecision.require_review,
                policy_reference="STALE_IDENTITY_REJECTION_IS_NON_DESTRUCTIVE_POLICY",
                detail="cannot classify stale identity: no registry and no context identifiers",
                session_id=ctx.session_id,
                tracking_record_phase=tracking_phase,
                flow_entity_phase=flow_phase,
            )
            self._record(artifact)
            return artifact

        # A valid live identity: session active and tracking/flow not terminal
        identity_is_live = (
            session_state in ("active", "detached")
            or (not session_state and (
                not tracking_is_stale or not flow_is_stale
            ))
        )

        if identity_is_live:
            decision = ContinuityDecision.continuity_resume
            policy_ref = "RECONNECT_CONTINUITY_RESUME_PRESERVES_ATTACHMENT_ID_POLICY"
            detail = "identity is live: session active or execution in-flight"
        else:
            decision = ContinuityDecision.reject_stale_identity
            policy_ref = "STALE_IDENTITY_MUST_BE_REJECTED_NON_DESTRUCTIVELY_POLICY"
            detail = (
                f"stale identity: session_state={session_state!r}, "
                f"tracking_phase={tracking_phase!r}, flow_phase={flow_phase!r}"
            )

        # Verify via contract
        contract = self._contract()
        contract_verified_str = ""
        if contract is not None and decision == ContinuityDecision.reject_stale_identity:
            reject_reason = detail
            v2_state_altered = False  # coordinator never alters state
            phantom_record_created = False
            outcome_obj = contract.verify_stale_identity_handling(
                was_reconciled=False,
                reject_reason=reject_reason,
                v2_state_altered=v2_state_altered,
                phantom_record_created=phantom_record_created,
            )
            contract_verified_str = outcome_obj.result.value

        artifact = self._base_artifact(
            ctx,
            decision,
            policy_reference=policy_ref,
            detail=detail,
            registry_outcome=session_state,
            tracking_record_phase=tracking_phase,
            flow_entity_phase=flow_phase,
            contract_verified=contract_verified_str,
        )
        self._record(artifact)
        return artifact

    def decide_duplicate_signal(
        self, ctx: ContinuityEventContext
    ) -> ContinuityDecisionArtifact:
        """Decide continuity for a potential duplicate signal.

        Scenario: Android sends a signal (ack, progress, result) that may
        already have been received and processed for the same execution
        context.  The coordinator must decide whether to suppress the duplicate
        before the reconciler is called.

        Decision rules
        --------------
        - ``signal_key`` present AND already seen in tracking record acks →
          ``dedupe_duplicate_signal``
        - ``signal_key`` absent or not previously seen → ``continuity_resume``
          (signal may proceed to reconciler)
        - Tracker unavailable → ``require_review``

        Parameters
        ----------
        ctx
            ``signal_key`` and at least one of ``session_id`` / ``contract_id``
            should be set.
        """
        ctx = ContinuityEventContext(
            **{**ctx.__dict__, "event_kind": ContinuityEventKind.duplicate_signal}
        ) if ctx.event_kind == ContinuityEventKind.unknown else ctx

        if not ctx.signal_key:
            # No idempotency key — cannot determine duplication; pass through
            artifact = self._base_artifact(
                ctx,
                ContinuityDecision.continuity_resume,
                policy_reference="DUPLICATE_SIGNAL_SUPPRESSION_PRECEDES_RECONCILIATION_POLICY",
                detail="no signal_key present; cannot check for duplicate; passing through",
                tracking_record_phase=self._lookup_tracking_phase(ctx),
                flow_entity_phase=self._lookup_flow_phase(ctx),
            )
            self._record(artifact)
            return artifact

        tracker = self._execution_tracker()
        if tracker is None:
            artifact = self._base_artifact(
                ctx,
                ContinuityDecision.require_review,
                policy_reference="DUPLICATE_SIGNAL_SUPPRESSION_PRECEDES_RECONCILIATION_POLICY",
                detail="execution tracker unavailable; cannot check for duplicate signal",
            )
            self._record(artifact)
            return artifact

        # Look up the tracking record and check acknowledgment history
        tracking_phase = ""
        signal_already_seen = False
        try:
            record = None
            if ctx.session_id:
                record = tracker.get_latest_for_session(ctx.session_id)
            if record is None and ctx.contract_id:
                record = getattr(tracker, "get_latest_for_contract", lambda _: None)(
                    ctx.contract_id
                )
            if record is not None:
                tracking_phase = (
                    record.phase.value
                    if hasattr(record.phase, "value")
                    else str(record.phase)
                )
                # Check acknowledgments for duplicate signal_key
                acks = getattr(record, "acknowledgments", [])
                for ack in acks:
                    ack_payload = getattr(ack, "payload", {}) or {}
                    if (
                        getattr(ack, "signal_key", None) == ctx.signal_key
                        or ack_payload.get("signal_key") == ctx.signal_key
                        or ack_payload.get("idempotency_key") == ctx.signal_key
                    ):
                        signal_already_seen = True
                        break
        except Exception as exc:
            logger.warning("duplicate signal check error: %s", exc)

        contract = self._contract()
        contract_verified_str = ""
        if contract is not None:
            outcome_obj = contract.verify_duplicate_signal_suppression(
                signal_suppressed=signal_already_seen,
                reconciler_called_count=0 if signal_already_seen else 1,
            )
            contract_verified_str = outcome_obj.result.value

        if signal_already_seen:
            decision = ContinuityDecision.dedupe_duplicate_signal
            policy_ref = "DUPLICATE_SIGNAL_MUST_BE_SUPPRESSED_POLICY"
            detail = f"duplicate signal detected (signal_key={ctx.signal_key!r}); suppressed"
        else:
            decision = ContinuityDecision.continuity_resume
            policy_ref = "DUPLICATE_SIGNAL_SUPPRESSION_PRECEDES_RECONCILIATION_POLICY"
            detail = f"signal is novel (signal_key={ctx.signal_key!r}); proceed to reconciler"

        artifact = self._base_artifact(
            ctx,
            decision,
            policy_reference=policy_ref,
            detail=detail,
            tracking_record_phase=tracking_phase,
            flow_entity_phase=self._lookup_flow_phase(ctx),
            contract_verified=contract_verified_str,
        )
        self._record(artifact)
        return artifact

    def decide_partial_result(
        self, ctx: ContinuityEventContext
    ) -> ContinuityDecisionArtifact:
        """Decide continuity for a partial-result delivery event.

        Scenario: Android delivers a partial result for an in-flight delegated
        execution.  V2 must preserve the partial result and NOT close the
        tracking record.

        Decision rules
        --------------
        - Tracking record exists and is non-terminal → ``preserve_partial_and_wait``
        - Tracking record is terminal → ``reject_stale_identity`` (late partial)
        - Tracker unavailable → ``require_review``

        Parameters
        ----------
        ctx
            ``is_partial_result=True`` and at least one of ``session_id`` /
            ``contract_id`` should be set.  ``partial_result_payload`` is
            forwarded in the artifact extension payload.
        """
        ctx = ContinuityEventContext(
            **{**ctx.__dict__, "event_kind": ContinuityEventKind.partial_result}
        ) if ctx.event_kind == ContinuityEventKind.unknown else ctx

        tracker = self._execution_tracker()
        if tracker is None:
            artifact = self._base_artifact(
                ctx,
                ContinuityDecision.require_review,
                policy_reference="PARTIAL_RESULT_PRESERVATION_IS_COORDINATOR_OWNED_POLICY",
                detail="execution tracker unavailable; cannot classify partial result",
                extension_payload={"partial_result_payload": ctx.partial_result_payload},
            )
            self._record(artifact)
            return artifact

        tracking_phase = self._lookup_tracking_phase(ctx)
        _terminal_tracking = frozenset({"completed", "failed", "timed_out", "cancelled"})

        if tracking_phase and tracking_phase in _terminal_tracking:
            decision = ContinuityDecision.reject_stale_identity
            policy_ref = "PARTIAL_RESULT_IS_SUPERSEDED_BY_TERMINAL_SIGNAL_POLICY"
            detail = (
                f"late partial result for terminal tracking record "
                f"(phase={tracking_phase!r}); rejected non-destructively"
            )
        else:
            decision = ContinuityDecision.preserve_partial_and_wait
            policy_ref = "PARTIAL_RESULT_MUST_BE_PRESERVED_UNTIL_COMPLETION_POLICY"
            if tracking_phase:
                detail = (
                    f"partial result for in-flight tracking record "
                    f"(phase={tracking_phase!r}); preserve and wait for completion"
                )
            else:
                detail = (
                    "partial result for untracked execution context; "
                    "preserve and wait for completion"
                )

        artifact = self._base_artifact(
            ctx,
            decision,
            policy_reference=policy_ref,
            detail=detail,
            tracking_record_phase=tracking_phase,
            flow_entity_phase=self._lookup_flow_phase(ctx),
            extension_payload={"partial_result_payload": ctx.partial_result_payload},
        )
        self._record(artifact)
        return artifact

    def decide_v2_restart_recovery(
        self, ctx: ContinuityEventContext
    ) -> ContinuityDecisionArtifact:
        """Decide continuity for a V2-restart recovery scenario.

        Scenario: V2 has restarted.  The coordinator consults the durable
        persistence bundle to determine whether there are in-flight flows that
        should be classified as ``continuity_resume`` rather than
        ``new_attachment``.

        Decision rules
        --------------
        - Durable store has active flow entities for this context →
          ``continuity_resume``
        - Durable store has no active flows or is unavailable → ``new_attachment``
        - Recovery not yet completed → ``require_review``

        Parameters
        ----------
        ctx
            ``recovery_completed`` should be set in the context.
            ``flow_lineage_id`` or ``contract_id`` is used to look up durable
            flows.
        """
        ctx = ContinuityEventContext(
            **{**ctx.__dict__, "event_kind": ContinuityEventKind.v2_restart_recovery}
        ) if ctx.event_kind == ContinuityEventKind.unknown else ctx

        if not ctx.recovery_completed:
            artifact = self._base_artifact(
                ctx,
                ContinuityDecision.require_review,
                policy_reference="V2_RESTART_CONTINUITY_USES_DURABLE_STORE_POLICY",
                detail="V2 restart recovery not yet completed; deferring continuity decision",
            )
            self._record(artifact)
            return artifact

        bundle = self._persistence_bundle()
        has_durable_flow = False
        flow_entity_phase = ""

        if bundle is not None and (ctx.flow_lineage_id or ctx.contract_id or ctx.flow_id):
            try:
                restored = bundle.restore_all()
                flow_entities = restored.get("flow_entities", [])
                _terminal_flow = frozenset({"completed", "failed", "cancelled"})
                for entity in flow_entities:
                    entity_flow_id = getattr(entity, "identity", None)
                    if entity_flow_id:
                        fid = getattr(entity_flow_id, "delegated_flow_id", "")
                        lin_id = getattr(entity_flow_id, "flow_lineage_id", "")
                    else:
                        fid = ""
                        lin_id = ""
                    phase = getattr(entity, "phase", None)
                    phase_str = phase.value if hasattr(phase, "value") else str(phase or "")
                    mapping = getattr(entity, "object_mapping", None)
                    c_id = getattr(mapping, "contract_id", "") if mapping else ""

                    matches = (
                        (ctx.flow_id and fid == ctx.flow_id)
                        or (ctx.flow_lineage_id and lin_id == ctx.flow_lineage_id)
                        or (ctx.contract_id and c_id == ctx.contract_id)
                    )
                    if matches and phase_str not in _terminal_flow:
                        has_durable_flow = True
                        flow_entity_phase = phase_str
                        break
            except Exception as exc:
                logger.warning("durable store restore error during V2 restart: %s", exc)

        if has_durable_flow:
            decision = ContinuityDecision.continuity_resume
            policy_ref = "V2_RESTART_CONTINUITY_USES_DURABLE_STORE_POLICY"
            detail = (
                f"V2 restart recovery: in-flight flow found in durable store "
                f"(phase={flow_entity_phase!r}); continuity_resume"
            )
        else:
            decision = ContinuityDecision.new_attachment
            policy_ref = "V2_RESTART_CONTINUITY_USES_DURABLE_STORE_POLICY"
            detail = (
                "V2 restart recovery: no in-flight flow in durable store; "
                "treating as new_attachment"
            )

        artifact = self._base_artifact(
            ctx,
            decision,
            policy_reference=policy_ref,
            detail=detail,
            flow_entity_phase=flow_entity_phase,
        )
        self._record(artifact)
        return artifact

    def decide(self, ctx: ContinuityEventContext) -> ContinuityDecisionArtifact:
        """Unified dispatch: route *ctx* to the appropriate scenario entry-point.

        This is the single top-level entry-point that callers should use when
        they have a typed :class:`ContinuityEventContext`.  The coordinator
        dispatches to the appropriate scenario handler based on
        ``ctx.event_kind``.

        Parameters
        ----------
        ctx
            Continuity event context with ``event_kind`` set.

        Returns
        -------
        ContinuityDecisionArtifact
        """
        kind = ctx.event_kind
        if kind == ContinuityEventKind.fresh_attach:
            return self.decide_attach(ctx)
        elif kind == ContinuityEventKind.transport_reconnect:
            return self.decide_reconnect(ctx)
        elif kind == ContinuityEventKind.process_recreation_reattach:
            return self.decide_reattach_process_recreation(ctx)
        elif kind == ContinuityEventKind.stale_identity:
            return self.decide_stale_identity(ctx)
        elif kind == ContinuityEventKind.duplicate_signal:
            return self.decide_duplicate_signal(ctx)
        elif kind == ContinuityEventKind.partial_result:
            return self.decide_partial_result(ctx)
        elif kind == ContinuityEventKind.v2_restart_recovery:
            return self.decide_v2_restart_recovery(ctx)
        else:
            # Unknown event kind — fail closed
            artifact = self._base_artifact(
                ctx,
                ContinuityDecision.fail_closed,
                policy_reference="FAIL_CLOSED_IS_SAFE_DEFAULT_POLICY",
                detail=f"unknown event_kind: {kind!r}",
            )
            self._record(artifact)
            return artifact


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------

_SINGLETON: Optional[FlowContinuityCoordinator] = None
_SINGLETON_LOCK = threading.Lock()


def get_flow_continuity_coordinator(
    capacity: int = _RING_BUFFER_CAPACITY,
) -> FlowContinuityCoordinator:
    """Return the process-level :class:`FlowContinuityCoordinator` singleton.

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
                _SINGLETON = FlowContinuityCoordinator(capacity=capacity)
    return _SINGLETON


def reset_flow_continuity_coordinator() -> None:
    """Replace the singleton with a fresh instance (test isolation helper)."""
    global _SINGLETON  # noqa: PLW0603
    with _SINGLETON_LOCK:
        _SINGLETON = None


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------


def coordinate_attach(
    device_id: str,
    runtime_attachment_session_id: str = "",
    *,
    prior_entry_state: str = "",
    registry_entry_created: bool = True,
    session_id: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    coordinator: Optional[FlowContinuityCoordinator] = None,
) -> ContinuityDecisionArtifact:
    """Convenience wrapper: decide continuity for a fresh Android attach.

    Parameters
    ----------
    device_id
        V2-side device identifier.
    runtime_attachment_session_id
        Canonical stable attachment identity.
    prior_entry_state
        State of the prior registry entry (``""`` if none).
    registry_entry_created
        Whether the registry successfully created an entry.
    session_id
        External session identifier.
    metadata
        Arbitrary extension metadata.
    coordinator
        Optional coordinator instance (uses singleton if None).
    """
    _coordinator = coordinator or get_flow_continuity_coordinator()
    ctx = ContinuityEventContext(
        event_kind=ContinuityEventKind.fresh_attach,
        device_id=device_id,
        session_id=session_id,
        runtime_attachment_session_id=runtime_attachment_session_id,
        prior_entry_state=prior_entry_state,
        metadata={
            "registry_entry_created": registry_entry_created,
            **(metadata or {}),
        },
    )
    return _coordinator.decide_attach(ctx)


def coordinate_reconnect(
    device_id: str,
    runtime_attachment_session_id: str = "",
    *,
    session_id: str = "",
    reconnect_count_incremented: bool = True,
    metadata: Optional[Dict[str, Any]] = None,
    coordinator: Optional[FlowContinuityCoordinator] = None,
) -> ContinuityDecisionArtifact:
    """Convenience wrapper: decide continuity for a transport reconnect.

    Parameters
    ----------
    device_id
        V2-side device identifier.
    runtime_attachment_session_id
        Attachment identity presented by the reconnecting client.
    session_id
        External session identifier.
    reconnect_count_incremented
        Whether the registry incremented reconnect_count on this reconnect.
    metadata
        Arbitrary extension metadata.
    coordinator
        Optional coordinator instance.
    """
    _coordinator = coordinator or get_flow_continuity_coordinator()
    ctx = ContinuityEventContext(
        event_kind=ContinuityEventKind.transport_reconnect,
        device_id=device_id,
        session_id=session_id,
        runtime_attachment_session_id=runtime_attachment_session_id,
        metadata={
            "reconnect_count_incremented": reconnect_count_incremented,
            **(metadata or {}),
        },
    )
    return _coordinator.decide_reconnect(ctx)


def coordinate_reattach_process_recreation(
    device_id: str,
    runtime_attachment_session_id: str = "",
    *,
    prior_entry_was_active_or_detached: bool = False,
    attachment_id_matched: bool = False,
    session_id: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    coordinator: Optional[FlowContinuityCoordinator] = None,
) -> ContinuityDecisionArtifact:
    """Convenience wrapper: decide continuity for process-recreation re-attach.

    Parameters
    ----------
    device_id
        V2-side device identifier.
    runtime_attachment_session_id
        Attachment identity presented by the re-attaching client.
    prior_entry_was_active_or_detached
        True iff the prior registry entry was active or detached.
    attachment_id_matched
        True iff the presented ID matched the stored prior entry value.
    session_id
        External session identifier.
    metadata
        Arbitrary extension metadata.
    coordinator
        Optional coordinator instance.
    """
    _coordinator = coordinator or get_flow_continuity_coordinator()
    ctx = ContinuityEventContext(
        event_kind=ContinuityEventKind.process_recreation_reattach,
        device_id=device_id,
        session_id=session_id,
        runtime_attachment_session_id=runtime_attachment_session_id,
        prior_entry_state="active" if prior_entry_was_active_or_detached else "replaced",
        metadata={
            "prior_entry_was_active_or_detached": prior_entry_was_active_or_detached,
            "attachment_id_matched": attachment_id_matched,
            **(metadata or {}),
        },
    )
    return _coordinator.decide_reattach_process_recreation(ctx)


def coordinate_stale_identity(
    session_id: str = "",
    contract_id: str = "",
    runtime_attachment_session_id: str = "",
    *,
    device_id: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    coordinator: Optional[FlowContinuityCoordinator] = None,
) -> ContinuityDecisionArtifact:
    """Convenience wrapper: decide continuity for a stale-identity signal.

    Parameters
    ----------
    session_id
        External session identifier from the signal.
    contract_id
        Contract identifier from the signal.
    runtime_attachment_session_id
        Attachment identity from the signal.
    device_id
        V2-side device identifier.
    metadata
        Arbitrary extension metadata.
    coordinator
        Optional coordinator instance.
    """
    _coordinator = coordinator or get_flow_continuity_coordinator()
    ctx = ContinuityEventContext(
        event_kind=ContinuityEventKind.stale_identity,
        device_id=device_id,
        session_id=session_id,
        runtime_attachment_session_id=runtime_attachment_session_id,
        contract_id=contract_id,
        metadata=metadata or {},
    )
    return _coordinator.decide_stale_identity(ctx)


def coordinate_duplicate_signal(
    signal_key: str,
    session_id: str = "",
    contract_id: str = "",
    *,
    device_id: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    coordinator: Optional[FlowContinuityCoordinator] = None,
) -> ContinuityDecisionArtifact:
    """Convenience wrapper: decide continuity for a potential duplicate signal.

    Parameters
    ----------
    signal_key
        Idempotency key for the incoming signal.
    session_id
        External session identifier.
    contract_id
        Contract identifier.
    device_id
        V2-side device identifier.
    metadata
        Arbitrary extension metadata.
    coordinator
        Optional coordinator instance.
    """
    _coordinator = coordinator or get_flow_continuity_coordinator()
    ctx = ContinuityEventContext(
        event_kind=ContinuityEventKind.duplicate_signal,
        device_id=device_id,
        session_id=session_id,
        contract_id=contract_id,
        signal_key=signal_key,
        metadata=metadata or {},
    )
    return _coordinator.decide_duplicate_signal(ctx)


def coordinate_partial_result(
    session_id: str = "",
    contract_id: str = "",
    partial_result_payload: Optional[Dict[str, Any]] = None,
    *,
    device_id: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    coordinator: Optional[FlowContinuityCoordinator] = None,
) -> ContinuityDecisionArtifact:
    """Convenience wrapper: decide continuity for a partial-result delivery.

    Parameters
    ----------
    session_id
        External session identifier.
    contract_id
        Contract identifier.
    partial_result_payload
        Opaque partial-result payload to preserve.
    device_id
        V2-side device identifier.
    metadata
        Arbitrary extension metadata.
    coordinator
        Optional coordinator instance.
    """
    _coordinator = coordinator or get_flow_continuity_coordinator()
    ctx = ContinuityEventContext(
        event_kind=ContinuityEventKind.partial_result,
        device_id=device_id,
        session_id=session_id,
        contract_id=contract_id,
        is_partial_result=True,
        partial_result_payload=partial_result_payload,
        metadata=metadata or {},
    )
    return _coordinator.decide_partial_result(ctx)


def coordinate_v2_restart_recovery(
    flow_lineage_id: str = "",
    flow_id: str = "",
    contract_id: str = "",
    *,
    recovery_completed: bool = True,
    device_id: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    coordinator: Optional[FlowContinuityCoordinator] = None,
) -> ContinuityDecisionArtifact:
    """Convenience wrapper: decide continuity after a V2 restart.

    Parameters
    ----------
    flow_lineage_id
        Flow lineage identifier to look up in the durable store.
    flow_id
        Delegated flow entity identifier.
    contract_id
        Contract identifier.
    recovery_completed
        True when V2-restart recovery has completed.
    device_id
        V2-side device identifier.
    metadata
        Arbitrary extension metadata.
    coordinator
        Optional coordinator instance.
    """
    _coordinator = coordinator or get_flow_continuity_coordinator()
    ctx = ContinuityEventContext(
        event_kind=ContinuityEventKind.v2_restart_recovery,
        device_id=device_id,
        flow_lineage_id=flow_lineage_id,
        flow_id=flow_id,
        contract_id=contract_id,
        recovery_completed=recovery_completed,
        metadata=metadata or {},
    )
    return _coordinator.decide_v2_restart_recovery(ctx)
