"""tests/test_setup_wizard_container_runtime.py
==================================================
克隆界面（首启配置向导）回归防护:两个真 bug 的锁定测试。

Bug 1 —— setup_wizard._configure_databases() 此前对每个数据库都写死打印
"docker run ..."，完全没有 Podman 选项。现应复用 core.container_runtime 的
选择器（不重新造文案），并把选中的运行时代入命令前缀。

Bug 2 —— main.py::_run_setup_wizard() 此前调用 setup_wizard.py 不带任何参数，
落到其 main() 的默认分支 quick_setup()（纯非交互，探测不到 env API Key 就直接
退出），导致 start.bat 首启（无 .env 时自动 `python main.py --setup`）实际上
【整个交互向导都没跑】——包括数据库/容器运行时选择在内的 run_interactive_setup()
全部被跳过。这正是"克隆界面里没有 Docker/Podman 选择"的根因。
"""

from __future__ import annotations

import io
import sys

import pytest

from core import container_runtime as cr
import setup_wizard as sw


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    # 隔离持久化文件与环境,避免污染真实 .galaxy_runtime / 真实 stdin。
    monkeypatch.setattr(cr, "_CHOICE_FILE", tmp_path / ".galaxy_runtime")
    monkeypatch.delenv("GALAXY_CONTAINER_RUNTIME", raising=False)


def _run_configure_databases(monkeypatch, capsys, stdin_text: str, which_map: dict):
    monkeypatch.setattr(cr.shutil, "which", lambda name: which_map.get(name))
    fake_stdin = io.StringIO(stdin_text)
    fake_stdin.isatty = lambda: True  # 让 interactive_select 走真正的菜单分支
    monkeypatch.setattr(sys, "stdin", fake_stdin)

    wiz = sw.SetupWizard()
    wiz.config = {}
    wiz._configure_databases()
    return capsys.readouterr().out


def test_configure_databases_offers_podman_choice_when_both_installed(monkeypatch, capsys):
    """两者都装时,_configure_databases 必须展示 Docker/Podman 选择菜单(回归 bug 1)。"""
    out = _run_configure_databases(
        monkeypatch, capsys,
        stdin_text="1\n" + "\n" * 20,  # '1' = Podman(推荐,排最前）
        which_map={"docker": "/usr/bin/docker", "podman": "/usr/bin/podman"},
    )
    assert "选择容器运行时" in out
    assert "Podman" in out and "Docker" in out


def test_configure_databases_substitutes_chosen_runtime_into_commands(monkeypatch, capsys):
    """选 Podman 后,打印的部署命令必须是 podman run,而不是硬编码的 docker run。"""
    out = _run_configure_databases(
        monkeypatch, capsys,
        stdin_text="1\n" + "\n" * 20,
        which_map={"docker": "/usr/bin/docker", "podman": "/usr/bin/podman"},
    )
    assert "podman run" in out
    assert "docker run" not in out
    assert "Podman 部署:" in out


def test_configure_databases_falls_back_to_docker_when_only_docker_installed(monkeypatch, capsys):
    """只装了 Docker 时不应打扰用户选择,直接沿用 docker(与 resolve_runtime 语义一致)。"""
    out = _run_configure_databases(
        monkeypatch, capsys,
        stdin_text="\n" * 20,
        which_map={"docker": "/usr/bin/docker"},
    )
    assert "docker run" in out
    assert "Docker 部署:" in out


def test_run_setup_wizard_invokes_interactive_flag(monkeypatch, tmp_path):
    """main.py::_run_setup_wizard 必须传 --interactive,否则落到无交互的 quick_setup()
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
        f"_run_setup_wizard 必须传 --interactive,实际调用: {captured['cmd']}"
    )
