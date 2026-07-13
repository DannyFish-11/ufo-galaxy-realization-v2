"""
NATS worker 面板显示/开关(Mesh 区)—— 契约测试
================================================

面板 Mesh 区新增 worker 状态卡与启停开关,数据/控制两条线:
- 数据:panel feed 的 ``nats_worker`` 块 + GET /api/v1/mesh/worker
  (running 为真实运行态,enabled_by_env 诚实回显启动序列总开关);
- 控制:POST /api/v1/mesh/worker/toggle —— NATS 不可用时如实回
  ``started=False + reason``,不假装启动。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    from core.routes.hybrid import create_router
    from core.worker_runtime import reset_worker_runtime

    reset_worker_runtime()
    app = FastAPI()
    app.include_router(create_router())
    yield TestClient(app)
    reset_worker_runtime()


class TestWorkerStatusEndpoint:
    def test_get_returns_real_state(self, client):
        r = client.get("/api/v1/mesh/worker")
        assert r.status_code == 200
        body = r.json()
        assert body["running"] is False
        assert body["worker_id"].startswith("worker-")
        assert "enabled_by_env" in body
        assert "nats_connected" in body

    def test_enabled_by_env_reflects_master_switch(self, client, monkeypatch):
        monkeypatch.setenv("GALAXY_MASTER_BRAIN_ENABLED", "1")
        assert client.get("/api/v1/mesh/worker").json()["enabled_by_env"] is True
        monkeypatch.delenv("GALAXY_MASTER_BRAIN_ENABLED")
        assert client.get("/api/v1/mesh/worker").json()["enabled_by_env"] is False


class TestWorkerToggleEndpoint:
    def test_enable_without_nats_fails_honestly(self, client):
        """NATS 不可达时不得假装启动:started=False + 真实 reason。"""
        r = client.post("/api/v1/mesh/worker/toggle", json={"enable": True})
        assert r.status_code == 200
        body = r.json()
        assert body["running"] is False
        assert body["started"] is False
        assert body.get("reason")

    def test_enable_with_mock_bus_starts(self, client):
        from core.worker_runtime import get_worker_runtime

        bus = MagicMock()
        bus.is_connected = MagicMock(return_value=True)
        bus.connect = AsyncMock()
        bus.publish_worker_registration = AsyncMock()
        bus.subscribe_task_dispatches = AsyncMock()
        get_worker_runtime()._nats = bus

        r = client.post("/api/v1/mesh/worker/toggle", json={"enable": True})
        body = r.json()
        assert body["started"] is True
        assert body["running"] is True
        bus.subscribe_task_dispatches.assert_awaited_once()

        r2 = client.post("/api/v1/mesh/worker/toggle", json={"enable": False})
        body2 = r2.json()
        assert body2["running"] is False
        assert body2["stopped"] is True


class TestPanelFeedBlock:
    def test_feed_shape_matches_frontend_mapping(self):
        """panel feed 的 nats_worker 键形与 usePanelData 映射一致。"""
        from core.worker_runtime import get_worker_runtime, worker_enabled

        wr = get_worker_runtime()
        block = {
            "running": bool(wr.running),
            "worker_id": wr.worker_id,
            "enabled_by_env": worker_enabled(),
        }
        assert set(block) == {"running", "worker_id", "enabled_by_env"}
        assert isinstance(block["running"], bool)
        assert isinstance(block["worker_id"], str)
        assert isinstance(block["enabled_by_env"], bool)
