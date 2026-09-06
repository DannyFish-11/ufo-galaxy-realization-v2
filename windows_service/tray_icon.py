"""
windows_service.tray_icon — Galaxy 系统托盘 / Galaxy System Tray
================================================================

**这一版是重写的,不是在旧托盘上做删减。**

旧托盘的右键菜单有九项(显示面板 / 唤醒覆盖层 / 隐藏覆盖层 / 配置面板 /
崩溃日志 / 查看日志 / 远程桌面接管 / 重启服务 / 退出)。按所有者要求全部移除,
菜单**留空**,后续要放什么再放什么。

于是这个模块现在只做两件事:

1. **在托盘上显示这台机器的状态** —— 定稿星云图标,非 running 时右下角叠一颗
   状态色圆点。图标那一段原样保留:它是视觉身份,和被移除的那九个入口无关。
2. **点它打开面板** —— 左键 / 双击。这是唯一保留的功能。

菜单为空但仍要能点开面板,靠的是一个 ``visible=False`` 的默认项:pystray 用
「默认项」承接单击,而不可见项不进右键菜单。**这不是取巧** —— 没有默认项的话
单击不会触发任何回调,托盘就成了一张纯图片。

.. warning::

   菜单里**没有退出项**。这是所有者明确要求的「暂时先不要放任何东西」。
   要停掉托盘:结束 ``python main.py`` 那个进程(控制台 Ctrl+C),或由调用方拿
   ``GalaxyTray.stop()``。要把退出加回来,见 ``_build_menu`` 的注释。

对用户可见的文字一律**中英双写**(tooltip、通知),因为托盘是系统级表层,
读它的人不一定和跑它的人是同一个。

依赖 / Requires::

    pip install pystray Pillow

用法 / Usage::

    python -m windows_service.tray_icon               # 独立启动 / standalone
    from windows_service.tray_icon import start_tray_in_thread
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

logger = logging.getLogger("Galaxy.Tray")


# ---------------------------------------------------------------------------
# 可选依赖 / Optional dependencies —— pystray 与 Pillow
# ---------------------------------------------------------------------------

_HAVE_TRAY = False
try:
    from PIL import Image, ImageDraw, ImageFilter

    import pystray

    _HAVE_TRAY = True
except ImportError:
    logger.warning(
        "未安装 pystray / Pillow,系统托盘不可用 / "
        "pystray or Pillow not installed; system tray unavailable"
    )


# ---------------------------------------------------------------------------
# 图标生成 / Icon rendering
# ---------------------------------------------------------------------------

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
# 状态提示 / Status tooltips —— 中英双写
# ---------------------------------------------------------------------------

# 托盘 tooltip 是系统级表层,读它的人不一定懂中文,也不一定懂英文,所以两种都给。
_STATUS_TOOLTIPS = {
    "running": "Galaxy V2 · 运行中 / Running",
    "warning": "Galaxy V2 · 降级 / Degraded",
    "error": "Galaxy V2 · 错误 / Error",
    "offline": "Galaxy V2 · 离线 / Offline",
}

#: 单击托盘时那个不可见默认项的名字。不进菜单,但辅助技术会读到它。
_ACTIVATE_LABEL = "显示面板 / Show panel"


# ---------------------------------------------------------------------------
# 托盘控制器 / Tray controller
# ---------------------------------------------------------------------------


class GalaxyTray:
    """Galaxy V2 系统托盘控制器 / system tray controller.

    只管两件事:图标状态,和「点开面板」。菜单是空的。
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

    # ── 属性 / Properties ──

    @property
    def icon(self) -> pystray.Icon | None:
        return self._icon

    # ── 状态 / Status ──

    def set_status(self, status: str) -> None:
        """更新托盘图标状态(线程安全)/ Update tray status (thread-safe)."""
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
                    self._icon.title = _STATUS_TOOLTIPS.get(status, "Galaxy V2")
            except Exception as exc:  # noqa: BLE001 — 状态更新失败不该拖垮托盘
                logger.debug("状态更新失败 / status update failed: %s", exc)

        if self.on_status_change:
            self.on_status_change(status)

    # ── 唯一保留的动作:打开面板 / The one action that stays ──

    @staticmethod
    def _post_ipc(path: str, timeout: float = 1.0) -> bool:
        """向 Electron 主进程的 IPC 端点 POST / POST to Electron's IPC endpoint.

        端口与 main.js、core.lumiv_websocket_bridge 一致:``GALAXY_IPC_PORT``,默认 9231。
        Electron 没在跑(连接被拒)时返回 False —— **不抛异常,也不假装成功**。
        """
        import urllib.request

        port = os.environ.get("GALAXY_IPC_PORT", "9231")
        url = f"http://127.0.0.1:{port}{path}"
        try:
            req = urllib.request.Request(
                url, data=b"{}", method="POST", headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.getcode() == 200
        except Exception:  # noqa: BLE001 — 连不上就是连不上,如实返回 False
            return False

    def open_panel(self, icon: "pystray.Icon | None" = None, item: object = None) -> None:
        """打开 / 切换面板 —— Open or toggle the panel.

        两条路,按可靠性排:

        1. **IPC**(Electron 已在跑)—— 不依赖全局快捷键。快捷键常被输入法、
           远程桌面或别的应用吞掉,IPC 不会。
        2. **拉起桌面壳**(Electron 没在跑)—— 只在依赖完整时才尝试;残缺时
           ``npm start`` 会静默失败(CREATE_NO_WINDOW,没有任何窗口),用户感受
           就是「点了没反应」。

        两条都不通就发一条**说得出下一步**的通知,而不是开一个空白页。
        """
        if self._post_ipc("/ipc/toggle-panel"):
            logger.info("面板已切换(经 IPC)/ panel toggled via IPC")
            return

        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        electron_dir = os.path.join(project_root, "electron")

        electron_ready = os.path.isdir(electron_dir)
        if electron_ready:
            try:
                sys.path.insert(0, project_root)
                from core.electron_launch_guard import electron_package_intact

                electron_ready = electron_package_intact(electron_dir)
            except Exception:  # noqa: BLE001
                electron_ready = os.path.isdir(os.path.join(electron_dir, "node_modules"))

        if electron_ready:
            try:
                # Windows 上 npm 是 npm.cmd(批处理),CreateProcess 不能直接执行它,
                # 所以显式解析出可执行文件,而不是把整串丢给 shell 解释。
                npm = shutil.which("npm.cmd") or shutil.which("npm") if sys.platform == "win32" else shutil.which("npm")
                if not npm:
                    raise FileNotFoundError("未在 PATH 中找到 npm / npm not found in PATH")
                if sys.platform == "win32":
                    subprocess.Popen(
                        [npm, "start"], cwd=electron_dir, creationflags=subprocess.CREATE_NO_WINDOW
                    )
                else:
                    subprocess.Popen([npm, "start"], cwd=electron_dir)
                logger.info("已拉起桌面壳 / desktop shell launched from %s", electron_dir)
                return
            except Exception as exc:  # noqa: BLE001
                logger.error("拉起桌面壳失败 / failed to launch shell: %s", exc)

        self._show_notification(
            "Galaxy",
            "桌面壳未就绪,面板打不开。\n"
            "Desktop shell not ready — the panel cannot open.\n"
            "在 electron/ 执行 npm install,"
            "并在 electron/renderer/panel/ 执行 npm install && npm run build。",
        )
        logger.error("桌面壳不可用 / desktop shell unavailable")

    def _show_notification(self, title: str, message: str) -> None:
        """发一条系统通知(不支持就静默跳过)/ Show a system notification."""
        if self._icon is not None and _HAVE_TRAY:
            try:
                self._icon.notify(message, title)
            except Exception:  # noqa: BLE001 — 平台不支持通知时不该炸
                pass

    # ── 菜单 / Menu ──

    def _build_menu(self) -> "pystray.Menu":
        """右键菜单 —— **空的**。/ The context menu — deliberately empty.

        所有者要求:把之前那九项全部删掉,暂时先不放任何东西。

        唯一的成员是一个 ``visible=False`` 的默认项。它不出现在右键菜单里,
        但 pystray 用「默认项」承接单击 —— 没有它,点托盘不会触发任何回调,
        这个图标就只是一张贴纸。

        要把「退出」加回来,在这里补一行::

            pystray.MenuItem("退出 / Quit", lambda icon, item: self.stop())

        在那之前,停掉托盘的办法是结束 ``python main.py`` 那个进程,
        或由调用方拿 :meth:`stop`。
        """
        return pystray.Menu(
            pystray.MenuItem(
                _ACTIVATE_LABEL,
                self.open_panel,
                default=True,
                visible=False,
            ),
        )

    # ── 生命周期 / Lifecycle ──

    def create(self) -> "pystray.Icon | None":
        """创建(但不启动)托盘图标 / Create the icon without running it."""
        if not _HAVE_TRAY:
            logger.error(
                "系统托盘需要 pystray 与 Pillow / pystray and Pillow are required for the tray"
            )
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

        # 双击也走同一条路 / double-click takes the same path
        if hasattr(self._icon, "double_click"):
            self._icon.double_click = lambda icon: self.open_panel(icon, None)  # type: ignore[method-assign]

        return self._icon

    def run(self) -> None:
        """阻塞运行(必须在主线程)/ Run blocking (main thread only)."""
        if self._icon is None:
            self.create()
        if self._icon:
            logger.info("托盘启动中 / starting system tray ...")
            self._icon.run()

    def run_detached(self) -> threading.Thread:
        """在后台线程里跑 / Run in a background thread."""
        thread = threading.Thread(target=self.run, name="GalaxyTray", daemon=True)
        thread.start()
        logger.info("托盘已在后台线程启动 / tray started in background thread")
        return thread

    def stop(self) -> None:
        """停掉托盘 / Stop the tray.

        菜单里没有退出项,所以这是**代码侧唯一的**停法。
        """
        if self._icon:
            self._icon.stop()
            self._icon = None


# ---------------------------------------------------------------------------
# 便捷函数 / Convenience helpers
# ---------------------------------------------------------------------------


def create_tray(
    galaxy_process: subprocess.Popen[str] | None = None,
    on_status_change: Callable[[str], None] | None = None,
) -> GalaxyTray | None:
    """建好托盘但不启动 / Build the tray without starting it.

    pystray 或 Pillow 缺席时返回 ``None`` —— **不抛异常**:托盘是可选表层,
    它不可用不该让整个启动失败。
    """
    if not _HAVE_TRAY:
        logger.warning(
            "系统托盘不可用(缺 pystray / Pillow)/ system tray unavailable (pystray / Pillow missing)"
        )
        return None

    tray = GalaxyTray(galaxy_process=galaxy_process, on_status_change=on_status_change)
    tray.create()
    return tray


def start_tray_in_thread(
    galaxy_process: subprocess.Popen[str] | None = None,
    on_status_change: Callable[[str], None] | None = None,
) -> GalaxyTray | None:
    """一步启动 / Create and start in one call.

    返回 ``GalaxyTray``,不可用时返回 ``None``。调用方可用
    ``tray.set_status("running" | "warning" | "error" | "offline")`` 更新状态。
    """
    tray = create_tray(galaxy_process, on_status_change)
    if tray is None:
        return None

    tray.run_detached()
    time.sleep(0.5)  # 给图标一点时间出现 / let the icon appear
    tray.set_status("running")
    return tray


# ---------------------------------------------------------------------------
# 独立入口 / Standalone entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    if not _HAVE_TRAY:
        print("错误:需要 pystray 与 Pillow / ERROR: pystray and Pillow are required.")
        print("安装 / Install:  pip install pystray Pillow")
        sys.exit(1)

    _tray = create_tray()
    if _tray:
        _tray.set_status("running")
        print(
            "Galaxy V2 托盘已启动。点击图标打开面板;右键菜单是空的。\n"
            "Galaxy V2 tray is running. Click the icon to open the panel; "
            "the context menu is intentionally empty.\n"
            "停止 / To stop: Ctrl+C"
        )
        _tray.run()
    else:
        print("托盘创建失败 / failed to create tray icon")
        sys.exit(1)
