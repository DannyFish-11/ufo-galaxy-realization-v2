"""tests/test_daemon_autostart.py
=====================================

开机自启(daemon/autostart.py,基于现有守护进程)+ 守护进程 Windows 兼容修复。
系统调用经 _run 抽象,测试全部 mock,不碰真实 systemctl/schtasks/launchctl。
"""

from __future__ import annotations

import signal

import pytest

import daemon.autostart as au


@pytest.fixture()
def calls(monkeypatch):
    """mock 掉系统调用,记录命令。"""
    recorded = []

    def _fake_run(cmd):
        recorded.append(cmd)
        return 0, "ok"

    monkeypatch.setattr(au, "_run", _fake_run)
    return recorded


# ── 内容生成(纯函数)──


class TestContent:
    def test_daemon_command_uses_existing_daemon(self):
        cmd = au.daemon_command()
        assert cmd[1].endswith("galaxy_daemon.py")  # 基于现有守护进程
        assert "--config" in cmd and cmd[-1].endswith("config.json")

    def test_systemd_unit_shape(self):
        unit = au.systemd_unit_content()
        assert "galaxy_daemon.py" in unit
        assert f"WorkingDirectory={au.REPO_ROOT}" in unit
        assert "Restart=on-failure" in unit  # 只兜守护进程本体
        assert "WantedBy=default.target" in unit

    def test_launchd_plist_shape(self):
        plist = au.launchd_plist_content()
        assert au.PLIST_LABEL in plist
        assert "galaxy_daemon.py" in plist
        assert "<key>RunAtLoad</key>" in plist and "<true/>" in plist

    def test_schtasks_command_shape(self):
        cmd = au.schtasks_create_command()
        assert cmd[:2] == ["schtasks", "/Create"]
        assert "/SC" in cmd and cmd[cmd.index("/SC") + 1] == "ONLOGON"
        tr = cmd[cmd.index("/TR") + 1]
        assert "galaxy_daemon.py" in tr and "cd /d" in tr  # 工作目录经 cmd /c cd 保证
        assert "/F" in cmd  # 幂等覆盖


# ── 平台分派 + 安装/卸载/状态(mock 落地)──


class TestLinux:
    @pytest.fixture(autouse=True)
    def _linux(self, monkeypatch):
        monkeypatch.setattr(au.sys, "platform", "linux")

    def test_install_writes_unit_and_enables(self, tmp_path, calls):
        r = au.install(home=tmp_path)
        unit = au.systemd_unit_path(tmp_path)
        assert unit.exists() and "galaxy_daemon.py" in unit.read_text(encoding="utf-8")
        assert ["systemctl", "--user", "daemon-reload"] in calls
        assert ["systemctl", "--user", "enable", au.UNIT_NAME] in calls
        assert r["ok"] == "True"

    def test_install_idempotent(self, tmp_path, calls):
        au.install(home=tmp_path)
        au.install(home=tmp_path)  # 重复安装 = 覆盖更新,不抛
        assert au.systemd_unit_path(tmp_path).exists()

    def test_uninstall_removes_unit(self, tmp_path, calls):
        au.install(home=tmp_path)
        r = au.uninstall(home=tmp_path)
        assert not au.systemd_unit_path(tmp_path).exists()
        assert ["systemctl", "--user", "disable", au.UNIT_NAME] in calls
        assert r["ok"] == "True"

    def test_uninstall_when_never_installed_is_safe(self, tmp_path, calls):
        r = au.uninstall(home=tmp_path)
        assert r["ok"] == "True"

    def test_status(self, tmp_path, calls):
        assert au.status(home=tmp_path)["installed"] == "False"
        au.install(home=tmp_path)
        assert au.status(home=tmp_path)["installed"] == "True"


class TestMacos:
    @pytest.fixture(autouse=True)
    def _mac(self, monkeypatch):
        monkeypatch.setattr(au.sys, "platform", "darwin")

    def test_install_writes_plist_and_loads(self, tmp_path, calls):
        r = au.install(home=tmp_path)
        plist = au.launchd_plist_path(tmp_path)
        assert plist.exists()
        assert any(c[:2] == ["launchctl", "load"] for c in calls)
        assert r["ok"] == "True"

    def test_uninstall_unloads_and_removes(self, tmp_path, calls):
        au.install(home=tmp_path)
        r = au.uninstall(home=tmp_path)
        assert not au.launchd_plist_path(tmp_path).exists()
        assert r["ok"] == "True"


class TestWindows:
    @pytest.fixture(autouse=True)
    def _win(self, monkeypatch):
        monkeypatch.setattr(au.sys, "platform", "win32")

    def test_install_calls_schtasks_create(self, tmp_path, calls):
        r = au.install(home=tmp_path)
        assert calls and calls[0][:2] == ["schtasks", "/Create"]
        assert r["ok"] == "True"

    def test_uninstall_calls_schtasks_delete(self, tmp_path, calls):
        au.uninstall(home=tmp_path)
        assert ["schtasks", "/Delete", "/TN", au.TASK_NAME, "/F"] in calls

    def test_status_queries_task(self, tmp_path, calls):
        r = au.status(home=tmp_path)
        assert calls[-1][:2] == ["schtasks", "/Query"]
        assert r["installed"] == "True"  # mock rc=0 → 已安装


# ── 守护进程 Windows 兼容(SIGHUP 守卫)──


class TestDaemonWindowsCompat:
    def test_daemon_init_survives_missing_sighup(self, monkeypatch):
        """Windows 无 SIGHUP/siginterrupt——守卫后 __init__ 不再崩。"""
        monkeypatch.delattr(signal, "SIGHUP", raising=False)
        monkeypatch.delattr(signal, "siginterrupt", raising=False)
        from daemon.galaxy_daemon import GalaxyDaemon

        d = GalaxyDaemon()  # 此前在这里 AttributeError
        assert d.state is not None
