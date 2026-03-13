"""
Galaxy Dashboard 后端
====================

使用已有协议:
- core/node_protocol.py
- enhancements/multidevice/device_protocol.py
- nodes/common/mcp_adapter.py

版本: v2.3.23
"""

import os
import sys
import json
import asyncio
import logging
import threading
import time as _time_module
import uuid as _uuid_module
from datetime import datetime
from typing import Dict, List, Optional, Any

# 添加项目路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

try:
    from core.unified_response import UnifiedChatResponse
except ImportError:
    # Fallback: define a minimal UnifiedChatResponse for standalone mode
    from pydantic import BaseModel as _BaseModel
    class UnifiedChatResponse(_BaseModel):
        success: bool = True
        response: str = ""
        intent: str = ""
        confidence: float = 0.0
        mode: str = "chat"
        suggestions: list = []
        data: dict = {}
        error: str = ""
        session_id: str = ""

        def to_json_response(self) -> dict:
            return self.model_dump()
from nodes.common.cors_config import get_cors_origins

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# 导入 ASCII 艺术字
try:
    from core.ascii_art import GALAXY_ASCII_MINIMAL
except ImportError:
    GALAXY_ASCII_MINIMAL = "GALAXY - L4 Autonomous Intelligence System"

# 导入整合核心
try:
    from core.galaxy_core import galaxy_core
    GALAXY_CORE_AVAILABLE = True
except ImportError:
    GALAXY_CORE_AVAILABLE = False
    galaxy_core = None

# 导入现代意图解析器和对话记忆
try:
    from core.ai_intent import get_intent_parser, get_conversation_memory
    MODERN_INTENT_AVAILABLE = True
except ImportError:
    MODERN_INTENT_AVAILABLE = False

# 导入已有协议
try:
    from core.node_protocol import Message, MessageHeader, MessageType
    NODE_PROTOCOL_AVAILABLE = True
except ImportError:
    NODE_PROTOCOL_AVAILABLE = False

try:
    from enhancements.multidevice.device_protocol import AIPMessage, AIPProtocol
    DEVICE_PROTOCOL_AVAILABLE = True
except ImportError:
    DEVICE_PROTOCOL_AVAILABLE = False

# 导入 Agent 工厂
try:
    from core.agent_factory import AgentFactory, AGENT_TEMPLATES
    agent_factory = AgentFactory()
    AGENT_FACTORY_AVAILABLE = True
except ImportError:
    AGENT_FACTORY_AVAILABLE = False
    agent_factory = None

# 导入 LLM 路由器 — 使用全局单例，确保与 OpenClawd/Agent 共享同一实例
try:
    from core.multi_llm_router import get_llm_router
    llm_router = get_llm_router()
    LLM_ROUTER_AVAILABLE = True
    # 将路由器注入 AgentFactory
    if AGENT_FACTORY_AVAILABLE and agent_factory:
        agent_factory.llm_router = llm_router
except ImportError:
    LLM_ROUTER_AVAILABLE = False
    llm_router = None

# 导入孪生模型管理器
try:
    from enhancements.agent_factory.twin_model import (
        TwinModelManager, CouplingMode as TwinCouplingMode, twin_manager as _twin_mgr
    )
    twin_manager = _twin_mgr  # 全局单例
    TWIN_AVAILABLE = True
except ImportError:
    TWIN_AVAILABLE = False
    twin_manager = None
    TwinCouplingMode = None

# 导入设备数字孪生引擎
try:
    from core.digital_twin_engine import get_digital_twin_engine
    device_twin_engine = get_digital_twin_engine()
    DEVICE_TWIN_AVAILABLE = True
except ImportError:
    DEVICE_TWIN_AVAILABLE = False
    device_twin_engine = None

# 导入 Agent Team 管理器（注入 twin_manager，需要 factory 和 router 都可用）
try:
    from core.agent_team import TeamManager
    if agent_factory and llm_router:
        team_manager = TeamManager(agent_factory, llm_router, twin_manager=twin_manager)
        TEAM_MANAGER_AVAILABLE = True
    else:
        team_manager = None
        TEAM_MANAGER_AVAILABLE = False
except (ImportError, Exception) as e:
    TEAM_MANAGER_AVAILABLE = False
    team_manager = None

# 导入协议管理路由
try:
    from core.routes import protocols as protocols_routes
    PROTOCOLS_ROUTES_AVAILABLE = True
except ImportError:
    PROTOCOLS_ROUTES_AVAILABLE = False
    protocols_routes = None

# 导入可观测性路由
try:
    from core.routes import observability as observability_routes
    OBSERVABILITY_ROUTES_AVAILABLE = True
except ImportError:
    OBSERVABILITY_ROUTES_AVAILABLE = False
    observability_routes = None

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger("Galaxy")

# 打印 ASCII 艺术字
print(GALAXY_ASCII_MINIMAL)

# ============================================================================
# P2: Device Trace Store — lightweight in-process store backed by JSON file
# ============================================================================

class DeviceTraceStore:
    """Persist and retrieve per-device execution traces.

    Traces are kept in memory and flushed to ``data/device_traces.json``
    on every write so they survive server restarts.  The file is created
    automatically if it does not exist.
    """

    _DEFAULT_MAX_TRACES = 500  # global cap to prevent unbounded growth

    def __init__(self, path: Optional[str] = None, max_traces: int = 0) -> None:
        _data_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "data",
        )
        os.makedirs(_data_dir, exist_ok=True)
        self._path: str = path or os.path.join(_data_dir, "device_traces.json")
        self._max_traces: int = max_traces if max_traces > 0 else self._DEFAULT_MAX_TRACES
        self._lock = threading.Lock()
        self._traces: List[dict] = self._load()

    # ── persistence ──────────────────────────────────────────────────────────

    def _load(self) -> List[dict]:
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                return data if isinstance(data, list) else []
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _flush(self) -> None:
        try:
            with open(self._path, "w", encoding="utf-8") as fh:
                json.dump(self._traces, fh, ensure_ascii=False, indent=2)
        except OSError as exc:
            logger.warning("DeviceTraceStore: failed to flush traces: %s", exc)

    # ── public API ────────────────────────────────────────────────────────────

    def add(
        self,
        *,
        device_id: str,
        command: str,
        params: dict,
        result: dict,
        agent_id: Optional[str] = None,
        task_id: Optional[str] = None,
        duration_ms: Optional[float] = None,
    ) -> dict:
        """Record one execution trace and return it."""
        trace = {
            "trace_id": f"tr_{int(_time_module.time() * 1000)}_{device_id}",
            "device_id": device_id,
            "command": command,
            "params": params,
            "result": result,
            "success": bool(result.get("success", True)),
            "error": result.get("error"),
            "agent_id": agent_id,
            "task_id": task_id,
            "duration_ms": duration_ms,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        with self._lock:
            self._traces.append(trace)
            # cap
            if len(self._traces) > self._max_traces:
                self._traces = self._traces[-self._max_traces :]
            self._flush()
        return trace

    def all(self) -> List[dict]:
        with self._lock:
            return list(self._traces)

    def for_device(self, device_id: str) -> List[dict]:
        with self._lock:
            return [t for t in self._traces if t["device_id"] == device_id]

    def recent(self, n: int = 50) -> List[dict]:
        with self._lock:
            return list(self._traces[-n:])

    def clear(self) -> None:
        with self._lock:
            self._traces.clear()
            self._flush()


# Global singleton
_device_trace_store = DeviceTraceStore()

# ============================================================================
# P2: In-memory agent–device mapping registry
# ============================================================================

class _AgentDeviceRegistry:
    """Lightweight in-memory store for agent↔device task assignments."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # {agent_id: {"agent_id", "device_id", "task", "status", "started_at", "updated_at"}}
        self._assignments: Dict[str, dict] = {}

    def assign(self, agent_id: str, device_id: str, task: str, status: str = "running") -> dict:
        entry = {
            "agent_id": agent_id,
            "device_id": device_id,
            "task": task,
            "status": status,
            "started_at": datetime.utcnow().isoformat() + "Z",
            "updated_at": datetime.utcnow().isoformat() + "Z",
        }
        with self._lock:
            self._assignments[agent_id] = entry
        return entry

    def update_status(self, agent_id: str, status: str) -> None:
        with self._lock:
            if agent_id in self._assignments:
                self._assignments[agent_id]["status"] = status
                self._assignments[agent_id]["updated_at"] = datetime.utcnow().isoformat() + "Z"

    def release(self, agent_id: str) -> None:
        with self._lock:
            self._assignments.pop(agent_id, None)

    def all(self) -> List[dict]:
        with self._lock:
            return list(self._assignments.values())

    def for_device(self, device_id: str) -> List[dict]:
        with self._lock:
            return [a for a in self._assignments.values() if a["device_id"] == device_id]


_agent_device_registry = _AgentDeviceRegistry()

# ============================================================================
# P2: In-memory orchestration task store
# ============================================================================

class _OrchestrationStore:
    """Store multi-device task orchestration records."""

    _MAX = 200

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tasks: List[dict] = []

    def record(
        self,
        *,
        task_id: str,
        description: str,
        device_assignments: List[dict],
        status: str = "running",
    ) -> dict:
        entry = {
            "task_id": task_id,
            "description": description,
            "device_assignments": device_assignments,
            "status": status,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "updated_at": datetime.utcnow().isoformat() + "Z",
            "results": {},
        }
        with self._lock:
            self._tasks.append(entry)
            if len(self._tasks) > self._MAX:
                self._tasks = self._tasks[-self._MAX :]
        return entry

    def update(self, task_id: str, *, status: Optional[str] = None, results: Optional[dict] = None) -> None:
        with self._lock:
            for t in self._tasks:
                if t["task_id"] == task_id:
                    if status:
                        t["status"] = status
                    if results:
                        t["results"].update(results)
                    t["updated_at"] = datetime.utcnow().isoformat() + "Z"
                    break

    def all(self) -> List[dict]:
        with self._lock:
            return list(self._tasks)

    def recent(self, n: int = 50) -> List[dict]:
        with self._lock:
            return list(self._tasks[-n:])


_orchestration_store = _OrchestrationStore()

# 创建应用 (使用 lifespan 替代 deprecated on_event)
from contextlib import asynccontextmanager

@asynccontextmanager
async def _lifespan(app):
    # startup
    logger.info("=" * 60)
    print(GALAXY_ASCII_MINIMAL)
    logger.info("Galaxy Dashboard v2.3.23")
    logger.info("=" * 60)
    if NODE_PROTOCOL_AVAILABLE:
        logger.info("✅ node_protocol 已加载")
    if DEVICE_PROTOCOL_AVAILABLE:
        logger.info("✅ device_protocol 已加载")
    if GALAXY_CORE_AVAILABLE:
        logger.info("✅ galaxy_core 已加载")
    yield
    # shutdown (nothing needed)

app = FastAPI(title="Galaxy Dashboard", version="2.3.23", lifespan=_lifespan)

# Default permission set for newly created Agents — all capabilities disabled
DEFAULT_AGENT_PERMISSIONS: Dict[str, bool] = {
    "filesystem": False,
    "terminal": False,
    "network": False,
    "browser": False,
}

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册协议管理路由
_PROTOCOLS_REGISTERED = False
if PROTOCOLS_ROUTES_AVAILABLE and protocols_routes:
    try:
        app.include_router(protocols_routes.create_router())
        _PROTOCOLS_REGISTERED = True
        logger.info("已注册协议管理路由 (/api/v1/protocols/*)")
    except Exception as _e:
        logger.warning(f"协议管理路由注册失败: {_e}")

# 注册可观测性路由（实时状态面板数据源）
_OBSERVABILITY_REGISTERED = False
if OBSERVABILITY_ROUTES_AVAILABLE and observability_routes:
    try:
        app.include_router(observability_routes.create_router())
        _OBSERVABILITY_REGISTERED = True
        logger.info("已注册可观测性路由 (/api/v1/observability/*)")
    except Exception as _e:
        logger.warning(f"可观测性路由注册失败: {_e}")

# 静态文件
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend", "public")

# 挂载静态文件目录（CSS/JS/图片等资源）
if os.path.isdir(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

# ============================================================================
# 静态文件路由
# ============================================================================

@app.get("/")
async def root():
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Galaxy Dashboard API", "version": "2.3.23"}

# ============================================================================
# ASCII 艺术字 API
# ============================================================================

@app.get("/api/v1/ascii")
async def get_ascii_art(style: str = "minimal"):
    """获取 ASCII 艺术字"""
    return {"ascii": GALAXY_ASCII_MINIMAL}


# ============================================================================
# 健康检查端点 (标准 /health 与 /api/v1/health)
# ============================================================================

@app.get("/health")
@app.get("/api/v1/health")
async def health_check():
    """标准健康检查端点，供负载均衡、Kubernetes 存活探针等使用。

    返回:
        status: "ok" 表示服务正常运行
        version: 当前 API 版本
        timestamp: UTC ISO-8601 时间戳
        components: 关键子组件的可用状态
    """
    components = {
        "galaxy_core": GALAXY_CORE_AVAILABLE,
        "llm_router":  LLM_ROUTER_AVAILABLE,
        "agent_factory": AGENT_FACTORY_AVAILABLE,
        "node_protocol": NODE_PROTOCOL_AVAILABLE,
        "device_protocol": DEVICE_PROTOCOL_AVAILABLE,
    }
    logger.debug("Health check: %s", components)
    return {
        "status": "ok",
        "version": "2.3.23",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "components": components,
    }


@app.get("/api/v1/system/info")
async def get_system_info():
    """获取系统信息"""
    info = {
        "name": "Galaxy",
        "version": "2.3.23",
        "description": "L4 Autonomous Intelligence System",
        "ascii": GALAXY_ASCII_MINIMAL,
        "protocols": {
            "node_protocol": NODE_PROTOCOL_AVAILABLE,
            "device_protocol": DEVICE_PROTOCOL_AVAILABLE,
            "galaxy_core": GALAXY_CORE_AVAILABLE
        },
        "timestamp": datetime.now().isoformat()
    }
    
    if GALAXY_CORE_AVAILABLE and galaxy_core:
        status = galaxy_core.get_status()
        info["nodes"] = status["nodes"]
        info["devices"] = status["devices"]
    
    return info

# ============================================================================
# 运行时节点注册表（内存结构，供 launcher 注册并供前端查询）
# ============================================================================

_runtime_nodes: Dict[str, Dict[str, Any]] = {}


class RuntimeNodeRegisterRequest(BaseModel):
    node_id: str
    name: str
    port: Optional[int] = None
    status: str = "running"


@app.post("/api/v1/nodes/register")
async def register_runtime_node(request: RuntimeNodeRegisterRequest):
    """launcher 启动节点后调用，注册运行时节点信息"""
    _runtime_nodes[request.node_id] = {
        "node_id": request.node_id,
        "name": request.name,
        "port": request.port,
        "status": request.status,
        "registered_at": datetime.now().isoformat(),
    }
    logger.info("运行时节点已注册: %s (port=%s)", request.node_id, request.port)
    return {"success": True, "node_id": request.node_id}


@app.get("/api/v1/nodes/runtime")
async def list_runtime_nodes():
    """返回运行时节点列表（launcher 注册的节点）"""
    return {"nodes": list(_runtime_nodes.values()), "total": len(_runtime_nodes)}


@app.get("/api/v1/nodes/all")
async def list_all_nodes():
    """统一节点聚合器：合并运行时注册表 + node_registry.json，未启动节点显示 inactive"""
    registry_path = os.path.join(PROJECT_ROOT, "config", "node_registry.json")
    registry_nodes: Dict[str, Dict[str, Any]] = {}
    if os.path.exists(registry_path):
        try:
            with open(registry_path, "r", encoding="utf-8") as f:
                registry = json.load(f)
            for node_key, node_info in registry.get("nodes", {}).items():
                nid = node_info.get("id", "")
                if nid:
                    registry_nodes[nid] = {
                        "node_id": nid,
                        "name": node_info.get("name", node_key),
                        "node_key": node_key,
                        "path": node_info.get("path", ""),
                        "status": "inactive",
                        "source": "registry",
                        "has_main": node_info.get("has_main", False),
                        "registry_status": node_info.get("status", "unknown"),
                    }
        except Exception as e:
            logger.warning("读取 node_registry.json 失败: %s", e)

    # 合并运行时节点（优先覆盖）
    merged: Dict[str, Dict[str, Any]] = dict(registry_nodes)
    for nid, rt_info in _runtime_nodes.items():
        if nid in merged:
            merged[nid].update({
                "status": rt_info.get("status", "running"),
                "port": rt_info.get("port"),
                "registered_at": rt_info.get("registered_at"),
                "source": "runtime",
            })
        else:
            merged[nid] = dict(rt_info)
            merged[nid]["source"] = "runtime"

    result = sorted(merged.values(), key=lambda x: x.get("node_id", ""))
    logger.debug("节点聚合器: 共 %d 个节点（运行时 %d + 注册表）", len(result), len(_runtime_nodes))
    return {"nodes": result, "total": len(result)}


# ============================================================================
# 节点 API - 使用已有协议
# ============================================================================

@app.get("/api/v1/nodes")
async def list_nodes():
    """列出所有节点"""
    if GALAXY_CORE_AVAILABLE and galaxy_core:
        return {"nodes": galaxy_core.nodes, "total": len(galaxy_core.nodes)}
    return {"nodes": {}, "total": 0}

@app.post("/api/v1/nodes/{node_id}/call")
async def call_node(node_id: str, request: dict):
    """调用节点 - 使用已有协议"""
    if GALAXY_CORE_AVAILABLE and galaxy_core:
        action = request.get("action", "")
        params = request.get("params", {})
        result = await galaxy_core.call_node(node_id, action, params)
        return result
    return {"success": False, "error": "Galaxy core not available"}

@app.post("/api/v1/mcp/call")
async def mcp_call(request: dict):
    """
    MCP 调用 - 统一入口
    
    通过 Node_04_Router 路由到具体节点
    """
    node_id = request.get("node_id", "04")
    tool = request.get("tool", "")
    params = request.get("params", {})
    
    if GALAXY_CORE_AVAILABLE and galaxy_core:
        result = await galaxy_core.call_node(node_id, tool, params)
        return result
    
    return {"success": False, "error": "Galaxy core not available"}

# ============================================================================
# 设备 API - 使用 device_protocol
# ============================================================================

@app.get("/api/v1/devices")
async def list_devices():
    """列出所有设备"""
    if GALAXY_CORE_AVAILABLE and galaxy_core:
        return {"devices": list(galaxy_core.devices.values())}
    return {"devices": []}

@app.post("/api/v1/devices/register")
async def register_device(request: dict):
    """注册设备 - 使用 device_protocol"""
    if GALAXY_CORE_AVAILABLE and galaxy_core:
        device_id = request.get("device_id", "")
        device_type = request.get("device_type", "android")
        name = request.get("device_name", "Device")
        endpoint = request.get("endpoint", "")
        
        result = await galaxy_core.register_device(device_id, device_type, name, endpoint)
        return result
    
    return {"success": False, "error": "Galaxy core not available"}

@app.post("/api/v1/devices/{device_id}/command")
async def send_device_command(device_id: str, request: dict):
    """发送设备命令 - 使用 device_protocol，并记录执行 trace"""
    command = request.get("command", "")
    params = request.get("params", {})
    agent_id = request.get("agent_id")
    task_id = request.get("task_id")

    _t0 = _time_module.monotonic()
    if GALAXY_CORE_AVAILABLE and galaxy_core:
        result = await galaxy_core.send_device_command(device_id, command, params)
    else:
        result = {"success": False, "error": "Galaxy core not available"}

    _duration = round((_time_module.monotonic() - _t0) * 1000, 2)
    _device_trace_store.add(
        device_id=device_id,
        command=command,
        params=params,
        result=result,
        agent_id=agent_id,
        task_id=task_id,
        duration_ms=_duration,
    )
    return result


@app.post("/api/v1/devices/discover-active")
async def discover_active_devices():
    """主动发现在线设备 — 扫描已注册节点和设备"""
    discovered = []

    # 1. 从 galaxy_core 获取已注册设备
    if GALAXY_CORE_AVAILABLE and galaxy_core:
        for dev_id, dev in galaxy_core.devices.items():
            discovered.append({**dev, "source": "registered"})

    # 2. 尝试通过 Node_71 (MultiDeviceCoordination) 发现更多设备
    if GALAXY_CORE_AVAILABLE and galaxy_core:
        try:
            result = await galaxy_core.call_node("71", "discover_devices", {})
            if result.get("success") and result.get("devices"):
                for dev in result["devices"]:
                    if dev.get("device_id") not in [d.get("device_id") for d in discovered]:
                        discovered.append({**dev, "source": "discovered"})
        except Exception as e:
            logger.debug(f"Node_71 discover failed: {e}")

    # 3. 尝试通过 Node_33 (ADB) 发现 Android 设备
    if GALAXY_CORE_AVAILABLE and galaxy_core:
        try:
            result = await galaxy_core.call_node("33", "list_devices", {})
            if result.get("success") and result.get("devices"):
                for dev in result["devices"]:
                    dev_id = dev.get("device_id") or dev.get("serial", "")
                    if dev_id and dev_id not in [d.get("device_id") for d in discovered]:
                        discovered.append({
                            "device_id": dev_id,
                            "device_type": "android",
                            "name": dev.get("model", dev_id),
                            "status": dev.get("status", "online"),
                            "source": "adb",
                        })
        except Exception as e:
            logger.debug(f"Node_33 ADB discover failed: {e}")

    return {"success": True, "devices": discovered, "total": len(discovered)}


@app.get("/api/v1/devices/{device_id}/telemetry")
async def get_device_telemetry(device_id: str):
    """获取设备遥测数据（CPU、内存、电池等）"""
    if not GALAXY_CORE_AVAILABLE or not galaxy_core:
        return {"success": False, "error": "Galaxy core not available"}

    device = galaxy_core.devices.get(device_id)
    if not device:
        return JSONResponse(status_code=404, content={"success": False, "error": f"Device {device_id} not found"})

    # 尝试从设备数字孪生获取最新状态
    if DEVICE_TWIN_AVAILABLE and device_twin_engine:
        twin = device_twin_engine.get_twin_by_device(device_id) if hasattr(device_twin_engine, 'get_twin_by_device') else None
        if twin:
            state = twin.get_state()
            return {"success": True, "device_id": device_id, "telemetry": state, "source": "digital_twin"}

    # 尝试通过 Node_92 (AutoControl) 获取实时遥测
    try:
        result = await galaxy_core.call_node("92", "get_device_info", {"device_id": device_id})
        if result.get("success"):
            return {"success": True, "device_id": device_id, "telemetry": result, "source": "node_92"}
    except Exception as e:
        logger.debug(f"Telemetry via node_92 failed: {e}")

    # 返回基础已知信息
    return {
        "success": True,
        "device_id": device_id,
        "telemetry": {
            "device_type": device.get("device_type", "unknown"),
            "status": device.get("status", "unknown"),
            "registered_at": device.get("registered_at", ""),
        },
        "source": "cached",
    }


@app.post("/api/v1/devices/cross-device")
async def cross_device_action(request: dict):
    """跨设备协同操作（如剪贴板同步、通知推送等）"""
    command = request.get("command", "")
    context = request.get("context", {})

    if not command:
        return JSONResponse(status_code=400, content={"success": False, "error": "command is required"})

    if not GALAXY_CORE_AVAILABLE or not galaxy_core:
        return {"success": False, "error": "Galaxy core not available"}

    # 通过 Node_71 (MultiDeviceCoordination) 执行跨设备操作
    try:
        result = await galaxy_core.call_node("71", command, context)
        return {"success": result.get("success", False), "result": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/v1/devices/transfer")
async def device_file_transfer(request: dict):
    """设备间文件传输"""
    source_device = request.get("source_device", "")
    target_device = request.get("target_device", "")
    file_path = request.get("file_path", "")

    if not source_device or not target_device or not file_path:
        return JSONResponse(status_code=400, content={
            "success": False,
            "error": "source_device, target_device and file_path are required"
        })

    if not GALAXY_CORE_AVAILABLE or not galaxy_core:
        return {"success": False, "error": "Galaxy core not available"}

    # 通过 Node_71 (MultiDeviceCoordination) 执行文件传输
    try:
        result = await galaxy_core.call_node("71", "file_transfer", {
            "source_device": source_device,
            "target_device": target_device,
            "file_path": file_path,
        })
        return {"success": result.get("success", False), "result": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================================
# 事件 API
# ============================================================================

@app.get("/api/v1/events/recent")
async def get_recent_events(limit: int = 50, event_type: str = None):
    """获取最近事件 - 从 EventBus 历史读取"""
    try:
        from integration.event_bus import event_bus, EventType as ET
        et = None
        if event_type:
            try:
                et = ET[event_type]
            except KeyError:
                pass
        events = event_bus.get_event_history(event_type=et, limit=limit)
        return {"success": True, "events": [e.to_dict() for e in events], "total": len(events)}
    except Exception as e:
        return {"success": True, "events": [], "total": 0, "note": str(e)}

# ============================================================================
# Agent API
# ============================================================================

@app.get("/api/v1/agents")
async def list_agents():
    """列出所有 Agent"""
    if AGENT_FACTORY_AVAILABLE and agent_factory:
        return {"agents": [a.to_dict() for a in agent_factory.agents.values()]}
    if GALAXY_CORE_AVAILABLE and galaxy_core:
        agents = galaxy_core.agents if hasattr(galaxy_core, "agents") else {}
        return {"agents": list(agents.values()) if isinstance(agents, dict) else agents}
    return {"agents": []}


@app.get("/api/v1/agents/templates")
async def list_agent_templates():
    """获取可用的 Agent 模板列表"""
    if AGENT_FACTORY_AVAILABLE:
        from core.agent_factory import AGENT_TEMPLATES
        templates = []
        for name, config in AGENT_TEMPLATES.items():
            templates.append({
                "name": name,
                "role": config.role.value,
                "display_name": config.name,
                "description": config.description,
                "capabilities": [{"name": c.name, "description": c.description} for c in config.capabilities],
            })
        return {"templates": templates}
    return {"templates": []}


@app.get("/api/v1/agents/tree")
async def get_agent_tree():
    """获取 Agent 层级树"""
    if AGENT_FACTORY_AVAILABLE and agent_factory:
        tree = {}
        for agent_id, agent in agent_factory.agents.items():
            tree[agent_id] = {
                "name": agent.config.name,
                "role": agent.config.role.value,
                "state": agent.state.value,
                "parent_id": agent.parent_id,
                "children": agent.children_ids,
                "depth": agent.depth,
            }
        return {"tree": tree}
    return {"tree": {}}


@app.post("/api/v1/agents/create")
async def create_agent_from_template(request: dict):
    """从模板创建 Agent"""
    if not AGENT_FACTORY_AVAILABLE or not agent_factory:
        return JSONResponse(status_code=503, content={"error": "Agent factory not available"})
    template_name = request.get("template", "")
    overrides = request.get("overrides", None)
    parent_id = request.get("parent_id", None)
    permissions = request.get("permissions", {})
    try:
        agent = agent_factory.create_from_template(template_name, parent_id=parent_id, overrides=overrides)
        agent.config.permissions = {**DEFAULT_AGENT_PERMISSIONS, **{k: bool(v) for k, v in permissions.items() if k in DEFAULT_AGENT_PERMISSIONS}}
        return {"success": True, "agent": agent.to_dict()}
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/v1/agents/create/dynamic")
async def create_agent_dynamic(request: dict):
    """LLM 动态生成 Agent"""
    if not AGENT_FACTORY_AVAILABLE or not agent_factory:
        return JSONResponse(status_code=503, content={"error": "Agent factory not available"})
    task_description = request.get("task_description", "")
    if not task_description:
        return JSONResponse(status_code=400, content={"error": "task_description is required"})
    permissions = request.get("permissions", {})
    try:
        agent = await agent_factory.create_from_llm(task_description, context=request.get("context"))
        agent.config.permissions = {**DEFAULT_AGENT_PERMISSIONS, **{k: bool(v) for k, v in permissions.items() if k in DEFAULT_AGENT_PERMISSIONS}}
        return {"success": True, "agent": agent.to_dict()}
    except RuntimeError as e:
        return JSONResponse(status_code=503, content={"error": str(e)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/v1/agents/{agent_id}")
async def get_agent_detail(agent_id: str):
    """获取单个 Agent 详情"""
    if AGENT_FACTORY_AVAILABLE and agent_factory:
        agent = agent_factory.agents.get(agent_id)
        if agent:
            return {"agent": agent.to_dict()}
        return JSONResponse(status_code=404, content={"error": f"Agent {agent_id} not found"})
    return JSONResponse(status_code=503, content={"error": "Agent factory not available"})


@app.delete("/api/v1/agents/{agent_id}")
async def delete_agent(agent_id: str):
    """停止并删除 Agent"""
    if AGENT_FACTORY_AVAILABLE and agent_factory:
        agent = agent_factory.agents.get(agent_id)
        if not agent:
            return JSONResponse(status_code=404, content={"error": f"Agent {agent_id} not found"})
        from core.agent_factory import AgentState
        agent.state = AgentState.TERMINATED
        agent_factory.message_bus.unregister(agent_id)
        del agent_factory.agents[agent_id]
        return {"success": True, "message": f"Agent {agent_id} terminated"}
    return JSONResponse(status_code=503, content={"error": "Agent factory not available"})


@app.post("/api/v1/agents/{agent_id}/task")
async def assign_agent_task(agent_id: str, request: dict):
    """给 Agent 分配任务"""
    if AGENT_FACTORY_AVAILABLE and agent_factory:
        agent = agent_factory.agents.get(agent_id)
        if not agent:
            return JSONResponse(status_code=404, content={"error": f"Agent {agent_id} not found"})
        task = request.get("task", {})
        agent.task_queue.append(task)
        from core.agent_factory import AgentState
        if agent.state == AgentState.IDLE:
            agent.state = AgentState.WORKING
        return {"success": True, "queue_length": len(agent.task_queue)}
    return JSONResponse(status_code=503, content={"error": "Agent factory not available"})


# ============================================================================
# Agent Twin & Swarm API (前端直接调用的简化接口)
# ============================================================================

@app.post("/api/v1/agents/twin")
async def create_agent_twin_task(request: dict):
    """
    通过 Twin 策略执行任务 — 创建多个 Agent 孪生体协作完成任务。
    前端发送: { task, strategy, member_count }
    """
    task = request.get("task", "")
    strategy = request.get("strategy", "parallel")
    member_count = request.get("member_count", 3)

    if not task:
        return JSONResponse(status_code=400, content={"error": "task is required"})

    # 优先使用 TeamManager 创建 twin team
    if TEAM_MANAGER_AVAILABLE and team_manager:
        try:
            team = await team_manager.create_team(strategy=strategy, task_hint=task)
            result = await team_manager.execute_team(team.team_id, task)
            return {
                "success": True,
                "team_id": team.team_id,
                "strategy": strategy,
                "result": result.to_dict() if hasattr(result, 'to_dict') else result,
            }
        except Exception as e:
            logger.error(f"Twin team execution failed: {e}")
            return JSONResponse(status_code=500, content={"error": str(e)})

    # 降级: 使用 Agent Twin Manager
    if TWIN_AVAILABLE and twin_manager and AGENT_FACTORY_AVAILABLE and agent_factory:
        try:
            agents = []
            for i in range(min(member_count, 5)):
                agent = await agent_factory.create_from_llm(
                    f"{task} (twin #{i+1})",
                    context={"twin_index": i, "strategy": strategy}
                )
                agents.append(agent.to_dict())
            return {"success": True, "agents": agents, "strategy": strategy}
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})

    return JSONResponse(status_code=503, content={"error": "Team manager and Twin manager not available"})


@app.post("/api/v1/agents/swarm")
async def create_agent_swarm(request: dict):
    """
    创建 Agent 蜂群 — 大量轻量级 Agent 并行执行子任务。
    前端发送: { task, agent_count }
    """
    task = request.get("task", "")
    agent_count = request.get("agent_count", 5)

    if not task:
        return JSONResponse(status_code=400, content={"error": "task is required"})

    if not AGENT_FACTORY_AVAILABLE or not agent_factory:
        return JSONResponse(status_code=503, content={"error": "Agent factory not available"})

    try:
        # 使用 LLM 拆分任务
        subtasks = []
        if LLM_ROUTER_AVAILABLE and llm_router and llm_router.is_available():
            try:
                decompose_resp = await llm_router.chat_json(
                    messages=[{
                        "role": "user",
                        "content": (
                            f"将以下任务拆解为 {agent_count} 个独立的子任务，"
                            f"每个子任务可以被一个 Agent 独立完成。\n"
                            f"任务: {task}\n"
                            f'返回 JSON: {{"subtasks": ["子任务1", "子任务2", ...]}}'
                        ),
                    }],
                    task_type="planning",
                )
                subtasks = decompose_resp.get("subtasks", [])
            except Exception as e:
                logger.debug(f"LLM task decomposition failed: {e}")

        # 如果 LLM 拆分失败，简单复制任务
        if not subtasks:
            subtasks = [f"{task} (part {i+1}/{agent_count})" for i in range(agent_count)]

        # 创建 Agent 并分配子任务
        created_agents = []
        for i, subtask in enumerate(subtasks[:agent_count]):
            try:
                agent = await agent_factory.create_from_llm(subtask, context={"swarm_index": i})
                agent.task_queue.append({"task": subtask, "type": "swarm_subtask"})
                created_agents.append(agent.to_dict())
            except Exception as e:
                logger.warning(f"Swarm agent #{i} creation failed: {e}")

        return {
            "success": True,
            "agents": created_agents,
            "total_created": len(created_agents),
            "subtasks": subtasks[:agent_count],
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# ============================================================================
# Agent Team API
# ============================================================================

@app.post("/api/v1/agents/team/create")
async def create_team(request: dict):
    """创建 Agent Team"""
    if not TEAM_MANAGER_AVAILABLE or not team_manager:
        return JSONResponse(status_code=503, content={"error": "Team manager not available"})
    strategy = request.get("strategy", "parallel")
    task_hint = request.get("task_hint", "")
    try:
        team = await team_manager.create_team(strategy, task_hint)
        return {"success": True, "team": team.to_dict()}
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/v1/agents/teams")
async def list_teams():
    """列出所有 Team"""
    if not TEAM_MANAGER_AVAILABLE or not team_manager:
        return {"teams": []}
    return {"teams": team_manager.list_teams()}


@app.post("/api/v1/agents/team/{team_id}/execute")
async def execute_team(team_id: str, request: dict):
    """执行 Team 任务"""
    if not TEAM_MANAGER_AVAILABLE or not team_manager:
        return JSONResponse(status_code=503, content={"error": "Team manager not available"})
    task = request.get("task", "")
    context = request.get("context", None)
    if not task:
        return JSONResponse(status_code=400, content={"error": "task is required"})
    try:
        result = await team_manager.execute_team(team_id, task, context)
        return {"success": True, "result": result.to_dict()}
    except ValueError as e:
        return JSONResponse(status_code=404, content={"error": str(e)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.delete("/api/v1/agents/team/{team_id}")
async def disband_team(team_id: str):
    """解散 Team"""
    if not TEAM_MANAGER_AVAILABLE or not team_manager:
        return JSONResponse(status_code=503, content={"error": "Team manager not available"})
    success = team_manager.disband_team(team_id)
    if success:
        return {"success": True, "message": f"Team {team_id} disbanded"}
    return JSONResponse(status_code=404, content={"error": f"Team {team_id} not found"})


# ============================================================================
# 孪生模型 API (Agent Twin + Device Twin)
# ============================================================================

# ── Agent 孪生 ──

@app.get("/api/v1/twins")
async def list_twins():
    """列出所有 Agent 孪生模型"""
    if not TWIN_AVAILABLE or not twin_manager:
        return {"twins": [], "available": False}
    return {"twins": twin_manager.list_twins(), "available": True}


@app.post("/api/v1/twins/create")
async def create_twin(request: dict):
    """为 Agent 创建孪生体"""
    if not TWIN_AVAILABLE or not twin_manager:
        return JSONResponse(status_code=503, content={"error": "Twin manager not available"})

    source_id = request.get("source_id", "")
    name = request.get("name", f"twin_{source_id[:8]}")
    coupling_mode = request.get("coupling_mode", "loose")
    snapshot = request.get("snapshot", {})

    if not source_id:
        return JSONResponse(status_code=400, content={"error": "source_id is required"})

    try:
        mode = TwinCouplingMode(coupling_mode)
        twin = await twin_manager.create_twin(source_id, name, mode, snapshot)
        return {
            "success": True,
            "twin_id": twin.twin_id,
            "source_id": twin.source_id,
            "coupling_mode": twin.coupling_mode.value,
            "state": twin.state.value,
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/v1/twins/{twin_id}/couple")
async def couple_twin(twin_id: str, request: dict):
    """耦合孪生体"""
    if not TWIN_AVAILABLE or not twin_manager:
        return JSONResponse(status_code=503, content={"error": "Twin manager not available"})

    mode = request.get("mode", "loose")
    try:
        twin_manager.couple(twin_id, TwinCouplingMode(mode))
        twin = twin_manager.get_twin(twin_id)
        return {
            "success": True,
            "twin_id": twin_id,
            "coupling_mode": twin.coupling_mode.value if twin else mode,
            "state": twin.state.value if twin else "unknown",
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/v1/twins/{twin_id}/decouple")
async def decouple_twin(twin_id: str):
    """解耦孪生体"""
    if not TWIN_AVAILABLE or not twin_manager:
        return JSONResponse(status_code=503, content={"error": "Twin manager not available"})

    twin_manager.decouple(twin_id)
    twin = twin_manager.get_twin(twin_id)
    return {
        "success": True,
        "twin_id": twin_id,
        "coupling_mode": twin.coupling_mode.value if twin else "decoupled",
        "state": twin.state.value if twin else "detached",
    }


@app.get("/api/v1/twins/{twin_id}/predict")
async def predict_twin(twin_id: str, horizon: int = 5):
    """预测孪生体行为"""
    if not TWIN_AVAILABLE or not twin_manager:
        return JSONResponse(status_code=503, content={"error": "Twin manager not available"})

    predictions = await twin_manager.predict_behavior(twin_id, horizon)
    return {"twin_id": twin_id, "predictions": predictions}


@app.post("/api/v1/twins/{twin_id}/simulate")
async def simulate_twin(twin_id: str, request: dict):
    """孪生体场景模拟"""
    if not TWIN_AVAILABLE or not twin_manager:
        return JSONResponse(status_code=503, content={"error": "Twin manager not available"})

    scenario = request.get("scenario", {})
    result = await twin_manager.simulate(twin_id, scenario)
    return {"twin_id": twin_id, "simulation": result}


# ── 设备数字孪生 ──

@app.get("/api/v1/device-twins")
async def list_device_twins():
    """列出设备数字孪生"""
    if not DEVICE_TWIN_AVAILABLE or not device_twin_engine:
        return {"twins": {}, "available": False}
    return {"twins": device_twin_engine.get_global_state(), "available": True}


@app.post("/api/v1/device-twins/create")
async def create_device_twin(request: dict):
    """创建设备数字孪生"""
    if not DEVICE_TWIN_AVAILABLE or not device_twin_engine:
        return JSONResponse(status_code=503, content={"error": "Device twin engine not available"})

    device_id = request.get("device_id", "")
    device_type = request.get("device_type", "generic")
    initial_state = request.get("initial_state", {})
    drift_threshold = request.get("drift_threshold", 0.1)

    if not device_id:
        return JSONResponse(status_code=400, content={"error": "device_id is required"})

    twin = device_twin_engine.create_twin(device_id, device_type, initial_state, drift_threshold)
    return {
        "success": True,
        "twin_id": twin.twin_id,
        "device_id": twin.device_id,
        "coupling_mode": twin.coupling_mode.value,
        "status": twin.status.value,
    }


@app.get("/api/v1/device-twins/{twin_id}/state")
async def get_device_twin_state(twin_id: str):
    """获取设备孪生状态（含漂移检测）"""
    if not DEVICE_TWIN_AVAILABLE or not device_twin_engine:
        return JSONResponse(status_code=503, content={"error": "Device twin engine not available"})

    twin = device_twin_engine.get_twin(twin_id)
    if not twin:
        return JSONResponse(status_code=404, content={"error": f"Device twin {twin_id} not found"})

    state = twin.get_state()
    # 附加漂移报告
    drift = twin.detect_drift()
    if drift:
        state["drift"] = {
            "max_drift": drift.max_drift,
            "severity": drift.severity,
            "drifted_properties": drift.drifted_properties,
        }
    return state


@app.post("/api/v1/device-twins/{twin_id}/simulate")
async def simulate_device_twin(twin_id: str, request: dict):
    """设备孪生操作模拟"""
    if not DEVICE_TWIN_AVAILABLE or not device_twin_engine:
        return JSONResponse(status_code=503, content={"error": "Device twin engine not available"})

    twin = device_twin_engine.get_twin(twin_id)
    if not twin:
        return JSONResponse(status_code=404, content={"error": f"Device twin {twin_id} not found"})

    action = request.get("action", "")
    params = request.get("params", {})
    if not action:
        return JSONResponse(status_code=400, content={"error": "action is required"})

    result = await twin.simulate_action(action, params)
    return {
        "twin_id": twin_id,
        "action": action,
        "predicted_state": result.predicted_state,
        "success_probability": result.success_probability,
        "risks": result.risks,
        "side_effects": result.side_effects,
    }


# ============================================================================
# 节点 API 配置
# ============================================================================

# 节点 → 所需 API Key 映射
NODE_API_REQUIREMENTS = {
    "01": {"name": "OneAPI 聚合器", "category": "llm", "keys": [
        {"env_var": "OPENROUTER_API_KEY", "label": "OpenRouter"},
        {"env_var": "ZHIPU_API_KEY", "label": "智谱"},
        {"env_var": "TOGETHER_API_KEY", "label": "Together"},
        {"env_var": "PERPLEXITY_API_KEY", "label": "Perplexity"},
        {"env_var": "XAI_API_KEY", "label": "xAI"},
    ]},
    "11": {"name": "GitHub", "category": "code", "keys": [
        {"env_var": "GITHUB_TOKEN", "label": "GitHub Token"},
    ]},
    "15": {"name": "OCR", "category": "vision", "keys": [
        {"env_var": "DEEPSEEK_OCR2_API_KEY", "label": "DeepSeek OCR"},
    ]},
    "18": {"name": "DeepL 翻译", "category": "translation", "keys": [
        {"env_var": "DEEPL_API_KEY", "label": "DeepL"},
    ]},
    "20": {"name": "Qdrant 向量数据库", "category": "data", "keys": [
        {"env_var": "QDRANT_URL", "label": "Qdrant URL"},
        {"env_var": "QDRANT_API_KEY", "label": "Qdrant Key"},
    ]},
    "21": {"name": "Notion", "category": "data", "keys": [
        {"env_var": "NOTION_API_KEY", "label": "Notion"},
    ]},
    "22": {"name": "Brave Search", "category": "search", "keys": [
        {"env_var": "BRAVE_API_KEY", "label": "Brave Search"},
    ]},
    "24": {"name": "天气", "category": "search", "keys": [
        {"env_var": "OPENWEATHER_API_KEY", "label": "OpenWeather"},
    ]},
    "49": {"name": "OctoPrint 3D打印", "category": "hardware", "keys": [
        {"env_var": "OCTOPRINT_URL", "label": "OctoPrint URL"},
        {"env_var": "OCTOPRINT_API_KEY", "label": "OctoPrint Key"},
    ]},
    "79": {"name": "本地 LLM", "category": "local_llm", "keys": [
        {"env_var": "OLLAMA_URL", "label": "Ollama URL"},
        {"env_var": "VLLM_API_BASE", "label": "vLLM URL"},
        {"env_var": "VLLM_API_KEY", "label": "vLLM Key"},
    ]},
    "90": {"name": "多模态视觉", "category": "vision", "keys": [
        {"env_var": "GEMINI_API_KEY", "label": "Gemini"},
    ]},
    "106": {"name": "GitHub Flow", "category": "code", "keys": [
        {"env_var": "GITHUB_TOKEN", "label": "GitHub Token"},
        {"env_var": "GEMINI_API_KEY", "label": "Gemini"},
    ]},
    "128": {"name": "媒体生成", "category": "media", "keys": [
        {"env_var": "PIXVERSE_API_KEY", "label": "PixVerse"},
    ]},
}


@app.get("/api/v1/config/node-apis")
async def get_node_apis():
    """获取所有节点的 API 配置需求和当前状态"""
    node_apis = []
    for node_id, info in NODE_API_REQUIREMENTS.items():
        keys = []
        for k in info["keys"]:
            value = os.environ.get(k["env_var"], "")
            # 也检查 CredentialVault
            if not value:
                try:
                    from core.credential_vault import get_vault
                    value = get_vault().get_credential(k["env_var"], actor="dashboard") or ""
                except Exception:
                    pass
            keys.append({
                "env_var": k["env_var"],
                "label": k["label"],
                "configured": bool(value),
                "masked": value[:6] + "..." if len(value) > 6 else "",
            })
        node_apis.append({
            "node_id": node_id,
            "name": info["name"],
            "category": info["category"],
            "keys": keys,
            "all_configured": all(k["configured"] for k in keys),
        })
    return {"node_apis": node_apis}


@app.get("/api/v1/config/node-apis/auto")
async def get_node_apis_auto():
    """自动扫描 nodes/**/README.md 提取环境变量配置需求，与静态表合并返回"""
    import re as _re

    _MAX_README_SECTION_LENGTH = 2000   # 每段 README 扫描字符数上限
    _MIN_ENV_VAR_LENGTH = 4             # 有效环境变量名最短字符数
    # - `ENV_VAR` — 描述
    # - ENV_VAR=xxx
    # - | ENV_VAR | 描述 | (Markdown 表格)
    _ENV_VAR_PATTERN = _re.compile(
        r'(?:^|\|)\s*`?([A-Z][A-Z0-9_]{2,})`?\s*(?:[=:｜|]|\s).*?(?:$|\|)',
        _re.MULTILINE,
    )
    # 过滤掉非 key 类的常见词
    _EXCLUDE = {"TRUE", "FALSE", "NULL", "NONE", "HTTP", "HTTPS", "API", "URL", "KEY"}

    nodes_dir = os.path.join(PROJECT_ROOT, "nodes")
    auto_result: Dict[str, Any] = {}

    # 扫描所有节点目录
    if os.path.isdir(nodes_dir):
        for entry in sorted(os.listdir(nodes_dir)):
            node_dir = os.path.join(nodes_dir, entry)
            if not os.path.isdir(node_dir) or not entry.startswith("Node_"):
                continue
            readme_path = os.path.join(node_dir, "README.md")
            if not os.path.exists(readme_path):
                continue
            try:
                with open(readme_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except Exception:
                continue

            # 仅扫描包含"环境变量"/"API"/"配置"关键词的段落
            env_section = ""
            for section_header in ("环境变量", "API", "配置", "Configuration", "Environment"):
                idx = content.find(section_header)
                if idx != -1:
                    env_section += content[idx: idx + _MAX_README_SECTION_LENGTH]

            if not env_section:
                env_section = content  # 全文扫描作为回退

            found_vars = []
            for m in _ENV_VAR_PATTERN.finditer(env_section):
                var = m.group(1).strip()
                if var and var not in _EXCLUDE and len(var) >= _MIN_ENV_VAR_LENGTH:
                    found_vars.append({"env_var": var, "label": var})

            # 去重
            seen = set()
            unique_vars = []
            for v in found_vars:
                if v["env_var"] not in seen:
                    seen.add(v["env_var"])
                    unique_vars.append(v)

            if unique_vars:
                # 从节点目录名解析 node_id
                parts = entry.split("_")
                node_id = parts[1] if len(parts) >= 2 else entry
                node_name = "_".join(parts[2:]) if len(parts) >= 3 else entry
                auto_result[node_id] = {
                    "node_id": node_id,
                    "name": node_name,
                    "node_key": entry,
                    "keys": unique_vars,
                    "source": "auto_scan",
                }

    # 合并静态表（静态优先）
    for node_id, info in NODE_API_REQUIREMENTS.items():
        if node_id not in auto_result:
            auto_result[node_id] = {
                "node_id": node_id,
                "name": info["name"],
                "node_key": None,
                "keys": info["keys"],
                "source": "static",
            }
        else:
            # 追加静态表中存在但 auto_scan 未找到的 key
            existing_vars = {k["env_var"] for k in auto_result[node_id]["keys"]}
            for k in info["keys"]:
                if k["env_var"] not in existing_vars:
                    auto_result[node_id]["keys"].append(k)

    # 检查当前环境变量配置状态
    result_list = []
    for node_id, info in sorted(auto_result.items()):
        keys_with_status = []
        for k in info["keys"]:
            value = os.environ.get(k["env_var"], "")
            keys_with_status.append({
                "env_var": k["env_var"],
                "label": k.get("label", k["env_var"]),
                "configured": bool(value),
                "masked": value[:6] + "..." if len(value) > 6 else "",
            })
        result_list.append({
            "node_id": node_id,
            "name": info["name"],
            "node_key": info.get("node_key"),
            "source": info["source"],
            "keys": keys_with_status,
            "all_configured": all(k["configured"] for k in keys_with_status),
        })

    logger.info("节点 API 自动扫描完成: %d 个节点", len(result_list))
    return {"node_apis": result_list, "total": len(result_list), "source": "auto"}


@app.post("/api/v1/config/node-api-key")
async def set_node_api_key(request: dict):
    """设置节点 API Key（写入环境变量 + CredentialVault + .env）"""
    env_var = request.get("env_var", "")
    value = request.get("value", "")
    if not env_var or not value:
        return JSONResponse(status_code=400, content={"error": "env_var and value required"})

    # 1. 写入环境变量
    os.environ[env_var] = value

    # 2. 写入 CredentialVault
    try:
        from core.credential_vault import get_vault
        get_vault().set_credential(env_var, value, actor="dashboard")
    except Exception as e:
        logger.debug(f"CredentialVault write failed: {e}")

    # 3. 持久化到 .env
    env_path = os.path.join(PROJECT_ROOT, ".env")
    try:
        lines = []
        replaced = False
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith(f"{env_var}="):
                        lines.append(f"{env_var}={value}\n")
                        replaced = True
                    else:
                        lines.append(line)
        if not replaced:
            lines.append(f"{env_var}={value}\n")
        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
    except Exception as e:
        logger.warning(f".env write failed: {e}")

    return {"success": True, "env_var": env_var}


# ============================================================================
# LLM 提供商 API
# ============================================================================

@app.get("/api/v1/llm/providers")
async def list_llm_providers():
    """列出可用的 LLM 提供商。

    Key lookup priority:
    1. UnifiedConfigManager (merges .env + config.json + unified_ports.yaml)
    2. os.environ (covers keys already exported to the environment)
    """
    # Initialise UnifiedConfigManager once for this request
    _unified_mgr = None
    try:
        from core.unified_config import UnifiedConfigManager
        _unified_mgr = UnifiedConfigManager()
    except Exception as _exc:
        logger.debug("UnifiedConfigManager 不可用，降级为 os.environ: %s", _exc)

    def _resolve_key(unified_key: str, env_key: str) -> str:
        if _unified_mgr is not None:
            val = _unified_mgr.get(unified_key) or _unified_mgr.get(unified_key.upper())
            if val:
                return str(val)
        return os.environ.get(env_key, "")

    providers = []
    llm_env_map = [
        ("openai",     "openai_api_key",     "OPENAI_API_KEY",     "gpt-4o",                      8, 9),
        ("anthropic",  "anthropic_api_key",   "ANTHROPIC_API_KEY",  "claude-3-5-sonnet-20241022",   7, 10),
        ("deepseek",   "deepseek_api_key",    "DEEPSEEK_API_KEY",   "deepseek-chat",               9, 8),
        ("zhipu",      "zhipu_api_key",       "ZHIPU_API_KEY",      "glm-4",                       8, 8),
        ("groq",       "groq_api_key",        "GROQ_API_KEY",       "llama-3.3-70b-versatile",     10, 8),
        ("gemini",     "gemini_api_key",      "GEMINI_API_KEY",     "gemini-1.5-pro",              8, 9),
        ("openrouter", "openrouter_api_key",  "OPENROUTER_API_KEY", "openrouter/auto",             7, 8),
        ("xai",        "xai_api_key",         "XAI_API_KEY",        "grok-beta",                   8, 8),
    ]
    for provider, unified_key, env_key, model, speed, quality in llm_env_map:
        api_key = _resolve_key(unified_key, env_key)
        providers.append({
            "provider": provider,
            "model": model,
            "speed_score": speed,
            "quality_score": quality,
            "available": bool(api_key),
        })
    logger.debug(
        "LLM providers status: %s",
        {p["provider"]: p["available"] for p in providers},
    )
    return {"providers": providers}

# ============================================================================
# 统一聊天 API (/api/v1/chat)
# ============================================================================

@app.post("/api/v1/chat")
async def chat_unified(request: dict):
    """统一聊天入口 - 与 /api/v1/dashboard/chat 功能相同"""
    return await dashboard_chat(request)

# ============================================================================
# 并行执行 API
# ============================================================================

@app.post("/api/v1/execute/parallel")
async def execute_parallel(request: dict):
    """并行执行多设备命令，并记录执行 traces"""
    commands = request.get("commands", [])
    task_id = request.get("task_id") or f"orch_{int(_time_module.time() * 1000)}"
    description = request.get("description", "Parallel execution")
    results = {}

    device_assignments = [
        {"device_id": cmd.get("device_id", ""), "action": cmd.get("action", "")}
        for cmd in commands
    ]
    _orchestration_store.record(
        task_id=task_id,
        description=description,
        device_assignments=device_assignments,
        status="running",
    )

    if GALAXY_CORE_AVAILABLE and galaxy_core:
        tasks = []
        for cmd in commands:
            device_id = cmd.get("device_id", "")
            action = cmd.get("action", "")
            params = cmd.get("params", {})
            tasks.append(galaxy_core.send_device_command(device_id, action, params))
        if tasks:
            task_results = await asyncio.gather(*tasks, return_exceptions=True)
            for cmd, result in zip(commands, task_results):
                device_id = cmd.get("device_id", "")
                resolved = result if not isinstance(result, Exception) else {"success": False, "error": str(result)}
                results[device_id] = resolved
                _device_trace_store.add(
                    device_id=device_id,
                    command=cmd.get("action", ""),
                    params=cmd.get("params", {}),
                    result=resolved,
                    task_id=task_id,
                )
        _orchestration_store.update(task_id, status="completed", results=results)
        return {"success": True, "task_id": task_id, "results": results}

    # 无 galaxy_core 时返回空结果
    for cmd in commands:
        device_id = cmd.get("device_id", "")
        err_result = {"success": False, "error": "Galaxy core not available"}
        results[device_id] = err_result
        _device_trace_store.add(
            device_id=device_id,
            command=cmd.get("action", ""),
            params=cmd.get("params", {}),
            result=err_result,
            task_id=task_id,
        )
    _orchestration_store.update(task_id, status="failed", results=results)
    return {"success": False, "task_id": task_id, "results": results}

# ============================================================================
# P2: Device Execution Trace API
# ============================================================================

@app.get("/api/v1/devices/traces")
async def get_all_device_traces(limit: int = 100):
    """获取所有设备执行 trace 记录（最多 limit 条，默认 100）"""
    traces = _device_trace_store.all()
    return {"traces": traces[-limit:], "total": len(traces)}


@app.get("/api/v1/devices/{device_id}/traces")
async def get_device_traces(device_id: str, limit: int = 50):
    """获取指定设备的执行 trace 记录"""
    traces = _device_trace_store.for_device(device_id)
    return {"device_id": device_id, "traces": traces[-limit:], "total": len(traces)}


# ============================================================================
# P2: Agent–Device Collaboration Mapping API
# ============================================================================

@app.get("/api/v1/agent-device/mapping")
async def get_agent_device_mapping():
    """Agent–Device 协同映射：返回所有 Agent 当前控制的设备及任务状态"""
    # Pull live agent list from factory when available
    live_agents: List[dict] = []
    if AGENT_FACTORY_AVAILABLE and agent_factory:
        try:
            for aid, agent in agent_factory.agents.items():
                device_id = getattr(agent, "device_id", None) or getattr(agent, "target_device_id", None) or ""
                task = getattr(agent, "task", "")
                status = getattr(agent, "state", "unknown")
                if hasattr(status, "value"):
                    status = status.value
                if device_id:
                    _agent_device_registry.assign(aid, device_id, task or "", str(status))
                live_agents.append({
                    "agent_id": aid,
                    "name": getattr(agent, "name", aid),
                    "device_id": device_id,
                    "task": task,
                    "status": str(status),
                })
        except Exception as exc:
            logger.debug("agent-device mapping live fetch failed: %s", exc)

    mappings = _agent_device_registry.all()
    # Merge live_agents into mappings: add any agent not already tracked
    tracked_ids = {m["agent_id"] for m in mappings}
    for la in live_agents:
        if la["agent_id"] not in tracked_ids:
            mappings.append({
                "agent_id": la["agent_id"],
                "device_id": la["device_id"],
                "task": la["task"],
                "status": la["status"],
                "started_at": None,
                "updated_at": None,
            })

    # Enrich with recent trace summary per (agent_id, device_id)
    all_traces = _device_trace_store.all()
    trace_index: Dict[str, dict] = {}
    for t in all_traces:
        if t.get("agent_id"):
            key = f"{t['agent_id']}_{t['device_id']}"
            trace_index[key] = {
                "last_command": t["command"],
                "last_result_success": t["success"],
                "last_error": t["error"],
                "last_trace_ts": t["timestamp"],
            }
    for m in mappings:
        key = f"{m['agent_id']}_{m['device_id']}"
        m["trace_summary"] = trace_index.get(key)

    return {
        "mappings": mappings,
        "total": len(mappings),
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


@app.post("/api/v1/agent-device/assign")
async def assign_agent_to_device(request: dict):
    """记录 Agent 到设备的分配关系（供其他组件上报）"""
    agent_id = request.get("agent_id", "")
    device_id = request.get("device_id", "")
    task = request.get("task", "")
    status = request.get("status", "running")
    if not agent_id or not device_id:
        raise HTTPException(status_code=400, detail="agent_id and device_id are required")
    entry = _agent_device_registry.assign(agent_id, device_id, task, status)
    return {"success": True, "assignment": entry}


@app.patch("/api/v1/agent-device/{agent_id}/status")
async def update_agent_device_status(agent_id: str, request: dict):
    """更新 Agent 的任务状态"""
    status = request.get("status", "")
    if not status:
        raise HTTPException(status_code=400, detail="status is required")
    _agent_device_registry.update_status(agent_id, status)
    return {"success": True}


# ============================================================================
# P2: Multi-Device Orchestration API
# ============================================================================

@app.get("/api/v1/orchestration/tasks")
async def get_orchestration_tasks(limit: int = 50):
    """获取多设备任务编排记录（最近 limit 条）"""
    tasks = _orchestration_store.recent(limit)
    # For each task, attach individual device traces
    trace_by_task: Dict[str, List[dict]] = {}
    for t in _device_trace_store.all():
        tid = t.get("task_id")
        if tid:
            trace_by_task.setdefault(tid, []).append(t)
    for task in tasks:
        task["device_traces"] = trace_by_task.get(task["task_id"], [])
    return {
        "tasks": tasks,
        "total": len(tasks),
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


@app.post("/api/v1/orchestration/tasks")
async def create_orchestration_task(request: dict):
    """手动记录一个多设备任务编排记录"""
    task_id = request.get("task_id") or f"orch_{_uuid_module.uuid4().hex[:8]}"
    description = request.get("description", "")
    device_assignments = request.get("device_assignments", [])
    status = request.get("status", "running")
    if not description:
        raise HTTPException(status_code=400, detail="description is required")
    entry = _orchestration_store.record(
        task_id=task_id,
        description=description,
        device_assignments=device_assignments,
        status=status,
    )
    return {"success": True, "task": entry}


@app.patch("/api/v1/orchestration/tasks/{task_id}")
async def update_orchestration_task(task_id: str, request: dict):
    """更新任务状态或归并结果"""
    status = request.get("status")
    results = request.get("results")
    _orchestration_store.update(task_id, status=status, results=results)
    return {"success": True}

# ============================================================================
# 自主能力 API
# ============================================================================

@app.post("/api/v1/learn")
async def autonomous_learn(request: dict):
    """自主学习"""
    if GALAXY_CORE_AVAILABLE and galaxy_core:
        result = await galaxy_core.autonomous_learn(request)
        return result
    return {"success": False, "error": "Galaxy core not available"}

@app.post("/api/v1/think")
async def autonomous_think(request: dict):
    """自主思考"""
    if GALAXY_CORE_AVAILABLE and galaxy_core:
        goal = request.get("goal", "")
        context = request.get("context", {})
        result = await galaxy_core.autonomous_think(goal, context)
        return result
    return {"success": False, "error": "Galaxy core not available"}

@app.post("/api/v1/code")
async def autonomous_code(request: dict):
    """自主编程"""
    if GALAXY_CORE_AVAILABLE and galaxy_core:
        task = request.get("task", "")
        files = request.get("files", [])
        result = await galaxy_core.autonomous_code(task, files)
        return result
    return {"success": False, "error": "Galaxy core not available"}

@app.post("/api/v1/knowledge/query")
async def query_knowledge(request: dict):
    """查询知识库"""
    if GALAXY_CORE_AVAILABLE and galaxy_core:
        query = request.get("query", "")
        top_k = request.get("top_k", 5)
        result = await galaxy_core.query_knowledge(query, top_k)
        return result
    return {"success": False, "error": "Galaxy core not available"}

# ============================================================================
# 智能对话
# ============================================================================

def _build_unified_response(
    success: bool,
    response: str,
    intent: str = "chat",
    confidence: float = 0.0,
    suggestions: Optional[List[str]] = None,
    data: Optional[Dict] = None,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    """构建统一的 API 响应格式 (UnifiedChatResponse)"""
    return {
        "success": success,
        "response": response,
        "intent": intent,
        "confidence": confidence,
        "suggestions": suggestions or [],
        "data": data or {},
        "error": error,
        "timestamp": datetime.now().isoformat(),
    }


async def get_parsed_intent_modern(message: str, session_id: str = "default"):
    """
    使用现代 IntentParser 解析意图。

    优先使用 core/ai_intent.IntentParser（规则引擎 + LLM），
    如果不可用则回退到旧的 parse_intent()。
    """
    if MODERN_INTENT_AVAILABLE:
        try:
            parser = get_intent_parser()
            memory = get_conversation_memory()
            context = {"history": await memory.get_context(session_id, max_turns=5)}
            parsed = await parser.parse(message, context=context)
            return {
                "type": parsed.intent,
                "action": parsed.command,
                "params": parsed.params,
                "confidence": parsed.confidence,
                "suggestions": parsed.suggestions,
                "targets": parsed.targets,
                "modern": True,
            }
        except Exception as e:
            logger.warning(f"现代意图解析器失败，回退到旧版: {e}")
    # 回退到旧版
    result = parse_intent(message)
    result["confidence"] = 0.3
    result["suggestions"] = []
    result["modern"] = False
    return result


@app.post("/api/v1/dashboard/chat")
async def dashboard_chat(request: dict):
    """
    Dashboard 对话入口 (路由: /api/v1/dashboard/chat)

    注意: 主对话端点 /api/v1/chat 在 core/api_routes.py 中定义。
    此端点是 Dashboard 专用的简化版本，转发到 core 的实现或本地处理。
    """
    message = request.get("message", "")
    device_id = request.get("device_id", "")
    context = request.get("context", [])
    session_id = request.get("session_id", "") or device_id or "default"
    user_id = request.get("user_id", "default")

    logger.info(f"Dashboard Chat: {message[:50]}...")

    # === 意图解析 (所有路径都需要) ===
    intent = await get_parsed_intent_modern(message, session_id)
    intent_type = intent["type"]
    confidence = intent.get("confidence", 0.3)
    suggestions = intent.get("suggestions", [])

    # === 集成对话记忆: 记录用户消息 ===
    memory = None
    if MODERN_INTENT_AVAILABLE:
        try:
            memory = get_conversation_memory()
            await memory.add_turn(session_id, "user", message)
        except Exception as e:
            logger.warning(f"记录用户消息失败: {e}")

    if GALAXY_CORE_AVAILABLE and galaxy_core:
        response_text = ""
        exec_success = False
        result_data = {}

    def _make_response(response_text: str, success: bool = True, mode: str = "chat",
                       extra_data: Dict = None, error: str = "",
                       routing: Dict = None, agent_steps: List = None) -> JSONResponse:
        resp = UnifiedChatResponse(
            success=success,
            response=response_text,
            intent=intent_type,
            confidence=confidence,
            suggestions=suggestions,
            data=extra_data or {},
            error=error,
            session_id=session_id,
        )
        # 增强响应：添加 reply 别名 + routing + agent_steps（Windows 客户端 UI 需要）
        resp_dict = resp.to_json_response()
        resp_dict["reply"] = response_text
        if routing:
            resp_dict["routing"] = routing
        if agent_steps:
            resp_dict["agent_steps"] = agent_steps
        return JSONResponse(resp_dict)

    async def _save_assistant_reply(reply_text: str):
        if memory:
            try:
                await memory.add_turn(session_id, "assistant", reply_text)
            except Exception as e:
                logger.debug(f"Failed to save assistant reply to memory: {e}")

    if GALAXY_CORE_AVAILABLE and galaxy_core:
        try:
            if intent_type == "device_control":
                result = await galaxy_core.send_device_command(
                    device_id or "default",
                    intent.get("action", ""),
                    intent.get("params", {}),
                )
                reply = f"已执行: {intent.get('action', '')}"
                await _save_assistant_reply(reply)
                return _make_response(reply, mode="agent_react",
                                      extra_data={"executed": result.get("success", False)})

            elif intent_type == "learning":
                await galaxy_core.autonomous_learn(intent.get("params", {}))
                reply = "已学习"
                await _save_assistant_reply(reply)
                return _make_response(reply, mode="agent_react")

            elif intent_type == "thinking":
                await galaxy_core.autonomous_think(intent.get("params", {}).get("goal", message))
                reply = "思考完成"
                await _save_assistant_reply(reply)
                return _make_response(reply, mode="agent_react")

            elif intent_type == "coding":
                await galaxy_core.autonomous_code(intent.get("params", {}).get("task", message))
                reply = "代码生成完成"
                await _save_assistant_reply(reply)
                return _make_response(reply, mode="agent_react")

            elif intent_type == "knowledge":
                result = await galaxy_core.query_knowledge(message)
                reply = "知识检索完成"
                await _save_assistant_reply(reply)
                return _make_response(reply, mode="agent_react", extra_data=result)

            else:
                # 默认通过 Node_50_Transformer 处理
                result = await galaxy_core.call_node("50", "chat", {"message": message})
                reply = result.get("response", "处理完成")
                await _save_assistant_reply(reply)
                return _make_response(reply)
        except Exception as e:
            logger.error(f"Galaxy core dispatch failed: {e}")
            # 降级到 LLM
            pass

    # ── Auto-Agent 创建路径 ────────────────────────────────────────────────────
    # 使用 IntentRouter 判定意图；若为 task_execute / hybrid，
    # 则通过 ExecutionPlanner 自动选择模板并创建 Agent 执行任务。
    if AGENT_FACTORY_AVAILABLE and agent_factory:
        try:
            from core.agent.intent_router import IntentRouter
            from core.agent.execution_planner import ExecutionPlanner, ExecutionPlan

            _router = IntentRouter(llm_router=llm_router if LLM_ROUTER_AVAILABLE else None)
            # rules-only 快速分类（不调用 LLM，保持低延迟）
            _intent_result = await _router.route(message, use_llm=False)

            if _intent_result.is_execution():
                logger.info(
                    "Auto-Agent 路径: intent=%s confidence=%.2f task_hint=%s",
                    _intent_result.mode,
                    _intent_result.confidence,
                    _intent_result.task_hint,
                )
                planner = ExecutionPlanner(llm_router=llm_router if LLM_ROUTER_AVAILABLE else None)
                # 将已有对话历史传入计划
                # Keep only dict items - expected structure: {role: str, content: str}
                _ctx = [m for m in (context or []) if isinstance(m, dict)]
                _plan = ExecutionPlan(
                    message=message,
                    intent=_intent_result,
                    session_id=session_id,
                    context=_ctx,
                )
                exec_result = await planner.execute(_plan)

                agent_steps_data = [s.model_dump() for s in exec_result.agent_steps]
                extra: Dict[str, Any] = {"task_result": exec_result.task_result or {}}
                if exec_result.auto_agent_id:
                    extra["auto_agent_id"] = exec_result.auto_agent_id
                if exec_result.auto_agent_template:
                    extra["auto_agent_template"] = exec_result.auto_agent_template
                # Expose new dynamic execution metadata (optional fields)
                if exec_result.chosen_strategy:
                    extra["chosen_strategy"] = exec_result.chosen_strategy
                if exec_result.chosen_providers:
                    extra["chosen_providers"] = exec_result.chosen_providers
                if exec_result.twin_id:
                    extra["twin_id"] = exec_result.twin_id
                if exec_result.twin_coupling:
                    extra["twin_coupling"] = exec_result.twin_coupling

                reply = exec_result.reply or "任务已完成"
                await _save_assistant_reply(reply)
                return _make_response(
                    reply,
                    success=exec_result.success,
                    mode=exec_result.mode or "task_execute",
                    extra_data=extra,
                    agent_steps=agent_steps_data,
                    error=exec_result.error if not exec_result.success else "",
                )
        except Exception as _ae:
            logger.warning("Auto-Agent 执行失败，降级到 LLM: %s", _ae)

    # 优先使用 MultiLLMRouter（智能路由 + 故障转移 + 断路器）
    if LLM_ROUTER_AVAILABLE and llm_router and llm_router.is_available():
        try:
            # 构建带历史上下文的消息列表
            llm_messages = []
            if MODERN_INTENT_AVAILABLE:
                try:
                    mem = get_conversation_memory()
                    history = await mem.get_context(session_id, max_turns=5)
                    if isinstance(history, list):
                        llm_messages.extend(history)
                except Exception:
                    pass
            llm_messages.append({"role": "user", "content": message})

            # 使用意图分类决定任务类型 hint
            task_hint = None
            if intent_type == "coding":
                task_hint = "coding"
            elif intent_type == "thinking":
                task_hint = "reasoning"
            elif intent_type == "learning":
                task_hint = "analysis"

            llm_resp = await llm_router.chat(
                messages=llm_messages,
                task_type=task_hint,
                auto_failover=True,
            )
            reply = llm_resp.content
            routing_info = {
                "provider": llm_resp.provider,
                "model": llm_resp.model,
                "latency_ms": round(llm_resp.latency_ms, 1),
                "input_tokens": llm_resp.input_tokens,
                "output_tokens": llm_resp.output_tokens,
            }
            # 记录助手回复
            if MODERN_INTENT_AVAILABLE:
                try:
                    mem = get_conversation_memory()
                    await mem.add_turn(session_id, "assistant", reply)
                except Exception:
                    pass
            return JSONResponse(_build_unified_response(
                success=True,
                response=reply,
                data=routing_info,
            ))
        except Exception as e:
            logger.warning(f"LLM Router 调用失败，降级到 api_manager: {e}")

    # 降级：使用 api_manager.call_llm()
    if API_MANAGER_AVAILABLE and api_manager:
        try:
            result = await api_manager.call_llm([
                {"role": "user", "content": message}
            ])
            if result.get("success"):
                reply = result.get("content", "处理完成")
                if MODERN_INTENT_AVAILABLE:
                    try:
                        memory = get_conversation_memory()
                        await memory.add_turn(session_id, "assistant", reply)
                    except Exception:
                        pass
                return JSONResponse(_build_unified_response(
                    success=True,
                    response=reply,
                    data={"provider": result.get("provider", ""), "model": result.get("model", "")},
                ))
            else:
                return JSONResponse(_build_unified_response(
                    success=False,
                    response=f"LLM 调用失败: {result.get('error', 'Unknown error')}",
                    error=result.get("error", "Unknown error"),
                ))
        except Exception as e:
            return JSONResponse(_build_unified_response(
                success=False,
                response=f"错误: {str(e)}",
                error=str(e),
            ))

    return JSONResponse(_build_unified_response(
        success=False,
        response=f"收到: {message}\n\n提示: 请配置 API Key 以启用智能对话功能。",
        error="Galaxy core and API manager not available",
    ))


def parse_intent(message: str) -> Dict[str, Any]:
    """
    简单关键词意图解析 (fallback)

    当 core.ai_intent.IntentParser 不可用时使用此版本。
    """
    message_lower = message.lower()

    # 设备控制
    if any(kw in message_lower for kw in ["打开", "启动", "open"]):
        return {
            "type": "device_control",
            "action": "open_app",
            "params": {"app_name": extract_app_name(message)},
            "confidence": 0.5,
            "suggestions": [],
        }

    if any(kw in message_lower for kw in ["截图", "screenshot"]):
        return {
            "type": "device_control",
            "action": "screenshot",
            "params": {},
            "confidence": 0.5,
            "suggestions": [],
        }

    if any(kw in message_lower for kw in ["滑动", "滚动", "scroll"]):
        direction = "down"
        if "上" in message_lower:
            direction = "up"
        return {
            "type": "device_control",
            "action": "scroll",
            "params": {"direction": direction},
            "confidence": 0.5,
            "suggestions": [],
        }

    # 学习
    if any(kw in message_lower for kw in ["学习", "记住", "learn"]):
        return {"type": "learning", "params": {"action": message, "reward": 0.5},
                "confidence": 0.5, "suggestions": []}

    # 思考
    if any(kw in message_lower for kw in ["思考", "分析", "think"]):
        return {"type": "thinking", "params": {"goal": message},
                "confidence": 0.5, "suggestions": []}

    # 编程
    if any(kw in message_lower for kw in ["写代码", "编程", "code"]):
        return {"type": "coding", "params": {"task": message},
                "confidence": 0.5, "suggestions": []}

    # 知识
    if any(kw in message_lower for kw in ["查询", "搜索", "知识"]):
        return {"type": "knowledge", "params": {"query": message},
                "confidence": 0.5, "suggestions": []}

    return {"type": "chat", "params": {"message": message},
            "confidence": 0.3, "suggestions": []}


def extract_app_name(message: str) -> str:
    """提取应用名称"""
    apps = ["微信", "淘宝", "抖音", "QQ", "支付宝", "浏览器", "设置"]
    for app in apps:
        if app in message:
            return app
    return ""


# ============================================================================
# WebSocket
# ============================================================================

active_websockets: List[WebSocket] = []

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_websockets.append(websocket)
    
    try:
        while True:
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                if message.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
                elif message.get("type") == "chat":
                    ws_response = await dashboard_chat({"message": message.get("content", "")})
                    # chat() returns a JSONResponse; extract body as dict
                    if hasattr(ws_response, "body"):
                        body = json.loads(ws_response.body)
                    else:
                        body = ws_response if isinstance(ws_response, dict) else {}
                    await websocket.send_json({
                        "type": "chat_response",
                        "content": body.get("response", "")
                    })
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        active_websockets.remove(websocket)

# ============================================================================
# 启动事件 (已迁移到 _lifespan context manager)
# ============================================================================

# ============================================================================
# 协议路由降级 — 当 core.routes.protocols 不可用时提供 /api/v1/protocols/* 端点
# 这些端点将请求映射到 /api/v1/config/* 的等效实现
# ============================================================================

if not _PROTOCOLS_REGISTERED:
    logger.info("协议路由未注册，启用降级兼容端点 (/api/v1/protocols/*)")

    @app.get("/api/v1/protocols/mcp")
    async def _fallback_list_mcp():
        return await list_mcp_servers()

    @app.get("/api/v1/protocols/mcp/{name}/tools")
    async def _fallback_mcp_tools(name: str):
        """列出指定 MCP 服务器的工具（降级实现）"""
        try:
            from core.mcp_loader import mcp_loader
            srv = mcp_loader.servers.get(name)
            if srv:
                tools = srv.get("tools", [])
                return {"success": True, "tools": tools, "total": len(tools)}
            return {"success": False, "error": f"MCP server '{name}' not found", "tools": []}
        except Exception as e:
            return {"success": False, "error": str(e), "tools": []}

    @app.delete("/api/v1/protocols/mcp/{name}")
    async def _fallback_remove_mcp(name: str):
        return await remove_mcp_server(name)

    @app.get("/api/v1/protocols/skills")
    async def _fallback_list_skills():
        return await list_skills()

    @app.post("/api/v1/protocols/skills/load")
    async def _fallback_load_skill(request: dict):
        """加载 Skill（降级实现）"""
        name = request.get("name", "")
        if not name:
            return {"success": False, "error": "name is required"}
        try:
            from core.skill_loader import skill_loader
            result = await skill_loader.load(path=name, skill_id=name)
            return result
        except Exception as e:
            return {"success": False, "error": str(e)}

    @app.delete("/api/v1/protocols/skills/{name}")
    async def _fallback_unload_skill(name: str):
        """卸载 Skill（降级实现）"""
        try:
            from core.skill_loader import skill_loader
            result = await skill_loader.unload(name)
            return result
        except Exception as e:
            return {"success": False, "error": str(e)}

    @app.get("/api/v1/protocols/status")
    async def _fallback_protocol_status():
        """协议状态（降级实现）"""
        status = {"success": True, "mcp": {"available": False}, "skills": {"available": False}}
        try:
            from core.mcp_loader import mcp_loader
            status["mcp"] = {"available": True, "servers": len(mcp_loader.servers)}
        except Exception:
            pass
        try:
            from core.skill_loader import skill_loader
            status["skills"] = {"available": True, "loaded": len(skill_loader.skills)}
        except Exception:
            pass
        return status


if __name__ == "__main__":
    import uvicorn
    try:
        from core.port_config import get_service_port
        _dashboard_port = get_service_port("dashboard_backend")
    except Exception:
        _dashboard_port = 8085
    uvicorn.run(app, host="0.0.0.0", port=_dashboard_port)


# ============================================================================
# 仓库协调 API
# ============================================================================

# 导入协调层
try:
    from core.repo_coordinator import repo_coordinator
    REPO_COORDINATOR_AVAILABLE = True
except ImportError:
    REPO_COORDINATOR_AVAILABLE = False
    repo_coordinator = None


@app.post("/api/v1/android/register")
async def register_android_device(request: dict):
    """
    注册 Android 设备
    
    Android 仓库通过此接口注册到主仓库
    """
    if REPO_COORDINATOR_AVAILABLE and repo_coordinator:
        device_id = request.get("device_id", "")
        device_info = request.get("device_info", {})
        result = await repo_coordinator.register_android_device(device_id, device_info)
        return result
    return {"success": False, "error": "Repo coordinator not available"}


@app.post("/api/v1/android/unregister")
async def unregister_android_device(request: dict):
    """注销 Android 设备"""
    if REPO_COORDINATOR_AVAILABLE and repo_coordinator:
        device_id = request.get("device_id", "")
        result = await repo_coordinator.unregister_android_device(device_id)
        return result
    return {"success": False, "error": "Repo coordinator not available"}


@app.post("/api/v1/android/heartbeat")
async def android_heartbeat(request: dict):
    """Android 设备心跳"""
    if REPO_COORDINATOR_AVAILABLE and repo_coordinator:
        device_id = request.get("device_id", "")
        result = await repo_coordinator.heartbeat_android_device(device_id)
        return result
    return {"success": False, "error": "Repo coordinator not available"}


@app.get("/api/v1/android/devices")
async def list_android_devices():
    """列出所有 Android 设备"""
    if REPO_COORDINATOR_AVAILABLE and repo_coordinator:
        devices = repo_coordinator.get_android_devices()
        return {"devices": devices, "total": len(devices)}
    return {"devices": [], "total": 0}


@app.post("/api/v1/android/dispatch")
async def dispatch_to_android(request: dict):
    """
    分发 Agent 到 Android 设备
    
    通过 WebSocket 或 HTTP 发送命令
    """
    if REPO_COORDINATOR_AVAILABLE and repo_coordinator:
        device_id = request.get("device_id", "")
        task_type = request.get("task_type", "")
        params = request.get("params", {})
        result = await repo_coordinator.dispatch_agent_to_android(device_id, task_type, params)
        return result
    return {"success": False, "error": "Repo coordinator not available"}


@app.post("/api/v1/android/broadcast")
async def broadcast_to_android(request: dict):
    """广播到所有 Android 设备"""
    if REPO_COORDINATOR_AVAILABLE and repo_coordinator:
        task_type = request.get("task_type", "")
        params = request.get("params", {})
        result = await repo_coordinator.broadcast_to_all_android(task_type, params)
        return result
    return {"success": False, "error": "Repo coordinator not available"}


@app.get("/api/v1/coordinator/status")
async def get_coordinator_status():
    """获取协调器状态"""
    if REPO_COORDINATOR_AVAILABLE and repo_coordinator:
        return repo_coordinator.get_status()
    return {"error": "Repo coordinator not available"}


# ============================================================================
# API 配置管理
# ============================================================================

# 导入 API 管理器
try:
    from core.api_manager import api_manager
    API_MANAGER_AVAILABLE = True
except ImportError:
    API_MANAGER_AVAILABLE = False
    api_manager = None


@app.get("/api/v1/config")
async def get_config():
    """获取完整配置"""
    if API_MANAGER_AVAILABLE and api_manager:
        return api_manager.get_config()
    return {"status": "standalone", "api_manager_available": False, "config": {}}


@app.post("/api/v1/config")
async def update_config(request: dict):
    """更新配置"""
    if API_MANAGER_AVAILABLE and api_manager:
        success = api_manager.update_config(request)
        return {"success": success}
    return {"success": False, "error": "API manager not available"}


@app.get("/api/v1/config/models")
async def get_models():
    """获取所有模型"""
    if API_MANAGER_AVAILABLE and api_manager:
        return {"models": api_manager.get_models()}
    return {"models": []}


@app.get("/api/v1/config/models/available")
async def get_available_models():
    """获取可用模型"""
    if API_MANAGER_AVAILABLE and api_manager:
        return {"models": api_manager.get_available_models()}
    return {"models": []}


@app.post("/api/v1/config/api-key")
async def set_api_key(request: dict):
    """设置 API Key — 同时持久化到 api_config.json 和 .env"""
    if API_MANAGER_AVAILABLE and api_manager:
        category = request.get("category", "direct_models")  # 默认是 direct_models
        key_name = request.get("provider", "")  # 兼容旧参数名
        api_key = request.get("api_key", "")

        # 如果 provider 是 oneapi，则 category 是 oneapi
        if key_name == "oneapi":
            category = "oneapi"
            key_name = ""

        # 1. 保存到 api_config.json + 同步到 os.environ
        success = api_manager.set_api_key(category, key_name, api_key)

        # 2. 持久化到 .env 文件 (与 set_node_api_key 保持一致)
        if success and api_key:
            env_var = ""
            if category == "oneapi":
                env_var = "ONEAPI_API_KEY"
            elif category == "direct_models" and key_name:
                env_var = f"{key_name.upper()}_API_KEY"
            elif category == "tools" and key_name:
                env_var = f"{key_name.upper()}_API_KEY"

            if env_var:
                # 写入环境变量
                os.environ[env_var] = api_key
                # 写入 CredentialVault
                try:
                    from core.credential_vault import get_vault
                    get_vault().set_credential(env_var, api_key, actor="dashboard")
                except Exception:
                    pass
                # 持久化到 .env
                env_path = os.path.join(PROJECT_ROOT, ".env")
                try:
                    lines = []
                    replaced = False
                    if os.path.exists(env_path):
                        with open(env_path, "r", encoding="utf-8") as f:
                            for line in f:
                                if line.strip().startswith(f"{env_var}="):
                                    lines.append(f"{env_var}={api_key}\n")
                                    replaced = True
                                else:
                                    lines.append(line)
                    if not replaced:
                        lines.append(f"{env_var}={api_key}\n")
                    with open(env_path, "w", encoding="utf-8") as f:
                        f.writelines(lines)
                except Exception as e:
                    logger.warning(f".env write failed for {env_var}: {e}")

                # 刷新 LLM Router 使其感知到新的 API Key
                if LLM_ROUTER_AVAILABLE and llm_router:
                    try:
                        import asyncio as _aio
                        _aio.get_running_loop().create_task(llm_router.refresh_providers())
                    except RuntimeError:
                        # 没有运行中的事件循环时，使用同步发现
                        llm_router._discover_providers()

        return {"success": success}
    return {"success": False, "error": "API manager not available"}


@app.get("/api/v1/config/nodes")
async def get_config_nodes():
    """获取所有节点配置"""
    if API_MANAGER_AVAILABLE and api_manager:
        return {"nodes": api_manager.get_nodes()}
    return {"nodes": []}


@app.post("/api/v1/config/nodes/check")
async def check_nodes():
    """检查所有节点"""
    if API_MANAGER_AVAILABLE and api_manager:
        results = await api_manager.check_all_nodes()
        return {"results": results}
    return {"results": {}}


@app.get("/api/v1/config/status")
async def get_config_status():
    """获取配置状态"""
    if API_MANAGER_AVAILABLE and api_manager:
        return api_manager.get_status()
    return {
        "status": "standalone",
        "api_manager_available": False,
        "models_configured": False,
        "nodes_active": 0,
        "message": "Running in standalone mode - core API manager not loaded"
    }


@app.post("/api/v1/config/test-llm")
async def test_llm(request: dict):
    """测试 LLM 调用"""
    if API_MANAGER_AVAILABLE and api_manager:
        message = request.get("message", "Hello, this is a test.")
        result = await api_manager.call_llm([
            {"role": "user", "content": message}
        ])
        return result
    return {"success": False, "error": "API manager not available"}
"""
Dashboard 后端 API 扩展
======================

添加到 main.py 的 API 接口
"""

# 将以下代码添加到 dashboard/backend/main.py 的末尾

# ============================================================================
# 工具 API 管理
# ============================================================================

@app.get("/api/v1/config/tools")
async def get_tools():
    """获取所有工具"""
    if API_MANAGER_AVAILABLE and api_manager:
        return {"tools": api_manager.get_tools()}
    return {"tools": []}


@app.get("/api/v1/config/tools/available")
async def get_available_tools():
    """获取可用工具"""
    if API_MANAGER_AVAILABLE and api_manager:
        return {"tools": api_manager.get_available_tools()}
    return {"tools": []}


@app.post("/api/v1/config/tools/api-key")
async def set_tool_api_key(request: dict):
    """设置工具 API Key"""
    if API_MANAGER_AVAILABLE and api_manager:
        tool_id = request.get("tool_id", "")
        api_key = request.get("api_key", "")
        success = api_manager.set_api_key("tools", tool_id, api_key)
        return {"success": success}
    return {"success": False, "error": "API manager not available"}


# ============================================================================
# MCP 服务器管理
# ============================================================================

@app.get("/api/v1/config/mcp-servers")
async def list_mcp_servers():
    """列出已配置的 MCP 服务器及其状态"""
    try:
        from core.mcp_loader import mcp_loader
        servers = []
        for name, srv in mcp_loader.servers.items():
            servers.append({
                "name": name,
                "status": "running" if srv.get("process") and srv["process"].returncode is None else "stopped",
                "command": srv.get("command", ""),
                "tools_count": len(srv.get("tools", [])),
                "tools": [t.get("name", "") for t in srv.get("tools", [])],
            })

        # 也读取配置文件中未启动的服务器
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "config", "mcp_servers.json"
        )
        if os.path.exists(config_path):
            import json as _json
            with open(config_path, "r", encoding="utf-8") as f:
                mcp_config = _json.load(f)
            for srv_cfg in mcp_config.get("servers", []):
                if srv_cfg["name"] not in mcp_loader.servers:
                    servers.append({
                        "name": srv_cfg["name"],
                        "status": "configured",
                        "command": srv_cfg.get("command", ""),
                        "auto_start": srv_cfg.get("auto_start", False),
                        "tools_count": 0,
                        "tools": [],
                    })

        return {"success": True, "servers": servers}
    except Exception as e:
        return {"success": False, "error": str(e), "servers": []}


@app.post("/api/v1/config/mcp-servers")
async def add_mcp_server(request: dict):
    """添加或修改 MCP 服务器配置"""
    name = request.get("name", "")
    command = request.get("command", "")
    auto_start = request.get("auto_start", False)
    env = request.get("env", {})

    if not name or not command:
        return {"success": False, "error": "name 和 command 必填"}

    try:
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "config", "mcp_servers.json"
        )
        import json as _json
        config = {"servers": []}
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                config = _json.load(f)

        # 更新或添加
        found = False
        for srv in config["servers"]:
            if srv["name"] == name:
                srv["command"] = command
                srv["auto_start"] = auto_start
                srv["env"] = env
                found = True
                break
        if not found:
            config["servers"].append({
                "name": name,
                "command": command,
                "auto_start": auto_start,
                "env": env,
            })

        with open(config_path, "w", encoding="utf-8") as f:
            _json.dump(config, f, ensure_ascii=False, indent=2)

        return {"success": True, "message": f"MCP 服务器 '{name}' 已{'更新' if found else '添加'}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.delete("/api/v1/config/mcp-servers/{name}")
async def remove_mcp_server(name: str):
    """移除 MCP 服务器配置"""
    try:
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "config", "mcp_servers.json"
        )
        import json as _json
        if not os.path.exists(config_path):
            return {"success": False, "error": "配置文件不存在"}

        with open(config_path, "r", encoding="utf-8") as f:
            config = _json.load(f)

        config["servers"] = [s for s in config["servers"] if s["name"] != name]

        with open(config_path, "w", encoding="utf-8") as f:
            _json.dump(config, f, ensure_ascii=False, indent=2)

        # 如果正在运行，尝试停止
        try:
            from core.mcp_loader import mcp_loader
            if name in mcp_loader.servers:
                await mcp_loader.unload(name)
        except Exception:
            pass

        return {"success": True, "message": f"MCP 服务器 '{name}' 已移除"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================================
# Skill 管理
# ============================================================================

@app.get("/api/v1/config/skills")
async def list_skills():
    """列出已加载的 Skill 及状态"""
    try:
        from core.skill_loader import skill_loader
        skills = []
        for name, skill in skill_loader.skills.items():
            skills.append({
                "name": name,
                "description": getattr(skill, "description", ""),
                "status": "loaded",
                "actions": list(getattr(skill, "actions", {}).keys()) if hasattr(skill, "actions") else [],
            })

        # 扫描 skills 目录中未加载的
        skills_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "skills"
        )
        if os.path.isdir(skills_dir):
            for entry in os.listdir(skills_dir):
                entry_path = os.path.join(skills_dir, entry)
                if os.path.isdir(entry_path) and entry not in [s["name"] for s in skills]:
                    skills.append({
                        "name": entry,
                        "description": "",
                        "status": "available",
                        "actions": [],
                    })

        return {"success": True, "skills": skills}
    except Exception as e:
        return {"success": False, "error": str(e), "skills": []}


@app.post("/api/v1/config/skills/reload")
async def reload_skills():
    """重新加载所有 Skill"""
    try:
        from core.skill_loader import skill_loader
        skill_loader.reload_all()
        return {
            "success": True,
            "message": f"已重新加载 {len(skill_loader.skills)} 个 Skill",
            "skills_count": len(skill_loader.skills),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================================
# API 验证 - 关键功能
# ============================================================================

@app.post("/api/v1/config/validate")
async def validate_api(request: dict):
    """
    验证 API Key 是否有效
    
    这是关键功能，确保 API Key 真的能用
    """
    if API_MANAGER_AVAILABLE and api_manager:
        category = request.get("category", "")  # oneapi, direct_models, tools
        key_name = request.get("key_name", "")
        
        result = await api_manager.validate_api_key(category, key_name)
        return result
    
    return {"valid": False, "error": "API manager not available"}


@app.post("/api/v1/config/validate-all")
async def validate_all_apis():
    """验证所有已配置的 API"""
    if API_MANAGER_AVAILABLE and api_manager:
        results = {}
        
        # 验证 OneAPI
        if api_manager.config.get("oneapi", {}).get("api_key"):
            results["oneapi"] = await api_manager.validate_api_key("oneapi", "")
        
        # 验证直接模型
        for provider, config in api_manager.config.get("direct_models", {}).items():
            if config.get("api_key"):
                results[provider] = await api_manager.validate_api_key("direct_models", provider)
        
        # 验证工具
        for tool_id, config in api_manager.config.get("tools", {}).items():
            if config.get("api_key"):
                results[tool_id] = await api_manager.validate_api_key("tools", tool_id)
        
        return {"results": results}
    
    return {"results": {}}


# ============================================================================
# 环境变量同步
# ============================================================================

@app.post("/api/v1/config/sync-env")
async def sync_to_env():
    """
    将配置同步到环境变量
    
    这是关键功能，确保节点能读取到 API Key
    """
    if API_MANAGER_AVAILABLE and api_manager:
        results = api_manager.sync_to_env()
        return {"success": True, "synced": results}
    return {"success": False, "error": "API manager not available"}


@app.get("/api/v1/config/env-status")
async def get_env_status():
    """获取环境变量状态"""
    env_keys = [
        "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY",
        "ZHIPU_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY",
        "OPENROUTER_API_KEY", "BRAVE_API_KEY", "NOTION_API_KEY",
        "OPENWEATHER_API_KEY"
    ]
    
    status = {}
    for key in env_keys:
        value = os.environ.get(key, "")
        status[key] = {
            "configured": bool(value),
            "masked": value[:8] + "..." if len(value) > 8 else ""
        }
    
    return {"status": status}


# ============================================================================
# 实时状态面板 — 聚合端点
# ============================================================================

@app.get("/api/v1/observability/live-status")
async def get_live_status():
    """
    实时状态面板聚合端点。

    一次调用返回面板所需的全部实时数据：
      - capability_load: CapabilityRegistry 中已注册的工具数量及列表
      - gateway_trace:   CommandRouter 路由统计 + 近期 3 条调用记录
      - device_health:   设备注册数 / 在线数 / 各设备状态
      - model_route:     当前活跃 LLM 路由及 Fallback 状态
      - observability_available: 是否已注册可观测性子路由
    """
    import time as _time

    # ── Capability load status ────────────────────────────────────────────
    capability_info: dict = {"count": 0, "tools": [], "error": None}
    try:
        from core.agent.capability_registry import CapabilityRegistry
        reg = CapabilityRegistry.get_instance()
        tools = [
            {"name": name, "source": item.source}
            for name, item in reg._items.items()
        ]
        capability_info = {"count": len(tools), "tools": tools, "error": None}
    except Exception as exc:
        capability_info["error"] = str(exc)

    # ── Gateway trace / command router ────────────────────────────────────
    gateway_info: dict = {"stats": {}, "recent_calls": [], "error": None}
    try:
        from core.command_router import get_command_router, get_gateway_trace_store
        gateway_info["stats"] = get_command_router().get_stats()
        gateway_info["recent_calls"] = get_gateway_trace_store().recent(3)
    except Exception as exc:
        gateway_info["error"] = str(exc)

    # ── Device health ─────────────────────────────────────────────────────
    device_info: dict = {
        "registered": 0, "online": 0, "devices": [], "error": None
    }
    try:
        from core.device_registry import DeviceRegistry
        registry = DeviceRegistry.get_instance()
        device_list = []
        for dev in registry.list_devices():
            online = dev.is_online()
            device_list.append({
                "device_id": dev.device_id,
                "device_type": dev.device_type,
                "online": online,
                "status": dev.status.value,
                "last_seen": dev.last_seen,
            })
        online_count = sum(1 for d in device_list if d["online"])
        device_info = {
            "registered": len(device_list),
            "online": online_count,
            "devices": device_list,
            "error": None,
        }
    except Exception as exc:
        device_info["error"] = str(exc)

    # ── Model route ───────────────────────────────────────────────────────
    model_info: dict = {
        "default_model": None, "active_provider": None,
        "fallbacks": [], "error": None,
    }
    try:
        from core.multi_llm_router import get_llm_router
        router_inst = get_llm_router()
        status = router_inst.get_status()
        providers = router_inst.get_provider_status()
        model_info = {
            "default_model": router_inst.get_default_model(),
            "active_provider": status.get("active_provider"),
            "fallbacks": [
                p for p in providers
                if not p.get("is_primary", False) and p.get("available", False)
            ],
            "router_stats": status,
            "error": None,
        }
    except Exception as exc:
        model_info["error"] = str(exc)

    return {
        "timestamp": _time.time(),
        "observability_available": _OBSERVABILITY_REGISTERED,
        "capability_load": capability_info,
        "gateway_trace": gateway_info,
        "device_health": device_info,
        "model_route": model_info,
    }


# ============================================================================
# 联邦健康摘要
# ============================================================================

@app.get("/api/v1/federation/health")
async def get_federation_health():
    """联邦健康摘要：本地状态 + peers 数量 + alive/degraded/offline 统计"""
    try:
        from core.galaxy_federation import get_federation, _federation_enabled
        fed = get_federation()
        peers = fed.list_peers()
        return {
            "instance_id": fed.instance_id,
            "local_url": fed.local_url,
            "enabled": _federation_enabled(),
            "peers_count": len(peers),
            "alive": sum(1 for p in peers if p["status"] == "healthy"),
            "degraded": sum(1 for p in peers if p["status"] == "degraded"),
            "offline": sum(1 for p in peers if p["status"] == "offline"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# 权限策略管理 (P1)
# ============================================================================

_DATA_DIR = os.path.join(PROJECT_ROOT, "data")
_PERMISSIONS_POLICY_FILE = os.path.join(_DATA_DIR, "permissions_policy.json")
_INTEGRATIONS_CONFIG_FILE = os.path.join(_DATA_DIR, "integrations_config.json")

_DEFAULT_PERMISSIONS_POLICY: Dict[str, Any] = {
    "global": {
        "filesystem": False,
        "terminal": False,
        "network": True,
        "browser": False,
        "description": "全局默认权限策略",
    },
    "agent_overrides": {},
    "updated_at": "",
}

_DEFAULT_INTEGRATIONS_CONFIG: Dict[str, Any] = {
    "telegram":  {"enabled": False, "bot_token": "", "webhook_url": "", "description": "Telegram Bot 集成"},
    "discord":   {"enabled": False, "bot_token": "", "webhook_url": "", "description": "Discord Bot 集成"},
    "slack":     {"enabled": False, "bot_token": "", "webhook_url": "", "description": "Slack App 集成"},
    "whatsapp":  {"enabled": False, "api_token": "", "phone_number_id": "", "description": "WhatsApp Business API 集成"},
    "updated_at": "",
}


def _load_json_file(path: str, default: dict) -> dict:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            pass
    return default.copy()


def _save_json_file(path: str, data: dict) -> bool:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data["updated_at"] = datetime.now().isoformat()
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        return True
    except Exception as exc:
        logger.error("保存文件失败 %s: %s", path, exc)
        return False


@app.get("/api/v1/permissions/policy")
async def get_permissions_policy():
    """获取全局权限策略（及各 Agent 覆盖项）"""
    return _load_json_file(_PERMISSIONS_POLICY_FILE, _DEFAULT_PERMISSIONS_POLICY)


@app.post("/api/v1/permissions/policy")
async def update_permissions_policy(request: dict):
    """更新全局权限策略。支持局部更新 global / agent_overrides。"""
    policy = _load_json_file(_PERMISSIONS_POLICY_FILE, _DEFAULT_PERMISSIONS_POLICY)
    if "global" in request and isinstance(request["global"], dict):
        policy.setdefault("global", {}).update(request["global"])
    if "agent_overrides" in request and isinstance(request["agent_overrides"], dict):
        policy.setdefault("agent_overrides", {}).update(request["agent_overrides"])
    success = _save_json_file(_PERMISSIONS_POLICY_FILE, policy)
    return {"success": success, "policy": policy}


# ============================================================================
# 集成管理 (P1)
# ============================================================================


@app.get("/api/v1/integrations/config")
async def get_integrations_config():
    """获取集成配置（Token 字段脱敏，仅返回是否已配置）"""
    config = _load_json_file(_INTEGRATIONS_CONFIG_FILE, _DEFAULT_INTEGRATIONS_CONFIG)
    safe: Dict[str, Any] = {}
    for key, val in config.items():
        if not isinstance(val, dict):
            safe[key] = val
            continue
        entry = dict(val)
        for token_field in ("bot_token", "api_token"):
            if entry.get(token_field):
                entry[token_field + "_configured"] = True
                entry[token_field] = ""
            else:
                entry[token_field + "_configured"] = False
        safe[key] = entry
    return safe


@app.post("/api/v1/integrations/config")
async def update_integrations_config(request: dict):
    """更新集成配置。支持局部更新各平台字段。"""
    config = _load_json_file(_INTEGRATIONS_CONFIG_FILE, _DEFAULT_INTEGRATIONS_CONFIG)
    for platform in ("telegram", "discord", "slack", "whatsapp"):
        if platform in request and isinstance(request[platform], dict):
            config.setdefault(platform, {}).update(request[platform])
    success = _save_json_file(_INTEGRATIONS_CONFIG_FILE, config)
    return {"success": success}
