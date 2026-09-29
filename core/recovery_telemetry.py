"""core/recovery_telemetry.py — 启动恢复的结果计入运行 SLO。

``core.operational_slo_metrics`` 里的六个恢复计数（尝试 / 续上 / 回放 / 重发 / 失败 /
启动扫描）一直没有生产调用方，于是 ``/metrics`` 上它们恒为 0 —— 看起来像「重启从来
没丢过东西」，实际是「没人记」。

这里读 :func:`core.runtime_restart_recovery.run_startup_recovery` 产出的报告，按报告里
**已经分好类**的数字记账，不自己重判：

- 在途任务每条记一次尝试；
- RESUMABLE → 续上，REPLAY_ONLY → 回放，REISSUABLE → 重发；
- 报告里每条错误记一次失败；
- 一次启动扫描：扫了多少条、采取了多少动作。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def record_recovery_outcome(report: Any) -> None:
    try:
        from core.operational_slo_metrics import get_operational_slo_metrics

        metrics = get_operational_slo_metrics()
        recovered = int(getattr(report, "inflight_tasks_recovered", 0) or 0)
        for _ in range(recovered):
            metrics.record_recovery_attempt()
        for _ in range(int(getattr(report, "inflight_tasks_resumable", 0) or 0)):
            metrics.record_recovery_resumed()
        for _ in range(int(getattr(report, "inflight_tasks_replay_only", 0) or 0)):
            metrics.record_recovery_replayed()
        for _ in range(int(getattr(report, "inflight_tasks_reissuable", 0) or 0)):
            metrics.record_recovery_reissued()
        for err in list(getattr(report, "errors", None) or []):
            metrics.record_recovery_failed(reason=str(err).split(":", 1)[0][:60])
        dispatched = getattr(report, "_dispatched_ids", None) or ()
        metrics.record_startup_recovery_scan(tasks_scanned=recovered, actions_taken=len(dispatched))
    except Exception as exc:  # noqa: BLE001 — 记账不拖垮启动
        logger.debug("recovery_telemetry: skipped: %s", exc)


__all__ = ["record_recovery_outcome"]
