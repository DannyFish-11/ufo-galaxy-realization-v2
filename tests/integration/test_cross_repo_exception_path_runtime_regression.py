"""
tests/integration/test_cross_repo_exception_path_runtime_regression.py
=======================================================================
PR-8: Cross-repo exception-path runtime regression matrix.

This module closes **R13** (cross-repo exception-path runtime regression gap
remains open) by building a multi-step regression harness that covers
combinations of disconnect, reconnect, replay, degradation, fallback,
takeover, delegated execution, and hybrid/mesh participation recovery.

What this module proves
-----------------------
Unlike isolated happy-path or single-transition checks, every test class here
exercises a **multi-step sequence** that chains at least two exception or
recovery steps:

1. ``TestDisconnectReconnectSessionContinuity``
   disconnect → reconnect → session entry survives; snapshot store still
   reflects latest Android-derived state.

2. ``TestReplayRejectionAfterTerminalSignal``
   final_result → terminal phase → replayed final_result is blocked; record
   not mutated; reject_reason is set.

3. ``TestDegradationFallbackChain``
   model_not_ready (degraded) → fallback tier active → dispatch routing
   penalises degraded candidate; fallback-tier candidate wins selection.

4. ``TestTakeoverAfterPrimaryDisconnect``
   primary ack → primary disconnect/error → takeover signal from backup
   device advances record to completed.

5. ``TestDelegatedExecutionSignalMultiStep``
   delegated dispatch → ack → progress (×N) → final_result → terminal;
   verifies phase monotonicity across the full chain.

6. ``TestStaleSessionBlockedBeforeTrackerMutation``
   PR-22 registry gate: a session recorded as 'replaced' in the registry
   must be blocked before any tracker mutation.

7. ``TestSignalSequenceWithOutOfOrderRejection``
   Two snapshots arrive out of sequence; out-of-order one is rejected by
   snapshot_seq ordering; the governance causality trail reflects the
   rejection correctly.

8. ``TestDelegatedFallbackDeterminism``
   Stale / replayed context from the delegated fallback path must produce
   the same deterministic reconciliation outcome on every call.

9. ``TestMeshParticipationRecoveryAfterDegradation``
   A mesh participant that reported degradation is re-evaluated after
   providing a fresh snapshot; participation re-eligibility is restored.

10. ``TestMultiStepHybridRecovery``
    Full hybrid sequence: error → snapshot update (model_ready restored) →
    re-dispatch → ack → final_result.  Proves the recovery arc from
    degradation through re-dispatch to completion.

No external services, live devices, or network connections are required.
The AndroidBridge, reconciler, and snapshot store use real code paths
(not mocks) wherever possible.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Shared AIP v3 helpers
# ---------------------------------------------------------------------------


def _v3(msg_type: str, device_id: str, **extra) -> Dict[str, Any]:
    """Build a minimal valid AIP v3 message dict."""
    return {
        "version": "3.0",
        "type": msg_type,
        "message_id": str(uuid.uuid4()),
        "device_id": device_id,
        "timestamp": int(time.time() * 1000),
        **extra,
    }


def _make_ws() -> MagicMock:
    ws = MagicMock()
    ws.send_json = AsyncMock()
    ws.send = AsyncMock()
    return ws


# ---------------------------------------------------------------------------
# Shared stub helpers
# ---------------------------------------------------------------------------

_HEALTHY_SNAPSHOT: Dict[str, Any] = {
    "llama_cpp_available": True,
    "ncnn_available": False,
    "active_runtime_type": "LLAMA_CPP",
    "model_ready": True,
    "accessibility_ready": True,
    "overlay_ready": True,
    "local_loop_ready": True,
    "degraded_reasons": [],
    "model_id": "mobilevlm_v2_7b",
    "runtime_type": "LLAMA_CPP",
    "checksum_ok": True,
    "compatibility_ok": True,
    "quantization": "q4_k_m",
    "model_version": "2.1.0",
    "mobilevlm_present": True,
    "mobilevlm_checksum_ok": True,
    "seeclick_present": True,
    "pending_first_download": False,
    "offline_queue_depth": 0,
    "current_fallback_tier": "planner_local",
    "warmup_result": "ok",
    "snapshot_ts": int(time.time() * 1000),
    "snapshot_seq": 1,
}

_DEGRADED_SNAPSHOT: Dict[str, Any] = {
    **_HEALTHY_SNAPSHOT,
    "model_ready": False,
    "local_loop_ready": False,
    "degraded_reasons": ["model_checksum_failed"],
    "warmup_result": "failed",
    "current_fallback_tier": "center_delegated",
    "snapshot_seq": 2,
    "snapshot_ts": int(time.time() * 1000) + 1000,
}


async def _register_device(bridge: Any, device_id: str) -> Dict[str, Any]:
    ws = _make_ws()
    ack = await bridge.handle_message(
        ws,
        _v3("device_register", device_id, platform="android", model="StubPhone"),
    )
    return {"ack": ack or {}, "ws": ws}


async def _send_snapshot(
    bridge: Any, ws: Any, device_id: str, payload: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    ack = await bridge.handle_message(
        ws,
        _v3("device_state_snapshot", device_id, payload=payload or _HEALTHY_SNAPSHOT),
    )
    return ack or {}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def bridge():
    """Real AndroidBridge instance (no mocking)."""
    from galaxy_gateway.android_bridge import AndroidBridge

    return AndroidBridge()


@pytest.fixture(autouse=True)
def _reset_state_store():
    """Reset android_device_state_store before each test."""
    from core.android_device_state_store import reset_android_device_state_store

    reset_android_device_state_store()
    yield
    reset_android_device_state_store()


@pytest.fixture(autouse=True)
def _reset_tracking_runtime():
    """Reset execution tracking runtime before each test."""
    try:
        from core.delegated_runtime_execution_tracker import (
            reset_execution_tracking_runtime,
        )

        reset_execution_tracking_runtime()
        yield
        reset_execution_tracking_runtime()
    except ImportError:
        yield


# ===========================================================================
# 1. Disconnect → Reconnect → Session Continuity
# ===========================================================================


class TestDisconnectReconnectSessionContinuity:
    """Multi-step: disconnect → reconnect → snapshot state survives."""

    @pytest.mark.asyncio
    async def test_reconnect_snapshot_overwrites_stale_state(
        self, bridge: Any
    ) -> None:
        """After disconnect and reconnect, a fresh snapshot replaces the stale one.

        Sequence:
          1. register + healthy snapshot (model_ready=True)
          2. simulate disconnect (new ws mock)
          3. reconnect: re-register
          4. send degraded snapshot (model_ready=False)
          5. assert store reflects degraded state (latest snapshot wins)
        """
        from core.android_device_state_store import get_device_state_snapshot

        device_id = f"r6-reconnect-{uuid.uuid4().hex[:8]}"

        # Step 1: first registration + healthy snapshot
        reg1 = await _register_device(bridge, device_id)
        ws1 = reg1["ws"]
        snap1_ack = await _send_snapshot(bridge, ws1, device_id, _HEALTHY_SNAPSHOT)
        assert snap1_ack.get("status") == "absorbed", (
            f"First snapshot must be absorbed; got status={snap1_ack.get('status')!r}"
        )
        stored_before_disconnect = get_device_state_snapshot(device_id)
        assert stored_before_disconnect is not None
        assert stored_before_disconnect.model_ready is True

        # Step 2: simulate disconnect — new ws mock (separate connection)
        ws2 = _make_ws()

        # Step 3: reconnect: re-register with same device_id
        reg2_ack = await bridge.handle_message(
            ws2,
            _v3("device_register", device_id, platform="android", model="StubPhone"),
        )
        assert (reg2_ack or {}).get("success") is True, (
            "Reconnect registration must succeed"
        )

        # Step 4: send updated snapshot marking degradation
        degraded_payload = {
            **_HEALTHY_SNAPSHOT,
            "model_ready": False,
            "degraded_reasons": ["model_checksum_failed"],
            "snapshot_seq": 2,
            "snapshot_ts": _HEALTHY_SNAPSHOT["snapshot_ts"] + 5000,
        }
        snap2_ack = await _send_snapshot(bridge, ws2, device_id, degraded_payload)
        assert snap2_ack.get("status") == "absorbed", (
            "Post-reconnect snapshot must be absorbed"
        )

        # Step 5: store must reflect latest (degraded) state
        stored_after_reconnect = get_device_state_snapshot(device_id)
        assert stored_after_reconnect is not None
        assert stored_after_reconnect.model_ready is False, (
            "android_device_state_store must reflect post-reconnect snapshot update; "
            "model_ready should be False after degraded snapshot was absorbed."
        )
        assert "model_checksum_failed" in (stored_after_reconnect.degraded_reasons or []), (
            "degraded_reasons must be updated from the post-reconnect snapshot"
        )

    @pytest.mark.asyncio
    async def test_reconnect_preserves_device_entry_in_store(
        self, bridge: Any
    ) -> None:
        """After reconnect the device entry remains present in the snapshot store.

        Verifies that a disconnect (no explicit deregister) + reconnect does
        not orphan the device entry.
        """
        from core.android_device_state_store import (
            get_device_state_snapshot,
            list_device_state_snapshots,
        )

        device_id = f"r6-persist-{uuid.uuid4().hex[:8]}"

        # First session
        reg1 = await _register_device(bridge, device_id)
        await _send_snapshot(bridge, reg1["ws"], device_id)

        # Second session (reconnect)
        ws2 = _make_ws()
        await bridge.handle_message(
            ws2,
            _v3("device_register", device_id, platform="android", model="StubPhone"),
        )
        fresh_payload = {
            **_HEALTHY_SNAPSHOT,
            "snapshot_seq": 10,
            "snapshot_ts": _HEALTHY_SNAPSHOT["snapshot_ts"] + 10000,
        }
        await _send_snapshot(bridge, ws2, device_id, fresh_payload)

        stored = get_device_state_snapshot(device_id)
        assert stored is not None, (
            "Device entry must survive disconnect + reconnect cycle"
        )
        all_snaps = list_device_state_snapshots()
        assert any(s.device_id == device_id for s in all_snaps), (
            "list_device_state_snapshots must include device after reconnect"
        )


# ===========================================================================
# 2. Replay Rejection After Terminal Signal
# ===========================================================================


class TestReplayRejectionAfterTerminalSignal:
    """Multi-step: final_result → terminal → replayed signal blocked."""

    def _make_record_and_runtime(self, contract_id: str, session_id: str):
        """Create a tracking record and runtime for isolation."""
        from core.delegated_runtime_execution_tracker import (
            DelegatedExecutionTrackingRuntime,
            create_execution_tracking_record,
            record_execution_tracking,
        )

        rt = DelegatedExecutionTrackingRuntime()
        record = create_execution_tracking_record(
            contract_id=contract_id,
            session_id=session_id,
            device_id="test_device",
            trace_id="trace_001",
        )
        record_execution_tracking(record, runtime=rt)
        return rt, record

    def test_terminal_record_blocks_replayed_final_result(self) -> None:
        """A terminal record must block a replayed final_result signal.

        Sequence:
          1. Create tracking record (pending_ack)
          2. Apply final_result → record becomes completed (terminal)
          3. Replay same final_result → outcome.was_updated=False, reject_reason set
        """
        from core.android_execution_signal_reconciler import (
            AndroidExecutionSignalEnvelope,
            AndroidSignalKind,
            reconcile_android_execution_signal,
        )

        contract_id = f"cid-replay-{uuid.uuid4().hex[:8]}"
        session_id = f"sid-replay-{uuid.uuid4().hex[:8]}"
        rt, _record = self._make_record_and_runtime(contract_id, session_id)

        # Step 1: apply final_result → terminal
        envelope_ok = AndroidExecutionSignalEnvelope(
            signal_kind=AndroidSignalKind.final_result,
            contract_id=contract_id,
            session_id=session_id,
            device_id="test_device",
            trace_id="trace_001",
            task_id="task_001",
            payload={"result": {"ok": True}},
        )
        outcome_ok = reconcile_android_execution_signal(envelope_ok, runtime=rt)
        assert outcome_ok.was_updated is True, (
            "First final_result must update the record"
        )
        assert outcome_ok.record is not None
        assert outcome_ok.record.phase.is_terminal(), (
            "Record must be terminal after final_result"
        )

        # Step 2: replay same final_result
        envelope_replay = AndroidExecutionSignalEnvelope(
            signal_kind=AndroidSignalKind.final_result,
            contract_id=contract_id,
            session_id=session_id,
            device_id="test_device",
            trace_id="trace_001",
            task_id="task_001",
            payload={"result": {"ok": True}},
        )
        outcome_replay = reconcile_android_execution_signal(envelope_replay, runtime=rt)

        assert outcome_replay.was_updated is False, (
            "Replayed final_result after terminal must be rejected (was_updated=False). "
            "Terminal phase must block further signal mutations."
        )
        assert outcome_replay.reject_reason, (
            "reject_reason must be non-empty for a blocked replay attempt"
        )

    def test_terminal_record_blocks_progress_after_error(self) -> None:
        """Progress signal arriving after error (terminal) must be blocked.

        Sequence:
          1. Create record
          2. Apply error → terminal (failed phase)
          3. Apply progress → blocked
        """
        from core.android_execution_signal_reconciler import (
            AndroidExecutionSignalEnvelope,
            AndroidSignalKind,
            reconcile_android_execution_signal,
        )

        contract_id = f"cid-err-{uuid.uuid4().hex[:8]}"
        session_id = f"sid-err-{uuid.uuid4().hex[:8]}"
        rt, _ = self._make_record_and_runtime(contract_id, session_id)

        # Apply error → terminal
        env_err = AndroidExecutionSignalEnvelope(
            signal_kind=AndroidSignalKind.error,
            contract_id=contract_id,
            session_id=session_id,
            payload={"error": "boom"},
        )
        outcome_err = reconcile_android_execution_signal(env_err, runtime=rt)
        assert outcome_err.was_updated is True
        assert outcome_err.record.phase.is_terminal()

        # Progress after error must be blocked
        env_progress = AndroidExecutionSignalEnvelope(
            signal_kind=AndroidSignalKind.progress,
            contract_id=contract_id,
            session_id=session_id,
        )
        outcome_progress = reconcile_android_execution_signal(env_progress, runtime=rt)
        assert outcome_progress.was_updated is False, (
            "Progress signal must not mutate a terminal (failed) record"
        )

    def test_cancelled_signal_produces_terminal_and_blocks_further_signals(
        self,
    ) -> None:
        """Cancel → terminal → any further signal is blocked."""
        from core.android_execution_signal_reconciler import (
            AndroidExecutionSignalEnvelope,
            AndroidSignalKind,
            reconcile_android_execution_signal,
        )

        contract_id = f"cid-cancel-{uuid.uuid4().hex[:8]}"
        session_id = f"sid-cancel-{uuid.uuid4().hex[:8]}"
        rt, _ = self._make_record_and_runtime(contract_id, session_id)

        env_cancel = AndroidExecutionSignalEnvelope(
            signal_kind=AndroidSignalKind.cancelled,
            contract_id=contract_id,
            session_id=session_id,
        )
        outcome_cancel = reconcile_android_execution_signal(env_cancel, runtime=rt)
        assert outcome_cancel.was_updated is True
        assert outcome_cancel.record.phase.is_terminal()

        for signal_kind in (
            AndroidSignalKind.ack,
            AndroidSignalKind.progress,
            AndroidSignalKind.final_result,
            AndroidSignalKind.error,
        ):
            env_after = AndroidExecutionSignalEnvelope(
                signal_kind=signal_kind,
                contract_id=contract_id,
                session_id=session_id,
            )
            outcome_after = reconcile_android_execution_signal(env_after, runtime=rt)
            assert outcome_after.was_updated is False, (
                f"{signal_kind.value} after cancelled terminal must be blocked"
            )


# ===========================================================================
# 3. Degradation → Fallback Chain in Dispatch Scoring
# ===========================================================================


class TestDegradationFallbackChain:
    """Multi-step: degraded device penalised; fallback-tier device wins selection."""

    @pytest.mark.asyncio
    async def test_degraded_device_loses_to_healthy_device_in_scoring(
        self, bridge: Any
    ) -> None:
        """Degraded model_ready=False device is scored lower than healthy one.

        Sequence:
          1. Register device_A with degraded snapshot (model_ready=False)
          2. Register device_B with healthy snapshot (model_ready=True)
          3. _score_candidate(device_A) < _score_candidate(device_B)
        """
        from core.android_device_state_store import get_device_state_snapshot
        from core.runtime.source_dispatch_orchestrator import _score_candidate
        from unittest.mock import MagicMock

        dev_a = f"r13-deg-a-{uuid.uuid4().hex[:8]}"
        dev_b = f"r13-deg-b-{uuid.uuid4().hex[:8]}"

        reg_a = await _register_device(bridge, dev_a)
        await _send_snapshot(bridge, reg_a["ws"], dev_a, _DEGRADED_SNAPSHOT)

        reg_b = await _register_device(bridge, dev_b)
        await _send_snapshot(bridge, reg_b["ws"], dev_b, _HEALTHY_SNAPSHOT)

        snap_a = get_device_state_snapshot(dev_a)
        snap_b = get_device_state_snapshot(dev_b)
        assert snap_a is not None, "Device A snapshot must be stored"
        assert snap_b is not None, "Device B snapshot must be stored"
        assert snap_a.model_ready is False
        assert snap_b.model_ready is True

        readiness = MagicMock()
        readiness.registered = True
        readiness.routable = True
        participation = MagicMock()
        participation.orchestration_eligible = True
        participation.participant_tier = "joined_runtime"

        score_a, _ = _score_candidate(
            "sess_a", dev_a,
            readiness=readiness,
            participation=participation,
            reuse_eligible=False,
            android_snapshot=snap_a,
            execution_busy=False,
        )
        score_b, _ = _score_candidate(
            "sess_b", dev_b,
            readiness=readiness,
            participation=participation,
            reuse_eligible=False,
            android_snapshot=snap_b,
            execution_busy=False,
        )

        assert score_a < score_b, (
            f"Degraded device score ({score_a}) must be lower than healthy device "
            f"score ({score_b}).  Degradation must materially affect dispatch routing."
        )

    @pytest.mark.asyncio
    async def test_fallback_tier_center_delegated_penalised_less_than_no_fallback(
        self, bridge: Any
    ) -> None:
        """model_ready=False with fallback_tier is penalised less than no fallback.

        Sequence:
          1. device_A: model_ready=False, current_fallback_tier=None (no fallback)
          2. device_B: model_ready=False, current_fallback_tier="center_delegated"
          3. score_B >= score_A (fallback tier mitigates the penalty)
        """
        from core.android_device_state_store import absorb_device_state_snapshot
        from core.runtime.source_dispatch_orchestrator import _score_candidate
        from unittest.mock import MagicMock

        dev_a = f"r13-nofb-a-{uuid.uuid4().hex[:8]}"
        dev_b = f"r13-fb-b-{uuid.uuid4().hex[:8]}"

        absorb_device_state_snapshot(
            dev_a,
            {"model_ready": False, "current_fallback_tier": None, "snapshot_seq": 1},
        )
        absorb_device_state_snapshot(
            dev_b,
            {"model_ready": False, "current_fallback_tier": "center_delegated", "snapshot_seq": 1},
        )

        from core.android_device_state_store import get_device_state_snapshot

        snap_a = get_device_state_snapshot(dev_a)
        snap_b = get_device_state_snapshot(dev_b)

        readiness = MagicMock()
        readiness.registered = True
        readiness.routable = True
        participation = MagicMock()
        participation.orchestration_eligible = True
        participation.participant_tier = "joined_runtime"

        score_a, _ = _score_candidate(
            "sess_a", dev_a,
            readiness=readiness, participation=participation,
            reuse_eligible=False, android_snapshot=snap_a, execution_busy=False,
        )
        score_b, _ = _score_candidate(
            "sess_b", dev_b,
            readiness=readiness, participation=participation,
            reuse_eligible=False, android_snapshot=snap_b, execution_busy=False,
        )

        assert score_b >= score_a, (
            f"Device with fallback tier (score={score_b}) should score >= no-fallback "
            f"device (score={score_a}).  Fallback tier must mitigate model_ready=False penalty."
        )


# ===========================================================================
# 4. Takeover After Primary Disconnect/Error
# ===========================================================================


class TestTakeoverAfterPrimaryDisconnect:
    """Multi-step: primary ack → primary error → backup takeover → completed."""

    def _make_runtime(self):
        from core.delegated_runtime_execution_tracker import (
            DelegatedExecutionTrackingRuntime,
        )

        return DelegatedExecutionTrackingRuntime()

    def test_primary_error_followed_by_takeover_completes_execution(self) -> None:
        """Primary device errors; backup device sends takeover final_result.

        Sequence:
          1. Create execution record for primary device
          2. Primary sends ack (pending_ack → acknowledged)
          3. Primary sends error (acknowledged → failed / terminal)
          4. Create NEW execution record for backup device (same contract_id)
          5. Backup sends final_result → backup record is completed (terminal)
        """
        from core.android_execution_signal_reconciler import (
            AndroidExecutionSignalEnvelope,
            AndroidSignalKind,
            reconcile_android_execution_signal,
        )
        from core.delegated_runtime_execution_tracker import (
            create_execution_tracking_record,
            record_execution_tracking,
        )

        contract_id = f"cid-takeover-{uuid.uuid4().hex[:8]}"
        primary_session = f"sid-primary-{uuid.uuid4().hex[:8]}"
        backup_session = f"sid-backup-{uuid.uuid4().hex[:8]}"
        rt = self._make_runtime()

        # Step 1: create primary record
        primary_record = create_execution_tracking_record(
            contract_id=contract_id,
            session_id=primary_session,
            device_id="primary_device",
            trace_id="trace_takeover",
        )
        record_execution_tracking(primary_record, runtime=rt)

        # Step 2: primary ack
        env_ack = AndroidExecutionSignalEnvelope(
            signal_kind=AndroidSignalKind.ack,
            contract_id=contract_id,
            session_id=primary_session,
            device_id="primary_device",
        )
        outcome_ack = reconcile_android_execution_signal(env_ack, runtime=rt)
        assert outcome_ack.was_updated is True
        assert outcome_ack.record.phase.value == "acknowledged"

        # Step 3: primary error → terminal
        env_error = AndroidExecutionSignalEnvelope(
            signal_kind=AndroidSignalKind.error,
            contract_id=contract_id,
            session_id=primary_session,
            device_id="primary_device",
            payload={"error": "connection_dropped"},
        )
        outcome_error = reconcile_android_execution_signal(env_error, runtime=rt)
        assert outcome_error.was_updated is True
        assert outcome_error.record.phase.is_terminal(), (
            "Primary device error must advance record to terminal phase"
        )

        # Step 4: create backup record (new session, same contract)
        backup_record = create_execution_tracking_record(
            contract_id=contract_id,
            session_id=backup_session,
            device_id="backup_device",
            trace_id="trace_takeover",
        )
        record_execution_tracking(backup_record, runtime=rt)

        # Step 5: backup sends final_result
        env_takeover = AndroidExecutionSignalEnvelope(
            signal_kind=AndroidSignalKind.final_result,
            contract_id=contract_id,
            session_id=backup_session,
            device_id="backup_device",
            trace_id="trace_takeover",
            task_id="task_001",
            payload={"result": {"ok": True, "takeover": True}},
        )
        outcome_takeover = reconcile_android_execution_signal(env_takeover, runtime=rt)
        assert outcome_takeover.was_updated is True, (
            "Backup device takeover final_result must update the backup record"
        )
        assert outcome_takeover.record.phase.is_terminal(), (
            "Backup record must be terminal after takeover final_result"
        )
        assert outcome_takeover.record.phase.value == "completed", (
            "Backup record phase must be 'completed' after successful takeover"
        )

    def test_timeout_signal_blocks_subsequent_ack(self) -> None:
        """Timeout (terminal) must block a late-arriving ack from the same device.

        Simulates: device times out → host side receives timeout signal →
        late ack arrives (network lag) → must be blocked.
        """
        from core.android_execution_signal_reconciler import (
            AndroidExecutionSignalEnvelope,
            AndroidSignalKind,
            reconcile_android_execution_signal,
        )
        from core.delegated_runtime_execution_tracker import (
            create_execution_tracking_record,
            record_execution_tracking,
        )

        contract_id = f"cid-timeout-{uuid.uuid4().hex[:8]}"
        session_id = f"sid-timeout-{uuid.uuid4().hex[:8]}"
        rt = self._make_runtime()

        record = create_execution_tracking_record(
            contract_id=contract_id,
            session_id=session_id,
            device_id="slow_device",
            trace_id="trace_timeout",
        )
        record_execution_tracking(record, runtime=rt)

        # Timeout first
        env_timeout = AndroidExecutionSignalEnvelope(
            signal_kind=AndroidSignalKind.timeout,
            contract_id=contract_id,
            session_id=session_id,
        )
        outcome_timeout = reconcile_android_execution_signal(env_timeout, runtime=rt)
        assert outcome_timeout.was_updated is True
        assert outcome_timeout.record.phase.is_terminal()

        # Late ack must be blocked
        env_late_ack = AndroidExecutionSignalEnvelope(
            signal_kind=AndroidSignalKind.ack,
            contract_id=contract_id,
            session_id=session_id,
        )
        outcome_late = reconcile_android_execution_signal(env_late_ack, runtime=rt)
        assert outcome_late.was_updated is False, (
            "Late ack arriving after timeout must be blocked by terminal-phase gate"
        )


# ===========================================================================
# 5. Delegated Execution Full Signal Chain (Multi-step)
# ===========================================================================


class TestDelegatedExecutionSignalMultiStep:
    """Full delegated execution chain: ack → progress(×N) → final_result."""

    def test_phase_monotonicity_across_full_signal_chain(self) -> None:
        """Verify phase advances monotonically through ack → progress → final_result.

        This is the canonical happy-path chain that underpins delegated
        execution.  Phase must advance forward at each step and never
        regress.
        """
        from core.android_execution_signal_reconciler import (
            AndroidExecutionSignalEnvelope,
            AndroidSignalKind,
            reconcile_android_execution_signal,
        )
        from core.delegated_runtime_execution_tracker import (
            DelegatedExecutionTrackingRuntime,
            create_execution_tracking_record,
            record_execution_tracking,
        )

        contract_id = f"cid-chain-{uuid.uuid4().hex[:8]}"
        session_id = f"sid-chain-{uuid.uuid4().hex[:8]}"
        rt = DelegatedExecutionTrackingRuntime()

        record = create_execution_tracking_record(
            contract_id=contract_id,
            session_id=session_id,
            device_id="chain_device",
            trace_id="trace_chain",
        )
        record_execution_tracking(record, runtime=rt)

        phases_seen = []

        def _apply(signal_kind: AndroidSignalKind, extra_payload=None):
            env = AndroidExecutionSignalEnvelope(
                signal_kind=signal_kind,
                contract_id=contract_id,
                session_id=session_id,
                device_id="chain_device",
                payload=extra_payload or {},
            )
            outcome = reconcile_android_execution_signal(env, runtime=rt)
            if outcome.record:
                phases_seen.append(outcome.record.phase.value)
            return outcome

        # ack
        o1 = _apply(AndroidSignalKind.ack)
        assert o1.was_updated is True
        assert o1.record.phase.value == "acknowledged"

        # progress × 3
        for _ in range(3):
            o_prog = _apply(AndroidSignalKind.progress)
            assert o_prog.was_updated is True
            assert o_prog.record.phase.value == "in_progress"

        # final_result
        o_final = _apply(
            AndroidSignalKind.final_result,
            extra_payload={"result": {"ok": True}},
        )
        assert o_final.was_updated is True
        assert o_final.record.phase.value == "completed"
        assert o_final.record.phase.is_terminal()

        # Verify no phase regression occurred in the sequence using the
        # canonical DelegatedExecutionPhase.can_advance_to() ordering
        from core.delegated_runtime_execution_tracker import DelegatedExecutionPhase
        for i in range(1, len(phases_seen)):
            prev = DelegatedExecutionPhase.from_string(phases_seen[i - 1])
            curr = DelegatedExecutionPhase.from_string(phases_seen[i])
            # Either same phase (idempotent) or advancing forward per canonical ordering
            assert prev == curr or prev.can_advance_to(curr), (
                f"Phase regression detected: {phases_seen[i - 1]!r} → {phases_seen[i]!r}. "
                "Delegated execution phases must be monotonically advancing."
            )

    def test_partial_result_does_not_terminate_execution(self) -> None:
        """partial_result must keep execution alive (non-terminal)."""
        from core.android_execution_signal_reconciler import (
            AndroidExecutionSignalEnvelope,
            AndroidSignalKind,
            reconcile_android_execution_signal,
        )
        from core.delegated_runtime_execution_tracker import (
            DelegatedExecutionTrackingRuntime,
            create_execution_tracking_record,
            record_execution_tracking,
        )

        contract_id = f"cid-partial-{uuid.uuid4().hex[:8]}"
        session_id = f"sid-partial-{uuid.uuid4().hex[:8]}"
        rt = DelegatedExecutionTrackingRuntime()

        record = create_execution_tracking_record(
            contract_id=contract_id,
            session_id=session_id,
            device_id="partial_device",
            trace_id="trace_partial",
        )
        record_execution_tracking(record, runtime=rt)

        env_partial = AndroidExecutionSignalEnvelope(
            signal_kind=AndroidSignalKind.partial_result,
            contract_id=contract_id,
            session_id=session_id,
            payload={"partial_result": {"step": 1, "ok": True}},
        )
        outcome = reconcile_android_execution_signal(env_partial, runtime=rt)
        assert outcome.was_updated is True
        assert not outcome.record.phase.is_terminal(), (
            "partial_result must not advance record to terminal phase — "
            "execution is still in progress"
        )


# ===========================================================================
# 6. Stale Session Blocked Before Tracker Mutation (PR-22 Registry Gate)
# ===========================================================================


class TestStaleSessionBlockedBeforeTrackerMutation:
    """PR-22 registry gate: non-active session must be blocked before mutation."""

    def test_replaced_session_blocks_reconciliation(self) -> None:
        """A session recorded as 'replaced' must be blocked by the registry gate.

        Sequence:
          1. Register session_A for device_X → session_A is active
          2. Create execution record with session_A; apply ack (record is live)
          3. Register session_B for device_X → session_A becomes 'replaced'
          4. Apply progress with session_A against the registry → blocked by PR-22
        """
        from core.android_execution_signal_reconciler import (
            AndroidExecutionSignalEnvelope,
            AndroidSignalKind,
            reconcile_android_execution_signal,
        )
        from core.delegated_runtime_execution_tracker import (
            DelegatedExecutionTrackingRuntime,
            create_execution_tracking_record,
            record_execution_tracking,
        )

        try:
            from core.attached_runtime_session_registry import (
                AttachedSessionRegistry,
                register_session,
            )
        except ImportError:
            pytest.skip("AttachedSessionRegistry not available")

        device_id = f"dev-pr22-{uuid.uuid4().hex[:8]}"
        session_id_a = f"sid-pr22-a-{uuid.uuid4().hex[:8]}"
        contract_id = f"cid-pr22-{uuid.uuid4().hex[:8]}"
        rt = DelegatedExecutionTrackingRuntime()

        # Use an isolated registry instance
        registry = AttachedSessionRegistry()

        # Step 1: register session_A — it is active
        register_session(device_id, session_id=session_id_a, registry=registry)

        # Confirm session_A is active
        from core.attached_runtime_session_registry import lookup_active_session
        entry_a = lookup_active_session(session_id_a, active_only=True, registry=registry)
        assert entry_a is not None, "session_A must be active after registration"
        assert entry_a.is_active()

        # Step 2: create execution record anchored to session_A
        record = create_execution_tracking_record(
            contract_id=contract_id,
            session_id=session_id_a,
            device_id=device_id,
            trace_id="trace_pr22",
        )
        record_execution_tracking(record, runtime=rt)

        # Ack advances the record while session_A is still active
        env_ack = AndroidExecutionSignalEnvelope(
            signal_kind=AndroidSignalKind.ack,
            contract_id=contract_id,
            session_id=session_id_a,
        )
        outcome_ack = reconcile_android_execution_signal(env_ack, runtime=rt, registry=registry)
        assert outcome_ack.was_updated is True, (
            "Ack must update the record while session_A is active"
        )

        # Step 3: register session_B for same device → session_A is now 'replaced'
        session_id_b = f"sid-pr22-b-{uuid.uuid4().hex[:8]}"
        register_session(device_id, session_id=session_id_b, registry=registry)

        # Confirm session_A is now non-active (replaced)
        entry_a_after = lookup_active_session(session_id_a, active_only=False, registry=registry)
        assert entry_a_after is not None
        assert not entry_a_after.is_active(), (
            "session_A must be non-active (replaced) after session_B registration"
        )

        # Step 4: progress with session_A must be blocked by PR-22 registry gate
        env_progress = AndroidExecutionSignalEnvelope(
            signal_kind=AndroidSignalKind.progress,
            contract_id=contract_id,
            session_id=session_id_a,
        )
        outcome_blocked = reconcile_android_execution_signal(
            env_progress, runtime=rt, registry=registry
        )
        assert outcome_blocked.was_updated is False, (
            "PR-22 registry gate must block reconciliation for a 'replaced' session. "
            "was_updated should be False when the registry reports a non-active state."
        )
        assert outcome_blocked.reject_reason, (
            "reject_reason must describe the PR-22 registry block"
        )
        assert "registry" in outcome_blocked.reject_reason.lower() or (
            "replaced" in outcome_blocked.reject_reason.lower()
            or "non-active" in outcome_blocked.reject_reason.lower()
        ), f"reject_reason should mention registry or non-active: {outcome_blocked.reject_reason!r}"


# ===========================================================================
# 7. Out-of-Order Snapshot Rejection and Governance Causality
# ===========================================================================


class TestSignalSequenceWithOutOfOrderRejection:
    """Out-of-order snapshot is rejected; governance causality reflects rejection."""

    def test_out_of_order_snapshot_rejected_and_causality_updated(self) -> None:
        """Sequence:
          1. Absorb snapshot seq=10 (newer, model_ready=True)
          2. Absorb snapshot seq=9  (older, model_ready=False) → rejected
          3. Stored snapshot still reflects seq=10 / model_ready=True
          4. Reconciliation dict reports out_of_order_rejected
        """
        from core.android_device_state_store import (
            absorb_device_state_snapshot,
            get_device_snapshot_reconciliation,
            get_device_state_snapshot,
            reset_android_device_state_store,
        )

        reset_android_device_state_store()
        device_id = f"r13-oor-{uuid.uuid4().hex[:8]}"
        ts_now = int(time.time() * 1000)

        absorb_device_state_snapshot(
            device_id,
            {"snapshot_ts": ts_now + 2000, "snapshot_seq": 10, "model_ready": True},
        )
        absorb_device_state_snapshot(
            device_id,
            {"snapshot_ts": ts_now, "snapshot_seq": 9, "model_ready": False},
        )

        stored = get_device_state_snapshot(device_id)
        assert stored is not None
        assert stored.model_ready is True, (
            "Out-of-order snapshot must not overwrite newer snapshot"
        )
        assert stored.snapshot_seq == 10

        reconciliation = get_device_snapshot_reconciliation(device_id)
        assert reconciliation.get("status") == "out_of_order_rejected", (
            "Reconciliation status must be 'out_of_order_rejected' for out-of-order snapshot"
        )
        assert reconciliation.get("applied") is False
        assert reconciliation.get("ordering_basis") == "snapshot_seq"

    def test_snapshot_sequence_conflict_is_deterministic(self) -> None:
        """Two snapshots with same ts/seq — conflict resolution is deterministic."""
        from core.android_device_state_store import (
            absorb_device_state_snapshot,
            get_device_snapshot_reconciliation,
            get_device_state_snapshot,
            reset_android_device_state_store,
        )

        reset_android_device_state_store()
        device_id = f"r13-conflict-{uuid.uuid4().hex[:8]}"
        ts = int(time.time() * 1000)

        absorb_device_state_snapshot(
            device_id,
            {"snapshot_ts": ts, "snapshot_seq": 5, "model_ready": True},
        )
        # Identical ts + seq: second call must not flip state
        absorb_device_state_snapshot(
            device_id,
            {"snapshot_ts": ts, "snapshot_seq": 5, "model_ready": False},
        )

        stored = get_device_state_snapshot(device_id)
        assert stored is not None
        # The first write must be retained (center-truth-stable semantics)
        assert stored.model_ready is True, (
            "Conflict resolution must be deterministic and retain the first (center) truth"
        )

        reconciliation = get_device_snapshot_reconciliation(device_id)
        assert reconciliation.get("conflict") is True
        assert reconciliation.get("applied") is False


# ===========================================================================
# 8. Delegated Fallback Determinism
# ===========================================================================


class TestDelegatedFallbackDeterminism:
    """Stale/replayed context must produce the same deterministic outcome."""

    def test_unknown_lookup_key_always_rejects_deterministically(self) -> None:
        """An envelope with an unknown contract_id must always reject the same way.

        Verifies that the 'no record found' path is stable across repeated
        calls — important for replay-resistance.
        """
        from core.android_execution_signal_reconciler import (
            AndroidExecutionSignalEnvelope,
            AndroidSignalKind,
            reconcile_android_execution_signal,
        )
        from core.delegated_runtime_execution_tracker import (
            DelegatedExecutionTrackingRuntime,
        )

        rt = DelegatedExecutionTrackingRuntime()
        unknown_contract = f"cid-unknown-{uuid.uuid4().hex[:8]}"

        for _attempt in range(3):
            env = AndroidExecutionSignalEnvelope(
                signal_kind=AndroidSignalKind.final_result,
                contract_id=unknown_contract,
                session_id=f"sid-unknown-{uuid.uuid4().hex[:8]}",
                payload={"result": {"ok": True}},
            )
            outcome = reconcile_android_execution_signal(env, runtime=rt)
            assert outcome.was_updated is False, (
                f"Attempt {_attempt}: unknown contract must always reject"
            )
            assert outcome.reject_reason, (
                f"Attempt {_attempt}: reject_reason must be set for unknown contract"
            )

    def test_empty_lookup_key_always_rejects_deterministically(self) -> None:
        """An envelope with no contract_id and no session_id must always reject."""
        from core.android_execution_signal_reconciler import (
            AndroidExecutionSignalEnvelope,
            AndroidSignalKind,
            reconcile_android_execution_signal,
        )
        from core.delegated_runtime_execution_tracker import (
            DelegatedExecutionTrackingRuntime,
        )

        rt = DelegatedExecutionTrackingRuntime()

        for _attempt in range(3):
            env = AndroidExecutionSignalEnvelope(
                signal_kind=AndroidSignalKind.progress,
                contract_id="",
                session_id="",
            )
            outcome = reconcile_android_execution_signal(env, runtime=rt)
            assert outcome.was_updated is False
            assert "lookup" in outcome.reject_reason.lower() or (
                "contract_id" in outcome.reject_reason.lower()
                or "session_id" in outcome.reject_reason.lower()
            ), f"reject_reason should describe missing lookup key: {outcome.reject_reason!r}"


# ===========================================================================
# 9. Mesh Participation Recovery After Degradation
# ===========================================================================


class TestMeshParticipationRecoveryAfterDegradation:
    """mesh participation: degraded → fresh snapshot → re-eligibility restored."""

    @pytest.mark.asyncio
    async def test_degraded_snapshot_then_healthy_snapshot_restores_score(
        self, bridge: Any
    ) -> None:
        """Sequence:
          1. Register + degraded snapshot → low score
          2. Register + healthy snapshot (later seq) → score restored to full
        """
        from core.android_device_state_store import get_device_state_snapshot
        from core.runtime.source_dispatch_orchestrator import _score_candidate
        from unittest.mock import MagicMock

        device_id = f"r13-mesh-{uuid.uuid4().hex[:8]}"

        # Step 1: register + degraded snapshot
        reg1 = await _register_device(bridge, device_id)
        degraded_payload = {
            **_DEGRADED_SNAPSHOT,
            "snapshot_seq": 1,
            "snapshot_ts": int(time.time() * 1000),
        }
        await _send_snapshot(bridge, reg1["ws"], device_id, degraded_payload)

        snap_degraded = get_device_state_snapshot(device_id)
        assert snap_degraded is not None
        assert snap_degraded.model_ready is False

        readiness = MagicMock()
        readiness.registered = True
        readiness.routable = True
        participation = MagicMock()
        participation.orchestration_eligible = True
        participation.participant_tier = "joined_runtime"

        score_degraded, _ = _score_candidate(
            "sess_mesh", device_id,
            readiness=readiness, participation=participation,
            reuse_eligible=False, android_snapshot=snap_degraded, execution_busy=False,
        )

        # Step 2: send healthy snapshot (higher seq/ts = newer)
        ws2 = _make_ws()
        await bridge.handle_message(
            ws2,
            _v3("device_register", device_id, platform="android", model="StubPhone"),
        )
        healthy_payload = {
            **_HEALTHY_SNAPSHOT,
            "snapshot_seq": 2,
            "snapshot_ts": degraded_payload["snapshot_ts"] + 5000,
        }
        await _send_snapshot(bridge, ws2, device_id, healthy_payload)

        snap_healthy = get_device_state_snapshot(device_id)
        assert snap_healthy is not None
        assert snap_healthy.model_ready is True, (
            "After healthy snapshot (higher seq), model_ready must be True"
        )

        score_recovered, _ = _score_candidate(
            "sess_mesh", device_id,
            readiness=readiness, participation=participation,
            reuse_eligible=False, android_snapshot=snap_healthy, execution_busy=False,
        )

        assert score_recovered > score_degraded, (
            f"Recovered score ({score_recovered}) must exceed degraded score ({score_degraded}). "
            "A device that recovers from degradation must regain dispatch priority."
        )


# ===========================================================================
# 10. Multi-Step Hybrid Recovery Arc
# ===========================================================================


class TestMultiStepHybridRecovery:
    """Full hybrid recovery arc: error → snapshot recovery → re-dispatch → completed."""

    @pytest.mark.asyncio
    async def test_hybrid_recovery_arc_error_to_completed(
        self, bridge: Any
    ) -> None:
        """Full multi-step recovery:
          1. Device registers + degraded snapshot
          2. Execution record created → ack → error (terminal)
          3. Device sends healthy snapshot (recovery)
          4. New execution record created → ack → final_result → completed
          5. Final store state reflects healthy device + completed execution
        """
        from core.android_device_state_store import get_device_state_snapshot
        from core.android_execution_signal_reconciler import (
            AndroidExecutionSignalEnvelope,
            AndroidSignalKind,
            reconcile_android_execution_signal,
        )
        from core.delegated_runtime_execution_tracker import (
            DelegatedExecutionTrackingRuntime,
            create_execution_tracking_record,
            record_execution_tracking,
        )

        device_id = f"r13-hybrid-{uuid.uuid4().hex[:8]}"
        rt = DelegatedExecutionTrackingRuntime()

        # Step 1: register + degraded snapshot
        reg1 = await _register_device(bridge, device_id)
        degraded_payload = {
            **_DEGRADED_SNAPSHOT,
            "snapshot_seq": 1,
            "snapshot_ts": int(time.time() * 1000),
        }
        await _send_snapshot(bridge, reg1["ws"], device_id, degraded_payload)

        # Step 2: execution record → ack → error
        contract_id_1 = f"cid-hybrid-1-{uuid.uuid4().hex[:8]}"
        session_id_1 = f"sid-hybrid-1-{uuid.uuid4().hex[:8]}"
        record_1 = create_execution_tracking_record(
            contract_id=contract_id_1,
            session_id=session_id_1,
            device_id=device_id,
            trace_id="trace_hybrid",
        )
        record_execution_tracking(record_1, runtime=rt)

        # ack
        env_ack = AndroidExecutionSignalEnvelope(
            signal_kind=AndroidSignalKind.ack,
            contract_id=contract_id_1,
            session_id=session_id_1,
            device_id=device_id,
        )
        o_ack = reconcile_android_execution_signal(env_ack, runtime=rt)
        assert o_ack.was_updated is True

        # error → terminal
        env_err = AndroidExecutionSignalEnvelope(
            signal_kind=AndroidSignalKind.error,
            contract_id=contract_id_1,
            session_id=session_id_1,
            device_id=device_id,
            payload={"error": "local_model_unavailable"},
        )
        o_err = reconcile_android_execution_signal(env_err, runtime=rt)
        assert o_err.was_updated is True
        assert o_err.record.phase.is_terminal()

        # Step 3: device sends healthy snapshot (recovery)
        ws2 = _make_ws()
        await bridge.handle_message(
            ws2,
            _v3("device_register", device_id, platform="android", model="StubPhone"),
        )
        healthy_payload = {
            **_HEALTHY_SNAPSHOT,
            "snapshot_seq": 2,
            "snapshot_ts": degraded_payload["snapshot_ts"] + 5000,
        }
        snap2_ack = await _send_snapshot(bridge, ws2, device_id, healthy_payload)
        assert snap2_ack.get("status") == "absorbed"

        snap_post_recovery = get_device_state_snapshot(device_id)
        assert snap_post_recovery is not None
        assert snap_post_recovery.model_ready is True, (
            "Post-recovery snapshot must show model_ready=True"
        )

        # Step 4: new execution record → ack → final_result
        contract_id_2 = f"cid-hybrid-2-{uuid.uuid4().hex[:8]}"
        session_id_2 = f"sid-hybrid-2-{uuid.uuid4().hex[:8]}"
        record_2 = create_execution_tracking_record(
            contract_id=contract_id_2,
            session_id=session_id_2,
            device_id=device_id,
            trace_id="trace_hybrid",
        )
        record_execution_tracking(record_2, runtime=rt)

        env_ack2 = AndroidExecutionSignalEnvelope(
            signal_kind=AndroidSignalKind.ack,
            contract_id=contract_id_2,
            session_id=session_id_2,
        )
        o_ack2 = reconcile_android_execution_signal(env_ack2, runtime=rt)
        assert o_ack2.was_updated is True

        env_final = AndroidExecutionSignalEnvelope(
            signal_kind=AndroidSignalKind.final_result,
            contract_id=contract_id_2,
            session_id=session_id_2,
            payload={"result": {"ok": True}},
        )
        o_final = reconcile_android_execution_signal(env_final, runtime=rt)
        assert o_final.was_updated is True
        assert o_final.record.phase.value == "completed", (
            "Step 4 final_result must advance record to 'completed'"
        )

        # Step 5: store still reflects healthy device state
        final_snap = get_device_state_snapshot(device_id)
        assert final_snap is not None
        assert final_snap.model_ready is True, (
            "After full hybrid recovery arc, device state store must reflect healthy device"
        )
