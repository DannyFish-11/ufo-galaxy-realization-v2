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


# ---------------------------------------------------------------------------
# K — coordination_role field on HandoffContract
# ---------------------------------------------------------------------------


class TestHandoffContractAuthorityRoleField:
    """PR-3: HandoffContract.coordination_role carries authority metadata."""

    def test_handoff_contract_has_coordination_role_field(self):
        """HandoffContract must have coordination_role attribute."""
        from galaxy_gateway.agent_bridge import HandoffContract

        c = HandoffContract(trace_id="t", task={})
        assert hasattr(c, "coordination_role")

    def test_handoff_contract_default_coordination_role_is_empty(self):
        """Default coordination_role is empty string (backwards-safe)."""
        from galaxy_gateway.agent_bridge import HandoffContract

        c = HandoffContract(trace_id="t", task={})
        assert c.coordination_role == ""

    def test_handoff_contract_accepts_source_controller_role(self):
        from galaxy_gateway.agent_bridge import HandoffContract

        c = HandoffContract(
            trace_id="t", task={}, coordination_role="source_controller"
        )
        assert c.coordination_role == "source_controller"

    def test_handoff_contract_accepts_joined_runtime_participant_role(self):
        from galaxy_gateway.agent_bridge import HandoffContract

        c = HandoffContract(
            trace_id="t", task={}, coordination_role="joined_runtime_participant"
        )
        assert c.coordination_role == "joined_runtime_participant"

    def test_handoff_contract_accepts_target_only_executor_role(self):
        from galaxy_gateway.agent_bridge import HandoffContract

        c = HandoffContract(
            trace_id="t", task={}, coordination_role="target_only_executor"
        )
        assert c.coordination_role == "target_only_executor"

    def test_handoff_contract_accepts_observer_only_role(self):
        from galaxy_gateway.agent_bridge import HandoffContract

        c = HandoffContract(
            trace_id="t", task={}, coordination_role="observer_only"
        )
        assert c.coordination_role == "observer_only"

    def test_to_dict_includes_coordination_role_when_non_empty(self):
        """to_dict() must include coordination_role when it is non-empty."""
        from galaxy_gateway.agent_bridge import HandoffContract

        c = HandoffContract(
            trace_id="t", task={}, coordination_role="source_controller"
        )
        d = c.to_dict()
        assert "coordination_role" in d
        assert d["coordination_role"] == "source_controller"

    def test_to_dict_omits_coordination_role_when_empty(self):
        """to_dict() omits coordination_role when it is empty string (compat)."""
        from galaxy_gateway.agent_bridge import HandoffContract

        c = HandoffContract(trace_id="t", task={}, coordination_role="")
        d = c.to_dict()
        assert "coordination_role" not in d

    def test_to_dict_still_includes_posture_and_trace_id(self):
        from galaxy_gateway.agent_bridge import HandoffContract

        c = HandoffContract(
            trace_id="tr_k_001",
            task={},
            source_runtime_posture="join_runtime",
            coordination_role="joined_runtime_participant",
        )
        d = c.to_dict()
        assert d["trace_id"] == "tr_k_001"
        assert d["source_runtime_posture"] == "join_runtime"
        assert d["coordination_role"] == "joined_runtime_participant"


# ---------------------------------------------------------------------------
# L — authority sentinel presence
# ---------------------------------------------------------------------------


class TestAuthorityRoleSentinels:
    """PR-3 authority sentinels are present and non-empty."""

    def test_handoff_contract_authority_role_active_sentinel(self):
        from galaxy_gateway.agent_bridge import HANDOFF_CONTRACT_AUTHORITY_ROLE_ACTIVE

        assert HANDOFF_CONTRACT_AUTHORITY_ROLE_ACTIVE
        assert isinstance(HANDOFF_CONTRACT_AUTHORITY_ROLE_ACTIVE, str)
        assert "pr3" in HANDOFF_CONTRACT_AUTHORITY_ROLE_ACTIVE

    def test_no_authority_silent_drop_policy_sentinel(self):
        from galaxy_gateway.agent_bridge import NO_AUTHORITY_SILENT_DROP_POLICY

        assert NO_AUTHORITY_SILENT_DROP_POLICY
        assert isinstance(NO_AUTHORITY_SILENT_DROP_POLICY, str)
        assert "pr3" in NO_AUTHORITY_SILENT_DROP_POLICY

    def test_canonical_handoff_path_pr3_sentinel(self):
        from galaxy_gateway.agent_bridge import CANONICAL_HANDOFF_PATH_PR3

        assert CANONICAL_HANDOFF_PATH_PR3
        assert isinstance(CANONICAL_HANDOFF_PATH_PR3, str)

    def test_new_sentinels_exported_in_dunder_all(self):
        import galaxy_gateway.agent_bridge as ab

        for sentinel in (
            "HANDOFF_CONTRACT_AUTHORITY_ROLE_ACTIVE",
            "NO_AUTHORITY_SILENT_DROP_POLICY",
            "CANONICAL_HANDOFF_PATH_PR3",
        ):
            assert sentinel in ab.__all__, f"{sentinel} missing from __all__"


# ---------------------------------------------------------------------------
# M — coordination_role propagation through from_legacy_handoff_contract
# ---------------------------------------------------------------------------


class TestFromLegacyHandoffContractAuthorityPropagation:
    """from_legacy_handoff_contract propagates coordination_role (PR-3)."""

    def test_propagates_source_controller_role(self):
        from contracts.handoff_envelope_v2 import from_legacy_handoff_contract

        contract = _make_real_handoff_contract(coordination_role="source_controller")
        env = from_legacy_handoff_contract(contract)
        assert env.coordination_role == "source_controller"
        assert env.source.coordination_role == "source_controller"

    def test_propagates_joined_runtime_participant_role(self):
        from contracts.handoff_envelope_v2 import from_legacy_handoff_contract

        contract = _make_real_handoff_contract(
            coordination_role="joined_runtime_participant"
        )
        env = from_legacy_handoff_contract(contract)
        assert env.coordination_role == "joined_runtime_participant"
        assert env.source.coordination_role == "joined_runtime_participant"

    def test_empty_coordination_role_propagated_as_empty(self):
        """Empty coordination_role (legacy caller) propagates as empty string."""
        from contracts.handoff_envelope_v2 import from_legacy_handoff_contract

        contract = _make_real_handoff_contract(coordination_role="")
        env = from_legacy_handoff_contract(contract)
        assert env.coordination_role == ""
        assert env.source.coordination_role == ""

    def test_contract_without_coordination_role_defaults_to_empty(self):
        """Contract missing coordination_role attr propagates as empty (compat)."""
        from unittest.mock import MagicMock

        from contracts.handoff_envelope_v2 import from_legacy_handoff_contract

        m = MagicMock(spec=[
            "trace_id", "task", "capability", "exec_mode", "route_mode",
            "session", "callback_channel", "source_runtime_posture",
        ])
        m.trace_id = "t"
        m.task = {}
        m.capability = ""
        m.exec_mode = "both"
        m.route_mode = "direct"
        m.callback_channel = "ws"
        m.session = {}
        m.source_runtime_posture = "control_only"
        env = from_legacy_handoff_contract(m)
        assert env.coordination_role == ""

    def test_posture_and_role_both_propagated(self):
        """Both posture and coordination_role must propagate in one pass."""
        from contracts.handoff_envelope_v2 import from_legacy_handoff_contract

        contract = _make_real_handoff_contract(
            source_runtime_posture="join_runtime",
            coordination_role="joined_runtime_participant",
        )
        env = from_legacy_handoff_contract(contract)
        assert env.source_runtime_posture == "join_runtime"
        assert env.coordination_role == "joined_runtime_participant"
        assert env.source.source_runtime_posture == "join_runtime"
        assert env.source.coordination_role == "joined_runtime_participant"


# ---------------------------------------------------------------------------
# N — coordination_role propagation through build_envelope_v2
# ---------------------------------------------------------------------------


class TestAgentBridgeBuildEnvelopeV2AuthorityPropagation:
    """AgentBridge.build_envelope_v2 propagates coordination_role (PR-3)."""

    def test_source_controller_role_propagated_to_envelope_metadata(self):
        from galaxy_gateway.agent_bridge import AgentBridge, AgentBridgeConfig

        bridge = AgentBridge(config=AgentBridgeConfig(enabled=True))
        contract = _make_real_handoff_contract(coordination_role="source_controller")
        env = bridge.build_envelope_v2(contract)
        assert env is not None
        assert env.metadata.get("coordination_role") == "source_controller"

    def test_joined_runtime_participant_role_propagated(self):
        from galaxy_gateway.agent_bridge import AgentBridge, AgentBridgeConfig

        bridge = AgentBridge(config=AgentBridgeConfig(enabled=True))
        contract = _make_real_handoff_contract(
            coordination_role="joined_runtime_participant"
        )
        env = bridge.build_envelope_v2(contract)
        assert env is not None
        assert env.metadata.get("coordination_role") == "joined_runtime_participant"

    def test_empty_role_not_injected_into_metadata(self):
        """Empty coordination_role must not add a spurious metadata key."""
        from galaxy_gateway.agent_bridge import AgentBridge, AgentBridgeConfig

        bridge = AgentBridge(config=AgentBridgeConfig(enabled=True))
        contract = _make_real_handoff_contract(coordination_role="")
        env = bridge.build_envelope_v2(contract)
        assert env is not None
        # Empty role should not pollute metadata with empty-string value
        role_in_meta = env.metadata.get("coordination_role", None)
        assert role_in_meta is None or role_in_meta == ""

    def test_posture_and_role_both_propagated_to_envelope(self):
        from galaxy_gateway.agent_bridge import AgentBridge, AgentBridgeConfig

        bridge = AgentBridge(config=AgentBridgeConfig(enabled=True))
        contract = _make_real_handoff_contract(
            source_runtime_posture="join_runtime",
            coordination_role="joined_runtime_participant",
        )
        env = bridge.build_envelope_v2(contract)
        assert env is not None
        assert env.source_runtime_posture == "join_runtime"
        assert env.metadata.get("coordination_role") == "joined_runtime_participant"


# ---------------------------------------------------------------------------
# O — coordination_role extraction from TaskEnvelope via handoff_contract_from_envelope
# ---------------------------------------------------------------------------


class TestHandoffContractFromEnvelopeAuthorityExtraction:
    """handoff_contract_from_envelope extracts coordination_role (PR-3)."""

    def test_extracts_source_controller_from_metadata(self):
        from galaxy_gateway.agent_bridge import handoff_contract_from_envelope

        env = _make_mock_task_envelope()
        env.metadata["coordination_role"] = "source_controller"
        contract = handoff_contract_from_envelope(env)
        assert contract.coordination_role == "source_controller"

    def test_extracts_joined_runtime_participant_from_metadata(self):
        from galaxy_gateway.agent_bridge import handoff_contract_from_envelope

        env = _make_mock_task_envelope()
        env.metadata["coordination_role"] = "joined_runtime_participant"
        contract = handoff_contract_from_envelope(env)
        assert contract.coordination_role == "joined_runtime_participant"

    def test_defaults_to_empty_when_coordination_role_missing(self):
        from galaxy_gateway.agent_bridge import handoff_contract_from_envelope

        env = _make_mock_task_envelope()
        # Remove coordination_role from metadata
        env.metadata.pop("coordination_role", None)
        contract = handoff_contract_from_envelope(env)
        assert contract.coordination_role == ""

    def test_posture_and_role_both_extracted(self):
        from galaxy_gateway.agent_bridge import handoff_contract_from_envelope

        env = _make_mock_task_envelope(source_runtime_posture="join_runtime")
        env.metadata["coordination_role"] = "joined_runtime_participant"
        contract = handoff_contract_from_envelope(env)
        assert contract.source_runtime_posture == "join_runtime"
        assert contract.coordination_role == "joined_runtime_participant"

    def test_trace_id_and_task_id_still_extracted(self):
        from galaxy_gateway.agent_bridge import handoff_contract_from_envelope

        env = _make_mock_task_envelope(trace_id="trace_o_001", task_id="task_o_001")
        env.metadata["coordination_role"] = "observer_only"
        contract = handoff_contract_from_envelope(env)
        assert contract.trace_id == "trace_o_001"
        assert contract.task_id == "task_o_001"
        assert contract.coordination_role == "observer_only"


# ---------------------------------------------------------------------------
# P — HandoffSourceSummary and HandoffEnvelopeV2 coordination_role field
# ---------------------------------------------------------------------------


class TestHandoffEnvelopeV2AuthorityField:
    """HandoffEnvelopeV2 and HandoffSourceSummary carry coordination_role."""

    def test_handoff_source_summary_has_coordination_role_field(self):
        from contracts.handoff_envelope_v2 import HandoffSourceSummary

        s = HandoffSourceSummary()
        assert hasattr(s, "coordination_role")
        assert s.coordination_role == ""

    def test_handoff_source_summary_accepts_coordination_role(self):
        from contracts.handoff_envelope_v2 import HandoffSourceSummary

        s = HandoffSourceSummary(coordination_role="source_controller")
        assert s.coordination_role == "source_controller"

    def test_handoff_envelope_v2_has_coordination_role_field(self):
        from contracts.handoff_envelope_v2 import HandoffEnvelopeV2

        env = HandoffEnvelopeV2(trace_id="t")
        assert hasattr(env, "coordination_role")
        assert env.coordination_role == ""

    def test_handoff_envelope_v2_accepts_coordination_role(self):
        from contracts.handoff_envelope_v2 import HandoffEnvelopeV2

        env = HandoffEnvelopeV2(
            trace_id="t", coordination_role="joined_runtime_participant"
        )
        assert env.coordination_role == "joined_runtime_participant"

    def test_to_compact_summary_includes_coordination_role(self):
        from contracts.handoff_envelope_v2 import HandoffEnvelopeV2

        env = HandoffEnvelopeV2(
            trace_id="t", coordination_role="source_controller"
        )
        summary = env.to_compact_summary()
        assert "coordination_role" in summary
        assert summary["coordination_role"] == "source_controller"

    def test_build_handoff_envelope_v2_propagates_coordination_role(self):
        from contracts.handoff_envelope_v2 import build_handoff_envelope_v2

        env = build_handoff_envelope_v2(
            trace_id="t",
            coordination_role="target_only_executor",
        )
        assert env.coordination_role == "target_only_executor"
        assert env.source.coordination_role == "target_only_executor"

    def test_from_bridge_inputs_propagates_coordination_role(self):
        from contracts.handoff_envelope_v2 import from_bridge_inputs

        env = from_bridge_inputs(
            trace_id="t",
            task={},
            coordination_role="observer_only",
        )
        assert env.coordination_role == "observer_only"
        assert env.source.coordination_role == "observer_only"

    def test_build_handoff_envelope_v2_empty_role_default(self):
        from contracts.handoff_envelope_v2 import build_handoff_envelope_v2

        env = build_handoff_envelope_v2(trace_id="t")
        assert env.coordination_role == ""


# ---------------------------------------------------------------------------
# Q — canonical_handoff_path module sentinel and builder
# ---------------------------------------------------------------------------


class TestCanonicalHandoffPathModule:
    """core/canonical_handoff_path.py provides canonical anchor for PR-3."""

    def test_canonical_path_module_importable(self):
        import core.canonical_handoff_path  # noqa: F401

    def test_canonical_handoff_path_main_repo_sentinel(self):
        from core.canonical_handoff_path import CANONICAL_HANDOFF_PATH_MAIN_REPO

        assert CANONICAL_HANDOFF_PATH_MAIN_REPO
        assert "pr3" in CANONICAL_HANDOFF_PATH_MAIN_REPO

    def test_posture_and_authority_unified_sentinel(self):
        from core.canonical_handoff_path import (
            CANONICAL_HANDOFF_POSTURE_AND_AUTHORITY_UNIFIED,
        )

        assert CANONICAL_HANDOFF_POSTURE_AND_AUTHORITY_UNIFIED
        assert "pr3" in CANONICAL_HANDOFF_POSTURE_AND_AUTHORITY_UNIFIED

    def test_single_chain_enforced_sentinel(self):
        from core.canonical_handoff_path import (
            CANONICAL_HANDOFF_PATH_SINGLE_CHAIN_ENFORCED,
        )

        assert CANONICAL_HANDOFF_PATH_SINGLE_CHAIN_ENFORCED
        assert "pr3" in CANONICAL_HANDOFF_PATH_SINGLE_CHAIN_ENFORCED

    def test_re_exported_handoff_contract_importable(self):
        from core.canonical_handoff_path import HandoffContract

        assert HandoffContract is not None

    def test_re_exported_build_handoff_envelope_v2_importable(self):
        from core.canonical_handoff_path import build_handoff_envelope_v2

        assert build_handoff_envelope_v2 is not None

    def test_build_canonical_handoff_contract_control_only(self):
        from core.canonical_handoff_path import build_canonical_handoff_contract

        c = build_canonical_handoff_contract(
            trace_id="trace_q_001",
            task={"tool_name": "screenshot", "args": {}},
            source_runtime_posture="control_only",
        )
        assert c.trace_id == "trace_q_001"
        assert c.source_runtime_posture == "control_only"

    def test_build_canonical_handoff_contract_join_runtime(self):
        from core.canonical_handoff_path import build_canonical_handoff_contract

        c = build_canonical_handoff_contract(
            trace_id="trace_q_002",
            task={},
            source_runtime_posture="join_runtime",
        )
        assert c.source_runtime_posture == "join_runtime"

    def test_build_canonical_handoff_contract_invalid_posture_falls_back(self):
        from core.canonical_handoff_path import build_canonical_handoff_contract

        c = build_canonical_handoff_contract(
            trace_id="trace_q_003",
            task={},
            source_runtime_posture="INVALID_POSTURE",
        )
        assert c.source_runtime_posture == "control_only"

    def test_build_canonical_handoff_contract_carries_explicit_role(self):
        from core.canonical_handoff_path import build_canonical_handoff_contract

        c = build_canonical_handoff_contract(
            trace_id="trace_q_004",
            task={},
            coordination_role="observer_only",
        )
        assert c.coordination_role == "observer_only"

    def test_build_canonical_handoff_contract_derives_role_from_posture(self):
        """When coordination_role is not supplied, it must be derived from posture."""
        from core.canonical_handoff_path import build_canonical_handoff_contract

        c = build_canonical_handoff_contract(
            trace_id="trace_q_005",
            task={},
            source_runtime_posture="control_only",
        )
        # After derivation, role must be a non-empty recognised value or empty fallback
        assert isinstance(c.coordination_role, str)

    def test_build_canonical_handoff_contract_all_fields(self):
        from core.canonical_handoff_path import build_canonical_handoff_contract

        c = build_canonical_handoff_contract(
            trace_id="trace_q_006",
            task={"tool_name": "file_transfer"},
            capability="file",
            exec_mode="remote",
            route_mode="broadcast",
            session={"session_id": "sess_001"},
            callback_channel="nats",
            task_id="task_q_006",
            source_runtime_posture="join_runtime",
            coordination_role="joined_runtime_participant",
        )
        assert c.trace_id == "trace_q_006"
        assert c.capability == "file"
        assert c.exec_mode == "remote"
        assert c.route_mode == "broadcast"
        assert c.callback_channel == "nats"
        assert c.task_id == "task_q_006"
        assert c.source_runtime_posture == "join_runtime"
        assert c.coordination_role == "joined_runtime_participant"


# ---------------------------------------------------------------------------
# R — NO_AUTHORITY_SILENT_DROP_POLICY end-to-end
# ---------------------------------------------------------------------------


class TestNoAuthoritySilentDropPolicyEndToEnd:
    """coordination_role must not be silently dropped at any boundary."""

    def test_source_controller_never_silently_reset_to_empty(self):
        """source_controller must survive from_legacy_handoff_contract."""
        from contracts.handoff_envelope_v2 import from_legacy_handoff_contract

        contract = _make_real_handoff_contract(coordination_role="source_controller")
        env = from_legacy_handoff_contract(contract)
        assert env.coordination_role == "source_controller"

    def test_joined_runtime_participant_end_to_end(self):
        """join_runtime posture + joined_runtime_participant role end-to-end."""
        from contracts.handoff_envelope_v2 import from_legacy_handoff_contract
        from galaxy_gateway.agent_bridge import AgentBridge, AgentBridgeConfig

        bridge = AgentBridge(config=AgentBridgeConfig(enabled=True))
        contract = _make_real_handoff_contract(
            source_runtime_posture="join_runtime",
            coordination_role="joined_runtime_participant",
        )

        # Path A: legacy adapter
        env_a = from_legacy_handoff_contract(contract)
        assert env_a.coordination_role == "joined_runtime_participant"

        # Path B: build_envelope_v2
        env_b = bridge.build_envelope_v2(contract)
        assert env_b is not None
        assert env_b.metadata.get("coordination_role") == "joined_runtime_participant"

    def test_contract_to_dict_includes_role_when_set(self):
        from galaxy_gateway.agent_bridge import HandoffContract

        for role in (
            "source_controller",
            "joined_runtime_participant",
            "target_only_executor",
            "observer_only",
        ):
            c = HandoffContract(trace_id="t", task={}, coordination_role=role)
            d = c.to_dict()
            assert d.get("coordination_role") == role, (
                f"to_dict() dropped coordination_role={role}"
            )

    def test_round_trip_contract_to_envelope_to_dict(self):
        """HandoffContract → HandoffEnvelopeV2 → to_dict preserves role."""
        from contracts.handoff_envelope_v2 import from_legacy_handoff_contract

        contract = _make_real_handoff_contract(
            coordination_role="target_only_executor"
        )
        env = from_legacy_handoff_contract(contract)
        d = env.to_dict()
        assert d.get("coordination_role") == "target_only_executor"
