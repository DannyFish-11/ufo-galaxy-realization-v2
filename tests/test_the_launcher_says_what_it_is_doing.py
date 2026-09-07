"""启动器不许沉默：Phase 1 里面那六个子阶段必须真的到得了控制台。

真机症状（所有者报告）："环境检查以后它就停那儿了，然后就没显示了"。
根因不是少写了代码 —— 六个子阶段都在跑、都返回了结果 —— 而是它们只
``logger.info``，而 ``main.py`` 的控制台 handler 是 WARNING 级；同时 Phase 6
「桌面表面」会同步跑 ``npm install``（首次数分钟，npm 自己的输出还被
``capture_output`` 吃掉）。于是那几分钟里控制台一个字都没有。

这里钉住的是**修好之后不许再退回去**：
1. ``run_startup_sequence`` 必须把每个阶段的开始与结束交给旁观者；
2. 旁观者抛异常不许把启动带崩；
3. ``main.py`` 真的把旁观者接上了，且打出来的是中文阶段名；
4. 会长时间不吭声的阶段（Phase 6）必须在**阻塞之前**先说一声。
"""

import pytest

from core.system_orchestrator import (
    PHASE_LABELS,
    PHASE_MAY_BLOCK,
    PhaseResult,
    PhaseStatus,
    StartupPhase,
    SystemOrchestrator,
)


@pytest.fixture(autouse=True)
def _no_npm(monkeypatch):
    """桌面壳阶段不许在测试里真去联网装依赖。"""
    monkeypatch.setenv("GALAXY_SKIP_DESKTOP_SURFACE", "1")


class TestTheOrchestratorHandsOutProgress:
    def test_every_phase_is_announced_before_it_runs_and_after(self):
        seen = []
        orch = SystemOrchestrator(continue_on_failure=True)
        orch.run_startup_sequence(on_phase=lambda phase, result: seen.append((phase, result)))

        started = [p for p, r in seen if r is None]
        finished = [p for p, r in seen if r is not None]
        # 七个阶段，每个都要有开始和结束两次
        assert started == list(StartupPhase), started
        assert finished == list(StartupPhase), finished
        # 顺序必须是「先开始、后结束」，不能事后一次性补报
        for phase in StartupPhase:
            assert seen.index((phase, None)) < min(i for i, (p, r) in enumerate(seen) if p is phase and r is not None)

    def test_the_observer_gets_the_real_result_not_a_placeholder(self):
        results = {}
        orch = SystemOrchestrator(continue_on_failure=True)
        summary = orch.run_startup_sequence(
            on_phase=lambda phase, result: results.__setitem__(phase, result) if result else None
        )
        for r in summary.phase_results:
            assert results[r.phase] is r

    def test_a_broken_observer_cannot_take_startup_down(self):
        def _explode(phase, result):
            raise RuntimeError("显示层炸了")

        orch = SystemOrchestrator(continue_on_failure=True)
        summary = orch.run_startup_sequence(on_phase=_explode)
        assert summary.phase_results, "旁观者抛异常不该让启动序列少跑阶段"

    def test_no_observer_keeps_the_old_behaviour(self):
        orch = SystemOrchestrator(continue_on_failure=True)
        summary = orch.run_startup_sequence()
        assert summary.phase_results


class TestTheNamesHaveExactlyOneHome:
    def test_every_phase_has_a_label(self):
        missing = [p.name for p in StartupPhase if p not in PHASE_LABELS]
        assert not missing, f"这些阶段没有中文名，控制台只能打英文枚举名: {missing}"

    def test_the_blocking_phase_says_why(self):
        # Phase 6 是唯一会 shell 出去跑 npm install 的阶段；它必须带一句理由，
        # 否则入口没法在阻塞前把沉默解释掉。
        assert StartupPhase.DESKTOP_SURFACE in PHASE_MAY_BLOCK
        why = PHASE_MAY_BLOCK[StartupPhase.DESKTOP_SURFACE]
        assert "npm" in why and len(why) >= 10, why


@pytest.fixture()
def printed(monkeypatch):
    """截下 ``launcher.ui.step`` 的调用（打印器唯一的出口）。"""
    from launcher import ui

    lines = []
    monkeypatch.setattr(ui, "step", lambda name, status="ok", value="", **kw: lines.append((name, status, value)))
    return lines


class TestTheEntrypointReallyHandsItOver:
    def test_preflight_passes_the_printer_in(self, monkeypatch):
        import main
        from launcher.ui import print_preflight_phase

        captured = {}

        class _FakeOrch:
            def __init__(self, *a, **kw):
                pass

            def run_startup_sequence(self, *, on_phase=None):
                captured["on_phase"] = on_phase

                class _S:
                    def is_ready(self):
                        return True

                return _S()

        monkeypatch.setattr("core.system_orchestrator.SystemOrchestrator", _FakeOrch)
        assert main._run_orchestrator_preflight() is True
        assert captured["on_phase"] is print_preflight_phase, "预检没把打印器接上去"


class TestWhatTheLineActuallySays:
    def test_it_uses_the_chinese_label_and_the_real_status(self, printed):
        from launcher.ui import print_preflight_phase

        print_preflight_phase(
            StartupPhase.RUNTIME_SUBJECT,
            PhaseResult(StartupPhase.RUNTIME_SUBJECT, PhaseStatus.DEGRADED, detail="半条腿"),
        )
        assert printed == [(PHASE_LABELS[StartupPhase.RUNTIME_SUBJECT], "warn", "半条腿")]

    def test_a_failed_phase_prints_as_an_error_not_as_ok(self, printed):
        from launcher.ui import print_preflight_phase

        print_preflight_phase(
            StartupPhase.LOAD_CONFIG, PhaseResult(StartupPhase.LOAD_CONFIG, PhaseStatus.FAILED, detail="炸了")
        )
        assert printed[0][1] == "error", printed

    def test_the_long_phase_warns_before_it_blocks(self, printed):
        from launcher.ui import print_preflight_phase

        print_preflight_phase(StartupPhase.DESKTOP_SURFACE, None)
        assert printed, "桌面表面阻塞前必须先说一声，否则控制台会静默数分钟"
        assert PHASE_MAY_BLOCK[StartupPhase.DESKTOP_SURFACE] in printed[0][2]

    def test_the_fast_phases_do_not_double_their_output(self, printed):
        from launcher.ui import print_preflight_phase

        for phase in StartupPhase:
            if phase not in PHASE_MAY_BLOCK:
                print_preflight_phase(phase, None)
        assert printed == [], "亚秒级阶段不该预告，否则输出白白翻倍"
