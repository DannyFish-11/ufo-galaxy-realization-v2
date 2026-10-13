"""端口上已经有一个 NATS 在应答(容器基础设施拉起的那个)时,内置 nats-server 不再另起一个。

真跑 ``python main.py --backend`` 的启动日志::

    ✓ Docker 基础设施     nats / redis / qdrant / neo4j / mongodb 已就绪 · via Docker
    01:20:44 | ERROR | NATS server exited:
    ✓ NATS Bus            nats://localhost:4222

内置那个照样再起一个 —— 端口被占,它立刻退出,控制台一条 **原因为空** 的 ERROR(输出接的是 DEVNULL,
却去读 ``process.stderr``);随后连接连上了容器里那个,横幅照打 ✓。
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess

import pytest

from core.nats_server import EmbeddedNATSServer


async def _listen(banner: bytes):
    async def on_conn(reader, writer):
        if banner:
            writer.write(banner)
            await writer.drain()
        await asyncio.sleep(0.5)
        writer.close()

    server = await asyncio.start_server(on_conn, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


@pytest.fixture
def nats_wanted(monkeypatch):
    monkeypatch.setenv("GALAXY_NATS_ENABLED", "true")
    monkeypatch.delenv("GALAXY_NATS_URL", raising=False)


def test_an_existing_nats_is_used_instead_of_starting_a_second_one(nats_wanted, monkeypatch, tmp_path):
    called = []
    monkeypatch.setattr(shutil, "which", lambda *a, **k: called.append("which") or "/usr/bin/nats-server")
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: called.append("popen"))

    async def run():
        server, port = await _listen(b"INFO {}\r\n")
        try:
            nats = EmbeddedNATSServer(port=port)
            nats.data_dir = tmp_path / "store"
            return await nats.start(), port
        finally:
            server.close()

    ok, port = asyncio.run(run())
    assert ok is True
    assert called == [], f"已有 NATS 在应答还去装 / 起了一个: {called}"
    import os

    assert os.environ["GALAXY_NATS_URL"] == f"nats://localhost:{port}"


def test_something_else_on_the_port_is_not_mistaken_for_nats():
    async def run():
        server, port = await _listen(b"HTTP/1.1 200 OK\r\n")
        try:
            nats = EmbeddedNATSServer(port=port)
            return await nats._already_served(), await nats._port_taken()
        finally:
            server.close()

    served, taken = asyncio.run(run())
    assert served is False and taken is True


def test_a_server_that_exits_says_why(nats_wanted, monkeypatch, tmp_path):
    """真起不来时原因不能是空的:说退出码,端口被别的程序占着也说出来。"""

    class _Exited:
        returncode = 1
        stderr = None

        def poll(self):
            return 1

    monkeypatch.setattr(shutil, "which", lambda *a, **k: "/usr/bin/nats-server")
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: _Exited())

    async def run():
        server, port = await _listen(b"")  # 占着端口,但不是 NATS
        try:
            nats = EmbeddedNATSServer(port=port)
            nats.data_dir = tmp_path / "store"
            ok = await nats.start()
            return ok, nats.last_error, port
        finally:
            server.close()

    ok, why, port = asyncio.run(run())
    assert ok is False
    assert "退出码 1" in why and f"端口 {port} 已被别的程序占用" in why, why
