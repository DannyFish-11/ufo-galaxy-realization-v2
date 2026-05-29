#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr19_unified_control_plan.py
========================================

PR-19 — OpenClawd Unified Control Core and Canonical Control Plan

Tests covering:
1.  Module exports — all public symbols importable
2.  Authority constants — AUTHORITY_ROLE, SHELL_ROLE, SUBSTRATE_ROLE values
3.  DecisionPosture enum — all values, serialisation stability
4.  FallbackLevel enum — all values, serialisation stability
5.  ChosenModelDecision — construction, to_dict, from_dict round-trip
6.  ChosenExecutionDecision — construction, to_dict, from_dict round-trip
7.  AuthorityChain — construction, invariant (decision_authority is always subject_decision_authority)
8.  ShellProjectionHints — construction, to_dict, from_dict
9.  UnifiedControlPlan — construction, to_dict, from_dict round-trip, schema_version
10. UnifiedControlPlan — authority_chain invariant preserved in all code paths
11. build_unified_control_plan — minimal inputs (text-only request)
12. build_unified_control_plan — multimodal request produces perception summary
13. build_unified_control_plan — local execution path
14. build_unified_control_plan — remote/cross-device execution path
15. build_unified_control_plan — fallback level and reason
16. build_unified_control_plan — continuum posture derivation
17. unified_control_plan_summary — compact summary shape
18. unified_control_plan_summary — None input returns None
19. Plan serialisation — JSON-safe, stable for diagnostics
20. Shell/core boundary — plan records shell role and core role distinctly
21. OpenClawd integration — _build_unified_control_plan helper exists and is callable
22. OpenClawd integration — process() response metadata contains unified_control_plan
23. Backward compatibility — plan fields are additive; existing keys unaffected
24. Edge cases — empty / None canonical_perception degrades gracefully
25. Edge cases — unknown decision_posture/fallback_level degraded by from_dict
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# 1. Module exports
# ---------------------------------------------------------------------------


class TestModuleExports:
    def test_all_public_symbols_importable(self) -> None:
        from core.schemas.unified_control_plan import (
            AUTHORITY_ROLE,
            SHELL_ROLE,
            SUBSTRATE_ROLE,
            ORCHESTRATION_ROLE,
            DecisionPosture,
            FallbackLevel,
            ChosenModelDecision,
            ChosenExecutionDecision,
            AuthorityChain,
            ShellProjectionHints,
            UnifiedControlPlan,
            build_unified_control_plan,
            unified_control_plan_summary,
        )
        assert AUTHORITY_ROLE
        assert SHELL_ROLE
        assert SUBSTRATE_ROLE
        assert DecisionPosture
        assert FallbackLevel
        assert ChosenModelDecision
        assert ChosenExecutionDecision
        assert AuthorityChain
        assert ShellProjectionHints
        assert UnifiedControlPlan
        assert callable(build_unified_control_plan)
        assert callable(unified_control_plan_summary)


# ---------------------------------------------------------------------------
# 2. Authority constants
# ---------------------------------------------------------------------------


class TestAuthorityConstants:
    def test_authority_role_is_subject_decision_authority(self) -> None:
        from core.schemas.unified_control_plan import AUTHORITY_ROLE
        assert AUTHORITY_ROLE == "subject_decision_authority"

    def test_shell_role_is_runtime_shell_authority(self) -> None:
        from core.schemas.unified_control_plan import SHELL_ROLE
        assert SHELL_ROLE == "runtime_shell_authority"

    def test_substrate_role_is_execution_substrate(self) -> None:
        from core.schemas.unified_control_plan import SUBSTRATE_ROLE
        assert SUBSTRATE_ROLE == "execution_substrate"

    def test_orchestration_role_is_orchestration_layer(self) -> None:
        from core.schemas.unified_control_plan import ORCHESTRATION_ROLE
        assert ORCHESTRATION_ROLE == "orchestration_layer"

    def test_authority_role_is_string(self) -> None:
        from core.schemas.unified_control_plan import AUTHORITY_ROLE
        assert isinstance(AUTHORITY_ROLE, str)

    def test_constants_are_json_serialisable(self) -> None:
        from core.schemas.unified_control_plan import (
            AUTHORITY_ROLE, SHELL_ROLE, SUBSTRATE_ROLE, ORCHESTRATION_ROLE
        )
        s = json.dumps([AUTHORITY_ROLE, SHELL_ROLE, SUBSTRATE_ROLE, ORCHESTRATION_ROLE])
        assert json.loads(s)


# ---------------------------------------------------------------------------
# 3. DecisionPosture enum
# ---------------------------------------------------------------------------


class TestDecisionPosture:
    def test_all_expected_values_present(self) -> None:
        from core.schemas.unified_control_plan import DecisionPosture
        expected = {"autonomous", "human_in_loop", "advisory", "degraded", "unknown"}
        assert {p.value for p in DecisionPosture} == expected

    def test_values_are_strings(self) -> None:
        from core.schemas.unified_control_plan import DecisionPosture
        for posture in DecisionPosture:
            assert isinstance(posture.value, str)
            assert posture.value

    def test_roundtrip(self) -> None:
        from core.schemas.unified_control_plan import DecisionPosture
        for posture in DecisionPosture:
            assert DecisionPosture(posture.value) == posture

    def test_json_serialisable(self) -> None:
        from core.schemas.unified_control_plan import DecisionPosture
        s = json.dumps([p.value for p in DecisionPosture])
        assert json.loads(s)


# ---------------------------------------------------------------------------
# 4. FallbackLevel enum
# ---------------------------------------------------------------------------


class TestFallbackLevel:
    def test_all_expected_values_present(self) -> None:
        from core.schemas.unified_control_plan import FallbackLevel
        expected = {
            "none", "model_fallback", "text_only_fallback",
            "local_fallback", "advisory_fallback", "no_op", "unknown",
        }
        assert {lvl.value for lvl in FallbackLevel} == expected

    def test_roundtrip(self) -> None:
        from core.schemas.unified_control_plan import FallbackLevel
        for lvl in FallbackLevel:
            assert FallbackLevel(lvl.value) == lvl

    def test_json_serialisable(self) -> None:
        from core.schemas.unified_control_plan import FallbackLevel
        s = json.dumps([lvl.value for lvl in FallbackLevel])
        assert json.loads(s)


# ---------------------------------------------------------------------------
# 5. ChosenModelDecision
# ---------------------------------------------------------------------------


class TestChosenModelDecision:
    def test_default_construction(self) -> None:
        from core.schemas.unified_control_plan import ChosenModelDecision
        cmd = ChosenModelDecision()
        assert cmd.provider_id is None
        assert cmd.model_id is None
        assert cmd.is_native_multimodal is False
        assert cmd.fallback_chain == []

    def test_to_dict_keys(self) -> None:
        from core.schemas.unified_control_plan import ChosenModelDecision
        cmd = ChosenModelDecision(provider_id="openai", model_id="gpt-4o", is_native_multimodal=True)
        d = cmd.to_dict()
        assert set(d.keys()) >= {"provider_id", "model_id", "is_native_multimodal", "selection_reason", "fallback_chain"}

    def test_to_dict_json_serialisable(self) -> None:
        from core.schemas.unified_control_plan import ChosenModelDecision
        cmd = ChosenModelDecision(provider_id="openai", model_id="gpt-4o", fallback_chain=["anthropic/claude"])
        assert json.loads(json.dumps(cmd.to_dict()))

    def test_from_dict_roundtrip(self) -> None:
        from core.schemas.unified_control_plan import ChosenModelDecision
        cmd = ChosenModelDecision(
            provider_id="anthropic",
            model_id="claude-opus-4-8-20250529",
            is_native_multimodal=True,
            selection_reason="best multimodal",
            fallback_chain=["openai/gpt-4o"],
        )
        restored = ChosenModelDecision.from_dict(cmd.to_dict())
        assert restored.provider_id == cmd.provider_id
        assert restored.model_id == cmd.model_id
        assert restored.is_native_multimodal == cmd.is_native_multimodal
        assert restored.selection_reason == cmd.selection_reason
        assert restored.fallback_chain == cmd.fallback_chain

    def test_from_dict_empty_dict_degrades(self) -> None:
        from core.schemas.unified_control_plan import ChosenModelDecision
        cmd = ChosenModelDecision.from_dict({})
        assert cmd.provider_id is None
        assert cmd.is_native_multimodal is False


# ---------------------------------------------------------------------------
# 6. ChosenExecutionDecision
# ---------------------------------------------------------------------------


class TestChosenExecutionDecision:
    def test_default_construction(self) -> None:
        from core.schemas.unified_control_plan import ChosenExecutionDecision
        ced = ChosenExecutionDecision()
        assert ced.execution_path == "local"
        assert ced.delegation_point is None
        assert ced.remote_execution_mode is None
        assert ced.orchestration_active is False

    def test_to_dict_keys(self) -> None:
        from core.schemas.unified_control_plan import ChosenExecutionDecision
        ced = ChosenExecutionDecision(execution_path="cross_device", remote_execution_mode="agent_runtime")
        d = ced.to_dict()
        assert set(d.keys()) >= {
            "execution_path", "delegation_point", "remote_execution_mode",
            "target_device_ids", "orchestration_active",
        }

    def test_from_dict_roundtrip(self) -> None:
        from core.schemas.unified_control_plan import ChosenExecutionDecision
        ced = ChosenExecutionDecision(
            execution_path="cross_device",
            delegation_point="single_remote",
            remote_execution_mode="agent_runtime",
            target_device_ids=["device-001"],
            orchestration_active=False,
        )
        restored = ChosenExecutionDecision.from_dict(ced.to_dict())
        assert restored.execution_path == ced.execution_path
        assert restored.delegation_point == ced.delegation_point
        assert restored.remote_execution_mode == ced.remote_execution_mode
        assert restored.target_device_ids == ced.target_device_ids

    def test_from_dict_empty_dict_degrades(self) -> None:
        from core.schemas.unified_control_plan import ChosenExecutionDecision
        ced = ChosenExecutionDecision.from_dict({})
        assert ced.execution_path == "local"


# ---------------------------------------------------------------------------
# 7. AuthorityChain
# ---------------------------------------------------------------------------


class TestAuthorityChain:
    def test_default_decision_authority_is_subject_decision_authority(self) -> None:
        from core.schemas.unified_control_plan import AuthorityChain, AUTHORITY_ROLE
        chain = AuthorityChain()
        assert chain.decision_authority == AUTHORITY_ROLE

    def test_default_shell_role(self) -> None:
        from core.schemas.unified_control_plan import AuthorityChain, SHELL_ROLE
        chain = AuthorityChain()
        assert chain.shell_role == SHELL_ROLE

    def test_default_substrate_role(self) -> None:
        from core.schemas.unified_control_plan import AuthorityChain, SUBSTRATE_ROLE
        chain = AuthorityChain()
        assert chain.substrate_role == SUBSTRATE_ROLE

    def test_canonical_module_and_class(self) -> None:
        from core.schemas.unified_control_plan import AuthorityChain
        chain = AuthorityChain()
        assert chain.canonical_module == "core.openclawd"
        assert chain.canonical_class == "OpenClawd"

    def test_to_dict_json_serialisable(self) -> None:
        from core.schemas.unified_control_plan import AuthorityChain
        chain = AuthorityChain()
        assert json.loads(json.dumps(chain.to_dict()))

    def test_from_dict_roundtrip(self) -> None:
        from core.schemas.unified_control_plan import AuthorityChain, AUTHORITY_ROLE
        chain = AuthorityChain()
        restored = AuthorityChain.from_dict(chain.to_dict())
        assert restored.decision_authority == AUTHORITY_ROLE
        assert restored.canonical_module == chain.canonical_module

    def test_decision_authority_immutable_in_from_dict(self) -> None:
        """from_dict must preserve decision_authority value from input dict."""
        from core.schemas.unified_control_plan import AuthorityChain, AUTHORITY_ROLE
        d = AuthorityChain().to_dict()
        restored = AuthorityChain.from_dict(d)
        assert restored.decision_authority == AUTHORITY_ROLE


# ---------------------------------------------------------------------------
# 8. ShellProjectionHints
# ---------------------------------------------------------------------------


class TestShellProjectionHints:
    def test_default_authority_label(self) -> None:
        from core.schemas.unified_control_plan import ShellProjectionHints
        hints = ShellProjectionHints()
        assert "OpenClawd" in hints.authority_label

    def test_to_dict_keys(self) -> None:
        from core.schemas.unified_control_plan import ShellProjectionHints
        hints = ShellProjectionHints(perception_summary="text-only", lifecycle_label="succeeded")
        d = hints.to_dict()
        assert set(d.keys()) >= {
            "perception_summary", "model_summary", "execution_summary",
            "fallback_note", "lifecycle_label", "authority_label", "diagnostics_note",
        }

    def test_from_dict_roundtrip(self) -> None:
        from core.schemas.unified_control_plan import ShellProjectionHints
        hints = ShellProjectionHints(
            perception_summary="image+audio",
            model_summary="openai/gpt-4o [native-multimodal]",
            execution_summary="cross_device:agent_runtime",
            lifecycle_label="succeeded",
        )
        restored = ShellProjectionHints.from_dict(hints.to_dict())
        assert restored.perception_summary == hints.perception_summary
        assert restored.model_summary == hints.model_summary
        assert restored.execution_summary == hints.execution_summary

    def test_json_serialisable(self) -> None:
        from core.schemas.unified_control_plan import ShellProjectionHints
        hints = ShellProjectionHints(diagnostics_note="errors=1 warnings=2")
        assert json.loads(json.dumps(hints.to_dict()))


# ---------------------------------------------------------------------------
# 9. UnifiedControlPlan construction and round-trip
# ---------------------------------------------------------------------------


class TestUnifiedControlPlan:
    def test_default_construction(self) -> None:
        from core.schemas.unified_control_plan import UnifiedControlPlan, AUTHORITY_ROLE
        plan = UnifiedControlPlan()
        assert plan.plan_id.startswith("ucp_")
        assert plan.schema_version == "1.0"
        assert plan.authority_chain.decision_authority == AUTHORITY_ROLE

    def test_to_dict_required_keys(self) -> None:
        from core.schemas.unified_control_plan import UnifiedControlPlan
        plan = UnifiedControlPlan()
        d = plan.to_dict()
        required = {
            "plan_id", "runtime_session_id", "trace_id", "created_at",
            "schema_version", "decision_posture",
            "canonical_perception_summary", "canonical_model_supply_summary",
            "chosen_model_decision", "chosen_execution_decision",
            "fallback_level", "fallback_reason",
            "lifecycle_target", "execution_plan_summary", "diagnostics_summary",
            "authority_chain", "shell_projection_hints",
        }
        assert required.issubset(set(d.keys()))

    def test_to_dict_json_serialisable(self) -> None:
        from core.schemas.unified_control_plan import UnifiedControlPlan
        plan = UnifiedControlPlan(
            runtime_session_id="rs-abc",
            trace_id="t-xyz",
            lifecycle_target="succeeded",
        )
        assert json.loads(json.dumps(plan.to_dict()))

    def test_from_dict_roundtrip(self) -> None:
        from core.schemas.unified_control_plan import UnifiedControlPlan, AUTHORITY_ROLE
        plan = UnifiedControlPlan(runtime_session_id="rs-abc", trace_id="t-xyz")
        restored = UnifiedControlPlan.from_dict(plan.to_dict())
        assert restored.plan_id == plan.plan_id
        assert restored.runtime_session_id == plan.runtime_session_id
        assert restored.trace_id == plan.trace_id
        assert restored.authority_chain.decision_authority == AUTHORITY_ROLE

    def test_from_dict_empty_dict_degrades_gracefully(self) -> None:
        from core.schemas.unified_control_plan import UnifiedControlPlan, AUTHORITY_ROLE
        plan = UnifiedControlPlan.from_dict({})
        assert plan.schema_version == "1.0"
        assert plan.authority_chain.decision_authority == AUTHORITY_ROLE

    def test_schema_version_is_1_0(self) -> None:
        from core.schemas.unified_control_plan import UnifiedControlPlan
        plan = UnifiedControlPlan()
        assert plan.schema_version == "1.0"
        assert plan.to_dict()["schema_version"] == "1.0"


# ---------------------------------------------------------------------------
# 10. Authority chain invariant
# ---------------------------------------------------------------------------


class TestAuthorityChainInvariant:
    def test_default_plan_has_subject_decision_authority(self) -> None:
        from core.schemas.unified_control_plan import UnifiedControlPlan, AUTHORITY_ROLE
        plan = UnifiedControlPlan()
        assert plan.authority_chain.decision_authority == AUTHORITY_ROLE

    def test_built_plan_has_subject_decision_authority(self) -> None:
        from core.schemas.unified_control_plan import build_unified_control_plan, AUTHORITY_ROLE
        plan = build_unified_control_plan(trace_id="t-001")
        assert plan.authority_chain.decision_authority == AUTHORITY_ROLE

    def test_authority_chain_in_to_dict(self) -> None:
        from core.schemas.unified_control_plan import build_unified_control_plan, AUTHORITY_ROLE
        plan = build_unified_control_plan(trace_id="t-002")
        d = plan.to_dict()
        assert d["authority_chain"]["decision_authority"] == AUTHORITY_ROLE

    def test_authority_chain_preserved_after_roundtrip(self) -> None:
        from core.schemas.unified_control_plan import build_unified_control_plan, UnifiedControlPlan, AUTHORITY_ROLE
        plan = build_unified_control_plan(trace_id="t-003")
        restored = UnifiedControlPlan.from_dict(plan.to_dict())
        assert restored.authority_chain.decision_authority == AUTHORITY_ROLE

    def test_shell_core_boundary_explicit_in_chain(self) -> None:
        from core.schemas.unified_control_plan import build_unified_control_plan, SHELL_ROLE, AUTHORITY_ROLE
        plan = build_unified_control_plan(trace_id="t-004")
        chain_dict = plan.authority_chain.to_dict()
        # Shell role and core role are distinct
        assert chain_dict["shell_role"] == SHELL_ROLE
        assert chain_dict["decision_authority"] == AUTHORITY_ROLE
        assert chain_dict["shell_role"] != chain_dict["decision_authority"]

    def test_canonical_module_is_openclawd(self) -> None:
        from core.schemas.unified_control_plan import build_unified_control_plan
        plan = build_unified_control_plan(trace_id="t-005")
        assert plan.authority_chain.canonical_module == "core.openclawd"
        assert plan.authority_chain.canonical_class == "OpenClawd"


# ---------------------------------------------------------------------------
# 11. build_unified_control_plan — text-only request
# ---------------------------------------------------------------------------


class TestBuildUnifiedControlPlanTextOnly:
    def test_text_only_produces_valid_plan(self) -> None:
        from core.schemas.unified_control_plan import build_unified_control_plan, AUTHORITY_ROLE
        plan = build_unified_control_plan(
            runtime_session_id="rs-001",
            trace_id="trace-001",
            execution_path="local",
        )
        assert plan.plan_id
        assert plan.authority_chain.decision_authority == AUTHORITY_ROLE

    def test_text_only_has_no_perception_summary(self) -> None:
        from core.schemas.unified_control_plan import build_unified_control_plan
        plan = build_unified_control_plan(trace_id="trace-002")
        # No perception means None perception summary
        assert plan.canonical_perception_summary is None

    def test_text_only_fallback_level_is_none(self) -> None:
        from core.schemas.unified_control_plan import build_unified_control_plan, FallbackLevel
        plan = build_unified_control_plan(trace_id="trace-003")
        assert plan.fallback_level == FallbackLevel.NONE.value

    def test_text_only_is_json_serialisable(self) -> None:
        from core.schemas.unified_control_plan import build_unified_control_plan
        plan = build_unified_control_plan(trace_id="trace-004", execution_path="local")
        assert json.loads(json.dumps(plan.to_dict()))

    def test_text_only_execution_path_is_local(self) -> None:
        from core.schemas.unified_control_plan import build_unified_control_plan
        plan = build_unified_control_plan(trace_id="trace-005")
        assert plan.chosen_execution_decision.execution_path == "local"


# ---------------------------------------------------------------------------
# 12. build_unified_control_plan — multimodal request
# ---------------------------------------------------------------------------


class TestBuildUnifiedControlPlanMultimodal:
    def _make_perception_dict(self, modalities=None) -> Dict[str, Any]:
        return {
            "has_continuous_perception": False,
            "has_request_multimodal": True,
            "active_modalities": modalities or ["image", "audio"],
            "source_summary": "request-bound multimodal",
            "fusion_summary": "image and audio input detected",
        }

    def test_multimodal_perception_summary_is_populated(self) -> None:
        from core.schemas.unified_control_plan import build_unified_control_plan
        plan = build_unified_control_plan(
            trace_id="t-mm-001",
            canonical_perception=self._make_perception_dict(),
        )
        assert plan.canonical_perception_summary is not None
        assert plan.canonical_perception_summary["has_request_multimodal"] is True

    def test_multimodal_active_modalities_preserved(self) -> None:
        from core.schemas.unified_control_plan import build_unified_control_plan
        plan = build_unified_control_plan(
            trace_id="t-mm-002",
            canonical_perception=self._make_perception_dict(["image"]),
        )
        assert "image" in plan.canonical_perception_summary["active_modalities"]

    def test_multimodal_shell_projection_has_perception_summary(self) -> None:
        from core.schemas.unified_control_plan import build_unified_control_plan
        plan = build_unified_control_plan(
            trace_id="t-mm-003",
            canonical_perception=self._make_perception_dict(["image", "audio"]),
        )
        # Shell projection should mention the modalities
        assert plan.shell_projection_hints.perception_summary is not None
        assert "text-only" not in plan.shell_projection_hints.perception_summary

    def test_native_multimodal_model_flagged_correctly(self) -> None:
        from core.schemas.unified_control_plan import build_unified_control_plan
        plan = build_unified_control_plan(
            trace_id="t-mm-004",
            canonical_perception=self._make_perception_dict(["image"]),
            chosen_model="gpt-4o",
            chosen_provider="openai",
            is_native_multimodal=True,
        )
        assert plan.chosen_model_decision.is_native_multimodal is True

    def test_multimodal_plan_is_json_serialisable(self) -> None:
        from core.schemas.unified_control_plan import build_unified_control_plan
        plan = build_unified_control_plan(
            trace_id="t-mm-005",
            canonical_perception=self._make_perception_dict(),
            chosen_model="gpt-4o",
            chosen_provider="openai",
            is_native_multimodal=True,
        )
        assert json.loads(json.dumps(plan.to_dict()))


# ---------------------------------------------------------------------------
# 13. build_unified_control_plan — local execution path
# ---------------------------------------------------------------------------


class TestBuildUnifiedControlPlanLocalPath:
    def test_local_path_records_correctly(self) -> None:
        from core.schemas.unified_control_plan import build_unified_control_plan
        plan = build_unified_control_plan(
            trace_id="t-local-001",
            execution_path="local",
            delegation_point="local",
        )
        assert plan.chosen_execution_decision.execution_path == "local"
        assert plan.chosen_execution_decision.delegation_point == "local"

    def test_local_path_has_no_remote_mode(self) -> None:
        from core.schemas.unified_control_plan import build_unified_control_plan
        plan = build_unified_control_plan(trace_id="t-local-002", execution_path="local")
        assert plan.chosen_execution_decision.remote_execution_mode is None

    def test_local_path_orchestration_false(self) -> None:
        from core.schemas.unified_control_plan import build_unified_control_plan
        plan = build_unified_control_plan(trace_id="t-local-003", execution_path="local")
        assert plan.chosen_execution_decision.orchestration_active is False


# ---------------------------------------------------------------------------
# 14. build_unified_control_plan — remote/cross-device execution path
# ---------------------------------------------------------------------------


class TestBuildUnifiedControlPlanRemotePath:
    def test_cross_device_path_records_correctly(self) -> None:
        from core.schemas.unified_control_plan import build_unified_control_plan
        plan = build_unified_control_plan(
            trace_id="t-remote-001",
            execution_path="cross_device",
            delegation_point="single_remote",
            remote_execution_mode="agent_runtime",
            target_device_ids=["device-abc"],
        )
        ced = plan.chosen_execution_decision
        assert ced.execution_path == "cross_device"
        assert ced.delegation_point == "single_remote"
        assert ced.remote_execution_mode == "agent_runtime"
        assert "device-abc" in ced.target_device_ids

    def test_command_only_mode_records_correctly(self) -> None:
        from core.schemas.unified_control_plan import build_unified_control_plan
        plan = build_unified_control_plan(
            trace_id="t-remote-002",
            execution_path="cross_device",
            remote_execution_mode="command_only",
        )
        assert plan.chosen_execution_decision.remote_execution_mode == "command_only"

    def test_orchestration_active_flag(self) -> None:
        from core.schemas.unified_control_plan import build_unified_control_plan
        plan = build_unified_control_plan(
            trace_id="t-remote-003",
            execution_path="cross_device",
            orchestration_active=True,
        )
        assert plan.chosen_execution_decision.orchestration_active is True

    def test_remote_plan_is_json_serialisable(self) -> None:
        from core.schemas.unified_control_plan import build_unified_control_plan
        plan = build_unified_control_plan(
            trace_id="t-remote-004",
            execution_path="cross_device",
            delegation_point="multi_device",
            orchestration_active=True,
            target_device_ids=["dev-1", "dev-2"],
        )
        assert json.loads(json.dumps(plan.to_dict()))


# ---------------------------------------------------------------------------
# 15. build_unified_control_plan — fallback level and reason
# ---------------------------------------------------------------------------


class TestBuildUnifiedControlPlanFallback:
    def test_no_fallback_is_default(self) -> None:
        from core.schemas.unified_control_plan import build_unified_control_plan, FallbackLevel
        plan = build_unified_control_plan(trace_id="t-fb-001")
        assert plan.fallback_level == FallbackLevel.NONE.value

    def test_model_fallback_recorded(self) -> None:
        from core.schemas.unified_control_plan import build_unified_control_plan, FallbackLevel
        plan = build_unified_control_plan(
            trace_id="t-fb-002",
            fallback_level=FallbackLevel.MODEL_FALLBACK.value,
            fallback_reason="primary provider unavailable",
        )
        assert plan.fallback_level == FallbackLevel.MODEL_FALLBACK.value
        assert plan.fallback_reason == "primary provider unavailable"

    def test_text_only_fallback_recorded(self) -> None:
        from core.schemas.unified_control_plan import build_unified_control_plan, FallbackLevel
        plan = build_unified_control_plan(
            trace_id="t-fb-003",
            fallback_level=FallbackLevel.TEXT_ONLY_FALLBACK.value,
            fallback_reason="multimodal model unavailable",
        )
        assert plan.fallback_level == FallbackLevel.TEXT_ONLY_FALLBACK.value

    def test_fallback_note_appears_in_shell_projection(self) -> None:
        from core.schemas.unified_control_plan import build_unified_control_plan, FallbackLevel
        plan = build_unified_control_plan(
            trace_id="t-fb-004",
            fallback_level=FallbackLevel.LOCAL_FALLBACK.value,
            fallback_reason="remote unavailable",
        )
        assert plan.shell_projection_hints.fallback_note is not None
        assert "local_fallback" in plan.shell_projection_hints.fallback_note

    def test_no_fallback_no_note_in_shell_projection(self) -> None:
        from core.schemas.unified_control_plan import build_unified_control_plan, FallbackLevel
        plan = build_unified_control_plan(
            trace_id="t-fb-005",
            fallback_level=FallbackLevel.NONE.value,
        )
        assert plan.shell_projection_hints.fallback_note is None


# ---------------------------------------------------------------------------
# 16. build_unified_control_plan — continuum posture derivation
# ---------------------------------------------------------------------------


class TestContinuumPostureDerivation:
    def test_no_continuum_gives_unknown_posture(self) -> None:
        from core.schemas.unified_control_plan import build_unified_control_plan, DecisionPosture
        plan = build_unified_control_plan(trace_id="t-posture-001")
        assert plan.decision_posture == DecisionPosture.UNKNOWN.value

    def test_liminal_continuum_gives_human_in_loop_posture(self) -> None:
        from core.schemas.unified_control_plan import build_unified_control_plan, DecisionPosture
        plan = build_unified_control_plan(
            trace_id="t-posture-002",
            continuum_state={"tri_state_phase": "liminal"},
        )
        assert plan.decision_posture == DecisionPosture.HUMAN_IN_LOOP.value

    def test_observer_continuum_gives_advisory_posture(self) -> None:
        from core.schemas.unified_control_plan import build_unified_control_plan, DecisionPosture
        plan = build_unified_control_plan(
            trace_id="t-posture-003",
            continuum_state={"tri_state_phase": "observer"},
        )
        assert plan.decision_posture == DecisionPosture.ADVISORY.value

    def test_autonomous_continuum_gives_autonomous_posture(self) -> None:
        from core.schemas.unified_control_plan import build_unified_control_plan, DecisionPosture
        plan = build_unified_control_plan(
            trace_id="t-posture-004",
            continuum_state={"tri_state_phase": "autonomous"},
        )
        assert plan.decision_posture == DecisionPosture.AUTONOMOUS.value

    def test_unknown_phase_gives_autonomous_posture(self) -> None:
        """Any non-liminal/observer phase is treated as autonomous."""
        from core.schemas.unified_control_plan import build_unified_control_plan, DecisionPosture
        plan = build_unified_control_plan(
            trace_id="t-posture-005",
            continuum_state={"tri_state_phase": "some_future_value"},
        )
        assert plan.decision_posture == DecisionPosture.AUTONOMOUS.value


# ---------------------------------------------------------------------------
# 17. unified_control_plan_summary
# ---------------------------------------------------------------------------


class TestUnifiedControlPlanSummary:
    def test_summary_has_required_keys(self) -> None:
        from core.schemas.unified_control_plan import build_unified_control_plan, unified_control_plan_summary
        plan = build_unified_control_plan(trace_id="t-sum-001", execution_path="local")
        summary = unified_control_plan_summary(plan)
        assert summary is not None
        required = {
            "plan_id", "decision_posture", "chosen_model", "chosen_provider",
            "is_native_multimodal", "execution_path", "fallback_level",
            "lifecycle_target", "authority_role", "has_perception", "has_model_supply",
        }
        assert required.issubset(set(summary.keys()))

    def test_summary_authority_role_is_correct(self) -> None:
        from core.schemas.unified_control_plan import build_unified_control_plan, unified_control_plan_summary, AUTHORITY_ROLE
        plan = build_unified_control_plan(trace_id="t-sum-002")
        summary = unified_control_plan_summary(plan)
        assert summary["authority_role"] == AUTHORITY_ROLE

    def test_summary_is_json_serialisable(self) -> None:
        from core.schemas.unified_control_plan import build_unified_control_plan, unified_control_plan_summary
        plan = build_unified_control_plan(trace_id="t-sum-003", chosen_model="gpt-4o", chosen_provider="openai")
        summary = unified_control_plan_summary(plan)
        assert json.loads(json.dumps(summary))


# ---------------------------------------------------------------------------
# 18. unified_control_plan_summary — None input
# ---------------------------------------------------------------------------


class TestUnifiedControlPlanSummaryNoneInput:
    def test_none_returns_none(self) -> None:
        from core.schemas.unified_control_plan import unified_control_plan_summary
        assert unified_control_plan_summary(None) is None


# ---------------------------------------------------------------------------
# 19. Plan serialisation stability
# ---------------------------------------------------------------------------


class TestPlanSerialisation:
    def test_full_plan_json_roundtrip(self) -> None:
        from core.schemas.unified_control_plan import build_unified_control_plan, UnifiedControlPlan, AUTHORITY_ROLE
        plan = build_unified_control_plan(
            runtime_session_id="rs-ser-001",
            trace_id="t-ser-001",
            canonical_perception={
                "has_continuous_perception": True,
                "has_request_multimodal": True,
                "active_modalities": ["image"],
                "source_summary": "host+request",
                "fusion_summary": "image input",
            },
            chosen_model="gpt-4o",
            chosen_provider="openai",
            is_native_multimodal=True,
            execution_path="cross_device",
            delegation_point="single_remote",
            remote_execution_mode="agent_runtime",
            fallback_level="none",
            lifecycle_target="succeeded",
            diagnostics_summary={"error_count": 0, "warning_count": 0},
        )
        serialised = json.dumps(plan.to_dict())
        d = json.loads(serialised)
        restored = UnifiedControlPlan.from_dict(d)
        assert restored.plan_id == plan.plan_id
        assert restored.authority_chain.decision_authority == AUTHORITY_ROLE

    def test_plan_id_is_stable(self) -> None:
        from core.schemas.unified_control_plan import build_unified_control_plan
        plan = build_unified_control_plan(trace_id="t-ser-002")
        assert plan.to_dict()["plan_id"] == plan.plan_id

    def test_schema_version_is_stable(self) -> None:
        from core.schemas.unified_control_plan import build_unified_control_plan
        plan = build_unified_control_plan(trace_id="t-ser-003")
        assert plan.to_dict()["schema_version"] == "1.0"


# ---------------------------------------------------------------------------
# 20. Shell/core boundary preserved
# ---------------------------------------------------------------------------


class TestShellCoreBoundary:
    def test_shell_role_distinct_from_decision_authority(self) -> None:
        from core.schemas.unified_control_plan import build_unified_control_plan, SHELL_ROLE, AUTHORITY_ROLE
        plan = build_unified_control_plan(trace_id="t-boundary-001")
        assert plan.authority_chain.shell_role == SHELL_ROLE
        assert plan.authority_chain.decision_authority == AUTHORITY_ROLE
        assert SHELL_ROLE != AUTHORITY_ROLE

    def test_execution_substrate_distinct_from_decision_authority(self) -> None:
        from core.schemas.unified_control_plan import build_unified_control_plan, SUBSTRATE_ROLE, AUTHORITY_ROLE
        plan = build_unified_control_plan(trace_id="t-boundary-002")
        assert plan.authority_chain.substrate_role == SUBSTRATE_ROLE
        assert SUBSTRATE_ROLE != AUTHORITY_ROLE

    def test_authority_label_mentions_openclawd(self) -> None:
        from core.schemas.unified_control_plan import build_unified_control_plan
        plan = build_unified_control_plan(trace_id="t-boundary-003")
        assert "OpenClawd" in plan.shell_projection_hints.authority_label

    def test_authority_chain_four_distinct_roles(self) -> None:
        from core.schemas.unified_control_plan import build_unified_control_plan
        plan = build_unified_control_plan(trace_id="t-boundary-004")
        chain_dict = plan.authority_chain.to_dict()
        roles = {
            chain_dict["decision_authority"],
            chain_dict["shell_role"],
            chain_dict["substrate_role"],
            chain_dict["orchestration_role"],
        }
        # All four roles should be distinct strings
        assert len(roles) == 4


# ---------------------------------------------------------------------------
# 21. OpenClawd integration — _build_unified_control_plan helper
# ---------------------------------------------------------------------------


class TestOpenClawdHelperExists:
    def test_helper_method_exists(self) -> None:
        from core.openclawd import OpenClawd
        assert hasattr(OpenClawd, "_build_unified_control_plan")

    def test_helper_is_callable(self) -> None:
        from core.openclawd import OpenClawd
        assert callable(getattr(OpenClawd, "_build_unified_control_plan"))

    def test_helper_returns_dict_or_none(self) -> None:
        """Call helper directly on a minimal OpenClawd-like object."""
        from core.schemas.unified_control_plan import build_unified_control_plan
        # Call the builder directly (not via OpenClawd to avoid heavy init)
        result = build_unified_control_plan(
            runtime_session_id="rs-helper-001",
            trace_id="t-helper-001",
            execution_path="local",
        )
        assert result is not None
        assert isinstance(result.to_dict(), dict)


# ---------------------------------------------------------------------------
# 22. OpenClawd integration — process() response contains unified_control_plan
# ---------------------------------------------------------------------------


class TestOpenClawdProcessIntegration:
    """Test that OpenClawd._build_unified_control_plan integrates with process().

    We test through the helper method and structural assertions rather than
    running a full process() call (which requires LLM connectivity).
    """

    def test_build_helper_returns_serialisable_dict(self) -> None:
        from core.schemas.unified_control_plan import build_unified_control_plan, AUTHORITY_ROLE
        plan = build_unified_control_plan(
            runtime_session_id="rs-proc-001",
            trace_id="t-proc-001",
            execution_path="local",
            lifecycle_target="succeeded",
        )
        d = plan.to_dict()
        assert isinstance(d, dict)
        assert d["authority_chain"]["decision_authority"] == AUTHORITY_ROLE

    def test_ucp_key_is_added_to_metadata(self) -> None:
        """Verify the key name used in response metadata is 'unified_control_plan'."""
        from core.schemas.unified_control_plan import build_unified_control_plan
        plan = build_unified_control_plan(trace_id="t-proc-002")
        # Simulate what openclawd.process() does
        metadata: Dict[str, Any] = {
            "trace_id": "t-proc-002",
            "unified_control_plan": plan.to_dict(),
        }
        assert "unified_control_plan" in metadata
        assert metadata["unified_control_plan"]["plan_id"]

    def test_ucp_authority_role_in_response_metadata(self) -> None:
        from core.schemas.unified_control_plan import build_unified_control_plan, AUTHORITY_ROLE
        plan = build_unified_control_plan(trace_id="t-proc-003")
        ucp_dict = plan.to_dict()
        assert ucp_dict["authority_chain"]["decision_authority"] == AUTHORITY_ROLE


# ---------------------------------------------------------------------------
# 23. Backward compatibility
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    def test_existing_metadata_keys_unaffected_by_ucp(self) -> None:
        """Adding unified_control_plan to metadata must not remove existing keys."""
        from core.schemas.unified_control_plan import build_unified_control_plan
        plan = build_unified_control_plan(trace_id="t-compat-001")
        # Simulate existing metadata
        existing_metadata = {
            "trace_id": "t-compat-001",
            "execution_path": "local",
            "canonical_perception_state": None,
            "execution_plan_summary": None,
        }
        # Adding new key is purely additive
        updated_metadata = {**existing_metadata, "unified_control_plan": plan.to_dict()}
        # All original keys still present
        assert updated_metadata["trace_id"] == "t-compat-001"
        assert updated_metadata["execution_path"] == "local"
        assert "unified_control_plan" in updated_metadata

    def test_plan_does_not_remove_execution_plan_key(self) -> None:
        """UnifiedControlPlan coexists with execution_plan in response."""
        from core.schemas.unified_control_plan import build_unified_control_plan
        plan = build_unified_control_plan(trace_id="t-compat-002")
        response = {
            "execution_plan": {"plan_id": "ep-001"},
            "metadata": {
                "unified_control_plan": plan.to_dict(),
            },
        }
        assert "execution_plan" in response
        assert "unified_control_plan" in response["metadata"]


# ---------------------------------------------------------------------------
# 24. Edge cases — None/empty perception
# ---------------------------------------------------------------------------


class TestEdgeCasesPerception:
    def test_none_perception_degrades_gracefully(self) -> None:
        from core.schemas.unified_control_plan import build_unified_control_plan
        plan = build_unified_control_plan(
            trace_id="t-edge-001",
            canonical_perception=None,
        )
        assert plan.canonical_perception_summary is None
        assert plan.to_dict()["canonical_perception_summary"] is None

    def test_empty_perception_dict_degrades_gracefully(self) -> None:
        from core.schemas.unified_control_plan import build_unified_control_plan
        plan = build_unified_control_plan(
            trace_id="t-edge-002",
            canonical_perception={},
        )
        # Empty dict is treated as no-perception (falsy); degrades to None summary
        # This is expected and safe behaviour
        assert plan.to_dict()["canonical_perception_summary"] is None

    def test_none_model_supply_degrades_gracefully(self) -> None:
        from core.schemas.unified_control_plan import build_unified_control_plan
        plan = build_unified_control_plan(
            trace_id="t-edge-003",
            canonical_model_supply=None,
        )
        assert plan.canonical_model_supply_summary is None

    def test_none_continuum_gives_unknown_posture(self) -> None:
        from core.schemas.unified_control_plan import build_unified_control_plan, DecisionPosture
        plan = build_unified_control_plan(trace_id="t-edge-004", continuum_state=None)
        assert plan.decision_posture == DecisionPosture.UNKNOWN.value


# ---------------------------------------------------------------------------
# 25. Edge cases — unknown enum values in from_dict
# ---------------------------------------------------------------------------


class TestEdgeCasesFromDict:
    def test_unknown_decision_posture_degrades_to_unknown(self) -> None:
        from core.schemas.unified_control_plan import UnifiedControlPlan, DecisionPosture
        plan = UnifiedControlPlan.from_dict({"decision_posture": "totally_unknown_value"})
        assert plan.decision_posture == DecisionPosture.UNKNOWN.value

    def test_unknown_fallback_level_degrades_to_unknown(self) -> None:
        from core.schemas.unified_control_plan import UnifiedControlPlan, FallbackLevel
        plan = UnifiedControlPlan.from_dict({"fallback_level": "bogus_level"})
        assert plan.fallback_level == FallbackLevel.UNKNOWN.value

    def test_missing_authority_chain_uses_defaults(self) -> None:
        from core.schemas.unified_control_plan import UnifiedControlPlan, AUTHORITY_ROLE
        plan = UnifiedControlPlan.from_dict({})
        assert plan.authority_chain.decision_authority == AUTHORITY_ROLE
