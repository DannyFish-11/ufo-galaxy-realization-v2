"""core/participant_truth_ingress.py — 参与方真相入口的通用接口（架构冻结计划 P3 · R7）。

要解决什么
==========
V2 真相链的第 1 步（:mod:`core.task_result_canonical_truth_chain`）把「参与方报上来的执行
真相」对账进中心的规范状态。这一步的逻辑本身与设备种类无关 —— 对账的对象是委派执行的
追踪记录、附着运行时会话、任务相位 —— 可它的入口名叫
``ingest_android_participant_truth_message``，真相链直接 import 它。于是「一台非安卓的
参与方把结果报回来」在结构上就没有位置：要么冒充安卓，要么另复制一份对账。

冻结守则 R5.3 规定了泛化的顺序：**定义抽象 → 热路径调抽象 → 实现符合抽象 → 才可改名**。
本模块完成前两步，并把安卓实现登记为第一个（也是默认的）实现：

* :class:`ParticipantTruthKind` —— 与设备无关的真相种类。
* :class:`ParticipantTruthIngressProtocol` —— 一个参与方族（``android``、``ios`` ……）
  的真相入口要满足的接口。
* :func:`ingest_participant_truth_message` —— 真相链调的通用入口：按消息声明的参与方族
  分派到对应实现。

刻意的边界
==========
* **行为逐位不变。** 不声明族的消息、以及声明了但还没有专门实现的族，一律交给默认实现
  （安卓那一份）—— 这正是今天每一条消息的去处。
* **没有改名。** ``android_participant_truth_ingress`` 原样保留（R5.3 第 4 步不在本项内）。
* ``ParticipantTruthKind`` **不是** ``AndroidParticipantTruthKind`` 的父类：Python 的枚举
  一旦有成员就不能被继承。两者按取值对齐，由测试钉住「安卓的每一种真相都有通用对应」。
"""

from __future__ import annotations

import importlib
import logging
from enum import Enum
from typing import Any, Callable, Dict, Optional, Protocol, Tuple, runtime_checkable

logger = logging.getLogger("Galaxy.ParticipantTruthIngress")

DEFAULT_PARTICIPANT_FAMILY = "android"


class ParticipantTruthKind(str, Enum):
    """参与方报上来的真相是哪一种。取值与 ``AndroidParticipantTruthKind`` 一一对应。"""

    session_snapshot = "session_snapshot"
    readiness_assessment = "readiness_assessment"
    task_phase = "task_phase"
    runtime_state = "runtime_state"
    cancel = "cancel"
    status = "status"
    failure = "failure"
    result = "result"
    reconciliation_signal = "reconciliation_signal"
    governance_artifact = "governance_artifact"
    recovery_state = "recovery_state"
    unknown = "unknown"

    @classmethod
    def from_string(cls, value: Optional[str]) -> "ParticipantTruthKind":
        normalised = str(value or "").strip().lower()
        for member in cls:
            if member.value == normalised:
                return member
        return cls.unknown


@runtime_checkable
class ParticipantTruthIngressProtocol(Protocol):
    """一个参与方族的真相入口。

    ``ingest`` 返回的结果对象至少带 ``was_reconciled: bool`` —— 真相链只读这一个字段。
    """

    participant_family: str

    def ingest(self, message: Dict[str, Any], *, runtime: Any = None, registry: Any = None) -> Any: ...


class AndroidParticipantTruthIngress:
    """安卓实现：委托 :func:`core.android_participant_truth_ingress.ingest_android_participant_truth_message`。

    每次调用时才取那个函数 —— 测试与运维对它打的补丁因此照样生效。
    """

    participant_family = "android"

    def ingest(self, message: Dict[str, Any], *, runtime: Any = None, registry: Any = None) -> Any:
        from core import android_participant_truth_ingress as _android

        return _android.ingest_android_participant_truth_message(message, runtime=runtime, registry=registry)


#: 族 → 实现的构造函数。新增一个参与方族 = 在这里登记一行。
PARTICIPANT_TRUTH_INGRESS: Dict[str, Callable[[], ParticipantTruthIngressProtocol]] = {
    "android": AndroidParticipantTruthIngress,
}

_FAMILY_FIELDS: Tuple[str, ...] = ("participant_family", "participant_kind")


def participant_family_of(message: Dict[str, Any]) -> str:
    """消息声明的参与方族；没声明返回默认族（今天所有真相消息都来自安卓）。"""
    payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}
    for field in _FAMILY_FIELDS:
        value = message.get(field) or payload.get(field)
        if value:
            return str(value).strip().lower()
    return DEFAULT_PARTICIPANT_FAMILY


def resolve_participant_truth_ingress(family: str) -> ParticipantTruthIngressProtocol:
    """取某族的实现；该族还没有专门实现时回落到默认族（逐位保持旧行为）。"""
    factory = PARTICIPANT_TRUTH_INGRESS.get(family)
    if factory is None:
        logger.debug(
            "participant family %r has no dedicated truth ingress; using %r", family, DEFAULT_PARTICIPANT_FAMILY
        )
        factory = PARTICIPANT_TRUTH_INGRESS[DEFAULT_PARTICIPANT_FAMILY]
    return factory()


def ingest_participant_truth_message(
    message: Dict[str, Any], *, runtime: Optional[Any] = None, registry: Optional[Any] = None
) -> Any:
    """真相链第 1 步的通用入口。"""
    return resolve_participant_truth_ingress(participant_family_of(message)).ingest(
        message, runtime=runtime, registry=registry
    )


def _module_available(name: str) -> bool:
    try:
        importlib.import_module(name)
        return True
    except ImportError:
        return False


#: 默认实现的后备模块不可导入时，真相链把第 1 步记为 SKIPPED_MODULE_UNAVAILABLE（旧语义）。
DEFAULT_IMPLEMENTATION_AVAILABLE: bool = _module_available("core.android_participant_truth_ingress")


__all__ = [
    "DEFAULT_IMPLEMENTATION_AVAILABLE",
    "DEFAULT_PARTICIPANT_FAMILY",
    "PARTICIPANT_TRUTH_INGRESS",
    "AndroidParticipantTruthIngress",
    "ParticipantTruthIngressProtocol",
    "ParticipantTruthKind",
    "ingest_participant_truth_message",
    "participant_family_of",
    "resolve_participant_truth_ingress",
]
