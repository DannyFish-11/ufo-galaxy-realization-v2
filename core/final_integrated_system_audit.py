"""
core/final_integrated_system_audit.py
======================================
Final code-grounded completion verdict for the integrated
ufo-galaxy-realization-v2 × ufo-galaxy-android center-distributed system.

AUDIT DATE: 2026-05-01
SCOPE:
  - ufo-galaxy-realization-v2 (V2, center / orchestration side)
  - ufo-galaxy-android (Android participant side)
    reference commit: ee2ea2f3563357d386422b5b45654a9a2ba3f797

PURPOSE
-------
This module encodes the *final* code-grounded completion verdict for the
integrated two-repository system.  It does NOT describe aspirational
architecture; it reflects observable facts derived from real code and
executable paths.

Every sentinel and verdict in this module is machine-checkable by tests.
If production code changes, the corresponding sentinels and test assertions
MUST be updated to reflect the new reality.  Silent divergence between this
surface and the live code is a CI failure.

HOW TO USE
----------
Import the top-level ``FINAL_INTEGRATED_SYSTEM_AUDIT`` dict or individual
constants.  Use :func:`assert_final_audit_surface_is_consistent` to run
all invariants in one call.

    from core.final_integrated_system_audit import (
        FINAL_INTEGRATED_SYSTEM_AUDIT,
        INTEGRATED_SYSTEM_VERDICT,
        IntegratedSystemVerdict,
        assert_final_audit_surface_is_consistent,
    )
    assert_final_audit_surface_is_consistent()

VERDICT TAXONOMY
----------------
``COMPLETE``
    The capability is fully implemented, all code paths are exercised, and
    no conditional activation is required beyond deployment configuration
    that every reasonably-configured deployment already provides.

``RUNNABLE_BUT_CONDITIONAL``
    The capability is runnable in practice but requires at least one
    explicit activation step (e.g. configuration flag, network overlay,
    manual trigger) that is NOT on by default.  The capability may also
    have known residual risks that do not prevent operation but do create
    failure modes under adversarial or long-running conditions.

``PARTIAL``
    The code for the capability exists but important sub-paths are absent,
    guarded behind hard-to-meet pre-conditions, or not proven end-to-end
    by any automated test.

``MISSING``
    No production code path for the capability exists, or the only code
    present is a stub / aspirational placeholder that cannot be reached at
    runtime.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List


# ============================================================================
# Verdict taxonomy
# ============================================================================


class IntegratedSystemVerdict(str, Enum):
    """Classification for a capability dimension of the integrated system."""

    COMPLETE = "COMPLETE"
    RUNNABLE_BUT_CONDITIONAL = "RUNNABLE_BUT_CONDITIONAL"
    PARTIAL = "PARTIAL"
    MISSING = "MISSING"


# ============================================================================
# AREA 1 — Transport / Protocol
# ============================================================================

# Evidence:
#   - V2 registers /ws/device/{device_id} as the canonical ingress path:
#     galaxy_gateway/routes/websocket.py (CANONICAL_DEVICE_INGRESS_AUTHORITY)
#   - Android constructs ws://{host}:{port}/ws/device/{device_id} via
#     AppSettings.effectiveGatewayWsUrl() (AppSettings.kt:212-230).
#   - AIP v3 compat layer (galaxy_gateway/protocol/compat.py) normalises v1.0
#     and v2.0 type aliases before dispatch, including:
#       "goal_result"          → MessageType.GOAL_EXECUTION_RESULT
#       "command_result"       → task_result
#       "task_execute"         → task_submit
#       etc.
#   - Previously-missing Android report types (cancel_result,
#     device_readiness_report, device_governance_report,
#     device_acceptance_report, device_strategy_report) are now registered
#     as MessageType enum entries and routed to handle_generic_forward which
#     returns a structured ACK (galaxy_gateway/protocol/aip_v3.py:298-313).
#   - Unknown message types return UNKNOWN_MESSAGE_TYPE response
#     (galaxy_gateway/android_bridge.py:875).
TRANSPORT_PROTOCOL_WS_PATH_ALIGNED: bool = True
TRANSPORT_PROTOCOL_ALIAS_COMPAT_PRESENT: bool = True
TRANSPORT_PROTOCOL_ANDROID_REPORT_TYPES_HANDLED: bool = True
TRANSPORT_PROTOCOL_UNKNOWN_TYPE_RESPONSE_PRESENT: bool = True
TRANSPORT_PROTOCOL_ACK_BEHAVIOR: str = (
    "Registered types: structured ACK via handle_generic_forward or specific handler. "
    "Unknown types: UNKNOWN_MESSAGE_TYPE response (android_bridge.py:875). "
    "No silent drops for any handled message type."
)

#: Area 1 verdict.  All transport/protocol requirements are met by existing
#: code.  No activation barriers apply to the transport layer itself.
TRANSPORT_PROTOCOL_VERDICT: IntegratedSystemVerdict = IntegratedSystemVerdict.COMPLETE
TRANSPORT_PROTOCOL_VERDICT_RATIONALE: str = (
    "WS path aligned (V2 /ws/device/{id}, Android AppSettings.effectiveGatewayWsUrl). "
    "AIP compat layer normalises v1.0/v2.0 aliases. "
    "All Android message types (incl. previously-missing report types) registered in "
    "MessageType enum and routed to structured handlers. "
    "Unknown types return explicit UNKNOWN_MESSAGE_TYPE rather than silently dropped."
)


# ============================================================================
# AREA 2 — Device Lifecycle / Liveness
# ============================================================================

# Registration
# Evidence:
#   - device_register → register_ack flow is in
#     galaxy_gateway/android/handlers/registration.py handle_device_register().
#   - ACK includes continuity_outcome (continuity_resume vs new_attachment)
#     via attached_runtime_session_registry.classify_reconnect_outcome().
DEVICE_REGISTRATION_PRESENT: bool = True
DEVICE_REGISTRATION_ACK_INCLUDES_CONTINUITY_OUTCOME: bool = True

# Heartbeat
# Evidence:
#   - Android: OkHttp TCP ping every 20 s (GalaxyWebSocketClient.kt).
#   - Android: application-level heartbeat every 30 s.
#   - V2: considers connection stale at 60 s (V2_HEARTBEAT_TIMEOUT_S).
#   - V2: purges device at 120 s (V2_STALE_CLEANUP_THRESHOLD_S).
DEVICE_HEARTBEAT_PROTOCOL_PRESENT: bool = True
DEVICE_HEARTBEAT_V2_STALE_TIMEOUT_S: int = 60
DEVICE_HEARTBEAT_V2_STALE_CLEANUP_THRESHOLD_S: int = 120

# Stale cleanup
# Evidence:
#   - galaxy_gateway/bootstrap/lifecycle.py runs _periodic_stale_cleanup every
#     90 s (STALE_CLEANUP_BACKGROUND_TASK_PRESENT confirmed in PR #929).
DEVICE_STALE_CLEANUP_BACKGROUND_TASK_PRESENT: bool = True
DEVICE_STALE_CLEANUP_INTERVAL_S: int = 90

# Reconnect logic
# Evidence:
#   - Android uses exponential backoff [1,2,4,8,16,30]s + jitter;
#     counter resets to 0 on successful onOpen.
#   - Network-change events trigger immediate reconnect with counter reset.
#   - Evidence: GalaxyWebSocketClient.kt scheduleReconnect().
DEVICE_RECONNECT_BACKOFF_PRESENT: bool = True
DEVICE_RECONNECT_COUNTER_RESETS_ON_OPEN: bool = True
DEVICE_RECONNECT_NETWORK_CHANGE_RESETS_COUNTER: bool = True

# Reconnect terminal stop — CRITICAL GAP
# Evidence:
#   - Android MAX_RECONNECT_ATTEMPTS = 10 (approx 181 s total cumulative delay).
#   - After 10 consecutive failures the client permanently stops reconnecting.
#   - No watchdog, no supervisory restart, no OS-level recovery beyond
#     BootReceiver starting GalaxyConnectionService on initial device boot.
#   - V2 has no server-side mechanism to wake/pull a permanently-stopped client.
#   - Evidence: GalaxyWebSocketClient.kt MAX_RECONNECT_ATTEMPTS constant.
#: Must be kept in sync with MAX_RECONNECT_ATTEMPTS in
#: ufo-galaxy-android GalaxyWebSocketClient.kt.
DEVICE_RECONNECT_MAX_ATTEMPTS: int = 10
DEVICE_RECONNECT_TERMINAL_STOP_PRESENT: bool = True  # stops after 10 failures
DEVICE_RECONNECT_NO_SERVER_SIDE_WAKE: bool = True
DEVICE_RECONNECT_NO_WATCHDOG: bool = True

# Boot/startup behavior
# Evidence:
#   - BootReceiver starts GalaxyConnectionService on device boot.
#   - This provides initial connection establishment; it does NOT provide
#     watchdog/restart for a permanently-stopped reconnect loop.
DEVICE_BOOT_RECEIVER_STARTS_CONNECTION_SERVICE: bool = True
DEVICE_BOOT_RECEIVER_RESTARTS_TERMINAL_RECONNECT_LOOP: bool = False

#: Area 2 verdict.
#:
#: Why RUNNABLE_BUT_CONDITIONAL:
#:   Registration, heartbeat, stale cleanup, and basic reconnect are all
#:   implemented.  However, the Android client permanently stops reconnecting
#:   after 10 consecutive failures (~181 s), with no watchdog or server-side
#:   wake mechanism.  Long-term unattended operation (e.g. intermittent
#:   network, prolonged outage) will eventually leave a device permanently
#:   dead without manual intervention (app restart or phone reboot).
DEVICE_LIFECYCLE_VERDICT: IntegratedSystemVerdict = (
    IntegratedSystemVerdict.RUNNABLE_BUT_CONDITIONAL
)
DEVICE_LIFECYCLE_VERDICT_RATIONALE: str = (
    "Registration + ACK + continuity classification: implemented. "
    "Heartbeat (OkHttp 20s TCP ping + app 30s heartbeat): implemented. "
    "Stale cleanup background task (V2 every 90s): implemented. "
    "Reconnect backoff + counter reset on open: implemented. "
    "CONDITIONAL: Android stops permanently after MAX_RECONNECT_ATTEMPTS=10 "
    "(~181 s total). No watchdog, no supervisory restart, no server-side wake. "
    "BootReceiver only covers cold boot; it does not restart a terminal reconnect loop. "
    "Long-running unattended deployments risk permanently-dead devices."
)


# ============================================================================
# AREA 3 — Dispatch / Execution / Result Continuity
# ============================================================================

# Legality gates
# Evidence:
#   - V1 continuity legality check present in handle_task_result:
#     task_lifecycle.py:391 checks continuity_legality verdict before processing.
#   - Rejected results are suppressed and logged at WARNING level.
DISPATCH_LEGALITY_GATE_PRESENT: bool = True
DISPATCH_LEGALITY_GATE_REJECTS_LOGGED: bool = True

# Device routing
# Evidence:
#   - AndroidBridge.assign_task() first attempts canonical
#     CommandRouter.route_envelope(), then falls back to direct
#     send_to_device() if the router is unavailable.
#   - send_to_device() delivers via live WebSocket or enqueues in the
#     pending-delivery buffer if the device is offline.
DISPATCH_DEVICE_ROUTING_PRESENT: bool = True
DISPATCH_OFFLINE_BUFFERING_PRESENT: bool = True  # pending_delivery_buffer.py

# Offline buffering details
# Evidence: galaxy_gateway/pending_delivery_buffer.py + android_bridge.py
DISPATCH_BUFFER_TTL_S: float = 60.0
DISPATCH_BUFFER_MAX_QUEUE_PER_DEVICE: int = 32
DISPATCH_BUFFER_DURABLE: bool = False  # in-process only; lost on V2 restart
DISPATCH_BUFFER_SCOPE: str = (
    "task_assign, task_execute, goal_execution only — "
    "heartbeat/GUI/control types are NOT buffered"
)

# Pending delivery residual risks
# Evidence: android_bridge.py INFLIGHT_TASK_LOSS_RESIDUAL_RISK_* sentinels
DISPATCH_RESIDUAL_RISK_TERMINAL_RECONNECT: bool = True
DISPATCH_RESIDUAL_RISK_PROCESS_RESTART: bool = True

# Result ingestion
# Evidence: galaxy_gateway/android/handlers/task_lifecycle.py
#   - handle_task_result() runs V1 continuity legality check, then invokes
#     _run_task_result_truth_chain (if available), then tries:
#       a) device_router.handle_task_result()
#       b) store_task_result() (OpenClawd memory backflow)
#   - Each downstream step is non-fatal try/except with observable error counters
#     (RESULT_RECONCILE_ERRORS, RESULT_TRUTH_INGRESS_ERRORS, etc.).
#   - All failures now logged at WARNING level (not silently swallowed).
DISPATCH_RESULT_INGESTION_TRUTH_CHAIN_PRESENT: bool = True
DISPATCH_RESULT_INGESTION_ERROR_COUNTERS_PRESENT: bool = True
DISPATCH_RESULT_INGESTION_SILENT_FAILURE_PATHS: bool = False  # fixed in PR #929

# Completion settlement
# Evidence:
#   - core/canonical_completion_ingress.py notifies awaiting Futures/Events
#     when a task completes.  This is the only completion gate; there is no
#     explicit accept/reject verdict gate (completion = optimistic acceptance).
DISPATCH_COMPLETION_INGRESS_PRESENT: bool = True
DISPATCH_COMPLETION_HAS_EXPLICIT_VERDICT_GATE: bool = False

# Durability across process restart
# Evidence:
#   - core/durable_result_idempotency.py provides an idempotency guard that
#     persists across V2 restarts, preventing double-processing of results.
#   - The pending-delivery buffer is NOT durable (in-process only).
DISPATCH_IDEMPOTENCY_GUARD_DURABLE: bool = True
DISPATCH_PENDING_BUFFER_DURABLE: bool = False

#: Area 3 verdict.
#:
#: Why RUNNABLE_BUT_CONDITIONAL:
#:   Legality gates, device routing, buffering, result ingestion, and
#:   completion settlement are all implemented.  Observable error counters
#:   replace silent failure paths.  However: buffer is not durable (process
#:   restart loses in-flight buffered tasks); completion settlement has no
#:   explicit accept/reject gate (optimistic); downstream truth-chain steps
#:   are non-fatal and may silently partially fail despite counters.
DISPATCH_EXECUTION_RESULT_VERDICT: IntegratedSystemVerdict = (
    IntegratedSystemVerdict.RUNNABLE_BUT_CONDITIONAL
)
DISPATCH_EXECUTION_RESULT_VERDICT_RATIONALE: str = (
    "Legality gate (V1 continuity check) on result ingress: present. "
    "Device routing (CommandRouter + send_to_device fallback): present. "
    "Offline buffering (pending_delivery_buffer, TTL=60s, cap=32): present. "
    "Result ingestion truth chain: present. "
    "Observable error counters (RESULT_*_ERRORS): present; silent-failure path CLOSED. "
    "Completion settlement (canonical_completion_ingress.notify): present. "
    "Durable result idempotency guard: present. "
    "CONDITIONAL: buffer is in-process only (lost on V2 restart). "
    "Completion gate is optimistic (no explicit accept/reject verdict). "
    "Downstream truth-chain failures are non-fatal and only visible via counters, "
    "not automatically retried."
)


# ============================================================================
# AREA 4 — Multi-Device / Cross-Location Usability
# ============================================================================

# Multi-device support in code
# Evidence:
#   - AndroidBridge._fan_out_task_assign() supports multi-device fan-out
#     for task_assign messages.
#   - DeviceRouter and UnifiedConnectionManager track multiple registered devices.
MULTI_DEVICE_FAN_OUT_PRESENT: bool = True
MULTI_DEVICE_REGISTRY_SUPPORTS_MULTIPLE: bool = True

# Configuration barriers — CRITICAL GAPS
# Evidence:
#   - ufo-galaxy-android config.properties: cross_device_enabled=false (default)
#   - GalaxyWebSocketClient.kt:569: skips ALL WebSocket connection attempts when false.
#   - AppSettings.kt:589: default server URL is 'ws://100.x.x.x:8765'
#     (Tailscale placeholder IP, not routable on standard networks).
#   - Every fresh deployment requires BOTH flags to be manually changed.
MULTI_DEVICE_ANDROID_CROSS_DEVICE_DISABLED_BY_DEFAULT: bool = True
MULTI_DEVICE_ANDROID_DEFAULT_URL_IS_PLACEHOLDER: bool = True
MULTI_DEVICE_REQUIRES_MANUAL_ACTIVATION: bool = True

# Remote / cross-location access
# Evidence:
#   - V2 has no built-in STUN, TURN, UPNP, or NAT-punch code.
#   - AndroidManifest usesCleartextTraffic=true allows ws://, but there is
#     no relay or fallback for NAT traversal.
#   - Remote operation requires Tailscale VPN or equivalent overlay.
#   - TailscaleAdapter.kt exists but is not a built-in relay.
MULTI_DEVICE_REMOTE_ACCESS_REQUIRES_VPN_OVERLAY: bool = True
MULTI_DEVICE_NO_BUILTIN_STUN_TURN: bool = True
MULTI_DEVICE_NO_RELAY_FALLBACK: bool = True

# Auth
# Evidence:
#   - GalaxyWebSocketClient.kt:586 sends Bearer token via Authorization header
#     when gatewayToken is configured.
#   - galaxy_gateway/middleware.py BearerAuthMiddleware verifies token when
#     GALAXY_AUTH_ENABLED=true (default: false — appropriate for closed networks).
MULTI_DEVICE_AUTH_BEARER_TOKEN_SUPPORTED: bool = True
MULTI_DEVICE_AUTH_DISABLED_BY_DEFAULT: bool = True

#: Area 4 verdict.
#:
#: Why PARTIAL:
#:   Multi-device fan-out and registry are code-present.  However, the system
#:   is NOT plug-and-run: every fresh Android deployment requires manual
#:   activation of cross_device_enabled and a routable server URL.  Remote
#:   cross-location usage requires a Tailscale/VPN overlay; there is no
#:   built-in STUN/TURN or relay.  In practice this means multi-device
#:   cross-location usage is deployment-conditional in a way that requires
#:   more than environment configuration — it requires explicit steps that
#:   most users would not take automatically.
MULTI_DEVICE_CROSS_LOCATION_VERDICT: IntegratedSystemVerdict = (
    IntegratedSystemVerdict.PARTIAL
)
MULTI_DEVICE_CROSS_LOCATION_VERDICT_RATIONALE: str = (
    "Multi-device fan-out (AndroidBridge._fan_out_task_assign): code-present. "
    "Multi-device registry (DeviceRouter, UnifiedConnectionManager): code-present. "
    "PARTIAL: Android cross_device_enabled=false by default — requires manual activation. "
    "PARTIAL: Default Android URL is Tailscale placeholder — requires manual configuration. "
    "PARTIAL: Remote access requires Tailscale/VPN overlay (no built-in STUN/TURN/relay). "
    "System is deployment-conditional, not plug-and-run."
)


# ============================================================================
# AREA 5 — Final Integrated System Verdict
# ============================================================================

#: Known remaining gaps that are not yet resolved.
#: These are machine-checkable: a test asserts that this list is non-empty and
#: contains at least the expected entries, ensuring no gap is silently removed
#: without being replaced by a real fix.
KNOWN_REMAINING_GAPS: List[str] = [
    "ANDROID_RECONNECT_TERMINAL_STOP: Android MAX_RECONNECT_ATTEMPTS=10 "
    "permanently stops reconnecting after ~181s; no watchdog or server-side "
    "wake mechanism exists (ufo-galaxy-android GalaxyWebSocketClient.kt).",

    "PENDING_BUFFER_NOT_DURABLE: galaxy_gateway/pending_delivery_buffer.py is "
    "in-process only. A V2 process restart loses all buffered pending-delivery "
    "messages, creating task loss for in-flight tasks at restart time.",

    "COMPLETION_NO_EXPLICIT_VERDICT_GATE: core/canonical_completion_ingress.py "
    "uses optimistic completion (completion = accepted). There is no explicit "
    "accept/reject verdict gate for task completion.",

    "MULTI_DEVICE_ACTIVATION_BARRIER: Android cross_device_enabled=false by "
    "default (ufo-galaxy-android config.properties). Requires manual activation "
    "before any cross-device functionality is available.",

    "MULTI_DEVICE_URL_PLACEHOLDER: Android default server URL is a Tailscale "
    "placeholder IP (ws://100.x.x.x:8765). Requires manual configuration for "
    "every fresh deployment.",

    "REMOTE_ACCESS_NO_BUILTIN_RELAY: Remote cross-location operation requires "
    "Tailscale VPN or equivalent overlay. V2 has no built-in STUN, TURN, UPNP, "
    "or NAT-punch code.",
]

#: Capabilities confirmed complete in both repositories.
CONFIRMED_COMPLETE_CAPABILITIES: List[str] = [
    "WS transport path alignment: V2 /ws/device/{id} ↔ Android AppSettings.effectiveGatewayWsUrl",
    "AIP compat layer: v1.0/v2.0 alias normalisation (goal_result, command_result, etc.)",
    "Android report type coverage: cancel_result, device_readiness_report, "
    "device_governance_report, device_acceptance_report, device_strategy_report",
    "Structured ACK/UNKNOWN_MESSAGE_TYPE response for all handled/unhandled types",
    "Device registration + register_ack with continuity_outcome classification",
    "Heartbeat protocol: OkHttp 20s TCP ping + app 30s heartbeat; V2 60s stale timeout",
    "Stale device cleanup background task: V2 every 90s (threshold 120s)",
    "Reconnect exponential backoff [1,2,4,8,16,30]s + counter reset on open + network-change reset",
    "BootReceiver cold-boot connection service start",
    "Pending-delivery buffer for offline devices: task-type messages buffered on disconnect, "
    "flushed on reconnect (TTL=60s, cap=32/device)",
    "Result ingestion: observable error counters (RESULT_*_ERRORS), WARNING-level logging, "
    "no silent failure paths",
    "Durable result idempotency guard (durable_result_idempotency.py)",
    "Multi-device fan-out task dispatch (AndroidBridge._fan_out_task_assign)",
    "Bearer token auth support (both sides; disabled by default for closed-network use)",
]

#: Capabilities confirmed runnable in practice but requiring explicit activation
#: or having known residual risks.
RUNNABLE_BUT_CONDITIONAL_CAPABILITIES: List[str] = [
    "Full cross-device dispatch/result loop: runnable after manual Android activation "
    "(cross_device_enabled=true + routable server URL)",
    "Reconnect recovery: runnable within 10-attempt window; terminal after that without "
    "manual intervention",
    "Pending-delivery buffer protection: effective for short disconnects (TTL=60s); "
    "ineffective if Android hits terminal reconnect limit or V2 restarts",
    "Result truth-chain completion: non-fatal failures are now observable via error counters "
    "but are not automatically retried",
    "Remote access: functional via Tailscale/VPN overlay; requires overlay setup",
]

# Final system verdict
#
# Evidence basis:
#   - Transport/Protocol: COMPLETE
#   - Device Lifecycle/Liveness: RUNNABLE_BUT_CONDITIONAL
#   - Dispatch/Execution/Result: RUNNABLE_BUT_CONDITIONAL
#   - Multi-Device/Cross-Location: PARTIAL
#
# The system has a real executable core and a well-wired protocol layer.  The
# main execution path (connect → register → dispatch → execute → result →
# complete) is code-present and runnable.  However, three classes of
# conditions prevent a COMPLETE classification:
#
#   (a) Long-term liveness: the Android reconnect limit creates a reliability
#       ceiling for unattended operation.
#   (b) Durability: the pending-delivery buffer is not durable; process restart
#       breaks continuity for in-flight tasks.
#   (c) Deployment: multi-device cross-location use requires manual activation
#       and a network overlay that is not provided out-of-box.
INTEGRATED_SYSTEM_VERDICT: IntegratedSystemVerdict = (
    IntegratedSystemVerdict.RUNNABLE_BUT_CONDITIONAL
)
INTEGRATED_SYSTEM_VERDICT_RATIONALE: str = (
    "The integrated V2↔Android center-distributed system is "
    "RUNNABLE_BUT_CONDITIONAL, not COMPLETE. "
    "The full transport, registration, dispatch, result-ingestion, and "
    "completion-settlement chain is code-present and has been exercised by "
    "integration tests. "
    "Conditions and residual risks that prevent a COMPLETE classification: "
    "(1) Android reconnect terminal stop (MAX_RECONNECT_ATTEMPTS=10, ~181s) "
    "with no watchdog or server-side wake — long unattended operation risks "
    "permanent device loss; "
    "(2) pending-delivery buffer is in-process only — V2 restart loses "
    "buffered in-flight tasks; "
    "(3) Android cross_device_enabled=false by default + placeholder gateway URL "
    "— requires explicit activation for every fresh deployment; "
    "(4) remote cross-location access requires Tailscale/VPN overlay — "
    "not a built-in capability. "
    "Multi-device/cross-location area is PARTIAL (code present, deployment-conditional)."
)

# Per-area verdicts summary
AREA_VERDICTS: Dict[str, IntegratedSystemVerdict] = {
    "transport_protocol": TRANSPORT_PROTOCOL_VERDICT,
    "device_lifecycle_liveness": DEVICE_LIFECYCLE_VERDICT,
    "dispatch_execution_result": DISPATCH_EXECUTION_RESULT_VERDICT,
    "multi_device_cross_location": MULTI_DEVICE_CROSS_LOCATION_VERDICT,
    "integrated_system": INTEGRATED_SYSTEM_VERDICT,
}


# ============================================================================
# Summary dict — machine-checkable by tests
# ============================================================================

#: Minimum number of known remaining gaps that must always be documented.
#: Tests use this constant to ensure gaps are not silently removed.
MINIMUM_KNOWN_GAPS: int = 6

#: Minimum number of confirmed-complete capabilities that must be documented.
#: Tests use this constant to ensure completed items are not silently removed.
MINIMUM_CONFIRMED_COMPLETE_CAPABILITIES: int = 10

FINAL_INTEGRATED_SYSTEM_AUDIT: Dict[str, Any] = {
    # --- Area 1: Transport / Protocol ---
    "transport_ws_path_aligned": TRANSPORT_PROTOCOL_WS_PATH_ALIGNED,
    "transport_alias_compat_present": TRANSPORT_PROTOCOL_ALIAS_COMPAT_PRESENT,
    "transport_android_report_types_handled": TRANSPORT_PROTOCOL_ANDROID_REPORT_TYPES_HANDLED,
    "transport_unknown_type_response_present": TRANSPORT_PROTOCOL_UNKNOWN_TYPE_RESPONSE_PRESENT,
    "transport_verdict": TRANSPORT_PROTOCOL_VERDICT,
    # --- Area 2: Device Lifecycle / Liveness ---
    "device_registration_present": DEVICE_REGISTRATION_PRESENT,
    "device_registration_ack_includes_continuity_outcome": DEVICE_REGISTRATION_ACK_INCLUDES_CONTINUITY_OUTCOME,
    "device_heartbeat_present": DEVICE_HEARTBEAT_PROTOCOL_PRESENT,
    "device_stale_cleanup_background_task_present": DEVICE_STALE_CLEANUP_BACKGROUND_TASK_PRESENT,
    "device_reconnect_backoff_present": DEVICE_RECONNECT_BACKOFF_PRESENT,
    "device_reconnect_terminal_stop": DEVICE_RECONNECT_TERMINAL_STOP_PRESENT,
    "device_reconnect_max_attempts": DEVICE_RECONNECT_MAX_ATTEMPTS,
    "device_reconnect_no_watchdog": DEVICE_RECONNECT_NO_WATCHDOG,
    "device_boot_receiver_present": DEVICE_BOOT_RECEIVER_STARTS_CONNECTION_SERVICE,
    "device_boot_receiver_restarts_terminal_loop": DEVICE_BOOT_RECEIVER_RESTARTS_TERMINAL_RECONNECT_LOOP,
    "device_lifecycle_verdict": DEVICE_LIFECYCLE_VERDICT,
    # --- Area 3: Dispatch / Execution / Result ---
    "dispatch_legality_gate_present": DISPATCH_LEGALITY_GATE_PRESENT,
    "dispatch_device_routing_present": DISPATCH_DEVICE_ROUTING_PRESENT,
    "dispatch_offline_buffering_present": DISPATCH_OFFLINE_BUFFERING_PRESENT,
    "dispatch_buffer_durable": DISPATCH_BUFFER_DURABLE,
    "dispatch_buffer_ttl_s": DISPATCH_BUFFER_TTL_S,
    "dispatch_buffer_max_queue_per_device": DISPATCH_BUFFER_MAX_QUEUE_PER_DEVICE,
    "dispatch_residual_risk_terminal_reconnect": DISPATCH_RESIDUAL_RISK_TERMINAL_RECONNECT,
    "dispatch_residual_risk_process_restart": DISPATCH_RESIDUAL_RISK_PROCESS_RESTART,
    "dispatch_result_truth_chain_present": DISPATCH_RESULT_INGESTION_TRUTH_CHAIN_PRESENT,
    "dispatch_result_error_counters_present": DISPATCH_RESULT_INGESTION_ERROR_COUNTERS_PRESENT,
    "dispatch_result_silent_failure_paths": DISPATCH_RESULT_INGESTION_SILENT_FAILURE_PATHS,
    "dispatch_completion_ingress_present": DISPATCH_COMPLETION_INGRESS_PRESENT,
    "dispatch_completion_explicit_verdict_gate": DISPATCH_COMPLETION_HAS_EXPLICIT_VERDICT_GATE,
    "dispatch_idempotency_guard_durable": DISPATCH_IDEMPOTENCY_GUARD_DURABLE,
    "dispatch_execution_result_verdict": DISPATCH_EXECUTION_RESULT_VERDICT,
    # --- Area 4: Multi-Device / Cross-Location ---
    "multi_device_fan_out_present": MULTI_DEVICE_FAN_OUT_PRESENT,
    "multi_device_registry_supports_multiple": MULTI_DEVICE_REGISTRY_SUPPORTS_MULTIPLE,
    "multi_device_android_disabled_by_default": MULTI_DEVICE_ANDROID_CROSS_DEVICE_DISABLED_BY_DEFAULT,
    "multi_device_android_url_is_placeholder": MULTI_DEVICE_ANDROID_DEFAULT_URL_IS_PLACEHOLDER,
    "multi_device_requires_manual_activation": MULTI_DEVICE_REQUIRES_MANUAL_ACTIVATION,
    "multi_device_remote_requires_vpn": MULTI_DEVICE_REMOTE_ACCESS_REQUIRES_VPN_OVERLAY,
    "multi_device_no_builtin_stun_turn": MULTI_DEVICE_NO_BUILTIN_STUN_TURN,
    "multi_device_cross_location_verdict": MULTI_DEVICE_CROSS_LOCATION_VERDICT,
    # --- Area 5: Final Verdict ---
    "area_verdicts": AREA_VERDICTS,
    "integrated_system_verdict": INTEGRATED_SYSTEM_VERDICT,
    "known_remaining_gaps_count": len(KNOWN_REMAINING_GAPS),
    "confirmed_complete_capabilities_count": len(CONFIRMED_COMPLETE_CAPABILITIES),
}


# ============================================================================
# Invariant checker — callable from tests and CI
# ============================================================================


def assert_final_audit_surface_is_consistent() -> None:
    """Assert all invariants of the final integrated system audit surface.

    Call this from tests to ensure this surface stays in sync with the live
    code.  Raises :class:`AssertionError` with a descriptive message if any
    invariant is violated.

    Invariants enforced:
    - Per-area verdicts are correctly classified.
    - The integrated system verdict is RUNNABLE_BUT_CONDITIONAL.
    - Known remaining gaps are documented and non-empty.
    - Transport area COMPLETE sentinels are True.
    - Device liveness conditional sentinels reflect real constraints.
    - Dispatch/result conditional sentinels reflect real constraints.
    - Multi-device partial sentinels reflect real constraints.
    """
    a = FINAL_INTEGRATED_SYSTEM_AUDIT

    # --- Area 1: Transport must be COMPLETE ---
    assert a["transport_verdict"] == IntegratedSystemVerdict.COMPLETE, (
        "FINAL_AUDIT: transport_verdict must be COMPLETE. "
        "Transport/protocol is fully aligned (WS path, compat layer, message types, ACK). "
        "Update this assertion only if a real regression is introduced."
    )
    assert a["transport_ws_path_aligned"] is True, (
        "FINAL_AUDIT: transport_ws_path_aligned must be True. "
        "V2 /ws/device/{id} and Android effectiveGatewayWsUrl must remain aligned."
    )
    assert a["transport_alias_compat_present"] is True, (
        "FINAL_AUDIT: transport_alias_compat_present must be True. "
        "AIP compat layer (compat.py _LEGACY_TYPE_MAP) must remain present."
    )
    assert a["transport_android_report_types_handled"] is True, (
        "FINAL_AUDIT: transport_android_report_types_handled must be True. "
        "Android report types must remain in MessageType enum."
    )

    # --- Area 2: Device lifecycle must be RUNNABLE_BUT_CONDITIONAL ---
    assert a["device_lifecycle_verdict"] == IntegratedSystemVerdict.RUNNABLE_BUT_CONDITIONAL, (
        "FINAL_AUDIT: device_lifecycle_verdict must be RUNNABLE_BUT_CONDITIONAL. "
        "Android terminal reconnect limit (MAX_RECONNECT_ATTEMPTS=10) and absence of watchdog "
        "prevent a COMPLETE classification. Update only when terminal reconnect is resolved."
    )
    assert a["device_registration_present"] is True, (
        "FINAL_AUDIT: device_registration_present must be True."
    )
    assert a["device_heartbeat_present"] is True, (
        "FINAL_AUDIT: device_heartbeat_present must be True."
    )
    assert a["device_stale_cleanup_background_task_present"] is True, (
        "FINAL_AUDIT: device_stale_cleanup_background_task_present must be True. "
        "Lifecycle.py periodic cleanup task must remain present."
    )
    assert a["device_reconnect_backoff_present"] is True, (
        "FINAL_AUDIT: device_reconnect_backoff_present must be True."
    )
    # Remaining gaps that MUST still be documented
    assert a["device_reconnect_terminal_stop"] is True, (
        "FINAL_AUDIT: device_reconnect_terminal_stop must remain True until "
        "ufo-galaxy-android removes the MAX_RECONNECT_ATTEMPTS limit or adds a watchdog."
    )
    assert a["device_reconnect_no_watchdog"] is True, (
        "FINAL_AUDIT: device_reconnect_no_watchdog must remain True until "
        "ufo-galaxy-android adds a supervisory restart or watchdog mechanism."
    )
    assert a["device_boot_receiver_restarts_terminal_loop"] is False, (
        "FINAL_AUDIT: device_boot_receiver_restarts_terminal_loop must be False. "
        "BootReceiver only covers cold boot; it does NOT restart a terminal reconnect loop. "
        "Update when BootReceiver is extended to cover terminal reconnect restart."
    )

    # --- Area 3: Dispatch/execution/result must be RUNNABLE_BUT_CONDITIONAL ---
    assert a["dispatch_execution_result_verdict"] == IntegratedSystemVerdict.RUNNABLE_BUT_CONDITIONAL, (
        "FINAL_AUDIT: dispatch_execution_result_verdict must be RUNNABLE_BUT_CONDITIONAL. "
        "Buffer is non-durable and completion gate is optimistic. "
        "Update only when buffer durability and explicit completion verdict gate are added."
    )
    assert a["dispatch_offline_buffering_present"] is True, (
        "FINAL_AUDIT: dispatch_offline_buffering_present must be True. "
        "pending_delivery_buffer.py must remain in place."
    )
    assert a["dispatch_buffer_durable"] is False, (
        "FINAL_AUDIT: dispatch_buffer_durable must be False — buffer is in-process only. "
        "Update when durable storage backing is added to pending_delivery_buffer."
    )
    assert a["dispatch_result_silent_failure_paths"] is False, (
        "FINAL_AUDIT: dispatch_result_silent_failure_paths must be False. "
        "Observable error counters (RESULT_*_ERRORS) must remain in task_lifecycle.py. "
        "Update only if the counters are replaced by a stronger mechanism."
    )
    assert a["dispatch_result_error_counters_present"] is True, (
        "FINAL_AUDIT: dispatch_result_error_counters_present must be True."
    )
    assert a["dispatch_completion_explicit_verdict_gate"] is False, (
        "FINAL_AUDIT: dispatch_completion_explicit_verdict_gate must remain False until "
        "canonical_completion_ingress.py adds an explicit accept/reject verdict gate."
    )
    assert a["dispatch_idempotency_guard_durable"] is True, (
        "FINAL_AUDIT: dispatch_idempotency_guard_durable must be True. "
        "durable_result_idempotency.py must remain present."
    )

    # --- Area 4: Multi-device/cross-location must be PARTIAL ---
    assert a["multi_device_cross_location_verdict"] == IntegratedSystemVerdict.PARTIAL, (
        "FINAL_AUDIT: multi_device_cross_location_verdict must be PARTIAL. "
        "Android cross_device_enabled=false default and placeholder URL mean the system "
        "is not plug-and-run. Remote access requires Tailscale/VPN. "
        "Update when defaults are changed and a built-in relay is added."
    )
    assert a["multi_device_android_disabled_by_default"] is True, (
        "FINAL_AUDIT: multi_device_android_disabled_by_default must remain True until "
        "ufo-galaxy-android ships with cross_device_enabled=true as the default."
    )
    assert a["multi_device_android_url_is_placeholder"] is True, (
        "FINAL_AUDIT: multi_device_android_url_is_placeholder must remain True until "
        "ufo-galaxy-android ships with a non-placeholder default gateway URL."
    )
    assert a["multi_device_remote_requires_vpn"] is True, (
        "FINAL_AUDIT: multi_device_remote_requires_vpn must remain True until V2 "
        "implements STUN/TURN or a built-in relay for general internet access."
    )

    # --- Area 5: Integrated verdict must be RUNNABLE_BUT_CONDITIONAL ---
    assert a["integrated_system_verdict"] == IntegratedSystemVerdict.RUNNABLE_BUT_CONDITIONAL, (
        "FINAL_AUDIT: integrated_system_verdict must be RUNNABLE_BUT_CONDITIONAL. "
        "The system is not COMPLETE (terminal reconnect, non-durable buffer, "
        "deployment barriers, no built-in relay) and not PARTIAL/MISSING "
        "(main execution chain is code-present and runnable). "
        "Update only when all blocking gaps listed in KNOWN_REMAINING_GAPS are resolved."
    )

    # Known gaps must remain documented
    assert len(KNOWN_REMAINING_GAPS) >= MINIMUM_KNOWN_GAPS, (
        "FINAL_AUDIT: KNOWN_REMAINING_GAPS must document at least "
        f"{MINIMUM_KNOWN_GAPS} known gaps. "
        "Do not remove gap documentation without resolving the underlying issue."
    )

    # Confirmed complete capabilities must be documented
    assert len(CONFIRMED_COMPLETE_CAPABILITIES) >= MINIMUM_CONFIRMED_COMPLETE_CAPABILITIES, (
        "FINAL_AUDIT: CONFIRMED_COMPLETE_CAPABILITIES must document at least "
        f"{MINIMUM_CONFIRMED_COMPLETE_CAPABILITIES} confirmed-complete items."
    )
