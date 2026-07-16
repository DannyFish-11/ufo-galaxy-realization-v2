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


def test_both_installed_noninteractive_requires_explicit_choice(monkeypatch):
    monkeypatch.setattr(cr.shutil, "which", lambda name: f"/usr/bin/{name}" if name in ("docker", "podman") else None)
    # In headless mode we must not silently pick by list order when both are installed.
    assert cr.resolve_runtime(interactive=False) == ""


def test_prefer_recommended_puts_podman_first():
    # 交互菜单的展示/默认把推荐运行时(Podman·更轻)排到最前,其余保持原序
    assert cr._prefer_recommended(["docker", "podman"]) == ["podman", "docker"]
    assert cr._prefer_recommended(["podman", "docker"]) == ["podman", "docker"]
    assert cr._prefer_recommended(["docker"]) == ["docker"]  # 无 podman → 不变
    assert cr._RECOMMENDED == "podman"


def test_saved_choice_used_when_no_env(monkeypatch, tmp_path):
    monkeypatch.setattr(cr.shutil, "which", lambda name: f"/usr/bin/{name}" if name in ("docker", "podman") else None)
    (tmp_path / ".galaxy_runtime").write_text('{"runtime":"podman","source":"test"}', encoding="utf-8")
    monkeypatch.setattr(cr, "_CHOICE_FILE", tmp_path / ".galaxy_runtime")
    assert cr.load_choice_record()["runtime"] == "podman"
    assert cr.resolve_runtime(interactive=False) == "podman"


def test_fallback_when_saved_runtime_becomes_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(cr, "_CHOICE_FILE", tmp_path / ".galaxy_runtime")
    (tmp_path / ".galaxy_runtime").write_text('{"runtime":"docker","source":"test"}', encoding="utf-8")
    monkeypatch.setattr(
        cr.shutil,
        "which",
        lambda name: (
            "/usr/bin/podman" if name == "podman" else ("/usr/bin/docker" if name == "docker-compose" else None)
        ),
    )
    # Saved docker is unavailable, and only podman exists -> fallback to podman.
    assert cr.resolve_runtime(interactive=False) == "podman"


def test_choice_record_written_as_json(monkeypatch, tmp_path):
    monkeypatch.setattr(cr, "_CHOICE_FILE", tmp_path / ".galaxy_runtime")
    cr.save_choice("docker", source="unit-test")
    record = cr.load_choice_record()
    assert record["runtime"] == "docker"
    assert record["source"] == "unit-test"
    assert record["selected_at"] is not None


def test_compose_base_shape(monkeypatch):
    # docker compose 子命令可用 → [docker, compose]
    monkeypatch.setattr(cr.shutil, "which", lambda name: "/usr/bin/docker" if name == "docker" else None)

    class _OK:
        returncode = 0

    monkeypatch.setattr(cr.subprocess, "run", lambda *a, **k: _OK())
    assert cr.compose_base("docker") == ["/usr/bin/docker", "compose"]
