"""
tests/test_task_semantic_routing_wiring.py
==========================================
PR-17: Task-Semantic Model Routing Wiring

Validates the two live routing entry points now carry task semantics:

  1. Text-only path — ``AgentKernel._fallback_chat`` threads
     ``IntentResult.task_hint`` into ``MultiLLMRouter.chat(task_type=...)``.

  2. Multimodal path — ``OpenClawd._select_multimodal_route`` accepts an
     optional ``task_type`` parameter and forwards it to
     ``MultiLLMRouter.route_multimodal_first``.  When absent, it derives a
     best-effort task type via ``classify_task``; when derivation also fails
     it falls back to ``TaskType.GENERAL``.

  3. Backward compatibility — both paths degrade gracefully when task hints
     are empty, absent, or unrecognised.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─────────────────────────────────────────────────────────────────────────────
# Sentinel — marks this module as aligned with the PR-17 wiring work
# ─────────────────────────────────────────────────────────────────────────────

TASK_ROUTING_WIRING_SENTINEL = (
    "TASK_ROUTING_WIRING::TEXT_AND_MULTIMODAL_TASK_HINT_THREADED_PR17_V1"
)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_llm_response(content: str = "ok", model: str = "gpt-4o") -> MagicMock:
    resp = MagicMock()
    resp.content = content
    resp.model = model
    return resp


# ─────────────────────────────────────────────────────────────────────────────
# 1. Text-only path — task_hint threading
# ─────────────────────────────────────────────────────────────────────────────


class TestTextPathTaskHintThreading:
    """AgentKernel._fallback_chat passes task_hint to llm_router.chat."""

    @pytest.mark.asyncio
    async def test_task_hint_forwarded_to_llm_router_chat(self):
        """When intent.task_hint is non-empty, llm_router.chat receives it as task_type."""
        from core.agent.kernel import AgentKernel

        AgentKernel._instance = None
        kernel = AgentKernel()
        kernel._ensure_components()

        chat_calls: List[Dict[str, Any]] = []

        async def fake_chat_method(messages, **kwargs):
            chat_calls.append(kwargs)
            return _make_llm_response()

        mock_router = MagicMock()
        mock_router.chat = fake_chat_method
        kernel._llm_router = mock_router

        await kernel._fallback_chat(
            message="帮我截图",
            session_id="s1",
            context=[],
            user_policy="",
            task_hint="agent_control",
        )

        assert len(chat_calls) == 1, "llm_router.chat must be called exactly once"
        assert chat_calls[0].get("task_type") == "agent_control", (
            "task_hint must be forwarded as task_type to llm_router.chat"
        )

    @pytest.mark.asyncio
    async def test_empty_task_hint_sends_none_task_type(self):
        """When task_hint is empty, llm_router.chat receives task_type=None."""
        from core.agent.kernel import AgentKernel

        AgentKernel._instance = None
        kernel = AgentKernel()
        kernel._ensure_components()

        chat_calls: List[Dict[str, Any]] = []

        async def fake_chat_method(messages, **kwargs):
            chat_calls.append(kwargs)
            return _make_llm_response()

        mock_router = MagicMock()
        mock_router.chat = fake_chat_method
        kernel._llm_router = mock_router

        await kernel._fallback_chat(
            message="你好",
            session_id="s1",
            context=[],
            user_policy="",
            task_hint="",
        )

        assert len(chat_calls) == 1
        # Empty task_hint maps to task_type=None (router does generic classify)
        assert chat_calls[0].get("task_type") is None, (
            "empty task_hint must produce task_type=None so the router classifies generically"
        )

    @pytest.mark.asyncio
    async def test_process_passes_intent_task_hint_to_handle_chat(self):
        """AgentKernel._process forwards intent.task_hint when calling _handle_chat."""
        from core.agent.kernel import AgentKernel, KernelResponse
        from core.agent.intent_router import IntentResult, IntentMode

        AgentKernel._instance = None
        kernel = AgentKernel()
        kernel._ensure_components()

        intent = IntentResult(
            mode=IntentMode.CHAT_ONLY,
            confidence=0.95,
            task_hint="reasoning",
        )

        received_hints: List[str] = []

        async def spy_handle_chat(message, session_id, context, user_policy, task_hint=""):
            received_hints.append(task_hint)
            return KernelResponse(success=True, mode="chat_only", reply="ok")

        with patch.object(kernel._intent_router, "route",
                          new_callable=AsyncMock, return_value=intent), \
             patch.object(kernel, "_handle_chat", side_effect=spy_handle_chat), \
             patch("core.agent.kernel.get_agents", return_value="agents"), \
             patch("core.agent.kernel.get_user", return_value="user"):
            await kernel._process("为什么天空是蓝色的？", "s1", "", [])

        assert received_hints == ["reasoning"], (
            "_process must forward intent.task_hint into _handle_chat"
        )

    @pytest.mark.asyncio
    async def test_process_no_task_hint_in_chat_only(self):
        """When intent has no task_hint, _handle_chat receives empty string."""
        from core.agent.kernel import AgentKernel, KernelResponse
        from core.agent.intent_router import IntentResult, IntentMode

        AgentKernel._instance = None
        kernel = AgentKernel()
        kernel._ensure_components()

        intent = IntentResult(mode=IntentMode.CHAT_ONLY, confidence=0.8, task_hint="")

        received_hints: List[str] = []

        async def spy_handle_chat(message, session_id, context, user_policy, task_hint=""):
            received_hints.append(task_hint)
            return KernelResponse(success=True, mode="chat_only", reply="hi")

        with patch.object(kernel._intent_router, "route",
                          new_callable=AsyncMock, return_value=intent), \
             patch.object(kernel, "_handle_chat", side_effect=spy_handle_chat), \
             patch("core.agent.kernel.get_agents", return_value="agents"), \
             patch("core.agent.kernel.get_user", return_value="user"):
            await kernel._process("你好", "s2", "", [])

        assert received_hints == [""], "empty task_hint must be forwarded as empty string"

    @pytest.mark.asyncio
    async def test_llm_router_unavailable_returns_error_gracefully(self):
        """When llm_router is None, _fallback_chat returns error response without raising."""
        from core.agent.kernel import AgentKernel

        AgentKernel._instance = None
        kernel = AgentKernel()
        kernel._ensure_components()
        kernel._llm_router = None

        result = await kernel._fallback_chat(
            message="hello",
            session_id="s1",
            context=[],
            user_policy="",
            task_hint="coding",
        )

        assert result.success is False
        assert result.error == "llm_unavailable"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Multimodal path — task_type parameter acceptance & pass-through
# ─────────────────────────────────────────────────────────────────────────────


class TestMultimodalRouteTaskTypeWiring:
    """_select_multimodal_route accepts task_type and passes it to route_multimodal_first."""

    def _make_openclawd(self):
        """Construct a minimal OpenClawd with a mock router."""
        try:
            from core.openclawd import OpenClawd
        except Exception:
            pytest.skip("OpenClawd import requires optional deps")

        oc = OpenClawd.__new__(OpenClawd)
        oc._router = None
        oc._kernel = None
        return oc

    def _make_mock_router(self, provider: str = "openai", model: str = "gpt-4o"):
        from core.multi_llm_router import TaskType

        decision = MagicMock()
        decision.provider = provider
        decision.model = model
        decision.reason = "tier=1 native_multimodal provider=openai"

        router = MagicMock()
        router.route_multimodal_first = MagicMock(return_value=decision)
        router.classify_task = MagicMock(return_value=TaskType.GENERAL)
        return router

    def _native_mm_perception(self) -> Dict[str, Any]:
        return {
            "requires_native_multimodal": True,
            "active_modalities": ["image"],
        }

    def test_explicit_task_type_forwarded_to_route_multimodal_first(self):
        """Explicit task_type is converted to TaskType and forwarded."""
        from core.multi_llm_router import TaskType
        from core.openclawd import OpenClawd

        oc = self._make_openclawd()
        mock_router = self._make_mock_router()

        with patch.object(OpenClawd, "_get_router", return_value=mock_router):
            result = oc._select_multimodal_route(
                canonical_perception=self._native_mm_perception(),
                task_type="coding",
            )

        assert mock_router.route_multimodal_first.called
        call_args = mock_router.route_multimodal_first.call_args
        # route_multimodal_first is always called with keyword args in the implementation
        used_task_type = call_args.kwargs.get("task_type")
        assert used_task_type == TaskType.CODING, (
            "explicit task_type='coding' must map to TaskType.CODING"
        )

    def test_result_includes_task_type_used_field(self):
        """Result dict includes task_type_used for diagnostics."""
        from core.openclawd import OpenClawd

        oc = self._make_openclawd()
        mock_router = self._make_mock_router()

        with patch.object(OpenClawd, "_get_router", return_value=mock_router):
            result = oc._select_multimodal_route(
                canonical_perception=self._native_mm_perception(),
                task_type="reasoning",
            )

        assert "task_type_used" in result, (
            "result dict must include task_type_used for routing diagnostics"
        )
        assert result["task_type_used"] == "reasoning"

    def test_no_task_type_falls_back_to_general(self):
        """When task_type is None and no hint, route_multimodal_first gets GENERAL."""
        from core.multi_llm_router import TaskType
        from core.openclawd import OpenClawd

        oc = self._make_openclawd()
        mock_router = self._make_mock_router()

        with patch.object(OpenClawd, "_get_router", return_value=mock_router):
            result = oc._select_multimodal_route(
                canonical_perception=self._native_mm_perception(),
                task_type=None,
            )

        assert mock_router.route_multimodal_first.called
        call_kwargs = mock_router.route_multimodal_first.call_args
        used_task_type = call_kwargs.kwargs.get("task_type")
        assert used_task_type == TaskType.GENERAL, (
            "absent task_type with no derivable hint must default to TaskType.GENERAL"
        )

    def test_unrecognised_task_type_string_falls_back_to_general(self):
        """Unrecognised task_type string falls back to GENERAL without raising."""
        from core.multi_llm_router import TaskType
        from core.openclawd import OpenClawd

        oc = self._make_openclawd()
        mock_router = self._make_mock_router()

        with patch.object(OpenClawd, "_get_router", return_value=mock_router):
            result = oc._select_multimodal_route(
                canonical_perception=self._native_mm_perception(),
                task_type="nonexistent_task_xyz",
            )

        # Must not raise; must call route_multimodal_first with GENERAL
        assert mock_router.route_multimodal_first.called
        call_kwargs = mock_router.route_multimodal_first.call_args
        used_task_type = call_kwargs.kwargs.get("task_type")
        assert used_task_type == TaskType.GENERAL

    def test_text_only_route_unaffected_by_task_type(self):
        """Text-only perception short-circuits before task_type is used."""
        from core.openclawd import OpenClawd

        oc = self._make_openclawd()
        mock_router = self._make_mock_router()

        text_only_perception = {
            "requires_native_multimodal": False,
            "active_modalities": [],
        }

        with patch.object(OpenClawd, "_get_router", return_value=mock_router):
            result = oc._select_multimodal_route(
                canonical_perception=text_only_perception,
                task_type="coding",
            )

        assert result["route_type"] == "text_only"
        # route_multimodal_first must NOT be called for text-only
        mock_router.route_multimodal_first.assert_not_called()

    def test_task_type_derived_from_perception_task_hint(self):
        """When task_type is absent, task_hint in canonical_perception drives classify_task."""
        from core.multi_llm_router import TaskType
        from core.openclawd import OpenClawd

        oc = self._make_openclawd()
        mock_router = self._make_mock_router()
        mock_router.classify_task = MagicMock(return_value=TaskType.ANALYSIS)

        perception_with_hint = {
            "requires_native_multimodal": True,
            "active_modalities": ["image"],
            "task_hint": "analysis",
        }

        with patch.object(OpenClawd, "_get_router", return_value=mock_router):
            result = oc._select_multimodal_route(
                canonical_perception=perception_with_hint,
                task_type=None,
            )

        mock_router.classify_task.assert_called_once()
        call_args = mock_router.classify_task.call_args
        assert call_args.kwargs.get("hint") == "analysis", (
            "classify_task must be called with the perception task_hint"
        )
        # route_multimodal_first should receive the derived ANALYSIS type
        call_kwargs = mock_router.route_multimodal_first.call_args
        used_task_type = call_kwargs.kwargs.get("task_type")
        assert used_task_type == TaskType.ANALYSIS


# ─────────────────────────────────────────────────────────────────────────────
# 3. Backward-compatibility guarantees
# ─────────────────────────────────────────────────────────────────────────────


class TestBackwardCompatibility:
    """Existing callers without task_type continue to work unchanged."""

    @pytest.mark.asyncio
    async def test_handle_chat_default_task_hint_is_empty_string(self):
        """_handle_chat default task_hint='' is backward-compatible."""
        from core.agent.kernel import AgentKernel

        AgentKernel._instance = None
        kernel = AgentKernel()
        kernel._ensure_components()

        chat_calls: List[Dict[str, Any]] = []

        async def fake_chat_method(messages, **kwargs):
            chat_calls.append(kwargs)
            return _make_llm_response()

        mock_router = MagicMock()
        mock_router.chat = fake_chat_method
        kernel._llm_router = mock_router

        # Call without providing task_hint (backward-compat call signature)
        await kernel._handle_chat(
            message="hello",
            session_id="s1",
            context=[],
            user_policy="",
        )

        assert len(chat_calls) == 1
        # Default task_hint="" → task_type=None (not some unexpected value)
        assert chat_calls[0].get("task_type") is None

    def test_select_multimodal_route_no_task_type_arg_is_valid(self):
        """Existing call sites that omit task_type still get a valid result."""
        try:
            from core.openclawd import OpenClawd
        except Exception:
            pytest.skip("OpenClawd import requires optional deps")

        from core.multi_llm_router import TaskType

        oc = OpenClawd.__new__(OpenClawd)
        oc._router = None
        oc._kernel = None

        decision = MagicMock()
        decision.provider = "openai"
        decision.model = "gpt-4o"
        decision.reason = "tier=1"

        mock_router = MagicMock()
        mock_router.route_multimodal_first = MagicMock(return_value=decision)
        mock_router.classify_task = MagicMock(return_value=TaskType.GENERAL)

        perception = {
            "requires_native_multimodal": True,
            "active_modalities": ["image"],
        }

        with patch.object(OpenClawd, "_get_router", return_value=mock_router):
            # Old-style call: no task_type kwarg
            result = oc._select_multimodal_route(canonical_perception=perception)

        assert result is not None
        assert "route_type" in result
        assert result["route_type"] in (
            "native_multimodal", "partial_multimodal", "advisory", "text_only"
        )

    def test_select_multimodal_route_none_canonical_perception(self):
        """None canonical_perception still returns a valid result dict."""
        try:
            from core.openclawd import OpenClawd
        except Exception:
            pytest.skip("OpenClawd import requires optional deps")

        oc = OpenClawd.__new__(OpenClawd)
        oc._router = None
        oc._kernel = None

        with patch.object(OpenClawd, "_get_router", return_value=None):
            result = oc._select_multimodal_route(canonical_perception=None)

        assert result is not None
        assert result.get("route_type") in ("text_only", "advisory")


# ─────────────────────────────────────────────────────────────────────────────
# Sentinel import test
# ─────────────────────────────────────────────────────────────────────────────


def test_sentinel_importable():
    """Module-level sentinel is importable and non-empty."""
    from tests.test_task_semantic_routing_wiring import TASK_ROUTING_WIRING_SENTINEL
    assert TASK_ROUTING_WIRING_SENTINEL
    assert "PR17" in TASK_ROUTING_WIRING_SENTINEL
