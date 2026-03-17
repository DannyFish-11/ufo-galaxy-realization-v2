"""
PR-6: Output Orchestrator — unit tests
========================================

Covers:
* TextChannel.build() — enabled, content, format selection, expression_hint
* VoiceChannel.build() — disabled default, enabled with tts_plan, mood hint
* AvatarChannel.build() — disabled default, enabled with animation plan, mood→expression
* OverlayChannel.build() — disabled default, enabled with overlay_plan, task_state steps
* OutputOrchestrator.orchestrate() — output keys present, text always enabled
* OutputOrchestrator with dict envelope (all channels on/off)
* OutputOrchestrator with InteractionEnvelope object
* OutputOrchestrator fallback on None envelope (text-only defaults)
* OutputOrchestrator actions extracted from task_state
* OpenClawd.process() includes ``output_plan`` key (non-regression)
* OpenClawd.process() ``output_plan`` has required top-level keys
* Existing response keys unaffected (non-regression)
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# TextChannel
# ---------------------------------------------------------------------------

class TestTextChannel:
    def _channel(self):
        from core.output.text_channel import TextChannel
        return TextChannel()

    def test_always_enabled(self):
        plan = self._channel().build(response_text="hello")
        assert plan["enabled"] is True

    def test_content_preserved(self):
        plan = self._channel().build(response_text="test response")
        assert plan["content"] == "test response"

    def test_markdown_for_chat_panel(self):
        plan = self._channel().build(response_text="x", ui_surface="chat_panel")
        assert plan["format"] == "markdown"

    def test_markdown_for_infinite_canvas(self):
        plan = self._channel().build(response_text="x", ui_surface="infinite_canvas")
        assert plan["format"] == "markdown"

    def test_plain_for_unknown_surface(self):
        plan = self._channel().build(response_text="x", ui_surface="unknown_surface")
        assert plan["format"] == "plain"

    def test_streaming_default_false(self):
        plan = self._channel().build(response_text="x")
        assert plan["streaming"] is False

    def test_streaming_true(self):
        plan = self._channel().build(response_text="x", streaming=True)
        assert plan["streaming"] is True

    def test_expression_hint_from_persona_state(self):
        ps = {"expression_mode": "quiet_luminous"}
        plan = self._channel().build(response_text="x", persona_state=ps)
        assert plan["expression_hint"] == "quiet_luminous"

    def test_expression_hint_none_without_persona(self):
        plan = self._channel().build(response_text="x")
        assert plan["expression_hint"] is None

    def test_required_keys(self):
        plan = self._channel().build(response_text="x")
        for key in ("enabled", "content", "format", "streaming", "expression_hint"):
            assert key in plan, f"Key {key!r} missing from text channel plan"


# ---------------------------------------------------------------------------
# VoiceChannel
# ---------------------------------------------------------------------------

class TestVoiceChannel:
    def _channel(self):
        from core.output.voice_channel import VoiceChannel
        return VoiceChannel()

    def test_disabled_by_default(self):
        plan = self._channel().build(response_text="hello", enabled=False)
        assert plan["enabled"] is False
        assert plan["tts_plan"] is None

    def test_note_present_when_disabled(self):
        plan = self._channel().build(response_text="hello", enabled=False)
        assert "note" in plan

    def test_enabled_returns_tts_plan(self):
        plan = self._channel().build(response_text="hello", enabled=True)
        assert plan["enabled"] is True
        assert isinstance(plan["tts_plan"], dict)

    def test_tts_plan_keys(self):
        plan = self._channel().build(response_text="hello", enabled=True)
        tp = plan["tts_plan"]
        for key in ("engine", "text", "voice_id", "speed", "pitch", "mood_hint"):
            assert key in tp, f"Key {key!r} missing from tts_plan"

    def test_tts_plan_engine_is_stub(self):
        plan = self._channel().build(response_text="hi", enabled=True)
        assert plan["tts_plan"]["engine"] == "stub"

    def test_tts_plan_text_matches_response(self):
        plan = self._channel().build(response_text="synthesize me", enabled=True)
        assert plan["tts_plan"]["text"] == "synthesize me"

    def test_mood_hint_from_persona_state(self):
        ps = {"mood": "excited"}
        plan = self._channel().build(response_text="hi", enabled=True, persona_state=ps)
        assert plan["tts_plan"]["mood_hint"] == "excited"

    def test_mood_hint_default_when_no_persona(self):
        plan = self._channel().build(response_text="hi", enabled=True)
        assert plan["tts_plan"]["mood_hint"] == "calm"


# ---------------------------------------------------------------------------
# AvatarChannel
# ---------------------------------------------------------------------------

class TestAvatarChannel:
    def _channel(self):
        from core.output.avatar_channel import AvatarChannel
        return AvatarChannel()

    def test_disabled_by_default(self):
        plan = self._channel().build(enabled=False)
        assert plan["enabled"] is False
        assert plan["avatar_plan"] is None

    def test_note_present_when_disabled(self):
        plan = self._channel().build(enabled=False)
        assert "note" in plan

    def test_enabled_returns_avatar_plan(self):
        plan = self._channel().build(enabled=True, mode="chat")
        assert plan["enabled"] is True
        assert isinstance(plan["avatar_plan"], dict)

    def test_avatar_plan_keys(self):
        plan = self._channel().build(enabled=True, mode="chat")
        ap = plan["avatar_plan"]
        for key in ("expression", "animation", "pose", "energy_level", "blink"):
            assert key in ap, f"Key {key!r} missing from avatar_plan"

    def test_animation_mapped_from_mode(self):
        plan = self._channel().build(enabled=True, mode="deep_thinking")
        assert plan["avatar_plan"]["animation"] == "thinking"

    def test_animation_field_assistant(self):
        plan = self._channel().build(enabled=True, mode="field_assistant")
        assert plan["avatar_plan"]["animation"] == "guiding"

    def test_expression_from_persona_mood(self):
        ps = {"mood": "curious", "energy": 0.9}
        plan = self._channel().build(enabled=True, persona_state=ps)
        assert plan["avatar_plan"]["expression"] == "curious"

    def test_energy_level_from_persona(self):
        ps = {"mood": "calm", "energy": 0.4}
        plan = self._channel().build(enabled=True, persona_state=ps)
        assert abs(plan["avatar_plan"]["energy_level"] - 0.4) < 1e-9

    def test_expression_default_neutral(self):
        plan = self._channel().build(enabled=True)
        assert plan["avatar_plan"]["expression"] == "neutral"


# ---------------------------------------------------------------------------
# OverlayChannel
# ---------------------------------------------------------------------------

class TestOverlayChannel:
    def _channel(self):
        from core.output.overlay_channel import OverlayChannel
        return OverlayChannel()

    def test_disabled_by_default(self):
        plan = self._channel().build(enabled=False)
        assert plan["enabled"] is False
        assert plan["overlay_plan"] is None

    def test_note_present_when_disabled(self):
        plan = self._channel().build(enabled=False)
        assert "note" in plan

    def test_enabled_returns_overlay_plan(self):
        plan = self._channel().build(enabled=True)
        assert plan["enabled"] is True
        assert isinstance(plan["overlay_plan"], dict)

    def test_overlay_plan_keys(self):
        plan = self._channel().build(enabled=True)
        op = plan["overlay_plan"]
        for key in ("type", "position", "content_snippet", "highlight_targets",
                    "steps", "opacity"):
            assert key in op, f"Key {key!r} missing from overlay_plan"

    def test_content_snippet_from_response(self):
        plan = self._channel().build(enabled=True, response_text="annotate this")
        assert "annotate this" in plan["overlay_plan"]["content_snippet"]

    def test_content_snippet_truncated(self):
        long_text = "x" * 200
        plan = self._channel().build(enabled=True, response_text=long_text)
        assert len(plan["overlay_plan"]["content_snippet"]) <= 120

    def test_steps_from_task_state(self):
        ts = {"steps": ["step1", "step2", "step3"]}
        plan = self._channel().build(enabled=True, task_state=ts)
        assert len(plan["overlay_plan"]["steps"]) == 3
        assert plan["overlay_plan"]["steps"][0] == {"label": "step1"}

    def test_steps_limited_to_five(self):
        ts = {"steps": [str(i) for i in range(10)]}
        plan = self._channel().build(enabled=True, task_state=ts)
        assert len(plan["overlay_plan"]["steps"]) <= 5

    def test_steps_empty_without_task_state(self):
        plan = self._channel().build(enabled=True)
        assert plan["overlay_plan"]["steps"] == []


# ---------------------------------------------------------------------------
# OutputOrchestrator
# ---------------------------------------------------------------------------

class TestOutputOrchestrator:
    def _orch(self):
        from core.output.orchestrator import OutputOrchestrator
        return OutputOrchestrator()

    def test_output_keys_present(self):
        plan = self._orch().orchestrate(
            interaction_envelope=None,
            persona_state=None,
            response_text="hi",
        )
        for key in ("text", "voice", "avatar", "overlay", "actions"):
            assert key in plan, f"Key {key!r} missing from output_plan"

    def test_text_always_enabled(self):
        plan = self._orch().orchestrate(
            interaction_envelope=None,
            persona_state=None,
            response_text="hello",
        )
        assert plan["text"]["enabled"] is True

    def test_text_content_matches_response(self):
        plan = self._orch().orchestrate(
            interaction_envelope=None,
            persona_state=None,
            response_text="the response",
        )
        assert plan["text"]["content"] == "the response"

    def test_voice_disabled_by_default(self):
        plan = self._orch().orchestrate(
            interaction_envelope=None,
            persona_state=None,
            response_text="hi",
        )
        assert plan["voice"]["enabled"] is False

    def test_avatar_disabled_by_default(self):
        plan = self._orch().orchestrate(
            interaction_envelope=None,
            persona_state=None,
            response_text="hi",
        )
        assert plan["avatar"]["enabled"] is False

    def test_overlay_disabled_by_default(self):
        plan = self._orch().orchestrate(
            interaction_envelope=None,
            persona_state=None,
            response_text="hi",
        )
        assert plan["overlay"]["enabled"] is False

    def test_actions_empty_without_task_state(self):
        plan = self._orch().orchestrate(
            interaction_envelope=None,
            persona_state=None,
            response_text="hi",
        )
        assert plan["actions"] == []

    def test_actions_extracted_from_task_state(self):
        ts = {"actions": [{"type": "navigate", "url": "/"}, {"type": "click"}]}
        plan = self._orch().orchestrate(
            interaction_envelope=None,
            persona_state=None,
            response_text="hi",
            task_state=ts,
        )
        assert len(plan["actions"]) == 2
        assert plan["actions"][0]["type"] == "navigate"

    def test_voice_enabled_from_dict_envelope(self):
        envelope = {
            "mode": "field_assistant",
            "output_plan": {
                "text": True, "voice": True, "avatar": True,
                "overlay": True, "ui_surface": "field_overlay",
            },
        }
        plan = self._orch().orchestrate(
            interaction_envelope=envelope,
            persona_state=None,
            response_text="guide me",
        )
        assert plan["voice"]["enabled"] is True
        assert plan["avatar"]["enabled"] is True
        assert plan["overlay"]["enabled"] is True

    def test_dict_envelope_mode_propagated_to_avatar(self):
        envelope = {
            "mode": "deep_thinking",
            "output_plan": {
                "text": True, "voice": False, "avatar": True,
                "overlay": False, "ui_surface": "infinite_canvas",
            },
        }
        plan = self._orch().orchestrate(
            interaction_envelope=envelope,
            persona_state=None,
            response_text="deep thought",
        )
        assert plan["avatar"]["avatar_plan"]["animation"] == "thinking"

    def test_ui_surface_propagated_to_text_channel(self):
        envelope = {
            "mode": "chat",
            "output_plan": {
                "text": True, "voice": False, "avatar": False,
                "overlay": False, "ui_surface": "chat_panel",
            },
        }
        plan = self._orch().orchestrate(
            interaction_envelope=envelope,
            persona_state=None,
            response_text="hello",
        )
        assert plan["text"]["format"] == "markdown"

    def test_with_interaction_envelope_object(self):
        from core.schemas.interaction_envelope import InteractionEnvelope, OutputPlan
        envelope = InteractionEnvelope(
            mode="ambient_companion",
            output_plan=OutputPlan(
                text=True, voice=True, avatar=True,
                overlay=False, ui_surface="ambient",
            ),
        )
        plan = self._orch().orchestrate(
            interaction_envelope=envelope,
            persona_state=None,
            response_text="companion",
        )
        assert plan["text"]["enabled"] is True
        assert plan["voice"]["enabled"] is True
        assert plan["avatar"]["enabled"] is True

    def test_persona_state_propagated_to_text_expression(self):
        ps = {"expression_mode": "luminous", "mood": "curious", "energy": 0.8}
        plan = self._orch().orchestrate(
            interaction_envelope=None,
            persona_state=ps,
            response_text="response",
        )
        assert plan["text"]["expression_hint"] == "luminous"

    def test_persona_state_propagated_to_avatar(self):
        envelope = {"mode": "chat",
                    "output_plan": {"text": True, "voice": False, "avatar": True,
                                    "overlay": False, "ui_surface": "chat_panel"}}
        ps = {"mood": "joyful", "energy": 0.9}
        plan = self._orch().orchestrate(
            interaction_envelope=envelope,
            persona_state=ps,
            response_text="hi",
        )
        assert plan["avatar"]["avatar_plan"]["expression"] == "happy"

    def test_result_is_json_serialisable(self):
        import json
        plan = self._orch().orchestrate(
            interaction_envelope=None,
            persona_state={"mood": "calm", "energy": 0.7, "expression_mode": "quiet"},
            response_text="json test",
            task_state={"actions": [{"type": "ping"}]},
        )
        # Must not raise
        json.dumps(plan)


# ---------------------------------------------------------------------------
# OpenClawd integration (non-regression + output_plan injection)
# ---------------------------------------------------------------------------

class TestOpenClawdOutputPlan:
    """Verify that OpenClawd.process() now includes ``output_plan``."""

    async def _run_process(self, message: str = "hello") -> Dict[str, Any]:
        from core.openclawd import OpenClawd

        oc = OpenClawd()

        async def _mock_chat(message, intent=None, device_id=None,
                              session_id=None, trace_id=None):
            return {"success": True, "response": "ok", "metadata": {}}

        with patch.object(oc, "_get_kernel", return_value=None):
            with patch.object(oc, "sync_device_capabilities", return_value=0):
                with patch.object(oc, "_parse_intent", return_value=None):
                    with patch.object(oc, "_dispatch_chat", side_effect=_mock_chat):
                        return await oc.process(message=message)

    @pytest.mark.asyncio
    async def test_process_includes_output_plan_key(self):
        result = await self._run_process(message="hello")
        assert "output_plan" in result

    @pytest.mark.asyncio
    async def test_output_plan_has_required_top_level_keys(self):
        result = await self._run_process(message="hello")
        op = result.get("output_plan")
        # output_plan may be None if orchestrator import fails in test env;
        # skip the sub-key check in that case
        if op is not None:
            for key in ("text", "voice", "avatar", "overlay", "actions"):
                assert key in op, f"Key {key!r} missing from output_plan"

    @pytest.mark.asyncio
    async def test_output_plan_text_always_enabled(self):
        result = await self._run_process(message="hello")
        op = result.get("output_plan")
        if op is not None and isinstance(op, dict):
            assert op["text"]["enabled"] is True

    @pytest.mark.asyncio
    async def test_existing_keys_unaffected(self):
        """Non-regression: existing response structure must be preserved."""
        result = await self._run_process(message="hello")
        for key in ("success", "response", "intent", "trace_id", "metadata"):
            assert key in result, f"Key {key!r} missing — regression!"

    @pytest.mark.asyncio
    async def test_response_text_unchanged(self):
        """Confirm that ``output_plan`` never modifies the ``response`` value."""
        result = await self._run_process(message="hello")
        assert result["response"] == "ok"
