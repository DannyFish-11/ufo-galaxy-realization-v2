"""
tests/test_pr3_runtime_projection.py
======================================
Tests for PR-3: Runtime Projection Object.

Coverage
--------
- Minimal projection creation (continuum state only, no route plan)
- Minimal projection creation with continuum + route plan
- Correct population of tri_state_phase / runtime_domain from ContinuumState
- Correct population of primary_model_id / support_model_ids / active_weights
  from TopologyRoutePlan
- correct population of all continuum metrics (coherence, collapse_tendency,
  retreat_tendency, presence_intensity)
- ExecutionSummary integration (active_device_ids, execution_stage, task summary)
- Serialisation stability: to_dict() produces correct types
- to_json() round-trip: json.loads(projection.to_json()) == projection.to_dict()
- Missing optional fields handled gracefully (no route plan, no exec summary)
- Explicit timestamp override
- repr smoke test
- Empty inventory → primary_model_id is None, support_model_ids is empty
- RuntimeProjection can be constructed directly without the compiler
"""

from __future__ import annotations

import json
import time
from typing import Optional

import pytest

from core.continuum.types import (
    ContinuumPhase,
    ContinuumState,
    RuntimeDomain,
    TriStatePhase,
)
from core.model_topology import (
    AggregatorKind,
    AggregatorRouterHint,
    LegacyLLMProviderSnapshot,
    ProviderInventory,
    TopologyRouter,
)
from core.model_topology.config_bridge import ConfigBridge
from core.projection import ExecutionSummary, RuntimeProjection, build_runtime_projection

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_OPENAI_DICT = {
    "provider": "openai",
    "model": "gpt-5.4",
    "models": ["gpt-5.4", "gpt-4o"],
    "speed_score": 8,
    "quality_score": 9,
    "available": True,
    "multimodal": True,
    "env_keys": ["OPENAI_API_KEY"],
}

_ANTHROPIC_DICT = {
    "provider": "anthropic",
    "model": "claude-opus-4.6",
    "models": ["claude-opus-4.6", "claude-sonnet-4.6"],
    "speed_score": 6,
    "quality_score": 10,
    "available": True,
    "multimodal": True,
    "env_keys": ["ANTHROPIC_API_KEY"],
}

_LOCAL_DICT = {
    "provider": "local",
    "model": "llama3",
    "models": ["llama3"],
    "speed_score": 9,
    "quality_score": 5,
    "available": True,
    "multimodal": False,
    "env_keys": [],
}


def _make_inventory() -> ProviderInventory:
    bridge = ConfigBridge()
    snapshots = [
        LegacyLLMProviderSnapshot.from_dict(_OPENAI_DICT),
        LegacyLLMProviderSnapshot.from_dict(_ANTHROPIC_DICT),
        LegacyLLMProviderSnapshot.from_dict(_LOCAL_DICT),
    ]
    return bridge.build_inventory(snapshots)


def _liminal_state(
    runtime_domain: Optional[RuntimeDomain] = RuntimeDomain.LOCAL,
) -> ContinuumState:
    return ContinuumState(
        phase=ContinuumPhase.LIMINAL,
        presence_intensity=0.6,
        coherence=0.5,
        collapse_tendency=0.3,
        retreat_tendency=0.1,
        runtime_domain=runtime_domain,
    )


def _manifest_state() -> ContinuumState:
    return ContinuumState(
        phase=ContinuumPhase.MANIFEST,
        presence_intensity=0.9,
        coherence=0.8,
        collapse_tendency=0.7,
        retreat_tendency=0.05,
        runtime_domain=RuntimeDomain.LOCAL,
    )


# ---------------------------------------------------------------------------
# TestMinimalProjection — continuum only, no route plan
# ---------------------------------------------------------------------------


class TestMinimalProjection:
    """Projection built from ContinuumState only (no route plan)."""

    def test_tri_state_phase_populated(self):
        state = _liminal_state()
        proj = build_runtime_projection(state)
        assert proj.tri_state_phase is TriStatePhase.LIMINAL

    def test_runtime_domain_from_state(self):
        state = _liminal_state(runtime_domain=RuntimeDomain.CROSS_DEVICE)
        proj = build_runtime_projection(state)
        assert proj.runtime_domain is RuntimeDomain.CROSS_DEVICE

    def test_runtime_domain_none_when_undetermined(self):
        state = ContinuumState(phase=ContinuumPhase.FORMLESS)
        proj = build_runtime_projection(state)
        assert proj.runtime_domain is None

    def test_no_route_plan_yields_empty_model_fields(self):
        state = _liminal_state()
        proj = build_runtime_projection(state)
        assert proj.primary_model_id is None
        assert proj.support_model_ids == []
        assert proj.active_weights == {}
        assert proj.route_reason is None

    def test_no_execution_summary_yields_empty_device_fields(self):
        state = _liminal_state()
        proj = build_runtime_projection(state)
        assert proj.active_device_ids == []
        assert proj.execution_stage is None
        assert proj.current_task_summary is None

    def test_metrics_populated(self):
        state = _liminal_state()
        proj = build_runtime_projection(state)
        assert proj.presence_intensity == pytest.approx(0.6)
        assert proj.coherence == pytest.approx(0.5)
        assert proj.collapse_tendency == pytest.approx(0.3)
        assert proj.retreat_tendency == pytest.approx(0.1)

    def test_manifest_tri_state(self):
        state = _manifest_state()
        proj = build_runtime_projection(state)
        assert proj.tri_state_phase is TriStatePhase.MANIFEST

    def test_receding_phase_maps_to_silent(self):
        """Internal receding phase must be collapsed to SILENT in the projection."""
        state = ContinuumState(phase=ContinuumPhase.RECEDING)
        proj = build_runtime_projection(state)
        assert proj.tri_state_phase is TriStatePhase.SILENT

    def test_formless_phase_maps_to_silent(self):
        state = ContinuumState(phase=ContinuumPhase.FORMLESS)
        proj = build_runtime_projection(state)
        assert proj.tri_state_phase is TriStatePhase.SILENT

    def test_timestamp_auto_assigned(self):
        before = time.time()
        proj = build_runtime_projection(_liminal_state())
        after = time.time()
        assert before <= proj.timestamp <= after

    def test_explicit_timestamp_override(self):
        ts = 1_700_000_000.0
        proj = build_runtime_projection(_liminal_state(), timestamp=ts)
        assert proj.timestamp == ts


# ---------------------------------------------------------------------------
# TestProjectionWithRoutePlan — continuum + route plan
# ---------------------------------------------------------------------------


class TestProjectionWithRoutePlan:
    """Projection built from ContinuumState + TopologyRoutePlan."""

    @pytest.fixture()
    def full_plan(self):
        inventory = _make_inventory()
        router = TopologyRouter(inventory)
        return router.route(TriStatePhase.LIMINAL, RuntimeDomain.LOCAL)

    def test_primary_model_id_set(self, full_plan):
        proj = build_runtime_projection(_liminal_state(), route_plan=full_plan)
        assert proj.primary_model_id is not None
        assert isinstance(proj.primary_model_id, str)
        assert len(proj.primary_model_id) > 0

    def test_primary_model_is_multimodal_native(self, full_plan):
        """The primary model in LIMINAL/LOCAL must be a native multimodal node."""
        proj = build_runtime_projection(_liminal_state(), route_plan=full_plan)
        # The primary node in the plan should be a multimodal node.
        assert full_plan.primary_model is not None
        assert full_plan.primary_model.is_multimodal_native

    def test_support_model_ids_list(self, full_plan):
        proj = build_runtime_projection(_liminal_state(), route_plan=full_plan)
        assert isinstance(proj.support_model_ids, list)
        # There should be at least one support model with our 3-provider inventory.
        assert len(proj.support_model_ids) >= 1

    def test_active_weights_dict_of_floats(self, full_plan):
        proj = build_runtime_projection(_liminal_state(), route_plan=full_plan)
        assert isinstance(proj.active_weights, dict)
        assert len(proj.active_weights) > 0
        for node_id, weight in proj.active_weights.items():
            assert isinstance(node_id, str)
            assert isinstance(weight, float)

    def test_primary_model_in_active_weights(self, full_plan):
        proj = build_runtime_projection(_liminal_state(), route_plan=full_plan)
        assert proj.primary_model_id in proj.active_weights

    def test_support_models_in_active_weights(self, full_plan):
        proj = build_runtime_projection(_liminal_state(), route_plan=full_plan)
        for sid in proj.support_model_ids:
            assert sid in proj.active_weights

    def test_route_reason_string(self, full_plan):
        proj = build_runtime_projection(_liminal_state(), route_plan=full_plan)
        assert proj.route_reason is not None
        assert isinstance(proj.route_reason, str)
        assert len(proj.route_reason) > 0

    def test_tri_state_phase_still_from_continuum(self, full_plan):
        """tri_state_phase must come from ContinuumState, not the route plan."""
        state = _manifest_state()
        proj = build_runtime_projection(state, route_plan=full_plan)
        assert proj.tri_state_phase is TriStatePhase.MANIFEST

    def test_runtime_domain_still_from_continuum(self, full_plan):
        state = ContinuumState(
            phase=ContinuumPhase.MANIFEST,
            runtime_domain=RuntimeDomain.CROSS_DEVICE,
        )
        proj = build_runtime_projection(state, route_plan=full_plan)
        assert proj.runtime_domain is RuntimeDomain.CROSS_DEVICE

    def test_manifest_cross_device_plan(self):
        inventory = _make_inventory()
        router = TopologyRouter(inventory)
        plan = router.route(TriStatePhase.MANIFEST, RuntimeDomain.CROSS_DEVICE)
        state = ContinuumState(
            phase=ContinuumPhase.MANIFEST,
            runtime_domain=RuntimeDomain.CROSS_DEVICE,
        )
        proj = build_runtime_projection(state, route_plan=plan)
        assert proj.tri_state_phase is TriStatePhase.MANIFEST
        assert proj.runtime_domain is RuntimeDomain.CROSS_DEVICE
        assert proj.primary_model_id is not None

    def test_empty_inventory_primary_is_none(self):
        inventory = ProviderInventory(entries=[])
        router = TopologyRouter(inventory)
        plan = router.route(TriStatePhase.SILENT, RuntimeDomain.LOCAL)
        proj = build_runtime_projection(_liminal_state(), route_plan=plan)
        assert proj.primary_model_id is None
        assert proj.support_model_ids == []


# ---------------------------------------------------------------------------
# TestExecutionSummaryIntegration
# ---------------------------------------------------------------------------


class TestExecutionSummaryIntegration:
    """ExecutionSummary fields must propagate correctly into the projection."""

    def test_active_device_ids_populated(self):
        state = _liminal_state()
        summary = ExecutionSummary(active_device_ids=["phone-1", "desktop-2"])
        proj = build_runtime_projection(state, execution_summary=summary)
        assert proj.active_device_ids == ["phone-1", "desktop-2"]

    def test_execution_stage_populated(self):
        state = _liminal_state()
        summary = ExecutionSummary(execution_stage="executing")
        proj = build_runtime_projection(state, execution_summary=summary)
        assert proj.execution_stage == "executing"

    def test_current_task_summary_populated(self):
        state = _liminal_state()
        summary = ExecutionSummary(current_task_summary="Open the settings dialog")
        proj = build_runtime_projection(state, execution_summary=summary)
        assert proj.current_task_summary == "Open the settings dialog"

    def test_all_execution_fields_together(self):
        state = _manifest_state()
        summary = ExecutionSummary(
            active_device_ids=["win-main"],
            execution_stage="completing",
            current_task_summary="Summarise meeting notes",
        )
        proj = build_runtime_projection(state, execution_summary=summary)
        assert proj.active_device_ids == ["win-main"]
        assert proj.execution_stage == "completing"
        assert proj.current_task_summary == "Summarise meeting notes"

    def test_none_execution_summary_defaults(self):
        state = _liminal_state()
        proj = build_runtime_projection(state, execution_summary=None)
        assert proj.active_device_ids == []
        assert proj.execution_stage is None
        assert proj.current_task_summary is None

    def test_empty_execution_summary_defaults(self):
        state = _liminal_state()
        summary = ExecutionSummary()
        proj = build_runtime_projection(state, execution_summary=summary)
        assert proj.active_device_ids == []
        assert proj.execution_stage is None
        assert proj.current_task_summary is None


# ---------------------------------------------------------------------------
# TestSerialisationStability
# ---------------------------------------------------------------------------


class TestSerialisationStability:
    """to_dict() and to_json() must produce stable, well-typed output."""

    def test_to_dict_keys_present(self):
        proj = build_runtime_projection(_liminal_state())
        d = proj.to_dict()
        expected_keys = {
            "tri_state_phase",
            "runtime_domain",
            "presence_intensity",
            "coherence",
            "collapse_tendency",
            "retreat_tendency",
            "primary_model_id",
            "support_model_ids",
            "active_weights",
            "route_reason",
            "routing_authority",
            "active_device_ids",
            "execution_stage",
            "current_task_summary",
            "execution_intent_summary",
            "governance",
            "runtime_governance_snapshot",
            "policy_alignment",
            "oneapi_summary",
            "provider_status_summary",
            "timestamp",
        }
        assert expected_keys == set(d.keys())

    def test_to_dict_tri_state_phase_is_string(self):
        proj = build_runtime_projection(_liminal_state())
        d = proj.to_dict()
        assert d["tri_state_phase"] == "liminal"

    def test_to_dict_runtime_domain_is_string_or_none(self):
        proj_local = build_runtime_projection(_liminal_state(RuntimeDomain.LOCAL))
        assert proj_local.to_dict()["runtime_domain"] == "local"

        proj_none = build_runtime_projection(ContinuumState(phase=ContinuumPhase.FORMLESS))
        assert proj_none.to_dict()["runtime_domain"] is None

    def test_to_dict_support_model_ids_is_list(self):
        proj = build_runtime_projection(_liminal_state())
        d = proj.to_dict()
        assert isinstance(d["support_model_ids"], list)

    def test_to_dict_active_weights_is_dict(self):
        proj = build_runtime_projection(_liminal_state())
        d = proj.to_dict()
        assert isinstance(d["active_weights"], dict)

    def test_to_dict_active_device_ids_is_list(self):
        proj = build_runtime_projection(_liminal_state())
        d = proj.to_dict()
        assert isinstance(d["active_device_ids"], list)

    def test_to_dict_with_route_plan_weights_are_floats(self):
        inventory = _make_inventory()
        plan = TopologyRouter(inventory).route(TriStatePhase.LIMINAL, RuntimeDomain.LOCAL)
        proj = build_runtime_projection(_liminal_state(), route_plan=plan)
        for weight in proj.to_dict()["active_weights"].values():
            assert isinstance(weight, float)

    def test_to_json_round_trip(self):
        inventory = _make_inventory()
        plan = TopologyRouter(inventory).route(TriStatePhase.MANIFEST, RuntimeDomain.LOCAL)
        summary = ExecutionSummary(
            active_device_ids=["device-1"],
            execution_stage="executing",
            current_task_summary="Test round-trip",
        )
        proj = build_runtime_projection(
            _manifest_state(),
            route_plan=plan,
            execution_summary=summary,
        )
        json_str = proj.to_json()
        parsed = json.loads(json_str)
        assert parsed == proj.to_dict()

    def test_to_json_is_valid_json(self):
        proj = build_runtime_projection(_liminal_state())
        json_str = proj.to_json()
        assert isinstance(json_str, str)
        parsed = json.loads(json_str)
        assert isinstance(parsed, dict)

    def test_to_json_indent_kwarg_works(self):
        proj = build_runtime_projection(_liminal_state())
        json_str = proj.to_json(indent=2)
        parsed = json.loads(json_str)
        assert parsed["tri_state_phase"] == "liminal"

    def test_to_dict_is_deterministic_without_timestamp(self):
        """Two calls with the same timestamp must produce identical dicts."""
        ts = 1_700_000_000.0
        proj1 = build_runtime_projection(_liminal_state(), timestamp=ts)
        proj2 = build_runtime_projection(_liminal_state(), timestamp=ts)
        assert proj1.to_dict() == proj2.to_dict()

    def test_none_optional_fields_preserved_in_dict(self):
        """None fields must remain None in the serialised dict (not omitted)."""
        proj = build_runtime_projection(ContinuumState(phase=ContinuumPhase.FORMLESS))
        d = proj.to_dict()
        assert d["runtime_domain"] is None
        assert d["primary_model_id"] is None
        assert d["route_reason"] is None
        assert d["execution_stage"] is None
        assert d["current_task_summary"] is None


# ---------------------------------------------------------------------------
# TestDirectConstruction — RuntimeProjection built without the compiler
# ---------------------------------------------------------------------------


class TestDirectConstruction:
    """RuntimeProjection can be constructed directly when callers want full control."""

    def test_direct_construction_minimal(self):
        proj = RuntimeProjection(tri_state_phase=TriStatePhase.SILENT)
        assert proj.tri_state_phase is TriStatePhase.SILENT
        assert proj.runtime_domain is None
        assert proj.primary_model_id is None
        assert proj.support_model_ids == []
        assert proj.active_weights == {}
        assert proj.active_device_ids == []

    def test_direct_construction_full(self):
        ts = 1_700_000_001.0
        proj = RuntimeProjection(
            tri_state_phase=TriStatePhase.MANIFEST,
            runtime_domain=RuntimeDomain.CROSS_DEVICE,
            presence_intensity=0.9,
            coherence=0.8,
            collapse_tendency=0.7,
            retreat_tendency=0.05,
            primary_model_id="node-gpt5",
            support_model_ids=["node-claude", "node-local"],
            active_weights={"node-gpt5": 1.4, "node-claude": 1.2, "node-local": 0.9},
            route_reason="native multimodal primary in MANIFEST/CROSS_DEVICE",
            active_device_ids=["desktop-win", "phone-android"],
            execution_stage="executing",
            current_task_summary="Send daily report",
            timestamp=ts,
        )
        assert proj.tri_state_phase is TriStatePhase.MANIFEST
        assert proj.runtime_domain is RuntimeDomain.CROSS_DEVICE
        assert proj.primary_model_id == "node-gpt5"
        assert proj.support_model_ids == ["node-claude", "node-local"]
        assert proj.active_weights["node-gpt5"] == pytest.approx(1.4)
        assert proj.active_device_ids == ["desktop-win", "phone-android"]
        assert proj.execution_stage == "executing"
        assert proj.timestamp == ts

    def test_repr_smoke(self):
        proj = RuntimeProjection(
            tri_state_phase=TriStatePhase.LIMINAL,
            runtime_domain=RuntimeDomain.LOCAL,
            primary_model_id="node-xyz",
        )
        r = repr(proj)
        assert "liminal" in r
        assert "local" in r
        assert "node-xyz" in r

    def test_repr_no_domain(self):
        proj = RuntimeProjection(tri_state_phase=TriStatePhase.SILENT)
        r = repr(proj)
        assert "silent" in r
        assert "None" in r
