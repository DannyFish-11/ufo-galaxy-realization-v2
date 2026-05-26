from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from core.canonical_cross_repo_evidence_pipeline import PipelineVerdict
from core.device_autonomy_evidence import classify_device_autonomy
from core.device_dispatch_readiness_surface import get_device_dispatch_readiness
from core.network_graph_runtime import NetworkNode, reset_network_graph_runtime
from core.network_topology_runtime import (
    TopologyConnectionState,
    TopologyEdge,
    TopologyEdgeKind,
    TopologyNode,
    TopologyNodeKind,
    build_grounded_runtime_topology,
    reset_network_topology_runtime,
)
from core.nodes.node_fabric_registry import (
    NodeArchitecturalClass,
    NodeCapability,
    NodeInfo,
    NodeRole,
    NodeStatus,
    reset_node_fabric_registry,
)
from core.runtime_restart_recovery import RuntimeRestartRecoveryCoordinator
from core.runtime_truth_governance import (
    TRUTH_GRADE_DURABLE,
    TRUTH_GRADE_PROJECTION,
    TRUTH_GRADE_RECOVERABLE,
)


def test_node_fabric_registry_restore_requires_revalidation(tmp_path, monkeypatch):
    import core.nodes.node_fabric_registry as node_mod

    state_path = str(tmp_path / "node_fabric_registry_state.json")
    monkeypatch.setattr(node_mod, "_DEFAULT_NODE_FABRIC_STATE_PATH", state_path)
    reset_node_fabric_registry(clear_durable_state=True)

    registry = node_mod.get_node_fabric_registry()
    registry.register(
        NodeInfo(
            node_id="node-alpha",
            role=NodeRole.AGENT,
            architectural_class=NodeArchitecturalClass.CAPABILITY_NODE,
            status=NodeStatus.HEALTHY,
            host="127.0.0.1",
            port=7777,
            capabilities=[NodeCapability(name="infer")],
        )
    )

    reset_node_fabric_registry()
    restored_registry = node_mod.get_node_fabric_registry()
    assert restored_registry.restore_durable_state() == 1

    restored = restored_registry.get("node-alpha")
    assert restored is not None
    assert restored.status == NodeStatus.OFFLINE
    assert restored.to_dict()["truth_governance"]["truth_grade"] == TRUTH_GRADE_RECOVERABLE
    assert restored_registry.get_metrics()["truth_governance"]["revalidation_pending_count"] == 1


def test_network_graph_and_topology_restore_as_degraded_views(tmp_path, monkeypatch):
    import core.network_graph_runtime as graph_mod
    import core.network_topology_runtime as topo_mod

    monkeypatch.setattr(
        graph_mod,
        "_DEFAULT_NETWORK_GRAPH_STATE_PATH",
        str(tmp_path / "network_graph_runtime_state.json"),
    )
    monkeypatch.setattr(
        topo_mod,
        "_DEFAULT_NETWORK_TOPOLOGY_STATE_PATH",
        str(tmp_path / "network_topology_runtime_state.json"),
    )
    reset_network_graph_runtime(clear_durable_state=True)
    reset_network_topology_runtime(clear_durable_state=True)

    graph_runtime = graph_mod.get_network_graph_runtime()
    graph_runtime.register_node(NetworkNode(node_id="graph-node"))

    topo_runtime = topo_mod.get_network_topology_runtime()
    topo_runtime.register_node(
        TopologyNode(
            node_id="device-1",
            kind=TopologyNodeKind.DEVICE,
            state=TopologyConnectionState.CONNECTED,
        )
    )
    topo_runtime.register_edge(
        TopologyEdge(
            edge_id="device-1::direct",
            source_node_id="gateway",
            target_node_id="device-1",
            kind=TopologyEdgeKind.DIRECT,
            state=TopologyConnectionState.PREFERRED,
            preferred=True,
        )
    )

    reset_network_graph_runtime()
    reset_network_topology_runtime()

    restored_graph = graph_mod.get_network_graph_runtime()
    restored_topology = topo_mod.get_network_topology_runtime()
    assert restored_graph.restore_durable_state() == {"nodes_restored": 1, "edges_restored": 0}
    assert restored_topology.restore_durable_state() == {"nodes_restored": 1, "edges_restored": 1}

    graph_snapshot = restored_graph.snapshot().to_dict()
    topology_snapshot = restored_topology.snapshot().to_dict()
    grounded = build_grounded_runtime_topology().to_dict()

    assert graph_snapshot["truth_governance"]["revalidation_required"] is True
    assert topology_snapshot["truth_governance"]["degraded"] is True
    assert restored_topology.get_node("device-1").state == TopologyConnectionState.DEGRADED
    assert grounded["truth_governance"]["truth_grade"] == TRUTH_GRADE_PROJECTION


def test_runtime_recovery_coordinator_restores_governed_runtime_surfaces(tmp_path, monkeypatch):
    import core.network_graph_runtime as graph_mod
    import core.network_topology_runtime as topo_mod
    import core.nodes.node_fabric_registry as node_mod

    monkeypatch.setattr(node_mod, "_DEFAULT_NODE_FABRIC_STATE_PATH", str(tmp_path / "nodes.json"))
    monkeypatch.setattr(graph_mod, "_DEFAULT_NETWORK_GRAPH_STATE_PATH", str(tmp_path / "graph.json"))
    monkeypatch.setattr(topo_mod, "_DEFAULT_NETWORK_TOPOLOGY_STATE_PATH", str(tmp_path / "topology.json"))
    reset_node_fabric_registry(clear_durable_state=True)
    reset_network_graph_runtime(clear_durable_state=True)
    reset_network_topology_runtime(clear_durable_state=True)

    node_mod.get_node_fabric_registry().register(
        NodeInfo(node_id="node-r1", role=NodeRole.WORKER, status=NodeStatus.HEALTHY)
    )
    graph_mod.get_network_graph_runtime().register_node(NetworkNode(node_id="node-r1"))
    topo_mod.get_network_topology_runtime().register_node(
        TopologyNode(node_id="node-r1", kind=TopologyNodeKind.RUNTIME_PROVIDER_NODE)
    )

    reset_node_fabric_registry()
    reset_network_graph_runtime()
    reset_network_topology_runtime()

    coord = RuntimeRestartRecoveryCoordinator()
    for name in (
        "_recover_mesh_sessions",
        "_recover_body_mesh",
        "_clear_webrtc_bindings",
        "_recover_hybrid_orchestration",
        "_recover_inflight_tasks",
        "_recover_session_truth",
        "_reconcile_continuation_waiters",
        "_verify_durable_truth_convergence",
        "_consolidate_multi_participant_recovery",
        "_verify_result_continuity_guard",
        "_evaluate_task_continuity",
    ):
        monkeypatch.setattr(coord, name, lambda report, _name=name: None)

    report = coord.run_recovery()

    assert report.node_registry_entries_restored == 1
    assert report.network_graph_nodes_restored == 1
    assert report.topology_nodes_restored == 1
    assert "node_registry" in report.degraded_recovery_surfaces
    assert "network_topology_runtime" in report.degraded_recovery_surfaces


def test_support_readiness_and_autonomy_surfaces_expose_truth_governance():
    readiness_payload = {
        "device_id": "android-01",
        "dispatch_ready": False,
        "registered": True,
        "status": "blocked_operational_support",
        "reason": "blocked",
        "registration_gaps": [],
        "attachment_state": "active",
        "runtime_session_id": "sess-1",
        "runtime_attachment_session_id": "attach-1",
        "transport_alive": True,
        "blocking_notes": [],
        "operational_support_status": "near_peer_operational",
    }
    complete_report = SimpleNamespace(
        pipeline_verdict=PipelineVerdict.complete,
        is_complete=True,
    )
    participation = SimpleNamespace(
        tier=SimpleNamespace(value="dispatch_eligible"),
        readiness_satisfied=True,
        dispatch_gate_passed=True,
        active_session_count=1,
        websocket_connected=True,
    )
    host_identity = SimpleNamespace(
        source_runtime_posture="join_runtime",
        role=SimpleNamespace(value="full_runtime_host"),
    )
    support_verdict = SimpleNamespace(
        to_dict=lambda: {
            "device_type": "android",
            "support_tier": "near_peer_operational",
            "dispatch_target_capable": True,
            "truth_grade": TRUTH_GRADE_DURABLE,
        }
    )
    readiness_result = SimpleNamespace(to_dict=lambda: dict(readiness_payload))

    with (
        patch(
            "core.unified_dispatch_readiness_gate.evaluate_dispatch_readiness",
            return_value=readiness_result,
        ),
        patch("core.device_dispatch_readiness_surface.time.time", return_value=1005.0),
    ):
        readiness = get_device_dispatch_readiness("android-01")

    with (
        patch(
            "core.device_autonomy_evidence.build_canonical_cross_repo_evidence_report",
            return_value=complete_report,
        ),
        patch(
            "core.device_autonomy_evidence.get_participation_state_for_device",
            return_value=participation,
        ),
        patch(
            "core.device_autonomy_evidence.build_android_runtime_host_identity",
            return_value=host_identity,
        ),
        patch(
            "core.device_autonomy_evidence.get_device_operational_support",
            return_value=support_verdict,
        ),
        patch(
            "core.device_autonomy_evidence.get_device_state_snapshot",
            return_value=object(),
        ),
        patch(
            "core.device_autonomy_evidence._build_allocation_evidence",
            return_value={
                "accepted_tasks": 3,
                "closed_tasks": 3,
                "fallback_count": 0,
                "latest_closed_at": 1000.0,
                "continuity_span_seconds": 30.0,
            },
        ),
        patch(
            "core.device_autonomy_evidence._build_tracker_evidence",
            return_value={
                "tracking_records": 3,
                "completed_results": 3,
                "failed_results": 0,
                "recovered_unrevalidated": 0,
                "recovered_stale": 0,
                "latest_updated_at": 1000.0,
                "runtime_snapshot": {},
            },
        ),
        patch(
            "core.device_autonomy_evidence._build_event_evidence",
            return_value={
                "event_count": 3,
                "completed_events": 3,
                "terminal_events": 3,
                "latest_event_at": 1000.0,
            },
        ),
        patch("core.device_autonomy_evidence.time.time", return_value=1005.0),
    ):
        autonomy = classify_device_autonomy("android-01")

    assert readiness["truth_governance"]["truth_grade"] == TRUTH_GRADE_PROJECTION
    assert autonomy["truth_governance"]["field_truth_grades"]["support"] == TRUTH_GRADE_DURABLE
