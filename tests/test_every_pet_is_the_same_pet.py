"""三只桌宠是**同一只**:面板里那只、覆盖层灵动岛上那只、右下角托盘那只。

所有者:「将右下角桌面图标改为桌宠样式 并且与其他地方的桌宠全部同步」。

「同步」拆成三件事,每一件都钉在这里:

1. **同一份推导** —— 同一帧推出同一档(相位、睁闭眼、在不在收、呼吸快慢、上一拍的反应)。
   面板与覆盖层都调 ``electron/renderer/pet_state.js``;托盘是 Python(``windows_service/pet_icon.derive``),
   与 node 那边(``pet_state.test.js``)跑**同一张用例表** ``pet_state.cases.json``。
   以前两份 JS 推导就讲岔过:进程里没有感知库时,覆盖层那只眼睛虚着、面板那只睁着。
2. **同一个样子** —— 外形、眼缝、各档眼睛的位置与高度、三相的大小与深浅、三种反应的姿势、颜色:
   面板 CSS、覆盖层 CSS、托盘常量逐个相等。
3. **同一份帧、实时** —— 托盘与后端同进程,直接订阅在场桥广播出去的那一份 ``payload.render``;
   感知那几位(按了隐私暂停、开始 / 停止在收)变了,桥每秒核一次、变了就广播,三只一起变 ——
   以前静息相位里没有下一帧,按了暂停眼睛也闭不上。
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from windows_service import pet_icon as P

_ROOT = Path(__file__).resolve().parents[1]
_RENDERER = _ROOT / "electron" / "renderer"
_PANEL_CSS = _RENDERER / "panel" / "src" / "styles" / "hud.css"
_TOKENS = _RENDERER / "panel" / "src" / "styles" / "tokens.css"
_PET_TS = _RENDERER / "panel" / "src" / "ui" / "pet.ts"
_OVERLAY = _RENDERER / "index.html"
_SHARED = _RENDERER / "pet_state.js"
_CASES = _RENDERER / "pet_state.cases.json"


def _nocomment_css(text: str) -> str:
    return re.sub(r"/\*.*?\*/", " ", text, flags=re.S)


def _decls(css: str, selector: str) -> dict:
    """某个选择器的全部声明(出现在几条规则里、或在逗号分隔的一组里都算),后写的覆盖先写的。"""
    out: dict = {}
    for sel_list, body in re.findall(r"([^{}]+)\{([^}]*)\}", css):
        if selector in [" ".join(x.split()) for x in sel_list.split(",")]:
            for k, v in re.findall(r"([\w-]+)\s*:\s*([^;]+);?", body):
                out[k.strip()] = v.strip()
    return out


def _px(v: str) -> float:
    m = re.fullmatch(r"(-?[\d.]+)(px)?", v.strip())
    assert m, v
    return float(m.group(1))


def _panel_css() -> str:
    return _nocomment_css(_PANEL_CSS.read_text(encoding="utf-8"))


def _overlay_css() -> str:
    html = _OVERLAY.read_text(encoding="utf-8")
    return _nocomment_css("\n".join(re.findall(r"<style[^>]*>(.*?)</style>", html, re.S)))


def _token(css: str, name: str) -> str:
    m = re.search(rf"{re.escape(name)}\s*:\s*(#[0-9a-fA-F]{{6}})", css)
    assert m, f"找不到 {name}"
    return m.group(1).lower()


def _color(css: str, value: str, token_css: str) -> str:
    m = re.fullmatch(r"var\((--[\w-]+)\)", value.strip())
    return _token(token_css, m.group(1)) if m else value.strip().lower()


#: 两处 CSS 各自的选择器前缀(面板是 class,覆盖层是 id)。
_SURFACES = {"panel": ".pet", "overlay": "#pet"}


def _surface_css(name: str) -> tuple:
    if name == "panel":
        return _panel_css(), _nocomment_css(_TOKENS.read_text(encoding="utf-8"))
    css = _overlay_css()
    return css, css


# ── 1. 同一份推导 ─────────────────────────────────────────────────────────────


_TABLE = json.loads(_CASES.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", _TABLE["cases"], ids=[c["name"] for c in _TABLE["cases"]])
def test_the_tray_derives_exactly_what_the_two_web_pets_derive(case):
    assert P.derive(case["input"]) == case["expect"]


@pytest.mark.parametrize("case", _TABLE["reactions"], ids=[str(c["act"]) for c in _TABLE["reactions"]])
def test_the_tray_reacts_exactly_like_the_two_web_pets(case):
    assert P.reaction_for(case["act"]) == case["expect"]


def test_the_tray_reads_the_whole_render_frame_too():
    """托盘收的是整份 ``payload.render``,里面多出来的字段不该影响推导。"""
    frame = {
        "lifecycle": "manifest",
        "liminal_activity": "none",
        "acting": True,
        "transition_seq": 7,
        "perception": {"source": "live", "is_sensing": True, "privacy_paused": False, "ambient_action": "speak"},
    }
    assert P.derive(frame)["eyes"] == "open" and P.derive(frame)["phase"] == "manifest"


def test_the_tables_are_the_same_three_ways():
    js = _SHARED.read_text(encoding="utf-8")

    def table(name: str) -> dict:
        m = re.search(rf"var {name} = \{{(.*?)\}};", js, re.S)
        assert m, name
        return dict(re.findall(r"(\w+):\s*'([^']+)'", m.group(1)))

    assert table("BREATH") == P.BREATH
    assert table("POSE") == P.POSE
    m = re.search(r"var REACT_MS = (\d+);", js)
    assert m and int(m.group(1)) == P.REACT_MS


def test_node_runs_the_same_case_table_in_ci():
    """用例表两边都要跑:pytest 这一边在上面,node 那一边必须真的在 CI 里跑(不在就是一条永远绿的线)。"""
    ci = (_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "electron/renderer/pet_state.test.js" in ci
    test_js = (_RENDERER / "pet_state.test.js").read_text(encoding="utf-8")
    assert "pet_state.cases.json" in test_js


# ── 2. 同一个样子 ─────────────────────────────────────────────────────────────


def test_the_outline_is_the_same_path_everywhere():
    ts = _PET_TS.read_text(encoding="utf-8")
    m = re.search(r"class: 'pet-skin',.*?d: '([^']+)'", ts, re.S)
    assert m, "pet.ts 里找不到身子那条路径"
    html = _OVERLAY.read_text(encoding="utf-8")
    m2 = re.search(r'<path class="pet-skin" d="([^"]+)"', html)
    assert m2, "index.html 里找不到身子那条路径"
    assert m.group(1) == m2.group(1) == P.PATH_D


def test_the_eye_slits_sit_in_the_same_place_everywhere():
    ts = _PET_TS.read_text(encoding="utf-8")
    panel = [
        (float(x), float(w), float(r))
        for x, w, r in re.findall(
            r"class: 'pet-eye', x: '([\d.]+)', y: '[\d.]+', width: '([\d.]+)'.*?rx: '([\d.]+)'", ts
        )
    ]
    html = _OVERLAY.read_text(encoding="utf-8")
    overlay = [
        (float(x), float(w), float(r))
        for x, w, r in re.findall(r'<rect class="pet-eye" x="([\d.]+)" width="([\d.]+)" rx="([\d.]+)"', html)
    ]
    want = [(x, P.EYE_W, P.EYE_RX) for x in P.EYE_X]
    assert panel == want, panel
    assert overlay == want, overlay


@pytest.mark.parametrize("surface", sorted(_SURFACES))
def test_every_eye_state_has_the_same_geometry(surface):
    css, _tokens = _surface_css(surface)
    pre = _SURFACES[surface]
    rules = {
        "open": f"{pre}[data-eyes='open'] .pet-eye",
        "shut": f"{pre}[data-eyes='shut'] .pet-eye",
        "unknown": f"{pre}[data-eyes='unknown'] .pet-eye",
        "sensing": f"{pre}[data-sensing='true'][data-eyes='open'] .pet-eye",
    }
    for key, sel in rules.items():
        d = _decls(css, sel)
        y, h, op = P.EYE_STATES[key]
        assert d, f"{surface}: 没有 {sel}"
        assert _px(d["y"]) == y and _px(d["height"]) == h, f"{surface} 的「{key}」眼睛几何与另外两只不一样:{d}"
        if key != "sensing":
            assert float(d["opacity"]) == op, f"{surface} 的「{key}」眼睛深浅与另外两只不一样:{d}"


@pytest.mark.parametrize("surface", sorted(_SURFACES))
def test_every_phase_has_the_same_size_and_depth(surface):
    css, _tokens = _surface_css(surface)
    pre = _SURFACES[surface]
    for phase, (opacity, scale, dy) in P.PHASES.items():
        skin = _decls(css, f"{pre}[data-phase='{phase}'] .pet-skin")
        assert float(skin["opacity"]) == opacity, f"{surface} 的「{phase}」身子深浅不一样:{skin}"
        body = _decls(css, f"{pre}[data-phase='{phase}'] .pet-body")
        tf = body.get("transform", "scale(1)")
        m = re.search(r"scale\(([\d.]+)\)", tf)
        assert float(m.group(1) if m else 1) == scale, f"{surface} 的「{phase}」大小不一样:{tf}"
        t = re.search(r"translate\(\s*0\s*,\s*(-?[\d.]+)px\)", tf)
        assert float(t.group(1) if t else 0) == dy, f"{surface} 的「{phase}」竖直位移不一样:{tf}"


@pytest.mark.parametrize("surface", sorted(_SURFACES))
def test_every_reaction_is_the_same_pose(surface):
    css, _tokens = _surface_css(surface)
    pre = _SURFACES[surface]
    for react, (dx, dy, scale, rot) in P.REACTS.items():
        tf = _decls(css, f"{pre}[data-react='{react}'] .pet-body")["transform"]
        t = re.search(r"translate\(\s*(-?[\d.]+)(?:px)?\s*,\s*(-?[\d.]+)(?:px)?\s*\)", tf)
        s = re.search(r"scale\(([\d.]+)\)", tf)
        r = re.search(r"rotate\((-?[\d.]+)deg\)", tf)
        got = (float(t.group(1)), float(t.group(2)), float(s.group(1)) if s else 1.0, float(r.group(1)) if r else 0.0)
        assert got == (dx, dy, scale, rot), f"{surface} 的「{react}」姿势与另外两只不一样:{tf}"


@pytest.mark.parametrize("surface", sorted(_SURFACES))
def test_the_colours_are_the_same(surface):
    css, tokens = _surface_css(surface)
    pre = _SURFACES[surface]
    skin = _decls(css, ".pet-skin")["fill"]
    eye = _decls(css, ".pet-eye")["fill"]
    unknown = _decls(css, f"{pre}[data-eyes='unknown'] .pet-skin")
    assert _color(css, skin, tokens) == P.SKIN, f"{surface} 的身子颜色不一样"
    assert _color(css, eye, tokens) == P.EYE, f"{surface} 的眼睛颜色不一样"
    assert _color(css, unknown["fill"], tokens) == P.SKIN_UNKNOWN, f"{surface}「还没收到帧」时的身子颜色不一样"
    assert float(unknown["opacity"]) == P.SKIN_UNKNOWN_OPACITY


# ── 托盘那只真的是这样画出来的 ────────────────────────────────────────────────


def _frame(**perception):
    base = {"source": "live", "is_sensing": False, "privacy_paused": False, "ambient_action": "none"}
    return {"lifecycle": "manifest", "liminal_activity": "none", "perception": {**base, **perception}}


def _pixels(img):
    """逐像素 RGBA。用 tobytes 而不用 getdata:后者在新版 Pillow 里已弃用,替代的那个旧版又没有。"""
    raw = img.convert("RGBA").tobytes()
    return [tuple(raw[i : i + 4]) for i in range(0, len(raw), 4)]


def _eye_pixels(img) -> int:
    er, eg, eb = P._rgb(P.EYE)
    return sum(
        1 for r, g, b, a in _pixels(img) if a > 200 and abs(r - er) < 24 and abs(g - eg) < 24 and abs(b - eb) < 24
    )


def test_the_tray_icon_is_the_pet_body_and_eyes():
    img = P.render_pet(P.derive(_frame()), 64)
    assert img.size == (64, 64) and img.mode == "RGBA"
    assert img.getpixel((0, 0))[3] == 0, "四角要透明 —— 托盘上只有那只桌宠,没有底板"
    sr, sg, sb = P._rgb(P.SKIN)
    r, g, b, a = img.getpixel((32, 46))
    assert a > 230 and abs(r - sr) < 10 and abs(g - sg) < 10 and abs(b - sb) < 10, "身子不是面板那支紫"
    assert _eye_pixels(img) > 40, "眼睛没画出来"


def test_shut_eyes_are_a_thin_line_and_unknown_is_faded():
    open_ = _eye_pixels(P.render_pet(P.derive(_frame()), 64))
    shut = _eye_pixels(P.render_pet(P.derive(_frame(privacy_paused=True)), 64))
    assert 0 < shut < open_ / 2, "按了隐私暂停,托盘那只的眼睛没压成一横"
    unknown = P.render_pet(P.derive(None), 64)
    assert max(px[3] for px in _pixels(unknown)) < 200, "还没收到帧时身子要淡下去(不知道就不摆样子)"


def test_a_reaction_and_a_status_change_the_icon():
    st = P.derive(_frame())
    base = P.render_pet(st, 64).tobytes()
    for react in P.REACTS:
        assert P.render_pet(st, 64, react=react).tobytes() != base, f"{react} 那一下在托盘上看不出来"
    assert P.render_pet(st, 64, status="error").tobytes() != base, "出错时托盘上没有那颗状态点"


def test_the_taskbar_icon_is_the_same_pet_not_the_old_nebula():
    """所有者:「桌面最下面一行应用图标显示的还是星云图片,那个也同样改成一样的桌宠」。

    任务栏 / 窗口 / 快捷方式 / 安装包用的那几张,必须就是 ``render_app_icon`` 现画的 ——
    桌宠的样子、颜色一改,``python scripts/render_app_icons.py`` 重画一遍,这里就会对上。"""
    import importlib.util

    spec = importlib.util.spec_from_file_location("render_app_icons", _ROOT / "scripts" / "render_app_icons.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    stale = [str(path.relative_to(_ROOT)) for path, data in mod.expected().items() if path.read_bytes() != data]
    assert not stale, f"这些应用图标不是现画的桌宠(跑一次 python scripts/render_app_icons.py): {stale}"

    from PIL import Image

    ico = Image.open(_ROOT / "electron" / "assets" / "icon.ico")
    assert {(16, 16), (32, 32), (48, 48), (256, 256)} <= set(ico.ico.sizes()), "任务栏常用的几个尺寸要各有一张"
    big = Image.open(_ROOT / "electron" / "assets" / "icon.png").convert("RGBA")
    assert big.getpixel((0, 0))[3] == 0, "四角要透明 —— 任务栏上只有那只桌宠,没有底板"
    sr, sg, sb = P._rgb(P.SKIN)
    r, g, b, a = big.getpixel((256, 380))
    assert a > 240 and abs(r - sr) < 10 and abs(g - sg) < 10 and abs(b - sb) < 10, "身子不是桌宠那支紫"
    main_js = (_ROOT / "electron" / "main.js").read_text(encoding="utf-8")
    assert "'icon.ico' : 'icon.png'" in main_js, "窗口图标不再取这几张了"


def test_the_svg_path_flattens_into_the_pebble():
    """折线的外框要与路径本身的几何对得上(按路径里的数算出来,不是量截图量出来的):

    * 左:半径 22 的弧(``a22 22 … 0-8.8``)从 x=5 往外鼓出一个弓高 22-√(22²-4.4²);
    * 右:``c.6 2.9.6 5.9 0 8.8`` 这段三次曲线从 x=35 往外最多鼓 0.75×0.6;
    * 上沿 4.6(起点),下沿 36.0(``…-15 11.6`` 落到的那一点)。
    """
    pts = P.path_points()
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    assert min(xs) == pytest.approx(5.0 - (22 - (22**2 - 4.4**2) ** 0.5), abs=0.01)
    assert max(xs) == pytest.approx(35.0 + 0.75 * 0.6, abs=0.01)
    assert min(ys) == pytest.approx(4.6, abs=0.01) and max(ys) == pytest.approx(36.0, abs=0.01)
    assert pts[0] == pts[-1], "外形没闭合"


# ── 3. 同一份帧、实时 ─────────────────────────────────────────────────────────


@pytest.fixture
def tray_module(monkeypatch):
    """托盘模块在无桌面的机器上 import 时 pystray 起不来(_HAVE_TRAY=False)—— 画图那部分不依赖它。"""
    import windows_service.tray_icon as T

    monkeypatch.setattr(T, "_HAVE_TRAY", True)
    return T


def test_the_tray_follows_every_frame_and_only_redraws_on_change(tray_module):
    tray = tray_module.GalaxyTray()
    tray._icon = SimpleNamespace(icon=None, title="")
    tray.on_render(_frame(is_sensing=True))
    first = tray._icon.icon
    assert first is not None and "正在感知" in tray._icon.title
    tray.on_render(_frame(is_sensing=True))
    assert tray._icon.icon is first, "同一帧又重画了一遍 —— 托盘图标重画在 Windows 上会闪"
    tray.on_render(_frame(privacy_paused=True))
    assert tray._icon.icon is not first and "感知已暂停" in tray._icon.title


def test_the_tray_reaction_is_one_shot(tray_module, monkeypatch):
    monkeypatch.setattr(P, "REACT_MS", 30)
    tray = tray_module.GalaxyTray()
    tray._icon = SimpleNamespace(icon=None, title="")
    tray.on_render(_frame(ambient_action="speak"))
    assert tray._react == "lean"
    tray.on_render(_frame(ambient_action="speak"))  # 同一个决策跟着下一帧回来:不重演
    import time

    time.sleep(0.15)
    assert tray._react is None, "反应演完没撤 —— 一个过去的决策会变成永久姿势"


def test_the_tray_subscribes_itself_to_the_presence_frames(tray_module):
    """托盘起来之后订阅在场桥广播的同一份帧(``start_tray_in_thread`` 在图标真的出现之后调它)。"""
    import core.presence_fanout as F

    src = Path(tray_module.__file__).read_text(encoding="utf-8")
    tail = src[src.index("def start_tray_in_thread(") :]
    assert tail.index('tray.set_status("running")') < tail.index("tray.follow_presence()")
    tray = tray_module.GalaxyTray()
    try:
        tray.follow_presence()
        assert tray.on_render in F._RENDER_LISTENERS
    finally:
        F._RENDER_LISTENERS.remove(tray.on_render)


@pytest.fixture
def bridge(monkeypatch):
    import core.lumiv_websocket_bridge as B
    import core.presence_fanout as F

    B.GalaxyPresenceBridge._instance = None
    monkeypatch.setattr(F, "_LAST_RENDER", None)
    monkeypatch.setattr(F, "_SENT_KEY", None)
    b = B.GalaxyPresenceBridge.get_instance()

    async def _no_ipc(_msg):
        return False

    b._try_ipc_http = _no_ipc
    yield F, b
    B.GalaxyPresenceBridge._instance = None


def test_every_broadcast_reaches_the_in_process_listeners(bridge):
    F, b = bridge
    seen = []
    F.add_render_listener(seen.append)
    try:
        asyncio.run(b._broadcast_state())
        assert seen and seen[-1] is F._LAST_RENDER
        assert {"lifecycle", "perception"} <= set(seen[-1])
        # 后订阅的立刻补发最近那一份 —— 托盘起得比第一次广播晚也不会停在「不知道」
        late = []
        F.add_render_listener(late.append)
        assert late and late[0] is seen[-1]
        F._RENDER_LISTENERS.remove(late.append)
    finally:
        F._RENDER_LISTENERS.remove(seen.append)


def test_a_broken_listener_does_not_break_the_broadcast(bridge):
    F, b = bridge

    def boom(_r):
        raise RuntimeError("坏了")

    F.add_render_listener(boom)
    try:
        asyncio.run(b._broadcast_state())  # 不抛
    finally:
        F._RENDER_LISTENERS.remove(boom)


def test_a_snapshot_for_one_new_client_does_not_count_as_a_broadcast(bridge):
    """单个新客户端的快照不走 publish:不然监视会以为「已经广播过这一份」,别的客户端就漏掉了变化。"""
    F, b = bridge

    class _WS:
        def __init__(self):
            self.sent = []

        async def send_json(self, msg):
            self.sent.append(msg)

    ws = _WS()
    asyncio.run(b._send_to(ws))
    assert ws.sent and ws.sent[0]["type"] == "state_event"
    assert F._SENT_KEY is None and F._LAST_RENDER is None


def test_the_broadcast_key_and_the_watch_key_agree(bridge):
    """监视拿 PerceptionView 算、广播后拿字典算 —— 两种算出来必须一样,否则每秒都会误判「变了」。"""
    F, b = bridge
    from core.phase_contract import resolve_perception_view

    view = resolve_perception_view(speaking=False, ambient_action="none", ambient_rationale="")
    asyncio.run(b._broadcast_state())
    assert F._SENT_KEY == F.perception_key(view)


def test_a_perception_change_is_broadcast_without_any_other_event(bridge, monkeypatch):
    """静息相位里没有别的广播:按了隐私暂停,三只桌宠的眼睛也要在一秒左右内闭上。"""
    F, b = bridge
    import core.phase_contract as PC

    state = {"paused": False}

    def fake_view(**_kw):
        return SimpleNamespace(
            source="live",
            is_sensing=False,
            privacy_paused=state["paused"],
            modalities=[SimpleNamespace(modality="microphone", state="idle")],
        )

    monkeypatch.setattr(PC, "resolve_perception_view", fake_view)
    monkeypatch.setattr(F, "WATCH_S", 0.01)
    monkeypatch.setattr(F, "_SENT_KEY", F.perception_key(fake_view()))  # 已经广播过当前这一份
    sent = []

    async def count():
        sent.append(1)

    async def run():
        b._broadcast_state = count  # 只数广播次数
        b._started = True
        F.start_perception_watch(b)
        await asyncio.sleep(0.08)
        quiet = len(sent)
        state["paused"] = True
        await asyncio.sleep(0.05)
        b._started = False
        await asyncio.sleep(0.03)
        return quiet, len(sent)

    quiet, after = asyncio.run(run())
    assert quiet == 0, "感知没变也在广播 —— 每秒一帧白白推给所有窗口"
    assert after >= 1, "按了隐私暂停,没有任何广播 —— 桌宠的眼睛闭不上"
