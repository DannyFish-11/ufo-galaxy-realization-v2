"""开机(登录)后自己连上主脑 —— 不然每次重启都得有人再敲一遍命令。

三个系统各用最常见、**不需要管理员权限**的做法:

* Windows:「启动」文件夹里放一个 .cmd(登录后以当前用户运行,最小化)。
* Linux:XDG 自启动项 ``~/.config/autostart/*.desktop`` —— 在图形会话里启动,
  才有 DISPLAY,xdotool 才能动别的窗口(systemd 用户服务拿不到会话环境)。
* macOS:LaunchAgent ``~/Library/LaunchAgents/*.plist``(RunAtLoad + KeepAlive)。

只写启动项,不改系统别处;``uninstall`` 删掉写过的那一个文件。
"""

from __future__ import annotations

import os
import shlex
import sys
from typing import Dict, Optional
from xml.sax.saxutils import escape

LABEL = "ai.galaxy.device-client"


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def entry_path(platform_name: str, home: Optional[str] = None, appdata: Optional[str] = None) -> str:
    home = home or os.path.expanduser("~")
    if platform_name == "windows":
        base = appdata or os.environ.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
        return os.path.join(base, "Microsoft", "Windows", "Start Menu", "Programs", "Startup", "GalaxyDeviceClient.cmd")
    if platform_name == "macos":
        return os.path.join(home, "Library", "LaunchAgents", f"{LABEL}.plist")
    return os.path.join(home, ".config", "autostart", "galaxy-device-client.desktop")


def entry_content(platform_name: str, python: Optional[str] = None, repo: Optional[str] = None) -> str:
    python = python or sys.executable
    repo = repo or _repo_root()
    if platform_name == "windows":
        pyw = python[:-10] + "pythonw.exe" if python.lower().endswith("python.exe") else python
        return f'@echo off\r\ncd /d "{repo}"\r\nstart "" /min "{pyw}" -m device_client\r\n'
    if platform_name == "macos":
        log = os.path.join(os.path.expanduser("~"), "Library", "Logs", "galaxy-device-client.log")
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0"><dict>\n'
            f"  <key>Label</key><string>{LABEL}</string>\n"
            "  <key>ProgramArguments</key><array>"
            f"<string>{escape(python)}</string><string>-m</string><string>device_client</string></array>\n"
            f"  <key>WorkingDirectory</key><string>{escape(repo)}</string>\n"
            "  <key>RunAtLoad</key><true/>\n"
            "  <key>KeepAlive</key><true/>\n"
            f"  <key>StandardOutPath</key><string>{escape(log)}</string>\n"
            f"  <key>StandardErrorPath</key><string>{escape(log)}</string>\n"
            "</dict></plist>\n"
        )
    exec_line = f"sh -c {shlex.quote(f'cd {shlex.quote(repo)} && exec {shlex.quote(python)} -m device_client')}"
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Galaxy Device Client\n"
        "Comment=把这台电脑接到主脑上\n"
        f"Exec={exec_line}\n"
        "X-GNOME-Autostart-enabled=true\n"
        "NoDisplay=true\n"
    )


def install(platform_name: str, **kw: str) -> Dict[str, str]:
    path = entry_path(platform_name, kw.get("home"), kw.get("appdata"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(entry_content(platform_name, kw.get("python"), kw.get("repo")))
    when = {"windows": "下次登录 Windows 时", "macos": "下次登录时(或现在执行 launchctl load " + path + ")"}.get(
        platform_name, "下次登录桌面时"
    )
    return {"path": path, "starts": when}


def uninstall(platform_name: str, **kw: str) -> Dict[str, str]:
    path = entry_path(platform_name, kw.get("home"), kw.get("appdata"))
    existed = os.path.exists(path)
    if existed:
        os.remove(path)
    return {"path": path, "removed": str(existed)}
