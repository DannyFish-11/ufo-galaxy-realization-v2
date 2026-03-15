"""
galaxy_gateway/capability_registry.py
======================================
Gateway Capability Registry — exec_mode-aware routing store.

每台设备通过 ``capability_report`` 消息上报其动作 schema；本模块将这些
schema 持久化在内存中，供路由层（DeviceRouter）在选择目标设备时参考
``exec_mode``（local / remote / both）。

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
    返回全局单例。

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
    """线程安全的 Gateway 能力注册表（内存存储）。"""

    _instance: Optional["GatewayCapabilityRegistry"] = None
    _instance_lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        # 存储结构: { device_id -> { action -> CapabilitySchema } }
        self._store: Dict[str, Dict[str, CapabilitySchema]] = {}
        self._lock = threading.Lock()

        # 计数器
        self._registration_count: int = 0
        self._hit_count: int = 0
        self._miss_count: int = 0

    # ── 单例 ──────────────────────────────────────────────────────────────────

    @classmethod
    def get_instance(cls) -> "GatewayCapabilityRegistry":
        """返回全局单例，线程安全。"""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
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

        with self._lock:
            if device_id not in self._store:
                self._store[device_id] = {}
            self._store[device_id][action] = schema
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
        with self._lock:
            removed = self._store.pop(device_id, {})

        count = len(removed)
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
        with self._lock:
            if device_id is not None:
                device_schemas = self._store.get(device_id, {}).values()
                candidates = list(device_schemas)
            else:
                candidates = [
                    schema
                    for device_schemas in self._store.values()
                    for schema in device_schemas.values()
                ]

        results = []
        for schema in candidates:
            # action 过滤
            if action is not None and schema.action != action:
                continue

            # exec_mode 过滤
            if exec_mode is not None and exec_mode != ExecMode.BOTH:
                # local 请求：接受 local 或 both
                if exec_mode == ExecMode.LOCAL and schema.exec_mode == ExecMode.REMOTE:
                    continue
                # remote 请求：接受 remote 或 both
                if exec_mode == ExecMode.REMOTE and schema.exec_mode == ExecMode.LOCAL:
                    continue

            # tags 过滤
            if tags:
                if not all(t in schema.tags for t in tags):
                    continue

            results.append(schema)

        # 更新命中/未命中计数
        with self._lock:
            if results:
                self._hit_count += 1
            else:
                self._miss_count += 1

        return results

    def get_by_device(self, device_id: str) -> List[CapabilitySchema]:
        """返回指定设备的全部能力 schema。"""
        with self._lock:
            return list(self._store.get(device_id, {}).values())

    def all_device_ids(self) -> List[str]:
        """返回注册表中所有设备 ID。"""
        with self._lock:
            return list(self._store.keys())

    # ── 计量 ──────────────────────────────────────────────────────────────────

    def stats(self) -> Dict[str, int]:
        """返回注册/命中/未命中计数。"""
        with self._lock:
            return {
                "registrations": self._registration_count,
                "hits": self._hit_count,
                "misses": self._miss_count,
                "devices": len(self._store),
                "total_capabilities": sum(len(v) for v in self._store.values()),
            }


# ── 模块级快捷入口 ─────────────────────────────────────────────────────────────

def get_gateway_capability_registry() -> GatewayCapabilityRegistry:
    """返回 GatewayCapabilityRegistry 全局单例（快捷函数）。"""
    return GatewayCapabilityRegistry.get_instance()
