"""core/device_onboarding/taxonomy.py — 设备的统一词汇:类型、能力、角色。

为什么要有这一层
================
设备从很多地方进来(手机 WS、手表配对、HA 桥、mDNS、edge worker……),每个来源各说各的:

* 类型:手机报 ``Android_Agent`` / ``android``,手表报 ``wearos``,AIP v3 规范值是
  ``android_phone`` / ``android_wear``;UDM 的 :class:`UnifiedDeviceType` 只有粗类
  ``android``。以前各登记路径各自把原值塞进粗类枚举,塞不进就退成 ``android`` 甚至
  ``unknown`` —— 细分类型就此丢失,而驱动映射表(``registry/device_node_map.yaml``)
  恰恰按细分类型建表。结果是**真实注册的设备一台都解析不到驱动**。
* 能力:手机报 ``gui_read`` / ``tap``,映射表写 ``GUI_READ``,HA 桥报 ``turn_on``。

这里给出唯一一份对照,``UnifiedDeviceManager.register_device`` 入口处统一调用 ——
不要求每个调用方记得做。

三件事
======
1. :func:`classify_type` —— 任意原始类型串 → (粗类 platform, AIP 细分类型, 形态)。
2. :func:`capability_classes` —— 任意能力串 → 归一的能力类(AIP v3 ``DeviceCapability``
   全部名字 + 本仓侧的 ``HOME_*`` 执行器类)。原始能力串**原样保留**在
   ``UnifiedDevice.capabilities`` 里,下行派发仍用它。
3. :func:`execution_model_for` —— 设备在系统里的角色,取值沿用
   ``contracts/registered_runtime_device.RuntimeDeviceExecutionModel``,不另立枚举。

同义词表是声明式的:认识一种新设备 = 在表里加几个词,不改逻辑。

``core/`` 不能依赖 ``galaxy_gateway/``,所以 AIP 细分类型在这里以字符串集合出现;
``tests/test_device_onboarding_taxonomy.py`` 钉住它与 ``AIPDeviceType`` 逐项一致。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional

# ── AIP v3 细分设备类型(与 galaxy_gateway/protocol/aip_v3.AIPDeviceType 逐项一致)──────
AIP_DEVICE_TYPES = frozenset(
    {
        "android_phone",
        "android_tablet",
        "android_tv",
        "android_car",
        "android_wear",
        "ios_phone",
        "ios_tablet",
        "ios_watch",
        "windows_desktop",
        "windows_laptop",
        "windows_wsl",
        "macos_desktop",
        "macos_laptop",
        "linux_desktop",
        "linux_server",
        "linux_raspberry",
        "cloud_huawei",
        "cloud_aliyun",
        "cloud_tencent",
        "cloud_aws",
        "cloud_azure",
        "embedded_esp32",
        "embedded_arduino",
        "iot_generic",
        "container_docker",
        "virtual_vm",
        "unknown",
    }
)

#: 原始类型串(小写、去掉非字母数字)→ AIP 细分类型。只列"不是 AIP 规范值本身"的写法。
_TYPE_SYNONYMS: Dict[str, str] = {
    # 手机
    "android": "android_phone",
    "androidagent": "android_phone",
    "androidphone": "android_phone",
    "phone": "android_phone",
    "mobile": "android_phone",
    "ios": "ios_phone",
    "iphone": "ios_phone",
    "ipad": "ios_tablet",
    # 手表
    "wearos": "android_wear",
    "wear": "android_wear",
    "watch": "android_wear",
    "androidwatch": "android_wear",
    "applewatch": "ios_watch",
    # 电视、车机
    "tv": "android_tv",
    "androidtv": "android_tv",
    "car": "android_car",
    # 桌面
    "windows": "windows_desktop",
    "win": "windows_desktop",
    "desktop": "windows_desktop",
    "laptop": "windows_laptop",
    "wsl": "windows_wsl",
    "macos": "macos_desktop",
    "mac": "macos_desktop",
    "darwin": "macos_desktop",
    "macbook": "macos_laptop",
    "linux": "linux_desktop",
    "server": "linux_server",
    "raspberrypi": "linux_raspberry",
    "raspberry": "linux_raspberry",
    "rpi": "linux_raspberry",
    # 云与虚拟
    "cloud": "virtual_vm",
    "vm": "virtual_vm",
    "docker": "container_docker",
    "container": "container_docker",
    # 嵌入式与被接入设备
    "esp32": "embedded_esp32",
    "arduino": "embedded_arduino",
    "embedded": "embedded_esp32",
    "iot": "iot_generic",
    "smarthome": "iot_generic",
    "homeassistant": "iot_generic",
    "matter": "iot_generic",
    "printer3d": "iot_generic",
    "camera": "iot_generic",
    "drone": "iot_generic",
    "robot": "iot_generic",
}

#: AIP 细分类型的前缀 → UDM 粗类(``UnifiedDeviceType`` 的值)。
_PLATFORM_BY_PREFIX = (
    ("android_", "android"),
    ("ios_", "ios"),
    ("windows_", "windows"),
    ("macos_", "macos"),
    ("linux_", "linux"),
    ("cloud_", "cloud"),
    ("virtual_", "cloud"),
    ("container_", "cloud"),
    ("embedded_", "iot"),
    ("iot_", "iot"),
)

#: 已知粗类:调用方给的就是粗类时直接保留(比如 ``printer_3d`` 这种 AIP 细分类型里没有的)。
_UNIFIED_TYPES = frozenset(
    {"android", "ios", "windows", "macos", "linux", "browser", "cloud", "drone", "printer_3d", "robot", "camera", "iot"}
)

_FORM_FACTOR: Dict[str, str] = {
    "android_phone": "phone",
    "ios_phone": "phone",
    "android_tablet": "tablet",
    "ios_tablet": "tablet",
    "android_wear": "watch",
    "ios_watch": "watch",
    "android_tv": "tv",
    "android_car": "embedded",
    "windows_desktop": "desktop",
    "macos_desktop": "desktop",
    "linux_desktop": "desktop",
    "windows_laptop": "laptop",
    "macos_laptop": "laptop",
    "windows_wsl": "virtual",
    "linux_server": "server",
    "linux_raspberry": "embedded",
    "embedded_esp32": "embedded",
    "embedded_arduino": "embedded",
    "iot_generic": "embedded",
    "container_docker": "virtual",
    "virtual_vm": "virtual",
}


def _squash(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


@dataclass(frozen=True)
class TypeInfo:
    """一台设备的类型三件套。"""

    platform: str  # UnifiedDeviceType 的值(粗类)
    aip_device_type: str  # AIP v3 细分类型
    form_factor: str


def classify_type(raw: Any, *, hints: Optional[Mapping[str, Any]] = None) -> TypeInfo:
    """任意原始类型串 → :class:`TypeInfo`。

    ``hints`` 里若带 ``aip_device_type`` / ``form_factor`` / ``platform``,优先用它们
    (来源比这里的推断知道得多)。认不出来时细分类型是 ``unknown``,粗类是 ``unknown``
    —— 不猜。
    """
    h = dict(hints or {})
    aip = str(h.get("aip_device_type") or "").strip().lower()
    if aip not in AIP_DEVICE_TYPES:
        aip = ""

    raw_s = str(raw or "").strip().lower()
    if not aip:
        if raw_s in AIP_DEVICE_TYPES:
            aip = raw_s
        else:
            aip = _TYPE_SYNONYMS.get(_squash(raw_s), "")
    if not aip:
        # 手表常把形态放在 form_factor / platform 里
        ff_hint = _squash(h.get("form_factor"))
        plat_hint = _squash(h.get("platform"))
        if ff_hint == "watch" and plat_hint in ("android", "wearos", ""):
            aip = "android_wear"
        elif plat_hint:
            aip = _TYPE_SYNONYMS.get(plat_hint, "")
    if not aip:
        aip = "unknown"

    platform = "unknown"
    for prefix, plat in _PLATFORM_BY_PREFIX:
        if aip.startswith(prefix):
            platform = plat
            break
    if raw_s in _UNIFIED_TYPES and (platform == "unknown" or raw_s in ("printer_3d", "drone", "robot", "camera")):
        platform = raw_s

    form_factor = str(h.get("form_factor") or "").strip().lower() or _FORM_FACTOR.get(aip, "unknown")
    return TypeInfo(platform=platform, aip_device_type=aip, form_factor=form_factor)


# ── 能力类 ─────────────────────────────────────────────────────────────────────────

#: AIP v3 ``DeviceCapability`` 的全部名字(与 galaxy_gateway/protocol/aip_v3.py 逐项一致)。
AIP_CAPABILITY_CLASSES = frozenset(
    {
        "NETWORK",
        "STORAGE",
        "COMPUTE",
        "GUI_READ",
        "GUI_WRITE",
        "GUI_SCREENSHOT",
        "GUI_STREAM",
        "INPUT_TOUCH",
        "INPUT_KEYBOARD",
        "INPUT_MOUSE",
        "INPUT_VOICE",
        "SENSOR_GPS",
        "SENSOR_CAMERA",
        "SENSOR_MIC",
        "SENSOR_MOTION",
        "SYSTEM_SHELL",
        "SYSTEM_ROOT",
        "SYSTEM_INSTALL",
        "SYSTEM_NOTIFICATION",
        "COMM_BLUETOOTH",
        "COMM_NFC",
        "COMM_WIFI_DIRECT",
    }
)

#: 被接入设备的执行器类。AIP 位图里没有(那需要三仓同步改);被接入设备不跑在手机/手表上,不受影响。
HOME_CAPABILITY_CLASSES = frozenset(
    {
        "HOME_POWER",
        "HOME_LIGHT",
        "HOME_CLIMATE",
        "HOME_COVER",
        "HOME_LOCK",
        "HOME_MEDIA",
        "HOME_SENSOR",
        "HOME_SCENE",
        "HOME_VACUUM",
    }
)

ALL_CAPABILITY_CLASSES = AIP_CAPABILITY_CLASSES | HOME_CAPABILITY_CLASSES

#: 原始能力串(小写、去非字母数字)→ 能力类。一个词可以对应多个类。
_CAPABILITY_SYNONYMS: Dict[str, tuple] = {
    # GUI
    "screenread": ("GUI_READ",),
    "readscreen": ("GUI_READ",),
    "uitree": ("GUI_READ",),
    "accessibility": ("GUI_READ", "GUI_WRITE"),
    "a11y": ("GUI_READ", "GUI_WRITE"),
    "tap": ("GUI_WRITE", "INPUT_TOUCH"),
    "click": ("GUI_WRITE",),
    "swipe": ("GUI_WRITE", "INPUT_TOUCH"),
    "scroll": ("GUI_WRITE",),
    "longpress": ("GUI_WRITE", "INPUT_TOUCH"),
    "type": ("GUI_WRITE", "INPUT_KEYBOARD"),
    "input": ("GUI_WRITE", "INPUT_KEYBOARD"),
    "inputtext": ("GUI_WRITE", "INPUT_KEYBOARD"),
    "openapp": ("GUI_WRITE",),
    "screenshot": ("GUI_SCREENSHOT",),
    "capturescreen": ("GUI_SCREENSHOT",),
    "screencapture": ("GUI_SCREENSHOT",),
    "stream": ("GUI_STREAM",),
    "screenstream": ("GUI_STREAM",),
    "screenmirror": ("GUI_STREAM",),
    # 输入
    "touch": ("INPUT_TOUCH",),
    "keyboard": ("INPUT_KEYBOARD",),
    "keyevent": ("INPUT_KEYBOARD",),
    "mouse": ("INPUT_MOUSE",),
    "voice": ("INPUT_VOICE",),
    "asr": ("INPUT_VOICE",),
    "speech": ("INPUT_VOICE",),
    # 传感器
    "gps": ("SENSOR_GPS",),
    "location": ("SENSOR_GPS",),
    "camera": ("SENSOR_CAMERA",),
    "microphone": ("SENSOR_MIC",),
    "mic": ("SENSOR_MIC",),
    "audiocapture": ("SENSOR_MIC",),
    "motion": ("SENSOR_MOTION",),
    "accelerometer": ("SENSOR_MOTION",),
    # 系统
    "shell": ("SYSTEM_SHELL",),
    "exec": ("SYSTEM_SHELL",),
    "command": ("SYSTEM_SHELL",),
    "root": ("SYSTEM_ROOT",),
    "install": ("SYSTEM_INSTALL",),
    "appinstall": ("SYSTEM_INSTALL",),
    "notification": ("SYSTEM_NOTIFICATION",),
    "notify": ("SYSTEM_NOTIFICATION",),
    # 通信
    "bluetooth": ("COMM_BLUETOOTH",),
    "ble": ("COMM_BLUETOOTH",),
    "nfc": ("COMM_NFC",),
    "wifidirect": ("COMM_WIFI_DIRECT",),
    # 基础
    "filesystem": ("STORAGE",),
    "fileread": ("STORAGE",),
    "filewrite": ("STORAGE",),
    "codeexec": ("COMPUTE",),
    "docker": ("COMPUTE",),
    "gpu": ("COMPUTE",),
    # 被接入设备(HA 桥的动作名)
    "turnon": ("HOME_POWER",),
    "turnoff": ("HOME_POWER",),
    "toggle": ("HOME_POWER",),
    "setbrightness": ("HOME_LIGHT",),
    "settemperature": ("HOME_CLIMATE",),
    "opencover": ("HOME_COVER",),
    "closecover": ("HOME_COVER",),
    "lock": ("HOME_LOCK",),
    "unlock": ("HOME_LOCK",),
    "play": ("HOME_MEDIA",),
    "pause": ("HOME_MEDIA",),
    "volumeset": ("HOME_MEDIA",),
    "activate": ("HOME_SCENE",),
    "run": ("HOME_SCENE",),
    "returntobase": ("HOME_VACUUM",),
    "setspeed": ("HOME_POWER",),
    "readstate": ("HOME_SENSOR",),
    "snapshot": ("SENSOR_CAMERA",),
}

#: HA 实体 domain → 能力类(比动作名更准,桥知道 domain 时优先用)。
HA_DOMAIN_CLASSES: Dict[str, tuple] = {
    "light": ("HOME_POWER", "HOME_LIGHT"),
    "switch": ("HOME_POWER",),
    "fan": ("HOME_POWER",),
    "climate": ("HOME_CLIMATE",),
    "water_heater": ("HOME_CLIMATE",),
    "cover": ("HOME_COVER",),
    "lock": ("HOME_LOCK",),
    "media_player": ("HOME_MEDIA", "HOME_POWER"),
    "scene": ("HOME_SCENE",),
    "script": ("HOME_SCENE",),
    "vacuum": ("HOME_VACUUM",),
    "sensor": ("HOME_SENSOR",),
    "binary_sensor": ("HOME_SENSOR",),
    "camera": ("SENSOR_CAMERA",),
}


def capability_classes(raw: Iterable[Any], *, ha_domain: str = "") -> List[str]:
    """任意能力串 → 排好序、去重的能力类列表。认不出来的词丢掉(不猜),原值另外保留。"""
    out = set()
    for item in raw or []:
        s = str(item or "").strip()
        if not s:
            continue
        upper = s.upper()
        if upper in ALL_CAPABILITY_CLASSES:
            out.add(upper)
            continue
        out.update(_CAPABILITY_SYNONYMS.get(_squash(s), ()))
    if ha_domain:
        out.update(HA_DOMAIN_CLASSES.get(ha_domain.strip().lower(), ()))
    return sorted(out)


# ── 传输 ───────────────────────────────────────────────────────────────────────────

#: 设备自己讲 AIP v3 的传输:它跑着本系统的运行时(手机/手表 App、edge worker),
#: **不需要驱动节点**。映射表里 ``android_phone → Node_33_ADB`` 说的是"没装 App、
#: 只能用 ADB 操控的手机";对一台开着 App、经 WS 连上来的手机再去拉 ADB 节点是错的。
NATIVE_AIP_TRANSPORTS = frozenset({"websocket", "nats", "aip", "tcp_direct"})


def is_native_transport(transport: Any) -> bool:
    return str(transport or "").strip().lower() in NATIVE_AIP_TRANSPORTS


# ── 角色 ───────────────────────────────────────────────────────────────────────────

FULL_RUNTIME_HOST = "full_runtime_host"
PARTIAL_RUNTIME_DEVICE = "partial_runtime_device"
COMMAND_ORIENTED_DEVICE = "command_oriented_device"
OBSERVER_TELEMETRY_DEVICE = "observer_telemetry_device"
ADAPTER_BRIDGED_DEVICE = "adapter_bridged_device"

EXECUTION_MODELS = frozenset(
    {
        FULL_RUNTIME_HOST,
        PARTIAL_RUNTIME_DEVICE,
        COMMAND_ORIENTED_DEVICE,
        OBSERVER_TELEMETRY_DEVICE,
        ADAPTER_BRIDGED_DEVICE,
    }
)

#: 各角色的中文名 —— 面板与智能体工具共用,不各写一份。
ROLE_LABELS: Dict[str, str] = {
    FULL_RUNTIME_HOST: "主体",
    PARTIAL_RUNTIME_DEVICE: "成员",
    COMMAND_ORIENTED_DEVICE: "成员",
    OBSERVER_TELEMETRY_DEVICE: "观测设备",
    ADAPTER_BRIDGED_DEVICE: "被接入设备",
}


def execution_model_for(
    *,
    explicit: str = "",
    bridge_id: str = "",
    aip_device_type: str = "",
    metadata: Optional[Mapping[str, Any]] = None,
    classes: Iterable[str] = (),
) -> str:
    """设备在系统里的角色。

    顺序:显式声明 → 经桥接入 → 讲 AIP 的主体类设备(手机/电脑) → 手表等成员 →
    只有传感类能力的观测设备 → 有能力的命令型设备。
    """
    e = str(explicit or "").strip().lower()
    if e in EXECUTION_MODELS:
        return e
    if bridge_id:
        return ADAPTER_BRIDGED_DEVICE
    meta = dict(metadata or {})
    if meta.get("is_runtime_host") or str(meta.get("source_runtime_posture", "")).lower() == "join_runtime":
        return FULL_RUNTIME_HOST
    t = str(aip_device_type or "")
    if t in ("android_phone", "android_tablet", "ios_phone", "ios_tablet"):
        return FULL_RUNTIME_HOST
    if t.startswith(("windows_", "macos_", "linux_", "virtual_", "container_", "cloud_")) or t in (
        "android_wear",
        "ios_watch",
        "android_tv",
        "android_car",
    ):
        return PARTIAL_RUNTIME_DEVICE
    cls = set(classes or ())
    if cls and cls <= {"HOME_SENSOR", "SENSOR_GPS", "SENSOR_MOTION"}:
        return OBSERVER_TELEMETRY_DEVICE
    if cls:
        return COMMAND_ORIENTED_DEVICE
    return ""


def can_initiate(execution_model: str) -> bool:
    """能不能主动发起任务:只有主体能。成员只响应,被接入设备只上报。"""
    return execution_model == FULL_RUNTIME_HOST


# ── 一次性归一 ─────────────────────────────────────────────────────────────────────


def normalize_device(device: Any, *, raw_type: Any = None, keep_declared_classes: bool = True) -> Any:
    """就地补齐一台 ``UnifiedDevice`` 的统一词汇字段。已有值不覆盖(来源比推断知道得多)。

    ``raw_type``:调用方手里的原始类型串(在它被塞进粗类枚举之前)。没有时从
    ``metadata`` 里找,再退回到粗类本身。

    ``keep_declared_classes``:登记时调用方直接给的能力类要保留;之后能力整表替换时
    (``upsert_device_state``)传 False,按新能力重算 —— 否则撤掉的能力会一直挂着。
    """
    meta = dict(getattr(device, "metadata", None) or {})
    raw = raw_type or meta.get("aip_device_type") or meta.get("device_type_raw") or getattr(device, "device_type", "")
    hints = {
        "aip_device_type": getattr(device, "aip_device_type", "") or meta.get("aip_device_type", ""),
        "form_factor": getattr(device, "form_factor", "") or meta.get("form_factor", ""),
        "platform": meta.get("platform", ""),
    }
    info = classify_type(raw, hints=hints)
    if not getattr(device, "aip_device_type", ""):
        device.aip_device_type = info.aip_device_type
    if not getattr(device, "form_factor", ""):
        device.form_factor = info.form_factor
    current = str(getattr(device, "device_type", "") or "unknown")
    if current in ("unknown", "") and info.platform != "unknown":
        device.device_type = info.platform
    if not getattr(device, "bridge_id", ""):
        device.bridge_id = str(meta.get("bridge_id") or "")
    if not getattr(device, "transport", ""):
        device.transport = str(meta.get("transport") or ("home_assistant" if meta.get("ha_entity_id") else ""))
    declared = list(getattr(device, "capability_classes", None) or []) if keep_declared_classes else []
    device.capability_classes = capability_classes(
        list(getattr(device, "capabilities", None) or []) + declared + list(meta.get("capability_classes") or []),
        ha_domain=str(meta.get("ha_domain") or ""),
    )
    device.execution_model = execution_model_for(
        explicit=getattr(device, "execution_model", "") or meta.get("device_execution_model", ""),
        bridge_id=device.bridge_id,
        aip_device_type=device.aip_device_type,
        metadata=meta,
        classes=device.capability_classes,
    )
    return device
