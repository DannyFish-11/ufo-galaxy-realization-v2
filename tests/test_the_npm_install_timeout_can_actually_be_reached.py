"""装前端依赖超时那条降级路,必须是**走得到**的路。

`_run_phase_6_desktop_surface` 里的 `npm install` 原本把等待上限硬写成 120 秒,
而调它的测试跑在 pytest 的 120 秒上限里 —— 内层不小于外层,于是
`npm install timed out after 120s` 那条优雅降级**永远到不了**,只会被外层硬超时
打断。代码里有那条分支、注释里也写着它存在,但没有任何一次执行真的走过它:
典型的"看起来接上了,其实没有"。

这里守两件事:
  1. 上限是**一处权威**且现读环境变量 —— 调小之后真的算数(不是冻在 import 那刻)。
  2. 真的把 TimeoutExpired 打进去,那条降级分支确实回 DEGRADED,且它说出来的
     秒数就是当时生效的那个数,不是写死的 120。
"""

import os
import subprocess

import pytest

from core.system_orchestrator import (
    NPM_INSTALL_MIRROR_TIMEOUT_S,
    NPM_INSTALL_TIMEOUT_S,
    PhaseStatus,
    SystemOrchestrator,
    npm_install_timeouts,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("GALAXY_NPM_INSTALL_TIMEOUT_S", raising=False)
    monkeypatch.delenv("GALAXY_NPM_INSTALL_MIRROR_TIMEOUT_S", raising=False)
    monkeypatch.delenv("GALAXY_SKIP_DESKTOP_SURFACE", raising=False)


class TestTheWaitCeilingIsOneAuthority:
    def test_default_is_unchanged_so_real_machines_behave_exactly_as_before(self):
        assert npm_install_timeouts() == (NPM_INSTALL_TIMEOUT_S, NPM_INSTALL_MIRROR_TIMEOUT_S)

    def test_turning_it_down_actually_takes_effect(self, monkeypatch):
        monkeypatch.setenv("GALAXY_NPM_INSTALL_TIMEOUT_S", "5")
        primary, mirror = npm_install_timeouts()
        assert primary == 5.0
        # 镜像重试跟着一起缩,否则内层还是压不到外层以下。
        assert mirror == pytest.approx(12.5)

    def test_the_mirror_ceiling_can_be_set_on_its_own(self, monkeypatch):
        monkeypatch.setenv("GALAXY_NPM_INSTALL_TIMEOUT_S", "5")
        monkeypatch.setenv("GALAXY_NPM_INSTALL_MIRROR_TIMEOUT_S", "7")
        assert npm_install_timeouts() == (5.0, 7.0)

    @pytest.mark.parametrize("junk", ["", "  ", "abc", "0", "-3"])
    def test_junk_falls_back_to_the_default_instead_of_crashing_startup(self, monkeypatch, junk):
        monkeypatch.setenv("GALAXY_NPM_INSTALL_TIMEOUT_S", junk)
        assert npm_install_timeouts()[0] == NPM_INSTALL_TIMEOUT_S


class TestTheGracefulDegradationIsReachable:
    """把 TimeoutExpired 真打进去,看那条分支到底走不走得到。"""

    def _phase(self, monkeypatch, tmp_path, *, seconds: str):
        monkeypatch.setenv("GALAXY_NPM_INSTALL_TIMEOUT_S", seconds)

        electron_dir = tmp_path / "electron"
        electron_dir.mkdir()
        (electron_dir / "package.json").write_text("{}", encoding="utf-8")

        orch = SystemOrchestrator()

        # 让这一阶段看见"目录在、依赖不全",从而真的走到 npm install。
        monkeypatch.setattr(
            "core.system_orchestrator.os.path.dirname",
            lambda _p: str(tmp_path),
            raising=False,
        )
        monkeypatch.setattr("core.electron_launch_guard.already_running", lambda: False)
        monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/npm" if "npm" in name else "/usr/bin/node")

        called = {}

        def _boom(argv, **kw):
            called["timeout"] = kw.get("timeout")
            raise subprocess.TimeoutExpired(cmd=argv, timeout=kw.get("timeout"))

        monkeypatch.setattr(subprocess, "run", _boom)
        return orch, called

    def test_it_returns_degraded_and_says_the_ceiling_that_was_actually_in_force(self, monkeypatch, tmp_path):
        orch, called = self._phase(monkeypatch, tmp_path, seconds="7")
        result = orch._run_phase_6_desktop_surface()

        # 走到了 —— 而不是被外层硬超时打断。
        assert result.status is PhaseStatus.DEGRADED
        # 说出来的秒数 == 当时真正传给子进程的那个数。写死 120 的话这里就红。
        assert "7s" in result.detail, result.detail
        assert "7 秒" in (result.said or ""), result.said
        assert called.get("timeout") == 7.0

    def test_the_number_on_screen_is_never_a_hardcoded_120(self, monkeypatch, tmp_path):
        orch, _ = self._phase(monkeypatch, tmp_path, seconds="3")
        result = orch._run_phase_6_desktop_surface()
        assert "120" not in result.detail, result.detail
        assert "120" not in (result.said or ""), result.said


def test_the_source_no_longer_hardcodes_the_two_numbers():
    """两个数只许在常量处出现,调用点必须取常量。"""
    src = open(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core", "system_orchestrator.py"),
        encoding="utf-8",
    ).read()
    assert "timeout=120," not in src
    assert "timeout=300," not in src
