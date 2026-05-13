"""core/nl_execution_spine.py
================================

Natural-language-driven center-distributed execution spine helpers.

This module builds two canonical, additive snapshots:

1) request-time ``problem_execution_spine``:
   NL request → goal/problem model → execution intent → route decision.
2) result-time ``problem_execution_closure``:
   task closure → delegated-step closure → user-problem closure.

The snapshots are intentionally additive and non-breaking.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

NL_EXECUTION_SPINE_CONTRACT_VERSION = "pr2.2.0.0"

# Cross-repo Android runtime anchors required to complete delegated/takeover
# participation semantics in the dual-repo execution spine.
# These are maintained as explicit touch-points so V2 runtime metadata can
# reference concrete Android code locations that must evolve in lockstep.
ANDROID_RUNTIME_INTEGRATION_POINTS = (
    "ufo-galaxy-android/agent/HandoffEnvelopeV2.kt",
    "ufo-galaxy-android/agent/DelegatedRuntimeUnit.kt",
    "ufo-galaxy-android/agent/AutonomousExecutionPipeline.kt",
    "ufo-galaxy-android/service/GalaxyConnectionService.kt",
    "ufo-galaxy-android/network/GalaxyWebSocketClient.kt",
    "ufo-galaxy-android/agent/DelegatedTakeoverExecutor.kt",
)
ANDROID_RESULT_REPORTING_SHAPE: Dict[str, Any] = {
    "required_fields": (
        "type",
        "task_id",
        "status",
        "result",
        "trace_id",
    ),
    "execution_intent_fields": (
        "handoff_id",
        "execution_path",
        "delegation_point",
        "remote_execution_mode",
        "source_channel",
    ),
    "problem_closure_fields": (
        "problem_closed",
        "final_answer_ready",
        "final_user_response",
        "problem_solved",
    ),
}
# Keep goal summaries compact in metadata/projection payloads.
_MAX_GOAL_TEXT_LEN = 240


def build_problem_execution_spine(
    *,
    message: str,
    source: str,
    entry_mode: Optional[str],
    metadata: Optional[Dict[str, Any]],
    execution_result: Optional[Dict[str, Any]],
    intent: Optional[str],
) -> Dict[str, Any]:
    """Build additive NL request→execution spine snapshot."""
    _md = metadata or {}
    _exec = execution_result or {}
    _exec_intent = _exec.get("execution_intent")
    _execution_path = str(_md.get("execution_path") or "none")
    _delegation_point = str(_md.get("delegation_point") or "")
    _remote_mode = str(_md.get("remote_execution_mode") or "")
    _android_selected = (
        _execution_path in ("cross_device", "hybrid")
        or bool(_md.get("remote_dispatch"))
        or source in ("android_vision", "android_goal_execution")
    )
    _route_basis = _derive_route_decision_basis(
        entry_mode=entry_mode,
        execution_path=_execution_path,
        metadata=_md,
        execution_result=_exec,
    )
    _traceability = _derive_traceability(metadata=_md, execution_result=_exec)
    return {
        "contract_version": NL_EXECUTION_SPINE_CONTRACT_VERSION,
        "traceability": _traceability,
        "nl_problem_model": {
            "raw_request": message,
            "intent": intent or "chat",
            "goal": _derive_goal(message, intent=intent, execution_intent=_exec_intent),
        },
        "execution_intent": _exec_intent or {},
        "route_decision": {
            "entry_mode": entry_mode or _md.get("entry_mode") or "local",
            "execution_path": _execution_path,
            "delegation_point": _delegation_point,
            "remote_execution_mode": _remote_mode,
            "android_participation_selected": _android_selected,
            "route_class": _derive_route_class(_execution_path),
            "decision_basis": _route_basis,
        },
        "android_integration": {
            "participation_mode": (
                "delegated_or_takeover_participant" if _android_selected else "none"
            ),
            "required_runtime_points": list(ANDROID_RUNTIME_INTEGRATION_POINTS),
            "result_reporting_shape": {
                "required_fields": list(ANDROID_RESULT_REPORTING_SHAPE["required_fields"]),
                "execution_intent_fields": list(ANDROID_RESULT_REPORTING_SHAPE["execution_intent_fields"]),
                "problem_closure_fields": list(ANDROID_RESULT_REPORTING_SHAPE["problem_closure_fields"]),
            },
        },
        "closure_state": {
            "task_closure_stage": "not_terminal",
            "delegated_step_stage": "in_progress" if _android_selected else "not_applicable",
            "problem_closure_stage": "pending_user_problem_closure",
        },
    }


def build_problem_execution_closure(
    *,
    source_channel: str,
    normalized_status: str,
    truth_chain_complete: bool,
    completion_notified: bool,
    payload: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build additive closure snapshot separating task/delegation/problem closure."""
    _payload = payload or {}
    _task_terminal = normalized_status in ("completed", "failed", "cancelled", "degraded")
    _delegated_signal = (
        source_channel in ("delegated", "canonical_ws", "compat_ws", "replay")
        or bool(_payload.get("handoff_id"))
        or bool(_payload.get("android_execution"))
    )
    _problem_closed_signal = bool(
        _payload.get("problem_closed")
        or _payload.get("final_answer_ready")
        or _payload.get("final_user_response")
        or _payload.get("problem_solved")
    )
    _task_closed = bool(_task_terminal and truth_chain_complete and completion_notified)
    _problem_closed = bool(
        _problem_closed_signal and truth_chain_complete and completion_notified
    )
    _execution_path = str(_payload.get("execution_path") or "")
    _solved_via = (
        "cross_device"
        if (
            source_channel in ("delegated", "canonical_ws", "compat_ws", "replay")
            or _execution_path in ("cross_device", "hybrid")
        )
        else "local"
    )
    _degraded_but_solved = bool(normalized_status == "degraded" and _problem_closed)
    return {
        "contract_version": NL_EXECUTION_SPINE_CONTRACT_VERSION,
        "task_closure_stage": (
            "closed"
            if _task_closed
            else "partial_or_pending"
        ),
        "delegated_step_stage": (
            "closed"
            if (_delegated_signal and _task_terminal)
            else "not_applicable" if not _delegated_signal else "pending"
        ),
        "problem_closure_stage": "closed" if _problem_closed else "pending_user_problem_closure",
        "task_completed": _task_closed,
        "problem_solved": _problem_closed,
        "problem_solved_via": _solved_via if _problem_closed else "pending",
        "degraded_but_problem_solved": _degraded_but_solved,
        "task_completion_semantics": {
            "terminal_status": _task_terminal,
            "truth_chain_complete": truth_chain_complete,
            "completion_notified": completion_notified,
            "normalized_status": normalized_status,
        },
        "problem_completion_semantics": {
            "problem_closed_signal": _problem_closed_signal,
            "requires_followup": (not _problem_closed and _task_terminal),
            "execution_quality": "degraded" if normalized_status == "degraded" else "normal",
        },
        "source_channel": source_channel,
    }


def _derive_route_class(execution_path: str) -> str:
    if execution_path == "local":
        return "local_path"
    if execution_path in ("cross_device", "hybrid"):
        return "cross_device_path"
    if execution_path in ("capability_rejected", "none"):
        return "degraded_or_noop_path"
    return "unknown_path"


def _derive_goal(
    message: str,
    *,
    intent: Optional[str],
    execution_intent: Optional[Dict[str, Any]],
) -> str:
    _safe_message = _truncate_text((message or "").strip())
    if execution_intent:
        target = execution_intent.get("target_ref")
        if target:
            return str(target)
    if intent and intent != "chat":
        return f"{intent}:{_safe_message}"
    return _safe_message


def _truncate_text(text: str) -> str:
    if len(text) <= _MAX_GOAL_TEXT_LEN:
        return text
    trimmed = text.encode("utf-8")[:_MAX_GOAL_TEXT_LEN].decode("utf-8", errors="ignore").rstrip()
    return f"{trimmed}…"


def _derive_route_decision_basis(
    *,
    entry_mode: Optional[str],
    execution_path: str,
    metadata: Dict[str, Any],
    execution_result: Dict[str, Any],
) -> Dict[str, Any]:
    _path_basis = metadata.get("execution_path_decision_basis")
    if not isinstance(_path_basis, dict):
        _path_basis = {}
    return {
        "entry_mode": entry_mode or metadata.get("entry_mode") or "local",
        "execution_path": execution_path,
        "remote_dispatch": bool(metadata.get("remote_dispatch")),
        "delegation_point": metadata.get("delegation_point") or "",
        "remote_execution_mode": metadata.get("remote_execution_mode") or "",
        "action_taken": execution_result.get("action_taken") or "none",
        "decision_source": (
            _path_basis.get("decision_source")
            or "openclawd.determine_execution_path"
        ),
    }


def _derive_traceability(
    *,
    metadata: Dict[str, Any],
    execution_result: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "trace_id": metadata.get("trace_id") or execution_result.get("trace_id") or "",
        "runtime_session_id": metadata.get("runtime_session_id") or "",
        "request_id": metadata.get("request_id") or "",
        "task_id": (
            metadata.get("task_id")
            or execution_result.get("task_id")
            or execution_result.get("execution_intent", {}).get("task_id")
            or ""
        ),
        "source_channel": metadata.get("source_channel") or "",
    }
