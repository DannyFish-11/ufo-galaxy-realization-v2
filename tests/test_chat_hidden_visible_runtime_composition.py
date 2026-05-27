from __future__ import annotations

from core.hidden_context_visible_action_surface import SurfaceLayer
from core.routes._models import ChatRequest
from core.routes.chat import (
    FOREGROUND_BLOCKED_PREFIX,
    FOREGROUND_CONFIRMATION_EXPLANATION,
    _apply_hidden_visible_boundary,
    _is_operator_request,
)


def _sample_result() -> dict:
    return {"success": True, "response": "raw operator payload"}


def test_user_vs_operator_response_composition_differs_at_runtime():
    metadata = {
        "presence_mode": "manifest",
        "runtime_decision_reasoning": {"chain": ["a", "b"]},
        "task_truth": {"owner": "operator"},
        "outward_truth": {"lineage": "deep"},
    }
    user_metadata, _, _, _ = _apply_hidden_visible_boundary(
        result=_sample_result(),
        metadata=dict(metadata),
        is_operator_request=False,
    )
    operator_metadata, _, _, _ = _apply_hidden_visible_boundary(
        result=_sample_result(),
        metadata=dict(metadata),
        is_operator_request=True,
    )
    assert "runtime_decision_reasoning" not in user_metadata
    assert "runtime_decision_reasoning" in operator_metadata
    assert user_metadata != operator_metadata


def test_operator_truth_fields_demoted_for_non_operator_by_default():
    metadata = {
        "runtime_decision_reasoning": {"debug": True},
        "task_truth": {"canonical": True},
        "outward_truth": {"raw": "internal"},
    }
    visible_metadata, _, _, demoted_fields = _apply_hidden_visible_boundary(
        result=_sample_result(),
        metadata=metadata,
        is_operator_request=False,
    )
    assert "runtime_decision_reasoning" not in visible_metadata
    assert "task_truth" not in visible_metadata
    assert "outward_truth" not in visible_metadata
    assert set(demoted_fields) == {"runtime_decision_reasoning", "task_truth", "outward_truth"}


def test_default_foreground_contains_visible_action_payload():
    metadata = {
        "presence_mode": "liminal",
        "action_trace_summary": "executing screenshot",
        "result_artifacts_summary": "1 screenshot artifact",
    }
    _, visible_action_surface, _, _ = _apply_hidden_visible_boundary(
        result=_sample_result(),
        metadata=metadata,
        is_operator_request=False,
    )
    assert visible_action_surface["current_presence_mode"] == "liminal"
    assert visible_action_surface["action_trace_summary"] == "executing screenshot"
    assert visible_action_surface["result_artifacts_summary"] == "1 screenshot artifact"
    assert visible_action_surface["current_action_state"] == "completed"


def test_blocked_execution_enforces_minimal_necessary_explanation():
    metadata = {
        "execution_blocker_summary": "device offline",
        "runtime_decision_reasoning": {"raw": "verbose internals"},
    }
    expected_explanation = f"{FOREGROUND_BLOCKED_PREFIX}device offline"
    _, visible_action_surface, response, _ = _apply_hidden_visible_boundary(
        result={"success": False, "response": "runtime_decision_reasoning dump"},
        metadata=metadata,
        is_operator_request=False,
    )
    assert response == expected_explanation
    assert visible_action_surface["blocker_summary"] == "device offline"
    assert visible_action_surface["minimal_necessary_explanation"] == expected_explanation


def test_unified_lifecycle_surface_drives_blocked_foreground_composition():
    result = {
        "success": False,
        "response": "raw runtime internals",
        "action_lifecycle_surface": {
            "phase": "blocked",
            "origin": "android_device",
            "blocker_reason": "policy_denied",
            "blocker": {"reason": "policy_denied"},
            "confirmation_needed": False,
        },
        "visible_action": {
            "status_feedback": "blocked:policy_denied",
            "confirmation_needed": False,
        },
    }
    metadata = {
        "presence_mode": "manifest",
        "blocker_summary": "",
        "execution_blocker_summary": "",
    }
    _, visible_action_surface, response, _ = _apply_hidden_visible_boundary(
        result=result,
        metadata=metadata,
        is_operator_request=False,
    )
    assert visible_action_surface["current_action_state"] == "blocked"
    assert visible_action_surface["lifecycle_phase"] == "blocked"
    assert visible_action_surface["lifecycle_origin"] == "android_device"
    assert visible_action_surface["blocker_summary"] == "policy_denied"
    assert visible_action_surface["lifecycle_status_feedback"] == "blocked:policy_denied"
    assert response == f"{FOREGROUND_BLOCKED_PREFIX}policy_denied"


def test_unified_lifecycle_confirmation_overrides_metadata_confirmation_default():
    result = {
        "success": True,
        "response": "confirm needed",
        "action_lifecycle_surface": {
            "phase": "confirmation_needed",
            "origin": "v2_center",
            "blocker_reason": "",
            "blocker": None,
            "confirmation_needed": True,
        },
        "visible_action": {"status_feedback": "confirmation_required"},
    }
    metadata = {
        "presence_mode": "liminal",
        "confirmation_needed": False,
    }
    _, visible_action_surface, response, _ = _apply_hidden_visible_boundary(
        result=result,
        metadata=metadata,
        is_operator_request=False,
    )
    assert visible_action_surface["current_action_state"] == "awaiting_confirmation"
    assert visible_action_surface["confirmation_needed"] is True
    assert visible_action_surface["lifecycle_status_feedback"] == "confirmation_required"
    assert response == FOREGROUND_CONFIRMATION_EXPLANATION


def test_layer_classifier_is_invoked_during_runtime_composition(monkeypatch):
    from core.routes import chat as chat_module

    calls = []

    def _fake_classifier(key: str):
        calls.append(key)
        if key == "runtime_decision_reasoning":
            return SurfaceLayer.OPERATOR_AUDIT_TRUTH
        return SurfaceLayer.FOREGROUND_PRESENCE_ACTION

    monkeypatch.setattr(chat_module, "classify_content_layer", _fake_classifier)
    chat_module._apply_hidden_visible_boundary(
        result=_sample_result(),
        metadata={"runtime_decision_reasoning": {"x": 1}, "presence_mode": "manifest"},
        is_operator_request=False,
    )
    assert calls == ["runtime_decision_reasoning", "presence_mode"]


def test_operator_request_detection_supports_context_hints():
    req = ChatRequest(
        message="hello",
        context=[{"response_audience": "operator"}, {"operator_mode": "true"}],
    )
    assert _is_operator_request(req) is True


def test_operator_request_detection_uses_latest_explicit_hint():
    req = ChatRequest(
        message="hello",
        context=[{"response_audience": "operator"}, {"response_audience": "user"}],
    )
    assert _is_operator_request(req) is False


def test_operator_request_detection_resolves_conflicting_hints_by_recency():
    req = ChatRequest(
        message="hello",
        context=[{"operator_mode": "true"}, {"response_audience": "user"}],
    )
    assert _is_operator_request(req) is False
