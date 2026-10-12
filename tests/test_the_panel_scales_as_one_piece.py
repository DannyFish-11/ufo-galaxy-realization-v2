"""面板是**一整张画布**:拖哪条边、哪个角都是整张等比变大变小,里面不重新排版。

所有者:「我把上下左右角一放缩,有些东西就被揉起来了,无论是右上角设置里面的那个,还是整个面板,
都会受到影响。而且这个面板给人感觉就像面团一样,不像一个完整的整体」。

原因是面板按窗口实际大小重新排版(左栏定宽 + 右边 1fr,设置页的行跟着宽度折行),每拖一下排一次。
现在桌面外壳里面板按 ``PanelStage.STAGE`` 排一次版,之后只做 ``transform: scale``;窗口的宽高比
锁在同一个比例上,拉伸由面板边角上的手柄发起、主进程按光标等比改大小(没有系统粗边框,系统不替它拉)。

几何本身(等比、对边不动、上下限)在 ``electron/renderer/panel_stage.test.js`` 里用 node 测;
真 Electron 里拖右下角、松手、拖过下限也实跑过(沙箱 xvfb)。这里钉的是**三处都真的接上了**。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ELECTRON = ROOT / "electron"
PANEL = ELECTRON / "renderer" / "panel"


def _panel_block() -> str:
    src = (ELECTRON / "main.js").read_text(encoding="utf-8")
    start = src.index("function createPanelWindow()")
    return src[start : src.index("panelWindow.loadFile(panelPath)", start)]


def test_one_stage_definition_for_the_window_and_the_page():
    main = (ELECTRON / "main.js").read_text(encoding="utf-8")
    assert "require('./renderer/panel_stage.js')" in main
    stage_ts = (PANEL / "src" / "stage.ts").read_text(encoding="utf-8")
    assert "import '../../panel_stage.js';" in stage_ts, "面板与主进程的画布尺寸不是同一个出处"
    block = _panel_block()
    assert "PanelStage.initialSize(" in block and "PanelStage.limits(" in block
    assert re.search(r"width:\s*first\.width", block) and re.search(r"height:\s*first\.height", block)


def test_the_window_is_resized_only_along_the_stage_ratio():
    block = _panel_block()
    assert re.search(r"resizable:\s*false", block), "系统拉伸不锁宽高比 —— 一拉就又成了面团"
    main = (ELECTRON / "main.js").read_text(encoding="utf-8")
    handler = main[main.index("ipcMain.on('panel:resize-begin'") :][:1500]
    assert "PanelStage.resizeBounds(" in handler
    assert "event.sender !== panelWindow.webContents" in handler, "别的窗口也能拉面板"
    assert "screen.getCursorScreenPoint()" in handler, "光标位置要在主进程读 —— 页面是缩放过的"
    # 拖着拖着失焦 / 被收起,也要停;不然窗口会一直跟着光标变。
    assert "panelWindow.on('blur', endPanelResize)" in main
    assert "panelWindow.on('hide', endPanelResize)" in main
    preload = (ELECTRON / "preload.js").read_text(encoding="utf-8")
    assert "ipcRenderer.send('panel:resize-begin'" in preload and "ipcRenderer.send('panel:resize-end'" in preload


def test_the_page_scales_the_whole_stage_instead_of_reflowing():
    stage_ts = (PANEL / "src" / "stage.ts").read_text(encoding="utf-8")
    assert "scale(${k})" in stage_ts
    assert "PS.STAGE.width" in stage_ts and "PS.STAGE.height" in stage_ts, "画布不是固定尺寸"
    assert "setPointerCapture" in stage_ts, "光标拖出窗口就收不到松手"
    main_ts = (PANEL / "src" / "main.ts").read_text(encoding="utf-8")
    boot = main_ts[main_ts.index("function boot(): void {") :][:300]
    assert boot.index("fitStage(host, IN_DESKTOP_SHELL)") < boot.index("mount(host)")
    css = (PANEL / "src" / "styles" / "hud.css").read_text(encoding="utf-8")
    assert re.search(r"html\[data-stage='fixed'\] #hud\s*\{[^}]*transform-origin:\s*0 0", css)
    for edge in ("n", "s", "e", "w", "ne", "nw", "se", "sw"):
        assert f".grip[data-edge='{edge}']" in css, f"{edge} 那条手柄没有样式(点不到)"


def test_the_built_panel_carries_the_stage():
    """Electron 加载的是提交进仓库的 dist —— 源码改了产物没重建等于没改。"""
    js = "".join(p.read_text(encoding="utf-8", errors="ignore") for p in (PANEL / "dist" / "assets").glob("*.js"))
    assert "PanelStage" in js and "data-stage" in js and "beginResize" in js


def test_the_stage_tests_run_in_ci():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "electron/renderer/panel_stage.test.js" in ci
