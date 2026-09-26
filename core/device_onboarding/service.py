"""core/device_onboarding/service.py — 接入服务:候选 → 成员 这一段的唯一编排处。

``observe()``  发现来源看见了东西 → 认领已有成员,或记成候选(不进 UDM)。
``join()``     接一个候选:选路径、执行、按结果推进候选状态;成了就 ``admit()``。
``admit()``    成员登记的唯一口径:UDM(身份)+ 花名册(持久)+ Mesh 编入。
``remove()``   移除成员:UDM、花名册、在线通道、tailnet 身份、Mesh、配对簿一并收回。
``overview()`` 成员(按角色分组、在线通道、驱动)+ 候选 —— 面板与智能体工具读同一份。

在线态不在这里:它归 UCM(``report_presence``),发现来源自己报。
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, List, Optional

from core.device_onboarding.join_paths import find_join_path, get_join_path, list_join_paths
from core.device_onboarding.models import (
    AUTOMATABLE,
    Candidate,
    CandidateStatus,
    HumanStep,
    JoinOutcome,
    MemberRecord,
    Observation,
    candidate_id_for,
)
from core.device_onboarding.store import JsonRecordStore
from core.device_onboarding.taxonomy import (
    ADAPTER_BRIDGED_DEVICE,
    FULL_RUNTIME_HOST,
    OBSERVER_TELEMETRY_DEVICE,
    ROLE_LABELS,
    can_initiate,
    classify_type,
    is_native_transport,
)

logger = logging.getLogger("Galaxy.Onboarding")

#: 自动接入到哪一级:off = 全等人;none = 只自动走不需要人的;approve = 连"同意"类也自动。
AUTO_LEVELS = ("off", "none", "approve")


def onboarding_enabled() -> bool:
    return os.getenv("GALAXY_ONBOARDING_ENABLED", "true").strip().lower() not in ("0", "false", "no", "off")


def auto_level() -> str:
    v = os.getenv("GALAXY_ONBOARDING_AUTO", "none").strip().lower()
    return v if v in AUTO_LEVELS else "none"


def _auto_allows(step: str) -> bool:
    level = auto_level()
    if level == "off":
        return False
    allowed = {HumanStep.NONE.value} | ({HumanStep.APPROVE.value} if level == "approve" else set())
    # 物理码、设备上确认、执行命令 永远不在自动化范围内 —— 不看配置。
    return step in allowed and step in {s.value for s in AUTOMATABLE}


def _udm():
    from core.unified.device_manager import get_unified_device_manager

    return get_unified_device_manager()


def _ucm():
    from core.unified.connection_manager import get_unified_connection_manager

    return get_unified_connection_manager()


def mesh_roles_for(classes: List[str]) -> List[Any]:
    """能力类 → Mesh 角色(感知 / 执行 / 在场)。"""
    from core.mesh.body_mesh_registry import DeviceRole

    cls = set(classes)
    roles = []
    if cls & {
        "SENSOR_CAMERA",
        "SENSOR_MIC",
        "SENSOR_MOTION",
        "SENSOR_GPS",
        "HOME_SENSOR",
        "GUI_READ",
        "GUI_SCREENSHOT",
    }:
        roles.append(DeviceRole.PERCEPTION)
    if any(c.startswith(("GUI_WRITE", "INPUT_", "SYSTEM_SHELL", "HOME_", "COMPUTE")) for c in cls - {"HOME_SENSOR"}):
        roles.append(DeviceRole.ACTION)
    if cls & {"SYSTEM_NOTIFICATION", "GUI_STREAM", "HOME_MEDIA"}:
        roles.append(DeviceRole.PRESENCE)
    return roles


def _role_group(execution_model: str) -> str:
    if execution_model == FULL_RUNTIME_HOST:
        return "subjects"
    if execution_model == ADAPTER_BRIDGED_DEVICE:
        return "bridged"
    if execution_model == OBSERVER_TELEMETRY_DEVICE:
        return "observers"
    return "members"


class OnboardingService:
    def __init__(self) -> None:
        self.candidates: JsonRecordStore[Candidate] = JsonRecordStore(
            "onboarding_candidates.json", to_dict=Candidate.to_dict, from_dict=Candidate.from_dict
        )
        self.roster: JsonRecordStore[MemberRecord] = JsonRecordStore(
            "onboarding_members.json", to_dict=MemberRecord.to_dict, from_dict=MemberRecord.from_dict
        )
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._tasks: set = set()

    # ── 生命周期 ────────────────────────────────────────────────────────

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """发现来源常在别的线程回调(zeroconf);自动接入要回到这个事件循环上跑。"""
        self._loop = loop

    def rehydrate(self) -> int:
        """把花名册里的成员以**离线**身份回灌 UDM。身份 ≠ 在线:在线等来源来报。"""
        from core.unified.models import UnifiedDeviceStatus

        udm = _udm()
        n = 0
        for rec in self.roster.values():
            if udm.get_device(rec.device_id) is not None:
                continue
            try:
                udm.register_device_from_dict(rec.device_id, rec.registration_dict())
                udm.update_device_status(rec.device_id, UnifiedDeviceStatus.OFFLINE)
                n += 1
            except Exception as exc:  # noqa: BLE001 — 一台回灌失败不影响其余
                logger.warning("成员 %s 回灌失败: %s", rec.device_id, exc)
        if n:
            logger.info("已把 %d 个成员回灌进设备表(离线,等来源报在线)", n)
        return n

    # ── 发现 ────────────────────────────────────────────────────────────

    def link(self, obs: Observation) -> Optional[str]:
        """看它是不是已有成员。强标识优先,地址最后;对不上不猜。"""
        udm = _udm()
        ident = {k: str(v) for k, v in (obs.identity or {}).items() if v}
        for key in ("device_id", "worker_id"):
            if ident.get(key) and udm.get_device(ident[key]) is not None:
                return ident[key]
        if ident.get("ha_entity_id") and udm.get_device(f"ha_{ident['ha_entity_id']}") is not None:
            return f"ha_{ident['ha_entity_id']}"
        ips = {ident.get("ip", "")} | set(obs.addresses or [])
        ips.discard("")
        if ips and obs.source in ("mdns", "ssdp", "tailnet"):
            for d in udm.list_devices():
                meta = d.metadata or {}
                if str(getattr(d, "bridge_id", "") or ""):
                    continue
                if {str(d.ip_address or ""), str(meta.get("ip", "")), str(meta.get("remote_ip", ""))} & ips:
                    return d.device_id
        return None

    def observe(self, obs: Observation) -> Optional[Candidate]:
        """发现来源的唯一入口。返回候选(已是成员时返回 None)。"""
        if not onboarding_enabled() or not obs.key:
            return None
        cid = candidate_id_for(obs.source, obs.key)
        existing = self.candidates.get(cid)
        linked = self.link(obs)
        if linked:
            if existing and existing.status != CandidateStatus.JOINED.value:
                existing.status = CandidateStatus.JOINED.value
                existing.linked_device_id = linked
                existing.last_seen = time.time()
                self.candidates.put(cid, existing)
            return None

        now = time.time()
        if existing is None:
            info = classify_type(obs.kind_hint, hints=obs.properties)
            cand = Candidate(
                candidate_id=cid,
                source=obs.source,
                key=obs.key,
                name=obs.name or obs.key,
                aip_device_type=info.aip_device_type,
                first_seen=now,
            )
        else:
            cand = existing
        cand.last_seen = now
        cand.present = bool(obs.present)
        if obs.name:
            cand.name = obs.name
        cand.addresses = list(obs.addresses or cand.addresses)
        cand.identity = {**cand.identity, **{k: str(v) for k, v in (obs.identity or {}).items() if v}}
        cand.properties = {**cand.properties, **(obs.properties or {})}
        if obs.capabilities:
            cand.capabilities = list(obs.capabilities)
        if cand.status in (CandidateStatus.NEW.value, CandidateStatus.FAILED.value) or not cand.join_path:
            path = find_join_path(cand)
            cand.join_path = path.name if path else ""
            cand.human_step = path.human_step.value if path else HumanStep.NONE.value
            if not path:
                cand.needs = {"what": "还没有能接入这类设备的路径;可以让智能体找一个驱动(MCP/技能)"}
        self.candidates.put(cid, cand)

        if (
            existing is None
            and cand.present
            and cand.join_path
            and _auto_allows(cand.human_step)
            and cand.status == CandidateStatus.NEW.value
        ):
            self._schedule(self.join(cid))
        return cand

    def _schedule(self, coro: Any) -> None:
        loop = self._loop
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                coro.close()
                return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            t = loop.create_task(coro)
            self._tasks.add(t)
            t.add_done_callback(self._tasks.discard)
        else:
            asyncio.run_coroutine_threadsafe(coro, loop)

    # ── 接入 ────────────────────────────────────────────────────────────

    async def join(self, candidate_id: str, inputs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        cand = self.candidates.get(candidate_id)
        if cand is None:
            return {"success": False, "error": f"没有这个候选:{candidate_id}"}
        if cand.status == CandidateStatus.JOINED.value:
            return {"success": True, "candidate": cand.to_dict(), "outcome": {"kind": "joined", "already": True}}
        path = get_join_path(cand.join_path) or find_join_path(cand)
        if path is None:
            return {
                "success": False,
                "candidate": cand.to_dict(),
                "error": cand.needs.get("what") or "没有可用的接入路径",
            }
        cand.status = CandidateStatus.JOINING.value
        self.candidates.put(candidate_id, cand)
        try:
            outcome = await path.join(cand, dict(inputs or {}))
        except Exception as exc:  # noqa: BLE001 — 路径实现的意外错误也要落到候选上,不能卡在 joining
            logger.warning("接入 %s 失败(%s): %s", candidate_id, path.name, exc)
            outcome = JoinOutcome.fail(f"{path.name} 出错:{exc}")

        if outcome.kind == "joined":
            cand.status = CandidateStatus.JOINED.value
            cand.error = ""
            cand.needs = dict(outcome.needs or {})
            if outcome.member is not None:
                self.admit(outcome.member)
                cand.linked_device_id = outcome.member.device_id
        elif outcome.kind == "needs_human":
            cand.status = CandidateStatus.NEEDS_HUMAN.value
            cand.human_step = outcome.human_step
            cand.needs = dict(outcome.needs)
        else:
            cand.status = CandidateStatus.FAILED.value
            cand.error = outcome.error
        self.candidates.put(candidate_id, cand)
        logger.info("接入 %s 经 %s → %s", cand.name, path.name, outcome.kind)
        return {"success": outcome.kind != "failed", "candidate": cand.to_dict(), "outcome": outcome.to_dict()}

    def ignore(self, candidate_id: str) -> Dict[str, Any]:
        cand = self.candidates.get(candidate_id)
        if cand is None:
            return {"success": False, "error": f"没有这个候选:{candidate_id}"}
        cand.status = CandidateStatus.IGNORED.value
        self.candidates.put(candidate_id, cand)
        return {"success": True, "candidate": cand.to_dict()}

    def admit(self, member: MemberRecord, *, persist: bool = True) -> Any:
        """成员登记的唯一口径。"""
        device = _udm().register_device_from_dict(member.device_id, member.registration_dict())
        if persist:
            member.aip_device_type = device.aip_device_type
            member.execution_model = device.execution_model
            self.roster.put(member.device_id, member)
        try:
            from core.mesh.mesh_auto_enrollment import get_auto_enrollment_service

            get_auto_enrollment_service().on_device_registered(
                member.device_id,
                roles=mesh_roles_for(device.capability_classes),
                metadata={"join_path": member.join_path, "execution_model": device.execution_model},
            )
        except Exception as exc:  # noqa: BLE001 — Mesh 编入失败不影响成员身份
            logger.debug("Mesh 编入 %s 跳过: %s", member.device_id, exc)
        return device

    async def remove(self, device_id: str) -> Dict[str, Any]:
        """移除成员:该收回的都收回,并如实报告每一项做没做成。"""
        done: Dict[str, Any] = {"device_id": device_id}
        done["roster"] = self.roster.pop(device_id) is not None
        udm = _udm()
        known = udm.get_device(device_id)
        device_dict = {"device_id": device_id, "remote_ip": getattr(known, "ip_address", "") or ""} if known else None
        if known is not None:
            udm.unregister_device(device_id)
        done["device_table"] = known is not None
        _ucm().clear_presence(device_id)
        try:
            from core.tailnet_membership import forget_device

            done["tailnet"] = await asyncio.to_thread(forget_device, device_id, device_dict)
        except Exception as exc:  # noqa: BLE001
            done["tailnet"] = {"tailnet_removed": False, "reason": str(exc)}
        try:
            from core.peer_trust import get_peer_trust_book

            done["pairing"] = bool(get_peer_trust_book().remove(device_id))
        except Exception as exc:  # noqa: BLE001
            done["pairing"] = False
            logger.debug("配对簿移除 %s 跳过: %s", device_id, exc)
        try:
            from core.mesh.mesh_auto_enrollment import get_auto_enrollment_service

            get_auto_enrollment_service().on_device_lost(device_id)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Mesh 退出 %s 跳过: %s", device_id, exc)
        # 指向它的候选一并清掉,之后再被看见就是一个新候选
        for c in self.candidates.values():
            if c.linked_device_id == device_id:
                self.candidates.pop(c.candidate_id)
        done["success"] = bool(done["roster"] or done["device_table"])
        return done

    # ── 总览(面板与智能体读同一份) ───────────────────────────────────────

    def _driver_for(self, d: Any) -> Dict[str, Any]:
        if is_native_transport(getattr(d, "transport", "")):
            return {"kind": "native"}
        try:
            from core.device_node_resolver import get_resolver

            m = get_resolver().resolve(
                device_type=d.aip_device_type or None,
                transport=d.transport or None,
                capabilities=list(d.capability_classes or []),
            )
        except Exception:  # noqa: BLE001
            m = None
        return {"kind": "node", "node": m.implementation.node} if m else {"kind": "none"}

    def member_view(self, d: Any) -> Dict[str, Any]:
        from contracts.registered_runtime_device import from_udm_device

        rrd = from_udm_device(d)
        ucm = _ucm()
        channels = ucm.channel_presence(d.device_id)
        online = any(c.get("online") for c in channels.values()) if channels else bool(rrd.online)
        rec = self.roster.get(d.device_id)
        model = str(getattr(d, "execution_model", "") or "")
        return {
            "device_id": d.device_id,
            "name": d.device_name or d.device_id,
            "type": d.aip_device_type or str(d.device_type),
            "form_factor": d.form_factor,
            "role": model,
            "role_label": ROLE_LABELS.get(model, "成员"),
            "can_initiate": can_initiate(model),
            "online": online,
            "channels": {k: bool(v.get("online")) for k, v in channels.items()},
            # 最近一次任一通道报到的时间(秒);0 = 从没报到过
            "last_seen": max((float(v.get("last_seen") or 0.0) for v in channels.values()), default=0.0),
            "capability_classes": list(d.capability_classes or []),
            "capabilities": list(d.capabilities or []),
            "bridge_id": d.bridge_id,
            "transport": d.transport,
            "driver": self._driver_for(d),
            "join_path": rec.join_path if rec else "",
            "remembered": rec is not None,
        }

    def overview(self, *, include_ignored: bool = False) -> Dict[str, Any]:
        groups: Dict[str, List[Dict[str, Any]]] = {"subjects": [], "members": [], "bridged": [], "observers": []}
        for d in _udm().list_devices():
            v = self.member_view(d)
            groups[_role_group(v["role"])].append(v)
        for g in groups.values():
            g.sort(key=lambda v: (not v["online"], v["name"]))

        cands = []
        ignored = 0
        for c in self.candidates.values():
            if c.status == CandidateStatus.JOINED.value:
                continue
            if c.status == CandidateStatus.IGNORED.value:
                ignored += 1
                if not include_ignored:
                    continue
            cands.append(c.to_dict())
        cands.sort(key=lambda c: (not c["present"], -c["last_seen"]))
        members_all = [v for g in groups.values() for v in g]
        return {
            "groups": groups,
            "candidates": cands,
            "summary": {
                "members": len(members_all),
                "online": sum(1 for v in members_all if v["online"]),
                "candidates": len([c for c in cands if c["status"] != CandidateStatus.IGNORED.value]),
                "needs_human": sum(1 for c in cands if c["status"] == CandidateStatus.NEEDS_HUMAN.value),
                "ignored": ignored,
            },
            "auto_level": auto_level(),
            "join_paths": list_join_paths(),
        }


_service: Optional[OnboardingService] = None


def get_onboarding_service() -> OnboardingService:
    global _service
    if _service is None:
        _service = OnboardingService()
    return _service


def reset_onboarding_service() -> None:
    """测试用。"""
    global _service
    _service = None
