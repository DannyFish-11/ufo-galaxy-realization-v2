"""tests/test_pr20_runtime_decision_observability.py
=====================================================

Tests for PR-20: Unified Runtime Decision Observability.

Coverage matrix
---------------
Group A — Sentinel / authority assertions
  A01. RUNTIME_DECISION_OBSERVABILITY_IS_AUTHORITY sentinel exists.
  A02. RUNTIME_DECISION_OBSERVABILITY_PR20_SENTINEL sentinel exists.
  A03. HARD_GATES_ARE_PRIMARY_AUTHORITY_POLICY sentinel exists.
  A04. OBSERVABILITY_REFLECTS_REAL_DECISIONS_POLICY sentinel exists.
  A05. INFLUENCE_LAYERS_ARE_NON_AUTHORITATIVE_POLICY sentinel exists.
  A06. DIAGNOSTICS_SURFACE_IS_CANONICAL_NOT_PARALLEL_POLICY sentinel exists.
  A07. RUNTIME_DECISION_OBSERVABILITY_WIRED_INTO_KERNEL_PR20 sentinel in kernel.py.
  A08. RUNTIME_DECISION_OBSERVABILITY_ALIGNED_PR20 sentinel in projection.py.
  A09. RUNTIME_DECISION_OBSERVABILITY_ALIGNED_GOVERNANCE_PR20 sentinel in governance.
  A10. EMPTY_RUNTIME_DECISION_EXPLANATION sentinel has expected shape.

Group B — InfluenceClass enum
  B01. All InfluenceClass values are strings.
  B02. Known values stable (hard_gate, soft_hint, policy_bias, memory_influence,
       task_semantic_influence, execution_posture, topology_influence).
  B03. Round-trip InfluenceClass via value string.

Group C — RuntimeDecisionRecord
  C01. Construction with defaults succeeds.
  C02. to_dict() returns expected keys.
  C03. from_dict() round-trips correctly.
  C04. from_dict() degrades on unknown influence_class.

Group D — RuntimeDecisionExplanation
  D01. Construction with all defaults succeeds.
  D02. to_dict() returns all guaranteed keys.
  D03. from_dict() round-trips correctly.
  D04. has_hard_gate = False when no hard gates.
  D05. has_hard_gate = True when active hard gate present.
  D06. active_influence_count reflects confirmed-active soft influences only.
  D07. from_dict() degrades gracefully on missing/partial data.

Group E — build_runtime_decision_explanation
  E01. Empty call returns valid RuntimeDecisionExplanation.
  E02. task_hint is reflected in explanation.task_hint.
  E03. task_semantic_influenced_routing=True reflected.
  E04. task_semantic_influenced_planner=True reflected.
  E05. activation_budget_hint → activation_budget_active and activation_budget_mode.
  E06. memory_bias_hint → memory_bias_posture and memory_influenced_planner.
  E07. governance_decision with eligible=False → has_hard_gate=True and node_allowed=False.
  E08. governance_decision with eligible=True → node_allowed=True, has_hard_gate=False.
  E09. cognitive_hint_dict → cognitive_region and execution_path_preference.
  E10. planner_strategy reflected in explanation.planner_strategy.
  E11. planner_strategy driven_by fields reflect active influence layers.
  E12. extra_records appended to soft_influences.
  E13. extra_records with HARD_GATE go to hard_gates.
  E14. build_runtime_decision_explanation never raises — returns EMPTY_SENTINEL on error.
  E15. task_semantic_influenced_routing=False when task_hint is None.

Group F — build_runtime_decision_diagnostics
  F01. None input → minimal fallback dict with all guaranteed keys.
  F02. Non-explanation input → minimal fallback dict.
  F03. Full explanation → all guaranteed keys present.
  F04. has_hard_gate field reflects explanation.has_hard_gate.
  F05. hard_gate_count reflects len(hard_gates).
  F06. active_soft_influence_count reflects explanation.active_influence_count.
  F07. influence_layers lists all records.
  F08. include_detail=True adds 'detail' to each influence layer entry.
  F09. include_detail=False omits 'detail' from influence layer entries.
  F10. observability_authority key present.
  F11. build_runtime_decision_diagnostics never raises on bad input.

Group G — enrich_multimodal_route_with_observability
  G01. Adds pr20_task_hint to route dict.
  G02. Adds pr20_task_semantic_influenced_routing to route dict.
  G03. Adds pr20_observability_source to route dict.
  G04. Original route_type is preserved.
  G05. Never raises on None task_hint.

Group H — enrich_governance_decision_with_observability
  H01. Adds pr20_observability_context to decision dict.
  H02. pr20_observability_context has task_hint field.
  H03. pr20_observability_context has activation_budget_mode field.
  H04. pr20_observability_context has memory_bias_posture field.
  H05. pr20_observability_context.observability_pr20_active = True.
  H06. Never raises on None/missing inputs.

Group I — Governance wiring (PR-20 context in governance decisions)
  I01. evaluate_invocation_governance accepts memory_bias parameter.
  I02. evaluate_invocation_governance accepts task_hint parameter.
  I03. With memory_bias=None, task_hint=None — no crash, no pr20 key expected.
  I04. governance decision diagnostic_context structure unchanged (PR-18 compat).

Group J — Kernel wiring
  J01. KernelResponse has runtime_decision_explanation field (Optional[Dict]).
  J02. to_api_dict() includes 'runtime_decision_explanation' key.

Group K — Backward compatibility
  K01. Old callers using build_runtime_decision_explanation() without any args work.
  K02. Old callers using evaluate_invocation_governance() without new params work.
  K03. build_runtime_decision_explanation never raises on garbage input.
  K04. build_runtime_decision_diagnostics never raises on garbage input.

Group L — Influence hierarchy / authority assertions
  L01. Memory bias NOVELTY posture does not create a hard gate.
  L02. Governance denial creates a hard gate record.
  L03. Task semantic influence does not elevate to hard gate.
  L04. Execution posture influence does not elevate to hard gate.
  L05. Multiple soft influences stack without interference.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_budget_hint(
    breadth_mode: str = "moderate",
    influenced: bool = True,
    budget_value: float = 0.6,
) -> Dict[str, Any]:
    return {
        "posture": "liminal",
        "breadth_mode": breadth_mode,
        "budget_value": budget_value,
        "influenced_runtime_decision": influenced,
        "influence_source": "kernel_process",
    }


def _make_memory_hint(
    posture: str = "continuity",
    influenced: bool = True,
) -> Dict[str, Any]:
    return {
        "posture": posture,
        "continuity_score": 0.7,
        "retrieval_relevance": 0.1,
        "influenced_runtime_decision": influenced,
        "influence_source": "memory_bias_layer",
    }


def _make_governance_dict(
    eligible: bool = True,
    denial_reasons: Optional[List[str]] = None,
) -> Dict[str, Any]:
    return {
        "eligible": eligible,
        "denial_reasons": denial_reasons or [],
        "governance_status": "eligible" if eligible else "ineligible_denied",
        "node_id": "test_node",
    }


def _make_cognitive_hint_dict(
    region: str = "LIMINAL",
    path_pref: str = "planning",
) -> Dict[str, Any]:
    return {
        "cognitive_region": region,
        "execution_path_preference": path_pref,
        "activation_budget": 0.6,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Group A — Sentinels / authority
# ─────────────────────────────────────────────────────────────────────────────


class TestGroupA_Sentinels:
    def test_A01_is_authority_sentinel_exists(self):
        from core.runtime_decision_observability import RUNTIME_DECISION_OBSERVABILITY_IS_AUTHORITY
        assert isinstance(RUNTIME_DECISION_OBSERVABILITY_IS_AUTHORITY, str)
        assert "CANONICAL_AUTHORITY" in RUNTIME_DECISION_OBSERVABILITY_IS_AUTHORITY

    def test_A02_pr20_sentinel_exists(self):
        from core.runtime_decision_observability import RUNTIME_DECISION_OBSERVABILITY_PR20_SENTINEL
        assert isinstance(RUNTIME_DECISION_OBSERVABILITY_PR20_SENTINEL, str)
        assert "PR20_SENTINEL" in RUNTIME_DECISION_OBSERVABILITY_PR20_SENTINEL

    def test_A03_hard_gates_policy_exists(self):
        from core.runtime_decision_observability import HARD_GATES_ARE_PRIMARY_AUTHORITY_POLICY
        assert isinstance(HARD_GATES_ARE_PRIMARY_AUTHORITY_POLICY, str)
        assert "POLICY_1" in HARD_GATES_ARE_PRIMARY_AUTHORITY_POLICY

    def test_A04_real_decisions_policy_exists(self):
        from core.runtime_decision_observability import OBSERVABILITY_REFLECTS_REAL_DECISIONS_POLICY
        assert isinstance(OBSERVABILITY_REFLECTS_REAL_DECISIONS_POLICY, str)
        assert "POLICY_2" in OBSERVABILITY_REFLECTS_REAL_DECISIONS_POLICY

    def test_A05_influence_layers_policy_exists(self):
        from core.runtime_decision_observability import INFLUENCE_LAYERS_ARE_NON_AUTHORITATIVE_POLICY
        assert isinstance(INFLUENCE_LAYERS_ARE_NON_AUTHORITATIVE_POLICY, str)
        assert "POLICY_3" in INFLUENCE_LAYERS_ARE_NON_AUTHORITATIVE_POLICY

    def test_A06_diagnostics_canonical_policy_exists(self):
        from core.runtime_decision_observability import DIAGNOSTICS_SURFACE_IS_CANONICAL_NOT_PARALLEL_POLICY
        assert isinstance(DIAGNOSTICS_SURFACE_IS_CANONICAL_NOT_PARALLEL_POLICY, str)
        assert "POLICY_4" in DIAGNOSTICS_SURFACE_IS_CANONICAL_NOT_PARALLEL_POLICY

    def test_A07_kernel_sentinel_exists(self):
        try:
            from core.agent.kernel import RUNTIME_DECISION_OBSERVABILITY_WIRED_INTO_KERNEL_PR20
            assert isinstance(RUNTIME_DECISION_OBSERVABILITY_WIRED_INTO_KERNEL_PR20, str)
            assert "PR20" in RUNTIME_DECISION_OBSERVABILITY_WIRED_INTO_KERNEL_PR20
        except ImportError:
            pytest.skip("kernel.py not importable (pydantic missing)")

    def test_A08_projection_sentinel_present_in_file(self):
        with open("core/routes/projection.py") as f:
            content = f.read()
        assert "RUNTIME_DECISION_OBSERVABILITY_ALIGNED_PR20" in content

    def test_A09_governance_sentinel_exists(self):
        from core.node_invocation_governance import RUNTIME_DECISION_OBSERVABILITY_ALIGNED_GOVERNANCE_PR20
        assert isinstance(RUNTIME_DECISION_OBSERVABILITY_ALIGNED_GOVERNANCE_PR20, str)
        assert "PR20" in RUNTIME_DECISION_OBSERVABILITY_ALIGNED_GOVERNANCE_PR20

    def test_A10_empty_explanation_sentinel_has_expected_shape(self):
        from core.runtime_decision_observability import EMPTY_RUNTIME_DECISION_EXPLANATION
        assert EMPTY_RUNTIME_DECISION_EXPLANATION.execution_path == "unknown"
        assert "EMPTY_SENTINEL" in EMPTY_RUNTIME_DECISION_EXPLANATION.source_authority


# ─────────────────────────────────────────────────────────────────────────────
# Group B — InfluenceClass enum
# ─────────────────────────────────────────────────────────────────────────────


class TestGroupB_InfluenceClass:
    def test_B01_all_values_are_strings(self):
        from core.runtime_decision_observability import InfluenceClass
        for member in InfluenceClass:
            assert isinstance(member.value, str)
            assert member.value

    def test_B02_known_values_stable(self):
        from core.runtime_decision_observability import InfluenceClass
        assert InfluenceClass.HARD_GATE.value == "hard_gate"
        assert InfluenceClass.SOFT_HINT.value == "soft_hint"
        assert InfluenceClass.POLICY_BIAS.value == "policy_bias"
        assert InfluenceClass.MEMORY_INFLUENCE.value == "memory_influence"
        assert InfluenceClass.TASK_SEMANTIC_INFLUENCE.value == "task_semantic_influence"
        assert InfluenceClass.EXECUTION_POSTURE.value == "execution_posture"
        assert InfluenceClass.TOPOLOGY_INFLUENCE.value == "topology_influence"

    def test_B03_round_trip_via_value(self):
        from core.runtime_decision_observability import InfluenceClass
        for member in InfluenceClass:
            assert InfluenceClass(member.value) is member


# ─────────────────────────────────────────────────────────────────────────────
# Group C — RuntimeDecisionRecord
# ─────────────────────────────────────────────────────────────────────────────


class TestGroupC_RuntimeDecisionRecord:
    def test_C01_construction_with_defaults(self):
        from core.runtime_decision_observability import RuntimeDecisionRecord, InfluenceClass
        r = RuntimeDecisionRecord(
            layer_name="test",
            influence_class=InfluenceClass.SOFT_HINT,
            active=True,
        )
        assert r.layer_name == "test"
        assert r.active is True
        assert r.detail == {}

    def test_C02_to_dict_expected_keys(self):
        from core.runtime_decision_observability import RuntimeDecisionRecord, InfluenceClass
        r = RuntimeDecisionRecord(
            layer_name="memory_bias",
            influence_class=InfluenceClass.MEMORY_INFLUENCE,
            active=True,
            summary="test summary",
        )
        d = r.to_dict()
        for key in ("layer_name", "influence_class", "active", "authority_module", "summary", "detail"):
            assert key in d, f"Missing key: {key}"
        assert d["influence_class"] == "memory_influence"

    def test_C03_from_dict_round_trip(self):
        from core.runtime_decision_observability import RuntimeDecisionRecord, InfluenceClass
        r = RuntimeDecisionRecord(
            layer_name="task_semantic",
            influence_class=InfluenceClass.TASK_SEMANTIC_INFLUENCE,
            active=False,
            authority_module="core.agent.kernel",
            summary="no task hint",
            detail={"task_hint": None},
        )
        d = r.to_dict()
        r2 = RuntimeDecisionRecord.from_dict(d)
        assert r2.layer_name == r.layer_name
        assert r2.influence_class == r.influence_class
        assert r2.active == r.active
        assert r2.detail == r.detail

    def test_C04_from_dict_degrades_on_unknown_influence_class(self):
        from core.runtime_decision_observability import RuntimeDecisionRecord, InfluenceClass
        r = RuntimeDecisionRecord.from_dict({
            "layer_name": "unknown",
            "influence_class": "nonexistent_class",
            "active": True,
        })
        # Should default to SOFT_HINT
        assert r.influence_class == InfluenceClass.SOFT_HINT


# ─────────────────────────────────────────────────────────────────────────────
# Group D — RuntimeDecisionExplanation
# ─────────────────────────────────────────────────────────────────────────────


class TestGroupD_RuntimeDecisionExplanation:
    def test_D01_construction_with_defaults(self):
        from core.runtime_decision_observability import RuntimeDecisionExplanation
        e = RuntimeDecisionExplanation()
        assert e.execution_path == ""
        assert e.hard_gates == []
        assert e.soft_influences == []
        assert e.node_allowed is None

    def test_D02_to_dict_all_guaranteed_keys(self):
        from core.runtime_decision_observability import RuntimeDecisionExplanation
        e = RuntimeDecisionExplanation(execution_path="agent_execute")
        d = e.to_dict()
        for key in (
            "execution_path", "model_selected", "provider_selected",
            "model_selection_reason", "task_hint",
            "task_semantic_influenced_routing", "task_semantic_influenced_planner",
            "hard_gates", "soft_influences",
            "node_allowed", "node_denial_reasons",
            "activation_budget_active", "activation_budget_mode",
            "memory_bias_posture", "memory_influenced_planner",
            "cognitive_region", "execution_path_preference",
            "execution_path_preference_binding", "execution_path_preference_authority",
            "planner_strategy", "source_authority", "assembled_at",
        ):
            assert key in d, f"Missing key: {key}"

    def test_D03_from_dict_round_trip(self):
        from core.runtime_decision_observability import RuntimeDecisionExplanation
        e = RuntimeDecisionExplanation(
            execution_path="multimodal_route",
            model_selected="gpt-4o",
            task_hint="CODING",
        )
        d = e.to_dict()
        e2 = RuntimeDecisionExplanation.from_dict(d)
        assert e2.execution_path == e.execution_path
        assert e2.model_selected == e.model_selected
        assert e2.task_hint == e.task_hint

    def test_D04_has_hard_gate_false_when_no_gates(self):
        from core.runtime_decision_observability import RuntimeDecisionExplanation
        e = RuntimeDecisionExplanation()
        assert e.has_hard_gate is False

    def test_D05_has_hard_gate_true_when_active_hard_gate(self):
        from core.runtime_decision_observability import (
            RuntimeDecisionExplanation, RuntimeDecisionRecord, InfluenceClass
        )
        gate = RuntimeDecisionRecord(
            layer_name="governance",
            influence_class=InfluenceClass.HARD_GATE,
            active=True,
        )
        e = RuntimeDecisionExplanation(hard_gates=[gate])
        assert e.has_hard_gate is True

    def test_D06_active_influence_count_counts_active_soft(self):
        from core.runtime_decision_observability import (
            RuntimeDecisionExplanation, RuntimeDecisionRecord, InfluenceClass
        )
        r1 = RuntimeDecisionRecord("a", InfluenceClass.SOFT_HINT, active=True)
        r2 = RuntimeDecisionRecord("b", InfluenceClass.MEMORY_INFLUENCE, active=False)
        r3 = RuntimeDecisionRecord("c", InfluenceClass.TASK_SEMANTIC_INFLUENCE, active=True)
        e = RuntimeDecisionExplanation(soft_influences=[r1, r2, r3])
        assert e.active_influence_count == 2

    def test_D07_from_dict_degrades_on_partial_data(self):
        from core.runtime_decision_observability import RuntimeDecisionExplanation
        e = RuntimeDecisionExplanation.from_dict({})
        assert e.execution_path == ""
        assert e.hard_gates == []
        assert e.soft_influences == []


# ─────────────────────────────────────────────────────────────────────────────
# Group E — build_runtime_decision_explanation
# ─────────────────────────────────────────────────────────────────────────────


class TestGroupE_BuildExplanation:
    def test_E01_empty_call_returns_valid_explanation(self):
        from core.runtime_decision_observability import (
            build_runtime_decision_explanation, RuntimeDecisionExplanation
        )
        e = build_runtime_decision_explanation()
        assert isinstance(e, RuntimeDecisionExplanation)

    def test_E02_task_hint_reflected(self):
        from core.runtime_decision_observability import build_runtime_decision_explanation
        e = build_runtime_decision_explanation(task_hint="CODING")
        assert e.task_hint == "CODING"

    def test_E03_task_semantic_influenced_routing_reflected(self):
        from core.runtime_decision_observability import build_runtime_decision_explanation
        e = build_runtime_decision_explanation(
            task_hint="CODING",
            task_semantic_influenced_routing=True,
        )
        assert e.task_semantic_influenced_routing is True

    def test_E04_task_semantic_influenced_planner_reflected(self):
        from core.runtime_decision_observability import build_runtime_decision_explanation
        e = build_runtime_decision_explanation(
            task_hint="CODING",
            task_semantic_influenced_planner=True,
        )
        assert e.task_semantic_influenced_planner is True

    def test_E05_activation_budget_hint_reflected(self):
        from core.runtime_decision_observability import build_runtime_decision_explanation
        hint = _make_budget_hint(breadth_mode="broad", influenced=True)
        e = build_runtime_decision_explanation(activation_budget_hint=hint)
        assert e.activation_budget_active is True
        assert e.activation_budget_mode == "broad"

    def test_E06_memory_bias_hint_reflected(self):
        from core.runtime_decision_observability import build_runtime_decision_explanation
        hint = _make_memory_hint(posture="retrieval", influenced=True)
        e = build_runtime_decision_explanation(memory_bias_hint=hint)
        assert e.memory_bias_posture == "retrieval"
        assert e.memory_influenced_planner is True

    def test_E07_governance_denied_creates_hard_gate(self):
        from core.runtime_decision_observability import build_runtime_decision_explanation
        gov = _make_governance_dict(eligible=False, denial_reasons=["node_archived"])
        e = build_runtime_decision_explanation(governance_decision=gov)
        assert e.has_hard_gate is True
        assert e.node_allowed is False
        assert "node_archived" in e.node_denial_reasons

    def test_E08_governance_allowed_sets_node_allowed_true(self):
        from core.runtime_decision_observability import build_runtime_decision_explanation
        gov = _make_governance_dict(eligible=True)
        e = build_runtime_decision_explanation(governance_decision=gov)
        assert e.node_allowed is True
        assert e.has_hard_gate is False

    def test_E09_cognitive_hint_dict_reflected(self):
        from core.runtime_decision_observability import build_runtime_decision_explanation
        cog = _make_cognitive_hint_dict(region="MANIFEST", path_pref="direct")
        e = build_runtime_decision_explanation(cognitive_hint_dict=cog)
        assert e.cognitive_region == "MANIFEST"
        assert e.execution_path_preference == "direct"

    def test_E10_planner_strategy_reflected(self):
        from core.runtime_decision_observability import build_runtime_decision_explanation
        e = build_runtime_decision_explanation(planner_strategy="team_swarm")
        assert e.planner_strategy == "team_swarm"

    def test_E11_planner_strategy_driven_by_fields(self):
        from core.runtime_decision_observability import build_runtime_decision_explanation
        e = build_runtime_decision_explanation(
            planner_strategy="single_agent",
            activation_budget_hint=_make_budget_hint(influenced=True),
            memory_bias_hint=_make_memory_hint(influenced=False),
        )
        # Planner strategy record should be in soft_influences
        planner_rec = next(
            (r for r in e.soft_influences if r.layer_name == "planner_strategy"),
            None,
        )
        assert planner_rec is not None
        assert planner_rec.detail["driven_by_activation_budget"] is True
        assert planner_rec.detail["driven_by_memory_bias"] is False

    def test_E12_extra_records_appended_to_soft_influences(self):
        from core.runtime_decision_observability import (
            build_runtime_decision_explanation, RuntimeDecisionRecord, InfluenceClass
        )
        extra = RuntimeDecisionRecord(
            layer_name="custom_layer",
            influence_class=InfluenceClass.TOPOLOGY_INFLUENCE,
            active=True,
            summary="custom",
        )
        e = build_runtime_decision_explanation(extra_records=[extra])
        names = [r.layer_name for r in e.soft_influences]
        assert "custom_layer" in names

    def test_E13_extra_records_hard_gate_to_hard_gates(self):
        from core.runtime_decision_observability import (
            build_runtime_decision_explanation, RuntimeDecisionRecord, InfluenceClass
        )
        extra = RuntimeDecisionRecord(
            layer_name="custom_gate",
            influence_class=InfluenceClass.HARD_GATE,
            active=True,
        )
        e = build_runtime_decision_explanation(extra_records=[extra])
        names = [r.layer_name for r in e.hard_gates]
        assert "custom_gate" in names

    def test_E14_never_raises_on_error(self):
        from core.runtime_decision_observability import (
            build_runtime_decision_explanation, EMPTY_RUNTIME_DECISION_EXPLANATION
        )
        # Pass in garbage extra_records to trigger internal error
        e = build_runtime_decision_explanation(extra_records=["not_a_record"])  # type: ignore
        # Should either return a valid explanation or the empty sentinel
        from core.runtime_decision_observability import RuntimeDecisionExplanation
        assert isinstance(e, RuntimeDecisionExplanation)

    def test_E15_no_task_hint_no_task_semantic_influence(self):
        from core.runtime_decision_observability import build_runtime_decision_explanation
        e = build_runtime_decision_explanation(task_hint=None)
        assert e.task_hint is None
        assert e.task_semantic_influenced_routing is False
        # No task_semantic soft influence record expected when task_hint is None
        names = [r.layer_name for r in e.soft_influences]
        assert "task_semantic" not in names


# ─────────────────────────────────────────────────────────────────────────────
# Group F — build_runtime_decision_diagnostics
# ─────────────────────────────────────────────────────────────────────────────


class TestGroupF_BuildDiagnostics:
    _REQUIRED_KEYS = (
        "execution_path", "model_selected", "provider_selected",
        "model_selection_reason", "task_hint",
        "task_semantic_influenced_routing", "task_semantic_influenced_planner",
        "has_hard_gate", "hard_gate_count",
        "node_allowed", "node_denial_reasons",
        "activation_budget_active", "activation_budget_mode",
        "memory_bias_posture", "memory_influenced_planner",
        "cognitive_region", "execution_path_preference",
        "execution_path_preference_binding", "execution_path_preference_authority",
        "planner_strategy",
        "active_soft_influence_count",
        "influence_layers",
        "decision_signal_breakdown",
        "assembled_at",
        "observability_authority",
    )

    def test_F01_none_input_returns_fallback_with_all_keys(self):
        from core.runtime_decision_observability import build_runtime_decision_diagnostics
        d = build_runtime_decision_diagnostics(None)
        for key in self._REQUIRED_KEYS:
            assert key in d, f"Missing key: {key}"

    def test_F02_non_explanation_input_returns_fallback(self):
        from core.runtime_decision_observability import build_runtime_decision_diagnostics
        d = build_runtime_decision_diagnostics("not_an_explanation")  # type: ignore
        for key in self._REQUIRED_KEYS:
            assert key in d, f"Missing key: {key}"

    def test_F03_full_explanation_all_keys_present(self):
        from core.runtime_decision_observability import (
            build_runtime_decision_explanation, build_runtime_decision_diagnostics
        )
        e = build_runtime_decision_explanation(
            execution_path="agent_execute",
            task_hint="CODING",
            activation_budget_hint=_make_budget_hint(),
            memory_bias_hint=_make_memory_hint(),
        )
        d = build_runtime_decision_diagnostics(e)
        for key in self._REQUIRED_KEYS:
            assert key in d, f"Missing key: {key}"

    def test_F04_has_hard_gate_reflects_explanation(self):
        from core.runtime_decision_observability import (
            build_runtime_decision_explanation, build_runtime_decision_diagnostics
        )
        e = build_runtime_decision_explanation(
            governance_decision=_make_governance_dict(eligible=False)
        )
        d = build_runtime_decision_diagnostics(e)
        assert d["has_hard_gate"] is True

    def test_F05_hard_gate_count(self):
        from core.runtime_decision_observability import (
            build_runtime_decision_explanation, build_runtime_decision_diagnostics
        )
        e = build_runtime_decision_explanation(
            governance_decision=_make_governance_dict(eligible=False)
        )
        d = build_runtime_decision_diagnostics(e)
        assert d["hard_gate_count"] >= 1

    def test_F05b_execution_path_preference_marked_non_binding(self):
        from core.runtime_decision_observability import (
            build_runtime_decision_explanation, build_runtime_decision_diagnostics
        )
        e = build_runtime_decision_explanation(
            cognitive_hint_dict=_make_cognitive_hint_dict(region="LIMINAL", path_pref="planning")
        )
        d = build_runtime_decision_diagnostics(e)
        assert d["execution_path_preference_binding"] == "advisory_only_non_binding"
        assert d["execution_path_preference_authority"] == "soft_hint_non_binding"

    def test_F06_active_soft_influence_count(self):
        from core.runtime_decision_observability import (
            build_runtime_decision_explanation, build_runtime_decision_diagnostics
        )
        e = build_runtime_decision_explanation(
            activation_budget_hint=_make_budget_hint(influenced=True),
            memory_bias_hint=_make_memory_hint(influenced=True),
        )
        d = build_runtime_decision_diagnostics(e)
        assert d["active_soft_influence_count"] >= 2

    def test_F07_influence_layers_lists_all_records(self):
        from core.runtime_decision_observability import (
            build_runtime_decision_explanation, build_runtime_decision_diagnostics
        )
        e = build_runtime_decision_explanation(
            task_hint="REASONING",
            task_semantic_influenced_routing=True,
            activation_budget_hint=_make_budget_hint(),
        )
        d = build_runtime_decision_diagnostics(e)
        assert isinstance(d["influence_layers"], list)
        assert len(d["influence_layers"]) >= 1

    def test_F08_include_detail_true_adds_detail_key(self):
        from core.runtime_decision_observability import (
            build_runtime_decision_explanation, build_runtime_decision_diagnostics
        )
        e = build_runtime_decision_explanation(
            activation_budget_hint=_make_budget_hint(),
        )
        d = build_runtime_decision_diagnostics(e, include_detail=True)
        for layer in d["influence_layers"]:
            assert "detail" in layer

    def test_F09_include_detail_false_omits_detail(self):
        from core.runtime_decision_observability import (
            build_runtime_decision_explanation, build_runtime_decision_diagnostics
        )
        e = build_runtime_decision_explanation(
            activation_budget_hint=_make_budget_hint(),
        )
        d = build_runtime_decision_diagnostics(e, include_detail=False)
        for layer in d["influence_layers"]:
            assert "detail" not in layer

    def test_F10_observability_authority_key_present(self):
        from core.runtime_decision_observability import build_runtime_decision_diagnostics
        d = build_runtime_decision_diagnostics(None)
        assert "observability_authority" in d
        assert d["observability_authority"]

    def test_F11_never_raises_on_bad_input(self):
        from core.runtime_decision_observability import build_runtime_decision_diagnostics
        for bad in (None, "string", 42, {}, []):
            d = build_runtime_decision_diagnostics(bad)  # type: ignore
            assert isinstance(d, dict)

    def test_F12_signal_breakdown_distinguishes_hard_soft_and_metadata(self):
        from core.runtime_decision_observability import (
            build_runtime_decision_explanation, build_runtime_decision_diagnostics
        )

        e = build_runtime_decision_explanation(
            governance_decision=_make_governance_dict(eligible=False, denial_reasons=["blocked"]),
            activation_budget_hint=_make_budget_hint(influenced=True),
        )
        d = build_runtime_decision_diagnostics(e)
        breakdown = d["decision_signal_breakdown"]
        assert "invocation_governance" in breakdown["hard_authority_layers"]
        assert "activation_budget" in breakdown["soft_influence_layers"]
        assert "execution_path" in breakdown["metadata_only_fields"]


# ─────────────────────────────────────────────────────────────────────────────
# Group G — enrich_multimodal_route_with_observability
# ─────────────────────────────────────────────────────────────────────────────


class TestGroupG_EnrichMultimodalRoute:
    def test_G01_adds_pr20_task_hint(self):
        from core.runtime_decision_observability import enrich_multimodal_route_with_observability
        route = {"route_type": "text_only", "is_native_multimodal": False}
        enrich_multimodal_route_with_observability(route, task_hint="CODING")
        assert route["pr20_task_hint"] == "CODING"

    def test_G02_adds_pr20_task_semantic_influenced_routing(self):
        from core.runtime_decision_observability import enrich_multimodal_route_with_observability
        route = {"route_type": "native_multimodal"}
        enrich_multimodal_route_with_observability(route, task_semantic_influenced=True)
        assert route["pr20_task_semantic_influenced_routing"] is True

    def test_G03_adds_pr20_observability_source(self):
        from core.runtime_decision_observability import enrich_multimodal_route_with_observability
        route = {}
        enrich_multimodal_route_with_observability(route)
        assert "pr20_observability_source" in route

    def test_G04_original_route_type_preserved(self):
        from core.runtime_decision_observability import enrich_multimodal_route_with_observability
        route = {"route_type": "partial_multimodal", "model": "gpt-4o"}
        enrich_multimodal_route_with_observability(route, task_hint="CREATIVE")
        assert route["route_type"] == "partial_multimodal"
        assert route["model"] == "gpt-4o"

    def test_G05_never_raises_on_none_task_hint(self):
        from core.runtime_decision_observability import enrich_multimodal_route_with_observability
        route = {}
        enrich_multimodal_route_with_observability(route, task_hint=None)
        assert route["pr20_task_hint"] is None


# ─────────────────────────────────────────────────────────────────────────────
# Group H — enrich_governance_decision_with_observability
# ─────────────────────────────────────────────────────────────────────────────


class TestGroupH_EnrichGovernanceDecision:
    def test_H01_adds_pr20_observability_context(self):
        from core.runtime_decision_observability import enrich_governance_decision_with_observability
        d = {"node_id": "test_node"}
        enrich_governance_decision_with_observability(d)
        assert "pr20_observability_context" in d

    def test_H02_pr20_context_has_task_hint(self):
        from core.runtime_decision_observability import enrich_governance_decision_with_observability
        d = {}
        enrich_governance_decision_with_observability(d, task_hint="CODING")
        assert d["pr20_observability_context"]["task_hint"] == "CODING"

    def test_H03_pr20_context_has_activation_budget_mode(self):
        from core.runtime_decision_observability import enrich_governance_decision_with_observability
        d = {}
        enrich_governance_decision_with_observability(
            d, activation_budget_hint=_make_budget_hint(breadth_mode="broad")
        )
        assert d["pr20_observability_context"]["activation_budget_mode"] == "broad"

    def test_H04_pr20_context_has_memory_bias_posture(self):
        from core.runtime_decision_observability import enrich_governance_decision_with_observability
        d = {}
        enrich_governance_decision_with_observability(
            d, memory_bias_hint=_make_memory_hint(posture="retrieval")
        )
        assert d["pr20_observability_context"]["memory_bias_posture"] == "retrieval"

    def test_H05_observability_pr20_active_true(self):
        from core.runtime_decision_observability import enrich_governance_decision_with_observability
        d = {}
        enrich_governance_decision_with_observability(d)
        assert d["pr20_observability_context"]["observability_pr20_active"] is True

    def test_H06_never_raises_on_none_inputs(self):
        from core.runtime_decision_observability import enrich_governance_decision_with_observability
        d = {}
        enrich_governance_decision_with_observability(
            d,
            activation_budget_hint=None,
            memory_bias_hint=None,
            task_hint=None,
        )
        assert "pr20_observability_context" in d


# ─────────────────────────────────────────────────────────────────────────────
# Group I — Governance wiring
# ─────────────────────────────────────────────────────────────────────────────


class TestGroupI_GovernanceWiring:
    def test_I01_evaluate_invocation_governance_accepts_memory_bias(self):
        from core.node_invocation_governance import evaluate_invocation_governance
        import inspect
        sig = inspect.signature(evaluate_invocation_governance)
        assert "memory_bias" in sig.parameters

    def test_I02_evaluate_invocation_governance_accepts_task_hint(self):
        from core.node_invocation_governance import evaluate_invocation_governance
        import inspect
        sig = inspect.signature(evaluate_invocation_governance)
        assert "task_hint" in sig.parameters

    def test_I03_no_crash_with_none_memory_bias_and_task_hint(self):
        from core.node_invocation_governance import evaluate_invocation_governance
        # Should not raise even with both None (unregistered node path)
        result = evaluate_invocation_governance(
            "nonexistent_node_xyz",
            memory_bias=None,
            task_hint=None,
        )
        assert result is not None
        assert hasattr(result, "invocation_allowed")

    def test_I04_governance_decision_structure_unchanged(self):
        from core.node_invocation_governance import evaluate_invocation_governance
        result = evaluate_invocation_governance("some_node_abc")
        d = result.to_dict()
        # PR-11 fields must still be present
        assert "invocation_allowed" in d
        assert "denial_reasons" in d
        assert "diagnostic_context" in d
        assert "governance_status" in d


# ─────────────────────────────────────────────────────────────────────────────
# Group J — Kernel wiring
# ─────────────────────────────────────────────────────────────────────────────


class TestGroupJ_KernelWiring:
    def test_J01_kernel_response_has_runtime_decision_explanation_field(self):
        try:
            from core.agent.kernel import KernelResponse
            import inspect
            # Check field exists in class fields (pydantic model)
            fields = KernelResponse.model_fields
            assert "runtime_decision_explanation" in fields
        except ImportError:
            pytest.skip("kernel.py not importable (pydantic missing)")

    def test_J02_to_api_dict_includes_runtime_decision_explanation_key(self):
        try:
            from core.agent.kernel import KernelResponse
            with open("core/agent/kernel.py") as f:
                content = f.read()
            assert '"runtime_decision_explanation"' in content
        except ImportError:
            pytest.skip("kernel.py not importable (pydantic missing)")


# ─────────────────────────────────────────────────────────────────────────────
# Group K — Backward compatibility
# ─────────────────────────────────────────────────────────────────────────────


class TestGroupK_BackwardCompatibility:
    def test_K01_empty_call_to_build_explanation_works(self):
        from core.runtime_decision_observability import (
            build_runtime_decision_explanation, RuntimeDecisionExplanation
        )
        e = build_runtime_decision_explanation()
        assert isinstance(e, RuntimeDecisionExplanation)

    def test_K02_governance_without_new_params_works(self):
        from core.node_invocation_governance import evaluate_invocation_governance
        # Old-style call without memory_bias / task_hint
        result = evaluate_invocation_governance("nonexistent_compat_node")
        assert result is not None

    def test_K03_build_explanation_never_raises_on_garbage(self):
        from core.runtime_decision_observability import (
            build_runtime_decision_explanation, RuntimeDecisionExplanation
        )
        for garbage in (
            {"activation_budget_hint": "string_not_dict"},
            {"memory_bias_hint": 42},
            {"governance_decision": "bad"},
        ):
            e = build_runtime_decision_explanation(**garbage)  # type: ignore
            assert isinstance(e, RuntimeDecisionExplanation)

    def test_K04_build_diagnostics_never_raises_on_garbage(self):
        from core.runtime_decision_observability import build_runtime_decision_diagnostics
        for garbage in (None, "bad", 0, [], {}):
            d = build_runtime_decision_diagnostics(garbage)  # type: ignore
            assert isinstance(d, dict)


# ─────────────────────────────────────────────────────────────────────────────
# Group L — Influence hierarchy / authority assertions
# ─────────────────────────────────────────────────────────────────────────────


class TestGroupL_InfluenceHierarchy:
    def test_L01_memory_novelty_does_not_create_hard_gate(self):
        from core.runtime_decision_observability import build_runtime_decision_explanation, InfluenceClass
        hint = _make_memory_hint(posture="novelty", influenced=True)
        e = build_runtime_decision_explanation(memory_bias_hint=hint)
        # Memory influence should be in soft_influences, NOT in hard_gates
        mem_hard = [r for r in e.hard_gates if r.layer_name == "memory_bias"]
        assert len(mem_hard) == 0
        mem_soft = [r for r in e.soft_influences if r.layer_name == "memory_bias"]
        assert len(mem_soft) == 1
        assert mem_soft[0].influence_class == InfluenceClass.MEMORY_INFLUENCE

    def test_L02_governance_denial_creates_hard_gate_record(self):
        from core.runtime_decision_observability import build_runtime_decision_explanation, InfluenceClass
        gov = _make_governance_dict(eligible=False, denial_reasons=["archived"])
        e = build_runtime_decision_explanation(governance_decision=gov)
        gov_gates = [r for r in e.hard_gates if r.layer_name == "invocation_governance"]
        assert len(gov_gates) == 1
        assert gov_gates[0].influence_class == InfluenceClass.HARD_GATE
        assert gov_gates[0].active is True

    def test_L03_task_semantic_does_not_elevate_to_hard_gate(self):
        from core.runtime_decision_observability import build_runtime_decision_explanation, InfluenceClass
        e = build_runtime_decision_explanation(
            task_hint="CODING",
            task_semantic_influenced_routing=True,
        )
        task_hard = [r for r in e.hard_gates if r.layer_name == "task_semantic"]
        assert len(task_hard) == 0
        task_soft = [r for r in e.soft_influences if r.layer_name == "task_semantic"]
        assert len(task_soft) == 1
        assert task_soft[0].influence_class == InfluenceClass.TASK_SEMANTIC_INFLUENCE

    def test_L04_execution_posture_does_not_elevate_to_hard_gate(self):
        from core.runtime_decision_observability import build_runtime_decision_explanation, InfluenceClass
        hint = _make_budget_hint(influenced=True)
        e = build_runtime_decision_explanation(activation_budget_hint=hint)
        budget_hard = [r for r in e.hard_gates if r.layer_name == "activation_budget"]
        assert len(budget_hard) == 0
        budget_soft = [r for r in e.soft_influences if r.layer_name == "activation_budget"]
        assert len(budget_soft) == 1
        assert budget_soft[0].influence_class == InfluenceClass.EXECUTION_POSTURE

    def test_L05_multiple_soft_influences_stack(self):
        from core.runtime_decision_observability import build_runtime_decision_explanation
        e = build_runtime_decision_explanation(
            task_hint="REASONING",
            task_semantic_influenced_routing=True,
            activation_budget_hint=_make_budget_hint(influenced=True),
            memory_bias_hint=_make_memory_hint(influenced=True),
            cognitive_hint_dict=_make_cognitive_hint_dict(),
            planner_strategy="single_agent",
        )
        # Should have: task_semantic + activation_budget + memory_bias + cognitive + planner = 5
        assert len(e.soft_influences) >= 4
        names = {r.layer_name for r in e.soft_influences}
        assert "task_semantic" in names
        assert "activation_budget" in names
        assert "memory_bias" in names
        assert "cognitive_execution_policy" in names
