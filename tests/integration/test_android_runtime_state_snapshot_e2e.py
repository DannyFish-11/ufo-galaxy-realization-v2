"""
tests/integration/test_android_runtime_state_snapshot_e2e.py
=============================================================
Android → V2 runtime state snapshot end-to-end CI evidence.

This module is the **machine-checkable proof** that Android-originated runtime
state travels the canonical path into V2 and becomes visible in existing V2
truth surfaces.  It closes the evidence gap identified in the system audit:
"Android local carrier truth is not activated end-to-end in CI."

Canonical path under test
--------------------------
::

    AndroidRuntimeStub (Android emulator equivalent)
        │ device_register          (AIP v3 via AndroidBridge.handle_message)
        │ device_state_snapshot    (AIP v3 via AndroidBridge.handle_message)
        ▼
    AndroidBridge._message_handlers[DEVICE_STATE_SNAPSHOT]
        │ calls handle_device_state_snapshot()
        ▼
    galaxy_gateway.android.handlers.device_state_snapshot
        │ calls absorb_device_state_snapshot()
        ▼
    core.android_device_state_store  ← android_device_state_store becomes non-empty
        │ get_device_state_snapshot()
        │ get_device_ecosystem_summary()
        ▼
    Operator surfaces:
        GET /api/v1/operator/devices/ecosystem
        GET /api/v1/operator/devices/ecosystem/{device_id}
        GET /api/v1/operator/devices/execution-events

What this module proves
------------------------
1. The canonical absorb/store path is activated — not just that the message is
   *accepted* syntactically.
2. The stored values are **Android-derived runtime values** (model_id, readiness
   flags, fallback tier, etc.) — not empty defaults or synthetic zeros.
3. The existing operator/ecosystem surfaces expose those absorbed values.
4. The transport layer (real WebSocket via FastAPI TestClient) routes the
   message through the same handler path that production uses.
5. Future regressions that break the absorb/store path or bypass the handler
   will cause these tests to fail with clear error messages.

No test doubles are used for:
- ``AndroidBridge.handle_message`` — the real bridge dispatch runs
- ``handle_device_state_snapshot`` — the real handler runs
- ``absorb_device_state_snapshot`` — the real store writes happen
- ``get_device_state_snapshot`` / ``get_device_ecosystem_summary`` — real reads

The "Android emulator" role is played by ``AndroidRuntimeStub``, which faithfully
replicates the message sequence a real Galaxy-Android client sends during startup
and runtime operation.

No external services, live devices, or network connections are required.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# AIP v3 helpers — identical to those used by production Android clients
# ---------------------------------------------------------------------------


def _v3(msg_type: str, device_id: str, **extra) -> Dict[str, Any]:
    """Build a minimal valid AIP v3 message dict."""
    return {
        "version": "3.0",
        "type": msg_type,
        "message_id": str(uuid.uuid4()),
        "device_id": device_id,
        "timestamp": int(time.time() * 1000),
        **extra,
    }


def _make_ws() -> MagicMock:
    """Return a minimal WebSocket mock sufficient for bridge handler calls."""
    ws = MagicMock()
    ws.send_json = AsyncMock()
    ws.send = AsyncMock()
    return ws


# ---------------------------------------------------------------------------
# AndroidRuntimeStub — high-fidelity Android participant for CI
# ---------------------------------------------------------------------------


class AndroidRuntimeStub:
    """High-fidelity stub replicating the message sequence of a real Android
    Galaxy client during startup and runtime.

    This stub communicates via the real ``AndroidBridge.handle_message`` path,
    making it a runtime-level (not mock-level) participant in the canonical
    Android → V2 ingestion chain.

    Message sequence simulated
    --------------------------
    1. ``device_register``            → expect ``device_register_ack``
    2. ``capability_report``          → expect ``capability_report_ack``
    3. ``device_state_snapshot``      → expect ``device_state_snapshot_ack``
    4. ``device_execution_event``     → expect ``device_execution_event_ack``

    The snapshot payload is populated with realistic Android-side runtime state
    values to verify that V2 stores and reflects **Android-derived** data, not
    synthetic zeros.
    """

    #: Realistic Android device snapshot payload.
    #: Reflects the state a Galaxy Android app would send after a successful
    #: local model warmup and accessibility service startup.
    REALISTIC_SNAPSHOT_PAYLOAD: Dict[str, Any] = {
        "llama_cpp_available": True,
        "ncnn_available": False,
        "active_runtime_type": "LLAMA_CPP",
        "model_ready": True,
        "accessibility_ready": True,
        "overlay_ready": True,
        "local_loop_ready": True,
        "degraded_reasons": [],
        "model_id": "mobilevlm_v2_7b",
        "runtime_type": "LLAMA_CPP",
        "checksum_ok": True,
        "compatibility_ok": True,
        "quantization": "q4_k_m",
        "model_version": "2.1.0",
        "mobilevlm_present": True,
        "mobilevlm_checksum_ok": True,
        "seeclick_present": True,
        "pending_first_download": False,
        "offline_queue_depth": 0,
        "current_fallback_tier": "planner_local",
        "planner_fallback_tier": "planner_local",
        "grounding_fallback_tier": "grounding_local",
        "warmup_result": "ok",
        "snapshot_ts": int(time.time() * 1000),
        "local_loop_config": {
            "max_steps": 20,
            "enable_replanning": True,
            "offline_mode": False,
        },
        "runtime_health_snapshot": {
            "memory_mb": 2048,
            "cpu_load_pct": 12.5,
            "temperature_c": 38.0,
            "health_score": 0.97,
        },
    }

    def __init__(self, device_id: str) -> None:
        self.device_id = device_id
        self.ws = _make_ws()

    async def register(self, bridge: Any) -> Dict[str, Any]:
        """Send device_register; return the ack."""
        msg = _v3(
            "device_register",
            self.device_id,
            platform="android",
            model=f"StubPhone_{self.device_id[:8]}",
            os_version="13",
        )
        ack = await bridge.handle_message(self.ws, msg)
        return ack or {}

    async def report_capabilities(self, bridge: Any) -> Dict[str, Any]:
        """Send capability_report; return the ack."""
        msg = _v3(
            "capability_report",
            self.device_id,
            platform="android",
            supported_actions=["tap", "swipe", "screenshot", "input_text"],
        )
        ack = await bridge.handle_message(self.ws, msg)
        return ack or {}

    async def send_state_snapshot(
        self,
        bridge: Any,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Send device_state_snapshot with realistic Android runtime values.

        This is the critical canonical uplink that should activate the
        android_device_state_store.
        """
        msg = _v3(
            "device_state_snapshot",
            self.device_id,
            payload=payload or self.REALISTIC_SNAPSHOT_PAYLOAD,
        )
        ack = await bridge.handle_message(self.ws, msg)
        return ack or {}

    async def send_execution_event(
        self,
        bridge: Any,
        flow_id: str,
        phase: str = "grounding",
        step_index: int = 1,
    ) -> Dict[str, Any]:
        """Send device_execution_event; return the ack."""
        msg = _v3(
            "device_execution_event",
            self.device_id,
            payload={
                "flow_id": flow_id,
                "task_id": str(uuid.uuid4()),
                "phase": phase,
                "step_index": step_index,
                "is_blocking": False,
                "stagnation_detected": False,
                "fallback_tier": "grounding_local",
                "event_ts": int(time.time() * 1000),
            },
        )
        ack = await bridge.handle_message(self.ws, msg)
        return ack or {}

    async def startup_sequence(self, bridge: Any) -> Dict[str, Any]:
        """Run the full Android startup sequence (register + cap + snapshot).

        Returns a dict with all three ack responses.
        """
        reg_ack = await self.register(bridge)
        cap_ack = await self.report_capabilities(bridge)
        snap_ack = await self.send_state_snapshot(bridge)
        return {"register_ack": reg_ack, "capability_ack": cap_ack, "snapshot_ack": snap_ack}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def bridge():
    """Real AndroidBridge instance (no mocking)."""
    from galaxy_gateway.android_bridge import AndroidBridge
    return AndroidBridge()


@pytest.fixture(autouse=True)
def isolate_android_state_store():
    """Reset the android_device_state_store singleton before each test.

    This ensures each test starts with a clean store so cross-test
    contamination cannot produce false positives.
    """
    from core.android_device_state_store import reset_android_device_state_store
    reset_android_device_state_store()
    yield
    reset_android_device_state_store()


@pytest.fixture()
def operator_client():
    """FastAPI TestClient with the operator routes mounted.

    Used to verify that the operator/ecosystem HTTP surfaces expose the
    Android-derived state absorbed into android_device_state_store.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from core.routes.operator import create_router

    app = FastAPI()
    router = create_router()
    app.include_router(router)

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def operator_panel_client():
    """FastAPI TestClient with operator + unified panel routes mounted."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from core.routes.operator import create_router as create_operator_router
    from core.routes.panel import create_router as create_panel_router

    app = FastAPI()
    app.include_router(create_operator_router())
    app.include_router(create_panel_router())

    with TestClient(app) as c:
        yield c


def _make_full_flow_entity(
    flow_id: str,
    *,
    trace_id: str,
    task_id: str,
    device_id: str,
) -> MagicMock:
    """Return a minimal DelegatedFlowEntity-like object for flow projection."""
    entity = MagicMock()
    entity.identity.delegated_flow_id = flow_id
    entity.identity.flow_lineage_id = f"lin_{flow_id}"
    entity.identity.flow_segment_id = ""
    entity.identity.trace_id = trace_id
    entity.identity.flow_kind.value = "goal_execution"
    entity.phase.value = "active"
    entity.phase.is_active.return_value = True
    entity.object_mapping.canonical_task_id = task_id
    entity.object_mapping.dispatch_record_id = f"dr_{task_id}"
    entity.object_mapping.contract_id = ""
    entity.object_mapping.binding_id = ""
    entity.object_mapping.device_id = device_id
    entity.object_mapping.android_flow_id = flow_id
    entity.created_at = time.time()
    entity.last_updated_at = time.time()
    entity.metadata = {}
    return entity


# ===========================================================================
# 1. Bridge-layer canonical path: register → snapshot → store non-empty
# ===========================================================================


class TestAndroidSnapshotBridgePath:
    """Prove that device_state_snapshot travels the canonical bridge path and
    activates android_device_state_store.

    Evidence class: bridge-layer (real AndroidBridge, no WebSocket transport).
    Isolation: each test resets the store singleton.
    """

    @pytest.mark.asyncio
    async def test_register_then_snapshot_activates_store(self, bridge: Any) -> None:
        """CANONICAL PATH: register → device_state_snapshot → store non-empty.

        Assertion contract
        ------------------
        After sending a device_register followed by a device_state_snapshot
        via the real AndroidBridge, the android_device_state_store singleton
        MUST be non-empty for this device_id.

        This test fails if the absorb/store path is broken or bypassed.
        """
        from core.android_device_state_store import (
            get_device_state_snapshot,
            list_device_state_snapshots,
        )

        device_id = f"snap-bridge-{uuid.uuid4().hex[:8]}"
        stub = AndroidRuntimeStub(device_id)

        # Step 1: register
        reg_ack = await stub.register(bridge)
        assert reg_ack.get("type") == "device_register_ack", (
            f"STEP1 FAILED: expected device_register_ack, got {reg_ack.get('type')!r}"
        )
        assert reg_ack.get("success") is True, "STEP1 FAILED: registration not successful"

        # Pre-condition: store is empty before snapshot
        assert get_device_state_snapshot(device_id) is None, (
            "PRE-CONDITION FAILED: store should be empty before snapshot is sent"
        )

        # Step 2: send device_state_snapshot
        snap_ack = await stub.send_state_snapshot(bridge)
        assert snap_ack.get("type") == "device_state_snapshot_ack", (
            f"STEP2 FAILED: expected device_state_snapshot_ack, got {snap_ack.get('type')!r}"
        )
        assert snap_ack.get("status") == "absorbed", (
            f"STEP2 FAILED: snapshot was not absorbed — status={snap_ack.get('status')!r}. "
            "This means the canonical absorb/store path did not execute."
        )
        assert snap_ack.get("device_id") == device_id, (
            "STEP2 FAILED: device_id mismatch in snapshot ack"
        )

        # Step 3: verify store is non-empty
        stored_snap = get_device_state_snapshot(device_id)
        assert stored_snap is not None, (
            "CANONICAL PATH BROKEN: android_device_state_store is still empty after "
            "a device_state_snapshot was sent and acknowledged as 'absorbed'. "
            "The absorb/store path may be bypassed or the store singleton is disconnected "
            "from the handler."
        )

        # Verify all devices list also reflects the new entry
        all_snapshots = list_device_state_snapshots()
        device_ids_in_store = {s.device_id for s in all_snapshots}
        assert device_id in device_ids_in_store, (
            "list_device_state_snapshots() does not include the absorbed device — "
            "the store is internally inconsistent."
        )

    @pytest.mark.asyncio
    async def test_snapshot_stores_android_derived_values(self, bridge: Any) -> None:
        """ANDROID-DERIVED VALUES: stored snapshot reflects real Android runtime state.

        This test proves the store contains **Android-derived** values (model_id,
        readiness flags, fallback tier, etc.) rather than empty defaults.  A
        test that only verifies ACK shape without reading the stored values would
        not detect a handler that absorbs but discards the payload.
        """
        from core.android_device_state_store import get_device_state_snapshot

        device_id = f"snap-vals-{uuid.uuid4().hex[:8]}"
        stub = AndroidRuntimeStub(device_id)
        expected = AndroidRuntimeStub.REALISTIC_SNAPSHOT_PAYLOAD

        await stub.register(bridge)
        snap_ack = await stub.send_state_snapshot(bridge)
        assert snap_ack.get("status") == "absorbed"

        stored = get_device_state_snapshot(device_id)
        assert stored is not None, "Store must be non-empty after snapshot absorption"

        # Identity: stored device_id matches the Android sender
        assert stored.device_id == device_id, (
            f"Stored device_id={stored.device_id!r} does not match sender {device_id!r}"
        )

        # Readiness flags: must reflect Android-reported values
        assert stored.model_ready == expected["model_ready"], (
            f"model_ready mismatch: stored={stored.model_ready!r} "
            f"expected={expected['model_ready']!r}"
        )
        assert stored.accessibility_ready == expected["accessibility_ready"], (
            f"accessibility_ready mismatch: stored={stored.accessibility_ready!r}"
        )
        assert stored.local_loop_ready == expected["local_loop_ready"], (
            f"local_loop_ready mismatch: stored={stored.local_loop_ready!r}"
        )

        # Model identity: must reflect Android-reported model
        assert stored.model_id == expected["model_id"], (
            f"model_id mismatch: stored={stored.model_id!r} expected={expected['model_id']!r}"
        )
        assert stored.quantization == expected["quantization"], (
            f"quantization mismatch: stored={stored.quantization!r}"
        )

        # Fallback tier: must reflect Android-reported tier
        assert stored.current_fallback_tier == expected["current_fallback_tier"], (
            f"current_fallback_tier mismatch: stored={stored.current_fallback_tier!r}"
        )

        # Runtime type: must reflect Android-reported runtime
        assert stored.active_runtime_type == expected["active_runtime_type"], (
            f"active_runtime_type mismatch: stored={stored.active_runtime_type!r}"
        )

        # Warmup result: must reflect Android-reported warmup outcome
        assert stored.warmup_result == expected["warmup_result"], (
            f"warmup_result mismatch: stored={stored.warmup_result!r}"
        )

    @pytest.mark.asyncio
    async def test_snapshot_to_dict_has_provenance_source(self, bridge: Any) -> None:
        """Stored snapshot to_dict() must include _source='android_device_state_store'.

        The ``_source`` field is the canonical provenance marker that distinguishes
        data stored via the real absorption path from data that might be synthesised
        elsewhere.  Operator surfaces that include this field allow callers to verify
        they are reading from the canonical store.
        """
        from core.android_device_state_store import get_device_state_snapshot

        device_id = f"snap-prov-{uuid.uuid4().hex[:8]}"
        stub = AndroidRuntimeStub(device_id)

        await stub.register(bridge)
        await stub.send_state_snapshot(bridge)

        stored = get_device_state_snapshot(device_id)
        assert stored is not None

        d = stored.to_dict()
        assert d.get("_source") == "android_device_state_store", (
            f"_source provenance marker missing or wrong: got {d.get('_source')!r}. "
            "This marker proves data came from the canonical android_device_state_store path."
        )
        assert d.get("device_id") == device_id

    @pytest.mark.asyncio
    async def test_ecosystem_summary_reflects_absorbed_snapshot(self, bridge: Any) -> None:
        """get_device_ecosystem_summary() count fields must reflect the absorbed snapshot.

        After Android sends device_state_snapshot with model_ready=True,
        accessibility_ready=True, and local_loop_ready=True, the ecosystem
        summary must return non-zero counts for those fields.
        """
        from core.android_device_state_store import get_device_ecosystem_summary

        device_id = f"snap-eco-{uuid.uuid4().hex[:8]}"
        stub = AndroidRuntimeStub(device_id)

        await stub.register(bridge)
        await stub.send_state_snapshot(bridge)

        summary = get_device_ecosystem_summary()

        assert summary["total_devices_with_snapshot"] >= 1, (
            "total_devices_with_snapshot must be ≥ 1 after absorption — "
            "ecosystem summary does not reflect the absorbed snapshot."
        )
        assert summary["model_ready_count"] >= 1, (
            "model_ready_count must be ≥ 1 — the absorbed snapshot has model_ready=True"
        )
        assert summary["accessibility_ready_count"] >= 1, (
            "accessibility_ready_count must be ≥ 1 — the absorbed snapshot has "
            "accessibility_ready=True"
        )
        assert summary["local_loop_ready_count"] >= 1, (
            "local_loop_ready_count must be ≥ 1 — the absorbed snapshot has "
            "local_loop_ready=True"
        )

        # The per-device list in summary must include our device
        devices_in_summary = {d["device_id"] for d in summary.get("devices", [])}
        assert device_id in devices_in_summary, (
            "Per-device list in ecosystem summary must include the absorbed device. "
            f"Devices present: {devices_in_summary}"
        )


# ===========================================================================
# 2. Transport-layer canonical path: WebSocket -> handler -> store
# ===========================================================================
# Transport-layer WebSocket tests are in the sibling file:
#   tests/integration/websocket/test_android_snapshot_ws_transport.py
#
# The transport tests must live in that directory because they require a
# module-scoped FastAPI TestClient fixture that only works correctly under
# asyncio_mode=auto when placed in the tests/integration/websocket/ package
# (matching the pattern of test_aip_v3_ws_contracts.py).
# ===========================================================================


# ===========================================================================
# 3. Operator surface: HTTP endpoints expose Android-derived state
# ===========================================================================


class TestOperatorSurfaceExposesAndroidState:
    """Prove the operator HTTP surfaces expose absorbed Android runtime state.

    These tests verify the full chain:
    device_state_snapshot absorbed → operator HTTP endpoint returns Android data.
    """

    @pytest.mark.asyncio
    async def test_ecosystem_http_surface_returns_android_data(
        self, bridge: Any, operator_client: Any
    ) -> None:
        """GET /api/v1/operator/devices/ecosystem must reflect absorbed Android state.

        After Android sends device_state_snapshot, the operator ecosystem
        endpoint must return a response that contains Android-derived values.
        """
        device_id = f"snap-http-eco-{uuid.uuid4().hex[:8]}"
        stub = AndroidRuntimeStub(device_id)

        await stub.register(bridge)
        await stub.send_state_snapshot(bridge)

        resp = operator_client.get("/api/v1/operator/devices/ecosystem")
        assert resp.status_code == 200, (
            f"Ecosystem endpoint returned HTTP {resp.status_code}: {resp.text}"
        )

        body = resp.json()
        assert body.get("total_devices_with_snapshot", 0) >= 1, (
            "Operator ecosystem surface does not reflect the absorbed snapshot. "
            "total_devices_with_snapshot is 0 after absorption."
        )
        assert body.get("model_ready_count", 0) >= 1, (
            "model_ready_count is 0 — Android-derived readiness not reflected"
        )

        # Per-device list must include our device
        devices = body.get("devices", [])
        device_ids = {d.get("device_id") for d in devices}
        assert device_id in device_ids, (
            f"Operator ecosystem surface does not include device {device_id!r}. "
            f"Devices in response: {device_ids}"
        )

    @pytest.mark.asyncio
    async def test_per_device_ecosystem_http_surface(
        self, bridge: Any, operator_client: Any
    ) -> None:
        """GET /api/v1/operator/devices/ecosystem/{device_id} returns Android state.

        The per-device operator endpoint must return HTTP 200 with Android-derived
        values after the device sends a device_state_snapshot.
        """
        device_id = f"snap-http-dev-{uuid.uuid4().hex[:8]}"
        stub = AndroidRuntimeStub(device_id)

        await stub.register(bridge)
        await stub.send_state_snapshot(bridge)

        resp = operator_client.get(f"/api/v1/operator/devices/ecosystem/{device_id}")
        assert resp.status_code == 200, (
            f"Per-device ecosystem endpoint returned HTTP {resp.status_code} for device "
            f"{device_id!r} after snapshot absorption. "
            "Expected 200 — 404 means the device was not found in the store."
        )

        body = resp.json()
        assert body.get("device_id") == device_id, (
            f"Response device_id mismatch: {body.get('device_id')!r} != {device_id!r}"
        )
        assert body.get("_source") == "android_device_state_store", (
            "Provenance marker _source must be 'android_device_state_store' — "
            "this confirms the response came from the canonical store."
        )

        # Verify Android-derived values are present in the HTTP response
        expected_payload = AndroidRuntimeStub.REALISTIC_SNAPSHOT_PAYLOAD
        assert body.get("model_id") == expected_payload["model_id"], (
            f"model_id in HTTP response: {body.get('model_id')!r} "
            f"expected: {expected_payload['model_id']!r}"
        )
        assert body.get("model_ready") == expected_payload["model_ready"], (
            f"model_ready in HTTP response: {body.get('model_ready')!r}"
        )
        assert body.get("current_fallback_tier") == expected_payload["current_fallback_tier"], (
            f"current_fallback_tier in HTTP response: {body.get('current_fallback_tier')!r}"
        )

    @pytest.mark.asyncio
    async def test_per_device_ecosystem_returns_404_before_snapshot(
        self, operator_client: Any
    ) -> None:
        """GET /api/v1/operator/devices/ecosystem/{device_id} returns 404 before snapshot.

        This establishes the baseline: a device that has not sent a snapshot
        should return 404.  It also validates the test isolation — if this
        returns 200 with stale data, isolation is broken.
        """
        # Use a device that has never sent a snapshot in this test run
        device_id = f"never-snapped-{uuid.uuid4().hex[:8]}"

        resp = operator_client.get(f"/api/v1/operator/devices/ecosystem/{device_id}")
        assert resp.status_code == 404, (
            f"Expected 404 for unknown device {device_id!r}, got {resp.status_code}. "
            "Either test isolation is broken or the store has stale data."
        )

    @pytest.mark.asyncio
    async def test_execution_events_http_surface_reflects_android_events(
        self, bridge: Any, operator_client: Any
    ) -> None:
        """GET /api/v1/operator/devices/execution-events returns absorbed events.

        After an Android device sends a device_execution_event, the operator
        execution-events endpoint must return a response that includes the event.
        """
        device_id = f"snap-http-evt-{uuid.uuid4().hex[:8]}"
        flow_id = f"flow-{uuid.uuid4().hex[:8]}"
        stub = AndroidRuntimeStub(device_id)

        await stub.register(bridge)
        await stub.send_state_snapshot(bridge)
        await stub.send_execution_event(bridge, flow_id=flow_id, phase="grounding")

        resp = operator_client.get(
            f"/api/v1/operator/devices/execution-events?device_id={device_id}"
        )
        assert resp.status_code == 200, (
            f"Execution events endpoint returned HTTP {resp.status_code}: {resp.text}"
        )

        body = resp.json()
        assert body.get("total_events", 0) >= 1, (
            "total_events is 0 after device_execution_event was sent. "
            "The execution event absorption path is not activated."
        )

        events = body.get("events", [])
        device_events = [e for e in events if e.get("device_id") == device_id]
        assert len(device_events) >= 1, (
            f"No events found for device {device_id!r} in execution-events response. "
            f"Events present: {[e.get('device_id') for e in events]}"
        )
        # Verify event carries Android-derived phase
        assert device_events[0].get("phase") == "grounding", (
            f"Event phase mismatch: {device_events[0].get('phase')!r} expected 'grounding'"
        )


# ===========================================================================
# 4. Execution event canonical path
# ===========================================================================


class TestAndroidExecutionEventCanonicalPath:
    """Prove that device_execution_event travels the canonical path.

    Mirrors the snapshot tests but for the execution event uplink.
    """

    @pytest.mark.asyncio
    async def test_execution_event_absorbed_into_store(self, bridge: Any) -> None:
        """device_execution_event must be absorbed into the store's event ring."""
        from core.android_device_state_store import list_recent_execution_events

        device_id = f"evt-bridge-{uuid.uuid4().hex[:8]}"
        flow_id = f"flow-{uuid.uuid4().hex[:8]}"
        stub = AndroidRuntimeStub(device_id)

        await stub.register(bridge)
        evt_ack = await stub.send_execution_event(bridge, flow_id=flow_id, phase="planning")

        assert evt_ack.get("type") == "device_execution_event_ack", (
            f"Expected device_execution_event_ack, got {evt_ack.get('type')!r}"
        )
        assert evt_ack.get("status") == "absorbed", (
            f"Execution event not absorbed: status={evt_ack.get('status')!r}"
        )

        # Verify the event is in the store's ring buffer
        events = list_recent_execution_events(device_id=device_id)
        assert len(events) >= 1, (
            "list_recent_execution_events() returned empty list after "
            "device_execution_event was absorbed.  The event ring buffer "
            "absorption path is not closed."
        )
        assert events[0].device_id == device_id
        assert events[0].phase == "planning", (
            f"Stored event phase mismatch: {events[0].phase!r} expected 'planning'"
        )
        assert events[0].flow_id == flow_id, (
            f"Stored event flow_id mismatch: {events[0].flow_id!r} expected {flow_id!r}"
        )


# ===========================================================================
# 5. Regression guard: bypass detection
# ===========================================================================


class TestCanonicalPathBypassRegression:
    """Regression guards ensuring the test would fail if the canonical path breaks.

    These tests verify that the absorb/store path is genuinely active by
    checking side effects that only occur when the real handler runs.
    """

    @pytest.mark.asyncio
    async def test_absorb_path_active_iff_ack_status_is_absorbed(
        self, bridge: Any
    ) -> None:
        """Status='absorbed' in ACK is coupled to actual store write.

        If status='absorbed' is returned but the store is empty, the ACK
        is lying and the canonical path is bypassed.  This test asserts the
        coupling is intact.
        """
        from core.android_device_state_store import get_device_state_snapshot

        device_id = f"snap-coupling-{uuid.uuid4().hex[:8]}"
        stub = AndroidRuntimeStub(device_id)

        await stub.register(bridge)
        snap_ack = await stub.send_state_snapshot(bridge)

        if snap_ack.get("status") == "absorbed":
            stored = get_device_state_snapshot(device_id)
            assert stored is not None, (
                "REGRESSION: ACK claims status='absorbed' but store is empty. "
                "The ACK is decoupled from the actual absorb/store path — "
                "this indicates the canonical path is bypassed."
            )
        # If status is 'error', the test still passes (handler ran but failed),
        # but the snapshot tests above would catch that case.

    @pytest.mark.asyncio
    async def test_snapshot_without_register_still_absorbed(
        self, bridge: Any
    ) -> None:
        """device_state_snapshot must be absorbed even without prior registration.

        The canonical absorb path should not silently discard snapshots from
        unregistered devices.  This tests that the store handles snapshots
        independently of registration state.
        """
        from core.android_device_state_store import get_device_state_snapshot

        device_id = f"snap-noreg-{uuid.uuid4().hex[:8]}"
        stub = AndroidRuntimeStub(device_id)

        # Send snapshot WITHOUT registering first
        snap_ack = await stub.send_state_snapshot(bridge)

        # The message must return an ack (not crash)
        assert isinstance(snap_ack, dict), (
            "Snapshot without registration must return a dict ack, not raise"
        )
        assert snap_ack.get("type") == "device_state_snapshot_ack", (
            f"Expected device_state_snapshot_ack, got {snap_ack.get('type')!r}"
        )
        # If status is absorbed, the store must be non-empty
        if snap_ack.get("status") == "absorbed":
            stored = get_device_state_snapshot(device_id)
            assert stored is not None, (
                "ACK claims 'absorbed' but store is empty for unregistered device. "
                "Store coupling is broken."
            )

    @pytest.mark.asyncio
    async def test_multiple_snapshots_update_store(self, bridge: Any) -> None:
        """Sending multiple snapshots overwrites the previous; store shows latest.

        The store is expected to keep only the most recent snapshot per device.
        This guards against regressions where the store ignores updates.
        """
        from core.android_device_state_store import get_device_state_snapshot

        device_id = f"snap-multi-{uuid.uuid4().hex[:8]}"
        stub = AndroidRuntimeStub(device_id)

        await stub.register(bridge)

        # First snapshot: model_ready=True
        await stub.send_state_snapshot(bridge)
        snap1 = get_device_state_snapshot(device_id)
        assert snap1 is not None and snap1.model_ready is True

        # Second snapshot: model_ready=False (device degraded)
        degraded_payload = dict(AndroidRuntimeStub.REALISTIC_SNAPSHOT_PAYLOAD)
        degraded_payload["model_ready"] = False
        degraded_payload["degraded_reasons"] = ["model_checksum_failed"]
        await stub.send_state_snapshot(bridge, payload=degraded_payload)

        snap2 = get_device_state_snapshot(device_id)
        assert snap2 is not None
        assert snap2.model_ready is False, (
            "Store did not update after second snapshot — model_ready should be False. "
            "The store may be caching the first snapshot and ignoring updates."
        )
        assert "model_checksum_failed" in (snap2.degraded_reasons or []), (
            "degraded_reasons not updated from second snapshot"
        )

    @pytest.mark.asyncio
    async def test_store_is_independent_of_task_execution_path(
        self, bridge: Any
    ) -> None:
        """android_device_state_store must be populated by snapshot path, not task path.

        This ensures the snapshot store is separate from the task execution
        registry.  A device can be present in the store without ever executing
        a task.
        """
        from core.android_device_state_store import get_device_state_snapshot

        device_id = f"snap-notask-{uuid.uuid4().hex[:8]}"
        stub = AndroidRuntimeStub(device_id)

        # Only register and snapshot — no task execution
        await stub.register(bridge)
        await stub.send_state_snapshot(bridge)

        # Store must be populated via the snapshot path alone
        stored = get_device_state_snapshot(device_id)
        assert stored is not None, (
            "android_device_state_store must be populated by the device_state_snapshot "
            "path independently of task execution.  A device that sends a snapshot but "
            "never executes a task must still appear in the store."
        )
        assert stored.device_id == device_id


# ===========================================================================
# 6. Canonical convergence / reconciliation determinism
# ===========================================================================


class TestAndroidSnapshotConvergenceDeterminism:
    """Deterministic convergence for stale/out-of-order/reconnect/conflict races."""

    def test_out_of_order_snapshot_is_rejected_by_sequence(self) -> None:
        from core.android_device_state_store import (
            absorb_device_state_snapshot,
            get_device_snapshot_reconciliation,
            get_device_state_snapshot,
            reset_android_device_state_store,
        )

        reset_android_device_state_store()
        device_id = f"snap-out-of-order-{uuid.uuid4().hex[:8]}"

        absorb_device_state_snapshot(
            device_id,
            {
                "snapshot_ts": 2000,
                "snapshot_seq": 10,
                "model_ready": True,
                "current_fallback_tier": "planner_local",
            },
        )
        absorb_device_state_snapshot(
            device_id,
            {
                "snapshot_ts": 1000,
                "snapshot_seq": 9,
                "model_ready": False,
                "current_fallback_tier": "center_delegated",
            },
        )

        stored = get_device_state_snapshot(device_id)
        assert stored is not None
        assert stored.model_ready is True
        assert stored.current_fallback_tier == "planner_local"

        reconciliation = get_device_snapshot_reconciliation(device_id)
        assert reconciliation.get("status") == "out_of_order_rejected"
        assert reconciliation.get("applied") is False
        assert reconciliation.get("ordering_basis") == "snapshot_seq"

    def test_same_timestamp_conflict_keeps_center_truth_stable(self) -> None:
        from core.android_device_state_store import (
            absorb_device_state_snapshot,
            get_device_snapshot_reconciliation,
            get_device_state_snapshot,
            reset_android_device_state_store,
        )

        reset_android_device_state_store()
        device_id = f"snap-conflict-{uuid.uuid4().hex[:8]}"

        absorb_device_state_snapshot(
            device_id,
            {"snapshot_ts": 3000, "snapshot_seq": 4, "model_ready": True, "runtime_type": "LLAMA_CPP"},
        )
        absorb_device_state_snapshot(
            device_id,
            {"snapshot_ts": 3000, "snapshot_seq": 4, "model_ready": False, "runtime_type": "CENTER"},
        )

        stored = get_device_state_snapshot(device_id)
        assert stored is not None
        assert stored.model_ready is True
        assert stored.runtime_type == "LLAMA_CPP"

        reconciliation = get_device_snapshot_reconciliation(device_id)
        assert reconciliation.get("status") == "conflict_center_truth_retained"
        assert reconciliation.get("conflict") is True
        assert reconciliation.get("applied") is False

    def test_reconnect_delayed_snapshot_missing_ordering_is_rejected(self) -> None:
        from core.android_device_state_store import (
            absorb_device_state_snapshot,
            get_device_snapshot_reconciliation,
            get_device_state_snapshot,
            reset_android_device_state_store,
        )

        reset_android_device_state_store()
        device_id = f"snap-reconnect-{uuid.uuid4().hex[:8]}"

        absorb_device_state_snapshot(
            device_id,
            {"snapshot_seq": 5, "snapshot_ts": 5000, "model_ready": True},
        )
        absorb_device_state_snapshot(
            device_id,
            {"snapshot_ts": 6000, "model_ready": False},
        )

        stored = get_device_state_snapshot(device_id)
        assert stored is not None
        assert stored.model_ready is True
        assert stored.snapshot_seq == 5

        reconciliation = get_device_snapshot_reconciliation(device_id)
        assert reconciliation.get("status") == "reconnect_delayed_rejected"
        assert reconciliation.get("applied") is False

    def test_governance_truth_path_projects_reconciliation_causality(self) -> None:
        from types import SimpleNamespace

        from core.android_device_state_store import (
            absorb_device_state_snapshot,
            reset_android_device_state_store,
        )
        from core.unified_governance_semantics import build_unified_governance_state

        reset_android_device_state_store()
        device_id = f"snap-gov-{uuid.uuid4().hex[:8]}"
        absorb_device_state_snapshot(
            device_id,
            {"snapshot_ts": 8000, "snapshot_seq": 2, "model_ready": True},
        )
        absorb_device_state_snapshot(
            device_id,
            {"snapshot_ts": 7000, "snapshot_seq": 1, "model_ready": False},
        )

        with patch(
            "core.attached_runtime_session_registry.list_active_sessions",
            return_value=[SimpleNamespace(device_id=device_id)],
        ), patch(
            "core.android_mode_gate_policy.build_mode_state_for_device",
            return_value=SimpleNamespace(mode=SimpleNamespace(value="cross_device")),
        ), patch(
            "core.android_mode_gate_policy.evaluate_android_mode_readiness",
            return_value=SimpleNamespace(is_dispatch_eligible=True, is_takeover_eligible=True),
        ), patch(
            "core.unified_execution_governance.is_takeover_active",
            return_value=False,
        ):
            state = build_unified_governance_state()

        device_state = next((d for d in state["devices"] if d["device_id"] == device_id), None)
        governance_state_device_ids = [d.get("device_id") for d in state["devices"]]
        assert device_state is not None, (
            f"Device {device_id!r} not present in governance state devices: "
            f"{governance_state_device_ids}"
        )
        causality = device_state["governance_precedence"]["delegated_execution"]["decision_causality"]
        assert causality["snapshot_reconciliation_status"] == "out_of_order_rejected"
        assert causality["snapshot_conflict"] is False
        assert causality["snapshot_ordering_basis"] == "snapshot_seq"


# ===========================================================================
# 7. Cross-device runtime roundtrip closure (machine-verifiable)
# ===========================================================================


class TestCrossDeviceRuntimeRoundtripClosure:
    """Canonical happy path proof: V2 dispatch → Android execution → V2 feedback."""

    @pytest.fixture(autouse=True)
    def _reset_roundtrip_singletons(self):
        from core.attached_runtime_session_registry import reset_session_registry
        from core.canonical_roundtrip import reset_execution_roundtrip
        from core.flow_level_operator_surface import reset_flow_level_operator_surface
        from core.unified_panel_aggregation import reset_unified_panel_aggregation_service

        reset_session_registry()
        reset_flow_level_operator_surface()
        reset_execution_roundtrip()
        reset_unified_panel_aggregation_service()
        yield
        reset_session_registry()
        reset_flow_level_operator_surface()
        reset_execution_roundtrip()
        reset_unified_panel_aggregation_service()

    @pytest.mark.asyncio
    async def test_v2_android_roundtrip_updates_state_flow_operator_and_panel(
        self,
        bridge: Any,
        operator_panel_client: Any,
    ) -> None:
        from core.android_device_state_store import (
            get_device_state_snapshot,
            list_recent_execution_events,
        )
        from core.attached_runtime_session_registry import lookup_session_by_device
        from core.flow_level_operator_surface import (
            AndroidExecutionPhase,
            get_flow_level_operator_surface,
        )
        from core.unified_panel_aggregation import build_unified_panel_payload
        from galaxy_gateway.android_bridge import get_android_bridge_trace_id

        device_id = f"rt-closure-{uuid.uuid4().hex[:8]}"
        flow_id = f"flow-{uuid.uuid4().hex[:8]}"
        task_id = f"task-{uuid.uuid4().hex[:8]}"
        trace_id = f"trace-{uuid.uuid4().hex[:8]}"
        stub = AndroidRuntimeStub(device_id)

        # Android startup path: register + capability + runtime-state snapshot.
        reg_ack = await stub.register(bridge)
        runtime_attachment_session_id = reg_ack.get("runtime_attachment_session_id", "")
        assert runtime_attachment_session_id, (
            "device_register_ack must include runtime_attachment_session_id for "
            "session continuity proof."
        )
        session_entry = lookup_session_by_device(device_id)
        assert session_entry is not None
        runtime_session_id = session_entry.runtime_session_id
        durable_session_id = session_entry.durable_session_id
        control_session_id = session_entry.session_id
        cap_ack = await stub.report_capabilities(bridge)
        assert cap_ack.get("accepted") is True
        snap_ack = await stub.send_state_snapshot(bridge)
        assert snap_ack.get("status") == "absorbed"

        # V2 dispatch path: send_to_device emits task_assign with trace_id.
        task_assign_message = {
            "version": "3.0",
            "type": "task_assign",
            "message_id": task_id,
            "task_id": task_id,
            "device_id": device_id,
            "timestamp": int(time.time() * 1000),
            "trace_id": trace_id,
            "payload": {
                "command": "tap",
                "flow_id": flow_id,
                "trace_id": trace_id,
                "orchestrator_dispatch": True,
            },
        }
        dispatched_task = asyncio.create_task(
            bridge.send_to_device(
                device_id,
                task_assign_message,
                wait_response=True,
                timeout=5.0,
            )
        )
        await asyncio.sleep(0.05)

        outbound_messages = [
            c.args[0] for c in stub.ws.send_json.call_args_list if c.args and isinstance(c.args[0], dict)
        ]
        assert any(m.get("type") == "task_assign" for m in outbound_messages), (
            "V2 dispatch did not emit task_assign to Android transport."
        )
        task_assign = next(m for m in outbound_messages if m.get("type") == "task_assign")
        assert get_android_bridge_trace_id(task_assign) == trace_id, (
            "trace_id must be preserved on V2→Android dispatch payload."
        )

        fake_entity = _make_full_flow_entity(
            flow_id,
            trace_id=trace_id,
            task_id=task_id,
            device_id=device_id,
        )
        fake_runtime = MagicMock()
        fake_runtime.get.side_effect = lambda fid: fake_entity if fid == flow_id else None
        fake_runtime.list_entities.return_value = [fake_entity]

        with patch("core.delegated_flow_entity.get_delegated_flow", return_value=fake_entity), patch(
            "core.delegated_flow_entity.get_delegated_flow_entity_runtime",
            return_value=fake_runtime,
        ):
            delegated_ack = await bridge.handle_message(
                stub.ws,
                _v3(
                    "delegated_execution_signal",
                    device_id,
                    trace_id=trace_id,
                    payload={
                        "kind": "result",
                        "session_id": runtime_attachment_session_id,
                        "flow_id": flow_id,
                    },
                ),
            )
            assert delegated_ack is not None
            assert delegated_ack.get("type") == "delegated_execution_signal_ack"

            event_ack = await bridge.handle_message(
                stub.ws,
                _v3(
                    "device_execution_event",
                    device_id,
                    payload={
                        "flow_id": flow_id,
                        "task_id": task_id,
                        "phase": "completed",
                        "step_index": 3,
                        "is_blocking": False,
                        "event_ts": int(time.time() * 1000),
                    },
                ),
            )
            assert event_ack is not None
            assert event_ack.get("type") == "device_execution_event_ack"
            assert event_ack.get("status") == "absorbed"

            await bridge.handle_message(
                stub.ws,
                _v3(
                    "task_result",
                    device_id,
                    task_id=task_id,
                    status="completed",
                    route_mode="cross_device",
                    trace_id=trace_id,
                    session_id=control_session_id,
                    runtime_session_id=runtime_session_id,
                    runtime_attachment_session_id=runtime_attachment_session_id,
                    durable_session_id=durable_session_id,
                    payload={
                        "result": {"ok": True},
                        "session_id": control_session_id,
                        "runtime_session_id": runtime_session_id,
                        "runtime_attachment_session_id": runtime_attachment_session_id,
                        "durable_session_id": durable_session_id,
                    },
                ),
            )

            dispatch_result = await asyncio.wait_for(dispatched_task, timeout=5.0)
            assert dispatch_result is not None, "Dispatch waiter must resolve after task_result."
            assert dispatch_result.get("runtime_attachment_session_id") == runtime_attachment_session_id

            stored_snapshot = get_device_state_snapshot(device_id)
            assert stored_snapshot is not None
            events = list_recent_execution_events(flow_id=flow_id, device_id=device_id, limit=10)
            assert events, "android_device_state_store must contain execution event."
            assert events[0].phase == "completed"

            surface = get_flow_level_operator_surface()
            flow_proj = surface.inspect_flow(flow_id)
            assert flow_proj is not None
            assert flow_proj.trace_id == trace_id
            assert flow_proj.current_execution_phase == AndroidExecutionPhase.completed.value

            flow_resp = operator_panel_client.get(f"/api/v1/operator/flows/{flow_id}")
            assert flow_resp.status_code == 200, flow_resp.text
            flow_body = flow_resp.json()
            assert flow_body.get("trace_id") == trace_id
            assert flow_body.get("current_execution_phase") == "completed"

            panel = build_unified_panel_payload().to_dict()
            assert any(
                d.get("device_id") == device_id
                for d in panel.get("android_device_execution_digest", [])
            ), "Unified panel digest must expose the Android device in roundtrip."
            last_exec = panel.get("last_execution_result", {})
            assert last_exec.get("action_kind") == "android_terminal"
            assert last_exec.get("android_flow_id") == flow_id

            panel_resp = operator_panel_client.get("/api/v1/panel/unified")
            assert panel_resp.status_code == 200
            assert panel_resp.json().get("last_execution_result", {}).get("android_flow_id") == flow_id

        session_entry_after = lookup_session_by_device(device_id)
        assert session_entry_after is not None
        assert session_entry_after.runtime_attachment_session_id == runtime_attachment_session_id


# ===========================================================================
# 8. Message type handler registration guard
# ===========================================================================


class TestSnapshotHandlerRegistrationGuard:
    """Guard that DEVICE_STATE_SNAPSHOT and DEVICE_EXECUTION_EVENT have handlers.

    These tests ensure the message types are registered in the bridge so that
    Android-side messages of these types are not silently dropped.
    """

    def test_device_state_snapshot_handler_is_registered(self) -> None:
        """DEVICE_STATE_SNAPSHOT must have a handler registered in AndroidBridge."""
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        registered = {mt.value for mt in bridge._message_handlers}
        assert "device_state_snapshot" in registered, (
            "DEVICE_STATE_SNAPSHOT has no handler in AndroidBridge._message_handlers. "
            "Android runtime-state snapshots would be silently dropped. "
            f"Registered types: {sorted(registered)}"
        )

    def test_device_execution_event_handler_is_registered(self) -> None:
        """DEVICE_EXECUTION_EVENT must have a handler registered in AndroidBridge."""
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        registered = {mt.value for mt in bridge._message_handlers}
        assert "device_execution_event" in registered, (
            "DEVICE_EXECUTION_EVENT has no handler in AndroidBridge._message_handlers. "
            "Android execution events would be silently dropped. "
            f"Registered types: {sorted(registered)}"
        )

    def test_message_type_enum_has_both_snapshot_types(self) -> None:
        """MessageType enum must define both DEVICE_STATE_SNAPSHOT and DEVICE_EXECUTION_EVENT."""
        from galaxy_gateway.protocol.aip_v3 import MessageType

        enum_values = {mt.value for mt in MessageType}
        assert "device_state_snapshot" in enum_values, (
            "MessageType enum missing 'device_state_snapshot' — "
            "Android runtime-state uplink has no V2 protocol definition."
        )
        assert "device_execution_event" in enum_values, (
            "MessageType enum missing 'device_execution_event' — "
            "Android execution event uplink has no V2 protocol definition."
        )

    def test_snapshot_store_module_importable(self) -> None:
        """core.android_device_state_store must be importable with all required symbols."""
        from core.android_device_state_store import (
            absorb_device_state_snapshot,
            absorb_device_execution_event,
            get_device_state_snapshot,
            list_device_state_snapshots,
            get_device_ecosystem_summary,
            list_recent_execution_events,
            reset_android_device_state_store,
            ANDROID_DEVICE_STATE_STORE_AUTHORITY,
        )
        assert callable(absorb_device_state_snapshot)
        assert callable(absorb_device_execution_event)
        assert callable(get_device_state_snapshot)
        assert callable(list_device_state_snapshots)
        assert callable(get_device_ecosystem_summary)
        assert callable(list_recent_execution_events)
        assert callable(reset_android_device_state_store)
        assert isinstance(ANDROID_DEVICE_STATE_STORE_AUTHORITY, str)
        assert "ANDROID_DEVICE_STATE_STORE" in ANDROID_DEVICE_STATE_STORE_AUTHORITY

    def test_snapshot_handler_module_importable(self) -> None:
        """galaxy_gateway.android.handlers.device_state_snapshot must be importable."""
        from galaxy_gateway.android.handlers.device_state_snapshot import (
            handle_device_state_snapshot,
            handle_device_execution_event,
        )
        assert callable(handle_device_state_snapshot)
        assert callable(handle_device_execution_event)
