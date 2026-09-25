"""core/participant_admission.py — 参与方的通用接入：注册、进 mesh、提交任务（R7）。

要解决什么
==========
一台设备要成为中心的「相对主体」，今天只有一条路：说安卓协议，走
``galaxy_gateway/android/handlers/registration.py``。那条路里真正做事的步骤 ——
入口鉴权与身份闸、写 UDM（设备的事实来源）、进 mesh（peer 表、耐久 mesh 会话、
附着运行时会话、Body Mesh 角色）、能力同化 —— 没有一步是安卓特有的，却全都长在
安卓命名的模块里。于是一台 iPad、一台 Linux 盒子、一块自研手表想接进来，要么冒充
安卓，要么宿主再复制一套 handler。

本模块把这些步骤按**设备自己声明的描述**（:class:`ParticipantDescriptor`）组合成
一条通用接入路径，全程不经过任何安卓命名的模块：

* :func:`admit_participant` —— 鉴权 → 身份闸 → 写 UDM → mesh peer → 耐久 mesh 会话 →
  附着运行时会话 → Body Mesh 角色 → 能力同化 → 生命周期事件。
* :func:`submit_participant_task` —— 已接入的参与方提交一句自然语言任务，交给
  ``DesktopPresenceRuntime.handle_request``（唯一收口，冻结守则 R1.1）。入口标为
  ``participant_task``，由 :mod:`core.presence_line` 判为远端身体：桌面不跟着动。

鉴权与准入闸原样搬自安卓注册路径（那边现在 import 这里），语义逐位不变：
配对令牌必须绑定本 ``device_id``；环境令牌代表管理员；``GALAXY_AUTH_ENABLED`` 打开时
无有效令牌拒绝接入；``GALAXY_REQUIRE_DEVICE_APPROVAL`` 打开时未批准设备降为
``control_only``（仍连接，永不作为派发目标）。

刻意的边界
==========
* **加法，不替换**：安卓注册路径一行逻辑不改，它继续负责安卓特有的那些事（传输缓存、
  重连续接判定、待投递回放）。
* 每一步都不致命：失败记为 ``gaps``，与安卓路径的 registration gap 同一语义 ——
  接入成功但没有完全附着。只有鉴权与身份闸会拒绝。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("Galaxy.ParticipantAdmission")

#: 通用接入写进 UDM 的 ``source``。据此能把「经通用路径接入的参与方」与安卓桥写入的区分开。
ADMISSION_SOURCE = "participant_admission"

#: 提交任务时交给在场运行时的入口名（:mod:`core.presence_line` 把它判为远端身体）。
PARTICIPANT_TASK_SOURCE = "participant_task"

_POSTURES: Tuple[str, ...] = ("join_runtime", "control_only")


# ---------------------------------------------------------------------------
# 入口鉴权与身份闸（搬自安卓注册路径，语义不变）
# ---------------------------------------------------------------------------


def extract_ingress_token(message: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """Extract device-ingress auth token from canonical and compat fields."""
    token_fields = (
        "_ingress_transport_token",
        "token",
        "auth_token",
        "api_token",
        "authorization",
    )
    payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}

    for field_name in token_fields:
        raw = message.get(field_name)
        if raw is None:
            raw = payload.get(field_name)
        if raw is None:
            continue
        value = str(raw).strip()
        if not value:
            continue
        if value.lower().startswith("bearer "):
            value = value[7:].strip()
        return value or None, field_name
    return None, None


#: 接纳"这台设备已配对"所需的最小作用域。与 core/routes/pairing.py 的
#: ``_TRUST_SCOPES`` 对齐:除 ``blocked``(压根不发令牌)外每级都至少有它 ——
#: 既不放进被拉黑的对端,也不把只读级别的正常设备挡在门外。
PAIRED_DEVICE_MIN_SCOPE = "device:status"


def verify_pairing_capability_token(token: str, device_id: str) -> bool:
    """这枚令牌是不是 ``/api/v1/pair/claim`` 发给**本设备**的配对令牌。

    单独判、不塞进 ``core.auth.verify_api_token``:配对令牌按信任级别限定作用域,
    塞进通用校验就会被中间件当成合法 API 令牌,只读级别的手表随即能去写配置 ——
    那是提权。这里问的是另一个问题:"这台设备配过对吗",只在设备入口成立。

    绑定 ``subject == device_id``:否则一枚泄露的令牌换个 device_id 就能冒充接入。
    """
    try:
        from core.capability_token import verify_token
    except ImportError as exc:
        # 只吞"模块不可用"。裸 except Exception 会把字段名写错这类自身缺陷
        # 一并吞成"这不是配对令牌",配对令牌集体失效而日志里一个字都没有。
        logger.debug("能力令牌模块不可用,跳过配对令牌校验: %s", exc)
        return False

    verdict = verify_token(token, required_scope=PAIRED_DEVICE_MIN_SCOPE)
    return bool(verdict.valid) and bool(device_id) and verdict.subject == device_id


def evaluate_ingress_authentication(message: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate token/auth boundary for device ingress registration."""
    auth_enforced = False
    active_token_count = 0
    token: Optional[str] = None
    token_source: Optional[str] = None
    token_present = False
    token_valid = False
    paired_token = False

    try:
        from core.auth import get_active_tokens, is_auth_enabled, verify_api_token

        auth_enforced = bool(is_auth_enabled())
        active_token_count = len(get_active_tokens())
        token, token_source = extract_ingress_token(message)
        token_present = bool(token)
        # 配对令牌与环境/每设备令牌是**并列**的三条合法凭证。少了第一条,
        # /api/v1/pair/claim 配对成功之后设备照样连不上 —— 配得上、连不了。
        if token:
            paired_token = verify_pairing_capability_token(token, str(message.get("device_id") or "").strip())
        token_valid = bool(token and (paired_token or verify_api_token(token)))
    except Exception as exc:  # pragma: no cover - defensive fallback
        return {
            "enforced": False,
            "token_present": False,
            "token_source": None,
            "token_valid": False,
            "active_token_count": 0,
            "state": "auth_check_unavailable",
            "reason": str(exc),
        }

    state = "not_enforced_no_token"
    reason = ""
    if auth_enforced:
        if active_token_count <= 0:
            state = "rejected_auth_misconfigured"
            reason = "GALAXY_AUTH_ENABLED=true but no active gateway tokens are configured"
        elif not token_present:
            state = "rejected_token_missing"
            reason = "Authentication is enforced; token is required"
        elif not token_valid:
            state = "rejected_token_invalid"
            reason = "Token is present but invalid"
        else:
            state = "verified"
            reason = "Token verified under enforced auth"
    else:
        if token_present and token_valid:
            state = "verified_optional"
            reason = "Token verified in compatibility mode (auth not enforced)"
        elif token_present and not token_valid and active_token_count > 0:
            state = "token_invalid_compat"
            reason = "Invalid token provided in compatibility mode"

    # 设备准入绑定:配对令牌是唯一"绑到这台设备"的凭据——它的 subject 必须等于本条
    # 消息的 device_id。环境共享 token 不绑设备,它代表管理员,按 token_valid 放行。
    #
    # 令牌被抄走、换台设备呈递时:subject 对不上 → paired_token False,而它也不是
    # 环境 token → verify_api_token 也 False,于是 token_valid 与 device_approved
    # 一并为 False。挡住这一条不需要额外分支,binding 本身就够。
    device_approved = paired_token or token_valid

    return {
        "enforced": auth_enforced,
        "token_present": token_present,
        "token_source": token_source,
        "token_valid": token_valid,
        "device_approved": device_approved,
        "active_token_count": active_token_count,
        "state": state,
        "reason": reason,
    }


def should_gate_unapproved(auth_outcome: Dict[str, Any]) -> bool:
    """设备准入闸决策:是否应把【未批准】设备降级为 control_only。

    仅当环境开关 GALAXY_REQUIRE_DEVICE_APPROVAL 打开、且设备【未批准】时返回 True。
    默认关 → 恒 False → 注册行为与现状逐字节一致(opt-in)。

    "已批准" == auth_outcome["device_approved"]:每设备 token 必须【发放给本 device_id】
    才算本设备已批准(见 evaluate_ingress_authentication 的绑定校验),否则一枚泄露 token
    换个 device_id 就能冒充接入。共享/环境管理员 token 仍按 token_valid 放行。配对批准
    发放的正是绑定本设备的 token,天然闭环。
    """
    require = os.environ.get("GALAXY_REQUIRE_DEVICE_APPROVAL", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    return require and not bool(auth_outcome.get("device_approved"))


def evaluate_ingress_identity(
    *,
    message_device_id: str,
    websocket_device_id: Optional[str],
) -> Dict[str, Any]:
    """Evaluate whether ingress path identity matches registration identity."""
    if websocket_device_id and message_device_id and websocket_device_id != message_device_id:
        return {
            "matched": False,
            "reason": ("device_id mismatch between WebSocket ingress path and " "device_register payload"),
        }
    return {"matched": True, "reason": ""}


# ---------------------------------------------------------------------------
# 设备自己声明的描述
# ---------------------------------------------------------------------------

#: 能力名里出现这些片段 → Body Mesh 角色。与安卓位掩码的映射同一套划分。
_ROLE_HINTS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("perception", ("camera", "mic", "microphone", "motion", "sensor", "gps", "accelerometer", "gyroscope")),
    ("action", ("touch", "keyboard", "gui_write", "shell", "input", "actuat", "automation")),
    ("presence", ("screen", "display", "screenshot", "gui_read", "notification", "speaker")),
)


@dataclass(frozen=True)
class ParticipantDescriptor:
    """一台设备对自己的声明。字段都是类型化的；``metadata`` 只进记录，不参与判定。"""

    device_id: str
    device_type: str
    name: str = ""
    capabilities: Tuple[str, ...] = ()
    tailscale_ip: str = ""
    runtime_posture: str = "join_runtime"
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_message(cls, message: Dict[str, Any]) -> "ParticipantDescriptor":
        payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}

        def pick(key: str, default: Any = "") -> Any:
            value = message.get(key)
            return payload.get(key, default) if value is None else value

        raw_caps = pick("capabilities", ())
        caps = tuple(str(c) for c in raw_caps) if isinstance(raw_caps, (list, tuple)) else ()
        posture = str(pick("runtime_posture", "join_runtime") or "join_runtime").strip().lower()
        return cls(
            device_id=str(pick("device_id") or "").strip(),
            device_type=str(pick("device_type") or "unknown").strip().lower(),
            name=str(pick("name") or ""),
            capabilities=caps,
            tailscale_ip=str(pick("tailscale_ip") or ""),
            runtime_posture=posture if posture in _POSTURES else "join_runtime",
            metadata=dict(pick("metadata", {}) or {}),
        )

    def body_mesh_roles(self) -> List[str]:
        lowered = [c.lower() for c in self.capabilities]
        roles = [role for role, hints in _ROLE_HINTS if any(h in cap for cap in lowered for h in hints)]
        return roles or ["action"]


@dataclass
class ParticipantAdmission:
    device_id: str
    admitted: bool
    error_code: str = ""
    runtime_posture: str = ""
    roles: List[str] = field(default_factory=list)
    steps: Dict[str, bool] = field(default_factory=dict)
    auth: Dict[str, Any] = field(default_factory=dict)
    identity: Dict[str, Any] = field(default_factory=dict)
    mesh_session_id: str = ""
    runtime_session_id: str = ""

    @property
    def gaps(self) -> List[str]:
        return [name for name, ok in self.steps.items() if not ok]

    @property
    def fully_attached(self) -> bool:
        return self.admitted and not self.gaps

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "admitted": self.admitted,
            "error_code": self.error_code,
            "runtime_posture": self.runtime_posture,
            "roles": list(self.roles),
            "steps": dict(self.steps),
            "gaps": self.gaps,
            "fully_attached": self.fully_attached,
            "auth_state": self.auth.get("state", ""),
            "mesh_session_id": self.mesh_session_id,
            "runtime_session_id": self.runtime_session_id,
        }


# ---------------------------------------------------------------------------
# 接入的各步 —— 每步都不致命，失败记进 steps
# ---------------------------------------------------------------------------


def _write_udm(descriptor: ParticipantDescriptor) -> None:
    from core.unified.device_manager import get_unified_device_manager
    from core.unified.models import UnifiedDevice, UnifiedDeviceStatus, UnifiedDeviceType

    try:
        utype = UnifiedDeviceType(descriptor.device_type)
    except ValueError:
        utype = UnifiedDeviceType.UNKNOWN
    get_unified_device_manager().register_device(
        UnifiedDevice(
            device_id=descriptor.device_id,
            device_name=descriptor.name or descriptor.device_id,
            device_type=utype,
            status=UnifiedDeviceStatus.ONLINE,
            capabilities=list(descriptor.capabilities),
            # 原始类型（wear_os 之类不在 UnifiedDeviceType 里）留在这里，入口分流据此认远端身体。
            metadata={**descriptor.metadata, "participant_kind": descriptor.device_type},
            source=ADMISSION_SOURCE,
        )
    )


def _register_mesh_peer(descriptor: ParticipantDescriptor) -> None:
    from core.mesh_coordinator import get_mesh_coordinator

    get_mesh_coordinator().register_peer(
        device_id=descriptor.device_id,
        tailscale_ip=descriptor.tailscale_ip,
        metadata={"participant_kind": descriptor.device_type, "registration_trigger": ADMISSION_SOURCE},
    )


def _open_mesh_session(descriptor: ParticipantDescriptor) -> str:
    from contracts.mesh_session import build_mesh_session
    from core.mesh.mesh_session_lifecycle import activate_durable_session, create_durable_session

    session = build_mesh_session(
        source_device_id=descriptor.device_id,
        primary_device_id=descriptor.device_id,
        metadata={"registration_trigger": ADMISSION_SOURCE},
    )
    record = create_durable_session(session, metadata={"device_id": descriptor.device_id, "trigger": ADMISSION_SOURCE})
    if not record:
        raise RuntimeError("durable mesh session was not created")
    activate_durable_session(record.session_id)
    return str(record.session_id)


def _attach_runtime_session(descriptor: ParticipantDescriptor, posture: str) -> str:
    from core.attached_runtime_session_registry import register_session

    entry = register_session(
        descriptor.device_id,
        posture=posture,
        metadata={"registration_trigger": ADMISSION_SOURCE, "participant_kind": descriptor.device_type},
    )
    return str(getattr(entry, "runtime_session_id", "") or "")


def _register_body_mesh(descriptor: ParticipantDescriptor, roles: List[str]) -> None:
    from core.mesh.body_mesh_registry import DeviceRole, get_body_mesh_registry

    get_body_mesh_registry().register(
        descriptor.device_id,
        roles=[DeviceRole(r) for r in roles],
        metadata={"registration_trigger": ADMISSION_SOURCE, "platform": descriptor.device_type},
    )


def _assimilate(descriptor: ParticipantDescriptor) -> None:
    from core.capability_assimilation import assimilate_device

    assimilate_device(
        descriptor.device_id,
        capabilities=list(descriptor.capabilities),
        tags=[descriptor.device_type],
        metadata={"registration_trigger": ADMISSION_SOURCE, "device_type": descriptor.device_type},
    )


def _emit_attach_event(descriptor: ParticipantDescriptor) -> None:
    from core.runtime.runtime_observability_sink import emit_device_lifecycle_event

    emit_device_lifecycle_event(
        descriptor.device_id, event_kind="attach", new_state="online", reason="participant_admission"
    )


def _step(admission: ParticipantAdmission, name: str, fn: Any, *args: Any) -> Any:
    try:
        result = fn(*args)
        admission.steps[name] = True
        return result
    except Exception as exc:  # noqa: BLE001 — 接入的每一步都不致命，记为 gap
        admission.steps[name] = False
        logger.warning("参与方接入步骤失败（记为 gap）| device_id=%s step=%s err=%s", admission.device_id, name, exc)
        return None


def admit_participant(
    descriptor: ParticipantDescriptor,
    *,
    message: Optional[Dict[str, Any]] = None,
    websocket_device_id: Optional[str] = None,
) -> ParticipantAdmission:
    """把一台自我声明的设备接进中心：鉴权、写事实来源、进 mesh。

    ``message`` 是设备发来的原始注册消息（令牌从这里取）；缺省时用描述本身。
    """
    raw = dict(message or {})
    raw.setdefault("device_id", descriptor.device_id)
    admission = ParticipantAdmission(device_id=descriptor.device_id, admitted=False)
    if not descriptor.device_id:
        admission.error_code = "DEVICE_ID_MISSING"
        return admission

    admission.auth = evaluate_ingress_authentication(raw)
    admission.identity = evaluate_ingress_identity(
        message_device_id=descriptor.device_id, websocket_device_id=websocket_device_id
    )
    if not admission.identity.get("matched", False):
        admission.error_code = "INGRESS_IDENTITY_MISMATCH"
        return admission
    if admission.auth.get("enforced") and not admission.auth.get("token_valid"):
        admission.error_code = "INGRESS_AUTHENTICATION_FAILED"
        return admission

    posture = descriptor.runtime_posture
    if should_gate_unapproved(admission.auth) and posture == "join_runtime":
        logger.info("设备准入闸:device_id=%s 未批准,降为 control_only(仅连接,非派发目标)", descriptor.device_id)
        posture = "control_only"
    admission.runtime_posture = posture
    admission.roles = descriptor.body_mesh_roles()

    _step(admission, "udm", _write_udm, descriptor)
    admission.admitted = admission.steps["udm"]
    if not admission.admitted:
        admission.error_code = "UDM_WRITE_FAILED"
        return admission
    if descriptor.tailscale_ip:
        _step(admission, "mesh_peer", _register_mesh_peer, descriptor)
    admission.mesh_session_id = _step(admission, "mesh_session", _open_mesh_session, descriptor) or ""
    admission.runtime_session_id = (
        _step(admission, "runtime_session", _attach_runtime_session, descriptor, posture) or ""
    )
    _step(admission, "body_mesh", _register_body_mesh, descriptor, admission.roles)
    _step(admission, "capability_assimilation", _assimilate, descriptor)
    _step(admission, "lifecycle_event", _emit_attach_event, descriptor)
    logger.info(
        "参与方接入 | device_id=%s type=%s posture=%s roles=%s gaps=%s",
        descriptor.device_id,
        descriptor.device_type,
        posture,
        admission.roles,
        admission.gaps,
    )
    return admission


def admitted_participant(device_id: str) -> Optional[Any]:
    """经通用路径接入的参与方在 UDM 里的记录；不是经本路径接入的返回 ``None``。"""
    from core.unified.device_manager import get_unified_device_manager

    device = get_unified_device_manager().get_device(device_id)
    if device is None or getattr(device, "source", "") != ADMISSION_SOURCE:
        return None
    return device


async def submit_participant_task(
    device_id: str,
    message: str,
    *,
    session_id: Optional[str] = None,
    credentials: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """已接入的参与方提交一句自然语言任务。

    只有经 :func:`admit_participant` 接入过的设备能提交；鉴权开启时每次都要带有效令牌
    （配对令牌须绑定本设备）。任务交给在场运行时的唯一收口。
    """
    if admitted_participant(device_id) is None:
        return {"success": False, "error_code": "PARTICIPANT_NOT_ADMITTED"}
    auth = evaluate_ingress_authentication({**(credentials or {}), "device_id": device_id})
    if auth.get("enforced") and not auth.get("token_valid"):
        return {"success": False, "error_code": "INGRESS_AUTHENTICATION_FAILED", "auth_state": auth.get("state")}

    from core.desktop_presence_runtime import get_desktop_presence_runtime

    return await get_desktop_presence_runtime().handle_request(
        message=message,
        source=PARTICIPANT_TASK_SOURCE,
        device_id=device_id,
        session_id=session_id or f"participant_{device_id}",
        user_id=device_id,
        entry_mode="cross_device",
    )


__all__ = [
    "ADMISSION_SOURCE",
    "PAIRED_DEVICE_MIN_SCOPE",
    "PARTICIPANT_TASK_SOURCE",
    "ParticipantAdmission",
    "ParticipantDescriptor",
    "admit_participant",
    "admitted_participant",
    "evaluate_ingress_authentication",
    "evaluate_ingress_identity",
    "extract_ingress_token",
    "should_gate_unapproved",
    "submit_participant_task",
    "verify_pairing_capability_token",
]
