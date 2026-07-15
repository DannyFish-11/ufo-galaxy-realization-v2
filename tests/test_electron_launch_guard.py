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


class _FakeShutil:
    """假 shutil：按预置名单回答 which()。"""

    def __init__(self, on_path):
        self._on_path = set(on_path)

    def which(self, name):
        return f"C:\\fake\\{name}" if name in self._on_path else None


class TestWindowsMsvcPrecheck:
    """Windows MSVC 链接器预检：只认 cl.exe / 磁盘上真实存在的 link.exe，
    杜绝"裸 link.exe 或组件已注册"的假阳性(真机踩过：放行后编译数分钟才崩)。"""

    def test_cl_on_path_is_msvc(self):
        from core.electron_launch_guard import _link_on_path_is_msvc

        assert _link_on_path_is_msvc(_FakeShutil(["cl.exe"])) is True

    def test_bare_link_on_path_not_trusted(self):
        # 只有 link.exe(可能是非 MSVC 的)→ 不认，交由磁盘核实
        from core.electron_launch_guard import _link_on_path_is_msvc

        assert _link_on_path_is_msvc(_FakeShutil(["link.exe"])) is False
        assert _link_on_path_is_msvc(_FakeShutil([])) is False

    def test_present_true_when_cl_on_path(self, monkeypatch):
        import core.electron_launch_guard as g

        # cl 在 PATH → 无需 vswhere 即判就位（且不应调用 vswhere 探测）
        monkeypatch.setattr(g, "_windows_msvc_linker_dir", lambda sp: (_ for _ in ()).throw(AssertionError("不该调用")))
        assert g._windows_msvc_present(_FakeShutil(["cl.exe"]), None) is True

    def test_present_true_when_disk_linker_found(self, monkeypatch):
        import core.electron_launch_guard as g

        monkeypatch.setattr(g, "_windows_msvc_linker_dir", lambda sp: r"C:\VS\VC\Tools\MSVC\14.4\bin\Hostx64\x64")
        assert g._windows_msvc_present(_FakeShutil([]), None) is True

    def test_present_false_when_registered_but_no_binary(self, monkeypatch):
        import core.electron_launch_guard as g

        # 组件"已注册"但磁盘无 link.exe → linker_dir 返回 None → 判为不就位
        monkeypatch.setattr(g, "_windows_msvc_linker_dir", lambda sp: None)
        assert g._windows_msvc_present(_FakeShutil([]), None) is False

    def test_prepend_path_dedups(self, monkeypatch):
        # 用不含 os.pathsep 的目录名，使 dedup 逻辑在任意平台可测
        # (真实 Windows 盘符路径含 ':'，但那里 pathsep 是 ';'，不会误切)
        import core.electron_launch_guard as g

        monkeypatch.setenv("PATH", "dirA" + os.pathsep + "dirB")
        g._prepend_path("msvcbin")
        assert os.environ["PATH"].startswith("msvcbin" + os.pathsep)
        # 再插一次不重复
        g._prepend_path("msvcbin")
        assert os.environ["PATH"].count("msvcbin") == 1

    def test_hint_loads_vcvars_and_proceeds_when_linker_on_disk(self, monkeypatch):
        import core.electron_launch_guard as g

        monkeypatch.setattr(g, "_link_on_path_is_msvc", lambda sh: False)
        monkeypatch.setattr(g, "_windows_msvc_linker_dir", lambda sp: r"C:\VS\...\Hostx64\x64")
        # 磁盘有链接器 → 加载完整 vcvars64 环境成功 → 返回 None（放行构建），不触发自动安装
        calls = {"vcvars": 0}

        def _fake_vcvars(sp):
            calls["vcvars"] += 1
            return True

        monkeypatch.setattr(g, "_windows_setup_msvc_build_env", _fake_vcvars)
        monkeypatch.setattr(g, "_windows_try_install_msvc", lambda *a: (_ for _ in ()).throw(AssertionError("不该装")))
        assert g._windows_msvc_hint(_FakeShutil([]), None) is None
        assert calls["vcvars"] == 1  # 走的是 vcvars 加载,不是裸 PATH 注入

    def test_hint_returns_native_tools_hint_when_vcvars_load_fails(self, monkeypatch):
        # 有链接器但 vcvars 加载失败 → 不硬着头皮构建(会 LNK1181),回退 Electron 并提示
        # 从 x64 Native Tools 手动构建
        import core.electron_launch_guard as g

        monkeypatch.setattr(g, "_link_on_path_is_msvc", lambda sh: False)
        monkeypatch.setattr(g, "_windows_msvc_linker_dir", lambda sp: r"C:\VS\...\Hostx64\x64")
        monkeypatch.setattr(g, "_windows_setup_msvc_build_env", lambda sp: False)
        out = g._windows_msvc_hint(_FakeShutil([]), None)
        assert out is not None and "Native Tools" in out

    def test_hint_returns_manual_msg_when_absent_and_autoinstall_off(self, monkeypatch):
        import core.electron_launch_guard as g

        monkeypatch.setenv("GALAXY_TAURI_AUTO_INSTALL_MSVC", "0")
        monkeypatch.setattr(g, "_link_on_path_is_msvc", lambda sh: False)
        monkeypatch.setattr(g, "_windows_msvc_linker_dir", lambda sp: None)
        out = g._windows_msvc_hint(_FakeShutil([]), None)
        assert out is not None and "MSVC" in out and "BuildTools" in out


class _FakeR:
    def __init__(self, rc, out):
        self.returncode = rc
        self.stdout = out


class _FakeSub:
    """假 subprocess:第 1 次(vswhere)返回安装路径,第 2 次(cmd set)返回 vcvars dump。"""

    _DEFAULT_DUMP = "PATH=C:\\vc\\bin\nLIB=C:\\sdk\\lib\nINCLUDE=C:\\sdk\\inc\n=C:=weird\n"

    def __init__(self, install="C:\\VS\\BuildTools", dump=None):
        self.n = 0
        self._install = install
        self._dump = dump if dump is not None else self._DEFAULT_DUMP

    def run(self, cmd, **kw):
        self.n += 1
        if self.n == 1:
            return _FakeR(0, self._install + "\n")
        return _FakeR(0, self._dump)


class TestVcvarsBuildEnv:
    """vcvars64 完整构建环境加载:PATH+LIB+INCLUDE 一并灌进 os.environ(修 LNK1181)。"""

    def test_applies_full_env_and_confirms_cl(self, monkeypatch):
        import shutil

        import core.electron_launch_guard as g

        monkeypatch.setattr(g.os.path, "isfile", lambda p: True)  # vswhere + vcvars64.bat 都在
        monkeypatch.setattr(shutil, "which", lambda name: "C:\\vc\\bin\\cl.exe" if name == "cl.exe" else None)
        monkeypatch.delenv("LIB", raising=False)
        monkeypatch.delenv("INCLUDE", raising=False)
        ok = g._windows_setup_msvc_build_env(_FakeSub())
        assert ok is True
        # 关键:LIB/INCLUDE(Windows SDK 库/头所在)也被设上了,不只是 PATH
        assert os.environ["LIB"] == "C:\\sdk\\lib"
        assert os.environ["INCLUDE"] == "C:\\sdk\\inc"

    def test_returns_false_when_cl_still_absent(self, monkeypatch):
        import shutil

        import core.electron_launch_guard as g

        monkeypatch.setattr(g.os.path, "isfile", lambda p: True)
        monkeypatch.setattr(shutil, "which", lambda name: None)  # 加载后 cl 仍不在 → 判失败
        ok = g._windows_setup_msvc_build_env(_FakeSub())
        assert ok is False

    def test_returns_false_when_no_vswhere(self, monkeypatch):
        import core.electron_launch_guard as g

        monkeypatch.setattr(g.os.path, "isfile", lambda p: False)  # vswhere 不存在
        assert g._windows_setup_msvc_build_env(_FakeSub()) is False
