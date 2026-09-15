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

import asyncio
import json
import logging
import os
import re
import shlex
import signal
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import uvicorn
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from core.port_config import get_node_port, get_service_port
from nodes.common.cors_config import get_cors_origins

# =============================================================================
# Configuration
# =============================================================================


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
    "curl | sh",
    "curl | bash",
    "wget | sh",
    "wget | bash",
    "shutdown",
    "reboot",
    "halt",
    "poweroff",
    "passwd",
    "useradd",
    "userdel",
    "usermod",
    "iptables -F",
    "ufw disable",
]

# Shell metacharacters that indicate injection when used in shell=True mode
# without explicit args — block command chaining
_DANGEROUS_SHELL_PATTERNS = [
    "&&",
    "||",
    ";",
    "|",
    "`",
    "$(",
    "${",
    "\n",
    "\r",
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
_DEFAULT_ALLOWED_COMMANDS = frozenset(
    {
        # 版本控制
        "git",
        # 文件与文本读取
        "ls",
        "cat",
        "head",
        "tail",
        "wc",
        "find",
        "grep",
        "rg",
        "diff",
        "file",
        "stat",
        "du",
        "df",
        "sort",
        "uniq",
        "cut",
        "awk",
        "sed",
        "tr",
        "basename",
        "dirname",
        "realpath",
        "readlink",
        # 运行时与包管理
        "python",
        "python3",
        "pip",
        "pip3",
        "node",
        "npm",
        "npx",
        "yarn",
        "pnpm",
        "go",
        "cargo",
        "rustc",
        "java",
        "javac",
        "mvn",
        "gradle",
        # 构建与测试
        "make",
        "cmake",
        "pytest",
        "tox",
        "ruff",
        "flake8",
        "mypy",
        "black",
        "isort",
        "eslint",
        # 进程与系统信息（只读）
        "ps",
        "top",
        "uname",
        "whoami",
        "id",
        "env",
        "printenv",
        "date",
        "uptime",
        "hostname",
        "which",
        "whereis",
        "echo",
        "pwd",
        "true",
        "false",
        # 网络诊断（只读）
        "curl",
        "wget",
        "ping",
        "dig",
        "nslookup",
        "ss",
        "netstat",
        # 归档（只读/解包）
        "tar",
        "unzip",
        "gzip",
        "gunzip",
        "zip",
        # 容器（本仓自身要用）
        "docker",
        "podman",
        "kubectl",
    }
)


def _allowlist_enabled() -> bool:
    return os.getenv("GALAXY_SHELL_ALLOWLIST_MODE", "on").strip().lower() not in ("off", "0", "false", "no")


def _allowed_commands() -> frozenset:
    extra = os.getenv("GALAXY_SHELL_ALLOWED_COMMANDS", "")
    if not extra.strip():
        return _DEFAULT_ALLOWED_COMMANDS
    added = {c.strip() for c in extra.split(",") if c.strip()}
    return _DEFAULT_ALLOWED_COMMANDS | added


def _is_powershell_invocation(executable_name: str) -> bool:
    """这次调用的是不是 PowerShell 解释器。"""
    try:
        from core.windows_powershell_policy import is_powershell
    except Exception:  # noqa: BLE001 — 策略模块不可用时按"不是 PowerShell"处理,
        return False  # 于是它落回 argv[0] 白名单 —— 而 powershell 不在里面,仍是拒绝。

    return is_powershell(executable_name)


def _powershell_allowed(command: str) -> bool:
    """PowerShell 的 cmdlet 级判定。拒绝时把原因记进日志 —— 只回 False 排障时无从查起。"""
    try:
        from core.windows_powershell_policy import evaluate
    except Exception as exc:  # noqa: BLE001 — 策略读不到时 fail-closed
        logger.warning("PowerShell 策略不可用,拒绝执行: %s", exc)
        return False

    try:
        argv = shlex.split(command, posix=False)
    except ValueError:
        logger.warning("PowerShell 命令引号不配对,拒绝")
        return False

    verdict = evaluate(argv)
    if not verdict.allowed:
        logger.warning("Blocked PowerShell: %s", verdict.reason)
    return bool(verdict.allowed)


async def _human_approved(title: str, summary: str) -> bool:
    """问人。**问不到人就是拒绝。**

    上一轮我把 ``needs_human`` 写进了 ``PowerShellVerdict``,然后向用户描述成"四层门禁"
    的第四层 —— 但全仓没有任何地方读这个字段,``_powershell_allowed`` 只返回
    ``verdict.allowed``。也就是说那一层当时并不存在,它只是个字段。这里把它接上。

    **超时按拒绝处理**(``OnTimeout.CANCEL``)。一个通用解释器的调用,没人应答时默认
    放行等于这道闸不存在;而它要防的恰恰是"没人盯着的时候执行了不该执行的东西"。

    没有可问的设备(无头部署)时同样是拒绝。这会让无头环境下 PowerShell 与 /script
    不可用 —— 这是**有意的取舍**,不是遗漏:要在无头环境放开,得显式设
    ``GALAXY_SHELL_UNATTENDED=1``,而那等于声明"这台机器上没人把关",应当写进部署文档。
    """
    if os.getenv("GALAXY_SHELL_UNATTENDED", "").strip().lower() in ("1", "true", "yes", "on"):
        logger.warning("GALAXY_SHELL_UNATTENDED 已设:跳过人确认 —— 这台机器上没有人把关")
        return True
    try:
        from core.interaction.pending_decision_registry import (
            OnTimeout,
            _discover_target_devices,
            request_human_decision,
        )
    except Exception as exc:  # noqa: BLE001 — 问不到人就是拒绝
        logger.warning("人确认通道不可用,拒绝执行: %s", exc)
        return False

    # 先看有没有人可问。没有设备在线时 request_human_decision 会**把超时等满**
    # (实测 60 秒),而结论从第一秒起就已经确定 —— 无头部署每条命令卡一分钟,
    # 会被当成节点坏了,然后有人去把这道闸关掉。拒绝要快。
    try:
        targets = await _discover_target_devices()
    except Exception as exc:  # noqa: BLE001
        logger.warning("查不到可问的设备,拒绝执行: %s", exc)
        return False
    if not targets:
        logger.warning("没有可问的设备,拒绝执行: %s(无头环境可设 GALAXY_SHELL_UNATTENDED=1)", title)
        return False

    try:
        outcome = await request_human_decision(
            title=title,
            summary=summary,
            options=[{"id": "approve", "label": "执行"}, {"id": "deny", "label": "拒绝"}],
            default_option="deny",
            urgency="high",
            on_timeout=OnTimeout.CANCEL,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("人确认过程出错,拒绝执行: %s", exc)
        return False

    approved = getattr(outcome, "selected_option", None) == "approve"
    if not approved:
        logger.warning("人确认未通过(或超时),拒绝执行: %s", title)
    return approved


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
    level=getattr(logging, LOG_LEVEL), format=f"[Node {NODE_ID}] %(asctime)s - %(levelname)s - %(message)s"
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

            # 1a) PowerShell 走**更细一层**的授权。
            #
            # argv[0] 级白名单对 git / ls 有效:程序本身决定了它能做什么。
            # 但 `powershell -Command <任意字符串>` 是通用解释器 —— 把它放进
            # argv[0] 白名单等于给了一把万能钥匙,白名单外的每个程序都能被它
            # 调起来,这道白名单当场失效。
            #
            # 所以 PowerShell 不按程序名授权,按它后面跟的那个 cmdlet 授权。
            # 判定在 core.windows_powershell_policy(纯函数,23 条用例)。
            if _is_powershell_invocation(exe):
                return _powershell_allowed(command)

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
                    logger.warning(f"Blocked shell metacharacter '{pattern}' in command: " f"{command[:80]}...")
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

    async def _needs_human_for(self, command: str) -> bool:
        """这条命令要不要人确认。

        目前只有 PowerShell 需要 —— ``PowerShellVerdict.needs_human`` 恒为 True。
        上一轮我把那个字段写出来、也向用户描述成"第四层门禁",但**全仓没有任何地方
        读它**:``_powershell_allowed`` 只返回 ``verdict.allowed``。所以那一层当时
        并不存在。这里把它真的接上。
        """
        if not _allowlist_enabled():
            return False
        exe = _executable_name(command)
        if not _is_powershell_invocation(exe):
            return False
        try:
            from core.windows_powershell_policy import evaluate  # noqa: PLC0415

            return bool(evaluate(shlex.split(command, posix=False)).needs_human)
        except Exception as exc:  # noqa: BLE001 — 判定不了就按"要问人"处理
            logger.warning("取 needs_human 失败,按需要人确认处理: %s", exc)
            return True

    async def execute(self, request: ExecuteRequest) -> Dict[str, Any]:
        """Execute shell command."""
        # Security check
        if not self._is_command_safe(request.command, shell_mode=request.shell):
            return {"success": False, "error": "Command blocked for security reasons", "command": request.command}

        # 通用解释器(目前是 PowerShell)必须人确认 —— 白名单能判"这个 cmdlet 允许吗",
        # 判不了"这一次这么用对不对"。
        if await self._needs_human_for(request.command):
            if not await _human_approved(title="执行命令？", summary=request.command[:200]):
                return {
                    "success": False,
                    "error": "Command denied: human approval not granted",
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
                    env=env,
                )
            else:
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE if request.capture_output else None,
                    stderr=asyncio.subprocess.PIPE if request.capture_output else None,
                    cwd=cwd,
                    env=env,
                )

            # Track process
            self._running_processes[process.pid] = process
            self._process_info[process.pid] = ProcessInfo(
                pid=process.pid, command=request.command, status="running", started_at=start_time.isoformat()
            )
            self._prune_process_info()

            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=request.timeout)

                end_time = datetime.now()
                elapsed = (end_time - start_time).total_seconds()

                # Update process info
                self._process_info[process.pid].status = "completed"

                return {
                    "success": process.returncode == 0,
                    "return_code": process.returncode,
                    "stdout": stdout.decode("utf-8", errors="replace") if stdout else "",
                    "stderr": stderr.decode("utf-8", errors="replace") if stderr else "",
                    "command": request.command,
                    "cwd": cwd,
                    "elapsed_seconds": elapsed,
                    "pid": process.pid,
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
                    "pid": process.pid,
                }

            finally:
                # Cleanup
                if process.pid in self._running_processes:
                    del self._running_processes[process.pid]

        except Exception as e:
            logger.error(f"Execute error: {e}")
            return {"success": False, "error": str(e), "command": request.command}

    async def execute_script(self, request: ScriptRequest) -> Dict[str, Any]:
        """Execute multi-line script.

        **这条路此前一道检查都没有。** ``interpreter`` 由调用方给、直接进
        ``create_subprocess_exec``,脚本正文从 stdin 灌进去 —— 上一轮为 PowerShell
        建的 cmdlet 白名单、元字符拒绝,在这条路上一条都不生效(实测:
        ``_is_command_safe`` 被调用 0 次)。

        判定在 ``core.shell_script_policy``(纯函数,可单测);这里只负责取来用,
        以及**真的去问人** —— 那一层上一轮只是个没人读的字段。
        """
        from core.shell_script_policy import evaluate_script  # noqa: PLC0415

        verdict = evaluate_script(
            request.interpreter,
            request.script,
            blocked_patterns=BLOCKED_COMMANDS,
            allowlist_enabled=_allowlist_enabled(),
        )
        if not verdict.allowed:
            logger.warning("Blocked script: %s", verdict.reason)
            return {"success": False, "error": f"Script blocked: {verdict.reason}"}

        # 一段任意脚本正文没法被静态判定安全。判定不了的时候问人,而不是放行。
        if verdict.needs_human and not await _human_approved(
            title="执行脚本？",
            summary=f"解释器 {verdict.interpreter}，{len(request.script.splitlines())} 行",
        ):
            return {"success": False, "error": "Script execution denied: human approval not granted"}

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
                env=env,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(input=request.script.encode()), timeout=request.timeout
                )

                end_time = datetime.now()
                elapsed = (end_time - start_time).total_seconds()

                return {
                    "success": process.returncode == 0,
                    "return_code": process.returncode,
                    "stdout": stdout.decode("utf-8", errors="replace"),
                    "stderr": stderr.decode("utf-8", errors="replace"),
                    "interpreter": request.interpreter,
                    "elapsed_seconds": elapsed,
                }

            except asyncio.TimeoutError:
                process.kill()
                await process.wait()

                return {"success": False, "error": f"Script timed out after {request.timeout} seconds"}

        except Exception as e:
            logger.error(f"Script error: {e}")
            return {"success": False, "error": str(e)}

    async def execute_background(self, request: ExecuteRequest) -> Dict[str, Any]:
        """Execute command in background."""
        if not self._is_command_safe(request.command):
            return {"success": False, "error": "Command blocked for security reasons"}

        # 通用解释器(目前是 PowerShell)必须人确认 —— 白名单能判"这个 cmdlet 允许吗",
        # 判不了"这一次这么用对不对"。
        if await self._needs_human_for(request.command):
            if not await _human_approved(title="执行命令？", summary=request.command[:200]):
                return {
                    "success": False,
                    "error": "Command denied: human approval not granted",
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
                start_new_session=True,
            )

            self._running_processes[process.pid] = process
            self._process_info[process.pid] = ProcessInfo(
                pid=process.pid, command=request.command, status="running", started_at=datetime.now().isoformat()
            )
            self._prune_process_info()

            return {
                "success": True,
                "pid": process.pid,
                "command": request.command,
                "message": "Process started in background",
            }

        except Exception as e:
            logger.error(f"Background execute error: {e}")
            return {"success": False, "error": str(e)}

    async def kill_process(self, request: KillRequest) -> Dict[str, Any]:
        """Kill a running process."""
        try:
            os.kill(request.pid, request.signal)

            if request.pid in self._process_info:
                self._process_info[request.pid].status = "killed"

            return {"success": True, "pid": request.pid, "signal": request.signal}
        except ProcessLookupError:
            return {"success": False, "error": f"Process {request.pid} not found"}
        except PermissionError:
            return {"success": False, "error": f"Permission denied to kill process {request.pid}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_processes(self) -> Dict[str, Any]:
        """List tracked processes."""
        processes = []
        for pid, info in self._process_info.items():
            processes.append(info.dict())

        return {"success": True, "count": len(processes), "processes": processes}

    def get_env(self, key: Optional[str] = None) -> Dict[str, Any]:
        """Get environment variables."""
        if key:
            value = os.environ.get(key)
            return {"success": True, "key": key, "value": value, "exists": value is not None}
        else:
            return {"success": True, "environment": dict(os.environ)}

    async def which(self, command: str) -> Dict[str, Any]:
        """Find command location."""
        try:
            result = await self.execute(ExecuteRequest(command=f"which {shlex.quote(command)}", timeout=10))

            if result["success"]:
                return {"success": True, "command": command, "path": result["stdout"].strip()}
            else:
                return {"success": False, "command": command, "error": "Command not found"}
        except Exception as e:
            return {"success": False, "error": str(e)}


# =============================================================================
# FastAPI Application
# =============================================================================

from nodes.common.action_gate import action_guard

app = FastAPI(title=f"Node {NODE_ID}: {NODE_NAME}", description="Shell operations service for Galaxy", version="5.0.0")

# HTTP 面的动作权限闸。判定在 core.node_action_permissions,接线在
# nodes.common.action_gate —— 此前这一面一道门都没有,manifest 只对
# 统一执行器那条路生效。
_require = action_guard("Node_122_Shell")

app.add_middleware(
    CORSMiddleware, allow_origins=get_cors_origins(), allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)

shell_service = ShellService()


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "node_id": NODE_ID, "node_name": NODE_NAME, "timestamp": datetime.now().isoformat()}


@app.post("/execute")
async def execute_command(request: ExecuteRequest):
    """Execute shell command."""
    _require("execute")
    return await shell_service.execute(request)


@app.post("/script")
async def execute_script(request: ScriptRequest):
    """Execute multi-line script."""
    _require("script")
    return await shell_service.execute_script(request)


@app.post("/background")
async def execute_background(request: ExecuteRequest):
    """Execute command in background."""
    _require("background")
    return await shell_service.execute_background(request)


@app.post("/kill")
async def kill_process(request: KillRequest):
    """Kill a running process."""
    _require("kill")
    return await shell_service.kill_process(request)


@app.get("/processes")
async def list_processes():
    """List tracked processes."""
    _require("list_processes")
    return shell_service.list_processes()


@app.get("/env")
async def get_environment(key: Optional[str] = None):
    """Get environment variables."""
    _require("env")
    return shell_service.get_env(key)


@app.get("/which")
async def which_command(command: str):
    """Find command location."""
    _require("which")
    return await shell_service.which(command)


@app.get("/cwd")
async def get_cwd():
    """Get current working directory."""
    _require("cwd")
    return {"success": True, "cwd": str(shell_service.workspace_root)}


@app.post("/run")
async def quick_run(command: str, timeout: int = 60):
    """Quick command execution."""
    _require("run")
    request = ExecuteRequest(command=command, timeout=timeout)
    return await shell_service.execute(request)


if __name__ == "__main__":
    logger.info(f"Starting Node {NODE_ID}: {NODE_NAME} on port {NODE_PORT}")
    uvicorn.run(app, host="0.0.0.0", port=NODE_PORT)
