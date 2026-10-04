"""关闭漫游会话：核心与网关两个入口都走 ``core.session_migration.close_roaming_session``。

此前网关有 ``POST /api/v1/sessions/{id}/close``、核心没有 —— 一条只挂在网关上的路由会让「跑哪个入口」重新变得要紧
（``config/api_surface_parity.json`` 的守卫）。现在权威层也有，行为一致。
"""

from __future__ import annotations

import importlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from galaxy_gateway.session_roaming import SessionRoamingManager, SessionState

sr = importlib.import_module("galaxy_gateway.session_roaming")
TOKEN = "close-test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def roaming(tmp_path, monkeypatch):
    monkeypatch.setattr(sr, "PERSISTENCE_DIR", tmp_path)
    monkeypatch.setattr(sr, "PERSISTENCE_FILE", tmp_path / "sessions.json")
    mgr = SessionRoamingManager()
    import core.session_migration as sm

    monkeypatch.setattr(sm, "_roaming_store", lambda: mgr)
    return mgr


@pytest.fixture
def client(tmp_path, monkeypatch, roaming):
    monkeypatch.setenv("GALAXY_NATS_ENABLED", "false")
    monkeypatch.setenv("GALAXY_AUTH_ENABLED", "true")
    monkeypatch.setenv("GALAXY_API_TOKEN", TOKEN)
    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
    from core.api_routes import create_api_routes

    app = FastAPI()
    app.include_router(create_api_routes(service_manager=None, config=None))
    return TestClient(app)


def test_core_close_marks_the_roaming_session_closed_and_frees_the_device(client, roaming):
    session = roaming.create_session("phone-1")
    r = client.post(f"/api/v1/sessions/{session.session_id}/close", headers=AUTH)
    assert r.status_code == 200 and r.json()["success"] is True
    assert roaming.get_session(session.session_id).state == SessionState.CLOSED
    # 设备映射释放：同一台设备能再开一个新会话
    assert roaming.create_session("phone-1").session_id != session.session_id


def test_unknown_session_is_404_not_a_silent_success(client):
    assert client.post("/api/v1/sessions/nope/close", headers=AUTH).status_code == 404


def test_closing_changes_state_so_it_needs_a_token(client, roaming):
    session = roaming.create_session("phone-2")
    assert client.post(f"/api/v1/sessions/{session.session_id}/close").status_code in (401, 403)
    assert roaming.get_session(session.session_id).state != SessionState.CLOSED


def test_the_gateway_route_goes_through_the_same_function(roaming, monkeypatch):
    import core.session_migration as sm
    from galaxy_gateway.routes import sessions as gw

    session = roaming.create_session("phone-3")
    seen = []
    real = sm.close_roaming_session
    monkeypatch.setattr(sm, "close_roaming_session", lambda sid: seen.append(sid) or real(sid))

    import asyncio

    out = asyncio.run(gw.close_session(session.session_id, auth={"authenticated": True}))
    assert seen == [session.session_id]
    assert out["state"] == "closed"
