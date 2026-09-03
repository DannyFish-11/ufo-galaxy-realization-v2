"""视觉坐标与结构树相悖时怎么判 —— 全系统只能有一份规则。

`core/perception_grounding.py` 早就写下了**归属**（Android 设备本地是权威、桌面
V2 服务端是权威），但它只回答了"谁说了算"，没回答"说了算的那一方按什么规则判"。
于是同一个问题在两端有两个不同答案：

  Android(Kotlin GroundingArbiter)  四路裁决矩阵 + 两档阈值 + JVM 单测
  服务端(ui_grounding)              **没有裁决** —— 只认 [n] 序号，
                                    模型给坐标就解析不出来

右边那一格不是"实现得简单些"，是整条路不存在：视觉定位模型的原生输出就是坐标。

本文件守两件事：
  1. 服务端那份裁决**真的按矩阵在判**（逐格用例，不是"跑通就行"）；
  2. 两端的阈值与来源标签**不会单方面漂**（直接读兄弟仓 Kotlin 源码比对）。
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from core.grounded_planner import plan
from core.grounding_arbitration import (
    RESCUE_MATCH_THRESHOLD,
    SOURCE_AGREEMENT,
    SOURCE_TREE_OVERRIDE,
    SOURCE_TREE_RESCUE,
    SOURCE_VLM_FAILED,
    SOURCE_VLM_ONLY,
    STRONG_MATCH_THRESHOLD,
    VisionPoint,
    fuse,
    match_candidates,
    normalize,
    tokenize,
)
from core.schemas.ui_element import UIBounds, UIElementNode, UIGraph, UISource
from core.ui_grounding import GroundingStrategy, parse_coordinate, parse_model_action

SCREEN = (1920, 1080)


def _node(label: str, x: int, y: int, w: int = 100, h: int = 40, clickable: bool = True) -> UIElementNode:
    return UIElementNode(label=label, role="button", clickable=clickable, bounds=UIBounds(x=x, y=y, width=w, height=h))


def _graph(*nodes: UIElementNode) -> UIGraph:
    return UIGraph(
        root=UIElementNode(label="窗口", children=list(nodes)),
        source=UISource.UIA,
        screen_width=SCREEN[0],
        screen_height=SCREEN[1],
    )


# ── 1. 裁决矩阵，逐格 ─────────────────────────────────────────────────


def test_agreement_when_the_point_lands_in_a_matching_element():
    nodes = [_node("发送", 400, 300)]
    f = fuse("点发送", VisionPoint(x=420, y=315, confidence=0.6), nodes, screen=SCREEN)
    assert f.source == SOURCE_AGREEMENT
    assert (f.x, f.y) == (420, 315), "一致时用的是视觉那一点，不是控件正中间"


def test_agreement_boosts_confidence_to_the_larger_of_the_two():
    nodes = [_node("发送", 400, 300)]
    f = fuse("点发送", VisionPoint(x=420, y=315, confidence=0.3), nodes, screen=SCREEN)
    assert f.confidence > 0.3, "双证据一致必须加信用"


def test_agreement_credit_comes_from_the_hit_element_not_the_global_best():
    """视觉命中的若是另一个弱匹配元素，不能拿无关元素的高分抬信用。

    Kotlin 侧修过同一个 bug（加信用用的是全局最高分），这里跟随修正后的语义。
    """
    strong = _node("发送邮件", 400, 300)  # 与意图强匹配，但视觉没点它
    weak = _node("送", 800, 300)  # 视觉点中的那个，匹配弱
    f = fuse("发送邮件", VisionPoint(x=820, y=315, confidence=0.2), [strong, weak], screen=SCREEN)
    assert f.source == SOURCE_AGREEMENT
    best = match_candidates([strong, weak], "发送邮件")[0]
    hit = next(c for c in match_candidates([strong, weak], "发送邮件") if c.node is weak)
    assert f.confidence == pytest.approx(max(0.2, hit.score))
    assert f.confidence < best.score or hit.score >= best.score


def test_tree_override_when_the_point_misses_but_the_tree_is_strong():
    nodes = [_node("发送", 400, 300)]
    f = fuse("发送", VisionPoint(x=9999, y=9999, confidence=0.9), nodes, screen=SCREEN)
    assert f.source == SOURCE_TREE_OVERRIDE
    assert (f.x, f.y) == (450, 320), "推翻视觉后落点是强候选的中心"


def test_vlm_only_when_the_tree_has_no_strong_evidence():
    nodes = [_node("完全无关的控件", 10, 10)]
    f = fuse("点发送", VisionPoint(x=500, y=500, confidence=0.8), nodes, screen=SCREEN)
    assert f.source == SOURCE_VLM_ONLY
    assert (f.x, f.y) == (500, 500), "树没有强证据就必须尊重视觉，不能瞎改坐标"


def test_tree_rescue_when_vision_failed_but_the_tree_is_credible():
    nodes = [_node("发送", 400, 300)]
    f = fuse("发送", VisionPoint(error="model timeout"), nodes, screen=SCREEN)
    assert f.source == SOURCE_TREE_RESCUE
    assert (f.x, f.y) == (450, 320)


def test_vlm_failed_passes_through_when_the_tree_cannot_help():
    f = fuse("点某个东西", VisionPoint(error="boom"), [_node("无关", 10, 10)], screen=SCREEN)
    assert f.source == SOURCE_VLM_FAILED
    assert f.error == "boom", "失败必须透传，让下游梯子接手；不能被伪装成一次成功定位"


def test_no_tree_channel_passes_vision_through():
    f = fuse("点发送", VisionPoint(x=1, y=2, confidence=0.5), None, screen=SCREEN)
    assert f.source == SOURCE_VLM_ONLY
    assert (f.x, f.y) == (1, 2)


def test_no_tree_channel_and_failed_vision():
    assert fuse("x", VisionPoint(error="e"), []).source == SOURCE_VLM_FAILED


# ── 2. 两档阈值的不对称是刻意的 ────────────────────────────────────────


def test_override_threshold_is_stricter_than_rescue():
    """推翻一条有效的视觉证据，门槛必须高于"视觉已经失败了、树只需可信"。"""
    assert STRONG_MATCH_THRESHOLD > RESCUE_MATCH_THRESHOLD


def test_a_candidate_between_the_two_thresholds_rescues_but_never_overrides():
    """落在两档之间的候选：视觉失败时救场，视觉有效时不许推翻。"""
    nodes = [_node("发送", 400, 300)]
    score = match_candidates(nodes, "把这封信发送出去")[0].score
    assert RESCUE_MATCH_THRESHOLD <= score < STRONG_MATCH_THRESHOLD, f"这条用例依赖分数落在两档之间，实际 {score}"
    assert fuse("把这封信发送出去", VisionPoint(error="e"), nodes, screen=SCREEN).source == SOURCE_TREE_RESCUE
    assert (
        fuse("把这封信发送出去", VisionPoint(x=9999, y=9999, confidence=0.9), nodes, screen=SCREEN).source
        == SOURCE_VLM_ONLY
    )


# ── 3. 打分与分词，与 Kotlin 同语义 ───────────────────────────────────


def test_cjk_is_tokenized_per_character():
    assert tokenize("发送邮件") == {"发", "送", "邮", "件"}


def test_single_latin_characters_are_dropped():
    assert tokenize("a send b") == {"send"}, "单字符拉丁 token 没有区分度"


def test_latin_words_survive():
    assert tokenize("Send Mail") == {"send", "mail"}


def test_normalize_strips_punctuation_keeps_cjk():
    assert normalize("发送(Send)!") == "发送send"


def test_unlabelled_nodes_never_score():
    assert match_candidates([_node("", 0, 0)], "发送") == []


def test_empty_intent_yields_no_candidates():
    assert match_candidates([_node("发送", 0, 0)], "") == []


def test_clickable_gets_a_bonus_over_identical_static_text():
    """意图刻意写长：短意图下两者都会撞到 1.0 上限（与 Kotlin 的 coerceAtMost(1f) 一致），
    加成看不出来。这不是 bug，但拿撞顶的样本去验加成，验的是上限不是加成。"""
    clickable = _node("发送", 0, 0, clickable=True)
    static = _node("发送", 0, 100, clickable=False)
    scores = {c.node.clickable: c.score for c in match_candidates([clickable, static], "把这封信发送出去")}
    assert scores[True] > scores[False]
    assert scores[True] - scores[False] == pytest.approx(0.1)


def test_candidates_are_sorted_by_score():
    scores = [c.score for c in match_candidates([_node("发送", 0, 0), _node("发送邮件草稿", 0, 100)], "发送")]
    assert scores == sorted(scores, reverse=True)


def test_override_coordinates_are_clamped_to_the_screen():
    """越界坐标发给执行节点就是点在屏幕外 —— 静默无效果，最难排查的那种失败。"""
    off = _node("发送", 5000, 5000)
    f = fuse("发送", VisionPoint(error="e"), [off], screen=SCREEN)
    assert 0 <= f.x <= SCREEN[0] - 1 and 0 <= f.y <= SCREEN[1] - 1


# ── 4. 服务端真的走上了这条路（此前整条不存在）────────────────────────


@pytest.mark.parametrize(
    "reply,expected",
    [
        ("点击 (420, 315)", (420, 315)),
        ("420,315", (420, 315)),
        ("x=420, y=315", (420, 315)),
        ("坐标 420，315", (420, 315)),
    ],
)
def test_coordinates_are_parsed_from_the_model_reply(reply, expected):
    assert parse_coordinate(reply) == expected


@pytest.mark.parametrize("reply", ["[3]", "点发送按钮", "第 3 个", ""])
def test_non_coordinate_replies_are_not_misread_as_points(reply):
    """宁可漏认也不能错认：错认的后果是在无关位置点一下。"""
    assert parse_coordinate(reply) is None


def test_parse_model_action_arbitrates_a_coordinate_reply():
    g = _graph(_node("发送", 400, 300))
    r = parse_model_action("点击 (420, 315)", g)
    assert r.strategy is GroundingStrategy.COORDINATE
    assert r.fusion_source == SOURCE_AGREEMENT
    assert r.coordinate == (420, 315)


def test_index_reference_still_wins_when_there_is_no_coordinate():
    g = _graph(_node("发送", 400, 300))
    assert parse_model_action("[1]", g).strategy is GroundingStrategy.INDEX_REF


def test_a_coordinate_reply_is_executable_without_a_matching_node():
    """vlm_only 那一格没有匹配的树节点，但坐标本身就是可执行的答案。

    此前 ok 只看 node，这一格会被判成"点不准"再问一遍模型 —— 而模型上一轮已经
    答过了：同一个问题问两遍，拿到同一个答案，再问第三遍。
    """
    g = _graph(_node("无关控件", 10, 10))
    action = plan(g, "点画布左上角", model_reply="画布左上角 (50, 60)")
    assert action.needs_model is False
    assert action.executable is True
    assert action.coordinates == [50, 60]
    assert action.fusion_source == SOURCE_VLM_ONLY


def test_planner_lands_on_the_arbitrated_point_not_the_node_centre():
    """agreement 时该用视觉那一点：大控件的中心往往落在另一个子控件上。"""
    g = _graph(_node("工具栏", 0, 0, w=1900, h=80))
    action = plan(g, "点工具栏最左边", model_reply="工具栏 (20, 40)")
    assert action.coordinates == [20, 40]
    assert action.coordinates != [950, 40]


def test_planner_reports_which_rule_decided_the_point():
    """阈值将来要按真机数据调 —— 没有这一列就只能拍脑袋。"""
    g = _graph(_node("发送", 400, 300))
    assert plan(g, "发送", model_reply="x=9999, y=9999 发送").fusion_source == SOURCE_TREE_OVERRIDE


def test_non_coordinate_paths_leave_fusion_source_empty():
    g = _graph(_node("发送", 400, 300))
    assert plan(g, "点发送").fusion_source == ""


# ── 5. 跨仓防漂：两端不许单方面改阈值或标签 ────────────────────────────


def _android_repo_root() -> Path:
    raw = os.environ.get("ANDROID_REPO_ROOT", "").strip()
    if not raw:
        pytest.skip("ANDROID_REPO_ROOT not set; skip cross-repo grounding-rule drift check.")
    root = Path(raw)
    if not root.exists():
        pytest.skip(f"ANDROID_REPO_ROOT does not exist: {root}")
    return root


def _arbiter_source() -> str:
    """读安卓侧 GroundingArbiter.kt。**文件不在就失败，不跳过。**

    这道门的全部作用就是"两端规则有没有漂"。文件被改名或挪走恰恰是最典型的漂移
    形态，此时跳过会让门变绿、且绿得毫无痕迹。跳过只对"根本没有跨仓 checkout"
    成立，那由 _android_repo_root 判定。
    """
    path = _android_repo_root() / "app/src/main/java/com/ufo/galaxy/perception/GroundingArbiter.kt"
    if not path.exists():
        raise AssertionError(f"安卓侧 GroundingArbiter.kt 不在预期位置: {path} —— 这本身就是规则漂移")
    return path.read_text(encoding="utf-8")


def _kotlin_const(src: str, name: str) -> float:
    m = re.search(rf"const\s+val\s+{name}\s*=\s*([0-9.]+)f?", src)
    assert m, f"安卓侧读不到常量 {name}"
    return float(m.group(1))


@pytest.mark.parametrize(
    "py_value,kotlin_name",
    [
        (STRONG_MATCH_THRESHOLD, "STRONG_MATCH_THRESHOLD"),
        (RESCUE_MATCH_THRESHOLD, "RESCUE_MATCH_THRESHOLD"),
    ],
)
def test_thresholds_match_the_android_side(py_value, kotlin_name):
    assert py_value == pytest.approx(_kotlin_const(_arbiter_source(), kotlin_name)), (
        f"{kotlin_name} 两端不一致 —— 同一个界面、同一个模型输出，两台设备会给出不同裁决。" "要改就两端一起改。"
    )


@pytest.mark.parametrize(
    "label",
    [SOURCE_AGREEMENT, SOURCE_VLM_ONLY, SOURCE_TREE_OVERRIDE, SOURCE_TREE_RESCUE, SOURCE_VLM_FAILED],
)
def test_source_labels_match_the_android_side(label):
    """标签是日志与遥测的连接键：两端不一样就没法把同一种裁决放在一起看。"""
    assert f'"{label}"' in _arbiter_source(), f"安卓侧没有来源标签 {label}"


def test_every_matrix_branch_of_the_kotlin_arbiter_exists_here():
    """安卓侧新增一格裁决而服务端没跟上时，这条会红。"""
    src = _arbiter_source()
    kotlin_labels = set(re.findall(r'const\s+val\s+SOURCE_\w+\s*=\s*"([^"]+)"', src))
    ours = {SOURCE_AGREEMENT, SOURCE_VLM_ONLY, SOURCE_TREE_OVERRIDE, SOURCE_TREE_RESCUE, SOURCE_VLM_FAILED}
    assert kotlin_labels == ours, f"两端裁决分支不一致：安卓 {kotlin_labels}，服务端 {ours}"
