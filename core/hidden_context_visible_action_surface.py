"""Formal Hidden Context / Visible Action Surface boundary contract."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

HIDDEN_CONTEXT_VISIBLE_ACTION_SURFACE_AUTHORITY = (
    "HIDDEN_CONTEXT_VISIBLE_ACTION_SURFACE_AUTHORITY::DESKTOP_PRESENCE_MAINLINE_V1"
)
HIDDEN_CONTEXT_VISIBLE_ACTION_SURFACE_SENTINEL = (
    "HIDDEN_CONTEXT_VISIBLE_ACTION_SURFACE::FORMAL_CONVERGENCE_PASS_V1"
)


class SurfaceLayer(str, Enum):
    """Formal layer partition for Hidden Context / Visible Action Surface."""

    BACKGROUND_SEMANTIC = "background_semantic"
    FOREGROUND_PRESENCE_ACTION = "foreground_presence_action"
    OPERATOR_AUDIT_TRUTH = "operator_audit_truth"


@dataclass(frozen=True)
class LayerContentRule:
    """Classify one content domain into a formal surface layer."""

    content_key: str
    layer: SurfaceLayer
    default_visibility: str
    rationale: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "content_key": self.content_key,
            "layer": self.layer.value,
            "default_visibility": self.default_visibility,
            "rationale": self.rationale,
        }


LAYER_CONTENT_RULES: Tuple[LayerContentRule, ...] = (
    LayerContentRule(
        "raw_sensing_streams",
        SurfaceLayer.BACKGROUND_SEMANTIC,
        "background_default",
        "Raw stream payloads stay background-semantic by default.",
    ),
    LayerContentRule(
        "continuous_context_assembly",
        SurfaceLayer.BACKGROUND_SEMANTIC,
        "background_default",
        "Context assembly intermediates remain hidden unless operator audit is requested.",
    ),
    LayerContentRule(
        "working_memory",
        SurfaceLayer.BACKGROUND_SEMANTIC,
        "background_default",
        "WorkingMemory is internal subject context, not a foreground surface.",
    ),
    LayerContentRule(
        "long_term_memory",
        SurfaceLayer.BACKGROUND_SEMANTIC,
        "background_default",
        "LongTermMemory is retained internally and not foregrounded by default.",
    ),
    LayerContentRule(
        "_session_memory",
        SurfaceLayer.BACKGROUND_SEMANTIC,
        "background_default",
        "Session memory internals are hidden semantic state.",
    ),
    LayerContentRule(
        "internal_reasoning_chains",
        SurfaceLayer.BACKGROUND_SEMANTIC,
        "background_default",
        "Detailed internal reasoning remains background unless operator traceability requires it.",
    ),
    LayerContentRule(
        "task_planning_and_routing_reasoning",
        SurfaceLayer.BACKGROUND_SEMANTIC,
        "background_default",
        "Planning and routing internals are background semantic by default.",
    ),
    LayerContentRule(
        "presence_mode",
        SurfaceLayer.FOREGROUND_PRESENCE_ACTION,
        "foreground_default",
        "Foreground should always expose static/liminal/manifest presence state.",
    ),
    LayerContentRule(
        "ambient_board_changes",
        SurfaceLayer.FOREGROUND_PRESENCE_ACTION,
        "foreground_default",
        "Liminal ambient-board transitions are foreground-visible by design.",
    ),
    LayerContentRule(
        "current_action_state",
        SurfaceLayer.FOREGROUND_PRESENCE_ACTION,
        "foreground_default",
        "Current desktop action activity is a primary foreground object.",
    ),
    LayerContentRule(
        "desktop_action_traces",
        SurfaceLayer.FOREGROUND_PRESENCE_ACTION,
        "foreground_default",
        "Desktop-visible execution traces are foreground-visible.",
    ),
    LayerContentRule(
        "result_artifacts",
        SurfaceLayer.FOREGROUND_PRESENCE_ACTION,
        "foreground_default",
        "Completed outputs and artifacts belong to the visible action surface.",
    ),
    LayerContentRule(
        "minimal_feedback",
        SurfaceLayer.FOREGROUND_PRESENCE_ACTION,
        "foreground_default",
        "Foreground receives lightweight feedback required for comprehension.",
    ),
    LayerContentRule(
        "compressed_explanation",
        SurfaceLayer.FOREGROUND_PRESENCE_ACTION,
        "foreground_default",
        "Foreground explanation is compressed and user-comprehensible.",
    ),
    LayerContentRule(
        "safety_permission_confirmation",
        SurfaceLayer.FOREGROUND_PRESENCE_ACTION,
        "foreground_default",
        "Safety/permission critical signals must remain foreground visible.",
    ),
    LayerContentRule(
        "outward_truth",
        SurfaceLayer.OPERATOR_AUDIT_TRUTH,
        "operator_default",
        "Outward truth is retained for operator/professional traceability surfaces.",
    ),
    LayerContentRule(
        "task_truth",
        SurfaceLayer.OPERATOR_AUDIT_TRUTH,
        "operator_default",
        "Task truth remains operator/audit facing unless summarized.",
    ),
    LayerContentRule(
        "runtime_decision_reasoning",
        SurfaceLayer.OPERATOR_AUDIT_TRUTH,
        "operator_default",
        "Detailed runtime reasoning stays in traceable operator surfaces.",
    ),
    LayerContentRule(
        "projection_surface",
        SurfaceLayer.OPERATOR_AUDIT_TRUTH,
        "operator_default",
        "Projection surface is preserved but demoted from natural foreground.",
    ),
    LayerContentRule(
        "operator_snapshot",
        SurfaceLayer.OPERATOR_AUDIT_TRUTH,
        "operator_default",
        "Operator snapshots are diagnostics/audit surfaces.",
    ),
    LayerContentRule(
        "checkpoint_provenance_recovery",
        SurfaceLayer.OPERATOR_AUDIT_TRUTH,
        "operator_default",
        "Checkpoint/provenance/recovery data is operator traceability data.",
    ),
    LayerContentRule(
        "truth_source_registry",
        SurfaceLayer.OPERATOR_AUDIT_TRUTH,
        "operator_default",
        "Truth-source registry is traceability metadata for operators/audits.",
    ),
    LayerContentRule(
        "system_state_narrative",
        SurfaceLayer.OPERATOR_AUDIT_TRUTH,
        "operator_default",
        "System narrative is retained as operator explanatory/audit view.",
    ),
)


def classify_content_layer(content_key: str) -> SurfaceLayer:
    """Return the formal layer for *content_key* (background by default)."""
    for rule in LAYER_CONTENT_RULES:
        if rule.content_key == content_key:
            return rule.layer
    return SurfaceLayer.BACKGROUND_SEMANTIC


def _rules_for_layer(layer: SurfaceLayer) -> List[Dict[str, str]]:
    return [r.to_dict() for r in LAYER_CONTENT_RULES if r.layer == layer]


def build_hidden_context_visible_action_surface_contract(
    *,
    presence_layer: str = "core.desktop_presence_system",
    multimodal_backbone: str = "core.desktop_native_multimodal_ingress_contract",
    streaming_backbone: str = "core.realtime_streaming_backbone",
    runtime_shell: str = "core.desktop_presence_runtime",
    subject_core: str = "core.openclawd",
    include_content_rules: bool = True,
) -> Dict[str, Any]:
    """Build the formal foreground/background/operator boundary contract."""
    content_rules = [r.to_dict() for r in LAYER_CONTENT_RULES] if include_content_rules else []
    return {
        "authority": HIDDEN_CONTEXT_VISIBLE_ACTION_SURFACE_AUTHORITY,
        "sentinel": HIDDEN_CONTEXT_VISIBLE_ACTION_SURFACE_SENTINEL,
        "contract_version": 1,
        "system_partition": {
            "background_semantic_layer": {
                "role": "continuous_sensing_context_memory_reasoning_and_orchestration",
                "default_visibility": "hidden_background",
                "rules": _rules_for_layer(SurfaceLayer.BACKGROUND_SEMANTIC),
            },
            "foreground_presence_action_layer": {
                "role": "presence_modes_actions_traces_results_and_minimal_explanation",
                "default_visibility": "foreground_default",
                "rules": _rules_for_layer(SurfaceLayer.FOREGROUND_PRESENCE_ACTION),
            },
            "operator_audit_truth_layer": {
                "role": "projection_truth_reasoning_and_diagnostics_traceability",
                "default_visibility": "operator_default",
                "rules": _rules_for_layer(SurfaceLayer.OPERATOR_AUDIT_TRUTH),
            },
        },
        "foreground_minimal_necessary_explanation_policy": {
            "minimal_prior_explanation_required_for": [
                "safety_sensitive_action",
                "permission_or_destructive_action",
                "cross_device_execution_handoff",
            ],
            "lightweight_feedback_required_for": [
                "presence_mode_change",
                "action_start_and_completion",
                "stream_state_degraded_or_recovered",
            ],
            "clear_failure_explanation_required_for": [
                "blocked_action",
                "execution_failure",
                "permission_denied_or_missing_capability",
            ],
            "foreground_reasoning_policy": (
                "Expose compressed user-comprehensible explanation in foreground; "
                "full reasoning chains remain operator/audit trace surfaces."
            ),
            "must_remain_foreground_visible": [
                "safety_confirmation",
                "permission_status",
                "critical_blockers",
                "result_artifact_identity",
                "action_trace_anchor",
            ],
        },
        "visible_action_surface": {
            "is_first_class_foreground_concept": True,
            "foreground_center_of_gravity": [
                "presence_mode",
                "current_action_state",
                "desktop_action_traces",
                "action_results",
                "result_artifacts",
                "lightweight_confirmation_blocker_feedback",
            ],
            "must_not_be_primary_foreground": [
                "projection_truth_sections",
                "runtime_reasoning_dumps",
                "operator_debug_payloads",
                "internal_truth_dashboard_fragments",
            ],
            "action_traceability_policy": (
                "Foreground shows action-level traces; operator surfaces retain full "
                "reasoning/provenance traceability."
            ),
        },
        "backbone_alignment": {
            "presence_layer": {
                "module": presence_layer,
                "alignment": (
                    "static/liminal/manifest remain foreground presence signals while "
                    "background cognition continues hidden by default."
                ),
            },
            "multimodal_ingress_backbone": {
                "module": multimodal_backbone,
                "alignment": (
                    "raw multimodal ingress remains background-semantic; only "
                    "presence/action implications are foregrounded by default."
                ),
            },
            "realtime_streaming_backbone": {
                "module": streaming_backbone,
                "alignment": (
                    "stream payload stays background; foreground shows lightweight "
                    "stream state and action-relevant status; diagnostics are operator-traceable."
                ),
            },
            "runtime_subject_coupling": {
                "runtime_shell": runtime_shell,
                "subject_core": subject_core,
                "alignment": "boundary is structural runtime policy, not mere UI masking",
            },
        },
        "default_visibility_rules": {
            "background_by_default_not_foregrounded_by_default": True,
            "foreground_default_focus": [
                "presence_modes",
                "desktop_activity",
                "execution_traces",
                "result_artifacts",
                "minimal_feedback",
            ],
            "operator_only_default_focus": [
                "projection_truth",
                "runtime_decision_reasoning",
                "operator_snapshots",
                "diagnostics_checkpoint_provenance",
            ],
        },
        "content_layer_rules": content_rules,
    }
