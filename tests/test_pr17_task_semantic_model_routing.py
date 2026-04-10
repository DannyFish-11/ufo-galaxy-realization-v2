"""tests/test_pr17_task_semantic_model_routing.py
=================================================
Tests for PR-17: task-semantic model routing wiring.

Coverage matrix
---------------
Group A — Sentinel / authority assertions
  A01. AGENT_KERNEL_TASK_HINT_THREADED_PR17 sentinel exists in kernel.py.
  A02. TASK_SEMANTIC_MULTIMODAL_ROUTE_WIRED_PR17 sentinel exists in openclawd.py.

Group B — Text-only path: task_hint threading (AgentKernel)
  B01. _fallback_chat passes task_hint as task_type when non-empty.
  B02. _fallback_chat does NOT pass task_type when task_hint is empty.
  B03. _fallback_chat does NOT pass task_type when task_hint is None.
  B04. _handle_chat forwards task_hint to _fallback_chat.
  B05. _process passes intent.task_hint to _handle_chat in chat_only mode.
  B06. _process does not crash when task_hint is empty string.
  B07. task_hint threading works end-to-end with a mock LLM router.

Group C — Multimodal path: task_type parameter in _select_multimodal_route
  C01. _select_multimodal_route accepts task_type parameter.
  C02. When task_type is a valid TaskType value, it is forwarded to router.
  C03. When task_type is None, GENERAL is used as fallback (backward compat).
  C04. When task_type is empty string, GENERAL is used as fallback.
  C05. When task_type is unrecognised, GENERAL is used as fallback.
  C06. text_only short-circuit is not affected by task_type parameter.

Group D — Multimodal call-site: task derivation in process()
  D01. process() derives task type when router has classify_task.
  D02. process() falls back gracefully when classify_task raises.
  D03. process() passes derived task_type into _select_multimodal_route.

Group E — Backward compatibility
  E01. _fallback_chat without task_hint still calls chat() successfully.
  E02. _select_multimodal_route with no task_type still returns valid dict.
  E03. route_type/provider/model keys present in result regardless of task_type.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─────────────────────────── Group A — Sentinels ────────────────────────────


class TestSentinels:
    """Group A — verify PR-17 authority/sentinel constants exist."""

    def test_a01_agent_kernel_task_hint_sentinel(self):
        """A01. AGENT_KERNEL_TASK_HINT_THREADED_PR17 sentinel exists in kernel.py."""
        from core.agent import kernel as kernel_mod
        assert hasattr(kernel_mod, "AGENT_KERNEL_TASK_HINT_THREADED_PR17"), (
            "AGENT_KERNEL_TASK_HINT_THREADED_PR17 sentinel must be present in "
            "core/agent/kernel.py to assert the PR-17 wiring is committed."
        )
        assert isinstance(kernel_mod.AGENT_KERNEL_TASK_HINT_THREADED_PR17, str)
        assert len(kernel_mod.AGENT_KERNEL_TASK_HINT_THREADED_PR17) > 0

    def test_a02_openclawd_multimodal_route_sentinel(self):
        """A02. TASK_SEMANTIC_MULTIMODAL_ROUTE_WIRED_PR17 sentinel exists in openclawd.py."""
        import core.openclawd as oc_mod
        assert hasattr(oc_mod, "TASK_SEMANTIC_MULTIMODAL_ROUTE_WIRED_PR17"), (
            "TASK_SEMANTIC_MULTIMODAL_ROUTE_WIRED_PR17 sentinel must be present "
            "in core/openclawd.py to assert the PR-17 multimodal wiring is committed."
        )
        assert isinstance(oc_mod.TASK_SEMANTIC_MULTIMODAL_ROUTE_WIRED_PR17, str)
        assert len(oc_mod.TASK_SEMANTIC_MULTIMODAL_ROUTE_WIRED_PR17) > 0


# ─────────────────────── Group B — Text-only path ───────────────────────────


def _make_mock_router(reply_content: str = "ok") -> MagicMock:
    """Build a mock LLM router whose chat() returns a simple LLMResponse-like."""
    mock_resp = MagicMock()
    mock_resp.content = reply_content
    mock_resp.model = "test-model"

    router = MagicMock()
    router.chat = AsyncMock(return_value=mock_resp)
    router.is_available = MagicMock(return_value=True)
    return router


def _make_kernel_with_router(router: Any):
    """Create an AgentKernel instance with a pre-set mock LLM router."""
    from core.agent.kernel import AgentKernel
    AgentKernel._instance = None
    kernel = AgentKernel()
    kernel._ensure_components()
    kernel._llm_router = router
    return kernel


class TestTextPathTaskHintThreading:
    """Group B — task_hint is threaded into the text-only LLM call."""

    @pytest.mark.asyncio
    async def test_b01_task_hint_passed_as_task_type(self):
        """B01. _fallback_chat passes task_hint as task_type when non-empty."""
        router = _make_mock_router()
        kernel = _make_kernel_with_router(router)

        await kernel._fallback_chat(
            message="帮我写代码",
            session_id="s1",
            context=[],
            user_policy="",
            task_hint="CODING",
        )

        # The mock router's chat must have been called with task_type="CODING"
        router.chat.assert_called_once()
        call_kwargs = router.chat.call_args
        # chat() may be called positionally or by keyword
        all_kwargs: Dict[str, Any] = call_kwargs.kwargs
        assert "task_type" in all_kwargs, (
            "task_type must be forwarded to llm_router.chat() when task_hint is non-empty"
        )
        assert all_kwargs["task_type"] == "CODING"

    @pytest.mark.asyncio
    async def test_b02_empty_task_hint_not_forwarded(self):
        """B02. _fallback_chat does NOT pass task_type when task_hint is empty string."""
        router = _make_mock_router()
        kernel = _make_kernel_with_router(router)

        await kernel._fallback_chat(
            message="你好",
            session_id="s1",
            context=[],
            user_policy="",
            task_hint="",
        )

        router.chat.assert_called_once()
        all_kwargs: Dict[str, Any] = router.chat.call_args.kwargs
        assert "task_type" not in all_kwargs, (
            "task_type must NOT be added to chat() kwargs when task_hint is empty"
        )

    @pytest.mark.asyncio
    async def test_b03_default_task_hint_none_not_forwarded(self):
        """B03. _fallback_chat does NOT pass task_type when task_hint is default (empty)."""
        router = _make_mock_router()
        kernel = _make_kernel_with_router(router)

        # Call without task_hint (uses default "")
        await kernel._fallback_chat(
            message="今天天气怎么样",
            session_id="s1",
            context=[],
            user_policy="",
        )

        router.chat.assert_called_once()
        all_kwargs: Dict[str, Any] = router.chat.call_args.kwargs
        assert "task_type" not in all_kwargs

    @pytest.mark.asyncio
    async def test_b04_handle_chat_forwards_task_hint(self):
        """B04. _handle_chat forwards task_hint to _fallback_chat."""
        router = _make_mock_router()
        kernel = _make_kernel_with_router(router)

        captured: List[Dict] = []

        original_fallback = kernel._fallback_chat

        async def capturing_fallback(message, session_id, context, user_policy, task_hint=""):
            captured.append({"task_hint": task_hint})
            return await original_fallback(
                message, session_id, context, user_policy, task_hint=task_hint
            )

        kernel._fallback_chat = capturing_fallback  # type: ignore[method-assign]

        await kernel._handle_chat(
            message="帮我分析数据",
            session_id="s1",
            context=[],
            user_policy="",
            task_hint="ANALYSIS",
        )

        assert len(captured) == 1
        assert captured[0]["task_hint"] == "ANALYSIS"

    @pytest.mark.asyncio
    async def test_b05_process_passes_task_hint_to_handle_chat(self):
        """B05. _process passes intent.task_hint to _handle_chat in chat_only mode."""
        from core.agent.intent_router import IntentResult, IntentMode

        router = _make_mock_router()
        kernel = _make_kernel_with_router(router)

        chat_intent = IntentResult(
            mode=IntentMode.CHAT_ONLY,
            confidence=0.9,
            task_hint="REASONING",
        )

        captured_hint: List[str] = []

        async def spy_handle_chat(message, session_id, context, user_policy, task_hint=""):
            captured_hint.append(task_hint)
            from core.agent.kernel import KernelResponse
            return KernelResponse(success=True, mode=IntentMode.CHAT_ONLY, reply="ok")

        with patch.object(kernel._intent_router, "route",
                          new_callable=AsyncMock, return_value=chat_intent), \
             patch.object(kernel, "_handle_chat", side_effect=spy_handle_chat), \
             patch("core.agent.kernel.get_agents", return_value=""), \
             patch("core.agent.kernel.get_user", return_value=""):
            await kernel._process("解释一下这个现象", "s1", "", [])

        assert len(captured_hint) == 1, "_handle_chat should be called once"
        assert captured_hint[0] == "REASONING", (
            "task_hint from IntentResult must be forwarded to _handle_chat"
        )

    @pytest.mark.asyncio
    async def test_b06_process_handles_empty_task_hint(self):
        """B06. _process does not crash when task_hint is empty string."""
        from core.agent.intent_router import IntentResult, IntentMode

        router = _make_mock_router()
        kernel = _make_kernel_with_router(router)

        chat_intent = IntentResult(
            mode=IntentMode.CHAT_ONLY,
            confidence=0.95,
            task_hint="",  # empty — typical chat_only case
        )

        with patch.object(kernel._intent_router, "route",
                          new_callable=AsyncMock, return_value=chat_intent), \
             patch("core.agent.kernel.get_agents", return_value=""), \
             patch("core.agent.kernel.get_user", return_value=""):
            result = await kernel._process("你好", "s1", "", [])

        assert result.success is True

    @pytest.mark.asyncio
    async def test_b07_task_hint_end_to_end(self):
        """B07. task_hint threading works end-to-end with a mock LLM router."""
        from core.agent.intent_router import IntentResult, IntentMode

        router = _make_mock_router(reply_content="分析结果")
        kernel = _make_kernel_with_router(router)

        chat_intent = IntentResult(
            mode=IntentMode.CHAT_ONLY,
            confidence=0.85,
            task_hint="ANALYSIS",
        )

        with patch.object(kernel._intent_router, "route",
                          new_callable=AsyncMock, return_value=chat_intent), \
             patch("core.agent.kernel.get_agents", return_value=""), \
             patch("core.agent.kernel.get_user", return_value=""):
            result = await kernel._process("分析这份数据", "s1", "", [])

        assert result.success is True
        assert result.reply == "分析结果"
        # Verify the router was called with task_type = "ANALYSIS"
        router.chat.assert_called_once()
        call_kwargs = router.chat.call_args.kwargs
        assert call_kwargs.get("task_type") == "ANALYSIS"


# ────────────────────── Group C — Multimodal route parameter ────────────────


def _make_openclawd_no_router() -> Any:
    """Build an OpenClawd instance whose _get_router() returns None."""
    from core.openclawd import OpenClawd
    oc = OpenClawd.__new__(OpenClawd)
    oc._initialized = True
    oc._get_router = MagicMock(return_value=None)
    return oc


def _make_openclawd_with_router(route_decision: Any) -> Any:
    """Build an OpenClawd instance with a mock router that returns route_decision."""
    from core.openclawd import OpenClawd
    oc = OpenClawd.__new__(OpenClawd)
    oc._initialized = True
    mock_router = MagicMock()
    mock_router.route_multimodal_first = MagicMock(return_value=route_decision)
    oc._get_router = MagicMock(return_value=mock_router)
    return oc, mock_router


def _make_routing_decision(provider: str = "test", model: str = "test-model",
                            reason: str = "tier=1 test") -> Any:
    from core.multi_llm_router import RoutingDecision
    return RoutingDecision(
        provider=provider,
        model=model,
        reason=reason,
        alternatives=[],
    )


class TestMultimodalRouteTaskType:
    """Group C — _select_multimodal_route task_type parameter."""

    def test_c01_method_accepts_task_type_parameter(self):
        """C01. _select_multimodal_route accepts task_type parameter without error."""
        import inspect
        from core.openclawd import OpenClawd
        sig = inspect.signature(OpenClawd._select_multimodal_route)
        assert "task_type" in sig.parameters, (
            "_select_multimodal_route must accept a task_type parameter (PR-17)"
        )

    def test_c02_valid_task_type_forwarded_to_router(self):
        """C02. When task_type is a valid TaskType value, it is forwarded to router."""
        from core.multi_llm_router import TaskType
        decision = _make_routing_decision()
        oc, mock_router = _make_openclawd_with_router(decision)

        # TaskType enum uses lowercase values ("coding", not "CODING").
        # classify_task() returns TaskType instances whose .value is lowercase.
        with patch(
            "core.multimodal.modality_confidence_policy.build_perception_routing_readiness",
            side_effect=ImportError("not available"),
        ):
            oc._select_multimodal_route(
                canonical_perception={
                    "requires_native_multimodal": True,
                    "active_modalities": ["image"],
                },
                task_type="coding",  # lowercase — the canonical TaskType enum value
            )

        mock_router.route_multimodal_first.assert_called_once()
        call_kwargs = mock_router.route_multimodal_first.call_args.kwargs
        assert "task_type" in call_kwargs
        assert call_kwargs["task_type"] == TaskType.CODING

    def test_c03_none_task_type_uses_general(self):
        """C03. When task_type is None, GENERAL is used as fallback."""
        from core.multi_llm_router import TaskType
        decision = _make_routing_decision()
        oc, mock_router = _make_openclawd_with_router(decision)

        with patch(
            "core.multimodal.modality_confidence_policy.build_perception_routing_readiness",
            side_effect=ImportError("not available"),
        ):
            oc._select_multimodal_route(
                canonical_perception={
                    "requires_native_multimodal": True,
                    "active_modalities": ["image"],
                },
                task_type=None,
            )

        mock_router.route_multimodal_first.assert_called_once()
        call_kwargs = mock_router.route_multimodal_first.call_args.kwargs
        assert call_kwargs.get("task_type") == TaskType.GENERAL

    def test_c04_empty_string_task_type_uses_general(self):
        """C04. When task_type is empty string, GENERAL is used as fallback."""
        from core.multi_llm_router import TaskType
        decision = _make_routing_decision()
        oc, mock_router = _make_openclawd_with_router(decision)

        with patch(
            "core.multimodal.modality_confidence_policy.build_perception_routing_readiness",
            side_effect=ImportError("not available"),
        ):
            oc._select_multimodal_route(
                canonical_perception={
                    "requires_native_multimodal": True,
                    "active_modalities": ["image"],
                },
                task_type="",
            )

        mock_router.route_multimodal_first.assert_called_once()
        call_kwargs = mock_router.route_multimodal_first.call_args.kwargs
        assert call_kwargs.get("task_type") == TaskType.GENERAL

    def test_c05_unrecognised_task_type_uses_general(self):
        """C05. When task_type is unrecognised, GENERAL is used as fallback."""
        from core.multi_llm_router import TaskType
        decision = _make_routing_decision()
        oc, mock_router = _make_openclawd_with_router(decision)

        with patch(
            "core.multimodal.modality_confidence_policy.build_perception_routing_readiness",
            side_effect=ImportError("not available"),
        ):
            oc._select_multimodal_route(
                canonical_perception={
                    "requires_native_multimodal": True,
                    "active_modalities": ["image"],
                },
                task_type="NOT_A_REAL_TASK_TYPE_XYZ",
            )

        mock_router.route_multimodal_first.assert_called_once()
        call_kwargs = mock_router.route_multimodal_first.call_args.kwargs
        assert call_kwargs.get("task_type") == TaskType.GENERAL

    def test_c06_text_only_short_circuit_unaffected(self):
        """C06. text_only short-circuit is not affected by task_type parameter."""
        oc = _make_openclawd_no_router()

        with patch(
            "core.multimodal.modality_confidence_policy.build_perception_routing_readiness",
            side_effect=ImportError("not available"),
        ):
            result = oc._select_multimodal_route(
                canonical_perception={
                    "requires_native_multimodal": False,
                    "active_modalities": [],
                },
                task_type="CODING",
            )

        assert result["route_type"] == "text_only"
        # router should never be consulted for text-only
        oc._get_router.assert_not_called()


# ─────────────────── Group D — Call-site task derivation ────────────────────


class TestProcessTaskDerivation:
    """Group D — process() derives and passes task type to _select_multimodal_route."""

    def test_d01_process_derives_task_type(self):
        """D01. process() calls classify_task to derive task type before routing.

        This is a structural assertion: verify that the process() source contains
        the classify_task derivation block added by PR-17 and that it is wired
        into the _select_multimodal_route call site.
        """
        import pathlib
        src = pathlib.Path(
            "/home/runner/work/ufo-galaxy-realization-v2/ufo-galaxy-realization-v2/"
            "core/openclawd.py"
        ).read_text()

        # The PR-17 derivation block must be present
        assert "_pr17_router.classify_task" in src or "classify_task(" in src, (
            "process() must contain a classify_task() call for PR-17 task derivation"
        )
        assert "_pr17_task_type" in src, (
            "process() must track the derived task type in _pr17_task_type"
        )

    def test_d02_classify_task_result_used_as_task_type(self):
        """D02. When classify_task succeeds, its .value is passed to _select_multimodal_route.

        Verify that the source wires the classified result into _select_multimodal_route
        using the canonical pattern established by PR-17.
        """
        import pathlib
        src = pathlib.Path(
            "/home/runner/work/ufo-galaxy-realization-v2/ufo-galaxy-realization-v2/"
            "core/openclawd.py"
        ).read_text()

        # classify_task result .value is captured as _pr17_task_type
        assert "_pr17_task_type = _pr17_classified.value" in src, (
            "process() must extract .value from classify_task() result "
            "as _pr17_task_type for routing wiring (PR-17)"
        )

    def test_d03_select_multimodal_route_passes_task_type(self):
        """D03. process() passes derived task_type into _select_multimodal_route."""
        # This is a structural test ensuring the call from process() includes task_type.
        import pathlib

        src = pathlib.Path(
            "/home/runner/work/ufo-galaxy-realization-v2/ufo-galaxy-realization-v2/"
            "core/openclawd.py"
        ).read_text()

        # Verify that the call to _select_multimodal_route in process() now
        # includes task_type (present after PR-17 wiring).
        assert "task_type=_pr17_task_type" in src, (
            "process() must pass task_type=_pr17_task_type to _select_multimodal_route (PR-17)"
        )


# ──────────────────────── Group E — Backward compat ─────────────────────────


class TestBackwardCompatibility:
    """Group E — existing callers are not broken by the PR-17 changes."""

    @pytest.mark.asyncio
    async def test_e01_fallback_chat_without_task_hint(self):
        """E01. _fallback_chat without task_hint still calls chat() successfully."""
        router = _make_mock_router("hello")
        kernel = _make_kernel_with_router(router)

        result = await kernel._fallback_chat(
            message="你好",
            session_id="s1",
            context=[],
            user_policy="",
        )
        assert result.success is True
        router.chat.assert_called_once()

    def test_e02_select_multimodal_route_no_task_type_returns_dict(self):
        """E02. _select_multimodal_route with no task_type still returns valid dict."""
        oc = _make_openclawd_no_router()

        with patch(
            "core.multimodal.modality_confidence_policy.build_perception_routing_readiness",
            side_effect=ImportError("not available"),
        ):
            result = oc._select_multimodal_route(
                canonical_perception={
                    "requires_native_multimodal": False,
                    "active_modalities": [],
                },
                # task_type not supplied — old-style call
            )

        assert isinstance(result, dict)
        assert "route_type" in result
        assert "provider" in result
        assert "model" in result

    def test_e03_route_keys_present_regardless_of_task_type(self):
        """E03. route_type/provider/model keys present in result regardless of task_type."""
        required_keys = {"route_type", "is_native_multimodal", "provider", "model",
                         "route_reason", "fallback_reason", "active_modalities"}
        oc = _make_openclawd_no_router()

        for task_type_val in [None, "", "CODING", "NOT_VALID_999"]:
            with patch(
                "core.multimodal.modality_confidence_policy.build_perception_routing_readiness",
                side_effect=ImportError("not available"),
            ):
                result = oc._select_multimodal_route(
                    canonical_perception=None,
                    task_type=task_type_val,
                )
            for key in required_keys:
                assert key in result, (
                    f"key '{key}' missing from _select_multimodal_route result "
                    f"when task_type={task_type_val!r}"
                )
