"""统一词汇:真实设备从真实登记路径进来,能不能被认出来、解析到驱动。

背景:细分类型在进 UDM 时被截断(android_phone → android 甚至 unknown),而驱动映射表
按细分类型建表 —— 真实注册的设备一台都解析不到驱动。这里每条用例都走真实登记入口,
再用真实的解析器 + 真实的 registry/device_node_map.yaml 验证。
"""

from __future__ import annotations

import asyncio

import pytest

from core.device_onboarding import taxonomy as tx


@pytest.fixture
def udm():
    from core.unified.device_manager import get_unified_device_manager, reset_unified_device_manager

    reset_unified_device_manager()
    yield get_unified_device_manager()
    reset_unified_device_manager()


# ── 与协议逐项一致(core 不能 import galaxy_gateway,所以词表是一份副本,这里钉住它) ──


def test_aip_device_types_match_the_protocol():
    from galaxy_gateway.protocol.aip_v3 import AIPDeviceType

    assert {t.value for t in AIPDeviceType} == set(tx.AIP_DEVICE_TYPES)


def test_capability_classes_match_the_protocol():
    from galaxy_gateway.protocol.aip_v3 import DeviceCapability

    names = {c.name for c in DeviceCapability if c.name and c.name != "NONE"}
    assert names == set(tx.AIP_CAPABILITY_CLASSES)
    assert not (tx.HOME_CAPABILITY_CLASSES & tx.AIP_CAPABILITY_CLASSES)


# ── 真实世界里的写法 ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,platform,fine,ff",
    [
        ("Android_Agent", "android", "android_phone", "phone"),  # 手机 App 的 WS 注册
        ("android", "android", "android_phone", "phone"),  # 手机 AuthMessage
        ("android_phone", "android", "android_phone", "phone"),
        ("wearos", "android", "android_wear", "watch"),  # 手表配对
        ("windows", "windows", "windows_desktop", "desktop"),
        ("linux_raspberry", "linux", "linux_raspberry", "embedded"),
        ("iot", "iot", "iot_generic", "embedded"),
        ("printer_3d", "printer_3d", "iot_generic", "embedded"),  # 粗类保留;细分归 iot_generic(映射到 OctoPrint)
        ("something-new", "unknown", "unknown", "unknown"),
    ],
)
def test_real_world_type_strings(raw, platform, fine, ff):
    info = tx.classify_type(raw)
    assert (info.platform, info.aip_device_type, info.form_factor) == (platform, fine, ff)


def test_capabilities_become_classes_and_unknown_words_are_not_guessed():
    assert tx.capability_classes(["gui_read", "tap", "GUI_SCREENSHOT", "wiggle"]) == [
        "GUI_READ",
        "GUI_SCREENSHOT",
        "GUI_WRITE",
        "INPUT_TOUCH",
    ]
    assert tx.capability_classes(["turn_on"], ha_domain="light") == ["HOME_LIGHT", "HOME_POWER"]


def test_only_subjects_can_initiate():
    assert tx.can_initiate(tx.FULL_RUNTIME_HOST)
    for m in (tx.PARTIAL_RUNTIME_DEVICE, tx.ADAPTER_BRIDGED_DEVICE, tx.OBSERVER_TELEMETRY_DEVICE):
        assert not tx.can_initiate(m)


# ── 真实登记路径 → 真实解析器 ─────────────────────────────────────────────


def _resolve(device):
    from core.device_node_resolver import get_resolver

    m = get_resolver().resolve(
        device_type=device.aip_device_type,
        transport=device.transport or None,
        capabilities=device.capability_classes,
    )
    return m.implementation.node if m else None


def test_ws_router_registration_keeps_the_fine_type(udm):
    # galaxy_gateway/device_router.py → udm.register_device_from_dict(原始类型串)
    d = udm.register_device_from_dict("p1", {"device_type": "android_phone", "capabilities": ["gui_read", "tap"]})
    assert d.device_type == "android"  # 以前:unknown
    assert d.aip_device_type == "android_phone"
    assert d.execution_model == tx.FULL_RUNTIME_HOST
    assert _resolve(d) == "Node_33_ADB"  # 没有 App 的安卓设备由 ADB 驱动


def test_gateway_ssot_registration_keeps_the_fine_type(udm):
    from galaxy_gateway.ssot import udm_write_register

    assert udm_write_register("p2", "我的手机", "Android_Agent", ["gui_read"], {})
    d = udm.get_device("p2")
    assert (d.device_type, d.aip_device_type) == ("android", "android_phone")


def test_desktop_resolves_to_desktop_automation(udm):
    d = udm.register_device_from_dict("pc", {"device_type": "windows"})
    assert _resolve(d) == "Node_45_DesktopAuto"


def test_home_assistant_entity_is_a_bridged_device_served_by_node_27(udm):
    from core.ha_bridge import HABridge

    bridge = HABridge(url="http://192.168.1.20:8123", token="t")
    assert bridge._mirror_entity(
        {"entity_id": "light.living", "state": "on", "attributes": {"friendly_name": "客厅灯"}}
    )
    d = udm.get_device("ha_light.living")
    assert d.transport == "home_assistant"
    assert d.bridge_id == "ha:192.168.1.20:8123"
    assert d.execution_model == tx.ADAPTER_BRIDGED_DEVICE
    assert d.capability_classes == ["HOME_LIGHT", "HOME_POWER"]
    assert _resolve(d) == "Node_27_SmartHome"


def test_replacing_capabilities_recomputes_the_classes(udm):
    udm.register_device_from_dict("x", {"device_type": "android", "capabilities": ["tap"]})
    d = udm.upsert_device_state("x", {"capabilities": ["screenshot"]})
    assert d.capability_classes == ["GUI_SCREENSHOT"]  # 撤掉的 tap 不再挂着


# ── 解析平面 hook ─────────────────────────────────────────────────────────


def test_hook_resolves_on_the_fine_type():
    from core.udm_registration_hook import UDMRegistrationHook
    from core.unified.models import UnifiedDevice

    d = tx.normalize_device(UnifiedDevice(device_id="pc2", device_type="windows"))
    out = asyncio.run(UDMRegistrationHook().on_device_registered(d, source="test"))
    assert out and out["resolved_node"] == "Node_45_DesktopAuto"


def test_hook_does_not_start_a_driver_for_a_device_running_our_app():
    """开着 App、经 WS 连上来的手机自己讲 AIP;再去拉 ADB 节点是错的。"""
    from core.udm_registration_hook import UDMRegistrationHook
    from core.unified.models import UnifiedDevice

    d = tx.normalize_device(UnifiedDevice(device_id="p3", device_type="android", transport="websocket"))
    out = asyncio.run(UDMRegistrationHook().on_device_registered(d, source="test"))
    assert out == {"device_id": "p3", "native": True, "transport": "websocket", "resolved_node": None}


def test_resolver_matches_capabilities_case_insensitively():
    from core.device_node_resolver import get_resolver

    m = get_resolver().resolve(capabilities=["sensor_camera"])
    assert m and m.implementation.node == "Node_46_Camera"


# ── 唯一对外读契约 ────────────────────────────────────────────────────────


def test_read_contract_carries_fine_type_role_and_bridge(udm):
    from contracts.registered_runtime_device import from_udm_device

    d = udm.register_device_from_dict(
        "h1",
        {"device_type": "iot", "bridge_id": "ha:h:8123", "transport": "home_assistant", "capabilities": ["turn_on"]},
    )
    r = from_udm_device(d)
    assert r.device_type == "iot_generic"
    assert r.device_execution_model == "adapter_bridged_device"
    assert r.participant_identity.bridge_id == "ha:h:8123"
    assert r.participant_identity.attached_via_adapter is True
