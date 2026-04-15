#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for PR-2 UGCP shared schema family namespace and mapping shims."""

from __future__ import annotations

import pytest

from core.schemas.task_envelope import TaskEnvelope as ExistingTaskEnvelope
from core.schemas.ugcp import (
    ParticipantKind,
    ParticipantRuntimeTier,
    ParticipantTier,
    ParticipantState,
    UGCP_CANONICAL_PARTICIPANT_TIERS_PR3_SENTINEL,
    UGCP_CANONICAL_PARTICIPANT_MODEL_PR52_SENTINEL,
    UGCP_SHARED_SCHEMA_FAMILY_AUTHORITY,
    UGCP_SHARED_SCHEMA_FAMILY_PR2_SENTINEL,
    map_from_device_participation_summary,
    RuntimeTruth,
    TaskTruth,
    TerminalReason,
    TerminalState,
    map_from_delegated_dispatch_record,
    map_from_delegated_handoff_contract,
    map_from_message_interop_payload,
    map_from_node_participant_record,
    map_from_runtime_participant_surface,
    map_from_runtime_session_snapshot,
    map_from_task_envelope,
)


def test_sentinel_strings_present() -> None:
    assert UGCP_SHARED_SCHEMA_FAMILY_AUTHORITY.startswith("UGCP_SHARED_SCHEMA_FAMILY_AUTHORITY::")
    assert UGCP_SHARED_SCHEMA_FAMILY_PR2_SENTINEL.startswith("UGCP_SHARED_SCHEMA_FAMILY_PR2_SENTINEL::")
    assert "core.schemas.ugcp.shared" in UGCP_SHARED_SCHEMA_FAMILY_AUTHORITY
    assert "namespace=core.schemas.ugcp" in UGCP_SHARED_SCHEMA_FAMILY_PR2_SENTINEL


def test_pr52_participant_model_sentinel_present() -> None:
    assert UGCP_CANONICAL_PARTICIPANT_MODEL_PR52_SENTINEL.startswith(
        "UGCP_CANONICAL_PARTICIPANT_MODEL_PR52_SENTINEL::"
    )
    assert "participant_identity_runtime_tier" in UGCP_CANONICAL_PARTICIPANT_MODEL_PR52_SENTINEL


def test_pr3_participant_tiers_sentinel_present() -> None:
    assert UGCP_CANONICAL_PARTICIPANT_TIERS_PR3_SENTINEL.startswith(
        "UGCP_CANONICAL_PARTICIPANT_TIERS_PR3_SENTINEL::"
    )
    assert "full_runtime_host" in UGCP_CANONICAL_PARTICIPANT_TIERS_PR3_SENTINEL


def test_truth_objects_to_dict() -> None:
    task_truth = TaskTruth(
        task_id="task_1",
        terminal_state=TerminalState("completed"),
        terminal_reason=TerminalReason("ok"),
    )
    runtime_truth = RuntimeTruth(
        runtime_session_id="rt_1",
        runtime_status="completed",
        terminal_state=TerminalState("completed"),
        terminal_reason=TerminalReason("ok"),
    )

    assert task_truth.to_dict()["terminal_state"] == "completed"
    assert runtime_truth.to_dict()["runtime_session_id"] == "rt_1"


@pytest.mark.parametrize("state", ["completed", "failed", "partial", "interrupted"])
def test_truth_objects_support_all_terminal_states(state: str) -> None:
    task_truth = TaskTruth(task_id="task_x", terminal_state=TerminalState(state))
    runtime_truth = RuntimeTruth(runtime_session_id="rt_x", terminal_state=TerminalState(state))
    assert task_truth.to_dict()["terminal_state"] == state
    assert runtime_truth.to_dict()["terminal_state"] == state


def test_map_from_existing_task_envelope_maps_session_to_control_session() -> None:
    existing = ExistingTaskEnvelope(
        task_id="task_1",
        trace_id="trace_1",
        session_id="sess_1",
        source="source_node",
        targets=["target_node"],
        tool_name="demo",
        args={"x": 1},
    )

    mapped = map_from_task_envelope(existing)

    assert mapped.task_id == "task_1"
    assert mapped.trace_id == "trace_1"
    assert mapped.control_session_id == "sess_1"
    assert mapped.source_node_id == "source_node"
    assert mapped.target_node_id == "target_node"


@pytest.mark.parametrize(
    "targets,expected,use_dict",
    [
        ([], None, False),
        ([123], None, True),
        (["target_ok", "target_other"], "target_ok", False),
    ],
)
def test_map_from_existing_task_envelope_handles_target_edge_cases(targets, expected, use_dict) -> None:
    existing = (
        {"task_id": "task_edge", "trace_id": "trace_edge", "targets": targets}
        if use_dict
        else ExistingTaskEnvelope(task_id="task_edge", trace_id="trace_edge", targets=targets)
    )
    mapped = map_from_task_envelope(existing)
    assert mapped.target_node_id == expected


def test_map_from_delegated_dispatch_record_uses_dispatch_id_aliases() -> None:
    record = {
        "dispatch_id": "dispatch_1",
        "delegation_intent": "delegate",
        "reason": "eligible",
        "metadata": {"k": "v"},
    }

    mapped = map_from_delegated_dispatch_record(record)

    assert mapped.execution_instance_id == "dispatch_1"
    assert mapped.dispatch_mode == "delegate"
    assert mapped.effective_mode == "delegate"
    assert mapped.decision_reason == "eligible"


def test_map_from_delegated_handoff_contract_maps_identity_payload_meta() -> None:
    contract = {
        "identity": {"session_id": "sess_2", "device_id": "android_1"},
        "payload": {"task_id": "task_2"},
        "meta": {"source_device_id": "source_2"},
        "reason": "handoff",
    }

    mapped = map_from_delegated_handoff_contract(contract)

    assert mapped.task_id == "task_2"
    assert mapped.control_session_id == "sess_2"
    assert mapped.runtime_session_id == "sess_2"
    assert mapped.source_node_id == "source_2"
    assert mapped.target_node_id == "android_1"


def test_map_from_runtime_session_snapshot_maps_terminal_states() -> None:
    snapshot = {
        "identity": {"session_id": "rt_3"},
        "status": "failed",
        "reason": "timeout",
    }

    mapped = map_from_runtime_session_snapshot(snapshot)

    assert mapped.runtime_session_id == "rt_3"
    assert mapped.runtime_status == "failed"
    assert mapped.terminal_state.value == "failed"
    assert mapped.terminal_reason.value == "timeout"


def test_map_from_message_interop_payload_accepts_context_session_id() -> None:
    payload = {
        "request_id": "task_4",
        "trace_id": "trace_4",
        "context": {"session_id": "sess_4"},
        "source": "bridge",
        "action": "click",
        "payload": {"ref": "el_1"},
    }

    mapped = map_from_message_interop_payload(payload)

    assert mapped.task_id == "task_4"
    assert mapped.trace_id == "trace_4"
    assert mapped.control_session_id == "sess_4"
    assert mapped.source_node_id == "bridge"
    assert mapped.tool_name == "click"
    assert mapped.args == {"ref": "el_1"}


def test_map_from_node_participant_record_maps_service_node_command_only() -> None:
    mapped = map_from_node_participant_record(
        {
            "node_id": "svc-1",
            "architectural_class": "service_node",
            "role": "tool",
            "status": "healthy",
            "capabilities": ["ocr", "extract"],
        }
    )

    assert mapped.participant_id == "svc-1"
    assert mapped.participant_kind is ParticipantKind.SERVICE_NODE
    assert mapped.runtime_tier is ParticipantRuntimeTier.COMMAND_ONLY
    assert mapped.participant_tier is ParticipantTier.COMMAND_ENDPOINT
    assert mapped.participation_state is ParticipantState.READY
    assert mapped.supports_capability_linkage is True


def test_map_from_device_participation_summary_maps_full_runtime_host() -> None:
    mapped = map_from_device_participation_summary(
        {
            "device_id": "dev-1",
            "runtime_present": True,
            "orchestration_eligible": True,
            "registered": True,
            "routable": True,
            "session_id": "rt-1",
            "roles": ["participant"],
            "capabilities": ["screen", "touch"],
        }
    )

    assert mapped.participant_id == "dev-1"
    assert mapped.participant_kind is ParticipantKind.DEVICE_RUNTIME_HOST
    assert mapped.runtime_tier is ParticipantRuntimeTier.FULL_RUNTIME
    assert mapped.participant_tier is ParticipantTier.FULL_RUNTIME_HOST
    assert mapped.participation_state is ParticipantState.ACTIVE
    assert mapped.supports_attached_session is True
    assert mapped.supports_local_execution is True


def test_map_from_runtime_participant_surface_maps_observer_role() -> None:
    mapped = map_from_runtime_participant_surface(
        {
            "source_device_id": "dev-obs",
            "source_runtime_posture": "join_runtime",
            "coordination_role": "observer_only",
            "runtime_session_id": "rs-obs",
        }
    )
    assert mapped.participant_id == "dev-obs"
    assert mapped.participant_kind is ParticipantKind.OBSERVER
    assert mapped.runtime_tier is ParticipantRuntimeTier.OBSERVER_ONLY
    assert mapped.participant_tier is ParticipantTier.OBSERVER_ENDPOINT
    assert mapped.participation_state is ParticipantState.ACTIVE
    assert mapped.supports_delegation is False


def test_map_from_device_participation_summary_maps_partial_runtime_node() -> None:
    mapped = map_from_device_participation_summary(
        {
            "device_id": "dev-partial",
            "runtime_present": True,
            "orchestration_eligible": False,
            "registered": True,
            "routable": True,
        }
    )
    assert mapped.runtime_tier is ParticipantRuntimeTier.PARTIAL_RUNTIME
    assert mapped.participant_tier is ParticipantTier.PARTIAL_RUNTIME_NODE
