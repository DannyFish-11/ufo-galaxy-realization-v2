"""设备接入平面:发现 → 候选 → 接入 → 成员,在线归 UCM,重启不丢。

全部走真实入口(LanDiscovery / 发现来源函数 / OnboardingService / UDM / UCM);
Home Assistant 用本地假服务器顶替(REST 走 HTTP,WS 命令走一个真的 WebSocket 服务),
断言它**真的收到了**那几次调用。
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from core.device_onboarding import ha_client
from core.device_onboarding.models import Observation
from core.device_onboarding.service import get_onboarding_service, reset_onboarding_service


@pytest.fixture
def plane(tmp_path, monkeypatch):
    from core.mesh.mesh_auto_enrollment import reset_auto_enrollment_service
    from core.unified.connection_manager import reset_unified_connection_manager
    from core.unified.device_manager import reset_unified_device_manager

    monkeypatch.setenv("GALAXY_ONBOARDING_STATE_DIR", str(tmp_path / "onboarding"))
    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("GALAXY_ONBOARDING_AUTO", raising=False)
    monkeypatch.delenv("HOME_ASSISTANT_URL", raising=False)
    monkeypatch.delenv("HOME_ASSISTANT_TOKEN", raising=False)
    monkeypatch.delenv("GALAXY_HEADSCALE_URL", raising=False)
    reset_unified_device_manager()
    reset_unified_connection_manager()
    reset_onboarding_service()
    reset_auto_enrollment_service()
    yield get_onboarding_service()
    reset_unified_device_manager()
    reset_unified_connection_manager()
    reset_onboarding_service()
    reset_auto_enrollment_service()


def _udm():
    from core.unified.device_manager import get_unified_device_manager

    return get_unified_device_manager()


def _ucm():
    from core.unified.connection_manager import get_unified_connection_manager

    return get_unified_connection_manager()


# ── UCM:在线态通道化 ───────────────────────────────────────────────────


def test_bridged_device_presence_lives_in_ucm(plane):
    ucm = _ucm()
    ucm.report_presence("ha_light.x", "bridge", True)
    view = ucm.get_presence_view()["ha_light.x"]
    assert view["online"] is True and view["channel"] == "bridge"
    assert ucm.is_present("ha_light.x")
    assert not ucm.is_device_connected("ha_light.x")  # 语义不变:仍只表示有 WS 句柄
    ucm.report_presence("ha_light.x", "bridge", False)
    assert ucm.get_presence_view()["ha_light.x"]["online"] is False


def test_heartbeat_channels_expire(plane):
    ucm = _ucm()
    ucm.report_presence("w1", "nats", True)
    ucm._channels["w1"]["nats"]["last_seen"] = time.time() - 120
    assert not ucm.is_present("w1")


def test_unknown_channel_is_refused(plane):
    with pytest.raises(ValueError):
        _ucm().report_presence("x", "websocket", True)


def test_websocket_presence_entry_is_unchanged(plane):
    class _WS:
        pass

    ucm = _ucm()
    asyncio.run(ucm.register_connection("phone", _WS()))
    ucm.report_presence("other", "lan", True)
    entry = ucm.get_presence_view()["phone"]
    assert set(entry) == {"device_id", "online", "routable", "last_seen", "state", "total_reconnects"}


# ── mDNS:看见 ≠ 接入 ─────────────────────────────────────────────────


def test_a_chromecast_nearby_is_a_candidate_not_a_device(plane):
    from core.lan_discovery import LanDiscovery

    lan = LanDiscovery()
    name = "Living Room TV._googlecast._tcp.local."
    assert lan.ingest_service("_googlecast._tcp.local.", name, "192.168.1.50", 8009, {"md": "Chromecast"})
    assert _udm().list_devices() == []  # 以前:以 iot+在线 写进设备表
    [cand] = plane.overview()["candidates"]
    assert cand["name"] == "Living Room TV"
    assert cand["join_path"] == "via_home_assistant"
    assert "lan" in _ucm().channel_presence(LanDiscovery._device_id(name))

    lan.service_removed("_googlecast._tcp.local.", name)
    [cand] = plane.overview()["candidates"]
    assert cand["present"] is False
    assert not _ucm().is_present(LanDiscovery._device_id(name))


def test_a_paired_phone_announcing_itself_is_recognised_not_duplicated(plane):
    from core.lan_discovery import LanDiscovery

    _udm().register_device_from_dict("phone-1", {"device_type": "android_phone", "transport": "websocket"})
    lan = LanDiscovery()
    lan.ingest_service(
        "_galaxy-aip3._tcp.", "phone-1._galaxy-aip3._tcp.", "192.168.1.30", 19421, {"device_id": "phone-1"}
    )
    ov = plane.overview()
    assert ov["candidates"] == []
    [phone] = ov["groups"]["subjects"]
    assert phone["device_id"] == "phone-1" and phone["channels"]["lan"] is True
    assert [d.device_id for d in _udm().list_devices()] == ["phone-1"]


# ── 候选的持久与忽略 ─────────────────────────────────────────────────


def test_ignored_candidates_stay_ignored_across_restarts(plane):
    c = plane.observe(Observation(source="ssdp", key="uuid-1", name="Router", kind_hint="iot"))
    plane.ignore(c.candidate_id)
    reset_onboarding_service()
    svc = get_onboarding_service()
    svc.observe(Observation(source="ssdp", key="uuid-1", name="Router"))
    ov = svc.overview()
    assert ov["candidates"] == [] and ov["summary"]["ignored"] == 1


# ── 需要"同意一下"的候选:同意 → 成员;重启不丢;在线来自通道 ──────────────────
#
# 拿插在主脑上的串口设备当样本 —— 它的接入路径(local_bus)就是"批准一档"。
# NATS worker **不是**发现来源(理由见 core/device_onboarding/sources.py 模块头),
# 所以这里不再用它做样本。

#: 一块插在主脑上的板子(product 只报一个名字,很多 USB 转串口设备就是这样)。
_SERIAL = {"device": "/dev/ttyACM0", "vid": "2341", "pid": "0043", "serial_number": "758", "product": "nas"}
_SERIAL_ID = "serial-usb-2341-0043-758"


def _see_serial():
    """走真实来源函数:端口字典 → Observation → observe()。"""
    from core.device_onboarding import local_buses as lb

    return get_onboarding_service().observe(lb.serial_observation(_SERIAL))


def test_a_candidate_waits_for_approval_by_default_then_joins(plane):
    _see_serial()
    [cand] = plane.overview()["candidates"]
    assert (cand["join_path"], cand["human_step"], cand["status"]) == ("local_bus", "approve", "new")
    assert _udm().get_device(_SERIAL_ID) is None

    out = asyncio.run(plane.join(cand["candidate_id"]))
    assert out["success"] and out["outcome"]["kind"] == "joined"
    d = _udm().get_device(_SERIAL_ID)
    assert (d.transport, d.execution_model) == ("serial", "adapter_bridged_device")

    _ucm().report_presence(_SERIAL_ID, "local", True)
    # 插在主脑上的设备是"被接入"的一类,归 bridged 组,不是能自己跑运行时的成员
    [board] = plane.overview()["groups"]["bridged"]
    assert board["online"] is True and board["channels"] == {"local": True}


def test_the_onboarding_plane_does_not_ingest_nats_worker_lifecycle(plane):
    """worker 生命周期是分发层,消费者只有 MasterBrain。

    接入平面再去订阅,就把"设备 → 发 worker 事件 → 调度器"这条单向边接成了环
    (worker 事件 → observe → 接入时 register_device_from_dict → 又发 worker 事件)。
    这条测试钉住那条边不再存在。
    """
    import pkgutil

    import core.device_onboarding as pkg

    offenders = {}
    for mod in pkgutil.iter_modules(pkg.__path__):
        text = open(f"{pkg.__path__[0]}/{mod.name}.py", encoding="utf-8").read()
        # 模块头的说明文字里会提到它为什么不在这儿,所以只看代码行
        code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
        code = code.split('"""')
        code = "".join(code[::2])  # 去掉 docstring
        hits = [n for n in ("WorkerLifecycleSubjects", "galaxy.workers.", "subscribe_worker") if n in code]
        if hits:
            offenders[mod.name] = hits
    assert offenders == {}, f"接入平面不该碰 worker 生命周期: {offenders}"


def test_members_survive_a_restart_as_offline_until_a_source_reports(plane):
    from core.device_onboarding.models import MemberRecord
    from core.unified.device_manager import reset_unified_device_manager

    plane.admit(
        MemberRecord(
            device_id=_SERIAL_ID, device_name="nas", device_type="iot", transport="serial", join_path="local_bus"
        )
    )
    reset_unified_device_manager()  # 进程重启:UDM 只在内存
    reset_onboarding_service()
    assert get_onboarding_service().rehydrate() == 1
    from core.unified.models import UnifiedDeviceStatus

    d = _udm().get_device(_SERIAL_ID)
    assert d.status in (UnifiedDeviceStatus.OFFLINE, "offline") and not d.is_online()
    assert d.transport == "serial"  # 身份完整回来了,只是还没人报在线


def test_auto_level_approve_joins_without_asking(plane, monkeypatch):
    monkeypatch.setenv("GALAXY_ONBOARDING_AUTO", "approve")

    async def go():
        _see_serial()
        for _ in range(20):
            await asyncio.sleep(0)

    asyncio.run(go())
    assert _udm().get_device(_SERIAL_ID) is not None


def test_joined_member_is_enrolled_into_the_mesh(plane):
    from core.mesh.mesh_auto_enrollment import get_auto_enrollment_service

    _see_serial()
    [cand] = plane.overview()["candidates"]
    asyncio.run(plane.join(cand["candidate_id"]))
    rec = get_auto_enrollment_service().get_record(_SERIAL_ID)
    assert rec is not None and rec.registered


# ── 移除:该收回的都收回 ──────────────────────────────────────────────


def test_remove_takes_back_everything(plane):
    _see_serial()
    [cand] = plane.overview()["candidates"]
    asyncio.run(plane.join(cand["candidate_id"]))
    _ucm().report_presence(_SERIAL_ID, "local", True)

    out = asyncio.run(plane.remove(_SERIAL_ID))
    assert out["success"] and out["roster"] and out["device_table"]
    assert _udm().get_device(_SERIAL_ID) is None
    assert not _ucm().is_present(_SERIAL_ID)
    assert plane.roster.get(_SERIAL_ID) is None
    # 再次看见 → 新候选,而不是"已接入"
    _see_serial()
    [again] = plane.overview()["candidates"]
    assert again["status"] == "new"


# ── 需要人在场的,永远不会被自动化 ──────────────────────────────────────


def test_matter_needs_the_physical_code_even_when_auto_is_approve(plane, monkeypatch):
    monkeypatch.setenv("GALAXY_ONBOARDING_AUTO", "approve")
    from core.lan_discovery import LanDiscovery

    LanDiscovery().ingest_service("_matterc._udp.local.", "PLUG-01._matterc._udp.local.", "192.168.1.60", 5540, {})
    [cand] = plane.overview()["candidates"]
    assert (cand["join_path"], cand["human_step"], cand["status"]) == ("matter_via_ha", "physical_code", "new")
    out = asyncio.run(plane.join(cand["candidate_id"]))
    assert out["candidate"]["status"] == "needs_human"
    assert out["outcome"]["needs"]["inputs"][0]["name"] == "code"


def test_galaxy_peer_gets_a_real_one_time_pairing_code(plane):
    from core.agent_card import get_pairing_code_registry, reset_pairing_code_registry

    reset_pairing_code_registry()
    c = plane.observe(Observation(source="tailnet", key="7", name="old-laptop", addresses=["100.64.0.9"]))
    out = asyncio.run(plane.join(c.candidate_id))
    needs = out["outcome"]["needs"]
    assert out["outcome"]["human_step"] == "confirm_on_device"
    assert needs["code"] in needs["what"]
    assert get_pairing_code_registry().resolve(needs["code"]) == needs["link"]


# ── 经 Home Assistant 接入(REST 配置流 + WS 配网命令) ──────────────────────


class _FakeHA:
    def __init__(self):
        self.calls = []
        self.ws_commands = []
        self.flows = {
            "f-cast": {
                "handler": "cast",
                "context": {"source": "zeroconf", "title_placeholders": {"name": "Living Room TV"}},
            },
            "f-hk": {
                "handler": "homekit_controller",
                "context": {"source": "zeroconf", "title_placeholders": {"name": "Lock"}},
            },
            "f-user": {"handler": "demo", "context": {"source": "user"}},
        }
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _reply(self, obj, code=200):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                outer.calls.append(("GET", self.path, None))
                if self.path == "/api/config/config_entries/flow":
                    return self._reply([{"flow_id": k, "step_id": "confirm", **v} for k, v in outer.flows.items()])
                self._reply({}, 404)

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n) or b"{}")
                outer.calls.append(("POST", self.path, body))
                fid = self.path.rsplit("/", 1)[-1]
                if fid == "f-cast":
                    return self._reply({"type": "create_entry", "title": "Living Room TV", "handler": "cast"})
                if fid == "f-hk":
                    if body.get("pairing_code"):
                        return self._reply({"type": "create_entry", "title": "Lock", "handler": "homekit_controller"})
                    return self._reply(
                        {
                            "type": "form",
                            "handler": "homekit_controller",
                            "data_schema": [{"name": "pairing_code", "required": True, "type": "string"}],
                            "errors": {},
                        }
                    )
                self._reply({"type": "abort", "reason": "unknown"})

        self.http = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.http.server_port}"
        self.ws_port = None
        self._ws_ready = threading.Event()
        threading.Thread(target=self._run_ws, daemon=True).start()
        self._ws_ready.wait(5)

    def _run_ws(self):
        import websockets

        async def handler(ws):
            await ws.send(json.dumps({"type": "auth_required"}))
            auth = json.loads(await ws.recv())
            if auth.get("access_token") != "tok":
                await ws.send(json.dumps({"type": "auth_invalid"}))
                return
            await ws.send(json.dumps({"type": "auth_ok"}))
            cmd = json.loads(await ws.recv())
            self.ws_commands.append(cmd)
            await ws.send(json.dumps({"id": cmd["id"], "type": "result", "success": True, "result": None}))

        async def main():
            async with websockets.serve(handler, "127.0.0.1", 0) as server:
                self.ws_port = server.sockets[0].getsockname()[1]
                self._ws_ready.set()
                await asyncio.Future()

        asyncio.run(main())


@pytest.fixture
def ha(plane, monkeypatch):
    fake = _FakeHA()
    monkeypatch.setenv("HOME_ASSISTANT_URL", fake.url)
    monkeypatch.setenv("HOME_ASSISTANT_TOKEN", "tok")
    monkeypatch.setattr(ha_client, "_ws_url", lambda base: f"ws://127.0.0.1:{fake.ws_port}/api/websocket")
    yield fake
    fake.http.shutdown()


def test_ha_discovered_integrations_become_candidates_but_user_flows_do_not(plane, ha):
    from core.device_onboarding.sources import scan_ha_flows

    assert asyncio.run(scan_ha_flows()) == 2
    names = sorted(c["name"] for c in plane.overview()["candidates"])
    assert names == ["Living Room TV", "Lock"]


def test_a_chromecast_is_joined_through_the_matching_ha_flow(plane, ha):
    from core.lan_discovery import LanDiscovery

    LanDiscovery().ingest_service(
        "_googlecast._tcp.local.", "Living Room TV._googlecast._tcp.local.", "192.168.1.50", 8009, {}
    )
    [cand] = plane.overview()["candidates"]
    out = asyncio.run(plane.join(cand["candidate_id"]))
    assert out["outcome"]["kind"] == "joined", out
    assert ("POST", "/api/config/config_entries/flow/f-cast", {}) in ha.calls


def test_a_homekit_lock_asks_for_its_pairing_code_then_joins(plane, ha):
    from core.device_onboarding.sources import scan_ha_flows

    asyncio.run(scan_ha_flows())
    lock = next(c for c in plane.overview()["candidates"] if c["name"] == "Lock")
    out = asyncio.run(plane.join(lock["candidate_id"]))
    assert out["outcome"]["human_step"] == "physical_code"
    assert out["outcome"]["needs"]["inputs"][0]["name"] == "pairing_code"

    out = asyncio.run(plane.join(lock["candidate_id"], {"pairing_code": "123-45-678"}))
    assert out["outcome"]["kind"] == "joined"
    assert ("POST", "/api/config/config_entries/flow/f-hk", {"pairing_code": "123-45-678"}) in ha.calls


def test_matter_code_is_sent_to_home_assistant_over_websocket(plane, ha):
    from core.lan_discovery import LanDiscovery

    LanDiscovery().ingest_service("_matterc._udp.local.", "PLUG-01._matterc._udp.local.", "192.168.1.60", 5540, {})
    [cand] = plane.overview()["candidates"]
    out = asyncio.run(plane.join(cand["candidate_id"], {"code": "MT:Y.K9042C00KA0648G00"}))
    assert out["outcome"]["kind"] == "joined", out
    assert ha.ws_commands == [{"id": 1, "type": "matter/commission", "code": "MT:Y.K9042C00KA0648G00"}]


# ── 总览:按角色分组 ─────────────────────────────────────────────────


def test_overview_groups_by_role(plane):
    from core.ha_bridge import HABridge

    _udm().register_device_from_dict("phone-1", {"device_type": "Android_Agent", "transport": "websocket"})
    _udm().register_device_from_dict("watch-1", {"device_type": "wearos", "transport": "websocket"})
    HABridge(url="http://ha.local:8123", token="t")._mirror_entity(
        {"entity_id": "switch.fan", "state": "on", "attributes": {"friendly_name": "风扇"}}
    )
    g = plane.overview()["groups"]
    assert [v["device_id"] for v in g["subjects"]] == ["phone-1"]
    assert [v["device_id"] for v in g["members"]] == ["watch-1"]
    [fan] = g["bridged"]
    assert fan["online"] is True and fan["channels"] == {"bridge": True}
    assert fan["driver"] == {"kind": "node", "node": "Node_27_SmartHome"}
    assert fan["can_initiate"] is False and g["subjects"][0]["can_initiate"] is True


# ── SSDP 解析 ────────────────────────────────────────────────────────


def test_ssdp_response_parsing():
    from core.device_onboarding.sources import parse_ssdp_response, ssdp_observation

    raw = (
        b"HTTP/1.1 200 OK\r\nCACHE-CONTROL: max-age=1800\r\nLOCATION: http://192.168.1.9:49152/desc.xml\r\n"
        b"SERVER: Linux UPnP/1.0 Sony-BRAVIA/1.0\r\nST: urn:schemas-upnp-org:device:MediaRenderer:1\r\n"
        b"USN: uuid:ABCD-1234::urn:schemas-upnp-org:device:MediaRenderer:1\r\n\r\n"
    )
    r = parse_ssdp_response(raw, "192.168.1.9")
    assert r["uuid"] == "abcd-1234" and r["location"].endswith("desc.xml")
    obs = ssdp_observation({**r, "types": r["st"]})
    assert obs.kind_hint == "tv" and obs.addresses == ["192.168.1.9"]
    assert parse_ssdp_response(b"NOTIFY * HTTP/1.1\r\n\r\n", "x") is None
