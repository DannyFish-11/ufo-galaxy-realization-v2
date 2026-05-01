"""
tests/test_final_integrated_system_audit.py
============================================
Final code-grounded completion verdict tests for the integrated
ufo-galaxy-realization-v2 × ufo-galaxy-android center-distributed system.

PURPOSE
-------
These tests enforce the final audit verdict surface defined in
``core/final_integrated_system_audit.py`` against the live code.

Each test class corresponds to one of the five audit areas:
  1. Transport / Protocol
  2. Device Lifecycle / Liveness
  3. Dispatch / Execution / Result Continuity
  4. Multi-Device / Cross-Location Usability
  5. Final Integrated System Verdict

SCOPE
-----
Pure unit tests — no live WebSocket, no FastAPI TestClient, no APK.
All assertions are against importable code artifacts.

When a test fails it means either:
  (a) The production code has been changed and the audit surface is stale —
      update the sentinels in core/final_integrated_system_audit.py to reflect
      the new reality; or
  (b) A gap has been resolved and a RUNNABLE_BUT_CONDITIONAL / PARTIAL sentinel
      should be promoted — update the sentinel, the rationale, and this test.
"""

from __future__ import annotations

import pytest


# ===========================================================================
# Import the audit surface
# ===========================================================================


@pytest.fixture(scope="module")
def audit():
    """Return the FINAL_INTEGRATED_SYSTEM_AUDIT dict."""
    from core.final_integrated_system_audit import FINAL_INTEGRATED_SYSTEM_AUDIT
    return FINAL_INTEGRATED_SYSTEM_AUDIT


@pytest.fixture(scope="module")
def verdict_enum():
    """Return the IntegratedSystemVerdict enum."""
    from core.final_integrated_system_audit import IntegratedSystemVerdict
    return IntegratedSystemVerdict


# ===========================================================================
# 0. Module-level invariant checker
# ===========================================================================


class TestAuditSurfaceSelfConsistency:
    """The audit module's own invariant checker must pass."""

    def test_assert_final_audit_surface_is_consistent(self) -> None:
        """assert_final_audit_surface_is_consistent() must not raise."""
        from core.final_integrated_system_audit import (
            assert_final_audit_surface_is_consistent,
        )
        assert_final_audit_surface_is_consistent()

    def test_all_area_verdicts_are_in_dict(self, audit) -> None:
        """FINAL_INTEGRATED_SYSTEM_AUDIT must contain all five area keys."""
        expected_keys = [
            "transport_verdict",
            "device_lifecycle_verdict",
            "dispatch_execution_result_verdict",
            "multi_device_cross_location_verdict",
            "integrated_system_verdict",
        ]
        for key in expected_keys:
            assert key in audit, (
                f"FINAL_AUDIT: '{key}' must be present in FINAL_INTEGRATED_SYSTEM_AUDIT."
            )

    def test_area_verdicts_dict_has_five_entries(self, audit) -> None:
        """AREA_VERDICTS must cover all five dimensions."""
        from core.final_integrated_system_audit import AREA_VERDICTS
        assert len(AREA_VERDICTS) == 5, (
            "FINAL_AUDIT: AREA_VERDICTS must have exactly 5 entries "
            "(transport, device_lifecycle, dispatch_execution_result, "
            "multi_device_cross_location, integrated_system)."
        )

    def test_known_remaining_gaps_non_empty(self) -> None:
        """KNOWN_REMAINING_GAPS must be non-empty."""
        from core.final_integrated_system_audit import (
            KNOWN_REMAINING_GAPS,
            MINIMUM_KNOWN_GAPS,
        )
        assert len(KNOWN_REMAINING_GAPS) >= MINIMUM_KNOWN_GAPS, (
            "FINAL_AUDIT: KNOWN_REMAINING_GAPS must document at least "
            f"{MINIMUM_KNOWN_GAPS} known gaps. "
            "Do not remove gap entries without resolving the underlying issue."
        )

    def test_confirmed_complete_capabilities_non_empty(self) -> None:
        """CONFIRMED_COMPLETE_CAPABILITIES must be non-empty."""
        from core.final_integrated_system_audit import (
            CONFIRMED_COMPLETE_CAPABILITIES,
            MINIMUM_CONFIRMED_COMPLETE_CAPABILITIES,
        )
        assert len(CONFIRMED_COMPLETE_CAPABILITIES) >= MINIMUM_CONFIRMED_COMPLETE_CAPABILITIES, (
            "FINAL_AUDIT: CONFIRMED_COMPLETE_CAPABILITIES must document at least "
            f"{MINIMUM_CONFIRMED_COMPLETE_CAPABILITIES} confirmed-complete items."
        )


# ===========================================================================
# 1. Transport / Protocol — must be COMPLETE
# ===========================================================================


class TestTransportProtocolVerdict:
    """Area 1: Transport/Protocol must be classified as COMPLETE."""

    def test_transport_verdict_is_complete(self, audit, verdict_enum) -> None:
        """COMPLETE: transport/protocol area verdict must be COMPLETE."""
        assert audit["transport_verdict"] == verdict_enum.COMPLETE, (
            "FINAL_AUDIT: transport_verdict must be COMPLETE. "
            "WS path aligned, compat layer present, all message types handled."
        )

    def test_ws_path_is_aligned(self, audit) -> None:
        """COMPLETE: V2 /ws/device/{id} and Android URL construction are aligned."""
        assert audit["transport_ws_path_aligned"] is True

    def test_alias_compat_is_present(self, audit) -> None:
        """COMPLETE: AIP compat layer normalises legacy type aliases."""
        assert audit["transport_alias_compat_present"] is True

    def test_android_report_types_are_handled(self, audit) -> None:
        """COMPLETE: Previously-missing Android report types are now handled."""
        assert audit["transport_android_report_types_handled"] is True

    def test_unknown_type_response_present(self, audit) -> None:
        """COMPLETE: Unknown message types return a structured response."""
        assert audit["transport_unknown_type_response_present"] is True


class TestTransportProtocolCodeVerification:
    """Verify transport/protocol code artifacts directly (not just sentinels)."""

    def test_canonical_ws_path_constant(self) -> None:
        """V2 canonical WS device path is /ws/device/{device_id}."""
        from core.final_integrated_system_audit import TRANSPORT_PROTOCOL_WS_PATH_ALIGNED
        from core.cross_device_integration_reality import CANONICAL_WS_DEVICE_PATH
        assert TRANSPORT_PROTOCOL_WS_PATH_ALIGNED is True
        assert "{device_id}" in CANONICAL_WS_DEVICE_PATH

    def test_goal_result_in_compat_map(self) -> None:
        """'goal_result' must be in _LEGACY_TYPE_MAP (compat.py)."""
        from galaxy_gateway.protocol.compat import _LEGACY_TYPE_MAP
        from galaxy_gateway.protocol.aip_v3 import MessageType
        assert "goal_result" in _LEGACY_TYPE_MAP
        assert _LEGACY_TYPE_MAP["goal_result"] == MessageType.GOAL_EXECUTION_RESULT

    def test_android_report_types_in_enum(self) -> None:
        """All previously-missing Android report types must be in MessageType enum."""
        from galaxy_gateway.protocol.aip_v3 import MessageType
        missing = []
        for t in [
            "cancel_result",
            "device_readiness_report",
            "device_governance_report",
            "device_acceptance_report",
            "device_strategy_report",
        ]:
            try:
                MessageType(t)
            except ValueError:
                missing.append(t)
        assert not missing, (
            f"FINAL_AUDIT: these message types are still missing from MessageType enum: {missing}"
        )

    def test_goal_result_enum_entry_exists(self) -> None:
        """MessageType.GOAL_RESULT must exist as a first-class enum entry."""
        from galaxy_gateway.protocol.aip_v3 import MessageType
        assert hasattr(MessageType, "GOAL_RESULT")
        assert MessageType("goal_result") == MessageType.GOAL_RESULT


# ===========================================================================
# 2. Device Lifecycle / Liveness — must be RUNNABLE_BUT_CONDITIONAL
# ===========================================================================


class TestDeviceLifecycleVerdict:
    """Area 2: Device lifecycle/liveness must be RUNNABLE_BUT_CONDITIONAL."""

    def test_device_lifecycle_verdict(self, audit, verdict_enum) -> None:
        """RUNNABLE_BUT_CONDITIONAL: device lifecycle verdict."""
        assert audit["device_lifecycle_verdict"] == verdict_enum.RUNNABLE_BUT_CONDITIONAL, (
            "FINAL_AUDIT: device_lifecycle_verdict must be RUNNABLE_BUT_CONDITIONAL. "
            "Terminal reconnect limit (MAX_RECONNECT_ATTEMPTS=10) and absence of watchdog "
            "prevent COMPLETE. Update when terminal reconnect is resolved."
        )

    def test_registration_present(self, audit) -> None:
        """Device registration must be present."""
        assert audit["device_registration_present"] is True

    def test_heartbeat_present(self, audit) -> None:
        """Heartbeat protocol must be present."""
        assert audit["device_heartbeat_present"] is True

    def test_stale_cleanup_task_present(self, audit) -> None:
        """Stale cleanup background task must be present."""
        assert audit["device_stale_cleanup_background_task_present"] is True

    def test_reconnect_backoff_present(self, audit) -> None:
        """Reconnect backoff must be present."""
        assert audit["device_reconnect_backoff_present"] is True

    # --- Documented remaining gaps (must NOT be silently removed) ---

    def test_terminal_reconnect_gap_documented(self, audit) -> None:
        """GAP: Android terminal reconnect stop (MAX_RECONNECT_ATTEMPTS=10) must be documented."""
        assert audit["device_reconnect_terminal_stop"] is True, (
            "FINAL_AUDIT: terminal reconnect stop must remain documented until "
            "ufo-galaxy-android removes the attempt limit or adds a watchdog."
        )

    def test_no_watchdog_gap_documented(self, audit) -> None:
        """GAP: No watchdog/supervisory restart must be documented."""
        assert audit["device_reconnect_no_watchdog"] is True, (
            "FINAL_AUDIT: no-watchdog gap must remain documented."
        )

    def test_boot_receiver_does_not_restart_terminal_loop(self, audit) -> None:
        """GAP: BootReceiver does NOT restart a terminal reconnect loop."""
        assert audit["device_boot_receiver_restarts_terminal_loop"] is False, (
            "FINAL_AUDIT: BootReceiver restarts terminal reconnect loop must be False. "
            "BootReceiver covers cold boot only."
        )

    def test_max_reconnect_attempts_value(self, audit) -> None:
        """Android MAX_RECONNECT_ATTEMPTS must be 10."""
        assert audit["device_reconnect_max_attempts"] == 10, (
            "FINAL_AUDIT: device_reconnect_max_attempts must be 10. "
            "Update if ufo-galaxy-android changes MAX_RECONNECT_ATTEMPTS."
        )


class TestDeviceLifecycleCodeVerification:
    """Verify device lifecycle code artifacts directly."""

    def test_cross_device_reality_reconnect_stops(self) -> None:
        """cross_device_integration_reality confirms Android reconnect stops at limit."""
        from core.cross_device_integration_reality import (
            ANDROID_RECONNECT_STOPS_PERMANENTLY_AT_LIMIT,
            ANDROID_MAX_RECONNECT_ATTEMPTS,
        )
        assert ANDROID_RECONNECT_STOPS_PERMANENTLY_AT_LIMIT is True
        assert ANDROID_MAX_RECONNECT_ATTEMPTS == 10

    def test_v2_stale_cleanup_task_in_reality_surface(self) -> None:
        """cross_device_integration_reality confirms V2 stale cleanup task present."""
        from core.cross_device_integration_reality import V2_STALE_CLEANUP_BACKGROUND_TASK_PRESENT
        assert V2_STALE_CLEANUP_BACKGROUND_TASK_PRESENT is True

    def test_task_lifecycle_error_counters_importable(self) -> None:
        """Result ingestion error counters must be importable from task_lifecycle."""
        from galaxy_gateway.android.handlers.task_lifecycle import (
            RESULT_RECONCILE_ERRORS,
            RESULT_TRUTH_INGRESS_ERRORS,
            RESULT_DEVICE_ROUTER_ERRORS,
            RESULT_MEMORY_BACKFLOW_ERRORS,
            get_result_ingestion_error_counts,
        )
        counts = get_result_ingestion_error_counts()
        assert "total_errors" in counts


# ===========================================================================
# 3. Dispatch / Execution / Result Continuity — must be RUNNABLE_BUT_CONDITIONAL
# ===========================================================================


class TestDispatchExecutionResultVerdict:
    """Area 3: Dispatch/execution/result continuity must be RUNNABLE_BUT_CONDITIONAL."""

    def test_dispatch_verdict(self, audit, verdict_enum) -> None:
        """RUNNABLE_BUT_CONDITIONAL: dispatch/execution/result verdict."""
        assert audit["dispatch_execution_result_verdict"] == verdict_enum.RUNNABLE_BUT_CONDITIONAL

    def test_legality_gate_present(self, audit) -> None:
        """Dispatch legality gate must be present."""
        assert audit["dispatch_legality_gate_present"] is True

    def test_device_routing_present(self, audit) -> None:
        """Device routing must be present."""
        assert audit["dispatch_device_routing_present"] is True

    def test_offline_buffering_present(self, audit) -> None:
        """Offline pending-delivery buffer must be present."""
        assert audit["dispatch_offline_buffering_present"] is True

    def test_result_truth_chain_present(self, audit) -> None:
        """Result ingestion truth chain must be present."""
        assert audit["dispatch_result_truth_chain_present"] is True

    def test_result_error_counters_present(self, audit) -> None:
        """Observable result ingestion error counters must be present."""
        assert audit["dispatch_result_error_counters_present"] is True

    def test_completion_ingress_present(self, audit) -> None:
        """Completion settlement ingress must be present."""
        assert audit["dispatch_completion_ingress_present"] is True

    def test_idempotency_guard_durable(self, audit) -> None:
        """Durable result idempotency guard must be present."""
        assert audit["dispatch_idempotency_guard_durable"] is True

    # --- Documented remaining gaps ---

    def test_buffer_not_durable_documented(self, audit) -> None:
        """GAP: pending-delivery buffer is non-durable (in-process only)."""
        assert audit["dispatch_buffer_durable"] is False, (
            "FINAL_AUDIT: dispatch_buffer_durable must be False until a durable "
            "storage backend is added to pending_delivery_buffer.py."
        )

    def test_silent_failure_paths_closed(self, audit) -> None:
        """GAP CLOSED: result ingestion no longer has silent failure paths."""
        assert audit["dispatch_result_silent_failure_paths"] is False

    def test_completion_no_explicit_verdict_gate(self, audit) -> None:
        """GAP: completion gate is optimistic — no explicit accept/reject verdict."""
        assert audit["dispatch_completion_explicit_verdict_gate"] is False, (
            "FINAL_AUDIT: dispatch_completion_explicit_verdict_gate must remain False "
            "until canonical_completion_ingress.py adds an explicit verdict gate."
        )

    def test_residual_terminal_reconnect_risk_documented(self, audit) -> None:
        """GAP: residual risk from Android terminal reconnect must be documented."""
        assert audit["dispatch_residual_risk_terminal_reconnect"] is True

    def test_residual_process_restart_risk_documented(self, audit) -> None:
        """GAP: residual risk from V2 process restart (buffer loss) must be documented."""
        assert audit["dispatch_residual_risk_process_restart"] is True

    def test_buffer_ttl_and_capacity_values(self, audit) -> None:
        """Buffer TTL=60s and capacity=32/device must match implementation."""
        assert audit["dispatch_buffer_ttl_s"] == 60.0
        assert audit["dispatch_buffer_max_queue_per_device"] == 32


class TestDispatchCodeVerification:
    """Verify dispatch/result code artifacts directly."""

    def test_pending_delivery_buffer_importable(self) -> None:
        """PendingDeliveryBuffer must be importable from galaxy_gateway."""
        from galaxy_gateway.pending_delivery_buffer import (
            PendingDeliveryBuffer,
            pending_delivery_buffer,
            PENDING_DELIVERY_TTL_SECONDS,
            PENDING_DELIVERY_MAX_QUEUE_PER_DEVICE,
        )
        assert PENDING_DELIVERY_TTL_SECONDS == 60.0
        assert PENDING_DELIVERY_MAX_QUEUE_PER_DEVICE == 32

    def test_result_ingestion_reality_sentinels(self) -> None:
        """cross_device_integration_reality result ingestion sentinels must be consistent."""
        from core.cross_device_integration_reality import (
            RESULT_INGESTION_HAS_SILENT_FAILURE_PATHS,
            RESULT_INGESTION_ERROR_COUNTERS_PRESENT,
            INFLIGHT_TASK_LOSS_ON_DISCONNECT,
            PENDING_DELIVERY_BUFFER_PRESENT,
        )
        assert RESULT_INGESTION_HAS_SILENT_FAILURE_PATHS is False
        assert RESULT_INGESTION_ERROR_COUNTERS_PRESENT is True
        assert INFLIGHT_TASK_LOSS_ON_DISCONNECT is False
        assert PENDING_DELIVERY_BUFFER_PRESENT is True

    def test_cross_device_reality_assert_passes(self) -> None:
        """cross_device_integration_reality.assert_known_gaps_are_documented() must pass."""
        from core.cross_device_integration_reality import assert_known_gaps_are_documented
        assert_known_gaps_are_documented()


# ===========================================================================
# 4. Multi-Device / Cross-Location — must be PARTIAL
# ===========================================================================


class TestMultiDeviceCrossLocationVerdict:
    """Area 4: Multi-device/cross-location usability must be PARTIAL."""

    def test_multi_device_verdict_is_partial(self, audit, verdict_enum) -> None:
        """PARTIAL: multi-device/cross-location verdict."""
        assert audit["multi_device_cross_location_verdict"] == verdict_enum.PARTIAL, (
            "FINAL_AUDIT: multi_device_cross_location_verdict must be PARTIAL. "
            "Android defaults and remote access requirements prevent COMPLETE. "
            "Update when defaults ship correctly and built-in relay is added."
        )

    def test_fan_out_present(self, audit) -> None:
        """Multi-device task fan-out must be code-present."""
        assert audit["multi_device_fan_out_present"] is True

    def test_registry_supports_multiple_devices(self, audit) -> None:
        """Device registry must support multiple devices."""
        assert audit["multi_device_registry_supports_multiple"] is True

    # --- Documented activation barriers (must NOT be silently removed) ---

    def test_android_cross_device_disabled_by_default_documented(self, audit) -> None:
        """GAP: cross_device_enabled=false by default in Android config.properties."""
        assert audit["multi_device_android_disabled_by_default"] is True, (
            "FINAL_AUDIT: android_disabled_by_default must remain True until "
            "ufo-galaxy-android ships with cross_device_enabled=true as default."
        )

    def test_android_url_is_placeholder_documented(self, audit) -> None:
        """GAP: Android default server URL is a Tailscale placeholder."""
        assert audit["multi_device_android_url_is_placeholder"] is True, (
            "FINAL_AUDIT: android_url_is_placeholder must remain True until "
            "ufo-galaxy-android ships with a non-placeholder default gateway URL."
        )

    def test_remote_access_requires_vpn_documented(self, audit) -> None:
        """GAP: remote access requires Tailscale/VPN overlay."""
        assert audit["multi_device_remote_requires_vpn"] is True, (
            "FINAL_AUDIT: remote_requires_vpn must remain True until V2 implements "
            "STUN/TURN or a built-in relay for general internet access."
        )

    def test_no_builtin_stun_turn_documented(self, audit) -> None:
        """GAP: no built-in STUN/TURN/relay in V2."""
        assert audit["multi_device_no_builtin_stun_turn"] is True

    def test_requires_manual_activation_documented(self, audit) -> None:
        """GAP: fresh Android deployment requires manual configuration activation."""
        assert audit["multi_device_requires_manual_activation"] is True


class TestMultiDeviceCrossLocationCodeVerification:
    """Verify multi-device/cross-location code artifacts directly."""

    def test_android_reality_activation_barriers(self) -> None:
        """cross_device_integration_reality must confirm Android activation barriers."""
        from core.cross_device_integration_reality import (
            ANDROID_CROSS_DEVICE_DISABLED_BY_DEFAULT,
            ANDROID_DEFAULT_URL_IS_PLACEHOLDER,
            REMOTE_ACCESS_REQUIRES_TAILSCALE_OR_VPNISH,
        )
        assert ANDROID_CROSS_DEVICE_DISABLED_BY_DEFAULT is True
        assert ANDROID_DEFAULT_URL_IS_PLACEHOLDER is True
        assert REMOTE_ACCESS_REQUIRES_TAILSCALE_OR_VPNISH is True


# ===========================================================================
# 5. Final Integrated System Verdict — must be RUNNABLE_BUT_CONDITIONAL
# ===========================================================================


class TestFinalIntegratedSystemVerdict:
    """Area 5: Final integrated system verdict must be RUNNABLE_BUT_CONDITIONAL."""

    def test_integrated_system_verdict(self, audit, verdict_enum) -> None:
        """RUNNABLE_BUT_CONDITIONAL: the integrated V2↔Android system verdict."""
        assert audit["integrated_system_verdict"] == verdict_enum.RUNNABLE_BUT_CONDITIONAL, (
            "FINAL_AUDIT: The integrated V2↔Android system is RUNNABLE_BUT_CONDITIONAL. "
            "It is not COMPLETE (terminal reconnect, non-durable buffer, deployment "
            "barriers, no built-in relay) and not PARTIAL/MISSING (main execution "
            "chain is code-present and runnable). "
            "Update only when ALL items in KNOWN_REMAINING_GAPS are resolved."
        )

    def test_integrated_verdict_not_complete(self, audit, verdict_enum) -> None:
        """The integrated system is NOT COMPLETE — known gaps prevent it."""
        assert audit["integrated_system_verdict"] != verdict_enum.COMPLETE, (
            "FINAL_AUDIT: Integrated verdict must not be COMPLETE while known gaps exist."
        )

    def test_integrated_verdict_not_missing(self, audit, verdict_enum) -> None:
        """The integrated system is NOT MISSING — real executable code exists."""
        assert audit["integrated_system_verdict"] != verdict_enum.MISSING, (
            "FINAL_AUDIT: Integrated verdict must not be MISSING — "
            "the main execution chain is code-present and runnable."
        )

    def test_integrated_verdict_not_partial(self, audit, verdict_enum) -> None:
        """The integrated system is NOT PARTIAL — main chain is runnable end-to-end."""
        assert audit["integrated_system_verdict"] != verdict_enum.PARTIAL, (
            "FINAL_AUDIT: Integrated verdict is RUNNABLE_BUT_CONDITIONAL, not PARTIAL. "
            "PARTIAL would imply the main chain is not runnable; it is."
        )

    def test_known_remaining_gaps_count(self, audit) -> None:
        """Known remaining gaps must be non-empty and count must match."""
        from core.final_integrated_system_audit import (
            KNOWN_REMAINING_GAPS,
            MINIMUM_KNOWN_GAPS,
        )
        assert audit["known_remaining_gaps_count"] == len(KNOWN_REMAINING_GAPS)
        assert audit["known_remaining_gaps_count"] >= MINIMUM_KNOWN_GAPS

    def test_confirmed_complete_capabilities_count(self, audit) -> None:
        """Confirmed complete capabilities must be non-empty and count must match."""
        from core.final_integrated_system_audit import (
            CONFIRMED_COMPLETE_CAPABILITIES,
            MINIMUM_CONFIRMED_COMPLETE_CAPABILITIES,
        )
        assert audit["confirmed_complete_capabilities_count"] == len(CONFIRMED_COMPLETE_CAPABILITIES)
        assert audit["confirmed_complete_capabilities_count"] >= MINIMUM_CONFIRMED_COMPLETE_CAPABILITIES

    def test_verdict_taxonomy_coverage(self, verdict_enum) -> None:
        """IntegratedSystemVerdict enum must cover all four categories."""
        values = {v.value for v in verdict_enum}
        assert "COMPLETE" in values
        assert "RUNNABLE_BUT_CONDITIONAL" in values
        assert "PARTIAL" in values
        assert "MISSING" in values

    def test_area_verdicts_taxonomy(self, verdict_enum) -> None:
        """Area verdicts must collectively cover COMPLETE, RUNNABLE_BUT_CONDITIONAL, PARTIAL."""
        from core.final_integrated_system_audit import AREA_VERDICTS
        verdict_values = {v.value for v in AREA_VERDICTS.values()}
        assert "COMPLETE" in verdict_values, (
            "At least one area (transport/protocol) must be COMPLETE."
        )
        assert "RUNNABLE_BUT_CONDITIONAL" in verdict_values, (
            "At least one area must be RUNNABLE_BUT_CONDITIONAL."
        )
        assert "PARTIAL" in verdict_values, (
            "At least one area (multi-device/cross-location) must be PARTIAL."
        )
        # MISSING is not expected for any current area
        assert "MISSING" not in verdict_values, (
            "No area should be classified as MISSING — all areas have real code."
        )
