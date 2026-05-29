#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_l2_model_supply_authority.py
=======================================

L2 — Canonicalize model supply truth, provider ordering, and fallback legality.

Validates:
  1.  LLM_SUPPLY_AUTHORITY sentinel is importable from core.llm.supply_authority.
  2.  LLM_SUPPLY_AUTHORITY is a non-empty string.
  3.  LLM_SUPPLY_AUTHORITY identifies LLMSupplyAuthority by module path.
  4.  FallbackLegality enum is importable from core.llm.supply_authority.
  5.  FallbackLegality.NONE exists.
  6.  FallbackLegality.PRIMARY_UNAVAILABLE exists.
  7.  FallbackLegality.PRIMARY_DEGRADED exists.
  8.  FallbackLegality.CAPABILITY_MISMATCH exists.
  9.  FallbackLegality.EXPLICIT_CALLER_PREFERENCE exists.
  10. FallbackLegality.NO_SUPPLY_AVAILABLE exists.
  11. ProviderOrderingPolicy is importable from core.llm.supply_authority.
  12. ProviderOrderingPolicy default allow_degraded_fallback is True.
  13. ProviderOrderingPolicy default max_fallback_depth is 5.
  14. ProviderOrderingPolicy default prefer_canonical_fallback_list is True.
  15. ProviderOrderingPolicy.to_dict() returns a dict with expected keys.
  16. SupplyResolutionStep is importable from core.llm.supply_authority.
  17. SupplyResolutionStep.to_dict() contains expected keys.
  18. SupplyResolutionResult is importable from core.llm.supply_authority.
  19. SupplyResolutionResult.authority defaults to LLM_SUPPLY_AUTHORITY.
  20. SupplyResolutionResult.to_dict() contains requested_provider key.
  21. SupplyResolutionResult.to_dict() contains requested_model key.
  22. SupplyResolutionResult.to_dict() contains supplied_provider key.
  23. SupplyResolutionResult.to_dict() contains supplied_model key.
  24. SupplyResolutionResult.to_dict() contains fallback_legality key.
  25. SupplyResolutionResult.to_dict() contains ordering_basis key.
  26. SupplyResolutionResult.to_dict() contains is_satisfied key.
  27. SupplyResolutionResult.to_dict() contains resolution_trace key.
  28. SupplyResolutionResult.to_dict() contains authority key.
  29. SupplyResolutionResult.to_dict() authority equals LLM_SUPPLY_AUTHORITY.
  30. LLMSupplyAuthority class is importable from core.llm.supply_authority.
  31. LLMSupplyAuthority has a resolve_supply method.
  32. LLMSupplyAuthority has a policy property.
  33. get_llm_supply_authority factory is importable from core.llm.supply_authority.
  34. get_llm_supply_authority returns an LLMSupplyAuthority instance.
  35. get_llm_supply_authority returns the same singleton on repeated calls.
  36. refresh_llm_supply_authority returns a fresh LLMSupplyAuthority instance.
  37. resolve_supply with a healthy primary provider satisfies supply without fallback.
  38. resolve_supply result has authority == LLM_SUPPLY_AUTHORITY.
  39. resolve_supply primary satisfaction has fallback_legality == NONE.
  40. resolve_supply with DOWN primary falls back to available secondary.
  41. resolve_supply fallback has fallback_legality == PRIMARY_UNAVAILABLE.
  42. resolve_supply fallback resolution_trace records the skipped primary.
  43. resolve_supply fallback resolution_trace records the selected secondary.
  44. resolve_supply with no available providers is_satisfied == False.
  45. resolve_supply with no available providers fallback_legality == NO_SUPPLY_AVAILABLE.
  46. resolve_supply supplied_provider differs from requested when fallback taken.
  47. resolve_supply with degraded primary and policy allowing degraded satisfies from primary.
  48. resolve_supply with degraded primary and policy disallowing degraded falls back.
  49. resolve_supply fallback_legality == PRIMARY_DEGRADED when primary is degraded.
  50. resolve_supply respects max_fallback_depth=0 (no fallback allowed).
  51. resolve_supply with canonical fallback_candidates list uses it for ordering.
  52. resolve_supply resolution_trace is non-empty.
  53. resolve_supply ordering_basis is non-empty.
  54. resolve_supply result is_satisfied == True for healthy primary.
  55. resolve_supply to_dict() is JSON-serialisable.
  56. LLM_SUPPLY_AUTHORITY is re-exported from core.llm package.
  57. FallbackLegality is re-exported from core.llm package.
  58. ProviderOrderingPolicy is re-exported from core.llm package.
  59. SupplyResolutionResult is re-exported from core.llm package.
  60. LLMSupplyAuthority is re-exported from core.llm package.
  61. get_llm_supply_authority is re-exported from core.llm package.
  62. LLM_SUPPLY_AUTHORITY differs from LLM_ROUTE_AUTHORITY.
  63. docs/MODEL_ROUTING_AUTHORITY.md contains LLM_SUPPLY_AUTHORITY.
  64. docs/MODEL_ROUTING_AUTHORITY.md contains LLMSupplyAuthority.
  65. docs/MODEL_ROUTING_AUTHORITY.md contains FallbackLegality.
  66. docs/MODEL_ROUTING_AUTHORITY.md contains SupplyResolutionResult.
  67. docs/MODEL_ROUTING_AUTHORITY.md section 10 exists.
  68. resolve_supply with None supply_state has is_satisfied == False.
  69. resolve_supply with empty supply_state dict has is_satisfied == False.
  70. resolve_supply requested_provider is always preserved in result.
  71. resolve_supply requested_model is always preserved in result.
  72. SupplyResolutionStep fallback_legality serialises as a string value.
  73. SupplyResolutionResult fallback_legality serialises as a string value in to_dict.
  74. resolve_supply capability_mismatch fallback_legality when capabilities required.
  75. LLMSupplyAuthority core.llm.supply_authority module is importable without errors.
"""

from __future__ import annotations

import json
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

def _healthy_provider_record(
    provider_id: str = "openai",
    model: str = "gpt-4o",
) -> dict:
    return {
        "provider_id": provider_id,
        "health_status": "healthy",
        "default_model": model,
        "models": [model],
        "is_available": True,
        "capability": None,
    }


def _down_provider_record(
    provider_id: str = "anthropic",
    model: str = "claude-sonnet-4-6-20251022",
) -> dict:
    return {
        "provider_id": provider_id,
        "health_status": "down",
        "default_model": model,
        "models": [model],
        "is_available": False,
        "capability": None,
    }


def _degraded_provider_record(
    provider_id: str = "openai",
    model: str = "gpt-4o",
) -> dict:
    return {
        "provider_id": provider_id,
        "health_status": "degraded",
        "default_model": model,
        "models": [model],
        "is_available": True,
        "capability": None,
    }


def _make_supply_state_dict(
    providers: dict,
    available_ids: list = None,
    fallback_candidates: list = None,
    primary_provider_id: str = None,
) -> dict:
    available_ids = available_ids or [
        pid for pid, rec in providers.items()
        if rec.get("health_status", "") not in ("down", "unavailable")
    ]
    return {
        "providers": providers,
        "available_provider_ids": available_ids,
        "unavailable_provider_ids": [
            pid for pid in providers if pid not in available_ids
        ],
        "fallback_candidates": fallback_candidates or [],
        "primary_provider_id": primary_provider_id,
    }


def _make_route_decision(provider: str = "openai", model: str = "gpt-4o") -> object:
    """Return a minimal stub LLMRouteDecision."""
    class _StubDecision:
        pass
    d = _StubDecision()
    d.provider = provider
    d.model = model
    d.reason = "stub"
    return d


# ---------------------------------------------------------------------------
# 1-3: LLM_SUPPLY_AUTHORITY sentinel
# ---------------------------------------------------------------------------


def test_01_llm_supply_authority_sentinel_importable():
    from core.llm.supply_authority import LLM_SUPPLY_AUTHORITY
    assert LLM_SUPPLY_AUTHORITY is not None


def test_02_llm_supply_authority_sentinel_non_empty():
    from core.llm.supply_authority import LLM_SUPPLY_AUTHORITY
    assert isinstance(LLM_SUPPLY_AUTHORITY, str)
    assert len(LLM_SUPPLY_AUTHORITY) > 0


def test_03_llm_supply_authority_sentinel_identifies_class():
    from core.llm.supply_authority import LLM_SUPPLY_AUTHORITY
    assert "LLMSupplyAuthority" in LLM_SUPPLY_AUTHORITY
    assert "supply_authority" in LLM_SUPPLY_AUTHORITY


# ---------------------------------------------------------------------------
# 4-10: FallbackLegality enum
# ---------------------------------------------------------------------------


def test_04_fallback_legality_importable():
    from core.llm.supply_authority import FallbackLegality
    assert FallbackLegality is not None


def test_05_fallback_legality_none_exists():
    from core.llm.supply_authority import FallbackLegality
    assert FallbackLegality.NONE is not None
    assert FallbackLegality.NONE.value == "none"


def test_06_fallback_legality_primary_unavailable_exists():
    from core.llm.supply_authority import FallbackLegality
    assert FallbackLegality.PRIMARY_UNAVAILABLE is not None
    assert FallbackLegality.PRIMARY_UNAVAILABLE.value == "primary_unavailable"


def test_07_fallback_legality_primary_degraded_exists():
    from core.llm.supply_authority import FallbackLegality
    assert FallbackLegality.PRIMARY_DEGRADED is not None
    assert FallbackLegality.PRIMARY_DEGRADED.value == "primary_degraded"


def test_08_fallback_legality_capability_mismatch_exists():
    from core.llm.supply_authority import FallbackLegality
    assert FallbackLegality.CAPABILITY_MISMATCH is not None
    assert FallbackLegality.CAPABILITY_MISMATCH.value == "capability_mismatch"


def test_09_fallback_legality_explicit_caller_preference_exists():
    from core.llm.supply_authority import FallbackLegality
    assert FallbackLegality.EXPLICIT_CALLER_PREFERENCE is not None
    assert FallbackLegality.EXPLICIT_CALLER_PREFERENCE.value == "explicit_caller_preference"


def test_10_fallback_legality_no_supply_available_exists():
    from core.llm.supply_authority import FallbackLegality
    assert FallbackLegality.NO_SUPPLY_AVAILABLE is not None
    assert FallbackLegality.NO_SUPPLY_AVAILABLE.value == "no_supply_available"


# ---------------------------------------------------------------------------
# 11-15: ProviderOrderingPolicy
# ---------------------------------------------------------------------------


def test_11_provider_ordering_policy_importable():
    from core.llm.supply_authority import ProviderOrderingPolicy
    assert ProviderOrderingPolicy is not None


def test_12_provider_ordering_policy_default_allow_degraded():
    from core.llm.supply_authority import ProviderOrderingPolicy
    p = ProviderOrderingPolicy()
    assert p.allow_degraded_fallback is True


def test_13_provider_ordering_policy_default_max_fallback_depth():
    from core.llm.supply_authority import ProviderOrderingPolicy
    p = ProviderOrderingPolicy()
    assert p.max_fallback_depth == 5


def test_14_provider_ordering_policy_default_prefer_canonical_list():
    from core.llm.supply_authority import ProviderOrderingPolicy
    p = ProviderOrderingPolicy()
    assert p.prefer_canonical_fallback_list is True


def test_15_provider_ordering_policy_to_dict_keys():
    from core.llm.supply_authority import ProviderOrderingPolicy
    p = ProviderOrderingPolicy()
    d = p.to_dict()
    assert isinstance(d, dict)
    assert "allow_degraded_fallback" in d
    assert "max_fallback_depth" in d
    assert "prefer_canonical_fallback_list" in d
    assert "required_capabilities" in d


# ---------------------------------------------------------------------------
# 16-17: SupplyResolutionStep
# ---------------------------------------------------------------------------


def test_16_supply_resolution_step_importable():
    from core.llm.supply_authority import SupplyResolutionStep
    assert SupplyResolutionStep is not None


def test_17_supply_resolution_step_to_dict_keys():
    from core.llm.supply_authority import FallbackLegality, SupplyResolutionStep
    step = SupplyResolutionStep(provider="openai", model="gpt-4o")
    d = step.to_dict()
    assert "provider" in d
    assert "model" in d
    assert "selected" in d
    assert "skipped" in d
    assert "skip_reason" in d
    assert "fallback_legality" in d


# ---------------------------------------------------------------------------
# 18-29: SupplyResolutionResult
# ---------------------------------------------------------------------------


def test_18_supply_resolution_result_importable():
    from core.llm.supply_authority import SupplyResolutionResult
    assert SupplyResolutionResult is not None


def test_19_supply_resolution_result_authority_default():
    from core.llm.supply_authority import LLM_SUPPLY_AUTHORITY, SupplyResolutionResult
    r = SupplyResolutionResult(requested_provider="openai", requested_model="gpt-4o")
    assert r.authority == LLM_SUPPLY_AUTHORITY


def test_20_supply_resolution_result_to_dict_has_requested_provider():
    from core.llm.supply_authority import SupplyResolutionResult
    r = SupplyResolutionResult(requested_provider="openai", requested_model="gpt-4o")
    assert "requested_provider" in r.to_dict()


def test_21_supply_resolution_result_to_dict_has_requested_model():
    from core.llm.supply_authority import SupplyResolutionResult
    r = SupplyResolutionResult(requested_provider="openai", requested_model="gpt-4o")
    assert "requested_model" in r.to_dict()


def test_22_supply_resolution_result_to_dict_has_supplied_provider():
    from core.llm.supply_authority import SupplyResolutionResult
    r = SupplyResolutionResult(requested_provider="openai", requested_model="gpt-4o")
    assert "supplied_provider" in r.to_dict()


def test_23_supply_resolution_result_to_dict_has_supplied_model():
    from core.llm.supply_authority import SupplyResolutionResult
    r = SupplyResolutionResult(requested_provider="openai", requested_model="gpt-4o")
    assert "supplied_model" in r.to_dict()


def test_24_supply_resolution_result_to_dict_has_fallback_legality():
    from core.llm.supply_authority import SupplyResolutionResult
    r = SupplyResolutionResult(requested_provider="openai", requested_model="gpt-4o")
    assert "fallback_legality" in r.to_dict()


def test_25_supply_resolution_result_to_dict_has_ordering_basis():
    from core.llm.supply_authority import SupplyResolutionResult
    r = SupplyResolutionResult(requested_provider="openai", requested_model="gpt-4o")
    assert "ordering_basis" in r.to_dict()


def test_26_supply_resolution_result_to_dict_has_is_satisfied():
    from core.llm.supply_authority import SupplyResolutionResult
    r = SupplyResolutionResult(requested_provider="openai", requested_model="gpt-4o")
    assert "is_satisfied" in r.to_dict()


def test_27_supply_resolution_result_to_dict_has_resolution_trace():
    from core.llm.supply_authority import SupplyResolutionResult
    r = SupplyResolutionResult(requested_provider="openai", requested_model="gpt-4o")
    assert "resolution_trace" in r.to_dict()


def test_28_supply_resolution_result_to_dict_has_authority():
    from core.llm.supply_authority import SupplyResolutionResult
    r = SupplyResolutionResult(requested_provider="openai", requested_model="gpt-4o")
    assert "authority" in r.to_dict()


def test_29_supply_resolution_result_to_dict_authority_equals_sentinel():
    from core.llm.supply_authority import LLM_SUPPLY_AUTHORITY, SupplyResolutionResult
    r = SupplyResolutionResult(requested_provider="openai", requested_model="gpt-4o")
    assert r.to_dict()["authority"] == LLM_SUPPLY_AUTHORITY


# ---------------------------------------------------------------------------
# 30-36: LLMSupplyAuthority class and factory
# ---------------------------------------------------------------------------


def test_30_llm_supply_authority_importable():
    from core.llm.supply_authority import LLMSupplyAuthority
    assert LLMSupplyAuthority is not None


def test_31_llm_supply_authority_has_resolve_supply():
    from core.llm.supply_authority import LLMSupplyAuthority
    auth = LLMSupplyAuthority()
    assert callable(getattr(auth, "resolve_supply", None))


def test_32_llm_supply_authority_has_policy_property():
    from core.llm.supply_authority import LLMSupplyAuthority, ProviderOrderingPolicy
    auth = LLMSupplyAuthority()
    assert isinstance(auth.policy, ProviderOrderingPolicy)


def test_33_get_llm_supply_authority_importable():
    from core.llm.supply_authority import get_llm_supply_authority
    assert callable(get_llm_supply_authority)


def test_34_get_llm_supply_authority_returns_instance():
    from core.llm.supply_authority import LLMSupplyAuthority, get_llm_supply_authority, refresh_llm_supply_authority
    refresh_llm_supply_authority()  # ensure fresh singleton
    auth = get_llm_supply_authority()
    assert isinstance(auth, LLMSupplyAuthority)


def test_35_get_llm_supply_authority_singleton():
    from core.llm.supply_authority import get_llm_supply_authority, refresh_llm_supply_authority
    refresh_llm_supply_authority()
    a1 = get_llm_supply_authority()
    a2 = get_llm_supply_authority()
    assert a1 is a2


def test_36_refresh_llm_supply_authority_fresh_instance():
    from core.llm.supply_authority import (
        LLMSupplyAuthority,
        get_llm_supply_authority,
        refresh_llm_supply_authority,
    )
    refresh_llm_supply_authority()
    old = get_llm_supply_authority()
    fresh = refresh_llm_supply_authority()
    assert isinstance(fresh, LLMSupplyAuthority)
    assert get_llm_supply_authority() is fresh


# ---------------------------------------------------------------------------
# 37-55: resolve_supply behaviour
# ---------------------------------------------------------------------------


def test_37_resolve_supply_healthy_primary_satisfies():
    from core.llm.supply_authority import LLMSupplyAuthority
    auth = LLMSupplyAuthority()
    supply = _make_supply_state_dict(
        providers={"openai": _healthy_provider_record("openai", "gpt-4o")},
        available_ids=["openai"],
    )
    decision = _make_route_decision("openai", "gpt-4o")
    result = auth.resolve_supply(decision, supply)
    assert result.is_satisfied is True


def test_38_resolve_supply_result_has_authority_sentinel():
    from core.llm.supply_authority import LLM_SUPPLY_AUTHORITY, LLMSupplyAuthority
    auth = LLMSupplyAuthority()
    supply = _make_supply_state_dict(
        providers={"openai": _healthy_provider_record("openai", "gpt-4o")},
        available_ids=["openai"],
    )
    decision = _make_route_decision("openai", "gpt-4o")
    result = auth.resolve_supply(decision, supply)
    assert result.authority == LLM_SUPPLY_AUTHORITY


def test_39_resolve_supply_primary_fallback_legality_none():
    from core.llm.supply_authority import FallbackLegality, LLMSupplyAuthority
    auth = LLMSupplyAuthority()
    supply = _make_supply_state_dict(
        providers={"openai": _healthy_provider_record("openai", "gpt-4o")},
        available_ids=["openai"],
    )
    decision = _make_route_decision("openai", "gpt-4o")
    result = auth.resolve_supply(decision, supply)
    assert result.fallback_legality == FallbackLegality.NONE


def test_40_resolve_supply_down_primary_falls_back():
    from core.llm.supply_authority import LLMSupplyAuthority
    auth = LLMSupplyAuthority()
    supply = _make_supply_state_dict(
        providers={
            "openai": _down_provider_record("openai", "gpt-4o"),
            "anthropic": _healthy_provider_record("anthropic", "claude-sonnet-4-6-20251022"),
        },
        available_ids=["anthropic"],
        fallback_candidates=["anthropic"],
    )
    decision = _make_route_decision("openai", "gpt-4o")
    result = auth.resolve_supply(decision, supply)
    assert result.is_satisfied is True
    assert result.supplied_provider == "anthropic"


def test_41_resolve_supply_down_primary_legality_primary_unavailable():
    from core.llm.supply_authority import FallbackLegality, LLMSupplyAuthority
    auth = LLMSupplyAuthority()
    supply = _make_supply_state_dict(
        providers={
            "openai": _down_provider_record("openai", "gpt-4o"),
            "anthropic": _healthy_provider_record("anthropic", "claude-sonnet-4-6-20251022"),
        },
        available_ids=["anthropic"],
        fallback_candidates=["anthropic"],
    )
    decision = _make_route_decision("openai", "gpt-4o")
    result = auth.resolve_supply(decision, supply)
    assert result.fallback_legality == FallbackLegality.PRIMARY_UNAVAILABLE


def test_42_resolve_supply_trace_records_skipped_primary():
    from core.llm.supply_authority import LLMSupplyAuthority
    auth = LLMSupplyAuthority()
    supply = _make_supply_state_dict(
        providers={
            "openai": _down_provider_record("openai", "gpt-4o"),
            "anthropic": _healthy_provider_record("anthropic", "claude-sonnet-4-6-20251022"),
        },
        available_ids=["anthropic"],
        fallback_candidates=["anthropic"],
    )
    decision = _make_route_decision("openai", "gpt-4o")
    result = auth.resolve_supply(decision, supply)
    skipped = [s for s in result.resolution_trace if s.skipped and s.provider == "openai"]
    assert len(skipped) >= 1


def test_43_resolve_supply_trace_records_selected_secondary():
    from core.llm.supply_authority import LLMSupplyAuthority
    auth = LLMSupplyAuthority()
    supply = _make_supply_state_dict(
        providers={
            "openai": _down_provider_record("openai", "gpt-4o"),
            "anthropic": _healthy_provider_record("anthropic", "claude-sonnet-4-6-20251022"),
        },
        available_ids=["anthropic"],
        fallback_candidates=["anthropic"],
    )
    decision = _make_route_decision("openai", "gpt-4o")
    result = auth.resolve_supply(decision, supply)
    selected = [s for s in result.resolution_trace if s.selected]
    assert len(selected) == 1
    assert selected[0].provider == "anthropic"


def test_44_resolve_supply_no_available_providers_not_satisfied():
    from core.llm.supply_authority import LLMSupplyAuthority
    auth = LLMSupplyAuthority()
    supply = _make_supply_state_dict(
        providers={
            "openai": _down_provider_record("openai", "gpt-4o"),
        },
        available_ids=[],
    )
    decision = _make_route_decision("openai", "gpt-4o")
    result = auth.resolve_supply(decision, supply)
    assert result.is_satisfied is False


def test_45_resolve_supply_no_available_legality_no_supply():
    from core.llm.supply_authority import FallbackLegality, LLMSupplyAuthority
    auth = LLMSupplyAuthority()
    supply = _make_supply_state_dict(
        providers={
            "openai": _down_provider_record("openai", "gpt-4o"),
        },
        available_ids=[],
    )
    decision = _make_route_decision("openai", "gpt-4o")
    result = auth.resolve_supply(decision, supply)
    assert result.fallback_legality == FallbackLegality.NO_SUPPLY_AVAILABLE


def test_46_resolve_supply_fallback_supplied_differs_from_requested():
    from core.llm.supply_authority import LLMSupplyAuthority
    auth = LLMSupplyAuthority()
    supply = _make_supply_state_dict(
        providers={
            "openai": _down_provider_record("openai", "gpt-4o"),
            "anthropic": _healthy_provider_record("anthropic", "claude-sonnet-4-6-20251022"),
        },
        available_ids=["anthropic"],
        fallback_candidates=["anthropic"],
    )
    decision = _make_route_decision("openai", "gpt-4o")
    result = auth.resolve_supply(decision, supply)
    assert result.supplied_provider != result.requested_provider


def test_47_resolve_supply_degraded_primary_allowed_by_policy():
    from core.llm.supply_authority import FallbackLegality, LLMSupplyAuthority, ProviderOrderingPolicy
    policy = ProviderOrderingPolicy(allow_degraded_fallback=True)
    auth = LLMSupplyAuthority(policy=policy)
    supply = _make_supply_state_dict(
        providers={"openai": _degraded_provider_record("openai", "gpt-4o")},
        available_ids=["openai"],
    )
    decision = _make_route_decision("openai", "gpt-4o")
    result = auth.resolve_supply(decision, supply)
    # Degraded but allowed: primary is used
    assert result.is_satisfied is True
    assert result.supplied_provider == "openai"
    assert result.fallback_legality == FallbackLegality.NONE


def test_48_resolve_supply_degraded_primary_not_allowed_falls_back():
    from core.llm.supply_authority import LLMSupplyAuthority, ProviderOrderingPolicy
    policy = ProviderOrderingPolicy(allow_degraded_fallback=False)
    auth = LLMSupplyAuthority(policy=policy)
    supply = _make_supply_state_dict(
        providers={
            "openai": _degraded_provider_record("openai", "gpt-4o"),
            "anthropic": _healthy_provider_record("anthropic", "claude-sonnet-4-6-20251022"),
        },
        available_ids=["openai", "anthropic"],
        fallback_candidates=["anthropic"],
    )
    decision = _make_route_decision("openai", "gpt-4o")
    result = auth.resolve_supply(decision, supply)
    assert result.supplied_provider == "anthropic"


def test_49_resolve_supply_degraded_fallback_legality_primary_degraded():
    from core.llm.supply_authority import FallbackLegality, LLMSupplyAuthority, ProviderOrderingPolicy
    policy = ProviderOrderingPolicy(allow_degraded_fallback=False)
    auth = LLMSupplyAuthority(policy=policy)
    supply = _make_supply_state_dict(
        providers={
            "openai": _degraded_provider_record("openai", "gpt-4o"),
            "anthropic": _healthy_provider_record("anthropic", "claude-sonnet-4-6-20251022"),
        },
        available_ids=["openai", "anthropic"],
        fallback_candidates=["anthropic"],
    )
    decision = _make_route_decision("openai", "gpt-4o")
    result = auth.resolve_supply(decision, supply)
    assert result.fallback_legality == FallbackLegality.PRIMARY_DEGRADED


def test_50_resolve_supply_max_fallback_depth_zero_no_fallback():
    from core.llm.supply_authority import LLMSupplyAuthority, ProviderOrderingPolicy
    policy = ProviderOrderingPolicy(max_fallback_depth=0)
    auth = LLMSupplyAuthority(policy=policy)
    supply = _make_supply_state_dict(
        providers={
            "openai": _down_provider_record("openai", "gpt-4o"),
            "anthropic": _healthy_provider_record("anthropic", "claude-sonnet-4-6-20251022"),
        },
        available_ids=["anthropic"],
        fallback_candidates=["anthropic"],
    )
    decision = _make_route_decision("openai", "gpt-4o")
    result = auth.resolve_supply(decision, supply)
    assert result.is_satisfied is False


def test_51_resolve_supply_uses_canonical_fallback_candidates_list():
    from core.llm.supply_authority import LLMSupplyAuthority
    auth = LLMSupplyAuthority()
    # anthropic is in fallback_candidates; gemini is available but not in candidates
    supply = _make_supply_state_dict(
        providers={
            "openai": _down_provider_record("openai", "gpt-4o"),
            "anthropic": _healthy_provider_record("anthropic", "claude-sonnet-4-6-20251022"),
            "gemini": _healthy_provider_record("gemini", "gemini-pro"),
        },
        available_ids=["anthropic", "gemini"],
        fallback_candidates=["anthropic"],
    )
    decision = _make_route_decision("openai", "gpt-4o")
    result = auth.resolve_supply(decision, supply)
    # Should select anthropic (first in fallback_candidates) not gemini
    assert result.supplied_provider == "anthropic"


def test_52_resolve_supply_resolution_trace_non_empty():
    from core.llm.supply_authority import LLMSupplyAuthority
    auth = LLMSupplyAuthority()
    supply = _make_supply_state_dict(
        providers={"openai": _healthy_provider_record("openai", "gpt-4o")},
        available_ids=["openai"],
    )
    decision = _make_route_decision("openai", "gpt-4o")
    result = auth.resolve_supply(decision, supply)
    assert len(result.resolution_trace) > 0


def test_53_resolve_supply_ordering_basis_non_empty():
    from core.llm.supply_authority import LLMSupplyAuthority
    auth = LLMSupplyAuthority()
    supply = _make_supply_state_dict(
        providers={"openai": _healthy_provider_record("openai", "gpt-4o")},
        available_ids=["openai"],
    )
    decision = _make_route_decision("openai", "gpt-4o")
    result = auth.resolve_supply(decision, supply)
    assert isinstance(result.ordering_basis, str)
    assert len(result.ordering_basis) > 0


def test_54_resolve_supply_healthy_primary_is_satisfied():
    from core.llm.supply_authority import LLMSupplyAuthority
    auth = LLMSupplyAuthority()
    supply = _make_supply_state_dict(
        providers={"openai": _healthy_provider_record("openai", "gpt-4o")},
        available_ids=["openai"],
    )
    decision = _make_route_decision("openai", "gpt-4o")
    result = auth.resolve_supply(decision, supply)
    assert result.is_satisfied is True


def test_55_resolve_supply_to_dict_json_serialisable():
    from core.llm.supply_authority import LLMSupplyAuthority
    auth = LLMSupplyAuthority()
    supply = _make_supply_state_dict(
        providers={"openai": _healthy_provider_record("openai", "gpt-4o")},
        available_ids=["openai"],
    )
    decision = _make_route_decision("openai", "gpt-4o")
    result = auth.resolve_supply(decision, supply)
    serialised = json.dumps(result.to_dict())
    assert len(serialised) > 0


# ---------------------------------------------------------------------------
# 56-61: core.llm package re-exports
# ---------------------------------------------------------------------------


def test_56_llm_supply_authority_re_exported_from_core_llm():
    from core.llm import LLM_SUPPLY_AUTHORITY
    assert LLM_SUPPLY_AUTHORITY is not None


def test_57_fallback_legality_re_exported_from_core_llm():
    from core.llm import FallbackLegality
    assert FallbackLegality is not None


def test_58_provider_ordering_policy_re_exported_from_core_llm():
    from core.llm import ProviderOrderingPolicy
    assert ProviderOrderingPolicy is not None


def test_59_supply_resolution_result_re_exported_from_core_llm():
    from core.llm import SupplyResolutionResult
    assert SupplyResolutionResult is not None


def test_60_llm_supply_authority_class_re_exported_from_core_llm():
    from core.llm import LLMSupplyAuthority
    assert LLMSupplyAuthority is not None


def test_61_get_llm_supply_authority_re_exported_from_core_llm():
    from core.llm import get_llm_supply_authority
    assert callable(get_llm_supply_authority)


# ---------------------------------------------------------------------------
# 62: L1 vs L2 sentinel distinction
# ---------------------------------------------------------------------------


def test_62_supply_authority_differs_from_route_authority():
    from core.llm.route_authority import LLM_ROUTE_AUTHORITY
    from core.llm.supply_authority import LLM_SUPPLY_AUTHORITY
    assert LLM_SUPPLY_AUTHORITY != LLM_ROUTE_AUTHORITY


# ---------------------------------------------------------------------------
# 63-67: docs/MODEL_ROUTING_AUTHORITY.md section 10
# ---------------------------------------------------------------------------


def _read_routing_authority_doc() -> str:
    doc_path = os.path.join(
        _REPO_ROOT, "docs", "MODEL_ROUTING_AUTHORITY.md"
    )
    if not os.path.exists(doc_path):
        return ""
    with open(doc_path, encoding="utf-8") as f:
        return f.read()


def test_63_docs_mentions_llm_supply_authority_sentinel():
    content = _read_routing_authority_doc()
    assert "LLM_SUPPLY_AUTHORITY" in content


def test_64_docs_mentions_llm_supply_authority_class():
    content = _read_routing_authority_doc()
    assert "LLMSupplyAuthority" in content


def test_65_docs_mentions_fallback_legality():
    content = _read_routing_authority_doc()
    assert "FallbackLegality" in content


def test_66_docs_mentions_supply_resolution_result():
    content = _read_routing_authority_doc()
    assert "SupplyResolutionResult" in content


def test_67_docs_section_10_exists():
    content = _read_routing_authority_doc()
    assert "## 10." in content


# ---------------------------------------------------------------------------
# 68-75: Edge cases
# ---------------------------------------------------------------------------


def test_68_resolve_supply_none_supply_state_not_satisfied():
    from core.llm.supply_authority import LLMSupplyAuthority
    auth = LLMSupplyAuthority()
    decision = _make_route_decision("openai", "gpt-4o")
    result = auth.resolve_supply(decision, None)
    assert result.is_satisfied is False


def test_69_resolve_supply_empty_supply_dict_not_satisfied():
    from core.llm.supply_authority import LLMSupplyAuthority
    auth = LLMSupplyAuthority()
    decision = _make_route_decision("openai", "gpt-4o")
    result = auth.resolve_supply(decision, {})
    assert result.is_satisfied is False


def test_70_resolve_supply_requested_provider_preserved():
    from core.llm.supply_authority import LLMSupplyAuthority
    auth = LLMSupplyAuthority()
    supply = _make_supply_state_dict(
        providers={"openai": _healthy_provider_record("openai", "gpt-4o")},
        available_ids=["openai"],
    )
    decision = _make_route_decision("openai", "gpt-4o")
    result = auth.resolve_supply(decision, supply)
    assert result.requested_provider == "openai"


def test_71_resolve_supply_requested_model_preserved():
    from core.llm.supply_authority import LLMSupplyAuthority
    auth = LLMSupplyAuthority()
    supply = _make_supply_state_dict(
        providers={"openai": _healthy_provider_record("openai", "gpt-4o")},
        available_ids=["openai"],
    )
    decision = _make_route_decision("openai", "gpt-4o")
    result = auth.resolve_supply(decision, supply)
    assert result.requested_model == "gpt-4o"


def test_72_supply_resolution_step_fallback_legality_string_in_to_dict():
    from core.llm.supply_authority import FallbackLegality, SupplyResolutionStep
    step = SupplyResolutionStep(
        provider="openai",
        model="gpt-4o",
        skipped=True,
        skip_reason="provider_down",
        fallback_legality=FallbackLegality.PRIMARY_UNAVAILABLE,
    )
    d = step.to_dict()
    assert isinstance(d["fallback_legality"], str)
    assert d["fallback_legality"] == "primary_unavailable"


def test_73_supply_resolution_result_fallback_legality_string_in_to_dict():
    from core.llm.supply_authority import FallbackLegality, SupplyResolutionResult
    r = SupplyResolutionResult(
        requested_provider="openai",
        requested_model="gpt-4o",
        fallback_legality=FallbackLegality.PRIMARY_UNAVAILABLE,
    )
    d = r.to_dict()
    assert isinstance(d["fallback_legality"], str)
    assert d["fallback_legality"] == "primary_unavailable"


def test_74_resolve_supply_capability_mismatch_when_required():
    """Provider lacking required capabilities triggers CAPABILITY_MISMATCH fallback."""
    from core.llm.supply_authority import FallbackLegality, LLMSupplyAuthority, ProviderOrderingPolicy
    policy = ProviderOrderingPolicy(required_capabilities=["tool_use"])
    auth = LLMSupplyAuthority(policy=policy)

    # openai record has no capability info (None) => fails capability check
    # anthropic has capability with supports_tools=True
    supply = _make_supply_state_dict(
        providers={
            "openai": {
                "provider_id": "openai",
                "health_status": "healthy",
                "default_model": "gpt-4o",
                "models": ["gpt-4o"],
                "is_available": True,
                "capability": None,  # no capability record
            },
            "anthropic": {
                "provider_id": "anthropic",
                "health_status": "healthy",
                "default_model": "claude-sonnet-4-6-20251022",
                "models": ["claude-sonnet-4-6-20251022"],
                "is_available": True,
                "capability": {"supports_tools": True, "is_natively_multimodal": False},
            },
        },
        available_ids=["openai", "anthropic"],
        fallback_candidates=["anthropic"],
    )
    decision = _make_route_decision("openai", "gpt-4o")
    result = auth.resolve_supply(decision, supply)
    assert result.supplied_provider == "anthropic"
    assert result.fallback_legality == FallbackLegality.CAPABILITY_MISMATCH


def test_75_core_llm_supply_authority_module_importable():
    import importlib
    mod = importlib.import_module("core.llm.supply_authority")
    assert mod is not None
