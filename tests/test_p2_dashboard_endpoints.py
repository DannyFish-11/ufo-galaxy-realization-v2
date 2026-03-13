"""
P2 Dashboard Backend Endpoint Tests
====================================

Tests for:
1. Device Execution Trace API  (DeviceTraceStore + /api/v1/devices/traces)
2. Agent–Device Collaboration API (/api/v1/agent-device/mapping, /assign, /status)
3. Multi-Device Orchestration API (/api/v1/orchestration/tasks)

These tests use the FastAPI TestClient and import the three in-process stores
directly from dashboard.backend.main so that no real network/galaxy_core is needed.
"""

import json
import os
import sys
import time
import pytest

# Make sure the project root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Import the FastAPI app and the in-process stores
# ---------------------------------------------------------------------------
from dashboard.backend.main import (
    app,
    DeviceTraceStore,
    _AgentDeviceRegistry,
    _OrchestrationStore,
    _device_trace_store,
    _agent_device_registry,
    _orchestration_store,
)

client = TestClient(app)


# ===========================================================================
# Helpers
# ===========================================================================

def _clear_stores() -> None:
    """Reset all in-process stores before each test."""
    _device_trace_store.clear()
    with _agent_device_registry._lock:
        _agent_device_registry._assignments.clear()
    with _orchestration_store._lock:
        _orchestration_store._tasks.clear()


# ===========================================================================
# 1. DeviceTraceStore unit tests
# ===========================================================================

class TestDeviceTraceStore:
    def setup_method(self):
        _clear_stores()

    def test_add_trace_and_retrieve_all(self, tmp_path):
        store = DeviceTraceStore(path=str(tmp_path / "traces.json"))
        t = store.add(
            device_id="dev-001",
            command="screenshot",
            params={},
            result={"success": True},
        )
        assert t["device_id"] == "dev-001"
        assert t["command"] == "screenshot"
        assert t["success"] is True
        assert len(store.all()) == 1

    def test_for_device_filters_correctly(self, tmp_path):
        store = DeviceTraceStore(path=str(tmp_path / "traces.json"))
        store.add(device_id="dev-001", command="click", params={}, result={"success": True})
        store.add(device_id="dev-002", command="swipe", params={}, result={"success": False, "error": "timeout"})
        assert len(store.for_device("dev-001")) == 1
        assert len(store.for_device("dev-002")) == 1
        assert len(store.for_device("dev-999")) == 0

    def test_persistence_across_reload(self, tmp_path):
        path = str(tmp_path / "traces.json")
        s1 = DeviceTraceStore(path=path)
        s1.add(device_id="dev-x", command="open_app", params={"app": "camera"}, result={"success": True})
        # New instance should reload from file
        s2 = DeviceTraceStore(path=path)
        assert len(s2.all()) == 1
        assert s2.all()[0]["command"] == "open_app"

    def test_max_cap_enforced(self, tmp_path):
        store = DeviceTraceStore(path=str(tmp_path / "traces.json"), max_traces=5)
        for i in range(10):
            store.add(device_id="d", command=f"cmd_{i}", params={}, result={"success": True})
        assert len(store.all()) == 5

    def test_failed_trace_stores_error(self, tmp_path):
        store = DeviceTraceStore(path=str(tmp_path / "traces.json"))
        t = store.add(
            device_id="dev-err",
            command="crash",
            params={},
            result={"success": False, "error": "device offline"},
        )
        assert t["success"] is False
        assert t["error"] == "device offline"


# ===========================================================================
# 2. Device Execution Trace API endpoints
# ===========================================================================

class TestDeviceTraceEndpoints:
    def setup_method(self):
        _clear_stores()

    def _seed(self, n: int = 3) -> None:
        for i in range(n):
            _device_trace_store.add(
                device_id=f"dev-{i % 2}",
                command=f"cmd_{i}",
                params={},
                result={"success": i % 2 == 0},
                agent_id="agent-a" if i == 0 else None,
                task_id="task-1" if i < 2 else None,
            )

    def test_get_all_traces_empty(self):
        r = client.get("/api/v1/devices/traces")
        assert r.status_code == 200
        data = r.json()
        assert data["traces"] == []
        assert data["total"] == 0

    def test_get_all_traces_with_data(self):
        self._seed(3)
        r = client.get("/api/v1/devices/traces")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 3
        assert len(data["traces"]) == 3

    def test_get_all_traces_limit(self):
        self._seed(5)
        r = client.get("/api/v1/devices/traces?limit=2")
        assert r.status_code == 200
        assert len(r.json()["traces"]) == 2

    def test_get_device_traces_specific(self):
        self._seed(4)
        r = client.get("/api/v1/devices/dev-0/traces")
        assert r.status_code == 200
        data = r.json()
        assert data["device_id"] == "dev-0"
        # Only traces for dev-0 returned (indices 0, 2 → 2 traces)
        assert all(t["device_id"] == "dev-0" for t in data["traces"])

    def test_get_device_traces_unknown_device(self):
        self._seed(2)
        r = client.get("/api/v1/devices/unknown-device/traces")
        assert r.status_code == 200
        assert r.json()["traces"] == []


# ===========================================================================
# 3. Agent–Device Collaboration Mapping endpoints
# ===========================================================================

class TestAgentDeviceMapping:
    def setup_method(self):
        _clear_stores()

    def test_mapping_empty(self):
        r = client.get("/api/v1/agent-device/mapping")
        assert r.status_code == 200
        data = r.json()
        assert "mappings" in data
        assert "total" in data
        assert "timestamp" in data

    def test_assign_and_retrieve(self):
        r = client.post(
            "/api/v1/agent-device/assign",
            json={"agent_id": "agent-1", "device_id": "dev-A", "task": "take screenshot", "status": "running"},
        )
        assert r.status_code == 200
        assert r.json()["success"] is True
        assignment = r.json()["assignment"]
        assert assignment["agent_id"] == "agent-1"
        assert assignment["device_id"] == "dev-A"

        r2 = client.get("/api/v1/agent-device/mapping")
        mappings = r2.json()["mappings"]
        assert any(m["agent_id"] == "agent-1" for m in mappings)

    def test_assign_missing_fields_returns_400(self):
        r = client.post("/api/v1/agent-device/assign", json={"agent_id": "x"})
        assert r.status_code == 400

    def test_update_status(self):
        _agent_device_registry.assign("agent-2", "dev-B", "run test", "running")
        r = client.patch("/api/v1/agent-device/agent-2/status", json={"status": "completed"})
        assert r.status_code == 200
        assert r.json()["success"] is True
        mappings = client.get("/api/v1/agent-device/mapping").json()["mappings"]
        entry = next((m for m in mappings if m["agent_id"] == "agent-2"), None)
        assert entry is not None
        assert entry["status"] == "completed"

    def test_update_status_missing_returns_400(self):
        r = client.patch("/api/v1/agent-device/agent-99/status", json={})
        assert r.status_code == 400

    def test_mapping_includes_trace_summary(self):
        _agent_device_registry.assign("agent-3", "dev-C", "cmd", "running")
        _device_trace_store.add(
            device_id="dev-C",
            command="click",
            params={},
            result={"success": True},
            agent_id="agent-3",
        )
        r = client.get("/api/v1/agent-device/mapping")
        entry = next((m for m in r.json()["mappings"] if m["agent_id"] == "agent-3"), None)
        assert entry is not None
        assert entry["trace_summary"] is not None
        assert entry["trace_summary"]["last_command"] == "click"


# ===========================================================================
# 4. Multi-Device Orchestration endpoints
# ===========================================================================

class TestOrchestrationEndpoints:
    def setup_method(self):
        _clear_stores()

    def test_list_tasks_empty(self):
        r = client.get("/api/v1/orchestration/tasks")
        assert r.status_code == 200
        data = r.json()
        assert data["tasks"] == []
        assert data["total"] == 0

    def test_create_task(self):
        payload = {
            "task_id": "task-abc",
            "description": "Capture screen on multiple devices",
            "device_assignments": [
                {"device_id": "dev-1", "action": "screenshot"},
                {"device_id": "dev-2", "action": "screenshot"},
            ],
            "status": "running",
        }
        r = client.post("/api/v1/orchestration/tasks", json=payload)
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert data["task"]["task_id"] == "task-abc"
        assert data["task"]["status"] == "running"

    def test_create_task_missing_description_returns_400(self):
        r = client.post("/api/v1/orchestration/tasks", json={"task_id": "t1"})
        assert r.status_code == 400

    def test_update_task_status(self):
        _orchestration_store.record(
            task_id="task-xyz",
            description="multi-device test",
            device_assignments=[],
            status="running",
        )
        r = client.patch("/api/v1/orchestration/tasks/task-xyz", json={"status": "completed"})
        assert r.status_code == 200
        assert r.json()["success"] is True

        tasks = client.get("/api/v1/orchestration/tasks").json()["tasks"]
        entry = next((t for t in tasks if t["task_id"] == "task-xyz"), None)
        assert entry is not None
        assert entry["status"] == "completed"

    def test_orchestration_tasks_include_device_traces(self):
        _orchestration_store.record(
            task_id="task-with-traces",
            description="test with traces",
            device_assignments=[],
            status="running",
        )
        _device_trace_store.add(
            device_id="dev-1",
            command="screenshot",
            params={},
            result={"success": True},
            task_id="task-with-traces",
        )
        r = client.get("/api/v1/orchestration/tasks")
        tasks = r.json()["tasks"]
        entry = next((t for t in tasks if t["task_id"] == "task-with-traces"), None)
        assert entry is not None
        assert len(entry["device_traces"]) == 1
        assert entry["device_traces"][0]["command"] == "screenshot"

    def test_list_tasks_limit(self):
        for i in range(5):
            _orchestration_store.record(
                task_id=f"task-{i}",
                description=f"task {i}",
                device_assignments=[],
                status="completed",
            )
        r = client.get("/api/v1/orchestration/tasks?limit=3")
        assert r.status_code == 200
        assert len(r.json()["tasks"]) == 3

    def test_auto_task_id_generation(self):
        r = client.post(
            "/api/v1/orchestration/tasks",
            json={"description": "auto id task", "status": "running"},
        )
        assert r.status_code == 200
        task_id = r.json()["task"]["task_id"]
        assert task_id.startswith("orch_")


# ===========================================================================
# 5. execute/parallel integration – trace + orchestration side effects
# ===========================================================================

class TestParallelExecuteP2Integration:
    def setup_method(self):
        _clear_stores()

    def test_parallel_execute_stores_orch_task(self):
        """Even without galaxy_core, a parallel execute should create an orch entry."""
        r = client.post(
            "/api/v1/execute/parallel",
            json={
                "task_id": "parallel-001",
                "description": "batch screenshot",
                "commands": [
                    {"device_id": "d1", "action": "screenshot", "params": {}},
                    {"device_id": "d2", "action": "screenshot", "params": {}},
                ],
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["task_id"] == "parallel-001"

        tasks = client.get("/api/v1/orchestration/tasks").json()["tasks"]
        entry = next((t for t in tasks if t["task_id"] == "parallel-001"), None)
        assert entry is not None

    def test_parallel_execute_stores_device_traces(self):
        client.post(
            "/api/v1/execute/parallel",
            json={
                "task_id": "parallel-002",
                "description": "test",
                "commands": [{"device_id": "d1", "action": "click", "params": {}}],
            },
        )
        traces = client.get("/api/v1/devices/d1/traces").json()["traces"]
        assert len(traces) >= 1
        assert any(t["task_id"] == "parallel-002" for t in traces)
