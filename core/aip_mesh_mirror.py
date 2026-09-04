"""core/aip_mesh_mirror.py — AIP v3 消息到 NATS 网格面的统一镜像出口。

为什么需要这一层
----------------
AIP v3 为设备协议定义了 28 个消息类,``core/nats_bus.py`` 为**每一个**都写了
对应的 ``publish_*``。但真正被生产代码调用过的只有一小半 —— 协议表面按消息
类型铺满了,发送方只接了其中几条路。剩下的方法既不是死代码也不是活代码:它们
是**写好了但从来没有人按下的按钮**。

这不是"清理一下死代码"能解决的问题。这套协议是为各种设备铺的路,缺一种消息
就意味着网格里少一种别的节点能听懂的事实。所以正确的方向是**接全**,不是删。

这一层做两件事:

1. **把"消息类型 → 发布器"这张表集中到一处**。协议接没接全,从此是一个可以
   一眼看出来、也可以被测试机器校验的事实(见
   :func:`unpublishable_message_types`),而不是散落在二十来个 handler 里
   谁也说不清的状态。新增一个 AIP 消息类却忘了给它发布器,测试当场就红。

2. **把 best-effort 发射收敛成一次实现**。在此之前只有
   ``galaxy_gateway/android/handlers/takeover_request.py`` 一处真的发了,
   代价是 25 行样板:取运行中的 loop、建后台任务、持强引用防 GC、吞掉所有
   异常。要在另外十个 handler 里复制这段,复制出来的每一份都会各自漂移。

镜像语义
--------
"镜像"是刻意选的词:handler 已经在它自己的链路上把这条消息处理完了(改会话
状态、回 WS 应答),镜像只是让**网格里的其它节点**也看得见这件事发生过。所以

* 它是 **best-effort** 的 —— NATS 没连上、没装 nats-py、消息类型没登记,
  都只是"这次没镜像出去",绝不能让 handler 本身的处理失败;
* 它是 **fire-and-forget** 的 —— handler 不等它,应答延迟不受网格影响;
* 它 **不改变消息内容** —— 送上网格的就是 handler 手里那条 AIP v3 消息本身。
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Dict, Set, Tuple

if TYPE_CHECKING:  # pragma: no cover - 仅供类型检查
    from core.schemas.aip_v3 import AIPMessage

logger = logging.getLogger(__name__)

__all__ = [
    "mirror_to_mesh",
    "publisher_for",
    "unpublishable_message_types",
    "mesh_exempt_message_types",
    "AIP_MESH_MIRROR_AUTHORITY",
]

#: 本模块是 AIP v3 → NATS 网格面镜像的权威实现。
AIP_MESH_MIRROR_AUTHORITY: str = "AIP_MESH_MIRROR::V1"

# 事件循环只持后台任务的弱引用,不留强引用会被 GC 掉,任务静默消失。
_BACKGROUND_TASKS: Set[asyncio.Task] = set()


# ---------------------------------------------------------------------------
# 消息类型 → NATSBus 发布器
# ---------------------------------------------------------------------------
#
# 键是 ``MsgType`` 的**字符串值**而不是枚举成员:这样本模块不必在导入期就把
# aip_v3 拉进来(它带 pydantic,是启动期的重量级依赖),而 ``msg.type`` 因为
# ``MsgType(str, Enum)`` 本身就是字符串,查表天然可用。
#
# 这张表就是"协议接全了没有"的账本。少一行,tests/test_aip_mesh_mirror.py 里
# 的完整性用例当场判红。
_PUBLISHER_BY_TYPE: Dict[str, str] = {
    # ── 设备生命周期 ──
    "device_register": "publish_device_register",
    "device_unregister": "publish_device_unregister",
    "heartbeat": "publish_heartbeat",
    "heartbeat_ack": "publish_heartbeat_ack",
    "capability_report": "publish_capability_report",
    "capability_query": "publish_capability_query",
    # ── 任务 / 执行 ──
    "task_assign": "publish_task_assign",
    "task_result": "publish_task_result",
    "task_cancel": "publish_task_cancel",
    "cancel_result": "publish_cancel_result",
    "goal_execution": "publish_goal_execution",
    "goal_execution_result": "publish_goal_result",
    # ── 网格协同 ──
    "mesh_join": "publish_mesh_join",
    "mesh_leave": "publish_mesh_leave",
    "mesh_result": "publish_mesh_result",
    "mesh_topology": "publish_mesh_topology",
    "coord_sync": "publish_coord_sync",
    # ── 对等 / 接管 ──
    "peer_announce": "publish_peer_announce",
    "peer_exchange": "publish_peer_exchange",
    "takeover_request": "publish_takeover_request",
    "takeover_response": "publish_takeover_response",
    # ── 信号 ──
    "delegated_execution_signal": "publish_delegated_signal",
    "reconciliation_signal": "publish_reconciliation",
    "state_event": "publish_state_event",
    # ── WebRTC 控制面 ──
    "webrtc_bind": "publish_webrtc_bind",
    "webrtc_unbind": "publish_webrtc_unbind",
    "webrtc_transport_state": "publish_webrtc_transport_state",
    # ── 通用应答 ──
    "ack": "publish_ack",
}


#: 明确**不镜像到网格**的类型 → 理由。
#:
#: 做成 {类型: 理由} 而不是一个名字列表:一条没有理由的豁免,和把门关掉没有区别。
#: 上面那张表回答"该走哪个发布器",这张表回答"为什么它根本不该上网格"——两个问题
#: 都必须有答案,不能有第三类"没人管过"的消息。
#:
#: 实时语音通话这六条全部落在这里,理由不是"懒得写发布器",是**写了会出事**:
_MESH_EXEMPT: Dict[str, str] = {
    "voice_call_start": (
        "承载完整的 SDP offer —— 设备的内网与公网地址、ICE ufrag/pwd、DTLS 指纹。"
        "那是一次通话的会话凭据,广播到网格上等于发给每一个节点。"
    ),
    "voice_call_accepted": "同上,承载 SDP answer,同样是会话凭据。",
    "voice_ice": (
        "ICE 候选逐条暴露设备所在的网络位置(内网网段、运营商出口地址)。" "第三方节点拿它没有任何用处,只剩泄露。"
    ),
    "voice_event": ("承载用户说话的实时转写文本。把它镜像给网格上每个节点,就是把私人对话广播出去。"),
    "voice_interrupt": ("只在一条 WebRTC 通话的两端之间有意义(让对端立刻停口),第三方节点收到它无事可做。"),
    "voice_call_end": (
        "同上,通话生命周期只对这条链路的两端有意义。"
        "\n"
        "注意区分:'这台设备正在通话中'确实是网格该知道的事 —— 但那属于在场/可打断性,"
        "由 state_event 承载,不是把通话信令原样转发出去。把它接进 state_event 是另一件事,"
        "不在实时语音通话这一轮的范围里。"
    ),
}


def mesh_exempt_message_types() -> Dict[str, str]:
    """明确不上网格的类型及其理由。给体检与测试读,不要在运行路径上用。"""
    return dict(_MESH_EXEMPT)


def publisher_for(msg_type: Any) -> str:
    """这个消息类型该走哪个 ``NATSBus`` 发布器;没登记则返回空串。"""
    return _PUBLISHER_BY_TYPE.get(str(getattr(msg_type, "value", msg_type)), "")


def unpublishable_message_types() -> Tuple[str, ...]:
    """AIP v3 里**有消息类、却没有网格发布器**的类型,按名字排序。

    这是协议完整性的机器判据。正常情况下它必须是空的 —— 非空就意味着有一种
    消息可以在别的链路上被构造出来,却永远上不了网格,别的设备无从知道它发生过。

    只统计**有对应模型类**的类型:``MsgType`` 里有几个成员(如 ``broadcast``、
    ``parallel_subtask``)是别的链路的线上词汇,并没有 AIP v3 模型类,不属于
    本层的职责范围。

    ``_MESH_EXEMPT`` 里的类型也不计入 —— 它们不是"忘了接",是**明确不该上网格**,
    每一条都在那张表里写了理由。
    """
    from core.schemas.aip_v3 import AIPMessage as _Base  # noqa: PLC0415

    missing = []
    for cls in _iter_message_classes(_Base):
        field = cls.model_fields.get("type")
        default = getattr(field, "default", None) if field is not None else None
        if default is None:
            continue  # 基类本身:type 是必填、没有默认值
        value = str(getattr(default, "value", default))
        if value not in _PUBLISHER_BY_TYPE and value not in _MESH_EXEMPT:
            missing.append(value)
    return tuple(sorted(missing))


def _iter_message_classes(base: type):
    """遍历 ``AIPMessage`` 的所有子类(含多层继承)。"""
    for sub in base.__subclasses__():
        yield sub
        yield from _iter_message_classes(sub)


def mirror_to_mesh(msg: "AIPMessage") -> bool:
    """把一条已处理完的 AIP v3 消息镜像到 NATS 网格面。

    返回是否真的把发送任务派出去了。返回 ``False`` 只说明"这次没镜像出去"
    (NATS 没连上、不在事件循环里、消息类型没登记),**不是错误** —— 调用方
    不需要、也不应该因此改变自己的处理结果。本函数不抛异常。
    """
    method_name = publisher_for(getattr(msg, "type", ""))
    if not method_name:
        logger.debug("AIP 网格镜像:消息类型 %r 没有登记发布器,跳过", getattr(msg, "type", ""))
        return False

    try:
        from core.nats_bus import get_nats_bus  # noqa: PLC0415  惰性导入:避免启动期拉起 NATS 栈

        bus = get_nats_bus()
        # 进程内降级总线也算"发得出去"。``is_connected()`` 判的是**网络**连接
        # (``self._nc is not None``),本地模式下恒为 False —— 只看它的话,单机
        # 运行时镜像永远不发,而本地总线的全部意义正是"单机语义完整保留:同进程
        # 内订阅者照常收到消息"。真跑一遍才发现的:桩总线 is_connected() 返回
        # True,把这个洞完全盖住了。
        if not (bus.is_connected() or bus.is_local_mode()):
            # NATS 完全不可用时这是常态,不是故障 —— 用 debug 而不是 warning,
            # 否则跑一天日志里全是它。
            logger.debug("AIP 网格镜像:总线不可用,%s 跳过", method_name)
            return False

        publish = getattr(bus, method_name, None)
        if publish is None:  # pragma: no cover - 表与 NATSBus 不同步时的兜底
            logger.warning("AIP 网格镜像:NATSBus 上没有 %s —— 镜像表与总线不同步", method_name)
            return False

        loop = asyncio.get_running_loop()
        task = loop.create_task(publish(msg))
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_BACKGROUND_TASKS.discard)
        return True
    except RuntimeError:
        # 没有运行中的事件循环(同步上下文调用)。镜像是可选的,不值得为它起一个循环。
        logger.debug("AIP 网格镜像:不在事件循环内,%s 跳过", method_name)
        return False
    except Exception as exc:  # pragma: no cover - 镜像绝不能影响 handler 本身
        logger.debug("AIP 网格镜像失败(已忽略):%s", exc)
        return False
