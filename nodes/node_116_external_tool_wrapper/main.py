"""
外部工具包装器节点 (Node 116)
功能：工具自动发现、动态命令生成、工具执行和结果解析、工具注册和管理
"""

import os
import sys
import json
import subprocess
import importlib
import inspect
from typing import Dict, List, Any, Optional, Callable, Union
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ToolType(Enum):
    """工具类型枚举"""
    PYTHON_FUNCTION = "python_function"
    SHELL_COMMAND = "shell_command"
    API_ENDPOINT = "api_endpoint"
    EXTERNAL_SCRIPT = "external_script"
    WEBHOOK = "webhook"


@dataclass
class ToolParameter:
    """工具参数定义"""
    name: str
    type: str
    description: str
    required: bool = True
    default: Any = None
    enum: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ToolDefinition:
    """工具定义"""
    name: str
    description: str
    tool_type: ToolType
    parameters: List[ToolParameter] = field(default_factory=list)
    return_type: str = "any"
    return_description: str = ""
    category: str = "general"
    tags: List[str] = field(default_factory=list)
    author: str = ""
    version: str = "1.0.0"
    timeout: int = 30
    enabled: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "tool_type": self.tool_type.value,
            "parameters": [p.to_dict() for p in self.parameters],
            "return_type": self.return_type,
            "return_description": self.return_description,
            "category": self.category,
            "tags": self.tags,
            "author": self.author,
            "version": self.version,
            "timeout": self.timeout,
            "enabled": self.enabled
        }


@dataclass
class ToolResult:
    """工具执行结果"""
    success: bool
    data: Any = None
    error: str = ""
    execution_time: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ToolRegistry:
    """工具注册表 - 管理所有可用工具"""

    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}
        self._handlers: Dict[str, Callable] = {}
        self._categories: Dict[str, List[str]] = {}

    def register(self, tool_def: ToolDefinition, handler: Callable) -> bool:
        """注册工具"""
        if tool_def.name in self._tools:
            logger.warning(f"Tool '{tool_def.name}' already registered, updating...")

        self._tools[tool_def.name] = tool_def
        self._handlers[tool_def.name] = handler

        # 按分类组织
        category = tool_def.category
        if category not in self._categories:
            self._categories[category] = []
        if tool_def.name not in self._categories[category]:
            self._categories[category].append(tool_def.name)

        logger.info(f"Tool '{tool_def.name}' registered successfully")
        return True

    def unregister(self, tool_name: str) -> bool:
        """注销工具"""
        if tool_name not in self._tools:
            logger.warning(f"Tool '{tool_name}' not found")
            return False

        tool_def = self._tools[tool_name]
        category = tool_def.category

        del self._tools[tool_name]
        del self._handlers[tool_name]

        if category in self._categories and tool_name in self._categories[category]:
            self._categories[category].remove(tool_name)

        logger.info(f"Tool '{tool_name}' unregistered")
        return True

    def get_tool(self, tool_name: str) -> Optional[ToolDefinition]:
        """获取工具定义"""
        return self._tools.get(tool_name)

    def get_handler(self, tool_name: str) -> Optional[Callable]:
        """获取工具处理器"""
        return self._handlers.get(tool_name)

    def list_tools(self, category: Optional[str] = None, 
                   enabled_only: bool = True) -> List[ToolDefinition]:
        """列出所有工具"""
        tools = []
        for name, tool_def in self._tools.items():
            if enabled_only and not tool_def.enabled:
                continue
            if category and tool_def.category != category:
                continue
            tools.append(tool_def)
        return tools

    def list_categories(self) -> List[str]:
        """列出所有分类"""
        return list(self._categories.keys())

    def search_tools(self, query: str) -> List[ToolDefinition]:
        """搜索工具"""
        results = []
        query = query.lower()
        for tool_def in self._tools.values():
            if (query in tool_def.name.lower() or 
                query in tool_def.description.lower() or
                any(query in tag.lower() for tag in tool_def.tags)):
                results.append(tool_def)
        return results

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "tools": {name: tool.to_dict() for name, tool in self._tools.items()},
            "categories": self._categories
        }


class ToolDiscovery:
    """工具自动发现器"""

    def __init__(self, registry: ToolRegistry):
        self.registry = registry
        self.discovery_paths: List[str] = []

    def add_discovery_path(self, path: str):
        """添加发现路径"""
        self.discovery_paths.append(path)

    def discover_from_module(self, module_path: str) -> List[ToolDefinition]:
        """从Python模块中发现工具"""
        discovered = []
        try:
            # 动态导入模块
            module = importlib.import_module(module_path)

            # 查找所有带有 @tool 装饰器的函数
            for name, obj in inspect.getmembers(module):
                if hasattr(obj, '_is_tool') and obj._is_tool:
                    tool_def = obj._tool_definition
                    discovered.append(tool_def)
                    self.registry.register(tool_def, obj)

        except Exception as e:
            logger.error(f"Failed to discover from module {module_path}: {e}")

        return discovered

    def discover_from_directory(self, directory: str) -> List[ToolDefinition]:
        """从目录中发现工具"""
        discovered = []
        dir_path = Path(directory)

        if not dir_path.exists():
            logger.warning(f"Directory not found: {directory}")
            return discovered

        # 扫描Python文件
        for py_file in dir_path.glob("**/*.py"):
            try:
                # 将文件路径转换为模块路径
                module_name = py_file.stem
                spec = importlib.util.spec_from_file_location(module_name, py_file)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)

                    for name, obj in inspect.getmembers(module):
                        if hasattr(obj, '_is_tool') and obj._is_tool:
                            tool_def = obj._tool_definition
                            discovered.append(tool_def)
                            self.registry.register(tool_def, obj)
            except Exception as e:
                logger.error(f"Failed to load {py_file}: {e}")

        # 扫描JSON配置文件
        for json_file in dir_path.glob("**/*.json"):
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    if 'tools' in config:
                        for tool_config in config['tools']:
                            tool_def = self._parse_tool_config(tool_config)
                            if tool_def:
                                discovered.append(tool_def)
                                handler = self._create_handler_from_config(tool_config)
                                self.registry.register(tool_def, handler)
            except Exception as e:
                logger.error(f"Failed to parse {json_file}: {e}")

        return discovered

    def _parse_tool_config(self, config: Dict[str, Any]) -> Optional[ToolDefinition]:
        """从配置解析工具定义"""
        try:
            params = []
            for p in config.get('parameters', []):
                params.append(ToolParameter(
                    name=p['name'],
                    type=p['type'],
                    description=p.get('description', ''),
                    required=p.get('required', True),
                    default=p.get('default'),
                    enum=p.get('enum', [])
                ))

            return ToolDefinition(
                name=config['name'],
                description=config.get('description', ''),
                tool_type=ToolType(config.get('tool_type', 'python_function')),
                parameters=params,
                return_type=config.get('return_type', 'any'),
                return_description=config.get('return_description', ''),
                category=config.get('category', 'general'),
                tags=config.get('tags', []),
                author=config.get('author', ''),
                version=config.get('version', '1.0.0'),
                timeout=config.get('timeout', 30),
                enabled=config.get('enabled', True)
            )
        except Exception as e:
            logger.error(f"Failed to parse tool config: {e}")
            return None

    def _create_handler_from_config(self, config: Dict[str, Any]) -> Callable:
        """从配置创建处理器"""
        tool_type = config.get('tool_type', 'python_function')

        if tool_type == 'shell_command':
            command_template = config.get('command', '')
            return lambda **kwargs: self._execute_shell_command(command_template, **kwargs)
        elif tool_type == 'api_endpoint':
            endpoint = config.get('endpoint', '')
            method = config.get('method', 'GET')
            return lambda **kwargs: self._execute_api_call(endpoint, method, **kwargs)
        else:
            return lambda **kwargs: {"error": "Handler not implemented"}

    def _execute_shell_command(self, template: str, **kwargs) -> Dict[str, Any]:
        """执行shell命令"""
        try:
            command = template.format(**kwargs)
            result = subprocess.run(
                command, 
                shell=True, 
                capture_output=True, 
                text=True,
                timeout=30
            )
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _execute_api_call(self, endpoint: str, method: str, **kwargs) -> Dict[str, Any]:
        """执行API调用"""
        try:
            import requests
            if method.upper() == 'GET':
                response = requests.get(endpoint, params=kwargs, timeout=30)
            else:
                response = requests.request(method, endpoint, json=kwargs, timeout=30)
            return {
                "success": response.status_code < 400,
                "status_code": response.status_code,
                "data": response.json() if response.headers.get('content-type', '').startswith('application/json') else response.text
            }
        except Exception as e:
            return {"success": False, "error": str(e)}


class CommandGenerator:
    """动态命令生成器"""

    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    def generate_command(self, tool_name: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """生成命令"""
        tool_def = self.registry.get_tool(tool_name)
        if not tool_def:
            return {"error": f"Tool '{tool_name}' not found"}

        # 验证参数
        validation = self._validate_parameters(tool_def, parameters)
        if not validation['valid']:
            return {"error": validation['error']}

        # 根据工具类型生成命令
        if tool_def.tool_type == ToolType.SHELL_COMMAND:
            return self._generate_shell_command(tool_def, parameters)
        elif tool_def.tool_type == ToolType.API_ENDPOINT:
            return self._generate_api_call(tool_def, parameters)
        else:
            return {
                "tool_name": tool_name,
                "parameters": parameters,
                "tool_type": tool_def.tool_type.value
            }

    def _validate_parameters(self, tool_def: ToolDefinition, 
                             parameters: Dict[str, Any]) -> Dict[str, Any]:
        """验证参数"""
        errors = []

        for param in tool_def.parameters:
            if param.required and param.name not in parameters:
                errors.append(f"Missing required parameter: {param.name}")

            if param.name in parameters:
                value = parameters[param.name]
                # 类型检查
                if param.type == "string" and not isinstance(value, str):
                    errors.append(f"Parameter {param.name} should be string")
                elif param.type == "number" and not isinstance(value, (int, float)):
                    errors.append(f"Parameter {param.name} should be number")
                elif param.type == "boolean" and not isinstance(value, bool):
                    errors.append(f"Parameter {param.name} should be boolean")

                # 枚举检查
                if param.enum and value not in param.enum:
                    errors.append(f"Parameter {param.name} should be one of {param.enum}")

        if errors:
            return {"valid": False, "error": "; ".join(errors)}
        return {"valid": True}

    def _generate_shell_command(self, tool_def: ToolDefinition, 
                                 parameters: Dict[str, Any]) -> Dict[str, Any]:
        """生成shell命令"""
        # 构建命令字符串
        args = []
        for param in tool_def.parameters:
            if param.name in parameters:
                value = parameters[param.name]
                if param.type == "boolean":
                    if value:
                        args.append(f"--{param.name}")
                else:
                    args.append(f"--{param.name} {value}")

        return {
            "command": f"{tool_def.name} {' '.join(args)}",
            "args": args,
            "parameters": parameters
        }

    def _generate_api_call(self, tool_def: ToolDefinition, 
                           parameters: Dict[str, Any]) -> Dict[str, Any]:
        """生成API调用"""
        return {
            "endpoint": f"/api/tools/{tool_def.name}",
            "method": "POST",
            "body": parameters
        }


class ToolExecutor:
    """工具执行器"""

    def __init__(self, registry: ToolRegistry):
        self.registry = registry
        self.executor = ThreadPoolExecutor(max_workers=10)
        self.execution_history: List[Dict[str, Any]] = []

    async def execute(self, tool_name: str, parameters: Dict[str, Any]) -> ToolResult:
        """异步执行工具"""
        import time
        start_time = time.time()

        tool_def = self.registry.get_tool(tool_name)
        if not tool_def:
            return ToolResult(
                success=False,
                error=f"Tool '{tool_name}' not found"
            )

        if not tool_def.enabled:
            return ToolResult(
                success=False,
                error=f"Tool '{tool_name}' is disabled"
            )

        handler = self.registry.get_handler(tool_name)
        if not handler:
            return ToolResult(
                success=False,
                error=f"Handler for '{tool_name}' not found"
            )

        try:
            # 在线程池中执行
            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(self.executor, lambda: handler(**parameters)),
                timeout=tool_def.timeout
            )

            execution_time = time.time() - start_time

            # 解析结果
            parsed_result = self._parse_result(result)

            tool_result = ToolResult(
                success=True,
                data=parsed_result,
                execution_time=execution_time,
                metadata={"tool_name": tool_name, "parameters": parameters}
            )

        except asyncio.TimeoutError:
            tool_result = ToolResult(
                success=False,
                error=f"Execution timeout after {tool_def.timeout}s"
            )
        except Exception as e:
            tool_result = ToolResult(
                success=False,
                error=str(e)
            )

        # 记录执行历史
        self.execution_history.append({
            "tool_name": tool_name,
            "parameters": parameters,
            "result": tool_result.to_dict(),
            "timestamp": time.time()
        })

        return tool_result

    def _parse_result(self, result: Any) -> Any:
        """解析执行结果"""
        if isinstance(result, dict):
            return result
        elif isinstance(result, list):
            return result
        elif hasattr(result, 'to_dict'):
            return result.to_dict()
        elif hasattr(result, '__dict__'):
            return result.__dict__
        else:
            return {"value": str(result)}

    def get_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """获取执行历史"""
        return self.execution_history[-limit:]

    def clear_history(self):
        """清除执行历史"""
        self.execution_history.clear()


# 工具装饰器
def tool(name: str, description: str, 
         parameters: List[Dict[str, Any]] = None,
         return_type: str = "any",
         category: str = "general",
         tags: List[str] = None,
         **kwargs):
    """工具装饰器 - 用于标记函数为可发现工具"""

    def decorator(func: Callable) -> Callable:
        # 创建工具定义
        params = []
        if parameters:
            for p in parameters:
                params.append(ToolParameter(
                    name=p['name'],
                    type=p['type'],
                    description=p.get('description', ''),
                    required=p.get('required', True),
                    default=p.get('default'),
                    enum=p.get('enum', [])
                ))

        tool_def = ToolDefinition(
            name=name,
            description=description,
            tool_type=ToolType.PYTHON_FUNCTION,
            parameters=params,
            return_type=return_type,
            category=category,
            tags=tags or [],
            **kwargs
        )

        # 标记函数
        func._is_tool = True
        func._tool_definition = tool_def

        return func

    return decorator


class ExternalToolWrapper:
    """外部工具包装器主类"""

    def __init__(self):
        self.registry = ToolRegistry()
        self.discovery = ToolDiscovery(self.registry)
        self.command_generator = CommandGenerator(self.registry)
        self.executor = ToolExecutor(self.registry)

    def initialize(self, config: Optional[Dict[str, Any]] = None):
        """初始化包装器"""
        if config:
            # 从配置加载发现路径
            for path in config.get('discovery_paths', []):
                self.discovery.add_discovery_path(path)

        # 注册内置工具
        self._register_builtin_tools()

        logger.info("ExternalToolWrapper initialized")

    def _register_builtin_tools(self):
        """注册内置工具"""

        @tool(
            name="list_tools",
            description="列出所有可用工具",
            parameters=[
                {"name": "category", "type": "string", "description": "工具分类过滤", "required": False},
                {"name": "enabled_only", "type": "boolean", "description": "仅显示启用的工具", "required": False}
            ],
            return_type="list",
            category="system"
        )
        def list_tools(category: str = None, enabled_only: bool = True) -> List[Dict[str, Any]]:
            tools = self.registry.list_tools(category=category, enabled_only=enabled_only)
            return [t.to_dict() for t in tools]

        @tool(
            name="search_tools",
            description="搜索工具",
            parameters=[
                {"name": "query", "type": "string", "description": "搜索关键词", "required": True}
            ],
            return_type="list",
            category="system"
        )
        def search_tools(query: str) -> List[Dict[str, Any]]:
            tools = self.registry.search_tools(query)
            return [t.to_dict() for t in tools]

        @tool(
            name="get_tool_info",
            description="获取工具详细信息",
            parameters=[
                {"name": "tool_name", "type": "string", "description": "工具名称", "required": True}
            ],
            return_type="dict",
            category="system"
        )
        def get_tool_info(tool_name: str) -> Optional[Dict[str, Any]]:
            tool_def = self.registry.get_tool(tool_name)
            return tool_def.to_dict() if tool_def else None

        @tool(
            name="execute_tool",
            description="执行指定工具",
            parameters=[
                {"name": "tool_name", "type": "string", "description": "工具名称", "required": True},
                {"name": "parameters", "type": "object", "description": "工具参数", "required": False}
            ],
            return_type="dict",
            category="system"
        )
        async def execute_tool(tool_name: str, parameters: Dict[str, Any] = None) -> Dict[str, Any]:
            result = await self.executor.execute(tool_name, parameters or {})
            return result.to_dict()

        @tool(
            name="discover_tools",
            description="发现并注册新工具",
            parameters=[
                {"name": "path", "type": "string", "description": "发现路径", "required": True}
            ],
            return_type="list",
            category="system"
        )
        def discover_tools(path: str) -> List[Dict[str, Any]]:
            discovered = self.discovery.discover_from_directory(path)
            return [t.to_dict() for t in discovered]

        # 注册内置工具
        self.registry.register(list_tools._tool_definition, list_tools)
        self.registry.register(search_tools._tool_definition, search_tools)
        self.registry.register(get_tool_info._tool_definition, get_tool_info)
        self.registry.register(execute_tool._tool_definition, execute_tool)
        self.registry.register(discover_tools._tool_definition, discover_tools)

    async def process(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """处理输入请求"""
        action = input_data.get('action')

        if action == 'list_tools':
            tools = self.registry.list_tools(
                category=input_data.get('category'),
                enabled_only=input_data.get('enabled_only', True)
            )
            return {"success": True, "tools": [t.to_dict() for t in tools]}

        elif action == 'search_tools':
            tools = self.registry.search_tools(input_data.get('query', ''))
            return {"success": True, "tools": [t.to_dict() for t in tools]}

        elif action == 'get_tool_info':
            tool_def = self.registry.get_tool(input_data.get('tool_name'))
            if tool_def:
                return {"success": True, "tool": tool_def.to_dict()}
            return {"success": False, "error": "Tool not found"}

        elif action == 'execute_tool':
            result = await self.executor.execute(
                input_data.get('tool_name'),
                input_data.get('parameters', {})
            )
            return {"success": result.success, "result": result.to_dict()}

        elif action == 'generate_command':
            command = self.command_generator.generate_command(
                input_data.get('tool_name'),
                input_data.get('parameters', {})
            )
            return {"success": True, "command": command}

        elif action == 'discover_tools':
            discovered = self.discovery.discover_from_directory(
                input_data.get('path', './tools')
            )
            return {"success": True, "discovered": [t.to_dict() for t in discovered]}

        elif action == 'register_tool':
            # 从配置注册工具
            config = input_data.get('config', {})
            tool_def = self.discovery._parse_tool_config(config)
            if tool_def:
                handler = self.discovery._create_handler_from_config(config)
                success = self.registry.register(tool_def, handler)
                return {"success": success, "tool": tool_def.to_dict()}
            return {"success": False, "error": "Invalid tool config"}

        elif action == 'unregister_tool':
            success = self.registry.unregister(input_data.get('tool_name'))
            return {"success": success}

        elif action == 'get_categories':
            categories = self.registry.list_categories()
            return {"success": True, "categories": categories}

        elif action == 'get_execution_history':
            history = self.executor.get_history(input_data.get('limit', 100))
            return {"success": True, "history": history}

        else:
            return {"success": False, "error": f"Unknown action: {action}"}

    def get_status(self) -> Dict[str, Any]:
        """获取状态信息"""
        return {
            "registered_tools": len(self.registry._tools),
            "categories": len(self.registry._categories),
            "execution_history_count": len(self.executor.execution_history)
        }


# 节点处理函数
async def node_process(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """节点主处理函数"""
    wrapper = ExternalToolWrapper()
    wrapper.initialize(input_data.get('config'))
    return await wrapper.process(input_data)


# 同步包装函数
def process(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """同步处理入口"""
    return asyncio.run(node_process(input_data))


if __name__ == "__main__":
    # 测试代码
    test_input = {
        "action": "list_tools",
        "config": {}
    }
    result = process(test_input)
    print(json.dumps(result, indent=2, ensure_ascii=False))
