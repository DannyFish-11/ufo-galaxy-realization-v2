"""
Galaxy MCP 层 (Model Context Protocol Layer)
=============================================
动态加载和管理 MCP 服务器，提供标准化的工具调用接口

功能：
1. MCP 服务器发现和加载
2. 工具注册和调用
3. 资源管理
4. 提示词模板管理
"""

import os
import sys
import json
import asyncio
import logging
import subprocess
import importlib
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from abc import ABC, abstractmethod

logger = logging.getLogger("Galaxy.MCPLayer")

# ============================================================================
# MCP 数据模型
# ============================================================================

class MCPServerStatus(Enum):
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
    server_id: str = ""
    category: str = "general"
    
    def to_dict(self):
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "server_id": self.server_id,
            "category": self.category
        }

@dataclass
class MCPServer:
    """MCP 服务器定义"""
    id: str
    name: str
    description: str
    command: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    status: MCPServerStatus = MCPServerStatus.STOPPED
    tools: List[MCPTool] = field(default_factory=list)
    process: Optional[subprocess.Popen] = None
    last_error: str = ""
    
    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "status": self.status.value,
            "tools_count": len(self.tools),
            "last_error": self.last_error
        }

# ============================================================================
# 内置 MCP 服务器配置
# ============================================================================

BUILTIN_MCP_SERVERS = {
    # 文件系统
    "filesystem": {
        "id": "filesystem",
        "name": "File System",
        "description": "文件系统操作",
        "category": "core",
        "tools": [
            {"name": "read_file", "description": "读取文件内容"},
            {"name": "write_file", "description": "写入文件内容"},
            {"name": "list_directory", "description": "列出目录内容"},
            {"name": "create_directory", "description": "创建目录"},
            {"name": "delete_file", "description": "删除文件"},
        ]
    },
    
    # Shell 命令
    "shell": {
        "id": "shell",
        "name": "Shell Commands",
        "description": "执行 Shell 命令",
        "category": "core",
        "tools": [
            {"name": "execute", "description": "执行 Shell 命令"},
            {"name": "run_script", "description": "运行脚本"},
        ]
    },
    
    # 网络请求
    "fetch": {
        "id": "fetch",
        "name": "Web Fetch",
        "description": "网络请求",
        "category": "network",
        "tools": [
            {"name": "fetch", "description": "获取网页内容"},
            {"name": "download", "description": "下载文件"},
        ]
    },
    
    # 串口通信
    "serial": {
        "id": "serial",
        "name": "Serial Port",
        "description": "串口通信",
        "category": "hardware",
        "tools": [
            {"name": "list_ports", "description": "列出可用串口"},
            {"name": "connect", "description": "连接串口"},
            {"name": "send", "description": "发送数据"},
            {"name": "receive", "description": "接收数据"},
        ]
    },
    
    # GPIO 控制
    "gpio": {
        "id": "gpio",
        "name": "GPIO Control",
        "description": "GPIO 引脚控制",
        "category": "hardware",
        "tools": [
            {"name": "setup", "description": "设置引脚模式"},
            {"name": "read", "description": "读取引脚状态"},
            {"name": "write", "description": "写入引脚状态"},
        ]
    },
    
    # USB 设备
    "usb": {
        "id": "usb",
        "name": "USB Devices",
        "description": "USB 设备管理",
        "category": "hardware",
        "tools": [
            {"name": "list_devices", "description": "列出 USB 设备"},
            {"name": "read", "description": "读取 USB 数据"},
            {"name": "write", "description": "写入 USB 数据"},
        ]
    },
    
    # 数字生命卡
    "digital_life": {
        "id": "digital_life",
        "name": "Digital Life Card",
        "description": "数字生命卡存储",
        "category": "hardware",
        "tools": [
            {"name": "read_memory", "description": "读取记忆数据"},
            {"name": "write_memory", "description": "写入记忆数据"},
            {"name": "get_status", "description": "获取存储状态"},
            {"name": "backup", "description": "备份数据"},
            {"name": "restore", "description": "恢复数据"},
        ]
    },
    
    # 机械狗
    "robot_dog": {
        "id": "robot_dog",
        "name": "Robot Dog (Benben)",
        "description": "苯苯机械狗控制",
        "category": "hardware",
        "tools": [
            {"name": "move", "description": "移动控制"},
            {"name": "turn", "description": "转向控制"},
            {"name": "stop", "description": "停止"},
            {"name": "get_status", "description": "获取状态"},
            {"name": "set_posture", "description": "设置姿态"},
            {"name": "speak", "description": "语音输出"},
            {"name": "get_camera", "description": "获取摄像头画面"},
        ]
    },
    
    # 机械臂
    "robot_arm": {
        "id": "robot_arm",
        "name": "Robot Arm",
        "description": "机械臂控制",
        "category": "hardware",
        "tools": [
            {"name": "move_to", "description": "移动到指定位置"},
            {"name": "grab", "description": "抓取"},
            {"name": "release", "description": "释放"},
            {"name": "get_position", "description": "获取当前位置"},
            {"name": "home", "description": "回到原点"},
        ]
    },
}

# ============================================================================
# MCP 层管理器
# ============================================================================

class MCPLayer:
    """MCP 层管理器"""
    
    _instance = None
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, config_dir: Optional[Path] = None):
        if self._initialized:
            return
        
        self.config_dir = config_dir or Path(__file__).parent.parent / "config"
        self.mcp_dir = self.config_dir / "mcp"
        self.mcp_dir.mkdir(parents=True, exist_ok=True)
        
        self.servers: Dict[str, MCPServer] = {}
        self.tools: Dict[str, MCPTool] = {}
        
        self._load_builtin_servers()
        self._load_user_servers()
        
        self._initialized = True
        logger.info(f"MCP 层初始化完成，已加载 {len(self.servers)} 个服务器")
    
    def _load_builtin_servers(self):
        """加载内置服务器"""
        for server_id, config in BUILTIN_MCP_SERVERS.items():
            server = MCPServer(
                id=config["id"],
                name=config["name"],
                description=config["description"],
            )
            
            for tool_config in config.get("tools", []):
                tool = MCPTool(
                    name=tool_config["name"],
                    description=tool_config["description"],
                    server_id=server.id,
                    category=config.get("category", "general")
                )
                server.tools.append(tool)
                self.tools[tool.name] = tool
            
            self.servers[server.id] = server
    
    def _load_user_servers(self):
        """加载用户服务器"""
        config_file = self.mcp_dir / "servers.json"
        if config_file.exists():
            try:
                data = json.loads(config_file.read_text())
                for server_config in data.get("servers", []):
                    self.register_server(server_config)
            except Exception as e:
                logger.error(f"加载用户服务器失败: {e}")
    
    def register_server(self, config: Dict[str, Any]) -> bool:
        """注册新服务器"""
        try:
            server = MCPServer(
                id=config["id"],
                name=config["name"],
                description=config.get("description", ""),
                command=config.get("command", []),
                env=config.get("env", {})
            )
            
            for tool_config in config.get("tools", []):
                tool = MCPTool(
                    name=tool_config["name"],
                    description=tool_config.get("description", ""),
                    input_schema=tool_config.get("input_schema", {}),
                    server_id=server.id,
                    category=config.get("category", "general")
                )
                server.tools.append(tool)
                self.tools[tool.name] = tool
            
            self.servers[server.id] = server
            self._save_user_servers()
            logger.info(f"注册 MCP 服务器: {server.name}")
            return True
        except Exception as e:
            logger.error(f"注册服务器失败: {e}")
            return False
    
    def unregister_server(self, server_id: str) -> bool:
        """注销服务器"""
        if server_id not in self.servers:
            return False
        
        server = self.servers[server_id]
        
        for tool in server.tools:
            self.tools.pop(tool.name, None)
        
        del self.servers[server_id]
        self._save_user_servers()
        logger.info(f"注销 MCP 服务器: {server.name}")
        return True
    
    def _save_user_servers(self):
        """保存用户服务器配置"""
        config_file = self.mcp_dir / "servers.json"
        
        user_servers = []
        for server in self.servers.values():
            if server.id not in BUILTIN_MCP_SERVERS:
                user_servers.append({
                    "id": server.id,
                    "name": server.name,
                    "description": server.description,
                    "command": server.command,
                    "env": server.env,
                    "tools": [{"name": t.name, "description": t.description} for t in server.tools]
                })
        
        config_file.write_text(json.dumps({"servers": user_servers}, indent=2, ensure_ascii=False))
    
    async def call_tool(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """调用工具"""
        if tool_name not in self.tools:
            return {"success": False, "error": f"Tool not found: {tool_name}"}
        
        tool = self.tools[tool_name]
        
        # 模拟调用 - 实际需要通过 MCP 协议
        return {
            "success": True,
            "result": f"Tool {tool.name} executed",
            "params": params,
            "server": tool.server_id
        }
    
    def get_tools(self, category: str = None) -> List[MCPTool]:
        """获取工具列表"""
        tools = list(self.tools.values())
        if category:
            tools = [t for t in tools if t.category == category]
        return tools
    
    def get_servers(self) -> List[MCPServer]:
        """获取服务器列表"""
        return list(self.servers.values())
    
    def get_status(self) -> Dict:
        """获取状态"""
        return {
            "servers_count": len(self.servers),
            "tools_count": len(self.tools),
            "servers": [s.to_dict() for s in self.servers.values()]
        }

# ============================================================================
# 全局实例
# ============================================================================

_mcp_layer: Optional[MCPLayer] = None

def get_mcp_layer() -> MCPLayer:
    """获取 MCP 层实例"""
    global _mcp_layer
    if _mcp_layer is None:
        _mcp_layer = MCPLayer()
    return _mcp_layer
