"""9 个声明了动作白名单的节点,HTTP 面是不是都过闸了。

## 背景

这些节点各有两条入口:

    统一执行器 invoke_node → 治理门 + 动作权限门 + HITL,三道
    自己的 FastAPI 路由     → 一道都没有

`config/node_catalog.json` 的白名单是运维手上唯一能收紧它们的旋钮,而它此前只对
第一条路有效。把某个动作删掉,`invoke_node` 会拒,HTTP 路由照常执行 ——
**那个旋钮在这条路上是假的**。

Node 36 先单独修过一版;这里覆盖全部 9 个,并钉住"不许再有新的漏网节点"。
"""

from __future__ import annotations

import ast
import contextlib
import glob
import importlib
import json
import os
import sys
import types

import pytest

import core.node_action_permissions as perms  # noqa: E402

CATALOG = json.load(open("config/node_catalog.json", encoding="utf-8"))
DECLARED = {
    n["num"]: set(n["permissions"]["actions"]) for n in CATALOG["nodes"] if (n.get("permissions") or {}).get("actions")
}

#: 只报告、不动手的路由 —— 有意不过闸,逐个写明理由。
UNGATED_BY_DESIGN = {
    "/health": "容器存活探针。把它挂在另一个子系统上,子系统一坏就是重启循环",
    "/status": "只报告状态",
    "/tools": "只列出工具清单",
    "/": "根路径,只报告节点信息",
}


def _node_dirs():
    for num in sorted(DECLARED):
        hits = glob.glob(f"nodes/Node_{num}_*")
        if hits:
            yield num, hits[0]


@pytest.fixture(autouse=True)
def _clean_permission_cache():
    perms.reset_cache()
    yield
    perms.reset_cache()


# ── 静态:每条会动手的路由都调了 _require ───────────────────────────────────
@pytest.mark.parametrize("num,node_dir", list(_node_dirs()), ids=lambda v: str(v))
def test_every_acting_route_calls_the_gate(num, node_dir):
    """用 AST 查,不是人眼看。

    新加一条路由却忘了过闸,是这类缺陷的标准复发方式,而且**没有任何症状**:
    那条路由工作得好好的,只是没人管。
    """
    src = open(os.path.join(node_dir, "main.py"), encoding="utf-8").read()
    tree = ast.parse(src)

    ungated = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        path = None
        for deco in fn.decorator_list:
            if (
                isinstance(deco, ast.Call)
                and isinstance(deco.func, ast.Attribute)
                and deco.func.attr in ("get", "post", "put", "delete")
                and deco.args
                and isinstance(deco.args[0], ast.Constant)
            ):
                path = deco.args[0].value
        if path is None or path in UNGATED_BY_DESIGN:
            continue
        calls = {c.func.id for c in ast.walk(fn) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
        # Node_36 用的是自己的 _require_action(先落地的那一版),其余用共享的 _require
        if not ({"_require", "_require_action"} & calls):
            ungated.append(path)

    assert not ungated, f"Node_{num} 这些会动手的路由没过闸: {ungated}"


# ── 静态:过闸用的动作名必须在 manifest 里 ─────────────────────────────────
@pytest.mark.parametrize("num,node_dir", list(_node_dirs()), ids=lambda v: str(v))
def test_gated_action_names_exist_in_the_manifest(num, node_dir):
    """动作名写错的后果是 **403 打死一条本来能用的路由**,而且只在真被调用时才暴露。

    路由名 ≠ 动作名(``/type`` ↔ ``type_text``、``/key`` ↔ ``press_key``),
    所以这一条不是形式主义 —— 8 个节点上有 20 多处两者不同。
    """
    src = open(os.path.join(node_dir, "main.py"), encoding="utf-8").read()
    used = {
        c.args[0].value
        for c in ast.walk(ast.parse(src))
        if isinstance(c, ast.Call)
        and isinstance(c.func, ast.Name)
        and c.func.id in ("_require", "_require_action")
        and c.args
        and isinstance(c.args[0], ast.Constant)
        and isinstance(c.args[0].value, str)
    }
    missing = sorted(used - DECLARED[num])
    assert not missing, f"Node_{num} 过闸用了 manifest 里没有的动作: {missing}"


# ── 动态:真把请求打进去 ─────────────────────────────────────────────────────
LIVE_CASES = [
    # (节点号, 模块, 路径, 请求体, 过闸用的动作名)
    (92, "nodes.Node_92_AutoControl.main", "/click", {"x": 1, "y": 1}, "click"),
    (34, "nodes.Node_34_Scrcpy.main", "/tap", {"x": 1, "y": 1}, "tap"),
    (45, "nodes.Node_45_DesktopAuto.main", "/type", {"text": "a"}, "type"),
    (124, "nodes.Node_124_LinuxDesktopAuto.main", "/type", {"text": "a"}, "type_text"),
    (122, "nodes.Node_122_Shell.main", "/execute", {"command": "ls"}, "execute"),
    (74, "nodes.Node_74_DigitalTwin.main", "/twin/reset", {}, "reset"),
    (27, "nodes.Node_27_SmartHome.main", "/devices/control", {"device_id": "d1", "action": "toggle"}, "control_device"),
]


#: 节点 HTTP 面现在还有一层身份认证(见 tests/test_node_http_auth.py)。这些用例要验的是
#: **动作权限闸**,所以必须带令牌把认证那一层让开 —— 否则它们会因为 401 而红,
#: 或者更糟:断言放宽成接受 401 之后"通过了",而权限闸从此无人测试。
_TEST_TOKEN = "test-token-for-action-gate"


@pytest.fixture(autouse=True)
def _token_env(monkeypatch):
    """用 monkeypatch 设令牌,**不要**直接改 os.environ。

    最初这里是 ``os.environ["GALAXY_API_TOKEN"] = ...``,于是这个变量泄漏给整个
    会话后面的用例 —— ``test_routes_import.py`` 单跑是绿的、跟在这后面跑就红。
    我的测试改变了别人的结果,和之前那个模块级 uvicorn 桩是同一类错误。
    """
    monkeypatch.setenv("GALAXY_API_TOKEN", _TEST_TOKEN)


def _client(module_path):
    testclient = pytest.importorskip("fastapi.testclient")
    try:
        with _uvicorn_stubbed():
            mod = importlib.import_module(module_path)
    except Exception as exc:  # noqa: BLE001 — 缺可选依赖的节点跳过,不是失败
        pytest.skip(f"{module_path} 导入不了(缺依赖): {type(exc).__name__}")
    return testclient.TestClient(
        mod.app,
        raise_server_exceptions=False,
        headers={"Authorization": f"Bearer {_TEST_TOKEN}"},
    )


@pytest.mark.parametrize("num,mod,path,body,action", LIVE_CASES, ids=lambda v: str(v))
def test_narrowing_the_manifest_actually_denies_the_route(num, mod, path, body, action):
    """**这条是整件事的理由。** 从白名单里删掉一个动作,对应路由就该 403。

    在加上这道闸之前:`invoke_node` 会拒,而 HTTP 照常执行。
    """
    c = _client(mod)
    table = perms._load_permissions()
    perms._cache = {num: [a for a in table[num] if a != action]}
    assert c.post(path, json=body).status_code == 403


@pytest.mark.parametrize("num,mod,path,body,action", LIVE_CASES, ids=lambda v: str(v))
def test_a_broken_catalog_closes_the_route_instead_of_opening_it(num, mod, path, body, action):
    """目录读不进来时 **503**,不是沿用 legacy 放行。

    `_load_permissions` 读失败返回空表 → `evaluate_action_permission` 认为节点
    "未声明" → 默认放行。那个默认值是给还没收编的 100+ 个节点用的,不是给一批
    已经声明了动作、又能操作设备/执行命令的节点用的。
    """
    c = _client(mod)
    perms._cache = {}
    assert c.post(path, json=body).status_code == 503


@pytest.mark.parametrize("num,mod,path,body,action", LIVE_CASES, ids=lambda v: str(v))
def test_a_declared_action_is_not_blocked(num, mod, path, body, action):
    """门禁只挡越权。挡住正常调用的门禁会被整个关掉,那比没有更糟。

    不断言 200:这些节点在本环境缺 pyautogui/xdotool/adb,真正执行必然失败。
    断言的是**没有被门禁拦下**。
    """
    c = _client(mod)
    perms.reset_cache()
    assert c.post(path, json=body).status_code not in (403, 503)


# ── 防止再出现漏网的节点 ─────────────────────────────────────────────────────
def test_no_declared_node_is_left_without_a_gate():
    """声明了白名单却一处都没过闸的节点 —— 一个都不该有。

    这一条是给**将来**的:新增一个敏感节点、写了 manifest、却忘了给 HTTP 面接闸,
    在这里变红。当初 9 个节点里有 8 个是这个状态,而没有任何测试发现得了。
    """
    naked = []
    for num, d in _node_dirs():
        src = open(os.path.join(d, "main.py"), encoding="utf-8").read()
        if "_require" not in src:
            naked.append(f"Node_{num}")
    assert not naked, f"这些节点声明了动作白名单,但 HTTP 面一处都没过闸: {naked}"


@contextlib.contextmanager
def _uvicorn_stubbed():
    """只在导入节点模块的那一瞬间塞一个 uvicorn 桩,出了作用域立刻摘掉。

    起因:最初这行写在模块级(``sys.modules.setdefault("uvicorn", ...)``),
    于是这个桩**泄漏到整个 pytest 会话** —— 按字母序排在后面的
    ``test_responses_transport_is_real.py`` 原本因为缺 uvicorn 收集不了、被记成
    collection error,有了桩之后变成能收集、然后失败。我的测试改变了别人的结果。

    节点只在 ``__main__`` 里用 uvicorn 起服务,和这里要验的判定逻辑无关。
    """
    added = "uvicorn" not in sys.modules
    if added:
        sys.modules["uvicorn"] = types.ModuleType("uvicorn")
    try:
        yield
    finally:
        if added:
            sys.modules.pop("uvicorn", None)
