"""tests/test_pr1_unified_architecture.py
==========================================

PR-1 Block-1 — Unified Architecture Contract + Entrypoint + Legacy Adapters + State Schema

Tests covering:

1.  docs/architecture/unified_system_contract.md exists with canonical sections.
2.  docs/architecture/module_ownership_map.md exists with key module entries.
3.  core/unified/entrypoint_router.py — EntrypointRouter, get_entrypoint_router, reset_entrypoint_router.
4.  EntrypointRouter.route_request() stamps canonical metadata.
5.  EntrypointRouter.route_request() stamps legacy metadata when via_legacy_adapter=True.
6.  EntrypointRouter stats() counts canonical and legacy requests separately.
7.  EntrypointRouter singleton pattern (get/reset).
8.  EntrypointRouter.route_request() returns handler result augmented with _routing key.
9.  EntrypointRouter._emit_routing_event() is best-effort (never raises).
10. core/unified/state_schema.py — all five state dataclasses importable.
11. DeviceState.to_dict() / from_dict() round-trip.
12. TaskState.to_dict() / from_dict() round-trip.
13. CognitiveState.to_dict() / from_dict() round-trip.
14. PresenceState.to_dict() / from_dict() round-trip.
15. ExecutionState.to_dict() / from_dict() round-trip.
16. EntryPath, TaskStatus, PresencePhase, ExecutionStatus enums.
17. core/legacy_adapters/__init__.py — adapters importable.
18. LegacyConnectionManagerAdapter — delegates to unified (method delegation).
19. LegacyDeviceAgentManagerAdapter — get_device delegates to unified.
20. LegacyDeviceAgentManagerAdapter — heartbeat delegates to unified.
21. state_event_bus.emit_state() — accepts DeviceState and publishes event.
22. state_event_bus.emit_state() — accepts TaskState with status=running.
23. state_event_bus.emit_state() — accepts PresenceState and selects correct event type.
24. state_event_bus.emit_state() — never raises on bad input.
25. task_lifecycle._emit_state_bus_event — emits unified TaskState on status=running.
26. core/unified/__init__.py exports EntrypointRouter and state schema types.
27. core/routes/chat.py imports and touches EntrypointRouter (canonical path stamping).
28. core/openclawd.py contains entrypoint router stamp logic.
29. Architecture docs cross-reference each other.
30. All new modules pass basic import sanity check.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
import types
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPO_ROOT = pathlib.Path(__file__).parent.parent


# ===========================================================================
# 1–2: Documentation files
# ===========================================================================


class TestDocumentationFiles:
    def test_unified_system_contract_exists(self):
        f = REPO_ROOT / "docs" / "architecture" / "unified_system_contract.md"
        assert f.exists(), "docs/architecture/unified_system_contract.md must exist"

    def test_unified_system_contract_has_canonical_flow(self):
        f = REPO_ROOT / "docs" / "architecture" / "unified_system_contract.md"
        content = f.read_text(encoding="utf-8")
        assert "EntrypointRouter" in content or "entrypoint_router" in content
        assert "OpenClawd" in content
        assert "StateEventBus" in content or "state_event_bus" in content

    def test_unified_system_contract_has_rules(self):
        f = REPO_ROOT / "docs" / "architecture" / "unified_system_contract.md"
        content = f.read_text(encoding="utf-8")
        assert "legacy" in content.lower()
        assert "adapter" in content.lower()

    def test_module_ownership_map_exists(self):
        f = REPO_ROOT / "docs" / "architecture" / "module_ownership_map.md"
        assert f.exists(), "docs/architecture/module_ownership_map.md must exist"

    def test_module_ownership_map_has_entries(self):
        f = REPO_ROOT / "docs" / "architecture" / "module_ownership_map.md"
        content = f.read_text(encoding="utf-8")
        assert "OpenClawd" in content
        assert "UnifiedDeviceManager" in content or "device_manager" in content
        assert "entrypoint_router" in content or "EntrypointRouter" in content

    def test_docs_cross_reference(self):
        contract = (REPO_ROOT / "docs" / "architecture" / "unified_system_contract.md").read_text()
        ownership = (REPO_ROOT / "docs" / "architecture" / "module_ownership_map.md").read_text()
        assert "module_ownership_map" in contract or "Module Ownership" in contract
        assert "unified_system_contract" in ownership or "unified system" in ownership.lower()


# ===========================================================================
# 3–9: EntrypointRouter
# ===========================================================================


class TestEntrypointRouter:
    def setup_method(self):
        from core.unified.entrypoint_router import reset_entrypoint_router
        reset_entrypoint_router()

    def teardown_method(self):
        from core.unified.entrypoint_router import reset_entrypoint_router
        reset_entrypoint_router()

    def test_import(self):
        from core.unified.entrypoint_router import (
            EntrypointRouter,
            get_entrypoint_router,
            reset_entrypoint_router,
        )
        assert EntrypointRouter is not None

    def test_singleton(self):
        from core.unified.entrypoint_router import get_entrypoint_router
        r1 = get_entrypoint_router()
        r2 = get_entrypoint_router()
        assert r1 is r2

    def test_reset(self):
        from core.unified.entrypoint_router import get_entrypoint_router, reset_entrypoint_router
        r1 = get_entrypoint_router()
        reset_entrypoint_router()
        r2 = get_entrypoint_router()
        assert r1 is not r2

    @pytest.mark.asyncio
    async def test_route_request_canonical_metadata(self):
        from core.unified.entrypoint_router import EntrypointRouter

        router = EntrypointRouter()
        captured: Dict[str, Any] = {}

        async def handler(**kwargs):
            captured.update(kwargs)
            return {"success": True, "response": "ok"}

        result = await router.route_request(
            message="hello",
            source="test",
            handler=handler,
        )
        assert result["_routing"]["entry_path"] == "canonical"
        assert result["_routing"]["via_legacy_adapter"] is False
        assert result["_routing"]["source"] == "test"
        assert "trace_id" in result["_routing"]

    @pytest.mark.asyncio
    async def test_route_request_legacy_metadata(self):
        from core.unified.entrypoint_router import EntrypointRouter

        router = EntrypointRouter()

        async def handler(**kwargs):
            return {"success": True}

        result = await router.route_request(
            message="hello",
            source="legacy_test",
            handler=handler,
            via_legacy_adapter=True,
        )
        assert result["_routing"]["entry_path"] == "legacy"
        assert result["_routing"]["via_legacy_adapter"] is True

    @pytest.mark.asyncio
    async def test_stats_incremented(self):
        from core.unified.entrypoint_router import EntrypointRouter

        router = EntrypointRouter()

        async def handler(**kwargs):
            return {}

        await router.route_request(message="a", source="s1", handler=handler)
        await router.route_request(
            message="b", source="s2", handler=handler, via_legacy_adapter=True
        )

        stats = router.stats()
        assert stats["total"] == 2
        assert stats["canonical"] == 1
        assert stats["legacy"] == 1

    @pytest.mark.asyncio
    async def test_route_request_returns_handler_result(self):
        from core.unified.entrypoint_router import EntrypointRouter

        router = EntrypointRouter()

        async def handler(**kwargs):
            return {"custom_key": "custom_value", "success": True}

        result = await router.route_request(
            message="hi", source="s", handler=handler
        )
        assert result["custom_key"] == "custom_value"
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_emit_routing_event_never_raises(self):
        from core.unified.entrypoint_router import EntrypointRouter

        router = EntrypointRouter()
        # Should not raise even if state_event_bus is not importable
        router._emit_routing_event({"trace_id": "test", "entry_path": "canonical"})

    @pytest.mark.asyncio
    async def test_trace_id_preserved_when_provided(self):
        from core.unified.entrypoint_router import EntrypointRouter

        router = EntrypointRouter()

        async def handler(**kwargs):
            return {}

        fixed_trace = "fixed-trace-001"
        result = await router.route_request(
            message="x", source="s", handler=handler, trace_id=fixed_trace
        )
        assert result["_routing"]["trace_id"] == fixed_trace


# ===========================================================================
# 10–16: State schema
# ===========================================================================


class TestStateSchema:
    def test_all_types_importable(self):
        from core.unified.state_schema import (
            DeviceState,
            TaskState,
            CognitiveState,
            PresenceState,
            ExecutionState,
            EntryPath,
            TaskStatus,
            PresencePhase,
            ExecutionStatus,
        )
        assert DeviceState is not None
        assert TaskState is not None
        assert CognitiveState is not None
        assert PresenceState is not None
        assert ExecutionState is not None

    def test_device_state_roundtrip(self):
        from core.unified.state_schema import DeviceState
        ds = DeviceState(
            device_id="dev-001",
            status="online",
            device_type="android",
            capabilities=["screen", "touch"],
            entry_path="canonical",
        )
        d = ds.to_dict()
        assert d["device_id"] == "dev-001"
        assert d["status"] == "online"
        assert d["capabilities"] == ["screen", "touch"]

        ds2 = DeviceState.from_dict(d)
        assert ds2.device_id == ds.device_id
        assert ds2.status == ds.status

    def test_task_state_roundtrip(self):
        from core.unified.state_schema import TaskState
        ts = TaskState(
            task_id="task-001",
            tool_name="open_app",
            status="running",
            entry_path="canonical",
        )
        d = ts.to_dict()
        assert d["task_id"] == "task-001"
        assert d["status"] == "running"

        ts2 = TaskState.from_dict(d)
        assert ts2.task_id == ts.task_id

    def test_cognitive_state_roundtrip(self):
        from core.unified.state_schema import CognitiveState
        cs = CognitiveState(
            session_id="sess-001",
            activation=0.7,
            uncertainty=0.3,
        )
        d = cs.to_dict()
        assert d["activation"] == 0.7
        cs2 = CognitiveState.from_dict(d)
        assert cs2.activation == cs.activation

    def test_presence_state_roundtrip(self):
        from core.unified.state_schema import PresenceState
        ps = PresenceState(
            runtime_session_id="rt-001",
            phase="manifest",
            intensity=0.9,
        )
        d = ps.to_dict()
        assert d["phase"] == "manifest"
        ps2 = PresenceState.from_dict(d)
        assert ps2.phase == ps.phase

    def test_execution_state_roundtrip(self):
        from core.unified.state_schema import ExecutionState
        es = ExecutionState(
            task_id="task-001",
            tool_name="close_app",
            status="success",
            latency_ms=123.4,
        )
        d = es.to_dict()
        assert d["latency_ms"] == 123.4
        es2 = ExecutionState.from_dict(d)
        assert es2.latency_ms == es.latency_ms

    def test_entry_path_enum(self):
        from core.unified.state_schema import EntryPath
        assert EntryPath.CANONICAL.value == "canonical"
        assert EntryPath.LEGACY.value == "legacy"

    def test_task_status_enum(self):
        from core.unified.state_schema import TaskStatus
        assert TaskStatus.RUNNING.value == "running"
        assert TaskStatus.DONE.value == "done"
        assert TaskStatus.FAILED.value == "failed"

    def test_presence_phase_enum(self):
        from core.unified.state_schema import PresencePhase
        assert PresencePhase.SILENT.value == "silent"
        assert PresencePhase.LIMINAL.value == "liminal"
        assert PresencePhase.MANIFEST.value == "manifest"

    def test_execution_status_enum(self):
        from core.unified.state_schema import ExecutionStatus
        assert ExecutionStatus.SUCCESS.value == "success"
        assert ExecutionStatus.FAILURE.value == "failure"

    def test_from_dict_ignores_unknown_fields(self):
        from core.unified.state_schema import DeviceState
        d = DeviceState(device_id="x").to_dict()
        d["unknown_future_field"] = "some_value"
        ds = DeviceState.from_dict(d)  # must not raise
        assert ds.device_id == "x"


# ===========================================================================
# 17–20: Legacy adapters
# ===========================================================================


class TestLegacyAdapters:
    def test_package_importable(self):
        from core.legacy_adapters import (
            LegacyConnectionManagerAdapter,
            LegacyDeviceAgentManagerAdapter,
        )
        assert LegacyConnectionManagerAdapter is not None
        assert LegacyDeviceAgentManagerAdapter is not None

    def test_connection_manager_adapter_get_connection_delegates(self):
        from core.legacy_adapters.connection_manager_adapter import LegacyConnectionManagerAdapter

        adapter = LegacyConnectionManagerAdapter()
        mock_unified = MagicMock()
        mock_unified.get_connection.return_value = {"id": "c1"}
        adapter._unified = mock_unified

        result = adapter.get_connection("c1")
        mock_unified.get_connection.assert_called_once_with("c1")
        assert result == {"id": "c1"}

    def test_connection_manager_adapter_get_stats_delegates(self):
        from core.legacy_adapters.connection_manager_adapter import LegacyConnectionManagerAdapter

        adapter = LegacyConnectionManagerAdapter()
        mock_unified = MagicMock()
        mock_unified.get_stats.return_value = {"total": 5}
        adapter._unified = mock_unified

        stats = adapter.get_stats()
        assert stats == {"total": 5}

    def test_device_agent_manager_adapter_get_device_delegates(self):
        from core.legacy_adapters.device_agent_manager_adapter import (
            LegacyDeviceAgentManagerAdapter,
        )

        adapter = LegacyDeviceAgentManagerAdapter()
        mock_unified = MagicMock()
        mock_device = MagicMock()
        mock_unified.get_device.return_value = mock_device
        adapter._unified = mock_unified

        result = adapter.get_device("dev-001")
        mock_unified.get_device.assert_called_once_with("dev-001")
        assert result is mock_device

    def test_device_agent_manager_adapter_heartbeat_delegates(self):
        from core.legacy_adapters.device_agent_manager_adapter import (
            LegacyDeviceAgentManagerAdapter,
        )

        adapter = LegacyDeviceAgentManagerAdapter()
        mock_unified = MagicMock()
        adapter._unified = mock_unified

        adapter.heartbeat("dev-001")
        mock_unified.heartbeat.assert_called_once_with("dev-001")

    def test_device_agent_manager_adapter_get_all_devices_delegates(self):
        from core.legacy_adapters.device_agent_manager_adapter import (
            LegacyDeviceAgentManagerAdapter,
        )

        adapter = LegacyDeviceAgentManagerAdapter()
        mock_unified = MagicMock()
        mock_unified.list_devices.return_value = ["dev1", "dev2"]
        adapter._unified = mock_unified

        result = adapter.get_all_devices()
        mock_unified.list_devices.assert_called_once()
        assert result == ["dev1", "dev2"]


# ===========================================================================
# 21–24: state_event_bus.emit_state()
# ===========================================================================


class TestEmitState:
    def setup_method(self):
        from core.state_event_bus import reset_state_event_bus
        reset_state_event_bus()

    def teardown_method(self):
        from core.state_event_bus import reset_state_event_bus
        reset_state_event_bus()

    def test_emit_state_importable(self):
        from core.state_event_bus import emit_state
        assert callable(emit_state)

    def test_emit_state_device_state(self):
        from core.state_event_bus import emit_state, get_state_event_bus, StateEventType
        from core.unified.state_schema import DeviceState

        received = []

        bus = get_state_event_bus()
        token = bus.subscribe(StateEventType.DEVICE_UPDATED, lambda e: received.append(e))

        ds = DeviceState(device_id="dev-001", status="online")
        emit_state(ds, source="test")

        bus.unsubscribe(token)
        assert len(received) == 1
        assert received[0].payload.get("device_id") == "dev-001"

    def test_emit_state_task_state_running(self):
        from core.state_event_bus import emit_state, get_state_event_bus, StateEventType
        from core.unified.state_schema import TaskState

        received = []

        bus = get_state_event_bus()
        token = bus.subscribe(StateEventType.TASK_STARTED, lambda e: received.append(e))

        ts = TaskState(task_id="t-001", tool_name="open_app", status="running")
        emit_state(ts, source="test")

        bus.unsubscribe(token)
        assert len(received) == 1
        assert received[0].payload.get("task_id") == "t-001"

    def test_emit_state_presence_state_manifest(self):
        from core.state_event_bus import emit_state, get_state_event_bus, StateEventType
        from core.unified.state_schema import PresenceState

        received = []

        bus = get_state_event_bus()
        token = bus.subscribe(StateEventType.PHASE_MANIFEST, lambda e: received.append(e))

        ps = PresenceState(phase="manifest", intensity=1.0)
        emit_state(ps, source="test")

        bus.unsubscribe(token)
        assert len(received) == 1

    def test_emit_state_never_raises(self):
        from core.state_event_bus import emit_state

        # Pass garbage — must not raise
        emit_state(None, source="test")
        emit_state(42, source="test")
        emit_state(object(), source="test")


# ===========================================================================
# 25: task_lifecycle emits unified TaskState
# ===========================================================================


class TestTaskLifecycleUnifiedEmit:
    def setup_method(self):
        from core.state_event_bus import reset_state_event_bus
        reset_state_event_bus()

    def teardown_method(self):
        from core.state_event_bus import reset_state_event_bus
        reset_state_event_bus()

    def test_emit_state_bus_event_emits_task_state(self):
        from core.task_lifecycle import _emit_state_bus_event
        from core.state_event_bus import get_state_event_bus, StateEventType

        received = []
        bus = get_state_event_bus()
        token = bus.subscribe(StateEventType.TASK_STARTED, lambda e: received.append(e))

        envelope = MagicMock()
        envelope.task_id = "t-lifecycle-001"
        envelope.trace_id = "tr-001"
        envelope.session_id = "sess-001"
        envelope.tool_name = "test_tool"

        _emit_state_bus_event(envelope, "running")

        bus.unsubscribe(token)
        # Should have received at least one event
        assert len(received) >= 1


# ===========================================================================
# 26: core/unified/__init__.py exports
# ===========================================================================


class TestUnifiedInitExports:
    def test_entrypoint_router_exported(self):
        from core.unified import (
            EntrypointRouter,
            get_entrypoint_router,
            reset_entrypoint_router,
        )
        assert EntrypointRouter is not None

    def test_state_schema_exported(self):
        from core.unified import (
            EntryPath,
            TaskStatus,
            PresencePhase,
            ExecutionStatus,
            DeviceState,
            TaskState,
            CognitiveState,
            PresenceState,
            ExecutionState,
        )
        assert DeviceState is not None
        assert TaskState is not None


# ===========================================================================
# 27–28: chat.py and openclawd.py integration
# ===========================================================================


class TestChatAndOpenClawdIntegration:
    def test_chat_py_references_entrypoint_router(self):
        chat_file = REPO_ROOT / "core" / "routes" / "chat.py"
        content = chat_file.read_text(encoding="utf-8")
        assert "entrypoint_router" in content or "EntrypointRouter" in content, (
            "core/routes/chat.py must reference entrypoint_router (PR-1 Block-1)"
        )
        assert "entry_path" in content, (
            "core/routes/chat.py must stamp entry_path"
        )

    def test_openclawd_py_references_entrypoint_router(self):
        oc_file = REPO_ROOT / "core" / "openclawd.py"
        content = oc_file.read_text(encoding="utf-8")
        assert "entrypoint_router" in content or "EntrypointRouter" in content, (
            "core/openclawd.py must reference entrypoint_router (PR-1 Block-1)"
        )


# ===========================================================================
# 29: Architecture docs cross-reference
# ===========================================================================


class TestDocsCrossReference:
    def test_contract_references_ownership_map(self):
        f = REPO_ROOT / "docs" / "architecture" / "unified_system_contract.md"
        content = f.read_text(encoding="utf-8")
        assert "module_ownership_map" in content or "Module Ownership" in content

    def test_ownership_map_references_contract(self):
        f = REPO_ROOT / "docs" / "architecture" / "module_ownership_map.md"
        content = f.read_text(encoding="utf-8")
        assert "unified_system_contract" in content or "unified system" in content.lower()


# ===========================================================================
# 30: Basic import sanity check for all new modules
# ===========================================================================


class TestImportSanity:
    def test_entrypoint_router_module(self):
        import importlib
        mod = importlib.import_module("core.unified.entrypoint_router")
        assert hasattr(mod, "EntrypointRouter")
        assert hasattr(mod, "get_entrypoint_router")
        assert hasattr(mod, "reset_entrypoint_router")

    def test_state_schema_module(self):
        import importlib
        mod = importlib.import_module("core.unified.state_schema")
        for name in ("DeviceState", "TaskState", "CognitiveState", "PresenceState", "ExecutionState"):
            assert hasattr(mod, name), f"state_schema missing {name}"

    def test_legacy_adapters_module(self):
        import importlib
        mod = importlib.import_module("core.legacy_adapters")
        assert hasattr(mod, "LegacyConnectionManagerAdapter")
        assert hasattr(mod, "LegacyDeviceAgentManagerAdapter")

    def test_state_event_bus_emit_state(self):
        import importlib
        mod = importlib.import_module("core.state_event_bus")
        assert hasattr(mod, "emit_state"), "state_event_bus must export emit_state"
