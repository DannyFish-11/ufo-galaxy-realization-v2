from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.integration._dual_runtime_cross_repo_harness import (
    DUAL_RUNTIME_EVIDENCE_ENV,
    DUAL_RUNTIME_PROTECTED_ENV,
    build_dual_runtime_cross_repo_evidence_report,
    build_dual_runtime_cross_repo_evidence_report_from_environment,
    load_evidence_or_skip,
)


def _base_messages() -> list[dict]:
    return [
        {"type": "device_register", "device_id": "android-1"},
        {"type": "capability_report", "device_id": "android-1"},
        {"type": "device_state_snapshot", "device_id": "android-1"},
        {"type": "device_execution_event", "device_id": "android-1", "payload": {"phase": "succeeded"}},
        {"type": "device_execution_event_ack", "device_id": "android-1"},
    ]


def test_load_evidence_or_skip_raises_in_protected_mode_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(DUAL_RUNTIME_EVIDENCE_ENV, raising=False)
    monkeypatch.setenv(DUAL_RUNTIME_PROTECTED_ENV, "1")
    with pytest.raises(AssertionError, match="DUAL_RUNTIME_CROSS_REPO_EVIDENCE_PATH"):
        load_evidence_or_skip()


def test_load_evidence_or_skip_skips_in_non_protected_mode_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(DUAL_RUNTIME_EVIDENCE_ENV, raising=False)
    monkeypatch.delenv(DUAL_RUNTIME_PROTECTED_ENV, raising=False)
    with pytest.raises(pytest.skip.Exception):
        load_evidence_or_skip()


def test_build_report_from_environment_not_run_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(DUAL_RUNTIME_EVIDENCE_ENV, raising=False)
    report = build_dual_runtime_cross_repo_evidence_report_from_environment()
    assert report["overall_state"] == "not_run"


def test_build_report_from_environment_failed_when_invalid_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bad_path = tmp_path / "bad_evidence.json"
    bad_path.write_text("{not-json", encoding="utf-8")
    monkeypatch.setenv(DUAL_RUNTIME_EVIDENCE_ENV, str(bad_path))
    report = build_dual_runtime_cross_repo_evidence_report_from_environment()
    assert report["overall_state"] == "failed"
    assert "Unable to parse" in report["reason"]


def test_build_report_marks_partially_run_when_reconnect_recovery_missing() -> None:
    report = build_dual_runtime_cross_repo_evidence_report(
        {
            "is_real_device_e2e_verified": True,
            "messages": _base_messages(),
        }
    )
    assert report["behavior_checks"]["replay_ordering"]["status"] == "evidenced"
    assert report["behavior_checks"]["closure_completeness"]["status"] == "evidenced"
    assert report["behavior_checks"]["reconnect_continuity"]["status"] == "not_evidenced"
    assert report["behavior_checks"]["recovery_behavior"]["status"] == "not_evidenced"
    assert report["overall_state"] == "partially_run"


def test_build_report_marks_evidenced_when_all_behaviors_present() -> None:
    messages = _base_messages()
    messages.extend(
        [
            {"type": "heartbeat", "device_id": "android-1", "correlation_id": "seq-1"},
            {"type": "recovery_state", "device_id": "android-1", "payload": {"recovery_step": "resume"}},
        ]
    )
    report = build_dual_runtime_cross_repo_evidence_report(
        {
            "is_real_device_e2e_verified": True,
            "messages": messages,
            "recovery_state": {"status": "resumed"},
            "reconnect_continuity_verified": True,
            "recovery_behavior_verified": True,
            "closure_complete": True,
        }
    )
    assert report["overall_state"] == "evidenced"


def test_build_report_from_environment_includes_evidence_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(
        json.dumps({"is_real_device_e2e_verified": True, "messages": _base_messages()}),
        encoding="utf-8",
    )
    monkeypatch.setenv(DUAL_RUNTIME_EVIDENCE_ENV, str(evidence_path))
    report = build_dual_runtime_cross_repo_evidence_report_from_environment()
    assert report["overall_state"] == "partially_run"
    assert report["evidence_path"] == str(evidence_path)
