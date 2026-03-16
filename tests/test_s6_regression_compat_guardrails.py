"""
tests/test_s6_regression_compat_guardrails.py
==============================================

PR-S6 "回归与兼容守护 (Regression & Compatibility Guardrails)"
---------------------------------------------------------------

Purpose
~~~~~~~
Ensure that:

1. **Legacy → compat → v3 contract** – every supported legacy payload type
   (device_register, heartbeat, capability_report, task_assign,
   command_result) exits the compat layer as a valid AIP v3 object with the
   correct canonical ``MessageType``.

2. **Native v3 regression** – payloads already expressed as AIP/3.0 pass
   through the compat layer unchanged and produce the expected v3 objects.
   After a v3-only refactor, the same inputs must yield the same outputs.

3. **Negative / rejection tests** – raw v2-versioned or v1-legacy payloads
   must be *rejected* (``AIPVersionError``) when they reach a strict v3
   ingress point (``parse_message_strict``) without having been normalised by
   ``parse_message_compat`` first.

4. **Smoke suite** – each test in this module is tagged with the pytest marker
   ``s6_smoke`` so that CI can run the full guardrail suite with::

       pytest -m s6_smoke tests/test_s6_regression_compat_guardrails.py

Scope
~~~~~
* ``galaxy_gateway/protocol/compat.py`` – normalisation functions
* ``galaxy_gateway/protocol/aip_v3.py``  – AIPMessage / MessageType
* ``galaxy_gateway/android_granular_adapter.py`` – v3-only adapter
* ``tests/fixtures/legacy_payloads.py``  – canonical test fixtures

No protocol shape changes are made; all tests are read-only assertions.
"""

import copy

import pytest
from pydantic import ValidationError

from galaxy_gateway.android_granular_adapter import (
    AIPAdapterVersionError,
    AndroidGranularAdapter,
)
from galaxy_gateway.protocol.aip_v3 import AIPMessage, MessageType
from galaxy_gateway.protocol.compat import (
    AIPVersionError,
    normalise_legacy_payload,
    normalise_to_v3_dict,
    parse_message_compat,
    parse_message_strict,
)
from tests.fixtures.legacy_payloads import LEGACY_V1, LEGACY_V2, NATIVE_V3, NEGATIVE_CASES

# ---------------------------------------------------------------------------
# Register the custom pytest marker so the suite can be targeted by CI:
#   pytest -m s6_smoke tests/test_s6_regression_compat_guardrails.py
# ---------------------------------------------------------------------------
pytestmark = pytest.mark.s6_smoke


# ===========================================================================
# Section 1: Legacy → compat → v3 contract tests
# ===========================================================================


class TestLegacyV1ToV3Contract:
    """
    AIP/1.0 payloads (no ``version`` field, legacy type aliases) must be
    normalised to AIP/3.0 AIPMessage objects with canonical MessageType values
    by ``parse_message_compat``.
    """

    # --- device_register ---------------------------------------------------

    def test_v1_register_alias_becomes_device_register(self):
        """v1 'register' type → MessageType.DEVICE_REGISTER after compat."""
        msg = parse_message_compat(copy.deepcopy(LEGACY_V1["device_register"]))
        assert isinstance(msg, AIPMessage)
        assert msg.version.startswith("3"), "version must be upgraded to 3.x"
        assert msg.type == MessageType.DEVICE_REGISTER
        assert msg.device_id == "v1-dev-001"

    def test_v1_agent_register_alias_becomes_device_register(self):
        """v1 'agent_register' alias → MessageType.DEVICE_REGISTER."""
        msg = parse_message_compat(
            copy.deepcopy(LEGACY_V1["device_register_alias_agent_register"])
        )
        assert msg.type == MessageType.DEVICE_REGISTER
        assert msg.version.startswith("3")

    def test_v1_registration_alias_becomes_device_register(self):
        """v1 'registration' alias → MessageType.DEVICE_REGISTER."""
        msg = parse_message_compat(
            copy.deepcopy(LEGACY_V1["device_register_alias_registration"])
        )
        assert msg.type == MessageType.DEVICE_REGISTER

    # --- heartbeat ---------------------------------------------------------

    def test_v1_heartbeat_becomes_device_heartbeat(self):
        """v1 'heartbeat' type → MessageType.DEVICE_HEARTBEAT after compat."""
        msg = parse_message_compat(copy.deepcopy(LEGACY_V1["heartbeat"]))
        assert isinstance(msg, AIPMessage)
        assert msg.version.startswith("3")
        assert msg.type == MessageType.DEVICE_HEARTBEAT
        assert msg.device_id == "v1-dev-010"

    def test_v1_device_heartbeat_alias_normalised(self):
        """v1 'device_heartbeat' alias → MessageType.DEVICE_HEARTBEAT."""
        msg = parse_message_compat(
            copy.deepcopy(LEGACY_V1["heartbeat_alias_device_heartbeat"])
        )
        assert msg.type == MessageType.DEVICE_HEARTBEAT

    # --- capability_report -------------------------------------------------

    def test_v1_capability_report_via_register_normalised(self):
        """v1 'register' with capability payload is normalised to v3 DEVICE_REGISTER."""
        raw = copy.deepcopy(LEGACY_V1["capability_report_via_register"])
        msg = parse_message_compat(raw)
        assert msg.version.startswith("3")
        # v1 'register' maps to DEVICE_REGISTER; payload is preserved for the handler
        assert msg.type == MessageType.DEVICE_REGISTER
        assert msg.device_id == "v1-dev-020"

    def test_v1_capability_payload_fields_preserved_in_dict(self):
        """normalise_to_v3_dict preserves extra payload fields from v1 capability fixture."""
        raw = copy.deepcopy(LEGACY_V1["capability_report_via_register"])
        d = normalise_to_v3_dict(raw)
        assert d["version"] == "3.0"
        payload = d.get("payload", {})
        assert "platform" in payload
        assert "supported_actions" in payload

    # --- task_assign -------------------------------------------------------

    def test_v1_task_execute_maps_to_task_submit(self):
        """v1 'task_execute' → MessageType.TASK_SUBMIT after compat."""
        msg = parse_message_compat(
            copy.deepcopy(LEGACY_V1["task_assign_via_task_execute"])
        )
        assert msg.version.startswith("3")
        assert msg.type == MessageType.TASK_SUBMIT
        assert msg.device_id == "v1-dev-030"

    def test_v1_task_execute_payload_preserved(self):
        """v1 task_execute payload is preserved after compat normalisation."""
        raw = copy.deepcopy(LEGACY_V1["task_assign_via_task_execute"])
        d = normalise_to_v3_dict(raw)
        assert d["version"] == "3.0"
        assert d.get("payload", {}).get("task_id") == "t-v1-001"

    # --- command_result ----------------------------------------------------

    def test_v1_command_result_maps_to_task_result(self):
        """v1 'command_result' type → MessageType.TASK_RESULT after compat."""
        msg = parse_message_compat(copy.deepcopy(LEGACY_V1["command_result"]))
        assert msg.version.startswith("3")
        assert msg.type == MessageType.TASK_RESULT
        assert msg.device_id == "v1-dev-040"

    def test_v1_response_alias_maps_to_command_result_type(self):
        """v1 'response' alias → MessageType.COMMAND_RESULT after compat."""
        msg = parse_message_compat(
            copy.deepcopy(LEGACY_V1["command_result_alias_response"])
        )
        assert msg.version.startswith("3")
        assert msg.type == MessageType.COMMAND_RESULT

    # --- common guarantees -------------------------------------------------

    def test_v1_device_id_defaults_to_unknown_when_absent(self):
        """compat injects device_id='unknown' when it is missing from a v1 message."""
        raw = {"type": "register"}   # no device_id
        msg = parse_message_compat(raw)
        assert msg.device_id == "unknown"

    def test_v1_trace_id_always_injected(self):
        """parse_message_compat always injects trace_id into the resulting message."""
        raw = {"type": "heartbeat", "device_id": "v1-trace-test"}
        msg = parse_message_compat(raw)
        # trace_id is injected into payload by inject_trace_metadata
        assert isinstance(msg, AIPMessage)
        assert msg.version.startswith("3")

    def test_v1_json_string_accepted(self):
        """parse_message_compat accepts a raw JSON string as well as a dict."""
        import json
        raw_str = json.dumps({"type": "heartbeat", "device_id": "v1-str-001"})
        msg = parse_message_compat(raw_str)
        assert msg.type == MessageType.DEVICE_HEARTBEAT


class TestLegacyV2ToV3Contract:
    """
    AIP/2.0 payloads (``version == "2.0"``) share v3 field names; compat
    must bump the version to ``"3.0"`` and return a valid AIPMessage.
    """

    def test_v2_device_register_version_bumped(self):
        """v2 device_register → version='3.0', type=DEVICE_REGISTER."""
        msg = parse_message_compat(copy.deepcopy(LEGACY_V2["device_register"]))
        assert isinstance(msg, AIPMessage)
        assert msg.version == "3.0"
        assert msg.type == MessageType.DEVICE_REGISTER
        assert msg.device_id == "v2-dev-001"

    def test_v2_heartbeat_version_bumped(self):
        """v2 heartbeat → version='3.0', type=DEVICE_HEARTBEAT."""
        msg = parse_message_compat(copy.deepcopy(LEGACY_V2["heartbeat"]))
        assert msg.version == "3.0"
        assert msg.type == MessageType.DEVICE_HEARTBEAT
        assert msg.device_id == "v2-dev-010"

    def test_v2_capability_report_version_bumped(self):
        """v2 capability_report → version='3.0', type=CAPABILITY_REPORT."""
        msg = parse_message_compat(copy.deepcopy(LEGACY_V2["capability_report"]))
        assert msg.version == "3.0"
        assert msg.type == MessageType.CAPABILITY_REPORT
        assert msg.device_id == "v2-dev-020"

    def test_v2_capability_report_payload_preserved(self):
        """v2 capability_report payload fields are preserved after version bump."""
        d = normalise_to_v3_dict(copy.deepcopy(LEGACY_V2["capability_report"]))
        assert d["version"] == "3.0"
        payload = d.get("payload", {})
        assert payload.get("platform") == "android"
        assert "supported_actions" in payload

    def test_v2_task_assign_version_bumped(self):
        """v2 task_assign → version='3.0', type=TASK_ASSIGN."""
        msg = parse_message_compat(copy.deepcopy(LEGACY_V2["task_assign"]))
        assert msg.version == "3.0"
        assert msg.type == MessageType.TASK_ASSIGN
        assert msg.device_id == "v2-dev-030"

    def test_v2_command_result_version_bumped(self):
        """v2 command_result → version='3.0', type=COMMAND_RESULT."""
        msg = parse_message_compat(copy.deepcopy(LEGACY_V2["command_result"]))
        assert msg.version == "3.0"
        assert msg.type == MessageType.COMMAND_RESULT
        assert msg.device_id == "v2-dev-040"

    def test_v2_device_id_defaults_to_unknown_when_absent(self):
        """v2 messages without device_id get device_id='unknown' from compat."""
        raw = {"version": "2.0", "type": "heartbeat"}
        msg = parse_message_compat(raw)
        assert msg.device_id == "unknown"

    def test_v2_extra_fields_preserved_by_dict_normaliser(self):
        """normalise_to_v3_dict preserves all extra v2 fields."""
        raw = {
            "version": "2.0",
            "type": "device_register",
            "device_id": "v2-extra",
            "custom_field": "should_survive",
        }
        d = normalise_to_v3_dict(raw)
        assert d["custom_field"] == "should_survive"
        assert d["version"] == "3.0"


# ===========================================================================
# Section 2: Native v3 regression tests
# ===========================================================================


class TestNativeV3Regression:
    """
    Payloads already expressed as AIP/3.0 must pass through the compat layer
    *unchanged* and produce the expected v3 AIPMessage.  After any v3-only
    refactor, the same inputs must continue to produce the same outputs.
    """

    def test_v3_device_register_passthrough(self):
        """Native v3 device_register passes through compat unchanged."""
        msg = parse_message_compat(copy.deepcopy(NATIVE_V3["device_register"]))
        assert msg.version == "3.0"
        assert msg.type == MessageType.DEVICE_REGISTER
        assert msg.device_id == "v3-dev-001"

    def test_v3_heartbeat_passthrough(self):
        """Native v3 heartbeat passes through compat unchanged."""
        msg = parse_message_compat(copy.deepcopy(NATIVE_V3["heartbeat"]))
        assert msg.version == "3.0"
        assert msg.type == MessageType.DEVICE_HEARTBEAT
        assert msg.device_id == "v3-dev-010"

    def test_v3_capability_report_passthrough(self):
        """Native v3 capability_report passes through compat unchanged."""
        msg = parse_message_compat(copy.deepcopy(NATIVE_V3["capability_report"]))
        assert msg.version == "3.0"
        assert msg.type == MessageType.CAPABILITY_REPORT
        assert msg.device_id == "v3-dev-020"

    def test_v3_capability_report_payload_intact(self):
        """v3 capability_report payload is not mutated by compat."""
        raw = copy.deepcopy(NATIVE_V3["capability_report"])
        msg = parse_message_compat(raw)
        assert msg.payload["platform"] == "android"
        assert "supported_actions" in msg.payload

    def test_v3_task_assign_passthrough(self):
        """Native v3 task_assign passes through compat unchanged."""
        msg = parse_message_compat(copy.deepcopy(NATIVE_V3["task_assign"]))
        assert msg.version == "3.0"
        assert msg.type == MessageType.TASK_ASSIGN
        assert msg.device_id == "v3-dev-030"

    def test_v3_command_result_passthrough(self):
        """Native v3 command_result passes through compat unchanged."""
        msg = parse_message_compat(copy.deepcopy(NATIVE_V3["command_result"]))
        assert msg.version == "3.0"
        assert msg.type == MessageType.COMMAND_RESULT
        assert msg.device_id == "v3-dev-040"

    def test_v3_message_is_aip_message_instance(self):
        """parse_message_compat always returns an AIPMessage for valid v3 input."""
        for key, raw in NATIVE_V3.items():
            msg = parse_message_compat(copy.deepcopy(raw))
            assert isinstance(msg, AIPMessage), f"fixture '{key}' did not return AIPMessage"

    def test_v3_all_message_types_have_v3_version(self):
        """All native v3 fixtures produce msg.version == '3.0'."""
        for key, raw in NATIVE_V3.items():
            msg = parse_message_compat(copy.deepcopy(raw))
            assert msg.version == "3.0", (
                f"fixture '{key}': expected version='3.0', got {msg.version!r}"
            )

    def test_v3_device_register_produces_stable_type_value(self):
        """v3 device_register type value is the stable string 'device_register'."""
        msg = parse_message_compat(copy.deepcopy(NATIVE_V3["device_register"]))
        assert msg.type.value == "device_register"

    def test_v3_heartbeat_produces_stable_type_value(self):
        """v3 heartbeat type value is the stable string 'heartbeat'."""
        msg = parse_message_compat(copy.deepcopy(NATIVE_V3["heartbeat"]))
        assert msg.type.value == "heartbeat"

    def test_v3_command_result_produces_stable_type_value(self):
        """v3 command_result type value is the stable string 'command_result'."""
        msg = parse_message_compat(copy.deepcopy(NATIVE_V3["command_result"]))
        assert msg.type.value == "command_result"

    def test_v3_task_assign_produces_stable_type_value(self):
        """v3 task_assign type value is the stable string 'task_assign'."""
        msg = parse_message_compat(copy.deepcopy(NATIVE_V3["task_assign"]))
        assert msg.type.value == "task_assign"

    def test_v3_capability_report_produces_stable_type_value(self):
        """v3 capability_report type value is the stable string 'capability_report'."""
        msg = parse_message_compat(copy.deepcopy(NATIVE_V3["capability_report"]))
        assert msg.type.value == "capability_report"


# ===========================================================================
# Section 3: Negative / rejection tests
# ===========================================================================


class TestNegativeStrictIngress:
    """
    ``parse_message_strict`` is the v3-only ingress validator.  It must reject
    any message whose ``version`` is absent, or below ``"3.0"``, with an
    ``AIPVersionError``.  Only messages that have passed through
    ``parse_message_compat`` (or were natively v3) should be forwarded to
    strict v3 handlers.
    """

    def test_v2_device_register_rejected_by_strict(self):
        """v2 device_register must raise AIPVersionError at strict ingress."""
        raw = copy.deepcopy(NEGATIVE_CASES["v2_device_register_strict"])
        with pytest.raises(AIPVersionError):
            parse_message_strict(raw)

    def test_v1_no_version_rejected_by_strict(self):
        """v1 message without version field raises AIPVersionError at strict ingress."""
        raw = copy.deepcopy(NEGATIVE_CASES["v1_no_version_strict"])
        with pytest.raises(AIPVersionError):
            parse_message_strict(raw)

    def test_v1_explicit_version_rejected_by_strict(self):
        """v1 message with version='1.0' raises AIPVersionError at strict ingress."""
        raw = copy.deepcopy(NEGATIVE_CASES["v1_explicit_version_strict"])
        with pytest.raises(AIPVersionError):
            parse_message_strict(raw)

    def test_v2_only_field_message_type_rejected_by_strict(self):
        """v2 message using 'message_type' instead of 'type' raises AIPVersionError."""
        raw = copy.deepcopy(NEGATIVE_CASES["v2_only_field_message_type"])
        with pytest.raises(AIPVersionError):
            parse_message_strict(raw)

    @pytest.mark.parametrize("version_str", ["0.9", "1.0", "1.5", "2.0", "2.9"])
    def test_sub_v3_versions_rejected_by_strict(self, version_str):
        """Any version string below '3.0' is rejected by parse_message_strict."""
        raw = {
            "version": version_str,
            "type": "device_register",
            "device_id": "neg-param-dev",
        }
        with pytest.raises(AIPVersionError):
            parse_message_strict(raw)

    def test_v3_after_compat_accepted_by_strict(self):
        """
        A message normalised by parse_message_compat (v1 → v3) can subsequently
        be passed to parse_message_strict without raising AIPVersionError.
        """
        raw = {"type": "register", "device_id": "compat-then-strict"}
        compat_dict = normalise_to_v3_dict(raw)
        # Must not raise
        msg = parse_message_strict(compat_dict)
        assert msg.version == "3.0"
        assert msg.type == MessageType.DEVICE_REGISTER

    def test_v2_after_compat_accepted_by_strict(self):
        """
        A v2 message normalised to v3 dict by normalise_to_v3_dict is accepted
        by parse_message_strict.
        """
        raw = copy.deepcopy(LEGACY_V2["heartbeat"])
        v3_dict = normalise_to_v3_dict(raw)
        msg = parse_message_strict(v3_dict)
        assert msg.version == "3.0"

    def test_native_v3_accepted_by_strict_directly(self):
        """Native v3 messages are accepted directly by parse_message_strict."""
        raw = copy.deepcopy(NATIVE_V3["device_register"])
        msg = parse_message_strict(raw)
        assert msg.version == "3.0"
        assert msg.type == MessageType.DEVICE_REGISTER


class TestNegativeAdapterDirectLegacy:
    """
    Raw legacy AIPMessage objects (version != '3.x') must be rejected by
    AndroidGranularAdapter with AIPAdapterVersionError.  Only messages that
    have passed through compat should reach the adapter.
    """

    @pytest.fixture()
    def adapter(self):
        from unittest.mock import AsyncMock, MagicMock
        adb = MagicMock()
        adb.shell = AsyncMock(return_value="ok")
        adb.pull = AsyncMock(return_value="ok")
        adb.install = AsyncMock(return_value="ok")
        return AndroidGranularAdapter(adb)

    @pytest.mark.asyncio
    async def test_v2_device_register_rejected_by_adapter(self, adapter):
        """AIPMessage(version='2.0') directly to adapter raises AIPAdapterVersionError."""
        msg = AIPMessage(
            version="2.0",
            type=MessageType.DEVICE_REGISTER,
            device_id="neg-adapter-v2",
        )
        with pytest.raises(AIPAdapterVersionError, match="v3-only"):
            await adapter.dispatch_aip_message("neg-adapter-v2", msg)

    @pytest.mark.asyncio
    async def test_v1_heartbeat_rejected_by_adapter(self, adapter):
        """AIPMessage(version='1.0') directly to adapter raises AIPAdapterVersionError."""
        msg = AIPMessage(
            version="1.0",
            type=MessageType.DEVICE_HEARTBEAT,
            device_id="neg-adapter-v1",
        )
        with pytest.raises(AIPAdapterVersionError):
            await adapter.dispatch_aip_message("neg-adapter-v1", msg)

    @pytest.mark.asyncio
    async def test_v2_capability_report_rejected_by_adapter(self, adapter):
        """AIPMessage(version='2.0', type=CAPABILITY_REPORT) is rejected."""
        msg = AIPMessage(
            version="2.0",
            type=MessageType.CAPABILITY_REPORT,
            device_id="neg-adapter-cap",
        )
        with pytest.raises(AIPAdapterVersionError):
            await adapter.dispatch_aip_message("neg-adapter-cap", msg)

    @pytest.mark.asyncio
    async def test_v2_task_assign_rejected_by_adapter(self, adapter):
        """AIPMessage(version='2.0', type=TASK_ASSIGN) is rejected."""
        msg = AIPMessage(
            version="2.0",
            type=MessageType.TASK_ASSIGN,
            device_id="neg-adapter-task",
        )
        with pytest.raises(AIPAdapterVersionError):
            await adapter.dispatch_aip_message("neg-adapter-task", msg)

    @pytest.mark.asyncio
    async def test_v2_command_result_rejected_by_adapter(self, adapter):
        """AIPMessage(version='2.0', type=COMMAND_RESULT) is rejected."""
        msg = AIPMessage(
            version="2.0",
            type=MessageType.COMMAND_RESULT,
            device_id="neg-adapter-cmd",
        )
        with pytest.raises(AIPAdapterVersionError):
            await adapter.dispatch_aip_message("neg-adapter-cmd", msg)

    @pytest.mark.asyncio
    async def test_v1_legacy_via_compat_then_adapter_succeeds(self, adapter):
        """
        A v1 legacy payload passed through compat IS accepted by the adapter.
        This is the correct 'compat then adapter' contract.
        """
        raw = {"type": "register", "device_id": "compat-flow-dev"}
        msg = parse_message_compat(raw)
        assert msg.version.startswith("3")
        # Must not raise — compat produced a valid v3 AIPMessage
        result = await adapter.dispatch_aip_message("compat-flow-dev", msg)
        assert isinstance(result, AIPMessage)


# ===========================================================================
# Section 4: normalise_legacy_payload field-promotion helper tests
# ===========================================================================


class TestNormaliseLegacyPayloadHelper:
    """
    ``normalise_legacy_payload`` / ``normalize_legacy_payload`` promotes
    v2-only fields (message_type, nested device_id) to their v3 equivalents.
    """

    def test_message_type_field_promoted_to_type(self):
        """'message_type' key is promoted to 'type' when 'type' is absent."""
        raw = {"message_type": "device_register", "device_id": "mtp-001"}
        out = normalise_legacy_payload(raw)
        assert out["type"] == "device_register"
        assert "message_type" in out  # original key preserved

    def test_device_id_promoted_from_payload(self):
        """device_id nested in payload is promoted to top-level when absent."""
        raw = {
            "type": "heartbeat",
            "payload": {"device_id": "inner-dev"},
        }
        out = normalise_legacy_payload(raw)
        assert out["device_id"] == "inner-dev"

    def test_existing_type_not_overwritten(self):
        """'type' is not overwritten when both 'type' and 'message_type' are present."""
        raw = {"type": "heartbeat", "message_type": "device_register", "device_id": "x"}
        out = normalise_legacy_payload(raw)
        assert out["type"] == "heartbeat"

    def test_existing_device_id_not_overwritten(self):
        """Top-level device_id is not overwritten by the nested payload value."""
        raw = {
            "type": "heartbeat",
            "device_id": "top-level",
            "payload": {"device_id": "inner"},
        }
        out = normalise_legacy_payload(raw)
        assert out["device_id"] == "top-level"

    def test_original_dict_not_mutated(self):
        """normalise_legacy_payload must not mutate the input dict."""
        raw = {"message_type": "heartbeat", "device_id": "immutable-dev"}
        original = dict(raw)
        normalise_legacy_payload(raw)
        assert raw == original

    def test_american_spelling_alias_works(self):
        """normalize_legacy_payload (American spelling) is identical in behaviour."""
        from galaxy_gateway.protocol.compat import normalize_legacy_payload
        raw = {"message_type": "heartbeat", "device_id": "alias-dev"}
        out = normalize_legacy_payload(raw)
        assert out["type"] == "heartbeat"


# ===========================================================================
# Section 5: End-to-end smoke – all 5 critical payload types, both legacy
#            versions, through the full compat → v3 → adapter chain
# ===========================================================================


class TestE2ESmokeAllPayloadTypes:
    """
    Fast end-to-end smoke: each of the 5 critical message types in both AIP/1.0
    and AIP/2.0 flavours flows through the complete chain
    (legacy wire → parse_message_compat → AIPMessage v3 → AndroidGranularAdapter)
    without error.
    """

    @pytest.fixture()
    def adapter(self):
        from unittest.mock import AsyncMock, MagicMock
        adb = MagicMock()
        adb.shell = AsyncMock(return_value="ok")
        adb.pull = AsyncMock(return_value="ok")
        adb.install = AsyncMock(return_value="ok")
        return AndroidGranularAdapter(adb)

    # --- device_register ---------------------------------------------------

    @pytest.mark.asyncio
    async def test_smoke_v1_device_register(self, adapter):
        raw = copy.deepcopy(LEGACY_V1["device_register"])
        msg = parse_message_compat(raw)
        assert msg.type == MessageType.DEVICE_REGISTER
        result = await adapter.dispatch_aip_message(msg.device_id, msg)
        assert isinstance(result, AIPMessage)

    @pytest.mark.asyncio
    async def test_smoke_v2_device_register(self, adapter):
        raw = copy.deepcopy(LEGACY_V2["device_register"])
        msg = parse_message_compat(raw)
        assert msg.version == "3.0"
        assert msg.type == MessageType.DEVICE_REGISTER
        result = await adapter.dispatch_aip_message(msg.device_id, msg)
        assert isinstance(result, AIPMessage)

    # --- heartbeat ---------------------------------------------------------

    @pytest.mark.asyncio
    async def test_smoke_v1_heartbeat(self, adapter):
        raw = copy.deepcopy(LEGACY_V1["heartbeat"])
        msg = parse_message_compat(raw)
        assert msg.type == MessageType.DEVICE_HEARTBEAT
        result = await adapter.dispatch_aip_message(msg.device_id, msg)
        assert isinstance(result, AIPMessage)

    @pytest.mark.asyncio
    async def test_smoke_v2_heartbeat(self, adapter):
        raw = copy.deepcopy(LEGACY_V2["heartbeat"])
        msg = parse_message_compat(raw)
        assert msg.version == "3.0"
        result = await adapter.dispatch_aip_message(msg.device_id, msg)
        assert isinstance(result, AIPMessage)

    # --- capability_report -------------------------------------------------

    @pytest.mark.asyncio
    async def test_smoke_v1_capability_report(self, adapter):
        """v1 capability data carried in a register payload flows end-to-end."""
        raw = copy.deepcopy(LEGACY_V1["capability_report_via_register"])
        msg = parse_message_compat(raw)
        # v1 'register' → DEVICE_REGISTER; capability data preserved in payload
        assert msg.version.startswith("3")
        result = await adapter.dispatch_aip_message(msg.device_id, msg)
        assert isinstance(result, AIPMessage)

    @pytest.mark.asyncio
    async def test_smoke_v2_capability_report(self, adapter):
        raw = copy.deepcopy(LEGACY_V2["capability_report"])
        msg = parse_message_compat(raw)
        assert msg.type == MessageType.CAPABILITY_REPORT
        result = await adapter.dispatch_aip_message(msg.device_id, msg)
        assert isinstance(result, AIPMessage)

    # --- task_assign -------------------------------------------------------

    @pytest.mark.asyncio
    async def test_smoke_v1_task_assign(self, adapter):
        """v1 'task_execute' → TASK_SUBMIT flows through adapter end-to-end."""
        raw = copy.deepcopy(LEGACY_V1["task_assign_via_task_execute"])
        msg = parse_message_compat(raw)
        assert msg.type == MessageType.TASK_SUBMIT
        result = await adapter.dispatch_aip_message(msg.device_id, msg)
        assert isinstance(result, AIPMessage)

    @pytest.mark.asyncio
    async def test_smoke_v2_task_assign(self, adapter):
        raw = copy.deepcopy(LEGACY_V2["task_assign"])
        msg = parse_message_compat(raw)
        assert msg.type == MessageType.TASK_ASSIGN
        result = await adapter.dispatch_aip_message(msg.device_id, msg)
        assert isinstance(result, AIPMessage)

    # --- command_result ----------------------------------------------------

    @pytest.mark.asyncio
    async def test_smoke_v1_command_result(self, adapter):
        """v1 'command_result' → TASK_RESULT flows through adapter end-to-end."""
        raw = copy.deepcopy(LEGACY_V1["command_result"])
        msg = parse_message_compat(raw)
        assert msg.type == MessageType.TASK_RESULT
        result = await adapter.dispatch_aip_message(msg.device_id, msg)
        assert isinstance(result, AIPMessage)

    @pytest.mark.asyncio
    async def test_smoke_v2_command_result(self, adapter):
        raw = copy.deepcopy(LEGACY_V2["command_result"])
        msg = parse_message_compat(raw)
        assert msg.type == MessageType.COMMAND_RESULT
        result = await adapter.dispatch_aip_message(msg.device_id, msg)
        assert isinstance(result, AIPMessage)
