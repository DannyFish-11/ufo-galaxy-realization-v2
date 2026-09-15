"""Node 36 的 HTTP 面也要过动作权限闸 —— 此前只有统一执行器那条路过了。

## 为什么这不是"多此一举"

这个节点有两条入口:统一执行器(治理门 + 权限门 + HITL 三道)和 FastAPI 路由(零道)。
`config/node_catalog.json` 里的动作白名单是运维手上唯一能收紧它的旋钮,而那个旋钮
此前只对第一条路有效 —— 把 `type_text` 删掉,`invoke_node` 会拒,`POST /type` 照常打字。

`test_narrowing_the_manifest_actually_narrows_the_http_surface` 钉的就是这一条:
旋钮得是真的。

## 为什么这条路上 fail-closed

`node_invocation` 在门禁自身出问题时放行 —— 它前后还有两道门。这条路上一道都没有,
所以相反:拿不到门禁就不执行。`test_a_broken_catalog_closes_the_surface_instead_of_opening_it`
钉住这个方向,因为默认值恰恰相反(`_load_permissions` 读不到目录时返回空表,
而空表会让 `evaluate_action_permission` 把节点判成"未声明" → legacy 放行)。
"""

from __future__ import annotations

import pytest

fastapi_testclient = pytest.importorskip("fastapi.testclient")

import core.node_action_permissions as perms  # noqa: E402
import nodes.Node_36_UIAWindows.main as node36  # noqa: E402

NODE_NUM = 36


#: 节点 HTTP 面现在还有一层身份认证(见 tests/test_node_http_auth.py)。这些用例要验的是
#: **动作权限闸**,所以必须带令牌把认证那一层让开 —— 否则它们会因为 401 而红,
#: 或者更糟:断言放宽成接受 401 之后"通过了",而权限闸从此无人测试。
_TEST_TOKEN = "test-token-for-action-gate"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("GALAXY_API_TOKEN", _TEST_TOKEN)
    perms.reset_cache()
    yield fastapi_testclient.TestClient(
        node36.app,
        raise_server_exceptions=False,
        headers={"Authorization": f"Bearer {_TEST_TOKEN}"},
    )
    perms.reset_cache()


@pytest.fixture
def declared():
    perms.reset_cache()
    table = perms._load_permissions()
    assert NODE_NUM in table, "Node 36 应当在目录里声明了动作白名单"
    return list(table[NODE_NUM])


def _force_whitelist(actions):
    """把门禁的白名单换成 actions(None 表示整张表为空,模拟目录读不进来)。"""
    perms._cache = {} if actions is None else {NODE_NUM: list(actions)}


# ── 旋钮得是真的 ─────────────────────────────────────────────────────────────
def test_narrowing_the_manifest_actually_narrows_the_http_surface(client, declared):
    """从白名单里删掉 type_text,`POST /type` 就该被拒。

    这是整个补丁的理由:此前统一执行器会拒,而 HTTP 照常打字 —— 于是 manifest
    在这条路上是一句空话。
    """
    _force_whitelist([a for a in declared if a != "type_text"])
    r = client.post("/type", json={"text": "hello"})
    assert r.status_code == 403
    assert "type_text" in r.json()["detail"]


def test_an_action_still_in_the_manifest_is_not_blocked(client, declared):
    """门禁只挡越权,不挡正常调用 —— 否则它就成了一个拒绝一切的开关。

    这里不断言 200:本环境没有 Windows/pyautogui,真正执行必然失败。断言的是
    **没有被门禁拦下**(403/503 都不该出现)。
    """
    _force_whitelist(declared)
    r = client.post("/click", json={"x": 1, "y": 1})
    assert r.status_code not in (403, 503), r.json()


# ── 指名调用任意动作的那条路由 ───────────────────────────────────────────────
def test_mcp_call_cannot_name_an_undeclared_action(client, declared):
    """`/mcp/call` 是唯一能**指名**调用任意动作的入口,也就是最需要门禁的那个。

    注意它此前不是完全没有兜底:`call_tool` 对不认识的名字返回 "Unknown tool"。
    但那个兜底保护的是**拼错的名字**,不是越权 —— 一旦有人往 call_tool 里加了
    动作却忘了写进 manifest(最初提的 run_powershell 正是这个形状),兜底就没了,
    而门禁还在。
    """
    _force_whitelist(declared)
    r = client.post("/mcp/call", json={"tool": "run_powershell", "params": {}})
    assert r.status_code == 403
    assert "run_powershell" in r.json()["detail"]


def test_mcp_call_still_works_for_a_declared_action(client, declared):
    _force_whitelist(declared)
    r = client.post("/mcp/call", json={"tool": "list_windows", "params": {}})
    assert r.status_code not in (403, 503), r.json()


# ── 门禁坏了的时候往哪边倒 ───────────────────────────────────────────────────
def test_a_broken_catalog_closes_the_surface_instead_of_opening_it(client):
    """目录读不进来时 **拒绝**,而不是沿用 legacy 放行。

    `_load_permissions` 读失败返回空表 → `evaluate_action_permission` 认为节点
    "未声明" → 默认放行。那个默认值是给"还没收编的 100+ 个节点"用的,不是给
    一个已经声明了 32 个动作、而且能操作你桌面的节点用的。

    Node 36 是**确定声明了**的;判定回来说它没声明,只能说明门禁坏了。
    """
    _force_whitelist(None)
    r = client.post("/click", json={"x": 1, "y": 1})
    assert r.status_code == 503
    assert "catalog failed to load" in r.json()["detail"]


def test_every_acting_route_goes_through_the_gate():
    """逐条核对:每个**会动手**的路由都调了 `_require_action`。

    用 AST 查而不是人眼看 —— 新加一条路由却忘了过闸,是这一类缺陷的标准复发方式,
    而且它不会有任何症状:那条路由工作得好好的,只是没人管。
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(node36))
    gated = set()
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.AsyncFunctionDef):
            continue
        for call in ast.walk(fn):
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "_require_action":
                gated.add(fn.name)

    acting = {
        "api_click",
        "api_type",
        "api_hotkey",
        "api_move",
        "api_drag",
        "api_screenshot",
        "api_mouse_position",
        "api_screen_size",
        "api_list_windows",
        "api_window",
        "mcp_call",
    }
    assert acting <= gated, f"这些路由没过闸: {sorted(acting - gated)}"


def test_the_liveness_probe_is_deliberately_not_gated(client):
    """`/health` 不过闸,而且这是有意的。

    它是容器的存活探针(`deploy/compose/full.yml` 用 curl 打它)。把存活探针挂在
    另一个子系统上,子系统一坏就是重启循环 —— 那比它想防的问题更糟。
    它也不暴露任何能力:只报告状态,不动手。
    """
    _force_whitelist(None)  # 门禁彻底坏掉的情况下
    assert client.get("/health").status_code == 200


def test_the_readme_table_matches_the_code():
    """README 里的「路由 → 动作名」表必须和代码一致。

    这张表此前就漂过:写了不存在的 `POST /double_click`,`/screenshot` 标成 POST 而
    实际是 GET。文档漂移在别处只是碍事,在**安全面**上会直接误导运维 ——
    照着一张假清单去收紧权限,收紧的是不存在的东西。
    """
    import ast
    import inspect
    import pathlib
    import re

    tree = ast.parse(inspect.getsource(node36))
    code_map = {}
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.AsyncFunctionDef):
            continue
        path = None
        for deco in fn.decorator_list:
            if isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute):
                if deco.args and isinstance(deco.args[0], ast.Constant):
                    path = deco.args[0].value
        if path is None:
            continue
        for call in ast.walk(fn):
            if (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id == "_require_action"
                and call.args
                and isinstance(call.args[0], ast.Constant)
            ):
                code_map[path] = call.args[0].value

    readme = pathlib.Path("nodes/Node_36_UIAWindows/README.md").read_text(encoding="utf-8")
    doc_map = {
        m.group(1): m.group(2) for m in re.finditer(r"\|\s*`(?:POST|GET) (/[\w/]+)`\s*\|\s*`(\w+)`\s*\|", readme)
    }

    assert doc_map, "README 里没找到那张表 —— 表被删了或格式变了"
    assert doc_map == code_map, (
        f"README 与代码对不上\n  只在 README: {sorted(set(doc_map) - set(code_map))}\n"
        f"  只在代码:   {sorted(set(code_map) - set(doc_map))}\n"
        f"  动作名不同: {sorted(k for k in set(doc_map) & set(code_map) if doc_map[k] != code_map[k])}"
    )
