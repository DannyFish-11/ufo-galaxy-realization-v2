#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr17_task_semantic_model_routing.py
==============================================

PR-17 — Task-Semantic Model Routing Wiring

Tests covering the two canonical wiring points introduced in PR-17:

A. TEXT-ONLY PATH (AgentKernel)
   1.  task_hint from IntentResult is forwarded to llm_router.chat as task_type
   2.  empty task_hint is forwarded as None (router falls back to classification)
   3.  _fallback_chat passes task_hint keyword arg to llm_router.chat
   4.  _handle_chat accepts and threads task_hint to _fallback_chat

B. MULTIMODAL PATH (OpenClawd._select_multimodal_route)
   5.  task_type parameter accepted without error
   6.  when task_type is provided it is passed to route_multimodal_first
   7.  when task_type is None/absent, GENERAL is used as fallback
   8.  unrecognised task_type string falls back gracefully to GENERAL
   9.  task_type_hint key present in every returned result dict
   10. task_type_hint reflects the supplied hint (or "general" when absent)
   11. text_only short-circuit result includes task_type_hint
   12. router_unavailable advisory result includes task_type_hint

C. BACKWARD COMPATIBILITY
   13. calling _select_multimodal_route without task_type arg still works
   14. calling _fallback_chat without task_hint arg still works
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_llm_router_mock(reply: str = "hello") -> MagicMock:
    """Return a minimal MultiLLMRouter-shaped async mock."""
    mock = MagicMock()
    response = MagicMock()
    response.content = reply
    response.model = "test-model"
    mock.chat = AsyncMock(return_value=response)
    return mock


@dataclass
class _FakeProviderConfig:
    name: str
    multimodal: bool = False
    status: str = "healthy"
    default_model: str = "model-v1"
    env_key: str = ""


def _make_mm_router(providers: Dict[str, _FakeProviderConfig]):
    """Create a MultiLLMRouter-like stub for unit testing _select_multimodal_route."""
    from core.multi_llm_router import (
        MultiLLMRouter,
        ProviderConfig,
        ProviderStatus,
        TaskType,
    )

    router = object.__new__(MultiLLMRouter)
    real_providers: Dict[str, ProviderConfig] = {}
    for name, fake in providers.items():
        cfg = object.__new__(ProviderConfig)
        cfg.name = name
        cfg.multimodal = fake.multimodal
        cfg.status = (
            ProviderStatus.HEALTHY
            if fake.status != "down"
            else ProviderStatus.DOWN
        )
        cfg.default_model = fake.default_model
        cfg.env_key = fake.env_key
        cfg.api_key = ""
        cfg.base_url = ""
        cfg.models = [fake.default_model]
        cfg.cost_per_1k_input = 0.0
        cfg.cost_per_1k_output = 0.0
        cfg.max_tokens = 4096
        cfg.supports_tools = True
        cfg.supports_json_mode = True
        cfg.timeout = 60.0
        cfg.latency_avg_ms = 0.0
        cfg.error_count = 0
        cfg.success_count = 0
        cfg.last_error = None
        cfg.last_used = 0.0
        real_providers[name] = cfg
    router.providers = real_providers
    return router


# ---------------------------------------------------------------------------
# A. TEXT-ONLY PATH — AgentKernel._fallback_chat task_hint threading
# ---------------------------------------------------------------------------

class TestTextPathTaskHintThreading:
    """Verify that IntentRouter.task_hint reaches MultiLLMRouter.chat as task_type."""

    @pytest.mark.asyncio
    async def test_task_hint_forwarded_to_llm_router_chat(self):
        """Non-empty task_hint must be passed as task_type to llm_router.chat."""
        from core.agent.kernel import AgentKernel
        from core.agent.intent_router import IntentMode

        kernel = object.__new__(AgentKernel)
        kernel._llm_router = _make_llm_router_mock()
        kernel._intent_router = None
        kernel._planner = None

        await kernel._fallback_chat(
            message="帮我写一个 Python 函数",
            session_id="s1",
            context=[],
            user_policy="",
            task_hint="coding",
        )

        call_kwargs = kernel._llm_router.chat.call_args
        assert call_kwargs is not None, "llm_router.chat must be called"
        kwargs = call_kwargs.kwargs if call_kwargs.kwargs else {}
        args = call_kwargs.args if call_kwargs.args else ()
        # task_type may be positional (index 1) or keyword
        task_type_passed = kwargs.get("task_type") if "task_type" in kwargs else (
            args[1] if len(args) > 1 else None
        )
        assert task_type_passed == "coding", (
            f"Expected task_type='coding', got {task_type_passed!r}"
        )

    @pytest.mark.asyncio
    async def test_empty_task_hint_forwarded_as_none(self):
        """Empty task_hint must be forwarded as None so the router classifies itself."""
        from core.agent.kernel import AgentKernel

        kernel = object.__new__(AgentKernel)
        kernel._llm_router = _make_llm_router_mock()
        kernel._intent_router = None
        kernel._planner = None

        await kernel._fallback_chat(
            message="你好",
            session_id="s2",
            context=[],
            user_policy="",
            task_hint="",
        )

        call_kwargs = kernel._llm_router.chat.call_args
        assert call_kwargs is not None
        kwargs = call_kwargs.kwargs if call_kwargs.kwargs else {}
        args = call_kwargs.args if call_kwargs.args else ()
        task_type_passed = kwargs.get("task_type") if "task_type" in kwargs else (
            args[1] if len(args) > 1 else None
        )
        assert task_type_passed is None, (
            f"Empty hint should yield task_type=None, got {task_type_passed!r}"
        )

    @pytest.mark.asyncio
    async def test_fallback_chat_no_task_hint_arg_backward_compat(self):
        """Calling _fallback_chat without task_hint must not raise."""
        from core.agent.kernel import AgentKernel

        kernel = object.__new__(AgentKernel)
        kernel._llm_router = _make_llm_router_mock()
        kernel._intent_router = None
        kernel._planner = None

        # Should not raise even when task_hint not provided
        result = await kernel._fallback_chat(
            message="hello",
            session_id="s3",
            context=[],
            user_policy="",
        )
        assert result.success is True

    @pytest.mark.asyncio
    async def test_handle_chat_threads_task_hint_to_fallback(self):
        """_handle_chat must forward task_hint to _fallback_chat."""
        from core.agent.kernel import AgentKernel

        kernel = object.__new__(AgentKernel)
        kernel._llm_router = _make_llm_router_mock()
        kernel._intent_router = None
        kernel._planner = None

        await kernel._handle_chat(
            message="analyze this data",
            session_id="s4",
            context=[],
            user_policy="",
            task_hint="analysis",
        )

        call_kwargs = kernel._llm_router.chat.call_args
        assert call_kwargs is not None
        kwargs = call_kwargs.kwargs if call_kwargs.kwargs else {}
        args = call_kwargs.args if call_kwargs.args else ()
        task_type_passed = kwargs.get("task_type") if "task_type" in kwargs else (
            args[1] if len(args) > 1 else None
        )
        assert task_type_passed == "analysis"

    @pytest.mark.asyncio
    async def test_handle_chat_without_task_hint_backward_compat(self):
        """_handle_chat without task_hint must not raise."""
        from core.agent.kernel import AgentKernel

        kernel = object.__new__(AgentKernel)
        kernel._llm_router = _make_llm_router_mock()
        kernel._intent_router = None
        kernel._planner = None

        result = await kernel._handle_chat(
            message="hello",
            session_id="s5",
            context=[],
            user_policy="",
        )
        assert result.success is True


# ---------------------------------------------------------------------------
# B. MULTIMODAL PATH — _select_multimodal_route task_type wiring
# ---------------------------------------------------------------------------

class TestMultimodalRouteTaskTypeWiring:
    """Verify _select_multimodal_route accepts and threads task_type."""

    def _make_openclawd_stub(self, router):
        """Build a minimal OpenClawd stub with a fixed router."""
        from core.openclawd import OpenClawd
        oc = object.__new__(OpenClawd)
        oc._router = router
        oc._mm_router = None
        oc.metadata = {}

        def _get_router_stub():
            return router

        oc._get_router = _get_router_stub
        return oc

    def test_task_type_param_accepted(self):
        """_select_multimodal_route must accept task_type kwarg without raising."""
        router = _make_mm_router({
            "openai": _FakeProviderConfig("openai", multimodal=True),
        })
        oc = self._make_openclawd_stub(router)
        perception = {
            "requires_native_multimodal": True,
            "active_modalities": ["image"],
        }
        # Must not raise
        result = oc._select_multimodal_route(
            canonical_perception=perception,
            task_type="coding",
        )
        assert isinstance(result, dict)

    def test_task_type_hint_key_present_native_multimodal(self):
        """task_type_hint must appear in tier-1 (native_multimodal) result."""
        router = _make_mm_router({
            "openai": _FakeProviderConfig("openai", multimodal=True),
        })
        oc = self._make_openclawd_stub(router)
        perception = {
            "requires_native_multimodal": True,
            "active_modalities": ["image"],
        }
        result = oc._select_multimodal_route(
            canonical_perception=perception,
            task_type="coding",
        )
        assert "task_type_hint" in result, (
            f"task_type_hint key missing from result: {list(result.keys())}"
        )

    def test_task_type_hint_reflects_supplied_value(self):
        """task_type_hint in result must equal the supplied task_type."""
        router = _make_mm_router({
            "openai": _FakeProviderConfig("openai", multimodal=True),
        })
        oc = self._make_openclawd_stub(router)
        perception = {
            "requires_native_multimodal": True,
            "active_modalities": ["image"],
        }
        result = oc._select_multimodal_route(
            canonical_perception=perception,
            task_type="reasoning",
        )
        assert result.get("task_type_hint") == "reasoning"

    def test_task_type_hint_defaults_to_general_when_absent(self):
        """When no task_type is supplied, task_type_hint must be 'general'."""
        router = _make_mm_router({
            "openai": _FakeProviderConfig("openai", multimodal=True),
        })
        oc = self._make_openclawd_stub(router)
        perception = {
            "requires_native_multimodal": True,
            "active_modalities": ["image"],
        }
        result = oc._select_multimodal_route(canonical_perception=perception)
        assert result.get("task_type_hint") == "general"

    def test_unrecognised_task_type_falls_back_gracefully(self):
        """An invalid task_type string must not raise; result must be valid."""
        router = _make_mm_router({
            "openai": _FakeProviderConfig("openai", multimodal=True),
        })
        oc = self._make_openclawd_stub(router)
        perception = {
            "requires_native_multimodal": True,
            "active_modalities": ["image"],
        }
        result = oc._select_multimodal_route(
            canonical_perception=perception,
            task_type="__nonexistent_type__",
        )
        assert isinstance(result, dict)
        assert result.get("route_type") in (
            "native_multimodal", "partial_multimodal", "advisory", "text_only"
        )

    def test_text_only_result_includes_task_type_hint(self):
        """The text_only short-circuit result must carry task_type_hint."""
        router = _make_mm_router({})
        oc = self._make_openclawd_stub(router)
        # No multimodal input → requires_native_multimodal=False
        perception = {
            "requires_native_multimodal": False,
            "active_modalities": [],
        }
        result = oc._select_multimodal_route(
            canonical_perception=perception,
            task_type="planning",
        )
        assert result.get("route_type") == "text_only"
        assert "task_type_hint" in result

    def test_text_only_no_task_type_hint_is_general(self):
        """text_only result without supplied task_type must have hint='general'."""
        router = _make_mm_router({})
        oc = self._make_openclawd_stub(router)
        perception = {
            "requires_native_multimodal": False,
            "active_modalities": [],
        }
        result = oc._select_multimodal_route(canonical_perception=perception)
        assert result.get("task_type_hint") == "general"

    def test_router_unavailable_advisory_includes_task_type_hint(self):
        """advisory (router=None) result must include task_type_hint."""
        from core.openclawd import OpenClawd
        oc = object.__new__(OpenClawd)
        oc._router = None
        oc.metadata = {}

        def _get_router_none():
            return None

        oc._get_router = _get_router_none

        perception = {
            "requires_native_multimodal": True,
            "active_modalities": ["image"],
        }
        result = oc._select_multimodal_route(
            canonical_perception=perception,
            task_type="creative",
        )
        assert result.get("route_type") == "advisory"
        assert "task_type_hint" in result

    def test_backward_compat_no_task_type_arg(self):
        """Calling _select_multimodal_route without task_type must not raise."""
        router = _make_mm_router({
            "openai": _FakeProviderConfig("openai", multimodal=True),
        })
        oc = self._make_openclawd_stub(router)
        perception = {
            "requires_native_multimodal": True,
            "active_modalities": ["image"],
        }
        # No task_type argument — must work exactly as before
        result = oc._select_multimodal_route(canonical_perception=perception)
        assert isinstance(result, dict)
        assert result.get("route_type") in (
            "native_multimodal", "partial_multimodal", "advisory", "text_only"
        )

    def test_task_type_passed_to_route_multimodal_first(self):
        """The resolved TaskType must be forwarded to route_multimodal_first."""
        from core.multi_llm_router import TaskType, RoutingDecision
        from core.openclawd import OpenClawd

        # Capture what task_type was passed to route_multimodal_first
        captured: Dict[str, Any] = {}

        class _CapturingRouter:
            def route_multimodal_first(
                self,
                active_modalities=None,
                task_type=TaskType.GENERAL,
                complexity_score=0.5,
            ) -> RoutingDecision:
                captured["task_type"] = task_type
                return RoutingDecision(
                    provider="openai",
                    model="gpt-4",
                    reason="tier=1 native_multimodal modalities=image",
                    alternatives=[],
                )

            def classify_task(self, messages, hint=None):
                return TaskType.GENERAL

        oc = object.__new__(OpenClawd)
        oc._router = None
        oc.metadata = {}
        oc._get_router = lambda: _CapturingRouter()

        perception = {
            "requires_native_multimodal": True,
            "active_modalities": ["image"],
        }
        oc._select_multimodal_route(
            canonical_perception=perception,
            task_type="coding",
        )

        assert "task_type" in captured, "route_multimodal_first was not called"
        assert captured["task_type"] == TaskType.CODING, (
            f"Expected TaskType.CODING, got {captured['task_type']!r}"
        )


# ---------------------------------------------------------------------------
# C. classify_task hint support (MultiLLMRouter)
# ---------------------------------------------------------------------------

class TestClassifyTaskHintSupport:
    """Verify MultiLLMRouter.classify_task respects the hint parameter."""

    def test_classify_task_uses_hint_when_valid(self):
        """A valid TaskType string hint must be returned directly."""
        from core.multi_llm_router import MultiLLMRouter, TaskType

        router = _make_mm_router({})
        result = router.classify_task(
            [{"role": "user", "content": "some message"}],
            hint="coding",
        )
        assert result == TaskType.CODING

    def test_classify_task_falls_back_when_hint_invalid(self):
        """An invalid hint must be silently ignored; classification proceeds."""
        from core.multi_llm_router import MultiLLMRouter, TaskType

        router = _make_mm_router({})
        result = router.classify_task(
            [{"role": "user", "content": "帮我写代码"}],
            hint="__bad_hint__",
        )
        # Should still produce a valid TaskType (not raise)
        assert isinstance(result, TaskType)

    def test_classify_task_no_hint_returns_general_for_empty_msg(self):
        """With no hint and no keyword matches, GENERAL is returned."""
        from core.multi_llm_router import TaskType

        router = _make_mm_router({})
        result = router.classify_task([{"role": "user", "content": "xyz123"}])
        assert result == TaskType.GENERAL
