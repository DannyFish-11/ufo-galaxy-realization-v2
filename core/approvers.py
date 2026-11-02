"""core/approvers.py —— 哪台设备能回答「这件事做不做」：一处说了算，不按设备种类写死（第 15 轮，所有者 2026-11-02）。

所有者的话：「危险操作需授权，就发给那个设备，或者由哪个设备来授权；接受各种生态识别的设备，不用每一次都要自己加一种设备。」

原先「能问谁」是两张写死的设备种类表（``wear_os`` / ``watch`` …… 与 ``android`` / ``phone`` ……）：
* 来一种新生态的设备（别家的手表、平板、车机、家居面板），要改代码把它的种类名加进表里；
* 表里的手机其实不会答 —— 安卓 App 只定义了 ``decision_request``、没有处理（第 14 轮只读核对安卓仓），
  手机发起的危险动作问过去没人显示，人白等一个确认超时。

现在按**设备自己的声明**：设备在登记（``device_register``）、报能力（``capability_report``）或接入（``POST /api/v1/participants/register``）时说一句
``"approvals": true``（顶层、``payload`` 或 ``metadata`` 里都认），意思是「我收得到 ``decision_request``、会经
``human_input`` 回 ``decision_id`` 与 ``selected_option``」。哪个生态、什么种类都一样，不用改这里。
声明了 ``false`` 就不问它。

没声明的设备：只认**已经发出去的客户端里确实会答的**那一类 —— 手表（galaxy-wearos 一直处理 ``decision_request``，
它还没开始发这句声明）。这是给旧客户端的兼容，不是扩展点：新设备一律声明，不往这里加种类。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

#: 设备声明自己能回答批准时用的字段名
DECLARATION = "approvals"
#: 存进设备登记（UDM）元数据里的那一位
METADATA_FLAG = "answers_approvals"


def _truthy(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("", "0", "false", "no", "off", "none"):
        return False
    return True  # "1" / "true" / 协议版本串（如 "hitl/1"）都算声明了


def declared(frame: Dict[str, Any]) -> Optional[bool]:
    """这一帧（能力报告 / 接入请求）里，设备有没有说自己能回答批准。没说是 ``None``。"""
    if not isinstance(frame, dict):
        return None
    payload = frame.get("payload") if isinstance(frame.get("payload"), dict) else {}
    meta = frame.get("metadata") if isinstance(frame.get("metadata"), dict) else {}
    pmeta = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    for source in (frame, payload, meta, pmeta):
        if DECLARATION in source:
            return _truthy(source.get(DECLARATION))
    return None


def remember(device_id: str, frame: Dict[str, Any], *, source: str) -> Optional[bool]:
    """设备说了，就记进它的登记（UDM 元数据）。返回它说的（没说是 ``None``，什么都不记）。永不抛出。"""
    said = declared(frame)
    if said is None or not device_id:
        return said
    try:
        from core.unified.device_manager import get_unified_device_manager

        get_unified_device_manager().upsert_device_state(device_id, {"metadata": {METADATA_FLAG: said}}, source=source)
    except Exception:  # noqa: BLE001 — 记不上：下次报能力再记
        pass
    return said


def _metadata(device_id: str) -> Dict[str, Any]:
    try:
        from core.unified.device_manager import get_unified_device_manager

        device = get_unified_device_manager().get_device(device_id)
        meta = getattr(device, "metadata", None)
        return meta if isinstance(meta, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _shipped_client_answers(device_type: str) -> bool:
    """没声明的设备：已经发出去的客户端里确实会答的那一类（手表）。只为旧客户端兼容，不是扩展点。"""
    t = (device_type or "").strip().lower()
    return "watch" in t or "wear" in t


def _raw_type(device_id: str) -> str:
    """设备自己报的种类原话(UCM 连接元数据里登记时报的,其次 UDM 元数据)。UDM 的大类太粗(手表也记成 android),不用。"""
    try:
        from core.unified.connection_manager import get_unified_connection_manager

        info = get_unified_connection_manager().get_connection(device_id)
        meta = getattr(info, "metadata", None) or {}
        raw = str(meta.get("device_type") or meta.get("platform") or "")
        if raw:
            return raw
    except Exception:  # noqa: BLE001
        pass
    meta = _metadata(device_id)
    return str(
        meta.get("reported_type")
        or meta.get("participant_kind")
        or meta.get("device_type")
        or meta.get("platform")
        or ""
    )


def _not_yet_approved(device_id: str) -> bool:
    """开了设备准入闸(``GALAXY_REQUIRE_DEVICE_APPROVAL``)、这台还没被主人批准(被降为 ``control_only``)。

    没被批准的设备说什么都不能替主人批危险动作 —— 声明了也不算。准入闸默认关:关着时拿着有效令牌接进来的就是成员。
    闸开着时只认「有一段在跑的附着会话、参与档是 ``join_runtime``」的:降档是准入闸唯一留下的痕迹,
    分不清是被闸降的还是设备自己选的 ``control_only`` —— 一律不问它,宁可少一台能批的(回落到电脑面板)。
    """
    try:
        from core.participant_admission import should_gate_unapproved

        if not should_gate_unapproved({"device_approved": False}):
            return False  # 准入闸关着
        from core.attached_runtime_session_registry import lookup_session_by_device

        entry = lookup_session_by_device(device_id)
        return entry is None or str(getattr(entry, "posture", "") or "") != "join_runtime"
    except Exception:  # noqa: BLE001 — 判不了就当没批准:批准这件事宁可少一台能批的
        return True


def approval_capability(device_id: str, device_type: str = "") -> Optional[bool]:
    """这台设备能不能回答批准:``True`` / ``False``;对它一无所知(没登记、没报种类)是 ``None``。

    先看它自己的声明(``approvals``);没声明才看它报的种类是不是已知会答的旧客户端(手表)。
    开了准入闸、还没被主人批准的设备一律 ``False``。
    """
    if _not_yet_approved(device_id):
        return False
    flag = _metadata(device_id).get(METADATA_FLAG)
    if isinstance(flag, bool):
        return flag
    t = (device_type or _raw_type(device_id)).strip().lower()
    if not t or t == "unknown":
        return None
    return _shipped_client_answers(t)


def answers_approvals(device_id: str, device_type: str = "") -> bool:
    """能确定它会回答批准(声明了,或是已知会答的旧客户端)。去找「问谁」时用 —— 说不清的不问。"""
    return approval_capability(device_id, device_type) is True


__all__ = ["DECLARATION", "METADATA_FLAG", "answers_approvals", "approval_capability", "declared", "remember"]
