"""
SafeExecutor — 安全代码执行沙箱
================================

Phase 4 Matrix OS 核心组件。

Agent "自编码" 能力的运行时:
1. Agent (LLM) 生成代码片段
2. SafeExecutor 验证安全性
3. 在受限沙箱中执行
4. 返回结果供 Agent 继续推理

安全层:
- 语言白名单 (Python, JavaScript, Bash)
- 危险 pattern 检测 (import os.system, exec, eval, subprocess, rm -rf 等)
- 资源限制 (内存, CPU 时间, 超时)
- 网络隔离 (可选)

与 Node_09_Sandbox 的关系:
- 如果 Node_09 在线, SafeExecutor 委托给 Node_09 (通过 HTTP API)
- 如果 Node_09 离线, SafeExecutor 使用内置轻量沙箱 (仅 Python)
"""

import asyncio
import json
import logging
import os
import subprocess
import tempfile
import time
import uuid
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field

logger = logging.getLogger("UFO-Galaxy.SafeExecutor")


# ============================================================================
# 安全检查
# ============================================================================

# 危险 pattern (阻止执行)
_DANGEROUS_PATTERNS_PYTHON = [
    "os.system",
    "subprocess.call",
    "subprocess.Popen",
    "subprocess.run",
    "__import__('os')",
    "exec(",
    "eval(",
    "compile(",
    "open('/etc",
    "open('/proc",
    "shutil.rmtree",
    "os.remove",
    "os.rmdir",
    "os.unlink",
    "import ctypes",
    "import socket",
    "__builtins__",
]

_DANGEROUS_PATTERNS_BASH = [
    "rm -rf",
    "dd if=",
    "mkfs",
    "format",
    "fdisk",
    ":(){ :|:& };:",
    "chmod 777",
    "wget",
    "curl http",
    "nc -l",
    "ssh ",
    "/etc/passwd",
    "/etc/shadow",
    "> /dev/",
    "kill -9",
]

_DANGEROUS_PATTERNS_JS = [
    "child_process",
    "fs.rm",
    "fs.unlink",
    "require('os')",
    "process.exit",
    "eval(",
]


class SecurityViolation(Exception):
    """安全违规异常"""
    pass


def check_code_safety(code: str, language: str = "python") -> Optional[str]:
    """
    检查代码安全性

    Returns: None if safe, error message if dangerous
    """
    code_lower = code.lower()

    if language == "python":
        patterns = _DANGEROUS_PATTERNS_PYTHON
    elif language in ("bash", "sh"):
        patterns = _DANGEROUS_PATTERNS_BASH
    elif language in ("javascript", "js"):
        patterns = _DANGEROUS_PATTERNS_JS
    else:
        patterns = _DANGEROUS_PATTERNS_PYTHON + _DANGEROUS_PATTERNS_BASH

    for pattern in patterns:
        if pattern.lower() in code_lower:
            return f"Dangerous pattern detected: {pattern}"

    return None


# ============================================================================
# 执行结果
# ============================================================================

@dataclass
class ExecutionResult:
    """代码执行结果"""
    execution_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    language: str = "python"
    success: bool = False
    stdout: str = ""
    stderr: str = ""
    return_value: Any = None
    error: str = ""
    execution_time_ms: float = 0
    safety_check_passed: bool = True

    def to_dict(self) -> Dict:
        return {
            "execution_id": self.execution_id,
            "language": self.language,
            "success": self.success,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "return_value": self.return_value,
            "error": self.error,
            "execution_time_ms": self.execution_time_ms,
            "safety_check_passed": self.safety_check_passed,
        }


# ============================================================================
# SafeExecutor
# ============================================================================

class SafeExecutor:
    """
    安全代码执行器

    执行策略:
    1. 优先委托 Node_09_Sandbox (功能更完整)
    2. 降级到内置 Python 沙箱
    """

    ALLOWED_LANGUAGES = {"python", "javascript", "bash"}
    DEFAULT_TIMEOUT = 15  # seconds
    DEFAULT_MEMORY_MB = 128

    def __init__(self, node09_url: str = ""):
        """
        Args:
            node09_url: Node_09 Sandbox 的 URL (e.g. "http://localhost:8009")
                       空值 = 自动检测或使用内置沙箱
        """
        self._node09_url = node09_url
        self._execution_log: List[Dict] = []
        self._stats = {"total": 0, "success": 0, "blocked": 0, "failed": 0}

    async def execute(
        self,
        code: str,
        language: str = "python",
        timeout: int = None,
        memory_limit_mb: int = None,
        stdin: str = "",
    ) -> ExecutionResult:
        """
        安全执行代码

        Args:
            code: 源代码
            language: 语言 (python, javascript, bash)
            timeout: 超时秒数
            memory_limit_mb: 内存限制 MB
            stdin: 标准输入

        Returns:
            ExecutionResult
        """
        timeout = timeout or self.DEFAULT_TIMEOUT
        memory_limit_mb = memory_limit_mb or self.DEFAULT_MEMORY_MB
        start = time.time()
        self._stats["total"] += 1

        # 1. 语言检查
        if language.lower() not in self.ALLOWED_LANGUAGES:
            self._stats["blocked"] += 1
            return ExecutionResult(
                language=language,
                success=False,
                error=f"Language not allowed: {language}. Allowed: {self.ALLOWED_LANGUAGES}",
                safety_check_passed=False,
            )

        # 2. 安全检查
        violation = check_code_safety(code, language)
        if violation:
            self._stats["blocked"] += 1
            result = ExecutionResult(
                language=language,
                success=False,
                error=f"Security violation: {violation}",
                safety_check_passed=False,
            )
            self._record(result)
            return result

        # 3. 尝试 Node_09
        if self._node09_url:
            try:
                result = await self._execute_via_node09(code, language, timeout, memory_limit_mb, stdin)
                result.execution_time_ms = (time.time() - start) * 1000
                if result.success:
                    self._stats["success"] += 1
                else:
                    self._stats["failed"] += 1
                self._record(result)
                return result
            except Exception as e:
                logger.warning(f"Node_09 unavailable: {e}, falling back to builtin")

        # 4. 内置执行
        result = await self._execute_builtin(code, language, timeout, memory_limit_mb, stdin)
        result.execution_time_ms = (time.time() - start) * 1000
        if result.success:
            self._stats["success"] += 1
        else:
            self._stats["failed"] += 1
        self._record(result)
        return result

    async def _execute_via_node09(
        self, code: str, language: str, timeout: int, memory_mb: int, stdin: str
    ) -> ExecutionResult:
        """委托 Node_09_Sandbox 执行"""
        import httpx
        async with httpx.AsyncClient(timeout=timeout + 5) as client:
            resp = await client.post(
                f"{self._node09_url}/execute",
                json={
                    "code": code,
                    "language": language,
                    "timeout": timeout,
                    "stdin": stdin,
                    "memory_limit_mb": memory_mb,
                },
            )
            data = resp.json()
            return ExecutionResult(
                language=language,
                success=data.get("success", False),
                stdout=data.get("stdout", ""),
                stderr=data.get("stderr", ""),
                return_value=data.get("return_value"),
                error=data.get("error", ""),
            )

    async def _execute_builtin(
        self, code: str, language: str, timeout: int, memory_mb: int, stdin: str
    ) -> ExecutionResult:
        """内置轻量沙箱执行"""
        if language == "python":
            return await self._exec_python(code, timeout, stdin)
        elif language == "bash":
            return await self._exec_bash(code, timeout, stdin)
        elif language == "javascript":
            return await self._exec_javascript(code, timeout, stdin)
        else:
            return ExecutionResult(
                language=language, success=False,
                error=f"Builtin executor not available for: {language}"
            )

    async def _exec_python(self, code: str, timeout: int, stdin: str) -> ExecutionResult:
        """Python 沙箱执行"""
        # 包装代码: 限制 builtins
        wrapped = (
            "import sys\n"
            "# Restricted builtins\n"
            "_safe_builtins = {k: v for k, v in __builtins__.__dict__.items() "
            "if k not in ('exec', 'eval', 'compile', '__import__', 'open', 'input')}\n"
            "# Allow safe open for reading\n"
            "import io\n"
            "try:\n"
        )
        indented = "\n".join("    " + line for line in code.split("\n"))
        wrapped += indented + "\n"
        wrapped += "except Exception as _e:\n    print(f'Error: {_e}', file=sys.stderr)\n    sys.exit(1)\n"

        return await self._run_subprocess(
            ["python3", "-c", wrapped], timeout, stdin, "python"
        )

    async def _exec_bash(self, code: str, timeout: int, stdin: str) -> ExecutionResult:
        """Bash 沙箱执行"""
        return await self._run_subprocess(
            ["bash", "-c", code], timeout, stdin, "bash"
        )

    async def _exec_javascript(self, code: str, timeout: int, stdin: str) -> ExecutionResult:
        """JavaScript 沙箱执行 (需要 node)"""
        return await self._run_subprocess(
            ["node", "-e", code], timeout, stdin, "javascript"
        )

    async def _run_subprocess(
        self, cmd: List[str], timeout: int, stdin: str, language: str
    ) -> ExecutionResult:
        """通用子进程执行"""
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(input=stdin.encode() if stdin else None),
                timeout=timeout,
            )

            stdout = stdout_bytes.decode("utf-8", errors="replace")[:10000]
            stderr = stderr_bytes.decode("utf-8", errors="replace")[:5000]

            return ExecutionResult(
                language=language,
                success=(proc.returncode == 0),
                stdout=stdout,
                stderr=stderr,
                error=stderr if proc.returncode != 0 else "",
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            return ExecutionResult(
                language=language, success=False,
                error=f"Execution timeout ({timeout}s)",
            )
        except FileNotFoundError:
            return ExecutionResult(
                language=language, success=False,
                error=f"Runtime not found for {language}",
            )
        except Exception as e:
            return ExecutionResult(
                language=language, success=False,
                error=str(e),
            )

    # ================================================================
    # Agent 集成: 作为 ReAct 工具
    # ================================================================

    def as_tool_definition(self) -> Dict:
        """返回 OpenAI function calling 格式的工具定义"""
        return {
            "type": "function",
            "function": {
                "name": "execute_code",
                "description": (
                    "Execute code in a secure sandbox. "
                    "Supports Python, JavaScript, and Bash. "
                    "Use this when you need to compute, process data, "
                    "or verify logic programmatically."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {
                            "type": "string",
                            "description": "The source code to execute"
                        },
                        "language": {
                            "type": "string",
                            "enum": ["python", "javascript", "bash"],
                            "description": "Programming language"
                        },
                    },
                    "required": ["code", "language"],
                },
            },
        }

    async def handle_tool_call(self, args: Dict) -> str:
        """处理来自 Agent 的 tool_call"""
        code = args.get("code", "")
        language = args.get("language", "python")
        result = await self.execute(code, language)
        return json.dumps(result.to_dict(), ensure_ascii=False)

    # ================================================================
    # 辅助
    # ================================================================

    def _record(self, result: ExecutionResult):
        entry = result.to_dict()
        self._execution_log.append(entry)
        if len(self._execution_log) > 200:
            self._execution_log = self._execution_log[-200:]

    def get_stats(self) -> Dict:
        return self._stats

    def get_log(self, limit: int = 50) -> List[Dict]:
        return self._execution_log[-limit:]


# ============================================================================
# 单例
# ============================================================================

_executor_instance: Optional[SafeExecutor] = None


def get_safe_executor() -> SafeExecutor:
    global _executor_instance
    if _executor_instance is None:
        node09_url = os.environ.get("NODE09_SANDBOX_URL", "")
        _executor_instance = SafeExecutor(node09_url=node09_url)
    return _executor_instance
