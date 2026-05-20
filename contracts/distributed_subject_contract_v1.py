"""contracts/distributed_subject_contract_v1.py
=================================================
Distributed Subject Contract v1 — PR-Task3.

This module defines the **canonical distributed subject contract v1**: the
formal, serialisable schema that answers the architectural question:

    *"When V2 (canonical center) and Android (bounded relative subject runtime)
    collaborate, what are the precise contract dimensions, field boundaries,
    lifecycle labels, and participant lifecycle rules that govern their
    interaction?"*

This contract is the cross-repo baseline for:

- **subject identity** — who is participating and with what stable identity
- **runtime attachment** — how a subject attaches and re-attaches to the center
- **continuity** — how execution state persists across reconnects and handoffs
- **participant truth** — what evidence a participant may supply, and what
  remains local vs. canonical
- **execution result** — how results are classified, labelled, and up-linked
- **handoff / takeover** — how execution authority transfers between subjects
- **recovery / replay** — how interrupted execution is reconciled
- **diagnostics** — what is locally-visible vs. operator-visible vs. canonical
- **readiness / posture / capability / busy** — participant health signals
- **participant lifecycle** — the formal state machine for participants

Lifecycle labels
----------------
Every contract dimension and field carries one of the following lifecycle
labels (see :class:`ContractFieldLabel`):

``canonical``
    The field / behaviour is authoritative, stable, and enforced by V2
    canonical governance.  Consumers MUST respect it.

``compat``
    The field / behaviour exists for backward-compatibility with older Android
    clients or legacy V2 handlers.  It is intentionally maintained but MUST
    NOT be the primary path for new consumers.

``transitional``
    The field / behaviour is in an active migration window.  It exists today
    but is expected to be superseded by a canonical alternative.  Consumers
    should prefer the canonical alternative where available.

``experimental``
    The field / behaviour is new and not yet proven under real load.  It may
    change or be removed without a deprecation window.

``deprecated``
    The field / behaviour has been superseded.  It will be removed in a future
    contract version.  Existing callers must migrate before the removal window.

``evidence_only``
    The field is valid *local* evidence produced by a bounded relative subject
    (e.g. Android).  It MUST NOT be treated as canonical truth.  V2 governance
    decides whether and how to promote it.

Design principles
-----------------
- **Grounded in real code** — every field maps to a real handler, wire type,
  or lifecycle path.  No purely theoretical protocol layer.
- **Additive only** — does not modify any existing module.
- **Fully serialisable** — all contracts produce stable JSON via ``to_dict``.
- **Graceful defaults** — all optional fields have safe defaults.
- **No capability inflation** — a field's presence does NOT imply the
  capability is mature.  Use :attr:`SubjectContractField.label` to determine
  maturity.

Cross-repo anchors
------------------
V2 side (this repo):
  - ``core/android_participant_truth_ingress.py``
  - ``core/unified_runtime_truth_ingress.py``
  - ``core/unified_result_ingress.py``
  - ``core/unified_continuity_legality_authority.py``
  - ``core/android_v2_continuity_contract.py``
  - ``core/attached_runtime_session_registry.py``
  - ``contracts/dispatch_continuity.py``
  - ``contracts/registered_runtime_device.py``
  - ``contracts/handoff_envelope_v2.py``

Android side (ufo-galaxy-android):
  - ``GalaxyConnectionService.kt``
  - ``GalaxyWebSocketClient.kt``
  - ``RuntimeController.kt``
  - ``AutonomousExecutionPipeline.kt``
  - ``AndroidContinuityIntegration.kt``
  - ``OfflineTaskQueue.kt``
  - ``LocalExecutionModeGate.kt``

Sentinels
---------
:data:`DISTRIBUTED_SUBJECT_CONTRACT_V1_SENTINEL`
    Canonical module-level sentinel.

:data:`PARTICIPANT_LIFECYCLE_IS_GOVERNED_BY_CENTER`
    V2 is the sole authority for participant lifecycle state.

:data:`SUBJECT_EVIDENCE_IS_NOT_CANONICAL_TRUTH`
    Bounded subject evidence requires canonical center validation.

:data:`CONTRACT_FIELD_LABEL_IS_EXPLICIT_POLICY`
    Every field must carry an explicit lifecycle label; unlabelled fields
    are treated as ``transitional`` by consumers.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Sentinels
# ---------------------------------------------------------------------------

DISTRIBUTED_SUBJECT_CONTRACT_V1_SENTINEL: str = (
    "DISTRIBUTED_SUBJECT_CONTRACT_V1_SENTINEL: "
    "contracts/distributed_subject_contract_v1.py is the canonical v1 schema "
    "for all V2 ↔ Android (bounded relative subject runtime) cross-repo contract "
    "dimensions.  See module docstring for field boundaries and lifecycle labels."
)

PARTICIPANT_LIFECYCLE_IS_GOVERNED_BY_CENTER: str = (
    "PARTICIPANT_LIFECYCLE_IS_GOVERNED_BY_CENTER: "
    "Participant lifecycle state transitions are authoritative only when issued "
    "by V2 canonical governance (core/android_participant_truth_ingress.py, "
    "core/unified_runtime_truth_ingress.py).  A bounded relative subject may "
    "signal readiness / posture / busy, but it cannot unilaterally promote or "
    "demote its own participant lifecycle state."
)

SUBJECT_EVIDENCE_IS_NOT_CANONICAL_TRUTH: str = (
    "SUBJECT_EVIDENCE_IS_NOT_CANONICAL_TRUTH: "
    "Evidence supplied by a bounded relative subject (e.g. Android) is classified "
    "as 'evidence_only' or 'participant truth' until V2 canonical governance "
    "accepts and promotes it.  Missing, stale, conflicting, or otherwise degraded "
    "evidence must not be treated as positive canonical truth."
)

CONTRACT_FIELD_LABEL_IS_EXPLICIT_POLICY: str = (
    "CONTRACT_FIELD_LABEL_IS_EXPLICIT_POLICY: "
    "Every field in the distributed subject contract v1 carries an explicit "
    "ContractFieldLabel.  An absent or unknown label is treated as 'transitional' "
    "by contract consumers.  Labels may not be silently omitted."
)


# ---------------------------------------------------------------------------
# Lifecycle label enum
# ---------------------------------------------------------------------------


class ContractFieldLabel(str, Enum):
    """Lifecycle maturity label for a contract field or dimension.

    See module docstring for full semantics of each value.
    """

    CANONICAL = "canonical"
    """Stable, authoritative, enforced by V2 governance."""

    COMPAT = "compat"
    """Backward-compatible; maintained but not the primary path."""

    TRANSITIONAL = "transitional"
    """In active migration; prefer canonical alternative where available."""

    EXPERIMENTAL = "experimental"
    """New; not yet proven; may change without deprecation."""

    DEPRECATED = "deprecated"
    """Superseded; callers must migrate before next contract version."""

    EVIDENCE_ONLY = "evidence_only"
    """Valid local subject evidence; must not be treated as canonical truth."""


# ---------------------------------------------------------------------------
# Contract dimension enum
# ---------------------------------------------------------------------------


class SubjectContractDimension(str, Enum):
    """Enumeration of all recognised distributed subject contract dimensions."""

    SUBJECT_IDENTITY = "subject_identity"
    RUNTIME_ATTACHMENT = "runtime_attachment"
    CONTINUITY = "continuity"
    PARTICIPANT_TRUTH = "participant_truth"
    EXECUTION_RESULT = "execution_result"
    HANDOFF_TAKEOVER = "handoff_takeover"
    RECOVERY_REPLAY = "recovery_replay"
    DIAGNOSTICS = "diagnostics"
    READINESS_POSTURE_CAPABILITY_BUSY = "readiness_posture_capability_busy"
    PARTICIPANT_LIFECYCLE = "participant_lifecycle"


# ---------------------------------------------------------------------------
# Contract field descriptor
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SubjectContractField:
    """Descriptor for a single field or dimension in the distributed subject
    contract v1.

    Parameters
    ----------
    name:
        Field name as it appears on the wire or in handler code.
    dimension:
        Which contract dimension this field belongs to.
    label:
        Lifecycle maturity label (see :class:`ContractFieldLabel`).
    description:
        Human-readable description of the field's semantics.
    v2_anchor:
        V2-side module / symbol where this field is authoritative.
    android_anchor:
        Android-side class / symbol where this field is produced (if any).
    notes:
        Additional free-text notes (migration guidance, boundary warnings, …).
    """

    name: str
    dimension: SubjectContractDimension
    label: ContractFieldLabel
    description: str
    v2_anchor: str = ""
    android_anchor: str = ""
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "dimension": self.dimension.value,
            "label": self.label.value,
            "description": self.description,
            "v2_anchor": self.v2_anchor,
            "android_anchor": self.android_anchor,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Canonical field registry
# ---------------------------------------------------------------------------

#: Complete v1 field registry.  Consumers must not infer field semantics from
#: field existence alone; always check the :attr:`SubjectContractField.label`.
DISTRIBUTED_SUBJECT_CONTRACT_V1_FIELDS: List[SubjectContractField] = [

    # ── Subject Identity ────────────────────────────────────────────────────

    SubjectContractField(
        name="device_id",
        dimension=SubjectContractDimension.SUBJECT_IDENTITY,
        label=ContractFieldLabel.CANONICAL,
        description=(
            "Stable identifier for the bounded relative subject device.  "
            "Assigned at registration; must not change across reconnects."
        ),
        v2_anchor="core/android_participant_truth_ingress.py",
        android_anchor="GalaxyConnectionService.kt",
    ),
    SubjectContractField(
        name="runtime_attachment_session_id",
        dimension=SubjectContractDimension.SUBJECT_IDENTITY,
        label=ContractFieldLabel.CANONICAL,
        description=(
            "Stable per-attachment session ID that persists across transport "
            "reconnects and Android process recreation.  Generated by V2 "
            "AttachedSessionRegistry if not supplied by the client."
        ),
        v2_anchor="core/attached_runtime_session_registry.py",
        android_anchor="GalaxyConnectionService.kt",
        notes=(
            "The client MUST persist this value across process recreation.  "
            "Absence on reconnect triggers a new_attachment classification."
        ),
    ),
    SubjectContractField(
        name="participant_id",
        dimension=SubjectContractDimension.SUBJECT_IDENTITY,
        label=ContractFieldLabel.CANONICAL,
        description="Logical participant identifier within a specific task flow.",
        v2_anchor="core/android_participant_truth_ingress.py",
        android_anchor="AutonomousExecutionPipeline.kt",
    ),

    # ── Runtime Attachment ──────────────────────────────────────────────────

    SubjectContractField(
        name="attach",
        dimension=SubjectContractDimension.RUNTIME_ATTACHMENT,
        label=ContractFieldLabel.CANONICAL,
        description=(
            "Initial attach message from Android to V2.  Creates an "
            "AttachedSessionRegistryEntry.  A failed attach is never silently "
            "promoted to connected."
        ),
        v2_anchor=(
            "galaxy_gateway/android/handlers/registration.py:"
            "handle_device_registration"
        ),
        android_anchor="GalaxyConnectionService.kt",
    ),
    SubjectContractField(
        name="device_reconnect",
        dimension=SubjectContractDimension.RUNTIME_ATTACHMENT,
        label=ContractFieldLabel.CANONICAL,
        description=(
            "Reconnect message after transport interruption.  V2 classifies "
            "the outcome as continuity_resume or new_attachment."
        ),
        v2_anchor=(
            "galaxy_gateway/android/handlers/registration.py:"
            "handle_device_reconnect"
        ),
        android_anchor="GalaxyWebSocketClient.kt",
    ),
    SubjectContractField(
        name="runtime_attachment_session_id_absent_fallback",
        dimension=SubjectContractDimension.RUNTIME_ATTACHMENT,
        label=ContractFieldLabel.COMPAT,
        description=(
            "When Android reconnects without presenting a "
            "runtime_attachment_session_id, V2 falls back to continuity_resume "
            "if a prior active/detached entry exists for the device.  This compat "
            "path supports older Android clients."
        ),
        v2_anchor="core/attached_runtime_session_registry.py",
        android_anchor="GalaxyConnectionService.kt",
        notes="Must not be used by new Android clients; present session ID instead.",
    ),

    # ── Continuity ───────────────────────────────────────────────────────────

    SubjectContractField(
        name="continuity_class",
        dimension=SubjectContractDimension.CONTINUITY,
        label=ContractFieldLabel.CANONICAL,
        description=(
            "Classification of the continuity context: online_session, "
            "resumed_session, handoff_session, replay_session, "
            "parallel_subtask, or no_continuity."
        ),
        v2_anchor="contracts/dispatch_continuity.py:DispatchContinuityClass",
        android_anchor="AndroidContinuityIntegration.kt",
    ),
    SubjectContractField(
        name="local_continuity_handling",
        dimension=SubjectContractDimension.CONTINUITY,
        label=ContractFieldLabel.EVIDENCE_ONLY,
        description=(
            "Android-local continuity management (OfflineTaskQueue, local "
            "recovery).  Valid local evidence; does not imply cross-device "
            "continuity legality.  V2 unified_continuity_legality_authority "
            "makes the cross-device legality determination."
        ),
        v2_anchor="core/unified_continuity_legality_authority.py",
        android_anchor="OfflineTaskQueue.kt",
        notes=(
            "Android may queue tasks locally, but whether they are legally "
            "resumable cross-device is determined by V2, not by Android."
        ),
    ),
    SubjectContractField(
        name="cross_device_continuity_legality",
        dimension=SubjectContractDimension.CONTINUITY,
        label=ContractFieldLabel.CANONICAL,
        description=(
            "Cross-device session/task continuation legality verdict, issued "
            "exclusively by V2 UnifiedContinuityLegalityAuthority."
        ),
        v2_anchor="core/unified_continuity_legality_authority.py",
        android_anchor="",
        notes="Android must not self-issue cross-device continuation verdicts.",
    ),

    # ── Participant Truth ────────────────────────────────────────────────────

    SubjectContractField(
        name="android_participant_truth_message",
        dimension=SubjectContractDimension.PARTICIPANT_TRUTH,
        label=ContractFieldLabel.CANONICAL,
        description=(
            "Android-originated participant truth message, ingested by "
            "core/android_participant_truth_ingress.py.  The canonical ingress "
            "path for Android runtime evidence."
        ),
        v2_anchor="core/android_participant_truth_ingress.py",
        android_anchor="AutonomousExecutionPipeline.kt",
    ),
    SubjectContractField(
        name="android_reported_mode",
        dimension=SubjectContractDimension.PARTICIPANT_TRUTH,
        label=ContractFieldLabel.EVIDENCE_ONLY,
        description=(
            "Android-self-reported execution mode (e.g. local_ai, offloaded).  "
            "Evidence only; V2 classifies and may override."
        ),
        v2_anchor="core/unified_execution_governance.py",
        android_anchor="LocalExecutionModeGate.kt",
    ),
    SubjectContractField(
        name="participant_truth_uplink_required",
        dimension=SubjectContractDimension.PARTICIPANT_TRUTH,
        label=ContractFieldLabel.CANONICAL,
        description=(
            "Policy: Android participant truth MUST be uplinked via "
            "android_participant_truth_ingress.py.  Bypassing this ingress "
            "path is prohibited."
        ),
        v2_anchor="core/android_participant_truth_ingress.py",
        android_anchor="GalaxyConnectionService.kt",
    ),

    # ── Execution Result ─────────────────────────────────────────────────────

    SubjectContractField(
        name="execution_result_uplink",
        dimension=SubjectContractDimension.EXECUTION_RESULT,
        label=ContractFieldLabel.CANONICAL,
        description=(
            "Android execution result up-link into V2 canonical truth chain via "
            "unified_runtime_truth_ingress or unified_result_ingress."
        ),
        v2_anchor=(
            "core/unified_runtime_truth_ingress.py, core/unified_result_ingress.py"
        ),
        android_anchor="GalaxyConnectionService.kt",
    ),
    SubjectContractField(
        name="local_execution_result",
        dimension=SubjectContractDimension.EXECUTION_RESULT,
        label=ContractFieldLabel.EVIDENCE_ONLY,
        description=(
            "Android-local execution outcome before V2 canonical acceptance.  "
            "Does not constitute canonical closure."
        ),
        v2_anchor="core/task_result_canonical_truth_chain.py",
        android_anchor="LocalLoopExecutor.kt",
    ),
    SubjectContractField(
        name="canonical_closure",
        dimension=SubjectContractDimension.EXECUTION_RESULT,
        label=ContractFieldLabel.CANONICAL,
        description=(
            "Final task/session closure verdict issued by V2 canonical truth "
            "chain.  Android may not self-declare canonical closure."
        ),
        v2_anchor=(
            "core/unified_result_ingress.py, core/task_result_canonical_truth_chain.py"
        ),
        android_anchor="",
    ),

    # ── Handoff / Takeover ───────────────────────────────────────────────────

    SubjectContractField(
        name="handoff_envelope",
        dimension=SubjectContractDimension.HANDOFF_TAKEOVER,
        label=ContractFieldLabel.CANONICAL,
        description=(
            "HandoffEnvelopeV2 carrying the formal handoff context from "
            "source to target device.  Canonical cross-device handoff record."
        ),
        v2_anchor="contracts/handoff_envelope_v2.py:HandoffEnvelopeV2",
        android_anchor="GalaxyConnectionService.kt",
    ),
    SubjectContractField(
        name="local_takeover_result",
        dimension=SubjectContractDimension.HANDOFF_TAKEOVER,
        label=ContractFieldLabel.CANONICAL,
        description=(
            "LocalTakeoverResult from the target device confirming takeover "
            "completion.  Used in mesh session coordinator."
        ),
        v2_anchor="contracts/local_takeover_result.py:LocalTakeoverResult",
        android_anchor="RuntimeController.kt",
    ),
    SubjectContractField(
        name="takeover_candidate_signal",
        dimension=SubjectContractDimension.HANDOFF_TAKEOVER,
        label=ContractFieldLabel.TRANSITIONAL,
        description=(
            "Signal from a participant advertising takeover candidacy.  "
            "Currently transitional; will be formalised in participant lifecycle "
            "state machine."
        ),
        v2_anchor="core/android_participant_session_state.py",
        android_anchor="RuntimeController.kt",
        notes="Prefer participant lifecycle state transitions once formalised.",
    ),

    # ── Recovery / Replay ────────────────────────────────────────────────────

    SubjectContractField(
        name="dispatch_continuity_context",
        dimension=SubjectContractDimension.RECOVERY_REPLAY,
        label=ContractFieldLabel.CANONICAL,
        description=(
            "DispatchContinuityContext: durable record linking a resumed "
            "execution to its prior dispatch, session, and mesh session context."
        ),
        v2_anchor="contracts/dispatch_continuity.py:DispatchContinuityContext",
        android_anchor="AndroidContinuityIntegration.kt",
    ),
    SubjectContractField(
        name="execution_interruption_record",
        dimension=SubjectContractDimension.RECOVERY_REPLAY,
        label=ContractFieldLabel.CANONICAL,
        description=(
            "ExecutionInterruptionRecord classifying an interruption as "
            "recoverable or terminal.  Required for replay path eligibility."
        ),
        v2_anchor="contracts/dispatch_continuity.py:ExecutionInterruptionRecord",
        android_anchor="AndroidContinuityIntegration.kt",
    ),
    SubjectContractField(
        name="offline_task_queue",
        dimension=SubjectContractDimension.RECOVERY_REPLAY,
        label=ContractFieldLabel.EVIDENCE_ONLY,
        description=(
            "Android-local offline task queue.  Evidence of locally-queued "
            "work; does not imply canonical replay eligibility without V2 "
            "continuity legality gate."
        ),
        v2_anchor="core/unified_continuity_legality_authority.py",
        android_anchor="OfflineTaskQueue.kt",
    ),

    # ── Diagnostics ──────────────────────────────────────────────────────────

    SubjectContractField(
        name="local_visible_diagnostics",
        dimension=SubjectContractDimension.DIAGNOSTICS,
        label=ContractFieldLabel.EVIDENCE_ONLY,
        description=(
            "Android-local diagnostics visible only within the bounded subject "
            "runtime.  Not promoted to canonical truth without explicit uplink."
        ),
        android_anchor="RuntimeController.kt",
        notes="Must not be treated as operator-visible or canonical evidence.",
    ),
    SubjectContractField(
        name="participant_diagnostics_uplink",
        dimension=SubjectContractDimension.DIAGNOSTICS,
        label=ContractFieldLabel.TRANSITIONAL,
        description=(
            "Path for Android to uplink diagnostics to V2 for operator "
            "visibility.  Transitional: the uplink format and ingress path "
            "are not yet fully formalised."
        ),
        v2_anchor="core/operator_surface.py",
        android_anchor="GalaxyConnectionService.kt",
        notes="Will be superseded by formalised evidence uplink contract.",
    ),
    SubjectContractField(
        name="operator_visible_diagnostics",
        dimension=SubjectContractDimension.DIAGNOSTICS,
        label=ContractFieldLabel.CANONICAL,
        description=(
            "Diagnostics surface presented to the operator via "
            "core/operator_surface.py.  Canonical, read-only projection; "
            "must not feed back into canonical truth."
        ),
        v2_anchor="core/operator_surface.py, core/routes/operator.py",
        android_anchor="",
    ),

    # ── Readiness / Posture / Capability / Busy ──────────────────────────────

    SubjectContractField(
        name="capability_truth",
        dimension=SubjectContractDimension.READINESS_POSTURE_CAPABILITY_BUSY,
        label=ContractFieldLabel.CANONICAL,
        description=(
            "Android-declared capability set, classified and accepted by V2 "
            "unified_execution_governance.  Missing, stale, or conflicting "
            "capability truth is a deny condition."
        ),
        v2_anchor="core/unified_execution_governance.py",
        android_anchor="GalaxyConnectionService.kt",
    ),
    SubjectContractField(
        name="android_semantics_contract_state",
        dimension=SubjectContractDimension.READINESS_POSTURE_CAPABILITY_BUSY,
        label=ContractFieldLabel.CANONICAL,
        description=(
            "V2-computed classification of Android runtime semantics contract "
            "completeness: complete / partial / missing / malformed / unknown / "
            "downgraded / stale / conflicting."
        ),
        v2_anchor=(
            "core/unified_execution_governance.py:"
            "classify_canonical_proof_input_diagnosis"
        ),
        android_anchor="",
    ),
    SubjectContractField(
        name="busy_signal",
        dimension=SubjectContractDimension.READINESS_POSTURE_CAPABILITY_BUSY,
        label=ContractFieldLabel.EVIDENCE_ONLY,
        description=(
            "Android-reported busy state.  Evidence only; V2 may use this "
            "in dispatch arbitration but must cross-check with execution "
            "lifecycle truth binding."
        ),
        v2_anchor="core/android_participant_truth_ingress.py",
        android_anchor="RuntimeController.kt",
    ),
    SubjectContractField(
        name="posture_contract",
        dimension=SubjectContractDimension.READINESS_POSTURE_CAPABILITY_BUSY,
        label=ContractFieldLabel.CANONICAL,
        description=(
            "SourcePostureContract: V2-authoritative assessment of source "
            "device posture (latency, throughput, reliability, memory, "
            "thermal, battery).  Distinct from Android self-report."
        ),
        v2_anchor="contracts/source_posture_contract.py:SourcePostureContract",
        android_anchor="",
    ),

    # ── Participant Lifecycle ─────────────────────────────────────────────────

    SubjectContractField(
        name="participant_lifecycle_state",
        dimension=SubjectContractDimension.PARTICIPANT_LIFECYCLE,
        label=ContractFieldLabel.CANONICAL,
        description=(
            "Formal participant lifecycle state as maintained by V2 canonical "
            "governance.  See ParticipantLifecycleState enum.  Android may "
            "signal intent but cannot self-transition state."
        ),
        v2_anchor="contracts/participant_lifecycle_schema.py:ParticipantLifecycleState",
        android_anchor="RuntimeController.kt",
    ),
    SubjectContractField(
        name="participant_role",
        dimension=SubjectContractDimension.PARTICIPANT_LIFECYCLE,
        label=ContractFieldLabel.CANONICAL,
        description=(
            "Formal participant role assigned by V2: primary, assistant, "
            "fallback, suspended, takeover_candidate, degraded."
        ),
        v2_anchor="contracts/participant_lifecycle_schema.py:ParticipantRole",
        android_anchor="RuntimeController.kt",
    ),
]


# ---------------------------------------------------------------------------
# Field registry index helpers
# ---------------------------------------------------------------------------


def get_fields_by_dimension(
    dimension: SubjectContractDimension,
) -> List[SubjectContractField]:
    """Return all fields for a given contract dimension."""
    return [f for f in DISTRIBUTED_SUBJECT_CONTRACT_V1_FIELDS if f.dimension == dimension]


def get_fields_by_label(label: ContractFieldLabel) -> List[SubjectContractField]:
    """Return all fields carrying a given lifecycle label."""
    return [f for f in DISTRIBUTED_SUBJECT_CONTRACT_V1_FIELDS if f.label == label]


def get_field(name: str) -> Optional[SubjectContractField]:
    """Look up a field descriptor by name.  Returns None if not found."""
    for f in DISTRIBUTED_SUBJECT_CONTRACT_V1_FIELDS:
        if f.name == name:
            return f
    return None


# ---------------------------------------------------------------------------
# Contract version record
# ---------------------------------------------------------------------------


@dataclass
class DistributedSubjectContractVersion:
    """Serialisable version record for the distributed subject contract.

    Parameters
    ----------
    version:
        Semantic version string for the contract (e.g. ``"v1"``).
    created_at:
        Unix timestamp of initial publication.
    field_count:
        Number of fields in this version's registry.
    dimensions:
        List of dimension names covered.
    """

    version: str = "v1"
    created_at: float = field(default_factory=time.time)
    field_count: int = field(
        default_factory=lambda: len(DISTRIBUTED_SUBJECT_CONTRACT_V1_FIELDS)
    )
    dimensions: List[str] = field(
        default_factory=lambda: [d.value for d in SubjectContractDimension]
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "created_at": self.created_at,
            "field_count": self.field_count,
            "dimensions": self.dimensions,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


def build_contract_version() -> DistributedSubjectContractVersion:
    """Return the canonical v1 version record."""
    return DistributedSubjectContractVersion()


# ---------------------------------------------------------------------------
# Contract manifest (full field dump)
# ---------------------------------------------------------------------------


def build_contract_manifest() -> Dict[str, Any]:
    """Return a full serialisable manifest of the v1 contract.

    The manifest is useful for documentation generation, cross-repo
    alignment checks, and snapshot regression tests.
    """
    return {
        "version": "v1",
        "sentinel": DISTRIBUTED_SUBJECT_CONTRACT_V1_SENTINEL,
        "policies": {
            "participant_lifecycle_governance": PARTICIPANT_LIFECYCLE_IS_GOVERNED_BY_CENTER,
            "subject_evidence_policy": SUBJECT_EVIDENCE_IS_NOT_CANONICAL_TRUTH,
            "field_label_policy": CONTRACT_FIELD_LABEL_IS_EXPLICIT_POLICY,
        },
        "dimensions": [d.value for d in SubjectContractDimension],
        "labels": [l.value for l in ContractFieldLabel],
        "fields": [f.to_dict() for f in DISTRIBUTED_SUBJECT_CONTRACT_V1_FIELDS],
    }
