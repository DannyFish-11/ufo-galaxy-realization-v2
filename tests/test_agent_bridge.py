"""
tests/test_agent_bridge.py
===========================

Round 5 — Agent Bridge & Runtime Handoff Tests.

Covers:
  1.  AgentBridgeConfig.from_env() — reads GALAXY_RUNTIME_URL/TIMEOUT/ENABLED.
  2.  HandoffContract.to_dict() — serialises all fields.
  3.  AgentBridgeMetrics — counters and avg_latency_ms.
  4.  Bridge OFF (GALAXY_RUNTIME_ENABLED=0) — stays local via fallback.
  5.  Cross-device switch OFF — returns disabled response, no runtime call.
  6.  Successful runtime handoff — returns runtime response, caches result.
  7.  Deduplication — second handoff with same trace_id returns cached result.
  8.  Timeout — falls back to local fallback, increments fallback metric.
  9.  Runtime unreachable (OSError) — falls back, increments fallback metric.
 10.  No fallback supplied — returns generic error dict on failure.
 11.  DeviceRouter.route_task() cross-device ON — delegates to bridge.
 12.  DeviceRouter.route_task() cross-device OFF — blocked (no bridge call).
 13.  Bridge fallback propagates trace_id through to caller.
 14.  Metrics snapshot includes all expected keys.
 15.  Singleton get_agent_bridge() returns same instance.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.absolute()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import galaxy_gateway.agent_bridge as _ab_module  # noqa: E402
from galaxy_gateway.agent_bridge import (  # noqa: E402
    AgentBridge,
    AgentBridgeConfig,
    AgentBridgeMetrics,
    HandoffContract,
    get_agent_bridge,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_bridge(
    *,
    runtime_url: str = "http://test-runtime:9000",
    timeout: float = 5.0,
    enabled: bool = True,
) -> AgentBridge:
    """Return a new AgentBridge with explicit config (no env reads)."""
    return AgentBridge(
        AgentBridgeConfig(runtime_url=runtime_url, timeout=timeout, enabled=enabled)
    )


def _contract(trace_id: str | None = None, **kwargs) -> HandoffContract:
    return HandoffContract(
        trace_id=trace_id or str(uuid.uuid4()),
        task={"command": "test_cmd"},
        **kwargs,
    )


async def _ok_fallback(task: dict) -> dict:
    return {"success": True, "result": "local", "from_fallback": True}


async def _fail_fallback(task: dict) -> dict:
    raise RuntimeError("local executor broken")


# ===========================================================================
# 1. AgentBridgeConfig.from_env()
# ===========================================================================

class TestAgentBridgeConfigFromEnv:
    def test_defaults(self, monkeypatch):
        monkeypatch.delenv("GALAXY_RUNTIME_URL", raising=False)
        monkeypatch.delenv("GALAXY_RUNTIME_TIMEOUT", raising=False)
        monkeypatch.delenv("GALAXY_RUNTIME_ENABLED", raising=False)
        cfg = AgentBridgeConfig.from_env()
        assert cfg.runtime_url == "http://localhost:9000"
        assert cfg.timeout == 10.0
        assert cfg.enabled is True

    def test_custom_url(self, monkeypatch):
        monkeypatch.setenv("GALAXY_RUNTIME_URL", "http://agent:8888")
        cfg = AgentBridgeConfig.from_env()
        assert cfg.runtime_url == "http://agent:8888"

    def test_custom_timeout(self, monkeypatch):
        monkeypatch.setenv("GALAXY_RUNTIME_TIMEOUT", "3.5")
        cfg = AgentBridgeConfig.from_env()
        assert cfg.timeout == 3.5

    def test_disabled_via_env(self, monkeypatch):
        for val in ("0", "false", "no", "FALSE"):
            monkeypatch.setenv("GALAXY_RUNTIME_ENABLED", val)
            cfg = AgentBridgeConfig.from_env()
            assert cfg.enabled is False, f"Expected disabled for {val!r}"

    def test_enabled_via_env(self, monkeypatch):
        monkeypatch.setenv("GALAXY_RUNTIME_ENABLED", "1")
        cfg = AgentBridgeConfig.from_env()
        assert cfg.enabled is True

    def test_invalid_timeout_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("GALAXY_RUNTIME_TIMEOUT", "not_a_number")
        cfg = AgentBridgeConfig.from_env()
        assert cfg.timeout == 10.0


# ===========================================================================
# 2. HandoffContract.to_dict()
# ===========================================================================

class TestHandoffContract:
    def test_to_dict_all_fields(self):
        trace_id = str(uuid.uuid4())
        c = HandoffContract(
            trace_id=trace_id,
            task={"cmd": "do"},
            capability="screen",
            exec_mode="remote",
            route_mode="broadcast",
            session={"user": "alice"},
            callback_channel="nats",
        )
        d = c.to_dict()
        assert d["trace_id"] == trace_id
        assert d["task"] == {"cmd": "do"}
        assert d["capability"] == "screen"
        assert d["exec_mode"] == "remote"
        assert d["route_mode"] == "broadcast"
        assert d["session"] == {"user": "alice"}
        assert d["callback_channel"] == "nats"

    def test_defaults(self):
        c = HandoffContract(trace_id="t1", task={})
        d = c.to_dict()
        assert d["exec_mode"] == "both"
        assert d["route_mode"] == "direct"
        assert d["callback_channel"] == "ws"
        assert d["session"] == {}


# ===========================================================================
# 3. AgentBridgeMetrics
# ===========================================================================

class TestAgentBridgeMetrics:
    def test_initial_state(self):
        m = AgentBridgeMetrics()
        s = m.snapshot()
        assert s["handoff_attempts"] == 0
        assert s["avg_latency_ms"] == 0.0

    def test_avg_latency(self):
        m = AgentBridgeMetrics()
        m.record_latency(0.1)
        m.record_latency(0.3)
        assert abs(m.avg_latency_ms - 200.0) < 1.0

    def test_snapshot_keys(self):
        m = AgentBridgeMetrics()
        s = m.snapshot()
        for key in (
            "handoff_attempts",
            "handoff_success",
            "handoff_failure",
            "fallback_count",
            "dedup_hit_count",
            "avg_latency_ms",
        ):
            assert key in s, f"Missing key: {key}"


# ===========================================================================
# 4. Bridge disabled (GALAXY_RUNTIME_ENABLED=0)
# ===========================================================================

class TestBridgeDisabled:
    @pytest.mark.asyncio
    async def test_stays_local_when_disabled(self, monkeypatch):
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "1")
        bridge = _fresh_bridge(enabled=False)
        contract = _contract()
        result = await bridge.handoff(contract=contract, local_fallback=_ok_fallback)
        assert result["bridge_source"] == "local_fallback"
        assert result["from_fallback"] is True
        assert bridge.metrics.fallback_count == 1

    @pytest.mark.asyncio
    async def test_disabled_does_not_call_runtime(self, monkeypatch):
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "1")
        bridge = _fresh_bridge(enabled=False)
        bridge._call_runtime = AsyncMock(return_value={"success": True})
        await bridge.handoff(contract=_contract(), local_fallback=_ok_fallback)
        bridge._call_runtime.assert_not_awaited()


# ===========================================================================
# 5. Cross-device switch OFF
# ===========================================================================

class TestCrossDeviceSwitchOff:
    @pytest.mark.asyncio
    async def test_returns_disabled_response(self, monkeypatch):
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "0")
        bridge = _fresh_bridge()
        trace_id = str(uuid.uuid4())
        result = await bridge.handoff(contract=_contract(trace_id=trace_id))
        assert result["success"] is False
        assert result["error"] == "cross_device_disabled"
        assert result["trace_id"] == trace_id

    @pytest.mark.asyncio
    async def test_no_runtime_call_when_switch_off(self, monkeypatch):
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "0")
        bridge = _fresh_bridge()
        bridge._call_runtime = AsyncMock()
        await bridge.handoff(contract=_contract())
        bridge._call_runtime.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_metrics_not_incremented_when_switch_off(self, monkeypatch):
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "0")
        bridge = _fresh_bridge()
        await bridge.handoff(contract=_contract())
        assert bridge.metrics.handoff_attempts == 0


# ===========================================================================
# 6. Successful runtime handoff
# ===========================================================================

class TestSuccessfulHandoff:
    @pytest.mark.asyncio
    async def test_runtime_result_returned(self, monkeypatch):
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "1")
        bridge = _fresh_bridge()
        trace_id = str(uuid.uuid4())
        runtime_resp = {"success": True, "result": "from_runtime"}
        bridge._call_runtime = AsyncMock(return_value=runtime_resp)
        result = await bridge.handoff(contract=_contract(trace_id=trace_id))
        assert result["success"] is True
        assert result["bridge_source"] == "runtime"
        assert result["trace_id"] == trace_id

    @pytest.mark.asyncio
    async def test_metrics_incremented_on_success(self, monkeypatch):
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "1")
        bridge = _fresh_bridge()
        bridge._call_runtime = AsyncMock(return_value={"success": True})
        await bridge.handoff(contract=_contract())
        assert bridge.metrics.handoff_attempts == 1
        assert bridge.metrics.handoff_success == 1
        assert bridge.metrics.handoff_failure == 0


# ===========================================================================
# 7. Deduplication by trace_id
# ===========================================================================

class TestDeduplication:
    @pytest.mark.asyncio
    async def test_second_call_returns_cached(self, monkeypatch):
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "1")
        bridge = _fresh_bridge()
        trace_id = str(uuid.uuid4())
        bridge._call_runtime = AsyncMock(return_value={"success": True, "call": 1})
        first = await bridge.handoff(contract=_contract(trace_id=trace_id))
        second = await bridge.handoff(contract=_contract(trace_id=trace_id))
        assert bridge._call_runtime.await_count == 1  # called only once
        assert second == first

    @pytest.mark.asyncio
    async def test_dedup_hit_counter_incremented(self, monkeypatch):
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "1")
        bridge = _fresh_bridge()
        trace_id = str(uuid.uuid4())
        bridge._call_runtime = AsyncMock(return_value={"success": True})
        await bridge.handoff(contract=_contract(trace_id=trace_id))
        await bridge.handoff(contract=_contract(trace_id=trace_id))
        assert bridge.metrics.dedup_hit_count == 1

    @pytest.mark.asyncio
    async def test_different_trace_ids_get_separate_calls(self, monkeypatch):
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "1")
        bridge = _fresh_bridge()
        bridge._call_runtime = AsyncMock(return_value={"success": True})
        await bridge.handoff(contract=_contract(trace_id="t-aaa"))
        await bridge.handoff(contract=_contract(trace_id="t-bbb"))
        assert bridge._call_runtime.await_count == 2


# ===========================================================================
# 8. Timeout fallback
# ===========================================================================

class TestTimeoutFallback:
    @pytest.mark.asyncio
    async def test_timeout_triggers_local_fallback(self, monkeypatch):
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "1")
        bridge = _fresh_bridge(timeout=0.05)

        async def _slow_runtime(contract):
            await asyncio.sleep(10)
            return {"success": True}

        bridge._call_runtime = _slow_runtime
        result = await bridge.handoff(
            contract=_contract(), local_fallback=_ok_fallback
        )
        assert result["bridge_source"] == "local_fallback"
        assert result["from_fallback"] is True

    @pytest.mark.asyncio
    async def test_timeout_increments_failure_and_fallback(self, monkeypatch):
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "1")
        bridge = _fresh_bridge(timeout=0.05)

        async def _slow_runtime(contract):
            await asyncio.sleep(10)
            return {}

        bridge._call_runtime = _slow_runtime
        await bridge.handoff(contract=_contract(), local_fallback=_ok_fallback)
        assert bridge.metrics.handoff_failure == 1
        assert bridge.metrics.fallback_count == 1


# ===========================================================================
# 9. Runtime unreachable (OSError)
# ===========================================================================

class TestRuntimeUnreachable:
    @pytest.mark.asyncio
    async def test_oserror_triggers_fallback(self, monkeypatch):
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "1")
        bridge = _fresh_bridge()

        async def _broken_runtime(contract):
            raise OSError("Connection refused")

        bridge._call_runtime = _broken_runtime
        result = await bridge.handoff(
            contract=_contract(), local_fallback=_ok_fallback
        )
        assert result["bridge_source"] == "local_fallback"

    @pytest.mark.asyncio
    async def test_runtime_error_triggers_fallback(self, monkeypatch):
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "1")
        bridge = _fresh_bridge()

        async def _bad_runtime(contract):
            raise RuntimeError("HTTP 503")

        bridge._call_runtime = _bad_runtime
        result = await bridge.handoff(
            contract=_contract(), local_fallback=_ok_fallback
        )
        assert result["bridge_source"] == "local_fallback"
        assert bridge.metrics.handoff_failure == 1
        assert bridge.metrics.fallback_count == 1


# ===========================================================================
# 10. No fallback supplied
# ===========================================================================

class TestNoFallback:
    @pytest.mark.asyncio
    async def test_returns_generic_error_when_no_fallback(self, monkeypatch):
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "1")
        bridge = _fresh_bridge(timeout=0.05)

        async def _slow(contract):
            await asyncio.sleep(10)
            return {}

        bridge._call_runtime = _slow
        result = await bridge.handoff(contract=_contract(), local_fallback=None)
        assert result["success"] is False
        assert "trace_id" in result
        assert result["bridge_source"] == "local_fallback"


# ===========================================================================
# 11. DeviceRouter.route_task() cross-device ON → bridge delegation
# ===========================================================================

class TestDeviceRouterBridgeIntegration:
    @pytest.mark.asyncio
    async def test_route_task_delegates_to_bridge_when_cross_device_on(
        self, monkeypatch
    ):
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "1")

        # Patch bridge singleton to return a known response
        trace_id = str(uuid.uuid4())
        bridge_result = {
            "success": True,
            "bridge_source": "runtime",
            "trace_id": trace_id,
        }

        mock_bridge = MagicMock()
        mock_bridge._config = MagicMock()
        mock_bridge._config.enabled = True
        mock_bridge.handoff = AsyncMock(return_value=bridge_result)

        with patch("galaxy_gateway.agent_bridge.get_agent_bridge", return_value=mock_bridge):
            from galaxy_gateway.device_router import DeviceRouter

            router = DeviceRouter()

            # Patch _analyze_command to return requires_cross_device=True
            async def _mock_analyze(command, context=None):
                return {
                    "task_type": "cross_device",
                    "requires_cross_device": True,
                    "exec_mode": "remote",
                    "actions": [],
                    "target_devices": [],
                    "priority": 2,
                    "context_required": [],
                }

            router._analyze_command = _mock_analyze

            result = await router.route_task(
                "take a screenshot on desktop",
                context={"trace_id": trace_id},
            )

        assert result["success"] is True
        assert result["bridge_source"] == "runtime"
        mock_bridge.handoff.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_route_task_blocked_when_cross_device_off(self, monkeypatch):
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "0")

        mock_bridge = MagicMock()
        mock_bridge.handoff = AsyncMock()

        with patch("galaxy_gateway.agent_bridge.get_agent_bridge", return_value=mock_bridge):
            from galaxy_gateway.device_router import DeviceRouter

            router = DeviceRouter()

            async def _mock_analyze(command, context=None):
                return {
                    "task_type": "cross_device",
                    "requires_cross_device": True,
                    "exec_mode": "remote",
                    "actions": [],
                    "target_devices": [],
                    "priority": 2,
                    "context_required": [],
                }

            router._analyze_command = _mock_analyze

            result = await router.route_task("test", context={})

        assert result["success"] is False
        assert result["error"] == "cross_device_disabled"
        mock_bridge.handoff.assert_not_awaited()


# ===========================================================================
# 12. (Covered by TestDeviceRouterBridgeIntegration above)
# ===========================================================================


# ===========================================================================
# 13. Fallback propagates trace_id
# ===========================================================================

class TestTracePropagation:
    @pytest.mark.asyncio
    async def test_fallback_result_carries_trace_id(self, monkeypatch):
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "1")
        bridge = _fresh_bridge(timeout=0.05)

        async def _slow(contract):
            await asyncio.sleep(10)
            return {}

        bridge._call_runtime = _slow
        trace_id = "trace-abc-123"
        result = await bridge.handoff(
            contract=_contract(trace_id=trace_id),
            local_fallback=_ok_fallback,
        )
        assert result.get("trace_id") == trace_id

    @pytest.mark.asyncio
    async def test_success_result_carries_trace_id(self, monkeypatch):
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "1")
        bridge = _fresh_bridge()
        trace_id = "trace-xyz-789"
        bridge._call_runtime = AsyncMock(return_value={"success": True})
        result = await bridge.handoff(contract=_contract(trace_id=trace_id))
        assert result["trace_id"] == trace_id


# ===========================================================================
# 14. Metrics snapshot keys
# ===========================================================================

class TestMetricsSnapshot:
    def test_snapshot_has_all_required_keys(self):
        m = AgentBridgeMetrics()
        s = m.snapshot()
        required = {
            "handoff_attempts",
            "handoff_success",
            "handoff_failure",
            "fallback_count",
            "dedup_hit_count",
            "avg_latency_ms",
        }
        assert required <= set(s.keys())

    @pytest.mark.asyncio
    async def test_get_metrics_on_bridge(self, monkeypatch):
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "1")
        bridge = _fresh_bridge()
        bridge._call_runtime = AsyncMock(return_value={"success": True})
        await bridge.handoff(contract=_contract())
        s = bridge.get_metrics()
        assert s["handoff_attempts"] == 1
        assert s["handoff_success"] == 1


# ===========================================================================
# 15. Singleton get_agent_bridge()
# ===========================================================================

class TestSingleton:
    def test_same_instance(self, monkeypatch):
        # Reset singleton
        _ab_module._bridge_instance = None
        monkeypatch.delenv("GALAXY_RUNTIME_URL", raising=False)
        monkeypatch.delenv("GALAXY_RUNTIME_ENABLED", raising=False)
        b1 = get_agent_bridge()
        b2 = get_agent_bridge()
        assert b1 is b2

    def test_module_exports(self):
        from galaxy_gateway.agent_bridge import __all__
        required = {
            "AgentBridge",
            "AgentBridgeConfig",
            "AgentBridgeMetrics",
            "HandoffContract",
            "get_agent_bridge",
        }
        assert required <= set(__all__)
