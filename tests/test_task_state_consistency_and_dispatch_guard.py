"""tests/test_task_state_consistency_and_dispatch_guard.py
============================================================
PR-893: Task state consistency and registration dispatch guard.

Validates the two critical state-consistency fixes introduced by this PR:

1. ``submit_task_result`` REST endpoint now syncs ``CanonicalTaskRuntime``
   lifecycle to the same terminal state as ``task_queue``, eliminating the
   dual-track state drift where one surface reflects ``completed`` and the
   other still shows ``dispatched``.

2. ``AndroidBridge.assign_task`` raises
   ``DispatchBlockedByRegistrationGapError`` when the target device has
   recorded registration gaps, converting a previously silent best-effort gap
   into an explicit machine-observable dispatch block.

Coverage groups
---------------
A  — REST submit_task_result syncs CanonicalTaskRuntime (all result statuses)
B  — REST submit_task_result: task_queue and CanonicalTaskRuntime agree
C  — assign_task blocked when registration gaps present
D  — assign_task proceeds when device has no registration gaps
E  — DispatchBlockedByRegistrationGapError carries device_id and gaps
F  — Registration gap cleared → dispatch allowed
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ===========================================================================
# Helpers
# ===========================================================================

def _make_task_in_queue(task_queue: dict, status: str = "dispatched") -> str:
    """Insert a minimal task entry and return its task_id."""
    task_id = str(uuid.uuid4())
    task_queue[task_id] = {
        "task_id": task_id,
        "status": status,
        "created_at": datetime.now().isoformat(),
    }
    return task_id


def _register_task_in_canonical_runtime(task_id: str) -> None:
    """Register a CanonicalTask in the global runtime at DISPATCHED lifecycle."""
    from core.canonical_task import (
        build_canonical_task,
        get_canonical_task_runtime,
        TaskLifecycle,
        TaskOrigin,
    )
    task = build_canonical_task(
        task_id=task_id,
        origin=TaskOrigin.API_REQUEST,
        requested_action="test_action",
    )
    task.advance_lifecycle(TaskLifecycle.DISPATCHED)
    get_canonical_task_runtime().register(task)


# ===========================================================================
# A. submit_task_result syncs CanonicalTaskRuntime lifecycle
# ===========================================================================

class TestSubmitTaskResultSyncsCanonicalRuntime:
    """The REST result endpoint must update both task_queue and CanonicalTaskRuntime."""

    @pytest.fixture(autouse=True)
    def reset_runtime(self):
        from core.canonical_task import reset_canonical_task_runtime
        reset_canonical_task_runtime()
        yield
        reset_canonical_task_runtime()

    def _call_submit(self, app_client, task_id: str, status: Optional[str] = None):
        body = {}
        if status is not None:
            body["status"] = status
        return app_client.post(f"/api/v1/tasks/{task_id}/result", json=body)

    @pytest.fixture()
    def task_route_client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from core.routes.tasks import create_router
        from core.routes._shared import task_queue
        # Reset task_queue state
        task_queue.clear()
        app = FastAPI()
        app.include_router(create_router())
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client, task_queue
        task_queue.clear()

    def test_A01_success_result_syncs_completed_lifecycle(self, task_route_client):
        """A 'success' result must leave CanonicalTaskRuntime at COMPLETED."""
        from core.canonical_task import get_canonical_task_runtime, TaskLifecycle

        client, task_queue = task_route_client
        task_id = _make_task_in_queue(task_queue, status="dispatched")
        _register_task_in_canonical_runtime(task_id)

        resp = self._call_submit(client, task_id, status="success")
        assert resp.status_code == 200

        # task_queue should be completed
        assert task_queue[task_id]["status"] == "completed"

        # CanonicalTaskRuntime must also be COMPLETED
        runtime_task = get_canonical_task_runtime().get_by_task_id(task_id)
        assert runtime_task is not None, "Task not found in CanonicalTaskRuntime"
        assert runtime_task.lifecycle == TaskLifecycle.COMPLETED, (
            f"Expected COMPLETED, got {runtime_task.lifecycle!r}; "
            "task_queue says 'completed' but CanonicalTaskRuntime says otherwise — dual-track drift"
        )

    def test_A02_failed_result_syncs_failed_lifecycle(self, task_route_client):
        """A 'failed' result must leave CanonicalTaskRuntime at FAILED."""
        from core.canonical_task import get_canonical_task_runtime, TaskLifecycle

        client, task_queue = task_route_client
        task_id = _make_task_in_queue(task_queue, status="dispatched")
        _register_task_in_canonical_runtime(task_id)

        resp = self._call_submit(client, task_id, status="failed")
        assert resp.status_code == 200

        assert task_queue[task_id]["status"] == "failed"

        runtime_task = get_canonical_task_runtime().get_by_task_id(task_id)
        assert runtime_task is not None
        assert runtime_task.lifecycle == TaskLifecycle.FAILED, (
            f"Expected FAILED, got {runtime_task.lifecycle!r}"
        )

    def test_A03_error_result_syncs_failed_lifecycle(self, task_route_client):
        """An 'error' status (Android error taxonomy) must map to FAILED in runtime."""
        from core.canonical_task import get_canonical_task_runtime, TaskLifecycle

        client, task_queue = task_route_client
        task_id = _make_task_in_queue(task_queue, status="dispatched")
        _register_task_in_canonical_runtime(task_id)

        resp = self._call_submit(client, task_id, status="error")
        assert resp.status_code == 200

        assert task_queue[task_id]["status"] == "failed"

        runtime_task = get_canonical_task_runtime().get_by_task_id(task_id)
        assert runtime_task is not None
        assert runtime_task.lifecycle == TaskLifecycle.FAILED

    def test_A04_cancelled_result_syncs_cancelled_lifecycle(self, task_route_client):
        """A 'cancelled' result must leave CanonicalTaskRuntime at CANCELLED."""
        from core.canonical_task import get_canonical_task_runtime, TaskLifecycle

        client, task_queue = task_route_client
        task_id = _make_task_in_queue(task_queue, status="dispatched")
        _register_task_in_canonical_runtime(task_id)

        resp = self._call_submit(client, task_id, status="cancelled")
        assert resp.status_code == 200

        assert task_queue[task_id]["status"] == "cancelled"

        runtime_task = get_canonical_task_runtime().get_by_task_id(task_id)
        assert runtime_task is not None
        assert runtime_task.lifecycle == TaskLifecycle.CANCELLED

    def test_A05_degraded_result_syncs_degraded_lifecycle(self, task_route_client):
        """A 'degraded' result must leave CanonicalTaskRuntime at DEGRADED."""
        from core.canonical_task import get_canonical_task_runtime, TaskLifecycle

        client, task_queue = task_route_client
        task_id = _make_task_in_queue(task_queue, status="dispatched")
        _register_task_in_canonical_runtime(task_id)

        resp = self._call_submit(client, task_id, status="degraded")
        assert resp.status_code == 200

        assert task_queue[task_id]["status"] == "degraded"

        runtime_task = get_canonical_task_runtime().get_by_task_id(task_id)
        assert runtime_task is not None
        assert runtime_task.lifecycle == TaskLifecycle.DEGRADED

    def test_A06_absent_body_defaults_to_completed(self, task_route_client):
        """No body → completed in both task_queue and CanonicalTaskRuntime."""
        from core.canonical_task import get_canonical_task_runtime, TaskLifecycle

        client, task_queue = task_route_client
        task_id = _make_task_in_queue(task_queue, status="dispatched")
        _register_task_in_canonical_runtime(task_id)

        resp = client.post(f"/api/v1/tasks/{task_id}/result")
        assert resp.status_code == 200

        assert task_queue[task_id]["status"] == "completed"

        runtime_task = get_canonical_task_runtime().get_by_task_id(task_id)
        assert runtime_task is not None
        assert runtime_task.lifecycle == TaskLifecycle.COMPLETED


# ===========================================================================
# B. task_queue and CanonicalTaskRuntime agree after submit_task_result
# ===========================================================================

class TestTaskQueueAndRuntimeAgreement:
    """After submit_task_result the two state surfaces must not diverge."""

    @pytest.fixture(autouse=True)
    def reset_runtime(self):
        from core.canonical_task import reset_canonical_task_runtime
        reset_canonical_task_runtime()
        yield
        reset_canonical_task_runtime()

    @pytest.fixture()
    def task_route_client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from core.routes.tasks import create_router
        from core.routes._shared import task_queue
        task_queue.clear()
        app = FastAPI()
        app.include_router(create_router())
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client, task_queue
        task_queue.clear()

    @pytest.mark.parametrize("android_status,expected_status,expected_lifecycle", [
        ("success",   "completed", "completed"),
        ("failed",    "failed",    "failed"),
        ("error",     "failed",    "failed"),
        ("cancelled", "cancelled", "cancelled"),
        ("degraded",  "degraded",  "degraded"),
    ])
    def test_B01_status_surfaces_agree(
        self, task_route_client, android_status, expected_status, expected_lifecycle
    ):
        """task_queue and CanonicalTaskRuntime must report the same terminal state."""
        from core.canonical_task import get_canonical_task_runtime

        client, task_queue = task_route_client
        task_id = _make_task_in_queue(task_queue, status="dispatched")
        _register_task_in_canonical_runtime(task_id)

        resp = client.post(
            f"/api/v1/tasks/{task_id}/result", json={"status": android_status}
        )
        assert resp.status_code == 200

        tq_status = task_queue[task_id]["status"]
        runtime_task = get_canonical_task_runtime().get_by_task_id(task_id)
        runtime_lifecycle = runtime_task.lifecycle.value if runtime_task else None

        assert tq_status == expected_status, (
            f"task_queue has {tq_status!r}; expected {expected_status!r}"
        )
        assert runtime_lifecycle == expected_lifecycle, (
            f"CanonicalTaskRuntime has lifecycle={runtime_lifecycle!r}; "
            f"expected {expected_lifecycle!r}; "
            "the two state surfaces diverged — this is the dual-track drift PR-893 fixes"
        )


# ===========================================================================
# C. assign_task blocked when registration gaps present
# ===========================================================================

class TestAssignTaskRegistrationGapBlock:
    """assign_task must raise DispatchBlockedByRegistrationGapError when gaps exist."""

    @pytest.fixture(autouse=True)
    def clear_gaps(self):
        from galaxy_gateway.android.handlers.registration import clear_registration_gaps
        clear_registration_gaps()
        yield
        clear_registration_gaps()

    @pytest.fixture()
    def bridge(self):
        from galaxy_gateway.android_bridge import AndroidBridge
        b = AndroidBridge()
        # Insert a dummy device directly (bypasses registration handler so no gaps)
        from galaxy_gateway.android.models import AndroidDevice
        ws = MagicMock()
        ws.send = AsyncMock()
        d = MagicMock(spec=AndroidDevice)
        d.connected = True
        d.websocket = ws
        b._devices["gap-device"] = d
        return b

    @pytest.mark.asyncio
    async def test_C01_dispatch_blocked_when_gap_recorded(self, bridge):
        """assign_task raises when gaps are recorded for the target device."""
        from galaxy_gateway.android.handlers.registration import (
            record_registration_gap,
            DispatchBlockedByRegistrationGapError,
        )
        device_id = "gap-device"
        record_registration_gap(device_id, "attach_runtime_session")

        with pytest.raises(DispatchBlockedByRegistrationGapError) as exc_info:
            await bridge.assign_task(
                device_id=device_id,
                task_id=str(uuid.uuid4()),
                task_type="screenshot",
                payload={},
            )

        err = exc_info.value
        assert err.device_id == device_id
        assert "attach_runtime_session" in err.gaps

    @pytest.mark.asyncio
    async def test_C02_dispatch_blocked_with_multiple_gaps(self, bridge):
        """All recorded gaps are included in the raised error."""
        from galaxy_gateway.android.handlers.registration import (
            record_registration_gap,
            DispatchBlockedByRegistrationGapError,
        )
        device_id = "gap-device"
        record_registration_gap(device_id, "attach_runtime_session")
        record_registration_gap(device_id, "attached_runtime_session_registry")

        with pytest.raises(DispatchBlockedByRegistrationGapError) as exc_info:
            await bridge.assign_task(
                device_id=device_id,
                task_id=str(uuid.uuid4()),
                task_type="tap",
                payload={},
            )

        err = exc_info.value
        assert "attach_runtime_session" in err.gaps
        assert "attached_runtime_session_registry" in err.gaps
        assert len(err.gaps) == 2


# ===========================================================================
# D. assign_task proceeds when device has no registration gaps
# ===========================================================================

class TestAssignTaskAllowedWhenNoGaps:
    """assign_task must succeed (not raise) when device has no recorded gaps."""

    @pytest.fixture(autouse=True)
    def clear_gaps(self):
        from galaxy_gateway.android.handlers.registration import clear_registration_gaps
        clear_registration_gaps()
        yield
        clear_registration_gaps()

    @pytest.fixture()
    def bridge(self):
        from galaxy_gateway.android_bridge import AndroidBridge
        from galaxy_gateway.android.models import AndroidDevice
        b = AndroidBridge()
        ws = MagicMock()
        ws.send = AsyncMock()
        d = MagicMock(spec=AndroidDevice)
        d.connected = True
        d.websocket = ws
        b._devices["clean-device"] = d
        return b

    @pytest.mark.asyncio
    async def test_D01_dispatch_allowed_when_no_gaps(self, bridge):
        """When no gaps are recorded for a device, assign_task does not raise."""
        # No gaps recorded for "clean-device" — is_registration_fully_attached returns True
        sent: Dict[str, Any] = {}

        async def _fake_send(d_id, msg, **kwargs):
            sent.update(msg)
            return {"success": True}

        bridge.send_to_device = _fake_send  # type: ignore[method-assign]

        # Patch device_router so it falls back to send_to_device
        mock_router = MagicMock()
        mock_router.devices = {}

        with patch("galaxy_gateway.device_router.device_router", mock_router):
            result = await bridge.assign_task(
                device_id="clean-device",
                task_id="task-clean-001",
                task_type="screenshot",
                payload={},
            )

        assert sent.get("type") == "task_assign", (
            "assign_task should have sent task_assign; gap check must not have blocked"
        )


# ===========================================================================
# E. DispatchBlockedByRegistrationGapError structure
# ===========================================================================

class TestDispatchBlockedErrorStructure:
    """DispatchBlockedByRegistrationGapError carries device_id and gaps attributes."""

    def test_E01_error_has_device_id(self):
        from galaxy_gateway.android.handlers.registration import (
            DispatchBlockedByRegistrationGapError,
        )
        err = DispatchBlockedByRegistrationGapError("dev-abc", ["step_x"])
        assert err.device_id == "dev-abc"

    def test_E02_error_has_gaps(self):
        from galaxy_gateway.android.handlers.registration import (
            DispatchBlockedByRegistrationGapError,
        )
        err = DispatchBlockedByRegistrationGapError("dev-abc", ["step_x", "step_y"])
        assert err.gaps == ["step_x", "step_y"]

    def test_E03_error_is_runtime_error_subclass(self):
        from galaxy_gateway.android.handlers.registration import (
            DispatchBlockedByRegistrationGapError,
        )
        err = DispatchBlockedByRegistrationGapError("dev-z", ["attach"])
        assert isinstance(err, RuntimeError)

    def test_E04_error_message_contains_device_id(self):
        from galaxy_gateway.android.handlers.registration import (
            DispatchBlockedByRegistrationGapError,
        )
        err = DispatchBlockedByRegistrationGapError("dev-xyz", ["step_a"])
        assert "dev-xyz" in str(err)

    def test_E05_error_message_contains_gap_names(self):
        from galaxy_gateway.android.handlers.registration import (
            DispatchBlockedByRegistrationGapError,
        )
        err = DispatchBlockedByRegistrationGapError("dev-xyz", ["step_a", "step_b"])
        msg = str(err)
        assert "step_a" in msg
        assert "step_b" in msg


# ===========================================================================
# F. Registration gap cleared → dispatch allowed
# ===========================================================================

class TestGapClearedAllowsDispatch:
    """After clearing gaps for a device, assign_task must proceed normally."""

    @pytest.fixture(autouse=True)
    def clear_gaps(self):
        from galaxy_gateway.android.handlers.registration import clear_registration_gaps
        clear_registration_gaps()
        yield
        clear_registration_gaps()

    @pytest.fixture()
    def bridge(self):
        from galaxy_gateway.android_bridge import AndroidBridge
        from galaxy_gateway.android.models import AndroidDevice
        b = AndroidBridge()
        ws = MagicMock()
        ws.send = AsyncMock()
        d = MagicMock(spec=AndroidDevice)
        d.connected = True
        d.websocket = ws
        b._devices["recover-device"] = d
        return b

    @pytest.mark.asyncio
    async def test_F01_dispatch_blocked_before_clear(self, bridge):
        """Dispatch is blocked while gaps are present."""
        from galaxy_gateway.android.handlers.registration import (
            record_registration_gap,
            DispatchBlockedByRegistrationGapError,
        )
        record_registration_gap("recover-device", "attach_runtime_session")

        with pytest.raises(DispatchBlockedByRegistrationGapError):
            await bridge.assign_task(
                device_id="recover-device",
                task_id=str(uuid.uuid4()),
                task_type="tap",
                payload={},
            )

    @pytest.mark.asyncio
    async def test_F02_dispatch_allowed_after_gap_cleared(self, bridge):
        """After clearing gaps, dispatch proceeds without raising."""
        from galaxy_gateway.android.handlers.registration import (
            record_registration_gap,
            clear_registration_gaps,
            DispatchBlockedByRegistrationGapError,
        )
        record_registration_gap("recover-device", "attach_runtime_session")
        # Simulate re-registration completing successfully: clear the gap
        clear_registration_gaps("recover-device")

        sent: Dict[str, Any] = {}

        async def _fake_send(d_id, msg, **kwargs):
            sent.update(msg)
            return {"success": True}

        bridge.send_to_device = _fake_send  # type: ignore[method-assign]

        mock_router = MagicMock()
        mock_router.devices = {}

        with patch("galaxy_gateway.device_router.device_router", mock_router):
            await bridge.assign_task(
                device_id="recover-device",
                task_id="task-recover-001",
                task_type="screenshot",
                payload={},
            )

        assert sent.get("type") == "task_assign", (
            "After gap cleared, assign_task should succeed"
        )
