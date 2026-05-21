from __future__ import annotations

from typing import Any, Dict, List

from core.mesh.android_mesh_lifecycle_store import (
    record_mesh_result,
    reset_android_mesh_lifecycle_store,
)
from core.runtime import source_dispatch_orchestrator as orchestrator
from core.runtime.source_dispatch_orchestrator import orchestrate_source_runtime_dispatch


def _mesh_session(participants: List[str], *, session_id: str = "test_mesh_session_real") -> Dict[str, Any]:
    return {
        "session_id": session_id,
        "mesh_id": "mesh_real",
        "participants": [
            {
                "device_id": did,
                "roles": ["primary" if i == 0 else "support"],
                "online": True,
                "status": "active",
            }
            for i, did in enumerate(participants)
        ],
        "multi_device_required": True,
    }


def test_wait_for_participant_results_all_completed() -> None:
    reset_android_mesh_lifecycle_store()
    record_mesh_result("d1", session_id="s_wait_all", payload={"result": {"value": 1, "success": True}})
    record_mesh_result("d2", session_id="s_wait_all", payload={"result": {"value": 2, "success": True}})

    collected, wait_meta = orchestrator._wait_for_staged_mesh_participant_results(
        mesh_session_id="s_wait_all",
        expected_device_ids=["d1", "d2"],
        timeout_seconds=0.05,
    )

    assert set(collected.keys()) == {"d1", "d2"}
    assert wait_meta["timed_out"] is False
    assert wait_meta["timed_out_device_ids"] == []


def test_wait_for_participant_results_partial_and_timeout() -> None:
    reset_android_mesh_lifecycle_store()
    record_mesh_result("d1", session_id="s_wait_partial", payload={"result": {"output": "ok", "success": True}})

    collected, wait_meta = orchestrator._wait_for_staged_mesh_participant_results(
        mesh_session_id="s_wait_partial",
        expected_device_ids=["d1", "d2"],
        timeout_seconds=0.05,
    )

    assert set(collected.keys()) == {"d1"}
    assert wait_meta["timed_out"] is True
    assert wait_meta["timed_out_device_ids"] == ["d2"]


def test_staged_mesh_orchestrator_all_completed_visible_merge(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        orchestrator,
        "_try_android_bridge_dispatch",
        lambda device_id, task_id, **kwargs: {"success": True, "device_id": device_id, "task_id": task_id},
    )
    monkeypatch.setattr(
        orchestrator,
        "_wait_for_staged_mesh_participant_results",
        lambda **kwargs: (
            {
                "d1": {"output_d1": "ok", "success": True},
                "d2": {"output_d2": "ok", "success": True},
            },
            {
                "mesh_session_id": "mesh_session_real",
                "expected_device_ids": ["d1", "d2"],
                "received_device_ids": ["d1", "d2"],
                "timed_out_device_ids": [],
                "timed_out": False,
                "wait_seconds": 0.01,
            },
        ),
    )

    result = orchestrate_source_runtime_dispatch(
        trace_id="trace_all",
        task_id="task_all",
        source_device_id="d0",
        task={"tool_name": "mesh_task"},
        mesh_session=_mesh_session(["d1", "d2"]),
    )
    body = result.result or {}

    assert result.success is True
    assert body.get("live_outcome") == "completed"
    assert body.get("mesh_completion_state") == "all_completed"
    assert body.get("canonical_result_visible") is True
    assert isinstance(body.get("live_merged_result"), dict)


def test_staged_mesh_orchestrator_partial_completion(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        orchestrator,
        "_try_android_bridge_dispatch",
        lambda device_id, task_id, **kwargs: {"success": True, "device_id": device_id, "task_id": task_id},
    )
    monkeypatch.setattr(
        orchestrator,
        "_wait_for_staged_mesh_participant_results",
        lambda **kwargs: (
            {"d1": {"output_d1": "ok", "success": True}},
            {
                "mesh_session_id": "mesh_session_real",
                "expected_device_ids": ["d1", "d2"],
                "received_device_ids": ["d1"],
                "timed_out_device_ids": ["d2"],
                "timed_out": True,
                "wait_seconds": 0.01,
            },
        ),
    )

    result = orchestrate_source_runtime_dispatch(
        trace_id="trace_partial",
        task_id="task_partial",
        source_device_id="d0",
        task={"tool_name": "mesh_task"},
        mesh_session=_mesh_session(["d1", "d2"]),
    )
    body = result.result or {}

    assert result.success is True
    assert body.get("live_outcome") == "partial"
    assert body.get("mesh_completion_state") == "partial_completed"
    assert body.get("participant_wait", {}).get("timed_out") is True


def test_staged_mesh_orchestrator_timeout_failed(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        orchestrator,
        "_try_android_bridge_dispatch",
        lambda device_id, task_id, **kwargs: {"success": True, "device_id": device_id, "task_id": task_id},
    )
    monkeypatch.setattr(
        orchestrator,
        "_wait_for_staged_mesh_participant_results",
        lambda **kwargs: (
            {},
            {
                "mesh_session_id": "mesh_session_real",
                "expected_device_ids": ["d1", "d2"],
                "received_device_ids": [],
                "timed_out_device_ids": ["d1", "d2"],
                "timed_out": True,
                "wait_seconds": 0.01,
            },
        ),
    )

    result = orchestrate_source_runtime_dispatch(
        trace_id="trace_timeout",
        task_id="task_timeout",
        source_device_id="d0",
        task={"tool_name": "mesh_task"},
        mesh_session=_mesh_session(["d1", "d2"]),
    )
    body = result.result or {}

    assert result.success is False
    assert body.get("live_outcome") == "failed"
    assert body.get("mesh_completion_state") == "failed_or_timeout"
    assert any("staged_mesh_participant_timeout" in err for err in (result.errors or []))
