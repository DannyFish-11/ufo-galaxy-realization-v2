"""
Node 27: SmartHome - 智能家居控制服务节点
==========================================
通过 Home Assistant REST API 及内存设备注册表提供智能家居控制功能。
支持 Home Assistant 直连、Tuya 配置，并提供本地 in-memory 设备回退。
"""
import os
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from nodes.common.cors_config import get_cors_origins

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

logger = logging.getLogger(__name__)

PORT = 8027

HA_URL = os.getenv("HOME_ASSISTANT_URL", "").rstrip("/")
HA_TOKEN = os.getenv("HOME_ASSISTANT_TOKEN", "")
TUYA_API_KEY = os.getenv("TUYA_API_KEY", "")
TUYA_API_SECRET = os.getenv("TUYA_API_SECRET", "")
TUYA_REGION = os.getenv("TUYA_REGION", "cn")

# In-memory device registry and scene store (fallback / standalone mode).
# _devices: {device_id: {device_id, name, type, protocol, ip_address, state, online, registered_at}}
# _scenes:  {scene_id: {scene_id, ...}} — populated externally or via HA.
# Note: contents are lost on process restart.
_devices: Dict[str, Dict[str, Any]] = {}
_scenes: Dict[str, Dict[str, Any]] = {}

stats: Dict[str, int] = {"commands_sent": 0, "ha_calls": 0, "error_count": 0}

app = FastAPI(title="Node 27 - SmartHome", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── 工具函数 ─────────────────────────────────────────────────────────────────

def _ha_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {HA_TOKEN}",
        "Content-Type": "application/json",
    }


def _require_ha():
    if not HA_URL or not HA_TOKEN:
        raise HTTPException(
            status_code=503,
            detail={"error": "HOME_ASSISTANT_URL or HOME_ASSISTANT_TOKEN not configured", "success": False},
        )
    if not HTTPX_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail={"error": "httpx not installed. Run: pip install httpx", "success": False},
        )


async def _ha_get(path: str) -> Any:
    _require_ha()
    stats["ha_calls"] += 1
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{HA_URL}/api{path}", headers=_ha_headers(), timeout=15.0)
    if response.status_code >= 400:
        stats["error_count"] += 1
        raise HTTPException(
            status_code=response.status_code,
            detail={"error": f"Home Assistant error: {response.text}", "success": False},
        )
    return response.json()


async def _ha_post(path: str, payload: Dict[str, Any]) -> Any:
    _require_ha()
    stats["ha_calls"] += 1
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{HA_URL}/api{path}", headers=_ha_headers(), json=payload, timeout=15.0
        )
    if response.status_code >= 400:
        stats["error_count"] += 1
        raise HTTPException(
            status_code=response.status_code,
            detail={"error": f"Home Assistant error: {response.text}", "success": False},
        )
    return response.json()


# ─── 请求模型 ────────────────────────────────────────────────────────────────

class RegisterDeviceRequest(BaseModel):
    device_id: str
    name: str
    type: str
    protocol: str
    ip_address: Optional[str] = None


class ControlDeviceRequest(BaseModel):
    device_id: str
    action: str
    params: Dict[str, Any] = {}


class TriggerSceneRequest(BaseModel):
    scene_id: str


class HACallRequest(BaseModel):
    domain: str
    service: str
    entity_id: Optional[str] = None
    data: Dict[str, Any] = {}


# ─── 端点 ─────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "node_id": "27",
        "name": "SmartHome",
        "port": PORT,
        "ha_configured": bool(HA_URL and HA_TOKEN),
        "tuya_configured": bool(TUYA_API_KEY and TUYA_API_SECRET),
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/status")
async def status():
    integrations: List[str] = []
    if HA_URL and HA_TOKEN:
        integrations.append("home_assistant")
    if TUYA_API_KEY and TUYA_API_SECRET:
        integrations.append("tuya")
    if not integrations:
        integrations.append("in_memory_mock")

    return {
        "node_id": "27",
        "name": "SmartHome",
        "configured": bool(HA_URL and HA_TOKEN),
        "config_summary": {
            "ha_url": HA_URL or None,
            "ha_token_set": bool(HA_TOKEN),
            "tuya_key_set": bool(TUYA_API_KEY),
            "tuya_region": TUYA_REGION,
        },
        "device_count": len(_devices),
        "scene_count": len(_scenes),
        "integrations_available": integrations,
        "stats": stats,
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/devices")
async def list_devices():
    """列出所有已知设备。"""
    return {
        "success": True,
        "devices": list(_devices.values()),
        "count": len(_devices),
    }


@app.post("/devices/register")
async def register_device(request: RegisterDeviceRequest):
    """注册新设备到内存注册表。"""
    device = {
        "device_id": request.device_id,
        "name": request.name,
        "type": request.type,
        "protocol": request.protocol,
        "ip_address": request.ip_address,
        "state": {},
        "online": True,
        "registered_at": datetime.now().isoformat(),
    }
    _devices[request.device_id] = device
    return {"success": True, "device": device}


@app.get("/devices/{device_id}")
async def get_device(device_id: str):
    """获取指定设备的详细信息。"""
    device = _devices.get(device_id)
    if not device:
        raise HTTPException(
            status_code=404,
            detail={"error": f"Device '{device_id}' not found", "success": False},
        )
    return {"success": True, "device": device}


@app.post("/devices/control")
async def control_device(request: ControlDeviceRequest):
    """控制设备（on/off/set_brightness 等）。如果配置了 HA，优先转发。"""
    stats["commands_sent"] += 1
    device = _devices.get(request.device_id)

    # Home Assistant path
    if HA_URL and HA_TOKEN:
        action_map = {
            "on": ("homeassistant", "turn_on"),
            "off": ("homeassistant", "turn_off"),
            "toggle": ("homeassistant", "toggle"),
            "set_brightness": ("light", "turn_on"),
            "set_temperature": ("climate", "set_temperature"),
        }
        domain_service = action_map.get(request.action)
        if domain_service:
            domain, service = domain_service
            payload: Dict[str, Any] = {"entity_id": request.device_id}
            payload.update(request.params)
            result = await _ha_post(f"/services/{domain}/{service}", payload)
            return {"success": True, "result": result, "source": "home_assistant"}

    # In-memory fallback
    if not device:
        raise HTTPException(
            status_code=404,
            detail={"error": f"Device '{request.device_id}' not found", "success": False},
        )

    if request.action in ("on",):
        device["state"]["power"] = True
    elif request.action == "toggle":
        device["state"]["power"] = not device["state"].get("power", False)
    elif request.action == "off":
        device["state"]["power"] = False
    elif request.action == "set_brightness":
        device["state"]["brightness"] = request.params.get("brightness", 100)
    elif request.action == "set_temperature":
        device["state"]["temperature"] = request.params.get("temperature", 22.0)
    else:
        device["state"].update(request.params)

    device["state"]["last_action"] = request.action
    device["state"]["updated_at"] = datetime.now().isoformat()

    return {"success": True, "device_id": request.device_id, "action": request.action, "state": device["state"], "source": "in_memory"}


@app.get("/scenes")
async def list_scenes():
    """列出所有场景。"""
    return {"success": True, "scenes": list(_scenes.values()), "count": len(_scenes)}


@app.post("/scenes/trigger")
async def trigger_scene(request: TriggerSceneRequest):
    """触发指定场景。如果配置了 HA，优先通过 HA 触发。"""
    if HA_URL and HA_TOKEN:
        result = await _ha_post(f"/services/scene/turn_on", {"entity_id": request.scene_id})
        return {"success": True, "result": result, "source": "home_assistant"}

    scene = _scenes.get(request.scene_id)
    if not scene:
        raise HTTPException(
            status_code=404,
            detail={"error": f"Scene '{request.scene_id}' not found", "success": False},
        )
    return {"success": True, "scene_id": request.scene_id, "triggered_at": datetime.now().isoformat(), "source": "in_memory"}


@app.post("/ha/call")
async def ha_call(request: HACallRequest):
    """直接调用 Home Assistant 服务。需要 HA 配置。"""
    payload: Dict[str, Any] = dict(request.data)
    if request.entity_id:
        payload["entity_id"] = request.entity_id
    result = await _ha_post(f"/services/{request.domain}/{request.service}", payload)
    return {"success": True, "result": result}


@app.get("/ha/states")
async def ha_states():
    """获取 Home Assistant 所有实体状态。需要 HA 配置。"""
    states = await _ha_get("/states")
    return {"success": True, "states": states, "count": len(states)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
