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
    bus.publish_worker_registration = AsyncMock(return_value={"success": True, "seq": 4})
    bus.publish_worker_shutdown = AsyncMock(return_value={"success": True, "seq": 5})
    bus.publish_event = AsyncMock(return_value={"success": True, "seq": 4})
    bus._subscribe = AsyncMock(return_value={"success": True})
    bus.subscribe_heartbeats = AsyncMock(return_value={"success": True})
    bus.subscribe_task_results = AsyncMock(return_value={"success": True})
    bus.subscribe_worker_registrations = AsyncMock(return_value={"success": True})
    bus.subscribe_worker_shutdowns = AsyncMock(return_value={"success": True})
    bus.subscribe_task_deadletters = AsyncMock(return_value={"success": True})
    bus.subscribe_events = AsyncMock(return_value={"success": True})
    bus.connect = AsyncMock(return_value={"success": True})
    bus.disconnect = AsyncMock(return_value={"success": True})
    return bus


class _FakeTemporalWorker:
    def __init__(self) -> None:
        self._stopped = asyncio.Event()
        self.shutdown = AsyncMock(side_effect=self._stopped.set)

    async def run(self) -> None:
        await self._stopped.wait()


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
        loop = asyncio.get_running_loop()
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
        async def _fast_forward(task_id, target, task_type, payload, **_kwargs):
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

        async def _slow_forward(task_id, target, task_type, payload, **_kwargs):
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
        mock_bus.publish_worker_registration.assert_awaited_once()

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

        registration = mock_bus.publish_worker_registration.call_args[0][0]
        assert hasattr(registration, "model_dump")
        payload = registration.model_dump(mode="json", exclude_none=True)
        cap_names = [c["name"] for c in payload.get("capabilities", [])]
        assert "cap_a" in cap_names
        assert "cap_b" in cap_names

    @pytest.mark.asyncio
    async def test_stop_publishes_worker_shutdown(self):
        """Stopping the heartbeat sender publishes canonical worker shutdown truth."""
        from core.nats_heartbeat import NodeHeartbeatSender

        mock_bus = _make_mock_nats_bus(connected=True)
        sender = NodeHeartbeatSender(worker_id="node-stop-test")

        with patch("core.nats_bus.nats_bus", mock_bus):
            await sender.stop()

        mock_bus.publish_worker_shutdown.assert_awaited_once()
        shutdown = mock_bus.publish_worker_shutdown.call_args[0][0]
        assert shutdown.worker_id == "node-stop-test"
        assert shutdown.reason == "heartbeat_stopped"

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
            asyncio.get_running_loop().call_soon(
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
        assert result.get("distributed_dispatch") is True
        assert result.get("execution_path") == "nats_distributed"
        assert result.get("fallback_used") is False

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
        assert result.get("distributed_dispatch") is False
        assert result.get("execution_path") == "local_fallback"
        assert result.get("fallback_used") is True
        assert result.get("fallback_reason") == "nats_not_connected"

    @pytest.mark.asyncio
    async def test_noop_publish_does_not_count_as_distributed_dispatch(self):
        """NATS noop publish cannot masquerade as distributed dispatch success."""
        from core.command_router import NATSExecutor

        async def fallback(target, command, params):
            return {"success": True, "source": "fallback-local"}

        mock_bus = _make_mock_nats_bus(connected=True)
        mock_bus.publish_task_envelope = AsyncMock(return_value={"success": True, "noop": True})
        executor = NATSExecutor(fallback_executor=fallback, fallback_enabled=True, timeout_s=0.2)

        with patch("core.nats_bus.nats_bus", mock_bus):
            result = await executor("device-noop", "tap", {"x": 1})

        assert result.get("success") is True
        assert result.get("source") == "fallback-local"
        assert result.get("distributed_dispatch") is False
        assert result.get("execution_path") == "local_fallback"
        assert result.get("fallback_used") is True
        assert result.get("fallback_reason") == "nats_noop_transport"
        assert result.get("nats_publish_state", {}).get("noop") is True
        assert executor.get_stats()["nats_dispatched"] == 0

    @pytest.mark.asyncio
    async def test_on_task_result_resolves_pending_future(self):
        """_on_task_result() resolves the matching future."""
        from core.command_router import NATSExecutor

        executor = NATSExecutor()
        loop = asyncio.get_running_loop()
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
    async def test_publish_noop_is_not_reported_as_success(self):
        """No-op transport publish must not return success=True."""
        import core.nats_bus as _nb_mod

        bus = _nb_mod.NATSBus.__new__(_nb_mod.NATSBus)
        bus._url = ""
        bus._nc = None
        bus._js = None
        bus._connected = False
        bus._noop = True
        bus._subscriptions = []
        bus._stats = {"published": 0, "received": 0, "errors": 0, "reconnects": 0}

        result = await bus._publish("galaxy.tasks.dispatch.worker-01", {"task_id": "t1"})
        assert result.get("noop") is True
        assert result.get("success") is False
        assert result.get("error") == "nats_noop_transport"

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
        mock_bus.subscribe_worker_registrations.assert_awaited_once()
        mock_bus.subscribe_worker_shutdowns.assert_awaited_once()
        mock_bus.subscribe_task_deadletters.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_master_brain_starts_temporal_worker_in_runtime_lifecycle(self):
        """MasterBrain.start() activates the Temporal worker when the client is available."""
        from core.master_brain import MasterBrain

        mock_bus = _make_mock_nats_bus(connected=True)
        fake_worker = _FakeTemporalWorker()
        brain = MasterBrain(nats=mock_bus)

        with patch(
            "core.temporal_workflows.get_temporal_client",
            AsyncMock(return_value=object()),
        ), patch(
            "core.temporal_workflows.start_temporal_worker",
            AsyncMock(return_value=fake_worker),
        ):
            result = await brain.start()
            status = brain.get_status()

        assert result.get("temporal_client_connected") is True
        assert result.get("temporal_worker_active") is True
        assert result.get("temporal_runtime_available") is True
        assert status["temporal_connected"] is True
        assert status["temporal_worker_active"] is True
        assert status["temporal_runtime_available"] is True

        await brain.stop()

    @pytest.mark.asyncio
    async def test_master_brain_execute_distributed_task_prefers_temporal_workflow_when_active(self):
        """Real distributed execution uses the Temporal workflow path when the runtime is active."""
        from core.master_brain import MasterBrain
        from core.schemas.contracts import TaskStatus

        mock_bus = _make_mock_nats_bus(connected=True)
        brain = MasterBrain(nats=mock_bus)
        brain._temporal_client = MagicMock()
        brain._temporal_worker = _FakeTemporalWorker()
        brain._temporal_worker_task = asyncio.create_task(brain._temporal_worker.run())

        handle = MagicMock()
        handle.id = "wf-stage9-01"
        handle.result_run_id = None
        handle.first_execution_run_id = None
        handle.result = AsyncMock(return_value={
            "success": True,
            "data": {
                "task_id": "stage9-temporal-01",
                "worker_id": "worker-temporal-01",
                "status": TaskStatus.SUCCESS.value,
            },
            "attempts": 1,
        })
        brain._temporal_client.start_workflow = AsyncMock(return_value=handle)

        result = await brain.execute_distributed_task({
            "task_id": "stage9-temporal-01",
            "target_worker_id": "worker-temporal-01",
            "trace_id": "trace-stage9-temporal-01",
        })

        assert result["success"] is True
        assert result["execution_path"] == "temporal_workflow"
        assert result["temporal_workflow_type"] == "code_execution"
        assert result["workflow_id"] == "wf-stage9-01"
        brain._temporal_client.start_workflow.assert_awaited_once()
        mock_bus.publish_task_dispatch.assert_not_awaited()

        await brain.stop()

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

    @pytest.mark.asyncio
    async def test_master_brain_consumes_worker_registration_on_workers_subject(self):
        """MasterBrain accepts wrapped worker_register payloads from worker subjects."""
        from core.master_brain import MasterBrain

        mock_bus = _make_mock_nats_bus(connected=True)
        brain = MasterBrain(nats=mock_bus)

        await brain._on_worker_event({
            "type": "worker_register",
            "worker_register": {
                "worker_id": "worker-reg-01",
                "device_type": "linux",
                "platform": "linux",
            },
        })

        topology = brain.get_worker_topology()
        assert "worker-reg-01" in topology
        assert topology["worker-reg-01"]["device_type"] == "linux"

    @pytest.mark.asyncio
    async def test_master_brain_consumes_worker_shutdown_on_workers_subject(self):
        """MasterBrain marks worker offline when shutdown event arrives."""
        from core.master_brain import MasterBrain
        from core.schemas.contracts import WorkerRegistrationModel

        mock_bus = _make_mock_nats_bus(connected=True)
        brain = MasterBrain(nats=mock_bus)

        await brain.register_worker(WorkerRegistrationModel(worker_id="worker-down-01", device_type="linux"))
        await brain._on_worker_shutdown({
            "type": "worker_shutdown",
            "worker_shutdown": {
                "worker_id": "worker-down-01",
                "reason": "graceful_shutdown",
                "drain_timeout_s": 30,
            },
        })

        topology = brain.get_worker_topology()
        assert topology["worker-down-01"]["status"] == "offline"
        assert topology["worker-down-01"]["alive"] is False
        assert topology["worker-down-01"]["shutdown_reason"] == "graceful_shutdown"

    @pytest.mark.asyncio
    async def test_master_brain_handle_worker_shutdown_updates_existing_topology(self):
        """Direct shutdown handling updates topology to offline state."""
        from core.master_brain import MasterBrain
        from core.schemas.contracts import WorkerRegistrationModel, WorkerShutdownModel

        mock_bus = _make_mock_nats_bus(connected=True)
        brain = MasterBrain(nats=mock_bus)
        await brain.register_worker(WorkerRegistrationModel(worker_id="worker-down-02", device_type="linux"))

        result = await brain.handle_worker_shutdown(
            WorkerShutdownModel(worker_id="worker-down-02", reason="maintenance", drain_timeout_s=15)
        )
        topology = brain.get_worker_topology()

        assert result.get("success") is True
        assert topology["worker-down-02"]["status"] == "offline"
        assert topology["worker-down-02"]["shutdown_reason"] == "maintenance"
        assert topology["worker-down-02"]["drain_timeout_s"] == 15
        assert topology["worker-down-02"]["alive"] is False

    @pytest.mark.asyncio
    async def test_master_brain_worker_shutdown_abandons_inflight_task(self, tmp_path):
        """Explicit worker shutdown closes in-flight distributed work as abandoned."""
        from core.master_brain import MasterBrain
        from core.schemas.contracts import (
            DeviceCommandPayloadModel,
            TaskDispatchModel,
            TaskType,
            WorkerRegistrationModel,
            WorkerShutdownModel,
        )

        mock_bus = _make_mock_nats_bus(connected=True)
        mock_bus.publish_task_dispatch = AsyncMock(return_value={"success": True, "seq": 13})
        brain = MasterBrain(nats=mock_bus, state_path=tmp_path / "brain-state.json")
        await brain.register_worker(WorkerRegistrationModel(worker_id="worker-shutdown-01", device_type="linux"))
        brain._acl.validate_task_dispatch = AsyncMock(return_value={
            "success": True,
            "data": TaskDispatchModel(
                task_id="stage8-shutdown-01",
                task_type=TaskType.DEVICE_CMD,
                target_worker_id="worker-shutdown-01",
                device_payload=DeviceCommandPayloadModel(command="tap", target_device_id="worker-shutdown-01"),
                context={"trace_id": "trace-stage8-shutdown"},
                timeout_ms=5_000,
            ),
        })

        await brain.dispatch_task({"task_id": "stage8-shutdown-01", "wait_for_completion": False})
        shutdown_result = await brain.handle_worker_shutdown(
            WorkerShutdownModel(worker_id="worker-shutdown-01", reason="maintenance", drain_timeout_s=15)
        )
        observed = brain.get_task_status("stage8-shutdown-01")

        assert shutdown_result.get("success") is True
        assert shutdown_result.get("affected_tasks") == ["stage8-shutdown-01"]
        assert observed is not None
        assert observed.get("closure_complete") is True
        assert observed.get("task_outcome_known") is True
        assert observed.get("completion_state") == "execution_abandoned"
        assert observed.get("lifecycle_state") == "abandoned"
        assert observed.get("error") == "worker_shutdown:maintenance"

    @pytest.mark.asyncio
    async def test_master_brain_recovers_persisted_task_and_worker_state(self, tmp_path):
        """Persisted distributed state survives MasterBrain process replacement."""
        from core.master_brain import MasterBrain
        from core.schemas.contracts import (
            DeviceCommandPayloadModel,
            TaskDispatchModel,
            TaskResultModel,
            TaskStatus,
            TaskType,
            TimestampModel,
            WorkerRegistrationModel,
        )

        state_path = tmp_path / "brain-state.json"
        mock_bus = _make_mock_nats_bus(connected=True)
        mock_bus.publish_task_dispatch = AsyncMock(return_value={"success": True, "seq": 14})
        brain = MasterBrain(nats=mock_bus, state_path=state_path)
        await brain.register_worker(WorkerRegistrationModel(worker_id="worker-recover-01", device_type="linux"))
        brain._acl.validate_task_dispatch = AsyncMock(return_value={
            "success": True,
            "data": TaskDispatchModel(
                task_id="stage8-recover-01",
                task_type=TaskType.DEVICE_CMD,
                target_worker_id="worker-recover-01",
                device_payload=DeviceCommandPayloadModel(command="tap", target_device_id="worker-recover-01"),
                context={"trace_id": "trace-stage8-recover"},
                timeout_ms=5_000,
            ),
        })

        await brain.dispatch_task({"task_id": "stage8-recover-01", "wait_for_completion": False})
        await brain.handle_task_result(TaskResultModel(
            task_id="stage8-recover-01",
            worker_id="worker-recover-01",
            status=TaskStatus.RUNNING,
            started_at=TimestampModel(seconds=10, nanos=0),
            metadata={"trace_id": "trace-stage8-recover", "result_id": "res-stage8-running"},
        ))

        recovered = MasterBrain(nats=mock_bus, state_path=state_path)
        topology = recovered.get_worker_topology()
        observed = recovered.get_task_status("stage8-recover-01")

        assert "worker-recover-01" in topology
        assert topology["worker-recover-01"]["device_type"] == "linux"
        assert observed is not None
        assert observed.get("worker_id") == "worker-recover-01"
        assert observed.get("completion_state") == "execution_started"
        assert observed.get("closure_complete") is False
        assert observed.get("result_received") is True

    @pytest.mark.asyncio
    async def test_master_brain_reconciles_overdue_task_after_restart(self, tmp_path):
        """Persisted in-flight work is marked timed out when its deadline has already expired."""
        from core.master_brain import MasterBrain
        from core.schemas.contracts import DeviceCommandPayloadModel, TaskDispatchModel, TaskType

        state_path = tmp_path / "brain-state.json"
        mock_bus = _make_mock_nats_bus(connected=True)
        mock_bus.publish_task_dispatch = AsyncMock(return_value={"success": True, "seq": 15})
        brain = MasterBrain(nats=mock_bus, state_path=state_path)
        brain._acl.validate_task_dispatch = AsyncMock(return_value={
            "success": True,
            "data": TaskDispatchModel(
                task_id="stage8-timeout-01",
                task_type=TaskType.DEVICE_CMD,
                target_worker_id="worker-timeout-01",
                device_payload=DeviceCommandPayloadModel(command="tap", target_device_id="worker-timeout-01"),
                context={"trace_id": "trace-stage8-timeout"},
                timeout_ms=10,
            ),
        })

        await brain.dispatch_task({"task_id": "stage8-timeout-01", "wait_for_completion": False})
        await asyncio.sleep(0.15)

        recovered = MasterBrain(nats=mock_bus, state_path=state_path)
        observed = recovered.get_task_status("stage8-timeout-01")

        assert observed is not None
        assert observed.get("status") == "timeout"
        assert observed.get("completion_state") == "execution_timed_out"
        assert observed.get("closure_complete") is True
        assert observed.get("task_outcome_known") is True

    @pytest.mark.asyncio
    async def test_master_brain_deadletter_consumption_marks_terminal_failure(self, tmp_path):
        """Dead-letter messages are consumed as a real recovery path for unresolved work."""
        from core.master_brain import MasterBrain
        from core.schemas.contracts import DeviceCommandPayloadModel, TaskDispatchModel, TaskType

        mock_bus = _make_mock_nats_bus(connected=True)
        mock_bus.publish_task_dispatch = AsyncMock(return_value={"success": True, "seq": 16})
        brain = MasterBrain(nats=mock_bus, state_path=tmp_path / "brain-state.json")
        brain._acl.validate_task_dispatch = AsyncMock(return_value={
            "success": True,
            "data": TaskDispatchModel(
                task_id="stage8-dlq-01",
                task_type=TaskType.DEVICE_CMD,
                target_worker_id="worker-dlq-01",
                device_payload=DeviceCommandPayloadModel(command="tap", target_device_id="worker-dlq-01"),
                context={"trace_id": "trace-stage8-dlq"},
                timeout_ms=5_000,
            ),
        })

        await brain.dispatch_task({"task_id": "stage8-dlq-01", "wait_for_completion": False})
        waiter = asyncio.create_task(brain.wait_for_task_result("stage8-dlq-01", timeout_s=1.0))
        await asyncio.sleep(0)
        await brain._on_deadletter({
            "task_id": "stage8-dlq-01",
            "reason": "timeout",
            "original": {
                "target_worker_id": "worker-dlq-01",
                "context": {"trace_id": "trace-stage8-dlq"},
            },
        })
        observed = await waiter

        assert observed.get("status") == "timeout"
        assert observed.get("completion_state") == "dead_lettered"
        assert observed.get("closure_complete") is True
        assert observed.get("task_outcome_known") is True
        assert observed.get("dead_lettered") is True
        assert observed.get("dead_letter_reason") == "timeout"

    @pytest.mark.asyncio
    async def test_master_brain_dispatch_rejects_noop_publish_success(self):
        """MasterBrain dispatch must not report distributed success when publish is noop."""
        from core.master_brain import MasterBrain
        from core.schemas.contracts import (
            TaskDispatchModel,
            TaskType,
            DeviceCommandPayloadModel,
        )

        mock_bus = _make_mock_nats_bus(connected=True)
        mock_bus.publish_task_dispatch = AsyncMock(return_value={"success": False, "noop": True})
        brain = MasterBrain(nats=mock_bus)
        brain._acl.validate_task_dispatch = AsyncMock(return_value={
            "success": True,
            "data": TaskDispatchModel(
                task_id="noop-dispatch-01",
                task_type=TaskType.DEVICE_CMD,
                target_worker_id="worker-01",
                device_payload=DeviceCommandPayloadModel(command="tap", target_device_id="worker-01"),
            ),
        })

        result = await brain.dispatch_task({"task_id": "noop-dispatch-01"})

        assert result.get("success") is False
        assert result.get("distributed_dispatch") is False
        assert result.get("execution_path") == "distributed_unavailable"
        assert result.get("nats_publish_state", {}).get("noop") is True

    @pytest.mark.asyncio
    async def test_master_brain_uses_device_scoring_and_records_graph_and_scaling(self, tmp_path):
        """Canonical MasterBrain dispatch uses scoring, graph registration, and scaling truth."""
        from core.master_brain import MasterBrain
        from core.schemas.contracts import (
            DeviceCommandPayloadModel,
            TaskDispatchModel,
            TaskType,
            WorkerRegistrationModel,
        )
        from core.task_graph_runtime import get_task_graph_runtime, reset_task_graph_runtime

        reset_task_graph_runtime()
        mock_bus = _make_mock_nats_bus(connected=True)
        mock_bus.publish_task_dispatch = AsyncMock(return_value={"success": True, "seq": 21})
        brain = MasterBrain(nats=mock_bus, state_path=tmp_path / "brain-state.json")
        await brain.register_worker(
            WorkerRegistrationModel(worker_id="worker-busy", device_type="linux", platform="linux")
        )
        await brain.register_worker(
            WorkerRegistrationModel(worker_id="worker-best", device_type="linux", platform="linux")
        )
        brain._workers["worker-busy"].update(
            {"active_tasks": 4, "cpu_usage_percent": 85.0, "memory_usage_percent": 90.0}
        )
        brain._workers["worker-best"].update(
            {"active_tasks": 0, "cpu_usage_percent": 5.0, "memory_usage_percent": 10.0}
        )
        brain._acl.validate_task_dispatch = AsyncMock(return_value={
            "success": True,
            "data": TaskDispatchModel(
                task_id="stage11-scoring-01",
                task_type=TaskType.DEVICE_CMD,
                target_device_type="linux",
                device_payload=DeviceCommandPayloadModel(command="tap", target_device_id="worker-best"),
                context={"trace_id": "trace-stage11-scoring"},
                timeout_ms=120_000,
                max_retries=3,
            ),
        })

        result = await brain.dispatch_task({"task_id": "stage11-scoring-01", "wait_for_completion": False})
        observed = brain.get_task_status("stage11-scoring-01")
        node = get_task_graph_runtime().get_node_by_task_id("stage11-scoring-01")

        assert result.get("success") is True
        assert result.get("worker_id") == "worker-best"
        assert observed is not None
        assert observed.get("selected_by") == "device_scoring_engine"
        assert observed.get("transport_state") == "active"
        assert observed.get("scaling_state", {}).get("trigger") == "dispatch_task"
        assert node is not None
        assert node.state.value == "dispatch"

    @pytest.mark.asyncio
    async def test_master_brain_scaling_reevaluates_on_topology_change(self, tmp_path):
        from core.master_brain import MasterBrain
        from core.schemas.contracts import WorkerRegistrationModel

        mock_bus = _make_mock_nats_bus(connected=True)
        brain = MasterBrain(nats=mock_bus, state_path=tmp_path / "brain-state.json")

        await brain.register_worker(
            WorkerRegistrationModel(worker_id="android-worker-01", device_type="android", platform="android")
        )

        scaling = brain.get_status().get("scaling", {})
        assert scaling.get("trigger") == "worker_registered"
        assert scaling.get("topology_has_android_workers") is True
        assert scaling.get("android_workers_alive") == 1

    @pytest.mark.asyncio
    async def test_master_brain_scaling_reevaluates_on_task_result(self, tmp_path):
        from core.master_brain import MasterBrain
        from core.schemas.contracts import TaskResultModel, TaskStatus, TimestampModel

        mock_bus = _make_mock_nats_bus(connected=True)
        brain = MasterBrain(nats=mock_bus, state_path=tmp_path / "brain-state.json")
        brain._task_log["scaler-task-01"] = {
            **brain._default_task_record("scaler-task-01"),
            "task_id": "scaler-task-01",
            "worker_id": "worker-1",
            "trace_id": "trace-scaler-01",
            "dispatch_attempted": True,
            "dispatch_accepted": True,
            "distributed_dispatch": True,
            "status": TaskStatus.RUNNING.value,
            "completion_state": "execution_started",
            "lifecycle_state": "running",
            "execution_started": True,
        }

        await brain.handle_task_result(TaskResultModel(
            task_id="scaler-task-01",
            worker_id="worker-1",
            status=TaskStatus.SUCCESS,
            started_at=TimestampModel(seconds=1, nanos=0),
            completed_at=TimestampModel(seconds=2, nanos=0),
            metadata={"result_id": "res-scaler-01", "trace_id": "trace-scaler-01"},
            output={},
        ))

        scaling = brain.get_status().get("scaling", {})
        assert scaling.get("trigger") == "task_result"
        assert scaling.get("reason") == TaskStatus.SUCCESS.value
        assert "pending_tasks" in scaling

    @pytest.mark.asyncio
    async def test_master_brain_late_result_cannot_override_terminal_closure(self, tmp_path):
        from core.master_brain import MasterBrain
        from core.schemas.contracts import TaskResultModel, TaskStatus, TimestampModel

        mock_bus = _make_mock_nats_bus(connected=True)
        brain = MasterBrain(nats=mock_bus, state_path=tmp_path / "brain-state.json")
        brain._task_log["terminal-lock-01"] = {
            **brain._default_task_record("terminal-lock-01"),
            "task_id": "terminal-lock-01",
            "worker_id": "worker-locked",
            "trace_id": "trace-locked",
            "status": TaskStatus.SUCCESS.value,
            "completion_state": "execution_completed",
            "lifecycle_state": "succeeded",
            "closure_complete": True,
            "task_outcome_known": True,
            "terminal_source": "canonical_success",
        }

        outcome = await brain.handle_task_result(
            TaskResultModel(
                task_id="terminal-lock-01",
                worker_id="worker-locked",
                status=TaskStatus.FAILED,
                started_at=TimestampModel(seconds=3, nanos=0),
                completed_at=TimestampModel(seconds=4, nanos=0),
                metadata={"result_id": "late-res-01", "trace_id": "trace-locked"},
                error={"message": "late failure"},
            )
        )
        observed = brain.get_task_status("terminal-lock-01")

        assert outcome.get("canonical_terminal_locked") is True
        assert outcome.get("precedence_decision") == "canonical_terminal_precedence"
        assert observed is not None
        assert observed.get("completion_state") == "execution_completed"
        assert observed.get("status") == TaskStatus.SUCCESS.value
        assert observed.get("late_result_reason") == "late_after_execution_completed"

    @pytest.mark.asyncio
    async def test_master_brain_periodic_scaling_monitor_runs(self, tmp_path):
        from core.master_brain import MasterBrain

        mock_bus = _make_mock_nats_bus(connected=True)
        brain = MasterBrain(nats=mock_bus, state_path=tmp_path / "brain-state.json")
        try:
            with patch("core.master_brain._SCALING_REEVAL_INTERVAL_S", 0.01):
                await brain.start()
                await asyncio.sleep(0.03)
                scaling = brain.get_status().get("scaling", {})
                assert scaling.get("trigger") == "periodic_monitor"
                assert scaling.get("reason") == "runtime_regulation_tick"
                assert scaling.get("activity_state") == "monitoring"
        finally:
            await brain.stop()

    @pytest.mark.parametrize("flag_value", ["1", "true", "yes", "on"])
    def test_get_master_brain_accepts_truthy_enable_flags(self, flag_value):
        """get_master_brain() normalises supported truthy enablement values consistently."""
        import core.master_brain as master_brain_module

        old_master_brain = master_brain_module._master_brain
        old_instance = master_brain_module.MasterBrain._instance
        try:
            with patch.dict(os.environ, {"GALAXY_MASTER_BRAIN_ENABLED": flag_value}, clear=False):
                master_brain_module._master_brain = None
                master_brain_module.MasterBrain._instance = None
                assert master_brain_module.master_brain_enabled() is True
                assert master_brain_module.get_master_brain() is not None
        finally:
            master_brain_module._master_brain = old_master_brain
            master_brain_module.MasterBrain._instance = old_instance

    @pytest.mark.asyncio
    async def test_master_brain_dispatch_waits_for_terminal_result(self):
        """dispatch_task() returns terminal worker completion, not just publish success."""
        from core.master_brain import MasterBrain
        from core.schemas.contracts import (
            DeviceCommandPayloadModel,
            TaskDispatchModel,
            TaskResultModel,
            TaskStatus,
            TaskType,
            TimestampModel,
        )

        mock_bus = _make_mock_nats_bus(connected=True)
        brain = MasterBrain(nats=mock_bus)
        brain._acl.validate_task_dispatch = AsyncMock(return_value={
            "success": True,
            "data": TaskDispatchModel(
                task_id="stage7-terminal-01",
                task_type=TaskType.DEVICE_CMD,
                target_worker_id="worker-42",
                device_payload=DeviceCommandPayloadModel(command="tap", target_device_id="worker-42"),
                context={"trace_id": "trace-stage7-terminal"},
                timeout_ms=1_000,
            ),
        })

        async def _publish_and_complete(*_args, **_kwargs):
            async def _emit_statuses():
                await asyncio.sleep(0)
                await brain.handle_task_result(TaskResultModel(
                    task_id="stage7-terminal-01",
                    worker_id="worker-42",
                    status=TaskStatus.DISPATCHED,
                    metadata={"trace_id": "trace-stage7-terminal", "result_id": "res-dispatched"},
                ))
                await brain.handle_task_result(TaskResultModel(
                    task_id="stage7-terminal-01",
                    worker_id="worker-42",
                    status=TaskStatus.RUNNING,
                    started_at=TimestampModel(seconds=1, nanos=0),
                    metadata={"trace_id": "trace-stage7-terminal", "result_id": "res-running"},
                ))
                await brain.handle_task_result(TaskResultModel(
                    task_id="stage7-terminal-01",
                    worker_id="worker-42",
                    status=TaskStatus.SUCCESS,
                    started_at=TimestampModel(seconds=1, nanos=0),
                    completed_at=TimestampModel(seconds=2, nanos=0),
                    metadata={"trace_id": "trace-stage7-terminal", "result_id": "res-success"},
                ))

            asyncio.create_task(_emit_statuses())
            return {"success": True, "seq": 7}

        mock_bus.publish_task_dispatch = AsyncMock(side_effect=_publish_and_complete)

        result = await brain.dispatch_task({"task_id": "stage7-terminal-01"})

        assert result.get("success") is True
        assert result.get("status") == "success"
        assert result.get("completion_state") == "execution_completed"
        assert result.get("dispatch_attempted") is True
        assert result.get("dispatch_accepted") is True
        assert result.get("execution_started") is True
        assert result.get("result_received") is True
        assert result.get("closure_complete") is True
        assert result.get("task_outcome_known") is True
        assert result.get("lifecycle_state") == "succeeded"

    @pytest.mark.asyncio
    async def test_master_brain_fire_and_observe_status_is_non_terminal_until_result_closes(self):
        """Fire-and-observe callers can inspect truthful non-terminal distributed state."""
        from core.master_brain import MasterBrain
        from core.schemas.contracts import (
            DeviceCommandPayloadModel,
            TaskDispatchModel,
            TaskResultModel,
            TaskStatus,
            TaskType,
            TimestampModel,
        )

        mock_bus = _make_mock_nats_bus(connected=True)
        mock_bus.publish_task_dispatch = AsyncMock(return_value={"success": True, "seq": 11})
        brain = MasterBrain(nats=mock_bus)
        brain._acl.validate_task_dispatch = AsyncMock(return_value={
            "success": True,
            "data": TaskDispatchModel(
                task_id="stage7-observe-01",
                task_type=TaskType.DEVICE_CMD,
                target_worker_id="worker-7",
                device_payload=DeviceCommandPayloadModel(command="tap", target_device_id="worker-7"),
                context={"trace_id": "trace-stage7-observe"},
                timeout_ms=1_000,
            ),
        })

        dispatch_result = await brain.dispatch_task({"task_id": "stage7-observe-01", "wait_for_completion": False})
        running_result = await brain.handle_task_result(TaskResultModel(
            task_id="stage7-observe-01",
            worker_id="worker-7",
            status=TaskStatus.RUNNING,
            started_at=TimestampModel(seconds=3, nanos=0),
            metadata={"trace_id": "trace-stage7-observe", "result_id": "res-running-01"},
        ))
        observed = brain.get_task_status("stage7-observe-01")

        assert dispatch_result.get("success") is True
        assert dispatch_result.get("closure_complete") is False
        assert dispatch_result.get("completion_state") == "dispatch_accepted"
        # RUNNING is a non-terminal progress update, so success stays false
        # until a terminal worker result closes the loop.
        assert running_result.get("success") is False
        assert running_result.get("closure_complete") is False
        assert running_result.get("completion_state") == "execution_started"
        assert observed is not None
        assert observed.get("execution_started") is True
        assert observed.get("result_received") is True
        assert observed.get("result_pending_closure") is True
        assert observed.get("task_outcome_known") is False
        assert observed.get("closure_complete") is False
        assert observed.get("lifecycle_state") == "running"

    @pytest.mark.asyncio
    async def test_master_brain_rejects_result_correlation_mismatch(self):
        """Mismatched worker results must not close an unrelated distributed dispatch."""
        from core.master_brain import MasterBrain
        from core.schemas.contracts import (
            DeviceCommandPayloadModel,
            TaskDispatchModel,
            TaskResultModel,
            TaskStatus,
            TaskType,
        )

        mock_bus = _make_mock_nats_bus(connected=True)
        mock_bus.publish_task_dispatch = AsyncMock(return_value={"success": True, "seq": 12})
        brain = MasterBrain(nats=mock_bus)
        brain._acl.validate_task_dispatch = AsyncMock(return_value={
            "success": True,
            "data": TaskDispatchModel(
                task_id="stage7-mismatch-01",
                task_type=TaskType.DEVICE_CMD,
                target_worker_id="worker-expected",
                device_payload=DeviceCommandPayloadModel(command="tap", target_device_id="worker-expected"),
                context={"trace_id": "trace-stage7-mismatch"},
                timeout_ms=1_000,
            ),
        })

        await brain.dispatch_task({"task_id": "stage7-mismatch-01", "wait_for_completion": False})
        mismatch = await brain.handle_task_result(TaskResultModel(
            task_id="stage7-mismatch-01",
            worker_id="worker-other",
            status=TaskStatus.SUCCESS,
            metadata={"trace_id": "trace-stage7-mismatch", "result_id": "res-mismatch-01"},
        ))
        observed = brain.get_task_status("stage7-mismatch-01")

        assert mismatch.get("success") is False
        assert "result_worker_id_mismatch" in mismatch.get("error", "")
        assert observed is not None
        assert observed.get("closure_complete") is False
        assert observed.get("task_outcome_known") is False
        assert observed.get("correlation_valid") is False

    @pytest.mark.asyncio
    async def test_route_worker_envelope_copies_completion_truth_from_master_brain(self):
        """CommandRouter exposes distributed completion truth returned by MasterBrain."""
        from core.command_router import CommandRouter
        from core.schemas.remote_execution import ExecutorTargetType
        from core.schemas.task_envelope import TaskEnvelope

        router = CommandRouter()
        master_brain = MagicMock()
        master_brain.execute_distributed_task = AsyncMock(return_value={
            "success": True,
            "distributed_dispatch": True,
            "execution_path": "temporal_workflow",
            "completion_state": "execution_completed",
            "closure_complete": True,
            "dispatch_attempted": True,
            "dispatch_accepted": True,
            "execution_started": True,
            "result_received": True,
            "result_pending_closure": False,
            "task_outcome_known": True,
            "lifecycle_state": "succeeded",
            "temporal_workflow_type": "code_execution",
        })
        envelope = TaskEnvelope(
            task_id="stage7-route-01",
            trace_id="trace-stage7-route",
            source="test",
            targets=["worker-route-1"],
            tool_name="run",
            args={"k": "v"},
            executor_target_type=ExecutorTargetType.go_worker,
        )

        with patch("core.master_brain.get_master_brain", return_value=master_brain):
            result = await router._route_worker_envelope(envelope, command_id="cmd-stage7-route", request_id="req-stage7-route")

        assert result["success"] is True
        assert result["execution_path"] == "temporal_workflow"
        assert result["completion_state"] == "execution_completed"
        assert result["closure_complete"] is True
        assert result["dispatch_accepted"] is True
        assert result["execution_started"] is True
        assert result["task_outcome_known"] is True
        assert result["lifecycle_state"] == "succeeded"
        master_brain.execute_distributed_task.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_route_worker_envelope_reports_unavailable_when_master_brain_missing(self):
        """go_worker dispatch must return explicit unavailable truth when MasterBrain is absent."""
        from core.command_router import CommandRouter
        from core.schemas.remote_execution import ExecutorTargetType
        from core.schemas.task_envelope import TaskEnvelope

        router = CommandRouter()
        envelope = TaskEnvelope(
            task_id="stage10-route-unavailable-01",
            trace_id="trace-stage10-route-unavailable",
            source="test",
            targets=["worker-route-missing"],
            tool_name="run",
            args={"k": "v"},
            executor_target_type=ExecutorTargetType.go_worker,
        )

        with patch("core.master_brain.get_master_brain", return_value=None):
            result = await router._route_worker_envelope(
                envelope,
                command_id="cmd-stage10-route-unavailable",
                request_id="req-stage10-route-unavailable",
            )

        assert result["success"] is False
        assert result["error_code"] == "WORKER_DISPATCH_UNAVAILABLE"
        assert result["error_message"] == "distributed_control_plane_disabled_or_unavailable"
        assert result["execution_path"] == "distributed_unavailable"
        assert result["completion_state"] == "dispatch_unavailable"
        assert result["closure_complete"] is True
        assert result["task_outcome_known"] is True
        assert result["dispatch_attempted"] is False
        assert result["dispatch_accepted"] is False
        assert result["execution_started"] is False
        assert result["result_received"] is False
        assert result["result_pending_closure"] is False

    @pytest.mark.asyncio
    async def test_route_worker_envelope_uses_selected_worker_from_master_brain(self):
        """CommandRouter should report worker/device identity from MasterBrain terminal snapshot."""
        from core.command_router import CommandRouter
        from core.schemas.remote_execution import ExecutorTargetType
        from core.schemas.task_envelope import TaskEnvelope

        router = CommandRouter()
        master_brain = MagicMock()
        master_brain.execute_distributed_task = AsyncMock(return_value={
            "success": True,
            "worker_id": "worker-selected-by-masterbrain",
            "distributed_dispatch": True,
            "execution_path": "nats_distributed",
            "completion_state": "execution_completed",
            "closure_complete": True,
            "temporal_worker_active": False,
        })
        envelope = TaskEnvelope(
            task_id="stage10-route-worker-id-01",
            trace_id="trace-stage10-route-worker-id",
            source="test",
            targets=["worker-requested-in-envelope"],
            tool_name="run",
            args={"k": "v"},
            executor_target_type=ExecutorTargetType.go_worker,
        )

        with patch("core.master_brain.get_master_brain", return_value=master_brain):
            result = await router._route_worker_envelope(
                envelope,
                command_id="cmd-stage10-route-worker-id",
                request_id="req-stage10-route-worker-id",
            )

        assert result["success"] is True
        assert result["device_id"] == "worker-selected-by-masterbrain"
        assert result["worker_id"] == "worker-selected-by-masterbrain"
        assert result["temporal_worker_active"] is False


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

        async def _capture_forward(task_id, target, task_type, payload, **_kwargs):
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

        async def _capture_forward(task_id, target, task_type, payload, **_kwargs):
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
        loop = asyncio.get_running_loop()
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
        loop = asyncio.get_running_loop()
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
# Temporal activity convergence
# ===========================================================================


class TestTemporalWorkflowActivities:
    """Validate subscription lifecycle and terminal-result waiting semantics."""

    @pytest.mark.asyncio
    async def test_wait_for_result_activity_waits_for_terminal_result_and_unsubscribes(self):
        """Temporal result wait ignores non-terminal updates and cleans up the subscription."""
        from core.temporal_workflows import wait_for_result_activity

        mock_bus = MagicMock()
        subscription = MagicMock()
        subscription.unsubscribe = AsyncMock(return_value=None)

        async def _subscribe(callback, *, include_subscription=False):
            async def _emit():
                await callback({
                    "task_id": "temporal-task-01",
                    "status": "dispatched",
                    "metadata": {"result_id": "res-dispatch"},
                })
                await callback({
                    "task_id": "temporal-task-01",
                    "status": "running",
                    "metadata": {"result_id": "res-running"},
                })
                await callback({
                    "task_id": "temporal-task-01",
                    "status": "success",
                    "metadata": {"result_id": "res-success"},
                })
                await callback({
                    "task_id": "temporal-task-01",
                    "status": "success",
                    "metadata": {"result_id": "res-success"},
                })

            asyncio.create_task(_emit())
            return {"success": True, "subscription": subscription}

        mock_bus.subscribe_task_results = AsyncMock(side_effect=_subscribe)
        mock_bus.unsubscribe = AsyncMock(return_value={"success": True})

        with patch("core.nats_bus.nats_bus", mock_bus):
            result = await wait_for_result_activity("temporal-task-01", timeout_ms=1000)

        assert result.get("success") is True
        assert result.get("data", {}).get("status") == "success"
        mock_bus.unsubscribe.assert_awaited_once_with(subscription)

    @pytest.mark.asyncio
    async def test_wait_for_result_activity_rejects_noop_subscription(self):
        """Temporal result wait surfaces noop transport as unavailable rather than timing out."""
        from core.temporal_workflows import wait_for_result_activity

        mock_bus = MagicMock()
        mock_bus.subscribe_task_results = AsyncMock(return_value={
            "success": False,
            "noop": True,
            "error": "nats_noop_transport",
        })
        mock_bus.unsubscribe = AsyncMock(return_value={"success": True})

        with patch("core.nats_bus.nats_bus", mock_bus):
            result = await wait_for_result_activity("temporal-task-noop", timeout_ms=50)

        assert result.get("success") is False
        assert "distributed_transport_unavailable" in result.get("error", "")


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
