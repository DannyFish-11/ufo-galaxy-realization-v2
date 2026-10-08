"""手表拿着进网钥匙进了一张**空网**:电脑自己不在里面。

为什么要这道门
==============
配对时给手表(和笔记本)发一把一次性进网钥匙,为的是它出门后还能**直连这台电脑**。
可如果电脑自己没入网 —— 没装 Tailscale 客户端、还没登录、登录在别的控制服务器上 ——
手表进了 headscale,却谁也找不到;配对界面还显示成功,用户第一次出门才发现连不上,
而没有任何线索说原因在这里。

另一半原因:桌面版由启动器自己建 FastAPI 应用,只挂了 ``/ws/device/{id}``,**不跑**网关的
lifespan。自动入网、局域网广播这两步只写在 lifespan 里,桌面版从来没发生过。

钉的事:
  1. 电脑不在网里 → 配对仍成功、令牌照发,但**不发钥匙**,并给出 ``desktop_not_on_tailnet``
     与能照做的下一步;
  2. 电脑在网里 / 查不出来 → 照常发钥匙;headscale 没配 → 照旧报没配(不被新门盖掉);
  3. 桌面启动器启动时:先自动入网、**再**让 TailscaleManager 探测;入不成时横幅说真话
     (装了没入成 ≠ 没装);局域网广播发出去,停机时收掉;
  4. 网关 lifespan 与启动器共用同一处实现,不是两份。
"""

from __future__ import annotations

import asyncio
import pathlib
import time
import types
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core import headscale_join as hj
from core import tailnet_self_join as sj

ROOT = pathlib.Path(__file__).resolve().parents[1]
URL = "https://hs.example.internal"


@pytest.fixture
def configured(monkeypatch, tmp_path):
    monkeypatch.setenv("GALAXY_HEADSCALE_URL", URL)
    monkeypatch.setenv("GALAXY_HEADSCALE_API_KEY", "hskey-api-xyz")
    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))


@pytest.fixture
def unconfigured(monkeypatch):
    for k in ("GALAXY_HEADSCALE_URL", "GALAXY_HEADSCALE_API_KEY"):
        monkeypatch.delenv(k, raising=False)


class FakeTailscale:
    def __init__(self, backend="NeedsLogin", control=""):
        self.backend, self.control = backend, control

    def __call__(self, cmd):
        if cmd[1:3] == ["status", "--json"]:
            ips = '["100.64.0.1"]' if self.backend == "Running" else "[]"
            return types.SimpleNamespace(
                returncode=0, stdout=f'{{"BackendState":"{self.backend}","Self":{{"TailscaleIPs":{ips}}}}}', stderr=""
            )
        if cmd[1:3] == ["debug", "prefs"]:
            return types.SimpleNamespace(returncode=0, stdout=f'{{"ControlURL":"{self.control}"}}', stderr="")
        raise AssertionError(cmd)


@pytest.fixture
def has_tailscale(monkeypatch):
    monkeypatch.setattr(sj.shutil, "which", lambda _: "/usr/bin/tailscale")


# ---------------------------------------------------------------------------
# 一、门本身
# ---------------------------------------------------------------------------


def test_a_computer_inside_our_network_passes(configured, has_tailscale):
    assert sj.desktop_gate(run=FakeTailscale("Running", URL + "/")) is None
    # 旧版 tailscale 取不到 ControlURL:不因此拒绝
    assert sj.desktop_gate(run=FakeTailscale("Running", "")) is None


def test_a_computer_that_has_not_logged_in_is_stopped_with_a_next_step(configured, has_tailscale):
    out = sj.desktop_gate(run=FakeTailscale("NeedsLogin"))
    assert out["reason"] == "desktop_not_on_tailnet"
    assert "join-this-computer" in out["how_to_fix"] and "GALAXY_HEADSCALE_AUTOJOIN" in out["how_to_fix"]
    assert set(out) == {"reason", "how_to_fix"}, "形状要和 JoinUnavailable.to_dict() 一致,客户端只认这两个键"


def test_a_computer_without_the_client_is_stopped_and_told_where_to_get_it(configured, monkeypatch):
    monkeypatch.setattr(sj.shutil, "which", lambda _: None)
    out = sj.desktop_gate(run=lambda c: pytest.fail("没装就不该执行任何命令"))
    assert out["reason"] == "desktop_not_on_tailnet" and "tailscale.com/download" in out["how_to_fix"]


def test_a_computer_in_somebody_elses_network_is_stopped(configured, has_tailscale):
    out = sj.desktop_gate(run=FakeTailscale("Running", "https://controlplane.tailscale.com"))
    assert out["reason"] == "desktop_not_on_tailnet"
    assert "controlplane.tailscale.com" in out["how_to_fix"] and f"--login-server={URL}" in out["how_to_fix"]


def test_when_it_cannot_tell_it_does_not_refuse(configured, has_tailscale):
    """查不出来不替人拒绝:钥匙是一次性、10 分钟内有效的。"""

    def broken(cmd):
        return types.SimpleNamespace(returncode=0, stdout="not json", stderr="")

    assert sj.desktop_gate(run=broken) is None


# ---------------------------------------------------------------------------
# 二、配对端点上真的接了
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


@pytest.fixture
def issued(monkeypatch):
    log = []

    def issue(ttl_s=hj.DEFAULT_KEY_TTL_S, *, http_json=None):
        g = hj.JoinGrant(URL, f"hskey-auth-{len(log)}", time.time() + ttl_s)
        log.append(g)
        return g

    monkeypatch.setattr(hj, "issue_join_key", issue)
    return log


def _claim(client, device_type="wearos"):
    card = client.get("/api/v1/pair/card").json()
    return client.post(
        "/api/v1/pair/claim",
        json={
            "code": card["code"],
            "device_id": f"dev-{uuid.uuid4().hex[:6]}",
            "device_type": device_type,
            "trust": "friend",
        },
    ).json()


def test_pairing_succeeds_but_no_key_goes_into_an_empty_network(client, configured, issued, monkeypatch):
    blocked = {"reason": "desktop_not_on_tailnet", "how_to_fix": "先让电脑入网"}
    monkeypatch.setattr(sj, "desktop_gate", lambda **_: blocked)
    r = _claim(client)
    assert r["success"] is True and r["capability_token"], "没发钥匙不该连带把配对和令牌弄丢"
    assert r["tailnet_join"] is None
    assert r["tailnet_join_unavailable"] == blocked
    assert issued == [], "电脑不在网里却还是签了钥匙 —— 多出一个没人用、却能进网的凭证"


def test_a_laptop_is_held_back_the_same_way(client, configured, issued, monkeypatch):
    monkeypatch.setattr(sj, "desktop_gate", lambda **_: {"reason": "desktop_not_on_tailnet", "how_to_fix": "x"})
    r = _claim(client, "windows_laptop")
    assert r["tailnet_join"] is None and issued == []


def test_with_the_computer_inside_the_key_is_issued(client, configured, issued, monkeypatch):
    monkeypatch.setattr(sj, "desktop_gate", lambda **_: None)
    r = _claim(client)
    assert r["tailnet_join"]["auth_key"] == "hskey-auth-0" and len(issued) == 1


def test_the_real_gate_is_what_the_endpoint_consults(client, configured, issued, has_tailscale, monkeypatch):
    """不 mock 门本身:假的 tailscale 命令说「没登录」,端点就不发。"""
    # 换掉门默认用的命令执行器(关键字参数的默认值在定义时就绑定了,patch 模块属性不管用)
    monkeypatch.setattr(sj.desktop_gate, "__kwdefaults__", {"run": FakeTailscale("NeedsLogin")})
    r = _claim(client)
    assert r["tailnet_join"] is None and r["tailnet_join_unavailable"]["reason"] == "desktop_not_on_tailnet"
    assert issued == []


def test_headscale_not_configured_still_says_so(client, unconfigured, monkeypatch):
    """新门不盖掉原来的原因码:没配 headscale 时,先说没配。"""
    monkeypatch.setattr(sj, "desktop_gate", lambda **_: pytest.fail("没配 headscale 就不该去问电脑在不在网里"))
    r = _claim(client)
    assert r["tailnet_join_unavailable"]["reason"] == "no_headscale_url"


def test_the_reason_code_is_one_the_watch_can_say_in_words():
    """手表 PairingMessages 里有这个码的人话映射;码改了,两边要一起改。"""
    watch = pathlib.Path("/home/user/galaxy-wearos/app/src/main/java/com/galaxy/wear/auth/PairingMessages.kt")
    if not watch.is_file():
        pytest.skip("手表仓不在本机")
    assert '"desktop_not_on_tailnet"' in watch.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 三、桌面启动器
# ---------------------------------------------------------------------------


def test_startup_autojoin_is_skipped_when_switched_off(monkeypatch):
    monkeypatch.setenv("GALAXY_HEADSCALE_AUTOJOIN", "0")
    monkeypatch.setattr(sj, "ensure_joined", lambda **_: pytest.fail("开关关着不该入网"))
    assert asyncio.run(sj.autojoin_at_startup()) is None


def test_startup_autojoin_reports_what_happened_and_warns_on_failure(monkeypatch, caplog):
    monkeypatch.delenv("GALAXY_HEADSCALE_AUTOJOIN", raising=False)
    fail = {"state": "needs_admin", "detail": "tailscale up 需要管理员权限", "how_to_fix": "sudo tailscale up ..."}
    monkeypatch.setattr(sj, "ensure_joined", lambda **_: fail)
    with caplog.at_level("WARNING", logger="Galaxy.TailnetSelfJoin"):
        assert asyncio.run(sj.autojoin_at_startup()) == fail
    assert "sudo tailscale up" in caplog.text, "没入成要带着处置留一条告警"

    caplog.clear()
    monkeypatch.setattr(sj, "ensure_joined", lambda **_: {"state": "joined", "detail": "", "how_to_fix": ""})
    with caplog.at_level("WARNING", logger="Galaxy.TailnetSelfJoin"):
        assert asyncio.run(sj.autojoin_at_startup())["state"] == "joined"
    assert caplog.text == ""


def test_launcher_joins_before_the_tailscale_probe_and_is_not_blocked_by_failure(monkeypatch):
    from launcher.tailnet_startup import TailnetStartup

    order = []

    async def boom():
        order.append("autojoin")
        raise RuntimeError("tailscale up 卡住了")

    monkeypatch.setattr(sj, "autojoin_at_startup", boom)
    t = TailnetStartup(9000)
    asyncio.run(t.autojoin())  # 不抛
    assert order == ["autojoin"] and t.self_join is None

    # 源码顺序:launcher/services.py 里先 autojoin、后 initialize
    src = (ROOT / "launcher/services.py").read_text(encoding="utf-8")
    body = src[src.index("async def start_tailscale") :]
    assert body.index("await self.tailnet.autojoin()") < body.index("await ts.initialize()")


def test_the_banner_tells_installed_but_not_joined_apart_from_not_installed():
    from launcher.tailnet_startup import TailnetStartup

    t = TailnetStartup(9000)
    assert t.not_on_tailnet_details() == [("Tailscale", "未安装 (LAN 直连模式)", "warn")]

    t.self_join = {"state": "joined", "detail": "", "how_to_fix": ""}
    assert t.not_on_tailnet_details()[0][1].startswith("未安装")

    t.self_join = {"state": "needs_admin", "detail": "tailscale up 需要管理员权限", "how_to_fix": "sudo tailscale up x"}
    rows = t.not_on_tailnet_details()
    assert "没能加入自建 tailnet" in rows[0][1] and "需要管理员权限" in rows[0][1]
    assert rows[1] == ("修复", "sudo tailscale up x", "info")


def test_lan_discovery_is_published_and_stopped(monkeypatch):
    import galaxy_gateway.mdns_announcer as m
    from launcher.tailnet_startup import TailnetStartup

    started, stopped = [], []

    class Fake:
        def __init__(self, port):
            self.port = port

        def start(self):
            started.append(self.port)
            return True

        def stop(self):
            stopped.append(self.port)

    monkeypatch.setattr(m, "MdnsAnnouncer", Fake)
    monkeypatch.delenv("GALAXY_MDNS", raising=False)
    t = TailnetStartup(9100)
    assert t.start_lan_discovery() == ("局域网发现", "已发布 _galaxy._tcp", "ok")
    assert started == [9100], "应当用桌面版实际监听的端口,而不是写死的 9000"
    t.stop()
    t.stop()  # 重复停机无害
    assert stopped == [9100]


def test_lan_discovery_says_so_when_it_could_not_start(monkeypatch):
    import galaxy_gateway.mdns_announcer as m
    from launcher.tailnet_startup import TailnetStartup

    class NoLan:
        def __init__(self, port):
            pass

        def start(self):
            return False

    monkeypatch.setattr(m, "MdnsAnnouncer", NoLan)
    row = TailnetStartup(9000).start_lan_discovery()
    assert row[2] == "warn" and "未发布" in row[1], "没发出去却写『已发布』就是谎报"

    monkeypatch.setenv("GALAXY_MDNS", "0")
    assert m.start_lan_announcer(9000) is None


def test_launcher_wires_discovery_into_banner_and_shutdown():
    src = (ROOT / "launcher/services.py").read_text(encoding="utf-8")
    assert "self.tailnet = TailnetStartup(self.config.web_ui_port)" in src
    assert "bus_details.extend(self.tailnet.not_on_tailnet_details())" in src
    assert "bus_details.append(self.tailnet.start_lan_discovery())" in src
    stop = src[src.index("    def stop(self):") :]
    assert stop.index("self.tailnet.stop()") < stop.index("self.service_manager.stop_all()")


def test_gateway_lifespan_and_launcher_share_one_implementation():
    life = (ROOT / "galaxy_gateway/bootstrap/lifecycle.py").read_text(encoding="utf-8")
    assert "autojoin_at_startup" in life and "start_lan_announcer" in life
    assert "ensure_joined" not in life and "MdnsAnnouncer(" not in life, "lifespan 又自己写了一份"
    launcher = (ROOT / "launcher/tailnet_startup.py").read_text(encoding="utf-8")
    assert "autojoin_at_startup" in launcher and "start_lan_announcer" in launcher
