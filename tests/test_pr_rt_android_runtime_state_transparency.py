"""tests/test_pr_rt_android_runtime_state_transparency.py
==========================================================
PR-RT: Android Runtime-State Transparency Uplink — wire-path closure tests.

Validates:

A.  MessageType enum has DEVICE_STATE_SNAPSHOT and DEVICE_EXECUTION_EVENT.
B.  IngressEventKind has these two constants and they are in _ALL.
C.  IngressEventKind.normalise() resolves them correctly.
D.  _ANDROID_DOMAIN_KINDS in websocket_handler includes both new kinds.
E.  ingress_classifier maps both kinds to TRANSPORT class.
F.  android_bridge dispatch table registers handlers for both types.
G.  handle_device_state_snapshot calls absorb_device_state_snapshot and ACKs.
H.  handle_device_execution_event calls absorb_device_execution_event and ACKs.
I.  OperatorSnapshot has android_ecosystem field and to_dict includes it.
J.  operator_snapshot() populates android_ecosystem from the store.
K.  GET /api/v1/operator/devices/execution-events route exists in the router.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# A. MessageType enum
# ---------------------------------------------------------------------------


class TestMessageTypeEnum:
    def test_A01_device_state_snapshot_present(self):
        from galaxy_gateway.protocol.aip_v3 import MessageType
        assert MessageType.DEVICE_STATE_SNAPSHOT == "device_state_snapshot"

    def test_A02_device_execution_event_present(self):
        from galaxy_gateway.protocol.aip_v3 import MessageType
        assert MessageType.DEVICE_EXECUTION_EVENT == "device_execution_event"

    def test_A03_values_are_correct_strings(self):
        from galaxy_gateway.protocol.aip_v3 import MessageType
        assert MessageType("device_state_snapshot") == MessageType.DEVICE_STATE_SNAPSHOT
        assert MessageType("device_execution_event") == MessageType.DEVICE_EXECUTION_EVENT


# ---------------------------------------------------------------------------
# B. IngressEventKind constants
# ---------------------------------------------------------------------------


class TestIngressEventKindConstants:
    def test_B01_device_state_snapshot_present(self):
        from galaxy_gateway.protocol.normalized_ingress_event import IngressEventKind
        assert IngressEventKind.DEVICE_STATE_SNAPSHOT == "device_state_snapshot"

    def test_B02_device_execution_event_present(self):
        from galaxy_gateway.protocol.normalized_ingress_event import IngressEventKind
        assert IngressEventKind.DEVICE_EXECUTION_EVENT == "device_execution_event"

    def test_B03_device_state_snapshot_in_ALL(self):
        from galaxy_gateway.protocol.normalized_ingress_event import IngressEventKind
        assert IngressEventKind.DEVICE_STATE_SNAPSHOT in IngressEventKind._ALL

    def test_B04_device_execution_event_in_ALL(self):
        from galaxy_gateway.protocol.normalized_ingress_event import IngressEventKind
        assert IngressEventKind.DEVICE_EXECUTION_EVENT in IngressEventKind._ALL


# ---------------------------------------------------------------------------
# C. IngressEventKind.normalise()
# ---------------------------------------------------------------------------


class TestIngressEventKindNormalise:
    def test_C01_normalise_device_state_snapshot(self):
        from galaxy_gateway.protocol.normalized_ingress_event import IngressEventKind
        result = IngressEventKind.normalise("device_state_snapshot")
        assert result == IngressEventKind.DEVICE_STATE_SNAPSHOT

    def test_C02_normalise_device_execution_event(self):
        from galaxy_gateway.protocol.normalized_ingress_event import IngressEventKind
        result = IngressEventKind.normalise("device_execution_event")
        assert result == IngressEventKind.DEVICE_EXECUTION_EVENT

    def test_C03_normalise_unknown_still_works(self):
        from galaxy_gateway.protocol.normalized_ingress_event import IngressEventKind
        result = IngressEventKind.normalise("definitely_not_a_valid_kind")
        assert result == IngressEventKind.UNKNOWN


# ---------------------------------------------------------------------------
# D. _ANDROID_DOMAIN_KINDS
# ---------------------------------------------------------------------------


class TestAndroidDomainKinds:
    def test_D01_device_state_snapshot_in_domain_kinds(self):
        from galaxy_gateway.websocket_handler import _ANDROID_DOMAIN_KINDS
        from galaxy_gateway.protocol.normalized_ingress_event import IngressEventKind
        assert IngressEventKind.DEVICE_STATE_SNAPSHOT in _ANDROID_DOMAIN_KINDS

    def test_D02_device_execution_event_in_domain_kinds(self):
        from galaxy_gateway.websocket_handler import _ANDROID_DOMAIN_KINDS
        from galaxy_gateway.protocol.normalized_ingress_event import IngressEventKind
        assert IngressEventKind.DEVICE_EXECUTION_EVENT in _ANDROID_DOMAIN_KINDS


# ---------------------------------------------------------------------------
# E. Ingress classifier
# ---------------------------------------------------------------------------


class TestIngressClassifier:
    def test_E01_device_state_snapshot_classified_as_transport(self):
        from galaxy_gateway.protocol.ingress_classifier import (
            classify_ingress_kind,
            IngressMessageClass,
        )
        from galaxy_gateway.protocol.normalized_ingress_event import IngressEventKind
        cls = classify_ingress_kind(IngressEventKind.DEVICE_STATE_SNAPSHOT)
        assert cls == IngressMessageClass.TRANSPORT

    def test_E02_device_execution_event_classified_as_transport(self):
        from galaxy_gateway.protocol.ingress_classifier import (
            classify_ingress_kind,
            IngressMessageClass,
        )
        from galaxy_gateway.protocol.normalized_ingress_event import IngressEventKind
        cls = classify_ingress_kind(IngressEventKind.DEVICE_EXECUTION_EVENT)
        assert cls == IngressMessageClass.TRANSPORT


# ---------------------------------------------------------------------------
# F. android_bridge dispatch table
# ---------------------------------------------------------------------------


class TestAndroidBridgeDispatchTable:
    def test_F01_device_state_snapshot_registered(self):
        from galaxy_gateway.android_bridge import AndroidBridge
        from galaxy_gateway.protocol.aip_v3 import MessageType
        bridge = AndroidBridge()
        assert MessageType.DEVICE_STATE_SNAPSHOT in bridge._message_handlers

    def test_F02_device_execution_event_registered(self):
        from galaxy_gateway.android_bridge import AndroidBridge
        from galaxy_gateway.protocol.aip_v3 import MessageType
        bridge = AndroidBridge()
        assert MessageType.DEVICE_EXECUTION_EVENT in bridge._message_handlers


# ---------------------------------------------------------------------------
# G. handle_device_state_snapshot handler
# ---------------------------------------------------------------------------


class TestHandleDeviceStateSnapshot:
    def test_G01_absorbs_snapshot_and_returns_ack(self):
        from galaxy_gateway.android.handlers.device_state_snapshot import (
            handle_device_state_snapshot,
        )
        from core.android_device_state_store import reset_android_device_state_store

        reset_android_device_state_store()
        try:
            message = {
                "type": "device_state_snapshot",
                "device_id": "test_device_rt_01",
                "message_id": "msg_snap_01",
                "payload": {
                    "model_ready": True,
                    "llama_cpp_available": True,
                    "active_runtime_type": "LLAMA_CPP",
                },
            }
            bridge = MagicMock()
            websocket = MagicMock()
            response = asyncio.run(
                handle_device_state_snapshot(bridge, websocket, message)
            )
            assert response is not None
            assert response.get("type") == "device_state_snapshot_ack"
            assert response.get("status") == "absorbed"
            assert response.get("device_id") == "test_device_rt_01"
            assert response.get("correlation_id") == "msg_snap_01"

            # Verify the snapshot was absorbed into the store
            from core.android_device_state_store import get_device_state_snapshot
            snap = get_device_state_snapshot("test_device_rt_01")
            assert snap is not None
            assert snap.model_ready is True
            assert snap.llama_cpp_available is True
            assert snap.active_runtime_type == "LLAMA_CPP"
        finally:
            reset_android_device_state_store()

    def test_G02_missing_payload_still_absorbs_and_acks(self):
        from galaxy_gateway.android.handlers.device_state_snapshot import (
            handle_device_state_snapshot,
        )
        from core.android_device_state_store import reset_android_device_state_store

        reset_android_device_state_store()
        try:
            message = {
                "type": "device_state_snapshot",
                "device_id": "test_device_rt_02",
                "message_id": "msg_snap_02",
                # no payload key
            }
            bridge = MagicMock()
            websocket = MagicMock()
            response = asyncio.run(
                handle_device_state_snapshot(bridge, websocket, message)
            )
            assert response is not None
            assert response.get("type") == "device_state_snapshot_ack"
        finally:
            reset_android_device_state_store()

    def test_G03_ready_snapshot_with_takeover_gate_advances_lifecycle_to_takeover_eligible(self):
        from galaxy_gateway.android.handlers.device_state_snapshot import (
            handle_device_state_snapshot,
        )
        from core.android_device_state_store import reset_android_device_state_store
        from core.device_lifecycle_state import (
            reset_lifecycle_store,
            get_lifecycle_record,
            transition_device_lifecycle,
            DeviceLifecycleTransitionEvent,
            DeviceLifecycleStage,
        )

        reset_android_device_state_store()
        reset_lifecycle_store()
        try:
            device_id = "test_device_rt_takeover_eligible"
            transition_device_lifecycle(
                device_id,
                DeviceLifecycleTransitionEvent.register_ack_sent,
                websocket_connected=True,
                registration_ack_success=True,
            )
            transition_device_lifecycle(
                device_id,
                DeviceLifecycleTransitionEvent.registration_fully_attached,
                registration_fully_attached=True,
                capability_visible=True,
            )
            message = {
                "type": "device_state_snapshot",
                "device_id": device_id,
                "message_id": "msg_snap_takeover",
                "payload": {
                    "model_ready": True,
                    "accessibility_ready": True,
                    "local_loop_ready": True,
                    "local_loop_config": {"cross_device_enabled": True},
                },
            }
            bridge = MagicMock()
            websocket = MagicMock()
            with patch(
                "core.android_mode_gate_policy.evaluate_android_mode_readiness"
            ) as mock_mode_gate:
                mock_mode_gate.return_value = MagicMock(
                    is_dispatch_eligible=True,
                    is_takeover_eligible=True,
                )
                _ = asyncio.run(handle_device_state_snapshot(bridge, websocket, message))
            record = get_lifecycle_record(device_id)
            assert record.stage == DeviceLifecycleStage.takeover_eligible
            assert record.takeover_eligible is True
        finally:
            reset_android_device_state_store()
            reset_lifecycle_store()


# ---------------------------------------------------------------------------
# H. handle_device_execution_event handler
# ---------------------------------------------------------------------------


class TestHandleDeviceExecutionEvent:
    def test_H01_absorbs_event_and_returns_ack(self):
        from galaxy_gateway.android.handlers.device_state_snapshot import (
            handle_device_execution_event,
        )
        from core.android_device_state_store import reset_android_device_state_store, get_android_device_state_store

        reset_android_device_state_store()
        try:
            message = {
                "type": "device_execution_event",
                "device_id": "test_device_rt_03",
                "message_id": "msg_evt_01",
                "payload": {
                    "flow_id": "flow_abc123",
                    "task_id": "task_xyz456",
                    "phase": "grounding",
                    "step_index": 3,
                    "is_blocking": False,
                },
            }
            bridge = MagicMock()
            websocket = MagicMock()
            response = asyncio.run(
                handle_device_execution_event(bridge, websocket, message)
            )
            assert response is not None
            assert response.get("type") == "device_execution_event_ack"
            assert response.get("status") == "absorbed"
            assert response.get("device_id") == "test_device_rt_03"
            assert response.get("correlation_id") == "msg_evt_01"

            # Verify the event was absorbed into the store
            store = get_android_device_state_store()
            events = store.list_recent_execution_events(device_id="test_device_rt_03")
            assert len(events) >= 1
            assert events[0].flow_id == "flow_abc123"
            assert events[0].phase == "grounding"
            assert events[0].step_index == 3
        finally:
            reset_android_device_state_store()

    def test_H02_execution_event_phases_drive_lifecycle_participating_and_back_to_ready(self):
        from galaxy_gateway.android.handlers.device_state_snapshot import (
            handle_device_execution_event,
        )
        from core.android_device_state_store import reset_android_device_state_store
        from core.device_lifecycle_state import (
            reset_lifecycle_store,
            get_lifecycle_record,
            transition_device_lifecycle,
            DeviceLifecycleTransitionEvent,
            DeviceLifecycleStage,
        )

        reset_android_device_state_store()
        reset_lifecycle_store()
        try:
            device_id = "test_device_rt_execution_lifecycle"
            transition_device_lifecycle(
                device_id,
                DeviceLifecycleTransitionEvent.register_ack_sent,
                websocket_connected=True,
                registration_ack_success=True,
            )
            transition_device_lifecycle(
                device_id,
                DeviceLifecycleTransitionEvent.registration_fully_attached,
                registration_fully_attached=True,
                capability_visible=True,
            )
            transition_device_lifecycle(
                device_id,
                DeviceLifecycleTransitionEvent.readiness_satisfied,
                readiness_satisfied=True,
                dispatch_gate_passed=True,
            )

            bridge = MagicMock()
            websocket = MagicMock()
            start_message = {
                "type": "device_execution_event",
                "device_id": device_id,
                "message_id": "msg_exec_start",
                "payload": {
                    "flow_id": "flow_exec_start",
                    "phase": "grounding",
                },
            }
            _ = asyncio.run(handle_device_execution_event(bridge, websocket, start_message))
            start_record = get_lifecycle_record(device_id)
            assert start_record.stage == DeviceLifecycleStage.participating
            assert start_record.execution_active is True

            end_message = {
                "type": "device_execution_event",
                "device_id": device_id,
                "message_id": "msg_exec_end",
                "payload": {
                    "flow_id": "flow_exec_start",
                    "phase": "completed",
                },
            }
            _ = asyncio.run(handle_device_execution_event(bridge, websocket, end_message))
            end_record = get_lifecycle_record(device_id)
            assert end_record.stage == DeviceLifecycleStage.ready
            assert end_record.execution_active is False
        finally:
            reset_android_device_state_store()
            reset_lifecycle_store()

    def test_H03_unknown_or_empty_phase_does_not_force_execution_end_transition(self):
        from galaxy_gateway.android.handlers.device_state_snapshot import (
            handle_device_execution_event,
        )
        from core.android_device_state_store import reset_android_device_state_store
        from core.device_lifecycle_state import (
            reset_lifecycle_store,
            get_lifecycle_record,
            transition_device_lifecycle,
            DeviceLifecycleTransitionEvent,
            DeviceLifecycleStage,
        )

        reset_android_device_state_store()
        reset_lifecycle_store()
        try:
            device_id = "test_device_rt_execution_unknown_phase"
            transition_device_lifecycle(
                device_id,
                DeviceLifecycleTransitionEvent.register_ack_sent,
                websocket_connected=True,
                registration_ack_success=True,
            )
            transition_device_lifecycle(
                device_id,
                DeviceLifecycleTransitionEvent.registration_fully_attached,
                registration_fully_attached=True,
                capability_visible=True,
            )
            transition_device_lifecycle(
                device_id,
                DeviceLifecycleTransitionEvent.readiness_satisfied,
                readiness_satisfied=True,
                dispatch_gate_passed=True,
            )

            bridge = MagicMock()
            websocket = MagicMock()
            unknown_message = {
                "type": "device_execution_event",
                "device_id": device_id,
                "message_id": "msg_exec_unknown",
                "payload": {"phase": None},
            }
            _ = asyncio.run(handle_device_execution_event(bridge, websocket, unknown_message))
            record_after_unknown = get_lifecycle_record(device_id)
            assert record_after_unknown.stage == DeviceLifecycleStage.ready
            assert record_after_unknown.execution_active is False

            whitespace_message = {
                "type": "device_execution_event",
                "device_id": device_id,
                "message_id": "msg_exec_whitespace",
                "payload": {"phase": "   "},
            }
            _ = asyncio.run(
                handle_device_execution_event(bridge, websocket, whitespace_message)
            )
            record_after_whitespace = get_lifecycle_record(device_id)
            assert record_after_whitespace.stage == DeviceLifecycleStage.ready
            assert record_after_whitespace.execution_active is False
        finally:
            reset_android_device_state_store()
            reset_lifecycle_store()


# ---------------------------------------------------------------------------
# I. OperatorSnapshot android_ecosystem field
# ---------------------------------------------------------------------------


class TestOperatorSnapshotAndroidEcosystem:
    def test_I01_operator_snapshot_has_android_ecosystem_field(self):
        from core.operator_surface import OperatorSnapshot
        snap = OperatorSnapshot()
        assert hasattr(snap, "android_ecosystem")
        assert isinstance(snap.android_ecosystem, dict)

    def test_I02_to_dict_includes_android_ecosystem(self):
        from core.operator_surface import OperatorSnapshot
        snap = OperatorSnapshot()
        d = snap.to_dict()
        assert "android_ecosystem" in d

    def test_I03_android_ecosystem_survives_serialisation_round_trip(self):
        from core.operator_surface import OperatorSnapshot
        snap = OperatorSnapshot()
        snap.android_ecosystem = {"total_devices_with_snapshot": 2, "local_ai_ready_count": 1}
        d = snap.to_dict()
        assert d["android_ecosystem"]["total_devices_with_snapshot"] == 2
        assert d["android_ecosystem"]["local_ai_ready_count"] == 1


# ---------------------------------------------------------------------------
# J. operator_snapshot() populates android_ecosystem
# ---------------------------------------------------------------------------


class TestOperatorSnapshotPopulatesAndroidEcosystem:
    def test_J01_android_ecosystem_populated_when_store_has_snapshot(self):
        from core.operator_surface import get_operator_surface
        from core.android_device_state_store import (
            absorb_device_state_snapshot,
            reset_android_device_state_store,
        )

        reset_android_device_state_store()
        try:
            absorb_device_state_snapshot("eco_device_01", {
                "model_ready": True,
                "llama_cpp_available": True,
                "local_loop_ready": True,
            })
            surface = get_operator_surface()
            snap = surface.operator_snapshot()
            eco = snap.android_ecosystem
            assert isinstance(eco, dict)
            assert eco.get("total_devices_with_snapshot", 0) >= 1
        finally:
            reset_android_device_state_store()


# ---------------------------------------------------------------------------
# K. /api/v1/operator/devices/execution-events route exists
# ---------------------------------------------------------------------------


class TestExecutionEventsRoute:
    def test_K01_route_registered_in_operator_router(self):
        from core.routes.operator import create_router
        router = create_router()
        paths = [r.path for r in router.routes]
        assert "/api/v1/operator/devices/execution-events" in paths

    def test_K02_route_is_get_method(self):
        from core.routes.operator import create_router
        router = create_router()
        for r in router.routes:
            if hasattr(r, "path") and r.path == "/api/v1/operator/devices/execution-events":
                assert "GET" in r.methods
                break
        else:
            pytest.fail("Route /api/v1/operator/devices/execution-events not found")
