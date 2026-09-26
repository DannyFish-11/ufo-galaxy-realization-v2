"""自建 tailnet 与设备列表是一套东西。

钉的事:
  1. 设备列表每台设备带上它在 tailnet 里的身份(靠配对时记下的钥匙认,最可靠),
     认不出来的节点单列,headscale 没配/不在线时设备列表照常;
  2. 移除设备 = 把它踢出 tailnet(丢了的手表不能还在你的网里);
  3. 这台电脑(智能体所在)自动加入;已在别的控制服务器上时不动它;
     没装客户端、权限不够时给出能照做的下一步;
  4. 手机/笔记本有一键加入的钥匙与说明;
  5. headscale 新旧版本的建钥匙接口都能用;
  6. 部署文件本身:版本钉死、不依赖外部中继、示例地址没改就不往下走。

真 headscale v0.29.4 + 真 tailscaled 上的验证见提交说明(配对→手表进程加入→设备列表
认出它→移除设备后节点消失;电脑自动加入、重复调用不重复加入、未装客户端、已在别处)。
"""

from __future__ import annotations

import io
import pathlib
import subprocess
import types
import urllib.error

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core import headscale_join as hj
from core import tailnet_membership as tm
from core import tailnet_self_join as sj

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture
def configured(monkeypatch, tmp_path):
    monkeypatch.setenv("GALAXY_HEADSCALE_URL", "https://hs.example.internal")
    monkeypatch.setenv("GALAXY_HEADSCALE_API_KEY", "hskey-api-xyz")
    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("GALAXY_TAILNET_MEMBERSHIP_PATH", raising=False)
    tm.invalidate_cache()
    yield
    tm.invalidate_cache()


@pytest.fixture
def unconfigured(monkeypatch, tmp_path):
    for k in ("GALAXY_HEADSCALE_URL", "GALAXY_HEADSCALE_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
    tm.invalidate_cache()


def node(nid, name, ip, key_id="", online=True):
    return hj.TailnetNode(nid, name, (ip,), online, "", key_id)


# ---------------------------------------------------------------------------
# 一、认设备
# ---------------------------------------------------------------------------


def test_the_key_recorded_at_pairing_identifies_the_node_even_under_another_name():
    devices = [{"device_id": "watch-1"}]
    nodes = [node("5", "whatever-name", "100.64.0.9", key_id="42")]
    by, rest = tm.match_nodes(devices, nodes, {"watch-1": {"key_id": "42"}})
    assert by["watch-1"].node_id == "5" and rest == []


def test_watch_process_name_and_address_are_fallbacks():
    devices = [{"device_id": "3F9A1C22-aaaa"}, {"device_id": "phone-1", "remote_ip": "100.64.0.20"}]
    nodes = [
        node("1", "galaxy-watch-3f9a1c", "100.64.0.9"),
        node("2", "pixel", "100.64.0.20"),
        node("3", "my-laptop", "100.64.0.30"),
    ]
    by, rest = tm.match_nodes(devices, nodes, {})
    assert by["3F9A1C22-aaaa"].node_id == "1"
    assert by["phone-1"].node_id == "2"
    assert [n.name for n in rest] == ["my-laptop"], "认不出来的节点要单列,而不是丢掉或猜"


def test_one_node_is_never_given_to_two_devices():
    devices = [{"device_id": "a"}, {"device_id": "b"}]
    nodes = [node("1", "n", "100.64.0.9", key_id="7")]
    by, _ = tm.match_nodes(devices, nodes, {"a": {"key_id": "7"}, "b": {"key_id": "7"}})
    assert list(by) == ["a"]


def test_watch_hostname_rule_matches_the_watch_side():
    # 与 galaxy-wearos TailnetProtocol.hostnameFor 同一规则(那边有同样的样例)
    assert tm.watch_hostname("3F9A1C22-7b0e-4d0e") == "galaxy-watch-3f9a1c"
    assert tm.watch_hostname("---") == "galaxy-watch"


def test_device_list_is_untouched_when_headscale_is_not_configured(unconfigured):
    devices = [{"device_id": "w"}]
    out = tm.annotate(devices)
    assert out["configured"] is False and devices[0]["tailnet"] is None


def test_device_list_survives_headscale_being_down(configured, monkeypatch):
    def boom(**_):
        raise hj.JoinUnavailable("headscale_unreachable", "x")

    monkeypatch.setattr(tm, "list_nodes", boom)
    devices = [{"device_id": "w"}]
    out = tm.annotate(devices)
    assert out["reachable"] is False and devices[0]["tailnet"] is None


def test_annotate_uses_the_recorded_grant(configured, monkeypatch):
    tm.record_grant("watch-1", hj.JoinGrant("u", "k", 0, key_id="9"))
    monkeypatch.setattr(
        tm, "list_nodes", lambda **_: [node("3", "x", "100.64.0.3", key_id="9"), node("4", "y", "100.64.0.4")]
    )
    devices = [{"device_id": "watch-1"}]
    out = tm.annotate(devices)
    assert devices[0]["tailnet"]["ips"] == ["100.64.0.3"]
    assert [n["name"] for n in out["tailnet_only"]] == ["y"]


# ---------------------------------------------------------------------------
# 二、移除设备 = 收回网络
# ---------------------------------------------------------------------------


def test_forgetting_a_device_deletes_its_node(configured, monkeypatch):
    tm.record_grant("watch-1", hj.JoinGrant("u", "k", 0, key_id="9"))
    deleted = []
    monkeypatch.setattr(tm, "list_nodes", lambda **_: [node("3", "x", "100.64.0.3", key_id="9")])
    monkeypatch.setattr(tm, "delete_node", lambda nid, **_: deleted.append(nid))
    out = tm.forget_device("watch-1")
    assert out["tailnet_removed"] is True and deleted == ["3"]
    assert "watch-1" not in tm._load(), "记录也要删,不然之后还会认错"


def test_forgetting_a_device_that_never_joined_says_so(configured, monkeypatch):
    monkeypatch.setattr(tm, "list_nodes", lambda **_: [])
    monkeypatch.setattr(tm, "delete_node", lambda *_a, **_k: pytest.fail("不该删任何东西"))
    assert tm.forget_device("nope")["reason"] == "not_in_tailnet"


def test_failing_to_remove_from_tailnet_is_reported(configured, monkeypatch):
    def boom(**_):
        raise hj.JoinUnavailable("api_key_rejected", "重新生成 API key")

    monkeypatch.setattr(tm, "list_nodes", boom)
    out = tm.forget_device("watch-1")
    assert out["tailnet_removed"] is False and out["how_to_fix"]


# ---------------------------------------------------------------------------
# 三、这台电脑自动加入
# ---------------------------------------------------------------------------


class FakeTailscale:
    """按脚本回应 tailscale 命令。"""

    def __init__(self, backend="NeedsLogin", control="", up_rc=0, up_err=""):
        self.backend, self.control, self.up_rc, self.up_err = backend, control, up_rc, up_err
        self.calls = []

    def __call__(self, cmd):
        self.calls.append(cmd)
        if cmd[1:3] == ["status", "--json"]:
            ips = '["100.64.0.1"]' if self.backend == "Running" else "[]"
            return types.SimpleNamespace(
                returncode=0, stdout=f'{{"BackendState":"{self.backend}","Self":{{"TailscaleIPs":{ips}}}}}', stderr=""
            )
        if cmd[1:3] == ["debug", "prefs"]:
            return types.SimpleNamespace(returncode=0, stdout=f'{{"ControlURL":"{self.control}"}}', stderr="")
        if cmd[1] == "up":
            if self.up_rc == 0:
                self.backend, self.control = "Running", cmd[2].split("=", 1)[1]
            return types.SimpleNamespace(returncode=self.up_rc, stdout="", stderr=self.up_err)
        raise AssertionError(cmd)


@pytest.fixture
def has_tailscale(monkeypatch):
    monkeypatch.setattr(sj.shutil, "which", lambda _: "/usr/bin/tailscale")


def _grant():
    return hj.JoinGrant("https://hs.example.internal", "hskey-auth-1", 0, key_id="1")


def test_joins_with_a_fresh_key_against_our_own_server(configured, has_tailscale):
    ts = FakeTailscale()
    out = sj.ensure_joined(run=ts, issue=_grant)
    assert out["state"] == "joined"
    up = next(c for c in ts.calls if c[1] == "up")
    assert "--login-server=https://hs.example.internal" in up
    assert "--authkey=hskey-auth-1" in up


def test_already_joined_is_left_alone(configured, has_tailscale):
    ts = FakeTailscale(backend="Running", control="https://hs.example.internal/")
    out = sj.ensure_joined(run=ts, issue=lambda: pytest.fail("已经在里面了,不该再签钥匙"))
    assert out["state"] == "joined"
    assert not any(c[1] == "up" for c in ts.calls)


def test_a_machine_on_another_control_server_is_not_hijacked(configured, has_tailscale):
    ts = FakeTailscale(backend="Running", control="https://controlplane.tailscale.com")
    out = sj.ensure_joined(run=ts, issue=lambda: pytest.fail("不该动别人的网"))
    assert out["state"] == "joined_elsewhere"
    assert not any(c[1] == "up" for c in ts.calls)


def test_no_client_installed_says_how_to_get_it(configured, monkeypatch):
    monkeypatch.setattr(sj.shutil, "which", lambda _: None)
    out = sj.ensure_joined(run=lambda c: pytest.fail("没装就不该执行任何命令"), issue=_grant)
    assert out["state"] == "no_tailscale" and "tailscale.com/download" in out["how_to_fix"]


def test_needing_admin_gives_a_command_to_copy(configured, has_tailscale):
    ts = FakeTailscale(up_rc=1, up_err="failed to connect to local tailscaled: permission denied")
    out = sj.ensure_joined(run=ts, issue=_grant)
    assert out["state"] == "needs_admin"
    assert (
        out["how_to_fix"].startswith("用管理员身份执行")
        and "--login-server=https://hs.example.internal" in out["how_to_fix"]
    )


def test_not_configured_does_nothing(unconfigured):
    out = sj.ensure_joined(run=lambda c: pytest.fail("没配就不该执行任何命令"), issue=_grant)
    assert out["state"] == "not_configured"


def test_gateway_startup_joins_before_probing_tailscale():
    """顺序:先加入,再让 TailscaleManager 探测 —— 反过来的话刚拿到的 100.x 要等下一轮才被看见。"""
    src = (ROOT / "galaxy_gateway/bootstrap/lifecycle.py").read_text(encoding="utf-8")
    assert "ensure_joined" in src
    assert src.index("ensure_joined") < src.index("await _ts_mgr.initialize()")


# ---------------------------------------------------------------------------
# 四、手机 / 笔记本加入;状态;设备列表接口
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    from core.routes.pairing import create_router

    app = FastAPI()
    app.include_router(create_router())
    return TestClient(app)


def test_join_key_for_a_laptop_is_a_command(configured, client, monkeypatch):
    monkeypatch.setattr(hj, "issue_join_key", lambda *a, **k: _grant())
    r = client.post("/api/v1/tailnet/join-key", json={"device_kind": "linux"}).json()
    assert r["success"] and r["single_use"] is True
    assert r["command"] == "sudo tailscale up --login-server=https://hs.example.internal --authkey=hskey-auth-1"


def test_join_key_for_a_phone_is_app_steps(configured, client, monkeypatch):
    monkeypatch.setattr(hj, "issue_join_key", lambda *a, **k: _grant())
    r = client.post("/api/v1/tailnet/join-key", json={"device_kind": "android"}).json()
    assert r["how"] == "app" and r["control_url"] == "https://hs.example.internal" and r["auth_key"]


def test_join_key_without_headscale_says_why(unconfigured, client):
    r = client.post("/api/v1/tailnet/join-key", json={"device_kind": "linux"})
    assert r.status_code == 409 and r.json()["reason"] == "no_headscale_url"


def test_status_does_not_leak_the_api_key(configured, client, monkeypatch):
    monkeypatch.setattr(hj, "list_nodes", lambda **_: [])
    monkeypatch.setattr(sj.shutil, "which", lambda _: None)
    body = client.get("/api/v1/tailnet/status").text
    assert "hskey-api-xyz" not in body and '"configured":true' in body.replace(" ", "")


def test_device_list_endpoint_carries_tailnet(unconfigured):
    src = (ROOT / "core/routes/devices.py").read_text(encoding="utf-8")
    assert "from core.tailnet_membership import annotate" in src
    assert '"tailnet": tailnet' in src


def test_pairing_records_the_grant(configured, monkeypatch):
    import asyncio

    from core.routes import pairing

    monkeypatch.setattr(hj, "issue_join_key", lambda *a, **k: _grant())
    out = asyncio.run(pairing._tailnet_join_for("wearos", "watch-7"))
    assert out["tailnet_join"]["auth_key"] == "hskey-auth-1"
    assert "key_id" not in out["tailnet_join"], "key_id 是网关自己留的,不交给设备"
    assert tm._load()["watch-7"]["key_id"] == "1"


# ---------------------------------------------------------------------------
# 五、headscale 新旧版本
# ---------------------------------------------------------------------------


def test_older_headscale_that_wants_the_user_name_still_works(configured):
    seen = []

    def call(method, url, headers, body):
        seen.append(body)
        if method == "GET":
            return {"users": [{"id": "7", "name": "galaxy"}]}
        if body["user"] == "7":  # 0.26 以前:按 id 会被当成用户名 "7" 而报错
            raise urllib.error.HTTPError(url, 500, "user not found", {}, io.BytesIO(b""))
        return {"preAuthKey": {"key": "k", "id": "3"}}

    g = hj.issue_join_key(http_json=call)
    assert g.auth_key == "k" and [b["user"] for b in seen if b] == ["7", "galaxy"]


def test_node_list_parses_both_field_styles(configured):
    camel = {
        "nodes": [
            {"id": "1", "givenName": "a", "ipAddresses": ["100.64.0.1"], "online": True, "preAuthKey": {"id": "9"}}
        ]
    }
    snake = {"nodes": [{"id": "2", "given_name": "b", "ip_addresses": ["100.64.0.2"], "pre_auth_key": {"id": "8"}}]}
    assert hj.list_nodes(http_json=lambda *a: camel)[0].pre_auth_key_id == "9"
    n = hj.list_nodes(http_json=lambda *a: snake)[0]
    assert (n.name, n.ips, n.pre_auth_key_id) == ("b", ("100.64.0.2",), "8")


def test_deleting_a_node_refuses_a_non_numeric_id(configured):
    with pytest.raises(hj.JoinUnavailable):
        hj.delete_node("../../user", http_json=lambda *a: {})


# ---------------------------------------------------------------------------
# 六、部署文件
# ---------------------------------------------------------------------------

DEPLOY = ROOT / "deploy/headscale"


def test_headscale_version_is_pinned():
    compose = (DEPLOY / "docker-compose.yml").read_text(encoding="utf-8")
    assert "image: headscale/headscale:0.29.4" in compose
    assert ":latest" not in compose


def test_no_dependency_on_outside_relays_by_default():
    cfg = (DEPLOY / "config.yaml").read_text(encoding="utf-8")
    body = "\n".join(ln for ln in cfg.splitlines() if not ln.lstrip().startswith("#"))
    assert "controlplane.tailscale.com" not in body, "默认不该依赖 Tailscale 公司的中继"
    assert "enabled: true" in body.split("derp:")[1].split("database:")[0]
    assert "override_local_dns: false" in body, "加入 tailnet 不该接管电脑自己的 DNS"


def test_init_refuses_the_example_address(tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_text("server_url: https://hs.example.com\n", encoding="utf-8")
    r = subprocess.run(
        ["bash", str(DEPLOY / "init.sh")],
        env={"PATH": "/usr/bin:/bin", "HS_CONFIG_FILE": str(cfg), "HS_CMD": "false"},
        capture_output=True,
        text=True,
    )
    assert r.returncode == 1 and "示例值" in r.stdout


def test_the_obsolete_watch_script_is_gone():
    """那个脚本教人往手表上装 Tailscale —— Wear OS 上装不了。"""
    assert not (DEPLOY / "connect-watch.sh").exists()


def test_removing_a_device_in_the_panel_also_takes_it_off_the_tailnet(configured, client, monkeypatch):
    """面板上"移除设备"这个按钮真的走到了踢出 tailnet 那一步。"""
    tm.record_grant("watch-1", hj.JoinGrant("u", "k", 0, key_id="9"))
    deleted = []
    monkeypatch.setattr(tm, "list_nodes", lambda **_: [node("3", "x", "100.64.0.3", key_id="9")])
    monkeypatch.setattr(tm, "delete_node", lambda nid, **_: deleted.append(nid))
    r = client.delete("/api/v1/pair/peers/watch-1").json()
    assert r["tailnet_removed"] is True and deleted == ["3"]
