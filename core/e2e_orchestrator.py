"""
Galaxy - 端到端编排器（便捷接口）
================================

提供 process_user_input() 函数作为统一入口，
内部委托给 EndToEndPipeline.execute()。

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
) -> Dict[str, Any]:
    """
    统一用户输入处理入口。

    完整链路:
      唤醒 → 会话管理 → 意图解析 → 智能路由 → Agent/LLM → 结果广播

    Args:
        message: 用户输入文本
        device_id: 来源设备 ID
        session_id: 会话 ID（可选，为 None 时自动创建/复用）
        user_id: 用户 ID（用于跨设备会话关联）
        context: 额外上下文（可选）

    Returns:
        {
            "success": bool,
            "reply": str,
            "session_id": str,
            "mode": str,       # "chat" | "device_control" | "agent_task" | "fallback"
            "data": {...},
            "devices_notified": [str],
        }
    """
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
