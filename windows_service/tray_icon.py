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
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Callable

logger = logging.getLogger("Galaxy.Tray")


# ---------------------------------------------------------------------------
# 统一日志根 / 崩溃专区路径
# ---------------------------------------------------------------------------
# 托盘可能在未把项目根加入 sys.path 的环境下被单独拉起(windows_service 场景),
# 故用带回退的薄封装:能导入 core.log_paths 就用唯一事实来源,导不到也不让
# 日志入口失效(回退到与其默认值一致的 <项目根>/logs)。
def _log_root() -> Path:
    """统一日志根目录(唯一事实来源:core.log_paths.log_root)。"""
    try:
        from core.log_paths import log_root

        return log_root()
    except Exception:  # noqa: BLE001 — 托盘入口不能因导入失败而不可用
        fallback = Path(__file__).resolve().parent.parent / "logs"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def _crash_latest_path() -> Path:
    """崩溃聚合视图路径(与 core.log_paths.crash_latest_path 一致)。"""
    try:
        from core.log_paths import crash_latest_path

        return crash_latest_path()
    except Exception:  # noqa: BLE001
        d = _log_root() / "crashes"
        d.mkdir(parents=True, exist_ok=True)
        return d / "latest.log"


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
    "running": (0, 200, 100),  # 鲜绿 — 正常运行
    "warning": (255, 200, 0),  # 琥珀黄 — 警告/降级
    "error": (255, 60, 60),  # 红色 — 错误/停止
    "offline": (128, 128, 128),  # 灰色 — 离线
}

# Galaxy ASCII 横幅渐变锚点（极光青 → 科技蓝 → 靛蓝 → 霓虹紫 → 赛博粉）。
# 与 core/ascii_art.py 的 _ANCHOR_COLORS 保持一致；优先复用其 _interp_rgb 作为
# 单一真相来源，导入失败时用此本地副本兜底，保证托盘渐变与横幅色调精确一致。
_BANNER_ANCHORS = [
    (0, 225, 253),  # aurora cyan
    (41, 156, 255),  # tech blue
    (109, 92, 255),  # indigo
    (184, 61, 245),  # neon purple
    (255, 46, 147),  # cyber pink
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


# 定稿品牌图标（分形星云环 seed-19）——托盘图标的【单一真相来源】，
# 与应用/窗口/通知图标像素一致。托盘不再自绘一颗球，而是加载这张定稿图，
# 只在其上叠加状态圆点。文件缺失时才回退到本地自绘（诚实降级，不静默）。
_REPO_ROOT = Path(__file__).resolve().parent.parent
_BRAND_ICON_CANDIDATES = (
    _REPO_ROOT / "electron" / "assets" / "icon-256.png",  # 高分辨率，缩放质量最好
    _REPO_ROOT / "electron" / "assets" / "tray-64.png",  # 托盘专用尺寸兜底
    _REPO_ROOT / "electron" / "assets" / "icon.png",
)


def _load_brand_icon() -> "Image.Image | None":
    """加载定稿星云品牌图（RGBA）。全部候选都不可用时返回 None → 触发自绘兜底。"""
    for path in _BRAND_ICON_CANDIDATES:
        try:
            if path.exists():
                return Image.open(path).convert("RGBA")
        except Exception as exc:  # 损坏/不可读 —— 记一笔再试下一候选
            logger.warning("品牌图标加载失败 %s: %s", path.name, exc)
    return None


def _overlay_status_pip(canvas: "Image.Image", status: str, S: int) -> None:
    """在 SxS 画布右下角叠加状态色圆点（仅非 running）；带白色描边保证对比度。"""
    if status == "running":
        return
    pip = _STATUS_COLORS.get(status, (128, 128, 128))
    R = int(S * 0.40)
    cx = cy = S // 2
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


def _draw_orb_fallback(status: str, S: int) -> "Image.Image":
    """兜底自绘：定稿星云图缺失时用的横幅渐变球（原实现，去掉白色高光）。"""
    cx = cy = S // 2
    R = int(S * 0.40)

    row = Image.new("RGBA", (S, 1))
    rpx = row.load()
    for x in range(S):
        r, g, b = _banner_gradient_rgb(x / (S - 1))
        rpx[x, 0] = (r, g, b, 255)
    grad = row.resize((S, S), Image.LANCZOS)

    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).ellipse([cx - R, cy - R, cx + R, cy + R], fill=255)
    orb = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    orb.paste(grad, (0, 0), mask)

    canvas = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    glow = orb.filter(ImageFilter.GaussianBlur(S * 0.075))
    canvas = Image.alpha_composite(canvas, glow)
    canvas = Image.alpha_composite(canvas, orb)
    return canvas


def create_icon_image(
    status: str = "running",
    width: int = 64,
    height: int = 64,
) -> Image.Image | None:
    """为系统托盘生成图标 —— 优先用定稿星云品牌图，缺失时自绘兜底。

    托盘图标此前是运行时自绘的一颗渐变球，和应用/窗口图标（分形星云环）不一致，
    也带着已被否决的白色高光。现在加载定稿 electron/assets/icon-256.png，保证托盘与
    其它所有位置像素一致；warning/error/offline 时在右下角叠加状态色圆点。4x 超采样。
    """
    if not _HAVE_TRAY:
        return None

    S = max(width, height) * 4

    brand = _load_brand_icon()
    if brand is not None:
        canvas = brand.resize((S, S), Image.LANCZOS)
    else:
        logger.warning("定稿星云图标不可用，托盘回退到自绘渐变球")
        canvas = _draw_orb_fallback(status, S)

    _overlay_status_pip(canvas, status, S)
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
            req = urllib.request.Request(url, data=b"{}", method="POST", headers={"Content-Type": "application/json"})
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

        # 2) 回退:Electron 未运行 → 依赖完整才尝试拉起;否则直接开 Web 面板。
        #    此前依赖残缺时 npm start 静默失败(CREATE_NO_WINDOW、无任何提示),
        #    用户感受就是"托盘点了没反应"。后端面板本身一直可用,浏览器兜底。
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        electron_dir = os.path.join(project_root, "electron")

        electron_ready = os.path.isdir(electron_dir)
        if electron_ready:
            try:
                sys.path.insert(0, project_root)
                from core.electron_launch_guard import electron_package_intact

                electron_ready = electron_package_intact(electron_dir)
            except Exception:
                electron_ready = os.path.isdir(os.path.join(electron_dir, "node_modules"))

        if electron_ready:
            try:
                if sys.platform == "win32":
                    # B8: 原为 Popen(["npm","start"], shell=True)。argv 列表配
                    # shell=True 在 Windows 上语义混乱 —— Python 会把列表拼成命令串
                    # 再交给 cmd.exe 解释，路径含空格时的引用规则由 cmd 决定，
                    # 且平白引入一层 shell 解析。
                    #
                    # 之所以当初要 shell=True：npm 在 Windows 上是 npm.cmd（批处理），
                    # CreateProcess 不能直接执行 .cmd。正确做法是显式解析出可执行文件，
                    # 而不是把整串丢给 shell。
                    npm = shutil.which("npm.cmd") or shutil.which("npm")
                    if not npm:
                        raise FileNotFoundError("未在 PATH 中找到 npm/npm.cmd")
                    subprocess.Popen(
                        [npm, "start"], cwd=electron_dir, creationflags=subprocess.CREATE_NO_WINDOW
                    )
                else:
                    npm = shutil.which("npm")
                    if not npm:
                        raise FileNotFoundError("未在 PATH 中找到 npm")
                    subprocess.Popen([npm, "start"], cwd=electron_dir)
                logger.info("Electron GUI launched from %s", electron_dir)
                return
            except Exception as exc:
                logger.error("Failed to launch GUI: %s", exc)

        # 3) 最终兜底:桌面壳不可用 → 浏览器打开 Web 面板(后端始终在跑)。
        # 注:网关根路径 / 没有注册任何路由(裸打开是 404),指向真实存在的
        # 运维台页面。
        port = os.environ.get("GALAXY_GATEWAY_PORT", "") or os.environ.get("GALAXY_PORT", "") or "9000"
        panel_url = f"http://localhost:{port}/operator-console"
        try:
            webbrowser.open(panel_url, new=1, autoraise=True)
            self._show_notification(
                "Galaxy",
                "桌面壳未就绪(electron 依赖未装好),已用浏览器打开面板。\n" "修复:在 electron/ 目录执行 npm install。",
            )
            logger.info("Desktop shell unavailable — opened web panel %s", panel_url)
        except Exception as exc:
            logger.error("Failed to open web panel fallback: %s", exc)

    def _wake_overlay(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        """通过 IPC 唤醒三态覆盖层（不依赖快捷键）。

        走 /ipc/wake（始终【显示】，幂等不隐藏），保证点「Wake Overlay」一定看得见，
        不会因 toggle 把已显示的外壳反而藏起来。
        """
        if self._post_ipc("/ipc/wake"):
            logger.info("Overlay shown via IPC (/ipc/wake)")
        else:
            self._show_notification("Galaxy", "覆盖层未就绪（Electron 可能未运行）")

    def _hide_overlay(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        """通过 IPC 隐藏三态覆盖层（不依赖快捷键）。

        补齐"放下"的托盘兜底——此前托盘只有 Wake(显示)一个入口,没有对应的隐藏
        菜单项;若 Ctrl+Alt+H 等隐藏快捷键在用户机器上被占用而注册失败,唤醒后的
        覆盖层就完全没有办法收起去。走 /ipc/hide-overlay(始终【隐藏】,幂等不显示)。
        """
        if self._post_ipc("/ipc/hide-overlay"):
            logger.info("Overlay hidden via IPC (/ipc/hide-overlay)")
        else:
            self._show_notification("Galaxy", "覆盖层未就绪（Electron 可能未运行）")

    def _open_config(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        """在浏览器中打开配置面板。

        修复:此前硬编码 16201/8080 两个端口 —— 网关从来不在那里(统一口 9000),
        每个链接都指向无人监听的地址。按标准端口解析链取真实网关口。
        """
        port = os.environ.get("GALAXY_GATEWAY_PORT", "") or os.environ.get("GALAXY_PORT", "") or "9000"
        urls = [
            f"http://localhost:{port}/api-manager",
            f"http://127.0.0.1:{port}/api-manager",
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
        """在文件资源管理器中打开【统一日志根目录】。

        统一前的真 bug:此处硬编码 ``~/.galaxy/logs``,而启动器/覆盖层/节点全部
        写在项目内 ``logs/`` —— 用户从托盘点进来看到的是个几乎空的目录,真正的
        日志在另一个地方,排障时白跑一趟。现改为读 :func:`core.log_paths.log_root`
        这一唯一事实来源(尊重 GALAXY_LOG_DIR),与所有写入方指向同一处。
        """
        log_dir = str(_log_root())
        os.makedirs(log_dir, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(log_dir)  # type: ignore[attr-defined]
        else:
            webbrowser.open(f"file://{log_dir}")

    def _open_crash_log(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        """【崩溃日志专区】—— 托盘单独一行,一键打开全系统崩溃聚合视图。

        统一前的痛点:崩溃分散在多个文件(覆盖层 GPU 崩溃在 electron.log、后端
        未处理异常在 lumiv.log、服务层在 windows_service.log、节点在 nodes/*.log),
        而托盘只有一个"三态动画日志"入口、只能看覆盖层那一份 —— 真机出问题时
        用户要自己挨个翻文件、还得辨认哪几行才是崩溃。

        现在:点这一行即时触发 :func:`core.crash_log_aggregator.aggregate_crashes`
        扫描统一日志根下的全部日志,把崩溃片段(traceback / fatal / GPU 崩溃 /
        WinError / 未处理异常等)跨来源去重后汇总到 ``logs/crashes/latest.log``
        并直接打开。源日志只读不改,单一入口一眼定位。
        """
        try:
            from core.crash_log_aggregator import aggregate_crashes

            log_path, count = aggregate_crashes()
            logger.info("Crash aggregation: %d block(s) -> %s", count, log_path)
        except Exception as exc:
            # 聚合失败不能让入口失效:退化为直接打开崩溃目录里已有的聚合文件,
            # 再不行就打开崩溃目录本身,保证这一行永远"点得开"。
            logger.error("Crash aggregation failed: %s", exc)
            try:
                log_path = _crash_latest_path()
                if not log_path.exists():
                    log_path.parent.mkdir(parents=True, exist_ok=True)
                    log_path.write_text(
                        "（崩溃聚合暂不可用）\n"
                        f"聚合器执行失败：{exc}\n"
                        "可直接查看同目录及上级日志根中的各源日志。\n",
                        encoding="utf-8",
                    )
            except Exception as inner:
                self._show_notification("崩溃日志", f"无法打开崩溃日志：{inner}")
                return

        try:
            target = str(log_path)
            if sys.platform == "win32":
                os.startfile(target)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", target])
            else:
                subprocess.Popen(["xdg-open", target])
            logger.info("Opened crash log: %s", target)
        except Exception as exc:
            logger.error("Failed to open crash log: %s", exc)
            self._show_notification("崩溃日志", f"无法打开崩溃日志：{log_path}\n{exc}")

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
            pystray.MenuItem("Hide Overlay (Ctrl+Alt+H)", self._hide_overlay),
            pystray.MenuItem("Config Panel", self._open_config),
            pystray.Menu.SEPARATOR,
            # ── 日志区(所有者要求:崩溃日志单独一行,统一入口)──
            # 上一行 = 崩溃专区(跨全部日志聚合去重,排障首选);
            # 下一行 = 统一日志根目录(看全部原始日志)。
            # 此前的"三态动画日志"只覆盖 Electron 一份、且与 View Logs 指向两个
            # 不同根目录,已合并进这两行,不再各开各的。
            pystray.MenuItem("💥 崩溃日志 (Crash Log)", self._open_crash_log),
            pystray.MenuItem("View Logs (统一日志目录)", self._open_logs),
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
