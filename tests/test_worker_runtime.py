"""tests/test_worker_runtime.py
==================================

NATS worker 消费循环:派发 → 规范执行器执行 → 回传结果。补上此前全仓零调用的
执行端。用假 bus + 打桩 invoke_node,不触网。
"""

from __future__ import annotations

import asyncio

import pytest

import core.worker_runtime as wr


class _FakeBus:
    def __init__(self, connected=True):
        self._connected = connected
        self.published_results = []
        self.subscribed = None
        self.registered = None

    def is_connected(self):
        return self._connected

    def is_local_mode(self):
        return False

    def is_usable(self):
        # 闸门语义:见 NATSBus.is_usable。这个替身不模拟本地降级总线。
        return self._connected

    async def connect(self):
        self._connected = True
        return {"success": True}

    async def publish_worker_registration(self, model):
        self.registered = model
        return {"success": True}

    async def subscribe_task_dispatches(self, worker_id, callback):
        self.subscribed = (worker_id, callback)
        return {"success": True}

    async def publish_task_result(self, msg):
        self.published_results.append(msg)
        return {"success": True}


class _OkResult:
    success = True
    result = {"clicked": True}
    error = ""
    duration_ms = 12.0


@pytest.fixture(autouse=True)
def _reset(monkeypatch, tmp_path):
    wr.reset_worker_runtime()
    monkeypatch.delenv("GALAXY_MASTER_BRAIN_ENABLED", raising=False)
    monkeypatch.delenv("GALAXY_DISPATCH_IDEMPOTENCY", raising=False)
    # 派发幂等守卫默认开且可持久化 → 隔离到 tmp,避免把 task_id 记进真实 data/ 文件、
    # 污染同一进程/重跑(否则第二次跑同一 task_id 会被去重、invoke_node 不再被调)。
    import core.durable_dispatch_idempotency as ddi

    ddi.reset_durable_dispatch_id_store()
    ddi.get_durable_dispatch_id_store(str(tmp_path / "dispatch_idem.json"))
    yield
    wr.reset_worker_runtime()
    ddi.reset_durable_dispatch_id_store()


class TestExecuteDispatch:
    def test_executes_via_invoke_node_and_builds_result(self, monkeypatch):
        captured = {}

        async def _fake_invoke(node_id, action, params, **kw):
            captured.update(node_id=node_id, action=action, kw=kw)
            return _OkResult()

        monkeypatch.setattr("core.node_invocation.invoke_node", _fake_invoke)
        w = wr.WorkerRuntime(worker_id="w1", nats_bus=_FakeBus())
        res = asyncio.run(
            w.execute_dispatch(
                {
                    "task_id": "t1",
                    "node_id": "Node_36_UIAWindows",
                    "action": "click",
                    "params": {"x": 1, "y": 2},
                    "ui_graph": {"source": "uia"},
                    "trace_id": "tr1",
                }
            )
        )
        assert res.status == "completed" and res.task_id == "t1"
        assert captured["node_id"] == "Node_36_UIAWindows" and captured["action"] == "click"
        assert captured["kw"].get("ui_graph") == {"source": "uia"}  # 结构优先透传

    def test_missing_fields_fail_cleanly(self):
        w = wr.WorkerRuntime(worker_id="w1", nats_bus=_FakeBus())
        res = asyncio.run(w.execute_dispatch({"task_id": "t2"}))
        assert res.status == "failed" and "node_id/action" in res.error

    def test_invoke_exception_becomes_failed_result(self, monkeypatch):
        async def _boom(*a, **k):
            raise RuntimeError("node blew up")

        monkeypatch.setattr("core.node_invocation.invoke_node", _boom)
        w = wr.WorkerRuntime(worker_id="w1", nats_bus=_FakeBus())
        res = asyncio.run(w.execute_dispatch({"task_id": "t3", "node_id": "N", "action": "a"}))
        assert res.status == "failed" and "worker 执行异常" in res.error


class TestDispatchIdempotency:
    """派发侧幂等:同一派发被 NATS 重投时不二次执行副作用(默认开)。"""

    def _count_invokes(self, monkeypatch):
        calls = {"n": 0}

        async def _invoke(*a, **k):
            calls["n"] += 1
            return _OkResult()

        monkeypatch.setattr("core.node_invocation.invoke_node", _invoke)
        return calls

    def test_redelivery_does_not_double_execute(self, monkeypatch):
        calls = self._count_invokes(monkeypatch)
        w = wr.WorkerRuntime(worker_id="w1", nats_bus=_FakeBus())
        d = {"task_id": "dup1", "node_id": "N", "action": "click", "params": {}}
        r1 = asyncio.run(w.execute_dispatch(d))
        r2 = asyncio.run(w.execute_dispatch(d))  # 模拟重投
        assert calls["n"] == 1  # 副作用只执行一次
        assert r1.status == "completed"
        assert r2.status == "completed" and r2.result.get("deduplicated") is True

    def test_executor_exception_rolls_back_key_so_retry_runs(self, monkeypatch):
        state = {"boom": True, "n": 0}

        async def _invoke(*a, **k):
            state["n"] += 1
            if state["boom"]:
                state["boom"] = False
                raise RuntimeError("transient")
            return _OkResult()

        monkeypatch.setattr("core.node_invocation.invoke_node", _invoke)
        w = wr.WorkerRuntime(worker_id="w1", nats_bus=_FakeBus())
        d = {"task_id": "retry1", "node_id": "N", "action": "click", "params": {}}
        r1 = asyncio.run(w.execute_dispatch(d))  # 抛异常 → 回滚键
        r2 = asyncio.run(w.execute_dispatch(d))  # 重投 → 应真正重试执行
        assert r1.status == "failed"
        assert r2.status == "completed"
        assert state["n"] == 2  # 回滚后确实重跑了

    def test_disabled_flag_always_executes(self, monkeypatch):
        monkeypatch.setenv("GALAXY_DISPATCH_IDEMPOTENCY", "0")
        calls = self._count_invokes(monkeypatch)
        w = wr.WorkerRuntime(worker_id="w1", nats_bus=_FakeBus())
        d = {"task_id": "off1", "node_id": "N", "action": "click", "params": {}}
        asyncio.run(w.execute_dispatch(d))
        asyncio.run(w.execute_dispatch(d))
        assert calls["n"] == 2  # 关掉守卫 → 每次都执行(旧行为)


class TestStartSubscribeReply:
    def test_start_subscribes_and_dispatch_replies(self, monkeypatch):
        async def _fake_invoke(*a, **k):
            return _OkResult()

        monkeypatch.setattr("core.node_invocation.invoke_node", _fake_invoke)
        bus = _FakeBus()
        w = wr.WorkerRuntime(worker_id="w1", nats_bus=bus)
        started = asyncio.run(w.start())
        assert started["started"] and w.running
        assert bus.subscribed[0] == "w1" and bus.registered is not None
        # 模拟收到一条派发 → 应回传一条结果
        callback = bus.subscribed[1]
        asyncio.run(callback({"task_id": "t9", "node_id": "N", "action": "a", "params": {}}))
        assert len(bus.published_results) == 1
        assert bus.published_results[0].status == "completed"

    def test_start_noop_when_nats_unavailable(self):
        w = wr.WorkerRuntime(worker_id="w1", nats_bus=_FakeBus(connected=False))

        # 让 connect 也连不上
        async def _fail_connect():
            return {"success": False}

        w._nats.connect = _fail_connect  # type: ignore
        out = asyncio.run(w.start())
        assert not out["started"] and out["reason"] == "nats_unavailable"


class TestGate:
    def test_start_worker_runtime_disabled_by_default(self):
        out = asyncio.run(wr.start_worker_runtime())
        assert not out["started"] and out["reason"] == "disabled"

    def test_worker_enabled_follows_flag(self, monkeypatch):
        assert not wr.worker_enabled()
        monkeypatch.setenv("GALAXY_MASTER_BRAIN_ENABLED", "true")
        assert wr.worker_enabled()
