"""
galaxy_gateway/capability_registry.py
======================================
Gateway Capability Registry — exec_mode-aware routing store
(Legacy Compatibility Module — PR-S7).

.. deprecated:: PR-S7
    This module (``galaxy_gateway.capability_registry``) is a **legacy
    compatibility surface** retained for backward compatibility only.

    The canonical capability registration and lookup path is::

        Writers → core.agent.capability_registry.CapabilityRegistry
        Readers → core.unified.capability_resolver.CapabilityResolver

    ``core.capability_bus.CapabilityBus`` remains a compatibility bridge that
    forwards registrations into the same canonical capability truth.

    :class:`GatewayCapabilityRegistry` is an in-gateway per-device capability
    schema store that was introduced before the canonical capability truth was
    fully consolidated.
    It is retained so existing DeviceRouter / capability_report pathways that
    read from it do not immediately break.  New capability registration must
    target ``CapabilityRegistry`` (directly or through approved canonical
    writer helpers / bridges).

    See ``core.orchestration_authority.legacy_paths`` for the registry entry
    (``galaxy_gateway.capability_registry.GatewayCapabilityRegistry``).

每台设备通过 ``capability_report`` 消息上报其动作 schema；本模块将这些
schema 持久化在内存中，供路由层（DeviceRouter）在选择目标设备时参考
``exec_mode``（local / remote / both）。
Legacy compat — authoritative capability truth lives in
CapabilityRegistry / CapabilityResolver; this module is only a compat facade.

数据结构
--------
CapabilitySchema
    action      : str   — 动作名称，如 "tap"、"screenshot"
    params      : dict  — 参数 JSON Schema（可选）
    returns     : dict  — 返回值描述（可选）
    version     : str   — 能力版本，如 "1.0"
    exec_mode   : ExecMode — 执行偏好（local/remote/both）
    tags        : list[str] — 自由标签，用于额外过滤
    device_id   : str   — 所属设备 ID
    registered_at: float — 注册时间戳（Unix）

ExecMode 语义
-------------
- ``local``  : 该能力只应在**本地**（设备自身）执行；路由器不应将其分配
               给远端（服务端）执行者。
- ``remote`` : 该能力只应在**远端**（服务器侧）执行。
- ``both``   : 本地和远端均可，路由器按负载/策略自行决定。
- （缺失）   : 向后兼容，等同于 ``both``。

公共 API
--------
GatewayCapabilityRegistry.get_instance() → GatewayCapabilityRegistry
    返回全局单例。（Legacy compat — use core.capability_bus.get_capability_bus()）

registry.upsert(device_id, action, schema_dict)
    插入或更新设备动作的能力 schema。

registry.query(action=None, exec_mode=None, device_id=None) → list[CapabilitySchema]
    按条件过滤查询，所有参数均为可选。

registry.get_by_device(device_id) → list[CapabilitySchema]
    返回指定设备的全部能力 schema。

registry.purge(device_id)
    清除指定设备的所有能力 schema（设备断开时调用）。

registry.stats() → dict
    返回计数器：registrations, hits, misses。

Author: Copilot
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from core.unified.gateway_capability_projection import (
    get_gateway_capabilities_for_device,
    list_gateway_capability_device_ids,
    normalize_gateway_exec_mode,
    purge_gateway_capabilities_for_device,
    query_gateway_capabilities,
)

logger = logging.getLogger("Galaxy.Gateway.CapabilityRegistry")

# ──────────────────────────────────────────────────────────────────────────────
# ExecMode 枚举
# ──────────────────────────────────────────────────────────────────────────────


class ExecMode(str, Enum):
    """执行模式偏好。"""

    LOCAL = "local"
    REMOTE = "remote"
    BOTH = "both"

    @classmethod
    def from_str(cls, value: Optional[str]) -> "ExecMode":
        """从字符串解析；缺失或非法值均退回 BOTH（向后兼容）。"""
        if not value:
            return cls.BOTH
        try:
            return cls(value.lower())
        except ValueError:
            logger.debug("Unknown exec_mode %r — treating as 'both'", value)
            return cls.BOTH


# ──────────────────────────────────────────────────────────────────────────────
# CapabilitySchema 数据模型
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class CapabilitySchema:
    """单条能力 schema 条目。"""

    device_id: str
    action: str
    params: Dict[str, Any] = field(default_factory=dict)
    returns: Dict[str, Any] = field(default_factory=dict)
    version: str = "1.0"
    exec_mode: ExecMode = ExecMode.BOTH
    tags: List[str] = field(default_factory=list)
    registered_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "action": self.action,
            "params": self.params,
            "returns": self.returns,
            "version": self.version,
            "exec_mode": self.exec_mode.value,
            "tags": self.tags,
            "registered_at": self.registered_at,
        }


# ──────────────────────────────────────────────────────────────────────────────
# GatewayCapabilityRegistry
# ──────────────────────────────────────────────────────────────────────────────


class GatewayCapabilityRegistry:
    """线程安全的 Gateway 能力注册表（内存存储） — Legacy compat store.

    .. deprecated:: PR-S7
        ``GatewayCapabilityRegistry`` is a **legacy compatibility capability
        store**.  It maintains an in-gateway per-device action-schema map that
        was introduced before capability truth was consolidated on the
        canonical registry / resolver path.

        Canonical replacement:
            Writers: :class:`core.agent.capability_registry.CapabilityRegistry`
            Readers: :class:`core.unified.capability_resolver.CapabilityResolver`

            ``core.capability_bus.CapabilityBus`` remains an approved compat
            bridge, not an independent authority.

        ``GatewayCapabilityRegistry`` is retained so existing DeviceRouter and
        capability-report pathways that currently read from it do not
        immediately break.  New capability registration / lookup must converge
        on the canonical registry / resolver path.
    """

    _instance: Optional["GatewayCapabilityRegistry"] = None
    _instance_lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        self._locally_registered_capability_names: set[str] = set()
        self._locally_registered_by_device: Dict[str, set[str]] = {}
        self._uses_global_projection = False
        self._lock = threading.Lock()

        # 计数器
        self._registration_count: int = 0
        self._hit_count: int = 0
        self._miss_count: int = 0
        # PR-S7: emit legacy guardrail — GatewayCapabilityRegistry is the legacy
        # compat in-gateway capability store.  Canonical capability registration
        # uses core.capability_bus.CapabilityBus.
        try:
            from core.orchestration_authority.legacy_paths import emit_legacy_guardrail

            emit_legacy_guardrail(
                caller="galaxy_gateway.capability_registry.GatewayCapabilityRegistry",
            )
        except Exception:
            pass

    @staticmethod
    def _canonical_capability_name(device_id: str, action: str) -> str:
        return f"gateway__{device_id}__{action}"

    def _record_managed_name(self, device_id: str, capability_name: str) -> None:
        with self._lock:
            self._locally_registered_capability_names.add(capability_name)
            if device_id not in self._locally_registered_by_device:
                self._locally_registered_by_device[device_id] = set()
            self._locally_registered_by_device[device_id].add(capability_name)

    def _drop_managed_device(self, device_id: str) -> List[str]:
        with self._lock:
            names = list(self._locally_registered_by_device.pop(device_id, set()))
            for name in names:
                self._locally_registered_capability_names.discard(name)
            return names

    def _filter_projection_schemas(self, schemas: List[Any]) -> List[Any]:
        if self._uses_global_projection:
            return list(schemas)
        with self._lock:
            managed_names = set(self._locally_registered_capability_names)
        return [schema for schema in schemas if getattr(schema, "canonical_name", "") in managed_names]

    # ── 单例 ──────────────────────────────────────────────────────────────────

    @classmethod
    def get_instance(cls) -> "GatewayCapabilityRegistry":
        """返回全局单例，线程安全。"""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
                    cls._instance._uses_global_projection = True
        return cls._instance

    # ── 写操作 ────────────────────────────────────────────────────────────────

    def upsert(
        self,
        device_id: str,
        action: str,
        schema_dict: Optional[Dict[str, Any]] = None,
    ) -> CapabilitySchema:
        """插入或更新设备动作的能力 schema。

        Parameters
        ----------
        device_id:
            设备唯一标识。
        action:
            动作名称（如 "tap"、"screenshot"）。
        schema_dict:
            可选的 schema 补充信息，可包含以下字段：
            ``params``, ``returns``, ``version``, ``exec_mode``, ``tags``。

        Returns
        -------
        CapabilitySchema
            插入/更新后的 schema 对象。
        """
        if schema_dict is None:
            schema_dict = {}

        exec_mode = ExecMode.from_str(schema_dict.get("exec_mode"))
        schema = CapabilitySchema(
            device_id=device_id,
            action=action,
            params=schema_dict.get("params") or {},
            returns=schema_dict.get("returns") or {},
            version=schema_dict.get("version") or "1.0",
            exec_mode=exec_mode,
            tags=list(schema_dict.get("tags") or []),
            registered_at=time.time(),
        )

        try:
            from core.unified.capability_contract import CapabilityContract, CapabilitySource
            from core.capability_runtime.capability_state import CapabilityAvailability
            from core.unified.capability_authority import CapabilityAuthority

            capability_name = self._canonical_capability_name(device_id, action)
            CapabilityAuthority.get_instance().upsert_contract(
                CapabilityContract(
                    name=capability_name,
                    description=f"[Gateway:{device_id}] Device capability: {action}",
                    source=CapabilitySource.GATEWAY,
                    source_id=device_id,
                    version=schema.version,
                    parameters=schema.params,
                    available=True,
                    tags=list(schema.tags),
                    metadata={
                        "device_id": device_id,
                        "action": action,
                        "returns": schema.returns,
                        "exec_mode": schema.exec_mode.value,
                        "registered_at": schema.registered_at,
                    },
                ),
                mutation_source="gateway_capability_registry.upsert",
                publication_source="gateway_capability_registry",
                lifecycle_event="capability_registered",
                sync_runtime_registry=False,
            )
            CapabilityAuthority.get_instance().update_runtime(
                capability_name,
                availability=CapabilityAvailability.AVAILABLE.value,
                device_bindings=[device_id],
                preferred_device_ids=[device_id],
                metadata={
                    "participant_kind": "gateway",
                    "exec_mode": schema.exec_mode.value,
                    "network_reachability": "reachable",
                },
                mutation_source="gateway_capability_registry.upsert",
                lifecycle_event="capability_runtime_registered",
            )
            self._record_managed_name(device_id, capability_name)
        except Exception as exc:
            logger.warning("capability_registry: canonical upsert failed: %s", exc)
            raise

        with self._lock:
            self._registration_count += 1

        logger.debug(
            "capability_registry: upsert device=%s action=%s exec_mode=%s",
            device_id,
            action,
            exec_mode.value,
        )
        return schema

    def purge(self, device_id: str) -> int:
        """清除指定设备的所有能力 schema（设备断开时调用）。

        Returns
        -------
        int
            被清除的条目数量。
        """
        removed_names = self._drop_managed_device(device_id)
        if self._uses_global_projection:
            count = purge_gateway_capabilities_for_device(device_id)
        else:
            count = 0
            try:
                from core.unified.capability_authority import CapabilityAuthority

                authority = CapabilityAuthority.get_instance()
                for name in removed_names:
                    if authority.remove(name, mutation_source="gateway_capability_registry.purge"):
                        count += 1
            except Exception as exc:
                logger.debug("capability_registry purge canonical sync failed: %s", exc)
        if count:
            logger.info(
                "capability_registry: purged %d capabilities for device %s",
                count,
                device_id,
            )
        return count

    # ── 读操作 ────────────────────────────────────────────────────────────────

    def query(
        self,
        action: Optional[str] = None,
        exec_mode: Optional[ExecMode] = None,
        device_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> List[CapabilitySchema]:
        """按条件过滤查询能力 schema。

        Parameters
        ----------
        action:
            精确匹配动作名称；``None`` 表示不过滤。
        exec_mode:
            过滤执行模式：
            - ``ExecMode.LOCAL``  → 仅返回 exec_mode=local 或 exec_mode=both
            - ``ExecMode.REMOTE`` → 仅返回 exec_mode=remote 或 exec_mode=both
            - ``ExecMode.BOTH``   → 不额外过滤（等同于 None）
            - ``None``            → 不额外过滤
        device_id:
            仅返回该设备的能力；``None`` 表示不过滤。
        tags:
            要求至少包含所有指定标签；``None`` 表示不过滤。

        Returns
        -------
        list[CapabilitySchema]
        """
        results = [
            CapabilitySchema(
                device_id=schema.device_id,
                action=schema.action,
                params=dict(schema.params),
                returns=dict(schema.returns),
                version=schema.version,
                exec_mode=ExecMode.from_str(schema.exec_mode),
                tags=list(schema.tags),
                registered_at=schema.registered_at,
            )
            for schema in self._filter_projection_schemas(
                query_gateway_capabilities(
                    action=action,
                    exec_mode=normalize_gateway_exec_mode(exec_mode) if exec_mode is not None else None,
                    device_id=device_id,
                    tags=tags,
                )
            )
        ]

        # 更新命中/未命中计数
        with self._lock:
            if results:
                self._hit_count += 1
            else:
                self._miss_count += 1

        return results

    def get_by_device(self, device_id: str) -> List[CapabilitySchema]:
        """返回指定设备的全部能力 schema。"""
        return [
            CapabilitySchema(
                device_id=schema.device_id,
                action=schema.action,
                params=dict(schema.params),
                returns=dict(schema.returns),
                version=schema.version,
                exec_mode=ExecMode.from_str(schema.exec_mode),
                tags=list(schema.tags),
                registered_at=schema.registered_at,
            )
            for schema in self._filter_projection_schemas(get_gateway_capabilities_for_device(device_id))
        ]

    def all_device_ids(self) -> List[str]:
        """返回注册表中所有设备 ID。"""
        if self._uses_global_projection:
            return list_gateway_capability_device_ids()
        return sorted({schema.device_id for schema in self._filter_projection_schemas(query_gateway_capabilities())})

    # ── 计量 ──────────────────────────────────────────────────────────────────

    def stats(self) -> Dict[str, int]:
        """返回注册/命中/未命中计数。"""
        schemas = self._filter_projection_schemas(query_gateway_capabilities())
        with self._lock:
            return {
                "registrations": self._registration_count,
                "hits": self._hit_count,
                "misses": self._miss_count,
                "devices": len({schema.device_id for schema in schemas}),
                "total_capabilities": len(schemas),
            }


# ── 模块级快捷入口 ─────────────────────────────────────────────────────────────


def get_gateway_capability_registry() -> GatewayCapabilityRegistry:
    """返回 GatewayCapabilityRegistry 全局单例（快捷函数）。"""
    return GatewayCapabilityRegistry.get_instance()
