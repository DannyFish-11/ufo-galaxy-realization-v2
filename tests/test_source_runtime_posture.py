#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from core.source_runtime_posture import (
    SourceRuntimePosture,
    build_source_runtime_posture_snapshot,
    record_source_runtime_posture,
    reset_source_runtime_posture_runtime,
    resolve_source_runtime_posture,
)


def setup_function() -> None:
    reset_source_runtime_posture_runtime()


def teardown_function() -> None:
    reset_source_runtime_posture_runtime()


def test_resolve_defaults_to_control_only() -> None:
    assert resolve_source_runtime_posture(None) == SourceRuntimePosture.CONTROL_ONLY


def test_resolve_join_runtime_hint() -> None:
    assert resolve_source_runtime_posture("join_runtime") == SourceRuntimePosture.JOIN_RUNTIME


def test_record_snapshot_counts() -> None:
    record_source_runtime_posture(
        task_id="task-control",
        source_device_id="phone_01",
        posture=SourceRuntimePosture.CONTROL_ONLY,
        reason="test",
    )
    record_source_runtime_posture(
        task_id="task-join",
        source_device_id="phone_02",
        posture=SourceRuntimePosture.JOIN_RUNTIME,
        reason="test",
    )

    snapshot = build_source_runtime_posture_snapshot()
    assert snapshot.control_only_count == 1
    assert snapshot.join_runtime_count == 1
    assert snapshot.total_records == 2


def test_snapshot_to_dict_contains_authority() -> None:
    snapshot = build_source_runtime_posture_snapshot()
    payload = snapshot.to_dict()
    assert "authority" in payload
    assert "recent_records" in payload
