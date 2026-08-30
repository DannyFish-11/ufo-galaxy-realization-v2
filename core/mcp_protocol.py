"""
core/mcp_protocol.py
====================
MCP 协议约定的**唯一定义处** —— 版本、客户端身份、每请求 ``_meta``、握手判定。

为什么需要这个模块
------------------
本仓有**两套** MCP 客户端(都是 stdio 子进程 + JSON-RPC):

* ``core/mcp_loader.py``   —— 主加载器;
* ``mcp_bridge/bridge.py`` —— 多语言桥接。

在此之前它们各自硬写了一个协议版本,而且**不一样**::

    core/mcp_loader.py:560     "protocolVersion": "2025-11-25"
    mcp_bridge/bridge.py:68    "protocolVersion": "2024-11-05"    ← 最初那一版

同一个系统对外自称两个版本,是本仓一直在消的那类不一致。

2026-07-28 之后的形状
---------------------
2026-07-28 是 MCP 自发布以来最大的一次修订,对本仓有两点实质影响(其余如
``Mcp-Method`` / ``Mcp-Name`` 头、``Mcp-Session-Id`` 移除、header 路由都只针对
Streamable HTTP,与 stdio 无关):

1. **握手整个没了。** ``initialize`` / ``notifications/initialized`` 在官方
   ``schema/2026-07-28/schema.ts`` 里**一次都不出现**(SEP-2575)。
2. 原先握手一次交换的东西,改成每个请求都带在 ``_meta`` 里:
   ``io.modelcontextprotocol/protocolVersion``(必填)、
   ``io.modelcontextprotocol/clientCapabilities``(必填)、
   ``io.modelcontextprotocol/clientInfo``(建议)。

本仓真正调用的 6 个方法(``tools/list`` ``tools/call`` ``resources/list``
``resources/read`` ``prompts/list`` ``prompts/get``)在新 schema 里**全部原样存活**,
断掉的只有握手那两个。

双栈:为什么可以同时接新旧
--------------------------
关键在于 ``_meta`` 是**加法**:老服务端会忽略不认识的 ``_meta`` 键,新服务端才要求它。
所以一个客户端可以:

* **每个请求都带** 上面三个保留字段 —— 对老服务端无害,对新服务端是必需;
* **仍然尝试** ``initialize`` —— 老服务端正常应答并协商版本;新服务端回
  ``-32601 Method not found``,客户端据此判定"对面是无握手的新版",跳过握手直接干活。

于是不需要预先知道对面是哪一版,也不需要为此配置什么。

顺带修掉的一个活缺陷
--------------------
老规范里版本是**协商**出来的:客户端提议,服务端在响应里回它**实际要用**的那一版,
可能与提议不同。而此前两处客户端都只读了 ``serverInfo`` 与 ``capabilities``::

    server.server_info  = response.result.get("serverInfo", {})
    server.capabilities = response.result.get("capabilities", {})
    # protocolVersion —— 全仓只在发出去那一行出现过,响应里从来没读过

服务端降级了客户端也不知道,继续按自己那版假设走。:func:`negotiated_version`
把这条补上:**读回来、对不上就说出来**。
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("Galaxy.MCP.Protocol")

__all__ = [
    "HANDSHAKE_PROTOCOL_VERSION",
    "STATELESS_PROTOCOL_VERSION",
    "META_PROTOCOL_VERSION",
    "META_CLIENT_INFO",
    "META_CLIENT_CAPABILITIES",
    "JSONRPC_METHOD_NOT_FOUND",
    "client_info",
    "client_capabilities",
    "handshake_params",
    "protocol_meta",
    "attach_protocol_meta",
    "is_method_not_found",
    "negotiated_version",
]

#: 在 ``initialize`` 里**提议**的版本 —— 取"仍然存在握手"的最新一版。
#: 不写 2026-07-28:那一版根本没有 initialize,对它提议毫无意义。
HANDSHAKE_PROTOCOL_VERSION = "2025-11-25"

#: 每请求 ``_meta`` 里**声明**的版本 —— ``_meta`` 那套规矩是 2026-07-28 定的,
#: 所以这里写它。老服务端忽略整个 ``_meta``,不受影响。
STATELESS_PROTOCOL_VERSION = "2026-07-28"

# ── 2026-07-28 的保留 _meta 键(照抄官方 schema,别手写变体)──────────────
META_PROTOCOL_VERSION = "io.modelcontextprotocol/protocolVersion"
META_CLIENT_INFO = "io.modelcontextprotocol/clientInfo"
META_CLIENT_CAPABILITIES = "io.modelcontextprotocol/clientCapabilities"

#: JSON-RPC 2.0 的"方法不存在"。新版服务端对 ``initialize`` 就回这个 —— 它是
#: 我们判定"对面已经是无握手版本"的依据,而不是一个错误。
JSONRPC_METHOD_NOT_FOUND = -32601

CLIENT_NAME = "Galaxy"
CLIENT_VERSION = "2.0.0"

#: 逃生开关。``_meta`` 一直是 MCP 保留的 params 属性,理论上任何版本的服务端都该
#: 忽略不认识的键;但真遇上校验过严、见到未知 params 就报错的实现时,置
#: ``GALAXY_MCP_REQUEST_META=off`` 可以整体关掉,不必改代码。
_META_ENV = "GALAXY_MCP_REQUEST_META"


def _meta_enabled() -> bool:
    raw = os.getenv(_META_ENV)
    if raw is None:
        return True
    return raw.strip().lower() not in ("0", "false", "no", "off")


def client_info() -> Dict[str, str]:
    """客户端身份 —— 握手与 ``_meta`` 用的是同一份,不各写一遍。"""
    return {"name": CLIENT_NAME, "version": CLIENT_VERSION}


def client_capabilities() -> Dict[str, Any]:
    """客户端能力声明。

    只声明**真的实现了**的那些。规范原文:"Servers MUST NOT rely on capabilities
    the client has not declared" —— 反过来说,声明了却没实现,坏的是对面。
    本仓两个客户端都只做"列工具/资源/提示 + 调工具",不提供 roots 变更通知、
    不做 sampling,所以这里是空的。
    """
    return {}


def handshake_params() -> Dict[str, Any]:
    """``initialize`` 的 params —— 给还有握手的服务端(2026-07-28 之前)。"""
    return {
        "protocolVersion": HANDSHAKE_PROTOCOL_VERSION,
        "capabilities": client_capabilities(),
        "clientInfo": client_info(),
    }


def protocol_meta() -> Dict[str, Any]:
    """2026-07-28 要求随每个请求携带的三个保留字段。"""
    return {
        META_PROTOCOL_VERSION: STATELESS_PROTOCOL_VERSION,
        META_CLIENT_CAPABILITIES: client_capabilities(),
        META_CLIENT_INFO: client_info(),
    }


def attach_protocol_meta(params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """把协议 ``_meta`` 并进 ``params``,返回**新字典**(不改调用方的对象)。

    调用方自己放进 ``_meta`` 的键**优先**:这里只补协议保留字段,不覆盖任何
    已有内容 —— 否则将来谁想用 ``_meta`` 传别的东西,会被我们悄悄吃掉。
    """
    merged: Dict[str, Any] = dict(params or {})
    if not _meta_enabled():
        return merged

    existing = merged.get("_meta")
    meta: Dict[str, Any] = dict(existing) if isinstance(existing, dict) else {}
    for key, value in protocol_meta().items():
        meta.setdefault(key, value)
    merged["_meta"] = meta
    return merged


def is_method_not_found(response: Optional[Dict[str, Any]]) -> bool:
    """响应是不是"方法不存在"。

    对 ``initialize`` 而言这**不是失败**,而是"对面是 2026-07-28 及之后的无握手
    服务端"的信号。有的实现不给标准错误码只给文字,所以文字也认一手。
    """
    if not isinstance(response, dict):
        return False
    err = response.get("error")
    if not isinstance(err, dict):
        return False
    if err.get("code") == JSONRPC_METHOD_NOT_FOUND:
        return True
    return "method not found" in str(err.get("message", "")).lower()


def negotiated_version(
    result: Optional[Dict[str, Any]],
    *,
    proposed: str = HANDSHAKE_PROTOCOL_VERSION,
    server_id: str = "",
) -> Tuple[str, Optional[str]]:
    """从 ``initialize`` 的 result 里**读回服务端实际选定的版本**。

    老规范里版本是协商的:我们提议,服务端回它要用的那一版。此前这个字段从来没被
    读过 —— 服务端降级了我们也不知道。这里读回来,并且**对不上就说出来**。

    Args:
        result: ``initialize`` 响应的 ``result``。
        proposed: 我们提议的版本。
        server_id: 仅用于日志。

    Returns:
        ``(实际生效的版本, 需要提醒的话 | None)``。服务端没给版本时退回 ``proposed``
        并给出提醒 —— 那本身就是不合规,不该当作"就是我们提议的那版"。
    """
    if not isinstance(result, dict):
        return proposed, f"MCP 服务端 {server_id or '?'} 的 initialize 没有返回 result,版本无从确认"

    actual = result.get("protocolVersion")
    if not actual:
        return proposed, (
            f"MCP 服务端 {server_id or '?'} 的 initialize 响应里没有 protocolVersion"
            f"(不合规),按提议的 {proposed} 继续"
        )

    actual = str(actual)
    if actual != proposed:
        return actual, (
            f"MCP 服务端 {server_id or '?'} 选定 {actual},与我们提议的 {proposed} 不同 —— " f"后续按 {actual} 走"
        )
    return actual, None
