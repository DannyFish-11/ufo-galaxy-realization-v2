"""core/device_onboarding/mode_request.py — 智能体**请求**打开跨设备模式；批准只归人。

系统只有两个模式：本地模式（默认，只用这台电脑）与跨设备模式（见 ``core/system_mode.py``）。
「能不能去碰你的手机、手表、别的电脑」是权限本身，不是一次任务里的选择 —— 所以模型可以**提**，
不可以**批**。这里的一个工具 ``devices__request_cross_device`` 只做一件事：本地模式下，问人要不要打开。

* 批准走设备接入平面已有的人在环（``agent_tools._ask`` → ``conversation.confirm_in_conversation``），不另写一套：
  问的那一回合不算数；只认人发起的回合（文字 / 语音 / 手表）；看人的原话；一次只管一件事、十分钟作废；
  手表/手机连着时在手表上问（fail-closed）。
* ``GALAXY_ONBOARDING_AUTO=approve`` **不适用**于它 —— 那个配置管的是「接入一台设备」这一类同意，
  不是「放开整台电脑能碰哪些设备」。和「移除永远要问」一样，这里永远要问。
* 后台自发的回合（环境注意力、定时心跳……）连**提出**都不行：它们不是人在说话，问了也没人在听，只会打扰。
* 只能请求**打开**，不能关，也不能借它改别的设置；关与主脑仍然只在面板。
* 批准后走面板按钮同一个写入函数（``core.routes.config.set_bundle``）：NATS、局域网发现这些跟着按钮走的键，
  结果和你点按钮完全一样。这个按钮要**重启**才完全生效，工具回话里说明白，不替人重启。
* 这个工具**不挂在** ``GALAXY_ONBOARDING_ENABLED`` 底下：那个开关是跨设备按钮的成员，按钮关着它也是关的 ——
  请求挂在那儿，最需要它的时候它就没了。只在本地模式下提供（已经是跨设备模式时不广告一个死工具）。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger("Galaxy.Onboarding.ModeRequest")

REQUEST_ACTION = "request_cross_device"
REQUEST_TOOL = f"devices__{REQUEST_ACTION}"

#: 问人的那句话。固定不变：对话里的确认是按「同一会话 + 同一句话」配对的。
WHAT = "打开跨设备模式(让这台电脑能使用你的手机、手表和别的电脑;要重启才完全生效)"

MODE_BUILTIN_TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": REQUEST_TOOL,
            "description": (
                "The system is in local mode: it only uses this computer, so the user's phone, watch and other "
                "computers cannot be used yet. Call this to ASK the user whether to turn on cross-device mode. "
                "You cannot turn it on yourself — the user decides: relay the question this returns (ask_user) "
                "word for word, and when they have answered call this again with no arguments. It takes effect "
                "after a restart; say so. Only call it when the user actually wants another device used."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    }
]


def mode_request_tools() -> List[Dict[str, Any]]:
    """要给模型的工具：只在本地模式下有。"""
    from core.system_mode import cross_device_requested

    return [] if cross_device_requested() else list(MODE_BUILTIN_TOOLS)


async def dispatch_mode_tool(action: str, arguments: Dict[str, Any], *, session_id: str = "") -> Dict[str, Any]:
    if action != REQUEST_ACTION:
        return {"success": False, "error": f"未知的模式工具: devices__{action}"}
    try:
        return await _request_cross_device(session_id)
    except Exception as exc:  # noqa: BLE001 — 失败作为结果回给智能体,不炸对话
        logger.warning("%s 失败: %s", REQUEST_TOOL, exc)
        return {"success": False, "error": str(exc)}


async def _request_cross_device(session_id: str) -> Dict[str, Any]:
    from core.device_onboarding.agent_tools import _ask
    from core.device_onboarding.conversation import HUMAN_REQUEST_SOURCES, _current_turn
    from core.system_mode import cross_device_requested

    if cross_device_requested():
        return {
            "success": True,
            "already": True,
            "message": "已经是跨设备模式(如果刚打开,要重启才完全生效)。",
        }

    turn_id, source, _text = _current_turn()
    if not turn_id or source not in HUMAN_REQUEST_SOURCES:
        # 后台自发的回合、或来源不明(fail closed):不是人在说话,不问。
        return {
            "success": False,
            "error": "只有用户自己发起的对话里才能请求打开跨设备模式(这是后台自发的回合,没有在问任何人)",
        }

    stop = await _ask(WHAT, session_id)
    if stop:
        return stop

    from core.routes.config import BundleUpdateRequest, set_bundle

    out = await set_bundle(BundleUpdateRequest(key="cross_device", value="true"))
    bundle = out.get("bundle", {})
    logger.info("[AUDIT] 跨设备模式已打开 | 批准=用户(对话/手表确认) | 回合=%s 来源=%s", turn_id, source)
    return {
        "success": True,
        "enabled": True,
        "restart_required": True,
        "bundle": {k: bundle.get(k) for k in ("key", "value", "overrides", "restart_required")},
        "tell_user": "已打开跨设备模式。要重启一次才完全生效(消息总线、桌面在场要重启才按跨设备模式起);我不会替你重启。",
    }
