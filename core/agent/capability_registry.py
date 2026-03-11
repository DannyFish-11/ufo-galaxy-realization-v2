"""
Galaxy - Capability Registry
==============================

MCP / Skill / Gateway 统一能力注册表。

所有执行链路的工具调用必须经过此注册表，确保：
  1. 能力可发现性 — 执行计划层可查询当前可用能力
  2. 能力隔离     — 禁止执行链路绕过注册表硬编码调用
  3. 健康度感知   — 工具调用前检查可用状态

注册的能力类型:
  mcp      — MCP 协议工具（来自 core.mcp_loader）
  skill    — 内置/外部技能（来自 core.skill_loader）
  gateway  — Galaxy Gateway 设备操控（来自 galaxy_gateway）
  node     — 内置执行节点（文件/代码/Shell/ADB 等）

使用方式:
    from core.agent.capability_registry import get_capability_registry

    registry = get_capability_registry()
    await registry.sync()                     # 同步已加载的 MCP/Skill

    tools = registry.list_tools()            # 列出所有可用工具
    tool  = registry.get_tool("web_search")  # 获取单个工具描述
    result = await registry.invoke(           # 调用工具
        "web_search", query="Galaxy AI"
    )
"""

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional

logger = logging.getLogger("Galaxy.Agent.CapabilityRegistry")


# ============================================================================
# 能力类型与数据模型
# ============================================================================

class CapabilityType(str, Enum):
    MCP = "mcp"
    SKILL = "skill"
    GATEWAY = "gateway"
    NODE = "node"


@dataclass
class CapabilityDescriptor:
    """单个能力的描述信息"""
    name: str                          # 唯一标识符（在注册表内唯一）
    capability_type: CapabilityType
    description: str
    parameters: Dict[str, Any] = field(default_factory=dict)  # JSON Schema 参数描述
    available: bool = True
    source_id: str = ""                # 来源 (MCP server name / skill id / node id)
    invoke_fn: Optional[Any] = None    # 可调用对象，类型 Callable[..., Awaitable[Any]]
    registered_at: float = field(default_factory=time.time)
    last_used_at: Optional[float] = None
    error_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": self.capability_type.value,
            "description": self.description,
            "parameters": self.parameters,
            "available": self.available,
            "source_id": self.source_id,
            "registered_at": self.registered_at,
            "last_used_at": self.last_used_at,
            "error_count": self.error_count,
        }


# ============================================================================
# CapabilityRegistry
# ============================================================================

class CapabilityRegistry:
    """
    MCP / Skill / Gateway / Node 统一能力注册表。

    所有注册的工具通过 invoke() 统一调用，支持同步注册和异步同步。
    """

    def __init__(self):
        self._capabilities: Dict[str, CapabilityDescriptor] = {}
        self._synced_at: Optional[float] = None
        self._register_builtin_nodes()
        logger.info("CapabilityRegistry 初始化，内置节点已注册")

    # ------------------------------------------------------------------
    # 注册
    # ------------------------------------------------------------------

    def register(self, descriptor: CapabilityDescriptor) -> None:
        """注册单个能力"""
        if descriptor.name in self._capabilities:
            logger.debug("CapabilityRegistry: 覆盖已存在的能力 %s", descriptor.name)
        self._capabilities[descriptor.name] = descriptor
        logger.debug("CapabilityRegistry: 注册能力 %s [%s]", descriptor.name, descriptor.capability_type.value)

    def unregister(self, name: str) -> bool:
        """注销能力，返回是否成功"""
        if name in self._capabilities:
            del self._capabilities[name]
            return True
        return False

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def list_tools(
        self,
        capability_type: Optional[CapabilityType] = None,
        available_only: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        列出所有（或指定类型）工具描述。

        Args:
            capability_type: 过滤类型，None 表示返回全部
            available_only:  是否只返回可用工具

        Returns:
            工具描述 dict 列表
        """
        result = []
        for cap in self._capabilities.values():
            if available_only and not cap.available:
                continue
            if capability_type and cap.capability_type != capability_type:
                continue
            result.append(cap.to_dict())
        return result

    def get_tool(self, name: str) -> Optional[CapabilityDescriptor]:
        """按名称获取工具描述"""
        return self._capabilities.get(name)

    def has_tool(self, name: str) -> bool:
        """检查工具是否已注册且可用"""
        cap = self._capabilities.get(name)
        return cap is not None and cap.available

    def list_names(self, available_only: bool = True) -> List[str]:
        """返回工具名称列表（用于计划层工具选择）"""
        return [
            name for name, cap in self._capabilities.items()
            if not available_only or cap.available
        ]

    def stats(self) -> Dict[str, Any]:
        """返回注册表统计信息"""
        by_type: Dict[str, int] = {}
        for cap in self._capabilities.values():
            key = cap.capability_type.value
            by_type[key] = by_type.get(key, 0) + 1
        return {
            "total": len(self._capabilities),
            "by_type": by_type,
            "synced_at": self._synced_at,
        }

    # ------------------------------------------------------------------
    # 调用
    # ------------------------------------------------------------------

    async def invoke(self, name: str, **kwargs: Any) -> Dict[str, Any]:
        """
        调用指定能力工具。

        Args:
            name:   工具名称
            **kwargs: 工具参数

        Returns:
            {"success": bool, "result": Any, "error": str}
        """
        cap = self._capabilities.get(name)
        if cap is None:
            return {"success": False, "result": None, "error": f"工具 '{name}' 未注册"}
        if not cap.available:
            return {"success": False, "result": None, "error": f"工具 '{name}' 当前不可用"}
        if cap.invoke_fn is None:
            return {"success": False, "result": None, "error": f"工具 '{name}' 没有可调用的实现"}

        cap.last_used_at = time.time()
        try:
            import asyncio
            import inspect
            fn = cap.invoke_fn
            if inspect.iscoroutinefunction(fn):
                result = await fn(**kwargs)
            else:
                result = fn(**kwargs)
            return {"success": True, "result": result, "error": ""}
        except Exception as e:
            cap.error_count += 1
            logger.warning("CapabilityRegistry: 工具 %s 调用失败: %s", name, e)
            return {"success": False, "result": None, "error": str(e)}

    # ------------------------------------------------------------------
    # 同步来自 MCP / Skill 加载器
    # ------------------------------------------------------------------

    async def sync(self) -> Dict[str, int]:
        """
        从 MCP 加载器和 Skill 加载器同步已注册的工具。

        Returns:
            {"mcp": 新增数, "skill": 新增数, "gateway": 新增数}
        """
        counts = {"mcp": 0, "skill": 0, "gateway": 0}

        # 同步 MCP 工具
        try:
            from core.mcp_loader import mcp_loader
            for server_name in mcp_loader.list_servers():
                tools = await mcp_loader.list_tools(server_name)
                for tool in tools:
                    tool_name = f"mcp_{server_name}_{tool.get('name', 'unknown')}"

                    async def _make_mcp_fn(sname: str, tname: str):
                        async def _fn(**kw: Any) -> Any:
                            return await mcp_loader.call_tool(sname, tname, kw)
                        return _fn

                    self.register(CapabilityDescriptor(
                        name=tool_name,
                        capability_type=CapabilityType.MCP,
                        description=tool.get("description", ""),
                        parameters=tool.get("inputSchema", {}),
                        source_id=server_name,
                        invoke_fn=await _make_mcp_fn(server_name, tool.get("name", "")),
                    ))
                    counts["mcp"] += 1
        except Exception as e:
            logger.debug("MCP 同步跳过: %s", e)

        # 同步 Skill 工具
        try:
            from core.skill_loader import skill_loader
            for skill in skill_loader.list_skills():
                skill_id = skill.get("id", "")
                skill_name = f"skill_{skill_id}"

                def _make_skill_fn(sid: str):
                    async def _fn(**kw: Any) -> Any:
                        return await skill_loader.execute(sid, **kw)
                    return _fn

                self.register(CapabilityDescriptor(
                    name=skill_name,
                    capability_type=CapabilityType.SKILL,
                    description=skill.get("description", ""),
                    source_id=skill_id,
                    invoke_fn=_make_skill_fn(skill_id),
                ))
                counts["skill"] += 1
        except Exception as e:
            logger.debug("Skill 同步跳过: %s", e)

        # 尝试同步 Gateway 工具
        try:
            from galaxy_gateway.device_router import get_device_router
            gw = get_device_router()
            devices = await gw.list_devices() if hasattr(gw, "list_devices") else []
            for device in devices:
                dev_id = device.get("device_id", "")
                cap_name = f"gateway_device_{dev_id}"

                def _make_gw_fn(did: str):
                    async def _fn(action: str = "", params: dict = None, **kw: Any) -> Any:
                        from galaxy_gateway.device_router import get_device_router as _get_dr
                        dr = _get_dr()
                        return await dr.execute(did, action, params or {})
                    return _fn

                self.register(CapabilityDescriptor(
                    name=cap_name,
                    capability_type=CapabilityType.GATEWAY,
                    description=f"Gateway device control: {dev_id}",
                    source_id=dev_id,
                    invoke_fn=_make_gw_fn(dev_id),
                ))
                counts["gateway"] += 1
        except Exception as e:
            logger.debug("Gateway 同步跳过: %s", e)

        self._synced_at = time.time()
        logger.info(
            "CapabilityRegistry.sync: mcp=%d skill=%d gateway=%d",
            counts["mcp"], counts["skill"], counts["gateway"],
        )
        return counts

    # ------------------------------------------------------------------
    # 内置节点注册（静态，无需外部依赖）
    # ------------------------------------------------------------------

    def _register_builtin_nodes(self) -> None:
        """注册内置执行节点描述（无 invoke_fn，调用时通过 scheduler/node 执行）"""

        builtin_tools = [
            CapabilityDescriptor(
                name="node_filesystem",
                capability_type=CapabilityType.NODE,
                description="文件系统操作：读写/创建/删除/移动/搜索文件",
                parameters={
                    "action": {"type": "string", "enum": ["read", "write", "list", "delete", "move", "search"]},
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                source_id="node_06",
            ),
            CapabilityDescriptor(
                name="node_code_execute",
                capability_type=CapabilityType.NODE,
                description="代码沙箱执行：支持 Python/JS/Bash/Go/Rust 等多语言",
                parameters={
                    "language": {"type": "string"},
                    "code": {"type": "string"},
                },
                source_id="node_09",
            ),
            CapabilityDescriptor(
                name="node_web_search",
                capability_type=CapabilityType.NODE,
                description="网络搜索（Brave/Google）",
                parameters={"query": {"type": "string"}},
                source_id="node_22",
            ),
            CapabilityDescriptor(
                name="node_shell",
                capability_type=CapabilityType.NODE,
                description="系统命令执行",
                parameters={"command": {"type": "string"}},
                source_id="node_122",
            ),
            CapabilityDescriptor(
                name="node_adb_device",
                capability_type=CapabilityType.NODE,
                description="Android 设备控制：截图/点击/滑动/输入文本",
                parameters={
                    "action": {"type": "string", "enum": ["tap", "swipe", "screenshot", "input", "shell"]},
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                    "text": {"type": "string"},
                },
                source_id="node_33",
            ),
            CapabilityDescriptor(
                name="node_desktop_auto",
                capability_type=CapabilityType.NODE,
                description="桌面自动化：点击/输入/截图/快捷键",
                parameters={
                    "action": {"type": "string", "enum": ["click", "type", "hotkey", "screenshot", "scroll"]},
                },
                source_id="node_45",
            ),
            CapabilityDescriptor(
                name="node_http_request",
                capability_type=CapabilityType.NODE,
                description="HTTP 请求（GET/POST）",
                parameters={
                    "method": {"type": "string", "enum": ["get", "post"]},
                    "url": {"type": "string"},
                    "body": {"type": "object"},
                },
                source_id="node_08",
            ),
            CapabilityDescriptor(
                name="node_ocr",
                capability_type=CapabilityType.NODE,
                description="图像 OCR 文字提取 / 文档转 Markdown",
                parameters={
                    "action": {"type": "string", "enum": ["extract_text", "document_markdown", "table_extract"]},
                    "image_base64": {"type": "string"},
                },
                source_id="node_15",
            ),
        ]

        for cap in builtin_tools:
            self._capabilities[cap.name] = cap


# ============================================================================
# 模块级单例
# ============================================================================

_registry_instance: Optional[CapabilityRegistry] = None


def get_capability_registry() -> CapabilityRegistry:
    """获取 CapabilityRegistry 全局单例"""
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = CapabilityRegistry()
    return _registry_instance
