#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_retry_criterion_uses_failure_domains.py

钉住 CommandRouter 重试判据的**来源**，而不是钉住某一组错误码。

背景
====
`CommandRouter._execute_command` 的重试环里原本手抄了一份错误码集合::

    _retryable_codes = {COMMAND_TIMEOUT, DISCONNECT, EXECUTOR_ERROR}
    is_retryable = result.get("error_code") in _retryable_codes

而同一个类在别处已经调用 `core.failure_domains.classify_from_error_code`，把
`failure_is_retryable` 盖到 result 上（PR-13）——盖完只用于观测，判据另起炉灶。
两者分歧在 `DEVICE_NOT_FOUND` / `DEVICE_OFFLINE`：分类器判 `remote_device_unavailable`
且可重试，手抄集合判不可重试。这恰恰是**最该换一台设备重试**的情形，而重试环的
`_pick_retry_device()` 本来就是挑另一台；漏掉等于设备掉线时故障转移完全失效。

判据设计
========
这里**不**断言"DEVICE_OFFLINE 必须重试"——那样只是把手抄集合换个地方再抄一遍，
以后分类器改了、判据没跟上，测试照样绿。真正要钉的是**两者同源**：对每一个
GatewayErrorCode，重试环的实际行为必须与 `classify_from_error_code` 的判定一致。
分类器改了，这个测试自动跟着改，不需要人来同步。

HITL_TIMEOUT / HITL_DENIED 在 HITL 闸口处就 return 了（到不了重试环），
因此本测试只覆盖真正会走到重试判定的错误码。
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from core.command_router import CommandRouter, GatewayErrorCode
from core.failure_domains import classify_from_error_code

# HITL 两条在闸口就返回，永远到不了重试环；单独列出以免误以为是遗漏。
_CODES_SHORT_CIRCUITED_BEFORE_RETRY = {
    GatewayErrorCode.HITL_TIMEOUT.value,
    GatewayErrorCode.HITL_DENIED.value,
}


class _Candidate:
    """最小的重试候选对象——`_pick_retry_device` 只读 device_id。"""

    def __init__(self, device_id: str) -> None:
        self.device_id = device_id
        self.capabilities: List[str] = []
        self.online = True


def _reset_device_health() -> None:
    """清掉进程级健康registry。

    重试环里有一道熔断闸口（`is_eligible`）：上一个用例把 dev-A/B/C 全打成失败后，
    熔断器会 OPEN，下一个用例连派发都进不去，`tried` 恒为空 —— 那样测试会因为
    "谁都没跑"而假绿/假红，跟判据毫无关系。每个用例前清干净，隔离掉这层串扰。
    """
    from core.control_plane._globals import get_health_registry

    registry = get_health_registry()
    with registry._lock:  # noqa: SLF001 —— 无公开的整体重置 API
        registry._states.clear()


def _devices_tried_for(error_code: str) -> List[str]:
    """跑真实的 `_execute_command` 重试环，返回它实际派发过的设备序列。

    只替换最底层的 `_dispatch_to_device`（模拟设备一直回同一个错误码），
    判据、熔断、审计、重试挑选全部走真实代码。
    """
    _reset_device_health()
    router = CommandRouter()
    tried: List[str] = []

    async def _fake_dispatch(device_id: str, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        tried.append(device_id)
        return {
            "success": False,
            "result": None,
            "error_code": error_code,
            "error_message": f"simulated {error_code}",
            "device_id": device_id,
        }

    router._dispatch_to_device = _fake_dispatch  # type: ignore[assignment]

    asyncio.run(
        router._execute_command(
            device_id="dev-A",
            command="echo",
            payload={},
            command_id="cmd-retry-probe",
            task_id="task-retry-probe",
            timeout=1.0,
            trace_id="trace-retry-probe",
            retry_candidates=[_Candidate("dev-A"), _Candidate("dev-B"), _Candidate("dev-C")],
            max_retries=2,
        )
    )
    return tried


def test_retry_behaviour_matches_failure_domain_classifier() -> None:
    """重试与否必须与规范分类器同源——逐个错误码比对实际行为。"""
    mismatches: List[str] = []

    for code in GatewayErrorCode:
        if code.value in _CODES_SHORT_CIRCUITED_BEFORE_RETRY:
            continue
        expected_retryable = bool(classify_from_error_code(code.value).is_retryable)
        tried = _devices_tried_for(code.value)
        actually_retried = len(tried) > 1
        if actually_retried != expected_retryable:
            mismatches.append(
                f"{code.value}: 分类器 is_retryable={expected_retryable}，" f"重试环实际派发 {len(tried)} 次（{tried}）"
            )

    assert not mismatches, "重试判据与 core.failure_domains 分歧：\n  " + "\n  ".join(mismatches)


def test_device_unavailable_actually_fails_over_to_another_device() -> None:
    """设备不可用时必须换设备，而不是原地放弃。

    这条是上面那条的具体后果，单独钉住：`remote_device_unavailable` 域下
    重试环必须走到 `_pick_retry_device` 并派发到**不同**的设备上。
    """
    for code in (GatewayErrorCode.DEVICE_OFFLINE.value, GatewayErrorCode.DEVICE_NOT_FOUND.value):
        classification = classify_from_error_code(code)
        assert classification.domain.value == "remote_device_unavailable", (
            f"{code} 的失败域变了（现为 {classification.domain.value}）——"
            "本测试的前提不再成立，请重新确认故障转移语义"
        )
        tried = _devices_tried_for(code)
        assert len(set(tried)) > 1, f"{code} 只在 {tried} 上试过，没有换设备——故障转移失效"


# ---------------------------------------------------------------------------
# 退避：节奏必须来自失败域策略，而不是这里再抄一条曲线
# ---------------------------------------------------------------------------


def _backoff_delays_for(error_code: str) -> List[float]:
    """跑真实重试环，返回它实际**请求过**的退避时长序列。

    把 ``asyncio.sleep`` 换成记录器而不是真睡：既让测试是确定的（不受机器负载影响），
    也让它跑得完——超时域一轮就要等 3 秒。
    """
    from unittest.mock import patch

    _reset_device_health()
    router = CommandRouter()
    delays: List[float] = []
    real_sleep = asyncio.sleep

    async def _fake_dispatch(device_id: str, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {
            "success": False,
            "result": None,
            "error_code": error_code,
            "error_message": f"simulated {error_code}",
            "device_id": device_id,
        }

    async def _recording_sleep(seconds: float, *args: Any, **kwargs: Any) -> Any:
        delays.append(round(float(seconds), 4))
        return await real_sleep(0)

    router._dispatch_to_device = _fake_dispatch  # type: ignore[assignment]

    with patch("core.command_router.asyncio.sleep", side_effect=_recording_sleep):
        asyncio.run(
            router._execute_command(
                device_id="dev-A",
                command="echo",
                payload={},
                command_id="cmd-backoff-probe",
                task_id="task-backoff-probe",
                timeout=1.0,
                trace_id="trace-backoff-probe",
                retry_candidates=[_Candidate("dev-A"), _Candidate("dev-B"), _Candidate("dev-C")],
                max_retries=2,
            )
        )
    return delays


def test_retry_backoff_comes_from_the_failure_domain_policy() -> None:
    """逐个错误码比对：实际退避序列 == 按策略算出的序列。

    **不写死「DEVICE_OFFLINE 等 200 毫秒」** —— 那只是把策略表抄到测试里再对一遍，
    策略改了测试不会跟。这里现算期望值，策略表改了这条自动跟着改。
    """
    from core.schemas.execution_failure import build_failure_record

    ceiling = CommandRouter._RETRY_BACKOFF_CEILING_S
    mismatches: List[str] = []

    for code in GatewayErrorCode:
        if code.value in _CODES_SHORT_CIRCUITED_BEFORE_RETRY:
            continue
        if not classify_from_error_code(code.value).is_retryable:
            continue  # 不重试的错误码根本走不到退避

        policy = build_failure_record(error_code=code.value).retry_policy
        base_s = float(policy.backoff_base_ms) / 1000.0
        expected = [
            round(min(base_s * (float(policy.backoff_multiplier) ** attempt), ceiling), 4) for attempt in range(2)
        ]
        actual = _backoff_delays_for(code.value)
        if actual != expected:
            mismatches.append(
                f"{code.value}: 期望 {expected}（base={policy.backoff_base_ms}ms "
                f"×{policy.backoff_multiplier}），实际 {actual}"
            )

    assert not mismatches, "重试退避与失败域策略不一致：\n  " + "\n  ".join(mismatches)


def test_retry_loop_actually_waits_at_all() -> None:
    """可重试失败必须至少等过一次。

    这条单独钉「有没有退避」这件事本身：上面那条比对的是数值，若整个退避被删掉，
    期望与实际会同时变成空列表而**依然相等**——那就成了判而不别。
    """
    delays = _backoff_delays_for(GatewayErrorCode.COMMAND_TIMEOUT.value)
    assert delays, "可重试失败后一次都没等 —— 退避没生效，失败即刻重打"
    assert all(d > 0 for d in delays), f"退避时长里有 0：{delays}"
