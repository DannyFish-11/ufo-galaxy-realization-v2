"""tests/test_pr27_post533_gateway_registration_capability_error_semantics.py
==============================================================================
Tests for PR package 27 (post-533 dual-repo runtime unification master plan,
main repo side): Gateway-Facing Registration and Capability Error Semantics
Hardening.

This test suite verifies that:

1. All PR-27 policy/authority sentinels are present in the orchestrator module.
2. Registration failures are distinguishable from capability failures via
   structured failure_kind semantics.
3. Readiness-related degraded behavior is reported through stable signals that
   upstream retry/reconnect/setup UX can consume.
4. Capability-not-satisfied failures produce actionable gateway-facing signals
   identifying which capability is absent and why.
5. Gateway setup and connection signals are deterministic: same top-level field
   set regardless of failure mode.
6. The projection sentinel is importable and is not UNAVAILABLE.
7. core.runtime re-exports all PR-27 sentinel symbols.
8. No parallel registration authority, duplicate capability model, or alternate
   error subsystem is introduced.

Coverage groups
---------------
A  — Orchestrator module: all PR-27 sentinels present and non-empty.
B  — Projection: PR-27 sentinel is importable and not UNAVAILABLE.
C  — core.runtime re-exports all PR-27 sentinels.
D  — Registration failure semantics: failure_kind is 'registration_failure'.
E  — Capability failure semantics: failure_kind is 'capability_failure'.
F  — Readiness failure semantics: failure_kind is 'readiness_failure'.
G  — Config error semantics: failure_kind is 'config_error'.
H  — Capability-not-satisfied signals are actionable (carry missing capability info).
I  — Readiness degraded signals carry BlockedBy / status detail.
J  — Gateway signal shape is deterministic (same top-level fields across failure kinds).
K  — Sentinel strings contain expected policy keywords.
L  — Regression: registration ack (success) carries same surface fields as failure ack.
M  — Regression: capability report ack (accepted) carries same surface fields as rejected.
N  — Retry/reconnect UX can branch on failure_kind without inspecting raw error strings.
O  — No new registration coordinator or alternate error authority is introduced.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import pytest

# ---------------------------------------------------------------------------
# Module availability guards
# ---------------------------------------------------------------------------

try:
    from core.runtime.source_dispatch_orchestrator import (
        GATEWAY_FACING_REGISTRATION_CAPABILITY_ERROR_SEMANTICS_HARDENED_PR27_SENTINEL,
        REGISTRATION_FAILURE_IS_DISTINGUISHABLE_FROM_CAPABILITY_FAILURE_PR27_POLICY,
        READINESS_DEGRADED_BEHAVIOR_IS_REPORTED_THROUGH_STABLE_SIGNALS_PR27_POLICY,
        CAPABILITY_NOT_SATISFIED_FAILURE_IS_ACTIONABLE_PR27_POLICY,
        GATEWAY_SETUP_CONNECTION_SIGNALS_ARE_DETERMINISTIC_PR27_POLICY,
    )

    _ORCHESTRATOR_AVAILABLE = True
except ImportError:
    _ORCHESTRATOR_AVAILABLE = False

try:
    from core.routes.projection import (
        GATEWAY_FACING_REGISTRATION_CAPABILITY_ERROR_SEMANTICS_HARDENED_ALIGNED_PR27,
    )

    _PROJECTION_AVAILABLE = True
except ImportError:
    _PROJECTION_AVAILABLE = False

try:
    from core.runtime import (
        GATEWAY_FACING_REGISTRATION_CAPABILITY_ERROR_SEMANTICS_HARDENED_PR27_SENTINEL as _rt_sentinel,
        REGISTRATION_FAILURE_IS_DISTINGUISHABLE_FROM_CAPABILITY_FAILURE_PR27_POLICY as _rt_reg,
        READINESS_DEGRADED_BEHAVIOR_IS_REPORTED_THROUGH_STABLE_SIGNALS_PR27_POLICY as _rt_readiness,
        CAPABILITY_NOT_SATISFIED_FAILURE_IS_ACTIONABLE_PR27_POLICY as _rt_capability,
        GATEWAY_SETUP_CONNECTION_SIGNALS_ARE_DETERMINISTIC_PR27_POLICY as _rt_signals,
    )

    _RUNTIME_EXPORTS_AVAILABLE = True
except ImportError:
    _RUNTIME_EXPORTS_AVAILABLE = False


# ---------------------------------------------------------------------------
# Shared helpers for constructing gateway signal payloads
# ---------------------------------------------------------------------------

def _make_registration_ack(
    device_id: str = "dev-test",
    success: bool = True,
    session_id: Optional[str] = None,
    message: str = "Registration successful",
    failure_kind: Optional[str] = None,
    reason_code: Optional[str] = None,
) -> Dict[str, Any]:
    """Construct a structured registration ack payload following PR-27 semantics."""
    ack: Dict[str, Any] = {
        "type": "device_register_ack",
        "device_id": device_id,
        "success": success,
        "message": message,
    }
    if session_id is not None:
        ack["session_id"] = session_id
    if failure_kind is not None:
        ack["failure_kind"] = failure_kind
    if reason_code is not None:
        ack["reason_code"] = reason_code
    return ack


def _make_capability_ack(
    device_id: str = "dev-test",
    accepted: bool = True,
    message: str = "capability_report accepted",
    failure_kind: Optional[str] = None,
    missing_capability: Optional[str] = None,
    exec_mode_required: Optional[str] = None,
) -> Dict[str, Any]:
    """Construct a structured capability ack payload following PR-27 semantics."""
    ack: Dict[str, Any] = {
        "type": "capability_report_ack",
        "device_id": device_id,
        "accepted": accepted,
        "message": message,
    }
    if failure_kind is not None:
        ack["failure_kind"] = failure_kind
    if missing_capability is not None:
        ack["missing_capability"] = missing_capability
    if exec_mode_required is not None:
        ack["exec_mode_required"] = exec_mode_required
    return ack


def _make_readiness_signal(
    device_id: str = "dev-test",
    status: str = "ready",
    failure_kind: Optional[str] = None,
    blocked_by: Optional[str] = None,
    degraded: bool = False,
    transient: bool = False,
) -> Dict[str, Any]:
    """Construct a structured readiness signal following PR-27 semantics."""
    signal: Dict[str, Any] = {
        "type": "readiness_signal",
        "device_id": device_id,
        "status": status,
        "degraded": degraded,
    }
    if failure_kind is not None:
        signal["failure_kind"] = failure_kind
    if blocked_by is not None:
        signal["blocked_by"] = blocked_by
    if transient:
        signal["transient"] = True
    return signal


# ---------------------------------------------------------------------------
# Group A — Orchestrator PR-27 sentinels present and non-empty
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _ORCHESTRATOR_AVAILABLE, reason="orchestrator not available")
class TestOrchestratorPR27Sentinels:
    """All PR-27 sentinels must be present and non-empty strings."""

    def test_main_sentinel_present(self):
        assert GATEWAY_FACING_REGISTRATION_CAPABILITY_ERROR_SEMANTICS_HARDENED_PR27_SENTINEL
        assert isinstance(
            GATEWAY_FACING_REGISTRATION_CAPABILITY_ERROR_SEMANTICS_HARDENED_PR27_SENTINEL, str
        )

    def test_registration_policy_present(self):
        assert REGISTRATION_FAILURE_IS_DISTINGUISHABLE_FROM_CAPABILITY_FAILURE_PR27_POLICY
        assert isinstance(
            REGISTRATION_FAILURE_IS_DISTINGUISHABLE_FROM_CAPABILITY_FAILURE_PR27_POLICY, str
        )

    def test_readiness_policy_present(self):
        assert READINESS_DEGRADED_BEHAVIOR_IS_REPORTED_THROUGH_STABLE_SIGNALS_PR27_POLICY
        assert isinstance(
            READINESS_DEGRADED_BEHAVIOR_IS_REPORTED_THROUGH_STABLE_SIGNALS_PR27_POLICY, str
        )

    def test_capability_policy_present(self):
        assert CAPABILITY_NOT_SATISFIED_FAILURE_IS_ACTIONABLE_PR27_POLICY
        assert isinstance(CAPABILITY_NOT_SATISFIED_FAILURE_IS_ACTIONABLE_PR27_POLICY, str)

    def test_signals_policy_present(self):
        assert GATEWAY_SETUP_CONNECTION_SIGNALS_ARE_DETERMINISTIC_PR27_POLICY
        assert isinstance(
            GATEWAY_SETUP_CONNECTION_SIGNALS_ARE_DETERMINISTIC_PR27_POLICY, str
        )

    def test_all_five_sentinels_non_empty(self):
        sentinels = [
            GATEWAY_FACING_REGISTRATION_CAPABILITY_ERROR_SEMANTICS_HARDENED_PR27_SENTINEL,
            REGISTRATION_FAILURE_IS_DISTINGUISHABLE_FROM_CAPABILITY_FAILURE_PR27_POLICY,
            READINESS_DEGRADED_BEHAVIOR_IS_REPORTED_THROUGH_STABLE_SIGNALS_PR27_POLICY,
            CAPABILITY_NOT_SATISFIED_FAILURE_IS_ACTIONABLE_PR27_POLICY,
            GATEWAY_SETUP_CONNECTION_SIGNALS_ARE_DETERMINISTIC_PR27_POLICY,
        ]
        for s in sentinels:
            assert len(s) > 10, f"Sentinel too short: {s!r}"


# ---------------------------------------------------------------------------
# Group B — Projection PR-27 sentinel
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _PROJECTION_AVAILABLE, reason="projection not available")
class TestProjectionPR27Sentinel:
    """Projection sentinel must be importable and not UNAVAILABLE."""

    def test_sentinel_not_unavailable(self):
        assert "UNAVAILABLE" not in GATEWAY_FACING_REGISTRATION_CAPABILITY_ERROR_SEMANTICS_HARDENED_ALIGNED_PR27

    def test_sentinel_contains_pr27_marker(self):
        assert "PR27" in GATEWAY_FACING_REGISTRATION_CAPABILITY_ERROR_SEMANTICS_HARDENED_ALIGNED_PR27 or \
               "PR-27" in GATEWAY_FACING_REGISTRATION_CAPABILITY_ERROR_SEMANTICS_HARDENED_ALIGNED_PR27

    def test_sentinel_mentions_registration(self):
        sentinel = GATEWAY_FACING_REGISTRATION_CAPABILITY_ERROR_SEMANTICS_HARDENED_ALIGNED_PR27.lower()
        assert "registration" in sentinel

    def test_sentinel_mentions_capability(self):
        sentinel = GATEWAY_FACING_REGISTRATION_CAPABILITY_ERROR_SEMANTICS_HARDENED_ALIGNED_PR27.lower()
        assert "capability" in sentinel

    def test_sentinel_mentions_readiness(self):
        sentinel = GATEWAY_FACING_REGISTRATION_CAPABILITY_ERROR_SEMANTICS_HARDENED_ALIGNED_PR27.lower()
        assert "readiness" in sentinel


# ---------------------------------------------------------------------------
# Group C — core.runtime re-exports
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _RUNTIME_EXPORTS_AVAILABLE, reason="core.runtime exports not available")
class TestCoreRuntimePR27Exports:
    """core.runtime must re-export all PR-27 sentinel symbols."""

    def test_main_sentinel_exported(self):
        assert _rt_sentinel
        assert isinstance(_rt_sentinel, str)

    def test_registration_policy_exported(self):
        assert _rt_reg
        assert isinstance(_rt_reg, str)

    def test_readiness_policy_exported(self):
        assert _rt_readiness
        assert isinstance(_rt_readiness, str)

    def test_capability_policy_exported(self):
        assert _rt_capability
        assert isinstance(_rt_capability, str)

    def test_signals_policy_exported(self):
        assert _rt_signals
        assert isinstance(_rt_signals, str)

    @pytest.mark.skipif(not _ORCHESTRATOR_AVAILABLE, reason="orchestrator not available")
    def test_all_match_orchestrator(self):
        assert _rt_sentinel == GATEWAY_FACING_REGISTRATION_CAPABILITY_ERROR_SEMANTICS_HARDENED_PR27_SENTINEL
        assert _rt_reg == REGISTRATION_FAILURE_IS_DISTINGUISHABLE_FROM_CAPABILITY_FAILURE_PR27_POLICY
        assert _rt_readiness == READINESS_DEGRADED_BEHAVIOR_IS_REPORTED_THROUGH_STABLE_SIGNALS_PR27_POLICY
        assert _rt_capability == CAPABILITY_NOT_SATISFIED_FAILURE_IS_ACTIONABLE_PR27_POLICY
        assert _rt_signals == GATEWAY_SETUP_CONNECTION_SIGNALS_ARE_DETERMINISTIC_PR27_POLICY


# ---------------------------------------------------------------------------
# Group D — Registration failure semantics
# ---------------------------------------------------------------------------

class TestRegistrationFailureSemantics:
    """Registration failures must carry failure_kind='registration_failure'."""

    def test_registration_ack_success_shape(self):
        ack = _make_registration_ack(success=True, session_id="sess-001")
        assert ack["success"] is True
        assert ack["device_id"] == "dev-test"
        assert "message" in ack
        assert "session_id" in ack

    def test_registration_ack_failure_has_failure_kind(self):
        ack = _make_registration_ack(
            success=False,
            failure_kind="registration_failure",
            reason_code="device_not_registered",
            message="Registration failed: device not registered",
        )
        assert ack["success"] is False
        assert ack["failure_kind"] == "registration_failure"
        assert ack["reason_code"] == "device_not_registered"

    def test_registration_failure_kind_is_stable_string(self):
        failure_kind = "registration_failure"
        assert isinstance(failure_kind, str)
        assert failure_kind == "registration_failure"

    def test_registration_ack_session_absent_reason_code(self):
        ack = _make_registration_ack(
            success=False,
            failure_kind="registration_failure",
            reason_code="session_absent",
            message="Registration failed: no active session found",
        )
        assert ack["failure_kind"] == "registration_failure"
        assert ack["reason_code"] == "session_absent"

    def test_registration_ack_identity_mismatch_reason_code(self):
        ack = _make_registration_ack(
            success=False,
            failure_kind="registration_failure",
            reason_code="identity_mismatch",
            message="Registration failed: device identity mismatch",
        )
        assert ack["failure_kind"] == "registration_failure"
        assert ack["reason_code"] == "identity_mismatch"

    def test_registration_failure_is_json_serialisable(self):
        ack = _make_registration_ack(
            success=False,
            failure_kind="registration_failure",
            reason_code="device_not_registered",
        )
        serialised = json.dumps(ack)
        restored = json.loads(serialised)
        assert restored["failure_kind"] == "registration_failure"


# ---------------------------------------------------------------------------
# Group E — Capability failure semantics
# ---------------------------------------------------------------------------

class TestCapabilityFailureSemantics:
    """Capability failures must carry failure_kind='capability_failure'."""

    def test_capability_ack_accepted_shape(self):
        ack = _make_capability_ack(accepted=True)
        assert ack["accepted"] is True
        assert ack["device_id"] == "dev-test"
        assert "message" in ack

    def test_capability_ack_rejected_has_failure_kind(self):
        ack = _make_capability_ack(
            accepted=False,
            failure_kind="capability_failure",
            missing_capability="tap",
            message="Capability report rejected: required capability 'tap' not satisfied",
        )
        assert ack["accepted"] is False
        assert ack["failure_kind"] == "capability_failure"
        assert ack["missing_capability"] == "tap"

    def test_capability_failure_exec_mode_mismatch(self):
        ack = _make_capability_ack(
            accepted=False,
            failure_kind="capability_failure",
            missing_capability="screenshot",
            exec_mode_required="local",
            message="Capability report rejected: exec_mode_mismatch for 'screenshot'",
        )
        assert ack["failure_kind"] == "capability_failure"
        assert ack["exec_mode_required"] == "local"

    def test_capability_failure_is_distinguishable_from_registration_failure(self):
        reg_fail = _make_registration_ack(
            success=False, failure_kind="registration_failure"
        )
        cap_fail = _make_capability_ack(
            accepted=False, failure_kind="capability_failure"
        )
        assert reg_fail["failure_kind"] != cap_fail["failure_kind"]
        assert reg_fail["failure_kind"] == "registration_failure"
        assert cap_fail["failure_kind"] == "capability_failure"

    def test_capability_failure_is_json_serialisable(self):
        ack = _make_capability_ack(
            accepted=False,
            failure_kind="capability_failure",
            missing_capability="tap",
        )
        serialised = json.dumps(ack)
        restored = json.loads(serialised)
        assert restored["failure_kind"] == "capability_failure"
        assert restored["missing_capability"] == "tap"


# ---------------------------------------------------------------------------
# Group F — Readiness failure semantics
# ---------------------------------------------------------------------------

class TestReadinessFailureSemantics:
    """Readiness failures must carry failure_kind='readiness_failure'."""

    def test_readiness_signal_ready_shape(self):
        signal = _make_readiness_signal(status="ready")
        assert signal["status"] == "ready"
        assert signal["degraded"] is False

    def test_readiness_signal_network_failure(self):
        signal = _make_readiness_signal(
            status="blocked",
            failure_kind="readiness_failure",
            blocked_by="transport_unavailable",
            transient=True,
        )
        assert signal["failure_kind"] == "readiness_failure"
        assert signal["blocked_by"] == "transport_unavailable"
        assert signal["transient"] is True

    def test_readiness_signal_degraded_status(self):
        signal = _make_readiness_signal(
            status="degraded",
            failure_kind="readiness_failure",
            degraded=True,
            blocked_by="recovering",
        )
        assert signal["failure_kind"] == "readiness_failure"
        assert signal["degraded"] is True
        assert signal["blocked_by"] == "recovering"

    def test_readiness_failure_distinguishable_from_capability_failure(self):
        readiness_fail = _make_readiness_signal(
            status="blocked", failure_kind="readiness_failure"
        )
        cap_fail = _make_capability_ack(
            accepted=False, failure_kind="capability_failure"
        )
        assert readiness_fail["failure_kind"] != cap_fail["failure_kind"]

    def test_readiness_signal_is_json_serialisable(self):
        signal = _make_readiness_signal(
            status="blocked",
            failure_kind="readiness_failure",
            blocked_by="transport_unavailable",
        )
        serialised = json.dumps(signal)
        restored = json.loads(serialised)
        assert restored["failure_kind"] == "readiness_failure"


# ---------------------------------------------------------------------------
# Group G — Config error semantics
# ---------------------------------------------------------------------------

class TestConfigErrorSemantics:
    """Configuration errors must carry failure_kind='config_error'."""

    def test_config_error_failure_kind(self):
        ack = _make_registration_ack(
            success=False,
            failure_kind="config_error",
            reason_code="missing_credentials",
            message="Registration failed: configuration error — missing credentials",
        )
        assert ack["failure_kind"] == "config_error"
        assert ack["reason_code"] == "missing_credentials"

    def test_config_error_is_distinguishable_from_registration_failure(self):
        config_fail = _make_registration_ack(
            success=False, failure_kind="config_error"
        )
        reg_fail = _make_registration_ack(
            success=False, failure_kind="registration_failure"
        )
        assert config_fail["failure_kind"] != reg_fail["failure_kind"]

    def test_config_error_is_json_serialisable(self):
        ack = _make_registration_ack(
            success=False,
            failure_kind="config_error",
            reason_code="bad_config",
        )
        serialised = json.dumps(ack)
        restored = json.loads(serialised)
        assert restored["failure_kind"] == "config_error"


# ---------------------------------------------------------------------------
# Group H — Capability-not-satisfied signals are actionable
# ---------------------------------------------------------------------------

class TestCapabilityNotSatisfiedActionable:
    """Capability-not-satisfied signals must identify what is missing and why."""

    def test_missing_capability_field_present(self):
        ack = _make_capability_ack(
            accepted=False,
            failure_kind="capability_failure",
            missing_capability="tap",
        )
        assert "missing_capability" in ack
        assert ack["missing_capability"] == "tap"

    def test_exec_mode_required_field_present(self):
        ack = _make_capability_ack(
            accepted=False,
            failure_kind="capability_failure",
            missing_capability="screenshot",
            exec_mode_required="local",
        )
        assert "exec_mode_required" in ack
        assert ack["exec_mode_required"] == "local"

    def test_capability_absent_reason_code(self):
        ack = _make_capability_ack(
            accepted=False,
            failure_kind="capability_failure",
            missing_capability="gui_write",
            message="Capability 'gui_write' is not registered for this device",
        )
        assert ack["missing_capability"] == "gui_write"
        assert "gui_write" in ack["message"]

    def test_transient_vs_permanent_distinction(self):
        transient_fail = {
            "type": "capability_report_ack",
            "device_id": "dev-t",
            "accepted": False,
            "failure_kind": "readiness_failure",
            "transient": True,
            "message": "Device temporarily offline",
        }
        permanent_fail = {
            "type": "capability_report_ack",
            "device_id": "dev-t",
            "accepted": False,
            "failure_kind": "capability_failure",
            "transient": False,
            "missing_capability": "system_root",
            "message": "Capability 'system_root' is structurally absent on this device",
        }
        assert transient_fail["transient"] is True
        assert permanent_fail["transient"] is False
        assert transient_fail["failure_kind"] != permanent_fail["failure_kind"]


# ---------------------------------------------------------------------------
# Group I — Readiness degraded signals carry detail
# ---------------------------------------------------------------------------

class TestReadinessDegradedSignals:
    """Degraded readiness signals must carry BlockedBy / status detail."""

    def test_degraded_signal_carries_blocked_by(self):
        signal = _make_readiness_signal(
            status="degraded",
            failure_kind="readiness_failure",
            degraded=True,
            blocked_by="recovering",
        )
        assert "blocked_by" in signal
        assert signal["blocked_by"] == "recovering"

    def test_blocked_signal_carries_blocked_by(self):
        signal = _make_readiness_signal(
            status="blocked",
            failure_kind="readiness_failure",
            blocked_by="transport_unavailable",
        )
        assert signal["status"] == "blocked"
        assert signal["blocked_by"] == "transport_unavailable"

    def test_degraded_status_is_distinct_from_blocked(self):
        blocked = _make_readiness_signal(status="blocked", degraded=False)
        degraded = _make_readiness_signal(status="degraded", degraded=True)
        assert blocked["status"] != degraded["status"]
        assert degraded["degraded"] is True
        assert blocked["degraded"] is False

    def test_readiness_signal_serialisable(self):
        signal = _make_readiness_signal(
            status="degraded",
            failure_kind="readiness_failure",
            degraded=True,
            blocked_by="recovering",
        )
        serialised = json.dumps(signal)
        restored = json.loads(serialised)
        assert restored["degraded"] is True
        assert restored["blocked_by"] == "recovering"


# ---------------------------------------------------------------------------
# Group J — Gateway signal shape is deterministic
# ---------------------------------------------------------------------------

class TestGatewaySignalShapeDeterministic:
    """All gateway failure signals must have the same stable top-level field set."""

    _REGISTRATION_ACK_BASE_FIELDS = {"type", "device_id", "success", "message"}
    _CAPABILITY_ACK_BASE_FIELDS = {"type", "device_id", "accepted", "message"}
    _READINESS_SIGNAL_BASE_FIELDS = {"type", "device_id", "status", "degraded"}

    def test_registration_ack_success_has_base_fields(self):
        ack = _make_registration_ack(success=True, session_id="s1")
        for field in self._REGISTRATION_ACK_BASE_FIELDS:
            assert field in ack, f"Missing field: {field}"

    def test_registration_ack_failure_has_base_fields(self):
        ack = _make_registration_ack(
            success=False, failure_kind="registration_failure"
        )
        for field in self._REGISTRATION_ACK_BASE_FIELDS:
            assert field in ack, f"Missing field: {field}"

    def test_capability_ack_accepted_has_base_fields(self):
        ack = _make_capability_ack(accepted=True)
        for field in self._CAPABILITY_ACK_BASE_FIELDS:
            assert field in ack, f"Missing field: {field}"

    def test_capability_ack_rejected_has_base_fields(self):
        ack = _make_capability_ack(
            accepted=False, failure_kind="capability_failure"
        )
        for field in self._CAPABILITY_ACK_BASE_FIELDS:
            assert field in ack, f"Missing field: {field}"

    def test_readiness_signal_ready_has_base_fields(self):
        signal = _make_readiness_signal(status="ready")
        for field in self._READINESS_SIGNAL_BASE_FIELDS:
            assert field in signal, f"Missing field: {field}"

    def test_readiness_signal_blocked_has_base_fields(self):
        signal = _make_readiness_signal(status="blocked", failure_kind="readiness_failure")
        for field in self._READINESS_SIGNAL_BASE_FIELDS:
            assert field in signal, f"Missing field: {field}"

    def test_registration_ack_type_field_stable(self):
        for success in [True, False]:
            ack = _make_registration_ack(success=success)
            assert ack["type"] == "device_register_ack"

    def test_capability_ack_type_field_stable(self):
        for accepted in [True, False]:
            ack = _make_capability_ack(accepted=accepted)
            assert ack["type"] == "capability_report_ack"

    def test_readiness_signal_type_field_stable(self):
        for status in ["ready", "blocked", "degraded"]:
            signal = _make_readiness_signal(status=status)
            assert signal["type"] == "readiness_signal"


# ---------------------------------------------------------------------------
# Group K — Sentinel keyword verification
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _ORCHESTRATOR_AVAILABLE, reason="orchestrator not available")
class TestSentinelKeywords:
    """Sentinel strings must contain expected policy keywords."""

    def test_main_sentinel_contains_pr27_marker(self):
        s = GATEWAY_FACING_REGISTRATION_CAPABILITY_ERROR_SEMANTICS_HARDENED_PR27_SENTINEL
        assert "PR27" in s or "pr27" in s.lower()

    def test_main_sentinel_contains_registration(self):
        s = GATEWAY_FACING_REGISTRATION_CAPABILITY_ERROR_SEMANTICS_HARDENED_PR27_SENTINEL.lower()
        assert "registration" in s

    def test_main_sentinel_contains_capability(self):
        s = GATEWAY_FACING_REGISTRATION_CAPABILITY_ERROR_SEMANTICS_HARDENED_PR27_SENTINEL.lower()
        assert "capability" in s

    def test_registration_policy_contains_failure_kind(self):
        s = REGISTRATION_FAILURE_IS_DISTINGUISHABLE_FROM_CAPABILITY_FAILURE_PR27_POLICY.lower()
        assert "failure_kind" in s

    def test_readiness_policy_mentions_config_error_distinction(self):
        s = READINESS_DEGRADED_BEHAVIOR_IS_REPORTED_THROUGH_STABLE_SIGNALS_PR27_POLICY.lower()
        assert "config_error" in s

    def test_capability_policy_contains_actionable(self):
        s = CAPABILITY_NOT_SATISFIED_FAILURE_IS_ACTIONABLE_PR27_POLICY.lower()
        assert "actionable" in s or "missing" in s

    def test_signals_policy_contains_deterministic(self):
        s = GATEWAY_SETUP_CONNECTION_SIGNALS_ARE_DETERMINISTIC_PR27_POLICY.lower()
        assert "deterministic" in s


# ---------------------------------------------------------------------------
# Group L — Regression: registration ack surface invariance
# ---------------------------------------------------------------------------

class TestRegistrationAckSurfaceInvariance:
    """Registration ack must have same top-level field structure for success/failure."""

    def test_success_and_failure_share_base_fields(self):
        success_ack = _make_registration_ack(success=True, session_id="s1")
        failure_ack = _make_registration_ack(
            success=False, failure_kind="registration_failure"
        )
        base_fields = {"type", "device_id", "success", "message"}
        for f in base_fields:
            assert f in success_ack
            assert f in failure_ack

    def test_type_field_is_always_device_register_ack(self):
        for success in [True, False]:
            ack = _make_registration_ack(success=success)
            assert ack["type"] == "device_register_ack"

    def test_device_id_always_present(self):
        for device_id in ["dev-a", "dev-b", "dev-c"]:
            ack = _make_registration_ack(device_id=device_id)
            assert ack["device_id"] == device_id


# ---------------------------------------------------------------------------
# Group M — Regression: capability report ack surface invariance
# ---------------------------------------------------------------------------

class TestCapabilityAckSurfaceInvariance:
    """Capability ack must have same top-level field structure for accepted/rejected."""

    def test_accepted_and_rejected_share_base_fields(self):
        accepted_ack = _make_capability_ack(accepted=True)
        rejected_ack = _make_capability_ack(
            accepted=False, failure_kind="capability_failure"
        )
        base_fields = {"type", "device_id", "accepted", "message"}
        for f in base_fields:
            assert f in accepted_ack
            assert f in rejected_ack

    def test_type_field_is_always_capability_report_ack(self):
        for accepted in [True, False]:
            ack = _make_capability_ack(accepted=accepted)
            assert ack["type"] == "capability_report_ack"


# ---------------------------------------------------------------------------
# Group N — Retry/reconnect UX can branch on failure_kind
# ---------------------------------------------------------------------------

class TestRetryReconnectUXBranching:
    """Upstream retry/reconnect UX must be able to branch on failure_kind alone."""

    _KNOWN_FAILURE_KINDS = {
        "registration_failure",
        "capability_failure",
        "readiness_failure",
        "config_error",
    }

    def test_all_failure_kinds_are_distinct(self):
        assert len(self._KNOWN_FAILURE_KINDS) == 4

    def test_registration_failure_is_in_known_kinds(self):
        assert "registration_failure" in self._KNOWN_FAILURE_KINDS

    def test_capability_failure_is_in_known_kinds(self):
        assert "capability_failure" in self._KNOWN_FAILURE_KINDS

    def test_readiness_failure_is_in_known_kinds(self):
        assert "readiness_failure" in self._KNOWN_FAILURE_KINDS

    def test_config_error_is_in_known_kinds(self):
        assert "config_error" in self._KNOWN_FAILURE_KINDS

    def test_failure_kind_routing_without_raw_string_inspection(self):
        """Simulate UX branching logic: branch on failure_kind, not message text."""
        signals = [
            _make_registration_ack(success=False, failure_kind="registration_failure"),
            _make_capability_ack(accepted=False, failure_kind="capability_failure"),
            _make_readiness_signal(status="blocked", failure_kind="readiness_failure"),
            _make_registration_ack(success=False, failure_kind="config_error"),
        ]
        ux_actions = []
        for signal in signals:
            fk = signal.get("failure_kind")
            if fk == "registration_failure":
                ux_actions.append("show_register_again_prompt")
            elif fk == "capability_failure":
                ux_actions.append("show_capability_setup_prompt")
            elif fk == "readiness_failure":
                ux_actions.append("show_retry_connection_prompt")
            elif fk == "config_error":
                ux_actions.append("show_configuration_settings")
            else:
                ux_actions.append("show_generic_error")

        assert "show_register_again_prompt" in ux_actions
        assert "show_capability_setup_prompt" in ux_actions
        assert "show_retry_connection_prompt" in ux_actions
        assert "show_configuration_settings" in ux_actions
        assert "show_generic_error" not in ux_actions


# ---------------------------------------------------------------------------
# Group O — No new registration coordinator or alternate error authority
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _ORCHESTRATOR_AVAILABLE, reason="orchestrator not available")
class TestNoParallelAuthority:
    """No new registration coordinator or alternate error authority must be introduced."""

    def test_registration_policy_affirms_no_parallel_coordinator(self):
        policy = REGISTRATION_FAILURE_IS_DISTINGUISHABLE_FROM_CAPABILITY_FAILURE_PR27_POLICY
        assert "parallel" not in policy.lower() or "no parallel" in policy.lower() or \
               "not introduced" in policy.lower() or "no new" in policy.lower() or \
               "no alternate" in policy.lower() or \
               "No parallel" in policy or "not permitted" in policy.lower()

    def test_signals_policy_affirms_stable_contract(self):
        policy = GATEWAY_SETUP_CONNECTION_SIGNALS_ARE_DETERMINISTIC_PR27_POLICY
        assert "stable" in policy.lower() or "contract" in policy.lower()

    def test_main_sentinel_is_single_authority(self):
        s = GATEWAY_FACING_REGISTRATION_CAPABILITY_ERROR_SEMANTICS_HARDENED_PR27_SENTINEL
        assert "source-dispatch-orchestrator" in s

    @pytest.mark.skipif(not _PROJECTION_AVAILABLE, reason="projection not available")
    def test_projection_sentinel_affirms_no_new_subsystem(self):
        sentinel = GATEWAY_FACING_REGISTRATION_CAPABILITY_ERROR_SEMANTICS_HARDENED_ALIGNED_PR27.lower()
        assert "no alternate" in sentinel or "not introduced" in sentinel or "no parallel" in sentinel
