"""
galaxy_gateway/android/capabilities.py — Device capability flag definitions.

Extracted from android_bridge.py as part of PR-3 modularization.
Provides the ``DeviceCapability`` bitmask class, aligned with AIPMessageV3.kt.
"""

from typing import List


class DeviceCapability:
    NONE = 0

    # 基础能力
    NETWORK = 1 << 0
    STORAGE = 1 << 1
    COMPUTE = 1 << 2

    # GUI 能力
    GUI_READ = 1 << 3
    GUI_WRITE = 1 << 4
    GUI_SCREENSHOT = 1 << 5
    GUI_STREAM = 1 << 6

    # 输入能力
    INPUT_TOUCH = 1 << 7
    INPUT_KEYBOARD = 1 << 8
    INPUT_MOUSE = 1 << 9
    INPUT_VOICE = 1 << 10

    # 传感器
    SENSOR_GPS = 1 << 11
    SENSOR_CAMERA = 1 << 12
    SENSOR_MIC = 1 << 13
    SENSOR_MOTION = 1 << 14

    # 系统能力
    SYSTEM_SHELL = 1 << 15
    SYSTEM_ROOT = 1 << 16
    SYSTEM_INSTALL = 1 << 17
    SYSTEM_NOTIFICATION = 1 << 18

    # 通信能力
    COMM_BLUETOOTH = 1 << 19
    COMM_NFC = 1 << 20
    COMM_WIFI_DIRECT = 1 << 21

    @classmethod
    def get_android_default(cls) -> int:
        """获取 Android 设备的默认能力"""
        return (cls.NETWORK | cls.STORAGE | cls.COMPUTE |
                cls.GUI_READ | cls.GUI_WRITE | cls.GUI_SCREENSHOT |
                cls.INPUT_TOUCH | cls.INPUT_VOICE |
                cls.SENSOR_GPS | cls.SENSOR_CAMERA | cls.SENSOR_MIC | cls.SENSOR_MOTION |
                cls.SYSTEM_NOTIFICATION |
                cls.COMM_BLUETOOTH | cls.COMM_NFC | cls.COMM_WIFI_DIRECT)

    @classmethod
    def has_capability(cls, capabilities: int, capability: int) -> bool:
        """检查是否具有某个能力"""
        return (capabilities & capability) != 0

    @classmethod
    def to_list(cls, capabilities: int) -> List[str]:
        """将能力标志转换为列表"""
        result = []
        capability_map = {
            cls.NETWORK: "network",
            cls.STORAGE: "storage",
            cls.COMPUTE: "compute",
            cls.GUI_READ: "gui_read",
            cls.GUI_WRITE: "gui_write",
            cls.GUI_SCREENSHOT: "gui_screenshot",
            cls.GUI_STREAM: "gui_stream",
            cls.INPUT_TOUCH: "input_touch",
            cls.INPUT_KEYBOARD: "input_keyboard",
            cls.INPUT_MOUSE: "input_mouse",
            cls.INPUT_VOICE: "input_voice",
            cls.SENSOR_GPS: "sensor_gps",
            cls.SENSOR_CAMERA: "sensor_camera",
            cls.SENSOR_MIC: "sensor_mic",
            cls.SENSOR_MOTION: "sensor_motion",
            cls.SYSTEM_SHELL: "system_shell",
            cls.SYSTEM_ROOT: "system_root",
            cls.SYSTEM_INSTALL: "system_install",
            cls.SYSTEM_NOTIFICATION: "system_notification",
            cls.COMM_BLUETOOTH: "comm_bluetooth",
            cls.COMM_NFC: "comm_nfc",
            cls.COMM_WIFI_DIRECT: "comm_wifi_direct",
        }
        for cap, name in capability_map.items():
            if cls.has_capability(capabilities, cap):
                result.append(name)
        return result
