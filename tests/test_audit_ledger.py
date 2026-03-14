"""
tests/test_audit_ledger.py
===========================

Unit tests for core.control_plane.audit_ledger.
"""

import json

import pytest

from core.control_plane.audit_ledger import (
    AuditLedger,
    EventType,
    LedgerSnapshot,
    Severity,
    TraceEvent,
    events_to_dag,
    events_to_json,
)


# ---------------------------------------------------------------------------
# TraceEvent model tests
# ---------------------------------------------------------------------------

class TestTraceEvent:
    def test_default_fields(self):
        ev = TraceEvent(event_type=EventType.TASK_CREATED)
        assert ev.event_id.startswith("ev_")
        assert ev.timestamp is not None
        assert ev.severity == Severity.INFO
        assert ev.parent_ids == []
        assert ev.payload == {}

    def test_frozen_prevents_mutation(self):
        ev = TraceEvent(event_type=EventType.TASK_CREATED)
        with pytest.raises(Exception):  # ValidationError or TypeError (frozen)
            ev.severity = Severity.ERROR  # type: ignore[misc]

    def test_all_fields_populated(self):
        ev = TraceEvent(
            event_type=EventType.APPROVAL_GRANTED,
            severity=Severity.WARNING,
            source="security_interceptor",
            message="HITL approved",
            trace_id="trace_abc",
            task_id="task_001",
            agent_id="agent_99",
            device_id="dev_xy",
            session_id="sess_z",
            parent_ids=["ev_parent1", "ev_parent2"],
            payload={"operator": "alice"},
        )
        assert ev.trace_id == "trace_abc"
        assert ev.task_id == "task_001"
        assert len(ev.parent_ids) == 2
        assert ev.payload["operator"] == "alice"

    def test_event_types_are_strings(self):
        # EventType inherits str — safe for JSON serialisation without extra steps
        assert isinstance(EventType.TASK_DISPATCHED, str)

    def test_severity_ordering(self):
        # Enum members exist
        for member in (
            Severity.DEBUG, Severity.INFO, Severity.WARNING,
            Severity.ERROR, Severity.CRITICAL,
        ):
            assert isinstance(member, Severity)


# ---------------------------------------------------------------------------
# AuditLedger tests
# ---------------------------------------------------------------------------

class TestAuditLedger:
    def test_empty_on_init(self):
        ledger = AuditLedger()
        assert len(ledger) == 0
        assert ledger.all_events == []

    def test_append_returns_event_id(self):
        ledger = AuditLedger()
        eid = ledger.append(
            EventType.TASK_CREATED,
            source="test",
            task_id="t1",
        )
        assert eid.startswith("ev_")
        assert len(ledger) == 1

    def test_multiple_appends(self):
        ledger = AuditLedger()
        for _ in range(5):
            ledger.append(EventType.DEVICE_HEARTBEAT)
        assert len(ledger) == 5

    def test_get_by_id(self):
        ledger = AuditLedger()
        eid = ledger.append(EventType.TASK_STARTED, task_id="t2")
        ev = ledger.get_by_id(eid)
        assert ev is not None
        assert ev.event_id == eid
        assert ev.task_id == "t2"

    def test_get_by_id_not_found(self):
        ledger = AuditLedger()
        assert ledger.get_by_id("nonexistent") is None

    def test_query_by_task_id(self):
        ledger = AuditLedger()
        ledger.append(EventType.TASK_CREATED, task_id="task_A")
        ledger.append(EventType.TASK_STARTED, task_id="task_A")
        ledger.append(EventType.TASK_CREATED, task_id="task_B")

        results = ledger.query(task_id="task_A")
        assert len(results) == 2
        for ev in results:
            assert ev.task_id == "task_A"

    def test_query_by_event_type(self):
        ledger = AuditLedger()
        ledger.append(EventType.TASK_CREATED)
        ledger.append(EventType.TASK_FAILED)
        ledger.append(EventType.TASK_CREATED)

        results = ledger.query(event_type=EventType.TASK_CREATED)
        assert len(results) == 2

    def test_query_by_severity(self):
        ledger = AuditLedger()
        ledger.append(EventType.SYSTEM_ERROR, severity=Severity.ERROR)
        ledger.append(EventType.TASK_CREATED, severity=Severity.INFO)

        assert len(ledger.query(severity=Severity.ERROR)) == 1
        assert len(ledger.query(severity=Severity.INFO)) == 1

    def test_query_by_source(self):
        ledger = AuditLedger()
        ledger.append(EventType.TASK_CREATED, source="scheduler")
        ledger.append(EventType.TASK_CREATED, source="gateway")

        assert len(ledger.query(source="scheduler")) == 1

    def test_query_limit(self):
        ledger = AuditLedger()
        for i in range(10):
            ledger.append(EventType.DEVICE_HEARTBEAT, task_id="t")
        results = ledger.query(task_id="t", limit=3)
        assert len(results) == 3

    def test_query_combined_filters(self):
        ledger = AuditLedger()
        ledger.append(EventType.APPROVAL_REQUESTED, source="sec", task_id="t1")
        ledger.append(EventType.APPROVAL_GRANTED, source="sec", task_id="t1")
        ledger.append(EventType.APPROVAL_GRANTED, source="sec", task_id="t2")

        results = ledger.query(
            source="sec",
            task_id="t1",
            event_type=EventType.APPROVAL_GRANTED,
        )
        assert len(results) == 1

    def test_parent_ids_linkage(self):
        ledger = AuditLedger()
        e1 = ledger.append(EventType.TASK_CREATED)
        e2 = ledger.append(EventType.TASK_DISPATCHED, parent_ids=[e1])
        e3 = ledger.append(EventType.TASK_STARTED, parent_ids=[e2])

        ev3 = ledger.get_by_id(e3)
        assert ev3 is not None
        assert ev3.parent_ids == [e2]


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

class TestSerialisationHelpers:
    def _make_chain(self) -> AuditLedger:
        ledger = AuditLedger()
        e1 = ledger.append(EventType.TASK_CREATED, task_id="t", trace_id="tr1")
        e2 = ledger.append(
            EventType.TASK_DISPATCHED,
            task_id="t",
            trace_id="tr1",
            parent_ids=[e1],
        )
        ledger.append(
            EventType.TASK_COMPLETED,
            task_id="t",
            trace_id="tr1",
            parent_ids=[e2],
        )
        return ledger

    def test_to_json_is_valid_json(self):
        ledger = self._make_chain()
        raw = ledger.to_json()
        parsed = json.loads(raw)
        assert isinstance(parsed, list)
        assert len(parsed) == 3

    def test_to_json_contains_event_fields(self):
        ledger = self._make_chain()
        raw = ledger.to_json()
        parsed = json.loads(raw)
        first = parsed[0]
        assert "event_id" in first
        assert "event_type" in first
        assert "timestamp" in first

    def test_events_to_json_helper(self):
        events = [TraceEvent(event_type=EventType.TASK_CREATED)]
        raw = events_to_json(events)
        parsed = json.loads(raw)
        assert len(parsed) == 1

    def test_to_dag_structure(self):
        ledger = self._make_chain()
        dag = ledger.to_dag()
        assert isinstance(dag, dict)
        assert len(dag) == 3
        # root event has no parents
        event_ids = list(dag.keys())
        root_id = event_ids[0]
        assert dag[root_id] == []
        # second event points to root
        second_id = event_ids[1]
        assert dag[second_id] == [root_id]

    def test_events_to_dag_standalone(self):
        e1 = TraceEvent(event_type=EventType.TASK_CREATED)
        e2 = TraceEvent(
            event_type=EventType.TASK_DISPATCHED, parent_ids=[e1.event_id]
        )
        dag = events_to_dag([e1, e2])
        assert dag[e1.event_id] == []
        assert dag[e2.event_id] == [e1.event_id]

    def test_snapshot(self):
        ledger = self._make_chain()
        snap = ledger.snapshot()
        assert isinstance(snap, LedgerSnapshot)
        assert snap.event_count == 3
        assert len(snap.events) == 3

    def test_snapshot_is_independent_copy(self):
        ledger = self._make_chain()
        snap = ledger.snapshot()
        ledger.append(EventType.TASK_FAILED)
        assert len(ledger) == 4
        assert snap.event_count == 3  # snapshot not affected
