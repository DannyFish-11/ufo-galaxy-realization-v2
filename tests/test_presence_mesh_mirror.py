"""tests/test_presence_mesh_mirror.py
=====================================

锁定「在场相位镜像到网格」这条通道(``core/lumiv_websocket_bridge.py`` 的
``_mirror_presence_to_mesh``)。

它补的是什么洞
--------------
``GalaxyPresenceBridge._broadcast_state`` 原来只推两条通道 —— IPC 到 Electron、
WS 到面板 —— **两条都是本机的**。网格里其它节点看不到这台机器的在场相位,
``galaxy.presence.*`` 这个命名空间在 desktop 侧一条都没发过。

为什么要按相位去重(本文件的主要断言)
--------------------------------------
这条广播在阈限期由 200ms 的 continuum tick 驱动 —— **每秒 5 次**。若每次广播都
往网格发,等于每个节点常态 5 Hz 灌流。网格消费方要的不是连续流,是"这个节点翻档了"。
本机那两条通道仍然拿到全部连续量(面板要平滑动画)—— 同一份数据,两种消费节奏。

所以这里钉三件事:
1. 同相位重复广播 → 网格只收一条;真翻档 → 每档一条。
2. 镜像**绝不影响**本机那两条通道 —— 总线不可用、发布抛异常,IPC/WS 照发不误。
3. 发出去的 subject 与 schema 就是 ``galaxy.presence.state`` / ``UnifiedPresenceEvent``。
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from core.lumiv_websocket_bridge import GalaxyPresenceBridge


@pytest.fixture(autouse=True)
def _restore_bridge_singleton():
    """本文件往单例上挂桩,跑完必须清掉。

    理由同 ``tests/test_presence_bridge_functions.py`` 里的同名 fixture:单例会停在
    最后一条用例留下的实例上,它的 ``_try_ipc_http`` / ``_ws_broadcast`` 已经被换成
    写进**局部 list** 的 lambda,下一个文件的广播就全掉进没人看的列表里。
    """
    GalaxyPresenceBridge._instance = None
    try:
        yield
    finally:
        GalaxyPresenceBridge._instance = None


class _FakeBus:
    """记录 publish_presence_event 调用的假总线。"""

    def __init__(self, usable: bool = True, raises: bool = False) -> None:
        self._usable = usable
        self._raises = raises
        self.calls: List[Dict[str, Any]] = []

    def is_usable(self) -> bool:
        return self._usable

    async def publish_presence_event(self, topic_suffix: str, data: dict, **kwargs: Any) -> dict:
        if self._raises:
            raise RuntimeError("总线炸了")
        self.calls.append({"topic_suffix": topic_suffix, "data": data, "kwargs": kwargs})
        return {"success": True}


def _bridge(monkeypatch, bus: Any) -> tuple:
    """新建一个干净 bridge,把两条本机通道换成可观测的 list,并注入假总线。

    返回 ``(bridge, ipc_msgs, ws_msgs)``。
    """
    GalaxyPresenceBridge._instance = None
    b = GalaxyPresenceBridge.get_instance()
    b._last_mirrored_phase = ""

    ipc_msgs: List[Dict[str, Any]] = []
    ws_msgs: List[Dict[str, Any]] = []

    async def _fake_ipc(msg):
        ipc_msgs.append(msg)
        return True

    async def _fake_ws(msg):
        ws_msgs.append(msg)

    b._try_ipc_http = _fake_ipc
    b._ws_broadcast = _fake_ws

    import core.nats_bus as nats_bus_mod

    monkeypatch.setattr(nats_bus_mod, "get_nats_bus", lambda: bus)
    return b, ipc_msgs, ws_msgs


async def _drain() -> None:
    """让镜像的 fire-and-forget task 跑完。"""
    for _ in range(5):
        await asyncio.sleep(0)


# ── 1. 去重:同相位只发一条,翻档才发 ────────────────────────────────────────


@pytest.mark.asyncio
async def test_repeated_same_phase_broadcasts_mirror_once(monkeypatch):
    """阈限期 5 Hz 的重复广播,网格只应看到一条。"""
    bus = _FakeBus()
    b, _ipc, _ws = _bridge(monkeypatch, bus)
    b._current_mode = "liminal"

    for _ in range(10):
        await b._broadcast_state()
    await _drain()

    assert len(bus.calls) == 1, f"同相位 10 次广播应只镜像 1 条,实收 {len(bus.calls)}"
    assert bus.calls[0]["data"]["phase"] == "liminal"


@pytest.mark.asyncio
async def test_each_phase_transition_mirrors_exactly_once(monkeypatch):
    """每翻一档发一条 —— 不多不少,且顺序保真。"""
    bus = _FakeBus()
    b, _ipc, _ws = _bridge(monkeypatch, bus)

    for mode in ("liminal", "liminal", "manifest", "manifest", "static"):
        b._current_mode = mode
        await b._broadcast_state()
    await _drain()

    phases = [c["data"]["phase"] for c in bus.calls]
    assert phases == ["liminal", "manifest", "static"], f"相位序列不符:{phases}"


@pytest.mark.asyncio
async def test_returning_to_a_previous_phase_mirrors_again(monkeypatch):
    """去重是"跟上一次比",不是"这个相位发过就再不发"。

    static → liminal → static 是真实的三次翻档(醒来、说完话睡回去),
    第三条必须发出去,否则网格里这台机器会永远停在 liminal。
    """
    bus = _FakeBus()
    b, _ipc, _ws = _bridge(monkeypatch, bus)

    for mode in ("static", "liminal", "static"):
        b._current_mode = mode
        await b._broadcast_state()
    await _drain()

    assert [c["data"]["phase"] for c in bus.calls] == ["static", "liminal", "static"]


# ── 2. 镜像不能影响本机那两条通道 ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_local_channels_get_every_broadcast_not_deduped(monkeypatch):
    """本机两条通道要的是**连续量**,不参与去重 —— 面板靠它做平滑动画。"""
    bus = _FakeBus()
    b, ipc, ws = _bridge(monkeypatch, bus)
    b._current_mode = "liminal"

    for _ in range(10):
        await b._broadcast_state()
    await _drain()

    assert len(ipc) == 10, f"IPC 应收满 10 条,实收 {len(ipc)}"
    assert len(ws) == 10, f"WS 应收满 10 条,实收 {len(ws)}"
    assert len(bus.calls) == 1, "网格仍然只应收 1 条"


@pytest.mark.asyncio
async def test_unusable_bus_does_not_break_local_channels(monkeypatch):
    """总线不可用(单机、没连 NATS)时,本机两条通道必须照常。"""
    bus = _FakeBus(usable=False)
    b, ipc, ws = _bridge(monkeypatch, bus)
    b._current_mode = "manifest"

    await b._broadcast_state()
    await _drain()

    assert len(ipc) == 1 and len(ws) == 1
    assert bus.calls == []


@pytest.mark.asyncio
async def test_publish_failure_does_not_break_local_channels(monkeypatch):
    """发布抛异常也只能烂在自己肚子里。"""
    bus = _FakeBus(raises=True)
    b, ipc, ws = _bridge(monkeypatch, bus)

    for mode in ("liminal", "manifest"):
        b._current_mode = mode
        await b._broadcast_state()
    await _drain()

    assert len(ipc) == 2 and len(ws) == 2


@pytest.mark.asyncio
async def test_get_nats_bus_import_failure_does_not_break_local_channels(monkeypatch):
    """连 get_nats_bus 本身都炸,广播也不能挂。"""
    GalaxyPresenceBridge._instance = None
    b = GalaxyPresenceBridge.get_instance()
    b._last_mirrored_phase = ""
    ipc: List[Dict[str, Any]] = []
    ws: List[Dict[str, Any]] = []

    async def _fake_ipc(msg):
        ipc.append(msg)
        return True

    async def _fake_ws(msg):
        ws.append(msg)

    b._try_ipc_http = _fake_ipc
    b._ws_broadcast = _fake_ws

    import core.nats_bus as nats_bus_mod

    def _boom():
        raise RuntimeError("总线不存在")

    monkeypatch.setattr(nats_bus_mod, "get_nats_bus", _boom)

    await b._broadcast_state()
    assert len(ipc) == 1 and len(ws) == 1


# ── 3. subject 与载荷形状 ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mirrors_to_presence_state_subject_with_expected_payload(monkeypatch):
    """topic_suffix 固定 ``state`` → ``galaxy.presence.state``。

    这条钉死的是**订阅方看到的名字**。改 suffix 等于把消费方全部断掉,
    必须让这条测试先红。
    """
    bus = _FakeBus()
    b, _ipc, _ws = _bridge(monkeypatch, bus)
    b._current_mode = "manifest"
    b._speaking = True

    await b._broadcast_state()
    await _drain()

    assert len(bus.calls) == 1
    call = bus.calls[0]
    assert call["topic_suffix"] == "state"
    data = call["data"]
    assert data["phase"] == "manifest"
    assert data["speaking"] is True
    assert isinstance(data["source"], str) and data["source"]


@pytest.mark.asyncio
async def test_real_bus_publishes_to_galaxy_presence_state(monkeypatch):
    """走**真的** NATSBus(本地回环模式),验证最终 subject 逐字正确。

    上一条用的是假总线,只能证明我们传了 ``"state"``;这条证明
    ``publish_presence_event("state", ...)`` 真的落在 ``galaxy.presence.state``,
    且带上了 ``UnifiedPresenceEvent`` 的 schema 标记。
    """
    from core.nats_bus import NATSBus

    real = NATSBus()
    # 单机降级形态:没有网络连接,但总线完全可用。这正是 is_usable() 与
    # is_connected() 分家的那个场景 —— 用后者当闸门,这条镜像单机下永远不发。
    real._local_mode = True
    published: List[tuple] = []

    async def _capture(subject, payload):
        published.append((subject, payload))
        return {"success": True}

    real._publish = _capture

    b, _ipc, _ws = _bridge(monkeypatch, real)
    b._current_mode = "liminal"

    await b._broadcast_state()
    await _drain()

    assert len(published) == 1, f"应发出 1 条,实发 {len(published)}"
    subject, payload = published[0]
    assert subject == "galaxy.presence.state"
    assert payload["_nats_schema"] == "UnifiedPresenceEvent"
    assert payload["phase"] == "liminal"
