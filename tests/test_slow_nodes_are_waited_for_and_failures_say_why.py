"""节点启动结果：慢的继续等并自动登记，真失败的屏幕上带一句原因，端口问题单独说。

Windows 真机日志：CPU 吃紧时 13 个节点里 4 个 5 秒内没过健康检查，汇总写成「4 个节点启动失败（详情见日志
DEBUG）」—— 进程其实还活着、只是慢，之后没人再看它们，系统就一直「9/13 就绪」；真起不来的原因也只进 DEBUG。
"""

from __future__ import annotations

import asyncio
import socket
from types import SimpleNamespace

import pytest
from aiohttp import web

from launcher.node_failure_report import (
    adopt_slow_nodes,
    is_port_failure,
    last_informative_line,
    report_node_failures,
)
from launcher.node_startup import NodeSystemLauncher


class TestPortFailuresAreRecognised:
    @pytest.mark.parametrize(
        "text",
        [
            "OSError: [WinError 10013] 以一种访问权限不允许的方式做了一个访问套接字的尝试 forbidden by its access"
            " permissions",
            "OSError: [WinError 10048] Only one usage of each socket address (protocol/network address/port) is"
            " normally permitted",
            "OSError: [Errno 98] Address already in use",
        ],
    )
    def test_real_bind_errors(self, text):
        assert is_port_failure(text)
        assert NodeSystemLauncher._classify_node_failure(text) == "port"

    def test_a_missing_module_is_still_an_import_failure_not_a_port_one(self):
        assert NodeSystemLauncher._classify_node_failure("ModuleNotFoundError: No module named 'redis'") == "import"

    def test_a_plain_error_is_not_a_port_failure(self):
        assert not is_port_failure("ValueError: bad config")


def test_the_reason_line_skips_the_caret_underlines():
    stderr = (
        'Traceback (most recent call last):\n  File "x.py", line 3\n    boom()\n    ^^^^^^\n'
        "RuntimeError: no thanks\n   ^^^\n"
    )
    assert last_informative_line(stderr) == "RuntimeError: no thanks"
    assert last_informative_line("") == ""


class TestTheSummaryTellsThreeThingsApart:
    def _run(self, results, reasons, details=None):
        said = []

        def say(msg, level="info"):
            said.append((level, msg))

        slow = report_node_failures(results, reasons, details or {}, say)
        return slow, said

    def test_slow_nodes_are_not_called_failures_and_are_handed_back(self):
        slow, said = self._run({"a": True, "b": False}, {"b": "slow_start"})
        assert slow == ["b"]
        text = " ".join(m for _, m in said)
        assert "还在启动" in text and "启动失败" not in text

    def test_a_real_failure_carries_its_reason_on_screen(self):
        _, said = self._run({"a": True, "b": False}, {"b": "other"}, {"b": "RuntimeError: no thanks"})
        assert any("启动失败" in m and "RuntimeError: no thanks" in m for _, m in said)

    def test_port_trouble_says_where_to_look(self):
        _, said = self._run({"a": True, "b": False}, {"b": "port"})
        assert any("excludedportrange" in m for _, m in said)

    def test_all_good_says_so(self):
        _, said = self._run({"a": True, "b": True}, {})
        assert any(level == "success" for level, _ in said)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Proc:
    def __init__(self, alive=True, stderr=b""):
        self._alive = alive
        self.stderr = SimpleNamespace(read=lambda: stderr)

    def poll(self):
        return None if self._alive else 1


class _Launcher:
    def __init__(self, nodes, procs):
        self.node_configs = {n: {"port": p} for n, p in nodes.items()}
        self.service_manager = SimpleNamespace(services={n: SimpleNamespace(process=procs[n]) for n in nodes})
        self.registered = []

    async def _register_node_with_runtime_registry(self, name, port):
        self.registered.append((name, port))


def test_a_slow_node_that_comes_up_later_gets_registered():
    port = _free_port()

    async def scenario():
        started = asyncio.get_running_loop().time()

        async def health(_req):
            if asyncio.get_running_loop().time() - started < 2.5:  # 起得慢：头几秒不健康
                return web.Response(status=503)
            return web.json_response({"status": "healthy"})

        app = web.Application()
        app.router.add_get("/health", health)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", port).start()
        try:
            launcher = _Launcher({"slowpoke": port}, {"slowpoke": _Proc(alive=True)})
            outcome = await adopt_slow_nodes(launcher, ["slowpoke"], wait_s=15)
            return outcome, launcher.registered
        finally:
            await runner.cleanup()

    outcome, registered = asyncio.run(scenario())
    assert outcome == {"slowpoke": True}
    assert registered == [("slowpoke", port)]


def test_a_node_whose_process_dies_while_we_wait_is_reported_not_registered():
    launcher = _Launcher({"gone": _free_port()}, {"gone": _Proc(alive=False, stderr=b"RuntimeError: died\n")})
    outcome = asyncio.run(adopt_slow_nodes(launcher, ["gone"], wait_s=6))
    assert outcome == {"gone": False} and launcher.registered == []


def test_a_node_that_never_answers_is_given_up_on_after_the_wait():
    launcher = _Launcher({"stuck": _free_port()}, {"stuck": _Proc(alive=True)})
    outcome = asyncio.run(adopt_slow_nodes(launcher, ["stuck"], wait_s=3))
    assert outcome == {"stuck": False} and launcher.registered == []
