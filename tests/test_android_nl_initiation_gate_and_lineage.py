from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from galaxy_gateway.android.handlers import goal_execution as ge


def _build_goal_execution_message(*, goal: str = "打开微信", task_id: str = "task-1") -> dict:
    return {
        "device_id": "android-device-1",
        "payload": {
            "goal": goal,
            "task_id": task_id,
            "session_id": "session-1",
            "trace_id": "trace-1",
        },
    }


def test_goal_execution_blocked_when_cross_device_disabled() -> None:
    msg = _build_goal_execution_message()
    with patch.object(ge, "_is_cross_device_enabled", lambda: False):
        result = asyncio.run(ge.handle_goal_execution(MagicMock(), MagicMock(), msg))
    assert result["error_code"] == "ANDROID_NL_INITIATION_BLOCKED"
    assert result["details"]["lineage"]["dispatch_lineage"] == "blocked_by_cross_device_gate"
    assert result["details"]["lineage"]["policy_admitted"] is False
    assert "v2_cross_device_switch" in result["details"]["blocking_gates"]


def test_goal_execution_task_assign_contains_canonical_lineage() -> None:
    msg = _build_goal_execution_message(task_id="task-2")
    fake_runtime = SimpleNamespace(
        handle_request=AsyncMock(
            return_value={
                "success": True,
                "response": "帮你打开微信",
                "runtime_session_id": "runtime-2",
                "ingress_carrier_context": {
                    "carrier": "android_goal_execution",
                    "semantic_authority": "v2_openclawd",
                    "nl_path_type": "android_cross_device_nl",
                    "is_android_carrier": True,
                },
            }
        )
    )
    with patch.object(ge, "_is_cross_device_enabled", lambda: True), patch.object(
        ge,
        "_evaluate_android_mode_readiness",
        lambda **_: SimpleNamespace(is_dispatch_eligible=True, blocking_gates=[]),
    ), patch.object(
        ge,
        "_evaluate_execution_governance",
        lambda *_args, **_kwargs: SimpleNamespace(
            accepted=True,
            blocking_gates=[],
            rejection_reason="",
            conflict=False,
            active_conflicting_type=None,
        ),
    ), patch("core.desktop_presence_runtime.get_desktop_presence_runtime", return_value=fake_runtime):
        result = asyncio.run(ge.handle_goal_execution(MagicMock(), MagicMock(), msg))

    lineage = result["payload"]["lineage"]
    assert lineage["authority"] == "v2_authority"
    assert lineage["origin"] == "android"
    assert lineage["ingress_lineage"] == "canonical_ingress"
    assert lineage["protocol_lineage"] == "aip_v3_goal_execution"
    assert lineage["policy_admitted"] is True
    assert lineage["canonical_truth_completed"] is False
    assert lineage["mature_closure_achieved"] is False
    assert result["payload"]["main_chain_ingress"]["is_main_chain_accepted"] is True


def test_canonical_closure_flags_require_authoritative_acceptance() -> None:
    canonical, mature = ge._derive_canonical_closure_flags(
        is_fully_closed=True,
        truth_chain_complete=True,
        acceptance_verdict="accept_provisional",
        lineage_quality="canonical_success",
    )
    assert canonical is False
    assert mature is False

    canonical, mature = ge._derive_canonical_closure_flags(
        is_fully_closed=True,
        truth_chain_complete=True,
        acceptance_verdict="accept",
        lineage_quality="canonical_success",
    )
    assert canonical is True
    assert mature is True


def test_goal_execution_blocked_when_main_chain_ingress_not_accepted() -> None:
    msg = _build_goal_execution_message(task_id="task-2b")
    fake_runtime = SimpleNamespace(
        handle_request=AsyncMock(
            return_value={
                "success": True,
                "response": "帮你打开微信",
                "runtime_session_id": "runtime-2b",
                "ingress_carrier_context": {
                    "carrier": "android_goal_execution",
                    "semantic_authority": "android_local_planner",
                    "nl_path_type": "android_cross_device_nl",
                    "is_android_carrier": True,
                },
            }
        )
    )
    with patch.object(ge, "_is_cross_device_enabled", lambda: True), patch.object(
        ge,
        "_evaluate_android_mode_readiness",
        lambda **_: SimpleNamespace(is_dispatch_eligible=True, blocking_gates=[]),
    ), patch.object(
        ge,
        "_evaluate_execution_governance",
        lambda *_args, **_kwargs: SimpleNamespace(
            accepted=True,
            blocking_gates=[],
            rejection_reason="",
            conflict=False,
            active_conflicting_type=None,
        ),
    ), patch("core.desktop_presence_runtime.get_desktop_presence_runtime", return_value=fake_runtime):
        result = asyncio.run(ge.handle_goal_execution(MagicMock(), MagicMock(), msg))

    assert result["error_code"] == "ANDROID_MAIN_CHAIN_INGRESS_REJECTED"
    assert result["details"]["lineage"]["dispatch_lineage"] == "blocked_by_main_chain_ingress"
    assert result["details"]["main_chain_ingress"]["is_main_chain_accepted"] is False


def test_goal_execution_governance_reject_stamps_blocked_lineage() -> None:
    msg = _build_goal_execution_message(task_id="task-3")
    with patch.object(ge, "_is_cross_device_enabled", lambda: True), patch.object(
        ge,
        "_evaluate_android_mode_readiness",
        lambda **_: SimpleNamespace(is_dispatch_eligible=True, blocking_gates=[]),
    ), patch.object(
        ge,
        "_evaluate_execution_governance",
        lambda *_args, **_kwargs: SimpleNamespace(
            accepted=False,
            blocking_gates=["takeover_conflict"],
            rejection_reason="takeover in progress",
            conflict=True,
            active_conflicting_type=SimpleNamespace(value="takeover_request"),
        ),
    ):
        result = asyncio.run(ge.handle_goal_execution(MagicMock(), MagicMock(), msg))
    assert result["error_code"] == "GOVERNANCE_REJECTED"
    assert result["details"]["lineage"]["dispatch_lineage"] == "blocked_by_governance"
    assert "takeover_conflict" in result["details"]["blocking_gates"]


def test_participation_boundary_model_never_allows_authority_override() -> None:
    from core.android_nl_semantic_chain_contract import (
        ANDROID_PARTICIPATION_TYPES,
        get_android_participation_boundary,
    )

    for participation_type in ANDROID_PARTICIPATION_TYPES:
        boundary = get_android_participation_boundary(participation_type)
        assert boundary["may_override_v2_authority"] is False


def test_goal_execution_blocked_when_mode_gate_unavailable() -> None:
    msg = _build_goal_execution_message(task_id="task-3b")
    with patch.object(ge, "_is_cross_device_enabled", lambda: True), patch.object(
        ge, "_evaluate_android_mode_readiness", None
    ):
        result = asyncio.run(ge.handle_goal_execution(MagicMock(), MagicMock(), msg))
    assert result["error_code"] == "ANDROID_NL_INITIATION_BLOCKED"
    assert "mode_gate_unavailable" in result["details"]["blocking_gates"]


def test_goal_execution_result_lineage_replay_assisted() -> None:
    message = {
        "device_id": "android-device-1",
        "payload": {
            "task_id": "task-4",
            "status": "success",
            "session_id": "session-1",
            "trace_id": "trace-4",
            "replay": True,
        },
    }
    captured = {}

    async def _capture_store(**kwargs):
        captured.update(kwargs)

    fake_runtime = SimpleNamespace(on_goal_execution_result=AsyncMock())
    bridge = SimpleNamespace(_pending_responses={})

    with patch.object(ge, "store_task_result", _capture_store), patch.object(
        ge,
        "_run_task_result_truth_chain",
        lambda *_args, **_kwargs: SimpleNamespace(
            is_truth_chain_complete=True,
            incomplete_reason="",
        ),
    ), patch(
        "core.desktop_presence_runtime.get_desktop_presence_runtime",
        return_value=fake_runtime,
    ), patch(
        "core.durable_result_idempotency.check_result_idempotency",
        return_value=False,
    ), patch(
        "core.durable_result_idempotency.record_result_idempotency",
        return_value=None,
    ), patch(
        "contracts.cross_repo_schema_version_gate.evaluate_android_uplink_schema_gate",
        return_value=None,
    ):
        asyncio.run(ge.handle_goal_execution_result(bridge, MagicMock(), message))

    assert captured["result"]["lineage"]["lineage_quality"] == "replay_assisted"


def test_parallel_subtask_blocked_when_main_chain_ingress_unavailable() -> None:
    message = {
        "device_id": "android-device-1",
        "payload": {
            "goal": "并行执行任务",
            "task_id": "parallel-task-1",
            "session_id": "session-1",
            "trace_id": "trace-1",
        },
    }
    fake_runtime = SimpleNamespace(
        handle_request=AsyncMock(
            return_value={
                "success": True,
                "response": "并行执行任务",
                "runtime_session_id": "runtime-parallel-1",
                "ingress_carrier_context": {
                    "carrier": "android_goal_execution",
                    "semantic_authority": "v2_openclawd",
                    "nl_path_type": "android_cross_device_nl",
                    "is_android_carrier": True,
                },
            }
        )
    )
    with patch.object(ge, "_is_cross_device_enabled", lambda: True), patch.object(
        ge,
        "_evaluate_android_mode_readiness",
        lambda **_: SimpleNamespace(is_dispatch_eligible=True, blocking_gates=[]),
    ), patch.object(
        ge,
        "_evaluate_execution_governance",
        lambda *_args, **_kwargs: SimpleNamespace(
            accepted=True,
            blocking_gates=[],
            rejection_reason="",
            conflict=False,
            active_conflicting_type=None,
        ),
    ), patch.object(
        ge, "_accept_android_originated_nl_into_main_chain", None
    ), patch(
        "core.desktop_presence_runtime.get_desktop_presence_runtime",
        return_value=fake_runtime,
    ):
        result = asyncio.run(ge.handle_parallel_subtask(MagicMock(), MagicMock(), message))

    assert result["error_code"] == "ANDROID_MAIN_CHAIN_INGRESS_REJECTED"
    assert result["details"]["lineage"]["dispatch_lineage"] == "blocked_by_main_chain_ingress"


def test_goal_execution_blocked_when_main_chain_context_builder_unavailable() -> None:
    msg = _build_goal_execution_message(task_id="task-2c")
    fake_runtime = SimpleNamespace(
        handle_request=AsyncMock(
            return_value={
                "success": True,
                "response": "帮你打开微信",
                "runtime_session_id": "runtime-2c",
                "ingress_carrier_context": {
                    "carrier": "android_goal_execution",
                    "semantic_authority": "v2_openclawd",
                    "nl_path_type": "android_cross_device_nl",
                    "is_android_carrier": True,
                },
            }
        )
    )
    with patch.object(ge, "_is_cross_device_enabled", lambda: True), patch.object(
        ge,
        "_evaluate_android_mode_readiness",
        lambda **_: SimpleNamespace(is_dispatch_eligible=True, blocking_gates=[]),
    ), patch.object(
        ge,
        "_evaluate_execution_governance",
        lambda *_args, **_kwargs: SimpleNamespace(
            accepted=True,
            blocking_gates=[],
            rejection_reason="",
            conflict=False,
            active_conflicting_type=None,
        ),
    ), patch.object(
        ge, "_build_android_originated_governance_context", None
    ), patch(
        "core.desktop_presence_runtime.get_desktop_presence_runtime",
        return_value=fake_runtime,
    ):
        result = asyncio.run(ge.handle_goal_execution(MagicMock(), MagicMock(), msg))

    assert result["error_code"] == "ANDROID_MAIN_CHAIN_INGRESS_REJECTED"
    assert "main_chain_ingress_unavailable" in result["error_message"]
