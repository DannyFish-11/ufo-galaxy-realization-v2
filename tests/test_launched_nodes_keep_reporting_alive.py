"""启动器拉起的节点活着就一直报活,治理门不会在开机一分钟后把它们全判成 unhealthy(第 17 轮真跑查到)。

真跑里:手机上点了「批准」删文件,删的那一步被治理门拒(``reasons=['unhealthy']``)——启动器只在节点起来那一刻报过一次心跳,
治理门的期限是 60 秒;``GET /api/v1/nodes/Node_06_Filesystem`` 同时却说它 healthy。现在 ``launcher/node_heartbeat.py``
每 20 秒看一遍:进程在、``/health`` 应答了就报活;进程退了记 offline;不应答的不报(到期如实 unhealthy)。
"""

from __future__ import annotations

import asyncio
import inspect
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace

import pytest


class _Healthy(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 — http.server 的写法
        self.send_response(200 if self.path == "/health" else 404)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *_a):
        pass


@pytest.fixture()
def health_port():
    server = HTTPServer(("127.0.0.1", 0), _Healthy)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1]
    server.shutdown()


@pytest.fixture()
def fabric(monkeypatch, tmp_path):
    import core.nodes.node_fabric_registry as fabric_mod
    from core.nodes.node_fabric_registry import NodeFabricRegistry

    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path / "data"))
    shared = NodeFabricRegistry._instance
    NodeFabricRegistry._instance = None  # 进程级单例:换一份新的,结束放回(见 test_legacy_orchestrators_… 的同一个坑)
    fresh = NodeFabricRegistry()
    monkeypatch.setattr(fabric_mod, "get_node_fabric_registry", lambda: fresh)
    yield fresh
    NodeFabricRegistry._instance = shared


class _Proc:
    def __init__(self, alive=True):
        self.alive = alive

    def poll(self):
        return None if self.alive else 1


def _launcher(nodes):
    """nodes: {名字: (进程, 端口)}。"""
    from launcher.bootstrap import ServiceType

    services = {
        n: SimpleNamespace(service_type=ServiceType.NODE, process=p, port=port) for n, (p, port) in nodes.items()
    }
    return SimpleNamespace(
        service_manager=SimpleNamespace(services=services),
        node_configs={n: {"port": port} for n, (_p, port) in nodes.items()},
    )


def _register_long_ago(fabric, name):
    from core.nodes.node_fabric_registry import NodeArchitecturalClass as C
    from core.nodes.node_fabric_registry import NodeInfo, NodeStatus

    fabric.register(NodeInfo(node_id=name, architectural_class=C.CAPABILITY_NODE, status=NodeStatus.HEALTHY))
    fabric.get(name).last_heartbeat = time.monotonic() - 120  # 起来以后两分钟没人报过活


def _allowed(fabric, name):
    from core.node_invocation_governance import evaluate_invocation_governance

    return evaluate_invocation_governance(name, registry=fabric).invocation_allowed


def test_a_node_reported_once_at_launch_is_refused_a_minute_later(fabric):
    """这正是真跑里的样子:只在起来那一刻报过一次。"""
    _register_long_ago(fabric, "Node_06_Filesystem")
    assert _allowed(fabric, "Node_06_Filesystem") is False


def test_a_live_answering_node_is_kept_fresh(fabric, health_port):
    from launcher.node_heartbeat import refresh_once

    _register_long_ago(fabric, "Node_06_Filesystem")
    seen = asyncio.run(refresh_once(_launcher({"Node_06_Filesystem": (_Proc(), health_port)})))
    assert seen["fresh"] == ["Node_06_Filesystem"]
    assert _allowed(fabric, "Node_06_Filesystem") is True, "报过活,治理门放行"


def test_a_live_node_that_does_not_answer_is_not_vouched_for(fabric):
    from launcher.node_heartbeat import refresh_once

    _register_long_ago(fabric, "Node_06_Filesystem")
    seen = asyncio.run(refresh_once(_launcher({"Node_06_Filesystem": (_Proc(), 1)})))  # 端口 1:没人在听
    assert seen["silent"] == ["Node_06_Filesystem"] and seen["fresh"] == []
    assert _allowed(fabric, "Node_06_Filesystem") is False, "不应答就不替它报活,到期如实 unhealthy"


def test_a_node_whose_process_exited_is_marked_offline(fabric, health_port):
    from core.nodes.node_fabric_registry import NodeStatus
    from launcher.node_heartbeat import refresh_once

    _register_long_ago(fabric, "Node_06_Filesystem")
    seen = asyncio.run(refresh_once(_launcher({"Node_06_Filesystem": (_Proc(alive=False), health_port)})))
    assert seen["gone"] == ["Node_06_Filesystem"]
    assert fabric.get("Node_06_Filesystem").status is NodeStatus.OFFLINE


def test_one_round_writes_the_node_table_once(fabric, health_port, monkeypatch):
    from launcher.node_heartbeat import refresh_once

    names = ["Node_06_Filesystem", "Node_23_Time", "Node_01_One"]
    for n in names:
        _register_long_ago(fabric, n)
    writes = []
    import core.nodes.node_fabric_registry as fabric_mod

    monkeypatch.setattr(fabric_mod, "write_json_atomically", lambda *_a, **_k: writes.append(1))  # 真正写文件的那一处
    asyncio.run(refresh_once(_launcher({n: (_Proc(), health_port) for n in names})))
    assert len(writes) == 1, "三个节点报活只落盘一次"


def test_the_launcher_starts_it_once_after_launching_nodes():
    from launcher import node_heartbeat
    from launcher.node_startup import NodeSystemLauncher

    assert "node_heartbeat import start" in inspect.getsource(NodeSystemLauncher.start_all)

    async def main():
        launcher = SimpleNamespace()
        node_heartbeat.start(launcher)
        first = launcher._heartbeat_task
        node_heartbeat.start(launcher)
        assert launcher._heartbeat_task is first, "同一个启动器只起一个"
        first.cancel()

    asyncio.run(main())
