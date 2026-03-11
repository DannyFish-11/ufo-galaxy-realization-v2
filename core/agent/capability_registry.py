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
    CapabilityRegistry.get_load_status() -> Dict  — Dashboard 可观测状态
    CapabilityRegistry.sync_device()  — 设备注册事件立即同步
    CapabilityRegistry.validate_mcp_tool_schema() — MCP 协议校验
    CapabilityRegistry.validate_skill_manifest()  — Skill 协议校验
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

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

        # 可观测加载状态（Dashboard 用）
        self._load_status: Dict[str, Any] = {
            "loaded": False,
            "last_refresh_ts": 0.0,
            "tool_count": 0,
            "by_source": {},
            "validated": {"mcp": 0, "skill": 0},
            "errors": [],
        }
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

    def get_load_status(self) -> Dict[str, Any]:
        """返回 Dashboard 可观测的加载状态（loaded/validated/errors/tool_count）。"""
        return dict(self._load_status)

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
            errors: List[str] = []
            validated_counts: Dict[str, int] = {"mcp": 0, "skill": 0}

            await asyncio.gather(
                self._load_mcp(new_items, errors, validated_counts),
                self._load_skills(new_items, errors, validated_counts),
                self._load_gateway(new_items, errors),
                return_exceptions=True,
            )

            self._items = new_items
            self._last_refresh = time.monotonic()

            by_source: Dict[str, int] = {}
            for i in new_items.values():
                by_source[i.source] = by_source.get(i.source, 0) + 1

            self._load_status.update({
                "loaded": True,
                "last_refresh_ts": self._last_refresh,
                "tool_count": len(new_items),
                "by_source": by_source,
                "validated": validated_counts,
                "errors": errors,
            })

            logger.info(
                "CapabilityRegistry: 刷新完成，共 %d 项能力 (mcp=%d skill=%d gateway=%d) 错误=%d",
                len(new_items),
                by_source.get("mcp", 0),
                by_source.get("skill", 0),
                by_source.get("gateway", 0),
                len(errors),
            )

    # ──────────────────────────────────────────────────────────────────
    # 分源加载
    # ──────────────────────────────────────────────────────────────────

    async def _load_mcp(self, target: Dict[str, CapabilityItem], errors: Optional[List[str]] = None, validated: Optional[Dict[str, int]] = None) -> None:
        """从 MCPLoader 加载工具列表（含标准协议 schema 校验）。"""
        try:
            from core.mcp_loader import MCPLoader
            loader = MCPLoader.get_instance()
            servers = loader.list_servers() if hasattr(loader, "list_servers") else {}

            if not servers:
                return

            for server in (servers if isinstance(servers, list) else servers.values()):
                # list_servers() returns list of dicts
                if isinstance(server, dict):
                    server_id = server.get("id", "")
                    tools_raw = []  # tools are on the instance, not the dict
                    # get real instance
                    inst = loader.servers.get(server_id) if hasattr(loader, "servers") else None
                    tools_raw = inst.tools if inst else []
                else:
                    server_id = getattr(server, "id", "")
                    tools_raw = getattr(server, "tools", []) or []

                for tool in tools_raw:
                    tool_name = getattr(tool, "name", None) or (tool.get("name", "") if isinstance(tool, dict) else "")
                    tool_desc = getattr(tool, "description", "") or (tool.get("description", "") if isinstance(tool, dict) else "")
                    if not tool_name:
                        continue
                    params = getattr(tool, "inputSchema", None) or (tool.get("inputSchema", {}) if isinstance(tool, dict) else {})

                    # 协议校验
                    ok, err = self.validate_mcp_tool_schema({"name": tool_name, "description": tool_desc, "inputSchema": params})
                    if not ok:
                        msg = f"MCP server={server_id} tool={tool_name}: {err}"
                        logger.warning("MCP tool schema 校验失败: %s", msg)
                        if errors is not None:
                            errors.append(msg)
                        continue
                    if validated is not None:
                        validated["mcp"] = validated.get("mcp", 0) + 1

                    key = f"mcp__{server_id}__{tool_name}"
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
            msg = f"MCP 能力加载失败: {exc}"
            logger.warning(msg)
            if errors is not None:
                errors.append(msg)

    async def _load_skills(self, target: Dict[str, CapabilityItem], errors: Optional[List[str]] = None, validated: Optional[Dict[str, int]] = None) -> None:
        """从 SkillLoader 加载技能列表（含 manifest 校验）。"""
        try:
            from core.skill_loader import SkillLoader
            loader = SkillLoader.get_instance()
            skills = loader.list_skills() if hasattr(loader, "list_skills") else []

            for skill in skills:
                skill_id = getattr(skill, "skill_id", None) or (skill.get("id", "") if isinstance(skill, dict) else "")
                skill_name = getattr(skill, "name", None) or (skill.get("name", skill_id) if isinstance(skill, dict) else skill_id)
                skill_desc = getattr(skill, "description", "") or (skill.get("description", "") if isinstance(skill, dict) else "")
                if not skill_id:
                    continue

                # manifest 校验
                ok, err = self.validate_skill_manifest(skill if isinstance(skill, dict) else {"id": skill_id, "name": skill_name, "description": skill_desc})
                if not ok:
                    msg = f"Skill id={skill_id}: {err}"
                    logger.warning("Skill manifest 校验失败: %s", msg)
                    if errors is not None:
                        errors.append(msg)
                    continue
                if validated is not None:
                    validated["skill"] = validated.get("skill", 0) + 1

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
            msg = f"Skill 能力加载失败: {exc}"
            logger.warning(msg)
            if errors is not None:
                errors.append(msg)

    async def _load_gateway(self, target: Dict[str, CapabilityItem], errors: Optional[List[str]] = None) -> None:
        """从设备注册表加载 Gateway 能力。"""
        try:
            from core.device_registry import DeviceRegistry
            registry = DeviceRegistry.get_instance() if hasattr(DeviceRegistry, "get_instance") else None
            if registry is None:
                try:
                    registry = DeviceRegistry()
                except Exception:
                    return

            devices = registry.list_devices() if hasattr(registry, "list_devices") else {}
            if not devices:
                return

            for device_id, device in (devices.items() if isinstance(devices, dict) else enumerate(devices)):
                if isinstance(device, dict):
                    caps = device.get("capabilities", [])
                    d_name = device.get("device_name", str(device_id))
                else:
                    caps = getattr(device, "capabilities", [])
                    d_name = getattr(device, "device_name", str(device_id))

                for cap in caps:
                    key = f"gateway__{device_id}__{cap}"
                    target[key] = CapabilityItem(
                        name=key,
                        description=f"[Gateway:{d_name}] 设备能力: {cap}",
                        source="gateway",
                        source_id=str(device_id),
                        available=True,
                    )
            logger.debug("Gateway 能力加载: %d 项", sum(1 for i in target.values() if i.source == "gateway"))
        except Exception as exc:
            msg = f"Gateway 能力加载失败: {exc}"
            logger.warning(msg)
            if errors is not None:
                errors.append(msg)


    # ──────────────────────────────────────────────────────────────────
    # 协议校验
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def validate_mcp_tool_schema(tool: Dict[str, Any]) -> Tuple[bool, str]:
        """
        校验 MCP 标准工具 schema。

        要求字段: name (str), description (str), inputSchema (dict)。
        返回 (ok, error_message)。
        """
        if not isinstance(tool, dict):
            return False, "tool must be a dict"
        name = tool.get("name", "")
        if not name or not isinstance(name, str):
            return False, "missing or invalid 'name' field"
        desc = tool.get("description", "")
        if not isinstance(desc, str):
            return False, "'description' must be a string"
        schema = tool.get("inputSchema") or tool.get("input_schema")  # MCP standard: inputSchema; legacy alias: input_schema
        if schema is not None and not isinstance(schema, dict):
            return False, "'inputSchema' must be a dict"
        return True, ""

    @staticmethod
    def validate_skill_manifest(manifest: Dict[str, Any]) -> Tuple[bool, str]:
        """
        校验 Skill manifest（skill.json / SkillInstance dict）。

        要求字段: id 或 skill_id, name, description。
        返回 (ok, error_message)。
        """
        if not isinstance(manifest, dict):
            return False, "manifest must be a dict"
        skill_id = manifest.get("id") or manifest.get("skill_id", "")
        if not skill_id:
            return False, "missing 'id' or 'skill_id' field"
        name = manifest.get("name", "")
        if not name:
            return False, "missing 'name' field"
        # description is recommended but not hard-required
        return True, ""

    # ──────────────────────────────────────────────────────────────────
    # 设备即时同步
    # ──────────────────────────────────────────────────────────────────

    def sync_device(self, device_id: str, device_name: str, capabilities: List[str]) -> int:
        """
        立即将新注册设备的能力同步到注册表（无需等待下次完整刷新）。

        当设备注册事件触发时调用，确保新设备立即可被 LLM 选中。
        返回新增的能力条目数量。
        """
        added = 0
        for cap in capabilities:
            key = f"gateway__{device_id}__{cap}"
            if key not in self._items:
                self._items[key] = CapabilityItem(
                    name=key,
                    description=f"[Gateway:{device_name}] 设备能力: {cap}",
                    source="gateway",
                    source_id=device_id,
                    available=True,
                )
                added += 1
        if added:
            # 更新 load_status 计数
            by_source = self._load_status.get("by_source", {})
            by_source["gateway"] = by_source.get("gateway", 0) + added
            self._load_status["by_source"] = by_source
            self._load_status["tool_count"] = len(self._items)
            logger.info(
                "CapabilityRegistry.sync_device: 设备 %s 新增 %d 项能力", device_id, added
            )
        return added


# ──────────────────────────────────────────────────────────────────────────────
# 模块级便捷函数
# ──────────────────────────────────────────────────────────────────────────────


def get_capability_registry() -> CapabilityRegistry:
    """返回全局 CapabilityRegistry 单例。"""
    return CapabilityRegistry.get_instance()
