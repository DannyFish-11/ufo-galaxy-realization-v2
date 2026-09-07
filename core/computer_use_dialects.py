"""桌面动作的**方言表** —— 一套循环吃多家格式。

为什么需要它
------------
``core/computer_use_loop.py`` 原来只认一种形状:自己在 planner prompt 里约定的
扁平 JSON ``{"action": "click", "x": 100, "y": 200, "reason": "…"}``。

本地模型按这个 prompt 来,没问题。但真要接**厂商自带的 computer use**,格式就对不上了:

* **Anthropic** 走 ``tool_use`` 块,动作在 ``input.action``,坐标是
  ``coordinate: [x, y]`` **数组**,而且动作名不一样(``key`` 不叫 ``press_key``、
  ``mouse_move`` 不叫 ``move``、``left_click_drag`` 不叫 ``drag``);
* **OpenAI Responses** 的 computer use 又是另一套(``computer_call``);
* 端侧 GUI-VLA(如 Mano-P)再一套。

三条路都往 ``_parse_action_json`` 里塞 ``if`` 的话,第二家就会写在第二个地方,
然后没人说得清"到底支持哪几种、这一次是按哪种解出来的"。

所以:每一家是一条**方言登记**,自己声明两件事 —— 怎么认出是我、怎么翻成规范动作。

规范动作长什么样
----------------
就是 ``computer_use_loop`` 现在用的那个扁平形状,一个字没改::

    {"action": "click", "x": 100, "y": 200, "reason": "点登录按钮"}

下游(白名单校验、循环检测、节点派发)全都吃它。方言层只负责**翻译**,
不碰下游的任何判据 —— 回滚等于把 dialect 参数去掉。

不许猜
------
认不出是哪一家就返回 ``None`` 并说明原因,**绝不"尽力猜一个"**:
猜错的后果是在无关位置点一下,而认不出只是这一步不执行。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("Galaxy.ComputerUse.Dialects")

#: 方言标识 —— 一处定义,日志/留痕/配置都用它。
DIALECT_NATIVE = "native"
DIALECT_ANTHROPIC = "anthropic"

__all__ = [
    "DIALECT_ANTHROPIC",
    "DIALECT_NATIVE",
    "ActionDialect",
    "DIALECTS",
    "translate_any",
    "anthropic_tool_schema",
    "ANTHROPIC_BUILTIN_TOOL_BETAS",
    "is_anthropic_native_tool",
    "anthropic_betas_for_tools",
    "anthropic_tool_for_screenshot",
]


# ---------------------------------------------------------------------------
# native —— 本仓自己的扁平 JSON(planner prompt 约定的那套)
# ---------------------------------------------------------------------------


def _strip_code_fence(text: str) -> str:
    t = (text or "").strip()
    if "```" in t:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", t)
        if m:
            t = m.group(1).strip()
    return t


def _first_json_object(text: str) -> Optional[Dict[str, Any]]:
    t = _strip_code_fence(text)
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(t[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _native_detect(payload: Any) -> bool:
    """扁平 JSON 且顶层就有 action。"""
    if isinstance(payload, dict):
        return "action" in payload and "input" not in payload
    obj = _first_json_object(payload) if isinstance(payload, str) else None
    return bool(obj and "action" in obj and "input" not in obj)


def _native_translate(payload: Any) -> Tuple[Optional[Dict[str, Any]], str]:
    obj = payload if isinstance(payload, dict) else _first_json_object(payload)
    if not obj or "action" not in obj:
        return None, "不是本仓约定的扁平动作 JSON"
    return dict(obj), ""


# ---------------------------------------------------------------------------
# anthropic —— tool_use 块
# ---------------------------------------------------------------------------

#: Anthropic 的动作名 → 本仓规范动作名。
#:
#: 名字对不上是真的会咬人:``key`` 直接当成本仓的动作名会落进白名单之外被拒,
#: 而 ``mouse_move`` / ``left_click_drag`` 更是完全不同的写法。
_ANTHROPIC_ACTION = {
    "click": "click",
    "left_click": "click",
    "double_click": "double_click",
    "right_click": "right_click",
    "type": "type",
    "key": "press_key",
    "mouse_move": "move",
    "left_click_drag": "drag",
    "scroll": "scroll",
    # screenshot 是它"想再看一眼屏幕"。本仓的循环**每一步都会重新截图**,
    # 所以这一步翻成 wait:等一拍,下一轮它自然拿到新画面。
    # 这是一次**转义**,不是等价映射 —— 记在这里,免得以后有人以为丢了动作。
    "screenshot": "wait",
}


def _anthropic_find_tool_use(payload: Any) -> Optional[Dict[str, Any]]:
    """从一条 Anthropic 响应里挑出 computer 那个 tool_use 块。

    ``payload`` 可以是已经解析好的 dict,**也可以是 JSON 字符串** ——
    调用方拿到的往往是模型回复的原文(字符串),只吃 dict 的话这一整家都认不出来。
    (第一版就漏了这条,自测时当场露馅。)
    """
    obj: Any = payload
    if isinstance(obj, str):
        obj = _first_json_object(obj)
    if not isinstance(obj, dict):
        return None
    if obj.get("type") == "tool_use":
        return obj
    content = obj.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                return block
    return None


def _anthropic_detect(payload: Any) -> bool:
    return _anthropic_find_tool_use(payload) is not None


def _coord_pair(raw: Any) -> Optional[Tuple[int, int]]:
    """``[x, y]`` → ``(x, y)``;形状不对返回 None(不猜)。"""
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        try:
            return int(raw[0]), int(raw[1])
        except (TypeError, ValueError):
            return None
    return None


def _anthropic_translate(payload: Any) -> Tuple[Optional[Dict[str, Any]], str]:
    block = _anthropic_find_tool_use(payload)  # 字符串与 dict 都吃
    if block is None:
        return None, "响应里没有 tool_use 块"

    tool_input = block.get("input")
    if not isinstance(tool_input, dict):
        return None, "tool_use 里没有结构化 input"

    raw_action = str(tool_input.get("action", "")).strip().lower()
    if not raw_action:
        return None, "input 里没有 action"

    mapped = _ANTHROPIC_ACTION.get(raw_action)
    if mapped is None:
        # 认不出就说认不出。这里**不许**回退成 click 之类的"合理猜测"。
        return None, f"不认识的 Anthropic 动作: {raw_action!r}"

    out: Dict[str, Any] = {"action": mapped, "reason": f"anthropic:{raw_action}"}

    point = _coord_pair(tool_input.get("coordinate"))
    if mapped == "drag":
        start = _coord_pair(tool_input.get("start_coordinate"))
        if start is None or point is None:
            return None, "left_click_drag 缺 start_coordinate / coordinate"
        out.update({"from_x": start[0], "from_y": start[1], "to_x": point[0], "to_y": point[1]})
    elif point is not None:
        out.update({"x": point[0], "y": point[1]})

    if mapped == "type":
        out["text"] = str(tool_input.get("text", ""))
    if mapped == "press_key":
        out["key"] = str(tool_input.get("key", "") or tool_input.get("text", ""))
    if mapped == "scroll":
        if "direction" in tool_input:
            out["direction"] = str(tool_input.get("direction", ""))
        if "magnitude" in tool_input:
            out["amount"] = tool_input.get("magnitude")
    if mapped == "wait":
        out["seconds"] = 0.5  # screenshot 转义来的:只等一拍就重新看画面

    return out, ""


# ---------------------------------------------------------------------------
# 登记表
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ActionDialect:
    """一种"模型怎么表达动作"的方言。

    Attributes:
        name: 稳定标识,进日志与留痕。
        label: 给人看的名字。
        detect: 这段回复是不是我这一家的。
        translate: 翻成规范动作;返回 ``(动作 or None, 说不出来的原因)``。
    """

    name: str
    label: str
    detect: Callable[[Any], bool]
    translate: Callable[[Any], Tuple[Optional[Dict[str, Any]], str]]


DIALECTS: List[ActionDialect] = [
    # anthropic 排在前面:它的形状(有 tool_use 块)比扁平 JSON 更**具体**,
    # 先认具体的那个,不会把它误判成 native。
    ActionDialect(
        name=DIALECT_ANTHROPIC,
        label="Anthropic computer use (tool_use)",
        detect=_anthropic_detect,
        translate=_anthropic_translate,
    ),
    ActionDialect(
        name=DIALECT_NATIVE,
        label="本仓扁平动作 JSON",
        detect=_native_detect,
        translate=_native_translate,
    ),
]


def translate_any(payload: Any, *, only: Optional[str] = None) -> Tuple[Optional[Dict[str, Any]], str, str]:
    """按登记表逐个认,认出来就翻。

    Args:
        payload: 模型回复 —— 字符串或已经解析好的 dict 都行。
        only: 只用指定方言(排障/测试用);不给就按登记顺序自动识别。

    Returns:
        ``(规范动作 or None, 用的是哪种方言, 认不出/翻不动的原因)``。
        **认不出一律返回 None**,绝不猜一个"看起来合理"的动作 ——
        猜错会在无关位置点一下,认不出只是这一步不执行。
    """
    tried: List[str] = []
    for dialect in DIALECTS:
        if only is not None and dialect.name != only:
            continue
        if not dialect.detect(payload):
            tried.append(dialect.name)
            continue
        action, why = dialect.translate(payload)
        if action is not None:
            return action, dialect.name, ""
        return None, dialect.name, f"{dialect.label}:{why}"
    scope = f"(只试了 {only})" if only else f"(试过 {', '.join(tried) or '无'})"
    return None, "", f"认不出这是哪一种动作格式{scope}"


# ---------------------------------------------------------------------------
# Anthropic 工具声明
# ---------------------------------------------------------------------------

#: computer 工具的类型串。**这是日期版本化的**,会随上游更新 ——
#: 写死一个旧的会拿到旧行为甚至直接报错,所以留成可配置,并且默认值写明它的来历。
DEFAULT_ANTHROPIC_COMPUTER_TYPE = "computer_20241022"
DEFAULT_ANTHROPIC_BETA = "computer-use-2024-10-22"


def anthropic_tool_schema(
    width: int,
    height: int,
    *,
    display_number: int = 1,
    tool_type: str = DEFAULT_ANTHROPIC_COMPUTER_TYPE,
) -> Dict[str, Any]:
    """按屏幕实际尺寸产出 computer 工具声明。

    ``display_width_px`` / ``display_height_px`` **必须跟真实屏幕一致** ——
    模型是按这个坐标系给点的。声明 1024x768 而实际是 2560x1440,
    它给的每一个坐标都会系统性偏到左上角,而且不会报错。
    Windows 上的 DPI 缩放(125% / 150%)是这类偏移最常见的来源。
    """
    return {
        "type": tool_type,
        "name": "computer",
        "display_width_px": int(width),
        "display_height_px": int(height),
        "display_number": int(display_number),
    }


#: Anthropic **内建工具**的 type → 需要的 beta 旗标。
#:
#: 内建工具(computer / bash / text_editor)跟普通 function 工具不是一回事:
#: 它们没有 ``function`` 包装、没有 ``input_schema``,而是靠一个**日期版本化的
#: type** 让服务端认出来,并且必须同时带上对应的 ``anthropic-beta`` 请求头 ——
#: 少了头,服务端不认这个 type,整个请求 400。
#:
#: 这里登记成表而不是散在 adapter 里的 if:以后加 bash / text_editor 只改这一处。
ANTHROPIC_BUILTIN_TOOL_BETAS: Dict[str, str] = {
    DEFAULT_ANTHROPIC_COMPUTER_TYPE: DEFAULT_ANTHROPIC_BETA,
}


def is_anthropic_native_tool(tool: Any) -> bool:
    """这个工具声明是不是**已经是 Anthropic 形状**(内建工具或已转好的自定义工具)。

    两种都算原生形状:

    * 内建工具 —— 有 ``type`` 且不是 ``"function"``(如 ``computer_20241022``);
    * 已转好的自定义工具 —— 带 ``input_schema``(Anthropic 的字段名,
      OpenAI 那边叫 ``parameters``)。

    判据放在这里而不是 adapter 里:adapter 只负责发请求,"什么形状算原生"
    是这套方言知识的一部分。
    """
    if not isinstance(tool, dict):
        return False
    if "input_schema" in tool:
        return True
    t = tool.get("type")
    return isinstance(t, str) and t != "function" and bool(t)


def anthropic_betas_for_tools(tools: Any) -> List[str]:
    """一批工具声明需要哪些 ``anthropic-beta`` 旗标(去重,保持出现顺序)。

    认不出的 type **不编一个旗标出来** —— 编错了服务端照样 400,
    而且报的错会指向 beta 名字,不是指向"这个工具本来就没登记"。
    """
    betas: List[str] = []
    for tool in tools or []:
        if not isinstance(tool, dict):
            continue
        beta = ANTHROPIC_BUILTIN_TOOL_BETAS.get(tool.get("type") or "")
        if beta and beta not in betas:
            betas.append(beta)
    return betas


def anthropic_tool_for_screenshot(
    screen_b64: str,
    *,
    display_number: int = 1,
    tool_type: str = DEFAULT_ANTHROPIC_COMPUTER_TYPE,
) -> Tuple[Optional[Dict[str, Any]], str]:
    """从**这一张实际截图**量出尺寸,产出 computer 工具声明。返回 ``(声明, 说明)``。

    为什么必须从截图量,而不是问屏幕分辨率:模型给的坐标是相对**它看到的那张图**的。
    截图链路上任何一次缩放(DPI 缩放、传输前压缩、多屏拼接)都会让"屏幕分辨率"和
    "图的像素尺寸"对不上,而声明错了不会报错 —— 它只会让每一次点击都系统性偏移。
    量图是唯一能对上的那个数。

    量不出来就返回 ``(None, 原因)``,**绝不填一个默认分辨率** —— 填了就是在保证偏移。
    """
    if not screen_b64:
        return None, "没有截图"
    try:
        import base64
        import io

        from PIL import Image  # noqa: PLC0415 —— 只有走原生工具这条路才需要

        raw = base64.b64decode(screen_b64, validate=False)
        with Image.open(io.BytesIO(raw)) as im:
            width, height = im.size
    except Exception as exc:  # noqa: BLE001
        return None, f"量不出截图尺寸: {exc}"
    if not width or not height:
        return None, "截图尺寸为 0"
    return (
        anthropic_tool_schema(width, height, display_number=display_number, tool_type=tool_type),
        "",
    )
