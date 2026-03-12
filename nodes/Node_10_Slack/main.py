"""
Node 10: Slack - Slack 集成服务节点
=====================================
提供消息发送、频道管理、用户查询、表情反应等功能
"""
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from nodes.common.cors_config import get_cors_origins

try:
    from slack_sdk.web.async_client import AsyncWebClient
    from slack_sdk.errors import SlackApiError
    SLACK_SDK_AVAILABLE = True
except ImportError:
    SLACK_SDK_AVAILABLE = False

# 配置
PORT = 8010
SLACK_DEFAULT_CHANNEL = os.getenv("SLACK_DEFAULT_CHANNEL", "#general")

# 统计
stats: Dict[str, int] = {"messages_sent": 0, "api_calls": 0, "error_count": 0}

app = FastAPI(title="Node 10 - Slack", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── 工具函数 ─────────────────────────────────────────────────────────────────

def _require_slack() -> "AsyncWebClient":
    """检查 SDK 和 token，返回已配置的 AsyncWebClient。"""
    if not SLACK_SDK_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail={"error": "slack-sdk not installed. Run: pip install slack-sdk", "success": False},
        )
    token = os.getenv("SLACK_BOT_TOKEN", "")
    if not token:
        raise HTTPException(
            status_code=503,
            detail={"error": "SLACK_BOT_TOKEN not configured", "success": False},
        )
    return AsyncWebClient(token=token)


# ─── 请求模型 ────────────────────────────────────────────────────────────────

class SendMessageRequest(BaseModel):
    channel: str = SLACK_DEFAULT_CHANNEL
    text: str
    blocks: Optional[List[Dict[str, Any]]] = None


class CreateChannelRequest(BaseModel):
    name: str
    is_private: bool = False


class UserInfoRequest(BaseModel):
    user_id: str


class AddReactionRequest(BaseModel):
    channel: str
    timestamp: str
    name: str


# ─── 端点 ─────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "node_id": "10",
        "name": "Slack",
        "port": PORT,
        "slack_configured": bool(os.getenv("SLACK_BOT_TOKEN", "")),
        "slack_sdk_available": SLACK_SDK_AVAILABLE,
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/status")
async def status():
    return {
        "node": "Slack",
        "port": PORT,
        "config": {
            "token_set": bool(os.getenv("SLACK_BOT_TOKEN", "")),
            "default_channel": SLACK_DEFAULT_CHANNEL,
        },
        "stats": stats,
        "slack_sdk_available": SLACK_SDK_AVAILABLE,
        "timestamp": datetime.now().isoformat(),
    }


@app.post("/messages/send")
async def send_message(request: SendMessageRequest):
    """向指定频道发送消息。"""
    client = _require_slack()
    stats["api_calls"] += 1
    try:
        kwargs: Dict[str, Any] = {"channel": request.channel, "text": request.text}
        if request.blocks:
            kwargs["blocks"] = request.blocks
        response = await client.chat_postMessage(**kwargs)
        stats["messages_sent"] += 1
        return {"success": True, "ts": response["ts"], "channel": response["channel"]}
    except SlackApiError as exc:
        stats["error_count"] += 1
        raise HTTPException(status_code=400, detail={"error": str(exc), "success": False})
    except Exception as exc:
        stats["error_count"] += 1
        raise HTTPException(status_code=500, detail={"error": str(exc), "success": False})


@app.get("/messages/history")
async def get_history(
    channel: str = Query(..., description="频道 ID 或名称"),
    limit: int = Query(100, ge=1, le=1000),
):
    """获取频道消息历史。"""
    client = _require_slack()
    stats["api_calls"] += 1
    try:
        response = await client.conversations_history(channel=channel, limit=limit)
        return {
            "success": True,
            "channel": channel,
            "messages": response.get("messages", []),
            "has_more": response.get("has_more", False),
        }
    except SlackApiError as exc:
        stats["error_count"] += 1
        raise HTTPException(status_code=400, detail={"error": str(exc), "success": False})
    except Exception as exc:
        stats["error_count"] += 1
        raise HTTPException(status_code=500, detail={"error": str(exc), "success": False})


@app.post("/channels/create")
async def create_channel(request: CreateChannelRequest):
    """创建新频道。"""
    client = _require_slack()
    stats["api_calls"] += 1
    try:
        response = await client.conversations_create(
            name=request.name, is_private=request.is_private
        )
        channel = response.get("channel", {})
        return {"success": True, "channel_id": channel.get("id"), "name": channel.get("name")}
    except SlackApiError as exc:
        stats["error_count"] += 1
        raise HTTPException(status_code=400, detail={"error": str(exc), "success": False})
    except Exception as exc:
        stats["error_count"] += 1
        raise HTTPException(status_code=500, detail={"error": str(exc), "success": False})


@app.get("/channels/list")
async def list_channels():
    """列出所有公开频道。"""
    client = _require_slack()
    stats["api_calls"] += 1
    try:
        response = await client.conversations_list()
        channels = [
            {"id": c.get("id"), "name": c.get("name"), "is_private": c.get("is_private", False)}
            for c in response.get("channels", [])
        ]
        return {"success": True, "channels": channels, "total": len(channels)}
    except SlackApiError as exc:
        stats["error_count"] += 1
        raise HTTPException(status_code=400, detail={"error": str(exc), "success": False})
    except Exception as exc:
        stats["error_count"] += 1
        raise HTTPException(status_code=500, detail={"error": str(exc), "success": False})


@app.post("/users/info")
async def get_user_info(request: UserInfoRequest):
    """获取用户信息。"""
    client = _require_slack()
    stats["api_calls"] += 1
    try:
        response = await client.users_info(user=request.user_id)
        user = response.get("user", {})
        return {"success": True, "user": user}
    except SlackApiError as exc:
        stats["error_count"] += 1
        raise HTTPException(status_code=400, detail={"error": str(exc), "success": False})
    except Exception as exc:
        stats["error_count"] += 1
        raise HTTPException(status_code=500, detail={"error": str(exc), "success": False})


@app.post("/reactions/add")
async def add_reaction(request: AddReactionRequest):
    """向消息添加表情反应。"""
    client = _require_slack()
    stats["api_calls"] += 1
    try:
        await client.reactions_add(
            channel=request.channel,
            timestamp=request.timestamp,
            name=request.name,
        )
        return {"success": True, "channel": request.channel, "timestamp": request.timestamp, "reaction": request.name}
    except SlackApiError as exc:
        stats["error_count"] += 1
        raise HTTPException(status_code=400, detail={"error": str(exc), "success": False})
    except Exception as exc:
        stats["error_count"] += 1
        raise HTTPException(status_code=500, detail={"error": str(exc), "success": False})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
