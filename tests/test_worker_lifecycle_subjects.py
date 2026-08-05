"""worker 生命周期三条信号必须真的到得了 MasterBrain。

这不是一条"接线"契约,是一条**投递**契约 —— 发布器存在、被调用、返回
``{"success": True}``,消息仍然可以落在没人听的主题上。本文件两端一起跑:
用 MasterBrain 自己的 ``subscribe_worker_*`` 订阅,用 worker 侧的
``publish_legacy_*`` 发布,断言回调真的被调到、且载荷真的能被 MasterBrain
解析成 contracts.py 的模型。

修之前的实况
------------
``galaxy.device.*`` 与 ``galaxy.workers.*`` 是**两个平面**:前者载 AIP v3 消息
类、对端是各种设备;后者载 contracts.py 的 Worker* 模型、对端是 MasterBrain。
三条 legacy 发布器却先把消息转成 AIP v3、再调设备平面的 ``publish_device_*``,
于是全都发去了 ``galaxy.device.*``。

而它们当时看起来是好的 —— 因为转换**恰好抛异常**,异常把它们打进 except 分支,
原样发去了 ``galaxy.workers.*``。对的结果,错的理由。三条里唯一转换会成功的
shutdown,就是真的断的那条:MasterBrain 永远收不到下线通知,只能等心跳超时把
worker 判死,再把它手上的在途任务标成 ``worker_lost`` —— 干净下线与崩溃从此
不可区分。

心跳还多错一层:``core/nats_heartbeat.py`` 调的是设备平面的
``publish_heartbeat``,连 except 兜底都没有,一条也到不了。
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from core.nats_bus import NATSBus, WorkerLifecycleSubjects
from core.schemas.contracts import (
    TimestampModel,
    WorkerCapabilityModel,
    WorkerHeartbeatModel,
    WorkerRegistrationModel,
    WorkerShutdownModel,
)

_TS = TimestampModel(seconds=1_700_000_000)


@pytest.fixture()
def bus() -> NATSBus:
    """一条进程内总线 —— 真的 NATSBus,不是桩。"""
    b = NATSBus()
    b.enable_local_fallback("测试:进程内总线")
    return b


def _heartbeat() -> WorkerHeartbeatModel:
    return WorkerHeartbeatModel(worker_id="w1", status="idle", timestamp=_TS)


def _registration() -> WorkerRegistrationModel:
    return WorkerRegistrationModel(
        worker_id="w1",
        worker_type="router",
        capabilities=[WorkerCapabilityModel(name="a")],
        timestamp=_TS,
    )


def _shutdown() -> WorkerShutdownModel:
    return WorkerShutdownModel(worker_id="w1", reason="graceful", timestamp=_TS)


@pytest.mark.asyncio
async def test_all_three_worker_signals_reach_the_brain(bus: NATSBus):
    """注册 / 心跳 / 下线,一条都不能少。"""
    got: Dict[str, List[Any]] = {"register": [], "heartbeat": [], "shutdown": []}
    await bus.subscribe_worker_registrations(lambda d: got["register"].append(d))
    await bus.subscribe_heartbeats(lambda d: got["heartbeat"].append(d))
    await bus.subscribe_worker_shutdowns(lambda d: got["shutdown"].append(d))

    await bus.publish_legacy_worker_registration(_registration())
    await bus.publish_legacy_heartbeat(_heartbeat())
    await bus.publish_legacy_worker_shutdown(_shutdown())
    await asyncio.sleep(0.05)

    missing = [k for k, v in got.items() if not v]
    assert not missing, f"这些信号没到 MasterBrain:{missing}"


@pytest.mark.asyncio
async def test_the_shutdown_signal_specifically(bus: NATSBus):
    """单独钉住 shutdown —— 它是三条里真的断掉过的那条。

    断掉的后果不是"少一条日志":MasterBrain 收不到下线通知就只能等心跳超时,
    把 worker 判死并把在途任务标成 worker_lost。干净下线与崩溃变得不可区分。
    """
    seen: List[Any] = []
    await bus.subscribe_worker_shutdowns(lambda d: seen.append(d))
    await bus.publish_legacy_worker_shutdown(_shutdown())
    await asyncio.sleep(0.05)

    assert seen, "worker 下线通知没到 MasterBrain"
    assert WorkerShutdownModel.model_validate(seen[0]).reason == "graceful"


@pytest.mark.asyncio
async def test_the_payload_is_what_the_brain_can_parse(bus: NATSBus):
    """到得了还不够 —— MasterBrain 拿到手要能 model_validate。

    ``MasterBrain._on_heartbeat`` 是 ``WorkerHeartbeatModel.model_validate(data)``,
    失败只打一行 debug 就吞掉。所以"收到了但解析不了"在生产里同样是静默失效,
    必须一起钉住。
    """
    seen: List[Any] = []
    await bus.subscribe_heartbeats(lambda d: seen.append(d))
    await bus.publish_legacy_heartbeat(_heartbeat())
    await asyncio.sleep(0.05)

    assert seen
    parsed = WorkerHeartbeatModel.model_validate(seen[0])
    assert parsed.worker_id == "w1"
    # timestamp 必须还是 {seconds, nanos} 结构 —— 摊平成 int 就过不了校验。
    assert parsed.timestamp.seconds == _TS.seconds


@pytest.mark.asyncio
async def test_worker_signals_do_not_leak_onto_the_device_plane(bus: NATSBus):
    """worker 平面的消息不该出现在设备平面上。

    反向也钉一下:修复前它们**只**出现在设备平面。两个平面的消费方、载荷模型
    都不同,串台不是"多发一份"而是两边都不对。
    """
    device_plane: List[Any] = []
    await bus._subscribe("galaxy.device.>", lambda d: device_plane.append(d))

    await bus.publish_legacy_worker_registration(_registration())
    await bus.publish_legacy_heartbeat(_heartbeat())
    await bus.publish_legacy_worker_shutdown(_shutdown())
    await asyncio.sleep(0.05)

    assert device_plane == [], f"worker 信号漏到了设备平面:{len(device_plane)} 条"


@pytest.mark.asyncio
async def test_the_subjects_are_the_ones_the_brain_subscribes_to(bus: NATSBus):
    """发布主题必须**就是** WorkerLifecycleSubjects 里那三个常量。

    两端都从同一个常量取,才不会再出现"发一个主题、听另一个主题"。
    """
    subjects: List[str] = []
    original = bus._publish

    async def _spy(subject: str, data: dict) -> dict:
        subjects.append(subject)
        return await original(subject, data)

    bus._publish = _spy  # type: ignore[method-assign]
    await bus.publish_legacy_worker_registration(_registration())
    await bus.publish_legacy_heartbeat(_heartbeat())
    await bus.publish_legacy_worker_shutdown(_shutdown())

    assert subjects == [
        WorkerLifecycleSubjects.REGISTER,
        WorkerLifecycleSubjects.HEARTBEAT,
        WorkerLifecycleSubjects.SHUTDOWN,
    ]


@pytest.mark.asyncio
async def test_the_node_heartbeat_sender_uses_the_worker_plane():
    """worker 侧的心跳循环必须调 worker 平面那个发布器。

    ``core/nats_heartbeat.py`` 此前调的是设备平面的 ``publish_heartbeat``,
    连 except 兜底都没有 —— 一条也到不了 MasterBrain。这条直接钉发送方。
    """
    import core.nats_heartbeat as nh

    src = (nh.__file__ or "").replace(".pyc", ".py")
    with open(src, encoding="utf-8") as fh:
        text = fh.read()

    assert "nats_bus.publish_legacy_heartbeat(hb)" in text
    assert "await nats_bus.publish_heartbeat(hb)" not in text, "又调回设备平面的发布器了"


def test_the_aip_v3_round_trip_is_still_lossy_for_worker_models():
    """记录一条**尚未修**的事实,免得它以后被当成"顺手能用"。

    ``from_aip_to_legacy`` 还原出来的 timestamp 是 int,而 ``WorkerHeartbeatModel``
    要的是 ``{seconds, nanos}``。也就是说 worker 平面**不能**改走 AIP v3 —— 真发
    了 AIP v3 上去,MasterBrain 的 model_validate 会失败,而它只打一行 debug 就吞掉。

    这条断言的是现状而非期望。哪天适配器把往返修好了,这里会红 —— 那时该做的是
    删掉本用例并重新评估两个平面要不要合并,而不是把断言反过来写。
    """
    import time

    from core.aip_v3_nats_adapter import from_aip_to_legacy
    from core.schemas.aip_v3 import HeartbeatMsg

    wire = HeartbeatMsg(device_id="w1", status="idle", timestamp=int(time.time() * 1000))
    legacy = from_aip_to_legacy(wire.model_dump(mode="json", exclude_none=True))

    with pytest.raises(Exception):
        WorkerHeartbeatModel.model_validate(legacy)


# ---------------------------------------------------------------------------
# 任务平面:同型缺陷已查实,修法待定
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_task_plane_publishers_and_subscribers_disagree(bus: NATSBus):
    """记录一条**已查实但尚未修**的同型缺陷,别让它再悄悄躺着。

    ``NATSTopics.TASK_DISPATCH/TASK_RESULT`` 是单数 ``galaxy.task.*``,而
    ``subscribe_task_dispatches`` / ``subscribe_task_results`` 听的是复数
    ``galaxy.tasks.*``,JetStream 的 ``GALAXY_TASKS`` 流覆盖的也是复数 ——
    差一个 token,NATS 逐 token 精确匹配,两者永不相通。

    后果:``publish_task_result`` 有四个生产调用方(worker_runtime /
    node_invocation / swarm_coordinator / task_graph),它们发出去的结果一条也
    回不到 MasterBrain;主脑只能等心跳超时把 worker 判死,再把在途任务标成
    ``worker_lost``。单数那些主题还落在所有 JetStream 流之外,连持久化都没有。

    **为什么先记不修**:仓库里 ``tests/conformance/test_nats_trace.py`` 的 K 节
    有一条明确契约说单数才是新规范、复数是遗留;而实际运转面(流、两个订阅器、
    command_router / scheduler / gateway_nats_adapter)全在复数上。往哪边收敛
    是带部署动作的架构决定(改 JetStream 流的 subjects),不该由改这行代码的人
    顺手定。

    本用例断言的是**现状**。方向定下、修完之后,它会红 —— 那时该做的是把它换成
    正向的投递断言(参照上面 worker 平面那几条),而不是删掉了事。
    """
    from core.schemas.aip_v3 import TaskResultMsg

    got: List[Any] = []
    await bus.subscribe_task_results(lambda d: got.append(d))
    await bus.publish_task_result(TaskResultMsg(device_id="w1", task_id="t1", status="ok"))
    await asyncio.sleep(0.05)

    assert got == [], "任务平面已经接通了 —— 请把本用例改写成正向的投递断言"
