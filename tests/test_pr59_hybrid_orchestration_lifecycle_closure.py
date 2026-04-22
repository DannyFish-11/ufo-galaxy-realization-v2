"""tests/test_pr59_hybrid_orchestration_lifecycle_closure.py
==============================================================
Tests for PR-59: Complete hybrid orchestration lifecycle, durability, and
recovery closure.

Coverage:

  Sentinels
  1.  HYBRID_ORCHESTRATION_CONTINUITY_IS_AUTHORITY is a non-empty string.
  2.  HYBRID_LIFECYCLE_IS_CANONICAL_ORCHESTRATION_PATH_POLICY is non-empty.
  3.  HYBRID_RECORD_IS_SERIALISABLE_POLICY is non-empty.
  4.  HYBRID_INTERRUPTION_IS_RECOVERABLE_POLICY is non-empty.
  5.  HYBRID_TERMINAL_STATE_IS_IMMUTABLE_POLICY is non-empty.
  6.  HYBRID_TRANSPORT_HANDLES_ARE_EPHEMERAL_POLICY is non-empty.
  7.  HYBRID_ORCHESTRATION_CONTINUITY_PR59_SENTINEL contains 'pr59'.

  HybridOrchestrationLifecycleState
  8.  All expected state values are present in the enum.
  9.  completed/failed/cancelled are terminal.
  10. created/dispatched/running/interrupted/resuming are non-terminal.
  11. interrupted.is_recoverable is True.
  12. running.is_active and resuming.is_active are True.
  13. created/interrupted/completed.is_active is False.
  14. terminal states have is_recoverable=False.

  HybridOrchestrationRecord — construction
  15. Default execution_id is non-empty and starts with 'hexec_'.
  16. Default lifecycle_state is 'created'.
  17. Default mode is 'sequential_degrade'.
  18. is_terminal is False for default (created) record.
  19. started_at defaults to None.
  20. resume_count defaults to 0.

  HybridOrchestrationRecord — serialisation
  21. to_dict() is JSON-serialisable.
  22. to_dict() contains all lifecycle-critical fields.
  23. from_dict() round-trip preserves execution_id.
  24. from_dict() round-trip preserves lifecycle_state.
  25. from_dict() round-trip preserves mode.
  26. from_dict() round-trip preserves resume_count.
  27. from_dict() with unknown state defaults to 'created'.
  28. from_dict() raises ValueError for non-dict input.

  HybridOrchestrationRecord — transitions
  29. created → dispatched is valid.
  30. dispatched → running sets started_at.
  31. running → completed sets completed_at and is_terminal=True.
  32. running → failed is terminal.
  33. running → interrupted sets interruption_reason.
  34. interrupted → resuming increments resume_count.
  35. resuming → running clears to active again.
  36. completed → running is rejected (terminal guard).
  37. failed → interrupted is rejected (terminal guard).
  38. created → completed is rejected (invalid transition).
  39. running → created is rejected (invalid transition).

  HybridOrchestrationContinuityRegistry — basic operations
  40. register() adds a record.
  41. create_and_register() returns a record with non-empty execution_id.
  42. get() returns the registered record.
  43. get() returns None for unknown execution_id.
  44. list_all() returns all records.
  45. list_non_terminal() excludes terminal records.
  46. list_terminal() includes only terminal records.
  47. list_interrupted() returns only interrupted records.
  48. transition() applies a valid transition.
  49. transition() returns False for unknown execution_id.
  50. count() reflects registration count.

  HybridOrchestrationContinuityRegistry — recovery
  51. mark_all_running_as_interrupted() transitions running→interrupted.
  52. mark_all_running_as_interrupted() transitions dispatched→interrupted.
  53. mark_all_running_as_interrupted() cancels created executions.
  54. mark_all_running_as_interrupted() leaves terminal records unchanged.
  55. mark_all_running_as_interrupted() leaves already-interrupted unchanged.
  56. mark_all_running_as_interrupted() returns correct count.
  57. clear_terminal() removes only terminal records.
  58. clear_terminal() returns count of removed records.

  RuntimeRecoveryReport — new field
  59. RuntimeRecoveryReport has hybrid_executions_interrupted field (default 0).
  60. to_dict() includes 'hybrid_executions_interrupted' key.

  RuntimeRestartRecoveryCoordinator — hybrid step
  61. run_recovery() sets hybrid_executions_interrupted on report.
  62. run_recovery() with in-flight registry marks them interrupted.
  63. run_recovery() with terminal-only registry marks 0 interrupted.
  64. run_recovery() non_goals list includes hybrid transport handles note.
  65. run_recovery() completes without error when hybrid registry is empty.

  run_startup_recovery — hybrid parameter
  66. run_startup_recovery() accepts hybrid_continuity_registry parameter.
  67. run_startup_recovery() returns RuntimeRecoveryReport with hybrid field.

  Durability boundary assertions
  68. Ephemeral sentinel mentions A2A/GUI/VLM.
  69. Canonical path sentinel confirms hybrid is not degrade-only.
  70. Interrupted state is non-terminal (resumable after restart).
"""

from __future__ import annotations

import json

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_registry() -> None:
    from core.hybrid_orchestration_continuity import reset_continuity_registry
    reset_continuity_registry()


def _make_registry():
    from core.hybrid_orchestration_continuity import HybridOrchestrationContinuityRegistry
    return HybridOrchestrationContinuityRegistry()


def _make_record(**kwargs):
    from core.hybrid_orchestration_continuity import HybridOrchestrationRecord
    return HybridOrchestrationRecord(**kwargs)


def _state(name: str):
    from core.hybrid_orchestration_continuity import HybridOrchestrationLifecycleState
    return HybridOrchestrationLifecycleState(name)


# ---------------------------------------------------------------------------
# 1–7: Sentinels
# ---------------------------------------------------------------------------

class TestSentinels:
    def test_01_continuity_is_authority_non_empty(self):
        from core.hybrid_orchestration_continuity import (
            HYBRID_ORCHESTRATION_CONTINUITY_IS_AUTHORITY,
        )
        assert isinstance(HYBRID_ORCHESTRATION_CONTINUITY_IS_AUTHORITY, str)
        assert len(HYBRID_ORCHESTRATION_CONTINUITY_IS_AUTHORITY) > 0

    def test_02_canonical_path_policy_non_empty(self):
        from core.hybrid_orchestration_continuity import (
            HYBRID_LIFECYCLE_IS_CANONICAL_ORCHESTRATION_PATH_POLICY,
        )
        assert len(HYBRID_LIFECYCLE_IS_CANONICAL_ORCHESTRATION_PATH_POLICY) > 0

    def test_03_serialisable_policy_non_empty(self):
        from core.hybrid_orchestration_continuity import (
            HYBRID_RECORD_IS_SERIALISABLE_POLICY,
        )
        assert len(HYBRID_RECORD_IS_SERIALISABLE_POLICY) > 0

    def test_04_interruption_recoverable_policy_non_empty(self):
        from core.hybrid_orchestration_continuity import (
            HYBRID_INTERRUPTION_IS_RECOVERABLE_POLICY,
        )
        assert len(HYBRID_INTERRUPTION_IS_RECOVERABLE_POLICY) > 0

    def test_05_terminal_immutable_policy_non_empty(self):
        from core.hybrid_orchestration_continuity import (
            HYBRID_TERMINAL_STATE_IS_IMMUTABLE_POLICY,
        )
        assert len(HYBRID_TERMINAL_STATE_IS_IMMUTABLE_POLICY) > 0

    def test_06_ephemeral_policy_non_empty(self):
        from core.hybrid_orchestration_continuity import (
            HYBRID_TRANSPORT_HANDLES_ARE_EPHEMERAL_POLICY,
        )
        assert len(HYBRID_TRANSPORT_HANDLES_ARE_EPHEMERAL_POLICY) > 0

    def test_07_pr59_sentinel_contains_pr59(self):
        from core.hybrid_orchestration_continuity import (
            HYBRID_ORCHESTRATION_CONTINUITY_PR59_SENTINEL,
        )
        assert "pr59" in HYBRID_ORCHESTRATION_CONTINUITY_PR59_SENTINEL.lower()


# ---------------------------------------------------------------------------
# 8–14: HybridOrchestrationLifecycleState
# ---------------------------------------------------------------------------

class TestLifecycleStateEnum:
    def test_08_all_states_present(self):
        from core.hybrid_orchestration_continuity import HybridOrchestrationLifecycleState
        names = {s.value for s in HybridOrchestrationLifecycleState}
        expected = {
            "created", "dispatched", "running", "interrupted",
            "resuming", "completed", "failed", "cancelled",
        }
        assert expected.issubset(names)

    def test_09_terminal_states(self):
        assert _state("completed").is_terminal is True
        assert _state("failed").is_terminal is True
        assert _state("cancelled").is_terminal is True

    def test_10_non_terminal_states(self):
        for s in ("created", "dispatched", "running", "interrupted", "resuming"):
            assert _state(s).is_terminal is False, f"expected {s!r} non-terminal"

    def test_11_interrupted_is_recoverable(self):
        assert _state("interrupted").is_recoverable is True

    def test_12_active_states(self):
        assert _state("running").is_active is True
        assert _state("resuming").is_active is True

    def test_13_inactive_states(self):
        for s in ("created", "interrupted", "completed", "dispatched"):
            assert _state(s).is_active is False, f"expected {s!r} inactive"

    def test_14_terminal_not_recoverable(self):
        for s in ("completed", "failed", "cancelled"):
            assert _state(s).is_recoverable is False


# ---------------------------------------------------------------------------
# 15–20: HybridOrchestrationRecord construction
# ---------------------------------------------------------------------------

class TestRecordConstruction:
    def test_15_execution_id_starts_with_hexec(self):
        r = _make_record()
        assert r.execution_id.startswith("hexec_")

    def test_16_default_state_is_created(self):
        r = _make_record()
        assert r.lifecycle_state.value == "created"

    def test_17_default_mode_is_sequential_degrade(self):
        r = _make_record()
        assert r.mode == "sequential_degrade"

    def test_18_is_terminal_false_for_created(self):
        r = _make_record()
        assert r.is_terminal is False

    def test_19_started_at_defaults_to_none(self):
        r = _make_record()
        assert r.started_at is None

    def test_20_resume_count_defaults_to_zero(self):
        r = _make_record()
        assert r.resume_count == 0


# ---------------------------------------------------------------------------
# 21–28: HybridOrchestrationRecord serialisation
# ---------------------------------------------------------------------------

class TestRecordSerialisation:
    def test_21_to_dict_is_json_serialisable(self):
        r = _make_record(session_id="s1", task_id="t1")
        d = r.to_dict()
        serialised = json.dumps(d)
        assert isinstance(serialised, str)

    def test_22_to_dict_contains_lifecycle_fields(self):
        r = _make_record()
        d = r.to_dict()
        for key in (
            "execution_id", "session_id", "task_id", "mode",
            "lifecycle_state", "started_at", "updated_at",
            "completed_at", "result_snapshot", "interruption_reason",
            "resume_count", "is_terminal",
        ):
            assert key in d, f"missing key {key!r}"

    def test_23_from_dict_round_trip_execution_id(self):
        from core.hybrid_orchestration_continuity import HybridOrchestrationRecord
        r = _make_record()
        r2 = HybridOrchestrationRecord.from_dict(r.to_dict())
        assert r2.execution_id == r.execution_id

    def test_24_from_dict_round_trip_lifecycle_state(self):
        from core.hybrid_orchestration_continuity import HybridOrchestrationRecord
        r = _make_record()
        r.transition(_state("dispatched"))
        r.transition(_state("running"))
        r2 = HybridOrchestrationRecord.from_dict(r.to_dict())
        assert r2.lifecycle_state.value == "running"

    def test_25_from_dict_round_trip_mode(self):
        from core.hybrid_orchestration_continuity import HybridOrchestrationRecord
        r = _make_record(mode="parallel_race")
        r2 = HybridOrchestrationRecord.from_dict(r.to_dict())
        assert r2.mode == "parallel_race"

    def test_26_from_dict_round_trip_resume_count(self):
        from core.hybrid_orchestration_continuity import HybridOrchestrationRecord
        r = _make_record()
        r.transition(_state("dispatched"))
        r.transition(_state("running"))
        r.transition(_state("interrupted"), reason="test")
        r.transition(_state("resuming"))
        r2 = HybridOrchestrationRecord.from_dict(r.to_dict())
        assert r2.resume_count == 1

    def test_27_from_dict_unknown_state_defaults_to_created(self):
        from core.hybrid_orchestration_continuity import HybridOrchestrationRecord
        r = HybridOrchestrationRecord.from_dict({"lifecycle_state": "bogus_state"})
        assert r.lifecycle_state.value == "created"

    def test_28_from_dict_raises_for_non_dict(self):
        from core.hybrid_orchestration_continuity import HybridOrchestrationRecord
        with pytest.raises(ValueError):
            HybridOrchestrationRecord.from_dict("not a dict")


# ---------------------------------------------------------------------------
# 29–39: HybridOrchestrationRecord transitions
# ---------------------------------------------------------------------------

class TestRecordTransitions:
    def test_29_created_to_dispatched(self):
        r = _make_record()
        assert r.transition(_state("dispatched")) is True
        assert r.lifecycle_state.value == "dispatched"

    def test_30_dispatched_to_running_sets_started_at(self):
        r = _make_record()
        r.transition(_state("dispatched"))
        r.transition(_state("running"))
        assert r.started_at is not None
        assert r.started_at > 0

    def test_31_running_to_completed_is_terminal(self):
        r = _make_record()
        r.transition(_state("dispatched"))
        r.transition(_state("running"))
        r.transition(_state("completed"), result={"output": "ok"})
        assert r.is_terminal is True
        assert r.completed_at is not None
        assert r.result_snapshot == {"output": "ok"}

    def test_32_running_to_failed_is_terminal(self):
        r = _make_record()
        r.transition(_state("dispatched"))
        r.transition(_state("running"))
        r.transition(_state("failed"))
        assert r.is_terminal is True

    def test_33_running_to_interrupted_sets_reason(self):
        r = _make_record()
        r.transition(_state("dispatched"))
        r.transition(_state("running"))
        r.transition(_state("interrupted"), reason="device_disconnect")
        assert r.lifecycle_state.value == "interrupted"
        assert r.interruption_reason == "device_disconnect"

    def test_34_interrupted_to_resuming_increments_count(self):
        r = _make_record()
        r.transition(_state("dispatched"))
        r.transition(_state("running"))
        r.transition(_state("interrupted"), reason="restart")
        r.transition(_state("resuming"))
        assert r.resume_count == 1

    def test_35_resuming_to_running_active_again(self):
        r = _make_record()
        r.transition(_state("dispatched"))
        r.transition(_state("running"))
        r.transition(_state("interrupted"), reason="restart")
        r.transition(_state("resuming"))
        r.transition(_state("running"))
        assert r.lifecycle_state.value == "running"
        assert r.is_terminal is False

    def test_36_completed_to_running_rejected(self):
        r = _make_record()
        r.transition(_state("dispatched"))
        r.transition(_state("running"))
        r.transition(_state("completed"))
        result = r.transition(_state("running"))
        assert result is False
        assert r.lifecycle_state.value == "completed"

    def test_37_failed_to_interrupted_rejected(self):
        r = _make_record()
        r.transition(_state("dispatched"))
        r.transition(_state("running"))
        r.transition(_state("failed"))
        result = r.transition(_state("interrupted"))
        assert result is False
        assert r.lifecycle_state.value == "failed"

    def test_38_created_to_completed_rejected(self):
        r = _make_record()
        result = r.transition(_state("completed"))
        assert result is False
        assert r.lifecycle_state.value == "created"

    def test_39_running_to_created_rejected(self):
        r = _make_record()
        r.transition(_state("dispatched"))
        r.transition(_state("running"))
        result = r.transition(_state("created"))
        assert result is False
        assert r.lifecycle_state.value == "running"


# ---------------------------------------------------------------------------
# 40–50: HybridOrchestrationContinuityRegistry — basic operations
# ---------------------------------------------------------------------------

class TestRegistryBasicOperations:
    def setup_method(self):
        _reset_registry()

    def test_40_register_adds_record(self):
        reg = _make_registry()
        r = _make_record()
        reg.register(r)
        assert reg.get(r.execution_id) is r

    def test_41_create_and_register_non_empty_id(self):
        reg = _make_registry()
        r = reg.create_and_register(session_id="s1", task_id="t1")
        assert r.execution_id.startswith("hexec_")
        assert reg.get(r.execution_id) is r

    def test_42_get_returns_registered(self):
        reg = _make_registry()
        r = _make_record()
        reg.register(r)
        assert reg.get(r.execution_id) is r

    def test_43_get_returns_none_for_unknown(self):
        reg = _make_registry()
        assert reg.get("nonexistent_id") is None

    def test_44_list_all_returns_all(self):
        reg = _make_registry()
        r1 = reg.create_and_register()
        r2 = reg.create_and_register()
        ids = {r.execution_id for r in reg.list_all()}
        assert r1.execution_id in ids
        assert r2.execution_id in ids

    def test_45_list_non_terminal_excludes_terminal(self):
        reg = _make_registry()
        r1 = reg.create_and_register()
        r2 = reg.create_and_register()
        # Advance r2 to terminal
        r2.transition(_state("dispatched"))
        r2.transition(_state("running"))
        r2.transition(_state("completed"))
        non_terminal = reg.list_non_terminal()
        non_terminal_ids = {r.execution_id for r in non_terminal}
        assert r1.execution_id in non_terminal_ids
        assert r2.execution_id not in non_terminal_ids

    def test_46_list_terminal_includes_only_terminal(self):
        reg = _make_registry()
        r1 = reg.create_and_register()
        r2 = reg.create_and_register()
        r2.transition(_state("dispatched"))
        r2.transition(_state("running"))
        r2.transition(_state("failed"))
        terminal_ids = {r.execution_id for r in reg.list_terminal()}
        assert r2.execution_id in terminal_ids
        assert r1.execution_id not in terminal_ids

    def test_47_list_interrupted_returns_only_interrupted(self):
        reg = _make_registry()
        r1 = reg.create_and_register()
        r1.transition(_state("dispatched"))
        r1.transition(_state("running"))
        r1.transition(_state("interrupted"), reason="test")
        r2 = reg.create_and_register()  # stays created
        interrupted_ids = {r.execution_id for r in reg.list_interrupted()}
        assert r1.execution_id in interrupted_ids
        assert r2.execution_id not in interrupted_ids

    def test_48_transition_applies_valid(self):
        reg = _make_registry()
        r = reg.create_and_register()
        result = reg.transition(r.execution_id, _state("dispatched"))
        assert result is True
        assert reg.get(r.execution_id).lifecycle_state.value == "dispatched"

    def test_49_transition_returns_false_for_unknown(self):
        reg = _make_registry()
        result = reg.transition("no_such_id", _state("running"))
        assert result is False

    def test_50_count_reflects_registrations(self):
        reg = _make_registry()
        assert reg.count() == 0
        reg.create_and_register()
        assert reg.count() == 1
        reg.create_and_register()
        assert reg.count() == 2


# ---------------------------------------------------------------------------
# 51–58: HybridOrchestrationContinuityRegistry — recovery operations
# ---------------------------------------------------------------------------

class TestRegistryRecovery:
    def test_51_running_marked_as_interrupted(self):
        reg = _make_registry()
        r = reg.create_and_register()
        r.transition(_state("dispatched"))
        r.transition(_state("running"))
        count = reg.mark_all_running_as_interrupted(reason="restart")
        assert count >= 1
        assert reg.get(r.execution_id).lifecycle_state.value == "interrupted"

    def test_52_dispatched_marked_as_interrupted(self):
        reg = _make_registry()
        r = reg.create_and_register()
        r.transition(_state("dispatched"))
        count = reg.mark_all_running_as_interrupted(reason="restart")
        assert count >= 1
        assert reg.get(r.execution_id).lifecycle_state.value == "interrupted"

    def test_53_created_cancelled(self):
        reg = _make_registry()
        r = reg.create_and_register()
        # still in 'created' state
        count = reg.mark_all_running_as_interrupted(reason="restart")
        assert count >= 1
        assert reg.get(r.execution_id).lifecycle_state.value == "cancelled"

    def test_54_terminal_records_unchanged(self):
        reg = _make_registry()
        r = reg.create_and_register()
        r.transition(_state("dispatched"))
        r.transition(_state("running"))
        r.transition(_state("completed"))
        reg.mark_all_running_as_interrupted(reason="restart")
        assert reg.get(r.execution_id).lifecycle_state.value == "completed"

    def test_55_already_interrupted_unchanged(self):
        reg = _make_registry()
        r = reg.create_and_register()
        r.transition(_state("dispatched"))
        r.transition(_state("running"))
        r.transition(_state("interrupted"), reason="first_interrupt")
        # Mark again — should leave it as interrupted (not double-count)
        count = reg.mark_all_running_as_interrupted(reason="second_restart")
        assert count == 0
        assert reg.get(r.execution_id).lifecycle_state.value == "interrupted"

    def test_56_returns_correct_count(self):
        reg = _make_registry()
        # 2 running, 1 terminal, 1 already interrupted
        for _ in range(2):
            r = reg.create_and_register()
            r.transition(_state("dispatched"))
            r.transition(_state("running"))
        r_done = reg.create_and_register()
        r_done.transition(_state("dispatched"))
        r_done.transition(_state("running"))
        r_done.transition(_state("completed"))
        r_intr = reg.create_and_register()
        r_intr.transition(_state("dispatched"))
        r_intr.transition(_state("running"))
        r_intr.transition(_state("interrupted"), reason="prev")
        count = reg.mark_all_running_as_interrupted(reason="restart")
        assert count == 2  # only the 2 running ones

    def test_57_clear_terminal_removes_only_terminal(self):
        reg = _make_registry()
        r_active = reg.create_and_register()
        r_done = reg.create_and_register()
        r_done.transition(_state("dispatched"))
        r_done.transition(_state("running"))
        r_done.transition(_state("completed"))
        reg.clear_terminal()
        assert reg.get(r_active.execution_id) is not None
        assert reg.get(r_done.execution_id) is None

    def test_58_clear_terminal_returns_count(self):
        reg = _make_registry()
        for _ in range(3):
            r = reg.create_and_register()
            r.transition(_state("dispatched"))
            r.transition(_state("running"))
            r.transition(_state("failed"))
        removed = reg.clear_terminal()
        assert removed == 3
        assert reg.count() == 0


# ---------------------------------------------------------------------------
# 59–60: RuntimeRecoveryReport — new field
# ---------------------------------------------------------------------------

class TestRecoveryReportNewField:
    def test_59_hybrid_executions_interrupted_field_exists(self):
        from core.runtime_restart_recovery import RuntimeRecoveryReport
        report = RuntimeRecoveryReport()
        assert hasattr(report, "hybrid_executions_interrupted")
        assert report.hybrid_executions_interrupted == 0

    def test_60_to_dict_includes_hybrid_field(self):
        from core.runtime_restart_recovery import RuntimeRecoveryReport
        report = RuntimeRecoveryReport()
        d = report.to_dict()
        assert "hybrid_executions_interrupted" in d


# ---------------------------------------------------------------------------
# 61–65: RuntimeRestartRecoveryCoordinator — hybrid step
# ---------------------------------------------------------------------------

class TestCoordinatorHybridStep:
    def setup_method(self):
        _reset_registry()

    def test_61_run_recovery_sets_hybrid_field(self):
        from core.runtime_restart_recovery import RuntimeRestartRecoveryCoordinator
        reg = _make_registry()
        coordinator = RuntimeRestartRecoveryCoordinator(
            hybrid_continuity_registry=reg,
        )
        report = coordinator.run_recovery()
        assert hasattr(report, "hybrid_executions_interrupted")

    def test_62_run_recovery_marks_inflight_interrupted(self):
        from core.runtime_restart_recovery import RuntimeRestartRecoveryCoordinator
        reg = _make_registry()
        r = reg.create_and_register()
        r.transition(_state("dispatched"))
        r.transition(_state("running"))
        coordinator = RuntimeRestartRecoveryCoordinator(
            hybrid_continuity_registry=reg,
        )
        report = coordinator.run_recovery()
        assert report.hybrid_executions_interrupted >= 1
        assert reg.get(r.execution_id).lifecycle_state.value == "interrupted"

    def test_63_run_recovery_terminal_only_marks_zero(self):
        from core.runtime_restart_recovery import RuntimeRestartRecoveryCoordinator
        reg = _make_registry()
        r = reg.create_and_register()
        r.transition(_state("dispatched"))
        r.transition(_state("running"))
        r.transition(_state("completed"))
        coordinator = RuntimeRestartRecoveryCoordinator(
            hybrid_continuity_registry=reg,
        )
        report = coordinator.run_recovery()
        assert report.hybrid_executions_interrupted == 0

    def test_64_non_goals_includes_hybrid_transport_note(self):
        from core.runtime_restart_recovery import RuntimeRestartRecoveryCoordinator
        reg = _make_registry()
        coordinator = RuntimeRestartRecoveryCoordinator(
            hybrid_continuity_registry=reg,
        )
        report = coordinator.run_recovery()
        combined = " ".join(report.non_goals).lower()
        # Should mention hybrid transport handles are ephemeral
        assert "hybrid" in combined

    def test_65_run_recovery_empty_registry_no_error(self):
        from core.runtime_restart_recovery import RuntimeRestartRecoveryCoordinator
        reg = _make_registry()
        coordinator = RuntimeRestartRecoveryCoordinator(
            hybrid_continuity_registry=reg,
        )
        report = coordinator.run_recovery()
        assert report.hybrid_executions_interrupted == 0
        assert report.completed_at is not None


# ---------------------------------------------------------------------------
# 66–67: run_startup_recovery — hybrid parameter
# ---------------------------------------------------------------------------

class TestRunStartupRecoveryHybrid:
    def setup_method(self):
        _reset_registry()

    def test_66_accepts_hybrid_continuity_registry_parameter(self):
        from core.runtime_restart_recovery import run_startup_recovery
        reg = _make_registry()
        report = run_startup_recovery(hybrid_continuity_registry=reg)
        assert report is not None

    def test_67_returns_report_with_hybrid_field(self):
        from core.runtime_restart_recovery import run_startup_recovery
        reg = _make_registry()
        r = reg.create_and_register()
        r.transition(_state("dispatched"))
        r.transition(_state("running"))
        report = run_startup_recovery(hybrid_continuity_registry=reg)
        assert report.hybrid_executions_interrupted >= 1


# ---------------------------------------------------------------------------
# 68–70: Durability boundary assertions
# ---------------------------------------------------------------------------

class TestDurabilityBoundaryAssertions:
    def test_68_ephemeral_sentinel_mentions_a2a_gui_vlm(self):
        from core.hybrid_orchestration_continuity import (
            HYBRID_TRANSPORT_HANDLES_ARE_EPHEMERAL_POLICY,
        )
        text = HYBRID_TRANSPORT_HANDLES_ARE_EPHEMERAL_POLICY.upper()
        assert "A2A" in text
        assert "GUI" in text
        assert "VLM" in text

    def test_69_canonical_path_sentinel_denies_degrade_only(self):
        from core.hybrid_orchestration_continuity import (
            HYBRID_LIFECYCLE_IS_CANONICAL_ORCHESTRATION_PATH_POLICY,
        )
        text = HYBRID_LIFECYCLE_IS_CANONICAL_ORCHESTRATION_PATH_POLICY.lower()
        # Should affirm canonical path, not just degrade-only
        assert "canonical" in text

    def test_70_interrupted_is_non_terminal_resumable(self):
        from core.hybrid_orchestration_continuity import (
            HybridOrchestrationLifecycleState,
        )
        interrupted = HybridOrchestrationLifecycleState.interrupted
        assert interrupted.is_terminal is False
        assert interrupted.is_recoverable is True
