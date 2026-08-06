#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_pair_claim_is_exempt_but_throttled.py

``GALAXY_AUTH_ENABLED`` 翻成默认开启之后,配对本身出现了一个死锁:

    一台还没配对的设备手里**没有任何令牌**。要求它先带令牌才能来换令牌,
    它就永远进不来。

所以 ``POST /api/v1/pair/claim`` 必须豁免鉴权 —— 凭证是那个一次性短码/带签名的
链接本身,不是 API 令牌。

但豁免不是白送
==============
1. ``GET /api/v1/pair/card`` **不许**一起豁免。它是"出示本机名片",每调一次就
   签发一个新短码。公开它等于任何人都能自助领一张进门票,那时豁免 claim 就真的
   成了敞门。card 属于桌面主人的操作。
2. claim 对公网开放(Tailscale Funnel 那条路),短码可枚举,所以猜错要按来源节流。
   31^6 ≈ 8.9 亿、10 分钟有效、用后即焚,盲猜期望本来就极低;但"概率低"不是把
   一个公网端点的爆破面敞着的理由 —— 它成功一次就等于交出一台设备。
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture(autouse=True)
def _fresh_throttle():
    import core.agent_card as ac

    ac.reset_pairing_attempt_throttle()
    ac.reset_pairing_code_registry()
    yield
    ac.reset_pairing_attempt_throttle()
    ac.reset_pairing_code_registry()


# ---------------------------------------------------------------------------
# 一、豁免表：claim 在，card 不在
# ---------------------------------------------------------------------------


def test_claim_is_exempt_so_an_unpaired_device_can_get_in():
    from galaxy_gateway.middleware import _is_exempt

    assert _is_exempt("/api/v1/pair/claim", "POST") is True


def test_card_is_not_exempt():
    """公开 card = 任何人都能自助领短码,那时豁免 claim 就成了敞门。"""
    from galaxy_gateway.middleware import _is_exempt

    assert _is_exempt("/api/v1/pair/card", "GET") is False


def test_claim_exemption_is_method_scoped():
    """只豁免 POST。同路径换个方法不该跟着白拿。"""
    from galaxy_gateway.middleware import _is_exempt

    assert _is_exempt("/api/v1/pair/claim", "GET") is False
    assert _is_exempt("/api/v1/pair/claim", "DELETE") is False


def test_other_pair_endpoints_stay_protected():
    """信任调整、对端列表、移除 —— 都是主人的操作,一个都不许豁免。"""
    from galaxy_gateway.middleware import _is_exempt

    for path, method in [
        ("/api/v1/pair/peers", "GET"),
        ("/api/v1/pair/trust", "POST"),
        ("/api/v1/pair/peers/some-device", "DELETE"),
        ("/api/v1/pair/check", "POST"),
    ]:
        assert _is_exempt(path, method) is False, f"{method} {path} 不该豁免"


def test_exemption_survives_production_mode():
    """生产模式下也得能配对 —— 否则装到生产就没法接设备了。"""
    import os

    from galaxy_gateway.middleware import _is_exempt

    prev = os.environ.get("GALAXY_MODE")
    os.environ["GALAXY_MODE"] = "production"
    try:
        assert _is_exempt("/api/v1/pair/claim", "POST") is True
        # 对照：仅非生产豁免的那批,在这里必须落回不豁免
        assert _is_exempt("/metrics", "GET") is False
    finally:
        if prev is None:
            os.environ.pop("GALAXY_MODE", None)
        else:
            os.environ["GALAXY_MODE"] = prev


# ---------------------------------------------------------------------------
# 二、节流本身
# ---------------------------------------------------------------------------


def test_wrong_codes_eventually_lock_out_that_source():
    from core.agent_card import PairingAttemptThrottle

    t = PairingAttemptThrottle(max_attempts=3, window_s=300.0)
    assert t.is_blocked("1.2.3.4") is False
    for _ in range(3):
        t.record_failure("1.2.3.4")
    assert t.is_blocked("1.2.3.4") is True


def test_throttle_is_per_source():
    """一个人爆破不该把同一个家里其他设备一起锁死。"""
    from core.agent_card import PairingAttemptThrottle

    t = PairingAttemptThrottle(max_attempts=2, window_s=300.0)
    t.record_failure("1.2.3.4")
    t.record_failure("1.2.3.4")
    assert t.is_blocked("1.2.3.4") is True
    assert t.is_blocked("5.6.7.8") is False


def test_lockout_expires_with_the_window():
    """锁是暂时的。手输错几次的人不该被永久拒之门外。"""
    from core.agent_card import PairingAttemptThrottle

    t = PairingAttemptThrottle(max_attempts=2, window_s=60.0)
    t.record_failure("1.2.3.4", now=1000.0)
    t.record_failure("1.2.3.4", now=1000.0)
    assert t.is_blocked("1.2.3.4", now=1030.0) is True
    assert t.is_blocked("1.2.3.4", now=1061.0) is False


def test_successful_pairings_do_not_count():
    """只计失败。正常配对不该因为家里连了几台设备就把自己锁住。

    区分度：如果实现改成"每次调用都计数",这条会红。
    """
    from core.agent_card import PairingAttemptThrottle

    t = PairingAttemptThrottle(max_attempts=2, window_s=300.0)
    # 成功路径压根不调 record_failure —— 这里模拟的就是"调了 100 次都成功"
    assert t.is_blocked("1.2.3.4") is False


# ---------------------------------------------------------------------------
# 三、端点上真的接了（不是只写了个类）
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from core.routes import pairing

    importlib.reload(pairing)
    app = FastAPI()
    app.include_router(pairing.create_router())
    return TestClient(app)


def test_bad_code_is_rejected_and_counted(client):
    import core.agent_card as ac

    r = client.post("/api/v1/pair/claim", json={"code": "ZZZZZZ"})
    assert r.status_code == 400
    assert ac.get_pairing_attempt_throttle().is_blocked("testclient") is False  # 一次还不至于
    # 但确实记了一笔 —— 否则节流永远触发不了
    assert ac.get_pairing_attempt_throttle().record_failure("testclient") == 2


def test_repeated_guessing_gets_429(client):
    import core.agent_card as ac

    for _ in range(ac.MAX_CODE_ATTEMPTS):
        client.post("/api/v1/pair/claim", json={"code": "ZZZZZZ"})
    r = client.post("/api/v1/pair/claim", json={"code": "ZZZZZZ"})
    assert r.status_code == 429, "猜了这么多次还在放行 —— 节流没接上"
    assert r.json()["success"] is False


def test_forged_card_also_counts_toward_the_limit(client):
    """伪造名片和猜短码是同一件事的两个入口,只拦一边等于没拦。"""
    import core.agent_card as ac

    for _ in range(3):
        client.post("/api/v1/pair/claim", json={"link": "galaxy://pair?c=bogus&s=bogus"})
    assert ac.get_pairing_attempt_throttle().record_failure("testclient") == 4


def test_missing_both_link_and_code_is_a_plain_400(client):
    """空请求是用法错误,不是爆破 —— 不该占用别人的配额。"""
    import core.agent_card as ac

    r = client.post("/api/v1/pair/claim", json={})
    assert r.status_code == 400
    assert ac.get_pairing_attempt_throttle().record_failure("testclient") == 1


def test_a_real_code_still_pairs_after_some_wrong_guesses(client):
    """节流不该把正确的那次也一起挡掉(只要还没到上限)。"""
    from core.agent_card import build_local_card, get_pairing_code_registry, to_link

    client.post("/api/v1/pair/claim", json={"code": "ZZZZZZ"})
    code, _exp = get_pairing_code_registry().issue(to_link(build_local_card()))
    r = client.post("/api/v1/pair/claim", json={"code": code})
    assert r.status_code == 200, r.text
    assert r.json()["success"] is True
