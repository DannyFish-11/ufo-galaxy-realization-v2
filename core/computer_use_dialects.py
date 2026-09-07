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
DIALECT_ANTHROPIC_TOOLSET = "anthropic_toolset"
DIALECT_OPENAI = "openai"

__all__ = [
    "DIALECT_ANTHROPIC",
    "DIALECT_ANTHROPIC_TOOLSET",
    "DIALECT_NATIVE",
    "DIALECT_OPENAI",
    "translate_sequence",
    "TOOLSET_NAME_FIELD",
    "TOOLSET_NAME_COMPUTER",
    "ActionDialect",
    "DIALECTS",
    "anthropic_tool_schema",
    "ANTHROPIC_TOOL_VERSIONS",
    "AnthropicToolVersion",
    "SHAPE_ACTION_IN_INPUT",
    "SHAPE_TOOLSET_MEMBER",
    "DEFAULT_ANTHROPIC_COMPUTER_TYPE",
    "LEGACY_ANTHROPIC_COMPUTER_TYPE",
    "anthropic_beta_for_type",
    "is_anthropic_native_tool",
    "anthropic_betas_for_tools",
    "anthropic_tool_for_screenshot",
    "measure_screenshot",
    "map_action_to_screen",
    "COORD_SPACE_FIELD",
    "COORD_SPACE_SCREEN",
    "COORD_SPACE_SCREENSHOT",
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
# anthropic toolset —— 20260801 起:动作名就是 tool_use 的 name
# ---------------------------------------------------------------------------

#: 成员工具名 → 本仓规范动作名。
#:
#: ``None`` 是**刻意**的:那是"上游确实有这个成员,但本仓的执行侧没有对应动作"。
#: 跟"没见过这个名字"必须分开 —— 前者该说"本仓还不支持",后者该说"认不出",
#: 两句话指向完全不同的下一步(改本仓 / 查上游)。
_TOOLSET_MEMBER_ACTION: Dict[str, Optional[str]] = {
    "left_click": "click",
    "right_click": "right_click",
    "double_click": "double_click",
    "mouse_move": "move",
    "left_click_drag": "drag",
    "scroll": "scroll",
    "type": "type",
    "key": "press_key",
    "wait": "wait",
    # screenshot 是"想再看一眼"。本仓循环每一步都会重新截图,所以等一拍即可。
    # 这是转义,不是等价映射。
    "screenshot": "wait",
    # 下面这些上游有、本仓执行侧没有(见 computer_use_loop.ALLOWED_ACTIONS)。
    # 登记成 None 而不是不写,是为了让消息说得出"是本仓缺,不是没认出来"。
    "middle_click": None,
    "triple_click": None,
    "hold_key": None,
    "left_mouse_down": None,
    "left_mouse_up": None,
    "cursor_position": None,
    "zoom": None,
}

#: toolset 块上的这个字段是它的身份证 —— 回传 tool_result 时也必须原样带上。
TOOLSET_NAME_FIELD = "toolset_name"
TOOLSET_NAME_COMPUTER = "computer"


def _toolset_find_block(payload: Any) -> Optional[Dict[str, Any]]:
    """挑出带 ``toolset_name`` 的 tool_use 块。"""
    obj: Any = payload
    if isinstance(obj, str):
        obj = _first_json_object(obj)
    if not isinstance(obj, dict):
        return None
    candidates: List[Dict[str, Any]] = []
    if obj.get("type") == "tool_use":
        candidates.append(obj)
    content = obj.get("content")
    if isinstance(content, list):
        candidates.extend(b for b in content if isinstance(b, dict) and b.get("type") == "tool_use")
    for block in candidates:
        if block.get(TOOLSET_NAME_FIELD):
            return block
    return None


def _toolset_detect(payload: Any) -> bool:
    return _toolset_find_block(payload) is not None


def _toolset_translate(payload: Any) -> Tuple[Optional[Dict[str, Any]], str]:
    block = _toolset_find_block(payload)
    if block is None:
        return None, "响应里没有带 toolset_name 的 tool_use 块"

    member = str(block.get("name", "")).strip().lower()
    if not member:
        return None, "tool_use 块没有成员工具名"
    if member not in _TOOLSET_MEMBER_ACTION:
        return None, f"不认识的 toolset 成员: {member!r}"
    mapped = _TOOLSET_MEMBER_ACTION[member]
    if mapped is None:
        return None, f"上游成员 {member!r} 本仓执行侧没有对应动作(见 ALLOWED_ACTIONS)"

    tool_input = block.get("input")
    if not isinstance(tool_input, dict):
        tool_input = {}

    out: Dict[str, Any] = {"action": mapped, "reason": f"anthropic_toolset:{member}"}
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
    if mapped == "wait" and member == "screenshot":
        out["seconds"] = 0.5
    return out, ""


# ---------------------------------------------------------------------------
# openai —— Responses API 的 computer_call
# ---------------------------------------------------------------------------
#
# 形状跟两家 Anthropic 都不一样:
#
#   {"type": "computer_call", "call_id": "call_002", "status": "completed",
#    "actions": [{"type": "click", "button": "left", "x": 405, "y": 157},
#                {"type": "type", "text": "penguin"}]}
#
# 三处要点:
#   1. ``actions`` 是**有序数组**,一次可能给好几步,要按顺序执行 ——
#      只取第一个就是在静默丢动作,所以这一家走 :func:`translate_sequence`。
#   2. 坐标是**扁平的 x / y**,不是 ``coordinate: [x, y]``。
#   3. ``call_id`` 回传 ``computer_call_output`` 时必须原样带回。

#: OpenAI 动作名 → 本仓规范动作名。``None`` 同上:上游有、本仓执行侧没有。
_OPENAI_ACTION: Dict[str, Optional[str]] = {
    "click": "click",
    "double_click": "double_click",
    "drag": "drag",
    "move": "move",
    "scroll": "scroll",
    "keypress": "press_key",
    "type": "type",
    "wait": "wait",
    "screenshot": "wait",  # 同样是转义:本仓每一步都会重新截图
}


def _openai_find_call(payload: Any) -> Optional[Dict[str, Any]]:
    obj: Any = payload
    if isinstance(obj, str):
        obj = _first_json_object(obj)
    if not isinstance(obj, dict):
        return None
    if obj.get("type") == "computer_call":
        return obj
    output = obj.get("output")
    if isinstance(output, list):
        for item in output:
            if isinstance(item, dict) and item.get("type") == "computer_call":
                return item
    return None


def _openai_detect(payload: Any) -> bool:
    return _openai_find_call(payload) is not None


def _openai_one_action(raw: Any) -> Tuple[Optional[Dict[str, Any]], str]:
    """``actions`` 里的一项 → 规范动作。"""
    if not isinstance(raw, dict):
        return None, "actions 里有一项不是对象"
    kind = str(raw.get("type", "")).strip().lower()
    if not kind:
        return None, "actions 里有一项没有 type"
    if kind not in _OPENAI_ACTION:
        return None, f"不认识的 OpenAI 动作: {kind!r}"
    mapped = _OPENAI_ACTION[kind]
    if mapped is None:
        return None, f"上游动作 {kind!r} 本仓执行侧没有对应动作"

    # button 决定的是**哪一种点击**,不是一个参数 —— 右键在本仓是另一个动作名。
    if kind == "click":
        button = str(raw.get("button", "left")).strip().lower()
        if button == "right":
            mapped = "right_click"
        elif button not in ("left", ""):
            return None, f"本仓执行侧没有 {button!r} 键点击"

    out: Dict[str, Any] = {"action": mapped, "reason": f"openai:{kind}"}
    x, y = raw.get("x"), raw.get("y")
    if x is not None and y is not None:
        try:
            out["x"], out["y"] = int(x), int(y)
        except (TypeError, ValueError):
            return None, "x / y 不是整数"

    if mapped == "type":
        out["text"] = str(raw.get("text", ""))
    if mapped == "press_key":
        # 字段名上游文档没给到字段级 schema(``keys`` / ``text`` / ``key`` 都见过),
        # 所以**只认真的取到的那个**,取不到就说取不到 —— 不替它编一个键名。
        keys = raw.get("keys")
        if isinstance(keys, (list, tuple)) and keys:
            out["key"] = "+".join(str(k) for k in keys)
        elif raw.get("text") or raw.get("key"):
            out["key"] = str(raw.get("text") or raw.get("key"))
        else:
            return None, "keypress 没有可识别的按键字段(上游未公开字段级 schema)"
    if mapped == "scroll":
        for field in ("scroll_x", "scroll_y", "amount"):
            if field in raw:
                out[field if field != "amount" else "amount"] = raw.get(field)
    if mapped == "drag":
        path = raw.get("path")
        pts: List[Tuple[int, int]] = []
        if isinstance(path, (list, tuple)):
            for pt in path:
                if isinstance(pt, dict) and pt.get("x") is not None and pt.get("y") is not None:
                    try:
                        pts.append((int(pt["x"]), int(pt["y"])))
                    except (TypeError, ValueError):
                        return None, "drag 路径里的坐标不是整数"
                else:
                    coord = _coord_pair(pt)
                    if coord is None:
                        return None, "drag 路径的点形状认不出"
                    pts.append(coord)
        if len(pts) >= 2:
            out.pop("x", None)
            out.pop("y", None)
            out.update({"from_x": pts[0][0], "from_y": pts[0][1], "to_x": pts[-1][0], "to_y": pts[-1][1]})
        else:
            return None, "drag 缺可用的起止点(上游未公开字段级 schema)"
    if kind == "screenshot":
        out["seconds"] = 0.5
    return out, ""


def _openai_translate_all(payload: Any) -> Tuple[List[Dict[str, Any]], str]:
    call = _openai_find_call(payload)
    if call is None:
        return [], "响应里没有 computer_call"
    actions = call.get("actions")
    if not isinstance(actions, list) or not actions:
        return [], "computer_call 里没有 actions 数组"
    call_id = call.get("call_id")
    out: List[Dict[str, Any]] = []
    for raw in actions:
        action, why = _openai_one_action(raw)
        if action is None:
            # 一项翻不出来就整条不执行。**不跳过继续** —— 顺序执行的语义下,
            # 跳掉中间一步,后面几步作用在错误的界面状态上,比什么都不做危险。
            return [], f"第 {len(out) + 1} 个动作翻不出来: {why}"
        if call_id:
            action["call_id"] = call_id
        out.append(action)
    return out, ""


def _openai_translate(payload: Any) -> Tuple[Optional[Dict[str, Any]], str]:
    actions, why = _openai_translate_all(payload)
    if not actions:
        return None, why
    return actions[0], ""


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
    #: 一次给出**多个**有序动作的方言(OpenAI 的 ``actions`` 数组)在这里给出
    #: 整串;留空表示这一家一次只给一个动作。有它就不会静默丢掉后面几步。
    translate_all: Optional[Callable[[Any], Tuple[List[Dict[str, Any]], str]]] = None


DIALECTS: List[ActionDialect] = [
    # 顺序 = 从**最具体**到最宽松。谁先认出来算谁的,所以更具体的必须排前面。
    #
    # anthropic_toolset 必须排在 anthropic 之前:两者都是 tool_use 块,
    # toolset 只是**多**一个 toolset_name 字段。反过来排的话,20260801 的响应
    # 会先被老版方言接住,然后因为 input 里没有 action 而报"没有 action" ——
    # 一句指向错误方向的报错,比认不出更难查。
    ActionDialect(
        name=DIALECT_ANTHROPIC_TOOLSET,
        label="Anthropic computer toolset (20260801+)",
        detect=_toolset_detect,
        translate=_toolset_translate,
    ),
    ActionDialect(
        name=DIALECT_OPENAI,
        label="OpenAI Responses computer_call",
        detect=_openai_detect,
        translate=_openai_translate,
        translate_all=_openai_translate_all,
    ),
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


def translate_sequence(payload: Any, *, only: Optional[str] = None) -> Tuple[List[Dict[str, Any]], str, str]:
    """认出方言,翻成**一串有序的**规范动作。返回 ``(动作清单, 方言名, 说不出来的原因)``。

    为什么是清单而不是单个动作:OpenAI 的 ``computer_call``
    一次可能给好几步(``actions`` 是有序数组,要按顺序执行)。只取第一个就是在
    **静默丢动作** —— 界面被改了一半,模型下一轮看到的画面对不上它以为的状态,
    然后开始纠正一个根本不存在的问题。

    一次只给一个动作的方言,返回的清单长度就是 1;两边用同一个出口。
    """
    tried: List[str] = []
    for dialect in DIALECTS:
        if only is not None and dialect.name != only:
            continue
        if not dialect.detect(payload):
            tried.append(dialect.name)
            continue
        if dialect.translate_all is not None:
            actions, why = dialect.translate_all(payload)
            if actions:
                return actions, dialect.name, ""
            return [], dialect.name, f"{dialect.label}:{why}"
        action, why = dialect.translate(payload)
        if action is not None:
            return [action], dialect.name, ""
        return [], dialect.name, f"{dialect.label}:{why}"
    scope = f"(只试了 {only})" if only else f"(试过 {', '.join(tried) or '无'})"
    return [], "", f"认不出这是哪一种动作格式{scope}"


# ---------------------------------------------------------------------------
# Anthropic computer 工具:版本串登记表
# ---------------------------------------------------------------------------
#
# 这一段是**时效性最强**的地方,所以做成表而不是常量:上游一年里换了四代,
# 每一代的声明形状、要不要 beta 头、响应长什么样都不一样。写死一个就等着过期。
#
# 2026-09 的事实(来自 platform.claude.com 的 computer use 文档与迁移章节):
#
#   type                        beta 头                      响应形状
#   --------------------------  ---------------------------  ----------------
#   computer_toolset_20260801   不需要                        成员工具名在 name
#   computer_20251124           computer-use-2025-11-24      动作在 input.action
#   computer_20250124           computer-use-2025-01-24      动作在 input.action
#   computer_20241022           computer-use-2024-10-22      动作在 input.action
#
# **"不需要 beta 头"和"这个 type 没见过"是两回事**,所以 beta 用 ``None``
# 表示前者,查不到条目表示后者 —— 两者都返回空清单的话,一个没登记的新版本串
# 会被当成"不用带头"发出去,然后收到一个指向 beta 名字的 400,而真正的问题是
# 这张表没更新。

#: 响应形状:动作名在 ``input.action`` 里(20241022 / 20250124 / 20251124)。
SHAPE_ACTION_IN_INPUT = "action_in_input"
#: 响应形状:动作名就是 ``tool_use`` 块的 ``name``(成员工具),``input`` 里**没有**
#: ``action`` 字段,块上另带 ``toolset_name``。20260801 起是这一种。
SHAPE_TOOLSET_MEMBER = "toolset_member"


@dataclass(frozen=True)
class AnthropicToolVersion:
    """一代 computer 工具的全部事实。

    Attributes:
        beta: 需要的 ``anthropic-beta`` 值;``None`` 表示**不需要头**(不是"不知道")。
        shape: 响应形状,见上面两个常量。
        declares_display: 声明里能不能写 ``display_width_px`` 这些。
            20260801 起**不能** —— 塞了会被 ``invalid_request_error`` 拒掉。
    """

    beta: Optional[str]
    shape: str
    declares_display: bool


ANTHROPIC_TOOL_VERSIONS: Dict[str, AnthropicToolVersion] = {
    "computer_toolset_20260801": AnthropicToolVersion(None, SHAPE_TOOLSET_MEMBER, False),
    "computer_20251124": AnthropicToolVersion("computer-use-2025-11-24", SHAPE_ACTION_IN_INPUT, True),
    "computer_20250124": AnthropicToolVersion("computer-use-2025-01-24", SHAPE_ACTION_IN_INPUT, True),
    "computer_20241022": AnthropicToolVersion("computer-use-2024-10-22", SHAPE_ACTION_IN_INPUT, True),
}

#: 默认用最新那一代。
#:
#: 上一版这里默认 ``computer_20241022`` —— 那是 2024 年 10 月的最初 beta,
#: 到 2026-09 已经落后两年,连 ``scroll`` / ``wait`` 都没有。默认值指向一个
#: 早就不该用的版本,比没有默认值更糟:它能跑,只是少一半动作,而且不报错。
DEFAULT_ANTHROPIC_COMPUTER_TYPE = "computer_toolset_20260801"

#: 老版路径的默认(平台还没上 toolset 时退回这一代,不要再退到 20241022)。
LEGACY_ANTHROPIC_COMPUTER_TYPE = "computer_20251124"


def anthropic_tool_schema(
    width: Optional[int] = None,
    height: Optional[int] = None,
    *,
    display_number: int = 1,
    tool_type: str = DEFAULT_ANTHROPIC_COMPUTER_TYPE,
    enable_zoom: Optional[bool] = None,
) -> Dict[str, Any]:
    """按版本产出 computer 工具声明。

    两代的声明形状**根本不同**,所以由登记表决定,不由调用方记着:

    * ``computer_toolset_20260801`` —— 就一行 ``{"type": ...}``。
      塞 ``name`` / ``display_width_px`` / ``display_height_px`` /
      ``display_number`` 会被 ``invalid_request_error`` 拒掉。
      要关掉 zoom 用 ``configs``。
    * 老版(``computer_20251124`` 等)—— 必须带 ``name`` 与屏幕尺寸。
      ``display_width_px`` / ``display_height_px`` **必须跟你真正发出去的那张截图
      一致**:模型是按那张图的像素空间给坐标的。声明 1024x768 而图是 2560x1440,
      每一个坐标都会系统性偏,而且不会报错。

    Raises:
        ValueError: 老版路径没给尺寸,或 ``tool_type`` 不在登记表里。
            **不给一个默认分辨率** —— 猜一个尺寸等于保证每一次点击都偏。
    """
    version = ANTHROPIC_TOOL_VERSIONS.get(tool_type)
    if version is None:
        raise ValueError(f"没登记过的 computer 工具版本串: {tool_type!r} —— 先补 ANTHROPIC_TOOL_VERSIONS")

    if not version.declares_display:
        tool: Dict[str, Any] = {"type": tool_type}
        if enable_zoom is False:
            tool["configs"] = {"zoom": {"enabled": False}}
        return tool

    if not width or not height:
        raise ValueError(f"{tool_type} 必须声明屏幕尺寸(要跟发出去的截图一致),不能留空")
    return {
        "type": tool_type,
        "name": "computer",
        "display_width_px": int(width),
        "display_height_px": int(height),
        "display_number": int(display_number),
    }


def anthropic_beta_for_type(tool_type: str) -> Tuple[Optional[str], bool]:
    """``(beta 值, 这个版本串认不认识)``。

    分开返回是有必要的:``(None, True)`` 是"这一代不需要头",
    ``(None, False)`` 是"这张表里没有它" —— 后者该当成配置错误,不是"不用带头"。
    """
    version = ANTHROPIC_TOOL_VERSIONS.get(tool_type or "")
    if version is None:
        return None, False
    return version.beta, True


def anthropic_betas_for_tools(tools: Any) -> List[str]:
    """一批工具声明需要哪些 ``anthropic-beta`` 旗标(去重,保持出现顺序)。

    没登记的 type **不编一个旗标出来**,但会留痕 —— 编错了服务端照样 400,
    而且报的错会指向 beta 名字,不是指向"这张表该更新了"。
    """
    betas: List[str] = []
    for tool in tools or []:
        if not isinstance(tool, dict):
            continue
        raw_type = tool.get("type") or ""
        if not raw_type or raw_type == "function":
            continue
        beta, known = anthropic_beta_for_type(raw_type)
        if not known:
            logger.warning("没登记过的 computer 工具版本串 %r —— 不替它编 beta 头,请更新登记表", raw_type)
            continue
        if beta and beta not in betas:
            betas.append(beta)
    return betas


def is_anthropic_native_tool(tool: Any) -> bool:
    """这个工具声明是不是**已经是 Anthropic 形状**(内建工具或已转好的自定义工具)。

    两种都算原生形状:

    * 内建工具 —— 有 ``type`` 且不是 ``"function"``(如 ``computer_toolset_20260801``);
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


def measure_screenshot(screen_b64: str) -> Tuple[Optional[Tuple[int, int]], str]:
    """量出这张截图的像素尺寸。返回 ``((宽, 高), "")`` 或 ``(None, 原因)``。

    量不出来就是量不出来 —— **不回一个默认分辨率**。
    """
    if not screen_b64:
        return None, "没有截图"
    try:
        import base64
        import io

        from PIL import Image  # noqa: PLC0415 —— 只有走原生工具/坐标换算才需要

        raw = base64.b64decode(screen_b64, validate=False)
        with Image.open(io.BytesIO(raw)) as im:
            width, height = im.size
    except Exception as exc:  # noqa: BLE001
        return None, f"量不出截图尺寸: {exc}"
    if not width or not height:
        return None, "截图尺寸为 0"
    return (width, height), ""


def anthropic_tool_for_screenshot(
    screen_b64: str,
    *,
    display_number: int = 1,
    tool_type: str = DEFAULT_ANTHROPIC_COMPUTER_TYPE,
    enable_zoom: Optional[bool] = None,
) -> Tuple[Optional[Dict[str, Any]], str]:
    """产出这一步要用的 computer 工具声明。返回 ``(声明, 说明)``。

    新版 toolset **不声明尺寸**(声明里塞尺寸会被拒),所以那条路不需要量图,
    也就不会因为量不出来而声明不出去。

    老版路径必须量:``display_width_px`` / ``display_height_px`` 要跟你真正发出去的
    那张截图一致 —— 模型是按那张图的像素空间给坐标的。量不出来就不声明,
    **绝不填一个默认分辨率**:填了不会报错,只会让每一次点击都系统性偏。
    """
    version = ANTHROPIC_TOOL_VERSIONS.get(tool_type)
    if version is None:
        return None, f"没登记过的 computer 工具版本串: {tool_type!r}"
    if not version.declares_display:
        return anthropic_tool_schema(tool_type=tool_type, enable_zoom=enable_zoom), ""
    size, why = measure_screenshot(screen_b64)
    if size is None:
        return None, why
    return (
        anthropic_tool_schema(size[0], size[1], display_number=display_number, tool_type=tool_type),
        "",
    )


# ---------------------------------------------------------------------------
# 坐标空间:模型看的是截图,手点的是屏幕
# ---------------------------------------------------------------------------
#
# 两家上游都用加粗写了同一件事,而且都明说**不替你换算**:
#
#   "Coordinates are in the pixel space of the screenshots you return,
#    with the origin at the top left."
#   "If you downscale a screenshot, map the model's coordinates back to the
#    environment's coordinate space before executing actions."
#
# 也就是说:模型给的 (x, y) 属于**那张图**,而 pyautogui 点的是**真实屏幕**。
# 两者尺寸一旦不同,每一次点击都按同一个比例偏 —— 而且不会报错,只是点不中。
#
# 本仓的截图来自感知层,上游采集端有没有缩放**这里并不知道**。所以:
# 知道两边尺寸才换算;不知道就**原样放行并说明**,而不是假设 1:1 后闷头点。
#
# 尺寸对不上最常见的两个来源:
#   1. **Windows 的 DPI 缩放**(125% / 150%)—— 截图拿到的是物理像素,而不少
#      自动化接口按逻辑像素点,两者差的就是那个缩放比;
#   2. 采集端为了省带宽把图缩了,却没人把这件事往下传。
# 两种都不会报错,只会让每一次点击都按同一个比例偏 —— 这类偏移最难查,
# 因为界面看着"差不多点对了",只是总差一点。

#: 记在动作里的坐标空间标注。有它才看得出这一步的坐标到底是谁的像素。
COORD_SPACE_FIELD = "coord_space"
COORD_SPACE_SCREENSHOT = "screenshot"
COORD_SPACE_SCREEN = "screen"

_COORD_FIELDS = (("x", "y"), ("from_x", "from_y"), ("to_x", "to_y"))


def map_action_to_screen(
    action: Dict[str, Any],
    *,
    shot_size: Optional[Tuple[int, int]],
    screen_size: Optional[Tuple[int, int]],
) -> Tuple[Dict[str, Any], str]:
    """把截图像素空间的坐标投到真实屏幕。返回 ``(动作, 说明)``。

    三种情况,**结果必须区分得出来**:

    * 两边尺寸都知道且相同 → 原样,标 ``coord_space=screen``;
    * 两边都知道但不同 → 按比例换算,标 ``coord_space=screen``,说明里记下比例;
    * 有一边不知道 → **不换算**,标 ``coord_space=screenshot`` 并说明为什么。
      这一条是重点:假设 1:1 然后闷头点,错了也看不出来是坐标的事。

    只动坐标字段,其它一律不碰。
    """
    out = dict(action)
    if not shot_size or not screen_size:
        out[COORD_SPACE_FIELD] = COORD_SPACE_SCREENSHOT
        which = "截图" if not shot_size else "屏幕"
        return out, f"不知道{which}尺寸,坐标未换算(仍是截图像素空间)"

    sw, sh = shot_size
    dw, dh = screen_size
    if not sw or not sh:
        out[COORD_SPACE_FIELD] = COORD_SPACE_SCREENSHOT
        return out, "截图尺寸为 0,坐标未换算"

    out[COORD_SPACE_FIELD] = COORD_SPACE_SCREEN
    if (sw, sh) == (dw, dh):
        return out, ""

    fx, fy = dw / sw, dh / sh
    for kx, ky in _COORD_FIELDS:
        if kx in out and ky in out:
            try:
                out[kx] = int(round(float(out[kx]) * fx))
                out[ky] = int(round(float(out[ky]) * fy))
            except (TypeError, ValueError):
                out[COORD_SPACE_FIELD] = COORD_SPACE_SCREENSHOT
                return out, f"坐标字段 {kx}/{ky} 不是数字,整条都没换算"
    return out, f"截图 {sw}x{sh} → 屏幕 {dw}x{dh}(x×{fx:.4f}, y×{fy:.4f})"
