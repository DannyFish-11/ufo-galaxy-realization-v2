"""core/execution_observability/event_log.py — 统一执行事件的进程内环形日志。

为什么要有它
------------
``/api/v1/observability/execution/recent-events`` 原先只把 ``GatewayTraceStore`` 的记录
规范化成 :class:`ExecutionEvent`。而 ``normalizers`` 里另外三个规范化器——信封
（``normalize_task_envelope``）、任务图（``normalize_task_graph_result``）、Windows 仲裁
尝试（``normalize_arbiter_attempt``）——写好了却没有任何生产调用方：它们产出的事件没有
地方可放，放了也没人读。

这里就是那个「地方」：各层在自己真实发生的位置规范化一条事件、追加进来；
recent-events 接口把它和网关轨迹一起返回。只在内存里、有上限、线程安全。
"""

from __future__ import annotations

import threading
from collections import deque
from typing import Any, Deque, Dict, List

_MAX_EVENTS = 500

_lock = threading.Lock()
_events: Deque[Dict[str, Any]] = deque(maxlen=_MAX_EVENTS)


def record_execution_event(event: Any, *, origin: str) -> None:
    """追加一条已规范化的执行事件。``origin`` 写明是哪一层产出的（``command_router`` 等）。"""
    try:
        payload = event.to_dict() if hasattr(event, "to_dict") else dict(event)
    except Exception:  # noqa: BLE001 — 记账不能拖垮产出方
        return
    payload["origin"] = origin
    with _lock:
        _events.append(payload)


def recent_execution_events(limit: int = 20) -> List[Dict[str, Any]]:
    """最近的 *limit* 条，新的在前。"""
    with _lock:
        items = list(_events)
    return list(reversed(items))[: max(0, int(limit))]


def reset_execution_event_log() -> None:
    """清空（测试用）。"""
    global _events
    with _lock:
        _events = deque(maxlen=_MAX_EVENTS)


__all__ = ["record_execution_event", "recent_execution_events", "reset_execution_event_log"]
