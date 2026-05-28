"""
windows_service.tray_icon -- Galaxy System Tray
===============================================

- 托盘图标显示运行状态（绿色=运行中 / 黄色=警告 / 红色=错误）
- 右键菜单：显示GUI / 配置 / 重启 / 退出
- 双击显示主 GUI
- 启动时自动检查 Galaxy 服务状态

依赖::

    pip install pystray Pillow

Usage::

    # 独立启动托盘
    python -m windows_service.tray_icon

    # 或作为 Galaxy 的一部分启动
    from windows_service.tray_icon import create_tray, start_tray_in_thread
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
import webbrowser
from typing import Callable

logger = logging.getLogger("Galaxy.Tray")

# ---------------------------------------------------------------------------
# 可选依赖 —— pystray 和 Pillow
# ---------------------------------------------------------------------------

_HAVE_TRAY = False
try:
    from PIL import Image, ImageDraw, ImageFont

    import pystray

    _HAVE_TRAY = True
except ImportError:
    logger.warning("pystray or Pillow not installed; system tray unavailable")


# ---------------------------------------------------------------------------
# 图标生成
# ---------------------------------------------------------------------------

# 状态 -> 颜色映射 (R, G, B)
_STATUS_COLORS = {
    "running": (0, 200, 100),    # 鲜绿 — 正常运行
    "warning": (255, 200, 0),    # 琥珀黄 — 警告/降级
    "error": (255, 60, 60),      # 红色 — 错误/停止
    "offline": (128, 128, 128),  # 灰色 — 离线
}

# 状态 -> 提示文本
_STATUS_TOOLTIPS = {
    "running": "Galaxy V2 AI -- Running",
    "warning": "Galaxy V2 AI -- Degraded",
    "error": "Galaxy V2 AI -- Error",
    "offline": "Galaxy V2 AI -- Offline",
}


def create_icon_image(
    status: str = "running",
    width: int = 64,
    height: int = 64,
) -> Image.Image | None:
    """为系统托盘生成状态图标。

    绘制一个带有内部发光高光和外边框的圆形，
    以呈现专业外观。
    """
    if not _HAVE_TRAY:
        return None

    color = _STATUS_COLORS.get(status, (100, 100, 100))

    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    dc = ImageDraw.Draw(image)

    # 外发光（柔和阴影）
    for i in range(3):
        alpha = 40 - i * 10
        offset = 6 - i * 2
        dc.ellipse(
            [offset, offset, width - offset, height - offset],
            fill=(color[0], color[1], color[2], alpha),
        )

    # 主圆
    margin = 4
    dc.ellipse(
        [margin, margin, width - margin, height - margin],
        fill=color,
        outline=(255, 255, 255, 180),
        width=2,
    )

    # 内部高光（模拟 3D 效果）
    highlight_margin = margin + 8
    dc.ellipse(
        [highlight_margin, highlight_margin, width // 2, height // 2],
        fill=(255, 255, 255, 60),
    )

    # 中心 "G" 文字
    try:
        font = ImageFont.truetype("segoeui.ttf", 24)
    except Exception:
        font = ImageFont.load_default()

    text = "G"
    bbox = dc.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    text_x = (width - text_w) // 2
    text_y = (height - text_h) // 2 - 2

    # 文字阴影
    dc.text((text_x + 1, text_y + 1), text, font=font, fill=(0, 0, 0, 120))
    # 文字本体
    dc.text((text_x, text_y), text, font=font, fill=(255, 255, 255, 230))

    return image


# ---------------------------------------------------------------------------
# 托盘图标构建
# ---------------------------------------------------------------------------

class GalaxyTray:
    """Galaxy V2 系统托盘控制器。

    管理 pystray 图标生命周期、菜单动作和
    状态更新。
    """

    def __init__(
        self,
        galaxy_process: subprocess.Popen[str] | None = None,
        on_status_change: Callable[[str], None] | None = None,
    ) -> None:
        self.galaxy_process = galaxy_process
        self.on_status_change = on_status_change
        self._icon: pystray.Icon | None = None
        self._current_status = "offline"
        self._status_lock = threading.Lock()

    # ── 属性 ──

    @property
    def icon(self) -> pystray.Icon | None:
        return self._icon

    # ── 状态管理 ──

    def set_status(self, status: str) -> None:
        """更新托盘图标状态（线程安全）。"""
        if status not in _STATUS_COLORS:
            status = "offline"

        with self._status_lock:
            if self._current_status == status:
                return
            self._current_status = status

        if self._icon is not None and _HAVE_TRAY:
            try:
                new_image = create_icon_image(status)
                if new_image:
                    self._icon.icon = new_image
                    self._icon.title = _STATUS_TOOLTIPS.get(status, "Galaxy V2 AI")
            except Exception as exc:
                logger.debug("Status update failed: %s", exc)

        if self.on_status_change:
            self.on_status_change(status)

    # ── 菜单动作 ──

    def _open_gui(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        """打开 Galaxy 桌面 GUI（Electron）。"""
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        electron_dir = os.path.join(project_root, "electron")

        if not os.path.isdir(electron_dir):
            logger.error("Electron GUI directory not found: %s", electron_dir)
            self._show_notification(
                "GUI Not Found",
                f"Electron directory missing:\n{electron_dir}",
            )
            return

        try:
            if sys.platform == "win32":
                subprocess.Popen(
                    ["npm", "start"],
                    cwd=electron_dir,
                    shell=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            else:
                subprocess.Popen(["npm", "start"], cwd=electron_dir)
            logger.info("Electron GUI launched from %s", electron_dir)
        except Exception as exc:
            logger.error("Failed to launch GUI: %s", exc)

    def _open_config(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        """在浏览器中打开配置面板。"""
        urls = [
            "http://localhost:16201/api-manager/",
            "http://localhost:8080/api-manager/",
            "http://127.0.0.1:16201/api-manager/",
        ]
        for url in urls:
            try:
                webbrowser.open(url, new=1, autoraise=True)
                logger.info("Opened config panel: %s", url)
                return
            except Exception:
                continue
        logger.error("Could not open any config URL")

    def _open_logs(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        """在文件资源管理器中打开日志目录。"""
        log_dir = os.path.join(os.path.expanduser("~"), ".galaxy", "logs")
        os.makedirs(log_dir, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(log_dir)  # type: ignore[attr-defined]
        else:
            webbrowser.open(f"file://{log_dir}")

    def _restart_service(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        """重启 Galaxy 服务（或子进程）。"""
        logger.info("Restart requested via tray menu")
        self.set_status("warning")

        if self.galaxy_process is not None:
            try:
                self.galaxy_process.terminate()
                self.galaxy_process.wait(timeout=10)
            except Exception:
                try:
                    self.galaxy_process.kill()
                except Exception:
                    pass
                self.galaxy_process = None

        # 如果作为 Windows 服务运行，提示用户使用服务管理器
        self._show_notification(
            "Galaxy V2 AI",
            "Service restart initiated.\nIf running as Windows service, use 'Services.msc'.",
        )
        self.set_status("running")

    def _exit_tray(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        """退出托盘（优雅关闭）。"""
        logger.info("Exit requested via tray menu")
        self._show_notification("Galaxy V2 AI", "Shutting down...")
        icon.stop()

        if self.galaxy_process is not None:
            try:
                self.galaxy_process.terminate()
                self.galaxy_process.wait(timeout=10)
            except Exception:
                try:
                    self.galaxy_process.kill()
                except Exception:
                    pass

        # 不要调用 sys.exit(0) — 这会杀死父进程
        logger.info("Tray icon stopped")

    def _show_notification(self, title: str, message: str) -> None:
        """显示气球通知（如果支持）。"""
        if self._icon and hasattr(self._icon, "notify"):
            try:
                self._icon.notify(message, title)
            except Exception:
                pass

    # ── 构建菜单 ──

    def _build_menu(self) -> pystray.Menu:
        """构建右键菜单。"""
        return pystray.Menu(
            pystray.MenuItem(
                lambda text: f"Status: {self._current_status.upper()}",
                lambda icon, item: None,
                enabled=False,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Show AI Assistant", self._open_gui),
            pystray.MenuItem("Config Panel", self._open_config),
            pystray.MenuItem("View Logs", self._open_logs),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Restart Service", self._restart_service),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", self._exit_tray),
        )

    # ── 生命周期 ──

    def create(self) -> pystray.Icon | None:
        """创建（但不启动）系统托盘图标。"""
        if not _HAVE_TRAY:
            logger.error("pystray / Pillow required for system tray")
            return None

        icon_image = create_icon_image(self._current_status)
        if icon_image is None:
            return None

        self._icon = pystray.Icon(
            name="GalaxyV2",
            icon=icon_image,
            title=_STATUS_TOOLTIPS[self._current_status],
            menu=self._build_menu(),
        )

        # 双击事件
        if hasattr(self._icon, "double_click"):
            self._icon.double_click = lambda icon: self._open_gui(icon, None)  # type: ignore[method-assign]

        return self._icon

    def run(self) -> None:
        """阻塞运行托盘图标（必须在主线程调用）。"""
        if self._icon is None:
            self.create()
        if self._icon:
            logger.info("Starting system tray icon...")
            self._icon.run()

    def run_detached(self) -> threading.Thread:
        """在后台线程中运行托盘图标并返回线程句柄。"""
        thread = threading.Thread(target=self.run, name="GalaxyTray", daemon=True)
        thread.start()
        logger.info("Tray icon started in background thread")
        return thread

    def stop(self) -> None:
        """停止托盘图标。"""
        if self._icon:
            self._icon.stop()
            self._icon = None


# ---------------------------------------------------------------------------
# 便捷函数
# ---------------------------------------------------------------------------


def create_tray(
    galaxy_process: subprocess.Popen[str] | None = None,
    on_status_change: Callable[[str], None] | None = None,
) -> GalaxyTray | None:
    """工厂函数 —— 创建 GalaxyTray 实例并初始化图标。

    参数:
        galaxy_process: 可选的 Galaxy 子进程引用，用于重启/终止
        on_status_change: 状态变化时的可选回调

    返回:
        已配置好但尚未运行的 GalaxyTray 实例，或者如果 pystray
        不可用则返回 None
    """
    if not _HAVE_TRAY:
        logger.warning("System tray unavailable (pystray / Pillow not installed)")
        return None

    tray = GalaxyTray(
        galaxy_process=galaxy_process,
        on_status_change=on_status_change,
    )
    tray.create()
    return tray


def start_tray_in_thread(
    galaxy_process: subprocess.Popen[str] | None = None,
    on_status_change: Callable[[str], None] | None = None,
) -> GalaxyTray | None:
    """一键启动 —— 在后台线程中创建并启动托盘。

    返回:
        GalaxyTray 实例，如果不可用则返回 None。
        调用者可通过 tray.set_status("running|warning|error|offline") 更新状态
    """
    tray = create_tray(galaxy_process, on_status_change)
    if tray is None:
        return None

    tray.run_detached()
    time.sleep(0.5)  # 让图标有时间出现
    tray.set_status("running")
    return tray


# ---------------------------------------------------------------------------
# 独立入口点
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    if not _HAVE_TRAY:
        print("ERROR: pystray and Pillow are required.")
        print("Install with:  pip install pystray Pillow")
        sys.exit(1)

    tray = create_tray()
    if tray:
        tray.set_status("running")
        print("Galaxy V2 system tray is running. Right-click the icon for menu.")
        tray.run()
    else:
        print("Failed to create tray icon")
        sys.exit(1)
