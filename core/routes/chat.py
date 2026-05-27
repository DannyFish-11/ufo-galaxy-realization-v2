"""
core/routes/chat.py — /api/v1/chat Compatibility Adapter Surface
=================================================================

**Role: Compatibility Adapter Surface — NOT a Subject-Core Authority**
-----------------------------------------------------------------------
This module is a **compatibility adapter surface**.  Its sole responsibility
is to translate HTTP POST requests at ``/api/v1/chat`` into calls to the
authoritative runtime shell
(:class:`~core.desktop_presence_runtime.DesktopPresenceRuntime`) and package
the result as a :class:`~core.unified_response.UnifiedChatResponse`.

Architectural constraints (PR-1 + PR-2):
  - ``/api/v1/chat`` is demoted to a *compatibility adapter surface*.
    It is **not** the system's architectural centre.
  - :class:`~core.desktop_presence_runtime.DesktopPresenceRuntime` is the
    **runtime shell** that owns the tri-state subject lifecycle.
  - :class:`~core.openclawd.OpenClawd` is the **subject core**.
  - This route has **no subject-core authority**.  It must not be treated as
    the primary execution decision-maker.
  - AgentKernel is an internal cognition sub-kernel of OpenClawd; it is
    **never called directly from this adapter**.

Authority chain (PR-1 established, PR-2 makes explicit in responses):

    HTTP POST /api/v1/chat
        → core/routes/chat.py  ← you are here (compat adapter — no authority)
            → DesktopPresenceRuntime.handle_request(source="chat")
                → TriState: SILENT → LIMINAL → OpenClawd → MANIFEST → SILENT
                    → response with runtime_session_id, execution_authority

Backward compatibility guarantee (PR-2):
  All existing fields in the response (success, response, intent, confidence,
  mode, suggestions, data, error, session_id, model, timestamp) are preserved
  unchanged.  New metadata fields (entry_surface, entry_source,
  execution_authority, surface_role) are **additive only**; existing clients
  can ignore them safely.

Do NOT:
  - Implement subject-core logic in this file.
  - Add LLM model selection logic here; that belongs in OpenClawd/AgentKernel.
  - Treat this file as the canonical entrypoint for architectural design.
  - Instantiate AgentKernel directly — it is owned exclusively by OpenClawd.
  - Add execution paths that bypass DesktopPresenceRuntime → OpenClawd.

PR-1 authority enforcement:
  All execution flows through the single canonical chain:
    DesktopPresenceRuntime → OpenClawd → AgentKernel (cognition only)
  Legacy bypass helper functions (_handle_agent_action, _try_capability_execute,
  _try_agent_factory, _handle_scheduler_react, _handle_pure_chat) that
  previously existed in this file have been removed as they circumvented the
  OpenClawd authority chain.  Any new capability dispatch must go through
  OpenClawd via DesktopPresenceRuntime.

Galaxy - Chat Routes
==========================

Routes:
  POST /api/v1/chat  - 兼容性适配器表面 (delegates to DesktopPresenceRuntime)
"""

import logging
from typing import Any, Dict, List, Tuple

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from core.hidden_context_visible_action_surface import SurfaceLayer, classify_content_layer
from core.routes._models import ChatRequest
from core.unified_response import UnifiedChatResponse

logger = logging.getLogger("Galaxy.API")

FOREGROUND_BLOCKED_PREFIX = "当前操作受阻："
FOREGROUND_CONFIRMATION_EXPLANATION = "该操作需要你的确认后才能继续执行。"
FOREGROUND_STATUS_DONE = "操作已完成"
FOREGROUND_STATUS_NOT_DONE = "操作未完成"

# ── 动作意图判断关键词集合 ──────────────────────────────────────────────────────
_ACTION_KEYWORDS = frozenset([
    # 操作动词
    "打开", "关闭", "启动", "停止", "运行", "执行", "发送", "发出", "拍摄",
    "截图", "录制", "下载", "上传", "安装", "卸载", "设置", "调整", "切换",
    "搜索", "查找", "浏览", "播放", "暂停", "跳转", "跳过", "重启", "关机",
    "帮我", "帮助我", "请帮", "请你帮",
    # 英文动词
    "open", "close", "start", "stop", "run", "execute", "send", "take",
    "screenshot", "record", "download", "upload", "install", "uninstall",
    "set", "adjust", "switch", "search", "find", "browse", "play", "pause",
    "restart", "shutdown", "launch", "help me", "please",
])


def _is_action_intent(message: str) -> bool:
    """判断消息是否为动作意图（而非纯聊天）。

    基于关键词的轻量启发式判断，用于在无意图解析器时作为后备。

    Args:
        message: 用户输入的消息文本

    Returns:
        True 表示动作意图（如"帮我打开微信"），False 表示纯聊天（如"你好"）
    """
    lower = message.lower()
    return any(kw in lower for kw in _ACTION_KEYWORDS)


def _is_operator_request(req: ChatRequest) -> bool:
    """Resolve whether this request is operator/audit facing."""
    context = req.context or []
    # Iterate newest→oldest so the latest explicit audience hint wins.
    for item in reversed(context):
        if not isinstance(item, dict):
            continue
        audience = str(item.get("response_audience", "")).strip().lower()
        if audience in {"operator", "audit", "diagnostic"}:
            return True
        if audience in {"user", "foreground", "default"}:
            return False
        operator_mode = str(item.get("operator_mode", "")).strip().lower()
        if operator_mode in {"1", "true", "yes", "operator"}:
            return True
        if operator_mode in {"0", "false", "no", "user"}:
            return False
    return False


def _derive_foreground_response(
    *,
    default_response: str,
    blocker_summary: str,
    confirmation_needed: bool,
) -> str:
    """Enforce minimal necessary explanation for foreground users."""
    if blocker_summary:
        return f"{FOREGROUND_BLOCKED_PREFIX}{blocker_summary}"
    if confirmation_needed:
        return FOREGROUND_CONFIRMATION_EXPLANATION
    return default_response


def _apply_hidden_visible_boundary(
    *,
    result: Dict[str, Any],
    metadata: Dict[str, Any],
    is_operator_request: bool,
) -> Tuple[Dict[str, Any], Dict[str, Any], str, List[str]]:
    """Compose response payload via hidden-context/visible-action boundary."""
    visible_metadata: Dict[str, Any] = {}
    demoted_fields: List[str] = []
    for key, value in metadata.items():
        layer = classify_content_layer(key)
        if not is_operator_request and layer == SurfaceLayer.OPERATOR_AUDIT_TRUTH:
            demoted_fields.append(key)
            continue
        visible_metadata[key] = value

    lifecycle_surface = (
        result.get("action_lifecycle_surface")
        if isinstance(result.get("action_lifecycle_surface"), dict)
        else {}
    )
    lifecycle_visible_action = (
        result.get("visible_action")
        if isinstance(result.get("visible_action"), dict)
        else {}
    )

    # Prefer canonical key `blocker_summary`; keep legacy fallback
    # `execution_blocker_summary` while older runtime producers migrate.
    # TODO(runtime-surface): remove legacy fallback after producers converge.
    blocker_summary = str(
        lifecycle_surface.get("blocker_reason")
        or (lifecycle_surface.get("blocker") or {}).get("reason", "")
        or lifecycle_visible_action.get("blocker_reason")
        or visible_metadata.get("blocker_summary")
        or visible_metadata.get("execution_blocker_summary")
        or "",
    ).strip()
    confirmation_needed = bool(
        lifecycle_surface.get("confirmation_needed")
        or lifecycle_visible_action.get("confirmation_needed")
        or visible_metadata.get("confirmation_needed", False)
    )
    current_presence_mode = (
        str(visible_metadata.get("presence_mode", "")).strip() or "unknown"
    )
    lifecycle_phase = str(lifecycle_surface.get("phase") or "")
    if lifecycle_phase == "blocked" or blocker_summary:
        current_action_state = "blocked"
    elif lifecycle_phase == "confirmation_needed" or confirmation_needed:
        current_action_state = "awaiting_confirmation"
    elif lifecycle_phase == "accepted":
        current_action_state = "accepted"
    elif lifecycle_phase == "executing":
        current_action_state = "executing"
    elif lifecycle_phase in {"result_received", "closed"}:
        current_action_state = "completed"
    elif result.get("success", False):
        current_action_state = "completed"
    else:
        current_action_state = "failed"
    lifecycle_status_feedback = str(
        lifecycle_visible_action.get("status_feedback")
        or result.get("status_feedback")
        or ""
    ).strip()
    visible_action_surface = {
        "current_presence_mode": current_presence_mode,
        "current_action_state": current_action_state,
        "lifecycle_phase": lifecycle_phase or "unknown",
        "lifecycle_origin": str(lifecycle_surface.get("origin") or ""),
        "lifecycle_status_feedback": lifecycle_status_feedback,
        "action_trace_summary": visible_metadata.get("action_trace_summary", ""),
        "result_artifacts_summary": visible_metadata.get("result_artifacts_summary", ""),
        "blocker_summary": blocker_summary,
        "confirmation_needed": confirmation_needed,
        "lightweight_status_feedback": visible_metadata.get(
            "lightweight_status_feedback",
            lifecycle_status_feedback
            or (
                FOREGROUND_STATUS_DONE
                if current_action_state == "completed"
                else FOREGROUND_STATUS_NOT_DONE
            ),
        ),
    }
    if blocker_summary or confirmation_needed:
        visible_action_surface["minimal_necessary_explanation"] = _derive_foreground_response(
            default_response=result.get("response", ""),
            blocker_summary=blocker_summary,
            confirmation_needed=confirmation_needed,
        )

    foreground_response = (
        result.get("response", "")
        if is_operator_request
        else _derive_foreground_response(
            default_response=result.get("response", ""),
            blocker_summary=blocker_summary,
            confirmation_needed=confirmation_needed,
        )
    )
    return visible_metadata, visible_action_surface, foreground_response, demoted_fields


def create_router(service_manager=None, config=None) -> APIRouter:
    """Create chat routes router."""
    router = APIRouter()

    from core.unified import get_unified_llm_router

    llm_router = get_unified_llm_router()  # 统一 LLM 路由器入口（委派到 MultiLLMRouter）

    @router.post("/api/v1/chat")
    async def chat(req: ChatRequest):
        """
        /api/v1/chat — Compatibility Adapter Surface (PR-2)

        ROLE: This handler is a **compatibility adapter surface**.
        It does NOT own subject-core authority.  It delegates all
        execution to DesktopPresenceRuntime (runtime shell) → OpenClawd
        (subject core).

        Architecture chain (PR-1 + PR-2):
          1. EntrypointRouter stamps entry_path=canonical (PR-1 Block-1).
          2. resolve_entry_mode selects local / cross_device entry mode.
          3. DesktopPresenceRuntime.handle_request() drives the tri-state
             lifecycle (SILENT → LIMINAL → MANIFEST → SILENT).
          4. OpenClawd.process() performs subject-core execution; its
             internal AgentKernel handles cognition / planning.
          5. This adapter packages the result as UnifiedChatResponse,
             adding non-breaking surface metadata (PR-2).

        Backward-compat guarantee (PR-2):
          All pre-existing response fields are preserved unchanged.
          New fields (entry_surface, entry_source, execution_authority,
          surface_role) are additive and safe for old clients to ignore.

        跨设备统一会话：同一 user_id 的不同设备共享会话历史。
        """
        import time as _time
        _t0 = _time.monotonic()

        # ── PR-1 Block-1: stamp entry metadata via EntrypointRouter ──
        # EntrypointRouter records entry_path=canonical and emits an
        # observability event so canonical vs legacy usage can be tracked.
        _trace_id_for_entry = ""
        try:
            from core.unified.entrypoint_router import get_entrypoint_router as _get_er
            _er = _get_er()
            _er_stats = _er.stats()  # just touch to ensure singleton is warm
            _routing_meta = {
                "entry_path": "canonical",
                "via_legacy_adapter": False,
                "source": "chat",
            }
            logger.debug(
                "EntrypointRouter | entry_path=canonical source=chat stats=%s",
                _er_stats,
            )
        except Exception as _er_exc:
            logger.debug("EntrypointRouter unavailable (non-fatal): %s", _er_exc)
            _routing_meta = {}

        # ── PR-1 EntryMode: resolve execution mode for this request ──
        # Respects explicit override from the caller; falls back to auto-detection.
        _entry_mode = "local"
        try:
            from core.unified.entrypoint_router import resolve_entry_mode as _resolve_em
            _entry_mode = _resolve_em(
                explicit_entry_mode=req.entry_mode or None,
                target_device=req.target_device or None,
                trace_id=_trace_id_for_entry,
                source="core.routes.chat",
            )
        except Exception as _em_exc:
            logger.debug("resolve_entry_mode failed (non-fatal): %s", _em_exc)

        # ── 统一控制面: DesktopPresenceRuntime → OpenClawd 母体智能体 ──
        # DesktopPresenceRuntime 负责三态推进和 runtime_session_id 生成；
        # OpenClawd 内部嵌入 AgentKernel；SOUL 注入规则由 OpenClawd 统一管理。
        try:
            from core.desktop_presence_runtime import get_desktop_presence_runtime
            runtime = get_desktop_presence_runtime()
            result = await runtime.handle_request(
                message=req.message,
                source="chat",
                device_id=req.device_id,
                session_id=req.session_id,
                user_id=req.user_id,
                context=req.context,
                required_capabilities=req.required_capabilities,
                multimodal_context=req.multimodal_context,
                entry_mode=_entry_mode,
                runtime_attachment_session_id=req.context[-1].get(
                    "runtime_attachment_session_id",
                    "",
                )
                if req.context
                else "",
            )
            metadata = result.get("metadata", {})
            if not isinstance(metadata, dict):
                logger.warning(
                    "chat metadata payload is not a dict; type=%s runtime_session_id=%s",
                    type(metadata).__name__,
                    result.get("runtime_session_id", ""),
                )
                metadata = {}
            is_operator_request = _is_operator_request(req)
            (
                metadata,
                visible_action_surface,
                foreground_response,
                demoted_fields,
            ) = _apply_hidden_visible_boundary(
                result=result,
                metadata=metadata,
                is_operator_request=is_operator_request,
            )
            trace_id = (
                result.get("runtime_session_id")
                or result.get("trace_id")
                or metadata.get("trace_id")
                or metadata.get("request_id", "")
            )

            resp = UnifiedChatResponse(
                success=result.get("success", False),
                response=foreground_response,
                intent=result.get("intent", "chat"),
                confidence=metadata.get("confidence", 1.0),
                mode=metadata.get("mode", "openclawd"),
                model=metadata.get("model", ""),
                session_id=metadata.get(
                    "conversation_session_id",
                    metadata.get("session_id", req.session_id or ""),
                ),
                data=metadata,
                error=result.get("error", ""),
                # ── PR-2: surface metadata — additive, non-breaking ──────────
                # Exposes the true execution chain so callers understand that
                # /api/v1/chat is a compat adapter surface, not a subject core.
                runtime_session_id=result.get("runtime_session_id") or trace_id or None,
                entry_surface="chat_adapter",
                entry_source="http_post",
                execution_authority="DesktopPresenceRuntime/OpenClawd",
                surface_role="compat_adapter",
            )
            resp_dict = resp.to_json_response()
            resp_dict["reply"] = foreground_response
            resp_dict["trace_id"] = trace_id
            resp_dict["runtime_session_id"] = result.get("runtime_session_id", trace_id)
            resp_dict["problem_execution_spine"] = metadata.get("problem_execution_spine", {})
            resp_dict["visible_action_surface"] = visible_action_surface
            if demoted_fields:
                resp_dict["demoted_operator_audit_fields"] = demoted_fields

            # ── InteractionEnvelope (PR-4) — non-breaking, absent when None ──
            _ie = result.get("interaction_envelope")
            if _ie is not None:
                resp_dict["interaction_envelope"] = _ie

            # ── Aggregation log: emit when parallel_result is present ────────
            parallel_result = metadata.get("parallel_result")
            if parallel_result is not None:
                _latency_ms = (_time.monotonic() - _t0) * 1000
                try:
                    from core.task_logger import emit_task_log
                    emit_task_log(
                        "aggregation_done",
                        trace_id=trace_id,
                        group_id=metadata.get("parallel_group", ""),
                        device_id=req.device_id,
                        session_id=req.session_id or "",
                        total=parallel_result.get("total", 0),
                        succeeded=parallel_result.get("succeeded", 0),
                        failed=parallel_result.get("failed", 0),
                        cancelled=parallel_result.get("cancelled", 0),
                        latency_ms=round(_latency_ms, 1),
                        status=parallel_result.get("summary_status", ""),
                        task_type="parallel_goal",
                    )
                except Exception as _le:
                    logger.debug("Aggregation log skipped: %s", _le)

            return JSONResponse(resp_dict)
        except Exception as e:
            logger.error(f"OpenClawd 处理异常: {e}", exc_info=True)
            resp = UnifiedChatResponse(
                success=False,
                response=f"处理消息时出错: {str(e)}",
                error=str(e),
                session_id=req.session_id or "",
            )
            return JSONResponse(resp.to_json_response())

    return router
