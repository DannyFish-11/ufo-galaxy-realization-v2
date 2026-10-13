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
]


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
