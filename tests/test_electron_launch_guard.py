"""tests/test_electron_launch_guard.py
=======================================
core/electron_launch_guard.py 覆盖:桌面壳(Electron/Tauri)历史上有 4 条互相独立的
启动路径(system_orchestrator Phase 6 / unified_launcher.start_electron|start_tauri /
unified_launcher._start_electron_gui / launch_desktop.start_electron_frontend),只有
一条会写 .electron.pid 锁,其余三条既不检查也不写入——本测试验证抽出来的共享原语
(already_running/write_lock/resolve_gateway_port)行为本身是正确的:
- 没有锁文件 → already_running() 为 False。
- 锁文件指向当前存活进程(用本测试自身的 pid)→ already_running() 为 True。
- 锁文件指向一个不存在的 pid(陈旧锁)→ 自动清理并返回 False。
- resolve_gateway_port() 优先读 GALAXY_GATEWAY_PORT,其次 PORT,再退回
  core.port_config,最终兜底 9000。
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from core.electron_launch_guard import already_running, lock_path, resolve_gateway_port, write_lock


@pytest.fixture(autouse=True)
def _clean_lock_file():
    path = lock_path()
    if os.path.exists(path):
        os.remove(path)
    yield
    if os.path.exists(path):
        os.remove(path)


def test_no_lock_file_means_not_running():
    assert already_running() is False


def test_write_lock_then_already_running_detects_live_process():
    write_lock(os.getpid())
    assert already_running() is True


def test_stale_lock_from_dead_pid_is_cleaned_up_and_returns_false():
    # 起一个立刻退出的子进程,拿到一个保证已经不存在的 pid。
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    dead_pid = proc.pid
    write_lock(dead_pid)

    assert already_running() is False
    # 陈旧锁文件应已被清理,不再残留误导后续调用方。
    assert not os.path.exists(lock_path())


def test_write_lock_then_release_via_stale_cleanup_allows_relaunch():
    write_lock(os.getpid())
    assert already_running() is True
    # 模拟锁进程退出:把锁改写成一个死 pid,应视为可重新启动。
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    write_lock(proc.pid)
    assert already_running() is False


class TestResolveGatewayPort:
    def test_galaxy_gateway_port_env_wins(self, monkeypatch):
        monkeypatch.setenv("GALAXY_GATEWAY_PORT", "9911")
        monkeypatch.setenv("PORT", "9922")
        assert resolve_gateway_port() == 9911

    def test_port_env_used_when_galaxy_gateway_port_absent(self, monkeypatch):
        monkeypatch.delenv("GALAXY_GATEWAY_PORT", raising=False)
        monkeypatch.setenv("PORT", "9933")
        assert resolve_gateway_port() == 9933

    def test_falls_back_to_port_config_default(self, monkeypatch):
        monkeypatch.delenv("GALAXY_GATEWAY_PORT", raising=False)
        monkeypatch.delenv("PORT", raising=False)
        monkeypatch.delenv("GALAXY_UNIFIED_LAUNCHER_PORT", raising=False)
        # 默认配置里 unified_launcher 端口是 9000(见 core/port_config.py)。
        assert resolve_gateway_port() == 9000
