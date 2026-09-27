"""本机登记的节点不许被 UDP 心跳超时判成"离线"。

真机日志:``✓ 全部 13 个节点就绪`` 之后 35 秒,``13 个节点 UDP 心跳超时转为离线``。
那 13 个节点是启动器刚拉起、HTTP 健康的;它们本来就不广播 UDP 心跳。旧逻辑不但
打日志,还真把状态改成 OFFLINE、触发 on_node_left,``get_healthy_nodes()`` 也把它们剔掉。
"""

import asyncio
import time

import pytest

from core import node_discovery as nd


@pytest.fixture
def svc(monkeypatch):
    monkeypatch.setattr(nd, "HEARTBEAT_INTERVAL", 0.01)
    s = nd.NodeDiscoveryService(node_id="master")
    left = []
    s.on_node_left(lambda n: left.append(n.node_id))
    s._left = left
    return s


def _run_health_once(s):
    async def _go():
        s._running = True
        t = asyncio.ensure_future(s._health_check_loop())
        await asyncio.sleep(0.05)
        s._running = False
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass

    asyncio.run(_go())


def test_a_launcher_started_node_stays_healthy_without_udp(svc):
    dn = nd.DiscoveredNode(node_id="Node_01_OneAPI", host="localhost", port=8001)
    svc.register_node(dn)
    dn.last_heartbeat = time.time() - 10 * nd.NODE_TIMEOUT  # 很久没"心跳"——它本来就不发

    _run_health_once(svc)

    assert svc.nodes["Node_01_OneAPI"].state != nd.DiscoveryState.OFFLINE
    assert svc._left == [], "不该对正在跑的本机节点触发 on_node_left"
    assert [n.node_id for n in svc.get_healthy_nodes()] == ["Node_01_OneAPI"]
    assert svc.nodes["Node_01_OneAPI"].to_dict()["liveness"] == "http_health"


def test_a_node_that_really_broadcast_and_went_silent_still_goes_offline(svc):
    svc._handle_announce({"node_id": "remote-1", "host": "10.0.0.5", "port": 9000}, ("10.0.0.5", 1))
    svc.nodes["remote-1"].last_heartbeat = time.time() - 10 * nd.NODE_TIMEOUT

    _run_health_once(svc)

    assert svc.nodes["remote-1"].state == nd.DiscoveryState.OFFLINE
    assert svc._left == ["remote-1"]
    assert svc.get_healthy_nodes() == []


def test_a_registered_node_that_starts_heartbeating_becomes_tracked(svc):
    svc.register_node(nd.DiscoveredNode(node_id="n", host="localhost", port=1))
    svc._handle_heartbeat({"node_id": "n"})
    assert svc.nodes["n"].heartbeat_tracked is True
    assert svc.nodes["n"].to_dict()["liveness"] == "udp_heartbeat"
