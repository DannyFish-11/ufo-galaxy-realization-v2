"""
galaxy_gateway/android/handlers/goal_execution.py

Handles goal_execution, parallel_subtask, and goal_execution_result messages.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from galaxy_gateway.android.message_builder import MessageBuilder

if TYPE_CHECKING:
    from galaxy_gateway.android_bridge import AndroidBridge

logger = logging.getLogger(__name__)

# OpenClawd memory backflow — top-level import so tests can patch() it.
try:
    from core.openclawd_memory_backflow import store_task_result
except ImportError:
    store_task_result = None  # type: ignore[assignment]

# PR-13: canonical host-side reconciliation binding — top-level import so
# tests can patch() it and so the import failure is handled gracefully.
try:
    from core.android_execution_signal_reconciler import reconcile_inbound_message as _reconcile_goal_result
except ImportError:
    _reconcile_goal_result = None  # type: ignore[assignment]

# PR-D: canonical server-side group result aggregator — top-level import so
# tests can patch() it.
try:
    from core.goal_result_aggregator import get_goal_result_aggregator as _get_goal_result_aggregator
except ImportError:
    _get_goal_result_aggregator = None  # type: ignore[assignment]

# PR-8V2: Android participant/session/runtime truth ingress — top-level import
# so tests can patch() it and import failures are handled gracefully.
# goal_execution_result carries a user-visible business result and must be
# reconciled into V2 canonical participant truth (truth_kind="result") just
# like task_result in task_lifecycle.py.
try:
    from core.android_participant_truth_ingress import ingest_android_participant_truth_message as _ingest_goal_result_truth
except ImportError:
    _ingest_goal_result_truth = None  # type: ignore[assignment]

# PR-UNIFY: Canonical must-run truth chain for goal_execution_result processing.
# Top-level import so tests can patch() the chain function.
# Mirrors the PR-TTC pattern from task_lifecycle.py handle_task_result so that
# goal_execution_result routes through the same four-step canonical chain:
#   (1) truth_ingress, (2) reconcile, (3) authority_update, (4) completion_linkage.
try:
    from core.task_result_canonical_truth_chain import run_task_result_truth_chain as _run_task_result_truth_chain
except ImportError:
    _run_task_result_truth_chain = None  # type: ignore[assignment]


def _make_completion_envelope(task_id: str, handoff_id: str = "") -> Any:
    """Build a minimal duck-typed envelope for CanonicalCompletionIngress.notify().

    Used only in the fallback path when the canonical truth chain module is
    unavailable.  The three fields match what the truth chain's
    _run_completion_linkage helper creates internally.
    """

    class _Envelope:
        is_terminal: bool = True
        handoff_id: str = ""
        task_id: str = ""

    env = _Envelope()
    env.is_terminal = True
    env.handoff_id = handoff_id
    env.task_id = task_id
    return env


def _try_ingest_goal_result_truth(message: Dict[str, Any]) -> None:
    """Best-effort ingest *message* as Android participant truth (result kind).

    Calls :func:`~core.android_participant_truth_ingress.ingest_android_participant_truth_message`
    when the ingress module is available, injecting ``truth_kind="result"`` so
    the envelope extractor classifies the goal_execution_result as a canonical
    result signal.

    Failures are logged at DEBUG level and never propagated — this is an
    additive PR-8V2 path that complements the existing PR-13 reconcile call.
    """
    if _ingest_goal_result_truth is None:
        return
    try:
        enriched = dict(message)
        enriched.setdefault("truth_kind", "result")
        outcome = _ingest_goal_result_truth(enriched)
        if outcome.was_reconciled:
            logger.debug(
                "PR-8V2 goal_execution_result participant truth ingested: "
                "contract_id=%r session_id=%r was_reconciled=True "
                "canonical_update=%r phase=%r",
                outcome.envelope.contract_id if outcome.envelope else "",
                outcome.envelope.session_id if outcome.envelope else "",
                outcome.canonical_update,
                outcome.tracking_record_phase,
            )
        elif outcome.reject_reason:
            logger.debug(
                "PR-8V2 goal_execution_result participant truth skipped: "
                "reason=%r",
                outcome.reject_reason,
            )
    except Exception as exc:
        logger.debug(
            "PR-8V2 goal_execution_result participant truth ingest failed (non-fatal): %s",
            exc,
        )


async def handle_goal_execution(
    bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """处理 GOAL_EXECUTION — Android 高层自治目标下发。

    与 handle_task_submit 类似，但专用于 goal_execution 类型：
    1. 解析 GoalExecutionPayload（goal / task_id / group_id / subtask_index 等）
    2. 通过 DesktopPresenceRuntime 处理
    3. 返回 task_assign（Android 据此执行本地 goal）
    """
    payload = message.get("payload", {})
    device_id = message.get("device_id") or payload.get("device_id", "unknown")
    session_id = payload.get("session_id") or message.get("session_id") or "android_default"
    trace_id = payload.get("trace_id") or message.get("trace_id") or f"trace_{uuid.uuid4().hex[:12]}"
    task_id = payload.get("task_id") or message.get("task_id") or str(uuid.uuid4())
    goal = payload.get("goal", "").strip()

    if not goal:
        return MessageBuilder.error(
            device_id,
            "INVALID_GOAL_EXECUTION",
            "goal_execution missing or empty 'goal' field",
            correlation_id=task_id,
        )

    logger.info(
        "GOAL_EXECUTION received: task_id=%s device_id=%s group_id=%s goal=%r",
        task_id, device_id, payload.get("group_id"), goal[:80],
    )

    result: Dict[str, Any] = {"success": False, "response": ""}
    try:
        from core.desktop_presence_runtime import get_desktop_presence_runtime
        runtime = get_desktop_presence_runtime()
        result = await runtime.handle_request(
            message=goal,
            source="chat",
            device_id=device_id,
            session_id=session_id,
            runtime_session_id=trace_id,
            entry_mode="local",
        )
    except Exception as runtime_err:
        logger.error(
            "GOAL_EXECUTION: DesktopPresenceRuntime 处理失败 | task_id=%s error=%s",
            task_id, runtime_err, exc_info=True,
        )
        return MessageBuilder.error(
            device_id,
            "RUNTIME_ERROR",
            f"Subject core processing error: {runtime_err}",
            correlation_id=task_id,
        )

    success = result.get("success", False)
    response_text = result.get("response", "") or str(result.get("reply", ""))
    runtime_session_id = result.get("runtime_session_id", "")

    goal_task_assign_payload: Dict[str, Any] = {
        "task_id": task_id,
        "goal": response_text if response_text else goal,
        "constraints": payload.get("constraints", []),
        "max_steps": payload.get("max_steps", 10),
        "require_local_agent": True,  # goal_execution 强制本地执行
        "trace_id": trace_id,
        "session_id": session_id,
        "runtime_session_id": runtime_session_id,
        "success": success,
        "group_id": payload.get("group_id"),
        "subtask_index": payload.get("subtask_index"),
    }

    logger.info(
        "GOAL_EXECUTION → task_assign: task_id=%s goal=%r",
        task_id, response_text[:80] if response_text else goal[:80],
    )

    return MessageBuilder.task_assign(
        device_id=device_id,
        task_id=task_id,
        task_type="goal_execution",
        payload=goal_task_assign_payload,
    )


async def handle_parallel_subtask(
    bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """处理 PARALLEL_SUBTASK — 服务器端多设备 Fan-out 协调。

    流程：
    1. 解析 parallel_subtask payload
    2. 通过 DesktopPresenceRuntime 将 goal 转换为可执行文本
    3. 查询 UnifiedDeviceManager 获取所有已连接的 Android 设备
    4. 通过统一编排脊柱（unified orchestration spine）评估每台设备的派发就绪状态
    5. 向通过就绪检查的设备发送独立的 task_assign（包含 subtask_index）
    6. 返回 fan-out 结果（异步，不等待设备执行完成）
    """
    payload = message.get("payload", {})
    device_id = message.get("device_id") or payload.get("device_id", "unknown")
    session_id = payload.get("session_id") or message.get("session_id") or "android_default"
    trace_id = payload.get("trace_id") or message.get("trace_id") or f"trace_{uuid.uuid4().hex[:12]}"
    task_id = payload.get("task_id") or message.get("task_id") or str(uuid.uuid4())
    goal = payload.get("goal", "").strip()
    group_id = payload.get("group_id") or f"group_{uuid.uuid4().hex[:8]}"
    constraints = payload.get("constraints", [])
    max_steps = payload.get("max_steps", 10)

    if not goal:
        return MessageBuilder.error(
            device_id,
            "INVALID_PARALLEL_SUBTASK",
            "parallel_subtask missing or empty 'goal' field",
            correlation_id=task_id,
        )

    logger.info(
        "PARALLEL_SUBTASK received: task_id=%s device_id=%s group_id=%s goal=%r",
        task_id, device_id, group_id, goal[:80],
    )

    # ── Step 1: 通过 DesktopPresenceRuntime 规范化 goal ──────────────
    result: Dict[str, Any] = {"success": False, "response": ""}
    try:
        from core.desktop_presence_runtime import get_desktop_presence_runtime
        runtime = get_desktop_presence_runtime()
        result = await runtime.handle_request(
            message=goal,
            source="chat",
            device_id=device_id,
            session_id=session_id,
            runtime_session_id=trace_id,
            entry_mode="local",
        )
    except Exception as runtime_err:
        logger.error(
            "PARALLEL_SUBTASK: DesktopPresenceRuntime 处理失败 | task_id=%s error=%s",
            task_id, runtime_err, exc_info=True,
        )
        return MessageBuilder.error(
            device_id,
            "RUNTIME_ERROR",
            f"Subject core processing error: {runtime_err}",
            correlation_id=task_id,
        )

    response_text = result.get("response", "") or str(result.get("reply", ""))
    runtime_session_id = result.get("runtime_session_id", "")

    # ── Step 2: 查询所有已连接设备 ───────────────────────────────────
    all_device_ids: List[str] = []
    try:
        from core.unified.connection_manager import get_unified_connection_manager
        ucm = get_unified_connection_manager()
        all_device_ids = [
            did
            for did, d in ucm.get_all_devices().items()
            if d.get("device_type", "").upper() in ("ANDROID", "MOBILE", "PHONE")
            or did.startswith("android_")
            or d.get("online")
        ]
        logger.debug("PARALLEL_SUBTASK: 发现 %d 台 Android 设备", len(all_device_ids))
    except Exception as ucm_err:
        logger.warning(
            "PARALLEL_SUBTASK: UCM 查询失败，使用空设备列表 | error=%s",
            ucm_err,
        )
        all_device_ids = []

    # 排除当前发送者设备（避免重复执行）
    candidate_device_ids: List[str] = [d for d in all_device_ids if d != device_id]

    # ── Step 2b: 统一编排脊柱评估 (Unified Orchestration Spine) ─────
    # All fan-out targets must pass the unified dispatch readiness gate via
    # the orchestration spine before any task_assign is sent.  Non-ready
    # devices are excluded from the fan-out set.
    target_device_ids: List[str] = candidate_device_ids
    _spine_blocked_count = 0
    try:
        from core.unified_orchestration_spine import (
            OrchestrationRequest,
            ExecutionMode,
            evaluate_orchestration_request,
        )
        if candidate_device_ids:
            _orch_request = OrchestrationRequest(
                execution_mode=ExecutionMode.PARALLEL_FANOUT.value,
                target_device_ids=candidate_device_ids,
                task_id=task_id,
                session_id=session_id,
                group_id=group_id,
            )
            _orch_decision = evaluate_orchestration_request(_orch_request)
            target_device_ids = _orch_decision.ready_device_ids
            _spine_blocked_count = len(_orch_decision.blocked_slots)
            if _spine_blocked_count > 0:
                logger.info(
                    "PARALLEL_SUBTASK: orchestration spine blocked %d/%d devices "
                    "| task_id=%s ready=%s blocked=%s",
                    _spine_blocked_count,
                    len(candidate_device_ids),
                    task_id,
                    target_device_ids,
                    _orch_decision.blocked_device_ids,
                )
    except Exception as _spine_err:
        # Spine unavailable — degrade gracefully and proceed with candidate list
        logger.debug(
            "PARALLEL_SUBTASK: unified orchestration spine unavailable "
            "(non-fatal, using candidate device list): %s",
            _spine_err,
        )

    # ── PR-D: Register group with aggregator before dispatching ──────────
    # Record the expected subtask count now so the aggregator can recognise
    # when all results have arrived.  The actual count is set to the number of
    # devices we will fan-out to (minimum 1 for fallback single-device path).
    _expected_count = len(target_device_ids) if target_device_ids else 1
    if _get_goal_result_aggregator is not None:
        try:
            _get_goal_result_aggregator().register_group(
                group_id=group_id,
                expected_count=_expected_count,
                session_id=session_id,
                trace_id=trace_id,
            )
        except Exception as _agg_reg_err:
            logger.debug(
                "PARALLEL_SUBTASK: group aggregator registration failed (non-fatal): %s",
                _agg_reg_err,
            )

    # ── Step 3: Fan-out 到多台设备 ───────────────────────────────────
    fanout_summary: Dict[str, Any] = {"fanout": 0, "failed": 0, "device_ids": [], "errors": []}
    if target_device_ids:
        fanout_summary = await bridge._fan_out_task_assign(
            task_id=task_id,
            task_type="parallel_subtask",
            goal=response_text if response_text else goal,
            device_ids=target_device_ids,
            session_id=session_id,
            trace_id=trace_id,
            max_steps=max_steps,
            constraints=constraints,
            group_id=group_id,
            require_local_agent=True,
        )
    else:
        logger.info(
            "PARALLEL_SUBTASK: 无其他在线设备，fallback 到单设备执行 | task_id=%s",
            task_id,
        )

    # ── Step 4: 返回结果给调用方（fire-and-forget，不等待执行）───────
    if fanout_summary["fanout"] > 0:
        logger.info(
            "PARALLEL_SUBTASK → fan-out 成功: task_id=%s fanout=%s devices=%s",
            task_id, fanout_summary["fanout"], fanout_summary["device_ids"],
        )
        return MessageBuilder.goal_execution_result(
            device_id=device_id,
            payload={
                "status": "dispatched",
                "task_id": task_id,
                "correlation_id": task_id,
                "group_id": group_id,
                "fanout_count": fanout_summary["fanout"],
                "dispatched_to": fanout_summary["device_ids"],
                "dispatch_failed": fanout_summary["failed"],
                "spine_blocked": _spine_blocked_count,
                "runtime_session_id": runtime_session_id,
                "message": f"Parallel task dispatched to {fanout_summary['fanout']} device(s)",
            },
            correlation_id=task_id,
            trace_id=trace_id,
        )
    else:
        # 无 fan-out 结果（无设备或 UCM 异常），fallback 到本地单设备执行
        parallel_task_assign_payload: Dict[str, Any] = {
            "task_id": task_id,
            "goal": response_text if response_text else goal,
            "constraints": constraints,
            "max_steps": max_steps,
            "require_local_agent": True,
            "trace_id": trace_id,
            "session_id": session_id,
            "runtime_session_id": runtime_session_id,
            "success": True,
            "group_id": group_id,
            "subtask_index": 0,
            "device_ids": target_device_ids,
        }

        logger.info(
            "PARALLEL_SUBTASK → task_assign(fallback): task_id=%s goal=%r",
            task_id, response_text[:80] if response_text else goal[:80],
        )

        return MessageBuilder.task_assign(
            device_id=device_id,
            task_id=task_id,
            task_type="parallel_subtask",
            payload=parallel_task_assign_payload,
        )


def _normalize_android_goal_status(raw_status: str) -> str:
    """Map Android execution status taxonomy to canonical V2 status.

    Android's ``OfflineTaskQueue`` emits ``goal_execution_result`` messages
    with status values from the Android execution taxonomy:
    ``success`` / ``failed`` / ``error`` / ``cancelled`` / ``degraded``.
    V2's canonical truth chain and lifecycle expect the normalised vocabulary:
    ``completed`` / ``failed`` / ``cancelled`` / ``degraded``.

    This function closes the taxonomy mismatch so that downstream truth chain
    steps — reconcile, authority_update, completion_linkage — always see the
    canonical status string.
    """
    s = str(raw_status).lower().strip()
    if s in ("failed", "error"):
        return "failed"
    if s == "cancelled":
        return "cancelled"
    if s == "degraded":
        return "degraded"
    return "completed"


async def handle_goal_execution_result(
    bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]
) -> None:
    """处理 GOAL_EXECUTION_RESULT — Android/设备执行结果回传。

    Android 执行完 goal_execution 或 parallel_subtask 后发送此消息。
    处理策略：
    - 幂等性保护（durable store）— 防止 OfflineTaskQueue 重放重复消费
    - Android→canonical status 规范化 — 防止"success"被误判为非终态
    - 记录到 TaskMemory（供 LLM 上下文注入）
    - 触发 OpenClawd 反馈（如果有对话反馈路径）
    """
    payload = message.get("payload", {})
    device_id = message.get("device_id") or payload.get("device_id", "unknown")
    task_id = payload.get("task_id") or message.get("correlation_id") or "unknown"
    trace_id = payload.get("trace_id") or message.get("trace_id") or ""
    # Raw Android status — may be "success", "failed", "error", "cancelled", "degraded".
    _raw_status = payload.get("status", "unknown")
    # Canonical V2 status — normalised from the Android taxonomy.
    status = _normalize_android_goal_status(_raw_status)
    result_text = payload.get("result") or payload.get("details", "")
    latency_ms = payload.get("latency_ms", 0)
    group_id = payload.get("group_id")
    subtask_index = payload.get("subtask_index")

    # ── Durable idempotency guard ─────────────────────────────────────────
    # Android's OfflineTaskQueue drains goal_execution_result messages on
    # reconnect.  A V2 restart + Android reconnect can replay the same result
    # multiple times.  Check the durable store before any side-effecting work
    # so that memory backflow, reconcile, and completion linkage each run at
    # most once per task_id.
    _ger_idem_key = f"goal_execution_result:{task_id}"
    try:
        from core.durable_result_idempotency import (
            check_result_idempotency as _check_ger_idem,
            record_result_idempotency as _record_ger_idem,
        )
        if _check_ger_idem(_ger_idem_key):
            logger.debug(
                "GOAL_EXECUTION_RESULT: duplicate suppressed (durable store): "
                "task_id=%s device_id=%s",
                task_id, device_id,
            )
            return
        _record_ger_idem(_ger_idem_key)
    except Exception as _ger_idem_err:
        logger.debug(
            "GOAL_EXECUTION_RESULT: idempotency check skipped (non-fatal): %s",
            _ger_idem_err,
        )

    logger.info(
        "GOAL_EXECUTION_RESULT received: task_id=%s device_id=%s "
        "raw_status=%s canonical_status=%s "
        "group_id=%s subtask_index=%s latency=%sms",
        task_id, device_id, _raw_status, status, group_id, subtask_index, latency_ms,
    )

    # ── 持久化到 TaskMemory（容错保护）─────────────────────────────
    if store_task_result is not None:
        try:
            result_dict: Dict[str, Any] = {
                "status": status,
                "result": result_text,
                "trace_id": trace_id,
                "latency_ms": latency_ms,
                "task_type": "goal_execution_result",
                "steps": payload.get("steps", []),
                "group_id": group_id,
                "subtask_index": subtask_index,
            }
            await store_task_result(
                task_id=task_id,
                device_id=device_id,
                route_mode=payload.get("route_mode", "cross_device"),
                result=result_dict,
                session_id=payload.get("session_id"),
            )
            logger.debug(
                "GOAL_EXECUTION_RESULT: task_memory 写入成功 task_id=%s", task_id,
            )
        except Exception as mem_err:
            logger.warning(
                "GOAL_EXECUTION_RESULT: task_memory 写入失败（非致命）task_id=%s error=%s",
                task_id, mem_err,
            )
    else:
        logger.debug(
            "GOAL_EXECUTION_RESULT: store_task_result 不可用，跳过内存回流 task_id=%s",
            task_id,
        )

    # ── 触发 OpenClawd 反馈（如果有对应会话）────────────────────────
    try:
        from core.desktop_presence_runtime import get_desktop_presence_runtime
        runtime = get_desktop_presence_runtime()
        if hasattr(runtime, "on_goal_execution_result"):
            await runtime.on_goal_execution_result(
                task_id=task_id,
                device_id=device_id,
                status=status,
                result=result_text,
                trace_id=trace_id,
            )
    except Exception as feedback_err:
        logger.debug(
            "GOAL_EXECUTION_RESULT: OpenClawd 反馈失败（非致命）task_id=%s error=%s",
            task_id, feedback_err,
        )

    # PR-UNIFY: Run the canonical must-run truth chain for goal_execution_result.
    # This replaces the previous separate _reconcile_goal_result +
    # _try_ingest_goal_result_truth + direct CanonicalCompletionIngress.notify()
    # calls with a single entry point (mirroring task_lifecycle.py PR-TTC):
    #   (1) truth_ingress   — ingest Android participant truth into V2 state
    #   (2) reconcile       — reconcile against host-side execution tracker
    #   (3) authority_update — advance CanonicalTaskRuntime lifecycle
    #   (4) completion_linkage — notify CanonicalCompletionIngress
    # All four steps must run as a single chain so that goal_execution_result
    # and task_result share the same canonical completion authority path.
    if _run_task_result_truth_chain is not None:
        _ger_ttc_outcome = _run_task_result_truth_chain(
            message,
            task_id=task_id,
            result_status=status,
        )
        if not _ger_ttc_outcome.is_truth_chain_complete:
            logger.warning(
                "handle_goal_execution_result: truth chain incomplete for task_id=%r: %s",
                task_id,
                _ger_ttc_outcome.incomplete_reason,
            )
        else:
            logger.debug(
                "handle_goal_execution_result: truth chain complete for task_id=%r",
                task_id,
            )
    else:
        # Fallback: canonical truth chain module unavailable — run legacy
        # best-effort helpers so existing behaviour is preserved.
        logger.warning(
            "handle_goal_execution_result: canonical truth chain module unavailable "
            "(task_result_canonical_truth_chain); falling back to legacy "
            "best-effort helpers for task_id=%r",
            task_id,
        )
        if _reconcile_goal_result is not None:
            try:
                _rec_outcome = _reconcile_goal_result(message)
                if _rec_outcome.was_updated:
                    logger.debug(
                        "goal_execution_result fallback reconcile: "
                        "signal=%s contract_id=%r → phase=%s",
                        _rec_outcome.envelope.signal_kind.value if _rec_outcome.envelope else "?",
                        _rec_outcome.envelope.contract_id if _rec_outcome.envelope else "",
                        _rec_outcome.record.phase.value if _rec_outcome.record else "?",
                    )
            except Exception as rec_err:
                logger.debug(
                    "goal_execution_result fallback reconcile failed (non-fatal): %s", rec_err
                )
        _try_ingest_goal_result_truth(message)
        # Fallback completion linkage — only reached when truth chain is unavailable.
        try:
            from core.canonical_completion_ingress import get_canonical_completion_ingress as _get_cci_fb

            _get_cci_fb().notify(_make_completion_envelope(
                task_id=task_id,
                handoff_id=payload.get("handoff_id") or "",
            ))
            logger.debug(
                "GOAL_EXECUTION_RESULT: fallback CanonicalCompletionIngress notified task_id=%s",
                task_id,
            )
        except Exception as _cci_fb_err:
            logger.debug(
                "GOAL_EXECUTION_RESULT: fallback completion ingress notify failed (non-fatal): %s",
                _cci_fb_err,
            )

    # PR-D: parallel/group subtask aggregation
    # If this result carries a group_id, feed it into the canonical aggregator.
    # When all expected subtasks have reported, a group-complete summary is
    # emitted so the upper runtime / session can consume it.
    if group_id and _get_goal_result_aggregator is not None:
        try:
            agg = _get_goal_result_aggregator()
            group_state = agg.record_subtask_result(
                group_id=group_id,
                task_id=task_id,
                status=status,
                result_text=result_text,
                device_id=device_id,
                subtask_index=subtask_index,
            )
            if group_state is not None and group_state.all_done:
                logger.info(
                    "GOAL_EXECUTION_RESULT: group COMPLETE | group_id=%s "
                    "completed=%d/%d success=%d failure=%d",
                    group_id,
                    group_state.completed_count,
                    group_state.expected_count or group_state.completed_count,
                    group_state.success_count,
                    group_state.failure_count,
                )
                # Notify the runtime about group completion so the session
                # can be updated with the aggregated result.
                try:
                    from core.desktop_presence_runtime import get_desktop_presence_runtime
                    _runtime = get_desktop_presence_runtime()
                    if hasattr(_runtime, "on_goal_execution_result"):
                        await _runtime.on_goal_execution_result(
                            task_id=task_id,
                            device_id=device_id,
                            status=(
                                "completed"
                                if group_state.failure_count == 0
                                else ("failed" if group_state.success_count == 0 else "partial")
                            ),
                            result=str(group_state.summary),
                            trace_id=trace_id,
                            group_id=group_id,
                            group_summary=group_state.summary,
                        )
                except Exception as _grp_notify_err:
                    logger.debug(
                        "GOAL_EXECUTION_RESULT: group-complete runtime notify failed (non-fatal): %s",
                        _grp_notify_err,
                    )
        except Exception as agg_err:
            logger.debug(
                "GOAL_EXECUTION_RESULT: group aggregator update failed (non-fatal): %s", agg_err,
            )

    # GOAL_EXECUTION_RESULT 是最终回传（fire-and-forget），返回 None

    # Resolve bridge._pending_responses future keyed by task_id (if present).
    # This is an enrichment step separate from the canonical truth chain.
    try:
        _pending = getattr(bridge, "_pending_responses", None)
        if _pending is not None and task_id in _pending:
            _future = _pending.pop(task_id, None)
            if _future is not None and not _future.done():
                _future.set_result({
                    "status": status,
                    "task_id": task_id,
                    "result": result_text,
                    "source": "canonical_ws",
                })
                logger.debug(
                    "GOAL_EXECUTION_RESULT: _pending_responses future resolved task_id=%s",
                    task_id,
                )
    except Exception as _pr_err:
        logger.debug(
            "GOAL_EXECUTION_RESULT: _pending_responses resolution failed (non-fatal): %s",
            _pr_err,
        )

    return None
