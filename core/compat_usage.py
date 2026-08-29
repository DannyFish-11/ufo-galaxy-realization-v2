"""core/compat_usage.py —— 那些旧面,到底还有没有人在用

这个模块为什么存在
------------------
路线图 Q6 问的是"AIP v2 / 旧 REST 别名的退役日期定在哪天",它挡着 C5 与 C6 两项。
但那不是一个能靠想清楚回答的问题 —— 它挡在**没有数据**上:

* ``/api/devices/register`` / ``list`` / ``heartbeat`` / ``unregister`` 四条旧 REST
  别名,此前只有一行 ``logger.info``。日志会滚,没有任何一处能回答"上周有多少次调用"。
* ``/ws/android/{device_id}`` 与 ``/ws/android`` 两条 compat WS 入口同理。

于是退役日期只能拍脑袋定。定早了打死还在用的客户端,定晚了这些面继续常开 ——
而它们每一条都是攻击面。

本模块把"还有没有人用"变成一处可以被抓取的事实。**它不定日期,也不该定** ——
它只负责让那个决定有依据。

一条必须写在最前面的限制
------------------------
**计数在进程内,重启归零。** 所以"这个面 0 次调用"这句话的射程只有本进程的运行时长,
不是"没人用"。报告里 :func:`usage_report` 一定带 ``since`` 与 ``uptime_seconds``,
并且把这句话原样写进 ``zero_means`` —— 因为"0 次"是这份数据里最容易被读错的一格,
而读错的后果正好是那个要防的:据此提前退役掉一个其实还在用的面。

要真正回答"过去两周有多少次",靠的是 Prometheus 抓取(:func:`prometheus_lines`
把每个面吐成带标签的计数器,由外部时序库留存),不是这里的内存计数。

为什么只发 ``Deprecation`` 不发 ``Sunset``
------------------------------------------
RFC 9745 的 ``Deprecation`` 头表示"这个面已被弃用",RFC 8594 的 ``Sunset`` 头表示
"它将在这个时刻停止服务"。这里**只发前者**。

发 ``Sunset`` 就等于对外承诺了一个日期,而那个日期恰恰是本模块要收集数据去支撑的
东西。先把日期编出来贴到响应头上,再回头收集数据看它对不对,顺序是反的 ——
而且对面的客户端会当真。

日期定下来之后,在 :data:`SUNSET_AT` 填上,``Sunset`` 头会自动跟着发。
在那之前它是空串,而空串**不会**被渲染成一个头。
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Tuple

#: 旧面的两类。``ws_ingress`` = 兼容 WebSocket 入口;``rest_alias`` = 旧 REST 别名。
SURFACE_KINDS: Tuple[str, ...] = ("ws_ingress", "rest_alias")

#: 已登记的旧面。**唯一一份清单** —— 加一条兼容面就在这里加一行,
#: 否则它会以 ``unknown`` 的形式出现在报告里(不会被静默丢掉,见 :func:`record_use`)。
COMPAT_SURFACES: Dict[str, str] = {
    "/api/devices/register": "rest_alias",
    "/api/devices/list": "rest_alias",
    "/api/devices/heartbeat": "rest_alias",
    "/api/devices/unregister": "rest_alias",
    "/ws/android/{device_id}": "ws_ingress",
    "/ws/android": "ws_ingress",
    "/ws/ufo3/{device_id}": "ws_ingress",
}

#: 退役时刻(RFC 8594 ``Sunset``)。**空串 = 还没定**,那时不发这个头。
#: 定下来之后填一个 HTTP-date,例如 ``"Wed, 31 Dec 2026 23:59:59 GMT"``。
SUNSET_AT: str = ""

#: 每个面最多记多少个不同的客户端提示。有界 —— 客户端 UA 是外部可控的,
#: 无界收集等于给了对面一个把内存撑爆的开关。
CLIENT_HINTS_MAX = 12

_lock = threading.Lock()
_started_at = time.time()
_counts: Dict[str, int] = {}
_first_seen: Dict[str, float] = {}
_last_seen: Dict[str, float] = {}
_client_hints: Dict[str, List[str]] = {}


def record_use(surface: str, *, client_hint: str = "") -> None:
    """记一次旧面调用。**永不抛异常** —— 记账失败不该影响被记的那次调用。

    Args:
        surface: 旧面标识,取 :data:`COMPAT_SURFACES` 的键。没登记过的也照记
                 (归到它自己的名下),因为"有个没登记的兼容面在被调用"本身
                 就是要被看见的事实,静默丢掉等于假装它不存在。
        client_hint: 客户端自报的标识(User-Agent / app_version 之类)。
                     用来回答"还在用的是谁",而不只是"还有多少次"。
    """
    key = str(surface or "").strip()
    if not key:
        return
    hint = str(client_hint or "").strip()[:80]
    now = time.time()
    with _lock:
        _counts[key] = _counts.get(key, 0) + 1
        _first_seen.setdefault(key, now)
        _last_seen[key] = now
        if hint:
            hints = _client_hints.setdefault(key, [])
            if hint not in hints and len(hints) < CLIENT_HINTS_MAX:
                hints.append(hint)


def deprecation_headers(surface: str = "") -> Dict[str, str]:
    """这个旧面该带的响应头。

    ``Deprecation: true`` 是 RFC 9745 的形式。``Sunset`` 只在
    :data:`SUNSET_AT` 有值时才发 —— 见模块头"为什么只发 Deprecation"。

    ``Link`` 指向规范路径,让对面知道该改到哪儿去,而不只是知道这条要没了。
    """
    headers = {"Deprecation": "true"}
    if SUNSET_AT:
        headers["Sunset"] = SUNSET_AT
    canonical = _canonical_for(surface)
    if canonical:
        headers["Link"] = f'<{canonical}>; rel="successor-version"'
    return headers


def _canonical_for(surface: str) -> str:
    """这个旧面对应的规范路径;说不出来就返回空串(不编一个)。"""
    return {
        "/api/devices/register": "/api/v1/devices/register",
        "/api/devices/list": "/api/v1/devices",
        "/api/devices/heartbeat": "/api/v1/devices/status",
        "/ws/android/{device_id}": "/ws/device/{device_id}",
        "/ws/android": "/ws/device/{device_id}",
        "/ws/ufo3/{device_id}": "/ws/device/{device_id}",
    }.get(str(surface or "").strip(), "")


def usage_report() -> Dict[str, Any]:
    """旧面用量。给诊断面,也给"该不该定退役日期"这个决定当依据。"""
    now = time.time()
    with _lock:
        counts = dict(_counts)
        first = dict(_first_seen)
        last = dict(_last_seen)
        hints = {k: list(v) for k, v in _client_hints.items()}

    surfaces = []
    for name, kind in sorted(COMPAT_SURFACES.items()):
        used = counts.get(name, 0)
        surfaces.append(
            {
                "surface": name,
                "kind": kind,
                "canonical": _canonical_for(name),
                "calls": used,
                "first_seen": first.get(name),
                "last_seen": last.get(name),
                "client_hints": hints.get(name, []),
            }
        )

    unregistered = sorted(set(counts) - set(COMPAT_SURFACES))
    return {
        "since": _started_at,
        "uptime_seconds": round(now - _started_at, 1),
        "surfaces": surfaces,
        "total_calls": sum(counts.values()),
        # 没登记但被调用了的面。不为空说明 COMPAT_SURFACES 漏了一条。
        "unregistered_surfaces": [{"surface": s, "calls": counts[s]} for s in unregistered],
        "sunset_at": SUNSET_AT or None,
        "sunset_note": (
            "null = 退役日期**还没定**。这正是本模块在收集数据要支撑的那个决定 —— "
            "先编一个日期贴到 Sunset 头上再回头验证,顺序是反的,而且对面会当真。"
        ),
        "zero_means": (
            "计数在进程内,重启归零。所以 calls=0 的射程只有 uptime_seconds 这么长, "
            "**不等于「没人用」** —— 据此提前退役会打死还在用的客户端。"
            "要回答「过去两周多少次」,抓 Prometheus 的 galaxy_compat_surface_calls_total。"
        ),
    }


def prometheus_lines() -> List[str]:
    """按面吐带标签的计数器。这才是能跨重启留存的那份数据(由外部时序库抓取)。"""
    with _lock:
        counts = dict(_counts)
    lines = [
        "# HELP galaxy_compat_surface_calls_total Calls into deprecated compat surfaces",
        "# TYPE galaxy_compat_surface_calls_total counter",
    ]
    for name, kind in sorted(COMPAT_SURFACES.items()):
        safe = name.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'galaxy_compat_surface_calls_total{{surface="{safe}",kind="{kind}"}} {counts.get(name, 0)}')
    for name in sorted(set(counts) - set(COMPAT_SURFACES)):
        safe = name.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'galaxy_compat_surface_calls_total{{surface="{safe}",kind="unregistered"}} {counts[name]}')
    return lines


def reset_usage() -> None:
    """清空计数。**测试用** —— 生产路径不该调它:清掉用量记录等于把"还有没有人用"
    这个问题的唯一依据抹掉,而那正是退役决定要靠的东西。"""
    with _lock:
        _counts.clear()
        _first_seen.clear()
        _last_seen.clear()
        _client_hints.clear()
