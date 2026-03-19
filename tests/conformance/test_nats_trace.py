"""
tests/conformance/test_nats_trace.py
=====================================
PR-2 Protocol Conformance Suite — NATS Trace Propagation

Validates that:
  A) NATSTopics provides canonical topic constants for all namespaces.
  B) NATSTopics helper methods produce correctly-formatted subject strings.
  C) NATSBus._ensure_trace_fields() injects trace_id and runtime_session_id.
  D) NATSBus._ensure_trace_fields() preserves existing trace field values.
  E) NATSBus publish_task_event() includes trace fields in noop mode.
  F) NATSBus publish_device_event() includes trace fields in noop mode.
  G) NATSBus publish_presence_event() includes trace fields in noop mode.
  H) NATSBus publish_capability_event() includes trace fields in noop mode.
  I) NATSBus publish_audit_event() includes trace fields in noop mode.
  J) Published payloads always carry _nats_schema discriminator.
  K) Standardized topic names match the PR-2 canonical namespace contract.
  L) Legacy publish methods (publish_task_dispatch etc.) still work.
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.nats_bus import NATSTopics, NATSBus


# ===========================================================================
# A) NATSTopics canonical topic constants
# ===========================================================================

class TestNATSTopicsConstants:

    def test_task_dispatch_constant_defined(self):
        assert NATSTopics.TASK_DISPATCH == "galaxy.task.dispatch"

    def test_task_result_constant_defined(self):
        assert NATSTopics.TASK_RESULT == "galaxy.task.result"

    def test_task_cancel_constant_defined(self):
        assert NATSTopics.TASK_CANCEL == "galaxy.task.cancel"

    def test_task_status_constant_defined(self):
        assert NATSTopics.TASK_STATUS == "galaxy.task.status"

    def test_device_register_constant_defined(self):
        assert NATSTopics.DEVICE_REGISTER == "galaxy.device.register"

    def test_device_heartbeat_constant_defined(self):
        assert NATSTopics.DEVICE_HEARTBEAT == "galaxy.device.heartbeat"

    def test_device_status_constant_defined(self):
        assert NATSTopics.DEVICE_STATUS == "galaxy.device.status"

    def test_device_presence_constant_defined(self):
        assert NATSTopics.DEVICE_PRESENCE == "galaxy.device.presence"

    def test_presence_state_constant_defined(self):
        assert NATSTopics.PRESENCE_STATE == "galaxy.presence.state"

    def test_presence_projection_constant_defined(self):
        assert NATSTopics.PRESENCE_PROJECTION == "galaxy.presence.projection"

    def test_capability_registered_constant_defined(self):
        assert NATSTopics.CAPABILITY_REGISTERED == "galaxy.capability.registered"

    def test_capability_removed_constant_defined(self):
        assert NATSTopics.CAPABILITY_REMOVED == "galaxy.capability.removed"

    def test_audit_command_constant_defined(self):
        assert NATSTopics.AUDIT_COMMAND == "galaxy.audit.command"

    def test_audit_result_constant_defined(self):
        assert NATSTopics.AUDIT_RESULT == "galaxy.audit.result"

    def test_audit_violation_constant_defined(self):
        assert NATSTopics.AUDIT_VIOLATION == "galaxy.audit.violation"


# ===========================================================================
# B) NATSTopics helper methods
# ===========================================================================

class TestNATSTopicsHelpers:

    def test_task_dispatch_with_target(self):
        subject = NATSTopics.task_dispatch("worker-01")
        assert subject == "galaxy.task.dispatch.worker-01"

    def test_task_dispatch_with_wildcard(self):
        subject = NATSTopics.task_dispatch(">")
        assert subject.startswith("galaxy.task.dispatch.")

    def test_task_result_with_task_id(self):
        subject = NATSTopics.task_result("task-abc-123")
        assert subject == "galaxy.task.result.task-abc-123"

    def test_device_heartbeat_with_device_id(self):
        subject = NATSTopics.device_heartbeat("android-01")
        assert subject == "galaxy.device.heartbeat.android-01"

    def test_capability_registered_with_source(self):
        subject = NATSTopics.capability_registered("mcp")
        assert subject == "galaxy.capability.registered.mcp"

    def test_all_task_topics_start_with_galaxy_task(self):
        for attr in ("TASK_DISPATCH", "TASK_RESULT", "TASK_CANCEL", "TASK_STATUS"):
            value = getattr(NATSTopics, attr)
            assert value.startswith("galaxy.task."), (
                f"NATSTopics.{attr} must start with 'galaxy.task.'"
            )

    def test_all_device_topics_start_with_galaxy_device(self):
        for attr in ("DEVICE_REGISTER", "DEVICE_HEARTBEAT", "DEVICE_STATUS", "DEVICE_PRESENCE"):
            value = getattr(NATSTopics, attr)
            assert value.startswith("galaxy.device."), (
                f"NATSTopics.{attr} must start with 'galaxy.device.'"
            )

    def test_all_audit_topics_start_with_galaxy_audit(self):
        for attr in ("AUDIT_COMMAND", "AUDIT_RESULT", "AUDIT_VIOLATION"):
            value = getattr(NATSTopics, attr)
            assert value.startswith("galaxy.audit."), (
                f"NATSTopics.{attr} must start with 'galaxy.audit.'"
            )


# ===========================================================================
# C) NATSBus._ensure_trace_fields injects when absent
# ===========================================================================

class TestEnsureTraceFieldsInjection:

    def _make_noop_bus(self) -> NATSBus:
        bus = NATSBus.__new__(NATSBus)
        bus._url = ""
        bus._auto_local = False
        bus._nc = None
        bus._js = None
        bus._connected = False
        bus._noop = True
        bus._subscriptions = []
        bus._stats = {"published": 0, "received": 0, "errors": 0, "reconnects": 0}
        return bus

    def test_injects_trace_id_when_absent(self):
        bus = self._make_noop_bus()
        result = bus._ensure_trace_fields({})
        assert result.get("trace_id"), "trace_id must be injected when absent"

    def test_injects_runtime_session_id_when_absent(self):
        bus = self._make_noop_bus()
        result = bus._ensure_trace_fields({})
        assert result.get("runtime_session_id"), "runtime_session_id must be injected when absent"

    def test_uses_provided_trace_id_when_given(self):
        bus = self._make_noop_bus()
        result = bus._ensure_trace_fields({}, trace_id="trace-explicit-01")
        assert result["trace_id"] == "trace-explicit-01"

    def test_uses_provided_runtime_session_id_when_given(self):
        bus = self._make_noop_bus()
        result = bus._ensure_trace_fields({}, runtime_session_id="sess-explicit-01")
        assert result["runtime_session_id"] == "sess-explicit-01"

    def test_injected_trace_id_is_string(self):
        bus = self._make_noop_bus()
        result = bus._ensure_trace_fields({})
        assert isinstance(result["trace_id"], str)

    def test_injected_session_id_is_string(self):
        bus = self._make_noop_bus()
        result = bus._ensure_trace_fields({})
        assert isinstance(result["runtime_session_id"], str)

    def test_input_dict_not_mutated(self):
        bus = self._make_noop_bus()
        original = {"key": "value"}
        bus._ensure_trace_fields(original)
        assert "trace_id" not in original


# ===========================================================================
# D) NATSBus._ensure_trace_fields preserves existing values
# ===========================================================================

class TestEnsureTraceFieldsPreservation:

    def _make_noop_bus(self) -> NATSBus:
        bus = NATSBus.__new__(NATSBus)
        bus._url = ""
        bus._auto_local = False
        bus._nc = None
        bus._js = None
        bus._connected = False
        bus._noop = True
        bus._subscriptions = []
        bus._stats = {"published": 0, "received": 0, "errors": 0, "reconnects": 0}
        return bus

    def test_preserves_existing_trace_id(self):
        bus = self._make_noop_bus()
        existing = "trace-existing-001"
        result = bus._ensure_trace_fields({"trace_id": existing})
        assert result["trace_id"] == existing

    def test_preserves_existing_runtime_session_id(self):
        bus = self._make_noop_bus()
        existing_sid = "session-existing-abc"
        result = bus._ensure_trace_fields({"runtime_session_id": existing_sid})
        assert result["runtime_session_id"] == existing_sid

    def test_preserves_data_payload(self):
        bus = self._make_noop_bus()
        result = bus._ensure_trace_fields({"action": "screenshot", "device_id": "d1"})
        assert result["action"] == "screenshot"
        assert result["device_id"] == "d1"


# ===========================================================================
# E–I) Canonical publish methods include trace fields and schema discriminator
# ===========================================================================

class TestCanonicalPublishMethods:

    def _make_noop_bus_with_capture(self):
        """Create a noop NATSBus that captures _publish calls."""
        bus = NATSBus.__new__(NATSBus)
        bus._url = ""
        bus._auto_local = False
        bus._nc = None
        bus._js = None
        bus._connected = False
        bus._noop = True
        bus._subscriptions = []
        bus._stats = {"published": 0, "received": 0, "errors": 0, "reconnects": 0}
        captured = []

        async def _capture_publish(subject, data):
            captured.append({"subject": subject, "data": data})
            return {"success": True, "noop": True}

        bus._publish = _capture_publish
        return bus, captured

    @pytest.mark.asyncio
    async def test_publish_task_event_trace_propagated(self):
        bus, captured = self._make_noop_bus_with_capture()
        await bus.publish_task_event(
            "dispatch.worker-01",
            {"action": "task_run"},
            trace_id="trace-task-01",
            runtime_session_id="sess-task-01",
        )
        assert len(captured) == 1
        data = captured[0]["data"]
        assert data["trace_id"] == "trace-task-01"
        assert data["runtime_session_id"] == "sess-task-01"

    @pytest.mark.asyncio
    async def test_publish_task_event_schema_discriminator(self):
        bus, captured = self._make_noop_bus_with_capture()
        await bus.publish_task_event("status.t-01", {})
        assert captured[0]["data"]["_nats_schema"] == "UnifiedTaskEvent"

    @pytest.mark.asyncio
    async def test_publish_task_event_subject_prefix(self):
        bus, captured = self._make_noop_bus_with_capture()
        await bus.publish_task_event("dispatch.worker-99", {})
        assert captured[0]["subject"] == "galaxy.task.dispatch.worker-99"

    @pytest.mark.asyncio
    async def test_publish_device_event_trace_propagated(self):
        bus, captured = self._make_noop_bus_with_capture()
        await bus.publish_device_event(
            "heartbeat.dev-01",
            {"status": "online"},
            trace_id="trace-dev-01",
        )
        assert captured[0]["data"]["trace_id"] == "trace-dev-01"

    @pytest.mark.asyncio
    async def test_publish_device_event_schema_discriminator(self):
        bus, captured = self._make_noop_bus_with_capture()
        await bus.publish_device_event("register", {})
        assert captured[0]["data"]["_nats_schema"] == "UnifiedDeviceEvent"

    @pytest.mark.asyncio
    async def test_publish_presence_event_trace_propagated(self):
        bus, captured = self._make_noop_bus_with_capture()
        await bus.publish_presence_event(
            "state",
            {"phase": "manifest"},
            trace_id="trace-presence-01",
        )
        assert captured[0]["data"]["trace_id"] == "trace-presence-01"

    @pytest.mark.asyncio
    async def test_publish_presence_event_schema_discriminator(self):
        bus, captured = self._make_noop_bus_with_capture()
        await bus.publish_presence_event("projection", {})
        assert captured[0]["data"]["_nats_schema"] == "UnifiedPresenceEvent"

    @pytest.mark.asyncio
    async def test_publish_capability_event_trace_propagated(self):
        bus, captured = self._make_noop_bus_with_capture()
        await bus.publish_capability_event(
            "registered.mcp",
            {"name": "screenshot"},
            trace_id="trace-cap-01",
        )
        assert captured[0]["data"]["trace_id"] == "trace-cap-01"

    @pytest.mark.asyncio
    async def test_publish_capability_event_schema_discriminator(self):
        bus, captured = self._make_noop_bus_with_capture()
        await bus.publish_capability_event("removed.skill", {})
        assert captured[0]["data"]["_nats_schema"] == "UnifiedCapabilityEvent"

    @pytest.mark.asyncio
    async def test_publish_audit_event_trace_propagated(self):
        bus, captured = self._make_noop_bus_with_capture()
        await bus.publish_audit_event(
            "command",
            {"action": "click"},
            trace_id="trace-audit-01",
        )
        assert captured[0]["data"]["trace_id"] == "trace-audit-01"

    @pytest.mark.asyncio
    async def test_publish_audit_event_schema_discriminator(self):
        bus, captured = self._make_noop_bus_with_capture()
        await bus.publish_audit_event("result", {})
        assert captured[0]["data"]["_nats_schema"] == "UnifiedAuditEvent"


# ===========================================================================
# J) All canonical publish methods inject trace when not provided
# ===========================================================================

class TestAutoTraceInjection:

    def _make_capture_bus(self):
        bus = NATSBus.__new__(NATSBus)
        bus._url = ""
        bus._auto_local = False
        bus._nc = None
        bus._js = None
        bus._connected = False
        bus._noop = True
        bus._subscriptions = []
        bus._stats = {"published": 0, "received": 0, "errors": 0, "reconnects": 0}
        captured = []

        async def _cap(subject, data):
            captured.append(data)
            return {"success": True}

        bus._publish = _cap
        return bus, captured

    @pytest.mark.asyncio
    async def test_task_event_auto_injects_trace(self):
        bus, captured = self._make_capture_bus()
        await bus.publish_task_event("dispatch.w", {})
        assert captured[0].get("trace_id"), "trace_id must be auto-injected"
        assert captured[0].get("runtime_session_id"), "runtime_session_id must be auto-injected"

    @pytest.mark.asyncio
    async def test_device_event_auto_injects_trace(self):
        bus, captured = self._make_capture_bus()
        await bus.publish_device_event("heartbeat.d", {})
        assert captured[0].get("trace_id")

    @pytest.mark.asyncio
    async def test_presence_event_auto_injects_trace(self):
        bus, captured = self._make_capture_bus()
        await bus.publish_presence_event("state", {})
        assert captured[0].get("trace_id")

    @pytest.mark.asyncio
    async def test_capability_event_auto_injects_trace(self):
        bus, captured = self._make_capture_bus()
        await bus.publish_capability_event("registered.mcp", {})
        assert captured[0].get("trace_id")

    @pytest.mark.asyncio
    async def test_audit_event_auto_injects_trace(self):
        bus, captured = self._make_capture_bus()
        await bus.publish_audit_event("command", {})
        assert captured[0].get("trace_id")


# ===========================================================================
# K) Topic namespace contract — no legacy galaxy.tasks prefix in new API
# ===========================================================================

class TestTopicNamespaceContract:

    def test_canonical_task_topic_uses_singular(self):
        assert "galaxy.task." in NATSTopics.TASK_DISPATCH
        assert "galaxy.tasks." not in NATSTopics.TASK_DISPATCH

    def test_canonical_device_topic_uses_singular(self):
        assert "galaxy.device." in NATSTopics.DEVICE_REGISTER
        assert "galaxy.devices." not in NATSTopics.DEVICE_REGISTER

    def test_helper_task_dispatch_returns_singular_prefix(self):
        subject = NATSTopics.task_dispatch("worker-01")
        assert subject.startswith("galaxy.task.dispatch.")

    def test_helper_task_result_returns_singular_prefix(self):
        subject = NATSTopics.task_result("task-01")
        assert subject.startswith("galaxy.task.result.")


# ===========================================================================
# L) Legacy publish methods remain backward-compatible
# ===========================================================================

class TestLegacyPublishBackwardCompat:

    def _make_noop_bus(self) -> NATSBus:
        bus = NATSBus.__new__(NATSBus)
        bus._url = ""
        bus._auto_local = False
        bus._nc = None
        bus._js = None
        bus._connected = False
        bus._noop = True
        bus._subscriptions = []
        bus._stats = {"published": 0, "received": 0, "errors": 0, "reconnects": 0}
        return bus

    @pytest.mark.asyncio
    async def test_publish_heartbeat_still_works(self):
        from core.schemas.contracts import WorkerHeartbeatModel
        bus = self._make_noop_bus()
        hb = WorkerHeartbeatModel(worker_id="w1", status="idle", capabilities=[])
        result = await bus.publish_heartbeat(hb)
        assert result.get("success") is True

    @pytest.mark.asyncio
    async def test_is_connected_returns_false_in_noop(self):
        bus = self._make_noop_bus()
        assert bus.is_connected() is False

    @pytest.mark.asyncio
    async def test_get_stats_returns_dict(self):
        bus = self._make_noop_bus()
        stats = bus.get_stats()
        assert isinstance(stats, dict)
        assert "connected" in stats
        assert "noop_mode" in stats
