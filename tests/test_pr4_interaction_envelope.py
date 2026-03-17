"""
PR-4: InteractionEnvelope schema + builder — unit tests
=========================================================

Covers:
* OutputPlan defaults (text_only, from_mode for every mode)
* OutputPlan.to_dict() keys and values
* InteractionEnvelope dataclass construction and to_dict() / model_dump()
* InteractionBuilder.build() with full inputs (scene decision + persona + context)
* InteractionBuilder.build() text-only fallback (all optional args omitted)
* InteractionBuilder strips binary payload keys from fused context
* InteractionBuilder error resilience (bad inputs return fallback envelope)
* OpenClawd.process() attaches ``interaction_envelope`` key to response
* OpenClawd.process() ``interaction_envelope`` contains expected fields
* Existing response keys are unaffected (non-regression)
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# OutputPlan tests
# ---------------------------------------------------------------------------

class TestOutputPlan:
    def test_text_only_defaults(self):
        from core.schemas.interaction_envelope import OutputPlan

        plan = OutputPlan.text_only()
        assert plan.text is True
        assert plan.voice is False
        assert plan.avatar is False
        assert plan.overlay is False
        assert plan.ui_surface == "chat_panel"

    def test_to_dict_keys(self):
        from core.schemas.interaction_envelope import OutputPlan

        d = OutputPlan().to_dict()
        assert set(d.keys()) == {"text", "voice", "avatar", "overlay", "ui_surface"}

    @pytest.mark.parametrize("mode,expected_surface", [
        ("chat", "chat_panel"),
        ("deep_thinking", "infinite_canvas"),
        ("control_console", "control_console"),
        ("field_assistant", "field_overlay"),
        ("ambient_companion", "ambient"),
        ("execution_bridge", "control_console"),
    ])
    def test_from_mode_surface(self, mode: str, expected_surface: str):
        from core.schemas.interaction_envelope import OutputPlan

        plan = OutputPlan.from_mode(mode)
        assert plan.ui_surface == expected_surface

    def test_from_mode_field_assistant_enables_overlay_and_voice(self):
        from core.schemas.interaction_envelope import OutputPlan

        plan = OutputPlan.from_mode("field_assistant")
        assert plan.voice is True
        assert plan.overlay is True
        assert plan.avatar is True

    def test_from_mode_unknown_falls_back_to_chat(self):
        from core.schemas.interaction_envelope import OutputPlan

        plan = OutputPlan.from_mode("nonexistent_mode")
        assert plan.ui_surface == "chat_panel"
        assert plan.voice is False

    def test_from_mode_text_always_true(self):
        from core.schemas.interaction_envelope import OutputPlan

        for mode in ("chat", "deep_thinking", "control_console", "field_assistant",
                     "ambient_companion", "execution_bridge"):
            assert OutputPlan.from_mode(mode).text is True


# ---------------------------------------------------------------------------
# InteractionEnvelope tests
# ---------------------------------------------------------------------------

class TestInteractionEnvelope:
    def test_default_construction(self):
        from core.schemas.interaction_envelope import InteractionEnvelope

        env = InteractionEnvelope()
        assert env.mode == "chat"
        assert env.interaction_id.startswith("ix_")
        assert env.session_id == "__global__"
        assert env.trace_id is None
        assert env.persona_state is None
        assert env.multimodal_context is None

    def test_to_dict_keys(self):
        from core.schemas.interaction_envelope import InteractionEnvelope

        d = InteractionEnvelope().to_dict()
        expected_keys = {
            "interaction_id", "trace_id", "session_id",
            "mode", "relationship_mode",
            "persona_state", "multimodal_context",
            "output_plan", "created_at",
        }
        assert set(d.keys()) == expected_keys

    def test_to_dict_output_plan_is_dict(self):
        from core.schemas.interaction_envelope import InteractionEnvelope

        d = InteractionEnvelope().to_dict()
        assert isinstance(d["output_plan"], dict)
        assert "ui_surface" in d["output_plan"]

    def test_model_dump_alias(self):
        from core.schemas.interaction_envelope import InteractionEnvelope

        env = InteractionEnvelope(trace_id="t1", session_id="s1", mode="chat")
        assert env.model_dump() == env.to_dict()

    def test_unique_interaction_ids(self):
        from core.schemas.interaction_envelope import InteractionEnvelope

        ids = {InteractionEnvelope().interaction_id for _ in range(50)}
        assert len(ids) == 50

    def test_created_at_is_iso_string_in_dict(self):
        from core.schemas.interaction_envelope import InteractionEnvelope

        d = InteractionEnvelope().to_dict()
        # Should be parseable as ISO 8601
        from datetime import datetime
        dt = datetime.fromisoformat(d["created_at"])
        assert dt.tzinfo is not None


# ---------------------------------------------------------------------------
# InteractionBuilder tests
# ---------------------------------------------------------------------------

class TestInteractionBuilder:
    def _make_decision(self, mode: str = "chat") -> Any:
        """Build a minimal InteractionDecision for testing."""
        from core.interaction.interaction_types import InteractionDecision, InteractionMode
        return InteractionDecision(
            mode=InteractionMode(mode),
            relationship_mode="scholar_companion",
            ui_surface="infinite_canvas",
        )

    def _make_persona_state(self) -> Any:
        """Build a minimal PersonaState for testing."""
        from core.schemas.persona_state import PersonaState
        return PersonaState(session_id="sess_test", mood="focused")

    def test_build_returns_envelope(self):
        from core.interaction.interaction_builder import InteractionBuilder
        from core.schemas.interaction_envelope import InteractionEnvelope

        env = InteractionBuilder().build(
            trace_id="t1",
            session_id="s1",
            scene_decision=self._make_decision("deep_thinking"),
            persona_state=self._make_persona_state(),
            fused_context={"fusion_summary": "test summary"},
        )
        assert isinstance(env, InteractionEnvelope)

    def test_build_propagates_trace_and_session(self):
        from core.interaction.interaction_builder import InteractionBuilder

        env = InteractionBuilder().build(trace_id="trace_abc", session_id="sess_xyz")
        assert env.trace_id == "trace_abc"
        assert env.session_id == "sess_xyz"

    def test_build_sets_mode_from_scene_decision(self):
        from core.interaction.interaction_builder import InteractionBuilder

        env = InteractionBuilder().build(
            trace_id="t2",
            session_id="s2",
            scene_decision=self._make_decision("control_console"),
        )
        assert env.mode == "control_console"

    def test_build_sets_relationship_mode(self):
        from core.interaction.interaction_builder import InteractionBuilder

        env = InteractionBuilder().build(
            scene_decision=self._make_decision("deep_thinking"),
        )
        assert env.relationship_mode == "scholar_companion"

    def test_build_serialises_persona_state(self):
        from core.interaction.interaction_builder import InteractionBuilder

        env = InteractionBuilder().build(
            persona_state=self._make_persona_state(),
        )
        assert isinstance(env.persona_state, dict)
        assert env.persona_state["mood"] == "focused"

    def test_build_accepts_persona_dict(self):
        from core.interaction.interaction_builder import InteractionBuilder

        persona_dict = {"session_id": "s1", "mood": "calm", "energy": 0.8}
        env = InteractionBuilder().build(persona_state=persona_dict)
        assert env.persona_state == persona_dict

    def test_build_strips_binary_context_keys(self):
        from core.interaction.interaction_builder import InteractionBuilder

        ctx = {
            "images": [{"data": "base64xxx"}],
            "audio": [{"data": "base64yyy"}],
            "fusion_summary": "a scene with an image",
            "modality_count": 1,
        }
        env = InteractionBuilder().build(fused_context=ctx)
        assert env.multimodal_context is not None
        assert "images" not in env.multimodal_context
        assert "audio" not in env.multimodal_context
        assert env.multimodal_context["fusion_summary"] == "a scene with an image"

    def test_build_text_only_all_optional_none(self):
        from core.interaction.interaction_builder import InteractionBuilder
        from core.schemas.interaction_envelope import InteractionEnvelope

        env = InteractionBuilder().build()
        assert isinstance(env, InteractionEnvelope)
        assert env.mode == "chat"
        assert env.persona_state is None
        assert env.multimodal_context is None

    def test_build_derives_output_plan_from_mode(self):
        from core.interaction.interaction_builder import InteractionBuilder

        env = InteractionBuilder().build(
            scene_decision=self._make_decision("field_assistant"),
        )
        assert env.output_plan.overlay is True
        assert env.output_plan.voice is True
        assert env.output_plan.ui_surface == "field_overlay"

    def test_build_accepts_custom_output_plan(self):
        from core.interaction.interaction_builder import InteractionBuilder
        from core.schemas.interaction_envelope import OutputPlan

        custom = OutputPlan(text=True, voice=True, avatar=False, overlay=False, ui_surface="custom")
        env = InteractionBuilder().build(output_plan=custom)
        assert env.output_plan.ui_surface == "custom"

    def test_build_error_resilience_bad_scene_decision(self):
        """Passing a broken scene decision should not raise — returns fallback envelope."""
        from core.interaction.interaction_builder import InteractionBuilder
        from core.schemas.interaction_envelope import InteractionEnvelope

        # An object that raises on attribute access
        bad_decision = MagicMock(spec=[])
        bad_decision.mode = property(lambda s: (_ for _ in ()).throw(RuntimeError("boom")))
        type(bad_decision).mode = property(lambda s: (_ for _ in ()).throw(RuntimeError("boom")))

        env = InteractionBuilder().build(
            trace_id="t_err",
            session_id="s_err",
            scene_decision=bad_decision,
        )
        assert isinstance(env, InteractionEnvelope)
        assert env.mode == "chat"  # fallback

    def test_to_dict_is_json_serialisable(self):
        import json
        from core.interaction.interaction_builder import InteractionBuilder

        env = InteractionBuilder().build(
            trace_id="t_json",
            session_id="s_json",
            scene_decision=self._make_decision("deep_thinking"),
            persona_state=self._make_persona_state(),
            fused_context={"fusion_summary": "ok"},
        )
        d = env.to_dict()
        # Should not raise
        json.dumps(d)


# ---------------------------------------------------------------------------
# OpenClawd.process() integration tests
# ---------------------------------------------------------------------------

class TestOpenClawdInteractionEnvelope:
    """Verify OpenClawd.process() attaches interaction_envelope to its response.

    Only ``_get_kernel``, ``sync_device_capabilities``, ``_parse_intent``, and
    ``_dispatch_chat`` are mocked.  The ``SceneInterpreter`` is **not** mocked —
    it runs the actual rule engine, so assertions on ``mode`` reflect the real
    keyword-based decision logic.
    """

    async def _run_process(self, message: str, multimodal_context=None) -> dict:
        from core.openclawd import OpenClawd

        oc = OpenClawd()

        async def _mock_chat(message, intent=None, device_id=None,
                              session_id=None, trace_id=None):
            return {"success": True, "response": "ok", "metadata": {}}

        with patch.object(oc, "_get_kernel", return_value=None):
            with patch.object(oc, "sync_device_capabilities", return_value=0):
                with patch.object(oc, "_parse_intent", return_value=None):
                    with patch.object(oc, "_dispatch_chat", side_effect=_mock_chat):
                        return await oc.process(
                            message=message,
                            multimodal_context=multimodal_context,
                        )

    @pytest.mark.asyncio
    async def test_process_includes_interaction_envelope_key(self):
        result = await self._run_process(message="hello")
        assert "interaction_envelope" in result

    @pytest.mark.asyncio
    async def test_process_interaction_envelope_has_required_fields(self):
        result = await self._run_process(message="hello")
        envelope = result.get("interaction_envelope")
        assert envelope is not None
        for key in ("interaction_id", "trace_id", "session_id", "mode",
                    "relationship_mode", "output_plan", "created_at"):
            assert key in envelope, f"Key {key!r} missing from interaction_envelope"

    @pytest.mark.asyncio
    async def test_process_envelope_trace_id_matches_response(self):
        result = await self._run_process(message="hello")
        envelope = result.get("interaction_envelope")
        assert envelope is not None
        assert envelope["trace_id"] == result["trace_id"]

    @pytest.mark.asyncio
    async def test_process_envelope_output_plan_present(self):
        result = await self._run_process(message="hello")
        envelope = result.get("interaction_envelope")
        assert envelope is not None
        assert isinstance(envelope["output_plan"], dict)
        assert envelope["output_plan"]["text"] is True

    @pytest.mark.asyncio
    async def test_process_existing_keys_unaffected(self):
        """Existing response structure must be preserved (non-regression)."""
        result = await self._run_process(message="hello")
        for key in ("success", "response", "intent", "trace_id", "metadata"):
            assert key in result, f"Key {key!r} missing from result — regression!"

    @pytest.mark.asyncio
    async def test_process_control_message_envelope_mode(self):
        result = await self._run_process(message="帮我执行这个部署脚本")
        envelope = result.get("interaction_envelope")
        assert envelope is not None
        assert envelope["mode"] == "control_console"

    @pytest.mark.asyncio
    async def test_process_deep_thinking_envelope_surface(self):
        result = await self._run_process(
            message="请深度分析一下这套架构设计的底层原理和本质逻辑，以及它背后的哲学基础和理论支撑是什么？"
        )
        envelope = result.get("interaction_envelope")
        assert envelope is not None
        assert envelope["mode"] == "deep_thinking"
        assert envelope["output_plan"]["ui_surface"] == "infinite_canvas"
