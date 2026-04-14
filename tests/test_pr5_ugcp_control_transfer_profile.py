"""Tests for PR-5 UGCP control transfer profile alignment."""

from __future__ import annotations

from core.ugcp_control_transfer_profile import (
    UGCP_CONTROL_TRANSFER_PROFILE_AUTHORITY,
    UGCP_CONTROL_TRANSFER_PROFILE_PR5_SENTINEL,
    ControlTransferFamily,
    ControlTransferState,
    ControlTransferTerminalReason,
    build_control_transfer_truth_event,
    build_transfer_merge_reason,
    can_transition,
    infer_terminal_reason,
    map_from_delegated_signal,
    map_from_dispatch_preparation_state,
    map_from_handoff_contract_status,
    map_from_takeover_status,
)


def test_sentinels_present() -> None:
    assert UGCP_CONTROL_TRANSFER_PROFILE_AUTHORITY.startswith("UGCP_CONTROL_TRANSFER_PROFILE_AUTHORITY::")
    assert "package=5" in UGCP_CONTROL_TRANSFER_PROFILE_PR5_SENTINEL


def test_state_graph_terminal_absorbing() -> None:
    assert can_transition(ControlTransferState.completed, ControlTransferState.in_progress) is False
    assert can_transition(ControlTransferState.failed, ControlTransferState.completed) is False


def test_state_graph_mainline_progression() -> None:
    assert can_transition(ControlTransferState.preparing, ControlTransferState.ready) is True
    assert can_transition(ControlTransferState.ready, ControlTransferState.dispatched) is True
    assert can_transition(ControlTransferState.adopting, ControlTransferState.resumed) is True
    assert can_transition(ControlTransferState.in_progress, ControlTransferState.completed) is True


def test_map_from_dispatch_preparation_state() -> None:
    assert map_from_dispatch_preparation_state("ready") == ControlTransferState.ready
    assert map_from_dispatch_preparation_state("failed") == ControlTransferState.failed


def test_map_from_handoff_contract_status() -> None:
    assert map_from_handoff_contract_status("draft") == ControlTransferState.preparing
    assert map_from_handoff_contract_status("sealed") == ControlTransferState.ready
    assert map_from_handoff_contract_status("expired") == ControlTransferState.expired


def test_map_from_takeover_status() -> None:
    assert map_from_takeover_status("adopted") == ControlTransferState.adopting
    assert map_from_takeover_status("succeeded") == ControlTransferState.completed
    assert map_from_takeover_status("blocked") == ControlTransferState.rejected


def test_map_from_delegated_signal() -> None:
    assert map_from_delegated_signal("ack") == ControlTransferState.dispatched
    assert map_from_delegated_signal("result", "failure") == ControlTransferState.failed
    assert map_from_delegated_signal("timeout") == ControlTransferState.timed_out


def test_terminal_reason_inference() -> None:
    assert infer_terminal_reason(ControlTransferState.failed) == ControlTransferTerminalReason.failed
    assert infer_terminal_reason(
        ControlTransferState.rejected,
        raw_reason="takeover_disallowed_by_policy",
    ) == ControlTransferTerminalReason.takeover_disallowed_by_policy


def test_build_transfer_truth_event_payload() -> None:
    event = build_control_transfer_truth_event(
        family=ControlTransferFamily.takeover,
        current_state=ControlTransferState.resumed,
        previous_state=ControlTransferState.adopting,
        trace_id="trace_1",
        task_id="task_1",
        control_session_id="ctrl_1",
        runtime_session_id="run_1",
    )

    payload = event.payload
    assert event.event_type == "ugcp.control_transfer.transition.v1"
    assert payload["profile"] == "ugcp_control_transfer_v1"
    assert payload["family"] == "takeover"
    assert payload["current_state"] == "resumed"
    assert payload["previous_state"] == "adopting"
    assert payload["is_terminal"] is False


def test_build_transfer_merge_reason() -> None:
    reason = build_transfer_merge_reason(
        family=ControlTransferFamily.delegated_execution,
        state=ControlTransferState.timed_out,
        terminal_reason=ControlTransferTerminalReason.timed_out,
    )
    assert reason == "ugcp_control_transfer_v1:delegated_execution:timed_out:timed_out"


def test_projection_alignment_sentinel_present() -> None:
    projection_path = (
        "core/routes/projection.py"
    )
    with open(projection_path, "r", encoding="utf-8") as handle:
        source = handle.read()
    assert "UGCP_CONTROL_TRANSFER_PROFILE_ALIGNED_PR5" in source
