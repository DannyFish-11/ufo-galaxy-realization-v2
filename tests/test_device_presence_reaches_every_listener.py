"""tests/test_device_presence_reaches_every_listener.py — 设备 / 节点的上下线与心跳真的通知到了。

各方都写好了「上线 / 离线 / 心跳」的接收方法，却没人调：网络拓扑里设备永远没有连接状态，
能力同化层只知道「注册过」、不知道掉线，重连的设备带着旧失败样本被打低分，掉线的设备仍挂在
Mesh 编组里，节点停了路由仍当它在线，传输换路 / 断路从不写回拓扑，通用参与方从不进 Mesh 编组。

另钉一个顺手修掉的缺陷：EventBridge 曾把 DeviceCommunication 的回调**列表**整个换成一个函数，
之后每次设备连上，``list(函数)`` 抛 TypeError，登记的回调一个也不跑。
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest


@pytest.fixture
def fresh():
    from core.capability_assimilation import reset_capability_assimilation_layer
    from core.device_formation.formation_auto_enrollment import reset_formation_auto_enrollment_manager
    from core.mesh.mesh_auto_enrollment import reset_auto_enrollment_service
    from core.network_topology_runtime import reset_network_topology_runtime
    from core.unified.device_health import reset_device_health_scorer
    from core.unified.device_manager import reset_unified_device_manager

    resets = (
        reset_capability_assimilation_layer,
        reset_formation_auto_enrollment_manager,
        reset_auto_enrollment_service,
        reset_network_topology_runtime,
        reset_device_health_scorer,
        reset_unified_device_manager,
    )
    for r in resets:
        r()
    yield
    for r in resets:
        r()


def _register(device_id: str):
    from core.unified.device_manager import get_unified_device_manager

    udm = get_unified_device_manager()
    udm.register_device_from_dict(device_id, {"device_type": "linux", "capabilities": ["screen"], "ip": "10.0.0.9"})
    return udm


def _presence(device_id: str) -> str:
    from core.capability_assimilation import get_capability_assimilation_layer

    record = get_capability_assimilation_layer().get_record(device_id)
    return record.fabric_presence.presence_state.value if record else "absent"


class TestUdmPresenceFanOut:
    def test_registration_puts_the_device_into_the_topology_and_online(self, fresh):
        from core.network_topology_runtime import get_network_topology_runtime

        _register("dev-up")
        assert get_network_topology_runtime().get_node("dev-up") is not None
        assert _presence("dev-up") == "online"

    def test_going_offline_reaches_assimilation_and_the_mesh(self, fresh, monkeypatch):
        import core.mesh.mesh_auto_enrollment as mae
        from core.unified.models import UnifiedDeviceStatus

        lost = []
        monkeypatch.setattr(mae, "notify_device_lost", lambda device_id, reason=None: lost.append((device_id, reason)))
        udm = _register("dev-down")
        mae.notify_device_registered("dev-down")  # 在编组里
        _register("dev-loner")  # 不在编组里

        udm.update_device_status("dev-down", UnifiedDeviceStatus.OFFLINE)
        udm.update_device_status("dev-loner", UnifiedDeviceStatus.OFFLINE)
        assert _presence("dev-down") == "offline"
        assert lost == [("dev-down", "status_update")]

    def test_reconnect_clears_old_health_samples_and_heartbeats_refresh_presence(self, fresh):
        from core.capability_assimilation import get_capability_assimilation_layer
        from core.unified.device_health import get_device_health_scorer
        from core.unified.models import UnifiedDeviceStatus

        udm = _register("dev-back")
        scorer = get_device_health_scorer()
        for _ in range(5):
            scorer.update("dev-back", latency_ms=5000, error=True)
        udm.update_device_status("dev-back", UnifiedDeviceStatus.OFFLINE)

        udm.heartbeat("dev-back")  # 回来了
        assert _presence("dev-back") == "online"
        assert scorer.score("dev-back").sample_count <= 1  # 掉线前的失败样本清掉了

        before = get_capability_assimilation_layer().get_record("dev-back").fabric_presence.heartbeat_count
        udm.heartbeat("dev-back")
        after = get_capability_assimilation_layer().get_record("dev-back").fabric_presence.heartbeat_count
        assert after > before

    def test_heartbeat_timeout_and_unregister_mark_offline(self, fresh):
        from datetime import datetime, timedelta, timezone

        udm = _register("dev-timeout")
        udm.get_device("dev-timeout").last_heartbeat = datetime.now(timezone.utc) - timedelta(hours=1)
        assert "dev-timeout" in asyncio.run(udm.check_heartbeat_timeouts(timeout_secs=1, grace_secs=1))
        assert _presence("dev-timeout") == "offline"

        _register("dev-leave")
        udm.unregister_device("dev-leave")
        assert _presence("dev-leave") == "offline"


class TestParticipantsJoinTheMesh:
    def test_admitted_participant_is_enrolled_and_confirmed_ready(self, fresh):
        import core.participant_admission as pa
        from core.mesh.mesh_auto_enrollment import get_enrollment_record

        device_id = f"box_{uuid.uuid4().hex[:6]}"
        outcome = pa.admit_participant(
            pa.ParticipantDescriptor(device_id=device_id, device_type="linux"),
            message={"token": os.environ.get("GALAXY_API_TOKEN", "")},
        )
        assert outcome.steps.get("mesh_enrollment") is True
        record = get_enrollment_record(device_id)
        assert record is not None and record.registered and record.readiness_confirmed


class TestNodesComeAndGo:
    def test_discovery_leave_marks_the_node_offline(self, fresh):
        from core.capability_assimilation import get_capability_assimilation_layer
        from core.node_discovery import DiscoveredNode, NodeDiscoveryService
        from core.node_discovery_runtime import bind_discovery_to_capability_presence

        get_capability_assimilation_layer().assimilate("Node_77_Probe", capabilities=["probe"])
        discovery = NodeDiscoveryService(node_id="self")
        assert bind_discovery_to_capability_presence(discovery) is True
        assert bind_discovery_to_capability_presence(discovery) is False  # 只绑一次
        discovery.register_node(DiscoveredNode(node_id="Node_77_Probe", host="localhost", port=8077))
        discovery.deregister_node("Node_77_Probe")
        assert _presence("Node_77_Probe") == "offline"

        discovery.register_node(DiscoveredNode(node_id="Node_77_Probe", host="localhost", port=8077))
        assert _presence("Node_77_Probe") == "online"

    def test_unknown_node_is_not_invented(self, fresh):
        from core.node_discovery_runtime import mark_node_gone, mark_node_seen

        mark_node_seen("Node_nobody")
        mark_node_gone("Node_nobody", reason="x")
        assert _presence("Node_nobody") == "absent"


class TestTransportPathsReachTheTopology:
    @pytest.mark.asyncio
    async def test_fallback_and_total_failure_are_written_back(self, fresh):
        from core.aip_transport import AIPTransport
        from core.network_topology_runtime import get_network_topology_runtime

        class _Adapter:
            def __init__(self, ttype, ok):
                self.transport_type, self.ok = ttype, ok

            async def is_available(self, target):
                return True

            async def send(self, message, target):
                return {"success": self.ok, "error": "down"}

        transport = AIPTransport()
        transport._adapters = {}
        transport.register_adapter(_Adapter("tcp", False))
        transport.register_adapter(_Adapter("websocket", True))
        result = await transport.send({"type": "command"}, "dev-path", transport="tcp")
        assert result["success"] is True

        topo = get_network_topology_runtime()
        source = topo._my_device_id or "server"
        edge_id = f"{source}::dev-path::websocket"
        edge = next(e for e in topo.all_edges() if e.edge_id == edge_id)
        assert edge.metadata["fallback_used"] is True

        transport._adapters["websocket"].ok = False
        await transport.send({"type": "command"}, "dev-path", transport="tcp")
        edge = next(e for e in topo.all_edges() if e.edge_id == edge_id)
        assert edge.state.value == "unavailable"


class TestHealthSignals:
    def test_health_score_says_whether_there_is_evidence(self, fresh):
        from core.unified.device_health import get_device_health_scorer

        scorer = get_device_health_scorer()
        assert scorer.score("never-seen").to_dict()["evidence_available"] is False
        scorer.update("seen", latency_ms=20)
        assert scorer.score("seen").to_dict()["evidence_available"] is True

    def test_error_rate_check_names_the_spiking_category(self):
        from core.error_framework import ErrorCategory, ErrorTracker, GalaxyError
        from core.health_integration import UnifiedHealthManager

        tracker = ErrorTracker()
        for _ in range(40):
            tracker.record(GalaxyError("llm down", category=ErrorCategory.LLM))
        manager = UnifiedHealthManager()
        manager._error_tracker = tracker
        check = manager._check_error_rate()
        assert check["spiking_categories"] == ["llm"]


class TestEventBridgeKeepsCallbackLists:
    @pytest.mark.asyncio
    async def test_connect_notifications_still_reach_registered_callbacks(self, monkeypatch):
        from core.device_communication import DeviceCommunication
        from integration.event_bus import event_bus

        comm = DeviceCommunication()
        seen, published = [], []
        comm.on_device_connected(lambda device_id: seen.append(device_id))
        monkeypatch.setattr("core.device_communication.device_comm", comm)
        monkeypatch.setattr(event_bus, "publish_sync", lambda *a, **k: published.append(k.get("data")))

        from core.event_bridge import EventBridge

        await EventBridge().wire()
        assert isinstance(comm._on_device_connected, list)
        await comm._emit_event("connected", "dev-bridge")
        assert seen == ["dev-bridge"]
        assert {"device_id": "dev-bridge"} in published
