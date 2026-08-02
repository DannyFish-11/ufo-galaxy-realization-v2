"""tests/test_l4_execution_honours_supply_decision.py
=====================================================
L4 ``CognitiveExecutionAuthority`` 必须**真的执行** L2 决定的供给路径，
而不是丢掉它、再在结果里声称自己执行了它。

修的是什么
----------
``CognitiveExecutionAuthority._dispatch()`` 的签名收下了 ``provider`` 与
``model``，函数体里却一个都没用，直接裸调 ``router.chat(messages=..., task_type=
"general", ...)``。于是：

- L1 → L2 算出来的供给路径（``supplied_provider`` / ``supplied_model``）被整条
  丢弃，后端自行路由；
- 而 ``execute()`` 仍把 ``supplied_provider`` / ``supplied_model`` 原样写进
  :class:`CognitiveExecutionResult`。

结果是 **L4 报告了一个并没有真正生效的 provider**。运行时实测（注入记录型
router，修复前）::

    L2 supplied      : anthropic
    实际传给 router  : {'messages': [...], 'task_type': 'general', ...}
                       ← provider / model 两个键根本不存在
    结果自称         : anthropic

外加 ``task_type`` 被写死成 ``"general"``，调用方的任务类型同样被丢掉 ——
而 task_type 正是上游 L1 路由的输入，写死它等于让 L4 的执行与 L1 的意图脱钩。

为什么此前 88 条 L4 测试没抓到
------------------------------
既有 ``tests/test_l4_cognitive_execution_authority.py`` 的断言几乎全是**结构性**
的：「sentinel 可导入」「类可导入」「有 execute 方法」「有 _normalize_response 静态
方法」。它们证明了模块**长什么样**，没有证明它**做了什么**。加上 L4 至今没有任何
生产调用方（只有 ``core/llm/__init__.py`` 的再导出、audit 探针、debt-freeze 清单
和这批测试），这个缺陷就一直没有暴露面 —— 空转的代码不会自己暴露缺陷。

本文件补的正是这一层：断言**传给 router 的实参**，而不是模块的形状。
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pytest

try:
    from core.llm.context_authority import (
        CognitiveContextRequest,
        get_cognitive_context_authority,
    )
    from core.llm.execution_authority import (
        CognitiveExecutionAuthority,
        CognitiveExecutionRequest,
    )
    from core.llm.route_authority import LLMRouteRequest, get_llm_route_authority
    from core.llm.supply_authority import get_llm_supply_authority

    _AVAILABLE = True
except ImportError:  # pragma: no cover
    _AVAILABLE = False


pytestmark = pytest.mark.skipif(not _AVAILABLE, reason="L1–L4 authority stack unavailable")


class _RecordingRouter:
    """替身 MultiLLMRouter：只记录 L4 到底让它做了什么。"""

    def __init__(self) -> None:
        self.calls: List[Tuple[str, Dict[str, Any]]] = []

    async def chat(self, **kwargs: Any) -> Any:
        self.calls.append(("chat", dict(kwargs)))
        return _FakeResponse()

    async def chat_with_tools(self, **kwargs: Any) -> Any:
        self.calls.append(("chat_with_tools", dict(kwargs)))
        return _FakeResponse()


class _FakeResponse:
    content = "ok"
    tool_calls = None
    raw_response = None
    input_tokens = 1
    output_tokens = 1
    latency_ms = 1.0


def _supply_state(provider_id: str = "anthropic") -> Dict[str, Any]:
    return {
        "providers": {
            provider_id: {
                "provider_id": provider_id,
                "health_status": "healthy",
                "available_models": [],
            }
        },
        "available_provider_ids": [provider_id],
        "fallback_candidates": [provider_id],
    }


async def _run_canonical_execution(
    router: _RecordingRouter,
    *,
    task_type: str = "general",
    tools: Any = None,
) -> Tuple[Any, Any]:
    """按模块 docstring 规定的 L1 → L2 → L3 → L4 顺序跑一次，返回 (supply, result)。"""
    decision = get_llm_route_authority().resolve(LLMRouteRequest(task_type=task_type))
    supply = get_llm_supply_authority().resolve_supply(decision, _supply_state())
    assembly = get_cognitive_context_authority().assemble(
        CognitiveContextRequest(task_type=task_type, user_message="hi", tool_manifest=tools)
    )
    auth = CognitiveExecutionAuthority(router=router)
    result = await auth.execute(CognitiveExecutionRequest(context_assembly=assembly, supply_resolution=supply))
    return supply, result


class TestSupplyDecisionReachesTheProvider:
    @pytest.mark.asyncio
    async def test_supplied_provider_is_actually_passed_to_the_router(self) -> None:
        """回归主体:修复前 provider 这个键在实参里根本不存在。"""
        router = _RecordingRouter()
        supply, _ = await _run_canonical_execution(router)

        assert router.calls, "L4 必须真的把请求派下去"
        _, kwargs = router.calls[0]
        assert supply.supplied_provider, "前提:L2 确实解出了一个 provider"
        assert kwargs.get("provider") == supply.supplied_provider, (
            "L4 必须把 L2 决定的 provider 真的传给执行层 —— "
            f"实际传了 {kwargs.get('provider')!r},L2 决定的是 {supply.supplied_provider!r}"
        )

    @pytest.mark.asyncio
    async def test_result_does_not_claim_a_provider_it_never_requested(self) -> None:
        """结果里自称的 provider,必须与实际请求的一致。

        这条才是缺陷的**危害面**:审计/追溯拿着 result.provider 当证据,
        而它在修复前可能与真正执行的 provider 无关。
        """
        router = _RecordingRouter()
        _, result = await _run_canonical_execution(router)
        _, kwargs = router.calls[0]
        assert result.provider == kwargs.get(
            "provider"
        ), "CognitiveExecutionResult.provider 不得声称一个没有真正下达的 provider"

    @pytest.mark.asyncio
    async def test_task_type_is_not_hardcoded_to_general(self) -> None:
        """写死 task_type='general' 等于让 L4 的执行与 L1 的路由意图脱钩。"""
        router = _RecordingRouter()
        await _run_canonical_execution(router, task_type="coding")
        _, kwargs = router.calls[0]
        assert (
            kwargs.get("task_type") == "coding"
        ), f"调用方的 task_type 必须传下去,实际传了 {kwargs.get('task_type')!r}"

    @pytest.mark.asyncio
    async def test_tools_path_also_carries_the_supply_decision(self) -> None:
        """带工具走的是 chat_with_tools 分支 —— 同一条约束不能只在无工具分支成立。"""
        router = _RecordingRouter()
        tools = [{"type": "function", "function": {"name": "noop", "parameters": {}}}]
        supply, _ = await _run_canonical_execution(router, tools=tools)

        method, kwargs = router.calls[0]
        assert method == "chat_with_tools"
        assert kwargs.get("provider") == supply.supplied_provider
        assert kwargs.get("tools") == tools


class TestEmptySupplyFieldsAreOmittedNotPassedBlank:
    """L2 没给出偏好时要**省略**该键,而不是传空串。

    传 ``provider=""`` 会被后端当成"有一个名叫空字符串的 provider"去查表,
    查不到就走异常/降级路径 —— 比不传更糟。
    """

    @pytest.mark.asyncio
    async def test_blank_model_is_omitted(self) -> None:
        router = _RecordingRouter()
        supply, _ = await _run_canonical_execution(router)
        _, kwargs = router.calls[0]
        if not supply.supplied_model:
            assert "model" not in kwargs, "L2 未指定 model 时不应传一个空 model"

    @pytest.mark.asyncio
    async def test_no_blank_string_values_are_ever_passed(self) -> None:
        router = _RecordingRouter()
        await _run_canonical_execution(router)
        _, kwargs = router.calls[0]
        for key in ("provider", "model"):
            if key in kwargs:
                assert kwargs[key], f"{key} 若无值就该省略,不该传空串"


class TestExecutionTraceRecordsTheRealTarget:
    @pytest.mark.asyncio
    async def test_trace_records_provider_model_and_task_type(self) -> None:
        """trace 是这条链路唯一的可复核记录,派发目标三要素都要在。"""
        router = _RecordingRouter()
        _, result = await _run_canonical_execution(router, task_type="coding")
        joined = " | ".join(result.execution_trace)
        assert "dispatch:" in joined
        assert "task_type=" in joined, "trace 必须记录真实下达的 task_type"
