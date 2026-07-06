"""tests/test_event_bus_deque_slice_fix.py
============================================

integration.event_bus.EventBus._event_history is a deque(maxlen=1000), which
does not support slice indexing. get_event_history() previously kept the raw
deque reference (never converted to list) whenever called with no event_type
filter - the overwhelmingly common case, e.g. core.event_bridge's 5-minute
periodic cleanup loop calls `event_bus.get_event_history()` with no arguments
at all. `events[-limit:]` on that raw deque raised
"TypeError: sequence index must be integer, not 'slice'" every single time,
silently swallowed by a bare `except Exception: logger.warning(...)` in the
caller - which is exactly the recurring, untraceable "Exception suppressed:
sequence index must be integer, not 'slice'" a real deployment logged every
~5 minutes.

publish() had the same class of bug: manually re-slicing self._event_history
after append() whenever length exceeded _max_history - except _max_history
(1000) is identical to the deque's own maxlen, so the deque already
self-evicts and that branch could never actually fire in practice (dead but
still broken code).
"""
from __future__ import annotations

import pytest

from integration.event_bus import EventBus, EventType


@pytest.fixture
def fresh_bus():
    EventBus._instance = None
    bus = EventBus()
    yield bus
    EventBus._instance = None


class TestEventBusDequeSliceFix:
    def test_get_event_history_no_filter_does_not_crash(self, fresh_bus):
        """This is the exact call core.event_bridge's cleanup loop makes."""
        fresh_bus.publish_sync(list(EventType)[0], source="test", data={})
        history = fresh_bus.get_event_history()
        assert isinstance(history, list)

    def test_get_event_history_respects_limit(self, fresh_bus):
        for i in range(10):
            fresh_bus.publish_sync(list(EventType)[0], source="test", data={"i": i})
        history = fresh_bus.get_event_history(limit=3)
        assert len(history) == 3

    def test_get_event_history_with_type_filter_still_works(self, fresh_bus):
        et = list(EventType)[0]
        fresh_bus.publish_sync(et, source="test", data={})
        history = fresh_bus.get_event_history(event_type=et, limit=5)
        assert isinstance(history, list)
        assert all(e.event_type == et for e in history)

    def test_publishing_past_maxlen_does_not_crash_and_still_caps_history(self, fresh_bus):
        """Exercises the deque's own eviction plus the (now-removed) manual
        re-slice path that used to crash whenever length exceeded _max_history."""
        et = list(EventType)[0]
        for i in range(1200):
            fresh_bus.publish_sync(et, source="test", data={"i": i})
        assert len(fresh_bus._event_history) == 1000
        history = fresh_bus.get_event_history()
        assert isinstance(history, list)
