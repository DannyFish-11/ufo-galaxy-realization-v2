"""core/device_onboarding/models.py — 接入平面里流转的几样东西。

* :class:`Observation` —— 某个发现来源"看见了一个东西"。来源各自把原始信息翻成它,
  平面其余部分不关心来源长什么样。
* :class:`Candidate` —— 附近有这么个东西,还不是成员。**不进 UDM、不进能力平面。**
* :class:`MemberRecord` —— 谁是我的成员、怎么接入的、桥是谁。持久化,重启后回灌 UDM。
* :class:`JoinOutcome` —— 一次接入尝试的结果:成了、要人做一件具体的事、失败。
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class HumanStep(str, Enum):
    """接入需要人做什么。前两档可被 ``GALAXY_ONBOARDING_AUTO`` 自动化,后三档永远不能。"""

    NONE = "none"  # 什么都不用
    APPROVE = "approve"  # 点一下同意(智能体可在手表上问)
    PHYSICAL_CODE = "physical_code"  # 设备上的配网码/PIN(只有人手里有)
    CONFIRM_ON_DEVICE = "confirm_on_device"  # 在那台设备上操作(输配对码)
    RUN_COMMAND = "run_command"  # 在那台设备上执行一条命令


#: 可被配置自动化的档位,按从严到宽排列。
AUTOMATABLE = (HumanStep.NONE, HumanStep.APPROVE)


class CandidateStatus(str, Enum):
    NEW = "new"
    NEEDS_HUMAN = "needs_human"
    JOINING = "joining"
    JOINED = "joined"
    IGNORED = "ignored"
    FAILED = "failed"


@dataclass
class Observation:
    """发现来源看见的一个东西。"""

    source: str  # mdns / ssdp / ha_flow / tailnet / nats_worker / manual
    key: str  # 在该来源内稳定唯一:mDNS 名、SSDP USN、HA flow_id、headscale 节点 id、worker id
    name: str = ""
    kind_hint: str = ""  # 原始类型提示,交给 taxonomy.classify_type
    addresses: List[str] = field(default_factory=list)
    #: 强标识,用来认领已有成员:device_id / ha_entity_id / tailnet_name / worker_id / ip / mac
    identity: Dict[str, str] = field(default_factory=dict)
    properties: Dict[str, Any] = field(default_factory=dict)
    capabilities: List[str] = field(default_factory=list)
    present: bool = True  # False = 来源说它不见了


def candidate_id_for(source: str, key: str) -> str:
    """候选 id:来源 + 来源内的键,稳定、可读前缀、定长。"""
    digest = hashlib.sha1(f"{source}:{key}".encode("utf-8")).hexdigest()[:12]
    return f"cand_{source}_{digest}"


@dataclass
class Candidate:
    candidate_id: str
    source: str
    key: str
    name: str = ""
    aip_device_type: str = "unknown"
    addresses: List[str] = field(default_factory=list)
    identity: Dict[str, str] = field(default_factory=dict)
    properties: Dict[str, Any] = field(default_factory=dict)
    capabilities: List[str] = field(default_factory=list)
    status: str = CandidateStatus.NEW.value
    join_path: str = ""  # 能接它的那条路径的名字;空 = 目前没有路径(见 needs)
    human_step: str = HumanStep.NONE.value
    #: 需要人时:要做什么(给人看)+ 需要哪些输入(给智能体/面板构造表单)
    needs: Dict[str, Any] = field(default_factory=dict)
    linked_device_id: str = ""  # 接入后 / 认领到的成员
    present: bool = True
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Candidate":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class MemberRecord:
    """一个成员的持久身份(不含在线态 —— 那归 UCM)。"""

    device_id: str
    device_name: str = ""
    device_type: str = "unknown"  # 粗类
    aip_device_type: str = ""
    transport: str = ""
    bridge_id: str = ""
    execution_model: str = ""
    capabilities: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    join_path: str = ""
    candidate_id: str = ""
    joined_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "MemberRecord":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})

    def registration_dict(self) -> Dict[str, Any]:
        """交给 ``UDM.register_device_from_dict`` 的那一份。"""
        return {
            "device_name": self.device_name or self.device_id,
            "device_type": self.aip_device_type or self.device_type,
            "capabilities": list(self.capabilities),
            "transport": self.transport,
            "bridge_id": self.bridge_id,
            "execution_model": self.execution_model,
            "source": "onboarding",
            "join_path": self.join_path,
            **dict(self.metadata),
        }


@dataclass
class JoinOutcome:
    """一次接入尝试的结果。三选一。"""

    kind: str  # joined / needs_human / failed
    device_id: str = ""
    member: Optional[MemberRecord] = None
    human_step: str = HumanStep.NONE.value
    #: needs_human 时:``{"what": 给人看的一句话, "inputs": [{name, label, required, ...}], ...}``
    needs: Dict[str, Any] = field(default_factory=dict)
    error: str = ""

    @classmethod
    def joined(cls, member: MemberRecord) -> "JoinOutcome":
        return cls(kind="joined", device_id=member.device_id, member=member)

    @classmethod
    def ask(cls, step: HumanStep, what: str, **extra: Any) -> "JoinOutcome":
        return cls(kind="needs_human", human_step=step.value, needs={"what": what, **extra})

    @classmethod
    def fail(cls, error: str) -> "JoinOutcome":
        return cls(kind="failed", error=error)

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"kind": self.kind}
        if self.device_id:
            out["device_id"] = self.device_id
        if self.kind == "needs_human":
            out["human_step"] = self.human_step
            out["needs"] = self.needs
        if self.error:
            out["error"] = self.error
        return out
