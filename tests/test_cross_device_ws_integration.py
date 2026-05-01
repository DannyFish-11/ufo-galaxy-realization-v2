"""
tests/test_cross_device_ws_integration.py
==========================================
Joint audit: ufo-galaxy-realization-v2 × ufo-galaxy-android
Cross-device integration reality tests — unit-level (no live WebSocket).

PURPOSE
-------
These tests verify the code-level fixes made in the joint audit PR:
  1. AIP compat layer maps 'goal_result' for v1.0 clients.
  2. Previously-missing Android report types are in MessageType enum.
  3. The integration reality sentinel module stays in sync with code.

WS end-to-end tests (register → heartbeat → task_result) live in:
  tests/integration/test_cross_device_ws_e2e.py

SCOPE
-----
These are pure unit tests — no live WebSocket, no FastAPI TestClient.
"""

from __future__ import annotations

import pytest


# ===========================================================================
# 1. AIP v3 compat layer: goal_result is mapped correctly for v1 clients
# ===========================================================================


class TestCompatLayerGoalResultMapping:
    """CLOSED: _LEGACY_TYPE_MAP in compat.py maps 'goal_result' for v1.0 clients."""

    def test_goal_result_in_legacy_type_map(self) -> None:
        """CLOSED: 'goal_result' is in _LEGACY_TYPE_MAP and maps to GOAL_EXECUTION_RESULT."""
        from galaxy_gateway.protocol.compat import _LEGACY_TYPE_MAP
        from galaxy_gateway.protocol.aip_v3 import MessageType

        assert "goal_result" in _LEGACY_TYPE_MAP, (
            "CLOSED: 'goal_result' must be in _LEGACY_TYPE_MAP so v1.0 clients "
            "that emit 'goal_result' are normalised to GOAL_EXECUTION_RESULT. "
            "This was added in the joint audit PR."
        )
        assert _LEGACY_TYPE_MAP["goal_result"] == MessageType.GOAL_EXECUTION_RESULT, (
            "CLOSED: _LEGACY_TYPE_MAP['goal_result'] must map to MessageType.GOAL_EXECUTION_RESULT."
        )

    def test_android_report_types_in_message_type_enum(self) -> None:
        """CLOSED: all previously-missing Android report types are in MessageType enum."""
        from galaxy_gateway.protocol.aip_v3 import MessageType

        expected = [
            "cancel_result",
            "device_readiness_report",
            "device_governance_report",
            "device_acceptance_report",
            "device_strategy_report",
        ]
        for type_str in expected:
            try:
                mt = MessageType(type_str)
                assert mt.value == type_str, (
                    f"CLOSED: MessageType('{type_str}').value must be '{type_str}'; "
                    f"got {mt.value!r}"
                )
            except ValueError:
                pytest.fail(
                    f"CLOSED: MessageType('{type_str}') raises ValueError — "
                    f"this type must be added to the MessageType enum.  "
                    f"Prior to the joint audit PR this caused UNKNOWN_MESSAGE_TYPE errors."
                )

    def test_goal_result_enum_entry_exists(self) -> None:
        """CLOSED: MessageType.GOAL_RESULT exists as a first-class enum entry."""
        from galaxy_gateway.protocol.aip_v3 import MessageType

        try:
            mt = MessageType("goal_result")
            assert mt == MessageType.GOAL_RESULT
        except (ValueError, AttributeError):
            pytest.fail("CLOSED: MessageType.GOAL_RESULT must exist as an enum entry.")


# ===========================================================================
# 2. Android bridge dispatch table: report types are registered
# ===========================================================================


class TestAndroidBridgeHandlerRegistration:
    """CLOSED: Android report types are registered in the dispatch table."""

    def test_android_report_types_have_handlers(self) -> None:
        """CLOSED: All Android report types have handlers (not unregistered/unknown)."""
        from galaxy_gateway.android_bridge import AndroidBridge
        from galaxy_gateway.protocol.aip_v3 import MessageType

        bridge = AndroidBridge()
        report_types = [
            MessageType.CANCEL_RESULT,
            MessageType.DEVICE_READINESS_REPORT,
            MessageType.DEVICE_GOVERNANCE_REPORT,
            MessageType.DEVICE_ACCEPTANCE_REPORT,
            MessageType.DEVICE_STRATEGY_REPORT,
        ]
        for mt in report_types:
            assert mt in bridge._message_handlers, (
                f"CLOSED: {mt.value!r} must have a registered handler in AndroidBridge. "
                f"Prior to the joint audit PR these types were absent from MessageType "
                f"and caused UNKNOWN_MESSAGE_TYPE errors."
            )

    def test_goal_result_handler_is_registered(self) -> None:
        """CLOSED: GOAL_RESULT is registered in the bridge dispatch table."""
        from galaxy_gateway.android_bridge import AndroidBridge
        from galaxy_gateway.protocol.aip_v3 import MessageType

        bridge = AndroidBridge()
        assert MessageType.GOAL_RESULT in bridge._message_handlers, (
            "CLOSED: MessageType.GOAL_RESULT must have a registered handler."
        )


# ===========================================================================
# 3. Integration reality sentinel (machine-checkable)
# ===========================================================================


class TestCrossDeviceIntegrationReality:
    """Verify the cross_device_integration_reality module stays in sync."""

    def test_known_gaps_are_documented(self) -> None:
        """CLOSED: integration reality sentinels are consistent with current code."""
        from core.cross_device_integration_reality import assert_known_gaps_are_documented
        assert_known_gaps_are_documented()

    def test_reality_dict_has_required_keys(self) -> None:
        """CLOSED: integration reality dict contains all expected keys."""
        from core.cross_device_integration_reality import CROSS_DEVICE_INTEGRATION_REALITY
        required_keys = [
            "ws_transport_protocol_aligned",
            "android_cross_device_disabled_by_default",
            "android_default_url_is_placeholder",
            "remote_access_requires_tailscale_or_vpnish",
            "goal_result_alias_handled",
            "android_governance_report_types_handled",
            "android_report_types_now_handled",
            "v2_stale_cleanup_background_task_present",
            "inflight_task_loss_on_disconnect",
            "result_ingestion_has_silent_failure_paths",
            "android_reconnect_stops_permanently_at_limit",
            "e2e_live_ws_tests_present",
        ]
        missing = [k for k in required_keys if k not in CROSS_DEVICE_INTEGRATION_REALITY]
        assert not missing, (
            f"CLOSED: CROSS_DEVICE_INTEGRATION_REALITY is missing required keys: {missing}"
        )

    def test_ws_transport_aligned(self) -> None:
        """CLOSED: WS transport protocol is confirmed aligned between repos."""
        from core.cross_device_integration_reality import WS_TRANSPORT_PROTOCOL_ALIGNED
        assert WS_TRANSPORT_PROTOCOL_ALIGNED is True

    def test_audit_fixes_present(self) -> None:
        """CLOSED: all audit-PR fixes are confirmed present in the reality surface."""
        from core.cross_device_integration_reality import (
            GOAL_RESULT_ALIAS_HANDLED,
            ANDROID_GOVERNANCE_REPORT_TYPES_HANDLED,
            V2_STALE_CLEANUP_BACKGROUND_TASK_PRESENT,
            E2E_LIVE_WS_TESTS_PRESENT,
        )
        assert GOAL_RESULT_ALIAS_HANDLED is True
        assert ANDROID_GOVERNANCE_REPORT_TYPES_HANDLED is True
        assert V2_STALE_CLEANUP_BACKGROUND_TASK_PRESENT is True
        assert E2E_LIVE_WS_TESTS_PRESENT is True

    def test_known_gaps_still_documented(self) -> None:
        """GAP_EXPOSED: known remaining gaps are explicitly documented (not silently removed).

        Two gaps from the previous audit have now been fixed:
        - INFLIGHT_TASK_LOSS_ON_DISCONNECT: Fixed by pending-delivery buffer.
        - RESULT_INGESTION_HAS_SILENT_FAILURE_PATHS: Fixed by observable error counters.

        Remaining gaps (Android-side issues outside V2's control) must still be True.
        """
        from core.cross_device_integration_reality import (
            ANDROID_CROSS_DEVICE_DISABLED_BY_DEFAULT,
            ANDROID_DEFAULT_URL_IS_PLACEHOLDER,
            REMOTE_ACCESS_REQUIRES_TAILSCALE_OR_VPNISH,
            INFLIGHT_TASK_LOSS_ON_DISCONNECT,
            RESULT_INGESTION_HAS_SILENT_FAILURE_PATHS,
            ANDROID_RECONNECT_STOPS_PERMANENTLY_AT_LIMIT,
            INFLIGHT_TASK_LOSS_RESIDUAL_RISK_ANDROID_TERMINAL_RECONNECT,
            INFLIGHT_TASK_LOSS_RESIDUAL_RISK_PROCESS_RESTART,
        )
        # Still-open Android-side gaps (not fixable in V2 alone)
        assert ANDROID_CROSS_DEVICE_DISABLED_BY_DEFAULT is True, (
            "GAP_EXPOSED: Android cross_device_enabled=false default is still a real gap."
        )
        assert ANDROID_DEFAULT_URL_IS_PLACEHOLDER is True, (
            "GAP_EXPOSED: Android default URL placeholder is still a real gap."
        )
        assert REMOTE_ACCESS_REQUIRES_TAILSCALE_OR_VPNISH is True, (
            "GAP_EXPOSED: Remote access requires Tailscale/VPN — still a real constraint."
        )
        assert ANDROID_RECONNECT_STOPS_PERMANENTLY_AT_LIMIT is True, (
            "GAP_EXPOSED: Android reconnect stops permanently at 10 attempts — still a real gap."
        )
        # V2-fixed gaps — sentinels must now be False
        assert INFLIGHT_TASK_LOSS_ON_DISCONNECT is False, (
            "FIXED: pending-delivery buffer was added. "
            "If this fails, the buffer was removed — update the sentinel back to True."
        )
        assert RESULT_INGESTION_HAS_SILENT_FAILURE_PATHS is False, (
            "FIXED: observable error counters were added to task_lifecycle.py. "
            "If this fails, the counters were removed — update the sentinel back to True."
        )
        # Residual risks still present even after fix
        assert INFLIGHT_TASK_LOSS_RESIDUAL_RISK_ANDROID_TERMINAL_RECONNECT is True, (
            "RESIDUAL: in-flight loss still possible if Android permanently stops reconnecting."
        )
        assert INFLIGHT_TASK_LOSS_RESIDUAL_RISK_PROCESS_RESTART is True, (
            "RESIDUAL: pending buffer is in-process only; V2 restarts still lose buffered msgs."
        )
