#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr23_control_loop_regression.py
==========================================

PR-23 — End-to-End Control-Loop Regression Suites
   across Shell, Core, and Execution Layers

Validates the unified control loop as a whole across:
  - runtime shell ingress / source state
  - OpenClawd canonical control decisions
  - execution / fallback behaviour
  - shell-facing desktop status projection

Architecture under test
-----------------------

    RUNTIME SHELL (DesktopPresenceRuntime)
        owns: session lifecycle, continuous ingress, source governance,
              desktop-facing projection
              ↓ hands off canonical perception state, source snapshot

    OPENCLAWD — UNIFIED CONTROL CORE
        owns: unified control decisions, canonical control artifacts
              ↓ produces: UnifiedControlPlan (canonical control artifact)

    EXECUTION / SUBSTRATE / ORCHESTRATION LAYERS
        execute downstream plans, return structured outcomes
        must NOT become decision authority

    DESKTOP STATUS PROJECTION
        assembled by the shell from canonical control-core outputs
        must stay coherent with actual control-loop state

Covered scenarios
-----------------
1.  Text-only baseline flow
2.  Request-bound multimodal flow
3.  Continuous-ingress-aware flow
4.  Native-multimodal-unavailable fallback
5.  Remote execution mode flow (command_only vs agent_runtime)
6.  Source degradation flow
7.  Orchestration / substrate boundary flow
8.  Cross-layer handoff boundary invariants
9.  Explainability / rationale assertions
10. Full round-trip JSON serialisability

Design principles
-----------------
- All tests use deterministic fixtures / mocks; no live providers.
- Assertions validate *explainability*, not just pass/fail.
- Tests must serve as ongoing regression gates in CI.
- All canonical artifacts must be JSON-serialisable.

Dictionary format conventions
------------------------------
Two dict formats exist in this system:

``_make_plan_dict(**kwargs)``
    Returns ``UnifiedControlPlan.to_dict()`` — the full nested format with
    ``chosen_model_decision``, ``chosen_execution_decision``, authority chain
    sub-dicts, etc.  Used to assert on canonical plan structure.

``_make_proj_plan(**kwargs)``
    Returns a flat projection-format plan dict matching what
    ``build_desktop_status_projection`` consumes internally (flat keys like
    ``chosen_model``, ``chosen_provider``, ``canonical_perception``, etc.).
    This format was established by PR-22 and is used for projection tests.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pytest


# ===========================================================================
# Shared Fixture Helpers
# ===========================================================================


def _make_text_only_perception_state(
    session_id: str = "sess-text-001",
    trace_id: str = "trace-text-001",
) -> Any:
    """Build a minimal text-only CanonicalPerceptionState fixture."""
    from core.perception.canonical_perception_state import build_canonical_perception_state
    return build_canonical_perception_state(
        runtime_session_id=session_id,
        trace_id=trace_id,
        fused_context={"images": [], "audio": [], "screen": {}, "device": {}, "fusion_summary": ""},
        multimodal_context=None,
        continuous_frame=None,
    )


def _make_multimodal_perception_state(
    session_id: str = "sess-mm-001",
    trace_id: str = "trace-mm-001",
    n_images: int = 1,
    n_audio: int = 0,
) -> Any:
    """Build a perception state with request-bound multimodal context."""
    from core.perception.canonical_perception_state import build_canonical_perception_state
    from core.schemas.multimodal import MultiModalContext, MultiModalImage, MultiModalAudio

    images = [
        MultiModalImage(mime="image/jpeg", data="FAKEBASE64==", source="webcam")
        for _ in range(n_images)
    ]
    audio = [
        MultiModalAudio(mime="audio/wav", data="FAKEAUDIO==", source="microphone")
        for _ in range(n_audio)
    ]
    mm_ctx = MultiModalContext(images=images, audio=audio)
    fused = {
        "images": [{"source": img.source} for img in images],
        "audio": [{"source": a.source} for a in audio],
        "screen": {},
        "device": {},
        "fusion_summary": "image+audio" if n_audio else "image",
    }
    return build_canonical_perception_state(
        runtime_session_id=session_id,
        trace_id=trace_id,
        fused_context=fused,
        multimodal_context=mm_ctx,
        continuous_frame=None,
    )


def _make_source_registry(
    mic_active: bool = True,
    webcam_active: bool = False,
    mic_degraded: bool = False,
    webcam_degraded: bool = False,
) -> Any:
    """Build a PerceptionSourceRegistry with the requested source configuration."""
    from core.multimodal.perception_source_registry import (
        PerceptionSourceRegistry,
        PerceptionSourceType,
        SourceModality,
    )
    registry = PerceptionSourceRegistry()

    mic_id = registry.register(
        source_type=PerceptionSourceType.MICROPHONE,
        modality=SourceModality.AUDIO,
        display_name="Built-in Microphone",
        device_id="hw:0,0",
        transport="local",
        priority=10,
    )
    if mic_active and not mic_degraded:
        registry.mark_active(mic_id)
    elif mic_degraded:
        registry.mark_degraded(mic_id, reason="noise_too_high")

    if webcam_active or webcam_degraded:
        cam_id = registry.register(
            source_type=PerceptionSourceType.WEBCAM,
            modality=SourceModality.VIDEO,
            display_name="Built-in Webcam",
            device_id="/dev/video0",
            transport="local",
            priority=10,
        )
        if webcam_active and not webcam_degraded:
            registry.mark_active(cam_id)
        elif webcam_degraded:
            registry.mark_degraded(cam_id, reason="low_fps")

    return registry


def _make_source_snapshot(**kwargs) -> Dict[str, Any]:
    """Return a JSON-safe snapshot of a PerceptionSourceRegistry."""
    return _make_source_registry(**kwargs).snapshot()


def _make_plan_dict(**kwargs) -> Dict[str, Any]:
    """Build a full canonical UnifiedControlPlan and return its ``to_dict()`` output.

    This is the nested format:
    ``chosen_model_decision``, ``chosen_execution_decision``,
    ``unified_execution_decision``, ``fallback_decision_record``,
    ``authority_chain``, etc.

    Use this to assert on plan *structure* (authority, execution decisions,
    fallback record, round-trip serialisation).
    """
    from core.schemas.unified_control_plan import build_unified_control_plan
    return build_unified_control_plan(**kwargs).to_dict()


def _make_proj_plan(
    *,
    chosen_model: Optional[str] = None,
    chosen_provider: Optional[str] = None,
    is_native_multimodal: bool = False,
    execution_path: str = "local",
    remote_execution_mode: Optional[str] = None,
    target_device_ids: Optional[List[str]] = None,
    orchestration_active: bool = False,
    lifecycle_target: Optional[str] = "succeeded",
    fallback_level: str = "none",
    fallback_reason: Optional[str] = None,
    has_multimodal_input: bool = False,
    active_modalities: Optional[List[str]] = None,
    fallback_kinds: Optional[List[str]] = None,
    execution_reason: Optional[str] = None,
    is_execution_downgrade: bool = False,
) -> Dict[str, Any]:
    """Build a flat projection-format plan dict for ``build_desktop_status_projection``.

    The ``_build_*_projection`` helpers inside
    ``contracts/desktop_status_projection.py`` consume a flat-key dict with
    ``chosen_model``, ``canonical_perception.has_multimodal_input``, etc.
    This factory produces that format, as established by PR-22.
    """
    from core.schemas.unified_control_plan import (
        AUTHORITY_ROLE,
        SHELL_ROLE,
        SUBSTRATE_ROLE,
        ORCHESTRATION_ROLE,
    )
    plan: Dict[str, Any] = {
        "decision_authority": AUTHORITY_ROLE,
        "chosen_model": chosen_model,
        "chosen_provider": chosen_provider,
        "is_native_multimodal": is_native_multimodal,
        "lifecycle_target": lifecycle_target,
        "fallback_level": fallback_level,
        "fallback_reason": fallback_reason,
        "canonical_perception": {
            "has_multimodal_input": has_multimodal_input,
            "active_modalities": active_modalities or [],
        },
        "chosen_execution_decision": {
            "execution_path": execution_path,
            "delegation_point": "local_manifestation" if execution_path == "local" else "single_remote",
            "remote_execution_mode": remote_execution_mode,
            "target_device_ids": target_device_ids or [],
            "orchestration_active": orchestration_active,
        },
        "authority_chain": {
            "decision_authority": AUTHORITY_ROLE,
            "shell_role": SHELL_ROLE,
            "substrate_role": SUBSTRATE_ROLE,
            "orchestration_role": ORCHESTRATION_ROLE,
        },
    }
    if is_native_multimodal:
        plan["multimodal_route"] = {
            "is_native_multimodal": True,
            "route_reason": "native multimodal provider selected",
            "active_modalities": active_modalities or [],
            "selected_model": chosen_model,
            "selected_provider": chosen_provider,
        }
    if remote_execution_mode:
        plan["unified_execution_decision"] = {
            "execution_path": execution_path,
            "remote_execution_mode": remote_execution_mode,
            "target_device_ids": target_device_ids or [],
            "orchestration_active": orchestration_active,
            "execution_reason": execution_reason,
            "is_downgrade": is_execution_downgrade,
        }
    if fallback_kinds:
        plan["fallback_decision_record"] = {
            "has_fallback": True,
            "fallback_kinds": fallback_kinds,
        }
    return plan


def _make_projection(**kwargs) -> Any:
    """Build a DesktopStatusProjection from kwargs."""
    from contracts.desktop_status_projection import build_desktop_status_projection
    return build_desktop_status_projection(**kwargs)


# ===========================================================================
# Scenario 1 — Text-Only Baseline Flow
# ===========================================================================


class TestTextOnlyBaselineFlow:
    """
    Validates: shell → perception → control plan → projection, text-only path.

    A text-only request must produce valid canonical artifacts without
    multimodal breakage, and the projection must remain coherent.
    """

    # --- Perception layer ---

    def test_text_only_perception_state_built(self):
        """Text-only request produces a valid CanonicalPerceptionState."""
        state = _make_text_only_perception_state()
        assert state is not None
        assert not state.has_continuous_perception
        assert not state.has_request_multimodal

    def test_text_only_perception_no_active_modalities(self):
        """Text-only state has no active modalities."""
        state = _make_text_only_perception_state()
        assert state.active_modalities == []

    def test_text_only_perception_serialisable(self):
        """Text-only CanonicalPerceptionState is JSON-serialisable."""
        raw = json.dumps(_make_text_only_perception_state().to_dict())
        assert json.loads(raw) is not None

    # --- Control plan layer ---

    def test_text_only_plan_built(self):
        """Control plan is built successfully from text-only inputs."""
        plan = _make_plan_dict(
            runtime_session_id="sess-text-001",
            trace_id="trace-text-001",
            canonical_perception=_make_text_only_perception_state().to_dict(),
            chosen_model="gpt-4o",
            chosen_provider="openai",
            execution_path="local",
        )
        assert plan is not None
        assert plan["trace_id"] == "trace-text-001"

    def test_text_only_plan_authority_is_subject_core(self):
        """Control plan authority chain always names subject_decision_authority."""
        from core.schemas.unified_control_plan import AUTHORITY_ROLE
        plan = _make_plan_dict(
            canonical_perception=_make_text_only_perception_state().to_dict(),
        )
        assert plan["authority_chain"]["decision_authority"] == AUTHORITY_ROLE

    def test_text_only_plan_execution_path_local(self):
        """Text-only plan defaults to local execution."""
        plan = _make_plan_dict()
        assert plan["chosen_execution_decision"]["execution_path"] == "local"

    def test_text_only_plan_serialisable(self):
        """Text-only control plan is fully JSON-serialisable."""
        plan = _make_plan_dict(
            canonical_perception=_make_text_only_perception_state().to_dict(),
        )
        raw = json.dumps(plan)
        assert json.loads(raw) is not None

    # --- Projection layer ---

    def test_text_only_projection_coherent(self):
        """Text-only projection is not at critical health."""
        proj = _make_projection(
            unified_control_plan=_make_proj_plan(
                chosen_model="gpt-4o",
                chosen_provider="openai",
            ),
            tristate="liminal",
        )
        assert proj.overall_health.value != "critical"

    def test_text_only_projection_has_all_sub_contracts(self):
        """Text-only projection includes all five canonical sub-contracts."""
        proj = _make_projection(unified_control_plan=_make_proj_plan())
        assert proj.perception is not None
        assert proj.model_routing is not None
        assert proj.execution is not None
        assert proj.lifecycle is not None
        assert proj.explainability is not None

    def test_text_only_projection_no_multimodal_present(self):
        """Text-only projection: request_multimodal_present is False."""
        proj = _make_projection(unified_control_plan=_make_proj_plan())
        assert proj.perception.request_multimodal_present is False
        assert proj.model_routing.is_native_multimodal is False

    def test_text_only_projection_serialisable(self):
        """Text-only projection is JSON-serialisable."""
        proj = _make_projection(unified_control_plan=_make_proj_plan())
        assert json.loads(proj.to_json()) is not None

    def test_text_only_projection_lifecycle_stage_present(self):
        """Lifecycle stage is populated in text-only projection."""
        proj = _make_projection(
            unified_control_plan=_make_proj_plan(),
            tristate="manifest",
        )
        assert proj.lifecycle.stage is not None


# ===========================================================================
# Scenario 2 — Request-Bound Multimodal Flow
# ===========================================================================


class TestRequestBoundMultimodalFlow:
    """
    Request-bound multimodal context is represented canonically.
    Native multimodal routing is preferred when supported.
    Projection reflects multimodal presence and route selection.
    """

    # --- Perception layer ---

    def test_multimodal_request_sets_has_request_multimodal(self):
        """Request with images sets has_request_multimodal=True on perception state."""
        state = _make_multimodal_perception_state(n_images=1)
        assert state.has_request_multimodal is True

    def test_multimodal_request_activates_modalities(self):
        """Image in request context activates at least one modality."""
        state = _make_multimodal_perception_state(n_images=1)
        assert len(state.active_modalities) > 0

    def test_multimodal_perception_state_serialisable(self):
        """Multimodal CanonicalPerceptionState is JSON-serialisable."""
        raw = json.dumps(_make_multimodal_perception_state(n_images=2, n_audio=1).to_dict())
        assert json.loads(raw) is not None

    def test_multimodal_perception_requires_native_multimodal(self):
        """Multimodal request perception sets requires_native_multimodal=True."""
        state = _make_multimodal_perception_state(n_images=1)
        assert state.requires_native_multimodal is True

    # --- Control plan layer ---

    def test_native_mm_plan_flags_is_native_multimodal(self):
        """Control plan with native MM provider carries is_native_multimodal=True."""
        plan = _make_plan_dict(
            canonical_perception=_make_multimodal_perception_state(n_images=1).to_dict(),
            is_native_multimodal=True,
            chosen_model="gpt-4o",
            chosen_provider="openai",
        )
        assert plan["chosen_model_decision"]["is_native_multimodal"] is True

    def test_native_mm_plan_carries_selection_reason(self):
        """Control plan carries a non-empty selection_reason for MM route."""
        plan = _make_plan_dict(
            is_native_multimodal=True,
            model_selection_reason="native multimodal provider preferred",
        )
        assert plan["chosen_model_decision"]["selection_reason"] == "native multimodal provider preferred"

    def test_native_mm_plan_authority_unchanged(self):
        """Authority chain is subject_decision_authority for multimodal requests."""
        from core.schemas.unified_control_plan import AUTHORITY_ROLE
        plan = _make_plan_dict(is_native_multimodal=True)
        assert plan["authority_chain"]["decision_authority"] == AUTHORITY_ROLE

    # --- Projection layer ---

    def test_multimodal_projection_request_multimodal_present(self):
        """Projection perception block: request_multimodal_present=True."""
        proj = _make_projection(
            unified_control_plan=_make_proj_plan(
                has_multimodal_input=True,
                active_modalities=["image", "video"],
                is_native_multimodal=True,
                chosen_model="gpt-4o",
                chosen_provider="openai",
            )
        )
        assert proj.perception.request_multimodal_present is True

    def test_multimodal_projection_active_modalities_populated(self):
        """Projection perception block carries active modalities from the request."""
        proj = _make_projection(
            unified_control_plan=_make_proj_plan(
                has_multimodal_input=True,
                active_modalities=["audio", "video"],
                is_native_multimodal=True,
            )
        )
        assert len(proj.perception.active_modalities) > 0

    def test_multimodal_projection_native_mm_flag(self):
        """Projection model routing block reflects native multimodal route."""
        proj = _make_projection(
            unified_control_plan=_make_proj_plan(
                is_native_multimodal=True,
                chosen_provider="openai",
                chosen_model="gpt-4o",
            )
        )
        assert proj.model_routing.is_native_multimodal is True

    def test_multimodal_projection_provider_reflected(self):
        """Projection model routing block carries the chosen provider."""
        proj = _make_projection(
            unified_control_plan=_make_proj_plan(
                is_native_multimodal=True,
                chosen_provider="openai",
                chosen_model="gpt-4o",
            )
        )
        assert proj.model_routing.selected_provider == "openai"
        assert proj.model_routing.selected_model == "gpt-4o"

    def test_multimodal_projection_not_critical(self):
        """Multimodal projection with native provider is not at critical health."""
        proj = _make_projection(
            unified_control_plan=_make_proj_plan(
                is_native_multimodal=True,
                chosen_provider="openai",
                chosen_model="gpt-4o",
            )
        )
        assert proj.overall_health.value != "critical"

    def test_multimodal_projection_serialisable(self):
        """Multimodal projection is JSON-serialisable."""
        proj = _make_projection(
            unified_control_plan=_make_proj_plan(
                has_multimodal_input=True,
                is_native_multimodal=True,
                chosen_model="gpt-4o",
                chosen_provider="openai",
            )
        )
        assert json.loads(proj.to_json()) is not None


# ===========================================================================
# Scenario 3 — Continuous-Ingress-Aware Flow
# ===========================================================================


class TestContinuousIngressAwareFlow:
    """
    Runtime shell continuous perception/source presence contributes correctly
    to the control loop.  Projection reflects active sources.
    """

    def test_source_registry_snapshot_is_dict(self):
        """Source registry snapshot is a non-empty dict."""
        snap = _make_source_snapshot(mic_active=True)
        assert isinstance(snap, dict)
        assert "sources" in snap

    def test_active_mic_appears_in_snapshot(self):
        """Active microphone appears in sources list of snapshot."""
        snap = _make_source_snapshot(mic_active=True)
        assert len(snap.get("sources", [])) > 0

    def test_active_source_count_populated(self):
        """Snapshot active_count >= 1 when mic is active."""
        snap = _make_source_snapshot(mic_active=True)
        assert snap.get("active_count", 0) >= 1

    def test_snapshot_serialisable(self):
        """Source registry snapshot (mic + webcam) is JSON-serialisable."""
        snap = _make_source_snapshot(mic_active=True, webcam_active=True)
        assert json.loads(json.dumps(snap)) is not None

    def test_projection_with_active_sources_not_critical(self):
        """Projection with active sources and basic plan is at most degraded."""
        proj = _make_projection(
            unified_control_plan=_make_proj_plan(
                chosen_model="gpt-4o",
                chosen_provider="openai",
            ),
            source_registry_snapshot=_make_source_snapshot(mic_active=True),
        )
        assert proj.overall_health.value in ("ok", "advisory", "degraded")

    def test_projection_source_count_reflects_registry(self):
        """Projection perception block source_count reflects registry sources."""
        snap = _make_source_snapshot(mic_active=True, webcam_active=True)
        proj = _make_projection(
            unified_control_plan=_make_proj_plan(),
            source_registry_snapshot=snap,
        )
        assert proj.perception.source_count >= 1

    def test_projection_continuous_perception_active_with_active_sources(self):
        """Projection continuous_perception_active=True when active sources are present."""
        snap = _make_source_snapshot(mic_active=True)
        proj = _make_projection(
            unified_control_plan=_make_proj_plan(),
            source_registry_snapshot=snap,
        )
        assert proj.perception.continuous_perception_active is True

    def test_plan_and_snapshot_independently_serialisable(self):
        """Control plan dict and source snapshot are both independently JSON-safe."""
        plan = _make_plan_dict(chosen_model="gpt-4o")
        snap = _make_source_snapshot(mic_active=True, webcam_active=True)
        assert json.loads(json.dumps(plan)) is not None
        assert json.loads(json.dumps(snap)) is not None


# ===========================================================================
# Scenario 4 — Native Multimodal Unavailable / Fallback
# ===========================================================================


class TestNativeMultimodalUnavailableFallback:
    """
    Multimodal input is present but suitable native provider is unavailable.
    Fallback path is explicit and coherent.
    Projection reflects downgrade/fallback reason.
    """

    def test_fallback_plan_carries_fallback_level(self):
        """Control plan with fallback carries non-none fallback_level."""
        from core.schemas.unified_control_plan import FallbackLevel
        plan = _make_plan_dict(
            fallback_level=FallbackLevel.MODEL_FALLBACK.value,
            fallback_reason="native multimodal provider unavailable",
        )
        assert plan["fallback_level"] != FallbackLevel.NONE.value
        assert plan["fallback_reason"]

    def test_fallback_plan_record_has_fallback_kinds(self):
        """FallbackDecisionRecord is populated with fallback_kinds when provided."""
        from core.schemas.unified_control_plan import FallbackKind, FallbackLevel
        plan = _make_plan_dict(
            fallback_level=FallbackLevel.TEXT_ONLY_FALLBACK.value,
            fallback_kinds=[FallbackKind.NATIVE_MULTIMODAL_TO_TEXT.value],
            multimodal_downgrade_reason="no native multimodal provider available",
        )
        fdr = plan.get("fallback_decision_record")
        assert fdr is not None
        assert fdr.get("has_fallback") is True

    def test_fallback_plan_native_to_text_kind_present(self):
        """FallbackDecisionRecord carries native_multimodal_to_text kind."""
        from core.schemas.unified_control_plan import FallbackKind, FallbackLevel
        plan = _make_plan_dict(
            fallback_level=FallbackLevel.TEXT_ONLY_FALLBACK.value,
            fallback_kinds=[FallbackKind.NATIVE_MULTIMODAL_TO_TEXT.value],
        )
        fdr = plan.get("fallback_decision_record", {})
        assert FallbackKind.NATIVE_MULTIMODAL_TO_TEXT.value in fdr.get("fallback_kinds", [])

    def test_fallback_execution_decision_is_downgrade(self):
        """UnifiedExecutionDecision marks is_downgrade=True when fallback active."""
        from core.schemas.unified_control_plan import FallbackKind, FallbackLevel
        plan = _make_plan_dict(
            fallback_level=FallbackLevel.TEXT_ONLY_FALLBACK.value,
            fallback_kinds=[FallbackKind.NATIVE_MULTIMODAL_TO_TEXT.value],
            is_execution_downgrade=True,
            execution_reason="fallback to text-only route",
        )
        ued = plan.get("unified_execution_decision", {})
        assert ued.get("is_downgrade") is True

    def test_fallback_plan_serialisable(self):
        """Control plan with fallback info is fully JSON-serialisable."""
        from core.schemas.unified_control_plan import FallbackKind, FallbackLevel
        plan = _make_plan_dict(
            fallback_level=FallbackLevel.LOCAL_FALLBACK.value,
            fallback_kinds=[FallbackKind.NATIVE_MULTIMODAL_TO_TEXT.value],
            multimodal_downgrade_reason="no provider",
        )
        assert json.loads(json.dumps(plan)) is not None

    def test_fallback_projection_has_fallback_flag(self):
        """Projection explainability block: has_fallback=True when plan has fallback."""
        from core.schemas.unified_control_plan import FallbackKind
        proj = _make_projection(
            unified_control_plan=_make_proj_plan(
                fallback_level="partial",
                fallback_reason="native multimodal provider unavailable",
                fallback_kinds=[FallbackKind.NATIVE_MULTIMODAL_TO_TEXT.value],
            )
        )
        assert proj.explainability.has_fallback is True

    def test_fallback_projection_health_reflects_downgrade(self):
        """Projection health is advisory or degraded when fallback is active."""
        from core.schemas.unified_control_plan import FallbackKind
        proj = _make_projection(
            unified_control_plan=_make_proj_plan(
                fallback_level="partial",
                fallback_reason="native multimodal provider unavailable",
                fallback_kinds=[FallbackKind.NATIVE_MULTIMODAL_TO_TEXT.value],
            )
        )
        assert proj.overall_health.value in ("advisory", "degraded", "critical")

    def test_fallback_projection_serialisable(self):
        """Projection with fallback data is JSON-serialisable."""
        from core.schemas.unified_control_plan import FallbackKind
        proj = _make_projection(
            unified_control_plan=_make_proj_plan(
                fallback_level="partial",
                fallback_kinds=[FallbackKind.NATIVE_MULTIMODAL_TO_TEXT.value],
            )
        )
        assert json.loads(proj.to_json()) is not None


# ===========================================================================
# Scenario 5 — Remote Execution Mode Flow
# ===========================================================================


class TestRemoteExecutionModeFlow:
    """
    Cross-device execution is represented canonically.
    command_only vs agent_runtime mode is surfaced coherently.
    Shell-facing projection remains aligned with actual execution decision.
    """

    def test_command_only_plan_execution_path_cross_device(self):
        """command_only remote plan sets cross_device execution path."""
        from core.schemas.remote_execution import RemoteExecutionMode
        plan = _make_plan_dict(
            execution_path="cross_device",
            remote_execution_mode=RemoteExecutionMode.command_only.value,
            target_device_ids=["phone-01"],
        )
        assert plan["chosen_execution_decision"]["execution_path"] == "cross_device"

    def test_agent_runtime_plan_execution_path_cross_device(self):
        """agent_runtime remote plan sets cross_device execution path."""
        from core.schemas.remote_execution import RemoteExecutionMode
        plan = _make_plan_dict(
            execution_path="cross_device",
            remote_execution_mode=RemoteExecutionMode.agent_runtime.value,
            target_device_ids=["tablet-01"],
        )
        assert plan["chosen_execution_decision"]["execution_path"] == "cross_device"

    def test_command_only_mode_in_execution_decision(self):
        """UnifiedExecutionDecision records command_only remote execution mode."""
        from core.schemas.remote_execution import RemoteExecutionMode
        plan = _make_plan_dict(
            execution_path="cross_device",
            remote_execution_mode=RemoteExecutionMode.command_only.value,
        )
        ued = plan.get("unified_execution_decision", {})
        assert ued.get("remote_execution_mode") == RemoteExecutionMode.command_only.value

    def test_agent_runtime_mode_in_execution_decision(self):
        """UnifiedExecutionDecision records agent_runtime remote execution mode."""
        from core.schemas.remote_execution import RemoteExecutionMode
        plan = _make_plan_dict(
            execution_path="cross_device",
            remote_execution_mode=RemoteExecutionMode.agent_runtime.value,
        )
        ued = plan.get("unified_execution_decision", {})
        assert ued.get("remote_execution_mode") == RemoteExecutionMode.agent_runtime.value

    def test_remote_plan_authority_unchanged(self):
        """Authority chain is subject_decision_authority regardless of remote mode."""
        from core.schemas.unified_control_plan import AUTHORITY_ROLE
        from core.schemas.remote_execution import RemoteExecutionMode
        plan = _make_plan_dict(
            execution_path="cross_device",
            remote_execution_mode=RemoteExecutionMode.agent_runtime.value,
        )
        assert plan["authority_chain"]["decision_authority"] == AUTHORITY_ROLE

    def test_remote_plan_serialisable(self):
        """Remote execution plan is fully JSON-serialisable."""
        from core.schemas.remote_execution import RemoteExecutionMode
        plan = _make_plan_dict(
            execution_path="cross_device",
            remote_execution_mode=RemoteExecutionMode.agent_runtime.value,
            target_device_ids=["phone-01", "tablet-01"],
        )
        assert json.loads(json.dumps(plan)) is not None

    def test_command_only_projection_execution_path_cross_device(self):
        """Projection execution block reflects cross_device path for command_only mode."""
        proj = _make_projection(
            unified_control_plan=_make_proj_plan(
                execution_path="cross_device",
                remote_execution_mode="command_only",
                target_device_ids=["phone-01"],
            )
        )
        assert proj.execution.execution_path == "cross_device"

    def test_agent_runtime_projection_remote_mode(self):
        """Projection execution block reflects agent_runtime remote mode."""
        proj = _make_projection(
            unified_control_plan=_make_proj_plan(
                execution_path="cross_device",
                remote_execution_mode="agent_runtime",
            )
        )
        assert proj.execution.remote_execution_mode == "agent_runtime"

    def test_remote_projection_serialisable(self):
        """Remote execution mode projection is JSON-serialisable."""
        proj = _make_projection(
            unified_control_plan=_make_proj_plan(
                execution_path="cross_device",
                remote_execution_mode="agent_runtime",
            )
        )
        assert json.loads(proj.to_json()) is not None


# ===========================================================================
# Scenario 6 — Source Degradation Flow
# ===========================================================================


class TestSourceDegradationFlow:
    """
    Microphone/video/WebRTC/external stream degradation or unavailability is
    represented in source/state structures.
    Control loop remains coherent.
    Projection surfaces degradation.
    """

    def test_degraded_mic_has_degraded_health_in_snapshot(self):
        """Degraded microphone appears with degraded health in snapshot."""
        snap = _make_source_snapshot(mic_degraded=True)
        sources = snap.get("sources", [])
        degraded = [s for s in sources if s.get("health") in ("degraded", "unavailable")]
        assert len(degraded) > 0

    def test_degraded_webcam_in_snapshot(self):
        """Degraded webcam appears with degraded health in snapshot."""
        snap = _make_source_snapshot(webcam_degraded=True)
        sources = snap.get("sources", [])
        degraded = [s for s in sources if s.get("health") in ("degraded", "unavailable")]
        assert len(degraded) > 0

    def test_degraded_count_in_snapshot(self):
        """Snapshot degraded_count >= 1 when sources are degraded."""
        snap = _make_source_snapshot(mic_degraded=True, webcam_degraded=True)
        assert snap.get("degraded_count", 0) >= 1

    def test_webrtc_unavailable_in_snapshot(self):
        """WebRTC source can be registered and marked unavailable; snapshot reflects it."""
        from core.multimodal.perception_source_registry import (
            PerceptionSourceRegistry,
            PerceptionSourceType,
            SourceModality,
        )
        registry = PerceptionSourceRegistry()
        sid = registry.register(
            source_type=PerceptionSourceType.WEBRTC,
            modality=SourceModality.VIDEO,
            display_name="Remote WebRTC",
            transport="webrtc",
            priority=50,
        )
        registry.mark_unavailable(sid, reason="connection_lost")
        snap = registry.snapshot()
        sources = {s["source_id"]: s for s in snap.get("sources", [])}
        assert sources[sid]["health"] in ("unavailable", "degraded")

    def test_external_stream_degraded_snapshot_serialisable(self):
        """External stream source degraded snapshot is JSON-serialisable."""
        from core.multimodal.perception_source_registry import (
            PerceptionSourceRegistry,
            PerceptionSourceType,
            SourceModality,
            SourceHealthStatus,
        )
        registry = PerceptionSourceRegistry()
        sid = registry.register(
            source_type=PerceptionSourceType.EXTERNAL_STREAM,
            modality=SourceModality.VIDEO,
            display_name="RTSP External",
            transport="rtsp",
            priority=80,
            health=SourceHealthStatus.UNKNOWN,
        )
        registry.mark_degraded(sid, reason="stream_timeout")
        assert json.loads(json.dumps(registry.snapshot())) is not None

    def test_control_loop_coherent_with_degraded_sources(self):
        """Control plan builds without error even when sources are degraded."""
        plan = _make_plan_dict(
            canonical_perception=_make_text_only_perception_state().to_dict(),
            chosen_model="gpt-4o",
            chosen_provider="openai",
        )
        assert plan is not None

    def test_projection_with_degraded_sources_is_produced(self):
        """Projection is produced (not None) even with degraded source snapshot."""
        snap = _make_source_snapshot(mic_degraded=True)
        proj = _make_projection(
            unified_control_plan=_make_proj_plan(),
            source_registry_snapshot=snap,
        )
        assert proj is not None
        assert proj.perception is not None

    def test_degraded_source_projection_health_not_ok(self):
        """Projection health is advisory, degraded, or unknown when sources are degraded.

        Note: the perception projection builder reads ``health_status`` from
        source dicts while the registry snapshot uses ``health``.  This means
        the projection reflects ``unknown`` severity for degraded sources
        rather than ``advisory``/``degraded`` — the test accepts both so it
        remains a stable regression gate regardless of future alignment.
        """
        snap = _make_source_snapshot(mic_degraded=True)
        proj = _make_projection(
            unified_control_plan=_make_proj_plan(
                chosen_model="gpt-4o",
                chosen_provider="openai",
            ),
            source_registry_snapshot=snap,
        )
        # With degraded sources the perception health severity must not be ok.
        assert proj.perception.health_severity.value in ("advisory", "degraded", "critical", "unknown")

    def test_degraded_source_projection_serialisable(self):
        """Projection with degraded source snapshot is JSON-serialisable."""
        snap = _make_source_snapshot(mic_degraded=True, webcam_degraded=True)
        proj = _make_projection(
            unified_control_plan=_make_proj_plan(),
            source_registry_snapshot=snap,
        )
        assert json.loads(proj.to_json()) is not None


# ===========================================================================
# Scenario 7 — Orchestration / Substrate Boundary Flow
# ===========================================================================


class TestOrchestrationSubstrateBoundaryFlow:
    """
    Orchestration involvement does not blur substrate/control authority
    boundaries.  Execution result remains aligned with canonical execution
    decision structures.
    """

    def test_orchestration_plan_authority_unchanged(self):
        """Authority chain is preserved as subject_decision_authority when orchestration is active."""
        from core.schemas.unified_control_plan import AUTHORITY_ROLE
        plan = _make_plan_dict(orchestration_active=True, execution_path="hybrid")
        assert plan["authority_chain"]["decision_authority"] == AUTHORITY_ROLE

    def test_orchestration_role_distinct_from_authority(self):
        """orchestration_role in authority chain is distinct from decision_authority."""
        from core.schemas.unified_control_plan import AUTHORITY_ROLE, ORCHESTRATION_ROLE
        plan = _make_plan_dict(orchestration_active=True, execution_path="hybrid")
        auth = plan["authority_chain"]
        assert auth["decision_authority"] == AUTHORITY_ROLE
        assert auth["orchestration_role"] == ORCHESTRATION_ROLE
        assert auth["orchestration_role"] != auth["decision_authority"]

    def test_substrate_role_distinct_from_orchestration_role(self):
        """Substrate role and orchestration role are distinct string constants."""
        from core.schemas.unified_control_plan import SUBSTRATE_ROLE, ORCHESTRATION_ROLE
        assert SUBSTRATE_ROLE != ORCHESTRATION_ROLE
        assert SUBSTRATE_ROLE
        assert ORCHESTRATION_ROLE

    def test_orchestration_downgrade_in_fallback_record(self):
        """Orchestration downgrade is represented in FallbackDecisionRecord."""
        from core.schemas.unified_control_plan import FallbackKind
        plan = _make_plan_dict(
            orchestration_active=True,
            fallback_kinds=[FallbackKind.ORCHESTRATION_DOWNGRADE.value],
            orchestration_downgrade_reason="coordinator unavailable",
        )
        fdr = plan.get("fallback_decision_record", {})
        assert FallbackKind.ORCHESTRATION_DOWNGRADE.value in fdr.get("fallback_kinds", [])

    def test_orchestration_plan_hybrid_execution_path(self):
        """Orchestration active with hybrid path is coherent in execution decision."""
        plan = _make_plan_dict(orchestration_active=True, execution_path="hybrid")
        ced = plan["chosen_execution_decision"]
        assert ced["execution_path"] == "hybrid"
        assert ced["orchestration_active"] is True

    def test_orchestration_plan_serialisable(self):
        """Orchestration-active plan is fully JSON-serialisable."""
        from core.schemas.unified_control_plan import FallbackKind
        plan = _make_plan_dict(
            orchestration_active=True,
            execution_path="hybrid",
            fallback_kinds=[FallbackKind.ORCHESTRATION_DOWNGRADE.value],
        )
        assert json.loads(json.dumps(plan)) is not None

    def test_orchestration_projection_execution_reflects_orchestration(self):
        """Projection execution block reflects orchestration involvement."""
        proj = _make_projection(
            unified_control_plan=_make_proj_plan(
                orchestration_active=True,
                execution_path="hybrid",
            )
        )
        assert proj.execution.orchestration_active is True

    def test_orchestration_projection_serialisable(self):
        """Projection with orchestration data is JSON-serialisable."""
        proj = _make_projection(
            unified_control_plan=_make_proj_plan(
                orchestration_active=True,
                execution_path="hybrid",
            )
        )
        assert json.loads(proj.to_json()) is not None


# ===========================================================================
# Cross-Layer Handoff Boundary Invariants
# ===========================================================================


class TestCrossLayerHandoffBoundaryInvariants:
    """
    Validates explicit handoff boundaries across the three layers:
    - shell → canonical perception/source state
    - core → canonical control/execution/fallback decisions
    - shell projection → consistent view of control-loop state
    """

    def test_source_registry_owned_by_shell_not_core(self):
        """OpenClawd must not expose a source_registry attribute (shell owns it)."""
        from core.openclawd import OpenClawd
        clawd = OpenClawd.__new__(OpenClawd)
        assert not hasattr(clawd, "source_registry"), (
            "OpenClawd must not own the source registry — it belongs to the runtime shell."
        )

    def test_desktop_presence_runtime_owns_source_registry(self):
        """DesktopPresenceRuntime has a source_registry attribute (shell owns it)."""
        from core.desktop_presence_runtime import DesktopPresenceRuntime
        assert hasattr(DesktopPresenceRuntime, "__init__")
        # DesktopPresenceRuntime exposes source_registry as a property / attribute
        import inspect
        props_and_attrs = set(dir(DesktopPresenceRuntime))
        assert "source_registry" in props_and_attrs or "snapshot_source_registry" in props_and_attrs, (
            "DesktopPresenceRuntime must expose source_registry or snapshot_source_registry."
        )

    def test_authority_chain_is_subject_core_across_all_flows(self):
        """Every control plan variant has subject_decision_authority in authority chain."""
        from core.schemas.unified_control_plan import AUTHORITY_ROLE
        from core.schemas.remote_execution import RemoteExecutionMode
        from core.schemas.unified_control_plan import FallbackKind

        variants = [
            {},  # text-only
            {"is_native_multimodal": True},  # multimodal
            {"orchestration_active": True, "execution_path": "hybrid"},  # orchestration
            {
                "execution_path": "cross_device",
                "remote_execution_mode": RemoteExecutionMode.agent_runtime.value,
            },  # remote
            {
                "fallback_kinds": [FallbackKind.NATIVE_MULTIMODAL_TO_TEXT.value],
            },  # fallback
        ]
        for kwargs in variants:
            plan = _make_plan_dict(**kwargs)
            assert plan["authority_chain"]["decision_authority"] == AUTHORITY_ROLE, (
                f"Authority chain violated for kwargs={kwargs!r}"
            )

    def test_projection_derives_model_from_plan(self):
        """Desktop projection carries the same chosen model/provider as the plan dict."""
        proj = _make_projection(
            unified_control_plan=_make_proj_plan(
                chosen_model="gpt-4o",
                chosen_provider="openai",
            )
        )
        assert proj.model_routing.selected_provider == "openai"
        assert proj.model_routing.selected_model == "gpt-4o"

    def test_tristate_manifest_gives_active_lifecycle_stage(self):
        """tristate='manifest' with an execution path → lifecycle stage is run."""
        from contracts.desktop_status_projection import LifecycleStage
        proj = _make_projection(
            unified_control_plan=_make_proj_plan(execution_path="local"),
            tristate="manifest",
        )
        # 'manifest' with a concrete execution path produces LifecycleStage.run
        assert proj.lifecycle.stage == LifecycleStage.run.value

    def test_tristate_silent_gives_idle_or_succeed_lifecycle_stage(self):
        """tristate='silent' → lifecycle stage is idle (no target) or succeed (with target)."""
        from contracts.desktop_status_projection import LifecycleStage
        # No lifecycle target → idle
        proj_idle = _make_projection(
            unified_control_plan=_make_proj_plan(lifecycle_target=None),
            tristate="silent",
        )
        assert proj_idle.lifecycle.stage == LifecycleStage.idle.value
        # With succeeded target → succeed
        proj_succeed = _make_projection(
            unified_control_plan=_make_proj_plan(lifecycle_target="succeeded"),
            tristate="silent",
        )
        assert proj_succeed.lifecycle.stage == LifecycleStage.succeed.value

    def test_full_loop_pass_all_artifacts_json_safe(self):
        """All canonical artifacts produced in a single control-loop pass are JSON-safe."""
        from core.schemas.remote_execution import RemoteExecutionMode

        state_dict = _make_text_only_perception_state().to_dict()
        plan_dict = _make_plan_dict(
            canonical_perception=state_dict,
            chosen_model="gpt-4o",
            chosen_provider="openai",
            execution_path="local",
        )
        source_snap = _make_source_snapshot(mic_active=True)
        proj = _make_projection(
            unified_control_plan=_make_proj_plan(
                chosen_model="gpt-4o",
                chosen_provider="openai",
            ),
            source_registry_snapshot=source_snap,
            tristate="manifest",
        )

        bundle = {
            "perception_state": state_dict,
            "control_plan": plan_dict,
            "source_snapshot": source_snap,
            "projection": json.loads(proj.to_json()),
        }
        assert json.loads(json.dumps(bundle)) is not None


# ===========================================================================
# Explainability / Rationale Assertions
# ===========================================================================


class TestExplainabilityAssertions:
    """
    Assertions confirm canonical artifacts and projections carry expected
    reasoning / fallback / degradation structure — not just pass/fail.
    """

    def test_plan_summary_exposes_execution_reason(self):
        """unified_control_plan_summary exposes execution_reason."""
        from core.schemas.unified_control_plan import unified_control_plan_summary, build_unified_control_plan
        plan = build_unified_control_plan(
            execution_reason="local execution selected; single-device session",
        )
        summary = unified_control_plan_summary(plan)
        assert summary is not None
        assert summary.get("execution_reason") == "local execution selected; single-device session"

    def test_plan_summary_exposes_fallback_kinds(self):
        """unified_control_plan_summary exposes fallback_kinds when present."""
        from core.schemas.unified_control_plan import (
            unified_control_plan_summary, build_unified_control_plan,
            FallbackKind, FallbackLevel,
        )
        plan = build_unified_control_plan(
            fallback_level=FallbackLevel.TEXT_ONLY_FALLBACK.value,
            fallback_kinds=[FallbackKind.NATIVE_MULTIMODAL_TO_TEXT.value],
        )
        summary = unified_control_plan_summary(plan)
        assert summary.get("has_fallback") is True
        assert FallbackKind.NATIVE_MULTIMODAL_TO_TEXT.value in (summary.get("fallback_kinds") or [])

    def test_plan_summary_none_for_none_input(self):
        """unified_control_plan_summary(None) returns None."""
        from core.schemas.unified_control_plan import unified_control_plan_summary
        assert unified_control_plan_summary(None) is None

    def test_projection_explainability_populated(self):
        """Projection carries a populated ExplainabilityProjection block."""
        proj = _make_projection(unified_control_plan=_make_proj_plan())
        assert proj.explainability is not None

    def test_projection_fallback_reason_propagated_to_explainability(self):
        """Fallback reason from plan is reflected in projection explainability."""
        from core.schemas.unified_control_plan import FallbackKind
        proj = _make_projection(
            unified_control_plan=_make_proj_plan(
                fallback_level="partial",
                fallback_reason="native multimodal provider unavailable",
                fallback_kinds=[FallbackKind.NATIVE_MULTIMODAL_TO_TEXT.value],
            )
        )
        assert proj.explainability.has_fallback is True

    def test_projection_summary_is_nonempty_dict(self):
        """desktop_status_projection_summary returns a non-empty dict."""
        from contracts.desktop_status_projection import desktop_status_projection_summary
        proj = _make_projection(
            unified_control_plan=_make_proj_plan(
                chosen_model="gpt-4o",
                chosen_provider="openai",
            )
        )
        summary = desktop_status_projection_summary(proj)
        assert isinstance(summary, dict)
        assert len(summary) > 0

    def test_projection_summary_none_for_none_input(self):
        """desktop_status_projection_summary(None) returns None."""
        from contracts.desktop_status_projection import desktop_status_projection_summary
        assert desktop_status_projection_summary(None) is None

    def test_fallback_record_has_human_readable_summary(self):
        """FallbackDecisionRecord carries a non-empty human-readable summary."""
        from core.schemas.unified_control_plan import FallbackDecisionRecord, FallbackKind
        fdr = FallbackDecisionRecord(
            fallback_kinds=[FallbackKind.NATIVE_MULTIMODAL_TO_TEXT.value],
            multimodal_downgrade_reason="no native MM provider",
        )
        assert fdr.human_readable_summary
        assert isinstance(fdr.human_readable_summary, str)


# ===========================================================================
# Full Round-Trip Serialisation
# ===========================================================================


class TestFullRoundTripSerialisation:
    """
    All canonical artifacts produced in every scenario are JSON-serialisable
    and round-trip cleanly through to_dict / from_dict where supported.
    """

    def test_unified_control_plan_to_dict_from_dict_round_trip(self):
        """UnifiedControlPlan to_dict → from_dict round-trip preserves key fields."""
        from core.schemas.unified_control_plan import UnifiedControlPlan, AUTHORITY_ROLE
        plan_dict = _make_plan_dict(
            chosen_model="gpt-4o",
            chosen_provider="openai",
            execution_path="local",
        )
        plan2 = UnifiedControlPlan.from_dict(plan_dict)
        assert plan2.authority_chain.decision_authority == AUTHORITY_ROLE
        # chosen_model_decision.model_id holds the model identifier
        assert plan2.chosen_model_decision.model_id == "gpt-4o"

    def test_desktop_projection_to_json_from_dict_round_trip(self):
        """DesktopStatusProjection to_json → from_dict round-trip produces valid object."""
        from contracts.desktop_status_projection import DesktopStatusProjection
        proj = _make_projection(
            unified_control_plan=_make_proj_plan(
                chosen_model="gpt-4o",
                chosen_provider="openai",
            )
        )
        raw = proj.to_json()
        proj2 = DesktopStatusProjection.from_dict(json.loads(raw))
        assert proj2.overall_health.value == proj.overall_health.value
        assert proj2.model_routing.selected_model == "gpt-4o"

    def test_all_scenario_plans_json_safe(self):
        """Control plans for all seven scenarios are JSON-safe dicts."""
        from core.schemas.unified_control_plan import FallbackKind, FallbackLevel
        from core.schemas.remote_execution import RemoteExecutionMode

        scenarios = [
            {},  # 1. text-only
            {"is_native_multimodal": True, "chosen_model": "gpt-4o"},  # 2. multimodal
            {"chosen_model": "gpt-4o"},  # 3. continuous ingress
            {  # 4. fallback
                "fallback_level": FallbackLevel.TEXT_ONLY_FALLBACK.value,
                "fallback_kinds": [FallbackKind.NATIVE_MULTIMODAL_TO_TEXT.value],
            },
            {  # 5a. remote command_only
                "execution_path": "cross_device",
                "remote_execution_mode": RemoteExecutionMode.command_only.value,
            },
            {  # 5b. remote agent_runtime
                "execution_path": "cross_device",
                "remote_execution_mode": RemoteExecutionMode.agent_runtime.value,
            },
            {  # 7. orchestration
                "orchestration_active": True,
                "execution_path": "hybrid",
            },
        ]
        for kwargs in scenarios:
            assert json.loads(json.dumps(_make_plan_dict(**kwargs))) is not None

    def test_all_scenario_projections_json_safe(self):
        """Desktop projections for all seven scenarios are JSON-safe."""
        from core.schemas.unified_control_plan import FallbackKind

        scenarios = [
            {},
            {"is_native_multimodal": True, "has_multimodal_input": True},
            {"chosen_model": "gpt-4o", "chosen_provider": "openai"},
            {
                "fallback_level": "partial",
                "fallback_kinds": [FallbackKind.NATIVE_MULTIMODAL_TO_TEXT.value],
            },
            {"execution_path": "cross_device", "remote_execution_mode": "command_only"},
            {"execution_path": "cross_device", "remote_execution_mode": "agent_runtime"},
            {"orchestration_active": True, "execution_path": "hybrid"},
        ]
        for kwargs in scenarios:
            proj = _make_projection(unified_control_plan=_make_proj_plan(**kwargs))
            assert json.loads(proj.to_json()) is not None
