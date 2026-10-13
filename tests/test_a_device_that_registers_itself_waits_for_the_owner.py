"""设备自己从 REST 来登记、不带任何凭据时，**等主人在面板上同意**才进设备表（UDM）。

原先 ``POST /api/v1/devices/register`` 与旧的 ``/api/devices/register`` 照单全收、直接写 UDM：同一局域网谁都能
登记一台假设备、接到派过去的任务（安卓走 WS 有带内认证；非安卓设备的通用入口自己核验入口令牌 —— 只有这两个口
是敞着的）。所有者定：在面板上确认。陌生设备只记成接入候选（``SelfRegisteredPath``），面板「全部设置」最上面
「等你同意的设备」点「接入」才写进去；鉴权关着、带主人令牌、本来就是成员的照旧直接登记。
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture()
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GALAXY_AUTH_ENABLED", "true")
    monkeypatch.delenv("GALAXY_ONBOARDING_AUTO", raising=False)
    monkeypatch.delenv("GALAXY_ONBOARDING_ENABLED", raising=False)
    from core.device_onboarding import service

    service.reset_onboarding_service()
    from core.api_routes import create_api_routes

    app = FastAPI()
    app.include_router(create_api_routes())
    with TestClient(app) as c:
        yield c
    service.reset_onboarding_service()


def _new_id() -> str:
    return f"stranger-{uuid.uuid4().hex[:8]}"


def _in_udm(device_id: str) -> bool:
    from core.unified.device_manager import get_unified_device_manager

    return get_unified_device_manager().get_device(device_id) is not None


def _pending(api, auth_headers):
    body = api.get("/api/v1/onboarding/overview", headers=auth_headers).json()
    return [c for c in body["candidates"] if c["join_path"] == "self_registered"]


def test_a_stranger_waits_and_is_not_in_the_device_table(api, auth_headers):
    dev = _new_id()
    r = api.post("/api/v1/devices/register", json={"device_id": dev, "device_name": "陌生手机"})
    assert r.status_code == 202 and r.json()["status"] == "pending_approval", r.text
    assert not _in_udm(dev), "没人同意就进了设备表 —— 局域网谁都能登记一台假设备"
    [cand] = [c for c in _pending(api, auth_headers) if c["identity"]["device_id"] == dev]
    assert cand["name"] == "陌生手机" and cand["human_step"] == "approve"


def test_the_owner_clicks_join_and_it_comes_back_as_a_member(api, auth_headers):
    dev = _new_id()
    cid = api.post("/api/v1/devices/register", json={"device_id": dev, "device_type": "android"}).json()["candidate_id"]
    joined = api.post(f"/api/v1/onboarding/candidates/{cid}/join", json={"inputs": {}}, headers=auth_headers)
    assert joined.status_code == 200 and joined.json()["success"] is True, joined.text
    assert _in_udm(dev)
    again = api.post("/api/v1/devices/register", json={"device_id": dev, "device_type": "android"})
    assert again.status_code == 200 and again.json()["success"] is True, "接入之后再来登记应当走原来那条完整路径"
    assert not [c for c in _pending(api, auth_headers) if c["identity"]["device_id"] == dev]


def test_once_refused_it_stays_refused(api, auth_headers):
    dev = _new_id()
    cid = api.post("/api/v1/devices/register", json={"device_id": dev}).json()["candidate_id"]
    assert api.post(f"/api/v1/onboarding/candidates/{cid}/ignore", headers=auth_headers).status_code == 200
    r = api.post("/api/v1/devices/register", json={"device_id": dev})
    assert r.status_code == 403 and r.json()["status"] == "rejected"
    assert not _in_udm(dev)


def test_the_owner_token_registers_directly(api, auth_headers):
    dev = _new_id()
    r = api.post("/api/v1/devices/register", json={"device_id": dev}, headers=auth_headers)
    assert r.status_code == 200 and _in_udm(dev)


def test_auth_turned_off_means_the_owner_trusts_the_lan(api, monkeypatch):
    monkeypatch.setenv("GALAXY_AUTH_ENABLED", "false")
    dev = _new_id()
    assert api.post("/api/v1/devices/register", json={"device_id": dev}).status_code == 200 and _in_udm(dev)


def test_auto_approve_does_not_wave_it_through(api, auth_headers, monkeypatch):
    """``GALAXY_ONBOARDING_AUTO=approve`` 放行的是有别的依据的「点头」;不带凭据的登记除了人没有依据。"""
    monkeypatch.setenv("GALAXY_ONBOARDING_AUTO", "approve")
    dev = _new_id()
    assert api.post("/api/v1/devices/register", json={"device_id": dev}).status_code == 202
    assert not _in_udm(dev)


def test_the_legacy_entrance_follows_the_same_rule(api, auth_headers):
    dev = _new_id()
    r = api.post("/api/devices/register", json={"device_id": dev, "device_type": "android"})
    assert r.status_code == 202 and not _in_udm(dev), r.text
    assert api.post("/api/devices/register", json={"device_id": _new_id()}, headers=auth_headers).status_code == 200


def test_a_known_driver_cannot_take_a_stranger_past_the_owner():
    """「以前接过同类设备、用同一个驱动」那条路径可被 AUTO=approve 放行 —— 它不许接自己上门来的候选。"""
    from core.device_onboarding import drivers
    from core.device_onboarding.join_paths import SELF_REGISTER_SOURCE, find_join_path
    from core.device_onboarding.models import Candidate

    cand = Candidate(candidate_id="c1", source=SELF_REGISTER_SOURCE, key="k", name="n")
    assert drivers.KnownDriverPath().can_handle(cand) is False
    assert find_join_path(cand).name == "self_registered"


def test_the_panel_shows_them_first_with_join_and_refuse():
    main_ts = (REPO / "electron/renderer/panel/src/main.ts").read_text(encoding="utf-8")
    assert "topSections: [pendingDevices.root," in main_ts, "等你同意的设备应当排在「全部设置」最前"
    ui = (REPO / "electron/renderer/panel/src/ui/pending_devices.ts").read_text(encoding="utf-8")
    assert "'接入'" in ui and "'不接入'" in ui
    transport = (REPO / "electron/renderer/panel/src/transport.ts").read_text(encoding="utf-8")
    assert "const SELF_REGISTERED = 'self_registered';" in transport
    from core.device_onboarding.join_paths import SelfRegisteredPath

    assert SelfRegisteredPath.name == "self_registered", "面板按这个路径名挑候选,两边要一致"


def test_the_first_sighting_says_where_to_click(api, monkeypatch):
    """第一次见到时在对话里说一声,说的是去哪儿点 —— 不是「跟我说一声」的通用说法。"""
    from core.device_onboarding import conversation

    said = []
    monkeypatch.setattr(conversation, "note_new_candidate", lambda name, how: said.append((name, how)))
    api.post("/api/v1/devices/register", json={"device_id": _new_id(), "device_name": "客厅平板"})
    assert said and said[0][0] == "客厅平板" and "全部设置" in said[0][1], said


def test_a_borrowed_device_id_cannot_rewrite_what_the_device_is(api, auth_headers):
    """设备号就写在请求体里,谁都能冒用。成员不带凭据来重新登记:只认已登记的名字 / 类型 / 能力。"""
    from core.unified.device_manager import get_unified_device_manager

    dev = _new_id()
    api.post(
        "/api/v1/devices/register",
        json={"device_id": dev, "device_name": "妈妈的手机", "capabilities": ["notification"]},
        headers=auth_headers,
    )
    spoof = {"device_id": dev, "device_name": "冒用的", "capabilities": ["camera", "shell"]}
    assert api.post("/api/v1/devices/register", json=spoof).status_code == 200  # 报到照收
    d = get_unified_device_manager().get_device(dev)
    assert d.device_name == "妈妈的手机" and "shell" not in d.capabilities, "冒用设备号改掉了它的资料"

    assert api.post("/api/devices/register", json={**spoof, "device_type": "android"}).status_code == 200
    d = get_unified_device_manager().get_device(dev)
    assert d.device_name == "妈妈的手机" and "shell" not in d.capabilities, "旧登记口照样不许改"

    api.post("/api/v1/devices/register", json={**spoof, "device_name": "妈妈的新手机"}, headers=auth_headers)
    assert get_unified_device_manager().get_device(dev).device_name == "妈妈的新手机", "主人的令牌照旧能改"
