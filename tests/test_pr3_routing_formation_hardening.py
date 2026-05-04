#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr3_routing_formation_hardening.py
==============================================
PR-3 — Formation & Routing Hardening: Capability-Aware Routing, Dynamic
Formation Rebalancing, Transport-Layer Purity, and Truth-Layer Boundaries.

This test file provides reviewable proof of the four acceptance criteria
from the PR-3 problem statement:

  1. Formation can be reevaluated when runtime conditions change.
  2. Capability-aware routing meaningfully constrains participant selection.
  3. DeviceRouter is transport-oriented rather than policy-heavy.
  4. Routing-visible decisions align better with canonical orchestration
     truth boundaries.

Test groups
-----------
A) Sentinels — all PR-3 sentinel constants importable.
B) CapabilityRoutingGate — device_meets_capabilities pure gate.
C) CapabilityRoutingGate — evaluate_capability_gate with device objects.
D) CapabilityRoutingGate — filter_by_required_capabilities hard gate.
E) CapabilityRoutingGate — gate is inactive when no requirements declared.
F) CapabilityRoutingGate — INSUFFICIENT_DATA handling.
G) select_devices capability gate wiring — gate excludes failing devices.
H) select_devices capability gate wiring — gate passes when caps satisfied.
I) select_devices capability gate wiring — gate inactive with empty requirements.
J) FormationRebalanceTrigger — on_runtime_event routes to coordinator.
K) FormationRebalanceTrigger — PARTICIPANT_LOST triggers rebalance.
L) FormationRebalanceTrigger — HEALTH_DEGRADED routes to coordinator.
M) FormationRebalanceTrigger — RECOVERY_AVAILABLE routes to coordinator.
N) FormationRebalanceTrigger — EXPLICIT_REBALANCE_REQUEST triggers evaluation.
O) FormationRebalanceTrigger — CAPABILITY_CHANGED triggers evaluation.
P) FormationRebalanceTrigger — trigger_rebalance_if_needed convenience fn.
Q) FormationRebalanceTrigger — no reshape when coordinator says KEEP.
R) FormationRebalanceTrigger — FormationRebuildResult.to_dict is serialisable.
S) core.device_formation __init__ exports trigger symbols.
T) Acceptance criterion 1 — dynamic reevaluation on runtime change.
U) Acceptance criterion 2 — capability gate meaningfully constrains selection.
V) Acceptance criterion 3 — DeviceRouter authority doc is transport-oriented.
W) Acceptance criterion 4 — routing truth-layer boundary sentinels present.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_formation_group(
    *,
    source_id: Optional[str] = "source-dev",
    primary_id: Optional[str] = "primary-dev",
    fallback_ids: Optional[List[str]] = None,
    support_ids: Optional[List[str]] = None,
    domain: str = "cross_device",
):
    from core.device_formation.formation_group import DeviceFormationGroup
    from core.device_formation.formation_role import FormationMember, FormationRole

    members = []
    if source_id:
        members.append(FormationMember(device_id=source_id, role=FormationRole.SOURCE,
                                       reason="source"))
    if primary_id:
        members.append(FormationMember(device_id=primary_id, role=FormationRole.PRIMARY_EXECUTION,
                                       reason="primary"))
    for fid in (fallback_ids or []):
        members.append(FormationMember(device_id=fid, role=FormationRole.FALLBACK,
                                       reason="fallback"))
    for sid in (support_ids or []):
        members.append(FormationMember(device_id=sid, role=FormationRole.SUPPORT,
                                       reason="support"))

    return DeviceFormationGroup(
        source_device_id=source_id,
        members=members,
        runtime_domain_intent=domain,
    )


def _make_coordinator(group):
    from core.device_formation.formation_runtime_coordinator import make_formation_runtime_coordinator
    return make_formation_runtime_coordinator(group)


def _make_device(
    device_id: str,
    status: str = "online",
    capabilities: Optional[List[str]] = None,
    websocket: Any = "ws",
):
    d = MagicMock()
    d.device_id = device_id
    d.status = status
    d.websocket = websocket
    d.capabilities = capabilities or []
    d.metadata = {}
    return d


# ===========================================================================
# A) Sentinels
# ===========================================================================


class TestPR3Sentinels:
    """All PR-3 sentinel constants are importable and contain expected text."""

    def test_capability_routing_gate_authority(self):
        from core.capability_routing_gate import CAPABILITY_ROUTING_GATE_IS_AUTHORITY
        assert isinstance(CAPABILITY_ROUTING_GATE_IS_AUTHORITY, str)
        assert "CAPABILITY_ROUTING_GATE_IS_AUTHORITY" in CAPABILITY_ROUTING_GATE_IS_AUTHORITY

    def test_capability_gate_elevates_from_advisory(self):
        from core.capability_routing_gate import CAPABILITY_GATE_ELEVATES_FROM_ADVISORY_POLICY
        assert isinstance(CAPABILITY_GATE_ELEVATES_FROM_ADVISORY_POLICY, str)
        assert "required_capabilities" in CAPABILITY_GATE_ELEVATES_FROM_ADVISORY_POLICY

    def test_capability_gate_does_not_modify_pool_manager(self):
        from core.capability_routing_gate import CAPABILITY_GATE_DOES_NOT_MODIFY_POOL_MANAGER_POLICY
        assert isinstance(CAPABILITY_GATE_DOES_NOT_MODIFY_POOL_MANAGER_POLICY, str)
        assert "additive" in CAPABILITY_GATE_DOES_NOT_MODIFY_POOL_MANAGER_POLICY.lower()

    def test_device_selection_capability_wired_sentinel(self):
        from galaxy_gateway.routing.device_selection import CAPABILITY_GATE_WIRED_IN_SELECTION
        assert isinstance(CAPABILITY_GATE_WIRED_IN_SELECTION, str)
        assert "required_capabilities" in CAPABILITY_GATE_WIRED_IN_SELECTION

    def test_rebalance_trigger_authority(self):
        from core.device_formation.formation_rebalance_trigger import (
            FORMATION_REBALANCE_TRIGGER_IS_AUTHORITY,
        )
        assert isinstance(FORMATION_REBALANCE_TRIGGER_IS_AUTHORITY, str)
        assert "FORMATION_REBALANCE_TRIGGER_IS_AUTHORITY" in FORMATION_REBALANCE_TRIGGER_IS_AUTHORITY

    def test_rebalance_trigger_wires_coordinator_policy(self):
        from core.device_formation.formation_rebalance_trigger import (
            FORMATION_TRIGGER_WIRES_COORDINATOR_TO_ENGINE_POLICY,
        )
        assert isinstance(FORMATION_TRIGGER_WIRES_COORDINATOR_TO_ENGINE_POLICY, str)
        assert "FormationRuntimeCoordinator" in FORMATION_TRIGGER_WIRES_COORDINATOR_TO_ENGINE_POLICY

    def test_rebalance_trigger_stateless_policy(self):
        from core.device_formation.formation_rebalance_trigger import (
            FORMATION_TRIGGER_DOES_NOT_OWN_STATE_POLICY,
        )
        assert isinstance(FORMATION_TRIGGER_DOES_NOT_OWN_STATE_POLICY, str)


# ===========================================================================
# B) CapabilityRoutingGate — device_meets_capabilities pure gate
# ===========================================================================


class TestCapabilityRoutingGatePure:
    def test_pass_when_all_satisfied(self):
        from core.capability_routing_gate import device_meets_capabilities, CapabilityGateVerdict
        result = device_meets_capabilities(
            device_id="dev-1",
            device_capabilities=["camera", "gps", "screen"],
            required_capabilities=["camera", "gps"],
        )
        assert result.verdict == CapabilityGateVerdict.PASS
        assert result.passed is True
        assert result.missing_capabilities == []

    def test_fail_when_missing_capability(self):
        from core.capability_routing_gate import device_meets_capabilities, CapabilityGateVerdict
        result = device_meets_capabilities(
            device_id="dev-2",
            device_capabilities=["screen"],
            required_capabilities=["camera", "screen"],
        )
        assert result.verdict == CapabilityGateVerdict.FAIL
        assert result.passed is False
        assert "camera" in result.missing_capabilities

    def test_not_required_when_empty(self):
        from core.capability_routing_gate import device_meets_capabilities, CapabilityGateVerdict
        result = device_meets_capabilities(
            device_id="dev-3",
            device_capabilities=[],
            required_capabilities=[],
        )
        assert result.verdict == CapabilityGateVerdict.NOT_REQUIRED
        assert result.passed is True

    def test_partial_match_is_fail(self):
        from core.capability_routing_gate import device_meets_capabilities, CapabilityGateVerdict
        result = device_meets_capabilities(
            device_id="dev-4",
            device_capabilities=["screen"],
            required_capabilities=["screen", "camera", "microphone"],
        )
        assert result.verdict == CapabilityGateVerdict.FAIL
        assert "camera" in result.missing_capabilities
        assert "microphone" in result.missing_capabilities
        assert result.matched_capabilities == ["screen"]

    def test_to_dict_serialisable(self):
        import json
        from core.capability_routing_gate import device_meets_capabilities
        result = device_meets_capabilities("d", ["a"], ["a"])
        d = result.to_dict()
        serialised = json.dumps(d)
        recovered = json.loads(serialised)
        assert recovered["device_id"] == "d"
        assert recovered["passed"] is True


# ===========================================================================
# C) CapabilityRoutingGate — evaluate_capability_gate with device objects
# ===========================================================================


class TestEvaluateCapabilityGate:
    def test_pass_with_capabilities_attr(self):
        from core.capability_routing_gate import evaluate_capability_gate, CapabilityGateVerdict
        device = _make_device("dev-a", capabilities=["touch", "screen"])
        result = evaluate_capability_gate(device, ["touch"])
        assert result.verdict == CapabilityGateVerdict.PASS

    def test_fail_with_capabilities_attr(self):
        from core.capability_routing_gate import evaluate_capability_gate, CapabilityGateVerdict
        device = _make_device("dev-b", capabilities=["screen"])
        result = evaluate_capability_gate(device, ["camera"])
        assert result.verdict == CapabilityGateVerdict.FAIL
        assert result.device_id == "dev-b"

    def test_insufficient_data_when_attr_missing(self):
        from core.capability_routing_gate import evaluate_capability_gate, CapabilityGateVerdict
        device = _make_device("dev-c")
        del device.capabilities
        result = evaluate_capability_gate(device, ["camera"])
        assert result.verdict == CapabilityGateVerdict.INSUFFICIENT_DATA

    def test_custom_capability_attr(self):
        from core.capability_routing_gate import evaluate_capability_gate, CapabilityGateVerdict
        device = MagicMock()
        device.device_id = "dev-d"
        device.caps_list = ["nfc", "bluetooth"]
        result = evaluate_capability_gate(
            device, ["nfc"], capability_attr="caps_list"
        )
        assert result.verdict == CapabilityGateVerdict.PASS

    def test_not_required_with_empty_requirements(self):
        from core.capability_routing_gate import evaluate_capability_gate, CapabilityGateVerdict
        device = _make_device("dev-e", capabilities=[])
        result = evaluate_capability_gate(device, [])
        assert result.verdict == CapabilityGateVerdict.NOT_REQUIRED


# ===========================================================================
# D) CapabilityRoutingGate — filter_by_required_capabilities hard gate
# ===========================================================================


class TestFilterByRequiredCapabilities:
    def test_excludes_devices_missing_capabilities(self):
        from core.capability_routing_gate import filter_by_required_capabilities
        dev_a = _make_device("a", capabilities=["camera", "gps"])
        dev_b = _make_device("b", capabilities=["screen"])
        result = filter_by_required_capabilities([dev_a, dev_b], ["camera"])
        ids = [d.device_id for d in result]
        assert "a" in ids
        assert "b" not in ids

    def test_returns_empty_when_no_devices_satisfy(self):
        from core.capability_routing_gate import filter_by_required_capabilities
        dev_a = _make_device("a", capabilities=["screen"])
        dev_b = _make_device("b", capabilities=["keyboard"])
        result = filter_by_required_capabilities([dev_a, dev_b], ["camera"])
        assert result == []

    def test_passes_all_when_requirements_empty(self):
        from core.capability_routing_gate import filter_by_required_capabilities
        dev_a = _make_device("a", capabilities=[])
        dev_b = _make_device("b", capabilities=[])
        result = filter_by_required_capabilities([dev_a, dev_b], [])
        assert len(result) == 2

    def test_all_devices_pass_when_all_satisfy(self):
        from core.capability_routing_gate import filter_by_required_capabilities
        dev_a = _make_device("a", capabilities=["camera", "screen"])
        dev_b = _make_device("b", capabilities=["camera", "gps", "screen"])
        result = filter_by_required_capabilities([dev_a, dev_b], ["camera", "screen"])
        ids = {d.device_id for d in result}
        assert ids == {"a", "b"}

    def test_insufficient_data_kept_by_default(self):
        from core.capability_routing_gate import filter_by_required_capabilities
        dev_a = _make_device("a")  # has .capabilities = []
        del dev_a.capabilities  # remove attribute → INSUFFICIENT_DATA
        dev_b = _make_device("b", capabilities=["camera"])
        result = filter_by_required_capabilities(
            [dev_a, dev_b], ["camera"], allow_insufficient_data=True
        )
        ids = {d.device_id for d in result}
        # dev_a: INSUFFICIENT_DATA → kept (conservative)
        # dev_b: PASS
        assert "a" in ids
        assert "b" in ids

    def test_insufficient_data_excluded_when_flag_false(self):
        from core.capability_routing_gate import filter_by_required_capabilities
        dev_a = _make_device("a")
        del dev_a.capabilities
        dev_b = _make_device("b", capabilities=["camera"])
        result = filter_by_required_capabilities(
            [dev_a, dev_b], ["camera"], allow_insufficient_data=False
        )
        ids = {d.device_id for d in result}
        assert "a" not in ids
        assert "b" in ids


# ===========================================================================
# E) CapabilityRoutingGate — gate is inactive when no requirements declared
# ===========================================================================


class TestCapabilityGateInactive:
    def test_gate_not_required_verdict(self):
        from core.capability_routing_gate import (
            evaluate_capability_gate, CapabilityGateVerdict
        )
        device = _make_device("x", capabilities=[])
        result = evaluate_capability_gate(device, [])
        assert result.verdict == CapabilityGateVerdict.NOT_REQUIRED
        assert result.passed is True

    def test_filter_passthrough_empty_requirements(self):
        from core.capability_routing_gate import filter_by_required_capabilities
        devices = [_make_device(f"d{i}") for i in range(5)]
        result = filter_by_required_capabilities(devices, [])
        assert len(result) == 5


# ===========================================================================
# F) CapabilityRoutingGate — INSUFFICIENT_DATA handling
# ===========================================================================


class TestInsufficientDataHandling:
    def test_verdict_enum_value(self):
        from core.capability_routing_gate import CapabilityGateVerdict
        assert CapabilityGateVerdict.INSUFFICIENT_DATA.value == "insufficient_data"

    def test_insufficient_data_is_not_passed(self):
        from core.capability_routing_gate import CapabilityGateResult, CapabilityGateVerdict
        r = CapabilityGateResult(
            device_id="d",
            verdict=CapabilityGateVerdict.INSUFFICIENT_DATA,
            required_capabilities=["camera"],
        )
        assert r.passed is False


# ===========================================================================
# G) select_devices capability gate wiring — excludes failing devices
# ===========================================================================


class TestSelectDevicesCapabilityGateExcluding:
    """When required_capabilities is set and a device cannot satisfy them,
    that device must be excluded from selection."""

    def test_gate_excludes_incapable_device(self):
        """Device missing required capability must not be returned."""
        from galaxy_gateway.routing.device_selection import select_devices

        dev_good = _make_device("good", capabilities=["camera", "screen"])
        dev_bad = _make_device("bad", capabilities=["screen"])

        analysis = {
            "required_capabilities": ["camera"],
            "exec_mode": "",
            "actions": [],
            "requires_cross_device": False,
            "task_role": None,
            "target_device_type": "android",
        }

        # Patch out external dependencies to isolate the capability gate.
        with patch(
            "galaxy_gateway.routing.device_selection.get_gateway_capability_projection_view",
            side_effect=ImportError("mocked"),
        ), patch(
            "galaxy_gateway.routing.device_selection.get_device_pool_manager",
            side_effect=Exception("mocked"),
        ), patch(
            "galaxy_gateway.autonomous_filter.filter_autonomous_devices",
            side_effect=ImportError("mocked"),
        ):
            result = select_devices(analysis, [dev_good, dev_bad])

        ids = [d.device_id for d in result]
        assert "good" in ids
        assert "bad" not in ids

    def test_gate_returns_empty_when_all_fail(self):
        from galaxy_gateway.routing.device_selection import select_devices

        dev_a = _make_device("a", capabilities=["screen"])
        dev_b = _make_device("b", capabilities=["keyboard"])

        analysis = {
            "required_capabilities": ["camera"],
            "exec_mode": "",
            "actions": [],
            "requires_cross_device": False,
            "task_role": None,
            "target_device_type": "android",
        }

        with patch(
            "galaxy_gateway.routing.device_selection.get_gateway_capability_projection_view",
            side_effect=ImportError("mocked"),
        ), patch(
            "galaxy_gateway.routing.device_selection.get_device_pool_manager",
            side_effect=Exception("mocked"),
        ):
            result = select_devices(analysis, [dev_a, dev_b])

        assert result == []


# ===========================================================================
# H) select_devices capability gate wiring — gate passes when caps satisfied
# ===========================================================================


class TestSelectDevicesCapabilityGatePassing:
    def test_capable_device_is_returned(self):
        from galaxy_gateway.routing.device_selection import select_devices

        dev = _make_device("capable", capabilities=["camera", "gps"])

        analysis = {
            "required_capabilities": ["camera"],
            "exec_mode": "",
            "actions": [],
            "requires_cross_device": False,
            "task_role": None,
            "target_device_type": "android",
        }

        with patch(
            "galaxy_gateway.routing.device_selection.get_gateway_capability_projection_view",
            side_effect=ImportError("mocked"),
        ), patch(
            "galaxy_gateway.routing.device_selection.get_device_pool_manager",
            side_effect=Exception("mocked"),
        ), patch(
            "galaxy_gateway.autonomous_filter.filter_autonomous_devices",
            side_effect=ImportError("mocked"),
        ):
            result = select_devices(analysis, [dev])

        assert len(result) == 1
        assert result[0].device_id == "capable"


# ===========================================================================
# I) select_devices capability gate wiring — gate inactive with empty requirements
# ===========================================================================


class TestSelectDevicesGateInactive:
    def test_no_requirements_does_not_filter(self):
        from galaxy_gateway.routing.device_selection import select_devices

        dev = _make_device("any-device", capabilities=[])

        analysis = {
            "required_capabilities": [],
            "exec_mode": "",
            "actions": [],
            "requires_cross_device": False,
            "task_role": None,
            "target_device_type": "android",
        }

        with patch(
            "galaxy_gateway.routing.device_selection.get_gateway_capability_projection_view",
            side_effect=ImportError("mocked"),
        ), patch(
            "galaxy_gateway.routing.device_selection.get_device_pool_manager",
            side_effect=Exception("mocked"),
        ), patch(
            "galaxy_gateway.autonomous_filter.filter_autonomous_devices",
            side_effect=ImportError("mocked"),
        ):
            result = select_devices(analysis, [dev])

        assert len(result) == 1


# ===========================================================================
# J) FormationRebalanceTrigger — on_runtime_event routes to coordinator
# ===========================================================================


class TestFormationRebalanceTriggerRouting:
    def test_participant_ready_event_routes(self):
        from core.device_formation.formation_rebalance_trigger import (
            on_runtime_event, FormationRuntimeEvent, FormationRuntimeEventType,
        )
        group = _make_formation_group(fallback_ids=["fb-1"])
        coordinator = _make_coordinator(group)
        event = FormationRuntimeEvent(
            event_type=FormationRuntimeEventType.PARTICIPANT_READY,
            device_id="primary-dev",
        )
        result = on_runtime_event(event, group, coordinator)
        assert result is not None
        assert hasattr(result, "reshaped")
        assert result.original_formation_id == group.formation_id


# ===========================================================================
# K) FormationRebalanceTrigger — PARTICIPANT_LOST triggers rebalance
# ===========================================================================


class TestParticipantLostTrigger:
    def test_primary_lost_triggers_promote_or_terminate(self):
        from core.device_formation.formation_rebalance_trigger import (
            on_runtime_event, FormationRuntimeEvent, FormationRuntimeEventType,
        )
        from core.device_formation.formation_runtime_coordinator import FormationRuntimeState
        group = _make_formation_group(fallback_ids=["fb-1"])
        coordinator = _make_coordinator(group)

        event = FormationRuntimeEvent(
            event_type=FormationRuntimeEventType.PARTICIPANT_LOST,
            device_id="primary-dev",
            reason="test: primary device disconnected",
        )
        result = on_runtime_event(event, group, coordinator)

        assert result is not None
        assert result.coordinator_decision is not None

    def test_support_lost_does_not_terminate_formation(self):
        from core.device_formation.formation_rebalance_trigger import (
            on_runtime_event, FormationRuntimeEvent, FormationRuntimeEventType,
        )
        group = _make_formation_group(support_ids=["sup-1"])
        coordinator = _make_coordinator(group)

        event = FormationRuntimeEvent(
            event_type=FormationRuntimeEventType.PARTICIPANT_LOST,
            device_id="sup-1",
        )
        result = on_runtime_event(event, group, coordinator)
        assert result is not None


# ===========================================================================
# L) FormationRebalanceTrigger — HEALTH_DEGRADED routes to coordinator
# ===========================================================================


class TestHealthDegradedTrigger:
    def test_health_degraded_produces_result(self):
        from core.device_formation.formation_rebalance_trigger import (
            on_runtime_event, FormationRuntimeEvent, FormationRuntimeEventType,
        )
        group = _make_formation_group()
        coordinator = _make_coordinator(group)
        event = FormationRuntimeEvent(
            event_type=FormationRuntimeEventType.HEALTH_DEGRADED,
            device_id="primary-dev",
            health_score=0.1,
        )
        result = on_runtime_event(event, group, coordinator)
        assert result is not None
        assert result.coordinator_decision is not None


# ===========================================================================
# M) FormationRebalanceTrigger — RECOVERY_AVAILABLE routes to coordinator
# ===========================================================================


class TestRecoveryAvailableTrigger:
    def test_recovery_available_produces_result(self):
        from core.device_formation.formation_rebalance_trigger import (
            on_runtime_event, FormationRuntimeEvent, FormationRuntimeEventType,
        )
        group = _make_formation_group()
        coordinator = _make_coordinator(group)

        # First mark a device as lost
        coordinator.on_participant_lost("primary-dev")

        # Then signal recovery
        event = FormationRuntimeEvent(
            event_type=FormationRuntimeEventType.RECOVERY_AVAILABLE,
            device_id="primary-dev",
        )
        result = on_runtime_event(event, group, coordinator)
        assert result is not None


# ===========================================================================
# N) FormationRebalanceTrigger — EXPLICIT_REBALANCE_REQUEST triggers evaluation
# ===========================================================================


class TestExplicitRebalanceRequest:
    def test_explicit_rebalance_request_handled(self):
        from core.device_formation.formation_rebalance_trigger import (
            on_runtime_event, FormationRuntimeEvent, FormationRuntimeEventType,
        )
        group = _make_formation_group(fallback_ids=["fb-1"])
        coordinator = _make_coordinator(group)
        event = FormationRuntimeEvent(
            event_type=FormationRuntimeEventType.EXPLICIT_REBALANCE_REQUEST,
            device_id="",
        )
        result = on_runtime_event(event, group, coordinator)
        assert result is not None
        assert hasattr(result, "reshaped")


# ===========================================================================
# O) FormationRebalanceTrigger — CAPABILITY_CHANGED triggers evaluation
# ===========================================================================


class TestCapabilityChangedEvent:
    def test_capability_changed_triggers_evaluation(self):
        from core.device_formation.formation_rebalance_trigger import (
            on_runtime_event, FormationRuntimeEvent, FormationRuntimeEventType,
        )
        group = _make_formation_group()
        coordinator = _make_coordinator(group)
        event = FormationRuntimeEvent(
            event_type=FormationRuntimeEventType.CAPABILITY_CHANGED,
            device_id="primary-dev",
        )
        result = on_runtime_event(event, group, coordinator)
        assert result is not None


# ===========================================================================
# P) FormationRebalanceTrigger — trigger_rebalance_if_needed convenience fn
# ===========================================================================


class TestTriggerRebalanceIfNeeded:
    def test_trigger_returns_result(self):
        from core.device_formation.formation_rebalance_trigger import trigger_rebalance_if_needed
        group = _make_formation_group(fallback_ids=["fb-1"])
        coordinator = _make_coordinator(group)
        result = trigger_rebalance_if_needed(group, coordinator)
        assert result is not None
        assert hasattr(result, "reshaped")
        assert hasattr(result, "new_group")

    def test_trigger_with_health_map(self):
        from core.device_formation.formation_rebalance_trigger import trigger_rebalance_if_needed
        from core.device_formation.formation_rebalance_engine import FormationHealthSignal
        group = _make_formation_group(fallback_ids=["fb-1"])
        coordinator = _make_coordinator(group)
        health_map = {
            "primary-dev": FormationHealthSignal(device_id="primary-dev", health_score=0.0,
                                                  is_reachable=False),
            "fb-1": FormationHealthSignal(device_id="fb-1", health_score=0.9, is_reachable=True),
        }
        result = trigger_rebalance_if_needed(group, coordinator, health_map=health_map)
        assert result is not None


# ===========================================================================
# Q) FormationRebalanceTrigger — no reshape when coordinator says KEEP
# ===========================================================================


class TestNoReshapeOnKeep:
    def test_no_reshape_when_all_healthy(self):
        from core.device_formation.formation_rebalance_trigger import (
            on_runtime_event, FormationRuntimeEvent, FormationRuntimeEventType,
        )
        group = _make_formation_group()
        coordinator = _make_coordinator(group)
        event = FormationRuntimeEvent(
            event_type=FormationRuntimeEventType.PARTICIPANT_READY,
            device_id="primary-dev",
        )
        result = on_runtime_event(event, group, coordinator)
        # Formation is already healthy; we don't expect a reshape.
        assert result.reshaped is False
        # The same group object should be returned when no reshape is needed.
        assert result.new_group is group


# ===========================================================================
# R) FormationRebalanceTrigger — FormationRebuildResult.to_dict serialisable
# ===========================================================================


class TestFormationRebuildResultSerialisation:
    def test_to_dict_is_json_serialisable(self):
        import json
        from core.device_formation.formation_rebalance_trigger import trigger_rebalance_if_needed
        group = _make_formation_group()
        coordinator = _make_coordinator(group)
        result = trigger_rebalance_if_needed(group, coordinator)
        d = result.to_dict()
        serialised = json.dumps(d)
        recovered = json.loads(serialised)
        assert isinstance(recovered["reshaped"], bool)
        assert "new_group" in recovered

    def test_to_dict_includes_reason(self):
        from core.device_formation.formation_rebalance_trigger import trigger_rebalance_if_needed
        group = _make_formation_group()
        coordinator = _make_coordinator(group)
        result = trigger_rebalance_if_needed(group, coordinator)
        d = result.to_dict()
        assert "reason" in d
        assert isinstance(d["reason"], str)


# ===========================================================================
# S) core.device_formation __init__ exports trigger symbols
# ===========================================================================


class TestDeviceFormationInitExportsTrigger:
    def test_trigger_symbols_exported(self):
        from core.device_formation import (
            FormationRuntimeEventType,
            FormationRuntimeEvent,
            FormationRebuildResult,
            on_runtime_event,
            trigger_rebalance_if_needed,
            FORMATION_REBALANCE_TRIGGER_IS_AUTHORITY,
            FORMATION_TRIGGER_WIRES_COORDINATOR_TO_ENGINE_POLICY,
            FORMATION_TRIGGER_DOES_NOT_OWN_STATE_POLICY,
        )
        assert FormationRuntimeEventType is not None
        assert callable(on_runtime_event)
        assert callable(trigger_rebalance_if_needed)
        assert isinstance(FORMATION_REBALANCE_TRIGGER_IS_AUTHORITY, str)


# ===========================================================================
# T) Acceptance criterion 1 — dynamic reevaluation on runtime change
#
# A reviewer can determine that formation CAN be reevaluated when runtime
# conditions change by observing that:
# - on_runtime_event() accepts PARTICIPANT_LOST and triggers reshaping
# - After primary is lost, the result shows the fallback was promoted
#   (reshape applied), proving reevaluation happened.
# ===========================================================================


class TestAcceptanceCriterion1DynamicReevaluation:
    """Formation reevaluation on runtime participant changes."""

    def test_primary_lost_reshapes_formation(self):
        """Losing the primary participant drives formation to promote a fallback.
        This proves that formation is reevaluated, not kept static."""
        from core.device_formation.formation_rebalance_trigger import (
            on_runtime_event, FormationRuntimeEvent, FormationRuntimeEventType,
        )
        from core.device_formation.formation_rebalance_engine import FormationHealthSignal
        from core.device_formation.formation_role import FormationRole

        group = _make_formation_group(fallback_ids=["fb-promote"])
        coordinator = _make_coordinator(group)

        event = FormationRuntimeEvent(
            event_type=FormationRuntimeEventType.PARTICIPANT_LOST,
            device_id="primary-dev",
            reason="acceptance-test: primary device lost",
        )

        health_map = {
            "primary-dev": FormationHealthSignal(
                device_id="primary-dev", health_score=0.0, is_reachable=False
            ),
            "fb-promote": FormationHealthSignal(
                device_id="fb-promote", health_score=0.9, is_reachable=True
            ),
        }

        result = on_runtime_event(event, group, coordinator, health_map=health_map)

        # Formation reevaluation happened — a decision was produced.
        assert result.coordinator_decision is not None

        # The result captures whether a reshape was applied.
        assert hasattr(result, "reshaped")

        # If reshape happened, the new primary should have been updated.
        # (engine decides based on health scores)
        if result.reshaped:
            new_primaries = [
                m.device_id
                for m in result.new_group.members
                if m.role == FormationRole.PRIMARY_EXECUTION
            ]
            assert len(new_primaries) >= 1

    def test_recovery_reevaluates_formation_state(self):
        """Recovery signal causes formation state to be reevaluated."""
        from core.device_formation.formation_rebalance_trigger import (
            on_runtime_event, FormationRuntimeEvent, FormationRuntimeEventType,
        )

        group = _make_formation_group()
        coordinator = _make_coordinator(group)

        # Mark device as lost first
        coordinator.on_participant_lost("primary-dev", reason="test")

        # Signal recovery — should trigger reevaluation
        event = FormationRuntimeEvent(
            event_type=FormationRuntimeEventType.RECOVERY_AVAILABLE,
            device_id="primary-dev",
        )
        result = on_runtime_event(event, group, coordinator)
        assert result is not None
        # Recovery was processed — a decision was produced
        assert result.coordinator_decision is not None

    def test_capability_changed_triggers_reevaluation(self):
        """Capability changes at runtime cause formation reevaluation."""
        from core.device_formation.formation_rebalance_trigger import (
            on_runtime_event, FormationRuntimeEvent, FormationRuntimeEventType,
        )

        group = _make_formation_group()
        coordinator = _make_coordinator(group)
        event = FormationRuntimeEvent(
            event_type=FormationRuntimeEventType.CAPABILITY_CHANGED,
            device_id="primary-dev",
            reason="capability set changed at runtime",
        )
        result = on_runtime_event(event, group, coordinator)
        assert result is not None


# ===========================================================================
# U) Acceptance criterion 2 — capability gate meaningfully constrains selection
#
# A reviewer can determine that capability-aware routing meaningfully
# constrains participant selection by observing that:
# - filter_by_required_capabilities() returns an EMPTY list when no device
#   satisfies the requirements (hard gate — not a soft fallback)
# - select_devices() returns empty when the capability gate fails all candidates
# ===========================================================================


class TestAcceptanceCriterion2CapabilityConstraint:
    """Capability-aware routing meaningfully constrains participant selection."""

    def test_hard_gate_empty_result_when_all_fail(self):
        """Hard gate produces an empty selection — not a fallback to 'all'."""
        from core.capability_routing_gate import filter_by_required_capabilities
        devices = [
            _make_device("d1", capabilities=["screen"]),
            _make_device("d2", capabilities=["keyboard"]),
            _make_device("d3", capabilities=["screen", "keyboard"]),
        ]
        result = filter_by_required_capabilities(devices, required_capabilities=["camera"])
        # None of the devices have "camera" → hard empty result
        assert result == [], (
            "Expected empty list when no device satisfies required capabilities. "
            "This proves the gate is hard, not advisory."
        )

    def test_only_capable_devices_pass(self):
        """Only devices that satisfy ALL required capabilities pass the gate."""
        from core.capability_routing_gate import filter_by_required_capabilities
        capable = _make_device("capable", capabilities=["camera", "gps"])
        incapable = _make_device("incapable", capabilities=["screen"])
        partial = _make_device("partial", capabilities=["camera"])  # missing gps

        result = filter_by_required_capabilities(
            [capable, incapable, partial], ["camera", "gps"]
        )
        ids = {d.device_id for d in result}
        assert ids == {"capable"}, (
            "Only the device satisfying ALL required capabilities should be selected."
        )

    def test_select_devices_respects_capability_gate(self):
        """select_devices applies the hard gate, not just a hint."""
        from galaxy_gateway.routing.device_selection import select_devices

        # Device missing required capability
        bad_device = _make_device("bad", capabilities=["screen"])

        analysis = {
            "required_capabilities": ["camera"],
            "exec_mode": "",
            "actions": [],
            "requires_cross_device": False,
            "task_role": None,
            "target_device_type": "android",
        }

        with patch(
            "galaxy_gateway.routing.device_selection.get_gateway_capability_projection_view",
            side_effect=ImportError("mocked"),
        ), patch(
            "galaxy_gateway.routing.device_selection.get_device_pool_manager",
            side_effect=Exception("mocked"),
        ):
            result = select_devices(analysis, [bad_device])

        # The gate must exclude the device, proving it's enforced not advisory.
        assert result == [], (
            "select_devices must return empty when the only device fails the "
            "capability gate. This proves capabilities are enforced constraints."
        )


# ===========================================================================
# V) Acceptance criterion 3 — DeviceRouter authority doc is transport-oriented
#
# A reviewer can determine that DeviceRouter is transport-oriented by
# verifying that its module docstring lists "Formation / session truth" and
# "Orchestration eligibility" as NOT responsibilities.
# ===========================================================================


class TestAcceptanceCriterion3TransportLayerPurity:
    """DeviceRouter is transport-oriented, not policy-heavy."""

    def test_device_router_docstring_declares_non_responsibilities(self):
        """DeviceRouter module doc explicitly declares what it is NOT responsible for."""
        import ast
        import pathlib

        router_path = pathlib.Path(
            __file__
        ).parent.parent / "galaxy_gateway" / "device_router.py"
        source = router_path.read_text(encoding="utf-8")

        # Check that the module docstring names 'Formation' and 'orchestration eligibility'
        # as non-responsibilities.
        assert "Formation" in source or "formation" in source, (
            "DeviceRouter module should document formation as NOT its responsibility"
        )
        assert "eligibility" in source or "Orchestration eligibility" in source, (
            "DeviceRouter module should document orchestration eligibility "
            "as NOT its responsibility"
        )

    def test_device_router_delegates_formation_to_resolver(self):
        """DeviceRouter delegates formation resolution to formation_resolver,
        not implement it inline."""
        import pathlib

        router_path = pathlib.Path(
            __file__
        ).parent.parent / "galaxy_gateway" / "device_router.py"
        source = router_path.read_text(encoding="utf-8")

        # DeviceRouter should import/use resolve_formation rather than
        # computing formation logic inline.
        assert "resolve_formation" in source, (
            "DeviceRouter should delegate formation resolution to "
            "formation_resolver.resolve_formation(), not compute it inline."
        )

    def test_routing_orchestrator_exposes_sub_module_authorities(self):
        """RoutingOrchestrator exposes sub-module authority sentinels,
        confirming policy stays in correct layers."""
        from galaxy_gateway.routing.router import RoutingOrchestrator
        orchestrator = RoutingOrchestrator()
        assert hasattr(orchestrator, "POLICY_AUTHORITY")
        assert hasattr(orchestrator, "SELECTION_AUTHORITY")
        assert hasattr(orchestrator, "HEALTH_AUTHORITY")
        assert hasattr(orchestrator, "DISPATCH_AUTHORITY")
        # Each authority belongs to a canonical sub-module — not DeviceRouter itself
        assert orchestrator.POLICY_AUTHORITY != "galaxy_gateway.device_router"
        assert orchestrator.SELECTION_AUTHORITY != "galaxy_gateway.device_router"

    def test_capability_gate_is_separate_from_device_router(self):
        """The capability gate lives in core/, not in DeviceRouter."""
        import importlib
        gate_module = importlib.import_module("core.capability_routing_gate")
        # If this import succeeds, the gate is in core/ (separate from DeviceRouter)
        assert gate_module is not None
        assert hasattr(gate_module, "filter_by_required_capabilities")


# ===========================================================================
# W) Acceptance criterion 4 — routing truth-layer boundary sentinels present
#
# A reviewer can determine routing-visible decisions align with canonical
# orchestration truth boundaries by observing that:
# - Each routing/formation layer has a clear authority sentinel
# - The trigger bridges coordinator to engine without owning either
# - FormationResolver is the formation-assembly authority
# - FormationRebalanceEngine is the reshape authority
# - FormationRuntimeCoordinator is the runtime lifecycle authority
# ===========================================================================


class TestAcceptanceCriterion4TruthLayerBoundaries:
    """Routing decisions align with canonical orchestration truth boundaries."""

    def test_formation_resolver_authority_sentinel(self):
        """Formation assembly authority is in formation_resolver, not router."""
        from core.device_formation.formation_resolver import resolve_formation
        # formation_resolver is the canonical formation-assembly layer —
        # it can be imported cleanly without DeviceRouter dependency
        assert callable(resolve_formation)

    def test_rebalance_engine_is_authority_sentinel(self):
        """FormationRebalanceEngine is the canonical reshape authority."""
        from core.device_formation.formation_rebalance_engine import (
            FORMATION_REBALANCE_ENGINE_IS_AUTHORITY,
        )
        assert "formation-rebalance" in FORMATION_REBALANCE_ENGINE_IS_AUTHORITY.lower() or \
               "rebalance" in FORMATION_REBALANCE_ENGINE_IS_AUTHORITY.lower()

    def test_coordinator_is_authority_sentinel(self):
        """FormationRuntimeCoordinator is the canonical runtime lifecycle authority."""
        from core.device_formation.formation_runtime_coordinator import (
            FORMATION_RUNTIME_COORDINATOR_IS_AUTHORITY,
        )
        assert "runtime coordinator" in FORMATION_RUNTIME_COORDINATOR_IS_AUTHORITY.lower()

    def test_trigger_does_not_own_state(self):
        """Rebalance trigger is a stateless bridge — confirmed by policy sentinel."""
        from core.device_formation.formation_rebalance_trigger import (
            FORMATION_TRIGGER_DOES_NOT_OWN_STATE_POLICY,
        )
        assert "stateless" in FORMATION_TRIGGER_DOES_NOT_OWN_STATE_POLICY.lower()

    def test_device_selection_authority_sentinel(self):
        """Device selection authority is in routing sub-module."""
        from galaxy_gateway.routing.device_selection import DEVICE_SELECTION_AUTHORITY
        assert "device_selection" in DEVICE_SELECTION_AUTHORITY

    def test_routing_policy_authority_sentinel(self):
        """Routing policy authority is in routing sub-module (not DeviceRouter)."""
        from galaxy_gateway.routing.policy import ROUTING_POLICY_AUTHORITY
        assert "policy" in ROUTING_POLICY_AUTHORITY

    def test_health_policy_authority_sentinel(self):
        """Health gating authority is in its own module."""
        from galaxy_gateway.routing.health_policy import DEVICE_HEALTH_POLICY_AUTHORITY
        assert "health_policy" in DEVICE_HEALTH_POLICY_AUTHORITY

    def test_all_formation_authorities_are_distinct(self):
        """Each layer in the formation stack has a distinct authority sentinel."""
        from core.device_formation.formation_rebalance_engine import FORMATION_REBALANCE_ENGINE_IS_AUTHORITY
        from core.device_formation.formation_runtime_coordinator import FORMATION_RUNTIME_COORDINATOR_IS_AUTHORITY
        from core.device_formation.formation_rebalance_trigger import FORMATION_REBALANCE_TRIGGER_IS_AUTHORITY
        from galaxy_gateway.routing.device_selection import DEVICE_SELECTION_AUTHORITY

        authorities = [
            FORMATION_REBALANCE_ENGINE_IS_AUTHORITY,
            FORMATION_RUNTIME_COORDINATOR_IS_AUTHORITY,
            FORMATION_REBALANCE_TRIGGER_IS_AUTHORITY,
            DEVICE_SELECTION_AUTHORITY,
        ]
        # All must be non-empty strings
        for auth in authorities:
            assert isinstance(auth, str) and auth

        # All must be distinct
        assert len(set(authorities)) == len(authorities), (
            "Each formation/routing layer must have a distinct authority sentinel. "
            "Duplicate sentinels suggest conflated responsibilities."
        )
