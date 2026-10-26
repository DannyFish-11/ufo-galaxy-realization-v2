"""core/device_boundaries.py — 给设备下发一个动作之前,代码守的边界。

设计见 ``docs/DEVICE_SELF_DESCRIPTION_DESIGN.md`` 第 5 节。清单之外的事(发给哪台、怎么说、失败了怎么办)
都交给模型,这里不替它挑设备。第 2 步落了其中两条,其余几条第 4 步收进来:

* **参数合法**:按设备自述里这个动作的 ``params``(JSON Schema)校验,不合法不发,原因交回模型;
* **权限门与自治档位**:按动作做了会怎样(``effect``)、要不要人在设备上点(``needs_human``)和
  自治档位判要不要先问人:

  ========  ============  ===================  ==========
  effect    谨慎 safe      引导 guided(默认)    自主
  ========  ============  ===================  ==========
  read      问             直接做                直接做
  notify    问             直接做                直接做
  act       问             问(可选本会话/永久)  直接做
  send      高风险确认      高风险确认            高风险确认
  danger    高风险确认      高风险确认            高风险确认
  ========  ============  ===================  ==========

  ``needs_human`` 的动作设备上那一下就是确认,中心不再另外问。设备没说 ``effect`` 的:动作名一看就是读的
  (``get_*``、``list_*`` 这类)按读,其余按改状态 —— 拿不准的往严里算。

  * **问**:有声明能回答提问的设备在线,就在那上面问(不要 / 仅此次 / 本会话 / 永久允许),选了本会话或永久
    就记一条授权(``core.autonomy_policy`` 的 ``GrantStore``,经 ``/api/v1/approval-grants`` 能列出、撤销),下次不再问;没有就在对话里问,
    人答应了智能体再调一次。
  * **高风险确认**:只弹到声明了能回答提问的设备上,要人点「批准」;嘴上说好不算,问不到人就不做。

一律 fail closed:问不到、超时、含糊的回答,都当没批准。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("Galaxy.DeviceBoundaries")

GO, ASK, CONFIRM = "go", "ask", "confirm"

#: 「问」时的四个选项。批准类放在后面,误触第一个按钮的代价不该是执行。
GRANT_OPTIONS = [
    {"id": "deny", "label": "不要"},
    {"id": "once", "label": "仅此次"},
    {"id": "session", "label": "本会话"},
    {"id": "always", "label": "永久允许"},
]

_RISK_WORDS = {"send": "对外发出、收不回来", "danger": "不可逆或代价大", "act": "改设备状态"}


def _device(device_id: str) -> Any:
    try:
        from core.unified.device_manager import get_unified_device_manager

        return get_unified_device_manager().get_device(device_id)
    except Exception:  # noqa: BLE001
        return None


def action_spec(device_id: str, action: str) -> Dict[str, Any]:
    """设备自述里这个动作怎么说(没说就是空字典)。"""
    from core.device_self import described

    d = _device(device_id)
    for a in described(getattr(d, "metadata", None) or {}).get("actions") or []:
        if a.get("name") == action:
            return a
    return {}


def effect_of(spec: Dict[str, Any], action: str) -> str:
    """这个动作做了会怎样。设备没说的,动作名一看就是读的按读,其余按改状态。"""
    from core.autonomy_policy import is_read_action
    from core.device_self import EFFECTS

    effect = str(spec.get("effect") or "")
    if effect in EFFECTS:
        return effect
    return "read" if is_read_action(action) else "act"


def check_params(spec: Dict[str, Any], params: Dict[str, Any]) -> Optional[str]:
    """参数哪里不合设备说的格式(合就是 None)。设备没给格式的不查。"""
    schema = spec.get("params")
    if not isinstance(schema, dict) or not (schema.get("properties") or schema.get("required")):
        return None
    try:
        import jsonschema
    except ImportError:  # pragma: no cover — requirements 里有
        return None
    errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(params or {}), key=lambda e: list(e.path))
    if not errors:
        return None
    e = errors[0]
    where = ".".join(str(p) for p in e.absolute_path)
    return f"{where}: {e.message}" if where else e.message


def verdict_for(level: str, effect: str, needs_human: bool) -> str:
    """按设计文档第 5 节那张表:直接做 / 问 / 高风险确认。"""
    if needs_human:
        return GO
    if effect in ("send", "danger"):
        return CONFIRM
    if level == "autonomous":
        return GO
    if level == "guided" and effect in ("read", "notify"):
        return GO
    return ASK


def describe(device_id: str, action: str, params: Dict[str, Any]) -> str:
    """给人看的一句:让「Pixel 9」app_control(app=微信)。"""
    d = _device(device_id)
    name = str(getattr(d, "device_name", "") or device_id)
    shown = ", ".join(f"{k}={str(v)[:40]}" for k, v in sorted((params or {}).items()))
    return f"让「{name}」{action}({shown})" if shown else f"让「{name}」{action}"


def _grant_from(outcome: Any) -> str:
    """问的结果 → 授权档位(once / session / always);不是人明确点了其中之一就是空串。"""
    if outcome is None or bool(getattr(outcome, "timed_out", False)):
        return ""
    status = getattr(outcome, "status", None)
    if str(getattr(status, "value", status) or "") != "resolved":
        return ""
    chosen = str(getattr(outcome, "selected_option", "") or "")
    return chosen if chosen in ("once", "session", "always") else ""


async def _ask_on_device(what: str, effect: str, session_id: str, targets: list) -> str:
    from core.interaction.pending_decision_registry import OnTimeout, request_human_decision

    try:
        outcome = await request_human_decision(
            title=f"要{what}吗?",
            summary=f"这会{_RISK_WORDS.get(effect, '改设备状态')}。选「本会话」或「永久允许」以后就不再问。",
            options=GRANT_OPTIONS,
            default_option=None,
            on_timeout=OnTimeout.CANCEL,
            urgency="normal",
            devices=targets,
            session_id=session_id,
            runtime_session_id=session_id,
        )
    except Exception as exc:  # noqa: BLE001 — 问不到当没批准
        logger.warning("设备动作审批:询问失败(%s),不执行 %s", exc, what)
        return ""
    return _grant_from(outcome)


def _in_conversation(what: str, session_id: str) -> Optional[Dict[str, Any]]:
    from core.device_onboarding.conversation import confirm_in_conversation

    v = confirm_in_conversation(what, session_id)
    if v["state"] == "approved":
        return None
    if v["state"] == "denied":
        return {"success": False, "error": "用户在对话里说不要,没有执行"}
    return {
        "success": False,
        "needs_confirmation": True,
        "ask_user": v["ask_user"],
        "next": "把 ask_user 原样问用户;用户回答之后,用同样的参数再调一次",
    }


async def gate(device_id: str, action: str, params: Dict[str, Any], session_id: str = "") -> Optional[Dict[str, Any]]:
    """下发前过边界:可以发返回 None;不能发返回该交回给智能体的结果(带原因)。"""
    from core.autonomy_policy import GrantScope, autonomy_level, get_grant_store

    spec = action_spec(device_id, action)
    problem = check_params(spec, params)
    if problem:
        return {
            "success": False,
            "error": f"参数不合「{action}」要的格式,没有发给设备:{problem}",
            "params_schema": spec.get("params"),
        }
    effect = effect_of(spec, action)
    verdict = verdict_for(autonomy_level().value, effect, spec.get("needs_human") is True)
    if verdict == GO:
        return None
    what = describe(device_id, action, params)

    if verdict == CONFIRM:
        from core.interaction.high_risk_confirmation import confirm_high_risk_tool

        outcome = await confirm_high_risk_tool(
            tool_name=what, risk_level=_RISK_WORDS[effect], session_id=session_id, device_id=device_id
        )
        return None if outcome.approved else {"success": False, "error": f"没有执行:{outcome.reason}"}

    node = f"device:{device_id}"
    if get_grant_store().consume_or_check(node, action):
        return None
    from core.device_onboarding.conversation import is_pending

    if is_pending(what, session_id):
        return _in_conversation(what, session_id)
    try:
        from core.device_declarations import online_devices_that

        targets = await online_devices_that("answers_decisions")
    except Exception:  # noqa: BLE001 — 探不到能问的设备就在对话里问
        targets = []
    if not targets:
        return _in_conversation(what, session_id)
    from core.device_onboarding.conversation import announce_soon

    announce_soon(f"我在设备上问你了:要{what}吗?")
    scope = await _ask_on_device(what, effect, session_id, targets)
    if not scope:
        return {"success": False, "error": f"没有执行:没有在设备上批准{what}"}
    if scope != "once":
        get_grant_store().grant(node, action, GrantScope(scope), operator="device_decision")
    logger.info("[AUDIT] 设备动作经人批准 | %s | %s", what, scope)
    return None
