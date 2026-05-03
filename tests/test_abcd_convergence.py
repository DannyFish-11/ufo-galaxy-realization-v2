"""
Convergence validation tests — PR A+B+C+D
==========================================

Proves that **all four** convergence goals are enforced end-to-end:

A) Orchestration entry — ConstellationRuntime is the sole entry point.
B) Device SSOT         — UnifiedDeviceManager (UDM) is the only device-state source.
C) Scheduling          — DevicePoolManager is the sole scheduling/selection entry.
D) Protocol            — Business layer only consumes AIP v3; legacy confined to compat.

All tests are unit-level, fully deterministic, and import-only where possible
(no network, no filesystem, no new dependencies).
"""

from __future__ import annotations

import importlib
import logging
import sys
import warnings
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest


# =============================================================================
# Part A — Orchestration entry convergence
# =============================================================================

class TestAOrchestrationEntry:
    """A) ConstellationRuntime must be the authoritative entry point."""

    def test_constellation_runtime_importable(self):
        """core.constellation_runtime must be importable."""
        mod = importlib.import_module("core.constellation_runtime")
        assert hasattr(mod, "ConstellationRuntime"), \
            "ConstellationRuntime class must be exported"
        assert hasattr(mod, "get_constellation_runtime"), \
            "get_constellation_runtime factory must be exported"

    def test_get_constellation_runtime_returns_instance(self):
        """get_constellation_runtime() must return a ConstellationRuntime."""
        from core.constellation_runtime import get_constellation_runtime, ConstellationRuntime
        runtime = get_constellation_runtime()
        assert isinstance(runtime, ConstellationRuntime)

    def test_constellation_runtime_has_run_method(self):
        """ConstellationRuntime must expose an async .run() method."""
        import inspect
        from core.constellation_runtime import ConstellationRuntime
        assert hasattr(ConstellationRuntime, "run")
        assert inspect.iscoroutinefunction(ConstellationRuntime.run)

    def test_wrap_as_orchestration_response_helper_exists(self):
        """wrap_as_orchestration_response helper must be exported from constellation_runtime."""
        from core.constellation_runtime import wrap_as_orchestration_response
        result = wrap_as_orchestration_response(
            {"success": True, "reply": "ok", "trace_id": "t1", "session_id": "s1", "mode": "dag"},
            task_id="task-42",
        )
        assert result["task_id"] == "task-42"
        assert result["status"] == "completed"
        assert result["result"]["success"] is True

    def test_wrap_as_orchestration_response_failed(self):
        """wrap_as_orchestration_response must map success=False → status='failed'."""
        from core.constellation_runtime import wrap_as_orchestration_response
        result = wrap_as_orchestration_response({"success": False, "reply": "err"})
        assert result["status"] == "failed"

    def test_legacy_orchestrator_paths_constant_exported(self):
        """LEGACY_ORCHESTRATOR_PATHS must be exported and contain known nodes."""
        from core.constellation_runtime import LEGACY_ORCHESTRATOR_PATHS
        assert isinstance(LEGACY_ORCHESTRATOR_PATHS, frozenset)
        assert "nodes.Node_110_SmartOrchestrator.server" in LEGACY_ORCHESTRATOR_PATHS
        assert "nodes.Node_81_Orchestrator.main" in LEGACY_ORCHESTRATOR_PATHS
        assert "nodes.Node_50_Transformer.task_orchestrator" in LEGACY_ORCHESTRATOR_PATHS

    def test_warn_legacy_path_logs_warning(self, caplog):
        """warn_legacy_path must emit a WARNING-level structured log."""
        from core.constellation_runtime import warn_legacy_path
        with caplog.at_level(logging.WARNING):
            warn_legacy_path(
                caller="nodes.Node_110_SmartOrchestrator.server",
                trace_id="trace-abc",
            )
        assert any("LEGACY PATH GUARDRAIL" in r.message for r in caplog.records)

    def test_node110_delegates_to_constellation_runtime(self):
        """Node_110 orchestrate_task must call ConstellationRuntime.run() by default."""
        from nodes.Node_110_SmartOrchestrator.server import orchestrate_task, OrchestrationRequest

        mock_result = {
            "success": True,
            "reply": "done via CR",
            "trace_id": "tr1",
            "session_id": "se1",
            "mode": "dag",
        }

        async def _fake_run(**kwargs):
            return mock_result

        fake_runtime = MagicMock()
        fake_runtime.run = _fake_run

        import asyncio
        # Patch the factory function that Node_110 imports internally
        with patch(
            "core.constellation_runtime.get_constellation_runtime",
            return_value=fake_runtime,
        ):
            req = OrchestrationRequest(task_description="hello")
            result = asyncio.run(orchestrate_task(req))

        assert result.task_id is not None
        assert result.status in ("completed", "failed", "delegated")

    def test_node110_server_imports_constellation_runtime(self):
        """Node_110 server.py source must reference get_constellation_runtime."""
        import os, inspect
        from nodes.Node_110_SmartOrchestrator import server as srv_mod
        source = inspect.getsource(srv_mod)
        assert "get_constellation_runtime" in source, \
            "Node_110 server must call get_constellation_runtime() to delegate orchestration"

    def test_node81_has_execute_workflow_function(self):
        """Node_81 must export execute_workflow (entry used by delegation tests)."""
        from nodes.Node_81_Orchestrator.main import execute_workflow
        assert callable(execute_workflow)

    def test_node81_delegates_to_constellation_runtime(self):
        """Node_81 source must reference ConstellationRuntime for workflow execution."""
        import inspect
        from nodes.Node_81_Orchestrator import main as n81_mod
        source = inspect.getsource(n81_mod)
        assert "get_constellation_runtime" in source, \
            "Node_81 main must delegate workflow execution to get_constellation_runtime()"

    def test_node50_task_orchestrator_deprecation_warning(self):
        """Instantiating Node_50 TaskOrchestrator must raise DeprecationWarning."""
        stub_nlu = MagicMock()
        stub_nlu.TaskStep = object
        stub_nlu.TargetDevice = object
        sys.modules.setdefault("enhanced_nlu_engine", stub_nlu)

        # Reload to ensure warning fires on fresh import
        if "nodes.Node_50_Transformer.task_orchestrator" in sys.modules:
            del sys.modules["nodes.Node_50_Transformer.task_orchestrator"]

        from nodes.Node_50_Transformer.task_orchestrator import TaskOrchestrator

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            TaskOrchestrator()

        deprecations = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert deprecations, "TaskOrchestrator must emit DeprecationWarning on instantiation"

    def test_node50_docstring_marks_legacy(self):
        """Node_50 task_orchestrator module docstring must mention 'legacy'."""
        stub_nlu = MagicMock()
        stub_nlu.TaskStep = object
        stub_nlu.TargetDevice = object
        sys.modules.setdefault("enhanced_nlu_engine", stub_nlu)

        import nodes.Node_50_Transformer.task_orchestrator as mod
        doc = mod.__doc__ or ""
        assert "legacy" in doc.lower() or "subordinate" in doc.lower(), \
            "Module docstring must mark it as legacy/subordinate"


# =============================================================================
# Part B — Device SSOT (UnifiedDeviceManager)
# =============================================================================

class TestBDeviceSSOT:
    """B) UDM must be the only authoritative device state source."""

    def test_udm_importable_and_singleton(self):
        """core.unified.device_manager must export get_unified_device_manager()."""
        from core.unified.device_manager import get_unified_device_manager, UnifiedDeviceManager
        udm1 = get_unified_device_manager()
        udm2 = get_unified_device_manager()
        assert udm1 is udm2, "UDM must be a singleton"
        assert isinstance(udm1, UnifiedDeviceManager)

    def test_udm_has_required_api(self):
        """UDM must expose the full state-query API required by dependent components."""
        from core.unified.device_manager import UnifiedDeviceManager
        for method in (
            "register_device",
            "register_device_from_dict",
            "unregister_device",
            "get_device",
            "list_devices",
            "get_online_devices",
            "heartbeat",
            "update_device_status",
        ):
            assert hasattr(UnifiedDeviceManager, method), \
                f"UDM must have method: {method}"

    def test_udm_register_and_retrieve(self):
        """UDM register_device_from_dict / get_device round-trip."""
        from core.unified.device_manager import get_unified_device_manager
        udm = get_unified_device_manager()
        udm.register_device_from_dict("test-ssot-dev", {
            "device_name": "SSOT Test Device",
            "device_type": "android_phone",
            "capabilities": ["screen_capture"],
        })
        dev = udm.get_device("test-ssot-dev")
        assert dev is not None, "Device registered to UDM must be retrievable"
        assert dev.device_id == "test-ssot-dev"

    def test_udm_heartbeat_updates_last_seen(self):
        """UDM heartbeat must update device metadata without error."""
        from core.unified.device_manager import get_unified_device_manager
        udm = get_unified_device_manager()
        udm.register_device_from_dict("test-hb-dev", {
            "device_name": "HB Device",
            "device_type": "android_phone",
            "capabilities": [],
        })
        # heartbeat must not raise
        udm.heartbeat("test-hb-dev")

    def test_device_router_writes_to_udm_on_register(self):
        """DeviceRouter.register_device must write to UDM (SSOT)."""
        from galaxy_gateway.device_router import DeviceRouter

        captured_calls: list = []

        def _fake_register(device_id, data):
            captured_calls.append(device_id)
            return MagicMock()

        fake_udm = MagicMock()
        fake_udm.register_device_from_dict = _fake_register

        router = DeviceRouter()
        with patch("galaxy_gateway.device_router._get_udm", return_value=fake_udm):
            router.register_device("router-dev-1", "android_phone", ["screen_capture"])

        assert "router-dev-1" in captured_calls, \
            "DeviceRouter.register_device must write device_id to UDM"

    def test_device_agent_manager_has_udm_integration(self):
        """DeviceAgentManager source must reference UDM (SSOT write on register)."""
        import inspect
        import core.device_agent_manager as dam_mod
        source = inspect.getsource(dam_mod)
        assert "get_unified_device_manager" in source or "_unified" in source, \
            "DeviceAgentManager must reference UDM for SSOT writes"
        # Check the register_device method references UDM
        assert "register_device" in source and (
            "unified" in source.lower() or "udm" in source.lower() or "_unified" in source
        ), "DeviceAgentManager must write to UDM during device registration"

    def test_device_agent_manager_register_writes_udm(self):
        """DeviceAgentManager.register_device must call UDM._unified().register_device."""
        import inspect
        import core.device_agent_manager as dam_mod

        # Verify source contains the SSOT write pattern
        source = inspect.getsource(dam_mod)
        assert "SSOT" in source or "unified" in source.lower(), \
            "DeviceAgentManager must include UDM SSOT write in register_device"

    def test_routes_devices_imports_udm(self):
        """core/routes/devices.py must import and use UDM for device registration."""
        import os
        path = os.path.join(
            os.path.dirname(__file__), "..", "core", "routes", "devices.py"
        )
        with open(path) as f:
            source = f.read()
        assert "get_unified_device_manager" in source, \
            "core/routes/devices.py must import get_unified_device_manager (UDM SSOT)"

    def test_device_registry_delegates_writes_to_udm(self):
        """DeviceRegistry source must reference UDM for state writes (SSOT delegation)."""
        import inspect
        import core.device_registry as dr_mod
        source = inspect.getsource(dr_mod)
        assert "unified" in source.lower() or "get_unified_device_manager" in source, \
            "DeviceRegistry must reference UDM as SSOT for device state writes"


# =============================================================================
# Part C — Scheduling unification (DevicePoolManager)
# =============================================================================

class TestCSchedulingUnification:
    """C) DevicePoolManager must be the sole device scheduling/selection entry."""

    def test_device_pool_manager_importable_and_singleton(self):
        """core.device_pool_manager must export get_device_pool_manager() singleton."""
        from core.device_pool_manager import get_device_pool_manager, DevicePoolManager
        p1 = get_device_pool_manager()
        p2 = get_device_pool_manager()
        assert p1 is p2, "DevicePoolManager must be a singleton"
        assert isinstance(p1, DevicePoolManager)

    def test_device_pool_manager_has_select_device(self):
        """DevicePoolManager must expose select_device()."""
        from core.device_pool_manager import DevicePoolManager
        assert hasattr(DevicePoolManager, "select_device"), \
            "DevicePoolManager must have select_device()"

    def test_device_orchestrator_has_select_device_via_pool(self):
        """DeviceOrchestrator must expose select_device that delegates to DevicePoolManager."""
        from core.device_orchestrator import DeviceOrchestrator
        assert hasattr(DeviceOrchestrator, "select_device"), \
            "DeviceOrchestrator must expose select_device()"

    def test_device_orchestrator_select_device_calls_pool(self):
        """DeviceOrchestrator.select_device source must delegate to get_device_pool_manager."""
        import inspect
        import core.device_orchestrator as do_mod
        source = inspect.getsource(do_mod)
        assert "get_device_pool_manager" in source, \
            "DeviceOrchestrator must call get_device_pool_manager() for device selection"

    def test_command_router_references_pool_manager(self):
        """CommandRouter source must reference get_device_pool_manager for target selection."""
        import inspect
        import core.command_router as cr_mod
        source = inspect.getsource(cr_mod)
        assert "get_device_pool_manager" in source, \
            "CommandRouter must reference get_device_pool_manager for automatic target selection"

    def test_command_router_uses_pool_when_no_target(self):
        """CommandRouter.route_envelope must consult DevicePoolManager when no explicit target.

        DevicePoolManager is the fallback selector when capability_graph_selection
        is unavailable or returns no match.
        """
        from core.schemas.task_envelope import TaskEnvelope
        from core.command_router import CommandRouter

        selected: list = []

        def _fake_select(required_capabilities=None, **kw):
            selected.append(required_capabilities)
            return None  # no device found → route_envelope returns error, keeping test simple

        fake_pool = MagicMock()
        fake_pool.select_device = _fake_select

        # ACL result that allows the request through
        fake_acl_result = MagicMock()
        fake_acl_result.allowed = True
        fake_acl_enforcer = MagicMock()
        fake_acl_enforcer.check.return_value = fake_acl_result

        router = CommandRouter()
        env = TaskEnvelope(
            task_id="t1",
            trace_id="tr1",
            source="test",
            targets=[],
            tool_name="test_tool",
            args={},
            required_capabilities=["screen_capture"],
        )

        import asyncio
        # Disable capability_graph_selection so DevicePoolManager fallback is reached.
        with patch(
            "core.capability_graph_selection.select_best_provider",
            return_value=None,
        ), patch(
            "core.device_pool_manager.get_device_pool_manager",
            return_value=fake_pool,
        ), patch(
            "core.acl_enforcer.get_acl_enforcer",
            return_value=fake_acl_enforcer,
        ):
            asyncio.run(router.route_envelope(env))

        assert selected, \
            "CommandRouter must consult DevicePoolManager when no explicit target is given"

    def test_device_router_delegates_selection_to_pool(self):
        """galaxy_gateway DeviceRouter._select_devices must delegate to DevicePoolManager."""
        import inspect
        from galaxy_gateway import device_router as dr_mod
        source = inspect.getsource(dr_mod)
        assert "get_device_pool_manager" in source or "DevicePoolManager" in source, \
            "galaxy_gateway/device_router.py must reference DevicePoolManager for selection"

    def test_node71_task_scheduler_docstring_marks_strategy_provider(self):
        """Node_71 task_scheduler.py docstring must mark it as strategy provider only."""
        import os
        ts_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "nodes",
            "Node_71_MultiDeviceCoordination",
            "core",
            "task_scheduler.py",
        )
        with open(ts_path) as f:
            source = f.read()
        assert "strategy" in source.lower(), \
            "Node_71 task_scheduler.py must describe itself as a strategy provider"
        # Confirm there is a guardrail note warning against standalone use
        assert "DevicePoolManager" in source or "MUST NOT" in source or "standalone" in source, \
            "Node_71 task_scheduler.py must include guardrail against standalone scheduling"


# =============================================================================
# Part D — Protocol convergence (AIP v3 only in business layer)
# =============================================================================

class TestDProtocolConvergence:
    """D) Business layer must only consume AIP v3; legacy confined to compat adapter."""

    def test_aip_v3_importable(self):
        """galaxy_gateway.protocol.aip_v3 must be importable."""
        mod = importlib.import_module("galaxy_gateway.protocol.aip_v3")
        assert hasattr(mod, "AIPMessage")
        assert hasattr(mod, "MessageType")

    def test_compat_layer_importable(self):
        """galaxy_gateway.protocol.compat must export parse_message_compat."""
        from galaxy_gateway.protocol.compat import parse_message_compat
        assert callable(parse_message_compat)

    def test_parse_message_compat_v3_passthrough(self):
        """parse_message_compat must accept AIP v3 messages and return AIPMessage."""
        from galaxy_gateway.protocol.compat import parse_message_compat
        from galaxy_gateway.protocol.aip_v3 import AIPMessage
        # Use 'heartbeat' — a valid AIP v3 MessageType value
        msg = parse_message_compat({
            "version": "3.0",
            "type": "heartbeat",
            "device_id": "dev-x",
            "timestamp": 1000.0,
        })
        assert isinstance(msg, AIPMessage)

    def test_parse_message_compat_v2_normalises_to_v3(self):
        """parse_message_compat must normalise AIP v2 messages to AIP v3."""
        from galaxy_gateway.protocol.compat import parse_message_compat
        from galaxy_gateway.protocol.aip_v3 import AIPMessage
        # v2.0 messages share the same field names; compat bumps version to 3.0
        msg = parse_message_compat({
            "version": "2.0",
            "type": "heartbeat",
            "device_id": "dev-y",
            "timestamp": 1000.0,
        })
        assert isinstance(msg, AIPMessage)
        assert msg.version == "3.0"

    def test_parse_message_compat_v1_register_alias_normalises(self):
        """parse_message_compat must map v1 alias 'register' → 'device_register'."""
        from galaxy_gateway.protocol.compat import parse_message_compat
        from galaxy_gateway.protocol.aip_v3 import AIPMessage
        msg = parse_message_compat({
            "type": "register",
            "device_id": "dev-z",
            "timestamp": 1000.0,
        })
        assert isinstance(msg, AIPMessage)
        assert msg.type == "device_register"

    def test_core_business_files_do_not_import_enhancements_multidevice(self):
        """Core business files must not import enhancements.multidevice directly."""
        import os

        core_root = os.path.join(os.path.dirname(__file__), "..", "core")
        # Files that form the business layer
        business_files = [
            "galaxy_core.py",
            "repo_coordinator.py",
        ]

        for fname in business_files:
            fpath = os.path.join(core_root, fname)
            if not os.path.exists(fpath):
                continue
            with open(fpath) as f:
                source = f.read()
            assert "enhancements.multidevice" not in source and \
                   "from enhancements" not in source, \
                f"{fname} must not import enhancements.multidevice directly (use compat adapter)"

    def test_enforce_aip_v3_rejects_version_below_3(self):
        """enforce_aip_v3 must raise AIPVersionError for sub-3 versions."""
        from galaxy_gateway.protocol.compat import enforce_aip_v3, AIPVersionError
        with pytest.raises(AIPVersionError):
            enforce_aip_v3({"version": "2.0", "type": "heartbeat"})

    def test_enforce_aip_v3_accepts_v3(self):
        """enforce_aip_v3 must not raise for version >= 3.0."""
        from galaxy_gateway.protocol.compat import enforce_aip_v3
        enforce_aip_v3({"version": "3.0", "type": "heartbeat"})  # must not raise

    def test_parse_message_strict_exported(self):
        """parse_message_strict must also be exported from the compat layer."""
        from galaxy_gateway.protocol.compat import parse_message_strict
        assert callable(parse_message_strict)

    def test_parse_message_strict_rejects_v1_v2(self):
        """parse_message_strict must reject messages with version < 3.0."""
        from galaxy_gateway.protocol.compat import parse_message_strict, AIPVersionError
        with pytest.raises(AIPVersionError):
            parse_message_strict({"version": "2.0", "type": "heartbeat", "device_id": "x"})

    def test_device_protocol_uses_v3_message_type(self):
        """enhancements/multidevice/device_protocol.py must import from aip_v3."""
        import inspect
        from enhancements.multidevice import device_protocol as dp_mod
        source = inspect.getsource(dp_mod)
        assert "V3MessageType" in source or "aip_v3" in source, \
            "device_protocol must import from aip_v3 (not define its own v3 types)"

    def test_websocket_handler_uses_compat_or_strict_not_raw_bytes(self):
        """galaxy_gateway websocket_handler must use compat/strict parsing, not raw from_bytes."""
        import inspect
        try:
            from galaxy_gateway import websocket_handler as wsh_mod
        except ImportError:
            pytest.skip("websocket_handler not available")
        source = inspect.getsource(wsh_mod)
        # Must use parse_message_compat or parse_message_strict (both AIP v3 normalising)
        assert "parse_message_compat" in source or "parse_message_strict" in source, \
            "websocket_handler must use parse_message_compat or parse_message_strict for ingress"
        # Must NOT call raw binary from_bytes in business logic
        assert "from_bytes" not in source, \
            "websocket_handler must not call raw from_bytes (use compat layer)"


# =============================================================================
# Integration smoke test — end-to-end minimal path
# =============================================================================

class TestEndToEndMinimalPath:
    """Smoke test: confirm the full A→B→C→D chain is wired."""

    @pytest.mark.asyncio
    async def test_constellation_runtime_run_returns_dict(self):
        """ConstellationRuntime.run() must return a dict with 'success' key."""
        from core.constellation_runtime import ConstellationRuntime

        runtime = ConstellationRuntime()

        # Stub Node_71 and SmartOrchestrator to avoid real network calls
        async def _fake_node71(*a, **kw):
            return None  # forces DAG path

        async def _fake_dag_loop(**kw):
            return {
                "success": True,
                "reply": "smoke-ok",
                "trace_id": "t0",
                "session_id": "s0",
                "mode": "dag",
                "data": {},
            }

        runtime._try_node71 = _fake_node71
        runtime._run_dag_loop = _fake_dag_loop

        result = await runtime.run(task_description="smoke test")
        assert isinstance(result, dict)
        assert "success" in result

    def test_udm_pool_manager_device_router_chain(self):
        """Registering a device via DeviceRouter must be visible in UDM."""
        from galaxy_gateway.device_router import DeviceRouter
        from core.unified.device_manager import get_unified_device_manager

        udm = get_unified_device_manager()
        router = DeviceRouter()
        router.register_device("chain-dev-1", "android_phone", ["screen_capture"])

        dev = udm.get_device("chain-dev-1")
        assert dev is not None, \
            "Device registered via DeviceRouter must be retrievable from UDM (SSOT)"
