"""
galaxy_gateway/android/handlers/goal_execution.py

Handles goal_execution, parallel_subtask, and goal_execution_result messages.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from galaxy_gateway.android.message_builder import MessageBuilder

if TYPE_CHECKING:
    from galaxy_gateway.android_bridge import AndroidBridge

logger = logging.getLogger(__name__)

_AUTHORITY_V2 = "v2_authority"
_AUTHORITY_BOUNDARY_ANDROID_UNDER_V2 = "android_participation_under_v2_authority"
_LINEAGE_QUALITY_CANONICAL_CANDIDATE = "canonical_candidate"
_LINEAGE_QUALITY_CANONICAL_SUCCESS = "canonical_success"
_LINEAGE_QUALITY_REPLAY_ASSISTED = "replay_assisted"
_LINEAGE_QUALITY_RECOVERY_ASSISTED = "recovery_assisted"
_LINEAGE_QUALITY_COMPAT_SUCCESS = "compat_success"
_LINEAGE_QUALITY_FALLBACK_SUCCESS = "fallback_success"
_LINEAGE_QUALITY_DEGRADED_SUCCESS = "degraded_success"

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
# PR-8V2 / PR-2-SINGLE-INGRESS: Android participant truth for goal_execution_result
# must flow through the canonical unified ingress, NOT through direct sub-ingress
# calls.  Import ingest_android_runtime_state_update as the single entry point.
try:
    from core.unified_runtime_truth_ingress import (
        ingest_android_runtime_state_update as _ingest_goal_result_via_canonical_ingress,
    )
except ImportError:
    _ingest_goal_result_via_canonical_ingress = None  # type: ignore[assignment]

# PR-UNIFY: Canonical must-run truth chain for goal_execution_result processing.
# Top-level import so tests can patch() the chain function.
# Mirrors the PR-TTC pattern from task_lifecycle.py handle_task_result so that
# goal_execution_result routes through the same four-step canonical chain:
#   (1) truth_ingress, (2) reconcile, (3) authority_update, (4) completion_linkage.
try:
    from core.task_result_canonical_truth_chain import run_task_result_truth_chain as _run_task_result_truth_chain
except ImportError:
    _run_task_result_truth_chain = None  # type: ignore[assignment]

# PR-EG: Unified execution governance — top-level import so tests can patch() it.
# Provides the unified gate evaluation for goal_execution / parallel_subtask /
# takeover_request via a single authority policy model.
try:
    from core.unified_execution_governance import (
        ExecutionType as _ExecutionType,
        evaluate_execution_governance as _evaluate_execution_governance,
        notify_execution_completed as _notify_execution_completed,
    )
    _GOVERNANCE_AVAILABLE = True
except ImportError:
    _ExecutionType = None  # type: ignore[assignment]
    _evaluate_execution_governance = None  # type: ignore[assignment]
    _notify_execution_completed = None  # type: ignore[assignment]
    _GOVERNANCE_AVAILABLE = False

try:
    from core.android_mode_gate_policy import evaluate_android_mode_readiness as _evaluate_android_mode_readiness
except ImportError:
    _evaluate_android_mode_readiness = None  # type: ignore[assignment]

try:
    from galaxy_gateway.cross_device_switch import is_cross_device_enabled as _is_cross_device_enabled
except ImportError:
    _is_cross_device_enabled = None  # type: ignore[assignment]

try:
    from core.android_originated_main_chain_ingress import (
        accept_android_originated_nl_into_main_chain as _accept_android_originated_nl_into_main_chain,
        build_android_originated_governance_context as _build_android_originated_governance_context,
        is_android_originated_main_chain_accepted as _is_android_originated_main_chain_accepted,
    )
except ImportError:
    _accept_android_originated_nl_into_main_chain = None  # type: ignore[assignment]
    _build_android_originated_governance_context = None  # type: ignore[assignment]
    _is_android_originated_main_chain_accepted = None  # type: ignore[assignment]


def _build_android_nl_lineage(
    *,
    task_id: str,
    origin_device_id: str,
    session_id: str,
    trace_id: str,
    runtime_session_id: str = "",
    lineage_quality: str = _LINEAGE_QUALITY_CANONICAL_CANDIDATE,
    ingress_lineage: str = "canonical_ingress",
    protocol_lineage: str = "aip_v3_goal_execution",
    routing_lineage: str = "desktop_presence_runtime",
    dispatch_lineage: str = "governance_gated_dispatch",
    reconciliation_lineage: str = "pending_android_result_reconciliation",
    closure_lineage: str = "pending_android_result_closure",
    audit_lineage: str = "pending_android_result_audit",
    gate_blocking_reasons: Optional[List[str]] = None,
    ingress_transport_accepted: bool = True,
    policy_admitted: bool = True,
    local_execution_started: bool = False,
    local_execution_completed: bool = False,
    advisory_evidence_sent: bool = False,
    uplink_acknowledged: bool = False,
    reconciliation_acknowledged: bool = False,
    canonical_truth_completed: bool = False,
    mature_closure_achieved: bool = False,
) -> Dict[str, Any]:
    """Build canonical lineage metadata for Android NL cross-device flows."""
    return {
        "task_id": task_id,
        "lineage_quality": lineage_quality,
        "origin": "android",
        "origin_device_id": origin_device_id,
        "authority": _AUTHORITY_V2,
        "authority_boundary": _AUTHORITY_BOUNDARY_ANDROID_UNDER_V2,
        "source": "android_goal_execution",
        "entry_mode": "cross_device",
        "session_id": session_id,
        "trace_id": trace_id,
        "runtime_session_id": runtime_session_id,
        "ingress_lineage": ingress_lineage,
        "protocol_lineage": protocol_lineage,
        "routing_lineage": routing_lineage,
        "dispatch_lineage": dispatch_lineage,
        "reconciliation_lineage": reconciliation_lineage,
        "closure_lineage": closure_lineage,
        "audit_lineage": audit_lineage,
        "gate_blocking_reasons": list(gate_blocking_reasons or []),
        "ingress_transport_accepted": bool(ingress_transport_accepted),
        "policy_admitted": bool(policy_admitted),
        "local_execution_started": bool(local_execution_started),
        "local_execution_completed": bool(local_execution_completed),
        "advisory_evidence_sent": bool(advisory_evidence_sent),
        "uplink_acknowledged": bool(uplink_acknowledged),
        "reconciliation_acknowledged": bool(reconciliation_acknowledged),
        "canonical_truth_completed": bool(canonical_truth_completed),
        "mature_closure_achieved": bool(mature_closure_achieved),
        "canonical_authority": "v2",
        "lineage_recorded_at_ms": int(time.time() * 1000),
    }


def _is_non_canonical_lineage_quality(lineage_quality: str) -> bool:
    """Return whether lineage quality is explicitly non-canonical.

    These values represent replay/recovery/compat/fallback/degraded/blocked
    paths that cannot be promoted to V2 canonical mature closure even when
    transport and reconciliation steps completed.
    """
    q = str(lineage_quality or "").strip().lower()
    return q in {
        _LINEAGE_QUALITY_REPLAY_ASSISTED,
        _LINEAGE_QUALITY_RECOVERY_ASSISTED,
        _LINEAGE_QUALITY_COMPAT_SUCCESS,
        _LINEAGE_QUALITY_FALLBACK_SUCCESS,
        _LINEAGE_QUALITY_DEGRADED_SUCCESS,
        "blocked",
    }


def _derive_canonical_closure_flags(
    *,
    is_fully_closed: bool,
    truth_chain_complete: bool,
    acceptance_verdict: str,
    lineage_quality: str,
) -> tuple[bool, bool]:
    """Derive canonical and mature closure flags for Android-originated lineage.

    ``canonical_truth_completed`` requires authoritative V2 closure evidence
    (full close + truth chain complete + acceptance verdict "accept").
    ``mature_closure_achieved`` is stricter: canonical truth must be complete
    and the lineage quality itself must remain canonical (not replay/fallback/
    degraded/provisional class).
    """
    verdict = str(acceptance_verdict or "").strip().lower()
    canonical_truth_completed = (
        bool(is_fully_closed)
        and bool(truth_chain_complete)
        and verdict in {"accept", "accepted"}
    )
    mature_closure_achieved = (
        canonical_truth_completed
        and not _is_non_canonical_lineage_quality(lineage_quality)
    )
    return canonical_truth_completed, mature_closure_achieved


def _evaluate_android_nl_initiation_gate(
    *,
    device_id: str,
    require_parallel_execution: bool = False,
) -> Tuple[bool, List[str], str]:
    """Fail-closed gate for Android NL cross-device initiation.

    Returns:
        (is_eligible, blocking_gates, reason)
    """
    cross_device_enabled = bool(_is_cross_device_enabled and _is_cross_device_enabled())
    if not cross_device_enabled:
        return False, ["v2_cross_device_switch"], "cross_device_disabled"

    if _evaluate_android_mode_readiness is None:
        return False, ["mode_gate_unavailable"], "mode_gate_unavailable"

    verdict = _evaluate_android_mode_readiness(
        device_id=device_id,
        require_goal_execution=not require_parallel_execution,
        require_parallel_execution=require_parallel_execution,
    )
    if verdict.is_dispatch_eligible:
        return True, [], "dispatch_eligible"
    blocking = list(verdict.blocking_gates)
    return False, blocking, "mode_gate_blocked"


def _determine_result_lineage_quality(payload: Dict[str, Any], status: str) -> str:
    """Classify result lineage quality with deterministic precedence.

    Priority order:
    1) replay-assisted
    2) recovery-assisted
    3) compat-success
    4) fallback-success
    5) degraded-success
    6) canonical-success (default)
    """
    if payload.get("replay") or payload.get("replay_sequence"):
        return _LINEAGE_QUALITY_REPLAY_ASSISTED
    if payload.get("recovered") or payload.get("recovery"):
        return _LINEAGE_QUALITY_RECOVERY_ASSISTED
    if str(payload.get("route_mode") or "").strip().lower().startswith("compat"):
        return _LINEAGE_QUALITY_COMPAT_SUCCESS
    if bool(payload.get("fallback")):
        return _LINEAGE_QUALITY_FALLBACK_SUCCESS
    if status == "degraded":
        return _LINEAGE_QUALITY_DEGRADED_SUCCESS
    return _LINEAGE_QUALITY_CANONICAL_SUCCESS


def _evaluate_main_chain_ingress(
    *,
    task_id: str,
    device_id: str,
    session_id: str,
    ingress_carrier_context: Optional[Dict[str, Any]],
    is_stale: bool = False,
    is_replay: bool = False,
    is_recovery_assisted: bool = False,
    is_takeover_scenario: bool = False,
    is_conflict_present: bool = False,
    is_multi_device_concurrent: bool = False,
    is_duplicate: bool = False,
) -> Tuple[bool, Dict[str, Any], Dict[str, Any], str]:
    """Evaluate Android-originated ingress against canonical main-chain acceptance."""
    if (
        _accept_android_originated_nl_into_main_chain is None
        or _build_android_originated_governance_context is None
        or _is_android_originated_main_chain_accepted is None
    ):
        return False, {}, {}, "main_chain_ingress_unavailable"

    ingress_result = _accept_android_originated_nl_into_main_chain(
        device_id=device_id,
        session_id=session_id,
        invocation_id=task_id,
        ingress_carrier_context=ingress_carrier_context,
        is_stale=is_stale,
        is_replay=is_replay,
        is_recovery_assisted=is_recovery_assisted,
        is_takeover_scenario=is_takeover_scenario,
        is_conflict_present=is_conflict_present,
        is_multi_device_concurrent=is_multi_device_concurrent,
        is_duplicate=is_duplicate,
    )
    governance_context = _build_android_originated_governance_context(
        device_id=device_id,
        execution_id=task_id,
        ingress_result=ingress_result,
    )
    accepted = _is_android_originated_main_chain_accepted(ingress_result)
    if ingress_result.blocking_reason:
        reason = ingress_result.blocking_reason
    else:
        reason = (
            "main_chain_not_accepted:"
            f" lineage={ingress_result.lineage.value}"
            f" gap_types={list(ingress_result.gap_types)}"
        )
    return accepted, ingress_result.to_dict(), governance_context, reason


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

    Routes through :func:`~core.unified_runtime_truth_ingress.ingest_android_runtime_state_update`
    — the single canonical ingress — so that continuity-gate enforcement is
    always applied.  Injects ``truth_kind="result"`` so the participant-truth
    sub-ingress classifies the goal_execution_result as a canonical result signal.

    Failures are logged at DEBUG level and never propagated — this is an
    additive PR-8V2 path that complements the existing PR-13 reconcile call.
    """
    if _ingest_goal_result_via_canonical_ingress is None:
        return
    try:
        enriched = dict(message)
        enriched.setdefault("truth_kind", "result")
        outcome = _ingest_goal_result_via_canonical_ingress(enriched)
        if outcome.was_reconciled:
            logger.debug(
                "PR-8V2 goal_execution_result participant truth ingested via "
                "canonical ingress: routed_path=%r was_reconciled=True",
                outcome.routed_path,
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

    gate_ok, gate_blocking_gates, gate_reason = _evaluate_android_nl_initiation_gate(
        device_id=device_id,
        require_parallel_execution=False,
    )
    if not gate_ok:
        lineage = _build_android_nl_lineage(
            task_id=task_id,
            origin_device_id=device_id,
            session_id=session_id,
            trace_id=trace_id,
            lineage_quality="blocked",
            ingress_lineage="blocked_ingress",
            dispatch_lineage="blocked_by_cross_device_gate",
            reconciliation_lineage="not_started",
            closure_lineage="not_started",
            audit_lineage="blocked_pre_dispatch",
            gate_blocking_reasons=gate_blocking_gates,
            policy_admitted=False,
        )
        return MessageBuilder.error(
            device_id,
            "ANDROID_NL_INITIATION_BLOCKED",
            f"android nl initiation blocked: {gate_reason}",
            details={"blocking_gates": gate_blocking_gates, "lineage": lineage},
            correlation_id=task_id,
        )

    # ── Unified Execution Governance check ───────────────────────────────
    # Consult the unified governance layer before proceeding.  This enforces
    # acceptance conditions, conflict detection (e.g., active takeover blocks
    # this goal_execution), and concurrency limits across all execution types.
    if _GOVERNANCE_AVAILABLE and _evaluate_execution_governance is not None:
        _gov_verdict = _evaluate_execution_governance(
            _ExecutionType.goal_execution,
            device_id,
            execution_id=task_id,
        )
        if not _gov_verdict.accepted:
            logger.warning(
                "GOAL_EXECUTION blocked by unified governance: task_id=%s device_id=%s "
                "reason=%r conflict=%s active_type=%s",
                task_id, device_id, _gov_verdict.rejection_reason,
                _gov_verdict.conflict,
                _gov_verdict.active_conflicting_type.value if _gov_verdict.active_conflicting_type else None,
            )
            return MessageBuilder.error(
                device_id,
                "GOVERNANCE_REJECTED",
                _gov_verdict.rejection_reason,
                details={
                    "blocking_gates": list(_gov_verdict.blocking_gates),
                    "lineage": _build_android_nl_lineage(
                        task_id=task_id,
                        origin_device_id=device_id,
                        session_id=session_id,
                        trace_id=trace_id,
                        lineage_quality="blocked",
                        dispatch_lineage="blocked_by_governance",
                        reconciliation_lineage="not_started",
                        closure_lineage="not_started",
                        audit_lineage="governance_rejected",
                        gate_blocking_reasons=list(_gov_verdict.blocking_gates),
                        policy_admitted=False,
                    ),
                },
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
        # source="android_goal_execution" correctly identifies the carrier as Android.
        # V2's OpenClawd + AgentKernel + MultiLLMRouter remains the semantic authority;
        # Android is the NL source/carrier only (GoalNormalizer = structural normalization,
        # not LLM semantic reasoning).
        result = await runtime.handle_request(
            message=goal,
            source="android_goal_execution",
            device_id=device_id,
            session_id=session_id,
            runtime_session_id=trace_id,
            entry_mode="cross_device",
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
    ingress_ok, ingress_result, governance_context, ingress_reason = _evaluate_main_chain_ingress(
        task_id=task_id,
        device_id=device_id,
        session_id=session_id,
        ingress_carrier_context=result.get("ingress_carrier_context"),
        is_stale=bool(payload.get("stale")),
        is_replay=bool(payload.get("replay")),
        is_recovery_assisted=bool(payload.get("recovered") or payload.get("recovery")),
        is_takeover_scenario=bool(payload.get("takeover")),
        is_conflict_present=bool(payload.get("conflict") or payload.get("partial")),
        is_multi_device_concurrent=bool(payload.get("multi_device_race")),
        is_duplicate=bool(payload.get("duplicate")),
    )
    if not ingress_ok:
        return MessageBuilder.error(
            device_id,
            "ANDROID_MAIN_CHAIN_INGRESS_REJECTED",
            f"android nl initiation rejected by main-chain ingress: {ingress_reason}",
            details={
                "lineage": _build_android_nl_lineage(
                    task_id=task_id,
                    origin_device_id=device_id,
                    session_id=session_id,
                    trace_id=trace_id,
                    runtime_session_id=runtime_session_id,
                    lineage_quality="blocked",
                    dispatch_lineage="blocked_by_main_chain_ingress",
                    reconciliation_lineage="not_started",
                    closure_lineage="not_started",
                    audit_lineage="main_chain_ingress_rejected",
                    policy_admitted=False,
                ),
                "main_chain_ingress": ingress_result,
                "android_governance_context": governance_context,
            },
            correlation_id=task_id,
        )

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
        "lineage": _build_android_nl_lineage(
            task_id=task_id,
            origin_device_id=device_id,
            session_id=session_id,
            trace_id=trace_id,
            runtime_session_id=runtime_session_id,
        ),
        # Main-chain ingress acceptance evidence for governance/audit consumers.
        "android_governance_context": governance_context,
        "main_chain_ingress": ingress_result,
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

    gate_ok, gate_blocking_gates, gate_reason = _evaluate_android_nl_initiation_gate(
        device_id=device_id,
        require_parallel_execution=True,
    )
    if not gate_ok:
        lineage = _build_android_nl_lineage(
            task_id=task_id,
            origin_device_id=device_id,
            session_id=session_id,
            trace_id=trace_id,
            lineage_quality="blocked",
            ingress_lineage="blocked_ingress",
            dispatch_lineage="blocked_parallel_dispatch_gate",
            reconciliation_lineage="not_started",
            closure_lineage="not_started",
            audit_lineage="blocked_pre_dispatch",
            gate_blocking_reasons=gate_blocking_gates,
            policy_admitted=False,
        )
        return MessageBuilder.error(
            device_id,
            "ANDROID_NL_INITIATION_BLOCKED",
            f"parallel android nl initiation blocked: {gate_reason}",
            details={"blocking_gates": gate_blocking_gates, "lineage": lineage},
            correlation_id=task_id,
        )

    # ── Unified Execution Governance check ───────────────────────────────
    # Consult the unified governance layer before proceeding.  This enforces
    # acceptance conditions, conflict detection (e.g., active takeover blocks
    # this parallel_subtask), and concurrency limits across all execution types.
    if _GOVERNANCE_AVAILABLE and _evaluate_execution_governance is not None:
        _gov_verdict = _evaluate_execution_governance(
            _ExecutionType.parallel_subtask,
            device_id,
            execution_id=task_id,
        )
        if not _gov_verdict.accepted:
            logger.warning(
                "PARALLEL_SUBTASK blocked by unified governance: task_id=%s device_id=%s "
                "reason=%r conflict=%s active_type=%s",
                task_id, device_id, _gov_verdict.rejection_reason,
                _gov_verdict.conflict,
                _gov_verdict.active_conflicting_type.value if _gov_verdict.active_conflicting_type else None,
            )
            return MessageBuilder.error(
                device_id,
                "GOVERNANCE_REJECTED",
                _gov_verdict.rejection_reason,
                details={
                    "blocking_gates": list(_gov_verdict.blocking_gates),
                    "lineage": _build_android_nl_lineage(
                        task_id=task_id,
                        origin_device_id=device_id,
                        session_id=session_id,
                        trace_id=trace_id,
                        lineage_quality="blocked",
                        dispatch_lineage="blocked_by_governance",
                        reconciliation_lineage="not_started",
                        closure_lineage="not_started",
                        audit_lineage="governance_rejected",
                        gate_blocking_reasons=list(_gov_verdict.blocking_gates),
                        policy_admitted=False,
                    ),
                },
                correlation_id=task_id,
            )

    logger.info(
        "PARALLEL_SUBTASK received: task_id=%s device_id=%s group_id=%s goal=%r",
        task_id, device_id, group_id, goal[:80],
    )

    # ── Step 1: 通过 DesktopPresenceRuntime 规范化 goal ──────────────
    # source="android_goal_execution" correctly identifies the carrier as Android.
    # V2's OpenClawd + AgentKernel + MultiLLMRouter is the semantic authority.
    result: Dict[str, Any] = {"success": False, "response": ""}
    try:
        from core.desktop_presence_runtime import get_desktop_presence_runtime
        runtime = get_desktop_presence_runtime()
        result = await runtime.handle_request(
            message=goal,
            source="android_goal_execution",
            device_id=device_id,
            session_id=session_id,
            runtime_session_id=trace_id,
            entry_mode="cross_device",
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
    ingress_ok, ingress_result, governance_context, ingress_reason = _evaluate_main_chain_ingress(
        task_id=task_id,
        device_id=device_id,
        session_id=session_id,
        ingress_carrier_context=result.get("ingress_carrier_context"),
        is_stale=bool(payload.get("stale")),
        is_replay=bool(payload.get("replay")),
        is_recovery_assisted=bool(payload.get("recovered") or payload.get("recovery")),
        is_takeover_scenario=bool(payload.get("takeover")),
        is_conflict_present=bool(payload.get("conflict") or payload.get("partial")),
        is_multi_device_concurrent=bool(payload.get("multi_device_race")),
        is_duplicate=bool(payload.get("duplicate")),
    )
    if not ingress_ok:
        return MessageBuilder.error(
            device_id,
            "ANDROID_MAIN_CHAIN_INGRESS_REJECTED",
            f"parallel android nl initiation rejected by main-chain ingress: {ingress_reason}",
            details={
                "lineage": _build_android_nl_lineage(
                    task_id=task_id,
                    origin_device_id=device_id,
                    session_id=session_id,
                    trace_id=trace_id,
                    runtime_session_id=runtime_session_id,
                    lineage_quality="blocked",
                    dispatch_lineage="blocked_by_main_chain_ingress",
                    reconciliation_lineage="not_started",
                    closure_lineage="not_started",
                    audit_lineage="main_chain_ingress_rejected",
                    policy_admitted=False,
                ),
                "main_chain_ingress": ingress_result,
                "android_governance_context": governance_context,
            },
            correlation_id=task_id,
        )

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
                "lineage": _build_android_nl_lineage(
                    task_id=task_id,
                    origin_device_id=device_id,
                    session_id=session_id,
                    trace_id=trace_id,
                    runtime_session_id=runtime_session_id,
                    dispatch_lineage="parallel_fanout_dispatched",
                ),
                # Main-chain ingress acceptance evidence for governance/audit consumers.
                "android_governance_context": governance_context,
                "main_chain_ingress": ingress_result,
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
            "lineage": _build_android_nl_lineage(
                task_id=task_id,
                origin_device_id=device_id,
                session_id=session_id,
                trace_id=trace_id,
                runtime_session_id=runtime_session_id,
                dispatch_lineage="single_device_fallback_dispatch",
                lineage_quality=_LINEAGE_QUALITY_FALLBACK_SUCCESS,
            ),
            # Main-chain ingress acceptance evidence for governance/audit consumers.
            "android_governance_context": governance_context,
            "main_chain_ingress": ingress_result,
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

    # PR-46: Cross-repo schema/version gate enforcement (STRICT mode).
    # goal_execution_result is a strict-reject type: schema/contract mismatches
    # block the message before any canonical truth chain step.
    try:
        from contracts.cross_repo_schema_version_gate import (
            evaluate_android_uplink_schema_gate as _evaluate_schema_gate,
        )
        _ger_gate_decision = _evaluate_schema_gate(
            message_type="goal_execution_result",
            message=message,
        )
        if _ger_gate_decision is not None:
            if _ger_gate_decision.action == "reject":
                logger.warning(
                    "handle_goal_execution_result: schema/version gate REJECTED ingress "
                    "reason=%s observed_schema=%r task_id=%r device_id=%r "
                    "— blocking before canonical truth chain",
                    _ger_gate_decision.reason,
                    _ger_gate_decision.observed_schema_version,
                    task_id,
                    device_id,
                )
                return
            if _ger_gate_decision.action == "degrade":
                logger.warning(
                    "handle_goal_execution_result: schema/version gate DEGRADED ingress "
                    "reason=%s observed_schema=%r task_id=%r device_id=%r "
                    "— proceeding in degraded mode",
                    _ger_gate_decision.reason,
                    _ger_gate_decision.observed_schema_version,
                    task_id,
                    device_id,
                )
    except Exception as _ger_gate_err:
        logger.debug(
            "handle_goal_execution_result: schema gate check skipped (non-fatal): %s",
            _ger_gate_err,
        )

    # Raw Android status — may be "success", "failed", "error", "cancelled", "degraded".
    _raw_status = payload.get("status", "unknown")
    # Canonical V2 status — normalised from the Android taxonomy.
    status = _normalize_android_goal_status(_raw_status)
    result_text = payload.get("result") or payload.get("details", "")
    latency_ms = payload.get("latency_ms", 0)
    group_id = payload.get("group_id")
    subtask_index = payload.get("subtask_index")
    result_lineage = dict(payload.get("lineage") or {})
    result_lineage.setdefault("origin", "android")
    result_lineage.setdefault("origin_device_id", device_id)
    result_lineage.setdefault("authority", _AUTHORITY_V2)
    result_lineage.setdefault("source", "android_goal_execution_result")
    result_lineage.setdefault("entry_mode", "cross_device")
    result_lineage.setdefault("task_id", task_id)
    result_lineage.setdefault("session_id", payload.get("session_id") or message.get("session_id") or "")
    result_lineage.setdefault("trace_id", trace_id)
    result_lineage.setdefault("protocol_lineage", "aip_v3_goal_execution_result")
    result_lineage.setdefault("routing_lineage", "task_result_canonical_truth_chain")
    result_lineage.setdefault("dispatch_lineage", "android_execution_completed")
    result_lineage.setdefault("reconciliation_lineage", "pending")
    result_lineage.setdefault("closure_lineage", "pending")
    result_lineage.setdefault("audit_lineage", "pending")
    result_lineage.setdefault(
        "lineage_quality",
        _determine_result_lineage_quality(payload, status),
    )
    result_lineage.setdefault("ingress_transport_accepted", True)
    result_lineage.setdefault("policy_admitted", True)
    result_lineage.setdefault("local_execution_started", True)
    result_lineage.setdefault("local_execution_completed", True)
    result_lineage.setdefault("advisory_evidence_sent", True)
    result_lineage.setdefault("uplink_acknowledged", True)
    result_lineage.setdefault("reconciliation_acknowledged", False)
    result_lineage.setdefault("canonical_truth_completed", False)
    result_lineage.setdefault("mature_closure_achieved", False)
    result_lineage.setdefault("canonical_authority", "v2")

    # ── Durable idempotency guard ─────────────────────────────────────────
    # Android's OfflineTaskQueue drains goal_execution_result messages on
    # reconnect.  A V2 restart + Android reconnect can replay the same result
    # multiple times.  Pre-check the durable store before any side-effecting work.
    # NOTE: We no longer call _record_ger_idem here; UnifiedResultIngress records
    # the same idempotency key internally so that the outer pre-check catches
    # replays on subsequent calls after the first successful ingestion.
    _ger_idem_key = f"goal_execution_result:{task_id}"
    try:
        from core.durable_result_idempotency import (
            check_result_idempotency as _check_ger_idem,
        )
        if _check_ger_idem(_ger_idem_key):
            logger.debug(
                "GOAL_EXECUTION_RESULT: duplicate suppressed (durable store): "
                "task_id=%s device_id=%s",
                task_id, device_id,
            )
            return
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
                "lineage": result_lineage,
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

    # PR-CLOSURE: 通过统一结果入口（UnifiedResultIngress）处理跨设备执行结果，
    # 实现跨设备链路的验收闭环（closure acceptance）。
    #
    # 本路径取代原先直接调用 run_task_result_truth_chain 的方式，统一通过
    # UnifiedResultIngress 处理以获得：
    #   (1) 幂等性保护（与外层使用同一 key，内部记录，防止重复处理）
    #   (2) 真值链（truth chain: truth_ingress / reconcile / lifecycle / completion）
    #   (3) 证据质量分级（execution evidence classification）
    #   (4) 验收判定（acceptance gate: accept / accept_provisional / quarantine / reject）
    #   (5) bridge pending_responses 解析（解除等待该任务结果的 Future）
    #
    # 如果 UnifiedResultIngress 不可用，回退到直接调用 run_task_result_truth_chain，
    # 以保留现有行为。
    _ger_ingress_closed = False
    _ger_ingress_outcome = None  # type: ignore[assignment]
    try:
        from core.unified_result_ingress import (
            NormalizedResultEvent as _NREV2,
            ResultSourceChannel as _RSCv2,
            ingest_result_async as _ingest_ger_async,
        )
        _ger_event = _NREV2(
            task_id=task_id,
            device_id=device_id,
            raw_message_type="goal_execution_result",
            normalized_result_kind="goal_execution_result",
            normalized_status=status,
            source_channel=_RSCv2.CANONICAL_WS,
            payload=payload,
            trace_id=trace_id,
            raw_message=message,
            runtime_session_id=payload.get("session_id") or message.get("session_id") or "",
            # 使用与外层幂等性保护相同的 key；UnifiedResultIngress 在此处记录该
            # key，外层的 pre-check 在下一次重放时会提前拦截重复消息。
            idempotency_key=_ger_idem_key,
        )
        _ger_ingress_outcome = await _ingest_ger_async(_ger_event, bridge=bridge)
        if _ger_ingress_outcome.was_deduplicated:
            # 已由 UnifiedResultIngress 幂等性保护拦截
            result_lineage["closure_lineage"] = "unified_ingress_deduplicated"
            result_lineage["reconciliation_acknowledged"] = True
            _canonical_completed, _mature_closure = _derive_canonical_closure_flags(
                is_fully_closed=getattr(_ger_ingress_outcome, "is_fully_closed", False),
                truth_chain_complete=getattr(_ger_ingress_outcome, "truth_chain_complete", False),
                acceptance_verdict=getattr(_ger_ingress_outcome, "evidence_acceptance_verdict", ""),
                lineage_quality=str(result_lineage.get("lineage_quality") or ""),
            )
            result_lineage["canonical_truth_completed"] = _canonical_completed
            result_lineage["mature_closure_achieved"] = _mature_closure
            logger.debug(
                "handle_goal_execution_result: unified ingress deduplicated task_id=%r",
                task_id,
            )
        elif _ger_ingress_outcome.is_fully_closed:
            _ger_ingress_closed = True
            result_lineage["reconciliation_lineage"] = "unified_ingress_closed"
            _acceptance_verdict = getattr(
                _ger_ingress_outcome, "evidence_acceptance_verdict", ""
            )
            if str(_acceptance_verdict).strip().lower() in {"accept_provisional", "accepted_provisional"}:
                result_lineage["closure_lineage"] = "unified_ingress_provisional_non_canonical"
                if result_lineage.get("lineage_quality") == _LINEAGE_QUALITY_CANONICAL_SUCCESS:
                    result_lineage["lineage_quality"] = _LINEAGE_QUALITY_DEGRADED_SUCCESS
            else:
                result_lineage["closure_lineage"] = "unified_ingress_accepted"
            result_lineage["audit_lineage"] = "unified_ingress_complete"
            result_lineage["acceptance_verdict"] = _acceptance_verdict or "accepted"
            if result_lineage.get("lineage_quality") in (
                _LINEAGE_QUALITY_CANONICAL_CANDIDATE,
                _LINEAGE_QUALITY_CANONICAL_SUCCESS,
            ):
                result_lineage["lineage_quality"] = _LINEAGE_QUALITY_CANONICAL_SUCCESS
            result_lineage["reconciliation_acknowledged"] = True
            _canonical_completed, _mature_closure = _derive_canonical_closure_flags(
                is_fully_closed=getattr(_ger_ingress_outcome, "is_fully_closed", False),
                truth_chain_complete=getattr(_ger_ingress_outcome, "truth_chain_complete", False),
                acceptance_verdict=_acceptance_verdict,
                lineage_quality=str(result_lineage.get("lineage_quality") or ""),
            )
            result_lineage["canonical_truth_completed"] = _canonical_completed
            result_lineage["mature_closure_achieved"] = _mature_closure
            logger.debug(
                "handle_goal_execution_result: unified ingress fully closed task_id=%r "
                "acceptance=%s truth_chain=%s",
                task_id,
                _ger_ingress_outcome.evidence_acceptance_verdict,
                _ger_ingress_outcome.truth_chain_complete,
            )
        else:
            # 部分闭环：UnifiedResultIngress 运行了但未完全关闭
            result_lineage["reconciliation_lineage"] = "unified_ingress_partial"
            result_lineage["closure_lineage"] = (
                f"unified_ingress_incomplete:{_ger_ingress_outcome.incomplete_reason}"
            )
            result_lineage["audit_lineage"] = "unified_ingress_partial"
            if result_lineage.get("lineage_quality") == _LINEAGE_QUALITY_CANONICAL_SUCCESS:
                result_lineage["lineage_quality"] = _LINEAGE_QUALITY_DEGRADED_SUCCESS
            result_lineage["reconciliation_acknowledged"] = bool(
                getattr(_ger_ingress_outcome, "truth_chain_complete", False)
            )
            result_lineage["canonical_truth_completed"] = False
            result_lineage["mature_closure_achieved"] = False
            logger.warning(
                "handle_goal_execution_result: unified ingress partial for task_id=%r "
                "reason=%s truth_chain=%s",
                task_id,
                _ger_ingress_outcome.incomplete_reason,
                _ger_ingress_outcome.truth_chain_complete,
            )
    except Exception as _ingest_ger_err:
        # 回退路径：UnifiedResultIngress 不可用，保持旧行为。
        logger.warning(
            "handle_goal_execution_result: unified ingress unavailable "
            "(falling back to truth chain) task_id=%r err=%s",
            task_id,
            _ingest_ger_err,
        )
        if _run_task_result_truth_chain is not None:
            _ger_ttc_outcome = _run_task_result_truth_chain(
                message,
                task_id=task_id,
                result_status=status,
            )
            if not _ger_ttc_outcome.is_truth_chain_complete:
                result_lineage["reconciliation_lineage"] = "truth_chain_fallback_incomplete"
                result_lineage["closure_lineage"] = "truth_chain_fallback_incomplete"
                result_lineage["audit_lineage"] = "truth_chain_fallback_incomplete"
                if result_lineage.get("lineage_quality") == _LINEAGE_QUALITY_CANONICAL_SUCCESS:
                    result_lineage["lineage_quality"] = _LINEAGE_QUALITY_DEGRADED_SUCCESS
                result_lineage["reconciliation_acknowledged"] = False
                result_lineage["canonical_truth_completed"] = False
                result_lineage["mature_closure_achieved"] = False
                logger.warning(
                    "handle_goal_execution_result: truth chain fallback incomplete "
                    "for task_id=%r: %s",
                    task_id,
                    _ger_ttc_outcome.incomplete_reason,
                )
            else:
                result_lineage["reconciliation_lineage"] = "truth_chain_fallback_reconciled"
                result_lineage["closure_lineage"] = "truth_chain_fallback_complete"
                result_lineage["audit_lineage"] = "truth_chain_fallback_complete"
                if result_lineage.get("lineage_quality") in (
                    _LINEAGE_QUALITY_CANONICAL_CANDIDATE,
                    _LINEAGE_QUALITY_CANONICAL_SUCCESS,
                ):
                    result_lineage["lineage_quality"] = _LINEAGE_QUALITY_FALLBACK_SUCCESS
                result_lineage["reconciliation_acknowledged"] = True
                result_lineage["canonical_truth_completed"] = False
                result_lineage["mature_closure_achieved"] = False
        else:
            # 第二层回退：遗留助手（truth chain 模块亦不可用）
            logger.warning(
                "handle_goal_execution_result: task_result_canonical_truth_chain "
                "unavailable, using legacy fallback for task_id=%r",
                task_id,
            )
            if _reconcile_goal_result is not None:
                try:
                    _rec_outcome = _reconcile_goal_result(message)
                    if _rec_outcome.was_updated:
                        logger.debug(
                            "goal_execution_result legacy reconcile: "
                            "signal=%s contract_id=%r → phase=%s",
                            _rec_outcome.envelope.signal_kind.value if _rec_outcome.envelope else "?",
                            _rec_outcome.envelope.contract_id if _rec_outcome.envelope else "",
                            _rec_outcome.record.phase.value if _rec_outcome.record else "?",
                        )
                except Exception as rec_err:
                    logger.debug(
                        "goal_execution_result legacy reconcile failed (non-fatal): %s", rec_err
                    )
            _try_ingest_goal_result_truth(message)
            result_lineage["reconciliation_lineage"] = "legacy_fallback_reconcile"
            result_lineage["closure_lineage"] = "legacy_fallback_completion"
            result_lineage["audit_lineage"] = "legacy_fallback_truth_chain"
            if result_lineage.get("lineage_quality") == _LINEAGE_QUALITY_CANONICAL_SUCCESS:
                result_lineage["lineage_quality"] = _LINEAGE_QUALITY_FALLBACK_SUCCESS
            result_lineage["reconciliation_acknowledged"] = False
            result_lineage["canonical_truth_completed"] = False
            result_lineage["mature_closure_achieved"] = False
            # 遗留完成通知
            try:
                from core.canonical_completion_ingress import get_canonical_completion_ingress as _get_cci_fb
                _get_cci_fb().notify(_make_completion_envelope(
                    task_id=task_id,
                    handoff_id=payload.get("handoff_id") or "",
                ))
                logger.debug(
                    "GOAL_EXECUTION_RESULT: legacy fallback CanonicalCompletionIngress "
                    "notified task_id=%s",
                    task_id,
                )
            except Exception as _cci_fb_err:
                logger.debug(
                    "GOAL_EXECUTION_RESULT: legacy fallback completion ingress notify "
                    "failed (non-fatal): %s",
                    _cci_fb_err,
                )

    # 写入双链路闭环注册表（execution_chain_closure）。
    # 将跨设备链路验收状态记录到全局闭环注册表，供操作员面板和审计消费。
    try:
        from core.execution_chain_closure import record_cross_device_chain_closure as _record_cdcc
        _ingress_outcome_for_closure: Optional[Dict[str, Any]] = None
        if _ger_ingress_outcome is not None:
            _ingress_outcome_for_closure = {
                "is_fully_closed": getattr(_ger_ingress_outcome, "is_fully_closed", False),
                "was_deduplicated": getattr(_ger_ingress_outcome, "was_deduplicated", False),
                "truth_chain_complete": getattr(_ger_ingress_outcome, "truth_chain_complete", False),
                "evidence_acceptance_verdict": getattr(_ger_ingress_outcome, "evidence_acceptance_verdict", ""),
                "incomplete_reason": getattr(_ger_ingress_outcome, "incomplete_reason", ""),
            }
        _record_cdcc(
            task_id=task_id,
            ingress_outcome=_ingress_outcome_for_closure,
            normalized_status=status,
            device_id=device_id,
        )
    except Exception as _cdcc_err:
        logger.debug(
            "GOAL_EXECUTION_RESULT: execution_chain_closure 写入失败（非致命）"
            "task_id=%s err=%s",
            task_id,
            _cdcc_err,
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
    # NOTE: bridge._pending_responses 由 ingest_result_async(bridge=bridge) 在
    # UnifiedResultIngress 内部解析，无需在此重复处理。如果 UnifiedResultIngress
    # 不可用（回退路径），作为保险措施仍在此处解析。
    if not _ger_ingress_closed:
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
                        "GOAL_EXECUTION_RESULT: _pending_responses fallback resolution "
                        "task_id=%s",
                        task_id,
                    )
        except Exception as _pr_err:
            logger.debug(
                "GOAL_EXECUTION_RESULT: _pending_responses fallback resolution failed "
                "(non-fatal): %s",
                _pr_err,
            )

    return None
