"""
Node 30: Reserved - Plugin Framework Service
"""
import os
import sys
import asyncio
import importlib.util
from datetime import datetime
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from nodes.common.cors_config import get_cors_origins

try:
    from core.port_config import get_node_port
    PORT = get_node_port("Node_30_Reserved")
except Exception:
    PORT = int(os.getenv("PORT", "8030"))

app = FastAPI(title="Node 30 - Plugin Framework", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=get_cors_origins(), allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# In-memory plugin registry
plugins: Dict[str, Dict[str, Any]] = {}

class LoadPluginRequest(BaseModel):
    path: str
    name: Optional[str] = None

class ExecutePluginRequest(BaseModel):
    name: str
    action: str = "execute"
    params: Optional[Dict[str, Any]] = None

class UnloadPluginRequest(BaseModel):
    name: str

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "node_id": "30",
        "name": "Plugin Framework",
        "loaded_plugins": len(plugins),
        "timestamp": datetime.now().isoformat()
    }

@app.get("/status")
async def status():
    return {
        "status": "running",
        "node_id": "30",
        "name": "Plugin Framework",
        "plugins": {name: {"path": p["path"], "loaded_at": p["loaded_at"]} for name, p in plugins.items()},
        "timestamp": datetime.now().isoformat()
    }

@app.get("/plugins")
async def list_plugins():
    return {
        "plugins": [
            {"name": name, "path": p["path"], "loaded_at": p["loaded_at"], "has_execute": p["has_execute"]}
            for name, p in plugins.items()
        ],
        "count": len(plugins)
    }

@app.post("/plugins/load")
async def load_plugin(request: LoadPluginRequest):
    if not os.path.exists(request.path):
        return {"success": False, "error": f"Plugin file not found: {request.path}"}
    try:
        module_name = request.name or os.path.splitext(os.path.basename(request.path))[0]
        spec = importlib.util.spec_from_file_location(module_name, request.path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        plugins[module_name] = {
            "module": module,
            "path": request.path,
            "loaded_at": datetime.now().isoformat(),
            "has_execute": hasattr(module, "execute")
        }
        return {"success": True, "name": module_name, "path": request.path}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/plugins/execute")
async def execute_plugin(request: ExecutePluginRequest):
    if request.name not in plugins:
        return {"success": False, "error": f"Plugin '{request.name}' not loaded"}
    try:
        module = plugins[request.name]["module"]
        params = request.params or {}
        if hasattr(module, request.action):
            fn = getattr(module, request.action)
            if asyncio.iscoroutinefunction(fn):
                result = await fn(**params)
            else:
                result = fn(**params)
            return {"success": True, "result": result}
        elif hasattr(module, "execute"):
            fn = module.execute
            if asyncio.iscoroutinefunction(fn):
                result = await fn(action=request.action, **params)
            else:
                result = fn(action=request.action, **params)
            return {"success": True, "result": result}
        else:
            return {"success": False, "error": f"Plugin '{request.name}' has no '{request.action}' method"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/plugins/unload")
async def unload_plugin(request: UnloadPluginRequest):
    if request.name not in plugins:
        return {"success": False, "error": f"Plugin '{request.name}' not loaded"}
    del plugins[request.name]
    return {"success": True, "name": request.name}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
