"""
Node 35: AppleScript - macOS Automation
"""
import os
import sys
import subprocess
import platform
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from nodes.common.cors_config import get_cors_origins

try:
    from core.port_config import get_node_port
    PORT = get_node_port("Node_35_AppleScript")
except Exception as exc:
    logger.debug("Fallback triggered: %s", exc)
    PORT = int(os.getenv("PORT", "8035"))

IS_MACOS = platform.system() == "Darwin"

app = FastAPI(title="Node 35 - AppleScript", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=get_cors_origins(), allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

class ExecuteRequest(BaseModel):
    script: str
    timeout: int = 30

class ExecuteFileRequest(BaseModel):
    file_path: str
    timeout: int = 30

class NotifyRequest(BaseModel):
    message: str
    title: str = "Galaxy Notification"
    subtitle: Optional[str] = None
    sound: str = "default"

def run_osascript(script: str, timeout: int = 30) -> dict:
    if not IS_MACOS:
        return {"success": False, "error": "AppleScript requires macOS"}
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=timeout
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "returncode": result.returncode
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"Script timed out after {timeout}s"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/health")
async def health():
    return {
        "status": "healthy" if IS_MACOS else "degraded",
        "node_id": "35",
        "name": "AppleScript",
        "macos": IS_MACOS,
        "degraded": not IS_MACOS,
        "degraded_reason": None if IS_MACOS else "Not running on macOS",
        "timestamp": datetime.now().isoformat()
    }

@app.get("/status")
async def status():
    return {
        "status": "running",
        "node_id": "35",
        "name": "AppleScript",
        "macos": IS_MACOS,
        "platform": platform.system(),
        "timestamp": datetime.now().isoformat()
    }

@app.post("/execute")
async def execute(request: ExecuteRequest):
    return run_osascript(request.script, request.timeout)

@app.post("/execute_file")
async def execute_file(request: ExecuteFileRequest):
    if not IS_MACOS:
        return {"success": False, "error": "AppleScript requires macOS"}
    if not os.path.exists(request.file_path):
        return {"success": False, "error": f"File not found: {request.file_path}"}
    try:
        result = subprocess.run(
            ["osascript", request.file_path],
            capture_output=True, text=True, timeout=request.timeout
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "returncode": result.returncode
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"Script timed out after {request.timeout}s"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/apps")
async def list_apps():
    script = 'tell application "System Events" to get name of every process where background only is false'
    result = run_osascript(script)
    if result["success"]:
        apps = [a.strip() for a in result["stdout"].split(",") if a.strip()]
        return {"success": True, "apps": apps, "count": len(apps)}
    return result

@app.post("/notify")
async def notify(request: NotifyRequest):
    parts = [f'display notification "{request.message}"']
    parts.append(f'with title "{request.title}"')
    if request.subtitle:
        parts.append(f'subtitle "{request.subtitle}"')
    if request.sound:
        parts.append(f'sound name "{request.sound}"')
    script = " ".join(parts)
    return run_osascript(script)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
