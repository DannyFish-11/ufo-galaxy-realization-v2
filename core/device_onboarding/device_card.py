"""core/device_onboarding/device_card.py — 模型看到的「设备整体卡」。

整体方案第二条原则:不给设备登记死的能力和角色,每台设备当成一个**整体**交给模型,由模型的泛化能力
加上工程流程约束决定它做什么(见 ``docs/CROSS_DEVICE_OVERALL_PLAN.md``「智能体怎么决定设备做什么」)。
规则只做过滤(在不在名册、在不在线、有没有权限),不替模型挑设备;固定的「感知 / 动作 / 在场」角色
(``core/mesh/device_role_allocator.py``)不给模型看,只留作观测标签。

一张卡回答五件事,都取自已有的权威,不另存一份:

    是什么        名称、类型、形态                      UDM
    能做什么      设备自己报的每个动作,附一句说明        能力权威面(capability_report 的 description)
    现在怎么样    在线、电量、网络路径、忙不忙、能否打扰  UCM / UDM 状态上报 / 可打扰性登记
    能否接 Agent  手机、Agent 载体能;手表、「手和眼」不能  UDM 的执行模型 + 设备自己的声明;装上了没有看桥接 Agent
    最近做过什么  最近几次下发与结果                    任务流程图(task_graph_runtime)

卡要短:它进模型上下文,动作最多列 ``MAX_ACTIONS`` 个、最近做过的最多 ``MAX_RECENT`` 条。
"""

from __future__ import annotations

import ipaddress
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from core.device_onboarding.taxonomy import FULL_RUNTIME_HOST

logger = logging.getLogger("Galaxy.Onboarding.DeviceCard")

MAX_ACTIONS = 24
MAX_RECENT = 3

#: 设备没给说明时,常见动作的一句话说明(说的是效果,不是实现)。
ACTION_GLOSSARY: Dict[str, str] = {
    "notify": "在设备上弹一条通知给人看",
    "haptic": "让设备震动提醒",
    "get_status": "读设备当前状态(电量、连接等)",
    "screenshot": "截一张当前屏幕",
    "tap": "点屏幕上的一个位置",
    "click": "点击屏幕上的一个位置或控件",
    "swipe": "在屏幕上滑动",
    "scroll": "滚动当前界面",
    "input_text": "往当前输入框里输入文字",
    "type": "用键盘输入文字",
    "key": "按一个按键或组合键",
    "open_app": "打开一个应用",
    "launch_app": "打开一个应用",
    "go_home": "回到主屏幕",
    "back": "返回上一页",
    "run_command": "在设备上执行一条命令",
    "shell": "在设备上执行一条命令",
    "read_file": "读设备上的一个文件",
    "write_file": "往设备上写一个文件",
    "speak": "让设备把一段文字念出来",
    "play_audio": "在设备上播放一段声音",
    "turn_on": "打开(灯、插座等)",
    "turn_off": "关闭(灯、插座等)",
    "goal_execution": "把一个完整目标交给设备自己规划完成",
}

_GENERIC_DESCRIPTION_PREFIX = "[Gateway:"


def _form(view: Dict[str, Any]) -> str:
    """一个词说清它是什么形态:手表 / 手机 / 电脑 / 载体 / 家居 / 设备。"""
    ff = str(view.get("form_factor") or "").lower()
    t = str(view.get("type") or "").lower()
    if view.get("bridge_id") or str(view.get("attached_via") or "").startswith(("ha:", "mcp:")):
        return "home"
    if ff == "watch" or "wear" in t or "watch" in t:
        return "watch"
    if ff in ("phone", "tablet") or t.startswith(("android_phone", "android_tablet", "ios_")):
        return "phone"
    if t.startswith(("cloud_", "container_", "virtual_")) or ff in ("server", "cloud"):
        return "carrier"
    if ff in ("desktop", "laptop") or t.startswith(("windows_", "macos_", "linux_")):
        return "computer"
    return "device"


def can_take_agent(view: Dict[str, Any], metadata: Optional[Dict[str, Any]] = None) -> bool:
    """能不能接中心派来的 Agent:有完整运行时的设备(手机),或自己声明能跑 Agent 的载体。

    手表只是人和智能体之间的入口和出口;「手和眼」式的电脑(``device_client``)只接单个动作。
    """
    meta = metadata or {}
    if meta.get("can_host_agent") is True or meta.get("agent_runtime") is True:
        return True
    if meta.get("can_host_agent") is False:
        return False
    return str(view.get("role") or "") == FULL_RUNTIME_HOST and _form(view) != "watch"


def _actions(device_id: str, raw_capabilities: List[str]) -> List[Dict[str, str]]:
    """设备自己报的动作(能力权威面里 ``gateway__<id>__<action>``),附一句说明。"""
    out: List[Dict[str, str]] = []
    try:
        from core.unified.capability_authority import CapabilityAuthority

        authority = CapabilityAuthority.get_instance()
        registry = authority._get_registry()
        prefix = f"gateway__{device_id}__"
        names = sorted(n for n in getattr(registry, "_items", {}) if str(n).startswith(prefix))
        for name in names[:MAX_ACTIONS]:
            rec = authority.get_record(name)
            action = name[len(prefix) :]
            desc = str(getattr(rec, "description", "") or "")
            if desc.startswith(_GENERIC_DESCRIPTION_PREFIX):
                desc = ""
            out.append({"name": action, "does": desc or ACTION_GLOSSARY.get(action, "")})
    except Exception as exc:  # noqa: BLE001 — 卡片是只读视图,拿不到动作不该让整张表失败
        logger.debug("device card: actions unavailable for %s: %s", device_id, exc)
    if not out:
        # 没经 capability_report 报过动作的(桥接设备、旧客户端):原始能力串当动作名
        for cap in raw_capabilities[:MAX_ACTIONS]:
            out.append({"name": cap, "does": ACTION_GLOSSARY.get(cap, "")})
    return out


def _network(device_id: str) -> str:
    """它现在经哪条路连着:tailnet / 局域网 / 本机 / 公网;没有 WebSocket 连接时说通道名。"""
    try:
        from core.unified.connection_manager import get_unified_connection_manager

        ucm = get_unified_connection_manager()
        ws = getattr(ucm, "_websockets", {}).get(device_id)
        host = str(getattr(getattr(ws, "client", None), "host", "") or "")
        if host:
            ip = ipaddress.ip_address(host)
            if ip.is_loopback:
                return "local"
            if ip in ipaddress.ip_network("100.64.0.0/10"):
                return "tailnet"
            return "lan" if ip.is_private else "internet"
        for ch, rec in ucm.channel_presence(device_id).items():
            if rec.get("online"):
                return str(ch)
    except Exception as exc:  # noqa: BLE001
        logger.debug("device card: network path unknown for %s: %s", device_id, exc)
    return ""


def _status(view: Dict[str, Any], metadata: Dict[str, Any], now: float) -> Dict[str, Any]:
    device_id = view["device_id"]
    status: Dict[str, Any] = {"online": bool(view.get("online"))}
    last_seen = float(view.get("last_seen") or 0.0)
    if last_seen:
        status["seen_s_ago"] = int(max(0.0, now - last_seen))
    report = metadata.get("device_status_report") if isinstance(metadata.get("device_status_report"), dict) else {}
    battery = report.get("battery") if "battery" in report else report.get("battery_level")
    if battery is not None:
        status["battery"] = battery
    net = _network(device_id) if status["online"] else ""
    if net:
        status["network"] = net
    try:
        from core.unified.connection_manager import get_unified_connection_manager

        status["busy"] = get_unified_connection_manager().inflight(device_id) > 0
    except Exception:  # noqa: BLE001
        pass
    if _form(view) == "watch":
        try:
            from core.interruptibility_registry import get_interruptibility_registry

            snap = get_interruptibility_registry()._by_device.get(device_id)
            if snap is not None and not snap.is_stale(now):
                status["interruptible"] = snap.band
        except Exception:  # noqa: BLE001
            pass
    return status


def _bridge(device_id: str) -> Dict[str, Any]:
    """中心派来的桥接 Agent 在这台设备上的状态(装上了才能 ``devices__delegate`` 整段目标)。"""
    try:
        from core.phone_bridge import bridge_state

        return bridge_state(device_id)
    except Exception:  # noqa: BLE001
        return {}


def _recent(device_id: str, now: float) -> List[Dict[str, Any]]:
    """最近几次给它的下发与结果(任务流程图)。"""
    try:
        from core.task_graph_runtime import get_task_graph_runtime

        nodes = [n for n in get_task_graph_runtime().all_nodes() if n.device_id == device_id]
    except Exception as exc:  # noqa: BLE001
        logger.debug("device card: task graph unavailable: %s", exc)
        return []
    nodes.sort(key=lambda n: n.queued_at, reverse=True)
    out = []
    for n in nodes[:MAX_RECENT]:
        item: Dict[str, Any] = {
            "what": n.tool_name,
            "state": n.state.value if hasattr(n.state, "value") else str(n.state),
            "s_ago": int(max(0.0, now - (n.completed_at or n.queued_at))),
        }
        if n.error:
            item["error"] = n.error[:120]
        elif n.result_summary:
            item["result"] = n.result_summary[:120]
        out.append(item)
    return out


def build_device_card(view: Dict[str, Any], metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """一台成员的整体卡。``view`` 是 ``OnboardingService.member_view`` 的结果。"""
    now = time.time()
    meta = dict(metadata or {})
    bridge = _bridge(view["device_id"])
    raw_caps = [str(c) for c in (view.get("capabilities") or [])]
    card: Dict[str, Any] = {
        "device_id": view["device_id"],
        "name": view.get("name") or view["device_id"],
        "type": view.get("type") or "",
        "form": _form(view),
        "can_initiate": bool(view.get("can_initiate")),
        "status": _status(view, meta, now),
        "actions": _actions(view["device_id"], raw_caps),
        "can_take_agent": can_take_agent(view, meta) or bool(bridge.get("hosted")),
        "agent_installed": bool(bridge.get("installed")),
        "recent": _recent(view["device_id"], now),
        "attached_via": view.get("bridge_id") or view.get("transport") or "",
    }
    if raw_caps:
        card["raw_capabilities"] = raw_caps[:MAX_ACTIONS]
    classes = [str(c) for c in (view.get("capability_classes") or [])]
    if classes:
        # 能力同化归出的类:只用于检索和过滤(「哪台能截图」),不替模型决定
        card["capability_classes"] = classes[:MAX_ACTIONS]
    driver = view.get("driver")
    if isinstance(driver, dict) and driver.get("kind") not in (None, "native"):
        card["driver"] = driver
    return card


# ── 每次单动作下发都进任务流程图 ────────────────────────────────────────────────


def record_dispatch(
    device_id: str, action: str, session_id: str = "", metadata: Optional[Dict[str, Any]] = None
) -> str:
    """登记一次给设备的下发,返回 task_id;登记不了返回空串(只是观测,不挡下发)。

    节点标 ``observation_only``:下发是在等结果的调用方做的,进程重启后调用方不在了,
    重启续跑不该拿一个没有载荷的节点去重派(多步计划自己续跑,见 core/task_plan.py)。
    """
    try:
        from core.task_graph_runtime import GraphNodeState, WorkflowContributorKind, get_task_graph_runtime

        task_id = f"dev_{uuid.uuid4().hex[:12]}"
        rt = get_task_graph_runtime()
        rt.register_node_raw(
            task_id,
            tool_name=action,
            session_id=session_id,
            device_id=device_id,
            contributor=WorkflowContributorKind.UNKNOWN,
            metadata={"kind": "device_action", "observation_only": True, **(metadata or {})},
        )
        rt.transition(task_id, GraphNodeState.DISPATCH, reason="device_action_dispatch")
        return task_id
    except Exception as exc:  # noqa: BLE001
        logger.debug("device card: dispatch not recorded: %s", exc)
        return ""


def record_result(task_id: str, ok: bool, summary: str = "", error: str = "") -> None:
    if not task_id:
        return
    try:
        from core.task_graph_runtime import GraphNodeState, get_task_graph_runtime

        get_task_graph_runtime().transition(
            task_id,
            GraphNodeState.COMPLETED if ok else GraphNodeState.FAILED,
            reason="device_action_result",
            result_summary=summary[:200],
            error=error[:200],
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("device card: result not recorded: %s", exc)
