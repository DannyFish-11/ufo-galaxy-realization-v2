"""
core/agent/capability_registry.py
====================================
PR-002 — Canonical In-Process Capability Catalog (SSOT)

**Canonical role**: ``CapabilityRegistry`` is the *authoritative in-process
inventory* of all capabilities available to the Galaxy system.  Every
capability — regardless of origin — must be registered here before it can
be consumed by ``OpenClawd`` or any other subsystem.

Architecture contract
---------------------
- **Writers / loaders** push entries in:
    - MCP tools     → ``mcp_loader`` calls ``inject_mcp_tool()`` after loading a server
    - Skills         → ``skill_loader`` calls ``inject_skill()`` after loading a skill
    - Node caps      → ``NodeFabricRegistry`` calls ``inject_item()`` after node sync
    - Gateway caps   → registered via ``_load_gateway()`` / ``inject_item()``
    - Device caps    → ``core.routes.devices._sync_device_to_capability_registry()``
    - CapabilityBus  → **bridged automatically** (CAPABILITY_BUS_CANONICAL_BRIDGE_ACTIVE)
    - CapabilityManager → **bridged automatically** (CAPABILITY_MANAGER_CANONICAL_BRIDGE_ACTIVE)
    - AutonomousCoder → registers directly via ``inject_item()`` (canonical path)
- **Consumers** (``OpenClawd``, projections, diagnostics) read through
  :class:`~core.unified.capability_resolver.CapabilityResolver`, which applies
  :class:`~core.unified.capability_contract.CapabilityContract` validation
  before returning entries.  Consumers **must not** bypass the resolver to
  hand-roll registry traversal.
- All entries are validated against
  :class:`~core.unified.capability_contract.CapabilityContract` at
  registration time.  Entries that fail validation are rejected and logged.

Sentinel: ``CAPABILITY_REGISTRY_IS_CANONICAL_TRUTH_SOURCE``
  Confirms this module is the single canonical truth source.  All compat
  bridges (CapabilityBus, CapabilityManager) converge here.

Public API
----------
    CapabilityRegistry.get_instance() -> CapabilityRegistry
    CapabilityRegistry.refresh()      — reload all capabilities from sources
    CapabilityRegistry.list_tools()   -> List[CapabilityItem]
    CapabilityRegistry.find(query)    -> List[CapabilityItem]
    CapabilityRegistry.get(name)      -> Optional[CapabilityItem]
    CapabilityRegistry.inject_mcp_tool(...)   — writer entry point (MCP)
    CapabilityRegistry.inject_skill(...)      — writer entry point (Skill)
    CapabilityRegistry.inject_item(item)      — writer entry point (Node/Gateway/compat)
    CapabilityRegistry.register(item)         — writer entry point (general)
    CapabilityRegistry.eject(name)            — removal entry point
    get_capability_registry()         -> CapabilityRegistry  (module-level helper)

Preferred consumer interface
-----------------------------
Use :func:`~core.unified.capability_resolver.get_capability_resolver` and
:meth:`~core.unified.capability_resolver.CapabilityResolver.collect_tool_schemas`
instead of accessing this registry directly from consumer code.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.Agent.CapabilityRegistry")

# ---------------------------------------------------------------------------
# PR-C04: CapabilityRegistry → CapabilityAssimilationLayer integration sentinel
# ---------------------------------------------------------------------------
# When CAPABILITY_REGISTRY_ASSIMILATION_LAYER_INTEGRATION is present, every
# registration method (register / inject_mcp_tool / inject_skill / inject_item)
# also projects the entry into the CapabilityAssimilationLayer so that the
# capability graph, task graph, and network graph runtimes see the node.
# This closes the legacy bypass where entries were written to _items only.
CAPABILITY_REGISTRY_ASSIMILATION_LAYER_INTEGRATION: str = (
    "CAPABILITY_REGISTRY_ASSIMILATION_LAYER_INTEGRATION_V1"
)

# ---------------------------------------------------------------------------
# Governance sentinel
# ---------------------------------------------------------------------------
# Presence of this sentinel confirms that CapabilityRegistry is the canonical
# in-process truth source for all capabilities.  All compat bridges
# (CapabilityBus, CapabilityManager) converge here.
CAPABILITY_REGISTRY_IS_CANONICAL_TRUTH_SOURCE = True

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
        self._lock = threading.Lock()  # used by NodeFabricRegistry.expire_stale_capabilities
        self._refresh_lock: Optional[asyncio.Lock] = None  # created lazily in async context
        self._last_refresh: float = 0.0
        self._refresh_interval: float = 120.0  # 2 分钟自动刷新
        self._validation_errors: list = []  # schema 校验错误记录
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

    def find_by_system_integration_id(self, integration_id: str) -> Optional[CapabilityItem]:
        """Return the registered item associated with a SystemIntegration ID."""
        for item in self._items.values():
            if str((item.metadata or {}).get("system_integration_id") or "") == str(integration_id):
                return item
        return None

    def register(self, item: Any) -> None:
        """手动注册一个能力条目或 canonical contract。"""
        try:
            from core.unified.capability_contract import CapabilityContract

            if isinstance(item, CapabilityContract):
                item = CapabilityItem(
                    name=item.name,
                    description=item.description,
                    source=item.source.value if hasattr(item.source, "value") else str(item.source),
                    source_id=item.source_id,
                    parameters=item.parameters,
                    available=item.available,
                    metadata={
                        **dict(item.metadata or {}),
                        "contract_version": item.version,
                        "contract_tags": list(item.tags or []),
                        "contract_created_at": item.created_at,
                    },
                )
        except Exception as exc:
            logger.warning("Exception suppressed: %s", exc)
        self._normalize_capability_plane_metadata(item)
        self._annotate_unified_capability_plane(item, mutation_source="capability_registry.register")
        if not self._validate_via_contract(item):
            return
        self._items[item.name] = item
        # PR-C04: project into CapabilityAssimilationLayer so the capability
        # graph, task graph, and network graph see this entry.
        self._assimilate_to_capability_layer(item)
        logger.debug("能力已注册: %s (%s)", item.name, item.source)

    @staticmethod
    def _normalize_capability_plane_metadata(item: CapabilityItem) -> None:
        """Normalize item metadata into canonical capability-plane provider model."""
        try:
            from core.unified.capability_contract import normalize_capability_provider_metadata

            item.metadata = normalize_capability_provider_metadata(
                name=item.name,
                source=item.source,
                source_id=item.source_id,
                metadata=item.metadata or {},
            )
        except Exception as exc:
            logger.debug(
                "capability provider metadata normalization skipped for '%s': %s",
                getattr(item, "name", "?"),
                exc,
            )

    @staticmethod
    def _annotate_unified_capability_plane(
        item: CapabilityItem,
        *,
        mutation_source: str,
    ) -> None:
        """Attach unified-plane lifecycle/runtime metadata to *item*."""
        metadata = dict(item.metadata or {})
        plane = dict(metadata.get("capability_plane") or {})
        runtime_state = dict(metadata.get("runtime_state") or {})
        record_version = int(plane.get("record_version", 0) or 0) + 1
        runtime_state.setdefault(
            "availability",
            "available" if item.available else "unknown",
        )
        runtime_state.setdefault("device_bindings", [])
        runtime_state.setdefault("preferred_device_ids", [])
        runtime_state.setdefault("constraint_flags", {})
        runtime_state.setdefault("reliability_flags", {})
        runtime_state.setdefault("metadata", {})
        runtime_state["last_updated"] = time.time()
        metadata["capability_id"] = item.name
        metadata["authority_lineage"] = [
            "capability_registry",
            "capability_authority",
            "capability_resolver",
        ]
        metadata["capability_plane"] = {
            "authority": "UNIFIED_CAPABILITY_PLANE_AUTHORITY::CapabilityRegistry",
            "record_version": record_version,
            "lifecycle_event": plane.get("lifecycle_event") or "capability_registered",
            "mutation_source": plane.get("mutation_source") or metadata.get("mutation_source") or mutation_source,
            "publication_source": plane.get("publication_source") or item.source_id or item.source,
            "last_updated": runtime_state["last_updated"],
            "authority_lineage": list(metadata["authority_lineage"]),
        }
        try:
            from core.peripheral_capability_boundary import build_capability_registry_ingress_contract

            metadata.setdefault(
                "ingress_boundary_contract",
                build_capability_registry_ingress_contract(),
            )
        except ImportError as exc:
            logger.debug("ingress boundary contract annotation skipped for '%s': %s", item.name, exc)
        metadata["runtime_state"] = runtime_state
        item.metadata = metadata
        item.available = runtime_state.get("availability") in {"available", "degraded"}

    # ── PR-C04: AssimilationLayer projection helper ────────────────────────

    @staticmethod
    def _assimilate_to_capability_layer(item: CapabilityItem) -> None:
        """Project a registered CapabilityItem into the CapabilityAssimilationLayer.

        This is a best-effort, fire-and-forget projection.  Failure is logged at
        DEBUG and never raises — registration into CapabilityRegistry must succeed
        even if the assimilation layer is unavailable.

        The mapping from CapabilityItem.source → assimilation type:
            - "gateway" / "autonomous" → assimilate_device()
            - "mcp"                  → assimilate_mcp_provider()
            - "skill"                → assimilate_skill()
            - "node" / other         → assimilate_node() (generic)
        """
        try:
            from core.capability_assimilation import (
                get_capability_assimilation_layer,
                NodeParticipantKind,
                assimilate_device,
                assimilate_mcp_provider,
                assimilate_skill,
            )

            source = getattr(item, "source", "") or "unknown"
            name = getattr(item, "name", "") or ""
            source_id = getattr(item, "source_id", "") or name

            if source in ("gateway", "autonomous", "device"):
                # Map device-type sources → assimilate_device
                caps = []
                if source == "gateway":
                    cap_name = name.split("__")[-1] if "__" in name else name
                    caps = [cap_name] if cap_name else []
                meta = dict(getattr(item, "metadata", {}) or {})
                meta.setdefault("capability_registry_source", source)
                meta.setdefault("capability_registry_name", name)
                # Extract embedded device_capabilities from metadata if caps empty
                embedded_caps = meta.get("device_capabilities", []) or []
                final_caps = caps or embedded_caps
                assimilate_device(
                    device_id=source_id or name,
                    capabilities=final_caps,
                    tags=[source],
                    metadata=meta,
                )
                logger.debug(
                    "PR-C04: assimilated device via register path: source=%s name=%s",
                    source,
                    name,
                )

            elif source == "mcp":
                # Map MCP sources → assimilate_mcp_provider
                server_id = source_id or name
                tool_name = name.split("__")[-1] if "__" in name else name
                assimilate_mcp_provider(
                    provider_id=server_id,
                    tools=[tool_name],
                    tags=["mcp"],
                    metadata={
                        "capability_registry_name": name,
                        "capability_registry_source": source,
                    },
                )
                logger.debug(
                    "PR-C04: assimilated MCP provider via inject_mcp_tool path: %s",
                    name,
                )

            elif source == "skill":
                # Map Skill sources → assimilate_skill
                skill_id = source_id or name
                assimilate_skill(
                    skill_id=skill_id,
                    capabilities=[name],
                    tags=["skill"],
                    metadata={
                        "capability_registry_name": name,
                        "capability_registry_source": source,
                    },
                )
                logger.debug(
                    "PR-C04: assimilated skill via inject_skill path: %s",
                    name,
                )

            else:
                # Generic node path — fall back to direct assimilate() call
                layer = get_capability_assimilation_layer()
                layer.assimilate(
                    node_id=source_id or name,
                    capabilities=[name],
                    participant_kind=NodeParticipantKind.CAPABILITY_PROVIDER,
                    tags=[source],
                    metadata={
                        "capability_registry_source": source,
                        "capability_registry_name": name,
                    },
                )
                logger.debug(
                    "PR-C04: assimilated generic provider via register path: source=%s name=%s",
                    source,
                    name,
                )

        except Exception as exc:
            logger.debug(
                "PR-C04: CapabilityAssimilationLayer projection skipped for '%s': %s",
                getattr(item, "name", "?"),
                exc,
            )

    def _validate_via_contract(self, item: CapabilityItem) -> bool:
        """PR-2: 通过统一能力合同校验 CapabilityItem。

        Uses :func:`~core.unified.capability_contract.validate_capability_contract`
        so that the unified schema rules are enforced at registration time.

        Returns:
            True  — 校验通过
            False — 校验失败（已记录错误，调用方应跳过注入）
        """
        try:
            from core.unified.capability_contract import (
                CapabilityContract,
                CapabilitySource,
                validate_capability_contract,
            )
            src_val = getattr(item, "source", "unknown") or "unknown"
            try:
                src = CapabilitySource(src_val)
            except ValueError:
                src = CapabilitySource.UNKNOWN
            contract = CapabilityContract(
                name=item.name,
                description=item.description,
                source=src,
                source_id=item.source_id,
                parameters=item.parameters or {},
                available=item.available,
                metadata=item.metadata or {},
            )
            validate_capability_contract(contract)
            return True
        except Exception as exc:
            logger.debug("Fallback triggered: %s", exc)
            violations = getattr(exc, "violations", [str(exc)])
            msg = f"capability_contract validation failed for '{item.name}': {violations}"
            logger.warning(msg)
            self._validation_errors.append({
                "source": getattr(item, "source", "?"),
                "id": item.name,
                "error": msg,
                "violations": violations,
            })
            return False

    def to_tool_schemas(self) -> List[Dict[str, Any]]:
        """返回所有可用能力的 OpenAI function calling 格式 schema 列表。"""
        return [item.to_tool_schema() for item in self.list_tools()]

    def stats(self) -> Dict[str, Any]:
        """返回注册表统计信息（含校验错误，可观测能力总线状态）。"""
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
            "validation_errors": list(self._validation_errors),
        }

    # ──────────────────────────────────────────────────────────────────
    # 快速注入 API（跳过全量刷新，供 mcp_loader / skill_loader 在加载后调用）
    # ──────────────────────────────────────────────────────────────────

    def _validate_parameters_schema(
        self,
        parameters: Any,
        source: str,
        entity_id: str,
    ) -> bool:
        """校验 parameters 必须为 dict（JSON Schema 格式）。

        Returns:
            True  — 校验通过
            False — 校验失败（已记录错误，调用方应跳过注入）
        """
        if parameters is not None and not isinstance(parameters, dict):
            msg = f"{source} {entity_id}: parameters schema 必须为 dict，跳过注入"
            logger.warning(msg)
            self._validation_errors.append({"source": source, "id": entity_id, "error": msg})
            return False
        return True

    def inject_mcp_tool(
        self,
        server_id: str,
        tool_name: str,
        description: str,
        parameters: Dict[str, Any],
        server_name: str = "",
    ) -> None:
        """将单个 MCP 工具直接注入能力总线（unified contract 校验 → 不通过则记录错误并跳过）。"""
        if not tool_name:
            return
        if not self._validate_parameters_schema(parameters, "mcp", f"{server_id}/{tool_name}"):
            return
        key = f"mcp__{server_id}__{tool_name}"
        item = CapabilityItem(
            name=key,
            description=f"[MCP:{server_name or server_id}] {description}",
            source="mcp",
            source_id=server_id,
            parameters=parameters or {},
            available=True,
        )
        self._normalize_capability_plane_metadata(item)
        self._annotate_unified_capability_plane(item, mutation_source="capability_registry.inject_mcp_tool")
        if not self._validate_via_contract(item):
            return
        self._items[key] = item
        # PR-C04: project MCP tool into CapabilityAssimilationLayer
        self._assimilate_to_capability_layer(item)
        logger.debug("MCP 工具已注入能力总线: %s", key)

    def inject_skill(
        self,
        skill_id: str,
        skill_name: str,
        description: str,
        parameters: Dict[str, Any],
    ) -> None:
        """将单个 Skill 直接注入能力总线（unified contract 校验 → 不通过则记录错误并跳过）。"""
        if not skill_id:
            return
        if not self._validate_parameters_schema(parameters, "skill", skill_id):
            return
        key = f"skill__{skill_id}"
        item = CapabilityItem(
            name=key,
            description=f"[Skill] {description or skill_name}",
            source="skill",
            source_id=skill_id,
            parameters=parameters or {},
            available=True,
        )
        self._normalize_capability_plane_metadata(item)
        self._annotate_unified_capability_plane(item, mutation_source="capability_registry.inject_skill")
        if not self._validate_via_contract(item):
            return
        self._items[key] = item
        # PR-C04: project Skill into CapabilityAssimilationLayer
        self._assimilate_to_capability_layer(item)
        logger.debug("Skill 已注入能力总线: %s", key)

    def eject(self, name: str) -> None:
        """从能力总线移除一个条目（用于 MCP/Skill 卸载时清理）。"""
        removed = self._items.pop(name, None)
        if removed:
            try:
                from core.capability_runtime.capability_registry_runtime import CapabilityRuntimeRegistry

                CapabilityRuntimeRegistry.get_instance().deregister(name, _sync_authority=False)
            except Exception as exc:
                logger.warning("Exception suppressed: %s", exc)
            logger.debug("能力已从总线移除: %s", name)

    def inject_item(self, item: CapabilityItem) -> None:
        """
        直接注入任意 CapabilityItem（Block-6：Node Fabric 能力同步入口）。

        与 inject_mcp_tool / inject_skill 不同，本方法接受已构造好的
        CapabilityItem，适用于 NodeFabricRegistry → CapabilityRegistry 同步。

        通过 unified contract 校验后写入；校验失败则记录错误并跳过。
        """
        if not item.name:
            return
        self._normalize_capability_plane_metadata(item)
        self._annotate_unified_capability_plane(item, mutation_source="capability_registry.inject_item")
        if not self._validate_via_contract(item):
            return
        self._items[item.name] = item
        # PR-C04: project injected item into CapabilityAssimilationLayer
        self._assimilate_to_capability_layer(item)
        logger.debug("CapabilityItem injected: %s (source=%s)", item.name, item.source)

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

            # Converge all source loaders (MCP/Skill/Gateway/Autonomous) through one
            # canonical capability-plane publication normalization step.
            for item in new_items.values():
                self._normalize_capability_plane_metadata(item)

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
            from core.mcp_loader import MCPLoader, MCPServerStatus
            loader = MCPLoader.get_instance()
            # 直接访问 servers 字典（MCPServerInstance 对象）
            servers: Dict = getattr(loader, "servers", {})

            if not servers:
                return

            for server_id, server in servers.items():
                # 只加载运行中的服务器
                if getattr(server, "status", None) != MCPServerStatus.RUNNING:
                    continue
                server_name = getattr(server, "name", server_id)
                tools = getattr(server, "tools", []) or []
                for tool in tools:
                    tool_name = getattr(tool, "name", "")
                    tool_desc = getattr(tool, "description", "")
                    if not tool_name:
                        continue
                    key = f"mcp__{server_id}__{tool_name}"
                    # MCPTool 使用 inputSchema（不是 input_schema）
                    params = getattr(tool, "inputSchema", {}) or {}
                    target[key] = CapabilityItem(
                        name=key,
                        description=f"[MCP:{server_name}] {tool_desc}",
                        source="mcp",
                        source_id=server_id,
                        parameters=params,
                        available=True,
                    )
            logger.debug("MCP 能力加载: %d 项", sum(1 for i in target.values() if i.source == "mcp"))
        except Exception as exc:
            logger.warning("MCP 能力加载失败: %s", exc)

    async def _load_skills(self, target: Dict[str, CapabilityItem]) -> None:
        """从 SkillLoader 加载技能列表。"""
        try:
            from core.skill_loader import SkillLoader, SkillStatus
            loader = SkillLoader.get_instance()
            # 直接访问 skills 字典（SkillInstance 对象）
            skills: Dict = getattr(loader, "skills", {})

            for skill_id, skill in skills.items():
                # ERROR 状态的技能（schema 校验失败 / handler 缺失）不注入
                if getattr(skill, "status", None) == SkillStatus.ERROR:
                    logger.debug("Skill %s 状态为 ERROR，跳过注入能力总线", skill_id)
                    continue
                key = f"skill__{skill_id}"
                # 通过 to_mcp_tool_schema 获取标准 JSON Schema
                mcp_schema = loader.to_mcp_tool_schema(skill_id)
                params = mcp_schema.get("inputSchema", {}) if mcp_schema else {}
                skill_desc = getattr(skill, "description", "") or ""
                skill_name = getattr(skill, "name", skill_id) or skill_id
                target[key] = CapabilityItem(
                    name=key,
                    description=f"[Skill] {skill_desc or skill_name}",
                    source="skill",
                    source_id=skill_id,
                    parameters=params,
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
