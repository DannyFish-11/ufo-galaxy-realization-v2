"""tests/test_memory_recall_non_blocking.py
=============================================
回归防护:每轮对话的语义记忆召回不得冻结事件循环。

真机日志现象(与 test_llm_router_refresh_non_blocking.py 同一类症状):
GET /api/perception/desktop/status(本身逻辑很轻)在正常聊天过程中反复出现
3~9 秒的"Slow request"告警,且持续到聊天请求结束之后仍偶发。

根因:统一记忆层的语义召回 ``UnifiedMemory.recall()`` 对 Chroma 后端要先把
query 编码成向量(``SentenceTransformer.encode()``，CPU 密集、同步)。这是
同步方法，但在【每一轮对话】都会被直接调用——三处热路径都没有 offload：
  1. ``core/openclawd.py`` ``async def handle_chat()`` 里的
     ``get_unified_context(...)``。
  2. ``core/session_memory_facade.py`` ``MemoryScope.__aenter__()``(async)
     里的 ``recall(...)``。
  3. ``core/agent/execution_planner.py`` ``async def execute()`` 里的
     ``_um.recall(...)`` 与 ``self._experience_strategy_adjust(...)``
     (后者内部也调用 ``um.recall``)。
在协程里直接调用同步阻塞代码不会自动让出控制权——会冻结整条共享事件循环，
期间任何其它并发协程(包括完全无关的路由)都被卡住，直到编码完成。

修复:全部改为 ``await asyncio.to_thread(...)``，把 CPU 密集的同步调用
offload 到线程，不占用事件循环。
"""

from __future__ import annotations

import asyncio
import time

import pytest


@pytest.mark.asyncio
async def test_memory_scope_aenter_does_not_block_event_loop(monkeypatch):
    """MemoryScope.__aenter__ 期间,并发协程必须能继续正常推进。"""
    import core.session_memory_facade as smf
    from core.memory import get_unified_memory

    um = get_unified_memory()
    # 让 .enabled 为 True,无需真实 provider。
    um.providers.append(object())

    def _slow_recall(query, top_k=3):
        time.sleep(0.2)  # 模拟 CPU 密集的 embedding 计算
        return []

    monkeypatch.setattr(um, "recall", _slow_recall)

    tick_count = [0]

    async def _ticker():
        while True:
            await asyncio.sleep(0.02)
            tick_count[0] += 1

    ticker_task = asyncio.create_task(_ticker())
    try:
        scope = smf.MemoryScope("test-session-nb", "今天天气怎么样")
        await scope.__aenter__()
    finally:
        ticker_task.cancel()

    assert tick_count[0] >= 5, (
        f"MemoryScope.__aenter__ 期间并发协程几乎没推进(tick={tick_count[0]})，" f"说明语义召回仍在同步阻塞事件循环"
    )


def test_openclawd_handle_chat_offloads_unified_context():
    """静态核实:handle_chat 里对 get_unified_context 的调用经由 asyncio.to_thread。"""
    import inspect

    import core.openclawd as mod

    src = inspect.getsource(mod.OpenClawd.handle_chat)
    assert "_aio.to_thread(\n                    get_unified_context" in src or (
        "to_thread(" in src and "get_unified_context" in src
    ), "handle_chat 应通过 asyncio.to_thread 调用 get_unified_context，避免阻塞事件循环"


def test_execution_planner_execute_offloads_recall_calls():
    """静态核实:execute() 里对 recall/_experience_strategy_adjust 的调用经由 asyncio.to_thread。"""
    import inspect

    from core.agent.execution_planner import ExecutionPlanner

    src = inspect.getsource(ExecutionPlanner.execute)
    assert "asyncio.to_thread(self._experience_strategy_adjust" in src
    assert (
        "to_thread(_um.recall" in src
        or "to_thread(\n                    _um.recall" in src
        or ("to_thread(" in src and "_um.recall" in src)
    )
