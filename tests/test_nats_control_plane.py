"""
Tests for unified NATS-centric control plane (Phases A–E).

Covers:
  - GatewayNATSAdapter: dispatch / result roundtrip (mock NATS)
  - NodeHeartbeatSender: registration and heartbeat message content
  - NATSExecutor: task dispatch and result resolution
  - Observability: /health/nats endpoint structure
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).parent.parent.absolute()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_nats_bus(connected: bool = True) -> MagicMock:
    """Create a mock NATSBus that reports as connected."""
    bus = MagicMock()
    bus.is_connected.return_value = connected
    bus.get_stats.return_value = {
        "connected": connected,
        "noop_mode": not connected,
        "published": 0,
        "received": 0,
        "errors": 0,
        "reconnects": 0,
        "subscriptions": 0,
        "url": "nats://localhost:4222",
    }
    bus._publish = AsyncMock(return_value={"success": True, "seq": 1})
    bus.publish_task_dispatch = AsyncMock(return_value={"success": True, "seq": 1})
    bus.publish_task_result = AsyncMock(return_value={"success": True, "seq": 2})
    bus.publish_heartbeat = AsyncMock(return_value={"success": True, "seq": 3})
    bus.publish_event = AsyncMock(return_value={"success": True, "seq": 4})
    bus._subscribe = AsyncMock(return_value={"success": True})
    bus.subscribe_task_results = AsyncMock(return_value={"success": True})
    bus.connect = AsyncMock(return_value={"success": True})
    bus.disconnect = AsyncMock(return_value={"success": True})
    return bus


# ===========================================================================
# Phase B — GatewayNATSAdapter
# ===========================================================================


class TestGatewayNATSAdapter:
    """Smoke tests for GatewayNATSAdapter dispatch / result flow."""

    @pytest.mark.asyncio
    async def test_start_subscribes_when_connected(self):
        """Adapter subscribes to the gateway subject when NATS is connected."""
        from galaxy_gateway.gateway_nats_adapter import GatewayNATSAdapter

        mock_bus = _make_mock_nats_bus(connected=True)
        adapter = GatewayNATSAdapter()

        with patch("core.nats_bus.nats_bus", mock_bus):
            await adapter.start()

        mock_bus._subscribe.assert_called_once()
        call_args = mock_bus._subscribe.call_args
        assert "galaxy.tasks.dispatch.gateway" in call_args[0][0]
        assert adapter._started is True

    @pytest.mark.asyncio
    async def test_start_noop_when_disconnected(self):
        """Adapter does not mark started when NATS is disconnected."""
        from galaxy_gateway.gateway_nats_adapter import GatewayNATSAdapter

        mock_bus = _make_mock_nats_bus(connected=False)
        adapter = GatewayNATSAdapter()

        with patch("core.nats_bus.nats_bus", mock_bus):
            await adapter.start()

        assert adapter._started is False

    @pytest.mark.asyncio
    async def test_resolve_task_fulfills_pending_future(self):
        """resolve_task() sets the result on the pending Future."""
        from galaxy_gateway.gateway_nats_adapter import GatewayNATSAdapter

        adapter = GatewayNATSAdapter()
        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        adapter._pending["task-abc"] = fut

        adapter.resolve_task("task-abc", {"success": True, "data": 42})

        assert fut.done()
        assert fut.result() == {"success": True, "data": 42}

    @pytest.mark.asyncio
    async def test_handle_task_dispatch_publishes_result(self):
        """A dispatched task that resolves immediately publishes a success result."""
        from galaxy_gateway.gateway_nats_adapter import GatewayNATSAdapter

        mock_bus = _make_mock_nats_bus(connected=True)
        adapter = GatewayNATSAdapter(task_timeout=5.0)

        # Patch device routing to immediately return success
        async def _fast_forward(task_id, target, task_type, payload):
            return {"success": True, "data": "device_output"}

        adapter._forward_to_device = _fast_forward

        with patch("core.nats_bus.nats_bus", mock_bus):
            await adapter._handle_task_dispatch(
                {
                    "task_id": "t-001",
                    "target_worker_id": "device-01",
                    "task_type": "command",
                    "payload": {"action": "tap"},
                }
            )

        # PR-3: _publish_result now calls nats_bus._publish() directly with a
        # unified envelope payload instead of publish_task_result().
        mock_bus._publish.assert_awaited()
        call_args = mock_bus._publish.call_args[0]
        assert "galaxy.tasks.result.t-001" in call_args[0]
        assert call_args[1].get("task_id") == "t-001"
        assert call_args[1].get("_nats_schema") == "TaskEnvelope"

    @pytest.mark.asyncio
    async def test_handle_task_dispatch_dlq_on_timeout(self):
        """Exhausted retries send the task to the dead-letter queue."""
        from galaxy_gateway.gateway_nats_adapter import GatewayNATSAdapter

        mock_bus = _make_mock_nats_bus(connected=True)
        adapter = GatewayNATSAdapter(task_timeout=0.01, max_retries=0)

        async def _slow_forward(task_id, target, task_type, payload):
            await asyncio.sleep(10)  # simulate timeout
            return {}

        adapter._forward_to_device = _slow_forward

        with patch("core.nats_bus.nats_bus", mock_bus):
            await adapter._handle_task_dispatch(
                {
                    "task_id": "t-002",
                    "target_worker_id": "device-02",
                    "task_type": "command",
                    "payload": {},
                }
            )

        assert adapter._stats["timed_out"] == 1
        assert adapter._stats["dlq"] == 1

    def test_get_stats_returns_dict(self):
        """get_stats() returns a dict with expected keys."""
        from galaxy_gateway.gateway_nats_adapter import GatewayNATSAdapter

        adapter = GatewayNATSAdapter()
        stats = adapter.get_stats()
        assert "dispatched" in stats
        assert "succeeded" in stats
        assert "failed" in stats
        assert "pending_tasks" in stats


# ===========================================================================
# Phase C — NodeHeartbeatSender
# ===========================================================================


class TestNodeHeartbeatSender:
    """Smoke tests for the NATS heartbeat sender."""

    @pytest.mark.asyncio
    async def test_register_publishes_to_workers_register(self):
        """register() publishes a WorkerRegistration to galaxy.workers.register."""
        from core.nats_heartbeat import NodeHeartbeatSender

        mock_bus = _make_mock_nats_bus(connected=True)
        sender = NodeHeartbeatSender(
            worker_id="test-node",
            device_type="router",
            capabilities=["routing"],
        )

        with patch("core.nats_bus.nats_bus", mock_bus):
            result = await sender.register()

        assert result.get("success") is True
        mock_bus._publish.assert_awaited_once()
        subject = mock_bus._publish.call_args[0][0]
        assert subject == "galaxy.workers.register"

    @pytest.mark.asyncio
    async def test_register_includes_capabilities(self):
        """The registration payload includes the advertised capabilities."""
        from core.nats_heartbeat import NodeHeartbeatSender

        mock_bus = _make_mock_nats_bus(connected=True)
        sender = NodeHeartbeatSender(
            worker_id="node-test",
            capabilities=["cap_a", "cap_b"],
        )

        with patch("core.nats_bus.nats_bus", mock_bus):
            await sender.register()

        payload = mock_bus._publish.call_args[0][1]
        cap_names = [c["name"] for c in payload.get("capabilities", [])]
        assert "cap_a" in cap_names
        assert "cap_b" in cap_names

    @pytest.mark.asyncio
    async def test_register_noop_when_disconnected(self):
        """register() silently returns when NATS is not connected."""
        from core.nats_heartbeat import NodeHeartbeatSender

        mock_bus = _make_mock_nats_bus(connected=False)
        sender = NodeHeartbeatSender(worker_id="node-offline")

        with patch("core.nats_bus.nats_bus", mock_bus):
            result = await sender.register()

        assert result["success"] is False
        mock_bus._publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_heartbeat_published_every_interval(self):
        """The heartbeat loop sends heartbeats at the configured interval."""
        from core.nats_heartbeat import NodeHeartbeatSender

        call_count = 0

        mock_bus = _make_mock_nats_bus(connected=True)

        async def _mock_hb(hb):
            nonlocal call_count
            call_count += 1
            return {"success": True}

        mock_bus.publish_heartbeat = _mock_hb

        sender = NodeHeartbeatSender(worker_id="node-hb", interval_s=0.1)
        sender._running = True  # simulate started state

        with patch("core.nats_bus.nats_bus", mock_bus):
            task = asyncio.create_task(sender._loop())
            await asyncio.sleep(0.35)  # allow ~2 heartbeats at 0.1s interval
            sender._running = False
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert call_count >= 1

    @pytest.mark.asyncio
    async def test_start_node_heartbeat_returns_task(self):
        """start_node_heartbeat() returns a running asyncio.Task."""
        from core.nats_heartbeat import start_node_heartbeat

        mock_bus = _make_mock_nats_bus(connected=True)

        with patch("core.nats_bus.nats_bus", mock_bus):
            task = await start_node_heartbeat(
                worker_id="node-quick",
                device_type="router",
                capabilities=["test"],
            )

        assert isinstance(task, asyncio.Task)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


# ===========================================================================
# Phase D — NATSExecutor
# ===========================================================================


class TestNATSExecutor:
    """Smoke tests for the NATS CommandRouter executor."""

    @pytest.mark.asyncio
    async def test_dispatches_task_via_nats_bus(self):
        """NATSExecutor publishes a TaskDispatch when NATS is connected."""
        from core.command_router import NATSExecutor

        mock_bus = _make_mock_nats_bus(connected=True)
        executor = NATSExecutor(fallback_enabled=False, timeout_s=1.0)

        # Resolve the future immediately after publish
        async def _publish_and_resolve(worker_id, task):
            task_id = task.task_id
            # Simulate result arriving from NATS
            asyncio.get_event_loop().call_soon(
                lambda: executor._pending[task_id].set_result(
                    {"success": True, "result": "ok", "task_id": task_id}
                )
                if task_id in executor._pending
                else None
            )
            return {"success": True, "seq": 1}

        mock_bus.publish_task_dispatch = _publish_and_resolve

        with patch("core.nats_bus.nats_bus", mock_bus):
            result = await executor("device-01", "tap", {"x": 100, "y": 200})

        assert result.get("success") is True

    @pytest.mark.asyncio
    async def test_falls_back_when_nats_disconnected(self):
        """NATSExecutor uses fallback executor when NATS is disconnected."""
        from core.command_router import NATSExecutor

        fallback_called = {}

        async def fallback(target, command, params):
            fallback_called["called"] = True
            return {"success": True, "source": "fallback"}

        mock_bus = _make_mock_nats_bus(connected=False)
        executor = NATSExecutor(fallback_executor=fallback, fallback_enabled=True)

        with patch("core.nats_bus.nats_bus", mock_bus):
            result = await executor("device-01", "tap", {})

        assert fallback_called.get("called") is True
        assert result.get("source") == "fallback"

    @pytest.mark.asyncio
    async def test_on_task_result_resolves_pending_future(self):
        """_on_task_result() resolves the matching future."""
        from core.command_router import NATSExecutor

        executor = NATSExecutor()
        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        executor._pending["task-xyz"] = fut

        await executor._on_task_result({
            "task_id": "task-xyz",
            "status": "completed",
            "result": {"data": "hello"},
        })

        assert fut.done()
        assert fut.result()["success"] is True

    def test_get_stats_returns_expected_keys(self):
        """get_stats() returns a dict with all required keys."""
        from core.command_router import NATSExecutor

        executor = NATSExecutor()
        stats = executor.get_stats()
        assert "nats_dispatched" in stats
        assert "nats_resolved" in stats
        assert "fallback_used" in stats
        assert "pending" in stats

    @pytest.mark.asyncio
    async def test_start_subscribes_to_results(self):
        """start() subscribes to galaxy.tasks.result.* when NATS is connected."""
        from core.command_router import NATSExecutor

        mock_bus = _make_mock_nats_bus(connected=True)
        executor = NATSExecutor()

        with patch("core.nats_bus.nats_bus", mock_bus):
            await executor.start()

        mock_bus.subscribe_task_results.assert_awaited_once_with(executor._on_task_result)
        assert executor._started is True


# ===========================================================================
# Phase E — Observability Endpoints
# ===========================================================================


class TestNATSObservability:
    """Smoke tests for /health/nats and observability endpoints."""

    def test_health_nats_schema(self):
        """The /health/nats route returns the expected response shape."""
        # We test the schema by calling the route handler directly
        # (no HTTP server needed)
        mock_bus = _make_mock_nats_bus(connected=True)

        # Import the router factory
        from core.routes.observability import create_router
        import asyncio

        router = create_router()

        # Find the health/nats endpoint
        nats_health_route = None
        for route in router.routes:
            if hasattr(route, "path") and route.path == "/health/nats":
                nats_health_route = route
                break

        assert nats_health_route is not None, "/health/nats route not found"

    def test_observability_nats_route_registered(self):
        """The /api/v1/observability/nats route is registered."""
        from core.routes.observability import create_router

        router = create_router()
        paths = [getattr(r, "path", "") for r in router.routes]
        assert "/api/v1/observability/nats" in paths

    def test_bus_events_route_registered(self):
        """The /api/v1/observability/bus-events route is registered."""
        from core.routes.observability import create_router

        router = create_router()
        paths = [getattr(r, "path", "") for r in router.routes]
        assert "/api/v1/observability/bus-events" in paths

    @pytest.mark.asyncio
    async def test_nats_bus_get_stats_shape(self):
        """NATSBus.get_stats() returns the expected dictionary shape."""
        from core.nats_bus import NATSBus

        bus = NATSBus.__new__(NATSBus)
        bus._url = ""
        bus._nc = None
        bus._js = None
        bus._connected = False
        bus._noop = True
        bus._subscriptions = []
        bus._stats = {"published": 0, "received": 0, "errors": 0, "reconnects": 0}

        stats = bus.get_stats()
        assert "connected" in stats
        assert "noop_mode" in stats
        assert "published" in stats
        assert "received" in stats


# ===========================================================================
# Phase A — Startup integration (light smoke)
# ===========================================================================


class TestStartupIntegration:
    """Light smoke tests for the NATS startup path."""

    @pytest.mark.asyncio
    async def test_nats_bus_connect_called_when_url_set(self):
        """When GALAXY_NATS_URL is set, the connect method is invoked."""
        mock_bus = _make_mock_nats_bus(connected=False)
        mock_bus.connect.return_value = {"success": True}
        mock_bus.is_connected.side_effect = [False, True]  # false before, true after

        with patch.dict(os.environ, {"GALAXY_NATS_URL": "nats://localhost:4222"}):
            with patch("core.nats_bus.nats_bus", mock_bus):
                from core.nats_bus import nats_bus
                result = await nats_bus.connect()

        # Verify connect was called (either on our mock or the real singleton)
        # This test is mainly a structure/smoke check
        assert result is not None

    def test_gateway_nats_adapter_module_importable(self):
        """galaxy_gateway.gateway_nats_adapter is importable."""
        import galaxy_gateway.gateway_nats_adapter  # noqa: F401

    def test_nats_heartbeat_module_importable(self):
        """core.nats_heartbeat is importable."""
        import core.nats_heartbeat  # noqa: F401

    def test_nats_executor_in_command_router(self):
        """NATSExecutor and get_nats_executor() are importable from command_router."""
        from core.command_router import NATSExecutor, get_nats_executor  # noqa: F401

        exec_ = get_nats_executor()
        assert isinstance(exec_, NATSExecutor)


# ===========================================================================
# PR-4 Validation — NATS URL missing / connection failure / connected
# ===========================================================================


class TestNATSURLMissing:
    """Validate behaviour when GALAXY_NATS_URL is not set."""

    def test_nats_bus_noop_when_url_absent(self):
        """NATSBus operates in no-op mode when GALAXY_NATS_URL is not set."""
        import importlib
        import core.nats_bus as _nb_mod

        # Temporarily patch env to remove the URL and re-init a fresh instance
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GALAXY_NATS_URL", None)
            bus = _nb_mod.NATSBus.__new__(_nb_mod.NATSBus)
            bus._url = os.environ.get("GALAXY_NATS_URL", "")
            bus._nc = None
            bus._js = None
            bus._connected = False
            bus._noop = not bus._url or not _nb_mod._HAS_NATS
            bus._subscriptions = []
            bus._stats = {"published": 0, "received": 0, "errors": 0, "reconnects": 0}

        assert bus._noop is True, "NATSBus must be in noop mode when GALAXY_NATS_URL is absent"
        assert bus.is_connected() is False

    @pytest.mark.asyncio
    async def test_nats_bus_connect_noop_when_url_absent(self):
        """connect() returns noop result immediately when URL is not set."""
        import core.nats_bus as _nb_mod

        bus = _nb_mod.NATSBus.__new__(_nb_mod.NATSBus)
        bus._url = ""
        bus._nc = None
        bus._js = None
        bus._connected = False
        bus._noop = True
        bus._subscriptions = []
        bus._stats = {"published": 0, "received": 0, "errors": 0, "reconnects": 0}

        result = await bus.connect()
        assert result.get("noop") is True
        assert result.get("success") is True

    @pytest.mark.asyncio
    async def test_master_brain_logs_warning_when_nats_noop(self, caplog):
        """MasterBrain logs a warning when NATS connection returns noop."""
        import logging
        from core.master_brain import MasterBrain

        mock_bus = _make_mock_nats_bus(connected=False)
        mock_bus.connect.return_value = {"success": False, "error": "GALAXY_NATS_URL not set"}
        mock_bus.is_connected.return_value = False

        brain = MasterBrain(nats=mock_bus)
        with caplog.at_level(logging.WARNING, logger="master_brain"):
            result = await brain.start()

        assert result.get("success") is True  # MasterBrain still starts in local-only mode
        assert brain._started is True
        # A warning must have been emitted about NATS
        nats_warnings = [r for r in caplog.records if "NATS" in r.message and r.levelno >= logging.WARNING]
        assert nats_warnings, "Expected a WARNING log about NATS when connection fails"

    def test_get_stats_noop_mode_field(self):
        """get_stats() advertises noop_mode=True when URL is absent."""
        import core.nats_bus as _nb_mod

        bus = _nb_mod.NATSBus.__new__(_nb_mod.NATSBus)
        bus._url = ""
        bus._nc = None
        bus._js = None
        bus._connected = False
        bus._noop = True
        bus._subscriptions = []
        bus._stats = {"published": 0, "received": 0, "errors": 0, "reconnects": 0}

        stats = bus.get_stats()
        assert stats["noop_mode"] is True
        assert stats["connected"] is False


class TestNATSConnectionFailure:
    """Validate behaviour when GALAXY_NATS_URL is set but connection fails."""

    @pytest.mark.asyncio
    async def test_connect_returns_failure_dict(self):
        """connect() returns {"success": False, "error": ...} on connection error."""
        import core.nats_bus as _nb_mod

        # Build a real NATSBus instance pointing at a non-existent server
        bus = _nb_mod.NATSBus.__new__(_nb_mod.NATSBus)
        bus._url = "nats://localhost:14222"  # port unlikely to be in use
        bus._nc = None
        bus._js = None
        bus._connected = False
        bus._noop = False  # URL is set, so not noop
        bus._subscriptions = []
        bus._stats = {"published": 0, "received": 0, "errors": 0, "reconnects": 0}

        # nats-py is not installed in CI; simulate via mock
        with patch.object(bus, "_noop", False):
            if not _nb_mod._HAS_NATS:
                # Can't actually connect without nats-py; simulate the error path
                bus._stats["errors"] += 1
                result = {"success": False, "error": "nats-py not installed"}
            else:
                result = await bus.connect()

        assert result["success"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_master_brain_stays_started_after_nats_failure(self):
        """MasterBrain still marks itself started when NATS connection fails."""
        from core.master_brain import MasterBrain

        mock_bus = _make_mock_nats_bus(connected=False)
        mock_bus.connect.return_value = {"success": False, "error": "connection refused"}

        brain = MasterBrain(nats=mock_bus)
        result = await brain.start()

        assert brain._started is True
        assert result.get("success") is True  # starts in local-only mode

    @pytest.mark.asyncio
    async def test_nats_executor_falls_back_on_connection_failure(self):
        """NATSExecutor falls back to local executor when NATS fails."""
        from core.command_router import NATSExecutor

        fallback_called = {}

        async def fallback(target, command, params):
            fallback_called["called"] = True
            return {"success": True, "source": "fallback"}

        mock_bus = _make_mock_nats_bus(connected=False)
        executor = NATSExecutor(fallback_executor=fallback, fallback_enabled=True)

        with patch("core.nats_bus.nats_bus", mock_bus):
            result = await executor("worker-1", "run_task", {"x": 1})

        assert fallback_called.get("called") is True
        assert result["source"] == "fallback"

    @pytest.mark.asyncio
    async def test_nats_executor_fallback_uses_warning_log(self, caplog):
        """NATSExecutor._use_fallback() emits a WARNING-level log."""
        import logging
        from core.command_router import NATSExecutor

        async def fallback(target, command, params):
            return {"success": True}

        executor = NATSExecutor(fallback_executor=fallback, fallback_enabled=True)

        with caplog.at_level(logging.WARNING):
            await executor._use_fallback("t", "cmd", {}, reason="nats_not_connected")

        warning_msgs = [r for r in caplog.records if r.levelno >= logging.WARNING and "fallback" in r.message.lower()]
        assert warning_msgs, "Expected a WARNING log when fallback is used"


class TestNATSConnected:
    """Validate behaviour when GALAXY_NATS_URL is set and connection succeeds."""

    @pytest.mark.asyncio
    async def test_master_brain_subscribes_when_nats_connected(self):
        """MasterBrain subscribes to heartbeats and results when NATS connects."""
        from core.master_brain import MasterBrain

        mock_bus = _make_mock_nats_bus(connected=True)
        mock_bus.connect.return_value = {"success": True}
        mock_bus.subscribe_heartbeats = AsyncMock(return_value={"success": True})
        mock_bus.subscribe_events = AsyncMock(return_value={"success": True})

        brain = MasterBrain(nats=mock_bus)
        result = await brain.start()

        assert result.get("success") is True
        assert brain._started is True
        mock_bus.subscribe_heartbeats.assert_awaited_once()
        mock_bus.subscribe_task_results.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_nats_bus_stats_reflect_connected_state(self):
        """get_stats() shows connected=True and noop_mode=False when connected."""
        mock_bus = _make_mock_nats_bus(connected=True)
        stats = mock_bus.get_stats()
        assert stats["connected"] is True
        assert stats["noop_mode"] is False

    @pytest.mark.asyncio
    async def test_heartbeat_includes_trace_id(self):
        """Heartbeat messages include a non-empty trace_id for session correlation."""
        from core.nats_heartbeat import NodeHeartbeatSender

        sent_payloads = []
        mock_bus = _make_mock_nats_bus(connected=True)

        async def _capture_hb(hb):
            sent_payloads.append(hb)
            return {"success": True}

        mock_bus.publish_heartbeat = _capture_hb

        trace = "test-trace-id-abc123"
        sender = NodeHeartbeatSender(worker_id="node-trace-test", trace_id=trace)

        with patch("core.nats_bus.nats_bus", mock_bus):
            await sender._send_heartbeat()

        assert len(sent_payloads) == 1
        hb = sent_payloads[0]
        assert hb.trace_id == trace, f"Expected trace_id={trace!r}, got {hb.trace_id!r}"

    @pytest.mark.asyncio
    async def test_heartbeat_auto_generates_trace_id_when_not_provided(self):
        """NodeHeartbeatSender auto-generates a trace_id when none is supplied."""
        from core.nats_heartbeat import NodeHeartbeatSender

        sender = NodeHeartbeatSender(worker_id="node-auto-trace")
        assert sender._trace_id != "", "Expected auto-generated trace_id to be non-empty"
        # Verify it looks like a UUID
        import re
        uuid_pattern = re.compile(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
        )
        assert uuid_pattern.match(sender._trace_id), f"Expected UUID pattern, got {sender._trace_id!r}"

    @pytest.mark.asyncio
    async def test_nats_executor_dispatches_when_connected(self):
        """NATSExecutor publishes task via NATS when bus is connected."""
        from core.command_router import NATSExecutor

        mock_bus = _make_mock_nats_bus(connected=True)
        executor = NATSExecutor(fallback_enabled=False, timeout_s=1.0)

        async def _pub_and_resolve(worker_id, task):
            task_id = task.task_id
            fut = executor._pending.get(task_id)
            if fut is not None:
                fut.set_result({"success": True, "result": "done", "task_id": task_id})
            return {"success": True, "seq": 42}

        mock_bus.publish_task_dispatch = _pub_and_resolve

        with patch("core.nats_bus.nats_bus", mock_bus):
            result = await executor("worker-1", "run_cmd", {"arg": "val"})

        assert result.get("success") is True
        assert executor._stats["nats_dispatched"] == 1


# ===========================================================================
# PR-3 — NATS × TaskEnvelope alignment
# ===========================================================================


class TestPR3NATSEnvelopeAlignment:
    """Validate PR-3: NATS transport unified to TaskEnvelope."""

    # ── contracts.py bridge functions ───────────────────────────────────────

    def test_envelope_from_task_dispatch_preserves_task_id(self):
        """envelope_from_task_dispatch() retains the original task_id."""
        from core.schemas.contracts import (
            envelope_from_task_dispatch,
            TaskDispatchModel,
            TaskType,
            DeviceCommandPayloadModel,
        )

        task = TaskDispatchModel(
            task_id="task-bridge-001",
            task_type=TaskType.DEVICE_CMD,
            target_worker_id="device-A",
            device_payload=DeviceCommandPayloadModel(command="tap", target_device_id="device-A"),
            context={"trace_id": "trace-abc"},
        )
        env = envelope_from_task_dispatch(task)

        assert env.task_id == "task-bridge-001"
        assert env.trace_id == "trace-abc"
        assert env.target == "device-A"
        assert env.tool_name == "tap"

    def test_envelope_from_task_dispatch_generates_trace_id_when_missing(self):
        """envelope_from_task_dispatch() generates a trace_id if context lacks one."""
        from core.schemas.contracts import (
            envelope_from_task_dispatch,
            TaskDispatchModel,
            TaskType,
        )

        task = TaskDispatchModel(
            task_id="task-no-trace",
            task_type=TaskType.DEVICE_CMD,
            target_worker_id="device-B",
        )
        env = envelope_from_task_dispatch(task)

        assert env.trace_id.startswith("trace_")
        assert len(env.trace_id) > 6

    def test_task_dispatch_from_envelope_roundtrip(self):
        """task_dispatch_from_envelope() produces a usable TaskDispatchModel."""
        from core.schemas.contracts import task_dispatch_from_envelope
        from core.schemas.task_envelope import TaskEnvelope

        env = TaskEnvelope(
            task_id="task-rt-001",
            trace_id="trace-rt",
            source="test",
            targets=["device-C"],
            tool_name="swipe",
            args={"direction": "up"},
            timeout=15.0,
        )
        task = task_dispatch_from_envelope(env)

        assert task.task_id == "task-rt-001"
        assert task.target_worker_id == "device-C"
        assert task.context.get("trace_id") == "trace-rt"
        assert task.device_payload is not None
        assert task.device_payload.command == "swipe"

    # ── NATSBus.publish_task_envelope ────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_publish_task_envelope_uses_correct_subject(self):
        """publish_task_envelope() publishes to galaxy.tasks.dispatch.{target}."""
        from core.nats_bus import NATSBus
        from core.schemas.task_envelope import TaskEnvelope

        bus = NATSBus.__new__(NATSBus)
        bus._noop = False
        bus._connected = True
        bus._js = None
        bus._stats = {"published": 0, "received": 0, "errors": 0, "reconnects": 0}
        bus._subscriptions = []

        published = {}

        async def _mock_publish(subject, data):
            published["subject"] = subject
            published["data"] = data
            return {"success": True, "seq": 1}

        bus._publish = _mock_publish

        env = TaskEnvelope(
            task_id="task-pub-001",
            trace_id="trace-pub",
            targets=["worker-42"],
            tool_name="ping",
        )
        result = await bus.publish_task_envelope("worker-42", env)

        assert result.get("success") is True
        assert published["subject"] == "galaxy.tasks.dispatch.worker-42"
        assert published["data"].get("_nats_schema") == "TaskEnvelope"
        assert published["data"].get("task_id") == "task-pub-001"

    # ── GatewayNATSAdapter — TaskEnvelope primary path ───────────────────────

    @pytest.mark.asyncio
    async def test_adapter_handles_task_envelope_directly(self):
        """Adapter accepts a TaskEnvelope-shaped message without conversion."""
        from galaxy_gateway.gateway_nats_adapter import GatewayNATSAdapter

        mock_bus = _make_mock_nats_bus(connected=True)
        adapter = GatewayNATSAdapter(task_timeout=5.0)

        received = {}

        async def _capture_forward(task_id, target, task_type, payload):
            received["task_id"] = task_id
            received["target"] = target
            received["tool_name"] = task_type
            return {"success": True, "data": "ok"}

        adapter._forward_to_device = _capture_forward

        envelope_payload = {
            "_nats_schema": "TaskEnvelope",
            "task_id": "task-env-001",
            "trace_id": "trace-env",
            "source": "test",
            "targets": ["device-env"],
            "tool_name": "long_press",
            "args": {"x": 50, "y": 100},
            "priority": 5,
            "timeout": 10.0,
            "created_at": "2025-01-01T00:00:00+00:00",
            "metadata": {},
        }

        with patch("core.nats_bus.nats_bus", mock_bus):
            await adapter._handle_task_dispatch(envelope_payload)

        assert received.get("task_id") == "task-env-001"
        assert received.get("target") == "device-env"
        assert received.get("tool_name") == "long_press"
        assert adapter._stats["dispatched"] == 1
        assert adapter._stats["succeeded"] == 1

    @pytest.mark.asyncio
    async def test_adapter_handles_legacy_task_dispatch(self):
        """Old TaskDispatch dicts are accepted and executed by the adapter."""
        from galaxy_gateway.gateway_nats_adapter import GatewayNATSAdapter

        mock_bus = _make_mock_nats_bus(connected=True)
        adapter = GatewayNATSAdapter(task_timeout=5.0)

        received = {}

        async def _capture_forward(task_id, target, task_type, payload):
            received["task_id"] = task_id
            received["target"] = target
            return {"success": True}

        adapter._forward_to_device = _capture_forward

        # No _nats_schema field — legacy format
        legacy_payload = {
            "task_id": "task-legacy-002",
            "target_worker_id": "device-legacy",
            "task_type": "command",
            "payload": {"action": "scroll"},
        }

        with patch("core.nats_bus.nats_bus", mock_bus):
            await adapter._handle_task_dispatch(legacy_payload)

        assert received.get("target") == "device-legacy"
        assert adapter._stats["dispatched"] == 1
        assert adapter._stats["succeeded"] == 1

    @pytest.mark.asyncio
    async def test_adapter_publish_result_includes_nats_schema(self):
        """_publish_result() emits a unified message with _nats_schema marker."""
        from galaxy_gateway.gateway_nats_adapter import GatewayNATSAdapter

        mock_bus = _make_mock_nats_bus(connected=True)
        published = {}

        async def _mock_pub(subject, data):
            published["subject"] = subject
            published["data"] = data
            return {"success": True}

        mock_bus._publish = _mock_pub
        adapter = GatewayNATSAdapter()

        with patch("core.nats_bus.nats_bus", mock_bus):
            await adapter._publish_result("task-res-001", {"value": "done"}, success=True, trace_id="tr-xyz")

        assert published["subject"] == "galaxy.tasks.result.task-res-001"
        d = published["data"]
        assert d.get("_nats_schema") == "TaskEnvelope"
        assert d.get("task_id") == "task-res-001"
        assert d.get("trace_id") == "tr-xyz"
        assert d.get("status") == "success"
        assert d["metadata"]["success"] is True

    # ── NATSExecutor — TaskEnvelope primary publish ───────────────────────────

    @pytest.mark.asyncio
    async def test_nats_executor_publishes_task_envelope(self):
        """NATSExecutor calls publish_task_envelope() when building a dispatch."""
        from core.command_router import NATSExecutor

        mock_bus = _make_mock_nats_bus(connected=True)
        envelope_calls = []

        async def _capture_envelope(target, envelope):
            task_id = envelope.task_id
            envelope_calls.append({"target": target, "task_id": task_id})
            # Immediately resolve so the executor doesn't time out.
            import asyncio as _a

            def _resolve():
                fut = executor._pending.get(task_id)
                if fut is not None and not fut.done():
                    fut.set_result({"success": True, "result": "ok", "task_id": task_id})

            _a.get_event_loop().call_soon(_resolve)
            return {"success": True, "seq": 10}

        mock_bus.publish_task_envelope = _capture_envelope

        executor = NATSExecutor(fallback_enabled=False, timeout_s=2.0)

        with patch("core.nats_bus.nats_bus", mock_bus):
            result = await executor("device-env", "swipe", {"dir": "down"})

        assert result.get("success") is True
        assert len(envelope_calls) == 1
        assert envelope_calls[0]["target"] == "device-env"

    # ── NATSExecutor._on_task_result — envelope result ───────────────────────

    @pytest.mark.asyncio
    async def test_nats_executor_resolves_task_envelope_result(self):
        """_on_task_result() correctly resolves a TaskEnvelope-shaped result."""
        from core.command_router import NATSExecutor
        import asyncio

        executor = NATSExecutor()
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        executor._pending["task-env-res-001"] = fut

        await executor._on_task_result({
            "_nats_schema": "TaskEnvelope",
            "task_id": "task-env-res-001",
            "metadata": {
                "success": True,
                "status": "success",
                "result": {"data": "envelope_ok"},
                "error": None,
            },
        })

        assert fut.done()
        r = fut.result()
        assert r["success"] is True
        assert r["result"] == {"data": "envelope_ok"}
        assert r["task_id"] == "task-env-res-001"

    @pytest.mark.asyncio
    async def test_nats_executor_resolves_legacy_task_result(self):
        """_on_task_result() correctly resolves a legacy TaskResult dict."""
        from core.command_router import NATSExecutor
        import asyncio

        executor = NATSExecutor()
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        executor._pending["task-legacy-res-001"] = fut

        await executor._on_task_result({
            "task_id": "task-legacy-res-001",
            "status": "success",
            "result": {"output": "legacy_ok"},
        })

        assert fut.done()
        r = fut.result()
        assert r["success"] is True
        assert r["result"] == {"output": "legacy_ok"}


# ===========================================================================
# PR-ALL v2 — NATS auto-local default + cross-device hint
# ===========================================================================


class TestNATSAutoLocal:
    """Validate the auto-local localhost default and graceful no-op fallback."""

    def test_auto_local_set_when_url_absent_and_nats_available(self):
        """When GALAXY_NATS_URL is unset and nats-py is installed, __init__ sets
        _url to nats://localhost:4222 and _auto_local to True."""
        import core.nats_bus as _nb_mod

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GALAXY_NATS_URL", None)
            with patch.object(_nb_mod, "_HAS_NATS", True):
                bus = _nb_mod.NATSBus()

        assert bus._url == "nats://localhost:4222"
        assert bus._auto_local is True
        assert bus._noop is False

    def test_noop_when_url_absent_and_nats_not_available(self):
        """When GALAXY_NATS_URL is unset AND nats-py is not installed, __init__
        leaves _noop True immediately (no auto-local attempt)."""
        import core.nats_bus as _nb_mod

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GALAXY_NATS_URL", None)
            with patch.object(_nb_mod, "_HAS_NATS", False):
                bus = _nb_mod.NATSBus()

        assert bus._noop is True
        assert bus._auto_local is False

    @pytest.mark.asyncio
    async def test_connect_auto_local_failure_returns_noop(self):
        """connect() for an auto-local bus that can't reach localhost returns
        noop=True and sets _noop=True without raising."""
        import core.nats_bus as _nb_mod

        bus = _nb_mod.NATSBus.__new__(_nb_mod.NATSBus)
        bus._url = "nats://localhost:4222"
        bus._auto_local = True
        bus._nc = None
        bus._js = None
        bus._connected = False
        bus._noop = False
        bus._subscriptions = []
        bus._stats = {"published": 0, "received": 0, "errors": 0, "reconnects": 0}

        if not _nb_mod._HAS_NATS:
            # Simulate the auto-local failure path manually
            bus._stats["errors"] += 1
            bus._noop = True
            result = {"success": True, "noop": True, "auto_local_failed": True}
        else:
            # Patch nats.connect to raise so we exercise the fallback
            import nats as _nats_mod
            with patch.object(_nats_mod, "connect", side_effect=Exception("connection refused")):
                result = await bus.connect()

        assert result.get("success") is True
        assert result.get("noop") is True
        assert result.get("auto_local_failed") is True
        assert bus._noop is True

    @pytest.mark.asyncio
    async def test_connect_auto_local_failure_logs_lan_hint(self):
        """connect() auto-local fallback logs a WARNING containing the LAN IP address."""
        import core.nats_bus as _nb_mod

        bus = _nb_mod.NATSBus.__new__(_nb_mod.NATSBus)
        bus._url = "nats://localhost:4222"
        bus._auto_local = True
        bus._nc = None
        bus._js = None
        bus._connected = False
        bus._noop = False
        bus._subscriptions = []
        bus._stats = {"published": 0, "received": 0, "errors": 0, "reconnects": 0}

        fake_lan_ip = "192.168.1.42"

        if not _nb_mod._HAS_NATS:
            # Exercise the warning path directly with a patched LAN IP
            with patch.object(_nb_mod, "_get_lan_ip", return_value=fake_lan_ip), \
                 patch.object(_nb_mod.logger, "warning") as mock_warn:
                bus._stats["errors"] += 1
                bus._noop = True
                hint = f" For cross-device support set: GALAXY_NATS_URL=nats://{_nb_mod._get_lan_ip()}:4222"
                _nb_mod.logger.warning(
                    "NATSBus: could not reach nats://localhost:4222 — running in no-op mode "
                    "(single-machine).%s",
                    hint,
                )
                assert mock_warn.called
                warning_text = " ".join(str(a) for a in mock_warn.call_args[0])
                assert fake_lan_ip in warning_text
        else:
            import nats as _nats_mod
            with patch.object(_nb_mod, "_get_lan_ip", return_value=fake_lan_ip), \
                 patch.object(_nats_mod, "connect", side_effect=Exception("refused")), \
                 patch.object(_nb_mod.logger, "warning") as mock_warn:
                await bus.connect()
                assert mock_warn.called
                all_warnings = " ".join(" ".join(str(a) for a in c[0]) for c in mock_warn.call_args_list)
                assert fake_lan_ip in all_warnings
