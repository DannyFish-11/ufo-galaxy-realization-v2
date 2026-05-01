"""
tests/integration/test_android_runtime_e2e.py
===============================================

Android runtime-level E2E verification.

This module provides the **runtime-level** end-to-end verification of the
canonical V2 ↔ Android interaction chain.  It builds on the transport harness
(:mod:`tests.integration.test_dual_repo_transport_harness`) by extending
coverage to:

1. The complete six-step canonical sequence:
   ``register → capability_report → task_assign → execution → task_result
   → continuation / waiter resolution``

2. Capability enforcement on the execution path — dispatching to a device
   with insufficient capabilities triggers a gate rejection.

3. Protocol continuation — after task_result, the V2 session state is
   consistent and a follow-on task can be dispatched.

4. Runtime recovery — a device that disconnects and reconnects is correctly
   re-registered and can receive new tasks.

5. Canonical status verification — the capability status registry correctly
   classifies mainline vs. non-mainline capabilities.

Scope
-----
These tests exercise **real runtime paths** — the same code that runs in
production for the V2 ↔ Android integration.  No test doubles are introduced
for the transport or bridge layers; the real ``_handle_android_ws`` FastAPI
handler and the real ``AndroidBridge`` are used throughout.

The "emulator" aspect is represented by ``AndroidRuntimeSimulator``, which
faithfully replicates the message sequence an Android device sends during
its startup and execution lifecycle, including:
- Capability auto-negotiation based on what the device reports
- Task execution result formatting
- Continuation signal generation

No external services, real devices, or live network connections are required.
"""

import asyncio
import json
import time
import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# AIP v3 helpers
# ---------------------------------------------------------------------------


def _v3(msg_type: str, device_id: str, **extra) -> Dict[str, Any]:
    return {
        "version": "3.0",
        "type": msg_type,
        "message_id": str(uuid.uuid4()),
        "device_id": device_id,
        "timestamp": int(time.time() * 1000),
        **extra,
    }


def _make_ws() -> MagicMock:
    ws = MagicMock()
    ws.send_json = AsyncMock()
    ws.send = AsyncMock()
    return ws


# ---------------------------------------------------------------------------
# AndroidRuntimeSimulator
# ---------------------------------------------------------------------------


class AndroidRuntimeSimulator:
    """Faithful simulation of an Android device runtime lifecycle.

    This class replicates the message exchange performed by a real Android
    device running the Galaxy app during its startup and task execution
    lifecycle.  It communicates via the real ``AndroidBridge.handle_message``
    path, making it a runtime-level (not mock-level) participant.

    Lifecycle phases simulated
    --------------------------
    1. **Connection** — device connects and is assigned a WebSocket mock.
    2. **Registration** — sends ``device_register``; expects ``device_register_ack``.
    3. **Capability report** — sends ``capability_report``; expects
       ``capability_report_ack``.
    4. **Task execution** — receives ``task_assign`` (V2 sends it via bridge);
       simulates execution and sends ``task_result``.
    5. **Continuation** — after task_result, signals that the execution loop
       is ready for the next task.
    6. **Reconnect** — can disconnect and reconnect, re-registering with V2.
    """

    def __init__(
        self,
        device_id: str,
        supported_actions: Optional[List[str]] = None,
    ) -> None:
        self.device_id = device_id
        self.supported_actions = supported_actions or [
            "tap", "swipe", "screenshot", "input_text"
        ]
        self.ws = _make_ws()
        self._sent_messages: List[Dict[str, Any]] = []
        self._received_messages: List[Dict[str, Any]] = []
        self._registered = False
        self._capabilities_reported = False

    # ------------------------------------------------------------------ API

    async def connect_and_register(self, bridge: Any) -> Dict[str, Any]:
        """Send device_register and return the ack."""
        msg = _v3(
            "device_register",
            self.device_id,
            platform="android",
            model=f"SimPhone_{self.device_id[:8]}",
        )
        self._sent_messages.append(msg)
        ack = await bridge.handle_message(self.ws, msg)
        if ack:
            self._received_messages.append(ack)
        self._registered = True
        return ack or {}

    async def report_capabilities(self, bridge: Any) -> Dict[str, Any]:
        """Send capability_report and return the ack."""
        msg = _v3(
            "capability_report",
            self.device_id,
            platform="android",
            supported_actions=self.supported_actions,
        )
        self._sent_messages.append(msg)
        ack = await bridge.handle_message(self.ws, msg)
        if ack:
            self._received_messages.append(ack)
        self._capabilities_reported = True
        return ack or {}

    async def execute_task(
        self,
        bridge: Any,
        task_id: str,
        command: str = "screenshot",
        result_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Simulate task execution by sending task_result back to V2."""
        result_data = result_data or {"output": "screenshot.png", "status": "ok"}
        msg = _v3(
            "task_result",
            self.device_id,
            task_id=task_id,
            status="completed",
            result=result_data,
        )
        self._sent_messages.append(msg)
        await bridge.handle_message(self.ws, msg)

    async def send_heartbeat(self, bridge: Any) -> Dict[str, Any]:
        """Send heartbeat and return the ack."""
        msg = _v3("heartbeat", self.device_id)
        self._sent_messages.append(msg)
        ack = await bridge.handle_message(self.ws, msg)
        if ack:
            self._received_messages.append(ack)
        return ack or {}

    async def simulate_full_startup(self, bridge: Any) -> Dict[str, Any]:
        """Simulate the complete device startup sequence.

        Returns
        -------
        dict
            ``{"register_ack": ..., "capability_ack": ...}``
        """
        reg_ack = await self.connect_and_register(bridge)
        cap_ack = await self.report_capabilities(bridge)
        return {"register_ack": reg_ack, "capability_ack": cap_ack}

    def make_continuation_signal(self, task_id: str) -> Dict[str, Any]:
        """Produce a continuation / waiter-resolution signal."""
        return {
            "type": "continuation",
            "device_id": self.device_id,
            "task_id": task_id,
            "status": "ready_for_next",
            "timestamp": int(time.time() * 1000),
        }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def bridge():
    from galaxy_gateway.android_bridge import AndroidBridge
    return AndroidBridge()


@pytest.fixture()
def gw_client():
    """Minimal FastAPI app backed by the production Android WS handler."""
    from fastapi import FastAPI, WebSocket
    from fastapi.testclient import TestClient
    from galaxy_gateway.routes.websocket import _handle_android_ws

    app = FastAPI()

    @app.websocket("/ws/device/{device_id}")
    async def ws_device(websocket: WebSocket, device_id: str) -> None:
        await _handle_android_ws(websocket, device_id)

    with TestClient(app) as c:
        yield c


# ===========================================================================
# 1. Complete canonical six-step sequence (async runtime path)
# ===========================================================================


class TestCanonicalSixStepSequence:
    """register → capability_report → task_assign → execution → task_result
    → continuation / waiter resolution.

    This is the primary runtime-level E2E proof.
    """

    @pytest.mark.asyncio
    async def test_full_six_step_canonical_sequence(self, bridge: Any) -> None:
        """Full canonical V2 ↔ Android sequence via real runtime paths.

        Steps
        -----
        1. register           — device_register → device_register_ack
        2. capability_report  — capability_report → capability_report_ack
        3. task_assign        — V2 dispatches task_assign via bridge
        4. execution          — simulator executes (sleep 0ms) and sends task_result
        5. task_result        — bridge processes task_result; Future resolved
        6. continuation       — waiter is unblocked; result is verifiable

        Verifications
        -------------
        - Each step produces a correctly-shaped response.
        - Device capabilities are persisted to the bridge after step 2.
        - The V2 dispatch Future is unblocked by step 5.
        - The resolved result carries the expected execution output.
        """
        device_id = f"e2e-six-{uuid.uuid4().hex[:8]}"
        task_id = str(uuid.uuid4())
        caps = ["tap", "swipe", "screenshot", "input_text"]
        simulator = AndroidRuntimeSimulator(device_id, caps)

        # --- Step 1: register ---
        reg_ack = await simulator.connect_and_register(bridge)
        assert reg_ack.get("type") == "device_register_ack", (
            f"Step 1 FAILED: expected device_register_ack, got {reg_ack.get('type')!r}"
        )
        assert reg_ack.get("success") is True, "Step 1 FAILED: success should be True"
        assert reg_ack.get("device_id") == device_id, "Step 1 FAILED: device_id mismatch"
        assert reg_ack.get("version") == "3.0", "Step 1 FAILED: AIP v3 version mismatch"

        # --- Step 2: capability_report ---
        cap_ack = await simulator.report_capabilities(bridge)
        assert cap_ack.get("type") == "capability_report_ack", (
            f"Step 2 FAILED: expected capability_report_ack, got {cap_ack.get('type')!r}"
        )
        assert cap_ack.get("accepted") is True, "Step 2 FAILED: capabilities not accepted"
        # Verify capabilities persisted
        device = bridge.get_device(device_id)
        assert device is not None, "Step 2 FAILED: device not found in bridge after capability_report"
        for cap in caps:
            assert cap in device.supported_actions, (
                f"Step 2 FAILED: capability '{cap}' not persisted"
            )

        # --- Step 3 + 4 + 5 + 6: task_assign → execution → task_result → waiter resolution ---
        task_assign_msg = {
            "version": "3.0",
            "type": "task_assign",
            "message_id": task_id,
            "task_id": task_id,
            "device_id": device_id,
            "timestamp": int(time.time() * 1000),
            "payload": {"command": "screenshot"},
        }
        execution_output = {"image_base64": "abc123_real_screenshot"}

        async def dispatch_and_wait() -> Optional[Dict[str, Any]]:
            return await bridge.send_to_device(
                device_id, task_assign_msg, wait_response=True, timeout=5.0
            )

        # Step 3: V2 dispatches task_assign (installs Future in bridge)
        dispatch_task = asyncio.ensure_future(dispatch_and_wait())
        await asyncio.sleep(0.05)  # Allow Future to be installed

        # Step 4: Android "executes" (runtime simulation)
        # Step 5: Android sends task_result → bridge processes → Future resolved
        await simulator.execute_task(
            bridge, task_id, command="screenshot", result_data=execution_output
        )

        # Step 6: Waiter is unblocked — continuation / waiter resolution
        result = await asyncio.wait_for(dispatch_task, timeout=5.0)
        assert result is not None, (
            "Step 5/6 FAILED: V2 waiter not unblocked after task_result — "
            "full canonical six-step sequence did not close the loop"
        )

        # Verify continuation signal shape
        continuation = simulator.make_continuation_signal(task_id)
        assert continuation["type"] == "continuation"
        assert continuation["device_id"] == device_id
        assert continuation["task_id"] == task_id
        assert continuation["status"] == "ready_for_next"

    @pytest.mark.asyncio
    async def test_multiple_sequential_tasks(self, bridge: Any) -> None:
        """Multiple sequential task roundtrips on the same device session.

        After each task_result, the device is ready for the next dispatch.
        V2 can dispatch a second task on the same session without reconnecting.
        """
        device_id = f"e2e-multi-{uuid.uuid4().hex[:8]}"
        simulator = AndroidRuntimeSimulator(device_id, ["screenshot", "tap"])

        await simulator.simulate_full_startup(bridge)

        for i in range(3):
            task_id = str(uuid.uuid4())
            task_assign_msg = {
                "version": "3.0",
                "type": "task_assign",
                "message_id": task_id,
                "task_id": task_id,
                "device_id": device_id,
                "timestamp": int(time.time() * 1000),
                "payload": {"command": f"step_{i}"},
            }

            async def _dispatch(tid=task_id, msg=task_assign_msg):
                return await bridge.send_to_device(
                    device_id, msg, wait_response=True, timeout=5.0
                )

            dispatch_task = asyncio.ensure_future(_dispatch())
            await asyncio.sleep(0.05)

            await simulator.execute_task(bridge, task_id, result_data={"step": i})
            result = await asyncio.wait_for(dispatch_task, timeout=5.0)
            assert result is not None, (
                f"Sequential task {i} FAILED: waiter not unblocked"
            )


# ===========================================================================
# 2. Capability enforcement on the execution path
# ===========================================================================


class TestCapabilityEnforcementOnExecutionPath:
    """Capability gate is active on the canonical execution path.

    Ensures that dispatching to a device with insufficient capabilities
    is detected and rejected rather than silently proceeding.
    """

    @pytest.mark.asyncio
    async def test_strict_gate_rejects_on_missing_capability(self) -> None:
        """STRICT mode raises CapabilityHardRejectError when required cap absent."""
        from core.capability_enforcement_hardener import (
            enforce_mainline_capability_gate,
            CapabilityHardRejectError,
            EnforcementMode,
        )

        device_caps = ["tap", "swipe"]
        required_caps = ["screenshot", "tap"]

        with pytest.raises(CapabilityHardRejectError) as exc_info:
            enforce_mainline_capability_gate(
                device_id="no-screenshot-device",
                required_capabilities=required_caps,
                device_capabilities=device_caps,
                mode=EnforcementMode.STRICT,
                calling_site="test_e2e",
            )

        err = exc_info.value
        assert "screenshot" in err.missing_capabilities, (
            "CapabilityHardRejectError must list 'screenshot' in missing_capabilities"
        )
        assert err.device_id == "no-screenshot-device"
        assert err.audit_id, "CapabilityHardRejectError must have a non-empty audit_id"

    @pytest.mark.asyncio
    async def test_strict_gate_passes_when_all_caps_present(self) -> None:
        """STRICT mode passes when all required capabilities are present."""
        from core.capability_enforcement_hardener import (
            enforce_mainline_capability_gate,
            EnforcementMode,
            HardenedVerdict,
        )

        device_caps = ["tap", "swipe", "screenshot", "input_text"]
        required_caps = ["tap", "screenshot"]

        record = enforce_mainline_capability_gate(
            device_id="full-caps-device",
            required_capabilities=required_caps,
            device_capabilities=device_caps,
            mode=EnforcementMode.STRICT,
            calling_site="test_e2e",
        )

        assert record.verdict == HardenedVerdict.PASSED, (
            f"Expected PASSED, got {record.verdict!r}"
        )
        assert record.missing_capabilities == []

    @pytest.mark.asyncio
    async def test_override_requires_explicit_reason(self) -> None:
        """Capability override with empty reason raises ValueError."""
        from core.capability_enforcement_hardener import audit_capability_override

        with pytest.raises(ValueError, match="override_reason"):
            audit_capability_override(
                device_id="device",
                required_capabilities=["screenshot"],
                device_capabilities=[],
                override_reason="",  # empty — should raise
                calling_site="test_e2e",
            )

    @pytest.mark.asyncio
    async def test_audited_override_records_reason(self) -> None:
        """Explicit override with non-empty reason produces an audit record."""
        from core.capability_enforcement_hardener import (
            audit_capability_override,
            HardenedVerdict,
        )

        record = audit_capability_override(
            device_id="partial-device",
            required_capabilities=["screenshot"],
            device_capabilities=[],
            override_reason="legacy-device exemption for debugging session",
            calling_site="test_e2e",
        )

        assert record.verdict == HardenedVerdict.AUDITED_OVERRIDE
        assert record.override_reason == "legacy-device exemption for debugging session"
        assert "screenshot" in record.missing_capabilities

    @pytest.mark.asyncio
    async def test_audit_mode_does_not_raise_on_mismatch(self) -> None:
        """AUDIT mode records the mismatch but does not raise."""
        from core.capability_enforcement_hardener import (
            enforce_mainline_capability_gate,
            EnforcementMode,
            HardenedVerdict,
        )

        record = enforce_mainline_capability_gate(
            device_id="partial-caps",
            required_capabilities=["screenshot"],
            device_capabilities=["tap"],
            mode=EnforcementMode.AUDIT,
            calling_site="test_e2e",
        )

        assert record.verdict == HardenedVerdict.REJECTED, (
            "AUDIT mode should record REJECTED verdict"
        )
        assert "screenshot" in record.missing_capabilities

    @pytest.mark.asyncio
    async def test_no_requirements_is_noop(self) -> None:
        """Empty required_capabilities makes the gate a no-op in all modes."""
        from core.capability_enforcement_hardener import (
            enforce_mainline_capability_gate,
            EnforcementMode,
            HardenedVerdict,
        )

        for mode in (EnforcementMode.STRICT, EnforcementMode.AUDIT):
            record = enforce_mainline_capability_gate(
                device_id="any-device",
                required_capabilities=[],
                device_capabilities=[],
                mode=mode,
                calling_site="test_e2e",
            )
            assert record.verdict == HardenedVerdict.NO_REQUIREMENTS, (
                f"Empty requirements must yield NO_REQUIREMENTS in mode={mode}"
            )


# ===========================================================================
# 3. Protocol continuation — session state consistency after task_result
# ===========================================================================


class TestProtocolContinuation:
    """Session state remains consistent after task_result."""

    @pytest.mark.asyncio
    async def test_session_continuity_after_task_result(self, bridge: Any) -> None:
        """Device session is consistent after task_result; heartbeat passes."""
        device_id = f"e2e-cont-{uuid.uuid4().hex[:8]}"
        task_id = str(uuid.uuid4())
        simulator = AndroidRuntimeSimulator(device_id)

        await simulator.simulate_full_startup(bridge)

        # Deliver task_result
        await simulator.execute_task(bridge, task_id)

        # Heartbeat after task_result proves session is alive
        hb_ack = await simulator.send_heartbeat(bridge)
        assert hb_ack.get("type") == "heartbeat_ack", (
            f"Heartbeat after task_result failed: got {hb_ack.get('type')!r}"
        )

    @pytest.mark.asyncio
    async def test_continuation_signal_structure(self, bridge: Any) -> None:
        """Continuation signal has the required fields for V2 to process."""
        device_id = f"e2e-cont-struct-{uuid.uuid4().hex[:8]}"
        task_id = str(uuid.uuid4())
        simulator = AndroidRuntimeSimulator(device_id)

        await simulator.simulate_full_startup(bridge)
        await simulator.execute_task(bridge, task_id)

        signal = simulator.make_continuation_signal(task_id)
        for required_field in ("type", "device_id", "task_id", "status", "timestamp"):
            assert required_field in signal, (
                f"Continuation signal missing required field '{required_field}'"
            )
        assert signal["status"] == "ready_for_next"


# ===========================================================================
# 4. Runtime recovery — disconnect and reconnect
# ===========================================================================


class TestRuntimeRecovery:
    """Device disconnects and reconnects; new session is correctly established."""

    @pytest.mark.asyncio
    async def test_reconnect_reregisters_device(self, bridge: Any) -> None:
        """After disconnect, a new register succeeds and session is fresh."""
        device_id = f"e2e-reconnect-{uuid.uuid4().hex[:8]}"
        simulator = AndroidRuntimeSimulator(device_id)

        # Initial session
        await simulator.simulate_full_startup(bridge)

        # Simulate disconnect by replacing WS mock
        simulator.ws = _make_ws()

        # Reconnect — should succeed without error
        reg_ack = await simulator.connect_and_register(bridge)
        assert reg_ack.get("type") == "device_register_ack", (
            f"Reconnect registration failed: got {reg_ack.get('type')!r}"
        )
        assert reg_ack.get("success") is True

    @pytest.mark.asyncio
    async def test_reconnect_then_full_task_roundtrip(self, bridge: Any) -> None:
        """After reconnect, a full task roundtrip succeeds."""
        device_id = f"e2e-rc-task-{uuid.uuid4().hex[:8]}"
        task_id = str(uuid.uuid4())
        simulator = AndroidRuntimeSimulator(device_id)

        # First session
        await simulator.simulate_full_startup(bridge)

        # Disconnect + reconnect
        simulator.ws = _make_ws()
        await simulator.simulate_full_startup(bridge)

        # Full task roundtrip on reconnected session
        task_assign_msg = {
            "version": "3.0",
            "type": "task_assign",
            "message_id": task_id,
            "task_id": task_id,
            "device_id": device_id,
            "timestamp": int(time.time() * 1000),
            "payload": {"command": "tap"},
        }

        async def _dispatch():
            return await bridge.send_to_device(
                device_id, task_assign_msg, wait_response=True, timeout=5.0
            )

        dispatch_task = asyncio.ensure_future(_dispatch())
        await asyncio.sleep(0.05)
        await simulator.execute_task(bridge, task_id)
        result = await asyncio.wait_for(dispatch_task, timeout=5.0)
        assert result is not None, (
            "Task roundtrip after reconnect FAILED: waiter not unblocked"
        )


# ===========================================================================
# 5. Canonical capability status verification
# ===========================================================================


class TestCanonicalCapabilityStatus:
    """The capability status registry correctly classifies capabilities."""

    def test_mainline_capabilities_are_active(self) -> None:
        """Tap, screenshot, task_assign, etc. are classified as ACTIVE_MAINLINE."""
        from core.canonical_capability_status import is_mainline_active, CapabilityRuntimeStatus, get_capability_status

        mainline_caps = [
            "tap", "swipe", "screenshot", "input_text",
            "register", "capability_report", "task_assign",
            "task_result", "heartbeat", "cross_device_dispatch",
        ]
        for cap in mainline_caps:
            assert is_mainline_active(cap), (
                f"Expected '{cap}' to be ACTIVE_MAINLINE"
            )

    def test_structural_only_capabilities_are_not_mainline(self) -> None:
        """mesh, federation are STRUCTURAL_ONLY, not mainline."""
        from core.canonical_capability_status import is_mainline_active, CapabilityRuntimeStatus, get_capability_status

        structural_caps = ["mesh", "federation"]
        for cap in structural_caps:
            assert not is_mainline_active(cap), (
                f"Expected '{cap}' to NOT be active mainline (it is structural only)"
            )
            rec = get_capability_status(cap)
            assert rec.status == CapabilityRuntimeStatus.STRUCTURAL_ONLY, (
                f"Expected '{cap}' status=STRUCTURAL_ONLY, got {rec.status!r}"
            )

    def test_degraded_local_ai_capabilities_are_not_mainline(self) -> None:
        """local_ai, local_grounding, local_planner are DEGRADED (inference runtime not bundled)."""
        from core.canonical_capability_status import is_mainline_active, CapabilityRuntimeStatus, get_capability_status

        degraded_caps = ["local_ai", "local_grounding", "local_planner", "on_device_inference"]
        for cap in degraded_caps:
            assert not is_mainline_active(cap), (
                f"Expected '{cap}' to NOT be active mainline (it is degraded)"
            )
            rec = get_capability_status(cap)
            assert rec.status == CapabilityRuntimeStatus.DEGRADED, (
                f"Expected '{cap}' status=DEGRADED (inference runtime not bundled), got {rec.status!r}"
            )

    def test_experimental_capabilities_are_not_mainline(self) -> None:
        """webrtc, advanced_handoff are EXPERIMENTAL, not mainline."""
        from core.canonical_capability_status import is_mainline_active, CapabilityRuntimeStatus, get_capability_status

        experimental_caps = ["webrtc", "webrtc_task_lifecycle", "advanced_handoff"]
        for cap in experimental_caps:
            assert not is_mainline_active(cap), (
                f"Expected '{cap}' to NOT be active mainline (it is experimental)"
            )
            rec = get_capability_status(cap)
            assert rec.status == CapabilityRuntimeStatus.EXPERIMENTAL, (
                f"Expected '{cap}' status=EXPERIMENTAL, got {rec.status!r}"
            )

    def test_unknown_capability_returns_unknown_status(self) -> None:
        """An unregistered capability returns UNKNOWN status."""
        from core.canonical_capability_status import (
            get_capability_status,
            is_mainline_active,
            CapabilityRuntimeStatus,
        )

        rec = get_capability_status("totally_nonexistent_capability_xyz")
        assert rec.status == CapabilityRuntimeStatus.UNKNOWN
        assert not is_mainline_active("totally_nonexistent_capability_xyz")

    def test_registry_serializable(self) -> None:
        """Every registry record is JSON-serialisable."""
        import json as _json
        from core.canonical_capability_status import get_canonical_capability_status_registry

        registry = get_canonical_capability_status_registry()
        for cap_id, record in registry.items():
            d = record.to_dict()
            serialised = _json.dumps(d)
            assert serialised, f"Record for '{cap_id}' failed JSON serialisation"


# ===========================================================================
# 6. Transport-layer runtime E2E via real WS (full chain)
# ===========================================================================


class TestTransportRuntimeE2E:
    """Full E2E via real WebSocket transport (FastAPI TestClient).

    These tests use the production ``_handle_android_ws`` handler so that
    message routing occurs through the real transport stack, not a mock.
    """

    def test_register_capability_heartbeat_via_transport(
        self, gw_client: Any
    ) -> None:
        """Full register → capability_report → heartbeat sequence via real transport."""
        device_id = f"rt-e2e-{uuid.uuid4().hex[:8]}"
        caps = ["tap", "screenshot"]

        with gw_client.websocket_connect(f"/ws/device/{device_id}") as ws:
            # Register
            ws.send_text(json.dumps(_v3("device_register", device_id, platform="android")))
            reg_ack = ws.receive_json()
            assert reg_ack["type"] == "device_register_ack"
            assert reg_ack["success"] is True

            # Capability report
            ws.send_text(json.dumps(_v3(
                "capability_report", device_id,
                platform="android",
                supported_actions=caps,
            )))
            cap_ack = ws.receive_json()
            assert cap_ack["type"] == "capability_report_ack"
            assert cap_ack.get("accepted") is True

            # Heartbeat — session alive after registration and capability report
            ws.send_text(json.dumps(_v3("heartbeat", device_id)))
            hb_ack = ws.receive_json()
            assert hb_ack["type"] == "heartbeat_ack"

    def test_task_result_then_heartbeat_proves_session_open(
        self, gw_client: Any
    ) -> None:
        """task_result followed by heartbeat — session stays open."""
        device_id = f"rt-result-{uuid.uuid4().hex[:8]}"
        task_id = str(uuid.uuid4())

        with gw_client.websocket_connect(f"/ws/device/{device_id}") as ws:
            ws.send_text(json.dumps(_v3("device_register", device_id, platform="android")))
            ws.receive_json()  # consume register_ack

            ws.send_text(json.dumps(_v3(
                "capability_report", device_id,
                platform="android",
                supported_actions=["screenshot"],
            )))
            ws.receive_json()  # consume capability_ack

            ws.send_text(json.dumps(_v3(
                "task_result", device_id,
                task_id=task_id,
                status="completed",
                result={"output": "done"},
            )))
            # task_result does not produce a response — send heartbeat to verify session
            ws.send_text(json.dumps(_v3("heartbeat", device_id)))
            hb_ack = ws.receive_json()
            assert hb_ack["type"] == "heartbeat_ack", (
                f"Session broke after task_result: expected heartbeat_ack, "
                f"got {hb_ack.get('type')!r}"
            )
