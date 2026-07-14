"""任务成本账本 + 效率闭环(Grok 借鉴 1→3→2)+ 哲学对齐接线 测试
====================================================================

北极星从"单次推理速度"换成"完成一个任务的总消耗":
  1. 账本:开账→深链记账(LLM/工具/轮次)→结账落盘,契约完整。
  2. router._record_call 漏斗自动记入当前任务账单。
  3. runtime.handle_request 全生命周期开/结账,账单挂进响应 task_cost。
  4. bandit 打分新增"啰嗦惩罚"(平均输出 token 越多越吃亏)。
  5. 哲学对齐:intent.update 此前有订阅无发射——LIMINAL 期由 continuum tick
     发射,阈限呼吸映射(0.15-0.85)终于有了数据源。
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# 1. 账本契约
# ---------------------------------------------------------------------------


class TestLedgerContract:
    def test_open_record_close_roundtrip(self, monkeypatch, tmp_path):
        from core import task_cost_ledger as tcl

        monkeypatch.setenv("GALAXY_TASK_LEDGER_PATH", str(tmp_path / "ledger.jsonl"))

        token = tcl.open_task_bill("trace_t1", source="chat")
        tcl.add_llm_usage("ollama", 100, 50, cost=0.001)
        tcl.add_llm_usage("deepseek", 200, 80)
        tcl.add_tool_call()
        tcl.add_react_round()
        tcl.add_react_round()
        bill = tcl.close_task_bill(token, success=True)

        assert bill["llm_calls"] == 2
        assert bill["input_tokens"] == 300
        assert bill["output_tokens"] == 130
        assert bill["total_tokens"] == 430
        assert bill["tool_calls"] == 1
        assert bill["react_rounds"] == 2
        assert bill["providers"] == {"ollama": 1, "deepseek": 1}
        assert bill["success"] is True
        assert bill["wall_ms"] >= 0

        # JSONL 落盘(长期积累/微调原料)
        lines = (tmp_path / "ledger.jsonl").read_text(encoding="utf-8").strip().splitlines()
        assert json.loads(lines[-1])["trace_id"] == "trace_t1"

        # 内存环形可查 + 汇总标尺
        recent = tcl.get_task_cost_ledger().recent(5)
        assert any(r["trace_id"] == "trace_t1" for r in recent)
        assert tcl.get_task_cost_ledger().summary()["tasks"] >= 1

    def test_no_bill_in_context_is_silent_noop(self):
        from core import task_cost_ledger as tcl

        # 无在途账单:深链记账入口必须静默无操作(绝不反噬)
        tcl.add_llm_usage("x", 1, 1)
        tcl.add_tool_call()
        tcl.add_react_round()
        assert tcl.current_task_bill() is None


# ---------------------------------------------------------------------------
# 2. router 漏斗自动记账
# ---------------------------------------------------------------------------


class TestRouterFunnelTap:
    def test_record_call_feeds_current_bill(self, monkeypatch, tmp_path):
        from core import task_cost_ledger as tcl
        from core.multi_llm_router import LLMResponse, MultiLLMRouter, TaskType

        monkeypatch.setenv("GALAXY_TASK_LEDGER_PATH", "off")
        r = MultiLLMRouter.__new__(MultiLLMRouter)
        r.providers = {}
        r.call_history = []

        token = tcl.open_task_bill("trace_r1", source="test")
        resp = LLMResponse(content="x", provider="ollama", model="m", input_tokens=42, output_tokens=17, latency_ms=1.0)
        r._record_call("ollama", "m", TaskType.GENERAL, resp, True)
        bill = tcl.close_task_bill(token, success=True)

        assert bill["llm_calls"] == 1
        assert bill["input_tokens"] == 42 and bill["output_tokens"] == 17
        # call_history 同步带上 tokens_out(bandit 啰嗦惩罚的数据源)
        assert r.call_history[-1]["tokens_out"] == 17


# ---------------------------------------------------------------------------
# 3. runtime 全生命周期开/结账
# ---------------------------------------------------------------------------


class TestRuntimeBillLifecycle:
    @pytest.mark.asyncio
    async def test_handle_request_attaches_task_cost(self, monkeypatch, tmp_path):
        monkeypatch.setenv("GALAXY_TASK_LEDGER_PATH", str(tmp_path / "l.jsonl"))
        from core import task_cost_ledger as tcl
        from core.desktop_presence_runtime import DesktopPresenceRuntime

        rt = DesktopPresenceRuntime()

        async def _mock_process(**kwargs):
            tcl.add_llm_usage("ollama", 10, 5)  # 深链某处记了一笔
            return {"success": True, "response": "OK", "intent": "chat", "metadata": {"session_id": "s1"}}

        with patch("core.openclawd.get_openclawd") as mock_get:
            mock_clawd = MagicMock()
            mock_clawd.process = AsyncMock(side_effect=_mock_process)
            mock_get.return_value = mock_clawd
            result = await rt.handle_request(message="hi", source="chat")

        tc = result.get("task_cost")
        assert tc, "响应必须携带 task_cost 账单"
        assert tc["llm_calls"] == 1 and tc["total_tokens"] == 15
        assert tc["source"] == "chat"
        assert tc["success"] is True

    @pytest.mark.asyncio
    async def test_bill_closed_even_on_error(self, monkeypatch, tmp_path):
        monkeypatch.setenv("GALAXY_TASK_LEDGER_PATH", str(tmp_path / "l.jsonl"))
        from core.desktop_presence_runtime import DesktopPresenceRuntime
        from core.task_cost_ledger import current_task_bill

        rt = DesktopPresenceRuntime()
        with patch("core.openclawd.get_openclawd") as mock_get:
            mock_clawd = MagicMock()
            mock_clawd.process = AsyncMock(side_effect=RuntimeError("boom"))
            mock_get.return_value = mock_clawd
            result = await rt.handle_request(message="hi", source="chat")

        assert result.get("task_cost", {}).get("success") is False
        assert current_task_bill() is None  # 上下文已复位,不泄漏到下个请求


# ---------------------------------------------------------------------------
# 4. bandit 啰嗦惩罚
# ---------------------------------------------------------------------------


class TestBanditVerbosityPenalty:
    def _router_with_history(self, records):
        from core.multi_llm_router import MultiLLMRouter

        r = MultiLLMRouter.__new__(MultiLLMRouter)
        r.call_history = records
        return r

    def test_verbose_provider_scores_lower(self):
        """同成功率/延迟/成本,平均输出 token 高 4 倍的 provider 分更低。"""
        base = {"task_type": "general", "latency_ms": 100.0, "cost": 0.0, "success": True, "timestamp": 0.0}
        records = []
        for _ in range(20):
            records.append({**base, "provider": "terse", "model": "m", "tokens": 600, "tokens_out": 400})
            records.append({**base, "provider": "verbose", "model": "m", "tokens": 1800, "tokens_out": 1600})
        r = self._router_with_history(records)
        stats = r._provider_stats(None)
        total = int(sum(s["calls"] for s in stats.values()))
        assert r._bandit_score("terse", stats, total) > r._bandit_score("verbose", stats, total)

    def test_legacy_records_without_tokens_out_tolerated(self):
        """老 call_history 条目没有 tokens_out 字段:聚合按 0 处理,不炸。"""
        records = [
            {
                "provider": "old",
                "model": "m",
                "task_type": "general",
                "latency_ms": 50.0,
                "tokens": 100,
                "cost": 0.0,
                "success": True,
                "timestamp": 0.0,
            }
        ] * 6
        r = self._router_with_history(records)
        stats = r._provider_stats(None)
        assert stats["old"]["tokens_out_sum"] == 0.0
        assert r._bandit_score("old", stats, 6) > 0


# ---------------------------------------------------------------------------
# 5. 哲学对齐:intent.update 终于有发射者
# ---------------------------------------------------------------------------


class TestIntentUpdateEmission:
    @pytest.mark.asyncio
    async def test_liminal_tick_emits_intent_update(self):
        """LIMINAL 期 continuum tick 必须发射 intent.update(此前全仓库
        只有订阅者没有发射者,阈限呼吸映射从未被驱动过)。"""
        from core.desktop_presence_runtime import RuntimeSession, TriState
        from core.state_event_bus import get_state_event_bus

        bus = get_state_event_bus()
        got = []
        tok = bus.subscribe("intent.update", lambda e: got.append(getattr(e, "payload", e)))

        s = RuntimeSession(source="chat")
        try:
            s.advance(TriState.LIMINAL)  # 启动 continuum tick
            await asyncio.sleep(0.45)  # 让 tick(200ms 周期)至少跑一拍
            assert got, "LIMINAL 期必须周期性发射 intent.update"
            payload = got[-1] if isinstance(got[-1], dict) else {}
            assert "intent_strength" in payload
        finally:
            s.advance(TriState.SILENT)  # 停 tick
            try:
                bus.unsubscribe(tok)
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# 6. 输出预算 env
# ---------------------------------------------------------------------------


class TestAnswerBudget:
    @pytest.mark.asyncio
    async def test_react_loop_respects_max_tokens_env(self, monkeypatch):
        monkeypatch.setenv("GALAXY_MAX_TOKENS_ANSWER", "1234")
        from core.multi_llm_router import LLMResponse
        from core.openclawd import OpenClawd

        seen = {}

        class _FakeRouter:
            async def chat_with_tools(self, messages, tools=None, task_type=None, max_tokens=4096, **kwargs):
                seen["max_tokens"] = max_tokens
                return LLMResponse(
                    content="答", provider="p", model="m", input_tokens=1, output_tokens=1, latency_ms=1.0
                )

        clawd = OpenClawd.__new__(OpenClawd)
        clawd._get_router = lambda: _FakeRouter()
        result = await clawd._react_loop([{"role": "user", "content": "q"}], tools=None)
        assert seen["max_tokens"] == 1234
        assert result["response"] == "答"
