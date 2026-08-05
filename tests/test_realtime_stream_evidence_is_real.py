#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_realtime_stream_evidence_is_real.py
==================================================
实时流主干必须反映**实测到的流**，而不只是 mic/cam 注册计数。

原缺陷：``build_realtime_stream_runtime_status`` 只由 source registry 的计数推导
状态，而真正在流的 SSE token 流它一路都看不见 —— 于是"确实有一路在流"时
状态仍报 ``discrete_fallback``，主干成了纯声明。

判据是外部可观察结果：真的挂一路 ``use_stream``，状态里必须能看到它；
退出后必须归零（含异常路径）。同时钉住**实事求是**：跨进程看不到就明说看不到，
拿不到的证据记为 unobservable 而不是当成 0。
"""

from __future__ import annotations

import threading

import pytest

from core.llm_stream import TokenStream, stream_registry_snapshot, use_stream
from core.realtime_streaming_backbone import (
    build_realtime_stream_runtime_status,
    collect_realtime_stream_evidence,
)


def _sink() -> TokenStream:
    return TokenStream(on_delta=lambda _t: None)


def test_active_stream_is_observed_in_runtime_status() -> None:
    """挂着一路真实 token 流时，主干状态必须实测到它。"""
    before = build_realtime_stream_runtime_status(stream_evidence=collect_realtime_stream_evidence())
    assert before["observed_live_streaming"] is False

    with use_stream(_sink()):
        during = build_realtime_stream_runtime_status(stream_evidence=collect_realtime_stream_evidence())

    after = build_realtime_stream_runtime_status(stream_evidence=collect_realtime_stream_evidence())

    assert during["observed_live_streaming"] is True, "有一路在流，主干却看不见 —— 证据源没接上"
    assert during["stream_observability"]["token_streams_active"] >= 1
    assert after["observed_live_streaming"] is False, "流结束后必须归零（否则活跃数会越积越多）"


def test_registry_unregisters_on_exception() -> None:
    """异常路径也必须注销 —— 否则活跃计数留下幽灵，状态永远显示"有流在跑"。"""
    base = stream_registry_snapshot()["active"]
    with pytest.raises(RuntimeError):
        with use_stream(_sink()):
            raise RuntimeError("boom")
    assert stream_registry_snapshot()["active"] == base, "异常退出后活跃计数没有归位"


def test_registry_is_thread_safe_and_balanced() -> None:
    """多线程并发进出不得错账（真并发，不是模拟）。"""
    base = stream_registry_snapshot()["active"]
    errors = []

    def _worker():
        try:
            for _ in range(50):
                with use_stream(_sink()):
                    pass
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=_worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"并发进出出错: {errors}"
    assert stream_registry_snapshot()["active"] == base, "并发进出后活跃计数没有回到基线"


def test_evidence_is_honest_about_scope() -> None:
    """实事求是：本进程之外看不到就明说看不到，不把"本进程没有"报成"系统没有"。"""
    ev = collect_realtime_stream_evidence()
    assert ev["scope"] == "process_local"
    assert ev["cross_process_visibility"] is False, "不得宣称能看见跨进程的流"

    status = build_realtime_stream_runtime_status(stream_evidence=ev)
    obs = status["stream_observability"]
    assert obs["evidence_collected"] is True
    assert obs["cross_process_visibility"] is False
    assert obs["scope"] == "process_local"


def test_no_evidence_is_reported_as_unmeasured_not_as_zero() -> None:
    """没采证据时必须报"没测"，而不是默认成"没有流"（两者含义完全不同）。"""
    status = build_realtime_stream_runtime_status()
    assert status["stream_observability"]["evidence_collected"] is False
    assert status["stream_observability"]["scope"] == "unknown"


def test_existing_registry_semantics_unchanged() -> None:
    """既有 registry 推导的 stream_state 逐字节不变（证据轴只叠加）。"""
    snap = {"total_count": 2, "active_count": 1, "degraded_count": 0}
    plain = build_realtime_stream_runtime_status(source_registry_snapshot=snap)
    with_ev = build_realtime_stream_runtime_status(
        source_registry_snapshot=snap, stream_evidence=collect_realtime_stream_evidence()
    )
    for key in (
        "stream_state",
        "live_stream_session_exists",
        "stream_provider_total",
        "stream_provider_active",
        "stream_provider_degraded",
        "stream_active_for_routing",
        "stream_fallback_required",
        "stream_context_available",
    ):
        assert plain[key] == with_ev[key], f"证据轴改变了既有语义: {key}"


def test_runtime_summary_carries_evidence() -> None:
    """真实生产调用点（DesktopPresenceRuntime）必须带上实测证据，而不是只有计数。"""
    from core.desktop_presence_runtime import get_desktop_presence_runtime

    summary = get_desktop_presence_runtime().realtime_streaming_backbone_summary()
    status = summary.get("runtime_status") or {}
    assert "stream_observability" in status, "生产调用点没有采集实测证据 —— 主干仍是纯声明"
    assert status["stream_observability"]["evidence_collected"] is True


def test_snapshot_shape_is_stable() -> None:
    snap = stream_registry_snapshot()
    assert set(snap) == {"scope", "active", "started_total", "completed_total"}
    assert snap["started_total"] >= snap["completed_total"] >= 0
