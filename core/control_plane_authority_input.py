"""Canonical control-plane backend authority input builders.

This module provides backend-facing authority input for control-plane
consumers. It intentionally reads canonical truth/governance sources directly
and does not depend on operator/projection route surfaces.
"""

from __future__ import annotations

from typing import Any, Dict


CONTROL_PLANE_BACKEND_AUTHORITY_INPUT_POLICY: str = (
    "POLICY::CONTROL_PLANE_BACKEND_AUTHORITY_INPUT_V1: "
    "control-plane backend authority input MUST be consumed from canonical "
    "truth/governance producers and MUST NOT be inferred from operator-visible "
    "projection/board/UI summaries."
)


def _derive_shared_execution_visibility(truth_payload: Dict[str, Any]) -> Dict[str, Any]:
    board = dict(truth_payload.get("operational_state_board") or {})
    task_visibility = dict(board.get("task_execution_visibility") or {})
    closure_basis = dict((truth_payload.get("runtime_decision_reasoning") or {}).get("closure_basis") or {})
    task_initiated = bool(
        task_visibility.get("task_initiated")
        or closure_basis.get("task_completed")
        or closure_basis.get("problem_solved")
    )
    result_closure_established = bool(
        task_visibility.get("result_closure_established")
        or closure_basis.get("is_fully_closed")
    )
    completion_state = "closed" if result_closure_established else ("in_progress" if task_initiated else "not_started")
    acceptance_verdict = closure_basis.get("acceptance_verdict")
    acceptance_verdict_normalized = str(acceptance_verdict or "").strip().lower()
    return {
        "task_initiated": task_initiated,
        "result_closure_established": result_closure_established,
        "completion_state": completion_state,
        "surface_execution_stage": "closed" if completion_state == "closed" else ("executing" if completion_state == "in_progress" else None),
        "acceptance_verdict": acceptance_verdict,
        "is_fully_closed": bool(closure_basis.get("is_fully_closed")),
        "authority_completion_truth": acceptance_verdict_normalized == "accept" and bool(closure_basis.get("is_fully_closed")),
        "acceptance_completion_truth": acceptance_verdict_normalized == "accept",
        "repo_mutation_completion_truth": closure_basis.get("repo_mutation_completion_truth", "unknown"),
        "operator_visible_done_summary": (
            f"completion={completion_state} | task_initiated={task_initiated} | "
            f"result_closed={result_closure_established}"
        ),
        "operator_visible_done_summary_role": "operator_visible_interpretation_only",
        "source_of_truth_refs": [
            "operational_state_board.task_execution_visibility",
            "runtime_decision_reasoning.closure_basis",
        ],
    }


def build_control_plane_backend_authority_input(
    *,
    runtime_decision_reasoning: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Build canonical backend authority input for control-plane consumers."""
    reasoning = dict(runtime_decision_reasoning or {})
    payload: Dict[str, Any] = {
        "runtime_decision_reasoning": reasoning,
        "authority_input_policy": CONTROL_PLANE_BACKEND_AUTHORITY_INPUT_POLICY,
    }

    try:
        from core.operational_readiness_surface import build_operational_readiness_report

        report = build_operational_readiness_report(route_paths=set())
        state_contract = dict(report.state_contract or {})
        closure = dict(state_contract.get("closure_quality_state") or {})
        raw = dict(state_contract.get("raw_signals") or {})
        payload["operational_state_board"] = {
            "authority": report.authority,
            "contract_version": report.contract_version,
            "task_execution_visibility": {
                "task_initiated": bool(raw.get("task_initiated")),
                "result_closure_established": bool(raw.get("result_closure_established")),
                "active_session_count": raw.get("active_session_count", 0),
                "participant_total_count": raw.get("participant_total_count", 0),
            },
            "dependencies_and_blockers": {
                "waiting_dependencies": list(
                    (dict(closure.get("waiting_dependency_state") or {}).get("evidence", {}) or {}).get(
                        "waiting_dependencies"
                    )
                    or []
                ),
                "blocked": dict(closure.get("blocked_state") or {}).get("state") == "present",
                "incomplete": dict(closure.get("incomplete_state") or {}).get("state") == "present",
            },
        }
    except Exception:
        payload["operational_state_board"] = {}

    payload["shared_execution_visibility"] = _derive_shared_execution_visibility(payload)

    try:
        from core.v2_android_truth_ssot import get_best_v2_android_truth_block

        selected_device_id = (
            reasoning.get("selected_device")
            or reasoning.get("selected_device_id")
            or reasoning.get("device_id")
            or None
        )
        block = get_best_v2_android_truth_block(selected_device_id) if selected_device_id else None
        payload["participation_truth_consumption"] = {
            "selected_device_id": selected_device_id,
            "participation_tier": reasoning.get("participation_tier"),
            "unified_mode_model": dict(reasoning.get("unified_mode_model") or {}),
            "android_truth_block": dict(block or {}),
            "completion_state": payload["shared_execution_visibility"].get("completion_state"),
            "surface_execution_stage": payload["shared_execution_visibility"].get("surface_execution_stage"),
            "source_of_truth_refs": [
                "runtime_decision_reasoning",
                "core.v2_android_truth_ssot.get_best_v2_android_truth_block",
            ],
            "_source": "core.control_plane_authority_input.build_control_plane_backend_authority_input",
        }
    except Exception:
        payload["participation_truth_consumption"] = {}

    try:
        from core.current_state_backbone_audit import build_system_backbone_snapshot

        snapshot = dict(build_system_backbone_snapshot() or {})
        mode_summary = dict(snapshot.get("mode_closure_summary") or {})
        chain_summary = dict(snapshot.get("chain_closure_summary") or {})
        layered_mode_model = dict(snapshot.get("layered_mode_model") or {})
        payload["foundational_system_truth"] = {
            "cross_device_foundation": {
                "closure_state": mode_summary.get("cross_device_mode"),
                "definition_zh": "中心把任务路由到其他设备执行，属于跨设备能力。",
            },
            "multi_device_foundation": {
                "closure_state": mode_summary.get("multi_device_participation"),
                "definition_zh": "多个设备同时接入并参与同一系统，属于多设备能力。",
            },
            "local_cross_multi_relation": {
                "local_layer": dict(layered_mode_model.get("local_layer") or {}),
                "cross_device_layer": dict(layered_mode_model.get("cross_device_layer") or {}),
                "multi_device_layer": dict(layered_mode_model.get("multi_device_layer") or {}),
            },
            "engineering_closure_three_state": {
                "code_complete_state": chain_summary.get("code_complete_state"),
                "integration_state": chain_summary.get("integration_state"),
                "acceptance_state": chain_summary.get("acceptance_state"),
            },
            "real_three_state_model": {
                "states": ["established", "partial", "open"],
            },
        }
    except Exception:
        payload["foundational_system_truth"] = {}

    return payload
