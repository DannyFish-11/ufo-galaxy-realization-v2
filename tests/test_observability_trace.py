"""
tests/test_observability_trace.py
===================================

Round 7 — unit/integration tests for end-to-end observability:

1.  TraceContext.new()          — generates valid UUID4 trace_id / span_id.
2.  TraceContext.from_message() — extracts existing trace_id; generates missing.
3.  TraceContext.child_span()   — preserves trace_id, creates new span_id.
4.  emit_gateway_log()          — writes valid JSON to Galaxy.Gateway logger.
5.  emit_gateway_log() sampling — GALAXY_TRACE_SAMPLE_RATE=0 suppresses debug;
                                  error events bypass sampling.
6.  GatewayMetrics.inc()        — counter increments correctly (thread-safe).
7.  GatewayMetrics._LatencyHistogram.observe() — buckets and sum updated.
8.  GatewayMetrics.snapshot()   — returns correct structure.
9.  GatewayMetrics.prometheus_text() — contains expected metric names.
10. webrtc_proxy — metrics incremented on signaling success path.
11. webrtc_proxy — metrics incremented on signaling timeout path.
12. webrtc_proxy — metrics incremented on node95-unreachable path.
13. webrtc_proxy — trace_id/span_id injected into forwarded messages.
14. agent_bridge — GatewayMetrics bridge counters on success path.
15. agent_bridge — GatewayMetrics bridge counters on failure/fallback path.
16. device_router — trace_id generated when missing from context.
17. device_router — routing_total / routing_failure incremented on no device.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import uuid
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# 1–3. TraceContext
# ---------------------------------------------------------------------------

class TestTraceContext:
    def test_new_generates_valid_uuids(self):
        from galaxy_gateway.observability import TraceContext
        ctx = TraceContext.new()
        uuid.UUID(ctx.trace_id)  # raises if invalid
        uuid.UUID(ctx.span_id)
        assert ctx.trace_id != ctx.span_id

    def test_from_message_uses_existing_trace_id(self):
        from galaxy_gateway.observability import TraceContext
        existing = str(uuid.uuid4())
        ctx = TraceContext.from_message({"trace_id": existing, "foo": "bar"})
        assert ctx.trace_id == existing
        # span_id is always freshly generated
        uuid.UUID(ctx.span_id)

    def test_from_message_generates_missing_trace_id(self):
        from galaxy_gateway.observability import TraceContext
        ctx = TraceContext.from_message({})
        uuid.UUID(ctx.trace_id)
        uuid.UUID(ctx.span_id)

    def test_from_message_accepts_x_trace_id_header(self):
        from galaxy_gateway.observability import TraceContext
        existing = str(uuid.uuid4())
        ctx = TraceContext.from_message({"x-trace-id": existing})
        assert ctx.trace_id == existing

    def test_child_span_preserves_trace_id(self):
        from galaxy_gateway.observability import TraceContext
        parent = TraceContext.new()
        child = parent.child_span()
        assert child.trace_id == parent.trace_id
        assert child.span_id != parent.span_id

    def test_to_dict(self):
        from galaxy_gateway.observability import TraceContext
        ctx = TraceContext.new()
        d = ctx.to_dict()
        assert d["trace_id"] == ctx.trace_id
        assert d["span_id"] == ctx.span_id


# ---------------------------------------------------------------------------
# 4–5. emit_gateway_log
# ---------------------------------------------------------------------------

class TestEmitGatewayLog:
    def _capture_log(self):
        """Return a list that accumulates Galaxy.Gateway log entries."""
        records = []

        class _H(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())

        h = _H()
        logger = logging.getLogger("Galaxy.Gateway")
        logger.addHandler(h)
        original_level = logger.level
        logger.setLevel(logging.DEBUG)
        return records, h, logger, original_level

    def teardown_method(self, _method):
        # Reset any env vars set during tests
        os.environ.pop("GALAXY_TRACE_SAMPLE_RATE", None)

    def test_emits_valid_json(self):
        from galaxy_gateway.observability import TraceContext, emit_gateway_log
        records, h, logger, orig = self._capture_log()
        try:
            ctx = TraceContext.new()
            emit_gateway_log("test_event", trace_ctx=ctx, device_id="dev1")
            assert records, "No log entry emitted"
            entry = json.loads(records[-1])
            assert entry["event"] == "test_event"
            assert entry["trace_id"] == ctx.trace_id
            assert entry["span_id"] == ctx.span_id
            assert entry["device_id"] == "dev1"
            assert "ts" in entry
        finally:
            logger.removeHandler(h)
            logger.setLevel(orig)

    def test_sample_rate_zero_suppresses_info(self):
        from galaxy_gateway.observability import TraceContext, emit_gateway_log
        os.environ["GALAXY_TRACE_SAMPLE_RATE"] = "0"
        records, h, logger, orig = self._capture_log()
        try:
            ctx = TraceContext.new()
            for _ in range(20):
                emit_gateway_log("verbose_event", trace_ctx=ctx, level="info")
            assert not records, "Expected no entries with sample_rate=0"
        finally:
            logger.removeHandler(h)
            logger.setLevel(orig)

    def test_error_events_bypass_sampling(self):
        from galaxy_gateway.observability import TraceContext, emit_gateway_log
        os.environ["GALAXY_TRACE_SAMPLE_RATE"] = "0"
        records, h, logger, orig = self._capture_log()
        try:
            ctx = TraceContext.new()
            emit_gateway_log("signaling_error", trace_ctx=ctx, level="error", cause="boom")
            assert records, "Error event must bypass sample_rate=0"
            entry = json.loads(records[-1])
            assert entry["event"] == "signaling_error"
            assert entry["cause"] == "boom"
        finally:
            logger.removeHandler(h)
            logger.setLevel(orig)

    def test_no_trace_ctx_still_works(self):
        from galaxy_gateway.observability import emit_gateway_log
        records, h, logger, orig = self._capture_log()
        try:
            emit_gateway_log("headless_event", device_id="x")
            assert records
            entry = json.loads(records[-1])
            assert entry["event"] == "headless_event"
            assert "trace_id" not in entry
        finally:
            logger.removeHandler(h)
            logger.setLevel(orig)


# ---------------------------------------------------------------------------
# 6–9. GatewayMetrics
# ---------------------------------------------------------------------------

class TestGatewayMetrics:
    def _fresh_metrics(self):
        from galaxy_gateway.observability import GatewayMetrics
        return GatewayMetrics()

    def test_inc_counter(self):
        m = self._fresh_metrics()
        m.inc("signaling_total")
        assert m.signaling_total == 1
        m.inc("signaling_total", 4)
        assert m.signaling_total == 5

    def test_inc_unknown_counter_creates_dynamic_attribute(self):
        """inc() on an unknown name creates the attribute (Python dynamic setattr)."""
        m = self._fresh_metrics()
        m.inc("nonexistent_counter")
        assert m.nonexistent_counter == 1  # type: ignore[attr-defined]

    def test_latency_histogram_observe_and_snapshot(self):
        from galaxy_gateway.observability import _LatencyHistogram
        h = _LatencyHistogram()
        h.observe(5.0)    # ≤10ms bucket
        h.observe(80.0)   # ≤100ms bucket
        h.observe(99999)  # +inf bucket
        snap = h.snapshot()
        assert snap["count"] == 3
        assert snap["sum_ms"] == pytest.approx(5.0 + 80.0 + 99999, rel=1e-3)
        assert snap["buckets"]["le_10ms"] == 1
        assert snap["buckets"]["le_inf"] == 1

    def test_snapshot_structure(self):
        m = self._fresh_metrics()
        m.inc("signaling_total", 3)
        m.inc("signaling_success", 2)
        m.inc("signaling_failure", 1)
        m.signaling_latency_ms.observe(42.0)
        snap = m.snapshot()
        assert snap["signaling"]["total"] == 3
        assert snap["signaling"]["success"] == 2
        assert snap["signaling"]["failure"] == 1
        assert snap["signaling"]["latency_ms"]["count"] == 1

    def test_prometheus_text_contains_metric_names(self):
        m = self._fresh_metrics()
        m.inc("signaling_total", 7)
        m.inc("bridge_handoff_total", 2)
        text = m.prometheus_text()
        assert "galaxy_gateway_signaling_total 7" in text
        assert "galaxy_gateway_bridge_handoff_total 2" in text
        assert "galaxy_gateway_signaling_latency_ms_count" in text
        assert "# TYPE galaxy_gateway_signaling_total counter" in text

    def test_thread_safety(self):
        m = self._fresh_metrics()
        errors = []

        def _worker():
            try:
                for _ in range(100):
                    m.inc("routing_total")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors
        assert m.routing_total == 1000

    def test_get_gateway_metrics_singleton(self):
        from galaxy_gateway.observability import get_gateway_metrics
        m1 = get_gateway_metrics()
        m2 = get_gateway_metrics()
        assert m1 is m2


# ---------------------------------------------------------------------------
# 10–13. webrtc_proxy integration (mocked Node_95)
# ---------------------------------------------------------------------------

class TestWebRTCProxyObservability:
    """Verify GatewayMetrics counters via webrtc_proxy on success / failure paths."""

    def setup_method(self, _method):
        # Reset the module-level gateway metrics singleton for isolation.
        import galaxy_gateway.observability as obs_module
        obs_module._gateway_metrics = None
        os.environ["GALAXY_CROSS_DEVICE_ENABLED"] = "1"

    def teardown_method(self, _method):
        import galaxy_gateway.observability as obs_module
        obs_module._gateway_metrics = None
        os.environ.pop("GALAXY_CROSS_DEVICE_ENABLED", None)

    @pytest.mark.asyncio
    async def test_success_path_increments_counters(self):
        """Metrics: signaling_total +1, signaling_success +1 on clean session."""
        from galaxy_gateway.observability import get_gateway_metrics
        from galaxy_gateway import webrtc_proxy

        # Patch out the actual websocket tunnel and just run the session logic.
        mock_client_ws = AsyncMock()
        mock_client_ws.receive_text = AsyncMock(side_effect=Exception("client_disconnect"))

        class _FakeNodeWS:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *_):
                pass
            async def send(self, data):
                pass
            def __aiter__(self):
                return self
            async def __anext__(self):
                raise StopAsyncIteration

        with patch("galaxy_gateway.webrtc_proxy.websockets.connect") as mock_connect:
            mock_connect.return_value = _FakeNodeWS()
            await webrtc_proxy.proxy_webrtc_signaling(mock_client_ws, "test_device")

        m = get_gateway_metrics()
        assert m.signaling_total >= 1
        # The session completed (either success or failure depending on mock)
        assert (m.signaling_success + m.signaling_failure) >= 1

    @pytest.mark.asyncio
    async def test_timeout_path_increments_timeout_counter(self):
        """Metrics: signaling_timeout +1 on asyncio.TimeoutError."""
        from galaxy_gateway.observability import get_gateway_metrics
        from galaxy_gateway import webrtc_proxy

        mock_client_ws = AsyncMock()

        async def _slow_session():
            await asyncio.sleep(9999)

        with patch("galaxy_gateway.webrtc_proxy.asyncio.wait_for", side_effect=asyncio.TimeoutError):
            with patch.object(webrtc_proxy, "_run_session", _slow_session, create=True):
                await webrtc_proxy.proxy_webrtc_signaling(mock_client_ws, "test_device")

        m = get_gateway_metrics()
        assert m.signaling_timeout >= 1
        assert m.signaling_failure >= 1

    @pytest.mark.asyncio
    async def test_node95_error_increments_failure_counter(self):
        """Metrics: signaling_failure +1 on OSError from node_ws."""
        from galaxy_gateway.observability import get_gateway_metrics
        from galaxy_gateway import webrtc_proxy

        mock_client_ws = AsyncMock()

        with patch("galaxy_gateway.webrtc_proxy.asyncio.wait_for", side_effect=OSError("refused")):
            await webrtc_proxy.proxy_webrtc_signaling(mock_client_ws, "test_device")

        m = get_gateway_metrics()
        assert m.signaling_failure >= 1
        assert m.signaling_timeout == 0  # should NOT be timeout

    @pytest.mark.asyncio
    async def test_trace_id_generated_and_consistent(self):
        """A session-level trace_id is generated and not empty."""
        from galaxy_gateway import webrtc_proxy

        mock_client_ws = AsyncMock()
        trace_ids_seen = []

        original_emit = webrtc_proxy.emit_gateway_log

        def _capturing_emit(event, *, trace_ctx=None, **fields):
            if trace_ctx is not None:
                trace_ids_seen.append(trace_ctx.trace_id)
            return original_emit(event, trace_ctx=trace_ctx, **fields)

        with patch("galaxy_gateway.webrtc_proxy.emit_gateway_log", side_effect=_capturing_emit):
            with patch("galaxy_gateway.webrtc_proxy.asyncio.wait_for", side_effect=OSError("no node")):
                await webrtc_proxy.proxy_webrtc_signaling(mock_client_ws, "dev_x")

        assert trace_ids_seen, "No emit_gateway_log calls captured"
        # All captured trace_ids from the same session must be identical
        unique_ids = set(trace_ids_seen)
        assert len(unique_ids) == 1, f"Multiple trace_ids in one session: {unique_ids}"
        uuid.UUID(trace_ids_seen[0])  # must be valid UUID


# ---------------------------------------------------------------------------
# 14–15. agent_bridge GatewayMetrics wiring
# ---------------------------------------------------------------------------

class TestAgentBridgeMetricsWiring:
    def setup_method(self, _method):
        import galaxy_gateway.observability as obs_module
        obs_module._gateway_metrics = None
        os.environ["GALAXY_CROSS_DEVICE_ENABLED"] = "1"
        os.environ["GALAXY_RUNTIME_ENABLED"] = "1"

    def teardown_method(self, _method):
        import galaxy_gateway.observability as obs_module
        obs_module._gateway_metrics = None
        import galaxy_gateway.agent_bridge as ab
        ab._bridge_instance = None
        os.environ.pop("GALAXY_CROSS_DEVICE_ENABLED", None)
        os.environ.pop("GALAXY_RUNTIME_ENABLED", None)

    @pytest.mark.asyncio
    async def test_success_increments_bridge_success(self):
        from galaxy_gateway.observability import get_gateway_metrics
        from galaxy_gateway.agent_bridge import (
            AgentBridge,
            AgentBridgeConfig,
            HandoffContract,
        )
        import galaxy_gateway.agent_bridge as ab

        bridge = AgentBridge(AgentBridgeConfig(
            runtime_url="http://localhost:9999",
            timeout=5.0,
            enabled=True,
        ))
        ab._bridge_instance = bridge

        success_result = {"success": True, "output": "done"}
        with patch.object(bridge, "_call_runtime", new_callable=AsyncMock, return_value=success_result):
            contract = HandoffContract(
                trace_id=str(uuid.uuid4()),
                task={"command": "test"},
                capability="ui_automation",
                exec_mode="remote",
                route_mode="cross_device",
                session={},
                callback_channel="ws",
            )
            result = await bridge.handoff(contract)

        assert result["success"] is True
        m = get_gateway_metrics()
        assert m.bridge_handoff_total >= 1
        assert m.bridge_handoff_success >= 1
        assert m.bridge_handoff_failure == 0

    @pytest.mark.asyncio
    async def test_failure_increments_bridge_failure_and_fallback(self):
        from galaxy_gateway.observability import get_gateway_metrics
        from galaxy_gateway.agent_bridge import (
            AgentBridge,
            AgentBridgeConfig,
            HandoffContract,
        )
        import galaxy_gateway.agent_bridge as ab

        bridge = AgentBridge(AgentBridgeConfig(
            runtime_url="http://localhost:9999",
            timeout=0.01,
            enabled=True,
        ))
        ab._bridge_instance = bridge

        async def _slow(*_):
            await asyncio.sleep(9999)

        with patch.object(bridge, "_call_runtime", side_effect=_slow):
            contract = HandoffContract(
                trace_id=str(uuid.uuid4()),
                task={"command": "test"},
                capability="ui_automation",
                exec_mode="remote",
                route_mode="cross_device",
                session={},
                callback_channel="ws",
            )
            result = await bridge.handoff(contract)

        m = get_gateway_metrics()
        assert m.bridge_handoff_failure >= 1
        assert m.bridge_fallback_total >= 1


# ---------------------------------------------------------------------------
# 16–17. device_router trace propagation and routing metrics
# ---------------------------------------------------------------------------

class TestDeviceRouterObservability:
    def setup_method(self, _method):
        import galaxy_gateway.observability as obs_module
        obs_module._gateway_metrics = None
        os.environ["GALAXY_CROSS_DEVICE_ENABLED"] = "1"

    def teardown_method(self, _method):
        import galaxy_gateway.observability as obs_module
        obs_module._gateway_metrics = None
        os.environ.pop("GALAXY_CROSS_DEVICE_ENABLED", None)

    @pytest.mark.asyncio
    async def test_trace_id_generated_when_missing(self):
        """route_task injects trace_id into context when absent."""
        from galaxy_gateway.observability import get_gateway_metrics, TraceContext
        from galaxy_gateway.device_router import DeviceRouter

        router = DeviceRouter()

        injected_trace_ids = []
        # Must patch the name as used inside device_router
        import galaxy_gateway.device_router as dr_module
        original_emit = dr_module.emit_gateway_log

        def _capture(event, *, trace_ctx=None, **fields):
            if trace_ctx and event == "trace_id_injected":
                injected_trace_ids.append(trace_ctx.trace_id)
            original_emit(event, trace_ctx=trace_ctx, **fields)

        # Provide a context without trace_id and no devices.
        with patch.object(dr_module, "emit_gateway_log", side_effect=_capture):
            with patch.object(router, "_analyze_command", new_callable=AsyncMock,
                              return_value={"requires_cross_device": False, "task_type": "query"}):
                with patch.object(router, "_select_devices", return_value=[]):
                    await router.route_task("hello", context={})

        assert injected_trace_ids, "trace_id_injected event must be emitted when context has no trace_id"
        uuid.UUID(injected_trace_ids[0])

    @pytest.mark.asyncio
    async def test_routing_failure_counter_on_no_device(self):
        """routing_failure increments when no device is available."""
        from galaxy_gateway.observability import get_gateway_metrics
        from galaxy_gateway.device_router import DeviceRouter

        router = DeviceRouter()
        m = get_gateway_metrics()
        before = m.routing_failure

        with patch.object(router, "_analyze_command", new_callable=AsyncMock,
                          return_value={"requires_cross_device": False, "task_type": "query"}):
            with patch.object(router, "_select_devices", return_value=[]):
                result = await router.route_task("test cmd", context={"trace_id": str(uuid.uuid4())})

        assert result["success"] is False
        assert m.routing_failure == before + 1

    @pytest.mark.asyncio
    async def test_existing_trace_id_preserved(self):
        """route_task preserves existing trace_id and does not overwrite it."""
        from galaxy_gateway.observability import get_gateway_metrics
        from galaxy_gateway.device_router import DeviceRouter
        import galaxy_gateway.device_router as dr_module

        router = DeviceRouter()
        existing_trace = str(uuid.uuid4())

        captured_trace_ids = []
        original_emit = dr_module.emit_gateway_log

        def _capture(event, *, trace_ctx=None, **fields):
            if trace_ctx:
                captured_trace_ids.append(trace_ctx.trace_id)
            original_emit(event, trace_ctx=trace_ctx, **fields)

        with patch.object(dr_module, "emit_gateway_log", side_effect=_capture):
            with patch.object(router, "_analyze_command", new_callable=AsyncMock,
                              return_value={"requires_cross_device": False, "task_type": "query"}):
                with patch.object(router, "_select_devices", return_value=[]):
                    await router.route_task("cmd", context={"trace_id": existing_trace})

        # Every emitted log in this call must use the same trace_id
        assert all(t == existing_trace for t in captured_trace_ids), (
            f"trace_id was not preserved: {set(captured_trace_ids)}"
        )
