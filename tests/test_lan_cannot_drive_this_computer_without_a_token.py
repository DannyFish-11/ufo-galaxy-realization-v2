"""不带令牌,改不了设置、点不了这台电脑的界面、调不动对话。

真跑(``GALAXY_AUTH_ENABLED`` 默认开、后端听 ``0.0.0.0``),从容器的局域网地址不带任何令牌::

    GET  /api/v1/system/status       401   ← 挂了鉴权的组,对
    POST /api/config                 422   ← 过了鉴权,只是请求体不对:带上合法的请求体就能改 .env(含关鉴权)
    POST /api/v1/ui/act              200   ← 点这台电脑的界面
    POST /api/v1/computer-use/task   422
    POST /api/v1/chat                422   ← 网关自己那条 /api/v1/chat 本来就要鉴权,只是这条同路径的先注册先命中
    GET  /api/v1/sessions            200   ← 对话列表

这几组在 ``core/api_routes.py`` 里挂载时没带 ``_auth_deps``。面板与主进程每个请求都带本机令牌
(``electron/main.js`` 的 ``onBeforeSendHeaders`` 与 ``withLocalAuth``),挂上鉴权不影响它们。

第二轮把整个权威 API 层逐条走了一遍(499 条),不带鉴权的写接口还有 74 条,其中有:

    POST /api/v1/agents/linux/servers/{id}/execute   在登记过的 Linux 服务器上跑命令(从网关并过来的)
    POST /api/v1/agents/sandbox/execute              沙箱里跑命令(同上)
    POST /api/v1/approvals/{request_id}              人在环的「批准」本身
    POST /api/v1/devices/{device_id}/command         给手机 / 手表下命令
    POST /api/v1/operator/dispatch                   派发任务
    GET  /api/v1/memory/cards                        对话记忆卡片

网关 app 上它们在全局 Bearer 中间件后面,权威层这个 app 没有那层中间件。现在除了下面
``OPEN_BY_DESIGN`` 列的几类(设备自注册、自带入口令牌的参与方、OAuth 登录),写接口一律要令牌;
新加的写接口忘了挂鉴权,``test_every_write_needs_a_token_unless_listed`` 会红。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

GUARDED = [
    ("POST", "/api/config"),
    ("GET", "/api/config/all"),
    ("POST", "/api/config/bundles"),
    ("POST", "/api/v1/ui/act"),
    ("POST", "/api/v1/computer-use/task"),
    ("POST", "/api/v1/providers/user"),
    ("POST", "/api/v1/chat"),
    ("POST", "/api/v1/chat/stream"),
    ("GET", "/api/v1/sessions"),
    ("POST", "/api/v1/memory/store"),
    ("POST", "/api/v1/opencode/configure"),
    ("POST", "/api/v1/agents/linux/servers/x/execute"),
    ("POST", "/api/v1/agents/sandbox/execute"),
    ("POST", "/api/v5/autonomous_programming"),
    ("GET", "/sync/status"),
    ("POST", "/api/v1/approvals/x"),
    ("POST", "/api/v1/devices/x/command"),
    ("DELETE", "/api/v1/devices/x"),
    ("POST", "/api/v1/devices/transfer"),
    ("POST", "/api/devices/unregister"),
    ("POST", "/api/v1/devices/x/unquarantine"),
    ("POST", "/api/v1/operator/dispatch"),
    ("POST", "/api/v1/operator/action"),
    ("POST", "/api/v1/hybrid/execute"),
    ("POST", "/api/v1/mesh/send"),
    ("POST", "/api/v1/agents/swarm"),
    ("GET", "/api/v1/ai/conversation/x"),
    ("POST", "/api/v1/models/tier"),
    ("POST", "/api/v1/vision/observe"),
    ("POST", "/api/v1/twin/x/simulate"),
    ("POST", "/api/v1/runtime/takeover"),
    ("POST", "/api/v1/results/isolated/x/retry"),
    ("POST", "/api/v1/presence/stop"),
    ("GET", "/api/v1/memory/cards"),
    ("POST", "/api/v1/github/context"),
]

#: 不带共享令牌也得进得来的写接口 —— 每一类都有自己的凭据或本来就是拿令牌的地方。
OPEN_BY_DESIGN = {
    # 设备自注册 / 心跳 / 状态:设备手里没有共享令牌(api_routes 的 Exempt routes)
    ("POST", "/api/v1/devices/register"),
    ("POST", "/api/v1/devices/status"),
    ("POST", "/api/v1/devices/{device_id}/heartbeat"),
    ("POST", "/api/devices/register"),
    ("POST", "/api/devices/heartbeat"),
    # 参与方:端点自己核验入口令牌(core.participant_admission)
    ("POST", "/api/v1/participants/register"),
    ("POST", "/api/v1/participants/{device_id}/tasks"),
    ("POST", "/api/v1/participants/{device_id}/heartbeat"),
    ("POST", "/api/v1/participants/{device_id}/disconnect"),
    # 配对:凭一次性配对码 / 旧令牌换新(core.auth.SELF_AUTHENTICATING_ENDPOINTS)
    ("POST", "/api/v1/pair/claim"),
    ("POST", "/api/v1/pair/renew"),
    # OAuth 登录面:登录本身就是拿令牌的地方
    ("POST", "/auth/oauth/google"),
    ("POST", "/auth/oauth/github"),
    ("POST", "/auth/oauth/device/start"),
    ("POST", "/auth/oauth/device/poll"),
    ("POST", "/auth/oauth/refresh"),
    ("POST", "/auth/oauth/logout"),
}


@pytest.fixture(scope="module")
def client():
    from core.api_routes import create_api_routes

    app = FastAPI()
    app.include_router(create_api_routes())
    with TestClient(app) as c:
        yield c


@pytest.mark.parametrize("method,path", GUARDED)
def test_no_token_no_entry(client, method, path, monkeypatch):
    monkeypatch.setenv("GALAXY_AUTH_ENABLED", "true")
    r = client.request(method, path, json={})
    assert r.status_code == 401, f"{method} {path} 不带令牌拿到 {r.status_code}"


@pytest.mark.parametrize("method,path", [("GET", "/api/config/all"), ("GET", "/api/v1/sessions")])
def test_the_token_the_panel_sends_gets_in(client, method, path, auth_headers, monkeypatch):
    monkeypatch.setenv("GALAXY_AUTH_ENABLED", "true")
    assert client.request(method, path, headers=auth_headers).status_code == 200


def test_the_panel_really_sends_the_token_on_every_request():
    """挂上鉴权不打断面板的前提:渲染进程的每个请求、主进程自己的 fetch 都带本机令牌。"""
    from pathlib import Path

    main_js = (Path(__file__).resolve().parents[1] / "electron" / "main.js").read_text(encoding="utf-8")
    assert "onBeforeSendHeaders" in main_js and "Authorization" in main_js
    assert "function withLocalAuth(" in main_js


def _walk(routes, inherited=()):
    """展开整棵路由树,产出 ``(方法, 完整路径, 这条路由上的全部依赖)``。

    新版 FastAPI 的 ``include_router`` 不把子路由摊平,而是包一层 ``_IncludedRouter``(挂载时给的
    ``dependencies`` 在它的 ``include_context`` 里);老版本摊平,依赖并进了路由自己的 ``dependant``。两种都认。
    """
    from fastapi.routing import APIRoute

    def deps_of(dependant):
        for d in dependant.dependencies:
            if d.call is not None:
                yield d.call
            yield from deps_of(d)

    for r in routes:
        sub = getattr(r, "original_router", None)
        if sub is not None:
            ctx = r.include_context
            yield from (
                (m, ctx.prefix + p, ds)
                for m, p, ds in _walk(sub.routes, tuple(inherited) + tuple(d.dependency for d in ctx.dependencies))
            )
        elif isinstance(r, APIRoute):
            ds = set(inherited) | set(deps_of(r.dependant))
            for m in r.methods:
                yield m, r.path, ds


def test_every_write_needs_a_token_unless_listed():
    from core.api_routes import create_api_routes

    def guarded(ds):  # 按名字认,不按对象:有用例会重新加载 core.auth,那之后同一个函数是另一个对象
        return any(
            (getattr(d, "__module__", ""), getattr(d, "__name__", "")) == ("core.auth", "require_auth") for d in ds
        )

    writes = [(m, p, ds) for m, p, ds in _walk(create_api_routes().routes) if m in ("POST", "PUT", "PATCH", "DELETE")]
    assert len(writes) > 100, "没走到路由树里(FastAPI 换了包法?)"
    open_ = sorted({(m, p) for m, p, ds in writes if not guarded(ds)} - OPEN_BY_DESIGN)
    assert not open_, f"这些写接口不带令牌就能调:{open_}"


def test_client_discovery_stays_public(client, monkeypatch):
    """从网关并过来的那几组里,只有客户端配置发现本来就公开(网关中间件的豁免表)。"""
    monkeypatch.setenv("GALAXY_AUTH_ENABLED", "true")
    assert client.get("/api/v1/config").status_code != 401


@pytest.mark.parametrize("path", ["/api/v1/models/catalog", "/api/v1/panel/self", "/api/v1/operator/heartbeat"])
def test_newly_guarded_reads_still_work_for_the_panel(client, path, auth_headers, monkeypatch):
    monkeypatch.setenv("GALAXY_AUTH_ENABLED", "true")
    assert client.get(path).status_code == 401
    assert client.get(path, headers=auth_headers).status_code != 401
