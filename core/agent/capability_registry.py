"""
core/agent/capability_registry.py
====================================
统一能力注册表

汇聚系统中所有可供 Agent 调用的"弹药"：
  - MCP 工具  (core.mcp_loader)
  - Skill 技能 (core.skill_loader)
  - Gateway 设备能力 (core.capability_manager + device_registry)

公共 API：
    CapabilityRegistry.get_instance() -> CapabilityRegistry
    CapabilityRegistry.refresh()      — 重新加载所有能力
    CapabilityRegistry.list_tools()   -> List[CapabilityItem]
    CapabilityRegistry.find(query)    -> List[CapabilityItem]
    CapabilityRegistry.get(name)      -> Optional[CapabilityItem]
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.Agent.CapabilityRegistry")

# ──────────────────────────────────────────────────────────────────────────────
# 数据模型
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class CapabilityItem:
    """统一能力描述条目。"""

    name: str
    """能力标识符（唯一键）"""

    description: str
    """能力功能描述（供 LLM 工具选择）"""

    source: str
    """来源类型: mcp | skill | gateway | node"""

    source_id: str = ""
    """来源 ID（如 mcp server_id、skill_id、device_id）"""

    parameters: Dict[str, Any] = field(default_factory=dict)
    """参数 schema（JSON Schema 格式）"""

    available: bool = True
    """当前是否可用"""

    metadata: Dict[str, Any] = field(default_factory=dict)
    """附加元数据"""

    def to_tool_schema(self) -> Dict[str, Any]:
        """转换为 OpenAI function calling 格式的工具 schema。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters or {
                    "type": "object",
                    "properties": {},
                },
            },
        }


# ──────────────────────────────────────────────────────────────────────────────
# 注册表主体
# ──────────────────────────────────────────────────────────────────────────────


class CapabilityRegistry:
    """统一能力注册表（进程级单例，线程安全）。"""

    _instance: Optional["CapabilityRegistry"] = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls) -> "CapabilityRegistry":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._items: Dict[str, CapabilityItem] = {}
        self._refresh_lock: Optional[asyncio.Lock] = None  # created lazily in async context
        self._last_refresh: float = 0.0
        self._refresh_interval: float = 120.0  # 2 分钟自动刷新
        logger.info("CapabilityRegistry 已初始化")

    @classmethod
    def get_instance(cls) -> "CapabilityRegistry":
        return cls()

    # ──────────────────────────────────────────────────────────────────
    # 查询 API
    # ──────────────────────────────────────────────────────────────────

    def list_tools(self, source: Optional[str] = None) -> List[CapabilityItem]:
        """返回所有（或指定来源的）可用能力列表。"""
        items = [i for i in self._items.values() if i.available]
        if source:
            items = [i for i in items if i.source == source]
        return items

    def get(self, name: str) -> Optional[CapabilityItem]:
        """根据名称获取能力条目。"""
        return self._items.get(name)

    def find(self, query: str) -> List[CapabilityItem]:
        """关键词搜索能力（名称 + 描述匹配）。"""
        q = query.lower()
        return [
            i for i in self._items.values()
            if i.available and (q in i.name.lower() or q in i.description.lower())
        ]

    def register(self, item: CapabilityItem) -> None:
        """手动注册一个能力条目。"""
        self._items[item.name] = item
        logger.debug("能力已注册: %s (%s)", item.name, item.source)

    def to_tool_schemas(self) -> List[Dict[str, Any]]:
        """返回所有可用能力的 OpenAI function calling 格式 schema 列表。"""
        return [item.to_tool_schema() for item in self.list_tools()]

    def stats(self) -> Dict[str, Any]:
        """返回注册表统计信息。"""
        total = len(self._items)
        available = sum(1 for i in self._items.values() if i.available)
        by_source: Dict[str, int] = {}
        for i in self._items.values():
            by_source[i.source] = by_source.get(i.source, 0) + 1
        return {
            "total": total,
            "available": available,
            "by_source": by_source,
            "last_refresh": self._last_refresh,
        }

    # ──────────────────────────────────────────────────────────────────
    # 刷新逻辑
    # ──────────────────────────────────────────────────────────────────

    async def refresh(self, force: bool = False) -> None:
        """从所有来源重新加载能力列表（带间隔保护）。"""
        now = time.monotonic()
        if not force and (now - self._last_refresh) < self._refresh_interval:
            return

        # 惰性创建 asyncio.Lock（确保在事件循环中创建）
        if self._refresh_lock is None:
            self._refresh_lock = asyncio.Lock()

        async with self._refresh_lock:
            # 双重检查（重新获取当前时间）
            now = time.monotonic()
            if not force and (now - self._last_refresh) < self._refresh_interval:
                return

            logger.info("CapabilityRegistry: 开始刷新能力列表 …")
            new_items: Dict[str, CapabilityItem] = {}

            await asyncio.gather(
                self._load_mcp(new_items),
                self._load_skills(new_items),
                self._load_gateway(new_items),
                self._load_autonomous(new_items),
                return_exceptions=True,
            )

            self._items = new_items
            self._last_refresh = time.monotonic()
            logger.info(
                "CapabilityRegistry: 刷新完成，共 %d 项能力 (mcp=%d skill=%d gateway=%d autonomous=%d)",
                len(new_items),
                sum(1 for i in new_items.values() if i.source == "mcp"),
                sum(1 for i in new_items.values() if i.source == "skill"),
                sum(1 for i in new_items.values() if i.source == "gateway"),
                sum(1 for i in new_items.values() if i.source == "autonomous"),
            )

    # ──────────────────────────────────────────────────────────────────
    # 分源加载
    # ──────────────────────────────────────────────────────────────────

    async def _load_mcp(self, target: Dict[str, CapabilityItem]) -> None:
        """从 MCPLoader 加载工具列表。"""
        try:
            from core.mcp_loader import MCPLoader
            loader = MCPLoader.get_instance()
            servers = loader.list_servers() if hasattr(loader, "list_servers") else {}

            if not servers:
                return

            for server_id, server in servers.items():
                tools = getattr(server, "tools", []) or []
                for tool in tools:
                    tool_name = getattr(tool, "name", None) or tool.get("name", "")
                    tool_desc = getattr(tool, "description", "") or tool.get("description", "")
                    if not tool_name:
                        continue
                    key = f"mcp__{server_id}__{tool_name}"
                    params = getattr(tool, "input_schema", None) or tool.get("input_schema", {})
                    target[key] = CapabilityItem(
                        name=key,
                        description=f"[MCP:{server_id}] {tool_desc}",
                        source="mcp",
                        source_id=server_id,
                        parameters=params or {},
                        available=True,
                    )
            logger.debug("MCP 能力加载: %d 项", sum(1 for i in target.values() if i.source == "mcp"))
        except Exception as exc:
            logger.warning("MCP 能力加载失败: %s", exc)

    async def _load_skills(self, target: Dict[str, CapabilityItem]) -> None:
        """从 SkillLoader 加载技能列表。"""
        try:
            from core.skill_loader import SkillLoader
            loader = SkillLoader.get_instance()
            skills = loader.list_skills() if hasattr(loader, "list_skills") else []

            for skill in skills:
                skill_id = getattr(skill, "skill_id", None) or skill.get("skill_id", "")
                skill_name = getattr(skill, "name", None) or skill.get("name", skill_id)
                skill_desc = getattr(skill, "description", "") or skill.get("description", "")
                if not skill_id:
                    continue
                key = f"skill__{skill_id}"
                target[key] = CapabilityItem(
                    name=key,
                    description=f"[Skill] {skill_desc or skill_name}",
                    source="skill",
                    source_id=skill_id,
                    available=True,
                )
            logger.debug("Skill 能力加载: %d 项", sum(1 for i in target.values() if i.source == "skill"))
        except Exception as exc:
            logger.warning("Skill 能力加载失败: %s", exc)

    async def _load_gateway(self, target: Dict[str, CapabilityItem]) -> None:
        """从 UnifiedDeviceManager 加载 Gateway 设备能力（Priority A: SSOT）。"""
        try:
            from core.unified.device_manager import get_unified_device_manager
            udm = get_unified_device_manager()
            devices = udm.list_devices()
            if not devices:
                return

            for device in devices:
                device_id = device.device_id
                d_name = device.device_name or device_id
                for cap in (device.capabilities or []):
                    key = f"gateway__{device_id}__{cap}"
                    target[key] = CapabilityItem(
                        name=key,
                        description=f"[Gateway:{d_name}] 设备能力: {cap}",
                        source="gateway",
                        source_id=device_id,
                        available=True,
                        metadata={
                            "device_name": d_name,
                            "device_type": str(device.device_type),
                        },
                    )
            logger.debug(
                "Gateway 能力加载: %d 项",
                sum(1 for i in target.values() if i.source == "gateway"),
            )
        except Exception as exc:
            logger.warning("Gateway 能力加载失败: %s", exc)

    async def _load_autonomous(self, target: Dict[str, CapabilityItem]) -> None:
        """从 UnifiedDeviceManager 加载高层自治能力（Priority C）。

        自治能力由设备在注册时通过 metadata 声明，例如：
          metadata.goal_execution_enabled = true
          metadata.local_task_planning = true
          metadata.local_ui_reasoning = true
          metadata.cross_device_coordination = true
          metadata.parallel_execution_enabled = true
        """
        _AUTONOMOUS_CAPABILITY_KEYS = (
            "goal_execution_enabled",
            "local_task_planning",
            "local_ui_reasoning",
            "cross_device_coordination",
            "parallel_execution_enabled",
            "local_model_enabled",
        )
        _AUTONOMOUS_DESCRIPTIONS = {
            "goal_execution_enabled": "设备支持高层目标执行（自然语言→端侧自主规划执行）",
            "local_task_planning": "设备支持本地任务规划（无需服务端逐步指令）",
            "local_ui_reasoning": "设备支持本地 UI 语义理解与推理",
            "cross_device_coordination": "设备支持跨设备协同执行",
            "parallel_execution_enabled": "设备支持并行任务执行",
            "local_model_enabled": "设备搭载本地推理模型",
        }
        try:
            from core.unified.device_manager import get_unified_device_manager
            udm = get_unified_device_manager()
            devices = udm.list_devices()

            for device in devices:
                meta = device.metadata or {}
                for cap_key in _AUTONOMOUS_CAPABILITY_KEYS:
                    if meta.get(cap_key):
                        key = f"autonomous__{device.device_id}__{cap_key}"
                        target[key] = CapabilityItem(
                            name=key,
                            description=(
                                f"[Autonomous:{device.device_name}] "
                                f"{_AUTONOMOUS_DESCRIPTIONS.get(cap_key, cap_key)}"
                            ),
                            source="autonomous",
                            source_id=device.device_id,
                            available=True,
                            metadata={
                                "device_id": device.device_id,
                                "device_name": device.device_name,
                                "device_type": str(device.device_type),
                                "capability_key": cap_key,
                            },
                        )
            logger.debug(
                "Autonomous 能力加载: %d 项",
                sum(1 for i in target.values() if i.source == "autonomous"),
            )
        except Exception as exc:
            logger.warning("Autonomous 能力加载失败: %s", exc)


# ──────────────────────────────────────────────────────────────────────────────
# 模块级便捷函数
# ──────────────────────────────────────────────────────────────────────────────


def get_capability_registry() -> CapabilityRegistry:
    """返回全局 CapabilityRegistry 单例。"""
    return CapabilityRegistry.get_instance()
