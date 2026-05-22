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


def test_wait_for_participant_results_duplicate_same_emission_is_ignored() -> None:
    reset_android_mesh_lifecycle_store()
    payload = {
        "result": {"output": "primary", "success": True},
        "session_epoch": 7,
        "completion_emission_id": "emit-dup-1",
    }
    record_mesh_result("d1", session_id="s_wait_dup", payload=payload)
    record_mesh_result("d1", session_id="s_wait_dup", payload=payload)

    collected, wait_meta = orchestrator._wait_for_staged_mesh_participant_results(
        mesh_session_id="s_wait_dup",
        expected_device_ids=["d1"],
        timeout_seconds=0.05,
    )

    assert set(collected.keys()) == {"d1"}
    summary = wait_meta.get("participant_result_summary", {})
    assert summary.get("duplicate_ignored", 0) >= 1
    assert any(
        item.get("disposition") == "ignored" and item.get("classification") == "duplicate-ignored"
        for item in wait_meta.get("participant_result_adjudication", [])
    )


def test_wait_for_participant_results_newer_epoch_supersedes_previous() -> None:
    reset_android_mesh_lifecycle_store()
    record_mesh_result(
        "d1",
        session_id="s_wait_epoch",
        payload={
            "result": {"output": "epoch1", "success": True},
            "session_epoch": 1,
            "completion_emission_id": "emit-epoch-1",
        },
    )
    record_mesh_result(
        "d1",
        session_id="s_wait_epoch",
        payload={
            "result": {"output": "epoch3", "success": True},
            "session_epoch": 3,
            "completion_emission_id": "emit-epoch-3",
        },
    )

    collected, wait_meta = orchestrator._wait_for_staged_mesh_participant_results(
        mesh_session_id="s_wait_epoch",
        expected_device_ids=["d1"],
        timeout_seconds=0.05,
    )

    assert collected["d1"]["output"] == "epoch3"
    accepted_lineage = wait_meta.get("accepted_participant_lineage", {}).get("d1", {})
    assert accepted_lineage.get("session_epoch") == 3
    summary = wait_meta.get("participant_result_summary", {})
    assert summary.get("superseded_by_newer_epoch_session", 0) >= 1
    assert any(
        item.get("classification") == "abandoned-or-superseded"
        for item in wait_meta.get("participant_result_adjudication", [])
    )


def test_wait_for_partial_merge_stale_late_arrival_does_not_complete_missing_participant() -> None:
    reset_android_mesh_lifecycle_store()
    record_mesh_result(
        "d1",
        session_id="s_wait_stale_late",
        payload={
            "result": {"output": "d1-current", "success": True},
            "session_epoch": 9,
            "completion_emission_id": "emit-d1-current",
        },
    )
    record_mesh_result(
        "d2",
        session_id="s_wait_stale_late",
        payload={
            "result": {"output": "d2-stale", "success": True},
            "session_epoch": 1,
            "completion_emission_id": "emit-d2-stale",
            "is_stale": True,
            "stale_reason": "late_after_epoch_bump",
        },
    )

    collected, wait_meta = orchestrator._wait_for_staged_mesh_participant_results(
        mesh_session_id="s_wait_stale_late",
        expected_device_ids=["d1", "d2"],
        timeout_seconds=0.05,
    )

    assert set(collected.keys()) == {"d1"}
    assert wait_meta.get("timed_out") is True
    assert wait_meta.get("timed_out_device_ids") == ["d2"]
    summary = wait_meta.get("participant_result_summary", {})
    assert summary.get("stale_rejected", 0) >= 1
    assert any(
        item.get("participant_id") == "d2"
        and item.get("classification") == "stale-rejected"
        and item.get("disposition") == "rejected"
        for item in wait_meta.get("participant_result_adjudication", [])
    )


def test_staged_mesh_merge_outcome_exposes_accepted_ignored_rejected_participant_results(monkeypatch: Any) -> None:
    reset_android_mesh_lifecycle_store()
    monkeypatch.setattr(
        orchestrator,
        "_try_android_bridge_dispatch",
        lambda device_id, task_id, **kwargs: {"success": True, "device_id": device_id, "task_id": task_id},
    )

    session_id = "s_mesh_adjudication"
    record_mesh_result(
        "d1",
        session_id=session_id,
        payload={
            "task_id": "task_mesh_adjudication",
            "result": {"d1_output": "first", "success": True},
            "session_epoch": 2,
            "completion_emission_id": "emit-d1-1",
        },
    )
    record_mesh_result(
        "d1",
        session_id=session_id,
        payload={
            "task_id": "task_mesh_adjudication",
            "result": {"d1_output": "dup", "success": True},
            "session_epoch": 2,
            "completion_emission_id": "emit-d1-1",
        },
    )
    record_mesh_result(
        "d2",
        session_id=session_id,
        payload={
            "task_id": "task_mesh_adjudication",
            "result": {"d2_output": "stale", "success": True},
            "session_epoch": 1,
            "completion_emission_id": "emit-d2-stale",
            "is_stale": True,
        },
    )
    record_mesh_result(
        "d2",
        session_id=session_id,
        payload={
            "task_id": "task_mesh_adjudication",
            "result": {"d2_output": "current", "success": True},
            "session_epoch": 4,
            "completion_emission_id": "emit-d2-current",
        },
    )

    result = orchestrate_source_runtime_dispatch(
        trace_id="trace_mesh_adjudication",
        task_id="task_mesh_adjudication",
        source_device_id="d0",
        task={"tool_name": "mesh_task"},
        mesh_session=_mesh_session(["d1", "d2"], session_id=session_id),
    )
    body = result.result or {}
    wait_meta = body.get("participant_wait", {})
    summary = wait_meta.get("participant_result_summary", {})

    assert result.success is True
    assert set(body.get("live_participant_results", {}).keys()) == {"d1", "d2"}
    assert summary.get("current_accepted", 0) >= 2
    assert summary.get("duplicate_ignored", 0) >= 1
    assert summary.get("stale_rejected", 0) >= 1
    dispositions = {item.get("disposition") for item in wait_meta.get("participant_result_adjudication", [])}
    assert {"accepted", "ignored", "rejected"}.issubset(dispositions)


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
