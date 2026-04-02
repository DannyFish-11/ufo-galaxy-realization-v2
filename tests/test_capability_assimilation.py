#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_capability_assimilation.py
=======================================
PR-7: Capability & Node Assimilation — tests for
``core.capability_assimilation``.

Coverage
--------
A) Module structure
   - CAPABILITY_ASSIMILATION_AUTHORITY sentinel is importable
   - CAPABILITY_ASSIMILATION_LAYER_POSITION is 7
   - NODE_ORCHESTRATOR_ASSIMILATION_POLICY is importable
   - ASSIMILATION_CONTRACT_VERSION is importable
   - All public names in __all__ are importable

B) Enumerations
   - NodeParticipantKind has CAPABILITY_PROVIDER value
   - NodeParticipantKind has WORKER value
   - NodeParticipantKind has SPECIALIST value
   - NodeParticipantKind has FABRIC_PARTICIPANT value
   - NodeParticipantKind has LEGACY_FACADE value
   - NodeParticipantKind has UNKNOWN value
   - AssimilationPresenceState has ONLINE value
   - AssimilationPresenceState has OFFLINE value
   - AssimilationPresenceState has DEGRADED value
   - AssimilationPresenceState has STALE value

C) CapabilityDescriptor dataclass
   - can be constructed with only node_id
   - to_dict() contains all expected keys
   - to_dict() is JSON-serialisable
   - capabilities, tags, constraints default to empty

D) ExecutionProfile dataclass
   - can be constructed with only node_id
   - to_dict() contains all expected keys
   - to_dict() participant_kind is a string
   - defaults: max_concurrent_tasks=0, priority="normal"

E) FabricPresence dataclass
   - can be constructed with only node_id
   - to_dict() contains all expected keys
   - heartbeat_age_secs() returns a non-negative float
   - transport_hints defaults to empty dict

F) AssimilationRecord dataclass
   - can be constructed with only node_id
   - to_dict() contains all expected keys
   - to_dict() is JSON-serialisable
   - projected_to_task_graph defaults to False
   - projected_to_network_graph defaults to False

G) AssimilationEvent dataclass
   - can be constructed with event_kind and node_id
   - to_dict() contains event_kind, node_id, timestamp, details
   - timestamp is a positive float

H) CapabilityAssimilationLayer — assimilation
   - assimilate() returns AssimilationRecord
   - assimilated record has correct node_id
   - assimilate() with empty node_id raises ValueError
   - capabilities are stored in capability_descriptor
   - participant_kind is stored in execution_profile
   - fabric presence is ONLINE after assimilation
   - heartbeat_count is 1 after first assimilation
   - re-assimilating same node updates the record
   - re-assimilation preserves registered_at timestamp

I) CapabilityAssimilationLayer — heartbeat
   - heartbeat() returns True for known node
   - heartbeat() returns False for unknown node
   - heartbeat increments heartbeat_count
   - heartbeat with health_score < 0.5 sets DEGRADED
   - heartbeat with health_score >= 0.5 keeps ONLINE

J) CapabilityAssimilationLayer — offline/stale
   - mark_offline() returns True for known node
   - mark_offline() returns False for unknown node
   - mark_offline() sets presence state to OFFLINE
   - after mark_offline, re-assimilation is treated as rejoin
   - mark_stale_if_expired() returns list of stale node ids

K) CapabilityAssimilationLayer — queries
   - get_record() returns record for known node
   - get_record() returns None for unknown node
   - list_records() returns list of AssimilationRecord
   - list_online_records() filters by ONLINE state
   - get_capability_descriptors() returns list
   - get_execution_profiles() returns list
   - get_fabric_presences() returns list

L) CapabilityAssimilationLayer — observability
   - get_event_log() returns a deque
   - events are appended after assimilation
   - events are appended after heartbeat
   - events are appended after mark_offline

M) CapabilityAssimilationLayer — snapshot
   - snapshot() returns a dict
   - snapshot contains total_nodes
   - snapshot contains by_participant_kind
   - snapshot contains by_presence_state
   - snapshot authority matches sentinel

N) assimilate_from_node_info — dict input
   - accepts a dict with node_id key
   - capabilities from dict are extracted

O) assimilate_node convenience helper
   - returns AssimilationRecord for dict input
   - returns AssimilationRecord for object input

P) Singleton behaviour
   - get_capability_assimilation_layer() returns same instance
   - reset_capability_assimilation_layer() creates new instance
"""

from __future__ import annotations

import json
import time
from collections import deque
from typing import Any
from unittest.mock import patch

import pytest

import core.capability_assimilation as _mod
from core.capability_assimilation import (
    ASSIMILATION_CONTRACT_VERSION,
    CAPABILITY_ASSIMILATION_AUTHORITY,
    CAPABILITY_ASSIMILATION_LAYER_POSITION,
    NODE_ORCHESTRATOR_ASSIMILATION_POLICY,
    AssimilationEvent,
    AssimilationPresenceState,
    AssimilationRecord,
    CapabilityAssimilationLayer,
    CapabilityDescriptor,
    ExecutionProfile,
    FabricPresence,
    NodeParticipantKind,
    assimilate_node,
    get_capability_assimilation_layer,
    reset_capability_assimilation_layer,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset():
    """Ensure each test gets a fresh singleton."""
    reset_capability_assimilation_layer()
    yield
    reset_capability_assimilation_layer()


def _layer() -> CapabilityAssimilationLayer:
    return get_capability_assimilation_layer()


# ===========================================================================
# A) Module structure
# ===========================================================================


def test_a01_authority_sentinel_importable():
    assert CAPABILITY_ASSIMILATION_AUTHORITY


def test_a02_layer_position_is_7():
    assert CAPABILITY_ASSIMILATION_LAYER_POSITION == 7


def test_a03_orchestrator_policy_importable():
    assert NODE_ORCHESTRATOR_ASSIMILATION_POLICY


def test_a04_contract_version_importable():
    assert ASSIMILATION_CONTRACT_VERSION


def test_a05_all_public_names_importable():
    for name in _mod.__all__:
        assert hasattr(_mod, name), f"Missing: {name}"


# ===========================================================================
# B) Enumerations
# ===========================================================================


def test_b01_participant_kind_capability_provider():
    assert NodeParticipantKind.CAPABILITY_PROVIDER.value == "capability_provider"


def test_b02_participant_kind_worker():
    assert NodeParticipantKind.WORKER.value == "worker"


def test_b03_participant_kind_specialist():
    assert NodeParticipantKind.SPECIALIST.value == "specialist"


def test_b04_participant_kind_fabric_participant():
    assert NodeParticipantKind.FABRIC_PARTICIPANT.value == "fabric_participant"


def test_b05_participant_kind_legacy_facade():
    assert NodeParticipantKind.LEGACY_FACADE.value == "legacy_facade"


def test_b06_participant_kind_unknown():
    assert NodeParticipantKind.UNKNOWN.value == "unknown"


def test_b07_presence_state_online():
    assert AssimilationPresenceState.ONLINE.value == "online"


def test_b08_presence_state_offline():
    assert AssimilationPresenceState.OFFLINE.value == "offline"


def test_b09_presence_state_degraded():
    assert AssimilationPresenceState.DEGRADED.value == "degraded"


def test_b10_presence_state_stale():
    assert AssimilationPresenceState.STALE.value == "stale"


# ===========================================================================
# C) CapabilityDescriptor
# ===========================================================================


def test_c01_capability_descriptor_minimal_construction():
    desc = CapabilityDescriptor(node_id="n1")
    assert desc.node_id == "n1"


def test_c02_capability_descriptor_to_dict_keys():
    desc = CapabilityDescriptor(node_id="n1", capabilities=["foo"], tags=["t"])
    d = desc.to_dict()
    for key in ("node_id", "capabilities", "tags", "constraints", "scope", "contract_version"):
        assert key in d, f"Missing key: {key}"


def test_c03_capability_descriptor_to_dict_json_serialisable():
    desc = CapabilityDescriptor(node_id="n1", capabilities=["a"])
    json.dumps(desc.to_dict())  # should not raise


def test_c04_capability_descriptor_defaults_empty():
    desc = CapabilityDescriptor(node_id="n1")
    assert desc.capabilities == []
    assert desc.tags == []
    assert desc.constraints == {}


# ===========================================================================
# D) ExecutionProfile
# ===========================================================================


def test_d01_execution_profile_minimal_construction():
    ep = ExecutionProfile(node_id="n1")
    assert ep.node_id == "n1"


def test_d02_execution_profile_to_dict_keys():
    ep = ExecutionProfile(node_id="n1")
    d = ep.to_dict()
    for key in ("node_id", "participant_kind", "max_concurrent_tasks", "priority",
                "supported_task_types", "metadata"):
        assert key in d, f"Missing key: {key}"


def test_d03_execution_profile_to_dict_participant_kind_is_string():
    ep = ExecutionProfile(node_id="n1", participant_kind=NodeParticipantKind.WORKER)
    assert isinstance(ep.to_dict()["participant_kind"], str)


def test_d04_execution_profile_defaults():
    ep = ExecutionProfile(node_id="n1")
    assert ep.max_concurrent_tasks == 0
    assert ep.priority == "normal"


# ===========================================================================
# E) FabricPresence
# ===========================================================================


def test_e01_fabric_presence_minimal_construction():
    fp = FabricPresence(node_id="n1")
    assert fp.node_id == "n1"


def test_e02_fabric_presence_to_dict_keys():
    fp = FabricPresence(node_id="n1")
    d = fp.to_dict()
    for key in ("node_id", "presence_state", "host", "port", "transport_hints",
                "last_heartbeat_at", "heartbeat_age_secs", "heartbeat_count", "registered_at"):
        assert key in d, f"Missing key: {key}"


def test_e03_fabric_presence_heartbeat_age_secs_non_negative():
    fp = FabricPresence(node_id="n1")
    assert fp.heartbeat_age_secs() >= 0.0


def test_e04_fabric_presence_transport_hints_default_empty():
    fp = FabricPresence(node_id="n1")
    assert fp.transport_hints == {}


# ===========================================================================
# F) AssimilationRecord
# ===========================================================================


def test_f01_assimilation_record_minimal_construction():
    rec = AssimilationRecord(node_id="n1")
    assert rec.node_id == "n1"


def test_f02_assimilation_record_to_dict_keys():
    rec = AssimilationRecord(node_id="n1")
    d = rec.to_dict()
    for key in ("node_id", "capability_descriptor", "execution_profile",
                "fabric_presence", "projected_to_task_graph",
                "projected_to_network_graph", "assimilation_notes", "contract_version"):
        assert key in d, f"Missing key: {key}"


def test_f03_assimilation_record_to_dict_json_serialisable():
    rec = AssimilationRecord(node_id="n1")
    json.dumps(rec.to_dict())  # should not raise


def test_f04_assimilation_record_projected_defaults_false():
    rec = AssimilationRecord(node_id="n1")
    assert rec.projected_to_task_graph is False
    assert rec.projected_to_network_graph is False


# ===========================================================================
# G) AssimilationEvent
# ===========================================================================


def test_g01_assimilation_event_construction():
    ev = AssimilationEvent(event_kind="registered", node_id="n1")
    assert ev.event_kind == "registered"
    assert ev.node_id == "n1"


def test_g02_assimilation_event_to_dict_keys():
    ev = AssimilationEvent(event_kind="heartbeat", node_id="n1")
    d = ev.to_dict()
    for key in ("event_kind", "node_id", "timestamp", "details"):
        assert key in d, f"Missing key: {key}"


def test_g03_assimilation_event_timestamp_positive():
    ev = AssimilationEvent(event_kind="offline", node_id="n1")
    assert ev.timestamp > 0


# ===========================================================================
# H) CapabilityAssimilationLayer — assimilation
# ===========================================================================


def test_h01_assimilate_returns_record():
    layer = _layer()
    rec = layer.assimilate("node-a")
    assert isinstance(rec, AssimilationRecord)


def test_h02_assimilated_record_has_correct_node_id():
    layer = _layer()
    rec = layer.assimilate("node-b")
    assert rec.node_id == "node-b"


def test_h03_assimilate_empty_node_id_raises_value_error():
    layer = _layer()
    with pytest.raises(ValueError):
        layer.assimilate("")


def test_h04_capabilities_stored_in_descriptor():
    layer = _layer()
    rec = layer.assimilate("node-c", capabilities=["llm", "vision"])
    assert "llm" in rec.capability_descriptor.capabilities
    assert "vision" in rec.capability_descriptor.capabilities


def test_h05_participant_kind_stored_in_profile():
    layer = _layer()
    rec = layer.assimilate("node-d", participant_kind=NodeParticipantKind.WORKER)
    assert rec.execution_profile.participant_kind == NodeParticipantKind.WORKER


def test_h06_fabric_presence_online_after_assimilation():
    layer = _layer()
    rec = layer.assimilate("node-e")
    assert rec.fabric_presence.presence_state == AssimilationPresenceState.ONLINE


def test_h07_heartbeat_count_1_after_first_assimilation():
    layer = _layer()
    rec = layer.assimilate("node-f")
    assert rec.fabric_presence.heartbeat_count == 1


def test_h08_re_assimilation_updates_record():
    layer = _layer()
    layer.assimilate("node-g", capabilities=["a"])
    rec = layer.assimilate("node-g", capabilities=["a", "b"])
    assert "b" in rec.capability_descriptor.capabilities


def test_h09_re_assimilation_preserves_registered_at():
    layer = _layer()
    rec1 = layer.assimilate("node-h")
    registered_at = rec1.fabric_presence.registered_at
    rec2 = layer.assimilate("node-h")
    assert rec2.fabric_presence.registered_at == registered_at


# ===========================================================================
# I) CapabilityAssimilationLayer — heartbeat
# ===========================================================================


def test_i01_heartbeat_returns_true_for_known_node():
    layer = _layer()
    layer.assimilate("node-hb")
    assert layer.heartbeat("node-hb") is True


def test_i02_heartbeat_returns_false_for_unknown_node():
    layer = _layer()
    assert layer.heartbeat("no-such-node") is False


def test_i03_heartbeat_increments_count():
    layer = _layer()
    layer.assimilate("node-hc")
    layer.heartbeat("node-hc")
    rec = layer.get_record("node-hc")
    assert rec.fabric_presence.heartbeat_count == 2


def test_i04_heartbeat_degraded_when_health_below_0_5():
    layer = _layer()
    layer.assimilate("node-hd")
    layer.heartbeat("node-hd", health_score=0.2)
    rec = layer.get_record("node-hd")
    assert rec.fabric_presence.presence_state == AssimilationPresenceState.DEGRADED


def test_i05_heartbeat_keeps_online_when_health_ok():
    layer = _layer()
    layer.assimilate("node-he")
    layer.heartbeat("node-he", health_score=1.0)
    rec = layer.get_record("node-he")
    assert rec.fabric_presence.presence_state == AssimilationPresenceState.ONLINE


# ===========================================================================
# J) CapabilityAssimilationLayer — offline/stale
# ===========================================================================


def test_j01_mark_offline_returns_true_for_known_node():
    layer = _layer()
    layer.assimilate("node-off")
    assert layer.mark_offline("node-off") is True


def test_j02_mark_offline_returns_false_for_unknown_node():
    layer = _layer()
    assert layer.mark_offline("not-there") is False


def test_j03_mark_offline_sets_presence_offline():
    layer = _layer()
    layer.assimilate("node-off2")
    layer.mark_offline("node-off2")
    rec = layer.get_record("node-off2")
    assert rec.fabric_presence.presence_state == AssimilationPresenceState.OFFLINE


def test_j04_re_assimilation_after_offline_is_rejoin():
    layer = _layer()
    layer.assimilate("node-rj")
    layer.mark_offline("node-rj")
    layer.assimilate("node-rj")
    # Check event log contains a 'rejoin' event
    events = list(layer.get_event_log())
    kinds = [e.event_kind for e in events]
    assert "rejoin" in kinds


def test_j05_mark_stale_returns_list():
    layer = _layer()
    layer.assimilate("node-stale")
    result = layer.mark_stale_if_expired(heartbeat_ttl_secs=0.0)
    assert isinstance(result, list)


# ===========================================================================
# K) CapabilityAssimilationLayer — queries
# ===========================================================================


def test_k01_get_record_returns_record_for_known_node():
    layer = _layer()
    layer.assimilate("node-q1")
    rec = layer.get_record("node-q1")
    assert rec is not None
    assert rec.node_id == "node-q1"


def test_k02_get_record_returns_none_for_unknown_node():
    layer = _layer()
    assert layer.get_record("ghost") is None


def test_k03_list_records_returns_list():
    layer = _layer()
    layer.assimilate("node-lr1")
    layer.assimilate("node-lr2")
    recs = layer.list_records()
    assert isinstance(recs, list)
    assert len(recs) >= 2


def test_k04_list_online_records_filters_by_online():
    layer = _layer()
    layer.assimilate("node-on1")
    layer.assimilate("node-off-q")
    layer.mark_offline("node-off-q")
    online = layer.list_online_records()
    ids = [r.node_id for r in online]
    assert "node-on1" in ids
    assert "node-off-q" not in ids


def test_k05_get_capability_descriptors_returns_list():
    layer = _layer()
    layer.assimilate("node-cd1", capabilities=["x"])
    descs = layer.get_capability_descriptors()
    assert isinstance(descs, list)


def test_k06_get_execution_profiles_returns_list():
    layer = _layer()
    layer.assimilate("node-ep1")
    profiles = layer.get_execution_profiles()
    assert isinstance(profiles, list)


def test_k07_get_fabric_presences_returns_list():
    layer = _layer()
    layer.assimilate("node-fp1")
    presences = layer.get_fabric_presences()
    assert isinstance(presences, list)


# ===========================================================================
# L) Observability
# ===========================================================================


def test_l01_get_event_log_returns_deque():
    layer = _layer()
    log = layer.get_event_log()
    assert isinstance(log, deque)


def test_l02_events_appended_after_assimilation():
    layer = _layer()
    layer.assimilate("node-ev1")
    events = list(layer.get_event_log())
    assert any(e.node_id == "node-ev1" for e in events)


def test_l03_events_appended_after_heartbeat():
    layer = _layer()
    layer.assimilate("node-ev2")
    layer.heartbeat("node-ev2")
    events = list(layer.get_event_log())
    hb_events = [e for e in events if e.event_kind == "heartbeat"]
    assert len(hb_events) >= 1


def test_l04_events_appended_after_mark_offline():
    layer = _layer()
    layer.assimilate("node-ev3")
    layer.mark_offline("node-ev3")
    events = list(layer.get_event_log())
    offline_events = [e for e in events if e.event_kind == "offline"]
    assert len(offline_events) >= 1


# ===========================================================================
# M) snapshot
# ===========================================================================


def test_m01_snapshot_returns_dict():
    layer = _layer()
    snap = layer.snapshot()
    assert isinstance(snap, dict)


def test_m02_snapshot_contains_total_nodes():
    layer = _layer()
    layer.assimilate("node-sn1")
    snap = layer.snapshot()
    assert "total_nodes" in snap
    assert snap["total_nodes"] >= 1


def test_m03_snapshot_contains_by_participant_kind():
    layer = _layer()
    layer.assimilate("node-sn2")
    snap = layer.snapshot()
    assert "by_participant_kind" in snap


def test_m04_snapshot_contains_by_presence_state():
    layer = _layer()
    layer.assimilate("node-sn3")
    snap = layer.snapshot()
    assert "by_presence_state" in snap


def test_m05_snapshot_authority_matches_sentinel():
    layer = _layer()
    snap = layer.snapshot()
    assert snap.get("authority") == CAPABILITY_ASSIMILATION_AUTHORITY


# ===========================================================================
# N) assimilate_from_node_info — dict input
# ===========================================================================


def test_n01_from_node_info_dict_input():
    layer = _layer()
    rec = layer.assimilate_from_node_info({"node_id": "dict-node", "capabilities": ["foo"]})
    assert rec.node_id == "dict-node"


def test_n02_from_node_info_dict_capabilities_extracted():
    layer = _layer()
    rec = layer.assimilate_from_node_info({"node_id": "dict-node2", "capabilities": ["bar", "baz"]})
    assert "bar" in rec.capability_descriptor.capabilities


# ===========================================================================
# O) assimilate_node convenience helper
# ===========================================================================


def test_o01_assimilate_node_dict():
    rec = assimilate_node({"node_id": "helper-node", "capabilities": ["x"]})
    assert isinstance(rec, AssimilationRecord)
    assert rec.node_id == "helper-node"


def test_o02_assimilate_node_object():
    class FakeNode:
        node_id = "obj-node"
        capabilities = []
        host = "localhost"
        port = 0
        role = type("R", (), {"value": "worker"})()
        architectural_class = type("A", (), {"value": "capability_node"})()
        metadata = {}

    rec = assimilate_node(FakeNode())
    assert isinstance(rec, AssimilationRecord)
    assert rec.node_id == "obj-node"


# ===========================================================================
# P) Singleton behaviour
# ===========================================================================


def test_p01_get_layer_returns_same_instance():
    a = get_capability_assimilation_layer()
    b = get_capability_assimilation_layer()
    assert a is b


def test_p02_reset_creates_new_instance():
    a = get_capability_assimilation_layer()
    reset_capability_assimilation_layer()
    b = get_capability_assimilation_layer()
    assert a is not b
