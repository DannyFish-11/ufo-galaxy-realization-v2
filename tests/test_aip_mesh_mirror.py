"""AIP v3 → NATS 网格面镜像的契约。

背景:这套设备协议定义了 28 个消息类,``core/nats_bus.py`` 为每一个都写了
``publish_*``,但真正被生产代码调用过的只有一小半 —— 协议表面铺满了,发送方
只接了其中几条路。本文件锁住三件事:

1. **表必须是全的** —— 每个有模型类的 AIP v3 消息类型都得有网格发布器,
   而且表里指的方法在 ``NATSBus`` 上真的存在;
2. **镜像不能影响 handler 本身** —— NATS 没连、不在事件循环里、类型没登记,
   都只是"这次没镜像出去",绝不能抛;
3. **该发的真的发出去了** —— 每条已接线的路径,拿真 handler 跑一遍,断言对应
   的 publish_* 被调到。
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Tuple
from unittest.mock import patch

import pytest

from core.aip_mesh_mirror import (
    mesh_exempt_message_types,
    mirror_to_mesh,
    publisher_for,
    unpublishable_message_types,
)
from core.schemas import aip_v3

# ---------------------------------------------------------------------------
# 桩:一个"连上了"的总线,把每次发布记下来
# ---------------------------------------------------------------------------


class _RecordingBus:
    """记录被调到哪个 publish_*、发的是哪条消息。"""

    def __init__(self, connected: bool = True) -> None:
        self._connected = connected
        self.calls: List[Tuple[str, Any]] = []

    def is_connected(self) -> bool:
        return self._connected

    def __getattr__(self, name: str):
        if not name.startswith("publish_"):
            raise AttributeError(name)

        async def _record(msg: Any) -> dict:
            self.calls.append((name, msg))
            return {"success": True}

        return _record


def _install(bus: _RecordingBus):
    """把 ``get_nats_bus`` 换成返回 *bus* —— 打在 core.nats_bus 上,因为
    ``mirror_to_mesh`` 是惰性从那里 import 的。"""
    return patch("core.nats_bus.get_nats_bus", return_value=bus)


async def _settle() -> None:
    """让 fire-and-forget 的后台发布任务跑完。"""
    for _ in range(3):
        await asyncio.sleep(0)


# ---------------------------------------------------------------------------
# 1. 表的完整性
# ---------------------------------------------------------------------------


def test_every_aip_message_class_has_a_mesh_publisher():
    """协议接没接全,就是这一条。

    新增一个 AIP v3 消息类却忘了给它网格发布器,这里当场红 —— 那种消息可以
    在别的链路上被构造出来,却永远上不了网格,别的设备无从知道它发生过。
    """
    missing = unpublishable_message_types()
    assert missing == (), f"这些 AIP v3 消息类型没有网格发布器:{list(missing)}"


def test_every_exemption_states_why():
    """豁免必须写理由,而且理由不能是敷衍的一句。

    这道门的价值全在"新增一个消息类就必须回答它上不上网格"。如果豁免可以只写个
    名字,那它就退化成一个绕过门的名单 —— 下一个人往里加一行,谁也不会去想为什么。
    """
    for name, reason in mesh_exempt_message_types().items():
        assert reason.strip(), f"{name} 的豁免没有写理由"
        assert len(reason.strip()) >= 20, f"{name} 的豁免理由太敷衍:{reason!r}"


def test_a_type_is_never_both_published_and_exempt():
    """同一种消息不能既在发布表里、又在豁免表里 —— 那是两个互相矛盾的答案。"""
    from core.aip_mesh_mirror import _MESH_EXEMPT, _PUBLISHER_BY_TYPE

    both = sorted(set(_PUBLISHER_BY_TYPE) & set(_MESH_EXEMPT))
    assert not both, f"这些类型同时被登记为「要发布」和「不该上网格」:{both}"


def test_exemptions_are_real_message_types():
    """豁免表里写的必须是真存在的类型。

    写错一个字不会报错,只会让那条豁免永远不生效,而真正的那种消息悄悄变回"缺发布器"
    —— 或者更糟:它在协议里已经被删了,豁免却还留着,把一条早就不存在的债记在账上。
    """
    from galaxy_gateway.protocol.aip_v3 import MessageType

    known = {m.value for m in MessageType}
    unknown = sorted(set(mesh_exempt_message_types()) - known)
    assert not unknown, f"豁免表里这些类型在协议里不存在:{unknown}"


def test_voice_call_signalling_is_the_exempt_set():
    """豁免目前**只有**实时语音通话那六条。

    钉死这个集合,是为了让下一次往里加东西成为一个必须解释的动作,而不是顺手一行。
    """
    assert set(mesh_exempt_message_types()) == {
        "voice_call_start",
        "voice_call_accepted",
        "voice_call_end",
        "voice_ice",
        "voice_event",
        "voice_interrupt",
    }


def test_the_table_points_at_methods_that_actually_exist():
    """表里写的方法名必须在 NATSBus 上真的有。

    只校验"表是全的"还不够:表指向一个不存在的方法,运行时同样发不出去,而且
    是静默失败(mirror_to_mesh 吞异常)。
    """
    from core.aip_mesh_mirror import _PUBLISHER_BY_TYPE
    from core.nats_bus import NATSBus

    missing = [m for m in sorted(set(_PUBLISHER_BY_TYPE.values())) if not hasattr(NATSBus, m)]
    assert not missing, f"镜像表指向 NATSBus 上不存在的方法:{missing}"


def test_unregistered_type_resolves_to_nothing():
    """``MsgType`` 里有几个成员是别的链路的线上词汇,没有 AIP v3 模型类。

    它们不该被硬塞一个发布器 —— 查表返回空串,镜像跳过,这是正确行为而不是遗漏。
    """
    assert publisher_for(aip_v3.MsgType.BROADCAST) == ""
    assert publisher_for("完全不存在的类型") == ""


# ---------------------------------------------------------------------------
# 2. 镜像绝不能影响 handler 本身
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disconnected_bus_is_not_an_error():
    """单机跑的时候 NATS 本来就没连 —— 这是常态,不是故障。"""
    bus = _RecordingBus(connected=False)
    with _install(bus):
        assert mirror_to_mesh(aip_v3.HeartbeatAckMsg(device_id="d1")) is False
    assert bus.calls == []


def test_outside_an_event_loop_is_not_an_error():
    """同步上下文里调用:镜像是可选的,不值得为它起一个事件循环。"""
    bus = _RecordingBus()
    with _install(bus):
        assert mirror_to_mesh(aip_v3.HeartbeatAckMsg(device_id="d1")) is False
    assert bus.calls == []


@pytest.mark.asyncio
async def test_a_throwing_bus_never_propagates():
    """总线本身炸了,也只能是"这次没镜像出去"。"""

    class _Exploding:
        def is_connected(self) -> bool:
            raise RuntimeError("总线炸了")

    with patch("core.nats_bus.get_nats_bus", return_value=_Exploding()):
        assert mirror_to_mesh(aip_v3.HeartbeatAckMsg(device_id="d1")) is False


@pytest.mark.asyncio
async def test_a_registered_type_really_goes_out():
    bus = _RecordingBus()
    with _install(bus):
        assert mirror_to_mesh(aip_v3.HeartbeatAckMsg(device_id="d1")) is True
        await _settle()
    assert [name for name, _ in bus.calls] == ["publish_heartbeat_ack"]


# ---------------------------------------------------------------------------
# 3. 每条已接线的路径,拿真 handler 跑一遍
# ---------------------------------------------------------------------------


class _StubDevice:
    def __init__(self) -> None:
        self.current_task_id = None

    def mark_heartbeat(self) -> None:
        pass


class _StubBridge:
    """够 handler 跑起来的最小 AndroidBridge 替身。"""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._devices: Dict[str, Any] = {"d1": _StubDevice()}
        self._pending_responses: Dict[str, Any] = {}

    def _patch_heartbeat_to_udm(self, device_id: Any) -> None:
        pass

    def _sync_device_router_session(self, device_id: Any, connected: bool = True) -> None:
        pass


@pytest.mark.asyncio
async def test_heartbeat_handler_mirrors_the_ack():
    from galaxy_gateway.android.handlers.heartbeat import handle_heartbeat

    bus = _RecordingBus()
    with _install(bus):
        await handle_heartbeat(_StubBridge(), None, {"device_id": "d1", "trace_id": "t1"})
        await _settle()

    assert [name for name, _ in bus.calls] == ["publish_heartbeat_ack"]
    _, msg = bus.calls[0]
    assert msg.device_id == "d1" and msg.trace_id == "t1"
    assert msg.server_timestamp > 0, "应答必须带服务端时间戳,否则算不出单程延迟"


@pytest.mark.asyncio
async def test_takeover_response_handler_mirrors_the_decision():
    """请求半边早就上网格了,应答半边不上去就判不出控制权在谁手里。"""
    from galaxy_gateway.android.handlers.takeover_response import handle_takeover_response

    bus = _RecordingBus()
    with _install(bus):
        await handle_takeover_response(
            _StubBridge(),
            None,
            {"device_id": "d1", "takeover_id": "tk1", "accepted": False, "reason": "busy"},
        )
        await _settle()

    names = [n for n, _ in bus.calls]
    assert "publish_takeover_response" in names
    msg = next(m for n, m in bus.calls if n == "publish_takeover_response")
    assert msg.accepted is False
    assert msg.rejection_reason == "busy"
    assert msg.request_correlation_id == "tk1"


@pytest.mark.asyncio
async def test_task_cancel_mirrors_both_halves():
    """取消是两条消息:喊停,和到底停没停。"""
    from galaxy_gateway.android.handlers import task_lifecycle

    bus = _RecordingBus()
    with _install(bus), patch.object(task_lifecycle, "_apply_canonical_task_cancellation", return_value=(True, "")):
        await task_lifecycle.handle_task_cancel(
            _StubBridge(), None, {"device_id": "d1", "task_id": "task-9", "reason": "user_abort"}
        )
        await _settle()

    names = [n for n, _ in bus.calls]
    assert "publish_task_cancel" in names and "publish_cancel_result" in names
    result = next(m for n, m in bus.calls if n == "publish_cancel_result")
    assert result.cancelled is True and result.cleanup_status == "clean"


@pytest.mark.asyncio
async def test_a_task_that_already_finished_is_not_reported_as_cancelled():
    """ "来不及了"跟"停住了"是两回事 —— cleanup_status 必须分得出来。"""
    from galaxy_gateway.android.handlers import task_lifecycle

    bus = _RecordingBus()
    with (
        _install(bus),
        patch.object(
            task_lifecycle, "_apply_canonical_task_cancellation", return_value=(False, "task_already_completed")
        ),
    ):
        await task_lifecycle.handle_task_cancel(_StubBridge(), None, {"device_id": "d1", "task_id": "task-9"})
        await _settle()

    result = next(m for n, m in bus.calls if n == "publish_cancel_result")
    assert result.cancelled is False
    assert result.cleanup_status == "partial"


@pytest.mark.asyncio
async def test_peer_announce_and_topology_reach_the_mesh():
    """设备加入与拓扑答复只回给发问方的话,别的节点算不出完整拓扑。"""
    from galaxy_gateway.android.handlers.mesh_topology import handle_mesh_topology
    from galaxy_gateway.android.handlers.peer_exchange import handle_peer_announce

    bus = _RecordingBus()
    with _install(bus):
        await handle_peer_announce(_StubBridge(), None, {"device_id": "d1", "payload": {"capabilities": ["adb"]}})
        await handle_mesh_topology(_StubBridge(), None, {"device_id": "d1"})
        await _settle()

    names = [n for n, _ in bus.calls]
    assert "publish_peer_announce" in names
    assert "publish_mesh_topology" in names
    announce = next(m for n, m in bus.calls if n == "publish_peer_announce")
    assert announce.peer_device_id == "d1"
    assert announce.peer_capabilities == ["adb"]
    topo = next(m for n, m in bus.calls if n == "publish_mesh_topology")
    assert topo.request_type == "update", "这是答复,不是发问"


@pytest.mark.asyncio
async def test_reconciliation_and_delegated_signals_reach_the_mesh():
    from galaxy_gateway.android.handlers.delegated_signal import handle_delegated_execution_signal
    from galaxy_gateway.android.handlers.reconciliation_signal import handle_reconciliation_signal

    bus = _RecordingBus()
    with _install(bus):
        await handle_delegated_execution_signal(
            _StubBridge(), None, {"device_id": "d1", "signal_kind": "PROGRESS", "progress_pct": 42}
        )
        await handle_reconciliation_signal(
            _StubBridge(),
            None,
            {"device_id": "d1", "signal_kind": "PARTICIPANT_STATE", "source_runtime_truth": {"phase": "running"}},
        )
        await _settle()

    names = [n for n, _ in bus.calls]
    assert "publish_delegated_signal" in names
    assert "publish_reconciliation" in names
    sig = next(m for n, m in bus.calls if n == "publish_delegated_signal")
    assert sig.progress_pct == 42
    rec = next(m for n, m in bus.calls if n == "publish_reconciliation")
    assert rec.source_runtime_truth == {"phase": "running"}


@pytest.mark.asyncio
async def test_generic_compat_ack_reaches_the_mesh():
    """兼容路径回的是裸 ACK,正因为没有状态语义,网格里更需要看见它。"""
    from galaxy_gateway.android.handlers.generic import handle_generic_forward

    bus = _RecordingBus()
    with _install(bus):
        await handle_generic_forward(_StubBridge(), None, {"type": "app_start", "device_id": "d1", "message_id": "m1"})
        await _settle()

    assert [n for n, _ in bus.calls] == ["publish_ack"]
    ack = bus.calls[0][1]
    assert ack.ack_for_type == "app_start"
    assert ack.ack_for_correlation_id == "m1"


@pytest.mark.asyncio
async def test_rejected_generic_types_do_not_reach_the_mesh():
    """被兼容门挡下来的消息没有被受理,网格里不该出现它的 ACK。"""
    from galaxy_gateway.android.handlers.generic import handle_generic_forward

    bus = _RecordingBus()
    with _install(bus):
        reply = await handle_generic_forward(_StubBridge(), None, {"type": "device_state_snapshot", "device_id": "d1"})
        await _settle()

    assert reply["status"] == "rejected"
    assert bus.calls == [], "被拒的消息不该镜像出 ACK"


@pytest.mark.asyncio
async def test_no_local_device_asks_the_mesh():
    """本机认识的设备不等于网格里全部 —— 选不出来就该往网格问一句。"""
    from core.capability_routing_gate import filter_by_required_capabilities

    class _Dev:
        device_id = "d1"
        capabilities = ["screen"]

    bus = _RecordingBus()
    with _install(bus):
        accepted = filter_by_required_capabilities([_Dev()], ["thermal_camera"], allow_insufficient_data=False)
        await _settle()

    assert accepted == []
    assert [n for n, _ in bus.calls] == ["publish_capability_query"]
    assert bus.calls[0][1].query_filter == "thermal_camera"


@pytest.mark.asyncio
async def test_a_satisfiable_requirement_does_not_ask_the_mesh():
    """选得出设备就别广播 —— 否则每次路由都往网格灌一条问询。"""
    from core.capability_routing_gate import filter_by_required_capabilities

    class _Dev:
        device_id = "d1"
        capabilities = ["screen"]

    bus = _RecordingBus()
    with _install(bus):
        accepted = filter_by_required_capabilities([_Dev()], ["screen"])
        await _settle()

    assert len(accepted) == 1
    assert bus.calls == []


@pytest.mark.asyncio
async def test_the_in_process_bus_counts_as_reachable():
    """本地降级总线也得发。

    ``NATSBus.is_connected()`` 判的是**网络**连接(``self._nc is not None``),
    进程内降级总线下恒为 False。第一版只看 is_connected(),结果单机运行时镜像
    一条都不发 —— 而本地总线的全部意义正是"单机语义完整保留:同进程内订阅者
    照常收到消息"。

    这个洞桩总线盖不住(桩的 is_connected() 返回 True),是拿真 NATSBus 跑
    一遍才现形的。
    """

    class _LocalOnlyBus(_RecordingBus):
        def is_connected(self) -> bool:
            return False  # 没有网络连接

        def is_local_mode(self) -> bool:
            return True  # 但进程内总线是通的

    bus = _LocalOnlyBus()
    with _install(bus):
        assert mirror_to_mesh(aip_v3.HeartbeatAckMsg(device_id="d1")) is True
        await _settle()
    assert [n for n, _ in bus.calls] == ["publish_heartbeat_ack"]


@pytest.mark.asyncio
async def test_every_wired_type_lands_on_a_real_bus():
    """端到端:真 NATSBus(进程内模式)+ 真 handler,断言消息真的到了订阅者手上。

    上面那些用例打的是桩;这一条不打桩 —— 它同时证明发布器名对得上、subject
    发得出去、消息体过得了 pydantic 序列化。
    """
    from core.nats_bus import get_nats_bus
    from galaxy_gateway.android.handlers import task_lifecycle
    from galaxy_gateway.android.handlers.generic import handle_generic_forward
    from galaxy_gateway.android.handlers.heartbeat import handle_heartbeat
    from galaxy_gateway.android.handlers.mesh_topology import handle_mesh_topology
    from galaxy_gateway.android.handlers.peer_exchange import handle_peer_announce, handle_peer_exchange
    from galaxy_gateway.android.handlers.takeover_response import handle_takeover_response

    bus = get_nats_bus()
    bus.enable_local_fallback("测试:进程内总线")
    received: List[dict] = []

    async def _cb(data: Any) -> None:
        # 本地模式的回调收到的就是 data 本身(dict),不是 NATS Msg 对象。
        if isinstance(data, dict):
            received.append(data)

    await bus._subscribe("galaxy.>", _cb)

    b = _StubBridge()
    await handle_heartbeat(b, None, {"device_id": "d1"})
    await handle_peer_announce(b, None, {"device_id": "d1", "payload": {}})
    await handle_peer_exchange(b, None, {"device_id": "d1"})
    await handle_mesh_topology(b, None, {"device_id": "d1"})
    await handle_takeover_response(b, None, {"device_id": "d1", "takeover_id": "tk1", "accepted": True})
    await handle_generic_forward(b, None, {"type": "app_start", "device_id": "d1", "message_id": "m1"})
    with patch.object(task_lifecycle, "_apply_canonical_task_cancellation", return_value=(True, "")):
        await task_lifecycle.handle_task_cancel(b, None, {"device_id": "d1", "task_id": "t9"})
    await asyncio.sleep(0.05)

    got = {d.get("type") for d in received}
    expected = {
        "heartbeat_ack",
        "peer_announce",
        "peer_exchange",
        "mesh_topology",
        "takeover_response",
        "ack",
        "task_cancel",
        "cancel_result",
    }
    assert expected <= got, f"这些没到总线上:{sorted(expected - got)}"
