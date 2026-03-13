"""
Galaxy - 标准 MCP 加载器
============================

完全兼容 Model Context Protocol 标准协议
支持动态加载任何符合 MCP 标准的服务器

标准协议参考:
https://github.com/modelcontextprotocol/specification

使用方法:
    from core.mcp_loader import mcp_loader
    
    # 加载 MCP 服务器 (用户自己下载的)
    await mcp_loader.load("my-server", command="node /path/to/server.js")
    
    # 列出已加载的服务器
    servers = mcp_loader.list_servers()
    
    # 获取服务器的工具
    tools = await mcp_loader.list_tools("my-server")
    
    # 调用工具
    result = await mcp_loader.call_tool("my-server", "tool_name", {...})
    
    # 卸载服务器
    await mcp_loader.unload("my-server")
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from pathlib import Path
from enum import Enum
import uuid

logger = logging.getLogger("Galaxy.MCP")

# C阶段 2C: 工具调用守护（可选依赖，默认不启用）
try:
    from core.tool_guardian import GuardedCallConfig, call_with_guardian, ToolGuardianBlockedError
    _GUARDIAN_AVAILABLE = True
except ImportError:
    _GUARDIAN_AVAILABLE = False
    GuardedCallConfig = None  # type: ignore
    ToolGuardianBlockedError = None  # type: ignore


# ============================================================================
# MCP 标准协议定义
# ============================================================================

class MCPMessageType(str, Enum):
    """MCP 消息类型"""
    REQUEST = "request"
    RESPONSE = "response"
    NOTIFICATION = "notification"


@dataclass
class MCPRequest:
    """MCP 请求 - 标准格式"""
    jsonrpc: str = "2.0"
    id: Optional[int] = None
    method: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
    
    def to_json(self) -> str:
        return json.dumps({
            "jsonrpc": self.jsonrpc,
            "id": self.id,
            "method": self.method,
            "params": self.params,
        })


@dataclass
class MCPResponse:
    """MCP 响应 - 标准格式"""
    jsonrpc: str = "2.0"
    id: Optional[int] = None
    result: Optional[Any] = None
    error: Optional[Dict] = None
    
    @classmethod
    def from_json(cls, data: str) -> "MCPResponse":
        obj = json.loads(data)
        return cls(
            jsonrpc=obj.get("jsonrpc", "2.0"),
            id=obj.get("id"),
            result=obj.get("result"),
            error=obj.get("error"),
        )


@dataclass
class MCPTool:
    """MCP 工具定义 - 标准格式"""
    name: str
    description: str
    inputSchema: Dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def from_dict(cls, data: Dict) -> "MCPTool":
        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            inputSchema=data.get("inputSchema", {}),
        )


@dataclass
class MCPResource:
    """MCP 资源定义 - 标准格式"""
    uri: str
    name: str
    description: str = ""
    mimeType: str = ""
    
    @classmethod
    def from_dict(cls, data: Dict) -> "MCPResource":
        return cls(
            uri=data.get("uri", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            mimeType=data.get("mimeType", ""),
        )


@dataclass
class MCPPrompt:
    """MCP 提示定义 - 标准格式"""
    name: str
    description: str
    arguments: List[Dict] = field(default_factory=list)
    
    @classmethod
    def from_dict(cls, data: Dict) -> "MCPPrompt":
        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            arguments=data.get("arguments", []),
        )


# ============================================================================
# MCP 服务器实例
# ============================================================================

class MCPServerStatus(str, Enum):
    """服务器状态"""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"


@dataclass
class MCPServerInstance:
    """MCP 服务器实例"""
    id: str
    name: str
    command: List[str]
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    cwd: str = ""
    
    status: MCPServerStatus = MCPServerStatus.STOPPED
    process: Optional[subprocess.Popen] = None
    error: Optional[str] = None
    
    # 服务器能力
    tools: List[MCPTool] = field(default_factory=list)
    resources: List[MCPResource] = field(default_factory=list)
    prompts: List[MCPPrompt] = field(default_factory=list)
    
    # 元数据
    server_info: Dict[str, Any] = field(default_factory=dict)
    capabilities: Dict[str, Any] = field(default_factory=dict)
    
    created_at: float = field(default_factory=lambda: datetime.now().timestamp())
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "command": self.command,
            "args": self.args,
            "status": self.status.value,
            "error": self.error,
            "tools_count": len(self.tools),
            "resources_count": len(self.resources),
            "prompts_count": len(self.prompts),
            "server_info": self.server_info,
            "capabilities": self.capabilities,
            "created_at": self.created_at,
        }


# ============================================================================
# MCP 加载器
# ============================================================================

class MCPLoader:
    """
    标准 MCP 加载器
    
    完全兼容 Model Context Protocol 标准
    支持动态加载任何符合 MCP 标准的服务器
    """
    
    _instance = None
    
    def __init__(self):
        self.servers: Dict[str, MCPServerInstance] = {}
        self._request_id = 0
        
        logger.info("MCP 加载器初始化")
    
    @classmethod
    def get_instance(cls) -> "MCPLoader":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    # ========================================================================
    # 加载/卸载
    # ========================================================================
    
    async def load(
        self,
        name: str,
        command: str | List[str],
        args: List[str] = None,
        env: Dict[str, str] = None,
        cwd: str = "",
        auto_start: bool = True,
    ) -> Dict[str, Any]:
        """
        加载 MCP 服务器
        
        Args:
            name: 服务器名称 (用户自定义)
            command: 启动命令
                - 字符串: "node /path/to/server.js"
                - 列表: ["node", "/path/to/server.js"]
                - npx: "npx -y @modelcontextprotocol/server-filesystem"
                - python: "python /path/to/server.py"
            args: 命令行参数
            env: 环境变量
            cwd: 工作目录
            auto_start: 是否自动启动
        
        Returns:
            加载结果
        """
        # 生成唯一 ID
        server_id = str(uuid.uuid4())[:8]
        
        # 解析命令
        if isinstance(command, str):
            command = command.split()
        
        # 创建服务器实例
        server = MCPServerInstance(
            id=server_id,
            name=name,
            command=command,
            args=args or [],
            env=env or {},
            cwd=cwd,
        )
        
        self.servers[server_id] = server
        
        if auto_start:
            success = await self.start(server_id)
            if not success:
                return {
                    "success": False,
                    "error": server.error,
                    "server_id": server_id,
                }
        
        return {
            "success": True,
            "server_id": server_id,
            "name": name,
            "status": server.status.value,
        }
    
    async def unload(self, server_id: str) -> Dict[str, Any]:
        """
        卸载 MCP 服务器
        
        Args:
            server_id: 服务器 ID
        
        Returns:
            卸载结果
        """
        if server_id not in self.servers:
            return {"success": False, "error": "服务器不存在"}
        
        # 先停止
        await self.stop(server_id)
        
        # 从能力总线移除该服务器的所有工具
        server = self.servers[server_id]
        self._eject_server_from_registry(server_id, server)

        # 移除
        server = self.servers.pop(server_id)
        
        return {
            "success": True,
            "server_id": server_id,
            "name": server.name,
        }

    def _inject_server_to_registry(self, server_id: str) -> None:
        """将 MCP 服务器的工具注入能力总线（在初始化完成后调用）。"""
        try:
            from core.agent.capability_registry import CapabilityRegistry
            server = self.servers.get(server_id)
            if not server:
                return
            reg = CapabilityRegistry.get_instance()
            for tool in getattr(server, "tools", []):
                reg.inject_mcp_tool(
                    server_id=server_id,
                    tool_name=tool.name,
                    description=tool.description,
                    parameters=tool.inputSchema or {},
                    server_name=server.name,
                )
            logger.info(
                "MCP 服务器 %s (%s) 的 %d 个工具已注入能力总线",
                server.name, server_id, len(server.tools),
            )
        except Exception as exc:
            logger.debug("MCP 工具注入能力总线失败（不影响正常运行）: %s", exc)

    def _eject_server_from_registry(self, server_id: str, server: "MCPServerInstance") -> None:
        """从能力总线移除 MCP 服务器的所有工具。"""
        try:
            from core.agent.capability_registry import CapabilityRegistry
            reg = CapabilityRegistry.get_instance()
            for tool in getattr(server, "tools", []):
                reg.eject(f"mcp__{server_id}__{tool.name}")
            logger.info("MCP 服务器 %s 的工具已从能力总线移除", server_id)
        except Exception as exc:
            logger.debug("MCP 工具从能力总线移除失败: %s", exc)
    
    async def start(self, server_id: str) -> bool:
        """启动服务器"""
        server = self.servers.get(server_id)
        if not server:
            return False
        
        try:
            server.status = MCPServerStatus.STARTING
            
            # 准备环境变量
            env = os.environ.copy()
            env.update(server.env)
            
            # 完整命令
            full_command = server.command + server.args
            
            # 启动进程
            server.process = subprocess.Popen(
                full_command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                cwd=server.cwd or None,
            )
            
            # 等待启动
            await asyncio.sleep(0.5)
            
            if server.process.poll() is not None:
                server.status = MCPServerStatus.ERROR
                server.error = server.process.stderr.read().decode()
                return False
            
            # 初始化连接
            await self._initialize(server_id)
            
            server.status = MCPServerStatus.RUNNING
            logger.info(f"MCP 服务器已启动: {server.name} ({server_id})")
            return True
            
        except Exception as e:
            server.status = MCPServerStatus.ERROR
            server.error = str(e)
            logger.error(f"启动 MCP 服务器失败: {e}")
            return False
    
    async def stop(self, server_id: str) -> bool:
        """停止服务器"""
        server = self.servers.get(server_id)
        if not server:
            return False
        
        if server.process:
            try:
                server.process.terminate()
                server.process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired) as e:
                logger.warning(f"MCP 进程 terminate 失败，强制 kill: {e}")
                try:
                    server.process.kill()
                except OSError:
                    pass
            server.process = None
        
        server.status = MCPServerStatus.STOPPED
        logger.info(f"MCP 服务器已停止: {server.name}")
        return True
    
    # ========================================================================
    # MCP 协议通信
    # ========================================================================
    
    async def _send_request(
        self,
        server_id: str,
        method: str,
        params: Dict = None,
    ) -> Optional[MCPResponse]:
        """发送 MCP 请求"""
        server = self.servers.get(server_id)
        if not server or not server.process:
            return None
        
        self._request_id += 1
        request = MCPRequest(
            id=self._request_id,
            method=method,
            params=params or {},
        )
        
        try:
            # 发送请求
            server.process.stdin.write((request.to_json() + "\n").encode())
            server.process.stdin.flush()
            
            # 读取响应
            response_line = server.process.stdout.readline().decode()
            if response_line:
                return MCPResponse.from_json(response_line)
            
        except Exception as e:
            logger.error(f"MCP 请求失败: {method} - {e}")
        
        return None
    
    async def _initialize(self, server_id: str) -> bool:
        """初始化 MCP 连接"""
        # 发送 initialize 请求
        response = await self._send_request(
            server_id,
            "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {
                    "roots": {"listChanged": True},
                },
                "clientInfo": {
                    "name": "Galaxy",
                    "version": "2.0.0",
                },
            },
        )
        
        if response and response.result:
            server = self.servers[server_id]
            server.server_info = response.result.get("serverInfo", {})
            server.capabilities = response.result.get("capabilities", {})
            
            # 发送 initialized 通知
            await self._send_notification(server_id, "notifications/initialized")
            
            # 获取工具列表
            await self._refresh_tools(server_id)
            
            # 获取资源列表
            await self._refresh_resources(server_id)
            
            # 获取提示列表
            await self._refresh_prompts(server_id)

            # 加载完成后自动注入能力总线
            self._inject_server_to_registry(server_id)

            return True
        
        return False
    
    async def _send_notification(self, server_id: str, method: str, params: Dict = None):
        """发送 MCP 通知"""
        server = self.servers.get(server_id)
        if not server or not server.process:
            return
        
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
        }
        
        server.process.stdin.write((json.dumps(notification) + "\n").encode())
        server.process.stdin.flush()
    
    async def _refresh_tools(self, server_id: str):
        """刷新工具列表"""
        response = await self._send_request(server_id, "tools/list", {})
        if response and response.result:
            server = self.servers[server_id]
            server.tools = [
                MCPTool.from_dict(t)
                for t in response.result.get("tools", [])
            ]
    
    async def _refresh_resources(self, server_id: str):
        """刷新资源列表"""
        response = await self._send_request(server_id, "resources/list", {})
        if response and response.result:
            server = self.servers[server_id]
            server.resources = [
                MCPResource.from_dict(r)
                for r in response.result.get("resources", [])
            ]
    
    async def _refresh_prompts(self, server_id: str):
        """刷新提示列表"""
        response = await self._send_request(server_id, "prompts/list", {})
        if response and response.result:
            server = self.servers[server_id]
            server.prompts = [
                MCPPrompt.from_dict(p)
                for p in response.result.get("prompts", [])
            ]
    
    # ========================================================================
    # 工具调用
    # ========================================================================
    
    async def call_tool(
        self,
        server_id: str,
        tool_name: str,
        arguments: Dict[str, Any] = None,
        guardian_config: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        调用 MCP 工具

        C阶段 2C: 若传入 guardian_config（GuardedCallConfig, enabled=True），
                  则在调用前进行风险评分/拦截，失败时触发重试/回滚。
                  guardian_config=None 或 enabled=False 时行为与之前完全相同。

        Args:
            server_id:       服务器 ID
            tool_name:       工具名称
            arguments:       参数
            guardian_config: 可选 GuardedCallConfig（C阶段 2C 守护配置）

        Returns:
            执行结果
        """
        server = self.servers.get(server_id)
        if not server:
            return {"success": False, "error": "服务器不存在"}

        if server.status != MCPServerStatus.RUNNING:
            return {"success": False, "error": "服务器未运行"}

        # C阶段 2C: 守护包装（enabled=False 时直通）
        if (
            _GUARDIAN_AVAILABLE
            and guardian_config is not None
            and getattr(guardian_config, "enabled", False)
        ):
            try:
                return await call_with_guardian(
                    fn=self._raw_call_tool,
                    fn_args=(server_id, tool_name, arguments),
                    tool_name=tool_name,
                    config=guardian_config,
                )
            except ToolGuardianBlockedError as blocked:
                return {
                    "success": False,
                    "error": str(blocked),
                    "isError": True,
                    "guardian_blocked": True,
                    "risk": blocked.risk,
                }

        return await self._raw_call_tool(server_id, tool_name, arguments)

    async def _raw_call_tool(
        self,
        server_id: str,
        tool_name: str,
        arguments: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """实际执行 MCP 工具调用（内部方法，供 call_tool 和守护器调用）。"""
        response = await self._send_request(
            server_id,
            "tools/call",
            {
                "name": tool_name,
                "arguments": arguments or {},
            },
        )

        if response:
            if response.error:
                return {"success": False, "error": response.error, "isError": True}
            # 提取 MCP 标准 isError 字段（工具执行错误 vs 协议错误）
            is_error = False
            if isinstance(response.result, dict):
                is_error = response.result.get("isError", False)
            return {
                "success": not is_error,
                "result": response.result,
                "isError": is_error,
            }

        return {"success": False, "error": "请求失败", "isError": True}

    async def read_resource(
        self,
        server_id: str,
        uri: str,
    ) -> Dict[str, Any]:
        """读取 MCP 资源"""
        response = await self._send_request(
            server_id,
            "resources/read",
            {"uri": uri},
        )
        
        if response:
            if response.error:
                return {"success": False, "error": response.error}
            return {"success": True, "result": response.result}
        
        return {"success": False, "error": "请求失败"}
    
    async def get_prompt(
        self,
        server_id: str,
        name: str,
        arguments: Dict[str, str] = None,
    ) -> Dict[str, Any]:
        """获取 MCP 提示"""
        response = await self._send_request(
            server_id,
            "prompts/get",
            {
                "name": name,
                "arguments": arguments or {},
            },
        )
        
        if response:
            if response.error:
                return {"success": False, "error": response.error}
            return {"success": True, "result": response.result}
        
        return {"success": False, "error": "请求失败"}
    
    # ========================================================================
    # 查询
    # ========================================================================
    
    def list_servers(self) -> List[Dict]:
        """列出所有服务器"""
        return [server.to_dict() for server in self.servers.values()]
    
    async def list_tools(self, server_id: str) -> List[Dict]:
        """列出服务器的工具"""
        server = self.servers.get(server_id)
        if not server:
            return []
        
        return [
            {
                "name": t.name,
                "description": t.description,
                "inputSchema": t.inputSchema,
            }
            for t in server.tools
        ]
    
    async def list_resources(self, server_id: str) -> List[Dict]:
        """列出服务器的资源"""
        server = self.servers.get(server_id)
        if not server:
            return []
        
        return [
            {
                "uri": r.uri,
                "name": r.name,
                "description": r.description,
                "mimeType": r.mimeType,
            }
            for r in server.resources
        ]
    
    async def list_prompts(self, server_id: str) -> List[Dict]:
        """列出服务器的提示"""
        server = self.servers.get(server_id)
        if not server:
            return []
        
        return [
            {
                "name": p.name,
                "description": p.description,
                "arguments": p.arguments,
            }
            for p in server.prompts
        ]
    
    def get_server(self, server_id: str) -> Optional[Dict]:
        """获取服务器详情"""
        if server_id in self.servers:
            return self.servers[server_id].to_dict()
        return None

    # ========================================================================
    # 配置加载（兼容 Galaxy 格式 + Claude Desktop 格式）
    # ========================================================================

    async def load_from_config(self, config_path: str) -> Dict[str, Any]:
        """
        从配置文件加载 MCP 服务器。

        同时支持两种配置格式：
        1. Galaxy 格式::

            {
              "servers": [
                {"name": "fs", "command": "npx -y @modelcontextprotocol/server-filesystem", ...}
              ]
            }

        2. Claude Desktop 格式 (claude_desktop_config.json)::

            {
              "mcpServers": {
                "filesystem": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem"], ...}
              }
            }

        Args:
            config_path: 配置文件路径

        Returns:
            {"loaded": int, "errors": [...]}
        """
        config_file = Path(config_path)
        if not config_file.exists():
            return {"loaded": 0, "errors": [f"配置文件不存在: {config_path}"]}

        with open(config_file, "r", encoding="utf-8") as f:
            config = json.load(f)

        server_defs: List[Dict[str, Any]] = []

        # 检测格式：Claude Desktop 格式（mcpServers 是 dict）
        if "mcpServers" in config and isinstance(config["mcpServers"], dict):
            for name, spec in config["mcpServers"].items():
                cmd = spec.get("command", "")
                args = spec.get("args", [])
                server_defs.append({
                    "name": name,
                    "command": cmd,
                    "args": args,
                    "env": spec.get("env", {}),
                    "cwd": spec.get("cwd", ""),
                    "auto_start": spec.get("auto_start", False),
                })

        # Galaxy 格式（servers 是 list）
        elif "servers" in config and isinstance(config["servers"], list):
            for spec in config["servers"]:
                name = spec.get("name", "")
                cmd = spec.get("command", "")
                args = spec.get("args", [])
                server_defs.append({
                    "name": name,
                    "command": cmd,
                    "args": args,
                    "env": spec.get("env", {}),
                    "cwd": spec.get("cwd", ""),
                    "auto_start": spec.get("auto_start", False),
                })
        else:
            return {"loaded": 0, "errors": ["未知配置格式：需要 'mcpServers' 或 'servers' 键"]}

        loaded = 0
        errors = []
        for sd in server_defs:
            if not sd["name"] or not sd["command"]:
                continue
            try:
                result = await self.load(
                    name=sd["name"],
                    command=sd["command"],
                    args=sd["args"],
                    env=sd["env"],
                    cwd=sd["cwd"],
                    auto_start=sd["auto_start"],
                )
                if result.get("success"):
                    loaded += 1
                else:
                    errors.append(f"{sd['name']}: {result.get('error', '未知错误')}")
            except Exception as e:
                errors.append(f"{sd['name']}: {e}")

        return {"loaded": loaded, "errors": errors}

    # ========================================================================
    # MCP 标准通知
    # ========================================================================

    async def notify_tools_list_changed(self, server_id: str):
        """
        向 MCP 服务器发送 tools/list_changed 通知。

        当工具列表变更（如 Self-Tool-Making 注册新工具后）调用此方法，
        通知所有连接的客户端刷新工具列表。
        """
        await self._send_notification(
            server_id,
            "notifications/tools/list_changed",
        )
        # 同时刷新本地缓存
        await self._refresh_tools(server_id)
        logger.info(f"已发送 tools/list_changed 通知: {server_id}")


# ============================================================================
# 全局实例
# ============================================================================

mcp_loader = MCPLoader.get_instance()
