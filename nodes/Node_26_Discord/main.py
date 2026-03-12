"""
Node 26: Discord - Discord 集成服务节点
=========================================
通过 Discord REST API v10 提供消息发送、频道管理、表情反应等功能
"""
import os
import urllib.parse
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from nodes.common.cors_config import get_cors_origins

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

PORT = 8023
DISCORD_API_BASE = "https://discord.com/api/v10"

DISCORD_DEFAULT_CHANNEL_ID = os.getenv("DISCORD_DEFAULT_CHANNEL_ID", "")
DISCORD_DEFAULT_GUILD_ID = os.getenv("DISCORD_DEFAULT_GUILD_ID", "")

stats: Dict[str, int] = {"messages_sent": 0, "api_calls": 0, "error_count": 0}

app = FastAPI(title="Node 26 - Discord", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _get_token() -> str:
    token = os.getenv("DISCORD_BOT_TOKEN", "")
    if not token:
        raise HTTPException(
            status_code=503,
            detail={"error": "DISCORD_BOT_TOKEN not configured", "success": False},
        )
    return token


def _require_httpx():
    if not HTTPX_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail={"error": "httpx not installed. Run: pip install httpx", "success": False},
        )


def _auth_headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
    }


async def _discord_request(method: str, path: str, token: str, **kwargs) -> Any:
    """Make an authenticated Discord API request."""
    _require_httpx()
    stats["api_calls"] += 1
    url = f"{DISCORD_API_BASE}{path}"
    async with httpx.AsyncClient() as client:
        response = await client.request(
            method, url, headers=_auth_headers(token), timeout=15.0, **kwargs
        )
    if response.status_code == 204:
        return None
    data = response.json()
    if response.status_code >= 400:
        stats["error_count"] += 1
        raise HTTPException(
            status_code=response.status_code,
            detail={"error": data.get("message", "Discord API error"), "success": False, "discord_error": data},
        )
    return data


# ─── 请求模型 ────────────────────────────────────────────────────────────────

class SendMessageRequest(BaseModel):
    channel_id: Optional[str] = None
    content: str
    embeds: Optional[List[Dict[str, Any]]] = None
    tts: bool = False


class ChannelInfoRequest(BaseModel):
    channel_id: str


class GuildInfoRequest(BaseModel):
    guild_id: str


class AddReactionRequest(BaseModel):
    channel_id: str
    message_id: str
    emoji: str


class WebhookSendRequest(BaseModel):
    webhook_url: str
    content: str
    username: Optional[str] = None
    avatar_url: Optional[str] = None


# ─── 端点 ─────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "node_id": "26",
        "name": "Discord",
        "port": PORT,
        "configured": bool(os.getenv("DISCORD_BOT_TOKEN", "")),
        "httpx_available": HTTPX_AVAILABLE,
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/status")
async def status():
    return {
        "node_id": "26",
        "name": "Discord",
        "configured": bool(os.getenv("DISCORD_BOT_TOKEN", "")),
        "config_summary": {
            "token_set": bool(os.getenv("DISCORD_BOT_TOKEN", "")),
            "default_channel": DISCORD_DEFAULT_CHANNEL_ID or None,
            "default_guild": DISCORD_DEFAULT_GUILD_ID or None,
        },
        "stats": stats,
        "timestamp": datetime.now().isoformat(),
    }


@app.post("/messages/send")
async def send_message(request: SendMessageRequest):
    """向指定频道发送消息。"""
    token = _get_token()
    channel_id = request.channel_id or DISCORD_DEFAULT_CHANNEL_ID
    if not channel_id:
        raise HTTPException(
            status_code=400,
            detail={"error": "channel_id required (or set DISCORD_DEFAULT_CHANNEL_ID)", "success": False},
        )
    payload: Dict[str, Any] = {"content": request.content, "tts": request.tts}
    if request.embeds:
        payload["embeds"] = request.embeds
    data = await _discord_request("POST", f"/channels/{channel_id}/messages", token, json=payload)
    stats["messages_sent"] += 1
    return {"success": True, "message": data}


@app.get("/messages/list")
async def list_messages(
    channel_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
):
    """获取频道消息列表。"""
    token = _get_token()
    cid = channel_id or DISCORD_DEFAULT_CHANNEL_ID
    if not cid:
        raise HTTPException(
            status_code=400,
            detail={"error": "channel_id required", "success": False},
        )
    data = await _discord_request("GET", f"/channels/{cid}/messages?limit={limit}", token)
    return {"success": True, "messages": data, "count": len(data)}


@app.post("/channels/info")
async def channel_info(request: ChannelInfoRequest):
    """获取频道详细信息。"""
    token = _get_token()
    data = await _discord_request("GET", f"/channels/{request.channel_id}", token)
    return {"success": True, "channel": data}


@app.get("/guilds/list")
async def list_guilds():
    """列出 Bot 所在的服务器。"""
    token = _get_token()
    data = await _discord_request("GET", "/users/@me/guilds", token)
    return {"success": True, "guilds": data, "count": len(data)}


@app.post("/guilds/info")
async def guild_info(request: GuildInfoRequest):
    """获取服务器详细信息。"""
    token = _get_token()
    data = await _discord_request("GET", f"/guilds/{request.guild_id}", token)
    return {"success": True, "guild": data}


@app.post("/reactions/add")
async def add_reaction(request: AddReactionRequest):
    """为指定消息添加表情反应。"""
    token = _get_token()
    encoded_emoji = urllib.parse.quote(request.emoji)
    await _discord_request(
        "PUT",
        f"/channels/{request.channel_id}/messages/{request.message_id}/reactions/{encoded_emoji}/@me",
        token,
    )
    return {"success": True, "message": "Reaction added"}


@app.post("/webhooks/send")
async def webhook_send(request: WebhookSendRequest):
    """通过 Webhook URL 发送消息（无需 Bot Token）。"""
    _require_httpx()
    payload: Dict[str, Any] = {"content": request.content}
    if request.username:
        payload["username"] = request.username
    if request.avatar_url:
        payload["avatar_url"] = request.avatar_url

    stats["api_calls"] += 1
    async with httpx.AsyncClient() as client:
        response = await client.post(
            request.webhook_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=15.0,
        )
    if response.status_code not in (200, 204):
        stats["error_count"] += 1
        raise HTTPException(
            status_code=response.status_code,
            detail={"error": "Webhook request failed", "success": False},
        )
    stats["messages_sent"] += 1
    return {"success": True, "message": "Webhook message sent"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
