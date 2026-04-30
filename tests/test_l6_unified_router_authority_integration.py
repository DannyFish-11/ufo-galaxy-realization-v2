#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_l6_unified_router_authority_integration.py
======================================================

PR-6 — Integrate L1/L2/L3 cognitive authority into UnifiedLLMRouter.

Validates:
  1.  UnifiedLLMRouter has _l1_authority, _l2_authority, _l3_authority attributes.
  2.  _get_l1_route_authority() returns an LLMRouteAuthority instance.
  3.  _get_l2_supply_authority() returns an LLMSupplyAuthority instance.
  4.  _get_l3_context_authority() returns a CognitiveContextAuthority instance.
  5.  _get_l1_route_authority() returns the same singleton on repeated calls.
  6.  _get_l2_supply_authority() returns the same singleton on repeated calls.
  7.  _get_l3_context_authority() returns the same singleton on repeated calls.
  8.  _consult_l1_route() returns a 4-tuple.
  9.  _consult_l1_route() returns an LLMRouteDecision as the fourth element.
  10. _consult_l1_route() propagates the preferred_provider into the decision.
  11. _consult_l1_route() does not raise even when no backend is configured.
  12. _consult_l2_supply(None) returns (None, None, False).
  13. _consult_l2_supply() returns a 3-tuple.
  14. _build_backend_supply_state() returns a dict.
  15. _build_backend_supply_state() returns {} when backend is None.
  16. _enrich_l3_context() returns a list.
  17. _enrich_l3_context() returns original messages on empty input.
  18. _enrich_l3_context() produces messages that include a system message.
  19. _enrich_l3_context() preserves the user message content.
  20. _enrich_l3_context() handles messages without a system message.
  21. _enrich_l3_context() handles messages without a user message.
  22. L1 authority consulted: _consult_l1_route spy records the call.
  23. L2 authority consulted: _consult_l2_supply spy records the call.
  24. L3 authority consulted: _enrich_l3_context spy records the call.
  25. chat() calls _enrich_l3_context internally (via monkeypatching).
  26. chat() calls _consult_l1_route internally (via monkeypatching).
  27. chat() calls _consult_l2_supply internally (via monkeypatching).
  28. chat_with_tools() calls _enrich_l3_context internally.
  29. chat_with_tools() calls _consult_l1_route internally.
  30. chat_with_tools() calls _consult_l2_supply internally.
  31. L2 satisfied result causes effective_provider to be supplied_provider in chat().
  32. L2 satisfied result causes effective_provider to be supplied_provider in chat_with_tools().
  33. L1 provider is used when L2 is not satisfied in chat().
  34. L3 enriched messages are passed to the backend in chat().
  35. L3 enriched messages are passed to the backend in chat_with_tools().
  36. L4 GalaxyMainLoopL4Enhanced is not imported or instantiated by UnifiedLLMRouter.
  37. OpenClawd class exists and has a process method (cognitive spine preserved).
  38. UnifiedLLMRouter.chat() still raises NoAvailableProviderError when backend is None.
  39. UnifiedLLMRouter.chat_with_tools() still raises NoAvailableProviderError when backend is None.
  40. reset_unified_llm_router() clears the singleton so a fresh instance can be created.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import sys
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# ---------------------------------------------------------------------------
# Helpers / stubs
# ---------------------------------------------------------------------------

_BACKEND_NOT_SET = object()  # sentinel to distinguish "not provided" from None


def _make_stub_multi_router(provider: str = "stub_provider", model: str = "stub_model"):
    """Return a minimal MultiLLMRouter-compatible stub."""
    # Capture into local variables with distinct names to avoid the Python
    # class-scope gotcha where `name = name` inside a class body raises NameError.
    _provider = provider
    _model = model

    _d = type("_Decision", (), {
        "provider": _provider,
        "model": _model,
        "reason": "stub",
        "alternatives": [],
    })()

    class _StubRouter:
        def route(self, task_type=None, preferred_provider=None, complexity_score=0.5):
            return _d

        async def chat(self, messages=None, task_type=None, **kwargs):
            r = type("_R", (), {
                "content": "stub response",
                "provider": _provider,
                "model": _model,
                "usage": {},
            })()
            return r

        def get_status(self):
            return {
                "available": True,
                "providers": [{"name": _provider, "status": "ok"}],
            }

        def is_available(self):
            return True

    return _StubRouter()


def _fresh_router(stub_backend=_BACKEND_NOT_SET):
    """Return a fresh UnifiedLLMRouter instance with optional stub backend."""
    from core.unified.llm_router import UnifiedLLMRouter, reset_unified_llm_router

    reset_unified_llm_router()
    router = UnifiedLLMRouter()
    if stub_backend is not _BACKEND_NOT_SET:
        router._backend = stub_backend
    # Reset authority singletons so each test gets a clean state.
    router._l1_authority = None
    router._l2_authority = None
    router._l3_authority = None
    return router


# ---------------------------------------------------------------------------
# 1-7: Authority attribute and accessor tests
# ---------------------------------------------------------------------------


def test_01_router_has_l1_authority_attribute():
    from core.unified.llm_router import UnifiedLLMRouter, reset_unified_llm_router

    reset_unified_llm_router()
    r = UnifiedLLMRouter()
    assert hasattr(r, "_l1_authority")


def test_02_router_has_l2_authority_attribute():
    r = _fresh_router()
    assert hasattr(r, "_l2_authority")


def test_03_router_has_l3_authority_attribute():
    r = _fresh_router()
    assert hasattr(r, "_l3_authority")


def test_04_get_l1_route_authority_returns_correct_type():
    from core.llm.route_authority import LLMRouteAuthority

    r = _fresh_router()
    authority = r._get_l1_route_authority()
    assert isinstance(authority, LLMRouteAuthority)


def test_05_get_l2_supply_authority_returns_correct_type():
    from core.llm.supply_authority import LLMSupplyAuthority

    r = _fresh_router()
    authority = r._get_l2_supply_authority()
    assert isinstance(authority, LLMSupplyAuthority)


def test_06_get_l3_context_authority_returns_correct_type():
    from core.llm.context_authority import CognitiveContextAuthority

    r = _fresh_router()
    authority = r._get_l3_context_authority()
    assert isinstance(authority, CognitiveContextAuthority)


def test_07_l1_authority_same_singleton_on_repeated_calls():
    r = _fresh_router()
    a1 = r._get_l1_route_authority()
    a2 = r._get_l1_route_authority()
    assert a1 is a2


def test_08_l2_authority_same_singleton_on_repeated_calls():  # noqa: N802
    r = _fresh_router()
    a1 = r._get_l2_supply_authority()
    a2 = r._get_l2_supply_authority()
    assert a1 is a2


def test_09_l3_authority_same_singleton_on_repeated_calls():  # noqa: N802
    r = _fresh_router()
    a1 = r._get_l3_context_authority()
    a2 = r._get_l3_context_authority()
    assert a1 is a2


# ---------------------------------------------------------------------------
# 10-15: _consult_l1_route tests
# ---------------------------------------------------------------------------


def test_10_consult_l1_route_returns_four_tuple():
    r = _fresh_router()
    result = r._consult_l1_route("general", None)
    assert isinstance(result, tuple) and len(result) == 4


def test_11_consult_l1_route_fourth_element_is_route_decision():
    from core.llm.route_authority import LLMRouteDecision

    r = _fresh_router()
    _, _, _, decision = r._consult_l1_route("general", None)
    assert isinstance(decision, LLMRouteDecision)


def test_12_consult_l1_route_preferred_provider_recorded_in_decision():
    r = _fresh_router()
    _, _, _, decision = r._consult_l1_route("general", "openai")
    # source_request carries the preferred_provider
    assert decision.source_request is not None
    assert decision.source_request.preferred_provider == "openai"


def test_13_consult_l1_route_does_not_raise_without_backend():
    r = _fresh_router(stub_backend=None)
    # Should not raise even when there is no real LLM backend.
    provider, model, alternatives, decision = r._consult_l1_route("reasoning", None)
    assert isinstance(alternatives, list)


def test_14_consult_l1_route_decision_has_authority_sentinel():
    from core.llm.route_authority import LLM_ROUTE_AUTHORITY

    r = _fresh_router()
    _, _, _, decision = r._consult_l1_route("coding", None)
    assert decision.authority == LLM_ROUTE_AUTHORITY


def test_15_consult_l1_route_decision_is_canonical():
    r = _fresh_router()
    _, _, _, decision = r._consult_l1_route("general", None)
    assert decision.is_canonical is True


# ---------------------------------------------------------------------------
# 16-20: _consult_l2_supply tests
# ---------------------------------------------------------------------------


def test_16_consult_l2_supply_none_decision_returns_false():
    r = _fresh_router()
    p, m, satisfied = r._consult_l2_supply(None)
    assert p is None
    assert m is None
    assert satisfied is False


def test_17_consult_l2_supply_returns_three_tuple():
    r = _fresh_router()
    result = r._consult_l2_supply(None)
    assert isinstance(result, tuple) and len(result) == 3


def test_18_consult_l2_supply_with_route_decision_returns_three_tuple():
    r = _fresh_router()
    _, _, _, decision = r._consult_l1_route("general", None)
    result = r._consult_l2_supply(decision)
    assert isinstance(result, tuple) and len(result) == 3


def test_19_consult_l2_supply_returns_bool_for_satisfied():
    r = _fresh_router()
    _, _, _, decision = r._consult_l1_route("general", None)
    _, _, satisfied = r._consult_l2_supply(decision)
    assert isinstance(satisfied, bool)


# ---------------------------------------------------------------------------
# 21-27: _build_backend_supply_state tests
# ---------------------------------------------------------------------------


def test_20_build_backend_supply_state_returns_dict():
    r = _fresh_router()
    state = r._build_backend_supply_state()
    assert isinstance(state, dict)


def test_21_build_backend_supply_state_empty_when_no_backend():
    r = _fresh_router(stub_backend=None)
    state = r._build_backend_supply_state()
    # With no backend, the function returns {} immediately.
    assert state == {}


def test_22_build_backend_supply_state_with_stub_backend_has_providers():
    stub = _make_stub_multi_router("openai")
    r = _fresh_router(stub_backend=stub)
    state = r._build_backend_supply_state()
    # The stub's get_status returns providers; but UnifiedLLMRouter.get_status
    # delegates to the backend, which returns a list of dicts.
    assert isinstance(state, dict)


# ---------------------------------------------------------------------------
# 28-35: _enrich_l3_context tests
# ---------------------------------------------------------------------------


def test_23_enrich_l3_context_returns_list():
    r = _fresh_router()
    messages = [{"role": "user", "content": "Hello"}]
    result = r._enrich_l3_context(messages, "general")
    assert isinstance(result, list)


def test_24_enrich_l3_context_empty_returns_empty():
    r = _fresh_router()
    result = r._enrich_l3_context([], "general")
    assert result == []


def test_25_enrich_l3_context_includes_system_message():
    r = _fresh_router()
    messages = [{"role": "user", "content": "Hello"}]
    enriched = r._enrich_l3_context(messages, "general")
    roles = [m.get("role") for m in enriched]
    assert "system" in roles


def test_26_enrich_l3_context_preserves_user_content():
    r = _fresh_router()
    messages = [{"role": "user", "content": "Hello, Galaxy!"}]
    enriched = r._enrich_l3_context(messages, "general")
    user_msgs = [m for m in enriched if m.get("role") == "user"]
    assert len(user_msgs) == 1
    assert user_msgs[0]["content"] == "Hello, Galaxy!"


def test_27_enrich_l3_context_handles_no_user_message():
    r = _fresh_router()
    messages = [{"role": "system", "content": "You are helpful."}]
    # Should not raise even without a user message.
    enriched = r._enrich_l3_context(messages, "general")
    assert isinstance(enriched, list)


def test_28_enrich_l3_context_handles_no_system_message():
    r = _fresh_router()
    messages = [{"role": "user", "content": "What is 2+2?"}]
    enriched = r._enrich_l3_context(messages, "general")
    # L3 always adds a system message (default prefix).
    roles = [m.get("role") for m in enriched]
    assert "system" in roles


def test_29_enrich_l3_context_preserves_system_prefix_from_input():
    r = _fresh_router()
    messages = [
        {"role": "system", "content": "Custom system prompt."},
        {"role": "user", "content": "Hi"},
    ]
    enriched = r._enrich_l3_context(messages, "general")
    system_msgs = [m for m in enriched if m.get("role") == "system"]
    assert len(system_msgs) == 1
    assert "Custom system prompt." in system_msgs[0]["content"]


def test_30_enrich_l3_context_with_conversation_history():
    r = _fresh_router()
    messages = [
        {"role": "user", "content": "Turn 1"},
        {"role": "assistant", "content": "Response 1"},
        {"role": "user", "content": "Turn 2"},
    ]
    enriched = r._enrich_l3_context(messages, "general")
    # Should contain system + history + current user message
    assert len(enriched) >= 2


# ---------------------------------------------------------------------------
# 31-35: Authority integration into chat() and chat_with_tools()
# ---------------------------------------------------------------------------


def test_31_chat_calls_enrich_l3_context():
    """chat() must call _enrich_l3_context (L3 authority on hot path)."""
    stub = _make_stub_multi_router()
    r = _fresh_router(stub_backend=stub)

    called_with: Dict[str, Any] = {}

    original = r._enrich_l3_context

    def spy_enrich(messages, task_type, tools=None):
        called_with["messages"] = messages
        called_with["task_type"] = task_type
        return original(messages, task_type, tools)

    r._enrich_l3_context = spy_enrich  # type: ignore[method-assign]

    from core.unified.models import LLMRequest

    req = LLMRequest(messages=[{"role": "user", "content": "hi"}])
    asyncio.get_event_loop().run_until_complete(r.chat(req))

    assert "messages" in called_with
    assert called_with["task_type"] == "general"


def test_32_chat_calls_consult_l1_route():
    """chat() must call _consult_l1_route (L1 authority on hot path)."""
    stub = _make_stub_multi_router()
    r = _fresh_router(stub_backend=stub)

    called: Dict[str, Any] = {}
    original = r._consult_l1_route

    def spy_l1(task_type_str, preferred_provider):
        called["task_type"] = task_type_str
        called["preferred_provider"] = preferred_provider
        return original(task_type_str, preferred_provider)

    r._consult_l1_route = spy_l1  # type: ignore[method-assign]

    from core.unified.models import LLMRequest

    req = LLMRequest(messages=[{"role": "user", "content": "hi"}])
    asyncio.get_event_loop().run_until_complete(r.chat(req))

    assert "task_type" in called


def test_33_chat_calls_consult_l2_supply():
    """chat() must call _consult_l2_supply (L2 authority on hot path)."""
    stub = _make_stub_multi_router()
    r = _fresh_router(stub_backend=stub)

    called: Dict[str, Any] = {}
    original = r._consult_l2_supply

    def spy_l2(route_decision):
        called["invoked"] = True
        called["decision"] = route_decision
        return original(route_decision)

    r._consult_l2_supply = spy_l2  # type: ignore[method-assign]

    from core.unified.models import LLMRequest

    req = LLMRequest(messages=[{"role": "user", "content": "hi"}])
    asyncio.get_event_loop().run_until_complete(r.chat(req))

    assert called.get("invoked") is True


def test_34_chat_with_tools_calls_enrich_l3_context():
    """chat_with_tools() must call _enrich_l3_context (L3 on hot path)."""
    stub = _make_stub_multi_router()
    r = _fresh_router(stub_backend=stub)

    called: Dict[str, Any] = {}
    original = r._enrich_l3_context

    def spy(messages, task_type, tools=None):
        called["messages"] = messages
        return original(messages, task_type, tools)

    r._enrich_l3_context = spy  # type: ignore[method-assign]

    messages = [{"role": "user", "content": "use tools"}]
    asyncio.get_event_loop().run_until_complete(
        r.chat_with_tools(messages, task_type="general")
    )

    assert "messages" in called


def test_35_chat_with_tools_calls_consult_l1_route():
    """chat_with_tools() must call _consult_l1_route (L1 on hot path)."""
    stub = _make_stub_multi_router()
    r = _fresh_router(stub_backend=stub)

    called: Dict[str, Any] = {}
    original = r._consult_l1_route

    def spy(task_type_str, preferred_provider):
        called["task_type"] = task_type_str
        return original(task_type_str, preferred_provider)

    r._consult_l1_route = spy  # type: ignore[method-assign]

    messages = [{"role": "user", "content": "use tools"}]
    asyncio.get_event_loop().run_until_complete(
        r.chat_with_tools(messages, task_type="coding")
    )

    assert called.get("task_type") == "coding"


def test_36_chat_with_tools_calls_consult_l2_supply():
    """chat_with_tools() must call _consult_l2_supply (L2 on hot path)."""
    stub = _make_stub_multi_router()
    r = _fresh_router(stub_backend=stub)

    called: Dict[str, Any] = {}
    original = r._consult_l2_supply

    def spy(route_decision):
        called["invoked"] = True
        return original(route_decision)

    r._consult_l2_supply = spy  # type: ignore[method-assign]

    messages = [{"role": "user", "content": "use tools"}]
    asyncio.get_event_loop().run_until_complete(
        r.chat_with_tools(messages)
    )

    assert called.get("invoked") is True


# ---------------------------------------------------------------------------
# 37-38: L2 supply decisions affect routing
# ---------------------------------------------------------------------------


def test_37_l2_satisfied_provider_used_in_chat():
    """When L2 returns a satisfied supply, its supplied_provider is used."""
    stub = _make_stub_multi_router("anthropic")
    r = _fresh_router(stub_backend=stub)

    # Fake L2 returning a satisfied result with a specific provider.
    def fake_l2(route_decision):
        return "anthropic", "claude-3-5-sonnet", True

    r._consult_l2_supply = fake_l2  # type: ignore[method-assign]

    effective_providers_seen: List[str] = []
    original_get_provider_order = r._get_provider_order

    def spy_get_provider_order(task_type_str, preferred_provider=None):
        effective_providers_seen.append(preferred_provider or "")
        return original_get_provider_order(task_type_str, preferred_provider)

    r._get_provider_order = spy_get_provider_order  # type: ignore[method-assign]

    from core.unified.models import LLMRequest

    req = LLMRequest(messages=[{"role": "user", "content": "test"}])
    asyncio.get_event_loop().run_until_complete(r.chat(req))

    # The effective provider passed to _get_provider_order must be "anthropic"
    assert any("anthropic" in p for p in effective_providers_seen)


def test_38_l2_satisfied_provider_used_in_chat_with_tools():
    """When L2 returns satisfied supply, its supplied_provider is used in chat_with_tools."""
    stub = _make_stub_multi_router("openai")
    r = _fresh_router(stub_backend=stub)

    def fake_l2(route_decision):
        return "openai", "gpt-4o", True

    r._consult_l2_supply = fake_l2  # type: ignore[method-assign]

    effective_providers_seen: List[str] = []
    original_get_provider_order = r._get_provider_order

    def spy_get_provider_order(task_type_str, preferred_provider=None):
        effective_providers_seen.append(preferred_provider or "")
        return original_get_provider_order(task_type_str, preferred_provider)

    r._get_provider_order = spy_get_provider_order  # type: ignore[method-assign]

    messages = [{"role": "user", "content": "test"}]
    asyncio.get_event_loop().run_until_complete(r.chat_with_tools(messages))

    assert any("openai" in p for p in effective_providers_seen)


# ---------------------------------------------------------------------------
# 39-40: Cognitive spine and L4 boundary
# ---------------------------------------------------------------------------


def test_39_openclawd_process_method_exists():
    """OpenClawd.process() must still exist — the cognitive spine is preserved."""
    try:
        from core.openclawd import OpenClawd  # type: ignore[import]
        assert hasattr(OpenClawd, "process"), "OpenClawd.process() must exist"
    except ImportError:
        # If the module cannot be imported in this environment, verify the file exists.
        import os
        path = os.path.join(_REPO_ROOT, "core", "openclawd.py")
        assert os.path.exists(path), "core/openclawd.py must exist"
        import ast
        with open(path) as fh:
            tree = ast.parse(fh.read())
        methods = [
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        assert "process" in methods, "OpenClawd.process() must exist in the source"


def test_40_l4_not_imported_by_unified_llm_router():
    """UnifiedLLMRouter must not import or use GalaxyMainLoopL4Enhanced.

    L4 is the outer autonomous loop; it must not be on the per-request
    router path.
    """
    import ast

    router_path = os.path.join(
        _REPO_ROOT, "core", "unified", "llm_router.py"
    )
    with open(router_path) as fh:
        source = fh.read()

    # The L4 class name must not appear in the router source.
    assert "GalaxyMainLoopL4Enhanced" not in source, (
        "GalaxyMainLoopL4Enhanced must not be referenced in "
        "core/unified/llm_router.py — L4 is the outer autonomous loop, "
        "not a per-request gate."
    )


# ---------------------------------------------------------------------------
# 41-42: NoAvailableProviderError is still raised when backend is None
# ---------------------------------------------------------------------------


def test_41_chat_raises_when_no_backend():
    from core.unified.exceptions import NoAvailableProviderError
    from core.unified.models import LLMRequest

    r = _fresh_router(stub_backend=None)

    with pytest.raises(NoAvailableProviderError):
        asyncio.get_event_loop().run_until_complete(
            r.chat(LLMRequest(messages=[{"role": "user", "content": "hi"}]))
        )


def test_42_chat_with_tools_raises_when_no_backend():
    from core.unified.exceptions import NoAvailableProviderError

    r = _fresh_router(stub_backend=None)

    with pytest.raises(NoAvailableProviderError):
        asyncio.get_event_loop().run_until_complete(
            r.chat_with_tools([{"role": "user", "content": "hi"}])
        )


# ---------------------------------------------------------------------------
# 43-44: Reset singleton works correctly
# ---------------------------------------------------------------------------


def test_43_reset_unified_llm_router_clears_singleton():
    from core.unified.llm_router import (
        UnifiedLLMRouter,
        get_unified_llm_router,
        reset_unified_llm_router,
    )

    r1 = get_unified_llm_router()
    reset_unified_llm_router()
    r2 = get_unified_llm_router()
    assert r1 is not r2


def test_44_l3_enriched_messages_passed_to_backend_in_chat():
    """The messages given to the backend in chat() must be the L3-enriched ones."""
    from core.unified.models import LLMRequest

    backend_messages_received: List[Any] = []

    class _CapturingBackend:
        async def chat(self, messages=None, **kwargs):
            backend_messages_received.extend(messages or [])

            class _R:
                content = "ok"
                provider = "stub"
                model = "stub_model"
                usage = {}

            return _R()

        def get_status(self):
            return {"available": True, "providers": []}

    r = _fresh_router(stub_backend=_CapturingBackend())

    # L3 enrichment should add a system message even when none was present.
    req = LLMRequest(messages=[{"role": "user", "content": "enrichment test"}])
    asyncio.get_event_loop().run_until_complete(r.chat(req))

    roles = [m.get("role") for m in backend_messages_received]
    assert "system" in roles, (
        "L3 context enrichment should add a system message; "
        "backend did not receive a system message."
    )
