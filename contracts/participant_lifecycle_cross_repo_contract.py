"""contracts/participant_lifecycle_cross_repo_contract.py
===========================================================
Cross-repo participant lifecycle/governance consistency contract.

This module locks the long-lived, machine-checkable consistency constraints
between:

- V2 canonical participant lifecycle schema
  (:mod:`contracts.participant_lifecycle_schema`)
- Android runtime formal lifecycle surface
  (``FormalParticipantLifecycleState.kt``)

Scope
-----
This contract does **not** create a new lifecycle authority center and does
not replace existing lifecycle state machines.  It only codifies cross-repo
consistency invariants so drift is detected by automated tests instead of
reviewer memory.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, FrozenSet, Iterable, List, Mapping, Sequence, Tuple

from contracts.participant_lifecycle_schema import (
    PARTICIPANT_STATE_TRANSITIONS,
    ParticipantLifecycleState,
    ParticipantTransitionTrigger,
)

PARTICIPANT_LIFECYCLE_CROSS_REPO_CONTRACT_AUTHORITY: str = (
    "PARTICIPANT_LIFECYCLE_CROSS_REPO_CONTRACT_AUTHORITY::"
    "contracts.participant_lifecycle_cross_repo_contract::"
    "V2 remains canonical participant governance center; Android lifecycle "
    "surface is bounded-runtime evidence and must not be elevated to center authority."
)

PARTICIPANT_LIFECYCLE_CROSS_REPO_CONTRACT_VERSION: str = "1.0.0"

# Android repository commit audited when this contract was calibrated.
# When Android lifecycle semantics intentionally change, bump this ref together
# with the contract mapping and tests in this module.
ANDROID_AUDITED_REF: str = "b66d9891c4aa67a6ec4db76137a30d8e6ead34e3"
# Blob SHA for FormalParticipantLifecycleState.kt at ANDROID_AUDITED_REF.
# This is file-level evidence for the exact Android formal-state definition
# consumed by this contract (distinct from the repository commit hash above).
ANDROID_FORMAL_PARTICIPANT_LIFECYCLE_SOURCE_SHA: str = "8f41ea2202868a9f05c02053768752677d91c7f4"
ANDROID_FORMAL_PARTICIPANT_LIFECYCLE_ANCHOR: str = (
    "ufo-galaxy-android/app/src/main/java/com/ufo/galaxy/runtime/FormalParticipantLifecycleState.kt"
)


class V2ParticipantStateClass(str, Enum):
    PREPARING = "preparing"
    EXECUTABLE = "executable"
    GOVERNANCE_GUARDED = "governance_guarded"
    RECOVERY = "recovery"
    TERMINAL = "terminal"


class AndroidFormalStateClass(str, Enum):
    STARTUP_BLOCKED = "startup_blocked"
    EXECUTABLE = "executable"
    DEGRADED_EXECUTABLE = "degraded_executable"
    RECOVERY_BLOCKED = "recovery_blocked"
    UNAVAILABLE_BLOCKED = "unavailable_blocked"


V2_STATE_CLASS_BY_STATE: Mapping[ParticipantLifecycleState, V2ParticipantStateClass] = {
    ParticipantLifecycleState.UNREGISTERED: V2ParticipantStateClass.PREPARING,
    ParticipantLifecycleState.ATTACHING: V2ParticipantStateClass.PREPARING,
    ParticipantLifecycleState.ATTACHED: V2ParticipantStateClass.EXECUTABLE,
    ParticipantLifecycleState.DISPATCHED: V2ParticipantStateClass.EXECUTABLE,
    ParticipantLifecycleState.EXECUTING: V2ParticipantStateClass.EXECUTABLE,
    ParticipantLifecycleState.WAITING_RESULT: V2ParticipantStateClass.EXECUTABLE,
    ParticipantLifecycleState.RESULT_ACCEPTED: V2ParticipantStateClass.EXECUTABLE,
    ParticipantLifecycleState.SUSPENDED_STATE: V2ParticipantStateClass.GOVERNANCE_GUARDED,
    ParticipantLifecycleState.TAKEOVER_CANDIDATE_STATE: V2ParticipantStateClass.GOVERNANCE_GUARDED,
    ParticipantLifecycleState.TAKING_OVER: V2ParticipantStateClass.GOVERNANCE_GUARDED,
    ParticipantLifecycleState.DEGRADED_STATE: V2ParticipantStateClass.GOVERNANCE_GUARDED,
    ParticipantLifecycleState.RECOVERING: V2ParticipantStateClass.RECOVERY,
    ParticipantLifecycleState.DETACHED: V2ParticipantStateClass.RECOVERY,
    ParticipantLifecycleState.TERMINAL: V2ParticipantStateClass.TERMINAL,
}

ANDROID_FORMAL_WIRE_VALUES: FrozenSet[str] = frozenset(
    {"starting", "ready", "degraded", "recovering", "unavailable_failed"}
)

ANDROID_FORMAL_STATE_CLASS_BY_WIRE: Mapping[str, AndroidFormalStateClass] = {
    "starting": AndroidFormalStateClass.STARTUP_BLOCKED,
    "ready": AndroidFormalStateClass.EXECUTABLE,
    "degraded": AndroidFormalStateClass.DEGRADED_EXECUTABLE,
    "recovering": AndroidFormalStateClass.RECOVERY_BLOCKED,
    "unavailable_failed": AndroidFormalStateClass.UNAVAILABLE_BLOCKED,
}

ANDROID_FORMAL_CAPABILITY_ADVERTISEMENT_ALLOWED: FrozenSet[str] = frozenset({"ready", "degraded"})
ANDROID_FORMAL_CAPABILITY_ADVERTISEMENT_BLOCKED: FrozenSet[str] = frozenset(
    {"starting", "recovering", "unavailable_failed"}
)

# Canonical closure remains V2-only. Android formal states are runtime states,
# not closure-finalization authority.
V2_TERMINAL_STATES: FrozenSet[ParticipantLifecycleState] = frozenset({ParticipantLifecycleState.TERMINAL})
ANDROID_FORMAL_CLOSURE_TERMINAL_STATES: FrozenSet[str] = frozenset()


@dataclass(frozen=True)
class CriticalTriggerSemanticMapping:
    trigger: ParticipantTransitionTrigger
    v2_from_state: ParticipantLifecycleState
    v2_to_state: ParticipantLifecycleState
    android_from_wire: str
    android_to_wire: str
    description: str


CRITICAL_TRIGGER_SEMANTIC_MAPPINGS: Tuple[CriticalTriggerSemanticMapping, ...] = (
    CriticalTriggerSemanticMapping(
        trigger=ParticipantTransitionTrigger.CAPABILITY_DEGRADED,
        v2_from_state=ParticipantLifecycleState.EXECUTING,
        v2_to_state=ParticipantLifecycleState.DEGRADED_STATE,
        android_from_wire="ready",
        android_to_wire="degraded",
        description="Runtime degradation during execution must align to degraded semantics on both sides.",
    ),
    CriticalTriggerSemanticMapping(
        trigger=ParticipantTransitionTrigger.CAPABILITY_RESTORED,
        v2_from_state=ParticipantLifecycleState.DEGRADED_STATE,
        v2_to_state=ParticipantLifecycleState.EXECUTING,
        android_from_wire="degraded",
        android_to_wire="ready",
        description="Capability restoration returns participant to executable semantics.",
    ),
    CriticalTriggerSemanticMapping(
        trigger=ParticipantTransitionTrigger.RECOVERY_INITIATED,
        v2_from_state=ParticipantLifecycleState.DETACHED,
        v2_to_state=ParticipantLifecycleState.RECOVERING,
        android_from_wire="recovering",
        android_to_wire="recovering",
        description=(
            "When V2 upgrades detached to recovering, Android runtime is already in "
            "recovering semantics (bounded-runtime recovery has started)."
        ),
    ),
    CriticalTriggerSemanticMapping(
        trigger=ParticipantTransitionTrigger.RECOVERY_COMPLETED,
        v2_from_state=ParticipantLifecycleState.RECOVERING,
        v2_to_state=ParticipantLifecycleState.ATTACHED,
        android_from_wire="recovering",
        android_to_wire="ready",
        description="Recovery completion restores dispatch-eligible executable semantics.",
    ),
    CriticalTriggerSemanticMapping(
        trigger=ParticipantTransitionTrigger.TERMINAL_LOSS,
        v2_from_state=ParticipantLifecycleState.RECOVERING,
        v2_to_state=ParticipantLifecycleState.TERMINAL,
        android_from_wire="recovering",
        android_to_wire="unavailable_failed",
        description=(
            "Terminal loss in V2 corresponds to Android hard-unavailable runtime evidence; "
            "closure finalization still occurs only in V2."
        ),
    ),
)


@dataclass
class ParticipantLifecycleCrossRepoVerificationReport:
    passed: bool
    issues: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "passed": self.passed,
            "issues": list(self.issues),
            "contract_version": PARTICIPANT_LIFECYCLE_CROSS_REPO_CONTRACT_VERSION,
            "android_audited_ref": ANDROID_AUDITED_REF,
            "android_formal_source_sha": ANDROID_FORMAL_PARTICIPANT_LIFECYCLE_SOURCE_SHA,
        }


_V2_TRANSITION_INDEX: FrozenSet[
    Tuple[ParticipantLifecycleState, ParticipantLifecycleState, ParticipantTransitionTrigger]
] = frozenset((t.from_state, t.to_state, t.trigger) for t in PARTICIPANT_STATE_TRANSITIONS)


def verify_participant_lifecycle_cross_repo_contract(
    android_wire_values: Iterable[str] | None = None,
) -> ParticipantLifecycleCrossRepoVerificationReport:
    issues: List[str] = []

    if set(V2_STATE_CLASS_BY_STATE.keys()) != set(ParticipantLifecycleState):
        issues.append("V2 state-class mapping does not cover all ParticipantLifecycleState values.")

    if set(ANDROID_FORMAL_STATE_CLASS_BY_WIRE.keys()) != set(ANDROID_FORMAL_WIRE_VALUES):
        issues.append("Android formal state-class mapping does not exactly cover declared wire values.")

    if android_wire_values is not None:
        observed_android_wire_values = set(android_wire_values)
    else:
        observed_android_wire_values = set(ANDROID_FORMAL_WIRE_VALUES)

    if observed_android_wire_values != set(ANDROID_FORMAL_WIRE_VALUES):
        missing = sorted(set(ANDROID_FORMAL_WIRE_VALUES) - observed_android_wire_values)
        extra = sorted(observed_android_wire_values - set(ANDROID_FORMAL_WIRE_VALUES))
        if missing:
            issues.append(f"Android formal wire values missing from observed set: {missing}.")
        if extra:
            issues.append(f"Observed Android formal wire values not in contract: {extra}.")

    if V2_TERMINAL_STATES != frozenset({ParticipantLifecycleState.TERMINAL}):
        issues.append("V2 terminal-state boundary must remain a closed singleton {terminal}.")

    if ANDROID_FORMAL_CLOSURE_TERMINAL_STATES:
        issues.append("Android formal lifecycle must not define closure-terminal authority states.")

    terminal_triggers = {
        t.trigger
        for t in PARTICIPANT_STATE_TRANSITIONS
        if t.to_state in V2_TERMINAL_STATES
    }
    expected_terminal_triggers = {
        ParticipantTransitionTrigger.TASK_CLOSURE,
        ParticipantTransitionTrigger.TERMINAL_LOSS,
    }
    if terminal_triggers != expected_terminal_triggers:
        issues.append(
            "V2 terminal transition trigger boundary drift detected: "
            f"expected {sorted(x.value for x in expected_terminal_triggers)}, "
            f"got {sorted(x.value for x in terminal_triggers)}."
        )

    for mapping in CRITICAL_TRIGGER_SEMANTIC_MAPPINGS:
        key = (mapping.v2_from_state, mapping.v2_to_state, mapping.trigger)
        if key not in _V2_TRANSITION_INDEX:
            issues.append(
                "Critical trigger semantic mapping missing V2 transition: "
                f"{mapping.v2_from_state.value} --{mapping.trigger.value}--> {mapping.v2_to_state.value}."
            )
        if mapping.android_from_wire not in ANDROID_FORMAL_WIRE_VALUES:
            issues.append(f"Critical mapping android_from_wire not in contract: {mapping.android_from_wire}.")
        if mapping.android_to_wire not in ANDROID_FORMAL_WIRE_VALUES:
            issues.append(f"Critical mapping android_to_wire not in contract: {mapping.android_to_wire}.")

    return ParticipantLifecycleCrossRepoVerificationReport(
        passed=not issues,
        issues=issues,
    )


def build_participant_lifecycle_cross_repo_contract_manifest() -> Dict[str, object]:
    report = verify_participant_lifecycle_cross_repo_contract()
    return {
        "authority": PARTICIPANT_LIFECYCLE_CROSS_REPO_CONTRACT_AUTHORITY,
        "contract_version": PARTICIPANT_LIFECYCLE_CROSS_REPO_CONTRACT_VERSION,
        "v2_role": "canonical_governance_center",
        "android_role": "bounded_relative_subject_runtime",
        "android_audited_ref": ANDROID_AUDITED_REF,
        "android_formal_source_sha": ANDROID_FORMAL_PARTICIPANT_LIFECYCLE_SOURCE_SHA,
        "android_anchor": ANDROID_FORMAL_PARTICIPANT_LIFECYCLE_ANCHOR,
        "v2_states": [s.value for s in ParticipantLifecycleState],
        "v2_state_classes": {k.value: v.value for k, v in V2_STATE_CLASS_BY_STATE.items()},
        "v2_terminal_states": [s.value for s in sorted(V2_TERMINAL_STATES, key=lambda x: x.value)],
        "android_formal_wire_values": sorted(ANDROID_FORMAL_WIRE_VALUES),
        "android_formal_state_classes": {k: v.value for k, v in ANDROID_FORMAL_STATE_CLASS_BY_WIRE.items()},
        "android_capability_advertisement_allowed": sorted(ANDROID_FORMAL_CAPABILITY_ADVERTISEMENT_ALLOWED),
        "android_capability_advertisement_blocked": sorted(ANDROID_FORMAL_CAPABILITY_ADVERTISEMENT_BLOCKED),
        "android_closure_terminal_states": sorted(ANDROID_FORMAL_CLOSURE_TERMINAL_STATES),
        "critical_trigger_semantic_mappings": [
            {
                "trigger": m.trigger.value,
                "v2_from_state": m.v2_from_state.value,
                "v2_to_state": m.v2_to_state.value,
                "android_from_wire": m.android_from_wire,
                "android_to_wire": m.android_to_wire,
                "description": m.description,
            }
            for m in CRITICAL_TRIGGER_SEMANTIC_MAPPINGS
        ],
        "verification": report.to_dict(),
    }
