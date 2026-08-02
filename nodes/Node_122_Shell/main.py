"""
Node 14: Shell Operations
Galaxy 64-Core MCP Matrix - Core Tool Node

Provides comprehensive shell/command execution:
- Command execution (sync and async)
- Process management
- Environment variable handling
- Working directory management
- Output streaming
- Timeout handling

Author: Galaxy Team
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
import re
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
from datetime import datetime
from dataclasses import dataclass, asdict
from enum import Enum

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn
from nodes.common.cors_config import get_cors_origins

# =============================================================================
# Configuration
# =============================================================================

from core.port_config import get_service_port, get_node_port

NODE_ID = os.getenv("NODE_ID", "122")
NODE_NAME = os.getenv("NODE_NAME", "ShellOperations")
NODE_PORT = int(os.getenv("NODE_PORT", str(get_node_port("Node_122_Shell"))))
STATE_MACHINE_URL = os.getenv("STATE_MACHINE_URL", f"http://localhost:{get_service_port('state_machine')}")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
DEFAULT_TIMEOUT = int(os.getenv("DEFAULT_TIMEOUT", "300"))
DEFAULT_SHELL = os.getenv("DEFAULT_SHELL", "/bin/bash")
WORKSPACE_ROOT = os.getenv("WORKSPACE_ROOT", os.path.expanduser("~"))

# Security: blocked commands and patterns
BLOCKED_COMMANDS = [
    "rm -rf /",
    "mkfs",
    "dd if=/dev/zero",
    ":(){:|:&};:",  # Fork bomb
    "chmod 777",
    "curl | sh", "curl | bash", "wget | sh", "wget | bash",
    "shutdown", "reboot", "halt", "poweroff",
    "passwd", "useradd", "userdel", "usermod",
    "iptables -F", "ufw disable",
]

# Shell metacharacters that indicate injection when used in shell=True mode
# without explicit args — block command chaining
_DANGEROUS_SHELL_PATTERNS = [
    "&&", "||", ";", "|", "`", "$(", "${", "\n", "\r",
]

# ---------------------------------------------------------------------------
# 可执行文件白名单（B3）
# ---------------------------------------------------------------------------
#
# 此前只有 BLOCKED_COMMANDS 黑名单，且是**子串匹配**：
#     if blocked.lower() in command_lower
# 于是 "rm -rf /" 拦得住，"rm  -rf /"（双空格）、"rm -fr /" 拦不住。黑名单本质是
# 枚举坏值 —— 攻击面由"我想到了多少种写法"决定，而不是由策略决定。
#
# 现在改为**白名单驱动**：只有 argv[0]（shell 模式下是命令串的第一个词）落在
# 允许集合内才放行。黑名单保留为第二道（白名单内的程序也可能被用来干坏事，
# 例如 `python -c ...`），两者是与的关系。
#
# 可配置项：
#   GALAXY_SHELL_ALLOWED_COMMANDS  逗号分隔，**追加**到默认集合
#   GALAXY_SHELL_ALLOWLIST_MODE=off  关闭白名单，退回纯黑名单（旧行为）
#
# 默认集合的取舍：覆盖开发/运维常用只读与构建类工具。刻意**不含**
# rm / mv / dd / mkfs / chmod / chown / sudo / su —— 需要这些的场景应当显式
# 通过 GALAXY_SHELL_ALLOWED_COMMANDS 授权，而不是默认可用。
_DEFAULT_ALLOWED_COMMANDS = frozenset({
    # 版本控制
    "git",
    # 文件与文本读取
    "ls", "cat", "head", "tail", "wc", "find", "grep", "rg", "diff", "file", "stat", "du", "df",
    "sort", "uniq", "cut", "awk", "sed", "tr", "basename", "dirname", "realpath", "readlink",
    # 运行时与包管理
    "python", "python3", "pip", "pip3", "node", "npm", "npx", "yarn", "pnpm",
    "go", "cargo", "rustc", "java", "javac", "mvn", "gradle",
    # 构建与测试
    "make", "cmake", "pytest", "tox", "ruff", "flake8", "mypy", "black", "isort", "eslint",
    # 进程与系统信息（只读）
    "ps", "top", "uname", "whoami", "id", "env", "printenv", "date", "uptime", "hostname",
    "which", "whereis", "echo", "pwd", "true", "false",
    # 网络诊断（只读）
    "curl", "wget", "ping", "dig", "nslookup", "ss", "netstat",
    # 归档（只读/解包）
    "tar", "unzip", "gzip", "gunzip", "zip",
    # 容器（本仓自身要用）
    "docker", "podman", "kubectl",
})


def _allowlist_enabled() -> bool:
    return os.getenv("GALAXY_SHELL_ALLOWLIST_MODE", "on").strip().lower() not in ("off", "0", "false", "no")


def _allowed_commands() -> frozenset:
    extra = os.getenv("GALAXY_SHELL_ALLOWED_COMMANDS", "")
    if not extra.strip():
        return _DEFAULT_ALLOWED_COMMANDS
    added = {c.strip() for c in extra.split(",") if c.strip()}
    return _DEFAULT_ALLOWED_COMMANDS | added


def _executable_name(command: str) -> str:
    """取出命令串里真正会被执行的程序名（去掉路径与 .exe 后缀）。

    ``/usr/bin/git`` → ``git``；``C:\\Python\\python.exe`` → ``python``。
    取 basename 是为了让 ``/bin/rm`` 不能绕过对 ``rm`` 的限制；同时也意味着
    白名单是按**程序名**而非路径授权 —— 这是刻意的，路径级授权在跨平台下不可维护。
    """
    if not command or not command.strip():
        return ""
    try:
        # posix=False 是刻意的：POSIX 模式会把反斜杠当转义符吃掉，
        # ``C:\Python\python.exe`` 会被拆成 ``C:Pythonpython.exe``，
        # 于是 Windows 风格路径永远解析不出正确的程序名。
        # 代价是引号会被保留在 token 里，下面手动剥掉。
        tokens = shlex.split(command, posix=False)
        first = tokens[0] if tokens else ""
    except ValueError:
        # 引号不配对之类 —— 交给后续的元字符检查去拒绝，这里退回朴素切分
        first = command.strip().split()[0]

    first = first.strip().strip("'\"")
    # 同时按 / 与 \ 切分：不能依赖 os.path.basename，它在 Linux 上不认反斜杠，
    # 于是 ``/bin/rm`` 拦得住、``C:\Windows\System32\cmd.exe`` 拦不住。
    name = re.split(r"[\\/]", first)[-1]
    if name.lower().endswith(".exe"):
        name = name[:-4]
    return name.lower()

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

    def _prune_process_info(self, cap: int = 500) -> None:
        # _process_info 只更新状态、从不删除(只有 _running_processes 在 finally 清理)
        # → 无界泄漏。按插入顺序保留最近 cap 条。
        if len(self._process_info) > cap:
            for _pid in list(self._process_info.keys())[: len(self._process_info) - cap]:
                self._process_info.pop(_pid, None)

    def _is_command_safe(self, command: str, shell_mode: bool = True) -> bool:
        """Check if command is safe to execute.

        三道检查，全部通过才放行：

        1. **可执行文件白名单**（B3 新增，主防线）—— argv[0] 必须在允许集合内。
        2. **危险命令黑名单** —— 白名单内的程序也可能被滥用，保留为第二道。
        3. **Shell 元字符** —— shell 模式下拒绝命令串接/注入。

        白名单是主防线：黑名单只能枚举已知坏值，攻击面由"想到了多少写法"决定；
        白名单则由策略决定，未授权的程序一律进不来。
        """
        command_lower = command.lower().strip()

        # 1) 白名单
        if _allowlist_enabled():
            exe = _executable_name(command)
            if not exe:
                logger.warning("Blocked empty command")
                return False
            if exe not in _allowed_commands():
                logger.warning(
                    "Blocked non-allowlisted executable %r (设 GALAXY_SHELL_ALLOWED_COMMANDS 可授权)",
                    exe,
                )
                return False

        # 2) 黑名单。
        #    归一化空白后再匹配 —— 原实现是对原串做子串匹配，"rm  -rf /"（双空格）
        #    与 "rm\t-rf /" 都能绕过 "rm -rf /" 这条规则。
        normalized = " ".join(command_lower.split())
        for blocked in BLOCKED_COMMANDS:
            blocked_norm = " ".join(blocked.lower().split())
            if blocked_norm in normalized:
                logger.warning("Blocked dangerous command pattern %r", blocked)
                return False

        # In shell mode, reject commands containing injection metacharacters
        if shell_mode:
            for pattern in _DANGEROUS_SHELL_PATTERNS:
                if pattern in command:
                    logger.warning(
                        f"Blocked shell metacharacter '{pattern}' in command: "
                        f"{command[:80]}..."
                    )
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
        if not self._is_command_safe(request.command, shell_mode=request.shell):
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
            self._prune_process_info()
            
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
            self._prune_process_info()
            
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
    description="Shell operations service for Galaxy",
    version="5.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
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
