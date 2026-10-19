"""同一个节点被同时要求启动两次，只起一个进程；停机时这个进程一定停得到。

全面排查第 7 轮真跑：两台安卓在同一秒登记，各自触发一次按需激活 ——``Node_33_ADB`` 被起了两次，日志里
「服务已启动: Node_33_ADB」「STARTED Node_33_ADB」各两遍。``NodeSystemLauncher.start_node`` 每次先
``register_service``（换一个新的空条目），再 ``start_service``（建进程）：第一个进程挂在被换掉的旧条目上，
没人记着它；它占着 8033 端口一直在跑，停机时 ``stop_all`` 只停得到第二个 —— 后端停了，它还活着。
"""

from __future__ import annotations

import asyncio
import sys
import time

import pytest

import launcher.service_manager as sm
from launcher.bootstrap import ServiceType, SystemConfig


class _FakeProcess:
    born: list = []

    def __init__(self, *a, **k):
        time.sleep(0.1)  # 建进程要时间（Windows 上杀软逐个扫）—— 并发的第二个调用正好落在这段里
        self.alive = True
        _FakeProcess.born.append(self)

    def poll(self):
        return None if self.alive else 0

    def terminate(self):
        self.alive = False

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.alive = False


@pytest.fixture()
def manager(tmp_path, monkeypatch):
    monkeypatch.setattr(sm, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(sm.subprocess, "Popen", _FakeProcess)
    _FakeProcess.born = []
    return sm.ServiceManager(SystemConfig())


async def _start(manager):
    # 与 NodeSystemLauncher.start_node 同一个顺序：先登记、再起
    manager.register_service("Node_33_ADB", ServiceType.NODE, 8033)
    return await manager.start_service("Node_33_ADB", [sys.executable, "main.py"])


def test_two_concurrent_starts_make_one_process(manager):
    async def both():
        return await asyncio.gather(_start(manager), _start(manager))

    assert asyncio.run(both()) == [True, True]
    assert len(_FakeProcess.born) == 1, f"起了 {len(_FakeProcess.born)} 个进程"
    assert manager.services["Node_33_ADB"].process is _FakeProcess.born[0]


def test_stopping_everything_stops_the_one_that_is_running(manager):
    asyncio.run(_start(manager))
    asyncio.run(_start(manager))  # 再要一次（已经在跑）：不起第二个，也不把正在跑的那个弄丢
    manager.stop_all()
    assert len(_FakeProcess.born) == 1 and not _FakeProcess.born[0].alive


def test_a_node_whose_process_died_is_started_again(manager):
    asyncio.run(_start(manager))
    _FakeProcess.born[0].alive = False
    assert asyncio.run(_start(manager)) is True
    assert len(_FakeProcess.born) == 2
