"""core/device_boundaries.py — 给设备下发动作时,代码守的边界。只有这七条。

设计见 ``docs/DEVICE_SELF_DESCRIPTION_DESIGN.md`` 第 5 节,这张表和下面的函数一一对应(:data:`BOUNDARIES`)。
清单之外的事(发给哪台、怎么说、失败了重试还是换设备还是问人)都交给模型,这里不替它挑设备。

== ================================= ======================================================================
#  边界                               函数
== ================================= ======================================================================
1  成员资格                            :func:`member`:在名册里;讲 AIP 的设备此刻连着;开了设备准入的,接入时批准过
2  权限门与自治档位,按 ``effect`` 判    :func:`permission`(表见下)
3  参数合法                            :func:`params_ok`:按设备自述里这个动作的 ``params`` 校验,不合法不发,原因交回模型
4  主动打扰有额度                      :func:`interrupt_budget`:智能体自发的 ``notify`` 计入每小时额度;有设备报了
                                       「此刻明确别打扰」时,自发的不发。人在等结果的请求不算主动打扰
5  每台设备串行;每次下发必有结果;      :func:`one_at_a_time`(串行、必有结果)与 :func:`record_start` / :func:`record_end`
   全部记进任务流程图                   (任务流程图)
6  结果以设备回的为准                  :func:`as_reported`:设备回的成没成、原因,原样交给模型,不替它补成「成了」
7  隐私                                :func:`kept`:中心记下的只有成没成和设备说的原因,不留设备回的数据
                                       (心率、通讯录、截屏);做完的多步计划不留每一步的结果(``core/task_plan.py``)
== ================================= ======================================================================

下发路径(``core/device_onboarding/agent_tools._invoke`` → 规范派发 ``_dispatch_device``)的顺序:
先 1(不在线、没批准的设备,不该先去问人要不要做);讲 AIP 的设备再过 :func:`gate`:3 → 4 → 2
(便宜的先查,问人放最后);发的时候 5;结果 6;记账 7。

第 2 条按 ``effect`` 怎么判:

  ========  ============  ===================  ==========
  effect    谨慎 safe      引导 guided(默认)    自主
  ========  ============  ===================  ==========
  read      问             直接做                直接做
  notify    问             直接做(计入额度)      直接做(计入额度)
  act       问             问(可选本会话/永久)  直接做
  send      高风险确认      高风险确认            高风险确认
  danger    高风险确认      高风险确认            高风险确认
  ========  ============  ===================  ==========

``needs_human`` 的动作设备上那一下就是确认,中心不再另外问。设备没说 ``effect`` 的:动作名一看就是读的
(``get_*``、``list_*`` 这类)按读,其余按改状态 —— 拿不准的往严里算。

* **问**:有声明能回答提问的设备在线,就在那上面问(不要 / 仅此次 / 本会话 / 永久允许),选了本会话或永久
  就记一条授权(``core.autonomy_policy`` 的 ``GrantStore``,经 ``/api/v1/approval-grants`` 能列出、撤销),下次不再问;
  没有就在对话里问,人答应了智能体再调一次。
* **高风险确认**:只弹到声明了能回答提问的设备上,要人点「批准」;嘴上说好不算,问不到人就不做。

一律 fail closed:问不到、超时、含糊的回答,都当没批准。
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any, Awaitable, Callable, Deque, Dict, Optional, Tuple

logger = logging.getLogger("Galaxy.DeviceBoundaries")

GO, ASK, CONFIRM = "go", "ask", "confirm"

#: 设计文档第 5 节那张表:编号 → 守这一条的函数名。改了表就要改这里,测试逐条对照。
BOUNDARIES: Dict[int, Tuple[str, ...]] = {
    1: ("member",),
    2: ("permission",),
    3: ("params_ok",),
    4: ("interrupt_budget",),
    5: ("one_at_a_time", "record_start", "record_end"),
    6: ("as_reported",),
    7: ("kept",),
}

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


def _name(device_id: str) -> str:
    d = _device(device_id)
    name = str(getattr(d, "device_name", "") or "")
    return name if name and name != "unknown" else device_id


# ── 1 成员资格 ───────────────────────────────────────────────────────────────────


def member(device_id: str) -> Optional[Dict[str, Any]]:
    """能不能给这台设备下发:在名册里;讲 AIP 的设备此刻连着;开了设备准入的,接入时批准过。能发返回 None。"""
    from core.device_onboarding.taxonomy import is_native_transport
    from core.participant_admission import approval_required

    d = _device(device_id)
    if d is None:
        return {"success": False, "error": f"没有这个成员:{device_id}(候选要先 devices__join)"}
    if d.bridge_id or not (is_native_transport(d.transport) or not d.transport):
        return None  # 经桥或驱动接入的设备:通不通由那座桥说,批准就是主人把它加进来那一下
    try:
        from core.unified.connection_manager import get_unified_connection_manager

        connected = get_unified_connection_manager().is_device_connected(device_id)
    except Exception:  # noqa: BLE001
        connected = False
    if not connected:
        return {"success": False, "error": f"「{_name(device_id)}」现在不在线,没有发"}
    if approval_required() and (d.metadata or {}).get("admission_approved") is not True:
        return {
            "success": False,
            "error": f"「{_name(device_id)}」还没被批准接入(开了设备准入),它连着但不给它下发动作;先让主人批准",
        }
    return None


# ── 2 权限门与自治档位 ──────────────────────────────────────────────────────────


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
    shown = ", ".join(f"{k}={str(v)[:40]}" for k, v in sorted((params or {}).items()))
    name = _name(device_id)
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


async def permission(
    device_id: str, action: str, params: Dict[str, Any], spec: Dict[str, Any], session_id: str = ""
) -> Optional[Dict[str, Any]]:
    """按动作的 ``effect`` / ``needs_human`` 与自治档位判直接做、问还是高风险确认。可以做返回 None。"""
    from core.autonomy_policy import GrantScope, autonomy_level, get_grant_store

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


# ── 3 参数合法 ───────────────────────────────────────────────────────────────────


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


def params_ok(spec: Dict[str, Any], action: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """参数不合设备说的格式就不发,把原因和格式交回模型。合格返回 None。"""
    problem = check_params(spec, params)
    if not problem:
        return None
    return {
        "success": False,
        "error": f"参数不合「{action}」要的格式,没有发给设备:{problem}",
        "params_schema": spec.get("params"),
    }


# ── 4 主动打扰有额度 ────────────────────────────────────────────────────────────

#: 额度窗口(秒)
INTERRUPT_WINDOW_S = 3600.0
_interrupts: Deque[float] = deque()
_interrupts_lock = threading.Lock()


def _proactive() -> bool:
    """这一次是不是智能体自发的:在一次请求里,且这次请求没人在等结果(自发注意力、定时心跳、主动感知)。"""
    try:
        from core.liminal_activity import current_runtime_session
        from core.presence_line import BACKGROUND_SOURCES

        rs = current_runtime_session()
    except Exception:  # noqa: BLE001
        return False
    return rs is not None and str(getattr(rs, "source", "") or "") in BACKGROUND_SOURCES


def _interrupt_limit() -> int:
    """和自发开口同一个额度设置(``GALAXY_AMBIENT_SPEAK_PER_HOUR``):在设备上弹一句和在电脑上说一句是同一种打扰。"""
    from core.ambient_governance import AmbientLimits

    return AmbientLimits.from_env().speak_per_hour


def interrupt_budget(device_id: str, effect: str, *, now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """智能体自发的 ``notify``:有设备报了「此刻明确别打扰」就不发;这一小时的额度用完了也不发。
    放行的这一次记一笔。人在等结果的请求不算主动打扰,不过这一条。可以发返回 None。"""
    if effect != "notify" or not _proactive():
        return None
    try:
        from core.interruptibility_registry import get_interruptibility_registry

        who = get_interruptibility_registry().blocking_source()
    except Exception:  # noqa: BLE001
        who = ""
    if who:
        return {"success": False, "error": f"{who}报告此刻明确不宜打扰,这条是自发的,没有发给「{_name(device_id)}」"}
    ts = now if now is not None else time.monotonic()
    limit = _interrupt_limit()
    with _interrupts_lock:
        while _interrupts and ts - _interrupts[0] >= INTERRUPT_WINDOW_S:
            _interrupts.popleft()
        if len(_interrupts) >= limit:
            wait_min = int((_interrupts[0] + INTERRUPT_WINDOW_S - ts) // 60) + 1
            return {
                "success": False,
                "error": f"这一小时自发打扰人的额度用完了({len(_interrupts)}/{limit}),约 {wait_min} 分钟后恢复;没有发",
            }
        _interrupts.append(ts)
    return None


def reset_interrupt_budget() -> None:
    """测试用。"""
    with _interrupts_lock:
        _interrupts.clear()


async def gate(device_id: str, action: str, params: Dict[str, Any], session_id: str = "") -> Optional[Dict[str, Any]]:
    """讲 AIP 的设备下发前过 3 → 4 → 2(便宜的先查,问人放最后)。可以发返回 None;不能发返回交回智能体的结果。"""
    spec = action_spec(device_id, action)
    return (
        params_ok(spec, action, params)
        or interrupt_budget(device_id, effect_of(spec, action))
        or await permission(device_id, action, params, spec, session_id)
    )


# ── 5 每台设备串行;每次下发必有结果;全部记进任务流程图 ───────────────────────────


async def one_at_a_time(
    device_id: str, job: Callable[[], Awaitable[Any]], *, timeout: Optional[float] = None
) -> Dict[str, Any]:
    """在这台设备的队列里做(前面的做完才轮到它,不同设备照样并行),一定回一个结果:
    成了、没成的原因,或做了多久没做完。"""
    from core.device_queue import DEFAULT_TIMEOUT_S, run_on_device

    r = await run_on_device(device_id, job, timeout=timeout or DEFAULT_TIMEOUT_S)
    if not isinstance(r, dict):
        return {"success": False, "error": f"「{_name(device_id)}」那边没有回结果"}
    if "success" not in r:
        r = {**r, "success": not r.get("error")}
    if r["success"] is False and not r.get("error"):
        r = {**r, "error": "没有成功,也没说原因"}
    return r


def record_start(device_id: str, action: str, session_id: str = "") -> str:
    """一次下发记进任务流程图,返回节点 id(记不上返回空串,只是观测,不挡下发)。"""
    from core.device_onboarding.device_card import record_dispatch

    return record_dispatch(device_id, action, session_id)


def record_end(task_id: str, ok: bool, payload: Any = None, error: str = "") -> None:
    """这次下发的结果记进任务流程图 —— 记什么由第 7 条(:func:`kept`)定。"""
    from core.device_onboarding.device_card import record_result

    summary, why = kept(ok, payload, error)
    record_result(task_id, ok, summary=summary, error=why)


# ── 6 结果以设备回的为准 ────────────────────────────────────────────────────────


def as_reported(raw: Any) -> Tuple[bool, Any, str]:
    """设备回的话 → (成没成, 设备回的内容, 没成的原因)。只看设备自己说的:它说没成就是没成,原因用它的原话;
    没回内容、回的不是成功也不算成了。"""
    if not isinstance(raw, dict):
        return False, raw, "设备没有回结果"
    payload = raw.get("payload", raw)
    if "payload" not in raw and raw.get("error"):
        return False, payload, str(raw["error"])
    if isinstance(payload, dict) and payload.get("success") is False:
        return False, payload, str(payload.get("error") or raw.get("error") or "设备说没做成,没说原因")
    return True, payload, ""


# ── 7 隐私 ───────────────────────────────────────────────────────────────────────


def kept(ok: bool, payload: Any = None, error: str = "") -> Tuple[str, str]:
    """中心自己记下的(任务流程图、设备卡的「最近」):只有成没成和设备说的原因。设备回的数据 —— 心率、
    通讯录、截屏 —— 只交给这一次调用它的智能体,不留副本。``payload`` 收进来只为说明:它不进记录。"""
    del payload
    return ("ok", "") if ok else ("", str(error or "")[:200])
