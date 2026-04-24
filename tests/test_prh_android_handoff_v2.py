"""tests/test_prh_android_handoff_v2.py
=========================================
PR-H (V2 配套): Tests for Android-native HandoffEnvelopeV2 build path,
contract mapping, ACK/result/failure response contract, and correlation /
routing identity round-trip.

This is the **V2 companion PR** for PR-H.  Android repo is the key
implementation repo (native consumption path); this file validates the
upstream protocol support that V2 must provide.

Coverage groups
---------------
A.  Sentinel / policy constants are importable from new modules.
B.  MessageType enum — HANDOFF_DISPATCH / HANDOFF_ACK / HANDOFF_RESULT /
    HANDOFF_FAILURE are present.
C.  HandoffEnvelopeV2.to_android_native_payload — field presence and values.
D.  HandoffEnvelopeV2.to_android_native_payload — correlation identity
    fields preserved (handoff_id, trace_id, task_id, session_id).
E.  HandoffEnvelopeV2.to_android_native_payload — routing fields preserved
    (source/target device_id, runtime_id, posture, coordination_role).
F.  HandoffEnvelopeV2.to_android_native_payload — execution hints preserved
    (capability, exec_mode, route_mode, callback_channel).
G.  HandoffEnvelopeV2.to_android_native_payload — nested task spec flattened
    into handoff_task.
H.  HandoffEnvelopeV2.to_android_native_payload — return_contract embedded.
I.  HandoffEnvelopeV2.to_android_native_payload — schema_version is "v2".
J.  HandoffEnvelopeV2.to_android_native_payload — JSON serialisable.
K.  HandoffEnvelopeV2.to_android_task_assign_payload — message frame fields.
L.  HandoffEnvelopeV2.to_android_task_assign_payload — payload contains
    android native payload.
M.  HandoffEnvelopeV2.to_android_task_assign_payload — handoff_id at top level.
N.  MessageBuilder.handoff_dispatch — delegates to envelope method.
O.  MessageBuilder.handoff_dispatch — correct message type.
P.  HandoffResponseKind — all expected enum values present.
Q.  HandoffResponseKind.from_string — known values round-trip.
R.  HandoffResponseKind.from_string — unknown values → HandoffResponseKind.unknown.
S.  AndroidHandoffResponseEnvelope — default field values.
T.  AndroidHandoffResponseEnvelope — to_dict / from_dict round-trip.
U.  AndroidHandoffResponseEnvelope — to_json / from_dict round-trip.
V.  AndroidHandoffResponseEnvelope.is_terminal — ack is not terminal.
W.  AndroidHandoffResponseEnvelope.is_terminal — result / failure / timeout /
    cancelled are terminal.
X.  from_android_ack_message — builds correct ack envelope.
Y.  from_android_result_message — builds correct result envelope.
Z.  from_android_failure_message — builds correct failure envelope.
AA. from_android_failure_message — maps handoff_failure type correctly.
AB. extract_handoff_response_envelope — dispatches by message type.
AC. extract_handoff_response_envelope — dispatches by response_kind in payload.
AD. extract_handoff_response_envelope — unknown type → HandoffResponseKind.unknown.
AE. extract_handoff_response_envelope — identity fields extracted from payload.
AF. HandoffV2ResponseRuntime — register / resolve by handoff_id.
AG. HandoffV2ResponseRuntime — resolve by task_id fallback.
AH. HandoffV2ResponseRuntime — terminal resolve clears entry.
AI. HandoffV2ResponseRuntime — ack resolve does NOT clear entry.
AJ. HandoffV2ResponseRuntime — resolve returns None for unknown handoff_id.
AK. HandoffV2ResponseOutcome — dataclass fields.
AL. ingest_android_handoff_response — ack is correlated and callback invoked.
AM. ingest_android_handoff_response — result is correlated, terminal, clears entry.
AN. ingest_android_handoff_response — failure is correlated, terminal.
AO. ingest_android_handoff_response — no pending entry → was_correlated=False.
AP. ingest_android_handoff_response — unknown kind → was_correlated=False.
AQ. ingest_android_handoff_response — exception in callback is non-fatal.
AR. ingest_android_handoff_response — broken message → was_correlated=False.
AS. Full correlation round-trip: build envelope → dispatch → ack → result.
AT. Backward compat: build_handoff_envelope_v2 result passes to_android_native_payload.
AU. Backward compat: from_legacy_handoff_contract result passes to_android_native_payload.
AV. Contract mapping: handoff_id is unique per envelope.
AW. Contract mapping: task_id=None still produces valid android payload.
AX. Correlation: handoff_id survives to_android_task_assign_payload → extract.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

import pytest


# ============================================================================
# A. Sentinel / policy importability
# ============================================================================

class TestSentinels:

    def test_A01_contract_sentinel_importable(self):
        from contracts.android_handoff_response import (
            ANDROID_HANDOFF_RESPONSE_CONTRACT_PR_H_SENTINEL,
        )
        assert ANDROID_HANDOFF_RESPONSE_CONTRACT_PR_H_SENTINEL != ""

    def test_A02_ingress_sentinel_importable(self):
        from core.android_handoff_v2_response_ingress import (
            ANDROID_HANDOFF_V2_RESPONSE_INGRESS_PR_H_SENTINEL,
        )
        assert ANDROID_HANDOFF_V2_RESPONSE_INGRESS_PR_H_SENTINEL != ""

    def test_A03_policy_sentinels_importable(self):
        from contracts.android_handoff_response import (
            HANDOFF_ID_IS_PRIMARY_CORRELATION_KEY_POLICY,
            RESPONSE_KIND_MUST_BE_EXPLICIT_POLICY,
            ACK_DOES_NOT_REQUIRE_RESULT_PAYLOAD_POLICY,
            FAILURE_MUST_CARRY_ERROR_DETAIL_POLICY,
            HANDOFF_RESPONSE_IS_CORRELATED_BY_HANDOFF_ID_THEN_TASK_ID_POLICY,
        )
        for s in [
            HANDOFF_ID_IS_PRIMARY_CORRELATION_KEY_POLICY,
            RESPONSE_KIND_MUST_BE_EXPLICIT_POLICY,
            ACK_DOES_NOT_REQUIRE_RESULT_PAYLOAD_POLICY,
            FAILURE_MUST_CARRY_ERROR_DETAIL_POLICY,
            HANDOFF_RESPONSE_IS_CORRELATED_BY_HANDOFF_ID_THEN_TASK_ID_POLICY,
        ]:
            assert s != ""

    def test_A04_ingress_policy_sentinels_importable(self):
        from core.android_handoff_v2_response_ingress import (
            HANDOFF_ID_CORRELATION_IS_PRIMARY_POLICY,
            SINGLE_INGRESS_PATH_POLICY,
            NON_DESTRUCTIVE_ON_MISS_POLICY,
            TERMINAL_RESPONSE_CLEARS_PENDING_POLICY,
            ACK_DOES_NOT_CLEAR_PENDING_POLICY,
        )
        for s in [
            HANDOFF_ID_CORRELATION_IS_PRIMARY_POLICY,
            SINGLE_INGRESS_PATH_POLICY,
            NON_DESTRUCTIVE_ON_MISS_POLICY,
            TERMINAL_RESPONSE_CLEARS_PENDING_POLICY,
            ACK_DOES_NOT_CLEAR_PENDING_POLICY,
        ]:
            assert s != ""


# ============================================================================
# B. MessageType enum
# ============================================================================

class TestMessageTypeEnum:

    def test_B01_handoff_dispatch_present(self):
        from galaxy_gateway.protocol.aip_v3 import MessageType
        assert MessageType.HANDOFF_DISPATCH.value == "handoff_dispatch"

    def test_B02_handoff_ack_present(self):
        from galaxy_gateway.protocol.aip_v3 import MessageType
        assert MessageType.HANDOFF_ACK.value == "handoff_ack"

    def test_B03_handoff_result_present(self):
        from galaxy_gateway.protocol.aip_v3 import MessageType
        assert MessageType.HANDOFF_RESULT.value == "handoff_result"

    def test_B04_handoff_failure_present(self):
        from galaxy_gateway.protocol.aip_v3 import MessageType
        assert MessageType.HANDOFF_FAILURE.value == "handoff_failure"

    def test_B05_handoff_envelope_v2_canonical_downlink(self):
        """HANDOFF_ENVELOPE_V2 is the canonical downlink wire type (Android-aligned)."""
        from galaxy_gateway.protocol.aip_v3 import MessageType
        assert MessageType.HANDOFF_ENVELOPE_V2.value == "handoff_envelope_v2"

    def test_B06_handoff_envelope_v2_result_canonical_uplink(self):
        """HANDOFF_ENVELOPE_V2_RESULT is the canonical uplink wire type (Android-aligned)."""
        from galaxy_gateway.protocol.aip_v3 import MessageType
        assert MessageType.HANDOFF_ENVELOPE_V2_RESULT.value == "handoff_envelope_v2_result"


# ============================================================================
# C–J. HandoffEnvelopeV2.to_android_native_payload
# ============================================================================

class TestToAndroidNativePayload:

    def _make_envelope(self, **kwargs):
        from contracts.handoff_envelope_v2 import build_handoff_envelope_v2
        defaults = dict(
            trace_id="trace_001",
            task={
                "tool_name": "take_screenshot",
                "args": {"quality": "high"},
            },
            capability="screen",
            source_device_id="phone_001",
            target_device_id="tablet_002",
            session_id="sess_abc",
        )
        defaults.update(kwargs)
        return build_handoff_envelope_v2(**defaults)

    def test_C01_method_exists(self):
        env = self._make_envelope()
        assert hasattr(env, "to_android_native_payload")

    def test_C02_returns_dict(self):
        env = self._make_envelope()
        payload = env.to_android_native_payload()
        assert isinstance(payload, dict)

    def test_D01_handoff_id_preserved(self):
        env = self._make_envelope()
        payload = env.to_android_native_payload()
        assert payload["handoff_id"] == env.handoff_id

    def test_D02_trace_id_preserved(self):
        env = self._make_envelope()
        payload = env.to_android_native_payload()
        assert payload["trace_id"] == "trace_001"

    def test_D03_session_id_preserved(self):
        env = self._make_envelope()
        payload = env.to_android_native_payload()
        assert payload["session_id"] == "sess_abc"

    def test_D04_task_id_preserved_when_set(self):
        from contracts.handoff_envelope_v2 import build_handoff_envelope_v2
        env = build_handoff_envelope_v2(
            trace_id="t",
            task={},
            task_id="task_xyz",
        )
        payload = env.to_android_native_payload()
        assert payload["task_id"] == "task_xyz"

    def test_E01_source_device_id_preserved(self):
        env = self._make_envelope()
        payload = env.to_android_native_payload()
        assert payload["source_device_id"] == "phone_001"

    def test_E02_target_device_id_preserved(self):
        env = self._make_envelope()
        payload = env.to_android_native_payload()
        assert payload["target_device_id"] == "tablet_002"

    def test_E03_source_runtime_posture_preserved(self):
        from contracts.handoff_envelope_v2 import build_handoff_envelope_v2
        env = build_handoff_envelope_v2(
            trace_id="t",
            task={},
            source_runtime_posture="join_runtime",
        )
        payload = env.to_android_native_payload()
        assert payload["source_runtime_posture"] == "join_runtime"

    def test_E04_coordination_role_preserved(self):
        from contracts.handoff_envelope_v2 import build_handoff_envelope_v2
        env = build_handoff_envelope_v2(
            trace_id="t",
            task={},
            coordination_role="source_controller",
        )
        payload = env.to_android_native_payload()
        assert payload["coordination_role"] == "source_controller"

    def test_F01_capability_preserved(self):
        env = self._make_envelope()
        payload = env.to_android_native_payload()
        assert payload["capability"] == "screen"

    def test_F02_exec_mode_preserved(self):
        from contracts.handoff_envelope_v2 import build_handoff_envelope_v2
        env = build_handoff_envelope_v2(trace_id="t", task={}, exec_mode="remote")
        payload = env.to_android_native_payload()
        assert payload["exec_mode"] == "remote"

    def test_F03_route_mode_preserved(self):
        from contracts.handoff_envelope_v2 import build_handoff_envelope_v2
        env = build_handoff_envelope_v2(trace_id="t", task={}, route_mode="broadcast")
        payload = env.to_android_native_payload()
        assert payload["route_mode"] == "broadcast"

    def test_F04_callback_channel_preserved(self):
        from contracts.handoff_envelope_v2 import build_handoff_envelope_v2
        env = build_handoff_envelope_v2(trace_id="t", task={}, callback_channel="http")
        payload = env.to_android_native_payload()
        assert payload["callback_channel"] == "http"

    def test_G01_task_spec_flattened_into_handoff_task(self):
        env = self._make_envelope()
        payload = env.to_android_native_payload()
        assert "handoff_task" in payload
        assert isinstance(payload["handoff_task"], dict)

    def test_G02_handoff_task_contains_tool_name(self):
        env = self._make_envelope(task={"tool_name": "take_screenshot"})
        payload = env.to_android_native_payload()
        assert payload["handoff_task"].get("tool_name") == "take_screenshot"

    def test_H01_return_contract_embedded(self):
        env = self._make_envelope()
        payload = env.to_android_native_payload()
        assert "return_contract" in payload
        assert isinstance(payload["return_contract"], dict)

    def test_I01_schema_version_is_v2(self):
        env = self._make_envelope()
        payload = env.to_android_native_payload()
        assert payload["schema_version"] == "v2"

    def test_J01_json_serialisable(self):
        env = self._make_envelope()
        payload = env.to_android_native_payload()
        serialised = json.dumps(payload, default=str)
        recovered = json.loads(serialised)
        assert recovered["handoff_id"] == env.handoff_id


# ============================================================================
# K–M. HandoffEnvelopeV2.to_android_task_assign_payload
# ============================================================================

class TestToAndroidTaskAssignPayload:

    def _make_envelope(self):
        from contracts.handoff_envelope_v2 import build_handoff_envelope_v2
        return build_handoff_envelope_v2(
            trace_id="trace_k",
            task={"tool_name": "open_app"},
            capability="screen",
            source_device_id="phone_k",
            target_device_id="tablet_k",
        )

    def test_K01_method_exists(self):
        env = self._make_envelope()
        assert hasattr(env, "to_android_task_assign_payload")

    def test_K02_returns_dict(self):
        env = self._make_envelope()
        msg = env.to_android_task_assign_payload("tablet_k")
        assert isinstance(msg, dict)

    def test_K03_version_3_0(self):
        env = self._make_envelope()
        msg = env.to_android_task_assign_payload("tablet_k")
        assert msg["version"] == "3.0"

    def test_K04_type_is_handoff_envelope_v2(self):
        env = self._make_envelope()
        msg = env.to_android_task_assign_payload("tablet_k")
        assert msg["type"] == "handoff_envelope_v2"

    def test_K05_device_id_set(self):
        env = self._make_envelope()
        msg = env.to_android_task_assign_payload("tablet_k")
        assert msg["device_id"] == "tablet_k"

    def test_K06_message_id_present(self):
        env = self._make_envelope()
        msg = env.to_android_task_assign_payload("tablet_k")
        assert msg["message_id"]

    def test_K07_timestamp_present(self):
        env = self._make_envelope()
        msg = env.to_android_task_assign_payload("tablet_k")
        assert msg["timestamp"] > 0

    def test_L01_payload_contains_android_native_payload(self):
        env = self._make_envelope()
        msg = env.to_android_task_assign_payload("tablet_k")
        assert "payload" in msg
        payload = msg["payload"]
        assert payload["handoff_id"] == env.handoff_id

    def test_L02_payload_contains_handoff_task(self):
        env = self._make_envelope()
        msg = env.to_android_task_assign_payload("tablet_k")
        assert "handoff_task" in msg["payload"]

    def test_M01_handoff_id_at_top_level(self):
        env = self._make_envelope()
        msg = env.to_android_task_assign_payload("tablet_k")
        assert msg["handoff_id"] == env.handoff_id

    def test_M02_trace_id_at_top_level(self):
        env = self._make_envelope()
        msg = env.to_android_task_assign_payload("tablet_k")
        assert msg["trace_id"] == "trace_k"


# ============================================================================
# N–O. MessageBuilder.handoff_dispatch
# ============================================================================

class TestMessageBuilderHandoffDispatch:

    def _make_envelope(self):
        from contracts.handoff_envelope_v2 import build_handoff_envelope_v2
        return build_handoff_envelope_v2(
            trace_id="trace_n",
            task={"tool_name": "screenshot"},
            source_device_id="phone_n",
            target_device_id="tablet_n",
        )

    def test_N01_method_exists(self):
        from galaxy_gateway.android.message_builder import MessageBuilder
        assert hasattr(MessageBuilder, "handoff_dispatch")

    def test_N02_delegates_to_envelope(self):
        from galaxy_gateway.android.message_builder import MessageBuilder
        env = self._make_envelope()
        msg = MessageBuilder.handoff_dispatch("tablet_n", env)
        assert msg["handoff_id"] == env.handoff_id

    def test_O01_message_type_is_handoff_envelope_v2(self):
        from galaxy_gateway.android.message_builder import MessageBuilder
        env = self._make_envelope()
        msg = MessageBuilder.handoff_dispatch("tablet_n", env)
        assert msg["type"] == "handoff_envelope_v2"

    def test_O02_default_priority_5(self):
        from galaxy_gateway.android.message_builder import MessageBuilder
        env = self._make_envelope()
        msg = MessageBuilder.handoff_dispatch("tablet_n", env)
        assert msg["priority"] == 5

    def test_O03_priority_override(self):
        from galaxy_gateway.android.message_builder import MessageBuilder
        env = self._make_envelope()
        msg = MessageBuilder.handoff_dispatch("tablet_n", env, priority=9)
        assert msg["priority"] == 9


# ============================================================================
# P–R. HandoffResponseKind
# ============================================================================

class TestHandoffResponseKind:

    def test_P01_ack_present(self):
        from contracts.android_handoff_response import HandoffResponseKind
        assert HandoffResponseKind.ack.value == "ack"

    def test_P02_result_present(self):
        from contracts.android_handoff_response import HandoffResponseKind
        assert HandoffResponseKind.result.value == "result"

    def test_P03_failure_present(self):
        from contracts.android_handoff_response import HandoffResponseKind
        assert HandoffResponseKind.failure.value == "failure"

    def test_P04_timeout_present(self):
        from contracts.android_handoff_response import HandoffResponseKind
        assert HandoffResponseKind.timeout.value == "timeout"

    def test_P05_cancelled_present(self):
        from contracts.android_handoff_response import HandoffResponseKind
        assert HandoffResponseKind.cancelled.value == "cancelled"

    def test_P06_unknown_present(self):
        from contracts.android_handoff_response import HandoffResponseKind
        assert HandoffResponseKind.unknown.value == "unknown"

    def test_Q01_from_string_ack(self):
        from contracts.android_handoff_response import HandoffResponseKind
        assert HandoffResponseKind.from_string("ack") == HandoffResponseKind.ack

    def test_Q02_from_string_result(self):
        from contracts.android_handoff_response import HandoffResponseKind
        assert HandoffResponseKind.from_string("result") == HandoffResponseKind.result

    def test_Q03_from_string_failure(self):
        from contracts.android_handoff_response import HandoffResponseKind
        assert HandoffResponseKind.from_string("failure") == HandoffResponseKind.failure

    def test_R01_from_string_unknown_value(self):
        from contracts.android_handoff_response import HandoffResponseKind
        assert HandoffResponseKind.from_string("bogus") == HandoffResponseKind.unknown

    def test_R02_from_string_empty_string(self):
        from contracts.android_handoff_response import HandoffResponseKind
        assert HandoffResponseKind.from_string("") == HandoffResponseKind.unknown


# ============================================================================
# S–W. AndroidHandoffResponseEnvelope
# ============================================================================

class TestAndroidHandoffResponseEnvelope:

    def test_S01_default_response_id_generated(self):
        from contracts.android_handoff_response import AndroidHandoffResponseEnvelope
        env = AndroidHandoffResponseEnvelope()
        assert env.response_id.startswith("ahr_")

    def test_S02_default_handoff_id_empty(self):
        from contracts.android_handoff_response import AndroidHandoffResponseEnvelope
        env = AndroidHandoffResponseEnvelope()
        assert env.handoff_id == ""

    def test_S03_default_response_kind_unknown(self):
        from contracts.android_handoff_response import (
            AndroidHandoffResponseEnvelope, HandoffResponseKind,
        )
        env = AndroidHandoffResponseEnvelope()
        assert env.response_kind == HandoffResponseKind.unknown

    def test_S04_default_success_none(self):
        from contracts.android_handoff_response import AndroidHandoffResponseEnvelope
        env = AndroidHandoffResponseEnvelope()
        assert env.success is None

    def test_T01_to_dict_from_dict_round_trip(self):
        from contracts.android_handoff_response import (
            AndroidHandoffResponseEnvelope, HandoffResponseKind,
        )
        env = AndroidHandoffResponseEnvelope(
            handoff_id="hev2_abc",
            trace_id="trace_t",
            task_id="task_t",
            device_id="device_t",
            response_kind=HandoffResponseKind.result,
            success=True,
            result_payload={"data": "ok"},
        )
        recovered = AndroidHandoffResponseEnvelope.from_dict(env.to_dict())
        assert recovered.handoff_id == "hev2_abc"
        assert recovered.trace_id == "trace_t"
        assert recovered.response_kind == HandoffResponseKind.result
        assert recovered.success is True

    def test_U01_to_json_from_dict_round_trip(self):
        from contracts.android_handoff_response import (
            AndroidHandoffResponseEnvelope, HandoffResponseKind,
        )
        env = AndroidHandoffResponseEnvelope(
            handoff_id="hev2_u",
            response_kind=HandoffResponseKind.ack,
        )
        recovered = AndroidHandoffResponseEnvelope.from_dict(json.loads(env.to_json()))
        assert recovered.handoff_id == "hev2_u"

    def test_V01_ack_is_not_terminal(self):
        from contracts.android_handoff_response import (
            AndroidHandoffResponseEnvelope, HandoffResponseKind,
        )
        env = AndroidHandoffResponseEnvelope(response_kind=HandoffResponseKind.ack)
        assert env.is_terminal is False

    def test_W01_result_is_terminal(self):
        from contracts.android_handoff_response import (
            AndroidHandoffResponseEnvelope, HandoffResponseKind,
        )
        env = AndroidHandoffResponseEnvelope(response_kind=HandoffResponseKind.result)
        assert env.is_terminal is True

    def test_W02_failure_is_terminal(self):
        from contracts.android_handoff_response import (
            AndroidHandoffResponseEnvelope, HandoffResponseKind,
        )
        env = AndroidHandoffResponseEnvelope(response_kind=HandoffResponseKind.failure)
        assert env.is_terminal is True

    def test_W03_timeout_is_terminal(self):
        from contracts.android_handoff_response import (
            AndroidHandoffResponseEnvelope, HandoffResponseKind,
        )
        env = AndroidHandoffResponseEnvelope(response_kind=HandoffResponseKind.timeout)
        assert env.is_terminal is True

    def test_W04_cancelled_is_terminal(self):
        from contracts.android_handoff_response import (
            AndroidHandoffResponseEnvelope, HandoffResponseKind,
        )
        env = AndroidHandoffResponseEnvelope(response_kind=HandoffResponseKind.cancelled)
        assert env.is_terminal is True


# ============================================================================
# X–AD. Builder helpers
# ============================================================================

class TestBuilderHelpers:

    def _ack_message(self, handoff_id="hev2_ack", **extras):
        msg = {
            "type": "handoff_ack",
            "message_id": str(uuid.uuid4()),
            "device_id": "device_x",
            "trace_id": "trace_x",
            "payload": {
                "handoff_id": handoff_id,
                "task_id": "task_x",
                "session_id": "sess_x",
            },
        }
        msg.update(extras)
        return msg

    def _result_message(self, handoff_id="hev2_result"):
        return {
            "type": "handoff_result",
            "message_id": str(uuid.uuid4()),
            "device_id": "device_y",
            "trace_id": "trace_y",
            "payload": {
                "handoff_id": handoff_id,
                "task_id": "task_y",
                "result": {"screenshot": "base64data"},
            },
        }

    def _failure_message(self, handoff_id="hev2_fail"):
        return {
            "type": "handoff_failure",
            "message_id": str(uuid.uuid4()),
            "device_id": "device_z",
            "error_code": "EXEC_FAILED",
            "error_message": "OOM",
            "payload": {
                "handoff_id": handoff_id,
                "task_id": "task_z",
            },
        }

    def test_X01_from_ack_response_kind(self):
        from contracts.android_handoff_response import (
            from_android_ack_message, HandoffResponseKind,
        )
        env = from_android_ack_message(self._ack_message())
        assert env.response_kind == HandoffResponseKind.ack

    def test_X02_from_ack_success_none(self):
        from contracts.android_handoff_response import from_android_ack_message
        env = from_android_ack_message(self._ack_message())
        assert env.success is None

    def test_X03_from_ack_handoff_id_extracted(self):
        from contracts.android_handoff_response import from_android_ack_message
        env = from_android_ack_message(self._ack_message(handoff_id="hev2_xyz"))
        assert env.handoff_id == "hev2_xyz"

    def test_X04_from_ack_device_id_extracted(self):
        from contracts.android_handoff_response import from_android_ack_message
        env = from_android_ack_message(self._ack_message())
        assert env.device_id == "device_x"

    def test_Y01_from_result_response_kind(self):
        from contracts.android_handoff_response import (
            from_android_result_message, HandoffResponseKind,
        )
        env = from_android_result_message(self._result_message())
        assert env.response_kind == HandoffResponseKind.result

    def test_Y02_from_result_success_true(self):
        from contracts.android_handoff_response import from_android_result_message
        env = from_android_result_message(self._result_message())
        assert env.success is True

    def test_Y03_from_result_payload_extracted(self):
        from contracts.android_handoff_response import from_android_result_message
        env = from_android_result_message(self._result_message())
        assert env.result_payload is not None
        assert env.result_payload.get("screenshot") == "base64data"

    def test_Z01_from_failure_response_kind(self):
        from contracts.android_handoff_response import (
            from_android_failure_message, HandoffResponseKind,
        )
        env = from_android_failure_message(self._failure_message())
        assert env.response_kind == HandoffResponseKind.failure

    def test_Z02_from_failure_success_false(self):
        from contracts.android_handoff_response import from_android_failure_message
        env = from_android_failure_message(self._failure_message())
        assert env.success is False

    def test_Z03_from_failure_error_code(self):
        from contracts.android_handoff_response import from_android_failure_message
        env = from_android_failure_message(self._failure_message())
        assert env.error_code == "EXEC_FAILED"

    def test_Z04_from_failure_error_detail(self):
        from contracts.android_handoff_response import from_android_failure_message
        env = from_android_failure_message(self._failure_message())
        assert env.error_detail == "OOM"

    def test_AA01_failure_message_type_maps_correctly(self):
        from contracts.android_handoff_response import (
            from_android_failure_message, HandoffResponseKind,
        )
        msg = {
            "type": "handoff_failure",
            "device_id": "d",
            "payload": {"handoff_id": "h1"},
        }
        env = from_android_failure_message(msg)
        assert env.response_kind == HandoffResponseKind.failure

    def test_AB01_extract_dispatches_ack(self):
        from contracts.android_handoff_response import (
            extract_handoff_response_envelope, HandoffResponseKind,
        )
        env = extract_handoff_response_envelope(self._ack_message())
        assert env.response_kind == HandoffResponseKind.ack

    def test_AB02_extract_dispatches_result(self):
        from contracts.android_handoff_response import (
            extract_handoff_response_envelope, HandoffResponseKind,
        )
        env = extract_handoff_response_envelope(self._result_message())
        assert env.response_kind == HandoffResponseKind.result

    def test_AB03_extract_dispatches_failure(self):
        from contracts.android_handoff_response import (
            extract_handoff_response_envelope, HandoffResponseKind,
        )
        env = extract_handoff_response_envelope(self._failure_message())
        assert env.response_kind == HandoffResponseKind.failure

    def test_AC01_extract_dispatches_by_response_kind_in_payload(self):
        from contracts.android_handoff_response import (
            extract_handoff_response_envelope, HandoffResponseKind,
        )
        msg = {
            "type": "task_result",
            "device_id": "d",
            "payload": {
                "handoff_id": "h1",
                "response_kind": "result",
            },
        }
        env = extract_handoff_response_envelope(msg)
        assert env.response_kind == HandoffResponseKind.result

    def test_AD01_extract_unknown_type(self):
        from contracts.android_handoff_response import (
            extract_handoff_response_envelope, HandoffResponseKind,
        )
        msg = {"type": "unrelated_message", "device_id": "d"}
        env = extract_handoff_response_envelope(msg)
        assert env.response_kind == HandoffResponseKind.unknown

    def test_AE01_identity_from_nested_payload(self):
        from contracts.android_handoff_response import from_android_ack_message
        msg = {
            "type": "handoff_ack",
            "device_id": "device_outer",
            "trace_id": "trace_outer",
            "payload": {
                "handoff_id": "hev2_nested",
                "task_id": "task_nested",
                "session_id": "sess_nested",
            },
        }
        env = from_android_ack_message(msg)
        assert env.handoff_id == "hev2_nested"
        assert env.task_id == "task_nested"
        assert env.session_id == "sess_nested"
        assert env.device_id == "device_outer"


# ============================================================================
# AF–AK. HandoffV2ResponseRuntime
# ============================================================================

class TestHandoffV2ResponseRuntime:

    def _fresh_runtime(self):
        from core.android_handoff_v2_response_ingress import HandoffV2ResponseRuntime
        return HandoffV2ResponseRuntime()

    def _ack_env(self, handoff_id="h1", task_id="t1"):
        from contracts.android_handoff_response import (
            AndroidHandoffResponseEnvelope, HandoffResponseKind,
        )
        return AndroidHandoffResponseEnvelope(
            handoff_id=handoff_id,
            task_id=task_id,
            response_kind=HandoffResponseKind.ack,
        )

    def _result_env(self, handoff_id="h1", task_id="t1"):
        from contracts.android_handoff_response import (
            AndroidHandoffResponseEnvelope, HandoffResponseKind,
        )
        return AndroidHandoffResponseEnvelope(
            handoff_id=handoff_id,
            task_id=task_id,
            response_kind=HandoffResponseKind.result,
            success=True,
        )

    def test_AF01_register_and_resolve_by_handoff_id(self):
        rt = self._fresh_runtime()
        called: List[Any] = []
        rt.register("h_af01", lambda env: called.append(env), task_id="t_af01")
        cb = rt.resolve(self._ack_env(handoff_id="h_af01"), clear=False)
        assert cb is not None

    def test_AG01_resolve_by_task_id_fallback(self):
        rt = self._fresh_runtime()
        called: List[Any] = []
        rt.register("h_ag01", lambda env: called.append(env), task_id="t_ag01")
        # resolve with empty handoff_id → should fall back to task_id
        from contracts.android_handoff_response import (
            AndroidHandoffResponseEnvelope, HandoffResponseKind,
        )
        env = AndroidHandoffResponseEnvelope(
            handoff_id="",
            task_id="t_ag01",
            response_kind=HandoffResponseKind.ack,
        )
        cb = rt.resolve(env, clear=False)
        assert cb is not None

    def test_AH01_terminal_resolve_clears_entry(self):
        rt = self._fresh_runtime()
        rt.register("h_ah01", lambda e: None)
        env = self._result_env(handoff_id="h_ah01")
        rt.resolve(env, clear=True)
        assert "h_ah01" not in rt.pending_by_handoff_id

    def test_AI01_ack_resolve_does_not_clear(self):
        rt = self._fresh_runtime()
        rt.register("h_ai01", lambda e: None)
        env = self._ack_env(handoff_id="h_ai01")
        rt.resolve(env, clear=False)
        assert "h_ai01" in rt.pending_by_handoff_id

    def test_AJ01_resolve_returns_none_for_unknown_id(self):
        rt = self._fresh_runtime()
        env = self._ack_env(handoff_id="no_such")
        cb = rt.resolve(env)
        assert cb is None

    def test_AK01_outcome_fields(self):
        from core.android_handoff_v2_response_ingress import HandoffV2ResponseOutcome
        from contracts.android_handoff_response import AndroidHandoffResponseEnvelope
        outcome = HandoffV2ResponseOutcome(
            envelope=AndroidHandoffResponseEnvelope(),
            was_correlated=True,
            reject_reason="",
            callback_invoked=True,
        )
        assert outcome.was_correlated is True
        assert outcome.callback_invoked is True


# ============================================================================
# AL–AR. ingest_android_handoff_response
# ============================================================================

class TestIngestAndroidHandoffResponse:

    def _fresh_runtime(self):
        from core.android_handoff_v2_response_ingress import HandoffV2ResponseRuntime
        return HandoffV2ResponseRuntime()

    def _ack_message(self, handoff_id):
        return {
            "type": "handoff_ack",
            "device_id": "d1",
            "trace_id": "tr1",
            "payload": {"handoff_id": handoff_id, "task_id": "task1"},
        }

    def _result_message(self, handoff_id):
        return {
            "type": "handoff_result",
            "device_id": "d1",
            "trace_id": "tr1",
            "payload": {
                "handoff_id": handoff_id,
                "task_id": "task1",
                "result": {"data": "ok"},
            },
        }

    def _failure_message(self, handoff_id):
        return {
            "type": "handoff_failure",
            "device_id": "d1",
            "error_code": "ERR",
            "error_message": "bad",
            "payload": {"handoff_id": handoff_id},
        }

    def test_AL01_ack_correlated_callback_invoked(self):
        from core.android_handoff_v2_response_ingress import ingest_android_handoff_response
        rt = self._fresh_runtime()
        received: List[Any] = []
        rt.register("h_al01", lambda e: received.append(e))
        outcome = ingest_android_handoff_response(
            self._ack_message("h_al01"), runtime=rt
        )
        assert outcome.was_correlated is True
        assert outcome.callback_invoked is True
        assert len(received) == 1

    def test_AM01_result_is_terminal_clears_entry(self):
        from core.android_handoff_v2_response_ingress import ingest_android_handoff_response
        rt = self._fresh_runtime()
        rt.register("h_am01", lambda e: None)
        outcome = ingest_android_handoff_response(
            self._result_message("h_am01"), runtime=rt
        )
        assert outcome.was_correlated is True
        assert "h_am01" not in rt.pending_by_handoff_id

    def test_AM02_result_envelope_in_outcome(self):
        from core.android_handoff_v2_response_ingress import ingest_android_handoff_response
        from contracts.android_handoff_response import HandoffResponseKind
        rt = self._fresh_runtime()
        rt.register("h_am02", lambda e: None)
        outcome = ingest_android_handoff_response(
            self._result_message("h_am02"), runtime=rt
        )
        assert outcome.envelope.response_kind == HandoffResponseKind.result

    def test_AN01_failure_is_correlated_terminal(self):
        from core.android_handoff_v2_response_ingress import ingest_android_handoff_response
        rt = self._fresh_runtime()
        received: List[Any] = []
        rt.register("h_an01", lambda e: received.append(e))
        outcome = ingest_android_handoff_response(
            self._failure_message("h_an01"), runtime=rt
        )
        assert outcome.was_correlated is True
        assert outcome.envelope.success is False
        assert len(received) == 1

    def test_AO01_no_pending_entry_was_correlated_false(self):
        from core.android_handoff_v2_response_ingress import ingest_android_handoff_response
        rt = self._fresh_runtime()
        outcome = ingest_android_handoff_response(
            self._result_message("no_such_handoff"), runtime=rt
        )
        assert outcome.was_correlated is False
        assert outcome.reject_reason != ""

    def test_AP01_unknown_kind_was_correlated_false(self):
        from core.android_handoff_v2_response_ingress import ingest_android_handoff_response
        rt = self._fresh_runtime()
        msg = {"type": "unrelated", "device_id": "d", "payload": {}}
        outcome = ingest_android_handoff_response(msg, runtime=rt)
        assert outcome.was_correlated is False

    def test_AQ01_callback_exception_is_non_fatal(self):
        from core.android_handoff_v2_response_ingress import ingest_android_handoff_response
        rt = self._fresh_runtime()

        def exploding_callback(env):
            raise RuntimeError("intentional error")

        rt.register("h_aq01", exploding_callback)
        outcome = ingest_android_handoff_response(
            self._ack_message("h_aq01"), runtime=rt
        )
        assert outcome.was_correlated is True
        assert outcome.callback_invoked is False

    def test_AR01_broken_message_not_fatal(self):
        from core.android_handoff_v2_response_ingress import ingest_android_handoff_response
        rt = self._fresh_runtime()
        # None instead of a dict will cause extraction to raise internally
        outcome = ingest_android_handoff_response(None, runtime=rt)  # type: ignore[arg-type]
        assert outcome.was_correlated is False


# ============================================================================
# AS. Full correlation round-trip
# ============================================================================

class TestFullRoundTrip:

    def test_AS01_build_dispatch_ack_result(self):
        """Build envelope → dispatch message → ack → result full round-trip."""
        from contracts.handoff_envelope_v2 import build_handoff_envelope_v2
        from core.android_handoff_v2_response_ingress import (
            HandoffV2ResponseRuntime, ingest_android_handoff_response,
        )
        from contracts.android_handoff_response import HandoffResponseKind

        # 1. V2 builds envelope
        envelope = build_handoff_envelope_v2(
            trace_id="roundtrip_trace",
            task={"tool_name": "screenshot"},
            source_device_id="pc_01",
            target_device_id="android_01",
            capability="screen",
        )

        # 2. V2 registers pending callback
        rt = HandoffV2ResponseRuntime()
        lifecycle: List[str] = []
        rt.register(
            envelope.handoff_id,
            lambda e: lifecycle.append(e.response_kind),
            task_id=envelope.task_id,
        )

        # 3. V2 builds dispatch message (Android would receive this)
        dispatch_msg = envelope.to_android_task_assign_payload("android_01")
        assert dispatch_msg["handoff_id"] == envelope.handoff_id

        # 4. Android sends ACK
        ack_msg = {
            "type": "handoff_ack",
            "device_id": "android_01",
            "trace_id": "roundtrip_trace",
            "payload": {
                "handoff_id": envelope.handoff_id,
                "task_id": envelope.task_id,
            },
        }
        outcome_ack = ingest_android_handoff_response(ack_msg, runtime=rt)
        assert outcome_ack.was_correlated is True
        assert lifecycle == [HandoffResponseKind.ack]
        # ACK should NOT clear the pending entry
        assert envelope.handoff_id in rt.pending_by_handoff_id

        # 5. Android sends result
        result_msg = {
            "type": "handoff_result",
            "device_id": "android_01",
            "trace_id": "roundtrip_trace",
            "payload": {
                "handoff_id": envelope.handoff_id,
                "task_id": envelope.task_id,
                "result": {"screenshot": "base64..."},
            },
        }
        outcome_result = ingest_android_handoff_response(result_msg, runtime=rt)
        assert outcome_result.was_correlated is True
        assert outcome_result.envelope.success is True
        assert lifecycle == [HandoffResponseKind.ack, HandoffResponseKind.result]
        # result is terminal — pending entry must be cleared
        assert envelope.handoff_id not in rt.pending_by_handoff_id


# ============================================================================
# AT–AX. Backward compat and contract mapping
# ============================================================================

class TestBackwardCompat:

    def test_AT01_build_helper_produces_android_payload(self):
        from contracts.handoff_envelope_v2 import build_handoff_envelope_v2
        env = build_handoff_envelope_v2(
            trace_id="at_trace",
            task={"tool_name": "app"},
            capability="touch",
        )
        payload = env.to_android_native_payload()
        assert payload["schema_version"] == "v2"
        assert payload["handoff_id"]

    def test_AU01_from_legacy_produces_android_payload(self):
        from contracts.handoff_envelope_v2 import from_legacy_handoff_contract

        class _Legacy:
            trace_id = "legacy_trace"
            task = {"tool_name": "open"}
            capability = "screen"
            exec_mode = "both"
            route_mode = "direct"
            session = {}
            callback_channel = "ws"
            task_id = None
            source_runtime_posture = "control_only"

        env = from_legacy_handoff_contract(_Legacy())
        payload = env.to_android_native_payload()
        assert payload["trace_id"] == "legacy_trace"
        assert payload["schema_version"] == "v2"

    def test_AV01_handoff_id_unique_per_envelope(self):
        from contracts.handoff_envelope_v2 import build_handoff_envelope_v2
        e1 = build_handoff_envelope_v2(trace_id="t1", task={})
        e2 = build_handoff_envelope_v2(trace_id="t2", task={})
        assert e1.handoff_id != e2.handoff_id

    def test_AW01_task_id_none_valid_android_payload(self):
        from contracts.handoff_envelope_v2 import build_handoff_envelope_v2
        env = build_handoff_envelope_v2(trace_id="t", task={})
        # task_id is None by default — payload should still be valid
        payload = env.to_android_native_payload()
        assert payload["task_id"] is None or payload["task_id"] == ""

    def test_AX01_handoff_id_survives_dispatch_to_extract(self):
        from contracts.handoff_envelope_v2 import build_handoff_envelope_v2
        from contracts.android_handoff_response import extract_handoff_response_envelope
        env = build_handoff_envelope_v2(
            trace_id="ax_trace",
            task={"tool_name": "screenshot"},
        )
        dispatch_msg = env.to_android_task_assign_payload("device_ax")
        # Simulate Android echoing back handoff_id in ACK
        ack_msg = {
            "type": "handoff_ack",
            "device_id": "device_ax",
            "trace_id": "ax_trace",
            "payload": {
                "handoff_id": dispatch_msg["handoff_id"],
            },
        }
        response_env = extract_handoff_response_envelope(ack_msg)
        assert response_env.handoff_id == env.handoff_id
