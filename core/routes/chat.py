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

import asyncio
import json
import logging
import os
from typing import Any, AsyncIterator, Dict, List, Tuple

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

from core.android_boundary_visibility_router import (
    apply_dual_repo_boundary_to_visible_action,
    extract_android_originated_info,
)
from core.hidden_context_visible_action_surface import SurfaceLayer, classify_content_layer
from core.routes._models import ChatRequest
from core.subject_facing_foreground import (
    build_subject_facing_foreground,
    build_subject_unified_lineage,
)
from core.unified_response import UnifiedChatResponse

logger = logging.getLogger("Galaxy.API")

FOREGROUND_BLOCKED_PREFIX = "当前操作受阻："
FOREGROUND_CONFIRMATION_EXPLANATION = "该操作需要你的确认后才能继续执行。"
FOREGROUND_STATUS_DONE = "操作已完成"
FOREGROUND_STATUS_NOT_DONE = "操作未完成"

# States where android_lifecycle_phase should not override current_action_state
# (the V2-derived state is already more specific).
_ANDROID_PHASE_OVERRIDE_EXCLUDED_STATES: frozenset[str] = frozenset({"blocked", "awaiting_confirmation"})

# ── 动作意图判断关键词集合 ──────────────────────────────────────────────────────
_ACTION_KEYWORDS = frozenset(
    [
        # 操作动词
        "打开",
        "关闭",
        "启动",
        "停止",
        "运行",
        "执行",
        "发送",
        "发出",
        "拍摄",
        "截图",
        "录制",
        "下载",
        "上传",
        "安装",
        "卸载",
        "设置",
        "调整",
        "切换",
        "搜索",
        "查找",
        "浏览",
        "播放",
        "暂停",
        "跳转",
        "跳过",
        "重启",
        "关机",
        "帮我",
        "帮助我",
        "请帮",
        "请你帮",
        # 英文动词
        "open",
        "close",
        "start",
        "stop",
        "run",
        "execute",
        "send",
        "take",
        "screenshot",
        "record",
        "download",
        "upload",
        "install",
        "uninstall",
        "set",
        "adjust",
        "switch",
        "search",
        "find",
        "browse",
        "play",
        "pause",
        "restart",
        "shutdown",
        "launch",
        "help me",
        "please",
    ]
)


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
        result.get("action_lifecycle_surface") if isinstance(result.get("action_lifecycle_surface"), dict) else {}
    )
    lifecycle_visible_action = result.get("visible_action") if isinstance(result.get("visible_action"), dict) else {}

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
    current_presence_mode = str(visible_metadata.get("presence_mode", "")).strip() or "unknown"
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
        lifecycle_visible_action.get("status_feedback") or result.get("status_feedback") or ""
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
            or (FOREGROUND_STATUS_DONE if current_action_state == "completed" else FOREGROUND_STATUS_NOT_DONE),
        ),
    }
    if blocker_summary or confirmation_needed:
        visible_action_surface["minimal_necessary_explanation"] = _derive_foreground_response(
            default_response=result.get("response", ""),
            blocker_summary=blocker_summary,
            confirmation_needed=confirmation_needed,
        )

    # ── Dual-repo boundary pass (goal B + C + D) ─────────────────────────────
    # Extract Android-originated information and apply the same
    # classify_content_layer logic used for V2-local metadata.  This is the
    # first runtime path where Android + V2 information share a single boundary
    # resolution function.  Android-originated blockers, confirmations, result
    # summaries, device-state, and execution signals are now governed by the
    # same foreground/background/operator classifier rather than ad-hoc handler
    # paths.
    android_info = extract_android_originated_info(result)
    dual_repo_decision = apply_dual_repo_boundary_to_visible_action(
        android_info=android_info,
        visible_action_surface=visible_action_surface,
        demoted_fields=demoted_fields,
        is_operator_request=is_operator_request,
    )

    # Re-derive blocker/confirmation from updated visible_action_surface so
    # that the foreground response reflects any Android-originated boundary
    # decisions (goal C: foreground payload changes due to dual-repo boundary).
    blocker_summary = str(visible_action_surface.get("blocker_summary", "")).strip()
    confirmation_needed = bool(visible_action_surface.get("confirmation_needed", False))

    # Re-run action_state derivation when android_lifecycle_phase provided
    android_phase = str(visible_action_surface.get("android_lifecycle_phase", "")).strip()
    if android_phase and visible_action_surface.get("current_action_state") not in (
        _ANDROID_PHASE_OVERRIDE_EXCLUDED_STATES
    ):
        if android_phase == "blocked" or blocker_summary:
            visible_action_surface["current_action_state"] = "blocked"
        elif android_phase == "confirmation_needed" or confirmation_needed:
            visible_action_surface["current_action_state"] = "awaiting_confirmation"
        elif android_phase in {"result_received", "closed", "completed"}:
            visible_action_surface["current_action_state"] = "completed"
        elif android_phase == "executing":
            visible_action_surface["current_action_state"] = "executing"

    # Update minimal_necessary_explanation if android boundary changed blocker/confirmation
    if dual_repo_decision.boundary_affected_foreground and (blocker_summary or confirmation_needed):
        visible_action_surface["minimal_necessary_explanation"] = _derive_foreground_response(
            default_response=result.get("response", ""),
            blocker_summary=blocker_summary,
            confirmation_needed=confirmation_needed,
        )

    # Expose dual-repo boundary decision for operators (non-breaking)
    if dual_repo_decision.android_boundary_applied and is_operator_request:
        visible_action_surface["dual_repo_boundary_decision"] = dual_repo_decision.to_dict()

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

    get_unified_llm_router()  # 统一 LLM 路由器入口（委派到 MultiLLMRouter）

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
            logger.debug(
                "EntrypointRouter | entry_path=canonical source=chat stats=%s",
                _er_stats,
            )
        except Exception as _er_exc:
            logger.debug("EntrypointRouter unavailable (non-fatal): %s", _er_exc)

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
                runtime_attachment_session_id=(
                    req.context[-1].get(
                        "runtime_attachment_session_id",
                        "",
                    )
                    if req.context
                    else ""
                ),
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
            resp_dict["visible_action_surface"] = visible_action_surface
            if demoted_fields:
                resp_dict["demoted_operator_audit_fields"] = demoted_fields

            # ── PR-SFF: subject_foreground — primary subject-facing foreground ──
            # SubjectFacingForeground is the canonical subject-lifecycle object
            # that organizes the default user-visible foreground around:
            #   subject_state (presence) → action_phase → foreground_event
            #   → [current_action | blocker | confirmation | result]
            # It is derived from the existing lifecycle surfaces, not from
            # scattered runtime text, and becomes the primary foreground object
            # for all non-operator responses.
            _subject_fg = build_subject_facing_foreground(
                visible_action_surface=visible_action_surface,
                action_lifecycle_surface=result.get("action_lifecycle_surface"),
                foreground_response=foreground_response,
            )
            _subject_fg_dict = _subject_fg.to_dict()
            resp_dict["subject_foreground"] = _subject_fg_dict
            resp_dict["subject_unified_lineage"] = build_subject_unified_lineage(
                subject_foreground=_subject_fg_dict,
                action_lifecycle_surface=result.get("action_lifecycle_surface"),
                android_presence_runtime=result.get("android_presence_runtime"),
                canonical_continuous_ingress=result.get("canonical_continuous_ingress"),
                ingress_carrier_context=result.get("ingress_carrier_context"),
            )
            if isinstance(result.get("desktop_presence_system"), dict):
                resp_dict["desktop_presence_system"] = result["desktop_presence_system"]

            # ── PR-SFF: control-plane demotion ───────────────────────────────
            # problem_execution_spine is a control-plane diagnostic object that
            # was previously exposed in every user response regardless of
            # audience.  It is now demoted to operator-only: users see
            # subject_foreground (subject lifecycle) instead.
            if is_operator_request:
                resp_dict["problem_execution_spine"] = metadata.get("problem_execution_spine", {})

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

    # ── SSE streaming surface (真流式: token 边生成边到) ────────────────────
    # POST /api/v1/chat/stream — same compatibility-adapter role as /api/v1/chat,
    # but emits the result as a Server-Sent Events stream.
    #
    # 真流式链路:本端点在请求上下文挂 TokenStream(core.llm_stream)→ openclawd
    # 的答案生成点(_react_loop)把它显式传给路由层 → 适配器(Ollama NDJSON /
    # OpenAI SSE)边生成边 feed → 这里逐帧转发给前端;同一份增量同时喂
    # IncrementalSpeaker(边生成边念)。级联换档/failover/工具轮会发 reset 帧,
    # 前端清空当前气泡、TTS 掐断未播句子,新一代内容重新流。
    #
    # Contract (each line is an SSE frame, JSON payload after ``data: ``):
    #   data: {"type":"phase", "phase":"liminal"}        # presence hint
    #   data: {"type":"delta", "text":"片段"}            # repeated,真增量
    #   data: {"type":"reset"}                           # 作废已流出内容(可能出现)
    #   data: {"type":"meta",  "session_id","model","runtime_session_id"}
    #   data: {"type":"done",  "response","intent","success","suggestions",
    #          "visible_action_surface","session_id","model"}   # response 为权威全文
    #   data: {"type":"error", "error":"..."}
    #
    # done.response 是【边界过滤后】的权威全文——前端以它对账替换累积增量
    # (ConversationView 的 done 分支本就如此),因此即使流出内容与最终前台文本
    # 有出入(hidden/visible 边界降级),最终展示一定正确。
    # 兜底:整条链路没流出任何增量时(适配器不支持流式/辅助路径),退回旧的
    # "整段假流式"逐字观感,行为与真流式前完全一致。
    _STREAM_CHUNK_CHARS = 2  # 假流式兜底:每帧字符数(中文逐字观感)
    _STREAM_CHUNK_DELAY = 0.012  # 假流式兜底:帧间隔(秒)

    def _sse(payload: Dict[str, Any]) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    @router.post("/api/v1/chat/stream")
    async def chat_stream(req: ChatRequest):
        """SSE 真流式对话 — 委派 DesktopPresenceRuntime → OpenClawd,token 级转发。"""

        async def _gen() -> AsyncIterator[str]:
            # 收到即进入"思考"态提示(前端在场带据此脉动)。
            yield _sse({"type": "phase", "phase": "liminal"})
            # 一体化：把用户输入实时推给面板的"实时上下文"视图（与在场共用 WS 通道）。
            _turn_id = req.session_id or ""
            try:
                from core.lumiv_websocket_bridge import emit_conversation as _emit_conv

                _emit_conv("user", req.message or "", source="text", turn_id=_turn_id)
            except Exception:
                _emit_conv = None  # type: ignore

            try:
                _chat_timeout = float(os.environ.get("GALAXY_CHAT_TIMEOUT_S", "90") or "90")
            except (TypeError, ValueError):
                _chat_timeout = 90.0

            from core.llm_stream import TokenStream, use_stream

            frames: "asyncio.Queue" = asyncio.Queue()
            sink = TokenStream(
                on_delta=lambda t: frames.put_nowait(("delta", t)),
                on_reset=lambda: frames.put_nowait(("reset", None)),
            )
            # 文字/语音锁步:每句在【被念出的那一刻】才逐句上屏,文字与语音同刻对齐。
            # reveal_q 收集"刚开口念的句子文本";speaker 的 on_sentence_start 往里塞。
            # GALAXY_TEXT_VOICE_LOCKSTEP=0 可关(桌面默认开);关或无 TTS 时退回
            # "文字逐 token 快流、语音按句松散跟随"。
            reveal_q: "asyncio.Queue" = asyncio.Queue()

            # 边生成边念:能建则建;建成后在请求上下文里抑制收尾的整段重念。
            speaker = None
            try:
                from core.speech_output import (
                    begin_incremental_speech,
                    suppress_final_speak_in_context,
                )

                speaker = begin_incremental_speech(
                    source="chat",
                    on_sentence_start=lambda t: reveal_q.put_nowait(t),
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("增量朗读建立失败(退回整段): %s", exc)

            _lockstep = speaker is not None and os.environ.get("GALAXY_TEXT_VOICE_LOCKSTEP", "1").strip().lower() in (
                "1",
                "true",
                "yes",
                "on",
            )

            async def _run():
                # 在【任务自身上下文】里挂 sink/抑制标记:contextvars 随 await 链
                # 传播到 openclawd 的答案生成点;任务结束自动消散,不污染别的请求。
                with use_stream(sink):
                    if speaker is not None:
                        suppress_final_speak_in_context()
                    from core.desktop_presence_runtime import get_desktop_presence_runtime

                    runtime = get_desktop_presence_runtime()
                    return await runtime.handle_request(
                        message=req.message,
                        source="chat",
                        device_id=req.device_id,
                        session_id=req.session_id,
                        user_id=req.user_id,
                        context=req.context,
                        required_capabilities=req.required_capabilities,
                        multimodal_context=req.multimodal_context,
                        entry_mode="local",
                    )

            task = asyncio.get_running_loop().create_task(_run())
            deadline = asyncio.get_running_loop().time() + _chat_timeout
            streamed_chars = 0
            revealed_chars = 0  # 锁步下已逐句上屏的字符数
            manifested = False
            # 有界锁步:锁步把"可见文字"押在"TTS 真的念出某句"上;可 TTS 运行期常静默
            # 失败(edge 云端不可达/无音频设备),那样一句都不会念 → 一字不上屏 → 整段憋到
            # done 帧一次性冒出。这里加"降级":喂给 TTS 但尚未露出的原始 delta 缓进 _ls_buf,
            # 若首 delta 起 _ls_grace 秒内【一句都没开口念】(revealed_chars==0),判 TTS 没在
            # 播 → 把缓存补吐、其后 delta 直接逐字上屏(等价非锁步),文字绝不再憋成一大段。
            _ls_buf: list = []  # 已喂 TTS 但未露出的原始 delta(降级时补吐)
            _ls_first_t = None  # 首个 delta 时刻(判 TTS 是否真在播的宽限起点)
            _ls_last_reveal_t = None  # 最近一次逐句露出的时刻(判中途卡住)
            _ls_fed_chars = 0  # 累计喂入原始字符数(与 revealed_chars 比较判有无未露出)
            _ls_degraded = False  # 锁步已降级为逐字直出
            try:
                _ls_grace = float(os.environ.get("GALAXY_LOCKSTEP_GRACE_S", "2.0") or "2.0")
            except (TypeError, ValueError):
                _ls_grace = 2.0
            try:
                # 中途卡住的宽限(比首句宽限更长,免把"念一句长句"误判卡死;即便偶尔误判,
                # 后果只是文字提前于语音、优雅不破)。
                _ls_stall_grace = float(os.environ.get("GALAXY_LOCKSTEP_STALL_S", "8.0") or "8.0")
            except (TypeError, ValueError):
                _ls_stall_grace = 8.0
            try:
                # 消费循环:增量帧即到即转;runtime 任务完成且队列排空后出循环。
                while True:
                    if task.done() and frames.empty():
                        break
                    if asyncio.get_running_loop().time() >= deadline:
                        raise asyncio.TimeoutError
                    kind = payload = None
                    try:
                        kind, payload = await asyncio.wait_for(frames.get(), timeout=0.1)
                    except asyncio.TimeoutError:
                        pass  # 无新帧:落到下面锁步露出/循环条件复查
                    if kind == "delta":
                        if _lockstep and not _ls_degraded:
                            # 锁步(未降级):喂 TTS + 缓存,暂不上屏;文字随语音逐句露出。
                            speaker.feed(payload)
                            _ls_buf.append(payload)
                            _ls_fed_chars += len(payload)
                            if _ls_first_t is None:
                                _ls_first_t = asyncio.get_running_loop().time()
                        else:
                            # 非锁步 或 锁步已降级:逐字直接上屏。
                            if not manifested:
                                manifested = True
                                yield _sse({"type": "phase", "phase": "manifest"})
                            streamed_chars += len(payload)
                            yield _sse({"type": "delta", "text": payload})
                            if speaker is not None:
                                speaker.feed(payload)
                    elif kind == "reset":
                        if _lockstep:
                            while not reveal_q.empty():
                                reveal_q.get_nowait()
                            revealed_chars = 0
                            _ls_buf.clear()
                            _ls_first_t = None
                            _ls_last_reveal_t = None
                            _ls_fed_chars = 0
                        streamed_chars = 0
                        yield _sse({"type": "reset"})
                        if speaker is not None:
                            speaker.reset()
                    # 锁步(未降级):把"刚开口念的句子"逐句吐出(文字与语音同刻)。
                    if _lockstep and not _ls_degraded:
                        while not reveal_q.empty():
                            sent = reveal_q.get_nowait()
                            if not manifested:
                                manifested = True
                                yield _sse({"type": "phase", "phase": "manifest"})
                            revealed_chars += len(sent)
                            streamed_chars += len(sent)
                            _ls_last_reveal_t = asyncio.get_running_loop().time()
                            yield _sse({"type": "delta", "text": sent})
                        # 有界降级:两种"TTS 没在推进"都转逐字直出,文字绝不再憋成一大段。
                        #  ① 一句都没开口念(revealed_chars==0)→ 首句宽限 _ls_grace。
                        #  ② 念了一部分后中途卡住(有未露出内容、且 _ls_stall_grace 内无新露出)。
                        # 降级后其后 delta 走 else 分支直出,仍继续喂 speaker 让语音尽力跟随。
                        _now = asyncio.get_running_loop().time()
                        _idle_ref = _ls_last_reveal_t if _ls_last_reveal_t is not None else _ls_first_t
                        _total_fail = (
                            revealed_chars == 0 and _ls_first_t is not None and (_now - _ls_first_t) > _ls_grace
                        )
                        _mid_stall = (
                            revealed_chars > 0
                            and (_ls_fed_chars - revealed_chars) > 8
                            and _idle_ref is not None
                            and (_now - _idle_ref) > _ls_stall_grace
                        )
                        if not _ls_degraded and _ls_buf and (_total_fail or _mid_stall):
                            _ls_degraded = True
                            if revealed_chars > 0:
                                # 已露出过一部分:先 reset 前端文字(不动语音,让其继续尾随),
                                # 再把【原始全量】补吐,规避与已露出内容重复(露出经 strip 归一,
                                # 与原始 delta 不字字对齐,无法安全切片,故整段 reset 重放最稳)。
                                yield _sse({"type": "reset"})
                                revealed_chars = 0
                                streamed_chars = 0
                            if not manifested:
                                manifested = True
                                yield _sse({"type": "phase", "phase": "manifest"})
                            _catchup = "".join(_ls_buf)
                            _ls_buf.clear()
                            if _catchup:
                                streamed_chars += len(_catchup)
                                yield _sse({"type": "delta", "text": _catchup})
                            logger.info(
                                "文字/语音锁步降级(%s):转逐字流式,语音继续尽力跟随。",
                                "一句未念出" if _total_fail else "中途卡住",
                            )

                result = task.result()  # 异常在此抛出,统一走下面的 except
                metadata = result.get("metadata", {})
                if not isinstance(metadata, dict):
                    metadata = {}
                is_operator = _is_operator_request(req)
                (
                    metadata,
                    visible_action_surface,
                    foreground_response,
                    _demoted,
                ) = _apply_hidden_visible_boundary(
                    result=result,
                    metadata=metadata,
                    is_operator_request=is_operator,
                )
                session_id = metadata.get(
                    "conversation_session_id",
                    metadata.get("session_id", req.session_id or ""),
                )
                model = metadata.get("model", "")
                runtime_session_id = result.get("runtime_session_id", "")

                yield _sse(
                    {
                        "type": "meta",
                        "session_id": session_id,
                        "model": model,
                        "runtime_session_id": runtime_session_id,
                    }
                )

                text = foreground_response or ""
                # 一体化：AI 回应实时推给面板"实时上下文"视图。
                if _emit_conv is not None:
                    _emit_conv("ai", text, source="text", turn_id=_turn_id)

                if _lockstep and not _ls_degraded and speaker is not None:
                    # ── 锁步收尾(TTS 正常)────────────────────────────────────
                    # 全程没有任何 delta 喂进去过(非流式适配器:整段一次返回)→ 把全文喂进去念。
                    # (有 delta 时已逐个喂过,不再整段重喂,免重复。)
                    try:
                        if _ls_first_t is None and text:
                            speaker.feed(text)
                        speaker.finish()
                    except Exception:  # noqa: BLE001
                        pass
                    # 等 _player 把剩余句子念完,边念边【逐句】露出;grace 有界,
                    # 语音卡住也绝不无限挂 SSE。~0.2s/字 宽松估播放时长,封顶 180s。
                    _loop = asyncio.get_running_loop()
                    speech_grace = _loop.time() + min(180.0, max(20.0, len(text) * 0.2))
                    ptask = getattr(speaker, "_player_task", None)
                    while True:
                        drained = False
                        while not reveal_q.empty():
                            sent = reveal_q.get_nowait()
                            if not manifested:
                                manifested = True
                                yield _sse({"type": "phase", "phase": "manifest"})
                            revealed_chars += len(sent)
                            streamed_chars += len(sent)
                            yield _sse({"type": "delta", "text": sent})
                            drained = True
                        if (ptask is None or ptask.done()) and reveal_q.empty():
                            break
                        if _loop.time() >= speech_grace:
                            break
                        if not drained:
                            await asyncio.sleep(0.05)
                    # 兜底:语音未能覆盖全文(TTS 部分/全失败)不在此逐字补 ——
                    # 下面 done 的 response=全文 会把气泡快照到权威全文,自然补齐。
                elif _lockstep and _ls_degraded and speaker is not None:
                    # 锁步已降级:文字早已逐字直出(streamed_chars>0),reveal_q 不再取用。
                    # 补吐理论残余,并收尾语音(尾音由后台 _player 播完,不阻塞 done ——
                    # 文字已完整,不必等语音)。
                    try:
                        if _ls_buf:
                            _tail = "".join(_ls_buf)
                            _ls_buf.clear()
                            if _tail:
                                streamed_chars += len(_tail)
                                yield _sse({"type": "delta", "text": _tail})
                        speaker.finish()
                    except Exception:  # noqa: BLE001
                        pass
                elif streamed_chars == 0 and text:
                    # 非锁步兜底:没有任何真增量(非流式适配器/边界降级为全新文本)。
                    # 退回逐字假流式,观感与真流式前完全一致。
                    if not manifested:
                        yield _sse({"type": "phase", "phase": "manifest"})
                    for i in range(0, len(text), _STREAM_CHUNK_CHARS):
                        yield _sse({"type": "delta", "text": text[i : i + _STREAM_CHUNK_CHARS]})
                        await asyncio.sleep(_STREAM_CHUNK_DELAY)

                # 非锁步的边生成边念收尾:真增量冲刷尾句;零增量把权威全文喂进去念。
                # (锁步已在上面 finish 过,不重复。)
                if speaker is not None and not _lockstep:
                    try:
                        if streamed_chars == 0 and text:
                            speaker.feed(text)
                        speaker.finish()
                    except Exception:  # noqa: BLE001
                        pass

                yield _sse(
                    {
                        "type": "done",
                        "success": result.get("success", False),
                        "response": text,
                        "intent": result.get("intent", "chat"),
                        "suggestions": metadata.get("suggestions", []) or [],
                        "session_id": session_id,
                        "model": model,
                        "runtime_session_id": runtime_session_id,
                        "visible_action_surface": visible_action_surface,
                    }
                )
                # 回到待机态。
                yield _sse({"type": "phase", "phase": "silent"})
            except asyncio.TimeoutError:
                logger.error("chat_stream 超时(%.0fs)——终止本轮并收流", _chat_timeout)
                task.cancel()
                if speaker is not None:
                    try:
                        await speaker.interrupt()
                    except Exception:  # noqa: BLE001
                        pass
                yield _sse(
                    {
                        "type": "error",
                        "error": (
                            f"响应超时（{int(_chat_timeout)}s 未返回）。"
                            "请在「模型」tab 配置可用的 API Key 或本地 Ollama 后重试。"
                        ),
                    }
                )
                yield _sse({"type": "phase", "phase": "silent"})
            except Exception as exc:  # noqa: BLE001 — surface any failure to the client
                logger.error("chat_stream 处理异常: %s", exc, exc_info=True)
                task.cancel()
                if speaker is not None:
                    try:
                        await speaker.interrupt()
                    except Exception:  # noqa: BLE001
                        pass
                yield _sse({"type": "error", "error": str(exc)})
                yield _sse({"type": "phase", "phase": "silent"})
            finally:
                # 客户端断连(生成器被提前关闭)时清场:取消在飞的 runtime 任务、
                # 掐断朗读。正常完成路径这里全是无害的空操作。
                if not task.done():
                    task.cancel()
                    if speaker is not None:
                        try:
                            await speaker.interrupt()
                        except Exception:  # noqa: BLE001
                            pass

        return StreamingResponse(
            _gen(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # 关掉反代缓冲,保证逐帧到达
            },
        )

    return router
