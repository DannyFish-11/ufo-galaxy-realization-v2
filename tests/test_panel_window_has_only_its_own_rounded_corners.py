"""面板窗口只有它自己的圆角：圆角之外不能再有方的、不透明的角。

真机：面板窗口是透明的，``.shell`` 有 34px 圆角，可窗口四角却多出方形的角。
根因有两处：
1. ``body`` 的渐变背景（``html`` 自己没有底）被当成画布底色，铺满整个窗口矩形 —— 圆角之外的四个角
   是方的、不透明的（用 Chromium 实测过：四角像素 alpha=255）；
2. 透明窗口开着 ``hasShadow``，系统阴影按窗口矩形画，不跟着圆角走。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PANEL = ROOT / "electron" / "renderer" / "panel"


def _css() -> str:
    return (PANEL / "src" / "styles" / "hud.css").read_text(encoding="utf-8")


def test_the_canvas_is_transparent_inside_the_desktop_shell():
    css = _css()
    m = re.search(r"html\[data-shell='desktop'\],\s*html\[data-shell='desktop'\] body\s*\{([^}]*)\}", css)
    assert m, "桌面外壳里 html 与 body 都要去掉画布底"
    assert re.search(r"background:\s*transparent", m.group(1))


def test_the_shell_marker_is_set_before_styles_apply_not_after_the_module_runs():
    html = (PANEL / "index.html").read_text(encoding="utf-8")
    inline = re.search(r"<script>([^<]*galaxyShell[^<]*)</script>", html)
    assert inline, "标记必须由 head 里的内联脚本同步设置 —— 等模块脚本再设会闪一下方形的渐变底"
    assert "dataset.shell = 'desktop'" in inline.group(1)
    assert html.index(inline.group(0)) < html.index('type="module"')


def test_the_built_page_carries_the_same_marker():
    """dist 是提交进仓库的产物，Electron 加载的是它 —— 源码改了而产物没重建等于没改。"""
    built = (PANEL / "dist" / "index.html").read_text(encoding="utf-8")
    assert "dataset.shell" in built and "galaxyShell" in built
    css_in_assets = "".join(
        p.read_text(encoding="utf-8", errors="ignore") for p in (PANEL / "dist" / "assets").glob("*.css")
    )
    js_in_assets = "".join(
        p.read_text(encoding="utf-8", errors="ignore") for p in (PANEL / "dist" / "assets").glob("*.js")
    )
    assert "data-shell" in css_in_assets + js_in_assets


def test_the_shell_still_rounds_its_own_corners():
    css = _css()
    radius = re.search(r":root\s*\{\s*--shell-r:\s*(\d+)px", css)
    assert radius and int(radius.group(1)) >= 16
    assert re.search(r"\.shell\s*\{[^}]*border-radius:\s*var\(--shell-r\)", css), ".shell 的圆角要取同一个半径"


def test_the_desktop_window_itself_is_clipped_to_that_same_radius():
    """透明窗口里，圆角之外任何一层漏出来的内容（滚动条、阴影、子层）都会画成方角。
    把整个 html 按同一个半径裁掉，圆角外就一个像素也不会有。"""
    css = _css()
    m = re.search(r"html\[data-shell='desktop'\]\s*\{[^}]*clip-path:\s*inset\(0 round var\(--shell-r\)\)", css)
    assert m, "桌面外壳的 html 要按 --shell-r 裁圆角"


def test_the_transparent_panel_window_does_not_ask_the_os_for_a_rectangular_shadow():
    src = (ROOT / "electron" / "main.js").read_text(encoding="utf-8")
    start = src.index("function createPanelWindow()")
    block = src[start : src.index("panelWindow.loadFile(panelPath)", start)]
    assert "transparent: true" in block
    assert re.search(r"hasShadow:\s*false", block), "透明窗口的系统阴影按窗口矩形画，会多出四个方角"
