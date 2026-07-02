"""tests/test_config_url_probe.py
===================================
真机复查:"设置"tab 里"端口与节点"/"网络"/"组网"分类展示的是真实配置值,但
从未对这些地址做过任何连通性探测——用户看不到"这个节点/网络是否真的通"，
被解读成"没有接真实数据"。

新增 POST /api/config/probe:对 url 类型的配置项做真实 TCP 连接探测(不是
伪造的固定返回值),这里验证探测结果确实随目标端口是否有人监听而变化。
"""

from __future__ import annotations

import socket
import threading

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.routes import config as config_module


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(config_module.router)
    return TestClient(app)


@pytest.fixture
def open_tcp_port():
    """起一个真实监听的 TCP server，返回其端口号。"""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def _accept_loop():
        try:
            while True:
                conn, _ = srv.accept()
                conn.close()
        except OSError:
            pass

    t = threading.Thread(target=_accept_loop, daemon=True)
    t.start()
    yield port
    srv.close()


class TestProbeReflectsRealConnectivity:
    def test_reachable_port_reports_true_with_latency(self, client, open_tcp_port, monkeypatch):
        monkeypatch.setitem(
            config_module.CONFIG_SCHEMA,
            "NODE_92_URL",
            {"default": f"http://127.0.0.1:{open_tcp_port}", "type": "url", "category": "ports", "description": "x"},
        )
        monkeypatch.delenv("NODE_92_URL", raising=False)

        resp = client.post("/api/config/probe", json={"keys": ["NODE_92_URL"]})
        assert resp.status_code == 200
        result = resp.json()["results"]["NODE_92_URL"]
        assert result["reachable"] is True
        assert isinstance(result["latency_ms"], (int, float))
        assert result["error"] is None

    def test_closed_port_reports_false(self, client, monkeypatch):
        # 找一个大概率没人监听的端口。
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        closed_port = s.getsockname()[1]
        s.close()  # 立刻关闭，端口大概率变回未监听状态

        monkeypatch.setitem(
            config_module.CONFIG_SCHEMA,
            "NODE_92_URL",
            {"default": f"http://127.0.0.1:{closed_port}", "type": "url", "category": "ports", "description": "x"},
        )
        monkeypatch.delenv("NODE_92_URL", raising=False)

        resp = client.post("/api/config/probe", json={"keys": ["NODE_92_URL"]})
        result = resp.json()["results"]["NODE_92_URL"]
        assert result["reachable"] is False
        assert result["error"] is not None

    def test_unconfigured_key_reports_not_configured(self, client, monkeypatch):
        monkeypatch.setitem(
            config_module.CONFIG_SCHEMA,
            "QDRANT_URL",
            {"default": "", "type": "url", "category": "ports", "description": "x"},
        )
        monkeypatch.delenv("QDRANT_URL", raising=False)

        resp = client.post("/api/config/probe", json={"keys": ["QDRANT_URL"]})
        result = resp.json()["results"]["QDRANT_URL"]
        assert result["reachable"] is False
        assert result["error"] == "未配置"

    def test_non_url_key_rejected(self, client):
        resp = client.post("/api/config/probe", json={"keys": ["DEEPSEEK_API_KEY"]})
        result = resp.json()["results"]["DEEPSEEK_API_KEY"]
        assert result["reachable"] is False

    def test_multiple_keys_probed_concurrently(self, client, open_tcp_port, monkeypatch):
        monkeypatch.setitem(
            config_module.CONFIG_SCHEMA,
            "NODE_92_URL",
            {"default": f"http://127.0.0.1:{open_tcp_port}", "type": "url", "category": "ports", "description": "x"},
        )
        monkeypatch.delenv("NODE_92_URL", raising=False)
        monkeypatch.delenv("QDRANT_URL", raising=False)

        resp = client.post("/api/config/probe", json={"keys": ["NODE_92_URL", "QDRANT_URL"]})
        results = resp.json()["results"]
        assert results["NODE_92_URL"]["reachable"] is True
        assert results["QDRANT_URL"]["reachable"] is False
