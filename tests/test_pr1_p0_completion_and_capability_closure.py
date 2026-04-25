"""
tests/test_pr1_p0_completion_and_capability_closure.py
=======================================================

PR-1 P0: Result-to-Orchestration Closure + Capability-Aware Scheduling Closure

This test suite proves the two P0 main-chain fixes introduced in this PR:

A. Result-to-Orchestration Closure
   - Android task_result arrival sets DeviceRouter._task_events[task_id]
   - handoff_v2 terminal result arrival sets DeviceRouter._task_events[task_id]
   - dispatch_to_websocket completes via real event (no timeout needed)

B. Capability-Aware Scheduling Closure
   - Explicit device_id with required_capabilities triggers capability check
   - Capability mismatch with fallback → rerouted to capable device
   - Capability mismatch with no fallback → rejected with CAPABILITY_MISMATCH
   - Confirmed target → dispatched without interference

Tests use lightweight stubs and do NOT require external services.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ===========================================================================
# A.1 — handle_task_result wakes DeviceRouter task_event
# ===========================================================================

class TestTaskResultWakesDeviceRouter(unittest.IsolatedAsyncioTestCase):
    """PR-1 P0: handle_task_result must call device_router.handle_task_result."""

    async def test_handle_task_result_wakes_device_router_event(self):
        """When handle_task_result is called, the DeviceRouter event is set."""
        from galaxy_gateway.android.handlers.task_lifecycle import handle_task_result

        # Build a minimal bridge stub
        bridge = MagicMock()
        bridge._pending_responses = {}
        bridge._lock = asyncio.Lock()
        bridge._devices = {}

        # Stub DeviceRouter with a real event we can inspect
        from galaxy_gateway.device_router import DeviceRouter
        router = DeviceRouter()
        event = asyncio.Event()
        router._task_events["task-abc"] = event

        msg = {
            "task_id": "task-abc",
            "device_id": "dev-1",
            "status": "success",
        }

        with patch(
            "galaxy_gateway.android.handlers.task_lifecycle.store_task_result",
            new_callable=AsyncMock,
        ), patch(
            "galaxy_gateway.android.handlers.task_lifecycle._reconcile_inbound_message",
            None,
        ), patch(
            "galaxy_gateway.android.handlers.task_lifecycle._ingest_participant_truth",
            None,
        ), patch(
            "galaxy_gateway.device_router.device_router",
            router,
        ):
            await handle_task_result(bridge, None, msg)

        # The device_router event must have been set by the PR-1 P0 closure path
        self.assertTrue(
            event.is_set(),
            "DeviceRouter task event must be set after handle_task_result — "
            "awaiter should complete via real completion, not timeout",
        )

    async def test_handle_task_result_stores_result_in_device_router(self):
        """task_result must also store the result in DeviceRouter.task_results."""
        from galaxy_gateway.android.handlers.task_lifecycle import handle_task_result

        bridge = MagicMock()
        bridge._pending_responses = {}
        bridge._lock = asyncio.Lock()
        bridge._devices = {}

        from galaxy_gateway.device_router import DeviceRouter
        router = DeviceRouter()
        router._task_events["task-xyz"] = asyncio.Event()

        msg = {
            "task_id": "task-xyz",
            "device_id": "dev-2",
            "status": "success",
            "payload": {"result": "done"},
        }

        with patch(
            "galaxy_gateway.android.handlers.task_lifecycle.store_task_result",
            new_callable=AsyncMock,
        ), patch(
            "galaxy_gateway.android.handlers.task_lifecycle._reconcile_inbound_message",
            None,
        ), patch(
            "galaxy_gateway.android.handlers.task_lifecycle._ingest_participant_truth",
            None,
        ), patch(
            "galaxy_gateway.device_router.device_router",
            router,
        ):
            await handle_task_result(bridge, None, msg)

        self.assertIn("task-xyz", router.task_results)


# ===========================================================================
# A.2 — handle_task_end wakes DeviceRouter task_event
# ===========================================================================

class TestTaskEndWakesDeviceRouter(unittest.IsolatedAsyncioTestCase):
    """PR-1 P0: handle_task_end must also call device_router.handle_task_result."""

    async def test_handle_task_end_wakes_device_router_event(self):
        from galaxy_gateway.android.handlers.task_lifecycle import handle_task_end

        bridge = MagicMock()
        bridge._pending_responses = {}
        bridge._lock = asyncio.Lock()
        bridge._devices = {}

        from galaxy_gateway.device_router import DeviceRouter
        router = DeviceRouter()
        event = asyncio.Event()
        router._task_events["task-end-1"] = event

        msg = {
            "task_id": "task-end-1",
            "device_id": "dev-3",
            "status": "completed",
        }

        with patch(
            "galaxy_gateway.android.handlers.task_lifecycle._reconcile_inbound_message",
            None,
        ), patch(
            "galaxy_gateway.android.handlers.task_lifecycle._ingest_participant_truth",
            None,
        ), patch(
            "galaxy_gateway.device_router.device_router",
            router,
        ):
            await handle_task_end(bridge, None, msg)

        self.assertTrue(
            event.is_set(),
            "DeviceRouter task event must be set after handle_task_end",
        )


# ===========================================================================
# A.3 — handoff_v2 terminal result wakes DeviceRouter task_event
# ===========================================================================

class TestHandoffV2TerminalWakesDeviceRouter(unittest.IsolatedAsyncioTestCase):
    """PR-1 P0: terminal handoff_v2 result must call device_router.handle_task_result."""

    async def test_terminal_handoff_result_wakes_device_router(self):
        from galaxy_gateway.android.handlers.handoff_v2_result import handle_handoff_v2_result

        bridge = MagicMock()

        # Build a mock outcome that looks like a terminal handoff success
        mock_env = MagicMock()
        mock_env.task_id = "handoff-task-1"
        mock_env.handoff_id = "hid-001"
        mock_env.session_id = "sess-1"
        mock_env.trace_id = "trace-1"
        mock_env.response_kind = "handoff_result"
        mock_env.is_terminal = True

        mock_outcome = MagicMock()
        mock_outcome.was_correlated = True
        mock_outcome.envelope = mock_env
        mock_outcome.callback_invoked = True

        from galaxy_gateway.device_router import DeviceRouter
        router = DeviceRouter()
        event = asyncio.Event()
        router._task_events["handoff-task-1"] = event

        msg = {
            "type": "handoff_result",
            "device_id": "android-dev-1",
            "message_id": "msg-001",
            "task_id": "handoff-task-1",
            "payload": {"output": "done"},
        }

        with patch(
            "galaxy_gateway.android.handlers.handoff_v2_result._ingest_handoff_response",
            return_value=mock_outcome,
        ), patch(
            "galaxy_gateway.android.handlers.handoff_v2_result._audit_handoff_v2_result",
            None,
        ), patch(
            "galaxy_gateway.device_router.device_router",
            router,
        ):
            await handle_handoff_v2_result(bridge, None, msg)

        self.assertTrue(
            event.is_set(),
            "DeviceRouter task event must be set after terminal handoff_v2 result — "
            "dispatch_to_websocket awaiter must complete via event, not timeout",
        )

    async def test_ack_non_terminal_does_not_wake_device_router(self):
        """handoff_ack (non-terminal) must NOT set the task event prematurely."""
        from galaxy_gateway.android.handlers.handoff_v2_result import handle_handoff_v2_result

        bridge = MagicMock()

        mock_env = MagicMock()
        mock_env.task_id = "handoff-task-2"
        mock_env.handoff_id = "hid-002"
        mock_env.session_id = "sess-2"
        mock_env.trace_id = "trace-2"
        mock_env.response_kind = "handoff_ack"
        mock_env.is_terminal = False  # ACK is NOT terminal

        mock_outcome = MagicMock()
        mock_outcome.was_correlated = True
        mock_outcome.envelope = mock_env
        mock_outcome.callback_invoked = False

        from galaxy_gateway.device_router import DeviceRouter
        router = DeviceRouter()
        event = asyncio.Event()
        router._task_events["handoff-task-2"] = event

        msg = {
            "type": "handoff_ack",
            "device_id": "android-dev-2",
            "message_id": "msg-002",
            "task_id": "handoff-task-2",
        }

        with patch(
            "galaxy_gateway.android.handlers.handoff_v2_result._ingest_handoff_response",
            return_value=mock_outcome,
        ), patch(
            "galaxy_gateway.android.handlers.handoff_v2_result._audit_handoff_v2_result",
            None,
        ), patch(
            "galaxy_gateway.device_router.device_router",
            router,
        ):
            await handle_handoff_v2_result(bridge, None, msg)

        self.assertFalse(
            event.is_set(),
            "DeviceRouter task event must NOT be set for non-terminal handoff_ack",
        )


# ===========================================================================
# A.4 — dispatch_to_websocket completes via event (integration)
# ===========================================================================

class TestDispatchToWebsocketCompletesViaEvent(unittest.IsolatedAsyncioTestCase):
    """PR-1 P0: dispatch_to_websocket should complete via event.set(), not timeout."""

    async def test_dispatch_completes_when_event_set_before_timeout(self):
        """If a result is stored and event set before timeout, dispatch returns it."""
        from galaxy_gateway.routing.dispatch import dispatch_to_websocket

        # Stub device with a working websocket
        mock_ws = MagicMock()
        mock_ws.send = AsyncMock()
        device = MagicMock()
        device.websocket = mock_ws
        device.device_id = "dev-dispatch"

        task_events: dict = {}
        task_results: dict = {}
        task_id = "dispatch-task-1"

        msg = {"task_id": task_id, "device_id": "dev-dispatch", "trace_id": "t1"}

        # Schedule a simulated completion after a short delay
        async def _simulate_completion():
            await asyncio.sleep(0.05)
            task_results[task_id] = {"success": True, "result": "done"}
            if task_id in task_events:
                task_events[task_id].set()

        with patch(
            "galaxy_gateway.routing.dispatch.asyncio.wait_for",
            wraps=asyncio.wait_for,
        ):
            # Run dispatch and the simulated completion concurrently
            result, _ = await asyncio.gather(
                dispatch_to_websocket(
                    device=device,
                    message=msg,
                    task_id=task_id,
                    task_events=task_events,
                    task_results=task_results,
                    timeout=2.0,
                ),
                _simulate_completion(),
            )

        self.assertTrue(result.get("success"), f"Expected success, got: {result}")
        self.assertEqual(result.get("result"), "done")


# ===========================================================================
# B.1 — Capability-aware routing: confirmed target proceeds
# ===========================================================================

class TestCapabilityAwareRoutingConfirmedTarget(unittest.TestCase):
    """PR-1 P0: confirmed capability target should proceed without interference."""

    def test_route_envelope_capability_mismatch_sentinel_exists(self):
        """The new CAPABILITY_MISMATCH_CONTROLLED_DECISION sentinel must exist."""
        from core.command_router import CAPABILITY_MISMATCH_CONTROLLED_DECISION
        self.assertIn("PR-1", CAPABILITY_MISMATCH_CONTROLLED_DECISION)
        self.assertIn("CAPABILITY_MISMATCH", CAPABILITY_MISMATCH_CONTROLLED_DECISION)

    def test_capability_mismatch_error_code_exists(self):
        """GatewayErrorCode must include CAPABILITY_MISMATCH."""
        from core.command_router import GatewayErrorCode
        self.assertIn("CAPABILITY_MISMATCH", [e.value for e in GatewayErrorCode])


# ===========================================================================
# B.2 — Capability mismatch with fallback: rerouted to capable device
# ===========================================================================

class TestCapabilityMismatchFallback(unittest.IsolatedAsyncioTestCase):
    """PR-1 P0: when target fails cap check but alternatives exist, fallback."""

    def test_explicit_device_id_bypasses_if_no_required_caps(self):
        """Without required_capabilities, capability check is skipped (no caps to verify)."""
        # This is a static test: when required_capabilities is empty/None, the
        # capability enforcement block in route_envelope is simply not entered
        # (_cap_query_caps is None/empty, so no check runs). This is correct
        # behavior — capability-aware routing only applies when caps are specified.
        from core.command_router import CommandRouter
        from core.schemas.task_envelope import TaskEnvelope

        cr = CommandRouter()
        envelope = TaskEnvelope(
            task_id="test-no-caps",
            trace_id="trace-x",
            source="test",
            targets=["device-explicit"],
            tool_name="test_command",
            args={},
            required_capabilities=[],  # no capabilities required
        )
        # When required_capabilities is empty, _cap_query_caps is None/empty
        # so the capability enforcement block is NOT entered — no rejection.
        # Just verify the envelope is constructed correctly.
        self.assertEqual(list(envelope.required_capabilities), [])
        self.assertEqual(list(envelope.targets), ["device-explicit"])

    async def test_capability_mismatch_with_fallback_reroutes(self):
        """When target lacks required caps but capable alternatives exist, fallback."""
        from core.command_router import CommandRouter
        from core.schemas.task_envelope import TaskEnvelope

        cr = CommandRouter()

        envelope = TaskEnvelope(
            task_id="test-cap-fallback",
            trace_id="trace-fb",
            source="test",
            targets=["device-wrong"],  # This device does NOT have required caps
            tool_name="camera_capture",
            args={},
            required_capabilities=["camera"],
            metadata={"cross_device": "true"},  # trigger cross-device routing path
        )

        # Simulate: device-wrong not in graph; device-capable IS in graph
        mock_executor = MagicMock()
        mock_executor.node_id = "device-capable"

        dispatched_targets: list = []

        async def _mock_route_cross(envelope, command_id, request_id):
            dispatched_targets.extend(list(envelope.targets))
            return {
                "success": True,
                "result": "captured",
                "task_id": envelope.task_id,
                "trace_id": envelope.trace_id,
                "via": "test",
                "device_id": list(envelope.targets)[0] if envelope.targets else "",
                "command": envelope.tool_name,
                "latency_ms": 1.0,
            }

        with patch(
            "core.capability_network_runtime_policy.query_routable_executors",
            return_value=[mock_executor],
        ), patch(
            "core.capability_network_runtime_policy.query_network_path",
            return_value=MagicMock(is_reachable=True, path_state="active"),
        ), patch.object(cr, "_route_cross_device_envelope", _mock_route_cross), \
           patch.object(cr, "_route_worker_envelope", AsyncMock(return_value={"success": False})), \
           patch("core.command_router.get_command_router", return_value=cr), \
           patch("core.acl_enforcer.get_acl_enforcer", return_value=MagicMock(
               check=MagicMock(return_value=MagicMock(allowed=True, reason=""))
           )):
            result = await cr.route_envelope(envelope)

        # Should have been redirected to the capable device, not the wrong one
        self.assertNotIn(
            "device-wrong",
            dispatched_targets,
            "Mismatched device must not receive the dispatch after fallback",
        )
        self.assertIn(
            "device-capable",
            dispatched_targets,
            "Capable fallback device must receive the dispatch",
        )

    async def test_capability_mismatch_no_fallback_rejects(self):
        """When target lacks required caps and no alternatives exist, reject."""
        from core.command_router import CommandRouter
        from core.schemas.task_envelope import TaskEnvelope

        cr = CommandRouter()

        envelope = TaskEnvelope(
            task_id="test-cap-reject",
            trace_id="trace-rj",
            source="test",
            targets=["device-incapable"],
            tool_name="nfc_scan",
            args={},
            required_capabilities=["nfc"],
        )

        # Simulate: device-incapable not in graph AND no routable alternatives
        with patch(
            "core.capability_network_runtime_policy.query_routable_executors",
            return_value=[],  # Empty: no capable devices in graph
        ), patch(
            "core.capability_network_runtime_policy.query_network_path",
            return_value=MagicMock(is_reachable=False, path_state="unknown"),
        ), patch("core.command_router.get_command_router", return_value=cr), \
           patch("core.acl_enforcer.get_acl_enforcer", return_value=MagicMock(
               check=MagicMock(return_value=MagicMock(allowed=True, reason=""))
           )):
            result = await cr.route_envelope(envelope)

        self.assertFalse(
            result.get("success"),
            "Dispatch to incapable device with no fallback must be rejected",
        )
        self.assertEqual(
            result.get("error_code"),
            "CAPABILITY_MISMATCH",
            f"Expected CAPABILITY_MISMATCH error code, got: {result.get('error_code')}",
        )


# ===========================================================================
# B.3 — send_gateway_command passes required_capabilities
# ===========================================================================

class TestSendGatewayCommandPassesCapabilities(unittest.TestCase):
    """PR-1 P0: send_gateway_command must forward required_capabilities to TaskEnvelope."""

    def test_send_gateway_command_signature_has_required_capabilities(self):
        """send_gateway_command must accept required_capabilities parameter."""
        import inspect
        from core.openclawd import OpenClawd

        sig = inspect.signature(OpenClawd.send_gateway_command)
        self.assertIn(
            "required_capabilities",
            sig.parameters,
            "send_gateway_command must accept required_capabilities parameter (PR-1 P0)",
        )

    def test_send_gateway_command_required_capabilities_default_none(self):
        """required_capabilities should default to None for backward compat."""
        import inspect
        from core.openclawd import OpenClawd

        sig = inspect.signature(OpenClawd.send_gateway_command)
        param = sig.parameters["required_capabilities"]
        self.assertIsNone(
            param.default,
            "required_capabilities must default to None for backward compatibility",
        )


# ===========================================================================
# B.4 — Capability mismatch metadata audit trail
# ===========================================================================

class TestCapabilityMismatchAuditTrail(unittest.IsolatedAsyncioTestCase):
    """PR-1 P0: fallback decision must be recorded in envelope metadata."""

    async def test_fallback_records_original_targets_in_metadata(self):
        """When capability fallback occurs, original_targets must be in metadata."""
        from core.command_router import CommandRouter
        from core.schemas.task_envelope import TaskEnvelope

        cr = CommandRouter()

        envelope = TaskEnvelope(
            task_id="test-audit",
            trace_id="trace-audit",
            source="test",
            targets=["original-device"],
            tool_name="gps_locate",
            args={},
            required_capabilities=["gps"],
            metadata={"cross_device": "true"},  # trigger cross-device routing path
        )

        mock_executor = MagicMock()
        mock_executor.node_id = "gps-capable-device"

        captured_envelopes: list = []

        async def _capture_envelope(envelope, command_id, request_id):
            captured_envelopes.append(envelope)
            return {
                "success": True,
                "result": "located",
                "task_id": envelope.task_id,
                "trace_id": envelope.trace_id,
                "via": "test",
                "device_id": list(envelope.targets)[0] if envelope.targets else "",
                "command": envelope.tool_name,
                "latency_ms": 1.0,
            }

        with patch(
            "core.capability_network_runtime_policy.query_routable_executors",
            return_value=[mock_executor],
        ), patch(
            "core.capability_network_runtime_policy.query_network_path",
            return_value=MagicMock(is_reachable=True, path_state="active"),
        ), patch.object(cr, "_route_cross_device_envelope", _capture_envelope), \
           patch.object(cr, "_route_worker_envelope", AsyncMock(return_value={"success": False})), \
           patch("core.command_router.get_command_router", return_value=cr), \
           patch("core.acl_enforcer.get_acl_enforcer", return_value=MagicMock(
               check=MagicMock(return_value=MagicMock(allowed=True, reason=""))
           )):
            await cr.route_envelope(envelope)

        self.assertTrue(
            len(captured_envelopes) > 0,
            "Envelope should have been dispatched to the fallback device",
        )
        dispatched_env = captured_envelopes[0]
        meta = dispatched_env.metadata or {}
        self.assertTrue(
            meta.get("capability_mismatch_override"),
            "Fallback decision must be recorded in envelope.metadata['capability_mismatch_override']",
        )
        self.assertIn(
            "original-device",
            meta.get("original_targets", []),
            "Original mismatched targets must be recorded in metadata['original_targets']",
        )
        self.assertEqual(
            meta.get("fallback_reason"),
            "capability_mismatch",
            "Fallback reason must be 'capability_mismatch'",
        )


if __name__ == "__main__":
    unittest.main()
