"""
core/routes/remote_desktop.py — 远程桌面(VNC)兜底接管路由
=========================================================

人类手动接管的兜底通道(AI 自动操控为主)。仅 Tailscale 私网内、ACL 锁死、默认关。

- GET  /api/remote-desktop/status   —— 状态 + 连接地址(vnc://<tailscale_ip>:5900)
- POST /api/remote-desktop/enable   —— 开启(仅 Tailscale 在线时)
- POST /api/remote-desktop/disable  —— 关闭

这些路由由 create_api_routes 挂在【需鉴权】组下(见 core/api_routes.py),非授权请求拒绝。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

logger = logging.getLogger("Galaxy.Routes.RemoteDesktop")


def create_router(service_manager=None, config=None) -> APIRouter:
    router = APIRouter(prefix="/api/remote-desktop", tags=["remote-desktop"])

    @router.get("/status")
    async def remote_desktop_status():
        try:
            from core.remote_desktop import get_remote_desktop_manager

            return {"success": True, **get_remote_desktop_manager().status()}
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "error": str(exc)}

    @router.post("/enable")
    async def remote_desktop_enable():
        try:
            from core.remote_desktop import get_remote_desktop_manager

            return get_remote_desktop_manager().enable()
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "error": str(exc)}

    @router.post("/disable")
    async def remote_desktop_disable():
        try:
            from core.remote_desktop import get_remote_desktop_manager

            return get_remote_desktop_manager().disable()
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "error": str(exc)}

    return router
