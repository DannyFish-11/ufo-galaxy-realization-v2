"""
tests/test_pr22_desktop_status_projection.py
=============================================
PR-22 — Add desktop status projection for shell-facing control-loop visibility.

Tests are grouped by category and cover the 7 required test scenarios:

1. Valid projection produced for text-only flows
2. Projection includes multimodal/ingress data when present
3. Projection reflects selected provider/model and native-multimodal status
4. Projection reflects execution path and remote mode
5. Projection surfaces fallback/degradation reasons coherently
6. Projection remains valid when sources or providers are unavailable
7. Shell consumes projection without reconstructing core logic from scratch

Additional coverage:
- All sub-contracts (PerceptionProjection, ModelRoutingProjection,
  ExecutionProjection, LifecycleProjection, ExplainabilityProjection)
- to_dict / from_dict round-trip stability
- desktop_status_projection_summary() compact summary
- build_desktop_status_projection() graceful defaults
- DesktopPresenceRuntime.build_desktop_status_projection() integration
- LifecycleStage derivation from tri-state and lifecycle_target
- Overall health severity roll-up
- JSON serialisation safety
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import pytest


# ---------------------------------------------------------------------------
# Helpers — minimal plan / source registry stubs
# ---------------------------------------------------------------------------


def _minimal_plan() -> Dict[str, Any]:
    """Return a minimal UnifiedControlPlan dict (text-only, no extras)."""
    return {
        "decision_authority": "subject_decision_authority",
        "chosen_model": None,
        "chosen_provider": None,
        "is_native_multimodal": False,
        "lifecycle_target": "succeeded",
        "fallback_level": "none",
        "fallback_reason": None,
        "chosen_execution_decision": {
            "execution_path": "local",
            "delegation_point": "local_manifestation",
            "remote_execution_mode": None,
            "target_device_ids": [],
            "orchestration_active": False,
        },
        "canonical_perception": {
            "has_multimodal_input": False,
            "active_modalities": [],
        },
        "diagnostics_summary": None,
        "fallback_decision_record": None,
    }


def _multimodal_plan() -> Dict[str, Any]:
    """Return a plan dict representing a native-multimodal request."""
    base = _minimal_plan()
    base["chosen_model"] = "gpt-4o"
    base["chosen_provider"] = "openai"
    base["is_native_multimodal"] = True
    base["canonical_perception"] = {
        "has_multimodal_input": True,
        "requires_native_multimodal": True,
        "active_modalities": ["audio", "video"],
    }
    base["multimodal_route"] = {
        "is_native_multimodal": True,
        "route_reason": "native multimodal provider selected",
        "active_modalities": ["audio", "video"],
        "selected_model": "gpt-4o",
        "selected_provider": "openai",
    }
    return base


def _cross_device_plan() -> Dict[str, Any]:
    """Return a plan dict representing a cross-device execution."""
    base = _minimal_plan()
    base["chosen_model"] = "claude-3-5-sonnet"
    base["chosen_provider"] = "anthropic"
    base["chosen_execution_decision"] = {
        "execution_path": "cross_device",
        "delegation_point": "single_remote",
        "remote_execution_mode": "agent_runtime",
        "target_device_ids": ["phone_001"],
        "orchestration_active": False,
    }
    base["unified_execution_decision"] = {
        "execution_path": "cross_device",
        "remote_execution_mode": "agent_runtime",
        "target_device_ids": ["phone_001"],
        "orchestration_active": False,
        "execution_reason": "remote device preferred for this task",
        "delegation_point": "single_remote",
    }
    return base


def _fallback_plan() -> Dict[str, Any]:
    """Return a plan dict with fallback/degradation data."""
    base = _minimal_plan()
    base["chosen_model"] = "gpt-4-turbo"
    base["chosen_provider"] = "openai"
    base["fallback_level"] = "model_fallback"
    base["fallback_reason"] = "primary provider unavailable"
    base["fallback_decision_record"] = {
        "has_fallback": True,
        "fallback_kinds": ["native_multimodal_to_text", "remote_to_local"],
        "model_fallback_reason": "gpt-4o unavailable",
        "multimodal_downgrade_reason": "no native provider available",
        "remote_to_local_reason": "target device unreachable",
        "machine_readable_codes": ["native_multimodal_to_text", "remote_to_local"],
    }
    base["lifecycle_target"] = "degraded"
    return base


def _source_registry_snapshot(
    *,
    mic_active: bool = True,
    cam_active: bool = False,
    mic_health: str = "healthy",
) -> Dict[str, Any]:
    """Return a minimal source registry snapshot dict."""
    sources = [
        {
            "source_id": "builtin:microphone",
            "source_type": "microphone",
            "modality": "audio",
            "is_active": mic_active,
            "is_primary_audio": mic_active,
            "is_primary_video": False,
            "health_status": mic_health,
            "quality_score": 0.9 if mic_health == "healthy" else 0.4,
            "latency_ms": 5.0,
            "display_name": "System Microphone",
        }
    ]
    if cam_active:
        sources.append({
            "source_id": "builtin:webcam",
            "source_type": "webcam",
            "modality": "video",
            "is_active": True,
            "is_primary_audio": False,
            "is_primary_video": True,
            "health_status": "healthy",
            "quality_score": 0.85,
            "latency_ms": 10.0,
            "display_name": "Built-in Webcam",
        })
    return {"snapshot_at": 0.0, "sources": sources}


# ===========================================================================
# 1. Valid projection for text-only flows
# ===========================================================================


class TestTextOnlyProjection:
    def test_build_returns_valid_object(self):
        from contracts.desktop_status_projection import build_desktop_status_projection, DesktopStatusProjection
        proj = build_desktop_status_projection(unified_control_plan=_minimal_plan())
        assert isinstance(proj, DesktopStatusProjection)

    def test_projection_has_all_sub_contracts(self):
        from contracts.desktop_status_projection import (
            build_desktop_status_projection,
            PerceptionProjection,
            ModelRoutingProjection,
            ExecutionProjection,
            LifecycleProjection,
            ExplainabilityProjection,
        )
        proj = build_desktop_status_projection(unified_control_plan=_minimal_plan())
        assert isinstance(proj.perception, PerceptionProjection)
        assert isinstance(proj.model_routing, ModelRoutingProjection)
        assert isinstance(proj.execution, ExecutionProjection)
        assert isinstance(proj.lifecycle, LifecycleProjection)
        assert isinstance(proj.explainability, ExplainabilityProjection)

    def test_text_only_no_multimodal(self):
        from contracts.desktop_status_projection import build_desktop_status_projection
        proj = build_desktop_status_projection(unified_control_plan=_minimal_plan())
        assert proj.perception.request_multimodal_present is False
        assert proj.perception.active_modalities == []
        assert proj.model_routing.is_native_multimodal is False

    def test_text_only_no_fallback(self):
        from contracts.desktop_status_projection import build_desktop_status_projection
        proj = build_desktop_status_projection(unified_control_plan=_minimal_plan())
        assert proj.explainability.has_fallback is False
        assert proj.explainability.fallback_kinds == []

    def test_projection_valid_with_no_plan(self):
        from contracts.desktop_status_projection import build_desktop_status_projection
        proj = build_desktop_status_projection()
        assert proj is not None
        assert proj.projection_id.startswith("dsp_")

    def test_projection_valid_with_none_plan(self):
        from contracts.desktop_status_projection import build_desktop_status_projection
        proj = build_desktop_status_projection(unified_control_plan=None)
        assert proj is not None

    def test_schema_version_present(self):
        from contracts.desktop_status_projection import build_desktop_status_projection
        proj = build_desktop_status_projection(unified_control_plan=_minimal_plan())
        assert proj.schema_version == "1.0"

    def test_projected_at_is_numeric(self):
        from contracts.desktop_status_projection import build_desktop_status_projection
        proj = build_desktop_status_projection(unified_control_plan=_minimal_plan())
        assert isinstance(proj.projected_at, float)
        assert proj.projected_at > 0

    def test_execution_path_local(self):
        from contracts.desktop_status_projection import build_desktop_status_projection, ExecutionPathKind
        proj = build_desktop_status_projection(unified_control_plan=_minimal_plan())
        assert proj.execution.execution_path == ExecutionPathKind.local

    def test_lifecycle_stage_succeed_on_silent(self):
        from contracts.desktop_status_projection import build_desktop_status_projection, LifecycleStage
        proj = build_desktop_status_projection(
            unified_control_plan=_minimal_plan(),
            tristate="silent",
        )
        assert proj.lifecycle.stage == LifecycleStage.succeed

    def test_tristate_propagated(self):
        from contracts.desktop_status_projection import build_desktop_status_projection
        proj = build_desktop_status_projection(
            unified_control_plan=_minimal_plan(),
            tristate="manifest",
        )
        assert proj.lifecycle.tristate == "manifest"

    def test_runtime_session_id_propagated(self):
        from contracts.desktop_status_projection import build_desktop_status_projection
        proj = build_desktop_status_projection(
            unified_control_plan=_minimal_plan(),
            runtime_session_id="sess_abc123",
        )
        assert proj.runtime_session_id == "sess_abc123"


# ===========================================================================
# 2. Projection includes multimodal/ingress data when present
# ===========================================================================


class TestMultimodalProjection:
    def test_active_modalities_populated(self):
        from contracts.desktop_status_projection import build_desktop_status_projection
        proj = build_desktop_status_projection(unified_control_plan=_multimodal_plan())
        assert "audio" in proj.perception.active_modalities
        assert "video" in proj.perception.active_modalities

    def test_request_multimodal_present(self):
        from contracts.desktop_status_projection import build_desktop_status_projection
        proj = build_desktop_status_projection(unified_control_plan=_multimodal_plan())
        assert proj.perception.request_multimodal_present is True

    def test_source_registry_audio_source(self):
        from contracts.desktop_status_projection import build_desktop_status_projection
        snap = _source_registry_snapshot(mic_active=True)
        proj = build_desktop_status_projection(
            unified_control_plan=_minimal_plan(),
            source_registry_snapshot=snap,
        )
        assert proj.perception.primary_audio_source_id == "builtin:microphone"
        assert proj.perception.primary_audio_source_type == "microphone"

    def test_source_registry_video_source(self):
        from contracts.desktop_status_projection import build_desktop_status_projection
        snap = _source_registry_snapshot(mic_active=True, cam_active=True)
        proj = build_desktop_status_projection(
            unified_control_plan=_minimal_plan(),
            source_registry_snapshot=snap,
        )
        assert proj.perception.primary_video_source_id == "builtin:webcam"
        assert proj.perception.primary_video_source_type == "webcam"

    def test_continuous_perception_active_with_active_sources(self):
        from contracts.desktop_status_projection import build_desktop_status_projection
        snap = _source_registry_snapshot(mic_active=True)
        proj = build_desktop_status_projection(
            unified_control_plan=_minimal_plan(),
            source_registry_snapshot=snap,
        )
        assert proj.perception.continuous_perception_active is True

    def test_no_sources_gives_inactive_perception(self):
        from contracts.desktop_status_projection import build_desktop_status_projection
        proj = build_desktop_status_projection(
            unified_control_plan=_minimal_plan(),
            source_registry_snapshot={"sources": []},
        )
        assert proj.perception.continuous_perception_active is False
        assert proj.perception.source_count == 0

    def test_active_modalities_from_source_registry(self):
        from contracts.desktop_status_projection import build_desktop_status_projection
        snap = _source_registry_snapshot(mic_active=True, cam_active=True)
        plan = _minimal_plan()
        # Clear modalities from plan so they come from registry
        plan["canonical_perception"]["active_modalities"] = []
        proj = build_desktop_status_projection(
            unified_control_plan=plan,
            source_registry_snapshot=snap,
        )
        assert "audio" in proj.perception.active_modalities
        assert "video" in proj.perception.active_modalities

    def test_source_count_matches_registry(self):
        from contracts.desktop_status_projection import build_desktop_status_projection
        snap = _source_registry_snapshot(mic_active=True, cam_active=True)
        proj = build_desktop_status_projection(
            unified_control_plan=_minimal_plan(),
            source_registry_snapshot=snap,
        )
        assert proj.perception.source_count == 2
        assert proj.perception.active_source_count == 2


# ===========================================================================
# 3. Projection reflects selected provider/model and native-multimodal status
# ===========================================================================


class TestModelRoutingProjection:
    def test_selected_provider_and_model(self):
        from contracts.desktop_status_projection import build_desktop_status_projection
        plan = _minimal_plan()
        plan["chosen_model"] = "claude-3-5-sonnet"
        plan["chosen_provider"] = "anthropic"
        proj = build_desktop_status_projection(unified_control_plan=plan)
        assert proj.model_routing.selected_provider == "anthropic"
        assert proj.model_routing.selected_model == "claude-3-5-sonnet"

    def test_native_multimodal_flag(self):
        from contracts.desktop_status_projection import build_desktop_status_projection
        proj = build_desktop_status_projection(unified_control_plan=_multimodal_plan())
        assert proj.model_routing.is_native_multimodal is True

    def test_non_native_multimodal(self):
        from contracts.desktop_status_projection import build_desktop_status_projection
        plan = _minimal_plan()
        plan["chosen_model"] = "gpt-4-turbo"
        plan["chosen_provider"] = "openai"
        plan["is_native_multimodal"] = False
        proj = build_desktop_status_projection(unified_control_plan=plan)
        assert proj.model_routing.is_native_multimodal is False

    def test_route_reason_propagated(self):
        from contracts.desktop_status_projection import build_desktop_status_projection
        proj = build_desktop_status_projection(unified_control_plan=_multimodal_plan())
        assert proj.model_routing.route_reason is not None
        assert len(proj.model_routing.route_reason) > 0

    def test_route_summary_contains_provider_and_model(self):
        from contracts.desktop_status_projection import build_desktop_status_projection
        plan = _minimal_plan()
        plan["chosen_model"] = "gpt-4o"
        plan["chosen_provider"] = "openai"
        plan["is_native_multimodal"] = True
        proj = build_desktop_status_projection(unified_control_plan=plan)
        assert proj.model_routing.route_summary is not None
        assert "openai" in proj.model_routing.route_summary
        assert "gpt-4o" in proj.model_routing.route_summary
        assert "native-MM" in proj.model_routing.route_summary

    def test_no_model_gives_unknown_health(self):
        from contracts.desktop_status_projection import build_desktop_status_projection, ProjectionHealthSeverity
        proj = build_desktop_status_projection(unified_control_plan=_minimal_plan())
        # No chosen_model/provider → unknown health
        assert proj.model_routing.health_severity == ProjectionHealthSeverity.unknown

    def test_model_available_health_ok(self):
        from contracts.desktop_status_projection import build_desktop_status_projection, ProjectionHealthSeverity
        plan = _minimal_plan()
        plan["chosen_model"] = "gpt-4o"
        plan["chosen_provider"] = "openai"
        proj = build_desktop_status_projection(unified_control_plan=plan)
        assert proj.model_routing.health_severity == ProjectionHealthSeverity.ok


# ===========================================================================
# 4. Projection reflects execution path and remote mode
# ===========================================================================


class TestExecutionProjection:
    def test_local_execution_path(self):
        from contracts.desktop_status_projection import build_desktop_status_projection, ExecutionPathKind
        proj = build_desktop_status_projection(unified_control_plan=_minimal_plan())
        assert proj.execution.execution_path == ExecutionPathKind.local

    def test_cross_device_execution_path(self):
        from contracts.desktop_status_projection import build_desktop_status_projection, ExecutionPathKind
        proj = build_desktop_status_projection(unified_control_plan=_cross_device_plan())
        assert proj.execution.execution_path == ExecutionPathKind.cross_device

    def test_remote_execution_mode_agent_runtime(self):
        from contracts.desktop_status_projection import build_desktop_status_projection
        proj = build_desktop_status_projection(unified_control_plan=_cross_device_plan())
        assert proj.execution.remote_execution_mode == "agent_runtime"

    def test_target_device_ids_populated(self):
        from contracts.desktop_status_projection import build_desktop_status_projection
        proj = build_desktop_status_projection(unified_control_plan=_cross_device_plan())
        assert "phone_001" in proj.execution.target_device_ids

    def test_orchestration_active_false_for_single_remote(self):
        from contracts.desktop_status_projection import build_desktop_status_projection
        proj = build_desktop_status_projection(unified_control_plan=_cross_device_plan())
        assert proj.execution.orchestration_active is False

    def test_orchestration_active_true_for_hybrid(self):
        from contracts.desktop_status_projection import build_desktop_status_projection
        plan = _cross_device_plan()
        plan["unified_execution_decision"]["execution_path"] = "hybrid"
        plan["unified_execution_decision"]["orchestration_active"] = True
        plan["chosen_execution_decision"]["execution_path"] = "hybrid"
        proj = build_desktop_status_projection(unified_control_plan=plan)
        assert proj.execution.orchestration_active is True

    def test_execution_reason_propagated(self):
        from contracts.desktop_status_projection import build_desktop_status_projection
        proj = build_desktop_status_projection(unified_control_plan=_cross_device_plan())
        assert proj.execution.execution_reason == "remote device preferred for this task"

    def test_delegation_point_propagated(self):
        from contracts.desktop_status_projection import build_desktop_status_projection
        proj = build_desktop_status_projection(unified_control_plan=_cross_device_plan())
        assert proj.execution.delegation_point == "single_remote"

    def test_command_only_remote_mode(self):
        from contracts.desktop_status_projection import build_desktop_status_projection
        plan = _cross_device_plan()
        plan["unified_execution_decision"]["remote_execution_mode"] = "command_only"
        plan["chosen_execution_decision"]["remote_execution_mode"] = "command_only"
        proj = build_desktop_status_projection(unified_control_plan=plan)
        assert proj.execution.remote_execution_mode == "command_only"


# ===========================================================================
# 5. Projection surfaces fallback/degradation reasons coherently
# ===========================================================================


class TestFallbackProjection:
    def test_has_fallback_true(self):
        from contracts.desktop_status_projection import build_desktop_status_projection
        proj = build_desktop_status_projection(unified_control_plan=_fallback_plan())
        assert proj.explainability.has_fallback is True

    def test_fallback_kinds_populated(self):
        from contracts.desktop_status_projection import build_desktop_status_projection
        proj = build_desktop_status_projection(unified_control_plan=_fallback_plan())
        assert "native_multimodal_to_text" in proj.explainability.fallback_kinds
        assert "remote_to_local" in proj.explainability.fallback_kinds

    def test_fallback_reasons_populated(self):
        from contracts.desktop_status_projection import build_desktop_status_projection
        proj = build_desktop_status_projection(unified_control_plan=_fallback_plan())
        reasons = proj.explainability.fallback_reasons
        assert len(reasons) > 0
        # At least one reason should mention something meaningful
        combined = " ".join(reasons)
        assert len(combined) > 0

    def test_degradation_summary_present(self):
        from contracts.desktop_status_projection import build_desktop_status_projection
        proj = build_desktop_status_projection(unified_control_plan=_fallback_plan())
        assert proj.explainability.degradation_summary is not None
        assert len(proj.explainability.degradation_summary) > 0

    def test_lifecycle_stage_degrade(self):
        from contracts.desktop_status_projection import build_desktop_status_projection, LifecycleStage
        proj = build_desktop_status_projection(
            unified_control_plan=_fallback_plan(),
            tristate="silent",
        )
        assert proj.lifecycle.stage == LifecycleStage.degrade

    def test_explainability_health_degraded(self):
        from contracts.desktop_status_projection import build_desktop_status_projection, ProjectionHealthSeverity
        proj = build_desktop_status_projection(unified_control_plan=_fallback_plan())
        assert proj.explainability.health_severity == ProjectionHealthSeverity.degraded

    def test_top_level_fallback_reason_surfaced(self):
        from contracts.desktop_status_projection import build_desktop_status_projection
        plan = _minimal_plan()
        plan["fallback_reason"] = "provider timeout"
        proj = build_desktop_status_projection(unified_control_plan=plan)
        assert proj.explainability.has_fallback is True
        assert "provider timeout" in proj.explainability.fallback_reasons

    def test_authority_chain_clear_for_subject_authority(self):
        from contracts.desktop_status_projection import build_desktop_status_projection
        proj = build_desktop_status_projection(unified_control_plan=_minimal_plan())
        assert proj.explainability.authority_chain_clear is True

    def test_authority_chain_not_clear_for_unknown(self):
        from contracts.desktop_status_projection import build_desktop_status_projection
        plan = _minimal_plan()
        plan["decision_authority"] = "unknown"
        proj = build_desktop_status_projection(unified_control_plan=plan)
        assert proj.explainability.authority_chain_clear is False


# ===========================================================================
# 6. Projection remains valid when sources or providers are unavailable
# ===========================================================================


class TestGracefulDegradation:
    def test_no_sources_still_valid(self):
        from contracts.desktop_status_projection import build_desktop_status_projection
        proj = build_desktop_status_projection(
            unified_control_plan=_minimal_plan(),
            source_registry_snapshot=None,
        )
        assert proj is not None
        assert proj.perception.source_count == 0
        assert proj.perception.continuous_perception_active is False

    def test_unavailable_source_health_degraded(self):
        from contracts.desktop_status_projection import build_desktop_status_projection, ProjectionHealthSeverity
        snap = _source_registry_snapshot(mic_active=False, mic_health="unavailable")
        proj = build_desktop_status_projection(
            unified_control_plan=_minimal_plan(),
            source_registry_snapshot=snap,
        )
        assert proj.perception.health_severity == ProjectionHealthSeverity.degraded

    def test_degraded_source_health_advisory(self):
        from contracts.desktop_status_projection import build_desktop_status_projection, ProjectionHealthSeverity
        snap = _source_registry_snapshot(mic_active=True, mic_health="degraded")
        proj = build_desktop_status_projection(
            unified_control_plan=_minimal_plan(),
            source_registry_snapshot=snap,
        )
        assert proj.perception.health_severity == ProjectionHealthSeverity.advisory

    def test_unavailable_provider_health_critical(self):
        from contracts.desktop_status_projection import build_desktop_status_projection, ProjectionHealthSeverity
        plan = _minimal_plan()
        plan["chosen_model"] = "gpt-4o"
        plan["chosen_provider"] = "openai"
        plan["canonical_model_supply"] = {
            "providers": [
                {"provider_id": "openai", "health_status": "unavailable"},
            ]
        }
        proj = build_desktop_status_projection(unified_control_plan=plan)
        assert proj.model_routing.provider_available is False
        assert proj.model_routing.health_severity == ProjectionHealthSeverity.critical

    def test_source_warning_for_unavailable_provider(self):
        from contracts.desktop_status_projection import build_desktop_status_projection
        plan = _minimal_plan()
        plan["chosen_model"] = "gpt-4o"
        plan["chosen_provider"] = "openai"
        plan["canonical_model_supply"] = {
            "providers": [
                {"provider_id": "openai", "health_status": "unavailable"},
            ]
        }
        proj = build_desktop_status_projection(unified_control_plan=plan)
        assert len(proj.explainability.source_warnings) > 0
        assert any("openai" in w for w in proj.explainability.source_warnings)

    def test_empty_plan_still_valid(self):
        from contracts.desktop_status_projection import build_desktop_status_projection
        proj = build_desktop_status_projection(unified_control_plan={})
        assert proj is not None
        assert proj.projection_id.startswith("dsp_")

    def test_malformed_plan_falls_back_gracefully(self):
        from contracts.desktop_status_projection import build_desktop_status_projection
        # Deliberately pass a partially broken plan (wrong types in sub-dicts)
        plan = {
            "chosen_execution_decision": "not_a_dict",  # wrong type
            "fallback_decision_record": [1, 2, 3],      # wrong type
            "canonical_perception": None,
        }
        proj = build_desktop_status_projection(unified_control_plan=plan)
        assert proj is not None

    def test_failed_lifecycle_stage(self):
        from contracts.desktop_status_projection import build_desktop_status_projection, LifecycleStage
        plan = _minimal_plan()
        plan["lifecycle_target"] = "failed"
        proj = build_desktop_status_projection(
            unified_control_plan=plan,
            tristate="silent",
        )
        assert proj.lifecycle.stage == LifecycleStage.fail


# ===========================================================================
# 7. Shell consumes projection without reconstructing core logic from scratch
# ===========================================================================


class TestShellConsumesProjection:
    def test_desktop_presence_runtime_has_build_method(self):
        """DesktopPresenceRuntime.build_desktop_status_projection exists."""
        from core.desktop_presence_runtime import DesktopPresenceRuntime
        runtime = DesktopPresenceRuntime()
        assert hasattr(runtime, "build_desktop_status_projection")
        assert callable(runtime.build_desktop_status_projection)

    def test_shell_builds_projection_from_openclawd_result(self):
        """Shell can build a projection from a mock OpenClawd result dict."""
        from core.desktop_presence_runtime import DesktopPresenceRuntime
        runtime = DesktopPresenceRuntime()

        mock_result = {
            "success": True,
            "response": "Done",
            "metadata": {
                "unified_control_plan": {
                    "decision_authority": "subject_decision_authority",
                    "chosen_model": "gpt-4o",
                    "chosen_provider": "openai",
                    "is_native_multimodal": False,
                    "lifecycle_target": "succeeded",
                    "fallback_level": "none",
                    "fallback_reason": None,
                    "chosen_execution_decision": {
                        "execution_path": "local",
                        "delegation_point": "local_manifestation",
                        "remote_execution_mode": None,
                        "target_device_ids": [],
                        "orchestration_active": False,
                    },
                    "canonical_perception": {"has_multimodal_input": False, "active_modalities": []},
                    "fallback_decision_record": None,
                }
            },
        }
        dsp = runtime.build_desktop_status_projection(
            result=mock_result,
            tristate="silent",
            runtime_session_id="test_session_001",
        )
        assert dsp is not None
        assert isinstance(dsp, dict)
        assert "lifecycle" in dsp
        assert "model_routing" in dsp
        assert "execution" in dsp
        assert "perception" in dsp
        assert "explainability" in dsp

    def test_shell_projection_has_correct_provider(self):
        """Shell projection exposes the provider from the control plan."""
        from core.desktop_presence_runtime import DesktopPresenceRuntime
        runtime = DesktopPresenceRuntime()
        mock_result = {
            "success": True,
            "response": "Done",
            "metadata": {
                "unified_control_plan": {
                    "decision_authority": "subject_decision_authority",
                    "chosen_model": "claude-3-5-sonnet",
                    "chosen_provider": "anthropic",
                    "is_native_multimodal": False,
                    "lifecycle_target": "succeeded",
                    "fallback_level": "none",
                    "fallback_reason": None,
                    "chosen_execution_decision": {
                        "execution_path": "local",
                        "delegation_point": None,
                        "remote_execution_mode": None,
                        "target_device_ids": [],
                        "orchestration_active": False,
                    },
                    "canonical_perception": {"has_multimodal_input": False, "active_modalities": []},
                    "fallback_decision_record": None,
                }
            },
        }
        dsp = runtime.build_desktop_status_projection(result=mock_result, tristate="silent")
        assert dsp["model_routing"]["selected_provider"] == "anthropic"
        assert dsp["model_routing"]["selected_model"] == "claude-3-5-sonnet"

    def test_shell_builds_projection_without_result(self):
        """Shell projection is valid when result dict is None."""
        from core.desktop_presence_runtime import DesktopPresenceRuntime
        runtime = DesktopPresenceRuntime()
        dsp = runtime.build_desktop_status_projection(result=None, tristate="silent")
        assert dsp is not None
        assert isinstance(dsp, dict)

    def test_shell_projection_does_not_reconstruct_routing(self):
        """Shell consumes provider/model from projection, not from ad hoc logic."""
        from core.desktop_presence_runtime import DesktopPresenceRuntime
        runtime = DesktopPresenceRuntime()
        mock_result = {
            "metadata": {
                "unified_control_plan": {
                    "decision_authority": "subject_decision_authority",
                    "chosen_model": "gpt-4-turbo",
                    "chosen_provider": "openai",
                    "is_native_multimodal": False,
                    "lifecycle_target": "succeeded",
                    "fallback_level": "none",
                    "fallback_reason": None,
                    "chosen_execution_decision": {
                        "execution_path": "local",
                        "delegation_point": None,
                        "remote_execution_mode": None,
                        "target_device_ids": [],
                        "orchestration_active": False,
                    },
                    "canonical_perception": {"has_multimodal_input": False},
                    "fallback_decision_record": None,
                }
            }
        }
        dsp = runtime.build_desktop_status_projection(result=mock_result, tristate="silent")
        # The projection surfaces the provider from the control plan directly.
        assert dsp["model_routing"]["selected_provider"] == "openai"
        # No "re-inference" needed — the shell just reads from the projection.
        assert dsp["lifecycle"]["decision_authority"] == "subject_decision_authority"


# ===========================================================================
# Serialisation — to_dict / from_dict round-trip
# ===========================================================================


class TestSerialisation:
    def test_to_dict_is_json_serialisable(self):
        from contracts.desktop_status_projection import build_desktop_status_projection
        proj = build_desktop_status_projection(unified_control_plan=_minimal_plan())
        d = proj.to_dict()
        assert json.dumps(d) is not None

    def test_to_json_is_valid_string(self):
        from contracts.desktop_status_projection import build_desktop_status_projection
        proj = build_desktop_status_projection(unified_control_plan=_minimal_plan())
        s = proj.to_json()
        assert isinstance(s, str)
        parsed = json.loads(s)
        assert "projection_id" in parsed

    def test_from_dict_round_trip(self):
        from contracts.desktop_status_projection import build_desktop_status_projection, DesktopStatusProjection
        proj = build_desktop_status_projection(unified_control_plan=_minimal_plan())
        d = proj.to_dict()
        proj2 = DesktopStatusProjection.from_dict(d)
        assert proj2.projection_id == proj.projection_id
        assert proj2.overall_health == proj.overall_health
        assert proj2.lifecycle.stage == proj.lifecycle.stage
        assert proj2.model_routing.selected_provider == proj.model_routing.selected_provider
        assert proj2.execution.execution_path == proj.execution.execution_path

    def test_from_dict_with_empty_dict(self):
        from contracts.desktop_status_projection import DesktopStatusProjection
        proj = DesktopStatusProjection.from_dict({})
        assert proj is not None

    def test_multimodal_plan_round_trip(self):
        from contracts.desktop_status_projection import build_desktop_status_projection, DesktopStatusProjection
        proj = build_desktop_status_projection(unified_control_plan=_multimodal_plan())
        d = proj.to_dict()
        proj2 = DesktopStatusProjection.from_dict(d)
        assert proj2.model_routing.is_native_multimodal is True
        assert "audio" in proj2.perception.active_modalities

    def test_fallback_plan_round_trip(self):
        from contracts.desktop_status_projection import build_desktop_status_projection, DesktopStatusProjection
        proj = build_desktop_status_projection(unified_control_plan=_fallback_plan())
        d = proj.to_dict()
        proj2 = DesktopStatusProjection.from_dict(d)
        assert proj2.explainability.has_fallback is True
        assert len(proj2.explainability.fallback_kinds) > 0

    def test_json_contains_all_top_level_keys(self):
        from contracts.desktop_status_projection import build_desktop_status_projection
        proj = build_desktop_status_projection(unified_control_plan=_minimal_plan())
        d = proj.to_dict()
        for key in ("projection_id", "projected_at", "overall_health", "schema_version",
                    "perception", "model_routing", "execution", "lifecycle", "explainability"):
            assert key in d, f"Missing key: {key}"


# ===========================================================================
# desktop_status_projection_summary
# ===========================================================================


class TestProjectionSummary:
    def test_summary_is_dict(self):
        from contracts.desktop_status_projection import build_desktop_status_projection, desktop_status_projection_summary
        proj = build_desktop_status_projection(unified_control_plan=_minimal_plan())
        s = desktop_status_projection_summary(proj)
        assert isinstance(s, dict)

    def test_summary_none_for_none_projection(self):
        from contracts.desktop_status_projection import desktop_status_projection_summary
        assert desktop_status_projection_summary(None) is None

    def test_summary_contains_expected_keys(self):
        from contracts.desktop_status_projection import build_desktop_status_projection, desktop_status_projection_summary
        proj = build_desktop_status_projection(unified_control_plan=_minimal_plan())
        s = desktop_status_projection_summary(proj)
        for key in (
            "projection_id", "overall_health", "lifecycle_stage", "tristate",
            "selected_provider", "selected_model", "is_native_multimodal",
            "execution_path", "remote_execution_mode", "orchestration_active",
            "continuous_perception_active", "active_modalities",
            "has_fallback", "fallback_kinds", "degradation_summary",
        ):
            assert key in s, f"Missing summary key: {key}"

    def test_summary_json_serialisable(self):
        from contracts.desktop_status_projection import build_desktop_status_projection, desktop_status_projection_summary
        proj = build_desktop_status_projection(unified_control_plan=_fallback_plan())
        s = desktop_status_projection_summary(proj)
        assert json.dumps(s) is not None

    def test_summary_execution_path_matches_projection(self):
        from contracts.desktop_status_projection import build_desktop_status_projection, desktop_status_projection_summary
        proj = build_desktop_status_projection(unified_control_plan=_cross_device_plan())
        s = desktop_status_projection_summary(proj)
        assert s["execution_path"] == "cross_device"
        assert s["remote_execution_mode"] == "agent_runtime"

    def test_summary_fallback_reflects_degradation(self):
        from contracts.desktop_status_projection import build_desktop_status_projection, desktop_status_projection_summary
        proj = build_desktop_status_projection(unified_control_plan=_fallback_plan())
        s = desktop_status_projection_summary(proj)
        assert s["has_fallback"] is True
        assert len(s["fallback_kinds"]) > 0
        assert s["degradation_summary"] is not None


# ===========================================================================
# Overall health roll-up
# ===========================================================================


class TestOverallHealthRollup:
    def test_ok_for_clean_text_flow_with_model(self):
        from contracts.desktop_status_projection import build_desktop_status_projection, ProjectionHealthSeverity
        plan = _minimal_plan()
        plan["chosen_model"] = "gpt-4o"
        plan["chosen_provider"] = "openai"
        proj = build_desktop_status_projection(
            unified_control_plan=plan,
            tristate="silent",
        )
        # With a model present and no fallback, overall health should be ok or advisory.
        assert proj.overall_health in (
            ProjectionHealthSeverity.ok,
            ProjectionHealthSeverity.advisory,
        )

    def test_degraded_for_fallback_plan(self):
        from contracts.desktop_status_projection import build_desktop_status_projection, ProjectionHealthSeverity
        proj = build_desktop_status_projection(unified_control_plan=_fallback_plan())
        assert proj.overall_health in (
            ProjectionHealthSeverity.degraded,
            ProjectionHealthSeverity.critical,
        )

    def test_critical_for_unavailable_provider(self):
        from contracts.desktop_status_projection import build_desktop_status_projection, ProjectionHealthSeverity
        plan = _minimal_plan()
        plan["chosen_model"] = "gpt-4o"
        plan["chosen_provider"] = "openai"
        plan["canonical_model_supply"] = {
            "providers": [
                {"provider_id": "openai", "health_status": "unavailable"},
            ]
        }
        proj = build_desktop_status_projection(unified_control_plan=plan)
        assert proj.overall_health == ProjectionHealthSeverity.critical
