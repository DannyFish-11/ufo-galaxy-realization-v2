"""tests/test_pr_v5_canonical_completion_closure.py
=====================================================
Test suite for PR-V5: Canonicalize group completion, delegated completion,
and partial failure semantics.

Coverage
--------
1. Module importability
   - canonical_group_completion_closure is importable.
   - All nine policy sentinels are non-empty strings.
   - All public symbols are accessible.

2. SignalKind enum
   - All expected signal kinds present.
   - delegated_ack is a recognised value.
   - device_blocked is a recognised value.
   - timeout_signal is a recognised value.

3. CanonicalTerminalKind enum
   - All expected terminal kinds present.
   - in_progress.is_terminal == False.
   - All other values have is_terminal == True.

4. DeviceResultSignal
   - is_terminal_signal is False for delegated_ack.
   - is_terminal_signal is False for device_blocked.
   - is_terminal_signal is True for subtask_result.
   - is_terminal_signal is True for delegated_terminal.
   - is_terminal_signal is True for handoff_terminal.
   - is_ack_signal is True only for delegated_ack.
   - to_dict() includes required keys.

5. CompletionContract V5 fields
   - blocked_device_exclusion field present with default "exclude_from_contract".
   - degraded_success_allowed field present with default False.
   - aggregate_timeout_seconds field present with default None.
   - to_dict() includes all three new fields.

6. _derive_completion_contract V5 per-mode values
   - PARALLEL_FANOUT uses blocked_device_exclusion="exclude_from_contract".
   - PARALLEL_FANOUT uses degraded_success_allowed=True.
   - LOCAL uses blocked_device_exclusion="promote_to_partial_failure".
   - HANDOFF uses blocked_device_exclusion="promote_to_partial_failure".
   - DELEGATED_RUNTIME uses blocked_device_exclusion="promote_to_partial_failure".
   - WAKE_ROUTED uses blocked_device_exclusion="exclude_from_contract".
   - CROSS_DEVICE uses degraded_success_allowed=True.
   - HYBRID uses degraded_success_allowed=True.

7. apply_completion_closure — subtask success ≠ group completion
   - Single subtask success with expected_count=2 → in_progress.
   - Both subtasks succeed with expected_count=2 → complete.
   - subtask 1 success + subtask 2 success → complete (not after first).

8. apply_completion_closure — delegated ACK distinct from terminal
   - Delegated ACK alone → in_progress (not terminal).
   - Delegated ACK + delegated_terminal success → complete.
   - Delegated ACK does not increment terminal result count.

9. apply_completion_closure — handoff terminal aligns with canonical closure
   - Handoff terminal success → complete (via same closure).
   - Handoff terminal failure with fail_all policy → partial_failure.

10. apply_completion_closure — blocked device exclusion
    - exclude_from_contract: blocked device shrinks effective count.
    - promote_to_partial_failure: blocked device counts as failure.
    - abort_on_any_blocked: any blocked device → aborted.

11. apply_completion_closure — degraded success
    - degraded_success_allowed=True + exclude + all received succeeded →
      degraded_success.
    - degraded_success_allowed=False + exclude + all received succeeded →
      complete (no excluded) or partial_success (if policy differs).

12. apply_completion_closure — aggregate timeout
    - timeout_signal injected → aggregate_timeout terminal state.
    - Wall-clock timeout exceeded with fewer results than expected →
      aggregate_timeout.

13. apply_completion_closure — partial failure
    - fail_all policy + one failure → partial_failure.
    - best_effort policy + one failure → partial_success (not partial_failure).

14. apply_completion_closure — aggregate failure
    - All devices returned failure → aggregate_failure regardless of policy.
    - aggregate_failure supersedes partial_failure.

15. apply_completion_closure — require_majority
    - Majority succeeded → partial_success.
    - Majority not reached → partial_failure.

16. apply_completion_closure — any_success aggregation
    - First success in any_success mode → complete immediately.

17. CompletionClosureCoordinator
    - record() stores outcomes.
    - snapshot() returns list of recorded outcomes.
    - clear() empties the buffer.

18. V5 policy sentinel importability from unified_orchestration_spine
    - ORCHESTRATION_SPINE_V5_COMPLETION_CLOSURE_POLICY non-empty.
    - COMPLETION_CONTRACT_V5_BLOCKED_DEVICE_EXCLUSION_POLICY non-empty.
    - COMPLETION_CONTRACT_V5_DEGRADED_SUCCESS_POLICY non-empty.
    - COMPLETION_CONTRACT_V5_AGGREGATE_TIMEOUT_POLICY non-empty.

19. Error safety
    - apply_completion_closure never raises.
    - Works with minimal context (empty signals list).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, List, Optional
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Availability guards
# ---------------------------------------------------------------------------

try:
    from core.canonical_group_completion_closure import (
        ALL_ADVANCED_MODES_USE_CANONICAL_CLOSURE_POLICY,
        AGGREGATE_FAILURE_HAS_CANONICAL_DEFINITION_POLICY,
        AGGREGATE_TIMEOUT_PRODUCES_CANONICAL_TERMINAL_POLICY,
        BLOCKED_DEVICE_EXCLUSION_SEMANTIC_IS_EXPLICIT_POLICY,
        CANONICAL_GROUP_COMPLETION_CLOSURE_AUTHORITY,
        DELEGATED_ACK_DISTINCT_FROM_DELEGATED_TERMINAL_POLICY,
        DEGRADED_SUCCESS_REQUIRES_EXPLICIT_ALLOWANCE_POLICY,
        HANDOFF_TERMINAL_ALIGNS_WITH_CANONICAL_CLOSURE_POLICY,
        PARTIAL_FAILURE_HAS_CANONICAL_DEFINITION_POLICY,
        SUBTASK_SUCCESS_DOES_NOT_CONSTITUTE_GROUP_COMPLETION_POLICY,
        CanonicalTerminalKind,
        CompletionClosureContext,
        CompletionClosureCoordinator,
        DeviceResultSignal,
        SignalKind,
        apply_completion_closure,
        get_completion_closure_coordinator,
    )
    _CLOSURE_AVAILABLE = True
except ImportError:
    _CLOSURE_AVAILABLE = False

try:
    from core.unified_orchestration_spine import (
        COMPLETION_CONTRACT_V5_AGGREGATE_TIMEOUT_POLICY,
        COMPLETION_CONTRACT_V5_BLOCKED_DEVICE_EXCLUSION_POLICY,
        COMPLETION_CONTRACT_V5_DEGRADED_SUCCESS_POLICY,
        ORCHESTRATION_SPINE_V5_COMPLETION_CLOSURE_POLICY,
        CompletionContract,
        ExecutionMode,
    )
    _SPINE_AVAILABLE = True
except ImportError:
    _SPINE_AVAILABLE = False

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_contract(
    expected: int = 1,
    policy: str = "fail_all",
    agg_mode: str = "all_required",
    exclusion: str = "exclude_from_contract",
    degraded: bool = False,
    timeout: Optional[float] = None,
) -> Any:
    """Build a minimal CompletionContract (or stand-in) for testing."""
    if _SPINE_AVAILABLE:
        return CompletionContract(
            expected_result_count=expected,
            partial_failure_policy=policy,
            aggregation_mode=agg_mode,
            blocked_device_exclusion=exclusion,
            degraded_success_allowed=degraded,
            aggregate_timeout_seconds=timeout,
        )

    @dataclass
    class _FakeContract:
        expected_result_count: int = 1
        partial_failure_policy: str = "fail_all"
        aggregation_mode: str = "all_required"
        blocked_device_exclusion: str = "exclude_from_contract"
        degraded_success_allowed: bool = False
        aggregate_timeout_seconds: Optional[float] = None

    return _FakeContract(
        expected_result_count=expected,
        partial_failure_policy=policy,
        aggregation_mode=agg_mode,
        blocked_device_exclusion=exclusion,
        degraded_success_allowed=degraded,
        aggregate_timeout_seconds=timeout,
    )


def _sig(
    device_id: str,
    signal_kind: str = SignalKind.subtask_result.value if _CLOSURE_AVAILABLE else "subtask_result",
    success: bool = True,
) -> Any:
    """Build a DeviceResultSignal for testing."""
    if _CLOSURE_AVAILABLE:
        return DeviceResultSignal(device_id=device_id, signal_kind=signal_kind, is_success=success)

    @dataclass
    class _FakeSig:
        device_id: str
        signal_kind: str
        is_success: bool
        is_terminal_signal: bool = True
        is_ack_signal: bool = False
        is_blocked_signal: bool = False
        is_timeout_signal: bool = False

    return _FakeSig(device_id=device_id, signal_kind=signal_kind, is_success=success)


def _ctx(signals: list, expected_ids: Optional[list] = None, started_at: Optional[float] = None) -> Any:
    if _CLOSURE_AVAILABLE:
        ctx = CompletionClosureContext(
            expected_device_ids=expected_ids or [],
        )
        ctx.signals = signals
        if started_at is not None:
            ctx.started_at = started_at
        return ctx

    @dataclass
    class _FakeCtx:
        signals: list
        expected_device_ids: list
        orchestration_id: str = "test_orch"
        started_at: float = field(default_factory=time.time)

    return _FakeCtx(signals=signals, expected_device_ids=expected_ids or [])


# ===========================================================================
# Group 1: Module importability
# ===========================================================================


@pytest.mark.skipif(not _CLOSURE_AVAILABLE, reason="canonical_group_completion_closure unavailable")
class TestModuleImportability:
    def test_authority_sentinel_non_empty(self) -> None:
        assert isinstance(CANONICAL_GROUP_COMPLETION_CLOSURE_AUTHORITY, str)
        assert len(CANONICAL_GROUP_COMPLETION_CLOSURE_AUTHORITY) > 0

    def test_subtask_policy_non_empty(self) -> None:
        assert len(SUBTASK_SUCCESS_DOES_NOT_CONSTITUTE_GROUP_COMPLETION_POLICY) > 0

    def test_delegated_ack_policy_non_empty(self) -> None:
        assert len(DELEGATED_ACK_DISTINCT_FROM_DELEGATED_TERMINAL_POLICY) > 0

    def test_handoff_policy_non_empty(self) -> None:
        assert len(HANDOFF_TERMINAL_ALIGNS_WITH_CANONICAL_CLOSURE_POLICY) > 0

    def test_blocked_device_policy_non_empty(self) -> None:
        assert len(BLOCKED_DEVICE_EXCLUSION_SEMANTIC_IS_EXPLICIT_POLICY) > 0

    def test_timeout_policy_non_empty(self) -> None:
        assert len(AGGREGATE_TIMEOUT_PRODUCES_CANONICAL_TERMINAL_POLICY) > 0

    def test_degraded_success_policy_non_empty(self) -> None:
        assert len(DEGRADED_SUCCESS_REQUIRES_EXPLICIT_ALLOWANCE_POLICY) > 0

    def test_partial_failure_policy_non_empty(self) -> None:
        assert len(PARTIAL_FAILURE_HAS_CANONICAL_DEFINITION_POLICY) > 0

    def test_aggregate_failure_policy_non_empty(self) -> None:
        assert len(AGGREGATE_FAILURE_HAS_CANONICAL_DEFINITION_POLICY) > 0

    def test_all_advanced_modes_policy_non_empty(self) -> None:
        assert len(ALL_ADVANCED_MODES_USE_CANONICAL_CLOSURE_POLICY) > 0

    def test_apply_completion_closure_callable(self) -> None:
        assert callable(apply_completion_closure)

    def test_get_coordinator_callable(self) -> None:
        assert callable(get_completion_closure_coordinator)


# ===========================================================================
# Group 2: SignalKind enum
# ===========================================================================


@pytest.mark.skipif(not _CLOSURE_AVAILABLE, reason="canonical_group_completion_closure unavailable")
class TestSignalKind:
    def test_subtask_result_present(self) -> None:
        assert SignalKind.subtask_result.value == "subtask_result"

    def test_delegated_ack_present(self) -> None:
        assert SignalKind.delegated_ack.value == "delegated_ack"

    def test_delegated_terminal_present(self) -> None:
        assert SignalKind.delegated_terminal.value == "delegated_terminal"

    def test_handoff_terminal_present(self) -> None:
        assert SignalKind.handoff_terminal.value == "handoff_terminal"

    def test_device_blocked_present(self) -> None:
        assert SignalKind.device_blocked.value == "device_blocked"

    def test_timeout_signal_present(self) -> None:
        assert SignalKind.timeout_signal.value == "timeout_signal"

    def test_local_terminal_present(self) -> None:
        assert SignalKind.local_terminal.value == "local_terminal"

    def test_wake_terminal_present(self) -> None:
        assert SignalKind.wake_terminal.value == "wake_terminal"


# ===========================================================================
# Group 3: CanonicalTerminalKind enum
# ===========================================================================


@pytest.mark.skipif(not _CLOSURE_AVAILABLE, reason="canonical_group_completion_closure unavailable")
class TestCanonicalTerminalKind:
    def test_in_progress_not_terminal(self) -> None:
        assert CanonicalTerminalKind.in_progress.is_terminal is False

    def test_complete_is_terminal(self) -> None:
        assert CanonicalTerminalKind.complete.is_terminal is True

    def test_degraded_success_is_terminal(self) -> None:
        assert CanonicalTerminalKind.degraded_success.is_terminal is True

    def test_partial_success_is_terminal(self) -> None:
        assert CanonicalTerminalKind.partial_success.is_terminal is True

    def test_partial_failure_is_terminal(self) -> None:
        assert CanonicalTerminalKind.partial_failure.is_terminal is True

    def test_aggregate_failure_is_terminal(self) -> None:
        assert CanonicalTerminalKind.aggregate_failure.is_terminal is True

    def test_aggregate_timeout_is_terminal(self) -> None:
        assert CanonicalTerminalKind.aggregate_timeout.is_terminal is True

    def test_aborted_is_terminal(self) -> None:
        assert CanonicalTerminalKind.aborted.is_terminal is True


# ===========================================================================
# Group 4: DeviceResultSignal
# ===========================================================================


@pytest.mark.skipif(not _CLOSURE_AVAILABLE, reason="canonical_group_completion_closure unavailable")
class TestDeviceResultSignal:
    def test_ack_not_terminal_signal(self) -> None:
        sig = DeviceResultSignal(device_id="d1", signal_kind=SignalKind.delegated_ack.value)
        assert sig.is_terminal_signal is False

    def test_blocked_not_terminal_signal(self) -> None:
        sig = DeviceResultSignal(device_id="d1", signal_kind=SignalKind.device_blocked.value)
        assert sig.is_terminal_signal is False

    def test_subtask_is_terminal_signal(self) -> None:
        sig = DeviceResultSignal(device_id="d1", signal_kind=SignalKind.subtask_result.value)
        assert sig.is_terminal_signal is True

    def test_delegated_terminal_is_terminal_signal(self) -> None:
        sig = DeviceResultSignal(device_id="d1", signal_kind=SignalKind.delegated_terminal.value)
        assert sig.is_terminal_signal is True

    def test_handoff_terminal_is_terminal_signal(self) -> None:
        sig = DeviceResultSignal(device_id="d1", signal_kind=SignalKind.handoff_terminal.value)
        assert sig.is_terminal_signal is True

    def test_ack_is_ack_signal(self) -> None:
        sig = DeviceResultSignal(device_id="d1", signal_kind=SignalKind.delegated_ack.value)
        assert sig.is_ack_signal is True

    def test_subtask_is_not_ack_signal(self) -> None:
        sig = DeviceResultSignal(device_id="d1", signal_kind=SignalKind.subtask_result.value)
        assert sig.is_ack_signal is False

    def test_to_dict_includes_keys(self) -> None:
        sig = DeviceResultSignal(device_id="d1", signal_kind=SignalKind.subtask_result.value, is_success=True)
        d = sig.to_dict()
        assert "device_id" in d
        assert "signal_kind" in d
        assert "is_success" in d
        assert "is_terminal_signal" in d
        assert "is_ack_signal" in d


# ===========================================================================
# Group 5: CompletionContract V5 fields
# ===========================================================================


@pytest.mark.skipif(not _SPINE_AVAILABLE, reason="unified_orchestration_spine unavailable")
class TestCompletionContractV5Fields:
    def test_blocked_device_exclusion_default(self) -> None:
        c = CompletionContract()
        assert c.blocked_device_exclusion == "exclude_from_contract"

    def test_degraded_success_allowed_default(self) -> None:
        c = CompletionContract()
        assert c.degraded_success_allowed is False

    def test_aggregate_timeout_seconds_default(self) -> None:
        c = CompletionContract()
        assert c.aggregate_timeout_seconds is None

    def test_to_dict_includes_blocked_device_exclusion(self) -> None:
        c = CompletionContract()
        assert "blocked_device_exclusion" in c.to_dict()

    def test_to_dict_includes_degraded_success_allowed(self) -> None:
        c = CompletionContract()
        assert "degraded_success_allowed" in c.to_dict()

    def test_to_dict_includes_aggregate_timeout_seconds(self) -> None:
        c = CompletionContract()
        assert "aggregate_timeout_seconds" in c.to_dict()

    def test_can_set_custom_values(self) -> None:
        c = CompletionContract(
            blocked_device_exclusion="abort_on_any_blocked",
            degraded_success_allowed=True,
            aggregate_timeout_seconds=30.0,
        )
        assert c.blocked_device_exclusion == "abort_on_any_blocked"
        assert c.degraded_success_allowed is True
        assert c.aggregate_timeout_seconds == 30.0


# ===========================================================================
# Group 6: _derive_completion_contract V5 per-mode values
# ===========================================================================


@pytest.mark.skipif(not _SPINE_AVAILABLE, reason="unified_orchestration_spine unavailable")
class TestDeriveCompletionContractV5:
    def _derive(self, mode: str, count: int = 2) -> "CompletionContract":
        from core.unified_orchestration_spine import (
            DeviceOrchestrationSlot,
            _derive_completion_contract,
        )
        slots = [DeviceOrchestrationSlot(device_id=f"d{i}", dispatch_ready=True) for i in range(count)]
        return _derive_completion_contract(mode, slots)

    def test_parallel_fanout_exclusion(self) -> None:
        c = self._derive(ExecutionMode.PARALLEL_FANOUT.value)
        assert c.blocked_device_exclusion == "exclude_from_contract"

    def test_parallel_fanout_degraded_allowed(self) -> None:
        c = self._derive(ExecutionMode.PARALLEL_FANOUT.value)
        assert c.degraded_success_allowed is True

    def test_cross_device_degraded_allowed(self) -> None:
        c = self._derive(ExecutionMode.CROSS_DEVICE.value)
        assert c.degraded_success_allowed is True

    def test_hybrid_degraded_allowed(self) -> None:
        c = self._derive(ExecutionMode.HYBRID.value)
        assert c.degraded_success_allowed is True

    def test_local_exclusion(self) -> None:
        c = self._derive(ExecutionMode.LOCAL.value)
        assert c.blocked_device_exclusion == "promote_to_partial_failure"

    def test_delegated_runtime_exclusion(self) -> None:
        c = self._derive(ExecutionMode.DELEGATED_RUNTIME.value)
        assert c.blocked_device_exclusion == "promote_to_partial_failure"

    def test_handoff_exclusion(self) -> None:
        c = self._derive(ExecutionMode.HANDOFF.value)
        assert c.blocked_device_exclusion == "promote_to_partial_failure"

    def test_wake_routed_exclusion(self) -> None:
        c = self._derive(ExecutionMode.WAKE_ROUTED.value)
        assert c.blocked_device_exclusion == "exclude_from_contract"


# ===========================================================================
# Group 7: Subtask success ≠ group completion
# ===========================================================================


@pytest.mark.skipif(not _CLOSURE_AVAILABLE, reason="canonical_group_completion_closure unavailable")
class TestSubtaskSuccessNotGroupCompletion:
    def test_single_success_of_two_is_in_progress(self) -> None:
        """Subtask 1 success with expected=2 must NOT produce a terminal state."""
        contract = _make_contract(expected=2, policy="best_effort", agg_mode="all_required")
        ctx = _ctx(
            signals=[_sig("d1", SignalKind.subtask_result.value, success=True)],
        )
        outcome = apply_completion_closure(ctx, contract)
        assert outcome.terminal_kind == CanonicalTerminalKind.in_progress.value
        assert outcome.is_terminal is False

    def test_both_succeed_of_two_is_complete(self) -> None:
        """Both subtask results received → group complete."""
        contract = _make_contract(expected=2, policy="best_effort", agg_mode="all_required")
        ctx = _ctx(
            signals=[
                _sig("d1", SignalKind.subtask_result.value, success=True),
                _sig("d2", SignalKind.subtask_result.value, success=True),
            ],
        )
        outcome = apply_completion_closure(ctx, contract)
        assert outcome.terminal_kind == CanonicalTerminalKind.complete.value
        assert outcome.is_terminal is True

    def test_success_count_not_confused_with_expected_count(self) -> None:
        """success_count=1 should not equal expected_count=1 after only an ACK."""
        # One device sent an ACK (non-terminal) and one sent a success.
        # expected=2 → still in_progress because only 1 terminal signal.
        contract = _make_contract(expected=2, policy="best_effort", agg_mode="all_required")
        ctx = _ctx(
            signals=[
                _sig("d1", SignalKind.delegated_ack.value, success=False),
                _sig("d2", SignalKind.subtask_result.value, success=True),
            ],
        )
        outcome = apply_completion_closure(ctx, contract)
        assert outcome.terminal_kind == CanonicalTerminalKind.in_progress.value


# ===========================================================================
# Group 8: Delegated ACK distinct from delegated terminal
# ===========================================================================


@pytest.mark.skipif(not _CLOSURE_AVAILABLE, reason="canonical_group_completion_closure unavailable")
class TestDelegatedAckDistinct:
    def test_ack_alone_is_not_terminal(self) -> None:
        contract = _make_contract(expected=1, policy="fail_all", agg_mode="all_required")
        ctx = _ctx(
            signals=[_sig("d1", SignalKind.delegated_ack.value, success=False)],
        )
        outcome = apply_completion_closure(ctx, contract)
        assert outcome.is_terminal is False
        assert outcome.terminal_kind == CanonicalTerminalKind.in_progress.value

    def test_ack_plus_terminal_success_is_complete(self) -> None:
        contract = _make_contract(expected=1, policy="fail_all", agg_mode="all_required")
        ctx = _ctx(
            signals=[
                _sig("d1", SignalKind.delegated_ack.value, success=False),
                _sig("d1", SignalKind.delegated_terminal.value, success=True),
            ],
        )
        outcome = apply_completion_closure(ctx, contract)
        assert outcome.terminal_kind == CanonicalTerminalKind.complete.value
        assert outcome.is_terminal is True

    def test_ack_does_not_contribute_to_result_count(self) -> None:
        contract = _make_contract(expected=2, policy="best_effort", agg_mode="all_required")
        ctx = _ctx(
            signals=[
                _sig("d1", SignalKind.delegated_ack.value),
                _sig("d1", SignalKind.delegated_ack.value),
                _sig("d1", SignalKind.delegated_terminal.value, success=True),
            ],
        )
        # Only 1 terminal signal arrived, expected=2 → in_progress
        outcome = apply_completion_closure(ctx, contract)
        assert outcome.terminal_kind == CanonicalTerminalKind.in_progress.value
        assert outcome.ack_count == 2

    def test_two_acks_do_not_satisfy_expected_count_of_two(self) -> None:
        """2 ACK signals for expected=2 must not produce complete."""
        contract = _make_contract(expected=2, policy="best_effort", agg_mode="all_required")
        ctx = _ctx(
            signals=[
                _sig("d1", SignalKind.delegated_ack.value),
                _sig("d2", SignalKind.delegated_ack.value),
            ],
        )
        outcome = apply_completion_closure(ctx, contract)
        assert outcome.is_terminal is False


# ===========================================================================
# Group 9: Handoff terminal aligns with canonical closure
# ===========================================================================


@pytest.mark.skipif(not _CLOSURE_AVAILABLE, reason="canonical_group_completion_closure unavailable")
class TestHandoffTerminalAligned:
    def test_handoff_success_produces_complete(self) -> None:
        contract = _make_contract(expected=1, policy="fail_all", agg_mode="first_wins")
        ctx = _ctx(
            signals=[_sig("d1", SignalKind.handoff_terminal.value, success=True)],
        )
        outcome = apply_completion_closure(ctx, contract)
        assert outcome.terminal_kind == CanonicalTerminalKind.complete.value

    def test_handoff_failure_with_fail_all_produces_partial_failure(self) -> None:
        contract = _make_contract(expected=1, policy="fail_all", agg_mode="first_wins")
        ctx = _ctx(
            signals=[_sig("d1", SignalKind.handoff_terminal.value, success=False)],
        )
        outcome = apply_completion_closure(ctx, contract)
        assert outcome.terminal_kind in (
            CanonicalTerminalKind.partial_failure.value,
            CanonicalTerminalKind.aggregate_failure.value,
        )
        assert outcome.is_terminal is True

    def test_handoff_uses_same_closure_as_parallel(self) -> None:
        """Handoff signals go through the same apply_completion_closure path."""
        contract_handoff = _make_contract(expected=1, policy="fail_all", agg_mode="first_wins")
        contract_parallel = _make_contract(expected=1, policy="fail_all", agg_mode="first_wins")
        ctx_h = _ctx(signals=[_sig("d1", SignalKind.handoff_terminal.value, success=True)])
        ctx_p = _ctx(signals=[_sig("d1", SignalKind.subtask_result.value, success=True)])
        outcome_h = apply_completion_closure(ctx_h, contract_handoff)
        outcome_p = apply_completion_closure(ctx_p, contract_parallel)
        assert outcome_h.terminal_kind == outcome_p.terminal_kind


# ===========================================================================
# Group 10: Blocked device exclusion semantics
# ===========================================================================


@pytest.mark.skipif(not _CLOSURE_AVAILABLE, reason="canonical_group_completion_closure unavailable")
class TestBlockedDeviceExclusion:
    def test_exclude_from_contract_shrinks_expected(self) -> None:
        # expected=2, one blocked → effective=1, one success → complete
        contract = _make_contract(
            expected=2, policy="best_effort", agg_mode="all_required",
            exclusion="exclude_from_contract", degraded=False,
        )
        ctx = _ctx(
            signals=[
                _sig("d1", SignalKind.device_blocked.value),
                _sig("d2", SignalKind.subtask_result.value, success=True),
            ],
        )
        outcome = apply_completion_closure(ctx, contract)
        assert outcome.terminal_kind == CanonicalTerminalKind.complete.value
        assert outcome.blocked_count == 1

    def test_promote_to_partial_failure_counts_blocked_as_failure(self) -> None:
        # expected=2, one blocked (counts as failure) + one success → fail_all → partial_failure
        contract = _make_contract(
            expected=2, policy="fail_all", agg_mode="all_required",
            exclusion="promote_to_partial_failure",
        )
        ctx = _ctx(
            signals=[
                _sig("d1", SignalKind.device_blocked.value),
                _sig("d2", SignalKind.subtask_result.value, success=True),
            ],
        )
        outcome = apply_completion_closure(ctx, contract)
        assert outcome.terminal_kind == CanonicalTerminalKind.partial_failure.value

    def test_abort_on_any_blocked_returns_aborted(self) -> None:
        contract = _make_contract(
            expected=2, policy="best_effort", agg_mode="all_required",
            exclusion="abort_on_any_blocked",
        )
        ctx = _ctx(
            signals=[
                _sig("d1", SignalKind.device_blocked.value),
                _sig("d2", SignalKind.subtask_result.value, success=True),
            ],
        )
        outcome = apply_completion_closure(ctx, contract)
        assert outcome.terminal_kind == CanonicalTerminalKind.aborted.value
        assert outcome.is_terminal is True


# ===========================================================================
# Group 11: Degraded success
# ===========================================================================


@pytest.mark.skipif(not _CLOSURE_AVAILABLE, reason="canonical_group_completion_closure unavailable")
class TestDegradedSuccess:
    def test_degraded_success_when_allowed(self) -> None:
        # expected=2, one blocked (excluded), one success → degraded_success
        contract = _make_contract(
            expected=2, policy="best_effort", agg_mode="all_required",
            exclusion="exclude_from_contract", degraded=True,
        )
        ctx = _ctx(
            signals=[
                _sig("d1", SignalKind.device_blocked.value),
                _sig("d2", SignalKind.subtask_result.value, success=True),
            ],
        )
        outcome = apply_completion_closure(ctx, contract)
        assert outcome.terminal_kind == CanonicalTerminalKind.degraded_success.value

    def test_no_degraded_success_when_not_allowed(self) -> None:
        # Same scenario but degraded_success_allowed=False → complete
        # (since no failures among received results, just one excluded)
        contract = _make_contract(
            expected=2, policy="best_effort", agg_mode="all_required",
            exclusion="exclude_from_contract", degraded=False,
        )
        ctx = _ctx(
            signals=[
                _sig("d1", SignalKind.device_blocked.value),
                _sig("d2", SignalKind.subtask_result.value, success=True),
            ],
        )
        outcome = apply_completion_closure(ctx, contract)
        # Not degraded_success — should be complete (all received succeeded)
        assert outcome.terminal_kind == CanonicalTerminalKind.complete.value

    def test_no_excluded_devices_no_degraded_success(self) -> None:
        # No blocked devices → no degraded_success even when allowed
        contract = _make_contract(
            expected=2, policy="best_effort", agg_mode="all_required",
            exclusion="exclude_from_contract", degraded=True,
        )
        ctx = _ctx(
            signals=[
                _sig("d1", SignalKind.subtask_result.value, success=True),
                _sig("d2", SignalKind.subtask_result.value, success=True),
            ],
        )
        outcome = apply_completion_closure(ctx, contract)
        assert outcome.terminal_kind == CanonicalTerminalKind.complete.value


# ===========================================================================
# Group 12: Aggregate timeout
# ===========================================================================


@pytest.mark.skipif(not _CLOSURE_AVAILABLE, reason="canonical_group_completion_closure unavailable")
class TestAggregateTimeout:
    def test_timeout_signal_produces_aggregate_timeout(self) -> None:
        contract = _make_contract(expected=2, policy="best_effort", agg_mode="all_required")
        ctx = _ctx(
            signals=[
                _sig("d1", SignalKind.subtask_result.value, success=True),
                _sig("_timeout", SignalKind.timeout_signal.value),
            ],
        )
        outcome = apply_completion_closure(ctx, contract)
        assert outcome.terminal_kind == CanonicalTerminalKind.aggregate_timeout.value
        assert outcome.is_terminal is True

    def test_wall_clock_timeout_exceeded(self) -> None:
        # started_at = far in the past, timeout = 1 second
        contract = _make_contract(
            expected=2, policy="best_effort", agg_mode="all_required", timeout=1.0
        )
        ctx = _ctx(
            signals=[_sig("d1", SignalKind.subtask_result.value, success=True)],
            started_at=time.time() - 100.0,  # started 100s ago
        )
        outcome = apply_completion_closure(ctx, contract)
        assert outcome.terminal_kind == CanonicalTerminalKind.aggregate_timeout.value

    def test_no_timeout_when_results_arrive_in_time(self) -> None:
        contract = _make_contract(
            expected=2, policy="best_effort", agg_mode="all_required", timeout=9999.0
        )
        ctx = _ctx(
            signals=[
                _sig("d1", SignalKind.subtask_result.value, success=True),
                _sig("d2", SignalKind.subtask_result.value, success=True),
            ],
        )
        outcome = apply_completion_closure(ctx, contract)
        assert outcome.terminal_kind == CanonicalTerminalKind.complete.value


# ===========================================================================
# Group 13: Partial failure semantics
# ===========================================================================


@pytest.mark.skipif(not _CLOSURE_AVAILABLE, reason="canonical_group_completion_closure unavailable")
class TestPartialFailure:
    def test_fail_all_one_failure_is_partial_failure(self) -> None:
        contract = _make_contract(expected=2, policy="fail_all", agg_mode="all_required")
        ctx = _ctx(
            signals=[
                _sig("d1", SignalKind.subtask_result.value, success=True),
                _sig("d2", SignalKind.subtask_result.value, success=False),
            ],
        )
        outcome = apply_completion_closure(ctx, contract)
        assert outcome.terminal_kind == CanonicalTerminalKind.partial_failure.value
        assert outcome.is_terminal is True

    def test_best_effort_one_failure_is_partial_success(self) -> None:
        contract = _make_contract(expected=2, policy="best_effort", agg_mode="all_required")
        ctx = _ctx(
            signals=[
                _sig("d1", SignalKind.subtask_result.value, success=True),
                _sig("d2", SignalKind.subtask_result.value, success=False),
            ],
        )
        outcome = apply_completion_closure(ctx, contract)
        assert outcome.terminal_kind == CanonicalTerminalKind.partial_success.value
        assert outcome.is_terminal is True

    def test_partial_failure_terminal_is_true(self) -> None:
        contract = _make_contract(expected=1, policy="fail_all", agg_mode="all_required")
        ctx = _ctx(signals=[_sig("d1", SignalKind.subtask_result.value, success=False)])
        outcome = apply_completion_closure(ctx, contract)
        # Either partial_failure or aggregate_failure since all failed
        assert outcome.is_terminal is True


# ===========================================================================
# Group 14: Aggregate failure semantics
# ===========================================================================


@pytest.mark.skipif(not _CLOSURE_AVAILABLE, reason="canonical_group_completion_closure unavailable")
class TestAggregateFailure:
    def test_all_fail_produces_aggregate_failure(self) -> None:
        contract = _make_contract(expected=2, policy="best_effort", agg_mode="all_required")
        ctx = _ctx(
            signals=[
                _sig("d1", SignalKind.subtask_result.value, success=False),
                _sig("d2", SignalKind.subtask_result.value, success=False),
            ],
        )
        outcome = apply_completion_closure(ctx, contract)
        assert outcome.terminal_kind == CanonicalTerminalKind.aggregate_failure.value

    def test_aggregate_failure_with_fail_all_policy(self) -> None:
        contract = _make_contract(expected=2, policy="fail_all", agg_mode="all_required")
        ctx = _ctx(
            signals=[
                _sig("d1", SignalKind.subtask_result.value, success=False),
                _sig("d2", SignalKind.subtask_result.value, success=False),
            ],
        )
        outcome = apply_completion_closure(ctx, contract)
        assert outcome.terminal_kind == CanonicalTerminalKind.aggregate_failure.value

    def test_aggregate_failure_supersedes_partial_failure(self) -> None:
        """When all fail, outcome must be aggregate_failure not partial_failure."""
        contract = _make_contract(expected=3, policy="fail_all", agg_mode="all_required")
        ctx = _ctx(
            signals=[
                _sig("d1", SignalKind.subtask_result.value, success=False),
                _sig("d2", SignalKind.subtask_result.value, success=False),
                _sig("d3", SignalKind.subtask_result.value, success=False),
            ],
        )
        outcome = apply_completion_closure(ctx, contract)
        assert outcome.terminal_kind == CanonicalTerminalKind.aggregate_failure.value


# ===========================================================================
# Group 15: require_majority
# ===========================================================================


@pytest.mark.skipif(not _CLOSURE_AVAILABLE, reason="canonical_group_completion_closure unavailable")
class TestRequireMajority:
    def test_majority_succeeded_is_partial_success(self) -> None:
        contract = _make_contract(expected=3, policy="require_majority", agg_mode="all_required")
        ctx = _ctx(
            signals=[
                _sig("d1", SignalKind.subtask_result.value, success=True),
                _sig("d2", SignalKind.subtask_result.value, success=True),
                _sig("d3", SignalKind.subtask_result.value, success=False),
            ],
        )
        outcome = apply_completion_closure(ctx, contract)
        assert outcome.terminal_kind == CanonicalTerminalKind.partial_success.value

    def test_majority_not_reached_is_partial_failure(self) -> None:
        contract = _make_contract(expected=4, policy="require_majority", agg_mode="all_required")
        ctx = _ctx(
            signals=[
                _sig("d1", SignalKind.subtask_result.value, success=True),
                _sig("d2", SignalKind.subtask_result.value, success=False),
                _sig("d3", SignalKind.subtask_result.value, success=False),
                _sig("d4", SignalKind.subtask_result.value, success=False),
            ],
        )
        outcome = apply_completion_closure(ctx, contract)
        assert outcome.terminal_kind == CanonicalTerminalKind.partial_failure.value


# ===========================================================================
# Group 16: any_success aggregation
# ===========================================================================


@pytest.mark.skipif(not _CLOSURE_AVAILABLE, reason="canonical_group_completion_closure unavailable")
class TestAnySuccessAggregation:
    def test_first_success_produces_complete_in_any_success_mode(self) -> None:
        contract = _make_contract(expected=3, policy="best_effort", agg_mode="any_success")
        ctx = _ctx(
            signals=[_sig("d1", SignalKind.wake_terminal.value, success=True)],
        )
        outcome = apply_completion_closure(ctx, contract)
        assert outcome.terminal_kind == CanonicalTerminalKind.complete.value

    def test_only_failures_in_any_success_mode(self) -> None:
        contract = _make_contract(expected=2, policy="fail_all", agg_mode="any_success")
        ctx = _ctx(
            signals=[
                _sig("d1", SignalKind.wake_terminal.value, success=False),
                _sig("d2", SignalKind.wake_terminal.value, success=False),
            ],
        )
        outcome = apply_completion_closure(ctx, contract)
        # All failed → aggregate_failure
        assert outcome.terminal_kind == CanonicalTerminalKind.aggregate_failure.value


# ===========================================================================
# Group 17: CompletionClosureCoordinator
# ===========================================================================


@pytest.mark.skipif(not _CLOSURE_AVAILABLE, reason="canonical_group_completion_closure unavailable")
class TestCompletionClosureCoordinator:
    def _fresh_coordinator(self) -> "CompletionClosureCoordinator":
        c = CompletionClosureCoordinator()
        return c

    def test_record_stores_outcome(self) -> None:
        from core.canonical_group_completion_closure import CanonicalCompletionOutcome
        coord = self._fresh_coordinator()
        outcome = CanonicalCompletionOutcome(
            terminal_kind=CanonicalTerminalKind.complete.value,
            is_terminal=True,
        )
        coord.record(outcome)
        assert len(coord.snapshot()) == 1

    def test_snapshot_returns_list(self) -> None:
        coord = self._fresh_coordinator()
        assert isinstance(coord.snapshot(), list)

    def test_clear_empties_buffer(self) -> None:
        from core.canonical_group_completion_closure import CanonicalCompletionOutcome
        coord = self._fresh_coordinator()
        coord.record(CanonicalCompletionOutcome(terminal_kind="complete", is_terminal=True))
        coord.clear()
        assert len(coord.snapshot()) == 0

    def test_get_coordinator_returns_singleton(self) -> None:
        c1 = get_completion_closure_coordinator()
        c2 = get_completion_closure_coordinator()
        assert c1 is c2


# ===========================================================================
# Group 18: V5 policy sentinels importable from unified_orchestration_spine
# ===========================================================================


@pytest.mark.skipif(not _SPINE_AVAILABLE, reason="unified_orchestration_spine unavailable")
class TestSpineV5Sentinels:
    def test_v5_completion_closure_policy_non_empty(self) -> None:
        assert len(ORCHESTRATION_SPINE_V5_COMPLETION_CLOSURE_POLICY) > 0

    def test_blocked_device_exclusion_policy_non_empty(self) -> None:
        assert len(COMPLETION_CONTRACT_V5_BLOCKED_DEVICE_EXCLUSION_POLICY) > 0

    def test_degraded_success_policy_non_empty(self) -> None:
        assert len(COMPLETION_CONTRACT_V5_DEGRADED_SUCCESS_POLICY) > 0

    def test_aggregate_timeout_policy_non_empty(self) -> None:
        assert len(COMPLETION_CONTRACT_V5_AGGREGATE_TIMEOUT_POLICY) > 0


# ===========================================================================
# Group 19: Error safety
# ===========================================================================


@pytest.mark.skipif(not _CLOSURE_AVAILABLE, reason="canonical_group_completion_closure unavailable")
class TestErrorSafety:
    def test_never_raises_with_empty_signals(self) -> None:
        contract = _make_contract(expected=2)
        ctx = _ctx(signals=[])
        outcome = apply_completion_closure(ctx, contract)
        assert outcome is not None

    def test_never_raises_with_none_contract_fields(self) -> None:
        @dataclass
        class _MinimalContract:
            expected_result_count: int = 0

        ctx = _ctx(signals=[_sig("d1")])
        outcome = apply_completion_closure(ctx, _MinimalContract())
        assert outcome is not None

    def test_outcome_has_required_keys_in_to_dict(self) -> None:
        from core.canonical_group_completion_closure import CanonicalCompletionOutcome
        outcome = CanonicalCompletionOutcome(
            terminal_kind=CanonicalTerminalKind.in_progress.value,
            is_terminal=False,
        )
        d = outcome.to_dict()
        for key in ("terminal_kind", "is_terminal", "policy_reference", "evidence", "authority"):
            assert key in d, f"Missing key: {key}"

    def test_outcome_to_json_is_valid(self) -> None:
        import json
        from core.canonical_group_completion_closure import CanonicalCompletionOutcome
        outcome = CanonicalCompletionOutcome(
            terminal_kind=CanonicalTerminalKind.complete.value,
            is_terminal=True,
        )
        json.loads(outcome.to_json())  # must not raise
