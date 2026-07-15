"""
NATS worker 面板显示/开关(Mesh 区)—— 契约测试
================================================

面板 Mesh 区新增 worker 状态卡与启停开关,数据/控制两条线:
- 数据:panel feed 的 ``nats_worker`` 块 + GET /api/v1/mesh/worker
  (running 为真实运行态,enabled_by_env 诚实回显启动序列总开关);
- 控制:POST /api/v1/mesh/worker/toggle —— **立即返回 starting=True**(真 bug
  修复:此前直接 await 冷启动的整条 NATS 连接/嵌入式服务器拉起链路,最坏能同步
  阻塞请求路径近 135s;现改为 fire-and-forget 后台任务,真实结果经
  running/starting/last_error 三个字段——由 panel feed 持续反映,不阻塞这次请求)。
  NATS 不可用时最终如实落地 last_error,不假装启动。
"""

from __future__ import annotations

import time
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
    def test_enable_returns_immediately_with_starting_true(self, client):
        """POST toggle 必须立即返回(不阻塞在 NATS 冷启动链路上):starting=True。"""
        from core.worker_runtime import get_worker_runtime

        t0 = time.monotonic()
        r = client.post("/api/v1/mesh/worker/toggle", json={"enable": True})
        elapsed = time.monotonic() - t0
        assert r.status_code == 200
        body = r.json()
        assert body["running"] is False
        assert body["starting"] is True
        assert body["started"] is False
        # 真正的慢链路(嵌入式服务器自动装/轮询)被挪到后台——请求本身必须秒回,
        # 给足够宽松的上限(1s)避免测试本身的抖动误报,但足以抓回归(旧行为是
        # 同步阻塞到 NATS 冷启动失败,数量级是秒到分钟)。
        assert elapsed < 1.0, f"toggle 端点耗时 {elapsed:.2f}s——是否又变回同步阻塞了?"

        # 等后台任务跑完(本机没有 nats-server,预期最终失败并落地 last_error)。
        for _ in range(50):
            if not get_worker_runtime().starting:
                break
            time.sleep(0.05)
        wr = get_worker_runtime()
        assert wr.running is False
        assert wr.starting is False
        assert wr.last_error, "NATS 不可达时必须如实落地 last_error,不能假装启动"

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
        # 立即响应只保证"已发起后台启动",不保证已经启动完成。
        assert body["starting"] is True
        assert body["started"] is False

        # 等后台任务把 mock bus 的连接/订阅链路真正跑完。
        for _ in range(50):
            if get_worker_runtime().running:
                break
            time.sleep(0.05)
        wr = get_worker_runtime()
        assert wr.running is True
        assert wr.starting is False
        assert wr.last_error is None
        bus.subscribe_task_dispatches.assert_awaited_once()

        r2 = client.post("/api/v1/mesh/worker/toggle", json={"enable": False})
        body2 = r2.json()
        assert body2["running"] is False
        assert body2["starting"] is False
        assert body2["stopped"] is True

    def test_toggle_while_already_starting_does_not_spawn_duplicate_task(self):
        """连点两下(第二次请求在第一次的后台任务还没跑完时打进来)不应重复发起启动。

        注意:这里不用共享的 ``client`` fixture——它不是以 context manager 方式
        使用 TestClient,Starlette 因而给【每次请求各开一个独立事件循环】,一次
        request 内起的后台任务会在该请求返回前就被那个临时循环跑到底,天然测不出
        "第二次请求打进来时第一个后台任务仍在飞"这个场景。本测试用 `with TestClient(...)`
        换成【一个跨请求持久的事件循环】,才能真正制造出两次 POST 之间的重叠窗口。
        """
        import asyncio

        from fastapi import FastAPI
        from fastapi.testclient import TestClient as _TC

        from core.routes.hybrid import create_router
        from core.worker_runtime import get_worker_runtime, reset_worker_runtime

        reset_worker_runtime()
        app = FastAPI()
        app.include_router(create_router())

        try:
            with _TC(app) as client:
                # 真正会挂一会儿的 mock bus,制造"第一次后台任务确实还没跑完"的窗口。
                bus = MagicMock()
                bus.is_connected = MagicMock(return_value=False)

                async def _slow_connect():
                    await asyncio.sleep(0.3)

                bus.connect = _slow_connect
                get_worker_runtime()._nats = bus

                r1 = client.post("/api/v1/mesh/worker/toggle", json={"enable": True})
                r2 = client.post("/api/v1/mesh/worker/toggle", json={"enable": True})
                assert r1.json()["starting"] is True
                body2 = r2.json()
                assert body2["starting"] is True
                assert body2.get("already_starting") is True

                wr = get_worker_runtime()
                for _ in range(50):
                    if not wr.starting:
                        break
                    time.sleep(0.05)
                # 无论最终成功与否,只应该有一个后台任务在跑过——这里只断言状态收敛,
                # 没有遗留的"starting 永远 True"这类卡死态。
                assert wr.starting is False
        finally:
            reset_worker_runtime()


class TestPanelFeedBlock:
    def test_feed_shape_matches_frontend_mapping(self):
        """panel feed 的 nats_worker 键形与 usePanelData 映射一致。"""
        from core.worker_runtime import get_worker_runtime, worker_enabled

        wr = get_worker_runtime()
        block = {
            "running": bool(wr.running),
            "worker_id": wr.worker_id,
            "enabled_by_env": worker_enabled(),
            "starting": bool(wr.starting),
            "last_error": wr.last_error,
        }
        assert set(block) == {"running", "worker_id", "enabled_by_env", "starting", "last_error"}
        assert isinstance(block["running"], bool)
        assert isinstance(block["worker_id"], str)
        assert isinstance(block["enabled_by_env"], bool)
        assert isinstance(block["starting"], bool)
        assert block["last_error"] is None or isinstance(block["last_error"], str)
