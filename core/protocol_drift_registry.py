"""协议漂移的**运行时**登记:收到不认识的取值时,记下来并上报,而不是悄悄改成别的。

## 修的是什么(P3-2 的运行时那一半)

三端(V2 / 安卓 / 手表)靠事先约好的字段取值通信。约定漂移时,V2 侧此前有两种
处理,都不好:

**一、缺字段 → 乐观默认。** ``galaxy_gateway/android/models.py`` 里:

    device_type=DeviceType(data.get("device_type", "android_phone")),
    platform=DevicePlatform(data.get("platform", "android")),

设备**根本没报**平台,却被记成"安卓手机"。同一个函数上面几行就写着 PR-7A 的
纪律 ——「没报能力 → NONE,不给乐观默认」—— 这条纪律没覆盖到这两个字段。

**二、不认识的取值 → 直接 ValueError。** 实测::

    platform='wearos'   → ValueError: 'wearos' is not a valid DevicePlatform

``DevicePlatform`` 里根本没有 ``wearos``。手表侧哪天真的这么报,注册解析就在
半路抛异常;调用方若吞掉,表现就是**设备静默注册不上**,而且没有任何地方留下
"我见过一个不认识的取值"的记录 —— 正是最难查的那种漂移。

## 这个模块提供什么

一个进程内的、**有界的**登记表,加一个 ``coerce_protocol_enum()`` helper:

* 缺字段 / 空值 → 返回枚举的 ``UNKNOWN``(保守,不臆造),并记一笔 ``absent``;
* 认识的取值 → 原样返回,不记;
* 不认识的取值 → 返回 ``UNKNOWN``,记一笔 ``unrecognized`` **并带上原始字符串**。

关键是最后那半句:**原始字符串必须留下来**。只记"有漂移"而不记"漂移成了什么",
排查时等于没记 —— 而这个字符串正是去对面仓库里搜的唯一线索。

## 为什么归 UNKNOWN 而不是抛异常

抛异常把"协议漂移"变成"某个模块崩了",错误信息出现在离根因很远的地方,而且
一条坏消息会打断整批处理。归 UNKNOWN 则让**调用方**去决定:该拒绝的拒绝、该
降级的降级,同时这里留下可查的记录。这与仓库既有的
``UNKNOWN_MESSAGE_TYPE``(消息类型层已经这么做了,见 android_bridge)保持一致
—— 字段层此前缺了这一环。

## 为什么有界

对面可能持续发同一个坏值(重连风暴、循环重试),也可能发**每次都不同**的值。
无界登记会被这两种情况撑爆内存。所以按 (surface, field, value) 去重计数,并对
不同取值的种类数封顶;超出后只累计总数、不再新增条目,并如实标记 ``truncated``。
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Type, TypeVar

logger = logging.getLogger(__name__)

#: 权威哨兵 —— 与仓库其它 canonical 模块同一习语。
PROTOCOL_DRIFT_RUNTIME_AUTHORITY = "PROTOCOL_DRIFT::RUNTIME_UNKNOWN_VALUE_REGISTRY"

#: 不同 (surface, field, value) 组合的上限。超出后只累计总数,不再新增条目。
#: 取 256:足够覆盖真实漂移(一次协议变更通常引入个位数新取值),又不至于被
#: "每次都不同"的坏值撑爆。
MAX_DISTINCT_ENTRIES = 256

#: 记录里保留的原始值最大长度。对面可能发一个超长字符串。
MAX_RAW_VALUE_CHARS = 200

REASON_ABSENT = "absent"
REASON_UNRECOGNIZED = "unrecognized"


@dataclass(frozen=True)
class DriftKey:
    """一条漂移记录的身份:哪个协议面、哪个字段、收到的原始值。"""

    surface: str
    field_name: str
    raw_value: str
    reason: str


@dataclass
class DriftEntry:
    """一条漂移记录及其出现次数。"""

    key: DriftKey
    count: int = 0
    #: 最近一次见到它的设备 id(若调用方提供)。只留最近一个 —— 留全量等于
    #: 又开了一个无界集合。
    last_device_id: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "surface": self.key.surface,
            "field": self.key.field_name,
            "raw_value": self.key.raw_value,
            "reason": self.key.reason,
            "count": self.count,
            "last_device_id": self.last_device_id,
        }


@dataclass
class _Registry:
    entries: Dict[DriftKey, DriftEntry] = field(default_factory=dict)
    #: 因为超出 MAX_DISTINCT_ENTRIES 而未被单独记录的次数。
    dropped_events: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)


_registry = _Registry()


def record_unknown_value(
    surface: str,
    field_name: str,
    raw_value: Any,
    reason: str,
    device_id: Optional[str] = None,
) -> None:
    """记一笔协议漂移。

    ``reason`` 取 :data:`REASON_ABSENT` 或 :data:`REASON_UNRECOGNIZED` ——
    两者要分开:**缺字段**通常是对面版本旧、还没开始发这个字段;**取值不认识**
    则是对面已经在用一个我们不知道的值。前者往往可以等,后者说明契约已经分叉了。
    """
    text = "" if raw_value is None else str(raw_value)
    if len(text) > MAX_RAW_VALUE_CHARS:
        text = text[:MAX_RAW_VALUE_CHARS] + "…"

    key = DriftKey(surface=surface, field_name=field_name, raw_value=text, reason=reason)

    with _registry.lock:
        entry = _registry.entries.get(key)
        if entry is None:
            if len(_registry.entries) >= MAX_DISTINCT_ENTRIES:
                _registry.dropped_events += 1
                return
            entry = DriftEntry(key=key)
            _registry.entries[key] = entry
            first_time = True
        else:
            first_time = False
        entry.count += 1
        if device_id:
            entry.last_device_id = device_id

    # 只在**第一次**见到某个组合时打日志。持续的坏值会被计数吸收,不刷屏 ——
    # 刷屏本身就会让人把这类告警静音,等于没有。
    if first_time:
        if reason == REASON_ABSENT:
            logger.warning(
                "协议漂移:%s.%s 字段缺失(device=%s)。已归为 UNKNOWN 并登记 —— 不给乐观默认。",
                surface,
                field_name,
                device_id or "?",
            )
        else:
            logger.warning(
                "协议漂移:%s.%s 收到不认识的取值 %r(device=%s)。已归为 UNKNOWN 并登记 —— "
                "契约可能已与对面仓库分叉,拿这个字符串去对面搜。",
                surface,
                field_name,
                text,
                device_id or "?",
            )


def drift_entries() -> List[Dict[str, Any]]:
    """当前登记的全部漂移记录(按出现次数降序)。"""
    with _registry.lock:
        entries = [e.as_dict() for e in _registry.entries.values()]
    return sorted(entries, key=lambda e: e["count"], reverse=True)


def drift_summary() -> Dict[str, Any]:
    """给就绪/诊断面用的摘要。

    ``truncated`` 如实反映"还有多少事件因为超上限没被单独记录" —— 不能让上限
    把规模悄悄抹平。
    """
    with _registry.lock:
        entries = list(_registry.entries.values())
        dropped = _registry.dropped_events

    unrecognized = [e for e in entries if e.key.reason == REASON_UNRECOGNIZED]
    return {
        "authority": PROTOCOL_DRIFT_RUNTIME_AUTHORITY,
        "distinct_entries": len(entries),
        "total_events": sum(e.count for e in entries) + dropped,
        "unrecognized_distinct": len(unrecognized),
        "unrecognized_total": sum(e.count for e in unrecognized),
        "truncated": dropped > 0,
        "dropped_events": dropped,
    }


def has_unrecognized_drift() -> bool:
    """是否见过**不认识的取值**(契约已分叉的信号)。

    刻意不把 ``absent`` 算进来:缺字段多半只是对面版本旧,不构成分叉。
    """
    with _registry.lock:
        return any(e.key.reason == REASON_UNRECOGNIZED for e in _registry.entries.values())


def reset_protocol_drift_registry() -> None:
    """清空登记表。给测试用 —— 生产路径不该调用。"""
    with _registry.lock:
        _registry.entries.clear()
        _registry.dropped_events = 0


_EnumT = TypeVar("_EnumT", bound=Enum)


def coerce_protocol_enum(
    enum_cls: Type[_EnumT],
    raw_value: Any,
    *,
    surface: str,
    field_name: str,
    device_id: Optional[str] = None,
    unknown_member: str = "UNKNOWN",
) -> _EnumT:
    """把线上收到的字符串转成枚举,不认识就归 UNKNOWN 并登记。

    这是 P3-2 在**字段层**的落点。三种情形:

    * 缺失 / 空值 → UNKNOWN,记 ``absent``。**不给乐观默认** —— 设备没报平台
      就不该被记成安卓,那是凭空造事实;
    * 认识的取值 → 原样返回,不记;
    * 不认识的取值 → UNKNOWN,记 ``unrecognized`` **并保留原始字符串**。

    ``enum_cls`` 必须有 ``UNKNOWN`` 成员;没有就说明这个枚举还没准备好承接漂移,
    此时如实抛 ``LookupError`` —— 这属于**我们自己的**契约没定义好,应当在开发期
    响亮地失败,而不是运行时悄悄兜住。
    """
    try:
        unknown = enum_cls[unknown_member]
    except KeyError as exc:  # pragma: no cover - 开发期错误
        raise LookupError(
            f"{enum_cls.__name__} 没有 {unknown_member} 成员,无法承接协议漂移。"
            f"请先给这个枚举加上 UNKNOWN,再把它用于线上字段解析。"
        ) from exc

    if raw_value is None or (isinstance(raw_value, str) and not raw_value.strip()):
        record_unknown_value(surface, field_name, raw_value, REASON_ABSENT, device_id)
        return unknown

    if isinstance(raw_value, enum_cls):
        return raw_value

    try:
        return enum_cls(raw_value)
    except ValueError:
        record_unknown_value(surface, field_name, raw_value, REASON_UNRECOGNIZED, device_id)
        return unknown
