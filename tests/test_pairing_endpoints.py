"""配对 REST 端点端到端回归:enroll → pending → approve → claim 全链路。

用一个独立 FastAPI app 只挂 pairing 路由 + 临时存储的协调器单例,避免碰真实
~/.galaxy 与整个网关 app 的重依赖。
"""

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # 把协调器单例指到临时存储(注册表也随之在临时目录)
    import core.device_enrollment as de
    from core.device_enrollment import DeviceEnrollmentCoordinator
    from core.device_token_registry import DeviceTokenRegistry

    reg = DeviceTokenRegistry(store_path=tmp_path / "device_tokens.json")
    monkeypatch.setattr(de, "_coordinator", DeviceEnrollmentCoordinator(registry=reg))

    from galaxy_gateway.api.pairing import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_enroll_pending_approve_claim(client):
    # 设备侧:提交入伙请求(开放,无需鉴权)
    r = client.post("/api/v1/pairing/enroll", json={"device_id": "dev-1", "device_type": "android", "name": "小米17"})
    assert r.status_code == 200 and r.json()["ok"] is True
    rid = r.json()["request_id"]

    # 信任侧:待批准列表(鉴权默认关 → 开放;返回不含 token)
    r = client.get("/api/v1/pairing/pending")
    assert r.status_code == 200
    pend = r.json()["pending"]
    assert any(x["device_id"] == "dev-1" for x in pend)
    assert all("token" not in x for x in pend)

    # 设备侧:批准前 claim 拿不到
    r = client.post(f"/api/v1/pairing/claim/{rid}")
    assert r.json()["ok"] is False

    # 信任侧:批准(token 不在此返回)
    r = client.post("/api/v1/pairing/approve", json={"request_id": rid})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert "token" not in r.json()

    # 设备侧:claim 领 token(一次性)
    r = client.post(f"/api/v1/pairing/claim/{rid}")
    assert r.json()["ok"] is True
    tok = r.json()["token"]
    assert isinstance(tok, str) and len(tok) >= 20
    # 第二次 claim 拿不到
    assert client.post(f"/api/v1/pairing/claim/{rid}").json()["ok"] is False

    # 领到的 token 在协调器所用的注册表里可校验通过(闭环)——不改任何全局单例,
    # 避免污染其它测试(auth.verify_api_token 走单例的路径已由
    # tests/test_device_token_registry.py 覆盖)。
    import core.device_enrollment as de

    assert de._coordinator._registry.verify(tok) is not None


def test_deny_blocks_claim(client):
    rid = client.post("/api/v1/pairing/enroll", json={"device_id": "dev-x"}).json()["request_id"]
    assert client.post("/api/v1/pairing/deny", json={"request_id": rid, "reason": "不认识"}).json()["ok"] is True
    assert client.post(f"/api/v1/pairing/claim/{rid}").json()["ok"] is False
    assert client.get(f"/api/v1/pairing/status/{rid}").json()["status"] == "denied"


def test_status_unknown(client):
    assert client.get("/api/v1/pairing/status/nope").json()["ok"] is False
