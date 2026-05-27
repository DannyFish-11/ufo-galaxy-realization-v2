from __future__ import annotations

from core.desktop_presence_system import build_desktop_presence_system_view
from core.subject_facing_foreground import (
    build_subject_facing_foreground,
    build_subject_unified_lineage,
)


def _foreground() -> dict:
    return build_subject_facing_foreground(
        visible_action_surface={
            "current_presence_mode": "liminal",
            "current_action_state": "executing",
            "lifecycle_phase": "executing",
            "lifecycle_origin": "android_device",
            "lifecycle_status_feedback": "android presence stream coupled",
            "action_trace_summary": "executing android foreground task",
            "blocker_summary": "",
            "confirmation_needed": False,
        },
        action_lifecycle_surface={
            "action_id": "runtime-1",
            "session_id": "conversation-1",
            "phase": "executing",
            "origin": "android_device",
        },
    ).to_dict()


def _continuous_ingress() -> dict:
    return {
        "authority": "CANONICAL_CONTINUOUS_INGRESS::TEST",
        "is_present": True,
        "families": {
            "desktop_continuous_stream": {"is_present": True},
            "android_device_continuous_stream": {"is_present": True},
            "runtime_stream_session_manager": {
                "is_present": True,
                "stream_state": "active",
            },
        },
    }


def test_subject_lineage_unifies_foreground_android_presence_lifecycle_and_stream():
    lineage = build_subject_unified_lineage(
        subject_foreground=_foreground(),
        action_lifecycle_surface={
            "action_id": "runtime-1",
            "session_id": "conversation-1",
            "phase": "executing",
            "origin": "android_device",
        },
        android_presence_runtime={
            "path_kind": "canonical_default",
            "device_count": 1,
            "any_presence_participant": True,
            "any_foreground_presence": True,
            "presence_participant_count": 1,
        },
        canonical_continuous_ingress=_continuous_ingress(),
        ingress_carrier_context={
            "invocation_id": "runtime-1",
            "session_id": "conversation-1",
            "control_session_id": "control-1",
            "is_android_carrier": True,
            "semantic_authority": "v2_openclawd",
        },
    )

    assert lineage["canonical_lineage_id"] == "runtime-1"
    assert lineage["subject_identity"]["android_in_unified_subject_expression"] is True
    assert "cognition_carrier" in lineage["subject_identity"]["android_roles"]
    assert "foreground_presence_surface" in lineage["subject_identity"]["android_roles"]
    assert lineage["authority_boundary"]["orchestration_authority"] == "v2_center"
    assert lineage["authority_boundary"]["participant_autonomy"] == (
        "bounded_android_participation"
    )
    assert lineage["temporal_alignment"]["foreground_event"] == "active"
    assert lineage["temporal_alignment"]["continuous_ingress_active"] is True
    assert lineage["failure_discipline"]["canonical_default_visible"] is True
    assert lineage["continuity_trace"]["replay_provenance_anchor"] == "runtime-1"
    assert set(lineage["continuity_trace"]["continuous_ingress_families"]) >= {
        "desktop_continuous_stream",
        "android_device_continuous_stream",
        "runtime_stream_session_manager",
    }


def test_subject_lineage_makes_fallback_visible_in_default_behavior():
    lineage = build_subject_unified_lineage(
        subject_foreground=_foreground(),
        action_lifecycle_surface={"action_id": "runtime-2", "phase": "executing"},
        android_presence_runtime={
            "path_kind": "fallback",
            "device_count": 0,
            "presence_participant_count": 0,
        },
        canonical_continuous_ingress={"is_present": False, "families": {}},
        ingress_carrier_context={"invocation_id": "runtime-2"},
    )

    assert lineage["failure_discipline"]["canonical_default_visible"] is False
    assert lineage["failure_discipline"]["degraded"] is True
    assert "android_presence_runtime_path=fallback" in (
        lineage["failure_discipline"]["degraded_reasons"]
    )
    assert lineage["authority_boundary"]["path_kind"] == "fallback"


def test_presence_system_panel_consumes_subject_foreground_lineage_and_stream():
    subject_fg = _foreground()
    lineage = build_subject_unified_lineage(
        subject_foreground=subject_fg,
        action_lifecycle_surface={"action_id": "runtime-panel", "phase": "executing"},
        android_presence_runtime={
            "path_kind": "canonical_default",
            "device_count": 1,
            "any_presence_participant": True,
            "presence_participant_count": 1,
        },
        canonical_continuous_ingress=_continuous_ingress(),
        ingress_carrier_context={"invocation_id": "runtime-panel"},
    )

    view = build_desktop_presence_system_view(
        state_machine_snapshot={"current_mode": "liminal"},
        dominant_tristate="liminal",
        tristate_distribution={"silent": 0, "liminal": 1, "manifest": 0},
        active_session_count=1,
        stream_runtime_status={"stream_state": "active"},
        subject_foreground=subject_fg,
        subject_unified_lineage=lineage,
        canonical_continuous_ingress=_continuous_ingress(),
    )

    panel = view["subject_panel"]
    assert panel["source_object_family"] == "subject_foreground"
    assert panel["shared_canonical_lineage_id"] == "runtime-panel"
    assert panel["subject_state"] == subject_fg["subject_state"]
    assert panel["foreground_event"] == subject_fg["foreground_event"]
    assert panel["continuous_ingress_participation"]["is_present"] is True
    assert "android_device_continuous_stream" in (
        panel["continuous_ingress_participation"]["active_families"]
    )
    assert panel["continuity_trace"]["replay_provenance_anchor"] == "runtime-panel"
    assert view["foreground_hierarchy"]["panel_subject_source"] == "subject_foreground"
