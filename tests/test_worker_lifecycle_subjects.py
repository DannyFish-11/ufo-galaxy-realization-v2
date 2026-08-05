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


def test_the_aip_v3_round_trip_survives_for_worker_models():
    """AIP v3 → legacy 往返后,主脑必须还能 model_validate。

    这条以前断言的是**相反**的事(记录"往返有损"这个现状)。根因是形状不匹配:
    AIP v3 的 timestamp 是毫秒整数,而 contracts.py 里 WorkerHeartbeatModel /
    WorkerRegistrationModel 的对应字段是 ``TimestampModel``(``{seconds, nanos}``)。
    整数塞回去 model_validate 就抛,而 ``MasterBrain._on_heartbeat`` 只打一行
    debug 就吞掉 —— worker 在主脑眼里等同于没心跳。

    同一个形状不匹配在**发布侧**也存在,而且是它让三条 legacy 发布器每次转换都
    抛异常、掉进 except 分支 —— 反倒歪打正着发对了主题。所以修往返之前必须先把
    发布侧改成不依赖那个异常(已在前一个提交完成),否则一修往返就会把发布链路
    弄断。两件事的顺序是有依赖的。
    """
    import time

    from core.aip_v3_nats_adapter import from_aip_to_legacy
    from core.schemas.aip_v3 import DeviceRegisterMsg, HeartbeatMsg

    hb_wire = HeartbeatMsg(device_id="w1", status="idle", timestamp=int(time.time() * 1000))
    hb_legacy = from_aip_to_legacy(hb_wire.model_dump(mode="json", exclude_none=True))
    parsed = WorkerHeartbeatModel.model_validate(hb_legacy)
    assert parsed.worker_id == "w1"
    assert parsed.timestamp.seconds > 0
    # 原始毫秒仍然拿得到 —— 想要整数的消费方不受影响。
    assert hb_legacy["timestamp_ms"] == hb_wire.timestamp

    reg_wire = DeviceRegisterMsg(device_id="w1", device_type="router")
    reg_legacy = from_aip_to_legacy(reg_wire.model_dump(mode="json", exclude_none=True))
    WorkerRegistrationModel.model_validate(reg_legacy)


# ---------------------------------------------------------------------------
# 任务平面:单数(新规范)与复数(遗留)两个前缀并存
# ---------------------------------------------------------------------------
#
# NATS 逐 token 精确匹配,``galaxy.task.*`` 与 ``galaxy.tasks.*`` 之间没有任何
# 通配符能搭桥。而本仓两个前缀**同时有真实发布方**:
#
#   单数(NATSTopics 常量,新规范)  publish_task_assign / publish_task_result /
#                                  publish_goal_execution / publish_goal_result
#   复数(硬编码,既有运转面)      publish_task_dispatch / publish_legacy_task_result /
#                                  publish_task_envelope / command_router /
#                                  scheduler / gateway_nats_adapter
#
# 修复前订阅侧只订复数,于是单数那四个发布器发出去的东西一条也到不了 ——
# publish_task_result 有四个生产调用方,它们各自都以为闭环了。


@pytest.mark.asyncio
async def test_canonical_singular_publishers_reach_the_brain(bus: NATSBus):
    """新规范(单数)那一侧必须到得了。这是修复前彻底断掉的那半边。"""
    from core.schemas.aip_v3 import TaskAssignMsg, TaskResultMsg

    got: Dict[str, List[Any]] = {"dispatch": [], "result": []}
    await bus.subscribe_task_dispatches("w1", lambda d: got["dispatch"].append(d))
    await bus.subscribe_task_results(lambda d: got["result"].append(d))

    await bus.publish_task_assign(TaskAssignMsg(device_id="w1", task_id="t1", action="noop"))
    await bus.publish_task_result(TaskResultMsg(device_id="w1", task_id="t1", status="ok"))
    await asyncio.sleep(0.05)

    assert got["dispatch"], "单数 task_assign 没到 worker"
    assert got["result"], "单数 task_result 没回到主脑"


@pytest.mark.asyncio
async def test_legacy_plural_publishers_still_reach_the_brain(bus: NATSBus):
    """遗留(复数)那一侧不能因为加了新前缀就被挤掉 —— 它才是当前的运转面。"""
    from core.schemas.contracts import TaskDispatchModel, TaskResultModel

    got: Dict[str, List[Any]] = {"dispatch": [], "result": []}
    await bus.subscribe_task_dispatches("w1", lambda d: got["dispatch"].append(d))
    await bus.subscribe_task_results(lambda d: got["result"].append(d))

    await bus.publish_task_dispatch("w1", TaskDispatchModel(task_id="t2", action="noop", timestamp=_TS))
    await bus.publish_legacy_task_result("t2", TaskResultModel(task_id="t2", status="success", timestamp=_TS))
    await asyncio.sleep(0.05)

    assert got["dispatch"], "复数 task_dispatch 没到 worker"
    assert got["result"], "复数 task_result 没回到主脑"


@pytest.mark.asyncio
async def test_external_publishers_on_the_raw_plural_subject_reach_the_brain(bus: NATSBus):
    """``command_router`` / ``scheduler`` / 网关适配器是直接发裸主题的。

    它们不经 NATSBus 的具名发布器(``_publish(f"galaxy.tasks.result.{id}", ...)``),
    所以只钉具名发布器是钉不住它们的。
    """
    got: List[Any] = []
    await bus.subscribe_task_results(lambda d: got.append(d))
    await bus._publish("galaxy.tasks.result.t3", {"task_id": "t3", "status": "success"})
    await asyncio.sleep(0.05)

    assert got, "外部发布方的裸复数主题没被收到"


@pytest.mark.asyncio
async def test_no_message_is_delivered_twice(bus: NATSBus):
    """并存不能变成重复投递。

    没有任何一条发布路径同时往两个前缀发,所以每条消息只该到一次。真出现重复,
    下游的幂等保护会被无谓地压上负担,结果去重也会掩盖真正的重发。
    """
    from core.schemas.aip_v3 import TaskResultMsg

    got: List[Any] = []
    await bus.subscribe_task_results(lambda d: got.append(d))
    await bus.publish_task_result(TaskResultMsg(device_id="w1", task_id="only-once", status="ok"))
    await asyncio.sleep(0.05)

    assert len(got) == 1, f"同一条消息到了 {len(got)} 次"


@pytest.mark.asyncio
async def test_both_prefixes_carry_distinct_durable_names(bus: NATSBus):
    """两个订阅的 durable 名必须不同。

    JetStream 的 durable consumer 绑死一个 filter subject。两个订阅共用一个
    durable 名会冲突 —— 要么直接报错,要么两边互相抢消息(更难查)。
    """
    seen: List[tuple] = []
    original = bus._subscribe

    async def _spy(subject, callback, durable="", **kw):
        seen.append((subject, durable))
        return await original(subject, callback, durable=durable, **kw)

    bus._subscribe = _spy  # type: ignore[method-assign]
    await bus.subscribe_task_results(lambda d: None)

    assert len(seen) == 2, f"应当订两个主题,实际 {len(seen)}"
    subjects = {s for s, _ in seen}
    durables = [d for _, d in seen]
    assert len(subjects) == 2, "两个订阅落在同一个主题上"
    assert len(set(durables)) == 2, f"durable 名重复:{durables}"


def test_the_stream_covers_both_prefixes():
    """JetStream 流必须同时覆盖两个前缀。

    落在流外的主题不是"慢一点",是**没有持久化**:没有重放、没有 at-least-once。
    任务结果恰恰是最需要这些保证的东西。
    """
    from core.nats_bus import _STREAMS

    subjects = _STREAMS["GALAXY_TASKS"]["subjects"]
    assert "galaxy.tasks.>" in subjects
    assert "galaxy.task.>" in subjects


@pytest.mark.asyncio
async def test_an_existing_stream_gets_the_new_prefix_added():
    """已经建好的流必须能被补上新前缀,而且旧的一个都不能丢。

    修复前建流只有"不存在就建"一条路:流一旦建起来,后来往 ``_STREAMS`` 里加的
    前缀就永远进不去 —— 新前缀在全新部署上生效、在已跑的部署上静默失效,同一份
    代码两种行为,是最难查的一类不一致。

    真 JetStream 上已验证过(老流 ``['galaxy.tasks.>']`` → 连接后
    ``['galaxy.tasks.>', 'galaxy.task.>']``,单数发布拿到真实 seq)。这里用假的
    js 对象把**合并逻辑**钉住,不需要 CI 上有 nats-server。
    """

    class _Cfg:
        def __init__(self, subjects):
            self.subjects = list(subjects)

    class _Info:
        def __init__(self, subjects):
            self.config = _Cfg(subjects)

    updated: List[Any] = []

    class _FakeJS:
        async def stream_info(self, name):
            if name == "GALAXY_TASKS":
                return _Info(["galaxy.tasks.>"])  # 老部署:只有复数
            raise RuntimeError("no such stream")

        async def add_stream(self, cfg):
            updated.append(("add", list(cfg.subjects)))

        async def update_stream(self, cfg):
            updated.append(("update", list(cfg.subjects)))

    bus = NATSBus()
    bus._js = _FakeJS()
    await bus._ensure_streams()

    ups = [subs for kind, subs in updated if kind == "update"]
    assert ups, "已存在的流没有被更新"
    assert "galaxy.task.>" in ups[0], "新前缀没被补进去"
    assert "galaxy.tasks.>" in ups[0], "旧前缀被弄丢了 —— 线上可能还有消费者挂在上面"


@pytest.mark.asyncio
async def test_a_stream_that_already_covers_everything_is_not_touched():
    """已经齐全的流不该被无谓地 update —— 每次启动都改一遍流是噪声,也是风险。"""

    class _Cfg:
        def __init__(self, subjects):
            self.subjects = list(subjects)

    class _Info:
        def __init__(self, subjects):
            self.config = _Cfg(subjects)

    from core.nats_bus import _STREAMS

    touched: List[str] = []

    class _FakeJS:
        async def stream_info(self, name):
            return _Info(_STREAMS[name]["subjects"])

        async def add_stream(self, cfg):
            touched.append("add")

        async def update_stream(self, cfg):
            touched.append("update")

    bus = NATSBus()
    bus._js = _FakeJS()
    await bus._ensure_streams()

    assert touched == [], f"流已经齐全却仍被改动:{touched}"


# ---------------------------------------------------------------------------
# 跨模块调用的公开 API 必须真的存在
# ---------------------------------------------------------------------------


def test_the_public_bus_api_that_other_modules_call_actually_exists():
    """别的模块调到的 NATSBus 方法,必须在 NATSBus 上真的有。

    这条是被一个真缺陷逼出来的:``gateway_nats_adapter`` 一直在调
    ``nats_bus.subscribe(...)``,而 NATSBus 上**从来没有**这个方法。调用抛
    AttributeError,被 ``start()`` 外面那个 ``except Exception`` 吞成一行日志,
    ``_started`` 保持 False —— 网关适配器静默不工作,派给 gateway 的任务一条也
    收不到。

    它能活这么久,是因为测试用 ``MagicMock`` 做替身 —— MagicMock **自动生成任何
    属性**,于是 ``nats_bus.subscribe`` 在测试里"存在"、在生产里不存在,用例一直
    是绿的。所以这条不打桩,直接对真类做 hasattr。
    """
    from core.nats_bus import NATSBus

    # 跨模块调用点(git grep "nats_bus\.<name>" 得到)必须都在真类上存在。
    required = [
        "subscribe",  # galaxy_gateway/gateway_nats_adapter.py
        "subscribe_task_dispatches",  # core/worker_runtime.py
        "subscribe_task_results",  # core/master_brain.py, core/command_router.py
        "subscribe_heartbeats",  # core/master_brain.py
        "subscribe_worker_registrations",  # core/master_brain.py
        "subscribe_worker_shutdowns",  # core/master_brain.py
        "publish_legacy_heartbeat",  # core/nats_heartbeat.py
        "publish_legacy_worker_registration",  # core/nats_heartbeat.py
        "publish_legacy_worker_shutdown",  # core/nats_heartbeat.py
        "is_connected",
        "is_usable",
        "is_local_mode",
        "unsubscribe",
    ]
    missing = [name for name in required if not hasattr(NATSBus, name)]
    assert not missing, f"这些被别的模块调用的方法在 NATSBus 上不存在:{missing}"


def test_is_usable_is_true_on_the_in_process_bus():
    """闸门语义:进程内降级总线**可用**。

    全仓二十多处 ``if nats.is_connected():`` 形式的闸门此前在单机模式下全部
    静默跳过 —— 心跳不发、任务不派、结果不回、网关适配器不订阅,而日志里什么
    异常都没有,因为那不是异常,是 if 判 False。单机跑起来看着一切正常,实际上
    整条 NATS 依赖面是黑的。
    """
    bus = NATSBus()
    assert bus.is_connected() is False
    assert bus.is_usable() is False, "既没连网络也没启降级总线,应当不可用"

    bus.enable_local_fallback("测试")
    assert bus.is_connected() is False, "本地总线不是网络连接"
    assert bus.is_usable() is True, "本地总线是可用的 —— 闸门必须放行"


@pytest.mark.asyncio
async def test_the_gateway_adapter_starts_on_the_in_process_bus():
    """网关适配器在单机模式下也要真的订上。

    两处缺陷叠加过:方法不存在(AttributeError 被吞),以及闸门看 is_connected()
    在本地模式恒 False 直接早退。两条都修掉了才有这一条。
    """
    from core.nats_bus import get_nats_bus
    from galaxy_gateway.gateway_nats_adapter import GatewayNATSAdapter

    get_nats_bus().enable_local_fallback("测试:进程内总线")
    adapter = GatewayNATSAdapter()
    await adapter.start()
    try:
        assert adapter._started is True, "网关适配器在单机模式下没订上"
    finally:
        await adapter.stop()
