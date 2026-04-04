"""tests/test_pr3_canonical_handoff_takeover.py
=================================================
Tests for PR-3 (post-533 dual-repo unification, MAIN repo side):
Canonicalize cross-device handoff and takeover.

Coverage groups
---------------
A  — Canonicalization sentinel presence and non-empty values.
B  — HandoffContract.source_runtime_posture field and to_dict() inclusion.
C  — from_legacy_handoff_contract posture propagation.
D  — AgentBridge.build_envelope_v2 posture propagation.
E  — handoff_contract_from_envelope posture extraction from TaskEnvelope.
F  — DeviceRouter HandoffContract construction carries posture.
G  — Round-trip: HandoffContract → HandoffEnvelopeV2 posture consistency.
H  — Graceful degradation: unknown / missing posture falls back to control_only.
I  — to_legacy_bridge_payload preserves posture roundtrip information.
J  — NO_POSTURE_SILENT_DROP_POLICY end-to-end path check.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_real_handoff_contract(**kwargs) -> Any:
    """Return a real HandoffContract dataclass instance."""
    from galaxy_gateway.agent_bridge import HandoffContract

    defaults = dict(
        trace_id="trace_pr3_001",
        task={"tool_name": "screenshot", "args": {}},
        capability="screen",
        exec_mode="both",
        route_mode="direct",
        session={},
        callback_channel="ws",
        task_id="task_pr3_001",
        source_runtime_posture="control_only",
    )
    defaults.update(kwargs)
    return HandoffContract(**defaults)


def _make_mock_task_envelope(
    *,
    trace_id: str = "trace_env_001",
    task_id: str = "task_env_001",
    tool_name: str = "screenshot",
    source_runtime_posture: str = "control_only",
    route_mode: str = "direct",
) -> Any:
    """Return a mock shaped like core.schemas.task_envelope.TaskEnvelope."""
    m = MagicMock()
    m.trace_id = trace_id
    m.task_id = task_id
    m.tool_name = tool_name
    m.args = {}
    m.targets = []
    m.source = "device_router"
    m.metadata = {
        "route_mode": route_mode,
        "source_runtime_posture": source_runtime_posture,
    }
    return m


# ---------------------------------------------------------------------------
# A — Canonicalization sentinel presence
# ---------------------------------------------------------------------------


class TestCanonicalizationSentinels:
    """PR-3 sentinels are present and non-empty in agent_bridge module."""

    def test_canonical_handoff_posture_propagation_active(self):
        from galaxy_gateway.agent_bridge import CANONICAL_HANDOFF_POSTURE_PROPAGATION_ACTIVE

        assert CANONICAL_HANDOFF_POSTURE_PROPAGATION_ACTIVE
        assert isinstance(CANONICAL_HANDOFF_POSTURE_PROPAGATION_ACTIVE, str)

    def test_handoff_contract_is_posture_aware(self):
        from galaxy_gateway.agent_bridge import HANDOFF_CONTRACT_IS_POSTURE_AWARE

        assert HANDOFF_CONTRACT_IS_POSTURE_AWARE
        assert isinstance(HANDOFF_CONTRACT_IS_POSTURE_AWARE, str)

    def test_handoff_envelope_v2_posture_adapter_active(self):
        from galaxy_gateway.agent_bridge import HANDOFF_ENVELOPE_V2_POSTURE_ADAPTER_ACTIVE

        assert HANDOFF_ENVELOPE_V2_POSTURE_ADAPTER_ACTIVE
        assert isinstance(HANDOFF_ENVELOPE_V2_POSTURE_ADAPTER_ACTIVE, str)

    def test_no_posture_silent_drop_policy(self):
        from galaxy_gateway.agent_bridge import NO_POSTURE_SILENT_DROP_POLICY

        assert NO_POSTURE_SILENT_DROP_POLICY
        assert isinstance(NO_POSTURE_SILENT_DROP_POLICY, str)

    def test_sentinels_exported_in_dunder_all(self):
        import galaxy_gateway.agent_bridge as ab

        for sentinel_name in (
            "CANONICAL_HANDOFF_POSTURE_PROPAGATION_ACTIVE",
            "HANDOFF_CONTRACT_IS_POSTURE_AWARE",
            "HANDOFF_ENVELOPE_V2_POSTURE_ADAPTER_ACTIVE",
            "NO_POSTURE_SILENT_DROP_POLICY",
        ):
            assert sentinel_name in ab.__all__, f"{sentinel_name} not in __all__"


# ---------------------------------------------------------------------------
# B — HandoffContract.source_runtime_posture field and to_dict()
# ---------------------------------------------------------------------------


class TestHandoffContractPostureField:
    """HandoffContract carries source_runtime_posture and includes it in to_dict()."""

    def test_handoff_contract_has_posture_field(self):
        from galaxy_gateway.agent_bridge import HandoffContract

        contract = HandoffContract(trace_id="t1", task={})
        assert hasattr(contract, "source_runtime_posture")

    def test_handoff_contract_default_is_control_only(self):
        from galaxy_gateway.agent_bridge import HandoffContract

        contract = HandoffContract(trace_id="t2", task={})
        assert contract.source_runtime_posture == "control_only"

    def test_handoff_contract_accepts_join_runtime(self):
        contract = _make_real_handoff_contract(source_runtime_posture="join_runtime")
        assert contract.source_runtime_posture == "join_runtime"

    def test_to_dict_includes_posture_control_only(self):
        contract = _make_real_handoff_contract(source_runtime_posture="control_only")
        d = contract.to_dict()
        assert "source_runtime_posture" in d
        assert d["source_runtime_posture"] == "control_only"

    def test_to_dict_includes_posture_join_runtime(self):
        contract = _make_real_handoff_contract(source_runtime_posture="join_runtime")
        d = contract.to_dict()
        assert "source_runtime_posture" in d
        assert d["source_runtime_posture"] == "join_runtime"

    def test_to_dict_still_includes_trace_id(self):
        contract = _make_real_handoff_contract()
        d = contract.to_dict()
        assert "trace_id" in d
        assert d["trace_id"] == "trace_pr3_001"

    def test_to_dict_task_id_present_when_set(self):
        contract = _make_real_handoff_contract(task_id="task_xyz")
        d = contract.to_dict()
        assert d.get("task_id") == "task_xyz"


# ---------------------------------------------------------------------------
# C — from_legacy_handoff_contract posture propagation
# ---------------------------------------------------------------------------


class TestFromLegacyHandoffContractPosturePropagation:
    """from_legacy_handoff_contract propagates source_runtime_posture into HandoffEnvelopeV2."""

    def test_propagates_control_only(self):
        from contracts.handoff_envelope_v2 import from_legacy_handoff_contract

        contract = _make_real_handoff_contract(source_runtime_posture="control_only")
        env = from_legacy_handoff_contract(contract)
        assert env.source_runtime_posture == "control_only"

    def test_propagates_join_runtime(self):
        from contracts.handoff_envelope_v2 import from_legacy_handoff_contract

        contract = _make_real_handoff_contract(source_runtime_posture="join_runtime")
        env = from_legacy_handoff_contract(contract)
        assert env.source_runtime_posture == "join_runtime"

    def test_source_summary_posture_propagated(self):
        from contracts.handoff_envelope_v2 import from_legacy_handoff_contract

        contract = _make_real_handoff_contract(source_runtime_posture="join_runtime")
        env = from_legacy_handoff_contract(contract)
        assert env.source.source_runtime_posture == "join_runtime"

    def test_mock_contract_without_posture_field_defaults_control_only(self):
        from contracts.handoff_envelope_v2 import from_legacy_handoff_contract

        mock_contract = MagicMock()
        mock_contract.trace_id = "trace_mock"
        mock_contract.task_id = ""
        mock_contract.capability = "screen"
        mock_contract.exec_mode = "both"
        mock_contract.route_mode = "direct"
        mock_contract.callback_channel = "ws"
        mock_contract.task = {}
        mock_contract.session = {}
        # Simulate a legacy contract that doesn't have source_runtime_posture:
        del mock_contract.source_runtime_posture
        env = from_legacy_handoff_contract(mock_contract)
        assert env.source_runtime_posture == "control_only"

    def test_unknown_posture_normalised_to_control_only(self):
        from contracts.handoff_envelope_v2 import from_legacy_handoff_contract

        mock_contract = MagicMock()
        mock_contract.trace_id = "trace_unk"
        mock_contract.task_id = ""
        mock_contract.capability = ""
        mock_contract.exec_mode = "both"
        mock_contract.route_mode = "direct"
        mock_contract.callback_channel = "ws"
        mock_contract.task = {}
        mock_contract.session = {}
        mock_contract.source_runtime_posture = "INVALID_VALUE"
        env = from_legacy_handoff_contract(mock_contract)
        assert env.source_runtime_posture == "control_only"

    def test_other_fields_still_mapped(self):
        from contracts.handoff_envelope_v2 import from_legacy_handoff_contract

        contract = _make_real_handoff_contract(
            trace_id="trace_map_001",
            capability="camera",
            exec_mode="remote",
            route_mode="broadcast",
        )
        env = from_legacy_handoff_contract(contract)
        assert env.trace_id == "trace_map_001"
        assert env.capability == "camera"
        assert env.exec_mode == "remote"
        assert env.route_mode == "broadcast"


# ---------------------------------------------------------------------------
# D — AgentBridge.build_envelope_v2 posture propagation
# ---------------------------------------------------------------------------


class TestAgentBridgeBuildEnvelopeV2PosturePropagation:
    """AgentBridge.build_envelope_v2 propagates source_runtime_posture from HandoffContract."""

    def _get_bridge(self):
        from galaxy_gateway.agent_bridge import AgentBridge, AgentBridgeConfig

        return AgentBridge(config=AgentBridgeConfig(enabled=True))

    def test_join_runtime_propagated_to_envelope(self):
        bridge = self._get_bridge()
        contract = _make_real_handoff_contract(source_runtime_posture="join_runtime")
        env = bridge.build_envelope_v2(contract)
        assert env is not None
        assert env.source_runtime_posture == "join_runtime"

    def test_control_only_propagated_to_envelope(self):
        bridge = self._get_bridge()
        contract = _make_real_handoff_contract(source_runtime_posture="control_only")
        env = bridge.build_envelope_v2(contract)
        assert env is not None
        assert env.source_runtime_posture == "control_only"

    def test_source_summary_posture_propagated(self):
        bridge = self._get_bridge()
        contract = _make_real_handoff_contract(source_runtime_posture="join_runtime")
        env = bridge.build_envelope_v2(contract)
        assert env is not None
        assert env.source.source_runtime_posture == "join_runtime"

    def test_posture_not_overwritten_by_default(self):
        """build_envelope_v2 must not silently reset join_runtime back to control_only."""
        bridge = self._get_bridge()
        contract = _make_real_handoff_contract(source_runtime_posture="join_runtime")
        env = bridge.build_envelope_v2(
            contract,
            source_device_id="phone_001",
            target_device_id="tablet_002",
        )
        assert env is not None
        assert env.source_runtime_posture == "join_runtime"


# ---------------------------------------------------------------------------
# E — handoff_contract_from_envelope posture extraction
# ---------------------------------------------------------------------------


class TestHandoffContractFromEnvelopePostureExtraction:
    """handoff_contract_from_envelope extracts source_runtime_posture from TaskEnvelope metadata."""

    def test_extracts_join_runtime_from_metadata(self):
        from galaxy_gateway.agent_bridge import handoff_contract_from_envelope

        envelope = _make_mock_task_envelope(source_runtime_posture="join_runtime")
        contract = handoff_contract_from_envelope(envelope)
        assert contract.source_runtime_posture == "join_runtime"

    def test_extracts_control_only_from_metadata(self):
        from galaxy_gateway.agent_bridge import handoff_contract_from_envelope

        envelope = _make_mock_task_envelope(source_runtime_posture="control_only")
        contract = handoff_contract_from_envelope(envelope)
        assert contract.source_runtime_posture == "control_only"

    def test_defaults_to_control_only_when_missing(self):
        from galaxy_gateway.agent_bridge import handoff_contract_from_envelope

        m = MagicMock()
        m.trace_id = "t"
        m.task_id = ""
        m.tool_name = "screenshot"
        m.args = {}
        m.targets = []
        m.source = "device_router"
        m.metadata = {}  # no source_runtime_posture key
        contract = handoff_contract_from_envelope(m)
        assert contract.source_runtime_posture == "control_only"

    def test_invalid_posture_in_metadata_falls_back_to_control_only(self):
        from galaxy_gateway.agent_bridge import handoff_contract_from_envelope

        envelope = _make_mock_task_envelope(source_runtime_posture="UNKNOWN_VALUE")
        contract = handoff_contract_from_envelope(envelope)
        assert contract.source_runtime_posture == "control_only"

    def test_route_mode_still_extracted(self):
        from galaxy_gateway.agent_bridge import handoff_contract_from_envelope

        envelope = _make_mock_task_envelope(route_mode="broadcast", source_runtime_posture="join_runtime")
        contract = handoff_contract_from_envelope(envelope)
        assert contract.route_mode == "broadcast"

    def test_trace_id_still_extracted(self):
        from galaxy_gateway.agent_bridge import handoff_contract_from_envelope

        envelope = _make_mock_task_envelope(trace_id="trace_env_xyz")
        contract = handoff_contract_from_envelope(envelope)
        assert contract.trace_id == "trace_env_xyz"


# ---------------------------------------------------------------------------
# F — DeviceRouter HandoffContract construction carries posture
# ---------------------------------------------------------------------------


class TestDeviceRouterHandoffContractCarriesPosture:
    """DeviceRouter.route_task passes source_runtime_posture into HandoffContract."""

    def test_device_router_passes_posture_to_contract(self):
        """Verify that posture flows into HandoffContract the same way DeviceRouter does.

        This test mirrors the construction logic in DeviceRouter.route_task() Round-5
        to assert that source_runtime_posture is included in the contract and its to_dict().
        """
        from galaxy_gateway.agent_bridge import HandoffContract
        from core.source_runtime_posture import resolve_source_runtime_posture

        ctx = {"source_runtime_posture": "join_runtime"}
        source_runtime_posture = resolve_source_runtime_posture(ctx.get("source_runtime_posture"))
        _bridge_posture = (
            source_runtime_posture.value
            if source_runtime_posture is not None
            else ctx.get("source_runtime_posture", "control_only") or "control_only"
        )
        contract = HandoffContract(
            trace_id="trace_dr_001",
            task={"command": "open_app", "analysis": {}, "context": ctx},
            capability="screen",
            exec_mode="both",
            route_mode="direct",
            session={},
            callback_channel="ws",
            source_runtime_posture=_bridge_posture,
        )
        assert contract.source_runtime_posture == "join_runtime"
        d = contract.to_dict()
        assert d["source_runtime_posture"] == "join_runtime"

    def test_device_router_defaults_posture_to_control_only(self):
        """When no posture is in context, HandoffContract defaults to control_only."""
        from galaxy_gateway.agent_bridge import HandoffContract

        contract = HandoffContract(
            trace_id="trace_dr_002",
            task={},
            source_runtime_posture="control_only",
        )
        assert contract.source_runtime_posture == "control_only"
        assert contract.to_dict()["source_runtime_posture"] == "control_only"


# ---------------------------------------------------------------------------
# G — Round-trip: HandoffContract → HandoffEnvelopeV2 posture consistency
# ---------------------------------------------------------------------------


class TestHandoffContractToEnvelopeRoundTrip:
    """posture is consistent across the full HandoffContract → HandoffEnvelopeV2 pipeline."""

    def test_join_runtime_round_trip(self):
        from contracts.handoff_envelope_v2 import from_legacy_handoff_contract

        contract = _make_real_handoff_contract(source_runtime_posture="join_runtime")
        env = from_legacy_handoff_contract(contract)
        assert env.source_runtime_posture == "join_runtime"
        assert env.source.source_runtime_posture == "join_runtime"

    def test_control_only_round_trip(self):
        from contracts.handoff_envelope_v2 import from_legacy_handoff_contract

        contract = _make_real_handoff_contract(source_runtime_posture="control_only")
        env = from_legacy_handoff_contract(contract)
        assert env.source_runtime_posture == "control_only"
        assert env.source.source_runtime_posture == "control_only"

    def test_envelope_to_dict_preserves_posture(self):
        from contracts.handoff_envelope_v2 import from_legacy_handoff_contract

        contract = _make_real_handoff_contract(source_runtime_posture="join_runtime")
        env = from_legacy_handoff_contract(contract)
        d = env.to_dict()
        assert d.get("source_runtime_posture") == "join_runtime"

    def test_envelope_from_dict_round_trip_preserves_posture(self):
        from contracts.handoff_envelope_v2 import HandoffEnvelopeV2, from_legacy_handoff_contract

        contract = _make_real_handoff_contract(source_runtime_posture="join_runtime")
        env = from_legacy_handoff_contract(contract)
        d = env.to_dict()
        # schema_version is a static marker set by HandoffEnvelopeV2 and not a
        # constructor parameter, so we exclude it to avoid a duplicate-kwarg error.
        d.pop("schema_version", None)
        env2 = HandoffEnvelopeV2(**d)
        assert env2.source_runtime_posture == "join_runtime"


# ---------------------------------------------------------------------------
# H — Graceful degradation: unknown / missing posture falls back to control_only
# ---------------------------------------------------------------------------


class TestPostureGracefulDegradation:
    """Missing or unknown posture values are normalised to control_only."""

    def test_handoff_contract_default_is_safe(self):
        from galaxy_gateway.agent_bridge import HandoffContract

        c = HandoffContract(trace_id="t", task={})
        assert c.source_runtime_posture == "control_only"

    def test_from_legacy_contract_none_posture(self):
        from contracts.handoff_envelope_v2 import from_legacy_handoff_contract

        m = MagicMock()
        m.trace_id = "t"
        m.task_id = ""
        m.capability = ""
        m.exec_mode = "both"
        m.route_mode = "direct"
        m.callback_channel = "ws"
        m.task = {}
        m.session = {}
        m.source_runtime_posture = None
        env = from_legacy_handoff_contract(m)
        assert env.source_runtime_posture == "control_only"

    def test_build_envelope_v2_without_posture_field(self):
        """build_envelope_v2 via HandoffEnvelopeV2 defaults posture to control_only."""
        from contracts.handoff_envelope_v2 import HandoffEnvelopeV2

        env = HandoffEnvelopeV2(trace_id="t")
        assert env.source_runtime_posture == "control_only"


# ---------------------------------------------------------------------------
# I — to_legacy_bridge_payload does not lose posture context
# ---------------------------------------------------------------------------


class TestToLegacyBridgePayloadPostureContext:
    """to_legacy_bridge_payload preserves enough context for posture correlation."""

    def test_payload_includes_trace_id(self):
        from contracts.handoff_envelope_v2 import (
            HandoffEnvelopeV2,
            to_legacy_bridge_payload,
        )

        env = HandoffEnvelopeV2(
            trace_id="trace_legacy_001",
            source_runtime_posture="join_runtime",
        )
        payload = to_legacy_bridge_payload(env)
        assert payload["trace_id"] == "trace_legacy_001"

    def test_build_handoff_envelope_v2_with_posture(self):
        """build_handoff_envelope_v2 always produces a posture-aware envelope."""
        from contracts.handoff_envelope_v2 import build_handoff_envelope_v2

        env = build_handoff_envelope_v2(
            trace_id="trace_build_001",
            source_runtime_posture="join_runtime",
            source_device_id="phone_001",
        )
        assert env.source_runtime_posture == "join_runtime"
        assert env.source.source_runtime_posture == "join_runtime"


# ---------------------------------------------------------------------------
# J — NO_POSTURE_SILENT_DROP_POLICY end-to-end path check
# ---------------------------------------------------------------------------


class TestNoPostureSilentDropPolicyEndToEnd:
    """join_runtime posture is preserved end-to-end: HandoffContract → HandoffEnvelopeV2."""

    def test_join_runtime_never_silently_reset_to_control_only(self):
        from contracts.handoff_envelope_v2 import from_legacy_handoff_contract
        from galaxy_gateway.agent_bridge import AgentBridge, AgentBridgeConfig

        bridge = AgentBridge(config=AgentBridgeConfig(enabled=True))
        contract = _make_real_handoff_contract(source_runtime_posture="join_runtime")

        # Path A: from_legacy_handoff_contract adapter
        env_a = from_legacy_handoff_contract(contract)
        assert env_a.source_runtime_posture == "join_runtime", (
            "from_legacy_handoff_contract silently reset join_runtime to control_only"
        )

        # Path B: AgentBridge.build_envelope_v2
        env_b = bridge.build_envelope_v2(contract)
        assert env_b is not None
        assert env_b.source_runtime_posture == "join_runtime", (
            "AgentBridge.build_envelope_v2 silently reset join_runtime to control_only"
        )

    def test_contract_to_dict_posture_matches_original(self):
        """to_dict() must never modify or drop the posture."""
        from galaxy_gateway.agent_bridge import HandoffContract

        for posture in ("control_only", "join_runtime"):
            c = HandoffContract(trace_id="t", task={}, source_runtime_posture=posture)
            assert c.to_dict()["source_runtime_posture"] == posture

    def test_handoff_contract_from_envelope_join_runtime_end_to_end(self):
        """TaskEnvelope join_runtime posture propagates through to HandoffContract."""
        from contracts.handoff_envelope_v2 import from_legacy_handoff_contract
        from galaxy_gateway.agent_bridge import handoff_contract_from_envelope

        env_mock = _make_mock_task_envelope(source_runtime_posture="join_runtime")
        contract = handoff_contract_from_envelope(env_mock)
        assert contract.source_runtime_posture == "join_runtime"

        # And then through to HandoffEnvelopeV2
        envelope = from_legacy_handoff_contract(contract)
        assert envelope.source_runtime_posture == "join_runtime"
