"""daemon/autostart.py — 开机自启(唯一属主)
==================================================

把【现有守护进程 galaxy_daemon.py】注册为开机自启,三平台同一入口:

- Windows: 计划任务(schtasks ONLOGON,优先 pythonw.exe 无黑窗)
- Linux:   systemd 用户单元 ~/.config/systemd/user/galaxy-daemon.service
- macOS:   LaunchAgent ~/Library/LaunchAgents/com.galaxy.daemon.plist

守护进程自身已带 24/7 监督(拉起 unified_launcher + 健康/硬件监控,崩溃自动重启),
所以系统层只负责"开机把守护进程带起来",不重复做保活(Restart=on-failure 仅兜
守护进程本体崩溃)。

用法(经 galaxy_daemon CLI)::

    python daemon/galaxy_daemon.py --install-autostart     # 注册开机自启
    python daemon/galaxy_daemon.py --uninstall-autostart   # 取消
    python daemon/galaxy_daemon.py --autostart-status      # 查看

纯逻辑与系统调用分离:内容生成为纯函数(可单测),落地经 _run()(测试可 mock)。
"""
from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("Galaxy.Autostart")

REPO_ROOT = Path(__file__).resolve().parent.parent
DAEMON_SCRIPT = REPO_ROOT / "daemon" / "galaxy_daemon.py"
DAEMON_CONFIG = REPO_ROOT / "daemon" / "config.json"

TASK_NAME = "GalaxyDaemon"                       # Windows 计划任务名
UNIT_NAME = "galaxy-daemon.service"              # systemd 用户单元名
PLIST_LABEL = "com.galaxy.daemon"                # macOS LaunchAgent 标签


def detect_platform() -> str:
    """windows / macos / linux。"""
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def _python_executable(prefer_windowless: bool = True) -> str:
    """守护进程用的 Python 解释器。

    Windows 上优先 pythonw.exe(无控制台黑窗,开机静默);找不到退回 python.exe。
    """
    exe = sys.executable or "python"
    if detect_platform() == "windows" and prefer_windowless:
        cand = Path(exe).with_name("pythonw.exe")
        if cand.exists():
            return str(cand)
    return exe


def daemon_command() -> List[str]:
    """开机要执行的完整命令(基于现有守护进程,不另起炉灶)。"""
    return [
        _python_executable(),
        str(DAEMON_SCRIPT),
        "--config",
        str(DAEMON_CONFIG),
    ]


# ── 内容生成(纯函数,单测覆盖)──────────────────────────────────────────────────

def systemd_unit_content() -> str:
    cmd = " ".join(_quote(c) for c in daemon_command())
    return f"""[Unit]
Description=Galaxy 24/7 Daemon (desktop AI supervisor)
After=network-online.target graphical-session.target

[Service]
Type=simple
WorkingDirectory={REPO_ROOT}
ExecStart={cmd}
# 守护进程自带 24/7 监督与子进程重启;这里只兜它本体崩溃。
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
"""


def launchd_plist_content() -> str:
    args = "\n".join(f"        <string>{c}</string>" for c in daemon_command())
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{PLIST_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
{args}
    </array>
    <key>WorkingDirectory</key>
    <string>{REPO_ROOT}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
</dict>
</plist>
"""


def schtasks_create_command() -> List[str]:
    """Windows 计划任务:用户登录时启动守护进程(工作目录经 cmd /c cd 保证)。"""
    inner = " ".join(_quote(c) for c in daemon_command())
    # schtasks 不支持设工作目录 → 经 cmd /c 先 cd 到仓库根,守护进程内的相对
    # 路径(main.py / .env 等)才解析正确。
    tr = f'cmd /c "cd /d {_quote(str(REPO_ROOT))} && {inner}"'
    return [
        "schtasks", "/Create",
        "/TN", TASK_NAME,
        "/SC", "ONLOGON",
        "/TR", tr,
        "/RL", "LIMITED",
        "/F",
    ]


def _quote(s: str) -> str:
    return f'"{s}"' if " " in s and not s.startswith('"') else s


def systemd_unit_path(home: Optional[Path] = None) -> Path:
    return (home or Path.home()) / ".config" / "systemd" / "user" / UNIT_NAME


def launchd_plist_path(home: Optional[Path] = None) -> Path:
    return (home or Path.home()) / "Library" / "LaunchAgents" / f"{PLIST_LABEL}.plist"


# ── 落地(系统调用集中经 _run,测试可 mock)────────────────────────────────────

def _run(cmd: List[str]) -> Tuple[int, str]:
    """跑一条系统命令,返回 (returncode, 合并输出)。绝不抛。"""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        out = (p.stdout or "") + (p.stderr or "")
        return p.returncode, out.strip()
    except Exception as exc:  # noqa: BLE001
        return 1, str(exc)


def install(home: Optional[Path] = None) -> Dict[str, str]:
    """注册开机自启(幂等:重复安装即覆盖更新)。返回 {platform, method, detail}。"""
    plat = detect_platform()
    if plat == "windows":
        rc, out = _run(schtasks_create_command())
        ok = rc == 0
        return {
            "platform": plat, "method": f"schtasks ONLOGON ({TASK_NAME})",
            "ok": str(ok), "detail": out[:300],
        }
    if plat == "macos":
        path = launchd_plist_path(home)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(launchd_plist_content(), encoding="utf-8")
        rc, out = _run(["launchctl", "load", "-w", str(path)])
        return {
            "platform": plat, "method": f"LaunchAgent ({path})",
            "ok": str(rc == 0), "detail": out[:300],
        }
    # linux
    path = systemd_unit_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(systemd_unit_content(), encoding="utf-8")
    _run(["systemctl", "--user", "daemon-reload"])
    rc, out = _run(["systemctl", "--user", "enable", UNIT_NAME])
    return {
        "platform": plat, "method": f"systemd user unit ({path})",
        "ok": str(rc == 0),
        "detail": (out[:250] + " | 提示: 无图形会话的机器需 `loginctl enable-linger $USER`"),
    }


def uninstall(home: Optional[Path] = None) -> Dict[str, str]:
    """取消开机自启(幂等:未安装时也安全)。"""
    plat = detect_platform()
    if plat == "windows":
        rc, out = _run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"])
        return {"platform": plat, "ok": str(rc == 0), "detail": out[:300]}
    if plat == "macos":
        path = launchd_plist_path(home)
        detail = ""
        if path.exists():
            _, detail = _run(["launchctl", "unload", "-w", str(path)])
            try:
                path.unlink()
            except OSError as exc:
                detail += f" | unlink: {exc}"
        return {"platform": plat, "ok": str(not path.exists()), "detail": detail[:300]}
    path = systemd_unit_path(home)
    _run(["systemctl", "--user", "disable", UNIT_NAME])
    detail = ""
    if path.exists():
        try:
            path.unlink()
        except OSError as exc:
            detail = f"unlink: {exc}"
    _run(["systemctl", "--user", "daemon-reload"])
    return {"platform": plat, "ok": str(not path.exists()), "detail": detail[:300]}


def status(home: Optional[Path] = None) -> Dict[str, str]:
    """当前开机自启状态。"""
    plat = detect_platform()
    if plat == "windows":
        rc, out = _run(["schtasks", "/Query", "/TN", TASK_NAME])
        return {"platform": plat, "installed": str(rc == 0), "detail": out[:300]}
    if plat == "macos":
        path = launchd_plist_path(home)
        return {"platform": plat, "installed": str(path.exists()), "detail": str(path)}
    path = systemd_unit_path(home)
    rc, out = _run(["systemctl", "--user", "is-enabled", UNIT_NAME])
    return {
        "platform": plat,
        "installed": str(path.exists() and rc == 0),
        "detail": f"{path} | is-enabled: {out[:100]}",
    }
