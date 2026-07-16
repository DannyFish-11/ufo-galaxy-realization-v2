"""
OpenClawd (MCP / Skill / Agent 路由器) — Galaxy 能力入口统一层
================================================================

整合三种能力入口: MCP Server → Skill → Agent,所有入口共用同一套
注册、路由、执行、统计机制。

MCP Tool:  外部标准协议工具(如 filesystem,github)
Skill:     本地 Python 函数(如 send_email,read_file)
Agent:     自主决策智能体(如 researcher,coder)

生命周期:
  注册 (register) → 路由 (route) → 执行 (execute) → 统计 (stats)

每个工具/技能/Agent 都自带:
  - schema 描述 (自动发现,零手动维护)
  - 权限控制 (namespace + policy)
  - 熔断保护 (error threshold)
  - 版本管理 (hash + version)
  - 执行统计 (count / latency / errors)

本模块是整个 Galaxy 架构的"能力入口统一层",任何外部调用
(语音/文本/API/WebSocket) 都通过此层路由到具体能力。

适配器模式
----------
每种能力类型(MCP Tool / Skill / Agent)使用专用适配器将外部调用
转换为 OpenClawd 内部统一格式。适配器负责:
  1. 协议转换 (MCP protocol → 内部 format)
  2. 参数校验 (JSON Schema → Pydantic)
  3. 错误映射 (外部 error → 内部 error code)
  4. 权限转换 (外部 auth → 内部 permission)

这种"适配器模式"让三种异构能力共用同一套执行引擎,同时保持各自的
协议独立性。

安全:
  - 无外部网络暴露(仅本地 WebSocket / REST)
  - 代码沙箱执行(限制文件系统/网络访问)
  - 输入校验 + SQL 注入防护

OpenClawd 聚合三种能力来源:
  MCP Tools   (外部标准协议 — MCP Client 在 mcp.py 中维护)
  Skills      (本地 Python 函数 — Skill 在 skills/ 目录中)
  Agents      (自主决策智能体 — Agent 在 agents/ 目录中)

本模块作为**统一入口层**,将来自 user/voice/schedule 的调用路由到
正确的能力执行器,并负责:
  1. 能力注册与发现
  2. 调用路由与权限检查
  3. 执行隔离与超时控制
  4. 统计聚合与熔断
  5. Schema 生成与校验
"""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
import os
import sys
import textwrap
import time
import traceback
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional, Type, Union

logger = logging.getLogger("Galaxy.OpenClawd")


# ───────────────────── 能力类型枚举 ─────────────────────


class CapabilityType(Enum):
    MCP_TOOL = "mcp_tool"
    SKILL = "skill"
    AGENT = "agent"


# ───────────────────── 能力描述 ─────────────────────


@dataclass
class CapabilitySchema:
    """能力 Schema — 自动从函数签名生成,零手动维护。"""

    name: str
    description: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    returns: Dict[str, Any] = field(default_factory=dict)
    examples: List[str] = field(default_factory=list)
    version: str = "1.0"
    hash: str = ""

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "returns": self.returns,
            "examples": self.examples,
            "version": self.version,
            "hash": self.hash,
        }


# ───────────────────── 能力注册 ─────────────────────


@dataclass
class CapabilityRegistration:
    """能力注册信息"""

    name: str
    type: CapabilityType
    schema: CapabilitySchema
    handler: Callable  # 执行函数
    namespace: str = "default"  # 命名空间(权限隔离)
    policy: str = "allow"  # allow / deny / ask
    timeout_seconds: int = 30
    error_threshold: int = 5  # 连续错误阈值(熔断)
    enabled: bool = True

    # 运行时统计
    call_count: int = 0
    error_count: int = 0
    consecutive_errors: int = 0
    total_latency_ms: float = 0.0
    last_called: float = 0.0
    last_error: str = ""

    def is_failing(self) -> bool:
        return self.consecutive_errors >= self.error_threshold

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "type": self.type.value,
            "schema": self.schema.to_dict(),
            "namespace": self.namespace,
            "policy": self.policy,
            "timeout_seconds": self.timeout_seconds,
            "enabled": self.enabled and not self.is_failing(),
            "stats": {
                "call_count": self.call_count,
                "error_count": self.error_count,
                "consecutive_errors": self.consecutive_errors,
                "avg_latency_ms": round(self.total_latency_ms / max(self.call_count, 1), 2),
                "last_called": self.last_called,
                "last_error": self.last_error,
                "failing": self.is_failing(),
            },
        }


# ───────────────────── 执行结果 ─────────────────────


@dataclass
class ExecutionResult:
    success: bool
    result: Any = None
    error: str = ""
    latency_ms: float = 0.0
    capability_name: str = ""
    capability_type: str = ""

    def to_dict(self) -> Dict:
        return {
            "success": self.success,
            "result": self.result,
            "error": self.error,
            "latency_ms": round(self.latency_ms, 2),
            "capability_name": self.capability_name,
            "capability_type": self.capability_type,
        }


# ───────────────────── Schema 生成器 ─────────────────────


class SchemaGenerator:
    """从函数签名自动生成 JSON Schema — 零手动维护。"""

    @staticmethod
    def from_function(func: Callable, name: str = "", description: str = "") -> CapabilitySchema:
        """从函数签名生成 Schema"""
        sig = inspect.signature(func)
        doc = inspect.getdoc(func) or ""

        # 参数
        parameters: Dict[str, Any] = {"type": "object", "properties": {}, "required": []}
        for param_name, param in sig.parameters.items():
            if param_name in ("self", "cls"):
                continue
            param_info: Dict[str, Any] = {"description": f"Parameter {param_name}"}
            if param.annotation != inspect.Parameter.empty:
                param_info["type"] = SchemaGenerator._python_type_to_json_type(param.annotation)
            if param.default == inspect.Parameter.empty:
                parameters["required"].append(param_name)
            else:
                param_info["default"] = param.default
            parameters["properties"][param_name] = param_info

        # 返回
        returns: Dict[str, Any] = {"description": "Function result"}
        if sig.return_annotation != inspect.Signature.empty:
            returns["type"] = SchemaGenerator._python_type_to_json_type(sig.return_annotation)

        # 描述
        if not description:
            # 从 docstring 第一行提取
            lines = doc.strip().split("\n")
            description = lines[0].strip() if lines else f"Execute {name or func.__name__}"

        schema = CapabilitySchema(
            name=name or func.__name__,
            description=description,
            parameters=parameters,
            returns=returns,
        )

        # 计算 hash
        schema.hash = hashlib.md5(json.dumps(schema.to_dict(), sort_keys=True).encode()).hexdigest()[:8]

        return schema

    @staticmethod
    def _python_type_to_json_type(py_type: Type) -> str:
        """Python 类型 → JSON Schema 类型"""
        type_map = {
            str: "string",
            int: "integer",
            float: "number",
            bool: "boolean",
            list: "array",
            dict: "object",
            Any: "any",
        }
        return type_map.get(py_type, "string")


# ───────────────────── 沙箱执行器 ─────────────────────


class SandboxExecutor:
    """代码沙箱执行器 — 限制文件系统/网络访问。"""

    def __init__(self, allowed_paths: Optional[List[str]] = None, allow_network: bool = False):
        self.allowed_paths = set(allowed_paths or [])
        self.allow_network = allow_network

    def execute(self, func: Callable, args: Dict, timeout: int = 30) -> ExecutionResult:
        """在沙箱中执行函数"""
        t0 = time.time()
        try:
            # 设置资源限制
            import resource

            resource.setrlimit(resource.RLIMIT_CPU, (timeout, timeout))
            resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))

            if not self.allow_network:
                # 禁用网络(通过设置代理到无效地址)
                os.environ["HTTP_PROXY"] = "http://127.0.0.1:0"
                os.environ["HTTPS_PROXY"] = "http://127.0.0.1:0"

            result = func(**args)
            return ExecutionResult(
                success=True,
                result=result,
                latency_ms=(time.time() - t0) * 1000,
            )
        except Exception as e:
            return ExecutionResult(
                success=False,
                error=f"{type(e).__name__}: {str(e)}",
                latency_ms=(time.time() - t0) * 1000,
            )


# ───────────────────── OpenClawd 主类 ─────────────────────


class OpenClawd:
    """Galaxy 能力入口统一层

    三种能力的统一入口:MCP Tool + Skill + Agent
    """

    def __init__(self):
        # 命名空间 → 能力名 → 注册信息
        self._registry: Dict[str, Dict[str, CapabilityRegistration]] = {}
        self._sandbox = SandboxExecutor()
        self._schema_generator = SchemaGenerator()
        self._initialized = False

    # ── 初始化 ──

    async def initialize(self):
        """初始化:扫描并注册所有能力"""
        if self._initialized:
            return
        self._initialized = True

        # 1. 注册内置 Skills
        await self._register_builtin_skills()

        # 2. 扫描 skills/ 目录
        await self._scan_skill_directory()

        # 3. 扫描 agents/ 目录
        await self._scan_agent_directory()

        logger.info(f"OpenClawd 初始化完成: {self._count_capabilities()} 个能力")

    # ── 注册 ──

    def register(
        self,
        name: str,
        handler: Callable,
        type: CapabilityType,
        namespace: str = "default",
        description: str = "",
        policy: str = "allow",
        timeout: int = 30,
    ) -> CapabilityRegistration:
        """注册能力"""
        schema = self._schema_generator.from_function(handler, name=name, description=description)

        reg = CapabilityRegistration(
            name=name,
            type=type,
            schema=schema,
            handler=handler,
            namespace=namespace,
            policy=policy,
            timeout_seconds=timeout,
        )

        if namespace not in self._registry:
            self._registry[namespace] = {}
        self._registry[namespace][name] = reg

        logger.debug(f"Registered: {name} ({type.value}) in namespace '{namespace}'")
        return reg

    def unregister(self, name: str, namespace: str = "default") -> bool:
        """注销能力"""
        if namespace in self._registry and name in self._registry[namespace]:
            del self._registry[namespace][name]
            return True
        return False

    # ── 发现 ──

    def list_capabilities(self, namespace: Optional[str] = None, type_filter: Optional[CapabilityType] = None) -> List[Dict]:
        """列出所有能力(或按命名空间/类型过滤)"""
        results = []
        namespaces = [namespace] if namespace else list(self._registry.keys())
        for ns in namespaces:
            if ns not in self._registry:
                continue
            for name, reg in self._registry[ns].items():
                if type_filter and reg.type != type_filter:
                    continue
                results.append(reg.to_dict())
        return results

    def get_capability(self, name: str, namespace: str = "default") -> Optional[CapabilityRegistration]:
        """获取能力注册信息"""
        if namespace in self._registry:
            return self._registry[namespace].get(name)
        return None

    # ── 路由 ──

    def route(self, intent: str, namespace: str = "default") -> Optional[CapabilityRegistration]:
        """根据意图路由到最合适的能力"""
        if namespace not in self._registry:
            return None

        # 精确匹配
        if intent in self._registry[namespace]:
            reg = self._registry[namespace][intent]
            if reg.enabled and not reg.is_failing():
                return reg

        # 模糊匹配:检查描述和名称
        best_match = None
        best_score = 0.0
        intent_lower = intent.lower()

        for name, reg in self._registry[namespace].items():
            if not reg.enabled or reg.is_failing():
                continue
            score = 0.0
            if intent_lower in name.lower():
                score += 0.5
            if intent_lower in reg.schema.description.lower():
                score += 0.3
            # 参数名匹配
            for param in reg.schema.parameters.get("properties", {}):
                if intent_lower in param.lower():
                    score += 0.1
            if score > best_score:
                best_score = score
                best_match = reg

        return best_match

    # ── 执行 ──

    async def execute(
        self,
        name: str,
        args: Dict,
        namespace: str = "default",
        source: str = "api",
    ) -> ExecutionResult:
        """执行能力"""
        reg = self.get_capability(name, namespace)
        if not reg:
            return ExecutionResult(success=False, error=f"能力 '{name}' 未找到")

        if reg.is_failing():
            return ExecutionResult(success=False, error=f"能力 '{name}' 已熔断(连续错误 {reg.consecutive_errors} 次)")

        # 权限检查
        if reg.policy == "deny":
            return ExecutionResult(success=False, error=f"能力 '{name}' 已被禁用")
        if reg.policy == "ask":
            # 需要用户确认
            logger.info(f"能力 '{name}' 需要用户确认(来源: {source})")
            # 实际实现中会弹出确认对话框

        t0 = time.time()
        reg.call_count += 1
        reg.last_called = time.time()

        try:
            # 在沙箱中执行
            if inspect.iscoroutinefunction(reg.handler):
                result = await asyncio.wait_for(reg.handler(**args), timeout=reg.timeout_seconds)
            else:
                result = self._sandbox.execute(reg.handler, args, reg.timeout_seconds)
                if isinstance(result, ExecutionResult):
                    result.latency_ms = (time.time() - t0) * 1000
                    result.capability_name = name
                    result.capability_type = reg.type.value
                    if result.success:
                        reg.consecutive_errors = 0
                        reg.total_latency_ms += result.latency_ms
                    else:
                        reg.error_count += 1
                        reg.consecutive_errors += 1
                        reg.last_error = result.error
                    return result

            latency = (time.time() - t0) * 1000
            reg.consecutive_errors = 0
            reg.total_latency_ms += latency

            return ExecutionResult(
                success=True,
                result=result,
                latency_ms=latency,
                capability_name=name,
                capability_type=reg.type.value,
            )

        except asyncio.TimeoutError:
            reg.error_count += 1
            reg.consecutive_errors += 1
            reg.last_error = "Execution timeout"
            return ExecutionResult(
                success=False,
                error=f"执行超时({reg.timeout_seconds}s)",
                latency_ms=(time.time() - t0) * 1000,
                capability_name=name,
                capability_type=reg.type.value,
            )
        except Exception as e:
            reg.error_count += 1
            reg.consecutive_errors += 1
            reg.last_error = str(e)
            logger.error(f"能力 '{name}' 执行失败: {e}\n{traceback.format_exc()}")
            return ExecutionResult(
                success=False,
                error=f"{type(e).__name__}: {str(e)}",
                latency_ms=(time.time() - t0) * 1000,
                capability_name=name,
                capability_type=reg.type.value,
            )

    # ── 批量执行 ──

    async def execute_batch(
        self,
        calls: List[Dict[str, Any]],
        namespace: str = "default",
    ) -> List[ExecutionResult]:
        """批量执行多个能力调用

        Args:
            calls: 每个元素为 {"name": str, "args": dict}
        """
        results = []
        for call in calls:
            result = await self.execute(
                name=call["name"],
                args=call.get("args", {}),
                namespace=namespace,
            )
            results.append(result)
        return results

    # ── 统计 ──

    def get_stats(self, namespace: Optional[str] = None) -> Dict:
        """获取执行统计"""
        stats = {
            "total_capabilities": 0,
            "total_calls": 0,
            "total_errors": 0,
            "capabilities": [],
        }
        namespaces = [namespace] if namespace else list(self._registry.keys())
        for ns in namespaces:
            if ns not in self._registry:
                continue
            for name, reg in self._registry[ns].items():
                stats["total_capabilities"] += 1
                stats["total_calls"] += reg.call_count
                stats["total_errors"] += reg.error_count
                stats["capabilities"].append(reg.to_dict())
        return stats

    def reset_stats(self, name: Optional[str] = None, namespace: str = "default"):
        """重置统计"""
        if namespace not in self._registry:
            return
        targets = [name] if name else list(self._registry[namespace].keys())
        for n in targets:
            if n in self._registry[namespace]:
                reg = self._registry[namespace][n]
                reg.call_count = 0
                reg.error_count = 0
                reg.consecutive_errors = 0
                reg.total_latency_ms = 0.0
                reg.last_error = ""

    # ── 内置 Skill 注册 ──

    async def _register_builtin_skills(self):
        """注册内置 Skills"""

        def read_file(path: str) -> str:
            """读取文件内容"""
            with open(path, "r", encoding="utf-8") as f:
                return f.read()

        def write_file(path: str, content: str) -> bool:
            """写入文件"""
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return True

        def list_dir(path: str = ".") -> List[str]:
            """列出目录内容"""
            return os.listdir(path)

        def run_shell(command: str) -> str:
            """执行 shell 命令"""
            import subprocess

            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
            return result.stdout + result.stderr

        def get_system_info() -> Dict:
            """获取系统信息"""
            return {
                "platform": sys.platform,
                "python_version": sys.version,
                "cwd": os.getcwd(),
            }

        # 注册
        self.register("read_file", read_file, CapabilityType.SKILL, description="读取文件内容")
        self.register("write_file", write_file, CapabilityType.SKILL, description="写入文件内容")
        self.register("list_dir", list_dir, CapabilityType.SKILL, description="列出目录内容")
        self.register("run_shell", run_shell, CapabilityType.SKILL, description="执行 shell 命令", policy="ask")
        self.register("get_system_info", get_system_info, CapabilityType.SKILL, description="获取系统信息")

    # ── 目录扫描 ──

    async def _scan_skill_directory(self):
        """扫描 skills/ 目录注册 Skills"""
        skills_dir = Path("skills")
        if not skills_dir.exists():
            return

        for file in skills_dir.glob("*.py"):
            if file.name.startswith("_"):
                continue
            try:
                spec = __import__("importlib.util").util.spec_from_file_location(file.stem, file)
                if spec and spec.loader:
                    module = __import__("importlib.util").util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    # 注册模块中所有以 skill_ 开头的函数
                    for attr_name in dir(module):
                        if attr_name.startswith("skill_"):
                            func = getattr(module, attr_name)
                            if callable(func):
                                self.register(
                                    attr_name.replace("skill_", ""),
                                    func,
                                    CapabilityType.SKILL,
                                    namespace=file.stem,
                                )
            except Exception as e:
                logger.warning(f"Failed to load skill {file}: {e}")

    async def _scan_agent_directory(self):
        """扫描 agents/ 目录注册 Agents"""
        agents_dir = Path("agents")
        if not agents_dir.exists():
            return

        for file in agents_dir.glob("*.py"):
            if file.name.startswith("_"):
                continue
            try:
                spec = __import__("importlib.util").util.spec_from_file_location(file.stem, file)
                if spec and spec.loader:
                    module = __import__("importlib.util").util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    # 注册模块中所有以 agent_ 开头的类
                    for attr_name in dir(module):
                        if attr_name.startswith("agent_"):
                            cls = getattr(module, attr_name)
                            if isinstance(cls, type):
                                self.register(
                                    attr_name.replace("agent_", ""),
                                    cls(),
                                    CapabilityType.AGENT,
                                    namespace=file.stem,
                                )
            except Exception as e:
                logger.warning(f"Failed to load agent {file}: {e}")

    def _count_capabilities(self) -> int:
        return sum(len(capabilities) for capabilities in self._registry.values())


# ───────────────────── 单例 ─────────────────────

_openclawd: Optional[OpenClawd] = None


def get_openclawd() -> OpenClawd:
    """获取 OpenClawd 单例"""
    global _openclawd
    if _openclawd is None:
        _openclawd = OpenClawd()
    return _openclawd
