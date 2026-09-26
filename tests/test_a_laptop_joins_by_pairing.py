"""一台笔记本怎么接进来、智能体怎么用上它 —— 全程走真的。

真的网关(uvicorn,规范设备入口 + 权威 API 层,**鉴权开着**,和默认部署一样)、
真的笔记本客户端(``windows_client/windows_aip_client.py``,真 WebSocket)、
真的配对/令牌/UDM/UCM/接入平面/智能体工具入口。只替掉一处:笔记本上
「真的去点屏幕」的那一步(``_execute_command``),断言它**真的被调到**、参数对。

这条链此前在五个地方断着,每一处都有用例钉住:

1. 笔记本客户端不配对、不带令牌 —— 鉴权默认开启,注册被拒,客户端还一声不吭地重连;
2. 它把 capabilities 报成名字列表,入口 ``int(list)`` 抛错 —— 鉴权关着也注册不上;
3. 配对端点只在中间件里豁免,路由上的 ``Depends(require_auth)`` 又把它 401 回去 ——
   手机、手表也一样配不上;
4. 规范入口从不把连接登记进 UCM —— 连着的设备,派发闸一律判「传输不在」;
5. ``device__*`` 派发走的是生产里空着的 ``device_comm`` 表,永远「设备未连接」却报成功。
"""

from __future__ import annotations

import asyncio
import socket
import threading
import time

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")
pytest.importorskip("websockets")


@pytest.fixture
def gateway(tmp_path, monkeypatch):
    import uvicorn
    from fastapi import FastAPI

    import core.agent_card as ac
    import core.capability_token as ct
    import core.lumiv_websocket_bridge as lwb
    import core.peer_trust as pt
    from core.api_routes import create_api_routes
    from core.device_onboarding.conversation import reset_conversation_confirmations
    from core.device_onboarding.service import reset_onboarding_service
    from core.unified.connection_manager import reset_unified_connection_manager
    from core.unified.device_manager import reset_unified_device_manager
    from galaxy_gateway.routes.websocket import register_websocket_routes

    for k, v in {
        "GALAXY_NATS_ENABLED": "false",
        "GALAXY_AUTH_ENABLED": "true",
        "GALAXY_API_TOKEN": "owner-secret",
        "GALAXY_ONBOARDING_STATE_DIR": str(tmp_path / "ob"),
        "GALAXY_DATA_DIR": str(tmp_path),
        "GALAXY_PEER_TRUST_PATH": str(tmp_path / "peers.json"),
        "GALAXY_DEVICE_STATE": str(tmp_path / "laptop.json"),
    }.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("GALAXY_HEADSCALE_URL", raising=False)
    monkeypatch.setattr(ct, "_revoked_path", lambda: str(tmp_path / "revoked.json"))
    ct.reset_revoked_cache()
    said: list = []
    monkeypatch.setattr(lwb, "emit_conversation", lambda role, text, **kw: said.append(text))
    for r in (
        reset_unified_device_manager,
        reset_unified_connection_manager,
        reset_onboarding_service,
        reset_conversation_confirmations,
        ac.reset_pairing_code_registry,
        ac.reset_pairing_attempt_throttle,
        pt.reset_peer_trust_book,
    ):
        r()

    app = FastAPI()
    register_websocket_routes(app)
    app.include_router(create_api_routes(service_manager=None, config=None))
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    holder: dict = {}

    def serve():
        loop = asyncio.new_event_loop()
        holder["loop"] = loop
        asyncio.set_event_loop(loop)
        loop.run_until_complete(server.serve())

    threading.Thread(target=serve, daemon=True).start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.02)

    class GW:
        url = f"http://127.0.0.1:{port}"
        spoken = said

        @staticmethod
        def run(coro, timeout=30):
            return asyncio.run_coroutine_threadsafe(coro, holder["loop"]).result(timeout=timeout)

        @staticmethod
        def agent(action, args):
            from core.device_onboarding.agent_tools import dispatch_devices_tool

            return GW.run(dispatch_devices_tool(action, args, session_id="s1"))

    yield GW
    server.should_exit = True
    time.sleep(0.2)
    ct.reset_revoked_cache()
    for r in (reset_unified_device_manager, reset_unified_connection_manager, reset_onboarding_service):
        r()


class Laptop:
    """真的 WindowsAIPClient;只把「在 Windows 上执行」换成记账。"""

    def __init__(self, gw, monkeypatch, state):
        import windows_client.windows_aip_client as wac

        self.done: list = []
        monkeypatch.setattr(
            wac, "_execute_command", lambda action, params: (self.done.append((action, params)), {"success": True})[1]
        )
        port = int(gw.url.rsplit(":", 1)[1])
        self.client = wac.WindowsAIPClient(host="127.0.0.1", port=port, state=state)
        self.thread = threading.Thread(target=lambda: asyncio.run(self.client.run()), daemon=True)
        self.thread.start()

    def wait_connected(self, timeout=20.0) -> bool:
        from core.unified.connection_manager import get_unified_connection_manager

        deadline = time.time() + timeout
        while time.time() < deadline:
            if get_unified_connection_manager().is_device_connected(self.client.device_id):
                return True
            if self.client.fatal:
                return False
            time.sleep(0.05)
        return False


def _pair(gw, name="书房笔记本"):
    from windows_client import device_pairing as dp

    invite = gw.agent("invite", {"kind": "laptop"})
    state: dict = {}
    resp = dp.pair(invite["code"], gw.url, state, name=name, device_type="windows_laptop")
    # 名片里的局域网地址指向网关的「配置端口」;测试服务器跑在随机端口,只留命令行给的那条
    state["candidates"] = []
    return invite, state, resp


def test_a_laptop_pairs_connects_and_the_agent_operates_it(gateway, monkeypatch):
    invite, state, resp = _pair(gateway)
    assert invite["success"] and resp["success"] and state["token"]

    laptop = Laptop(gateway, monkeypatch, state)
    assert laptop.wait_connected(), laptop.client.fatal
    did = laptop.client.device_id

    listing = gateway.agent("list", {})
    [me] = [m for group in listing["members"].values() for m in group if m["device_id"] == did]
    assert me["online"] and me["type"] == "windows_laptop" and me["name"] == "书房笔记本"
    assert "click" in me["capabilities"] and "GUI_SCREENSHOT" in me["capability_classes"]

    out = gateway.agent("invoke", {"device_id": did, "action": "click", "params": {"x": 10, "y": 20}})
    assert out["success"], out
    assert laptop.done == [("click", {"x": 10, "y": 20})]

    time.sleep(0.2)
    assert gateway.spoken == ["笔记本「书房笔记本」配对好了,正在连过来。", "「书房笔记本」连上了,现在可以让我操作它。"]


def test_an_unpaired_laptop_is_refused_and_says_so_instead_of_retrying_forever(gateway, monkeypatch):
    laptop = Laptop(gateway, monkeypatch, {"gateway": gateway.url})
    assert not laptop.wait_connected(timeout=10)
    assert laptop.client.fatal and "--pair" in laptop.client.fatal
    laptop.thread.join(timeout=5)
    assert not laptop.thread.is_alive()


def test_the_laptop_keeps_its_identity_across_restarts(gateway, monkeypatch):
    from windows_client import device_pairing as dp

    _, state, _ = _pair(gateway)
    dp.save_state(state)
    first = Laptop(gateway, monkeypatch, dp.load_state())
    assert first.wait_connected()
    again = dp.load_state()
    assert dp.stable_device_id(again) == first.client.device_id


def test_pairing_is_reachable_with_auth_on_but_the_rest_of_pairing_is_not(gateway):
    import json
    import urllib.error
    import urllib.request

    def post(path, body, headers=None):
        req = urllib.request.Request(
            gateway.url + path,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", **(headers or {})},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code

    # 一台还没配对的设备:没有任何令牌,也得能来领 —— 错码是 400,不是 401
    assert post("/api/v1/pair/claim", {"code": "WRONG1", "device_id": "x"}) == 400
    # 其余配对操作是主人的事:不带令牌 401
    assert post("/api/v1/pair/trust", {"device_id": "x", "trust": "trusted"}) == 401
    assert (
        post("/api/v1/pair/trust", {"device_id": "x", "trust": "trusted"}, {"Authorization": "Bearer owner-secret"})
        == 200
    )


def test_the_token_renews_and_the_old_one_stops_working(gateway):
    from core.capability_token import verify_token
    from windows_client import device_pairing as dp

    _, state, _ = _pair(gateway)
    old = state["token"]
    assert dp.renew_if_due(state) is False  # 离过期还远
    assert dp.renew_if_due(state, now=time.time() + 23 * 3600) is True
    assert state["token"] != old
    assert verify_token(state["token"]).valid and not verify_token(old).valid

    with pytest.raises(dp.PairingError):  # 旧令牌不能再拿来换
        dp.renew_if_due({**state, "token": old, "token_expires_at": 0}, now=time.time())


def test_a_removed_laptop_cannot_renew(gateway):
    from core.peer_trust import get_peer_trust_book
    from windows_client import device_pairing as dp

    _, state, _ = _pair(gateway)
    get_peer_trust_book().remove(state["device_id"])
    with pytest.raises(dp.PairingError) as e:
        dp.renew_if_due({**state, "token_expires_at": 0}, now=time.time())
    assert "重新配对" in e.value.how_to_fix


def test_a_token_cannot_be_renewed_for_another_device(gateway):
    from windows_client import device_pairing as dp

    _, a, _ = _pair(gateway, name="A")
    _, b, _ = _pair(gateway, name="B")
    assert a["device_id"] != b["device_id"]
    # 两台都配过对、都在名册里:拦住它的只能是「令牌签给的不是你」
    with pytest.raises(dp.PairingError):
        dp.renew_if_due({**a, "token": b["token"], "token_expires_at": 0}, now=time.time())


def test_an_old_connection_closing_late_does_not_take_the_new_one_offline(gateway, monkeypatch):
    """弱网下新连接先连上、旧连接后关:旧的收尾不能把设备判成离线。"""
    import json

    import websockets

    _, state, _ = _pair(gateway)
    laptop = Laptop(gateway, monkeypatch, state)
    assert laptop.wait_connected()
    did = laptop.client.device_id
    ws_url = gateway.url.replace("http://", "ws://") + f"/ws/device/{did}"

    async def ghost():
        # 一条「旧」连接:用同一枚令牌注册,然后被新的顶掉,最后才关
        async with websockets.connect(ws_url) as old:
            await old.send(json.dumps(laptop.client._device_register_msg()))
            await old.recv()
            # 笔记本重新注册,成为当前连接
            await laptop.client._send(laptop.client._device_register_msg())
            await asyncio.sleep(0.5)

    gateway.run(ghost())
    time.sleep(0.3)
    from core.unified.connection_manager import get_unified_connection_manager

    assert get_unified_connection_manager().is_device_connected(did)
    out = gateway.agent("invoke", {"device_id": did, "action": "screenshot"})
    assert out["success"], out


def test_joining_the_private_network_uses_the_grant_and_never_hijacks_an_existing_one():
    import subprocess

    from windows_client import device_pairing as dp

    grant = {"control_url": "https://hs.example", "auth_key": "k1"}
    calls = []

    def run(state):
        def _run(cmd):
            calls.append(cmd)
            if cmd[1] == "status":
                return subprocess.CompletedProcess(cmd, 0, json.dumps({"BackendState": state}), "")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        return _run

    import json

    assert dp.join_tailnet(grant, "lap-1", run=run("NeedsLogin"), which=lambda _: "tailscale")["state"] == "joined"
    assert calls[-1] == ["tailscale", "up", "--login-server=https://hs.example", "--authkey=k1", "--hostname=lap-1"]
    calls.clear()
    assert (
        dp.join_tailnet(grant, "lap-1", run=run("Running"), which=lambda _: "tailscale")["state"]
        == "already_in_a_tailnet"
    )
    assert all(c[1] != "up" for c in calls)
    missing = dp.join_tailnet(grant, "lap-1", which=lambda _: None)
    assert missing["state"] == "no_tailscale" and "--pair" in missing["how_to_fix"]
    assert "k1" not in json.dumps(missing)  # 钥匙是秘密,不进给人看的提示

    def refused(cmd):
        if cmd[1] == "status":
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"BackendState": "NeedsLogin"}), "")
        return subprocess.CompletedProcess(cmd, 1, "", "access denied for --authkey=k1")

    failed = dp.join_tailnet(grant, "lap-1", run=refused, which=lambda _: "tailscale")
    assert failed["state"] == "failed" and "k1" not in json.dumps(failed, ensure_ascii=False)
    assert dp.join_tailnet(None, "lap-1")["state"] == "no_grant"


def test_pairing_does_not_wait_for_the_conversation_record(gateway, monkeypatch):
    """记进对话主线要落盘;不管它多慢,配对都不能等它(CI 干净环境里曾因此 15 秒超时)。"""
    from core.session_manager import get_session_manager

    async def stuck(*a, **kw):
        await asyncio.sleep(60)

    monkeypatch.setattr(get_session_manager(), "add_message", stuck)
    started = time.time()
    _, state, resp = _pair(gateway)
    assert resp["success"] and state["token"]
    assert time.time() - started < 5
    assert gateway.spoken == ["笔记本「书房笔记本」配对好了,正在连过来。"]  # 推面板不等记录
