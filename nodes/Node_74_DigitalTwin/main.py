# -*- coding: utf-8 -*-

"""
Node_74_DigitalTwin: 数字孪生节点 (FastAPI)

物理设备的数字孪生体服务，模拟同步设备状态，
提供状态查询、历史记录、模拟控制和多设备管理 API。
"""

import asyncio
import logging
import os
import random
import uuid
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# ---------------------------------------------------------------------------
# Port / CORS config (optional dependencies)
# ---------------------------------------------------------------------------

try:
    from core.port_config import get_service_port
    PORT = get_service_port("node_74") or 8074
except Exception as exc:
    logger.debug("Fallback triggered: %s", exc)
    PORT = int(os.getenv("PORT", "8074"))

try:
    from nodes.common.cors_config import get_cors_origins
    CORS_ORIGINS = get_cors_origins()
except Exception as exc:
    logger.debug("Fallback triggered: %s", exc)
    CORS_ORIGINS = ["*"]

# ---------------------------------------------------------------------------
# Environment variables
# ---------------------------------------------------------------------------

DEVICE_ID           = os.getenv("DEVICE_ID", "Device_001")
SIMULATION_INTERVAL = float(os.getenv("SIMULATION_INTERVAL", "5.0"))
MAX_HISTORY_LENGTH  = int(os.getenv("MAX_HISTORY_LENGTH", "1000"))

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="[Node_74] %(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("Node_74_DigitalTwin")

# ---------------------------------------------------------------------------
# Enums & Data classes
# ---------------------------------------------------------------------------

class ServiceStatus(Enum):
    INITIALIZING = "initializing"
    RUNNING      = "running"
    STOPPED      = "stopped"
    ERROR        = "error"


class DeviceStatus(Enum):
    ONLINE      = "online"
    OFFLINE     = "offline"
    MAINTENANCE = "maintenance"


@dataclass
class DeviceState:
    timestamp: str
    device_id: str
    status: str  # DeviceStatus.value
    temperature: float
    humidity: float
    location: Dict[str, float]
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RegisteredDevice:
    device_id: str
    name: str
    device_type: str
    config: Dict[str, Any]
    registered_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    last_seen: Optional[str] = None

# ---------------------------------------------------------------------------
# Digital Twin service
# ---------------------------------------------------------------------------

class DigitalTwinService:
    """数字孪生主服务"""

    def __init__(self):
        self.service_status = ServiceStatus.INITIALIZING
        self.start_time: Optional[datetime] = None
        # Primary twin state
        self._twin_state: Optional[DeviceState] = None
        self._history: deque = deque(maxlen=MAX_HISTORY_LENGTH)
        # Device registry (can manage multiple physical devices)
        self._devices: Dict[str, RegisteredDevice] = {}
        self._simulation_task: Optional[asyncio.Task] = None
        self._cycle = 0
        # Register the default device from env
        self._register_default_device()

    def _register_default_device(self):
        dev = RegisteredDevice(
            device_id=DEVICE_ID,
            name=f"Default Device ({DEVICE_ID})",
            device_type="sensor_node",
            config={"simulation_interval": SIMULATION_INTERVAL},
        )
        self._devices[DEVICE_ID] = dev

    async def start(self):
        self.service_status = ServiceStatus.RUNNING
        self.start_time = datetime.now(timezone.utc)
        self._simulation_task = asyncio.create_task(self._simulate_loop())
        logger.info(f"DigitalTwinService 启动 (device={DEVICE_ID})")

    async def stop(self):
        self.service_status = ServiceStatus.STOPPED
        if self._simulation_task:
            self._simulation_task.cancel()
            try:
                await self._simulation_task
            except asyncio.CancelledError:
                pass
        logger.info("DigitalTwinService 已停止")

    async def _simulate_loop(self):
        """持续模拟物理设备状态更新"""
        while self.service_status == ServiceStatus.RUNNING:
            try:
                self._cycle += 1
                state = self._generate_state(DEVICE_ID)
                self._twin_state = state
                self._history.append(asdict(state))
                # update device last_seen
                if DEVICE_ID in self._devices:
                    self._devices[DEVICE_ID].last_seen = state.timestamp
                logger.debug(f"[Cycle {self._cycle}] twin updated: T={state.temperature}°C")
                await asyncio.sleep(SIMULATION_INTERVAL)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"模拟循环出错: {e}")
                self.service_status = ServiceStatus.ERROR
                break

    def _generate_state(self, device_id: str) -> DeviceState:
        online_weight = [DeviceStatus.ONLINE] * 8 + [DeviceStatus.OFFLINE, DeviceStatus.MAINTENANCE]
        return DeviceState(
            timestamp=datetime.now(timezone.utc).isoformat(),
            device_id=device_id,
            status=random.choice(online_weight).value,
            temperature=round(random.uniform(18.0, 30.0) + (self._cycle % 10) * 0.1, 2),
            humidity=round(random.uniform(40.0, 60.0) - (self._cycle % 5) * 0.05, 2),
            location={"latitude": 34.0522, "longitude": -118.2437},
            metadata={
                "firmware_version": "v1.2.4",
                "battery_level": round(max(0.0, 1.0 - self._cycle / 5000), 3),
                "signal_strength": random.randint(-90, -50),
                "error_code": random.choice([0] * 19 + [1]),
                "cycle": self._cycle,
            },
        )

    # -- public interface ---------------------------------------------------

    def get_twin_state(self) -> Optional[DeviceState]:
        return self._twin_state

    def update_twin_state(self, **kwargs) -> DeviceState:
        """Manually patch current twin state"""
        if self._twin_state is None:
            raise ValueError("数字孪生尚未初始化，请等待首次模拟循环")
        for k, v in kwargs.items():
            if hasattr(self._twin_state, k):
                setattr(self._twin_state, k, v)
        self._twin_state.timestamp = datetime.now(timezone.utc).isoformat()
        self._history.append(asdict(self._twin_state))
        return self._twin_state

    def get_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        h = list(self._history)
        return h[-limit:] if limit < len(h) else h

    async def simulate_steps(self, steps: int, interval: float = 1.0) -> List[Dict[str, Any]]:
        """按需运行指定步数的模拟（不影响后台循环）"""
        results = []
        for _ in range(steps):
            self._cycle += 1
            state = self._generate_state(DEVICE_ID)
            self._twin_state = state
            self._history.append(asdict(state))
            results.append(asdict(state))
            await asyncio.sleep(interval)
        return results

    def reset_twin(self):
        """重置孪生状态"""
        self._twin_state = None
        self._history.clear()
        self._cycle = 0
        logger.info("数字孪生已重置")

    def register_device(self, device_id: str, name: str, device_type: str, config: Dict[str, Any]) -> RegisteredDevice:
        dev = RegisteredDevice(device_id=device_id, name=name, device_type=device_type, config=config)
        self._devices[device_id] = dev
        logger.info(f"设备已注册: {device_id}")
        return dev

    def list_devices(self) -> List[RegisteredDevice]:
        return list(self._devices.values())

    def uptime(self) -> float:
        if not self.start_time:
            return 0.0
        return (datetime.now(timezone.utc) - self.start_time).total_seconds()


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------

class UpdateTwinRequest(BaseModel):
    temperature: Optional[float] = None
    humidity: Optional[float] = None
    status: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class SimulateRequest(BaseModel):
    steps: int = 5
    interval: float = 0.1  # fast simulation by default

class RegisterDeviceRequest(BaseModel):
    device_id: str
    name: str
    device_type: str = "sensor_node"
    config: Dict[str, Any] = {}

class MCPCallRequest(BaseModel):
    tool: str
    params: Dict[str, Any] = {}

# ---------------------------------------------------------------------------
# FastAPI app (module-level)
# ---------------------------------------------------------------------------

_svc = DigitalTwinService()

@asynccontextmanager
async def lifespan(app: FastAPI):
    await _svc.start()
    logger.info("Node_74_DigitalTwin FastAPI 启动")
    yield
    await _svc.stop()
    logger.info("Node_74_DigitalTwin FastAPI 关闭")

app = FastAPI(
    title="Node_74_DigitalTwin",
    description="数字孪生节点 API",
    version="1.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -- routes ------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok", "node": "Node_74_DigitalTwin", "timestamp": datetime.utcnow().isoformat()}


@app.get("/status")
def status():
    twin = _svc.get_twin_state()
    return {
        "status": _svc.service_status.value,
        "node": "Node_74_DigitalTwin",
        "device_id": DEVICE_ID,
        "uptime_seconds": round(_svc.uptime(), 2),
        "twin_initialized": twin is not None,
        "current_twin_status": twin.status if twin else None,
        "history_length": len(_svc._history),
        "cycle": _svc._cycle,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/twin")
def get_twin():
    """获取当前数字孪生状态"""
    twin = _svc.get_twin_state()
    if twin is None:
        raise HTTPException(status_code=503, detail="数字孪生尚未初始化，请稍后重试")
    return asdict(twin)


@app.post("/twin/update")
def update_twin(req: UpdateTwinRequest):
    """手动更新孪生状态"""
    updates = {k: v for k, v in req.dict().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="没有提供更新字段")
    try:
        state = _svc.update_twin_state(**updates)
        return asdict(state)
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/twin/history")
def get_twin_history(limit: int = 50):
    """获取历史状态记录"""
    history = _svc.get_history(limit)
    return {"device_id": DEVICE_ID, "count": len(history), "history": history}


@app.post("/twin/simulate")
async def simulate(req: SimulateRequest):
    """按需运行模拟步骤"""
    if req.steps < 1 or req.steps > 100:
        raise HTTPException(status_code=400, detail="steps 必须在 1~100 之间")
    results = await _svc.simulate_steps(req.steps, req.interval)
    return {"steps_run": len(results), "results": results}


@app.post("/twin/reset")
def reset_twin():
    """重置数字孪生到初始状态"""
    _svc.reset_twin()
    return {"success": True, "message": "数字孪生已重置"}


@app.get("/devices")
def list_devices():
    """列出所有已注册设备"""
    devs = _svc.list_devices()
    return {"devices": [asdict(d) for d in devs], "count": len(devs)}


@app.post("/device/register", status_code=201)
def register_device(req: RegisterDeviceRequest):
    """注册新设备用于孪生监控"""
    dev = _svc.register_device(req.device_id, req.name, req.device_type, req.config)
    return asdict(dev)


@app.post("/mcp/call")
async def mcp_call(req: MCPCallRequest):
    p = req.params
    try:
        if req.tool == "get_twin":
            twin = _svc.get_twin_state()
            if twin is None:
                raise HTTPException(status_code=503, detail="not initialized")
            return {"result": asdict(twin)}
        elif req.tool == "get_history":
            return {"result": _svc.get_history(p.get("limit", 50))}
        elif req.tool == "simulate":
            results = await _svc.simulate_steps(p.get("steps", 5), p.get("interval", 0.1))
            return {"result": results}
        elif req.tool == "reset":
            _svc.reset_twin()
            return {"result": "ok"}
        elif req.tool == "register_device":
            dev = _svc.register_device(p["device_id"], p["name"], p.get("device_type","sensor_node"), p.get("config",{}))
            return {"result": asdict(dev)}
        elif req.tool == "list_devices":
            return {"result": [asdict(d) for d in _svc.list_devices()]}
        elif req.tool == "get_status":
            return {"result": _svc.service_status.value}
        else:
            raise HTTPException(status_code=404, detail=f"未知工具: {req.tool}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
