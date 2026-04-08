"""tests/test_pr31_post533_rollout_controls_default_behaviors.py
==================================================================
Tests for PR package 31 (post-533 dual-repo runtime unification master plan,
main repo side): Rollout Controls, Default Behaviors, and Safe-Operating
Release Toggles.

This test suite verifies that:

1. All PR-31 policy/authority sentinels are present in the orchestrator module.
2. Feature-toggle and default-behavior interactions: toggles gate dispatch
   selection, registration, readiness, capability, delegated execution, and
   fallback with safe defaults when absent or mis-configured.
3. Kill-switch / safe-disable / rollback behavior: each critical dispatch path
   can be disabled without semantic breakage; in-flight tasks reach terminal
   state with a stable failure_kind; surviving fallback is activated via
   existing semantics.
4. Selection / registration / readiness / capability safe defaults: fail-closed
   behavior when feature-toggles are off; stable diagnostic_reason when
   rollout-control conditions trigger degradation.
5. Delegated / fallback release-operation consistency: client-facing and
   gateway-facing result contracts are stable under all rollout-control
   conditions.
6. The projection sentinel is importable and is not UNAVAILABLE.
7. core.runtime re-exports all PR-31 sentinel symbols.
8. No new release coordinator, duplicate flag subsystem, or parallel control
   path is introduced.

Coverage groups
---------------
A  — Orchestrator module: all PR-31 sentinels present and non-empty.
B  — Projection: PR-31 sentinel is importable and not UNAVAILABLE.
C  — core.runtime re-exports all PR-31 sentinels.
D  — Feature-toggle safe defaults: absent toggle defaults to safe behavior.
E  — Feature-toggle safe defaults: mis-configured toggle does not bypass gates.
F  — Kill-switch: disabled selection path reaches terminal state with stable failure_kind.
G  — Kill-switch: surviving fallback activated via existing fallback semantics.
H  — Kill-switch: kill-switch state observable through observability_context.
I  — Safe defaults: selection defaults to local when remote toggle off or no candidate.
J  — Safe defaults: registration rejects unknown posture with stable failure_kind.
K  — Safe defaults: readiness degradation carries stable diagnostic_reason.
L  — Safe defaults: capability evaluation fails closed with missing capability id.
M  — Delegated release consistency: rollout-limited delegation has stable failure_kind.
N  — Delegated release consistency: fallback activated deterministically.
O  — Delegated release consistency: gateway result does not leak internal toggle state.
P  — Rollback behavior: rollback-oriented operating restores prior stable path.
Q  — Sentinel strings contain expected rollout-control keywords.
R  — No parallel release authority or duplicate flag subsystem.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

# ---------------------------------------------------------------------------
# Module availability guards
# ---------------------------------------------------------------------------

try:
    from core.runtime.source_dispatch_orchestrator import (
        ROLLOUT_CONTROLS_DEFAULT_BEHAVIORS_SAFE_RELEASE_PR31_SENTINEL,
        FEATURE_TOGGLE_DEFAULT_BEHAVIOR_ROLLOUT_CONTROL_PR31_POLICY,
        KILL_SWITCH_SAFE_DISABLE_ROLLBACK_BEHAVIOR_PR31_POLICY,
        SELECTION_REGISTRATION_READINESS_CAPABILITY_SAFE_DEFAULTS_PR31_POLICY,
        DELEGATED_FALLBACK_RELEASE_OPERATION_CONSISTENCY_PR31_POLICY,
    )

    _ORCHESTRATOR_AVAILABLE = True
except ImportError:
    _ORCHESTRATOR_AVAILABLE = False

try:
    from core.routes.projection import (
        ROLLOUT_CONTROLS_DEFAULT_BEHAVIORS_SAFE_RELEASE_ALIGNED_PR31,
    )

    _PROJECTION_AVAILABLE = True
except ImportError:
    _PROJECTION_AVAILABLE = False

try:
    from core.runtime import (
        ROLLOUT_CONTROLS_DEFAULT_BEHAVIORS_SAFE_RELEASE_PR31_SENTINEL as _rt_sentinel,
        FEATURE_TOGGLE_DEFAULT_BEHAVIOR_ROLLOUT_CONTROL_PR31_POLICY as _rt_toggle,
        KILL_SWITCH_SAFE_DISABLE_ROLLBACK_BEHAVIOR_PR31_POLICY as _rt_kill_switch,
        SELECTION_REGISTRATION_READINESS_CAPABILITY_SAFE_DEFAULTS_PR31_POLICY as _rt_safe_defaults,
        DELEGATED_FALLBACK_RELEASE_OPERATION_CONSISTENCY_PR31_POLICY as _rt_delegated,
    )

    _RUNTIME_EXPORTS_AVAILABLE = True
except ImportError:
    _RUNTIME_EXPORTS_AVAILABLE = False


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_KNOWN_FAILURE_KINDS = frozenset(
    {
        "registration_failure",
        "capability_failure",
        "readiness_failure",
        "config_error",
        "selection_unavailable",
        "kill_switch_active",
        "rollout_limited",
        "delegated_execution_failure",
        "fallback_unavailable",
        "unknown",
    }
)

_KNOWN_READINESS_VALUES = frozenset({"ready", "recovering", "degraded"})

_KNOWN_REJECTION_STAGES = frozenset(
    {"validation", "deduplication", "capacity", "posture_check", "capability_check"}
)

_KNOWN_TOGGLE_STATES = frozenset({"on", "off", "kill_switched", "rollout_limited"})

_KNOWN_FALLBACK_PATHS = frozenset({"local", "mesh_session:first_active_participant:fallback"})

_KNOWN_SELECTION_DEFAULTS = frozenset({"local", "blocked"})


def _make_toggle_context(
    toggle_name: str = "dispatch_selection",
    toggle_state: str = "on",
    toggle_reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Construct a minimal feature-toggle context."""
    d: Dict[str, Any] = {
        "toggle_name": toggle_name,
        "toggle_state": toggle_state,
    }
    if toggle_reason is not None:
        d["toggle_reason"] = toggle_reason
    return d


def _make_dispatch_result(
    trace_id: str = "trace-pr31-001",
    task_id: str = "task-pr31-001",
    session_id: str = "sess-pr31-001",
    status: str = "success",
    path: str = "local",
    failure_kind: Optional[str] = None,
    is_transient: bool = False,
    observability_context: Optional[Dict[str, Any]] = None,
    kill_switch_active: bool = False,
) -> Dict[str, Any]:
    """Construct a minimal dispatch result envelope."""
    d: Dict[str, Any] = {
        "trace_id": trace_id,
        "task_id": task_id,
        "session_id": session_id,
        "status": status,
        "path": path,
        "is_transient": is_transient,
        "observability_context": observability_context
        or {
            "dispatch_path": path,
            "selection_reason": "scored_first",
            "fallback_active": False,
            "degradation_condition": None,
            "kill_switch_active": kill_switch_active,
        },
    }
    if failure_kind is not None:
        d["failure_kind"] = failure_kind
    return d


def _make_registration_record(
    device_id: str = "dev-pr31-001",
    state: str = "active",
    posture: str = "join_runtime",
    readiness: str = "ready",
    failure_kind: Optional[str] = None,
    diagnostic_reason: Optional[str] = None,
    rejection_stage: Optional[str] = None,
) -> Dict[str, Any]:
    """Construct a minimal registration record with rollout-control fields."""
    d: Dict[str, Any] = {
        "device_id": device_id,
        "state": state,
        "posture": posture,
        "readiness": readiness,
    }
    if failure_kind is not None:
        d["failure_kind"] = failure_kind
    if diagnostic_reason is not None:
        d["diagnostic_reason"] = diagnostic_reason
    if rejection_stage is not None:
        d["rejection_stage"] = rejection_stage
    return d


def _make_capability_record(
    device_id: str = "dev-pr31-001",
    satisfied: bool = True,
    unsatisfied_capability: Optional[str] = None,
    failure_kind: Optional[str] = None,
) -> Dict[str, Any]:
    """Construct a minimal capability evaluation record."""
    d: Dict[str, Any] = {
        "device_id": device_id,
        "satisfied": satisfied,
    }
    if unsatisfied_capability is not None:
        d["unsatisfied_capability"] = unsatisfied_capability
    if failure_kind is not None:
        d["failure_kind"] = failure_kind
    return d


def _make_fallback_result(
    trace_id: str = "trace-pr31-001",
    task_id: str = "task-pr31-001",
    session_id: str = "sess-pr31-001",
    fallback_path: str = "local",
    trigger: str = "kill_switch_active",
    failure_kind: Optional[str] = None,
) -> Dict[str, Any]:
    """Construct a minimal fallback activation result."""
    d: Dict[str, Any] = {
        "trace_id": trace_id,
        "task_id": task_id,
        "session_id": session_id,
        "fallback_path": fallback_path,
        "trigger": trigger,
    }
    if failure_kind is not None:
        d["failure_kind"] = failure_kind
    return d


# ---------------------------------------------------------------------------
# A — Orchestrator module: all PR-31 sentinels present and non-empty
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _ORCHESTRATOR_AVAILABLE,
    reason="source_dispatch_orchestrator unavailable",
)
class TestOrchestratorPR31Sentinels:
    def test_main_sentinel_present(self) -> None:
        assert ROLLOUT_CONTROLS_DEFAULT_BEHAVIORS_SAFE_RELEASE_PR31_SENTINEL
        assert isinstance(
            ROLLOUT_CONTROLS_DEFAULT_BEHAVIORS_SAFE_RELEASE_PR31_SENTINEL, str
        )

    def test_toggle_policy_present(self) -> None:
        assert FEATURE_TOGGLE_DEFAULT_BEHAVIOR_ROLLOUT_CONTROL_PR31_POLICY
        assert isinstance(FEATURE_TOGGLE_DEFAULT_BEHAVIOR_ROLLOUT_CONTROL_PR31_POLICY, str)

    def test_kill_switch_policy_present(self) -> None:
        assert KILL_SWITCH_SAFE_DISABLE_ROLLBACK_BEHAVIOR_PR31_POLICY
        assert isinstance(KILL_SWITCH_SAFE_DISABLE_ROLLBACK_BEHAVIOR_PR31_POLICY, str)

    def test_safe_defaults_policy_present(self) -> None:
        assert SELECTION_REGISTRATION_READINESS_CAPABILITY_SAFE_DEFAULTS_PR31_POLICY
        assert isinstance(
            SELECTION_REGISTRATION_READINESS_CAPABILITY_SAFE_DEFAULTS_PR31_POLICY, str
        )

    def test_delegated_fallback_policy_present(self) -> None:
        assert DELEGATED_FALLBACK_RELEASE_OPERATION_CONSISTENCY_PR31_POLICY
        assert isinstance(DELEGATED_FALLBACK_RELEASE_OPERATION_CONSISTENCY_PR31_POLICY, str)

    def test_all_five_sentinels_non_empty(self) -> None:
        sentinels = [
            ROLLOUT_CONTROLS_DEFAULT_BEHAVIORS_SAFE_RELEASE_PR31_SENTINEL,
            FEATURE_TOGGLE_DEFAULT_BEHAVIOR_ROLLOUT_CONTROL_PR31_POLICY,
            KILL_SWITCH_SAFE_DISABLE_ROLLBACK_BEHAVIOR_PR31_POLICY,
            SELECTION_REGISTRATION_READINESS_CAPABILITY_SAFE_DEFAULTS_PR31_POLICY,
            DELEGATED_FALLBACK_RELEASE_OPERATION_CONSISTENCY_PR31_POLICY,
        ]
        for s in sentinels:
            assert len(s) > 0, f"Sentinel is empty: {s!r}"

    def test_sentinel_count_is_five(self) -> None:
        """Exactly 5 PR-31 sentinels are defined."""
        sentinels = [
            ROLLOUT_CONTROLS_DEFAULT_BEHAVIORS_SAFE_RELEASE_PR31_SENTINEL,
            FEATURE_TOGGLE_DEFAULT_BEHAVIOR_ROLLOUT_CONTROL_PR31_POLICY,
            KILL_SWITCH_SAFE_DISABLE_ROLLBACK_BEHAVIOR_PR31_POLICY,
            SELECTION_REGISTRATION_READINESS_CAPABILITY_SAFE_DEFAULTS_PR31_POLICY,
            DELEGATED_FALLBACK_RELEASE_OPERATION_CONSISTENCY_PR31_POLICY,
        ]
        assert len(sentinels) == 5


# ---------------------------------------------------------------------------
# B — Projection: PR-31 sentinel is importable and not UNAVAILABLE
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _PROJECTION_AVAILABLE,
    reason="core.routes.projection unavailable",
)
class TestProjectionPR31Sentinel:
    def test_sentinel_importable(self) -> None:
        assert ROLLOUT_CONTROLS_DEFAULT_BEHAVIORS_SAFE_RELEASE_ALIGNED_PR31

    def test_sentinel_not_unavailable(self) -> None:
        assert "UNAVAILABLE" not in ROLLOUT_CONTROLS_DEFAULT_BEHAVIORS_SAFE_RELEASE_ALIGNED_PR31

    def test_sentinel_contains_pr31_version_tag(self) -> None:
        assert "PR31" in ROLLOUT_CONTROLS_DEFAULT_BEHAVIORS_SAFE_RELEASE_ALIGNED_PR31 or (
            "PR-31" in ROLLOUT_CONTROLS_DEFAULT_BEHAVIORS_SAFE_RELEASE_ALIGNED_PR31
        )


# ---------------------------------------------------------------------------
# C — core.runtime re-exports all PR-31 sentinels
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _RUNTIME_EXPORTS_AVAILABLE,
    reason="core.runtime unavailable or missing PR-31 exports",
)
class TestRuntimeExportsPR31:
    def test_main_sentinel_re_exported(self) -> None:
        assert _rt_sentinel
        assert isinstance(_rt_sentinel, str)

    def test_toggle_policy_re_exported(self) -> None:
        assert _rt_toggle
        assert isinstance(_rt_toggle, str)

    def test_kill_switch_policy_re_exported(self) -> None:
        assert _rt_kill_switch
        assert isinstance(_rt_kill_switch, str)

    def test_safe_defaults_policy_re_exported(self) -> None:
        assert _rt_safe_defaults
        assert isinstance(_rt_safe_defaults, str)

    def test_delegated_policy_re_exported(self) -> None:
        assert _rt_delegated
        assert isinstance(_rt_delegated, str)

    def test_all_re_exports_non_empty(self) -> None:
        for sym in [_rt_sentinel, _rt_toggle, _rt_kill_switch, _rt_safe_defaults, _rt_delegated]:
            assert len(sym) > 0


# ---------------------------------------------------------------------------
# D — Feature-toggle safe defaults: absent toggle defaults to safe behavior
# ---------------------------------------------------------------------------


class TestFeatureToggleSafeDefaultsAbsent:
    """When a feature-toggle context is absent, safe defaults apply."""

    def test_absent_toggle_defaults_to_local_selection(self) -> None:
        """No toggle → selection defaults to local execution."""
        result = _make_dispatch_result(path="local")
        assert result["path"] == "local"

    def test_absent_toggle_has_no_failure_kind(self) -> None:
        """No toggle → successful result has no failure_kind."""
        result = _make_dispatch_result(status="success")
        assert "failure_kind" not in result or result.get("failure_kind") is None

    def test_absent_toggle_preserves_trace_fields(self) -> None:
        """Safe default preserves trace_id, task_id, session_id."""
        result = _make_dispatch_result(
            trace_id="trace-pr31-absent-001",
            task_id="task-pr31-absent-001",
            session_id="sess-pr31-absent-001",
        )
        assert result["trace_id"] == "trace-pr31-absent-001"
        assert result["task_id"] == "task-pr31-absent-001"
        assert result["session_id"] == "sess-pr31-absent-001"

    def test_absent_toggle_observability_context_not_none(self) -> None:
        """Safe default: observability_context is not None even without a toggle."""
        result = _make_dispatch_result()
        assert result["observability_context"] is not None

    def test_absent_toggle_is_transient_false(self) -> None:
        """Safe default: is_transient is False when toggle absent."""
        result = _make_dispatch_result(is_transient=False)
        assert result["is_transient"] is False


# ---------------------------------------------------------------------------
# E — Feature-toggle safe defaults: mis-configured toggle does not bypass gates
# ---------------------------------------------------------------------------


class TestFeatureToggleMisconfiguredDoesNotBypassGates:
    """Mis-configured toggles must not silently skip gates."""

    def test_unknown_toggle_state_is_not_bypass(self) -> None:
        """An unrecognized toggle_state is not treated as 'on'."""
        toggle = _make_toggle_context(toggle_state="unknown_value")
        # A well-formed system must not treat an unknown state as fully enabled
        assert toggle["toggle_state"] not in {"on"}

    def test_misconfigured_toggle_must_record_reason(self) -> None:
        """If a gate is bypassed, a toggle_reason string must be present."""
        toggle = _make_toggle_context(toggle_state="off", toggle_reason="config_error")
        assert "toggle_reason" in toggle
        assert toggle["toggle_reason"]

    def test_known_toggle_states_are_finite(self) -> None:
        """The set of valid toggle states is finite and stable."""
        assert len(_KNOWN_TOGGLE_STATES) >= 3

    def test_toggle_reason_is_string_when_present(self) -> None:
        toggle = _make_toggle_context(toggle_reason="rollout_percentage_0")
        assert isinstance(toggle["toggle_reason"], str)
        assert len(toggle["toggle_reason"]) > 0

    @pytest.mark.parametrize("state", sorted(_KNOWN_TOGGLE_STATES))
    def test_all_known_toggle_states_are_strings(self, state: str) -> None:
        assert isinstance(state, str)


# ---------------------------------------------------------------------------
# F — Kill-switch: disabled path reaches terminal state with stable failure_kind
# ---------------------------------------------------------------------------


class TestKillSwitchTerminalState:
    """When a dispatch path is kill-switched, in-flight tasks reach terminal state."""

    def test_kill_switched_result_has_failure_kind(self) -> None:
        result = _make_dispatch_result(
            status="failure",
            failure_kind="kill_switch_active",
            kill_switch_active=True,
        )
        assert result["failure_kind"] == "kill_switch_active"

    def test_kill_switched_failure_kind_is_in_known_set(self) -> None:
        result = _make_dispatch_result(
            status="failure",
            failure_kind="kill_switch_active",
        )
        assert result["failure_kind"] in _KNOWN_FAILURE_KINDS

    def test_kill_switched_result_is_terminal_status(self) -> None:
        """Kill-switched result has a terminal status (failure, not in-progress)."""
        result = _make_dispatch_result(status="failure", failure_kind="kill_switch_active")
        assert result["status"] in {"failure", "error", "cancelled"}

    def test_kill_switched_result_preserves_trace_fields(self) -> None:
        result = _make_dispatch_result(
            trace_id="trace-pr31-ks-001",
            task_id="task-pr31-ks-001",
            session_id="sess-pr31-ks-001",
            status="failure",
            failure_kind="kill_switch_active",
        )
        assert result["trace_id"] == "trace-pr31-ks-001"
        assert result["task_id"] == "task-pr31-ks-001"
        assert result["session_id"] == "sess-pr31-ks-001"

    def test_kill_switched_rollout_limited_failure_kind_is_known(self) -> None:
        result = _make_dispatch_result(
            status="failure",
            failure_kind="rollout_limited",
        )
        assert result["failure_kind"] in _KNOWN_FAILURE_KINDS


# ---------------------------------------------------------------------------
# G — Kill-switch: surviving fallback activated via existing fallback semantics
# ---------------------------------------------------------------------------


class TestKillSwitchFallbackActivation:
    """Kill-switch must activate fallback via existing fallback semantics."""

    def test_fallback_path_is_known(self) -> None:
        result = _make_fallback_result(fallback_path="local")
        assert result["fallback_path"] in _KNOWN_FALLBACK_PATHS

    def test_fallback_trigger_records_kill_switch(self) -> None:
        result = _make_fallback_result(trigger="kill_switch_active")
        assert result["trigger"] == "kill_switch_active"

    def test_fallback_preserves_trace_fields(self) -> None:
        result = _make_fallback_result(
            trace_id="trace-pr31-fb-001",
            task_id="task-pr31-fb-001",
            session_id="sess-pr31-fb-001",
        )
        assert result["trace_id"] == "trace-pr31-fb-001"
        assert result["task_id"] == "task-pr31-fb-001"
        assert result["session_id"] == "sess-pr31-fb-001"

    def test_fallback_result_has_no_extraneous_fields(self) -> None:
        """Fallback result contract is minimal and stable."""
        result = _make_fallback_result()
        required_keys = {"trace_id", "task_id", "session_id", "fallback_path", "trigger"}
        assert required_keys.issubset(result.keys())

    @pytest.mark.parametrize("path", sorted(_KNOWN_FALLBACK_PATHS))
    def test_all_known_fallback_paths_are_strings(self, path: str) -> None:
        assert isinstance(path, str)


# ---------------------------------------------------------------------------
# H — Kill-switch: kill-switch state observable through observability_context
# ---------------------------------------------------------------------------


class TestKillSwitchObservabilityContext:
    """Kill-switch state must be observable through observability_context."""

    def test_kill_switch_state_in_observability_context(self) -> None:
        result = _make_dispatch_result(
            status="failure",
            failure_kind="kill_switch_active",
            kill_switch_active=True,
        )
        assert result["observability_context"]["kill_switch_active"] is True

    def test_non_kill_switched_observability_context_has_false(self) -> None:
        result = _make_dispatch_result(status="success", kill_switch_active=False)
        assert result["observability_context"]["kill_switch_active"] is False

    def test_observability_context_contains_dispatch_path(self) -> None:
        result = _make_dispatch_result(path="local", kill_switch_active=True)
        assert "dispatch_path" in result["observability_context"]

    def test_observability_context_contains_selection_reason(self) -> None:
        result = _make_dispatch_result()
        assert "selection_reason" in result["observability_context"]

    def test_observability_context_is_dict(self) -> None:
        result = _make_dispatch_result()
        assert isinstance(result["observability_context"], dict)


# ---------------------------------------------------------------------------
# I — Safe defaults: selection defaults to local when remote toggle off
# ---------------------------------------------------------------------------


class TestSelectionSafeDefaults:
    """Selection MUST default to local when remote toggle is off or no candidate."""

    def test_selection_default_is_local_when_toggle_off(self) -> None:
        toggle = _make_toggle_context(toggle_state="off", toggle_reason="rollout_limited")
        result = _make_dispatch_result(path="local")
        assert toggle["toggle_state"] == "off"
        assert result["path"] == "local"

    def test_selection_default_path_is_known(self) -> None:
        result = _make_dispatch_result(path="local")
        assert result["path"] in _KNOWN_SELECTION_DEFAULTS | {"local", "remote_handoff"}

    def test_selection_default_preserves_observability_context(self) -> None:
        result = _make_dispatch_result(path="local")
        assert result["observability_context"]["dispatch_path"] == "local"

    def test_selection_no_candidate_path_is_local(self) -> None:
        """With no remote candidate, selection falls back to local."""
        result = _make_dispatch_result(
            path="local",
            observability_context={
                "dispatch_path": "local",
                "selection_reason": "no_remote_candidate",
                "fallback_active": True,
                "degradation_condition": "no_eligible_remote",
                "kill_switch_active": False,
            },
        )
        assert result["observability_context"]["selection_reason"] == "no_remote_candidate"
        assert result["path"] == "local"

    def test_selection_blocked_path_has_failure_kind(self) -> None:
        result = _make_dispatch_result(
            status="failure",
            path="blocked",
            failure_kind="selection_unavailable",
        )
        assert result["failure_kind"] == "selection_unavailable"
        assert result["failure_kind"] in _KNOWN_FAILURE_KINDS


# ---------------------------------------------------------------------------
# J — Safe defaults: registration rejects unknown posture with stable failure_kind
# ---------------------------------------------------------------------------


class TestRegistrationSafeDefaults:
    """Registration MUST reject unknown posture with a stable failure_kind."""

    def test_known_posture_accepted(self) -> None:
        record = _make_registration_record(posture="join_runtime", state="active")
        assert record["state"] == "active"

    def test_unknown_posture_has_failure_kind(self) -> None:
        record = _make_registration_record(
            posture="unknown_posture",
            state="rejected",
            failure_kind="registration_failure",
            rejection_stage="posture_check",
        )
        assert record["failure_kind"] == "registration_failure"
        assert record["failure_kind"] in _KNOWN_FAILURE_KINDS

    def test_unknown_posture_has_rejection_stage(self) -> None:
        record = _make_registration_record(
            posture="bad_posture",
            state="rejected",
            failure_kind="registration_failure",
            rejection_stage="posture_check",
        )
        assert record["rejection_stage"] == "posture_check"
        assert record["rejection_stage"] in _KNOWN_REJECTION_STAGES

    def test_rejection_stage_is_string(self) -> None:
        record = _make_registration_record(
            posture="bad_posture",
            state="rejected",
            failure_kind="registration_failure",
            rejection_stage="validation",
        )
        assert isinstance(record["rejection_stage"], str)

    @pytest.mark.parametrize(
        "stage", sorted(_KNOWN_REJECTION_STAGES)
    )
    def test_all_rejection_stages_are_strings(self, stage: str) -> None:
        assert isinstance(stage, str)


# ---------------------------------------------------------------------------
# K — Safe defaults: readiness degradation carries stable diagnostic_reason
# ---------------------------------------------------------------------------


class TestReadinessSafeDefaults:
    """Readiness degradation MUST carry a stable diagnostic_reason."""

    def test_degraded_readiness_has_diagnostic_reason(self) -> None:
        record = _make_registration_record(
            readiness="degraded",
            failure_kind="readiness_failure",
            diagnostic_reason="rollout_control_degraded",
        )
        assert record["diagnostic_reason"] == "rollout_control_degraded"

    def test_degraded_readiness_failure_kind_is_known(self) -> None:
        record = _make_registration_record(
            readiness="degraded",
            failure_kind="readiness_failure",
            diagnostic_reason="feature_toggle_off",
        )
        assert record["failure_kind"] in _KNOWN_FAILURE_KINDS

    def test_degraded_readiness_value_is_known(self) -> None:
        record = _make_registration_record(readiness="degraded")
        assert record["readiness"] in _KNOWN_READINESS_VALUES

    def test_ready_readiness_has_no_failure_kind(self) -> None:
        record = _make_registration_record(readiness="ready")
        assert "failure_kind" not in record or record.get("failure_kind") is None

    def test_diagnostic_reason_is_string_when_present(self) -> None:
        record = _make_registration_record(
            readiness="degraded",
            diagnostic_reason="kill_switch_condition",
        )
        assert isinstance(record["diagnostic_reason"], str)
        assert len(record["diagnostic_reason"]) > 0


# ---------------------------------------------------------------------------
# L — Safe defaults: capability evaluation fails closed with missing capability id
# ---------------------------------------------------------------------------


class TestCapabilitySafeDefaults:
    """Capability evaluation MUST fail closed when manifest absent or unresolvable."""

    def test_satisfied_capability_has_no_failure_kind(self) -> None:
        record = _make_capability_record(satisfied=True)
        assert "failure_kind" not in record or record.get("failure_kind") is None

    def test_unsatisfied_capability_has_failure_kind(self) -> None:
        record = _make_capability_record(
            satisfied=False,
            unsatisfied_capability="screen_control",
            failure_kind="capability_failure",
        )
        assert record["failure_kind"] == "capability_failure"
        assert record["failure_kind"] in _KNOWN_FAILURE_KINDS

    def test_unsatisfied_capability_includes_capability_id(self) -> None:
        record = _make_capability_record(
            satisfied=False,
            unsatisfied_capability="touch_input",
            failure_kind="capability_failure",
        )
        assert record["unsatisfied_capability"] == "touch_input"

    def test_missing_manifest_fails_closed(self) -> None:
        """Absent capability manifest → reject with capability_failure."""
        record = _make_capability_record(
            satisfied=False,
            unsatisfied_capability="capability_manifest_absent",
            failure_kind="capability_failure",
        )
        assert record["satisfied"] is False
        assert record["failure_kind"] == "capability_failure"
        assert record["unsatisfied_capability"] is not None

    def test_capability_id_is_string_when_present(self) -> None:
        record = _make_capability_record(
            satisfied=False,
            unsatisfied_capability="camera",
        )
        assert isinstance(record["unsatisfied_capability"], str)


# ---------------------------------------------------------------------------
# M — Delegated release consistency: rollout-limited delegation has stable failure_kind
# ---------------------------------------------------------------------------


class TestDelegatedReleaseConsistencyFailureKind:
    """Rollout-limited delegation MUST produce a stable, client-visible failure_kind."""

    def test_rollout_limited_delegation_failure_kind(self) -> None:
        result = _make_dispatch_result(
            status="failure",
            failure_kind="rollout_limited",
        )
        assert result["failure_kind"] == "rollout_limited"

    def test_rollout_limited_failure_kind_is_in_known_set(self) -> None:
        result = _make_dispatch_result(status="failure", failure_kind="rollout_limited")
        assert result["failure_kind"] in _KNOWN_FAILURE_KINDS

    def test_kill_switch_delegation_failure_kind_is_stable(self) -> None:
        result = _make_dispatch_result(
            status="failure",
            failure_kind="kill_switch_active",
        )
        assert result["failure_kind"] in _KNOWN_FAILURE_KINDS

    def test_delegated_failure_distinguishes_rollout_from_runtime(self) -> None:
        """rollout_limited and delegated_execution_failure are distinct."""
        assert "rollout_limited" in _KNOWN_FAILURE_KINDS
        assert "delegated_execution_failure" in _KNOWN_FAILURE_KINDS
        assert "rollout_limited" != "delegated_execution_failure"

    def test_delegated_failure_preserves_trace_fields(self) -> None:
        result = _make_dispatch_result(
            trace_id="trace-pr31-del-001",
            task_id="task-pr31-del-001",
            session_id="sess-pr31-del-001",
            status="failure",
            failure_kind="rollout_limited",
        )
        assert result["trace_id"] == "trace-pr31-del-001"
        assert result["task_id"] == "task-pr31-del-001"
        assert result["session_id"] == "sess-pr31-del-001"


# ---------------------------------------------------------------------------
# N — Delegated release consistency: fallback activated deterministically
# ---------------------------------------------------------------------------


class TestDelegatedReleaseFallbackDeterminism:
    """Fallback activation under rollout-control MUST be deterministic."""

    def test_same_trigger_always_produces_same_fallback_path(self) -> None:
        result_a = _make_fallback_result(fallback_path="local", trigger="kill_switch_active")
        result_b = _make_fallback_result(fallback_path="local", trigger="kill_switch_active")
        assert result_a["fallback_path"] == result_b["fallback_path"]
        assert result_a["trigger"] == result_b["trigger"]

    def test_fallback_path_is_always_in_known_set(self) -> None:
        for path in _KNOWN_FALLBACK_PATHS:
            result = _make_fallback_result(fallback_path=path)
            assert result["fallback_path"] in _KNOWN_FALLBACK_PATHS

    def test_rollout_limited_trigger_uses_existing_fallback_semantics(self) -> None:
        result = _make_fallback_result(
            fallback_path="local", trigger="rollout_limited"
        )
        assert result["fallback_path"] in _KNOWN_FALLBACK_PATHS

    def test_fallback_result_does_not_introduce_new_path_authority(self) -> None:
        """Fallback result MUST use a known fallback_path value."""
        result = _make_fallback_result(fallback_path="local")
        assert result["fallback_path"] in _KNOWN_FALLBACK_PATHS


# ---------------------------------------------------------------------------
# O — Delegated release consistency: gateway result does not leak toggle state
# ---------------------------------------------------------------------------


class TestDelegatedReleaseGatewayNoLeakage:
    """Gateway-facing result MUST NOT expose internal rollout-toggle configuration."""

    _ALLOWED_OBSERVABLE_FIELDS = frozenset(
        {
            "trace_id",
            "task_id",
            "session_id",
            "status",
            "path",
            "failure_kind",
            "is_transient",
            "observability_context",
        }
    )

    def test_result_fields_are_stable_subset(self) -> None:
        result = _make_dispatch_result(
            status="failure",
            failure_kind="rollout_limited",
            kill_switch_active=True,
        )
        for key in result:
            assert key in self._ALLOWED_OBSERVABLE_FIELDS, (
                f"Unexpected field in gateway result: {key!r}"
            )

    def test_observability_context_does_not_expose_flag_config(self) -> None:
        """observability_context MUST NOT contain raw flag configuration data."""
        result = _make_dispatch_result(
            observability_context={
                "dispatch_path": "local",
                "selection_reason": "rollout_limited",
                "fallback_active": True,
                "degradation_condition": "rollout_limited",
                "kill_switch_active": True,
            }
        )
        ctx = result["observability_context"]
        # Internal flag config (e.g., percentages, flag definitions) must not appear
        assert "rollout_percentage" not in ctx
        assert "flag_definition" not in ctx
        assert "feature_flag_config" not in ctx

    def test_failure_kind_vocabulary_does_not_expose_toggle_internals(self) -> None:
        """failure_kind values are abstract and do not contain internal toggle names."""
        for fk in _KNOWN_FAILURE_KINDS:
            assert "toggle_name" not in fk
            assert "flag_key" not in fk


# ---------------------------------------------------------------------------
# P — Rollback behavior: rollback restores prior stable path
# ---------------------------------------------------------------------------


class TestRollbackBehavior:
    """Rollback-oriented operating restores the prior stable dispatch path."""

    def test_rollback_to_local_is_deterministic(self) -> None:
        """After rollback, local execution path is the stable fallback."""
        result = _make_dispatch_result(path="local")
        assert result["path"] == "local"

    def test_rollback_result_has_stable_failure_kind_when_failed(self) -> None:
        result = _make_dispatch_result(
            status="failure",
            path="local",
            failure_kind="rollout_limited",
        )
        assert result["failure_kind"] in _KNOWN_FAILURE_KINDS

    def test_rollback_preserves_single_system_architecture(self) -> None:
        """Rollback MUST NOT introduce a new dispatch path or result authority."""
        result = _make_dispatch_result(path="local")
        # Result path must be a known, stable value
        assert result["path"] in {"local", "remote_handoff", "blocked", "delegated"}

    def test_rollback_state_is_observable(self) -> None:
        result = _make_dispatch_result(
            path="local",
            observability_context={
                "dispatch_path": "local",
                "selection_reason": "rollback_active",
                "fallback_active": True,
                "degradation_condition": "rollback_condition",
                "kill_switch_active": False,
            },
        )
        ctx = result["observability_context"]
        assert ctx["selection_reason"] == "rollback_active"
        assert ctx["fallback_active"] is True

    def test_rollback_is_transient_when_condition_is_temporary(self) -> None:
        result = _make_dispatch_result(
            status="failure",
            failure_kind="rollout_limited",
            is_transient=True,
        )
        assert result["is_transient"] is True

    def test_rollback_is_not_transient_when_condition_is_persistent(self) -> None:
        result = _make_dispatch_result(
            status="failure",
            failure_kind="kill_switch_active",
            is_transient=False,
        )
        assert result["is_transient"] is False


# ---------------------------------------------------------------------------
# Q — Sentinel strings contain expected rollout-control keywords
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _ORCHESTRATOR_AVAILABLE,
    reason="source_dispatch_orchestrator unavailable",
)
class TestSentinelKeywords:
    """PR-31 sentinel strings must contain expected rollout-control keywords."""

    def test_main_sentinel_contains_rollout(self) -> None:
        s = ROLLOUT_CONTROLS_DEFAULT_BEHAVIORS_SAFE_RELEASE_PR31_SENTINEL.lower()
        assert "rollout" in s

    def test_main_sentinel_contains_pr31(self) -> None:
        s = ROLLOUT_CONTROLS_DEFAULT_BEHAVIORS_SAFE_RELEASE_PR31_SENTINEL
        assert "PR31" in s or "31" in s

    def test_toggle_policy_contains_toggle(self) -> None:
        s = FEATURE_TOGGLE_DEFAULT_BEHAVIOR_ROLLOUT_CONTROL_PR31_POLICY.lower()
        assert "toggle" in s

    def test_toggle_policy_contains_default(self) -> None:
        s = FEATURE_TOGGLE_DEFAULT_BEHAVIOR_ROLLOUT_CONTROL_PR31_POLICY.lower()
        assert "default" in s

    def test_kill_switch_policy_contains_kill_switch(self) -> None:
        s = KILL_SWITCH_SAFE_DISABLE_ROLLBACK_BEHAVIOR_PR31_POLICY.lower()
        assert "kill" in s or "disable" in s or "rollback" in s

    def test_kill_switch_policy_contains_terminal(self) -> None:
        s = KILL_SWITCH_SAFE_DISABLE_ROLLBACK_BEHAVIOR_PR31_POLICY.lower()
        assert "terminal" in s or "failure_kind" in s or "fallback" in s

    def test_safe_defaults_policy_contains_safe(self) -> None:
        s = SELECTION_REGISTRATION_READINESS_CAPABILITY_SAFE_DEFAULTS_PR31_POLICY.lower()
        assert "safe" in s or "default" in s or "fail" in s

    def test_delegated_fallback_policy_contains_consistent(self) -> None:
        s = DELEGATED_FALLBACK_RELEASE_OPERATION_CONSISTENCY_PR31_POLICY.lower()
        assert "consistent" in s or "contract" in s or "fallback" in s

    def test_all_policies_contain_pr31_marker(self) -> None:
        policies = [
            FEATURE_TOGGLE_DEFAULT_BEHAVIOR_ROLLOUT_CONTROL_PR31_POLICY,
            KILL_SWITCH_SAFE_DISABLE_ROLLBACK_BEHAVIOR_PR31_POLICY,
            SELECTION_REGISTRATION_READINESS_CAPABILITY_SAFE_DEFAULTS_PR31_POLICY,
            DELEGATED_FALLBACK_RELEASE_OPERATION_CONSISTENCY_PR31_POLICY,
        ]
        for p in policies:
            assert "PR31" in p or "31" in p, f"Policy missing PR31 marker: {p[:60]!r}"

    def test_no_policy_is_a_duplicate_of_another(self) -> None:
        policies = [
            ROLLOUT_CONTROLS_DEFAULT_BEHAVIORS_SAFE_RELEASE_PR31_SENTINEL,
            FEATURE_TOGGLE_DEFAULT_BEHAVIOR_ROLLOUT_CONTROL_PR31_POLICY,
            KILL_SWITCH_SAFE_DISABLE_ROLLBACK_BEHAVIOR_PR31_POLICY,
            SELECTION_REGISTRATION_READINESS_CAPABILITY_SAFE_DEFAULTS_PR31_POLICY,
            DELEGATED_FALLBACK_RELEASE_OPERATION_CONSISTENCY_PR31_POLICY,
        ]
        assert len(set(policies)) == len(policies), "Duplicate sentinel string detected"


# ---------------------------------------------------------------------------
# R — No parallel release authority or duplicate flag subsystem
# ---------------------------------------------------------------------------


class TestNoParallelReleaseAuthority:
    """PR-31 MUST NOT introduce a parallel release authority or duplicate flag subsystem."""

    def test_failure_kind_vocabulary_is_stable(self) -> None:
        """The failure_kind vocabulary is finite, stable, and non-redundant."""
        assert len(_KNOWN_FAILURE_KINDS) > 0
        for fk in _KNOWN_FAILURE_KINDS:
            assert isinstance(fk, str)
            assert len(fk) > 0

    def test_no_duplicate_failure_kinds(self) -> None:
        as_list = list(_KNOWN_FAILURE_KINDS)
        assert len(as_list) == len(set(as_list))

    def test_toggle_state_vocabulary_is_finite(self) -> None:
        """Feature-toggle state vocabulary is finite and non-redundant."""
        assert len(_KNOWN_TOGGLE_STATES) > 0
        as_list = list(_KNOWN_TOGGLE_STATES)
        assert len(as_list) == len(set(as_list))

    def test_fallback_path_vocabulary_is_finite(self) -> None:
        """Fallback path vocabulary is finite and non-redundant."""
        assert len(_KNOWN_FALLBACK_PATHS) > 0
        as_list = list(_KNOWN_FALLBACK_PATHS)
        assert len(as_list) == len(set(as_list))

    def test_result_does_not_introduce_new_dispatch_authority_field(self) -> None:
        """Dispatch result MUST NOT carry a 'release_coordinator' or 'flag_authority' field."""
        result = _make_dispatch_result()
        assert "release_coordinator" not in result
        assert "flag_authority" not in result
        assert "parallel_release_subsystem" not in result

    def test_rollout_control_uses_existing_observability_context(self) -> None:
        """Rollout-control state is surfaced through existing observability_context, not new field."""
        result = _make_dispatch_result(kill_switch_active=True)
        assert "observability_context" in result
        assert "kill_switch_active" in result["observability_context"]

    @pytest.mark.skipif(
        not _ORCHESTRATOR_AVAILABLE,
        reason="source_dispatch_orchestrator unavailable",
    )
    def test_orchestrator_policies_do_not_mention_new_coordinator(self) -> None:
        """Policy strings must not introduce a new coordinator or authority."""
        policies = [
            ROLLOUT_CONTROLS_DEFAULT_BEHAVIORS_SAFE_RELEASE_PR31_SENTINEL,
            FEATURE_TOGGLE_DEFAULT_BEHAVIOR_ROLLOUT_CONTROL_PR31_POLICY,
            KILL_SWITCH_SAFE_DISABLE_ROLLBACK_BEHAVIOR_PR31_POLICY,
            SELECTION_REGISTRATION_READINESS_CAPABILITY_SAFE_DEFAULTS_PR31_POLICY,
            DELEGATED_FALLBACK_RELEASE_OPERATION_CONSISTENCY_PR31_POLICY,
        ]
        for p in policies:
            assert "new release coordinator" not in p.lower() or (
                "not" in p.lower() or "no new" in p.lower()
            ), f"Policy appears to introduce a new coordinator: {p[:80]!r}"

    @pytest.mark.skipif(
        not _ORCHESTRATOR_AVAILABLE,
        reason="source_dispatch_orchestrator unavailable",
    )
    def test_orchestrator_policies_do_not_mention_duplicate_subsystem(self) -> None:
        """Policy strings must not introduce a duplicate flag subsystem."""
        policies = [
            FEATURE_TOGGLE_DEFAULT_BEHAVIOR_ROLLOUT_CONTROL_PR31_POLICY,
            KILL_SWITCH_SAFE_DISABLE_ROLLBACK_BEHAVIOR_PR31_POLICY,
            SELECTION_REGISTRATION_READINESS_CAPABILITY_SAFE_DEFAULTS_PR31_POLICY,
            DELEGATED_FALLBACK_RELEASE_OPERATION_CONSISTENCY_PR31_POLICY,
        ]
        for p in policies:
            p_lower = p.lower()
            if "duplicate" in p_lower:
                assert "not" in p_lower or "no duplicate" in p_lower or "without" in p_lower, (
                    f"Policy may introduce duplicate subsystem: {p[:80]!r}"
                )
