"""模型能用节点了,危险的先问人(第 10 轮,所有者 2026-11-01 的决定)。

「节点可以开放给模型,但是要确保他调用相关的东西;高权限、高危险的需要跟之前那些一样,交给人确认。」

* ``nodes__list`` 查(目录 / 按用途找 / 一个节点的动作、参数、档、调了要不要先问人),``nodes__invoke`` 调;
* 每个动作一个档(``core/node_action_risk.py``):危险与极危险**总要问人**,「会改东西」只在谨慎档问,只读不问;
* 问人只经 ``core.approval_gate.request_approval``;没批就不执行;批过的这一次,节点拨盘门认(一次调用只问一次);
* 认不出 / 有歧义 / 缺必填参数 —— 不执行,照实说(不替模型猜)。

接通时顺带查出、一并修掉的(都是「进程内调不通」):

* 模板生成的服务型入口(命令行、网页请求、自主学习、多设备协调)``method(**params)``,而服务方法收一个请求对象 ——
  ``execute(command="ls")`` 一调就错;它们的 ``help`` 也是写死的、与服务上真有的方法对不上;
* 通用入口把节点的路由函数当成了入口或工厂:Node_35 的 ``execute``、Node_55 的 ``process`` 收请求对象;
  Node_118 有一条路由叫 ``get_instance(instance_id)``,通用入口把它当工厂调、缺参数就放弃,整个节点载不成;
* ``get_instance()`` 回服务对象的四个节点(语音、图像分析、工作流、网关),桥在服务对象上找不到 ``app``;
* Node_125 的应用叫 ``_health_app``,桥找不到。
* 本进程里起过一份、后来节点自己的进程也起来了:两份并存,状态分家 —— 进程那份一答话就把这份收掉。
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import textwrap

import httpx
import pytest

import core.approval_gate as gate
import core.autonomy_policy as ap
from core.node_action_risk import CRITICAL, DANGEROUS, LEVELS, MODERATE, SAFE, grade, needs_human

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── 每个动作的档 ──────────────────────────────────────────────────────────────────

_PINNED = [
    # (节点, 动作, HTTP 方法, 处理函数名, 至少这一档)
    ("Node_122_Shell", "execute", "", "", CRITICAL),
    ("Node_122_Shell", "get_env", "", "", CRITICAL),
    ("Node_09_Sandbox", "execute", "POST", "execute_code", CRITICAL),
    ("Node_03_SecretVault", "get_secret", "GET", "get_secret", CRITICAL),
    ("Node_39_SSH", "execute", "POST", "execute_command", CRITICAL),
    ("Node_43_MAVLink", "takeoff", "POST", "takeoff", CRITICAL),
    ("Node_43_MAVLink", "arm", "POST", "arm", CRITICAL),
    ("Node_127_BambuLab", "gcode", "POST", "send_gcode", CRITICAL),
    ("Node_89_APIGateway", "proxy", "GET", "proxy_to_node", CRITICAL),
    ("Node_71_MultiDeviceCoordination", "parallel", "POST", "execute_parallel", CRITICAL),
    ("Node_77_TaskScheduler", "create", "POST", "job_create", CRITICAL),
    ("Node_34_Scrcpy", "install", "POST", "install_apk", CRITICAL),
    ("Node_12_Postgres", "query", "POST", "execute_query", CRITICAL),
    ("Node_16_Email", "send", "POST", "send_email", DANGEROUS),
    ("Node_07_Git", "push", "POST", "push", DANGEROUS),
    ("Node_11_GitHub", "create", "POST", "pulls_create", DANGEROUS),
    ("Node_06_Filesystem", "delete", "DELETE", "delete_file", DANGEROUS),
    ("Node_120_File", "delete", "", "", DANGEROUS),
    ("Node_36_UIAWindows", "click", "", "", DANGEROUS),
    ("Node_36_UIAWindows", "type_text", "", "", DANGEROUS),
    ("Node_27_SmartHome", "control", "", "", DANGEROUS),
    ("Node_46_Camera", "capture", "POST", "capture_photo", DANGEROUS),
    ("Node_46_Camera", "frame", "GET", "get_stream_frame", DANGEROUS),
    ("Node_106_GitHubFlow", "issue_to_pr", "GET", "workflow_issue_to_pr", DANGEROUS),
    ("Node_121_Web", "post", "POST", "http_post", DANGEROUS),
    ("Node_66_ConfigManager", "set", "POST", "set_config", DANGEROUS),
    ("Node_69_BackupRestore", "restore", "POST", "restore_backup", DANGEROUS),
    ("Node_82_NetworkGuard", "scan", "POST", "scan_ports", DANGEROUS),
]


@pytest.mark.parametrize("node, action, method, handler, floor", _PINNED)
def test_high_risk_actions_are_graded_high(node, action, method, handler, floor):
    got = grade(node, action, method=method, handler=handler)
    assert LEVELS.index(got.level) >= LEVELS.index(floor), (node, action, got)
    assert got.why


@pytest.mark.parametrize(
    "node, action, method, handler",
    [
        ("Node_23_Time", "now", "GET", "get_current_time"),
        ("Node_54_SymbolicMath", "solve", "POST", "sympy_solve"),
        ("Node_22_BraveSearch", "search", "", ""),
        ("Node_11_GitHub", "list", "POST", "issues_list"),  # POST 也可以只是读
        ("Node_36_UIAWindows", "screenshot", "", ""),
        ("Node_122_Shell", "list_processes", "", ""),
    ],
)
def test_reading_and_computing_are_safe(node, action, method, handler):
    assert grade(node, action, method=method, handler=handler).level == SAFE


def test_a_generic_http_node_is_graded_by_the_method_it_will_use():
    assert grade("Node_08_Fetch", "fetch", method="POST", handler="fetch", params={"url": "u"}).level == SAFE
    assert (
        grade("Node_08_Fetch", "fetch", method="POST", handler="fetch", params={"method": "DELETE"}).level == DANGEROUS
    )
    batch = {"requests": [{"url": "a"}, {"url": "b", "method": "put"}]}
    assert grade("Node_08_Fetch", "batch", method="POST", handler="fetch_batch", params=batch).level == DANGEROUS


def test_dangerous_and_critical_always_ask_whatever_the_dial():
    for dial in ("safe", "guided", "autonomous"):
        assert needs_human(CRITICAL, dial) and needs_human(DANGEROUS, dial)
        assert not needs_human(SAFE, dial)
    assert needs_human(MODERATE, "safe") and not needs_human(MODERATE, "guided")
    assert not needs_human(MODERATE, "autonomous")


# ── 全部节点:每个动作都有档、高危的词一律不低于「危险」 ─────────────────────────────

_SCAN = textwrap.dedent("""
    import json, logging, sys
    logging.disable(logging.CRITICAL)
    from core.node_catalog import catalog_nodes
    from core.node_actions import list_actions
    out = {}
    for n in catalog_nodes():
        acts, source = list_actions(n["dir"])
        out[n["dir"]] = {"runnable": n.get("runnable", True), "source": source,
                         "actions": [[a.name, a.method, a.handler, a.grade.level] for a in acts]}
    sys.stdout.write(json.dumps(out, ensure_ascii=False))
    """)


@pytest.fixture(scope="module")
def every_node(tmp_path_factory):
    """把 125 个节点都载一遍(在子进程里,不让节点模块的导入副作用留在测试进程)。"""
    env = {**os.environ, "GALAXY_DATA_DIR": str(tmp_path_factory.mktemp("scan"))}
    done = subprocess.run([sys.executable, "-c", _SCAN], cwd=REPO, env=env, capture_output=True, text=True, timeout=600)
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout)


def test_every_runnable_node_lists_its_actions_or_says_why_not(every_node):
    assert len(every_node) >= 120
    silent = {n: v["source"] for n, v in every_node.items() if v["runnable"] and not v["actions"]}
    for node, source in silent.items():
        assert "载不进来" in source, f"{node} 一个动作都列不出来,也没说为什么:{source}"
    assert len(silent) <= 3, silent  # 这里缺的只能是本机缺依赖(PortAudio 之类)


_HIGH_WORDS = ("execute", "shell", "install", "proxy", "gcode", "delete", "remove", "send", "push", "upload", "kill")


def test_no_action_named_for_running_deleting_or_sending_is_graded_below_dangerous(every_node):
    low = []
    for node, v in every_node.items():
        for name, _method, handler, level in v["actions"]:
            words = set(f"{name}_{handler}".lower().replace("-", "_").split("_"))
            if words & set(_HIGH_WORDS) and level not in (DANGEROUS, CRITICAL):
                low.append((node, name, handler, level))
            assert level in LEVELS
    assert low == []


def test_device_and_code_running_nodes_never_change_things_without_asking(every_node):
    from core.node_action_risk import _CLASS_FLOOR

    for node, v in every_node.items():
        num = int(node.split("_")[1])
        if num not in _CLASS_FLOOR:
            continue
        for name, method, handler, level in v["actions"]:
            if level == MODERATE:
                pytest.fail(f"{node}.{name}({method} {handler}) 是「会改东西」—— 这类节点的写动作至少是危险")


# ── nodes__list / nodes__invoke ───────────────────────────────────────────────────


@pytest.fixture()
def registry(monkeypatch):
    from core.control_plane import _globals as cp_globals
    from core.control_plane.security_interceptor import ApprovalRegistry

    reg = ApprovalRegistry()
    monkeypatch.setattr(cp_globals, "get_approval_registry", lambda: reg)
    return reg


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(ap, "_LEGACY_GRANTS", str(tmp_path / "legacy_grants.json"))
    monkeypatch.delenv("GALAXY_AUTONOMY", raising=False)
    ap.reset_grant_store()
    monkeypatch.setattr(gate, "publish_pending", lambda: None)
    import core.node_route_bridge as bridge

    monkeypatch.setattr(bridge, "_node_url", lambda node_id: "")  # 不碰本机真在跑的节点进程
    yield
    ap.reset_grant_store()


@pytest.fixture()
def executed(monkeypatch):
    """记下真落到节点上的调用(不真跑命令);治理门、白名单门、拨盘门照常走。"""
    import core.node_invocation as ni
    import core.routes._helpers as helpers

    calls = []

    async def fake_execute(node_info, action, params):
        calls.append((action, dict(params)))
        return {"success": True, "action": action, "result": {"done": action}}

    async def no_golden(self, envelope):
        return None

    monkeypatch.setattr(helpers, "_execute_node", fake_execute)
    monkeypatch.setattr(ni.UnifiedNodeExecutor, "_try_golden_path", no_golden)
    return calls


def _tool(tool, **args):
    from core.node_tools import dispatch_nodes_tool

    return asyncio.run(dispatch_nodes_tool(tool, args, session_id="conv-1"))


def test_the_tools_are_offered_to_the_model_and_graded_as_tools():
    from core.node_tools import nodes_tools_for_agent
    from core.tool_permissions import get_tool_permission_checker

    names = [t["function"]["name"] for t in nodes_tools_for_agent()]
    assert names == ["nodes__list", "nodes__invoke"]
    checker = get_tool_permission_checker()
    assert checker.check("nodes__list").risk_level == "safe"
    invoke = checker.check("nodes__invoke")
    assert invoke.risk_level == "moderate" and not invoke.requires_confirmation, "问不问人由动作的档决定,不是一刀切"

    src = open(os.path.join(REPO, "core", "openclawd.py"), encoding="utf-8").read()
    assert "nodes_tools_for_agent()" in src and '"nodes": dispatch_nodes_tool' in src and '"nodes__",' in src


def test_the_directory_and_the_search_tell_the_model_what_is_there():
    listed = _tool("list")
    assert listed["success"] and listed["count"] >= 120
    assert any("Node_23_Time" in line for lines in listed["groups"].values() for line in lines)
    found = _tool("list", query="搜索")
    assert any(line.startswith("Node_22_BraveSearch") for line in found["nodes"])


def test_a_node_s_actions_come_with_params_risk_and_whether_it_asks():
    shell = _tool("list", node="122")
    rows = {a["action"]: a for a in shell["actions"]}
    assert rows["execute"]["risk"] == CRITICAL and rows["execute"]["asks_first"] is True
    assert {"name": "command", "type": "str", "required": True} in rows["execute"]["params"]
    assert rows["list_processes"]["asks_first"] is False
    assert _tool("list", node="Node_23_Weather")["success"] is False, "编号与名字对不上:不替模型猜是哪个"


def test_what_cannot_be_resolved_is_not_run(executed):
    out = _tool("invoke", node="nope", action="x")
    assert not out["success"] and "nodes__list" in out["error"]
    out = _tool("invoke", node="Node_23_Time", action="timers")
    assert "create_timer" in out["error"] and "delete_timer" in out["error"], "几条路由共用一个名字:列出来让模型挑"
    out = _tool("invoke", node="Node_23_Time", action="create_timer")
    assert "duration_seconds" in out["error"] and "没有执行" in out["error"]
    out = _tool("invoke", node="Node_122_Shell", action="rm_rf")
    assert "没有声明" in out["error"]
    assert executed == []


def test_a_safe_action_runs_without_asking(executed, registry):
    out = _tool("invoke", node="Node_22_BraveSearch", action="search", params={"query": "python"})
    assert out["success"] and out["risk"] == SAFE
    assert executed == [("search", {"query": "python"})] and registry.list_pending() == []


def test_a_critical_action_is_not_run_when_nobody_can_be_asked(executed, registry, monkeypatch):
    import core.interaction.pending_decision_registry as hitl

    async def _none():
        return []

    monkeypatch.setattr(hitl, "_discover_target_devices", _none)
    monkeypatch.setattr(gate, "desktop_reachable", lambda: False)
    out = _tool("invoke", node="Node_122_Shell", action="execute", params={"command": "echo hi"})
    assert not out["success"] and out["needs_confirmation"] and out["risk"] == CRITICAL
    assert executed == []


async def _panel(reg, *, approve=True):
    from fastapi import FastAPI

    from core.routes.approvals import create_router

    for _ in range(300):
        if reg.list_pending():
            break
        await asyncio.sleep(0.01)
    (req,) = reg.list_pending()
    app = FastAPI()
    app.include_router(create_router())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        token = (await c.get("/api/v1/approvals")).json()["approvals"][0]["ack_token"]
        body = {"action": "approve", "token": token, "grant": "session"} if approve else {"action": "deny"}
        assert (await c.post(f"/api/v1/approvals/{req.request_id}", json=body)).status_code == 200
    return req


def _invoke_with_panel(registry, *, approve, **args):
    from core.node_tools import dispatch_nodes_tool

    async def run():
        call = asyncio.create_task(dispatch_nodes_tool("invoke", args, session_id="conv-1"))
        req = await _panel(registry, approve=approve)
        return req, await call

    return asyncio.run(run())


def test_the_person_at_the_computer_approves_a_critical_action_once(executed, registry, monkeypatch):
    """Node_122 也是声明了白名单的节点(拨盘门管它):工具这一步批过,拨盘门认,一次调用只问一次。"""
    monkeypatch.setattr(gate, "desktop_reachable", lambda: True)
    req, out = _invoke_with_panel(
        registry, approve=True, node="Node_122_Shell", action="execute", params={"command": "echo hi"}, reason="看看"
    )
    assert out["success"], out
    assert out["approved_by"] == "desktop" and out["risk"] == CRITICAL
    assert executed == [("execute", {"command": "echo hi"})]
    assert "Node_122_Shell.execute" in req.context["what"] and "看看" in req.context["what"]
    assert req.context["approval_key"] == "node:122:execute"
    assert registry.list_pending() == [], "拨盘门没有再问第二遍"


def test_saying_no_means_it_does_not_run(executed, registry, monkeypatch):
    monkeypatch.setattr(gate, "desktop_reachable", lambda: True)
    _req, out = _invoke_with_panel(
        registry, approve=False, node="Node_122_Shell", action="execute", params={"command": "echo hi"}
    )
    assert not out["success"] and "拒绝" in out["error"] and executed == []


def test_moderate_actions_ask_only_on_the_careful_dial(executed, registry, monkeypatch):
    out = _tool("invoke", node="Node_23_Time", action="create_timer", params={"duration_seconds": 5})
    assert out["risk"] == MODERATE and registry.list_pending() == []
    monkeypatch.setenv("GALAXY_AUTONOMY", "safe")
    monkeypatch.setattr(gate, "desktop_reachable", lambda: True)
    _req, out = _invoke_with_panel(
        registry, approve=False, node="Node_23_Time", action="create_timer", params={"duration_seconds": 5}
    )
    assert not out["success"] and out["needs_confirmation"]


def test_the_tool_budget_leaves_time_for_a_human_only_when_one_will_be_asked():
    assert gate.may_wait_for_a_human("nodes__invoke", {"node": "Node_122_Shell", "action": "execute"})
    assert not gate.may_wait_for_a_human("nodes__invoke", {"node": "Node_23_Time", "action": "now"})


# ── 接通时一并修掉的 ─────────────────────────────────────────────────────────────


from pydantic import BaseModel  # noqa: E402


class _Req(BaseModel):
    """模块级定义:与节点一样(函数里定义的模型在 postponed annotations 下解析不到)。"""

    command: str
    timeout: int = 5


class _Service:
    def execute(self, request: _Req):
        """跑一条命令。"""
        return {"ran": request.command, "timeout": request.timeout}

    def which(self, command: str):
        return {"which": command}


def test_service_style_entries_build_the_request_object_from_the_params():
    from nodes.common import service_entry

    svc = _Service()
    run = service_entry.call
    assert run(svc.execute, {"command": "ls"}, asyncio.run) == {"ran": "ls", "timeout": 5}
    assert run(svc.execute, {"request": {"command": "ls", "timeout": 9}}, asyncio.run)["timeout"] == 9
    assert run(svc.which, {"command": "git"}, asyncio.run) == {"which": "git"}
    listed = service_entry.actions(svc)
    assert listed["execute"]["summary"] == "跑一条命令。"
    assert {"name": "command", "type": "str", "required": True} in listed["execute"]["params"]


def test_the_template_nodes_help_tells_what_the_service_really_has():
    import importlib.util

    path = os.path.join(REPO, "nodes", "Node_121_Web", "fusion_entry.py")
    spec = importlib.util.spec_from_file_location("nodes.Node_121_Web.fusion_entry", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    told = set(mod.execute("help")["actions"])
    assert "api_call" not in told, "模板里写死的动作,服务上没有"
    assert told == {"api_request", "batch_request", "download", "http_request", "scrape"}


@pytest.mark.parametrize(
    "node, why",
    [
        ("Node_118_NodeFactory", "通用入口把路由 get_instance(instance_id) 当成了工厂"),
        ("Node_35_AppleScript", "「入口」execute 其实是一条收请求对象的路由"),
    ],
)
def test_nodes_the_generic_entry_cannot_call_go_straight_to_their_routes(node, why):
    from core.node_actions import _load, use_routes_directly

    assert use_routes_directly(_load(node)), why


def test_a_node_whose_factory_returns_a_service_object_still_has_its_routes_found():
    from core.node_actions import _load
    from core.node_route_bridge import node_app

    for node in ("Node_86_SpeechProcessor", "Node_87_ImageAnalysis", "Node_88_WorkflowEngine", "Node_89_APIGateway"):
        assert node_app(_load(node)) is not None, node


def test_the_node_factory_is_reachable_in_process(executed):
    from core.node_invocation import InvocationSource, invoke_node

    res = asyncio.run(
        invoke_node("Node_118_NodeFactory", "list_templates", {}, invocation_source=InvocationSource.SYSTEM)
    )
    assert res.success and "generic_service" in json.dumps(res.result, ensure_ascii=False), res.error
    assert executed == [], "这个节点走的是路由,不是通用入口"


def test_when_the_node_process_comes_up_the_in_process_copy_is_retired(monkeypatch):
    import core.node_route_bridge as bridge

    closed = []

    class Host:
        app = object()

        def close(self):
            closed.append(True)

    monkeypatch.setitem(bridge._HOSTS, "Node_X", Host())
    monkeypatch.setattr(bridge, "_node_url", lambda node_id: "http://127.0.0.1:1")
    monkeypatch.setattr(bridge, "node_app", lambda info: "app")
    monkeypatch.setattr(bridge, "pick_route", lambda app, action, params: (object(), "GET", ""))
    monkeypatch.setattr(bridge, "build_request", lambda route, params: ("/x", {}, None))

    async def over_http(*a, **k):
        return {"success": True, "result": 1, "via": "http"}

    monkeypatch.setattr(bridge, "_over_http", over_http)
    out = asyncio.run(bridge.call_route("Node_X", {}, "x", {}))
    assert out["success"] and out["note"] == bridge.RETIRED_NOTE
    assert closed == [True] and "Node_X" not in bridge._HOSTS
    again = asyncio.run(bridge.call_route("Node_X", {}, "x", {}))
    assert "note" not in again, "只收一次"


# ── 工具结果交给模型的那段文字(真跑查出:不在 result 键里的结果,模型收到的是空串) ─────────────────────


def test_results_outside_the_result_key_reach_the_model():
    from core.tool_result_text import tool_result_text

    members = {"success": True, "members": [{"name": "小米手表", "online": True}], "candidates": []}
    text = tool_result_text(members)
    assert "小米手表" in text and json.loads(text)["members"][0]["online"] is True, "以前这里是空串"
    assert json.loads(tool_result_text({"success": True, "topics": ["语音"], "_latency_ms": 3.0})) == {
        "topics": ["语音"]
    }


def test_plain_results_and_errors_are_handed_over_as_before_but_as_json():
    from core.tool_result_text import tool_result_text

    assert tool_result_text({"success": True, "result": "42"}) == "42"
    assert json.loads(tool_result_text({"success": True, "result": {"ok": True, "名字": "时间"}})) == {
        "ok": True,
        "名字": "时间",
    }
    assert tool_result_text({"success": False, "error": "没配 Key"}) == "没配 Key"
    refused = tool_result_text({"success": False, "error": "缺必填参数 x", "params": [{"name": "x"}]})
    assert json.loads(refused)["params"] == [{"name": "x"}], "缺了什么、有哪些候选,要一起交过去"


def test_both_tool_loops_use_the_same_wording():
    import inspect

    import core.agent.react_loop as react_loop

    assert "tool_result_text(result)" in inspect.getsource(react_loop)
    src = open(os.path.join(REPO, "core", "openclawd.py"), encoding="utf-8").read()
    assert "result_str = tool_result_text(result)" in src
    assert 'result_str = str(\n                        result.get("result", result.get("error", ""))' not in src


def test_the_agent_loop_hands_a_list_result_to_the_model():
    """经 Agent 工厂的工具循环真走一遍:nodes__list 的结果出现在下一轮交给模型的 tool 消息里。"""
    from core.agent.react_loop import run_react_tool_loop

    seen = []

    class Resp:
        def __init__(self, tool_calls=None, content=""):
            self.tool_calls = tool_calls
            self.content = content

    async def call_llm(messages):
        seen.append([m for m in messages if m.get("role") == "tool"])
        if len(seen) == 1:
            return Resp([{"id": "c1", "type": "function", "function": {"name": "nodes__list", "arguments": "{}"}}])
        return Resp(None, "好了")

    async def dispatch(name, args):
        return {"success": True, "count": 1, "groups": {"工具集成": ["Node_23_Time — 时间"]}}

    messages = [{"role": "user", "content": "有哪些节点"}]
    asyncio.run(run_react_tool_loop(messages=messages, llm_call=call_llm, dispatch_tool=dispatch, max_iterations=3))
    assert "Node_23_Time" in seen[-1][0]["content"]


def test_the_older_node_tool_path_is_graded_the_same_way(monkeypatch):
    """``node__<节点>__<动作>``(能力表里登记了节点能力时的那条路)与 ``nodes__invoke`` 同一套档:同一个动作经哪条路来,问不问人一样。"""
    from core.tool_permissions import ToolPermissionChecker

    monkeypatch.setenv("GALAXY_AUTONOMY", "autonomous")
    checker = ToolPermissionChecker()
    click = checker.check("node__36__click")
    assert click.risk_level == DANGEROUS and click.requires_confirmation
    assert checker.check("node__Node_122_Shell__get_env").risk_level == CRITICAL
    assert not checker.check("node__23__now").requires_confirmation
    assert checker.check("node__Node_06_Filesystem__execute").risk_level == CRITICAL, "按名字登记的更严的那条照旧生效"


def test_the_handler_name_shown_in_the_directory_also_works(executed):
    out = _tool("invoke", node="Node_23_Time", action="get_current_time")
    assert out["success"] and out["risk"] == SAFE, out
