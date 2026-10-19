"""启动时那一批节点登记，节点表只落盘一次。

全面排查第 7 轮真跑，卡顿记录抓到事件循环被卡 0.3 秒，卡在
``core/nodes/node_fabric_registry.py persist_durable_state ← register``：每个节点健康检查通过后登记一次（随后经
HTTP 再通知一次），每一次都在事件循环里把整张节点表（这台 18KB）重新序列化、原子替换一遍，十几个节点就是二三十份，
中间那些没人读、下一次马上覆盖。拓扑图早先因为同一件事改成了批量落盘（``core/persist_batch.py``），节点表用同一个。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import core.nodes.node_fabric_registry as nfr

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def registry(tmp_path, monkeypatch):
    nfr.reset_node_fabric_registry()
    reg = nfr.get_node_fabric_registry()
    reg._state_path = str(tmp_path / "node_fabric_registry_state.json")
    writes = []
    real = nfr.write_json_atomically
    monkeypatch.setattr(nfr, "write_json_atomically", lambda path, payload: (writes.append(path), real(path, payload)))
    reg.writes = writes
    yield reg
    nfr.reset_node_fabric_registry()


def _node(i: int) -> "nfr.NodeInfo":
    return nfr.NodeInfo(node_id=f"Node_{i:02d}_Test", port=8000 + i)


def test_a_batch_of_registrations_is_written_once_with_everything_in_it(registry):
    with registry.batched_persistence():
        for i in range(13):
            registry.register(_node(i))
            registry.heartbeat(f"Node_{i:02d}_Test")
        assert registry.writes == [], "批内一次都不该写"
    assert len(registry.writes) == 1
    saved = json.loads(Path(registry._state_path).read_text(encoding="utf-8"))
    assert sorted(n["node_id"] for n in saved["nodes"]) == [f"Node_{i:02d}_Test" for i in range(13)]


def test_outside_a_batch_every_change_is_still_written_at_once(registry):
    registry.register(_node(1))
    registry.update_status("Node_01_Test", nfr.NodeStatus.HEALTHY)
    assert len(registry.writes) == 2


def test_the_launcher_starts_its_nodes_inside_one_batch():
    src = (REPO_ROOT / "launcher" / "node_startup.py").read_text(encoding="utf-8")
    at = src.index("results = await self.start_nodes(nodes, parallel=True)")
    assert "batched_persistence()" in src[at - 200 : at], "start_all 那一批节点又在逐个整份落盘了"
