"""节点 HTTP 面的身份认证。

## 和权限闸的分工

`nodes.common.action_gate` 回答"**这个动作**被声明允许了吗";
这一层回答"**调用方是谁**"。只有前者,等于"谁都可以,但只能做白名单里的事" ——
在一个能点鼠标、跑 shell、控手机的节点上,那还差得远。

此前这 9 个节点两个问题都没有答案,而且和仓里其余 122 个节点一样绑 0.0.0.0。

## 不是新造的一套

`core.auth` 早就有:token 轮换、吊销、过期、每设备配对、零配置自签。
网关的 routes/sessions.py、routes/llm.py 和 launcher/services.py 都在用它。
这里只是把同一套接到节点上。
"""

from __future__ import annotations

import contextlib
import glob
import importlib
import json
import os
import sys
import types

import pytest

CATALOG = json.load(open("config/node_catalog.json", encoding="utf-8"))
PROTECTED = sorted(n["num"] for n in CATALOG["nodes"] if (n.get("permissions") or {}).get("actions"))

TOKEN = "test-token-for-node-auth"


@contextlib.contextmanager
def _uvicorn_stubbed():
    """只在导入节点模块时塞桩,出作用域摘掉 —— 模块级 setdefault 会泄漏到整个会话。"""
    added = "uvicorn" not in sys.modules
    if added:
        sys.modules["uvicorn"] = types.ModuleType("uvicorn")
    try:
        yield
    finally:
        if added:
            sys.modules.pop("uvicorn", None)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("GALAXY_API_TOKEN", TOKEN)
    monkeypatch.delenv("GALAXY_NODE_AUTH", raising=False)
    testclient = pytest.importorskip("fastapi.testclient")
    with _uvicorn_stubbed():
        m = importlib.import_module("nodes.Node_92_AutoControl.main")
    return testclient.TestClient(m.app, raise_server_exceptions=False)


BODY = {"x": 1, "y": 1}


def test_an_unauthenticated_request_is_refused(client):
    """此前这里**没有任何认证** —— 同一网段上谁都能点这台机器的鼠标。"""
    r = client.post("/click", json=BODY)
    assert r.status_code == 401


def test_a_wrong_token_is_refused(client):
    assert client.post("/click", json=BODY, headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_a_valid_token_passes_the_auth_layer(client):
    """认证只挡身份,不挡正常调用。挡住正常调用的认证会被整个关掉,那比没有更糟。"""
    r = client.post("/click", json=BODY, headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code != 401


def test_the_liveness_probe_stays_public(client):
    """`deploy/compose/full.yml` 的 healthcheck 是裸 curl,不带令牌。

    把存活探针也要求鉴权,结果是容器永远 unhealthy、反复重启 —— 比它想防的问题更糟。
    它也不暴露能力:只报告状态。
    """
    assert client.get("/health").status_code == 200


def test_turning_it_off_must_be_explicit(client, monkeypatch):
    """`GALAXY_NODE_AUTH=off` 是给"确实不想要"的部署留的,不是默认。"""
    assert client.post("/click", json=BODY).status_code == 401
    monkeypatch.setenv("GALAXY_NODE_AUTH", "off")
    assert client.post("/click", json=BODY).status_code != 401


def test_an_unavailable_auth_module_closes_the_door(client):
    """拿不到 core.auth 时 **503**,不是放行。

    `galaxy_gateway/routes/sessions.py` 里那个 try/except 在导入失败时退化成 no-op
    依赖 —— 对会话查询也许还行,对一个能点鼠标、跑命令的节点不行:那等于这层没装。
    """
    real = sys.modules.pop("core.auth")
    sys.modules["core.auth"] = None  # 让 import 抛 ImportError
    try:
        r = client.post("/click", json=BODY)
        assert r.status_code == 503
        assert "auth unavailable" in r.json()["detail"]
    finally:
        sys.modules["core.auth"] = real


# ── 接线:9 个节点一个都不能漏 ───────────────────────────────────────────────
@pytest.mark.parametrize("num", PROTECTED)
def test_every_protected_node_installs_auth(num):
    """声明了动作白名单的节点,HTTP 面必须装上认证。

    这一条是给**将来**的:新增一个敏感节点、写了 manifest、却忘了装认证,在这里变红。
    当初 9 个节点无一装有认证,而没有任何测试发现得了。
    """
    d = glob.glob(f"nodes/Node_{num}_*")[0]
    src = open(os.path.join(d, "main.py"), encoding="utf-8").read()
    assert "install_node_auth(app" in src, f"Node_{num} 的 HTTP 面没装认证"


# ── 调用方那一侧 ─────────────────────────────────────────────────────────────
def test_internal_callers_carry_a_token(monkeypatch):
    """仓内直接打节点端点的调用方必须带令牌,否则会在自己的系统里被 401。"""
    monkeypatch.setenv("GALAXY_API_TOKEN", TOKEN)
    from core.internal_auth import internal_auth_headers

    assert internal_auth_headers() == {"Authorization": f"Bearer {TOKEN}"}


def test_no_token_yields_no_header_rather_than_an_exception(monkeypatch):
    """拿不到令牌时返回空 header,而不是抛。

    调用方随后收到 401 —— 那是准确的现象("这次调用没有身份");
    在这里抛异常会把它伪装成"调用方自己坏了"。
    """
    monkeypatch.delenv("GALAXY_API_TOKEN", raising=False)
    monkeypatch.delenv("GALAXY_API_TOKENS", raising=False)
    monkeypatch.setenv("GALAXY_DATA_DIR", "/nonexistent-dir-for-this-test")
    from core.internal_auth import internal_auth_headers

    assert internal_auth_headers() == {}


def test_the_device_control_service_attaches_it_at_the_single_chokepoint():
    """8 个调用点都走 `_get_client()`,所以令牌装在那一个工厂上。

    逐个调用点加一次,漏一处就是一条会 401 的路径,而且只在真被调用时才暴露。
    """
    import ast
    import inspect

    import core.device_control_service as svc

    fn = next(
        n
        for n in ast.walk(ast.parse(inspect.getsource(svc)))
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "_get_client"
    )
    names = {c.func.id for c in ast.walk(fn) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    assert "internal_auth_headers" in names, "_get_client 没有带上内部身份"
