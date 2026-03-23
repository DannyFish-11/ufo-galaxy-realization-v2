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

import pytest

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
            "is_native_multimodal": route_decision.get("is_native_multimodal", False)
            if route_decision
            else False,
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
        assert summary["multimodal_route_type"] is None


# ---------------------------------------------------------------------------
# Tests: CanonicalStateAdapter — canonical read order
# ---------------------------------------------------------------------------


class TestCanonicalStateAdapterPerceptionState:
    """Adapter must return canonical_perception_state, not multimodal_context."""

    def test_returns_canonical_perception_state(self):
        from core.perception.canonical_state_adapter import CanonicalStateAdapter

        meta = _make_metadata()
        adapter = CanonicalStateAdapter(meta)

        cps = adapter.canonical_perception_state()
        assert cps is not None
        assert "has_request_multimodal" in cps

    def test_canonical_perception_preferred_over_compat(self):
        from core.perception.canonical_state_adapter import CanonicalStateAdapter

        # Both canonical and compat are present; canonical must win
        meta = _make_metadata(include_compat_mm_context=True)
        adapter = CanonicalStateAdapter(meta)

        cps = adapter.canonical_perception_state()
        assert cps is not None
        # Must not be the raw compat dict
        assert "images" not in cps

    def test_returns_none_when_no_canonical_perception(self):
        from core.perception.canonical_state_adapter import CanonicalStateAdapter

        meta = _make_metadata(include_canonical_perception=False)
        adapter = CanonicalStateAdapter(meta)

        assert adapter.canonical_perception_state() is None
        assert not adapter.has_canonical_perception()

    def test_compat_accessor_returns_mm_context(self):
        from core.perception.canonical_state_adapter import CanonicalStateAdapter

        meta = _make_metadata(include_compat_mm_context=True)
        adapter = CanonicalStateAdapter(meta)

        compat = adapter.multimodal_context_compat()
        assert compat is not None
        assert "images" in compat

    def test_has_multimodal_perception_uses_canonical(self):
        from core.perception.canonical_state_adapter import CanonicalStateAdapter

        meta = _make_metadata(is_native=True)
        adapter = CanonicalStateAdapter(meta)

        assert adapter.has_multimodal_perception() is True

    def test_has_multimodal_perception_false_for_text_only(self):
        from core.perception.canonical_state_adapter import CanonicalStateAdapter

        meta = _make_metadata(
            include_canonical_perception=True,
            is_native=False,
        )
        # Override the canonical perception to be text-only
        meta["canonical_perception_state"] = _make_canonical_perception(
            has_multimodal=False, requires_native=False, modalities=[]
        )
        adapter = CanonicalStateAdapter(meta)

        assert adapter.has_multimodal_perception() is False


class TestCanonicalStateAdapterRouteDecision:
    """Adapter must prefer canonical route inside UCP over deprecated top-level key."""

    def test_route_from_ucp_when_available(self):
        from core.perception.canonical_state_adapter import CanonicalStateAdapter

        meta = _make_metadata(route_in_ucp=True, include_compat_top_level_route=True)
        adapter = CanonicalStateAdapter(meta)

        route = adapter.multimodal_route_decision()
        assert route is not None
        assert route["route_type"] == "native_multimodal"

    def test_route_canonical_beats_compat_top_level(self):
        from core.perception.canonical_state_adapter import CanonicalStateAdapter

        # UCP has advisory route; compat top-level has native route
        ucp = _make_ucp_dict(
            route_decision=_make_multimodal_route(route_type="advisory", is_native=False)
        )
        meta = {
            "unified_control_plan": ucp,
            # Compat key has a different value — should be ignored
            "multimodal_route_decision": _make_multimodal_route(
                route_type="native_multimodal", is_native=True
            ),
        }
        adapter = CanonicalStateAdapter(meta)

        route = adapter.multimodal_route_decision()
        # Must return the canonical UCP-embedded value
        assert route["route_type"] == "advisory"

    def test_compat_fallback_when_no_ucp_route(self):
        from core.perception.canonical_state_adapter import CanonicalStateAdapter

        # UCP present but has no embedded route (pre-PR-24 response)
        ucp = _make_ucp_dict(route_decision=None)
        compat_route = _make_multimodal_route(route_type="partial_multimodal", is_native=False)
        meta = {
            "unified_control_plan": ucp,
            "multimodal_route_decision": compat_route,
        }
        adapter = CanonicalStateAdapter(meta)

        route = adapter.multimodal_route_decision()
        # Compat fallback should be used
        assert route is not None
        assert route["route_type"] == "partial_multimodal"

    def test_route_none_when_nothing_present(self):
        from core.perception.canonical_state_adapter import CanonicalStateAdapter

        adapter = CanonicalStateAdapter({})
        assert adapter.multimodal_route_decision() is None
        assert adapter.is_native_multimodal_route() is False
        assert adapter.route_type() is None

    def test_is_native_multimodal_route_true(self):
        from core.perception.canonical_state_adapter import CanonicalStateAdapter

        meta = _make_metadata(route_type="native_multimodal", is_native=True)
        adapter = CanonicalStateAdapter(meta)

        assert adapter.is_native_multimodal_route() is True

    def test_is_native_multimodal_route_false_advisory(self):
        from core.perception.canonical_state_adapter import CanonicalStateAdapter

        ucp = _make_ucp_dict(
            route_decision=_make_multimodal_route(route_type="advisory", is_native=False)
        )
        adapter = CanonicalStateAdapter({"unified_control_plan": ucp})

        assert adapter.is_native_multimodal_route() is False
        assert adapter.route_type() == "advisory"


class TestCanonicalStateAdapterUCP:
    """Adapter must expose UCP-level canonical state correctly."""

    def test_unified_control_plan_present(self):
        from core.perception.canonical_state_adapter import CanonicalStateAdapter

        meta = _make_metadata()
        adapter = CanonicalStateAdapter(meta)

        assert adapter.has_unified_control_plan() is True
        ucp = adapter.unified_control_plan()
        assert ucp is not None
        assert ucp["plan_id"] == "ucp_test123"

    def test_plan_id_from_ucp(self):
        from core.perception.canonical_state_adapter import CanonicalStateAdapter

        meta = _make_metadata()
        adapter = CanonicalStateAdapter(meta)

        assert adapter.plan_id() == "ucp_test123"

    def test_execution_path_from_unified_execution_decision(self):
        from core.perception.canonical_state_adapter import CanonicalStateAdapter

        ucp = _make_ucp_dict(execution_path="cross_device")
        adapter = CanonicalStateAdapter({"unified_control_plan": ucp})

        assert adapter.execution_path() == "cross_device"

    def test_fallback_level_none(self):
        from core.perception.canonical_state_adapter import CanonicalStateAdapter

        meta = _make_metadata()
        adapter = CanonicalStateAdapter(meta)

        assert adapter.fallback_level() == "none"
        assert adapter.has_fallback() is False

    def test_model_supply_summary_from_ucp(self):
        from core.perception.canonical_state_adapter import CanonicalStateAdapter

        ucp = _make_ucp_dict(has_supply=True)
        adapter = CanonicalStateAdapter({"unified_control_plan": ucp})

        supply = adapter.canonical_model_supply_summary()
        assert supply is not None
        assert supply["primary_provider_id"] == "p1"

    def test_model_supply_none_when_absent(self):
        from core.perception.canonical_state_adapter import CanonicalStateAdapter

        ucp = _make_ucp_dict(has_supply=False)
        adapter = CanonicalStateAdapter({"unified_control_plan": ucp})

        assert adapter.canonical_model_supply_summary() is None

    def test_empty_metadata_degrades_gracefully(self):
        from core.perception.canonical_state_adapter import CanonicalStateAdapter

        adapter = CanonicalStateAdapter({})

        assert adapter.canonical_perception_state() is None
        assert adapter.unified_control_plan() is None
        assert adapter.multimodal_route_decision() is None
        assert adapter.has_canonical_perception() is False
        assert adapter.has_unified_control_plan() is False
        assert adapter.is_native_multimodal_route() is False

    def test_none_metadata_degrades_gracefully(self):
        from core.perception.canonical_state_adapter import CanonicalStateAdapter

        adapter = CanonicalStateAdapter(None)

        assert adapter.canonical_perception_state() is None
        assert adapter.unified_control_plan() is None
        assert adapter.multimodal_route_decision() is None


# ---------------------------------------------------------------------------
# Tests: canonical_state_summary diagnostics
# ---------------------------------------------------------------------------


class TestCanonicalStateSummary:
    """canonical_state_summary() must expose truthful canonical state presence."""

    def test_full_canonical_state_summary(self):
        from core.perception.canonical_state_adapter import CanonicalStateAdapter

        meta = _make_metadata(
            include_canonical_perception=True,
            include_ucp=True,
            route_in_ucp=True,
            include_compat_mm_context=True,
            include_compat_top_level_route=True,
            is_native=True,
        )
        adapter = CanonicalStateAdapter(meta)
        summary = adapter.canonical_state_summary()

        assert summary["has_canonical_perception"] is True
        assert summary["has_unified_control_plan"] is True
        assert summary["plan_id"] == "ucp_test123"
        assert summary["route_type"] == "native_multimodal"
        assert summary["is_native_multimodal_route"] is True
        assert summary["requires_native_multimodal"] is True
        # Compat fields present (for migration audit)
        assert summary["compat_multimodal_context_present"] is True
        assert summary["compat_top_level_route_present"] is True
        # Canonical route embedded in UCP (PR-24)
        assert summary["canonical_route_in_ucp"] is True

    def test_text_only_summary(self):
        from core.perception.canonical_state_adapter import CanonicalStateAdapter

        meta: Dict[str, Any] = {
            "canonical_perception_state": _make_canonical_perception(
                has_multimodal=False, requires_native=False, modalities=[]
            ),
            "unified_control_plan": _make_ucp_dict(route_decision=None),
        }
        adapter = CanonicalStateAdapter(meta)
        summary = adapter.canonical_state_summary()

        assert summary["has_canonical_perception"] is True
        assert summary["has_unified_control_plan"] is True
        assert summary["route_type"] is None
        assert summary["is_native_multimodal_route"] is False
        assert summary["requires_native_multimodal"] is False
        assert summary["canonical_route_in_ucp"] is False
        assert summary["compat_multimodal_context_present"] is False
        assert summary["compat_top_level_route_present"] is False


# ---------------------------------------------------------------------------
# Tests: no duplicate-state drift (canonical vs compat do not disagree)
# ---------------------------------------------------------------------------


class TestNoDuplicateStateDrift:
    """Canonical state must not drift from compat fields in representative scenarios."""

    def test_canonical_route_in_ucp_matches_compat_top_level(self):
        """When both are present, they should carry the same route_type."""
        from core.perception.canonical_state_adapter import CanonicalStateAdapter

        route = _make_multimodal_route(route_type="native_multimodal", is_native=True)
        ucp = _make_ucp_dict(route_decision=route)
        meta = {
            "unified_control_plan": ucp,
            "multimodal_route_decision": route,  # compat copy
        }
        adapter = CanonicalStateAdapter(meta)

        # Adapter reads canonical (UCP-embedded); values agree with compat
        assert adapter.route_type() == "native_multimodal"
        assert adapter.is_native_multimodal_route() is True

    def test_is_native_multimodal_consistent_with_perception(self):
        """canonical_perception_state.requires_native_multimodal must agree with
        the routing decision's is_native_multimodal when both are present."""
        from core.perception.canonical_state_adapter import CanonicalStateAdapter

        meta = _make_metadata(is_native=True)
        adapter = CanonicalStateAdapter(meta)

        # Both must say native
        assert adapter.requires_native_multimodal() is True
        assert adapter.is_native_multimodal_route() is True

    def test_text_only_no_native_multimodal_anywhere(self):
        """Text-only flow must have no native multimodal signal in any state path."""
        from core.perception.canonical_state_adapter import CanonicalStateAdapter

        cps = _make_canonical_perception(
            has_multimodal=False, requires_native=False, modalities=[]
        )
        ucp = _make_ucp_dict(
            route_decision=_make_multimodal_route(
                route_type="advisory", is_native=False
            )
        )
        meta = {"canonical_perception_state": cps, "unified_control_plan": ucp}
        adapter = CanonicalStateAdapter(meta)

        assert adapter.requires_native_multimodal() is False
        assert adapter.is_native_multimodal_route() is False
        assert adapter.has_multimodal_perception() is False

    def test_build_ucp_route_decision_parameter_accepted(self):
        """build_unified_control_plan must accept multimodal_route_decision
        without raising."""
        from core.schemas.unified_control_plan import build_unified_control_plan

        route = _make_multimodal_route(route_type="partial_multimodal", is_native=False)
        plan = build_unified_control_plan(
            multimodal_route_decision=route,
            is_native_multimodal=False,
            execution_path="local",
        )

        assert plan.multimodal_route_decision is not None
        assert plan.multimodal_route_decision["route_type"] == "partial_multimodal"
        # chosen_model_decision should also reflect the non-native flag
        assert plan.chosen_model_decision.is_native_multimodal is False


# ---------------------------------------------------------------------------
# Tests: backward compatibility — existing callers still work
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    """Deprecated compat fields must remain accessible for backward compatibility."""

    def test_compat_mm_context_still_readable_from_metadata(self):
        from core.perception.canonical_state_adapter import CanonicalStateAdapter

        meta = _make_metadata(include_compat_mm_context=True)
        adapter = CanonicalStateAdapter(meta)

        # Legacy consumers that read this directly should still get data
        raw = meta.get("multimodal_context")
        assert raw is not None

        # Adapter compat accessor also works
        compat = adapter.multimodal_context_compat()
        assert compat is not None

    def test_compat_top_level_route_still_readable_from_metadata(self):
        from core.perception.canonical_state_adapter import CanonicalStateAdapter

        meta = _make_metadata(
            include_compat_top_level_route=True,
            route_in_ucp=False,  # No canonical route in UCP
        )
        # Simulate pre-PR-24 response: UCP has no embedded route
        meta["unified_control_plan"] = _make_ucp_dict(route_decision=None)

        adapter = CanonicalStateAdapter(meta)

        # Compat fallback must be used when canonical source is absent
        route = adapter.multimodal_route_decision()
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
