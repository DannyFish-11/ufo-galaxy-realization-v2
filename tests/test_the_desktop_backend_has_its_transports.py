"""桌面版也装上传输适配器(跨设备整体方案阶段 6)。

一种消息(AIP v3)、多种传输、自动选路 —— 此前传输只在独立运行网关时才装;桌面版(``main.py`` → 主 app
挂载网关)一个适配器都没有,每次 ``get_aip_transport().send`` 都回「没有可用传输」。现在两条启动路径共用
``galaxy_gateway/bootstrap/transports.register_transport_adapters``:同一进程只装一次;「websocket」这条走
规范设备入口上真的连接;端口被占时只发不收、照样起来。真的绑端口、真的走 TCP。
"""

from __future__ import annotations

import ast
import asyncio
import json
import socket
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def ports(monkeypatch):
    p = {"GALAXY_AIP_TCP_PORT": _free_port(), "GALAXY_AIP_UDP_PORT": _free_port(), "GALAXY_MESH_PORT": _free_port()}
    for k, v in p.items():
        monkeypatch.setenv(k, str(v))
    monkeypatch.delenv("MQTT_BROKER", raising=False)
    return p


def _run(coro):
    return asyncio.run(coro)


async def _with_transports(body, message_handler=None):
    from galaxy_gateway.bootstrap.transports import close_transport_adapters, register_transport_adapters

    try:
        status = await register_transport_adapters(message_handler)
        return await body(status)
    finally:
        await close_transport_adapters()


def test_the_adapters_are_registered_once_per_process(ports):
    from core.aip_transport import get_aip_transport
    from galaxy_gateway.bootstrap.transports import register_transport_adapters

    async def body(status):
        again = await register_transport_adapters()
        return status, again, set(get_aip_transport().list_adapters())

    status, again, names = _run(_with_transports(body))
    assert {"websocket", "tcp", "udp", "mesh", "ble", "serial", "dbus", "canbus"} <= names
    assert status["tcp"] == f"listening:{ports['GALAXY_AIP_TCP_PORT']}"
    assert status["mesh"] == f"listening:{ports['GALAXY_MESH_PORT']}"
    assert again == status, "第二次调用不再装一遍、不再绑一次端口"
    assert status["mqtt"].startswith("skipped"), "没配 MQTT_BROKER 就不装 MQTT(否则后台对着 localhost:1883 无休止重连)"


def test_the_websocket_transport_reaches_devices_on_the_canonical_ingress(ports):
    """「websocket」这条传输投递到规范设备入口上真的连接 —— 此前它接的 manager 从来没有连接。"""
    from core.aip_transport import get_aip_transport
    from core.unified.connection_manager import get_unified_connection_manager

    class _Socket:
        def __init__(self):
            self.sent = []

        async def send_json(self, data):
            self.sent.append(data)

    sock = _Socket()

    async def body(status):
        ucm = get_unified_connection_manager()
        await ucm.register_connection("watch-ws-1", sock)
        try:
            out = await get_aip_transport().send(
                {"type": "command", "command": "notify", "_transport": "auto"}, "watch-ws-1"
            )
        finally:
            await ucm.unregister_connection("watch-ws-1")
        return out

    out = _run(_with_transports(body))
    assert out["success"] is True and out["_transport_used"] == "websocket", out
    assert sock.sent and sock.sent[-1]["command"] == "notify"
    assert not any(k.startswith("_") for k in sock.sent[-1]), "选路用的内部标记不出现在发给设备的帧里"


def test_a_tcp_frame_reaches_the_gateways_message_handler(ports):
    """TCP 直连真的在听,收到的 AIP 帧交给网关的消息处理器(桌面版此前根本没有这个监听)。"""
    seen = []

    class _Handler:
        async def handle_message(self, device_id, message):
            seen.append((device_id, getattr(message, "type", None)))
            return None

    async def body(status):
        reader, writer = await asyncio.open_connection("127.0.0.1", ports["GALAXY_AIP_TCP_PORT"])
        frame = json.dumps({"version": "3.0", "type": "heartbeat", "device_id": "pc-tcp-1", "timestamp": 1}).encode()
        writer.write(len(frame).to_bytes(4, "big") + frame)
        await writer.drain()
        for _ in range(50):
            if seen:
                break
            await asyncio.sleep(0.05)
        writer.close()
        return seen

    got = _run(_with_transports(body, _Handler()))
    assert got and got[0][0] == "pc-tcp-1", got


def test_a_busy_port_leaves_that_transport_send_only_and_the_rest_comes_up(ports):
    """同一台机器上另一个 Galaxy 进程已经占着 TCP 端口:这边只发不收,不让启动失败。"""
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", ports["GALAXY_AIP_TCP_PORT"]))  # 占着环回地址也让通配地址绑不上
    blocker.listen(1)
    try:

        async def body(status):
            return status

        status = _run(_with_transports(body))
    finally:
        blocker.close()
    assert status["tcp"] == f"send-only: port {ports['GALAXY_AIP_TCP_PORT']} busy", status
    assert status["mesh"].startswith("listening"), "别的传输照样起来"


def test_announcing_the_tcp_entry_on_the_lan_does_not_hold_up_startup(ports, monkeypatch):
    """zeroconf 注册是阻塞的(实测这里要 10 秒):放在启动里同步做,桌面版启动和事件循环都会被卡住。"""
    import threading
    import time

    from core.adapters.tcp_adapter import TCPAdapter

    announced = threading.Event()

    def slow_register(self, device_id, port=None):
        time.sleep(3)
        announced.set()

    monkeypatch.setattr(TCPAdapter, "register_local_service", slow_register)

    async def body(status):
        return status

    t0 = time.monotonic()
    status = _run(_with_transports(body))
    assert time.monotonic() - t0 < 2.5, "启动等着局域网广播注册完"
    assert status["tcp"].startswith("listening")
    assert announced.wait(10), "广播照样在后台注册上了"


def test_with_a_working_transport_a_vision_request_gets_one_answer_not_two(ports, monkeypatch, tmp_path):
    """视觉结果只靠返回值回去。处理器此前还经 AIPTransport 另推一份 —— 没装传输时那份从没送到过,
    装上之后手机会收到两份 vision_result。走真网关、真规范入口、真传输层,只替掉看图本身。"""
    pytest.importorskip("uvicorn")
    import websockets

    import galaxy_gateway.android.handlers.vision as vision
    from tests.test_a_laptop_joins_by_pairing import gateway as gateway_fixture

    async def quick(**kw):
        return {"description": "一张白图"}

    monkeypatch.setattr(vision, "_process_via_runtime_shell", quick)
    gen = gateway_fixture.__wrapped__(tmp_path, monkeypatch)
    gw = next(gen)
    try:
        from galaxy_gateway.bootstrap.transports import close_transport_adapters, register_transport_adapters

        gw.run(register_transport_adapters())
        import httpx

        owner = {"Authorization": "Bearer owner-secret"}
        card = httpx.get(f"{gw.url}/api/v1/pair/card", headers=owner).json()
        dev = "phone-vision-1"
        token = httpx.post(
            f"{gw.url}/api/v1/pair/claim",
            json={
                "code": card["code"],
                "device_id": dev,
                "name": dev,
                "device_type": "android_phone",
                "trust": "friend",
            },
        ).json()["capability_token"]

        async def phone():
            got = []
            async with websockets.connect(gw.url.replace("http", "ws") + f"/ws/device/{dev}") as ws:
                await ws.send(
                    json.dumps(
                        {"version": "3.0", "type": "device_register", "device_id": dev, "timestamp": 1, "token": token,
                         "device_type": "android_phone", "platform": "android"}
                    )
                )  # fmt: skip
                while json.loads(await asyncio.wait_for(ws.recv(), 20)).get("type") != "device_register_ack":
                    pass
                await ws.send(
                    json.dumps(
                        {"version": "3.0", "type": "vision_request", "device_id": dev, "timestamp": 2, "task_id": "v1",
                         "image_base64": "aGVsbG8=", "mode": "full"}
                    )
                )  # fmt: skip
                end = asyncio.get_running_loop().time() + 3
                while asyncio.get_running_loop().time() < end:
                    try:
                        m = json.loads(await asyncio.wait_for(ws.recv(), 0.5))
                    except asyncio.TimeoutError:
                        continue
                    # 线上的视觉结果是 task_assign(task_type=vision_action)
                    if m.get("task_id") == "v1" and m.get("task_type") == "vision_action":
                        got.append(m)
            return got

        got = asyncio.run(phone())
        gw.run(close_transport_adapters())
    finally:
        next(gen, None)
    assert len(got) == 1, f"收到 {len(got)} 份视觉结果"


@pytest.mark.parametrize("desktop", ["manifest", "liminal", "silent"])
def test_a_device_that_joins_or_reconnects_is_never_told_the_desktops_tri_state(desktop, ports, monkeypatch, tmp_path):
    """电脑的三态不推给设备(设备直接对智能体):电脑忙着也好、静默也好,登记、再连一次,
    设备收到的第一帧是登记确认,之后没有任何相位帧。"""
    pytest.importorskip("uvicorn")
    import httpx
    import websockets

    import core.lumiv_websocket_bridge as presence
    from tests.test_a_laptop_joins_by_pairing import gateway as gateway_fixture

    monkeypatch.setattr(presence, "get_current_phase", lambda: desktop)

    gen = gateway_fixture.__wrapped__(tmp_path, monkeypatch)
    gw = next(gen)
    try:
        from galaxy_gateway.bootstrap.transports import close_transport_adapters, register_transport_adapters

        gw.run(register_transport_adapters())
        owner = {"Authorization": "Bearer owner-secret"}
        card = httpx.get(f"{gw.url}/api/v1/pair/card", headers=owner).json()
        dev = "phone-order-1"
        token = httpx.post(
            f"{gw.url}/api/v1/pair/claim",
            json={
                "code": card["code"],
                "device_id": dev,
                "name": dev,
                "device_type": "android_phone",
                "trust": "friend",
            },
        ).json()["capability_token"]

        async def phone():
            frames = []
            async with websockets.connect(gw.url.replace("http", "ws") + f"/ws/device/{dev}") as ws:
                await ws.send(
                    json.dumps(
                        {"version": "3.0", "type": "device_register", "device_id": dev, "timestamp": 1, "token": token,
                         "device_type": "android_phone", "platform": "android"}
                    )
                )  # fmt: skip
                end = asyncio.get_running_loop().time() + 3
                while asyncio.get_running_loop().time() < end:
                    try:
                        frames.append(json.loads(await asyncio.wait_for(ws.recv(), 0.5)))
                    except asyncio.TimeoutError:
                        continue
            return frames

        frames = asyncio.run(phone())
        again = asyncio.run(phone())  # 断开再连一次(重连)
        gw.run(close_transport_adapters())
    finally:
        next(gen, None)
    for got in (frames, again):
        types = [f.get("type") for f in got]
        assert types and types[0] == "device_register_ack", types
        phase = [f for f in got if f.get("type") == "state_event" or f.get("event_category") == "phase"]
        assert not phase, f"电脑的三态({desktop})不该推给设备:{phase}"


def test_both_startup_paths_use_the_same_registration():
    """独立网关的 lifespan 和桌面版(主 app 挂载网关)都调同一个函数,不再各写一份。"""
    lifecycle = (ROOT / "galaxy_gateway/bootstrap/lifecycle.py").read_text(encoding="utf-8")
    startup = (ROOT / "core/startup.py").read_text(encoding="utf-8")
    ports_map = json.loads((ROOT / "config/upper_layer_ports.json").read_text(encoding="utf-8"))
    assert "register_transport_adapters" in lifecycle
    assert '"gateway.bootstrap.transports.register_transport_adapters"' in startup
    assert ports_map["ports"]["gateway.bootstrap.transports.register_transport_adapters"].endswith(
        "transports:register_transport_adapters"
    )
    tree = ast.parse(lifecycle)
    direct = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "register_adapter"
    ]
    assert not direct, "lifecycle 不再自己逐个注册适配器(那样两条路径又会漂开)"
