"""
Node 92: AutoControl - 统一自动操控接口

功能：
1. 统一的操控接口（Windows + Android）
2. 支持点击、输入、滚动、按键等操作
3. 支持远程设备操控
4. 自动路由到对应的平台

版本：1.0.0
日期：2026-01-22
作者：Manus AI
"""

import os
import asyncio
import httpx
from datetime import datetime
from typing import Optional, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node 92 - AutoControl", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# ============================================================================
# 配置
# ============================================================================

# 节点地址
NODE_45_DESKTOP_URL = os.getenv("NODE_45_DESKTOP_URL", "http://localhost:8045")
NODE_33_ADB_URL = os.getenv("NODE_33_ADB_URL", "http://localhost:8033")

# ============================================================================
# 数据模型
# ============================================================================

class ClickRequest(BaseModel):
    """点击"""
    device_id: Optional[str] = None
    platform: str = "windows"
    x: int
    y: int
    clicks: int = 1
    button: str = "left"

class InputRequest(BaseModel):
    """输入"""
    device_id: Optional[str] = None
    platform: str = "windows"
    text: str

class ScrollRequest(BaseModel):
    """滚动"""
    device_id: Optional[str] = None
    platform: str = "windows"
    amount: int = 100
    direction: Optional[str] = None  # up, down, left, right

class PressKeyRequest(BaseModel):
    """按键"""
    device_id: Optional[str] = None
    platform: str = "windows"
    key: str

class HotkeyRequest(BaseModel):
    """组合键"""
    device_id: Optional[str] = None
    platform: str = "windows"
    keys: str  # e.g., "ctrl+c"

# ============================================================================
# 辅助函数
# ============================================================================

async def call_node(url: str, endpoint: str, data: dict) -> dict:
    """调用其他节点"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(f"{url}{endpoint}", json=data)
            response.raise_for_status()
            return response.json()
    except Exception as e:
        return {"success": False, "error": str(e)}

# ============================================================================
# Windows 操控
# ============================================================================

async def windows_click(x: int, y: int, clicks: int = 1, button: str = "left") -> Dict[str, Any]:
    """Windows 点击"""
    result = await call_node(NODE_45_DESKTOP_URL, "/click", {
        "x": x,
        "y": y,
        "clicks": clicks,
        "button": button
    })
    return result

async def windows_input(text: str) -> Dict[str, Any]:
    """Windows 输入"""
    result = await call_node(NODE_45_DESKTOP_URL, "/type", {
        "text": text,
        "interval": 0.05
    })
    return result

async def windows_scroll(amount: int) -> Dict[str, Any]:
    """Windows 滚动"""
    result = await call_node(NODE_45_DESKTOP_URL, "/scroll", {
        "amount": amount
    })
    return result

async def windows_press_key(key: str) -> Dict[str, Any]:
    """Windows 按键"""
    result = await call_node(NODE_45_DESKTOP_URL, "/press", {
        "key": key
    })
    return result

async def windows_hotkey(keys: str) -> Dict[str, Any]:
    """Windows 组合键"""
    result = await call_node(NODE_45_DESKTOP_URL, "/hotkey", {
        "keys": keys
    })
    return result

# ============================================================================
# Android 操控
# ============================================================================

async def android_click(device_id: str, x: int, y: int) -> Dict[str, Any]:
    """Android 点击（通过 Node_33 ADB）"""
    result = await call_node(NODE_33_ADB_URL, "/tap", {
        "device_id": device_id,
        "x": x,
        "y": y
    })
    return result

async def android_input(device_id: str, text: str) -> Dict[str, Any]:
    """Android 输入（通过 Node_33 ADB）"""
    result = await call_node(NODE_33_ADB_URL, "/input_text", {
        "device_id": device_id,
        "text": text
    })
    return result

async def android_scroll(device_id: str, direction: str) -> Dict[str, Any]:
    """Android 滚动（通过 Node_33 ADB）"""
    result = await call_node(NODE_33_ADB_URL, "/swipe", {
        "device_id": device_id,
        "direction": direction
    })
    return result

async def android_press_key(device_id: str, key: str) -> Dict[str, Any]:
    """Android 按键（通过 Node_33 ADB）"""
    result = await call_node(NODE_33_ADB_URL, "/press_key", {
        "device_id": device_id,
        "key": key
    })
    return result

# ============================================================================
# API 端点
# ============================================================================

@app.post("/click")
async def click(request: ClickRequest) -> Dict[str, Any]:
    """点击"""
    if request.platform == "windows":
        return await windows_click(request.x, request.y, request.clicks, request.button)
    elif request.platform == "android":
        if not request.device_id:
            return {"success": False, "error": "device_id required for Android"}
        return await android_click(request.device_id, request.x, request.y)
    else:
        return {"success": False, "error": f"Unsupported platform: {request.platform}"}

@app.post("/input")
async def input_text(request: InputRequest) -> Dict[str, Any]:
    """输入"""
    if request.platform == "windows":
        return await windows_input(request.text)
    elif request.platform == "android":
        if not request.device_id:
            return {"success": False, "error": "device_id required for Android"}
        return await android_input(request.device_id, request.text)
    else:
        return {"success": False, "error": f"Unsupported platform: {request.platform}"}

@app.post("/scroll")
async def scroll(request: ScrollRequest) -> Dict[str, Any]:
    """滚动"""
    if request.platform == "windows":
        return await windows_scroll(request.amount)
    elif request.platform == "android":
        if not request.device_id:
            return {"success": False, "error": "device_id required for Android"}
        direction = request.direction or ("down" if request.amount > 0 else "up")
        return await android_scroll(request.device_id, direction)
    else:
        return {"success": False, "error": f"Unsupported platform: {request.platform}"}

@app.post("/press_key")
async def press_key(request: PressKeyRequest) -> Dict[str, Any]:
    """按键"""
    if request.platform == "windows":
        return await windows_press_key(request.key)
    elif request.platform == "android":
        if not request.device_id:
            return {"success": False, "error": "device_id required for Android"}
        return await android_press_key(request.device_id, request.key)
    else:
        return {"success": False, "error": f"Unsupported platform: {request.platform}"}

@app.post("/hotkey")
async def hotkey(request: HotkeyRequest) -> Dict[str, Any]:
    """组合键"""
    if request.platform == "windows":
        return await windows_hotkey(request.keys)
    elif request.platform == "android":
        # Android 不支持组合键
        return {"success": False, "error": "Hotkey not supported on Android"}
    else:
        return {"success": False, "error": f"Unsupported platform: {request.platform}"}

# ============================================================================
# 健康检查
# ============================================================================

@app.get("/health")
async def health():
    """健康检查"""
    # 检查依赖节点
    node_45_status = "unknown"
    node_33_status = "unknown"
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{NODE_45_DESKTOP_URL}/health")
            if response.status_code == 200:
                node_45_status = "healthy"
    except:
        node_45_status = "unhealthy"
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{NODE_33_ADB_URL}/health")
            if response.status_code == 200:
                node_33_status = "healthy"
    except:
        node_33_status = "unhealthy"
    
    return {
        "status": "healthy",
        "node_id": "92",
        "name": "AutoControl",
        "version": "1.0.0",
        "dependencies": {
            "node_45_desktop": node_45_status,
            "node_33_adb": node_33_status
        },
        "supported_platforms": ["windows", "android"],
        "timestamp": datetime.now().isoformat()
    }

# ============================================================================
# MCP 调用接口
# ============================================================================

@app.post("/mcp/call")
async def mcp_call(request: dict) -> Dict[str, Any]:
    """MCP 调用接口"""
    tool = request.get("tool", "")
    params = request.get("params", {})
    
    if tool == "click":
        return await click(ClickRequest(**params))
    elif tool == "input":
        return await input_text(InputRequest(**params))
    elif tool == "scroll":
        return await scroll(ScrollRequest(**params))
    elif tool == "press_key":
        return await press_key(PressKeyRequest(**params))
    elif tool == "hotkey":
        return await hotkey(HotkeyRequest(**params))
    else:
        raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

# ============================================================================
# 启动服务
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8092)
