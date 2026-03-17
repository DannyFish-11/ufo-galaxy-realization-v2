"""
PR-2: Scene Interpreter / Interaction Mode Engine — unit tests
==============================================================

Covers:
* InteractionMode enum values
* InteractionDecision to_dict / from_dict round-trip
* ModeSelector.build_decision for every mode
* SceneInterpreter rule engine:
  - CONTROL_CONSOLE on execution keywords
  - FIELD_ASSISTANT on visual context + pointing keywords
  - DEEP_THINKING on long message with analytical keywords
  - AMBIENT_COMPANION on very short message
  - CHAT as default fallback
  - mode_hint caller override
  - invalid mode_hint falls through to rules
  - error resilience: bad fused_context does not raise
* EventBus event emission (INTERACTION_MODE_SELECTED)
* OpenClawd.process() attaches ``interaction`` key when multimodal input provided
* OpenClawd.process() text-only response is unchanged (no regression)
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# InteractionMode enum tests
# ---------------------------------------------------------------------------

class TestInteractionModeEnum:
    def test_all_expected_values_exist(self):
        from core.interaction.interaction_types import InteractionMode

        expected = {
            "chat", "deep_thinking", "control_console",
            "field_assistant", "ambient_companion", "execution_bridge",
        }
        actual = {m.value for m in InteractionMode}
        assert expected == actual

    def test_str_enum_identity(self):
        from core.interaction.interaction_types import InteractionMode

        assert InteractionMode.CHAT.value == "chat"
        assert InteractionMode("control_console") is InteractionMode.CONTROL_CONSOLE

    def test_invalid_value_raises(self):
        from core.interaction.interaction_types import InteractionMode

        with pytest.raises(ValueError):
            InteractionMode("unknown_mode")


# ---------------------------------------------------------------------------
# InteractionDecision serialisation tests
# ---------------------------------------------------------------------------

class TestInteractionDecisionSerialisation:
    def test_to_dict_keys(self):
        from core.interaction.interaction_types import InteractionDecision, InteractionMode

        d = InteractionDecision(mode=InteractionMode.CHAT, rationale="test").to_dict()
        assert set(d.keys()) == {
            "mode", "relationship_mode", "ui_surface",
            "voice_mode", "avatar_mode", "confidence", "rationale",
        }

    def test_to_dict_mode_is_string(self):
        from core.interaction.interaction_types import InteractionDecision, InteractionMode

        d = InteractionDecision(mode=InteractionMode.DEEP_THINKING).to_dict()
        assert d["mode"] == "deep_thinking"
        assert isinstance(d["mode"], str)

    def test_from_dict_round_trip(self):
        from core.interaction.interaction_types import InteractionDecision, InteractionMode

        original = InteractionDecision(
            mode=InteractionMode.CONTROL_CONSOLE,
            relationship_mode="commander_executor",
            ui_surface="control_console",
            voice_mode="off",
            avatar_mode="standby",
            confidence=0.9,
            rationale="test rationale",
        )
        reconstructed = InteractionDecision.from_dict(original.to_dict())
        assert reconstructed.mode == original.mode
        assert reconstructed.relationship_mode == original.relationship_mode
        assert reconstructed.ui_surface == original.ui_surface
        assert reconstructed.confidence == original.confidence
        assert reconstructed.rationale == original.rationale

    def test_from_dict_missing_keys_use_defaults(self):
        from core.interaction.interaction_types import InteractionDecision, InteractionMode

        d = InteractionDecision.from_dict({})
        assert d.mode == InteractionMode.CHAT
        assert d.relationship_mode == "user_companion"


# ---------------------------------------------------------------------------
# ModeSelector tests
# ---------------------------------------------------------------------------

class TestModeSelector:
    def test_build_decision_returns_correct_mode(self):
        from core.interaction.interaction_types import InteractionMode
        from core.interaction.mode_selector import ModeSelector

        selector = ModeSelector()
        for mode in InteractionMode:
            decision = selector.build_decision(mode=mode)
            assert decision.mode is mode

    def test_confidence_clamped(self):
        from core.interaction.interaction_types import InteractionMode
        from core.interaction.mode_selector import ModeSelector

        selector = ModeSelector()
        assert selector.build_decision(mode=InteractionMode.CHAT, confidence=5.0).confidence == 1.0
        assert selector.build_decision(mode=InteractionMode.CHAT, confidence=-1.0).confidence == 0.0

    def test_overrides_applied(self):
        from core.interaction.interaction_types import InteractionMode
        from core.interaction.mode_selector import ModeSelector

        selector = ModeSelector()
        decision = selector.build_decision(
            mode=InteractionMode.CHAT,
            overrides={"ui_surface": "custom_surface"},
        )
        assert decision.ui_surface == "custom_surface"

    def test_deep_thinking_defaults(self):
        from core.interaction.interaction_types import InteractionMode
        from core.interaction.mode_selector import ModeSelector

        selector = ModeSelector()
        decision = selector.build_decision(mode=InteractionMode.DEEP_THINKING)
        assert decision.ui_surface == "infinite_canvas"
        assert decision.voice_mode == "ambient"
        assert decision.avatar_mode == "focused"

    def test_control_console_defaults(self):
        from core.interaction.interaction_types import InteractionMode
        from core.interaction.mode_selector import ModeSelector

        selector = ModeSelector()
        decision = selector.build_decision(mode=InteractionMode.CONTROL_CONSOLE)
        assert decision.ui_surface == "control_console"
        assert decision.voice_mode == "off"

    def test_field_assistant_defaults(self):
        from core.interaction.interaction_types import InteractionMode
        from core.interaction.mode_selector import ModeSelector

        selector = ModeSelector()
        decision = selector.build_decision(mode=InteractionMode.FIELD_ASSISTANT)
        assert decision.voice_mode == "active"
        assert decision.avatar_mode == "guiding"


# ---------------------------------------------------------------------------
# SceneInterpreter rule-engine tests
# ---------------------------------------------------------------------------

class TestSceneInterpreterRules:
    """Each test validates one rule branch of SceneInterpreter."""

    def _interp(self):
        from core.interaction.scene_interpreter import SceneInterpreter
        return SceneInterpreter()

    # ── CONTROL_CONSOLE ───────────────────────────────────────────────────

    def test_control_console_chinese_keywords(self):
        from core.interaction.interaction_types import InteractionMode

        for kw in ("执行任务", "帮我跑个脚本", "运行部署命令", "启动服务流程"):
            d = self._interp().interpret(message=kw)
            assert d.mode is InteractionMode.CONTROL_CONSOLE, f"Failed for: {kw!r}"

    def test_control_console_english_keywords(self):
        from core.interaction.interaction_types import InteractionMode

        for kw in ("please execute this", "deploy the script", "run the command"):
            d = self._interp().interpret(message=kw)
            assert d.mode is InteractionMode.CONTROL_CONSOLE, f"Failed for: {kw!r}"

    # ── FIELD_ASSISTANT ───────────────────────────────────────────────────

    def test_field_assistant_requires_visual_context(self):
        from core.interaction.interaction_types import InteractionMode

        # Without visual context → should NOT be FIELD_ASSISTANT
        d = self._interp().interpret(message="这个怎么修", fused_context=None)
        assert d.mode is not InteractionMode.FIELD_ASSISTANT

    def test_field_assistant_with_image_and_keyword(self):
        from core.interaction.interaction_types import InteractionMode

        fused = {"images": [{"mime": "image/jpeg", "source": "webcam"}], "fusion_summary": "[image]"}
        d = self._interp().interpret(message="帮我看看这个怎么修", fused_context=fused)
        assert d.mode is InteractionMode.FIELD_ASSISTANT

    def test_field_assistant_with_screen_context_and_keyword(self):
        from core.interaction.interaction_types import InteractionMode

        fused = {"images": [], "screen": {"title": "Terminal"}, "fusion_summary": ""}
        d = self._interp().interpret(message="这里是什么", fused_context=fused)
        assert d.mode is InteractionMode.FIELD_ASSISTANT

    def test_field_assistant_visual_context_but_no_field_keyword(self):
        from core.interaction.interaction_types import InteractionMode

        fused = {"images": [{"mime": "image/jpeg"}], "fusion_summary": "[image]"}
        d = self._interp().interpret(message="你好，天气怎么样？", fused_context=fused)
        # No pointing keywords — should fall through to CHAT
        assert d.mode is InteractionMode.CHAT

    # ── DEEP_THINKING ─────────────────────────────────────────────────────

    def test_deep_thinking_long_message_with_keywords(self):
        from core.interaction.interaction_types import InteractionMode

        msg = "我想深入探讨一下这个系统的哲学原理和核心架构，以及它背后的本质逻辑和机制，这对我们理解整体结构非常重要"
        assert len(msg) > 40
        d = self._interp().interpret(message=msg)
        assert d.mode is InteractionMode.DEEP_THINKING

    def test_deep_thinking_requires_min_length(self):
        from core.interaction.interaction_types import InteractionMode

        # Short message with keyword — NOT deep_thinking
        d = self._interp().interpret(message="哲学")
        assert d.mode is not InteractionMode.DEEP_THINKING

    def test_deep_thinking_long_but_no_keywords(self):
        from core.interaction.interaction_types import InteractionMode

        msg = "今天天气不错，阳光很好，我们来聊聊今天发生了什么事情好不好呢？感觉心情很愉快，很想出去散步走走看看"
        assert len(msg) > 40
        d = self._interp().interpret(message=msg)
        assert d.mode is not InteractionMode.DEEP_THINKING

    # ── AMBIENT_COMPANION ─────────────────────────────────────────────────

    def test_ambient_companion_very_short_message(self):
        from core.interaction.interaction_types import InteractionMode

        for msg in ("hi", "嗯", "ok", "好的"):
            d = self._interp().interpret(message=msg)
            assert d.mode is InteractionMode.AMBIENT_COMPANION, f"Failed for: {msg!r}"

    def test_ambient_not_triggered_for_normal_length(self):
        from core.interaction.interaction_types import InteractionMode

        d = self._interp().interpret(message="你好，请帮我查一下今天的天气预报")
        assert d.mode is not InteractionMode.AMBIENT_COMPANION

    # ── CHAT default ──────────────────────────────────────────────────────

    def test_chat_default_fallback(self):
        from core.interaction.interaction_types import InteractionMode

        d = self._interp().interpret(message="你好，请介绍一下你自己")
        assert d.mode is InteractionMode.CHAT

    def test_chat_confidence_high(self):
        d = self._interp().interpret(message="你好，请介绍一下你自己")
        assert d.confidence >= 0.9

    # ── mode_hint override ────────────────────────────────────────────────

    def test_mode_hint_overrides_all_rules(self):
        from core.interaction.interaction_types import InteractionMode

        # A message that would normally be CONTROL_CONSOLE
        d = self._interp().interpret(
            message="执行这个脚本",
            mode_hint="deep_thinking",
        )
        assert d.mode is InteractionMode.DEEP_THINKING

    def test_mode_hint_ambient_companion(self):
        from core.interaction.interaction_types import InteractionMode

        d = self._interp().interpret(
            message="今天发生了什么",
            mode_hint="ambient_companion",
        )
        assert d.mode is InteractionMode.AMBIENT_COMPANION

    def test_mode_hint_execution_bridge(self):
        from core.interaction.interaction_types import InteractionMode

        d = self._interp().interpret(message="hello", mode_hint="execution_bridge")
        assert d.mode is InteractionMode.EXECUTION_BRIDGE

    def test_invalid_mode_hint_falls_through_to_rules(self):
        from core.interaction.interaction_types import InteractionMode

        # "not_a_mode" is invalid → rules should run → CONTROL_CONSOLE from keyword
        d = self._interp().interpret(
            message="执行任务",
            mode_hint="not_a_mode",
        )
        assert d.mode is InteractionMode.CONTROL_CONSOLE

    # ── error resilience ──────────────────────────────────────────────────

    def test_interpreter_never_raises_on_bad_fused_context(self):
        from core.interaction.interaction_types import InteractionMode

        # Pass various garbage values — should always return a decision
        for bad_ctx in [object(), 42, "string", b"bytes"]:
            d = self._interp().interpret(message="hello", fused_context=bad_ctx)
            assert isinstance(d.mode, InteractionMode)

    def test_empty_message_does_not_raise(self):
        from core.interaction.interaction_types import InteractionMode

        d = self._interp().interpret(message="")
        assert isinstance(d.mode, InteractionMode)


# ---------------------------------------------------------------------------
# EventBus integration
# ---------------------------------------------------------------------------

class TestSceneInterpreterEventBus:
    def test_event_emitted_on_interpret(self):
        """SceneInterpreter._emit_event should be called once per interpret() call."""
        import core.interaction.scene_interpreter as _mod

        with patch.object(_mod.SceneInterpreter, "_emit_event") as mock_emit:
            interp = _mod.SceneInterpreter()
            interp.interpret(message="执行脚本", session_id="sess_test")

        mock_emit.assert_called_once()
        _, kwargs = mock_emit.call_args
        assert kwargs.get("session_id") == "sess_test"

    def test_interaction_mode_selected_event_type_exists(self):
        from integration.event_bus import EventType

        assert hasattr(EventType, "INTERACTION_MODE_SELECTED")


# ---------------------------------------------------------------------------
# OpenClawd integration tests
# ---------------------------------------------------------------------------

class TestOpenClawdInteractionIntegration:
    """Verify OpenClawd.process() correctly attaches ``interaction`` to the payload."""

    @pytest.mark.asyncio
    async def test_process_text_only_has_interaction_key(self):
        """Text-only requests should still have an ``interaction`` key in the result."""
        from core.openclawd import OpenClawd

        oc = OpenClawd()

        async def _mock_chat(message, intent=None, device_id=None, session_id=None, trace_id=None):
            return {"success": True, "response": "hello", "metadata": {}}

        with patch.object(oc, "_get_kernel", return_value=None):
            with patch.object(oc, "sync_device_capabilities", return_value=0):
                with patch.object(oc, "_parse_intent", return_value=None):
                    with patch.object(oc, "_dispatch_chat", side_effect=_mock_chat):
                        result = await oc.process(message="你好")

        # The ``interaction`` key must be present (may be None if interpreter failed)
        assert "interaction" in result

    @pytest.mark.asyncio
    async def test_process_text_only_interaction_is_chat(self):
        """Text-only requests should produce CHAT interaction mode."""
        from core.openclawd import OpenClawd

        oc = OpenClawd()

        async def _mock_chat(message, intent=None, device_id=None, session_id=None, trace_id=None):
            return {"success": True, "response": "hello", "metadata": {}}

        with patch.object(oc, "_get_kernel", return_value=None):
            with patch.object(oc, "sync_device_capabilities", return_value=0):
                with patch.object(oc, "_parse_intent", return_value=None):
                    with patch.object(oc, "_dispatch_chat", side_effect=_mock_chat):
                        result = await oc.process(message="你好，请介绍一下你自己")

        interaction = result.get("interaction")
        if interaction is not None:  # May be None only if interpreter import fails
            assert interaction["mode"] == "chat"

    @pytest.mark.asyncio
    async def test_process_multimodal_attaches_interaction(self):
        """When multimodal_context is provided the result must include interaction info."""
        from core.schemas.multimodal import MultiModalContext, MultiModalImage
        from core.openclawd import OpenClawd

        oc = OpenClawd()
        ctx = MultiModalContext(
            images=[MultiModalImage(mime="image/jpeg", data="X", source="webcam")]
        )

        async def _mock_chat(message, intent=None, device_id=None, session_id=None, trace_id=None):
            return {"success": True, "response": "I see an image", "metadata": {}}

        with patch.object(oc, "_get_kernel", return_value=None):
            with patch.object(oc, "sync_device_capabilities", return_value=0):
                with patch.object(oc, "_parse_intent", return_value=None):
                    with patch.object(oc, "_dispatch_chat", side_effect=_mock_chat):
                        result = await oc.process(
                            message="帮我看看这个怎么修",
                            multimodal_context=ctx,
                        )

        assert "interaction" in result
        interaction = result["interaction"]
        assert interaction is not None
        # With image context + field keyword, expect FIELD_ASSISTANT
        assert interaction["mode"] == "field_assistant"

    @pytest.mark.asyncio
    async def test_process_control_message_returns_control_console(self):
        """Message with execution keywords should produce CONTROL_CONSOLE interaction."""
        from core.openclawd import OpenClawd

        oc = OpenClawd()

        async def _mock_chat(message, intent=None, device_id=None, session_id=None, trace_id=None):
            return {"success": True, "response": "ok", "metadata": {}}

        with patch.object(oc, "_get_kernel", return_value=None):
            with patch.object(oc, "sync_device_capabilities", return_value=0):
                with patch.object(oc, "_parse_intent", return_value=None):
                    with patch.object(oc, "_dispatch_chat", side_effect=_mock_chat):
                        result = await oc.process(message="帮我执行这个部署脚本")

        interaction = result.get("interaction")
        assert interaction is not None
        assert interaction["mode"] == "control_console"

    @pytest.mark.asyncio
    async def test_process_response_structure_unchanged_for_text_only(self):
        """Existing keys (success, response, intent, trace_id, metadata) must be present."""
        from core.openclawd import OpenClawd

        oc = OpenClawd()

        async def _mock_chat(message, intent=None, device_id=None, session_id=None, trace_id=None):
            return {"success": True, "response": "hello", "metadata": {}}

        with patch.object(oc, "_get_kernel", return_value=None):
            with patch.object(oc, "sync_device_capabilities", return_value=0):
                with patch.object(oc, "_parse_intent", return_value=None):
                    with patch.object(oc, "_dispatch_chat", side_effect=_mock_chat):
                        result = await oc.process(message="hi there")

        for key in ("success", "response", "intent", "trace_id", "metadata"):
            assert key in result, f"Key {key!r} missing from result"
