from __future__ import annotations

from core.hidden_context_visible_action_surface import (
    SurfaceLayer,
    build_hidden_context_visible_action_surface_contract,
    classify_content_layer,
)


def test_boundary_contract_declares_three_formal_layers():
    contract = build_hidden_context_visible_action_surface_contract()
    partition = contract["system_partition"]
    assert set(partition.keys()) == {
        "background_semantic_layer",
        "foreground_presence_action_layer",
        "operator_audit_truth_layer",
    }


def test_background_defaults_cover_hidden_semantic_internals():
    contract = build_hidden_context_visible_action_surface_contract()
    background_rules = contract["system_partition"]["background_semantic_layer"]["rules"]
    keys = {r["content_key"] for r in background_rules}
    for required in (
        "raw_sensing_streams",
        "continuous_context_assembly",
        "working_memory",
        "long_term_memory",
        "_session_memory",
        "internal_reasoning_chains",
        "task_planning_and_routing_reasoning",
    ):
        assert required in keys


def test_foreground_defaults_center_on_presence_and_action_surface():
    contract = build_hidden_context_visible_action_surface_contract()
    keys = set(contract["visible_action_surface"]["foreground_center_of_gravity"])
    assert "presence_mode" in keys
    assert "desktop_action_traces" in keys
    assert "result_artifacts" in keys


def test_operator_audit_defaults_keep_projection_truth_surfaces_demoted():
    contract = build_hidden_context_visible_action_surface_contract()
    operator_rules = contract["system_partition"]["operator_audit_truth_layer"]["rules"]
    keys = {r["content_key"] for r in operator_rules}
    for required in (
        "outward_truth",
        "task_truth",
        "runtime_decision_reasoning",
        "projection_surface",
        "operator_snapshot",
        "checkpoint_provenance_recovery",
        "truth_source_registry",
        "system_state_narrative",
    ):
        assert required in keys


def test_explanation_policy_and_backbone_alignment_are_explicit():
    contract = build_hidden_context_visible_action_surface_contract()
    policy = contract["foreground_minimal_necessary_explanation_policy"]
    assert "safety_sensitive_action" in policy["minimal_prior_explanation_required_for"]
    assert "execution_failure" in policy["clear_failure_explanation_required_for"]
    alignment = contract["backbone_alignment"]
    assert alignment["presence_layer"]["module"] == "core.desktop_presence_system"
    assert alignment["multimodal_ingress_backbone"]["module"] == "core.desktop_native_multimodal_ingress_contract"
    assert alignment["realtime_streaming_backbone"]["module"] == "core.realtime_streaming_backbone"


def test_unknown_content_defaults_to_background_semantic_layer():
    assert classify_content_layer("unknown_future_internal_key") == SurfaceLayer.BACKGROUND_SEMANTIC


def test_known_content_keys_map_to_expected_layers():
    assert classify_content_layer("working_memory") == SurfaceLayer.BACKGROUND_SEMANTIC
    assert classify_content_layer("result_artifacts") == SurfaceLayer.FOREGROUND_PRESENCE_ACTION
    assert classify_content_layer("runtime_decision_reasoning") == SurfaceLayer.OPERATOR_AUDIT_TRUTH
