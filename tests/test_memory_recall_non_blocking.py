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
     ``_um.recall(...)`` 与 ``self._derive_experience_guidance(...)``。

     后者原名 ``_experience_strategy_adjust``，内部也调用 ``um.recall``;
     现已改为读 TaskSummary 的类型化字段并用 BM25 排序作用域
     (见 ``core.cognitive.experience_guidance``)。BM25 比向量编码轻，
     但仍是同步 CPU 调用，**offload 要求不变**——本测试照旧防护它。
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


def _is_offloaded_to_thread(src: str, callee: str) -> bool:
    """``callee`` 是不是**作为参数**出现在某个 ``to_thread(...)`` 调用里。

    按 AST 判，不按字符串形状判 —— 理由见下面 ``test_openclawd_...`` 的说明。
    ``asyncio.to_thread(f, a, b)`` 的语义是"把 f 丢到线程里跑"，所以要找的是
    "``callee`` 出现在 to_thread 的实参位置上"，而不是"源码里两个词都出现过"。
    """
    import ast
    import textwrap

    tree = ast.parse(textwrap.dedent(src))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fname = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        if fname != "to_thread":
            continue
        for arg in node.args:
            # to_thread(f, ...) —— f 可能是 name、self.attr、module.attr
            name = arg.attr if isinstance(arg, ast.Attribute) else getattr(arg, "id", "")
            if name == callee.rsplit(".", 1)[-1]:
                return True
            # 也接受 to_thread(lambda: f(...)) 这种包一层的写法
            for inner in ast.walk(arg):
                if isinstance(inner, ast.Call):
                    iname = inner.func.attr if isinstance(inner.func, ast.Attribute) else getattr(inner.func, "id", "")
                    if iname == callee.rsplit(".", 1)[-1]:
                        return True
    return False


def test_openclawd_handle_chat_offloads_unified_context():
    """静态核实:handle_chat 里对 get_unified_context 的调用经由 asyncio.to_thread。

    这一条原先是这么写的::

        assert "_aio.to_thread(\\n                    get_unified_context" in src or (
            "to_thread(" in src and "get_unified_context" in src
        )

    两个子句都有问题，合起来更糟：

    * **主子句**把换行和 20 个空格的缩进编进了判据。black 换个行宽、或者这段代码
      被挪进/挪出一层缩进，它立刻不成立 —— 本仓库刚刚才因为同一种写法吃过一次假警
      (tests/test_device_ingress_is_canonical.py，启动器重做后缩进变了)。
    * **兜底子句**根本不判别：``"to_thread(" in src and "get_unified_context" in src``
      只要求这两个字符串**各自出现过**，不要求它们有任何关系。已实测反例：一段
      "同步调用 get_unified_context、另有一处无关的 to_thread" 的源码照样通过。

    合起来的后果最坏：今天主子句成立、测试是真的；哪天一次无关的重排让主子句失效，
    兜底会**静默接住**，这条钉子从此永远绿 —— 它不会像上次那样吵着报假警提醒你，
    而是一声不响地不再守任何东西。

    改成按 AST 判"callee 是否出现在 to_thread 的实参位置上"：换行缩进怎么变都不影响，
    而"同步调了它"这件事一定判得出来。
    """
    import inspect

    import core.openclawd as mod

    src = inspect.getsource(mod.OpenClawd.handle_chat)
    assert _is_offloaded_to_thread(
        src, "get_unified_context"
    ), "handle_chat 应通过 asyncio.to_thread 调用 get_unified_context，避免阻塞事件循环"


def test_execution_planner_execute_offloads_recall_calls():
    """静态核实:execute() 里对 recall/_derive_experience_guidance 的调用经由 asyncio.to_thread。"""
    import inspect

    from core.agent.execution_planner import ExecutionPlanner

    src = inspect.getsource(ExecutionPlanner.execute)
    # 同上:按 AST 判 callee 是否真的被 offload,不再靠字符串形状 + 不判别的兜底。
    assert _is_offloaded_to_thread(
        src, "_derive_experience_guidance"
    ), "execute() 应通过 asyncio.to_thread 调用 _derive_experience_guidance"
    assert _is_offloaded_to_thread(src, "recall"), "execute() 应通过 asyncio.to_thread 调用 _um.recall"
