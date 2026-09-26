"""core/device_onboarding/ha_client.py — 接入平面对 Home Assistant 的两种调用。

* REST:``/api/config/config_entries/flow``(HA 自己发现、等人确认的集成)。
* WebSocket 命令:``matter/commission``(用配网码把 Matter 设备加进 HA)。

地址/令牌每次调用时从环境变量读(面板保存后即时生效,见 core/routes/config.py)。
所有失败都翻译成 :class:`HAUnavailable`,带一句给人看的原因。
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

#: 单次 REST 超时。配网这类 WS 命令另给更长的时间(Matter 入网常要几十秒)。
REST_TIMEOUT_S = 15.0
COMMISSION_TIMEOUT_S = 120.0


class HAUnavailable(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def ha_settings() -> Dict[str, str]:
    return {
        "url": os.getenv("HOME_ASSISTANT_URL", "").strip().rstrip("/"),
        "token": os.getenv("HOME_ASSISTANT_TOKEN", "").strip(),
    }


def ha_configured() -> bool:
    s = ha_settings()
    return bool(s["url"] and s["token"])


def _require() -> Dict[str, str]:
    s = ha_settings()
    if not (s["url"] and s["token"]):
        raise HAUnavailable("没配 Home Assistant:在面板「设备」里填 HOME_ASSISTANT_URL 和令牌")
    return s


async def ha_rest(method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Any:
    """调 HA REST。返回解析后的 JSON。"""
    s = _require()
    import httpx

    try:
        async with httpx.AsyncClient(timeout=REST_TIMEOUT_S) as client:
            resp = await client.request(
                method,
                f"{s['url']}{path}",
                headers={"Authorization": f"Bearer {s['token']}", "Content-Type": "application/json"},
                json=body,
            )
    except httpx.HTTPError as exc:
        raise HAUnavailable(f"连不上 Home Assistant({exc.__class__.__name__})") from exc
    if resp.status_code in (401, 403):
        raise HAUnavailable("Home Assistant 拒绝了令牌(过期、填错,或该令牌的用户不是管理员)")
    if resp.status_code >= 400:
        raise HAUnavailable(f"Home Assistant 返回 HTTP {resp.status_code}: {resp.text[:200]}")
    try:
        return resp.json()
    except ValueError as exc:
        raise HAUnavailable("Home Assistant 的返回看不懂") from exc


def _ws_url(base: str) -> str:
    if base.startswith("https://"):
        return "wss://" + base[len("https://") :] + "/api/websocket"
    if base.startswith("http://"):
        return "ws://" + base[len("http://") :] + "/api/websocket"
    return "ws://" + base + "/api/websocket"


async def ha_ws_command(payload: Dict[str, Any], *, timeout_s: float = COMMISSION_TIMEOUT_S) -> Any:
    """发一条 HA WebSocket 命令,等它的 result。成功返回 ``result`` 字段。"""
    import asyncio

    s = _require()
    import websockets

    async def _run() -> Any:
        async with websockets.connect(_ws_url(s["url"]), max_size=4 * 1024 * 1024) as ws:
            first = json.loads(await ws.recv())
            if first.get("type") == "auth_required":
                await ws.send(json.dumps({"type": "auth", "access_token": s["token"]}))
                reply = json.loads(await ws.recv())
                if reply.get("type") != "auth_ok":
                    raise HAUnavailable("Home Assistant 拒绝了令牌")
            await ws.send(json.dumps({"id": 1, **payload}))
            while True:
                msg = json.loads(await ws.recv())
                if msg.get("id") == 1 and msg.get("type") == "result":
                    if msg.get("success"):
                        return msg.get("result")
                    err = msg.get("error") or {}
                    raise HAUnavailable(
                        f"Home Assistant 执行失败:{err.get('message') or err.get('code') or '未知原因'}"
                    )

    try:
        return await asyncio.wait_for(_run(), timeout=timeout_s)
    except HAUnavailable:
        raise
    except asyncio.TimeoutError as exc:
        raise HAUnavailable(f"Home Assistant {timeout_s:.0f} 秒内没有回应") from exc
    except Exception as exc:  # noqa: BLE001 — 连接/协议层的各种异常统一翻译
        raise HAUnavailable(f"连不上 Home Assistant 的 WebSocket({exc.__class__.__name__})") from exc
