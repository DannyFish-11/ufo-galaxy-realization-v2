"""节点子进程的输出不接管道：没人读的管道写满，子进程就卡死在 write() 里。

被修的问题：``ServiceManager.start_service`` 用 ``stdout=PIPE, stderr=PIPE`` 起节点，而启动器只在节点
**起不来时**才读一次。Windows 匿名管道的默认缓冲只有 4KB：节点的启动日志加上几十条 uvicorn 访问日志就能写满，
之后节点停在 ``write()`` 里 —— 进程活着、端口还开着、什么都不回应。真机上表现为「节点起来一会儿就没反应」
「N 个节点启动失败」。现在输出写 ``logs/nodes/<名字>.log``（也方便人去看），失败原因从文件末尾读。

同一处还把创建进程放进工作线程：Windows 上 ``CreateProcess`` 要上百毫秒，13 个节点串着在事件循环上做，
启动期间面板请求就排在后面。
"""

from __future__ import annotations

import asyncio
import sys
import threading
from types import SimpleNamespace

import pytest

import launcher.service_manager as sm
from launcher.bootstrap import ServiceType, SystemConfig
from launcher.node_failure_report import read_node_output


@pytest.fixture()
def manager(tmp_path, monkeypatch):
    monkeypatch.setattr(sm, "PROJECT_ROOT", tmp_path)
    m = sm.ServiceManager(SystemConfig())
    m.register_service("noisy", ServiceType.NODE, None)
    return m


def test_a_child_that_writes_far_more_than_a_pipe_holds_still_finishes(manager, tmp_path):
    code = (
        "import sys\n"
        "for _ in range(60):\n"
        "    sys.stdout.write('x' * 4000 + '\\n'); sys.stderr.write('y' * 4000 + '\\n')\n"
        "print('done')"
    )

    async def run():
        assert await manager.start_service("noisy", [sys.executable, "-c", code], cwd=tmp_path) is True
        proc = manager.services["noisy"].process
        for _ in range(100):
            if proc.poll() is not None:
                break
            await asyncio.sleep(0.1)
        return proc.poll()

    assert asyncio.run(run()) == 0, "子进程被没人读的管道卡住了"
    log = (tmp_path / "logs" / "nodes" / "noisy.log").read_bytes()
    assert log.endswith(b"done\n") and len(log) > 400_000


def test_the_failure_reason_comes_from_the_end_of_the_log(manager, tmp_path):
    code = (
        "import sys; sys.stderr.write('Traceback (most recent call last):\\n'); "
        "raise SystemExit('RuntimeError: no thanks')"
    )

    async def run():
        await manager.start_service("noisy", [sys.executable, "-c", code], cwd=tmp_path)
        proc = manager.services["noisy"].process
        for _ in range(100):
            if proc.poll() is not None:
                break
            await asyncio.sleep(0.05)

    asyncio.run(run())
    assert "RuntimeError: no thanks" in read_node_output(manager.services["noisy"])


def test_the_process_is_created_off_the_event_loop_thread(manager, tmp_path, monkeypatch):
    seen = []
    real = sm.subprocess.Popen

    def recording(*a, **k):
        seen.append(threading.get_ident())
        return real(*a, **k)

    monkeypatch.setattr(sm.subprocess, "Popen", recording)

    async def run():
        loop_thread = threading.get_ident()
        await manager.start_service("noisy", [sys.executable, "-c", "pass"], cwd=tmp_path)
        manager.services["noisy"].process.wait(10)
        return loop_thread

    loop_thread = asyncio.run(run())
    assert seen and loop_thread not in seen


def test_no_pipe_is_ever_attached(manager, tmp_path):
    async def run():
        await manager.start_service("noisy", [sys.executable, "-c", "pass"], cwd=tmp_path)
        proc = manager.services["noisy"].process
        proc.wait(10)
        return proc

    proc = asyncio.run(run())
    assert proc.stdout is None and proc.stderr is None


class TestReadNodeOutput:
    def test_falls_back_to_the_pipe_for_the_old_path(self):
        svc = SimpleNamespace(process=SimpleNamespace(stderr=SimpleNamespace(read=lambda: b"x\nboom\n")))
        assert read_node_output(svc).endswith("boom\n")

    def test_nothing_to_read_is_an_empty_string_not_an_error(self):
        assert read_node_output(SimpleNamespace(process=None)) == ""
        assert read_node_output(None) == ""

    def test_only_the_tail_is_returned(self, tmp_path):
        p = tmp_path / "n.log"
        p.write_bytes(b"a" * 10_000 + b"END")
        out = read_node_output(SimpleNamespace(log_path=p), limit=100)
        assert len(out) == 100 and out.endswith("END")

    def test_a_missing_log_falls_through_instead_of_raising(self, tmp_path):
        assert read_node_output(SimpleNamespace(log_path=tmp_path / "nope.log", process=None)) == ""
