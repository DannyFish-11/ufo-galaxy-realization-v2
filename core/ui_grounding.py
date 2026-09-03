"""core/ui_grounding.py — grounding 脑（视觉主看 · 结构化恒辅助）
====================================================================

模型与"操作方法"之间的中间机制:把一句自然语言意图(「点发送」「在输入框打字」)
落到 :class:`UIGraph` 里一个**具体控件 + 规范化动作**上。桌面(UIA)与手机(a11y)
的 planner 都复用这同一个脑——模型无关、设备无关。

视觉与结构的关系(要点)
----------------------
**视觉是主视觉通道,一直在看;结构化控件图一直作为叠加辅助同时提供。**两者恒并存,
不是谁 fallback 谁:模型每一拍都同时拿到 ①截图(看到全部,包括结构漏掉的
Canvas/游戏/自绘控件) + ②结构化控件清单 ``to_prompt()``(精确锚点:名字/坐标/状态)。
结构不是替代视觉,是"给视觉配一副知道每个控件叫什么、在哪、什么状态的眼镜"——
把过去那段"文字描述界面"的提示词,换成精确的结构化节点。

两个方向
--------
1. :func:`resolve_target` —— 意图 → 控件的**确定性快路径**:若结构化图里能无歧义地
   点名目标控件,直接给出确定节点+坐标+动作,省掉一次模型往返;点不准就返回
   ``defer_to_model`` —— 交给多模态模型(它本来就同时看着截图+结构清单)去判断。
   这不是"降级到视觉":视觉从头到尾都在,只是这一步没走确定性捷径。
2. :func:`parse_model_action` —— 模型回复 → 控件:模型(看着截图+结构清单)回
   "[3]" 或 "tap 发送",本函数把它解析回具体节点+动作,闭环执行。
"""

from __future__ import annotations

import re
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel

from core.schemas.ui_element import UIActionKind, UIElementNode, UIGraph


class GroundingStrategy(str, Enum):
    COORDINATE = "coordinate"  # 模型直接给了坐标(视觉定位模型的原生输出) → 走裁决矩阵
    LABEL_EXACT = "label_exact"  # 结构确定性快路径:精确名匹配
    LABEL_SUBSTRING = "label_substring"  # 结构确定性快路径:子串名匹配
    INDEX_REF = "index_ref"  # 模型(看着截图+结构)回了 [n] 序号
    DEFER_TO_MODEL = "defer_to_model"  # 结构点不准 → 交多模态模型(视觉一直在看)判断
    NONE = "none"  # 完全无法定位


class GroundingResult(BaseModel):
    node: Optional[UIElementNode] = None
    action: UIActionKind = UIActionKind.TAP
    text: str = ""  # SET_TEXT 时要输入的文字
    strategy: GroundingStrategy = GroundingStrategy.NONE
    confidence: float = 0.0
    reason: str = ""
    coordinate: Optional["tuple[int, int]"] = None
    """裁决后的最终点击点。仅 COORDINATE 策略下非 None —— 其余策略的落点由 node.bounds 决定。"""
    fusion_source: str = ""
    """裁决来源标签(agreement / tree_override / tree_rescue / vlm_only),与 Android 侧同名。"""

    @property
    def ok(self) -> bool:
        """能否直接落地。

        裁决出坐标也算 —— ``vlm_only`` 那一格没有匹配的树节点,但视觉给的坐标本身
        就是可执行的答案。此前 ``ok`` 只看 node,那一格会被判成"点不准"再去问一遍
        模型,而模型上一轮已经答过了:同一个问题问两遍,拿到同一个答案,再问第三遍。
        """
        return self.node is not None or self.coordinate is not None

    def target_center(self) -> "Optional[tuple[int, int]]":
        """最终落点。裁决坐标优先于节点中心。

        ``agreement`` 那一格里两者都有,而该用的是**视觉那一点** —— 树只是给它加了
        信用,并没有说"应该点控件正中间"。大控件(工具栏、列表行)的中心往往落在
        另一个子控件上,拿中心替换掉模型的落点会点错。
        """
        if self.coordinate is not None:
            return self.coordinate
        if self.node is not None and self.node.bounds is not None:
            return self.node.bounds.center()
        return None


# ── 动词 → 规范化动作(中英)──────────────────────────────────────────────────
_VERB_ACTION = [
    (("双击", "double", "double-click", "double click"), UIActionKind.DOUBLE_TAP),
    (("长按", "long press", "long-press", "longpress"), UIActionKind.LONG_PRESS),
    (("右键", "right click", "right-click", "rightclick"), UIActionKind.RIGHT_CLICK),
    (("输入", "填", "打字", "type", "enter text", "input", "set text"), UIActionKind.SET_TEXT),
    (("清空", "清除", "clear"), UIActionKind.CLEAR),
    (("滑动", "滚动", "scroll", "swipe"), UIActionKind.SCROLL),
    (("聚焦", "focus"), UIActionKind.FOCUS),
    (("打开", "启动", "open", "launch"), UIActionKind.OPEN_APP),
    (("返回", "back"), UIActionKind.BACK),
    (("点", "按", "单击", "tap", "click", "press", "选"), UIActionKind.TAP),
]


def infer_action(instruction: str) -> UIActionKind:
    s = (instruction or "").lower()
    for keys, action in _VERB_ACTION:
        if any(k in s for k in keys):
            return action
    return UIActionKind.TAP


# 目标短语:优先取引号/书名号里的;否则取动词后面的名词块。
_QUOTE = re.compile(r"[「『\"'“‘]([^」』\"'”’]+)[」』\"'”’]")


def extract_target(instruction: str) -> str:
    if not instruction:
        return ""
    m = _QUOTE.search(instruction)
    if m:
        return m.group(1).strip()
    # 去掉常见动词/助词后剩下的当目标(粗略但对短指令够用)
    s = instruction.strip()
    for keys, _ in _VERB_ACTION:
        for k in keys:
            if s.startswith(k):
                s = s[len(k) :]
                break
    for stop in ("按钮", "输入框", "里", "中", "上", "的", "一下", "框", "，", ",", "。"):
        s = s.replace(stop, " ")
    return s.strip()


# SET_TEXT 时把要打的字抽出来。三种写法:
#   1) 动词/"文本="后跟引号: 输入「你好」 · 文本="你好"
#   2) 动词/"文本="后跟裸文本到行尾: 输入:今天天气不错
#   3) 整句只有一处引号(且无其它目标) → 当要打的字
_TYPE_VERBS = r"输入|填|打字|type|input|enter|文本|text"
_TYPE_QUOTED = re.compile(rf"(?:{_TYPE_VERBS})\s*[:：=]?\s*[「『\"'“‘]([^」』\"'”’]+)[」』\"'”’]", re.I)
_TYPE_BARE = re.compile(rf"(?:{_TYPE_VERBS})\s*[:：=]\s*(.+)$", re.I)


def extract_text_to_type(instruction: str) -> str:
    s = instruction or ""
    m = _TYPE_QUOTED.search(s)  # 1) 动词后引号(即便前面还有别的引号目标)
    if m:
        return m.group(1).strip()
    m = _TYPE_BARE.search(s)  # 2) 动词后裸文本
    if m:
        return m.group(1).strip().strip("「』\"'“‘’”")
    quotes = _QUOTE.findall(s)  # 3) 全句唯一引号
    if len(quotes) == 1:
        return quotes[0].strip()
    return ""


def resolve_target(graph: UIGraph, instruction: str, *, action: Optional[UIActionKind] = None) -> GroundingResult:
    """意图 → 控件的确定性快路径。点不准返回 defer_to_model(交给同时看着截图+结构的
    多模态模型;视觉一直在看,不是降级)。"""
    act = action or infer_action(instruction)
    target = extract_target(instruction)
    text = extract_text_to_type(instruction) if act is UIActionKind.SET_TEXT else ""

    if graph.root is None or not target:
        return GroundingResult(
            action=act,
            text=text,
            strategy=GroundingStrategy.DEFER_TO_MODEL,
            reason="无结构树或未抽到目标短语 → 交多模态模型(视觉在看)",
        )

    tl = target.lower()
    interactive = graph.interactive()

    # 1) 精确名
    for n in interactive:
        if f"{n.label} {n.value}".strip().lower() == tl:
            return GroundingResult(
                node=n,
                action=act,
                text=text,
                strategy=GroundingStrategy.LABEL_EXACT,
                confidence=0.98,
                reason=f"精确匹配控件『{n.label}』",
            )
    # 2) 子串名(可交互优先,已在 interactive())
    subs = [n for n in interactive if tl in f"{n.label} {n.value}".strip().lower()]
    if len(subs) == 1:
        n = subs[0]
        return GroundingResult(
            node=n,
            action=act,
            text=text,
            strategy=GroundingStrategy.LABEL_SUBSTRING,
            confidence=0.85,
            reason=f"子串匹配控件『{n.label}』",
        )
    if len(subs) > 1:
        # 多个候选:取名字最短的(最贴合),但置信度降一档,提示可能歧义
        n = min(subs, key=lambda x: len(x.label or x.value or ""))
        return GroundingResult(
            node=n,
            action=act,
            text=text,
            strategy=GroundingStrategy.LABEL_SUBSTRING,
            confidence=0.6,
            reason=f"{len(subs)} 个候选,取最贴合『{n.label}』(可能歧义)",
        )
    # 3) 结构点不准 → 交多模态模型(它一直看着截图;结构里没有可能是第三方封锁 a11y
    #    或 Canvas/自绘,但模型仍能靠视觉操作)
    return GroundingResult(
        action=act,
        text=text,
        strategy=GroundingStrategy.DEFER_TO_MODEL,
        reason=f"结构树里无『{target}』→ 交多模态模型判断(视觉在看)",
    )


# 模型回复里的 [n] 序号引用(to_prompt 的 DFS 序 == graph.flatten() 序)
_INDEX_REF = re.compile(r"\[(\d+)\]")

#: 模型直接给坐标的写法:``(420, 315)`` / ``420,315`` / ``x=420 y=315`` / ``点 420 315``。
#: 视觉定位模型(SeeClick / Qwen-VL / MAI-UI 这一类)的**原生输出就是坐标** —— 此前
#: parse_model_action 只认 [n],模型答对了也用不上,只能落回按名匹配再 defer_to_model。
_COORD_REF = re.compile(
    r"(?:x\s*[=:]\s*)?(?<![\d.])(\d{1,5})(?![\d.])\s*[,，]\s*(?:y\s*[=:]\s*)?(?<![\d.])(\d{1,5})(?![\d.])"
)


def parse_coordinate(reply: str) -> Optional["tuple[int, int]"]:
    """从模型回复里抽出一个坐标点;抽不到返回 None。

    只认**逗号分隔**的一对数 —— 空格分隔会把"点第 3 个 420"之类的句子误读成坐标,
    宁可漏认也不能错认:错认的后果是在无关位置点一下,而漏认只是退回原有路径。
    """
    m = _COORD_REF.search(reply or "")
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def parse_model_action(reply: str, graph: UIGraph, *, action: Optional[UIActionKind] = None) -> GroundingResult:
    """模型回复 → 控件。优先解析 [n] 序号引用;否则回退到按名解析(resolve_target)。"""
    flat: List[UIElementNode] = graph.flatten()

    # 坐标优先于序号:模型给出坐标就说明它在看画面直接定位,这时结构树的角色是
    # **裁决**(救场 / 推翻 / 加信用),不是另一条并行的解析路径。规则本身不写在这里,
    # 全系统只有 core.grounding_arbitration 一份 —— 与 Android 的 GroundingArbiter
    # 共用同一张矩阵、同一组阈值。
    point = parse_coordinate(reply)
    if point is not None:
        return _arbitrate_coordinate(reply, graph, flat, point, action)

    m = _INDEX_REF.search(reply or "")
    if m:
        idx = int(m.group(1))
        if 0 <= idx < len(flat):
            n = flat[idx]
            txt = extract_text_to_type(reply)
            # 动作:显式指定优先;否则有文字且控件可编辑 → SET_TEXT;否则按动词(默认 TAP)
            if action is not None:
                act = action
            elif txt and n.editable:
                act = UIActionKind.SET_TEXT
            else:
                act = infer_action(reply)
            return GroundingResult(
                node=n,
                action=act,
                text=txt if act is UIActionKind.SET_TEXT else "",
                strategy=GroundingStrategy.INDEX_REF,
                confidence=0.95,
                reason=f"模型引用 [{idx}] → 控件『{n.label}』",
            )
    # 无序号 / 越界 → 剥掉方括号引用,当自然语言意图解析
    cleaned = _INDEX_REF.sub(" ", reply or "").strip()
    return resolve_target(graph, cleaned, action=action)


def _arbitrate_coordinate(
    reply: str,
    graph: UIGraph,
    flat: List[UIElementNode],
    point: "tuple[int, int]",
    action: Optional[UIActionKind],
) -> GroundingResult:
    """模型坐标 + 结构树 → 裁决结果。规则来自 core.grounding_arbitration(单一权威)。"""
    from core.grounding_arbitration import VisionPoint, fuse

    x, y = point
    fused = fuse(
        reply or "",
        VisionPoint(x=x, y=y, confidence=0.9),
        flat,
        screen=(graph.screen_width, graph.screen_height),
    )
    txt = extract_text_to_type(reply)
    node = fused.node if isinstance(fused.node, UIElementNode) else None
    if action is not None:
        act = action
    elif txt and node is not None and node.editable:
        act = UIActionKind.SET_TEXT
    else:
        act = infer_action(reply)
    return GroundingResult(
        node=node,
        action=act,
        text=txt if act is UIActionKind.SET_TEXT else "",
        strategy=GroundingStrategy.COORDINATE,
        confidence=fused.confidence,
        coordinate=(fused.x, fused.y),
        fusion_source=fused.source,
        reason=f"模型给出坐标({x},{y}) → 裁决 {fused.source} → ({fused.x},{fused.y})",
    )


def build_grounding_prompt(graph: UIGraph, instruction: str) -> str:
    """结构化辅助提示——**与截图一同发给模型**(视觉主看,本文本是叠加辅助)。

    模型同时拥有画面(看到全部)和这份结构化控件清单(精确锚点)。故指示模型:
    优先用序号 [n] 精确引用已识别控件;清单里没有(但画面上有)的,直接描述位置。"""
    return (
        "【结构化辅助】以下是当前画面上已精确识别的可交互控件(与你看到的截图对应);"
        "画面里可能还有未被结构识别到的控件,以你所见为准。\n"
        f"{graph.to_prompt()}\n\n"
        f"用户意图:{instruction}\n"
        '优先回复要操作控件的序号 [n](精确);若需输入文字,追加 文本="..."。'
        "若目标控件在清单里没有、但画面上有,直接描述其位置。"
    )
