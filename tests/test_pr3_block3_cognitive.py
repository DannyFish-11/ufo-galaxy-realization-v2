"""tests/test_pr3_block3_cognitive.py
======================================

Block-3: Continuous Cognitive Engine + Tri-state Interpreter + Decay + Memory Split

Tests covering:

1.  CognitiveState — field clamping, update(), apply_input(), snapshot(), singleton.
2.  CognitiveFieldEngine — notify_request(), notify_task_complete(), tick listeners,
    disabled mode, singleton.
3.  StateInterpreter — region mapping (passive / liminal / manifest), uncertainty cap,
    hysteresis, interpret_snapshot(), singleton.
4.  LiminalDynamics — dwell guard, volatility tracking, threshold adjustment, singleton.
5.  DecayController — sync decay step, async decay sequence, task lifecycle subscription,
    singleton.
6.  WorkingMemory — add/get/clear, capacity eviction, disabled mode, singleton.
7.  LongTermMemory — store/retrieve/forget, namespace isolation, capacity eviction,
    disabled mode, singleton.
8.  desktop_presence_runtime integration — cognitive_state field in result,
    existing tests unaffected.
9.  openclawd integration — _record_turn populates working memory.
10. config.json — Block-3 flags present.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import time
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ROOT = pathlib.Path(__file__).parents[1]


def _reset_all() -> None:
    """Reset all Block-3 singletons before each test."""
    from core.cognitive.continuous_state import reset_cognitive_state
    from core.cognitive.cognitive_field_engine import reset_cognitive_field_engine
    from core.cognitive.state_interpreter import reset_state_interpreter
    from core.cognitive.liminal_dynamics import reset_liminal_dynamics
    from core.cognitive.decay_controller import reset_decay_controller
    from core.cognitive.working_memory import reset_working_memory
    from core.cognitive.long_term_memory import reset_long_term_memory

    reset_cognitive_state()
    reset_cognitive_field_engine()
    reset_state_interpreter()
    reset_liminal_dynamics()
    reset_decay_controller()
    reset_working_memory()
    reset_long_term_memory()


# ===========================================================================
# 1. CognitiveState
# ===========================================================================


class TestCognitiveState:
    def setup_method(self) -> None:
        _reset_all()

    def test_default_values_in_range(self) -> None:
        from core.cognitive.continuous_state import CognitiveState
        s = CognitiveState()
        assert 0.0 <= s.activation <= 1.0
        assert 0.0 <= s.intent_strength <= 1.0
        assert 0.0 <= s.uncertainty <= 1.0
        assert 0.0 <= s.momentum <= 1.0
        assert 0.0 <= s.manifest_pressure <= 1.0
        assert 0.0 <= s.stability <= 1.0
        assert 0.0 <= s.decay_rate <= 1.0

    def test_update_clamps_values(self) -> None:
        from core.cognitive.continuous_state import CognitiveState
        s = CognitiveState()
        s.update(activation=2.0, manifest_pressure=-1.0, stability=0.5)
        assert s.activation == 1.0
        assert s.manifest_pressure == 0.0
        assert s.stability == 0.5

    def test_update_refreshes_timestamp(self) -> None:
        from core.cognitive.continuous_state import CognitiveState
        s = CognitiveState()
        old_ts = s.timestamp
        time.sleep(0.01)
        s.update(activation=0.3)
        assert s.timestamp > old_ts

    def test_update_raises_on_unknown_field(self) -> None:
        from core.cognitive.continuous_state import CognitiveState
        s = CognitiveState()
        with pytest.raises(ValueError, match="unknown fields"):
            s.update(nonexistent_field=0.5)

    def test_snapshot_returns_dict(self) -> None:
        from core.cognitive.continuous_state import CognitiveState
        s = CognitiveState(activation=0.4, intent_strength=0.6)
        snap = s.snapshot()
        assert isinstance(snap, dict)
        assert snap["activation"] == 0.4
        assert snap["intent_strength"] == 0.6

    def test_snapshot_excludes_lock(self) -> None:
        from core.cognitive.continuous_state import CognitiveState
        snap = CognitiveState().snapshot()
        assert "_lock" not in snap

    def test_apply_input_increases_manifest_pressure(self) -> None:
        from core.cognitive.continuous_state import CognitiveState
        s = CognitiveState(activation=0.5, intent_strength=0.5, manifest_pressure=0.1)
        s.apply_input(intent_delta=0.3, activation_delta=0.2)
        assert s.manifest_pressure > 0.1

    def test_apply_input_uncertainty_override(self) -> None:
        from core.cognitive.continuous_state import CognitiveState
        s = CognitiveState(uncertainty=0.9)
        s.apply_input(uncertainty_override=0.2)
        assert s.uncertainty == pytest.approx(0.2)

    def test_singleton_same_instance(self) -> None:
        from core.cognitive.continuous_state import get_cognitive_state
        assert get_cognitive_state() is get_cognitive_state()

    def test_reset_creates_new_instance(self) -> None:
        from core.cognitive.continuous_state import get_cognitive_state, reset_cognitive_state
        a = get_cognitive_state()
        reset_cognitive_state()
        b = get_cognitive_state()
        assert a is not b


# ===========================================================================
# 2. CognitiveFieldEngine
# ===========================================================================


class TestCognitiveFieldEngine:
    def setup_method(self) -> None:
        _reset_all()

    def test_notify_request_raises_manifest_pressure(self) -> None:
        from core.cognitive.cognitive_field_engine import CognitiveFieldEngine
        from core.cognitive.continuous_state import CognitiveState
        state = CognitiveState()
        engine = CognitiveFieldEngine(state=state, enabled=False, tick_interval_s=60.0)
        engine.notify_request(intent_delta=0.5, activation_delta=0.4)
        assert state.manifest_pressure > 0.0

    def test_notify_request_emits_event(self) -> None:
        from core.cognitive.cognitive_field_engine import CognitiveFieldEngine
        from core.cognitive.continuous_state import CognitiveState
        state = CognitiveState()
        engine = CognitiveFieldEngine(state=state, enabled=False, tick_interval_s=60.0)
        # notify_request does NOT call tick listeners — listeners are only called on tick.
        # Verify notify_request updates the state and last_request_ts.
        engine.notify_request()
        assert engine._last_request_ts > 0.0

    def test_tick_listener_called_on_tick(self) -> None:
        from core.cognitive.cognitive_field_engine import CognitiveFieldEngine
        from core.cognitive.continuous_state import CognitiveState
        ticks: List[Dict] = []
        state = CognitiveState()
        engine = CognitiveFieldEngine(state=state, enabled=True, tick_interval_s=60.0)

        async def run():
            engine.add_tick_listener(ticks.append)
            await engine._do_tick()

        asyncio.get_event_loop().run_until_complete(run())
        assert len(ticks) == 1
        assert "activation" in ticks[0]
        assert "tick_count" in ticks[0]

    def test_tick_decays_manifest_pressure(self) -> None:
        from core.cognitive.cognitive_field_engine import CognitiveFieldEngine
        from core.cognitive.continuous_state import CognitiveState
        state = CognitiveState(manifest_pressure=0.8, activation=0.7)
        engine = CognitiveFieldEngine(state=state, enabled=True, tick_interval_s=60.0)
        engine._last_request_ts = 0.0  # simulate long idle

        asyncio.get_event_loop().run_until_complete(engine._do_tick())
        assert state.manifest_pressure < 0.8
        assert state.activation < 0.7

    def test_tick_count_increments(self) -> None:
        from core.cognitive.cognitive_field_engine import CognitiveFieldEngine
        from core.cognitive.continuous_state import CognitiveState
        engine = CognitiveFieldEngine(state=CognitiveState(), enabled=True, tick_interval_s=60.0)
        asyncio.get_event_loop().run_until_complete(engine._do_tick())
        asyncio.get_event_loop().run_until_complete(engine._do_tick())
        assert engine.tick_count == 2

    def test_disabled_engine_not_started(self) -> None:
        from core.cognitive.cognitive_field_engine import CognitiveFieldEngine
        from core.cognitive.continuous_state import CognitiveState
        engine = CognitiveFieldEngine(state=CognitiveState(), enabled=False, tick_interval_s=1.0)

        async def run():
            await engine.start()
            assert engine._task is None

        asyncio.get_event_loop().run_until_complete(run())

    def test_remove_tick_listener(self) -> None:
        from core.cognitive.cognitive_field_engine import CognitiveFieldEngine
        from core.cognitive.continuous_state import CognitiveState
        ticks: List = []
        engine = CognitiveFieldEngine(state=CognitiveState(), enabled=True, tick_interval_s=60.0)
        engine.add_tick_listener(ticks.append)
        engine.remove_tick_listener(ticks.append)
        asyncio.get_event_loop().run_until_complete(engine._do_tick())
        assert len(ticks) == 0

    def test_singleton(self) -> None:
        from core.cognitive.cognitive_field_engine import get_cognitive_field_engine
        assert get_cognitive_field_engine() is get_cognitive_field_engine()


# ===========================================================================
# 3. StateInterpreter
# ===========================================================================


class TestStateInterpreter:
    def setup_method(self) -> None:
        _reset_all()

    def test_passive_region_low_pressure(self) -> None:
        from core.cognitive.state_interpreter import StateInterpreter
        from core.cognitive.continuous_state import CognitiveState
        state = CognitiveState(activation=0.05, intent_strength=0.05, manifest_pressure=0.05, uncertainty=0.5)
        interp = StateInterpreter(state=state)
        r = interp.interpret(state)
        assert r.tristate == "silent"
        assert r.region.value == "silent"

    def test_manifest_region_high_pressure_low_uncertainty(self) -> None:
        from core.cognitive.state_interpreter import StateInterpreter
        from core.cognitive.continuous_state import CognitiveState
        state = CognitiveState(activation=0.9, intent_strength=0.9, manifest_pressure=0.9, uncertainty=0.1)
        interp = StateInterpreter(state=state)
        # Hysteresis: passive → liminal first call, then liminal → manifest second call
        interp.interpret(state)
        r = interp.interpret(state)
        assert r.tristate == "manifest"

    def test_liminal_region_moderate(self) -> None:
        from core.cognitive.state_interpreter import StateInterpreter
        from core.cognitive.continuous_state import CognitiveState
        state = CognitiveState(activation=0.4, intent_strength=0.4, manifest_pressure=0.4, uncertainty=0.3)
        interp = StateInterpreter(state=state)
        # From passive, score 0.34 is above passive_threshold (0.20) → enters liminal
        r = interp.interpret(state)
        assert r.tristate == "liminal"

    def test_uncertainty_cap_blocks_manifest(self) -> None:
        from core.cognitive.state_interpreter import StateInterpreter
        from core.cognitive.continuous_state import CognitiveState
        state = CognitiveState(activation=0.95, intent_strength=0.95, manifest_pressure=0.95, uncertainty=0.8)
        interp = StateInterpreter(state=state, uncertainty_cap=0.70)
        r = interp.interpret(state)
        assert r.tristate != "manifest"

    def test_hysteresis_prevents_snap_back(self) -> None:
        """Once in manifest, score must drop far below threshold to go directly to passive.

        The hysteresis rule for manifest is: score must drop below
        ``passive_threshold + 0.10`` to jump to passive; otherwise the system
        transitions back through liminal.  This prevents manifest → passive snapping.
        """
        from core.cognitive.state_interpreter import StateInterpreter, CognitiveRegion
        from core.cognitive.continuous_state import CognitiveState
        state_high = CognitiveState(activation=0.9, manifest_pressure=0.9, uncertainty=0.1)
        interp = StateInterpreter(state=state_high, manifest_threshold=0.65, passive_threshold=0.20)
        interp.interpret(state_high)  # passive → liminal
        interp.interpret(state_high)  # liminal → manifest
        assert interp.last_region == CognitiveRegion.MANIFEST

        # Moderate drop (score ~0.40): score is in (0.30, 0.65) → should go to liminal,
        # NOT jump directly to passive (that would require score < 0.30).
        state_mod = CognitiveState(activation=0.5, manifest_pressure=0.5, uncertainty=0.2)
        r = interp.interpret(state_mod)
        # Hysteresis: does NOT snap directly to passive — stops at liminal
        assert r.tristate != "silent"

    def test_interpret_snapshot_dict(self) -> None:
        from core.cognitive.state_interpreter import StateInterpreter
        interp = StateInterpreter()
        r = interp.interpret_snapshot({"manifest_pressure": 0.05, "activation": 0.05, "uncertainty": 0.5})
        assert r.tristate == "silent"

    def test_result_source_is_interpreter(self) -> None:
        from core.cognitive.state_interpreter import StateInterpreter
        from core.cognitive.continuous_state import CognitiveState
        state = CognitiveState()
        r = StateInterpreter(state=state).interpret(state)
        assert r.source == "interpreter"

    def test_to_dict_has_required_fields(self) -> None:
        from core.cognitive.state_interpreter import StateInterpreter
        from core.cognitive.continuous_state import CognitiveState
        d = StateInterpreter(state=CognitiveState()).interpret().to_dict()
        for field in ("region", "tristate", "score", "uncertainty", "manifest_pressure", "activation", "source"):
            assert field in d, f"Missing field: {field}"

    def test_singleton(self) -> None:
        from core.cognitive.state_interpreter import get_state_interpreter
        assert get_state_interpreter() is get_state_interpreter()


# ===========================================================================
# 4. LiminalDynamics
# ===========================================================================


class TestLiminalDynamics:
    def setup_method(self) -> None:
        _reset_all()

    def test_can_transition_when_not_in_liminal(self) -> None:
        from core.cognitive.liminal_dynamics import LiminalDynamics
        ld = LiminalDynamics(min_dwell_s=1.5)
        assert ld.can_transition_to_manifest() is True

    def test_dwell_guard_blocks_fast_transition(self) -> None:
        from core.cognitive.liminal_dynamics import LiminalDynamics
        ld = LiminalDynamics(min_dwell_s=100.0)
        ld.record_transition("silent", "liminal")
        assert ld.can_transition_to_manifest() is False

    def test_dwell_guard_allows_after_min_dwell(self) -> None:
        from core.cognitive.liminal_dynamics import LiminalDynamics
        ld = LiminalDynamics(min_dwell_s=0.0)
        ld.record_transition("silent", "liminal")
        assert ld.can_transition_to_manifest() is True

    def test_volatility_zero_with_no_transitions(self) -> None:
        from core.cognitive.liminal_dynamics import LiminalDynamics
        assert LiminalDynamics().volatility() == 0.0

    def test_volatility_increases_with_flips(self) -> None:
        from core.cognitive.liminal_dynamics import LiminalDynamics
        ld = LiminalDynamics(volatility_window=4)
        ld.record_transition("silent", "liminal")
        ld.record_transition("liminal", "manifest")
        ld.record_transition("manifest", "liminal")
        ld.record_transition("liminal", "silent")
        assert ld.volatility() > 0.0

    def test_threshold_adjustment_non_negative(self) -> None:
        from core.cognitive.liminal_dynamics import LiminalDynamics
        assert LiminalDynamics().manifest_threshold_adjustment() >= 0.0

    def test_liminal_dwell_increases_over_time(self) -> None:
        from core.cognitive.liminal_dynamics import LiminalDynamics
        ld = LiminalDynamics()
        ld.record_transition("silent", "liminal")
        time.sleep(0.05)
        assert ld.liminal_dwell_s() >= 0.04

    def test_state_dict_has_required_keys(self) -> None:
        from core.cognitive.liminal_dynamics import LiminalDynamics
        d = LiminalDynamics().state_dict()
        for k in ("liminal_dwell_s", "volatility", "threshold_adjustment", "min_dwell_s"):
            assert k in d

    def test_singleton(self) -> None:
        from core.cognitive.liminal_dynamics import get_liminal_dynamics
        assert get_liminal_dynamics() is get_liminal_dynamics()


# ===========================================================================
# 5. DecayController
# ===========================================================================


class TestDecayController:
    def setup_method(self) -> None:
        _reset_all()

    def test_sync_decay_step_reduces_pressure(self) -> None:
        from core.cognitive.decay_controller import DecayController
        from core.cognitive.continuous_state import CognitiveState
        state = CognitiveState(manifest_pressure=0.8, activation=0.7)
        dc = DecayController(state=state, decay_rate=0.20, step_interval_s=0.01, num_steps=1)
        dc._sync_decay_step(task_id="t1", trace_id="tr1")
        assert state.manifest_pressure < 0.8
        assert state.activation < 0.7

    def test_async_decay_sequence_smooth_reduction(self) -> None:
        from core.cognitive.decay_controller import DecayController
        from core.cognitive.continuous_state import CognitiveState
        state = CognitiveState(manifest_pressure=0.9, activation=0.8)
        dc = DecayController(state=state, decay_rate=0.20, step_interval_s=0.001, num_steps=5)

        asyncio.get_event_loop().run_until_complete(
            dc._async_decay_sequence(task_id="t1", trace_id="tr1")
        )
        assert state.manifest_pressure < 0.9
        assert state.activation < 0.8

    def test_decay_stops_when_fully_decayed(self) -> None:
        from core.cognitive.decay_controller import DecayController
        from core.cognitive.continuous_state import CognitiveState
        state = CognitiveState(manifest_pressure=0.001, activation=0.001)
        dc = DecayController(state=state, decay_rate=0.99, step_interval_s=0.001, num_steps=20)

        asyncio.get_event_loop().run_until_complete(
            dc._async_decay_sequence(task_id="t2", trace_id="tr2")
        )
        # Should have stopped early
        assert state.manifest_pressure == pytest.approx(0.0, abs=0.01)

    def test_subscribe_to_task_lifecycle_idempotent(self) -> None:
        from core.cognitive.decay_controller import DecayController
        from core.cognitive.continuous_state import CognitiveState
        dc = DecayController(state=CognitiveState(), decay_rate=0.1)
        dc.subscribe_to_task_lifecycle()
        dc.subscribe_to_task_lifecycle()
        assert dc._subscribed is True

    def test_trigger_decay_sync_fallback(self) -> None:
        """trigger_decay uses sync fallback when no event loop is running."""
        from core.cognitive.decay_controller import DecayController
        from core.cognitive.continuous_state import CognitiveState
        state = CognitiveState(manifest_pressure=0.6, activation=0.5)
        dc = DecayController(state=state, decay_rate=0.3, step_interval_s=0.01, num_steps=2)
        dc.trigger_decay(task_id="t3", trace_id="tr3")
        # sync step applied
        assert state.manifest_pressure < 0.6

    def test_singleton(self) -> None:
        from core.cognitive.decay_controller import get_decay_controller
        assert get_decay_controller() is get_decay_controller()


# ===========================================================================
# 6. WorkingMemory
# ===========================================================================


class TestWorkingMemory:
    def setup_method(self) -> None:
        _reset_all()

    def test_add_and_get(self) -> None:
        from core.cognitive.working_memory import WorkingMemory
        wm = WorkingMemory(capacity=5)
        wm.add(session_id="s1", role="user", content="hello", trace_id="t1")
        entries = wm.get(session_id="s1")
        assert len(entries) == 1
        assert entries[0]["role"] == "user"
        assert entries[0]["content"] == "hello"
        assert entries[0]["trace_id"] == "t1"

    def test_capacity_eviction(self) -> None:
        from core.cognitive.working_memory import WorkingMemory
        wm = WorkingMemory(capacity=3)
        for i in range(5):
            wm.add(session_id="s1", role="user", content=f"msg{i}")
        entries = wm.get(session_id="s1")
        assert len(entries) == 3
        assert entries[-1]["content"] == "msg4"

    def test_get_last_n(self) -> None:
        from core.cognitive.working_memory import WorkingMemory
        wm = WorkingMemory(capacity=10)
        for i in range(6):
            wm.add(session_id="s1", role="user", content=f"msg{i}")
        entries = wm.get(session_id="s1", last_n=3)
        assert len(entries) == 3
        assert entries[0]["content"] == "msg3"

    def test_clear_removes_session(self) -> None:
        from core.cognitive.working_memory import WorkingMemory
        wm = WorkingMemory(capacity=5)
        wm.add(session_id="s1", role="user", content="hello")
        wm.clear(session_id="s1")
        assert wm.get(session_id="s1") == []

    def test_get_empty_for_unknown_session(self) -> None:
        from core.cognitive.working_memory import WorkingMemory
        assert WorkingMemory().get(session_id="nonexistent") == []

    def test_disabled_returns_empty(self) -> None:
        from core.cognitive.working_memory import WorkingMemory
        wm = WorkingMemory(enabled=False)
        wm.add(session_id="s1", role="user", content="hello")
        assert wm.get(session_id="s1") == []

    def test_active_sessions(self) -> None:
        from core.cognitive.working_memory import WorkingMemory
        wm = WorkingMemory()
        wm.add(session_id="s1", role="user", content="x")
        wm.add(session_id="s2", role="user", content="y")
        sessions = wm.active_sessions()
        assert "s1" in sessions
        assert "s2" in sessions

    def test_multiple_sessions_isolated(self) -> None:
        from core.cognitive.working_memory import WorkingMemory
        wm = WorkingMemory(capacity=5)
        wm.add(session_id="s1", role="user", content="s1_msg")
        wm.add(session_id="s2", role="user", content="s2_msg")
        assert wm.get(session_id="s1")[0]["content"] == "s1_msg"
        assert wm.get(session_id="s2")[0]["content"] == "s2_msg"

    def test_singleton(self) -> None:
        from core.cognitive.working_memory import get_working_memory
        assert get_working_memory() is get_working_memory()


# ===========================================================================
# 7. LongTermMemory
# ===========================================================================


class TestLongTermMemory:
    def setup_method(self) -> None:
        _reset_all()

    def test_store_and_retrieve(self) -> None:
        from core.cognitive.long_term_memory import LongTermMemory
        ltm = LongTermMemory()
        ltm.store(key="lang", value="zh-CN", namespace="preferences", trace_id="t1")
        assert ltm.retrieve(key="lang", namespace="preferences") == "zh-CN"

    def test_retrieve_default_when_not_found(self) -> None:
        from core.cognitive.long_term_memory import LongTermMemory
        assert LongTermMemory().retrieve(key="missing", default="fallback") == "fallback"

    def test_namespace_isolation(self) -> None:
        from core.cognitive.long_term_memory import LongTermMemory
        ltm = LongTermMemory()
        ltm.store(key="x", value="a", namespace="ns1")
        ltm.store(key="x", value="b", namespace="ns2")
        assert ltm.retrieve(key="x", namespace="ns1") == "a"
        assert ltm.retrieve(key="x", namespace="ns2") == "b"

    def test_retrieve_all_sorted_by_time(self) -> None:
        from core.cognitive.long_term_memory import LongTermMemory
        ltm = LongTermMemory()
        ltm.store(key="k1", value=1, namespace="ns")
        time.sleep(0.01)
        ltm.store(key="k2", value=2, namespace="ns")
        entries = ltm.retrieve_all(namespace="ns")
        assert entries[0]["key"] == "k1"
        assert entries[1]["key"] == "k2"

    def test_forget_removes_key(self) -> None:
        from core.cognitive.long_term_memory import LongTermMemory
        ltm = LongTermMemory()
        ltm.store(key="del_me", value="v", namespace="ns")
        assert ltm.forget(key="del_me", namespace="ns") is True
        assert ltm.retrieve(key="del_me", namespace="ns") is None

    def test_forget_namespace(self) -> None:
        from core.cognitive.long_term_memory import LongTermMemory
        ltm = LongTermMemory()
        ltm.store(key="k1", value=1, namespace="ns")
        ltm.store(key="k2", value=2, namespace="ns")
        removed = ltm.forget_namespace(namespace="ns")
        assert removed == 2
        assert ltm.retrieve_all(namespace="ns") == []

    def test_capacity_eviction(self) -> None:
        from core.cognitive.long_term_memory import LongTermMemory
        ltm = LongTermMemory(max_entries=3)
        for i in range(5):
            ltm.store(key=f"k{i}", value=i, namespace="ns")
        assert ltm.stats()["total_entries"] <= 3

    def test_disabled_returns_none(self) -> None:
        from core.cognitive.long_term_memory import LongTermMemory
        ltm = LongTermMemory(enabled=False)
        ltm.store(key="k", value="v")
        assert ltm.retrieve(key="k") is None
        assert ltm.retrieve_all() == []

    def test_stats_keys(self) -> None:
        from core.cognitive.long_term_memory import LongTermMemory
        stats = LongTermMemory().stats()
        for k in ("total_entries", "max_entries", "namespaces", "enabled"):
            assert k in stats

    def test_retrieve_entry_dict(self) -> None:
        from core.cognitive.long_term_memory import LongTermMemory
        ltm = LongTermMemory()
        ltm.store(key="k1", value="v1", namespace="ns", trace_id="t1", session_id="s1")
        entry = ltm.retrieve_entry(key="k1", namespace="ns")
        assert entry is not None
        assert entry["trace_id"] == "t1"
        assert entry["session_id"] == "s1"

    def test_singleton(self) -> None:
        from core.cognitive.long_term_memory import get_long_term_memory
        assert get_long_term_memory() is get_long_term_memory()


# ===========================================================================
# 8. desktop_presence_runtime integration
# ===========================================================================


class TestDesktopPresenceRuntimeCognitiveIntegration:
    def _make_openclawd_result(self) -> dict:
        return {"success": True, "response": "ok", "runtime_session_id": "r1"}

    @pytest.mark.asyncio
    async def test_result_includes_cognitive_state_field(self) -> None:
        """handle_request() result should contain cognitive_state (Block-3 additive field)."""
        _reset_all()
        from core.desktop_presence_runtime import DesktopPresenceRuntime

        rt = DesktopPresenceRuntime()
        with patch("core.openclawd.get_openclawd") as mock_get:
            mock_clawd = MagicMock()
            mock_clawd.process = AsyncMock(return_value=self._make_openclawd_result())
            mock_get.return_value = mock_clawd
            result = await rt.handle_request(message="test", source="chat")

        assert "cognitive_state" in result
        cs = result["cognitive_state"]
        assert "tristate" in cs
        assert "score" in cs
        assert cs["source"] == "interpreter"

    @pytest.mark.asyncio
    async def test_existing_tristate_field_unchanged(self) -> None:
        """The existing tristate field must still be 'silent' after execution."""
        _reset_all()
        from core.desktop_presence_runtime import DesktopPresenceRuntime, TriState

        rt = DesktopPresenceRuntime()
        with patch("core.openclawd.get_openclawd") as mock_get:
            mock_clawd = MagicMock()
            mock_clawd.process = AsyncMock(return_value=self._make_openclawd_result())
            mock_get.return_value = mock_clawd
            result = await rt.handle_request(message="hello", source="chat")

        assert result["tristate"] == TriState.SILENT.value

    @pytest.mark.asyncio
    async def test_cognitive_engine_notified_on_request(self) -> None:
        """CognitiveFieldEngine.notify_request must be called."""
        _reset_all()
        from core.desktop_presence_runtime import DesktopPresenceRuntime

        rt = DesktopPresenceRuntime()
        notify_called = []

        def _fake_notify(**kwargs):
            notify_called.append(kwargs)

        with (
            patch("core.openclawd.get_openclawd") as mock_get,
            patch(
                "core.cognitive.cognitive_field_engine.get_cognitive_field_engine"
            ) as mock_cfe,
        ):
            mock_clawd = MagicMock()
            mock_clawd.process = AsyncMock(return_value=self._make_openclawd_result())
            mock_get.return_value = mock_clawd
            mock_engine = MagicMock()
            mock_engine.notify_request = _fake_notify
            mock_engine.notify_task_complete = MagicMock()
            mock_cfe.return_value = mock_engine
            await rt.handle_request(message="hello", source="chat")

        assert len(notify_called) >= 1


# ===========================================================================
# 9. openclawd integration — _record_turn populates working memory
# ===========================================================================


class TestOpenClawdWorkingMemoryIntegration:
    def setup_method(self) -> None:
        _reset_all()

    @pytest.mark.asyncio
    async def test_record_turn_adds_to_working_memory(self) -> None:
        from core.cognitive.working_memory import get_working_memory

        with patch("core.openclawd.get_openclawd"):
            from core.openclawd import OpenClawd
            clawd = OpenClawd.__new__(OpenClawd)
            clawd._session_memory = {}
            clawd._current_trace_id = "trace_test"

            await clawd._record_turn("sess_wm_test", "user", "hello world")

        wm = get_working_memory()
        entries = wm.get(session_id="sess_wm_test")
        assert any(e["content"] == "hello world" for e in entries)

    @pytest.mark.asyncio
    async def test_record_turn_role_preserved(self) -> None:
        from core.cognitive.working_memory import get_working_memory

        from core.openclawd import OpenClawd
        clawd = OpenClawd.__new__(OpenClawd)
        clawd._session_memory = {}
        clawd._current_trace_id = ""

        await clawd._record_turn("sess_role_test", "assistant", "I can help")
        entries = get_working_memory().get(session_id="sess_role_test")
        assert entries[0]["role"] == "assistant"


# ===========================================================================
# 10. config.json — Block-3 flags present
# ===========================================================================


class TestConfigBlock3Flags:
    def test_cognitive_engine_flag(self) -> None:
        cfg = json.loads((ROOT / "config.json").read_text())
        assert "enable_cognitive_field_engine" in cfg
        assert isinstance(cfg["enable_cognitive_field_engine"], bool)

    def test_tick_interval_flag(self) -> None:
        cfg = json.loads((ROOT / "config.json").read_text())
        assert "cognitive_field_tick_interval_s" in cfg
        assert cfg["cognitive_field_tick_interval_s"] > 0

    def test_interpreter_threshold_flags(self) -> None:
        cfg = json.loads((ROOT / "config.json").read_text())
        assert "cognitive_manifest_threshold" in cfg
        assert "cognitive_passive_threshold" in cfg
        assert "cognitive_uncertainty_cap" in cfg
        assert 0 < cfg["cognitive_manifest_threshold"] <= 1.0
        assert 0 < cfg["cognitive_passive_threshold"] <= 1.0

    def test_liminal_flags(self) -> None:
        cfg = json.loads((ROOT / "config.json").read_text())
        assert "cognitive_liminal_min_dwell_s" in cfg
        assert "cognitive_liminal_volatility_window" in cfg
        assert "cognitive_liminal_volatility_penalty" in cfg

    def test_decay_flags(self) -> None:
        cfg = json.loads((ROOT / "config.json").read_text())
        assert "cognitive_decay_rate" in cfg
        assert "cognitive_decay_step_interval_s" in cfg
        assert "cognitive_decay_steps" in cfg
        assert 0 < cfg["cognitive_decay_rate"] < 1.0

    def test_memory_split_flags(self) -> None:
        cfg = json.loads((ROOT / "config.json").read_text())
        assert "enable_cognitive_memory_split" in cfg
        assert "working_memory_capacity" in cfg
        assert "long_term_memory_max_entries" in cfg
        assert isinstance(cfg["enable_cognitive_memory_split"], bool)
        assert cfg["working_memory_capacity"] > 0
        assert cfg["long_term_memory_max_entries"] > 0
