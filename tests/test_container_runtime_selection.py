"""tests/test_container_runtime_selection.py
==============================================
容器运行时(Docker / Podman)选择解析回归防护。

resolve_runtime 优先级:环境 GALAXY_CONTAINER_RUNTIME > 已保存(.galaxy_runtime)
> 单一已装 > (两者都装且交互)提示 > 都没装 → ""。非交互终端不阻塞。
"""

from __future__ import annotations

import pytest

from core import container_runtime as cr


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    # 隔离持久化文件与环境,避免污染真实 .galaxy_runtime。
    monkeypatch.setattr(cr, "_CHOICE_FILE", tmp_path / ".galaxy_runtime")
    monkeypatch.delenv("GALAXY_CONTAINER_RUNTIME", raising=False)


def test_env_var_wins_when_installed(monkeypatch):
    monkeypatch.setattr(cr.shutil, "which", lambda name: "/usr/bin/podman" if name == "podman" else None)
    monkeypatch.setenv("GALAXY_CONTAINER_RUNTIME", "podman")
    assert cr.resolve_runtime(interactive=False) == "podman"


def test_single_installed_auto_selected_no_prompt(monkeypatch):
    monkeypatch.setattr(cr.shutil, "which", lambda name: "/usr/bin/docker" if name == "docker" else None)
    # interactive=True 但只装了一个 → 不应提示,直接用它
    assert cr.resolve_runtime(interactive=True) == "docker"


def test_none_installed_returns_empty(monkeypatch):
    monkeypatch.setattr(cr.shutil, "which", lambda name: None)
    assert cr.resolve_runtime(interactive=True) == ""


def test_both_installed_noninteractive_defaults_to_docker_first(monkeypatch):
    monkeypatch.setattr(cr.shutil, "which", lambda name: f"/usr/bin/{name}" if name in ("docker", "podman") else None)
    # 非交互(interactive=False)→ avail[0]=docker(docker 优先),不阻塞
    assert cr.resolve_runtime(interactive=False) == "docker"


def test_saved_choice_used_when_no_env(monkeypatch, tmp_path):
    monkeypatch.setattr(cr.shutil, "which", lambda name: f"/usr/bin/{name}" if name in ("docker", "podman") else None)
    (tmp_path / ".galaxy_runtime").write_text("podman", encoding="utf-8")
    monkeypatch.setattr(cr, "_CHOICE_FILE", tmp_path / ".galaxy_runtime")
    assert cr.resolve_runtime(interactive=False) == "podman"


def test_compose_base_shape(monkeypatch):
    # docker compose 子命令可用 → [docker, compose]
    monkeypatch.setattr(cr.shutil, "which", lambda name: "/usr/bin/docker" if name == "docker" else None)

    class _OK:
        returncode = 0

    monkeypatch.setattr(cr.subprocess, "run", lambda *a, **k: _OK())
    assert cr.compose_base("docker") == ["/usr/bin/docker", "compose"]
