"""tests/test_participant_responsiveness_wiring.py
===================================================

就绪变化时,顺带定出「这台设备能指望多快回应」。

补的是什么洞
------------
``core/cross_device_responsiveness_contract.py`` 有整套五级响应性分类
(near_interactive / bounded_deferred / eventual / degraded / unavailable)、
降级判据、以及一个 ``responsiveness_for_participant`` 便捷入口。它的
``ParticipantReadinessState`` 文档白纸黑字写着这套状态"align with the readiness
signals emitted by ``on_participant_readiness_changed``" —— 也就是说,它本来就是
为那个 hook 写的。

这个 hook 之前不定级 —— 就绪一变,编队照重整、会话快照照更新,唯独"这台设备现在
能指望多快"这件事没人算,调用方拿不到。

(选择侧已经在用同一个分类器:``device_pool_manager._responsiveness_factor`` 在候选
打分时把分级折成乘数。那是"该派给谁",这里是"它刚变成了什么档" —— 同一个分类器,
两个消费时机,互不替代。)

为什么这件事值得接
------------------
就绪与否回答不了"多快"。四维全通(注册/在线/连通/可路由)只说明"能派得过去",
不说明"派过去多久能回话"。一个刚回来、证据还没攒够的参与者,和一个满血在线的
参与者,``ready`` 是同一个值 —— 但前者只能承诺 ``eventual``,后者才够
``near_interactive``。把这两种当成一回事,就会对着一个还没站稳的设备做交互级的
派发决策。
"""

from __future__ import annotations

from typing import Any, Optional

import pytest

from core.multi_device_runtime_harness import MultiDeviceCoherenceHarness


@pytest.fixture()
def harness() -> MultiDeviceCoherenceHarness:
    return MultiDeviceCoherenceHarness()


def _level(result: Any) -> Optional[str]:
    c = result.responsiveness
    return c.level.value if c is not None else None


# ── 1. 定级真的发生了 ────────────────────────────────────────────────────────


def test_readiness_change_produces_a_responsiveness_contract(harness):
    """这是修复前从未发生过的事:运行时产出一条响应性结论。"""
    r = harness.on_participant_readiness_changed("dev-1", "ready", health_score=0.95)

    assert r.responsiveness is not None, "就绪变化没有定出响应性等级"
    assert _level(r) == "near_interactive"
    assert r.responsiveness.is_bounded_near_real_time is True
    assert r.responsiveness.participant_id == "dev-1"


def test_contract_reaches_the_serialised_result(harness):
    """``to_dict()`` 里要带上 —— 否则对进程外的消费方等于没接。"""
    d = harness.on_participant_readiness_changed("dev-1", "ready", health_score=0.9).to_dict()

    assert "responsiveness" in d, f"to_dict 没带 responsiveness:{sorted(d)}"
    assert d["responsiveness"]["level"] == "near_interactive"


# ── 2. 两套就绪词汇的翻译 ────────────────────────────────────────────────────
#
# harness(编队视角)   ready / degraded / lost / recovering
# 分类器(响应性视角)  ready / degraded / stale / partial / missing
#
# 不是同一套词。翻译错了不会报错,只会**悄悄给出一个偏乐观的承诺** —— 所以逐条钉。


def test_lost_maps_to_missing_and_yields_unavailable(harness):
    """``lost`` 必须翻成 ``missing``。

    实话实说:不翻的话分类器也会兜到 missing(它对认不出的值 fail-conservative),
    最终等级一样。翻译在这一条上**不改变行为** —— 做它是为了不刷一行
    "unknown readiness value" 警告,以及不把"碰巧对"当成"翻对了"。

    真正靠翻译才对的是 ``recovering``,见下一条。
    """
    r = harness.on_participant_readiness_changed("dev-1", "lost")

    assert _level(r) == "unavailable"
    assert r.responsiveness.is_bounded_near_real_time is False


def test_recovering_maps_to_partial_not_degraded(harness):
    """``recovering`` 要翻成 ``partial``,**不能**翻成 ``degraded``。

    两者语义不同:``degraded`` 是"在线但打折",``recovering`` 是"还没站稳"。
    翻成 degraded 会让一个正在恢复的设备拿到 ``bounded_deferred`` —— 一个
    有界近实时的承诺,而它其实还没准备好兑现。
    """
    recovering = harness.on_participant_readiness_changed("dev-1", "recovering", health_score=0.9)
    degraded = harness.on_participant_readiness_changed("dev-1", "degraded", health_score=0.9)

    # 钉死具体等级,不能只断言"两者不同" —— 翻译表整个删掉时 recovering 会掉到
    # unavailable,那也满足"不同",测试却该红。实测:翻 → eventual,不翻 → unavailable。
    assert _level(recovering) == "eventual", "recovering 没被翻成 partial"
    assert _level(degraded) == "bounded_deferred"
    assert degraded.responsiveness.is_bounded_near_real_time is True
    assert recovering.responsiveness.is_bounded_near_real_time is False


def test_unknown_readiness_falls_back_conservatively(harness):
    """认不出的就绪值交给分类器兜底 —— 它默认 missing,宁可低估。"""
    r = harness.on_participant_readiness_changed("dev-1", "这是个没人认识的值", health_score=1.0)

    assert _level(r) == "unavailable", "认不出的值被乐观处理了"


# ── 3. 没上报健康分 ≠ 健康 ───────────────────────────────────────────────────


def test_missing_health_score_is_treated_as_no_evidence(harness):
    """没上报健康分 = **不知道**它多健康,不是"它很健康"。

    就绪值一模一样(都是 ``ready``),有证据 0.95 → ``near_interactive``,
    没证据 → ``eventual``,差两级。真把 ``evidence_available`` 恒填 True 的话,
    一个从没上报过健康分的设备就会拿到交互级承诺。

    注:``health_score`` 在无证据时填 0.0 还是 1.0 **不影响结果** —— "没有证据"
    这一条已经压过健康分。所以这条不去断言那个默认值,免得钉一个假判据。
    """
    with_evidence = harness.on_participant_readiness_changed("dev-1", "ready", health_score=0.95)
    without = harness.on_participant_readiness_changed("dev-1", "ready", health_score=None)

    assert _level(with_evidence) == "near_interactive"
    assert _level(without) == "eventual", "没有证据却没被降到 eventual"
    assert without.responsiveness.evidence_present is False
    assert any("evidence" in reason for reason in without.responsiveness.downgrade_reasons)


def test_low_health_downgrades_even_when_ready(harness):
    """就绪但健康分低,不能拿满级 —— 就绪回答不了"多快"。"""
    r = harness.on_participant_readiness_changed("dev-1", "ready", health_score=0.2)

    assert _level(r) != "near_interactive"
    assert r.responsiveness.downgrade_reasons, "降级了却说不出理由"


# ── 4. 定级绝不能影响编队恢复 ────────────────────────────────────────────────


def test_classification_failure_does_not_break_the_hook(harness, monkeypatch):
    """分类器炸了,就绪 hook 本身照跑 —— 它的正事是编队重整,不是定级。"""
    import core.cross_device_responsiveness_contract as mod

    def _boom(**_kw):
        raise RuntimeError("分类器炸了")

    monkeypatch.setattr(mod, "responsiveness_for_participant", _boom)

    r = harness.on_participant_readiness_changed("dev-1", "ready", health_score=0.9)

    assert r.responsiveness is None
    assert r.operation == "on_participant_readiness_changed"
    assert not r.errors, f"定级失败不该记进 errors:{r.errors}"


def test_classification_happens_before_formation_work(harness):
    """编队那一步失败,响应性等级仍然要有。

    定级与编队重整是两件独立的事。放在同一个 try 里的话,编队协调器一抛异常,
    等级就跟着没了 —— 而那恰恰是最需要知道"这台设备现在能指望多快"的时刻。
    """

    class _ExplodingFormation:
        formation_id = "f-1"

        def __getattr__(self, name):
            raise RuntimeError("编队炸了")

    r = harness.on_participant_readiness_changed("dev-1", "degraded", health_score=0.6, formation=_ExplodingFormation())

    assert r.responsiveness is not None, "编队失败把响应性等级也带走了"
    assert _level(r) == "bounded_deferred"
