"""进程级信号只能有一个权威。

``loop.add_signal_handler(sig, cb)`` 是**覆盖**语义:后注册的把先注册的顶掉,
不报错、不留痕。仓库里曾经有两处各自注册:

* ``launcher/gateway.install_signal_handlers`` —— 顶层入口 ``main.py`` 用它挂真正
  的停机(清理 + **取消主协程**);
* ``core/startup.bootstrap_subsystems`` —— 它在 ``main.py`` 的启动过程中被调用,
  于是**后**注册,把上面那个顶掉了。而它自己的处理器只 ``await
  shutdown_subsystems()``,**不结束事件循环**。

真跑实测的后果:``timeout --signal=TERM 150 python main.py`` 打进来,日志里只有
一条 zeroconf 注销告警,主协程 ``watch_processes()`` 的 ``while True`` 照常转,
进程 300 秒后仍在,只有 SIGKILL 收得掉 —— 桌面上就是"托盘退出没反应"。
"""

import asyncio

import pytest

from core import process_signals
from core.process_signals import (
    SIGNAL_OWNER_CORE_STARTUP,
    SIGNAL_OWNER_LAUNCHER,
    claim_process_signals,
    process_signals_owner,
    release_process_signals,
)


@pytest.fixture(autouse=True)
def _fresh_registry():
    """每条判据都从"没人认领"开始 —— 登记是模块级状态。"""
    process_signals._owner = None
    yield
    process_signals._owner = None


class TestTheOwnershipRegistry:
    def test_first_claimer_wins(self):
        assert claim_process_signals(SIGNAL_OWNER_LAUNCHER) is True
        assert process_signals_owner() == SIGNAL_OWNER_LAUNCHER

    def test_a_second_owner_is_refused_rather_than_silently_overwriting(self):
        claim_process_signals(SIGNAL_OWNER_LAUNCHER)
        assert claim_process_signals(SIGNAL_OWNER_CORE_STARTUP) is False
        # 归属没变 —— 这正是此前缺的那一条。
        assert process_signals_owner() == SIGNAL_OWNER_LAUNCHER

    def test_the_same_owner_can_claim_again(self):
        assert claim_process_signals(SIGNAL_OWNER_LAUNCHER) is True
        assert claim_process_signals(SIGNAL_OWNER_LAUNCHER) is True

    def test_only_the_owner_can_hand_it_back(self):
        claim_process_signals(SIGNAL_OWNER_LAUNCHER)
        assert release_process_signals(SIGNAL_OWNER_CORE_STARTUP) is False
        assert process_signals_owner() == SIGNAL_OWNER_LAUNCHER
        assert release_process_signals(SIGNAL_OWNER_LAUNCHER) is True
        assert process_signals_owner() is None

    def test_after_handback_someone_else_can_own_it(self):
        claim_process_signals(SIGNAL_OWNER_LAUNCHER)
        release_process_signals(SIGNAL_OWNER_LAUNCHER)
        assert claim_process_signals(SIGNAL_OWNER_CORE_STARTUP) is True

    def test_the_two_owner_names_are_defined_once_and_differ(self):
        assert SIGNAL_OWNER_LAUNCHER != SIGNAL_OWNER_CORE_STARTUP
        assert SIGNAL_OWNER_LAUNCHER and SIGNAL_OWNER_CORE_STARTUP


class TestTheLauncherClaimsItWhenItInstallsHandlers:
    def test_install_signal_handlers_claims_ownership(self):
        from launcher import gateway

        installed = []

        class FakeLoop:
            def add_signal_handler(self, sig, cb):
                installed.append(sig)

            def remove_signal_handler(self, sig):
                installed.remove(sig)

        loop = FakeLoop()
        gateway.install_signal_handlers(loop, lambda: None)
        assert process_signals_owner() == SIGNAL_OWNER_LAUNCHER
        assert len(installed) == 2  # SIGINT + SIGTERM

        gateway.remove_signal_handlers(loop)
        # 摘完要交还,否则同进程里再起一轮就认领不到了。
        assert process_signals_owner() is None


class TestCoreStartupDefersInsteadOfOverwriting:
    """这是真正会咬人的那一条:核心子系统引导**不许**顶掉顶层入口的处理器。"""

    def test_it_does_not_register_when_the_launcher_already_owns_signals(self, monkeypatch):
        import core.startup as startup

        claim_process_signals(SIGNAL_OWNER_LAUNCHER)

        registered = []

        class SpyLoop:
            def add_signal_handler(self, sig, cb):
                registered.append(sig)

        monkeypatch.setattr(asyncio, "get_running_loop", lambda: SpyLoop())

        # 只跑那一段判据本身 —— 完整 bootstrap 会把整套子系统拉起来。
        assert claim_process_signals(SIGNAL_OWNER_CORE_STARTUP) is False
        assert registered == [], "顶层入口已经是权威了,这里还去注册就会把它顶掉"
        assert startup is not None

    def test_deferring_is_reported_as_ok_not_as_a_degradation(self):
        """让位给顶层入口**不是降级** —— 信号确实有人接,只是不由这里接。

        报成 "skipped" 的话,core/startup 末尾那句
        ``logger.warning("  ⚠ %s: %s …")`` 会在**每一次正常启动**里冒出来,
        读起来像"没人管停机信号了",而事实恰好相反。
        """
        import inspect

        import core.startup as startup

        src = inspect.getsource(startup.bootstrap_subsystems)
        head = src[src.index("claim_process_signals(SIGNAL_OWNER_CORE_STARTUP)") :]
        block = head[: head.index("else:")]
        # 只看代码行 —— 注释里正解释着"为什么不是 skipped",不能被它带偏。
        code = "\n".join(ln for ln in block.split("\n") if not ln.lstrip().startswith("#"))
        assert '"status": "ok"' in code, "让位应记成 ok,不是 skipped/degraded"
        assert '"skipped"' not in code and '"degraded"' not in code

    def test_the_source_actually_gates_on_the_claim(self):
        """判据要盯着真代码,不能只盯着我在测试里重写的那份逻辑。"""
        import inspect

        import core.startup as startup

        src = inspect.getsource(startup.bootstrap_subsystems)
        assert "claim_process_signals" in src, "core.startup 没有走归属登记就注册信号"
        i_claim = src.index("claim_process_signals(SIGNAL_OWNER_CORE_STARTUP)")
        # 找**真正的调用**,不是注释里提到的那个名字。
        i_add = src.index("loop.add_signal_handler(")
        assert i_claim < i_add, "必须先认领、认领到了才注册"

    def test_it_still_registers_when_nobody_owns_signals(self):
        """单独用 bootstrap_subsystems(没有顶层入口)时,行为一个字没变。"""
        assert process_signals_owner() is None
        assert claim_process_signals(SIGNAL_OWNER_CORE_STARTUP) is True
