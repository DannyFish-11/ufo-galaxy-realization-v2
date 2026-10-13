"""面板窗口只有它自己的圆角：圆角之外不能再有方的、不透明的角。

真机：面板窗口是透明的，``.shell`` 有 34px 圆角，可窗口四角却多出方形的角。
根因有三处：
1. ``body`` 的渐变背景（``html`` 自己没有底）被当成画布底色，铺满整个窗口矩形 —— 圆角之外的四个角
   是方的、不透明的（用 Chromium 实测过：四角像素 alpha=255）；
2. 透明窗口开着 ``hasShadow``，系统阴影按窗口矩形画，不跟着圆角走；
3. 前两处修完，所有者还是看到「4 个角还是有那种矩形的白边」：窗口带着 Windows 的粗边框
   （WS_THICKFRAME / WS_CAPTION），Windows 11 沿**窗口矩形**描一圈 1 像素的系统边 —— 页面这边
   四角早就是透明的了，这一圈是系统画的，只有去掉粗边框（``thickFrame: false``）才没有。
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
    把整个 html 按同一个半径、按画布那一块裁掉（窗口比例没对上时画布外那一条也裁），圆角外就一个像素也不会有。"""
    css = _css()
    m = re.search(
        r"html\[data-shell='desktop'\]\s*\{[^}]*clip-path:\s*inset\(var\(--stage-dy, 0px\) var\(--stage-dx, 0px\) "
        r"round calc\(var\(--shell-r\) \* var\(--stage-k, 1\)\)\)",
        css,
    )
    assert m, "桌面外壳的 html 要按 --shell-r 裁圆角(随画布一起缩放、跟着画布的位置)"


def test_the_os_cuts_the_window_to_the_panel_shape():
    """所有者在 Windows 上拍到：窗口矩形是白的、方角，面板圆角落在里面，上沿还露一条白带 —— 那台机器上
    透明窗口没有透明，页面这边做什么都没用。窗口外形交给系统裁（setShape = 窗口区域），
    圆角外、画布外就不是窗口的一部分：不画、不接鼠标。真 Electron（xvfb，无合成器）里核过：
    圆角外与多出来的那条透出的是下层窗口。"""
    main = (ROOT / "electron" / "main.js").read_text(encoding="utf-8")
    start = main.index("function createPanelWindow()")
    block = main[start : main.index("panelWindow.loadFile(panelPath)", start)]
    assert "shapePanel();" in block and "panelWindow.on('resize', shapePanel)" in block
    fn = main[main.index("function shapePanel()") :][:600]
    assert "panelWindow.setShape(PanelStage.shapeRects(" in fn, "外形不是按画布算的"


def test_the_window_shape_and_the_page_use_one_radius():
    stage = (ROOT / "electron" / "renderer" / "panel_stage.js").read_text(encoding="utf-8")
    radius = re.search(r"var RADIUS = (\d+);", stage)
    css = re.search(r":root\s*\{\s*--shell-r:\s*(\d+)px", _css())
    assert radius and css and radius.group(1) == css.group(1), "窗口外形的圆角与页面的圆角不是同一个半径"
    stage_ts = (ROOT / "electron" / "renderer" / "panel" / "src" / "stage.ts").read_text(encoding="utf-8")
    assert "setProperty('--shell-r', `${PS.RADIUS}px`)" in stage_ts


def test_the_transparent_panel_window_does_not_ask_the_os_for_a_rectangular_shadow():
    src = (ROOT / "electron" / "main.js").read_text(encoding="utf-8")
    start = src.index("function createPanelWindow()")
    block = src[start : src.index("panelWindow.loadFile(panelPath)", start)]
    assert "transparent: true" in block
    assert re.search(r"hasShadow:\s*false", block), "透明窗口的系统阴影按窗口矩形画，会多出四个方角"


def test_the_panel_window_has_no_thick_frame_for_windows_to_outline():
    """Windows 给带粗边框的窗口沿窗口矩形描边、倒系统圆角 —— 面板的圆角外就多一圈方的白边。"""
    src = (ROOT / "electron" / "main.js").read_text(encoding="utf-8")
    start = src.index("function createPanelWindow()")
    block = src[start : src.index("panelWindow.loadFile(panelPath)", start)]
    assert re.search(r"thickFrame:\s*false", block), "面板窗口又带上了系统粗边框"
