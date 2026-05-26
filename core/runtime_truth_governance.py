"""Shared truth-grade and durable-state helpers for governed runtime surfaces."""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Dict, Optional

TRUTH_GRADE_DURABLE: str = "durable_truth"
TRUTH_GRADE_RECOVERABLE: str = "recoverable_truth"
TRUTH_GRADE_REVALIDATED: str = "revalidated_after_recovery_truth"
TRUTH_GRADE_RUNTIME_ONLY: str = "runtime_only_truth"
TRUTH_GRADE_PROJECTION: str = "outward_projection_truth"

RECOVERY_STATUS_LIVE: str = "live"
RECOVERY_STATUS_RECOVERED_UNREVALIDATED: str = "recovered_unrevalidated"
RECOVERY_STATUS_REVALIDATED: str = "revalidated_live"
RECOVERY_STATUS_DEGRADED: str = "degraded_projection"


def build_truth_governance(
    truth_grade: str,
    *,
    source: str,
    recovery_status: str = RECOVERY_STATUS_LIVE,
    revalidation_required: bool = False,
    degraded: bool = False,
    field_truth_grades: Optional[Dict[str, str]] = None,
    notes: Optional[list[str]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "truth_grade": truth_grade,
        "source": source,
        "recovery_status": recovery_status,
        "revalidation_required": bool(revalidation_required),
        "degraded": bool(degraded),
        "field_truth_grades": dict(field_truth_grades or {}),
        "notes": list(notes or []),
    }
    if extra:
        payload.update(dict(extra))
    return payload


def write_json_atomically(path: str, payload: Dict[str, Any]) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".runtime_truth_", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def load_json_payload(path: str) -> Dict[str, Any]:
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}
