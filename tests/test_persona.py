"""
Galaxy — Persona / Spirit Engine unit tests (PR-3)
====================================================

Tests cover:
* PersonaState schema + to_dict()
* StateStore.get_state / update_state / reset_state
* EmotionEngine.compute_delta + apply_delta (all rule branches)
* OpenClawd.process() includes persona_state and is stable for text-only input
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

# ---------------------------------------------------------------------------
# PersonaState schema tests
# ---------------------------------------------------------------------------

class TestPersonaStateSchema:
    def test_default_baseline(self):
        from core.schemas.persona_state import PersonaState
        state = PersonaState.default_baseline("sess_1")
        assert state.session_id == "sess_1"
        assert state.mood == "calm"
        assert 0.0 <= state.energy <= 1.0
        assert 0.0 <= state.focus <= 1.0
        assert 0.0 <= state.trust_level <= 1.0

    def test_to_dict_contains_required_fields(self):
        from core.schemas.persona_state import PersonaState
        d = PersonaState.default_baseline("s1").to_dict()
        for key in ("session_id", "mood", "energy", "focus", "curiosity",
                    "urgency", "trust_level", "expression_mode", "updated_at"):
            assert key in d, f"Missing field: {key}"

    def test_to_dict_values_serialisable(self):
        import json
        from core.schemas.persona_state import PersonaState
        d = PersonaState.default_baseline().to_dict()
        # must not raise
        json.dumps(d)


# ---------------------------------------------------------------------------
# EmotionEngine tests
# ---------------------------------------------------------------------------

class TestEmotionEngine:
    def setup_method(self):
        from core.persona.emotion_engine import EmotionEngine
        self.engine = EmotionEngine()

    def test_gratitude_increases_trust(self):
        delta = self.engine.compute_delta("谢谢你帮助我")
        assert delta.get("trust_level", 0) > 0

    def test_english_thanks_increases_trust(self):
        delta = self.engine.compute_delta("thanks, that was awesome")
        assert delta.get("trust_level", 0) > 0

    def test_frustration_increases_urgency_and_decreases_energy(self):
        delta = self.engine.compute_delta("这个脚本崩溃了，完全错误")
        assert delta.get("urgency", 0) > 0
        assert delta.get("energy", 0) < 0

    def test_curiosity_keyword_increases_curiosity(self):
        delta = self.engine.compute_delta("为什么这个函数会失败？")
        assert delta.get("curiosity", 0) > 0

    def test_urgency_keyword_raises_urgency(self):
        delta = self.engine.compute_delta("紧急！马上处理")
        assert delta.get("urgency", 0) > 0

    def test_long_message_increases_focus(self):
        long_msg = "a" * 100  # > LONG_MSG_THRESHOLD
        delta = self.engine.compute_delta(long_msg)
        assert delta.get("focus", 0) > 0

    def test_control_console_mode_increases_focus_and_urgency(self):
        delta = self.engine.compute_delta("", interaction_mode="control_console")
        assert delta.get("focus", 0) > 0
        assert delta.get("urgency", 0) > 0

    def test_task_failure_control_console_sets_mood_override(self):
        delta = self.engine.compute_delta(
            "执行脚本", interaction_mode="control_console", task_success=False
        )
        assert delta.get("_mood_override") == "focused"
        assert delta.get("urgency", 0) > 0

    def test_task_success_increases_trust_and_energy(self):
        delta = self.engine.compute_delta("", task_success=True)
        assert delta.get("trust_level", 0) > 0
        assert delta.get("energy", 0) > 0

    def test_task_failure_increases_urgency(self):
        delta = self.engine.compute_delta("", task_success=False)
        assert delta.get("urgency", 0) > 0

    def test_empty_message_no_crash(self):
        delta = self.engine.compute_delta("")
        assert isinstance(delta, dict)

    def test_apply_delta_clips_values(self):
        from core.schemas.persona_state import PersonaState
        state = PersonaState.default_baseline("s1")
        state.urgency = 0.95
        delta = {"urgency": 0.5}  # should clip to 1.0, not 1.45
        self.engine.apply_delta(state, delta)
        assert state.urgency <= 1.0

    def test_apply_delta_updates_mood(self):
        from core.schemas.persona_state import PersonaState
        state = PersonaState.default_baseline("s1")
        # drive urgency above 0.6 → mood should become "concerned"
        state.urgency = 0.0
        delta = {"urgency": 0.7}
        self.engine.apply_delta(state, delta)
        assert state.mood == "concerned"

    def test_apply_delta_honours_mood_override(self):
        from core.schemas.persona_state import PersonaState
        state = PersonaState.default_baseline("s1")
        delta = {"_mood_override": "focused"}
        self.engine.apply_delta(state, delta)
        assert state.mood == "focused"

    def test_apply_delta_updates_updated_at(self):
        from core.schemas.persona_state import PersonaState
        from datetime import datetime, timezone
        state = PersonaState.default_baseline("s1")
        old_ts = state.updated_at
        delta = {"energy": 0.1}
        self.engine.apply_delta(state, delta)
        assert state.updated_at >= old_ts


# ---------------------------------------------------------------------------
# StateStore tests
# ---------------------------------------------------------------------------

class TestStateStore:
    def setup_method(self):
        from core.persona.state_store import StateStore
        self.store = StateStore()

    def test_get_state_creates_baseline_on_first_access(self):
        state = self.store.get_state("new_session_xyz")
        assert state is not None
        assert state.session_id == "new_session_xyz"
        assert state.mood == "calm"

    def test_get_state_same_object_on_second_access(self):
        s1 = self.store.get_state("sess_a")
        s2 = self.store.get_state("sess_a")
        assert s1 is s2

    def test_empty_session_id_falls_back_to_global(self):
        state = self.store.get_state("")
        assert state.session_id == "__global__"

    def test_update_state_returns_state_and_delta(self):
        state, delta = self.store.update_state(
            "sess_upd", message="谢谢", task_success=True
        )
        assert state is not None
        assert isinstance(delta, dict)
        assert state.trust_level > 0.5  # gratitude + task_success should push it up

    def test_update_state_no_crash_on_empty_message(self):
        state, delta = self.store.update_state("sess_empty", message="")
        assert state is not None

    def test_reset_state_returns_baseline(self):
        self.store.update_state("sess_reset", message="紧急！")
        self.store.reset_state("sess_reset")
        state2 = self.store.get_state("sess_reset")
        assert state2.mood == "calm"

    def test_different_sessions_are_independent(self):
        self.store.update_state("sess_1a", message="谢谢", task_success=True)
        self.store.update_state("sess_2a", message="崩溃了", task_success=False)
        s1 = self.store.get_state("sess_1a")
        s2 = self.store.get_state("sess_2a")
        # trust/energy for s1 should generally be higher than s2's urgency-driven state
        assert s1 is not s2

    def test_update_state_emits_no_exception_when_event_bus_publish_fails(self):
        """StateStore must not raise even if EventBus.publish raises."""
        with patch("integration.event_bus.EventBus.publish", side_effect=RuntimeError("bus down")):
            state, delta = self.store.update_state("sess_bus_err", message="hello")
        assert state is not None


# ---------------------------------------------------------------------------
# PersonaRules helpers
# ---------------------------------------------------------------------------

class TestPersonaRules:
    def test_derive_mood_concerned_when_urgency_high(self):
        from core.persona.persona_rules import derive_mood
        assert derive_mood(urgency=0.8, focus=0.5, energy=0.5, trust_level=0.5) == "concerned"

    def test_derive_mood_focused_when_focus_high(self):
        from core.persona.persona_rules import derive_mood
        assert derive_mood(urgency=0.1, focus=0.9, energy=0.5, trust_level=0.5) == "focused"

    def test_derive_mood_tired_when_energy_low(self):
        from core.persona.persona_rules import derive_mood
        assert derive_mood(urgency=0.1, focus=0.5, energy=0.2, trust_level=0.5) == "tired"

    def test_derive_mood_warm_when_trust_high(self):
        from core.persona.persona_rules import derive_mood
        assert derive_mood(urgency=0.1, focus=0.5, energy=0.5, trust_level=0.9) == "warm"

    def test_derive_mood_calm_default(self):
        from core.persona.persona_rules import derive_mood
        assert derive_mood(urgency=0.1, focus=0.5, energy=0.5, trust_level=0.5) == "calm"


# ---------------------------------------------------------------------------
# OpenClawd.process() integration — persona_state included, text-only stable
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_includes_persona_state():
    """OpenClawd.process() must include persona_state in response dict."""
    from core.openclawd import OpenClawd
    oc = OpenClawd()

    with patch.object(oc, "_get_kernel", return_value=None):
        with patch.object(oc, "sync_device_capabilities", return_value=0):
            with patch.object(oc, "_parse_intent", new_callable=AsyncMock) as mock_parse:
                mock_parse.return_value = None
                with patch.object(oc, "_dispatch_chat", new_callable=AsyncMock) as mock_chat:
                    mock_chat.return_value = {
                        "success": True,
                        "response": "好的",
                        "intent": "chat",
                    }
                    result = await oc.process("你好", session_id="test_persona_sess")

    assert "persona_state" in result, "persona_state must be present in response"
    ps = result["persona_state"]
    assert ps is not None
    assert "mood" in ps
    assert "trust_level" in ps
    assert "energy" in ps


@pytest.mark.asyncio
async def test_process_text_only_response_unchanged():
    """text-only callers: result['response'] must equal the handler's reply."""
    from core.openclawd import OpenClawd
    oc = OpenClawd()
    expected_reply = "这是回复内容"

    with patch.object(oc, "_get_kernel", return_value=None):
        with patch.object(oc, "sync_device_capabilities", return_value=0):
            with patch.object(oc, "_parse_intent", new_callable=AsyncMock) as mock_parse:
                mock_parse.return_value = None
                with patch.object(oc, "_dispatch_chat", new_callable=AsyncMock) as mock_chat:
                    mock_chat.return_value = {
                        "success": True,
                        "response": expected_reply,
                        "intent": "chat",
                    }
                    result = await oc.process("测试消息", session_id="text_only_test")

    assert result["response"] == expected_reply, "response field must be unchanged"
    assert result["success"] is True


@pytest.mark.asyncio
async def test_process_persona_state_stable_across_calls():
    """Consecutive calls on same session must not degrade the state to error."""
    from core.openclawd import OpenClawd
    oc = OpenClawd()

    for i in range(3):
        with patch.object(oc, "_get_kernel", return_value=None):
            with patch.object(oc, "sync_device_capabilities", return_value=0):
                with patch.object(oc, "_parse_intent", new_callable=AsyncMock) as mock_parse:
                    mock_parse.return_value = None
                    with patch.object(oc, "_dispatch_chat", new_callable=AsyncMock) as mock_chat:
                        mock_chat.return_value = {"success": True, "response": f"reply {i}"}
                        result = await oc.process("消息", session_id="stability_sess")

        ps = result.get("persona_state", {})
        if ps:
            assert 0.0 <= ps["energy"] <= 1.0
            assert 0.0 <= ps["trust_level"] <= 1.0
            assert 0.0 <= ps["urgency"] <= 1.0
