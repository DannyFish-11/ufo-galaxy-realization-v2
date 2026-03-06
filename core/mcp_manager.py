"""
UFO Galaxy - MCP 管理器
=======================

通用的 MCP (Model Context Protocol) 管理系统

功能：
1. 动态加载 GitHub 上的 MCP 服务器
2. 统一的工具注册和调用
3. 标准的 MCP 协议支持
4. 自动发现和注册工具

参考：
- https://github.com/modelcontextprotocol
- https://github.com/anthropics/anthropic-cookbook/tree/main/misc/mcp

使用方法：
    from core.mcp_manager import mcp_manager
    
    # 加载 MCP 服务器
    await mcp_manager.load_server("filesystem", "npx -y @modelcontextprotocol/server-filesystem /path")
    
    # 调用工具
    result = await mcp_manager.call_tool("filesystem", "read_file", {"path": "/path/to/file"})
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Callable
from pathlib import Path
from enum import Enum

logger = logging.getLogger("UFO-Galaxy.MCP")


# ============================================================================
# 数据模型
# ============================================================================

class MCPServerStatus(str, Enum):
    """MCP 服务器状态"""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"


@dataclass
class MCPTool:
    """MCP 工具定义"""
    name: str
    description: str
    input_schema: Dict[str, Any] = field(default_factory=dict)
    server_name: str = ""
    
    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "server_name": self.server_name,
        }


@dataclass
class MCPServer:
    """MCP 服务器"""
    name: str
    command: List[str]
    env: Dict[str, str] = field(default_factory=dict)
    status: MCPServerStatus = MCPServerStatus.STOPPED
    tools: List[MCPTool] = field(default_factory=list)
    process: Optional[subprocess.Popen] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=lambda: datetime.now().timestamp())


# ============================================================================
# MCP 管理器
# ============================================================================

class MCPManager:
    """
    MCP 管理器
    
    统一管理所有 MCP 服务器和工具
    """
    
    _instance = None
    
    def __init__(self):
        self.servers: Dict[str, MCPServer] = {}
        self.tools: Dict[str, MCPTool] = {}
        self._tool_handlers: Dict[str, Callable] = {}
        
        # 内置工具
        self._builtin_tools: Dict[str, MCPTool] = {}
        self._builtin_handlers: Dict[str, Callable] = {}
        
        # 配置
        self.config_path = Path("config/mcp_servers.json")
        
        logger.info("MCP 管理器初始化")
    
    @classmethod
    def get_instance(cls) -> "MCPManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    # ========================================================================
    # 服务器管理
    # ========================================================================
    
    async def load_server(
        self,
        name: str,
        command: str | List[str],
        env: Dict[str, str] = None,
        auto_start: bool = True,
    ) -> bool:
        """
        加载 MCP 服务器
        
        Args:
            name: 服务器名称
            command: 启动命令 (字符串或列表)
            env: 环境变量
            auto_start: 是否自动启动
        
        Returns:
            是否成功
        """
        if isinstance(command, str):
            command = command.split()
        
        server = MCPServer(
            name=name,
            command=command,
            env=env or {},
        )
        
        self.servers[name] = server
        
        if auto_start:
            return await self.start_server(name)
        
        return True
    
    async def start_server(self, name: str) -> bool:
        """启动 MCP 服务器"""
        server = self.servers.get(name)
        if not server:
            logger.error(f"服务器不存在: {name}")
            return False
        
        try:
            server.status = MCPServerStatus.STARTING
            
            # 准备环境变量
            env = os.environ.copy()
            env.update(server.env)
            
            # 启动进程
            server.process = subprocess.Popen(
                server.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
            
            # 等待启动
            await asyncio.sleep(1)
            
            if server.process.poll() is None:
                server.status = MCPServerStatus.RUNNING
                
                # 获取工具列表
                await self._discover_tools(name)
                
                logger.info(f"MCP 服务器已启动: {name}")
                return True
            else:
                server.status = MCPServerStatus.ERROR
                server.error = server.process.stderr.read().decode()
                logger.error(f"MCP 服务器启动失败: {name} - {server.error}")
                return False
                
        except Exception as e:
            server.status = MCPServerStatus.ERROR
            server.error = str(e)
            logger.error(f"启动 MCP 服务器失败: {name} - {e}")
            return False
    
    async def stop_server(self, name: str) -> bool:
        """停止 MCP 服务器"""
        server = self.servers.get(name)
        if not server:
            return False
        
        if server.process:
            server.process.terminate()
            server.process = None
        
        server.status = MCPServerStatus.STOPPED
        
        # 移除该服务器的工具
        tools_to_remove = [t for t, tool in self.tools.items() if tool.server_name == name]
        for t in tools_to_remove:
            del self.tools[t]
        
        logger.info(f"MCP 服务器已停止: {name}")
        return True
    
    async def _discover_tools(self, name: str):
        """发现服务器的工具"""
        server = self.servers.get(name)
        if not server:
            return
        
        # 发送 tools/list 请求
        try:
            response = await self._send_request(name, "tools/list", {})
            
            if response and "tools" in response:
                for tool_data in response["tools"]:
                    tool = MCPTool(
                        name=tool_data.get("name", ""),
                        description=tool_data.get("description", ""),
                        input_schema=tool_data.get("inputSchema", {}),
                        server_name=name,
                    )
                    server.tools.append(tool)
                    self.tools[tool.name] = tool
                    
                logger.info(f"发现 {len(server.tools)} 个工具: {name}")
        except Exception as e:
            logger.warning(f"发现工具失败: {name} - {e}")
    
    async def _send_request(
        self,
        server_name: str,
        method: str,
        params: Dict,
    ) -> Optional[Dict]:
        """发送请求到 MCP 服务器"""
        server = self.servers.get(server_name)
        if not server or not server.process:
            return None
        
        try:
            request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": method,
                "params": params,
            }
            
            server.process.stdin.write((json.dumps(request) + "\n").encode())
            server.process.stdin.flush()
            
            response = server.process.stdout.readline().decode()
            return json.loads(response)
            
        except Exception as e:
            logger.error(f"发送请求失败: {server_name} - {e}")
            return None
    
    # ========================================================================
    # 工具调用
    # ========================================================================
    
    async def call_tool(
        self,
        tool_name: str,
        params: Dict[str, Any],
    ) -> Any:
        """
        调用工具
        
        Args:
            tool_name: 工具名称
            params: 参数
        
        Returns:
            执行结果
        """
        # 检查内置工具
        if tool_name in self._builtin_handlers:
            return await self._builtin_handlers[tool_name](**params)
        
        # 检查注册的工具
        if tool_name in self._tool_handlers:
            return await self._tool_handlers[tool_name](**params)
        
        # 检查 MCP 工具
        tool = self.tools.get(tool_name)
        if not tool:
            raise ValueError(f"工具不存在: {tool_name}")
        
        server = self.servers.get(tool.server_name)
        if not server or server.status != MCPServerStatus.RUNNING:
            raise RuntimeError(f"服务器未运行: {tool.server_name}")
        
        # 发送 tools/call 请求
        response = await self._send_request(
            tool.server_name,
            "tools/call",
            {"name": tool_name, "arguments": params},
        )
        
        if response and "result" in response:
            return response["result"]
        
        raise RuntimeError(f"工具调用失败: {tool_name}")
    
    def register_tool(
        self,
        name: str,
        description: str,
        handler: Callable,
        input_schema: Dict = None,
    ):
        """
        注册自定义工具
        
        Args:
            name: 工具名称
            description: 描述
            handler: 处理函数
            input_schema: 输入模式
        """
        tool = MCPTool(
            name=name,
            description=description,
            input_schema=input_schema or {},
            server_name="builtin",
        )
        
        self._builtin_tools[name] = tool
        self._builtin_handlers[name] = handler
        self.tools[name] = tool
        
        logger.info(f"注册工具: {name}")
    
    def list_tools(self) -> List[Dict]:
        """列出所有工具"""
        return [tool.to_dict() for tool in self.tools.values()]
    
    def list_servers(self) -> List[Dict]:
        """列出所有服务器"""
        return [
            {
                "name": s.name,
                "status": s.status.value,
                "tools_count": len(s.tools),
                "error": s.error,
            }
            for s in self.servers.values()
        ]
    
    # ========================================================================
    # 预定义 MCP 服务器
    # ========================================================================
    
    async def load_builtin_servers(self):
        """加载内置的 MCP 服务器配置"""
        
        # 文件系统 MCP
        await self.load_server(
            "filesystem",
            "npx -y @modelcontextprotocol/server-filesystem",
            auto_start=False,
        )
        
        # GitHub MCP
        await self.load_server(
            "github",
            "npx -y @modelcontextprotocol/server-github",
            env={"GITHUB_TOKEN": os.environ.get("GITHUB_TOKEN", "")},
            auto_start=False,
        )
        
        # Brave Search MCP
        await self.load_server(
            "brave-search",
            "npx -y @modelcontextprotocol/server-brave-search",
            env={"BRAVE_API_KEY": os.environ.get("BRAVE_API_KEY", "")},
            auto_start=False,
        )
        
        # Puppeteer MCP
        await self.load_server(
            "puppeteer",
            "npx -y @modelcontextprotocol/server-puppeteer",
            auto_start=False,
        )
        
        logger.info("已加载内置 MCP 服务器配置")
    
    # ========================================================================
    # 从配置加载
    # ========================================================================
    
    async def load_from_config(self):
        """从配置文件加载；若文件不存在则创建默认模板"""
        if not self.config_path.exists():
            self._create_default_config()

        try:
            with open(self.config_path, encoding="utf-8") as f:
                config = json.load(f)

            loaded = 0
            for server_config in config.get("servers", []):
                try:
                    await self.load_server(
                        name=server_config["name"],
                        command=server_config["command"],
                        env=server_config.get("env", {}),
                        auto_start=server_config.get("auto_start", False),
                    )
                    loaded += 1
                except Exception as srv_err:
                    logger.warning(f"加载 MCP 服务器 '{server_config.get('name')}' 失败: {srv_err}")

            logger.info(f"从配置加载了 {loaded} 个 MCP 服务器")
        except Exception as e:
            logger.error(f"加载 MCP 配置失败: {e}")

    def _create_default_config(self):
        """若配置文件不存在则创建默认模板"""
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            default = {
                "version": "1.0.0",
                "description": "MCP 服务器配置 - 支持动态加载 MCP 工具",
                "servers": [],
                "custom_servers": [],
            }
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(default, f, indent=2, ensure_ascii=False)
            logger.info(f"已创建默认 MCP 配置模板: {self.config_path}")
        except Exception as e:
            logger.warning(f"创建 MCP 配置模板失败: {e}")


# ============================================================================
# 全局实例
# ============================================================================

mcp_manager = MCPManager.get_instance()


# ============================================================================
# 便捷函数
# ============================================================================

async def call_mcp_tool(tool_name: str, **params) -> Any:
    """调用 MCP 工具"""
    return await mcp_manager.call_tool(tool_name, params)


def register_mcp_tool(name: str, description: str, handler: Callable, schema: Dict = None):
    """注册 MCP 工具"""
    mcp_manager.register_tool(name, description, handler, schema)
