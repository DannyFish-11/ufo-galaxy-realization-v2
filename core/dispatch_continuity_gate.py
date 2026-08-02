"""core/dispatch_continuity_gate.py — 下发口的 V1 会话连续性合法性门（Gate C）

修的是什么
----------
``core/unified_continuity_legality_authority`` 是「会话连续性是否合法」的**唯一**
规范权威，但此前它只守住了**结果回流口**（``galaxy_gateway/android/handlers/
task_lifecycle.py`` 的 ``TERMINAL_RESULT_INGESTION``）。全系统唯一的规范派发口
``CommandRouter.route_envelope()`` **从不询问它**。

后果不是纸面的：一台设备的 runtime attachment 已进入 terminal 态（``replaced`` /
``invalidated``，例如会话被顶替），它依然能被派发新命令；要等命令**真的执行完**、
结果回流时才在回流口被拒 —— 中间那次真实执行已经发生，拒不回来。

Gate C 与 Gate A 不是重复实现
-----------------------------
两者问的是两个不同的问题：

- **Gate A**（:mod:`core.source_execution_eligibility`）：这个**来源**有没有执行
  姿态？—— ``control_only`` 的手机不该本地执行。
- **Gate C**（本模块）：这个**动作**相对会话连续性合法吗？—— 陈旧 / 被顶替 /
  已失效的会话不该再下发。

一个看能力，一个看身份时效。两者都过才算可派发。

为什么 REJECT 阻断、REQUIRE_REVIEW 不阻断
------------------------------------------
这不是"放松"，是两种判定语义本来就不同：

``REJECT``
    权威**做出了判定**：身份已失效（terminal 态 / attachment id 不匹配）。
    这正是审计要求必须拒的情形 → 硬阻断。
``REQUIRE_REVIEW``
    权威**没能判定**。在本路径上它只有一个来源：
    ``core.attached_runtime_session_registry`` 导入失败。把"权威自己坏了"升级成
    "全系统一条命令都发不出去"，是自伤而不是防护 —— Gate A / Gate B 在同样处境
    下也都是降级放行 + 留痕，这里保持一致。

想要更严的部署可以显式打开 :data:`DISPATCH_CONTINUITY_LEGALITY_ENFORCEMENT_ENV`
（设为 ``strict``），默认不替运维做这个决定。

为什么独立成模块
----------------
这段逻辑最初直接写在 ``core/command_router.py`` 里，把那个文件从 5456 行推到
5651 行。该文件的 ``File Complexity Budget`` 上限是 3000 行（早已超标、被
grandfather 住），**门本来就是红的**——但"基线本来就红"不是继续把它推高的理由。
拆出来之后 command_router 只保留一处调用点，净行数比接入前更少。
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:  # pragma: no cover - typing only
    from core.schemas.task_envelope import TaskEnvelope

logger = logging.getLogger("Galaxy.DispatchContinuityGate")

DISPATCH_CONTINUITY_LEGALITY_ENFORCEMENT_ENV: str = "GALAXY_DISPATCH_CONTINUITY_LEGALITY_ENFORCEMENT"

DISPATCH_CONTINUITY_LEGALITY_GATE_APPLIED: str = (
    "COMMAND_ROUTER::DISPATCH_CONTINUITY_LEGALITY_GATE_V1: "
    "route_envelope() submits every envelope to "
    "core.unified_continuity_legality_authority.evaluate_continuity_legality() "
    "on the ONLINE_DISPATCH_ACCEPTANCE path as Gate C of the unified "
    "pre-dispatch constraint chain, BEFORE lifecycle mark_running and before "
    "any execution branching. "
    "A hard REJECT verdict blocks dispatch and returns a structured error; "
    "REQUIRE_REVIEW (authority could not determine) is recorded in "
    "_constraint_chain_trace and warned, and blocks only when "
    f"{DISPATCH_CONTINUITY_LEGALITY_ENFORCEMENT_ENV}=strict. "
    "Complements Gate A: Gate A gates on source execution posture, "
    "Gate C gates on session-continuity identity validity."
)

__all__ = [
    "DISPATCH_CONTINUITY_LEGALITY_ENFORCEMENT_ENV",
    "DISPATCH_CONTINUITY_LEGALITY_GATE_APPLIED",
    "build_dispatch_continuity_context",
    "evaluate_dispatch_continuity_legality",
]


def build_dispatch_continuity_context(envelope: "TaskEnvelope") -> Any:
    """把 envelope 的连续性身份字段翻译成 V1 的 ``ContinuityLegalityContext``。

    字段来源刻意与 ``route_envelope`` 里已有的 V3 slot 门保持一致（``metadata``
    的 ``session_id`` / ``runtime_attachment_session_id`` / ``continuity_*``），
    这样同一个 envelope 在两个门里被认成同一个身份，不会出现"V3 认得、V1 不认得"
    的错位。

    缺字段不是错误：V1 对空身份的判定是 ALLOW（见其 ``_check_session_identity``
    的 "cannot assert illegality" 分支）。所以本地 / 纯工具类 envelope 天然放行，
    只有真正带会话身份的跨设备派发才会被实质校验。
    """
    from core.unified_continuity_legality_authority import ContinuityLegalityContext

    meta: Dict[str, Any] = envelope.metadata or {}

    def _s(*keys: str) -> str:
        for k in keys:
            v = meta.get(k)
            if v:
                return str(v)
        return ""

    try:
        epoch = int(meta.get("continuity_epoch") or 0)
    except (TypeError, ValueError):
        # metadata 是外部可控的；一个坏 epoch 不该把整条派发链炸掉。
        epoch = 0

    return ContinuityLegalityContext(
        # target 是"发给谁"，source_device_id 是"谁发的"。连续性身份问的是
        # **发起方**的会话还算不算数，所以优先取 source_device_id。
        device_id=_s("source_device_id", "device_id"),
        runtime_session_id=_s("runtime_session_id", "session_id"),
        runtime_attachment_session_id=_s("runtime_attachment_session_id"),
        durable_session_id=_s("durable_session_id"),
        continuity_epoch=epoch,
        contract_id=_s("contract_id"),
        flow_id=_s("flow_id"),
        metadata={k: v for k, v in meta.items() if str(k).startswith("continuity_")},
    )


def evaluate_dispatch_continuity_legality(
    envelope: "TaskEnvelope",
    trace: Dict[str, Any],
    *,
    error_code: str,
) -> Optional[Dict[str, Any]]:
    """Gate C：向 V1 权威提交本次派发。

    Returns
    -------
    ``None``
        放行（含降级放行）。
    ``dict``
        阻断——一个可直接从 ``route_envelope`` 返回的结构化错误响应。

    权威本身不可用（导入失败 / 内部异常）时降级放行并在 *trace* 里留痕 ——
    与 Gate A / Gate B 的降级语义一致。留痕而不是静默，这样"门没跑"和
    "门跑了并放行"可以区分开，否则降级就是掩盖。
    """
    try:
        from core.unified_continuity_legality_authority import (
            ContinuityLegalityPath,
            ContinuityLegalityVerdict,
            evaluate_continuity_legality,
        )

        report = evaluate_continuity_legality(
            ContinuityLegalityPath.ONLINE_DISPATCH_ACCEPTANCE,
            build_dispatch_continuity_context(envelope),
        )
        verdict = report.verdict
        trace["continuity_legality_applied"] = True
        trace["continuity_legality_verdict"] = verdict.value
        trace["continuity_legality_reason"] = report.reject_reason or ""
    except Exception as _cl_exc:
        trace["continuity_legality_verdict"] = "unavailable"
        trace["continuity_legality_reason"] = str(_cl_exc)
        logger.debug(
            "route_envelope [constraint-chain/continuity-gate]: skipped (graceful degradation): %s",
            _cl_exc,
        )
        return None

    strict = os.environ.get(DISPATCH_CONTINUITY_LEGALITY_ENFORCEMENT_ENV, "").strip().lower() == "strict"
    should_block = verdict is ContinuityLegalityVerdict.REJECT or (
        strict and verdict is ContinuityLegalityVerdict.REQUIRE_REVIEW
    )

    if not should_block:
        if verdict is ContinuityLegalityVerdict.REQUIRE_REVIEW:
            logger.warning(
                "route_envelope [constraint-chain/continuity-gate]: "
                "REQUIRE_REVIEW（权威未能判定，非阻断）reason=%s task_id=%s —— 需要阻断请设置 %s=strict",
                report.reject_reason,
                envelope.task_id,
                DISPATCH_CONTINUITY_LEGALITY_ENFORCEMENT_ENV,
            )
        return None

    trace["continuity_legality_blocked"] = True
    logger.warning(
        "route_envelope [constraint-chain/continuity-gate]: dispatch BLOCKED verdict=%s reason=%s task_id=%s",
        verdict.value,
        report.reject_reason,
        envelope.task_id,
    )
    return {
        "request_id": envelope.task_id,
        "task_id": envelope.task_id,
        "trace_id": envelope.trace_id,
        "command_id": (envelope.metadata or {}).get("command_id", envelope.task_id),
        "device_id": "",
        "command": envelope.tool_name,
        "via": "command_router",
        "success": False,
        "result": None,
        "error_code": error_code,
        "error_message": (f"会话连续性合法性校验未通过（{verdict.value}）：{report.reject_reason or '无附加原因'}"),
        "latency_ms": 0.0,
        "_constraint_chain_trace": dict(trace),
    }
