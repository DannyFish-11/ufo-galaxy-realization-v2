"""tests/test_node_activation_policy.py
========================================

**125 个节点，每一个都得说得出"什么时候起"。**

修复前
------
:mod:`core.activation_policy` 定义了四档（``always_on`` / ``on_demand`` /
``lazy`` / ``shared``），但"哪个节点属于哪一档"只在
``registry/device_node_map.yaml`` 里回答过 —— 那是一张**设备 → 节点**的表，
磁盘上 125 个节点里只覆盖 7 个。运行时问"该不该起 Node_101"根本无从回答。

一处方案自我更正
----------------
一度打算把剩下 118 个逐条塞进 ``device_node_map.yaml``。那是错的：那张表的匹配键
是 ``device_type`` / ``transport`` / ``capabilities``，而 ``Node_101_CodeEngine``
这类节点根本不是设备驱动的 —— **没有任何 device_type 能表达"有人要生成代码"**。
硬塞进去会造出一百多条永远匹配不上的规则，比没有更糟：它看起来覆盖了，实际一条
也不会触发。

改成从既有元数据**推导**，这也是 ``node_dependencies.json`` 自己
``_startup_tier_model`` 写明的原则（"derived from existing metadata — no new
governance authority is introduced"）。

这份测试钉什么
--------------
1. 覆盖是**全量**的：磁盘上每个节点都有档位与判定来源，一个不落；
2. 判定顺序不许乱：设备表 > skip > core 组 > 默认 lazy；
3. 默认是 ``lazy`` 而不是 ``always_on`` —— "不知道什么时候需要它"绝不等于
   "应该一直开着"。这一条钉死了，才谈得上"容器起来后按需加载"；
4. ``skip`` 的节点必须真的是 ``None``（永不启动），不能被默认档兜成 lazy。
"""

from __future__ import annotations

import json
import pathlib

import pytest

from core.activation_policy import ActivationPolicy
from core.node_activation_policy import (
    SOURCE_CORE_GROUP,
    SOURCE_DEFAULT_LAZY,
    SOURCE_DEVICE_MAP,
    SOURCE_SKIP,
    activation_policy_coverage,
    resolve_activation_policy,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
NODES_DIR = REPO_ROOT / "nodes"


def _nodes_on_disk():
    return sorted(d.name for d in NODES_DIR.iterdir() if d.is_dir() and (d / "main.py").exists())


# ── 1. 全量覆盖 ──────────────────────────────────────────────────────────────


def test_every_node_on_disk_has_a_policy_and_a_reason():
    """一个不落 —— 而且每一档都说得出**为什么**是这一档。

    ``source`` 不是装饰:线上"这个节点为什么没起来"必须有答案，否则只能靠翻代码猜。
    """
    cov = activation_policy_coverage()
    on_disk = set(_nodes_on_disk())

    assert set(cov) == on_disk, f"漏了:{sorted(on_disk - set(cov))};多了:{sorted(set(cov) - on_disk)}"
    missing_reason = [n for n, v in cov.items() if not v["source"]]
    assert not missing_reason, f"这些节点定了档却说不出依据:{missing_reason}"


def test_policies_are_all_valid_values():
    """档位只能是四档之一，或者 None（永不启动）。"""
    valid = {p.value for p in ActivationPolicy} | {None}
    bad = {n: v["policy"] for n, v in activation_policy_coverage().items() if v["policy"] not in valid}
    assert not bad, f"出现了非法档位:{bad}"


# ── 2. 判定顺序 ──────────────────────────────────────────────────────────────


def test_device_mapped_nodes_take_the_device_map_value():
    """设备型节点以 ``device_node_map.yaml`` 为准 —— 那是人写的、有匹配条件的真规则。"""
    policy, source = resolve_activation_policy("Node_33_ADB")

    assert source == SOURCE_DEVICE_MAP
    assert policy is ActivationPolicy.ON_DEMAND, "Node_33_ADB 在设备表里是 on_demand"


def test_skip_beats_the_default_and_really_means_never():
    """``startup_policy: skip`` 的节点必须是 ``None``，不能被默认档兜成 lazy。

    这 6 个是 5 个 ``Node_XX_Reserved`` 占位符加上 ``Node_130_AutonomousCoding``
    —— 也就是说「130 节点」里编号最大的那个，**设计上就不参与运行**。
    """
    policy, source = resolve_activation_policy("Node_130_AutonomousCoding")

    assert policy is None, "skip 的节点被兜成了某一档"
    assert source == SOURCE_SKIP

    nevers = {n for n, v in activation_policy_coverage().items() if v["policy"] is None}
    declared = {
        n
        for n, c in json.loads((REPO_ROOT / "node_dependencies.json").read_text(encoding="utf-8"))["nodes"].items()
        if c.get("startup_policy") == "skip" and (NODES_DIR / n / "main.py").exists()
    }
    assert nevers == declared, f"永不启动的集合与声明不符:多 {nevers - declared};少 {declared - nevers}"


def test_core_group_is_always_on():
    """系统地基常驻 —— 这一档要小而明确。"""
    policy, source = resolve_activation_policy("Node_00_StateMachine")

    assert policy is ActivationPolicy.ALWAYS_ON
    assert source == SOURCE_CORE_GROUP


# ── 3. 默认必须是 lazy ───────────────────────────────────────────────────────


def test_the_default_is_lazy_not_always_on():
    """**这条是整件事的关键。**

    「不知道什么时候需要它」绝不等于「应该一直开着」。默认若是 ``always_on``，
    130 个节点就会全部常驻 —— 那既不现实，也正是"容器起来后按需加载"要避免的。
    """
    policy, source = resolve_activation_policy("Node_101_CodeEngine")

    assert policy is ActivationPolicy.LAZY, "非设备、非核心的节点默认应当是 lazy"
    assert source == SOURCE_DEFAULT_LAZY


def test_always_on_stays_a_small_minority():
    """常驻档不许膨胀。

    不写死具体数字（核心组会随架构调整），但"绝大多数节点不常驻"这条语义必须成立：
    一旦超过四分之一，说明有人在往核心组里塞东西，按需加载就名存实亡了。
    """
    cov = activation_policy_coverage()
    always_on = [n for n, v in cov.items() if v["policy"] == ActivationPolicy.ALWAYS_ON.value]

    assert len(always_on) <= len(cov) // 4, f"常驻节点 {len(always_on)}/{len(cov)} 太多了:{sorted(always_on)}"
    assert always_on, "一个常驻节点都没有 —— 地基没了"


def test_unknown_node_falls_back_to_lazy_not_a_crash():
    """问一个不存在的节点不该炸 —— 运行时可能拿到任何名字。"""
    policy, source = resolve_activation_policy("Node_999_不存在")

    assert policy is ActivationPolicy.LAZY
    assert source == SOURCE_DEFAULT_LAZY


# ── 4. 与设备表的一致性 ──────────────────────────────────────────────────────


def test_device_map_entries_for_missing_nodes_are_not_silently_counted():
    """设备表里指向**磁盘上不存在**的节点时，覆盖表里不该凭空多出条目。

    ``registry/device_node_map.yaml`` 目前有 4 条指向不存在的目录
    （Node_38_BLE / 41_MQTT / 42_CANbus / 48_Serial —— 与
    ``deploy/compose/full.yml`` 里那 5 个幽灵节点是同一批）。覆盖表按磁盘为准，
    不能把它们算进去，否则"125 个都有档"就成了假的。
    """
    cov = activation_policy_coverage()
    assert all((NODES_DIR / n / "main.py").exists() for n in cov), "覆盖表里出现了磁盘上不存在的节点"


@pytest.mark.parametrize("node_name", ["Node_33_ADB", "Node_47_Audio", "Node_00_StateMachine", "Node_101_CodeEngine"])
def test_resolution_is_stable_across_calls(node_name: str):
    """同一个节点问两次必须得到同一个答案 —— 不能受缓存/加载顺序影响。"""
    assert resolve_activation_policy(node_name) == resolve_activation_policy(node_name)


# ── 5. 接线:这套档位真的被消费了 ────────────────────────────────────────────


def test_engine_get_core_nodes_is_no_longer_empty():
    """``ActivationPolicyEngine.get_core_nodes()`` 必须真的返回东西。

    它原来只扫 ``registry/device_node_map.yaml`` 找 ``startup: always_on`` ——
    而那张表里**一条 always_on 都没有**（记的全是设备型节点，on_demand /
    lazy / shared）。于是这个方法**恒返回空表**，一直如此，不报错也没人发现：
    调用方拿到"核心启动集是空的"，只会以为本来就没有核心节点。

    接到本模块的推导之后它返回真实的地基节点集。这条同时也是本模块"有真实消费方"
    的证据 —— 一个算得出档位却没人用的表，和没有是一样的。
    """
    from core.activation_policy import get_engine

    core = get_engine().get_core_nodes()

    assert core, "get_core_nodes() 又回到空表了"
    expected = {n for n, v in activation_policy_coverage().items() if v["policy"] == ActivationPolicy.ALWAYS_ON.value}
    assert set(core) == expected, f"与档位表不一致:多 {set(core) - expected};少 {expected - set(core)}"


# ── 6. LAZY 的落地点:首次能力请求 ───────────────────────────────────────────
#
# 仓里定义了 TRIGGER_CAPABILITY_REQUEST，四档里 LAZY 的语义也白纸黑字写着「首次
# 能力请求时启动，然后保活」—— 但在此之前**全仓没有任何一处发出这个触发**。
# 103 个节点被定成 lazy，而 lazy 永远不会发生。


@pytest.fixture()
def executor_slot():
    """借用执行器插槽，用完必须还回去 —— 它是模块级单例。"""
    from core.node_activation_policy import get_activation_executor, set_activation_executor

    before = get_activation_executor()
    calls = []

    async def _exec(*, node_name, decision, device_type, transport):
        calls.append((node_name, decision.policy.value, decision.reason))
        return node_name

    set_activation_executor(_exec)
    yield calls
    set_activation_executor(before)


async def test_capability_request_starts_a_lazy_node(executor_slot):
    """这是修复前从未发生过的事:一次能力请求把 lazy 节点拉起来。"""
    from core.activation_policy import ActivationPolicyEngine
    from core.node_activation_policy import ensure_node_started

    started = await ensure_node_started("Node_101_CodeEngine", ActivationPolicyEngine.TRIGGER_CAPABILITY_REQUEST)

    assert started == "Node_101_CodeEngine", "lazy 节点没有被首次能力请求拉起来"
    assert executor_slot and executor_slot[0][1] == "lazy"


async def test_capability_request_does_not_drag_up_an_on_demand_node(executor_slot):
    """``on_demand`` 的节点要**真实设备**，不该被一次能力请求拽起来。

    不加这条判断的话，"有触发就起"会让 Node_33_ADB 在没有任何安卓设备时被拉起来
    —— 而它在那种情况下只能走 mock 兜底，等于凭空多一个空转进程。
    """
    from core.activation_policy import ActivationPolicyEngine
    from core.node_activation_policy import ensure_node_started

    started = await ensure_node_started("Node_33_ADB", ActivationPolicyEngine.TRIGGER_CAPABILITY_REQUEST)

    assert started is None, "on_demand 节点被能力请求拽起来了"
    assert not executor_slot, f"不该起却调用了执行器:{executor_slot}"


async def test_skip_nodes_are_never_started(executor_slot):
    """``skip`` 的节点任何触发都不许起 —— 包括 Node_130。"""
    from core.activation_policy import ActivationPolicyEngine
    from core.node_activation_policy import ensure_node_started

    for trigger in (
        ActivationPolicyEngine.TRIGGER_CAPABILITY_REQUEST,
        ActivationPolicyEngine.TRIGGER_DEVICE_REGISTERED,
        ActivationPolicyEngine.TRIGGER_BOOT,
    ):
        assert await ensure_node_started("Node_130_AutonomousCoding", trigger) is None, trigger
    assert not executor_slot


async def test_no_executor_means_no_crash_and_no_start():
    """没登记执行器时安静返回 None —— 单跑 core 的场景不能因此炸掉。"""
    from core.activation_policy import ActivationPolicyEngine
    from core.node_activation_policy import ensure_node_started, get_activation_executor, set_activation_executor

    before = get_activation_executor()
    set_activation_executor(None)
    try:
        assert (
            await ensure_node_started("Node_101_CodeEngine", ActivationPolicyEngine.TRIGGER_CAPABILITY_REQUEST) is None
        )
    finally:
        set_activation_executor(before)


async def test_executor_failure_is_swallowed(executor_slot):
    """执行器炸了不该把调用方的主流程带走 —— 拉不起来只是"能力暂时不可用"。"""
    from core.activation_policy import ActivationPolicyEngine
    from core.node_activation_policy import ensure_node_started, get_activation_executor, set_activation_executor

    before = get_activation_executor()

    async def _boom(*, node_name, decision, device_type, transport):
        raise RuntimeError("执行器炸了")

    set_activation_executor(_boom)
    try:
        assert (
            await ensure_node_started("Node_101_CodeEngine", ActivationPolicyEngine.TRIGGER_CAPABILITY_REQUEST) is None
        )
    finally:
        set_activation_executor(before)


async def test_call_node_actually_reaches_the_lazy_trigger(executor_slot):
    """``NodeRegistry.call_node`` 调一个还没起来的 lazy 节点时，必须真的发出触发。

    **判据是行为，不是 AST。** 先写的是"``node_registry.py`` 里存在一处
    ``ensure_node_started`` 调用"——变异验证当场证明它是弱的：把 ``call_node``
    里那句 ``await self._try_lazy_start(...)`` 掐掉之后，``ensure_node_started``
    依然留在 ``_try_lazy_start`` 的函数体里，AST 照样找得到，测试照样绿，而整条
    链其实已经断了。

    这里改成真的走一遍 ``call_node``：节点不在注册表里 → 应当触发惰性启动 →
    执行器被调到。掐断调用点就立刻红。
    """
    from core.node_registry import NodeRegistry

    registry = NodeRegistry()
    # Node_101_CodeEngine 是 lazy 档，且不在注册表里 —— 正是"首次能力请求"的场景。
    await registry.call_node("Node_101_CodeEngine", "ping", {}, allow_failover=False)

    assert executor_slot, "call_node 遇到未起来的 lazy 节点，却没有发出惰性启动触发"
    assert executor_slot[0][0] == "Node_101_CodeEngine"
    assert executor_slot[0][1] == "lazy"
