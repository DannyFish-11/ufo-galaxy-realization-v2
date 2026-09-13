"""启动的节奏:等得久可以,但不许看起来像死了,也不许白等。

所有者反馈:"整体的速度和节奏有点奇怪,你看看能不能完全搞清楚。"

先量,再改。``logs/lumiv.log`` 里 ``[PHASE-TIMING]`` 的真实读数(同一台机器,
冷启 = 容器起来后第一次跑,热启 = 紧接着再跑)::

    阶段                冷启      热启     倍数
    Phase 0 环境检查     0.8s     0.8s      1×
    Phase 1 系统预检    20.3s     1.0s     20×      ← 首次 npm install(真活)
    Phase 2 依赖确保    14.0s     3.3s      4×      ← 首次装依赖(真活)
    API 网关             7.5s     1.6s      5×
    核心服务            10.2s     0.1s    100×      ← 9 秒卡在 import pyautogui
    基础设施             5.4s     3.7s    1.5×
    ────────────────────────────────────────
    合计                约 58s    约 11s

结论分两半,这个文件守的就是这两半:

1. **真活不该被误当成卡死。** 20 秒的 npm install 是必要的;但一个只转不走字的
   圈和卡死长得一模一样。所以转圈行必须把秒数走起来。
2. **白等的要拿掉。** 核心服务那 10 秒里有 9 秒是最慢的一条把另外两条堵住了 ——
   三条彼此独立,却一个 ``await`` 一个。改成并发,耗时从"求和"变"取最大"。

(那段代码此前的注释写着"这三个都是秒级的" —— 被上面这组读数直接推翻了。
注释已改,但这里**不**拿字符串去判它:验散文没有意义,并发与否看下面那条
计时判据。)
"""

from __future__ import annotations

import asyncio
import io
import time

import pytest


class _Tty(io.StringIO):
    def isatty(self):
        return True


class TestALongWaitDoesNotLookLikeAFreeze:
    def test_a_running_row_counts_the_seconds(self):
        from launcher.live_list import LiveList

        lst = LiveList([("npm", "npm install")], stream=_Tty())
        lst.start()
        lst._started_at["npm"] -= 14.0
        line = lst._line("npm")
        assert "已等 14 秒" in line, line

    def test_the_first_two_seconds_stay_quiet(self):
        """秒级就完事的项闪一下"已等 0 秒"反而更乱。"""
        from launcher.live_list import LiveList

        lst = LiveList([("npm", "npm install")], stream=_Tty())
        lst.start()
        assert "已等" not in lst._line("npm")

    def test_a_finished_row_shows_its_result_not_the_clock(self):
        """跑完了就该显示结果 —— 秒数是"还在等"的话,不是结论。"""
        from launcher.live_list import STATE_OK, LiveList

        lst = LiveList([("npm", "npm install")], stream=_Tty())
        lst.start()
        lst._started_at["npm"] -= 14.0
        lst.update("npm", STATE_OK, "10.9.7")
        line = lst._line("npm")
        assert "10.9.7" in line
        assert "已等" not in line, line

    def test_an_explicit_value_wins_over_the_clock(self):
        """调用方给了话说,就说它的 —— 秒数只是没话说时的填充。"""
        from launcher.live_list import LiveList

        lst = LiveList([("npm", "npm install")], stream=_Tty())
        lst.start()
        lst._started_at["npm"] -= 20.0
        lst._value["npm"] = "正在拉 1200 个包"
        assert "正在拉 1200 个包" in lst._line("npm")

    def test_the_clock_can_be_turned_off(self):
        from launcher.live_list import LiveList

        lst = LiveList([("npm", "npm install")], stream=_Tty(), show_elapsed=False)
        lst.start()
        lst._started_at["npm"] -= 30.0
        assert "已等" not in lst._line("npm")


class TestCoreServicesDoNotQueueUp:
    """三条核心服务彼此独立,不许一个等一个。

    判的是**行为**(总耗时接近最慢那条,而不是三条之和),不是"源码里有没有
    出现 gather 这个词" —— 后者能过而实际照旧串行。
    """

    def _fake_manager(self):
        class _Svc:
            def __init__(self):
                self.status = "running"

        class _Mgr:
            def __init__(self):
                self.services = {}

            def register_service(self, key, _type):
                self.services[key] = _Svc()

        return _Mgr()

    @pytest.mark.asyncio
    async def test_the_slowest_one_does_not_hold_up_the_others(self, monkeypatch):
        from launcher.core_services import CoreServiceLauncher

        class _Config:
            enable_device_api = True

        svc = CoreServiceLauncher.__new__(CoreServiceLauncher)
        svc.config = _Config()
        svc.service_manager = self._fake_manager()
        for key in ("device_agent_manager", "device_status_api", "microsoft_ufo_integration"):
            svc.service_manager.register_service(key, None)

        async def _slow():
            await asyncio.sleep(0.30)
            return True

        async def _quick():
            await asyncio.sleep(0.30)
            return True

        monkeypatch.setattr(svc, "start_device_agent_manager", _quick)
        monkeypatch.setattr(svc, "start_device_status_api", _quick)
        monkeypatch.setattr(svc, "start_microsoft_ufo_integration", _slow)
        monkeypatch.setattr("launcher.core_services.print_status", lambda *a, **k: None)

        t0 = time.monotonic()
        results = await svc.start_all()
        elapsed = time.monotonic() - t0

        assert set(results) == {"device_agent_manager", "device_status_api", "microsoft_ufo_integration"}
        # 串行是 0.9s,并发是 0.3s。0.6 这个界把两者分得很开,不靠机器快慢。
        assert elapsed < 0.60, f"看起来还是一个等一个:{elapsed:.2f}s"

    @pytest.mark.asyncio
    async def test_one_blowing_up_does_not_take_the_others_with_it(self):
        """并发最容易丢的就是这个:一条抛异常,另外两条的结论一起没了。"""
        from launcher.core_services import CoreServiceLauncher

        class _Config:
            enable_device_api = True

        svc = CoreServiceLauncher.__new__(CoreServiceLauncher)
        svc.config = _Config()
        svc.service_manager = self._fake_manager()
        for key in ("device_agent_manager", "device_status_api", "microsoft_ufo_integration"):
            svc.service_manager.register_service(key, None)

        async def _ok():
            return True

        async def _boom():
            raise RuntimeError("这一条炸了")

        svc.start_device_agent_manager = _ok
        svc.start_device_status_api = _ok
        svc.start_microsoft_ufo_integration = _boom
        import launcher.core_services as cs

        _saved = cs.print_status
        cs.print_status = lambda *a, **k: None
        try:
            results = await svc.start_all()
        finally:
            cs.print_status = _saved

        assert results["microsoft_ufo_integration"] == "failed"
        assert results["device_agent_manager"] == "running"
        assert results["device_status_api"] == "running"
