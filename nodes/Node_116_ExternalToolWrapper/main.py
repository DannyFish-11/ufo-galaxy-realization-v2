"""
Node 116 - ExternalToolWrapper (外部工具包装节点)
提供外部工具和服务的统一封装和调用能力
"""
import os
import json
import asyncio
import logging
import subprocess
import shutil
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field, asdict
from enum import Enum
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uuid

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Node 116 - ExternalToolWrapper", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


class ToolType(str, Enum):
    """工具类型"""
    CLI = "cli"                 # 命令行工具
    API = "api"                 # API 服务
    LIBRARY = "library"         # 程序库
    SCRIPT = "script"           # 脚本
    BINARY = "binary"           # 二进制程序
    CONTAINER = "container"     # 容器


class ToolStatus(str, Enum):
    """工具状态"""
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    INSTALLING = "installing"
    ERROR = "error"


@dataclass
class ExternalTool:
    """外部工具定义"""
    tool_id: str
    name: str
    tool_type: ToolType
    description: str
    command: Optional[str] = None
    path: Optional[str] = None
    version: Optional[str] = None
    status: ToolStatus = ToolStatus.UNAVAILABLE
    capabilities: List[str] = field(default_factory=list)
    parameters: Dict[str, Any] = field(default_factory=dict)
    environment: Dict[str, str] = field(default_factory=dict)
    install_command: Optional[str] = None
    check_command: Optional[str] = None
    last_used: Optional[datetime] = None
    usage_count: int = 0


@dataclass
class ToolExecution:
    """工具执行记录"""
    execution_id: str
    tool_id: str
    command: str
    arguments: List[str]
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    exit_code: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    success: bool = False


class ExternalToolWrapper:
    """外部工具包装器"""
    
    def __init__(self):
        self.tools: Dict[str, ExternalTool] = {}
        self.executions: List[ToolExecution] = []
        self._custom_handlers: Dict[str, Callable] = {}
        self._initialize_common_tools()
    
    def _initialize_common_tools(self):
        """初始化常用工具"""
        common_tools = [
            ExternalTool(
                tool_id="python",
                name="Python",
                tool_type=ToolType.CLI,
                description="Python 解释器",
                command="python3",
                check_command="python3 --version",
                capabilities=["execute_script", "repl", "package_management"]
            ),
            ExternalTool(
                tool_id="git",
                name="Git",
                tool_type=ToolType.CLI,
                description="版本控制系统",
                command="git",
                check_command="git --version",
                capabilities=["clone", "commit", "push", "pull", "branch"]
            ),
            ExternalTool(
                tool_id="curl",
                name="cURL",
                tool_type=ToolType.CLI,
                description="HTTP 客户端",
                command="curl",
                check_command="curl --version",
                capabilities=["http_request", "download", "upload"]
            ),
            ExternalTool(
                tool_id="docker",
                name="Docker",
                tool_type=ToolType.CLI,
                description="容器运行时",
                command="docker",
                check_command="docker --version",
                capabilities=["container_run", "image_build", "container_manage"]
            ),
            ExternalTool(
                tool_id="ffmpeg",
                name="FFmpeg",
                tool_type=ToolType.CLI,
                description="多媒体处理工具",
                command="ffmpeg",
                check_command="ffmpeg -version",
                capabilities=["video_convert", "audio_convert", "stream"]
            ),
            ExternalTool(
                tool_id="node",
                name="Node.js",
                tool_type=ToolType.CLI,
                description="JavaScript 运行时",
                command="node",
                check_command="node --version",
                capabilities=["execute_script", "npm", "package_management"]
            ),
        ]
        
        for tool in common_tools:
            self.tools[tool.tool_id] = tool
        
        # 检查工具可用性
        asyncio.create_task(self._check_all_tools())
    
    async def _check_all_tools(self):
        """检查所有工具的可用性"""
        for tool_id in self.tools:
            await self.check_tool(tool_id)
    
    def register_tool(self, tool: ExternalTool) -> bool:
        """注册工具"""
        self.tools[tool.tool_id] = tool
        logger.info(f"Registered tool: {tool.tool_id} ({tool.name})")
        return True
    
    def unregister_tool(self, tool_id: str) -> bool:
        """注销工具"""
        if tool_id in self.tools:
            del self.tools[tool_id]
            return True
        return False
    
    async def check_tool(self, tool_id: str) -> ToolStatus:
        """检查工具可用性"""
        if tool_id not in self.tools:
            return ToolStatus.UNAVAILABLE
        
        tool = self.tools[tool_id]
        
        # 检查命令是否存在
        if tool.command:
            if not shutil.which(tool.command):
                tool.status = ToolStatus.UNAVAILABLE
                return tool.status
        
        # 运行检查命令
        if tool.check_command:
            try:
                result = await self._run_command(tool.check_command, timeout=10)
                if result.exit_code == 0:
                    tool.status = ToolStatus.AVAILABLE
                    # 尝试提取版本
                    if result.stdout:
                        lines = result.stdout.strip().split('\n')
                        if lines:
                            tool.version = lines[0]
                else:
                    tool.status = ToolStatus.ERROR
            except Exception as e:
                logger.error(f"Tool check failed for {tool_id}: {e}")
                tool.status = ToolStatus.ERROR
        else:
            tool.status = ToolStatus.AVAILABLE
        
        return tool.status
    
    async def install_tool(self, tool_id: str) -> bool:
        """安装工具"""
        if tool_id not in self.tools:
            return False
        
        tool = self.tools[tool_id]
        
        if not tool.install_command:
            logger.warning(f"No install command for tool {tool_id}")
            return False
        
        tool.status = ToolStatus.INSTALLING
        
        try:
            result = await self._run_command(tool.install_command, timeout=300)
            if result.exit_code == 0:
                tool.status = ToolStatus.AVAILABLE
                return True
            else:
                tool.status = ToolStatus.ERROR
                return False
        except Exception as e:
            logger.error(f"Tool installation failed for {tool_id}: {e}")
            tool.status = ToolStatus.ERROR
            return False
    
    async def execute(self, tool_id: str, arguments: List[str] = None,
                      input_data: str = None, timeout: int = 60,
                      working_dir: str = None) -> ToolExecution:
        """执行工具"""
        if tool_id not in self.tools:
            raise ValueError(f"Tool not found: {tool_id}")
        
        tool = self.tools[tool_id]
        
        if tool.status != ToolStatus.AVAILABLE:
            raise RuntimeError(f"Tool not available: {tool_id} (status: {tool.status})")
        
        # 构建命令
        cmd_parts = [tool.command]
        if arguments:
            cmd_parts.extend(arguments)
        
        command = ' '.join(cmd_parts)
        
        # 创建执行记录
        execution = ToolExecution(
            execution_id=str(uuid.uuid4()),
            tool_id=tool_id,
            command=command,
            arguments=arguments or []
        )
        
        try:
            # 准备环境变量
            env = os.environ.copy()
            env.update(tool.environment)
            
            # 执行命令
            result = await self._run_command(
                command,
                timeout=timeout,
                input_data=input_data,
                working_dir=working_dir,
                env=env
            )
            
            execution.exit_code = result.exit_code
            execution.stdout = result.stdout
            execution.stderr = result.stderr
            execution.success = result.exit_code == 0
            
        except asyncio.TimeoutError:
            execution.stderr = "Execution timed out"
            execution.exit_code = -1
        except Exception as e:
            execution.stderr = str(e)
            execution.exit_code = -1
        
        execution.completed_at = datetime.now()
        
        # 更新工具使用统计
        tool.last_used = datetime.now()
        tool.usage_count += 1
        
        # 保存执行记录
        self.executions.append(execution)
        if len(self.executions) > 1000:
            self.executions = self.executions[-500:]
        
        return execution
    
    async def _run_command(self, command: str, timeout: int = 60,
                           input_data: str = None, working_dir: str = None,
                           env: Dict = None) -> ToolExecution:
        """运行命令"""
        process = await asyncio.create_subprocess_shell(
            command,
            stdin=asyncio.subprocess.PIPE if input_data else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=working_dir,
            env=env
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(input_data.encode() if input_data else None),
                timeout=timeout
            )
            
            return ToolExecution(
                execution_id="",
                tool_id="",
                command=command,
                arguments=[],
                exit_code=process.returncode,
                stdout=stdout.decode('utf-8', errors='replace'),
                stderr=stderr.decode('utf-8', errors='replace'),
                success=process.returncode == 0
            )
        except asyncio.TimeoutError:
            process.kill()
            raise
    
    def register_custom_handler(self, tool_id: str, handler: Callable):
        """注册自定义处理器"""
        self._custom_handlers[tool_id] = handler
    
    async def execute_custom(self, tool_id: str, **kwargs) -> Any:
        """执行自定义工具"""
        if tool_id not in self._custom_handlers:
            raise ValueError(f"No custom handler for tool: {tool_id}")
        
        handler = self._custom_handlers[tool_id]
        return await handler(**kwargs)
    
    def get_tool(self, tool_id: str) -> Optional[ExternalTool]:
        """获取工具信息"""
        return self.tools.get(tool_id)
    
    def list_tools(self, tool_type: Optional[ToolType] = None,
                   status: Optional[ToolStatus] = None) -> List[ExternalTool]:
        """列出工具"""
        tools = list(self.tools.values())
        
        if tool_type:
            tools = [t for t in tools if t.tool_type == tool_type]
        if status:
            tools = [t for t in tools if t.status == status]
        
        return tools
    
    def get_available_tools(self) -> List[str]:
        """获取可用工具列表"""
        return [t.tool_id for t in self.tools.values() if t.status == ToolStatus.AVAILABLE]
    
    def get_status(self) -> Dict[str, Any]:
        """获取包装器状态"""
        return {
            "total_tools": len(self.tools),
            "available_tools": sum(1 for t in self.tools.values() if t.status == ToolStatus.AVAILABLE),
            "unavailable_tools": sum(1 for t in self.tools.values() if t.status == ToolStatus.UNAVAILABLE),
            "total_executions": len(self.executions),
            "successful_executions": sum(1 for e in self.executions if e.success)
        }


# 全局实例
tool_wrapper = ExternalToolWrapper()


# API 模型
class RegisterToolRequest(BaseModel):
    tool_id: str
    name: str
    tool_type: str
    description: str
    command: Optional[str] = None
    check_command: Optional[str] = None
    install_command: Optional[str] = None
    capabilities: List[str] = []
    environment: Dict[str, str] = {}

class ExecuteToolRequest(BaseModel):
    tool_id: str
    arguments: List[str] = []
    input_data: Optional[str] = None
    timeout: int = 60
    working_dir: Optional[str] = None


# API 端点
@app.get("/health")
async def health_check():
    return {"status": "healthy", "node": "Node_116_ExternalToolWrapper"}

@app.get("/status")
async def get_status():
    return tool_wrapper.get_status()

@app.post("/tools")
async def register_tool(request: RegisterToolRequest):
    tool = ExternalTool(
        tool_id=request.tool_id,
        name=request.name,
        tool_type=ToolType(request.tool_type),
        description=request.description,
        command=request.command,
        check_command=request.check_command,
        install_command=request.install_command,
        capabilities=request.capabilities,
        environment=request.environment
    )
    tool_wrapper.register_tool(tool)
    await tool_wrapper.check_tool(tool.tool_id)
    return {"success": True, "status": tool.status.value}

@app.get("/tools")
async def list_tools(tool_type: Optional[str] = None, status: Optional[str] = None):
    tt = ToolType(tool_type) if tool_type else None
    ts = ToolStatus(status) if status else None
    tools = tool_wrapper.list_tools(tt, ts)
    return [asdict(t) for t in tools]

@app.get("/tools/available")
async def get_available_tools():
    return tool_wrapper.get_available_tools()

@app.get("/tools/{tool_id}")
async def get_tool(tool_id: str):
    tool = tool_wrapper.get_tool(tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")
    return asdict(tool)

@app.post("/tools/{tool_id}/check")
async def check_tool(tool_id: str):
    status = await tool_wrapper.check_tool(tool_id)
    return {"status": status.value}

@app.post("/tools/{tool_id}/install")
async def install_tool(tool_id: str):
    success = await tool_wrapper.install_tool(tool_id)
    return {"success": success}

@app.post("/execute")
async def execute_tool(request: ExecuteToolRequest):
    try:
        execution = await tool_wrapper.execute(
            request.tool_id,
            request.arguments,
            request.input_data,
            request.timeout,
            request.working_dir
        )
        return asdict(execution)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/executions")
async def list_executions(tool_id: Optional[str] = None, limit: int = 50):
    executions = tool_wrapper.executions
    if tool_id:
        executions = [e for e in executions if e.tool_id == tool_id]
    executions = sorted(executions, key=lambda e: e.started_at, reverse=True)[:limit]
    return [asdict(e) for e in executions]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8116)
