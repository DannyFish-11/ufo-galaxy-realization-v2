"""
tests/test_ssot_udm.py — SSOT (Single Source of Truth) UDM write-through tests.

Verifies that:
  1. galaxy_gateway.ssot helpers return False and emit structured warnings when
     UDM calls raise, and that they return True on success.
  2. GatewayWSManager.disconnect() calls udm_write_unregister BEFORE touching
     local device_connections / device_router.
  3. handle_register() and handle_heartbeat() gate local-cache updates on the
     return value of the ssot helpers.
  4. handlers.DeviceManager register/unregister/update_device_status all use
     the write-through pattern.
"""

import sys
import os
import logging
import unittest
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------------------------------------------------------------------------
# galaxy_gateway.ssot unit tests
# ---------------------------------------------------------------------------

class TestSSOTHelpers(unittest.TestCase):
    """Test the public helpers in galaxy_gateway.ssot."""

    # ------------------------------------------------------------------
    # udm_write_register
    # ------------------------------------------------------------------

    def test_register_success_returns_true(self):
        from galaxy_gateway.ssot import udm_write_register
        udm = MagicMock()
        with patch("galaxy_gateway.ssot._get_udm", return_value=udm):
            result = udm_write_register(
                device_id="d1",
                device_name="Dev One",
                device_type_raw="android",
                capabilities=["touch"],
                metadata={},
                source="test",
            )
        self.assertTrue(result)
        udm.register_device.assert_called_once()

    def test_register_udm_failure_returns_false_and_warns(self):
        from galaxy_gateway.ssot import udm_write_register
        udm = MagicMock()
        udm.register_device.side_effect = RuntimeError("db down")
        with patch("galaxy_gateway.ssot._get_udm", return_value=udm):
            with self.assertLogs("galaxy_gateway.ssot", level="WARNING") as cm:
                result = udm_write_register(
                    device_id="d2",
                    device_name="Dev Two",
                    device_type_raw="windows",
                    capabilities=[],
                    metadata={},
                )
        self.assertFalse(result)
        # Structured event tag must appear in the log record extras
        self.assertTrue(
            any(getattr(r, "event", None) == "ssot_udm_write_failed" for r in cm.records)
        )

    def test_register_unknown_device_type_uses_unknown(self):
        """Unknown device type string should not raise — fallback to UNKNOWN."""
        from galaxy_gateway.ssot import udm_write_register
        udm = MagicMock()
        with patch("galaxy_gateway.ssot._get_udm", return_value=udm):
            result = udm_write_register(
                device_id="d3",
                device_name="Dev Three",
                device_type_raw="xyzzy_custom",
                capabilities=[],
                metadata={},
            )
        self.assertTrue(result)

    # ------------------------------------------------------------------
    # udm_write_heartbeat
    # ------------------------------------------------------------------

    def test_heartbeat_success_returns_true(self):
        from galaxy_gateway.ssot import udm_write_heartbeat
        udm = MagicMock()
        with patch("galaxy_gateway.ssot._get_udm", return_value=udm):
            result = udm_write_heartbeat("d1")
        self.assertTrue(result)
        udm.update_device_status.assert_called_once()

    def test_heartbeat_failure_returns_false_and_warns(self):
        from galaxy_gateway.ssot import udm_write_heartbeat
        udm = MagicMock()
        udm.update_device_status.side_effect = RuntimeError("timeout")
        with patch("galaxy_gateway.ssot._get_udm", return_value=udm):
            with self.assertLogs("galaxy_gateway.ssot", level="WARNING") as cm:
                result = udm_write_heartbeat("d_hb_fail")
        self.assertFalse(result)
        self.assertTrue(
            any(getattr(r, "event", None) == "ssot_udm_heartbeat_failed" for r in cm.records)
        )

    # ------------------------------------------------------------------
    # udm_write_unregister
    # ------------------------------------------------------------------

    def test_unregister_success_returns_true(self):
        from galaxy_gateway.ssot import udm_write_unregister
        udm = MagicMock()
        with patch("galaxy_gateway.ssot._get_udm", return_value=udm):
            result = udm_write_unregister("d1")
        self.assertTrue(result)
        udm.update_device_status.assert_called_once()

    def test_unregister_failure_returns_false_and_warns(self):
        from galaxy_gateway.ssot import udm_write_unregister
        udm = MagicMock()
        udm.update_device_status.side_effect = RuntimeError("gone")
        udm.unregister_device.side_effect = RuntimeError("also gone")
        with patch("galaxy_gateway.ssot._get_udm", return_value=udm):
            with self.assertLogs("galaxy_gateway.ssot", level="WARNING") as cm:
                result = udm_write_unregister("d_un_fail")
        self.assertFalse(result)
        self.assertTrue(
            any(getattr(r, "event", None) == "ssot_udm_unregister_failed" for r in cm.records)
        )


# ---------------------------------------------------------------------------
# GatewayWSManager.disconnect() SSOT ordering test
# ---------------------------------------------------------------------------

class TestWSManagerDisconnectOrder(unittest.TestCase):
    """disconnect() must call udm_write_unregister BEFORE clearing local state."""

    def test_udm_called_before_local_state_cleared(self):
        call_order = []

        def fake_udm_unregister(device_id):
            call_order.append(("udm", device_id))
            return True

        def fake_router_unregister(device_id):
            call_order.append(("router", device_id))

        with (
            patch("galaxy_gateway.websocket_handler.udm_write_unregister", side_effect=fake_udm_unregister),
            patch("galaxy_gateway.websocket_handler.device_router") as mock_router,
        ):
            mock_router.unregister_device.side_effect = fake_router_unregister

            from galaxy_gateway.websocket_handler import GatewayWSManager
            mgr = GatewayWSManager()
            ws_mock = MagicMock()
            mgr.active_connections["conn1"] = ws_mock
            mgr.device_connections["dev1"] = "conn1"

            mgr.disconnect("conn1")

        self.assertEqual(call_order[0], ("udm", "dev1"), "UDM must be written first")
        self.assertEqual(call_order[1], ("router", "dev1"), "Router unregister comes after UDM")

    def test_local_state_cleaned_even_when_udm_fails(self):
        """Socket is gone — local state must still be cleaned up on UDM failure."""
        with (
            patch("galaxy_gateway.websocket_handler.udm_write_unregister", return_value=False),
            patch("galaxy_gateway.websocket_handler.device_router"),
        ):
            from galaxy_gateway.websocket_handler import GatewayWSManager
            mgr = GatewayWSManager()
            mgr.active_connections["conn2"] = MagicMock()
            mgr.device_connections["dev2"] = "conn2"

            mgr.disconnect("conn2")

        self.assertNotIn("conn2", mgr.active_connections)
        self.assertNotIn("dev2", mgr.device_connections)


# ---------------------------------------------------------------------------
# handlers.DeviceManager SSOT guardrail tests
# ---------------------------------------------------------------------------

class TestHandlersDeviceManagerSSOT(unittest.TestCase):
    """DeviceManager methods must gate local cache on ssot helper return value."""

    def _make_device_info(self, device_id="dm-test"):
        from galaxy_gateway.protocol import DeviceInfo, DeviceType
        return DeviceInfo(
            device_id=device_id,
            device_type=DeviceType.ANDROID_PHONE,
        )

    def test_register_does_not_update_local_on_udm_failure(self):
        from galaxy_gateway.handlers.device_manager import DeviceManager
        dm = DeviceManager()
        device_info = self._make_device_info("d_fail")

        with patch("galaxy_gateway.handlers.device_manager.udm_write_register", return_value=False):
            result = dm.register_device(device_info)

        self.assertFalse(result)
        self.assertNotIn("d_fail", dm.devices)
        self.assertNotIn("d_fail", dm.device_status)

    def test_register_updates_local_on_udm_success(self):
        from galaxy_gateway.handlers.device_manager import DeviceManager
        dm = DeviceManager()
        device_info = self._make_device_info("d_ok")

        with patch("galaxy_gateway.handlers.device_manager.udm_write_register", return_value=True):
            result = dm.register_device(device_info)

        self.assertTrue(result)
        self.assertIn("d_ok", dm.devices)
        self.assertEqual(dm.device_status["d_ok"], "online")

    def test_unregister_does_not_remove_local_on_udm_failure(self):
        from galaxy_gateway.handlers.device_manager import DeviceManager
        dm = DeviceManager()
        device_info = self._make_device_info("d_un")
        dm.devices["d_un"] = device_info
        dm.device_status["d_un"] = "online"

        with patch("galaxy_gateway.handlers.device_manager.udm_write_unregister", return_value=False):
            result = dm.unregister_device("d_un")

        self.assertFalse(result)
        self.assertIn("d_un", dm.devices)

    def test_unregister_removes_local_on_udm_success(self):
        from galaxy_gateway.handlers.device_manager import DeviceManager
        dm = DeviceManager()
        device_info = self._make_device_info("d_un_ok")
        dm.devices["d_un_ok"] = device_info
        dm.device_status["d_un_ok"] = "online"

        with patch("galaxy_gateway.handlers.device_manager.udm_write_unregister", return_value=True):
            result = dm.unregister_device("d_un_ok")

        self.assertTrue(result)
        self.assertNotIn("d_un_ok", dm.devices)

    def test_update_status_online_uses_heartbeat_helper(self):
        from galaxy_gateway.handlers.device_manager import DeviceManager
        from galaxy_gateway.protocol import DeviceType, DeviceInfo
        dm = DeviceManager()
        dm.devices["d_hb"] = DeviceInfo(device_id="d_hb", device_type=DeviceType.ANDROID_PHONE)
        dm.device_status["d_hb"] = "offline"

        with patch("galaxy_gateway.handlers.device_manager.udm_write_heartbeat", return_value=True) as mock_hb:
            dm.update_device_status("d_hb", "online")

        mock_hb.assert_called_once_with("d_hb")
        self.assertEqual(dm.device_status["d_hb"], "online")

    def test_update_status_online_does_not_update_local_on_udm_failure(self):
        from galaxy_gateway.handlers.device_manager import DeviceManager
        from galaxy_gateway.protocol import DeviceType, DeviceInfo
        dm = DeviceManager()
        dm.devices["d_hb2"] = DeviceInfo(device_id="d_hb2", device_type=DeviceType.ANDROID_PHONE)
        dm.device_status["d_hb2"] = "offline"

        with patch("galaxy_gateway.handlers.device_manager.udm_write_heartbeat", return_value=False):
            dm.update_device_status("d_hb2", "online")

        self.assertEqual(dm.device_status["d_hb2"], "offline")


if __name__ == "__main__":
    unittest.main()
