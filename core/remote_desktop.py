"""
core/remote_desktop.py — 远程桌面(VNC)兜底接管管理器
=====================================================

**定位**:AI 自动操控电脑为【主】通道(网关 API + UFO/UIA 自动化 + scrcpy)。本模块是
**人类手动接管的【兜底】**——你出门时想亲自看一眼 / 手动控那台跑 Galaxy 的电脑时用。

**安全边界(反"后门")**:
- 仅在你自己的 **Tailscale 私网**内可达;未连 Tailscale 时直接拒绝启用。
- **默认关闭**(``GALAXY_REMOTE_DESKTOP`` 显式开,或经鉴权 API/托盘手动开)。
- 配 ACL 白名单(见 deploy/headscale/acl.hujson 的 vnc 规则);绝不暴露公网。

**职责划分(诚实)**:Galaxy 负责【编排(开/关)+ 安全地址 + 状态呈现】;VNC 服务端本体
由你在 Windows 一次性安装(UltraVNC / TightVNC / RealVNC),或用 ``GALAXY_VNC_CMD``
显式给出启动命令(支持 ``{ip}`` / ``{port}`` 占位)。本模块不去猜各家服务端的绑定/认证
参数——那是安全隐患;把控制权交给你。

环境变量::

    GALAXY_REMOTE_DESKTOP=1     # 启动时即开启兜底(默认关)
    GALAXY_VNC_PORT=5900        # VNC 端口(默认 5900)
    GALAXY_VNC_CMD="winvnc.exe ... {ip} {port}"   # 显式启动命令(首选,最稳)
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.RemoteDesktop")


def _truthy(v: str) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes", "on")


class RemoteDesktopManager:
    """VNC 兜底接管:编排 + 安全地址 + 状态。进程内单例,线程安全,永不抛出影响主流程。"""

    _instance: Optional["RemoteDesktopManager"] = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        try:
            self.port = int(os.getenv("GALAXY_VNC_PORT", "5900") or 5900)
        except (ValueError, TypeError):
            self.port = 5900
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "RemoteDesktopManager":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ── Tailscale 地址 ────────────────────────────────────────────────────

    def _tailscale_ip(self) -> Optional[str]:
        try:
            from core.tailscale_manager import TailscaleManager

            return TailscaleManager().get_tailscale_ip() or None
        except Exception:  # noqa: BLE001
            return None

    def get_address(self) -> Optional[str]:
        """返回 Tailscale 私网内的 VNC 连接地址 ``vnc://<ts_ip>:<port>``；未连 Tailscale 则 None。"""
        ip = self._tailscale_ip()
        return f"vnc://{ip}:{self.port}" if ip else None

    # ── 服务端命令解析 ────────────────────────────────────────────────────

    def _resolve_server_cmd(self, bind_ip: str) -> Optional[List[str]]:
        """解析 VNC 服务端启动命令。优先 GALAXY_VNC_CMD(支持 {ip}/{port} 占位)，
        否则自动探测常见服务端(尽量绑定到 Tailscale 网卡)。找不到返回 None。"""
        cmd = os.getenv("GALAXY_VNC_CMD", "").strip()
        if cmd:
            import shlex

            resolved = cmd.replace("{ip}", bind_ip).replace("{port}", str(self.port))
            try:
                return shlex.split(resolved, posix=(os.name != "nt"))
            except Exception:  # noqa: BLE001
                return resolved.split()
        # x11vnc(Linux/开发环境;绑定到指定网卡)——便于真机外的链路验证。
        x11vnc = shutil.which("x11vnc")
        if x11vnc:
            args = [
                x11vnc,
                "-rfbport",
                str(self.port),
                "-localhost" if not bind_ip else "-listen",
                bind_ip,
                "-forever",
                "-shared",
                "-quiet",
                "-bg",
            ]
            # -localhost 与 -listen 互斥:有 bind_ip 用 -listen,否则 -localhost
            return (
                [x11vnc, "-rfbport", str(self.port), "-listen", bind_ip, "-forever", "-shared", "-quiet", "-bg"]
                if bind_ip
                else args
            )
        # Windows 常见服务端仅探测"是否安装"——绑定/认证参数交给 GALAXY_VNC_CMD,不擅自猜。
        return None

    def _detected_server_hint(self) -> str:
        for name in ("winvnc.exe", "winvnc", "tvnserver.exe", "tvnserver", "vncserver", "x11vnc"):
            if shutil.which(name):
                return name
        return ""

    # ── 开 / 关 / 状态 ────────────────────────────────────────────────────

    def is_running(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def enable(self) -> Dict[str, Any]:
        """启用兜底远程桌面(仅 Tailscale 在线时)。返回结果 dict,永不抛出。"""
        ip = self._tailscale_ip()
        if not ip:
            return {"success": False, "error": "未连接 Tailscale —— 兜底远程桌面只在 Tailscale 私网内可用，请先连上。"}
        if self.is_running():
            return {"success": True, "already_running": True, "address": self.get_address()}
        cmd = self._resolve_server_cmd(ip)
        if not cmd:
            hint = self._detected_server_hint()
            return {
                "success": False,
                "error": (
                    "未找到可用的 VNC 服务端。请在 Windows 安装一个(UltraVNC/TightVNC/RealVNC),"
                    "或设 GALAXY_VNC_CMD 显式指定启动命令(支持 {ip}/{port} 占位)。"
                    + (f" 检测到:{hint}(请用 GALAXY_VNC_CMD 指定其绑定 Tailscale 网卡的启动命令)。" if hint else "")
                ),
            }
        try:
            with self._lock:
                self._proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            logger.info("兜底远程桌面已启用:%s(绑定 %s:%d)", self.get_address(), ip, self.port)
            return {"success": True, "address": self.get_address(), "bind": f"{ip}:{self.port}"}
        except Exception as exc:  # noqa: BLE001
            logger.warning("启用兜底远程桌面失败:%s", exc)
            return {"success": False, "error": str(exc)}

    def disable(self) -> Dict[str, Any]:
        """关闭兜底远程桌面。"""
        with self._lock:
            proc = self._proc
            self._proc = None
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:  # noqa: BLE001
                    proc.kill()
            except Exception as exc:  # noqa: BLE001
                logger.debug("关闭远程桌面进程异常(忽略):%s", exc)
        logger.info("兜底远程桌面已关闭")
        return {"success": True}

    def status(self) -> Dict[str, Any]:
        return {
            "running": self.is_running(),
            "address": self.get_address(),
            "port": self.port,
            "tailscale_connected": self._tailscale_ip() is not None,
            "server_detected": self._detected_server_hint() or None,
            "vnc_cmd_set": bool(os.getenv("GALAXY_VNC_CMD", "").strip()),
            "note": "AI 自动操控为主;此为人类手动接管的兜底,仅 Tailscale 私网内、ACL 锁死、默认关。",
        }


def get_remote_desktop_manager() -> RemoteDesktopManager:
    return RemoteDesktopManager.get_instance()


def maybe_autostart() -> None:
    """若 GALAXY_REMOTE_DESKTOP 为真,启动时自动开启兜底(否则保持关闭)。best-effort。"""
    if _truthy(os.getenv("GALAXY_REMOTE_DESKTOP", "")):
        try:
            get_remote_desktop_manager().enable()
        except Exception as exc:  # noqa: BLE001
            logger.debug("远程桌面自动开启跳过(非致命):%s", exc)
