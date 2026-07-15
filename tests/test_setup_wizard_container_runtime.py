"""tests/test_setup_wizard_container_runtime.py
==================================================
克隆界面（首启配置向导）回归防护:三个真 bug 的锁定测试。

Bug 1 —— setup_wizard._configure_databases() 此前对每个数据库都写死打印
"docker run ..."，完全没有 Podman 选项。现应复用 core.container_runtime 的
选择器（不重新造文案），并把选中的运行时代入命令前缀。

Bug 2 —— main.py::_run_setup_wizard() 此前调用 setup_wizard.py 不带任何参数，
落到其 main() 的默认分支 quick_setup()（纯非交互，探测不到 env API Key 就直接
退出），导致 start.bat 首启（无 .env 时自动 `python main.py --setup`）实际上
【整个交互向导都没跑】——包括数据库/容器运行时选择在内的 run_interactive_setup()
全部被跳过。

Bug 3（第二轮真机反馈:"Docker 的和 podman 选择压根就没有啊"）—— Bug 1/2 修完
后，_configure_databases() 改调 core.container_runtime.resolve_runtime()，但
该函数的设计是给【日常静默启动】用的（unified_launcher.ensure_docker_infra，
每次 python main.py 都会走）："只装了一个就直接用，不弹菜单"——这在日常启动
路径上是对的（不该打扰用户），但绝大多数机器只装了 Docker（比 Podman 普及
得多），于是首启向导里"选择"实际上几乎从来不出现，正是本轮反馈的根因。
新增 core.container_runtime.setup_wizard_select_runtime()：专给一次性交互
配置场景用，无论已装几个都【总是】展示完整菜单；_configure_databases() 改调
这个新函数，而不是复用日常启动路径的 resolve_runtime()。
"""

from __future__ import annotations

import io
import sys

import pytest

from core import container_runtime as cr
import setup_wizard as sw


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    # 隔离持久化文件与环境，避免污染真实 .galaxy_runtime / 真实 stdin。
    monkeypatch.setattr(cr, "_CHOICE_FILE", tmp_path / ".galaxy_runtime")
    monkeypatch.delenv("GALAXY_CONTAINER_RUNTIME", raising=False)
    # 禁用真实的自动安装尝试（会在 CI/沙盒里真的跑 apt-get/winget 等系统级命令）。
    monkeypatch.setattr(cr, "can_auto_install", lambda: False)
    monkeypatch.setattr(cr, "background_install", lambda rt: False)


def _run_configure_databases(monkeypatch, capsys, stdin_text: str, which_map: dict):
    monkeypatch.setattr(cr.shutil, "which", lambda name: which_map.get(name))
    fake_stdin = io.StringIO(stdin_text)
    fake_stdin.isatty = lambda: True
    monkeypatch.setattr(sys, "stdin", fake_stdin)

    wiz = sw.SetupWizard()
    wiz.config = {}
    wiz._configure_databases()
    return capsys.readouterr().out


class TestConfigureDatabasesUsesSetupWizardSelector:
    """_configure_databases 必须走 setup_wizard_select_runtime（不是 resolve_runtime）。"""

    def test_offers_podman_choice_when_both_installed(self, monkeypatch, capsys):
        out = _run_configure_databases(
            monkeypatch, capsys,
            stdin_text="1\n" + "\n" * 20,  # '1' = Podman（推荐，排最前）
            which_map={"docker": "/usr/bin/docker", "podman": "/usr/bin/podman"},
        )
        assert "选择容器运行时" in out
        assert "Podman" in out and "Docker" in out

    def test_substitutes_chosen_runtime_into_commands(self, monkeypatch, capsys):
        out = _run_configure_databases(
            monkeypatch, capsys,
            stdin_text="1\n" + "\n" * 20,
            which_map={"docker": "/usr/bin/docker", "podman": "/usr/bin/podman"},
        )
        assert "podman run" in out
        assert "docker run" not in out
        assert "Podman 部署:" in out

    def test_menu_still_shown_when_only_docker_installed(self, monkeypatch, capsys):
        """回归锁定(bug 3 的核心断言):只装 Docker 时，菜单必须依然出现，
        不能像 resolve_runtime 那样静默跳过——这正是"压根没有选择"的真根因。
        """
        out = _run_configure_databases(
            monkeypatch, capsys,
            stdin_text="2\n" + "\n" * 20,  # 显式选 [2]=Docker（已安装，立即生效）
            which_map={"docker": "/usr/bin/docker"},
        )
        assert "选择容器运行时" in out, "只装了一个运行时时菜单被跳过——回归了 bug 3"
        assert "Podman" in out and "Docker" in out, "菜单必须同时列出两个选项，不能只显示已装的那个"
        assert "docker run" in out
        assert "Docker 部署:" in out

    def test_can_pick_uninstalled_runtime_when_only_docker_installed(self, monkeypatch, capsys):
        """只装 Docker 时依然可以【选 Podman】——即便它还没装。"""
        out = _run_configure_databases(
            monkeypatch, capsys,
            stdin_text="1\n" + "\n" * 20,  # '1' = Podman（未安装）
            which_map={"docker": "/usr/bin/docker"},
        )
        assert "已记住偏好: Podman" in out
        assert cr.load_choice() == "podman"


class TestSetupWizardSelectRuntime:
    """core.container_runtime.setup_wizard_select_runtime 的直接单测。"""

    def test_env_var_wins_without_prompting(self, monkeypatch, capsys):
        monkeypatch.setattr(cr.shutil, "which", lambda name: "/usr/bin/podman" if name == "podman" else None)
        monkeypatch.setenv("GALAXY_CONTAINER_RUNTIME", "podman")
        result = cr.setup_wizard_select_runtime()
        assert result == "podman"
        assert "选择容器运行时" not in capsys.readouterr().out

    def test_non_interactive_falls_back_silently(self, monkeypatch):
        monkeypatch.setattr(cr.shutil, "which", lambda name: "/usr/bin/docker" if name == "docker" else None)
        fake_stdin = io.StringIO("")
        fake_stdin.isatty = lambda: False
        monkeypatch.setattr(sys, "stdin", fake_stdin)
        assert cr.setup_wizard_select_runtime() == "docker"

    def test_single_installed_still_shows_full_menu(self, monkeypatch, capsys):
        """核心回归断言:与 resolve_runtime 不同，单一已装不应跳过菜单。"""
        monkeypatch.setattr(cr.shutil, "which", lambda name: "/usr/bin/docker" if name == "docker" else None)
        fake_stdin = io.StringIO("2\n")  # 显式选 Docker
        fake_stdin.isatty = lambda: True
        monkeypatch.setattr(sys, "stdin", fake_stdin)

        result = cr.setup_wizard_select_runtime()
        out = capsys.readouterr().out
        assert "选择容器运行时" in out
        assert "Docker" in out and "Podman" in out
        assert result == "docker"

    def test_picking_installed_runtime_returns_immediately_usable(self, monkeypatch):
        monkeypatch.setattr(
            cr.shutil, "which",
            lambda name: {"docker": "/usr/bin/docker", "podman": "/usr/bin/podman"}.get(name),
        )
        fake_stdin = io.StringIO("2\n")  # Docker
        fake_stdin.isatty = lambda: True
        monkeypatch.setattr(sys, "stdin", fake_stdin)

        assert cr.setup_wizard_select_runtime() == "docker"
        assert cr.load_choice() == "docker"

    def test_picking_uninstalled_runtime_saves_preference_and_returns_empty(self, monkeypatch):
        """选中一个还没装的运行时:偏好必须持久化(下次自动采用),但本次不可用(返回"")。"""
        monkeypatch.setattr(cr.shutil, "which", lambda name: "/usr/bin/docker" if name == "docker" else None)
        fake_stdin = io.StringIO("1\n")  # Podman，未安装
        fake_stdin.isatty = lambda: True
        monkeypatch.setattr(sys, "stdin", fake_stdin)

        result = cr.setup_wizard_select_runtime()
        assert result == ""
        assert cr.load_choice() == "podman"

    def test_skip_returns_empty_without_saving(self, monkeypatch):
        monkeypatch.setattr(cr.shutil, "which", lambda name: "/usr/bin/docker" if name == "docker" else None)
        fake_stdin = io.StringIO("s\n")
        fake_stdin.isatty = lambda: True
        monkeypatch.setattr(sys, "stdin", fake_stdin)

        assert cr.setup_wizard_select_runtime() == ""
        assert cr.load_choice() == ""

    def test_enter_picks_recommended_default(self, monkeypatch):
        monkeypatch.setattr(
            cr.shutil, "which",
            lambda name: {"docker": "/usr/bin/docker", "podman": "/usr/bin/podman"}.get(name),
        )
        fake_stdin = io.StringIO("\n")  # 回车 = 默认（推荐 Podman）
        fake_stdin.isatty = lambda: True
        monkeypatch.setattr(sys, "stdin", fake_stdin)

        assert cr.setup_wizard_select_runtime() == "podman"


def test_run_setup_wizard_invokes_interactive_flag(monkeypatch, tmp_path):
    """main.py::_run_setup_wizard 必须传 --interactive，否则落到无交互的 quick_setup()
    （bug 2 的根因）——用一个假的 setup_wizard.py 路径 + mock subprocess.call 锁定调用参数。
    """
    import main as main_mod

    captured = {}

    def _fake_call(cmd, *a, **k):
        captured["cmd"] = cmd
        return 0

    fake_wizard = tmp_path / "setup_wizard.py"
    fake_wizard.write_text("# stub\n", encoding="utf-8")

    monkeypatch.setattr(main_mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(main_mod.subprocess, "call", _fake_call)
    monkeypatch.setattr(main_mod.sys, "exit", lambda code=0: (_ for _ in ()).throw(SystemExit(code)))

    with pytest.raises(SystemExit):
        main_mod._run_setup_wizard()

    assert "cmd" in captured, "subprocess.call 应被调用"
    assert "--interactive" in captured["cmd"], (
        f"_run_setup_wizard 必须传 --interactive，实际调用: {captured['cmd']}"
    )
