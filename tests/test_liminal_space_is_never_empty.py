#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_liminal_space_is_never_empty.py

钉住阈限空间（中间态）的三条性质：**永不空白、单点定义、不会漂**。

背景
====
阈限态在面板上一直「什么都没有」，根因不是动画简陋，是它的内容从没送出来过。
此前已经补过一轮（推演摘要上链路），但只补了一半：``should_rehearse()`` 要求
**有工具可调**且**复杂度 ≥ 0.55**，于是纯对话与简单请求永远不推演，而阈限内容的
全部登记点都在推演块**内部**——那两类请求的阈限期全程 ``liminal_activity="none"``，
面板照样空白。

这个文件钉的就是「补完之后不会再退回去」。
"""

from __future__ import annotations

import dataclasses

import pytest

from core.desktop_presence_runtime import RuntimeSession, TriState
from core.phase_contract import LIMINAL_ACTIVITIES

# ---------------------------------------------------------------------------
# 一、永不空白 —— 结构保证，不依赖任何分支恰好登记
# ---------------------------------------------------------------------------


def test_entering_liminal_always_yields_content():
    """进阈限就一定有内容。

    判据钉的是 ``advance(LIMINAL)`` 这个**相位推进本身**，而不是「认知段某处会登记」
    ——后者正是此前失效的那条：登记点都在推演闸门内，闸门关了就全空。
    """
    session = RuntimeSession(source="test")
    assert session.liminal_activity == "none", "静息期不该有阈限内容"

    session.advance(TriState.LIMINAL)
    assert session.liminal_activity != "none", (
        "进入 LIMINAL 之后阈限内容仍为 none —— 「阈限态永远有内容」的结构保证失效了。"
        "注意：这一条不能靠认知段某个分支去登记，纯对话与低复杂度请求根本进不去那些分支。"
    )
    assert session.liminal_activity in LIMINAL_ACTIVITIES


def test_liminal_content_clears_on_the_way_out():
    """出阈限要清干净，别把上一次请求的内容挂到下一次。"""
    session = RuntimeSession(source="test")
    session.advance(TriState.LIMINAL)
    session.enter_liminal_activity("rehearsing", {"is_active": True, "candidate_paths": ["A"]})

    session.advance(TriState.MANIFEST)
    assert session.liminal_activity == "none", "进入表达期后不该还报着阈限活动"
    assert (
        session.simulation_summary is not None
    ), "摘要在 MANIFEST 期必须保留 —— 面板要显示「按哪条候选提交的」，那是结果不是活动"

    session.advance(TriState.SILENT)
    assert session.liminal_activity == "none"
    assert session.simulation_summary is None, "回到静息必须连摘要一起归零"


def test_progression_is_ordered_and_reaches_thinking_without_rehearsal():
    """递进序列有序，且**不经推演**也能走到 thinking。

    ``understanding → thinking`` 这一段必须与推演无关：纯对话没有工具可调，永远
    不会有 rehearsing，但它同样在「理解 → 规划」。
    """
    assert LIMINAL_ACTIVITIES[0] == "none"
    assert "understanding" in LIMINAL_ACTIVITIES
    assert LIMINAL_ACTIVITIES.index("understanding") < LIMINAL_ACTIVITIES.index(
        "thinking"
    ), "understanding 必须排在 thinking 之前"
    assert LIMINAL_ACTIVITIES.index("thinking") < LIMINAL_ACTIVITIES.index(
        "rehearsing"
    ), "thinking 必须排在 rehearsing 之前"

    session = RuntimeSession(source="test")
    session.advance(TriState.LIMINAL)
    assert session.liminal_activity == "understanding"
    session.enter_liminal_activity("thinking")  # 认知段在推演闸门之外登记
    assert session.liminal_activity == "thinking"


def test_illegal_activity_is_bounced_not_silently_accepted():
    """非法取值兜成 none 且留 warning —— 静默接受会让渲染端收到契约外的值。"""
    session = RuntimeSession(source="test")
    session.advance(TriState.LIMINAL)
    session.enter_liminal_activity("definitely_not_a_real_activity")
    assert session.liminal_activity == "none"


# ---------------------------------------------------------------------------
# 二、单点定义 —— 取值域不能有第二份
# ---------------------------------------------------------------------------


def test_activity_vocabulary_has_exactly_one_definition():
    """运行时侧与契约侧必须是**同一个对象**，不是「值相等」。

    值相等的断言挡不住「两边各自改成同样的新值」之外的情形；钉同一性才能保证
    根本不存在第二份定义。
    """
    from core.liminal_activity import LIMINAL_ACTIVITIES as runtime_side
    from core.phase_contract import LIMINAL_ACTIVITIES as contract_side

    assert runtime_side is contract_side, (
        "阈限活动取值域出现了第二份定义。两边各写一份字面量、靠注释说「同源」，"
        "改一边忘另一边时的症状是「面板偶尔空白」，根本指不回定义处。"
    )


# ---------------------------------------------------------------------------
# 三、不会漂 —— 渲染契约不能长出投影层没有的字段
# ---------------------------------------------------------------------------


def test_render_contract_summary_does_not_outgrow_the_projection_layer():
    """渲染契约的 SimulationSummary 字段集必须是投影层那份的**子集**。

    两层是刻意分开的（core 侧投影 vs 跨 JSON 边界的渲染契约，前端拿不到 core 类型），
    所以不合并。但渲染契约一旦长出投影层没有的字段，就等于凭空多了一处真相来源，
    而 builder 校验不到它。

    钉子集而不是钉相等：投影层可以有渲染端用不上的东西（summary_id / timestamp）。
    """
    from core.liminal_space_mapping import SimulationSummary as ProjectionSummary
    from core.phase_contract import SimulationSummary as RenderSummary

    projection_fields = {f.name for f in dataclasses.fields(ProjectionSummary)}
    render_fields = {f.name for f in dataclasses.fields(RenderSummary)}

    extra = render_fields - projection_fields
    assert not extra, (
        f"渲染契约长出了投影层没有的字段：{sorted(extra)}。"
        "这些字段不会经过 build_simulation_summary() 的取值域校验与推导，"
        "要么加进投影层，要么说明它为什么只属于渲染端。"
    )


def test_simulation_kinds_vocabulary_is_enforced_by_the_builder():
    """取值域校验必须真的跑 —— 非法 simulation_kind 要被兜住。"""
    from core.liminal_space_mapping import build_simulation_summary
    from core.phase_contract import SIMULATION_KINDS

    bounced = build_simulation_summary(simulation_kind="definitely_not_a_kind")
    assert bounced.simulation_kind == "none"
    assert bounced.simulation_kind in SIMULATION_KINDS

    for kind in SIMULATION_KINDS:
        assert build_simulation_summary(simulation_kind=kind).simulation_kind == kind, f"合法取值 {kind!r} 不该被兜掉"


def test_is_committed_is_derived_once_not_recomputed_downstream():
    """``is_committed`` 由 builder 推导，下游直接取，不各推一遍。"""
    from core.liminal_space_mapping import build_simulation_summary

    committed = build_simulation_summary(candidate_paths=["A", "B"], committed_path="B").to_dict()
    assert committed["is_committed"] is True
    assert "is_committed" in committed, "摘要必须把 is_committed 带出来，否则下游只能自己再推一遍"

    still_open = build_simulation_summary(candidate_paths=["A", "B"], committed_path=None).to_dict()
    assert still_open["is_committed"] is False


# ---------------------------------------------------------------------------
# 四、执行链视图进了 tick
# ---------------------------------------------------------------------------


def test_tick_carries_both_execution_chain_views():
    """阈限空间的三类内容里，两条执行链也必须能构造出来。

    零态是**合法且有意义**的（还没跑过），所以判据是「构造得出、字段齐」，
    不是「必须非零」。
    """
    views = RuntimeSession._build_chain_views()
    assert "local_chain" in views, "本机执行链视图没进 tick —— 阈限空间三类内容缺一类"
    assert "cross_device_chain" in views, "跨设备执行链视图没进 tick"
    for key in ("local_chain", "cross_device_chain"):
        for field in ("total_executions", "canonical_chain_order", "is_active"):
            assert field in views[key], f"{key} 缺字段 {field}"


@pytest.mark.parametrize("view_key", ["local_chain", "cross_device_chain"])
def test_chain_views_are_cheap_enough_for_a_200ms_tick(view_key):
    """视图只读最近一条记录，不该把整段历史序列化 —— tick 是 200ms 一拍。"""
    views = RuntimeSession._build_chain_views()
    assert "recent_records" not in views[view_key], (
        f"{view_key} 把 recent_records 也带上了：视图只读 recent[-1]，" "整段历史跟着上 200ms 通道是白费功夫"
    )
