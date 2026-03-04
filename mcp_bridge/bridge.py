"""
UFO Galaxy - MCP 多语言桥接实现
================================

核心实现：MCPBridgeLoader 通过子进程 + stdio JSON-RPC 与任意语言编写的 MCP Server 通信，
然后将其注册到 core/mcp_loader 中，使其可以像原生 Python MCP Server 一样被调用。
"""

import asyncio
import json
import logging
import os
import shlex
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("UFO-Galaxy.MCPBridge")


@dataclass
class MCPBridgeSpec:
    """MCP 桥接服务器规范"""
    server_id: str
    command: str                          # 启动命令，如 "node /path/to/server.js"
    description: str = ""
    env: Dict[str, str] = field(default_factory=dict)
    cwd: Optional[str] = None
    startup_timeout: float = 10.0        # 等待服务器启动的超时时间（秒）
    health_check_interval: float = 30.0  # 健康检查间隔（秒）


class MCPBridgeProcess:
    """管理单个外部 MCP Server 子进程"""

    def __init__(self, spec: MCPBridgeSpec):
        self.spec = spec
        self._process: Optional[asyncio.subprocess.Process] = None
        self._request_id = 0
        self._pending: Dict[int, asyncio.Future] = {}
        self._reader_task: Optional[asyncio.Task] = None
        self._initialized = False

    async def start(self) -> bool:
        """启动子进程并完成 MCP initialize 握手"""
        cmd = shlex.split(self.spec.command)
        env = {**os.environ, **self.spec.env}
        try:
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.spec.cwd,
                env=env,
            )
        except Exception as e:
            logger.error(f"Failed to start bridge process '{self.spec.server_id}': {e}")
            return False

        # 启动读取循环
        self._reader_task = asyncio.create_task(self._read_loop())

        # 发送 initialize
        try:
            resp = await asyncio.wait_for(
                self._send_request("initialize", {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "ufo-galaxy", "version": "2.0"},
                }),
                timeout=self.spec.startup_timeout,
            )
            if resp and not resp.get("error"):
                self._initialized = True
                logger.info(f"MCP bridge '{self.spec.server_id}' initialized successfully")
                return True
            else:
                logger.error(f"MCP bridge init failed: {resp}")
                return False
        except asyncio.TimeoutError:
            logger.error(f"MCP bridge '{self.spec.server_id}' init timeout")
            return False

    async def stop(self) -> None:
        """停止子进程"""
        if self._reader_task:
            self._reader_task.cancel()
        if self._process:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except Exception:
                self._process.kill()

    async def list_tools(self) -> List[Dict]:
        """列出服务器提供的工具"""
        resp = await self._send_request("tools/list", {})
        if resp and not resp.get("error"):
            return resp.get("result", {}).get("tools", [])
        return []

    async def call_tool(self, name: str, arguments: Dict) -> Any:
        """调用工具"""
        resp = await self._send_request("tools/call", {
            "name": name,
            "arguments": arguments,
        })
        if resp is None:
            return {"error": "No response from MCP bridge process"}
        if resp.get("error"):
            return {"error": resp["error"]}
        return resp.get("result", {})

    async def _send_request(self, method: str, params: Dict, timeout: float = 15.0) -> Optional[Dict]:
        """发送 JSON-RPC 请求并等待响应"""
        if self._process is None or self._process.returncode is not None:
            return None

        self._request_id += 1
        req_id = self._request_id
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }

        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[req_id] = fut

        try:
            line = json.dumps(payload) + "\n"
            self._process.stdin.write(line.encode())
            await self._process.stdin.drain()
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            return None
        except Exception as e:
            self._pending.pop(req_id, None)
            logger.error(f"Bridge request error: {e}")
            return None

    async def _read_loop(self) -> None:
        """持续读取子进程的 stdout 并分发响应"""
        try:
            while self._process and self._process.returncode is None:
                line = await self._process.stdout.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line.decode().strip())
                    req_id = msg.get("id")
                    if req_id is not None and req_id in self._pending:
                        fut = self._pending.pop(req_id)
                        if not fut.done():
                            fut.set_result(msg)
                except json.JSONDecodeError:
                    pass  # 忽略非 JSON 行（debug 输出等）
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Bridge read loop error: {e}")

    @property
    def alive(self) -> bool:
        return self._process is not None and self._process.returncode is None


class MCPBridgeLoader:
    """管理多个桥接 MCP 服务器"""

    _instance = None

    def __init__(self):
        self._bridges: Dict[str, MCPBridgeProcess] = {}

    @classmethod
    def get_instance(cls) -> "MCPBridgeLoader":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def load(self, spec: MCPBridgeSpec) -> Dict[str, Any]:
        """
        加载一个桥接 MCP 服务器

        成功后自动注册到 core/mcp_loader 中，
        可通过 /api/v1/mcp/call 调用其工具。
        """
        proc = MCPBridgeProcess(spec)
        ok = await proc.start()
        if not ok:
            return {"success": False, "error": f"Failed to start bridge: {spec.server_id}"}

        self._bridges[spec.server_id] = proc

        # 注册到 core/mcp_loader
        try:
            from core.mcp_loader import mcp_loader
            # mcp_loader 支持用命令加载，复用其接口
            await mcp_loader.load(spec.server_id, command=spec.command)
            logger.info(f"Bridge server '{spec.server_id}' registered in mcp_loader")
        except Exception as e:
            logger.warning(f"Could not register bridge in mcp_loader (non-fatal): {e}")

        tools = await proc.list_tools()
        return {
            "success": True,
            "server_id": spec.server_id,
            "tools_count": len(tools),
            "tools": [t.get("name") for t in tools],
        }

    async def unload(self, server_id: str) -> Dict[str, Any]:
        """停止并注销桥接服务器"""
        proc = self._bridges.pop(server_id, None)
        if proc is None:
            return {"success": False, "error": f"Bridge not loaded: {server_id}"}
        await proc.stop()
        return {"success": True, "server_id": server_id}

    async def call_tool(self, server_id: str, tool_name: str, arguments: Dict) -> Any:
        """调用桥接服务器的工具"""
        proc = self._bridges.get(server_id)
        if proc is None:
            return {"error": f"Bridge not loaded: {server_id}"}
        return await proc.call_tool(tool_name, arguments)

    async def list_tools(self, server_id: str) -> List[Dict]:
        """列出桥接服务器的工具"""
        proc = self._bridges.get(server_id)
        if proc is None:
            return []
        return await proc.list_tools()

    def list_servers(self) -> List[Dict]:
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


def get_bridge_loader() -> MCPBridgeLoader:
    return MCPBridgeLoader.get_instance()


async def load_bridge_server(spec: MCPBridgeSpec) -> Dict[str, Any]:
    """便捷函数：加载一个桥接 MCP 服务器"""
    return await get_bridge_loader().load(spec)
