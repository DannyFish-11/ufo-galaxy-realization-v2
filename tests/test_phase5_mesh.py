"""
Phase 5 P2P Mesh Overlay 测试
==============================

测试覆盖:
1. MeshCoordinator: peer 注册/注销/列表
2. MeshCoordinator: 自动选路 (P2P direct vs Relay)
3. MeshCoordinator: peer 探测 (TCP probe mock)
4. MeshCoordinator: peer_exchange 构建 + 广播
5. MeshCoordinator: handle_peer_announce
6. MeshCoordinator: 拓扑图 (get_topology)
7. Scheduler: mesh_send 工具注册 + 执行
8. ProxyRelay: mesh-aware P2P 优先路由
9. AIP v2: Phase 5 消息类型
"""

import asyncio
import json
import os
import sys
import time
import pytest

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ============================================================================
# Test 1: MeshCoordinator — Peer 管理
# ============================================================================

def test_1_mesh_peer_management():
    """测试 peer 注册、更新、注销、列表"""
    from core.mesh_coordinator import MeshCoordinator, ConnectionType

    mesh = MeshCoordinator(local_device_id="server")

    # 注册 peer
    p1 = mesh.register_peer("phone_a", local_ip="192.168.1.10", local_port=19720)
    assert p1.device_id == "phone_a"
    assert p1.local_ip == "192.168.1.10"
    assert p1.connection_type == ConnectionType.UNKNOWN

    # 注册第二个 peer
    p2 = mesh.register_peer("phone_b", local_ip="192.168.1.11", local_port=19720)
    assert len(mesh.list_peers()) == 2

    # 更新 peer (再次注册同 ID)
    p1_updated = mesh.register_peer("phone_a", public_ip="1.2.3.4")
    assert p1_updated.public_ip == "1.2.3.4"
    assert p1_updated.local_ip == "192.168.1.10"  # 保留旧值
    assert len(mesh.list_peers()) == 2  # 不新增

    # 查询 peer
    assert mesh.get_peer("phone_a") is not None
    assert mesh.get_peer("phone_c") is None

    # is_peer_direct
    assert not mesh.is_peer_direct("phone_a")  # 未探测, 默认 False
    p1_updated.reachable_direct = True
    assert mesh.is_peer_direct("phone_a")

    # 注销 peer
    mesh.unregister_peer("phone_b")
    assert len(mesh.list_peers()) == 1
    assert mesh.get_peer("phone_b") is None


# ============================================================================
# Test 2: MeshCoordinator — 自动选路 (P2P direct vs Relay)
# ============================================================================

@pytest.mark.asyncio
async def test_2_mesh_auto_routing():
    """测试消息发送时自动选择 P2P / Relay"""
    from core.mesh_coordinator import MeshCoordinator, ConnectionType

    p2p_log = []
    relay_log = []

    async def mock_p2p_send(device_id: str, msg: bytes) -> bool:
        p2p_log.append({"device": device_id, "size": len(msg)})
        return True

    async def mock_relay_send(source, target, payload_type, payload):
        relay_log.append({"source": source, "target": target})
        return {"status": "forwarded"}

    mesh = MeshCoordinator(
        local_device_id="server",
        p2p_sender=mock_p2p_send,
        relay_sender=mock_relay_send,
    )

    # 注册 peer A (direct reachable)
    pa = mesh.register_peer("phone_a", local_ip="192.168.1.10", local_port=19720)
    pa.reachable_direct = True
    pa.last_probe = time.time()

    # 注册 peer B (不可直连)
    mesh.register_peer("phone_b", local_ip="10.0.0.5", local_port=19720)

    # 发送到 phone_a → 应走 P2P
    result_a = await mesh.send(
        target_device="phone_a",
        payload={"task": "ping"},
        payload_type="task",
    )
    assert result_a.success
    assert result_a.via == ConnectionType.DIRECT
    assert len(p2p_log) == 1

    # 发送到 phone_b → 应走 Relay
    result_b = await mesh.send(
        target_device="phone_b",
        payload={"task": "ping"},
        payload_type="task",
    )
    assert result_b.success
    assert result_b.via == ConnectionType.RELAY
    assert len(relay_log) == 1

    # 统计
    stats = mesh.get_stats()
    assert stats["via_direct"] == 1
    assert stats["via_relay"] == 1
    assert stats["total_sent"] == 2


# ============================================================================
# Test 3: MeshCoordinator — P2P 失败自动降级到 Relay
# ============================================================================

@pytest.mark.asyncio
async def test_3_mesh_p2p_fallback_relay():
    """P2P 发送失败时自动 fallback 到 Relay"""
    from core.mesh_coordinator import MeshCoordinator, ConnectionType

    async def failing_p2p(device_id: str, msg: bytes) -> bool:
        return False  # 模拟 P2P 失败

    relay_log = []

    async def mock_relay(source, target, payload_type, payload):
        relay_log.append(target)
        return {"status": "forwarded"}

    mesh = MeshCoordinator(
        p2p_sender=failing_p2p,
        relay_sender=mock_relay,
    )

    pa = mesh.register_peer("phone_a", local_ip="192.168.1.10")
    pa.reachable_direct = True  # 标记为可直连
    pa.last_probe = time.time()

    result = await mesh.send(
        target_device="phone_a",
        payload={"test": True},
    )

    # P2P 失败后应该 fallback 到 Relay
    assert result.success
    assert result.via == ConnectionType.RELAY
    assert len(relay_log) == 1
    # peer 应被标记为不可直连
    assert not pa.reachable_direct
    assert result.fallback_used
    assert result.fallback_reason == "direct_send_failed"
    assert result.route_decision == "relay_fallback"


@pytest.mark.asyncio
async def test_3b_mesh_direct_health_check_before_send():
    """直连发送前应执行健康检查（需要重探测时）"""
    from core.mesh_coordinator import MeshCoordinator, ConnectionType

    p2p_log = []
    relay_log = []
    probe_log = []

    async def mock_p2p_send(device_id: str, msg: bytes) -> bool:
        p2p_log.append(device_id)
        return True

    async def mock_relay_send(source, target, payload_type, payload):
        relay_log.append(target)
        return {"status": "forwarded"}

    mesh = MeshCoordinator(
        local_device_id="server",
        p2p_sender=mock_p2p_send,
        relay_sender=mock_relay_send,
    )

    peer = mesh.register_peer("phone_a", local_ip="192.168.1.10", local_port=19720)
    peer.reachable_direct = True
    peer.last_probe = time.time() - (mesh.PROBE_INTERVAL + 10)  # 强制触发健康检查

    async def mock_probe(device_id: str) -> bool:
        probe_log.append(device_id)
        peer.last_probe = time.time()
        peer.reachable_direct = True
        return True

    mesh.probe_peer = mock_probe

    result = await mesh.send(target_device="phone_a", payload={"task": "ping"})

    assert result.success
    assert result.via == ConnectionType.DIRECT
    assert result.direct_health_checked
    assert result.direct_attempted
    assert result.route_decision == "direct_p2p"
    assert probe_log == ["phone_a"]
    assert p2p_log == ["phone_a"]
    assert len(relay_log) == 0


@pytest.mark.asyncio
async def test_3c_mesh_probe_failure_forces_explicit_fallback():
    """健康检查失败时应显式回退到 relay 并携带回退原因"""
    from core.mesh_coordinator import MeshCoordinator, ConnectionType

    p2p_called = False
    relay_log = []

    async def mock_p2p_send(device_id: str, msg: bytes) -> bool:
        nonlocal p2p_called
        p2p_called = True
        return True

    async def mock_relay_send(source, target, payload_type, payload):
        relay_log.append(target)
        return {"status": "forwarded"}

    mesh = MeshCoordinator(
        local_device_id="server",
        p2p_sender=mock_p2p_send,
        relay_sender=mock_relay_send,
    )

    peer = mesh.register_peer("phone_a", local_ip="192.168.1.10", local_port=19720)
    peer.reachable_direct = True
    peer.last_probe = time.time() - (mesh.PROBE_INTERVAL + 10)

    async def failing_probe(device_id: str) -> bool:
        return False

    mesh.probe_peer = failing_probe

    result = await mesh.send(target_device="phone_a", payload={"task": "ping"})

    assert result.success
    assert result.via == ConnectionType.RELAY
    assert result.fallback_used
    assert result.fallback_reason == "direct_probe_failed"
    assert result.route_decision == "relay_fallback"
    assert result.direct_health_checked
    assert not result.direct_attempted
    assert not p2p_called
    assert len(relay_log) == 1


@pytest.mark.asyncio
async def test_3d_mesh_unconfigured_direct_sender_fallback_is_explicit():
    """直连 sender 未配置时必须给出明确 fallback 语义"""
    from core.mesh_coordinator import MeshCoordinator, ConnectionType

    relay_log = []

    async def mock_relay_send(source, target, payload_type, payload):
        relay_log.append(target)
        return {"status": "forwarded"}

    mesh = MeshCoordinator(local_device_id="server", relay_sender=mock_relay_send)
    peer = mesh.register_peer("phone_a", local_ip="192.168.1.10", local_port=19720)
    peer.reachable_direct = True

    result = await mesh.send(target_device="phone_a", payload={"task": "ping"})

    assert result.success
    assert result.via == ConnectionType.RELAY
    assert result.fallback_used
    assert result.fallback_reason == "p2p_sender_unconfigured"
    assert result.route_decision == "relay_fallback"
    assert len(relay_log) == 1


# ============================================================================
# Test 4: MeshCoordinator — peer_exchange 构建 + handle_peer_announce
# ============================================================================

def test_4_peer_exchange_and_announce():
    """测试 peer_exchange 构建和 peer_announce 处理"""
    from core.mesh_coordinator import MeshCoordinator

    mesh = MeshCoordinator()

    # 模拟设备上报 peer_announce
    data_a = {
        "local_ip": "192.168.1.10",
        "local_port": 19720,
        "public_ip": "1.2.3.4",
        "metadata": {"os": "android"},
    }
    peer_a = mesh.handle_peer_announce("phone_a", data_a)
    assert peer_a.local_ip == "192.168.1.10"
    assert peer_a.metadata["os"] == "android"

    data_b = {
        "local_ip": "192.168.1.11",
        "local_port": 19720,
    }
    mesh.handle_peer_announce("phone_b", data_b)

    # 构建 peer_exchange (排除 phone_a)
    exchange = mesh.build_peer_exchange(exclude_device="phone_a")
    assert len(exchange) == 1
    assert exchange[0]["device_id"] == "phone_b"

    # 构建完整 peer_exchange (不排除)
    exchange_full = mesh.build_peer_exchange()
    assert len(exchange_full) == 2


# ============================================================================
# Test 5: MeshCoordinator — 拓扑图
# ============================================================================

def test_5_mesh_topology():
    """测试拓扑图生成"""
    from core.mesh_coordinator import MeshCoordinator

    mesh = MeshCoordinator(local_device_id="server")

    # 注册 3 个设备
    pa = mesh.register_peer("phone_a", local_ip="192.168.1.10")
    pb = mesh.register_peer("phone_b", local_ip="192.168.1.11")
    pc = mesh.register_peer("tablet_c", local_ip="10.0.0.5")

    # phone_a 和 phone_b 同网段, 标记为 direct
    pa.reachable_direct = True
    pb.reachable_direct = True

    topo = mesh.get_topology()

    # 应有 4 个节点 (server + 3 devices)
    assert topo["total_peers"] == 3
    assert topo["direct_peers"] == 2
    assert topo["relay_peers"] == 1
    assert len(topo["nodes"]) == 4

    # 应有 WS edges (server ↔ 每台设备) + P2P edges (phone_a ↔ phone_b)
    ws_edges = [e for e in topo["edges"] if e["type"] == "websocket"]
    p2p_edges = [e for e in topo["edges"] if e["type"] == "p2p_direct"]
    assert len(ws_edges) == 3
    assert len(p2p_edges) >= 1  # phone_a ↔ phone_b 同网段


# ============================================================================
# Test 6: Scheduler — mesh_send 工具注册
# ============================================================================

def test_6_scheduler_mesh_send_tool():
    """确认 Scheduler 包含 mesh_send 内置工具"""
    from core.scheduler import AutonomousScheduler, _BUILTIN_TOOLS

    # mesh_send 在 _BUILTIN_TOOLS 中
    tool_names = [t["function"]["name"] for t in _BUILTIN_TOOLS]
    assert "mesh_send" in tool_names

    # 验证 mesh_send 工具定义
    mesh_tool = next(t for t in _BUILTIN_TOOLS if t["function"]["name"] == "mesh_send")
    params = mesh_tool["function"]["parameters"]["properties"]
    assert "target_device" in params
    assert "payload" in params
    assert "payload_type" in params


# ============================================================================
# Test 7: Scheduler — mesh_send 执行
# ============================================================================

@pytest.mark.asyncio
async def test_7_scheduler_exec_mesh_send():
    """测试 Scheduler._exec_mesh_send 方法"""
    from core.scheduler import AutonomousScheduler

    # 需要先 monkey-patch mesh coordinator
    import core.mesh_coordinator as mc

    relay_log = []

    async def mock_relay(source, target, payload_type, payload):
        relay_log.append(target)
        return {"status": "forwarded"}

    # 替换单例
    old = mc._mesh_instance
    mc._mesh_instance = mc.MeshCoordinator(relay_sender=mock_relay)
    mc._mesh_instance.register_peer("phone_x")

    try:
        scheduler = AutonomousScheduler(nodes_dir="/tmp/nonexistent_nodes_dir")
        result_str = await scheduler._exec_mesh_send({
            "target_device": "phone_x",
            "payload": {"test": 1},
            "payload_type": "task",
        })
        result = json.loads(result_str)
        assert result["target_device"] == "phone_x"
        assert result["via"] == "relay"  # 无 P2P sender → relay
        assert len(relay_log) == 1
    finally:
        mc._mesh_instance = old


# ============================================================================
# Test 8: ProxyRelay — mesh-aware P2P 优先路由
# ============================================================================

@pytest.mark.asyncio
async def test_8_proxy_relay_mesh_aware():
    """测试 ProxyRelay.relay() 在 Mesh 可用时优先走 P2P"""
    import core.mesh_coordinator as mc
    from core.proxy_relay import ProxyRelay, RelayRequest, RelayStatus

    p2p_log = []

    async def mock_p2p(device_id: str, msg: bytes) -> bool:
        p2p_log.append(device_id)
        return True

    # 设置 MeshCoordinator 单例
    old = mc._mesh_instance
    mc._mesh_instance = mc.MeshCoordinator(p2p_sender=mock_p2p)
    pa = mc._mesh_instance.register_peer("phone_a", local_ip="192.168.1.10")
    pa.reachable_direct = True
    pa.last_probe = time.time()

    ws_log = []

    async def mock_ws(device_id: str, msg: dict) -> bool:
        ws_log.append(device_id)
        return True

    relay = ProxyRelay(
        device_sender=mock_ws,
        get_online_devices=lambda: ["phone_a"],
    )

    try:
        req = RelayRequest(
            source_device="server",
            target_device="phone_a",
            payload_type="task",
            payload={"action": "test"},
            expect_reply=False,
        )
        result = await relay.relay(req)

        # 应该走 Mesh P2P 而非 WS
        assert result.status == RelayStatus.FORWARDED
        assert len(p2p_log) == 1
        assert len(ws_log) == 0  # WS 不应被调用
    finally:
        mc._mesh_instance = old


# ============================================================================
# Test 9: AIP v2 — Phase 5 消息类型
# ============================================================================

def test_9_aip_v2_phase5_types():
    """确认 AIP v3 协议包含 Phase 5 消息类型（已从 v2 迁移到 v3 MessageType）"""
    from galaxy_gateway.protocol.aip_v3 import MessageType

    # Phase 5 新增类型
    assert MessageType.PEER_ANNOUNCE.value == "peer_announce"
    assert MessageType.PEER_EXCHANGE.value == "peer_exchange"
    assert MessageType.MESH_TOPOLOGY.value == "mesh_topology"


# ============================================================================
# Test 10: MeshCoordinator — 过期 peer 清理
# ============================================================================

def test_10_mesh_cleanup_expired():
    """测试过期 peer 自动清理"""
    from core.mesh_coordinator import MeshCoordinator

    mesh = MeshCoordinator()

    pa = mesh.register_peer("phone_a", local_ip="192.168.1.10")
    pb = mesh.register_peer("phone_b", local_ip="192.168.1.11")

    # 将 phone_a 的 last_seen 设为很久以前
    pa.last_seen = time.time() - 600  # 10 分钟前 (超过 PEER_EXPIRE=300)

    mesh.cleanup_expired()

    assert mesh.get_peer("phone_a") is None
    assert mesh.get_peer("phone_b") is not None
    assert len(mesh.list_peers()) == 1


# ============================================================================
# Test 11: MeshCoordinator — broadcast_peer_exchange
# ============================================================================

@pytest.mark.asyncio
async def test_11_broadcast_peer_exchange():
    """测试 peer 列表广播"""
    from core.mesh_coordinator import MeshCoordinator

    ws_messages = []

    async def mock_ws_send(device_id: str, msg: dict) -> bool:
        ws_messages.append({"device_id": device_id, "msg": msg})
        return True

    mesh = MeshCoordinator(ws_sender=mock_ws_send)

    mesh.register_peer("phone_a", local_ip="192.168.1.10", local_port=19720)
    mesh.register_peer("phone_b", local_ip="192.168.1.11", local_port=19720)

    await mesh.broadcast_peer_exchange()

    # 每个设备收到 peer_exchange (排除自己)
    assert len(ws_messages) == 2

    msg_a = next(m for m in ws_messages if m["device_id"] == "phone_a")
    msg_b = next(m for m in ws_messages if m["device_id"] == "phone_b")

    # phone_a 收到的列表不含自己
    peers_for_a = msg_a["msg"]["peers"]
    assert all(p["device_id"] != "phone_a" for p in peers_for_a)
    assert any(p["device_id"] == "phone_b" for p in peers_for_a)

    # phone_b 收到的列表不含自己
    peers_for_b = msg_b["msg"]["peers"]
    assert all(p["device_id"] != "phone_b" for p in peers_for_b)


# ============================================================================
# Test 12: MeshCoordinator — 无 sender 时优雅处理
# ============================================================================

@pytest.mark.asyncio
async def test_12_mesh_no_sender():
    """所有 sender 都未配置时返回失败而非抛异常"""
    from core.mesh_coordinator import MeshCoordinator, ConnectionType

    mesh = MeshCoordinator()  # 不配置任何 sender
    mesh.register_peer("phone_a")

    result = await mesh.send(target_device="phone_a", payload={"test": 1})

    assert not result.success
    assert result.via == ConnectionType.UNKNOWN
    assert "unconfigured" in result.error.lower()
