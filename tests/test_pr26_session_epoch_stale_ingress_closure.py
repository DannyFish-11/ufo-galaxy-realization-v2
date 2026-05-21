#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr26_session_epoch_stale_ingress_closure.py
=======================================================
PR-26: Closes the ``session_epoch -> is_stale -> canonical ingress decision``
loop in :class:`~core.unified_result_ingress.UnifiedResultIngress`.

Scenarios covered
-----------------
Group A — NormalizedResultEvent epoch / stale fields
  A01  NormalizedResultEvent accepts session_epoch
  A02  NormalizedResultEvent accepts is_stale=True
  A03  NormalizedResultEvent accepts stale_reason
  A04  session_epoch defaults to None
  A05  is_stale defaults to False

Group B — UnifiedResultIngressOutcome stale fields
  B01  UnifiedResultIngressOutcome has stale_epoch_rejected field (default False)
  B02  UnifiedResultIngressOutcome has stale_classification field (default "")
  B03  UnifiedResultIngressOutcome has stale_epoch_evidence field (default {})

Group C — Explicit is_stale flag blocks canonical closure
  C01  Event with is_stale=True is blocked (stale_epoch_rejected=True)
  C02  Blocked stale result has stale_classification="explicit_stale"
  C03  Blocked stale result has non-empty stale_epoch_evidence
  C04  Blocked stale result does NOT reach truth-chain step (is_fully_closed=False)
  C05  stale_reason propagated into evidence dict

Group D — Epoch mismatch detection via registry
  D01  Event with matching epoch (same as stored) passes through normally
  D02  Event with epoch mismatch is blocked as "epoch_mismatch"
  D03  REPLAY channel with epoch mismatch is classified as "replay_epoch_mismatch"
  D04  Event with no session_epoch (None) is NOT classified as stale
  D05  Event with session_epoch but no registry entry is NOT classified as stale
  D06  stale_epoch_evidence contains stored_epoch and presented_epoch on mismatch

Group E — Stale result evidence / diagnostics
  E01  stale_epoch_evidence contains task_id, device_id, source_channel
  E02  stale_epoch_evidence contains stale_trigger
  E03  stale_epoch_rejected=True implies incomplete_reason starts with "stale_epoch_rejected"
  E04  stale_epoch_rejected result NOT recorded in durable idempotency store

Group F — Current epoch normal result not mis-flagged
  F01  Current epoch result passes through (stale_epoch_rejected=False)
  F02  Current epoch result can reach is_fully_closed=True
  F03  Current epoch result on REPLAY channel with matching epoch not stale

Group G — Late completion / reconnect scenarios
  G01  Old session epoch late completion is classified as stale and blocked
  G02  Reconnect-late result (explicit is_stale) blocked from closure
  G03  Replay-derived stale result classified and blocked
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest


# ===========================================================================
# Helpers
# ===========================================================================


def _make_task_id() -> str:
    return f"task-{uuid.uuid4().hex[:12]}"


def _make_event(
    task_id: Optional[str] = None,
    status: str = "completed",
    kind: str = "goal_execution_result",
    channel: str = "canonical_ws",
    device_id: str = "test-device",
    session_epoch: Optional[int] = None,
    is_stale: bool = False,
    stale_reason: str = "",
) -> Any:
    from core.unified_result_ingress import NormalizedResultEvent, ResultSourceChannel

    tid = task_id or _make_task_id()
    return NormalizedResultEvent(
        task_id=tid,
        device_id=device_id,
        raw_message_type=kind,
        normalized_result_kind=kind,
        normalized_status=status,
        source_channel=ResultSourceChannel(channel),
        payload={"task_id": tid, "status": status, "result": "ok"},
        trace_id="trace-test",
        raw_message={"task_id": tid, "status": status, "type": kind},
        session_epoch=session_epoch,
        is_stale=is_stale,
        stale_reason=stale_reason,
    )


def _make_ingress_with_stubs(
    *,
    patch_continuity: bool = True,
    patch_idempotency: bool = True,
    patch_truth_chain: bool = True,
    patch_completion: bool = True,
) -> Any:
    """Return a :class:`UnifiedResultIngress` with non-epoch steps stubbed out
    so tests can focus on the epoch stale gate in isolation."""
    from core.unified_result_ingress import UnifiedResultIngress

    ingress = UnifiedResultIngress()

    if patch_continuity:
        ingress._check_continuity_legality = lambda e, mode: "allow"  # type: ignore[method-assign]

    if patch_idempotency:
        ingress._check_idempotency = lambda e: False  # type: ignore[method-assign]
        ingress._record_idempotency = lambda e: None  # type: ignore[method-assign]

    if patch_truth_chain:
        ingress._run_truth_chain = lambda e: True  # type: ignore[method-assign]
        ingress._sync_lifecycle = lambda e: None  # type: ignore[method-assign]

    if patch_completion:
        ingress._notify_completion = lambda e: True  # type: ignore[method-assign]
        ingress._log_outcome = lambda e, o: None  # type: ignore[method-assign]

    return ingress


def _make_registry_entry(continuity_epoch: int) -> Any:
    """Return a minimal mock registry entry with the given epoch."""
    entry = MagicMock()
    entry.continuity_epoch = continuity_epoch
    return entry


# ===========================================================================
# Group A — NormalizedResultEvent epoch / stale fields
# ===========================================================================


class TestNormalizedResultEventEpochFields:

    def test_A01_session_epoch_accepted(self):
        evt = _make_event(session_epoch=5)
        assert evt.session_epoch == 5

    def test_A02_is_stale_accepted(self):
        evt = _make_event(is_stale=True)
        assert evt.is_stale is True

    def test_A03_stale_reason_accepted(self):
        evt = _make_event(is_stale=True, stale_reason="old_session_reconnect_late")
        assert evt.stale_reason == "old_session_reconnect_late"

    def test_A04_session_epoch_defaults_none(self):
        evt = _make_event()
        assert evt.session_epoch is None

    def test_A05_is_stale_defaults_false(self):
        evt = _make_event()
        assert evt.is_stale is False


# ===========================================================================
# Group B — UnifiedResultIngressOutcome stale fields
# ===========================================================================


class TestOutcomeStaleFields:

    def test_B01_stale_epoch_rejected_default_false(self):
        from core.unified_result_ingress import UnifiedResultIngressOutcome

        o = UnifiedResultIngressOutcome()
        assert o.stale_epoch_rejected is False

    def test_B02_stale_classification_default_empty(self):
        from core.unified_result_ingress import UnifiedResultIngressOutcome

        o = UnifiedResultIngressOutcome()
        assert o.stale_classification == ""

    def test_B03_stale_epoch_evidence_default_empty_dict(self):
        from core.unified_result_ingress import UnifiedResultIngressOutcome

        o = UnifiedResultIngressOutcome()
        assert o.stale_epoch_evidence == {}


# ===========================================================================
# Group C — Explicit is_stale flag blocks canonical closure
# ===========================================================================


class TestExplicitStaleFlag:

    def _ingress(self):
        return _make_ingress_with_stubs()

    def test_C01_is_stale_true_blocks_ingress(self):
        ingress = self._ingress()
        evt = _make_event(is_stale=True)
        outcome = ingress.process(evt)
        assert outcome.stale_epoch_rejected is True

    def test_C02_explicit_stale_classification(self):
        ingress = self._ingress()
        evt = _make_event(is_stale=True)
        outcome = ingress.process(evt)
        assert outcome.stale_classification == "explicit_stale"

    def test_C03_stale_epoch_evidence_non_empty(self):
        ingress = self._ingress()
        evt = _make_event(is_stale=True)
        outcome = ingress.process(evt)
        assert isinstance(outcome.stale_epoch_evidence, dict)
        assert len(outcome.stale_epoch_evidence) > 0

    def test_C04_stale_result_not_fully_closed(self):
        ingress = self._ingress()
        evt = _make_event(is_stale=True)
        outcome = ingress.process(evt)
        assert outcome.is_fully_closed is False

    def test_C05_stale_reason_in_evidence(self):
        ingress = self._ingress()
        evt = _make_event(is_stale=True, stale_reason="old_session_late_completion")
        outcome = ingress.process(evt)
        evidence = outcome.stale_epoch_evidence
        assert "old_session_late_completion" in evidence.get("stale_reason", "")


# ===========================================================================
# Group D — Epoch mismatch detection via registry
# ===========================================================================


class TestEpochMismatchViaRegistry:

    def _ingress(self):
        return _make_ingress_with_stubs()

    def test_D01_matching_epoch_passes_through(self):
        ingress = self._ingress()
        evt = _make_event(session_epoch=3, device_id="dev-match")
        registry_entry = _make_registry_entry(continuity_epoch=3)

        with patch(
            "core.unified_result_ingress.UnifiedResultIngress._check_stale_epoch",
            wraps=ingress._check_stale_epoch,
        ) as _wrapped:
            # Patch the registry lookup inside _check_stale_epoch
            with patch(
                "core.attached_runtime_session_registry.lookup_session_by_device",
                return_value=registry_entry,
            ):
                outcome = ingress.process(evt)

        assert outcome.stale_epoch_rejected is False

    def test_D02_epoch_mismatch_blocked(self):
        ingress = self._ingress()
        evt = _make_event(session_epoch=1, device_id="dev-old")
        registry_entry = _make_registry_entry(continuity_epoch=3)

        with patch(
            "core.attached_runtime_session_registry.lookup_session_by_device",
            return_value=registry_entry,
        ):
            outcome = ingress.process(evt)

        assert outcome.stale_epoch_rejected is True
        assert outcome.stale_classification == "epoch_mismatch"

    def test_D03_replay_epoch_mismatch_classification(self):
        ingress = self._ingress()
        evt = _make_event(session_epoch=1, device_id="dev-old", channel="replay")
        registry_entry = _make_registry_entry(continuity_epoch=3)

        with patch(
            "core.attached_runtime_session_registry.lookup_session_by_device",
            return_value=registry_entry,
        ):
            outcome = ingress.process(evt)

        assert outcome.stale_epoch_rejected is True
        assert outcome.stale_classification == "replay_epoch_mismatch"

    def test_D04_no_session_epoch_not_stale(self):
        ingress = self._ingress()
        # No session_epoch → skip epoch check
        evt = _make_event(session_epoch=None, device_id="dev-no-epoch")
        registry_entry = _make_registry_entry(continuity_epoch=5)

        with patch(
            "core.attached_runtime_session_registry.lookup_session_by_device",
            return_value=registry_entry,
        ):
            outcome = ingress.process(evt)

        assert outcome.stale_epoch_rejected is False

    def test_D05_no_registry_entry_not_stale(self):
        ingress = self._ingress()
        evt = _make_event(session_epoch=2, device_id="dev-unknown")

        with patch(
            "core.attached_runtime_session_registry.lookup_session_by_device",
            return_value=None,
        ):
            outcome = ingress.process(evt)

        assert outcome.stale_epoch_rejected is False

    def test_D06_evidence_contains_epoch_details_on_mismatch(self):
        ingress = self._ingress()
        evt = _make_event(session_epoch=1, device_id="dev-mismatch")
        registry_entry = _make_registry_entry(continuity_epoch=5)

        with patch(
            "core.attached_runtime_session_registry.lookup_session_by_device",
            return_value=registry_entry,
        ):
            outcome = ingress.process(evt)

        evidence = outcome.stale_epoch_evidence
        assert evidence.get("stored_epoch") == 5
        assert evidence.get("presented_epoch") == 1


# ===========================================================================
# Group E — Stale result evidence / diagnostics
# ===========================================================================


class TestStaleEvidenceDiagnostics:

    def _ingress(self):
        return _make_ingress_with_stubs()

    def test_E01_evidence_contains_base_fields(self):
        ingress = self._ingress()
        evt = _make_event(is_stale=True, task_id="task-e01", device_id="dev-e01")
        outcome = ingress.process(evt)
        ev = outcome.stale_epoch_evidence
        assert ev.get("task_id") == "task-e01"
        assert ev.get("device_id") == "dev-e01"
        assert "source_channel" in ev

    def test_E02_evidence_contains_stale_trigger(self):
        ingress = self._ingress()
        evt = _make_event(is_stale=True)
        outcome = ingress.process(evt)
        assert "stale_trigger" in outcome.stale_epoch_evidence

    def test_E03_incomplete_reason_starts_with_stale_prefix(self):
        ingress = self._ingress()
        evt = _make_event(is_stale=True)
        outcome = ingress.process(evt)
        assert outcome.incomplete_reason.startswith("stale_epoch_rejected:")

    def test_E04_stale_not_recorded_in_idempotency_store(self):
        """Stale results MUST NOT pollute the durable idempotency store."""
        ingress = self._ingress()
        recorded_keys: list = []

        original_record = ingress._record_idempotency

        def _recording_record(evt):
            recorded_keys.append(evt.idempotency_key)
            return original_record(evt)

        ingress._record_idempotency = _recording_record  # type: ignore[method-assign]

        evt = _make_event(is_stale=True)
        ingress.process(evt)

        assert evt.idempotency_key not in recorded_keys, (
            "Stale result idempotency key must not be recorded"
        )


# ===========================================================================
# Group F — Current epoch normal result not mis-flagged
# ===========================================================================


class TestCurrentEpochNotMisFlagged:

    def _ingress(self):
        return _make_ingress_with_stubs()

    def test_F01_current_epoch_not_stale_rejected(self):
        ingress = self._ingress()
        evt = _make_event(session_epoch=7, device_id="dev-current")
        registry_entry = _make_registry_entry(continuity_epoch=7)

        with patch(
            "core.attached_runtime_session_registry.lookup_session_by_device",
            return_value=registry_entry,
        ):
            outcome = ingress.process(evt)

        assert outcome.stale_epoch_rejected is False

    def test_F02_current_epoch_can_fully_close(self):
        ingress = self._ingress()
        evt = _make_event(session_epoch=7, device_id="dev-current")
        registry_entry = _make_registry_entry(continuity_epoch=7)

        with patch(
            "core.attached_runtime_session_registry.lookup_session_by_device",
            return_value=registry_entry,
        ):
            outcome = ingress.process(evt)

        # should proceed through truth chain and completion
        assert outcome.truth_chain_complete is True
        assert outcome.completion_notified is True

    def test_F03_replay_channel_matching_epoch_not_stale(self):
        ingress = self._ingress()
        evt = _make_event(session_epoch=4, device_id="dev-replay-ok", channel="replay")
        registry_entry = _make_registry_entry(continuity_epoch=4)

        with patch(
            "core.attached_runtime_session_registry.lookup_session_by_device",
            return_value=registry_entry,
        ):
            outcome = ingress.process(evt)

        assert outcome.stale_epoch_rejected is False


# ===========================================================================
# Group G — Late completion / reconnect scenarios
# ===========================================================================


class TestLateCompletionAndReconnectScenarios:
    """End-to-end scenario tests that mirror real Android continuity drift cases."""

    def _ingress(self):
        return _make_ingress_with_stubs()

    def test_G01_old_session_late_completion_blocked(self):
        """A completion from a previous session epoch (e.g. epoch=1) must NOT
        enter canonical closure when the current registered epoch is 2."""
        ingress = self._ingress()
        tid = _make_task_id()
        evt = _make_event(task_id=tid, session_epoch=1, device_id="dev-g01")
        current_entry = _make_registry_entry(continuity_epoch=2)

        with patch(
            "core.attached_runtime_session_registry.lookup_session_by_device",
            return_value=current_entry,
        ):
            outcome = ingress.process(evt)

        assert outcome.stale_epoch_rejected is True
        assert outcome.is_fully_closed is False
        assert outcome.stale_classification == "epoch_mismatch"
        assert outcome.stale_epoch_evidence.get("stored_epoch") == 2
        assert outcome.stale_epoch_evidence.get("presented_epoch") == 1

    def test_G02_reconnect_late_result_explicit_stale_blocked(self):
        """After a device reconnects, its old inflight results pre-marked as
        is_stale=True (by the reconnect handler) must be blocked."""
        ingress = self._ingress()
        tid = _make_task_id()
        evt = _make_event(
            task_id=tid,
            is_stale=True,
            stale_reason="reconnect_late_result",
            channel="canonical_ws",
        )
        outcome = ingress.process(evt)

        assert outcome.stale_epoch_rejected is True
        assert outcome.is_fully_closed is False
        assert "reconnect_late_result" in outcome.stale_epoch_evidence.get(
            "stale_reason", ""
        )

    def test_G03_replay_derived_stale_result_blocked(self):
        """An offline-replay result arriving with a mismatched session epoch
        must be classified as replay_epoch_mismatch and blocked."""
        ingress = self._ingress()
        tid = _make_task_id()
        evt = _make_event(
            task_id=tid,
            session_epoch=0,
            device_id="dev-g03",
            channel="replay",
        )
        current_entry = _make_registry_entry(continuity_epoch=3)

        with patch(
            "core.attached_runtime_session_registry.lookup_session_by_device",
            return_value=current_entry,
        ):
            outcome = ingress.process(evt)

        assert outcome.stale_epoch_rejected is True
        assert outcome.stale_classification == "replay_epoch_mismatch"
        assert outcome.is_fully_closed is False

    def test_G04_current_epoch_result_not_blocked(self):
        """Control case: a result from the current session epoch must pass
        through without stale rejection."""
        ingress = self._ingress()
        tid = _make_task_id()
        evt = _make_event(
            task_id=tid,
            session_epoch=5,
            device_id="dev-g04",
            channel="canonical_ws",
        )
        current_entry = _make_registry_entry(continuity_epoch=5)

        with patch(
            "core.attached_runtime_session_registry.lookup_session_by_device",
            return_value=current_entry,
        ):
            outcome = ingress.process(evt)

        assert outcome.stale_epoch_rejected is False
        assert outcome.truth_chain_complete is True
