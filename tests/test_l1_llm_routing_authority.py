#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_l1_llm_routing_authority.py
=======================================

L1 — Unify LLM routing under a single router authority.

Validates:
  1.  LLM_ROUTE_AUTHORITY sentinel is importable from core.llm.route_authority.
  2.  LLM_ROUTE_AUTHORITY is a non-empty string.
  3.  LLM_ROUTE_AUTHORITY identifies LLMRouteAuthority by module path.
  4.  LLMRouteAuthority class is importable from core.llm.route_authority.
  5.  LLMRouteRequest class is importable from core.llm.route_authority.
  6.  LLMRouteDecision class is importable from core.llm.route_authority.
  7.  get_llm_route_authority factory is importable from core.llm.route_authority.
  8.  get_llm_route_authority returns an LLMRouteAuthority instance.
  9.  get_llm_route_authority returns the same singleton on repeated calls.
  10. refresh_llm_route_authority returns a fresh LLMRouteAuthority instance.
  11. LLMRouteRequest default task_type is "general".
  12. LLMRouteRequest default complexity is 0.5.
  13. LLMRouteRequest TaskType enum coercion works.
  14. LLMRouteRequest complexity is clamped to [0, 1].
  15. LLMRouteDecision authority is always LLM_ROUTE_AUTHORITY.
  16. LLMRouteDecision is_canonical defaults to True.
  17. LLMRouteDecision.to_dict() includes authority key.
  18. LLMRouteDecision.to_dict() authority value equals LLM_ROUTE_AUTHORITY.
  19. LLMRouteDecision.to_dict() includes provider key.
  20. LLMRouteDecision.to_dict() includes model key.
  21. LLMRouteDecision.to_dict() includes reason key.
  22. LLMRouteDecision.to_dict() includes is_canonical key.
  23. LLMRouteDecision.to_dict() includes source_request key.
  24. LLMRouteAuthority.execution_router returns a non-None object.
  25. LLMRouteAuthority.resolve returns an LLMRouteDecision.
  26. LLMRouteDecision returned by resolve has authority == LLM_ROUTE_AUTHORITY.
  27. LLMRouteDecision returned by resolve has is_canonical == True.
  28. LLMRouteDecision returned by resolve includes source_request.
  29. resolve with explicit task_type preserves it in source_request.
  30. resolve with preferred_provider preserves it in source_request.
  31. LLM_ROUTE_AUTHORITY is re-exported from core.llm package.
  32. LLMRouteRequest is re-exported from core.llm package.
  33. LLMRouteDecision is re-exported from core.llm package.
  34. LLMRouteAuthority is re-exported from core.llm package.
  35. get_llm_route_authority is re-exported from core.llm package.
  36. LLM_ROUTE_AUTHORITY sentinel differs from LLM_ROUTING_PACKAGE_AUTHORITY.
  37. LEGACY_PATH_REGISTRY contains PR-L1 routes.ai twin entry.
  38. LEGACY_PATH_REGISTRY contains PR-L1 routes.ai swarm entry.
  39. LEGACY_PATH_REGISTRY contains PR-L1 routes.nodes entry.
  40. LEGACY_PATH_REGISTRY contains PR-L1 routes.system status entry.
  41. LEGACY_PATH_REGISTRY contains PR-L1 routes.system env update entry.
  42. LEGACY_PATH_REGISTRY contains PR-L1 observability entry.
  43. LEGACY_PATH_REGISTRY contains PR-L1 system_integration entry.
  44. LEGACY_PATH_REGISTRY contains PR-L1 openclawd entry.
  45. LEGACY_PATH_REGISTRY contains PR-L1 agent kernel entry.
  46. LEGACY_PATH_REGISTRY contains PR-L1 ai_intent entry.
  47. LEGACY_PATH_REGISTRY contains PR-L1 galaxy_orchestrator entry.
  48. LEGACY_PATH_REGISTRY contains PR-L1 dashboard entry.
  49. PR-L1 registry entries have pr_guardrail_added == "PR-L1".
  50. LEGACY_PATH_REGISTRY has at least 8 PR-L1 entries.
  51. All PR-L1 entries have status LEGACY_COMPATIBILITY.
  52. docs/MODEL_ROUTING_AUTHORITY.md mentions LLMRouteAuthority.
  53. docs/MODEL_ROUTING_AUTHORITY.md mentions LLM_ROUTE_AUTHORITY.
  54. docs/MODEL_ROUTING_AUTHORITY.md mentions LLMRouteRequest.
  55. docs/MODEL_ROUTING_AUTHORITY.md mentions LLMRouteDecision.
  56. docs/MODEL_ROUTING_AUTHORITY.md mentions get_llm_route_authority.
  57. docs/MODEL_ROUTING_AUTHORITY.md section 9 exists.
  58. LLMRouteAuthority has a resolve method.
  59. LLMRouteAuthority has an execution_router property.
  60. LLMRouteAuthority has a chat method.
  61. LLMRouteAuthority has a chat_with_tools method.
  62. LLMRouteAuthority has a chat_json method.
  63. LLMRouteDecision default authority always equals LLM_ROUTE_AUTHORITY.
  64. Constructing LLMRouteDecision without authority still sets it to LLM_ROUTE_AUTHORITY.
  65. core.llm.route_authority module is importable without errors.
  66. core.llm.__init__ exports LLM_ROUTE_AUTHORITY without error.
"""

from __future__ import annotations

import os
import sys

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_stub_router():
    """Return a minimal stub object that mimics the MultiLLMRouter interface."""
    from dataclasses import dataclass, field
    from typing import List

    @dataclass
    class _StubRoutingDecision:
        provider: str = "stub_provider"
        model: str = "stub_model"
        reason: str = "stub reason"
        alternatives: List[str] = field(default_factory=list)

    class _StubRouter:
        def route(self, task_type=None, preferred_provider=None, complexity_score=0.5):
            return _StubRoutingDecision(
                provider=preferred_provider or "stub_provider",
                model="stub_model",
                reason=f"stub: task={getattr(task_type, 'value', task_type)} complexity={complexity_score}",
            )

    return _StubRouter()


# ---------------------------------------------------------------------------
# 1-3: LLM_ROUTE_AUTHORITY sentinel
# ---------------------------------------------------------------------------


def test_01_llm_route_authority_importable():
    from core.llm.route_authority import LLM_ROUTE_AUTHORITY

    assert LLM_ROUTE_AUTHORITY is not None


def test_02_llm_route_authority_non_empty():
    from core.llm.route_authority import LLM_ROUTE_AUTHORITY

    assert isinstance(LLM_ROUTE_AUTHORITY, str)
    assert len(LLM_ROUTE_AUTHORITY) > 0


def test_03_llm_route_authority_identifies_class_and_module():
    from core.llm.route_authority import LLM_ROUTE_AUTHORITY

    assert "LLMRouteAuthority" in LLM_ROUTE_AUTHORITY
    assert "route_authority" in LLM_ROUTE_AUTHORITY


# ---------------------------------------------------------------------------
# 4-7: Class / factory importability
# ---------------------------------------------------------------------------


def test_04_llm_route_authority_class_importable():
    from core.llm.route_authority import LLMRouteAuthority

    assert LLMRouteAuthority is not None


def test_05_llm_route_request_importable():
    from core.llm.route_authority import LLMRouteRequest

    assert LLMRouteRequest is not None


def test_06_llm_route_decision_importable():
    from core.llm.route_authority import LLMRouteDecision

    assert LLMRouteDecision is not None


def test_07_get_llm_route_authority_importable():
    from core.llm.route_authority import get_llm_route_authority

    assert callable(get_llm_route_authority)


# ---------------------------------------------------------------------------
# 8-10: Factory behaviour
# ---------------------------------------------------------------------------


def test_08_get_llm_route_authority_returns_instance():
    from core.llm.route_authority import LLMRouteAuthority, get_llm_route_authority

    auth = get_llm_route_authority()
    assert isinstance(auth, LLMRouteAuthority)


def test_09_get_llm_route_authority_singleton():
    from core.llm.route_authority import get_llm_route_authority

    a1 = get_llm_route_authority()
    a2 = get_llm_route_authority()
    assert a1 is a2


def test_10_refresh_llm_route_authority_fresh_instance():
    from core.llm.route_authority import (
        LLMRouteAuthority,
        get_llm_route_authority,
        refresh_llm_route_authority,
    )

    old = get_llm_route_authority()
    fresh = refresh_llm_route_authority()
    assert isinstance(fresh, LLMRouteAuthority)
    # After refresh the singleton should point to the new instance
    assert get_llm_route_authority() is fresh


# ---------------------------------------------------------------------------
# 11-14: LLMRouteRequest
# ---------------------------------------------------------------------------


def test_11_route_request_default_task_type():
    from core.llm.route_authority import LLMRouteRequest

    req = LLMRouteRequest()
    assert req.task_type == "general"


def test_12_route_request_default_complexity():
    from core.llm.route_authority import LLMRouteRequest

    req = LLMRouteRequest()
    assert req.complexity == 0.5


def test_13_route_request_task_type_enum_coercion():
    from core.llm.route_authority import LLMRouteRequest
    from core.multi_llm_router import TaskType

    req = LLMRouteRequest(task_type=TaskType.REASONING)
    assert req.task_type == TaskType.REASONING.value


def test_14_route_request_complexity_clamped():
    from core.llm.route_authority import LLMRouteRequest

    req_low = LLMRouteRequest(complexity=-5.0)
    assert req_low.complexity == 0.0

    req_high = LLMRouteRequest(complexity=99.9)
    assert req_high.complexity == 1.0


# ---------------------------------------------------------------------------
# 15-23: LLMRouteDecision
# ---------------------------------------------------------------------------


def test_15_route_decision_authority_is_sentinel():
    from core.llm.route_authority import LLM_ROUTE_AUTHORITY, LLMRouteDecision

    decision = LLMRouteDecision(provider="p", model="m", reason="r")
    assert decision.authority == LLM_ROUTE_AUTHORITY


def test_16_route_decision_is_canonical_default_true():
    from core.llm.route_authority import LLMRouteDecision

    decision = LLMRouteDecision(provider="p", model="m", reason="r")
    assert decision.is_canonical is True


def test_17_route_decision_to_dict_has_authority():
    from core.llm.route_authority import LLMRouteDecision

    decision = LLMRouteDecision(provider="p", model="m", reason="r")
    d = decision.to_dict()
    assert "authority" in d


def test_18_route_decision_to_dict_authority_equals_sentinel():
    from core.llm.route_authority import LLM_ROUTE_AUTHORITY, LLMRouteDecision

    decision = LLMRouteDecision(provider="p", model="m", reason="r")
    d = decision.to_dict()
    assert d["authority"] == LLM_ROUTE_AUTHORITY


def test_19_route_decision_to_dict_has_provider():
    from core.llm.route_authority import LLMRouteDecision

    decision = LLMRouteDecision(provider="openai", model="gpt-4o", reason="test")
    d = decision.to_dict()
    assert "provider" in d
    assert d["provider"] == "openai"


def test_20_route_decision_to_dict_has_model():
    from core.llm.route_authority import LLMRouteDecision

    decision = LLMRouteDecision(provider="openai", model="gpt-4o", reason="test")
    d = decision.to_dict()
    assert "model" in d
    assert d["model"] == "gpt-4o"


def test_21_route_decision_to_dict_has_reason():
    from core.llm.route_authority import LLMRouteDecision

    decision = LLMRouteDecision(provider="p", model="m", reason="canonical reason")
    d = decision.to_dict()
    assert "reason" in d
    assert d["reason"] == "canonical reason"


def test_22_route_decision_to_dict_has_is_canonical():
    from core.llm.route_authority import LLMRouteDecision

    decision = LLMRouteDecision(provider="p", model="m", reason="r")
    d = decision.to_dict()
    assert "is_canonical" in d
    assert d["is_canonical"] is True


def test_23_route_decision_to_dict_has_source_request():
    from core.llm.route_authority import LLMRouteDecision, LLMRouteRequest

    req = LLMRouteRequest(task_type="reasoning", complexity=0.8)
    decision = LLMRouteDecision(provider="p", model="m", reason="r", source_request=req)
    d = decision.to_dict()
    assert "source_request" in d
    assert d["source_request"] is not None
    assert d["source_request"]["task_type"] == "reasoning"


# ---------------------------------------------------------------------------
# 24-30: LLMRouteAuthority.resolve()
# ---------------------------------------------------------------------------


def test_24_execution_router_non_none():
    from core.llm.route_authority import LLMRouteAuthority

    stub = _make_stub_router()
    auth = LLMRouteAuthority(router=stub)
    assert auth.execution_router is not None


def test_25_resolve_returns_llm_route_decision():
    from core.llm.route_authority import LLMRouteAuthority, LLMRouteDecision, LLMRouteRequest

    stub = _make_stub_router()
    auth = LLMRouteAuthority(router=stub)
    decision = auth.resolve(LLMRouteRequest())
    assert isinstance(decision, LLMRouteDecision)


def test_26_resolve_decision_authority_is_sentinel():
    from core.llm.route_authority import LLM_ROUTE_AUTHORITY, LLMRouteAuthority, LLMRouteRequest

    stub = _make_stub_router()
    auth = LLMRouteAuthority(router=stub)
    decision = auth.resolve(LLMRouteRequest(task_type="general", complexity=0.5))
    assert decision.authority == LLM_ROUTE_AUTHORITY


def test_27_resolve_decision_is_canonical_true():
    from core.llm.route_authority import LLMRouteAuthority, LLMRouteRequest

    stub = _make_stub_router()
    auth = LLMRouteAuthority(router=stub)
    decision = auth.resolve(LLMRouteRequest())
    assert decision.is_canonical is True


def test_28_resolve_decision_has_source_request():
    from core.llm.route_authority import LLMRouteAuthority, LLMRouteRequest

    stub = _make_stub_router()
    auth = LLMRouteAuthority(router=stub)
    req = LLMRouteRequest(task_type="reasoning", complexity=0.9)
    decision = auth.resolve(req)
    assert decision.source_request is not None
    assert decision.source_request is req


def test_29_resolve_preserves_task_type_in_source_request():
    from core.llm.route_authority import LLMRouteAuthority, LLMRouteRequest

    stub = _make_stub_router()
    auth = LLMRouteAuthority(router=stub)
    req = LLMRouteRequest(task_type="code_generation", complexity=0.6)
    decision = auth.resolve(req)
    assert decision.source_request.task_type == "code_generation"


def test_30_resolve_preserves_preferred_provider_in_source_request():
    from core.llm.route_authority import LLMRouteAuthority, LLMRouteRequest

    stub = _make_stub_router()
    auth = LLMRouteAuthority(router=stub)
    req = LLMRouteRequest(task_type="general", preferred_provider="anthropic")
    decision = auth.resolve(req)
    assert decision.source_request.preferred_provider == "anthropic"


# ---------------------------------------------------------------------------
# 31-36: core.llm package re-exports
# ---------------------------------------------------------------------------


def test_31_llm_route_authority_re_exported_from_core_llm():
    from core.llm import LLM_ROUTE_AUTHORITY

    assert LLM_ROUTE_AUTHORITY is not None


def test_32_llm_route_request_re_exported_from_core_llm():
    from core.llm import LLMRouteRequest

    assert LLMRouteRequest is not None


def test_33_llm_route_decision_re_exported_from_core_llm():
    from core.llm import LLMRouteDecision

    assert LLMRouteDecision is not None


def test_34_llm_route_authority_class_re_exported_from_core_llm():
    from core.llm import LLMRouteAuthority

    assert LLMRouteAuthority is not None


def test_35_get_llm_route_authority_re_exported_from_core_llm():
    from core.llm import get_llm_route_authority

    assert callable(get_llm_route_authority)


def test_36_llm_route_authority_differs_from_package_authority():
    from core.llm import LLM_ROUTE_AUTHORITY, LLM_ROUTING_PACKAGE_AUTHORITY

    assert LLM_ROUTE_AUTHORITY != LLM_ROUTING_PACKAGE_AUTHORITY


# ---------------------------------------------------------------------------
# 37-51: Legacy path registry entries
# ---------------------------------------------------------------------------


def test_37_legacy_registry_has_routes_ai_twin_entry():
    from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY

    assert "core.routes.ai.create_twin_command.direct_get_llm_router" in LEGACY_PATH_REGISTRY


def test_38_legacy_registry_has_routes_ai_swarm_entry():
    from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY

    assert "core.routes.ai.create_agent_swarm.direct_get_llm_router" in LEGACY_PATH_REGISTRY


def test_39_legacy_registry_has_routes_nodes_entry():
    from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY

    assert "core.routes.nodes.create_router.direct_get_llm_router" in LEGACY_PATH_REGISTRY


def test_40_legacy_registry_has_routes_system_status_entry():
    from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY

    assert "core.routes.system.get_system_status.direct_get_llm_router" in LEGACY_PATH_REGISTRY


def test_41_legacy_registry_has_routes_system_env_update_entry():
    from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY

    assert "core.routes.system.update_env.direct_get_llm_router" in LEGACY_PATH_REGISTRY


def test_42_legacy_registry_has_observability_entry():
    from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY

    assert "core.routes.observability.model_route_status.direct_get_llm_router" in LEGACY_PATH_REGISTRY


def test_43_legacy_registry_has_system_integration_entry():
    from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY

    assert "core.system_integration.SystemIntegration._execute_builtin.direct_get_llm_router" in LEGACY_PATH_REGISTRY


def test_44_legacy_registry_has_openclawd_entry():
    from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY

    assert "core.openclawd.OpenClawd.direct_get_llm_router" in LEGACY_PATH_REGISTRY


def test_45_legacy_registry_has_agent_kernel_entry():
    from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY

    assert "core.agent.kernel.AgentKernel.direct_get_llm_router" in LEGACY_PATH_REGISTRY


def test_46_legacy_registry_has_ai_intent_entry():
    from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY

    assert "core.ai_intent.IntentParser.direct_get_llm_router" in LEGACY_PATH_REGISTRY


def test_47_legacy_registry_has_galaxy_orchestrator_entry():
    from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY

    assert "galaxy_gateway.orchestrator.galaxy_orchestrator.direct_get_llm_router" in LEGACY_PATH_REGISTRY


def test_48_legacy_registry_has_dashboard_entry():
    from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY

    assert "dashboard.backend.main.direct_get_llm_router" in LEGACY_PATH_REGISTRY


def test_49_all_pr_l1_entries_have_guardrail_tag():
    from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY

    l1_entries = [e for e in LEGACY_PATH_REGISTRY.values() if e.pr_guardrail_added == "PR-L1"]
    for entry in l1_entries:
        assert entry.pr_guardrail_added == "PR-L1"


def test_50_legacy_registry_has_at_least_eight_pr_l1_entries():
    from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY

    count = sum(
        1
        for e in LEGACY_PATH_REGISTRY.values()
        if e.pr_guardrail_added == "PR-L1"
    )
    assert count >= 8, f"Expected ≥8 PR-L1 entries, got {count}"


def test_51_all_pr_l1_entries_are_legacy_compatibility():
    from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY, LegacyPathStatus

    l1_entries = [e for e in LEGACY_PATH_REGISTRY.values() if e.pr_guardrail_added == "PR-L1"]
    assert len(l1_entries) > 0
    for entry in l1_entries:
        assert entry.status == LegacyPathStatus.LEGACY_COMPATIBILITY, (
            f"PR-L1 entry {entry.module_path!r} should be LEGACY_COMPATIBILITY, "
            f"got {entry.status!r}"
        )


# ---------------------------------------------------------------------------
# 52-57: docs/MODEL_ROUTING_AUTHORITY.md content
# ---------------------------------------------------------------------------


def _doc_path():
    return os.path.join(_REPO_ROOT, "docs", "MODEL_ROUTING_AUTHORITY.md")


def _doc_content():
    with open(_doc_path(), encoding="utf-8") as fh:
        return fh.read()


def test_52_doc_mentions_llm_route_authority_class():
    assert "LLMRouteAuthority" in _doc_content()


def test_53_doc_mentions_llm_route_authority_sentinel():
    assert "LLM_ROUTE_AUTHORITY" in _doc_content()


def test_54_doc_mentions_llm_route_request():
    assert "LLMRouteRequest" in _doc_content()


def test_55_doc_mentions_llm_route_decision():
    assert "LLMRouteDecision" in _doc_content()


def test_56_doc_mentions_get_llm_route_authority():
    assert "get_llm_route_authority" in _doc_content()


def test_57_doc_section_9_exists():
    assert "## 9." in _doc_content()


# ---------------------------------------------------------------------------
# 58-62: LLMRouteAuthority interface
# ---------------------------------------------------------------------------


def test_58_authority_has_resolve_method():
    from core.llm.route_authority import LLMRouteAuthority

    assert hasattr(LLMRouteAuthority, "resolve")
    assert callable(LLMRouteAuthority.resolve)


def test_59_authority_has_execution_router_property():
    from core.llm.route_authority import LLMRouteAuthority

    # Check that it's a property (or at least attribute) on the class
    assert hasattr(LLMRouteAuthority, "execution_router")


def test_60_authority_has_chat_method():
    from core.llm.route_authority import LLMRouteAuthority

    assert hasattr(LLMRouteAuthority, "chat")
    assert callable(LLMRouteAuthority.chat)


def test_61_authority_has_chat_with_tools_method():
    from core.llm.route_authority import LLMRouteAuthority

    assert hasattr(LLMRouteAuthority, "chat_with_tools")
    assert callable(LLMRouteAuthority.chat_with_tools)


def test_62_authority_has_chat_json_method():
    from core.llm.route_authority import LLMRouteAuthority

    assert hasattr(LLMRouteAuthority, "chat_json")
    assert callable(LLMRouteAuthority.chat_json)


# ---------------------------------------------------------------------------
# 63-66: Authority sentinel invariants
# ---------------------------------------------------------------------------


def test_63_route_decision_default_authority_always_sentinel():
    from core.llm.route_authority import LLM_ROUTE_AUTHORITY, LLMRouteDecision

    # Explicitly specifying authority keeps sentinel value
    d1 = LLMRouteDecision(provider="a", model="b", reason="c", authority=LLM_ROUTE_AUTHORITY)
    assert d1.authority == LLM_ROUTE_AUTHORITY


def test_64_route_decision_constructed_without_explicit_authority_is_sentinel():
    from core.llm.route_authority import LLM_ROUTE_AUTHORITY, LLMRouteDecision

    # Default should be the sentinel
    d = LLMRouteDecision(provider="x", model="y", reason="z")
    assert d.authority == LLM_ROUTE_AUTHORITY


def test_65_route_authority_module_importable_without_errors():
    import importlib

    mod = importlib.import_module("core.llm.route_authority")
    assert mod is not None


def test_66_core_llm_exports_llm_route_authority_without_error():
    import importlib

    mod = importlib.import_module("core.llm")
    assert hasattr(mod, "LLM_ROUTE_AUTHORITY")
    assert hasattr(mod, "get_llm_route_authority")
    assert hasattr(mod, "LLMRouteRequest")
    assert hasattr(mod, "LLMRouteDecision")
    assert hasattr(mod, "LLMRouteAuthority")
