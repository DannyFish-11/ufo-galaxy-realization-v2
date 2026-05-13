from core.nl_execution_spine import (
    ANDROID_RUNTIME_INTEGRATION_POINTS,
    build_problem_execution_closure,
    build_problem_execution_spine,
)


def test_spine_cross_device_android_participation():
    snap = build_problem_execution_spine(
        message="帮我在手机上打开微信并回复",
        source="chat",
        entry_mode="cross_device",
        metadata={
            "execution_path": "cross_device",
            "delegation_point": "android_gateway",
            "remote_execution_mode": "agent_runtime",
            "remote_dispatch": True,
        },
        execution_result={"execution_intent": {"target_ref": "android:wechat"}},
        intent="goal_execution",
    )
    assert snap["route_decision"]["route_class"] == "cross_device_path"
    assert snap["route_decision"]["android_participation_selected"] is True
    assert snap["route_decision"]["decision_basis"]["decision_source"] == "openclawd.determine_execution_path"
    assert snap["android_integration"]["participation_mode"] == "delegated_or_takeover_participant"
    assert snap["android_integration"]["required_runtime_points"] == list(ANDROID_RUNTIME_INTEGRATION_POINTS)
    assert "required_fields" in snap["android_integration"]["result_reporting_shape"]


def test_build_problem_execution_closure_separates_task_and_problem_closure():
    closure = build_problem_execution_closure(
        source_channel="delegated",
        normalized_status="completed",
        truth_chain_complete=True,
        completion_notified=True,
        payload={"task_id": "t-1"},
    )
    assert closure["task_closure_stage"] == "closed"
    assert closure["delegated_step_stage"] == "closed"
    assert closure["problem_closure_stage"] == "pending_user_problem_closure"
    assert closure["task_completed"] is True
    assert closure["problem_solved"] is False

    closed_problem = build_problem_execution_closure(
        source_channel="delegated",
        normalized_status="completed",
        truth_chain_complete=True,
        completion_notified=True,
        payload={"task_id": "t-1", "problem_closed": True},
    )
    assert closed_problem["problem_closure_stage"] == "closed"
    assert closed_problem["problem_solved"] is True
    assert closed_problem["problem_solved_via"] == "cross_device"


def test_build_problem_execution_closure_allows_degraded_but_solved():
    closure = build_problem_execution_closure(
        source_channel="delegated",
        normalized_status="degraded",
        truth_chain_complete=True,
        completion_notified=True,
        payload={"task_id": "t-2", "final_user_response": "done with workaround"},
    )
    assert closure["task_completed"] is True
    assert closure["problem_solved"] is True
    assert closure["degraded_but_problem_solved"] is True


def test_spine_goal_truncation_handles_multibyte_chars():
    long_message = "你好" * 200
    snap = build_problem_execution_spine(
        message=long_message,
        source="chat",
        entry_mode="local",
        metadata={"execution_path": "local"},
        execution_result={"execution_intent": {}},
        intent="goal_execution",
    )
    goal = snap["nl_problem_model"]["goal"]
    assert goal.startswith("goal_execution:")
    assert goal.endswith("…")
    goal.encode("utf-8")


def test_spine_traceability_propagates_trace_id():
    snap = build_problem_execution_spine(
        message="帮我总结今天完成情况",
        source="chat",
        entry_mode="local",
        metadata={
            "execution_path": "local",
            "trace_id": "trace-123",
            "runtime_session_id": "rs-123",
            "request_id": "req-123",
        },
        execution_result={"execution_intent": {"task_id": "task-123"}},
        intent="chat",
    )
    assert snap["traceability"]["trace_id"] == "trace-123"
    assert snap["traceability"]["runtime_session_id"] == "rs-123"
    assert snap["traceability"]["task_id"] == "task-123"
