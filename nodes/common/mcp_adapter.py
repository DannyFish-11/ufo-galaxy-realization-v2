"""
MCP Adapter Base Class
======================
存量工具的通用适配器基类。
将现有 MCP 服务器封装为 UFO Galaxy 节点。

功能：
- 统一的 MCP 工具调用接口
- 健康检查
- 日志记录
- 错误处理
"""

import os
import json
import subprocess
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any, List
from abc import ABC, abstractmethod

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware


class MCPAdapter(ABC):
    """MCP 适配器基类"""
    
    def __init__(self, node_id: str, name: str, port: int):
        self.node_id = node_id
        self.name = name
        self.port = port
        self.app = FastAPI(title=f"Node {node_id} - {name}", version="1.0.0")
        self._setup_middleware()
        self._setup_routes()
        
    def _setup_middleware(self):
        """设置中间件"""
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        
    def _setup_routes(self):
        """设置路由"""
        @self.app.get("/health")
        async def health():
            return {
                "status": "healthy",
                "node_id": self.node_id,
                "name": self.name,
                "timestamp": datetime.now().isoformat()
            }
            
        @self.app.get("/tools")
        async def list_tools():
            return {"tools": self.get_tools()}
            
        @self.app.post("/mcp/call")
        async def mcp_call(request: Dict[str, Any]):
            tool = request.get("tool", "")
            params = request.get("params", {})
            
            try:
                result = await self.call_tool(tool, params)
                return {"success": True, "result": result}
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
                
    @abstractmethod
    def get_tools(self) -> List[Dict[str, Any]]:
        """获取可用工具列表"""
        pass
        
    @abstractmethod
    async def call_tool(self, tool: str, params: Dict[str, Any]) -> Any:
        """调用工具"""
        pass
        
    def run(self):
        """运行服务"""
        import uvicorn
        uvicorn.run(self.app, host="0.0.0.0", port=self.port)


class ExternalMCPAdapter(MCPAdapter):
    """外部 MCP 服务器适配器"""
    
    def __init__(
        self, 
        node_id: str, 
        name: str, 
        port: int,
        mcp_command: List[str],
        mcp_env: Dict[str, str] = None
    ):
        super().__init__(node_id, name, port)
        self.mcp_command = mcp_command
        self.mcp_env = mcp_env or {}
        self._tools_cache = None
        
    def get_tools(self) -> List[Dict[str, Any]]:
        """获取工具列表"""
        if self._tools_cache:
            return self._tools_cache
            
        # 通过 manus-mcp-cli 获取工具列表
        try:
            result = subprocess.run(
                ["manus-mcp-cli", "tool", "list", "--server", self.name.lower()],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0:
                self._tools_cache = json.loads(result.stdout)
                return self._tools_cache
        except:
            pass
            
        return []
        
    async def call_tool(self, tool: str, params: Dict[str, Any]) -> Any:
        """调用外部 MCP 工具"""
        # 通过 manus-mcp-cli 调用
        cmd = [
            "manus-mcp-cli", "tool", "call", tool,
            "--server", self.name.lower(),
            "--input", json.dumps(params)
        ]
        
        env = os.environ.copy()
        env.update(self.mcp_env)
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env
        )
        
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=60
        )
        
        if process.returncode != 0:
            raise Exception(f"MCP call failed: {stderr.decode()}")
            
        return json.loads(stdout.decode())


class PythonMCPAdapter(MCPAdapter):
    """Python 实现的 MCP 适配器"""
    
    def __init__(self, node_id: str, name: str, port: int):
        super().__init__(node_id, name, port)
        self._tools = {}
        
    def register_tool(
        self, 
        name: str, 
        description: str,
        handler,
        parameters: Dict[str, Any] = None
    ):
        """注册工具"""
        self._tools[name] = {
            "name": name,
            "description": description,
            "handler": handler,
            "parameters": parameters or {}
        }
        
    def get_tools(self) -> List[Dict[str, Any]]:
        """获取工具列表"""
        return [
            {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"]
            }
            for t in self._tools.values()
        ]
        
    async def call_tool(self, tool: str, params: Dict[str, Any]) -> Any:
        """调用工具"""
        if tool not in self._tools:
            raise ValueError(f"Unknown tool: {tool}")
            
        handler = self._tools[tool]["handler"]
        
        if asyncio.iscoroutinefunction(handler):
            return await handler(**params)
        else:
            return handler(**params)
