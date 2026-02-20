"""
Node 49: OctoPrint 3D Printer Wrapper
UFO Galaxy 64-Core MCP Matrix - DeepSeek Audited Architecture

SECURITY: This node is in Layer 3 (Physical) and can ONLY be accessed by Node 50.
"""

import os
import asyncio
import logging
from typing import Dict, Optional
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn
import httpx

# =============================================================================
# Configuration
# =============================================================================

NODE_ID = os.getenv("NODE_ID", "49")
NODE_NAME = os.getenv("NODE_NAME", "OctoPrint")
ALLOWED_CALLER = os.getenv("ALLOWED_CALLER", "node_50_transformer")
OCTOPRINT_URL = os.getenv("OCTOPRINT_URL", "http://localhost:5000")
OCTOPRINT_API_KEY = os.getenv("OCTOPRINT_API_KEY", "")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format=f"[Node {NODE_ID}] %(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# =============================================================================
# Models
# =============================================================================

class PrintRequest(BaseModel):
    action: str = Field(..., description="Print action")
    params: Dict = Field(default={}, description="Action parameters")

class PrintResponse(BaseModel):
    success: bool
    data: Optional[Dict] = None
    error: Optional[str] = None
    execution_time_ms: float

class PrinterStatus(BaseModel):
    state: str
    temperature: Dict
    progress: Optional[Dict] = None
    job: Optional[Dict] = None

# =============================================================================
# OctoPrint Controller
# =============================================================================

class OctoPrintController:
    """
    OctoPrint Controller - Manages 3D printer operations.
    
    Supported actions:
    - print_start: Start printing a file
    - print_pause: Pause current print
    - print_resume: Resume paused print
    - print_cancel: Cancel current print
    - print_status: Get printer status
    - set_temperature: Set bed/nozzle temperature
    - home: Home axes
    - jog: Move print head
    """
    
    def __init__(self, octoprint_url: str, api_key: str):
        self.octoprint_url = octoprint_url.rstrip("/")
        self.api_key = api_key
        self.headers = {
            "X-Api-Key": api_key,
            "Content-Type": "application/json"
        }
        self.http_client = httpx.AsyncClient(timeout=30.0)
        self.mock_mode = not api_key  # Use mock mode if no API key
        
        # Mock state
        self.mock_state = {
            "state": "Operational",
            "temperature": {
                "bed": {"actual": 25.0, "target": 0.0},
                "tool0": {"actual": 25.0, "target": 0.0}
            },
            "progress": None,
            "job": None
        }
    
    async def execute(self, action: str, params: Dict) -> Dict:
        """Execute a print action."""
        if self.mock_mode:
            return await self._mock_execute(action, params)
        
        try:
            if action == "print_start":
                return await self._start_print(params)
            elif action == "print_pause":
                return await self._pause_print()
            elif action == "print_resume":
                return await self._resume_print()
            elif action == "print_cancel":
                return await self._cancel_print()
            elif action == "print_status":
                return await self._get_status()
            elif action == "set_temperature":
                return await self._set_temperature(params)
            elif action == "home":
                return await self._home(params)
            elif action == "jog":
                return await self._jog(params)
            elif action == "files":
                return await self._list_files()
            else:
                raise ValueError(f"Unknown action: {action}")
                
        except Exception as e:
            logger.error(f"OctoPrint action failed: {e}")
            return {"error": str(e), "success": False}
    
    async def _api_request(self, method: str, endpoint: str, data: Dict = None) -> Dict:
        """Make an API request to OctoPrint."""
        url = f"{self.octoprint_url}/api/{endpoint}"
        
        try:
            if method == "GET":
                response = await self.http_client.get(url, headers=self.headers)
            elif method == "POST":
                response = await self.http_client.post(url, headers=self.headers, json=data)
            else:
                raise ValueError(f"Unsupported method: {method}")
            
            if response.status_code >= 400:
                raise Exception(f"API error: {response.status_code} - {response.text}")
            
            return response.json() if response.text else {}
            
        except httpx.ConnectError:
            raise Exception("Cannot connect to OctoPrint")
    
    async def _start_print(self, params: Dict) -> Dict:
        """Start printing a file."""
        filename = params.get("filename")
        if not filename:
            raise ValueError("filename is required")
        
        # Select file
        await self._api_request("POST", f"files/local/{filename}", {"command": "select"})
        
        # Start print
        await self._api_request("POST", "job", {"command": "start"})
        
        return {
            "action": "print_start",
            "filename": filename,
            "success": True
        }
    
    async def _pause_print(self) -> Dict:
        """Pause current print."""
        await self._api_request("POST", "job", {"command": "pause", "action": "pause"})
        
        return {
            "action": "print_pause",
            "success": True
        }
    
    async def _resume_print(self) -> Dict:
        """Resume paused print."""
        await self._api_request("POST", "job", {"command": "pause", "action": "resume"})
        
        return {
            "action": "print_resume",
            "success": True
        }
    
    async def _cancel_print(self) -> Dict:
        """Cancel current print."""
        await self._api_request("POST", "job", {"command": "cancel"})
        
        return {
            "action": "print_cancel",
            "success": True
        }
    
    async def _get_status(self) -> Dict:
        """Get printer status."""
        printer = await self._api_request("GET", "printer")
        job = await self._api_request("GET", "job")
        
        return {
            "action": "print_status",
            "state": printer.get("state", {}).get("text", "Unknown"),
            "temperature": printer.get("temperature", {}),
            "progress": job.get("progress", {}),
            "job": job.get("job", {}),
            "success": True
        }
    
    async def _set_temperature(self, params: Dict) -> Dict:
        """Set temperature."""
        target = params.get("target", "bed")  # bed or tool0
        temp = params.get("temperature", 0)
        
        if target == "bed":
            await self._api_request("POST", "printer/bed", {"command": "target", "target": temp})
        else:
            await self._api_request("POST", "printer/tool", {"command": "target", "targets": {target: temp}})
        
        return {
            "action": "set_temperature",
            "target": target,
            "temperature": temp,
            "success": True
        }
    
    async def _home(self, params: Dict) -> Dict:
        """Home axes."""
        axes = params.get("axes", ["x", "y", "z"])
        
        await self._api_request("POST", "printer/printhead", {"command": "home", "axes": axes})
        
        return {
            "action": "home",
            "axes": axes,
            "success": True
        }
    
    async def _jog(self, params: Dict) -> Dict:
        """Jog print head."""
        x = params.get("x", 0)
        y = params.get("y", 0)
        z = params.get("z", 0)
        
        await self._api_request("POST", "printer/printhead", {
            "command": "jog",
            "x": x,
            "y": y,
            "z": z
        })
        
        return {
            "action": "jog",
            "movement": {"x": x, "y": y, "z": z},
            "success": True
        }
    
    async def _list_files(self) -> Dict:
        """List available files."""
        result = await self._api_request("GET", "files")
        
        files = []
        for file in result.get("files", []):
            files.append({
                "name": file.get("name"),
                "size": file.get("size"),
                "date": file.get("date")
            })
        
        return {
            "action": "files",
            "files": files,
            "success": True
        }
    
    async def _mock_execute(self, action: str, params: Dict) -> Dict:
        """Mock execution for testing."""
        logger.info(f"Mock executing: {action}")
        await asyncio.sleep(0.1)
        
        if action == "print_start":
            self.mock_state["state"] = "Printing"
            self.mock_state["job"] = {
                "file": {"name": params.get("filename", "test.gcode")},
                "estimatedPrintTime": 3600
            }
            self.mock_state["progress"] = {"completion": 0.0, "printTime": 0}
            
        elif action == "print_pause":
            self.mock_state["state"] = "Paused"
            
        elif action == "print_resume":
            self.mock_state["state"] = "Printing"
            
        elif action == "print_cancel":
            self.mock_state["state"] = "Operational"
            self.mock_state["job"] = None
            self.mock_state["progress"] = None
            
        elif action == "print_status":
            return {
                "action": "print_status",
                **self.mock_state,
                "mock": True,
                "success": True
            }
            
        elif action == "set_temperature":
            target = params.get("target", "bed")
            temp = params.get("temperature", 0)
            if target == "bed":
                self.mock_state["temperature"]["bed"]["target"] = temp
            else:
                self.mock_state["temperature"]["tool0"]["target"] = temp
        
        return {
            "action": action,
            "params": params,
            "mock": True,
            "success": True,
            "timestamp": datetime.now().isoformat()
        }

# =============================================================================
# FastAPI Application
# =============================================================================

octoprint_controller: Optional[OctoPrintController] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global octoprint_controller
    
    logger.info(f"Starting Node {NODE_ID}: {NODE_NAME}")
    logger.info(f"SECURITY: Only accepting requests from {ALLOWED_CALLER}")
    
    octoprint_controller = OctoPrintController(OCTOPRINT_URL, OCTOPRINT_API_KEY)
    
    if octoprint_controller.mock_mode:
        logger.warning("Running in MOCK MODE (no API key provided)")
    
    logger.info(f"Node {NODE_ID} ({NODE_NAME}) is ready")
    
    yield
    
    logger.info(f"Shutting down Node {NODE_ID}")

app = FastAPI(
    title=f"UFO Galaxy Node {NODE_ID}: {NODE_NAME}",
    description="OctoPrint 3D Printer Wrapper - Physical Layer Node (ISOLATED)",
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
        "mock_mode": octoprint_controller.mock_mode if octoprint_controller else True,
        "security": f"Only accessible by {ALLOWED_CALLER}"
    }

@app.post("/execute", response_model=PrintResponse)
async def execute_action(request: PrintRequest):
    """Execute a print action."""
    start_time = datetime.now()
    
    try:
        result = await octoprint_controller.execute(request.action, request.params)
        
        execution_time = (datetime.now() - start_time).total_seconds() * 1000
        
        return PrintResponse(
            success=result.get("success", True),
            data=result,
            execution_time_ms=execution_time
        )
        
    except Exception as e:
        execution_time = (datetime.now() - start_time).total_seconds() * 1000
        return PrintResponse(
            success=False,
            error=str(e),
            execution_time_ms=execution_time
        )

@app.get("/status")
async def get_status():
    """Get printer status."""
    return await octoprint_controller.execute("print_status", {})

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
            "print_start", "print_pause", "print_resume", "print_cancel",
            "print_status", "set_temperature", "home", "jog", "files"
        ]
    }

# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8049,
        reload=False,
        log_level=LOG_LEVEL.lower()
    )
