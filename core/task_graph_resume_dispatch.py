#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/task_graph_resume_dispatch.py
==================================
Feature ① 续跑闭环的执行端接线。

背景
----
``TaskGraphRuntime.resume_pending_dispatch()`` 是重启续跑的执行入口：对每个
"待执行态 + 依赖已满足"的节点调用注入的 ``dispatch_fn`` 重新派发。它的文档
说"dispatch_fn 由恢复协调器/主脑注入"，而 ``runtime_restart_recovery`` 的
Step 12 注释说"实际重派由启动序列注入 dispatch_fn 完成"——但在本模块出现
之前，全仓库没有任何生产代码真正接线，续跑闭环停在"只出报告、不重派"。

本模块提供 :func:`resume_durable_task_graph`，由 ``core.startup`` 在启动恢复
（Step 20）之后调用。派发策略：

* 仅在 ``GALAXY_DURABLE_EXEC`` 开启时被调用（调用方把关）——默认关闭时
  零行为变化，与 task_graph_runtime 的持久化契约一致。
* 每个节点先过 ② 派发幂等守卫（``durable_dispatch_idempotency``）：崩溃前
  已标记过的键说明副作用已经发生，绝不二次触发，仅将节点推回 DISPATCH。
* 载荷从 ``node.metadata["resume_args"]`` 恢复（由
  ``envelope_to_graph_node`` 在注册时保留）。载荷不可恢复的节点【拒绝】
  带空参数重跑——保持待执行态，由 ``resume_snapshot()`` 暴露给操作者。
* 重派统一走 canonical 路径 ``CommandRouter.route_envelope``。
"""

from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger("Galaxy.TaskGraphResumeDispatch")

# 本模块是 resume_pending_dispatch 的唯一生产接线点（启动序列专用）。
TASK_GRAPH_RESUME_DISPATCH_WIRED: str = (
    "TASK_GRAPH_RESUME_DISPATCH_WIRED_V1: core.startup calls "
    "resume_durable_task_graph() after Step 20 recovery when "
    "GALAXY_DURABLE_EXEC is enabled; dispatch goes through "
    "CommandRouter.route_envelope guarded by durable_dispatch_idempotency."
)


def _build_envelope_from_node(node: Any) -> Any:
    """Rebuild a faithful ``TaskEnvelope`` from a durable ``GraphNode``.

    Raises ``RuntimeError`` when the re-dispatch payload is unrecoverable —
    re-running a tool with empty args is worse than leaving the node pending.
    """
    meta: Dict[str, Any] = getattr(node, "metadata", None) or {}
    args = meta.get("resume_args")
    if not getattr(node, "tool_name", "") or not isinstance(args, dict):
        raise RuntimeError(
            f"resume payload unavailable for task {node.task_id!r} "
            f"(tool={getattr(node, 'tool_name', '')!r}) — left pending for operator review"
        )

    from core.schemas.task_envelope import TaskEnvelope

    kwargs: Dict[str, Any] = {
        "task_id": node.task_id,
        "source": "restart_resume",
        "tool_name": node.tool_name,
        "args": args,
    }
    if getattr(node, "trace_id", ""):
        kwargs["trace_id"] = node.trace_id
    if getattr(node, "session_id", ""):
        kwargs["session_id"] = node.session_id
    if getattr(node, "device_id", ""):
        kwargs["targets"] = [node.device_id]
    _timeout = meta.get("resume_timeout")
    if isinstance(_timeout, (int, float)) and _timeout > 0:
        kwargs["timeout"] = float(_timeout)
    _priority = meta.get("resume_priority")
    if isinstance(_priority, int) and 1 <= _priority <= 10:
        kwargs["priority"] = _priority
    return TaskEnvelope(**kwargs)


async def resume_durable_task_graph() -> Dict[str, Any]:
    """Run ``TaskGraphRuntime.resume_pending_dispatch`` over the canonical spine.

    Returns the runtime's resume result dict ``{"resumed": [...], "failed": [...]}``
    augmented with a ``"deduplicated"`` list of task_ids whose dispatch key was
    already marked before the crash (side effect already ran — not re-triggered).
    """
    from core.task_graph_runtime import get_task_graph_runtime

    tgr = get_task_graph_runtime()
    deduplicated: list = []

    async def _dispatch(node: Any) -> None:
        # ② 派发幂等守卫:崩前已标记的键 = 副作用已发生,绝不二次执行。
        from core.durable_dispatch_idempotency import (
            already_dispatched,
            dispatch_idempotency_enabled,
            dispatch_key_for,
        )

        key = dispatch_key_for({"task_id": node.task_id}) if dispatch_idempotency_enabled() else ""
        if key and already_dispatched(key):
            deduplicated.append(node.task_id)
            logger.info(
                "resume: task %s 崩溃前已派发过(幂等键命中),不二次触发副作用",
                node.task_id,
            )
            return

        envelope = _build_envelope_from_node(node)

        from core.command_router import get_command_router

        router = get_command_router()
        await router.route_envelope(envelope)

    result = await tgr.resume_pending_dispatch(_dispatch)
    result["deduplicated"] = deduplicated
    return result


__all__ = [
    "TASK_GRAPH_RESUME_DISPATCH_WIRED",
    "resume_durable_task_graph",
]
