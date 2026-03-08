"""core/device_types.py 的单元测试 — 统一设备类型解析和映射"""

import pytest

from core.device_types import (
    DeviceType,
    DeviceStatus,
    resolve_device_type,
    device_type_to_platform,
    DEVICE_TYPE_TO_AIP,
)


class TestResolveDeviceType:
    """resolve_device_type() 应将任意字符串解析为统一 DeviceType"""

    def test_exact_match(self):
        assert resolve_device_type("android") == DeviceType.ANDROID
        assert resolve_device_type("windows") == DeviceType.WINDOWS
        assert resolve_device_type("ios") == DeviceType.IOS
        assert resolve_device_type("linux") == DeviceType.LINUX

    def test_aip_v3_fine_grained(self):
        assert resolve_device_type("android_phone") == DeviceType.ANDROID
        assert resolve_device_type("android_tablet") == DeviceType.ANDROID
        assert resolve_device_type("windows_desktop") == DeviceType.WINDOWS
        assert resolve_device_type("linux_server") == DeviceType.LINUX
        assert resolve_device_type("ios_phone") == DeviceType.IOS
        assert resolve_device_type("macos_laptop") == DeviceType.MACOS
        assert resolve_device_type("cloud_aws") == DeviceType.CLOUD

    def test_prefix_match(self):
        assert resolve_device_type("android_unknown_future") == DeviceType.ANDROID
        assert resolve_device_type("ios_future_device") == DeviceType.IOS
        assert resolve_device_type("embedded_new") == DeviceType.IOT

    def test_case_insensitive(self):
        assert resolve_device_type("ANDROID") == DeviceType.ANDROID
        assert resolve_device_type("Windows") == DeviceType.WINDOWS
        assert resolve_device_type("IOS_Phone") == DeviceType.IOS

    def test_empty_returns_unknown(self):
        assert resolve_device_type("") == DeviceType.UNKNOWN

    def test_none_like_returns_unknown(self):
        assert resolve_device_type("") == DeviceType.UNKNOWN

    def test_unrecognized_returns_custom(self):
        assert resolve_device_type("totally_new_device") == DeviceType.CUSTOM

    def test_whitespace_stripped(self):
        assert resolve_device_type("  android  ") == DeviceType.ANDROID


class TestMappingCompleteness:
    """DEVICE_TYPE_TO_AIP 映射表应覆盖所有主要设备类型"""

    def test_major_types_mapped(self):
        for dt in [DeviceType.ANDROID, DeviceType.IOS, DeviceType.WINDOWS,
                   DeviceType.MACOS, DeviceType.LINUX, DeviceType.IOT, DeviceType.CLOUD]:
            assert dt in DEVICE_TYPE_TO_AIP, f"{dt} missing from DEVICE_TYPE_TO_AIP"
            assert len(DEVICE_TYPE_TO_AIP[dt]) > 0

    def test_reverse_mapping_consistent(self):
        """每个 AIP 细分类型应能反向解析回对应的简化类型"""
        for dt, aip_types in DEVICE_TYPE_TO_AIP.items():
            for aip_type in aip_types:
                resolved = resolve_device_type(aip_type.value)
                assert resolved == dt, (
                    f"{aip_type.value} resolved to {resolved}, expected {dt}"
                )


class TestDeviceTypeToPlatform:
    """device_type_to_platform() 应正确映射"""

    def test_known_platforms(self):
        from galaxy_gateway.protocol.aip_v3 import DevicePlatform
        assert device_type_to_platform(DeviceType.ANDROID) == DevicePlatform.ANDROID
        assert device_type_to_platform(DeviceType.WINDOWS) == DevicePlatform.WINDOWS
        assert device_type_to_platform(DeviceType.IOS) == DevicePlatform.IOS
        assert device_type_to_platform(DeviceType.LINUX) == DevicePlatform.LINUX

    def test_unknown_returns_unknown_platform(self):
        from galaxy_gateway.protocol.aip_v3 import DevicePlatform
        assert device_type_to_platform(DeviceType.BROWSER) == DevicePlatform.UNKNOWN


class TestDeviceStatusEnum:
    """DeviceStatus 枚举应包含所有必要状态"""

    def test_basic_statuses(self):
        assert DeviceStatus.ONLINE.value == "online"
        assert DeviceStatus.OFFLINE.value == "offline"
        assert DeviceStatus.BUSY.value == "busy"
        assert DeviceStatus.ERROR.value == "error"
