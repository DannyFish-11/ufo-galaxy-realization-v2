"""tests/test_pr58_runtime_presence_backbone.py
================================================
Tests for PR-58: Consolidate runtime presence around
``core/unified/connection_manager.UnifiedConnectionManager`` (UCM).

Coverage:
  UnifiedConnectionInfo model
  1.  last_seen field defaults to 0.0.
  2.  routable field defaults to False.
  3.  last_seen is set on register_connection.
  4.  routable is True after register_connection.

  UCM.update_heartbeat
  5.  Returns True for a connected device.
  6.  Returns False for an unknown device.
  7.  Updates last_seen to a recent timestamp.
  8.  Keeps routable=True after heartbeat.
  9.  Restores state to CONNECTED if previously DISCONNECTED.

  UCM.mark_offline
  10. Sets routable=False for a connected device.
  11. Removes device from _websockets map.
  12. Preserves connection record (does not delete from _connections).
  13. No-op for unknown device (no raise).

  UCM.reconnect_patch
  14. Updates _websockets with new websocket.
  15. Preserves existing UnifiedConnectionInfo entry (no duplicate).
  16. Increments total_reconnects.
  17. Sets routable=True.
  18. Updates last_seen.
  19. Creates new entry if device was not previously known.
  20. Broadcasts device_reconnected status event.

  UCM.check_heartbeat_timeouts
  21. Returns empty list when no devices are timed out.
  22. Returns device_id of timed-out device.
  23. Marks timed-out device offline (routable=False).
  24. Does not mark device with last_seen==0.0 as timed out.
  25. Does not mark recently-heartbeated device as timed out.

  UCM.get_presence_view
  26. Returns dict with device_id as key.
  27. online=True when device is in _websockets and routable=True.
  28. online=False when device removed from _websockets.
  29. routable field matches UnifiedConnectionInfo.routable.
  30. last_seen is preserved.
  31. state is a string value.
  32. Empty dict when no connections registered.

  GatewayWSManager presence delegation
  33. disconnect() calls UCM mark_offline (sync path via asyncio loop absence).
  34. send_to_device() falls through to UCM when local connection_id not found.
  35. is_device_connected() returns True when device in UCM.

  RouteConnectionPool pending-response delegation
  36. resolve_command_response() calls UCM.resolve_command_response().
  37. Local _pending_responses still resolves if UCM raises.

  AndroidBridge UCM routing
  38. _patch_heartbeat_to_udm() calls UCM.update_heartbeat().
  39. _patch_disconnect_to_udm() calls UCM.mark_offline().
  40. _patch_reconnect_to_udm() calls UCM.update_heartbeat().

  register_connection: broadcast semantics
  41. Broadcasts device_connected status on registration.
  42. Broadcasts device_disconnected on unregister_connection.

  UCM.send_command_and_wait + resolve_command_response round-trip
  43. Future is resolved when resolve_command_response is called with matching id.
  44. Returns error dict on timeout.

  Backward-compatibility: existing API surface preserved
  45. UCM.is_device_connected() still works as before.
  46. UCM.get_all_devices() includes UCM-registered devices.
  47. UCM.get_connected_device_ids() reflects current _websockets.
  48. UCM.get_connection() returns UnifiedConnectionInfo with new fields.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_ucm() -> None:
    """Reset the UCM singleton between tests."""
    from core.unified import connection_manager as _mod
    _mod.UnifiedConnectionManager._instance = None
    _mod._manager = None


def _make_websocket() -> MagicMock:
    ws = MagicMock()
    ws.send_json = AsyncMock()
    return ws


# ---------------------------------------------------------------------------
# 1–4: UnifiedConnectionInfo model
# ---------------------------------------------------------------------------

class TestUnifiedConnectionInfoPresenceFields:
    def test_01_last_seen_defaults_to_zero(self):
        from core.unified.models import UnifiedConnectionInfo
        info = UnifiedConnectionInfo(device_id="d1")
        assert info.last_seen == 0.0

    def test_02_routable_defaults_to_false(self):
        from core.unified.models import UnifiedConnectionInfo
        info = UnifiedConnectionInfo(device_id="d1")
        assert info.routable is False

    @pytest.mark.asyncio
    async def test_03_last_seen_set_on_register(self):
        _reset_ucm()
        from core.unified.connection_manager import get_unified_connection_manager
        ucm = get_unified_connection_manager()
        before = time.time()
        ws = _make_websocket()
        await ucm.register_connection("reg_dev", ws)
        info = ucm.get_connection("reg_dev")
        assert info.last_seen >= before

    @pytest.mark.asyncio
    async def test_04_routable_true_after_register(self):
        _reset_ucm()
        from core.unified.connection_manager import get_unified_connection_manager
        ucm = get_unified_connection_manager()
        ws = _make_websocket()
        await ucm.register_connection("reg_dev2", ws)
        info = ucm.get_connection("reg_dev2")
        assert info.routable is True


# ---------------------------------------------------------------------------
# 5–9: UCM.update_heartbeat
# ---------------------------------------------------------------------------

class TestUCMUpdateHeartbeat:
    def setup_method(self):
        _reset_ucm()

    @pytest.mark.asyncio
    async def test_05_returns_true_for_connected_device(self):
        from core.unified.connection_manager import get_unified_connection_manager
        ucm = get_unified_connection_manager()
        await ucm.register_connection("hb_dev", _make_websocket())
        result = ucm.update_heartbeat("hb_dev")
        assert result is True

    def test_06_returns_false_for_unknown_device(self):
        from core.unified.connection_manager import get_unified_connection_manager
        ucm = get_unified_connection_manager()
        assert ucm.update_heartbeat("nonexistent_device") is False

    @pytest.mark.asyncio
    async def test_07_updates_last_seen(self):
        from core.unified.connection_manager import get_unified_connection_manager
        ucm = get_unified_connection_manager()
        await ucm.register_connection("hb_dev2", _make_websocket())
        before = time.time()
        ucm.update_heartbeat("hb_dev2")
        info = ucm.get_connection("hb_dev2")
        assert info.last_seen >= before

    @pytest.mark.asyncio
    async def test_08_routable_stays_true_after_heartbeat(self):
        from core.unified.connection_manager import get_unified_connection_manager
        ucm = get_unified_connection_manager()
        await ucm.register_connection("hb_dev3", _make_websocket())
        ucm.update_heartbeat("hb_dev3")
        info = ucm.get_connection("hb_dev3")
        assert info.routable is True

    @pytest.mark.asyncio
    async def test_09_restores_connected_state(self):
        from core.unified.connection_manager import get_unified_connection_manager
        from core.unified.models import UnifiedConnectionState
        ucm = get_unified_connection_manager()
        await ucm.register_connection("hb_dev4", _make_websocket())
        # Manually set state to DISCONNECTED
        ucm.get_connection("hb_dev4").state = UnifiedConnectionState.DISCONNECTED
        ucm.update_heartbeat("hb_dev4")
        info = ucm.get_connection("hb_dev4")
        state_val = info.state if isinstance(info.state, str) else info.state.value
        assert state_val == "connected"


# ---------------------------------------------------------------------------
# 10–13: UCM.mark_offline
# ---------------------------------------------------------------------------

class TestUCMMarkOffline:
    def setup_method(self):
        _reset_ucm()

    @pytest.mark.asyncio
    async def test_10_sets_routable_false(self):
        from core.unified.connection_manager import get_unified_connection_manager
        ucm = get_unified_connection_manager()
        await ucm.register_connection("off_dev", _make_websocket())
        ucm.mark_offline("off_dev")
        info = ucm.get_connection("off_dev")
        assert info.routable is False

    @pytest.mark.asyncio
    async def test_11_removes_from_websockets(self):
        from core.unified.connection_manager import get_unified_connection_manager
        ucm = get_unified_connection_manager()
        await ucm.register_connection("off_dev2", _make_websocket())
        ucm.mark_offline("off_dev2")
        assert "off_dev2" not in ucm._websockets

    @pytest.mark.asyncio
    async def test_12_preserves_connection_record(self):
        from core.unified.connection_manager import get_unified_connection_manager
        ucm = get_unified_connection_manager()
        await ucm.register_connection("off_dev3", _make_websocket())
        ucm.mark_offline("off_dev3")
        # Connection record remains (soft offline, not full unregister)
        assert ucm.get_connection("off_dev3") is not None

    def test_13_no_raise_for_unknown_device(self):
        from core.unified.connection_manager import get_unified_connection_manager
        ucm = get_unified_connection_manager()
        # Should not raise for unknown device
        ucm.mark_offline("completely_unknown")


# ---------------------------------------------------------------------------
# 14–20: UCM.reconnect_patch
# ---------------------------------------------------------------------------

class TestUCMReconnectPatch:
    def setup_method(self):
        _reset_ucm()

    @pytest.mark.asyncio
    async def test_14_updates_websockets(self):
        from core.unified.connection_manager import get_unified_connection_manager
        ucm = get_unified_connection_manager()
        ws1 = _make_websocket()
        ws2 = _make_websocket()
        await ucm.register_connection("rc_dev", ws1)
        await ucm.reconnect_patch("rc_dev", ws2)
        assert ucm._websockets["rc_dev"] is ws2

    @pytest.mark.asyncio
    async def test_15_preserves_existing_entry(self):
        from core.unified.connection_manager import get_unified_connection_manager
        ucm = get_unified_connection_manager()
        ws1 = _make_websocket()
        await ucm.register_connection("rc_dev2", ws1)
        original_conn_id = ucm.get_connection("rc_dev2").connection_id
        await ucm.reconnect_patch("rc_dev2", _make_websocket())
        info = ucm.get_connection("rc_dev2")
        assert info.connection_id == original_conn_id

    @pytest.mark.asyncio
    async def test_16_increments_total_reconnects(self):
        from core.unified.connection_manager import get_unified_connection_manager
        ucm = get_unified_connection_manager()
        await ucm.register_connection("rc_dev3", _make_websocket())
        await ucm.reconnect_patch("rc_dev3", _make_websocket())
        info = ucm.get_connection("rc_dev3")
        assert info.total_reconnects == 1

    @pytest.mark.asyncio
    async def test_17_sets_routable_true(self):
        from core.unified.connection_manager import get_unified_connection_manager
        ucm = get_unified_connection_manager()
        await ucm.register_connection("rc_dev4", _make_websocket())
        ucm.mark_offline("rc_dev4")  # go offline
        await ucm.reconnect_patch("rc_dev4", _make_websocket())
        info = ucm.get_connection("rc_dev4")
        assert info.routable is True

    @pytest.mark.asyncio
    async def test_18_updates_last_seen(self):
        from core.unified.connection_manager import get_unified_connection_manager
        ucm = get_unified_connection_manager()
        await ucm.register_connection("rc_dev5", _make_websocket())
        before = time.time()
        await ucm.reconnect_patch("rc_dev5", _make_websocket())
        info = ucm.get_connection("rc_dev5")
        assert info.last_seen >= before

    @pytest.mark.asyncio
    async def test_19_creates_new_entry_for_unknown(self):
        from core.unified.connection_manager import get_unified_connection_manager
        ucm = get_unified_connection_manager()
        await ucm.reconnect_patch("new_rc_dev", _make_websocket())
        assert ucm.get_connection("new_rc_dev") is not None

    @pytest.mark.asyncio
    async def test_20_broadcasts_reconnected_event(self):
        from core.unified.connection_manager import get_unified_connection_manager
        ucm = get_unified_connection_manager()
        await ucm.register_connection("rc_dev6", _make_websocket())
        # Subscribe a status sink to capture events
        events = []
        sub_ws = MagicMock()
        sub_ws.send_json = AsyncMock(side_effect=lambda m: events.append(m))
        ucm._status_subscribers.append(sub_ws)
        await ucm.reconnect_patch("rc_dev6", _make_websocket())
        event_types = [e.get("type") for e in events]
        assert "device_reconnected" in event_types


# ---------------------------------------------------------------------------
# 21–25: UCM.check_heartbeat_timeouts
# ---------------------------------------------------------------------------

class TestUCMCheckHeartbeatTimeouts:
    def setup_method(self):
        _reset_ucm()

    @pytest.mark.asyncio
    async def test_21_returns_empty_when_no_timeout(self):
        from core.unified.connection_manager import get_unified_connection_manager
        ucm = get_unified_connection_manager()
        await ucm.register_connection("t_dev1", _make_websocket())
        ucm.update_heartbeat("t_dev1")
        result = ucm.check_heartbeat_timeouts(timeout_seconds=3600.0)
        assert "t_dev1" not in result

    @pytest.mark.asyncio
    async def test_22_returns_timed_out_device(self):
        from core.unified.connection_manager import get_unified_connection_manager
        ucm = get_unified_connection_manager()
        await ucm.register_connection("t_dev2", _make_websocket())
        # Force last_seen to a very old timestamp
        ucm.get_connection("t_dev2").last_seen = time.time() - 9999.0
        result = ucm.check_heartbeat_timeouts(timeout_seconds=60.0)
        assert "t_dev2" in result

    @pytest.mark.asyncio
    async def test_23_marks_timed_out_offline(self):
        from core.unified.connection_manager import get_unified_connection_manager
        ucm = get_unified_connection_manager()
        await ucm.register_connection("t_dev3", _make_websocket())
        ucm.get_connection("t_dev3").last_seen = time.time() - 9999.0
        ucm.check_heartbeat_timeouts(timeout_seconds=60.0)
        info = ucm.get_connection("t_dev3")
        assert info.routable is False

    @pytest.mark.asyncio
    async def test_24_does_not_mark_zero_last_seen(self):
        from core.unified.connection_manager import get_unified_connection_manager
        ucm = get_unified_connection_manager()
        await ucm.register_connection("t_dev4", _make_websocket())
        # last_seen == 0.0 means never heartbeated — should NOT be timed out
        ucm.get_connection("t_dev4").last_seen = 0.0
        result = ucm.check_heartbeat_timeouts(timeout_seconds=1.0)
        assert "t_dev4" not in result

    @pytest.mark.asyncio
    async def test_25_does_not_mark_recent_device(self):
        from core.unified.connection_manager import get_unified_connection_manager
        ucm = get_unified_connection_manager()
        await ucm.register_connection("t_dev5", _make_websocket())
        ucm.update_heartbeat("t_dev5")
        result = ucm.check_heartbeat_timeouts(timeout_seconds=9999.0)
        assert "t_dev5" not in result


# ---------------------------------------------------------------------------
# 26–32: UCM.get_presence_view
# ---------------------------------------------------------------------------

class TestUCMGetPresenceView:
    def setup_method(self):
        _reset_ucm()

    @pytest.mark.asyncio
    async def test_26_returns_device_id_as_key(self):
        from core.unified.connection_manager import get_unified_connection_manager
        ucm = get_unified_connection_manager()
        await ucm.register_connection("pv_dev1", _make_websocket())
        view = ucm.get_presence_view()
        assert "pv_dev1" in view

    @pytest.mark.asyncio
    async def test_27_online_true_when_connected_and_routable(self):
        from core.unified.connection_manager import get_unified_connection_manager
        ucm = get_unified_connection_manager()
        await ucm.register_connection("pv_dev2", _make_websocket())
        ucm.update_heartbeat("pv_dev2")
        view = ucm.get_presence_view()
        assert view["pv_dev2"]["online"] is True

    @pytest.mark.asyncio
    async def test_28_online_false_when_ws_removed(self):
        from core.unified.connection_manager import get_unified_connection_manager
        ucm = get_unified_connection_manager()
        await ucm.register_connection("pv_dev3", _make_websocket())
        ucm.mark_offline("pv_dev3")
        view = ucm.get_presence_view()
        assert view["pv_dev3"]["online"] is False

    @pytest.mark.asyncio
    async def test_29_routable_field_matches_info(self):
        from core.unified.connection_manager import get_unified_connection_manager
        ucm = get_unified_connection_manager()
        await ucm.register_connection("pv_dev4", _make_websocket())
        info = ucm.get_connection("pv_dev4")
        info.routable = False
        view = ucm.get_presence_view()
        assert view["pv_dev4"]["routable"] is False

    @pytest.mark.asyncio
    async def test_30_last_seen_preserved(self):
        from core.unified.connection_manager import get_unified_connection_manager
        ucm = get_unified_connection_manager()
        await ucm.register_connection("pv_dev5", _make_websocket())
        ucm.get_connection("pv_dev5").last_seen = 12345.0
        view = ucm.get_presence_view()
        assert view["pv_dev5"]["last_seen"] == 12345.0

    @pytest.mark.asyncio
    async def test_31_state_is_string(self):
        from core.unified.connection_manager import get_unified_connection_manager
        ucm = get_unified_connection_manager()
        await ucm.register_connection("pv_dev6", _make_websocket())
        view = ucm.get_presence_view()
        assert isinstance(view["pv_dev6"]["state"], str)

    def test_32_empty_when_no_connections(self):
        from core.unified.connection_manager import get_unified_connection_manager
        ucm = get_unified_connection_manager()
        view = ucm.get_presence_view()
        assert view == {}


# ---------------------------------------------------------------------------
# 33–35: GatewayWSManager presence delegation
# ---------------------------------------------------------------------------

class TestGatewayWSManagerPresenceDelegation:
    def test_33_disconnect_calls_ucm_mark_offline(self):
        """disconnect() must call UCM mark_offline (sync) when no event loop running."""
        import galaxy_gateway.websocket_handler  # noqa: F401
        from galaxy_gateway.websocket_handler import GatewayWSManager

        mock_ucm = MagicMock()
        with (
            patch("galaxy_gateway.websocket_handler.udm_write_unregister", return_value=True),
            patch("galaxy_gateway.websocket_handler.device_router"),
            patch.object(GatewayWSManager, "_ucm", return_value=mock_ucm),
        ):
            # Simulate no running loop by making get_running_loop raise
            with patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")):
                mgr = GatewayWSManager()
                mgr.active_connections["conn1"] = MagicMock()
                mgr.device_connections["d_gw"] = "conn1"
                mgr.disconnect("conn1")

        mock_ucm.mark_offline.assert_called_once_with("d_gw")

    @pytest.mark.asyncio
    async def test_34_send_to_device_delegates_to_ucm_on_miss(self):
        """send_to_device falls through to UCM when device not in local connections."""
        from galaxy_gateway.websocket_handler import GatewayWSManager

        mock_ucm = MagicMock()
        mock_ucm.send_to_device = AsyncMock(return_value=True)
        with patch.object(GatewayWSManager, "_ucm", return_value=mock_ucm):
            mgr = GatewayWSManager()
            await mgr.send_to_device("unknown_dev", {"msg": "hello"})

        mock_ucm.send_to_device.assert_called_once_with("unknown_dev", {"msg": "hello"})

    def test_35_is_device_connected_checks_ucm(self):
        """is_device_connected returns True when device is in UCM."""
        from galaxy_gateway.websocket_handler import GatewayWSManager

        mock_ucm = MagicMock()
        mock_ucm.is_device_connected.return_value = True
        with patch.object(GatewayWSManager, "_ucm", return_value=mock_ucm):
            mgr = GatewayWSManager()
            assert mgr.is_device_connected("ucm_only_dev") is True


# ---------------------------------------------------------------------------
# 36–37: RouteConnectionPool pending-response delegation
# ---------------------------------------------------------------------------

class TestRouteConnectionPoolPendingDelegation:
    def test_36_resolve_delegates_to_ucm(self):
        from core.routes._shared import RouteConnectionPool

        mock_ucm = MagicMock()
        with patch.object(RouteConnectionPool, "_unified", return_value=mock_ucm):
            pool = RouteConnectionPool()
            pool.resolve_command_response("cmd_1", {"result": "ok"})

        mock_ucm.resolve_command_response.assert_called_once_with("cmd_1", {"result": "ok"})

    def test_37_local_pending_still_resolved_if_ucm_raises(self):
        from core.routes._shared import RouteConnectionPool
        import asyncio

        mock_ucm = MagicMock()
        mock_ucm.resolve_command_response.side_effect = RuntimeError("ucm down")

        loop = asyncio.new_event_loop()
        try:
            future = loop.create_future()
            with patch.object(RouteConnectionPool, "_unified", return_value=mock_ucm):
                pool = RouteConnectionPool()
                pool._pending_responses["cmd_local"] = future
                pool.resolve_command_response("cmd_local", {"r": 1})

            assert future.done()
            assert future.result() == {"r": 1}
        finally:
            loop.close()


# ---------------------------------------------------------------------------
# 38–40: AndroidBridge UCM routing
# ---------------------------------------------------------------------------

class TestAndroidBridgeUCMRouting:
    def test_38_patch_heartbeat_calls_ucm_update_heartbeat(self):
        mock_ucm = MagicMock()
        with (
            patch("core.unified.connection_manager.get_unified_connection_manager", return_value=mock_ucm),
            # Suppress UDM call (not under test here)
            patch("core.unified.device_manager.UnifiedDeviceManager"),
        ):
            from galaxy_gateway.android_bridge import AndroidBridge
            bridge = AndroidBridge()
            bridge._patch_heartbeat_to_udm("ab_dev1")

        mock_ucm.update_heartbeat.assert_called_once_with("ab_dev1")

    def test_39_patch_disconnect_calls_ucm_mark_offline(self):
        from galaxy_gateway.android_bridge import AndroidBridge
        mock_ucm = MagicMock()
        with (
            patch("core.unified.connection_manager.get_unified_connection_manager", return_value=mock_ucm),
            patch.object(AndroidBridge, "_patch_runtime_state_to_udm"),
        ):
            bridge = AndroidBridge()
            bridge._patch_disconnect_to_udm("ab_dev2")

        mock_ucm.mark_offline.assert_called_once_with("ab_dev2")

    def test_40_patch_reconnect_calls_ucm_update_heartbeat(self):
        from galaxy_gateway.android_bridge import AndroidBridge
        mock_ucm = MagicMock()
        with (
            patch("core.unified.connection_manager.get_unified_connection_manager", return_value=mock_ucm),
            patch.object(AndroidBridge, "_patch_runtime_state_to_udm"),
        ):
            bridge = AndroidBridge()
            bridge._patch_reconnect_to_udm("ab_dev3")

        mock_ucm.update_heartbeat.assert_called_once_with("ab_dev3")


# ---------------------------------------------------------------------------
# 41–42: register/unregister broadcast semantics
# ---------------------------------------------------------------------------

class TestUCMBroadcastSemantics:
    def setup_method(self):
        _reset_ucm()

    @pytest.mark.asyncio
    async def test_41_broadcasts_device_connected_on_register(self):
        from core.unified.connection_manager import get_unified_connection_manager
        ucm = get_unified_connection_manager()
        events = []
        sub_ws = MagicMock()
        sub_ws.send_json = AsyncMock(side_effect=lambda m: events.append(m))
        ucm._status_subscribers.append(sub_ws)
        await ucm.register_connection("bc_dev1", _make_websocket())
        event_types = [e.get("type") for e in events]
        assert "device_connected" in event_types

    @pytest.mark.asyncio
    async def test_42_broadcasts_device_disconnected_on_unregister(self):
        from core.unified.connection_manager import get_unified_connection_manager
        ucm = get_unified_connection_manager()
        await ucm.register_connection("bc_dev2", _make_websocket())
        events = []
        sub_ws = MagicMock()
        sub_ws.send_json = AsyncMock(side_effect=lambda m: events.append(m))
        ucm._status_subscribers.append(sub_ws)
        await ucm.unregister_connection("bc_dev2")
        event_types = [e.get("type") for e in events]
        assert "device_disconnected" in event_types


# ---------------------------------------------------------------------------
# 43–44: send_command_and_wait + resolve round-trip
# ---------------------------------------------------------------------------

class TestUCMCommandRoundTrip:
    def setup_method(self):
        _reset_ucm()

    @pytest.mark.asyncio
    async def test_43_future_resolved_on_matching_response(self):
        from core.unified.connection_manager import get_unified_connection_manager
        ucm = get_unified_connection_manager()
        ws = _make_websocket()
        await ucm.register_connection("cmd_dev", ws)

        # Start the wait in the background
        wait_task = asyncio.create_task(
            ucm.send_command_and_wait("cmd_dev", "ping", {}, timeout=2.0)
        )

        # Give the task a moment to register the future and send
        await asyncio.sleep(0.05)

        # Resolve whichever pending command_id was registered
        assert len(ucm._pending_responses) == 1
        cmd_id = next(iter(ucm._pending_responses))
        ucm.resolve_command_response(cmd_id, {"pong": True})

        result = await wait_task
        assert result.get("pong") is True

    @pytest.mark.asyncio
    async def test_44_returns_error_on_timeout(self):
        from core.unified.connection_manager import get_unified_connection_manager
        ucm = get_unified_connection_manager()
        ws = _make_websocket()
        await ucm.register_connection("timeout_dev", ws)

        result = await ucm.send_command_and_wait("timeout_dev", "slow", {}, timeout=0.05)
        assert "error" in result
        assert "timed out" in result["error"] or "timeout" in result["error"].lower()


# ---------------------------------------------------------------------------
# 45–48: Backward-compatibility
# ---------------------------------------------------------------------------

class TestUCMBackwardCompat:
    def setup_method(self):
        _reset_ucm()

    @pytest.mark.asyncio
    async def test_45_is_device_connected_still_works(self):
        from core.unified.connection_manager import get_unified_connection_manager
        ucm = get_unified_connection_manager()
        ws = _make_websocket()
        await ucm.register_connection("compat_dev", ws)
        assert ucm.is_device_connected("compat_dev") is True
        assert ucm.is_device_connected("not_registered") is False

    @pytest.mark.asyncio
    async def test_46_get_all_devices_includes_ucm_devices(self):
        from core.unified.connection_manager import get_unified_connection_manager
        ucm = get_unified_connection_manager()
        await ucm.register_connection("all_dev", _make_websocket())
        devices = ucm.get_all_devices()
        assert "all_dev" in devices

    @pytest.mark.asyncio
    async def test_47_get_connected_device_ids_reflects_websockets(self):
        from core.unified.connection_manager import get_unified_connection_manager
        ucm = get_unified_connection_manager()
        await ucm.register_connection("ids_dev1", _make_websocket())
        await ucm.register_connection("ids_dev2", _make_websocket())
        ids = ucm.get_connected_device_ids()
        assert "ids_dev1" in ids
        assert "ids_dev2" in ids

    @pytest.mark.asyncio
    async def test_48_get_connection_returns_info_with_new_fields(self):
        from core.unified.connection_manager import get_unified_connection_manager
        ucm = get_unified_connection_manager()
        await ucm.register_connection("info_dev", _make_websocket())
        info = ucm.get_connection("info_dev")
        assert hasattr(info, "last_seen")
        assert hasattr(info, "routable")
        assert info.last_seen > 0.0
        assert info.routable is True
