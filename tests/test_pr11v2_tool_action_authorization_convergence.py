from __future__ import annotations

import asyncio


def _run(coro):
    return asyncio.run(coro)


def _make_openclawd():
    from core.openclawd import OpenClawd

    oc = OpenClawd.__new__(OpenClawd)
    oc._node_registry = {}
    oc._node_cache = {}
    oc._node_id_to_key = {}
    oc._skills = {}
    oc._mcp_tools = {}
    oc._pr8_trace_id = ""
    oc._pr8_session_id = ""
    oc._CORE_NODE_ACTIONS = {}
    oc._continuum_orchestrator = None
    oc._tool_permission_checker = None
    return oc


def test_execution_plan_defaults_are_intent_only():
    from core.schemas.execution_plan import build_execution_plan, plan_summary

    plan = build_execution_plan(execution_path="cross_device", delegation_point="single_remote")
    assert plan.metadata["intent_truth"] == "planned_not_executed"
    assert plan.metadata["tool_invocation_truth"] == "not_invoked_by_plan"
    assert plan.metadata["side_effect_execution_truth"] == "not_executed_by_plan"
    assert plan.metadata["repo_mutation_authorization_truth"] == "not_authorized_by_plan"

    summary = plan_summary(plan)
    assert summary["intent_truth"] == "planned_not_executed"
    assert summary["tool_invocation_truth"] == "not_invoked_by_plan"
    assert summary["side_effect_execution_truth"] == "not_executed_by_plan"
    assert summary["repo_mutation_authorization_truth"] == "not_authorized_by_plan"


def test_self_healing_apply_does_not_claim_repo_mutation_without_operator_approval():
    from core.self_improvement import SelfHealingLoop

    loop = SelfHealingLoop()
    proposal = loop.submit_diagnosis("issue")
    loop.attach_context(proposal.proposal_id, {})
    loop.plan_patch(proposal.proposal_id, "patch")
    result = loop.apply_patch(
        proposal.proposal_id,
        {"repo_mutation_applied": True, "operator_approved": False},
    )
    assert result["success"] is True
    assert result["tool_invocation_truth"]["invoked"] is True
    assert result["side_effect_authorization"]["authorization_status"] == "not_authorized"
    assert result["repo_mutation_truth"]["mutation_reported"] is True
    assert result["repo_mutation_truth"]["mutation_applied"] is False


def test_self_healing_apply_reports_repo_mutation_only_when_approved():
    from core.self_improvement import SelfHealingLoop

    loop = SelfHealingLoop()
    proposal = loop.submit_diagnosis("issue")
    loop.attach_context(proposal.proposal_id, {})
    loop.plan_patch(proposal.proposal_id, "patch")
    result = loop.apply_patch(
        proposal.proposal_id,
        {"repo_mutation_applied": True, "operator_approved": True},
    )
    assert result["success"] is True
    assert result["side_effect_authorization"]["authorization_status"] == "authorized"
    assert result["repo_mutation_truth"]["mutation_applied"] is True


def test_openclawd_engineer_apply_emits_intent_authority_truth_contract():
    from core.self_improvement import reset_self_healing_loop

    reset_self_healing_loop()
    oc = _make_openclawd()
    r1 = _run(oc._dispatch_engineer_tool("diagnose", {"issue_summary": "x"}))
    pid = r1["proposal_id"]
    _run(oc._dispatch_engineer_tool("context", {"proposal_id": pid, "context": {}}))
    _run(oc._dispatch_engineer_tool("plan", {"proposal_id": pid, "patch_content": "fix"}))

    applied = _run(oc._dispatch_engineer_tool("apply", {"proposal_id": pid}))
    assert applied["success"] is True
    assert applied["runtime_authority"] == "OpenClawd/SelfHealingLoop"
    assert applied["tool_invocation_truth"]["tool_name"] == "engineer__apply"
    assert applied["planner_intent_truth"]["intent_only"] is True


def test_command_router_stamps_tool_and_repo_truth_fields():
    from core.command_router import CommandRouter
    from core.schemas.task_envelope import TaskEnvelope

    async def _executor(*_args, **_kwargs):
        return {"ok": True}

    router = CommandRouter(executor=_executor)
    envelope = TaskEnvelope(
        tool_name="ping",
        targets=["dev-1"],
        args={"x": 1},
    )
    result = _run(router.route_envelope(envelope))

    assert "tool_invocation_truth" in result
    assert result["tool_invocation_truth"]["route_envelope_invoked"] is True
    assert "repo_mutation_truth" in result
    assert result["repo_mutation_truth"]["mutation_applied"] is False
