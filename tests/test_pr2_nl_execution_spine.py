from core.nl_execution_spine import (
    ANDROID_RUNTIME_INTEGRATION_POINTS,
    build_problem_execution_closure,
    build_problem_execution_spine,
)


def test_build_problem_execution_spine_marks_cross_device_android_participation():
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
    assert snap["android_integration"]["participation_mode"] == "delegated_or_takeover_participant"
    assert snap["android_integration"]["required_runtime_points"] == list(ANDROID_RUNTIME_INTEGRATION_POINTS)


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

    closed_problem = build_problem_execution_closure(
        source_channel="delegated",
        normalized_status="completed",
        truth_chain_complete=True,
        completion_notified=True,
        payload={"task_id": "t-1", "problem_closed": True},
    )
    assert closed_problem["problem_closure_stage"] == "closed"
