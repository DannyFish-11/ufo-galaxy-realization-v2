"""tests/test_pr8_state_event_bus.py
=====================================

PR-8 — Unified State Event Bus

Tests covering:

1. StateEvent schema — field defaults, trace/session propagation, to_dict().
2. StateEventType enum — string values follow domain.action convention.
3. StateEventBus.subscribe() / unsubscribe() — token management.
4. StateEventBus.publish() — sync dispatch to type-specific subscribers.
5. StateEventBus wildcard subscribers — receive every event type.
6. StateEventBus async subscribers — dispatched via create_task in a loop.
7. emit() helper — best-effort, never raises.
8. reset_state_event_bus() — resets singleton.
9. task_lifecycle integration — TaskLifecycleManager emits on state bus.
10. desktop_presence_runtime integration — phase transitions emit events.
11. config.json — PR-8 flags present.
12. Backward compatibility — existing integration.event_bus unaffected.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import time
import uuid
from typing import List
from unittest.mock import MagicMock, patch

import pytest

from core.state_event_bus import (
    StateEvent,
    StateEventBus,
    StateEventType,
    SubscriptionToken,
    emit,
    get_state_event_bus,
    reset_state_event_bus,
)


# ===========================================================================
# Helpers
# ===========================================================================

def _collect(bus: StateEventBus, event_type=None) -> List[StateEvent]:
    """Register a sync listener and return the shared list."""
    received: List[StateEvent] = []
    bus.subscribe(event_type, received.append)
    return received


# ===========================================================================
# 1. StateEvent schema
# ===========================================================================


class TestStateEventSchema:
    def test_unique_event_ids(self):
        e1 = StateEvent(type="task.started", source="test")
        e2 = StateEvent(type="task.started", source="test")
        assert e1.event_id != e2.event_id

    def test_timestamp_positive(self):
        e = StateEvent(type="task.started", source="test")
        assert e.timestamp > 0

    def test_trace_id_generated_when_missing(self):
        e = StateEvent(type="task.started", source="test")
        assert len(e.trace_id) == 32  # uuid4().hex

    def test_runtime_session_id_defaults_to_trace_id(self):
        e = StateEvent(type="task.started", source="test")
        assert e.runtime_session_id == e.trace_id

    def test_explicit_trace_and_session(self):
        e = StateEvent(
            type="task.started",
            source="test",
            trace_id="trace-abc",
            runtime_session_id="sess-xyz",
        )
        assert e.trace_id == "trace-abc"
        assert e.runtime_session_id == "sess-xyz"

    def test_payload_defaults_to_empty_dict(self):
        e = StateEvent(type="task.started", source="test")
        assert e.payload == {}

    def test_to_dict_keys(self):
        e = StateEvent(type="task.started", source="my_module", payload={"k": "v"})
        d = e.to_dict()
        assert set(d.keys()) == {
            "event_id", "type", "timestamp", "trace_id",
            "runtime_session_id", "source", "payload",
        }
        assert d["payload"] == {"k": "v"}
        assert d["source"] == "my_module"


# ===========================================================================
# 2. StateEventType enum
# ===========================================================================


class TestStateEventType:
    def test_phase_values(self):
        assert StateEventType.PHASE_SILENT   == "phase.silent"
        assert StateEventType.PHASE_LIMINAL  == "phase.liminal"
        assert StateEventType.PHASE_MANIFEST == "phase.manifest"

    def test_task_values(self):
        assert StateEventType.TASK_STARTED == "task.started"
        assert StateEventType.TASK_DONE    == "task.done"
        assert StateEventType.TASK_FAILED  == "task.failed"

    def test_skill_values(self):
        assert StateEventType.SKILL_INVOKED == "skill.invoked"
        assert StateEventType.SKILL_DONE    == "skill.done"
        assert StateEventType.SKILL_FAILED  == "skill.failed"

    def test_executor_values(self):
        assert StateEventType.EXECUTOR_START == "executor.start"
        assert StateEventType.EXECUTOR_DONE  == "executor.done"
        assert StateEventType.EXECUTOR_FAIL  == "executor.fail"

    def test_device_updated(self):
        assert StateEventType.DEVICE_UPDATED == "device.updated"

    def test_is_string_enum(self):
        # All values are strings so they serialise cleanly.
        for et in StateEventType:
            assert isinstance(et.value, str)
            # All domain-scoped events use dot notation; GENERIC is the fallback.
            if et != StateEventType.GENERIC:
                assert "." in et.value, f"{et!r} value should contain '.'"


# ===========================================================================
# 3. Subscribe / unsubscribe
# ===========================================================================


class TestSubscribeUnsubscribe:
    def setup_method(self):
        reset_state_event_bus()
        self.bus = StateEventBus()

    def test_subscribe_returns_token(self):
        token = self.bus.subscribe(StateEventType.TASK_STARTED, lambda e: None)
        assert isinstance(token, SubscriptionToken)
        assert token.event_type == StateEventType.TASK_STARTED.value

    def test_subscriber_count(self):
        self.bus.subscribe(StateEventType.TASK_STARTED, lambda e: None)
        self.bus.subscribe(StateEventType.TASK_STARTED, lambda e: None)
        assert self.bus.subscriber_count(StateEventType.TASK_STARTED) == 2

    def test_unsubscribe_removes_listener(self):
        received: List[StateEvent] = []
        token = self.bus.subscribe(StateEventType.TASK_STARTED, received.append)
        assert self.bus.unsubscribe(token) is True
        self.bus.publish(StateEventType.TASK_STARTED, source="test")
        assert received == []

    def test_unsubscribe_unknown_token_returns_false(self):
        fake = SubscriptionToken(event_type="task.started", callback=lambda e: None)
        assert self.bus.unsubscribe(fake) is False

    def test_clear_removes_all(self):
        self.bus.subscribe(StateEventType.TASK_STARTED, lambda e: None)
        self.bus.subscribe(StateEventType.TASK_DONE, lambda e: None)
        self.bus.clear()
        assert self.bus.subscriber_count() == 0

    def test_wildcard_subscribe_none(self):
        received: List[StateEvent] = []
        self.bus.subscribe(None, received.append)
        self.bus.publish(StateEventType.TASK_STARTED, source="s")
        self.bus.publish(StateEventType.PHASE_LIMINAL, source="s")
        assert len(received) == 2


# ===========================================================================
# 4. Publish — sync dispatch
# ===========================================================================


class TestPublishSync:
    def setup_method(self):
        self.bus = StateEventBus()

    def test_event_delivered_to_matching_subscriber(self):
        received: List[StateEvent] = []
        self.bus.subscribe(StateEventType.TASK_STARTED, received.append)
        evt = self.bus.publish(StateEventType.TASK_STARTED, source="mod", payload={"x": 1})
        assert len(received) == 1
        assert received[0] is evt
        assert received[0].payload == {"x": 1}

    def test_non_matching_subscriber_not_called(self):
        received: List[StateEvent] = []
        self.bus.subscribe(StateEventType.TASK_DONE, received.append)
        self.bus.publish(StateEventType.TASK_STARTED, source="mod")
        assert received == []

    def test_trace_id_propagated(self):
        received: List[StateEvent] = []
        self.bus.subscribe(StateEventType.TASK_STARTED, received.append)
        self.bus.publish(StateEventType.TASK_STARTED, source="m", trace_id="tid-1")
        assert received[0].trace_id == "tid-1"

    def test_runtime_session_id_propagated(self):
        received: List[StateEvent] = []
        self.bus.subscribe(StateEventType.TASK_STARTED, received.append)
        self.bus.publish(
            StateEventType.TASK_STARTED,
            source="m",
            trace_id="t",
            runtime_session_id="rs-42",
        )
        assert received[0].runtime_session_id == "rs-42"

    def test_publish_sync_alias(self):
        """publish_sync is an alias for publish."""
        received: List[StateEvent] = []
        self.bus.subscribe(StateEventType.TASK_DONE, received.append)
        self.bus.publish_sync(StateEventType.TASK_DONE, source="x")
        assert len(received) == 1

    def test_pre_built_event_accepted(self):
        received: List[StateEvent] = []
        self.bus.subscribe(StateEventType.PHASE_LIMINAL, received.append)
        pre = StateEvent(
            type=StateEventType.PHASE_LIMINAL.value,
            source="runtime",
            trace_id="t123",
        )
        self.bus.publish(StateEventType.PHASE_LIMINAL, source="", event=pre)
        assert received[0] is pre

    def test_multiple_subscribers_all_receive(self):
        r1: List[StateEvent] = []
        r2: List[StateEvent] = []
        self.bus.subscribe(StateEventType.SKILL_INVOKED, r1.append)
        self.bus.subscribe(StateEventType.SKILL_INVOKED, r2.append)
        self.bus.publish(StateEventType.SKILL_INVOKED, source="s")
        assert len(r1) == len(r2) == 1

    def test_faulty_subscriber_does_not_break_others(self):
        r: List[StateEvent] = []
        self.bus.subscribe(StateEventType.TASK_STARTED, lambda e: (_ for _ in ()).throw(RuntimeError("boom")))
        self.bus.subscribe(StateEventType.TASK_STARTED, r.append)
        # Should not raise; second subscriber still receives the event.
        self.bus.publish(StateEventType.TASK_STARTED, source="s")
        assert len(r) == 1


# ===========================================================================
# 5. Wildcard subscribers
# ===========================================================================


class TestWildcardSubscribers:
    def setup_method(self):
        self.bus = StateEventBus()

    def test_wildcard_receives_all_types(self):
        received: List[StateEvent] = []
        self.bus.subscribe(None, received.append)
        for et in [
            StateEventType.TASK_STARTED,
            StateEventType.TASK_DONE,
            StateEventType.PHASE_LIMINAL,
            StateEventType.SKILL_INVOKED,
        ]:
            self.bus.publish(et, source="s")
        assert len(received) == 4

    def test_wildcard_and_type_both_receive(self):
        wildcard: List[StateEvent] = []
        typed: List[StateEvent] = []
        self.bus.subscribe(None, wildcard.append)
        self.bus.subscribe(StateEventType.TASK_STARTED, typed.append)
        self.bus.publish(StateEventType.TASK_STARTED, source="s")
        assert len(wildcard) == 1
        assert len(typed) == 1
        assert wildcard[0] is typed[0]


# ===========================================================================
# 6. Async subscribers
# ===========================================================================


class TestAsyncSubscribers:
    def setup_method(self):
        self.bus = StateEventBus()

    @pytest.mark.asyncio
    async def test_async_subscriber_called(self):
        received: List[StateEvent] = []

        async def async_handler(event: StateEvent) -> None:
            received.append(event)

        self.bus.subscribe(StateEventType.TASK_STARTED, async_handler)
        self.bus.publish(StateEventType.TASK_STARTED, source="s")
        # Let the event loop run scheduled tasks.
        await asyncio.sleep(0)
        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_async_wildcard_subscriber(self):
        received: List[StateEvent] = []

        async def handler(e: StateEvent) -> None:
            received.append(e)

        self.bus.subscribe(None, handler)
        self.bus.publish(StateEventType.PHASE_MANIFEST, source="runtime")
        await asyncio.sleep(0)
        assert len(received) == 1


# ===========================================================================
# 7. emit() helper
# ===========================================================================


class TestEmitHelper:
    def setup_method(self):
        reset_state_event_bus()

    def teardown_method(self):
        reset_state_event_bus()

    def test_emit_delivers_event(self):
        bus = get_state_event_bus()
        received: List[StateEvent] = []
        bus.subscribe(StateEventType.DEVICE_UPDATED, received.append)
        emit(StateEventType.DEVICE_UPDATED, "test", {"device_id": "dev-1"})
        assert len(received) == 1
        assert received[0].payload["device_id"] == "dev-1"

    def test_emit_never_raises_on_bad_type(self):
        # Should not raise even with a non-existent event type string.
        emit("totally.unknown.type", "test")

    def test_emit_propagates_trace_id(self):
        bus = get_state_event_bus()
        received: List[StateEvent] = []
        bus.subscribe(StateEventType.TASK_STARTED, received.append)
        emit(StateEventType.TASK_STARTED, "s", trace_id="trace-999")
        assert received[0].trace_id == "trace-999"


# ===========================================================================
# 8. Singleton reset
# ===========================================================================


class TestSingletonReset:
    def teardown_method(self):
        reset_state_event_bus()

    def test_singleton_returns_same_instance(self):
        b1 = get_state_event_bus()
        b2 = get_state_event_bus()
        assert b1 is b2

    def test_reset_creates_fresh_instance(self):
        b1 = get_state_event_bus()
        reset_state_event_bus()
        b2 = get_state_event_bus()
        assert b1 is not b2

    def test_reset_clears_subscriptions(self):
        bus = get_state_event_bus()
        bus.subscribe(StateEventType.TASK_STARTED, lambda e: None)
        reset_state_event_bus()
        new_bus = get_state_event_bus()
        assert new_bus.subscriber_count() == 0


# ===========================================================================
# 9. TaskLifecycleManager integration
# ===========================================================================


class TestTaskLifecycleIntegration:
    """Verify that TaskLifecycleManager emits on the state event bus."""

    def setup_method(self):
        reset_state_event_bus()

    def teardown_method(self):
        reset_state_event_bus()

    def _make_envelope(self, tool_name: str = "test_tool"):
        """Minimal TaskEnvelope-like object."""
        from core.schemas.task_envelope import TaskEnvelope
        return TaskEnvelope(tool_name=tool_name, args={})

    def test_mark_running_emits_task_started(self):
        from core.task_lifecycle import TaskLifecycleManager
        bus = get_state_event_bus()
        received: List[StateEvent] = []
        bus.subscribe(StateEventType.TASK_STARTED, received.append)

        mgr = TaskLifecycleManager()
        env = self._make_envelope()
        mgr.mark_running(env)

        assert len(received) == 1
        assert received[0].payload["lifecycle_status"] == "running"

    def test_mark_done_emits_task_done(self):
        from core.task_lifecycle import TaskLifecycleManager
        bus = get_state_event_bus()
        received: List[StateEvent] = []
        bus.subscribe(StateEventType.TASK_DONE, received.append)

        mgr = TaskLifecycleManager()
        env = self._make_envelope()
        env = mgr.mark_running(env)
        mgr.mark_done(env, result_summary="ok")

        assert len(received) == 1
        assert received[0].payload["lifecycle_status"] == "done"

    def test_mark_failed_emits_task_failed(self):
        from core.task_lifecycle import TaskLifecycleManager
        bus = get_state_event_bus()
        received: List[StateEvent] = []
        bus.subscribe(StateEventType.TASK_FAILED, received.append)

        mgr = TaskLifecycleManager()
        env = self._make_envelope()
        env = mgr.mark_running(env)
        mgr.mark_failed(env, error="something went wrong")

        assert len(received) == 1
        assert received[0].payload["lifecycle_status"] == "failed"

    def test_trace_id_carried_in_lifecycle_event(self):
        from core.task_lifecycle import TaskLifecycleManager
        bus = get_state_event_bus()
        received: List[StateEvent] = []
        bus.subscribe(StateEventType.TASK_STARTED, received.append)

        mgr = TaskLifecycleManager()
        env = self._make_envelope()
        # Manually set trace_id on the envelope to verify propagation.
        env = env.model_copy(update={"trace_id": "fixed-trace-id"})
        mgr.mark_running(env)

        assert received[0].trace_id == "fixed-trace-id"


# ===========================================================================
# 10. DesktopPresenceRuntime integration
# ===========================================================================


class TestDesktopPresenceRuntimeIntegration:
    """Verify that RuntimeSession.advance() emits phase events."""

    def setup_method(self):
        reset_state_event_bus()

    def teardown_method(self):
        reset_state_event_bus()

    def test_advance_to_liminal_emits_phase_liminal(self):
        from core.desktop_presence_runtime import RuntimeSession, TriState
        bus = get_state_event_bus()
        received: List[StateEvent] = []
        bus.subscribe(StateEventType.PHASE_LIMINAL, received.append)

        session = RuntimeSession(source="test")
        session.advance(TriState.LIMINAL)

        assert len(received) == 1
        assert received[0].payload["to_phase"] == "liminal"
        assert received[0].trace_id == session.trace_id

    def test_advance_to_manifest_emits_phase_manifest(self):
        from core.desktop_presence_runtime import RuntimeSession, TriState
        bus = get_state_event_bus()
        received: List[StateEvent] = []
        bus.subscribe(StateEventType.PHASE_MANIFEST, received.append)

        session = RuntimeSession(source="test")
        session.advance(TriState.LIMINAL)
        session.advance(TriState.MANIFEST)

        assert len(received) == 1
        assert received[0].payload["to_phase"] == "manifest"

    def test_advance_to_silent_emits_phase_silent(self):
        from core.desktop_presence_runtime import RuntimeSession, TriState
        bus = get_state_event_bus()
        received: List[StateEvent] = []
        bus.subscribe(StateEventType.PHASE_SILENT, received.append)

        session = RuntimeSession(source="test")
        session.advance(TriState.LIMINAL)
        session.advance(TriState.MANIFEST)
        session.advance(TriState.SILENT)

        assert len(received) == 1
        assert received[0].payload["from_phase"] == "manifest"
        assert received[0].payload["to_phase"] == "silent"

    def test_runtime_session_id_in_phase_event(self):
        from core.desktop_presence_runtime import RuntimeSession, TriState
        bus = get_state_event_bus()
        received: List[StateEvent] = []
        bus.subscribe(None, received.append)  # wildcard

        session = RuntimeSession(source="chat")
        session.advance(TriState.LIMINAL)

        phase_events = [e for e in received if e.type == StateEventType.PHASE_LIMINAL.value]
        assert phase_events
        assert phase_events[0].runtime_session_id == session.runtime_session_id


# ===========================================================================
# 11. config.json flags
# ===========================================================================


class TestConfigFlags:
    def test_pr8_flags_present(self):
        config_path = pathlib.Path(__file__).parent.parent / "config.json"
        with config_path.open() as f:
            cfg = json.load(f)
        assert "enable_state_event_bus" in cfg
        assert cfg["enable_state_event_bus"] is True
        assert "state_event_bus_log_all" in cfg


# ===========================================================================
# 12. Backward compatibility — integration.event_bus unaffected
# ===========================================================================


class TestBackwardCompatibility:
    def test_integration_event_bus_still_importable(self):
        from integration.event_bus import event_bus, EventType
        assert event_bus is not None
        assert EventType.COMMAND_DISPATCHED is not None

    def test_task_lifecycle_m2_emit_still_works(self):
        """mark_running should not raise even when M2 event bus is unavailable."""
        from core.task_lifecycle import TaskLifecycleManager
        from core.schemas.task_envelope import TaskEnvelope

        reset_state_event_bus()
        env = TaskEnvelope(tool_name="compat_test", args={})
        mgr = TaskLifecycleManager()
        # Should not raise regardless of M2 bus availability.
        updated = mgr.mark_running(env)
        assert updated.lifecycle_status == "running"

    def test_state_event_bus_does_not_break_process(self):
        """Importing state_event_bus does not import openclawd at module level."""
        import core.state_event_bus as seb
        # If openclawd were imported at module level, circular import errors
        # would surface here.
        assert hasattr(seb, "StateEventBus")
        assert hasattr(seb, "get_state_event_bus")
