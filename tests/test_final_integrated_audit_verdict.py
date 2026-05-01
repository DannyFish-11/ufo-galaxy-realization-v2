"""
tests/test_final_integrated_audit_verdict.py
=============================================
FINAL INTEGRATED AUDIT — machine-checkable verdict enforcement.

These tests enforce that core/final_integrated_audit_verdict.py stays
in sync with the real code state of the integrated V2↔Android system.

They answer the five questions from the final audit PR:
  1. Which capabilities are COMPLETE?
  2. Which are RUNNABLE_BUT_CONDITIONAL?
  3. Which are PARTIAL?
  4. Which are MISSING?
  5. Is the system a truly complete continuously-runnable center-distributed
     system, or only a partially-complete one?

Test groups
-----------
Group A — Module importability and enum structure
Group B — Transport / Protocol verdicts
Group C — Device Lifecycle / Liveness verdicts
Group D — Dispatch / Execution / Result Continuity verdicts
Group E — Multi-Device / Cross-Location verdicts
Group F — Final System Verdict
Group G — assert_final_verdict_invariants() enforcement
Group H — FINAL_AUDIT_VERDICT dict completeness
Group I — Completeness-review alignment (dual_repo cross-check)
"""

from __future__ import annotations

import sys
import os

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from core.final_integrated_audit_verdict import (
    CapabilityVerdict,
    SystemVerdict,
    FINAL_AUDIT_VERDICT,
    FINAL_SYSTEM_VERDICT,
    FINAL_VERDICT_RATIONALE,
    GAPS_TO_COMPLETE,
    # Transport
    TRANSPORT_WS_PATH_ALIGNMENT,
    TRANSPORT_LEGACY_ALIAS_COMPAT,
    TRANSPORT_ANDROID_REPORT_TYPE_COVERAGE,
    TRANSPORT_ACK_BEHAVIOR,
    TRANSPORT_UNKNOWN_TYPE_HANDLING,
    TRANSPORT_PROTOCOL_OVERALL,
    TRANSPORT_PROTOCOL_NOTES,
    # Lifecycle
    LIFECYCLE_DEVICE_REGISTRATION,
    LIFECYCLE_HEARTBEAT_V2_SIDE,
    LIFECYCLE_STALE_CLEANUP,
    LIFECYCLE_ANDROID_RECONNECT_BASIC,
    LIFECYCLE_ANDROID_RECONNECT_PERPETUAL,
    LIFECYCLE_ANDROID_BOOT_STARTUP,
    LIFECYCLE_DEVICE_CONTINUOUS_USABILITY,
    LIFECYCLE_OVERALL,
    LIFECYCLE_NOTES,
    # Dispatch
    DISPATCH_LEGALITY_GATES_PRESENT,
    DISPATCH_DEVICE_ROUTING,
    DISPATCH_OFFLINE_BUFFERING,
    DISPATCH_RESULT_INGESTION_OBSERVABLE,
    DISPATCH_COMPLETION_SETTLEMENT,
    DISPATCH_DISCONNECT_RECONNECT_RISK,
    DISPATCH_DURABILITY_ACROSS_RESTART,
    DISPATCH_EXECUTION_OVERALL,
    DISPATCH_EXECUTION_NOTES,
    # Multi-device
    MULTI_DEVICE_SINGLE_DEVICE_LOCAL,
    MULTI_DEVICE_MULTIPLE_DEVICES,
    MULTI_DEVICE_REMOTE_ACCESS,
    MULTI_DEVICE_PLUG_AND_RUN,
    MULTI_DEVICE_COORDINATION_STRUCTURE,
    MULTI_DEVICE_SIMULTANEOUS_RECONNECT_ORDERING,
    MULTI_DEVICE_CROSS_REPO_EVIDENCE_FLOW,
    MULTI_DEVICE_OVERALL,
    MULTI_DEVICE_NOTES,
    # Guard function
    assert_final_verdict_invariants,
)


# ===========================================================================
# Group A — Module importability and enum structure
# ===========================================================================


class TestModuleStructure:
    def test_A01_module_importable(self) -> None:
        """Module imports without error."""
        import core.final_integrated_audit_verdict as m
        assert m is not None

    def test_A02_capability_verdict_has_four_values(self) -> None:
        """CapabilityVerdict has exactly four members."""
        members = list(CapabilityVerdict)
        assert len(members) == 4
        values = {m.value for m in members}
        assert values == {"COMPLETE", "RUNNABLE_BUT_CONDITIONAL", "PARTIAL", "MISSING"}

    def test_A03_system_verdict_has_four_values(self) -> None:
        """SystemVerdict has exactly four members."""
        members = list(SystemVerdict)
        assert len(members) == 4
        values = {m.value for m in members}
        assert values == {"COMPLETE", "RUNNABLE_BUT_CONDITIONAL", "PARTIAL", "MISSING"}

    def test_A04_final_audit_verdict_dict_present(self) -> None:
        """FINAL_AUDIT_VERDICT is a non-empty dict."""
        assert isinstance(FINAL_AUDIT_VERDICT, dict)
        assert len(FINAL_AUDIT_VERDICT) > 0

    def test_A05_notes_lists_are_non_empty(self) -> None:
        """All *_NOTES lists are non-empty."""
        assert isinstance(TRANSPORT_PROTOCOL_NOTES, list) and TRANSPORT_PROTOCOL_NOTES
        assert isinstance(LIFECYCLE_NOTES, list) and LIFECYCLE_NOTES
        assert isinstance(DISPATCH_EXECUTION_NOTES, list) and DISPATCH_EXECUTION_NOTES
        assert isinstance(MULTI_DEVICE_NOTES, list) and MULTI_DEVICE_NOTES


# ===========================================================================
# Group B — Transport / Protocol verdicts
# ===========================================================================


class TestTransportProtocol:
    def test_B01_ws_path_alignment_complete(self) -> None:
        """WS path alignment is COMPLETE: /ws/device/{device_id} aligned in both repos."""
        assert TRANSPORT_WS_PATH_ALIGNMENT == CapabilityVerdict.COMPLETE, (
            "WS path alignment must be COMPLETE.  "
            "V2 registers /ws/device/{device_id} (galaxy_gateway/routes/websocket.py). "
            "Android builds the same URL in GalaxyWebSocketClient.kt."
        )

    def test_B02_legacy_alias_compat_complete(self) -> None:
        """Legacy alias compat is COMPLETE: goal_result mapped in _LEGACY_TYPE_MAP."""
        assert TRANSPORT_LEGACY_ALIAS_COMPAT == CapabilityVerdict.COMPLETE

    def test_B03_android_report_type_coverage_complete(self) -> None:
        """Android report types are COMPLETE: all report types in MessageType enum."""
        assert TRANSPORT_ANDROID_REPORT_TYPE_COVERAGE == CapabilityVerdict.COMPLETE, (
            "Android report types (cancel_result, device_readiness_report, etc.) "
            "must be COMPLETE after PR #928 added them to MessageType enum."
        )

    def test_B04_ack_behavior_complete(self) -> None:
        """ACK behavior is COMPLETE: structured ACK returned for all registered types."""
        assert TRANSPORT_ACK_BEHAVIOR == CapabilityVerdict.COMPLETE

    def test_B05_unknown_type_handling_complete(self) -> None:
        """Unknown type handling is COMPLETE: compat layer normalises before dispatch."""
        assert TRANSPORT_UNKNOWN_TYPE_HANDLING == CapabilityVerdict.COMPLETE

    def test_B06_transport_overall_complete(self) -> None:
        """Transport/protocol overall verdict is COMPLETE."""
        assert TRANSPORT_PROTOCOL_OVERALL == CapabilityVerdict.COMPLETE, (
            "Transport/protocol must be COMPLETE.  All sub-verdicts are COMPLETE. "
            "If this fails, check that no transport regression has been introduced."
        )

    def test_B07_compat_layer_functional(self) -> None:
        """Compat layer actually maps goal_result correctly (live code check)."""
        from galaxy_gateway.protocol.compat import _LEGACY_TYPE_MAP
        from galaxy_gateway.protocol.aip_v3 import MessageType
        assert "goal_result" in _LEGACY_TYPE_MAP
        assert _LEGACY_TYPE_MAP["goal_result"] == MessageType.GOAL_EXECUTION_RESULT

    def test_B08_report_types_in_enum(self) -> None:
        """All Android report types are in MessageType enum (live code check)."""
        from galaxy_gateway.protocol.aip_v3 import MessageType
        for type_str in [
            "cancel_result",
            "device_readiness_report",
            "device_governance_report",
            "device_acceptance_report",
            "device_strategy_report",
        ]:
            try:
                mt = MessageType(type_str)
                assert mt.value == type_str
            except ValueError:
                pytest.fail(
                    f"MessageType('{type_str}') must exist after PR #928 "
                    f"but raises ValueError — check aip_v3.py MessageType enum."
                )


# ===========================================================================
# Group C — Device Lifecycle / Liveness verdicts
# ===========================================================================


class TestDeviceLifecycle:
    def test_C01_device_registration_complete(self) -> None:
        """Device registration is COMPLETE: handler present and callable."""
        assert LIFECYCLE_DEVICE_REGISTRATION == CapabilityVerdict.COMPLETE

    def test_C02_heartbeat_v2_side_complete(self) -> None:
        """V2-side heartbeat is COMPLETE: double-keepalive present."""
        assert LIFECYCLE_HEARTBEAT_V2_SIDE == CapabilityVerdict.COMPLETE

    def test_C03_stale_cleanup_complete(self) -> None:
        """Stale cleanup background task is COMPLETE: added in PR #928."""
        assert LIFECYCLE_STALE_CLEANUP == CapabilityVerdict.COMPLETE

    def test_C04_android_reconnect_basic_conditional(self) -> None:
        """Android basic reconnect is RUNNABLE_BUT_CONDITIONAL: requires activation."""
        assert LIFECYCLE_ANDROID_RECONNECT_BASIC == CapabilityVerdict.RUNNABLE_BUT_CONDITIONAL

    def test_C05_android_reconnect_perpetual_missing(self) -> None:
        """GAP: Android perpetual reconnect is MISSING (stops after 10 failures)."""
        assert LIFECYCLE_ANDROID_RECONNECT_PERPETUAL == CapabilityVerdict.MISSING, (
            "Android MAX_RECONNECT_ATTEMPTS=10 permanently stops reconnection. "
            "There is no watchdog or OS-level recovery beyond BootReceiver. "
            "This MUST remain MISSING until ufo-galaxy-android implements "
            "perpetual/watchdog reconnect."
        )

    def test_C06_android_boot_startup_complete(self) -> None:
        """Android boot startup is COMPLETE: BootReceiver starts service on boot."""
        assert LIFECYCLE_ANDROID_BOOT_STARTUP == CapabilityVerdict.COMPLETE

    def test_C07_device_continuous_usability_missing(self) -> None:
        """GAP: Device continuous usability is MISSING (terminal reconnect stop)."""
        assert LIFECYCLE_DEVICE_CONTINUOUS_USABILITY == CapabilityVerdict.MISSING, (
            "Devices can silently stop reconnecting after ~3 min outage. "
            "This MUST remain MISSING until the terminal reconnect problem is solved."
        )

    def test_C08_lifecycle_overall_not_complete(self) -> None:
        """Lifecycle overall is NOT COMPLETE due to terminal reconnect gap."""
        assert LIFECYCLE_OVERALL != CapabilityVerdict.COMPLETE, (
            "Lifecycle overall must NOT be COMPLETE while Android perpetual "
            "reconnect is MISSING."
        )

    def test_C09_lifecycle_overall_is_partial(self) -> None:
        """Lifecycle overall is PARTIAL."""
        assert LIFECYCLE_OVERALL == CapabilityVerdict.PARTIAL

    def test_C10_stale_cleanup_background_task_in_lifecycle(self) -> None:
        """Stale cleanup background task code exists in bootstrap/lifecycle.py."""
        import os
        path = os.path.join(_PROJECT_ROOT, "galaxy_gateway", "bootstrap", "lifecycle.py")
        assert os.path.isfile(path), "galaxy_gateway/bootstrap/lifecycle.py must exist"
        with open(path) as f:
            content = f.read()
        assert "_periodic_stale_cleanup" in content, (
            "_periodic_stale_cleanup must be present in lifecycle.py "
            "(stale cleanup background task added in PR #928)"
        )


# ===========================================================================
# Group D — Dispatch / Execution / Result Continuity verdicts
# ===========================================================================


class TestDispatchExecution:
    def test_D01_legality_gates_conditional(self) -> None:
        """Legality gates are RUNNABLE_BUT_CONDITIONAL (advisory-only)."""
        assert DISPATCH_LEGALITY_GATES_PRESENT == CapabilityVerdict.RUNNABLE_BUT_CONDITIONAL

    def test_D02_device_routing_complete(self) -> None:
        """Device routing is COMPLETE: DeviceRouter routes to connected devices."""
        assert DISPATCH_DEVICE_ROUTING == CapabilityVerdict.COMPLETE

    def test_D03_offline_buffering_conditional(self) -> None:
        """Offline buffering is RUNNABLE_BUT_CONDITIONAL: in-process, 60s TTL."""
        assert DISPATCH_OFFLINE_BUFFERING == CapabilityVerdict.RUNNABLE_BUT_CONDITIONAL

    def test_D04_result_ingestion_observable_complete(self) -> None:
        """Result ingestion observability is COMPLETE: error counters present."""
        assert DISPATCH_RESULT_INGESTION_OBSERVABLE == CapabilityVerdict.COMPLETE

    def test_D05_completion_settlement_partial(self) -> None:
        """Completion settlement is PARTIAL: idempotency guard present but no atomic rollback."""
        assert DISPATCH_COMPLETION_SETTLEMENT == CapabilityVerdict.PARTIAL

    def test_D06_disconnect_reconnect_risk_partial(self) -> None:
        """Disconnect/reconnect risk is PARTIAL: short-window covered, long-outage not."""
        assert DISPATCH_DISCONNECT_RECONNECT_RISK == CapabilityVerdict.PARTIAL

    def test_D07_durability_across_restart_missing(self) -> None:
        """GAP: Restart durability is MISSING: pending buffer lost on V2 restart."""
        assert DISPATCH_DURABILITY_ACROSS_RESTART == CapabilityVerdict.MISSING, (
            "Pending-delivery buffer is in-process only. "
            "V2 restart loses all buffered dispatch messages. "
            "This MUST remain MISSING until the buffer is backed by durable storage."
        )

    def test_D08_dispatch_overall_conditional(self) -> None:
        """Dispatch overall is RUNNABLE_BUT_CONDITIONAL."""
        assert DISPATCH_EXECUTION_OVERALL == CapabilityVerdict.RUNNABLE_BUT_CONDITIONAL

    def test_D09_pending_delivery_buffer_importable(self) -> None:
        """Pending delivery buffer module is importable (live code check)."""
        from galaxy_gateway.pending_delivery_buffer import (
            PendingDeliveryBuffer,
            pending_delivery_buffer,
            PENDING_DELIVERY_TTL_SECONDS,
            PENDING_DELIVERY_MAX_QUEUE_PER_DEVICE,
        )
        assert PENDING_DELIVERY_TTL_SECONDS == 60.0
        assert PENDING_DELIVERY_MAX_QUEUE_PER_DEVICE == 32

    def test_D10_result_ingestion_error_counters_importable(self) -> None:
        """Result ingestion error counters are importable (live code check)."""
        from galaxy_gateway.android.handlers.task_lifecycle import (
            RESULT_RECONCILE_ERRORS,
            RESULT_TRUTH_INGRESS_ERRORS,
            RESULT_DEVICE_ROUTER_ERRORS,
            RESULT_MEMORY_BACKFLOW_ERRORS,
            get_result_ingestion_error_counts,
        )
        counts = get_result_ingestion_error_counts()
        assert set(counts.keys()) == {
            "reconcile_errors",
            "truth_ingress_errors",
            "device_router_errors",
            "memory_backflow_errors",
            "total_errors",
        }


# ===========================================================================
# Group E — Multi-Device / Cross-Location verdicts
# ===========================================================================


class TestMultiDevice:
    def test_E01_single_device_local_conditional(self) -> None:
        """Single device local is RUNNABLE_BUT_CONDITIONAL: manual config required."""
        assert MULTI_DEVICE_SINGLE_DEVICE_LOCAL == CapabilityVerdict.RUNNABLE_BUT_CONDITIONAL

    def test_E02_multiple_devices_conditional(self) -> None:
        """Multiple devices is RUNNABLE_BUT_CONDITIONAL: per-device config required."""
        assert MULTI_DEVICE_MULTIPLE_DEVICES == CapabilityVerdict.RUNNABLE_BUT_CONDITIONAL

    def test_E03_remote_access_conditional(self) -> None:
        """Remote access is RUNNABLE_BUT_CONDITIONAL: requires Tailscale/VPN."""
        assert MULTI_DEVICE_REMOTE_ACCESS == CapabilityVerdict.RUNNABLE_BUT_CONDITIONAL

    def test_E04_plug_and_run_missing(self) -> None:
        """GAP: Plug-and-run is MISSING: no zero-config provisioning."""
        assert MULTI_DEVICE_PLUG_AND_RUN == CapabilityVerdict.MISSING, (
            "Fresh Android install requires manual configuration. "
            "No auto-discovery or zero-config mechanism exists. "
            "This MUST remain MISSING until provisioning is built."
        )

    def test_E05_coordination_structure_partial(self) -> None:
        """Multi-device coordination structure is PARTIAL: modules present, no real-device CI."""
        assert MULTI_DEVICE_COORDINATION_STRUCTURE == CapabilityVerdict.PARTIAL

    def test_E06_simultaneous_reconnect_ordering_missing(self) -> None:
        """GAP: Simultaneous reconnect ordering is MISSING: explicitly deferred."""
        assert MULTI_DEVICE_SIMULTANEOUS_RECONNECT_ORDERING == CapabilityVerdict.MISSING

    def test_E07_cross_repo_evidence_flow_missing(self) -> None:
        """GAP: Cross-repo evidence flow is MISSING: ReconciliationSignal wire absent."""
        assert MULTI_DEVICE_CROSS_REPO_EVIDENCE_FLOW == CapabilityVerdict.MISSING, (
            "ReconciliationSignal AIP wire layer is absent in ufo-galaxy-android. "
            "Android governance/readiness artifacts cannot reach V2 over the live wire. "
            "HandoffEnvelopeV2 response handler is also absent at V2 gateway. "
            "This MUST remain MISSING until both wire gaps are closed."
        )

    def test_E08_multi_device_overall_partial(self) -> None:
        """Multi-device overall is PARTIAL."""
        assert MULTI_DEVICE_OVERALL == CapabilityVerdict.PARTIAL


# ===========================================================================
# Group F — Final System Verdict
# ===========================================================================


class TestFinalSystemVerdict:
    def test_F01_system_verdict_not_complete(self) -> None:
        """FINAL VERDICT: system is NOT COMPLETE."""
        assert FINAL_SYSTEM_VERDICT != SystemVerdict.COMPLETE, (
            "The integrated V2↔Android system must NOT be COMPLETE. "
            "Multiple documented gaps remain.  Update this assertion ONLY when "
            "all gaps_to_complete are resolved."
        )

    def test_F02_system_verdict_is_runnable_but_conditional(self) -> None:
        """FINAL VERDICT: system is RUNNABLE_BUT_CONDITIONAL."""
        assert FINAL_SYSTEM_VERDICT == SystemVerdict.RUNNABLE_BUT_CONDITIONAL, (
            "Honest final verdict: the core single-device dispatch loop works "
            "when activation conditions are met, but the system is not a fully "
            "complete continuously-runnable center-distributed system."
        )

    def test_F03_rationale_non_empty(self) -> None:
        """Final verdict rationale is a non-empty string."""
        assert isinstance(FINAL_VERDICT_RATIONALE, str)
        assert len(FINAL_VERDICT_RATIONALE) > 0

    def test_F04_rationale_mentions_key_gaps(self) -> None:
        """Rationale mentions key gaps: reconnect, ReconciliationSignal, buffer."""
        rationale_lower = FINAL_VERDICT_RATIONALE.lower()
        assert "reconnect" in rationale_lower, "Rationale must mention reconnect gap"
        assert "reconciliation" in rationale_lower or "wire" in rationale_lower, (
            "Rationale must mention ReconciliationSignal or wire layer gap"
        )
        assert "buffer" in rationale_lower or "restart" in rationale_lower, (
            "Rationale must mention pending buffer or restart durability gap"
        )

    def test_F05_gaps_to_complete_count(self) -> None:
        """There are exactly 5 documented remaining gaps to achieve COMPLETE."""
        assert len(GAPS_TO_COMPLETE) == 5, (
            f"Expected 5 gaps_to_complete, got {len(GAPS_TO_COMPLETE)}. "
            "If a gap is resolved, update the corresponding capability verdict "
            "and remove the gap from this list."
        )

    def test_F06_gaps_cover_critical_areas(self) -> None:
        """Gaps list covers all four critical areas."""
        gaps_text = " ".join(GAPS_TO_COMPLETE).lower()
        assert "reconnect" in gaps_text, "gaps_to_complete must cover reconnect gap"
        assert "reconciliation" in gaps_text, "gaps_to_complete must cover ReconciliationSignal gap"
        assert "handoff" in gaps_text, "gaps_to_complete must cover HandoffEnvelopeV2 gap"
        assert "durable" in gaps_text or "buffer" in gaps_text, (
            "gaps_to_complete must cover durable buffer gap"
        )
        assert "governance" in gaps_text or "gate" in gaps_text, (
            "gaps_to_complete must cover governance gate gap"
        )

    def test_F07_system_is_not_missing_either(self) -> None:
        """System verdict is not MISSING: core loop does run."""
        assert FINAL_SYSTEM_VERDICT != SystemVerdict.MISSING, (
            "The system is not MISSING — core dispatch can run with activation. "
            "MISSING would overstate the gap."
        )


# ===========================================================================
# Group G — assert_final_verdict_invariants() enforcement
# ===========================================================================


class TestInvariantGuard:
    def test_G01_invariants_pass(self) -> None:
        """assert_final_verdict_invariants() passes without AssertionError."""
        assert_final_verdict_invariants()

    def test_G02_invariants_callable(self) -> None:
        """assert_final_verdict_invariants is callable and returns None."""
        result = assert_final_verdict_invariants()
        assert result is None

    def test_G03_transport_must_not_be_downgraded(self) -> None:
        """Downgrading transport_protocol_overall to non-COMPLETE breaks invariants."""
        # Verify the invariant function catches the violation
        original = FINAL_AUDIT_VERDICT["transport_protocol_overall"]
        FINAL_AUDIT_VERDICT["transport_protocol_overall"] = CapabilityVerdict.PARTIAL
        try:
            with pytest.raises(AssertionError, match="transport_protocol_overall"):
                assert_final_verdict_invariants()
        finally:
            FINAL_AUDIT_VERDICT["transport_protocol_overall"] = original

    def test_G04_perpetual_reconnect_must_not_be_upgraded(self) -> None:
        """Upgrading lifecycle_android_reconnect_perpetual to COMPLETE breaks invariants."""
        original = FINAL_AUDIT_VERDICT["lifecycle_android_reconnect_perpetual"]
        FINAL_AUDIT_VERDICT["lifecycle_android_reconnect_perpetual"] = CapabilityVerdict.COMPLETE
        try:
            with pytest.raises(AssertionError, match="lifecycle_android_reconnect_perpetual"):
                assert_final_verdict_invariants()
        finally:
            FINAL_AUDIT_VERDICT["lifecycle_android_reconnect_perpetual"] = original

    def test_G05_system_verdict_must_not_be_upgraded_to_complete(self) -> None:
        """Upgrading final_system_verdict to COMPLETE breaks invariants."""
        original = FINAL_AUDIT_VERDICT["final_system_verdict"]
        FINAL_AUDIT_VERDICT["final_system_verdict"] = SystemVerdict.COMPLETE
        try:
            with pytest.raises(AssertionError, match="final_system_verdict"):
                assert_final_verdict_invariants()
        finally:
            FINAL_AUDIT_VERDICT["final_system_verdict"] = original


# ===========================================================================
# Group H — FINAL_AUDIT_VERDICT dict completeness
# ===========================================================================


class TestVerdictDictCompleteness:
    REQUIRED_KEYS = [
        # Transport
        "transport_ws_path_alignment",
        "transport_legacy_alias_compat",
        "transport_android_report_type_coverage",
        "transport_ack_behavior",
        "transport_unknown_type_handling",
        "transport_protocol_overall",
        # Lifecycle
        "lifecycle_device_registration",
        "lifecycle_heartbeat_v2_side",
        "lifecycle_stale_cleanup",
        "lifecycle_android_reconnect_basic",
        "lifecycle_android_reconnect_perpetual",
        "lifecycle_android_boot_startup",
        "lifecycle_device_continuous_usability",
        "lifecycle_overall",
        # Dispatch
        "dispatch_legality_gates_present",
        "dispatch_device_routing",
        "dispatch_offline_buffering",
        "dispatch_result_ingestion_observable",
        "dispatch_completion_settlement",
        "dispatch_disconnect_reconnect_risk",
        "dispatch_durability_across_restart",
        "dispatch_execution_overall",
        # Multi-device
        "multi_device_single_device_local",
        "multi_device_multiple_devices",
        "multi_device_remote_access",
        "multi_device_plug_and_run",
        "multi_device_coordination_structure",
        "multi_device_simultaneous_reconnect_ordering",
        "multi_device_cross_repo_evidence_flow",
        "multi_device_overall",
        # Final verdict
        "final_system_verdict",
        "final_verdict_rationale",
        "gaps_to_complete",
    ]

    def test_H01_all_required_keys_present(self) -> None:
        """FINAL_AUDIT_VERDICT contains all required keys."""
        missing = [k for k in self.REQUIRED_KEYS if k not in FINAL_AUDIT_VERDICT]
        assert not missing, (
            f"FINAL_AUDIT_VERDICT is missing required keys: {missing}"
        )

    def test_H02_all_capability_verdicts_are_valid_enum_values(self) -> None:
        """All CapabilityVerdict entries in the dict are valid enum members."""
        capability_keys = [k for k in FINAL_AUDIT_VERDICT if k not in (
            "final_system_verdict", "final_verdict_rationale", "gaps_to_complete",
        )]
        valid_values = {v.value for v in CapabilityVerdict}
        # Also allow SystemVerdict for final_system_verdict
        system_values = {v.value for v in SystemVerdict}

        for key in capability_keys:
            val = FINAL_AUDIT_VERDICT[key]
            if isinstance(val, (CapabilityVerdict, SystemVerdict)):
                continue  # already a valid enum
            assert val in valid_values or val in system_values, (
                f"FINAL_AUDIT_VERDICT['{key}'] = {val!r} is not a valid "
                f"CapabilityVerdict or SystemVerdict value"
            )

    def test_H03_gaps_to_complete_is_list(self) -> None:
        """gaps_to_complete is a list."""
        assert isinstance(FINAL_AUDIT_VERDICT["gaps_to_complete"], list)

    def test_H04_rationale_is_string(self) -> None:
        """final_verdict_rationale is a string."""
        assert isinstance(FINAL_AUDIT_VERDICT["final_verdict_rationale"], str)


# ===========================================================================
# Group I — Cross-check with existing reality surfaces
# ===========================================================================


class TestCrossCheck:
    """Cross-check the final audit against the existing cross_device_integration_reality
    and dual_repo_system_completeness_review surfaces to ensure consistency."""

    def test_I01_cross_device_reality_surface_consistent(self) -> None:
        """Final audit is consistent with cross_device_integration_reality sentinels."""
        from core.cross_device_integration_reality import (
            WS_TRANSPORT_PROTOCOL_ALIGNED,
            ANDROID_RECONNECT_STOPS_PERMANENTLY_AT_LIMIT,
            INFLIGHT_TASK_LOSS_ON_DISCONNECT,
            PENDING_DELIVERY_BUFFER_PRESENT,
            RESULT_INGESTION_ERROR_COUNTERS_PRESENT,
            ANDROID_CROSS_DEVICE_DISABLED_BY_DEFAULT,
            REMOTE_ACCESS_REQUIRES_TAILSCALE_OR_VPNISH,
        )
        # WS transport aligned → TRANSPORT_WS_PATH_ALIGNMENT must be COMPLETE
        if WS_TRANSPORT_PROTOCOL_ALIGNED:
            assert TRANSPORT_WS_PATH_ALIGNMENT == CapabilityVerdict.COMPLETE

        # Android reconnect stops permanently → LIFECYCLE_ANDROID_RECONNECT_PERPETUAL must be MISSING
        if ANDROID_RECONNECT_STOPS_PERMANENTLY_AT_LIMIT:
            assert LIFECYCLE_ANDROID_RECONNECT_PERPETUAL == CapabilityVerdict.MISSING

        # Pending buffer present → DISPATCH_OFFLINE_BUFFERING is at least RUNNABLE_BUT_CONDITIONAL
        if PENDING_DELIVERY_BUFFER_PRESENT:
            assert DISPATCH_OFFLINE_BUFFERING != CapabilityVerdict.MISSING

        # Result ingestion counters present → DISPATCH_RESULT_INGESTION_OBSERVABLE is COMPLETE
        if RESULT_INGESTION_ERROR_COUNTERS_PRESENT:
            assert DISPATCH_RESULT_INGESTION_OBSERVABLE == CapabilityVerdict.COMPLETE

        # Android cross-device disabled by default → single device local is CONDITIONAL
        if ANDROID_CROSS_DEVICE_DISABLED_BY_DEFAULT:
            assert MULTI_DEVICE_SINGLE_DEVICE_LOCAL != CapabilityVerdict.COMPLETE

        # Remote access requires Tailscale → MULTI_DEVICE_REMOTE_ACCESS is CONDITIONAL
        if REMOTE_ACCESS_REQUIRES_TAILSCALE_OR_VPNISH:
            assert MULTI_DEVICE_REMOTE_ACCESS != CapabilityVerdict.COMPLETE

    def test_I02_dual_repo_verdict_not_fully_closed(self) -> None:
        """Dual-repo completeness review verdict is consistent: not fully_closed."""
        from core.dual_repo_system_completeness_review import (
            build_completeness_review,
            CompletenessVerdict,
        )
        report = build_completeness_review()
        assert report.verdict != CompletenessVerdict.fully_closed, (
            "dual_repo_system_completeness_review verdict must not be fully_closed. "
            "This is consistent with FINAL_SYSTEM_VERDICT != COMPLETE."
        )

    def test_I03_cross_repo_evidence_gap_consistent(self) -> None:
        """Cross-repo evidence gap is consistently MISSING in both surfaces."""
        from core.dual_repo_system_completeness_review import (
            build_completeness_review,
            CompletenessDimension,
            CompletenessLabel,
        )
        report = build_completeness_review()
        cross_repo = report.get_dimension(CompletenessDimension.cross_repo_evidence)
        assert cross_repo is not None
        assert cross_repo.label == CompletenessLabel.evidence_gap, (
            "cross_repo_evidence must be evidence_gap in completeness review."
        )
        # Final audit surface says MISSING — consistent (MISSING = more specific than evidence_gap)
        assert MULTI_DEVICE_CROSS_REPO_EVIDENCE_FLOW == CapabilityVerdict.MISSING

    def test_I04_completeness_review_has_blocking_gaps(self) -> None:
        """Dual-repo completeness review has blocking gaps (consistent with PARTIAL/MISSING areas)."""
        from core.dual_repo_system_completeness_review import build_completeness_review
        report = build_completeness_review()
        assert report.has_blocking_gaps, (
            "Completeness review must have blocking gaps, consistent with "
            "the final audit identifying MISSING capabilities."
        )
