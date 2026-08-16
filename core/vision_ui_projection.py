#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/vision_ui_projection.py — 视觉理解结果 → 统一控件契约
============================================================

**Stage B：让 ``vision_pipeline`` 成为 ``UIGraph`` 的第二个生产者，而不是第二套形状。**

要解决的问题
------------
``core/vision_pipeline.py`` 已经能从一张截图里解出 OCR 文本框与 GUI 元素树（四级
降级：DeepSeek OCR 2 → Gemini → Qwen3-VL → Tesseract+规则）。但它产出的是自己的
``VisionResult``，而 grounding 那条链（``ui_grounding`` / ``grounded_planner`` /
``/api/v1/ui/act``）吃的是 :class:`~core.schemas.ui_element.UIGraph`。

于是同一件事有了两套表示：契约里 ``UISource.VISION`` 与 ``UISource.OCR`` 两个来源
**声明了却零生产者**，而真正能产出它们的模块只挂在两个 HTTP 端点上，主链路走不到。
本模块补的就是中间这一步投影。

三条设计约束
------------
1. **纯投影，不改 vision_pipeline 任何行为。** 只加出口，不动它的降级链、不动它的
   调用方。回滚等于删掉本文件。
2. **失败必须可观测。** 投影不出东西时返回**空图并说明原因**，而不是静默返回
   ``None``——"识别不出控件"与"投影坏了"是两件事，混成一个空值就无从排查。
3. **不与结构树竞争。** 产出的图 ``source=VISION``，交由
   :meth:`UIGraph.merge` 融进结构图：视觉给结构补它漏掉的控件（Canvas、自绘、
   第三方封锁无障碍的界面），结构给视觉补精确边界与状态。**两条腿一起走，
   不是谁 fallback 谁**——这是 ``ui_element`` 契约本身写下的立场。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from core.schemas.ui_element import UIActionKind, UIBounds, UIElementNode, UIGraph, UISource

logger = logging.getLogger("Galaxy.VisionUIProjection")

__all__ = [
    "VISION_PROJECTION_IS_ADDITIVE_POLICY",
    "VISION_NODES_ARE_NEVER_CERTAIN_POLICY",
    "ELEMENT_ROLE_MAP",
    "INTERACTION_ACTION_MAP",
    "project_vision_result",
    "project_and_merge",
]


# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

VISION_PROJECTION_IS_ADDITIVE_POLICY: str = (
    "VISION_UI_PROJECTION::POLICY_1: "
    "This module only projects; it never changes how vision_pipeline recognises "
    "anything and never becomes a second recogniser.  Rolling it back is deleting "
    "the file — that property is what makes it safe to wire into the live path."
)

VISION_NODES_ARE_NEVER_CERTAIN_POLICY: str = (
    "VISION_UI_PROJECTION::POLICY_2: "
    "Projected nodes carry source=VISION/OCR and the recogniser's own confidence, "
    "never 1.0.  A structural node from UIA/a11y is what the system reports about "
    "itself; a vision node is an inference about pixels.  Flattening that "
    "distinction would let a guess outrank a fact during merge."
)


# ---------------------------------------------------------------------------
# Vocabulary mapping
# ---------------------------------------------------------------------------

ELEMENT_ROLE_MAP: Dict[str, str] = {
    "button": "button",
    "text": "text",
    "input": "edit",
    "image": "image",
    "icon": "button",
    "checkbox": "checkbox",
    "radio": "radio",
    "toggle": "switch",
    "slider": "slider",
    "dropdown": "combobox",
    "tab": "tab",
    "link": "link",
    "menu": "menu",
    "toolbar": "toolbar",
    "status_bar": "statusbar",
    "navigation": "navigation",
    "dialog": "dialog",
    "list_item": "listitem",
    "card": "group",
    "container": "group",
    # 识别器自己都说不上来是什么 —— 就照实叫 unknown。映射成 text 会让下游以为
    # 这是一段文字(不可交互),而它可能恰恰是个能点的东西。
    "unknown": "unknown",
}
"""``ElementType`` → 契约里的规范化 role。

``icon`` 落到 ``button``:图标在界面上就是可点的按钮,给它一个独有 role 只会让
下游多一处分支。``card``/``container`` 落到 ``group``——它们是容器,不是可交互控件。"""

INTERACTION_ACTION_MAP: Dict[str, UIActionKind] = {
    "click": UIActionKind.TAP,
    "long_press": UIActionKind.LONG_PRESS,
    "type": UIActionKind.SET_TEXT,
    "scroll": UIActionKind.SCROLL,
    "swipe": UIActionKind.SWIPE,
    "drag": UIActionKind.SWIPE,
    "toggle": UIActionKind.TAP,
    "select": UIActionKind.TAP,
}
"""``InteractionType`` → ``UIActionKind``。``none`` 不在表里:它表示"不可交互",
映射成任何动作都是谎报。"""

_EDITABLE_ROLES = frozenset({"edit"})
_OCR_DEDUP_IOU = 0.55
"""OCR 文本框与已识别 GUI 元素的重叠阈值。

超过即认为这段文字就是那个控件的文案,不再单独建节点——否则同一个按钮会以
"按钮"和"文字"两个节点出现两次,模型引用 [n] 时看到两个都对的候选。"""


def _enum_value(raw: Any) -> str:
    """Enum 或裸串都收——调用方可能已经把 VisionResult 序列化过一轮。"""
    return str(getattr(raw, "value", raw) or "").strip().lower()


def _bounds_of(bbox: Any) -> Optional[UIBounds]:
    """坐标框 → ``UIBounds``；给不出**可用**锚点时返回 None 并说明。

    两处不能用 ``getattr(..., 0)` 兜底糊过去：

    * 对象根本没有 x/y/width/height —— 那样兜底会造出 ``(0,0,0x0)``，
      也就是告诉模型"这个控件在屏幕左上角"。**猜错的坐标比没有坐标危险**：
      没有坐标时 grounding 会 defer 给模型看画面，有个错坐标则会直接点过去。
    * 面积为零 —— 同理，零面积框点不中任何东西，却看起来像个有效锚点。
    """
    if bbox is None:
        return None
    missing = [attr for attr in ("x", "y", "width", "height") if not hasattr(bbox, attr)]
    if missing:
        logger.warning("视觉元素的边界框缺少 %s,该节点将没有坐标锚点(不构造零值框)", "/".join(missing))
        return None
    try:
        bounds = UIBounds(
            x=int(getattr(bbox, "x", 0) or 0),
            y=int(getattr(bbox, "y", 0) or 0),
            width=int(getattr(bbox, "width", 0) or 0),
            height=int(getattr(bbox, "height", 0) or 0),
        )
    except (TypeError, ValueError) as exc:
        logger.warning("视觉元素的边界框无法解析(%s),该节点将没有坐标锚点", exc)
        return None
    if bounds.area() <= 0:
        logger.warning("视觉元素给出零面积边界框 @(%d,%d),不作为坐标锚点", bounds.x, bounds.y)
        return None
    return bounds


def _actions_of(element: Any) -> List[UIActionKind]:
    out: List[UIActionKind] = []
    for it in getattr(element, "interaction_types", None) or []:
        mapped = INTERACTION_ACTION_MAP.get(_enum_value(it))
        if mapped is not None and mapped not in out:
            out.append(mapped)
    return out


def _project_element(element: Any) -> Optional[UIElementNode]:
    """一个 ``GUIElement`` → 一个 ``UIElementNode``(含子树)。"""
    role = ELEMENT_ROLE_MAP.get(_enum_value(getattr(element, "element_type", "")), "text")
    actions = _actions_of(element)
    interactable = bool(getattr(element, "interactable", False))
    try:
        confidence = float(getattr(element, "confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0

    node = UIElementNode(
        node_id=str(getattr(element, "element_id", "") or ""),
        role=role,
        label=str(getattr(element, "text", "") or ""),
        bounds=_bounds_of(getattr(element, "bbox", None)),
        clickable=interactable and UIActionKind.SET_TEXT not in actions,
        editable=role in _EDITABLE_ROLES or UIActionKind.SET_TEXT in actions,
        scrollable=UIActionKind.SCROLL in actions or UIActionKind.SWIPE in actions,
        actions=actions,
        source=UISource.VISION,
        # POLICY_2:视觉节点永远带识别器自己的置信度,不冒充结构节点的 1.0。
        confidence=min(max(confidence, 0.0), 0.999),
    )
    for child in getattr(element, "children", None) or []:
        projected = _project_element(child)
        if projected is not None:
            node.children.append(projected)
    return node


def _project_ocr_word(word: Any) -> Optional[UIElementNode]:
    text = str(getattr(word, "text", "") or "").strip()
    if not text:
        return None
    bounds = _bounds_of(getattr(word, "bbox", None))
    try:
        confidence = float(getattr(word, "confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    return UIElementNode(
        role="text",
        label=text,
        bounds=bounds,
        clickable=False,
        source=UISource.OCR,
        confidence=min(max(confidence, 0.0), 0.999),
    )


def _covered_by(bounds: Optional[UIBounds], others: List[UIElementNode]) -> bool:
    if bounds is None:
        return False
    for node in others:
        if node.bounds is not None and node.bounds.iou(bounds) >= _OCR_DEDUP_IOU:
            return True
    return False


def project_vision_result(
    result: Any,
    *,
    device_id: str = "",
    screen_width: int = 0,
    screen_height: int = 0,
    include_ocr: bool = True,
) -> Tuple[UIGraph, str]:
    """``VisionResult`` → ``UIGraph``。返回 ``(图, 说明)``。

    说明这一栏不是装饰:调用方必须能区分"这一屏确实没识别出控件"与"投影失败了"。
    两者都产生一张空图,但需要的处置完全不同——前者该退回纯视觉让模型自己看,
    后者是本模块的缺陷。空图配一句空说明会把这个区别抹掉,那正是本轮改造一直在
    消除的那类缺陷。
    """
    empty = UIGraph(source=UISource.VISION, device_id=device_id)
    if result is None:
        logger.warning("视觉投影收到空结果")
        return empty, "视觉结果为空"

    if not bool(getattr(result, "success", False)):
        reason = str(getattr(result, "error", "") or "").strip() or "视觉识别未成功且未给出原因"
        logger.info("视觉识别未成功,不产出结构图: %s", reason)
        return empty, f"视觉识别未成功:{reason}"

    children: List[UIElementNode] = []
    for element in getattr(result, "gui_elements", None) or []:
        projected = _project_element(element)
        if projected is not None:
            children.append(projected)

    element_count = len(children)
    ocr_added = 0
    if include_ocr:
        # OCR 文本单独成节点,但**不与已识别控件重复**:同一个按钮不该既是按钮
        # 又是文字,那会让模型引用 [n] 时看到两个都对的候选。
        flat_so_far = [n for parent in children for n in parent.flatten()]
        for word in getattr(result, "ocr_words", None) or []:
            node = _project_ocr_word(word)
            if node is None or _covered_by(node.bounds, flat_so_far):
                continue
            children.append(node)
            ocr_added += 1

    if not children:
        engine = str(getattr(result, "engine_used", "") or "未知引擎")
        logger.info("视觉识别成功但未解出任何控件(engine=%s)", engine)
        return empty, f"识别成功但无可用控件(engine={engine})"

    scene = getattr(result, "scene", None)
    app = str(getattr(scene, "app_name", "") or "") if scene is not None else ""

    root = UIElementNode(role="root", label=app, source=UISource.VISION, confidence=0.999)
    root.children = children

    graph = UIGraph(
        root=root,
        source=UISource.VISION,
        device_id=device_id,
        app=app,
        screen_width=int(screen_width or 0),
        screen_height=int(screen_height or 0),
    )
    note = f"视觉投影:{element_count} 个控件"
    if ocr_added:
        note += f" + {ocr_added} 段独立文本"
    engine = str(getattr(result, "engine_used", "") or "")
    if engine:
        note += f"(engine={engine})"
    logger.info("%s", note)
    return graph, note


def project_and_merge(
    result: Any,
    structural: Optional[UIGraph] = None,
    *,
    device_id: str = "",
    screen_width: int = 0,
    screen_height: int = 0,
) -> Tuple[UIGraph, str]:
    """投影视觉结果，若给了结构图则融合成混合图。

    融合方向固定为「结构为底、视觉补充」,不是反过来:结构节点是系统对自身的
    陈述,视觉节点是对像素的推断。让推断当底、陈述当补丁,就是让猜测覆盖事实。
    """
    vision_graph, note = project_vision_result(
        result,
        device_id=device_id,
        screen_width=screen_width,
        screen_height=screen_height,
    )
    if structural is None or structural.root is None:
        return vision_graph, note
    if vision_graph.root is None:
        return structural, f"{note};保持结构图不变"
    try:
        merged = structural.merge(vision_graph)
    except Exception as exc:  # noqa: BLE001 — 融合失败必须退回结构图,而不是丢掉两边
        logger.warning("结构图与视觉图融合失败(%s),退回纯结构图", exc)
        return structural, f"{note};融合失败({type(exc).__name__}),已退回结构图"
    return merged, f"{note};已与结构图融合(新增 {merged.vision_added} 个视觉控件)"
