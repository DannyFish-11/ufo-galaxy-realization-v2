"""core/android_acceptance_evidence_store.py
===========================================
V2 侧 Android DEVICE_ACCEPTANCE_REPORT 证据摄取存储。

该模块提供一个进程内、线程安全的轻量存储，用于承接 Android 上行的
``DEVICE_ACCEPTANCE_REPORT``，并将 acceptance_tag 映射为 V2 侧可消费的
evidence/trust 提示（如映射 proof_class）。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class AndroidAcceptanceEvidenceRecord:
    """单条 Android 接受证据记录。"""

    device_id: str
    acceptance_tag: str = ""
    acceptance_class: str = "unknown"
    mapped_android_proof_class: str = ""
    mapped_evidence_trust_level: str = "provisional"
    mapping_reason: str = ""
    dimension_states: Dict[str, Any] = field(default_factory=dict)
    missing_dimensions: List[str] = field(default_factory=list)
    snapshot_id: str = ""
    st_gap_reason: str = ""
    message_id: str = ""
    ingested_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "acceptance_tag": self.acceptance_tag,
            "acceptance_class": self.acceptance_class,
            "mapped_android_proof_class": self.mapped_android_proof_class,
            "mapped_evidence_trust_level": self.mapped_evidence_trust_level,
            "mapping_reason": self.mapping_reason,
            "dimension_states": dict(self.dimension_states),
            "missing_dimensions": list(self.missing_dimensions),
            "snapshot_id": self.snapshot_id,
            "st_gap_reason": self.st_gap_reason,
            "message_id": self.message_id,
            "ingested_at": self.ingested_at,
        }


_lock = threading.Lock()
_latest_by_device: Dict[str, AndroidAcceptanceEvidenceRecord] = {}


def ingest_device_acceptance_report(
    *,
    device_id: str,
    payload: Dict[str, Any],
    message_id: str = "",
) -> AndroidAcceptanceEvidenceRecord:
    """摄取 DEVICE_ACCEPTANCE_REPORT 并覆盖该设备最新记录。"""
    normalized_payload = payload if isinstance(payload, dict) else {}
    acceptance_tag = _coerce_text(
        normalized_payload.get("acceptance_tag")
        or normalized_payload.get("acceptanceTag")
    )
    dimension_states = _coerce_dict(
        normalized_payload.get("dimension_states")
        or normalized_payload.get("dimensionStates")
    )
    missing_dimensions = _coerce_str_list(
        normalized_payload.get("missing_dimensions")
        or normalized_payload.get("missingDimensions")
    )
    snapshot_id = _coerce_text(
        normalized_payload.get("snapshot_id")
        or normalized_payload.get("snapshotId")
        or normalized_payload.get("evidence_snapshot_id")
        or normalized_payload.get("evidenceSnapshotId")
    )
    st_gap_reason = _coerce_text(
        normalized_payload.get("st_gap_reason")
        or normalized_payload.get("stGapReason")
    )
    mapped = _map_acceptance_tag(acceptance_tag)
    record = AndroidAcceptanceEvidenceRecord(
        device_id=str(device_id or ""),
        acceptance_tag=acceptance_tag,
        acceptance_class=mapped["acceptance_class"],
        mapped_android_proof_class=mapped["mapped_android_proof_class"],
        mapped_evidence_trust_level=mapped["mapped_evidence_trust_level"],
        mapping_reason=mapped["mapping_reason"],
        dimension_states=dimension_states,
        missing_dimensions=missing_dimensions,
        snapshot_id=snapshot_id,
        st_gap_reason=st_gap_reason,
        message_id=_coerce_text(message_id),
        ingested_at=time.time(),
    )
    with _lock:
        _latest_by_device[record.device_id] = record
    return record


def get_latest_device_acceptance_evidence_dict(device_id: str) -> Dict[str, Any]:
    """读取设备最新 acceptance 证据（dict 形式）。"""
    with _lock:
        record = _latest_by_device.get(str(device_id or ""))
    return record.to_dict() if record is not None else {}


def list_device_acceptance_evidence_dicts() -> List[Dict[str, Any]]:
    """返回当前所有设备的 acceptance 证据快照（按摄取时间升序）。"""
    with _lock:
        records = list(_latest_by_device.values())
    records.sort(key=lambda item: item.ingested_at)
    return [record.to_dict() for record in records]


def clear_device_acceptance_evidence(device_id: Optional[str] = None) -> None:
    """清理 acceptance 证据（测试辅助）。"""
    with _lock:
        if device_id is None:
            _latest_by_device.clear()
            return
        _latest_by_device.pop(str(device_id or ""), None)


def _map_acceptance_tag(acceptance_tag: str) -> Dict[str, str]:
    tag = (acceptance_tag or "").strip().lower()
    if tag in {"device_accepted_for_graduation", "accepted_for_graduation"}:
        return {
            "acceptance_class": "accepted",
            "mapped_android_proof_class": "confirmed_strong",
            "mapped_evidence_trust_level": "trusted",
            "mapping_reason": "acceptance_tag indicates graduation-level acceptance",
        }
    if "rejected" in tag or tag in {"reject", "rejected"}:
        return {
            "acceptance_class": "rejected",
            "mapped_android_proof_class": "degraded_conflicting",
            "mapped_evidence_trust_level": "quarantine",
            "mapping_reason": "acceptance_tag indicates rejection/conflict",
        }
    if "unknown" in tag:
        return {
            "acceptance_class": "unknown",
            "mapped_android_proof_class": "degraded_partial",
            "mapped_evidence_trust_level": "provisional",
            "mapping_reason": "acceptance_tag indicates unknown acceptance state",
        }
    return {
        "acceptance_class": "unknown",
        "mapped_android_proof_class": "",
        "mapped_evidence_trust_level": "provisional",
        "mapping_reason": "acceptance_tag unavailable or unmapped",
    }


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _coerce_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _coerce_str_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [
            str(item).strip()
            for item in value
            if item is not None and str(item).strip()
        ]
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    return []


__all__ = [
    "AndroidAcceptanceEvidenceRecord",
    "ingest_device_acceptance_report",
    "get_latest_device_acceptance_evidence_dict",
    "list_device_acceptance_evidence_dicts",
    "clear_device_acceptance_evidence",
]
