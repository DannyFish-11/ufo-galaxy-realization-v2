"""起来了却没接上的 MCP 服务端:如实记成没起来,进程停掉、收掉,不留僵尸(``core/mcp_loader.py`` + ``core/own_process.py``)。

第 18 轮全接口扫描之后,后端底下挂着 8 个 ``npm exec @model…`` 僵尸:``npm exec`` 在 0.5 秒时还活着(在下包),
握手没回结果 —— 原先不看 ``_initialize`` 的返回值,照样记成 RUNNING,进程撒手不管;它后来自己退了,没人 wait。
重载时也是直接换掉 ``server.process``,上一个没停。
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="看 /proc 判僵尸")


def _state(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/status", encoding="utf-8") as f:
            return next((ln.split()[1] for ln in f if ln.startswith("State:")), "")
    except FileNotFoundError:
        return "gone"


def _loader(command):
    from core.mcp_loader import MCPLoader, MCPServerInstance

    loader = MCPLoader.__new__(MCPLoader)
    loader.servers = {"s1": MCPServerInstance(id="s1", name="t", command=command, args=[], env={}, cwd=None)}
    loader._request_id = 0
    return loader


def test_a_server_that_does_not_answer_the_handshake_is_not_running_and_is_reaped(monkeypatch):
    from core.mcp_loader import MCPServerStatus

    loader = _loader([sys.executable, "-c", "import time; time.sleep(30)"])

    async def no_answer(_sid):
        return False

    monkeypatch.setattr(loader, "_initialize", no_answer)
    seen = {}
    real_popen = subprocess.Popen

    def spy(*a, **kw):
        p = real_popen(*a, **kw)
        seen["pid"] = p.pid
        return p

    monkeypatch.setattr(subprocess, "Popen", spy)
    ok = asyncio.run(loader.start("s1"))
    server = loader.servers["s1"]
    assert ok is False and server.status is MCPServerStatus.ERROR, "握手没回结果不是「在跑」"
    assert "握手" in server.error and server.process is None
    assert _state(seen["pid"]) == "gone", "进程要停掉并收掉(不是 Z 僵尸、也不是还活着)"


def test_restarting_stops_the_previous_process():
    loader = _loader([sys.executable, "-c", "import time; time.sleep(30)"])
    old = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
    loader.servers["s1"].process = old

    async def main():
        loader._initialize = lambda _sid: asyncio.sleep(0, result=True)  # type: ignore[assignment]
        assert await loader.start("s1") is True
        await loader.stop("s1")

    asyncio.run(main())
    assert _state(old.pid) == "gone", "重载时上一个进程要停掉、收掉"
    assert loader.servers["s1"].process is None


def test_a_server_that_exits_at_once_reports_why(monkeypatch):
    loader = _loader([sys.executable, "-c", "import sys; sys.stderr.write('缺一个包'); sys.exit(3)"])
    ok = asyncio.run(loader.start("s1"))
    assert ok is False and "缺一个包" in loader.servers["s1"].error


def test_stop_and_close_does_not_hang_on_a_grandchild_holding_the_pipe():
    from core.own_process import OWN_GROUP_KW, stop_and_close

    # 孩子起一个孙子(继承 stderr)然后自己退:EOF 永远不来,读要有期限
    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import subprocess,sys; subprocess.Popen([sys.executable,'-c','import time; time.sleep(20)'])",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **OWN_GROUP_KW,
    )
    proc.wait(timeout=10)
    t0 = time.monotonic()
    stop_and_close(proc, read_s=0.5)
    assert time.monotonic() - t0 < 5
    assert _state(proc.pid) == "gone"
    os.killpg(proc.pid, 9) if _group_alive(proc.pid) else None


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False
