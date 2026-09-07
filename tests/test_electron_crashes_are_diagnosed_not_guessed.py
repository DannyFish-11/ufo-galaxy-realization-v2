"""Electron 崩了要先看它到底崩在哪,不能一律说成显卡问题。

真跑实测(全新克隆 + root 冷启动):electron.log 里八次都是同一句

    FATAL:electron_main_delegate.cc(295)] Running as root without --no-sandbox
    is not supported.

跟显卡毫无关系。而 watch_processes 当时**没有分诊**,把任何崩溃都当渲染问题,
一路 GPU → 软件渲染 → basic 窗口 地降级 —— 八次重启一次都没能改变结果(全程
空转),屏幕上还写着"你的显卡/驱动可能不支持透明窗口 GPU 合成"。

那句话是**错的诊断**。比不说更糟:照着它去查显卡驱动,永远查不到真因。
"""

import os

import pytest

from launcher import shell as _shell

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 真跑那次 electron.log 的原文(未删改)。
REAL_ROOT_SANDBOX_TAIL = (
    "[0907/105824.357779:FATAL:electron_main_delegate.cc(295)] "
    "Running as root without --no-sandbox is not supported. See https://crbug.com/638180."
)
#: 修好 --no-sandbox 之后,那次真跑换成了这一段。
REAL_NO_DISPLAY_TAIL = (
    "[2777:0907/110652.326575:ERROR:ozone_platform_x11.cc(240)] Missing X server or $DISPLAY\n"
    "[2777:0907/110652.326595:ERROR:env.cc(257)] The platform failed to initialize.  Exiting."
)


class TestItRecognisesWhatActuallyHappened:
    def test_the_real_root_sandbox_log_is_not_called_a_gpu_problem(self):
        assert _shell.classify_electron_crash(REAL_ROOT_SANDBOX_TAIL) == _shell.CRASH_ROOT_SANDBOX

    def test_the_real_headless_log_is_recognised_as_no_display(self):
        assert _shell.classify_electron_crash(REAL_NO_DISPLAY_TAIL) == _shell.CRASH_NO_DISPLAY

    def test_a_genuine_gpu_crash_is_still_called_a_gpu_crash(self):
        assert _shell.classify_electron_crash("GPU process isn't usable. Goodbye.") == _shell.CRASH_RENDER

    @pytest.mark.parametrize("tail", ["", "   ", "\n\n", "something nobody has seen before"])
    def test_unknown_stays_unknown_instead_of_defaulting_to_render(self, tail):
        """空与未知必须分得开,而且都**不许**默认归到渲染那一档。

        默认归到渲染,正是那句错误诊断的来源。
        """
        assert _shell.classify_electron_crash(tail) == _shell.CRASH_UNKNOWN


class TestEveryCategoryCanSayWhatToDo:
    def test_each_class_has_advice(self):
        for kind in (
            _shell.CRASH_ROOT_SANDBOX,
            _shell.CRASH_NO_DISPLAY,
            _shell.CRASH_RENDER,
            _shell.CRASH_UNKNOWN,
        ):
            assert _shell.CRASH_ADVICE[kind].strip()

    def test_only_the_render_class_may_blame_the_graphics_card(self):
        """显卡只许在**真的是渲染问题**那一档里被当成原因。

        注意要拦的是"**归因**给显卡",不是"提到显卡"—— sandbox 那一档里写着
        "与显卡驱动无关",那是**否定**,恰恰是这次要传达的话,不能误伤。
        """
        blame_words = ("可能不支持", "驱动不支持", "显卡问题")
        for kind, advice in _shell.CRASH_ADVICE.items():
            if kind == _shell.CRASH_RENDER:
                continue
            for word in blame_words:
                assert word not in advice, f"{kind} 这一档不该甩锅显卡:{advice}"
            # 提到显卡就必须是在否定它。
            if "显卡" in advice:
                assert ("无关" in advice) or ("不是" in advice), f"{kind} 提了显卡却没说清关系:{advice}"

    def test_the_unknown_advice_admits_it_does_not_know(self):
        assert "认不出" in _shell.CRASH_ADVICE[_shell.CRASH_UNKNOWN]

    def test_no_advice_repeats_itself(self):
        """措辞不许自我重复 —— 真跑里那句话把"桌面壳起不来"说了两遍。"""
        for kind, advice in _shell.CRASH_ADVICE.items():
            assert "桌面壳起不来" not in advice, f"{kind}: 调用方已经说过这四个字了"
            assert "后端与 API" not in advice, f"{kind}: 调用方已经说过这一句了"


class TestTheSandboxFlagIsAddedOnlyWhenNeeded:
    def test_it_is_added_when_asked(self):
        assert _shell.electron_extra_argv(no_sandbox=True) == ["--no-sandbox"]

    def test_it_is_not_on_by_default(self):
        """--no-sandbox 会削弱 Chromium 的沙箱隔离,不该无条件常开。"""
        assert _shell.electron_extra_argv() == []
        assert _shell.electron_extra_argv(no_sandbox=False) == []

    def test_running_as_root_is_a_real_check_not_a_guess(self, monkeypatch):
        monkeypatch.setattr(os, "geteuid", lambda: 0, raising=False)
        assert _shell.running_as_root() is True
        monkeypatch.setattr(os, "geteuid", lambda: 1000, raising=False)
        assert _shell.running_as_root() is False

    def test_non_posix_platforms_are_never_root(self, monkeypatch):
        monkeypatch.delattr(os, "geteuid", raising=False)
        assert _shell.running_as_root() is False


class TestTheLauncherActuallyUsesTheTriage:
    """源码判据:降级循环必须**先分诊、再降级**,而不是直接降。"""

    def _watch_src(self):
        import inspect

        from launcher.services import GalaxyUnified

        return inspect.getsource(GalaxyUnified.watch_processes)

    def test_it_classifies_before_it_degrades(self):
        src = self._watch_src()
        assert "classify_electron_crash" in src, "降级循环压根没分诊"
        i_class = src.index("classify_electron_crash")
        i_degrade = src.index("_electron_force_software = True")
        assert i_class < i_degrade, "必须先分诊,再决定降不降级"

    def test_the_sandbox_case_short_circuits_instead_of_degrading_render(self):
        src = self._watch_src()
        assert "CRASH_ROOT_SANDBOX" in src
        assert "_electron_no_sandbox" in src

    def test_the_headless_case_stops_instead_of_spinning(self):
        src = self._watch_src()
        assert "CRASH_NO_DISPLAY" in src

    def test_the_hardcoded_gpu_blame_is_gone(self):
        src = self._watch_src()
        assert "你的显卡/驱动可能不支持" not in src, "那句写死的错误诊断又回来了"
