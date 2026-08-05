#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_dispatch_selection_considers_reachability.py

钉住派发选目标时**网络可达性参与决策**这件事。

背景
====
`CommandRouter.route_envelope()` 在按 required_capabilities 挑目标时，原先只调
`core.capability_graph_selection.select_best_provider()`。那条评分是::

    total = coverage * 10.0 + kind_priority * 0.5 - (0.1 if offline else 0.0)

—— 三项里没有一项来自网络。于是"有这个能力、但那条路根本不通"的节点会被照常选中，
派过去必然失败再走重试。而 `core.network_topology_runtime` 是活的、有真实数据
（aip_transport / state_sync_bus / NATS / gateway 都在往里喂）。

更别扭的是，`COMMAND_ROUTER_DUAL_GRAPH_INTEGRATED` 这条哨兵**早就写着**本路由器
"经 core.capability_network_bridge 做 provider+path 联合决策"——但该模块从任何真实
入口都不可达，从未被 import 过。声明与事实不符。现已改成真的走它。

判据设计
========
用两个**能力面完全打平**的节点（同能力集、同 kind、同在线状态），只让网络状态不同，
并且刻意让不可达的那个在能力面排在前列。这样：

* 如果选择只看能力 → 选中不可达的那个（能力面第一个）
* 如果选择看了网络 → 选中可达的那个

分数不打平的话，这条测试就不判别了——赢家可能只是因为能力分高，跟网络没关系。
"""

from __future__ import annotations

import pytest

from core.capability_assimilation import assimilate_device, reset_capability_assimilation_layer
from core.capability_graph_selection import discover_providers, score_provider, select_best_provider
from core.capability_network_bridge import joint_select
from core.network_topology_runtime import get_network_topology_runtime

_CAP = "screen_probe_reachability"
_UNREACHABLE = "probe-node-unreachable"
_REACHABLE = "probe-node-reachable"


@pytest.fixture()
def two_tied_providers():
    """两个能力面完全等价的 provider，只有网络可达性不同。

    注册顺序刻意把**不可达**的那个放在前面，让它在能力面排第一。
    """
    reset_capability_assimilation_layer()
    for node_id in (_UNREACHABLE, _REACHABLE):
        assimilate_device(
            node_id,
            capabilities=[_CAP],
            host="10.0.0.1",
            port=9000,
            transport_hints={"preferred_path": "direct_ws"},
        )

    topo = get_network_topology_runtime()
    topo.absorb_device_connectivity(_REACHABLE, preferred_path="direct_ws", effective_routable=True)
    topo.absorb_device_connectivity(_UNREACHABLE, preferred_path="", effective_routable=False)
    yield
    reset_capability_assimilation_layer()


def test_capability_scores_are_tied_so_the_assertion_discriminates(two_tied_providers):
    """前提检查：两者能力分必须相等，否则下面那条测的就不是网络了。"""
    candidates = discover_providers(capabilities=[_CAP], require_online=True)
    scores = {c.node_id: score_provider(c, [_CAP]).total_score for c in candidates}
    assert _REACHABLE in scores and _UNREACHABLE in scores, f"两个探针节点没都进候选：{scores}"
    assert (
        scores[_REACHABLE] == scores[_UNREACHABLE]
    ), f"能力分不再打平（{scores}）—— 本用例的判别力依赖于打平，请重新构造探针节点"


def test_pure_capability_selection_would_pick_the_unreachable_one(two_tied_providers):
    """反面基准：只看能力时，选中的确实是那个不可达的节点。

    这条不是在要求"能力面必须选错"，而是把**旧行为**固定下来，
    好让下一条的差异确实来自网络维度，而不是来自别的偶然因素。
    """
    picked = select_best_provider(required_capabilities=[_CAP])
    assert picked is not None
    assert picked.node_id == _UNREACHABLE, f"能力面首选变成了 {picked.node_id}——探针构造失效，下一条用例不再具有判别力"


def test_joint_selection_picks_the_reachable_one(two_tied_providers):
    """联合选择必须避开不可达节点。"""
    result = joint_select(required_capabilities=[_CAP])
    assert result.selected_provider_id == _REACHABLE, (
        f"联合选择选了 {result.selected_provider_id}，没有避开不可达节点 "
        f"(path={result.path_availability.effective_path} "
        f"reachable={result.path_availability.is_reachable})"
    )
    assert result.path_availability.is_reachable is True


def test_command_router_dispatch_path_actually_calls_the_bridge():
    """派发路径必须真的走桥，而不是只在哨兵里声称走了。

    `COMMAND_ROUTER_DUAL_GRAPH_INTEGRATED` 这条哨兵曾经声称路由器经
    capability_network_bridge 做联合决策，实际却从未 import 过——这条测试就是防
    那种"声明与事实不符"再次发生。

    判据是**行为**不是源码文本：把 joint_select 换成一个记录调用的桩，跑真实的
    route_envelope，然后看它到底被叫到没有。钉源码字符串的话，改个换行或者改成
    `import core.capability_network_bridge as _b` 就假红，而真把调用删掉却可能假绿。
    """
    import asyncio
    from unittest.mock import MagicMock, patch

    from core.command_router import CommandRouter
    from core.schemas.task_envelope import TaskEnvelope

    calls = []
    real_joint = joint_select

    def _recording_joint(*args, **kwargs):
        calls.append((args, kwargs))
        return real_joint(*args, **kwargs)

    # ACL 闸口在能力选择**之前**，默认会拦下这个合成信封；放行它才能走到选择那一步。
    allow = MagicMock()
    allow.allowed = True
    acl = MagicMock()
    acl.check.return_value = allow

    router = CommandRouter()
    envelope = TaskEnvelope(
        task_id="probe-joint-call",
        trace_id="probe-joint-trace",
        source="test",
        targets=[],  # 不给显式目标，才会走能力选择
        tool_name="test_tool",
        args={},
        required_capabilities=[_CAP],
    )

    with (
        patch("core.capability_network_bridge.joint_select", side_effect=_recording_joint),
        patch("core.acl_enforcer.get_acl_enforcer", return_value=acl),
    ):
        asyncio.run(router.route_envelope(envelope))

    assert calls, (
        "route_envelope 没有调用 capability_network_bridge.joint_select —— "
        "派发选目标又退回成只看能力、不看网络了"
    )
    assert calls[0][1].get("required_capabilities") == [_CAP], f"传给桥的能力集不对：{calls[0]}"
