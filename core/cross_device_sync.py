"""
core/cross_device_sync.py
=========================
中心往设备推的两种状态:一台设备发起的请求的进度(只回那台设备),和任务状态(推给指定的手机)。

电脑的三态(静默 / 思考 / 执行)是电脑这具身体的表达,**不推给任何设备**:设备直接对智能体 ——
登记、报能力、说话、拿回答 —— 不跟着电脑的脸显示。此前这里把电脑的每次相位变化广播给所有手机,
新设备登记 / 重连时还补推一次电脑当前的三态;两处都已删掉。

每台设备记一份时延画像,推送超时按它自适应(慢设备不拖住调用方)。
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core import upper_ports

logger = logging.getLogger("Galaxy.CrossDeviceSync")

# Retains fire-and-forget request-progress tasks.  The event loop only keeps a WEAK
# reference to a task, so a bare create_task(...) whose result is discarded can be
# garbage-collected before it runs.  Hold a strong ref until the task finishes.
_BACKGROUND_PHASE_SYNC_TASKS: set = set()

try:
    from core.schemas.aip_v3 import StateEventMsg  # noqa: F401

    _AIPV3_AVAILABLE = True
except ImportError:
    _AIPV3_AVAILABLE = False

# ---------------------------------------------------------------------------
# Per-device latency tracker (adaptive timeout)
# ---------------------------------------------------------------------------


@dataclass
class DeviceLatencyProfile:
    """Observed latency profile for a single device."""

    device_id: str
    samples: List[float] = field(default_factory=list)  # ms
    max_samples: int = 10
    last_success: float = 0.0  # timestamp
    last_failure: float = 0.0  # timestamp
    failure_count: int = 0

    def record(self, latency_ms: float, success: bool) -> None:
        if success:
            self.samples.append(latency_ms)
            if len(self.samples) > self.max_samples:
                self.samples.pop(0)
            self.last_success = time.time()
            self.failure_count = max(0, self.failure_count - 1)
        else:
            self.last_failure = time.time()
            self.failure_count += 1

    @property
    def avg_latency(self) -> float:
        if not self.samples:
            return 50.0  # default assumption 50ms
        return sum(self.samples) / len(self.samples)

    @property
    def p95_latency(self) -> float:
        if not self.samples:
            return 100.0
        sorted_samples = sorted(self.samples)
        idx = int(len(sorted_samples) * 0.95)
        return sorted_samples[min(idx, len(sorted_samples) - 1)]

    @property
    def is_healthy(self) -> bool:
        return self.failure_count < 3

    @property
    def adaptive_timeout(self) -> float:
        """Dynamic timeout: p95 + headroom, clamped to [0.5s, 5s]."""
        timeout = self.p95_latency * 3 + 100  # 3x p95 + 100ms buffer
        return max(0.5, min(timeout / 1000, 5.0))


class _LatencyTracker:
    """Module-level singleton tracking observed latency per device."""

    def __init__(self) -> None:
        self._profiles: Dict[str, DeviceLatencyProfile] = {}

    def get(self, device_id: str) -> DeviceLatencyProfile:
        if device_id not in self._profiles:
            self._profiles[device_id] = DeviceLatencyProfile(device_id=device_id)
        return self._profiles[device_id]

    def remove(self, device_id: str) -> None:
        self._profiles.pop(device_id, None)

    def all_profiles(self) -> Dict[str, Dict[str, Any]]:
        return {
            did: {
                "avg_ms": round(p.avg_latency, 1),
                "p95_ms": round(p.p95_latency, 1),
                "failures": p.failure_count,
                "healthy": p.is_healthy,
                "timeout_s": round(p.adaptive_timeout, 2),
            }
            for did, p in self._profiles.items()
        }


_latency_tracker = _LatencyTracker()

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


#: 进度报文的标记(``payload.sync_type``):这是「智能体在处理**你这件事**」的进度,不是电脑的三态。
#: 手机只认带这个标记的相位报文。
REQUEST_PROGRESS = "request_progress"


def build_phase_state_event(
    *,
    new_phase: str,
    old_phase: str = "unknown",
    source: str = "agent",
    sync_type: str = REQUEST_PROGRESS,
    session_id: str = "",
    trace_id: str = "",
    now_ms: Optional[int] = None,
) -> Dict[str, Any]:
    """相位报文的**唯一**构造处(现在只有一个用途:请求进度,见 :func:`tell_origin_device`)。

    手机读**顶层** ``event_action``,并看 ``payload.sync_type`` 是不是 :data:`REQUEST_PROGRESS`;
    ``payload`` 里另有 ``from_phase`` / ``to_phase``。``phase`` 顶层字段是旧版手机端的读法,保留兼容。

    Args:
        new_phase: 目标相位(``silent`` / ``liminal`` / ``manifest``)。
        old_phase: 来源相位。
        source:    这件请求从哪个入口进来的 —— 排障用。
        sync_type: 报文的由头,默认 :data:`REQUEST_PROGRESS`。
        now_ms:    时间戳(毫秒);留空取当前时间。测试可注入固定值。
    """
    ts = int(time.time() * 1000) if now_ms is None else int(now_ms)
    msg: Dict[str, Any] = {
        "type": "state_event",
        # ── 顶层:手机端读这两个字段 ──
        "event_category": "phase",
        "event_action": new_phase,
        "device_id": "v2_desktop",
        "timestamp": ts,
        "aip_version": "3.0",
        # ── payload:由头(手机靠 sync_type 认出这是请求进度)与前后相位 ──
        "payload": {
            "from_phase": old_phase,
            "to_phase": new_phase,
            "source": source,
            "sync_type": sync_type,
        },
        # ── 旧版手机端的读法,保留兼容 ──
        "phase": new_phase,
    }
    if session_id:
        msg["session_id"] = session_id
    if trace_id or session_id:
        msg["trace_id"] = trace_id or session_id
    return msg


def tell_origin_device(
    device_id: str,
    *,
    old_phase: str,
    new_phase: str,
    session_id: str = "",
    source: str = "",
    trace_id: str = "",
) -> None:
    """Fire-and-forget:智能体处理一台设备发起的请求时,把这件事的进度(在想 / 在做 / 做完)只回给那台设备。

    电脑的三态是电脑这具身体的表达,**不推给任何设备** —— 设备直接对智能体:登记、报能力、说话、
    拿回答。这里推的不是电脑的三态,而是发起设备自己那件请求的进度;手表不收(手表只响应,不显示进度)。
    调用方见 :func:`core.presence_line.tell_origin`。
    """
    if not device_id:
        return
    msg = build_phase_state_event(
        new_phase=new_phase,
        old_phase=old_phase,
        source=source or "agent",
        sync_type=REQUEST_PROGRESS,
        session_id=session_id,
        trace_id=trace_id,
    )
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("CrossDeviceSync: no event loop, request progress for %s not sent", device_id)
        return
    task = loop.create_task(_push_request_progress(device_id, msg))
    # 事件循环只弱引用任务;不留强引用,任务可能还没跑就被回收
    _BACKGROUND_PHASE_SYNC_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_PHASE_SYNC_TASKS.discard)


def _is_watch(device_id: str, device: Any) -> bool:
    """是不是手表。bridge 的缓存条目认不出手表报的 ``wearos``(落成 UNKNOWN),所以也看 UDM 归一后的类型。"""
    raw: List[Any] = [
        getattr(getattr(device, "device_type", None), "value", ""),
        getattr(getattr(device, "platform", None), "value", ""),
    ]
    try:
        from core.unified.device_manager import get_unified_device_manager  # noqa: PLC0415

        record = get_unified_device_manager().get_device(device_id)
        if record is not None:
            raw += [getattr(record, "form_factor", ""), getattr(record, "aip_device_type", "")]
    except Exception as exc:  # noqa: BLE001 — 查不到就按 bridge 条目判
        logger.debug("CrossDeviceSync: UDM lookup for %s failed: %s", device_id, exc)
    return any("wear" in str(v).lower() or "watch" in str(v).lower() for v in raw)


async def _push_request_progress(device_id: str, msg: Dict[str, Any]) -> bool:
    try:
        bridge = upper_ports.resolve("gateway.android_bridge.android_bridge")
    except Exception as exc:  # noqa: BLE001
        logger.debug("CrossDeviceSync: bridge not available: %s", exc)
        return False
    device = bridge.get_device(device_id)
    if device is None or device.websocket is None or not getattr(device, "connected", False):
        return False
    if _is_watch(device_id, device):
        return False
    try:
        return await _push_to_one_device(device_id, device, msg)
    except Exception as exc:  # noqa: BLE001 — 进度推不到不影响请求本身
        logger.debug("CrossDeviceSync: request progress to %s failed: %s", device_id, exc)
        return False


async def _push_to_one_device(
    device_id: str,
    device: Any,
    msg: Dict[str, Any],
) -> bool:
    """Push to a single device with adaptive timeout and retry.

    Returns True on success, raises on failure.
    """
    profile = _latency_tracker.get(device_id)
    timeout = profile.adaptive_timeout
    MAX_RETRIES = 2

    for attempt in range(MAX_RETRIES):
        t0 = time.time()
        try:
            await asyncio.wait_for(
                device.websocket.send_json(msg),
                timeout=timeout,
            )
            latency_ms = (time.time() - t0) * 1000
            profile.record(latency_ms, success=True)
            logger.debug(
                "CrossDeviceSync: push to %s OK (%.1fms, timeout=%.2fs)",
                device_id,
                latency_ms,
                timeout,
            )
            return True
        except asyncio.TimeoutError:
            profile.record(timeout * 1000, success=False)
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(0.05 * (attempt + 1))
            else:
                raise
        except Exception as exc:
            latency_ms = (time.time() - t0) * 1000
            profile.record(latency_ms, success=False)
            logger.debug("Push to %s failed after %d attempts: %s", device_id, attempt + 1, exc)
            raise

    return False


async def push_task_state_to_device(
    device_id: str,
    task_status: str,
    task_result: Optional[str] = None,
    task_error: Optional[str] = None,
    session_id: str = "",
    trace_id: str = "",
) -> bool:
    """Push task state update to a specific Android device."""
    try:
        _bridge = upper_ports.resolve("gateway.android_bridge.android_bridge")

        device = _bridge._devices.get(device_id)
        if device is None or device.websocket is None:
            return False

        msg: Dict[str, Any] = {
            "type": "state_event",
            "event_category": "task",
            "event_action": task_status,
            "device_id": "v2_desktop",
            "timestamp": int(time.time() * 1000),
            "session_id": session_id,
            "trace_id": trace_id,
            "aip_version": "3.0",
            "payload": {
                "task_status": task_status,
                "task_result": task_result,
                "task_error": task_error,
            },
        }

        return await _push_to_one_device(device_id, device, msg)

    except Exception as exc:
        logger.debug("CrossDeviceSync: task push to %s failed: %s", device_id, exc)
        return False


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


def get_sync_diagnostics() -> Dict[str, Any]:
    """Return current sync engine diagnostics for /status endpoint."""
    return {
        "latency_profiles": _latency_tracker.all_profiles(),
        "total_tracked_devices": len(_latency_tracker._profiles),
    }


def forget_device(device_id: str) -> None:
    """Remove a device's latency profile (call on disconnect)."""
    _latency_tracker.remove(device_id)
