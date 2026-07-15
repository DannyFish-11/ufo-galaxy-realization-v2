"""工具路径故障转移回归:chat_with_tools 必须沿策略顺序逐个兜底。

此前 chat_with_tools 只取 provider_order[0] 强制成单一 provider,执行层 route()
返回它时 alternatives 为空 → 中途失败无从兜底(用户干活时云端抽风即降级)。
本测试锁死:首选软降级/抛异常时会换下一个候选;全失败时返回软结果而非抛。
"""

import pytest

from core.unified.llm_router import UnifiedLLMRouter


class _Resp:
    def __init__(self, provider, content="ok", model="m"):
        self.provider = provider
        self.content = content
        self.model = model
        self.tool_calls = None


class _FakeTelemetry:
    def __init__(self):
        self.calls = []

    def record(self, *a, **k):
        self.calls.append((a, k))


def _router(backend_chat):
    """构造一个只挂了必要桩的 UnifiedLLMRouter,避开 __init__ 的后端加载/网络探测。"""
    r = UnifiedLLMRouter.__new__(UnifiedLLMRouter)

    class _B:
        async def chat(self, **kwargs):
            return await backend_chat(**kwargs)

    r._backend = _B()
    r._telemetry = _FakeTelemetry()
    # 桩掉 L1/L2/L3 与策略顺序,让候选就是 [p1, p2]
    r._enrich_l3_context = lambda messages, task_type, tools: messages
    r._consult_l1_route = lambda t, p: (None, None, None, None)
    r._consult_l2_supply = lambda d: (None, None, False)
    r._get_provider_order = lambda *a, **k: (["p1", "p2"], None)
    return r


@pytest.mark.asyncio
async def test_failover_advances_on_soft_none():
    """p1 软降级(provider='none')→ 自动换 p2 并成功。"""
    seen = []

    async def backend_chat(**kw):
        p = kw["provider"]
        seen.append(p)
        if p == "p1":
            return _Resp("none")  # 软降级
        return _Resp("p2")

    r = _router(backend_chat)
    out = await r.chat_with_tools([{"role": "user", "content": "干活"}], tools=[{"x": 1}])
    assert out.provider == "p2", "首选软降级后应兜底到 p2"
    assert seen == ["p1", "p2"], "应按策略顺序逐个尝试"


@pytest.mark.asyncio
async def test_failover_advances_on_exception():
    """p1 抛异常 → 换 p2 成功。"""
    seen = []

    async def backend_chat(**kw):
        p = kw["provider"]
        seen.append(p)
        if p == "p1":
            raise RuntimeError("p1 boom")
        return _Resp("p2")

    r = _router(backend_chat)
    out = await r.chat_with_tools([{"role": "user", "content": "干活"}], tools=[{"x": 1}])
    assert out.provider == "p2"
    assert seen == ["p1", "p2"]


@pytest.mark.asyncio
async def test_all_fail_returns_soft_not_raise():
    """全部软降级 → 返回软结果(契约统一),不抛给上层。"""

    async def backend_chat(**kw):
        return _Resp("none")

    r = _router(backend_chat)
    out = await r.chat_with_tools([{"role": "user", "content": "干活"}], tools=[{"x": 1}])
    assert out is not None and str(out.provider).lower() == "none"


@pytest.mark.asyncio
async def test_first_success_short_circuits():
    """首选就成功 → 不再尝试后续候选。"""
    seen = []

    async def backend_chat(**kw):
        seen.append(kw["provider"])
        return _Resp("p1")

    r = _router(backend_chat)
    out = await r.chat_with_tools([{"role": "user", "content": "hi"}], tools=[{"x": 1}])
    assert out.provider == "p1"
    assert seen == ["p1"], "首选成功不应再打后续候选"
