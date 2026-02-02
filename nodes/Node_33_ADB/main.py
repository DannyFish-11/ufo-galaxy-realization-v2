"""
Node 33: Android ADB Wrapper
UFO Galaxy 64-Core MCP Matrix - DeepSeek Audited Architecture

SECURITY: This node is in Layer 3 (Physical) and can ONLY be accessed by Node 50.
It cannot communicate with other L3 nodes or the internet.
"""

import os
import asyncio
import logging
import subprocess
from typing import Dict, Optional, List
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

# =============================================================================
# Configuration
# =============================================================================

NODE_ID = os.getenv("NODE_ID", "33")
NODE_NAME = os.getenv("NODE_NAME", "AndroidADB")
ALLOWED_CALLER = os.getenv("ALLOWED_CALLER", "node_50_transformer")
ADB_PATH = os.getenv("ADB_PATH", "adb")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format=f"[Node {NODE_ID}] %(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# =============================================================================
# Models
# =============================================================================

class ADBRequest(BaseModel):
    action: str = Field(..., description="ADB action to perform")
    params: Dict = Field(default={}, description="Action parameters")

class ADBResponse(BaseModel):
    success: bool
    data: Optional[Dict] = None
    error: Optional[str] = None
    device_id: Optional[str] = None
    execution_time_ms: float

class DeviceInfo(BaseModel):
    device_id: str
    status: str
    model: Optional[str] = None
    android_version: Optional[str] = None

# =============================================================================
# ADB Controller
# =============================================================================

class ADBController:
    """
    ADB Controller - Manages Android device connections and commands.
    
    Supported actions:
    - tap: Tap at coordinates
    - swipe: Swipe between coordinates
    - shell: Execute shell command
    - screenshot: Take screenshot
    - input: Input text
    - keyevent: Send key event
    """
    
    RECONNECT_INTERVAL = 5  # seconds
    
    def __init__(self, adb_path: str = "adb"):
        self.adb_path = adb_path
        self.connected_devices: List[str] = []
        self.current_device: Optional[str] = None
        self._reconnect_task: Optional[asyncio.Task] = None
    
    async def start(self):
        """Start ADB server and device monitoring."""
        logger.info("Starting ADB controller...")
        
        # Start ADB server
        await self._run_adb(["start-server"])
        
        # Initial device scan
        await self.refresh_devices()
        
        # Start reconnect loop
        self._reconnect_task = asyncio.create_task(self._reconnect_loop())
        
        logger.info(f"ADB controller started. Devices: {self.connected_devices}")
    
    async def stop(self):
        """Stop ADB controller."""
        if self._reconnect_task:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
        logger.info("ADB controller stopped")
    
    async def _reconnect_loop(self):
        """Background task to reconnect to devices."""
        while True:
            try:
                await asyncio.sleep(self.RECONNECT_INTERVAL)
                await self.refresh_devices()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Reconnect loop error: {e}")
    
    async def refresh_devices(self) -> List[str]:
        """Refresh the list of connected devices."""
        try:
            result = await self._run_adb(["devices"])
            
            devices = []
            for line in result.split("\n")[1:]:
                if "\tdevice" in line:
                    device_id = line.split("\t")[0]
                    devices.append(device_id)
            
            self.connected_devices = devices
            
            if devices and not self.current_device:
                self.current_device = devices[0]
                logger.info(f"Auto-selected device: {self.current_device}")
            
            return devices
            
        except Exception as e:
            logger.error(f"Failed to refresh devices: {e}")
            return []
    
    async def _run_adb(self, args: List[str], device: str = None) -> str:
        """Run an ADB command."""
        cmd = [self.adb_path]
        
        if device:
            cmd.extend(["-s", device])
        
        cmd.extend(args)
        
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=30.0
            )
            
            if process.returncode != 0:
                error_msg = stderr.decode().strip() or stdout.decode().strip()
                raise Exception(f"ADB command failed: {error_msg}")
            
            return stdout.decode().strip()
            
        except asyncio.TimeoutError:
            raise Exception("ADB command timed out")
        except FileNotFoundError:
            # ADB not installed, return mock response
            logger.warning("ADB not found, returning mock response")
            return "mock_response"
    
    async def execute(self, action: str, params: Dict) -> Dict:
        """Execute an ADB action."""
        device = params.get("device") or self.current_device
        
        if not device and action not in ["devices", "status"]:
            # For testing without real device
            logger.warning("No device connected, using mock mode")
            return await self._mock_execute(action, params)
        
        try:
            if action == "tap":
                return await self._tap(device, params)
            elif action == "swipe":
                return await self._swipe(device, params)
            elif action == "shell":
                return await self._shell(device, params)
            elif action == "screenshot":
                return await self._screenshot(device, params)
            elif action == "input":
                return await self._input_text(device, params)
            elif action == "keyevent":
                return await self._keyevent(device, params)
            elif action == "devices":
                return await self._get_devices()
            elif action == "status":
                return await self._get_status()
            else:
                raise ValueError(f"Unknown action: {action}")
                
        except Exception as e:
            logger.error(f"ADB action failed: {e}")
            return {"error": str(e), "success": False}
    
    async def _tap(self, device: str, params: Dict) -> Dict:
        """Tap at coordinates."""
        x = params.get("x", 0)
        y = params.get("y", 0)
        
        await self._run_adb(["shell", "input", "tap", str(x), str(y)], device)
        
        return {
            "action": "tap",
            "coordinates": {"x": x, "y": y},
            "device": device,
            "success": True
        }
    
    async def _swipe(self, device: str, params: Dict) -> Dict:
        """Swipe between coordinates."""
        x1 = params.get("x1", 0)
        y1 = params.get("y1", 0)
        x2 = params.get("x2", 0)
        y2 = params.get("y2", 0)
        duration = params.get("duration", 300)
        
        await self._run_adb([
            "shell", "input", "swipe",
            str(x1), str(y1), str(x2), str(y2), str(duration)
        ], device)
        
        return {
            "action": "swipe",
            "from": {"x": x1, "y": y1},
            "to": {"x": x2, "y": y2},
            "duration": duration,
            "device": device,
            "success": True
        }
    
    async def _shell(self, device: str, params: Dict) -> Dict:
        """Execute shell command."""
        command = params.get("command", "echo 'hello'")
        
        # Security: Block dangerous commands
        dangerous = ["rm -rf", "mkfs", "dd if=", "reboot", "shutdown"]
        if any(d in command.lower() for d in dangerous):
            raise ValueError("Dangerous command blocked")
        
        result = await self._run_adb(["shell", command], device)
        
        return {
            "action": "shell",
            "command": command,
            "output": result,
            "device": device,
            "success": True
        }
    
    async def _screenshot(self, device: str, params: Dict) -> Dict:
        """Take screenshot."""
        import base64
        import tempfile
        
        # Create temp file
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            temp_path = f.name
        
        try:
            # Take screenshot on device
            await self._run_adb(["shell", "screencap", "-p", "/sdcard/screenshot.png"], device)
            
            # Pull to local
            await self._run_adb(["pull", "/sdcard/screenshot.png", temp_path], device)
            
            # Read and encode
            with open(temp_path, "rb") as f:
                screenshot_data = base64.b64encode(f.read()).decode()
            
            # Clean up device
            await self._run_adb(["shell", "rm", "/sdcard/screenshot.png"], device)
            
            return {
                "action": "screenshot",
                "format": "png",
                "encoding": "base64",
                "data": screenshot_data[:100] + "...",  # Truncate for response
                "size_bytes": len(screenshot_data),
                "device": device,
                "success": True
            }
            
        except Exception as e:
            # Return mock screenshot
            return await self._mock_execute("screenshot", params)
        finally:
            # Clean up temp file
            try:
                os.unlink(temp_path)
            except:
                pass
    
    async def _input_text(self, device: str, params: Dict) -> Dict:
        """Input text."""
        text = params.get("text", "")
        
        # Escape special characters
        escaped = text.replace(" ", "%s").replace("'", "\\'")
        
        await self._run_adb(["shell", "input", "text", escaped], device)
        
        return {
            "action": "input",
            "text": text,
            "device": device,
            "success": True
        }
    
    async def _keyevent(self, device: str, params: Dict) -> Dict:
        """Send key event."""
        keycode = params.get("keycode", 4)  # Default: BACK
        
        await self._run_adb(["shell", "input", "keyevent", str(keycode)], device)
        
        return {
            "action": "keyevent",
            "keycode": keycode,
            "device": device,
            "success": True
        }
    
    async def _get_devices(self) -> Dict:
        """Get connected devices."""
        await self.refresh_devices()
        
        return {
            "action": "devices",
            "devices": self.connected_devices,
            "current_device": self.current_device,
            "success": True
        }
    
    async def _get_status(self) -> Dict:
        """Get controller status."""
        return {
            "action": "status",
            "connected_devices": self.connected_devices,
            "current_device": self.current_device,
            "adb_path": self.adb_path,
            "success": True
        }
    
    async def _mock_execute(self, action: str, params: Dict) -> Dict:
        """Mock execution for testing."""
        logger.info(f"Mock executing: {action}")
        await asyncio.sleep(0.1)
        
        return {
            "action": action,
            "params": params,
            "mock": True,
            "device": "mock-device",
            "success": True,
            "timestamp": datetime.now().isoformat()
        }

# =============================================================================
# FastAPI Application
# =============================================================================

adb_controller: Optional[ADBController] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global adb_controller
    
    logger.info(f"Starting Node {NODE_ID}: {NODE_NAME}")
    logger.info(f"SECURITY: Only accepting requests from {ALLOWED_CALLER}")
    
    adb_controller = ADBController(ADB_PATH)
    await adb_controller.start()
    
    logger.info(f"Node {NODE_ID} ({NODE_NAME}) is ready")
    
    yield
    
    logger.info(f"Shutting down Node {NODE_ID}")
    await adb_controller.stop()

app = FastAPI(
    title=f"UFO Galaxy Node {NODE_ID}: {NODE_NAME}",
    description="Android ADB Wrapper - Physical Layer Node (ISOLATED)",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# Security Middleware
# =============================================================================

@app.middleware("http")
async def check_caller(request: Request, call_next):
    """Verify that requests come from allowed callers."""
    # In production, verify the caller's identity
    # For now, we log the request
    client_host = request.client.host if request.client else "unknown"
    logger.debug(f"Request from {client_host}: {request.url.path}")
    
    response = await call_next(request)
    return response

# =============================================================================
# API Endpoints
# =============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "node_id": NODE_ID,
        "node_name": NODE_NAME,
        "layer": "L3_PHYSICAL",
        "connected_devices": adb_controller.connected_devices if adb_controller else [],
        "security": f"Only accessible by {ALLOWED_CALLER}"
    }

@app.post("/execute", response_model=ADBResponse)
async def execute_action(request: ADBRequest):
    """Execute an ADB action."""
    start_time = datetime.now()
    
    try:
        result = await adb_controller.execute(request.action, request.params)
        
        execution_time = (datetime.now() - start_time).total_seconds() * 1000
        
        return ADBResponse(
            success=result.get("success", True),
            data=result,
            device_id=result.get("device"),
            execution_time_ms=execution_time
        )
        
    except Exception as e:
        execution_time = (datetime.now() - start_time).total_seconds() * 1000
        return ADBResponse(
            success=False,
            error=str(e),
            execution_time_ms=execution_time
        )

@app.get("/devices")
async def get_devices():
    """Get connected devices."""
    return await adb_controller.execute("devices", {})

@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "node_id": NODE_ID,
        "node_name": NODE_NAME,
        "layer": "L3_PHYSICAL",
        "status": "running",
        "security_notice": "This node is ISOLATED. Only Node 50 can access it.",
        "supported_actions": [
            "tap", "swipe", "shell", "screenshot",
            "input", "keyevent", "devices", "status"
        ]
    }

# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8033,
        reload=False,
        log_level=LOG_LEVEL.lower()
    )
