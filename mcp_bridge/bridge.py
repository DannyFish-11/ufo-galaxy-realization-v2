"""
Galaxy - MCP 多语言桥接实现
================================

核心实现：MCPBridgeLoader 通过子进程 + stdio JSON-RPC 与任意语言编写的 MCP Server 通信，
然后将其注册到 core/mcp_loader 中，使其可以像原生 Python MCP Server 一样被调用。

提示级改进：
- 类型注解全覆盖（PR-type-coverage）
- 统一错误消息格式（PR-error-uniform）
- 模块级 docstring（本段）
- 魔法数字提取为类常量
- 代码注释补充
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.MCPBridge")

# ---------------------------------------------------------------------------
# Constants (extracted magic numbers)
# ---------------------------------------------------------------------------
DEFAULT_STARTUP_TIMEOUT: float = 10.0       # 等待服务器启动的超时时间（秒）
DEFAULT_HEALTH_CHECK_INTERVAL: float = 30.0  # 健康检查间隔（秒）
DEFAULT_REQUEST_TIMEOUT: float = 15.0        # JSON-RPC 请求超时（秒）
MAX_RECONNECT_ATTEMPTS: int = 3              # 最大重连尝试次数
RECONNECT_DELAY_BASE: float = 2.0            # 重连退避基数（秒）
PROCESS_TERMINATE_TIMEOUT: float = 5.0       # 进程终止等待超时（秒）


# ---------------------------------------------------------------------------
# Safe JSON serializer (handles circular references and datetime)
# ---------------------------------------------------------------------------
class SafeJSONEncoder(json.JSONEncoder):
    """JSON encoder that handles circular references, datetime, and non-serializable objects."""

    def default(self, o: Any) -> Any:
        # Handle datetime and date objects (Bug 9 fix)
        if isinstance(o, datetime):
            return o.isoformat()
        if isinstance(o, date):
            return o.isoformat()
        # Handle sets, bytes, and other common non-serializable types
        if isinstance(o, set):
            return list(o)
        if isinstance(o, bytes):
            return o.decode("utf-8", errors="replace")
        if isinstance(o, Exception):
            return f"<{type(o).__name__}: {o}>"
        # Fall back to repr for anything else
        return repr(o)


def _safe_json_dumps(obj: Any) -> str:
    """Safely serialize obj to JSON string, handling circular references and datetime."""
    try:
        return json.dumps(obj, cls=SafeJSONEncoder)
    except (TypeError, ValueError) as e:
        # If circular reference or other serialization error, fall back
        logger.warning("JSON serialization fallback used: %s", e)
        return json.dumps({"_serialization_error": str(e), "_repr": repr(obj)})


# ---------------------------------------------------------------------------
# Metrics container (Bug 11 fix — basic metrics exposure)
# ---------------------------------------------------------------------------
@dataclass
class _BridgeMetrics:
    """In-process counters for bridge observability."""
    bridges_loaded: int = 0
    bridges_failed: int = 0
    reconnections: int = 0
    requests_sent: int = 0
    responses_received: int = 0
    errors: int = 0
    last_error: Optional[str] = None
    started_at: datetime = field(default_factory=lambda: datetime.utcnow())

    def snapshot(self) -> Dict[str, Any]:
        """Return a snapshot dict of current metrics."""
        return {
            "bridges_loaded": self.bridges_loaded,
            "bridges_failed": self.bridges_failed,
            "reconnections": self.reconnections,
            "requests_sent": self.requests_sent,
            "responses_received": self.responses_received,
            "errors": self.errors,
            "last_error": self.last_error,
            "uptime_seconds": (datetime.utcnow() - self.started_at).total_seconds(),
        }


# Module-level metrics singleton
_bridge_metrics = _BridgeMetrics()


def get_metrics() -> Dict[str, Any]:
    """Return the current bridge metrics snapshot."""
    return _bridge_metrics.snapshot()


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------
@dataclass
class MCPBridgeSpec:
    """MCP 桥接服务器规范"""
    server_id: str
    command: str                          # 启动命令，如 "node /path/to/server.js"
    description: str = ""
    env: Dict[str, str] = field(default_factory=dict)
    cwd: Optional[str] = None
    startup_timeout: float = field(default=DEFAULT_STARTUP_TIMEOUT)
    health_check_interval: float = field(default=DEFAULT_HEALTH_CHECK_INTERVAL)


# ---------------------------------------------------------------------------
# Error formatting helper (uniform error messages)
# ---------------------------------------------------------------------------
def _fmt_error(message: str, *, detail: Optional[str] = None, code: Optional[str] = None) -> Dict[str, Any]:
    """Return a uniformly-formatted error dict.

    All bridge errors follow the same shape so callers can inspect
    ``error["error"]`` and ``error["error_code"]`` consistently.
    """
    err: Dict[str, Any] = {"error": message}
    if detail:
        err["detail"] = detail
    if code:
        err["error_code"] = code
    return err


# ---------------------------------------------------------------------------
# MCPBridgeProcess
# ---------------------------------------------------------------------------
class MCPBridgeProcess:
    """管理单个外部 MCP Server 子进程"""

    # Auto-reconnect settings (class constants for visibility)
    _MAX_RECONNECT_ATTEMPTS = MAX_RECONNECT_ATTEMPTS
    _RECONNECT_DELAY_BASE = RECONNECT_DELAY_BASE  # seconds

    def __init__(self, spec: MCPBridgeSpec) -> None:
        self.spec: MCPBridgeSpec = spec
        self._process: Optional[asyncio.subprocess.Process] = None
        self._request_id: int = 0
        self._pending: Dict[int, asyncio.Future] = {}
        self._reader_task: Optional[asyncio.Task] = None
        self._initialized: bool = False
        self._reconnect_attempts: int = 0
        self._reconnect_task: Optional[asyncio.Task] = None

    async def start(self) -> bool:
        """启动子进程并完成 MCP initialize 握手"""
        cmd: List[str] = shlex.split(self.spec.command)
        env: Dict[str, str] = {**os.environ, **self.spec.env}
        try:
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                cwd=self.spec.cwd,
                env=env,
            )
        except Exception as e:
            logger.error("Failed to start bridge process '%s': %s", self.spec.server_id, e)
            _bridge_metrics.bridges_failed += 1
            _bridge_metrics.last_error = f"start_failed: {e}"
            return False

        # 启动读取循环
        self._reader_task = asyncio.create_task(self._read_loop())

        # 发送 initialize
        try:
            resp: Optional[Dict[str, Any]] = await asyncio.wait_for(
                self._send_request("initialize", {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "galaxy", "version": "2.0"},
                }),
                timeout=self.spec.startup_timeout,
            )
            if resp and not resp.get("error"):
                self._initialized = True
                logger.info("MCP bridge '%s' initialized successfully", self.spec.server_id)
                _bridge_metrics.bridges_loaded += 1
                return True
            else:
                logger.error("MCP bridge init failed: %s", resp)
                _bridge_metrics.bridges_failed += 1
                _bridge_metrics.last_error = f"init_failed: {resp}"
                return False
        except asyncio.TimeoutError:
            logger.error("MCP bridge '%s' init timeout", self.spec.server_id)
            _bridge_metrics.bridges_failed += 1
            _bridge_metrics.last_error = "init_timeout"
            return False

    async def stop(self) -> None:
        """停止子进程 — 发送关闭通知后优雅终止 (Bug 10 fix: graceful close)"""
        if self._reconnect_task:
            self._reconnect_task.cancel()
        if self._reader_task:
            self._reader_task.cancel()
        # Bug 10 fix: attempt to send a graceful shutdown notification before terminating
        if self._process and self._process.returncode is None:
            try:
                shutdown_msg = json.dumps({"jsonrpc": "2.0", "method": "shutdown", "params": {}}) + "\n"
                self._process.stdin.write(shutdown_msg.encode())
                await asyncio.wait_for(self._process.stdin.drain(), timeout=1.0)
            except Exception:
                pass  # best-effort graceful notification
        # Cancel all pending futures to prevent leaks
        for req_id, fut in list(self._pending.items()):
            if not fut.done():
                fut.cancel()
        self._pending.clear()
        if self._process:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=PROCESS_TERMINATE_TIMEOUT)
            except Exception:
                self._process.kill()

    async def list_tools(self) -> List[Dict[str, Any]]:
        """列出服务器提供的工具"""
        resp: Optional[Dict[str, Any]] = await self._send_request("tools/list", {})
        if resp and not resp.get("error"):
            return resp.get("result", {}).get("tools", [])
        return []

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        """调用工具"""
        resp: Optional[Dict[str, Any]] = await self._send_request("tools/call", {
            "name": name,
            "arguments": arguments,
        })
        if resp is None:
            return _fmt_error("No response from MCP bridge process", code="no_response")
        if resp.get("error"):
            return _fmt_error("MCP bridge error", detail=resp["error"], code="bridge_error")
        return resp.get("result", {})

    async def _send_request(self, method: str, params: Dict[str, Any], timeout: float = DEFAULT_REQUEST_TIMEOUT) -> Optional[Dict[str, Any]]:
        """发送 JSON-RPC 请求并等待响应"""
        if self._process is None or self._process.returncode is not None:
            # Trigger reconnect if process is dead
            if self._reconnect_task is None or self._reconnect_task.done():
                self._reconnect_task = asyncio.create_task(self._reconnect())
            return None

        self._request_id += 1
        req_id: int = self._request_id
        payload: Dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }

        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[req_id] = fut

        try:
            line: str = _safe_json_dumps(payload) + "\n"
            self._process.stdin.write(line.encode())
            await self._process.stdin.drain()
            _bridge_metrics.requests_sent += 1
            result: Dict[str, Any] = await asyncio.wait_for(fut, timeout=timeout)
            _bridge_metrics.responses_received += 1
            return result
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            if not fut.done():
                fut.cancel()
            _bridge_metrics.errors += 1
            _bridge_metrics.last_error = f"request_timeout:{method}"
            return None
        except Exception as e:
            self._pending.pop(req_id, None)
            if not fut.done():
                fut.cancel()
            # Bug 12 fix: use debug for routine errors, error for unexpected ones
            logger.debug("Bridge request error for method '%s': %s", method, e)
            _bridge_metrics.errors += 1
            _bridge_metrics.last_error = f"request_error:{method}:{e}"
            return None

    async def _read_loop(self) -> None:
        """持续读取子进程的 stdout 并分发响应"""
        try:
            while self._process and self._process.returncode is None:
                line: bytes = await self._process.stdout.readline()
                if not line:
                    break
                try:
                    msg: Dict[str, Any] = json.loads(line.decode().strip())
                    req_id: Optional[int] = msg.get("id")
                    if req_id is not None and req_id in self._pending:
                        fut: asyncio.Future = self._pending.pop(req_id)
                        if not fut.done():
                            fut.set_result(msg)
                except json.JSONDecodeError:
                    pass  # 忽略非 JSON 行（debug 输出等）
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Bridge read loop error: %s", e)
            _bridge_metrics.errors += 1
            _bridge_metrics.last_error = f"read_loop_error:{e}"
        finally:
            # Auto-reconnect on disconnect (Bug 11 fix)
            if self._reconnect_attempts < self._MAX_RECONNECT_ATTEMPTS:
                self._reconnect_task = asyncio.create_task(self._reconnect())

    async def _reconnect(self) -> None:
        """Attempt to reconnect after disconnect with exponential backoff."""
        self._reconnect_attempts += 1
        delay: float = self._RECONNECT_DELAY_BASE * (2 ** (self._reconnect_attempts - 1))
        logger.warning(
            "MCP bridge '%s' disconnected. Reconnect attempt %d/%d in %.1fs",
            self.spec.server_id, self._reconnect_attempts, self._MAX_RECONNECT_ATTEMPTS, delay,
        )
        _bridge_metrics.reconnections += 1
        await asyncio.sleep(delay)
        ok: bool = await self.start()
        if ok:
            logger.info("MCP bridge '%s' reconnected successfully", self.spec.server_id)
            self._reconnect_attempts = 0
        else:
            logger.error(
                "MCP bridge '%s' reconnect attempt %d failed",
                self.spec.server_id, self._reconnect_attempts,
            )

    @property
    def alive(self) -> bool:
        return self._process is not None and self._process.returncode is None


# ---------------------------------------------------------------------------
# MCPBridgeLoader
# ---------------------------------------------------------------------------
class MCPBridgeLoader:
    """管理多个桥接 MCP 服务器 — 单例模式，线程安全"""

    _instance: Optional["MCPBridgeLoader"] = None
    _lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        self._bridges: Dict[str, MCPBridgeProcess] = {}

    @classmethod
    def get_instance(cls) -> "MCPBridgeLoader":
        # Thread-safe singleton with double-checked locking
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    async def load(self, spec: MCPBridgeSpec) -> Dict[str, Any]:
        """加载一个桥接 MCP 服务器

        成功后自动注册到 core/mcp_loader 中，
        可通过 /api/v1/mcp/call 调用其工具。
        """
        proc: MCPBridgeProcess = MCPBridgeProcess(spec)
        ok: bool = await proc.start()
        if not ok:
            return _fmt_error(f"Failed to start bridge: {spec.server_id}", code="start_failed")

        self._bridges[spec.server_id] = proc

        # 注册到 core/mcp_loader
        try:
            from core.mcp_loader import mcp_loader
            # mcp_loader 支持用命令加载，复用其接口
            await mcp_loader.load(spec.server_id, command=spec.command)
            logger.debug("Bridge server '%s' registered in mcp_loader", spec.server_id)
        except Exception as e:
            # Bug 12 fix: downgrade to debug — non-fatal optional integration
            logger.debug("Could not register bridge in mcp_loader (non-fatal): %s", e)

        tools: List[Dict[str, Any]] = await proc.list_tools()
        return {
            "success": True,
            "server_id": spec.server_id,
            "tools_count": len(tools),
            "tools": [t.get("name") for t in tools],
        }

    async def unload(self, server_id: str) -> Dict[str, Any]:
        """停止并注销桥接服务器"""
        proc: Optional[MCPBridgeProcess] = self._bridges.pop(server_id, None)
        if proc is None:
            return _fmt_error(f"Bridge not loaded: {server_id}", code="not_loaded")
        await proc.stop()
        return {"success": True, "server_id": server_id}

    async def call_tool(self, server_id: str, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """调用桥接服务器的工具"""
        proc: Optional[MCPBridgeProcess] = self._bridges.get(server_id)
        if proc is None:
            return _fmt_error(f"Bridge not loaded: {server_id}", code="not_loaded")
        return await proc.call_tool(tool_name, arguments)

    async def list_tools(self, server_id: str) -> List[Dict[str, Any]]:
        """列出桥接服务器的工具"""
        proc: Optional[MCPBridgeProcess] = self._bridges.get(server_id)
        if proc is None:
            return []
        return await proc.list_tools()

    def list_servers(self) -> List[Dict[str, Any]]:
        """列出所有已加载的桥接服务器"""
        return [
            {
                "server_id": sid,
                "alive": proc.alive,
                "initialized": proc._initialized,
                "command": proc.spec.command,
                "description": proc.spec.description,
            }
            for sid, proc in self._bridges.items()
        ]


# ---------------------------------------------------------------------------
# Public API helpers
# ---------------------------------------------------------------------------
def get_bridge_loader() -> MCPBridgeLoader:
    """Return the singleton MCPBridgeLoader instance."""
    return MCPBridgeLoader.get_instance()


async def load_bridge_server(spec: MCPBridgeSpec) -> Dict[str, Any]:
    """便捷函数：加载一个桥接 MCP 服务器"""
    return await get_bridge_loader().load(spec)
