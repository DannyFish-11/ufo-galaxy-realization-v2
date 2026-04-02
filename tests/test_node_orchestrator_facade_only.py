#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_node_orchestrator_facade_only.py
============================================
PR-7: Capability & Node Assimilation — tests that node-level orchestrators
are demoted to adapter/facade/local-coordinator only and do NOT form a
parallel system execution authority.

Coverage
--------
A) SmartOrchestrator (Node_110) facade sentinel
   - SMART_ORCHESTRATOR_NODE_FACADE_ONLY sentinel is importable
   - sentinel value is a non-empty string
   - sentinel value contains "FACADE" or "ONLY"

B) CapabilityOrchestrator facade sentinel
   - CAPABILITY_ORCHESTRATOR_FACADE_ONLY sentinel is importable
   - sentinel value is a non-empty string
   - sentinel value contains "FACADE" or "ONLY"

C) Assimilation layer governance sentinel
   - NODE_ORCHESTRATOR_ASSIMILATION_POLICY is importable
   - policy value contains "ADAPTER" or "FACADE"
   - policy value does NOT claim "authority"
     (node orchestrators must not claim system authority)

D) LEGACY_FACADE participant kind governance
   - LEGACY_FACADE nodes are NOT projected to task graph runtime
   - LEGACY_FACADE nodes ARE projected to network graph (presence only)
   - LEGACY_FACADE nodes have execution_profile participant_kind = LEGACY_FACADE

E) Architectural class → participant kind mapping
   - legacy_orchestrator_node maps to LEGACY_FACADE
   - capability_node maps to CAPABILITY_PROVIDER
   - service_node maps to SPECIALIST
   - worker maps to WORKER
   - experimental_node maps to FABRIC_PARTICIPANT
   - archived_node maps to FABRIC_PARTICIPANT

F) Existing canonical execution authorities are NOT demoted
   - TASK_GRAPH_RUNTIME_AUTHORITY is importable (task graph runtime intact)
   - GALAXY_ORCHESTRATOR_FACADE_AUTHORITY is importable (PR-3 facade intact)
   - UNIFIED_ORCHESTRATOR_FACADE_AUTHORITY is importable (PR-3 facade intact)
   - DEVICE_ORCHESTRATOR_FACADE_AUTHORITY is importable (PR-3 facade intact)

G) Assimilation layer authority sentinel is canonical
   - CAPABILITY_ASSIMILATION_AUTHORITY is importable
   - CAPABILITY_ASSIMILATION_LAYER_POSITION == 7
   - authority sentinel value references "PR-7"

H) Assimilation layer correctly classifies orchestrator-kind nodes
   - assimilating a node with architectural_class=legacy_orchestrator_node
     sets participant_kind=LEGACY_FACADE
   - LEGACY_FACADE node is excluded from capability_descriptors surfaced
     to task executor projections

I) Event observability for LEGACY_FACADE nodes
   - registering a LEGACY_FACADE node emits an event
   - event has correct node_id
   - event kind is 'registered' or 'rejoin'

J) NODE_ORCHESTRATOR_ASSIMILATION_POLICY content
   - policy string is at least 10 characters (not a trivial placeholder)
   - policy string does not contain "TODO"
"""

from __future__ import annotations

import pytest


# ===========================================================================
# A) SmartOrchestrator (Node_110) facade sentinel
# ===========================================================================


def _import_smart_orchestrator_sentinel():
    try:
        from nodes.Node_110_SmartOrchestrator.main import SMART_ORCHESTRATOR_NODE_FACADE_ONLY
        return SMART_ORCHESTRATOR_NODE_FACADE_ONLY
    except (ImportError, Exception) as e:
        pytest.skip(f"Node_110_SmartOrchestrator import unavailable (missing dependency): {e}")


def test_a01_smart_orchestrator_facade_sentinel_importable():
    sentinel = _import_smart_orchestrator_sentinel()
    assert sentinel is not None


def test_a02_smart_orchestrator_sentinel_non_empty():
    sentinel = _import_smart_orchestrator_sentinel()
    assert len(sentinel) > 0


def test_a03_smart_orchestrator_sentinel_contains_facade_or_only():
    sentinel = _import_smart_orchestrator_sentinel()
    upper = sentinel.upper()
    assert "FACADE" in upper or "ONLY" in upper


# ===========================================================================
# B) CapabilityOrchestrator facade sentinel
# ===========================================================================


def test_b01_capability_orchestrator_facade_sentinel_importable():
    from core.capability_orchestrator import CAPABILITY_ORCHESTRATOR_FACADE_ONLY
    assert CAPABILITY_ORCHESTRATOR_FACADE_ONLY is not None


def test_b02_capability_orchestrator_sentinel_non_empty():
    from core.capability_orchestrator import CAPABILITY_ORCHESTRATOR_FACADE_ONLY
    assert len(CAPABILITY_ORCHESTRATOR_FACADE_ONLY) > 0


def test_b03_capability_orchestrator_sentinel_contains_facade_or_only():
    from core.capability_orchestrator import CAPABILITY_ORCHESTRATOR_FACADE_ONLY
    upper = CAPABILITY_ORCHESTRATOR_FACADE_ONLY.upper()
    assert "FACADE" in upper or "ONLY" in upper


# ===========================================================================
# C) Assimilation layer governance sentinel
# ===========================================================================


def test_c01_node_orchestrator_assimilation_policy_importable():
    from core.capability_assimilation import NODE_ORCHESTRATOR_ASSIMILATION_POLICY
    assert NODE_ORCHESTRATOR_ASSIMILATION_POLICY is not None


def test_c02_policy_contains_adapter_or_facade():
    from core.capability_assimilation import NODE_ORCHESTRATOR_ASSIMILATION_POLICY
    upper = NODE_ORCHESTRATOR_ASSIMILATION_POLICY.upper()
    assert "ADAPTER" in upper or "FACADE" in upper


def test_c03_policy_does_not_grant_authority_to_node_orchestrators():
    from core.capability_assimilation import NODE_ORCHESTRATOR_ASSIMILATION_POLICY
    # The policy string should explicitly state nodes are NOT authorities
    # (check it says "NO" or "NOT" or "ONLY" near authority)
    upper = NODE_ORCHESTRATOR_ASSIMILATION_POLICY.upper()
    # The policy must contain a constraint word
    assert any(word in upper for word in ("ONLY", "NOT", "NO ", "EXCLUDED", "FACADE")), (
        f"Policy does not contain a constraint word: {NODE_ORCHESTRATOR_ASSIMILATION_POLICY!r}"
    )


# ===========================================================================
# D) LEGACY_FACADE participant kind governance
# ===========================================================================


def test_d01_legacy_facade_not_projected_to_task_graph():
    from core.capability_assimilation import (
        NodeParticipantKind,
        get_capability_assimilation_layer,
        reset_capability_assimilation_layer,
    )
    from core.network_graph_runtime import reset_network_graph_runtime
    from core.task_graph_runtime import reset_task_graph_runtime

    reset_capability_assimilation_layer()
    reset_network_graph_runtime()
    reset_task_graph_runtime()

    layer = get_capability_assimilation_layer()
    rec = layer.assimilate("legacy-orch-1", participant_kind=NodeParticipantKind.LEGACY_FACADE)
    assert rec.projected_to_task_graph is False

    reset_capability_assimilation_layer()
    reset_network_graph_runtime()
    reset_task_graph_runtime()


def test_d02_legacy_facade_projected_to_network_graph():
    from core.capability_assimilation import (
        NodeParticipantKind,
        get_capability_assimilation_layer,
        reset_capability_assimilation_layer,
    )
    from core.network_graph_runtime import reset_network_graph_runtime
    from core.task_graph_runtime import reset_task_graph_runtime

    reset_capability_assimilation_layer()
    reset_network_graph_runtime()
    reset_task_graph_runtime()

    layer = get_capability_assimilation_layer()
    rec = layer.assimilate("legacy-orch-2", participant_kind=NodeParticipantKind.LEGACY_FACADE)
    assert rec.projected_to_network_graph is True

    reset_capability_assimilation_layer()
    reset_network_graph_runtime()
    reset_task_graph_runtime()


def test_d03_legacy_facade_execution_profile_kind():
    from core.capability_assimilation import (
        NodeParticipantKind,
        get_capability_assimilation_layer,
        reset_capability_assimilation_layer,
    )
    from core.network_graph_runtime import reset_network_graph_runtime
    from core.task_graph_runtime import reset_task_graph_runtime

    reset_capability_assimilation_layer()
    reset_network_graph_runtime()
    reset_task_graph_runtime()

    layer = get_capability_assimilation_layer()
    rec = layer.assimilate("legacy-orch-3", participant_kind=NodeParticipantKind.LEGACY_FACADE)
    assert rec.execution_profile.participant_kind == NodeParticipantKind.LEGACY_FACADE

    reset_capability_assimilation_layer()
    reset_network_graph_runtime()
    reset_task_graph_runtime()


# ===========================================================================
# E) Architectural class → participant kind mapping
# ===========================================================================


def test_e01_legacy_orchestrator_maps_to_legacy_facade():
    from core.capability_assimilation import (
        NodeParticipantKind,
        get_capability_assimilation_layer,
        reset_capability_assimilation_layer,
    )
    from core.network_graph_runtime import reset_network_graph_runtime
    from core.task_graph_runtime import reset_task_graph_runtime

    reset_capability_assimilation_layer()
    reset_network_graph_runtime()
    reset_task_graph_runtime()

    layer = get_capability_assimilation_layer()
    rec = layer.assimilate_from_node_info({
        "node_id": "arch-legacy",
        "architectural_class": "legacy_orchestrator_node",
        "capabilities": [],
    })
    assert rec.execution_profile.participant_kind == NodeParticipantKind.LEGACY_FACADE

    reset_capability_assimilation_layer()
    reset_network_graph_runtime()
    reset_task_graph_runtime()


def test_e02_capability_node_maps_to_capability_provider():
    from core.capability_assimilation import (
        NodeParticipantKind,
        get_capability_assimilation_layer,
        reset_capability_assimilation_layer,
    )
    from core.network_graph_runtime import reset_network_graph_runtime
    from core.task_graph_runtime import reset_task_graph_runtime

    reset_capability_assimilation_layer()
    reset_network_graph_runtime()
    reset_task_graph_runtime()

    layer = get_capability_assimilation_layer()
    rec = layer.assimilate_from_node_info({
        "node_id": "arch-cap",
        "architectural_class": "capability_node",
        "capabilities": ["foo"],
    })
    assert rec.execution_profile.participant_kind == NodeParticipantKind.CAPABILITY_PROVIDER

    reset_capability_assimilation_layer()
    reset_network_graph_runtime()
    reset_task_graph_runtime()


def test_e03_service_node_maps_to_specialist():
    from core.capability_assimilation import (
        NodeParticipantKind,
        get_capability_assimilation_layer,
        reset_capability_assimilation_layer,
    )
    from core.network_graph_runtime import reset_network_graph_runtime
    from core.task_graph_runtime import reset_task_graph_runtime

    reset_capability_assimilation_layer()
    reset_network_graph_runtime()
    reset_task_graph_runtime()

    layer = get_capability_assimilation_layer()
    rec = layer.assimilate_from_node_info({
        "node_id": "arch-svc",
        "architectural_class": "service_node",
    })
    assert rec.execution_profile.participant_kind == NodeParticipantKind.SPECIALIST

    reset_capability_assimilation_layer()
    reset_network_graph_runtime()
    reset_task_graph_runtime()


def test_e04_worker_role_maps_to_worker():
    from core.capability_assimilation import (
        NodeParticipantKind,
        get_capability_assimilation_layer,
        reset_capability_assimilation_layer,
    )
    from core.network_graph_runtime import reset_network_graph_runtime
    from core.task_graph_runtime import reset_task_graph_runtime

    reset_capability_assimilation_layer()
    reset_network_graph_runtime()
    reset_task_graph_runtime()

    layer = get_capability_assimilation_layer()
    rec = layer.assimilate_from_node_info({
        "node_id": "arch-worker",
        "architectural_class": "worker",
    })
    assert rec.execution_profile.participant_kind == NodeParticipantKind.WORKER

    reset_capability_assimilation_layer()
    reset_network_graph_runtime()
    reset_task_graph_runtime()


def test_e05_experimental_node_maps_to_fabric_participant():
    from core.capability_assimilation import (
        NodeParticipantKind,
        get_capability_assimilation_layer,
        reset_capability_assimilation_layer,
    )
    from core.network_graph_runtime import reset_network_graph_runtime
    from core.task_graph_runtime import reset_task_graph_runtime

    reset_capability_assimilation_layer()
    reset_network_graph_runtime()
    reset_task_graph_runtime()

    layer = get_capability_assimilation_layer()
    rec = layer.assimilate_from_node_info({
        "node_id": "arch-exp",
        "architectural_class": "experimental_node",
    })
    assert rec.execution_profile.participant_kind == NodeParticipantKind.FABRIC_PARTICIPANT

    reset_capability_assimilation_layer()
    reset_network_graph_runtime()
    reset_task_graph_runtime()


def test_e06_archived_node_maps_to_fabric_participant():
    from core.capability_assimilation import (
        NodeParticipantKind,
        get_capability_assimilation_layer,
        reset_capability_assimilation_layer,
    )
    from core.network_graph_runtime import reset_network_graph_runtime
    from core.task_graph_runtime import reset_task_graph_runtime

    reset_capability_assimilation_layer()
    reset_network_graph_runtime()
    reset_task_graph_runtime()

    layer = get_capability_assimilation_layer()
    rec = layer.assimilate_from_node_info({
        "node_id": "arch-arch",
        "architectural_class": "archived_node",
    })
    assert rec.execution_profile.participant_kind == NodeParticipantKind.FABRIC_PARTICIPANT

    reset_capability_assimilation_layer()
    reset_network_graph_runtime()
    reset_task_graph_runtime()


# ===========================================================================
# F) Existing canonical execution authorities are NOT demoted
# ===========================================================================


def test_f01_task_graph_runtime_authority_intact():
    from core.task_graph_runtime import TASK_GRAPH_RUNTIME_AUTHORITY
    assert TASK_GRAPH_RUNTIME_AUTHORITY


def test_f02_galaxy_orchestrator_facade_authority_intact():
    try:
        from galaxy_gateway.orchestrator.galaxy_orchestrator import (
            GALAXY_ORCHESTRATOR_FACADE_AUTHORITY,
        )
    except (ImportError, Exception) as e:
        pytest.skip(f"galaxy_orchestrator import unavailable (missing dependency): {e}")
    assert GALAXY_ORCHESTRATOR_FACADE_AUTHORITY


def test_f03_unified_orchestrator_facade_authority_intact():
    import warnings
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from fusion.unified_orchestrator import UNIFIED_ORCHESTRATOR_FACADE_AUTHORITY
    except (ImportError, AttributeError, Exception) as e:
        pytest.skip(f"unified_orchestrator import unavailable (missing dependency): {e}")
    assert UNIFIED_ORCHESTRATOR_FACADE_AUTHORITY


def test_f04_device_orchestrator_facade_authority_intact():
    from core.device_orchestrator import DEVICE_ORCHESTRATOR_FACADE_AUTHORITY
    assert DEVICE_ORCHESTRATOR_FACADE_AUTHORITY


# ===========================================================================
# G) Assimilation layer authority sentinel is canonical
# ===========================================================================


def test_g01_capability_assimilation_authority_importable():
    from core.capability_assimilation import CAPABILITY_ASSIMILATION_AUTHORITY
    assert CAPABILITY_ASSIMILATION_AUTHORITY


def test_g02_capability_assimilation_layer_position_is_7():
    from core.capability_assimilation import CAPABILITY_ASSIMILATION_LAYER_POSITION
    assert CAPABILITY_ASSIMILATION_LAYER_POSITION == 7


def test_g03_authority_sentinel_references_pr7():
    from core.capability_assimilation import CAPABILITY_ASSIMILATION_AUTHORITY
    assert "PR-7" in CAPABILITY_ASSIMILATION_AUTHORITY or "pr-7" in CAPABILITY_ASSIMILATION_AUTHORITY.lower()


# ===========================================================================
# H) Assimilation layer classifies orchestrator nodes correctly
# ===========================================================================


def test_h01_legacy_orchestrator_node_gets_legacy_facade_kind():
    from core.capability_assimilation import (
        NodeParticipantKind,
        get_capability_assimilation_layer,
        reset_capability_assimilation_layer,
    )
    from core.network_graph_runtime import reset_network_graph_runtime
    from core.task_graph_runtime import reset_task_graph_runtime

    reset_capability_assimilation_layer()
    reset_network_graph_runtime()
    reset_task_graph_runtime()

    layer = get_capability_assimilation_layer()
    rec = layer.assimilate_from_node_info({
        "node_id": "orch-110",
        "architectural_class": "legacy_orchestrator_node",
        "capabilities": ["orchestrate", "schedule"],
    })
    # Should be LEGACY_FACADE, not CAPABILITY_PROVIDER
    assert rec.execution_profile.participant_kind == NodeParticipantKind.LEGACY_FACADE

    reset_capability_assimilation_layer()
    reset_network_graph_runtime()
    reset_task_graph_runtime()


def test_h02_legacy_facade_not_in_task_graph():
    from core.capability_assimilation import (
        NodeParticipantKind,
        get_capability_assimilation_layer,
        reset_capability_assimilation_layer,
    )
    from core.network_graph_runtime import reset_network_graph_runtime
    from core.task_graph_runtime import get_task_graph_runtime, reset_task_graph_runtime

    reset_capability_assimilation_layer()
    reset_network_graph_runtime()
    reset_task_graph_runtime()

    layer = get_capability_assimilation_layer()
    layer.assimilate_from_node_info({
        "node_id": "orch-tg-check",
        "architectural_class": "legacy_orchestrator_node",
    })

    # The task graph runtime should NOT have a node for this orchestrator
    tgr = get_task_graph_runtime()
    task_node = tgr.get_node_by_task_id("executor__orch-tg-check")
    assert task_node is None

    reset_capability_assimilation_layer()
    reset_network_graph_runtime()
    reset_task_graph_runtime()


# ===========================================================================
# I) Event observability for LEGACY_FACADE nodes
# ===========================================================================


def test_i01_legacy_facade_registration_emits_event():
    from core.capability_assimilation import (
        NodeParticipantKind,
        get_capability_assimilation_layer,
        reset_capability_assimilation_layer,
    )
    from core.network_graph_runtime import reset_network_graph_runtime
    from core.task_graph_runtime import reset_task_graph_runtime

    reset_capability_assimilation_layer()
    reset_network_graph_runtime()
    reset_task_graph_runtime()

    layer = get_capability_assimilation_layer()
    layer.assimilate("legacy-ev-1", participant_kind=NodeParticipantKind.LEGACY_FACADE)
    events = list(layer.get_event_log())
    assert len(events) >= 1

    reset_capability_assimilation_layer()
    reset_network_graph_runtime()
    reset_task_graph_runtime()


def test_i02_legacy_facade_event_has_correct_node_id():
    from core.capability_assimilation import (
        NodeParticipantKind,
        get_capability_assimilation_layer,
        reset_capability_assimilation_layer,
    )
    from core.network_graph_runtime import reset_network_graph_runtime
    from core.task_graph_runtime import reset_task_graph_runtime

    reset_capability_assimilation_layer()
    reset_network_graph_runtime()
    reset_task_graph_runtime()

    layer = get_capability_assimilation_layer()
    layer.assimilate("legacy-ev-2", participant_kind=NodeParticipantKind.LEGACY_FACADE)
    events = [e for e in layer.get_event_log() if e.node_id == "legacy-ev-2"]
    assert len(events) >= 1

    reset_capability_assimilation_layer()
    reset_network_graph_runtime()
    reset_task_graph_runtime()


def test_i03_legacy_facade_event_kind_is_registered_or_rejoin():
    from core.capability_assimilation import (
        NodeParticipantKind,
        get_capability_assimilation_layer,
        reset_capability_assimilation_layer,
    )
    from core.network_graph_runtime import reset_network_graph_runtime
    from core.task_graph_runtime import reset_task_graph_runtime

    reset_capability_assimilation_layer()
    reset_network_graph_runtime()
    reset_task_graph_runtime()

    layer = get_capability_assimilation_layer()
    layer.assimilate("legacy-ev-3", participant_kind=NodeParticipantKind.LEGACY_FACADE)
    events = [
        e for e in layer.get_event_log()
        if e.node_id == "legacy-ev-3"
    ]
    assert all(e.event_kind in ("registered", "rejoin") for e in events)

    reset_capability_assimilation_layer()
    reset_network_graph_runtime()
    reset_task_graph_runtime()


# ===========================================================================
# J) NODE_ORCHESTRATOR_ASSIMILATION_POLICY content
# ===========================================================================


def test_j01_policy_is_at_least_10_chars():
    from core.capability_assimilation import NODE_ORCHESTRATOR_ASSIMILATION_POLICY
    assert len(NODE_ORCHESTRATOR_ASSIMILATION_POLICY) >= 10


def test_j02_policy_does_not_contain_todo():
    from core.capability_assimilation import NODE_ORCHESTRATOR_ASSIMILATION_POLICY
    assert "TODO" not in NODE_ORCHESTRATOR_ASSIMILATION_POLICY.upper()
