"""调到了节点 ≠ 节点做成了:节点自己回失败,整条调用就是失败(第 8 轮真跑发现)。

真跑时 ``POST /api/v1/nodes/call`` 调 Node_23_Time 与 Node_22_BraveSearch,回的都是::

    200 {"success": true, ..., "result": {"success": false, "error": "No executable method found"}}

外层照报成功,模型、REST 调用方、边说边核的账看到的都是「成功」,失败裹在里面。扫一遍,117 个用通用 fusion 入口的
节点里有 112 个的模块上没有 fusion 入口认得的入口(process / execute / run / handle,或 Node 类)——
进程内调它们一律走不通。这里先把两件事钉住:

1. 结果信封照实:任何一层回 ``success: False``,``NodeInvocationResult.success`` 就是 False(REST 回 502,不是 200);
2. 联网搜索的两个节点(核对线联网那一级要用)接上了真入口;缺 Key 照实说缺 Key。

其余节点的进程内入口(按节点自己的 HTTP 路由桥过去)记在 docs/SYSTEM_STATUS.md 6.20 第 8 轮的待办里。
"""

from __future__ import annotations

import asyncio

import pytest

from core.node_invocation import NodeInvocationResult


def _r(**kw):
    return NodeInvocationResult(node_id="Node_X", action="a", request_id="r", trace_id="t", **kw)


def test_the_node_saying_no_makes_the_call_a_failure():
    res = _r(success=True, result={"success": False, "error": "No executable method found"})
    assert res.success is False and res.node_reported_failure is True
    assert res.error == "No executable method found"
    assert "error" in res.to_legacy_dict() and res.to_legacy_dict()["success"] is False


def test_a_failure_wrapped_one_level_deeper_counts_too():
    res = _r(success=True, result={"success": True, "data": {"success": False, "error": "没配 KEY"}})
    assert res.success is False and res.error == "没配 KEY"


def test_a_real_success_stays_a_success():
    res = _r(success=True, result={"success": True, "data": {"value": 1}})
    assert res.success is True and res.node_reported_failure is False
    assert _r(success=True, result=["not", "a", "dict"]).success is True


def test_the_executor_side_error_is_not_overwritten():
    res = _r(success=False, error="approval_required: 等人批准", result={"success": False, "error": "x"})
    assert res.error.startswith("approval_required") and res.node_reported_failure is False


def test_rest_says_502_when_the_node_said_no():
    from core.routes.nodes import _call_failure_status

    assert _call_failure_status("没配 BRAVE_API_KEY", node_said=True) == 502
    assert _call_failure_status("boom") == 500
    assert _call_failure_status("approval_required: x", node_said=True) == 202


def _execute(node: str, command: str, **params):
    import importlib

    mod = importlib.import_module(f"nodes.{node}.main")
    return asyncio.run(mod.execute(command, **params))


def test_brave_search_has_a_real_entry_and_says_when_the_key_is_missing(monkeypatch):
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    import nodes.Node_22_BraveSearch.main as brave

    monkeypatch.setattr(brave.brave_manager, "api_key", "")
    out = _execute("Node_22_BraveSearch", "search", query="python")
    assert out == {"success": False, "error": "没配 BRAVE_API_KEY,联网搜索用不了"}
    assert "Unknown action" in _execute("Node_22_BraveSearch", "nope", query="x")["error"]
    assert _execute("Node_22_BraveSearch", "search")["error"] == "缺 query"


def test_brave_search_returns_the_results_with_their_snippets(monkeypatch):
    import nodes.Node_22_BraveSearch.main as brave

    monkeypatch.setenv("BRAVE_API_KEY", "k")

    class _Resp:
        status_code = 200

        def json(self):
            return {"web": {"results": [{"title": "T", "url": "https://u", "description": "D"}]}}

    seen = {}

    def fake_get(url, headers=None, params=None, timeout=None):
        seen.update(url=url, token=headers.get("X-Subscription-Token"), q=params.get("q"))
        return _Resp()

    monkeypatch.setattr(brave.requests, "get", fake_get)
    out = _execute("Node_22_BraveSearch", "search", query="python 3.14", count=3)
    assert out["success"] is True and out["results"][0]["description"] == "D"
    assert seen == {"url": f"{brave.BRAVE_API_URL}/web/search", "token": "k", "q": "python 3.14"}


def test_google_search_has_a_real_entry_and_fails_honestly(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_CSE_ID", raising=False)
    import nodes.Node_25_GoogleSearch.main as google

    monkeypatch.setattr(google, "_GOOGLESEARCH_AVAILABLE", False)
    out = _execute("Node_25_GoogleSearch", "search", query="python")
    assert out["success"] is False and "GOOGLE_API_KEY" in out["error"]


@pytest.mark.parametrize("node", ["Node_22_BraveSearch", "Node_25_GoogleSearch"])
def test_the_unified_executor_reaches_the_search_nodes(node, monkeypatch):
    """经 ``invoke_node`` 真走一遍:不再是「No executable method found」,而是节点自己的原因。"""
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    from core.node_invocation import InvocationSource, invoke_node

    res = asyncio.run(invoke_node(node, "search", {"query": "python"}, invocation_source=InvocationSource.SYSTEM))
    assert res.success is False and res.node_reported_failure is True
    assert "No executable method found" not in str(res.error)


# ── 信封照实之后露出来的:Node_120 声明的动作此前多半走不到实现 ─────────────────────────


@pytest.fixture
def files(tmp_path, monkeypatch):
    import nodes.Node_120_File.fusion_entry as fe

    service = fe._import_from_node_main("FileService")(workspace_root=str(tmp_path))
    monkeypatch.setattr(fe, "_service", service)
    return fe, tmp_path


def test_every_declared_file_action_reaches_its_implementation(files):
    fe, root = files
    assert fe.execute("write", {"path": "a.txt", "content": "你好"})["success"] is True
    assert (root / "a.txt").read_text(encoding="utf-8") == "你好"
    read = fe.execute("read", {"path": "a.txt"})
    assert read["success"] is True and "你好" in str(read["result"])
    assert fe.execute("append", {"path": "a.txt", "content": "!"})["success"] is True
    listed = fe.execute("list", {"path": "."})
    assert listed["success"] is True and "a.txt" in str(listed["result"])
    assert fe.execute("info", {"path": "a.txt"})["success"] is True
    assert fe.execute("copy", {"source": "a.txt", "destination": "b.txt"})["success"] is True
    assert fe.execute("move", {"source": "b.txt", "destination": "c.txt"})["success"] is True
    assert fe.execute("hash", {"path": "c.txt"})["success"] is True
    assert fe.execute("search", {"root_path": ".", "pattern": "*.txt"})["success"] is True
    assert fe.execute("delete", {"path": "c.txt"})["success"] is True
    assert not (root / "c.txt").exists() and (root / "a.txt").exists()


def test_a_missing_file_is_an_honest_failure(files):
    fe, _root = files
    out = fe.execute("delete", {"path": "nope.txt"})
    assert out["success"] is False and "未找到操作" not in out["error"]
    bad = fe.execute("write", {"content": "缺 path"})
    assert bad["success"] is False and "path" in bad["error"]


def test_a_path_outside_the_workspace_is_refused(files):
    fe, _root = files
    out = fe.execute("read", {"path": "/etc/hostname"})
    assert out["success"] is False and "outside the workspace" in out["error"]


def test_a_synchronous_node_entry_does_not_run_on_the_event_loop(monkeypatch):
    """模块函数写法的入口(``execute(action, params)``)在工作线程里跑 —— Node_120 的入口里会阻塞地等另一个线程。"""
    import threading
    import types

    from core import node_facade_local as facade

    seen = {}

    def execute(action, params):
        seen["thread"] = threading.current_thread()
        return {"success": True, "result": {"ok": action}}

    mod = types.SimpleNamespace(execute=execute)
    monkeypatch.setattr(facade, "_load_fusion_entry", lambda node_id: mod)

    class _Resolver:
        def resolve_by_node_id(self, node_id):
            return {"node": "Node_X"}

    import core.device_node_resolver as resolver

    monkeypatch.setattr(resolver, "get_resolver", lambda: _Resolver())

    async def go():
        loop_thread = threading.current_thread()
        out = await facade.get_local_node_facade().invoke(node_id="Node_X", action="ping", params={})
        return loop_thread, out

    loop_thread, out = asyncio.run(go())
    assert out["success"] is True and out["result"] == {"ok": "ping"}, out
    assert seen["thread"] is not loop_thread
