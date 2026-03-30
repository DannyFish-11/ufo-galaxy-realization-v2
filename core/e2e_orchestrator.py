"""
Galaxy - 端到端编排器（便捷接口）
================================

**Architecture role: CONVENIENCE FACADE over the canonical execution chain**
------------------------------------------------------------------------------
``e2e_orchestrator`` is a **convenience facade** — it is NOT a parallel
top-level orchestration authority.  All actual execution passes through the
canonical chain::

    process_user_input()          ← facade entry (this module)
        → DesktopPresenceRuntime  ← runtime shell
            → OpenClawd           ← subject/execution core (authority)
                → CommandRouter   ← canonical orchestration authority
                    → DeviceRouter ← canonical device dispatch authority

This module MUST NOT hold independent dispatch authority or bypass OpenClawd.
Any new orchestration feature should be added to OpenClawd / CommandRouter,
with this facade simply delegating to those components.

E2E_ORCHESTRATOR_ROLE sentinel: "convenience_facade"

提供 process_user_input() 函数作为统一入口，
内部委托给 DesktopPresenceRuntime（控制面）再流转到
ConstellationRuntime.run() / EndToEndPipeline.execute()。

PR-5 DAG 集成
-------------
当 ``enable_task_dag=true``（config.json）时，该模块同时暴露
:func:`compile_and_run_dag` 便捷入口，将高级计划编译成
:class:`~core.task_graph.TaskGraph` 并并行执行。
若 DAG 编译失败，会自动回退到现有线性执行路径并记录警告。

PR-2 多设备执行收口
-------------------
所有显式跨多设备的任务（``targets`` 列表 > 1）强制经过 TaskGraph，
不存在旁路执行路径。入口函数 :func:`run_multi_device_via_task_graph`
暴露为顶层 API，orchestrator 可直接调用。

用法:
    from core.e2e_orchestrator import process_user_input

    result = await process_user_input(
        message="帮我在手机上打开微信",
        device_id="pc_01",
        session_id=None,          # 自动分配
        user_id="default",
    )
"""

import logging
import uuid as _uuid_mod
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.E2EOrchestrator")

# ---------------------------------------------------------------------------
# Architecture role declaration
# ---------------------------------------------------------------------------

E2E_ORCHESTRATOR_ROLE: str = "convenience_facade"
"""Role sentinel: e2e_orchestrator is a convenience facade over the canonical
execution chain (OpenClawd → CommandRouter → DeviceRouter).  It MUST NOT act
as an independent orchestration authority."""




# ---------------------------------------------------------------------------
# PR-5: DAG execution helpers
# ---------------------------------------------------------------------------

def _is_dag_enabled() -> bool:
    """Return True when the task-DAG feature flag is on."""
    try:
        from core.unified_config import get_config
        cfg = get_config()
        if hasattr(cfg, "get"):
            return bool(cfg.get("enable_task_dag", True))
        return bool(getattr(cfg, "enable_task_dag", True))
    except Exception:
        return True  # default-on when config unavailable


async def compile_and_run_dag(
    subtasks: List[Any],
    *,
    trace_id: str = "",
    runtime_session_id: str = "",
    context: Optional[Dict[str, Any]] = None,
    continue_on_failure: bool = True,
) -> Dict[str, Any]:
    """Compile a list of subtask objects into a :class:`~core.task_graph.TaskGraph`
    and execute it with parallel scheduling.

    This is the PR-5 DAG execution path.  It is used internally by
    :func:`process_user_input` when ``enable_task_dag`` is ``True`` and a plan
    is available, and may also be called directly by orchestrators that already
    hold a decomposed subtask list.

    Args:
        subtasks:            List of objects with ``task_id``, ``name``,
                             ``description``, ``depends_on``, ``device_id``
                             attributes (compatible with
                             :class:`~core.schemas.orchestration.SubTask`).
        trace_id:            Trace identifier propagated into every node.
        runtime_session_id:  Session identifier propagated into every node.
        context:             Additional key-value context for handlers.
        continue_on_failure: When ``True`` (default), failed nodes skip their
                             dependents; independent branches keep running.

    Returns:
        Dict with keys ``success``, ``done``, ``failed``, ``skipped``,
        ``elapsed_ms``, ``graph_id``, ``trace_id``, ``node_statuses``.
    """
    from core.task_graph import compile_subtasks_to_graph, RetryPolicy

    # Read retry defaults from config
    max_retries = 1
    retry_delay = 1.0
    try:
        from core.unified_config import get_config
        cfg = get_config()
        _get = cfg.get if hasattr(cfg, "get") else lambda k, d: getattr(cfg, k, d)
        max_retries = int(_get("task_dag_default_max_retries", 1))
        retry_delay = float(_get("task_dag_retry_delay_seconds", 1.0))
    except Exception:
        pass

    policy = RetryPolicy(max_retries=max_retries, retry_delay_seconds=retry_delay)

    try:
        graph = compile_subtasks_to_graph(
            subtasks,
            trace_id=trace_id,
            runtime_session_id=runtime_session_id,
            default_retry_policy=policy,
        )
    except ValueError as exc:
        logger.warning(
            "compile_and_run_dag: DAG compilation failed (%s), "
            "caller should fall back to linear execution.",
            exc,
        )
        return {
            "success": False,
            "error": f"DAG compilation failed: {exc}",
            "graph_id": "",
            "trace_id": trace_id,
            "done": 0,
            "failed": 0,
            "skipped": 0,
            "elapsed_ms": 0.0,
            "node_statuses": {},
        }

    result = await graph.execute(
        context=context or {},
        continue_on_failure=continue_on_failure,
    )
    return {
        "success": result.success,
        "graph_id": result.graph_id,
        "trace_id": result.trace_id,
        "done": result.done_nodes,
        "failed": result.failed_nodes,
        "skipped": result.skipped_nodes,
        "elapsed_ms": result.elapsed_ms,
        "node_statuses": result.node_statuses,
        "error": result.error,
    }


# ---------------------------------------------------------------------------
# PR-2: Multi-device execution entry point — always routes through TaskGraph
# ---------------------------------------------------------------------------


async def run_multi_device_via_task_graph(
    subtasks: List[Any],
    *,
    trace_id: str = "",
    runtime_session_id: str = "",
    context: Optional[Dict[str, Any]] = None,
    continue_on_failure: bool = True,
    policy: Optional[Any] = None,
) -> Dict[str, Any]:
    """Execute *subtasks* across multiple devices **always** via TaskGraph.

    This is the PR-2 canonical multi-device entry point.  Unlike
    :func:`compile_and_run_dag`, this function never falls back to linear
    execution; callers that need a fallback must handle the returned
    ``{"success": False, ...}`` dict explicitly.

    All commands dispatched through this function are wrapped in a
    :class:`~core.unified.command_envelope.CommandEnvelope` and logged
    at DEBUG level for traceability.

    Args:
        subtasks:            List of subtask objects with ``task_id``, ``name``,
                             ``device_id`` and optional ``depends_on`` fields.
        trace_id:            Distributed trace identifier.
        runtime_session_id:  Session identifier.
        context:             Additional execution context.
        continue_on_failure: If ``True`` (default), independent branches keep
                             running when a node fails.
        policy:              Optional :class:`~core.execution_policy.ExecutionPolicy`
                             (PR-12).  When supplied and
                             ``cross_device_allowed=False``, the function
                             returns a ``cross_device_not_allowed`` result
                             immediately without dispatching to the TaskGraph.

    Returns:
        Dict with keys ``success``, ``done``, ``failed``, ``skipped``,
        ``elapsed_ms``, ``graph_id``, ``trace_id``, ``node_statuses``.
        When blocked by policy, ``policy_outcome`` carries the stable code.
    """
    if not subtasks:
        return {
            "success": True,
            "done": 0,
            "failed": 0,
            "skipped": 0,
            "elapsed_ms": 0.0,
            "graph_id": "",
            "trace_id": trace_id,
            "node_statuses": {},
        }

    trace_id = trace_id or f"trace_{_uuid_mod.uuid4().hex[:12]}"
    runtime_session_id = runtime_session_id or f"session_{_uuid_mod.uuid4().hex[:12]}"

    # ── PR-12: Cross-device policy enforcement ────────────────────────────────
    if policy is not None:
        try:
            from core.execution_policy.policy_enforcement import enforce_cross_device
            cross_device_decision = enforce_cross_device(
                policy,
                context={"trace_id": trace_id, "subtask_count": len(subtasks)},
            )
            if not cross_device_decision.is_allowed:
                logger.info(
                    "PR-2 run_multi_device_via_task_graph: blocked by policy | "
                    "outcome=%s reason=%s | trace_id=%s",
                    cross_device_decision.outcome.value,
                    cross_device_decision.reason,
                    trace_id,
                )
                return {
                    "success": False,
                    "done": 0,
                    "failed": 0,
                    "skipped": len(subtasks),
                    "elapsed_ms": 0.0,
                    "graph_id": "",
                    "trace_id": trace_id,
                    "node_statuses": {},
                    "policy_outcome": cross_device_decision.outcome.value,
                    "policy_band": (
                        policy.policy_band.value
                        if hasattr(policy, "policy_band")
                        else None
                    ),
                    "policy_reason": cross_device_decision.reason,
                    "error": cross_device_decision.hint,
                }
        except Exception as _policy_exc:
            # Never block the execution path because of a policy check error
            logger.debug(
                "run_multi_device_via_task_graph: policy check error (non-fatal): %s",
                _policy_exc,
            )

    # Log canonical envelope creation for observability
    try:
        from core.unified.command_envelope import CommandEnvelope, log_command_envelope
        env = CommandEnvelope(
            trace_id=trace_id,
            runtime_session_id=runtime_session_id,
            task_id=f"multi_device_{_uuid_mod.uuid4().hex[:8]}",
            device_id="*",
            payload={"subtask_count": len(subtasks)},
        )
        log_command_envelope(env, event="multi_device_task_graph_entry")
    except Exception:
        pass  # never block execution path for observability

    logger.info(
        "PR-2 run_multi_device_via_task_graph: routing %d subtasks through TaskGraph "
        "| trace_id=%s session=%s",
        len(subtasks),
        trace_id,
        runtime_session_id,
    )

    # Delegate to the canonical DAG executor — no bypass
    return await compile_and_run_dag(
        subtasks,
        trace_id=trace_id,
        runtime_session_id=runtime_session_id,
        context=context,
        continue_on_failure=continue_on_failure,
    )


async def process_user_input(
    message: str,
    device_id: str = "",
    session_id: Optional[str] = None,
    user_id: str = "default",
    context: Optional[List[Dict]] = None,
    use_constellation: bool = True,
    entry_mode: Optional[str] = None,
    target_device: Optional[str] = None,
) -> Dict[str, Any]:
    """
    统一用户输入处理入口。

    完整链路:
      唤醒 → 会话管理 → DesktopPresenceRuntime（三态控制面）
      → ConstellationRuntime / EndToEndPipeline → 结果广播

    所有顶层 E2E 请求统一通过 :class:`~core.desktop_presence_runtime.DesktopPresenceRuntime`
    处理，保证三态推进（silent→liminal→manifest→silent）闭环及
    ``runtime_session_id`` 全链路透传。

    降级行为:
    - 若 DesktopPresenceRuntime 不可用，则直接调用 ConstellationRuntime
      并打印警告；再不可用则降级到 EndToEndPipeline。
    - 传入 ``use_constellation=False`` 可显式绕过 ConstellationRuntime（已废弃，
      仍触发警告）。

    Args:
        message: 用户输入文本
        device_id: 来源设备 ID
        session_id: 会话 ID（可选，为 None 时自动创建/复用）
        user_id: 用户 ID（用于跨设备会话关联）
        context: 额外上下文（可选）
        use_constellation: 是否优先走 ConstellationRuntime（默认 True）
        entry_mode: Optional caller-supplied execution mode override
            (``"local"`` | ``"cross_device"`` | ``"hybrid"``).  When absent
            the mode is auto-resolved inside :func:`resolve_entry_mode`.
        target_device: Optional explicit target device ID.  When provided
            (and cross-device routing is enabled) forces ``"cross_device"``
            mode regardless of online device count.

    Returns:
        {
            "success": bool,
            "reply": str,
            "session_id": str,
            "mode": str,       # "chat" | "device_control" | "agent_task" | "fallback" | "dag"
            "data": {...},
            "devices_notified": [str],
            "runtime_session_id": str,
        }
    """
    # ── Guardrail: warn when ConstellationRuntime is explicitly bypassed ──────
    if not use_constellation:
        import uuid as _uuid
        _ctx0 = context[0] if context and isinstance(context[0], dict) else {}
        _trace_id = _ctx0.get("trace_id") or _uuid.uuid4().hex[:12]
        logger.warning(
            "LEGACY PATH GUARDRAIL [E2EOrchestrator]: use_constellation=False — "
            "ConstellationRuntime is being bypassed in favour of EndToEndPipeline. "
            "trace_id=%s  message=%r  "
            "Recommendation: remove use_constellation=False and migrate to "
            "core.constellation_runtime.get_constellation_runtime().",
            _trace_id,
            message[:80],
        )

    # ── PR-5 EntryMode: resolve execution mode (with target_device support) ──
    _resolved_entry_mode = "local"
    try:
        from core.unified.entrypoint_router import resolve_entry_mode as _resolve_em
        _resolved_entry_mode = _resolve_em(
            explicit_entry_mode=entry_mode or None,
            target_device=target_device or None,
            source="core.e2e_orchestrator",
        )
    except Exception as _em_exc:
        logger.debug("resolve_entry_mode failed (non-fatal): %s", _em_exc)

    # ── Primary path: DesktopPresenceRuntime（控制面）────────────────────────
    try:
        from core.desktop_presence_runtime import get_desktop_presence_runtime
        runtime = get_desktop_presence_runtime()
        result = await runtime.handle_request(
            message=message,
            source="e2e",
            device_id=device_id,
            session_id=session_id,
            user_id=user_id,
            context=context,
            use_constellation=use_constellation,
            entry_mode=_resolved_entry_mode,
        )
        # Normalise: e2e callers expect "reply" not "response"
        if "reply" not in result:
            result["reply"] = result.get("response", "")
        result.setdefault("devices_notified", [])
        return result
    except Exception as exc:
        logger.warning(
            "DesktopPresenceRuntime unavailable in E2EOrchestrator, falling back: %s", exc
        )

    # ── Fallback: ConstellationRuntime 优先路径 ──────────────────────────────
    if use_constellation:
        try:
            from core.constellation_runtime import get_constellation_runtime
            runtime = get_constellation_runtime()
            ctx: Dict[str, Any] = {
                "user_id": user_id,
                "use_constellation": True,
            }
            if context:
                for item in context:
                    if isinstance(item, dict):
                        ctx.update(item)
            result = await runtime.run(
                task_description=message,
                device_id=device_id,
                session_id=session_id,
                user_id=user_id,
                context=ctx,
            )
            # PR-5: when the result carries a subtask list, fan out through
            # the TaskGraph engine for parallel execution and per-node
            # lifecycle observability (gated by enable_task_dag flag).
            _subtasks = result.get("subtasks") or result.get("data", {}).get("subtasks")
            if _subtasks and _is_dag_enabled():
                import uuid as _uuid
                _trace = result.get("trace_id") or ctx.get("trace_id") or _uuid.uuid4().hex[:12]
                _session = result.get("runtime_session_id") or session_id or ""
                logger.info(
                    "E2EOrchestrator: compiling %d subtasks into TaskGraph | trace_id=%s",
                    len(_subtasks),
                    _trace,
                )
                try:
                    _dag_result = await compile_and_run_dag(
                        _subtasks,
                        trace_id=_trace,
                        runtime_session_id=_session,
                        context={"device_id": device_id, "user_id": user_id},
                    )
                    result.setdefault("data", {})["dag"] = _dag_result
                    # mode="dag" signals that the response was produced via parallel
                    # TaskGraph execution (PR-5). Other possible values set by the
                    # runtime are "chat", "device_control", "agent_task", "fallback".
                    result["mode"] = "dag"
                except Exception as _dag_exc:
                    logger.warning(
                        "E2EOrchestrator: TaskGraph execution failed, "
                        "results from ConstellationRuntime used as-is: %s",
                        _dag_exc,
                    )
            return {
                "success": result.get("success", False),
                "reply": result.get("reply", ""),
                "session_id": result.get("session_id", session_id or ""),
                "mode": result.get("mode", "dag"),
                "data": result.get("data", {}),
                "devices_notified": [],
                "trace_id": result.get("trace_id", ""),
            }
        except Exception as exc:
            logger.warning("ConstellationRuntime 路径失败，降级到 pipeline: %s", exc)

    # ── 默认 EndToEndPipeline 路径 ────────────────────────────────────
    from core.e2e_pipeline import get_pipeline

    pipeline = get_pipeline()
    return await pipeline.execute(
        message=message,
        user_id=user_id,
        source_device_id=device_id,
        session_id=session_id,
        context=context,
    )


async def process_wake_event(
    device_id: str,
    wake_word: str,
    task_type: str = "general",
    extra: Optional[Dict] = None,
) -> Dict[str, Any]:
    """
    处理唤醒事件 — 创建会话并准备接收用户输入。

    Args:
        device_id: 唤醒来源设备
        wake_word: 唤醒词
        task_type: 任务类型 (voice/visual/general)
        extra: 附加数据

    Returns:
        {"session_id": str, "status": str}
    """
    try:
        from galaxy_gateway.session_roaming import session_roaming

        session = session_roaming.create_session(
            device_id=device_id,
            wake_word=wake_word,
            meta={"task_type": task_type, **(extra or {})},
        )
        logger.info(
            f"唤醒事件已处理: device={device_id} wake_word={wake_word} "
            f"session={session.session_id}"
        )
        return {
            "session_id": session.session_id,
            "status": "session_created",
            "device_id": device_id,
        }
    except Exception as e:
        logger.error(f"唤醒事件处理失败: {e}")
        return {"session_id": "", "status": "error", "error": str(e)}

