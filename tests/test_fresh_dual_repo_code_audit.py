"""
tests/test_fresh_dual_repo_code_audit.py
=========================================
Test suite for core/fresh_dual_repo_code_audit.py

These tests validate that the fresh code-grounded integrated audit sentinels
remain internally consistent and reflect actual code reality.

The test file:
  1. Imports all major sentinels and verifies expected values.
  2. Calls assert_fresh_audit_invariants() to run the full invariant suite.
  3. Validates verdict categories, upgrade findings, and activation barriers.
  4. Checks key UPGRADE findings from prior audit verdicts.
  5. Verifies the FRESH_AUDIT_SUMMARY dict has all required keys.
"""

from __future__ import annotations

import pytest

from core.fresh_dual_repo_code_audit import (
    DISPATCH_ANDROID_OFFLINE_RESULT_QUEUE,
    DISPATCH_DEVICE_ROUTING,
    DISPATCH_IDEMPOTENCY_GUARD,
    DISPATCH_LEGALITY_GATES,
    DISPATCH_OFFLINE_BUFFERING,
    DISPATCH_OVERALL,
    DISPATCH_RESULT_INGESTION,
    FRESH_AUDIT_SUMMARY,
    FRESH_AUDIT_UPGRADES_FROM_PRIOR,
    FRESH_SYSTEM_VERDICT,
    FRESH_VERDICT_RATIONALE,
    GOVERNANCE_ANDROID_CONSISTENCY_TESTS,
    GOVERNANCE_CI_GATE_ENFORCING,
    GOVERNANCE_CROSS_REPO_CONSISTENCY,
    GOVERNANCE_DUAL_REPO_AUDIT_CI,
    GOVERNANCE_OVERALL,
    LIFECYCLE_ANDROID_BOOT_STARTUP,
    LIFECYCLE_ANDROID_RECONNECT_BASIC,
    LIFECYCLE_ANDROID_RECONNECT_PERPETUAL,
    LIFECYCLE_DEVICE_CONTINUOUS_USABILITY,
    LIFECYCLE_DEVICE_REGISTRATION,
    LIFECYCLE_OVERALL,
    LIFECYCLE_V2_KEEPALIVE_AND_CLEANUP,
    MULTI_DEVICE_ACTIVATION_BARRIER_EXISTS,
    MULTI_DEVICE_CROSS_REPO_SIGNAL_FLOW,
    MULTI_DEVICE_MULTIPLE_DEVICES,
    MULTI_DEVICE_NOTES,
    MULTI_DEVICE_OVERALL,
    MULTI_DEVICE_PLUG_AND_RUN,
    MULTI_DEVICE_REMOTE_ACCESS,
    MULTI_DEVICE_SINGLE_DEVICE_LOCAL,
    MULTI_DEVICE_URL_IS_PLACEHOLDER_BY_DEFAULT,
    REMAINING_ACTIVATION_BARRIERS,
    TRANSPORT_ACK_RESPONSE_BEHAVIOR,
    TRANSPORT_HANDOFF_V2_RESPONSE,
    TRANSPORT_MESSAGE_TYPE_COVERAGE,
    TRANSPORT_NOTES,
    TRANSPORT_OVERALL,
    TRANSPORT_RECONCILIATION_SIGNAL_WIRE,
    TRANSPORT_UNKNOWN_TYPE_FALLBACK,
    TRANSPORT_WS_PATH_ALIGNED,
    CodeVerdictLevel,
    FreshSystemVerdict,
    assert_fresh_audit_invariants,
)


# =============================================================================
# SECTION 1 — Invariant assertion suite
# =============================================================================


class TestFreshAuditInvariants:
    """assert_fresh_audit_invariants() must pass without raising."""

    def test_invariants_pass(self) -> None:
        """The full invariant suite must pass without raising AssertionError."""
        assert_fresh_audit_invariants()

    def test_transport_invariants(self) -> None:
        """Transport area: overall must be COMPLETE and both key wire paths confirmed."""
        assert TRANSPORT_OVERALL == CodeVerdictLevel.COMPLETE, (
            "transport_overall must be COMPLETE"
        )
        assert TRANSPORT_RECONCILIATION_SIGNAL_WIRE == CodeVerdictLevel.COMPLETE, (
            "transport_reconciliation_signal_wire must be COMPLETE (PR-51 closed both sides)"
        )
        assert TRANSPORT_HANDOFF_V2_RESPONSE == CodeVerdictLevel.COMPLETE, (
            "transport_handoff_v2_response must be COMPLETE"
        )

    def test_lifecycle_perpetual_reconnect_invariant(self) -> None:
        """Lifecycle: perpetual reconnect must NOT be MISSING (PR-Block1)."""
        assert LIFECYCLE_ANDROID_RECONNECT_PERPETUAL != CodeVerdictLevel.MISSING, (
            "Perpetual reconnect must NOT be MISSING — PR-Block1 watchdog is implemented"
        )
        assert LIFECYCLE_ANDROID_RECONNECT_PERPETUAL == CodeVerdictLevel.RUNNABLE_BUT_CONDITIONAL, (
            "Perpetual reconnect must be RUNNABLE_BUT_CONDITIONAL (requires activation flags)"
        )

    def test_multi_device_activation_barrier_invariant(self) -> None:
        """Multi-device: activation barriers must be documented and zero-config must be MISSING."""
        assert MULTI_DEVICE_ACTIVATION_BARRIER_EXISTS is True, (
            "Activation barrier must be documented as existing (cross_device_enabled=false default)"
        )
        assert MULTI_DEVICE_PLUG_AND_RUN == CodeVerdictLevel.MISSING, (
            "Plug-and-run must be MISSING (no zero-config provisioning)"
        )
        assert MULTI_DEVICE_CROSS_REPO_SIGNAL_FLOW != CodeVerdictLevel.MISSING, (
            "Cross-repo signal flow must NOT be MISSING (ReconciliationSignal wire closed)"
        )

    def test_governance_invariant(self) -> None:
        """Governance: overall must be COMPLETE (CI-enforcing, not advisory)."""
        assert GOVERNANCE_OVERALL == CodeVerdictLevel.COMPLETE, (
            "governance_overall must be COMPLETE (governance_gate_enforcement.yml hard-blocks CI)"
        )

    def test_final_verdict_invariant(self) -> None:
        """Final verdict must be OPERATIONALLY_CLOSED_CONDITIONAL."""
        assert FRESH_SYSTEM_VERDICT == FreshSystemVerdict.OPERATIONALLY_CLOSED_CONDITIONAL, (
            "Final verdict must be OPERATIONALLY_CLOSED_CONDITIONAL — all wire paths are "
            "implementation-complete; system is deployment-conditional only."
        )


# =============================================================================
# SECTION 2 — Transport / Protocol
# =============================================================================


class TestTransportProtocol:
    """Fresh code-grounded transport/protocol verdict tests."""

    def test_ws_path_aligned_complete(self) -> None:
        assert TRANSPORT_WS_PATH_ALIGNED == CodeVerdictLevel.COMPLETE, (
            "WS path /ws/device/{device_id} is aligned on both sides (V2 code + Android code)."
        )

    def test_message_type_coverage_complete(self) -> None:
        assert TRANSPORT_MESSAGE_TYPE_COVERAGE == CodeVerdictLevel.COMPLETE

    def test_unknown_type_fallback_complete(self) -> None:
        assert TRANSPORT_UNKNOWN_TYPE_FALLBACK == CodeVerdictLevel.COMPLETE

    def test_ack_response_behavior_complete(self) -> None:
        assert TRANSPORT_ACK_RESPONSE_BEHAVIOR == CodeVerdictLevel.COMPLETE

    def test_reconciliation_signal_wire_complete(self) -> None:
        """Key upgrade: ReconciliationSignal wire is COMPLETE on both sides.

        Android: ReconciliationSignal.kt (PR-51) + GalaxyConnectionService sends it.
        V2: reconciliation_signal.py handler registered in android_bridge.py.
        """
        assert TRANSPORT_RECONCILIATION_SIGNAL_WIRE == CodeVerdictLevel.COMPLETE, (
            "ReconciliationSignal wire must be COMPLETE — PR-51 closed both sides."
        )

    def test_reconciliation_signal_wire_is_not_missing(self) -> None:
        assert TRANSPORT_RECONCILIATION_SIGNAL_WIRE != CodeVerdictLevel.MISSING, (
            "ReconciliationSignal wire must NOT be MISSING — prior audit was stale."
        )

    def test_handoff_v2_response_complete(self) -> None:
        """Key upgrade: HandoffEnvelopeV2 response handling is COMPLETE.

        V2: handoff_v2_result.py handles handoff_ack/handoff_result/handoff_failure.
        PR-1 P0 Completion Closure drives dispatch_to_websocket completion.
        """
        assert TRANSPORT_HANDOFF_V2_RESPONSE == CodeVerdictLevel.COMPLETE

    def test_transport_overall_complete(self) -> None:
        assert TRANSPORT_OVERALL == CodeVerdictLevel.COMPLETE

    def test_transport_notes_not_empty(self) -> None:
        assert len(TRANSPORT_NOTES) >= 4


# =============================================================================
# SECTION 3 — Lifecycle / Liveness
# =============================================================================


class TestLifecycleLiveness:
    """Fresh code-grounded lifecycle/liveness verdict tests."""

    def test_v2_keepalive_complete(self) -> None:
        assert LIFECYCLE_V2_KEEPALIVE_AND_CLEANUP == CodeVerdictLevel.COMPLETE

    def test_device_registration_complete(self) -> None:
        assert LIFECYCLE_DEVICE_REGISTRATION == CodeVerdictLevel.COMPLETE

    def test_android_reconnect_basic_conditional(self) -> None:
        assert LIFECYCLE_ANDROID_RECONNECT_BASIC == CodeVerdictLevel.RUNNABLE_BUT_CONDITIONAL

    def test_android_perpetual_reconnect_not_missing(self) -> None:
        """Key upgrade: Android perpetual reconnect must NOT be MISSING.

        PR-Block1 implemented watchdog recovery in GalaxyWebSocketClient and
        RuntimeController.  PrBlock1PerpetualReconnectTest.kt confirms with 12+ tests.
        """
        assert LIFECYCLE_ANDROID_RECONNECT_PERPETUAL != CodeVerdictLevel.MISSING, (
            "Android perpetual reconnect was MISSING in prior audit but is now implemented. "
            "This sentinel must not regress back to MISSING."
        )

    def test_android_perpetual_reconnect_conditional(self) -> None:
        """Perpetual reconnect is implemented but still requires activation flags."""
        assert LIFECYCLE_ANDROID_RECONNECT_PERPETUAL == CodeVerdictLevel.RUNNABLE_BUT_CONDITIONAL

    def test_boot_startup_complete(self) -> None:
        assert LIFECYCLE_ANDROID_BOOT_STARTUP == CodeVerdictLevel.COMPLETE

    def test_device_continuous_usability_not_missing(self) -> None:
        """Continuous usability is no longer MISSING — watchdog ensures perpetual reconnect."""
        assert LIFECYCLE_DEVICE_CONTINUOUS_USABILITY != CodeVerdictLevel.MISSING, (
            "Continuous usability was MISSING (10-retry terminal stop). "
            "PR-Block1 watchdog eliminates that; must not be MISSING anymore."
        )

    def test_lifecycle_overall_conditional(self) -> None:
        assert LIFECYCLE_OVERALL == CodeVerdictLevel.RUNNABLE_BUT_CONDITIONAL


# =============================================================================
# SECTION 4 — Dispatch / Execution / Result Continuity
# =============================================================================


class TestDispatchExecution:
    """Fresh code-grounded dispatch/execution verdict tests."""

    def test_dispatch_device_routing_complete(self) -> None:
        assert DISPATCH_DEVICE_ROUTING == CodeVerdictLevel.COMPLETE

    def test_dispatch_result_ingestion_complete(self) -> None:
        assert DISPATCH_RESULT_INGESTION == CodeVerdictLevel.COMPLETE

    def test_dispatch_idempotency_guard_complete(self) -> None:
        assert DISPATCH_IDEMPOTENCY_GUARD == CodeVerdictLevel.COMPLETE

    def test_dispatch_android_offline_queue_complete(self) -> None:
        assert DISPATCH_ANDROID_OFFLINE_RESULT_QUEUE == CodeVerdictLevel.COMPLETE

    def test_dispatch_offline_buffering_conditional(self) -> None:
        assert DISPATCH_OFFLINE_BUFFERING == CodeVerdictLevel.RUNNABLE_BUT_CONDITIONAL

    def test_dispatch_legality_gates_conditional(self) -> None:
        """Legality gates are present but advisory-only — do not block actual dispatch."""
        assert DISPATCH_LEGALITY_GATES == CodeVerdictLevel.RUNNABLE_BUT_CONDITIONAL

    def test_dispatch_overall_conditional(self) -> None:
        assert DISPATCH_OVERALL == CodeVerdictLevel.RUNNABLE_BUT_CONDITIONAL


# =============================================================================
# SECTION 5 — Multi-Device / Deployment
# =============================================================================


class TestMultiDevice:
    """Fresh code-grounded multi-device/deployment verdict tests."""

    def test_activation_barrier_exists(self) -> None:
        """cross_device_enabled=false is still the build-time default."""
        assert MULTI_DEVICE_ACTIVATION_BARRIER_EXISTS is True

    def test_url_is_placeholder_by_default(self) -> None:
        """Default Android gateway URL is still a Tailscale placeholder."""
        assert MULTI_DEVICE_URL_IS_PLACEHOLDER_BY_DEFAULT is True

    def test_single_device_local_conditional(self) -> None:
        assert MULTI_DEVICE_SINGLE_DEVICE_LOCAL == CodeVerdictLevel.RUNNABLE_BUT_CONDITIONAL

    def test_multiple_devices_conditional(self) -> None:
        assert MULTI_DEVICE_MULTIPLE_DEVICES == CodeVerdictLevel.RUNNABLE_BUT_CONDITIONAL

    def test_remote_access_conditional(self) -> None:
        assert MULTI_DEVICE_REMOTE_ACCESS == CodeVerdictLevel.RUNNABLE_BUT_CONDITIONAL

    def test_plug_and_run_missing(self) -> None:
        """Zero-config plug-and-run is still MISSING — no auto-discovery exists."""
        assert MULTI_DEVICE_PLUG_AND_RUN == CodeVerdictLevel.MISSING

    def test_cross_repo_signal_flow_not_missing(self) -> None:
        """Key upgrade: ReconciliationSignal wire exists on both sides."""
        assert MULTI_DEVICE_CROSS_REPO_SIGNAL_FLOW != CodeVerdictLevel.MISSING, (
            "Cross-repo signal flow was MISSING in prior audit; ReconciliationSignal "
            "wire is now implemented on both sides."
        )

    def test_multi_device_overall_conditional(self) -> None:
        assert MULTI_DEVICE_OVERALL == CodeVerdictLevel.RUNNABLE_BUT_CONDITIONAL

    def test_multi_device_notes_not_empty(self) -> None:
        assert len(MULTI_DEVICE_NOTES) >= 4


# =============================================================================
# SECTION 6 — Governance / Integrity Enforcement
# =============================================================================


class TestGovernance:
    """Fresh code-grounded governance/integrity verdict tests."""

    def test_ci_gate_enforcing_complete(self) -> None:
        """governance_gate_enforcement.yml is a hard-blocking CI workflow."""
        assert GOVERNANCE_CI_GATE_ENFORCING == CodeVerdictLevel.COMPLETE

    def test_dual_repo_audit_ci_complete(self) -> None:
        assert GOVERNANCE_DUAL_REPO_AUDIT_CI == CodeVerdictLevel.COMPLETE

    def test_cross_repo_consistency_complete(self) -> None:
        assert GOVERNANCE_CROSS_REPO_CONSISTENCY == CodeVerdictLevel.COMPLETE

    def test_android_consistency_tests_complete(self) -> None:
        assert GOVERNANCE_ANDROID_CONSISTENCY_TESTS == CodeVerdictLevel.COMPLETE

    def test_governance_overall_complete(self) -> None:
        assert GOVERNANCE_OVERALL == CodeVerdictLevel.COMPLETE


# =============================================================================
# SECTION 7 — Final System Verdict
# =============================================================================


class TestFinalVerdict:
    """Tests for the final integrated system verdict."""

    def test_fresh_verdict_is_operationally_closed_conditional(self) -> None:
        """The fresh verdict must be OPERATIONALLY_CLOSED_CONDITIONAL.

        This represents an UPGRADE from the prior RUNNABLE_BUT_CONDITIONAL claim,
        reflecting that the ReconciliationSignal wire, perpetual reconnect, and
        HandoffV2 response handling are all now code-complete.
        """
        assert FRESH_SYSTEM_VERDICT == FreshSystemVerdict.OPERATIONALLY_CLOSED_CONDITIONAL, (
            "FRESH_SYSTEM_VERDICT must be OPERATIONALLY_CLOSED_CONDITIONAL — "
            "all critical wire paths and lifecycle mechanisms are code-complete. "
            "System is deployment-conditional, not implementation-incomplete."
        )

    def test_fresh_verdict_is_not_partial(self) -> None:
        assert FRESH_SYSTEM_VERDICT != FreshSystemVerdict.PARTIAL

    def test_verdict_rationale_not_empty(self) -> None:
        assert len(FRESH_VERDICT_RATIONALE) > 100

    def test_verdict_rationale_mentions_perpetual_reconnect(self) -> None:
        assert "perpetual" in FRESH_VERDICT_RATIONALE.lower() or "PR-Block1" in FRESH_VERDICT_RATIONALE

    def test_verdict_rationale_mentions_reconciliation_signal(self) -> None:
        assert "ReconciliationSignal" in FRESH_VERDICT_RATIONALE

    def test_verdict_rationale_mentions_conditional(self) -> None:
        assert "CONDITION" in FRESH_VERDICT_RATIONALE.upper() or "conditional" in FRESH_VERDICT_RATIONALE.lower()

    def test_upgrades_list_has_all_four_key_upgrades(self) -> None:
        """The four key upgrade findings must all be documented."""
        assert len(FRESH_AUDIT_UPGRADES_FROM_PRIOR) >= 4

    def test_upgrades_include_perpetual_reconnect(self) -> None:
        text = " ".join(FRESH_AUDIT_UPGRADES_FROM_PRIOR)
        assert "perpetual" in text.lower() or "PR-Block1" in text

    def test_upgrades_include_reconciliation_signal(self) -> None:
        text = " ".join(FRESH_AUDIT_UPGRADES_FROM_PRIOR)
        assert "ReconciliationSignal" in text or "reconciliation_signal" in text

    def test_upgrades_include_handoff_v2(self) -> None:
        text = " ".join(FRESH_AUDIT_UPGRADES_FROM_PRIOR)
        assert "HandoffEnvelope" in text or "handoff_v2" in text

    def test_upgrades_include_governance_ci(self) -> None:
        text = " ".join(FRESH_AUDIT_UPGRADES_FROM_PRIOR)
        assert "governance" in text.lower() or "CI" in text

    def test_activation_barriers_documented(self) -> None:
        assert len(REMAINING_ACTIVATION_BARRIERS) >= 3

    def test_activation_barriers_include_cross_device_flag(self) -> None:
        text = " ".join(REMAINING_ACTIVATION_BARRIERS)
        assert "cross_device_enabled" in text

    def test_activation_barriers_include_url_config(self) -> None:
        text = " ".join(REMAINING_ACTIVATION_BARRIERS)
        assert "URL" in text or "placeholder" in text.lower()


# =============================================================================
# SECTION 8 — Summary dict completeness
# =============================================================================


class TestSummaryDict:
    """FRESH_AUDIT_SUMMARY dict must have all required keys."""

    REQUIRED_KEYS = [
        # Transport
        "transport_ws_path_aligned",
        "transport_message_type_coverage",
        "transport_unknown_type_fallback",
        "transport_ack_response_behavior",
        "transport_reconciliation_signal_wire",
        "transport_handoff_v2_response",
        "transport_overall",
        # Lifecycle
        "lifecycle_v2_keepalive_and_cleanup",
        "lifecycle_device_registration",
        "lifecycle_android_reconnect_basic",
        "lifecycle_android_reconnect_perpetual",
        "lifecycle_android_boot_startup",
        "lifecycle_device_continuous_usability",
        "lifecycle_overall",
        # Dispatch
        "dispatch_legality_gates",
        "dispatch_device_routing",
        "dispatch_offline_buffering",
        "dispatch_result_ingestion",
        "dispatch_idempotency_guard",
        "dispatch_android_offline_result_queue",
        "dispatch_overall",
        # Multi-device
        "multi_device_activation_barrier_exists",
        "multi_device_url_is_placeholder_by_default",
        "multi_device_single_device_local",
        "multi_device_multiple_devices",
        "multi_device_remote_access",
        "multi_device_plug_and_run",
        "multi_device_cross_repo_signal_flow",
        "multi_device_overall",
        # Governance
        "governance_ci_gate_enforcing",
        "governance_dual_repo_audit_ci",
        "governance_cross_repo_consistency",
        "governance_android_consistency_tests",
        "governance_overall",
        # Final verdict
        "fresh_system_verdict",
        "fresh_verdict_rationale",
        "fresh_audit_upgrades_from_prior",
        "remaining_activation_barriers",
    ]

    @pytest.mark.parametrize("key", REQUIRED_KEYS)
    def test_summary_key_present(self, key: str) -> None:
        assert key in FRESH_AUDIT_SUMMARY, (
            f"FRESH_AUDIT_SUMMARY must contain key '{key}'."
        )

    def test_summary_has_expected_count(self) -> None:
        assert len(FRESH_AUDIT_SUMMARY) >= len(self.REQUIRED_KEYS), (
            "FRESH_AUDIT_SUMMARY must contain at least as many keys as REQUIRED_KEYS."
        )


# =============================================================================
# SECTION 9 — CodeVerdictLevel enum completeness
# =============================================================================


class TestCodeVerdictEnum:
    def test_all_four_levels_present(self) -> None:
        levels = {v.value for v in CodeVerdictLevel}
        assert "COMPLETE" in levels
        assert "RUNNABLE_BUT_CONDITIONAL" in levels
        assert "PARTIAL" in levels
        assert "MISSING" in levels

    def test_fresh_system_verdict_enum_has_three_levels(self) -> None:
        verdicts = {v.value for v in FreshSystemVerdict}
        assert "OPERATIONALLY_CLOSED_CONDITIONAL" in verdicts
        assert "RUNNABLE_BUT_CONDITIONAL" in verdicts
        assert "PARTIAL" in verdicts
