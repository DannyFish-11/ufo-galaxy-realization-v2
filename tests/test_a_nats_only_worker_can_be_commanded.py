"""命令目标是「只挂在 NATS 上的 worker」时，经 NATSExecutor 派发。

被修的问题：命令路由的执行器只认本机节点和 WebSocket 连上的设备；主脑名下只通过 NATS 汇报心跳的 worker
得到的是「Target … not found」，而 ``NATSExecutor``（以及面板上 ``GALAXY_NATS_EXECUTOR_FALLBACK`` /
``GALAXY_NATS_EXECUTOR_TIMEOUT`` 两个键）从来没被装到任何地方。
"""

from __future__ import annotations

import asyncio

import pytest

from core import nats_dispatch_bridge as bridge


class _Brain:
    def __init__(self, topo):
        self._topo = topo

    def get_worker_topology(self):
        return self._topo


class _Executor:
    def __init__(self):
        self.started = 0
        self.calls = []
        self.fail = False

    async def start(self):
        self.started += 1

    async def __call__(self, target, command, params):
        if self.fail:
            raise RuntimeError("bus down")
        self.calls.append((target, command, params))
        return {"success": True, "via": "nats", "target": target}


@pytest.fixture()
def wired(monkeypatch):
    ex = _Executor()
    monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "true")
    monkeypatch.setattr(
        "core.master_brain.get_master_brain", lambda: _Brain({"w1": {"alive": True}, "w2": {"alive": False}})
    )
    monkeypatch.setattr("core.command_router.get_nats_executor", lambda *a, **k: ex)
    return ex


def _run(target):
    return asyncio.run(bridge.dispatch_to_nats_worker(target, "ping", {"x": 1}))


def test_an_alive_nats_worker_is_dispatched_through_the_executor(wired):
    out = _run("w1")
    assert out == {"success": True, "via": "nats", "target": "w1"}
    assert wired.calls == [("w1", "ping", {"x": 1})] and wired.started == 1


def test_a_dead_worker_is_still_not_found_instead_of_waiting_for_a_timeout(wired):
    assert _run("w2") is None
    assert wired.calls == []


def test_an_unknown_target_is_left_to_the_caller(wired):
    assert _run("nobody") is None


def test_local_mode_never_dispatches_to_another_machine(wired, monkeypatch):
    monkeypatch.delenv("GALAXY_CROSS_DEVICE_ENABLED", raising=False)
    monkeypatch.delenv("GALAXY_SYSTEM_MODE", raising=False)
    assert _run("w1") is None
    assert wired.calls == []


def test_no_master_brain_means_no_workers(monkeypatch):
    monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "true")
    monkeypatch.setattr("core.master_brain.get_master_brain", lambda: None)
    assert _run("w1") is None


def test_an_executor_failure_degrades_to_not_found_not_a_crash(wired):
    wired.fail = True
    assert _run("w1") is None
