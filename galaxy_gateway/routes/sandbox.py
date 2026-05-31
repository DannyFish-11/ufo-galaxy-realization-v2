"""
galaxy_gateway/routes/sandbox.py — Code Execution Sandbox Routes
=================================================================

把 Node_09_Sandbox 的能力暴露为 REST API，供 AI Agent 在执行前做安全预检。

安全策略：
  1. 危险命令黑名单（rm -rf, mkfs, dd 等）
  2. 资源限制（内存 256MB, CPU 30秒超时）
  3. 子进程隔离（临时目录 + preexec_fn）
  4. 代码/命令先过沙箱验证，通过后才允许实际执行

Routes:
  POST /api/v1/agents/sandbox/execute     — 沙箱执行代码
  POST /api/v1/agents/sandbox/validate    — 验证命令安全性（预检）
  GET  /api/v1/agents/sandbox/status      — 沙箱状态

使用：
  AI Agent 在执行命令前，先调用 /validate 检查安全性。
  如果命令在黑名单中或资源超限，返回安全警告。
"""

import logging
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("Galaxy.Sandbox")

router = APIRouter(prefix="/api/v1/agents/sandbox", tags=["sandbox"])

# ── 资源限制 ──
try:
    import resource as _resource
    _RESOURCE_AVAILABLE = True
except ImportError:
    _resource = None
    _RESOURCE_AVAILABLE = False

# ── 危险命令黑名单 ──
DANGEROUS_PATTERNS = [
    "rm -rf", "rm -rf /", "dd if=", "mkfs", "format", "fdisk",
    ":(){ :|:& };:",           # fork bomb
    "chmod 777 /",             # 根目录权限破坏
    "> /dev/sda", ">/dev/sda", # 磁盘覆写
    "mv / /dev/null",          # 根目录移动
    "shutdown", "reboot", "halt", "poweroff",
    "curl http", "wget http",   # 网络下载（需审查）
    "nc -l", "nc -lp",          # netcat 监听
    "telnet", "ssh", "scp", "sftp",
    "/etc/passwd", "/etc/shadow", "/etc/hosts",
    "iptables -F", "ufw disable",
    "userdel", "groupdel",
    "kill -9 -1", "kill -9 1",
]

SAFE_COMMAND_WHITELIST = [
    "ls", "cat", "echo", "pwd", "whoami", "uname", "df", "du",
    "free", "top", "ps", "grep", "awk", "sed", "head", "tail",
    "find", "wc", "sort", "uniq", "cut", "tr", "xargs",
    "mkdir", "touch", "cp", "mv", "rm", "chmod", "chown",
    "git", "docker ps", "docker images", "systemctl status",
    "nginx -t", "nginx -v", "python3", "pip", "node", "npm",
    "tar", "gzip", "gunzip", "zip", "unzip",
    "ping", "curl -I", "wget --spider", "netstat", "ss",
    "journalctl", "dmesg", "lsof", "strace",
]


# ============================================================================
# Pydantic 模型
# ============================================================================

class SandboxExecuteRequest(BaseModel):
    code: str = Field(..., description="要执行的代码")
    language: str = Field(default="python", description="语言 (python/bash/javascript 等)")
    timeout: int = Field(default=30, ge=1, le=300, description="超时秒数 (1-300)")
    stdin: Optional[str] = Field(default=None, description="标准输入")
    memory_limit_mb: int = Field(default=256, ge=32, le=2048, description="内存限制 MB (32-2048)")
    cpu_limit_seconds: Optional[int] = Field(default=None, description="CPU 时间限制秒数")


class SandboxValidateRequest(BaseModel):
    command: str = Field(..., description="要验证的命令")
    context: Optional[str] = Field(default=None, description="执行上下文 (local/remote)")


class SandboxExecuteResponse(BaseModel):
    success: bool
    stdout: str
    stderr: str
    exit_code: int
    execution_time_ms: float
    language: str
    safe: bool                          # 是否通过安全检查
    blocked_reason: Optional[str]       # 如果不安全，原因
    timestamp: str


class SandboxValidateResponse(BaseModel):
    safe: bool                          # 是否安全
    risk_level: str                     # "safe" | "low" | "medium" | "high" | "blocked"
    blocked: bool                       # 是否被黑名单阻止
    blocked_reason: Optional[str]       # 阻止原因
    warnings: List[str]                 # 警告列表
    recommended_action: str             # 建议操作


# ============================================================================
# 安全检查引擎
# ============================================================================

def check_command_safety(command: str) -> SandboxValidateResponse:
    """
    检查命令安全性，返回风险评估。

    评估维度：
      1. 黑名单匹配 → blocked
      2. 白名单匹配 → safe
      3. 包含潜在危险操作 → warning
    """
    warnings: List[str] = []
    cmd_lower = command.lower().strip()

    # 1. 黑名单检查
    for pattern in DANGEROUS_PATTERNS:
        if pattern.lower() in cmd_lower:
            return SandboxValidateResponse(
                safe=False,
                risk_level="blocked",
                blocked=True,
                blocked_reason=f"匹配危险模式: {pattern}",
                warnings=[f"命令包含危险模式: {pattern}"],
                recommended_action="拒绝执行，需人工审查",
            )

    # 2. 白名单检查（基础命令认为是安全的）
    cmd_first = command.split()[0] if command.split() else ""
    is_whitelisted = any(cmd_first == w.split()[0] for w in SAFE_COMMAND_WHITELIST)

    # 3. 潜在风险检查
    if "sudo " in cmd_lower and "rm" in cmd_lower:
        warnings.append("sudo + rm 组合可能导致数据丢失")
    if ">" in command and "/dev/" in cmd_lower:
        warnings.append("重定向到设备文件可能破坏系统")
    if "curl" in cmd_lower and ("|" in command or ";" in command):
        warnings.append("curl 管道执行存在注入风险")
    if "wget" in cmd_lower and ("|" in command or ";" in command):
        warnings.append("wget 管道执行存在注入风险")
    if "eval" in cmd_lower or "exec" in cmd_lower:
        warnings.append("eval/exec 可能执行任意代码")
    if "$(" in command or "`" in command:
        warnings.append("命令替换可能引入注入风险")

    # 4. 综合评级
    if warnings:
        risk_level = "medium" if len(warnings) <= 1 else "high"
        return SandboxValidateResponse(
            safe=True,              # 技术上允许，但有警告
            risk_level=risk_level,
            blocked=False,
            blocked_reason=None,
            warnings=warnings,
            recommended_action="执行前确认，建议人工审查",
        )

    if is_whitelisted:
        return SandboxValidateResponse(
            safe=True,
            risk_level="safe",
            blocked=False,
            blocked_reason=None,
            warnings=[],
            recommended_action="可直接执行",
        )

    # 未知命令
    return SandboxValidateResponse(
        safe=True,
        risk_level="low",
        blocked=False,
        blocked_reason=None,
        warnings=[f"未知命令: {cmd_first}"],
        recommended_action="首次使用，建议确认",
    )


def _set_resource_limits(memory_mb: int, cpu_sec: Optional[int]):
    """设置子进程资源限制（Unix only）。"""
    if not _RESOURCE_AVAILABLE:
        return
    try:
        memory_bytes = memory_mb * 1024 * 1024
        _resource.setrlimit(_resource.RLIMIT_AS, (memory_bytes, memory_bytes))
        if cpu_sec:
            _resource.setrlimit(_resource.RLIMIT_CPU, (cpu_sec, cpu_sec))
    except Exception:
        pass


# ============================================================================
# 路由
# ============================================================================

@router.get("/status")
async def sandbox_status():
    """沙箱状态。"""
    return {
        "status": "active",
        "resource_limits_available": _RESOURCE_AVAILABLE,
        "blacklist_patterns": len(DANGEROUS_PATTERNS),
        "whitelist_commands": len(SAFE_COMMAND_WHITELIST),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/validate", response_model=SandboxValidateResponse)
async def validate_command(req: SandboxValidateRequest):
    """
    验证命令安全性（预检）。

    AI Agent 在执行命令前应先调用此端点检查。
    返回风险评估，blocked=True 时拒绝执行。
    """
    return check_command_safety(req.command)


@router.post("/execute", response_model=SandboxExecuteResponse)
async def sandbox_execute(req: SandboxExecuteRequest):
    """
    在沙箱中执行代码。

    安全策略：
      1. 先过安全检查
      2. 在临时目录中运行
      3. 设置资源限制
      4. 严格超时控制
    """
    start_time = datetime.now(timezone.utc)

    # 1. 安全检查（代码级别）
    for pattern in DANGEROUS_PATTERNS:
        if pattern.lower() in req.code.lower():
            return SandboxExecuteResponse(
                success=False,
                stdout="",
                stderr=f"[SANDBOX BLOCKED] 危险模式: {pattern}",
                exit_code=-1,
                execution_time_ms=0,
                language=req.language,
                safe=False,
                blocked_reason=f"匹配危险模式: {pattern}",
                timestamp=start_time.isoformat(),
            )

    # 2. 准备临时目录
    with tempfile.TemporaryDirectory(prefix="galaxy_sandbox_") as tmpdir:
        # 3. 按语言执行
        try:
            if req.language == "python":
                cmd = ["python3", "-c", req.code]
            elif req.language == "bash" or req.language == "sh":
                cmd = ["bash", "-c", req.code]
            elif req.language == "javascript":
                cmd = ["node", "-e", req.code]
            else:
                raise HTTPException(400, f"Unsupported language: {req.language}")

            # 4. 执行（带资源限制）
            result = subprocess.run(
                cmd,
                cwd=tmpdir,
                capture_output=True,
                text=True,
                timeout=req.timeout,
                input=req.stdin or "",
                preexec_fn=lambda: _set_resource_limits(
                    req.memory_limit_mb, req.cpu_limit_seconds
                ),
            )

            elapsed = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000

            return SandboxExecuteResponse(
                success=result.returncode == 0,
                stdout=result.stdout[:50000],
                stderr=result.stderr[:10000],
                exit_code=result.returncode,
                execution_time_ms=elapsed,
                language=req.language,
                safe=True,
                blocked_reason=None,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

        except subprocess.TimeoutExpired:
            return SandboxExecuteResponse(
                success=False,
                stdout="",
                stderr=f"[SANDBOX TIMEOUT] 执行超过 {req.timeout} 秒",
                exit_code=-1,
                execution_time_ms=req.timeout * 1000,
                language=req.language,
                safe=False,
                blocked_reason=f"超时: {req.timeout}s",
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as e:
            return SandboxExecuteResponse(
                success=False,
                stdout="",
                stderr=f"[SANDBOX ERROR] {e}",
                exit_code=-1,
                execution_time_ms=0,
                language=req.language,
                safe=False,
                blocked_reason=str(e),
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
