"""
UFO Galaxy - 统一设备类型定义（单一事实来源）
=============================================

所有模块必须从此文件导入设备类型，不得自行定义。

层次结构：
  DeviceType (简化大类) ← core 层 + gateway 路由使用
  AIPDeviceType (细分类型) ← AIP v3.0 协议使用
  DevicePlatform (平台大类) ← 路由决策使用

映射关系：
  DeviceType.ANDROID ↔ AIPDeviceType.ANDROID_PHONE / ANDROID_TABLET / ...
  DeviceType.WINDOWS ↔ AIPDeviceType.WINDOWS_DESKTOP / WINDOWS_LAPTOP / ...
"""

from enum import Enum
from typing import List, Optional

# 从 AIP v3.0 重导出细分类型（协议层使用）
from galaxy_gateway.protocol.aip_v3 import (
    DeviceType as AIPDeviceType,
    DevicePlatform,
    DeviceCapability as AIPDeviceCapability,
)


# ============================================================================
# 简化设备类型（core 层 + 路由层统一使用）
# ============================================================================

class DeviceType(str, Enum):
    """设备类型大类 — 所有模块统一使用

    包含平台类型和专用设备类型，覆盖 Galaxy-Nexus 星枢的
    全部设备节点场景（手机/电脑/无人机/3D打印机/机器人等）。
    """
    # ── 平台类型 ──
    ANDROID = "android"
    IOS = "ios"
    WINDOWS = "windows"
    MACOS = "macos"
    LINUX = "linux"
    BROWSER = "browser"
    CLOUD = "cloud"
    # ── 专用设备类型 ──
    DRONE = "drone"
    PRINTER_3D = "printer_3d"
    ROBOT = "robot"
    CAMERA = "camera"
    SENSOR = "sensor"
    ACTUATOR = "actuator"
    DISPLAY = "display"
    SPEAKER = "speaker"
    IOT = "iot"
    EMBEDDED = "embedded"
    # ── 通信/接口类设备 ──
    AUDIO = "audio"
    SERIAL = "serial"
    BLE = "ble"
    NFC = "nfc"
    CANBUS = "canbus"
    # ── 通用 ──
    CUSTOM = "custom"
    UNKNOWN = "unknown"


class DeviceStatus(str, Enum):
    """设备状态"""
    OFFLINE = "offline"
    ONLINE = "online"
    BUSY = "busy"
    ERROR = "error"
    UNKNOWN = "unknown"


# ============================================================================
# 映射表：简化类型 ↔ AIP v3.0 细分类型
# ============================================================================

DEVICE_TYPE_TO_AIP: dict[DeviceType, list[AIPDeviceType]] = {
    DeviceType.ANDROID: [
        AIPDeviceType.ANDROID_PHONE,
        AIPDeviceType.ANDROID_TABLET,
        AIPDeviceType.ANDROID_TV,
        AIPDeviceType.ANDROID_CAR,
        AIPDeviceType.ANDROID_WEAR,
    ],
    DeviceType.IOS: [
        AIPDeviceType.IOS_PHONE,
        AIPDeviceType.IOS_TABLET,
        AIPDeviceType.IOS_WATCH,
    ],
    DeviceType.WINDOWS: [
        AIPDeviceType.WINDOWS_DESKTOP,
        AIPDeviceType.WINDOWS_LAPTOP,
        AIPDeviceType.WINDOWS_WSL,
    ],
    DeviceType.MACOS: [
        AIPDeviceType.MACOS_DESKTOP,
        AIPDeviceType.MACOS_LAPTOP,
    ],
    DeviceType.LINUX: [
        AIPDeviceType.LINUX_DESKTOP,
        AIPDeviceType.LINUX_SERVER,
        AIPDeviceType.LINUX_RASPBERRY,
    ],
    DeviceType.IOT: [
        AIPDeviceType.EMBEDDED_ESP32,
        AIPDeviceType.EMBEDDED_ARDUINO,
        AIPDeviceType.IOT_GENERIC,
    ],
    DeviceType.CLOUD: [
        AIPDeviceType.CLOUD_HUAWEI,
        AIPDeviceType.CLOUD_ALIYUN,
        AIPDeviceType.CLOUD_TENCENT,
        AIPDeviceType.CLOUD_AWS,
        AIPDeviceType.CLOUD_AZURE,
    ],
}

# 反向映射：AIP v3.0 细分类型 → 简化大类
_AIP_TO_DEVICE_TYPE: dict[str, DeviceType] = {}
for _dt, _aip_list in DEVICE_TYPE_TO_AIP.items():
    for _aip in _aip_list:
        _AIP_TO_DEVICE_TYPE[_aip.value] = _dt

# 前缀映射（兼容不带后缀的字符串）
_PREFIX_TO_DEVICE_TYPE: dict[str, DeviceType] = {
    "android": DeviceType.ANDROID,
    "ios": DeviceType.IOS,
    "windows": DeviceType.WINDOWS,
    "macos": DeviceType.MACOS,
    "linux": DeviceType.LINUX,
    "cloud": DeviceType.CLOUD,
    "embedded": DeviceType.EMBEDDED,
    "iot": DeviceType.IOT,
    "web": DeviceType.BROWSER,
    "browser": DeviceType.BROWSER,
    "drone": DeviceType.DRONE,
    "printer": DeviceType.PRINTER_3D,
    "robot": DeviceType.ROBOT,
    "camera": DeviceType.CAMERA,
    "sensor": DeviceType.SENSOR,
    "actuator": DeviceType.ACTUATOR,
    "display": DeviceType.DISPLAY,
    "speaker": DeviceType.SPEAKER,
    "container": DeviceType.CUSTOM,
    "virtual": DeviceType.CUSTOM,
}


def resolve_device_type(raw: str) -> DeviceType:
    """将任意设备类型字符串解析为统一的 DeviceType。

    支持：
      - 精确匹配 DeviceType 值 ("android", "windows")
      - AIP v3 细分类型 ("android_phone", "windows_desktop")
      - 前缀匹配 ("android_xxx" → ANDROID)

    >>> resolve_device_type("android_phone")
    <DeviceType.ANDROID: 'android'>
    >>> resolve_device_type("windows")
    <DeviceType.WINDOWS: 'windows'>
    """
    if not raw:
        return DeviceType.UNKNOWN

    raw_lower = raw.lower().strip()

    # 1. 精确匹配简化类型
    try:
        return DeviceType(raw_lower)
    except ValueError:
        pass

    # 2. AIP v3 细分类型
    if raw_lower in _AIP_TO_DEVICE_TYPE:
        return _AIP_TO_DEVICE_TYPE[raw_lower]

    # 3. 前缀匹配
    prefix = raw_lower.split("_")[0]
    if prefix in _PREFIX_TO_DEVICE_TYPE:
        return _PREFIX_TO_DEVICE_TYPE[prefix]

    return DeviceType.CUSTOM


def device_type_to_platform(device_type: DeviceType) -> DevicePlatform:
    """将简化 DeviceType 映射为 AIP DevicePlatform。"""
    _map = {
        DeviceType.ANDROID: DevicePlatform.ANDROID,
        DeviceType.IOS: DevicePlatform.IOS,
        DeviceType.WINDOWS: DevicePlatform.WINDOWS,
        DeviceType.MACOS: DevicePlatform.MACOS,
        DeviceType.LINUX: DevicePlatform.LINUX,
        DeviceType.IOT: DevicePlatform.EMBEDDED,
        DeviceType.CLOUD: DevicePlatform.CLOUD,
    }
    return _map.get(device_type, DevicePlatform.UNKNOWN)
