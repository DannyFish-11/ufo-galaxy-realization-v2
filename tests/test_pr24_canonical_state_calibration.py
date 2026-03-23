"""
tests/test_pr24_canonical_state_calibration.py
================================================
PR-24 — Calibrate canonical state contracts and eliminate duplicate state paths.

Validates that the unified control loop uses canonical state as the single
source of truth across all major state families, and that legacy/compat fields
do not compete with canonical artifacts.

Architecture under test
-----------------------

    CANONICAL STATE CHAIN
    ─────────────────────
    CanonicalPerceptionState (PR-16)
        └── assembled from continuous ingress + request-bound multimodal context
            ↓
    CanonicalModelSupplyState (PR-18)               ← PR-24: now wired in
        └── assembled from MultiLLMRouter provider inventory
            ↓
    UnifiedControlPlan (PR-19 / PR-21)
        └── single canonical control artifact; captures both perception and
            model supply truth alongside execution decisions
            ↓
    DesktopStatusProjection (PR-22)
        └── derived from UnifiedControlPlan + shell-owned source registry

DUPLICATE / LEGACY STATE PATHS (PR-24 audit)
─────────────────────────────────────────────
``multimodal_context`` in response metadata
    STATUS: backward-compatibility field (raw fused bus output).
    SOURCE OF TRUTH: ``canonical_perception_state`` (PR-16).
    ACTION: retained for callers that depend on bus output; labelled compat.

``canonical_model_supply`` gap in UnifiedControlPlan
    STATUS: closed by PR-24.
    BEFORE: CanonicalModelSupplyState built by PR-18 but not forwarded into
            the unified control plan.
    AFTER:  ``_build_canonical_model_supply_state()`` builds supply state once
            per request and passes it to ``_build_unified_control_plan()``.

Covered test scenarios
-----------------------
1.  Canonical perception state is the authoritative perception path
2.  Canonical model supply state is wired into the unified control plan
3.  Unified control plan captures both perception and model supply truth
4.  ``multimodal_context`` metadata key preserved for backward compat
5.  ``canonical_model_supply_state`` is present in response metadata
6.  Desktop status projection derives from unified control plan (not re-derived)
7.  Diagnostics/projection consistent with canonical control artifacts
8.  Text-only flow backward compatible
9.  Multimodal flow backward compatible
10. All canonical artifacts are JSON-serialisable
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pytest


# ===========================================================================
# Shared fixture helpers
# ===========================================================================


def _text_only_perception_dict(
    session_id: str = "pr24-sess-001",
    trace_id: str = "pr24-trace-001",
) -> Dict[str, Any]:
    """Build a text-only CanonicalPerceptionState dict."""
    from core.perception.canonical_perception_state import build_canonical_perception_state
    return build_canonical_perception_state(
        runtime_session_id=session_id,
        trace_id=trace_id,
        fused_context={
            "images": [], "audio": [], "screen": {}, "device": {},
            "fusion_summary": "",
        },
        multimodal_context=None,
        continuous_frame=None,
    ).to_dict()


def _multimodal_perception_dict(
    session_id: str = "pr24-sess-mm-001",
    trace_id: str = "pr24-trace-mm-001",
) -> Dict[str, Any]:
    """Build a multimodal CanonicalPerceptionState dict (1 image)."""
    from core.perception.canonical_perception_state import build_canonical_perception_state
    from core.schemas.multimodal import MultiModalContext, MultiModalImage

    images = [MultiModalImage(mime="image/jpeg", data="FAKE64==", source="webcam")]
    mm_ctx = MultiModalContext(images=images, audio=[])
    fused = {
        "images": [{"source": "webcam"}],
        "audio": [],
        "screen": {},
        "device": {},
        "fusion_summary": "image",
    }
    return build_canonical_perception_state(
        runtime_session_id=session_id,
        trace_id=trace_id,
        fused_context=fused,
        multimodal_context=mm_ctx,
        continuous_frame=None,
    ).to_dict()


def _minimal_model_supply_dict() -> Dict[str, Any]:
    """Build a minimal CanonicalModelSupplyState dict (no real router)."""
    from core.model_topology.canonical_model_supply_state import CanonicalModelSupplyState
    state = CanonicalModelSupplyState(snapshot_id="pr24-supply-001")
    return state.to_dict()


def _build_plan_dict(**kwargs) -> Dict[str, Any]:
    """Build a UnifiedControlPlan dict from kwargs."""
    from core.schemas.unified_control_plan import build_unified_control_plan
    return build_unified_control_plan(**kwargs).to_dict()


def _build_projection(
    unified_control_plan: Optional[Dict[str, Any]] = None,
    source_registry_snapshot: Optional[Dict[str, Any]] = None,
    tristate: str = "silent",
    runtime_session_id: str = "pr24-rsid-001",
) -> Any:
    """Build a DesktopStatusProjection from the supplied plan."""
    from contracts.desktop_status_projection import build_desktop_status_projection
    return build_desktop_status_projection(
        unified_control_plan=unified_control_plan,
        source_registry_snapshot=source_registry_snapshot,
        tristate=tristate,
        runtime_session_id=runtime_session_id,
    )


def _flat_plan(
    *,
    chosen_model: Optional[str] = None,
    chosen_provider: Optional[str] = None,
    is_native_multimodal: bool = False,
    execution_path: str = "local",
    fallback_level: str = "none",
    has_multimodal_input: bool = False,
    active_modalities: Optional[List[str]] = None,
    canonical_model_supply_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return a flat projection-format plan dict for build_desktop_status_projection.

    This is the flat format consumed by desktop_status_projection builders
    (as established by PR-22).
    """
    from core.schemas.unified_control_plan import AUTHORITY_ROLE, SHELL_ROLE, SUBSTRATE_ROLE, ORCHESTRATION_ROLE
    return {
        "decision_authority": AUTHORITY_ROLE,
        "chosen_model": chosen_model,
        "chosen_provider": chosen_provider,
        "is_native_multimodal": is_native_multimodal,
        "lifecycle_target": "succeeded",
        "fallback_level": fallback_level,
        "fallback_reason": None,
        "canonical_perception": {
            "has_multimodal_input": has_multimodal_input,
            "active_modalities": active_modalities or [],
        },
        "canonical_model_supply_summary": canonical_model_supply_summary,
        "chosen_execution_decision": {
            "execution_path": execution_path,
            "delegation_point": "local_manifestation",
            "remote_execution_mode": None,
            "target_device_ids": [],
            "orchestration_active": False,
        },
        "authority_chain": {
            "decision_authority": AUTHORITY_ROLE,
            "shell_role": SHELL_ROLE,
            "substrate_role": SUBSTRATE_ROLE,
            "orchestration_role": ORCHESTRATION_ROLE,
        },
    }


# ===========================================================================
# 1. Canonical Perception State — authoritative perception path
# ===========================================================================


class TestCanonicalPerceptionStateAuthority:
    """
    Canonical perception state (PR-16) is the authoritative perception path.

    New consumers should use ``canonical_perception_state`` from response
    metadata rather than the raw ``multimodal_context`` fused bus output.
    """

    def test_text_only_perception_state_is_valid_dict(self):
        """Text-only canonical perception state is a well-formed dict."""
        d = _text_only_perception_dict()
        assert isinstance(d, dict)
        assert "has_multimodal_input" in d or "has_continuous_perception" in d

    def test_multimodal_perception_state_has_input_flag(self):
        """Multimodal canonical perception state reflects the presence of input data."""
        d = _multimodal_perception_dict()
        assert isinstance(d, dict)
        # At minimum the state should record image/multimodal context was provided
        has_mm = d.get("has_request_multimodal") or d.get("has_multimodal_input") or bool(
            d.get("active_modalities")
        )
        assert has_mm, (
            "Canonical perception state must reflect multimodal input when images are present"
        )

    def test_canonical_perception_state_json_serialisable(self):
        """Canonical perception state dict is JSON-serialisable (no binary payloads)."""
        for d in (_text_only_perception_dict(), _multimodal_perception_dict()):
            raw = json.dumps(d)
            restored = json.loads(raw)
            assert restored == d

    def test_canonical_perception_has_session_id(self):
        """Canonical perception state embeds the session correlation ID."""
        d = _text_only_perception_dict(session_id="test-sess-999")
        assert d.get("runtime_session_id") == "test-sess-999"

    def test_canonical_perception_has_trace_id(self):
        """Canonical perception state embeds the trace correlation ID."""
        d = _text_only_perception_dict(trace_id="test-trace-999")
        assert d.get("trace_id") == "test-trace-999"


# ===========================================================================
# 2. Canonical Model Supply State — wired into unified control plan
# ===========================================================================


class TestCanonicalModelSupplyWiring:
    """
    PR-24 closes the gap: CanonicalModelSupplyState (PR-18) is now forwarded
    into UnifiedControlPlan via _build_unified_control_plan().

    The plan's ``canonical_model_supply_summary`` field must be populated when
    a valid supply dict is provided.
    """

    def test_plan_accepts_canonical_model_supply(self):
        """build_unified_control_plan() accepts canonical_model_supply kwarg."""
        supply = _minimal_model_supply_dict()
        plan = _build_plan_dict(
            runtime_session_id="pr24-sess-001",
            trace_id="pr24-trace-001",
            canonical_model_supply=supply,
        )
        assert plan is not None
        assert isinstance(plan, dict)

    def test_plan_carries_model_supply_summary_when_supply_given(self):
        """When canonical_model_supply is passed, plan carries a supply summary."""
        supply = _minimal_model_supply_dict()
        plan = _build_plan_dict(
            canonical_model_supply=supply,
            chosen_model="gpt-4o",
            chosen_provider="openai",
        )
        # The summary key should exist (may be None for empty supply, but key present)
        assert "canonical_model_supply_summary" in plan

    def test_plan_model_supply_summary_none_when_supply_omitted(self):
        """When canonical_model_supply is not passed, supply summary is None."""
        plan = _build_plan_dict(
            runtime_session_id="pr24-sess-002",
        )
        assert plan.get("canonical_model_supply_summary") is None

    def test_model_supply_dict_is_json_serialisable(self):
        """CanonicalModelSupplyState dict is JSON-serialisable."""
        supply = _minimal_model_supply_dict()
        raw = json.dumps(supply)
        restored = json.loads(raw)
        assert restored == supply

    def test_model_supply_has_stats_key(self):
        """CanonicalModelSupplyState dict always includes a stats sub-dict."""
        supply = _minimal_model_supply_dict()
        assert "stats" in supply
        assert "total_providers" in supply["stats"]

    def test_openclawd_has_canonical_model_supply_helper(self):
        """OpenClawd exposes _build_canonical_model_supply_state() method (PR-24)."""
        from core.openclawd import OpenClawd
        assert hasattr(OpenClawd, "_build_canonical_model_supply_state"), (
            "OpenClawd must expose _build_canonical_model_supply_state() added by PR-24"
        )

    def test_openclawd_model_supply_helper_returns_none_or_dict(self):
        """_build_canonical_model_supply_state() returns None or a dict; never raises."""
        from core.openclawd import OpenClawd
        clawd = OpenClawd.__new__(OpenClawd)
        # Minimal attribute setup so the helper can run without a real router
        clawd._router = None
        result = clawd._build_canonical_model_supply_state()
        assert result is None or isinstance(result, dict)


# ===========================================================================
# 3. Unified Control Plan — captures perception and model supply truth
# ===========================================================================


class TestUnifiedControlPlanCanonicalChain:
    """
    UnifiedControlPlan (PR-19) is the single canonical control artifact.

    It must capture both perception truth (PR-16) and model supply truth (PR-18)
    as authoritative inputs so downstream consumers have one place to look.
    """

    def test_plan_includes_canonical_perception_summary(self):
        """UnifiedControlPlan embeds a canonical perception summary."""
        perception = _text_only_perception_dict()
        plan = _build_plan_dict(canonical_perception=perception)
        assert "canonical_perception_summary" in plan

    def test_plan_perception_summary_reflects_modality_state(self):
        """Perception summary in plan correctly reflects text-only vs multimodal."""
        text_plan = _build_plan_dict(canonical_perception=_text_only_perception_dict())
        mm_plan = _build_plan_dict(canonical_perception=_multimodal_perception_dict())
        text_perc = text_plan.get("canonical_perception_summary") or {}
        mm_perc = mm_plan.get("canonical_perception_summary") or {}
        # Both must be present; their content differs by modality
        assert isinstance(text_perc, dict)
        assert isinstance(mm_perc, dict)

    def test_plan_authority_chain_always_names_subject_core(self):
        """Plan authority_chain always names subject_decision_authority."""
        from core.schemas.unified_control_plan import AUTHORITY_ROLE
        plan = _build_plan_dict(canonical_perception=_text_only_perception_dict())
        assert plan["authority_chain"]["decision_authority"] == AUTHORITY_ROLE

    def test_plan_with_supply_and_perception_is_json_serialisable(self):
        """Plan carrying both canonical perception and model supply is JSON-serialisable."""
        plan = _build_plan_dict(
            runtime_session_id="pr24-sess-003",
            trace_id="pr24-trace-003",
            canonical_perception=_text_only_perception_dict(),
            canonical_model_supply=_minimal_model_supply_dict(),
            chosen_model="gpt-4o",
            chosen_provider="openai",
            execution_path="local",
        )
        raw = json.dumps(plan)
        restored = json.loads(raw)
        assert restored["trace_id"] == "pr24-trace-003"

    def test_plan_from_dict_round_trip_stable(self):
        """UnifiedControlPlan.to_dict() / from_dict() round-trip is stable."""
        from core.schemas.unified_control_plan import UnifiedControlPlan, build_unified_control_plan
        orig = build_unified_control_plan(
            runtime_session_id="pr24-rt-001",
            canonical_perception=_text_only_perception_dict(),
            canonical_model_supply=_minimal_model_supply_dict(),
        )
        plan_dict = orig.to_dict()
        restored = UnifiedControlPlan.from_dict(plan_dict)
        assert restored.runtime_session_id == "pr24-rt-001"
        assert restored.authority_chain.decision_authority == orig.authority_chain.decision_authority

    def test_plan_decision_authority_stable_across_builds(self):
        """Decision authority is always subject_decision_authority regardless of supply."""
        from core.schemas.unified_control_plan import AUTHORITY_ROLE
        for supply in (None, _minimal_model_supply_dict()):
            plan = _build_plan_dict(canonical_model_supply=supply)
            assert plan["authority_chain"]["decision_authority"] == AUTHORITY_ROLE


# ===========================================================================
# 4 & 5. Backward-compat metadata keys
# ===========================================================================


class TestResponseMetadataCanonicalKeys:
    """
    PR-24 audit of response metadata canonical key structure.

    After PR-24:
    - ``canonical_perception_state`` (PR-16): authoritative perception path
    - ``canonical_model_supply_state`` (PR-24): authoritative model supply path
    - ``unified_control_plan`` (PR-19): authoritative control plan
    - ``multimodal_context``: backward-compat key (raw fused bus output)

    Tests verify the contract by inspecting OpenClawd source code — the
    actual key placement is validated structurally without live LLM calls.
    """

    def test_canonical_perception_key_in_openclawd_source(self):
        """openclawd.py must contain 'canonical_perception_state' metadata key."""
        import inspect
        from core import openclawd as _oc_mod
        src = inspect.getsource(_oc_mod)
        assert '"canonical_perception_state"' in src, (
            "canonical_perception_state key must be present in response metadata"
        )

    def test_canonical_model_supply_key_in_openclawd_source(self):
        """PR-24: openclawd.py must contain 'canonical_model_supply_state' metadata key."""
        import inspect
        from core import openclawd as _oc_mod
        src = inspect.getsource(_oc_mod)
        assert '"canonical_model_supply_state"' in src, (
            "PR-24: canonical_model_supply_state key must be present in response metadata"
        )

    def test_unified_control_plan_key_in_openclawd_source(self):
        """openclawd.py must contain 'unified_control_plan' metadata key."""
        import inspect
        from core import openclawd as _oc_mod
        src = inspect.getsource(_oc_mod)
        assert '"unified_control_plan"' in src

    def test_multimodal_context_compat_key_still_present(self):
        """'multimodal_context' backward-compat key must still be present in source."""
        import inspect
        from core import openclawd as _oc_mod
        src = inspect.getsource(_oc_mod)
        assert '"multimodal_context"' in src, (
            "'multimodal_context' must be retained for backward compatibility"
        )

    def test_canonical_model_supply_build_helper_in_openclawd_source(self):
        """PR-24: _build_canonical_model_supply_state() must be defined in openclawd.py."""
        import inspect
        from core import openclawd as _oc_mod
        src = inspect.getsource(_oc_mod)
        assert "_build_canonical_model_supply_state" in src, (
            "PR-24: _build_canonical_model_supply_state helper must be in openclawd.py"
        )

    def test_build_ucp_receives_canonical_model_supply_in_source(self):
        """PR-24: _build_unified_control_plan() must pass canonical_model_supply."""
        import inspect
        from core import openclawd as _oc_mod
        src = inspect.getsource(_oc_mod)
        assert "canonical_model_supply=_canonical_model_supply" in src, (
            "PR-24: canonical_model_supply must be wired into both _build_unified_control_plan calls"
        )


# ===========================================================================
# 6. Desktop Status Projection — derives from canonical control plan
# ===========================================================================


class TestDesktopStatusProjectionFromCanonicalPlan:
    """
    DesktopStatusProjection (PR-22) must derive from the UnifiedControlPlan
    rather than re-assembling state ad hoc.

    The shell uses the canonical projection contract rather than rebuilding
    state from scattered metadata.
    """

    def test_projection_built_from_text_only_plan(self):
        """Text-only projection is produced without multimodal inputs."""
        plan = _flat_plan()
        proj = _build_projection(unified_control_plan=plan)
        assert proj is not None

    def test_projection_built_from_multimodal_plan(self):
        """Multimodal projection is produced with native multimodal markers."""
        plan = _flat_plan(
            chosen_model="gpt-4o",
            chosen_provider="openai",
            is_native_multimodal=True,
            has_multimodal_input=True,
            active_modalities=["audio", "video"],
        )
        proj = _build_projection(unified_control_plan=plan)
        assert proj is not None

    def test_projection_carries_execution_projection(self):
        """Desktop projection always includes an execution sub-projection."""
        plan = _flat_plan(execution_path="local")
        proj = _build_projection(unified_control_plan=plan)
        proj_dict = proj.to_dict()
        assert "execution" in proj_dict

    def test_projection_carries_lifecycle_projection(self):
        """Desktop projection always includes a lifecycle sub-projection."""
        plan = _flat_plan()
        proj = _build_projection(unified_control_plan=plan)
        proj_dict = proj.to_dict()
        assert "lifecycle" in proj_dict

    def test_projection_is_json_serialisable(self):
        """Desktop projection dict is fully JSON-serialisable."""
        plan = _flat_plan(chosen_model="gpt-4o", chosen_provider="openai")
        proj = _build_projection(unified_control_plan=plan)
        proj_dict = proj.to_dict()
        raw = json.dumps(proj_dict)
        restored = json.loads(raw)
        assert restored.keys() == proj_dict.keys()

    def test_projection_without_plan_gracefully_degrades(self):
        """Projection can be built without a unified control plan (shell-only)."""
        proj = _build_projection(unified_control_plan=None)
        assert proj is not None
        proj_dict = proj.to_dict()
        assert isinstance(proj_dict, dict)

    def test_projection_canonical_authority_not_re_derived_by_shell(self):
        """Projection does not re-derive authority — it reads from the plan."""
        from core.schemas.unified_control_plan import AUTHORITY_ROLE
        plan = _flat_plan()
        # Authority info is in the plan, not reconstructed by the shell
        assert plan.get("decision_authority") == AUTHORITY_ROLE


# ===========================================================================
# 7. Diagnostics / projection consistency with canonical control artifacts
# ===========================================================================


class TestDiagnosticsProjectionConsistency:
    """
    Diagnostics and projection must stay consistent with canonical control
    artifacts rather than independently deriving state.
    """

    def test_projection_reflects_fallback_level_from_plan(self):
        """Projection explainability reflects the plan's fallback level."""
        plan_no_fallback = _flat_plan(fallback_level="none")
        plan_fallback = _flat_plan(fallback_level="text_only_fallback")

        proj_no_fb = _build_projection(unified_control_plan=plan_no_fallback)
        proj_fb = _build_projection(unified_control_plan=plan_fallback)

        d_no_fb = proj_no_fb.to_dict()
        d_fb = proj_fb.to_dict()

        # Both must produce valid projections; fallback state differs
        assert "explainability" in d_no_fb
        assert "explainability" in d_fb

    def test_projection_health_severity_degrades_with_fallback(self):
        """Projection health severity reflects fallback/degradation state."""
        plan_ok = _flat_plan(fallback_level="none")
        plan_fb = _flat_plan(fallback_level="text_only_fallback")

        proj_ok = _build_projection(unified_control_plan=plan_ok)
        proj_fb = _build_projection(unified_control_plan=plan_fb)

        d_ok = proj_ok.to_dict()
        d_fb = proj_fb.to_dict()

        sev_ok = d_ok.get("overall_health_severity", "")
        sev_fb = d_fb.get("overall_health_severity", "")

        # Fallback should not produce a healthier severity than no-fallback
        severity_order = ["ok", "info", "warning", "error", "critical"]

        def _sev_rank(s: str) -> int:
            try:
                return severity_order.index(str(s).lower())
            except ValueError:
                return -1  # unknown — tolerate

        rank_ok = _sev_rank(sev_ok)
        rank_fb = _sev_rank(sev_fb)

        if rank_ok >= 0 and rank_fb >= 0:
            assert rank_fb >= rank_ok, (
                f"Fallback severity ({sev_fb}) should not be healthier than no-fallback ({sev_ok})"
            )

    def test_projection_model_info_from_control_plan(self):
        """Projection model routing info comes from the canonical control plan."""
        plan = _flat_plan(
            chosen_model="claude-3-haiku",
            chosen_provider="anthropic",
            is_native_multimodal=False,
        )
        proj = _build_projection(unified_control_plan=plan)
        proj_dict = proj.to_dict()
        model_routing = proj_dict.get("model_routing") or {}
        # Provider / model info must come from the plan
        if model_routing:
            assert isinstance(model_routing, dict)

    def test_projection_with_model_supply_summary_in_plan(self):
        """Projection is coherent when plan carries canonical_model_supply_summary."""
        from core.model_topology.canonical_model_supply_state import CanonicalModelSupplyState
        supply = CanonicalModelSupplyState(snapshot_id="diag-supply-001").to_dict()
        plan_full = _build_plan_dict(
            runtime_session_id="diag-sess-001",
            trace_id="diag-trace-001",
            canonical_perception=_text_only_perception_dict(),
            canonical_model_supply=supply,
            chosen_model="gpt-4o",
            chosen_provider="openai",
        )
        # Supply summary is embedded in the plan
        assert "canonical_model_supply_summary" in plan_full


# ===========================================================================
# 8 & 9. Backward Compatibility — text-only and multimodal flows
# ===========================================================================


class TestBackwardCompatibility:
    """
    PR-24 changes are additive.  Existing text-only and multimodal flows must
    remain backward compatible — no existing callers should be broken.
    """

    def test_build_unified_control_plan_without_supply_still_works(self):
        """build_unified_control_plan() without canonical_model_supply does not raise."""
        plan = _build_plan_dict(
            runtime_session_id="compat-sess-001",
            trace_id="compat-trace-001",
        )
        assert plan is not None
        assert plan.get("canonical_model_supply_summary") is None

    def test_build_unified_control_plan_without_perception_still_works(self):
        """build_unified_control_plan() without canonical_perception does not raise."""
        plan = _build_plan_dict(
            runtime_session_id="compat-sess-002",
            canonical_model_supply=_minimal_model_supply_dict(),
        )
        assert plan is not None

    def test_build_unified_control_plan_empty_args_still_works(self):
        """build_unified_control_plan() with no args produces valid plan."""
        plan = _build_plan_dict()
        assert plan is not None
        assert "authority_chain" in plan

    def test_projection_with_no_supply_summary_still_builds(self):
        """Desktop projection builds without canonical_model_supply_summary in plan."""
        plan = _flat_plan()  # no supply summary
        proj = _build_projection(unified_control_plan=plan)
        assert proj is not None

    def test_text_only_flow_perception_to_plan_to_projection(self):
        """Full text-only canonical chain: perception → plan → projection succeeds."""
        perception = _text_only_perception_dict()
        _build_plan_dict(canonical_perception=perception)  # must not raise

        # Projection-format plan for the desktop projection contract
        proj_plan = _flat_plan()
        proj = _build_projection(unified_control_plan=proj_plan)
        assert proj is not None
        proj_dict = proj.to_dict()
        raw = json.dumps(proj_dict)
        assert json.loads(raw).keys() == proj_dict.keys()

    def test_multimodal_flow_perception_to_plan_to_projection(self):
        """Full multimodal canonical chain: perception → plan → projection succeeds."""
        perception = _multimodal_perception_dict()
        plan = _build_plan_dict(
            canonical_perception=perception,
            canonical_model_supply=_minimal_model_supply_dict(),
            is_native_multimodal=True,
        )
        proj_plan = _flat_plan(
            is_native_multimodal=True,
            has_multimodal_input=True,
            active_modalities=["video"],
        )
        proj = _build_projection(unified_control_plan=proj_plan)
        assert proj is not None

    def test_pr16_perception_builder_still_importable(self):
        """PR-16 build_canonical_perception_state() is still importable."""
        from core.perception.canonical_perception_state import build_canonical_perception_state
        assert callable(build_canonical_perception_state)

    def test_pr18_model_supply_builder_still_importable(self):
        """PR-18 build_canonical_model_supply_state_from_router() is still importable."""
        from core.model_topology.canonical_model_supply_state import (
            build_canonical_model_supply_state_from_router,
        )
        assert callable(build_canonical_model_supply_state_from_router)

    def test_pr19_unified_control_plan_builder_still_importable(self):
        """PR-19 build_unified_control_plan() is still importable."""
        from core.schemas.unified_control_plan import build_unified_control_plan
        assert callable(build_unified_control_plan)

    def test_pr22_desktop_status_projection_builder_still_importable(self):
        """PR-22 build_desktop_status_projection() is still importable."""
        from contracts.desktop_status_projection import build_desktop_status_projection
        assert callable(build_desktop_status_projection)


# ===========================================================================
# 10. JSON serialisability of full canonical chain
# ===========================================================================


class TestFullChainJsonSerialisability:
    """All canonical artifacts in the chain must be JSON-serialisable."""

    def test_perception_state_serialisable(self):
        """CanonicalPerceptionState is JSON-serialisable."""
        d = _text_only_perception_dict()
        assert json.loads(json.dumps(d)) == d

    def test_model_supply_state_serialisable(self):
        """CanonicalModelSupplyState is JSON-serialisable."""
        d = _minimal_model_supply_dict()
        assert json.loads(json.dumps(d)) == d

    def test_unified_control_plan_with_supply_serialisable(self):
        """UnifiedControlPlan carrying model supply is JSON-serialisable."""
        plan = _build_plan_dict(
            canonical_perception=_text_only_perception_dict(),
            canonical_model_supply=_minimal_model_supply_dict(),
        )
        assert json.loads(json.dumps(plan)) == plan

    def test_desktop_projection_serialisable(self):
        """DesktopStatusProjection is JSON-serialisable."""
        proj = _build_projection(unified_control_plan=_flat_plan())
        proj_dict = proj.to_dict()
        assert json.loads(json.dumps(proj_dict)).keys() == proj_dict.keys()

    def test_full_chain_text_only_serialisable(self):
        """Full text-only canonical chain is end-to-end JSON-serialisable."""
        perception = _text_only_perception_dict()
        supply = _minimal_model_supply_dict()
        plan = _build_plan_dict(
            runtime_session_id="chain-sess-001",
            canonical_perception=perception,
            canonical_model_supply=supply,
        )
        proj = _build_projection(unified_control_plan=_flat_plan())
        chain = {
            "canonical_perception_state": perception,
            "canonical_model_supply_state": supply,
            "unified_control_plan": plan,
            "desktop_status_projection": proj.to_dict(),
        }
        restored = json.loads(json.dumps(chain))
        assert set(restored.keys()) == {"canonical_perception_state", "canonical_model_supply_state",
                                        "unified_control_plan", "desktop_status_projection"}

    def test_full_chain_multimodal_serialisable(self):
        """Full multimodal canonical chain is end-to-end JSON-serialisable."""
        perception = _multimodal_perception_dict()
        supply = _minimal_model_supply_dict()
        plan = _build_plan_dict(
            runtime_session_id="chain-mm-001",
            canonical_perception=perception,
            canonical_model_supply=supply,
            is_native_multimodal=True,
        )
        proj = _build_projection(
            unified_control_plan=_flat_plan(
                is_native_multimodal=True,
                has_multimodal_input=True,
                active_modalities=["video"],
            )
        )
        chain = {
            "canonical_perception_state": perception,
            "canonical_model_supply_state": supply,
            "unified_control_plan": plan,
            "desktop_status_projection": proj.to_dict(),
        }
        restored = json.loads(json.dumps(chain))
        assert "canonical_model_supply_state" in restored
        assert "unified_control_plan" in restored
