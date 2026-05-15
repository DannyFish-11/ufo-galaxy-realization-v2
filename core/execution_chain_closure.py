"""core/execution_chain_closure.py
===================================
执行链路闭环追踪模块 — Execution Chain Closure Tracking

背景 (Background)
-----------------
Galaxy 系统存在两条核心执行链路：

1. **本地链（Local Chain）**：
   trigger → execution → result entering unified ingress → acceptance → final completion state

2. **跨设备链（Cross-Device Chain）**：
   central initiation → Android handling → delegated execution →
   result/truth uplink → central ingestion → closure acceptance

本模块提供两条链路共享的**验收闭环状态追踪**逻辑，解决以下问题：

- 本地执行结果曾不经过 UnifiedResultIngress，导致无法获得统一验收判定
- 跨设备执行结果曾直接调用 truth chain，绕过证据质量分级和验收判定
- 两条链路的失败/中断状态缺乏统一可见的终态
- 没有跨链路的统一闭环摘要视图

设计原则 (Design Principles)
-----------------------------
- **Additive only** — 不修改现有模块，仅提供新公共 API。
- **Non-raising** — 所有函数永不 raise；错误以明确的失败状态返回。
- **JSON-serialisable** — 所有 dataclass 暴露 ``to_dict()``。
- **Both chains** — 本模块必须同时服务本地链和跨设备链。

权威标记 (Authority Sentinels)
------------------------------
``EXECUTION_CHAIN_CLOSURE_AUTHORITY`` — 导入此常量以断言本模块是
执行链路闭环追踪的权威层。

公共 API (Public API)
---------------------
Sentinels::

    EXECUTION_CHAIN_CLOSURE_AUTHORITY
    EXECUTION_CHAIN_CLOSURE_CONTRACT_VERSION

Enums::

    ChainKind
    ClosureState

Dataclasses::

    ChainClosureRecord
    DualChainClosureSummary

Functions::

    record_local_chain_closure(task_id, ...)
    record_cross_device_chain_closure(task_id, ...)
    get_chain_closure_record(task_id)
    get_dual_chain_closure_summary()
    reset_closure_registry()
"""

from __future__ import annotations

import dataclasses
import logging
import threading
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.ExecutionChainClosure")

# ---------------------------------------------------------------------------
# 权威标记 & 契约版本
# ---------------------------------------------------------------------------

EXECUTION_CHAIN_CLOSURE_AUTHORITY: str = (
    "EXECUTION_CHAIN_CLOSURE_V1: core/execution_chain_closure.py 是执行链路闭环追踪的权威层。"
    "本地链和跨设备链的验收状态均通过 record_local_chain_closure() 和 "
    "record_cross_device_chain_closure() 写入，通过 get_chain_closure_record() 读取。"
)

EXECUTION_CHAIN_CLOSURE_CONTRACT_VERSION: str = "1.0.0"

# ---------------------------------------------------------------------------
# ChainKind — 链路类型
# ---------------------------------------------------------------------------


class ChainKind(str, Enum):
    """执行链路类型。"""

    LOCAL = "local"
    """本地链：trigger → execution → result ingress → acceptance → completion."""

    CROSS_DEVICE = "cross_device"
    """跨设备链：central initiation → Android execution → result uplink → acceptance."""


# ---------------------------------------------------------------------------
# ClosureState — 闭环状态
# ---------------------------------------------------------------------------


class ClosureState(str, Enum):
    """执行链路闭环状态。

    表示链路结果被 UnifiedResultIngress 处理后的验收状态。
    """

    PENDING = "pending"
    """尚未提交到 UnifiedResultIngress，或 ingress 尚未运行。"""

    ACCEPTED = "accepted"
    """结果已被 UnifiedResultIngress 完全接受（is_fully_closed=True，verdict=accept）。"""

    ACCEPTED_PROVISIONAL = "accepted_provisional"
    """结果已被接受但为临时状态（verdict=accept_provisional 或证据质量有限）。"""

    PARTIAL = "partial"
    """UnifiedResultIngress 部分处理（truth chain 不完整或证据门控未通过）。"""

    REJECTED = "rejected"
    """结果被 UnifiedResultIngress 拒绝（verdict=reject 或 quarantine）。"""

    INTERRUPTED = "interrupted"
    """执行链路中断（超时、取消、设备断联等）。"""

    FAILED = "failed"
    """执行失败（executor 返回失败状态）。"""

    ERROR = "error"
    """内部错误（ingress 抛出异常或内部状态异常）。"""

    UNKNOWN = "unknown"
    """未知状态（兜底值）。"""


# ---------------------------------------------------------------------------
# ChainClosureRecord — 单次闭环记录
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class ChainClosureRecord:
    """单次执行链路验收闭环记录。

    每次通过 record_local_chain_closure() 或 record_cross_device_chain_closure()
    提交均产生一条记录，并存入全局注册表。

    Attributes
    ----------
    record_id:
        自动生成的唯一 ID。
    task_id:
        执行任务的 ID。
    chain_kind:
        链路类型（LOCAL 或 CROSS_DEVICE）。
    closure_state:
        闭环状态（验收判定）。
    acceptance_verdict:
        来自 UnifiedResultIngress 的细粒度验收判定字符串。
    truth_chain_complete:
        truth chain 四步骤是否全部完成。
    is_fully_closed:
        UnifiedResultIngress 返回的 is_fully_closed 布尔值。
    normalized_status:
        规范化后的任务状态（completed / failed / cancelled / degraded）。
    device_id:
        目标设备 ID（跨设备链路专用）。
    executor_module:
        执行器模块路径（本地链路专用）。
    incomplete_reason:
        未完全闭环时的原因描述。
    extra:
        额外元数据。
    recorded_at:
        记录时间戳。
    """

    record_id: str = dataclasses.field(default_factory=lambda: uuid.uuid4().hex)
    task_id: str = ""
    chain_kind: ChainKind = ChainKind.LOCAL
    closure_state: ClosureState = ClosureState.PENDING
    acceptance_verdict: str = ""
    truth_chain_complete: bool = False
    is_fully_closed: bool = False
    normalized_status: str = ""
    device_id: str = ""
    executor_module: str = ""
    incomplete_reason: str = ""
    extra: Dict[str, Any] = dataclasses.field(default_factory=dict)
    recorded_at: float = dataclasses.field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "record_id": self.record_id,
            "task_id": self.task_id,
            "chain_kind": self.chain_kind.value,
            "closure_state": self.closure_state.value,
            "acceptance_verdict": self.acceptance_verdict,
            "truth_chain_complete": self.truth_chain_complete,
            "is_fully_closed": self.is_fully_closed,
            "normalized_status": self.normalized_status,
            "device_id": self.device_id,
            "executor_module": self.executor_module,
            "incomplete_reason": self.incomplete_reason,
            "extra": self.extra,
            "recorded_at": self.recorded_at,
        }


# ---------------------------------------------------------------------------
# DualChainClosureSummary — 双链路闭环摘要
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class DualChainClosureSummary:
    """本地链 + 跨设备链的双链路闭环摘要视图。

    由 get_dual_chain_closure_summary() 构建，适合嵌入操作员面板、
    投影端点和审计日志。

    Attributes
    ----------
    total_records:
        注册表中的总记录数。
    local_total:
        本地链路记录总数。
    local_accepted:
        本地链路完全接受（ACCEPTED）的记录数。
    local_partial:
        本地链路部分闭环（PARTIAL）的记录数。
    local_failed:
        本地链路失败/中断/拒绝的记录数。
    cross_device_total:
        跨设备链路记录总数。
    cross_device_accepted:
        跨设备链路完全接受的记录数。
    cross_device_partial:
        跨设备链路部分闭环的记录数。
    cross_device_failed:
        跨设备链路失败/中断/拒绝的记录数。
    recent_records:
        最近的闭环记录（bounded）。
    summary_id:
        自动生成的摘要 ID。
    timestamp:
        摘要生成时间。
    """

    total_records: int = 0
    local_total: int = 0
    local_accepted: int = 0
    local_partial: int = 0
    local_failed: int = 0
    cross_device_total: int = 0
    cross_device_accepted: int = 0
    cross_device_partial: int = 0
    cross_device_failed: int = 0
    recent_records: List[ChainClosureRecord] = dataclasses.field(default_factory=list)
    summary_id: str = dataclasses.field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = dataclasses.field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "summary_id": self.summary_id,
            "timestamp": self.timestamp,
            "total_records": self.total_records,
            "local_total": self.local_total,
            "local_accepted": self.local_accepted,
            "local_partial": self.local_partial,
            "local_failed": self.local_failed,
            "cross_device_total": self.cross_device_total,
            "cross_device_accepted": self.cross_device_accepted,
            "cross_device_partial": self.cross_device_partial,
            "cross_device_failed": self.cross_device_failed,
            "recent_records": [r.to_dict() for r in self.recent_records],
            "contract_version": EXECUTION_CHAIN_CLOSURE_CONTRACT_VERSION,
        }


# ---------------------------------------------------------------------------
# 全局注册表
# ---------------------------------------------------------------------------

_MAX_REGISTRY_SIZE = 500
_registry: Dict[str, ChainClosureRecord] = {}
_registry_order: List[str] = []  # insertion-order list of task_ids
_registry_lock = threading.Lock()


def _compute_closure_state(
    ingress_outcome: Optional[Dict[str, Any]],
    normalized_status: str,
) -> ClosureState:
    """根据 UnifiedResultIngress 输出和任务状态推断 ClosureState。

    Parameters
    ----------
    ingress_outcome:
        来自 submit_local_result_to_ingress() 或 ingest_result_async() 的输出字典，
        或 None（表示 ingress 不可用）。
    normalized_status:
        规范化任务状态（completed / failed / cancelled / degraded）。

    Returns
    -------
    ClosureState
        推断出的闭环状态。
    """
    if ingress_outcome is None:
        # ingress 不可用
        s = (normalized_status or "").lower()
        if s in ("failed", "error"):
            return ClosureState.FAILED
        if s == "cancelled":
            return ClosureState.INTERRUPTED
        return ClosureState.PARTIAL

    verdict = str(ingress_outcome.get("evidence_acceptance_verdict") or "").lower()
    is_fully_closed = bool(ingress_outcome.get("is_fully_closed"))
    was_deduplicated = bool(ingress_outcome.get("was_deduplicated"))
    truth_chain_complete = bool(ingress_outcome.get("truth_chain_complete"))
    incomplete_reason = str(ingress_outcome.get("incomplete_reason") or "")

    if was_deduplicated:
        # 幂等性保护已处理，状态由原始记录决定
        return ClosureState.ACCEPTED

    if verdict in ("reject",):
        return ClosureState.REJECTED
    if verdict in ("quarantine",):
        return ClosureState.REJECTED

    if is_fully_closed:
        if verdict in ("accept_provisional", "accepted_provisional"):
            return ClosureState.ACCEPTED_PROVISIONAL
        return ClosureState.ACCEPTED

    # 未完全闭环
    s = (normalized_status or "").lower()
    if s in ("failed", "error"):
        return ClosureState.FAILED
    if s == "cancelled":
        return ClosureState.INTERRUPTED
    if incomplete_reason.startswith("continuity_rejected"):
        return ClosureState.REJECTED

    return ClosureState.PARTIAL


# ---------------------------------------------------------------------------
# 公共写入函数
# ---------------------------------------------------------------------------


def record_local_chain_closure(
    task_id: str,
    *,
    ingress_outcome: Optional[Dict[str, Any]] = None,
    normalized_status: str = "completed",
    executor_module: str = "",
    extra: Optional[Dict[str, Any]] = None,
) -> ChainClosureRecord:
    """记录本地链路的验收闭环状态。

    由 ``record_local_execution()``（core/local_execution_chain.py）在调用
    ``submit_local_result_to_ingress()`` 后调用，将本地链路验收结果写入注册表。

    Parameters
    ----------
    task_id:
        执行任务 ID。
    ingress_outcome:
        来自 ``submit_local_result_to_ingress()`` 的输出字典，或 None。
    normalized_status:
        规范化任务状态。
    executor_module:
        执行器模块路径（用于审计）。
    extra:
        额外元数据。

    Returns
    -------
    ChainClosureRecord
        新写入的闭环记录。
    """
    closure_state = _compute_closure_state(ingress_outcome, normalized_status)
    acceptance_verdict = ""
    truth_chain_complete = False
    is_fully_closed = False
    incomplete_reason = ""

    if ingress_outcome is not None:
        acceptance_verdict = str(ingress_outcome.get("evidence_acceptance_verdict") or "")
        truth_chain_complete = bool(ingress_outcome.get("truth_chain_complete"))
        is_fully_closed = bool(ingress_outcome.get("is_fully_closed"))
        incomplete_reason = str(ingress_outcome.get("incomplete_reason") or "")

    record = ChainClosureRecord(
        task_id=task_id,
        chain_kind=ChainKind.LOCAL,
        closure_state=closure_state,
        acceptance_verdict=acceptance_verdict,
        truth_chain_complete=truth_chain_complete,
        is_fully_closed=is_fully_closed,
        normalized_status=normalized_status,
        executor_module=executor_module,
        incomplete_reason=incomplete_reason,
        extra=dict(extra or {}),
    )

    _write_record(record)
    logger.debug(
        "execution_chain_closure: local chain recorded task_id=%s state=%s "
        "verdict=%s is_fully_closed=%s",
        task_id,
        closure_state.value,
        acceptance_verdict or "n/a",
        is_fully_closed,
    )
    return record


def record_cross_device_chain_closure(
    task_id: str,
    *,
    ingress_outcome: Optional[Dict[str, Any]] = None,
    normalized_status: str = "completed",
    device_id: str = "",
    extra: Optional[Dict[str, Any]] = None,
) -> ChainClosureRecord:
    """记录跨设备链路的验收闭环状态。

    由 ``handle_goal_execution_result()``（galaxy_gateway/android/handlers/goal_execution.py）
    在调用 ``ingest_result_async()`` 后调用，将跨设备链路验收结果写入注册表。

    Parameters
    ----------
    task_id:
        执行任务 ID。
    ingress_outcome:
        来自 ``ingest_result_async()`` 的输出字典，或 None（ingress 不可用时）。
    normalized_status:
        规范化任务状态。
    device_id:
        执行设备 ID。
    extra:
        额外元数据。

    Returns
    -------
    ChainClosureRecord
        新写入的闭环记录。
    """
    closure_state = _compute_closure_state(ingress_outcome, normalized_status)
    acceptance_verdict = ""
    truth_chain_complete = False
    is_fully_closed = False
    incomplete_reason = ""

    if ingress_outcome is not None:
        acceptance_verdict = str(ingress_outcome.get("evidence_acceptance_verdict") or "")
        truth_chain_complete = bool(ingress_outcome.get("truth_chain_complete"))
        is_fully_closed = bool(ingress_outcome.get("is_fully_closed"))
        incomplete_reason = str(ingress_outcome.get("incomplete_reason") or "")

    record = ChainClosureRecord(
        task_id=task_id,
        chain_kind=ChainKind.CROSS_DEVICE,
        closure_state=closure_state,
        acceptance_verdict=acceptance_verdict,
        truth_chain_complete=truth_chain_complete,
        is_fully_closed=is_fully_closed,
        normalized_status=normalized_status,
        device_id=device_id,
        incomplete_reason=incomplete_reason,
        extra=dict(extra or {}),
    )

    _write_record(record)
    logger.debug(
        "execution_chain_closure: cross-device chain recorded task_id=%s device_id=%s "
        "state=%s verdict=%s is_fully_closed=%s",
        task_id,
        device_id,
        closure_state.value,
        acceptance_verdict or "n/a",
        is_fully_closed,
    )
    return record


# ---------------------------------------------------------------------------
# 公共读取函数
# ---------------------------------------------------------------------------


def get_chain_closure_record(task_id: str) -> Optional[ChainClosureRecord]:
    """查询指定 task_id 最近的闭环记录。

    Parameters
    ----------
    task_id:
        执行任务 ID。

    Returns
    -------
    ChainClosureRecord or None
        最近写入的闭环记录，若 task_id 不存在则返回 None。
    """
    with _registry_lock:
        return _registry.get(task_id)


def get_dual_chain_closure_summary(
    max_recent: int = 20,
) -> DualChainClosureSummary:
    """构建双链路闭环摘要（本地链 + 跨设备链）。

    返回 :class:`DualChainClosureSummary`，包含两条链路的验收统计和最近记录。

    Parameters
    ----------
    max_recent:
        摘要中包含的最近记录数上限。

    Returns
    -------
    DualChainClosureSummary
        双链路闭环摘要。
    """
    _FAILED_STATES = {ClosureState.FAILED, ClosureState.INTERRUPTED, ClosureState.REJECTED, ClosureState.ERROR}

    with _registry_lock:
        records = list(_registry.values())

    local_records = [r for r in records if r.chain_kind == ChainKind.LOCAL]
    cross_records = [r for r in records if r.chain_kind == ChainKind.CROSS_DEVICE]

    local_accepted = sum(
        1 for r in local_records
        if r.closure_state in (ClosureState.ACCEPTED, ClosureState.ACCEPTED_PROVISIONAL)
    )
    local_partial = sum(1 for r in local_records if r.closure_state == ClosureState.PARTIAL)
    local_failed = sum(1 for r in local_records if r.closure_state in _FAILED_STATES)

    cross_accepted = sum(
        1 for r in cross_records
        if r.closure_state in (ClosureState.ACCEPTED, ClosureState.ACCEPTED_PROVISIONAL)
    )
    cross_partial = sum(1 for r in cross_records if r.closure_state == ClosureState.PARTIAL)
    cross_failed = sum(1 for r in cross_records if r.closure_state in _FAILED_STATES)

    # 最近记录：按 recorded_at 降序取前 max_recent 条
    all_sorted = sorted(records, key=lambda r: r.recorded_at, reverse=True)
    recent = all_sorted[:max_recent]

    return DualChainClosureSummary(
        total_records=len(records),
        local_total=len(local_records),
        local_accepted=local_accepted,
        local_partial=local_partial,
        local_failed=local_failed,
        cross_device_total=len(cross_records),
        cross_device_accepted=cross_accepted,
        cross_device_partial=cross_partial,
        cross_device_failed=cross_failed,
        recent_records=recent,
    )


def reset_closure_registry() -> None:
    """清空闭环注册表（仅用于测试）。"""
    global _registry, _registry_order
    with _registry_lock:
        _registry = {}
        _registry_order = []


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------


def _write_record(record: ChainClosureRecord) -> None:
    """向全局注册表写入一条闭环记录（线程安全，FIFO 有界）。"""
    with _registry_lock:
        _registry[record.task_id] = record
        if record.task_id not in _registry_order:
            _registry_order.append(record.task_id)
        # 超出上限时删除最早的记录
        while len(_registry_order) > _MAX_REGISTRY_SIZE:
            oldest = _registry_order.pop(0)
            _registry.pop(oldest, None)


# ---------------------------------------------------------------------------
# __all__
# ---------------------------------------------------------------------------

__all__ = [
    "EXECUTION_CHAIN_CLOSURE_AUTHORITY",
    "EXECUTION_CHAIN_CLOSURE_CONTRACT_VERSION",
    "ChainKind",
    "ClosureState",
    "ChainClosureRecord",
    "DualChainClosureSummary",
    "record_local_chain_closure",
    "record_cross_device_chain_closure",
    "get_chain_closure_record",
    "get_dual_chain_closure_summary",
    "reset_closure_registry",
]
