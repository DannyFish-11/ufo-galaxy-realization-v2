"""
Galaxy - 端到端编排器（便捷接口）
================================

提供 process_user_input() 函数作为统一入口，
内部委托给 EndToEndPipeline.execute() 或（当可用时）
ConstellationRuntime.run() 以获得完整的 TaskConstellation
规划→DAG→执行闭环。

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
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.E2EOrchestrator")


async def process_user_input(
    message: str,
    device_id: str = "",
    session_id: Optional[str] = None,
    user_id: str = "default",
    context: Optional[List[Dict]] = None,
    use_constellation: bool = True,
) -> Dict[str, Any]:
    """
    统一用户输入处理入口。

    完整链路:
      唤醒 → 会话管理 → 意图解析 → 智能路由 → Agent/LLM → 结果广播

    默认通过 :class:`core.constellation_runtime.ConstellationRuntime` 处理，
    以获得完整的 TaskConstellation 规划→DAG→执行闭环；降级到
    :class:`core.e2e_pipeline.EndToEndPipeline`。
    传入 ``use_constellation=False`` 可显式绕过 ConstellationRuntime。

    Args:
        message: 用户输入文本
        device_id: 来源设备 ID
        session_id: 会话 ID（可选，为 None 时自动创建/复用）
        user_id: 用户 ID（用于跨设备会话关联）
        context: 额外上下文（可选）
        use_constellation: 是否优先走 ConstellationRuntime（默认 True）

    Returns:
        {
            "success": bool,
            "reply": str,
            "session_id": str,
            "mode": str,       # "chat" | "device_control" | "agent_task" | "fallback" | "dag"
            "data": {...},
            "devices_notified": [str],
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

    # ── ConstellationRuntime 优先路径 ──────────────────────────────────
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

