"""托盘说"右下角常驻"时,它必须**真的**在右下角。

真机复现(所有者):"托盘没有正常显示,没有正常出现在右下角,相关的日志我也看不到。"

复现出来的缺陷是这个仓库最不许出现的那一类 —— 看起来接上了,其实没有:

``run_detached()`` 起一个线程就立刻 ``return thread``;``start_tray_in_thread``
再睡 0.5 秒、``set_status("running")``、返回托盘对象。整条路上**没有任何一处**
问过"图标出现了吗"。``icon.run()`` 是在那个线程里才开始跑的,它抛异常
(Windows 上 shell 未就绪、图标资源建不出来、后端不支持……)时异常留在线程里,
主线程照样拿到对象,屏幕上照样打 ``✓ 系统托盘  右下角常驻``。

判据分两层:
1. ``icon.run()`` 炸了,``start_tray_in_thread`` **不许**返回托盘对象;
2. 起不来时给的那句话里要有**日志文件路径** —— 托盘自己坏了,"去点托盘看日志"
   是空头支票。
"""

from __future__ import annotations

import sys
import types

import pytest


def _install_fake_pystray(run_behaviour):
    """装一个假 pystray,``Icon.run`` 的行为由调用方给。返回卸载函数。"""
    fake = types.ModuleType("pystray")

    class _Icon:
        def __init__(self, **kwargs):
            self.visible = False
            self.title = kwargs.get("title", "")

        def run(self, setup=None):
            run_behaviour(self, setup)

        def stop(self):
            pass

    class _Menu:
        SEPARATOR = object()

        def __init__(self, *items, **kwargs):
            self.items = items

    class _MenuItem:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    fake.Icon = _Icon
    fake.Menu = _Menu
    fake.MenuItem = _MenuItem

    saved = sys.modules.get("pystray")
    sys.modules["pystray"] = fake

    def _restore():
        if saved is None:
            sys.modules.pop("pystray", None)
        else:
            sys.modules["pystray"] = saved

    return fake, _restore


@pytest.fixture
def tray_module():
    """``windows_service.tray_icon``,并保证它认得我们塞进去的假 pystray。

    真模块在无头 Linux 上 import 期就会炸(pystray 连不上 X11),所以这里先把
    假的放进 ``sys.modules`` 再导入 —— 这不是绕过判据,判据要验的是
    ``start_tray_in_thread`` 的**返回约定**,和哪家后端无关。
    """
    fake, restore = _install_fake_pystray(lambda icon, setup: None)
    reloaded = False
    try:
        import importlib

        mod = importlib.import_module("windows_service.tray_icon")
        importlib.reload(mod)
        reloaded = True
        mod.pystray = fake
        mod._HAVE_TRAY = True
        # 画图标那条路**不在这组判据的范围内** —— 这里验的是"起来了没有"的返回
        # 约定。让它去真画的话,就把判据绑在了 Pillow 上:CI 上实测过一次,同一
        # 分片里另一个测试往 sys.modules 塞了空壳 PIL 又没摘掉,这 4 条一起红,
        # 而失败信息是 ``ImageDraw has no attribute 'Draw'`` —— 和托盘毫无关系。
        #
        # 那个残留已经修掉了(见 test_logs_have_one_entry_point),但判据不该
        # 依赖别人守规矩:这里直接把画图标短路成一个占位对象。
        saved_icon_fn = mod.create_icon_image
        mod.create_icon_image = lambda *_a, **_k: object()
        try:
            yield mod, fake
        finally:
            mod.create_icon_image = saved_icon_fn
    finally:
        restore()
        # 把模块**还原回真实状态**。
        #
        # 上一版只还原了 sys.modules 里的 pystray,却把 ``_HAVE_TRAY = True`` 和
        # ``pystray = <假的>`` 留在真模块对象上 —— 于是后面 test_the_tray_says_why
        # 那 6 条判据读到的是被我改过的模块,报出来的原因跟它们预期的不是一回事。
        #
        # 这正是我刚在 test_logs_have_one_entry_point 里挑出来的同一种毛病:
        # 一个测试的残留改变了另一个测试的结论。自己不许犯。
        if reloaded:
            try:
                import importlib as _il

                _il.reload(_il.import_module("windows_service.tray_icon"))
            except Exception:  # noqa: BLE001 —— 无头机器上真 import 会抛,那本来就是真实状态
                pass


def _run_ok(icon, setup):
    """正常后端:图标可见之后回调 setup,然后阻塞。"""
    if setup:
        setup(icon)
    import threading

    threading.Event().wait(5)


def _run_boom(icon, setup):
    raise RuntimeError("托盘后端起不来(模拟 Windows shell 未就绪)")


def _run_silent(icon, setup):
    """既不回调也不抛 —— 卡住。最难发现的那一种。"""
    import threading

    threading.Event().wait(30)


class TestItOnlySaysYesWhenTheIconIsUp:
    def test_a_crashing_backend_is_not_reported_as_running(self, tray_module):
        mod, fake = tray_module
        fake.Icon.run = lambda self, setup=None: _run_boom(self, setup)

        result = mod.start_tray_in_thread()
        assert not isinstance(result, mod.GalaxyTray), "icon.run() 炸了却还返回了托盘对象 —— 屏幕上会说「右下角常驻」"
        assert isinstance(result, str) and result, "起不来必须给出原因,不能只给一个 None"
        assert "起不来" in result or "RuntimeError" in result, result

    def test_a_backend_that_never_comes_up_is_not_reported_as_running(self, tray_module):
        """不抛也不回调 —— 等到上界就如实说"没等到",不许当成成功。"""
        mod, fake = tray_module
        fake.Icon.run = lambda self, setup=None: _run_silent(self, setup)

        result = mod.start_tray_in_thread()
        assert isinstance(result, str), "图标一直没出现,却返回了托盘对象"
        assert "没出现" in result, result

    def test_a_working_backend_is_reported_as_running(self, tray_module):
        """反过来也要成立:真起来了就得返回托盘对象,否则这道门只会一味说不。"""
        mod, fake = tray_module
        fake.Icon.run = lambda self, setup=None: _run_ok(self, setup)

        result = mod.start_tray_in_thread()
        assert isinstance(result, mod.GalaxyTray), f"图标起来了却报了失败:{result!r}"

    def test_readiness_comes_from_the_setup_callback(self, tray_module):
        """「起来了」的证据必须是 pystray 的 ``setup=`` 回调 —— 那是图标可见之后才调的。

        睡够半秒不算证据(那正是上一版的做法)。这里用一个**只回调、不阻塞**的
        后端:如果实现改回"睡一会儿就算好",它照样能过;所以再补一条 —— 后端
        压根不接 setup 参数时必须报失败,证明代码真的在用那个回调。
        """
        mod, fake = tray_module
        seen = {}

        def _run(icon, setup=None):
            seen["got_setup"] = setup is not None
            if setup:
                setup(icon)
            import threading

            threading.Event().wait(5)

        fake.Icon.run = _run
        result = mod.start_tray_in_thread()
        assert seen.get("got_setup") is True, "没把 setup 回调传给 icon.run() —— 那就没有「可见了」的证据"
        assert isinstance(result, mod.GalaxyTray)


class TestTheReasonTellsYouWhereToLook:
    def test_the_failure_reason_carries_a_log_path(self):
        """托盘坏了就别让人「去点托盘看日志」。"""
        from launcher.services import _with_log_path

        said = _with_log_path("装了 pystray,但这台机器上起不来")
        assert "日志在" in said, said
        assert "lumiv.log" in said, said
        assert "托盘 → 日志" not in said, "托盘自己都起不来了,还让人去点托盘:" + said

    def test_missing_dependency_and_no_desktop_are_different_reasons(self):
        """「没装」和「装了但这台机器没有桌面」是两件事,不许混成一句。"""
        import importlib

        fake, restore = _install_fake_pystray(lambda icon, setup: None)
        try:
            mod = importlib.import_module("windows_service.tray_icon")
            importlib.reload(mod)
            assert hasattr(mod, "TRAY_UNAVAILABLE_REASON"), "连「为什么用不了」都没有记下来"
        finally:
            restore()

    def test_an_unavailable_tray_names_the_real_reason(self):
        """``create_tray`` 在依赖不可用时返回 None,原因必须留在模块里可读。"""
        import importlib

        saved = sys.modules.pop("pystray", None)
        sys.modules["pystray"] = None  # type: ignore[assignment]  # 模拟 import 失败
        try:
            mod = importlib.import_module("windows_service.tray_icon")
            importlib.reload(mod)
            assert mod._HAVE_TRAY is False
            assert mod.TRAY_UNAVAILABLE_REASON, "用不了却说不出为什么"
            assert mod.create_tray() is None
        finally:
            if saved is None:
                sys.modules.pop("pystray", None)
            else:
                sys.modules["pystray"] = saved
            importlib.reload(importlib.import_module("windows_service.tray_icon"))
