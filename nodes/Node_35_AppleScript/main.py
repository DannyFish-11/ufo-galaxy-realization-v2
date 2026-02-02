"""
Node 35: AppleScript - macOS 自动化
"""
import os, subprocess, platform
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node 35 - AppleScript", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

IS_MACOS = platform.system() == "Darwin"

def run_osascript(script: str, timeout: int = 30):
    if not IS_MACOS:
        return {"success": False, "error": "AppleScript only works on macOS"}
    try:
        result = subprocess.run(["/usr/bin/osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
        return {"success": result.returncode == 0, "output": result.stdout.strip(), "error": result.stderr.strip() if result.returncode != 0 else None}
    except Exception as e:
        return {"success": False, "error": str(e)}

class ScriptRequest(BaseModel):
    script: str
    timeout: int = 30

class NotificationRequest(BaseModel):
    title: str
    message: str

class AppRequest(BaseModel):
    app_name: str

@app.get("/health")
async def health():
    return {"status": "healthy" if IS_MACOS else "unavailable", "node_id": "35", "name": "AppleScript", "is_macos": IS_MACOS, "timestamp": datetime.now().isoformat()}

@app.post("/execute")
async def execute_script(request: ScriptRequest):
    result = run_osascript(request.script, request.timeout)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error"))
    return result

@app.post("/notification")
async def show_notification(request: NotificationRequest):
    script = f'display notification "{request.message}" with title "{request.title}"'
    return run_osascript(script)

@app.post("/open_app")
async def open_app(request: AppRequest):
    script = f'tell application "{request.app_name}" to activate'
    return run_osascript(script)

@app.post("/quit_app")
async def quit_app(request: AppRequest):
    script = f'tell application "{request.app_name}" to quit'
    return run_osascript(script)

@app.get("/running_apps")
async def get_running_apps():
    script = 'tell application "System Events" to get name of every process whose background only is false'
    result = run_osascript(script)
    if result["success"]:
        apps = result["output"].split(", ") if result["output"] else []
        return {"success": True, "apps": apps}
    return result

@app.post("/say")
async def say_text(text: str, voice: Optional[str] = None):
    script = f'say "{text}"'
    if voice:
        script += f' using "{voice}"'
    return run_osascript(script, timeout=60)

@app.get("/clipboard")
async def get_clipboard():
    return run_osascript("the clipboard")

@app.post("/clipboard")
async def set_clipboard(content: str):
    return run_osascript(f'set the clipboard to "{content}"')

@app.post("/mcp/call")
async def mcp_call(request: dict):
    tool = request.get("tool", "")
    params = request.get("params", {})
    if tool == "execute": return await execute_script(ScriptRequest(**params))
    elif tool == "notification": return await show_notification(NotificationRequest(**params))
    elif tool == "open_app": return await open_app(AppRequest(**params))
    elif tool == "quit_app": return await quit_app(AppRequest(**params))
    elif tool == "running_apps": return await get_running_apps()
    elif tool == "say": return await say_text(params.get("text", ""), params.get("voice"))
    elif tool == "clipboard": return await get_clipboard() if not params.get("content") else await set_clipboard(params["content"])
    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8035)
