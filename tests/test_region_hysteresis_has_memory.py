#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_region_hysteresis_has_memory.py

钉住：认知区域的滞回**有记忆** —— 反复横跳会抬高进入 manifest 的门槛。

背景
====
``StateInterpreter`` 的类 docstring 一直写着「uses hysteresis (via
:class:`LiminalDynamics`)」。那句话**从来不成立**：全仓没有任何地方 import 过
``LiminalDynamics``，``_apply_hysteresis`` 里只有数值滞回。

数值滞回对「反复横跳」是没有记忆的 —— 跳一百次和跳一次判得一模一样。而区域是真的
驱动行为的（``cognitive_execution_policy._REGION_HINT_MAP``）：

    liminal  → PLANNING / PREFER_PLANNING / HEAVY   / 激活预算 0.6
    manifest → DIRECT   / PREFER_LOCAL    / STANDARD / 激活预算 1.0

刻意没接的那一半
================
``can_transition_to_manifest()`` 的时间驻留闸**不接**。实测三个场景：1.5s 驻留压住了
振荡的两个，但把「分数稳定高、本来就该直接进 manifest」的那个也一起压住了。原因是
驻留闸在转移发生的**那一刻**分不出「这次越界之后会掉回来」和「这次越界是对的」——
二者当时长得一模一样。取值域留在配置里，要开得先有一个能分开这两种情形的判据。
"""

from __future__ import annotations

import pytest

from core.cognitive.liminal_dynamics import get_liminal_dynamics, reset_liminal_dynamics
from core.cognitive.state_interpreter import CognitiveRegion, StateInterpreter

#: 把波动顶到满的热身序列：高分与「uncertainty 越 cap」交替，制造方向反转。
_OSCILLATION_WARMUP = [(0.80, 0.75, 0.10), (0.80, 0.75, 0.72)] * 4

#: 落在阻尼带里的分数（0.6574）：高于基础阈值 0.65，低于 0.65 + 最大调整 0.07。
#: **判据必须落在这条带里** —— 带外的分数接不接都一样，测带外等于判而不别。
_IN_BAND_SAMPLE = {"manifest_pressure": 0.70, "activation": 0.68, "uncertainty": 0.10}


@pytest.fixture(autouse=True)
def _fresh_dynamics():
    reset_liminal_dynamics()
    yield
    reset_liminal_dynamics()


def _feed(interpreter, samples):
    return [
        interpreter.interpret_snapshot({"manifest_pressure": mp, "activation": act, "uncertainty": unc}).region.value
        for mp, act, unc in samples
    ]


# ---------------------------------------------------------------------------
# 一、记账在跑 —— 它是阻尼判据的唯一数据来源
# ---------------------------------------------------------------------------


def test_region_changes_are_recorded_as_transitions():
    """区域每变一次就必须记一笔。

    漏记的后果不是「少一条日志」：波动完全由转移历史算，漏一次，之后所有阻尼都按
    一份不完整的历史算，而调整量看起来仍是个正常数字。
    """
    interpreter = StateInterpreter()
    _feed(interpreter, _OSCILLATION_WARMUP)
    assert (
        get_liminal_dynamics().state_dict()["transition_count"] >= 4
    ), "区域反复变化却没有被记账 —— 波动恒为 0、阻尼恒为 0，等于没接。"


def test_oscillation_raises_the_manifest_threshold():
    interpreter = StateInterpreter()
    _feed(interpreter, _OSCILLATION_WARMUP)
    snap = get_liminal_dynamics().state_dict()
    assert snap["volatility"] > 0.3, f"横跳了 8 拍波动仍是 {snap['volatility']}"
    assert snap["threshold_adjustment"] > 0, "波动起来了但阈值没被抬高 —— 调整量没接进判定"


# ---------------------------------------------------------------------------
# 二、阻尼真的改变了决策（不是只改了个可观测数字）
# ---------------------------------------------------------------------------


def test_damping_actually_flips_a_decision_inside_the_band():
    """同一个分数、同一个起始区域，接阻尼判 liminal、旁路判 manifest。

    这是**唯一**能证明「接进去了」而不是「接了个空转」的判据：阻尼只在
    ``[阈值, 阈值+调整)`` 这条带里改变结论，所以样本必须落在带里。
    """

    def _run(bypass_damping: bool) -> str:
        reset_liminal_dynamics()
        interpreter = StateInterpreter()
        if bypass_damping:
            interpreter._dynamics = staticmethod(lambda: None)
        _feed(interpreter, _OSCILLATION_WARMUP)
        interpreter._last_region = CognitiveRegion.LIMINAL
        return interpreter.interpret_snapshot(dict(_IN_BAND_SAMPLE)).region.value

    assert _run(bypass_damping=True) == "manifest", "前置条件：不接阻尼时这个分数应当进 manifest"
    assert _run(bypass_damping=False) == "liminal", (
        "接了阻尼之后同一个分数仍然进 manifest —— 调整量没有真的进入判定，" "整条接入是空转的。"
    )


# ---------------------------------------------------------------------------
# 三、不误伤：分数稳定高的请求不该被压住
# ---------------------------------------------------------------------------


def test_a_steadily_high_score_is_never_damped():
    """对照组。没有横跳就没有波动，阻尼必须完全不介入。

    这一条是接入的**安全边界**：压住这种请求等于让一个本该 direct/预算 1.0 的
    紧急请求拿到 planning/预算 0.6，而故障现场只会看到「它今天有点慢」。
    """
    interpreter = StateInterpreter()
    regions = _feed(interpreter, [(0.90, 0.90, 0.05)] * 5)
    assert "manifest" in regions, f"稳定高分被压住了：{regions}"
    assert get_liminal_dynamics().state_dict()["threshold_adjustment"] == 0.0


def test_dwell_gate_is_deliberately_not_wired():
    """时间驻留闸刻意没接 —— 这一条钉的是「别有人顺手把它加上」。

    它会连稳定高分的请求一起压住（实测），而那正是上一条测试守的边界。
    要接得先有一个能分开「越界之后会掉回来」与「越界是对的」的判据。
    """
    import ast
    import inspect
    import textwrap

    # 必须查**真实调用**而不是子串：上面那段解释「为什么不接」的注释本身就写着
    # can_transition_to_manifest，子串检查会被自己的散文骗到。
    tree = ast.parse(textwrap.dedent(inspect.getsource(StateInterpreter._apply_hysteresis)))
    called = {
        node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "can_transition_to_manifest" not in called, (
        "时间驻留闸被接进了 _apply_hysteresis。它在转移发生的那一刻分不出振荡与合法"
        "越界，会把稳定高分的请求一起压住 —— 见 test_a_steadily_high_score_is_never_damped。"
    )
    assert "manifest_threshold_adjustment" in called, "阻尼调整量没有被调用 —— 接入是空的"
    assert "record_transition" in called, "转移记账没有被调用 —— 波动恒为 0"


# ---------------------------------------------------------------------------
# 四、取不到 dynamics 时退化为原来的纯数值滞回
# ---------------------------------------------------------------------------


def test_falls_back_to_plain_hysteresis_when_dynamics_unavailable():
    interpreter = StateInterpreter()
    interpreter._dynamics = staticmethod(lambda: None)
    regions = _feed(interpreter, [(0.90, 0.90, 0.05)] * 3)
    assert regions[-1] == "manifest", "dynamics 缺席时区域判定应当照旧工作"
