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
        from galaxy_gateway.protocol.aip_v3 import MessageType
        from galaxy_gateway.protocol.compat import _LEGACY_TYPE_MAP

        assert "goal_result" in _LEGACY_TYPE_MAP, (
            "CLOSED: 'goal_result' must be in _LEGACY_TYPE_MAP so v1.0 clients "
            "that emit 'goal_result' are normalised to GOAL_EXECUTION_RESULT. "
            "This was added in the joint audit PR."
        )
        assert (
            _LEGACY_TYPE_MAP["goal_result"] == MessageType.GOAL_EXECUTION_RESULT
        ), "CLOSED: _LEGACY_TYPE_MAP['goal_result'] must map to MessageType.GOAL_EXECUTION_RESULT."

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
                    f"CLOSED: MessageType('{type_str}').value must be '{type_str}'; " f"got {mt.value!r}"
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
        assert (
            MessageType.GOAL_RESULT in bridge._message_handlers
        ), "CLOSED: MessageType.GOAL_RESULT must have a registered handler."


# ===========================================================================
# 3. Integration reality sentinel (machine-checkable)
# ===========================================================================


# 此处原有的用例引用了本批删除的零引用模块（审计报告产物 / 纯声明层 / 已被取代的
# 平行实现）。模块不存在后这些断言失去对象，随之移除；同文件其余用例保持不变。
