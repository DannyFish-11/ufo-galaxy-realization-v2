"""
core/mcp_call_client.py — MCP over NATS 的调用方(Brain)这一端
==============================================================

契约在 ``contracts/proto/galaxy/v1/mcp.proto`` 与 ``docs/AGENTIC_OS_ARCHITECTURE.md``
里写了很久:

    galaxy.mcp.calls    Brain → MCP Gateway  (MCPCallRequest)
    galaxy.mcp.results  MCP Gateway → Brain  (MCPCallResponse)

而实际状态是**两头各断一半**:

* ``NATSBus.publish_mcp_call`` —— 有发布器,没有任何订阅方。发出去没人接。
* ``NATSBus.subscribe_mcp_results`` —— 有订阅器,没有任何发布方。订了永远收不到。

两条主题各自"半通",合起来就是这个回路一次也没跑通过。文档、proto、发布器、
订阅器全都在,唯独没有把它们连起来的那段代码 —— 这比整块缺失更难发现,因为
每一处单看都像是好的。

本模块是调用方那一端:发请求、按 ``request_id`` 等结果、超时能自己收场。
网关那一端在 ``core/mcp_gateway.py`` 的 ``start_nats_listener`` /
``_on_nats_call``。

为什么不直接调本地 MCPLoader
----------------------------
本地那条路(``mcp_gateway.execute_tool``)只能用**本进程**里的 MCP server。
走 NATS 这条路,工具可以跑在网格里任何一个节点上 —— 这正是把 MCP 放到总线上
的全部意义。调用方不需要知道工具在哪台机器上。

单机也走得通:总线在本地降级模式下是进程内直投,同一套代码路径不变。
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger("mcp_call_client")

# 默认调用超时。比 MCPCallRequestModel.timeout_ms 的默认值(30s)略长一点:
# 网关那边是拿 timeout_ms 去约束**工具执行**的,这里约束的是"整条来回",
# 包含派发与回程。取一样的值会让网络抖动一下就变成"调用方先超时",
# 而结果其实随后就到了。
_DEFAULT_TIMEOUT_S = 35.0


class MCPCallClient:
    """Brain 侧:把 MCP 工具调用发上网格,并等回结果。

    一个进程一个实例就够(见模块级 :func:`get_mcp_call_client`)。
    """

    _instance: Optional["MCPCallClient"] = None

    def __init__(self, nats: Any = None) -> None:
        self._nats = nats
        # request_id → Future。回调按 id 找人,找不到就丢掉(迟到的结果)。
        self._pending: Dict[str, asyncio.Future] = {}
        self._started = False

    @classmethod
    def get_instance(cls) -> "MCPCallClient":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _bus(self) -> Any:
        if self._nats is None:
            from core.nats_bus import get_nats_bus

            self._nats = get_nats_bus()
        return self._nats

    async def start(self) -> dict:
        """订上 ``galaxy.mcp.results``。幂等 —— 重复调用不会订第二次。"""
        if self._started:
            return {"success": True, "already_started": True}
        bus = self._bus()
        if not bus.is_usable():
            logger.debug("MCPCallClient: 总线不可用,不订阅 galaxy.mcp.results")
            return {"success": False, "error": "nats_unavailable"}
        try:
            await bus.subscribe_mcp_results(self._on_result)
            self._started = True
            logger.info("MCPCallClient: 已订阅 galaxy.mcp.results")
            return {"success": True}
        except Exception as exc:
            logger.error("MCPCallClient: 订阅 galaxy.mcp.results 失败 — %s", exc)
            return {"success": False, "error": str(exc)}

    async def call_tool(
        self,
        tool_name: str,
        arguments: Optional[dict] = None,
        *,
        server_id: str = "",
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        caller_agent_id: str = "",
        caller_task_id: str = "",
    ) -> dict:
        """在网格上调一个 MCP 工具,等它的结果。

        Returns:
            ``{"success": bool, "result": Any, "error": str, "request_id": str}``

        永远不抛:总线不可用、超时、网关报错,都转成 ``success=False`` 的结果字典。
        调用方(通常在某个任务的执行路径上)不该因为工具调用失败而炸掉整条链路。
        """
        from core.schemas.contracts import MCPCallRequestModel, TimestampModel

        request_id = str(uuid.uuid4())
        bus = self._bus()
        if not bus.is_usable():
            return {
                "success": False,
                "error": "nats_unavailable",
                "request_id": request_id,
            }

        # 先订上再发 —— 反过来的话,快速返回的结果会在订阅生效前到达而丢失。
        start_result = await self.start()
        if not start_result.get("success"):
            return {
                "success": False,
                "error": start_result.get("error", "subscribe_failed"),
                "request_id": request_id,
            }

        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._pending[request_id] = future
        try:
            request = MCPCallRequestModel(
                request_id=request_id,
                tool_name=tool_name,
                server_id=server_id,
                arguments_json=json.dumps(arguments or {}, default=str),
                timeout_ms=int(timeout_s * 1000),
                caller_agent_id=caller_agent_id,
                caller_task_id=caller_task_id,
                created_at=TimestampModel.now(),
            )
            pub = await bus.publish_mcp_call(request)
            if not pub.get("success"):
                return {
                    "success": False,
                    "error": f"publish_failed: {pub.get('error', '')}",
                    "request_id": request_id,
                }
            try:
                return await asyncio.wait_for(future, timeout=timeout_s)
            except asyncio.TimeoutError:
                logger.warning("MCPCallClient: %s (%s) 等结果超时 %.1fs", tool_name, request_id, timeout_s)
                return {
                    "success": False,
                    "error": f"timeout after {timeout_s}s",
                    "request_id": request_id,
                }
        finally:
            self._pending.pop(request_id, None)

    async def _on_result(self, data: dict) -> None:
        """把一条 MCPCallResponse 交回给等它的那个 future。

        找不到对应的 future 就丢掉 —— 那是超时之后才到的迟到结果,或者别的进程
        发起的调用(同一条主题上可以有多个 Brain)。这不是错误。
        """
        request_id = str((data or {}).get("request_id") or "")
        future = self._pending.get(request_id)
        if future is None or future.done():
            return

        is_error = bool((data or {}).get("is_error"))
        if is_error:
            err = (data or {}).get("error") or {}
            message = err.get("message") if isinstance(err, dict) else str(err)
            future.set_result(
                {
                    "success": False,
                    "error": message or "mcp_call_failed",
                    "request_id": request_id,
                    "duration_ms": (data or {}).get("duration_ms", 0),
                }
            )
            return

        raw = (data or {}).get("result_json") or "{}"
        try:
            result = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            # 网关发回来的不是合法 JSON —— 原样交回去,比谎报一个空结果好。
            result = raw
        future.set_result(
            {
                "success": True,
                "result": result,
                "request_id": request_id,
                "duration_ms": (data or {}).get("duration_ms", 0),
            }
        )

    def pending_count(self) -> int:
        """当前在等结果的调用数 —— 给状态上报/体检用。"""
        return len(self._pending)


def get_mcp_call_client() -> MCPCallClient:
    """返回进程级 MCP 调用方单例。"""
    return MCPCallClient.get_instance()


__all__ = ["MCPCallClient", "get_mcp_call_client"]
