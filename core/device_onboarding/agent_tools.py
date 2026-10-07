"""core/device_onboarding/agent_tools.py — 智能体的设备工具族 ``devices__*``。

智能体此前没有任何设备工具:能力总线里登记了每台设备的能力,可工具收集只收
MCP/技能/节点;资源表里从没放进过设备。这里不把几百个 ``device__<id>__<cap>``
灌进上下文,而是给一组元工具,对着同一份总览(``OnboardingService.overview``)工作:

    devices__list            成员(按角色)+ 候选
    devices__join            接入一个候选(需要人时返回要做什么)
    devices__ignore          不再提示某个候选
    devices__remove          移除成员(该收回的都收回)
    devices__invoke          调某台设备的一个动作(按它是原生/桥接/驱动节点/MCP 驱动分别路由)
    devices__invite          邀请一台新设备(手机/手表:配对码;笔记本:配对码 + 一条命令;worker:进网 + 启动命令)
    devices__acquire_driver  没有接入路径的候选:装一个 MCP 驱动(GitHub),或让模型写一个
    devices__bind_driver     把某个 MCP 工具认作这个候选的驱动,接入为成员

哪些步骤要人:
* 同意类(接入 edge worker、确认 HA 集成、移除成员)—— 在手表上问(fail-closed),
  除非 ``GALAXY_ONBOARDING_AUTO=approve``(移除永远要问);
* 物理码、设备上确认、执行命令 —— 智能体做不了,如实返回"要人做什么";
* 生成驱动代码 —— 永远要问。
"""

from __future__ import annotations

import logging
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional

from core.device_onboarding.gateway_address import gateway_http_base
from core.device_onboarding.mode_request import REQUEST_ACTION, dispatch_mode_tool, mode_request_tools
from core.device_onboarding.models import CandidateStatus, HumanStep
from core.device_onboarding.service import _auto_allows, get_onboarding_service, onboarding_enabled
from core.device_onboarding.taxonomy import is_native_transport

logger = logging.getLogger("Galaxy.Onboarding.AgentTools")


def _fn(name: str, description: str, properties: Dict[str, Any], required: Optional[List[str]] = None) -> Dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required or []},
        },
    }


DEVICES_BUILTIN_TOOLS: List[Dict[str, Any]] = [
    _fn(
        "devices__list",
        "List this system's devices: members grouped by role (subjects that can initiate, members, bridged "
        "devices such as smart-home entities, observers) with online status, capability classes and driver; "
        "plus candidates discovered nearby that are NOT members yet and what joining each would take.",
        {"include_ignored": {"type": "boolean", "description": "Also list candidates the user ignored."}},
    ),
    _fn(
        "devices__join",
        "Join a discovered candidate as a member. If a human step is needed (a pairing code to enter on the "
        "device, a physical setup code, a command to run) the result says exactly what to ask the user; call "
        "again with 'inputs' once they provide it.",
        {
            "candidate_id": {"type": "string"},
            "inputs": {
                "type": "object",
                "description": "Values the previous attempt asked for, e.g. {'code': 'MT:...'}",
            },
        },
        ["candidate_id"],
    ),
    _fn("devices__ignore", "Stop suggesting a candidate.", {"candidate_id": {"type": "string"}}, ["candidate_id"]),
    _fn(
        "devices__remove",
        "Remove a member: forget it, revoke its network identity and pairing. Asks the user on their watch first.",
        {"device_id": {"type": "string"}},
        ["device_id"],
    ),
    _fn(
        "devices__invoke",
        "Run one action on a member device (see its capabilities in devices__list). Routed by how the device "
        "is attached (native app, Home Assistant, driver node, MCP driver); permission gates still apply.",
        {
            "device_id": {"type": "string"},
            "action": {"type": "string"},
            "params": {"type": "object"},
        },
        ["device_id", "action"],
    ),
    _fn(
        "devices__invite",
        "Invite a new device the user wants to add. phone/watch: returns a one-time pairing code to enter in the "
        "Galaxy app. laptop: a Windows, macOS or Linux computer the user wants you to operate (screen, mouse, "
        "keyboard) — returns one command with a pairing code to run on it; it finds this system on the LAN, joins the "
        "private network, starts on login, and you will be told in the conversation when it connects. worker: a "
        "headless machine that only runs code jobs — it joins the message bus and starts taking jobs on its own, "
        "so it needs no onboarding and does not appear in the device list.",
        {"kind": {"type": "string", "enum": ["phone", "watch", "laptop", "worker"]}},
        ["kind"],
    ),
    _fn(
        "devices__acquire_driver",
        "For a candidate no join path can handle. With no arguments: search the MCP tools already installed for "
        "ones that match this device. source_url: install an MCP driver from GitHub. generate=true (asks the user "
        "first): have one written and sandbox-tested. Then call devices__bind_driver. Once a kind of device has "
        "a driver, later devices of the same kind can be joined with devices__join directly.",
        {
            "candidate_id": {"type": "string"},
            "source_url": {"type": "string", "description": "GitHub URL of an MCP server/skill that controls it"},
            "generate": {"type": "boolean"},
        },
        ["candidate_id"],
    ),
    _fn(
        "devices__bind_driver",
        "Use an installed MCP tool as the driver of a candidate and join it as a bridged member.",
        {"candidate_id": {"type": "string"}, "tool": {"type": "string", "description": "MCP tool name"}},
        ["candidate_id", "tool"],
    ),
]


def devices_tools_for_agent() -> List[Dict[str, Any]]:
    """要给智能体的设备工具：设备接入平面开着才有 ``devices__list`` 等；本地模式下另有「请求打开跨设备模式」
    （它**不挂在**接入开关底下 —— 那个开关是跨设备按钮的成员，按钮关着它也关着，见 mode_request.py）。"""
    return (list(DEVICES_BUILTIN_TOOLS) if onboarding_enabled() else []) + mode_request_tools()


# ── 人在环 ───────────────────────────────────────────────────────────────────────


async def _ask(what: str, session_id: str) -> Optional[Dict[str, Any]]:
    """问人要不要做。批准返回 None;否则返回该交回给智能体的结果。

    * 这件事已经在对话里问过 → 按用户这一回合的原话判(规则见 conversation.py);
    * 手表/手机连着 → 在手表上问(阻塞等回答,fail-closed),同时在对话里说一声问了什么;
    * 都没有 → 在对话里问:本次不执行,交回一句要问用户的话,用户答了之后原样再调一次。
    """
    from core.device_onboarding.conversation import announce_soon, confirm_in_conversation, is_pending

    def _in_conversation() -> Optional[Dict[str, Any]]:
        v = confirm_in_conversation(what, session_id)
        if v["state"] == "approved":
            return None
        if v["state"] == "denied":
            return {"success": False, "error": "用户在对话里说不要,没有执行"}
        return {
            "success": False,
            "needs_confirmation": True,
            "ask_user": v["ask_user"],
            "next": "把 ask_user 原样问用户;用户回答之后,用同样的参数再调一次这个工具",
        }

    if is_pending(what, session_id):
        return _in_conversation()
    try:
        from core.interaction.pending_decision_registry import _discover_target_devices

        watch_up = bool(await _discover_target_devices())
    except Exception:  # noqa: BLE001 — 探不到手表就在对话里问,不因此放行
        watch_up = False
    if not watch_up:
        return _in_conversation()

    from core.interaction.high_risk_confirmation import confirm_high_risk_tool

    announce_soon(f"我在手表上问你了:要{what}吗?")
    outcome = await confirm_high_risk_tool(tool_name=what, risk_level="设备接入", session_id=session_id)
    return None if outcome.approved else {"success": False, "error": f"没有执行:{outcome.reason}"}


# ── list ─────────────────────────────────────────────────────────────────────────


def _brief_member(v: Dict[str, Any]) -> Dict[str, Any]:
    return {
        k: v[k]
        for k in (
            "device_id",
            "name",
            "type",
            "role_label",
            "can_initiate",
            "online",
            "capability_classes",
            "capabilities",
        )
        if k in v
    } | {"attached_via": v.get("bridge_id") or v.get("transport") or "", "driver": v.get("driver")}


def _brief_candidate(c: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "candidate_id": c["candidate_id"],
        "name": c["name"],
        "type": c.get("aip_device_type"),
        "seen_via": c["source"],
        "present": c["present"],
        "status": c["status"],
        "join_path": c["join_path"] or None,
        "human_step": c["human_step"],
        "needs": (c.get("needs") or {}).get("what", ""),
    }


def _list(args: Dict[str, Any]) -> Dict[str, Any]:
    ov = get_onboarding_service().overview(include_ignored=bool(args.get("include_ignored")))
    return {
        "success": True,
        "summary": ov["summary"],
        "members": {g: [_brief_member(v) for v in vs] for g, vs in ov["groups"].items() if vs},
        "candidates": [_brief_candidate(c) for c in ov["candidates"]],
    }


# ── join / ignore / remove ──────────────────────────────────────────────────────


async def _join(args: Dict[str, Any], session_id: str) -> Dict[str, Any]:
    svc = get_onboarding_service()
    cid = str(args.get("candidate_id") or "")
    cand = svc.candidates.get(cid)
    if cand is None:
        return {"success": False, "error": f"没有这个候选:{cid}(先 devices__list)"}
    if cand.human_step == HumanStep.APPROVE.value and cand.status == CandidateStatus.NEW.value:
        if not _auto_allows(HumanStep.APPROVE.value):
            stop = await _ask(f"把「{cand.name}」接入为设备", session_id)
            if stop:
                return stop
    out = await svc.join(cid, dict(args.get("inputs") or {}))
    outcome = out.get("outcome") or {}
    if outcome.get("kind") == "needs_human":
        out["tell_user"] = (outcome.get("needs") or {}).get("what", "")
    return out


async def _remove(args: Dict[str, Any], session_id: str) -> Dict[str, Any]:
    did = str(args.get("device_id") or "")
    from core.unified.device_manager import get_unified_device_manager

    d = get_unified_device_manager().get_device(did)
    if d is None and get_onboarding_service().roster.get(did) is None:
        return {"success": False, "error": f"没有这个成员:{did}"}
    stop = await _ask(f"移除设备「{getattr(d, 'device_name', '') or did}」(同时收回它的网络身份)", session_id)
    if stop:
        return stop
    return await get_onboarding_service().remove(did)


# ── invoke:按接入方式路由 ─────────────────────────────────────────────────────


async def _invoke_home_assistant(d: Any, action: str, params: Dict[str, Any], session_id: str) -> Dict[str, Any]:
    from core.smart_home_tools import CONTROL_ACTIONS, dispatch_home_tool

    entity = str((d.metadata or {}).get("ha_entity_id") or d.device_id.removeprefix("ha_"))
    if entity.startswith("scene.") or action in ("activate", "scene"):
        return await dispatch_home_tool("scene", {"scene": entity}, session_id=session_id)
    act = {"turn_on": "on", "turn_off": "off"}.get(action, action)
    if act not in CONTROL_ACTIONS:
        return {"success": False, "error": f"经 Home Assistant 的设备支持:{', '.join(CONTROL_ACTIONS)}"}
    return await dispatch_home_tool(
        "control", {"device": entity, "action": act, "params": params}, session_id=session_id
    )


async def _invoke_mcp(d: Any, action: str, params: Dict[str, Any], session_id: str) -> Dict[str, Any]:
    from core.autonomy_policy import autonomy_level, is_read_action
    from core.mcp_gateway import get_mcp_gateway

    tool = str((d.metadata or {}).get("driver_mcp_tool") or d.bridge_id.removeprefix("mcp:"))
    if autonomy_level().value != "autonomous" and not is_read_action(action):
        stop = await _ask(f"对「{d.device_name or d.device_id}」执行 {action}", session_id)
        if stop:
            return stop
    meta = d.metadata or {}
    return await get_mcp_gateway().execute_tool(
        tool,
        {
            "device": {
                "name": d.device_name,
                "addresses": meta.get("addresses", []),
                **(meta.get("driver_device") or {}),
            },
            "action": action,
            "params": params,
        },
    )


#: 桥类型前缀 → 下行调用方式。新桥 = 在这里加一行。
BRIDGE_INVOKERS: Dict[str, Callable[[Any, str, Dict[str, Any], str], Awaitable[Dict[str, Any]]]] = {
    "ha:": _invoke_home_assistant,
    "mcp:": _invoke_mcp,
}


async def _invoke(args: Dict[str, Any], session_id: str) -> Dict[str, Any]:
    from core.unified.device_manager import get_unified_device_manager

    did = str(args.get("device_id") or "")
    action = str(args.get("action") or "").strip()
    params = dict(args.get("params") or {})
    d = get_unified_device_manager().get_device(did)
    if d is None:
        return {"success": False, "error": f"没有这个成员:{did}(候选要先 devices__join)"}
    if not action:
        return {"success": False, "error": "需要 action"}
    for prefix, invoker in BRIDGE_INVOKERS.items():
        if d.bridge_id.startswith(prefix):
            return await invoker(d, action, params, session_id)
    if is_native_transport(d.transport) or not d.transport:
        # 讲 AIP 的设备:走规范派发链(权限门在里面)
        from core.capabilities.canonical_dispatcher import get_canonical_dispatcher

        r = await get_canonical_dispatcher().dispatch(f"device__{did}__{action}", params, session_id=session_id)
        return r.as_legacy_dict()
    # 由驱动节点服务的设备:走统一执行器(白名单 + 自治档位照常)
    drv = get_onboarding_service()._driver_for(d)
    if drv.get("kind") != "node":
        return {"success": False, "error": f"「{d.device_name}」没有可用的驱动(试试 devices__acquire_driver)"}
    from core.node_invocation import InvocationSource, invoke_node

    inv = await invoke_node(
        drv["node"], action, {**params, "device_id": did}, invocation_source=InvocationSource.CAPABILITY
    )
    return {"success": inv.success, "result": inv.result, "error": inv.error}


# ── invite ───────────────────────────────────────────────────────────────────────


def _invite(args: Dict[str, Any]) -> Dict[str, Any]:
    kind = str(args.get("kind") or "").lower()
    from core.agent_card import build_local_card, get_pairing_code_registry, to_link
    from core.headscale_join import JoinUnavailable, issue_join_key

    if kind in ("phone", "watch"):
        link = to_link(build_local_card())
        code, expires_at = get_pairing_code_registry().issue(link)
        out: Dict[str, Any] = {
            "success": True,
            "human_step": HumanStep.CONFIRM_ON_DEVICE.value,
            "code": code,
            "link": link,
            "expires_at": expires_at,
            "tell_user": f"在{'手机' if kind == 'phone' else '手表'}的 Galaxy App 接入页输入配对码 {code}"
            + ("(手表配对时会自动进自建内网)" if kind == "watch" else "(10 分钟内有效)"),
        }
        if kind == "phone":
            try:
                from core.tailnet_self_join import join_command_for

                out["network"] = join_command_for("android", issue_join_key())
            except JoinUnavailable as exc:
                out["network"] = {"skipped": exc.reason, "how_to_fix": exc.how_to_fix}
        return out
    if kind in ("laptop", "computer"):
        # 电脑作为「相对主体」接进来:和手机同一条配对链。Windows / macOS / Linux 同一条命令
        # (device_client:连接层共用,本机怎么动手由执行插件决定)。同一局域网里客户端自己
        # 找主脑,所以短命令只带配对码;找不到时用带地址的那条。
        card = build_local_card()
        link = to_link(card)
        code, expires_at = get_pairing_code_registry().issue(link)
        gateway = gateway_http_base(card)
        short = f"python -m device_client --pair {code} --install-autostart"
        full = f"python -m device_client --pair {code} --gateway {gateway} --install-autostart"
        return {
            "success": True,
            "human_step": HumanStep.RUN_COMMAND.value,
            "code": code,
            "expires_at": expires_at,
            "commands": [short, full],
            "tell_user": (
                f"在那台电脑上(Windows、Mac、Linux 都一样,需要有本仓库和 Python)进到仓库目录,执行:{short} 。"
                f"如果它说在局域网里找不到主脑,改用:{full} 。配对码 {code} 10 分钟内有效、只能用一次;"
                "之后它开机会自己连上,连上时我会在这里告诉你。"
            ),
        }
    if kind == "worker":
        try:
            grant = issue_join_key()
        except JoinUnavailable as exc:
            return {"success": False, "error": f"签不出进网钥匙:{exc.reason}", "how_to_fix": exc.how_to_fix}
        from core.tailnet_self_join import current_state, join_command_for

        ips = current_state().get("ips") or []
        nats = f"nats://{ips[0]}:4222" if ips else "nats://<这台电脑的 100.x 地址>:4222"
        join = join_command_for("linux", grant)["command"]
        # worker 没有发布好的镜像:与 docker-compose.yml 的 galaxy-worker 一样,从本仓库 worker/ 构建。
        worker = (
            "cd <本仓库>/worker && docker build -t galaxy-worker . && "
            f"docker run -d --restart unless-stopped --network host -e GALAXY_NATS_URL={nats} galaxy-worker"
        )
        return {
            "success": True,
            "human_step": HumanStep.RUN_COMMAND.value,
            "commands": [join, worker],
            "tell_user": "在那台电脑上先执行第一条(进自建内网;钥匙 10 分钟内有效、只能用一次),"
            "再在它上面的本仓库副本里执行第二条(启动执行 worker)。起来之后它自己上消息总线、"
            "开始领计算任务 —— 不用再接入一次。它是干活的机器,不进设备列表",
        }
    return {"success": False, "error": "kind 只能是 phone / watch / laptop / worker"}


# ── 驱动:获取与绑定 ─────────────────────────────────────────────────────────────


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:40] or "device"


async def _acquire_driver(args: Dict[str, Any], session_id: str) -> Dict[str, Any]:
    svc = get_onboarding_service()
    cand = svc.candidates.get(str(args.get("candidate_id") or ""))
    if cand is None:
        return {"success": False, "error": "没有这个候选"}
    url = str(args.get("source_url") or "").strip()
    if url:
        from core.github_installer import get_github_installer

        res = await get_github_installer().install(url=url)
        ok = bool(res.get("success"))
        return {
            "success": ok,
            "install": {
                k: res.get(k) for k in ("name", "type", "install_state", "failure_reason", "error") if k in res
            },
            **({"next": "用 devices__bind_driver 指定其中控制这台设备的 MCP 工具"} if ok else {}),
        }
    if args.get("generate"):
        stop = await _ask(f"为「{cand.name}」生成一个驱动程序(模型写代码,沙箱测试后加载)", session_id)
        if stop:
            return stop
        from core.mcp_gateway import get_mcp_gateway

        tool = f"driver_{_slug(cand.aip_device_type + '_' + (cand.name or cand.key))}"
        res = await get_mcp_gateway().handle_capability_gap(
            tool,
            {
                "description": (
                    f"Control the device '{cand.name}' (type {cand.aip_device_type}, seen via {cand.source}, "
                    f"addresses {cand.addresses}). Input: {{device, action, params}}. Return {{success, result|error}}."
                ),
                "properties": cand.properties,
            },
        )
        if not res.get("success"):
            return {"success": False, "error": res.get("error") or "驱动生成失败", "detail": res}
        return await _bind_driver({"candidate_id": cand.candidate_id, "tool": res.get("tool_name", tool)})
    from core.device_onboarding.drivers import search_installed

    found = await search_installed(cand)
    if found:
        return {
            "success": True,
            "installed_matches": found,
            "next": "已装的工具里有这些可能对得上;确认是哪个后用 devices__bind_driver 绑定。都不对的话给 source_url 或 generate=true",
        }
    return {
        "success": False,
        "error": "已装的 MCP 工具里没有对得上的。给一个 GitHub 上控制这类设备的 MCP 服务地址(source_url),"
        "或 generate=true 让我写一个(会先问你)",
    }


async def _bind_driver(args: Dict[str, Any]) -> Dict[str, Any]:
    from core.device_onboarding.drivers import bind_member

    svc = get_onboarding_service()
    cand = svc.candidates.get(str(args.get("candidate_id") or ""))
    tool = str(args.get("tool") or "").strip()
    if cand is None or not tool:
        return {"success": False, "error": "需要 candidate_id 与 tool"}
    member = bind_member(cand, tool, svc)
    return {"success": True, "device_id": member.device_id, "driver": tool}


# ── 分发 ─────────────────────────────────────────────────────────────────────────


async def dispatch_devices_tool(action: str, arguments: Dict[str, Any], *, session_id: str = "") -> Dict[str, Any]:
    if action == REQUEST_ACTION:  # 不受设备接入开关管
        return await dispatch_mode_tool(action, arguments, session_id=session_id)
    if not onboarding_enabled():
        return {"success": False, "error": "设备接入平面已关闭(GALAXY_ONBOARDING_ENABLED=false)"}
    args = dict(arguments or {})
    try:
        if action == "list":
            return _list(args)
        if action == "join":
            return await _join(args, session_id)
        if action == "ignore":
            return get_onboarding_service().ignore(str(args.get("candidate_id") or ""))
        if action == "remove":
            return await _remove(args, session_id)
        if action == "invoke":
            return await _invoke(args, session_id)
        if action == "invite":
            return _invite(args)
        if action == "acquire_driver":
            return await _acquire_driver(args, session_id)
        if action == "bind_driver":
            return await _bind_driver(args)
    except Exception as exc:  # noqa: BLE001 — 工具失败要作为结果回给智能体,不能炸掉对话
        logger.warning("devices__%s 失败: %s", action, exc)
        return {"success": False, "error": str(exc)}
    return {"success": False, "error": f"未知的设备工具: devices__{action}"}
