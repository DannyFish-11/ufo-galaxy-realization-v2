"""core/approval_gate.py —— 要人点头的操作，只有这一个入口。

为什么要有它
============
改之前仓库里「问人批准」各写一份：工具门（``core/tool_permissions.py`` + ``core/interaction/high_risk_confirmation.py``，
只问手表 / 手机）、节点拨盘门（``core/autonomy_policy.py``，排进审批队列等人去面板上批 —— 可面板上没有入口）、
智能家居、GitHub 插件各有一段「问完再试」。结果是：

* 默认的本地模式只有一台电脑，坐在电脑前的人**批不了**：工具门没连手表就直接拒，拨盘门的队列面板上看不见；
* 同一次节点调用可能先后问两遍；
* 「批过一次」各记各的，粒度只有「节点:动作」，「本会话」其实是进程存活期。

所有者的两条决定（``docs/GROUNDED_AGENT_DESIGN.md`` §0）：

1. **从哪发起就在哪批** —— 电脑发起的在电脑面板上批，手机 / 手表发起的在那台设备上批；
2. **批一次默认记「同一个动作 + 同一个对象」到这次会话结束**；「一直允许」要人明确选，面板能撤。

这里做的事
==========
:func:`request_approval` 一处做完：查授权 → 判在哪问 → 问 → 等 → 落授权。

* 授权按「动作 × 对象」记（:func:`node_key` / :func:`tool_key` + :func:`approval_target`），
  存在 :mod:`core.autonomy_policy` 的 ``GrantStore``（数据目录）；
* 在电脑上问：登记进同一个 ``ApprovalRegistry``，推一帧 ``{"type": "approvals"}``（只有摘要，**不带令牌** ——
  令牌由面板经带鉴权的 ``GET /api/v1/approvals`` 去取）、岛上一张「等你批准」卡，然后等人点；
  桌面外壳一个都没连着就不白等，退到手表 / 手机；也没有就立刻判不批准；
* 在手表 / 手机上问：:func:`core.interaction.high_risk_confirmation.confirm_high_risk_tool`（只有明确点了
  「批准」才算），发起的那台设备在线就只问它；
* **一次调用只问一次**：工具门批过的，同一次调用里的节点拨盘门认（:func:`take_pre_approval`）。

一律 fail closed：问的过程出任何错都判不批准，并说出原因。
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import logging
import os
import re
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional, Tuple

logger = logging.getLogger("Galaxy.ApprovalGate")

#: 面板上的三档（第一个是默认 —— 所有者的决定：记到这次会话结束）。
GRANT_CHOICES: Tuple[str, ...] = ("session", "once", "always")
DEFAULT_SCOPE = "session"

#: 工具门批过之后，同一次调用里的节点门在多久之内认它（秒）。一次调用的派发不会比这更久才到节点。
_PRE_APPROVAL_TTL_S = 300.0

_NODE_NUM = re.compile(r"^(?:Node_)?(\d+)(?:_|$)")

#: 参数里哪些键说的是「对哪个东西做」—— 按先后取第一个有值的。
_TARGET_KEYS: Tuple[str, ...] = (
    "device_id",
    "serial",
    "target_device",
    "entity_id",
    "scene_id",
    "path",
    "file_path",
    "filepath",
    "file",
    "directory",
    "dir",
    "window",
    "window_title",
    "app",
    "app_name",
    "package",
    "url",
    "repo",
    "name",
)
_PATH_KEYS = frozenset({"path", "file_path", "filepath", "file", "directory", "dir"})


# ── 动作与对象 ────────────────────────────────────────────────────────────────


def _canon_node(node_id: str) -> str:
    """``Node_08_Fetch`` / ``08`` / ``8`` 都是 8 号节点；认不出编号的照原样。"""
    m = _NODE_NUM.match((node_id or "").strip())
    return str(int(m.group(1))) if m else (node_id or "").strip()


def _sub_action(params: Any) -> str:
    """``control`` 这类分派型动作，真正做什么在 ``params["action"]`` 里（开灯和关灯不是同一个动作）。"""
    if isinstance(params, dict):
        sub = params.get("action")
        if isinstance(sub, str) and sub.strip():
            return sub.strip()
    return ""


def node_key(node_id: str, action: str, params: Any = None) -> str:
    """节点动作的授权键：``node:<编号>:<动作>[/<子动作>]``。"""
    key = f"node:{_canon_node(node_id)}:{(action or '').strip()}"
    sub = _sub_action(params)
    return f"{key}/{sub}" if sub else key


def _node_params(arguments: Any) -> Any:
    """节点工具的参数可能包在 ``params`` 里，也可能是平铺的（与派发那一侧同一个取法）。"""
    if isinstance(arguments, dict):
        inner = arguments.get("params", arguments)
        return inner if isinstance(inner, dict) else {}
    return {}


def tool_key(tool_name: str, arguments: Any = None) -> str:
    """工具的授权键。节点工具 ``node__<id>__<动作>`` 与节点门用同一个键 —— 这样「问一次」才对得上。"""
    if tool_name.startswith("node__"):
        parts = tool_name.split("__", 2)
        if len(parts) == 3:
            return node_key(parts[1], parts[2], _node_params(arguments))
    return f"tool:{tool_name}"


def approval_target(params: Any) -> str:
    """这次是对哪个东西做的（设备号、路径、实体……）。说不出就是空串 —— 那授权就是「这个动作」本身。"""
    if not isinstance(params, dict):
        return ""
    inner = params.get("params")
    for source in (params, inner if isinstance(inner, dict) else {}):
        for k in _TARGET_KEYS:
            v = source.get(k)
            if isinstance(v, (str, int)) and not isinstance(v, bool) and str(v).strip():
                text = str(v).strip()
                if k in _PATH_KEYS:
                    text = os.path.normcase(os.path.normpath(text))
                return text[:200]
    return ""


# ── 结果 ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ApprovalOutcome:
    """``approved`` 为 True 才继续。``source`` 说是谁批的：``grant:<档>`` / ``desktop`` / ``device`` / ``call``。"""

    approved: bool
    reason: str
    source: str = ""
    request_id: str = ""
    scope: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "approved": self.approved,
            "reason": self.reason,
            "source": self.source,
            "request_id": self.request_id,
            "scope": self.scope,
        }


# ── 一次调用只问一次 ──────────────────────────────────────────────────────────

_APPROVED_NOW: "contextvars.ContextVar[Tuple[Tuple[str, str, float], ...]]" = contextvars.ContextVar(
    "galaxy_approved_now", default=()
)


def _note_approved(key: str, target: str) -> None:
    now = time.time()
    kept = tuple(e for e in _APPROVED_NOW.get() if e[2] > now)
    _APPROVED_NOW.set(kept + ((key, target, now + _PRE_APPROVAL_TTL_S),))


def take_pre_approval(key: str, target: str) -> bool:
    """这一次调用在外层（工具门）已经批过 → 用掉它并返回 True。只在批准时由本模块记下，别处记不进来。"""
    now = time.time()
    hit = False
    kept: List[Tuple[str, str, float]] = []
    for entry in _APPROVED_NOW.get():
        if entry[2] <= now:
            continue
        if not hit and entry[0] == key and entry[1] == target:
            hit = True
            continue
        kept.append(entry)
    if hit:
        _APPROVED_NOW.set(tuple(kept))
    return hit


# ── 这次是不是有人在等（智能体的一次工具调用 / 一次请求） ───────────────────────

_INTERACTIVE: "contextvars.ContextVar[bool]" = contextvars.ContextVar("galaxy_approval_interactive", default=False)
_LABEL: "contextvars.ContextVar[str]" = contextvars.ContextVar("galaxy_approval_label", default="")


@contextlib.contextmanager
def interactive() -> Iterator[None]:
    """智能体的工具调用包在这里面：节点门遇到要批的动作就当场问，而不是排进队列让调用方自己重试。"""
    token = _INTERACTIVE.set(True)
    try:
        yield
    finally:
        _INTERACTIVE.reset(token)


def mark_interactive() -> None:
    """把当前上下文标成「智能体的工具调用」(``OpenClawd._dispatch_tool_call`` 开头调)。

    不复位:主循环每次工具调用都在自己的任务里(``asyncio.wait_for``),标记随任务结束;直接 await 的调用方
    (Agent 工厂的工具循环)本身就是智能体那一轮,之后的节点调用同样有人在等。
    """
    _INTERACTIVE.set(True)


@contextlib.contextmanager
def label(what: str) -> Iterator[None]:
    """给接下来那一次「问人」一句人话（「打开 客厅灯」），比「Node_27_SmartHome.control」好认。"""
    token = _LABEL.set(str(what or ""))
    try:
        yield
    finally:
        _LABEL.reset(token)


def _current_session() -> Any:
    try:
        from core.liminal_activity import current_runtime_session

        return current_runtime_session()
    except Exception:  # noqa: BLE001
        return None


def caller_is_interactive() -> bool:
    """有人在等这次调用的结论：在智能体的工具调用里，或在一次请求的运行时会话里。"""
    return _INTERACTIVE.get() or _current_session() is not None


def current_session_id() -> str:
    """这一段对话的 id —— 「本会话」授权绑的就是它。

    先认智能体主循环记在上下文里的对话 id（与工具门传进来的是同一个）；不在主循环里时退到运行时会话。
    只读已经加载了的模块，不为这一句去 import 主循环。
    """
    agent = sys.modules.get("core.openclawd")
    var = getattr(agent, "_CTX_CURRENT_SESSION_ID", None) if agent is not None else None
    if var is not None:
        try:
            sid = var.get()
        except LookupError:
            sid = None
        if sid:
            return str(sid)
    session = _current_session()
    if session is None:
        return ""
    return str(getattr(session, "runtime_session_id", "") or "")


# ── 在哪问 ───────────────────────────────────────────────────────────────────


def desktop_reachable() -> bool:
    """桌面外壳（面板或覆盖层）此刻连着吗。连着才在电脑上问 —— 没人看得见的卡等于白等一个超时周期。"""
    try:
        from core.lumiv_websocket_bridge import GalaxyPresenceBridge

        return bool(getattr(GalaxyPresenceBridge.get_instance(), "_clients", None))
    except Exception:  # noqa: BLE001
        return False


def _origin_device() -> str:
    """别的设备发起的请求：那台设备的 id；电脑发起的 / 说不清的：空串。"""
    session = _current_session()
    if session is None or getattr(session, "desktop_originated", True):
        return ""
    return str(getattr(session, "origin_device_id", "") or "")


# ── 主入口 ───────────────────────────────────────────────────────────────────


def _store() -> Any:
    from core.autonomy_policy import get_grant_store

    return get_grant_store()


def _wait_s(explicit: Optional[float]) -> float:
    if explicit is not None:
        return max(1.0, float(explicit))
    from core.interaction.high_risk_confirmation import _timeout_s

    return _timeout_s()


async def request_approval(
    *,
    key: str,
    target: str = "",
    what: str = "",
    risk: str = "high",
    session_id: str = "",
    params: Optional[Dict[str, Any]] = None,
    timeout_s: Optional[float] = None,
) -> ApprovalOutcome:
    """问一下人：这件事做不做。只有明确批准（或已有对得上的授权）才返回 ``approved=True``。"""
    sid = session_id or current_session_id()
    what = _LABEL.get() or what or key
    try:
        scope = _store().check_key(key, target, sid)
    except Exception as exc:  # noqa: BLE001 — 授权账读不出来就当没有，照常去问
        logger.warning("授权记录读取失败(照常去问): %s", exc)
        scope = None
    if scope:
        _note_approved(key, target)
        return ApprovalOutcome(True, f"已有授权({_SCOPE_TEXT.get(scope, scope)})", f"grant:{scope}", scope=scope)

    origin = _origin_device()
    if not origin and desktop_reachable():
        outcome = await _ask_desktop(key, target, what, risk, sid, params, _wait_s(timeout_s))
    else:
        outcome = await _ask_devices(key, target, what, risk, sid, origin, _wait_s(timeout_s))
        if not outcome.approved and origin and outcome.source == "unreachable" and desktop_reachable():
            # 发起的那台设备这会儿问不到 —— 退回主人的电脑
            outcome = await _ask_desktop(key, target, what, risk, sid, params, _wait_s(timeout_s))
    if outcome.approved:
        _note_approved(key, target)
    return outcome


_SCOPE_TEXT = {"session": "本会话", "once": "只这一次", "always": "一直允许"}


async def _ask_devices(
    key: str, target: str, what: str, risk: str, sid: str, origin: str, wait_s: float
) -> ApprovalOutcome:
    """在手表 / 手机上问。批了落「本会话」授权（手表上只有批准 / 不要两个键）。"""
    from core.interaction import high_risk_confirmation as hrc

    try:
        result = await hrc.confirm_high_risk_tool(
            tool_name=what,
            risk_level=risk,
            session_id=sid,
            device_id=origin,
            timeout_s=wait_s,
            devices=[origin] if origin else None,
        )
    except Exception as exc:  # noqa: BLE001 — 问的过程出错 = 不批准
        logger.warning("在设备上问批准时出错(判不批准): %s", exc)
        return ApprovalOutcome(False, f"询问过程出错: {exc}", "device")
    if not result.approved:
        source = "unreachable" if getattr(result, "source", "") == "unreachable" else "device"
        return ApprovalOutcome(False, result.reason, source, getattr(result, "decision_id", "") or "")
    try:
        _store().grant_key(key, DEFAULT_SCOPE, target=target, session_id=sid, operator="device")
    except Exception as exc:  # noqa: BLE001 — 授权没记上不影响这一次
        logger.warning("授权没记上(这一次照样执行): %s", exc)
    return ApprovalOutcome(True, result.reason, "device", getattr(result, "decision_id", "") or "", DEFAULT_SCOPE)


def _risk_level(risk: str) -> Any:
    from core.control_plane.security_interceptor import RiskLevel

    text = str(risk or "").lower()
    if "critical" in text:
        return RiskLevel.CRITICAL
    if "moderate" in text or "medium" in text or "read" in text:
        return RiskLevel.MEDIUM
    return RiskLevel.HIGH


async def _ask_desktop(
    key: str,
    target: str,
    what: str,
    risk: str,
    sid: str,
    params: Optional[Dict[str, Any]],
    wait_s: float,
) -> ApprovalOutcome:
    """在电脑面板上问：登记 → 推摘要 + 岛卡 → 等人点。超时 / 被取消都判不批准，并把这一条收掉。"""
    from core.control_plane._globals import get_approval_registry
    from core.control_plane.security_interceptor import ApprovalRequest, ApprovalStatus

    registry = get_approval_registry()
    req = ApprovalRequest(
        action=what,
        risk_level=_risk_level(risk),
        requestor="approval_gate",
        context={
            "approval_key": key,
            "target": target,
            "what": what,
            "risk": str(risk or ""),
            "session_id": sid,
            "surface": "desktop",
            "waited": True,
            "wait_s": wait_s,
            "params_preview": {k: str(v)[:120] for k, v in (params or {}).items()},
            "grant_choices": list(GRANT_CHOICES),
        },
    )
    event = registry._register(req)  # noqa: SLF001 — 与 SecurityInterceptor 同一入册路径
    post_approval_card(req.request_id, what)
    publish_pending()
    try:
        await asyncio.wait_for(event.wait(), timeout=wait_s)
    except asyncio.TimeoutError:
        registry._resolve(  # noqa: SLF001
            req.request_id, ApprovalStatus.TIMED_OUT, resolved_by="approval_gate", deny_reason="没有人点"
        )
    except asyncio.CancelledError:
        registry._resolve(  # noqa: SLF001
            req.request_id, ApprovalStatus.CANCELLED, resolved_by="approval_gate", deny_reason="这次调用被取消了"
        )
        raise
    finally:
        remove_approval_card(req.request_id)
        publish_pending()

    if req.status == ApprovalStatus.GRANTED:
        scope = str((req.context or {}).get("granted_scope") or DEFAULT_SCOPE)
        return ApprovalOutcome(True, "你在面板上批准了", "desktop", req.request_id, scope)
    if req.status == ApprovalStatus.DENIED:
        why = f":{req.deny_reason}" if req.deny_reason else ""
        return ApprovalOutcome(False, f"你在面板上拒绝了{why}", "desktop", req.request_id)
    if req.status == ApprovalStatus.TIMED_OUT:
        return ApprovalOutcome(False, f"在面板上等了 {int(wait_s)} 秒，没有人批", "desktop", req.request_id)
    return ApprovalOutcome(False, f"没有批准(状态 {req.status.value})", "desktop", req.request_id)


# ── 工具门(OpenClawd 内联派发用;CanonicalDispatcher 同一套,见它的 dispatch) ──────────


async def check_tool_call(
    checker: Any, tool_name: str, arguments: Any, *, session_id: str = "", device_id: str = ""
) -> Optional[Dict[str, Any]]:
    """按风险表判这次工具调用;要人点头的去问。返回 None = 放行,否则是不执行的理由(并入工具结果)。

    门禁自身出错一律不执行 —— 原先这里是 ``except: 放行``,门坏了等于门开着。
    """
    try:
        check = checker.check(tool_name=tool_name, session_id=session_id, device_id=device_id)
        if not check.allowed:
            logger.warning("工具调用被拒绝: %s — %s", tool_name, check.reason)
            return {"error": f"权限拒绝: {check.reason}"}
        if not check.requires_confirmation:
            return None
        outcome = await request_approval(
            key=tool_key(tool_name, arguments),
            target=approval_target(arguments),
            what=tool_name,
            risk=str(check.risk_level),
            session_id=session_id,
            params=arguments if isinstance(arguments, dict) else None,
        )
    except Exception as exc:  # noqa: BLE001 — 门坏了不等于门开着
        logger.warning("权限检查出错,不执行 %s: %s", tool_name, exc)
        return {"error": f"权限检查出错,没有执行: {exc}"}
    if outcome.approved:
        logger.info(
            "[AUDIT] 要人点头的工具已放行: %s (来源=%s, request_id=%s)", tool_name, outcome.source, outcome.request_id
        )
        return None
    return {
        "needs_confirmation": True,
        "risk_level": str(check.risk_level),
        "error": f"操作 [{tool_name}] 未获用户确认:{outcome.reason}",
    }


# ── 推给面板与岛 ──────────────────────────────────────────────────────────────


def card_id(request_id: str) -> str:
    """一条待批请求在岛上的卡 id(在等的、排队的同一种)。"""
    return f"approval:{request_id}"


def post_approval_card(request_id: str, what: str) -> None:
    """岛上推一张「等你批准」(点了打开面板)。排队的请求也推 —— 没人在等,更容易被忘掉。"""
    _post_card(card_id(request_id), what)


def remove_approval_card(request_id: str) -> None:
    _remove_card(card_id(request_id))


def _post_card(cid: str, what: str) -> None:
    from core.island_cards import post_card

    post_card(
        cid,
        kind="approval",
        title="等你批准",
        subtitle=what,
        body="在面板上点「批准」才会执行",
        tone="warning",
        priority="high",
        ttl_s=None,
        action="panel",
    )


def _remove_card(cid: str) -> None:
    from core.island_cards import remove_card

    remove_card(cid)


def pending_summary() -> List[Dict[str, Any]]:
    """面板该看到的待批清单 —— 只有摘要，没有令牌。"""
    try:
        from core.control_plane._globals import get_approval_registry

        pending = get_approval_registry().list_pending()
    except Exception:  # noqa: BLE001
        return []
    now = time.time()
    rows: List[Dict[str, Any]] = []
    for req in pending:
        ctx = req.context or {}
        asked_at = req.requested_at.timestamp()
        wait_s = ctx.get("wait_s")
        rows.append(
            {
                "request_id": req.request_id,
                "what": str(ctx.get("what") or req.action),
                "target": str(ctx.get("target") or ""),
                "risk": str(req.risk_level.value),
                "waiting": bool(ctx.get("waited")),
                "requested_at": asked_at,
                "expires_in_s": (
                    round(max(0.0, asked_at + float(wait_s) - now), 1) if isinstance(wait_s, (int, float)) else None
                ),
            }
        )
    return rows


_seq_lock = threading.Lock()
_seq = 0
_BACKGROUND: set = set()
_loop: Optional[asyncio.AbstractEventLoop] = None


def frame() -> Dict[str, Any]:
    with _seq_lock:
        seq = _seq
    return {"type": "approvals", "payload": {"pending": pending_summary(), "seq": seq}}


def publish_pending() -> None:
    """待批清单变了：推一帧给桌面外壳。推不出去只是面板晚一点知道（打开时会再拉），永不抛出。"""
    global _seq, _loop
    with _seq_lock:
        _seq += 1
    try:
        loop: Optional[asyncio.AbstractEventLoop] = asyncio.get_running_loop()
        _loop = loop
    except RuntimeError:
        loop = None
    if loop is None:
        saved = _loop
        if saved is not None and saved.is_running() and not saved.is_closed():
            with contextlib.suppress(RuntimeError):
                saved.call_soon_threadsafe(_spawn, saved)
        return
    _spawn(loop)


def _spawn(loop: asyncio.AbstractEventLoop) -> None:
    try:
        from core.lumiv_websocket_bridge import GalaxyPresenceBridge

        task = loop.create_task(GalaxyPresenceBridge.get_instance()._ws_broadcast(frame()))
        _BACKGROUND.add(task)
        task.add_done_callback(_BACKGROUND.discard)
    except Exception as exc:  # noqa: BLE001
        logger.debug("待批清单没推出去: %s", exc)


# ── 给工具超时预算用：这次调用会不会停下来等人 ──────────────────────────────────


def may_wait_for_a_human(tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> bool:
    """只读判断（不消费任何授权）：这次工具调用会不会在中途停下来问人。

    会的话，外层的单工具超时要留出等人的时间 —— 否则批准卡刚推上面板，30 秒就被外层取消。
    """
    args = arguments or {}
    try:
        from core.autonomy_policy import would_ask

        if tool_name.startswith("node__"):
            parts = tool_name.split("__", 2)
            if len(parts) == 3:
                params = _node_params(args)
                return would_ask(parts[1], parts[2], params=params, session_id=current_session_id())
        if tool_name in ("home__control", "home__scene"):
            from core.smart_home_tools import NODE_ID

            action = "scene" if tool_name == "home__scene" else "control"
            params = {"action": args.get("action")} if action == "control" else {}
            return would_ask(NODE_ID, action, params=params, session_id=current_session_id())
    except Exception:  # noqa: BLE001 — 判不出来就按会问算：多等一会儿不出错，少等会把人的批准掐掉
        return True
    return False


# ── 节点门(core.node_invocation 调) ─────────────────────────────────────────


@dataclass(frozen=True)
class NodeGateVerdict:
    proceed: bool
    error: str = ""
    denial: Optional[Dict[str, Any]] = None


async def gate_node_call(node_id: str, action: str, params: Any) -> NodeGateVerdict:
    """节点拨盘门(``GALAXY_AUTONOMY``):这次调用要不要先问人、问了批没批。

    * 同一次调用在工具门已经批过 → 放行(一次调用只问一次);
    * 不用问 / 已有对得上的授权 → 放行;
    * 有人在等(智能体的工具调用、一次请求里)→ 当场问(:func:`request_approval`),批了放行,没批照实说;
    * 没有人在等(REST 直调、后台)→ 排进审批队列(面板上看得见),返回 ``approval_required``,批了之后重试即通过。
    """
    from core.autonomy_policy import ensure_approval_request, evaluate_autonomy, is_read_action

    params = params if isinstance(params, dict) else {}
    key = node_key(node_id, action, params)
    target = approval_target(params)
    if take_pre_approval(key, target):
        return NodeGateVerdict(True)
    sid = current_session_id()
    decision = evaluate_autonomy(node_id, action, params=params, target=target, session_id=sid)
    if not decision.needs_approval:
        return NodeGateVerdict(True)
    what = _LABEL.get() or (f"{node_id}.{action}" + (f"({target})" if target else ""))
    if caller_is_interactive():
        outcome = await request_approval(
            key=key,
            target=target,
            what=what,
            risk="moderate" if is_read_action(action) else "high",
            session_id=sid,
            params=params,
        )
        if outcome.approved:
            take_pre_approval(key, target)  # 记下的这一笔就是给这一次的,别留着
            return NodeGateVerdict(True)
        return NodeGateVerdict(
            False,
            f"approval_denied: {what} 没有执行:{outcome.reason}",
            {"approval_denied": {**decision.to_dict(), **outcome.to_dict()}},
        )
    pending = ensure_approval_request(node_id, action, params)
    return NodeGateVerdict(
        False,
        f"approval_required: {node_id}.{action} 需人工审批(自治档位={decision.level});"
        f"在面板上批准后重试即可。approval_id={pending.get('request_id')}",
        {"approval_required": {**decision.to_dict(), **pending}},
    )


__all__ = [
    "ApprovalOutcome",
    "DEFAULT_SCOPE",
    "NodeGateVerdict",
    "GRANT_CHOICES",
    "approval_target",
    "caller_is_interactive",
    "card_id",
    "check_tool_call",
    "current_session_id",
    "desktop_reachable",
    "frame",
    "gate_node_call",
    "interactive",
    "label",
    "mark_interactive",
    "may_wait_for_a_human",
    "node_key",
    "pending_summary",
    "post_approval_card",
    "publish_pending",
    "remove_approval_card",
    "request_approval",
    "take_pre_approval",
    "tool_key",
]
