"""配对时给手表发一把"一次性进 tailnet 的钥匙" —— 出门直连的起点。

为什么要这道门
==============
手表装不了 Tailscale(Wear OS 把 VPN 授权做成了桩),App 里嵌的是用户态 tailnet
进程,它第一次加入要一把 headscale 预授权密钥。让人去电脑上敲命令再把一长串
字符手输进手表不现实 —— 配对这一刻手表正好在跟电脑说话,就在这里交过去。

钉的事:
  1. 钥匙是**一次性**、**短命**、**非临时节点**的(发给 headscale 的请求体);
  2. 只发给手表;被拒的设备不发;
  3. 签不出来**不影响配对**,但必须说清为什么、怎么修;
  4. 各种失败(没配、密钥错、用户不存在、headscale 不在线、返回怪)各有各的原因码;
  5. 状态盘能看到"手表出门直连"这条前提齐不齐。

真 headscale 上的验证见 galaxy-wearos 仓 tailnet/e2e/run.sh:同一把一次性密钥
第二次加入会被 headscale 以 "authkey already used" 拒绝。
"""

from __future__ import annotations

import io
import time
import urllib.error
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core import headscale_join as hj


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("GALAXY_HEADSCALE_URL", "https://hs.example.internal/")
    monkeypatch.setenv("GALAXY_HEADSCALE_API_KEY", "hskey-api-xyz")
    monkeypatch.delenv("GALAXY_HEADSCALE_USER", raising=False)


@pytest.fixture
def unconfigured(monkeypatch):
    for k in ("GALAXY_HEADSCALE_URL", "GALAXY_HEADSCALE_API_KEY", "GALAXY_HEADSCALE_USER"):
        monkeypatch.delenv(k, raising=False)


class FakeHeadscale:
    """记下每一次请求,按脚本回应 —— 形状照 headscale v0.29 的 REST 网关。"""

    def __init__(self, users=None, key="hskey-auth-abc", snake=False):
        self.calls = []
        self.users = users if users is not None else [{"id": "7", "name": "galaxy"}]
        self.key = key
        self.snake = snake

    def __call__(self, method, url, headers, body):
        self.calls.append({"method": method, "url": url, "headers": headers, "body": body})
        if method == "GET" and "/api/v1/user" in url:
            return {"users": self.users}
        if method == "POST" and url.endswith("/api/v1/preauthkey"):
            field = "pre_auth_key" if self.snake else "preAuthKey"
            return {field: {"key": self.key, "reusable": False}}
        raise AssertionError(f"没想到的请求 {method} {url}")


# ---------------------------------------------------------------------------
# 一、钥匙的形状
# ---------------------------------------------------------------------------


def test_the_key_is_single_use_short_lived_and_not_ephemeral(configured):
    fake = FakeHeadscale()
    before = time.time()
    g = hj.issue_join_key(http_json=fake)

    post = [c for c in fake.calls if c["method"] == "POST"][0]
    body = post["body"]
    assert body["reusable"] is False, "钥匙能用多次 —— 配对响应被截走就等于门开着"
    assert body["ephemeral"] is False, "临时节点离线就被清掉,手表每次回来都得重新配对"
    assert body["user"] == "7", "新版 headscale 按用户数字 id 指定,要先按名字查出 id"
    assert before + 500 < g.expires_at < time.time() + 700, "有效期应当是 10 分钟上下"
    assert g.auth_key == "hskey-auth-abc"
    # 地址末尾的斜杠去掉,手表拿去直接当 --control-url 用
    assert g.control_url == "https://hs.example.internal"
    assert post["headers"]["Authorization"] == "Bearer hskey-api-xyz"


def test_snake_case_responses_are_understood_too(configured):
    """headscale 的 REST 网关不同版本字段风格不同 —— 两种都得认。"""
    g = hj.issue_join_key(http_json=FakeHeadscale(snake=True))
    assert g.auth_key == "hskey-auth-abc"


def test_the_user_can_be_chosen(configured, monkeypatch):
    monkeypatch.setenv("GALAXY_HEADSCALE_USER", "family")
    fake = FakeHeadscale(users=[{"id": "3", "name": "family"}])
    hj.issue_join_key(http_json=fake)
    assert "name=family" in fake.calls[0]["url"]
    assert fake.calls[1]["body"]["user"] == "3"


# ---------------------------------------------------------------------------
# 二、失败各有各的原因
# ---------------------------------------------------------------------------


def test_not_configured_says_what_is_missing(unconfigured, monkeypatch):
    with pytest.raises(hj.JoinUnavailable) as e:
        hj.issue_join_key(http_json=FakeHeadscale())
    assert e.value.reason == "no_headscale_url"

    monkeypatch.setenv("GALAXY_HEADSCALE_URL", "https://hs")
    with pytest.raises(hj.JoinUnavailable) as e:
        hj.issue_join_key(http_json=FakeHeadscale())
    assert e.value.reason == "no_api_key"
    assert "apikeys create" in e.value.how_to_fix


def test_missing_user_is_its_own_reason(configured):
    with pytest.raises(hj.JoinUnavailable) as e:
        hj.issue_join_key(http_json=FakeHeadscale(users=[{"id": "1", "name": "someone-else"}]))
    assert e.value.reason == "no_such_user"
    assert "users create galaxy" in e.value.how_to_fix


def _raising(exc):
    def call(*_a, **_k):
        raise exc

    return call


def test_rejected_api_key_is_its_own_reason(configured):
    err = urllib.error.HTTPError("https://hs/api/v1/user", 401, "Unauthorized", {}, io.BytesIO(b""))
    with pytest.raises(hj.JoinUnavailable) as e:
        hj.issue_join_key(http_json=_raising(err))
    assert e.value.reason == "api_key_rejected"


def test_unreachable_headscale_is_its_own_reason(configured):
    with pytest.raises(hj.JoinUnavailable) as e:
        hj.issue_join_key(http_json=_raising(urllib.error.URLError("refused")))
    assert e.value.reason == "headscale_unreachable"


def test_success_without_a_key_is_not_success(configured):
    """回了 200 却没有密钥:不能当成拿到了。"""
    with pytest.raises(hj.JoinUnavailable) as e:
        hj.issue_join_key(http_json=FakeHeadscale(key=""))
    assert e.value.reason == "bad_response"


# ---------------------------------------------------------------------------
# 三、配对端点上真的接了
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_pairing():
    import core.agent_card as ac
    import core.peer_trust as pt

    ac.reset_pairing_code_registry()
    ac.reset_pairing_attempt_throttle()
    if hasattr(pt, "reset_peer_trust_book"):
        pt.reset_peer_trust_book()
    yield


@pytest.fixture
def client():
    from core.routes.pairing import create_router

    app = FastAPI()
    app.include_router(create_router())
    return TestClient(app)


def _claim(client, device_type, trust="friend"):
    card = client.get("/api/v1/pair/card").json()
    return client.post(
        "/api/v1/pair/claim",
        json={
            "code": card["code"],
            "device_id": f"dev-{uuid.uuid4().hex[:6]}",
            "device_type": device_type,
            "trust": trust,
        },
    ).json()


@pytest.fixture
def fake_issue(monkeypatch):
    issued = []

    def issue(ttl_s=hj.DEFAULT_KEY_TTL_S, *, http_json=None):
        g = hj.JoinGrant("https://hs.example.internal", f"hskey-auth-{len(issued)}", time.time() + ttl_s)
        issued.append(g)
        return g

    monkeypatch.setattr(hj, "issue_join_key", issue)
    return issued


def test_a_watch_gets_the_key_with_its_pairing(client, fake_issue):
    r = _claim(client, "wearos")
    assert r["success"] is True
    assert r["tailnet_join"]["auth_key"] == "hskey-auth-0"
    assert r["tailnet_join"]["control_url"] == "https://hs.example.internal"
    assert len(fake_issue) == 1


def test_a_phone_does_not_get_one(client, fake_issue):
    """手机装得了 Tailscale 自己登录;多发一把没人用的进网凭证只是多一个泄露面。"""
    r = _claim(client, "android")
    assert r["success"] is True
    assert "tailnet_join" not in r
    assert fake_issue == []


def test_a_blocked_device_does_not_get_one(client, fake_issue):
    r = _claim(client, "wearos", trust="blocked")
    assert "tailnet_join" not in r
    assert fake_issue == []


def test_no_key_does_not_break_pairing_but_says_why(client, unconfigured):
    """签不出钥匙时,配对照样成功(在家的局域网直连不受影响),但必须说清楚。"""
    r = _claim(client, "wearos")
    assert r["success"] is True
    assert r["capability_token"], "钥匙签不出来连带把令牌也弄丢了"
    assert r["tailnet_join"] is None
    assert r["tailnet_join_unavailable"]["reason"] == "no_headscale_url"
    assert r["tailnet_join_unavailable"]["how_to_fix"]


# ---------------------------------------------------------------------------
# 四、状态盘
# ---------------------------------------------------------------------------


def test_status_board_shows_whether_watch_direct_is_possible(client, unconfigured):
    st = client.get("/api/v1/pair/paths").json()
    assert st["watch_tailnet"]["configured"] is False
    assert st["watch_tailnet"]["reason"] == "no_headscale_url"


def test_status_board_does_not_leak_the_api_key(client, configured):
    st = client.get("/api/v1/pair/paths").json()
    assert st["watch_tailnet"]["configured"] is True
    assert "hskey-api-xyz" not in str(st), "API 密钥出现在状态盘上了"
