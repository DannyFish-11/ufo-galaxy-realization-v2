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

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from core.routes._models import ChatRequest
from core.unified_response import UnifiedChatResponse

logger = logging.getLogger("Galaxy.API")


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
                context=req.context,
                required_capabilities=req.required_capabilities,
                multimodal_context=req.multimodal_context,
                entry_mode=_entry_mode,
            )
            metadata = result.get("metadata", {})
            trace_id = (
                result.get("runtime_session_id")
                or result.get("trace_id")
                or metadata.get("trace_id")
                or metadata.get("request_id", "")
            )

            resp = UnifiedChatResponse(
                success=result.get("success", False),
                response=result.get("response", ""),
                intent=result.get("intent", "chat"),
                confidence=metadata.get("confidence", 1.0),
                mode=metadata.get("mode", "openclawd"),
                model=metadata.get("model", ""),
                session_id=metadata.get("session_id", req.session_id or ""),
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
            resp_dict["reply"] = result.get("response", "")
            resp_dict["trace_id"] = trace_id
            resp_dict["runtime_session_id"] = result.get("runtime_session_id", trace_id)
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

            # 记录到会话管理器
            try:
                from core.session_manager import get_session_manager
                sm = get_session_manager()
                sid = req.session_id or req.device_id or "default"
                sm.add_message(sid, "user", req.message, req.device_id)
                sm.add_message(sid, "assistant", result.get("response", ""), req.device_id)
            except Exception as _e:
                logger.debug("Session recording skipped: %s", _e)
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

