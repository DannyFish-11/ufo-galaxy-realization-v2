"""
windows_service.pet_icon — 右下角托盘那只桌宠 / The tray pet
============================================================

托盘图标以前是一张品牌星云图。现在它是**桌宠** —— 与面板里那只（``panel/src/ui/pet.ts``）、
覆盖层灵动岛上那只（``electron/renderer/app.js``）是同一只：

* **同一个样子** —— 下面这些常量（卵石外形、两道眼缝、各档眼睛的位置与高度、三相的大小与深浅、
  三种反应的姿势、身子与眼睛的颜色）与两处 CSS / SVG 逐个相等，由
  ``tests/test_every_pet_is_the_same_pet.py`` 核对。改一处不改另外两处，那条测试就红。
* **同一份推导** —— :func:`derive` 与 ``electron/renderer/pet_state.js`` 的 ``derive`` 是同一套规则，
  两边各跑一遍同一张用例表（``electron/renderer/pet_state.cases.json``）。
* **同一份帧** —— 托盘与后端在同一个进程里，它直接收在场桥广播给 WS / IPC 的那一份
  ``payload.render``（``core.lumiv_websocket_bridge.add_render_listener``），不另问、不另算。

托盘是一张静态图标：**不做呼吸、不做眨眼**（每秒重画托盘图标在 Windows 上会闪，也费电）。
相位、睁闭眼、在不在收、上一拍的反应 —— 这几样是事实，托盘照画；呼吸和眨眼不声称任何事，托盘不画。

本模块只依赖 Pillow，不依赖 pystray：没有桌面的机器上（CI、无头部署）也能画、也能测。
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# 样子 —— 与 panel/src/styles/hud.css、electron/renderer/index.html 逐个相等(测试核对)
# ---------------------------------------------------------------------------

#: 卵石外形(viewBox 0 0 40 40)。与 pet.ts / index.html 里 ``.pet-skin`` 的 ``d`` 一字不差。
PATH_D = (
    "M20 4.6c8 0 13.6 4.2 15 11 .6 2.9.6 5.9 0 8.8-1.4 7.2-6.8 11.6-15 11.6"
    "S6.4 31.6 5 24.4a22 22 0 0 1 0-8.8c1.4-6.8 7-11 15-11z"
)

#: 两道眼缝的横向位置、宽、圆角。
EYE_X: Tuple[float, float] = (13.2, 22.8)
EYE_W = 4.0
EYE_RX = 2.0

#: 眼睛的四档:(y, height, opacity)。``sensing`` = 睁着且此刻在收(睁大一点)。
EYE_STATES: Dict[str, Tuple[float, float, float]] = {
    "open": (14.4, 9.6, 1.0),
    "sensing": (14.0, 10.4, 1.0),
    "shut": (18.6, 2.4, 0.9),
    "unknown": (14.4, 9.6, 0.4),
}

#: 三相:(身子不透明度, 缩放, 竖直位移)。静的时候小而沉,显形时立起来。
PHASES: Dict[str, Tuple[float, float, float]] = {
    "silent": (0.86, 0.94, 0.0),
    "liminal": (0.94, 1.0, 0.0),
    "manifest": (1.0, 1.04, -0.8),
}

#: 一次性的反应:(dx, dy, 缩放, 旋转角度)。CSS 写法分别是
#: ``translate(0, -2.2px) scale(1.08)`` / ``translate(0, 1.6px) scale(0.9)`` / ``translate(3.4px, 0) rotate(8deg)``。
REACTS: Dict[str, Tuple[float, float, float, float]] = {
    "lean": (0.0, -2.2, 1.08, 0.0),
    "tuck": (0.0, 1.6, 0.9, 0.0),
    "aside": (3.4, 0.0, 1.0, 8.0),
}

#: 身子 / 还没收到过帧时的身子(再淡到 0.6)/ 眼睛 —— 面板 tokens.css 的 --pet-* 同一套。
#: 眼睛与皮肤是对调过的(所有者:「眼睛和皮肤的颜色调换一下,整体更明亮」):身子取面板那一支紫
#: (色相 312°)提亮,眼睛近白。只对调不提亮的话身子是墨色,在深色任务栏上几乎看不见。
SKIN = "#a58bb5"
SKIN_UNKNOWN = "#d3c8dc"
SKIN_UNKNOWN_OPACITY = 0.6
EYE = "#fcf9fe"

#: 姿势与呼吸的变换原点:身子包围盒的 (50%, 82%)(CSS 的 ``transform-origin: 50% 82%`` + ``fill-box``)。
ORIGIN_FRACTION = (0.5, 0.82)

# ---------------------------------------------------------------------------
# 推导 —— 与 electron/renderer/pet_state.js 同一套规则(同一张用例表核对)
# ---------------------------------------------------------------------------

BREATH: Dict[str, str] = {"none": "9s", "understanding": "6.5s", "thinking": "3.6s", "rehearsing": "2.6s"}
POSE: Dict[str, str] = {"none": "rest", "speak": "lean", "silent": "tuck", "delegate": "aside"}
REACT_MS = 1600


def derive(render: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """一帧(``payload.render``,或其中 lifecycle / liminal_activity / perception 三位)→ 桌宠该是哪一档。"""
    r = render or {}
    life = r.get("lifecycle")
    phase = life if life in ("liminal", "manifest") else "silent"
    act_raw = r.get("liminal_activity")
    activity = act_raw if isinstance(act_raw, str) and act_raw in BREATH else "none"
    p = r.get("perception")
    p = p if isinstance(p, Mapping) else None
    known = bool(p) and p.get("source") != "unwired"
    eyes = "shut" if p and p.get("privacy_paused") is True else ("open" if known else "unknown")
    sensing = ("true" if p.get("is_sensing") else "false") if known else "unknown"
    act: Optional[str] = None
    if known:
        a = p.get("ambient_action")
        act = a if isinstance(a, str) and a else "none"
    return {
        "phase": phase,
        "activity": activity,
        "rate": BREATH[activity],
        "eyes": eyes,
        "sensing": sensing,
        "act": act,
    }


def reaction_for(act: Optional[str]) -> Optional[str]:
    """这一拍的决策该演哪一种反应;不演就是 None。"""
    if not act or act == "none":
        return None
    return POSE.get(act, "rest")


# ---------------------------------------------------------------------------
# SVG 路径 → 折线(只认这条路径用到的命令,外加 L/H/V 以防以后改形)
# ---------------------------------------------------------------------------

_TOKEN = re.compile(r"[MmLlHhVvCcSsAaZz]|-?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?")
_ARITY = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "A": 7, "Z": 0}


def _arc_points(
    x1: float, y1: float, rx: float, ry: float, phi_deg: float, large: bool, sweep: bool, x2: float, y2: float
) -> List[Tuple[float, float]]:
    """SVG 椭圆弧(端点参数)→ 若干点(不含起点)。按 SVG 规范 F.6.5 换成中心参数再采样。"""
    if rx == 0 or ry == 0:
        return [(x2, y2)]
    phi = math.radians(phi_deg)
    cos_p, sin_p = math.cos(phi), math.sin(phi)
    dx, dy = (x1 - x2) / 2, (y1 - y2) / 2
    x1p = cos_p * dx + sin_p * dy
    y1p = -sin_p * dx + cos_p * dy
    rx, ry = abs(rx), abs(ry)
    lam = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
    if lam > 1:
        s = math.sqrt(lam)
        rx, ry = rx * s, ry * s
    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    coef = math.sqrt(max(0.0, num / den)) if den else 0.0
    if large == sweep:
        coef = -coef
    cxp = coef * rx * y1p / ry
    cyp = -coef * ry * x1p / rx
    cx = cos_p * cxp - sin_p * cyp + (x1 + x2) / 2
    cy = sin_p * cxp + cos_p * cyp + (y1 + y2) / 2

    def _ang(ux: float, uy: float, vx: float, vy: float) -> float:
        a = math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
        return a

    t1 = _ang(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    dt = _ang((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not sweep and dt > 0:
        dt -= 2 * math.pi
    elif sweep and dt < 0:
        dt += 2 * math.pi
    n = max(8, int(abs(dt) / (math.pi / 32)))
    pts = []
    for i in range(1, n + 1):
        t = t1 + dt * i / n
        x = cx + rx * math.cos(t) * cos_p - ry * math.sin(t) * sin_p
        y = cy + rx * math.cos(t) * sin_p + ry * math.sin(t) * cos_p
        pts.append((x, y))
    return pts


def _cubic(p0, p1, p2, p3, n: int = 16) -> List[Tuple[float, float]]:
    out = []
    for i in range(1, n + 1):
        t = i / n
        mt = 1 - t
        x = mt**3 * p0[0] + 3 * mt * mt * t * p1[0] + 3 * mt * t * t * p2[0] + t**3 * p3[0]
        y = mt**3 * p0[1] + 3 * mt * mt * t * p1[1] + 3 * mt * t * t * p2[1] + t**3 * p3[1]
        out.append((x, y))
    return out


def path_points(d: str = PATH_D) -> List[Tuple[float, float]]:
    """把一条闭合 SVG 路径展成折线点(viewBox 坐标)。"""
    tokens = _TOKEN.findall(d)
    pts: List[Tuple[float, float]] = []
    cur = (0.0, 0.0)
    start = (0.0, 0.0)
    last_ctrl: Optional[Tuple[float, float]] = None
    cmd = ""
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.isalpha():
            cmd = tok
            i += 1
            if cmd in "Zz":
                pts.append(start)
                cur = start
                last_ctrl = None
                continue
        up = cmd.upper()
        rel = cmd.islower()
        n = _ARITY[up]
        args = [float(t) for t in tokens[i : i + n]]
        i += n
        if up == "M":
            cur = (cur[0] + args[0], cur[1] + args[1]) if rel else (args[0], args[1])
            start = cur
            pts.append(cur)
            last_ctrl = None
            cmd = "l" if rel else "L"  # M 后面跟着的坐标对按 L 处理
        elif up == "L":
            cur = (cur[0] + args[0], cur[1] + args[1]) if rel else (args[0], args[1])
            pts.append(cur)
            last_ctrl = None
        elif up == "H":
            cur = (cur[0] + args[0] if rel else args[0], cur[1])
            pts.append(cur)
            last_ctrl = None
        elif up == "V":
            cur = (cur[0], cur[1] + args[0] if rel else args[0])
            pts.append(cur)
            last_ctrl = None
        elif up in ("C", "S"):
            if up == "C":
                c1 = (cur[0] + args[0], cur[1] + args[1]) if rel else (args[0], args[1])
                rest = args[2:]
            else:
                c1 = (2 * cur[0] - last_ctrl[0], 2 * cur[1] - last_ctrl[1]) if last_ctrl else cur
                rest = args
            c2 = (cur[0] + rest[0], cur[1] + rest[1]) if rel else (rest[0], rest[1])
            end = (cur[0] + rest[2], cur[1] + rest[3]) if rel else (rest[2], rest[3])
            pts.extend(_cubic(cur, c1, c2, end))
            last_ctrl = c2
            cur = end
        elif up == "A":
            end = (cur[0] + args[5], cur[1] + args[6]) if rel else (args[5], args[6])
            pts.extend(_arc_points(cur[0], cur[1], args[0], args[1], args[2], bool(args[3]), bool(args[4]), *end))
            cur = end
            last_ctrl = None
    return pts


# ---------------------------------------------------------------------------
# 画
# ---------------------------------------------------------------------------

_SKIN_POINTS: Optional[List[Tuple[float, float]]] = None


def _skin_points() -> List[Tuple[float, float]]:
    global _SKIN_POINTS
    if _SKIN_POINTS is None:
        _SKIN_POINTS = path_points(PATH_D)
    return _SKIN_POINTS


def _rgb(hex_color: str) -> Tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _body_transform(phase: str, react: Optional[str]):
    """身子那一层的变换(反应盖过静息姿势,与 CSS 里两条规则的先后一致)。返回 p -> p'。"""
    xs = [p[0] for p in _skin_points()]
    ys = [p[1] for p in _skin_points()]
    ox = min(xs) + (max(xs) - min(xs)) * ORIGIN_FRACTION[0]
    oy = min(ys) + (max(ys) - min(ys)) * ORIGIN_FRACTION[1]
    if react in REACTS:
        dx, dy, s, rot = REACTS[react]
        c, si = math.cos(math.radians(rot)), math.sin(math.radians(rot))

        def tf(p):  # translate(dx,dy) · scale(s) · rotate(rot):先转再缩、最后平移(CSS 从右往左作用)
            x, y = p[0] - ox, p[1] - oy
            x, y = x * c - y * si, x * si + y * c
            x, y = x * s, y * s
            return (ox + x + dx, oy + y + dy)

        return tf
    _op, s, dy = PHASES.get(phase, PHASES["silent"])

    def tf_phase(p):  # scale(s) · translate(0, dy):先平移再缩
        x, y = p[0] - ox, p[1] - oy + dy
        return (ox + x * s, oy + y * s)

    return tf_phase


def eye_state_key(state: Mapping[str, Any]) -> str:
    """眼睛画哪一档:闭 / 虚 / 睁大(在收)/ 睁。"""
    eyes = state.get("eyes")
    if eyes in ("shut", "unknown"):
        return eyes
    return "sensing" if state.get("sensing") == "true" else "open"


#: 托盘上取 viewBox 里的哪一块:整个 0 0 40 40,与 SVG 那两只同一个框 —— 裁小一点身子能大一圈,
#: 但「探身」(lean)那一下头顶就被切掉了。
_VIEW = (0.0, 0.0, 40.0, 40.0)


def render_pet(
    state: Mapping[str, Any],
    size: int = 64,
    *,
    react: Optional[str] = None,
    status: str = "running",
) -> Any:
    """画一帧托盘桌宠(RGBA)。4 倍超采样再缩小,边缘才是圆的。

    ``status`` 非 running 时右下角叠一颗状态点(降级 / 错误 / 离线),与原托盘一致。
    """
    from PIL import Image, ImageDraw

    S = size * 4
    x0, y0, x1, y1 = _VIEW
    k = S / (x1 - x0)

    def to_px(p):
        return ((p[0] - x0) * k, (p[1] - y0) * k)

    phase = state.get("phase") if state.get("phase") in PHASES else "silent"
    tf = _body_transform(phase, react)
    eyes_key = eye_state_key(state)

    if state.get("eyes") == "unknown":
        skin_rgb, skin_op = _rgb(SKIN_UNKNOWN), SKIN_UNKNOWN_OPACITY
    else:
        skin_rgb, skin_op = _rgb(SKIN), PHASES[phase][0]

    canvas = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    body = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(body).polygon([to_px(tf(p)) for p in _skin_points()], fill=(*skin_rgb, int(round(255 * skin_op))))
    canvas = Image.alpha_composite(canvas, body)

    if react in REACTS and REACTS[react][3]:
        # 转了一个角度的那一档(aside):圆角矩形不好直接转,每只眼画正了再转过去。
        eyes_layer = _rotate_eyes(state, react, k, to_px, tf, eyes_key, S)
    else:
        ey, eh, eop = EYE_STATES[eyes_key]
        eyes_layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        ed = ImageDraw.Draw(eyes_layer)
        for ex in EYE_X:
            (ax, ay), (bx, by) = to_px(tf((ex, ey))), to_px(tf((ex + EYE_W, ey + eh)))
            lo_x, hi_x = sorted((ax, bx))
            lo_y, hi_y = sorted((ay, by))
            # 眼缝的圆角跟着身子一起缩放;压扁(闭眼)时圆角不超过半高,两头仍是圆的。
            r = min(EYE_RX * k * _scale_of(phase, react), (hi_y - lo_y) / 2, (hi_x - lo_x) / 2)
            ed.rounded_rectangle([lo_x, lo_y, hi_x, hi_y], radius=r, fill=(*_rgb(EYE), int(round(255 * eop))))
    canvas = Image.alpha_composite(canvas, eyes_layer)

    _overlay_status_pip(canvas, status, S)
    return canvas.resize((size, size), Image.LANCZOS)


#: 应用图标(任务栏 / 窗口 / 快捷方式)上那只:立着、睁着眼、身子不透明 —— 不跟任何一帧,
#: 是它「在」的那个样子。画图标的是 scripts/render_app_icons.py。
APP_ICON_STATE: Mapping[str, Any] = {"phase": "manifest", "eyes": "open", "sensing": "false"}


def render_app_icon(size: int) -> Any:
    """应用图标的一张(RGBA,``size``×``size``)。与托盘同一只、同一套画法。"""
    return render_pet(APP_ICON_STATE, size)


def _scale_of(phase: str, react: Optional[str]) -> float:
    if react in REACTS:
        return REACTS[react][2]
    return PHASES.get(phase, PHASES["silent"])[1]


def _rotate_eyes(state, react, k, to_px, tf, eyes_key, S):
    """aside 那一档的眼睛:每只眼在自己的小图层里画正、转过去、贴到变换后的位置。"""
    from PIL import Image, ImageDraw

    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ey, eh, eop = EYE_STATES[eyes_key]
    s = _scale_of(state.get("phase", "silent"), react)
    rot = REACTS[react][3]
    w_px, h_px = EYE_W * k * s, eh * k * s
    pad = int(max(w_px, h_px)) + 4
    for ex in EYE_X:
        tile = Image.new("RGBA", (pad * 2, pad * 2), (0, 0, 0, 0))
        r = min(EYE_RX * k * s, h_px / 2, w_px / 2)
        ImageDraw.Draw(tile).rounded_rectangle(
            [pad - w_px / 2, pad - h_px / 2, pad + w_px / 2, pad + h_px / 2],
            radius=r,
            fill=(*_rgb(EYE), int(round(255 * eop))),
        )
        tile = tile.rotate(-rot, resample=Image.BICUBIC)  # PIL 逆时针为正,屏幕上 CSS rotate 正值是顺时针
        cx, cy = to_px(tf((ex + EYE_W / 2, ey + eh / 2)))
        layer.alpha_composite(tile, (int(round(cx - pad)), int(round(cy - pad))))
    return layer


_STATUS_COLORS = {
    "warning": (255, 200, 0),
    "error": (255, 60, 60),
    "offline": (128, 128, 128),
}


def _overlay_status_pip(canvas: Any, status: str, S: int) -> None:
    """非 running 时在右下角叠一颗状态色圆点,带白描边保证在深浅任务栏上都看得见。"""
    if status not in _STATUS_COLORS:
        return
    from PIL import ImageDraw

    pip = _STATUS_COLORS[status]
    pr = int(S * 0.13)
    ring = max(1, int(pr * 0.3))
    px = S - pr - ring - 1
    py = S - pr - ring - 1
    d = ImageDraw.Draw(canvas)
    d.ellipse([px - pr - ring, py - pr - ring, px + pr + ring, py + pr + ring], fill=(255, 255, 255, 235))
    d.ellipse([px - pr, py - pr, px + pr, py + pr], fill=(*pip, 255))


def state_key(state: Mapping[str, Any], react: Optional[str], status: str) -> Tuple[Any, ...]:
    """决定图标长什么样的那几位 —— 一样就不重画(托盘图标重画在 Windows 上会闪)。"""
    return (state.get("phase"), eye_state_key(state), state.get("eyes") == "unknown", react, status)


__all__: Sequence[str] = (
    "BREATH",
    "EYE",
    "EYE_RX",
    "EYE_STATES",
    "EYE_W",
    "EYE_X",
    "PATH_D",
    "PHASES",
    "POSE",
    "REACTS",
    "REACT_MS",
    "SKIN",
    "SKIN_UNKNOWN",
    "SKIN_UNKNOWN_OPACITY",
    "derive",
    "path_points",
    "reaction_for",
    "render_pet",
    "state_key",
)
