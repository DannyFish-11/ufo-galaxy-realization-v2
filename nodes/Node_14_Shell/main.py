"""
Node 14: Shell Operations
UFO Galaxy 64-Core MCP Matrix - Core Tool Node

Provides comprehensive shell/command execution:
- Command execution (sync and async)
- Process management
- Environment variable handling
- Working directory management
- Output streaming
- Timeout handling

Author: UFO Galaxy Team
Version: 5.0.0
"""

import os
import sys
import json
import asyncio
import logging
import subprocess
import signal
import shlex
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
from datetime import datetime
from dataclasses import dataclass, asdict
from enum import Enum

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

# =============================================================================
# Configuration
# =============================================================================

NODE_ID = os.getenv("NODE_ID", "14")
NODE_NAME = os.getenv("NODE_NAME", "ShellOperations")
NODE_PORT = int(os.getenv("NODE_PORT", "8014"))
STATE_MACHINE_URL = os.getenv("STATE_MACHINE_URL", "http://localhost:8000")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
DEFAULT_TIMEOUT = int(os.getenv("DEFAULT_TIMEOUT", "300"))
DEFAULT_SHELL = os.getenv("DEFAULT_SHELL", "/bin/bash")
WORKSPACE_ROOT = os.getenv("WORKSPACE_ROOT", "/home/ubuntu")

# Security: blocked commands
BLOCKED_COMMANDS = [
    "rm -rf /",
    "mkfs",
    "dd if=/dev/zero",
    ":(){:|:&};:",  # Fork bomb
]

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format=f"[Node {NODE_ID}] %(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# =============================================================================
# Data Models
# =============================================================================

class ExecuteRequest(BaseModel):
    command: str
    args: Optional[List[str]] = None
    cwd: Optional[str] = None
    env: Optional[Dict[str, str]] = None
    timeout: int = DEFAULT_TIMEOUT
    shell: bool = True
    capture_output: bool = True
    stream_output: bool = False


class ScriptRequest(BaseModel):
    script: str
    interpreter: str = "/bin/bash"
    cwd: Optional[str] = None
    env: Optional[Dict[str, str]] = None
    timeout: int = DEFAULT_TIMEOUT


class ProcessInfo(BaseModel):
    pid: int
    command: str
    status: str
    started_at: str


class KillRequest(BaseModel):
    pid: int
    signal: int = 15  # SIGTERM


# =============================================================================
# Shell Operations Service
# =============================================================================

class ShellService:
    """Core shell operations service."""
    
    def __init__(self, workspace_root: str = WORKSPACE_ROOT):
        self.workspace_root = Path(workspace_root)
        self._running_processes: Dict[int, asyncio.subprocess.Process] = {}
        self._process_info: Dict[int, ProcessInfo] = {}
        logger.info(f"ShellService initialized with workspace: {self.workspace_root}")
    
    def _is_command_safe(self, command: str) -> bool:
        """Check if command is safe to execute."""
        command_lower = command.lower().strip()
        
        for blocked in BLOCKED_COMMANDS:
            if blocked.lower() in command_lower:
                return False
        
        return True
    
    def _resolve_cwd(self, cwd: Optional[str]) -> str:
        """Resolve working directory."""
        if cwd:
            p = Path(cwd)
            if not p.is_absolute():
                p = self.workspace_root / p
            return str(p)
        return str(self.workspace_root)
    
    async def execute(self, request: ExecuteRequest) -> Dict[str, Any]:
        """Execute shell command."""
        # Security check
        if not self._is_command_safe(request.command):
            return {
                "success": False,
                "error": "Command blocked for security reasons",
                "command": request.command
            }
        
        cwd = self._resolve_cwd(request.cwd)
        
        # Prepare environment
        env = os.environ.copy()
        if request.env:
            env.update(request.env)
        
        # Build command
        if request.shell:
            if request.args:
                cmd = f"{request.command} {' '.join(shlex.quote(a) for a in request.args)}"
            else:
                cmd = request.command
        else:
            cmd = [request.command] + (request.args or [])
        
        logger.info(f"Executing: {cmd} in {cwd}")
        
        try:
            start_time = datetime.now()
            
            if request.shell:
                process = await asyncio.create_subprocess_shell(
                    cmd,
                    stdout=asyncio.subprocess.PIPE if request.capture_output else None,
                    stderr=asyncio.subprocess.PIPE if request.capture_output else None,
                    cwd=cwd,
                    env=env
                )
            else:
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE if request.capture_output else None,
                    stderr=asyncio.subprocess.PIPE if request.capture_output else None,
                    cwd=cwd,
                    env=env
                )
            
            # Track process
            self._running_processes[process.pid] = process
            self._process_info[process.pid] = ProcessInfo(
                pid=process.pid,
                command=request.command,
                status="running",
                started_at=start_time.isoformat()
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=request.timeout
                )
                
                end_time = datetime.now()
                elapsed = (end_time - start_time).total_seconds()
                
                # Update process info
                self._process_info[process.pid].status = "completed"
                
                return {
                    "success": process.returncode == 0,
                    "return_code": process.returncode,
                    "stdout": stdout.decode('utf-8', errors='replace') if stdout else "",
                    "stderr": stderr.decode('utf-8', errors='replace') if stderr else "",
                    "command": request.command,
                    "cwd": cwd,
                    "elapsed_seconds": elapsed,
                    "pid": process.pid
                }
                
            except asyncio.TimeoutError:
                # Kill process on timeout
                process.kill()
                await process.wait()
                
                self._process_info[process.pid].status = "timeout"
                
                return {
                    "success": False,
                    "error": f"Command timed out after {request.timeout} seconds",
                    "command": request.command,
                    "pid": process.pid
                }
            
            finally:
                # Cleanup
                if process.pid in self._running_processes:
                    del self._running_processes[process.pid]
                
        except Exception as e:
            logger.error(f"Execute error: {e}")
            return {
                "success": False,
                "error": str(e),
                "command": request.command
            }
    
    async def execute_script(self, request: ScriptRequest) -> Dict[str, Any]:
        """Execute multi-line script."""
        cwd = self._resolve_cwd(request.cwd)
        
        # Prepare environment
        env = os.environ.copy()
        if request.env:
            env.update(request.env)
        
        logger.info(f"Executing script with {request.interpreter}")
        
        try:
            start_time = datetime.now()
            
            process = await asyncio.create_subprocess_exec(
                request.interpreter,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(input=request.script.encode()),
                    timeout=request.timeout
                )
                
                end_time = datetime.now()
                elapsed = (end_time - start_time).total_seconds()
                
                return {
                    "success": process.returncode == 0,
                    "return_code": process.returncode,
                    "stdout": stdout.decode('utf-8', errors='replace'),
                    "stderr": stderr.decode('utf-8', errors='replace'),
                    "interpreter": request.interpreter,
                    "elapsed_seconds": elapsed
                }
                
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                
                return {
                    "success": False,
                    "error": f"Script timed out after {request.timeout} seconds"
                }
                
        except Exception as e:
            logger.error(f"Script error: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def execute_background(self, request: ExecuteRequest) -> Dict[str, Any]:
        """Execute command in background."""
        if not self._is_command_safe(request.command):
            return {
                "success": False,
                "error": "Command blocked for security reasons"
            }
        
        cwd = self._resolve_cwd(request.cwd)
        
        env = os.environ.copy()
        if request.env:
            env.update(request.env)
        
        try:
            if request.args:
                cmd = f"{request.command} {' '.join(shlex.quote(a) for a in request.args)}"
            else:
                cmd = request.command
            
            process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                cwd=cwd,
                env=env,
                start_new_session=True
            )
            
            self._running_processes[process.pid] = process
            self._process_info[process.pid] = ProcessInfo(
                pid=process.pid,
                command=request.command,
                status="running",
                started_at=datetime.now().isoformat()
            )
            
            return {
                "success": True,
                "pid": process.pid,
                "command": request.command,
                "message": "Process started in background"
            }
            
        except Exception as e:
            logger.error(f"Background execute error: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def kill_process(self, request: KillRequest) -> Dict[str, Any]:
        """Kill a running process."""
        try:
            os.kill(request.pid, request.signal)
            
            if request.pid in self._process_info:
                self._process_info[request.pid].status = "killed"
            
            return {
                "success": True,
                "pid": request.pid,
                "signal": request.signal
            }
        except ProcessLookupError:
            return {
                "success": False,
                "error": f"Process {request.pid} not found"
            }
        except PermissionError:
            return {
                "success": False,
                "error": f"Permission denied to kill process {request.pid}"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def list_processes(self) -> Dict[str, Any]:
        """List tracked processes."""
        processes = []
        for pid, info in self._process_info.items():
            processes.append(info.dict())
        
        return {
            "success": True,
            "count": len(processes),
            "processes": processes
        }
    
    def get_env(self, key: Optional[str] = None) -> Dict[str, Any]:
        """Get environment variables."""
        if key:
            value = os.environ.get(key)
            return {
                "success": True,
                "key": key,
                "value": value,
                "exists": value is not None
            }
        else:
            return {
                "success": True,
                "environment": dict(os.environ)
            }
    
    async def which(self, command: str) -> Dict[str, Any]:
        """Find command location."""
        try:
            result = await self.execute(ExecuteRequest(
                command=f"which {shlex.quote(command)}",
                timeout=10
            ))
            
            if result["success"]:
                return {
                    "success": True,
                    "command": command,
                    "path": result["stdout"].strip()
                }
            else:
                return {
                    "success": False,
                    "command": command,
                    "error": "Command not found"
                }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }


# =============================================================================
# FastAPI Application
# =============================================================================

app = FastAPI(
    title=f"Node {NODE_ID}: {NODE_NAME}",
    description="Shell operations service for UFO Galaxy",
    version="5.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

shell_service = ShellService()


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "node_id": NODE_ID,
        "node_name": NODE_NAME,
        "timestamp": datetime.now().isoformat()
    }


@app.post("/execute")
async def execute_command(request: ExecuteRequest):
    """Execute shell command."""
    return await shell_service.execute(request)


@app.post("/script")
async def execute_script(request: ScriptRequest):
    """Execute multi-line script."""
    return await shell_service.execute_script(request)


@app.post("/background")
async def execute_background(request: ExecuteRequest):
    """Execute command in background."""
    return await shell_service.execute_background(request)


@app.post("/kill")
async def kill_process(request: KillRequest):
    """Kill a running process."""
    return await shell_service.kill_process(request)


@app.get("/processes")
async def list_processes():
    """List tracked processes."""
    return shell_service.list_processes()


@app.get("/env")
async def get_environment(key: Optional[str] = None):
    """Get environment variables."""
    return shell_service.get_env(key)


@app.get("/which")
async def which_command(command: str):
    """Find command location."""
    return await shell_service.which(command)


@app.get("/cwd")
async def get_cwd():
    """Get current working directory."""
    return {
        "success": True,
        "cwd": str(shell_service.workspace_root)
    }


@app.post("/run")
async def quick_run(command: str, timeout: int = 60):
    """Quick command execution."""
    request = ExecuteRequest(command=command, timeout=timeout)
    return await shell_service.execute(request)


if __name__ == "__main__":
    logger.info(f"Starting Node {NODE_ID}: {NODE_NAME} on port {NODE_PORT}")
    uvicorn.run(app, host="0.0.0.0", port=NODE_PORT)
