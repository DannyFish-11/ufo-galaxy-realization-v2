#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for PR-2 UGCP shared schema family namespace and mapping shims."""

from __future__ import annotations

import pytest

from core.schemas.task_envelope import TaskEnvelope as ExistingTaskEnvelope
from core.schemas.ugcp import (
    UGCP_SHARED_SCHEMA_FAMILY_AUTHORITY,
    UGCP_SHARED_SCHEMA_FAMILY_PR2_SENTINEL,
    RuntimeTruth,
    TaskTruth,
    TerminalReason,
    TerminalState,
    map_from_delegated_dispatch_record,
    map_from_delegated_handoff_contract,
    map_from_message_interop_payload,
    map_from_runtime_session_snapshot,
    map_from_task_envelope,
)


def test_sentinel_strings_present() -> None:
    assert UGCP_SHARED_SCHEMA_FAMILY_AUTHORITY.startswith("UGCP_SHARED_SCHEMA_FAMILY_AUTHORITY::")
    assert UGCP_SHARED_SCHEMA_FAMILY_PR2_SENTINEL.startswith("UGCP_SHARED_SCHEMA_FAMILY_PR2_SENTINEL::")
    assert "core.schemas.ugcp.shared" in UGCP_SHARED_SCHEMA_FAMILY_AUTHORITY
    assert "namespace=core.schemas.ugcp" in UGCP_SHARED_SCHEMA_FAMILY_PR2_SENTINEL


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
