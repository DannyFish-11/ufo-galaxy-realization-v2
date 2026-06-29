"""
windows_service.tray_icon -- Galaxy System Tray
===============================================

- 托盘图标为彩色渐变球，色调与 Galaxy ASCII 启动横幅一致；
  warning/error/offline 时在右下角叠加状态色圆点（黄/红/灰）
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
    from PIL import Image, ImageDraw, ImageFont, ImageFilter

    import pystray

    _HAVE_TRAY = True
except ImportError:
    logger.warning("pystray or Pillow not installed; system tray unavailable")


# ---------------------------------------------------------------------------
# 图标生成
# ---------------------------------------------------------------------------

# 状态指示圆点颜色 (R, G, B) —— 仅在非 running 状态时叠加到渐变球右下角
_STATUS_COLORS = {
    "running": (0, 200, 100),    # 鲜绿 — 正常运行
    "warning": (255, 200, 0),    # 琥珀黄 — 警告/降级
    "error": (255, 60, 60),      # 红色 — 错误/停止
    "offline": (128, 128, 128),  # 灰色 — 离线
}

# Galaxy ASCII 横幅渐变锚点（极光青 → 科技蓝 → 靛蓝 → 霓虹紫 → 赛博粉）。
# 与 core/ascii_art.py 的 _ANCHOR_COLORS 保持一致；优先复用其 _interp_rgb 作为
# 单一真相来源，导入失败时用此本地副本兜底，保证托盘渐变与横幅色调精确一致。
_BANNER_ANCHORS = [
    (  0, 225, 253),  # aurora cyan
    ( 41, 156, 255),  # tech blue
    (109,  92, 255),  # indigo
    (184,  61, 245),  # neon purple
    (255,  46, 147),  # cyber pink
]


def _banner_gradient_rgb(t: float) -> tuple:
    """返回横幅渐变在位置 t∈[0,1] 处的 RGB（左→右与启动横幅一致）。

    优先复用 core.ascii_art._interp_rgb（单一真相来源），导入失败时本地插值。
    """
    try:
        from core.ascii_art import _interp_rgb
        return _interp_rgb(t)
    except Exception:
        anchors = _BANNER_ANCHORS
        n = len(anchors) - 1
        scaled = max(0.0, min(1.0, t)) * n
        i = int(scaled)
        if i >= n:
            return anchors[-1]
        frac = scaled - i
        r1, g1, b1 = anchors[i]
        r2, g2, b2 = anchors[i + 1]
        return (
            int(r1 + (r2 - r1) * frac),
            int(g1 + (g2 - g1) * frac),
            int(b1 + (b2 - b1) * frac),
        )

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
    """为系统托盘生成彩色渐变图标。

    绘制一个左→右多彩渐变的发光球体，色调与 Galaxy ASCII 启动横幅完全一致
    （极光青 → 科技蓝 → 靛蓝 → 霓虹紫 → 赛博粉）。正常运行时是一颗干净的
    渐变球；warning/error/offline 时在右下角叠加一个状态色圆点用于区分。
    4x 超采样后缩回以求平滑。
    """
    if not _HAVE_TRAY:
        return None

    S = max(width, height) * 4
    cx = cy = S // 2
    R = int(S * 0.40)

    # 1) 左→右横幅渐变：先做 1px 高的渐变条，再拉伸成正方形（与横幅同向同色）。
    row = Image.new("RGBA", (S, 1))
    rpx = row.load()
    for x in range(S):
        r, g, b = _banner_gradient_rgb(x / (S - 1))
        rpx[x, 0] = (r, g, b, 255)
    grad = row.resize((S, S), Image.LANCZOS)

    # 2) 圆形遮罩 → 渐变球
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).ellipse([cx - R, cy - R, cx + R, cy + R], fill=255)
    orb = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    orb.paste(grad, (0, 0), mask)

    # 3) 外发光：用球体自身的模糊副本作柔光晕，颜色天然跟随渐变
    canvas = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    glow = orb.filter(ImageFilter.GaussianBlur(S * 0.075))
    canvas = Image.alpha_composite(canvas, glow)
    canvas = Image.alpha_composite(canvas, orb)

    # 4) 体积高光（左上偏移柔光），裁剪到球体内
    hr = int(R * 0.52)
    hx, hy = cx - int(R * 0.30), cy - int(R * 0.32)
    highlight = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(highlight).ellipse(
        [hx - hr, hy - hr, hx + hr, hy + hr], fill=(255, 255, 255, 95)
    )
    highlight = highlight.filter(ImageFilter.GaussianBlur(S * 0.05))
    hclip = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    hclip.paste(highlight, (0, 0), mask)
    canvas = Image.alpha_composite(canvas, hclip)

    # 5) 状态圆点（仅非 running 状态）：右下角，带白色描边以保证对比度
    if status != "running":
        pip = _STATUS_COLORS.get(status, (128, 128, 128))
        pr = int(S * 0.135)
        px = cx + int(R * 0.66)
        py = cy + int(R * 0.66)
        pd = ImageDraw.Draw(canvas)
        ring = int(pr * 0.28)
        pd.ellipse(
            [px - pr - ring, py - pr - ring, px + pr + ring, py + pr + ring],
            fill=(255, 255, 255, 235),
        )
        pd.ellipse([px - pr, py - pr, px + pr, py + pr], fill=(pip[0], pip[1], pip[2], 255))

    return canvas.resize((width, height), Image.LANCZOS)


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

    @staticmethod
    def _post_ipc(path: str, timeout: float = 1.0) -> bool:
        """向 Electron 主进程的 IPC HTTP 端点 POST（用于托盘可靠地控制 UI）。

        端口与 main.js / core.lumiv_websocket_bridge 一致：GALAXY_IPC_PORT 默认 9231。
        成功返回 True；Electron 未运行（连接被拒）返回 False。
        """
        import urllib.request
        port = os.environ.get("GALAXY_IPC_PORT", "9231")
        url = f"http://127.0.0.1:{port}{path}"
        try:
            req = urllib.request.Request(url, data=b"{}", method="POST",
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.getcode() == 200
        except Exception:
            return False

    def _open_gui(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        """打开 Galaxy 控制面板。

        优先通过 IPC 让【正在运行的】Electron 打开/切换面板窗口 —— 这条路径不依赖
        全局快捷键（F12 常被输入法/开发者工具占用），是「面板打不开」时最可靠的入口。
        若 Electron 未运行（IPC 连接被拒），回退为 npm start 拉起桌面层。
        """
        # 1) 首选：IPC 直接打开面板（Electron 在跑）
        if self._post_ipc("/ipc/toggle-panel"):
            logger.info("Panel toggled via IPC")
            return

        # 2) 回退：Electron 未运行 → 拉起桌面层
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        electron_dir = os.path.join(project_root, "electron")
        if not os.path.isdir(electron_dir):
            logger.error("Electron GUI directory not found: %s", electron_dir)
            self._show_notification("GUI Not Found", f"Electron directory missing:\n{electron_dir}")
            return
        try:
            if sys.platform == "win32":
                subprocess.Popen(["npm", "start"], cwd=electron_dir, shell=True,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                subprocess.Popen(["npm", "start"], cwd=electron_dir)
            logger.info("Electron GUI launched from %s", electron_dir)
        except Exception as exc:
            logger.error("Failed to launch GUI: %s", exc)

    def _wake_overlay(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        """通过 IPC 唤醒三态覆盖层（不依赖快捷键）。

        走 /ipc/wake（始终【显示】，幂等不隐藏），保证点「Wake Overlay」一定看得见，
        不会因 toggle 把已显示的外壳反而藏起来。
        """
        if self._post_ipc("/ipc/wake"):
            logger.info("Overlay shown via IPC (/ipc/wake)")
        else:
            self._show_notification("Galaxy", "覆盖层未就绪（Electron 可能未运行）")

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

    def _open_overlay_log(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        """直接打开三态覆盖层(Electron)的日志文件 logs/electron.log。

        覆盖层「打不开/三态不显示」的报错都写在这里（GPU 崩溃、WebGL 初始化失败、
        did-fail-load、渲染层 console 等）。单独开一栏，方便用户一眼定位、排查。
        日志不存在时（覆盖层还没跑过）先建一个带说明的占位文件，保证点开总有东西看。
        """
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        log_path = os.path.join(project_root, "logs", "electron.log")
        try:
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            if not os.path.exists(log_path):
                with open(log_path, "w", encoding="utf-8") as f:
                    f.write(
                        "（暂无三态覆盖层日志）\n"
                        "Electron 覆盖层尚未启动或还没产生输出。\n"
                        "运行 `python main.py` 拉起桌面层后，覆盖层的崩溃/WebGL/加载报错会写到这里。\n"
                    )
            if sys.platform == "win32":
                os.startfile(log_path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", log_path])
            else:
                subprocess.Popen(["xdg-open", log_path])
            logger.info("Opened overlay log: %s", log_path)
        except Exception as exc:
            logger.error("Failed to open overlay log: %s", exc)
            self._show_notification(
                "三态动画日志", f"无法打开日志：{log_path}\n{exc}"
            )

    def _toggle_remote_desktop(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        """开/关【兜底远程桌面(VNC)】——人类手动接管通道,仅 Tailscale 私网内、默认关。

        AI 自动操控为主;这是你想亲自看/控那台电脑时的兜底。点一下切换开关,并弹出
        连接地址(vnc://<tailscale_ip>:5900)。需先连上 Tailscale + 装好 VNC 服务端
        (或设 GALAXY_VNC_CMD)。
        """
        try:
            from core.remote_desktop import get_remote_desktop_manager
            mgr = get_remote_desktop_manager()
            if mgr.is_running():
                mgr.disable()
                self._show_notification("远程桌面(兜底)", "已关闭。")
            else:
                res = mgr.enable()
                if res.get("success"):
                    addr = res.get("address") or "(地址未知)"
                    self._show_notification("远程桌面(兜底)已开启", f"在 Tailscale 内用 VNC 连:\n{addr}")
                else:
                    self._show_notification("远程桌面(兜底)开启失败", str(res.get("error", "未知错误")))
        except Exception as exc:
            logger.error("Toggle remote desktop failed: %s", exc)
            self._show_notification("远程桌面(兜底)", f"操作失败：{exc}")

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
            pystray.MenuItem("Show Panel (F12)", self._open_gui, default=True),
            pystray.MenuItem("Wake Overlay (Ctrl+Alt+Space)", self._wake_overlay),
            pystray.MenuItem("三态动画日志 (Overlay Log)", self._open_overlay_log),
            pystray.MenuItem("Config Panel", self._open_config),
            pystray.MenuItem("View Logs", self._open_logs),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("远程桌面接管 (VNC 兜底, 开/关)", self._toggle_remote_desktop),
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
