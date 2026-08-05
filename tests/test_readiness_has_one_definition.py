#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_readiness_has_one_definition.py

钉住「设备就绪」只有一处定义，且派发闸门**看真值**。

背景
====
「就绪」这件事此前在仓里被算了三遍，三遍还不一样：

1. ``core/device_readiness.list_ready_devices()`` 内联算
   ``registered and online and connected and routable``；
2. ``core/target_device_validator._readiness_gate()`` 把同一个表达式重打一遍；
3. ``core/runtime/source_dispatch_orchestrator`` 读 ``getattr(rs, "ready", False)``
   —— ``DeviceReadinessSummary`` **根本没有这个字段**，所以恒为 ``False``：派发记录里
   的 ``ready_to_route`` 与 ``readiness_summary.verdict`` 无论设备多健康都报 "blocked"。

同一份数据、三种读法，其中一种永远读错，而它不报错、不变慢，只是把一条假信息写进
派发记录。

第二件事：闸门被喂常量
======================
``resolve_android_execution_gate_decision()`` 的 ``policy_eligible`` 与
``readiness_ready`` 两个参数，在派发路径的**两个**调用点都被写死成字面 ``True``，
而真值就在同一作用域里躺着。实测该闸门在这两维上都会 deny
（``readiness_not_ready`` / ``policy_ineligible``），写死等于把这两条拒绝路径整个关掉。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from core.android_mode_gate_policy import resolve_android_execution_gate_decision
from core.device_readiness import DeviceReadinessSummary

_REPO = Path(__file__).resolve().parent.parent

#: 能力维必须先放行，否则四条用例全被 ``capability_unavailable`` 挡住 —— 那样就测不到
#: readiness / policy 这两维，属于判而不别。
_CAPABILITY_OK = {
    "execution_busy": False,
    "local_inference_available": True,
    "fallback_tier": "cloud",
    "model_ready": True,
}


# ---------------------------------------------------------------------------
# 一、就绪判据只有一处定义
# ---------------------------------------------------------------------------


def test_ready_is_a_real_attribute_not_a_missing_one():
    """``ready`` 必须真的存在。

    此前下游 ``getattr(rs, "ready", False)`` 拿到的是默认值 —— 一个恒假的判据，
    而故障现场只会看到「这台设备被报成 blocked」，指不回属性不存在这件事。
    """
    healthy = DeviceReadinessSummary(device_id="d", registered=True, online=True, connected=True, routable=True)
    assert healthy.ready is True
    assert healthy.to_dict()["ready"] is True, "ready 没有随对象上线，下游只能再算一遍"


@pytest.mark.parametrize("missing", ["registered", "online", "connected", "routable"])
def test_every_one_of_the_four_dimensions_can_block_ready(missing):
    """四维缺一不可 —— 逐维验证，避免「只要注册了就算就绪」这种松掉的实现也能通过。"""
    fields = {"registered": True, "online": True, "connected": True, "routable": True}
    fields[missing] = False
    assert DeviceReadinessSummary(device_id="d", **fields).ready is False, f"{missing}=False 时仍报就绪"


def test_no_module_recomputes_the_readiness_conjunction():
    """全仓不该再有第二处手打 ``registered and online and connected and routable``。

    钉源码：漏改一处的症状是「两个判据对同一台设备给出不同结论」，而两处各自看
    都很合理。
    """
    offenders = []
    for rel in (
        "core/device_readiness.py",
        "core/target_device_validator.py",
        "core/runtime/source_dispatch_orchestrator.py",
    ):
        tree = ast.parse((_REPO / rel).read_text(encoding="utf-8"))
        # 定义处本身当然要写这个合取 —— 把它整段排除，否则这条断言会把唯一定义
        # 也算成「重算」，那样它就永远红，等于没有判据。
        definition = next(
            (n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "ready"),
            None,
        )
        exempt = range(definition.lineno, (definition.end_lineno or definition.lineno) + 1) if definition else range(0)
        for node in ast.walk(tree):
            if not isinstance(node, ast.BoolOp) or not isinstance(node.op, ast.And):
                continue
            if node.lineno in exempt:
                continue
            names = set()
            for value in ast.walk(node):
                if isinstance(value, ast.Attribute):
                    names.add(value.attr)
                elif isinstance(value, ast.Constant) and isinstance(value.value, str):
                    names.add(value.value)
            if {"registered", "online", "connected", "routable"} <= names:
                offenders.append(f"{rel}:{node.lineno}")
    assert not offenders, f"这些地方在重算就绪判据：{offenders}。唯一定义是 DeviceReadinessSummary.ready。"


# ---------------------------------------------------------------------------
# 二、闸门看真值
# ---------------------------------------------------------------------------


def test_the_gate_actually_denies_on_readiness_and_policy():
    """前置条件：这两维**确实**会改变判决。

    如果闸门本来就忽略它们，那么「写死 True」与「传真值」等价，下面的钉子全是空的。
    """
    allow = resolve_android_execution_gate_decision(policy_eligible=True, readiness_ready=True, **_CAPABILITY_OK)
    assert allow.decision == "allow"
    assert (
        resolve_android_execution_gate_decision(policy_eligible=True, readiness_ready=False, **_CAPABILITY_OK).decision
        == "deny"
    )
    assert (
        resolve_android_execution_gate_decision(policy_eligible=False, readiness_ready=True, **_CAPABILITY_OK).decision
        == "deny"
    )


def test_an_offline_but_registered_device_is_denied():
    """已注册、可路由，但**离线** —— 这正是写死 True 时会被放过去的那一类。

    注意上游 ``_score_candidate`` 的前置闸只查 ``registered`` 与 ``routable``，
    不查 ``online`` / ``connected``，所以「前面已经把关过了」这个理由不成立。
    """
    offline = DeviceReadinessSummary(device_id="d", registered=True, online=False, connected=True, routable=True)
    assert offline.ready is False
    verdict = resolve_android_execution_gate_decision(
        policy_eligible=True, readiness_ready=offline.ready, **_CAPABILITY_OK
    )
    assert verdict.decision == "deny"
    assert "readiness_not_ready" in verdict.reasons


@pytest.mark.parametrize("func_name", ["_score_candidate", "_select_target_from_candidates"])
def test_dispatch_never_feeds_the_gate_a_literal_true(func_name):
    """派发路径的两个调用点都不许再给闸门喂字面 ``True``。

    钉的是**这两个关键字实参的字面量**，不是整段源码文本 —— 上面解释「为什么不能写死」
    的注释里也出现了 True 这个词，扫文本会被自己的散文骗到。
    """
    tree = ast.parse((_REPO / "core/runtime/source_dispatch_orchestrator.py").read_text(encoding="utf-8"))
    target = next(
        n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == func_name
    )
    literal_args = []
    for node in ast.walk(target):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
        if callee != "resolve_android_execution_gate_decision":
            continue
        for kw in node.keywords:
            if kw.arg in ("policy_eligible", "readiness_ready") and isinstance(kw.value, ast.Constant):
                literal_args.append(f"{kw.arg}={kw.value.value} @L{node.lineno}")
    assert not literal_args, (
        f"{func_name} 又把常量喂给闸门了：{literal_args}。"
        "真值就在同一作用域，写死等于把 readiness_not_ready / policy_ineligible "
        "两条拒绝路径在派发路径上整个关掉。"
    )
