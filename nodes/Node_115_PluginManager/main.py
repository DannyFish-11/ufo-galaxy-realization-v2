"""
Node 115: PluginManager
========================
Manages Galaxy system plugins: plugin registry, lifecycle management
(install/enable/disable/remove), plugin health checking, and plugin
capability discovery.
"""

import logging  # auto: ensure module logger is defined
logger = logging.getLogger(__name__)


import os
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from core.atomic_json import atomic_write_json

try:
    from nodes.common.cors_config import get_cors_origins
except Exception as exc:
    def get_cors_origins():
        return ["*"]

try:
    from core.port_config import get_node_port
    _DEFAULT_PORT = get_node_port("Node_115_PluginManager")
except Exception as exc:
    logger.debug("Fallback triggered: %s", exc)
    _DEFAULT_PORT = 8115

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

NODE_ID = "115"
NODE_NAME = "PluginManager"

# 插件注册表落盘位置。
#
# 原先是 ``os.getenv("PLUGIN_REGISTRY_PATH", "./plugins")`` —— 一个**相对 CWD**
# 的默认值。两个后果:
#
#   1. 文件落在哪取决于你从哪个目录启动。正常从仓库根启动 = 写进**仓库目录**,
#      于是这个纯运行时产物变成 git 里的一个未跟踪脏文件;本会话早先就有一次
#      ``git add -A`` 把 plugins/registry.json 顺手提交了进去(已从索引移除并加进
#      .gitignore)。.gitignore 挡住的是"被提交",挡不住"写错地方"。
#   2. 换个目录启动就读不到上次的注册表 —— 表现为插件列表莫名回到内置三条,
#      看不出是路径问题。
#
# 改用仓库既有的 GALAXY_DATA_DIR 约定(peer_trust / delegated_flow_persistence /
# mesh 持久化都认它),并把兜底值锚在**本文件的位置**而不是 CWD,这样"从哪启动"
# 不再改变数据位置。PLUGIN_REGISTRY_PATH 仍然优先,显式配置不受影响。
_REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_REGISTRY_PATH = os.getenv("PLUGIN_REGISTRY_PATH", "").strip() or str(
    Path(os.getenv("GALAXY_DATA_DIR", "").strip() or (_REPO_ROOT / "data")) / "plugins"
)
PLUGIN_STORE_URL = os.getenv("PLUGIN_STORE_URL", "")

_start_time = datetime.now()

# 目录**不在 import 期建**。建目录是文件系统副作用,不该由"导入一个模块"触发 ——
# 只是 collect 一下测试、或者 import 进来读个常量,都不该在磁盘上留下东西。
# 真正要写的时候 atomic_write_json 自己会 makedirs;读的时候 exists() 判空即可。
_REGISTRY_FILE = Path(PLUGIN_REGISTRY_PATH) / "registry.json"

app = FastAPI(title=f"Node {NODE_ID} - {NODE_NAME}", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Registry persistence
# ---------------------------------------------------------------------------

_plugin_registry: Dict[str, Dict[str, Any]] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_registry():
    global _plugin_registry
    if _REGISTRY_FILE.exists():
        try:
            with open(_REGISTRY_FILE, "r", encoding="utf-8") as f:
                _plugin_registry = json.load(f)
            logger.info(f"Loaded {len(_plugin_registry)} plugins from registry")
            return
        except Exception as e:
            logger.warning(f"Could not load registry: {e}")
    # Seed built-in plugins
    _plugin_registry = {
        "galaxy-core": {
            "id": "galaxy-core",
            "name": "Galaxy Core",
            "version": "1.0.0",
            "description": "Core Galaxy system plugin providing base functionality",
            "status": "enabled",
            "endpoint": "http://localhost:8000",
            "capabilities": ["task_routing", "agent_management", "system_status"],
            "installed_at": _now_iso(),
            "last_check": _now_iso(),
        },
        "galaxy-memory": {
            "id": "galaxy-memory",
            "name": "Galaxy Memory",
            "version": "1.0.0",
            "description": "Persistent memory and knowledge storage for Galaxy agents",
            "status": "enabled",
            "endpoint": "http://localhost:8100",
            "capabilities": ["memory_store", "memory_retrieve", "knowledge_graph"],
            "installed_at": _now_iso(),
            "last_check": _now_iso(),
        },
        "galaxy-code-engine": {
            "id": "galaxy-code-engine",
            "name": "Galaxy Code Engine",
            "version": "1.0.0",
            "description": "Code execution and analysis plugin",
            "status": "disabled",
            "endpoint": "http://localhost:8101",
            "capabilities": ["code_execution", "code_analysis", "syntax_check"],
            "installed_at": _now_iso(),
            "last_check": _now_iso(),
        },
    }
    _save_registry()


def _save_registry():
    try:
        atomic_write_json(_REGISTRY_FILE, _plugin_registry, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Could not save registry: {e}")


_load_registry()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class RegisterPluginRequest(BaseModel):
    id: str
    name: str
    version: str
    description: str = ""
    endpoint: str = ""
    capabilities: List[str] = []


class MCPCallRequest(BaseModel):
    tool: str
    parameters: Dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    enabled = sum(1 for p in _plugin_registry.values() if p["status"] == "enabled")
    return {
        "status": "healthy",
        "node": "Node_115_PluginManager",
        "version": "1.0.0",
        "plugins_count": len(_plugin_registry),
        "enabled_count": enabled,
    }


@app.get("/status")
async def status():
    uptime = (datetime.now() - _start_time).total_seconds()
    by_status: Dict[str, int] = {}
    for p in _plugin_registry.values():
        by_status[p["status"]] = by_status.get(p["status"], 0) + 1
    return {
        "node_id": NODE_ID,
        "node_name": NODE_NAME,
        "status": "running",
        "uptime_seconds": uptime,
        "config": {
            "registry_path": PLUGIN_REGISTRY_PATH,
            "plugin_store_url": PLUGIN_STORE_URL,
        },
        "plugin_summary": {
            "total": len(_plugin_registry),
            "by_status": by_status,
        },
    }


@app.post("/mcp/call")
async def mcp_call(req: MCPCallRequest):
    tool = req.tool
    parameters = req.parameters
    if tool == "list_plugins":
        return {"tool": tool, "result": {"plugins": list(_plugin_registry.values())}}
    if tool == "get_plugin":
        return {"tool": tool, "result": _plugin_registry.get(parameters.get("plugin_id", ""), {})}
    if tool == "get_capabilities":
        return {"tool": tool, "result": _get_capabilities()}
    raise HTTPException(status_code=404, detail=f"Unknown tool: {tool}")


@app.get("/plugins")
async def list_plugins(status: Optional[str] = None):
    plugins = list(_plugin_registry.values())
    if status and status != "all":
        plugins = [p for p in plugins if p["status"] == status]
    return {"plugins": plugins, "count": len(plugins)}


@app.post("/plugins/register")
async def register_plugin(req: RegisterPluginRequest):
    if req.id in _plugin_registry:
        raise HTTPException(status_code=409, detail=f"Plugin '{req.id}' already registered")
    plugin = {
        "id": req.id,
        "name": req.name,
        "version": req.version,
        "description": req.description,
        "status": "disabled",
        "endpoint": req.endpoint,
        "capabilities": req.capabilities,
        "installed_at": _now_iso(),
        "last_check": _now_iso(),
    }
    _plugin_registry[req.id] = plugin
    _save_registry()
    logger.info(f"Registered plugin: {req.id}")
    return {"message": f"Plugin '{req.id}' registered successfully", "plugin": plugin}


@app.get("/plugins/{plugin_id}")
async def get_plugin(plugin_id: str):
    plugin = _plugin_registry.get(plugin_id)
    if not plugin:
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_id}' not found")
    return plugin


@app.post("/plugins/{plugin_id}/enable")
async def enable_plugin(plugin_id: str):
    plugin = _plugin_registry.get(plugin_id)
    if not plugin:
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_id}' not found")
    plugin["status"] = "enabled"
    _save_registry()
    return {"message": f"Plugin '{plugin_id}' enabled", "plugin": plugin}


@app.post("/plugins/{plugin_id}/disable")
async def disable_plugin(plugin_id: str):
    plugin = _plugin_registry.get(plugin_id)
    if not plugin:
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_id}' not found")
    plugin["status"] = "disabled"
    _save_registry()
    return {"message": f"Plugin '{plugin_id}' disabled", "plugin": plugin}


@app.delete("/plugins/{plugin_id}")
async def remove_plugin(plugin_id: str):
    if plugin_id not in _plugin_registry:
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_id}' not found")
    del _plugin_registry[plugin_id]
    _save_registry()
    logger.info(f"Removed plugin: {plugin_id}")
    return {"message": f"Plugin '{plugin_id}' removed"}


@app.post("/plugins/{plugin_id}/check")
async def check_plugin(plugin_id: str):
    plugin = _plugin_registry.get(plugin_id)
    if not plugin:
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_id}' not found")
    endpoint = plugin.get("endpoint", "")
    check_result: Dict[str, Any] = {"plugin_id": plugin_id, "endpoint": endpoint}
    if not endpoint:
        check_result["reachable"] = False
        check_result["error"] = "No endpoint configured"
    else:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{endpoint}/health")
            check_result["reachable"] = resp.status_code < 500
            check_result["status_code"] = resp.status_code
            try:
                check_result["health"] = resp.json()
            except Exception as exc:
                logger.debug("Fallback triggered: %s", exc)
                check_result["health"] = resp.text[:200]
        except Exception as e:
            logger.debug("Fallback triggered: %s", e)
            check_result["reachable"] = False
            check_result["error"] = str(e)
            plugin["status"] = "error"
    plugin["last_check"] = _now_iso()
    _save_registry()
    return check_result


@app.get("/capabilities")
async def list_capabilities():
    return _get_capabilities()


def _get_capabilities() -> Dict[str, Any]:
    caps: Dict[str, List[str]] = {}
    all_caps = set()
    for plugin in _plugin_registry.values():
        if plugin["status"] == "enabled":
            for cap in plugin.get("capabilities", []):
                all_caps.add(cap)
                caps.setdefault(cap, []).append(plugin["id"])
    return {
        "capabilities": sorted(all_caps),
        "capability_map": caps,
        "total": len(all_caps),
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("NODE_115_PORT", str(_DEFAULT_PORT)))
    logger.info(f"Starting Node {NODE_ID} - {NODE_NAME} on port {port}")
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
