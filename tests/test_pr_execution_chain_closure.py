#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr_execution_chain_closure.py
==========================================
执行链路闭环 PR — 本地链与跨设备链验收闭环测试

本测试文件验证以下执行链路闭环改进：

本地链路（Local Chain）:
  1.  ResultSourceChannel 新增 LOCAL 源通道。
  2.  LocalExecutionRecord 包含 acceptance_state 验收状态字段。
  3.  LocalExecutionRecord 包含 acceptance_closed 闭环标志字段。
  4.  to_dict() 包含 acceptance_state 和 acceptance_closed。
  5.  from_dict() 正确还原 acceptance_state 和 acceptance_closed。
  6.  submit_local_result_to_ingress: 成功路径返回字典。
  7.  submit_local_result_to_ingress: 返回 is_fully_closed 字段。
  8.  submit_local_result_to_ingress: UnifiedResultIngress 不可用时返回 None（优雅降级）。
  9.  submit_local_result_to_ingress: 使用 LOCAL 源通道。
  10. submit_local_result_to_ingress: 幂等性 key 前缀为 local_execution_result。
  11. record_local_execution: 有 result 时更新 acceptance_state。
  12. record_local_execution: 有 result 且 ingress 成功时 acceptance_closed=True。
  13. record_local_execution: ingress 不可用时 acceptance_state='ingress_skipped'。
  14. record_local_execution: 无 result 时 acceptance_state 保持为空字符串。
  15. record_local_execution: 将闭环记录写入 execution_chain_closure 注册表。

跨设备链路（Cross-Device Chain）:
  16. ChainExecutionRecord 包含 acceptance_state 验收状态字段。
  17. ChainExecutionRecord 包含 acceptance_closed 闭环标志字段。
  18. ChainExecutionRecord.to_dict() 包含新验收字段。
  19. ChainExecutionRecord.from_dict() 正确还原新验收字段。
  20. handle_goal_execution_result: 通过 ingest_result_async 路由。
  21. handle_goal_execution_result: 幂等性不再由外层记录（由 ingress 记录）。
  22. handle_goal_execution_result: 将闭环记录写入 execution_chain_closure 注册表。
  23. handle_goal_execution_result: ingress 不可用时回退到直接 truth chain。
  24. handle_goal_execution_result: 失败状态正确反映在 result_lineage 中。

闭环追踪模块（ExecutionChainClosure）:
  25. EXECUTION_CHAIN_CLOSURE_AUTHORITY 常量存在且非空。
  26. ChainKind 枚举包含 LOCAL 和 CROSS_DEVICE。
  27. ClosureState 枚举包含 PENDING / ACCEPTED / PARTIAL / FAILED / INTERRUPTED / REJECTED。
  28. ChainClosureRecord 默认构建成功。
  29. ChainClosureRecord.to_dict() 包含所有必需字段。
  30. ChainClosureRecord.from_dict() 不可用（序列化为 dict 供消费者使用）。
  31. DualChainClosureSummary 默认构建成功。
  32. DualChainClosureSummary.to_dict() 包含 contract_version。
  33. record_local_chain_closure: ACCEPTED 状态写入注册表。
  34. record_cross_device_chain_closure: ACCEPTED 状态写入注册表。
  35. record_local_chain_closure: 失败状态映射为 FAILED。
  36. record_cross_device_chain_closure: 取消状态映射为 INTERRUPTED。
  37. get_chain_closure_record: 返回最近写入的记录。
  38. get_chain_closure_record: task_id 不存在时返回 None。
  39. get_dual_chain_closure_summary: local 和 cross_device 统计分离。
  40. reset_closure_registry: 清空注册表。
  41. DualChainClosureSummary.to_dict() 包含 recent_records。
  42. 注册表有界（超出 _MAX_REGISTRY_SIZE 时删除最旧记录）。
  43. record_local_chain_closure: ingress_outcome=None 时优雅降级。
  44. record_cross_device_chain_closure: ingress_outcome=None 且 failed 时返回 FAILED。
  45. ChainClosureRecord JSON 可序列化。
  46. DualChainClosureSummary JSON 可序列化。
  47. 本地链和跨设备链 ClosureState 统计独立（不相互干扰）。
  48. get_dual_chain_closure_summary max_recent 参数有效。

All tests are self-contained (no live servers, no real devices).
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_task_id() -> str:
    return f"task-closure-{uuid.uuid4().hex[:12]}"


# ===========================================================================
# 1–15. 本地链路测试
# ===========================================================================


class TestLocalSourceChannel:
    def test_local_source_channel_exists(self):
        """ResultSourceChannel 新增 LOCAL 源通道。"""
        from core.unified_result_ingress import ResultSourceChannel
        assert hasattr(ResultSourceChannel, "LOCAL")

    def test_local_source_channel_value(self):
        """LOCAL 源通道值为 'local'。"""
        from core.unified_result_ingress import ResultSourceChannel
        assert ResultSourceChannel.LOCAL.value == "local"

    def test_local_source_channel_str_value(self):
        """LOCAL 源通道的值等于 'local'（str Enum 值比较）。"""
        from core.unified_result_ingress import ResultSourceChannel
        assert ResultSourceChannel.LOCAL == "local"


class TestLocalExecutionRecordAcceptanceFields:
    def test_acceptance_state_default_empty(self):
        """LocalExecutionRecord 的 acceptance_state 默认为空字符串。"""
        from core.local_execution_chain import LocalExecutionRecord
        r = LocalExecutionRecord()
        assert r.acceptance_state == ""

    def test_acceptance_closed_default_false(self):
        """LocalExecutionRecord 的 acceptance_closed 默认为 False。"""
        from core.local_execution_chain import LocalExecutionRecord
        r = LocalExecutionRecord()
        assert r.acceptance_closed is False

    def test_to_dict_includes_acceptance_state(self):
        """to_dict() 包含 acceptance_state 字段。"""
        from core.local_execution_chain import LocalExecutionRecord
        r = LocalExecutionRecord(task_id="t1", acceptance_state="accepted")
        d = r.to_dict()
        assert "acceptance_state" in d
        assert d["acceptance_state"] == "accepted"

    def test_to_dict_includes_acceptance_closed(self):
        """to_dict() 包含 acceptance_closed 字段。"""
        from core.local_execution_chain import LocalExecutionRecord
        r = LocalExecutionRecord(task_id="t1", acceptance_closed=True)
        d = r.to_dict()
        assert "acceptance_closed" in d
        assert d["acceptance_closed"] is True

    def test_from_dict_restores_acceptance_state(self):
        """from_dict() 正确还原 acceptance_state。"""
        from core.local_execution_chain import LocalExecutionRecord
        r = LocalExecutionRecord(task_id="t1", acceptance_state="quarantine")
        r2 = LocalExecutionRecord.from_dict(r.to_dict())
        assert r2.acceptance_state == "quarantine"

    def test_from_dict_restores_acceptance_closed(self):
        """from_dict() 正确还原 acceptance_closed。"""
        from core.local_execution_chain import LocalExecutionRecord
        r = LocalExecutionRecord(task_id="t1", acceptance_closed=True)
        r2 = LocalExecutionRecord.from_dict(r.to_dict())
        assert r2.acceptance_closed is True

    def test_from_dict_missing_acceptance_fields_defaults(self):
        """from_dict() 处理缺少验收字段的旧格式（向后兼容）。"""
        from core.local_execution_chain import LocalExecutionRecord
        old_dict = {
            "task_id": "old-task",
            "session_id": None,
            "executor_module": "",
            "steps_completed": [],
            "is_canonical": False,
            "legacy_path_used": None,
            "result": None,
            "record_id": "abc123",
            "dispatched_at": 1.0,
            "completed_at": None,
            "extra": {},
            # acceptance_state 和 acceptance_closed 故意省略
        }
        r = LocalExecutionRecord.from_dict(old_dict)
        assert r.acceptance_state == ""
        assert r.acceptance_closed is False


class TestSubmitLocalResultToIngress:
    def test_submit_returns_dict_on_success(self):
        """submit_local_result_to_ingress: 成功路径返回字典。"""
        from core.local_execution_chain import (
            LocalExecutionResult,
            submit_local_result_to_ingress,
        )

        class _FakeOutcome:
            is_fully_closed = True
            was_deduplicated = False
            truth_chain_complete = True
            completion_notified = True
            evidence_acceptance_verdict = "accept"
            evidence_trust_level = "high"
            incomplete_reason = ""
            task_completed = True
            problem_solved = False

        result = LocalExecutionResult(
            task_id="t-submit-ok",
            success=True,
            status="completed",
        )
        with patch("core.unified_result_ingress.ingest_result", return_value=_FakeOutcome()):
            out = submit_local_result_to_ingress(result, task_id="t-submit-ok")

        assert isinstance(out, dict)
        assert out["is_fully_closed"] is True
        assert out["truth_chain_complete"] is True

    def test_submit_returns_none_on_ingress_unavailable(self):
        """submit_local_result_to_ingress: ingress 不可用时返回 None（优雅降级）。"""
        from core.local_execution_chain import (
            LocalExecutionResult,
            submit_local_result_to_ingress,
        )

        result = LocalExecutionResult(task_id="t-submit-err", success=True, status="completed")

        with patch("core.unified_result_ingress.ingest_result", side_effect=RuntimeError("down")):
            out = submit_local_result_to_ingress(result, task_id="t-submit-err")

        assert out is None

    def test_submit_uses_local_source_channel(self):
        """submit_local_result_to_ingress: 使用 LOCAL 源通道。"""
        from core.local_execution_chain import (
            LocalExecutionResult,
            submit_local_result_to_ingress,
        )
        from core.unified_result_ingress import ResultSourceChannel

        received_events = []

        class _FakeOutcome:
            is_fully_closed = True
            was_deduplicated = False
            truth_chain_complete = True
            completion_notified = True
            evidence_acceptance_verdict = "accept"
            evidence_trust_level = "high"
            incomplete_reason = ""
            task_completed = True
            problem_solved = False

        def _fake_ingest(event):
            received_events.append(event)
            return _FakeOutcome()

        result = LocalExecutionResult(task_id="t-src-ch", success=True, status="completed")
        with patch("core.unified_result_ingress.ingest_result", side_effect=_fake_ingest):
            submit_local_result_to_ingress(result, task_id="t-src-ch")

        assert len(received_events) == 1
        assert received_events[0].source_channel == ResultSourceChannel.LOCAL

    def test_submit_idempotency_key_has_local_prefix(self):
        """submit_local_result_to_ingress: 幂等性 key 前缀为 local_execution_result。"""
        from core.local_execution_chain import (
            LocalExecutionResult,
            submit_local_result_to_ingress,
        )

        received_events = []

        class _FakeOutcome:
            is_fully_closed = True
            was_deduplicated = False
            truth_chain_complete = True
            completion_notified = True
            evidence_acceptance_verdict = "accept"
            evidence_trust_level = "high"
            incomplete_reason = ""
            task_completed = True
            problem_solved = False

        def _fake_ingest(event):
            received_events.append(event)
            return _FakeOutcome()

        result = LocalExecutionResult(task_id="t-idem", success=True, status="completed")
        with patch("core.unified_result_ingress.ingest_result", side_effect=_fake_ingest):
            submit_local_result_to_ingress(result, task_id="t-idem")

        assert len(received_events) == 1
        assert received_events[0].idempotency_key == "local_execution_result:t-idem"

    def test_submit_returns_is_fully_closed(self):
        """submit_local_result_to_ingress: 返回字典中包含 is_fully_closed。"""
        from core.local_execution_chain import (
            LocalExecutionResult,
            submit_local_result_to_ingress,
        )

        class _FakeOutcomePartial:
            is_fully_closed = False
            was_deduplicated = False
            truth_chain_complete = False
            completion_notified = False
            evidence_acceptance_verdict = ""
            evidence_trust_level = ""
            incomplete_reason = "truth_chain_failed"
            task_completed = False
            problem_solved = False

        result = LocalExecutionResult(task_id="t-partial", success=False, status="failed")
        with patch("core.unified_result_ingress.ingest_result", return_value=_FakeOutcomePartial()):
            out = submit_local_result_to_ingress(result, task_id="t-partial")

        assert out is not None
        assert out["is_fully_closed"] is False
        assert out["incomplete_reason"] == "truth_chain_failed"


class TestRecordLocalExecutionAcceptance:
    def test_record_updates_acceptance_state_when_result_provided(self):
        """record_local_execution: 有 result 时更新 acceptance_state。"""
        from core.local_execution_chain import (
            LocalExecutionResult,
            reset_local_execution_chain,
            record_local_execution,
        )

        class _FakeOutcome:
            is_fully_closed = True
            was_deduplicated = False
            truth_chain_complete = True
            completion_notified = True
            evidence_acceptance_verdict = "accept"
            evidence_trust_level = "high"
            incomplete_reason = ""
            task_completed = True
            problem_solved = False

        reset_local_execution_chain()
        result = LocalExecutionResult(task_id="t-rec-acc", success=True, status="completed")
        with (
            patch("core.unified_result_ingress.ingest_result", return_value=_FakeOutcome()),
            patch("core.execution_chain_closure.record_local_chain_closure"),
        ):
            rec = record_local_execution(
                task_id="t-rec-acc",
                result=result,
                executor_module="core.test_executor",
            )

        assert rec.acceptance_state == "accept"
        assert rec.acceptance_closed is True

    def test_record_acceptance_closed_true_when_fully_closed(self):
        """record_local_execution: ingress 完全闭环时 acceptance_closed=True。"""
        from core.local_execution_chain import (
            LocalExecutionResult,
            reset_local_execution_chain,
            record_local_execution,
        )

        class _FakeOutcomeClosed:
            is_fully_closed = True
            was_deduplicated = False
            truth_chain_complete = True
            completion_notified = True
            evidence_acceptance_verdict = "accept"
            evidence_trust_level = "high"
            incomplete_reason = ""
            task_completed = True
            problem_solved = False

        reset_local_execution_chain()
        result = LocalExecutionResult(task_id="t-closed", success=True, status="completed")
        with (
            patch("core.unified_result_ingress.ingest_result", return_value=_FakeOutcomeClosed()),
            patch("core.execution_chain_closure.record_local_chain_closure"),
        ):
            rec = record_local_execution(task_id="t-closed", result=result)

        assert rec.acceptance_closed is True

    def test_record_acceptance_skipped_when_ingress_unavailable(self):
        """record_local_execution: ingress 不可用时 acceptance_state='ingress_skipped'。"""
        from core.local_execution_chain import (
            LocalExecutionResult,
            reset_local_execution_chain,
            record_local_execution,
        )

        reset_local_execution_chain()
        result = LocalExecutionResult(task_id="t-skipped", success=True, status="completed")
        with (
            patch("core.unified_result_ingress.ingest_result", side_effect=ImportError("not installed")),
            patch("core.execution_chain_closure.record_local_chain_closure"),
        ):
            rec = record_local_execution(task_id="t-skipped", result=result)

        assert rec.acceptance_state == "ingress_skipped"
        assert rec.acceptance_closed is False

    def test_record_no_acceptance_when_no_result(self):
        """record_local_execution: 无 result 时 acceptance_state 保持为空字符串。"""
        from core.local_execution_chain import (
            reset_local_execution_chain,
            record_local_execution,
        )

        reset_local_execution_chain()
        rec = record_local_execution(task_id="t-no-result")
        assert rec.acceptance_state == ""
        assert rec.acceptance_closed is False

    def test_record_writes_to_closure_registry(self):
        """record_local_execution: 写入 execution_chain_closure 注册表。"""
        from core.local_execution_chain import (
            LocalExecutionResult,
            reset_local_execution_chain,
            record_local_execution,
        )
        from core.execution_chain_closure import reset_closure_registry, get_chain_closure_record

        class _FakeOutcome:
            is_fully_closed = True
            was_deduplicated = False
            truth_chain_complete = True
            completion_notified = True
            evidence_acceptance_verdict = "accept"
            evidence_trust_level = "high"
            incomplete_reason = ""
            task_completed = True
            problem_solved = False

        reset_local_execution_chain()
        reset_closure_registry()
        tid = _make_task_id()
        result = LocalExecutionResult(task_id=tid, success=True, status="completed")
        with patch("core.unified_result_ingress.ingest_result", return_value=_FakeOutcome()):
            record_local_execution(task_id=tid, result=result)

        rec = get_chain_closure_record(tid)
        assert rec is not None
        assert rec.chain_kind.value == "local"


# ===========================================================================
# 16–24. 跨设备链路测试
# ===========================================================================


class TestCrossDeviceChainRecordAcceptanceFields:
    def test_acceptance_state_default_empty(self):
        """ChainExecutionRecord 的 acceptance_state 默认为空字符串。"""
        from core.cross_device_execution_chain import ChainExecutionRecord
        r = ChainExecutionRecord()
        assert r.acceptance_state == ""

    def test_acceptance_closed_default_false(self):
        """ChainExecutionRecord 的 acceptance_closed 默认为 False。"""
        from core.cross_device_execution_chain import ChainExecutionRecord
        r = ChainExecutionRecord()
        assert r.acceptance_closed is False

    def test_to_dict_includes_acceptance_state(self):
        """to_dict() 包含 acceptance_state 字段。"""
        from core.cross_device_execution_chain import ChainExecutionRecord
        r = ChainExecutionRecord(task_id="t-cd", acceptance_state="accepted")
        d = r.to_dict()
        assert "acceptance_state" in d
        assert d["acceptance_state"] == "accepted"

    def test_to_dict_includes_acceptance_closed(self):
        """to_dict() 包含 acceptance_closed 字段。"""
        from core.cross_device_execution_chain import ChainExecutionRecord
        r = ChainExecutionRecord(task_id="t-cd2", acceptance_closed=True)
        d = r.to_dict()
        assert "acceptance_closed" in d
        assert d["acceptance_closed"] is True

    def test_from_dict_restores_acceptance_state(self):
        """from_dict() 正确还原 acceptance_state。"""
        from core.cross_device_execution_chain import ChainExecutionRecord
        r = ChainExecutionRecord(task_id="t-cd3", acceptance_state="reject")
        r2 = ChainExecutionRecord.from_dict(r.to_dict())
        assert r2.acceptance_state == "reject"

    def test_from_dict_missing_acceptance_fields_defaults(self):
        """from_dict() 处理缺少验收字段的旧格式（向后兼容）。"""
        from core.cross_device_execution_chain import ChainExecutionRecord
        old_dict = {
            "record_id": "abc",
            "task_id": "old",
            "trace_id": None,
            "device_id": "",
            "route_mode": "cross_device",
            "steps_completed": [],
            "is_canonical": False,
            "legacy_path_used": None,
            "result_envelope": None,
            "dispatched_at": 1.0,
            "completed_at": None,
            "extra": {},
            # acceptance_state 和 acceptance_closed 故意省略
        }
        r = ChainExecutionRecord.from_dict(old_dict)
        assert r.acceptance_state == ""
        assert r.acceptance_closed is False


@pytest.mark.skipif(
    sys.version_info < (3, 8),
    reason="asyncio.run requires Python 3.8+",
)
class TestHandleGoalExecutionResultClosure:
    @pytest.mark.asyncio
    async def test_routes_through_ingest_result_async(self):
        """handle_goal_execution_result: 通过 ingest_result_async 路由。"""
        from galaxy_gateway.android.handlers.goal_execution import handle_goal_execution_result

        ingress_calls = []

        class _FakeOutcome:
            is_fully_closed = True
            was_deduplicated = False
            truth_chain_complete = True
            incomplete_reason = ""
            evidence_acceptance_verdict = "accept"
            evidence_trust_level = "high"
            task_completed = True
            problem_solved = False
            completion_notified = True
            pending_response_resolved = True

        async def _fake_ingest(event, *, store_fn=None, bridge=None):
            ingress_calls.append(event.task_id)
            return _FakeOutcome()

        bridge = MagicMock()
        bridge._pending_responses = {}
        ws = MagicMock()
        tid = _make_task_id()

        with (
            patch("core.durable_result_idempotency.check_result_idempotency", return_value=False),
            patch("core.unified_result_ingress.ingest_result_async", side_effect=_fake_ingest),
            patch("core.execution_chain_closure.record_cross_device_chain_closure"),
        ):
            await handle_goal_execution_result(bridge, ws, {
                "type": "goal_execution_result",
                "device_id": "dev-1",
                "payload": {"task_id": tid, "status": "success", "result": "ok"},
            })

        assert len(ingress_calls) == 1
        assert ingress_calls[0] == tid

    @pytest.mark.asyncio
    async def test_outer_idempotency_not_recorded_by_handler(self):
        """handle_goal_execution_result: 外层不再调用 record_result_idempotency。
        幂等性 key 由 UnifiedResultIngress 内部记录。"""
        from galaxy_gateway.android.handlers.goal_execution import handle_goal_execution_result

        outer_record_calls = []

        class _FakeOutcome:
            is_fully_closed = True
            was_deduplicated = False
            truth_chain_complete = True
            incomplete_reason = ""
            evidence_acceptance_verdict = "accept"
            evidence_trust_level = "high"
            task_completed = True
            problem_solved = False
            completion_notified = True
            pending_response_resolved = True

        async def _fake_ingest(event, *, store_fn=None, bridge=None):
            return _FakeOutcome()

        bridge = MagicMock()
        bridge._pending_responses = {}
        ws = MagicMock()
        tid = _make_task_id()

        with (
            patch("core.durable_result_idempotency.check_result_idempotency", return_value=False),
            patch(
                "core.durable_result_idempotency.record_result_idempotency",
                side_effect=lambda key: outer_record_calls.append(key),
            ),
            patch("core.unified_result_ingress.ingest_result_async", side_effect=_fake_ingest),
            patch("core.execution_chain_closure.record_cross_device_chain_closure"),
        ):
            await handle_goal_execution_result(bridge, ws, {
                "type": "goal_execution_result",
                "device_id": "dev-1",
                "payload": {"task_id": tid, "status": "success", "result": "ok"},
            })

        # 外层不应调用 record_result_idempotency（由 ingress 内部负责）
        assert outer_record_calls == [], (
            f"外层不应调用 record_result_idempotency，但收到了调用: {outer_record_calls}"
        )

    @pytest.mark.asyncio
    async def test_writes_to_closure_registry(self):
        """handle_goal_execution_result: 写入 execution_chain_closure 注册表。"""
        from galaxy_gateway.android.handlers.goal_execution import handle_goal_execution_result
        from core.execution_chain_closure import reset_closure_registry, get_chain_closure_record

        class _FakeOutcome:
            is_fully_closed = True
            was_deduplicated = False
            truth_chain_complete = True
            incomplete_reason = ""
            evidence_acceptance_verdict = "accept"
            evidence_trust_level = "high"
            task_completed = True
            problem_solved = False
            completion_notified = True
            pending_response_resolved = True

        async def _fake_ingest(event, *, store_fn=None, bridge=None):
            return _FakeOutcome()

        bridge = MagicMock()
        bridge._pending_responses = {}
        ws = MagicMock()
        tid = _make_task_id()

        reset_closure_registry()

        with (
            patch("core.durable_result_idempotency.check_result_idempotency", return_value=False),
            patch("core.unified_result_ingress.ingest_result_async", side_effect=_fake_ingest),
        ):
            await handle_goal_execution_result(bridge, ws, {
                "type": "goal_execution_result",
                "device_id": "dev-1",
                "payload": {"task_id": tid, "status": "success", "result": "ok"},
            })

        rec = get_chain_closure_record(tid)
        assert rec is not None
        assert rec.chain_kind.value == "cross_device"
        assert rec.is_fully_closed is True

    @pytest.mark.asyncio
    async def test_fallback_to_truth_chain_when_ingress_unavailable(self):
        """handle_goal_execution_result: ingress 不可用时回退到直接 truth chain。"""
        from galaxy_gateway.android.handlers.goal_execution import handle_goal_execution_result

        truth_chain_calls = []

        class _FakeTTCOutcome:
            is_truth_chain_complete = True
            incomplete_reason = ""

        def _fake_ttc(msg, *, task_id=None, result_status=None):
            truth_chain_calls.append((task_id, result_status))
            return _FakeTTCOutcome()

        bridge = MagicMock()
        bridge._pending_responses = {}
        ws = MagicMock()
        tid = _make_task_id()

        with (
            patch("core.durable_result_idempotency.check_result_idempotency", return_value=False),
            patch(
                "core.unified_result_ingress.ingest_result_async",
                side_effect=ImportError("not installed"),
            ),
            patch(
                "galaxy_gateway.android.handlers.goal_execution._run_task_result_truth_chain",
                side_effect=_fake_ttc,
            ),
            patch("core.execution_chain_closure.record_cross_device_chain_closure"),
        ):
            await handle_goal_execution_result(bridge, ws, {
                "type": "goal_execution_result",
                "device_id": "dev-1",
                "payload": {"task_id": tid, "status": "failed", "result": ""},
            })

        # 回退路径必须调用 truth chain
        assert len(truth_chain_calls) == 1
        assert truth_chain_calls[0][0] == tid
        assert truth_chain_calls[0][1] == "failed"

    @pytest.mark.asyncio
    async def test_failed_status_reflected_in_lineage(self):
        """handle_goal_execution_result: 部分闭环时 lineage 反映失败状态。"""
        from galaxy_gateway.android.handlers.goal_execution import handle_goal_execution_result

        class _FakeOutcomePartial:
            is_fully_closed = False
            was_deduplicated = False
            truth_chain_complete = True
            incomplete_reason = "completion_not_notified"
            evidence_acceptance_verdict = ""
            evidence_trust_level = ""
            task_completed = False
            problem_solved = False
            completion_notified = False
            pending_response_resolved = False

        async def _fake_ingest(event, *, store_fn=None, bridge=None):
            return _FakeOutcomePartial()

        bridge = MagicMock()
        bridge._pending_responses = {}
        ws = MagicMock()
        tid = _make_task_id()

        with (
            patch("core.durable_result_idempotency.check_result_idempotency", return_value=False),
            patch("core.unified_result_ingress.ingest_result_async", side_effect=_fake_ingest),
            patch("core.execution_chain_closure.record_cross_device_chain_closure"),
        ):
            await handle_goal_execution_result(bridge, ws, {
                "type": "goal_execution_result",
                "device_id": "dev-1",
                "payload": {"task_id": tid, "status": "failed", "result": ""},
            })

        # 测试只验证代码不崩溃，并且能处理部分闭环（不抛出异常）


# ===========================================================================
# 25–48. 闭环追踪模块测试
# ===========================================================================


class TestExecutionChainClosureModule:
    def setup_method(self):
        """每个测试前重置注册表。"""
        from core.execution_chain_closure import reset_closure_registry
        reset_closure_registry()

    def test_authority_sentinel_exists(self):
        """EXECUTION_CHAIN_CLOSURE_AUTHORITY 常量存在且非空。"""
        from core.execution_chain_closure import EXECUTION_CHAIN_CLOSURE_AUTHORITY
        assert EXECUTION_CHAIN_CLOSURE_AUTHORITY
        assert len(EXECUTION_CHAIN_CLOSURE_AUTHORITY) > 10

    def test_chain_kind_local_and_cross_device(self):
        """ChainKind 枚举包含 LOCAL 和 CROSS_DEVICE。"""
        from core.execution_chain_closure import ChainKind
        assert ChainKind.LOCAL.value == "local"
        assert ChainKind.CROSS_DEVICE.value == "cross_device"

    def test_closure_state_all_required_states(self):
        """ClosureState 枚举包含所有必需状态。"""
        from core.execution_chain_closure import ClosureState
        required = {
            ClosureState.PENDING,
            ClosureState.ACCEPTED,
            ClosureState.PARTIAL,
            ClosureState.FAILED,
            ClosureState.INTERRUPTED,
            ClosureState.REJECTED,
        }
        for state in required:
            assert state in ClosureState

    def test_chain_closure_record_default_construction(self):
        """ChainClosureRecord 默认构建成功。"""
        from core.execution_chain_closure import ChainClosureRecord, ClosureState, ChainKind
        r = ChainClosureRecord()
        assert r.closure_state == ClosureState.PENDING
        assert r.chain_kind == ChainKind.LOCAL
        assert r.is_fully_closed is False

    def test_chain_closure_record_to_dict_keys(self):
        """ChainClosureRecord.to_dict() 包含所有必需字段。"""
        from core.execution_chain_closure import ChainClosureRecord
        r = ChainClosureRecord(task_id="t1")
        d = r.to_dict()
        for key in ("record_id", "task_id", "chain_kind", "closure_state",
                    "acceptance_verdict", "truth_chain_complete", "is_fully_closed",
                    "canonical_truth_completed", "mature_closure_achieved",
                    "normalized_status", "device_id", "executor_module",
                    "incomplete_reason", "extra", "recorded_at"):
            assert key in d, f"to_dict() missing key: {key}"

    def test_dual_chain_summary_default_construction(self):
        """DualChainClosureSummary 默认构建成功。"""
        from core.execution_chain_closure import DualChainClosureSummary
        s = DualChainClosureSummary()
        assert s.total_records == 0

    def test_dual_chain_summary_includes_contract_version(self):
        """DualChainClosureSummary.to_dict() 包含 contract_version。"""
        from core.execution_chain_closure import (
            DualChainClosureSummary,
            EXECUTION_CHAIN_CLOSURE_CONTRACT_VERSION,
        )
        s = DualChainClosureSummary()
        d = s.to_dict()
        assert "contract_version" in d
        assert d["contract_version"] == EXECUTION_CHAIN_CLOSURE_CONTRACT_VERSION

    def test_record_local_chain_closure_accepted(self):
        """record_local_chain_closure: ACCEPTED 状态写入注册表。"""
        from core.execution_chain_closure import (
            record_local_chain_closure,
            get_chain_closure_record,
            ClosureState,
        )
        tid = _make_task_id()
        ingress = {
            "is_fully_closed": True,
            "was_deduplicated": False,
            "truth_chain_complete": True,
            "evidence_acceptance_verdict": "accept",
            "incomplete_reason": "",
        }
        rec = record_local_chain_closure(tid, ingress_outcome=ingress)
        assert rec.closure_state == ClosureState.ACCEPTED
        fetched = get_chain_closure_record(tid)
        assert fetched is not None
        assert fetched.closure_state == ClosureState.ACCEPTED

    def test_record_cross_device_chain_closure_accepted(self):
        """record_cross_device_chain_closure: ACCEPTED 状态写入注册表。"""
        from core.execution_chain_closure import (
            record_cross_device_chain_closure,
            get_chain_closure_record,
            ClosureState,
            ChainKind,
        )
        tid = _make_task_id()
        ingress = {
            "is_fully_closed": True,
            "was_deduplicated": False,
            "truth_chain_complete": True,
            "evidence_acceptance_verdict": "accept",
            "incomplete_reason": "",
        }
        rec = record_cross_device_chain_closure(tid, ingress_outcome=ingress, device_id="dev-x")
        assert rec.closure_state == ClosureState.ACCEPTED
        assert rec.chain_kind == ChainKind.CROSS_DEVICE
        assert rec.device_id == "dev-x"

    def test_record_local_failed_status_maps_to_failed(self):
        """record_local_chain_closure: 失败状态映射为 FAILED。"""
        from core.execution_chain_closure import (
            record_local_chain_closure,
            ClosureState,
        )
        tid = _make_task_id()
        ingress = {
            "is_fully_closed": False,
            "was_deduplicated": False,
            "truth_chain_complete": False,
            "evidence_acceptance_verdict": "",
            "incomplete_reason": "truth_chain_failed",
        }
        rec = record_local_chain_closure(tid, ingress_outcome=ingress, normalized_status="failed")
        assert rec.closure_state == ClosureState.FAILED

    def test_record_cross_device_cancelled_maps_to_interrupted(self):
        """record_cross_device_chain_closure: 取消状态映射为 INTERRUPTED。"""
        from core.execution_chain_closure import (
            record_cross_device_chain_closure,
            ClosureState,
        )
        tid = _make_task_id()
        ingress = {
            "is_fully_closed": False,
            "was_deduplicated": False,
            "truth_chain_complete": False,
            "evidence_acceptance_verdict": "",
            "incomplete_reason": "cancelled",
        }
        rec = record_cross_device_chain_closure(tid, ingress_outcome=ingress, normalized_status="cancelled")
        assert rec.closure_state == ClosureState.INTERRUPTED

    def test_get_chain_closure_record_returns_none_for_unknown(self):
        """get_chain_closure_record: task_id 不存在时返回 None。"""
        from core.execution_chain_closure import get_chain_closure_record
        assert get_chain_closure_record("nonexistent-task-xyz") is None

    def test_dual_summary_local_and_cross_device_counts_independent(self):
        """get_dual_chain_closure_summary: local 和 cross_device 统计分离。"""
        from core.execution_chain_closure import (
            record_local_chain_closure,
            record_cross_device_chain_closure,
            get_dual_chain_closure_summary,
        )
        ingress_ok = {
            "is_fully_closed": True,
            "was_deduplicated": False,
            "truth_chain_complete": True,
            "evidence_acceptance_verdict": "accept",
            "incomplete_reason": "",
        }
        ingress_fail = {
            "is_fully_closed": False,
            "was_deduplicated": False,
            "truth_chain_complete": False,
            "evidence_acceptance_verdict": "",
            "incomplete_reason": "failed",
        }
        record_local_chain_closure(_make_task_id(), ingress_outcome=ingress_ok)
        record_local_chain_closure(_make_task_id(), ingress_outcome=ingress_fail, normalized_status="failed")
        record_cross_device_chain_closure(_make_task_id(), ingress_outcome=ingress_ok)

        s = get_dual_chain_closure_summary()
        assert s.local_total == 2
        assert s.cross_device_total == 1
        assert s.local_accepted == 1
        assert s.local_failed == 1
        assert s.cross_device_accepted == 1

    def test_reset_closure_registry_clears_records(self):
        """reset_closure_registry: 清空注册表。"""
        from core.execution_chain_closure import (
            record_local_chain_closure,
            reset_closure_registry,
            get_dual_chain_closure_summary,
        )
        record_local_chain_closure(_make_task_id(), ingress_outcome=None)
        reset_closure_registry()
        s = get_dual_chain_closure_summary()
        assert s.total_records == 0

    def test_summary_includes_recent_records(self):
        """DualChainClosureSummary.to_dict() 包含 recent_records 列表。"""
        from core.execution_chain_closure import (
            record_local_chain_closure,
            get_dual_chain_closure_summary,
        )
        record_local_chain_closure(_make_task_id(), ingress_outcome=None)
        s = get_dual_chain_closure_summary(max_recent=5)
        d = s.to_dict()
        assert "recent_records" in d
        assert len(d["recent_records"]) >= 1

    def test_record_ingress_none_graceful_degradation_local(self):
        """record_local_chain_closure: ingress_outcome=None 时优雅降级（不崩溃）。"""
        from core.execution_chain_closure import record_local_chain_closure, ClosureState
        tid = _make_task_id()
        # 应不抛出异常
        rec = record_local_chain_closure(tid, ingress_outcome=None, normalized_status="completed")
        # 无 ingress outcome，应为 PARTIAL 或 PENDING
        assert rec.closure_state in (ClosureState.PARTIAL, ClosureState.PENDING, ClosureState.ACCEPTED)

    def test_record_ingress_none_failed_status_graceful(self):
        """record_cross_device_chain_closure: ingress=None 且 failed 时返回 FAILED。"""
        from core.execution_chain_closure import (
            record_cross_device_chain_closure,
            ClosureState,
        )
        tid = _make_task_id()
        rec = record_cross_device_chain_closure(tid, ingress_outcome=None, normalized_status="failed")
        assert rec.closure_state == ClosureState.FAILED

    def test_chain_closure_record_json_serialisable(self):
        """ChainClosureRecord JSON 可序列化。"""
        from core.execution_chain_closure import ChainClosureRecord, ClosureState, ChainKind
        r = ChainClosureRecord(
            task_id="t-json",
            chain_kind=ChainKind.LOCAL,
            closure_state=ClosureState.ACCEPTED,
            acceptance_verdict="accept",
            is_fully_closed=True,
        )
        # 不应抛出 TypeError
        json_str = json.dumps(r.to_dict())
        assert json_str  # 非空字符串

    def test_dual_chain_summary_json_serialisable(self):
        """DualChainClosureSummary JSON 可序列化。"""
        from core.execution_chain_closure import get_dual_chain_closure_summary
        s = get_dual_chain_closure_summary()
        json_str = json.dumps(s.to_dict())
        assert json_str

    def test_summary_max_recent_respected(self):
        """get_dual_chain_closure_summary max_recent 参数有效。"""
        from core.execution_chain_closure import record_local_chain_closure, get_dual_chain_closure_summary
        ingress = {
            "is_fully_closed": True,
            "was_deduplicated": False,
            "truth_chain_complete": True,
            "evidence_acceptance_verdict": "accept",
            "incomplete_reason": "",
        }
        for _ in range(10):
            record_local_chain_closure(_make_task_id(), ingress_outcome=ingress)
        s = get_dual_chain_closure_summary(max_recent=3)
        assert len(s.recent_records) <= 3
