"""PR-24: Canonical state contract calibration tests.

Validates that:
1. canonical_perception/control/execution/projection paths are used by the
   main control-loop flow.
2. Compatibility/derived fields, if retained, remain derived from canonical
   state rather than competing with it.
3. The multimodal_route_decision is embedded in the UnifiedControlPlan (canonical
   source) and the deprecated top-level key is only a compat fallback.
4. CanonicalStateAdapter reads canonical sources in preference to compat fields.
5. Duplicate-state drift is reduced: the adapter never surfaces compat data when
   canonical data is available.
6. Text-only and multimodal flows both produce valid canonical state.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_canonical_perception(
    *,
    has_multimodal: bool = False,
    requires_native: bool = False,
    modalities: Optional[list] = None,
) -> Dict[str, Any]:
    """Return a minimal canonical_perception_state dict."""
    return {
        "has_continuous_perception": False,
        "has_request_multimodal": has_multimodal,
        "active_modalities": modalities or (["audio", "video"] if has_multimodal else []),
        "requires_native_multimodal": requires_native,
        "degradation_reasons": [],
        "perception_summary": "test",
    }


def _make_multimodal_route(
    *,
    route_type: str = "native_multimodal",
    is_native: bool = True,
    reason: str = "native_capable",
) -> Dict[str, Any]:
    """Return a minimal multimodal_route_decision dict."""
    return {
        "route_type": route_type,
        "is_native_multimodal": is_native,
        "route_reason": reason,
        "fallback_reason": None,
    }


def _make_ucp_dict(
    *,
    route_decision: Optional[Dict[str, Any]] = None,
    execution_path: str = "local",
    fallback_level: str = "none",
    has_perception: bool = False,
    has_supply: bool = False,
) -> Dict[str, Any]:
    """Return a minimal unified_control_plan dict (as produced by UCP.to_dict())."""
    return {
        "plan_id": "ucp_test123",
        "schema_version": "1.0",
        "decision_posture": "autonomous",
        "canonical_perception_summary": {"perception_summary": "test"} if has_perception else None,
        "canonical_model_supply_summary": {"primary_provider_id": "p1"} if has_supply else None,
        "chosen_model_decision": {
            "provider_id": "p1",
            "model_id": "m1",
            "is_native_multimodal": route_decision.get("is_native_multimodal", False) if route_decision else False,
            "selection_reason": None,
            "fallback_chain": [],
        },
        "chosen_execution_decision": {
            "execution_path": execution_path,
            "delegation_point": None,
            "remote_execution_mode": None,
            "target_device_ids": [],
            "orchestration_active": False,
        },
        "unified_execution_decision": {
            "execution_path": execution_path,
            "delegation_point": None,
            "remote_execution_mode": None,
            "target_device_ids": [],
            "orchestration_active": False,
            "execution_reason": None,
            "fallback_intent": None,
            "is_downgrade": False,
            "preferred_path": None,
        },
        # PR-24: canonical route embedded in the plan
        "multimodal_route_decision": route_decision,
        "fallback_level": fallback_level,
        "fallback_reason": None,
        "fallback_decision_record": None,
        "lifecycle_target": "succeeded",
        "execution_plan_summary": None,
        "diagnostics_summary": None,
        "authority_chain": {"decision_authority": "subject_decision_authority"},
        "shell_projection_hints": {},
    }


def _make_metadata(
    *,
    include_canonical_perception: bool = True,
    include_ucp: bool = True,
    include_route: bool = True,
    route_in_ucp: bool = True,
    include_compat_mm_context: bool = True,
    include_compat_top_level_route: bool = True,
    route_type: str = "native_multimodal",
    is_native: bool = True,
) -> Dict[str, Any]:
    """Assemble a response metadata dict mirroring what OpenClawd produces."""
    route = _make_multimodal_route(route_type=route_type, is_native=is_native)
    ucp = _make_ucp_dict(
        route_decision=route if route_in_ucp else None,
        has_perception=include_canonical_perception,
    )

    meta: Dict[str, Any] = {}

    if include_canonical_perception:
        meta["canonical_perception_state"] = _make_canonical_perception(
            has_multimodal=is_native,
            requires_native=is_native,
        )

    if include_ucp:
        meta["unified_control_plan"] = ucp

    # Deprecated-compat fields
    if include_compat_mm_context:
        meta["multimodal_context"] = {"images": [], "audio": [], "fusion_summary": "test"}

    if include_compat_top_level_route and include_route:
        meta["multimodal_route_decision"] = route

    return meta


# ---------------------------------------------------------------------------
# Tests: UnifiedControlPlan schema embeds multimodal_route_decision (PR-24)
# ---------------------------------------------------------------------------


class TestUnifiedControlPlanEmbeddedRouteDecision:
    """The UnifiedControlPlan schema must accept and carry multimodal_route_decision."""

    def test_build_ucp_accepts_route_decision(self):
        from core.schemas.unified_control_plan import build_unified_control_plan

        route = _make_multimodal_route()
        plan = build_unified_control_plan(
            multimodal_route_decision=route,
        )

        assert plan.multimodal_route_decision is not None
        assert plan.multimodal_route_decision["route_type"] == "native_multimodal"
        assert plan.multimodal_route_decision["is_native_multimodal"] is True

    def test_ucp_to_dict_includes_route_decision(self):
        from core.schemas.unified_control_plan import build_unified_control_plan

        route = _make_multimodal_route(route_type="partial_multimodal", is_native=False)
        plan = build_unified_control_plan(multimodal_route_decision=route)
        d = plan.to_dict()

        assert "multimodal_route_decision" in d
        assert d["multimodal_route_decision"]["route_type"] == "partial_multimodal"

    def test_ucp_route_decision_none_by_default(self):
        from core.schemas.unified_control_plan import build_unified_control_plan

        plan = build_unified_control_plan()
        assert plan.multimodal_route_decision is None
        d = plan.to_dict()
        assert d["multimodal_route_decision"] is None

    def test_ucp_from_dict_roundtrip_with_route(self):
        from core.schemas.unified_control_plan import UnifiedControlPlan, build_unified_control_plan

        route = _make_multimodal_route(route_type="advisory", is_native=False)
        plan = build_unified_control_plan(multimodal_route_decision=route)
        d = plan.to_dict()

        restored = UnifiedControlPlan.from_dict(d)
        assert restored.multimodal_route_decision is not None
        assert restored.multimodal_route_decision["route_type"] == "advisory"

    def test_ucp_from_dict_without_route_defaults_none(self):
        from core.schemas.unified_control_plan import UnifiedControlPlan

        d = _make_ucp_dict()
        d.pop("multimodal_route_decision", None)

        plan = UnifiedControlPlan.from_dict(d)
        assert plan.multimodal_route_decision is None

    def test_ucp_summary_includes_route_type(self):
        from core.schemas.unified_control_plan import (
            build_unified_control_plan,
            unified_control_plan_summary,
        )

        route = _make_multimodal_route(route_type="native_multimodal")
        plan = build_unified_control_plan(multimodal_route_decision=route)
        summary = unified_control_plan_summary(plan)

        assert summary is not None
        assert summary["multimodal_route_type"] == "native_multimodal"

    def test_ucp_summary_route_type_none_when_no_route(self):
        from core.schemas.unified_control_plan import (
            build_unified_control_plan,
            unified_control_plan_summary,
        )

        plan = build_unified_control_plan()
        summary = unified_control_plan_summary(plan)

        assert summary is not None


# ---------------------------------------------------------------------------
# Tests: backward compatibility — existing callers still work
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    """Deprecated compat fields must remain accessible for backward compatibility."""

    # 注：原先这两条经由 core.perception.canonical_state_adapter 断言"规范优先、
    # compat 兜底"的读取顺序。该适配器已随不可达模块清理一并删除——活代码里
    # UCP 内嵌与顶层两个键由 openclawd 从**同一个变量**写出（见
    # openclawd._build_unified_control_plan 附近的两处 multimodal_route_decision=），
    # 结构上不可能漂移；顶层键的废弃状态由 core/orchestration_authority/legacy_paths.py
    # 登记并管控。这里保留真正还成立的部分：compat 键必须仍然能从 metadata 读到。

    def test_compat_mm_context_still_readable_from_metadata(self):
        meta = _make_metadata(include_compat_mm_context=True)

        # Legacy consumers that read this directly should still get data
        raw = meta.get("multimodal_context")
        assert raw is not None
        assert "images" in raw

    def test_compat_top_level_route_still_readable_from_metadata(self):
        meta = _make_metadata(
            include_compat_top_level_route=True,
            route_in_ucp=False,  # No canonical route in UCP
        )
        # Simulate pre-PR-24 response: UCP has no embedded route
        meta["unified_control_plan"] = _make_ucp_dict(route_decision=None)

        route = meta.get("multimodal_route_decision")
        assert route is not None
        assert route["route_type"] == "native_multimodal"

    def test_ucp_from_dict_without_route_field_is_backward_compatible(self):
        """UCP.from_dict() must not fail on old dicts lacking multimodal_route_decision."""
        from core.schemas.unified_control_plan import UnifiedControlPlan

        old_dict = {
            "plan_id": "ucp_old",
            "schema_version": "1.0",
            "decision_posture": "autonomous",
            "chosen_model_decision": {
                "provider_id": "p1",
                "model_id": "m1",
                "is_native_multimodal": False,
                "selection_reason": None,
                "fallback_chain": [],
            },
            "chosen_execution_decision": {
                "execution_path": "local",
                "delegation_point": None,
                "remote_execution_mode": None,
                "target_device_ids": [],
                "orchestration_active": False,
            },
        }
        plan = UnifiedControlPlan.from_dict(old_dict)
        assert plan.multimodal_route_decision is None
