"""
Node 34: Scrcpy - Android 屏幕镜像与控制
=========================================
功能: 通过 scrcpy/adb 实现 Android 设备的屏幕镜像、截图、录屏、输入控制
依赖: adb (Android Debug Bridge), scrcpy (可选)
"""
import os
import subprocess
import shutil
import tempfile
import base64
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node 34 - Scrcpy", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# Configuration
# =============================================================================
ADB_PATH = shutil.which("adb") or os.getenv("ADB_PATH", "adb")
SCRCPY_PATH = shutil.which("scrcpy") or os.getenv("SCRCPY_PATH", "scrcpy")

# =============================================================================
# Helper Functions
# =============================================================================
def run_adb(args: List[str], device: Optional[str] = None, timeout: int = 30) -> Dict[str, Any]:
    """执行 ADB 命令"""
    cmd = [ADB_PATH]
    if device:
        cmd.extend(["-s", device])
    cmd.extend(args)
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "command": " ".join(cmd)
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Command timed out", "command": " ".join(cmd)}
    except FileNotFoundError:
        return {"success": False, "error": f"ADB not found at {ADB_PATH}", "command": " ".join(cmd)}
    except Exception as e:
        return {"success": False, "error": str(e), "command": " ".join(cmd)}

# =============================================================================
# Request Models
# =============================================================================
class DeviceRequest(BaseModel):
    device: Optional[str] = None

class TapRequest(BaseModel):
    device: Optional[str] = None
    x: int
    y: int

class SwipeRequest(BaseModel):
    device: Optional[str] = None
    x1: int
    y1: int
    x2: int
    y2: int
    duration: int = 300

class InputTextRequest(BaseModel):
    device: Optional[str] = None
    text: str

class KeyEventRequest(BaseModel):
    device: Optional[str] = None
    keycode: int

class ScreenshotRequest(BaseModel):
    device: Optional[str] = None
    output_path: Optional[str] = None

class ShellRequest(BaseModel):
    device: Optional[str] = None
    command: str

class InstallRequest(BaseModel):
    device: Optional[str] = None
    apk_path: str

# =============================================================================
# API Endpoints
# =============================================================================
@app.get("/health")
async def health():
    """健康检查"""
    adb_available = shutil.which("adb") is not None
    scrcpy_available = shutil.which("scrcpy") is not None
    return {
        "status": "healthy" if adb_available else "degraded",
        "node_id": "34",
        "name": "Scrcpy",
        "adb_available": adb_available,
        "scrcpy_available": scrcpy_available,
        "timestamp": datetime.now().isoformat()
    }

@app.get("/devices")
async def list_devices():
    """列出所有连接的 Android 设备"""
    result = run_adb(["devices", "-l"])
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Failed to list devices"))
    
    devices = []
    lines = result["stdout"].split("\n")[1:]
    for line in lines:
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) >= 2:
            device_info = {"id": parts[0], "status": parts[1]}
            for part in parts[2:]:
                if ":" in part:
                    key, value = part.split(":", 1)
                    device_info[key] = value
            devices.append(device_info)
    return {"success": True, "devices": devices, "count": len(devices)}

@app.post("/screenshot")
async def screenshot(request: ScreenshotRequest):
    """截取设备屏幕"""
    output_path = request.output_path or tempfile.mktemp(suffix=".png")
    cmd = [ADB_PATH]
    if request.device:
        cmd.extend(["-s", request.device])
    cmd.extend(["exec-out", "screencap", "-p"])
    
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=10)
        if result.returncode == 0 and result.stdout:
            with open(output_path, "wb") as f:
                f.write(result.stdout)
            return {"success": True, "path": output_path, "size": len(result.stdout)}
        else:
            raise HTTPException(status_code=500, detail="Screenshot failed")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/tap")
async def tap(request: TapRequest):
    """点击屏幕指定位置"""
    result = run_adb(["shell", "input", "tap", str(request.x), str(request.y)], device=request.device)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Tap failed"))
    return {"success": True, "x": request.x, "y": request.y, "action": "tap"}

@app.post("/swipe")
async def swipe(request: SwipeRequest):
    """滑动屏幕"""
    result = run_adb([
        "shell", "input", "swipe",
        str(request.x1), str(request.y1),
        str(request.x2), str(request.y2),
        str(request.duration)
    ], device=request.device)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Swipe failed"))
    return {"success": True, "from": {"x": request.x1, "y": request.y1}, "to": {"x": request.x2, "y": request.y2}}

@app.post("/input_text")
async def input_text(request: InputTextRequest):
    """输入文本"""
    escaped_text = request.text.replace(" ", "%s").replace("'", "\\'")
    result = run_adb(["shell", "input", "text", escaped_text], device=request.device)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Input text failed"))
    return {"success": True, "text": request.text, "action": "input_text"}

@app.post("/key_event")
async def key_event(request: KeyEventRequest):
    """发送按键事件 (3=HOME, 4=BACK, 24=VOL_UP, 25=VOL_DOWN, 26=POWER)"""
    result = run_adb(["shell", "input", "keyevent", str(request.keycode)], device=request.device)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Key event failed"))
    return {"success": True, "keycode": request.keycode, "action": "key_event"}

@app.post("/press_home")
async def press_home(request: DeviceRequest):
    """按 HOME 键"""
    return await key_event(KeyEventRequest(device=request.device, keycode=3))

@app.post("/press_back")
async def press_back(request: DeviceRequest):
    """按返回键"""
    return await key_event(KeyEventRequest(device=request.device, keycode=4))

@app.post("/shell")
async def shell_command(request: ShellRequest):
    """执行 shell 命令"""
    result = run_adb(["shell", request.command], device=request.device, timeout=60)
    return result

@app.post("/install")
async def install_apk(request: InstallRequest):
    """安装 APK"""
    if not os.path.exists(request.apk_path):
        raise HTTPException(status_code=404, detail=f"APK not found: {request.apk_path}")
    result = run_adb(["install", "-r", request.apk_path], device=request.device, timeout=120)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Install failed"))
    return {"success": True, "apk": request.apk_path, "action": "install"}

@app.get("/packages")
async def list_packages(device: Optional[str] = None):
    """列出已安装的应用"""
    result = run_adb(["shell", "pm", "list", "packages"], device=device)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Failed"))
    packages = [line.replace("package:", "") for line in result["stdout"].split("\n") if line.startswith("package:")]
    return {"success": True, "packages": packages, "count": len(packages)}

@app.get("/device_info")
async def device_info(device: Optional[str] = None):
    """获取设备信息"""
    info = {}
    result = run_adb(["shell", "getprop", "ro.product.model"], device=device)
    if result["success"]:
        info["model"] = result["stdout"]
    result = run_adb(["shell", "getprop", "ro.build.version.release"], device=device)
    if result["success"]:
        info["android_version"] = result["stdout"]
    result = run_adb(["shell", "wm", "size"], device=device)
    if result["success"]:
        info["screen_size"] = result["stdout"].replace("Physical size: ", "")
    return {"success": True, "device": device, "info": info}

@app.post("/mcp/call")
async def mcp_call(request: dict):
    """MCP 工具调用接口"""
    tool = request.get("tool", "")
    params = request.get("params", {})
    
    if tool == "devices":
        return await list_devices()
    elif tool == "screenshot":
        return await screenshot(ScreenshotRequest(**params))
    elif tool == "tap":
        return await tap(TapRequest(**params))
    elif tool == "swipe":
        return await swipe(SwipeRequest(**params))
    elif tool == "input_text":
        return await input_text(InputTextRequest(**params))
    elif tool == "key_event":
        return await key_event(KeyEventRequest(**params))
    elif tool == "press_home":
        return await press_home(DeviceRequest(**params))
    elif tool == "press_back":
        return await press_back(DeviceRequest(**params))
    elif tool == "shell":
        return await shell_command(ShellRequest(**params))
    elif tool == "install":
        return await install_apk(InstallRequest(**params))
    elif tool == "packages":
        return await list_packages(params.get("device"))
    elif tool == "device_info":
        return await device_info(params.get("device"))
    else:
        raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8034)
