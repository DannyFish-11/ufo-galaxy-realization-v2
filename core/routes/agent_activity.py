"""core/routes/agent_activity.py — 智能体此刻在做什么，含不进桌面三态的那部分。

端点
----
  GET /api/v1/agent/activity   智能体正在处理的全部请求

为什么要有它：桌面三态只表达**电脑发起的**请求（见 :mod:`core.presence_line`）。别的设备发起的、
智能体自己发起的工作不进三态 —— 这是对的，但这样一来它们在桌面上就完全看不见了。
``presence_summary()`` 也只数进三态的会话。这个端点把两部分都列出来：每条请求是谁发起的、
此刻在不在三态里、在哪一相。它只读，不改任何东西。

挂在 ``core/routes/system.py`` 的路由下，与系统状态同属需要 API 鉴权的一组。
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/agent/activity")
    async def agent_activity() -> Dict[str, Any]:
        """每条请求：``source`` / ``origin_device_id`` / ``desktop_originated`` / ``in_tri_state`` / ``phase``。"""
        from core.desktop_presence_runtime import get_desktop_presence_runtime

        return get_desktop_presence_runtime().agent_activity()

    return router


__all__ = ["create_router"]
