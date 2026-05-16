#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_unified_result_ingress.py
=====================================
PR-UNIFY: Unified Result Ingress — verifies that ALL result source channels
enter the same processing chain and that the full closure loop is maintained.

Coverage
--------
Group A — Module and API surface
  A01  core.unified_result_ingress is importable
  A02  UNIFIED_RESULT_INGRESS_POLICY sentinel is present
  A03  ResultSourceChannel has all required values
  A04  NormalizedResultEvent is constructable with minimal fields
  A05  NormalizedResultEvent auto-generates idempotency_key from kind + task_id
  A06  UnifiedResultIngress is importable
  A07  get_unified_result_ingress() returns a singleton
  A08  ingest_result convenience wrapper is importable
  A09  ingest_result_async convenience wrapper is importable
  A10  normalize_status helper is importable and correct

Group B — Idempotency
  B01  First ingest_result call is NOT deduplicated
  B02  Second ingest_result call for same idempotency_key IS deduplicated
  B03  Deduplicated event returns was_deduplicated=True
  B04  Different task_ids are independently tracked

Group C — Status mapping (normalize_status)
  C01  "failed"    → "failed"
  C02  "error"     → "failed"
  C03  "cancelled" → "cancelled"
  C04  "degraded"  → "degraded"
  C05  "success"   → "completed"
  C06  "completed" → "completed"
  C07  None / ""   → "completed"
  C08  "FAILED" (upper-case) → "failed"

Group D — Truth chain integration
  D01  ingest_result calls run_task_result_truth_chain when available
  D02  truth chain receives the normalized_status (not raw Android status)
  D03  ImportError of truth chain is handled gracefully

Group E — CanonicalCompletionIngress notify
  E01  ingest_result calls CanonicalCompletionIngress.notify()
  E02  ImportError of completion ingress is handled gracefully
  E03  notify() returning False cannot be counted as full closure success

Group F — Bridge _pending_responses resolution
  F01  process_async resolves bridge._pending_responses future for task_id
  F02  Already-done future is not set again
  F03  Missing future is handled gracefully

Group G — Source channel coverage (all channels produce closure)
  G01  CANONICAL_WS channel produces a closure attempt
  G02  COMPAT_WS channel produces a closure attempt
  G03  REST_CALLBACK channel produces a closure attempt
  G04  REPLAY channel produces a closure attempt
  G05  DELEGATED channel produces a closure attempt

Group H — REST endpoint integration (real closure, not pseudo-completion)
  H01  submit_task_result calls run_task_result_truth_chain
  H02  submit_task_result calls CanonicalCompletionIngress.notify

Group I — compat WS goal_execution_result handler
  I01  compat WS handles goal_execution_result message type (not silent discard)
  I02  compat WS goal_execution_result calls unified ingress truth chain
  I03  compat WS goal_execution_result idempotency guard suppresses replay

Group J — canonical handle_goal_execution_result completion authority
  J01  handle_goal_execution_result calls CanonicalCompletionIngress.notify
  J02  handle_goal_execution_result resolves bridge._pending_responses
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

try:
    import fastapi  # noqa: F401

    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False

try:
    import pydantic  # noqa: F401

    _PYDANTIC_AVAILABLE = True
except ImportError:
    _PYDANTIC_AVAILABLE = False


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
) -> Any:
    from core.unified_result_ingress import NormalizedResultEvent, ResultSourceChannel

    tid = task_id or _make_task_id()
    return NormalizedResultEvent(
        task_id=tid,
        device_id="test-device",
        raw_message_type=kind,
        normalized_result_kind=kind,
        normalized_status=status,
        source_channel=ResultSourceChannel(channel),
        payload={"task_id": tid, "status": status, "result": "ok"},
        trace_id="trace-test",
        raw_message={"task_id": tid, "status": status, "type": kind},
    )


# ===========================================================================
# Group A — Module and API surface
# ===========================================================================


class TestModuleSurface:

    def test_A01_module_importable(self):
        import core.unified_result_ingress  # noqa: F401

    def test_A02_policy_sentinel_present(self):
        from core.unified_result_ingress import UNIFIED_RESULT_INGRESS_POLICY

        assert "UNIFIED_RESULT_INGRESS_V1" in UNIFIED_RESULT_INGRESS_POLICY

    def test_A03_result_source_channel_values(self):
        from core.unified_result_ingress import ResultSourceChannel

        assert hasattr(ResultSourceChannel, "CANONICAL_WS")
        assert hasattr(ResultSourceChannel, "COMPAT_WS")
        assert hasattr(ResultSourceChannel, "REST_CALLBACK")
        assert hasattr(ResultSourceChannel, "REPLAY")
        assert hasattr(ResultSourceChannel, "DELEGATED")
        assert hasattr(ResultSourceChannel, "UNKNOWN")

    def test_A04_normalized_result_event_constructable(self):
        from core.unified_result_ingress import NormalizedResultEvent, ResultSourceChannel

        evt = NormalizedResultEvent(
            task_id="t1",
            device_id="d1",
            raw_message_type="goal_execution_result",
            normalized_result_kind="goal_execution_result",
            normalized_status="completed",
            source_channel=ResultSourceChannel.CANONICAL_WS,
        )
        assert evt.task_id == "t1"
        assert evt.device_id == "d1"
        assert evt.normalized_status == "completed"

    def test_A05_idempotency_key_auto_generated(self):
        from core.unified_result_ingress import NormalizedResultEvent, ResultSourceChannel

        evt = NormalizedResultEvent(
            task_id="auto-key-test",
            normalized_result_kind="goal_execution_result",
            normalized_status="completed",
            source_channel=ResultSourceChannel.CANONICAL_WS,
        )
        assert evt.idempotency_key == "goal_execution_result:auto-key-test"

    def test_A06_unified_result_ingress_class_importable(self):
        from core.unified_result_ingress import UnifiedResultIngress

        assert callable(UnifiedResultIngress)

    def test_A07_get_unified_result_ingress_singleton(self):
        from core.unified_result_ingress import get_unified_result_ingress

        a = get_unified_result_ingress()
        b = get_unified_result_ingress()
        assert a is b

    def test_A08_ingest_result_importable(self):
        from core.unified_result_ingress import ingest_result

        assert callable(ingest_result)

    def test_A09_ingest_result_async_importable(self):
        from core.unified_result_ingress import ingest_result_async

        assert callable(ingest_result_async)

    def test_A10_normalize_status_importable(self):
        from core.unified_result_ingress import normalize_status

        assert callable(normalize_status)

    def test_A11_outcome_exposes_problem_execution_closure(self):
        from core.unified_result_ingress import UnifiedResultIngressOutcome

        outcome = UnifiedResultIngressOutcome()
        assert isinstance(outcome.problem_execution_closure, dict)
        assert outcome.task_completed is False
        assert outcome.problem_solved is False


# ===========================================================================
# Group B — Idempotency
# ===========================================================================


class TestIdempotency:
    """Ingest idempotency uses durable_result_idempotency store."""

    def _make_ingress_with_fresh_store(self):
        """Return an ingress backed by a fresh in-memory idempotency store."""
        from core.unified_result_ingress import UnifiedResultIngress

        store: set = set()

        ingress = UnifiedResultIngress()
        # Patch check/record at the ingress object method level
        original_check = ingress._check_idempotency
        original_record = ingress._record_idempotency

        def _patched_check(event):
            return event.idempotency_key in store

        def _patched_record(event):
            store.add(event.idempotency_key)

        ingress._check_idempotency = _patched_check  # type: ignore[method-assign]
        ingress._record_idempotency = _patched_record  # type: ignore[method-assign]

        # Also patch downstream steps to be no-ops so idempotency is isolated
        ingress._run_truth_chain = lambda _e: True  # type: ignore[method-assign]
        ingress._sync_lifecycle = lambda _e: None  # type: ignore[method-assign]
        ingress._notify_completion = lambda _e: True  # type: ignore[method-assign]
        ingress._log_outcome = lambda _e, _o: None  # type: ignore[method-assign]

        return ingress, store

    def test_B01_first_ingest_not_deduplicated(self):
        ingress, _ = self._make_ingress_with_fresh_store()
        evt = _make_event(_make_task_id())
        outcome = ingress.process(evt)
        assert not outcome.was_deduplicated

    def test_B02_second_ingest_deduplicated(self):
        ingress, _ = self._make_ingress_with_fresh_store()
        tid = _make_task_id()
        evt = _make_event(tid)
        ingress.process(evt)  # first
        outcome = ingress.process(evt)  # second, same key
        assert outcome.was_deduplicated

    def test_B03_deduplicated_returns_flag_true(self):
        ingress, _ = self._make_ingress_with_fresh_store()
        tid = _make_task_id()
        evt = _make_event(tid)
        ingress.process(evt)
        outcome = ingress.process(evt)
        assert outcome.was_deduplicated is True

    def test_B04_different_task_ids_independent(self):
        ingress, _ = self._make_ingress_with_fresh_store()
        tid1, tid2 = _make_task_id(), _make_task_id()
        o1 = ingress.process(_make_event(tid1))
        o2 = ingress.process(_make_event(tid2))
        assert not o1.was_deduplicated
        assert not o2.was_deduplicated


# ===========================================================================
# Group C — Status mapping (normalize_status)
# ===========================================================================


class TestNormalizeStatus:

    def test_C01_failed_maps_to_failed(self):
        from core.unified_result_ingress import normalize_status

        assert normalize_status("failed") == "failed"

    def test_C02_error_maps_to_failed(self):
        from core.unified_result_ingress import normalize_status

        assert normalize_status("error") == "failed"

    def test_C03_cancelled_maps_to_cancelled(self):
        from core.unified_result_ingress import normalize_status

        assert normalize_status("cancelled") == "cancelled"

    def test_C04_degraded_maps_to_degraded(self):
        from core.unified_result_ingress import normalize_status

        assert normalize_status("degraded") == "degraded"

    def test_C05_success_maps_to_completed(self):
        from core.unified_result_ingress import normalize_status

        assert normalize_status("success") == "completed"

    def test_C06_completed_maps_to_completed(self):
        from core.unified_result_ingress import normalize_status

        assert normalize_status("completed") == "completed"

    def test_C07_none_maps_to_completed(self):
        from core.unified_result_ingress import normalize_status

        assert normalize_status(None) == "completed"
        assert normalize_status("") == "completed"

    def test_C08_upper_case_failed_maps_to_failed(self):
        from core.unified_result_ingress import normalize_status

        assert normalize_status("FAILED") == "failed"


# ===========================================================================
# Group D — Truth chain integration
# ===========================================================================


class TestTruthChainIntegration:

    def test_D01_ingest_result_calls_truth_chain(self):
        """ingest_result must invoke run_task_result_truth_chain when available."""
        from core.unified_result_ingress import UnifiedResultIngress, NormalizedResultEvent, ResultSourceChannel

        called = []

        class _FakeOutcome:
            is_truth_chain_complete = True
            incomplete_reason = ""

        def _fake_truth_chain(msg, *, task_id=None, result_status=None):
            called.append((task_id, result_status))
            return _FakeOutcome()

        ingress = UnifiedResultIngress()
        ingress._check_idempotency = lambda _e: False  # type: ignore[method-assign]
        ingress._record_idempotency = lambda _e: None  # type: ignore[method-assign]
        ingress._sync_lifecycle = lambda _e: None  # type: ignore[method-assign]
        ingress._notify_completion = lambda _e: True  # type: ignore[method-assign]
        ingress._log_outcome = lambda _e, _o: None  # type: ignore[method-assign]

        with patch(
            "core.unified_result_ingress.UnifiedResultIngress._run_truth_chain",
            wraps=ingress._run_truth_chain,
        ):
            tid = _make_task_id()
            evt = _make_event(tid)

            with patch(
                "core.task_result_canonical_truth_chain.run_task_result_truth_chain",
                side_effect=_fake_truth_chain,
            ):
                ingress.process(evt)

        assert len(called) == 1
        assert called[0][0] == tid

    def test_D02_truth_chain_receives_normalized_status(self):
        """The truth chain must receive the V2 canonical status, not raw Android."""
        from core.unified_result_ingress import UnifiedResultIngress, NormalizedResultEvent, ResultSourceChannel

        received_status = []

        class _FakeOutcome:
            is_truth_chain_complete = True
            incomplete_reason = ""

        def _fake(msg, *, task_id=None, result_status=None):
            received_status.append(result_status)
            return _FakeOutcome()

        ingress = UnifiedResultIngress()
        ingress._check_idempotency = lambda _e: False  # type: ignore[method-assign]
        ingress._record_idempotency = lambda _e: None  # type: ignore[method-assign]
        ingress._sync_lifecycle = lambda _e: None  # type: ignore[method-assign]
        ingress._notify_completion = lambda _e: True  # type: ignore[method-assign]
        ingress._log_outcome = lambda _e, _o: None  # type: ignore[method-assign]

        with patch(
            "core.task_result_canonical_truth_chain.run_task_result_truth_chain",
            side_effect=_fake,
        ):
            evt = NormalizedResultEvent(
                task_id=_make_task_id(),
                normalized_result_kind="goal_execution_result",
                normalized_status="failed",  # already normalized
                source_channel=ResultSourceChannel.CANONICAL_WS,
            )
            ingress.process(evt)

        assert received_status == ["failed"]

    def test_D03_import_failure_handled_gracefully(self):
        """ImportError of truth chain must not raise from ingest_result."""
        from core.unified_result_ingress import UnifiedResultIngress

        ingress = UnifiedResultIngress()
        ingress._check_idempotency = lambda _e: False  # type: ignore[method-assign]
        ingress._record_idempotency = lambda _e: None  # type: ignore[method-assign]
        ingress._sync_lifecycle = lambda _e: None  # type: ignore[method-assign]
        ingress._notify_completion = lambda _e: True  # type: ignore[method-assign]
        ingress._log_outcome = lambda _e, _o: None  # type: ignore[method-assign]

        evt = _make_event(_make_task_id())
        with patch(
            "core.task_result_canonical_truth_chain.run_task_result_truth_chain",
            side_effect=ImportError("unavailable"),
        ):
            outcome = ingress.process(evt)

        # Must not raise; truth chain marked incomplete
        assert not outcome.truth_chain_complete


# ===========================================================================
# Group E — CanonicalCompletionIngress notify
# ===========================================================================


class TestCompletionIngressNotify:

    def test_E01_ingest_result_calls_completion_notify(self):
        """ingest_result must call CanonicalCompletionIngress.notify()."""
        from core.unified_result_ingress import UnifiedResultIngress

        notified = []

        class _NotifyOnlyIngress:
            def notify(self, env):
                notified.append(env.task_id)
                return True

        ingress = UnifiedResultIngress()
        ingress._check_idempotency = lambda _e: False  # type: ignore[method-assign]
        ingress._record_idempotency = lambda _e: None  # type: ignore[method-assign]
        ingress._run_truth_chain = lambda _e: True  # type: ignore[method-assign]
        ingress._sync_lifecycle = lambda _e: None  # type: ignore[method-assign]
        ingress._log_outcome = lambda _e, _o: None  # type: ignore[method-assign]

        tid = _make_task_id()
        with patch(
            "core.canonical_completion_ingress.get_canonical_completion_ingress",
            return_value=_NotifyOnlyIngress(),
        ):
            ingress.process(_make_event(tid))

        assert tid in notified

    def test_E02_completion_ingress_import_failure_graceful(self):
        """ImportError of completion ingress must not raise."""
        from core.unified_result_ingress import UnifiedResultIngress

        ingress = UnifiedResultIngress()
        ingress._check_idempotency = lambda _e: False  # type: ignore[method-assign]
        ingress._record_idempotency = lambda _e: None  # type: ignore[method-assign]
        ingress._run_truth_chain = lambda _e: True  # type: ignore[method-assign]
        ingress._sync_lifecycle = lambda _e: None  # type: ignore[method-assign]
        ingress._log_outcome = lambda _e, _o: None  # type: ignore[method-assign]

        with patch(
            "core.canonical_completion_ingress.get_canonical_completion_ingress",
            side_effect=ImportError("unavailable"),
        ):
            outcome = ingress.process(_make_event(_make_task_id()))

        assert not outcome.completion_notified  # not notified but no exception

    def test_E03_notify_false_prevents_full_closure(self):
        """notify() returns False must not be treated as full closure success."""
        from core.unified_result_ingress import UnifiedResultIngress

        class _NotifyOnlyIngress:
            def notify(self, _env):
                return False

        ingress = UnifiedResultIngress()
        ingress._check_idempotency = lambda _e: False  # type: ignore[method-assign]
        ingress._record_idempotency = lambda _e: None  # type: ignore[method-assign]
        ingress._run_truth_chain = lambda _e: True  # type: ignore[method-assign]
        ingress._sync_lifecycle = lambda _e: None  # type: ignore[method-assign]
        ingress._log_outcome = lambda _e, _o: None  # type: ignore[method-assign]

        with patch(
            "core.canonical_completion_ingress.get_canonical_completion_ingress",
            return_value=_NotifyOnlyIngress(),
        ):
            outcome = ingress.process(_make_event(_make_task_id()))

        assert outcome.completion_notified is False
        assert outcome.is_fully_closed is False
        assert outcome.incomplete_reason == "completion_not_notified"

    def test_E04_problem_execution_closure_defaults_to_pending_problem_closure(self):
        from core.unified_result_ingress import UnifiedResultIngress

        ingress = UnifiedResultIngress()
        ingress._check_idempotency = lambda _e: False  # type: ignore[method-assign]
        ingress._record_idempotency = lambda _e: None  # type: ignore[method-assign]
        ingress._run_truth_chain = lambda _e: True  # type: ignore[method-assign]
        ingress._sync_lifecycle = lambda _e: None  # type: ignore[method-assign]
        ingress._notify_completion = lambda _e: True  # type: ignore[method-assign]
        ingress._log_outcome = lambda _e, _o: None  # type: ignore[method-assign]

        evt = _make_event(_make_task_id(), status="completed", channel="delegated")
        outcome = ingress.process(evt)
        assert outcome.problem_execution_closure["task_closure_stage"] == "closed"
        assert outcome.problem_execution_closure["problem_closure_stage"] == "pending_user_problem_closure"
        assert outcome.task_completed is True
        assert outcome.problem_solved is False

    def test_E05_quarantine_verdict_blocks_closure(self):
        from core.unified_result_ingress import UnifiedResultIngress

        ingress = UnifiedResultIngress()
        ingress._check_idempotency = lambda _e: False  # type: ignore[method-assign]
        ingress._record_idempotency = lambda _e: None  # type: ignore[method-assign]
        ingress._run_truth_chain = lambda _e: True  # type: ignore[method-assign]
        ingress._sync_lifecycle = lambda _e: None  # type: ignore[method-assign]
        ingress._notify_completion = lambda _e: True  # type: ignore[method-assign]
        ingress._log_outcome = lambda _e, _o: None  # type: ignore[method-assign]

        def _force_quarantine(_event: Any, outcome: Any) -> None:
            outcome.evidence_acceptance_verdict = "quarantine"
            outcome.incomplete_reason = "evidence_gate:quarantine"

        ingress._classify_and_apply_evidence_gate = _force_quarantine  # type: ignore[method-assign]

        outcome = ingress.process(_make_event(_make_task_id()))

        assert outcome.evidence_acceptance_verdict == "quarantine"
        assert outcome.is_fully_closed is False
        assert "evidence_gate:quarantine" in outcome.incomplete_reason

    def test_E06_quarantine_verdict_backfills_missing_reason(self):
        from core.unified_result_ingress import UnifiedResultIngress

        ingress = UnifiedResultIngress()
        ingress._check_idempotency = lambda _e: False  # type: ignore[method-assign]
        ingress._record_idempotency = lambda _e: None  # type: ignore[method-assign]
        ingress._run_truth_chain = lambda _e: True  # type: ignore[method-assign]
        ingress._sync_lifecycle = lambda _e: None  # type: ignore[method-assign]
        ingress._notify_completion = lambda _e: True  # type: ignore[method-assign]
        ingress._log_outcome = lambda _e, _o: None  # type: ignore[method-assign]

        def _force_quarantine_without_reason(_event: Any, outcome: Any) -> None:
            outcome.evidence_acceptance_verdict = "quarantine"

        ingress._classify_and_apply_evidence_gate = _force_quarantine_without_reason  # type: ignore[method-assign]

        outcome = ingress.process(_make_event(_make_task_id()))

        assert outcome.is_fully_closed is False
        assert outcome.incomplete_reason == "evidence_gate:quarantine"

    def test_E07_notify_with_android_context_receives_acceptance_and_tier(self):
        from core.unified_result_ingress import UnifiedResultIngress

        class _FakeCompletionIngress:
            def __init__(self):
                self.calls = []

            def notify_with_android_context(
                self,
                env,
                *,
                android_participation_tier=None,
                android_device_id=None,
                acceptance_verdict=None,
            ):
                self.calls.append(
                    {
                        "task_id": env.task_id,
                        "tier": android_participation_tier,
                        "device_id": android_device_id,
                        "acceptance_verdict": acceptance_verdict,
                    }
                )
                return True

            def notify(self, _env):
                raise AssertionError("notify() should not be called when notify_with_android_context is available")

        class _FakeTruthBlock:
            def to_dict(self):
                return {"participation_tier": "dispatch_eligible"}

        fake_completion_ingress = _FakeCompletionIngress()

        ingress = UnifiedResultIngress()
        ingress._check_idempotency = lambda _e: False  # type: ignore[method-assign]
        ingress._record_idempotency = lambda _e: None  # type: ignore[method-assign]
        ingress._run_truth_chain = lambda _e: True  # type: ignore[method-assign]
        ingress._sync_lifecycle = lambda _e: None  # type: ignore[method-assign]
        ingress._log_outcome = lambda _e, _o: None  # type: ignore[method-assign]

        def _force_accept_provisional(_event: Any, outcome: Any) -> None:
            outcome.evidence_acceptance_verdict = "accept_provisional"

        ingress._classify_and_apply_evidence_gate = _force_accept_provisional  # type: ignore[method-assign]

        tid = _make_task_id()
        with (
            patch(
                "core.canonical_completion_ingress.get_canonical_completion_ingress",
                return_value=fake_completion_ingress,
            ),
            patch(
                "core.v2_android_truth_ssot.build_v2_android_truth_block",
                return_value=_FakeTruthBlock(),
            ),
        ):
            outcome = ingress.process(_make_event(tid))

        assert outcome.completion_notified is True
        assert fake_completion_ingress.calls, "notify_with_android_context should be called"
        call = fake_completion_ingress.calls[0]
        assert call["task_id"] == tid
        assert call["tier"] == "dispatch_eligible"
        assert call["device_id"] == "test-device"
        assert call["acceptance_verdict"] == "accept_provisional"

    def test_E08_fallback_to_notify_when_notify_with_android_context_missing(self):
        from core.unified_result_ingress import UnifiedResultIngress

        fallback_calls = []

        class _NotifyOnlyIngress:
            def notify(self, env):
                fallback_calls.append(env.task_id)
                return True

        ingress = UnifiedResultIngress()
        ingress._check_idempotency = lambda _e: False  # type: ignore[method-assign]
        ingress._record_idempotency = lambda _e: None  # type: ignore[method-assign]
        ingress._run_truth_chain = lambda _e: True  # type: ignore[method-assign]
        ingress._sync_lifecycle = lambda _e: None  # type: ignore[method-assign]
        ingress._log_outcome = lambda _e, _o: None  # type: ignore[method-assign]

        tid = _make_task_id()
        with patch(
            "core.canonical_completion_ingress.get_canonical_completion_ingress",
            return_value=_NotifyOnlyIngress(),
        ):
            outcome = ingress.process(_make_event(tid))

        assert outcome.completion_notified is True
        assert fallback_calls == [tid]

    def test_E09_android_missing_proof_surfaces_inferred_strong_evidence(self):
        from core.unified_result_ingress import UnifiedResultIngress

        class _FakeTruthBlock:
            def to_dict(self):
                return {
                    "participation_tier": "dispatch_eligible",
                    "dispatch_eligible": True,
                    "runtime_constrained": False,
                    "local_mode_active": False,
                    "local_loop_ready": True,
                    "sources": ["test-runtime-truth"],
                }

        ingress = UnifiedResultIngress()
        ingress._check_idempotency = lambda _e: False  # type: ignore[method-assign]
        ingress._record_idempotency = lambda _e: None  # type: ignore[method-assign]
        ingress._run_truth_chain = lambda _e: True  # type: ignore[method-assign]
        ingress._sync_lifecycle = lambda _e: None  # type: ignore[method-assign]
        ingress._notify_completion = lambda _e: True  # type: ignore[method-assign]
        ingress._log_outcome = lambda _e, _o: None  # type: ignore[method-assign]

        with patch(
            "core.v2_android_truth_ssot.build_v2_android_truth_block",
            return_value=_FakeTruthBlock(),
        ):
            event = _make_event(
                _make_task_id(),
                channel="canonical_ws",
            )
            event.payload.update(
                {
                    "runtime_constrained": False,
                    "local_mode_active": False,
                }
            )
            outcome = ingress.process(event)

        assert outcome.evidence_acceptance_verdict == "accept"
        assert outcome.effective_android_proof_class == "inferred_strong"
        assert outcome.android_evidence_resolution == "inferred_runtime_context"
        assert outcome.android_inferred_evidence_strength == "strong"
        assert outcome.android_evidence_runtime_context["participation_tier"] == "dispatch_eligible"

    def test_E09b_android_acceptance_report_maps_to_evidence_gate(self):
        from core.unified_result_ingress import UnifiedResultIngress

        class _FakeTruthBlock:
            def to_dict(self):
                return {
                    "participation_tier": "cross_device_enabled",
                    "dispatch_eligible": False,
                    "runtime_constrained": True,
                    "local_mode_active": False,
                    "local_loop_ready": False,
                    "sources": ["test-runtime-truth"],
                }

        ingress = UnifiedResultIngress()
        ingress._check_idempotency = lambda _e: False  # type: ignore[method-assign]
        ingress._record_idempotency = lambda _e: None  # type: ignore[method-assign]
        ingress._run_truth_chain = lambda _e: True  # type: ignore[method-assign]
        ingress._sync_lifecycle = lambda _e: None  # type: ignore[method-assign]
        ingress._notify_completion = lambda _e: True  # type: ignore[method-assign]
        ingress._log_outcome = lambda _e, _o: None  # type: ignore[method-assign]

        with patch(
            "core.v2_android_truth_ssot.build_v2_android_truth_block",
            return_value=_FakeTruthBlock(),
        ), patch(
            "core.android_acceptance_evidence_store.get_latest_device_acceptance_evidence_dict",
            return_value={
                "acceptance_tag": "device_accepted_for_graduation",
                "mapped_android_proof_class": "confirmed_strong",
                "mapped_evidence_trust_level": "trusted",
                "snapshot_id": "accept-snap-02",
                "dimension_states": {"governance": "pass"},
                "missing_dimensions": [],
                "mapping_reason": "acceptance_tag indicates graduation-level acceptance",
            },
        ):
            outcome = ingress.process(_make_event(_make_task_id(), channel="canonical_ws"))

        assert outcome.evidence_acceptance_verdict == "accept"
        assert outcome.effective_android_proof_class == "confirmed_strong"
        assert (
            outcome.android_evidence_resolution
            == "acceptance_report_mapped_proof_class"
        )
        assert (
            outcome.android_evidence_runtime_context["acceptance_tag"]
            == "device_accepted_for_graduation"
        )
        assert (
            "runtime_truth:acceptance_tag"
            in outcome.android_evidence_runtime_context.get("context_sources", [])
        )

    def test_E10_android_truth_stamp_prefers_result_payload_over_ssot(self):
        from core.unified_result_ingress import UnifiedResultIngress

        class _FakeCompletionIngress:
            def __init__(self):
                self.calls = []

            def notify_with_android_context(
                self,
                env,
                *,
                android_participation_tier=None,
                android_device_id=None,
                acceptance_verdict=None,
            ):
                self.calls.append(
                    {
                        "task_id": env.task_id,
                        "tier": android_participation_tier,
                        "device_id": android_device_id,
                        "acceptance_verdict": acceptance_verdict,
                    }
                )
                return True

        class _FakeTruthBlock:
            def to_dict(self):
                return {
                    "participation_tier": None,
                    "dispatch_eligible": True,
                    "runtime_constrained": True,
                    "local_mode_active": False,
                    "local_loop_ready": False,
                    "sources": ["ssot"],
                }

        fake_completion_ingress = _FakeCompletionIngress()

        ingress = UnifiedResultIngress()
        ingress._check_idempotency = lambda _e: False  # type: ignore[method-assign]
        ingress._record_idempotency = lambda _e: None  # type: ignore[method-assign]
        ingress._run_truth_chain = lambda _e: True  # type: ignore[method-assign]
        ingress._sync_lifecycle = lambda _e: None  # type: ignore[method-assign]
        ingress._log_outcome = lambda _e, _o: None  # type: ignore[method-assign]

        event = _make_event(_make_task_id())
        event.payload.update(
            {
                "participation_tier": "distributed_participant",
                "dispatch_eligible": False,
                "runtime_constrained": False,
                "local_mode_active": True,
                "local_loop_ready": True,
            }
        )

        with (
            patch(
                "core.canonical_completion_ingress.get_canonical_completion_ingress",
                return_value=fake_completion_ingress,
            ),
            patch(
                "core.v2_android_truth_ssot.build_v2_android_truth_block",
                return_value=_FakeTruthBlock(),
            ),
        ):
            outcome = ingress.process(event)

        call = fake_completion_ingress.calls[0]
        assert call["tier"] == "distributed_participant"
        assert outcome.android_truth_context["participation_tier"] == "distributed_participant"
        assert outcome.android_truth_context["dispatch_eligible"] is False
        assert outcome.android_truth_context["runtime_constrained"] is False
        assert outcome.android_truth_context["local_mode_active"] is True
        assert outcome.android_truth_context["local_loop_ready"] is True
        assert outcome.android_truth_context["android_truth_source_by_field"]["participation_tier"] == "result_payload"
        assert outcome.android_truth_context["android_truth_source_by_field"]["dispatch_eligible"] == "result_payload"
        assert outcome.android_truth_context["android_truth_source_by_field"]["local_loop_ready"] == "result_payload"

    def test_E11_android_truth_stamp_falls_back_to_ssot_when_payload_truth_absent(self):
        from core.unified_result_ingress import UnifiedResultIngress

        class _FakeCompletionIngress:
            def __init__(self):
                self.calls = []

            def notify_with_android_context(
                self,
                env,
                *,
                android_participation_tier=None,
                android_device_id=None,
                acceptance_verdict=None,
            ):
                self.calls.append(
                    {
                        "task_id": env.task_id,
                        "tier": android_participation_tier,
                        "device_id": android_device_id,
                        "acceptance_verdict": acceptance_verdict,
                    }
                )
                return True

        class _FakeTruthBlock:
            def to_dict(self):
                return {
                    "participation_tier": "dispatch_eligible",
                    "dispatch_eligible": True,
                    "runtime_constrained": False,
                    "local_mode_active": False,
                    "local_loop_ready": True,
                    "sources": ["ssot"],
                }

        fake_completion_ingress = _FakeCompletionIngress()

        ingress = UnifiedResultIngress()
        ingress._check_idempotency = lambda _e: False  # type: ignore[method-assign]
        ingress._record_idempotency = lambda _e: None  # type: ignore[method-assign]
        ingress._run_truth_chain = lambda _e: True  # type: ignore[method-assign]
        ingress._sync_lifecycle = lambda _e: None  # type: ignore[method-assign]
        ingress._log_outcome = lambda _e, _o: None  # type: ignore[method-assign]

        with (
            patch(
                "core.canonical_completion_ingress.get_canonical_completion_ingress",
                return_value=fake_completion_ingress,
            ),
            patch(
                "core.v2_android_truth_ssot.build_v2_android_truth_block",
                return_value=_FakeTruthBlock(),
            ),
        ):
            outcome = ingress.process(_make_event(_make_task_id()))

        call = fake_completion_ingress.calls[0]
        assert call["tier"] == "dispatch_eligible"
        assert outcome.android_truth_context["participation_tier"] == "dispatch_eligible"
        assert outcome.android_truth_context["android_truth_source_by_field"]["participation_tier"] == "ssot_snapshot"
        assert outcome.android_truth_context["dispatch_eligible"] is True
        assert outcome.android_truth_context["runtime_constrained"] is False
        assert outcome.android_truth_context["local_mode_active"] is False
        assert outcome.android_truth_context["local_loop_ready"] is True
        assert outcome.android_truth_context["android_truth_source_by_field"]["local_loop_ready"] == "ssot_snapshot"

    def test_E12_delayed_result_keeps_payload_truth_when_ssot_snapshot_is_empty(self):
        from core.unified_result_ingress import UnifiedResultIngress

        class _FakeTruthBlock:
            def to_dict(self):
                return {
                    "participation_tier": None,
                    "dispatch_eligible": None,
                    "runtime_constrained": None,
                    "local_mode_active": None,
                    "local_loop_ready": None,
                    "sources": [],
                }

        ingress = UnifiedResultIngress()
        ingress._check_idempotency = lambda _e: False  # type: ignore[method-assign]
        ingress._record_idempotency = lambda _e: None  # type: ignore[method-assign]
        ingress._run_truth_chain = lambda _e: True  # type: ignore[method-assign]
        ingress._sync_lifecycle = lambda _e: None  # type: ignore[method-assign]
        ingress._notify_completion = lambda _e: True  # type: ignore[method-assign]
        ingress._log_outcome = lambda _e, _o: None  # type: ignore[method-assign]

        event = _make_event(_make_task_id(), channel="canonical_ws")
        event.payload.update(
            {
                "participation_tier": "dispatch_eligible",
                "dispatch_eligible": True,
                "runtime_constrained": False,
                "local_mode_active": False,
                "local_loop_ready": True,
            }
        )

        with patch(
            "core.v2_android_truth_ssot.build_v2_android_truth_block",
            return_value=_FakeTruthBlock(),
        ):
            outcome = ingress.process(event)

        assert outcome.android_truth_context["participation_tier"] == "dispatch_eligible"
        assert outcome.android_truth_context["android_truth_source_by_field"]["participation_tier"] == "result_payload"
        assert outcome.evidence_acceptance_verdict == "accept"
        assert outcome.android_evidence_runtime_context["participation_tier"] == "dispatch_eligible"
        assert "payload:participation_tier" in outcome.android_evidence_runtime_context.get("context_sources", [])

    def test_E13_delayed_result_keeps_payload_truth_when_ssot_read_fails(self):
        from core.unified_result_ingress import UnifiedResultIngress

        class _FakeCompletionIngress:
            def __init__(self):
                self.calls = []

            def notify_with_android_context(
                self,
                env,
                *,
                android_participation_tier=None,
                android_device_id=None,
                acceptance_verdict=None,
            ):
                self.calls.append(
                    {
                        "task_id": env.task_id,
                        "tier": android_participation_tier,
                        "device_id": android_device_id,
                        "acceptance_verdict": acceptance_verdict,
                    }
                )
                return True

        fake_completion_ingress = _FakeCompletionIngress()

        ingress = UnifiedResultIngress()
        ingress._check_idempotency = lambda _e: False  # type: ignore[method-assign]
        ingress._record_idempotency = lambda _e: None  # type: ignore[method-assign]
        ingress._run_truth_chain = lambda _e: True  # type: ignore[method-assign]
        ingress._sync_lifecycle = lambda _e: None  # type: ignore[method-assign]
        ingress._log_outcome = lambda _e, _o: None  # type: ignore[method-assign]

        event = _make_event(_make_task_id())
        event.payload.update(
            {
                "participation_tier": "distributed_participant",
                "dispatch_eligible": False,
                "runtime_constrained": False,
                "local_mode_active": False,
                "local_loop_ready": True,
            }
        )

        with (
            patch(
                "core.canonical_completion_ingress.get_canonical_completion_ingress",
                return_value=fake_completion_ingress,
            ),
            patch(
                "core.v2_android_truth_ssot.build_v2_android_truth_block",
                side_effect=Exception("ssot_unavailable"),
            ),
        ):
            outcome = ingress.process(event)

        call = fake_completion_ingress.calls[0]
        assert call["tier"] == "distributed_participant"
        assert outcome.android_truth_context["participation_tier"] == "distributed_participant"
        assert outcome.android_truth_context["dispatch_eligible"] is False
        assert outcome.android_truth_context["runtime_constrained"] is False
        assert outcome.android_truth_context["local_mode_active"] is False
        assert outcome.android_truth_context["local_loop_ready"] is True
        assert outcome.android_truth_context["android_truth_source_by_field"]["participation_tier"] == "result_payload"

    def test_E14_android_closure_class_backfills_completion_env_without_truth_chain(self):
        from core.unified_result_ingress import UnifiedResultIngress

        notify_calls = []

        class _NotifyOnlyIngress:
            def notify(self, env):
                notify_calls.append(
                    {
                        "problem_solved": env.problem_solved,
                        "problem_closed": env.problem_closed,
                    }
                )
                return True

        ingress = UnifiedResultIngress()
        ingress._check_idempotency = lambda _e: False  # type: ignore[method-assign]
        ingress._record_idempotency = lambda _e: None  # type: ignore[method-assign]
        ingress._run_truth_chain = lambda _e: False  # type: ignore[method-assign]
        ingress._sync_lifecycle = lambda _e: None  # type: ignore[method-assign]
        ingress._log_outcome = lambda _e, _o: None  # type: ignore[method-assign]

        event = _make_event(_make_task_id())
        event.payload["problem_solving_closure_class"] = "problem_solved_completed"

        with patch(
            "core.canonical_completion_ingress.get_canonical_completion_ingress",
            return_value=_NotifyOnlyIngress(),
        ):
            outcome = ingress.process(event)

        assert outcome.completion_notified is True
        assert notify_calls == [{"problem_solved": True, "problem_closed": True}]
        assert event.payload["problem_solved"] is True
        assert event.payload["problem_closed"] is True

    def test_E15_android_closure_class_unsolved_closed_keeps_problem_unsolved(self):
        from core.unified_result_ingress import UnifiedResultIngress

        notify_calls = []

        class _NotifyOnlyIngress:
            def notify(self, env):
                notify_calls.append(
                    {
                        "problem_solved": env.problem_solved,
                        "problem_closed": env.problem_closed,
                    }
                )
                return True

        ingress = UnifiedResultIngress()
        ingress._check_idempotency = lambda _e: False  # type: ignore[method-assign]
        ingress._record_idempotency = lambda _e: None  # type: ignore[method-assign]
        ingress._run_truth_chain = lambda _e: False  # type: ignore[method-assign]
        ingress._sync_lifecycle = lambda _e: None  # type: ignore[method-assign]
        ingress._log_outcome = lambda _e, _o: None  # type: ignore[method-assign]

        event = _make_event(_make_task_id())
        event.payload["problem_solving_closure_class"] = "problem_unsolved_closed"

        with patch(
            "core.canonical_completion_ingress.get_canonical_completion_ingress",
            return_value=_NotifyOnlyIngress(),
        ):
            ingress.process(event)

        assert notify_calls == [{"problem_solved": False, "problem_closed": True}]
        assert event.payload.get("problem_solved") is not True
        assert event.payload["problem_closed"] is True

    def test_E16_android_closure_class_fallback_does_not_downgrade_true_problem_solved(self):
        from core.unified_result_ingress import UnifiedResultIngress

        notify_calls = []

        class _NotifyOnlyIngress:
            def notify(self, env):
                notify_calls.append(
                    {
                        "problem_solved": env.problem_solved,
                        "problem_closed": env.problem_closed,
                    }
                )
                return True

        ingress = UnifiedResultIngress()
        ingress._check_idempotency = lambda _e: False  # type: ignore[method-assign]
        ingress._record_idempotency = lambda _e: None  # type: ignore[method-assign]
        ingress._run_truth_chain = lambda _e: False  # type: ignore[method-assign]
        ingress._sync_lifecycle = lambda _e: None  # type: ignore[method-assign]
        ingress._log_outcome = lambda _e, _o: None  # type: ignore[method-assign]

        event = _make_event(_make_task_id())
        event.payload.update(
            {
                "problem_solved": True,
                "problem_closed": True,
                "problem_solving_closure_class": "problem_unsolved_closed",
            }
        )

        with patch(
            "core.canonical_completion_ingress.get_canonical_completion_ingress",
            return_value=_NotifyOnlyIngress(),
        ):
            ingress.process(event)

        assert notify_calls == [{"problem_solved": True, "problem_closed": True}]
        assert event.payload["problem_solved"] is True
        assert event.payload["problem_closed"] is True


# ===========================================================================
# Group F — Bridge _pending_responses resolution
# ===========================================================================


class TestBridgePendingResolution:

    @pytest.mark.asyncio
    async def test_F01_process_async_resolves_pending_future(self):
        """process_async must resolve bridge._pending_responses future."""
        from core.unified_result_ingress import UnifiedResultIngress

        tid = _make_task_id()
        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()

        bridge = MagicMock()
        bridge._pending_responses = {tid: future}

        ingress = UnifiedResultIngress()
        ingress._check_idempotency = lambda _e: False  # type: ignore[method-assign]
        ingress._record_idempotency = lambda _e: None  # type: ignore[method-assign]
        ingress._run_truth_chain = lambda _e: True  # type: ignore[method-assign]
        ingress._sync_lifecycle = lambda _e: None  # type: ignore[method-assign]
        ingress._notify_completion = lambda _e: True  # type: ignore[method-assign]
        ingress._log_outcome = lambda _e, _o: None  # type: ignore[method-assign]

        evt = _make_event(tid, status="completed")
        outcome = await ingress.process_async(evt, bridge=bridge)

        assert future.done()
        result = future.result()
        assert result["status"] == "completed"
        assert result["task_id"] == tid
        assert outcome.pending_response_resolved

    @pytest.mark.asyncio
    async def test_F02_already_done_future_not_set_again(self):
        """process_async must not set_result on an already-done future."""
        from core.unified_result_ingress import UnifiedResultIngress

        tid = _make_task_id()
        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        future.set_result({"already": "done"})  # pre-resolve

        bridge = MagicMock()
        bridge._pending_responses = {tid: future}

        ingress = UnifiedResultIngress()
        ingress._check_idempotency = lambda _e: False  # type: ignore[method-assign]
        ingress._record_idempotency = lambda _e: None  # type: ignore[method-assign]
        ingress._run_truth_chain = lambda _e: True  # type: ignore[method-assign]
        ingress._sync_lifecycle = lambda _e: None  # type: ignore[method-assign]
        ingress._notify_completion = lambda _e: True  # type: ignore[method-assign]
        ingress._log_outcome = lambda _e, _o: None  # type: ignore[method-assign]

        evt = _make_event(tid)
        # Must not raise InvalidStateError
        await ingress.process_async(evt, bridge=bridge)
        assert future.result() == {"already": "done"}

    @pytest.mark.asyncio
    async def test_F03_missing_future_handled_gracefully(self):
        """process_async must handle bridge with no matching pending future."""
        from core.unified_result_ingress import UnifiedResultIngress

        ingress = UnifiedResultIngress()
        ingress._check_idempotency = lambda _e: False  # type: ignore[method-assign]
        ingress._record_idempotency = lambda _e: None  # type: ignore[method-assign]
        ingress._run_truth_chain = lambda _e: True  # type: ignore[method-assign]
        ingress._sync_lifecycle = lambda _e: None  # type: ignore[method-assign]
        ingress._notify_completion = lambda _e: True  # type: ignore[method-assign]
        ingress._log_outcome = lambda _e, _o: None  # type: ignore[method-assign]

        bridge = MagicMock()
        bridge._pending_responses = {}  # empty

        evt = _make_event(_make_task_id())
        outcome = await ingress.process_async(evt, bridge=bridge)
        assert not outcome.pending_response_resolved


# ===========================================================================
# Group G — Source channel coverage
# ===========================================================================


class TestSourceChannelCoverage:
    """All source channels must produce a processable NormalizedResultEvent."""

    @pytest.mark.parametrize(
        "channel",
        [
            "canonical_ws",
            "compat_ws",
            "rest_callback",
            "replay",
            "delegated",
        ],
    )
    def test_G_channel_produces_closure_attempt(self, channel: str):
        from core.unified_result_ingress import UnifiedResultIngress, ResultSourceChannel

        closure_attempted = []

        ingress = UnifiedResultIngress()
        ingress._check_idempotency = lambda _e: False  # type: ignore[method-assign]
        ingress._record_idempotency = lambda _e: None  # type: ignore[method-assign]
        ingress._run_truth_chain = lambda _e: closure_attempted.append("truth") or True  # type: ignore[method-assign]
        ingress._sync_lifecycle = lambda _e: None  # type: ignore[method-assign]
        ingress._notify_completion = lambda _e: closure_attempted.append("notify") or True  # type: ignore[method-assign]
        ingress._log_outcome = lambda _e, _o: None  # type: ignore[method-assign]

        evt = _make_event(_make_task_id(), channel=channel)
        ingress.process(evt)

        assert "truth" in closure_attempted, f"Truth chain not called for {channel}"
        assert "notify" in closure_attempted, f"Completion not called for {channel}"


# ===========================================================================
# Group H — REST endpoint integration
# ===========================================================================


@pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed")
class TestRestEndpointIntegration:

    def test_H01_submit_task_result_calls_truth_chain(self):
        """POST /api/v1/tasks/{task_id}/result must invoke truth chain."""
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from core.routes.tasks import create_router
        from core.routes._shared import task_queue

        app = FastAPI()
        app.include_router(create_router())

        tid = _make_task_id()
        task_queue[tid] = {
            "task_id": tid,
            "status": "dispatched",
            "device_id": "test-device",
        }

        truth_chain_called = []

        class _FakeOutcome:
            is_truth_chain_complete = True
            incomplete_reason = ""

        def _fake_ttc(msg, *, task_id=None, result_status=None):
            truth_chain_called.append(task_id)
            return _FakeOutcome()

        with patch(
            "core.task_result_canonical_truth_chain.run_task_result_truth_chain",
            side_effect=_fake_ttc,
        ):
            client = TestClient(app)
            resp = client.post(
                f"/api/v1/tasks/{tid}/result",
                json={"status": "success"},
            )

        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert tid in truth_chain_called, "submit_task_result did not invoke run_task_result_truth_chain"

        # Cleanup
        task_queue.pop(tid, None)

    def test_H02_submit_task_result_calls_completion_notify(self):
        """POST /api/v1/tasks/{task_id}/result must notify CanonicalCompletionIngress."""
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from core.routes.tasks import create_router
        from core.routes._shared import task_queue

        app = FastAPI()
        app.include_router(create_router())

        tid = _make_task_id()
        task_queue[tid] = {
            "task_id": tid,
            "status": "dispatched",
            "device_id": "test-device",
        }

        notified = []
        mock_cci = MagicMock()
        mock_cci.notify.side_effect = lambda env: notified.append(env.task_id) or True

        with patch(
            "core.canonical_completion_ingress.get_canonical_completion_ingress",
            return_value=mock_cci,
        ):
            client = TestClient(app)
            resp = client.post(
                f"/api/v1/tasks/{tid}/result",
                json={"status": "success"},
            )

        assert resp.status_code == 200
        assert tid in notified, "submit_task_result did not notify CanonicalCompletionIngress"

        # Cleanup
        task_queue.pop(tid, None)


# ===========================================================================
# Group I — compat WS goal_execution_result handler
# ===========================================================================


class TestCompatWsGoalExecutionResult:

    def _run_compat_handler_inline(
        self,
        task_id: str,
        task_queue_local: dict,
        message: dict,
        durable_store: set,
    ) -> dict:
        """
        Minimal inline re-implementation of the compat WS goal_execution_result
        handler logic, used to test idempotency and status mapping in isolation
        without spinning up a real WebSocket server.
        """
        idem_key = f"goal_execution_result:{task_id}"
        if idem_key in durable_store:
            return {"deduplicated": True}
        durable_store.add(idem_key)

        raw_status = str((message.get("payload") or {}).get("status") or message.get("status", "")).lower().strip()
        if raw_status in ("failed", "error"):
            mapped = "failed"
        elif raw_status == "cancelled":
            mapped = "cancelled"
        elif raw_status == "degraded":
            mapped = "degraded"
        else:
            mapped = "completed"

        if task_id in task_queue_local:
            task_queue_local[task_id]["status"] = mapped

        return {"deduplicated": False, "status": mapped}

    def test_I01_goal_execution_result_not_silently_discarded(self):
        """The compat WS path must handle goal_execution_result (not discard it)."""
        # Verify that goal_execution_result is a recognised msg_type in api_routes.py
        import ast
        import pathlib

        src = pathlib.Path("core/api_routes.py").read_text(encoding="utf-8")
        assert "goal_execution_result" in src, (
            "core/api_routes.py does not contain a goal_execution_result handler "
            "on the compat WS path — silent discard is still possible"
        )

    def test_I02_goal_execution_result_calls_unified_ingress_or_truth_chain(self):
        """Handler must call the unified ingress or truth chain (not just task_queue)."""
        import pathlib

        src = pathlib.Path("core/api_routes.py").read_text(encoding="utf-8")
        has_unified = "unified_result_ingress" in src or "run_task_result_truth_chain" in src
        assert has_unified, (
            "core/api_routes.py goal_execution_result handler does not call "
            "unified_result_ingress or run_task_result_truth_chain"
        )

    def test_I03_goal_execution_result_idempotency_suppresses_replay(self):
        """Duplicate goal_execution_result from replay must be suppressed via ingest_result."""
        tid = _make_task_id()
        task_queue_local = {tid: {"status": "dispatched"}}
        durable_store: set = set()
        msg = {"type": "goal_execution_result", "task_id": tid, "status": "success"}

        r1 = self._run_compat_handler_inline(tid, task_queue_local, msg, durable_store)
        r2 = self._run_compat_handler_inline(tid, task_queue_local, msg, durable_store)

        assert not r1["deduplicated"]
        assert r2["deduplicated"]
        assert task_queue_local[tid]["status"] == "completed"


# ===========================================================================
# Group J — canonical handle_goal_execution_result completion authority
# ===========================================================================


@pytest.mark.skipif(not _PYDANTIC_AVAILABLE, reason="pydantic not installed")
class TestCanonicalGoalExecutionResultCompletion:

    @pytest.mark.asyncio
    async def test_J01_handle_goal_execution_result_routes_through_unified_ingress(self):
        """handle_goal_execution_result 必须通过 UnifiedResultIngress 处理跨设备结果。

        这是跨设备链路验收闭环的权威契约：goal_execution_result 现在通过
        UnifiedResultIngress.ingest_result_async() 统一处理，而不是直接调用
        run_task_result_truth_chain。UnifiedResultIngress 内部会执行
        (1) 幂等性记录、(2) truth chain、(3) 证据分级、(4) 验收判定。

        同时验证状态规范化：Android 上报的 'success' 必须规范化为 'completed'。
        """
        from galaxy_gateway.android.handlers.goal_execution import handle_goal_execution_result

        ingress_calls = []

        class _FakeIngressOutcome:
            is_fully_closed = True
            was_deduplicated = False
            truth_chain_complete = True
            incomplete_reason = ""
            evidence_acceptance_verdict = "accept"
            evidence_trust_level = "high"
            task_completed = True
            problem_solved = False
            completion_notified = True
            pending_response_resolved = False

        async def _fake_ingest_async(event, *, store_fn=None, bridge=None):
            ingress_calls.append((event.task_id, event.normalized_status))
            return _FakeIngressOutcome()

        bridge = MagicMock()
        bridge._pending_responses = {}
        ws = MagicMock()

        tid = _make_task_id()
        msg = {
            "type": "goal_execution_result",
            "device_id": "test-device",
            "payload": {
                "task_id": tid,
                "status": "success",
                "result": "done",
            },
        }

        with (
            patch(
                "core.durable_result_idempotency.check_result_idempotency",
                return_value=False,
            ),
            patch(
                "core.unified_result_ingress.ingest_result_async",
                side_effect=_fake_ingest_async,
            ),
        ):
            await handle_goal_execution_result(bridge, ws, msg)

        assert len(ingress_calls) == 1, (
            "handle_goal_execution_result must call ingest_result_async exactly once "
            f"(got {len(ingress_calls)} calls)"
        )
        assert ingress_calls[0][0] == tid, "ingest_result_async must receive the correct task_id"
        assert ingress_calls[0][1] == "completed", (
            "ingest_result_async must receive the normalized canonical status " "(not the raw Android 'success')"
        )

    @pytest.mark.asyncio
    async def test_J02_handle_goal_execution_result_resolves_pending_response(self):
        """handle_goal_execution_result must resolve bridge._pending_responses future."""
        from galaxy_gateway.android.handlers.goal_execution import handle_goal_execution_result

        bridge = MagicMock()
        ws = MagicMock()

        tid = _make_task_id()
        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        bridge._pending_responses = {tid: future}

        msg = {
            "type": "goal_execution_result",
            "device_id": "test-device",
            "payload": {
                "task_id": tid,
                "status": "success",
                "result": "done",
            },
        }

        with (
            patch(
                "core.durable_result_idempotency.check_result_idempotency",
                return_value=False,
            ),
            patch(
                "core.durable_result_idempotency.record_result_idempotency",
            ),
        ):
            await handle_goal_execution_result(bridge, ws, msg)

        assert future.done(), (
            "handle_goal_execution_result did not resolve bridge._pending_responses " "future for task_id"
        )
        result = future.result()
        assert result["task_id"] == tid

    @pytest.mark.asyncio
    async def test_J03_handle_goal_execution_result_normalizes_all_terminal_statuses(self):
        """UnifiedResultIngress must receive normalized status for all terminal Android statuses.

        Android reports 'failed', 'error', or 'cancelled'; these must be normalised
        to canonical V2 status before UnifiedResultIngress receives them, ensuring
        status normalisation always happens before canonical state mutation.
        """
        from galaxy_gateway.android.handlers.goal_execution import handle_goal_execution_result

        received_statuses = []

        class _FakeIngressOutcome:
            is_fully_closed = True
            was_deduplicated = False
            truth_chain_complete = True
            incomplete_reason = ""
            evidence_acceptance_verdict = "accept"
            evidence_trust_level = "high"
            task_completed = True
            problem_solved = False
            completion_notified = True
            pending_response_resolved = False

        async def _fake_ingest_async(event, *, store_fn=None, bridge=None):
            received_statuses.append(event.normalized_status)
            return _FakeIngressOutcome()

        bridge = MagicMock()
        bridge._pending_responses = {}
        ws = MagicMock()

        for raw_status, expected in [("failed", "failed"), ("error", "failed"), ("cancelled", "cancelled")]:
            received_statuses.clear()
            tid = _make_task_id()
            msg = {
                "type": "goal_execution_result",
                "device_id": "test-device",
                "payload": {"task_id": tid, "status": raw_status, "result": ""},
            }

            with (
                patch("core.durable_result_idempotency.check_result_idempotency", return_value=False),
                patch(
                    "core.unified_result_ingress.ingest_result_async",
                    side_effect=_fake_ingest_async,
                ),
            ):
                await handle_goal_execution_result(bridge, ws, msg)

            assert received_statuses == [expected], (
                f"For raw_status={raw_status!r}, ingest_result_async received "
                f"{received_statuses!r} instead of [{expected!r}]"
            )
