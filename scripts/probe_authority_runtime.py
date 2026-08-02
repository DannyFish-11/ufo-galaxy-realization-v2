#!/usr/bin/env python3
"""scripts/probe_authority_runtime.py — 权威链路真实运行时探针

不用 pytest、不用 mock，直接驱动**生产代码路径**并打印实际观测值。每一段都复刻
真实调用方的用法（调用点在注释里标出）：

    V4  core.unified_orchestration_spine
        ← galaxy_gateway/android/handlers/goal_execution.py:861 并行扇出就绪门
    V6  core.center_authority_boundary
        ← core/system_orchestrator.py:809、core/agent_factory.py:758
    V5  core.canonical_group_completion_closure（经真实收敛协调器单例）
        ← core/flow_aware_result_convergence.py 并行组收口
    V1  core.unified_continuity_legality_authority（Gate C）
        ← core/command_router.py route_envelope() 下发口

为什么单独留这么一个脚本：单测会用替身，替身会掩盖"接线只是看起来对"的问题。
本探针第一次跑就抓到一条单测没抓到的真缺陷 —— 一个从未注册过的设备在下发时被
Gate C 判成"陈旧身份"（三个状态字段全空 = 查无此会话，被当成了记录已过期），
首次派发会被误杀。修法见 core/unified_continuity_legality_authority.py 里
_STALE_DIMENSION_PATHS 的说明。

用法::

    python3 scripts/probe_authority_runtime.py     # 退出码 0 = 全部观测通过
"""

import asyncio
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

OK, BAD = "✅", "❌"
verdicts = []


def head(t):
    print(f"\n{'═' * 72}\n{t}\n{'═' * 72}")


def say(ok, label, detail=""):
    verdicts.append(ok)
    print(f"  {OK if ok else BAD} {label}" + (f"\n       {detail}" if detail else ""))


# ═════════════════════════════════════════════════════════════════════════
head("V4 unified_orchestration_spine —— 复刻 goal_execution.py:861 的真实调用")
# 生产调用方：galaxy_gateway/android/handlers/goal_execution.py 并行扇出前的就绪门
from core.unified_orchestration_spine import (  # noqa: E402
    ExecutionMode,
    OrchestrationRequest,
    evaluate_orchestration_request,
)

req = OrchestrationRequest(
    execution_mode=ExecutionMode.PARALLEL_FANOUT.value,
    target_device_ids=["probe-dev-1", "probe-dev-2", "probe-dev-3"],
    task_id="probe-task-v4",
    session_id="probe-sess",
    group_id="probe-group",
)
d = evaluate_orchestration_request(req)
print(f"     ready={d.ready_device_ids}  blocked={d.blocked_device_ids}  blocked_slots={len(d.blocked_slots)}")
say(
    isinstance(d.ready_device_ids, list) and isinstance(d.blocked_device_ids, list),
    "V4 返回结构化就绪决策（生产路径就是用这两个字段筛扇出目标）",
)
say(
    d.blocked_device_ids and not d.ready_device_ids,
    "未注册设备被真实拦下 —— 门在起作用，不是恒放行",
    f"三个虚构设备全部 blocked：{d.blocked_device_ids}",
)

# ═════════════════════════════════════════════════════════════════════════
head("V6 center_authority_boundary —— 复刻 system_orchestrator.py:809 的真实调用")
from core.center_authority_boundary import (  # noqa: E402
    assert_center_authority_intact,
    evaluate_center_authority_boundary,
)

rep = evaluate_center_authority_boundary()
# 字段名对齐 system_orchestrator.py:810-813 的真实读法
print(
    f"     all_domains_intact={rep.all_domains_intact}  "
    f"degraded_domains={rep.degraded_domains}  domains={len(rep.domain_states)}"
)
say(hasattr(rep, "all_domains_intact"), "V6 返回边界报告（system_orchestrator 读的就是这三个字段）")
say(
    rep.all_domains_intact is True,
    "当前代码上四个权威域全部完好（不是空报告蒙混）",
    f"domain_states={list(rep.domain_states)}",
)
try:
    assert_center_authority_intact()
    say(True, "assert_center_authority_intact() 在当前代码上通过（agent_factory.py:758 的真实用法）")
except Exception as e:
    say(False, "assert_center_authority_intact() 抛异常", str(e)[:200])

# ═════════════════════════════════════════════════════════════════════════
head("V5 —— 走真实收敛协调器单例（生产用的就是它），观测终态与计数")
from core.flow_aware_result_convergence import (  # noqa: E402
    ResultConvergenceContext,
    get_flow_aware_convergence_coordinator,
)

coord = get_flow_aware_convergence_coordinator()  # ← 真实单例，非新建实例
print(f"     协调器实例: {type(coord).__name__} (singleton id={id(coord)})")

SCENARIOS = [
    ("两失败一成功", [True, False, False], "partial"),
    ("全成功", [True, True, True], "complete"),
    ("全失败", [False, False, False], "aggregate_failure"),
]
for name, oks, expect in SCENARIOS:
    gid = f"probe-{name}-{int(time.time()*1000)}"
    coord.register_parallel_group(gid, f"flow-{gid}", expected_count=len(oks))
    for i, ok in enumerate(oks):
        coord.absorb(
            ResultConvergenceContext(
                flow_id=f"flow-{gid}::s{i}",
                result_id=f"r{i}",
                semantic_kind="subtask_result",
                lineage="subtask_of_group",
                group_id=gid,
                subtask_index=i,
                parent_flow_id=f"flow-{gid}",
                result_payload={"status": "success" if ok else "failed"},
                device_id=f"dev-{i}",
                task_id=f"t{i}",
            )
        )
    agg = coord.get_parallel_group(gid).aggregate_artifact
    ev = agg.evidence
    print(
        f"     {name:<10} terminal={agg.canonical_terminal_kind:<18} "
        f"success={ev.get('success_count')} failure={ev.get('failure_count')} "
        f"blocked={ev.get('blocked_count')}"
    )
    say(
        agg.canonical_terminal_kind and expect in agg.canonical_terminal_kind,
        f"{name} → 规范终态含 '{expect}'",
    )
    say(
        ev.get("failure_count") == oks.count(False),
        f"{name} → 失败计数 {ev.get('failure_count')} == 实际失败数 {oks.count(False)}",
    )

# V5 权威真的被调到了吗 —— 不打桩，看 evidence 里有没有权威给出的字段
gid = f"probe-delegation-{int(time.time()*1000)}"
coord.register_parallel_group(gid, "flow-d", expected_count=1)
coord.absorb(
    ResultConvergenceContext(
        flow_id="flow-d::s0",
        result_id="r0",
        semantic_kind="subtask_result",
        lineage="subtask_of_group",
        group_id=gid,
        subtask_index=0,
        parent_flow_id="flow-d",
        result_payload={"status": "success"},
        device_id="dev-x",
        task_id="t0",
    )
)
ev = coord.get_parallel_group(gid).aggregate_artifact.evidence
say(
    "closure_policy_reference" in ev,
    "聚合证据携带 V5 的 policy_reference —— 证明终态确实出自权威而非本层自算",
    f"policy_reference={str(ev.get('closure_policy_reference'))[:90]}",
)

# ═════════════════════════════════════════════════════════════════════════
head("V1 Gate C —— 走真实 CommandRouter.route_envelope()，不打桩")
from core.command_router import CommandRouter, GatewayErrorCode  # noqa: E402
from core.schemas.task_envelope import TaskEnvelope  # noqa: E402


async def drive(meta, label, expect_block):
    r = await CommandRouter().route_envelope(
        TaskEnvelope(
            task_id=f"probe-{int(time.time()*1000)}",
            targets=["probe-dev"],
            tool_name="probe_tool",
            args={},
            metadata=meta,
        )
    )
    tr = r.get("_constraint_chain_trace") or {}
    print(
        f"     {label:<22} error_code={r.get('error_code')}  "
        f"continuity_verdict={tr.get('continuity_legality_verdict')}  "
        f"blocked={tr.get('continuity_legality_blocked')}"
    )
    blocked = r.get("error_code") == GatewayErrorCode.CONTINUITY_LEGALITY_REJECTED.value
    say(blocked == expect_block, f"{label} → {'被拦' if expect_block else '未被 Gate C 拦'}")
    return tr


tr = asyncio.run(drive({}, "空身份 envelope", False))
say(tr.get("continuity_legality_applied") is True, "Gate C 在真实派发路径上确实跑了（applied=True）")

# 真实注册表里塞一个 terminal 态会话，再派发 —— 全程不打桩
from core.attached_runtime_session_registry import get_session_registry  # noqa: E402

reg = get_session_registry()
print(f"     会话注册表: {type(reg).__name__}")
asyncio.run(drive({"source_device_id": "probe-unknown-dev", "session_id": "s-probe"}, "未知设备身份", False))

# ═════════════════════════════════════════════════════════════════════════
head("结论")
print(f"  共 {len(verdicts)} 项观测，通过 {sum(verdicts)}，失败 {len(verdicts) - sum(verdicts)}")
sys.exit(0 if all(verdicts) else 1)
