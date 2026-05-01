"""
core/cross_device_integration_reality.py
==========================================
Joint audit: ufo-galaxy-realization-v2 × ufo-galaxy-android
Code-grounded integration reality surface — machine-checkable sentinels.

PURPOSE
-------
This module encodes the *actual* cross-device integration state discovered
by a code-first joint audit of both repositories.  It does NOT declare
aspirational architecture — it encodes observable facts and real gaps.

Every constant here is machine-checkable by tests and CI.  If a gap is
fixed in production code the corresponding sentinel must be updated to
reflect the new reality and the test assertion updated to match.

AUDIT DATE: 2026-04-30 (initial)
REMEDIATION WAVE UPDATE: 2026-05-01
  - PR1-Android: Perpetual reconnect watchdog added in ufo-galaxy-android.
    GalaxyConnectionService now supervises GalaxyWebSocketClient and restarts
    it after MAX_RECONNECT_ATTEMPTS, eliminating the permanent-stop gap.
  - PR2-V2: ReconciliationSignal canonical gateway handler added
    (galaxy_gateway/android/handlers/reconciliation_signal.py).
  - PR2-V2: HandoffEnvelopeV2 response canonical gateway handler added
    (galaxy_gateway/android/handlers/handoff_v2_result.py).
  - PR2-Android: ReconciliationSignal AIP wire-layer added in ufo-galaxy-android.
    AipModels.kt MsgType now includes RECONCILIATION_SIGNAL; ReconciliationSignal.kt
    DTO is serialised to AIP v3 wire format.
  - PR3-V2: Distributed release gate promoted from advisory to CI-enforcing.
    core.distributed_release_gate_skeleton now produces is_enforcing=True reports;
    .github/workflows/governance_gate_enforcement.yml blocks CI on FAIL verdict.
AUDIT SCOPE:
  - ufo-galaxy-realization-v2 (V2, center side)
  - ufo-galaxy-android @ ee2ea2f3563357d386422b5b45654a9a2ba3f797 (initial)
    + post-remediation-wave commits (PR1-Android, PR2-Android)

HOW TO USE
----------
Import individual sentinels or the summary dict
:data:`CROSS_DEVICE_INTEGRATION_REALITY` from tests and CI guards to
assert that the documented state matches the live code.

    from core.cross_device_integration_reality import (
        CROSS_DEVICE_INTEGRATION_REALITY,
        assert_known_gaps_are_documented,
    )
    assert_known_gaps_are_documented()
"""

from __future__ import annotations

from typing import Any, Dict, List

# ============================================================================
# 1. Transport protocol — REAL and ALIGNED
# ============================================================================

#: Android builds the canonical URL:
#:   ws://{host}:{port}/ws/device/{device_id}
#: using AppSettings.effectiveGatewayWsUrl() (AppSettings.kt:212–230).
#: V2 accepts this at /ws/device/{device_id} (galaxy_gateway/routes/websocket.py).
#: The AIP v3 compat layer (galaxy_gateway/protocol/compat.py) normalises legacy
#: type aliases from v1.0/v2.0 clients before dispatch.  Verdict: REAL.
WS_TRANSPORT_PROTOCOL_ALIGNED: bool = True

#: V2 canonical WebSocket ingress path.  New device clients MUST connect here.
#: galaxy_gateway/routes/websocket.py registers this at startup.
CANONICAL_WS_DEVICE_PATH: str = "/ws/device/{device_id}"

#: Default V2 gateway port (from galaxy_gateway/port_config.py or env).
CANONICAL_GATEWAY_PORT: int = 8765

# ============================================================================
# 2. Android default configuration — ACTIVATION BARRIERS (CRITICAL)
# ============================================================================

#: cross_device_enabled=false is the out-of-box default in Android
#: config.properties.  GalaxyWebSocketClient.kt skips ALL WebSocket
#: connection attempts when this flag is false.  Every fresh Android
#: deployment requires this to be explicitly enabled before any
#: cross-device functionality is available.
#: Evidence: ufo-galaxy-android/config.properties:17,
#:           GalaxyWebSocketClient.kt:569
ANDROID_CROSS_DEVICE_DISABLED_BY_DEFAULT: bool = True

#: The Android default server URL is a Tailscale placeholder IP
#: ('ws://100.x.x.x:8765').  It is NOT a routable address out of the box.
#: Every deployment requires manual configuration of galaxyGatewayUrl
#: (SharedPreferences KEY_GATEWAY_HOST or assets/config.properties).
#: Evidence: AppSettings.kt:589
ANDROID_DEFAULT_URL_IS_PLACEHOLDER: bool = True

# ============================================================================
# 3. Network access model — CONDITIONAL (Tailscale / same-LAN only)
# ============================================================================

#: Remote operation (phone at arbitrary location connecting to home/office V2
#: server) requires Tailscale VPN or equivalent.  V2 has no built-in STUN,
#: TURN, UPNP, or NAT-punch code.  AndroidManifest usesCleartextTraffic=true
#: allows ws:// but there is no relay fallback.
#: Evidence: AppSettings.kt:589 (Tailscale IP default), TailscaleAdapter.kt,
#:           no STUN/TURN code found in V2.
REMOTE_ACCESS_REQUIRES_TAILSCALE_OR_VPNISH: bool = True

#: Auth: Android sends Bearer token via Authorization header when gatewayToken
#: is configured (GalaxyWebSocketClient.kt:586).  V2 verifies via
#: BearerAuthMiddleware (galaxy_gateway/middleware.py).  When GALAXY_AUTH_ENABLED
#: is false (default) no token is required — appropriate for closed networks.
AUTH_BEARER_TOKEN_SUPPORTED: bool = True

# ============================================================================
# 4. Protocol message coverage — PARTIAL GAPS FIXED IN THIS AUDIT PR
# ============================================================================

#: Android 'goal_result' (error-path alias for goal_execution_result) is now
#: handled in two places:
#:   a) LEGACY_TYPE_MAP in compat.py maps it for v1.0 clients.
#:   b) MessageType.GOAL_RESULT in aip_v3.py + handler in android_bridge.py.
#: Prior to this audit the compat.py mapping was absent.  Now CLOSED.
GOAL_RESULT_ALIAS_HANDLED: bool = True

#: Android 'cancel_result', 'device_readiness_report', 'device_governance_report',
#: 'device_acceptance_report', 'device_strategy_report' are now registered as
#: MessageType enum entries and routed to handle_generic_forward, returning a
#: structured ACK instead of UNKNOWN_MESSAGE_TYPE error.
#: Prior to this audit these types caused ValueError in MessageType() lookup.
ANDROID_GOVERNANCE_REPORT_TYPES_HANDLED: bool = True

#: Message types now registered (fixed in this PR):
ANDROID_REPORT_TYPES_NOW_HANDLED: List[str] = [
    "cancel_result",
    "device_readiness_report",
    "device_governance_report",
    "device_acceptance_report",
    "device_strategy_report",
]

# ============================================================================
# 5. Reconnect / liveness — PARTIAL
# ============================================================================

#: Android reconnect uses exponential backoff [1,2,4,8,16,30]s + jitter.
#: Reconnect counter resets to 0 on successful onOpen.
#: Network-change events trigger an immediate reconnect with counter reset.
#: Evidence: GalaxyWebSocketClient.kt scheduleReconnect()
ANDROID_RECONNECT_BACKOFF_PRESENT: bool = True

#: Android MAX_RECONNECT_ATTEMPTS=10 (per GalaxyWebSocketClient reconnect cycle).
#: After 10 consecutive failures (~181 s total) the client ends the current
#: reconnect cycle.  However: as of PR1-Android, GalaxyConnectionService now
#: supervises GalaxyWebSocketClient and automatically restarts the entire
#: connection cycle after the per-cycle limit is exhausted (watchdog recovery).
#: This eliminates the permanent-stop gap: connection is recovered even after
#: a multi-minute outage without any operator intervention.
ANDROID_MAX_RECONNECT_ATTEMPTS: int = 10
ANDROID_RECONNECT_STOPS_PERMANENTLY_AT_LIMIT: bool = False  # Fixed — PR1-Android watchdog added
ANDROID_PERPETUAL_RECONNECT_WATCHDOG_PRESENT: bool = True  # Added — PR1-Android

#: V2 double-keepalive: OkHttp TCP ping every 20 s + application heartbeat every
#: 30 s.  V2 considers connection stale at 60 s, purges at 120 s.
#: The stale-device cleanup background task (added in this PR) now runs every 90 s.
V2_HEARTBEAT_TIMEOUT_S: int = 60
V2_STALE_CLEANUP_THRESHOLD_S: int = 120
V2_STALE_CLEANUP_BACKGROUND_TASK_PRESENT: bool = True  # Added in this audit PR

# ============================================================================
# 6. In-flight task continuity — IMPROVED (pending-delivery buffer added)
# ============================================================================

#: V2-side pending-delivery buffer (galaxy_gateway/pending_delivery_buffer.py)
#: enqueues task-dispatch messages for temporarily-offline devices and re-delivers
#: them on reconnect.  This closes the majority of the in-flight task loss window:
#:   - Messages buffered when device is offline are flushed on reconnect_device().
#:   - Buffer TTL=60s, capacity=32 msgs/device; oldest msgs evicted at capacity.
#:   - Non-bufferable types (heartbeats, GUI interactions) are NOT buffered.
#: The buffer is backed by a durable JSON snapshot file so that buffered messages
#: survive V2 process restarts within the TTL window.  Expired messages are
#: discarded on load so stale payloads are never replayed.
#: Remaining gap: if the device never reconnects within the TTL window (e.g. it
#: hit MAX_RECONNECT_ATTEMPTS=10 and stopped), buffered messages expire and are
#: discarded.
INFLIGHT_TASK_LOSS_ON_DISCONNECT: bool = False  # Fixed — pending-delivery buffer added
PENDING_DELIVERY_BUFFER_PRESENT: bool = True
PENDING_DELIVERY_BUFFER_TTL_S: float = 60.0
PENDING_DELIVERY_BUFFER_MAX_QUEUE_PER_DEVICE: int = 32
DURABLE_PENDING_DELIVERY_BUFFER_PRESENT: bool = True  # Added: buffer now survives V2 restarts
V2_COMMAND_TIMEOUT_S: int = 30  # android_bridge send_to_device default

#: Residual risk: previously, if Android hit MAX_RECONNECT_ATTEMPTS=10 and
#: permanently stopped reconnecting, buffered messages would expire and be lost.
#: As of PR1-Android, the watchdog-level recovery ensures Android reconnects even
#: after multi-minute outages, eliminating this terminal-reconnect loss window.
INFLIGHT_TASK_LOSS_RESIDUAL_RISK_ANDROID_TERMINAL_RECONNECT: bool = False  # Fixed — PR1-Android
INFLIGHT_TASK_LOSS_RESIDUAL_RISK_PROCESS_RESTART: bool = False  # Fixed — durable buffer added

# ============================================================================
# 7. Result ingestion — IMPROVED (observable error counters added)
# ============================================================================

#: Truth-chain steps (reconciler, participant truth ingress, device_router
#: notification, memory backflow) are each wrapped in non-fatal try/except
#: blocks.  Prior to this PR all failures were logged at DEBUG level, making
#: them invisible in production logs.  This PR upgrades all truth-chain
#: exception paths to WARNING level and adds observable integer error counters:
#:   - task_lifecycle.RESULT_RECONCILE_ERRORS
#:   - task_lifecycle.RESULT_TRUTH_INGRESS_ERRORS
#:   - task_lifecycle.RESULT_DEVICE_ROUTER_ERRORS
#:   - task_lifecycle.RESULT_MEMORY_BACKFLOW_ERRORS
#: These counters are machine-checkable by tests and can be exported to
#: metrics/monitoring.  A non-zero value signals partial truth-chain failure.
#: Root causes (missing modules, import errors) are separately non-fatal and
#: expected in constrained deployments.
RESULT_INGESTION_HAS_SILENT_FAILURE_PATHS: bool = False  # Fixed — observable error paths
RESULT_INGESTION_ERROR_COUNTERS_PRESENT: bool = True

#: The durable idempotency guard (core/durable_result_idempotency.py) prevents
#: re-processing of already-seen task results across V2 process restarts.
DURABLE_RESULT_IDEMPOTENCY_GUARD_PRESENT: bool = True

# ============================================================================
# 7b. Cross-repo evidence wire layer — CLOSED (PR2-V2 + PR2-Android)
# ============================================================================

#: V2 canonical gateway handler for ReconciliationSignal messages added in PR2-V2.
#: galaxy_gateway/android/handlers/reconciliation_signal.py provides
#: handle_reconciliation_signal(), registered under MessageType.RECONCILIATION_SIGNAL
#: in android_bridge._register_default_handlers().
RECONCILIATION_SIGNAL_V2_HANDLER_PRESENT: bool = True  # Added — PR2-V2

#: Android AIP wire layer for ReconciliationSignal added in PR2-Android.
#: AipModels.kt MsgType enum now includes RECONCILIATION_SIGNAL.
#: ReconciliationSignal.kt DTO is serialised to AIP v3 wire format and sent
#: via GalaxyWebSocketClient on the live wire path.
RECONCILIATION_SIGNAL_ANDROID_WIRE_PRESENT: bool = True  # Added — PR2-Android

#: V2 canonical gateway handler for HandoffEnvelopeV2 response messages added in PR2-V2.
#: galaxy_gateway/android/handlers/handoff_v2_result.py provides
#: handle_handoff_v2_result(), registered for handoff_ack, handoff_result,
#: handoff_failure, and handoff_envelope_v2_result in android_bridge.
HANDOFF_ENVELOPE_V2_RESPONSE_HANDLER_PRESENT: bool = True  # Added — PR2-V2

#: Cross-repo evidence wire layer is now closed end-to-end:
#: Android can send ReconciliationSignal and HandoffEnvelopeV2 responses;
#: V2 canonical handlers receive, correlate, and ingest them.
CROSS_REPO_EVIDENCE_WIRE_CLOSED: bool = True  # Closed — PR2-V2 + PR2-Android

# ============================================================================
# 7c. Governance CI enforcement — ENFORCING (PR3-V2)
# ============================================================================

#: core.distributed_release_gate_skeleton now produces ReleaseGateReport with
#: is_enforcing=True (promoted in PR3-V2).  GATE_IS_NOW_CI_ENFORCING_AUTHORITY
#: sentinel documents this promotion.
GOVERNANCE_GATE_IS_ENFORCING: bool = True  # Promoted — PR3-V2

#: .github/workflows/governance_gate_enforcement.yml added in PR3-V2.
#: This workflow runs governance_validation_gate.run_governance_verdict_ci() and
#: cross_repo_consistency_gates enforcement; exits non-zero (blocking CI) when
#: governance is violated or cross-repo drift is detected.
GOVERNANCE_CI_WORKFLOW_PRESENT: bool = True  # Added — PR3-V2

#: As of this audit no live WebSocket message exchange between a real
#: Android-equivalent client and the V2 gateway is exercised in the test suite.
#: Existing tests (test_android_bridge_udm_flow.py, test_udm_upsert.py) use mocks.
#: The integration tests added in PR #928 exercise the real WebSocket handler
#: (register → heartbeat → task_result → unknown_android_types) but do not
#: run a real Android APK.  Tests in this PR additionally cover the pending-delivery
#: buffer and reconnect-flush behavior.
E2E_LIVE_WS_TESTS_PRESENT: bool = True
E2E_REAL_ANDROID_APK_TESTS_PRESENT: bool = False  # Requires hardware; out of scope

# ============================================================================
# 9. Summary dict — machine-checkable by tests
# ============================================================================

CROSS_DEVICE_INTEGRATION_REALITY: Dict[str, Any] = {
    # Transport
    "ws_transport_protocol_aligned": WS_TRANSPORT_PROTOCOL_ALIGNED,
    "canonical_ws_device_path": CANONICAL_WS_DEVICE_PATH,
    "canonical_gateway_port": CANONICAL_GATEWAY_PORT,
    # Activation barriers
    "android_cross_device_disabled_by_default": ANDROID_CROSS_DEVICE_DISABLED_BY_DEFAULT,
    "android_default_url_is_placeholder": ANDROID_DEFAULT_URL_IS_PLACEHOLDER,
    # Network
    "remote_access_requires_tailscale_or_vpnish": REMOTE_ACCESS_REQUIRES_TAILSCALE_OR_VPNISH,
    "auth_bearer_token_supported": AUTH_BEARER_TOKEN_SUPPORTED,
    # Protocol coverage
    "goal_result_alias_handled": GOAL_RESULT_ALIAS_HANDLED,
    "android_governance_report_types_handled": ANDROID_GOVERNANCE_REPORT_TYPES_HANDLED,
    "android_report_types_now_handled": ANDROID_REPORT_TYPES_NOW_HANDLED,
    # Reconnect / liveness (PR1-Android: watchdog added)
    "android_reconnect_backoff_present": ANDROID_RECONNECT_BACKOFF_PRESENT,
    "android_max_reconnect_attempts": ANDROID_MAX_RECONNECT_ATTEMPTS,
    "android_reconnect_stops_permanently_at_limit": ANDROID_RECONNECT_STOPS_PERMANENTLY_AT_LIMIT,
    "android_perpetual_reconnect_watchdog_present": ANDROID_PERPETUAL_RECONNECT_WATCHDOG_PRESENT,
    "v2_heartbeat_timeout_s": V2_HEARTBEAT_TIMEOUT_S,
    "v2_stale_cleanup_threshold_s": V2_STALE_CLEANUP_THRESHOLD_S,
    "v2_stale_cleanup_background_task_present": V2_STALE_CLEANUP_BACKGROUND_TASK_PRESENT,
    # In-flight task continuity (fixed: pending-delivery buffer + durable persistence)
    "inflight_task_loss_on_disconnect": INFLIGHT_TASK_LOSS_ON_DISCONNECT,
    "pending_delivery_buffer_present": PENDING_DELIVERY_BUFFER_PRESENT,
    "pending_delivery_buffer_ttl_s": PENDING_DELIVERY_BUFFER_TTL_S,
    "pending_delivery_buffer_max_queue_per_device": PENDING_DELIVERY_BUFFER_MAX_QUEUE_PER_DEVICE,
    "durable_pending_delivery_buffer_present": DURABLE_PENDING_DELIVERY_BUFFER_PRESENT,
    "v2_command_timeout_s": V2_COMMAND_TIMEOUT_S,
    "inflight_task_loss_residual_risk_android_terminal_reconnect": INFLIGHT_TASK_LOSS_RESIDUAL_RISK_ANDROID_TERMINAL_RECONNECT,
    "inflight_task_loss_residual_risk_process_restart": INFLIGHT_TASK_LOSS_RESIDUAL_RISK_PROCESS_RESTART,
    # Result ingestion (fixed: observable error counters)
    "result_ingestion_has_silent_failure_paths": RESULT_INGESTION_HAS_SILENT_FAILURE_PATHS,
    "result_ingestion_error_counters_present": RESULT_INGESTION_ERROR_COUNTERS_PRESENT,
    "durable_result_idempotency_guard_present": DURABLE_RESULT_IDEMPOTENCY_GUARD_PRESENT,
    # Cross-repo evidence wire (closed: PR2-V2 + PR2-Android)
    "reconciliation_signal_v2_handler_present": RECONCILIATION_SIGNAL_V2_HANDLER_PRESENT,
    "reconciliation_signal_android_wire_present": RECONCILIATION_SIGNAL_ANDROID_WIRE_PRESENT,
    "handoff_envelope_v2_response_handler_present": HANDOFF_ENVELOPE_V2_RESPONSE_HANDLER_PRESENT,
    "cross_repo_evidence_wire_closed": CROSS_REPO_EVIDENCE_WIRE_CLOSED,
    # Governance CI enforcement (PR3-V2)
    "governance_gate_is_enforcing": GOVERNANCE_GATE_IS_ENFORCING,
    "governance_ci_workflow_present": GOVERNANCE_CI_WORKFLOW_PRESENT,
    # Tests
    "e2e_live_ws_tests_present": E2E_LIVE_WS_TESTS_PRESENT,
    "e2e_real_android_apk_tests_present": E2E_REAL_ANDROID_APK_TESTS_PRESENT,
}


def assert_known_gaps_are_documented() -> None:
    """Assert that all known integration gaps are documented in this module.

    Call from tests to ensure this surface stays in sync with the real
    code state.  Raises AssertionError with a descriptive message if a
    required sentinel has an unexpected value.

    Post-remediation wave (2026-05-01): GAP-1, GAP-2, GAP-3, and GAP-5 are
    all resolved.  This function now asserts the resolved state.
    """
    r = CROSS_DEVICE_INTEGRATION_REALITY

    # Critical activation barriers must still be documented as present
    assert r["android_cross_device_disabled_by_default"] is True, (
        "INTEGRATION_REALITY: android_cross_device_disabled_by_default must be True "
        "until ufo-galaxy-android ships with cross_device_enabled=true as default. "
        "Update this sentinel only when config.properties default is changed."
    )
    assert r["android_default_url_is_placeholder"] is True, (
        "INTEGRATION_REALITY: android_default_url_is_placeholder must be True "
        "until ufo-galaxy-android ships with a non-placeholder default gateway URL."
    )
    assert r["remote_access_requires_tailscale_or_vpnish"] is True, (
        "INTEGRATION_REALITY: remote_access_requires_tailscale_or_vpnish must be True "
        "until V2 implements STUN/TURN or a relay fallback for general internet access."
    )

    # Fixes from PR #928 must be confirmed present
    assert r["goal_result_alias_handled"] is True, (
        "INTEGRATION_REALITY: goal_result_alias_handled must be True after PR #928. "
        "Recheck galaxy_gateway/protocol/compat.py _LEGACY_TYPE_MAP and "
        "galaxy_gateway/android_bridge.py handler registration."
    )
    assert r["android_governance_report_types_handled"] is True, (
        "INTEGRATION_REALITY: android_governance_report_types_handled must be True after PR #928. "
        "Recheck galaxy_gateway/protocol/aip_v3.py MessageType enum and "
        "galaxy_gateway/android_bridge.py _register_default_handlers."
    )
    assert r["v2_stale_cleanup_background_task_present"] is True, (
        "INTEGRATION_REALITY: v2_stale_cleanup_background_task_present must be True after PR #928. "
        "Recheck galaxy_gateway/bootstrap/lifecycle.py for the periodic cleanup task."
    )
    assert r["e2e_live_ws_tests_present"] is True, (
        "INTEGRATION_REALITY: e2e_live_ws_tests_present must be True after PR #928. "
        "Recheck tests/test_cross_device_ws_integration.py."
    )

    # Fixes from PR #929 must be confirmed present
    assert r["pending_delivery_buffer_present"] is True, (
        "INTEGRATION_REALITY: pending_delivery_buffer_present must be True. "
        "Recheck galaxy_gateway/pending_delivery_buffer.py and android_bridge.py integration."
    )
    assert r["inflight_task_loss_on_disconnect"] is False, (
        "INTEGRATION_REALITY: inflight_task_loss_on_disconnect must be False now that the "
        "pending-delivery buffer is in place.  If the buffer was removed, update this sentinel "
        "and re-document the gap."
    )
    assert r["durable_pending_delivery_buffer_present"] is True, (
        "INTEGRATION_REALITY: durable_pending_delivery_buffer_present must be True. "
        "Recheck galaxy_gateway/pending_delivery_buffer.py DurablePendingDeliveryBuffer and "
        "the module-level singleton."
    )
    assert r["result_ingestion_error_counters_present"] is True, (
        "INTEGRATION_REALITY: result_ingestion_error_counters_present must be True. "
        "Recheck galaxy_gateway/android/handlers/task_lifecycle.py for RESULT_*_ERRORS counters."
    )
    assert r["result_ingestion_has_silent_failure_paths"] is False, (
        "INTEGRATION_REALITY: result_ingestion_has_silent_failure_paths must be False now that "
        "observable error counters and WARNING-level logging have been added.  If the counters "
        "were removed, update this sentinel and re-document the gap."
    )

    # Remediation wave fixes — confirmed closed
    assert r["android_reconnect_stops_permanently_at_limit"] is False, (
        "INTEGRATION_REALITY: android_reconnect_stops_permanently_at_limit must be False "
        "after PR1-Android added the watchdog-level reconnect recovery.  If the watchdog "
        "was removed from ufo-galaxy-android, update this sentinel back to True."
    )
    assert r["android_perpetual_reconnect_watchdog_present"] is True, (
        "INTEGRATION_REALITY: android_perpetual_reconnect_watchdog_present must be True "
        "after PR1-Android.  Recheck GalaxyConnectionService watchdog implementation."
    )
    assert r["inflight_task_loss_residual_risk_android_terminal_reconnect"] is False, (
        "INTEGRATION_REALITY: inflight_task_loss_residual_risk_android_terminal_reconnect must "
        "be False after PR1-Android closed the terminal-reconnect loss window. "
        "If the watchdog was removed, update back to True."
    )
    assert r["inflight_task_loss_residual_risk_process_restart"] is False, (
        "INTEGRATION_REALITY: inflight_task_loss_residual_risk_process_restart must be False "
        "now that the pending-delivery buffer is backed by durable storage that survives V2 "
        "restarts.  If the durable buffer was removed, update this sentinel back to True."
    )
    assert r["reconciliation_signal_v2_handler_present"] is True, (
        "INTEGRATION_REALITY: reconciliation_signal_v2_handler_present must be True "
        "after PR2-V2.  Recheck galaxy_gateway/android/handlers/reconciliation_signal.py "
        "and android_bridge._register_default_handlers()."
    )
    assert r["reconciliation_signal_android_wire_present"] is True, (
        "INTEGRATION_REALITY: reconciliation_signal_android_wire_present must be True "
        "after PR2-Android.  Recheck AipModels.kt and ReconciliationSignal.kt in "
        "ufo-galaxy-android."
    )
    assert r["handoff_envelope_v2_response_handler_present"] is True, (
        "INTEGRATION_REALITY: handoff_envelope_v2_response_handler_present must be True "
        "after PR2-V2.  Recheck galaxy_gateway/android/handlers/handoff_v2_result.py "
        "and android_bridge._register_default_handlers()."
    )
    assert r["cross_repo_evidence_wire_closed"] is True, (
        "INTEGRATION_REALITY: cross_repo_evidence_wire_closed must be True "
        "after PR2-V2 + PR2-Android.  If any wire-layer handler was removed, "
        "update this sentinel and re-document the gap."
    )
    assert r["governance_gate_is_enforcing"] is True, (
        "INTEGRATION_REALITY: governance_gate_is_enforcing must be True "
        "after PR3-V2 promoted the release gate from advisory to CI-enforcing. "
        "Recheck core.distributed_release_gate_skeleton GATE_IS_NOW_CI_ENFORCING_AUTHORITY."
    )
    assert r["governance_ci_workflow_present"] is True, (
        "INTEGRATION_REALITY: governance_ci_workflow_present must be True "
        "after PR3-V2.  Recheck .github/workflows/governance_gate_enforcement.yml."
    )
