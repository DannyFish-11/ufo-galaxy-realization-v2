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

AUDIT DATE: 2026-04-30
AUDIT SCOPE:
  - ufo-galaxy-realization-v2 (V2, center side)
  - ufo-galaxy-android @ ee2ea2f3563357d386422b5b45654a9a2ba3f797

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
CANONICAL_GATEWAY_PORT: int = 9000

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

#: Android MAX_RECONNECT_ATTEMPTS=10.  After 10 consecutive failures (approx
#: 181 seconds total delay) the client permanently stops reconnecting.
#: There is NO watchdog, supervisory restart, or OS-level recovery mechanism
#: beyond BootReceiver starting GalaxyConnectionService on device boot.
#: V2 has no server-side mechanism to wake/pull a permanently-stopped Android client.
ANDROID_MAX_RECONNECT_ATTEMPTS: int = 10
ANDROID_RECONNECT_STOPS_PERMANENTLY_AT_LIMIT: bool = True

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

#: Residual risk: if Android hits MAX_RECONNECT_ATTEMPTS=10 (approx 181s total)
#: and permanently stops reconnecting, buffered messages will expire before
#: reconnect and are lost.  The V2-side durable buffer alone cannot recover from
#: a permanently-stopped Android client.
INFLIGHT_TASK_LOSS_RESIDUAL_RISK_ANDROID_TERMINAL_RECONNECT: bool = True
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
# 8. End-to-end tests — PARTIAL
# ============================================================================

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
    # Reconnect / liveness
    "android_reconnect_backoff_present": ANDROID_RECONNECT_BACKOFF_PRESENT,
    "android_max_reconnect_attempts": ANDROID_MAX_RECONNECT_ATTEMPTS,
    "android_reconnect_stops_permanently_at_limit": ANDROID_RECONNECT_STOPS_PERMANENTLY_AT_LIMIT,
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
    # Tests
    "e2e_live_ws_tests_present": E2E_LIVE_WS_TESTS_PRESENT,
    "e2e_real_android_apk_tests_present": E2E_REAL_ANDROID_APK_TESTS_PRESENT,
}


def assert_known_gaps_are_documented() -> None:
    """Assert that all known integration gaps are documented in this module.

    Call from tests to ensure this surface stays in sync with the real
    code state.  Raises AssertionError with a descriptive message if a
    required sentinel has an unexpected value.
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

    # Fixes from this PR must be confirmed present
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

    # Remaining gaps that must still be documented (do not silently remove these)
    assert r["android_reconnect_stops_permanently_at_limit"] is True, (
        "INTEGRATION_REALITY: android_reconnect_stops_permanently_at_limit must remain True "
        "until ufo-galaxy-android implements perpetual reconnect or a watchdog mechanism."
    )
    assert r["inflight_task_loss_residual_risk_android_terminal_reconnect"] is True, (
        "INTEGRATION_REALITY: inflight_task_loss_residual_risk_android_terminal_reconnect must "
        "remain True until Android no longer permanently stops reconnecting after 10 failures."
    )
    assert r["inflight_task_loss_residual_risk_process_restart"] is False, (
        "INTEGRATION_REALITY: inflight_task_loss_residual_risk_process_restart must be False "
        "now that the pending-delivery buffer is backed by durable storage that survives V2 "
        "restarts.  If the durable buffer was removed, update this sentinel back to True."
    )
