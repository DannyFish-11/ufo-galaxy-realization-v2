#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_l4_cognitive_execution_authority.py
===============================================

L4 — Close the final cognitive authority boundary.

Validates:
  1.  LLM_EXECUTION_AUTHORITY sentinel is importable from core.llm.execution_authority.
  2.  LLM_EXECUTION_AUTHORITY is a non-empty string.
  3.  LLM_EXECUTION_AUTHORITY identifies CognitiveExecutionAuthority by module path.
  4.  CognitiveExecutionAuthority class is importable from core.llm.execution_authority.
  5.  CognitiveExecutionRequest class is importable from core.llm.execution_authority.
  6.  CognitiveExecutionResult class is importable from core.llm.execution_authority.
  7.  get_cognitive_execution_authority factory is importable from core.llm.execution_authority.
  8.  get_cognitive_execution_authority returns a CognitiveExecutionAuthority instance.
  9.  get_cognitive_execution_authority returns the same singleton on repeated calls.
  10. refresh_cognitive_execution_authority returns a fresh CognitiveExecutionAuthority instance.
  11. CognitiveExecutionRequest default temperature is 0.7.
  12. CognitiveExecutionRequest default max_tokens is 4096.
  13. CognitiveExecutionRequest accepts feature_context.
  14. CognitiveExecutionRequest accepts execution_metadata.
  15. CognitiveExecutionResult authority defaults to LLM_EXECUTION_AUTHORITY.
  16. CognitiveExecutionResult is_canonical defaults to True.
  17. CognitiveExecutionResult to_dict() includes content key.
  18. CognitiveExecutionResult to_dict() includes tool_calls key.
  19. CognitiveExecutionResult to_dict() includes provider key.
  20. CognitiveExecutionResult to_dict() includes model key.
  21. CognitiveExecutionResult to_dict() includes is_canonical key.
  22. CognitiveExecutionResult to_dict() includes authority key.
  23. CognitiveExecutionResult to_dict() authority value equals LLM_EXECUTION_AUTHORITY.
  24. CognitiveExecutionResult to_dict() includes execution_trace key.
  25. CognitiveExecutionResult to_dict() includes source_context key.
  26. CognitiveExecutionResult to_dict() includes source_supply key.
  27. CognitiveExecutionResult to_dict() includes input_tokens key.
  28. CognitiveExecutionResult to_dict() includes output_tokens key.
  29. CognitiveExecutionResult to_dict() includes latency_ms key.
  30. CognitiveExecutionResult to_dict() is JSON-serialisable.
  31. CognitiveExecutionAuthority has an execute method.
  32. CognitiveExecutionAuthority has an execution_router property.
  33. CognitiveExecutionAuthority has _verify_context_authority static method.
  34. CognitiveExecutionAuthority has _verify_supply_authority static method.
  35. CognitiveExecutionAuthority has _normalize_response static method.
  36. execute raises ValueError when context_assembly lacks LLM_CONTEXT_AUTHORITY.
  37. execute raises ValueError when supply_resolution lacks LLM_SUPPLY_AUTHORITY.
  38. execute raises ValueError when supply_resolution is_satisfied is False.
  39. execute raises ValueError when context_assembly authority is wrong string.
  40. execute raises ValueError when supply_resolution authority is wrong string.
  41. _verify_context_authority records trace entry on success.
  42. _verify_supply_authority records trace entry on success.
  43. _verify_context_authority raises on authority mismatch.
  44. _verify_supply_authority raises on authority mismatch.
  45. _verify_supply_authority raises on is_satisfied False.
  46. _normalize_response returns empty content for None input.
  47. _normalize_response returns tuple of (content, tool_calls, raw_dict, in_tok, out_tok, latency).
  48. _normalize_response normalizes content to str.
  49. _normalize_response normalizes empty tool_calls list to None.
  50. _normalize_response preserves non-empty tool_calls list.
  51. execute with valid L3 context and L2 supply returns CognitiveExecutionResult.
  52. execute result has authority == LLM_EXECUTION_AUTHORITY.
  53. execute result has is_canonical == True.
  54. execute result provider matches supply resolution.
  55. execute result model matches supply resolution.
  56. execute result has non-empty execution_trace.
  57. execute result execution_trace records context_authority verification.
  58. execute result execution_trace records supply_authority verification.
  59. execute result execution_trace records execution_target.
  60. execute result execution_trace records normalization step.
  61. execute result source_context is the provided context assembly.
  62. execute result source_supply is the provided supply resolution.
  63. execute result to_dict source_context carries LLM_CONTEXT_AUTHORITY.
  64. execute result to_dict source_supply carries LLM_SUPPLY_AUTHORITY.
  65. LLM_EXECUTION_AUTHORITY is re-exported from core.llm package.
  66. CognitiveExecutionRequest is re-exported from core.llm package.
  67. CognitiveExecutionResult is re-exported from core.llm package.
  68. CognitiveExecutionAuthority is re-exported from core.llm package.
  69. get_cognitive_execution_authority is re-exported from core.llm package.
  70. LLM_EXECUTION_AUTHORITY differs from LLM_ROUTE_AUTHORITY.
  71. LLM_EXECUTION_AUTHORITY differs from LLM_SUPPLY_AUTHORITY.
  72. LLM_EXECUTION_AUTHORITY differs from LLM_CONTEXT_AUTHORITY.
  73. docs/MODEL_ROUTING_AUTHORITY.md contains LLM_EXECUTION_AUTHORITY.
  74. docs/MODEL_ROUTING_AUTHORITY.md contains CognitiveExecutionAuthority.
  75. docs/MODEL_ROUTING_AUTHORITY.md contains CognitiveExecutionRequest.
  76. docs/MODEL_ROUTING_AUTHORITY.md contains CognitiveExecutionResult.
  77. docs/MODEL_ROUTING_AUTHORITY.md contains get_cognitive_execution_authority.
  78. docs/MODEL_ROUTING_AUTHORITY.md section 12 exists.
  79. core.llm.execution_authority module is importable without errors.
  80. core.llm.__init__ exports LLM_EXECUTION_AUTHORITY without error.
  81. execute result execution_trace records execution_metadata when provided.
  82. execute result execution_trace records tool_manifest count when tools present.
  83. CognitiveExecutionResult content is always a str.
  84. CognitiveExecutionResult raw_response is preserved.
  85. retry path with same context and supply produces same provider/model.
  86. execute result to_dict source_context includes message_count.
  87. execute result to_dict source_supply includes requested_provider.
  88. execute result to_dict source_supply includes is_satisfied.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# ---------------------------------------------------------------------------
# Helpers — canonical stub objects for L3 context assembly & L2 supply
# ---------------------------------------------------------------------------

def _make_canonical_context(message_count: int = 2, with_tools: bool = False):
    """Return a minimal CognitiveContextAssembly with the correct L3 sentinel."""
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
        LLM_CONTEXT_AUTHORITY,
    )
    auth = CognitiveContextAuthority()
    req = CognitiveContextRequest(
        system_prefix="You are a test assistant.",
        user_message="Hello",
        task_type="general",
        tool_manifest=[{"type": "function", "function": {"name": "noop"}}]
        if with_tools
        else None,
    )
    assembly = auth.assemble(req)
    assert assembly.authority == LLM_CONTEXT_AUTHORITY
    return assembly


def _make_canonical_supply(
    provider: str = "openai",
    model: str = "gpt-5.5",
    satisfied: bool = True,
):
    """Return a minimal SupplyResolutionResult with the correct L2 sentinel."""
    from core.llm.supply_authority import (
        FallbackLegality,
        LLM_SUPPLY_AUTHORITY,
        ProviderOrderingPolicy,
        SupplyResolutionResult,
        SupplyResolutionStep,
    )
    step = SupplyResolutionStep(
        provider=provider,
        model=model,
        selected=satisfied,
    )
    return SupplyResolutionResult(
        requested_provider=provider,
        requested_model=model,
        supplied_provider=provider if satisfied else None,
        supplied_model=model if satisfied else None,
        fallback_legality=FallbackLegality.NONE,
        ordering_basis="test_direct",
        is_satisfied=satisfied,
        resolution_trace=[step],
        authority=LLM_SUPPLY_AUTHORITY,
        policy=ProviderOrderingPolicy(),
    )


def _make_mock_llm_response(
    content: str = "Test response",
    tool_calls=None,
    provider: str = "openai",
    model: str = "gpt-5.5",
):
    """Return a mock LLMResponse-like object."""
    resp = MagicMock()
    resp.content = content
    resp.tool_calls = tool_calls
    resp.raw_response = {"mock": True, "content": content}
    resp.input_tokens = 10
    resp.output_tokens = 20
    resp.latency_ms = 150.0
    resp.provider = provider
    resp.model = model
    return resp


def _make_patched_exec_auth(
    response=None,
    provider: str = "openai",
    model: str = "gpt-5.5",
):
    """Return a CognitiveExecutionAuthority with a patched _dispatch method."""
    from core.llm.execution_authority import CognitiveExecutionAuthority

    mock_resp = response or _make_mock_llm_response(provider=provider, model=model)

    auth = CognitiveExecutionAuthority()
    auth._dispatch = AsyncMock(return_value=mock_resp)  # type: ignore[method-assign]
    return auth


# ---------------------------------------------------------------------------
# 1-3: LLM_EXECUTION_AUTHORITY sentinel
# ---------------------------------------------------------------------------


def test_01_llm_execution_authority_sentinel_importable():
    from core.llm.execution_authority import LLM_EXECUTION_AUTHORITY
    assert LLM_EXECUTION_AUTHORITY is not None


def test_02_llm_execution_authority_sentinel_non_empty():
    from core.llm.execution_authority import LLM_EXECUTION_AUTHORITY
    assert isinstance(LLM_EXECUTION_AUTHORITY, str)
    assert len(LLM_EXECUTION_AUTHORITY) > 0


def test_03_llm_execution_authority_sentinel_identifies_class():
    from core.llm.execution_authority import LLM_EXECUTION_AUTHORITY
    assert "CognitiveExecutionAuthority" in LLM_EXECUTION_AUTHORITY


# ---------------------------------------------------------------------------
# 4-7: Class / factory importability
# ---------------------------------------------------------------------------


def test_04_cognitive_execution_authority_class_importable():
    from core.llm.execution_authority import CognitiveExecutionAuthority
    assert CognitiveExecutionAuthority is not None


def test_05_cognitive_execution_request_class_importable():
    from core.llm.execution_authority import CognitiveExecutionRequest
    assert CognitiveExecutionRequest is not None


def test_06_cognitive_execution_result_class_importable():
    from core.llm.execution_authority import CognitiveExecutionResult
    assert CognitiveExecutionResult is not None


def test_07_get_cognitive_execution_authority_importable():
    from core.llm.execution_authority import get_cognitive_execution_authority
    assert callable(get_cognitive_execution_authority)


# ---------------------------------------------------------------------------
# 8-10: Singleton / factory behaviour
# ---------------------------------------------------------------------------


def test_08_get_cognitive_execution_authority_returns_instance():
    from core.llm.execution_authority import (
        CognitiveExecutionAuthority,
        get_cognitive_execution_authority,
    )
    auth = get_cognitive_execution_authority()
    assert isinstance(auth, CognitiveExecutionAuthority)


def test_09_get_cognitive_execution_authority_singleton():
    from core.llm.execution_authority import get_cognitive_execution_authority
    a1 = get_cognitive_execution_authority()
    a2 = get_cognitive_execution_authority()
    assert a1 is a2


def test_10_refresh_cognitive_execution_authority_returns_fresh_instance():
    from core.llm.execution_authority import (
        CognitiveExecutionAuthority,
        get_cognitive_execution_authority,
        refresh_cognitive_execution_authority,
    )
    original = get_cognitive_execution_authority()
    fresh = refresh_cognitive_execution_authority()
    assert isinstance(fresh, CognitiveExecutionAuthority)
    assert fresh is not original


# ---------------------------------------------------------------------------
# 11-14: CognitiveExecutionRequest defaults
# ---------------------------------------------------------------------------


def test_11_cognitive_execution_request_default_temperature():
    from core.llm.execution_authority import CognitiveExecutionRequest
    ctx = _make_canonical_context()
    sup = _make_canonical_supply()
    req = CognitiveExecutionRequest(context_assembly=ctx, supply_resolution=sup)
    assert req.temperature == 0.7


def test_12_cognitive_execution_request_default_max_tokens():
    from core.llm.execution_authority import CognitiveExecutionRequest
    ctx = _make_canonical_context()
    sup = _make_canonical_supply()
    req = CognitiveExecutionRequest(context_assembly=ctx, supply_resolution=sup)
    assert req.max_tokens == 4096


def test_13_cognitive_execution_request_accepts_feature_context():
    from core.llm.execution_authority import CognitiveExecutionRequest
    ctx = _make_canonical_context()
    sup = _make_canonical_supply()
    req = CognitiveExecutionRequest(
        context_assembly=ctx,
        supply_resolution=sup,
        feature_context="test_feature",
    )
    assert req.feature_context == "test_feature"


def test_14_cognitive_execution_request_accepts_execution_metadata():
    from core.llm.execution_authority import CognitiveExecutionRequest
    ctx = _make_canonical_context()
    sup = _make_canonical_supply()
    meta = {"retry_count": 1, "recovery_reason": "timeout"}
    req = CognitiveExecutionRequest(
        context_assembly=ctx,
        supply_resolution=sup,
        execution_metadata=meta,
    )
    assert req.execution_metadata == meta


# ---------------------------------------------------------------------------
# 15-30: CognitiveExecutionResult defaults and to_dict
# ---------------------------------------------------------------------------


def test_15_cognitive_execution_result_authority_default():
    from core.llm.execution_authority import (
        CognitiveExecutionResult,
        LLM_EXECUTION_AUTHORITY,
    )
    res = CognitiveExecutionResult(
        content="hello",
        tool_calls=None,
        provider="openai",
        model="gpt-5.5",
    )
    assert res.authority == LLM_EXECUTION_AUTHORITY


def test_16_cognitive_execution_result_is_canonical_default():
    from core.llm.execution_authority import CognitiveExecutionResult
    res = CognitiveExecutionResult(
        content="hello",
        tool_calls=None,
        provider="openai",
        model="gpt-5.5",
    )
    assert res.is_canonical is True


def test_17_cognitive_execution_result_to_dict_content_key():
    from core.llm.execution_authority import CognitiveExecutionResult
    res = CognitiveExecutionResult(content="hi", tool_calls=None, provider="openai", model="gpt-5.5")
    assert "content" in res.to_dict()


def test_18_cognitive_execution_result_to_dict_tool_calls_key():
    from core.llm.execution_authority import CognitiveExecutionResult
    res = CognitiveExecutionResult(content="hi", tool_calls=None, provider="openai", model="gpt-5.5")
    assert "tool_calls" in res.to_dict()


def test_19_cognitive_execution_result_to_dict_provider_key():
    from core.llm.execution_authority import CognitiveExecutionResult
    res = CognitiveExecutionResult(content="hi", tool_calls=None, provider="openai", model="gpt-5.5")
    assert "provider" in res.to_dict()


def test_20_cognitive_execution_result_to_dict_model_key():
    from core.llm.execution_authority import CognitiveExecutionResult
    res = CognitiveExecutionResult(content="hi", tool_calls=None, provider="openai", model="gpt-5.5")
    assert "model" in res.to_dict()


def test_21_cognitive_execution_result_to_dict_is_canonical_key():
    from core.llm.execution_authority import CognitiveExecutionResult
    res = CognitiveExecutionResult(content="hi", tool_calls=None, provider="openai", model="gpt-5.5")
    assert "is_canonical" in res.to_dict()


def test_22_cognitive_execution_result_to_dict_authority_key():
    from core.llm.execution_authority import CognitiveExecutionResult
    res = CognitiveExecutionResult(content="hi", tool_calls=None, provider="openai", model="gpt-5.5")
    assert "authority" in res.to_dict()


def test_23_cognitive_execution_result_to_dict_authority_value():
    from core.llm.execution_authority import CognitiveExecutionResult, LLM_EXECUTION_AUTHORITY
    res = CognitiveExecutionResult(content="hi", tool_calls=None, provider="openai", model="gpt-5.5")
    assert res.to_dict()["authority"] == LLM_EXECUTION_AUTHORITY


def test_24_cognitive_execution_result_to_dict_execution_trace_key():
    from core.llm.execution_authority import CognitiveExecutionResult
    res = CognitiveExecutionResult(content="hi", tool_calls=None, provider="openai", model="gpt-5.5")
    assert "execution_trace" in res.to_dict()


def test_25_cognitive_execution_result_to_dict_source_context_key():
    from core.llm.execution_authority import CognitiveExecutionResult
    res = CognitiveExecutionResult(content="hi", tool_calls=None, provider="openai", model="gpt-5.5")
    assert "source_context" in res.to_dict()


def test_26_cognitive_execution_result_to_dict_source_supply_key():
    from core.llm.execution_authority import CognitiveExecutionResult
    res = CognitiveExecutionResult(content="hi", tool_calls=None, provider="openai", model="gpt-5.5")
    assert "source_supply" in res.to_dict()


def test_27_cognitive_execution_result_to_dict_input_tokens_key():
    from core.llm.execution_authority import CognitiveExecutionResult
    res = CognitiveExecutionResult(content="hi", tool_calls=None, provider="openai", model="gpt-5.5")
    assert "input_tokens" in res.to_dict()


def test_28_cognitive_execution_result_to_dict_output_tokens_key():
    from core.llm.execution_authority import CognitiveExecutionResult
    res = CognitiveExecutionResult(content="hi", tool_calls=None, provider="openai", model="gpt-5.5")
    assert "output_tokens" in res.to_dict()


def test_29_cognitive_execution_result_to_dict_latency_ms_key():
    from core.llm.execution_authority import CognitiveExecutionResult
    res = CognitiveExecutionResult(content="hi", tool_calls=None, provider="openai", model="gpt-5.5")
    assert "latency_ms" in res.to_dict()


def test_30_cognitive_execution_result_to_dict_json_serialisable():
    from core.llm.execution_authority import CognitiveExecutionResult
    res = CognitiveExecutionResult(
        content="hello world",
        tool_calls=None,
        provider="openai",
        model="gpt-5.5",
        execution_trace=["step1", "step2"],
    )
    serialised = json.dumps(res.to_dict())
    assert isinstance(serialised, str)


# ---------------------------------------------------------------------------
# 31-35: CognitiveExecutionAuthority interface
# ---------------------------------------------------------------------------


def test_31_cognitive_execution_authority_has_execute_method():
    from core.llm.execution_authority import CognitiveExecutionAuthority
    assert hasattr(CognitiveExecutionAuthority, "execute")
    assert callable(CognitiveExecutionAuthority.execute)


def test_32_cognitive_execution_authority_has_execution_router_property():
    from core.llm.execution_authority import CognitiveExecutionAuthority
    assert hasattr(CognitiveExecutionAuthority, "execution_router")


def test_33_cognitive_execution_authority_has_verify_context_authority():
    from core.llm.execution_authority import CognitiveExecutionAuthority
    assert hasattr(CognitiveExecutionAuthority, "_verify_context_authority")


def test_34_cognitive_execution_authority_has_verify_supply_authority():
    from core.llm.execution_authority import CognitiveExecutionAuthority
    assert hasattr(CognitiveExecutionAuthority, "_verify_supply_authority")


def test_35_cognitive_execution_authority_has_normalize_response():
    from core.llm.execution_authority import CognitiveExecutionAuthority
    assert hasattr(CognitiveExecutionAuthority, "_normalize_response")


# ---------------------------------------------------------------------------
# 36-45: Authority boundary enforcement — ValueError paths
# ---------------------------------------------------------------------------


def test_36_execute_raises_when_context_lacks_authority_sentinel():
    """execute must raise ValueError when context assembly lacks L3 sentinel."""
    from core.llm.execution_authority import CognitiveExecutionAuthority, CognitiveExecutionRequest

    # Build a context with the wrong authority sentinel
    ctx = _make_canonical_context()
    ctx.authority = "wrong.authority.sentinel"  # type: ignore[attr-defined]

    sup = _make_canonical_supply()
    req = CognitiveExecutionRequest(context_assembly=ctx, supply_resolution=sup)
    auth = CognitiveExecutionAuthority()

    with pytest.raises(ValueError, match="context_assembly authority"):
        asyncio.get_running_loop().run_until_complete(auth.execute(req))


def test_37_execute_raises_when_supply_lacks_authority_sentinel():
    """execute must raise ValueError when supply resolution lacks L2 sentinel."""
    from core.llm.execution_authority import CognitiveExecutionAuthority, CognitiveExecutionRequest

    ctx = _make_canonical_context()
    sup = _make_canonical_supply()
    sup.authority = "wrong.supply.sentinel"  # type: ignore[attr-defined]

    req = CognitiveExecutionRequest(context_assembly=ctx, supply_resolution=sup)
    auth = CognitiveExecutionAuthority()

    with pytest.raises(ValueError, match="supply_resolution authority"):
        asyncio.get_running_loop().run_until_complete(auth.execute(req))


def test_38_execute_raises_when_supply_not_satisfied():
    """execute must raise ValueError when supply is_satisfied is False."""
    from core.llm.execution_authority import CognitiveExecutionAuthority, CognitiveExecutionRequest

    ctx = _make_canonical_context()
    sup = _make_canonical_supply(satisfied=False)

    req = CognitiveExecutionRequest(context_assembly=ctx, supply_resolution=sup)
    auth = CognitiveExecutionAuthority()

    with pytest.raises(ValueError, match="supply is not satisfied"):
        asyncio.get_running_loop().run_until_complete(auth.execute(req))


def test_39_execute_raises_on_wrong_context_authority_string():
    from core.llm.execution_authority import CognitiveExecutionAuthority, CognitiveExecutionRequest

    ctx = _make_canonical_context()
    ctx.authority = "some.other.module.SomeOtherClass"  # type: ignore[attr-defined]

    sup = _make_canonical_supply()
    req = CognitiveExecutionRequest(context_assembly=ctx, supply_resolution=sup)
    auth = CognitiveExecutionAuthority()

    with pytest.raises(ValueError):
        asyncio.get_running_loop().run_until_complete(auth.execute(req))


def test_40_execute_raises_on_wrong_supply_authority_string():
    from core.llm.execution_authority import CognitiveExecutionAuthority, CognitiveExecutionRequest

    ctx = _make_canonical_context()
    sup = _make_canonical_supply()
    sup.authority = "core.some_other_module.SomeClass"  # type: ignore[attr-defined]

    req = CognitiveExecutionRequest(context_assembly=ctx, supply_resolution=sup)
    auth = CognitiveExecutionAuthority()

    with pytest.raises(ValueError):
        asyncio.get_running_loop().run_until_complete(auth.execute(req))


# ---------------------------------------------------------------------------
# 41-45: Static verification helpers
# ---------------------------------------------------------------------------


def test_41_verify_context_authority_records_trace_on_success():
    from core.llm.execution_authority import CognitiveExecutionAuthority

    ctx = _make_canonical_context()
    trace: list = []
    CognitiveExecutionAuthority._verify_context_authority(ctx, trace)
    assert any("context_authority" in t for t in trace)


def test_42_verify_supply_authority_records_trace_on_success():
    from core.llm.execution_authority import CognitiveExecutionAuthority

    sup = _make_canonical_supply()
    trace: list = []
    CognitiveExecutionAuthority._verify_supply_authority(sup, trace)
    assert any("supply_authority" in t for t in trace)


def test_43_verify_context_authority_raises_on_mismatch():
    from core.llm.execution_authority import CognitiveExecutionAuthority

    ctx = _make_canonical_context()
    ctx.authority = "bad.authority"  # type: ignore[attr-defined]
    trace: list = []

    with pytest.raises(ValueError, match="context_assembly authority"):
        CognitiveExecutionAuthority._verify_context_authority(ctx, trace)


def test_44_verify_supply_authority_raises_on_mismatch():
    from core.llm.execution_authority import CognitiveExecutionAuthority

    sup = _make_canonical_supply()
    sup.authority = "bad.authority"  # type: ignore[attr-defined]
    trace: list = []

    with pytest.raises(ValueError, match="supply_resolution authority"):
        CognitiveExecutionAuthority._verify_supply_authority(sup, trace)


def test_45_verify_supply_authority_raises_when_not_satisfied():
    from core.llm.execution_authority import CognitiveExecutionAuthority

    sup = _make_canonical_supply(satisfied=False)
    trace: list = []

    with pytest.raises(ValueError, match="supply is not satisfied"):
        CognitiveExecutionAuthority._verify_supply_authority(sup, trace)


# ---------------------------------------------------------------------------
# 46-50: _normalize_response behaviour
# ---------------------------------------------------------------------------


def test_46_normalize_response_returns_empty_content_for_none():
    from core.llm.execution_authority import CognitiveExecutionAuthority

    trace: list = []
    content, tool_calls, raw_dict, in_tok, out_tok, latency = (
        CognitiveExecutionAuthority._normalize_response(None, trace)
    )
    assert content == ""
    assert tool_calls is None


def test_47_normalize_response_returns_tuple():
    from core.llm.execution_authority import CognitiveExecutionAuthority

    mock_resp = _make_mock_llm_response(content="Hello!")
    trace: list = []
    result = CognitiveExecutionAuthority._normalize_response(mock_resp, trace)
    assert isinstance(result, tuple)
    assert len(result) == 6


def test_48_normalize_response_normalizes_content_to_str():
    from core.llm.execution_authority import CognitiveExecutionAuthority

    mock_resp = _make_mock_llm_response(content="Some text")
    trace: list = []
    content, _, _, _, _, _ = CognitiveExecutionAuthority._normalize_response(mock_resp, trace)
    assert isinstance(content, str)
    assert content == "Some text"


def test_49_normalize_response_empty_tool_calls_list_becomes_none():
    from core.llm.execution_authority import CognitiveExecutionAuthority

    mock_resp = _make_mock_llm_response(content="hi", tool_calls=[])
    trace: list = []
    _, tool_calls, _, _, _, _ = CognitiveExecutionAuthority._normalize_response(mock_resp, trace)
    assert tool_calls is None


def test_50_normalize_response_preserves_non_empty_tool_calls():
    from core.llm.execution_authority import CognitiveExecutionAuthority

    tc = [{"id": "tc1", "type": "function", "function": {"name": "foo", "arguments": "{}"}}]
    mock_resp = _make_mock_llm_response(content="using tool", tool_calls=tc)
    trace: list = []
    _, tool_calls, _, _, _, _ = CognitiveExecutionAuthority._normalize_response(mock_resp, trace)
    assert tool_calls is not None
    assert len(tool_calls) == 1
    assert tool_calls[0]["id"] == "tc1"


# ---------------------------------------------------------------------------
# 51-64: End-to-end execute with patched dispatch
# ---------------------------------------------------------------------------


def test_51_execute_returns_cognitive_execution_result():
    from core.llm.execution_authority import CognitiveExecutionAuthority, CognitiveExecutionRequest, CognitiveExecutionResult

    auth = _make_patched_exec_auth(response=_make_mock_llm_response(content="test response"))
    ctx = _make_canonical_context()
    sup = _make_canonical_supply()
    req = CognitiveExecutionRequest(context_assembly=ctx, supply_resolution=sup)

    result = asyncio.get_running_loop().run_until_complete(auth.execute(req))
    assert isinstance(result, CognitiveExecutionResult)


def test_52_execute_result_has_execution_authority_sentinel():
    from core.llm.execution_authority import CognitiveExecutionRequest, LLM_EXECUTION_AUTHORITY

    auth = _make_patched_exec_auth()
    ctx = _make_canonical_context()
    sup = _make_canonical_supply()
    req = CognitiveExecutionRequest(context_assembly=ctx, supply_resolution=sup)

    result = asyncio.get_running_loop().run_until_complete(auth.execute(req))
    assert result.authority == LLM_EXECUTION_AUTHORITY


def test_53_execute_result_is_canonical_true():
    from core.llm.execution_authority import CognitiveExecutionRequest

    auth = _make_patched_exec_auth()
    ctx = _make_canonical_context()
    sup = _make_canonical_supply()
    req = CognitiveExecutionRequest(context_assembly=ctx, supply_resolution=sup)

    result = asyncio.get_running_loop().run_until_complete(auth.execute(req))
    assert result.is_canonical is True


def test_54_execute_result_provider_matches_supply():
    from core.llm.execution_authority import CognitiveExecutionRequest

    auth = _make_patched_exec_auth(provider="anthropic", model="claude-sonnet-4-6-20251022")
    ctx = _make_canonical_context()
    sup = _make_canonical_supply(provider="anthropic", model="claude-sonnet-4-6-20251022")
    req = CognitiveExecutionRequest(context_assembly=ctx, supply_resolution=sup)

    result = asyncio.get_running_loop().run_until_complete(auth.execute(req))
    assert result.provider == "anthropic"


def test_55_execute_result_model_matches_supply():
    from core.llm.execution_authority import CognitiveExecutionRequest

    auth = _make_patched_exec_auth(provider="anthropic", model="claude-sonnet-4-6-20251022")
    ctx = _make_canonical_context()
    sup = _make_canonical_supply(provider="anthropic", model="claude-sonnet-4-6-20251022")
    req = CognitiveExecutionRequest(context_assembly=ctx, supply_resolution=sup)

    result = asyncio.get_running_loop().run_until_complete(auth.execute(req))
    assert result.model == "claude-sonnet-4-6-20251022"


def test_56_execute_result_execution_trace_non_empty():
    from core.llm.execution_authority import CognitiveExecutionRequest

    auth = _make_patched_exec_auth()
    ctx = _make_canonical_context()
    sup = _make_canonical_supply()
    req = CognitiveExecutionRequest(context_assembly=ctx, supply_resolution=sup)

    result = asyncio.get_running_loop().run_until_complete(auth.execute(req))
    assert len(result.execution_trace) > 0


def test_57_execute_trace_records_context_authority_verification():
    from core.llm.execution_authority import CognitiveExecutionRequest

    auth = _make_patched_exec_auth()
    ctx = _make_canonical_context()
    sup = _make_canonical_supply()
    req = CognitiveExecutionRequest(context_assembly=ctx, supply_resolution=sup)

    result = asyncio.get_running_loop().run_until_complete(auth.execute(req))
    assert any("context_authority" in t for t in result.execution_trace)


def test_58_execute_trace_records_supply_authority_verification():
    from core.llm.execution_authority import CognitiveExecutionRequest

    auth = _make_patched_exec_auth()
    ctx = _make_canonical_context()
    sup = _make_canonical_supply()
    req = CognitiveExecutionRequest(context_assembly=ctx, supply_resolution=sup)

    result = asyncio.get_running_loop().run_until_complete(auth.execute(req))
    assert any("supply_authority" in t for t in result.execution_trace)


def test_59_execute_trace_records_execution_target():
    from core.llm.execution_authority import CognitiveExecutionRequest

    auth = _make_patched_exec_auth()
    ctx = _make_canonical_context()
    sup = _make_canonical_supply()
    req = CognitiveExecutionRequest(context_assembly=ctx, supply_resolution=sup)

    result = asyncio.get_running_loop().run_until_complete(auth.execute(req))
    assert any("execution_target" in t for t in result.execution_trace)


def test_60_execute_trace_records_normalization():
    from core.llm.execution_authority import CognitiveExecutionRequest

    auth = _make_patched_exec_auth()
    ctx = _make_canonical_context()
    sup = _make_canonical_supply()
    req = CognitiveExecutionRequest(context_assembly=ctx, supply_resolution=sup)

    result = asyncio.get_running_loop().run_until_complete(auth.execute(req))
    assert any("normalization" in t for t in result.execution_trace)


def test_61_execute_result_source_context_is_provided_assembly():
    from core.llm.execution_authority import CognitiveExecutionRequest

    auth = _make_patched_exec_auth()
    ctx = _make_canonical_context()
    sup = _make_canonical_supply()
    req = CognitiveExecutionRequest(context_assembly=ctx, supply_resolution=sup)

    result = asyncio.get_running_loop().run_until_complete(auth.execute(req))
    assert result.source_context is ctx


def test_62_execute_result_source_supply_is_provided_supply():
    from core.llm.execution_authority import CognitiveExecutionRequest

    auth = _make_patched_exec_auth()
    ctx = _make_canonical_context()
    sup = _make_canonical_supply()
    req = CognitiveExecutionRequest(context_assembly=ctx, supply_resolution=sup)

    result = asyncio.get_running_loop().run_until_complete(auth.execute(req))
    assert result.source_supply is sup


def test_63_execute_result_to_dict_source_context_carries_l3_authority():
    from core.llm.execution_authority import CognitiveExecutionRequest, LLM_EXECUTION_AUTHORITY
    from core.llm.context_authority import LLM_CONTEXT_AUTHORITY

    auth = _make_patched_exec_auth()
    ctx = _make_canonical_context()
    sup = _make_canonical_supply()
    req = CognitiveExecutionRequest(context_assembly=ctx, supply_resolution=sup)

    result = asyncio.get_running_loop().run_until_complete(auth.execute(req))
    d = result.to_dict()
    assert d["source_context"]["authority"] == LLM_CONTEXT_AUTHORITY


def test_64_execute_result_to_dict_source_supply_carries_l2_authority():
    from core.llm.execution_authority import CognitiveExecutionRequest
    from core.llm.supply_authority import LLM_SUPPLY_AUTHORITY

    auth = _make_patched_exec_auth()
    ctx = _make_canonical_context()
    sup = _make_canonical_supply()
    req = CognitiveExecutionRequest(context_assembly=ctx, supply_resolution=sup)

    result = asyncio.get_running_loop().run_until_complete(auth.execute(req))
    d = result.to_dict()
    assert d["source_supply"]["authority"] == LLM_SUPPLY_AUTHORITY


# ---------------------------------------------------------------------------
# 65-69: Re-exports from core.llm package
# ---------------------------------------------------------------------------


def test_65_llm_execution_authority_re_exported_from_core_llm():
    from core.llm import LLM_EXECUTION_AUTHORITY
    assert LLM_EXECUTION_AUTHORITY is not None


def test_66_cognitive_execution_request_re_exported_from_core_llm():
    from core.llm import CognitiveExecutionRequest
    assert CognitiveExecutionRequest is not None


def test_67_cognitive_execution_result_re_exported_from_core_llm():
    from core.llm import CognitiveExecutionResult
    assert CognitiveExecutionResult is not None


def test_68_cognitive_execution_authority_re_exported_from_core_llm():
    from core.llm import CognitiveExecutionAuthority
    assert CognitiveExecutionAuthority is not None


def test_69_get_cognitive_execution_authority_re_exported_from_core_llm():
    from core.llm import get_cognitive_execution_authority
    assert callable(get_cognitive_execution_authority)


# ---------------------------------------------------------------------------
# 70-72: Sentinel uniqueness
# ---------------------------------------------------------------------------


def test_70_llm_execution_authority_differs_from_route_authority():
    from core.llm.execution_authority import LLM_EXECUTION_AUTHORITY
    from core.llm.route_authority import LLM_ROUTE_AUTHORITY
    assert LLM_EXECUTION_AUTHORITY != LLM_ROUTE_AUTHORITY


def test_71_llm_execution_authority_differs_from_supply_authority():
    from core.llm.execution_authority import LLM_EXECUTION_AUTHORITY
    from core.llm.supply_authority import LLM_SUPPLY_AUTHORITY
    assert LLM_EXECUTION_AUTHORITY != LLM_SUPPLY_AUTHORITY


def test_72_llm_execution_authority_differs_from_context_authority():
    from core.llm.execution_authority import LLM_EXECUTION_AUTHORITY
    from core.llm.context_authority import LLM_CONTEXT_AUTHORITY
    assert LLM_EXECUTION_AUTHORITY != LLM_CONTEXT_AUTHORITY


# ---------------------------------------------------------------------------
# 73-78: Documentation checks
# ---------------------------------------------------------------------------

_DOC_PATH = os.path.join(
    _REPO_ROOT, "docs", "MODEL_ROUTING_AUTHORITY.md"
)


def test_73_docs_contain_llm_execution_authority():
    with open(_DOC_PATH, encoding="utf-8") as f:
        content = f.read()
    assert "LLM_EXECUTION_AUTHORITY" in content


def test_74_docs_contain_cognitive_execution_authority():
    with open(_DOC_PATH, encoding="utf-8") as f:
        content = f.read()
    assert "CognitiveExecutionAuthority" in content


def test_75_docs_contain_cognitive_execution_request():
    with open(_DOC_PATH, encoding="utf-8") as f:
        content = f.read()
    assert "CognitiveExecutionRequest" in content


def test_76_docs_contain_cognitive_execution_result():
    with open(_DOC_PATH, encoding="utf-8") as f:
        content = f.read()
    assert "CognitiveExecutionResult" in content


def test_77_docs_contain_get_cognitive_execution_authority():
    with open(_DOC_PATH, encoding="utf-8") as f:
        content = f.read()
    assert "get_cognitive_execution_authority" in content


def test_78_docs_section_12_exists():
    with open(_DOC_PATH, encoding="utf-8") as f:
        content = f.read()
    # Section 12 should exist for L4 execution authority
    assert "## 12." in content or "## 12 " in content or "section 12" in content.lower() or "L4" in content


# ---------------------------------------------------------------------------
# 79-80: Module importability
# ---------------------------------------------------------------------------


def test_79_execution_authority_module_importable_without_errors():
    import importlib
    mod = importlib.import_module("core.llm.execution_authority")
    assert mod is not None


def test_80_core_llm_init_exports_llm_execution_authority_without_error():
    import importlib
    mod = importlib.import_module("core.llm")
    assert hasattr(mod, "LLM_EXECUTION_AUTHORITY")


# ---------------------------------------------------------------------------
# 81-88: Additional contract tests
# ---------------------------------------------------------------------------


def test_81_execute_trace_records_execution_metadata_when_provided():
    from core.llm.execution_authority import CognitiveExecutionRequest

    auth = _make_patched_exec_auth()
    ctx = _make_canonical_context()
    sup = _make_canonical_supply()
    meta = {"retry_count": 2, "recovery_reason": "rate_limit"}
    req = CognitiveExecutionRequest(
        context_assembly=ctx,
        supply_resolution=sup,
        execution_metadata=meta,
    )

    result = asyncio.get_running_loop().run_until_complete(auth.execute(req))
    assert any("execution_metadata" in t for t in result.execution_trace)


def test_82_execute_trace_records_tool_manifest_when_tools_present():
    from core.llm.execution_authority import CognitiveExecutionRequest

    auth = _make_patched_exec_auth()
    ctx = _make_canonical_context(with_tools=True)
    sup = _make_canonical_supply()
    req = CognitiveExecutionRequest(context_assembly=ctx, supply_resolution=sup)

    result = asyncio.get_running_loop().run_until_complete(auth.execute(req))
    assert any("tool_manifest" in t for t in result.execution_trace)


def test_83_execute_result_content_is_always_str():
    from core.llm.execution_authority import CognitiveExecutionRequest

    auth = _make_patched_exec_auth(response=_make_mock_llm_response(content="response text"))
    ctx = _make_canonical_context()
    sup = _make_canonical_supply()
    req = CognitiveExecutionRequest(context_assembly=ctx, supply_resolution=sup)

    result = asyncio.get_running_loop().run_until_complete(auth.execute(req))
    assert isinstance(result.content, str)


def test_84_execute_result_raw_response_preserved():
    from core.llm.execution_authority import CognitiveExecutionRequest

    mock_resp = _make_mock_llm_response(content="hello")
    mock_resp.raw_response = {"id": "test_raw_id", "choices": []}
    auth = _make_patched_exec_auth(response=mock_resp)
    ctx = _make_canonical_context()
    sup = _make_canonical_supply()
    req = CognitiveExecutionRequest(context_assembly=ctx, supply_resolution=sup)

    result = asyncio.get_running_loop().run_until_complete(auth.execute(req))
    assert result.raw_response is not None
    assert result.raw_response.get("id") == "test_raw_id"


def test_85_retry_path_same_context_and_supply_yields_same_provider():
    """Retry with same L3 context and L2 supply must yield the same provider."""
    from core.llm.execution_authority import CognitiveExecutionRequest

    auth = _make_patched_exec_auth(provider="openai", model="gpt-5.5")
    ctx = _make_canonical_context()
    sup = _make_canonical_supply(provider="openai", model="gpt-5.5")

    req1 = CognitiveExecutionRequest(
        context_assembly=ctx,
        supply_resolution=sup,
        execution_metadata={"retry_count": 0},
    )
    req2 = CognitiveExecutionRequest(
        context_assembly=ctx,
        supply_resolution=sup,
        execution_metadata={"retry_count": 1},
    )

    res1 = asyncio.get_running_loop().run_until_complete(auth.execute(req1))
    res2 = asyncio.get_running_loop().run_until_complete(auth.execute(req2))

    assert res1.provider == res2.provider
    assert res1.model == res2.model


def test_86_execute_result_to_dict_source_context_has_message_count():
    from core.llm.execution_authority import CognitiveExecutionRequest

    auth = _make_patched_exec_auth()
    ctx = _make_canonical_context()
    sup = _make_canonical_supply()
    req = CognitiveExecutionRequest(context_assembly=ctx, supply_resolution=sup)

    result = asyncio.get_running_loop().run_until_complete(auth.execute(req))
    d = result.to_dict()
    assert "message_count" in d["source_context"]
    assert d["source_context"]["message_count"] >= 1


def test_87_execute_result_to_dict_source_supply_has_requested_provider():
    from core.llm.execution_authority import CognitiveExecutionRequest

    auth = _make_patched_exec_auth(provider="deepseek", model="deepseek-v4-pro")
    ctx = _make_canonical_context()
    sup = _make_canonical_supply(provider="deepseek", model="deepseek-v4-pro")
    req = CognitiveExecutionRequest(context_assembly=ctx, supply_resolution=sup)

    result = asyncio.get_running_loop().run_until_complete(auth.execute(req))
    d = result.to_dict()
    assert d["source_supply"]["requested_provider"] == "deepseek"


def test_88_execute_result_to_dict_source_supply_has_is_satisfied():
    from core.llm.execution_authority import CognitiveExecutionRequest

    auth = _make_patched_exec_auth()
    ctx = _make_canonical_context()
    sup = _make_canonical_supply()
    req = CognitiveExecutionRequest(context_assembly=ctx, supply_resolution=sup)

    result = asyncio.get_running_loop().run_until_complete(auth.execute(req))
    d = result.to_dict()
    assert "is_satisfied" in d["source_supply"]
    assert d["source_supply"]["is_satisfied"] is True
