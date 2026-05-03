#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json

from core.system_completion_status import (
    SystemCompletionStatus,
    build_system_completion_status,
    get_system_completion_status,
    reset_system_completion_status,
)


def test_build_system_completion_status_returns_report():
    report = build_system_completion_status()
    assert isinstance(report, SystemCompletionStatus)
    assert report.system_kind == "dual_repo_distributed_agent_system"
    assert 0.0 <= report.architecture_completion_pct <= 100.0
    assert 0.0 <= report.system_closure_pct <= 100.0
    assert report.remaining_pct_to_full_closure == round(100.0 - report.system_closure_pct, 2)
    assert isinstance(report.remaining_to_100, list)
    assert isinstance(report.accepted_limitations, list)
    assert report.summary


def test_build_system_completion_status_exposes_real_status_misalignment():
    report = build_system_completion_status()
    if report.architecture_completion_pct >= 100.0 and not report.is_fully_closed:
        assert report.status_alignment["architecture_complete_but_system_not_closed"] is True
        assert report.remaining_to_100


def test_system_completion_status_to_json_roundtrip():
    report = build_system_completion_status()
    data = json.loads(report.to_json())
    assert data["report_id"] == report.report_id
    assert data["summary"] == report.summary
    assert "remaining_to_100" in data


def test_system_completion_status_singleton_reset():
    reset_system_completion_status()
    first = get_system_completion_status()
    second = get_system_completion_status()
    assert first is second

    reset_system_completion_status()
    third = get_system_completion_status()
    assert third is not first
