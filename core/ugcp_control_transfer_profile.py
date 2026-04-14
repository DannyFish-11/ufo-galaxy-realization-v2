"""core/ugcp_control_transfer_profile.py
=================================================
UGCP Control Transfer Profile v1 (realization-v2 side, PR-5 scope).

This module unifies center-side control-transfer semantics across:
- delegated runtime dispatch intent (pre-handoff states)
- delegated runtime handoff contracts
- target-side takeover/adoption status
- Android delegated execution transfer signals

The profile is additive and mapping-oriented: existing runtime families keep
their current contracts, while this module defines a shared vocabulary,
state graph, and truth-event bridge so those families can be interpreted as
one coherent control-transfer subprotocol.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Set

from core.schemas.ugcp.shared import TruthEvent

UGCP_CONTROL_TRANSFER_PROFILE_AUTHORITY: str = (
    "UGCP_CONTROL_TRANSFER_PROFILE_AUTHORITY::"
    "core.ugcp_control_transfer_profile is the canonical mapping authority for "
    "handoff/takeover/delegated-execution control-transfer semantics in realization-v2."
)

TRANSFER_VOCABULARY_IS_FROZEN_POLICY: str = (
    "TRANSFER_PROFILE_POLICY::TRANSFER_VOCABULARY_IS_FROZEN: "
    "Control-transfer terminology must use the canonical enums in this module "
    "for state, family, and terminal reasons."
)

TRANSFER_STATE_GRAPH_IS_CANONICAL_POLICY: str = (
    "TRANSFER_PROFILE_POLICY::TRANSFER_STATE_GRAPH_IS_CANONICAL: "
    "Allowed control-transfer transitions must follow "
    "CONTROL_TRANSFER_ALLOWED_TRANSITIONS."
)

TRANSFER_TERMINAL_REASON_IS_CANONICAL_POLICY: str = (
    "TRANSFER_PROFILE_POLICY::TRANSFER_TERMINAL_REASON_IS_CANONICAL: "
    "Terminal outcomes for handoff/takeover/delegated execution must map to "
    "ControlTransferTerminalReason."
)

TRANSFER_TRUTH_EVENT_IS_CHAIN_INPUT_POLICY: str = (
    "TRANSFER_PROFILE_POLICY::TRANSFER_TRUTH_EVENT_IS_CHAIN_INPUT: "
    "Transfer transitions should enter the canonical truth chain through "
    "TruthEvent payloads produced by build_control_transfer_truth_event()."
)

UGCP_CONTROL_TRANSFER_PROFILE_PR5_SENTINEL: str = (
    "UGCP_CONTROL_TRANSFER_PROFILE_PR5_SENTINEL::package=5::"
    "profile=ugcp-control-transfer-v1::module=core.ugcp_control_transfer_profile"
)


class ControlTransferFamily(str, Enum):
    handoff = "handoff"
    takeover = "takeover"
    delegated_execution = "delegated_execution"


class ControlTransferState(str, Enum):
    not_started = "not_started"
    preparing = "preparing"
    ready = "ready"
    dispatched = "dispatched"
    adopting = "adopting"
    resumed = "resumed"
    in_progress = "in_progress"
    completed = "completed"
    rejected = "rejected"
    cancelled = "cancelled"
    expired = "expired"
    failed = "failed"
    timed_out = "timed_out"
    unknown = "unknown"

    def is_terminal(self) -> bool:
        return self in {
            ControlTransferState.completed,
            ControlTransferState.rejected,
            ControlTransferState.cancelled,
            ControlTransferState.expired,
            ControlTransferState.failed,
            ControlTransferState.timed_out,
        }


class ControlTransferTerminalReason(str, Enum):
    none = ""
    completed = "completed"
    rejected = "rejected"
    cancelled = "cancelled"
    expired = "expired"
    failed = "failed"
    timed_out = "timed_out"
    blocked = "blocked"
    takeover_disallowed_by_policy = "takeover_disallowed_by_policy"
    session_anchor_missing = "session_anchor_missing"
    invalid_payload = "invalid_payload"
    resume_unavailable = "resume_unavailable"
    unknown = "unknown"


_TERMINAL_REASON_VALUES = {item.value for item in ControlTransferTerminalReason}


CONTROL_TRANSFER_ALLOWED_TRANSITIONS: Dict[ControlTransferState, Set[ControlTransferState]] = {
    ControlTransferState.not_started: {
        ControlTransferState.preparing,
        ControlTransferState.cancelled,
        ControlTransferState.rejected,
    },
    ControlTransferState.preparing: {
        ControlTransferState.ready,
        ControlTransferState.failed,
        ControlTransferState.cancelled,
        ControlTransferState.expired,
        ControlTransferState.rejected,
    },
    ControlTransferState.ready: {
        ControlTransferState.dispatched,
        ControlTransferState.failed,
        ControlTransferState.cancelled,
        ControlTransferState.expired,
        ControlTransferState.rejected,
    },
    ControlTransferState.dispatched: {
        ControlTransferState.adopting,
        ControlTransferState.in_progress,
        ControlTransferState.completed,
        ControlTransferState.failed,
        ControlTransferState.cancelled,
        ControlTransferState.timed_out,
    },
    ControlTransferState.adopting: {
        ControlTransferState.resumed,
        ControlTransferState.in_progress,
        ControlTransferState.failed,
        ControlTransferState.rejected,
        ControlTransferState.cancelled,
    },
    ControlTransferState.resumed: {
        ControlTransferState.in_progress,
        ControlTransferState.completed,
        ControlTransferState.failed,
        ControlTransferState.cancelled,
        ControlTransferState.timed_out,
    },
    ControlTransferState.in_progress: {
        ControlTransferState.completed,
        ControlTransferState.failed,
        ControlTransferState.cancelled,
        ControlTransferState.timed_out,
    },
    ControlTransferState.completed: set(),
    ControlTransferState.rejected: set(),
    ControlTransferState.cancelled: set(),
    ControlTransferState.expired: set(),
    ControlTransferState.failed: set(),
    ControlTransferState.timed_out: set(),
    ControlTransferState.unknown: set(),
}


@dataclass(frozen=True)
class ControlTransferTransition:
    family: ControlTransferFamily
    from_state: ControlTransferState
    to_state: ControlTransferState
    trace_id: Optional[str] = None
    task_id: Optional[str] = None
    control_session_id: Optional[str] = None
    runtime_session_id: Optional[str] = None
    terminal_reason: ControlTransferTerminalReason = ControlTransferTerminalReason.none
    source_contract: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_truth_event(self) -> TruthEvent:
        return build_control_transfer_truth_event(
            family=self.family,
            current_state=self.to_state,
            previous_state=self.from_state,
            trace_id=self.trace_id,
            task_id=self.task_id,
            control_session_id=self.control_session_id,
            runtime_session_id=self.runtime_session_id,
            terminal_reason=self.terminal_reason,
            source_contract=self.source_contract,
            metadata={**self.metadata, "transition_timestamp": self.timestamp},
        )


def _normalize_state(raw: Any) -> ControlTransferState:
    if isinstance(raw, ControlTransferState):
        return raw
    if not isinstance(raw, str):
        return ControlTransferState.unknown
    normalized = raw.strip().lower()
    try:
        return ControlTransferState(normalized)
    except ValueError:
        return ControlTransferState.unknown


def can_transition(from_state: Any, to_state: Any) -> bool:
    source = _normalize_state(from_state)
    target = _normalize_state(to_state)
    return target in CONTROL_TRANSFER_ALLOWED_TRANSITIONS.get(source, set())


def map_from_dispatch_preparation_state(state: Any) -> ControlTransferState:
    mapped = _normalize_state(state)
    return mapped if mapped != ControlTransferState.unknown else ControlTransferState.not_started


def map_from_handoff_contract_status(status: Any) -> ControlTransferState:
    raw = str(status).strip().lower() if isinstance(status, str) else ""
    mapping = {
        "draft": ControlTransferState.preparing,
        "sealed": ControlTransferState.ready,
        "dispatched": ControlTransferState.dispatched,
        "expired": ControlTransferState.expired,
        "cancelled": ControlTransferState.cancelled,
    }
    return mapping.get(raw, ControlTransferState.unknown)


def map_from_takeover_status(status: Any) -> ControlTransferState:
    raw = str(status).strip().lower() if isinstance(status, str) else ""
    mapping = {
        "pending": ControlTransferState.adopting,
        "adopted": ControlTransferState.adopting,
        "executing": ControlTransferState.in_progress,
        "succeeded": ControlTransferState.completed,
        "failed": ControlTransferState.failed,
        "blocked": ControlTransferState.rejected,
        "rejected": ControlTransferState.rejected,
    }
    return mapping.get(raw, ControlTransferState.unknown)


def map_from_delegated_signal(signal_kind: Any, result_kind: Any = None) -> ControlTransferState:
    """Map Android delegated signal kinds into canonical transfer state.

    ``result_kind`` is only meaningful when ``signal_kind == "result"``.
    If omitted/unknown, the mapping defaults to ``completed`` to stay
    consistent with the optimistic default used by delegated signal ingress.
    """
    signal = str(signal_kind).strip().lower() if isinstance(signal_kind, str) else ""
    result = str(result_kind).strip().lower() if isinstance(result_kind, str) else ""
    if signal == "ack":
        return ControlTransferState.dispatched
    if signal == "progress":
        return ControlTransferState.in_progress
    if signal == "result":
        return ControlTransferState.failed if result == "failure" else ControlTransferState.completed
    if signal == "timeout":
        return ControlTransferState.timed_out
    if signal == "cancelled":
        return ControlTransferState.cancelled
    return ControlTransferState.unknown


def infer_terminal_reason(state: Any, raw_reason: Optional[str] = None) -> ControlTransferTerminalReason:
    if isinstance(raw_reason, str):
        normalized_reason = raw_reason.strip().lower()
        if normalized_reason in _TERMINAL_REASON_VALUES:
            return ControlTransferTerminalReason(normalized_reason)
        normalized_aliases = {
            "takeover_disallowed": ControlTransferTerminalReason.takeover_disallowed_by_policy,
            "session_missing": ControlTransferTerminalReason.session_anchor_missing,
            "missing_session_anchor": ControlTransferTerminalReason.session_anchor_missing,
            "invalid_contract": ControlTransferTerminalReason.invalid_payload,
        }
        if normalized_reason in normalized_aliases:
            return normalized_aliases[normalized_reason]

    transfer_state = _normalize_state(state)
    fallback = {
        ControlTransferState.completed: ControlTransferTerminalReason.completed,
        ControlTransferState.rejected: ControlTransferTerminalReason.rejected,
        ControlTransferState.cancelled: ControlTransferTerminalReason.cancelled,
        ControlTransferState.expired: ControlTransferTerminalReason.expired,
        ControlTransferState.failed: ControlTransferTerminalReason.failed,
        ControlTransferState.timed_out: ControlTransferTerminalReason.timed_out,
    }
    return fallback.get(transfer_state, ControlTransferTerminalReason.none)


def build_control_transfer_truth_event(
    *,
    family: ControlTransferFamily,
    current_state: ControlTransferState,
    previous_state: Optional[ControlTransferState] = None,
    trace_id: Optional[str] = None,
    task_id: Optional[str] = None,
    control_session_id: Optional[str] = None,
    runtime_session_id: Optional[str] = None,
    terminal_reason: ControlTransferTerminalReason = ControlTransferTerminalReason.none,
    source_contract: str = "",
    metadata: Optional[Mapping[str, Any]] = None,
) -> TruthEvent:
    return TruthEvent(
        event_type="ugcp.control_transfer.transition.v1",
        trace_id=trace_id,
        task_id=task_id,
        control_session_id=control_session_id,
        runtime_session_id=runtime_session_id,
        payload={
            "profile": "ugcp_control_transfer_v1",
            "family": family.value,
            "current_state": current_state.value,
            "previous_state": previous_state.value if previous_state else None,
            "is_terminal": current_state.is_terminal(),
            "terminal_reason": terminal_reason.value,
            "source_contract": source_contract,
            "metadata": dict(metadata or {}),
        },
    )


def build_transfer_merge_reason(
    family: ControlTransferFamily,
    state: ControlTransferState,
    terminal_reason: ControlTransferTerminalReason = ControlTransferTerminalReason.none,
) -> str:
    if terminal_reason.value:
        return f"ugcp_control_transfer_v1:{family.value}:{state.value}:{terminal_reason.value}"
    return f"ugcp_control_transfer_v1:{family.value}:{state.value}"


__all__ = [
    "UGCP_CONTROL_TRANSFER_PROFILE_AUTHORITY",
    "TRANSFER_VOCABULARY_IS_FROZEN_POLICY",
    "TRANSFER_STATE_GRAPH_IS_CANONICAL_POLICY",
    "TRANSFER_TERMINAL_REASON_IS_CANONICAL_POLICY",
    "TRANSFER_TRUTH_EVENT_IS_CHAIN_INPUT_POLICY",
    "UGCP_CONTROL_TRANSFER_PROFILE_PR5_SENTINEL",
    "ControlTransferFamily",
    "ControlTransferState",
    "ControlTransferTerminalReason",
    "CONTROL_TRANSFER_ALLOWED_TRANSITIONS",
    "ControlTransferTransition",
    "can_transition",
    "map_from_dispatch_preparation_state",
    "map_from_handoff_contract_status",
    "map_from_takeover_status",
    "map_from_delegated_signal",
    "infer_terminal_reason",
    "build_control_transfer_truth_event",
    "build_transfer_merge_reason",
]
