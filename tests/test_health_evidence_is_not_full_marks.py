#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_health_evidence_is_not_full_marks.py

钉住：**没有健康证据的设备不算满分**，且响应性分级真的参与候选选择。

背景
====
本仓有两套设备健康登记，各自对「这台设备我从没测过」给满分：

* ``core.unified.device_health.DeviceHealthScorer`` → ``1.0``
  （它的 docstring 还把 1.0 称作 "neutral score"，而 1.0 是它的**上界** ——
  把满分叫成中性，就没人会觉得它可疑。这一步命名错位正是缺陷的源头。）
* ``core.control_plane.device_health_registry`` 经 ``device_pool_manager._health_score()``
  → ``100.0``。**这一条在活的选择路径上**（``constellation_runtime`` 用它）。

实测后果（走活的 ``device_pool_manager``）：

    从没测过的设备   _health_score() = 100.0
    实测很差的设备   _health_score() =  29.83
    → max(candidates, key=score) 选中了从没测过的那台

也就是说一台**可能根本是死的**设备，会排在一台实测很差但确实在工作的设备前面。

而 ``core/cross_device_responsiveness_contract.py`` 里明写着相反的策略 ——
``EVIDENCE_ABSENCE_BLOCKS_NEAR_INTERACTIVE_POLICY``：证据缺失必须下调，绝不乐观上调。
两边对同一件事的判断是反的，而各自看都很合理。
"""

from __future__ import annotations

import pytest

from core.control_plane.device_health_registry import CircuitState
from core.device_pool_manager import get_device_pool_manager
from core.health_evidence_policy import NO_EVIDENCE_FRACTION, has_health_evidence, no_evidence_score


@pytest.fixture()
def pool():
    return get_device_pool_manager()


# ---------------------------------------------------------------------------
# 一、判据只有一处，两套刻度由它换算
# ---------------------------------------------------------------------------


def test_no_evidence_is_neutral_not_full_marks():
    assert 0.0 < NO_EVIDENCE_FRACTION < 1.0, "证据缺失既不该是满分也不该是零分"
    assert no_evidence_score(1.0) == NO_EVIDENCE_FRACTION
    assert no_evidence_score(100.0) == NO_EVIDENCE_FRACTION * 100.0


def test_both_registries_use_the_same_policy():
    """两套刻度不同（1.0 与 100.0）是历史遗留，但**判据必须同源**。"""
    from core.unified.device_health import get_device_health_scorer

    scorer_side = get_device_health_scorer().score("never-measured-anywhere").total_score
    pool_side = get_device_pool_manager()._health_score("never-measured-anywhere")
    assert scorer_side == no_evidence_score(1.0), f"DeviceHealthScorer 没走同一判据：{scorer_side}"
    assert pool_side == no_evidence_score(100.0), f"device_pool_manager 没走同一判据：{pool_side}"
    assert scorer_side * 100.0 == pool_side, "两套刻度换算后必须是同一个判断"


def test_evidence_presence_is_a_separate_bit():
    """「有没有证据」不能被压进分数里。

    压成一个数之后下游分不出 "测过、就是中等" 和 "没测过" —— 而这两件事对
    「该不该把活派给它」的含义完全不同。
    """
    assert has_health_evidence(0) is False
    assert has_health_evidence(1) is True

    from core.unified.device_health import get_device_health_scorer

    unknown = get_device_health_scorer().score("still-never-measured")
    assert unknown.sample_count == 0, "证据位丢了，分数就成了唯一线索"


# ---------------------------------------------------------------------------
# 二、排位：零证据在实测健康之下、实测很差之上
# ---------------------------------------------------------------------------


def test_unknown_device_never_outranks_a_proven_healthy_one(pool):
    """这就是被修掉的那条缺陷。"""
    registry = pool._health_registry
    registry.record_heartbeat("t-proven-good", latency_ms=15.0)
    for _ in range(8):
        registry.record_success("t-proven-good")

    unknown = pool._health_score("t-never-seen")
    good = pool._health_score("t-proven-good")
    assert unknown < good, (
        f"零证据设备（{unknown}）排在实测健康设备（{good}）之前 —— " "一台可能已经死掉的设备会优先接活。"
    )


def test_unknown_device_is_not_starved_below_a_proven_bad_one(pool):
    """另一个方向也要守：排在实测很差的之后，新设备就永远拿不到第一次机会，
    而健康分只能靠接活才积累得出来 —— 那是另一种死锁。"""
    registry = pool._health_registry
    for _ in range(8):
        registry.record_failure("t-burned")

    assert pool._health_score("t-never-seen") > pool._health_score("t-burned")


# ---------------------------------------------------------------------------
# 三、响应性契约真的改变选择（不是空转）
# ---------------------------------------------------------------------------


def test_absent_evidence_is_downgraded_below_near_interactive(pool):
    """``EVIDENCE_ABSENCE_BLOCKS_NEAR_INTERACTIVE_POLICY`` 落到实处。"""
    registry = pool._health_registry
    registry.record_heartbeat("t-evidenced", latency_ms=15.0)
    for _ in range(8):
        registry.record_success("t-evidenced")

    evidenced = pool._responsiveness_factor("t-evidenced", pool._health_score("t-evidenced") / 100.0)
    unknown = pool._responsiveness_factor("t-unknown", pool._health_score("t-unknown") / 100.0)
    assert evidenced == 1.0, "有证据且健康却没拿到近交互满权重"
    assert unknown < evidenced, "零证据被算成了近交互 —— 契约的核心策略没生效"


def test_an_open_circuit_device_gets_zero_weight(pool):
    """熔断打开 = 这条路现在走不通。给任何正权重都意味着没有别的候选时它仍会被选中。"""
    registry = pool._health_registry
    for _ in range(10):
        registry.record_failure("t-open-circuit")
    state = registry.get_state("t-open-circuit")
    if state.circuit_state is not CircuitState.OPEN and not state.quarantined:
        pytest.skip("这台设备没有进入 OPEN/隔离，换个阈值再钉")
    assert pool._responsiveness_factor("t-open-circuit", 0.9) == 0.0


def test_circuit_state_flips_a_choice_that_health_alone_would_get_wrong(pool):
    """契约独有的那一维：**熔断状态**。health 分完全看不见它。

    这是唯一能证明「接了不是空转」的判据 —— 零证据那一档单靠中性默认就已经翻转了，
    契约在那一档是冗余的；真正只有契约能给出的判断在这里。
    """
    registry = pool._health_registry
    registry.record_heartbeat("t-closed", latency_ms=400.0)
    for _ in range(6):
        registry.record_success("t-closed")
    registry.record_heartbeat("t-halfopen", latency_ms=300.0)
    for _ in range(6):
        registry.record_success("t-halfopen")
    registry._states["t-halfopen"].circuit_state = CircuitState.HALF_OPEN

    h_closed = pool._health_score("t-closed") / 100.0
    h_half = pool._health_score("t-halfopen") / 100.0
    assert h_half > h_closed, "前置条件：半开那台的原始 health 必须更高，否则这条测不出东西"

    final_closed = h_closed * pool._responsiveness_factor("t-closed", h_closed)
    final_half = h_half * pool._responsiveness_factor("t-halfopen", h_half)
    assert final_closed > final_half, (
        "还在半开试探的设备仍然压过了完全恢复的设备 —— 契约的熔断维没有进入打分，" "接进去等于空转。"
    )


def test_scoring_degrades_to_the_pre_integration_shape_when_contract_unavailable(pool, monkeypatch):
    """契约层不可用时退回接入前口径，绝不让整个选择停摆。"""
    import builtins

    real_import = builtins.__import__

    def _blocked(name, *args, **kwargs):
        if name == "core.cross_device_responsiveness_contract":
            raise ImportError("simulated")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked)
    assert pool._responsiveness_factor("t-anything", 0.9) == 1.0
