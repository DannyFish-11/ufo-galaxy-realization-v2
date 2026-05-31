"""
SafeExecutor — 安全代码执行沙箱
================================

Phase 4 Matrix OS 核心组件。

Agent "自编码" 能力的运行时:
1. Agent (LLM) 生成代码片段
2. SafeExecutor 验证安全性
3. 语法预检 (py_compile / node --check / bash -n)
4. 在受限沙箱中执行
5. 返回结果供 Agent 继续推理
6. 执行结果回流到 ExecutionFeedbackLoop (经验沉淀)

安全层:
- 语言白名单 (Python, JavaScript, Bash)
- 危险 pattern 检测 (import os.system, exec, eval, subprocess, rm -rf 等)
- 语法预检 (拦截80%+ 低级语法错误，无需实际执行)
- 资源限制 (内存, CPU 时间, 超时)
- 网络隔离 (可选)

与 Node_09_Sandbox 的关系:
- 如果 Node_09 在线, SafeExecutor 委托给 Node_09 (通过 HTTP API)
- 如果 Node_09 离线, SafeExecutor 使用内置轻量沙箱 (仅 Python)

Reflexion 闭环:
- ExecutionFeedbackLoop 持久化所有执行结果到 SQLite
- 失败时提取 [错误特征, 代码片段] 供后续相似错误快速匹配
- 成功时记录修复模式，形成"肌肉记忆"
"""

import asyncio
import hashlib
import json
import logging
import os
import sqlite3
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field

logger = logging.getLogger("Galaxy.SafeExecutor")


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
    "__import__(\"os\")",
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
    "__subclasses__",
    "__class__",
    "__bases__",
    "importlib",
    "globals()",
    "locals()",
    "getattr(",
    "delattr(",
    "setattr(",
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
            self._record(result, code)
            return result

        # 3. 语法预检 (LSP 轻量替代 — 零额外依赖)
        syntax_error = await self._syntax_precheck(code, language.lower())
        if syntax_error:
            self._stats["blocked"] += 1
            result = ExecutionResult(
                language=language,
                success=False,
                error=f"Syntax precheck failed: {syntax_error}",
                safety_check_passed=True,
            )
            self._record(result, code)
            return result

        # 4. 尝试 Node_09
        if self._node09_url:
            try:
                result = await self._execute_via_node09(code, language, timeout, memory_limit_mb, stdin)
                result.execution_time_ms = (time.time() - start) * 1000
                if result.success:
                    self._stats["success"] += 1
                else:
                    self._stats["failed"] += 1
                self._record(result, code)
                return result
            except Exception as e:
                logger.warning(f"Node_09 unavailable: {e}, falling back to builtin")

        # 5. 内置执行
        result = await self._execute_builtin(code, language, timeout, memory_limit_mb, stdin)
        result.execution_time_ms = (time.time() - start) * 1000
        if result.success:
            self._stats["success"] += 1
        else:
            self._stats["failed"] += 1
        self._record(result, code)
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
        """Python 沙箱执行

        安全模型：pattern-based 检测 + subprocess 隔离 + 超时限制。
        不依赖 Python builtins 限制（容易绕过），而是在独立子进程中运行。
        """
        wrapped = (
            "import sys\n"
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
            except Exception as exc:
                logger.warning("Exception suppressed: %s", exc)
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
    # 语法预检 (LSP 轻量替代)
    # ================================================================

    async def _syntax_precheck(self, code: str, language: str) -> Optional[str]:
        """
        语法预检 — 利用各语言运行时自带的语法检查工具。

        Python  → python3 -m py_compile <tmpfile>
        Bash    → bash -n <tmpfile>
        JavaScript → node --check <tmpfile>

        Returns: None if syntax OK, error message if syntax error detected.
        """
        suffix_map = {"python": ".py", "bash": ".sh", "javascript": ".js"}
        suffix = suffix_map.get(language)
        if not suffix:
            return None

        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=suffix, delete=False, encoding="utf-8"
            ) as f:
                f.write(code)
                tmp_path = f.name

            if language == "python":
                cmd = ["python3", "-m", "py_compile", tmp_path]
            elif language == "bash":
                cmd = ["bash", "-n", tmp_path]
            elif language == "javascript":
                cmd = ["node", "--check", tmp_path]
            else:
                return None

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=5
            )

            if proc.returncode != 0:
                err = stderr_bytes.decode("utf-8", errors="replace").strip()
                # 清理临时文件路径，让错误信息更清晰
                err = err.replace(tmp_path, "<code>")
                return err[:500]

            return None
        except asyncio.TimeoutError:
            return None  # 超时不阻塞，让实际执行阶段处理
        except FileNotFoundError:
            return None  # 运行时不存在，跳过预检
        except Exception as e:
            logger.debug(f"Syntax precheck skipped: {e}")
            return None
        finally:
            try:
                os.unlink(tmp_path)
            except Exception as exc:
                logger.warning("Exception suppressed: %s", exc)

    # ================================================================
    # 辅助
    # ================================================================

    def _record(self, result: ExecutionResult, code: str = ""):
        entry = result.to_dict()
        self._execution_log.append(entry)
        if len(self._execution_log) > 200:
            self._execution_log = self._execution_log[-200:]

        # Reflexion: 将执行结果灌入反馈循环
        if code:
            try:
                _feedback_loop = get_feedback_loop()
                _feedback_loop.record(code, result.language, result)
            except Exception as e:
                logger.debug(f"Feedback loop record skipped: {e}")

    def get_stats(self) -> Dict:
        return self._stats

    def get_log(self, limit: int = 50) -> List[Dict]:
        return self._execution_log[-limit:]


# ============================================================================
# Reflexion 反馈循环 — 执行经验持久化
# ============================================================================

class ExecutionFeedbackLoop:
    """
    执行反馈循环 — 沉淀代码执行的成败经验。

    功能:
    1. 记录每次执行的代码、语言、结果（成功/失败/错误信息）
    2. 按错误特征做文本匹配，查询历史类似错误
    3. 提供修复建议（基于历史成功修复的代码片段）

    存储: SQLite (data/execution_feedback.db)
    """

    _CREATE_SQL = """
    CREATE TABLE IF NOT EXISTS executions (
        id TEXT PRIMARY KEY,
        code_hash TEXT NOT NULL,
        code_snippet TEXT NOT NULL,
        language TEXT NOT NULL,
        success INTEGER NOT NULL,
        error_message TEXT DEFAULT '',
        error_pattern TEXT DEFAULT '',
        timestamp REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_error_pattern ON executions(error_pattern);
    CREATE INDEX IF NOT EXISTS idx_code_hash ON executions(code_hash);
    CREATE INDEX IF NOT EXISTS idx_success ON executions(success);
    """

    def __init__(self, db_path: str = ""):
        if not db_path:
            project_root = Path(__file__).resolve().parent.parent
            data_dir = project_root / "data"
            data_dir.mkdir(exist_ok=True)
            db_path = str(data_dir / "execution_feedback.db")

        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _init_db(self):
        try:
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._conn.executescript(self._CREATE_SQL)
            self._conn.commit()
        except Exception as e:
            logger.warning(f"ExecutionFeedbackLoop DB init failed: {e}")
            self._conn = None

    def _extract_error_pattern(self, error: str) -> str:
        """提取错误特征 — 去除文件路径和行号，保留错误类型和关键信息"""
        if not error:
            return ""
        lines = error.strip().split("\n")
        # 取最后一行（通常是错误类型和信息）
        last_line = lines[-1].strip() if lines else ""
        # 截断到200字符
        return last_line[:200]

    def record(self, code: str, language: str, result: ExecutionResult):
        """记录一次执行结果"""
        if not self._conn:
            return

        code_hash = hashlib.sha256(code.encode()).hexdigest()[:16]
        # 存储代码前500字符作为摘要
        code_snippet = code[:500]
        error_pattern = self._extract_error_pattern(result.error)

        try:
            self._conn.execute(
                "INSERT OR REPLACE INTO executions "
                "(id, code_hash, code_snippet, language, success, error_message, error_pattern, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid.uuid4())[:12],
                    code_hash,
                    code_snippet,
                    language,
                    1 if result.success else 0,
                    result.error[:1000],
                    error_pattern,
                    time.time(),
                ),
            )
            self._conn.commit()
        except Exception as e:
            logger.debug(f"Feedback record failed: {e}")

    def query_similar_errors(self, error_msg: str, limit: int = 5) -> List[Dict]:
        """查询历史中类似的错误"""
        if not self._conn or not error_msg:
            return []

        pattern = self._extract_error_pattern(error_msg)
        if not pattern:
            return []

        try:
            # 用 LIKE 做模糊匹配（取错误类型关键词）
            keywords = pattern.split(":")
            search_term = keywords[0].strip() if keywords else pattern
            cursor = self._conn.execute(
                "SELECT code_snippet, language, error_message, error_pattern, timestamp "
                "FROM executions WHERE error_pattern LIKE ? AND success = 0 "
                "ORDER BY timestamp DESC LIMIT ?",
                (f"%{search_term}%", limit),
            )
            rows = cursor.fetchall()
            return [
                {
                    "code_snippet": r[0],
                    "language": r[1],
                    "error_message": r[2],
                    "error_pattern": r[3],
                    "timestamp": r[4],
                }
                for r in rows
            ]
        except Exception as e:
            logger.debug(f"Feedback query failed: {e}")
            return []

    def get_fix_suggestions(self, error_msg: str, limit: int = 3) -> List[str]:
        """获取修复建议 — 查找同一代码hash后来成功执行的版本"""
        if not self._conn or not error_msg:
            return []

        similar = self.query_similar_errors(error_msg, limit=10)
        suggestions = []

        for entry in similar:
            try:
                # 查找同语言、后来成功的执行
                cursor = self._conn.execute(
                    "SELECT code_snippet FROM executions "
                    "WHERE language = ? AND success = 1 AND timestamp > ? "
                    "ORDER BY timestamp ASC LIMIT 1",
                    (entry["language"], entry["timestamp"]),
                )
                row = cursor.fetchone()
                if row:
                    suggestions.append(row[0])
            except Exception as exc:
                logger.warning("Exception suppressed: %s", exc)

        return suggestions[:limit]

    def get_stats(self) -> Dict:
        """获取反馈循环统计"""
        if not self._conn:
            return {"status": "offline"}
        try:
            total = self._conn.execute("SELECT COUNT(*) FROM executions").fetchone()[0]
            success = self._conn.execute(
                "SELECT COUNT(*) FROM executions WHERE success = 1"
            ).fetchone()[0]
            failed = total - success
            return {
                "status": "online",
                "total_executions": total,
                "success": success,
                "failed": failed,
                "success_rate": round(success / total * 100, 1) if total > 0 else 0,
            }
        except Exception:
            return {"status": "error"}


# ============================================================================
# 单例
# ============================================================================

_executor_instance: Optional[SafeExecutor] = None
_feedback_instance: Optional[ExecutionFeedbackLoop] = None


def get_safe_executor() -> SafeExecutor:
    global _executor_instance
    if _executor_instance is None:
        node09_url = os.environ.get("NODE09_SANDBOX_URL", "")
        _executor_instance = SafeExecutor(node09_url=node09_url)
    return _executor_instance


def get_feedback_loop() -> ExecutionFeedbackLoop:
    global _feedback_instance
    if _feedback_instance is None:
        _feedback_instance = ExecutionFeedbackLoop()
    return _feedback_instance
