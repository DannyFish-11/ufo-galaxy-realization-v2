"""
tests/integration/websocket/test_android_snapshot_ws_transport.py
===================================================================
Android → V2 runtime state snapshot — WebSocket transport-layer evidence.

"""
import json
import time
import uuid
from typing import Any, Dict

import pytest


# ---------------------------------------------------------------------------
# Message builder
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


# ---------------------------------------------------------------------------
# Realistic Android snapshot payload
# ---------------------------------------------------------------------------

ANDROID_SNAPSHOT_PAYLOAD: Dict[str, Any] = {
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
    "runtime_health_snapshot": {
        "memory_mb": 2048,
        "cpu_load_pct": 12.5,
        "temperature_c": 38.0,
        "health_score": 0.97,
    },
}


# ---------------------------------------------------------------------------
# Fixtures — module-scoped following the pattern of test_aip_v3_ws_contracts.py
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def gw_client():
    """Minimal FastAPI app with Android WS routes — module-scoped.

    Mirrors the fixture in ``test_aip_v3_ws_contracts.py``, which is the
    tested-and-working pattern for WebSocket transport tests in this project.
    """
    from fastapi import FastAPI, Query, WebSocket
    from fastapi.testclient import TestClient
    from galaxy_gateway.app import _handle_android_ws

    minimal_app = FastAPI()

    @minimal_app.websocket("/ws/android/{device_id}")
    async def ws_android_primary(websocket: WebSocket, device_id: str):
        await _handle_android_ws(websocket, device_id)

    @minimal_app.websocket("/ws/android")
    async def ws_android_fallback(
        websocket: WebSocket, device_id: str = Query(None)
    ):
        if not device_id:
            device_id = str(uuid.uuid4())
        await _handle_android_ws(websocket, device_id)

    @minimal_app.websocket("/ws/device/{device_id}")
    async def ws_device(websocket: WebSocket, device_id: str):
        await _handle_android_ws(websocket, device_id)

    with TestClient(minimal_app) as c:
        yield c


# ===========================================================================
# Transport-layer tests
# ===========================================================================


class TestAndroidSnapshotWSTransport:
    """Prove the WebSocket transport-layer path for Android runtime state.

    Transport path: /ws/device/{device_id} → _handle_android_ws
    → AndroidBridge → handle_device_state_snapshot
    → android_device_state_store.absorb_device_state_snapshot()

    Each test resets the android_device_state_store inline (no autouse
    fixture) to avoid event-loop conflicts with asyncio_mode=auto when
    a function-scoped autouse fixture runs alongside a module-scoped
    TestClient fixture.
    """

    def test_ws_register_then_snapshot_activates_store(
        self, gw_client: Any
    ) -> None:
        """TRANSPORT PATH: WebSocket register + snapshot → store non-empty.

        This is the transport-layer complement to
        ``TestAndroidSnapshotBridgePath.test_register_then_snapshot_activates_store``
        in the bridge-layer test module.  Together they prove the full path
        from WebSocket bytes → absorbed state in the canonical store.
        """
        from core.android_device_state_store import (
            get_device_state_snapshot,
            reset_android_device_state_store,
        )
        reset_android_device_state_store()

        device_id = f"snap-ws-{uuid.uuid4().hex[:8]}"

        with gw_client.websocket_connect(f"/ws/device/{device_id}") as ws:
            # Step 1: register
            ws.send_text(json.dumps(_v3(
                "device_register", device_id, platform="android", model="StubPhone"
            )))
            reg_ack = ws.receive_json()
            assert reg_ack["type"] == "device_register_ack", (
                f"Transport registration failed: got {reg_ack.get('type')!r}"
            )

            # Step 2: send device_state_snapshot
            ws.send_text(json.dumps(_v3(
                "device_state_snapshot",
                device_id,
                payload=ANDROID_SNAPSHOT_PAYLOAD,
            )))
            snap_ack = ws.receive_json()
            assert snap_ack["type"] == "device_state_snapshot_ack", (
                f"Transport snapshot failed: got {snap_ack.get('type')!r}"
            )
            assert snap_ack.get("status") == "absorbed", (
                f"Transport snapshot not absorbed: status={snap_ack.get('status')!r}. "
                "The canonical absorb/store path may have thrown an exception."
            )

        # Post-connection: verify store was populated through the transport path
        stored = get_device_state_snapshot(device_id)
        assert stored is not None, (
            "TRANSPORT PATH BROKEN: android_device_state_store is empty after "
            "device_state_snapshot was sent via WebSocket transport. "
            "The /ws/device/{device_id} → handler → store path is not closed."
        )
        assert stored.device_id == device_id
        assert stored.model_id == ANDROID_SNAPSHOT_PAYLOAD["model_id"], (
            f"Transport path stored wrong model_id: {stored.model_id!r} "
            f"expected: {ANDROID_SNAPSHOT_PAYLOAD['model_id']!r}. "
            "Android-derived values are not propagating through the transport path."
        )
        assert stored.model_ready == ANDROID_SNAPSHOT_PAYLOAD["model_ready"], (
            f"model_ready mismatch: stored={stored.model_ready!r}"
        )

    def test_ws_snapshot_ack_status_is_absorbed(self, gw_client: Any) -> None:
        """Snapshot ACK status via transport must be 'absorbed'.

        'error' status means the handler threw an exception.
        This test ensures the canonical absorb path runs cleanly through
        the full transport stack.
        """
        from core.android_device_state_store import reset_android_device_state_store
        reset_android_device_state_store()

        device_id = f"snap-ws-ack-{uuid.uuid4().hex[:8]}"
        snap_ack: Dict[str, Any] = {}

        with gw_client.websocket_connect(f"/ws/device/{device_id}") as ws:
            ws.send_text(json.dumps(_v3(
                "device_register", device_id, platform="android"
            )))
            ws.receive_json()  # consume register ack

            ws.send_text(json.dumps(_v3(
                "device_state_snapshot",
                device_id,
                payload=ANDROID_SNAPSHOT_PAYLOAD,
            )))
            snap_ack = ws.receive_json()

        assert snap_ack.get("status") != "error", (
            "Snapshot absorption failed with status='error' through the transport path. "
            "The canonical absorb path threw an exception.  "
            "Check that core.android_device_state_store is importable and working."
        )
        assert snap_ack.get("status") == "absorbed", (
            f"Expected status='absorbed', got {snap_ack.get('status')!r}"
        )

    def test_ws_snapshot_values_are_android_derived(
        self, gw_client: Any
    ) -> None:
        """Transport path stores Android-derived values, not synthetic defaults."""
        from core.android_device_state_store import (
            get_device_state_snapshot,
            reset_android_device_state_store,
        )
        reset_android_device_state_store()

        device_id = f"snap-ws-vals-{uuid.uuid4().hex[:8]}"

        with gw_client.websocket_connect(f"/ws/device/{device_id}") as ws:
            ws.send_text(json.dumps(_v3(
                "device_register", device_id, platform="android"
            )))
            ws.receive_json()

            ws.send_text(json.dumps(_v3(
                "device_state_snapshot",
                device_id,
                payload=ANDROID_SNAPSHOT_PAYLOAD,
            )))
            ws.receive_json()

        stored = get_device_state_snapshot(device_id)
        assert stored is not None

        # All values must match the Android-supplied payload
        assert stored.quantization == ANDROID_SNAPSHOT_PAYLOAD["quantization"]
        assert stored.current_fallback_tier == ANDROID_SNAPSHOT_PAYLOAD["current_fallback_tier"]
        assert stored.warmup_result == ANDROID_SNAPSHOT_PAYLOAD["warmup_result"]
        assert stored.local_loop_ready == ANDROID_SNAPSHOT_PAYLOAD["local_loop_ready"]
        assert stored.accessibility_ready == ANDROID_SNAPSHOT_PAYLOAD["accessibility_ready"]
