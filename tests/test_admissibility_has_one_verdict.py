#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_admissibility_has_one_verdict.py

钉住：**选择器与二元闸门对同一台设备给同一个结论**。

背景
====
readiness / participation / target-validation 这三个源，在仓里被合成了**两次**，各合各的：

* ``core/target_device_validator.validate_target_device()`` —— 二元闸门，
  ``command_router`` 派发前用。判据是 ``registered ∧ ready ∧ capability_match ∧
  orchestration_eligible``，其中 ``ready`` 是四维合取（registered/online/connected/routable）。
* ``core/runtime/source_dispatch_orchestrator._score_candidate()`` —— 候选打分。
  判据此前只查 ``registered ∧ routable``，**不查 online / connected**。

实测两处会打架：

    已注册、可路由、但**离线**   → 选择器给满分 100 放行，闸门判 valid=False
    已注册、可路由、但**断连**   → 同上

后果不是「多选了一台」：选择器选中它、路由器随后拒掉，失败表现为「派发错误」，
排查时指不到「选了一台不合格的设备」这一步。

变严不会新增饿死风险 —— 这条严格性下游本来就有（闸门是活的），选择器宽松只是把拒绝
推迟到一个更差的地方。
"""

from __future__ import annotations

import pytest

from core.device_readiness import DeviceReadinessSummary
from core.runtime.source_dispatch_orchestrator import _score_candidate


class _Participation:
    def __init__(self, eligible: bool = True, tier: str = "execution_endpoint") -> None:
        self.orchestration_eligible = eligible
        self.participant_tier = tier


def _gate_verdict(readiness: DeviceReadinessSummary, participation: _Participation) -> bool:
    """二元闸门 ``validate_target_device`` 的判据（能力维在打分侧不适用，这里不取）。"""
    return bool(readiness.ready and participation.orchestration_eligible)


def _selector_verdict(readiness, participation) -> bool:
    score, rejection = _score_candidate(
        "s", "d", readiness=readiness, participation=participation, reuse_eligible=False, posture=""
    )
    return score > 0 and not rejection


_CASES = [
    ("全通", dict(registered=True, online=True, connected=True, routable=True), True),
    ("离线", dict(registered=True, online=False, connected=True, routable=True), False),
    ("断连", dict(registered=True, online=True, connected=False, routable=True), False),
    ("不可路由", dict(registered=True, online=True, connected=True, routable=False), False),
    ("未注册", dict(registered=False, online=True, connected=True, routable=True), False),
]


@pytest.mark.parametrize("label,fields,expected", _CASES)
def test_selector_and_gate_agree(label, fields, expected):
    """两处判断必须一致 —— 这就是被修掉的那条。"""
    readiness = DeviceReadinessSummary(device_id="d", **fields)
    participation = _Participation()
    selector = _selector_verdict(readiness, participation)
    gate = _gate_verdict(readiness, participation)
    assert selector == gate, (
        f"{label}：选择器判 {selector}、闸门判 {gate} —— 选择器会选中一台路由器随后要拒的设备，"
        "失败表现为「派发错误」而不是「选了一台不合格的设备」。"
    )
    assert selector is expected


def test_the_disagreeing_cases_are_the_offline_ones():
    """判据必须**有区分度**：如果所有场景本来就一致，上面那条测不出东西。

    这一条钉的是「离线/断连确实是会打架的那两档」—— 它们是本次修复的全部内容，
    别有人把测试样本换成一堆本来就一致的场景。
    """
    lax = []  # 只查 registered ∧ routable 的旧口径
    for label, fields, _ in _CASES:
        readiness = DeviceReadinessSummary(device_id="d", **fields)
        old_pass = bool(readiness.registered and readiness.routable)
        if old_pass != _gate_verdict(readiness, _Participation()):
            lax.append(label)
    assert lax == ["离线", "断连"], f"打架的场景集合变了：{lax}"


def test_rejection_reason_names_the_missing_dimension():
    """拒因要指明缺的是 online 还是 connected —— 只写「不就绪」现场什么都查不到。"""
    offline = DeviceReadinessSummary(device_id="d", registered=True, online=False, connected=True, routable=True)
    _, rejection = _score_candidate(
        "s", "d", readiness=offline, participation=_Participation(), reuse_eligible=False, posture=""
    )
    assert "online" in rejection, f"拒因没指明缺哪一维：{rejection!r}"

    disconnected = DeviceReadinessSummary(device_id="d", registered=True, online=True, connected=False, routable=True)
    _, rejection2 = _score_candidate(
        "s", "d", readiness=disconnected, participation=_Participation(), reuse_eligible=False, posture=""
    )
    assert "connected" in rejection2, f"拒因没指明缺哪一维：{rejection2!r}"


def test_selection_consults_the_single_convergence():
    """候选选择必须取一次 ``evaluate_policy_convergence`` —— 三个源的唯一合成。

    钉的是**调用**，不是源码文本：解释它的注释里也写着这个名字。
    """
    import ast
    from pathlib import Path

    tree = ast.parse(
        (Path(__file__).resolve().parent.parent / "core" / "runtime" / "source_dispatch_orchestrator.py").read_text(
            encoding="utf-8"
        )
    )
    target = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "_select_target_from_candidates"
    )
    called = {
        (node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", ""))
        for node in ast.walk(target)
        if isinstance(node, ast.Call)
    }
    assert "evaluate_policy_convergence" in called, "候选选择没有取合成判据 —— 三个源又变回各合各的"


def test_readiness_gate_does_not_hand_pick_dimensions_again():
    """就绪闸不许再回到「只挑 registered 与 routable 两维」。"""
    import ast
    from pathlib import Path

    tree = ast.parse(
        (Path(__file__).resolve().parent.parent / "core" / "runtime" / "source_dispatch_orchestrator.py").read_text(
            encoding="utf-8"
        )
    )
    target = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "_score_candidate"
    )
    reads = {
        node.args[1].value
        for node in ast.walk(target)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
        and len(node.args) >= 2
        and isinstance(node.args[1], ast.Constant)
    }
    assert "ready" in reads, "就绪闸没有读 DeviceReadinessSummary.ready —— 判据又和闸门分家了"
