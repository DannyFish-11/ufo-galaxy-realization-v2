#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenClawd 每请求身份的并发隔离测试(contextvars 立项)
====================================================

背景
----
OpenClawd 是进程级单例。``process()`` 在每个请求开始时把该请求的身份
(trace/session/device 等 7 个 ``_current_*`` 字段)打在 ``self`` 上,而写点与
后续读点(_dispatch_tool_call 等)之间隔着大量 ``await``。若这些字段是普通实例
属性,并发请求会互相覆盖 → 请求 A 可能读到请求 B 的身份(串号)。

本套测试锁定修复后的契约:``_current_*`` 字段必须是【上下文局部】的 ——
每个 asyncio 任务(= 每个请求)只看到自己写入的值;经 ``wait_for``/
``create_task`` 派生的子任务继承父请求身份;同步上下文(测试直接赋值)照常工作。

字段全集(与 core/openclawd.py process() 写点一一对应,一个不落):
    _current_trace_id, _current_session_id, _current_device_id,
    _current_control_session_id, _current_runtime_attachment_session_id,
    _current_source_runtime_posture, _current_cognitive_execution_hint
"""

from __future__ import annotations

import asyncio
import contextvars

from core.openclawd import OpenClawd

# 与 core/openclawd.py process() 写点(≈L4004-4021)保持同步的字段全集
IDENTITY_FIELDS = [
    "_current_trace_id",
    "_current_session_id",
    "_current_device_id",
    "_current_control_session_id",
    "_current_runtime_attachment_session_id",
    "_current_source_runtime_posture",
    "_current_cognitive_execution_hint",
]


def _bare() -> OpenClawd:
    """裸实例(跳过重量级 __init__),与既有测试套件同款做法。"""
    return OpenClawd.__new__(OpenClawd)


# ---------------------------------------------------------------------------
# 1. 核心:并发请求身份不得串号
# ---------------------------------------------------------------------------


def test_concurrent_requests_do_not_cross_contaminate():
    """两个并发"请求"交错读写身份字段,各自读回的必须是自己写入的值。

    时序设计:A 先写、后读(中间 sleep 0.05s);B 在 A 的窗口内写入并先读。
    若字段是共享实例属性,A 最终读到的是 B 的身份 → 断言失败(修复前为红)。
    """
    oc = _bare()
    results = {}

    async def request(tag: str, delay: float) -> None:
        oc._current_device_id = f"dev-{tag}"
        oc._current_session_id = f"sess-{tag}"
        oc._current_trace_id = f"tr-{tag}"
        await asyncio.sleep(delay)  # 让出事件循环,制造交错窗口
        results[tag] = (
            oc._current_device_id,
            oc._current_session_id,
            oc._current_trace_id,
        )

    async def main() -> None:
        await asyncio.gather(request("A", 0.05), request("B", 0.01))

    asyncio.run(main())
    assert results["A"] == ("dev-A", "sess-A", "tr-A"), f"请求 A 身份被污染: {results['A']}"
    assert results["B"] == ("dev-B", "sess-B", "tr-B"), f"请求 B 身份被污染: {results['B']}"


def test_all_seven_identity_fields_isolated():
    """7 个身份字段【全部】满足并发隔离 —— 一个不落。"""
    oc = _bare()
    out = {}

    async def request(tag: str, delay: float) -> None:
        for f in IDENTITY_FIELDS:
            setattr(oc, f, f"{tag}:{f}")
        await asyncio.sleep(delay)
        out[tag] = [getattr(oc, f) for f in IDENTITY_FIELDS]

    async def main() -> None:
        await asyncio.gather(request("A", 0.05), request("B", 0.01))

    asyncio.run(main())
    assert out["A"] == [f"A:{f}" for f in IDENTITY_FIELDS], f"A 被污染: {out['A']}"
    assert out["B"] == [f"B:{f}" for f in IDENTITY_FIELDS], f"B 被污染: {out['B']}"


def test_many_concurrent_requests_fuzz():
    """20 路并发 + 随机让出:任何一路读到别路身份即失败(小型压力回归)。"""
    oc = _bare()
    bad = []

    async def request(i: int) -> None:
        me = f"dev-{i}"
        oc._current_device_id = me
        oc._current_trace_id = f"tr-{i}"
        # 多次让出,扩大交错面
        for _ in range(3):
            await asyncio.sleep(0.001 * (i % 5))
        if oc._current_device_id != me or oc._current_trace_id != f"tr-{i}":
            bad.append((i, oc._current_device_id, oc._current_trace_id))

    async def main() -> None:
        await asyncio.gather(*[request(i) for i in range(20)])

    asyncio.run(main())
    assert not bad, f"以下请求读到了别人的身份: {bad[:5]}"


# ---------------------------------------------------------------------------
# 2. 继承:派生子任务必须看到父请求身份(_dispatch_tool_call 经 wait_for 包任务)
# ---------------------------------------------------------------------------


def test_child_task_inherits_parent_identity():
    """openclawd 实际派发路径是 `asyncio.wait_for(self._dispatch_tool_call(...))`,
    wait_for 会把协程包成新任务 → 新任务复制创建时的上下文,必须继承父身份。"""
    oc = _bare()

    async def main():
        oc._current_device_id = "dev-parent"
        oc._current_trace_id = "tr-parent"

        async def dispatch():
            return (oc._current_device_id, oc._current_trace_id)

        via_wait_for = await asyncio.wait_for(dispatch(), timeout=5)
        via_create_task = await asyncio.get_running_loop().create_task(dispatch())
        return via_wait_for, via_create_task

    wf, ct = asyncio.run(main())
    assert wf == ("dev-parent", "tr-parent"), f"wait_for 子任务未继承父身份: {wf}"
    assert ct == ("dev-parent", "tr-parent"), f"create_task 子任务未继承父身份: {ct}"


# ---------------------------------------------------------------------------
# 3. 兼容:既有测试/同步上下文的直接赋值语义保持不变
# ---------------------------------------------------------------------------


def test_sync_assignment_roundtrip_including_none():
    """既有测试套件里存在 `oc._current_trace_id = None` / `= ""` 等直接赋值,
    修复后同步上下文读写必须原样往返(包括 None)。"""
    oc = _bare()
    oc._current_trace_id = None
    oc._current_session_id = None
    oc._current_device_id = ""
    assert oc._current_trace_id is None
    assert oc._current_session_id is None
    assert oc._current_device_id == ""
    # 属性在类上存在 → getattr default 不触发
    assert getattr(oc, "_current_trace_id", "SENTINEL") is None

    oc._current_device_id = "dev-sync"
    assert oc._current_device_id == "dev-sync"


def test_unset_defaults_match_read_site_expectations():
    """未打戳(请求开始前)的默认值必须满足全部读点的预期:
    device/session/control/runtime_attach → 空串语义;trace/posture/hint → None 语义。
    在全新 Context 里执行,排除本测试进程先前写入的干扰。"""
    oc = _bare()

    def check():
        # 读点形态: getattr(self, "_current_device_id", "") or ""
        assert (getattr(oc, "_current_device_id", "") or "") == ""
        assert (getattr(oc, "_current_session_id", "") or "") == ""
        assert (getattr(oc, "_current_control_session_id", "") or "") == ""
        assert (getattr(oc, "_current_runtime_attachment_session_id", "") or "") == ""
        # 读点形态: getattr(self, "_current_trace_id", None) → 需为 falsy
        assert not getattr(oc, "_current_trace_id", None)
        assert getattr(oc, "_current_source_runtime_posture", None) is None
        assert getattr(oc, "_current_cognitive_execution_hint", None) is None

    contextvars.Context().run(check)


def test_identity_shared_across_instances_is_context_scoped():
    """OpenClawd 是单例;若测试创建多个裸实例,身份按【上下文】而非按实例区分 ——
    同一上下文里两个实例读到同一份(符合"进程单例 + 请求上下文"模型)。"""
    a, b = _bare(), _bare()

    def check():
        a._current_device_id = "dev-ctx"
        assert b._current_device_id == "dev-ctx"

    # 在隔离 Context 中执行,不污染其他测试
    contextvars.Context().run(check)
