"""tests/test_mcp_over_nats.py
==============================

MCP 工具调用走 NATS 的**完整来回**。

补的是什么洞
------------
契约(``contracts/proto/galaxy/v1/mcp.proto``、``docs/AGENTIC_OS_ARCHITECTURE.md``)
里写了很久:

    galaxy.mcp.calls    Brain → MCP Gateway  (MCPCallRequest)
    galaxy.mcp.results  MCP Gateway → Brain  (MCPCallResponse)

实际状态是**两头各断一半**:

* ``NATSBus.publish_mcp_call``     有发布器,**没有任何订阅方** —— 发出去没人接。
* ``NATSBus.subscribe_mcp_results`` 有订阅器,**没有任何发布方** —— 订了永远收不到。

每一处单看都像是好的(发布器在、订阅器在、proto 在、文档在),合起来这个回路
一次也没跑通过。这类"半通"比整块缺失更难发现。

所以这里一律钉**来回**,不钉"某个方法被调用了":发一个请求,断言真的拿到结果。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List

import pytest

from core.mcp_call_client import MCPCallClient
from core.mcp_gateway import MCPDynamicGateway
from core.nats_bus import NATSBus


@pytest.fixture()
def bus() -> NATSBus:
    """一条进程内总线 —— 真的 NATSBus,不是桩。"""
    b = NATSBus()
    b.enable_local_fallback("测试:进程内总线")
    return b


@pytest.fixture()
def gateway(bus: NATSBus) -> MCPDynamicGateway:
    gw = MCPDynamicGateway(nats=bus)
    return gw


@pytest.fixture()
def client(bus: NATSBus) -> MCPCallClient:
    return MCPCallClient(nats=bus)


def _tool_returns(gw: MCPDynamicGateway, value: Any):
    """把网关的工具执行换成一个可控的返回值。"""

    async def _exec(tool_name: str, arguments: dict, **_kw: Any) -> Any:
        return value

    gw.execute_tool = _exec


# ── 1. 完整来回 ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tool_call_completes_a_full_round_trip(gateway, client):
    """请求发上 calls、结果从 results 回来 —— 这是修复前一次也没发生过的事。"""
    _tool_returns(gateway, {"stdout": "hello", "code": 0})
    await gateway.start_nats_listener()

    result = await client.call_tool("echo", {"text": "hello"}, timeout_s=5.0)

    assert result["success"] is True, f"来回没走通:{result}"
    assert result["result"] == {"stdout": "hello", "code": 0}
    assert result["request_id"]


@pytest.mark.asyncio
async def test_arguments_reach_the_tool_intact(gateway, client):
    """参数要原样送到工具手上 —— 中间隔着一次 JSON 编解码。"""
    seen: Dict[str, Any] = {}

    async def _exec(tool_name: str, arguments: dict, **_kw: Any) -> Any:
        seen["tool"] = tool_name
        seen["args"] = arguments
        return {"ok": True}

    gateway.execute_tool = _exec
    await gateway.start_nats_listener()

    await client.call_tool("grep", {"pattern": "a.*b", "flags": ["-i"], "n": 3}, timeout_s=5.0)

    assert seen["tool"] == "grep"
    assert seen["args"] == {"pattern": "a.*b", "flags": ["-i"], "n": 3}


@pytest.mark.asyncio
async def test_concurrent_calls_do_not_cross_wires(gateway, client):
    """并发调用必须按 request_id 各回各的 —— 串了线就是把 A 的结果给了 B。"""

    async def _exec(tool_name: str, arguments: dict, **_kw: Any) -> Any:
        # 故意让先发的后返回,逼出"按顺序配对"这种错误实现。
        await asyncio.sleep(0.05 if arguments.get("slow") else 0.0)
        return {"echo": arguments.get("tag")}

    gateway.execute_tool = _exec
    await gateway.start_nats_listener()

    results = await asyncio.gather(
        client.call_tool("t", {"tag": "slow-one", "slow": True}, timeout_s=5.0),
        client.call_tool("t", {"tag": "fast-one"}, timeout_s=5.0),
    )

    assert results[0]["result"] == {"echo": "slow-one"}, "慢的那条拿到了别人的结果"
    assert results[1]["result"] == {"echo": "fast-one"}, "快的那条拿到了别人的结果"


# ── 2. 失败路径:任何情况都必须回一条,不能让调用方悬着 ────────────────────────


@pytest.mark.asyncio
async def test_tool_failure_comes_back_as_an_error_not_a_hang(gateway, client):
    """工具报错也要回一条。不回 = 调用方一直等到超时,错误原因还丢了。"""
    _tool_returns(gateway, {"success": False, "error": "tool blew up"})
    await gateway.start_nats_listener()

    result = await client.call_tool("boom", {}, timeout_s=5.0)

    assert result["success"] is False
    assert "tool blew up" in result["error"]


@pytest.mark.asyncio
async def test_tool_exception_comes_back_as_an_error(gateway, client):
    """工具抛异常同理 —— 网关兜住,转成错误响应发回去。"""

    async def _exec(tool_name: str, arguments: dict, **_kw: Any) -> Any:
        raise RuntimeError("内部炸了")

    gateway.execute_tool = _exec
    await gateway.start_nats_listener()

    result = await client.call_tool("boom", {}, timeout_s=5.0)

    assert result["success"] is False
    assert "内部炸了" in result["error"]


@pytest.mark.asyncio
async def test_malformed_arguments_json_comes_back_as_an_error(bus, gateway, client):
    """坏 JSON 在网关侧就被挡下,并回一条错误 —— 不能静默丢弃请求。"""
    _tool_returns(gateway, {"ok": True})
    await gateway.start_nats_listener()

    got: List[Any] = []
    await bus.subscribe_mcp_results(lambda d: got.append(d))
    await bus._publish(
        "galaxy.mcp.calls",
        {"request_id": "bad-json-1", "tool_name": "t", "arguments_json": "{not json"},
    )
    await asyncio.sleep(0.1)

    assert got, "坏 JSON 的请求没有任何响应 —— 调用方会一直等"
    assert got[0]["request_id"] == "bad-json-1"
    assert got[0]["is_error"] is True


@pytest.mark.asyncio
async def test_no_gateway_listening_times_out_cleanly(client):
    """没有网关在听时,调用方要自己超时收场,而不是永远挂着。"""
    result = await client.call_tool("nobody-home", {}, timeout_s=0.3)

    assert result["success"] is False
    assert "timeout" in result["error"]


@pytest.mark.asyncio
async def test_unusable_bus_fails_fast_instead_of_waiting(client):
    """总线不可用时立刻返回,不该白等一个超时。"""
    bus = NATSBus()  # 既没连网络也没开降级总线
    client._nats = bus

    result = await client.call_tool("t", {}, timeout_s=5.0)

    assert result["success"] is False
    assert result["error"] == "nats_unavailable"


# ── 3. 不泄漏 ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pending_table_is_drained_on_success_and_on_timeout(gateway, client):
    """成功和超时两条路径都要把 future 从 _pending 里摘掉。

    只在成功路径清理的话,每一次超时都会永久留下一条 —— 一个慢慢长大的泄漏,
    而且 pending_count() 从此再也不能用来判断"现在有多少调用在飞"。
    """
    _tool_returns(gateway, {"ok": True})
    await gateway.start_nats_listener()
    await client.call_tool("t", {}, timeout_s=5.0)
    assert client.pending_count() == 0, "成功后没清干净"

    gateway.execute_tool = None  # 让网关这一端塌掉,逼出超时
    await client.call_tool("t", {}, timeout_s=0.3)
    assert client.pending_count() == 0, "超时后没清干净"


@pytest.mark.asyncio
async def test_start_is_idempotent(client, bus):
    """重复 start 不能订第二次 —— 否则每条结果会被处理多遍。"""
    first = await client.start()
    second = await client.start()

    assert first["success"] is True
    assert second.get("already_started") is True


@pytest.mark.asyncio
async def test_late_result_after_timeout_is_dropped_silently(gateway, client, bus):
    """超时之后才到的结果直接丢掉 —— 没人等它了,不该抛异常。"""
    got_error: List[Any] = []
    await gateway.start_nats_listener()
    await client.start()

    try:
        await client._on_result({"request_id": "nobody-waiting", "is_error": False, "result_json": "{}"})
    except Exception as exc:  # pragma: no cover
        got_error.append(exc)

    assert not got_error, f"迟到的结果不该抛:{got_error}"


# ── 4. 主题就是契约里写的那两条 ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_two_subjects_are_exactly_what_the_contract_says(bus, gateway, client):
    """``galaxy.mcp.calls`` / ``galaxy.mcp.results`` —— proto 里写死的那两条。

    改主题等于把另一端断掉,必须让这条先红。
    """
    seen: Dict[str, List[Any]] = {"calls": [], "results": []}
    await bus.subscribe("galaxy.mcp.calls", lambda d: seen["calls"].append(d), durable="probe-calls")
    await bus.subscribe("galaxy.mcp.results", lambda d: seen["results"].append(d), durable="probe-results")

    _tool_returns(gateway, {"ok": True})
    await gateway.start_nats_listener()
    await client.call_tool("echo", {"a": 1}, timeout_s=5.0)

    assert seen["calls"], "galaxy.mcp.calls 上没有请求"
    assert seen["results"], "galaxy.mcp.results 上没有结果"
    assert seen["calls"][0]["tool_name"] == "echo"
    assert json.loads(seen["calls"][0]["arguments_json"]) == {"a": 1}
    assert seen["results"][0]["request_id"] == seen["calls"][0]["request_id"]


# ── 5. 本机没有的工具去问网格,且绝不成环 ─────────────────────────────────────


@pytest.mark.asyncio
async def test_local_tool_wins_and_never_touches_the_mesh(bus, gateway, monkeypatch):
    """本机有就本机跑 —— 不该白白绕一圈总线。"""
    from core import mcp_call_client as ccm

    async def _local(tool_name, arguments):
        return {"from": "local"}

    gateway._execute_tool_locally = _local
    called: List[Any] = []
    monkeypatch.setattr(ccm.MCPCallClient, "call_tool", lambda *a, **k: called.append(1))

    result = await gateway.execute_tool("t", {})

    assert result == {"from": "local"}
    assert not called, "本机能跑却还是去问了网格"


@pytest.mark.asyncio
async def test_missing_local_tool_falls_back_to_the_mesh(bus, gateway):
    """本机没有,就问网格 —— 这是把 MCP 放到总线上的全部意义。

    这条同时也是 ``publish_mcp_call`` 的**第一个真实生产调用方**:在此之前它
    有发布器、没有任何人调,``galaxy.mcp.calls`` 上一条消息都没有过。
    """

    async def _no_local(tool_name, arguments):
        return None

    gateway._execute_tool_locally = _no_local

    # 网格上的另一台:用第二个网关实例扮演,它本机"有"这个工具。
    remote = MCPDynamicGateway(nats=bus)

    async def _remote_local(tool_name, arguments):
        return {"from": "mesh", "tool": tool_name}

    remote._execute_tool_locally = _remote_local
    await remote.start_nats_listener()

    from core.mcp_call_client import MCPCallClient

    MCPCallClient._instance = MCPCallClient(nats=bus)
    try:
        result = await gateway.execute_tool("remote-only-tool", {"x": 1})
    finally:
        MCPCallClient._instance = None

    assert result == {"from": "mesh", "tool": "remote-only-tool"}


@pytest.mark.asyncio
async def test_a_call_arriving_over_nats_never_republishes(bus, gateway):
    """从网格收到的调用,本机没有就回 not_found —— **不能**再发上 calls。

    再发一次就是让消息在网关之间来回弹,而且每弹一次换一个 request_id,永不收敛。
    这条直接数 ``galaxy.mcp.calls`` 上的消息条数:只该有最初那一条。
    """

    async def _no_local(tool_name, arguments):
        return None

    gateway._execute_tool_locally = _no_local
    await gateway.start_nats_listener()

    calls: List[Any] = []
    results: List[Any] = []
    await bus.subscribe("galaxy.mcp.calls", lambda d: calls.append(d), durable="loop-probe-calls")
    await bus.subscribe_mcp_results(lambda d: results.append(d))

    await bus._publish(
        "galaxy.mcp.calls",
        {"request_id": "loop-1", "tool_name": "nowhere", "arguments_json": "{}"},
    )
    await asyncio.sleep(0.3)

    assert len(calls) == 1, f"调用被重新发布了 {len(calls)} 次 —— 成环了"
    assert results and results[0]["is_error"] is True, "应当老实回一条 not_found"


@pytest.mark.asyncio
async def test_mesh_fallback_is_skipped_when_the_bus_is_unusable(gateway):
    """总线不可用时不去问网格,直接回本机的 not_found —— 不该白等一个超时。"""
    gateway._nats = NATSBus()  # 既没连也没开降级总线

    async def _no_local(tool_name, arguments):
        return None

    gateway._execute_tool_locally = _no_local

    result = await gateway.execute_tool("nowhere", {})

    assert result["success"] is False
    assert "not found" in result["error"]
