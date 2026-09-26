"""core/smart_home_tools.py — 智能体的智能家居工具:看家里有什么、开关它们。

缺口是什么
==========
下行控制早就有:``nodes/Node_27_SmartHome`` 经 Home Assistant 的 REST 开关设备;
上行也有:``core/ha_bridge.py`` 把 HA 实体镜像进设备列表。可两头之间,**智能体
够不着**:

* 智能体的节点工具只来自 NodeFabricRegistry 里声明了能力的节点,而启动器登记
  节点时能力表是空的 —— Node_27 在智能体的工具表里一个工具都没有;
* 就算直接去调,Node_27 的权限白名单只写了 HTTP 路由名(``control_device``),
  统一执行器那条路用的是 ``control``,被 fail-closed 拒掉。

于是"跟手表说一句'把客厅灯打开'"走不通:灯在设备列表里看得见,智能体却没有
任何工具能碰它。

这里补的是智能体那一端:三件具体的工具,只在配了 HA 时出现(没配就不广告死工具)。
执行一律走统一执行器 ``invoke_node("Node_27_SmartHome", …)``,不绕开任何一道门:
权限白名单、自治档位审批都照常生效。

审批不能卡死在面板上
====================
默认的自治档位(guided)下,Node_27 的"写"动作要人点头。原来的形态是排进审批
队列、等人去面板上批 —— 可你是在外面对着手表说的话,面板不在手边。所以这里
被要求审批时,**直接在手表上问你**(与高风险工具同一条 HITL 通路,fail-closed:
只有明确点了"批准"才算),批了就只授权这一次,再执行。
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.SmartHomeTools")

NODE_ID = "Node_27_SmartHome"

#: Node_27 在 HA 模式下认识的动作(nodes/Node_27_SmartHome/main.py control_device 的 action_map)。
CONTROL_ACTIONS = ("on", "off", "toggle", "set_brightness", "set_temperature")

_ACTION_WORDS = {"on": "打开", "off": "关掉", "toggle": "切换", "set_brightness": "调亮度", "set_temperature": "调温度"}

#: 一次列给模型的设备上限。HA 里常有几百个实体(传感器、更新项……),全塞进上下文没有意义。
MAX_LISTED = 80


def home_tools_enabled() -> bool:
    """配了 HA(地址 + 令牌)才给智能体这组工具。"""
    return bool(os.getenv("HOME_ASSISTANT_URL", "").strip() and os.getenv("HOME_ASSISTANT_TOKEN", "").strip())


HOME_BUILTIN_TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "home__devices",
            "description": (
                "List smart-home devices (lights, switches, climate, covers, scenes…) from Home Assistant, "
                "with their current state. Call this first to find the entity_id of the device the user means "
                "(match on the friendly name, e.g. '客厅灯'). Optional 'query' filters by name or entity_id."
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Substring to filter by (optional)."}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "home__control",
            "description": (
                "Turn a smart-home device on/off/toggle, or set brightness/temperature. 'device' is the "
                "entity_id from home__devices (e.g. 'light.living_room'); a friendly name also works when it "
                "matches exactly one device. The user may be asked to approve on their watch first."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "entity_id or exact friendly name"},
                    "action": {"type": "string", "enum": list(CONTROL_ACTIONS)},
                    "params": {
                        "type": "object",
                        "description": (
                            "Extra service data, e.g. {'brightness_pct': 40} for set_brightness, "
                            "{'temperature': 24} for set_temperature."
                        ),
                    },
                },
                "required": ["device", "action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "home__scene",
            "description": "Activate a Home Assistant scene by its entity_id (e.g. 'scene.movie_night').",
            "parameters": {
                "type": "object",
                "properties": {"scene": {"type": "string", "description": "scene entity_id"}},
                "required": ["scene"],
            },
        },
    },
]


async def _invoke(action: str, params: Dict[str, Any]) -> Any:
    from core.node_invocation import InvocationSource, invoke_node

    return await invoke_node(NODE_ID, action, params, invocation_source=InvocationSource.CAPABILITY)


def _unwrap(inv: Any) -> Dict[str, Any]:
    """统一执行器的结果 → ``{success, result|error}``。

    成功要两层都成功:执行器成功只说明节点被调到了;节点自己回的
    ``{"success": False}``(比如 HA 回 401)同样是失败,不能报成"已打开"。
    """
    if not inv.success:
        return {"success": False, "error": inv.error or "执行失败"}
    outer = inv.result if isinstance(inv.result, dict) else {}
    if outer.get("success") is False:
        return {"success": False, "error": outer.get("error") or "节点执行失败"}
    inner = outer.get("result", outer)
    if isinstance(inner, dict) and inner.get("success") is False:
        return {"success": False, "error": inner.get("error") or "Home Assistant 执行失败"}
    return {"success": True, "result": inner}


async def _states() -> Dict[str, Any]:
    out = _unwrap(await _invoke("states", {}))
    if not out["success"]:
        return out
    raw = out["result"].get("states", []) if isinstance(out["result"], dict) else []
    devices = [
        {
            "entity_id": s.get("entity_id", ""),
            "name": (s.get("attributes") or {}).get("friendly_name") or s.get("entity_id", ""),
            "state": s.get("state", ""),
        }
        for s in raw
        if isinstance(s, dict) and s.get("entity_id")
    ]
    return {"success": True, "devices": devices}


def _filter(devices: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
    q = query.strip().lower()
    if not q:
        return devices
    return [d for d in devices if q in d["entity_id"].lower() or q in str(d["name"]).lower()]


async def _resolve_entity(device: str) -> Dict[str, Any]:
    """``device`` → entity_id。已经是 entity_id(含点)就直接用;否则按名字唯一匹配。"""
    dev = device.strip()
    if dev.startswith("ha_") and "." in dev:  # 设备列表里 HA 实体的 device_id 形如 ha_<entity_id>
        dev = dev[3:]
    if "." in dev:
        return {"success": True, "entity_id": dev, "name": dev}
    listed = await _states()
    if not listed["success"]:
        return listed
    exact = [d for d in listed["devices"] if str(d["name"]).strip().lower() == dev.lower()]
    if len(exact) == 1:
        return {"success": True, "entity_id": exact[0]["entity_id"], "name": exact[0]["name"]}
    candidates = exact or _filter(listed["devices"], dev)
    if not candidates:
        return {"success": False, "error": f"Home Assistant 里没有叫「{device}」的设备,先用 home__devices 查"}
    return {
        "success": False,
        "error": f"「{device}」对应多个设备,请用 entity_id 指定",
        "candidates": candidates[:10],
    }


async def _approve_on_watch(node_action: str, what: str, error: str, session_id: str) -> Optional[str]:
    """执行器要求审批时,在手表上问一次。批准返回 None;否则返回不执行的理由。"""
    if not error.startswith("approval_required"):
        return error
    from core.interaction.high_risk_confirmation import confirm_high_risk_tool

    outcome = await confirm_high_risk_tool(tool_name=what, risk_level="写操作", session_id=session_id)
    if not outcome.approved:
        return f"没有执行:{outcome.reason}"
    # 与面板审批同一套落账(core/routes/approvals.py):ack 掉排队中的请求,授权**仅此一次**。
    try:
        from core.autonomy_policy import GrantScope, get_grant_store
        from core.control_plane._globals import get_approval_registry

        registry = get_approval_registry()
        for req in registry.list_pending():
            if req.action == f"{NODE_ID}.{node_action}":
                registry.ack(req.request_id, req.ack_token, operator=f"watch:{outcome.decision_id}")
        get_grant_store().grant(NODE_ID, node_action, GrantScope.ONCE, operator=f"watch:{outcome.decision_id}")
    except Exception as exc:  # noqa: BLE001
        return f"已批准,但授权没记上({exc}),没有执行"
    return None


async def dispatch_home_tool(action: str, arguments: Dict[str, Any], *, session_id: str = "") -> Dict[str, Any]:
    """执行 ``home__<action>``。"""
    args = arguments or {}
    if not home_tools_enabled():
        return {"success": False, "error": "没配 Home Assistant:在面板「设备」里填 HOME_ASSISTANT_URL 和令牌"}

    if action == "devices":
        listed = await _states()
        if not listed["success"]:
            return listed
        found = _filter(listed["devices"], str(args.get("query") or ""))
        return {
            "success": True,
            "count": len(found),
            "devices": found[:MAX_LISTED],
            "truncated": len(found) > MAX_LISTED,
        }

    if action == "scene":
        scene = str(args.get("scene") or "").strip()
        if not scene:
            return {"success": False, "error": "home__scene 需要 scene"}
        out = _unwrap(await _invoke("scene", {"scene_id": scene}))
        if not out["success"]:
            why = await _approve_on_watch("scene", f"启动场景 {scene}", out["error"], session_id)
            if why is not None:
                return {"success": False, "error": why}
            out = _unwrap(await _invoke("scene", {"scene_id": scene}))
        return out

    if action == "control":
        act = str(args.get("action") or "").strip()
        if act not in CONTROL_ACTIONS:
            return {"success": False, "error": f"action 只能是 {', '.join(CONTROL_ACTIONS)}"}
        target = await _resolve_entity(str(args.get("device") or ""))
        if not target["success"]:
            return target
        params = {"device_id": target["entity_id"], "action": act, "params": dict(args.get("params") or {})}
        out = _unwrap(await _invoke("control", params))
        if not out["success"]:
            what = f"{_ACTION_WORDS[act]} {target['name']}"
            why = await _approve_on_watch("control", what, out["error"], session_id)
            if why is not None:
                return {"success": False, "error": why}
            out = _unwrap(await _invoke("control", params))
        if out["success"]:
            out["entity_id"] = target["entity_id"]
        return out

    return {"success": False, "error": f"未知的 home 工具: home__{action}"}
