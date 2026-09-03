#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/grounding_arbitration.py — 视觉坐标 × 结构树候选的裁决规则(单一权威)
========================================================================

**Stage D：把「两端各写一份裁决规则」收敛成一份。**

问题的形状
----------
:mod:`core.perception_grounding` 已经写下了**归属**：Android 设备本地是权威、
桌面 V2 服务端是权威。但它只回答了"谁说了算"，没回答"说了算的那一方按什么规则
判"。于是同一个问题在两端有两个不同答案：

===============================  ==========================================
Android(Kotlin ``GroundingArbiter``)  服务端(``ui_grounding.parse_model_action``)
===============================  ==========================================
四路裁决矩阵                       **没有裁决**
agreement / tree_override /       模型回 ``[n]`` 序号 → 用序号；
tree_rescue / vlm_only            回坐标 → **解析不出来**，落到按名匹配，
两档阈值 + JVM 单测                多半返回 defer_to_model
===============================  ==========================================

右边那一格不是"实现得简单些"，是**整条路不存在**：视觉定位模型（SeeClick /
Qwen-VL / MAI-UI 这一类）的原生输出就是坐标，而服务端的 ``parse_model_action``
只认 ``[n]``。模型答对了坐标，服务端也用不上；结构树明明能救场，也没人问它。

本模块把 Kotlin 那份规则**逐条搬到服务端**，两端从此共用同一张矩阵、同一组阈值、
同一套来源标签。规则本身的所有权仍在 Android（它有真机数据回流），服务端这份是
**跟随**，不是第四份 —— :mod:`tests.test_grounding_rule_is_one_rule` 直接读兄弟仓
的 Kotlin 源码比对常量，任何一端单方面改动都会红。

裁决矩阵（与 ``GroundingArbiter.fuse`` 逐行对应）
------------------------------------------------
==========================================  ==========  ==================
视觉结果                                      树候选       裁决 / 来源标签
==========================================  ==========  ==================
有效，落在**匹配意图**的元素内                  有          视觉坐标，置信度取两者较大 · ``agreement``
有效，但不落在任何匹配元素内，且有强匹配候选      有          强候选中心点 · ``tree_override``
有效，树无强证据                               无/弱       视觉坐标原样 · ``vlm_only``
失败，且有可信候选                             有          强候选中心点 · ``tree_rescue``
失败，树也没有                                 无/弱       原失败结果透传 · ``vlm_failed_no_tree``
==========================================  ==========  ==================

两档阈值不对称是**刻意的**：``tree_override`` 是拿结构去推翻一条有效的视觉证据，
门槛要高；``tree_rescue`` 时视觉已经失败，树只需可信即可。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional, Sequence, Set, Tuple

logger = logging.getLogger("Galaxy.GroundingArbitration")

__all__ = [
    "GROUNDING_RULE_HAS_ONE_DEFINITION_POLICY",
    "STRONG_MATCH_THRESHOLD",
    "RESCUE_MATCH_THRESHOLD",
    "SOURCE_AGREEMENT",
    "SOURCE_VLM_ONLY",
    "SOURCE_TREE_OVERRIDE",
    "SOURCE_TREE_RESCUE",
    "SOURCE_VLM_FAILED",
    "VisionPoint",
    "ScoredElement",
    "FusedGrounding",
    "tokenize",
    "normalize",
    "match_candidates",
    "fuse",
]

GROUNDING_RULE_HAS_ONE_DEFINITION_POLICY: str = (
    "GROUNDING_ARBITRATION::POLICY_1: "
    "视觉坐标与结构树相悖时怎么判,全系统只有一份规则。服务端这份跟随 Android 的 "
    "GroundingArbiter(它有真机数据回流),不得单方面改阈值或加分支;要改就两端一起改, "
    "由 test_grounding_rule_is_one_rule 守住。"
)

#: 推翻视觉坐标(tree_override)所需的最低树匹配分。与 Kotlin 侧同名常量必须相等。
STRONG_MATCH_THRESHOLD = 0.75

#: 视觉失败后采用树候选(tree_rescue)所需的最低树匹配分。同上。
RESCUE_MATCH_THRESHOLD = 0.55

SOURCE_AGREEMENT = "agreement"
SOURCE_VLM_ONLY = "vlm_only"
SOURCE_TREE_OVERRIDE = "tree_override"
SOURCE_TREE_RESCUE = "tree_rescue"
SOURCE_VLM_FAILED = "vlm_failed_no_tree"

#: CJK 起始码位。低于它按拉丁词处理,不低于它逐字成 token(与 Kotlin 侧 0x2E80 一致)。
_CJK_START = 0x2E80


@dataclass(frozen=True)
class VisionPoint:
    """视觉定位模型的原始输出。``error`` 非空即视为失败。"""

    x: int = 0
    y: int = 0
    confidence: float = 0.0
    error: str = ""

    @property
    def failed(self) -> bool:
        return bool(self.error)


@dataclass(frozen=True)
class ScoredElement:
    """一个结构树节点 + 它与意图的匹配分。"""

    node: object
    score: float


@dataclass(frozen=True)
class FusedGrounding:
    """裁决结果:最终坐标 + 来源标签 + 被选中的节点(视觉独走时为 None)。"""

    x: int
    y: int
    confidence: float
    source: str
    node: object = None
    error: str = ""


def normalize(s: str) -> str:
    """小写并只保留字母数字与 CJK。与 Kotlin ``normalize`` 等价。"""
    return "".join(ch for ch in (s or "").lower() if ch.isalnum() or ord(ch) > 0x2E7F)


def tokenize(s: str) -> Set[str]:
    """混合分词:拉丁词按非字母数字切分;CJK 逐字成 token。

    中文 UI 标签多为 2~4 字短词,逐字重叠率已够裁决用。末尾过滤掉无区分度的
    单字符拉丁 token —— 与 Kotlin ``tokenize`` 逐行等价。
    """
    tokens: Set[str] = set()
    latin: List[str] = []
    for ch in (s or "").lower():
        code = ord(ch)
        if ch.isalnum() and code < _CJK_START:
            latin.append(ch)
        elif code >= _CJK_START:
            if latin:
                tokens.add("".join(latin))
                latin.clear()
            tokens.add(ch)
        else:
            if latin:
                tokens.add("".join(latin))
                latin.clear()
    if latin:
        tokens.add("".join(latin))
    return {t for t in tokens if not (len(t) == 1 and ord(t[0]) < _CJK_START)}


def _label_of(node: object) -> str:
    return (getattr(node, "label", "") or "").strip()


def _score(intent_tokens: Set[str], intent_norm: str, node: object) -> float:
    label = _label_of(node)
    if not label:
        return 0.0
    label_tokens = tokenize(label)
    if not label_tokens:
        return 0.0
    overlap = len(intent_tokens & label_tokens) / max(len(intent_tokens), 1)
    label_norm = normalize(label)
    if label_norm and label_norm in intent_norm:
        containment = 0.5
    elif intent_norm and intent_norm in label_norm:
        containment = 0.5
    else:
        containment = 0.0
    click_bonus = 0.1 if getattr(node, "clickable", False) else 0.0
    return min(overlap * 0.5 + containment + click_bonus, 1.0)


def match_candidates(nodes: Sequence[object], intent: str) -> List[ScoredElement]:
    """按意图给结构节点打分并降序排列。零分节点不入选。"""
    intent_tokens = tokenize(intent)
    if not intent_tokens:
        return []
    intent_norm = normalize(intent)
    scored = [ScoredElement(n, _score(intent_tokens, intent_norm, n)) for n in nodes]
    return sorted((s for s in scored if s.score > 0.0), key=lambda s: s.score, reverse=True)


def _contains(node: object, x: int, y: int) -> bool:
    """点是否落在节点矩形内。

    坐标形状用服务端 :class:`core.schemas.ui_element.UIBounds` 的 x/y/width/height,
    而不是 Kotlin 侧的 left/top/right/bottom —— 两端的矩形表示本来就不同,统一的是
    **裁决规则**,不是数据结构。没有 bounds 的节点(视觉节点可能只给标签)恒不命中。
    """
    b = getattr(node, "bounds", None)
    if b is None:
        return False
    try:
        return b.x <= x <= b.x + b.width and b.y <= y <= b.y + b.height
    except (AttributeError, TypeError):
        return False


def _center(node: object) -> Tuple[int, int]:
    b = getattr(node, "bounds", None)
    if b is None:
        return 0, 0
    try:
        cx, cy = b.center()
        return int(cx), int(cy)
    except (AttributeError, TypeError):
        return 0, 0


def _clamp_to_screen(x: int, y: int, screen: Tuple[int, int]) -> Tuple[int, int]:
    w, h = screen
    max_x = max(w - 1, 0)
    max_y = max(h - 1, 0)
    return (min(max(x, 0), max_x) if max_x > 0 else max(x, 0), min(max(y, 0), max_y) if max_y > 0 else max(y, 0))


def _from_element(scored: ScoredElement, screen: Tuple[int, int], source: str) -> FusedGrounding:
    cx, cy = _clamp_to_screen(*_center(scored.node), screen)
    return FusedGrounding(x=cx, y=cy, confidence=scored.score, source=source, node=scored.node)


def fuse(
    intent: str,
    vision: VisionPoint,
    nodes: Optional[Sequence[object]] = None,
    *,
    screen: Tuple[int, int] = (0, 0),
) -> FusedGrounding:
    """裁决一次定位。``nodes`` 为空 = 没有结构通道,视觉结果原样透传。

    坐标系必须一致 —— 调用方负责在"缩放截图上定位"时把树 bounds 或视觉坐标
    换算到同一空间之后再进来。这一条与 Kotlin 侧同样是调用方的责任。
    """
    if not nodes:
        return _log(
            intent,
            FusedGrounding(
                x=vision.x,
                y=vision.y,
                confidence=vision.confidence,
                source=SOURCE_VLM_FAILED if vision.failed else SOURCE_VLM_ONLY,
                error=vision.error,
            ),
        )

    candidates = match_candidates(nodes, intent)
    best = candidates[0] if candidates else None

    # 视觉失败 → 树可信即救场。
    if vision.failed:
        if best is not None and best.score >= RESCUE_MATCH_THRESHOLD:
            return _log(intent, _from_element(best, screen, SOURCE_TREE_RESCUE))
        return _log(
            intent,
            FusedGrounding(
                x=vision.x,
                y=vision.y,
                confidence=vision.confidence,
                source=SOURCE_VLM_FAILED,
                error=vision.error,
            ),
        )

    # 视觉坐标落在意图匹配的元素内 → 双证据一致。
    # 置信度取"视觉分"与**被命中元素**的分较大者 —— 不是全局最高分:视觉命中的
    # 若是另一个弱匹配元素,拿无关元素的分数抬高置信度就是凭空加信用。
    # (Kotlin 侧修过同一个 bug,这里跟随修正后的语义。)
    hit = max(
        (c for c in candidates if c.score > 0.0 and _contains(c.node, vision.x, vision.y)),
        key=lambda c: c.score,
        default=None,
    )
    if hit is not None:
        return _log(
            intent,
            FusedGrounding(
                x=vision.x,
                y=vision.y,
                confidence=max(vision.confidence, hit.score),
                source=SOURCE_AGREEMENT,
                node=hit.node,
            ),
        )

    # 视觉坐标与强树候选相悖 → 树推翻视觉。
    if best is not None and best.score >= STRONG_MATCH_THRESHOLD:
        return _log(intent, _from_element(best, screen, SOURCE_TREE_OVERRIDE))

    # 树无强证据 → 尊重视觉。
    return _log(
        intent,
        FusedGrounding(x=vision.x, y=vision.y, confidence=vision.confidence, source=SOURCE_VLM_ONLY),
    )


def _log(intent: str, fused: FusedGrounding) -> FusedGrounding:
    """每次裁决都留一条结构化记录 —— 阈值将来要按真机数据调,没有记录就只能拍脑袋。"""
    logger.info(
        "grounding_fused source=%s intent_len=%d x=%d y=%d conf=%.3f error=%s",
        fused.source,
        len(intent or ""),
        fused.x,
        fused.y,
        fused.confidence,
        fused.error or "",
    )
    return fused
