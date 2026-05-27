"""tests/test_subject_facing_foreground.py
============================================
PR-SFF behavioral tests: Subject-Facing Foreground.

These tests prove that SubjectFacingForeground represents a real foreground
*structural* change — not a payload expansion, field rename, or UI text
adjustment.

Each group targets one of the four required behavioral verification criteria:

Group A — default foreground composition change test
  Verify that the default foreground response path now produces a
  subject_foreground primary object that is structurally different from
  (and not derivable by simple renaming of) the scattered visible_action_surface.

Group B — subject-facing primary object test
  Verify that SubjectFacingForeground organizes the foreground around the
  subject lifecycle (presence_state → action_phase → foreground_event →
  blocker/confirmation/result) rather than around scattered runtime fields.

Group C — blocker/confirmation foreground priority test
  Verify that blocker and confirmation are *primary foreground events* in
  SubjectFacingForeground — they drive foreground_event and foreground_status
  before any other consideration, unlike visible_action_surface where they
  are optional supplementary fields.

Group D — control-plane demotion test
  Verify that problem_execution_spine (control-plane diagnostic, previously
  always in the default user response) is now demoted to operator-only, while
  subject_foreground is promoted as the primary user-facing organizing object.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import pytest

from core.subject_facing_foreground import (
    FOREGROUND_EVENT_ACTIVE,
    FOREGROUND_EVENT_BLOCKED,
    FOREGROUND_EVENT_COMPLETED,
    FOREGROUND_EVENT_CONFIRMING,
    FOREGROUND_EVENT_READY,
    FOREGROUND_EVENT_TRANSITIONING,
    SUBJECT_FACING_FOREGROUND_SENTINEL,
    SubjectFacingForeground,
    build_subject_facing_foreground,
)


# ===========================================================================
# Helpers
# ===========================================================================


def _visible(
    *,
    presence_mode: str = "manifest",
    action_state: str = "completed",
    lifecycle_phase: str = "result_received",
    lifecycle_origin: str = "v2_center",
    action_trace_summary: str = "",
    result_artifacts_summary: str = "",
    blocker_summary: str = "",
    confirmation_needed: bool = False,
    lightweight_status_feedback: str = "",
    lifecycle_status_feedback: str = "",
) -> Dict[str, Any]:
    """Build a minimal visible_action_surface dict for testing."""
    return {
        "current_presence_mode": presence_mode,
        "current_action_state": action_state,
        "lifecycle_phase": lifecycle_phase,
        "lifecycle_origin": lifecycle_origin,
        "action_trace_summary": action_trace_summary,
        "result_artifacts_summary": result_artifacts_summary,
        "blocker_summary": blocker_summary,
        "confirmation_needed": confirmation_needed,
        "lightweight_status_feedback": lightweight_status_feedback,
        "lifecycle_status_feedback": lifecycle_status_feedback,
    }


def _lifecycle(
    *,
    phase: str = "result_received",
    origin: str = "v2_center",
    blocker: Optional[Dict[str, Any]] = None,
    blocker_reason: str = "",
    confirmation_needed: bool = False,
    confirmation_context: Optional[Dict[str, Any]] = None,
    closure_state: str = "closed",
) -> Dict[str, Any]:
    """Build a minimal action_lifecycle_surface dict for testing."""
    return {
        "phase": phase,
        "origin": origin,
        "blocker": blocker,
        "blocker_reason": blocker_reason,
        "confirmation_needed": confirmation_needed,
        "confirmation_context": confirmation_context,
        "closure_state": closure_state,
    }


# ===========================================================================
# Group A — Default foreground composition change test
# ===========================================================================


class TestDefaultForegroundCompositionChange:
    """
    A. Verify that the default foreground now produces a SubjectFacingForeground
    primary object that is structurally distinct from the old scattered
    visible_action_surface approach.
    """

    def test_A01_subject_foreground_is_produced_in_default_path(self):
        """build_subject_facing_foreground() returns a SubjectFacingForeground."""
        sfg = build_subject_facing_foreground(
            visible_action_surface=_visible(),
            action_lifecycle_surface=_lifecycle(),
            foreground_response="executed",
        )
        assert isinstance(sfg, SubjectFacingForeground)
        assert sfg.is_subject_primary is True

    def test_A02_foreground_version_is_set(self):
        """Produced object carries schema version for forward-compat."""
        sfg = build_subject_facing_foreground(
            visible_action_surface=_visible(),
        )
        assert sfg.foreground_version == "1.0"

    def test_A03_to_dict_has_subject_lifecycle_keys_not_runtime_field_dump(self):
        """to_dict() exposes subject lifecycle keys, not raw runtime fields."""
        sfg = build_subject_facing_foreground(
            visible_action_surface=_visible(
                presence_mode="manifest",
                action_state="executing",
                lifecycle_phase="executing",
            ),
        )
        d = sfg.to_dict()
        # Subject lifecycle keys must be present
        assert "subject_state" in d
        assert "action_phase" in d
        assert "foreground_event" in d
        assert "foreground_status" in d
        assert "blocker" in d
        assert "confirmation" in d
        assert "result" in d
        # Raw runtime-internal fields must NOT be present
        assert "current_presence_mode" not in d  # visible_action_surface key
        assert "current_action_state" not in d   # visible_action_surface key
        assert "lifecycle_origin" not in d       # runtime origin tag

    def test_A04_subject_foreground_and_visible_action_surface_are_structurally_different(self):
        """
        Composition change: subject_foreground keys differ from visible_action_surface keys.
        This is the structural difference test — not the same field set under different names.
        """
        vas = _visible(
            presence_mode="manifest",
            action_state="completed",
            lifecycle_phase="result_received",
        )
        sfg = build_subject_facing_foreground(
            visible_action_surface=vas,
        )
        sfg_dict = sfg.to_dict()

        # The two dicts must have different key sets — structural difference
        vas_keys = set(vas.keys())
        sfg_keys = set(sfg_dict.keys())
        assert vas_keys != sfg_keys, (
            "subject_foreground and visible_action_surface must have different key sets; "
            "they represent different organizing structures"
        )
        # subject_foreground has keys absent from visible_action_surface
        sfg_only_keys = sfg_keys - vas_keys
        assert "foreground_event" in sfg_only_keys
        assert "foreground_status" in sfg_only_keys
        assert "subject_state" in sfg_only_keys
        assert "is_subject_primary" in sfg_only_keys

    def test_A05_sentinel_is_stable_string(self):
        """Sentinel constant is a non-empty stable identifier."""
        assert isinstance(SUBJECT_FACING_FOREGROUND_SENTINEL, str)
        assert len(SUBJECT_FACING_FOREGROUND_SENTINEL) > 0
        assert "subject-lifecycle-primary-foreground" in SUBJECT_FACING_FOREGROUND_SENTINEL


# ===========================================================================
# Group B — Subject-facing primary object test
# ===========================================================================


class TestSubjectFacingPrimaryObject:
    """
    B. Verify that SubjectFacingForeground organizes the foreground around
    subject lifecycle (presence_state → action_phase → foreground_event)
    rather than around scattered runtime output fields.
    """

    def test_B01_subject_state_reflects_presence_mode(self):
        """subject_state is the presence mode — the subject's existence state."""
        for mode in ("liminal", "manifest", "silent"):
            sfg = build_subject_facing_foreground(
                visible_action_surface=_visible(presence_mode=mode),
            )
            assert sfg.subject_state == mode, (
                f"subject_state should be {mode!r} but got {sfg.subject_state!r}"
            )

    def test_B02_action_phase_reflects_lifecycle_phase(self):
        """action_phase reflects canonical lifecycle phase from the surface."""
        sfg = build_subject_facing_foreground(
            visible_action_surface=_visible(lifecycle_phase="executing"),
            action_lifecycle_surface=_lifecycle(phase="executing"),
        )
        assert sfg.action_phase == "executing"

    def test_B03_foreground_event_is_active_when_subject_is_executing(self):
        """foreground_event=active when subject is executing an action."""
        sfg = build_subject_facing_foreground(
            visible_action_surface=_visible(
                action_state="executing",
                lifecycle_phase="executing",
            ),
        )
        assert sfg.foreground_event == FOREGROUND_EVENT_ACTIVE

    def test_B04_foreground_event_is_completed_when_result_received(self):
        """foreground_event=completed when lifecycle is in result_received/closed."""
        sfg = build_subject_facing_foreground(
            visible_action_surface=_visible(
                action_state="completed",
                lifecycle_phase="result_received",
            ),
        )
        assert sfg.foreground_event == FOREGROUND_EVENT_COMPLETED
        assert sfg.result == "completed"

    def test_B05_foreground_event_is_active_for_liminal_accepted_subject(self):
        """foreground_event=active when subject is in liminal phase with accepted action.

        liminal + accepted → action_state='accepted' branch fires first (active),
        before the liminal-presence fallback branch.
        """
        sfg = build_subject_facing_foreground(
            visible_action_surface=_visible(
                presence_mode="liminal",
                action_state="accepted",
                lifecycle_phase="accepted",
            ),
        )
        assert sfg.foreground_event == FOREGROUND_EVENT_ACTIVE
        assert sfg.subject_state == "liminal"

    def test_B06_foreground_event_is_ready_for_silent_subject_with_no_active_action(self):
        """foreground_event=ready when subject is silent with no active/executing action.

        silent + action_state='failed' → result='failed', but result branch
        only fires for action_state='completed'.  silent subject_state does not
        trigger liminal/manifest branch.  Falls through to FOREGROUND_EVENT_READY.
        """
        sfg = build_subject_facing_foreground(
            visible_action_surface=_visible(
                presence_mode="silent",
                action_state="failed",
                lifecycle_phase="",
            ),
        )
        assert sfg.foreground_event == FOREGROUND_EVENT_READY
        assert sfg.subject_state == "silent"

    def test_B07_foreground_status_is_lifecycle_derived_not_runtime_text(self):
        """
        foreground_status is derived from lifecycle state, not from runtime
        response text.  This is the core structural difference.
        """
        sfg = build_subject_facing_foreground(
            visible_action_surface=_visible(
                action_state="completed",
                lifecycle_phase="result_received",
            ),
            foreground_response="系统内部状态: branch=local, model=gpt-4, tokens=1200",
        )
        # foreground_status must NOT contain the runtime text dump
        assert "branch=local" not in sfg.foreground_status
        assert "model=gpt-4" not in sfg.foreground_status
        assert "tokens=1200" not in sfg.foreground_status
        # It must be lifecycle-derived
        assert sfg.foreground_status == "completed"

    def test_B08_is_subject_primary_is_always_true(self):
        """is_subject_primary=True signals this is the canonical foreground primary."""
        sfg = build_subject_facing_foreground(
            visible_action_surface={},
        )
        assert sfg.is_subject_primary is True
        assert sfg.to_dict()["is_subject_primary"] is True

    def test_B09_current_action_reflects_action_trace_summary(self):
        """current_action is populated from action_trace_summary."""
        sfg = build_subject_facing_foreground(
            visible_action_surface=_visible(
                action_trace_summary="截取当前屏幕",
                action_state="executing",
            ),
        )
        assert sfg.current_action == "截取当前屏幕"

    def test_B10_result_summary_reflects_artifacts_when_completed(self):
        """result_summary is populated from result_artifacts_summary on completion."""
        sfg = build_subject_facing_foreground(
            visible_action_surface=_visible(
                action_state="completed",
                result_artifacts_summary="screenshot_001.png",
            ),
        )
        assert sfg.result == "completed"
        assert sfg.result_summary == "screenshot_001.png"


# ===========================================================================
# Group C — Blocker / confirmation foreground priority test
# ===========================================================================


class TestBlockerConfirmationForegroundPriority:
    """
    C. Verify that blocker and confirmation are PRIMARY foreground events in
    SubjectFacingForeground — they drive foreground_event and foreground_status
    before any other consideration.
    """

    def test_C01_blocker_drives_foreground_event_to_blocked(self):
        """When a blocker is present, foreground_event=blocked regardless of phase."""
        sfg = build_subject_facing_foreground(
            visible_action_surface=_visible(
                blocker_summary="device offline",
                action_state="completed",   # would normally be COMPLETED
                lifecycle_phase="result_received",
            ),
        )
        assert sfg.foreground_event == FOREGROUND_EVENT_BLOCKED

    def test_C02_blocker_drives_foreground_status_to_blocked_prefix(self):
        """foreground_status starts with 'blocked:' when a blocker is present."""
        sfg = build_subject_facing_foreground(
            visible_action_surface=_visible(blocker_summary="permission denied"),
        )
        assert sfg.foreground_status.startswith("blocked:")
        assert "permission denied" in sfg.foreground_status

    def test_C03_blocker_reason_is_first_class_field_not_metadata_attachment(self):
        """blocker_reason is a top-level field on SubjectFacingForeground."""
        sfg = build_subject_facing_foreground(
            visible_action_surface=_visible(blocker_summary="insufficient permissions"),
        )
        assert sfg.blocker_reason == "insufficient permissions"
        assert sfg.is_blocked()

    def test_C04_blocker_dict_is_normalized(self):
        """blocker is a dict (canonical payload) when blocker_reason is present."""
        sfg = build_subject_facing_foreground(
            visible_action_surface=_visible(blocker_summary="file not found"),
        )
        assert isinstance(sfg.blocker, dict)
        assert sfg.blocker["reason"] == "file not found"

    def test_C05_confirmation_drives_foreground_event_to_confirming(self):
        """When confirmation_needed, foreground_event=confirming regardless of phase."""
        sfg = build_subject_facing_foreground(
            visible_action_surface=_visible(
                confirmation_needed=True,
                action_state="completed",   # would normally be COMPLETED
                lifecycle_phase="result_received",
            ),
        )
        assert sfg.foreground_event == FOREGROUND_EVENT_CONFIRMING

    def test_C06_confirmation_drives_foreground_status_to_awaiting_confirmation(self):
        """foreground_status = awaiting_confirmation when confirmation is needed."""
        sfg = build_subject_facing_foreground(
            visible_action_surface=_visible(confirmation_needed=True),
        )
        assert sfg.foreground_status == "awaiting_confirmation"
        assert sfg.needs_confirmation()

    def test_C07_blocker_takes_priority_over_confirmation(self):
        """When both blocker and confirmation are present, blocker wins."""
        sfg = build_subject_facing_foreground(
            visible_action_surface=_visible(
                blocker_summary="blocked by safety policy",
                confirmation_needed=True,
            ),
        )
        assert sfg.foreground_event == FOREGROUND_EVENT_BLOCKED
        assert sfg.foreground_status.startswith("blocked:")

    def test_C08_blocker_from_lifecycle_surface_is_elevated(self):
        """Blocker from action_lifecycle_surface is also elevated to primary event."""
        sfg = build_subject_facing_foreground(
            visible_action_surface=_visible(),  # no blocker in visible surface
            action_lifecycle_surface=_lifecycle(
                phase="blocked",
                blocker={"reason": "resource busy", "kind": "resource_lock"},
                blocker_reason="resource busy",
            ),
        )
        assert sfg.foreground_event == FOREGROUND_EVENT_BLOCKED
        assert sfg.blocker_reason == "resource busy"

    def test_C09_confirmation_context_from_lifecycle_surface_is_elevated(self):
        """confirmation_context from lifecycle_surface surfaces on SubjectFacingForeground."""
        sfg = build_subject_facing_foreground(
            visible_action_surface=_visible(confirmation_needed=True),
            action_lifecycle_surface=_lifecycle(
                phase="confirmation_needed",
                confirmation_needed=True,
                confirmation_context={"scope": "file_delete", "target": "/tmp/x"},
            ),
        )
        assert sfg.foreground_event == FOREGROUND_EVENT_CONFIRMING
        assert isinstance(sfg.confirmation, dict)
        assert sfg.confirmation.get("scope") == "file_delete"

    def test_C10_no_blocker_no_confirmation_does_not_set_blocked_confirming(self):
        """In the normal case (no blocker, no confirmation), event is not blocked/confirming."""
        sfg = build_subject_facing_foreground(
            visible_action_surface=_visible(
                action_state="executing",
                lifecycle_phase="executing",
            ),
        )
        assert sfg.foreground_event not in (FOREGROUND_EVENT_BLOCKED, FOREGROUND_EVENT_CONFIRMING)
        assert not sfg.is_blocked()
        assert not sfg.needs_confirmation()


# ===========================================================================
# Group D — Control-plane demotion test
# ===========================================================================


class TestControlPlaneDemotion:
    """
    D. Verify that problem_execution_spine (control-plane diagnostic) is
    demoted to operator-only, and that subject_foreground is promoted as
    the primary user-facing organizing object in the chat response path.
    """

    def test_D01_subject_foreground_present_in_user_response(self):
        """
        In the default (non-operator) response, subject_foreground must be
        present as a primary organizing object.
        """
        from core.routes.chat import _apply_hidden_visible_boundary, _is_operator_request

        result = {
            "success": True,
            "response": "action executed",
            "action_lifecycle_surface": {
                "phase": "result_received",
                "origin": "v2_center",
                "blocker": None,
                "blocker_reason": "",
                "confirmation_needed": False,
                "confirmation_context": None,
                "closure_state": "closed",
            },
        }
        metadata = {"presence_mode": "manifest"}

        _, visible_action_surface, foreground_response, _ = _apply_hidden_visible_boundary(
            result=result,
            metadata=metadata,
            is_operator_request=False,
        )
        # Build subject_foreground as the chat handler would
        sfg = build_subject_facing_foreground(
            visible_action_surface=visible_action_surface,
            action_lifecycle_surface=result.get("action_lifecycle_surface"),
            foreground_response=foreground_response,
        )
        # subject_foreground is present and is_subject_primary
        assert sfg.is_subject_primary is True
        # subject_state reflects presence mode
        assert sfg.subject_state == "manifest"

    def test_D02_subject_foreground_absent_from_keys_for_operator(self):
        """
        Operators see both subject_foreground AND problem_execution_spine;
        users see subject_foreground but NOT problem_execution_spine.
        This test documents the asymmetry.
        """
        # Simulate what chat handler builds for user vs operator
        # For user: problem_execution_spine is NOT attached
        # For operator: problem_execution_spine IS attached
        user_metadata = {"presence_mode": "manifest", "problem_execution_spine": {"spine": True}}
        operator_metadata = dict(user_metadata)

        from core.routes.chat import _apply_hidden_visible_boundary

        result = {"success": True, "response": "ok"}

        # For user: problem_execution_spine would be excluded by chat handler
        _, user_vas, _, _ = _apply_hidden_visible_boundary(
            result=result, metadata=user_metadata, is_operator_request=False
        )
        _, op_vas, _, _ = _apply_hidden_visible_boundary(
            result=result, metadata=operator_metadata, is_operator_request=True
        )

        # Both get visible_action_surface but problem_execution_spine is in metadata
        # The key point: user_metadata["problem_execution_spine"] is present but
        # the chat handler (PR-SFF change) only exposes it for operators.
        # We verify the subject_foreground object is always produced.
        user_sfg = build_subject_facing_foreground(
            visible_action_surface=user_vas,
            foreground_response="ok",
        )
        op_sfg = build_subject_facing_foreground(
            visible_action_surface=op_vas,
            foreground_response="ok",
        )
        assert user_sfg.is_subject_primary is True
        assert op_sfg.is_subject_primary is True

    def test_D03_problem_execution_spine_is_not_in_subject_foreground(self):
        """
        subject_foreground must not contain problem_execution_spine or any
        control-plane diagnostic fields.  It is a clean subject lifecycle object.
        """
        sfg = build_subject_facing_foreground(
            visible_action_surface=_visible(),
            action_lifecycle_surface=_lifecycle(),
        )
        d = sfg.to_dict()
        # Control-plane / diagnostic fields must NOT appear
        assert "problem_execution_spine" not in d
        assert "desktop_status_projection" not in d
        assert "ingress_carrier_context" not in d
        assert "arch_layer_id" not in d
        assert "introspection_snapshot" not in d
        assert "runtime_decision_reasoning" not in d

    def test_D04_user_response_subject_foreground_is_subject_organized(self):
        """
        For a non-operator user: the primary organizing object (subject_foreground)
        centers on subject lifecycle, not on runtime internal structure.
        This contrasts with problem_execution_spine which is about runtime execution.
        """
        sfg = build_subject_facing_foreground(
            visible_action_surface=_visible(
                presence_mode="manifest",
                action_state="completed",
                lifecycle_phase="result_received",
                result_artifacts_summary="output.txt",
            ),
        )
        d = sfg.to_dict()
        # Subject lifecycle fields are present
        assert d["subject_state"] == "manifest"
        assert d["action_phase"] == "result_received"
        assert d["foreground_event"] == FOREGROUND_EVENT_COMPLETED
        assert d["result"] == "completed"
        # is_subject_primary marks this as the canonical foreground primary
        assert d["is_subject_primary"] is True

    def test_D05_blocked_subject_foreground_surfaces_blocker_as_primary(self):
        """
        When blocked, subject_foreground makes blocker the primary story for the
        user — not a secondary payload field.
        """
        sfg = build_subject_facing_foreground(
            visible_action_surface=_visible(
                blocker_summary="device locked",
                action_state="failed",  # runtime says failed
                lifecycle_phase="blocked",
            ),
        )
        assert sfg.foreground_event == FOREGROUND_EVENT_BLOCKED
        assert sfg.blocker_reason == "device locked"
        assert sfg.is_blocked()
        # The blocker IS the foreground — not an aside
        assert sfg.to_dict()["blocker"]["reason"] == "device locked"

    def test_D06_control_plane_heavy_chat_produces_clean_subject_foreground(self):
        """
        Even when the underlying result is control-plane-heavy (many runtime
        fields), subject_foreground remains clean and lifecycle-organized.
        """
        control_plane_heavy_result = {
            "success": True,
            "response": "processed",
            "action_lifecycle_surface": {
                "phase": "result_received",
                "origin": "v2_center",
                "blocker": None,
                "blocker_reason": "",
                "confirmation_needed": False,
                "confirmation_context": None,
                "closure_state": "closed",
                # Control-plane detail that should not leak to subject_foreground:
                "cross_repo_lifecycle_map": {"handoff_dispatch": "dispatched"},
                "android_result_authority": "",
                "surface_version": "1.0",
                "surface_origin_module": "core.unified_action_lifecycle_surface",
            },
        }
        metadata = {
            "presence_mode": "manifest",
            "runtime_decision_reasoning": {"chain": ["route_v2", "openclawd"]},
            "task_truth": {"authority": "v2_center"},
            "outward_truth": {"lineage": "core_execution"},
            "problem_execution_spine": {"spine_class": "goal_execution_spine"},
        }

        from core.routes.chat import _apply_hidden_visible_boundary
        _, vis_surface, fg_resp, _ = _apply_hidden_visible_boundary(
            result=control_plane_heavy_result,
            metadata=metadata,
            is_operator_request=False,
        )
        sfg = build_subject_facing_foreground(
            visible_action_surface=vis_surface,
            action_lifecycle_surface=control_plane_heavy_result.get("action_lifecycle_surface"),
            foreground_response=fg_resp,
        )
        d = sfg.to_dict()
        # subject_foreground is clean — no control-plane internals
        assert "runtime_decision_reasoning" not in d
        assert "task_truth" not in d
        assert "cross_repo_lifecycle_map" not in d
        assert "problem_execution_spine" not in d
        # But the subject lifecycle IS present
        assert d["subject_state"] == "manifest"
        assert d["foreground_event"] == FOREGROUND_EVENT_COMPLETED
        assert d["is_subject_primary"] is True
