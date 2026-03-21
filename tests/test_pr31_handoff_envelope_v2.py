"""tests/test_pr31_handoff_envelope_v2.py
==========================================
Tests for PR-31: Handoff Envelope v2 Contract.

Coverage:
  1.  Serialisation stability — to_dict / to_json / from_dict round-trips.
  2.  Stable field names — all documented fields present in to_dict output.
  3.  Sub-contract field correctness.
  4.  from_legacy_handoff_contract — adapter from HandoffContract.
  5.  from_bridge_inputs — adapter from raw bridge parameters.
  6.  to_legacy_bridge_payload — v2 → legacy compatibility payload.
  7.  build_handoff_envelope_v2 — convenience factory.
  8.  to_compact_summary — projection-safe compact summary.
  9.  Graceful handling of partial / missing data.
  10. contracts package root re-exports.
  11. core.unified package re-exports.
  12. Bridge integration — handoff result includes handoff_envelope_v2 summary.
  13. AgentBridge.build_envelope_v2 helper.
  14. Legacy compatibility — to_legacy_bridge_payload round-trip.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_legacy_contract(
    trace_id: str = "trace_001",
    task: dict = None,
    capability: str = "screen",
    exec_mode: str = "both",
    route_mode: str = "direct",
    session: dict = None,
    callback_channel: str = "ws",
    task_id: str = "",
) -> Any:
    """Return a mock shaped like galaxy_gateway.agent_bridge.HandoffContract."""
    m = MagicMock()
    m.trace_id = trace_id
    m.task_id = task_id
    m.task = task if task is not None else {"tool_name": "screenshot", "args": {}}
    m.capability = capability
    m.exec_mode = exec_mode
    m.route_mode = route_mode
    m.session = session if session is not None else {}
    m.callback_channel = callback_channel
    return m


def _make_real_legacy_contract(**kwargs) -> Any:
    """Return an actual HandoffContract (uses dataclass)."""
    from galaxy_gateway.agent_bridge import HandoffContract
    defaults = dict(
        trace_id="trace_real_001",
        task={"tool_name": "open_app", "args": {"app": "Chrome"}},
        capability="screen",
        exec_mode="both",
        route_mode="direct",
        session={"session_id": "sess_abc"},
        callback_channel="ws",
        task_id="task_xyz",
    )
    defaults.update(kwargs)
    return HandoffContract(**defaults)


# ---------------------------------------------------------------------------
# 1. Serialisation stability
# ---------------------------------------------------------------------------

class TestSerialisationStability:
    """HandoffEnvelopeV2 serialises and round-trips correctly."""

    def test_to_dict_returns_serialisable_dict(self):
        from contracts.handoff_envelope_v2 import HandoffEnvelopeV2
        env = HandoffEnvelopeV2(trace_id="t1")
        result = env.to_dict()
        assert isinstance(result, dict)
        assert result["trace_id"] == "t1"
        # Must be JSON-serialisable
        json.dumps(result)

    def test_to_json_returns_valid_json(self):
        from contracts.handoff_envelope_v2 import HandoffEnvelopeV2
        env = HandoffEnvelopeV2(trace_id="t2", source_device_id="phone_001")
        raw = env.to_json()
        parsed = json.loads(raw)
        assert parsed["trace_id"] == "t2"
        assert parsed["source_device_id"] == "phone_001"

    def test_from_dict_round_trip(self):
        from contracts.handoff_envelope_v2 import HandoffEnvelopeV2
        original = HandoffEnvelopeV2(
            trace_id="t3",
            task_id="task_001",
            source_device_id="phone_001",
            target_device_id="tablet_002",
            capability="screen",
            exec_mode="remote",
        )
        data = original.to_dict()
        reconstructed = HandoffEnvelopeV2.from_dict(data)
        assert reconstructed.trace_id == "t3"
        assert reconstructed.task_id == "task_001"
        assert reconstructed.source_device_id == "phone_001"
        assert reconstructed.target_device_id == "tablet_002"
        assert reconstructed.exec_mode == "remote"

    def test_to_json_then_from_dict_full_round_trip(self):
        from contracts.handoff_envelope_v2 import HandoffEnvelopeV2
        env = HandoffEnvelopeV2(
            trace_id="t4",
            session_id="sess_001",
            source_device_id="phone_001",
            target_device_id="tablet_002",
            capability="camera",
            schema_version="v2",
        )
        data = json.loads(env.to_json())
        r = HandoffEnvelopeV2.from_dict(data)
        assert r.session_id == "sess_001"
        assert r.capability == "camera"
        assert r.schema_version == "v2"

    def test_schema_version_is_v2(self):
        from contracts.handoff_envelope_v2 import HandoffEnvelopeV2
        env = HandoffEnvelopeV2(trace_id="t5")
        assert env.schema_version == "v2"
        assert env.to_dict()["schema_version"] == "v2"

    def test_handoff_id_auto_generated(self):
        from contracts.handoff_envelope_v2 import HandoffEnvelopeV2
        e1 = HandoffEnvelopeV2(trace_id="t6a")
        e2 = HandoffEnvelopeV2(trace_id="t6b")
        assert e1.handoff_id.startswith("hev2_")
        assert e2.handoff_id.startswith("hev2_")
        assert e1.handoff_id != e2.handoff_id

    def test_created_at_is_float(self):
        import time
        from contracts.handoff_envelope_v2 import HandoffEnvelopeV2
        before = time.time()
        env = HandoffEnvelopeV2(trace_id="t7")
        after = time.time()
        assert before <= env.created_at <= after


# ---------------------------------------------------------------------------
# 2. Stable field names
# ---------------------------------------------------------------------------

class TestStableFieldNames:
    """All documented top-level fields present in to_dict output."""

    REQUIRED_FIELDS = {
        "handoff_id",
        "trace_id",
        "task_id",
        "session_id",
        "source_device_id",
        "target_device_id",
        "source_runtime_id",
        "target_runtime_id",
        "source",
        "target",
        "agent_spec",
        "task_spec",
        "session_context",
        "capability",
        "exec_mode",
        "route_mode",
        "callback_channel",
        "handoff_policy",
        "takeover_policy",
        "return_contract",
        "metadata",
        "schema_version",
        "created_at",
    }

    def test_all_required_fields_present(self):
        from contracts.handoff_envelope_v2 import HandoffEnvelopeV2
        env = HandoffEnvelopeV2(trace_id="fields_test")
        result = env.to_dict()
        missing = self.REQUIRED_FIELDS - set(result.keys())
        assert not missing, f"Missing fields: {missing}"


# ---------------------------------------------------------------------------
# 3. Sub-contract field correctness
# ---------------------------------------------------------------------------

class TestSubContractFields:
    """Sub-contract models serialise with expected fields."""

    def test_handoff_source_summary_fields(self):
        from contracts.handoff_envelope_v2 import HandoffSourceSummary
        s = HandoffSourceSummary(
            device_id="phone_001",
            runtime_id="rt_abc",
            platform="android",
            runtime_version="1.0.0",
            capability_summary=["screen", "camera"],
        )
        d = s.model_dump()
        assert d["device_id"] == "phone_001"
        assert d["runtime_id"] == "rt_abc"
        assert d["platform"] == "android"
        assert d["capability_summary"] == ["screen", "camera"]

    def test_handoff_target_summary_fields(self):
        from contracts.handoff_envelope_v2 import HandoffTargetSummary
        t = HandoffTargetSummary(
            device_id="tablet_002",
            handoff_endpoint="http://tablet:9000/handoff",
        )
        d = t.model_dump()
        assert d["device_id"] == "tablet_002"
        assert d["handoff_endpoint"] == "http://tablet:9000/handoff"

    def test_handoff_agent_spec_fields(self):
        from contracts.handoff_envelope_v2 import HandoffAgentSpec
        a = HandoffAgentSpec(
            agent_id="agent_01",
            agent_type="executor",
            agent_role="primary",
            required_capabilities=["screen"],
        )
        d = a.model_dump()
        assert d["agent_id"] == "agent_01"
        assert d["agent_role"] == "primary"
        assert d["required_capabilities"] == ["screen"]

    def test_handoff_task_spec_fields(self):
        from contracts.handoff_envelope_v2 import HandoffTaskSpec
        t = HandoffTaskSpec(
            task_id="task_001",
            tool_name="open_app",
            args={"app": "Chrome"},
            targets=["tablet_002"],
            source="phone_001",
        )
        d = t.model_dump()
        assert d["task_id"] == "task_001"
        assert d["tool_name"] == "open_app"
        assert d["args"] == {"app": "Chrome"}

    def test_handoff_session_context_fields(self):
        from contracts.handoff_envelope_v2 import HandoffSessionContext
        sc = HandoffSessionContext(
            session_id="sess_abc",
            turn_id="turn_02",
            user_id="user_001",
        )
        d = sc.model_dump()
        assert d["session_id"] == "sess_abc"
        assert d["turn_id"] == "turn_02"
        assert d["user_id"] == "user_001"

    def test_local_takeover_policy_fields(self):
        from contracts.handoff_envelope_v2 import LocalTakeoverPolicy
        p = LocalTakeoverPolicy(
            allow_local_takeover=True,
            require_ack_before_takeover=True,
            max_takeover_duration_s=60.0,
            release_on_completion=True,
            fallback_on_timeout=True,
        )
        d = p.model_dump()
        assert d["allow_local_takeover"] is True
        assert d["require_ack_before_takeover"] is True
        assert d["max_takeover_duration_s"] == 60.0

    def test_handoff_return_contract_fields(self):
        from contracts.handoff_envelope_v2 import HandoffReturnContract
        rc = HandoffReturnContract(
            callback_channel="nats",
            expect_ack=True,
            expect_result=True,
            result_schema_hint="screenshot_v1",
        )
        d = rc.model_dump()
        assert d["callback_channel"] == "nats"
        assert d["expect_ack"] is True
        assert d["result_schema_hint"] == "screenshot_v1"

    def test_sub_contracts_in_envelope_to_dict(self):
        from contracts.handoff_envelope_v2 import HandoffEnvelopeV2
        env = HandoffEnvelopeV2(trace_id="sub_test")
        d = env.to_dict()
        # All sub-contracts must serialise as dicts
        assert isinstance(d["source"], dict)
        assert isinstance(d["target"], dict)
        assert isinstance(d["agent_spec"], dict)
        assert isinstance(d["task_spec"], dict)
        assert isinstance(d["session_context"], dict)
        assert isinstance(d["takeover_policy"], dict)
        assert isinstance(d["return_contract"], dict)


# ---------------------------------------------------------------------------
# 4. from_legacy_handoff_contract adapter
# ---------------------------------------------------------------------------

class TestFromLegacyHandoffContract:
    """from_legacy_handoff_contract maps legacy fields correctly."""

    def test_trace_id_preserved(self):
        from contracts.handoff_envelope_v2 import from_legacy_handoff_contract
        contract = _make_legacy_contract(trace_id="trace_leg_001")
        env = from_legacy_handoff_contract(contract)
        assert env.trace_id == "trace_leg_001"

    def test_capability_preserved(self):
        from contracts.handoff_envelope_v2 import from_legacy_handoff_contract
        contract = _make_legacy_contract(capability="camera")
        env = from_legacy_handoff_contract(contract)
        assert env.capability == "camera"

    def test_exec_mode_preserved(self):
        from contracts.handoff_envelope_v2 import from_legacy_handoff_contract
        contract = _make_legacy_contract(exec_mode="remote")
        env = from_legacy_handoff_contract(contract)
        assert env.exec_mode == "remote"

    def test_route_mode_preserved(self):
        from contracts.handoff_envelope_v2 import from_legacy_handoff_contract
        contract = _make_legacy_contract(route_mode="broadcast")
        env = from_legacy_handoff_contract(contract)
        assert env.route_mode == "broadcast"

    def test_callback_channel_preserved(self):
        from contracts.handoff_envelope_v2 import from_legacy_handoff_contract
        contract = _make_legacy_contract(callback_channel="nats")
        env = from_legacy_handoff_contract(contract)
        assert env.callback_channel == "nats"

    def test_task_id_preserved(self):
        from contracts.handoff_envelope_v2 import from_legacy_handoff_contract
        contract = _make_legacy_contract(task_id="task_abc")
        env = from_legacy_handoff_contract(contract)
        assert env.task_id == "task_abc"

    def test_task_dict_projected_to_task_spec(self):
        from contracts.handoff_envelope_v2 import from_legacy_handoff_contract
        contract = _make_legacy_contract(
            task={"tool_name": "open_app", "args": {"app": "Chrome"}, "targets": ["tablet_002"]}
        )
        env = from_legacy_handoff_contract(contract)
        assert env.task_spec.tool_name == "open_app"
        assert env.task_spec.args == {"app": "Chrome"}
        assert env.task_spec.targets == ["tablet_002"]

    def test_session_dict_projected_to_session_context(self):
        from contracts.handoff_envelope_v2 import from_legacy_handoff_contract
        contract = _make_legacy_contract(
            session={"session_id": "sess_xyz", "turn_id": "t1", "user_id": "u1"}
        )
        env = from_legacy_handoff_contract(contract)
        assert env.session_context.session_id == "sess_xyz"
        assert env.session_context.turn_id == "t1"
        assert env.session_context.user_id == "u1"

    def test_raw_task_preserved_in_task_spec(self):
        from contracts.handoff_envelope_v2 import from_legacy_handoff_contract
        raw = {"tool_name": "screenshot", "args": {}, "extra_field": "yes"}
        contract = _make_legacy_contract(task=raw)
        env = from_legacy_handoff_contract(contract)
        assert env.task_spec.raw_task == raw

    def test_raw_session_preserved_in_session_context(self):
        from contracts.handoff_envelope_v2 import from_legacy_handoff_contract
        raw_sess = {"session_id": "s1", "custom_key": "val"}
        contract = _make_legacy_contract(session=raw_sess)
        env = from_legacy_handoff_contract(contract)
        assert env.session_context.raw_session == raw_sess

    def test_schema_version_is_v2(self):
        from contracts.handoff_envelope_v2 import from_legacy_handoff_contract
        contract = _make_legacy_contract()
        env = from_legacy_handoff_contract(contract)
        assert env.schema_version == "v2"

    def test_handoff_id_auto_generated(self):
        from contracts.handoff_envelope_v2 import from_legacy_handoff_contract
        contract = _make_legacy_contract()
        env = from_legacy_handoff_contract(contract)
        assert env.handoff_id.startswith("hev2_")

    def test_return_contract_callback_channel_matches(self):
        from contracts.handoff_envelope_v2 import from_legacy_handoff_contract
        contract = _make_legacy_contract(callback_channel="webrtc")
        env = from_legacy_handoff_contract(contract)
        assert env.return_contract.callback_channel == "webrtc"

    def test_from_real_handoff_contract(self):
        from contracts.handoff_envelope_v2 import from_legacy_handoff_contract
        contract = _make_real_legacy_contract()
        env = from_legacy_handoff_contract(contract)
        assert env.trace_id == "trace_real_001"
        assert env.task_id == "task_xyz"
        assert env.task_spec.tool_name == "open_app"
        assert env.session_context.session_id == "sess_abc"


# ---------------------------------------------------------------------------
# 5. from_bridge_inputs adapter
# ---------------------------------------------------------------------------

class TestFromBridgeInputs:
    """from_bridge_inputs builds HandoffEnvelopeV2 from raw bridge params."""

    def test_basic_fields(self):
        from contracts.handoff_envelope_v2 import from_bridge_inputs
        env = from_bridge_inputs(
            trace_id="bridge_t1",
            task={"tool_name": "screenshot"},
            capability="screen",
            exec_mode="remote",
        )
        assert env.trace_id == "bridge_t1"
        assert env.capability == "screen"
        assert env.exec_mode == "remote"
        assert env.task_spec.tool_name == "screenshot"

    def test_device_ids_embedded(self):
        from contracts.handoff_envelope_v2 import from_bridge_inputs
        env = from_bridge_inputs(
            trace_id="bridge_t2",
            task={},
            source_device_id="phone_001",
            target_device_id="tablet_002",
        )
        assert env.source_device_id == "phone_001"
        assert env.target_device_id == "tablet_002"
        assert env.source.device_id == "phone_001"
        assert env.target.device_id == "tablet_002"

    def test_runtime_ids_embedded(self):
        from contracts.handoff_envelope_v2 import from_bridge_inputs
        env = from_bridge_inputs(
            trace_id="bridge_t3",
            task={},
            source_runtime_id="rt_src",
            target_runtime_id="rt_tgt",
        )
        assert env.source_runtime_id == "rt_src"
        assert env.target_runtime_id == "rt_tgt"
        assert env.source.runtime_id == "rt_src"
        assert env.target.runtime_id == "rt_tgt"

    def test_session_projected(self):
        from contracts.handoff_envelope_v2 import from_bridge_inputs
        env = from_bridge_inputs(
            trace_id="bridge_t4",
            task={},
            session={"session_id": "sess_01", "user_id": "usr_01"},
        )
        assert env.session_context.session_id == "sess_01"
        assert env.session_context.user_id == "usr_01"

    def test_task_id_forwarded(self):
        from contracts.handoff_envelope_v2 import from_bridge_inputs
        env = from_bridge_inputs(trace_id="bridge_t5", task={}, task_id="task_q1")
        assert env.task_id == "task_q1"
        assert env.task_spec.task_id == "task_q1"

    def test_handoff_policy_embedded(self):
        from contracts.handoff_envelope_v2 import from_bridge_inputs
        policy = {"ack_required": True, "max_handoff_depth": 3}
        env = from_bridge_inputs(trace_id="bridge_t6", task={}, handoff_policy=policy)
        assert env.handoff_policy == policy

    def test_metadata_embedded(self):
        from contracts.handoff_envelope_v2 import from_bridge_inputs
        env = from_bridge_inputs(
            trace_id="bridge_t7", task={}, metadata={"custom": "value"}
        )
        assert env.metadata["custom"] == "value"

    def test_empty_session_defaults(self):
        from contracts.handoff_envelope_v2 import from_bridge_inputs
        env = from_bridge_inputs(trace_id="bridge_t8", task={})
        assert env.session_context.session_id is None
        assert env.session_context.raw_session == {}


# ---------------------------------------------------------------------------
# 6. to_legacy_bridge_payload adapter
# ---------------------------------------------------------------------------

class TestToLegacyBridgePayload:
    """to_legacy_bridge_payload produces a legacy-compatible dict."""

    LEGACY_KEYS = {"trace_id", "task", "capability", "exec_mode", "route_mode", "session", "callback_channel"}

    def test_all_legacy_keys_present(self):
        from contracts.handoff_envelope_v2 import HandoffEnvelopeV2, to_legacy_bridge_payload
        env = HandoffEnvelopeV2(trace_id="t_leg_1", capability="screen")
        payload = to_legacy_bridge_payload(env)
        missing = self.LEGACY_KEYS - set(payload.keys())
        assert not missing, f"Missing legacy keys: {missing}"

    def test_trace_id_preserved(self):
        from contracts.handoff_envelope_v2 import HandoffEnvelopeV2, to_legacy_bridge_payload
        env = HandoffEnvelopeV2(trace_id="t_leg_2")
        assert to_legacy_bridge_payload(env)["trace_id"] == "t_leg_2"

    def test_capability_preserved(self):
        from contracts.handoff_envelope_v2 import HandoffEnvelopeV2, to_legacy_bridge_payload
        env = HandoffEnvelopeV2(trace_id="t_leg_3", capability="camera")
        assert to_legacy_bridge_payload(env)["capability"] == "camera"

    def test_exec_mode_preserved(self):
        from contracts.handoff_envelope_v2 import HandoffEnvelopeV2, to_legacy_bridge_payload
        env = HandoffEnvelopeV2(trace_id="t_leg_4", exec_mode="local")
        assert to_legacy_bridge_payload(env)["exec_mode"] == "local"

    def test_task_id_included_when_present(self):
        from contracts.handoff_envelope_v2 import HandoffEnvelopeV2, to_legacy_bridge_payload
        env = HandoffEnvelopeV2(trace_id="t_leg_5", task_id="task_001")
        payload = to_legacy_bridge_payload(env)
        assert payload.get("task_id") == "task_001"

    def test_task_id_absent_when_none(self):
        from contracts.handoff_envelope_v2 import HandoffEnvelopeV2, to_legacy_bridge_payload
        env = HandoffEnvelopeV2(trace_id="t_leg_6")
        payload = to_legacy_bridge_payload(env)
        assert "task_id" not in payload

    def test_raw_task_used_when_available(self):
        from contracts.handoff_envelope_v2 import (
            HandoffEnvelopeV2, HandoffTaskSpec, to_legacy_bridge_payload,
        )
        raw = {"tool_name": "screenshot", "args": {}, "my_extra": True}
        env = HandoffEnvelopeV2(
            trace_id="t_leg_7",
            task_spec=HandoffTaskSpec(raw_task=raw),
        )
        payload = to_legacy_bridge_payload(env)
        assert payload["task"] == raw

    def test_session_round_trip_via_raw_session(self):
        from contracts.handoff_envelope_v2 import (
            HandoffEnvelopeV2, HandoffSessionContext, to_legacy_bridge_payload,
        )
        raw_sess = {"session_id": "sess_abc", "user_id": "u1"}
        env = HandoffEnvelopeV2(
            trace_id="t_leg_8",
            session_context=HandoffSessionContext(raw_session=raw_sess),
        )
        payload = to_legacy_bridge_payload(env)
        assert payload["session"] == raw_sess

    def test_full_round_trip_via_legacy_adapter(self):
        """from_legacy → v2 → to_legacy should reproduce compatible payload."""
        from contracts.handoff_envelope_v2 import from_legacy_handoff_contract, to_legacy_bridge_payload
        contract = _make_real_legacy_contract()
        original_payload = contract.to_dict()
        env = from_legacy_handoff_contract(contract)
        reproduced = to_legacy_bridge_payload(env)
        # Core bridge fields must match
        assert reproduced["trace_id"] == original_payload["trace_id"]
        assert reproduced["capability"] == original_payload["capability"]
        assert reproduced["exec_mode"] == original_payload["exec_mode"]
        assert reproduced["route_mode"] == original_payload["route_mode"]
        assert reproduced["callback_channel"] == original_payload["callback_channel"]
        assert reproduced.get("task_id") == original_payload.get("task_id")


# ---------------------------------------------------------------------------
# 7. build_handoff_envelope_v2 factory
# ---------------------------------------------------------------------------

class TestBuildHandoffEnvelopeV2:
    """build_handoff_envelope_v2 convenience factory."""

    def test_basic_construction(self):
        from contracts.handoff_envelope_v2 import build_handoff_envelope_v2
        env = build_handoff_envelope_v2(
            trace_id="build_t1",
            task={"tool_name": "screenshot"},
            capability="screen",
        )
        assert env.trace_id == "build_t1"
        assert env.capability == "screen"
        assert env.task_spec.tool_name == "screenshot"

    def test_device_ids(self):
        from contracts.handoff_envelope_v2 import build_handoff_envelope_v2
        env = build_handoff_envelope_v2(
            trace_id="build_t2",
            task={},
            source_device_id="phone_001",
            target_device_id="tablet_002",
        )
        assert env.source_device_id == "phone_001"
        assert env.target_device_id == "tablet_002"

    def test_agent_spec_populated(self):
        from contracts.handoff_envelope_v2 import build_handoff_envelope_v2
        env = build_handoff_envelope_v2(
            trace_id="build_t3",
            task={},
            agent_id="agent_01",
            agent_type="executor",
            agent_role="primary",
        )
        assert env.agent_spec.agent_id == "agent_01"
        assert env.agent_spec.agent_type == "executor"
        assert env.agent_spec.agent_role == "primary"

    def test_takeover_policy_defaults(self):
        from contracts.handoff_envelope_v2 import build_handoff_envelope_v2
        env = build_handoff_envelope_v2(trace_id="build_t4", task={})
        assert env.takeover_policy.allow_local_takeover is True
        assert env.takeover_policy.require_ack_before_takeover is False

    def test_takeover_policy_overrides(self):
        from contracts.handoff_envelope_v2 import build_handoff_envelope_v2
        env = build_handoff_envelope_v2(
            trace_id="build_t5",
            task={},
            allow_local_takeover=False,
            require_ack_before_takeover=True,
        )
        assert env.takeover_policy.allow_local_takeover is False
        assert env.takeover_policy.require_ack_before_takeover is True

    def test_session_id_forwarded(self):
        from contracts.handoff_envelope_v2 import build_handoff_envelope_v2
        env = build_handoff_envelope_v2(trace_id="build_t6", task={}, session_id="sess_42")
        assert env.session_id == "sess_42"
        assert env.session_context.session_id == "sess_42"

    def test_return_contract_callback_matches(self):
        from contracts.handoff_envelope_v2 import build_handoff_envelope_v2
        env = build_handoff_envelope_v2(
            trace_id="build_t7", task={}, callback_channel="nats"
        )
        assert env.return_contract.callback_channel == "nats"
        assert env.callback_channel == "nats"

    def test_metadata_embedded(self):
        from contracts.handoff_envelope_v2 import build_handoff_envelope_v2
        env = build_handoff_envelope_v2(
            trace_id="build_t8", task={}, metadata={"origin": "test"}
        )
        assert env.metadata["origin"] == "test"

    def test_result_is_json_serialisable(self):
        from contracts.handoff_envelope_v2 import build_handoff_envelope_v2
        env = build_handoff_envelope_v2(
            trace_id="build_t9",
            task={"tool_name": "open_app"},
            source_device_id="phone_001",
            target_device_id="tablet_002",
        )
        json.dumps(env.to_dict())


# ---------------------------------------------------------------------------
# 8. to_compact_summary
# ---------------------------------------------------------------------------

class TestToCompactSummary:
    """to_compact_summary returns a projection-safe compact dict."""

    COMPACT_KEYS = {
        "handoff_id",
        "trace_id",
        "task_id",
        "session_id",
        "source_device_id",
        "target_device_id",
        "source_runtime_id",
        "target_runtime_id",
        "capability",
        "exec_mode",
        "route_mode",
        "callback_channel",
        "schema_version",
        "created_at",
    }

    def test_all_expected_keys_present(self):
        from contracts.handoff_envelope_v2 import HandoffEnvelopeV2
        env = HandoffEnvelopeV2(trace_id="compact_t1")
        summary = env.to_compact_summary()
        missing = self.COMPACT_KEYS - set(summary.keys())
        assert not missing, f"Missing compact keys: {missing}"

    def test_no_task_payload_in_summary(self):
        from contracts.handoff_envelope_v2 import HandoffEnvelopeV2, HandoffTaskSpec
        env = HandoffEnvelopeV2(
            trace_id="compact_t2",
            task_spec=HandoffTaskSpec(raw_task={"tool_name": "secret_tool"}),
        )
        summary = env.to_compact_summary()
        assert "task_spec" not in summary
        assert "raw_task" not in summary

    def test_values_correct(self):
        from contracts.handoff_envelope_v2 import HandoffEnvelopeV2
        env = HandoffEnvelopeV2(
            trace_id="compact_t3",
            source_device_id="phone_001",
            target_device_id="tablet_002",
            capability="screen",
        )
        summary = env.to_compact_summary()
        assert summary["trace_id"] == "compact_t3"
        assert summary["source_device_id"] == "phone_001"
        assert summary["target_device_id"] == "tablet_002"
        assert summary["capability"] == "screen"

    def test_is_json_serialisable(self):
        from contracts.handoff_envelope_v2 import HandoffEnvelopeV2
        env = HandoffEnvelopeV2(trace_id="compact_t4")
        json.dumps(env.to_compact_summary())


# ---------------------------------------------------------------------------
# 9. Graceful handling of partial / missing data
# ---------------------------------------------------------------------------

class TestGracefulPartialData:
    """Adapters handle missing or partial data without raising."""

    def test_from_legacy_with_empty_task(self):
        from contracts.handoff_envelope_v2 import from_legacy_handoff_contract
        contract = _make_legacy_contract(task={}, session={})
        env = from_legacy_handoff_contract(contract)
        assert env.task_spec.tool_name is None
        assert env.task_spec.args == {}
        assert env.task_spec.targets == []

    def test_from_legacy_with_none_task(self):
        from contracts.handoff_envelope_v2 import from_legacy_handoff_contract
        contract = MagicMock()
        contract.trace_id = "t_partial"
        contract.task_id = ""
        contract.task = None
        contract.capability = ""
        contract.exec_mode = "both"
        contract.route_mode = "direct"
        contract.session = None
        contract.callback_channel = "ws"
        # Should not raise
        env = from_legacy_handoff_contract(contract)
        assert env.trace_id == "t_partial"

    def test_from_legacy_with_missing_attributes(self):
        from contracts.handoff_envelope_v2 import from_legacy_handoff_contract
        # Minimal object — only trace_id
        contract = MagicMock(spec=[])
        contract.trace_id = "t_minimal"
        env = from_legacy_handoff_contract(contract)
        assert env.trace_id == "t_minimal"

    def test_build_with_no_task(self):
        from contracts.handoff_envelope_v2 import build_handoff_envelope_v2
        env = build_handoff_envelope_v2(trace_id="partial_build")
        assert env.trace_id == "partial_build"
        assert env.task_spec.tool_name is None

    def test_handoff_envelope_defaults_are_valid(self):
        from contracts.handoff_envelope_v2 import HandoffEnvelopeV2
        env = HandoffEnvelopeV2()
        d = env.to_dict()
        assert d["trace_id"] == ""
        assert d["task_id"] is None
        assert d["source_device_id"] is None
        assert d["target_device_id"] is None

    def test_sub_contracts_have_safe_defaults(self):
        from contracts.handoff_envelope_v2 import HandoffEnvelopeV2
        env = HandoffEnvelopeV2(trace_id="defaults_t")
        assert env.source.device_id is None
        assert env.target.device_id is None
        assert env.agent_spec.agent_id is None
        assert env.task_spec.tool_name is None
        assert env.session_context.session_id is None
        assert env.takeover_policy.allow_local_takeover is True
        assert env.return_contract.callback_channel == "ws"


# ---------------------------------------------------------------------------
# 10. contracts package root re-exports
# ---------------------------------------------------------------------------

class TestContractsPackageExports:
    """All PR-31 types exported from the contracts package root."""

    def test_handoff_envelope_v2_importable(self):
        from contracts import HandoffEnvelopeV2
        assert HandoffEnvelopeV2 is not None

    def test_sub_contracts_importable(self):
        from contracts import (
            HandoffSourceSummary,
            HandoffTargetSummary,
            HandoffAgentSpec,
            HandoffTaskSpec,
            HandoffSessionContext,
            LocalTakeoverPolicy,
            HandoffReturnContract,
        )
        for cls in [HandoffSourceSummary, HandoffTargetSummary, HandoffAgentSpec,
                    HandoffTaskSpec, HandoffSessionContext, LocalTakeoverPolicy,
                    HandoffReturnContract]:
            assert cls is not None

    def test_adapters_importable(self):
        from contracts import (
            from_legacy_handoff_contract,
            from_bridge_inputs,
            to_legacy_bridge_payload,
            build_handoff_envelope_v2,
        )
        for fn in [from_legacy_handoff_contract, from_bridge_inputs,
                   to_legacy_bridge_payload, build_handoff_envelope_v2]:
            assert callable(fn)


# ---------------------------------------------------------------------------
# 11. core.unified package re-exports
# ---------------------------------------------------------------------------

class TestCoreUnifiedExports:
    """All PR-31 types re-exported from core.unified."""

    def test_handoff_envelope_v2_importable(self):
        from core.unified import HandoffEnvelopeV2
        assert HandoffEnvelopeV2 is not None

    def test_sub_contracts_importable(self):
        from core.unified import (
            HandoffSourceSummary,
            HandoffTargetSummary,
            HandoffAgentSpec,
            HandoffTaskSpec,
            HandoffSessionContext,
            LocalTakeoverPolicy,
            HandoffReturnContract,
        )
        for cls in [HandoffSourceSummary, HandoffTargetSummary, HandoffAgentSpec,
                    HandoffTaskSpec, HandoffSessionContext, LocalTakeoverPolicy,
                    HandoffReturnContract]:
            assert cls is not None

    def test_adapters_importable(self):
        from core.unified import (
            from_legacy_handoff_contract,
            from_bridge_inputs,
            to_legacy_bridge_payload,
            build_handoff_envelope_v2,
        )
        for fn in [from_legacy_handoff_contract, from_bridge_inputs,
                   to_legacy_bridge_payload, build_handoff_envelope_v2]:
            assert callable(fn)


# ---------------------------------------------------------------------------
# 12. Bridge integration — result includes handoff_envelope_v2 summary
# ---------------------------------------------------------------------------

class TestBridgeIntegration:
    """AgentBridge.handoff() attaches handoff_envelope_v2 summary to result."""

    @pytest.mark.asyncio
    async def test_successful_handoff_includes_v2_summary(self):
        import os
        from galaxy_gateway.agent_bridge import AgentBridge, AgentBridgeConfig, HandoffContract

        config = AgentBridgeConfig(runtime_url="http://fake:9000", timeout=5.0, enabled=True)
        bridge = AgentBridge(config)

        contract = HandoffContract(
            trace_id="bridge_int_t1",
            task={"tool_name": "screenshot"},
            capability="screen",
        )

        runtime_response = {"success": True, "data": "ok"}

        async def _mock_runtime(c):
            return dict(runtime_response)

        with patch.object(bridge, "_call_runtime", side_effect=_mock_runtime):
            with patch("galaxy_gateway.cross_device_switch.is_cross_device_enabled", return_value=True):
                result = await bridge.handoff(contract=contract)

        assert "handoff_envelope_v2" in result
        summary = result["handoff_envelope_v2"]
        assert summary["trace_id"] == "bridge_int_t1"
        assert summary["schema_version"] == "v2"
        assert summary["capability"] == "screen"

    @pytest.mark.asyncio
    async def test_fallback_handoff_includes_v2_summary(self):
        from galaxy_gateway.agent_bridge import AgentBridge, AgentBridgeConfig, HandoffContract

        config = AgentBridgeConfig(runtime_url="http://fake:9000", timeout=0.01, enabled=True)
        bridge = AgentBridge(config)

        contract = HandoffContract(
            trace_id="bridge_int_t2",
            task={"tool_name": "fallback_task"},
            capability="camera",
        )

        async def _timeout_runtime(c):
            import asyncio
            await asyncio.sleep(10)
            return {}

        async def _local_fb(task):
            return {"success": True, "source": "local"}

        with patch.object(bridge, "_call_runtime", side_effect=_timeout_runtime):
            with patch("galaxy_gateway.cross_device_switch.is_cross_device_enabled", return_value=True):
                result = await bridge.handoff(contract=contract, local_fallback=_local_fb)

        assert "handoff_envelope_v2" in result
        assert result["handoff_envelope_v2"]["trace_id"] == "bridge_int_t2"


# ---------------------------------------------------------------------------
# 13. AgentBridge.build_envelope_v2 helper
# ---------------------------------------------------------------------------

class TestAgentBridgeBuildEnvelopeV2:
    """AgentBridge.build_envelope_v2 returns a populated HandoffEnvelopeV2."""

    def test_returns_envelope_from_legacy_contract(self):
        from galaxy_gateway.agent_bridge import AgentBridge, AgentBridgeConfig, HandoffContract
        from contracts.handoff_envelope_v2 import HandoffEnvelopeV2

        bridge = AgentBridge(AgentBridgeConfig())
        contract = HandoffContract(
            trace_id="bev2_t1",
            task={"tool_name": "screenshot"},
            capability="screen",
        )
        env = bridge.build_envelope_v2(contract)
        assert env is not None
        assert isinstance(env, HandoffEnvelopeV2)
        assert env.trace_id == "bev2_t1"
        assert env.capability == "screen"

    def test_source_device_id_injected(self):
        from galaxy_gateway.agent_bridge import AgentBridge, AgentBridgeConfig, HandoffContract

        bridge = AgentBridge(AgentBridgeConfig())
        contract = HandoffContract(trace_id="bev2_t2", task={})
        env = bridge.build_envelope_v2(contract, source_device_id="phone_001")
        assert env.source_device_id == "phone_001"
        assert env.source.device_id == "phone_001"

    def test_target_device_id_injected(self):
        from galaxy_gateway.agent_bridge import AgentBridge, AgentBridgeConfig, HandoffContract

        bridge = AgentBridge(AgentBridgeConfig())
        contract = HandoffContract(trace_id="bev2_t3", task={})
        env = bridge.build_envelope_v2(contract, target_device_id="tablet_002")
        assert env.target_device_id == "tablet_002"
        assert env.target.device_id == "tablet_002"

    def test_handoff_policy_injected(self):
        from galaxy_gateway.agent_bridge import AgentBridge, AgentBridgeConfig, HandoffContract

        bridge = AgentBridge(AgentBridgeConfig())
        contract = HandoffContract(trace_id="bev2_t4", task={})
        policy = {"ack_required": True, "max_handoff_depth": 2}
        env = bridge.build_envelope_v2(contract, handoff_policy=policy)
        assert env.handoff_policy == policy

    def test_envelope_is_serialisable(self):
        from galaxy_gateway.agent_bridge import AgentBridge, AgentBridgeConfig, HandoffContract

        bridge = AgentBridge(AgentBridgeConfig())
        contract = HandoffContract(
            trace_id="bev2_t5",
            task={"tool_name": "open_app"},
            capability="screen",
        )
        env = bridge.build_envelope_v2(
            contract,
            source_device_id="phone_001",
            target_device_id="tablet_002",
        )
        json.dumps(env.to_dict())


# ---------------------------------------------------------------------------
# 14. Legacy compatibility — additional round-trip checks
# ---------------------------------------------------------------------------

class TestLegacyCompatibility:
    """Extended round-trip compatibility checks."""

    def test_legacy_to_v2_to_legacy_trace_id(self):
        from contracts.handoff_envelope_v2 import from_legacy_handoff_contract, to_legacy_bridge_payload
        contract = _make_real_legacy_contract(trace_id="compat_t1")
        env = from_legacy_handoff_contract(contract)
        payload = to_legacy_bridge_payload(env)
        assert payload["trace_id"] == "compat_t1"

    def test_legacy_to_v2_to_legacy_no_task_id_dropped(self):
        from contracts.handoff_envelope_v2 import from_legacy_handoff_contract, to_legacy_bridge_payload
        contract = _make_legacy_contract(task_id="")
        env = from_legacy_handoff_contract(contract)
        payload = to_legacy_bridge_payload(env)
        assert "task_id" not in payload

    def test_all_exec_modes_preserved(self):
        from contracts.handoff_envelope_v2 import from_legacy_handoff_contract
        for mode in ("local", "remote", "both"):
            contract = _make_legacy_contract(exec_mode=mode)
            env = from_legacy_handoff_contract(contract)
            assert env.exec_mode == mode

    def test_all_callback_channels_preserved(self):
        from contracts.handoff_envelope_v2 import from_legacy_handoff_contract
        for ch in ("ws", "webrtc", "nats", "http"):
            contract = _make_legacy_contract(callback_channel=ch)
            env = from_legacy_handoff_contract(contract)
            assert env.callback_channel == ch
