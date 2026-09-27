"""core/device_onboarding/drivers.py — 被接入设备的 MCP 驱动:绑定、按种类复用、在已装的里找。

三件事,都围绕「这台设备用哪个 MCP 工具来控制」:

**绑定** :func:`bind_member`
    把一个 MCP 工具认作某个候选的驱动,候选以 ``bridge_id=mcp:<tool>`` 成为成员;
    ``devices__invoke`` 按这个前缀把调用交给 MCP 网关。

**按种类复用** :class:`DriverBook` + :class:`KnownDriverPath`
    每绑定一次,记下「这一种设备 → 这个工具」(持久化)。之后再发现同一种设备,
    它就有了一条接入路径「用已知驱动」,只要人点个头(``GALAXY_ONBOARDING_AUTO=approve``
    时自动)。「同一种」按来源给出的型号信息判断;说不清是什么型号的(只知道 unknown/iot)
    不记 —— 猜错了等于拿一台设备的驱动去控另一台。

**在已装的里找** :func:`search_installed`
    智能体想给某台设备找驱动时,先看已经装好的 MCP 工具里有没有对得上的,
    按名字/描述/标签与设备信息的重合度排序,再考虑去 GitHub 装或让模型写。
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

from core.device_onboarding.join_paths import JoinPath, register_join_path
from core.device_onboarding.models import Candidate, HumanStep, JoinOutcome, MemberRecord
from core.device_onboarding.store import JsonRecordStore
from core.device_onboarding.taxonomy import classify_type

logger = logging.getLogger("Galaxy.Onboarding.Drivers")

#: 这些类型本身说明不了「是哪一种设备」,不能单凭它们复用驱动。
_VAGUE_TYPES = frozenset({"", "unknown", "iot"})


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")[:40] or "device"


def kind_key(cand: Candidate) -> Optional[str]:
    """这台设备属于「哪一种」。说不清时返回 None(不复用)。

    型号信息按来源取:SSDP 的 Server 头与设备类型 URN、mDNS 的服务类型与 TXT 里的型号。
    """
    p = cand.properties or {}
    model = " ".join(
        str(p.get(k) or "").strip()
        for k in ("server", "device_type_urn", "service_type", "model", "md", "manufacturer")
        if str(p.get(k) or "").strip()
    )
    model = re.sub(r"\s+", " ", model).strip().lower()
    if not model and cand.aip_device_type in _VAGUE_TYPES:
        return None
    if not model:
        return None
    return f"{cand.source}|{cand.aip_device_type}|{model}"


@dataclass
class DriverRecord:
    kind: str
    tool: str
    example: str = ""
    bound_at: float = 0.0
    times: int = 0


class DriverBook:
    """「一种设备 → 控制它的 MCP 工具」,持久化在接入平面的状态目录。"""

    def __init__(self) -> None:
        self.store: JsonRecordStore[DriverRecord] = JsonRecordStore(
            "onboarding_drivers.json", to_dict=asdict, from_dict=lambda d: DriverRecord(**d)
        )

    def remember(self, cand: Candidate, tool: str) -> Optional[str]:
        key = kind_key(cand)
        if not key or not tool:
            return None
        rec = self.store.get(key) or DriverRecord(kind=key, tool=tool, example=cand.name)
        rec.tool, rec.bound_at, rec.times = tool, time.time(), rec.times + 1
        rec.example = rec.example or cand.name
        self.store.put(key, rec)
        return key

    def lookup(self, cand: Candidate) -> Optional[DriverRecord]:
        key = kind_key(cand)
        return self.store.get(key) if key else None


_book: Optional[DriverBook] = None


def get_driver_book() -> DriverBook:
    global _book
    if _book is None:
        _book = DriverBook()
    return _book


def reset_driver_book() -> None:
    global _book
    _book = None


# ── 绑定 ─────────────────────────────────────────────────────────────────────────


def member_for(cand: Candidate, tool: str) -> MemberRecord:
    info = classify_type(cand.aip_device_type)
    return MemberRecord(
        device_id=f"dev_{_slug(cand.name or cand.key)}_{cand.candidate_id[-6:]}",
        device_name=cand.name or cand.key,
        device_type=info.platform,
        aip_device_type=info.aip_device_type,
        transport="mcp",
        bridge_id=f"mcp:{tool}",
        capabilities=list(cand.capabilities) or ["invoke"],
        metadata={"driver_mcp_tool": tool, "addresses": cand.addresses, "driver_device": dict(cand.identity)},
        join_path="mcp_driver",
        candidate_id=cand.candidate_id,
    )


def bind_member(cand: Candidate, tool: str, svc: Any) -> MemberRecord:
    """把 *tool* 认作 *cand* 的驱动并接入;同时记下这一种设备用它。"""
    from core.device_onboarding.models import CandidateStatus

    member = member_for(cand, tool)
    svc.admit(member)
    cand.status = CandidateStatus.JOINED.value
    cand.linked_device_id = member.device_id
    svc.candidates.put(cand.candidate_id, cand)
    get_driver_book().remember(cand, tool)
    return member


class KnownDriverPath(JoinPath):
    """同一种设备以前接过:直接用那次的驱动。要人点头(可由 AUTO=approve 放行)。"""

    name = "known_mcp_driver"
    human_step = HumanStep.APPROVE
    description = "这种设备以前接过,用同一个驱动"

    def can_handle(self, cand: Candidate) -> bool:
        return get_driver_book().lookup(cand) is not None

    async def join(self, cand: Candidate, inputs: Dict[str, Any]) -> JoinOutcome:
        rec = get_driver_book().lookup(cand)
        if rec is None:
            return JoinOutcome.fail("这种设备的驱动记录不见了")
        member = member_for(cand, rec.tool)
        get_driver_book().remember(cand, rec.tool)
        return JoinOutcome.joined(member)


# 比「经 HA」「HA 集成」这些泛化路径更专门:已经知道用哪个驱动了,就先用它。
register_join_path(KnownDriverPath(), first=True)


# ── 在已装的里找 ─────────────────────────────────────────────────────────────────

_STOP = frozenset(
    {"the", "a", "an", "and", "of", "for", "to", "device", "devices", "control", "upnp", "linux", "http", "1", "0"}
)


def _terms(*texts: str) -> set:
    out = set()
    for t in texts:
        for w in re.split(r"[^0-9a-z一-鿿]+", (t or "").lower()):
            if len(w) >= 2 and w not in _STOP and not w.isdigit():
                out.add(w)
    return out


def _candidate_terms(cand: Candidate) -> set:
    p = cand.properties or {}
    return _terms(
        cand.name,
        cand.aip_device_type.replace("_", " "),
        str(p.get("server") or ""),
        str(p.get("device_type_urn") or "").replace(":", " "),
        str(p.get("model") or ""),
        str(p.get("manufacturer") or ""),
    )


async def search_installed(cand: Candidate, limit: int = 5) -> List[Dict[str, Any]]:
    """已装的 MCP 工具里,哪些可能控制得了这台设备。按重合度从高到低。"""
    want = _candidate_terms(cand)
    if not want:
        return []
    rows: List[Dict[str, Any]] = []
    try:
        from core.mcp_gateway import get_mcp_gateway

        gw = get_mcp_gateway()
        tools = await gw.list_all_tools()
        for t in tools:
            have = _terms(t.name, t.description, t.server_name, " ".join(t.tags or []))
            hit = sorted(want & have)
            if hit:
                rows.append({"tool": t.name, "server": t.server_name, "score": len(hit), "matched": hit})
        for name, rec in (getattr(gw, "_generated_tools", {}) or {}).items():
            manifest = rec.get("manifest") or {}
            have = _terms(name, str(manifest.get("description") or ""), " ".join(manifest.get("tags") or []))
            hit = sorted(want & have)
            if hit and all(r["tool"] != name for r in rows):
                rows.append({"tool": name, "server": rec.get("source", ""), "score": len(hit), "matched": hit})
    except Exception as exc:  # noqa: BLE001 — 找不到就是没有,不让工具调用失败
        logger.debug("查已装驱动失败: %s", exc)
    rows.sort(key=lambda r: (-r["score"], r["tool"]))
    return rows[:limit]
