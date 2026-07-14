"""tests/test_llm_router_refresh_non_blocking.py
==================================================
回归防护:MultiLLMRouter.refresh_providers() 不得冻结事件循环。

真机日志现象:面板保存一次模型 API Key 后,大量完全无关的并发请求(如
GET /api/perception/desktop/status,本身逻辑很轻)出现 3~8 秒的"Slow request"
告警。

根因:``MultiLLMRouter.refresh_providers()``(``async def``)内部直接同步调用
``_discover_providers()``——一个对 Ollama/OneAPI 等做阻塞 ``httpx.get()``
(timeout 2~5s)网络探测的**同步**方法。在协程里直接调用同步阻塞代码不会
自动让出控制权,会冻结整条共享事件循环:期间任何其它并发协程(包括完全
无关的路由)都会被彻底卡住,直到探测完成。``core/routes/system.py`` 的
``/api/config/update`` 端点也曾这样直接同步调用。

修复:两处调用点都改为 ``await asyncio.to_thread(self._discover_providers)``
/ ``await asyncio.to_thread(router._discover_providers)``,把阻塞探测
offload 到线程,不占用事件循环。
"""

from __future__ import annotations

import asyncio
import time

import pytest


@pytest.mark.asyncio
async def test_refresh_providers_does_not_block_event_loop(monkeypatch):
    """refresh_providers() 期间,并发协程必须能继续正常推进(证明未冻结事件循环)。"""
    from core.multi_llm_router import MultiLLMRouter

    def _slow_discover(self):
        time.sleep(0.3)  # 模拟阻塞网络探测(真实场景是 httpx.get timeout=2~5s)

    monkeypatch.setattr(MultiLLMRouter, "_discover_providers", _slow_discover)

    router = MultiLLMRouter.__new__(MultiLLMRouter)
    router.providers = {}
    router.adapters = {}
    router.circuit_breakers = {}

    tick_count = [0]

    async def _ticker():
        while True:
            await asyncio.sleep(0.02)
            tick_count[0] += 1

    ticker_task = asyncio.create_task(_ticker())
    try:
        t0 = time.time()
        await router.refresh_providers()
        elapsed = time.time() - t0
    finally:
        ticker_task.cancel()

    # 0.3s 窗口、每 20ms 一次 tick，理论上限约 15 次；冻结时应为 0。
    # 留足裕量：只要明显 > 0 即证明事件循环在阻塞探测期间保持响应。
    assert tick_count[0] >= 8, (
        f"refresh_providers() 期间并发协程几乎没推进(tick={tick_count[0]})，"
        f"说明 _discover_providers() 仍在同步阻塞事件循环(耗时 {elapsed:.2f}s)"
    )


def test_refresh_providers_awaits_to_thread(monkeypatch):
    """静态核实：refresh_providers() 源码里对 _discover_providers 的调用
    确实经由 asyncio.to_thread,而不是裸同步调用(防止未来改动悄悄回退)。"""
    import inspect

    import core.multi_llm_router as mod

    src = inspect.getsource(mod.MultiLLMRouter.refresh_providers)
    assert "asyncio.to_thread(self._discover_providers)" in src, (
        "refresh_providers() 应通过 asyncio.to_thread 调用 _discover_providers，" "避免在共享事件循环上做阻塞网络探测"
    )
