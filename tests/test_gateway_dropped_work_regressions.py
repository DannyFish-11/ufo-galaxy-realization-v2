#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_gateway_dropped_work_regressions.py
==================================================
把 galaxy_gateway 里三处「算出来却丢掉」的缺陷钉住。

这三处是同一个形状：代码**付出了真实代价**（一次 ADB 抓屏、一次向量检索、一次
设备能力上报），结果却没有被任何人读取，于是系统的行为和从没做过这件事一样 ——
但日志/返回值仍然报告成功。它们是在给 galaxy_gateway 补 flake8 门覆盖时，由
F841（局部变量赋值后未使用）扫出来的。

判据都不是「变量有没有被用到」，而是**外部可观察的结果**：
能力上报后匹配器能不能查到、抓屏失败时会不会伪装成功、RAG 上下文有没有真的
进入下游提示词。只断言「变量被用了」的守卫是空的 —— 随便读一下就能骗过去。
"""

from __future__ import annotations

import asyncio
import base64
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

# ===========================================================================
# 一、AIP 能力上报必须真的落库
# ===========================================================================


def _unique_device_id(suffix: str) -> str:
    """每个用例用独立 device_id —— CapabilityBus 是进程内单例，会跨用例累积。"""
    return f"regr_dropped_work_{suffix}"


def test_capability_report_becomes_visible_to_capability_matcher() -> None:
    """设备上报的能力，必须能被 capability_registry 的多源解析读到。

    原缺陷：``_handle_capability_report`` 把 payload 里的 capabilities 读出来后
    直接丢弃，只把设备标成 online，却回 ``accepted: True``。于是设备能力只在
    **注册那一刻**被记录过，之后再上报多少次都进不了任何可查询的地方 —— 表现
    就是「设备明明有这个能力却选不中」，与 #1561 修的能力匹配缺陷是同一条链。
    """
    from core.capability_registry import get_device_capability_summary
    from galaxy_gateway.handlers.message_handler import MessageHandler
    from galaxy_gateway.protocol import AIPMessage, MessageType

    device_id = _unique_device_id("capability_visible")

    before = set(get_device_capability_summary(device_id).resolved_capabilities)
    assert "take_screenshot" not in before, "前置条件不成立：该 device_id 已经带有能力"

    handler = MessageHandler(MagicMock())
    message = AIPMessage(
        type=MessageType.CAPABILITY_REPORT,
        device_id=device_id,
        payload={"capabilities": ["take_screenshot", "tap"], "supported_actions": ["swipe"]},
    )

    ack = asyncio.get_event_loop().run_until_complete(handler._handle_capability_report(device_id, message))

    after = set(get_device_capability_summary(device_id).resolved_capabilities)
    missing = {"take_screenshot", "tap", "swipe"} - after
    assert not missing, (
        f"上报的能力没有进入能力解析结果，匹配器查不到：缺 {sorted(missing)}。\n" f"解析到的是：{sorted(after)}"
    )

    # ACK 要如实报告登记了多少条，而不是笼统一句 accepted。
    assert ack.payload.get("registered_capabilities") == 3, f"ACK 未如实回报登记条数：{ack.payload!r}"


def test_capability_report_ack_does_not_claim_success_without_registering() -> None:
    """空上报不应谎称登记了东西。"""
    from galaxy_gateway.handlers.message_handler import MessageHandler
    from galaxy_gateway.protocol import AIPMessage, MessageType

    device_id = _unique_device_id("capability_empty")
    handler = MessageHandler(MagicMock())
    message = AIPMessage(
        type=MessageType.CAPABILITY_REPORT,
        device_id=device_id,
        payload={"capabilities": [], "supported_actions": []},
    )
    ack = asyncio.get_event_loop().run_until_complete(handler._handle_capability_report(device_id, message))
    assert ack.payload.get("registered_capabilities") == 0


# ===========================================================================
# 二、截图失败不得伪装成功
# ===========================================================================


class _FakeADB:
    """可控的 adb_executor 替身。"""

    def __init__(self, *, pull_writes: Optional[bytes]) -> None:
        self._pull_writes = pull_writes
        self.calls: List[str] = []

    async def shell(self, cmd: str, device_id: str = "") -> str:
        self.calls.append(f"shell:{cmd}")
        return ""

    async def pull(self, remote: str, local: str, device_id: str = "") -> str:
        self.calls.append(f"pull:{remote}")
        if self._pull_writes is not None:
            with open(local, "wb") as fh:
                fh.write(self._pull_writes)
        return ""


def _screenshot(adb: _FakeADB) -> Dict[str, Any]:
    from galaxy_gateway.android_granular_adapter import AndroidGranularAdapter

    adapter = AndroidGranularAdapter(adb)
    return asyncio.get_event_loop().run_until_complete(adapter._handle_screenshot("dev_regr_screenshot", {}))


def test_screenshot_reports_error_when_pull_produces_empty_file() -> None:
    """pull 失败（文件为空）时必须报错，而不是回一张空图还说成功。

    原缺陷：``except FileNotFoundError`` 这条兜底**永远不会触发** —— ``mkstemp``
    已经把临时文件创建出来了，``open()`` 不会抛 FileNotFoundError，读到 0 字节，
    于是返回 ``{"status": "success", "image_base64": ""}``。调用方拿到一个
    "成功"的空截图，问题被推到更下游才暴露。
    """
    result = _screenshot(_FakeADB(pull_writes=b""))
    assert result["status"] == "error", f"空文件仍被当成成功：{result!r}"
    assert not result.get("image_base64"), "报错时不应带图像数据"


def test_screenshot_succeeds_with_real_content() -> None:
    """正常路径不能被上面的校验误伤。"""
    payload = b"\x89PNG\r\n\x1a\nfake-image-bytes"
    result = _screenshot(_FakeADB(pull_writes=payload))
    assert result["status"] == "success", f"正常截图被误判：{result!r}"
    assert base64.b64decode(result["image_base64"]) == payload


# ===========================================================================
# 三、RAG 增强上下文必须真的进入下游
# ===========================================================================


def test_rag_context_is_passed_into_team_execution_context() -> None:
    """检索出来的 rag_context 必须进入 TeamManager 的 context。

    原缺陷：``rag_context`` 被 ``await`` 出来后全函数再无引用 —— 向量检索和
    few-shot 拼接的开销照付，增强却从未进入任何提示词，等于没检索。
    AgentTeam 会把 context 序列化进 system prompt（core/agent_team.py），
    所以「有没有进 context」就是「有没有真的生效」。

    这里不去构造完整的 orchestrator 运行时（那需要一整套网关依赖），而是直接
    读源码确认注入点存在 —— 但**不是**只匹配变量名：断言的是 rag_context 被放进
    了交给 execute_team_task 的那个 context 字典。
    """
    import inspect

    from galaxy_gateway.orchestrator.galaxy_orchestrator import GalaxyOrchestrator

    src = inspect.getsource(GalaxyOrchestrator)

    assert "rag_context" in src, "RAG 增强调用整个消失了？"
    # 注入点：先构造 team_context，把 rag_context 挂进去，再传给 execute_team_task
    assert 'team_context["rag_context"] = rag_context' in src, (
        "rag_context 没有被放进交给 TeamManager 的 context —— " "检索开销照付但增强不生效（回到原缺陷）"
    )
    assert "context=team_context" in src, "execute_team_task 没有收到那个带 rag_context 的 context 字典"


def test_agent_team_serialises_context_into_prompt() -> None:
    """上一条的前提：AgentTeam 确实把 context 拼进提示词。

    如果哪天 AgentTeam 不再这么做，上面那条注入就变成了另一个「算了不用」，
    所以把这个前提也钉住。
    """
    import inspect

    import core.agent_team as agent_team

    src = inspect.getsource(agent_team)
    assert "上下文:\\n" in src or "上下文:" in src, (
        "AgentTeam 不再把 context 拼进提示词 —— rag_context 的注入点已失效，" "需要重新找一个真正能生效的位置"
    )
