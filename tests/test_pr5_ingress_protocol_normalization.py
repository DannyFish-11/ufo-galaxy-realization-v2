"""tests/test_pr5_ingress_protocol_normalization.py
===================================================
PR-5 — Normalize canonical ingress protocol handling to AIP v3 and stable
message classes.

Coverage
--------
Authority sentinels
 1.  INGRESS_CLASSIFIER_AUTHORITY importable from ingress_classifier module.
 2.  INGRESS_CLASSIFIER_AUTHORITY starts with "INGRESS_CLASSIFIER::".
 3.  INGRESS_NORMALIZATION_AUTHORITY importable from websocket_handler.
 4.  INGRESS_NORMALIZATION_AUTHORITY starts with "WEBSOCKET_HANDLER::INGRESS_NORMALIZED".

IngressMessageClass semantic categories
 5.  IngressMessageClass.PRESENCE == "presence".
 6.  IngressMessageClass.CONTROL == "control".
 7.  IngressMessageClass.EXECUTION == "execution".
 8.  IngressMessageClass.TRANSPORT == "transport".
 9.  IngressMessageClass.UNKNOWN == "unknown".
10.  IngressMessageClass importable from galaxy_gateway.protocol.

classify_ingress_kind function
11.  device_register → presence.
12.  heartbeat → presence.
13.  device_status → presence.
14.  device_unregister → presence.
15.  command → control.
16.  task_submit → control.
17.  task_cancel → control.
18.  goal_execution → control.
19.  parallel_subtask → control.
20.  task_result → execution.
21.  command_result → execution.
22.  parallel_result → execution.
23.  wake_event → transport.
24.  capability_report → transport.
25.  unknown → unknown.
26.  unrecognised string → unknown.
27.  empty string → unknown.
28.  classify_ingress_kind importable from galaxy_gateway.protocol.

Normalization wiring in websocket_handler
29.  websocket_handler imports IngressEventKind.
30.  websocket_handler imports NormalizedIngressEvent (from_aip_message).
31.  websocket_handler imports classify_ingress_kind.
32.  INGRESS_NORMALIZATION_AUTHORITY is non-empty.

Normalization wiring in transport/websocket_server
33.  transport.websocket_server imports to_normalized_ingress_event.
34.  transport.websocket_server imports IngressEventKind.
35.  transport.websocket_server imports NormalizedIngressEvent.

Classifier covers all IngressEventKind constants
36.  All known IngressEventKind values except UNKNOWN map to a non-unknown class.

Protocol package re-exports
37.  IngressMessageClass importable from galaxy_gateway.protocol.
38.  classify_ingress_kind importable from galaxy_gateway.protocol.
39.  INGRESS_CLASSIFIER_AUTHORITY importable from galaxy_gateway.protocol.

Correlation field consistency via NormalizedIngressEvent
40.  from_aip_message always returns non-empty trace_id.
41.  from_aip_message always returns non-empty route_mode.
42.  from_aip_message preserves device_id.
43.  from_aip_message preserves message_id.
44.  from_aip_message sets correlation_id from aip_msg.correlation_id.
45.  from_normalized_dict always returns non-empty trace_id.
46.  from_normalized_dict always returns non-empty route_mode.

End-to-end: to_normalized_ingress_event produces correct kind for v3 messages
47.  v3 device_register dict → kind="device_register", class="presence".
48.  v3 task_submit dict → kind="task_submit", class="control".
49.  v3 task_result dict → kind="task_result", class="execution".
50.  v3 heartbeat dict → kind="heartbeat", class="presence".
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_aip_v3_dict(msg_type: str, device_id: str = "dev_001", **kw) -> dict:
    return {
        "version": "3.0",
        "type": msg_type,
        "device_id": device_id,
        "message_id": "msg_abc",
        "trace_id": "trace_xyz",
        "route_mode": "cross_device",
        "payload": {},
        **kw,
    }


def _make_aip_msg(msg_type_str: str, device_id: str = "dev_001") -> Any:
    """Return a minimal AIPMessage-like object for adapter tests."""
    from galaxy_gateway.protocol.aip_v3 import AIPMessage, MessageType
    aip_type = MessageType(msg_type_str)
    return AIPMessage(
        type=aip_type,
        device_id=device_id,
        message_id="msg_xyz",
        trace_id="trace_aaa",
        route_mode="cross_device",
        payload={"foo": "bar"},
    )


# ---------------------------------------------------------------------------
# 1–4: Authority sentinels
# ---------------------------------------------------------------------------

class TestAuthoritySentinels:
    def test_ingress_classifier_authority_importable(self):
        from galaxy_gateway.protocol.ingress_classifier import INGRESS_CLASSIFIER_AUTHORITY
        assert INGRESS_CLASSIFIER_AUTHORITY

    def test_ingress_classifier_authority_prefix(self):
        from galaxy_gateway.protocol.ingress_classifier import INGRESS_CLASSIFIER_AUTHORITY
        assert INGRESS_CLASSIFIER_AUTHORITY.startswith("INGRESS_CLASSIFIER::")

    def test_ingress_normalization_authority_importable(self):
        from galaxy_gateway.websocket_handler import INGRESS_NORMALIZATION_AUTHORITY
        assert INGRESS_NORMALIZATION_AUTHORITY

    def test_ingress_normalization_authority_prefix(self):
        from galaxy_gateway.websocket_handler import INGRESS_NORMALIZATION_AUTHORITY
        assert INGRESS_NORMALIZATION_AUTHORITY.startswith(
            "WEBSOCKET_HANDLER::INGRESS_NORMALIZED"
        )


# ---------------------------------------------------------------------------
# 5–10: IngressMessageClass semantic categories
# ---------------------------------------------------------------------------

class TestIngressMessageClass:
    def test_presence_value(self):
        from galaxy_gateway.protocol.ingress_classifier import IngressMessageClass
        assert IngressMessageClass.PRESENCE == "presence"

    def test_control_value(self):
        from galaxy_gateway.protocol.ingress_classifier import IngressMessageClass
        assert IngressMessageClass.CONTROL == "control"

    def test_execution_value(self):
        from galaxy_gateway.protocol.ingress_classifier import IngressMessageClass
        assert IngressMessageClass.EXECUTION == "execution"

    def test_transport_value(self):
        from galaxy_gateway.protocol.ingress_classifier import IngressMessageClass
        assert IngressMessageClass.TRANSPORT == "transport"

    def test_unknown_value(self):
        from galaxy_gateway.protocol.ingress_classifier import IngressMessageClass
        assert IngressMessageClass.UNKNOWN == "unknown"

    def test_importable_from_protocol_package(self):
        from galaxy_gateway.protocol import IngressMessageClass
        assert IngressMessageClass.PRESENCE == "presence"


# ---------------------------------------------------------------------------
# 11–28: classify_ingress_kind
# ---------------------------------------------------------------------------

class TestClassifyIngressKind:
    @pytest.fixture(autouse=True)
    def _imports(self):
        from galaxy_gateway.protocol.ingress_classifier import (
            classify_ingress_kind,
            IngressMessageClass,
        )
        self.classify = classify_ingress_kind
        self.C = IngressMessageClass

    def test_device_register_presence(self):
        assert self.classify("device_register") == self.C.PRESENCE

    def test_heartbeat_presence(self):
        assert self.classify("heartbeat") == self.C.PRESENCE

    def test_device_status_presence(self):
        assert self.classify("device_status") == self.C.PRESENCE

    def test_device_unregister_presence(self):
        assert self.classify("device_unregister") == self.C.PRESENCE

    def test_command_control(self):
        assert self.classify("command") == self.C.CONTROL

    def test_task_submit_control(self):
        assert self.classify("task_submit") == self.C.CONTROL

    def test_task_cancel_control(self):
        assert self.classify("task_cancel") == self.C.CONTROL

    def test_goal_execution_control(self):
        assert self.classify("goal_execution") == self.C.CONTROL

    def test_parallel_subtask_control(self):
        assert self.classify("parallel_subtask") == self.C.CONTROL

    def test_task_result_execution(self):
        assert self.classify("task_result") == self.C.EXECUTION

    def test_command_result_execution(self):
        assert self.classify("command_result") == self.C.EXECUTION

    def test_parallel_result_execution(self):
        assert self.classify("parallel_result") == self.C.EXECUTION

    def test_wake_event_transport(self):
        assert self.classify("wake_event") == self.C.TRANSPORT

    def test_capability_report_transport(self):
        assert self.classify("capability_report") == self.C.TRANSPORT

    def test_unknown_unknown(self):
        assert self.classify("unknown") == self.C.UNKNOWN

    def test_unrecognised_unknown(self):
        assert self.classify("some_future_type_xyz") == self.C.UNKNOWN

    def test_empty_string_unknown(self):
        assert self.classify("") == self.C.UNKNOWN

    def test_importable_from_protocol_package(self):
        from galaxy_gateway.protocol import classify_ingress_kind
        assert classify_ingress_kind("device_register") == "presence"


# ---------------------------------------------------------------------------
# 29–35: Normalization wiring checks
# ---------------------------------------------------------------------------

class TestNormalizationWiring:
    def test_websocket_handler_imports_ingress_event_kind(self):
        import galaxy_gateway.websocket_handler as wh
        assert hasattr(wh, "IngressEventKind")

    def test_websocket_handler_imports_ingress_event_from_aip(self):
        import galaxy_gateway.websocket_handler as wh
        assert hasattr(wh, "_ingress_event_from_aip")

    def test_websocket_handler_imports_classify(self):
        import galaxy_gateway.websocket_handler as wh
        assert hasattr(wh, "classify_ingress_kind")

    def test_ingress_normalization_authority_non_empty(self):
        from galaxy_gateway.websocket_handler import INGRESS_NORMALIZATION_AUTHORITY
        assert len(INGRESS_NORMALIZATION_AUTHORITY) > 0

    def test_transport_ws_imports_to_normalized(self):
        import galaxy_gateway.transport.websocket_server as ws
        assert hasattr(ws, "to_normalized_ingress_event")

    def test_transport_ws_imports_ingress_event_kind(self):
        import galaxy_gateway.transport.websocket_server as ws
        assert hasattr(ws, "IngressEventKind")

    def test_transport_ws_imports_normalized_ingress_event(self):
        import galaxy_gateway.transport.websocket_server as ws
        assert hasattr(ws, "NormalizedIngressEvent")


# ---------------------------------------------------------------------------
# 36: Classifier covers all IngressEventKind constants (except UNKNOWN)
# ---------------------------------------------------------------------------

class TestClassifierCoversAllKinds:
    def test_all_known_kinds_have_non_unknown_class(self):
        from galaxy_gateway.protocol.normalized_ingress_event import IngressEventKind
        from galaxy_gateway.protocol.ingress_classifier import (
            classify_ingress_kind,
            IngressMessageClass,
        )
        # All canonical kinds except UNKNOWN itself should map to a real class
        known_kinds = [
            v for k, v in vars(IngressEventKind).items()
            if not k.startswith("_") and isinstance(v, str) and v != IngressEventKind.UNKNOWN
        ]
        assert len(known_kinds) > 0
        for kind in known_kinds:
            cls = classify_ingress_kind(kind)
            assert cls != IngressMessageClass.UNKNOWN, (
                f"IngressEventKind.{kind!r} mapped to UNKNOWN — add it to "
                "_KIND_TO_CLASS in ingress_classifier.py"
            )


# ---------------------------------------------------------------------------
# 37–39: Protocol package re-exports
# ---------------------------------------------------------------------------

class TestProtocolPackageReExports:
    def test_ingress_message_class_importable(self):
        from galaxy_gateway.protocol import IngressMessageClass
        assert IngressMessageClass

    def test_classify_ingress_kind_importable(self):
        from galaxy_gateway.protocol import classify_ingress_kind
        assert callable(classify_ingress_kind)

    def test_ingress_classifier_authority_importable(self):
        from galaxy_gateway.protocol import INGRESS_CLASSIFIER_AUTHORITY
        assert INGRESS_CLASSIFIER_AUTHORITY


# ---------------------------------------------------------------------------
# 40–46: Correlation field consistency
# ---------------------------------------------------------------------------

class TestCorrelationFieldConsistency:
    def test_from_aip_message_trace_id_never_empty(self):
        from galaxy_gateway.protocol.normalized_ingress_event import from_aip_message
        msg = _make_aip_msg("device_register")
        event = from_aip_message(msg)
        assert event.trace_id

    def test_from_aip_message_route_mode_never_empty(self):
        from galaxy_gateway.protocol.normalized_ingress_event import from_aip_message
        msg = _make_aip_msg("device_register")
        event = from_aip_message(msg)
        assert event.route_mode

    def test_from_aip_message_preserves_device_id(self):
        from galaxy_gateway.protocol.normalized_ingress_event import from_aip_message
        msg = _make_aip_msg("device_register", device_id="dev_abc")
        event = from_aip_message(msg)
        assert event.device_id == "dev_abc"

    def test_from_aip_message_preserves_message_id(self):
        from galaxy_gateway.protocol.normalized_ingress_event import from_aip_message
        msg = _make_aip_msg("device_register")
        event = from_aip_message(msg)
        assert event.message_id == "msg_xyz"

    def test_from_aip_message_correlation_id(self):
        from galaxy_gateway.protocol.aip_v3 import AIPMessage, MessageType
        aip_msg = AIPMessage(
            type=MessageType.TASK_RESULT,
            device_id="dev_001",
            message_id="msg_resp",
            correlation_id="corr_123",
        )
        from galaxy_gateway.protocol.normalized_ingress_event import from_aip_message
        event = from_aip_message(aip_msg)
        assert event.correlation_id == "corr_123"

    def test_from_normalized_dict_trace_id_never_empty(self):
        from galaxy_gateway.protocol.normalized_ingress_event import from_normalized_dict
        d = _make_aip_v3_dict("task_submit")
        event = from_normalized_dict(d)
        assert event.trace_id

    def test_from_normalized_dict_route_mode_never_empty(self):
        from galaxy_gateway.protocol.normalized_ingress_event import from_normalized_dict
        d = _make_aip_v3_dict("task_submit")
        d.pop("route_mode", None)
        event = from_normalized_dict(d)
        assert event.route_mode  # should default to "cross_device"


# ---------------------------------------------------------------------------
# SESSION_MIGRATE backward-compat fallback (MessageType-level check)
# ---------------------------------------------------------------------------

class TestSessionMigrateFallback:
    """Verify that SESSION_MIGRATE is still dispatched correctly via the
    MessageType fallback path even though it is not yet a named IngressEventKind.
    """

    def test_session_migrate_not_in_ingress_event_kind(self):
        """session_migrate is a MessageType but not yet in IngressEventKind —
        so it produces kind='unknown' after normalization."""
        from galaxy_gateway.protocol.normalized_ingress_event import to_normalized_ingress_event
        d = {
            "version": "3.0",
            "type": "session_migrate",
            "device_id": "dev_001",
            "trace_id": "trace_sm",
            "route_mode": "cross_device",
            "payload": {"session_id": "sess_abc"},
        }
        import json
        event = to_normalized_ingress_event(json.dumps(d))
        # session_migrate is not a declared IngressEventKind, so kind is 'unknown'
        assert event.kind == "unknown"

    def test_session_migrate_kind_unknown_class_unknown(self):
        """classify_ingress_kind('unknown') → 'unknown' — the fallback path."""
        from galaxy_gateway.protocol.ingress_classifier import classify_ingress_kind
        assert classify_ingress_kind("unknown") == "unknown"

    def test_websocket_handler_has_session_migrate_fallback(self):
        """websocket_handler still references MessageType.SESSION_MIGRATE to
        preserve backward compatibility for this transport-class event."""
        import inspect
        import galaxy_gateway.websocket_handler as wh
        src = inspect.getsource(wh.handle_message)
        assert "SESSION_MIGRATE" in src, (
            "handle_message must retain SESSION_MIGRATE fallback path for "
            "backward compatibility"
        )


class TestEndToEndNormalization:
    def test_device_register_kind_and_class(self):
        from galaxy_gateway.protocol.normalized_ingress_event import to_normalized_ingress_event
        from galaxy_gateway.protocol.ingress_classifier import classify_ingress_kind
        d = _make_aip_v3_dict("device_register")
        event = to_normalized_ingress_event(json.dumps(d))
        assert event.kind == "device_register"
        assert classify_ingress_kind(event.kind) == "presence"

    def test_task_submit_kind_and_class(self):
        from galaxy_gateway.protocol.normalized_ingress_event import to_normalized_ingress_event
        from galaxy_gateway.protocol.ingress_classifier import classify_ingress_kind
        d = _make_aip_v3_dict("task_submit")
        event = to_normalized_ingress_event(json.dumps(d))
        assert event.kind == "task_submit"
        assert classify_ingress_kind(event.kind) == "control"

    def test_task_result_kind_and_class(self):
        from galaxy_gateway.protocol.normalized_ingress_event import to_normalized_ingress_event
        from galaxy_gateway.protocol.ingress_classifier import classify_ingress_kind
        d = _make_aip_v3_dict("task_result")
        event = to_normalized_ingress_event(json.dumps(d))
        assert event.kind == "task_result"
        assert classify_ingress_kind(event.kind) == "execution"

    def test_heartbeat_kind_and_class(self):
        from galaxy_gateway.protocol.normalized_ingress_event import to_normalized_ingress_event
        from galaxy_gateway.protocol.ingress_classifier import classify_ingress_kind
        d = _make_aip_v3_dict("heartbeat")
        event = to_normalized_ingress_event(json.dumps(d))
        assert event.kind == "heartbeat"
        assert classify_ingress_kind(event.kind) == "presence"
