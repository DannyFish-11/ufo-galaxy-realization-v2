"""MCP 双栈:同一个客户端要能同时接住有握手的旧服务端与无握手的 2026-07-28 服务端。

守的是三件事:

1. **一处定义** —— 协议版本不许再在各个客户端里各写一遍(此前 ``core/mcp_loader``
   写 ``2025-11-25``、``mcp_bridge/bridge`` 写 ``2024-11-05``)。
2. **读回协商结果** —— 老规范里版本是协商的,服务端可以选一个跟提议不同的。
   此前两处客户端都没读这个字段,服务端降级了也不知道。
3. **无握手也能干活** —— 2026-07-28 删掉了 ``initialize``(SEP-2575),服务端对它回
   ``-32601``;那是信号不是失败。

下面用**真的 stdio 子进程服务端**验证,不是 mock:两个假服务端一个故意降级、一个
严格校验 ``_meta`` 少一个字段就报错 —— 后者保证"注入了 ``_meta``"这件事是被真校验过的,
而不是我们自说自话。
"""

from __future__ import annotations

import asyncio
import json
import sys
import textwrap

import pytest

from core.mcp_protocol import (
    HANDSHAKE_PROTOCOL_VERSION,
    META_CLIENT_CAPABILITIES,
    META_CLIENT_INFO,
    META_PROTOCOL_VERSION,
    STATELESS_PROTOCOL_VERSION,
    attach_protocol_meta,
    is_method_not_found,
    negotiated_version,
)

# ── 纯函数 ────────────────────────────────────────────────────────────────


def test_meta_carries_all_three_reserved_fields():
    meta = attach_protocol_meta({})["_meta"]
    assert meta[META_PROTOCOL_VERSION] == STATELESS_PROTOCOL_VERSION
    assert META_CLIENT_CAPABILITIES in meta
    assert META_CLIENT_INFO in meta


def test_meta_never_clobbers_caller_keys():
    """只补协议保留字段,不吃掉调用方自己放的东西。"""
    out = attach_protocol_meta({"_meta": {"mine": 1, META_PROTOCOL_VERSION: "手写的"}})
    assert out["_meta"]["mine"] == 1
    assert out["_meta"][META_PROTOCOL_VERSION] == "手写的", "调用方显式给的值优先"


def test_attach_does_not_mutate_the_callers_dict():
    original = {"a": 1}
    attach_protocol_meta(original)
    assert original == {"a": 1}, "不许原地改调用方的对象"


def test_meta_can_be_switched_off(monkeypatch):
    """逃生开关:真遇上见到未知 params 就报错的实现时,不改代码也能关掉。"""
    monkeypatch.setenv("GALAXY_MCP_REQUEST_META", "off")
    assert attach_protocol_meta({"a": 1}) == {"a": 1}


@pytest.mark.parametrize(
    "response,expected",
    [
        ({"error": {"code": -32601, "message": "Method not found"}}, True),
        ({"error": {"code": -32603, "message": "boom"}}, False),
        ({"error": {"message": "METHOD NOT FOUND"}}, True),  # 只给文字不给码的实现
        ({"result": {}}, False),
        (None, False),
    ],
)
def test_method_not_found_detection(response, expected):
    assert is_method_not_found(response) is expected


def test_negotiated_version_reports_a_downgrade():
    version, warning = negotiated_version({"protocolVersion": "2024-11-05"}, server_id="s")
    assert version == "2024-11-05", "以服务端选定的为准,不是我们提议的"
    assert warning and "2024-11-05" in warning, "对不上必须说出来"


def test_negotiated_version_flags_a_missing_field():
    version, warning = negotiated_version({}, server_id="s")
    assert version == HANDSHAKE_PROTOCOL_VERSION
    assert warning, "服务端不给版本本身就不合规,不能当作'就是我们提议的那版'"


def test_negotiated_version_is_quiet_when_it_agrees():
    version, warning = negotiated_version({"protocolVersion": HANDSHAKE_PROTOCOL_VERSION})
    assert version == HANDSHAKE_PROTOCOL_VERSION
    assert warning is None


# ── 真子进程服务端 ────────────────────────────────────────────────────────

_OLD_SERVER = """
import json, sys
def send(o):
    sys.stdout.write(json.dumps(o) + "\\n"); sys.stdout.flush()
for line in sys.stdin:
    line = line.strip()
    if not line: continue
    try: req = json.loads(line)
    except Exception: continue
    m, rid, params = req.get("method"), req.get("id"), req.get("params") or {}
    if m == "initialize":
        # 故意降级:客户端提议什么都回 2024-11-05
        send({"jsonrpc":"2.0","id":rid,"result":{"protocolVersion":"2024-11-05",
             "serverInfo":{"name":"fake-old","version":"1.0"},"capabilities":{"tools":{}}}})
    elif m == "tools/list":
        send({"jsonrpc":"2.0","id":rid,"result":{"tools":[
            {"name":"echo","description":"echo","inputSchema":{"type":"object"}},
            {"name":"__seen_meta__","description":json.dumps(params.get("_meta")),
             "inputSchema":{"type":"object"}}]}})
    elif m in ("resources/list","prompts/list"):
        send({"jsonrpc":"2.0","id":rid,"result":{m.split("/")[0]:[]}})
    elif rid is not None:
        send({"jsonrpc":"2.0","id":rid,"error":{"code":-32601,"message":"Method not found"}})
"""

_NEW_SERVER = """
import json, sys
PV="io.modelcontextprotocol/protocolVersion"
CC="io.modelcontextprotocol/clientCapabilities"
def send(o):
    sys.stdout.write(json.dumps(o) + "\\n"); sys.stdout.flush()
for line in sys.stdin:
    line = line.strip()
    if not line: continue
    try: req = json.loads(line)
    except Exception: continue
    m, rid, params = req.get("method"), req.get("id"), req.get("params") or {}
    if m == "initialize":
        # 2026-07-28 没有 initialize
        send({"jsonrpc":"2.0","id":rid,"error":{"code":-32601,"message":"Method not found"}}); continue
    meta = params.get("_meta") or {}
    missing = [k for k in (PV, CC) if k not in meta]
    if missing and rid is not None:
        # 严格:少一个保留字段就拒 —— 这样"注入了 _meta"才是被真校验过的
        send({"jsonrpc":"2.0","id":rid,"error":{"code":-32602,"message":"missing "+str(missing)}}); continue
    if m == "tools/list":
        send({"jsonrpc":"2.0","id":rid,"result":{"tools":[
            {"name":"echo","description":"echo","inputSchema":{"type":"object"}},
            {"name":"__seen_version__","description":str(meta.get(PV)),
             "inputSchema":{"type":"object"}}]}})
    elif m in ("resources/list","prompts/list"):
        send({"jsonrpc":"2.0","id":rid,"result":{m.split("/")[0]:[]}})
    elif rid is not None:
        send({"jsonrpc":"2.0","id":rid,"error":{"code":-32601,"message":"Method not found"}})
"""


@pytest.fixture()
def servers(tmp_path):
    old = tmp_path / "srv_old.py"
    new = tmp_path / "srv_new.py"
    old.write_text(textwrap.dedent(_OLD_SERVER), encoding="utf-8")
    new.write_text(textwrap.dedent(_NEW_SERVER), encoding="utf-8")
    return f"{sys.executable} {old}", f"{sys.executable} {new}"


async def _drive_bridge(command: str, server_id: str):
    from mcp_bridge.bridge import MCPBridgeProcess, MCPBridgeSpec

    proc = MCPBridgeProcess(MCPBridgeSpec(server_id=server_id, command=command, startup_timeout=30.0))
    try:
        started = await proc.start()
        tools = await proc.list_tools() if started else []
        return started, tools, proc.protocol_version
    finally:
        await proc.stop()


@pytest.mark.timeout(90)
def test_bridge_against_a_handshake_server_reads_back_the_downgrade(servers):
    old, _ = servers
    started, tools, version = asyncio.run(_drive_bridge(old, "old"))
    assert started
    assert version == "2024-11-05", "必须以服务端选定的为准 —— 此前这个字段根本没读过"

    seen = next(t["description"] for t in tools if t["name"] == "__seen_meta__")
    meta = json.loads(seen)
    assert meta, "老服务端也应当收到 _meta —— 它是加法,对老服务端无害"
    assert meta[META_PROTOCOL_VERSION] == STATELESS_PROTOCOL_VERSION


@pytest.mark.timeout(90)
def test_bridge_against_a_handshakeless_server_still_works(servers):
    """2026-07-28 服务端没有 initialize,且严格校验 _meta —— 两条都得过。"""
    _, new = servers
    started, tools, version = asyncio.run(_drive_bridge(new, "new"))
    assert started, "-32601 是'对面无握手'的信号,不是失败"
    assert version == STATELESS_PROTOCOL_VERSION

    names = [t["name"] for t in tools]
    assert "echo" in names, "被服务端的 _meta 严格校验拒了 —— 说明 _meta 没真的带上"
    seen = next(t["description"] for t in tools if t["name"] == "__seen_version__")
    assert seen == STATELESS_PROTOCOL_VERSION


async def _drive_loader(command: str, name: str):
    from core.mcp_loader import MCPLoader

    loader = MCPLoader()
    result = await loader.load(name, command=command)
    server_id = result.get("server_id", "")
    server = loader.servers.get(server_id)
    try:
        return (
            result.get("success", False),
            getattr(server, "protocol_version", ""),
            [t.name for t in getattr(server, "tools", [])],
        )
    finally:
        try:
            await loader.unload(server_id)
        except Exception:  # noqa: BLE001 — 卸载失败不该影响断言
            pass


@pytest.mark.timeout(90)
def test_loader_against_a_handshake_server_reads_back_the_downgrade(servers):
    old, _ = servers
    ok, version, tools = asyncio.run(_drive_loader(old, "old"))
    assert ok
    assert version == "2024-11-05"
    assert "echo" in tools


@pytest.mark.timeout(90)
def test_loader_against_a_handshakeless_server_still_works(servers):
    _, new = servers
    ok, version, tools = asyncio.run(_drive_loader(new, "new"))
    assert ok
    assert version == STATELESS_PROTOCOL_VERSION
    assert "echo" in tools, "被 _meta 严格校验拒了"


def test_no_client_hardcodes_a_protocol_version():
    """一处定义:协议版本只许出现在 core/mcp_protocol 里。

    这条守的是回归 —— 此前两个客户端各硬写一个版本,而且不一样。
    """
    from pathlib import Path

    repo = Path(__file__).resolve().parent.parent
    offenders = []
    for rel in ("core/mcp_loader.py", "mcp_bridge/bridge.py"):
        text = (repo / rel).read_text(encoding="utf-8")
        for line in text.splitlines():
            if '"protocolVersion"' in line and ":" in line and "get(" not in line:
                offenders.append(f"{rel}: {line.strip()}")
    assert not offenders, "协议版本又被硬写回客户端里了:\n" + "\n".join(offenders)
