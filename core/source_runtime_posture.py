#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/source_runtime_posture.py
================================

Dedicated authority for source-device runtime participation posture.

This module keeps ``control_only`` / ``join_runtime`` semantics separate from:

* ``entry_mode`` — execution path selection (local / cross_device / hybrid)
* ``cross_device_enabled`` — global feature gate

It provides a small canonical runtime that records the posture selected for the
originating device so formation, projection, and operator surfaces can expose
that semantic without overloading existing fields.
"""

from __future__ import annotations

import dataclasses
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

__all__ = [
    "SOURCE_RUNTIME_POSTURE_AUTHORITY",
    "SOURCE_RUNTIME_POSTURE_LAYER_POSITION",
    "SOURCE_RUNTIME_POSTURE_NO_ENTRYMODE_OVERLOAD_POLICY",
    "SOURCE_RUNTIME_POSTURE_NO_SWITCH_OVERLOAD_POLICY",
    "SourceRuntimePosture",
    "SourceRuntimePostureRecord",
    "SourceRuntimePostureSnapshot",
    "resolve_source_runtime_posture",
    "record_source_runtime_posture",
    "build_source_runtime_posture_snapshot",
    "get_source_runtime_posture_runtime",
    "reset_source_runtime_posture_runtime",
]

SOURCE_RUNTIME_POSTURE_AUTHORITY: str = (
    "SOURCE_RUNTIME_POSTURE::AUTHORITY_V1: "
    "Canonical participation-posture authority for the originating device. "
    "Separates control-only vs join-runtime semantics from execution-path routing."
)

SOURCE_RUNTIME_POSTURE_LAYER_POSITION: int = 9

SOURCE_RUNTIME_POSTURE_NO_ENTRYMODE_OVERLOAD_POLICY: str = (
    "SOURCE_RUNTIME_POSTURE::NO_ENTRYMODE_OVERLOAD_POLICY_V1: "
    "entry_mode remains execution-path selection only and must not encode "
    "source-device participation posture."
)

SOURCE_RUNTIME_POSTURE_NO_SWITCH_OVERLOAD_POLICY: str = (
    "SOURCE_RUNTIME_POSTURE::NO_SWITCH_OVERLOAD_POLICY_V1: "
    "cross_device_enabled remains a global gate only and must not encode "
    "control-only vs join-runtime source-device posture."
)


class SourceRuntimePosture(str, Enum):
    CONTROL_ONLY = "control_only"
    JOIN_RUNTIME = "join_runtime"


@dataclasses.dataclass
class SourceRuntimePostureRecord:
    record_id: str = dataclasses.field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str = ""
    trace_id: Optional[str] = None
    source_device_id: str = ""
    posture: SourceRuntimePosture = SourceRuntimePosture.CONTROL_ONLY
    target_device_ids: List[str] = dataclasses.field(default_factory=list)
    entry_mode: str = ""
    reason: str = ""
    timestamp: float = dataclasses.field(default_factory=time.time)
    extra: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "source_device_id": self.source_device_id,
            "posture": self.posture.value,
            "target_device_ids": list(self.target_device_ids),
            "entry_mode": self.entry_mode,
            "reason": self.reason,
            "timestamp": self.timestamp,
            "extra": dict(self.extra),
        }


@dataclasses.dataclass
class SourceRuntimePostureSnapshot:
    snapshot_id: str = dataclasses.field(default_factory=lambda: str(uuid.uuid4()))
    total_records: int = 0
    control_only_count: int = 0
    join_runtime_count: int = 0
    recent_records: List[SourceRuntimePostureRecord] = dataclasses.field(default_factory=list)
    timestamp: float = dataclasses.field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "total_records": self.total_records,
            "control_only_count": self.control_only_count,
            "join_runtime_count": self.join_runtime_count,
            "recent_records": [record.to_dict() for record in self.recent_records],
            "timestamp": self.timestamp,
            "authority": SOURCE_RUNTIME_POSTURE_AUTHORITY,
        }


def resolve_source_runtime_posture(
    posture_hint: Optional[str] = None,
) -> SourceRuntimePosture:
    raw = str(posture_hint or "").strip().lower()
    if raw == SourceRuntimePosture.JOIN_RUNTIME.value:
        return SourceRuntimePosture.JOIN_RUNTIME
    return SourceRuntimePosture.CONTROL_ONLY


class SourceRuntimePostureRuntime:
    def __init__(self, max_records: int = 128) -> None:
        self._max_records = max_records
        self._records: List[SourceRuntimePostureRecord] = []

    def record(self, record: SourceRuntimePostureRecord) -> SourceRuntimePostureRecord:
        self._records.append(record)
        if len(self._records) > self._max_records:
            self._records = self._records[-self._max_records :]
        return record

    def snapshot(self, max_recent: int = 20) -> SourceRuntimePostureSnapshot:
        recent_records = list(self._records[-max_recent:])
        return SourceRuntimePostureSnapshot(
            total_records=len(self._records),
            control_only_count=sum(
                1 for record in self._records if record.posture == SourceRuntimePosture.CONTROL_ONLY
            ),
            join_runtime_count=sum(
                1 for record in self._records if record.posture == SourceRuntimePosture.JOIN_RUNTIME
            ),
            recent_records=recent_records,
        )


_RUNTIME: Optional[SourceRuntimePostureRuntime] = None


def get_source_runtime_posture_runtime() -> SourceRuntimePostureRuntime:
    global _RUNTIME
    if _RUNTIME is None:
        _RUNTIME = SourceRuntimePostureRuntime()
    return _RUNTIME


def reset_source_runtime_posture_runtime() -> None:
    global _RUNTIME
    _RUNTIME = None


def record_source_runtime_posture(
    *,
    task_id: str = "",
    trace_id: Optional[str] = None,
    source_device_id: str = "",
    posture: SourceRuntimePosture = SourceRuntimePosture.CONTROL_ONLY,
    target_device_ids: Optional[List[str]] = None,
    entry_mode: str = "",
    reason: str = "",
    extra: Optional[Dict[str, Any]] = None,
) -> SourceRuntimePostureRecord:
    record = SourceRuntimePostureRecord(
        task_id=task_id,
        trace_id=trace_id,
        source_device_id=source_device_id,
        posture=posture,
        target_device_ids=list(target_device_ids or []),
        entry_mode=entry_mode,
        reason=reason,
        extra=dict(extra or {}),
    )
    return get_source_runtime_posture_runtime().record(record)


def build_source_runtime_posture_snapshot(max_recent: int = 20) -> SourceRuntimePostureSnapshot:
    return get_source_runtime_posture_runtime().snapshot(max_recent=max_recent)
