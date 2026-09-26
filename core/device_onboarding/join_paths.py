"""core/device_onboarding/join_paths.py — 接入路径:一类设备怎么变成成员。

每条路径是一个类,声明它能接哪种候选、要人做什么,以及怎么接。**新增一种设备 =
新增一条路径类 + ``register_join_path()`` 一行**,接入服务本身不改。

路径只负责"接",不负责"登记":成功时返回 :class:`MemberRecord`,由接入服务统一写
UDM、花名册、在线通道、Mesh(见 service.py)。所以每条路径都拿不到、也不需要拿
UDM —— 登记口径只有一处。

有两种"成功"没有成员记录:经 Home Assistant 接入的集成与 Matter 设备。它们建好之后,
实体由 HA 桥按 ``bridge_id`` 逐个接入(见 core/ha_bridge.py),这里只报"接好了"。
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from core.device_onboarding import ha_client
from core.device_onboarding.models import Candidate, HumanStep, JoinOutcome, MemberRecord
from core.device_onboarding.taxonomy import classify_type

logger = logging.getLogger("Galaxy.Onboarding.JoinPaths")


class JoinPath:
    """接入路径的基类。子类覆盖 ``name`` / ``human_step`` / ``can_handle`` / ``join``。"""

    name = "base"
    human_step = HumanStep.NONE
    description = ""

    def can_handle(self, cand: Candidate) -> bool:  # pragma: no cover - 抽象
        raise NotImplementedError

    async def join(self, cand: Candidate, inputs: Dict[str, Any]) -> JoinOutcome:  # pragma: no cover - 抽象
        raise NotImplementedError


def _service_type(cand: Candidate) -> str:
    return str(cand.properties.get("service_type") or "")


# ── 开着本系统 App 的手机/手表、tailnet 里还没配对的机器 ──────────────────────────


class GalaxyPeerPath(JoinPath):
    """它自己讲 AIP,缺的只是"证明是你的"。签一个配对码,在那台设备上输入。

    设备上的确认不能由智能体代劳:否则局域网里任何一台装了 App 的设备都能被悄悄拉进来。
    设备领码成功(``/api/v1/pair/claim``)并连上网关后,会经正常登记路径成为成员,
    接入服务按地址把候选认领过去。
    """

    name = "galaxy_peer"
    human_step = HumanStep.CONFIRM_ON_DEVICE
    description = "在那台设备的 Galaxy App 里输入配对码"

    def can_handle(self, cand: Candidate) -> bool:
        return cand.source == "tailnet" or (cand.source == "mdns" and "_galaxy" in _service_type(cand))

    async def join(self, cand: Candidate, inputs: Dict[str, Any]) -> JoinOutcome:
        from core.agent_card import build_local_card, get_pairing_code_registry, to_link

        link = to_link(build_local_card())
        code, expires_at = get_pairing_code_registry().issue(link)
        who = cand.name or "那台设备"
        return JoinOutcome.ask(
            HumanStep.CONFIRM_ON_DEVICE,
            f"在「{who}」的 Galaxy App 接入页输入配对码 {code}(10 分钟内有效,只能用一次)",
            code=code,
            link=link,
            expires_at=expires_at,
        )


# ── NATS 上注册的 Go edge worker ─────────────────────────────────────────────────


class EdgeWorkerPath(JoinPath):
    """一台跑着 edge worker 的电脑。它已经在 tailnet + NATS 上,点一下同意就成为成员。"""

    name = "edge_worker"
    human_step = HumanStep.APPROVE
    description = "同意这台电脑作为执行成员加入"

    def can_handle(self, cand: Candidate) -> bool:
        return cand.source == "nats_worker"

    async def join(self, cand: Candidate, inputs: Dict[str, Any]) -> JoinOutcome:
        info = classify_type(cand.aip_device_type)
        props = dict(cand.properties)
        return JoinOutcome.joined(
            MemberRecord(
                device_id=cand.key,
                device_name=cand.name or cand.key,
                device_type=info.platform,
                aip_device_type=info.aip_device_type,
                transport="nats",
                execution_model="partial_runtime_device",
                capabilities=list(cand.capabilities) or ["code_exec"],
                metadata={
                    "worker_id": cand.key,
                    "hostname": props.get("hostname", ""),
                    "platform": props.get("platform", ""),
                    "has_docker": bool(props.get("has_docker")),
                    "has_gpu": bool(props.get("has_gpu")),
                },
                join_path=self.name,
                candidate_id=cand.candidate_id,
            )
        )


# ── Home Assistant:它自己发现、等人确认的集成 ────────────────────────────────────

#: 看起来像"只有人手里才有"的字段名 —— 出现在表单里就是物理码类步骤。
_SECRET_FIELD = re.compile(r"pin|code|password|passcode|pairing|token|key", re.I)


def _form_inputs(schema: Any) -> List[Dict[str, Any]]:
    out = []
    for f in schema or []:
        if not isinstance(f, dict) or not f.get("name"):
            continue
        out.append(
            {
                "name": f["name"],
                "required": bool(f.get("required")),
                "type": f.get("type", "string"),
                **({"default": f["default"]} if "default" in f else {}),
            }
        )
    return out


async def advance_ha_flow(flow_id: str, inputs: Dict[str, Any], *, label: str = "") -> JoinOutcome:
    """把 HA 的一个配置流往前推。无字段的确认步自动走,要字段就告诉人要填什么。"""
    body: Dict[str, Any] = dict(inputs or {})
    for _ in range(4):  # 大多数流一两步;设上限防止对端异常时死循环
        try:
            step = await ha_client.ha_rest("POST", f"/api/config/config_entries/flow/{flow_id}", body)
        except ha_client.HAUnavailable as exc:
            return JoinOutcome.fail(exc.reason)
        kind = str(step.get("type", ""))
        if kind == "create_entry":
            title = step.get("title") or label or step.get("handler", "")
            return JoinOutcome(kind="joined", needs={"what": f"已在 Home Assistant 里添加「{title}」,设备会自动出现"})
        if kind == "abort":
            return JoinOutcome.fail(f"Home Assistant 中止了:{step.get('reason', '未知原因')}")
        if kind == "form":
            fields = _form_inputs(step.get("data_schema"))
            missing = [f for f in fields if f["required"] and f["name"] not in body and "default" not in f]
            if not missing and not (step.get("errors") or {}):
                body = {f["name"]: f["default"] for f in fields if "default" in f}
                continue
            secret = any(_SECRET_FIELD.search(f["name"]) for f in missing)
            return JoinOutcome.ask(
                HumanStep.PHYSICAL_CODE if secret else HumanStep.APPROVE,
                f"添加「{label or step.get('handler', '')}」需要填写:"
                + "、".join(f["name"] for f in missing or fields),
                inputs=missing or fields,
                errors=step.get("errors") or {},
                flow_id=flow_id,
            )
        # external / progress / menu:这一步只能在 HA 的界面里完成
        return JoinOutcome.ask(
            HumanStep.APPROVE,
            "这一步要在 Home Assistant 的界面里完成(设置 → 设备与服务)",
            url=f"{ha_client.ha_settings()['url']}/config/integrations",
            flow_id=flow_id,
        )
    return JoinOutcome.fail("Home Assistant 的配置流步数异常,已停止")


class HAFlowPath(JoinPath):
    name = "ha_flow"
    human_step = HumanStep.APPROVE
    description = "确认 Home Assistant 已发现的集成"

    def can_handle(self, cand: Candidate) -> bool:
        return cand.source == "ha_flow"

    async def join(self, cand: Candidate, inputs: Dict[str, Any]) -> JoinOutcome:
        return await advance_ha_flow(cand.key, inputs, label=cand.name)


# ── Matter:配网码经 HA 的 Matter 集成 ────────────────────────────────────────────


class MatterViaHAPath(JoinPath):
    name = "matter_via_ha"
    human_step = HumanStep.PHYSICAL_CODE
    description = "输入设备上的 Matter 配网码"

    def can_handle(self, cand: Candidate) -> bool:
        return cand.source == "mdns" and _service_type(cand).startswith("_matterc")

    async def join(self, cand: Candidate, inputs: Dict[str, Any]) -> JoinOutcome:
        code = str(inputs.get("code") or "").strip()
        if not code:
            return JoinOutcome.ask(
                HumanStep.PHYSICAL_CODE,
                "需要设备上的 Matter 配网码(贴纸或二维码:MT: 开头,或 11 位数字)",
                inputs=[{"name": "code", "required": True, "type": "string"}],
            )
        if not ha_client.ha_configured():
            return JoinOutcome.fail(
                "Matter 设备经 Home Assistant 入网:先在面板填 HA 地址和令牌,并在 HA 里装 Matter 集成"
            )
        try:
            await ha_client.ha_ws_command({"type": "matter/commission", "code": code})
        except ha_client.HAUnavailable as exc:
            return JoinOutcome.fail(exc.reason)
        return JoinOutcome(kind="joined", needs={"what": "已交给 Home Assistant 入网,设备会自动出现"})


# ── 其他局域网设备(投屏、HomeKit、UPnP):经 HA 的对应集成 ───────────────────────

#: mDNS 服务类型 / SSDP 设备类型 → HA 集成名(用于在 HA 已发现的流里找到它)。
_HA_HANDLER_BY_SERVICE = {
    "_googlecast": "cast",
    "_hap": "homekit_controller",
    "_matter._tcp": "matter",
    "_ipp": "ipp",
    "_printer": "ipp",
    "_airplay": "apple_tv",
    "_spotify-connect": "spotify",
    "_sonos": "sonos",
    "_hue": "hue",
    "_esphomelib": "esphome",
    "_shelly": "shelly",
    "_miio": "xiaomi_miio",
    "_elg": "elgato",
    "_wled": "wled",
    "_androidtvremote2": "androidtv_remote",
    "mediarenderer": "dlna_dmr",
    "mediaserver": "dlna_dms",
    "internetgatewaydevice": "upnp",
}


def ha_handler_for(cand: Candidate) -> str:
    key = (_service_type(cand) + " " + str(cand.properties.get("device_type_urn", ""))).lower()
    for needle, handler in _HA_HANDLER_BY_SERVICE.items():
        if needle in key:
            return handler
    return ""


class ViaHomeAssistantPath(JoinPath):
    """局域网里能看见、但本系统没有专门驱动的设备:交给 HA 那 3000 多种集成。

    做法:在 HA 已发现、待确认的流里找到它(按名字或集成名),推进那个流。
    HA 还没发现它时,如实告诉人去 HA 里加哪个集成。
    """

    name = "via_home_assistant"
    human_step = HumanStep.APPROVE
    description = "经 Home Assistant 的对应集成接入"

    def can_handle(self, cand: Candidate) -> bool:
        return cand.source in ("mdns", "ssdp")

    async def join(self, cand: Candidate, inputs: Dict[str, Any]) -> JoinOutcome:
        handler = ha_handler_for(cand)
        if not ha_client.ha_configured():
            return JoinOutcome.ask(
                HumanStep.APPROVE,
                "这类设备经 Home Assistant 接入:先在面板「设备」里填 HA 地址和令牌",
                ha_integration=handler,
            )
        flow_id = str(inputs.get("flow_id") or "") or await self._find_flow(cand, handler)
        if not flow_id:
            return JoinOutcome.ask(
                HumanStep.APPROVE,
                f"Home Assistant 还没发现「{cand.name}」"
                + (f";在 HA 里添加「{handler}」集成后再接一次" if handler else ";在 HA 里添加对应集成后再接一次"),
                ha_integration=handler,
                url=f"{ha_client.ha_settings()['url']}/config/integrations",
            )
        return await advance_ha_flow(flow_id, {k: v for k, v in inputs.items() if k != "flow_id"}, label=cand.name)

    @staticmethod
    async def _find_flow(cand: Candidate, handler: str) -> str:
        try:
            flows = await ha_client.ha_rest("GET", "/api/config/config_entries/flow")
        except ha_client.HAUnavailable:
            return ""
        name = (cand.name or "").strip().lower()
        hosts = {a.lower() for a in cand.addresses}
        same_handler = [f for f in flows or [] if not handler or f.get("handler") == handler]
        for f in same_handler:
            ctx = f.get("context") or {}
            placeholders = {str(v).lower() for v in (ctx.get("title_placeholders") or {}).values()}
            if (name and any(name in p or p in name for p in placeholders if p)) or (hosts & placeholders):
                return str(f.get("flow_id", ""))
        return str(same_handler[0].get("flow_id", "")) if len(same_handler) == 1 else ""


# ── 注册表 ──────────────────────────────────────────────────────────────────────

_REGISTRY: List[JoinPath] = []


def register_join_path(path: JoinPath, *, first: bool = False) -> None:
    """登记一条路径。``first=True`` 放到最前(更专门的路径应先于泛化路径被选中)。"""
    global _REGISTRY
    _REGISTRY = [p for p in _REGISTRY if p.name != path.name]
    if first:
        _REGISTRY.insert(0, path)
    else:
        _REGISTRY.append(path)


def find_join_path(cand: Candidate) -> Optional[JoinPath]:
    for p in _REGISTRY:
        try:
            if p.can_handle(cand):
                return p
        except Exception as exc:  # noqa: BLE001 — 一条路径判断出错不影响其余
            logger.debug("接入路径 %s 判断失败: %s", p.name, exc)
    return None


def get_join_path(name: str) -> Optional[JoinPath]:
    return next((p for p in _REGISTRY if p.name == name), None)


def list_join_paths() -> List[Dict[str, str]]:
    return [{"name": p.name, "human_step": p.human_step.value, "description": p.description} for p in _REGISTRY]


# 顺序即优先级:专门的在前,"经 HA"这条兜底在最后。
for _p in (MatterViaHAPath(), GalaxyPeerPath(), EdgeWorkerPath(), HAFlowPath(), ViaHomeAssistantPath()):
    register_join_path(_p)
