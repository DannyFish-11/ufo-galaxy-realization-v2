"""galaxy_gateway/android/handlers/mesh_mirror.py — 线上消息 → AIP v3 → 网格。

职责边界
--------
handler 收到的是 Android 发来的**线上 dict**(字段名、嵌套、缺省各家不一);网格
上跑的是 **AIP v3 消息类**。两者之间的翻译是一件独立的事,和"这条消息该怎么
处理"没有关系。

这里只做翻译 + 交给 :func:`core.aip_mesh_mirror.mirror_to_mesh` 发出去。发射
本身(取 loop、建后台任务、持强引用、吞异常)在那一层,不在这里。

为什么集中在一个模块
--------------------
* **一处对照**。镜像表(``core/aip_mesh_mirror._PUBLISHER_BY_TYPE``)列的是
  "哪些消息发得出去",这里列的是"哪些消息真的有人在发"。两张表放在一起,
  协议接没接全一眼可对。散回各 handler 就只能靠 grep 拼。
* **不给已经过胖的 handler 添重**。``goal_execution.py`` 1760 行、
  ``task_lifecycle.py`` 1244 行,都已经在复杂度基线上被记着;
  把翻译代码塞进去会把它们继续推向 2000 行硬上限。

失败语义
--------
每个函数都是 best-effort:handler 已经在自己的链路上把消息处理完了,镜像只是
让网格里其它节点也看得见。翻译失败(字段缺、类型不对)只记 debug,绝不能让
handler 本身失败或变慢。
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional, Sequence

logger = logging.getLogger(__name__)

__all__ = [
    "mirror_heartbeat_ack",
    "mirror_peer_announce",
    "mirror_peer_exchange",
    "mirror_mesh_topology",
    "mirror_takeover_response",
    "mirror_delegated_signal",
    "mirror_reconciliation_signal",
    "mirror_goal_execution",
    "mirror_goal_result",
    "mirror_task_cancel",
    "mirror_cancel_result",
    "mirror_generic_ack",
]


def _s(value: Any) -> str:
    """线上字段取字符串;``None`` 与缺省一律成空串。"""
    return str(value or "")


def _i(value: Any, default: int = 0) -> int:
    """线上字段取整数;非数字一律回落到 *default*(线上来的东西不能信)。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _list(value: Any) -> list:
    """线上字段取字符串列表;不是序列就当空。"""
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    return []


def _dict(value: Any) -> dict:
    return dict(value) if isinstance(value, dict) else {}


def _send(build_label: str, msg: Any) -> bool:
    """交给镜像层发出去。翻译已完成,这里只兜住发射侧的意外。"""
    try:
        from core.aip_mesh_mirror import mirror_to_mesh  # noqa: PLC0415

        return mirror_to_mesh(msg)
    except Exception as exc:  # pragma: no cover
        logger.debug("%s 网格镜像跳过:%s", build_label, exc)
        return False


# ---------------------------------------------------------------------------
# 设备生命周期
# ---------------------------------------------------------------------------


def mirror_heartbeat_ack(device_id: Any, message: Dict[str, Any]) -> bool:
    """HEARTBEAT_ACK —— 心跳的应答半边。

    设备的心跳本身已经上了网格(``publish_heartbeat``),应答不上去的话,网格里
    只看得到"设备还在喊",看不到"中心听见了"—— 判不出是设备掉线还是中心没在处理。
    """
    try:
        from core.schemas.aip_v3 import HeartbeatAckMsg  # noqa: PLC0415

        return _send(
            "heartbeat_ack",
            HeartbeatAckMsg(
                device_id=_s(device_id),
                trace_id=_s(message.get("trace_id")),
                session_id=_s(message.get("session_id")),
                server_timestamp=int(time.time() * 1000),
            ),
        )
    except Exception as exc:  # pragma: no cover
        logger.debug("heartbeat_ack 构造失败:%s", exc)
        return False


# ---------------------------------------------------------------------------
# 对等 / 拓扑
# ---------------------------------------------------------------------------


def mirror_peer_announce(device_id: Any, message: Dict[str, Any], payload: Dict[str, Any]) -> bool:
    """PEER_ANNOUNCE —— 一台设备加入。

    不上网格的话,这台设备只对接它的那个网关可见,别的节点算不出完整拓扑。
    """
    try:
        from core.schemas.aip_v3 import PeerAnnounceMsg  # noqa: PLC0415

        return _send(
            "peer_announce",
            PeerAnnounceMsg(
                device_id=_s(device_id),
                peer_device_id=_s(device_id),
                peer_device_type=_s(payload.get("device_type") or message.get("device_type")),
                peer_capabilities=_list(payload.get("capabilities") or message.get("capabilities")),
                mesh_id=_s(message.get("mesh_id")),
                session_id=_s(message.get("session_id")),
                trace_id=_s(message.get("trace_id")),
            ),
        )
    except Exception as exc:  # pragma: no cover
        logger.debug("peer_announce 构造失败:%s", exc)
        return False


def mirror_peer_exchange(device_id: Any, message: Dict[str, Any]) -> bool:
    """PEER_EXCHANGE —— "谁能为谁做什么"的协商,别的节点据此做调度决策。"""
    try:
        from core.schemas.aip_v3 import PeerExchangeMsg  # noqa: PLC0415

        return _send(
            "peer_exchange",
            PeerExchangeMsg(
                device_id=_s(device_id),
                peer_device_id=_s(message.get("peer_device_id")),
                offered_capabilities=_list(message.get("offered_capabilities") or message.get("capabilities")),
                requested_capabilities=_list(message.get("requested_capabilities")),
                session_id=_s(message.get("session_id")),
                trace_id=_s(message.get("trace_id")),
            ),
        )
    except Exception as exc:  # pragma: no cover
        logger.debug("peer_exchange 构造失败:%s", exc)
        return False


def mirror_mesh_topology(device_id: Any, message: Dict[str, Any], topology: Any, peer_count: int) -> bool:
    """MESH_TOPOLOGY —— 拓扑答复。

    这一份只回给发问的那台设备。镜像上网格,别的节点才能拿同一时刻的同一份
    拓扑做对账 —— 拓扑分歧正是网格类故障最难查的一种。
    """
    try:
        from core.schemas.aip_v3 import MeshTopologyMsg  # noqa: PLC0415

        return _send(
            "mesh_topology",
            MeshTopologyMsg(
                device_id=_s(device_id),
                mesh_id=_s(message.get("mesh_id")),
                topology=_dict(topology),
                peer_count=_i(peer_count),
                request_type="update",  # 这是答复,不是发问
                session_id=_s(message.get("session_id")),
                trace_id=_s(message.get("trace_id")),
            ),
        )
    except Exception as exc:  # pragma: no cover
        logger.debug("mesh_topology 构造失败:%s", exc)
        return False


def mirror_takeover_response(
    *,
    device_id: Any,
    takeover_id: Any,
    accepted: bool,
    reason: Any,
    session_id: Any,
    task_id: Any,
    trace_id: Any,
) -> bool:
    """TAKEOVER_RESPONSE —— 接管的应答半边。

    TAKEOVER_REQUEST 早就上了网格。只有请求没有应答,网格里就只看得到"有人要
    接管",永远看不到接管到底成没成 —— 判不出控制权现在在谁手里。
    """
    try:
        from core.schemas.aip_v3 import TakeoverResponseMsg  # noqa: PLC0415

        return _send(
            "takeover_response",
            TakeoverResponseMsg(
                device_id=_s(device_id),
                request_correlation_id=_s(takeover_id),
                accepted=bool(accepted),
                rejection_reason="" if accepted else _s(reason),
                session_id=_s(session_id),
                task_id=_s(task_id),
                trace_id=_s(trace_id),
            ),
        )
    except Exception as exc:  # pragma: no cover
        logger.debug("takeover_response 构造失败:%s", exc)
        return False


# ---------------------------------------------------------------------------
# 信号
# ---------------------------------------------------------------------------


def mirror_delegated_signal(device_id: Any, message: Dict[str, Any]) -> bool:
    """DELEGATED_EXECUTION_SIGNAL —— "任务此刻跑到哪了"的唯一来源。

    不上网格,别的节点就只能靠超时猜,做不了接管或重调度的判断。
    """
    try:
        from core.schemas.aip_v3 import DelegatedExecutionSignalMsg  # noqa: PLC0415

        payload = _dict(message.get("payload"))
        return _send(
            "delegated_execution_signal",
            DelegatedExecutionSignalMsg(
                device_id=_s(device_id),
                signal_kind=_s(message.get("signal_kind") or message.get("kind")),
                payload=payload,
                progress_pct=_i(message.get("progress_pct") or payload.get("progress_pct")),
                session_id=_s(message.get("session_id")),
                task_id=_s(message.get("task_id")),
                trace_id=_s(message.get("trace_id")),
            ),
        )
    except Exception as exc:  # pragma: no cover
        logger.debug("delegated_execution_signal 构造失败:%s", exc)
        return False


def mirror_reconciliation_signal(device_id: Any, message: Dict[str, Any]) -> bool:
    """RECONCILIATION_SIGNAL —— 设备侧的运行时真相快照。

    这正是网格里其它节点用来消解状态分歧的输入。只回给发信设备,等于对账做了一半。
    """
    try:
        from core.schemas.aip_v3 import ReconciliationSignalMsg  # noqa: PLC0415

        return _send(
            "reconciliation_signal",
            ReconciliationSignalMsg(
                device_id=_s(device_id),
                signal_kind=_s(message.get("signal_kind") or message.get("kind")),
                payload=_dict(message.get("payload")),
                source_runtime_truth=_dict(message.get("source_runtime_truth") or message.get("runtime_truth")),
                session_id=_s(message.get("session_id")),
                task_id=_s(message.get("task_id")),
                trace_id=_s(message.get("trace_id")),
            ),
        )
    except Exception as exc:  # pragma: no cover
        logger.debug("reconciliation_signal 构造失败:%s", exc)
        return False


# ---------------------------------------------------------------------------
# 目标执行
# ---------------------------------------------------------------------------


def mirror_goal_execution(
    *,
    device_id: Any,
    task_id: Any,
    goal: Any,
    payload: Dict[str, Any],
    session_id: Any,
    trace_id: Any,
) -> bool:
    """GOAL_EXECUTION —— 目标已被受理并派给了这台设备。

    网格里其它节点据此知道这个目标名花有主 —— 否则同一个目标可能被两个入口
    各自接一遍。
    """
    try:
        from core.schemas.aip_v3 import GoalExecutionMsg  # noqa: PLC0415

        subtasks = payload.get("parallel_subtasks") or []
        return _send(
            "goal_execution",
            GoalExecutionMsg(
                device_id=_s(device_id),
                goal=_s(goal),
                params=_dict(payload.get("params")),
                parallel_subtasks=[s for s in subtasks if isinstance(s, dict)],
                source_device_id=_s(payload.get("source_device_id") or device_id),
                task_id=_s(task_id),
                session_id=_s(session_id),
                trace_id=_s(trace_id),
            ),
        )
    except Exception as exc:  # pragma: no cover
        logger.debug("goal_execution 构造失败:%s", exc)
        return False


def mirror_goal_result(
    *,
    device_id: Any,
    task_id: Any,
    status: Any,
    result_text: Any,
    payload: Dict[str, Any],
    session_id: Any,
    trace_id: Any,
) -> bool:
    """GOAL_EXECUTION_RESULT —— 目标的终态。

    GOAL_EXECUTION 已经上了网格,结果不上去的话,网格里的目标永远停在"已派发",
    看不出跑完没有、成没成。
    """
    try:
        from core.schemas.aip_v3 import GoalExecutionResultMsg  # noqa: PLC0415

        summary = result_text if isinstance(result_text, str) else ""
        return _send(
            "goal_execution_result",
            GoalExecutionResultMsg(
                device_id=_s(device_id),
                status=_s(status),
                result_summary=summary[:512],
                result=result_text,
                error=_s(payload.get("error")),
                duration_ms=_i(payload.get("duration_ms")),
                task_id=_s(task_id),
                session_id=_s(session_id),
                trace_id=_s(trace_id),
            ),
        )
    except Exception as exc:  # pragma: no cover
        logger.debug("goal_execution_result 构造失败:%s", exc)
        return False


# ---------------------------------------------------------------------------
# 任务取消
# ---------------------------------------------------------------------------


def mirror_task_cancel(device_id: Any, task_id: Any, message: Dict[str, Any]) -> bool:
    """TASK_CANCEL —— 谁要取消、为什么。"""
    try:
        from core.schemas.aip_v3 import TaskCancelMsg  # noqa: PLC0415

        return _send(
            "task_cancel",
            TaskCancelMsg(
                device_id=_s(device_id),
                task_id=_s(task_id),
                force=bool(message.get("force", False)),
                reason=_s(message.get("reason")),
                session_id=_s(message.get("session_id")),
                trace_id=_s(message.get("trace_id")),
            ),
        )
    except Exception as exc:  # pragma: no cover
        logger.debug("task_cancel 构造失败:%s", exc)
        return False


def mirror_cancel_result(
    device_id: Any,
    task_id: Any,
    cancelled: bool,
    reason: Any,
    message: Dict[str, Any],
) -> bool:
    """CANCEL_RESULT —— 到底取消掉了没有、清理干不干净。

    只发 TASK_CANCEL 的话,网格看得到有人喊停、看不到停没停;而任务可能已经
    跑完了,那跟"成功取消"是两回事。``cleanup_status`` 用取消链路自己给出的
    reason 判定,下游据以区分"停住了 / 来不及了 / 停不下来":

    * ``clean``   —— 取消生效;
    * ``partial`` —— 任务已经跑完了(没什么可清理的,但也不是取消生效);
    * ``failed``  —— 其余(传播失败、找不到任务)。
    """
    try:
        from core.schemas.aip_v3 import CancelResultMsg  # noqa: PLC0415

        if cancelled:
            cleanup = "clean"
        elif reason == "task_already_completed":
            cleanup = "partial"
        else:
            cleanup = "failed"
        return _send(
            "cancel_result",
            CancelResultMsg(
                device_id=_s(device_id),
                task_id=_s(task_id),
                cancelled=bool(cancelled),
                cleanup_status=cleanup,
                session_id=_s(message.get("session_id")),
                trace_id=_s(message.get("trace_id")),
            ),
        )
    except Exception as exc:  # pragma: no cover
        logger.debug("cancel_result 构造失败:%s", exc)
        return False


# ---------------------------------------------------------------------------
# 通用应答
# ---------------------------------------------------------------------------


def mirror_generic_ack(device_id: Any, normalized_type: str, message: Dict[str, Any]) -> bool:
    """ACK —— 兼容路径的裸应答。

    兼容路径回的 ACK 没有任何状态语义,正因为如此,网格里更需要看到它:否则
    一条走兼容路径的消息,在网格视角里是"发出去了然后什么都没发生",与真的
    丢了分不出来。
    """
    try:
        from core.schemas.aip_v3 import AckMsg  # noqa: PLC0415

        return _send(
            "ack",
            AckMsg(
                device_id=_s(device_id),
                ack_for_type=normalized_type,
                ack_for_correlation_id=_s(message.get("message_id")),
                status="ok",
                session_id=_s(message.get("session_id")),
                trace_id=_s(message.get("trace_id")),
            ),
        )
    except Exception as exc:  # pragma: no cover
        logger.debug("generic ack 构造失败:%s", exc)
        return False


def mirror_capability_query(required_capabilities: Sequence[str], *, device_id: Optional[str] = None) -> bool:
    """CAPABILITY_QUERY —— 本机选不出设备时,向网格问一句。

    放在这里而不是 ``core/`` 里:它和上面那些一样,是"把本地事实翻译成一条
    AIP v3 消息"。唯一的区别是触发它的不是一条线上消息,而是一次路由失败。
    """
    try:
        from core.schemas.aip_v3 import CapabilityQueryMsg  # noqa: PLC0415

        return _send(
            "capability_query",
            CapabilityQueryMsg(
                device_id=_s(device_id),  # 问的是整个网格,默认不针对某台设备
                query_filter=",".join(str(c) for c in required_capabilities),
            ),
        )
    except Exception as exc:  # pragma: no cover
        logger.debug("capability_query 构造失败:%s", exc)
        return False


__all__.append("mirror_capability_query")
