"""tests/unit/routing/test_device_routing_dispatch_separation.py
=========================================================
PR-4: Device routing and dispatch authority separation.

Coverage
--------
A. Routing package imports and authority sentinels
   1.  All new routing sub-modules are importable.
   2.  Authority sentinels are defined and are strings.
   3.  ``galaxy_gateway.routing`` top-level package re-exports key symbols.
   4.  ``RoutingOrchestrator`` exposes sub-module authority constants.

B. health_policy — device availability / health gating
   5.  ``is_device_available`` returns True when websocket is set.
   6.  ``is_device_available`` returns False when websocket is None.
   7.  ``is_device_online`` returns True for status == "online".
   8.  ``is_device_online`` returns False for status != "online".
   9.  ``is_device_online`` handles enum-style status objects.
   10. ``filter_eligible_devices`` keeps only online devices.
   11. ``filter_eligible_devices`` returns empty list when none are online.

C. policy — command analysis
   12. Android keywords map to DeviceType.ANDROID.
   13. Windows keywords map to DeviceType.WINDOWS.
   14. Tablet keywords map to DeviceType.IOS.
   15. Unknown command maps to DeviceType.UNKNOWN.
   16. Open/launch keywords produce app_control task type.
   17. Click keywords produce ui_automation task type and "click" action.
   18. Input keywords produce ui_automation task type and "input" action.
   19. Query keywords produce query task type and "query" action.
   20. System keywords produce system_control task type.
   21. Cross-device keywords set requires_cross_device=True.
   22. Context exec_mode is passed through to analysis dict.
   23. Context required_capabilities is passed through.
   24. analyze_command is idempotent across calls.

D. device_selection — device eligibility and selection
   25. Empty candidate list returns empty.
   26. All-offline candidates return empty list.
   27. Online device is selected when pool unavailable.
   28. exec_mode filtering selects matching device (local).
   29. exec_mode filtering selects matching device (remote).
   30. Legacy device (no caps) kept as fallback.
   31. DevicePoolManager result is returned when available.
   32. DevicePoolManager exception falls back to first preferred.
   33. Capability registry exception falls back gracefully.

E. dispatch — AIP message construction
   34. ``build_aip_message`` returns correct AIP v3 structure.
   35. ``build_aip_message`` uses provided message_id when given.
   36. ``build_aip_message`` generates message_id when omitted.
   37. ``build_aip_message`` merges payload dict into message payload.
   38. ``build_aip_message`` command appears in payload["command"].

F. dispatch — WebSocket send and wait
   39. ``dispatch_to_websocket`` calls websocket.send.
   40. ``dispatch_to_websocket`` returns success when event is set with result.
   41. ``dispatch_to_websocket`` returns timeout error on timeout.
   42. ``dispatch_to_websocket`` returns send error when send raises.
   43. Event is cleaned up from task_events after success.
   44. Event is cleaned up from task_events after timeout.

G. RoutingOrchestrator — thin wiring layer
   45. ``orchestrator.analyze`` delegates to ``analyze_command``.
   46. ``orchestrator.select`` delegates to ``select_devices``.
   47. ``orchestrator.filter_eligible`` delegates to ``filter_eligible_devices``.
   48. ``orchestrator.is_available`` delegates to ``is_device_available``.
   49. ``orchestrator.is_online`` delegates to ``is_device_online``.
   50. ``orchestrator.build_message`` returns a valid AIP v3 dict.

H. DeviceRouter delegation — behaviour compatibility
   51. ``DeviceRouter._analyze_command`` output matches ``analyze_command``.
   52. ``DeviceRouter._select_devices`` delegates to routing.device_selection.
   53. ``DeviceRouter.send_command_to_device`` builds AIP v3 via dispatch module.
   54. ``DeviceRouter.send_command_to_device`` returns None for unknown device.
   55. ``DeviceRouter.send_command_to_device`` returns error for no websocket.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_device(device_id: str, status: str = "online", websocket=None):
    """Build a minimal Device-like object for tests."""
    device = MagicMock()
    device.device_id = device_id
    device.status = status
    device.websocket = websocket
    device.metadata = {}
    return device


def _make_ws():
    ws = MagicMock()
    ws.send = AsyncMock()
    return ws


# ===========================================================================
# A. Routing package imports and sentinels
# ===========================================================================


class TestRoutingPackageImports:
    """All new routing sub-modules are importable and export sentinels."""

    def test_health_policy_importable(self):
        from galaxy_gateway.routing import health_policy  # noqa: F401

    def test_device_selection_importable(self):
        from galaxy_gateway.routing import device_selection  # noqa: F401

    def test_policy_importable(self):
        from galaxy_gateway.routing import policy  # noqa: F401

    def test_dispatch_importable(self):
        from galaxy_gateway.routing import dispatch  # noqa: F401

    def test_router_importable(self):
        from galaxy_gateway.routing import router  # noqa: F401

    def test_health_policy_authority_sentinel(self):
        from galaxy_gateway.routing.health_policy import DEVICE_HEALTH_POLICY_AUTHORITY
        assert isinstance(DEVICE_HEALTH_POLICY_AUTHORITY, str)
        assert "health_policy" in DEVICE_HEALTH_POLICY_AUTHORITY

    def test_device_selection_authority_sentinel(self):
        from galaxy_gateway.routing.device_selection import DEVICE_SELECTION_AUTHORITY
        assert isinstance(DEVICE_SELECTION_AUTHORITY, str)
        assert "device_selection" in DEVICE_SELECTION_AUTHORITY

    def test_policy_authority_sentinel(self):
        from galaxy_gateway.routing.policy import ROUTING_POLICY_AUTHORITY
        assert isinstance(ROUTING_POLICY_AUTHORITY, str)
        assert "policy" in ROUTING_POLICY_AUTHORITY

    def test_dispatch_authority_sentinel(self):
        from galaxy_gateway.routing.dispatch import DISPATCH_AUTHORITY
        assert isinstance(DISPATCH_AUTHORITY, str)
        assert "dispatch" in DISPATCH_AUTHORITY

    def test_router_orchestration_sentinel(self):
        from galaxy_gateway.routing.router import ROUTING_ORCHESTRATION_AUTHORITY
        assert isinstance(ROUTING_ORCHESTRATION_AUTHORITY, str)
        assert "RoutingOrchestrator" in ROUTING_ORCHESTRATION_AUTHORITY

    def test_top_level_reexports_all_symbols(self):
        import galaxy_gateway.routing as r
        assert hasattr(r, "is_device_available")
        assert hasattr(r, "is_device_online")
        assert hasattr(r, "filter_eligible_devices")
        assert hasattr(r, "select_devices")
        assert hasattr(r, "analyze_command")
        assert hasattr(r, "build_aip_message")
        assert hasattr(r, "dispatch_to_websocket")

    def test_routing_orchestrator_has_authority_constants(self):
        from galaxy_gateway.routing.router import RoutingOrchestrator
        orch = RoutingOrchestrator()
        assert hasattr(orch, "POLICY_AUTHORITY")
        assert hasattr(orch, "SELECTION_AUTHORITY")
        assert hasattr(orch, "HEALTH_AUTHORITY")
        assert hasattr(orch, "DISPATCH_AUTHORITY")


# ===========================================================================
# B. health_policy
# ===========================================================================


class TestHealthPolicy:
    """health_policy module — device availability and health gating."""

    def test_is_device_available_true_with_websocket(self):
        from galaxy_gateway.routing.health_policy import is_device_available
        device = _make_device("d1", websocket=_make_ws())
        assert is_device_available(device) is True

    def test_is_device_available_false_without_websocket(self):
        from galaxy_gateway.routing.health_policy import is_device_available
        device = _make_device("d1", websocket=None)
        assert is_device_available(device) is False

    def test_is_device_online_true_for_online(self):
        from galaxy_gateway.routing.health_policy import is_device_online
        device = _make_device("d1", status="online")
        assert is_device_online(device) is True

    def test_is_device_online_false_for_offline(self):
        from galaxy_gateway.routing.health_policy import is_device_online
        device = _make_device("d1", status="offline")
        assert is_device_online(device) is False

    def test_is_device_online_handles_enum_status(self):
        from galaxy_gateway.routing.health_policy import is_device_online
        device = MagicMock()
        device.status = MagicMock()
        device.status.value = "online"
        assert is_device_online(device) is True

    def test_filter_eligible_devices_keeps_online(self):
        from galaxy_gateway.routing.health_policy import filter_eligible_devices
        devices = [
            _make_device("a", status="online"),
            _make_device("b", status="offline"),
            _make_device("c", status="online"),
        ]
        eligible = filter_eligible_devices(devices)
        assert [d.device_id for d in eligible] == ["a", "c"]

    def test_filter_eligible_devices_empty_when_none_online(self):
        from galaxy_gateway.routing.health_policy import filter_eligible_devices
        devices = [_make_device("x", status="offline"), _make_device("y", status="unknown")]
        assert filter_eligible_devices(devices) == []


# ===========================================================================
# C. policy — command analysis
# ===========================================================================


class TestRoutingPolicy:
    """policy module — analyze_command produces correct analysis dicts."""

    def _analyze(self, command: str, context=None):
        from galaxy_gateway.routing.policy import analyze_command
        return analyze_command(command, context)

    def test_android_keyword_maps_to_android(self):
        from core.device_types import DeviceType
        a = self._analyze("打开手机相册")
        assert a["target_device_type"] == DeviceType.ANDROID

    def test_windows_keyword_maps_to_windows(self):
        from core.device_types import DeviceType
        a = self._analyze("打开电脑文件")
        assert a["target_device_type"] == DeviceType.WINDOWS

    def test_tablet_keyword_maps_to_ios(self):
        from core.device_types import DeviceType
        a = self._analyze("在平板上查看文档")
        assert a["target_device_type"] == DeviceType.IOS

    def test_unknown_command_maps_to_unknown(self):
        from core.device_types import DeviceType
        a = self._analyze("do something")
        assert a["target_device_type"] == DeviceType.UNKNOWN

    def test_launch_keyword_gives_app_control(self):
        a = self._analyze("打开微信")
        assert a["task_type"] == "app_control"
        assert "open" in a["actions"]

    def test_click_keyword_gives_ui_automation(self):
        a = self._analyze("点击确认按钮")
        assert a["task_type"] == "ui_automation"
        assert "click" in a["actions"]

    def test_input_keyword_gives_ui_automation_with_input_action(self):
        a = self._analyze("输入用户名")
        assert a["task_type"] == "ui_automation"
        assert "input" in a["actions"]

    def test_query_keyword_gives_query_type(self):
        a = self._analyze("查看天气")
        assert a["task_type"] == "query"
        assert "query" in a["actions"]

    def test_system_keyword_gives_system_control(self):
        a = self._analyze("调节音量")
        assert a["task_type"] == "system_control"

    def test_cross_device_keyword_sets_flag(self):
        a = self._analyze("发送到手机")
        assert a["requires_cross_device"] is True

    def test_context_exec_mode_passed_through(self):
        a = self._analyze("打开app", context={"exec_mode": "remote"})
        assert a["exec_mode"] == "remote"

    def test_context_required_capabilities_passed_through(self):
        a = self._analyze("截图", context={"required_capabilities": ["screen"]})
        assert a["required_capabilities"] == ["screen"]

    def test_analyze_command_idempotent(self):
        a1 = self._analyze("点击按钮")
        a2 = self._analyze("点击按钮")
        assert a1["task_type"] == a2["task_type"]
        assert a1["actions"] == a2["actions"]


# ===========================================================================
# D. device_selection
# ===========================================================================


class TestDeviceSelection:
    """device_selection.select_devices — eligibility and selection logic."""

    def test_empty_candidates_returns_empty(self):
        from galaxy_gateway.routing.device_selection import select_devices
        analysis = {"exec_mode": None, "actions": [], "requires_cross_device": False,
                    "task_role": None, "required_capabilities": [], "target_device_type": "android"}
        assert select_devices(analysis, []) == []

    def test_online_device_selected_when_pool_unavailable(self):
        from galaxy_gateway.routing.device_selection import select_devices

        candidates = [_make_device("d1", status="online")]
        analysis = {"exec_mode": None, "actions": [], "requires_cross_device": False,
                    "task_role": None, "required_capabilities": [], "target_device_type": "android"}

        with patch("galaxy_gateway.routing.device_selection.get_gateway_capability_projection_view",
                   side_effect=Exception("registry unavailable")):
            with patch("galaxy_gateway.routing.device_selection.get_device_pool_manager",
                       side_effect=Exception("pool unavailable")):
                result = select_devices(analysis, candidates)

        assert len(result) == 1
        assert result[0].device_id == "d1"

    def test_exec_mode_local_selects_local_device(self):
        from galaxy_gateway.routing.device_selection import select_devices
        from galaxy_gateway.capability_registry import GatewayCapabilityRegistry, ExecMode

        dev_local = _make_device("dev-local", status="online")
        dev_remote = _make_device("dev-remote", status="online")

        reg = GatewayCapabilityRegistry()
        reg.upsert("dev-local", "click", {"exec_mode": "local"})
        reg.upsert("dev-remote", "click", {"exec_mode": "remote"})

        analysis = {"exec_mode": "local", "actions": ["click"],
                    "requires_cross_device": False, "task_role": None,
                    "required_capabilities": [], "target_device_type": "android"}

        with patch("galaxy_gateway.routing.device_selection.get_gateway_capability_projection_view",
                   return_value=reg):
            with patch("galaxy_gateway.autonomous_filter.filter_autonomous_devices",
                       side_effect=lambda devs, **kw: [d for d in devs if d.status == "online"]):
                with patch("galaxy_gateway.routing.device_selection.get_device_pool_manager",
                           side_effect=Exception("pool unavailable")):
                    result = select_devices(analysis, [dev_local, dev_remote])

        assert len(result) == 1
        assert result[0].device_id == "dev-local"

    def test_exec_mode_remote_selects_remote_device(self):
        from galaxy_gateway.routing.device_selection import select_devices
        from galaxy_gateway.capability_registry import GatewayCapabilityRegistry

        dev_local = _make_device("dev-local", status="online")
        dev_remote = _make_device("dev-remote", status="online")

        reg = GatewayCapabilityRegistry()
        reg.upsert("dev-local", "tap", {"exec_mode": "local"})
        reg.upsert("dev-remote", "tap", {"exec_mode": "remote"})

        analysis = {"exec_mode": "remote", "actions": ["tap"],
                    "requires_cross_device": False, "task_role": None,
                    "required_capabilities": [], "target_device_type": "android"}

        with patch("galaxy_gateway.routing.device_selection.get_gateway_capability_projection_view",
                   return_value=reg):
            with patch("galaxy_gateway.autonomous_filter.filter_autonomous_devices",
                       side_effect=lambda devs, **kw: [d for d in devs if d.status == "online"]):
                with patch("galaxy_gateway.routing.device_selection.get_device_pool_manager",
                           side_effect=Exception("pool unavailable")):
                    result = select_devices(analysis, [dev_local, dev_remote])

        assert len(result) == 1
        assert result[0].device_id == "dev-remote"

    def test_legacy_device_kept_as_fallback_when_no_caps(self):
        from galaxy_gateway.routing.device_selection import select_devices
        from galaxy_gateway.capability_registry import GatewayCapabilityRegistry

        dev_legacy = _make_device("dev-legacy", status="online")
        reg = GatewayCapabilityRegistry()
        # dev-legacy has no capability_report entries at all

        analysis = {"exec_mode": "local", "actions": ["tap"],
                    "requires_cross_device": False, "task_role": None,
                    "required_capabilities": [], "target_device_type": "android"}

        with patch("galaxy_gateway.routing.device_selection.get_gateway_capability_projection_view",
                   return_value=reg):
            with patch("galaxy_gateway.autonomous_filter.filter_autonomous_devices",
                       side_effect=lambda devs, **kw: [d for d in devs if d.status == "online"]):
                with patch("galaxy_gateway.routing.device_selection.get_device_pool_manager",
                           side_effect=Exception("pool unavailable")):
                    result = select_devices(analysis, [dev_legacy])

        assert len(result) == 1
        assert result[0].device_id == "dev-legacy"

    def test_pool_manager_result_used_when_available(self):
        from galaxy_gateway.routing.device_selection import select_devices

        dev_a = _make_device("dev-a", status="online")
        dev_b = _make_device("dev-b", status="online")

        mock_pool = MagicMock()
        mock_pool.select_device.return_value = "dev-b"

        analysis = {"exec_mode": None, "actions": [], "requires_cross_device": False,
                    "task_role": None, "required_capabilities": [], "target_device_type": "android"}

        with patch("galaxy_gateway.routing.device_selection.get_gateway_capability_projection_view",
                   side_effect=Exception("skip")):
            with patch("galaxy_gateway.autonomous_filter.filter_autonomous_devices",
                       side_effect=lambda devs, **kw: [d for d in devs if d.status == "online"]):
                with patch("galaxy_gateway.routing.device_selection.get_device_pool_manager",
                           return_value=mock_pool):
                    result = select_devices(analysis, [dev_a, dev_b])

        assert len(result) == 1
        assert result[0].device_id == "dev-b"

    def test_pool_exception_falls_back_to_first_preferred(self):
        from galaxy_gateway.routing.device_selection import select_devices

        dev_a = _make_device("dev-a", status="online")
        dev_b = _make_device("dev-b", status="online")

        analysis = {"exec_mode": None, "actions": [], "requires_cross_device": False,
                    "task_role": None, "required_capabilities": [], "target_device_type": "android"}

        with patch("galaxy_gateway.routing.device_selection.get_gateway_capability_projection_view",
                   side_effect=Exception("skip")):
            with patch("galaxy_gateway.autonomous_filter.filter_autonomous_devices",
                       side_effect=lambda devs, **kw: [d for d in devs if d.status == "online"]):
                with patch("galaxy_gateway.routing.device_selection.get_device_pool_manager",
                           side_effect=Exception("pool error")):
                    result = select_devices(analysis, [dev_a, dev_b])

        assert len(result) == 1
        assert result[0].device_id == "dev-a"


# ===========================================================================
# E. dispatch — AIP message construction
# ===========================================================================


class TestBuildAipMessage:
    """dispatch.build_aip_message constructs correct AIP v3 envelopes."""

    def _build(self, **kwargs):
        from galaxy_gateway.routing.dispatch import build_aip_message
        defaults = {
            "device_id": "dev-1",
            "task_id": "task-123",
            "trace_id": "trace-456",
            "command": "click",
        }
        defaults.update(kwargs)
        return build_aip_message(**defaults)

    def test_version_is_3_0(self):
        msg = self._build()
        assert msg["version"] == "3.0"

    def test_type_is_command(self):
        msg = self._build()
        assert msg["type"] == "command"

    def test_device_id_in_message(self):
        msg = self._build(device_id="my-device")
        assert msg["device_id"] == "my-device"

    def test_task_id_in_message(self):
        msg = self._build(task_id="t-999")
        assert msg["task_id"] == "t-999"

    def test_trace_id_in_message(self):
        msg = self._build(trace_id="tr-abc")
        assert msg["trace_id"] == "tr-abc"

    def test_command_in_payload(self):
        msg = self._build(command="swipe")
        assert msg["payload"]["command"] == "swipe"

    def test_explicit_message_id_used(self):
        msg = self._build(message_id="explicit-id")
        assert msg["message_id"] == "explicit-id"

    def test_message_id_generated_when_omitted(self):
        msg = self._build()
        assert msg["message_id"]  # non-empty

    def test_payload_dict_merged(self):
        msg = self._build(payload={"x": 10, "y": 20})
        assert msg["payload"]["x"] == 10
        assert msg["payload"]["y"] == 20

    def test_timestamp_present(self):
        msg = self._build()
        assert "timestamp" in msg
        assert msg["timestamp"].endswith("Z")


# ===========================================================================
# F. dispatch — WebSocket send and wait
# ===========================================================================


class TestDispatchToWebsocket:
    """dispatch.dispatch_to_websocket — send and result-wait mechanics."""

    def _make_message(self, task_id="t-1", device_id="dev-1", trace_id="tr-1"):
        return {
            "version": "3.0",
            "device_id": device_id,
            "task_id": task_id,
            "trace_id": trace_id,
            "payload": {"command": "click"},
        }

    def test_send_is_called(self):
        from galaxy_gateway.routing.dispatch import dispatch_to_websocket
        ws = _make_ws()
        device = _make_device("d1", websocket=ws)
        task_events: Dict = {}
        task_results: Dict = {}
        msg = self._make_message()

        async def _run():
            # Set the event quickly so the wait doesn't block
            async def _set_event():
                await asyncio.sleep(0.01)
                if "t-1" in task_events:
                    task_results["t-1"] = {"success": True, "result": "ok"}
                    task_events["t-1"].set()
            asyncio.create_task(_set_event())
            return await dispatch_to_websocket(device, msg, "t-1", task_events, task_results, timeout=1.0)

        result = asyncio.run(_run())
        ws.send.assert_called_once()

    def test_returns_success_when_result_event_set(self):
        from galaxy_gateway.routing.dispatch import dispatch_to_websocket
        ws = _make_ws()
        device = _make_device("d1", websocket=ws)
        task_events: Dict = {}
        task_results: Dict = {}

        async def _run():
            async def _set_event():
                await asyncio.sleep(0.01)
                task_results["t-1"] = {"success": True, "result": "done"}
                task_events["t-1"].set()
            asyncio.create_task(_set_event())
            return await dispatch_to_websocket(
                device, self._make_message(), "t-1", task_events, task_results, timeout=1.0
            )

        result = asyncio.run(_run())
        assert result["success"] is True

    def test_returns_timeout_error_on_timeout(self):
        from galaxy_gateway.routing.dispatch import dispatch_to_websocket
        ws = _make_ws()
        device = _make_device("d1", websocket=ws)
        task_events: Dict = {}
        task_results: Dict = {}

        async def _run():
            return await dispatch_to_websocket(
                device, self._make_message(), "t-timeout", task_events, task_results, timeout=0.05
            )

        result = asyncio.run(_run())
        assert result["success"] is False
        assert result["error"] == "timeout"

    def test_returns_send_error_when_websocket_send_raises(self):
        from galaxy_gateway.routing.dispatch import dispatch_to_websocket
        ws = MagicMock()
        ws.send = AsyncMock(side_effect=Exception("connection closed"))
        device = _make_device("d1", websocket=ws)
        task_events: Dict = {}
        task_results: Dict = {}

        async def _run():
            return await dispatch_to_websocket(
                device, self._make_message(), "t-err", task_events, task_results, timeout=1.0
            )

        result = asyncio.run(_run())
        assert result["success"] is False
        assert "connection closed" in result["error"]

    def test_task_event_cleaned_up_on_success(self):
        from galaxy_gateway.routing.dispatch import dispatch_to_websocket
        ws = _make_ws()
        device = _make_device("d1", websocket=ws)
        task_events: Dict = {}
        task_results: Dict = {}

        async def _run():
            async def _set_event():
                await asyncio.sleep(0.01)
                task_results["t-1"] = {"success": True}
                task_events["t-1"].set()
            asyncio.create_task(_set_event())
            return await dispatch_to_websocket(
                device, self._make_message(), "t-1", task_events, task_results, timeout=1.0
            )

        asyncio.run(_run())
        assert "t-1" not in task_events

    def test_task_event_cleaned_up_on_timeout(self):
        from galaxy_gateway.routing.dispatch import dispatch_to_websocket
        ws = _make_ws()
        device = _make_device("d1", websocket=ws)
        task_events: Dict = {}
        task_results: Dict = {}

        async def _run():
            return await dispatch_to_websocket(
                device, self._make_message("t-cleanup"), "t-cleanup", task_events, task_results, timeout=0.05
            )

        asyncio.run(_run())
        assert "t-cleanup" not in task_events


# ===========================================================================
# G. RoutingOrchestrator — thin wiring layer
# ===========================================================================


class TestRoutingOrchestrator:
    """RoutingOrchestrator delegates to the correct sub-module functions."""

    def test_analyze_delegates_to_analyze_command(self):
        from galaxy_gateway.routing.router import RoutingOrchestrator
        from core.device_types import DeviceType
        orch = RoutingOrchestrator()
        analysis = orch.analyze("打开手机应用")
        assert analysis["target_device_type"] == DeviceType.ANDROID

    def test_select_delegates_to_select_devices(self):
        from galaxy_gateway.routing.router import RoutingOrchestrator
        orch = RoutingOrchestrator()
        candidates = [_make_device("d1", status="online")]
        analysis = {"exec_mode": None, "actions": [], "requires_cross_device": False,
                    "task_role": None, "required_capabilities": [], "target_device_type": "android"}
        with patch("galaxy_gateway.routing.device_selection.get_gateway_capability_projection_view",
                   side_effect=Exception("skip")):
            with patch("galaxy_gateway.routing.device_selection.get_device_pool_manager",
                       side_effect=Exception("skip")):
                result = orch.select(analysis, candidates)
        assert result[0].device_id == "d1"

    def test_filter_eligible_delegates_to_filter(self):
        from galaxy_gateway.routing.router import RoutingOrchestrator
        orch = RoutingOrchestrator()
        devices = [_make_device("a", "online"), _make_device("b", "offline")]
        result = orch.filter_eligible(devices)
        assert len(result) == 1 and result[0].device_id == "a"

    def test_is_available_delegates(self):
        from galaxy_gateway.routing.router import RoutingOrchestrator
        orch = RoutingOrchestrator()
        assert orch.is_available(_make_device("d", websocket=_make_ws())) is True
        assert orch.is_available(_make_device("d", websocket=None)) is False

    def test_is_online_delegates(self):
        from galaxy_gateway.routing.router import RoutingOrchestrator
        orch = RoutingOrchestrator()
        assert orch.is_online(_make_device("d", status="online")) is True
        assert orch.is_online(_make_device("d", status="offline")) is False

    def test_build_message_returns_aip_v3(self):
        from galaxy_gateway.routing.router import RoutingOrchestrator
        orch = RoutingOrchestrator()
        msg = orch.build_message("dev-1", "t-1", "tr-1", "click")
        assert msg["version"] == "3.0"
        assert msg["type"] == "command"
        assert msg["payload"]["command"] == "click"


# ===========================================================================
# H. DeviceRouter delegation — behaviour compatibility
# ===========================================================================


class TestDeviceRouterDelegation:
    """DeviceRouter delegates to routing sub-modules but maintains same API."""

    def _fresh_router(self):
        try:
            from core.unified import device_manager as _udm_mod
            _udm_mod.UnifiedDeviceManager._instance = None
        except Exception:
            pass
        from galaxy_gateway.device_router import DeviceRouter
        return DeviceRouter()

    def test_analyze_command_output_matches_routing_policy(self):
        from galaxy_gateway.routing.policy import analyze_command
        from core.device_types import DeviceType
        router = self._fresh_router()
        cmd = "打开手机微信"
        # _analyze_command is async in DeviceRouter but analyze_command is sync
        dr_result = asyncio.run(router._analyze_command(cmd))
        rc_result = analyze_command(cmd)
        assert dr_result["target_device_type"] == rc_result["target_device_type"]
        assert dr_result["task_type"] == rc_result["task_type"]

    def test_select_devices_delegates_to_routing_module(self):
        from galaxy_gateway.routing.device_selection import select_devices
        from galaxy_gateway.device_router import Device, DeviceRouter
        from core.device_types import DeviceType

        router = self._fresh_router()
        device = Device("dev-sel", "android_phone", [])
        device.status = "online"
        router.devices["dev-sel"] = device

        analysis = {
            "target_device_type": DeviceType.ANDROID,
            "exec_mode": None,
            "actions": [],
            "requires_cross_device": False,
            "task_role": None,
            "required_capabilities": [],
        }
        with patch("galaxy_gateway.routing.device_selection.get_gateway_capability_projection_view",
                   side_effect=Exception("skip")):
            with patch("galaxy_gateway.routing.device_selection.get_device_pool_manager",
                       side_effect=Exception("skip")):
                result = router._select_devices(analysis)

        assert len(result) == 1
        assert result[0].device_id == "dev-sel"

    def test_send_command_returns_none_for_unknown_device(self):
        router = self._fresh_router()

        async def _run():
            return await router.send_command_to_device(
                "nonexistent-device", "click", {}
            )

        result = asyncio.run(_run())
        assert result is None

    def test_send_command_returns_error_for_no_websocket(self):
        from galaxy_gateway.device_router import Device
        router = self._fresh_router()
        device = Device("dev-nows", "android_phone", [])
        device.websocket = None
        router.devices["dev-nows"] = device

        async def _run():
            return await router.send_command_to_device(
                "dev-nows", "click", {}
            )

        result = asyncio.run(_run())
        assert result is not None
        assert result["success"] is False
        assert "websocket" in result["error"].lower() or "active" in result["error"].lower()

    def test_send_command_uses_dispatch_module_for_aip_message(self):
        """Verify send_command_to_device calls routing.dispatch.build_aip_message."""
        from galaxy_gateway.device_router import Device

        router = self._fresh_router()
        ws = _make_ws()
        device = Device("dev-ws", "android_phone", [])
        device.websocket = ws
        router.devices["dev-ws"] = device

        captured_messages: list = []

        async def _run():
            # Set result immediately so the wait resolves
            async def _set():
                await asyncio.sleep(0.01)
                for task_id, ev in list(router._task_events.items()):
                    router.task_results[task_id] = {"success": True}
                    ev.set()
            asyncio.create_task(_set())
            return await router.send_command_to_device("dev-ws", "click", {"x": 1}, timeout=0.5)

        # Patch at the device_router module level (where it's imported as _routing_build_aip_message)
        import galaxy_gateway.device_router as _dr_mod
        original = _dr_mod._routing_build_aip_message

        def _capturing_build(**kwargs):
            msg = original(**kwargs)
            captured_messages.append(msg)
            return msg

        with patch.object(_dr_mod, "_routing_build_aip_message", side_effect=_capturing_build):
            asyncio.run(_run())

        assert len(captured_messages) >= 1
        assert captured_messages[0]["version"] == "3.0"
        assert captured_messages[0]["payload"]["command"] == "click"
