"""启动时登记一百多个能力 / 节点，拓扑图只整份落盘一次，而不是一百多次。

被修的问题：每次 ``register_node`` 都把整张图序列化并原子替换（实测 106 次、最大 93KB）。中间那些份没人读。
Linux 上 0.4 秒，Windows 上有杀软逐个扫临时文件，是几秒 —— 全在启动的同步段里。
"""

from __future__ import annotations

import pytest

from core.persist_batch import PersistBatcher


class TestBatcher:
    def test_outside_a_batch_every_request_writes(self):
        writes = []
        b = PersistBatcher(lambda: writes.append(1))
        b.request()
        b.request()
        assert len(writes) == 2

    def test_inside_a_batch_it_writes_once_at_the_end(self):
        writes = []
        b = PersistBatcher(lambda: writes.append(1))
        with b.batch():
            for _ in range(50):
                b.request()
            assert writes == []
        assert len(writes) == 1

    def test_an_untouched_batch_writes_nothing(self):
        writes = []
        b = PersistBatcher(lambda: writes.append(1))
        with b.batch():
            pass
        assert writes == []

    def test_nested_batches_flush_only_at_the_outermost_end(self):
        writes = []
        b = PersistBatcher(lambda: writes.append(1))
        with b.batch():
            with b.batch():
                b.request()
            assert writes == []
        assert len(writes) == 1

    def test_an_exception_in_the_batch_still_flushes_what_was_done(self):
        writes = []
        b = PersistBatcher(lambda: writes.append(1))
        with pytest.raises(RuntimeError):
            with b.batch():
                b.request()
                raise RuntimeError("boom")
        assert len(writes) == 1


class TestTheGraphUsesIt:
    @pytest.fixture()
    def graph(self, tmp_path, monkeypatch):
        from core.network_graph_runtime import NetworkGraphRuntime

        monkeypatch.setattr(NetworkGraphRuntime, "_instance", None)
        g = NetworkGraphRuntime()
        g._state_path = str(tmp_path / "graph.json")
        yield g
        monkeypatch.setattr(NetworkGraphRuntime, "_instance", None)

    def _node(self, i):
        from core.network_graph_runtime import NetworkNode, NetworkNodeRole

        return NetworkNode(node_id=f"n{i}", role=NetworkNodeRole.UNKNOWN)

    def test_a_hundred_registrations_in_a_batch_write_the_file_once(self, graph, monkeypatch):
        import core.network_graph_runtime as mod

        writes = []
        real = mod.write_json_atomically
        monkeypatch.setattr(mod, "write_json_atomically", lambda p, payload: (writes.append(1), real(p, payload)))
        with graph.batched_persistence():
            for i in range(100):
                graph.register_node(self._node(i))
        assert len(writes) == 1

    def test_the_one_write_has_every_node(self, graph):
        from core.runtime_truth_governance import load_json_payload

        with graph.batched_persistence():
            for i in range(10):
                graph.register_node(self._node(i))
        assert len(load_json_payload(graph._state_path)["nodes"]) == 10

    def test_outside_a_batch_behaviour_is_unchanged(self, graph):
        from core.runtime_truth_governance import load_json_payload

        graph.register_node(self._node(1))
        assert [n["node_id"] for n in load_json_payload(graph._state_path)["nodes"]] == ["n1"]


class TestRegisteringTheSameNodeAgainDoesNotRewriteTheFile:
    """每次对话都会把所有设备的所有能力重新登记一遍（``sync_device_capabilities``）。内容没变就不该重写整份图。"""

    @pytest.fixture()
    def graph(self, tmp_path, monkeypatch):
        from core.network_graph_runtime import NetworkGraphRuntime

        monkeypatch.setattr(NetworkGraphRuntime, "_instance", None)
        g = NetworkGraphRuntime()
        g._state_path = str(tmp_path / "graph.json")
        yield g
        monkeypatch.setattr(NetworkGraphRuntime, "_instance", None)

    def _count_writes(self, monkeypatch):
        import core.network_graph_runtime as mod

        writes = []
        real = mod.write_json_atomically
        monkeypatch.setattr(mod, "write_json_atomically", lambda p, payload: (writes.append(1), real(p, payload)))
        return writes

    def _node(self, **kw):
        from core.network_graph_runtime import NetworkNode, NetworkNodeRole

        return NetworkNode(node_id="gw1", role=NetworkNodeRole.UNKNOWN, **kw)

    def test_identical_registration_writes_once(self, graph, monkeypatch):
        writes = self._count_writes(monkeypatch)
        for _ in range(20):
            graph.register_node(self._node(host="10.0.0.2", port=80, tags=["a"]))
        assert len(writes) == 1

    def test_a_real_change_is_written(self, graph, monkeypatch):
        writes = self._count_writes(monkeypatch)
        graph.register_node(self._node(host="10.0.0.2", port=80))
        graph.register_node(self._node(host="10.0.0.2", port=80))
        graph.register_node(self._node(host="10.0.0.3", port=80))  # 地址变了
        assert len(writes) == 2
        from core.runtime_truth_governance import load_json_payload

        assert load_json_payload(graph._state_path)["nodes"][0]["host"] == "10.0.0.3"

    def test_the_in_memory_node_is_still_refreshed(self, graph):
        """不写盘不等于不更新：内存里那份的时间戳照常刷新。"""
        first = graph.register_node(self._node(host="h", port=1))
        t1 = first.last_updated_at
        second = graph.register_node(self._node(host="h", port=1))
        assert second.last_updated_at >= t1
