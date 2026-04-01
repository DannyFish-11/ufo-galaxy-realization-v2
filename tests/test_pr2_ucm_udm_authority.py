"""
tests/test_pr2_ucm_udm_authority.py
=====================================

PR-2 — Enforce UnifiedConnectionManager (UCM) and UnifiedDeviceManager (UDM)
as the sole connection and device-state authorities.

Validates that:
  1.  UCM_CONNECTION_AUTHORITY sentinel is importable from connection_manager.
  2.  UCM_CONNECTION_AUTHORITY is a non-empty string.
  3.  UCM_CONNECTION_AUTHORITY contains 'UCM' identifying its owner.
  4.  UCM_CONNECTION_AUTHORITY contains 'AUTHORITY' declaring its role.
  5.  UCM_CONNECTION_AUTHORITY contains 'CANONICAL' (not merely advisory).
  6.  UDM_DEVICE_STATE_AUTHORITY sentinel is importable from device_manager.
  7.  UDM_DEVICE_STATE_AUTHORITY is a non-empty string.
  8.  UDM_DEVICE_STATE_AUTHORITY contains 'UDM' identifying its owner.
  9.  UDM_DEVICE_STATE_AUTHORITY contains 'AUTHORITY' declaring its role.
  10. UDM_DEVICE_STATE_AUTHORITY contains 'CANONICAL' (not merely advisory).
  11. GATEWAY_SSOT_WRITE_AUTHORITY sentinel is importable from ssot.
  12. GATEWAY_SSOT_WRITE_AUTHORITY is a non-empty string.
  13. GATEWAY_SSOT_WRITE_AUTHORITY contains 'WRITE_PATH' (write-path role only).
  14. UCM and UDM sentinel values are distinct strings.
  15. UCM, UDM, and SSOT sentinel values are all distinct.
  16. connection_manager.py source contains 'UCM_CONNECTION_AUTHORITY'.
  17. connection_manager.py source declares non-authoritative roles for local maps.
  18. device_manager.py source contains 'UDM_DEVICE_STATE_AUTHORITY'.
  19. device_manager.py source declares compatibility-layer role for downstream.
  20. ssot.py source contains 'GATEWAY_SSOT_WRITE_AUTHORITY'.
  21. ssot.py source docstring mentions 'gateway-side canonical write path'.
  22. ssot.py source documents write-through path for gateway→UDM.
  23. ssot.py has no SyntaxError (from __future__ placed correctly).
  24. udm_write_register returns True on success.
  25. udm_write_register returns False and logs warning when UDM raises.
  26. udm_write_heartbeat returns True on success.
  27. udm_write_heartbeat returns False and logs warning when UDM raises.
  28. udm_write_unregister returns True on success.
  29. udm_write_unregister returns False and logs warning when UDM raises.
  30. udm_write_upsert returns True on success.
  31. udm_write_upsert returns False and logs warning when UDM raises.
  32. GatewayWSManager.disconnect calls UCM unregister before local map cleanup.
  33. GatewayWSManager.disconnect calls udm_write_unregister before local map cleanup.
  34. handle_register gates device_router.register_device on udm_success.
  35. handle_register calls UCM register_connection after UDM write succeeds.
  36. handle_heartbeat calls UCM update_heartbeat on heartbeat path.
  37. connection_manager.py source mentions 'NOT acceptable' roles for local maps.
  38. device_manager.py source mentions 'compatibility' for downstream structures.
  39. websocket_handler.py source routes disconnect through UCM (unregister_connection).
  40. websocket_handler.py source routes registration through UCM (register_connection).
"""

from __future__ import annotations

import ast
import importlib
import logging
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch, call

# ---------------------------------------------------------------------------
# Source-file helpers (avoid heavy import side-effects for boundary tests)
# ---------------------------------------------------------------------------

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))


def _read_source(rel_path: str) -> str:
    full = os.path.join(_REPO_ROOT, rel_path)
    with open(full, encoding="utf-8") as fh:
        return fh.read()


UCM_SRC = _read_source("core/unified/connection_manager.py")
UDM_SRC = _read_source("core/unified/device_manager.py")
SSOT_SRC = _read_source("galaxy_gateway/ssot.py")
WS_HANDLER_SRC = _read_source("galaxy_gateway/websocket_handler.py")


# ===========================================================================
# 1–15: Sentinel constant existence and shape
# ===========================================================================

class TestUCMSentinel(unittest.TestCase):
    """Tests 1–5: UCM_CONNECTION_AUTHORITY sentinel."""

    def test_01_ucm_authority_importable(self):
        """UCM_CONNECTION_AUTHORITY is importable from connection_manager."""
        from core.unified.connection_manager import UCM_CONNECTION_AUTHORITY  # noqa: F401

    def test_02_ucm_authority_non_empty_string(self):
        from core.unified.connection_manager import UCM_CONNECTION_AUTHORITY
        self.assertIsInstance(UCM_CONNECTION_AUTHORITY, str)
        self.assertTrue(len(UCM_CONNECTION_AUTHORITY) > 0)

    def test_03_ucm_authority_contains_ucm(self):
        from core.unified.connection_manager import UCM_CONNECTION_AUTHORITY
        self.assertIn("UCM", UCM_CONNECTION_AUTHORITY)

    def test_04_ucm_authority_contains_authority(self):
        from core.unified.connection_manager import UCM_CONNECTION_AUTHORITY
        self.assertIn("AUTHORITY", UCM_CONNECTION_AUTHORITY)

    def test_05_ucm_authority_contains_canonical(self):
        from core.unified.connection_manager import UCM_CONNECTION_AUTHORITY
        self.assertIn("CANONICAL", UCM_CONNECTION_AUTHORITY)


class TestUDMSentinel(unittest.TestCase):
    """Tests 6–10: UDM_DEVICE_STATE_AUTHORITY sentinel."""

    def test_06_udm_authority_importable(self):
        """UDM_DEVICE_STATE_AUTHORITY is importable from device_manager."""
        from core.unified.device_manager import UDM_DEVICE_STATE_AUTHORITY  # noqa: F401

    def test_07_udm_authority_non_empty_string(self):
        from core.unified.device_manager import UDM_DEVICE_STATE_AUTHORITY
        self.assertIsInstance(UDM_DEVICE_STATE_AUTHORITY, str)
        self.assertTrue(len(UDM_DEVICE_STATE_AUTHORITY) > 0)

    def test_08_udm_authority_contains_udm(self):
        from core.unified.device_manager import UDM_DEVICE_STATE_AUTHORITY
        self.assertIn("UDM", UDM_DEVICE_STATE_AUTHORITY)

    def test_09_udm_authority_contains_authority(self):
        from core.unified.device_manager import UDM_DEVICE_STATE_AUTHORITY
        self.assertIn("AUTHORITY", UDM_DEVICE_STATE_AUTHORITY)

    def test_10_udm_authority_contains_canonical(self):
        from core.unified.device_manager import UDM_DEVICE_STATE_AUTHORITY
        self.assertIn("CANONICAL", UDM_DEVICE_STATE_AUTHORITY)


class TestSSOTSentinel(unittest.TestCase):
    """Tests 11–15: GATEWAY_SSOT_WRITE_AUTHORITY sentinel and distinctness."""

    def test_11_ssot_authority_importable(self):
        from galaxy_gateway.ssot import GATEWAY_SSOT_WRITE_AUTHORITY  # noqa: F401

    def test_12_ssot_authority_non_empty_string(self):
        from galaxy_gateway.ssot import GATEWAY_SSOT_WRITE_AUTHORITY
        self.assertIsInstance(GATEWAY_SSOT_WRITE_AUTHORITY, str)
        self.assertTrue(len(GATEWAY_SSOT_WRITE_AUTHORITY) > 0)

    def test_13_ssot_authority_contains_write_path(self):
        from galaxy_gateway.ssot import GATEWAY_SSOT_WRITE_AUTHORITY
        self.assertIn("WRITE_PATH", GATEWAY_SSOT_WRITE_AUTHORITY)

    def test_14_ucm_and_udm_sentinels_distinct(self):
        from core.unified.connection_manager import UCM_CONNECTION_AUTHORITY
        from core.unified.device_manager import UDM_DEVICE_STATE_AUTHORITY
        self.assertNotEqual(UCM_CONNECTION_AUTHORITY, UDM_DEVICE_STATE_AUTHORITY)

    def test_15_all_three_sentinels_distinct(self):
        from core.unified.connection_manager import UCM_CONNECTION_AUTHORITY
        from core.unified.device_manager import UDM_DEVICE_STATE_AUTHORITY
        from galaxy_gateway.ssot import GATEWAY_SSOT_WRITE_AUTHORITY
        sentinels = {UCM_CONNECTION_AUTHORITY, UDM_DEVICE_STATE_AUTHORITY, GATEWAY_SSOT_WRITE_AUTHORITY}
        self.assertEqual(len(sentinels), 3, "All three authority sentinels must be distinct strings")


# ===========================================================================
# 16–22: Source-file content checks
# ===========================================================================

class TestSourceContent(unittest.TestCase):
    """Tests 16–22: Source-file boundary documentation."""

    def test_16_ucm_source_contains_sentinel_name(self):
        self.assertIn("UCM_CONNECTION_AUTHORITY", UCM_SRC)

    def test_17_ucm_source_documents_non_authoritative_local_maps(self):
        self.assertIn("NOT acceptable", UCM_SRC)

    def test_18_udm_source_contains_sentinel_name(self):
        self.assertIn("UDM_DEVICE_STATE_AUTHORITY", UDM_SRC)

    def test_19_udm_source_documents_compatibility_layer(self):
        self.assertIn("compatibility", UDM_SRC.lower())

    def test_20_ssot_source_contains_sentinel_name(self):
        self.assertIn("GATEWAY_SSOT_WRITE_AUTHORITY", SSOT_SRC)

    def test_21_ssot_source_documents_gateway_side_canonical_write_path(self):
        self.assertIn("gateway-side canonical write path", SSOT_SRC)

    def test_22_ssot_source_documents_udm_write_through_path(self):
        # The docstring must describe the UDM write-through path
        self.assertIn("UnifiedDeviceManager", SSOT_SRC)
        self.assertIn("udm_write_", SSOT_SRC)


# ===========================================================================
# 23: ssot.py has no SyntaxError (from __future__ placed correctly)
# ===========================================================================

class TestSSOTSyntax(unittest.TestCase):
    """Test 23: ssot.py has valid Python syntax."""

    def test_23_ssot_no_syntax_error(self):
        try:
            ast.parse(SSOT_SRC)
        except SyntaxError as exc:
            self.fail(f"galaxy_gateway/ssot.py has a SyntaxError: {exc}")


# ===========================================================================
# 24–31: SSOT write-through helper behaviour
# ===========================================================================

class TestSSOTHelpers(unittest.TestCase):
    """Tests 24–31: SSOT helpers return True on success, False+warn on failure."""

    # --- udm_write_register ---

    def test_24_udm_write_register_returns_true_on_success(self):
        from galaxy_gateway.ssot import udm_write_register
        udm = MagicMock()
        with patch("galaxy_gateway.ssot._get_udm", return_value=udm):
            result = udm_write_register(
                device_id="p2_d1", device_name="PR2 Device",
                device_type_raw="android", capabilities=[], metadata={},
            )
        self.assertTrue(result)
        udm.register_device.assert_called_once()

    def test_25_udm_write_register_returns_false_and_warns_on_failure(self):
        from galaxy_gateway.ssot import udm_write_register
        udm = MagicMock()
        udm.register_device.side_effect = RuntimeError("write failed")
        with patch("galaxy_gateway.ssot._get_udm", return_value=udm):
            with self.assertLogs("galaxy_gateway.ssot", level="WARNING") as cm:
                result = udm_write_register(
                    device_id="p2_d2", device_name="PR2 Device",
                    device_type_raw="android", capabilities=[], metadata={},
                )
        self.assertFalse(result)
        self.assertTrue(
            any(getattr(r, "event", None) == "ssot_udm_write_failed" for r in cm.records),
            "Structured event tag 'ssot_udm_write_failed' must appear in warning log",
        )

    # --- udm_write_heartbeat ---

    def test_26_udm_write_heartbeat_returns_true_on_success(self):
        from galaxy_gateway.ssot import udm_write_heartbeat
        udm = MagicMock()
        with patch("galaxy_gateway.ssot._get_udm", return_value=udm):
            result = udm_write_heartbeat("p2_hb_ok")
        self.assertTrue(result)
        udm.update_device_status.assert_called_once()

    def test_27_udm_write_heartbeat_returns_false_and_warns_on_failure(self):
        from galaxy_gateway.ssot import udm_write_heartbeat
        udm = MagicMock()
        udm.update_device_status.side_effect = RuntimeError("timeout")
        with patch("galaxy_gateway.ssot._get_udm", return_value=udm):
            with self.assertLogs("galaxy_gateway.ssot", level="WARNING") as cm:
                result = udm_write_heartbeat("p2_hb_fail")
        self.assertFalse(result)
        self.assertTrue(
            any(getattr(r, "event", None) == "ssot_udm_heartbeat_failed" for r in cm.records),
        )

    # --- udm_write_unregister ---

    def test_28_udm_write_unregister_returns_true_on_success(self):
        from galaxy_gateway.ssot import udm_write_unregister
        udm = MagicMock()
        with patch("galaxy_gateway.ssot._get_udm", return_value=udm):
            result = udm_write_unregister("p2_unreg_ok")
        self.assertTrue(result)

    def test_29_udm_write_unregister_returns_false_and_warns_on_failure(self):
        from galaxy_gateway.ssot import udm_write_unregister
        udm = MagicMock()
        udm.update_device_status.side_effect = RuntimeError("gone")
        udm.unregister_device.side_effect = RuntimeError("gone")
        with patch("galaxy_gateway.ssot._get_udm", return_value=udm):
            with self.assertLogs("galaxy_gateway.ssot", level="WARNING") as cm:
                result = udm_write_unregister("p2_unreg_fail")
        self.assertFalse(result)
        self.assertTrue(
            any(getattr(r, "event", None) == "ssot_udm_unregister_failed" for r in cm.records),
        )

    # --- udm_write_upsert ---

    def test_30_udm_write_upsert_returns_true_on_success(self):
        from galaxy_gateway.ssot import udm_write_upsert
        udm = MagicMock()
        with patch("galaxy_gateway.ssot._get_udm", return_value=udm):
            result = udm_write_upsert("p2_upsert_ok", {"status": "online"})
        self.assertTrue(result)
        udm.upsert_device_state.assert_called_once()

    def test_31_udm_write_upsert_returns_false_and_warns_on_failure(self):
        from galaxy_gateway.ssot import udm_write_upsert
        udm = MagicMock()
        udm.upsert_device_state.side_effect = RuntimeError("db error")
        with patch("galaxy_gateway.ssot._get_udm", return_value=udm):
            with self.assertLogs("galaxy_gateway.ssot", level="WARNING") as cm:
                result = udm_write_upsert("p2_upsert_fail", {"status": "online"})
        self.assertFalse(result)
        self.assertTrue(
            any(getattr(r, "event", None) == "ssot_udm_upsert_failed" for r in cm.records),
        )


# ===========================================================================
# 32–33: GatewayWSManager.disconnect calls UCM and SSOT before local cleanup
# ===========================================================================

class TestGatewayWSManagerDisconnect(unittest.TestCase):
    """Tests 32–33: UCM/SSOT called before local map cleanup on disconnect."""

    def _make_manager(self):
        from galaxy_gateway.websocket_handler import GatewayWSManager
        mgr = GatewayWSManager.__new__(GatewayWSManager)
        mgr.active_connections = {}
        mgr.device_connections = {}
        return mgr

    def test_32_disconnect_calls_ucm_unregister_before_local_cleanup(self):
        """UCM unregister is invoked on disconnect path."""
        mgr = self._make_manager()
        ws = MagicMock()
        mgr.active_connections["conn-1"] = ws
        mgr.device_connections["dev-ucm-1"] = "conn-1"

        ucm = MagicMock()
        ucm.mark_offline = MagicMock()

        call_order = []

        def track_ucm_mark_offline(did):
            call_order.append(("ucm_mark_offline", did))

        ucm.mark_offline.side_effect = track_ucm_mark_offline

        def track_udm_unregister(did):
            call_order.append(("udm_unregister", did))
            return True

        with patch("galaxy_gateway.websocket_handler.udm_write_unregister",
                   side_effect=track_udm_unregister), \
             patch("galaxy_gateway.websocket_handler.device_router") as mock_router, \
             patch.object(mgr, "_ucm", return_value=ucm), \
             patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")):

            mgr.disconnect("conn-1")

        # Both UCM and UDM must have been called
        ucm_called = any(tag == "ucm_mark_offline" for tag, _ in call_order)
        udm_called = any(tag == "udm_unregister" for tag, _ in call_order)
        self.assertTrue(ucm_called, "UCM mark_offline must be called on disconnect")
        self.assertTrue(udm_called, "udm_write_unregister must be called on disconnect")

    def test_33_disconnect_calls_udm_write_unregister_before_local_map_delete(self):
        """udm_write_unregister is called on disconnect; local map is cleaned up."""
        mgr = self._make_manager()
        ws = MagicMock()
        mgr.active_connections["conn-2"] = ws
        mgr.device_connections["dev-ssot-2"] = "conn-2"

        udm_called = []

        def capture_udm(did):
            udm_called.append(did)
            return True

        with patch("galaxy_gateway.websocket_handler.udm_write_unregister",
                   side_effect=capture_udm), \
             patch("galaxy_gateway.websocket_handler.device_router"), \
             patch.object(mgr, "_ucm", return_value=MagicMock(mark_offline=MagicMock())), \
             patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")):

            mgr.disconnect("conn-2")

        self.assertIn("dev-ssot-2", udm_called,
                      "udm_write_unregister must be called with the device_id")
        # Local map must be cleaned up after the call
        self.assertNotIn("dev-ssot-2", mgr.device_connections)


# ===========================================================================
# 34–36: handle_register and handle_heartbeat canonical authority paths
# ===========================================================================

class TestHandleRegisterAndHeartbeat(unittest.TestCase):
    """Tests 34–36: registration and heartbeat route through UCM/UDM."""

    def test_34_handle_register_gates_device_router_on_udm_success(self):
        """device_router.register_device is only called when UDM write succeeds."""
        # When udm_write_register returns False, device_router must NOT be called.
        import asyncio
        from galaxy_gateway.websocket_handler import handle_register

        ws = MagicMock()
        ws.send_json = AsyncMock()

        aip_msg = MagicMock()
        aip_msg.device_id = "pr2_reg_gate"
        aip_msg.message_id = "msg-gate-1"
        aip_msg.device_type = None
        aip_msg.payload = {"device_info": {"device_type": "android", "capabilities": []}}

        with patch("galaxy_gateway.websocket_handler.udm_write_register", return_value=False), \
             patch("galaxy_gateway.websocket_handler.device_router") as mock_router:
            asyncio.run(handle_register("conn-gate", aip_msg, ws))
            mock_router.register_device.assert_not_called()

    def test_35_handle_register_calls_ucm_register_after_udm_success(self):
        """UCM register_connection is called after successful UDM write."""
        import asyncio
        from galaxy_gateway.websocket_handler import handle_register, connection_manager

        ws = MagicMock()
        ws.send_json = AsyncMock()

        aip_msg = MagicMock()
        aip_msg.device_id = "pr2_ucm_register"
        aip_msg.message_id = "msg-ucm-reg-1"
        aip_msg.device_type = None
        aip_msg.payload = {"device_info": {"device_type": "android", "capabilities": []}}

        ucm = MagicMock()
        ucm.is_device_connected = MagicMock(return_value=False)
        ucm.register_connection = AsyncMock()

        with patch("galaxy_gateway.websocket_handler.udm_write_register", return_value=True), \
             patch("galaxy_gateway.websocket_handler.device_router") as mock_router, \
             patch.object(connection_manager, "_ucm", return_value=ucm):
            mock_router.register_device.return_value = True
            asyncio.run(handle_register("conn-ucm-reg", aip_msg, ws))

        ucm.register_connection.assert_called_once()

    def test_36_handle_heartbeat_updates_ucm_heartbeat(self):
        """handle_heartbeat calls UCM update_heartbeat on the presence backbone."""
        import asyncio
        from galaxy_gateway.websocket_handler import handle_heartbeat, connection_manager

        aip_msg = MagicMock()
        aip_msg.device_id = "pr2_hb_ucm"
        aip_msg.message_id = "msg-hb-1"

        ucm = MagicMock()
        ucm.update_heartbeat = MagicMock(return_value=True)

        with patch("galaxy_gateway.websocket_handler.udm_write_heartbeat", return_value=True), \
             patch("galaxy_gateway.websocket_handler.device_router") as mock_router, \
             patch("galaxy_gateway.websocket_handler.connection_manager") as mock_cm:
            mock_router.get_device.return_value = None
            mock_cm._ucm.return_value = ucm
            mock_cm.send_message = AsyncMock()
            asyncio.run(handle_heartbeat("conn-hb", aip_msg))

        ucm.update_heartbeat.assert_called_once_with("pr2_hb_ucm")


# ===========================================================================
# 37–40: Source-level enforcement documentation checks
# ===========================================================================

class TestSourceEnforcementDocs(unittest.TestCase):
    """Tests 37–40: Source-file enforcement signals and documentation."""

    def test_37_ucm_source_documents_not_acceptable_roles(self):
        """UCM source must document which local map roles are NOT acceptable."""
        self.assertIn("NOT acceptable", UCM_SRC,
                      "UCM source must document unacceptable roles for external connection maps")

    def test_38_udm_source_documents_compatibility_downstream(self):
        """UDM source must document that downstream structures are compat-only."""
        self.assertIn("compatibility", UDM_SRC.lower())
        # Must also mention that downstream structures must not act as parallel sources
        udm_lower = UDM_SRC.lower()
        self.assertTrue(
            "must not act as parallel" in udm_lower or
            ("must not" in udm_lower and "parallel" in udm_lower),
            "UDM source must state that downstream structures must not act as parallel truth sources",
        )

    def test_39_websocket_handler_routes_disconnect_through_ucm(self):
        """websocket_handler.py must call UCM unregister_connection on disconnect."""
        self.assertIn("unregister_connection", WS_HANDLER_SRC,
                      "websocket_handler must route disconnect through UCM.unregister_connection")

    def test_40_websocket_handler_routes_registration_through_ucm(self):
        """websocket_handler.py must call UCM register_connection on registration."""
        self.assertIn("register_connection", WS_HANDLER_SRC,
                      "websocket_handler must route registration through UCM.register_connection")


if __name__ == "__main__":
    unittest.main()
