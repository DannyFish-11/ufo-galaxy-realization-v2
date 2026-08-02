"""``GALAXY_NATS_ENABLED=false`` 必须真的关掉 —— 契约测试
=========================================================

这个开关此前是**只写不认**的:``unified_launcher`` 读它,``core.nats_server`` 与
``core.nats_bus`` 都不读,而这两个文件里的提示文案却一直在教用户"设
GALAXY_NATS_ENABLED=false 显式关闭此尝试"。于是任何绕过启动器直接用总线的调用方
(HTTP 端点、后台任务、测试)照样会走完:

    connect() → EmbeddedNATSServer.start() → 自动下载 nats-server 到 ~/.lumiv/bin
              → Popen 拉起一个监听 0.0.0.0:4222、**脱离调用进程长期存活**的常驻服务

也就是说这是一个**整机级、跨进程、跨会话的持久副作用**。它已经造成过实际损害:
``tests/test_mesh_worker_panel_toggle.py`` 里断言"NATS 不可达时 WorkerRuntime 必须
如实落地 last_error"的用例,第一次跑时本机确实没有 NATS —— 但那次跑**自己**把服务器
装上并拉起了,此后每个新进程都连得上,``running`` 变 True,断言**永久红**,重跑、
换分支都不自愈。

本文件锁住修复后的语义:关掉时**一步副作用都不做**。
"""

from __future__ import annotations

import asyncio

import pytest


class TestDisableSwitchPredicate:
    """``nats_disabled_by_config()`` 的取值语义。"""

    @pytest.mark.parametrize("raw", ["false", "FALSE", "False", "0", "no", "off", "  off  "])
    def test_falsey_spellings_disable(self, monkeypatch, raw):
        from core.nats_server import nats_disabled_by_config

        monkeypatch.setenv("GALAXY_NATS_ENABLED", raw)
        assert nats_disabled_by_config() is True

    @pytest.mark.parametrize("raw", ["true", "1", "yes", "on"])
    def test_truthy_spellings_do_not_disable(self, monkeypatch, raw):
        from core.nats_server import nats_disabled_by_config

        monkeypatch.setenv("GALAXY_NATS_ENABLED", raw)
        assert nats_disabled_by_config() is False

    def test_unset_does_not_disable(self, monkeypatch):
        """未设 = 保持既有默认(尝试启用),关闭必须是**显式**的。"""
        from core.nats_server import nats_disabled_by_config

        monkeypatch.delenv("GALAXY_NATS_ENABLED", raising=False)
        assert nats_disabled_by_config() is False


class TestEmbeddedServerHonoursSwitch:
    def test_start_does_nothing_when_disabled(self, monkeypatch, tmp_path):
        """关掉时:不建目录、不查 which、不装、不 Popen —— 一步都不做。

        这几个断言是分开写的,因为它们对应三种不同的持久副作用:落在磁盘上的
        ``~/.lumiv/nats`` 目录、落在 ``~/.lumiv/bin`` 的二进制、以及那个常驻进程。
        """
        import shutil
        import subprocess

        from core.nats_server import EmbeddedNATSServer

        monkeypatch.setenv("GALAXY_NATS_ENABLED", "false")

        server = EmbeddedNATSServer()
        # 把 data_dir 指到 tmp,这样"目录没被建出来"这条断言不受本机既有状态干扰。
        server.data_dir = tmp_path / "nats-store"

        called: list = []
        monkeypatch.setattr(shutil, "which", lambda *a, **k: called.append("which") or None)
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: called.append("popen"))

        assert asyncio.run(server.start()) is False
        assert called == [], f"关闭时不应触碰安装/启动路径,实际调用了 {called}"
        assert not server.data_dir.exists(), "关闭时连数据目录都不该建"
        assert "GALAXY_NATS_ENABLED" in server.last_error, "必须如实回报是被配置关掉的,不是别的失败"


class TestBusHonoursSwitch:
    def test_connect_degrades_to_local_bus_without_touching_network(self, monkeypatch):
        """关掉时 connect() 直接切进程内总线:不拨号、不拉嵌入式服务器。

        注意断言的是**降级成功**而非失败:进程内内存 pub/sub 对单机语义是完整的,
        谎报失败会让调用方去走没必要的错误分支。
        """
        import core.nats_bus as nats_bus_mod
        import core.nats_server as nats_server_mod

        monkeypatch.setenv("GALAXY_NATS_ENABLED", "false")

        touched: list = []

        class _ShouldNeverStart:
            async def start(self):  # pragma: no cover — 被断言为永不调用
                touched.append("embedded")
                return False

        monkeypatch.setattr(nats_server_mod, "EmbeddedNATSServer", _ShouldNeverStart)

        async def _boom(*a, **k):  # pragma: no cover — 被断言为永不调用
            touched.append("dial")
            raise AssertionError("关闭时不应拨号")

        if getattr(nats_bus_mod, "_HAS_NATS", False):
            import nats as nats_mod

            monkeypatch.setattr(nats_mod, "connect", _boom)

        bus = nats_bus_mod.NATSBus.__new__(nats_bus_mod.NATSBus)
        bus._url = "nats://localhost:4222"
        bus._auto_local = True
        bus._nc = None
        bus._js = None
        bus._connected = False
        bus._noop = False
        bus._embedded = None
        bus._subscriptions = []
        bus._stats = {"published": 0, "received": 0, "errors": 0, "reconnects": 0}

        result = asyncio.run(bus.connect())

        assert touched == [], f"关闭时不应拨号也不应拉嵌入式服务器,实际触碰了 {touched}"
        assert result.get("success") is True
        assert result.get("local") is True
        assert bus.is_local_mode() is True
        # is_connected() 仍必须是 False —— 进程内总线不是"连上了 NATS"。
        # WorkerRuntime.start() 正是靠这个区分来如实落地 last_error 的。
        assert bus.is_connected() is False


class TestTestSuiteLeavesNoDaemon:
    def test_conftest_disables_nats_for_the_whole_suite(self):
        """兜底:整个测试套件默认必须是关的。

        这条看起来像在测 conftest,但它守的是一个**会自我毁灭的前提**:一旦有人
        把 conftest 里那行删掉,后果不是这条用例红,而是跑过测试的机器上多出一个
        常驻 nats-server,然后 test_mesh_worker_panel_toggle 在**下一次**跑的时候
        永久红 —— 症状和原因隔着一整轮 CI。所以在这里当场钉死。
        """
        from core.nats_server import nats_disabled_by_config

        assert nats_disabled_by_config() is True
