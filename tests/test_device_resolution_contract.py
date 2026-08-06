"""
tests/test_device_resolution_contract.py
========================================
PR-DEVICE-RESOLUTION: Contract tests for the Unified Node Contract v1.

Covers:
    - schemas/node_contract.py: request/response model validation
    - schemas/node_errors.py: error code consistency
    - launcher/launcher_adapter.py: 4-mode feature flag behavior

Run: python -m unittest tests.test_device_resolution_contract -v
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from typing import Any, Dict

# ---------------------------------------------------------------------------
# 1. node_contract.py — model validation
# ---------------------------------------------------------------------------


class TestUnifiedResponse(unittest.TestCase):
    def test_success_response(self):
        from schemas.node_contract import UnifiedResponse

        r = UnifiedResponse(success=True, data={"key": "value"}, node="Node_33_ADB")
        self.assertTrue(r.success)
        self.assertEqual(r.data, {"key": "value"})
        self.assertEqual(r.node, "Node_33_ADB")
        self.assertIsNone(r.duration_ms)

    def test_error_response_with_data(self):
        from schemas.node_contract import UnifiedResponse

        r = UnifiedResponse(success=False, data={"error": "something"}, node="Node_38_BLE")
        self.assertFalse(r.success)
        self.assertEqual(r.node, "Node_38_BLE")

    def test_serialization_roundtrip(self):
        from schemas.node_contract import UnifiedResponse

        r = UnifiedResponse(success=True, data={"x": 1}, node="Node_41_MQTT", duration_ms=12.5)
        raw = r.model_dump_json()
        restored = UnifiedResponse.model_validate_json(raw)
        self.assertTrue(restored.success)
        self.assertEqual(restored.data, {"x": 1})
        self.assertEqual(restored.duration_ms, 12.5)


class TestInvokeRequest(unittest.TestCase):
    def test_minimal(self):
        from schemas.node_contract import InvokeRequest

        req = InvokeRequest(action="click")
        self.assertEqual(req.action, "click")
        self.assertEqual(req.params, {})
        self.assertEqual(req.timeout_ms, 10_000)

    def test_full(self):
        from schemas.node_contract import InvokeRequest

        req = InvokeRequest(
            action="screenshot",
            params={"quality": 90},
            timeout_ms=5_000,
            correlation_id="abc-123",
        )
        self.assertEqual(req.action, "screenshot")
        self.assertEqual(req.params["quality"], 90)
        self.assertEqual(req.timeout_ms, 5_000)
        self.assertEqual(req.correlation_id, "abc-123")

    def test_timeout_bounds_low(self):
        from schemas.node_contract import InvokeRequest

        with self.assertRaises(Exception):
            InvokeRequest(action="x", timeout_ms=50)

    def test_timeout_bounds_high(self):
        from schemas.node_contract import InvokeRequest

        with self.assertRaises(Exception):
            InvokeRequest(action="x", timeout_ms=400_000)


class TestConnectRequest(unittest.TestCase):
    def test_basic(self):
        from schemas.node_contract import ConnectRequest

        req = ConnectRequest(target="192.168.1.5:5555")
        self.assertEqual(req.target, "192.168.1.5:5555")
        self.assertEqual(req.params, {})

    def test_with_params(self):
        from schemas.node_contract import ConnectRequest

        req = ConnectRequest(target="/dev/ttyUSB0", params={"baudrate": 115200})
        self.assertEqual(req.params["baudrate"], 115200)


class TestNodeMetadata(unittest.TestCase):
    def test_basic(self):
        from schemas.node_contract import NodeMetadata

        m = NodeMetadata(
            node_name="Node_33_ADB",
            transport="adb",
            capabilities=["GUI_READ", "GUI_WRITE"],
            actions=["execute", "devices"],
        )
        self.assertEqual(m.node_name, "Node_33_ADB")
        self.assertEqual(m.version, "1.0.0")
        self.assertEqual(m.transport, "adb")

    def test_serialization(self):
        from schemas.node_contract import NodeMetadata

        m = NodeMetadata(node_name="Node_38_BLE", transport="ble")
        raw = m.model_dump_json()
        restored = NodeMetadata.model_validate_json(raw)
        self.assertEqual(restored.node_name, "Node_38_BLE")


# ---------------------------------------------------------------------------
# 2. node_errors.py — error code consistency
# ---------------------------------------------------------------------------


class TestNodeErrorCode(unittest.TestCase):
    def test_all_codes_unique(self):
        from schemas.node_errors import NodeErrorCode

        codes = list(NodeErrorCode)
        values = [c.value for c in codes]
        self.assertEqual(len(values), len(set(values)), "Duplicate error code values")

    def test_count(self):
        from schemas.node_errors import NodeErrorCode

        self.assertEqual(len(NodeErrorCode), 14)


class TestNodeErrorResponse(unittest.TestCase):
    def test_basic(self):
        from schemas.node_errors import NodeErrorCode, NodeErrorResponse

        e = NodeErrorResponse.from_exception(NodeErrorCode.TIMEOUT, "timed out", node="Node_33_ADB", action="execute")
        self.assertFalse(e.success)
        self.assertEqual(e.code, NodeErrorCode.TIMEOUT)
        self.assertFalse(e.retryable)

    def test_timeout_factory(self):
        from schemas.node_errors import NodeErrorResponse

        e = NodeErrorResponse.timeout(action="click", timeout_ms=5000, node="Node_45_DesktopAuto")
        self.assertEqual(e.code.value, "TIMEOUT")
        self.assertTrue(e.retryable)
        self.assertEqual(e.node, "Node_45_DesktopAuto")

    def test_unsupported_action_factory(self):
        from schemas.node_errors import NodeErrorResponse

        e = NodeErrorResponse.unsupported_action(action="fly", node="Node_33_ADB", supported=["execute", "devices"])
        self.assertEqual(e.code.value, "UNSUPPORTED_ACTION")
        self.assertIn("fly", e.detail)

    def test_serialization_roundtrip(self):
        from schemas.node_errors import NodeErrorCode, NodeErrorResponse

        e = NodeErrorResponse.from_exception(NodeErrorCode.NODE_UNAVAILABLE, "down", node="Node_48_Serial")
        raw = e.model_dump_json()
        restored = NodeErrorResponse.model_validate_json(raw)
        self.assertEqual(restored.code, NodeErrorCode.NODE_UNAVAILABLE)


# ---------------------------------------------------------------------------
# 3. Facade action registration — all 11 facades
# ---------------------------------------------------------------------------


class TestFacadeActionRegistry(unittest.TestCase):
    EXPECTED = {
        "Node_33_ADB": ["execute", "devices", "shell", "install", "screenshot"],
        "Node_38_BLE": ["connect", "disconnect", "scan", "read", "write"],
        "Node_41_MQTT": ["connect", "disconnect", "publish", "subscribe"],
        "Node_45_DesktopAuto": ["click", "double_click", "type", "hotkey", "move", "scroll", "press"],
        "Node_48_Serial": ["connect", "disconnect", "send", "read"],
        "Node_34_Scrcpy": ["screenshot", "tap", "swipe", "input_text", "key_event"],
        "Node_42_CANbus": ["connect", "disconnect", "send_frame", "read_frame"],
        "Node_44_NFC": ["read_tag", "write_tag", "scan"],
        "Node_46_Camera": ["capture", "record_start", "record_stop", "get_frame"],
        "Node_47_Audio": ["record_start", "record_stop", "play", "play_stop"],
        "Node_49_OctoPrint": ["get_status", "start_print", "cancel_print", "home_axes", "jog"],
    }

    def test_all_facades(self):
        from schemas.node_contract import NodeActionRouter

        for node_name, expected_actions in self.EXPECTED.items():
            with self.subTest(node=node_name):
                router = NodeActionRouter(node_name)
                for action in expected_actions:
                    router.register(action, lambda p, t: {})
                self.assertEqual(sorted(router.supported_actions()), sorted(expected_actions))

    def test_duplicate_registration_overwrites(self):
        from schemas.node_contract import NodeActionRouter

        router = NodeActionRouter("TestNode")
        router.register("scan", lambda p, t: {"v": 1})
        router.register("scan", lambda p, t: {"v": 2})
        self.assertEqual(len(router.supported_actions()), 1)

    def test_unsupported_action_returns_error(self):
        from schemas.node_contract import InvokeRequest, NodeActionRouter

        router = NodeActionRouter("TestNode")
        router.register("scan", lambda p, t: {"found": True})
        req = InvokeRequest(action="fly")
        result = asyncio.run(router.handle(req))
        self.assertFalse(result.success)
        self.assertIn("error", result.data or {})


# ---------------------------------------------------------------------------
# 4. launcher_adapter.py — 4-mode behavior
# ---------------------------------------------------------------------------


class TestLauncherAdapterModes(unittest.TestCase):
    def test_default_mode(self):
        from launcher.launcher_adapter import AdapterMode

        self.assertEqual(AdapterMode.OBSERVE_ONLY.value, "observe_only")
        self.assertEqual(AdapterMode.DRY_RUN.value, "dry_run")
        self.assertEqual(AdapterMode.ALLOWLIST.value, "allowlist")
        self.assertEqual(AdapterMode.FULL.value, "full")

    def test_mode_from_env(self):
        from launcher.launcher_adapter import AdapterMode, LauncherAdapter

        os.environ["LAUNCHER_ADAPTER_MODE"] = "dry_run"
        try:
            mode = LauncherAdapter._detect_mode()
            self.assertEqual(mode, AdapterMode.DRY_RUN)
        finally:
            del os.environ["LAUNCHER_ADAPTER_MODE"]

    def test_invalid_env_fallback(self):
        """环境变量写错时退回**默认**模式。

        原来断言的是 ``OBSERVE_ONLY`` —— 那时 observe_only 就是默认，所以这条测的
        其实一直是"退回默认"（方法名 ``fallback`` 也是这个意思），而不是"必须退到
        最保守的那一档"。默认改成 ``full`` 之后仍然按同一条语义断言。

        为什么不能继续写死 observe_only：那样一个**拼错的环境变量**会把按需激活
        整个静默关掉，而日志只说 "Invalid ...，using observe_only" —— 没人会把
        "节点都不自动起了"和"我环境变量拼错了"联系起来。真要关它，写对了名字明确
        关（``LAUNCHER_ADAPTER_MODE=observe_only``），那是显式决定。
        """
        from launcher.launcher_adapter import LauncherAdapter

        os.environ["LAUNCHER_ADAPTER_MODE"] = "garbage"
        try:
            mode = LauncherAdapter._detect_mode()
            self.assertEqual(mode, LauncherAdapter.DEFAULT_MODE)
        finally:
            del os.environ["LAUNCHER_ADAPTER_MODE"]

    def test_allowlist_parsing(self):
        from launcher.launcher_adapter import LauncherAdapter

        os.environ["LAUNCHER_ADAPTER_ALLOWLIST"] = "Node_33_ADB,Node_38_BLE"
        try:
            wl = LauncherAdapter._load_allowlist()
            self.assertIn("Node_33_ADB", wl)
            self.assertIn("Node_38_BLE", wl)
        finally:
            del os.environ["LAUNCHER_ADAPTER_ALLOWLIST"]

    def test_observe_only_blocks_start(self):
        from launcher.launcher_adapter import AdapterMode, LauncherAdapter

        class FakeDecision:
            should_start = True
            reason = "test"
            policy = type("P", (), {"value": "on_demand"})()

        adapter = LauncherAdapter(None, mode=AdapterMode.OBSERVE_ONLY)
        result = asyncio.run(
            adapter._maybe_start_node(
                node_name="Node_33_ADB", device_type="android_phone", transport=None, decision=FakeDecision()
            )
        )
        self.assertIsNone(result)

    def test_dry_run_returns_without_starting(self):
        from launcher.launcher_adapter import AdapterMode, LauncherAdapter

        class FakeDecision:
            should_start = True
            reason = "test"
            policy = type("P", (), {"value": "on_demand"})()

        adapter = LauncherAdapter(None, mode=AdapterMode.DRY_RUN)
        result = asyncio.run(
            adapter._maybe_start_node(
                node_name="Node_33_ADB", device_type="android_phone", transport=None, decision=FakeDecision()
            )
        )
        self.assertEqual(result, "Node_33_ADB")

    def test_allowlist_blocks_unlisted(self):
        from launcher.launcher_adapter import AdapterMode, LauncherAdapter

        class FakeDecision:
            should_start = True
            reason = "test"
            policy = type("P", (), {"value": "on_demand"})()

        adapter = LauncherAdapter(None, mode=AdapterMode.ALLOWLIST)
        adapter.allowlist = {"Node_38_BLE"}
        result = asyncio.run(
            adapter._maybe_start_node(
                node_name="Node_33_ADB", device_type="android_phone", transport=None, decision=FakeDecision()
            )
        )
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# 5. Integration: end-to-end resolve + policy (no I/O)
# ---------------------------------------------------------------------------


class TestResolutionEndToEnd(unittest.TestCase):
    def test_resolve_android_phone(self):
        from core.device_node_resolver import get_resolver

        resolver = get_resolver()
        result = resolver.resolve(device_type="android_phone")
        self.assertIsNotNone(result)
        self.assertEqual(result.match_type, "device_type")
        self.assertEqual(result.implementation.node, "Node_33_ADB")
        self.assertEqual(result.implementation.port, 8033)
        self.assertEqual(result.implementation.startup, "on_demand")

    def test_unimplemented_transports_resolve_to_nothing(self):
        """BLE / MQTT / CAN / 串口现在**解析不到节点** —— 因为它们确实没有实现。

        这条原来断言 ``transport="ble"`` 解析到 ``Node_38_BLE``。而
        ``nodes/Node_38_BLE/`` **从来没有存在过** —— 它和 41_MQTT / 42_CANbus /
        48_Serial / 37_LinuxDBus 是同一批"设计好了、实现没跟上"的物理总线节点。

        以前留着那几条映射不痛不痒：解析出来也没人拿去启动。**按需激活接通之后
        就变有害了**：一台 BLE 设备注册进来会解析到 Node_38_BLE 并真的去启动它，
        而那个目录不存在——启动失败，日志里多一条谁也看不懂的告警，设备侧只知道
        "没能力"。让一条本来就不成立的规则去驱动真实动作，比没有规则更糟。

        所以映射被移除了。现在的行为是解析不到、日志明说
        "no mapping for transport=ble" —— 那是**准确**的。真把节点做出来了，
        把规则加回 registry/device_node_map.yaml，这条测试也随之改回去。
        """
        from core.device_node_resolver import get_resolver

        resolver = get_resolver()
        for transport in ("ble", "mqtt", "can", "serial"):
            self.assertIsNone(
                resolver.resolve(transport=transport),
                f"{transport} 解析到了节点 —— 但它对应的节点目录并不存在",
            )

    def test_resolve_camera_by_capability(self):
        from core.device_node_resolver import get_resolver

        resolver = get_resolver()
        result = resolver.resolve(capabilities=["SENSOR_CAMERA"])
        self.assertIsNotNone(result)
        self.assertEqual(result.implementation.node, "Node_46_Camera")

    def test_unresolved_returns_none(self):
        from core.device_node_resolver import get_resolver

        resolver = get_resolver()
        result = resolver.resolve(device_type="nonexistent_xyz")
        self.assertIsNone(result)

    def test_list_supported_device_types(self):
        from core.device_node_resolver import get_resolver

        resolver = get_resolver()
        types = resolver.list_supported_device_types()
        self.assertIn("android_phone", types)
        self.assertIn("windows_desktop", types)
        self.assertIn("linux_desktop", types)

    def test_list_supported_transports(self):
        """ "支持的传输"必须只列**真的有实现**的那些。

        原来断言里面有 ble / mqtt —— 那两个对应的节点目录并不存在（见
        ``test_unimplemented_transports_resolve_to_nothing``）。一份把没实现的东西
        也列成"支持"的清单，比没有清单更误导：调用方据此以为能用。
        """
        from core.device_node_resolver import get_resolver

        resolver = get_resolver()
        transports = resolver.list_supported_transports()

        self.assertIn("adb", transports)
        for unimplemented in ("ble", "mqtt", "can", "serial"):
            self.assertNotIn(
                unimplemented,
                transports,
                f"{unimplemented} 被列为受支持，但它对应的节点目录并不存在",
            )


# ---------------------------------------------------------------------------
# 6. Feature flag governance
# ---------------------------------------------------------------------------


class TestFeatureFlagsDocumented(unittest.TestCase):
    def test_adapter_mode_env_var(self):
        with open("launcher/launcher_adapter.py") as f:
            src = f.read()
        self.assertIn("LAUNCHER_ADAPTER_MODE", src)
        self.assertIn("observe_only", src)
        self.assertIn("dry_run", src)

    def test_adapter_allowlist_env_var(self):
        with open("launcher/launcher_adapter.py") as f:
            src = f.read()
        self.assertIn("LAUNCHER_ADAPTER_ALLOWLIST", src)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
