"""core/device_state.py — 设备此刻的状态:设备自己报,中心原样记,不推断。

设计见 ``docs/DEVICE_SELF_DESCRIPTION_DESIGN.md`` 3.5;schema 在 ``contracts/device_state_v1.json``,
手机、手表用 shared-protocol 的 ``DeviceState.kt`` 拼同一个形状。

状态和自述分开:自述很少变,状态一直在变。状态跟着心跳走(``heartbeat`` 帧的 ``payload.state``),
每一份都是设备此刻的**全部**状态 —— 这一份里没有的键就是设备现在不知道,不沿用上一份。

三种来源一条规则:

* 设备报的(电量、屏幕、戴没戴着、能不能打扰……)原样记,存进 UDM 元数据的 ``device_state``;
* 中心看到的(在线、最后见到、网络路径、有没有命令在跑)由设备卡片自己算;
* 推断的不做:设备没报就是不知道,卡片上不写。

设备报的 ``interruptible`` 同时交给可打扰性登记处(``core/interruptibility_registry.py``),
常驻注意力循环据此决定要不要主动开口 —— 哪台设备报的就记哪台,不看它是什么设备。

旧帧照认一个版本:``device_status`` 帧里的电量、旧版手表单独发的 ``interruptibility`` 帧,
读成同一个形状。
"""

from __future__ import annotations

import json
import logging
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.DeviceState")

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "contracts" / "device_state_v1.json"
KEY = "state"
#: UDM 元数据里存设备状态的键
METADATA_KEY = "device_state"

INTERRUPTIBLE = ("blocked", "busy", "neutral", "free")
FLAGS = ("charging", "screen_on", "worn", "in_call")
KEYS = ("battery",) + FLAGS + ("interruptible", "note")
NOTE_MAX = 120

#: 旧版手表的原因标签 → 一句话。新版手表自己写 ``note``,中心不再翻译。
_LEGACY_REASON_WORDS = {
    "dnd": "已开勿扰",
    "likely_asleep": "极可能在睡",
    "attending": "正抬腕在看",
    "high_motion": "运动量大",
    "moderate_motion": "有一定活动",
    "still": "静止",
    "elevated_arousal": "心率高于其个人静息",
    "calm": "平静",
    "recent_interaction": "刚交互过",
    "no_sensor_data": "无传感证据",
}


@lru_cache(maxsize=1)
def schema() -> Dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def problems(state: Any) -> List[str]:
    """``state`` 哪里不合 schema(合就是空表)。只用来记日志和给契约测试,读入不因此拒收。"""
    try:
        import jsonschema
    except ImportError:  # pragma: no cover — requirements 里有;没装就不查
        return []
    validator = jsonschema.Draft202012Validator(schema())
    return [
        f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}" for e in validator.iter_errors(state)
    ]


def _battery(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        b = float(value)
    except (TypeError, ValueError):
        return None
    if 1.0 < b <= 100.0:  # 旧帧按百分数报
        b /= 100.0
    if not 0.0 <= b <= 1.0:
        return None
    return round(b, 2)


def read(raw: Any) -> Dict[str, Any]:
    """一份上报 → 只含认识的键、值都合法的状态。宽松:认不出的值丢掉、记日志,不拒收整份。"""
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, Any] = {}
    if "battery" in raw and (b := _battery(raw.get("battery"))) is not None:
        out["battery"] = b
    for k in FLAGS:
        if isinstance(raw.get(k), bool):
            out[k] = raw[k]
    band = str(raw.get("interruptible") or "").strip().lower()
    if band in INTERRUPTIBLE:
        out["interruptible"] = band
    note = str(raw.get("note") or "").strip()[:NOTE_MAX]
    if note:
        out["note"] = note
    dropped = sorted(set(raw) - set(out))
    if dropped:
        # 多出来的键不收:心率、位置这类原始信号就算设备那头被改坏塞上来,也进不了中心
        logger.info("设备状态里有认不出的键或值,丢掉: %s", dropped)
    return out


def carried(message: Any) -> Optional[Dict[str, Any]]:
    """心跳帧带的状态(``payload.state``,也认顶层 ``state``);没带就是 None —— 没带和带了一份空的不一样。"""
    if not isinstance(message, dict):
        return None
    payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}
    raw = payload.get(KEY, message.get(KEY))
    return read(raw) if isinstance(raw, dict) else None


def from_status_report(payload: Any) -> Dict[str, Any]:
    """旧的 ``device_status`` 帧:``battery`` / ``battery_level``、``charging`` / ``is_charging``、``screen_on``。"""
    if not isinstance(payload, dict):
        return {}
    return read(
        {
            "battery": payload.get("battery", payload.get("battery_level")),
            "charging": payload.get("charging", payload.get("is_charging")),
            "screen_on": payload.get("screen_on"),
        }
    )


def from_snapshot(snapshot: Any) -> Dict[str, Any]:
    """旧版手表单独发的 ``interruptibility`` 帧(登记处已校验成快照)→ 同一个形状。

    手表说不出所以然(``unknown`` 或零置信度)就不报 ``interruptible``;原因标签译成一句话进 ``note``。
    """
    if snapshot is None or not getattr(snapshot, "usable", False):
        return {}
    out: Dict[str, Any] = {"interruptible": snapshot.band}
    words = "、".join(_LEGACY_REASON_WORDS.get(r, r) for r in snapshot.reasons)
    if snapshot.confidence < 0.5:
        words = f"{words}(证据不足)" if words else "证据不足"
    if words:
        out["note"] = words[:NOTE_MAX]
    return out


def name_of(device_id: str) -> str:
    """人叫这台设备的名字,和设备卡片取法一样:登记的名字,其次自述里的名字;都没有就是空串。"""
    try:
        from core.device_self import described
        from core.unified.device_manager import get_unified_device_manager

        d = get_unified_device_manager().get_device(device_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug("读不到设备 %s 的名字: %s", device_id, exc)
        return ""
    if d is None:
        return ""
    for name in (d.device_name, described(d.metadata or {}).get("name")):
        if name and name not in (device_id, "unknown"):
            return str(name)
    return ""


def store(device_id: str, state: Dict[str, Any], *, now: Optional[float] = None) -> Dict[str, Any]:
    """把这份状态整份记进 UDM 元数据(替换上一份)。设备还没登记就不记。"""
    stored = {**state, "reported_at": now if now is not None else time.time()}
    try:
        from core.unified.device_manager import get_unified_device_manager

        get_unified_device_manager().upsert_device_state(
            device_id, {"metadata": {METADATA_KEY: stored}}, source="device_state"
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("设备 %s 的状态没记上(不影响连接): %s", device_id, exc)
    return stored


def record(device_id: str, state: Dict[str, Any], *, now: Optional[float] = None) -> Dict[str, Any]:
    """设备报来一份状态:记进 UDM;``interruptible`` 交给可打扰性登记处,这份没报就撤掉它上一份的。"""
    stored = store(device_id, state, now=now)
    try:
        from core.interruptibility_registry import get_interruptibility_registry

        reg = get_interruptibility_registry()
        if "interruptible" in state:
            reg.observe(
                device_id, state["interruptible"], note=state.get("note", ""), source=name_of(device_id), now=now
            )
        else:
            reg.forget(device_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug("可打扰性登记跳过: %s", exc)
    return stored


def current(metadata: Any, *, online: bool, now: Optional[float] = None) -> Dict[str, Any]:
    """卡片上该显示的设备状态:只在设备在线、这份还新鲜时给,只给设备报了的键。"""
    from core.interruptibility_registry import STALE_AFTER_S

    if not online or not isinstance(metadata, dict):
        return {}
    s = metadata.get(METADATA_KEY)
    if not isinstance(s, dict):
        return {}
    at = float(s.get("reported_at") or 0.0)
    if (now if now is not None else time.time()) - at > STALE_AFTER_S:
        return {}
    return {k: s[k] for k in KEYS if k in s}
