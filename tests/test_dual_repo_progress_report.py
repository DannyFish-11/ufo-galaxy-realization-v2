from __future__ import annotations

import json


def test_dual_repo_progress_report_has_authority_and_summary():
    from core.dual_repo_progress_report import (
        DUAL_REPO_PROGRESS_REPORT_AUTHORITY,
        build_dual_repo_progress_report,
    )

    payload = build_dual_repo_progress_report(force_rebuild=False)
    assert payload["authority"] == DUAL_REPO_PROGRESS_REPORT_AUTHORITY
    assert isinstance(payload.get("generated_at"), float)
    assert isinstance(payload.get("summary_zh"), str)
    assert payload["summary_zh"]


def test_dual_repo_progress_report_contains_completion_status_when_available():
    from core.dual_repo_progress_report import build_dual_repo_progress_report

    payload = build_dual_repo_progress_report(force_rebuild=False)
    if "system_completion_status" in payload:
        status = payload["system_completion_status"]
        assert isinstance(status, dict)
        assert "system_closure_pct" in status


def test_dual_repo_progress_report_is_json_serialisable():
    from core.dual_repo_progress_report import build_dual_repo_progress_report

    payload = build_dual_repo_progress_report(force_rebuild=False)
    dumped = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    assert isinstance(dumped, str)

