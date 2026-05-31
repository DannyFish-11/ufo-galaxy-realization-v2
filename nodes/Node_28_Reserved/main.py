"""
Node 28: Plugin Manager - 插件管理节点
=========================================
动态加载、执行和管理本地 Python 插件
"""
import os
import sys
import importlib.util
import logging
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional, List

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from nodes.common.cors_config import get_cors_origins

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Node_28_PluginManager")

PORT = 8028
NODE_ID = "28"
NODE_NAME = os.getenv("NODE_28_NAME", "PluginManager")
PLUGIN_DIR = os.getenv("PLUGIN_DIR", os.path.join(os.path.dirname(__file__), "plugins"))

app = FastAPI(title=f"Node {NODE_ID} - {NODE_NAME}", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-memory plugin registry ────────────────────────────────────────────────

class PluginRecord:
    def __init__(self, name: str, version: str, description: str, module: Any, filepath: str):
        self.name = name
        self.version = version
        self.description = description
        self.module = module
        self.filepath = filepath
        self.enabled = True
        self.loaded_at = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "enabled": self.enabled,
            "filepath": self.filepath,
            "loaded_at": self.loaded_at,
        }


plugins: Dict[str, PluginRecord] = {}
stats = {"load_count": 0, "execute_count": 0, "execute_errors": 0}

# ── Plugin loading helpers ────────────────────────────────────────────────────

def _load_plugin_from_file(filepath: str) -> Optional[PluginRecord]:
    """Load a single plugin file; returns None if invalid."""
    try:
        spec = importlib.util.spec_from_file_location("_plugin_tmp", filepath)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[attr-defined]

        name = getattr(module, "PLUGIN_NAME", None)
        version = getattr(module, "PLUGIN_VERSION", None)
        description = getattr(module, "PLUGIN_DESCRIPTION", "")

        if not name or not version:
            logger.warning("Plugin %s missing PLUGIN_NAME or PLUGIN_VERSION – skipped", filepath)
            return None
        if not callable(getattr(module, "execute", None)):
            logger.warning("Plugin %s has no execute() function – skipped", filepath)
            return None

        return PluginRecord(name=name, version=version, description=description,
                            module=module, filepath=filepath)
    except Exception as exc:
        logger.error("Failed to load plugin %s: %s", filepath, exc)
        return None


def _scan_plugin_dir(directory: str) -> List[PluginRecord]:
    """Scan directory and return valid plugin records."""
    if not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)
        return []

    loaded = []
    for filename in os.listdir(directory):
        if not filename.endswith(".py") or filename.startswith("_"):
            continue
        filepath = os.path.join(directory, filename)
        record = _load_plugin_from_file(filepath)
        if record:
            loaded.append(record)
    return loaded


# ── Pydantic request models ───────────────────────────────────────────────────

class LoadRequest(BaseModel):
    plugin_dir: Optional[str] = None

class PluginNameRequest(BaseModel):
    plugin_name: str

class ExecuteRequest(BaseModel):
    plugin_name: str
    params: Dict[str, Any] = {}

# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    enabled_count = sum(1 for p in plugins.values() if p.enabled)
    return {
        "success": True,
        "status": "healthy",
        "node_id": NODE_ID,
        "name": NODE_NAME,
        "port": PORT,
        "plugin_dir": PLUGIN_DIR,
        "plugins_loaded": len(plugins),
        "plugins_enabled": enabled_count,
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/status")
async def status():
    enabled = sum(1 for p in plugins.values() if p.enabled)
    disabled = len(plugins) - enabled
    return {
        "success": True,
        "node_id": NODE_ID,
        "name": NODE_NAME,
        "configured": True,
        "config_summary": {"plugin_dir": PLUGIN_DIR},
        "stats": {
            "total_plugins": len(plugins),
            "enabled_plugins": enabled,
            "disabled_plugins": disabled,
            "load_count": stats["load_count"],
            "execute_count": stats["execute_count"],
            "execute_errors": stats["execute_errors"],
        },
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/plugins")
async def list_plugins():
    return {
        "success": True,
        "plugins": [p.to_dict() for p in plugins.values()],
        "total": len(plugins),
    }


@app.post("/plugins/load")
async def load_plugins(request: LoadRequest = LoadRequest()):
    directory = request.plugin_dir or PLUGIN_DIR
    records = _scan_plugin_dir(directory)
    loaded_names = []
    for record in records:
        plugins[record.name] = record
        stats["load_count"] += 1
        loaded_names.append(record.name)
    return {
        "success": True,
        "message": f"Loaded {len(loaded_names)} plugin(s) from {directory}",
        "loaded": loaded_names,
        "plugin_dir": directory,
    }


@app.post("/plugins/reload")
async def reload_plugin(request: PluginNameRequest):
    if request.plugin_name not in plugins:
        raise HTTPException(status_code=404, detail=f"Plugin '{request.plugin_name}' not found")
    existing = plugins[request.plugin_name]
    record = _load_plugin_from_file(existing.filepath)
    if record is None:
        raise HTTPException(status_code=500, detail="Failed to reload plugin")
    record.enabled = existing.enabled
    plugins[record.name] = record
    stats["load_count"] += 1
    return {"success": True, "message": f"Plugin '{request.plugin_name}' reloaded", "plugin": record.to_dict()}


@app.post("/plugins/enable")
async def enable_plugin(request: PluginNameRequest):
    if request.plugin_name not in plugins:
        raise HTTPException(status_code=404, detail=f"Plugin '{request.plugin_name}' not found")
    plugins[request.plugin_name].enabled = True
    return {"success": True, "message": f"Plugin '{request.plugin_name}' enabled"}


@app.post("/plugins/disable")
async def disable_plugin(request: PluginNameRequest):
    if request.plugin_name not in plugins:
        raise HTTPException(status_code=404, detail=f"Plugin '{request.plugin_name}' not found")
    plugins[request.plugin_name].enabled = False
    return {"success": True, "message": f"Plugin '{request.plugin_name}' disabled"}


@app.delete("/plugins/{plugin_name}")
async def unload_plugin(plugin_name: str):
    if plugin_name not in plugins:
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_name}' not found")
    del plugins[plugin_name]
    return {"success": True, "message": f"Plugin '{plugin_name}' unloaded"}


@app.get("/plugins/{plugin_name}")
async def get_plugin(plugin_name: str):
    if plugin_name not in plugins:
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_name}' not found")
    return {"success": True, "plugin": plugins[plugin_name].to_dict()}


@app.post("/plugins/execute")
async def execute_plugin(request: ExecuteRequest):
    if request.plugin_name not in plugins:
        raise HTTPException(status_code=404, detail=f"Plugin '{request.plugin_name}' not found")
    record = plugins[request.plugin_name]
    if not record.enabled:
        raise HTTPException(status_code=400, detail=f"Plugin '{request.plugin_name}' is disabled")
    try:
        result = record.module.execute(request.params)
        if asyncio.iscoroutine(result):
            result = await result
        stats["execute_count"] += 1
        return {"success": True, "plugin": request.plugin_name, "result": result}
    except Exception as exc:
        logger.debug("Fallback triggered: %s", exc)
        stats["execute_errors"] += 1
        logger.error("Plugin execute error (%s): %s", request.plugin_name, exc)
        raise HTTPException(status_code=500, detail=str(exc))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
