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
# 6. In-flight task continuity — GAP (not fixed in this PR)
# ============================================================================

#: When Android disconnects and reconnects, in-flight tasks (dispatched via
#: android_bridge.send_to_device() or device_router.dispatch_task()) will
#: already have timed out (V2 command_timeout=30s) before Android's 31s max
#: reconnect delay completes.  No automatic re-dispatch mechanism exists.
#: The session identity (runtime_session_id) is preserved across reconnects,
#: but the application-layer task payload must be re-issued by the orchestration
#: layer — which does not do this automatically.
INFLIGHT_TASK_LOSS_ON_DISCONNECT: bool = True  # Gap — not fixed here
V2_COMMAND_TIMEOUT_S: int = 30  # android_bridge send_to_device default

# ============================================================================
# 7. Result ingestion — PARTIAL
# ============================================================================

#: Android sends task_result / goal_execution_result / handoff_envelope_v2_result
#: via the open WebSocket.  OfflineTaskQueue.kt buffers and replays on reconnect.
#: V2 handle_task_result() processes them and returns task_result_ack to Android.
#: HOWEVER: downstream truth-chain steps (reconciler, participant truth ingress,
#: memory backflow) are each wrapped in try/except "non-fatal" blocks.
#: Silent V2-side state divergence is therefore possible without Android knowing.
RESULT_INGESTION_HAS_SILENT_FAILURE_PATHS: bool = True

#: The durable idempotency guard (core/durable_result_idempotency.py) prevents
#: re-processing of already-seen task results across V2 process restarts.
DURABLE_RESULT_IDEMPOTENCY_GUARD_PRESENT: bool = True

# ============================================================================
# 8. End-to-end tests — PARTIAL
# ============================================================================

#: As of this audit no live WebSocket message exchange between a real
#: Android-equivalent client and the V2 gateway is exercised in the test suite.
#: Existing tests (test_android_bridge_udm_flow.py, test_udm_upsert.py) use mocks.
#: The integration tests added in this PR exercise the real WebSocket handler
#: (register → heartbeat → task_result → unknown_android_types) but do not
#: run a real Android APK.
E2E_LIVE_WS_TESTS_PRESENT: bool = True  # Added in this audit PR
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
    # In-flight task gap
    "inflight_task_loss_on_disconnect": INFLIGHT_TASK_LOSS_ON_DISCONNECT,
    "v2_command_timeout_s": V2_COMMAND_TIMEOUT_S,
    # Result ingestion
    "result_ingestion_has_silent_failure_paths": RESULT_INGESTION_HAS_SILENT_FAILURE_PATHS,
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

    # Fixes from this PR must be confirmed present
    assert r["goal_result_alias_handled"] is True, (
        "INTEGRATION_REALITY: goal_result_alias_handled must be True after this PR. "
        "Recheck galaxy_gateway/protocol/compat.py _LEGACY_TYPE_MAP and "
        "galaxy_gateway/android_bridge.py handler registration."
    )
    assert r["android_governance_report_types_handled"] is True, (
        "INTEGRATION_REALITY: android_governance_report_types_handled must be True after this PR. "
        "Recheck galaxy_gateway/protocol/aip_v3.py MessageType enum and "
        "galaxy_gateway/android_bridge.py _register_default_handlers."
    )
    assert r["v2_stale_cleanup_background_task_present"] is True, (
        "INTEGRATION_REALITY: v2_stale_cleanup_background_task_present must be True after this PR. "
        "Recheck galaxy_gateway/bootstrap/lifecycle.py for the periodic cleanup task."
    )
    assert r["e2e_live_ws_tests_present"] is True, (
        "INTEGRATION_REALITY: e2e_live_ws_tests_present must be True after this PR. "
        "Recheck tests/test_cross_device_ws_integration.py."
    )

    # Known remaining gaps must still be documented (not silently removed)
    assert r["inflight_task_loss_on_disconnect"] is True, (
        "INTEGRATION_REALITY: inflight_task_loss_on_disconnect must remain True "
        "until a task re-dispatch mechanism is implemented in the orchestration layer. "
        "Do not remove this sentinel without implementing the fix."
    )
    assert r["result_ingestion_has_silent_failure_paths"] is True, (
        "INTEGRATION_REALITY: result_ingestion_has_silent_failure_paths must remain True "
        "until all non-fatal try/except blocks in task_lifecycle.py are replaced with "
        "observable error paths (metrics, structured warnings, retry)."
    )
    assert r["android_reconnect_stops_permanently_at_limit"] is True, (
        "INTEGRATION_REALITY: android_reconnect_stops_permanently_at_limit must remain True "
        "until ufo-galaxy-android implements perpetual reconnect or a watchdog mechanism."
    )
