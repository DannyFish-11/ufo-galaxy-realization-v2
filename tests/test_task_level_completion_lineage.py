#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch


def _task_id() -> str:
    return f"task-{uuid.uuid4().hex[:12]}"


def _event(
    *,
    task_id: str,
    device_id: str = "device-1",
    participant_id: str = "participant-1",
    session_epoch: int | None = 7,
    handoff_id: str = "handoff-1",
    idempotency_key: str = "",
    trace_id: str = "trace-1",
) -> Any:
    from core.unified_result_ingress import NormalizedResultEvent, ResultSourceChannel

    payload = {
        "task_id": task_id,
        "status": "completed",
        "result": "ok",
        "handoff_id": handoff_id,
        "participant_id": participant_id,
    }
    raw_message = dict(payload)
    raw_message["type"] = "goal_execution_result"
    return NormalizedResultEvent(
        task_id=task_id,
        device_id=device_id,
        participant_id=participant_id,
        raw_message_type="goal_execution_result",
        normalized_result_kind="goal_execution_result",
        normalized_status="completed",
        source_channel=ResultSourceChannel.CANONICAL_WS,
        payload=payload,
        trace_id=trace_id,
        raw_message=raw_message,
        session_epoch=session_epoch,
        idempotency_key=idempotency_key,
    )


def _make_ingress():
    from core.unified_result_ingress import UnifiedResultIngress

    ingress = UnifiedResultIngress()
    ingress._check_continuity_legality = lambda _e, mode: "allow"  # type: ignore[method-assign]
    ingress._run_truth_chain = lambda _e: True  # type: ignore[method-assign]
    ingress._sync_lifecycle = lambda _e: None  # type: ignore[method-assign]
    ingress._notify_completion = lambda _e: True  # type: ignore[method-assign]
    ingress._log_outcome = lambda _e, _o: None  # type: ignore[method-assign]
    return ingress


@contextmanager
def _mock_idempotency_store():
    seen: set[str] = set()

    def _check(key: str) -> bool:
        return key in seen

    def _record(key: str) -> bool:
        if key in seen:
            return False
        seen.add(key)
        return True

    with patch(
        "core.durable_result_idempotency.check_result_idempotency",
        side_effect=_check,
    ), patch(
        "core.durable_result_idempotency.record_result_idempotency",
        side_effect=_record,
    ):
        yield seen


def _registry_entry(epoch: int) -> Any:
    entry = MagicMock()
    entry.continuity_epoch = epoch
    return entry


def test_first_accepted_completion_records_lineage_evidence():
    ingress = _make_ingress()
    task_id = _task_id()

    with _mock_idempotency_store():
        outcome = ingress.process(_event(task_id=task_id))

    assert outcome.was_deduplicated is False
    assert outcome.completion_disposition == "first_accepted"
    assert outcome.joint_idempotency_evidence["joint_idempotency_decision"] == "first_accepted"
    assert outcome.completion_lineage["task_id"] == task_id
    assert outcome.completion_lineage["participant_id"] == "participant-1"
    assert outcome.completion_lineage["session_epoch"] == 7
    assert outcome.completion_lineage["completion_emission_id"] == "handoff-1"
    assert outcome.closure_evidence_ledger["first_accepted_completion"]["disposition"] == "first_accepted"
    assert (
        outcome.final_truth_provenance["accepted_event_identity"]["completion_emission_id"]
        == "handoff-1"
    )


def test_same_completion_resend_is_duplicate_ignored_with_distinct_evidence():
    ingress = _make_ingress()
    task_id = _task_id()
    event = _event(task_id=task_id)

    with _mock_idempotency_store():
        first = ingress.process(event)
        duplicate = ingress.process(event)

    assert first.completion_disposition == "first_accepted"
    assert duplicate.was_deduplicated is True
    assert duplicate.completion_disposition == "duplicate_ignored"
    assert (
        first.joint_idempotency_evidence["joint_idempotency_decision"]
        == "first_accepted"
    )
    assert (
        duplicate.joint_idempotency_evidence["joint_idempotency_decision"]
        == "duplicate_ignored"
    )
    assert duplicate.joint_idempotency_evidence["duplicate_reason"] == (
        "result_idempotency+completion_lineage"
    )
    assert ingress.get_last_closure_outcome()["completion_disposition"] == "duplicate_ignored"
    ledger = ingress.get_last_closure_outcome()["closure_evidence_ledger"]
    assert ledger["competing_summary"]["duplicate_ignored"] == 1
    provenance = ingress.get_last_closure_outcome()["final_truth_provenance"]
    assert provenance["accepted_event_identity"]["completion_emission_id"] == "handoff-1"
    assert provenance["competing_rejected_or_ignored_summary"]["duplicate_ignored"] == 1


def test_same_task_different_epoch_completion_is_stale_rejected():
    ingress = _make_ingress()
    task_id = _task_id()

    with _mock_idempotency_store(), patch(
        "core.attached_runtime_session_registry.lookup_session_by_device",
        return_value=_registry_entry(9),
    ):
        outcome = ingress.process(_event(task_id=task_id, session_epoch=8))

    assert outcome.stale_epoch_rejected is True
    assert outcome.completion_disposition == "stale_rejected"
    assert outcome.stale_classification == "epoch_mismatch"
    assert outcome.joint_idempotency_evidence["joint_idempotency_decision"] == "stale_rejected"
    assert outcome.closure_evidence_ledger["competing_summary"]["stale_rejected"] == 1
    assert (
        outcome.final_truth_provenance["competing_rejected_or_ignored_summary"]["stale_rejected"]
        == 1
    )


def test_reconnect_repeated_terminal_upload_is_caught_by_lineage_evidence():
    ingress = _make_ingress()
    task_id = _task_id()
    first = _event(task_id=task_id, idempotency_key="result-a", trace_id="trace-a")
    replay = _event(task_id=task_id, idempotency_key="result-b", trace_id="trace-b")

    with _mock_idempotency_store():
        first_outcome = ingress.process(first)
        replay_outcome = ingress.process(replay)

    assert first_outcome.completion_disposition == "first_accepted"
    assert replay_outcome.was_deduplicated is True
    assert replay_outcome.completion_disposition == "duplicate_ignored"
    assert replay_outcome.joint_idempotency_evidence["duplicate_reason"] == (
        "completion_lineage"
    )
    assert (
        replay_outcome.joint_idempotency_evidence["result_idempotency_key"]
        == "result-b"
    )


def test_final_truth_provenance_distinguishes_accepted_and_competing_events():
    ingress = _make_ingress()
    task_id = _task_id()
    accepted = _event(task_id=task_id, handoff_id="accepted-1")
    duplicate = _event(task_id=task_id, handoff_id="accepted-1")
    stale = _event(task_id=task_id, handoff_id="stale-1", session_epoch=3)

    with _mock_idempotency_store():
        first = ingress.process(accepted)
        dup = ingress.process(duplicate)
        with patch(
            "core.attached_runtime_session_registry.lookup_session_by_device",
            return_value=_registry_entry(9),
        ):
            stale_outcome = ingress.process(stale)

    assert first.completion_disposition == "first_accepted"
    assert dup.completion_disposition == "duplicate_ignored"
    assert stale_outcome.completion_disposition == "stale_rejected"
    summary = ingress.get_last_closure_outcome()
    assert summary["canonical_truth_completed"] is False
    assert summary["mature_closure_achieved"] is False
    provenance = summary["final_truth_provenance"]
    assert provenance["accepted_event_identity"]["completion_emission_id"] == "accepted-1"
    assert provenance["accepted_reason_basis"] != ""
    competing = provenance["competing_rejected_or_ignored_summary"]
    assert competing["duplicate_ignored"] >= 1
    assert competing["stale_rejected"] >= 1
    assert competing["superseded_by_newer_epoch_session"] >= 1
