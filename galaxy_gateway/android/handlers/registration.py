"""
galaxy_gateway/android/handlers/registration.py

Handles device registration messages and unregistered message types.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import OrderedDict
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from galaxy_gateway.android.message_builder import MessageBuilder
from galaxy_gateway.android.models import AndroidDevice

if TYPE_CHECKING:
    from galaxy_gateway.android_bridge import AndroidBridge

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Registration completeness tracking
# ---------------------------------------------------------------------------
# Per-device store of downstream registration step gaps.  When a device
# registers successfully at the transport/UDM level but one or more of the
# critical downstream steps (attach_runtime_session, registry, DeviceRouter
# session sync) fails, the gap is recorded here so the incompleteness is
# machine-observable rather than silently logged.
#
# Key   → device_id
# Value → list of step-name strings that failed, e.g. ["attach_runtime_session"]
#
# Bounded to _REG_GAP_MAX_ENTRIES entries (LRU eviction) so it never grows
# unboundedly.
#
# 512 entries covers the registration history of a large fleet of devices in
# a single process.  A device registers once per session; 512 entries retain
# the gap state for up to 512 unique device sessions before the oldest are
# evicted.  This is intentionally smaller than the truth chain ledger because
# device registrations are far less frequent than task results.

_REG_GAP_MAX_ENTRIES: int = 512
_device_registration_gaps: OrderedDict = OrderedDict()


def record_registration_gap(device_id: str, step_name: str) -> None:
    """Record that *step_name* failed during *device_id*'s registration.

    Safe to call from any except block — never raises.  Does nothing if
    *device_id* is falsy.
    """
    if not device_id:
        return
    if device_id not in _device_registration_gaps:
        if len(_device_registration_gaps) >= _REG_GAP_MAX_ENTRIES:
            _device_registration_gaps.popitem(last=False)
        _device_registration_gaps[device_id] = []
    _device_registration_gaps[device_id].append(step_name)


def get_registration_gaps(device_id: str) -> List[str]:
    """Return the list of downstream step names that failed for *device_id*.

    An empty list means the device completed all tracked downstream steps
    successfully (or it was never registered through this handler).
    """
    return list(_device_registration_gaps.get(device_id, []))


def is_registration_fully_attached(device_id: str) -> bool:
    """Return ``True`` if no downstream registration gaps were recorded for
    *device_id*.

    A device without gaps successfully completed all tracked downstream steps:
    UDM write, DeviceRouter session sync, ``attach_runtime_session``, and
    ``attached_runtime_session_registry``.  A device with gaps is considered
    *partially registered* and may not be reliably dispatchable.
    """
    return len(_device_registration_gaps.get(device_id, [])) == 0


def clear_registration_gaps(device_id: Optional[str] = None) -> None:
    """Remove registration gap records.

    If *device_id* is given, only that device's record is removed.  If
    *device_id* is ``None``, all records are cleared (useful in tests).
    """
    if device_id is None:
        _device_registration_gaps.clear()
    else:
        _device_registration_gaps.pop(device_id, None)


def get_all_devices_with_registration_gaps() -> Dict[str, List[str]]:
    """Return a snapshot of all device IDs that have recorded registration gaps.

    Returns a dict mapping ``device_id → list[step_name]`` for every device
    that has at least one failed downstream registration step.  Devices with
    no gaps are excluded.

    This is the canonical read-path for control-plane surfaces that need to
    enumerate *all* partially-registered devices without knowing their IDs
    upfront.
    """
    return {
        device_id: list(gaps)
        for device_id, gaps in _device_registration_gaps.items()
        if gaps
    }


def _schedule_pending_delivery_replay_on_canonical_reconnect(
    *,
    device_id: str,
    websocket: Any,
) -> int:
    """Replay buffered messages after canonical ``device_register`` continuity resume.

    ``AndroidBridge.reconnect_device()`` already flushes the pending-delivery
    buffer, but the production reconnect path is a new websocket followed by
    ``device_register``.  When that registration is classified as
    ``continuity_resume``, V2 must replay buffered task messages on the new
    websocket so the resumed execution path remains stable on the canonical flow.

    The replay is scheduled asynchronously so the registration ack can be sent
    first by the websocket route before buffered task messages are re-delivered.
    """
    try:
        from galaxy_gateway.pending_delivery_buffer import (
            pending_delivery_buffer as _pending_delivery_buffer,
        )
    except Exception as exc:  # pragma: no cover - non-fatal integration absence
        logger.debug(
            "handle_device_register: canonical reconnect replay unavailable "
            "device_id=%s error=%s",
            device_id,
            exc,
        )
        return 0

    buffered_count = _pending_delivery_buffer.queue_size(device_id)
    if buffered_count <= 0:
        return 0

    async def _flush() -> None:
        try:
            delivered, skipped = await _pending_delivery_buffer.flush(
                device_id,
                websocket.send_json,
            )
            logger.info(
                "handle_device_register: canonical reconnect replay complete "
                "device_id=%s delivered=%d skipped=%d",
                device_id,
                delivered,
                skipped,
            )
        except Exception as exc:  # pragma: no cover - best-effort replay path
            logger.warning(
                "handle_device_register: canonical reconnect replay failed "
                "device_id=%s error=%s",
                device_id,
                exc,
            )

    asyncio.create_task(_flush())
    return buffered_count


def _apply_pending_lifecycle_reconnect_decisions(
    *,
    device_id: str,
    continuity_outcome: str,
    delivery_replay_scheduled: bool,
) -> List[Dict[str, Any]]:
    """Consume pending lifecycle records on reconnect and make deterministic decisions.

    This closes the reconnect gap where pending envelopes previously remained in
    the registry and silently waited for timeout.  Decisions align with the
    existing lifecycle registry owner model:

    * ``DEVICE_DISPATCH`` / ``CROSS_DEVICE`` + ``continuity_resume`` → resume
    * ``ROUTING`` → replay/reconciliation required
    * ``GATEWAY_INGRESS`` → failover / re-issue required
    * ``RESULT_COMPLETION`` or timed-out records → abandon as stale/closed
    """
    try:
        from core.task_envelope_lifecycle_registry import (
            LifecycleOwner,
            get_lifecycle_registry,
        )
    except Exception as exc:  # pragma: no cover - graceful degradation
        logger.debug(
            "reconnect pending lifecycle decisions unavailable: device_id=%s error=%s",
            device_id,
            exc,
        )
        return []

    registry = get_lifecycle_registry()
    decisions: List[Dict[str, Any]] = []
    pending_records = list(registry.get_pending_for_device(device_id))

    for record in pending_records:
        decision = "resume_existing_execution"
        action = "resume_existing_execution"
        reason = ""
        should_fail = False

        if record.is_timed_out():
            decision = "mark_abandoned_stale"
            action = "abandon_pending_envelope"
            reason = "pending_envelope_timed_out_before_reconnect_decision"
            should_fail = True
        elif record.owner == LifecycleOwner.RESULT_COMPLETION:
            decision = "closure_already_decided"
            action = "abandon_pending_envelope"
            reason = "pending_record_already_at_result_completion_owner"
            should_fail = True
        elif continuity_outcome != "continuity_resume":
            if record.owner == LifecycleOwner.ROUTING:
                decision = "request_replay_reconciliation"
                action = "fail_pending_for_replay"
                reason = "new_attachment_blocks_routing_stage_resume"
            else:
                decision = "trigger_failover"
                action = "fail_pending_for_failover"
                reason = f"new_attachment_blocks_{record.owner.value}_resume"
            should_fail = True
        elif record.owner == LifecycleOwner.ROUTING:
            decision = "request_replay_reconciliation"
            action = "fail_pending_for_replay"
            reason = "reconnect_requires_routing_replay"
            should_fail = True
        elif record.owner == LifecycleOwner.GATEWAY_INGRESS:
            decision = "trigger_failover"
            action = "fail_pending_for_failover"
            reason = "reconnect_requires_gateway_reissue_or_failover"
            should_fail = True

        evidence = {
            "task_id": record.task_id,
            "trace_id": record.trace_id,
            "target_device_id": record.target_device_id,
            "tool_name": record.tool_name,
            "owner": record.owner.value,
            "elapsed_seconds": round(record.elapsed(), 3),
            "timeout_seconds": float(record.timeout),
            "continuity_outcome": continuity_outcome,
            "decision": decision,
            "action": action,
            "reason": reason,
            "delivery_replay_scheduled": bool(delivery_replay_scheduled),
            "diagnostic_trace": (
                f"reconnect:{continuity_outcome}:{decision}:{record.owner.value}:{record.task_id}"
            ),
        }

        if should_fail:
            registry.fail(
                record.task_id,
                f"reconnect_lifecycle_decision:{decision}:{reason}",
            )
            logger.warning(
                "reconnect lifecycle decision | device_id=%s task_id=%s decision=%s owner=%s reason=%s",
                device_id,
                record.task_id,
                decision,
                record.owner.value,
                reason,
            )
        else:
            registry.merge_metadata(
                record.task_id,
                {
                    "reconnect_lifecycle_decision": decision,
                    "reconnect_lifecycle_reason": reason or "continuity_resume_for_existing_execution",
                    "reconnect_lifecycle_trace": evidence["diagnostic_trace"],
                    "reconnect_delivery_replay_scheduled": bool(delivery_replay_scheduled),
                },
            )
            registry.transfer_ownership(record.task_id, LifecycleOwner.DEVICE_DISPATCH)
            logger.info(
                "reconnect lifecycle decision | device_id=%s task_id=%s decision=%s owner=%s replay_scheduled=%s",
                device_id,
                record.task_id,
                decision,
                record.owner.value,
                delivery_replay_scheduled,
            )

        decisions.append(evidence)

    return decisions


def _summarize_pending_lifecycle_decisions(
    decisions: List[Dict[str, Any]],
) -> Dict[str, int]:
    summary: Dict[str, int] = {}
    for decision in decisions:
        key = str(decision.get("decision") or "unknown")
        summary[key] = summary.get(key, 0) + 1
    return summary


# ---------------------------------------------------------------------------
# Canonical reconnect path sentinel
# ---------------------------------------------------------------------------

#: Affirms that ``device_register`` (not ``device_reconnect``) is the
#: canonical Android reconnect path.  When an Android client reconnects it
#: opens a new WebSocket and sends ``device_register`` again, optionally
#: including the same ``runtime_attachment_session_id`` that was issued during
#: the prior session.  :func:`handle_device_register` detects this via
#: :func:`~core.attached_runtime_session_registry.classify_reconnect_outcome`
#: and calls :func:`~core.attached_runtime_session_registry.reconnect_session`
#: to restore continuity (same ``runtime_session_id``) rather than creating a
#: brand-new session.
#:
#: :func:`handle_device_reconnect` below exists for clients that send an
#: explicit ``device_reconnect`` wire message, but this is **NOT** the Android
#: production canonical path.  It is preserved for backward-compat but must
#: not be treated as the authoritative reconnect handler.
DEVICE_REGISTER_IS_CANONICAL_RECONNECT_PATH: str = (
    "RECONNECT_CANONICAL_PATH_V1: "
    "handle_device_register() is the canonical Android reconnect consumer.  "
    "Android clients reconnect by sending device_register with the same "
    "runtime_attachment_session_id; classify_reconnect_outcome() determines "
    "whether the re-registration should be treated as a continuity resume or "
    "a fresh new attachment.  There is no separate device_reconnect wire type "
    "in the Android production path."
)


class DispatchBlockedByRegistrationGapError(RuntimeError):
    """Raised when a task dispatch is attempted for a device that has incomplete
    registration attachments (one or more downstream registration steps failed).

    This converts what was previously a silent best-effort gap into a
    machine-observable, explicit dispatch block so that callers can decide how
    to handle partial registration rather than silently proceeding with
    potentially unreliable devices.

    Attributes
    ----------
    device_id : str
        The device that has incomplete registration.
    gaps : list[str]
        Names of the registration steps that failed.
    """

    def __init__(self, device_id: str, gaps: List[str]) -> None:
        self.device_id = device_id
        self.gaps = gaps
        super().__init__(
            f"Dispatch blocked: device_id={device_id!r} has incomplete registration "
            f"attachments (gaps={gaps!r}). The device registered at transport level "
            "but critical downstream attachment steps failed. Resolve the gaps before "
            "dispatching tasks to this device."
        )

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_runtime_attachment_session_id(message: Dict[str, Any]) -> str:
    """Extract the canonical runtime attachment session identity from a message.

    Priority order (PR-G):
    1. ``runtime_attachment_session_id`` — explicit canonical field.
    2. ``session_id`` — backward-compatible fallback for older clients.
    3. Generated UUID fallback — ensures every call produces a non-empty id.

    Returns a non-empty string; never returns ``None`` or ``""``.
    """
    value = message.get("runtime_attachment_session_id") or message.get("session_id")
    if value:
        return value
    return str(uuid.uuid4())


def _extract_durable_continuity_fields(message: Dict[str, Any]) -> tuple:
    """Extract Android durable continuity identity fields from a message.

    PR-C: Android clients supply ``durable_session_id`` and
    ``session_continuity_epoch`` in registration and reconnect messages.
    These fields provide a cross-restart stable identity that survives cold
    Android process recreation and complements ``runtime_attachment_session_id``
    (which is stable only across transport reconnects within the same process
    epoch).

    Returns ``(durable_session_id, continuity_epoch)`` where
    ``durable_session_id`` is a string (empty if absent) and
    ``continuity_epoch`` is an int (0 if absent).
    """
    durable_session_id: str = message.get("durable_session_id") or ""
    raw_epoch = message.get("session_continuity_epoch")
    try:
        continuity_epoch: int = int(raw_epoch) if raw_epoch is not None else 0
    except (ValueError, TypeError):
        continuity_epoch = 0
    return durable_session_id, continuity_epoch


def _normalize_assimilation_capabilities(raw_capabilities: Any) -> List[str]:
    """Normalize Android capability payloads into canonical capability names."""
    if raw_capabilities is None:
        return []
    if isinstance(raw_capabilities, int):
        try:
            from galaxy_gateway.android.capabilities import DeviceCapability

            return DeviceCapability.to_list(raw_capabilities)
        except Exception:
            return []
    if isinstance(raw_capabilities, str):
        return [raw_capabilities.strip().lower()] if raw_capabilities.strip() else []
    if isinstance(raw_capabilities, (list, tuple, set, frozenset)):
        normalized: List[str] = []
        for item in raw_capabilities:
            value = str(item or "").strip().lower()
            if value and value not in normalized:
                normalized.append(value)
        return normalized
    return []


def _enum_or_string(value: Any) -> Optional[str]:
    """Return a stable string for enum-like values used in metadata payloads."""
    if value is None:
        return None
    if hasattr(value, "value"):
        return str(value.value)
    text = str(value).strip()
    return text or None


def _extract_ingress_token(message: Dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    """Extract device-ingress auth token from canonical and compat fields."""
    token_fields = (
        "_ingress_transport_token",
        "token",
        "auth_token",
        "api_token",
        "authorization",
    )
    payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}

    for field in token_fields:
        raw = message.get(field)
        if raw is None:
            raw = payload.get(field)
        if raw is None:
            continue
        value = str(raw).strip()
        if not value:
            continue
        if value.lower().startswith("bearer "):
            value = value[7:].strip()
        return value or None, field
    return None, None


def _evaluate_ingress_authentication(message: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate token/auth boundary for device ingress registration."""
    auth_enforced = False
    active_token_count = 0
    token: Optional[str] = None
    token_source: Optional[str] = None
    token_present = False
    token_valid = False

    try:
        from core.auth import is_auth_enabled, get_active_tokens, verify_api_token

        auth_enforced = bool(is_auth_enabled())
        active_token_count = len(get_active_tokens())
        token, token_source = _extract_ingress_token(message)
        token_present = bool(token)
        token_valid = bool(token and verify_api_token(token))
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

    return {
        "enforced": auth_enforced,
        "token_present": token_present,
        "token_source": token_source,
        "token_valid": token_valid,
        "active_token_count": active_token_count,
        "state": state,
        "reason": reason,
    }


def _evaluate_ingress_identity(
    *,
    message_device_id: str,
    websocket_device_id: Optional[str],
) -> Dict[str, Any]:
    """Evaluate whether ingress path identity matches registration identity."""
    if websocket_device_id and message_device_id and websocket_device_id != message_device_id:
        return {
            "matched": False,
            "reason": (
                "device_id mismatch between WebSocket ingress path and "
                "device_register payload"
            ),
        }
    return {"matched": True, "reason": ""}


def _decorate_registration_boundary(
    *,
    ack: Dict[str, Any],
    websocket_device_id: Optional[str],
    auth_outcome: Dict[str, Any],
    identity_outcome: Dict[str, Any],
    registration_success: bool,
    registration_fully_attached: bool,
    registration_gaps: List[str],
    network_participation_tier: str,
) -> None:
    participation_eligible = network_participation_tier in {
        "dispatch_eligible",
        "distributed_participant",
    }
    ack["connection_accepted"] = True
    ack["authentication_enforced"] = bool(auth_outcome.get("enforced"))
    ack["authentication_success"] = bool(auth_outcome.get("token_valid"))
    ack["identity_match_success"] = bool(identity_outcome.get("matched"))
    ack["registration_success"] = bool(registration_success)
    ack["participation_eligible"] = participation_eligible
    ack["ingress_boundary"] = {
        "connection": {
            "accepted": True,
            "websocket_device_id": websocket_device_id,
            "message_device_id": ack.get("device_id"),
        },
        "authentication": {
            "enforced": bool(auth_outcome.get("enforced")),
            "token_present": bool(auth_outcome.get("token_present")),
            "token_valid": bool(auth_outcome.get("token_valid")),
            "token_source": auth_outcome.get("token_source"),
            "state": auth_outcome.get("state"),
            "reason": auth_outcome.get("reason") or "",
            "active_token_count": int(auth_outcome.get("active_token_count") or 0),
        },
        "identity": {
            "matched": bool(identity_outcome.get("matched")),
            "reason": identity_outcome.get("reason") or "",
        },
        "registration": {
            "success": bool(registration_success),
            "fully_attached": bool(registration_fully_attached),
            "gaps": list(registration_gaps or []),
        },
        "participation": {
            "eligible": participation_eligible,
            "network_participation_tier": network_participation_tier,
        },
    }

# ---------------------------------------------------------------------------
# Role derivation helpers
# ---------------------------------------------------------------------------

def _derive_body_mesh_roles(capabilities: int) -> List[Any]:
    """Derive :class:`~core.mesh.body_mesh_registry.DeviceRole` values from a
    ``DeviceCapability`` bitmask.

    Mapping:
    - PERCEPTION  — any of SENSOR_CAMERA, SENSOR_MIC, SENSOR_MOTION
    - ACTION      — any of INPUT_TOUCH, INPUT_KEYBOARD, GUI_WRITE, SYSTEM_SHELL
    - PRESENCE    — any of GUI_READ, GUI_SCREENSHOT, SYSTEM_NOTIFICATION

    A device that has none of the above defaults to the ACTION role to ensure
    every registered device has at least one role.
    """
    try:
        from core.mesh.body_mesh_registry import DeviceRole
        from galaxy_gateway.android.capabilities import DeviceCapability as DC
    except ImportError:
        return []

    roles: List = []
    has = DC.has_capability

    if has(capabilities, DC.SENSOR_CAMERA) or has(capabilities, DC.SENSOR_MIC) or has(capabilities, DC.SENSOR_MOTION):
        roles.append(DeviceRole.PERCEPTION)
    if has(capabilities, DC.INPUT_TOUCH) or has(capabilities, DC.INPUT_KEYBOARD) or has(capabilities, DC.GUI_WRITE) or has(capabilities, DC.SYSTEM_SHELL):
        roles.append(DeviceRole.ACTION)
    if has(capabilities, DC.GUI_READ) or has(capabilities, DC.GUI_SCREENSHOT) or has(capabilities, DC.SYSTEM_NOTIFICATION):
        roles.append(DeviceRole.PRESENCE)

    if not roles:
        roles.append(DeviceRole.ACTION)

    return roles


async def handle_device_register(
    bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]
) -> Dict[str, Any]:
    """处理设备注册，失败时向网关日志输出结构化错误。

    Registration flow (PR-2):
    1. Write canonical identity/state to UDM (SSOT).
    2. Update local ``_devices`` as transport/session cache only.

    PR-G: extracts ``runtime_attachment_session_id`` from the message and
    propagates it to the attach and registry paths for canonical identity
    handling.  Falls back to generating a new stable ID when absent (backward
    compatibility with older clients).
    """
    device_id = message.get("device_id")
    websocket_device_id = str(message.get("_ingress_connection_device_id") or "").strip() or None
    auth_outcome = _evaluate_ingress_authentication(message)
    identity_outcome = _evaluate_ingress_identity(
        message_device_id=str(device_id or ""),
        websocket_device_id=websocket_device_id,
    )

    if not identity_outcome.get("matched", False):
        ack = MessageBuilder.device_register_ack(
            device_id=device_id or "unknown",
            success=False,
            message="Registration rejected: ingress identity mismatch",
        )
        ack["error_code"] = "INGRESS_IDENTITY_MISMATCH"
        _decorate_registration_boundary(
            ack=ack,
            websocket_device_id=websocket_device_id,
            auth_outcome=auth_outcome,
            identity_outcome=identity_outcome,
            registration_success=False,
            registration_fully_attached=False,
            registration_gaps=["identity_boundary"],
            network_participation_tier="connected",
        )
        return ack

    if auth_outcome.get("enforced") and not auth_outcome.get("token_valid"):
        ack = MessageBuilder.device_register_ack(
            device_id=device_id or "unknown",
            success=False,
            message="Registration rejected: ingress authentication failed",
        )
        ack["error_code"] = "INGRESS_AUTHENTICATION_FAILED"
        _decorate_registration_boundary(
            ack=ack,
            websocket_device_id=websocket_device_id,
            auth_outcome=auth_outcome,
            identity_outcome=identity_outcome,
            registration_success=False,
            registration_fully_attached=False,
            registration_gaps=["authentication_boundary"],
            network_participation_tier="connected",
        )
        return ack

    try:
        # Step 1 — canonical write to UDM (SSOT); must happen before local cache update.
        bridge._write_registration_to_udm(device_id, message)

        # Step 2 — update local transport/session cache.
        async with bridge._lock:
            device = AndroidDevice.from_registration(message)
            device.websocket = websocket
            bridge._devices[device_id] = device

        bridge._sync_device_router_session(device_id, websocket=websocket, connected=True)

        # PR-G: extract canonical runtime attachment session identity.
        # Prefer the explicit field; fall back to a generated UUID so that
        # older clients that do not supply the field remain compatible.
        inbound_attachment_id = _extract_runtime_attachment_session_id(message)
        if not message.get("runtime_attachment_session_id") and not message.get("session_id"):
            logger.debug(
                "handle_device_register: runtime_attachment_session_id absent in "
                "message, generated fallback: device_id=%s attachment_id=%s",
                device_id, inbound_attachment_id,
            )

        # PR-C: extract Android durable continuity identity fields so reconnect
        # and session-resume decisions can validate cross-restart stable identity.
        inbound_durable_session_id, inbound_continuity_epoch = _extract_durable_continuity_fields(message)
        _raw_runtime_posture = (
            message.get("source_runtime_posture")
            or (message.get("payload") or {}).get("source_runtime_posture")
            or ""
        )
        _inbound_runtime_posture = str(_raw_runtime_posture or "").strip().lower()
        if _inbound_runtime_posture not in {"join_runtime", "control_only"}:
            _inbound_runtime_posture = "join_runtime"
        if inbound_durable_session_id:
            logger.debug(
                "handle_device_register: durable continuity fields present: "
                "device_id=%s durable_session_id=%s continuity_epoch=%s",
                device_id, inbound_durable_session_id, inbound_continuity_epoch,
            )

        # PR-G: emit device lifecycle (attach) so the observability sink records
        # the registration event in the production path.
        try:
            from core.runtime.runtime_observability_sink import emit_device_lifecycle_event
            emit_device_lifecycle_event(
                device_id,
                event_kind="attach",
                new_state="online",
                reason="android_device_register",
            )
        except Exception:
            pass

        # PR-B: Create and activate a durable mesh session for this device so that
        # the MeshSessionLifecycleCoordinator is aware of the device's registration.
        # The session tracks this device as both source and primary participant so
        # that disconnect handling can later locate and terminate it.
        try:
            from contracts.mesh_session import build_mesh_session
            from core.mesh.mesh_session_lifecycle import (
                create_durable_session,
                activate_durable_session,
            )
            _mesh_session = build_mesh_session(
                source_device_id=device_id,
                primary_device_id=device_id,
                metadata={"registration_trigger": "android_device_register"},
            )
            _record = create_durable_session(
                _mesh_session,
                metadata={"device_id": device_id, "trigger": "device_register"},
            )
            if _record:
                activate_durable_session(_record.session_id)
                logger.info(
                    "Mesh session created+activated for device: device_id=%s session_id=%s",
                    device_id, _record.session_id,
                )
        except Exception as _mesh_exc:
            logger.debug(
                "android_bridge: mesh session create/activate non-fatal: device_id=%s error=%s",
                device_id, _mesh_exc,
            )

        # PR-C / PR-G: attach runtime session with canonical runtime_attachment_session_id
        # so the device enters the attached runtime session registry and becomes visible
        # as a managed runtime node with a stable attachment identity.
        try:
            from core.attached_runtime_session import attach_runtime_session
            _attach_record = attach_runtime_session(
                device_id,
                source_runtime_posture=_inbound_runtime_posture,
                runtime_attachment_session_id=inbound_attachment_id,
                attach_reason="android_device_register",
                metadata={"registration_trigger": "android_device_register"},
            )
            logger.info(
                "attach_runtime_session: device_id=%s state=%s runtime_attachment_session_id=%s",
                device_id, _attach_record.attachment_state, _attach_record.runtime_attachment_session_id,
            )
        except Exception as _attach_exc:
            logger.debug(
                "android_bridge: attach_runtime_session non-fatal: device_id=%s error=%s",
                device_id, _attach_exc,
            )
            record_registration_gap(device_id, "attach_runtime_session")

        # PR-C / PR-G / canonical reconnect: register or resume in the authoritative
        # attached runtime session registry.
        #
        # This is the canonical Android reconnect consumer.  classify_reconnect_outcome()
        # determines whether the inbound device_register carries a matching
        # runtime_attachment_session_id (continuity_resume) or represents a brand-new
        # session (new_attachment):
        #
        # - continuity_resume: reconnect_session() is called to restore the existing
        #   registry entry to active state while preserving the stable runtime_session_id.
        # - new_attachment: register_session() creates a fresh entry as before.
        #
        # _reconnect_outcome reflects the classification decision from
        # classify_reconnect_outcome().  If the block raises before classification
        # completes, it falls back to "new_attachment" (safe conservative default).
        # If classification succeeds but the subsequent session operation fails, the
        # failure is recorded as a registration gap (see record_registration_gap) so
        # the gap tracking provides the operational result while _reconnect_outcome
        # always reflects the server-side classification decision.
        #
        # See DEVICE_REGISTER_IS_CANONICAL_RECONNECT_PATH for the full policy statement.
        _reconnect_outcome = "new_attachment"  # safe default if classify call throws
        _reg_entry = None
        try:
            from core.attached_runtime_session_registry import (
                classify_reconnect_outcome,
                reconnect_session,
                register_session,
            )
            # Capture classification result before attempting the session operation
            # so that _reconnect_outcome always reflects the classify decision even
            # if the subsequent reconnect_session / register_session call raises.
            # PR-C: pass durable_session_id to additionally validate cross-restart
            # session era continuity.
            _reconnect_outcome, _existing_entry = classify_reconnect_outcome(
                device_id,
                runtime_attachment_session_id=inbound_attachment_id,
                durable_session_id=inbound_durable_session_id,
                continuity_epoch=inbound_continuity_epoch,
            )
            if _reconnect_outcome == "continuity_resume" and _existing_entry is not None:
                _reg_entry = reconnect_session(
                    _existing_entry,
                    runtime_attachment_session_id=inbound_attachment_id,
                    metadata={"reconnect_trigger": "device_register_continuity"},
                    durable_session_id=inbound_durable_session_id,
                    continuity_epoch=inbound_continuity_epoch,
                    new_posture=_inbound_runtime_posture,
                )
                logger.info(
                    "attached_runtime_session_registry: continuity_resume via device_register: "
                    "device_id=%s runtime_session_id=%s runtime_attachment_session_id=%s "
                    "durable_session_id=%s continuity_epoch=%s",
                    device_id, _reg_entry.runtime_session_id,
                    _reg_entry.runtime_attachment_session_id,
                    _reg_entry.durable_session_id, _reg_entry.continuity_epoch,
                )
            else:
                _reg_entry = register_session(
                    device_id,
                    posture=_inbound_runtime_posture,
                    runtime_attachment_session_id=inbound_attachment_id,
                    metadata={"registration_trigger": "android_device_register"},
                    durable_session_id=inbound_durable_session_id,
                    continuity_epoch=inbound_continuity_epoch,
                )
                logger.info(
                    "attached_runtime_session_registry: new_attachment via device_register: "
                    "device_id=%s runtime_session_id=%s runtime_attachment_session_id=%s "
                    "durable_session_id=%s continuity_epoch=%s",
                    device_id, _reg_entry.runtime_session_id,
                    _reg_entry.runtime_attachment_session_id,
                    _reg_entry.durable_session_id, _reg_entry.continuity_epoch,
                )
        except Exception as _reg_exc:
            logger.debug(
                "android_bridge: attached_runtime_session_registry non-fatal: device_id=%s error=%s",
                device_id, _reg_exc,
            )
            record_registration_gap(device_id, "attached_runtime_session_registry")

        # PR-C: assign Body Mesh roles based on device capability bitmask so
        # that the BodyMeshRegistry (and downstream presence/projection paths)
        # can correctly classify the device.
        _roles = []
        try:
            from core.mesh.body_mesh_registry import get_body_mesh_registry
            _cap_flags = message.get("capabilities", device.capabilities)
            _roles = _derive_body_mesh_roles(_cap_flags)
            get_body_mesh_registry().register(
                device_id,
                roles=_roles,
                metadata={"registration_trigger": "android_device_register", "platform": device.platform.value if device.platform else None},
            )
            logger.info(
                "BodyMeshRegistry: registered device_id=%s roles=%s",
                device_id, [r.value for r in _roles],
            )
        except Exception as _mesh_exc:
            logger.debug(
                "android_bridge: BodyMeshRegistry registration non-fatal: device_id=%s error=%s",
                device_id, _mesh_exc,
            )

        # D4 / CROSS-004: project registered Android device capabilities into the
        # canonical CapabilityAssimilationLayer so routing queries can treat the
        # device as a first-class executor immediately after registration.
        try:
            from core.capability_assimilation import assimilate_device

            _capability_names = _normalize_assimilation_capabilities(
                message.get("capabilities", device.capabilities)
            )
            assimilate_device(
                device_id,
                capabilities=_capability_names,
                host=str(getattr(device, "ip_address", "") or "localhost"),
                port=int(getattr(device, "port", 0) or 0),
                tags=[str(getattr(device, "platform", "") or "android")],
                metadata={
                    "registration_trigger": "android_device_register",
                    "platform": _enum_or_string(device.platform),
                    "device_type": _enum_or_string(device.device_type),
                    "model": getattr(device, "model", None),
                },
            )
            logger.info(
                "CapabilityAssimilationLayer: assimilated device_id=%s capabilities=%s",
                device_id,
                _capability_names,
            )
        except Exception as _assim_exc:
            logger.warning(
                "android_bridge: capability assimilation non-fatal: device_id=%s error=%s",
                device_id,
                _assim_exc,
            )
            record_registration_gap(device_id, "capability_assimilation")

        # PR-I: notify the auto-enrollment service so that MeshMembership and
        # Formation auto-enrollment are triggered as part of the registration chain.
        try:
            from core.mesh.mesh_auto_enrollment import notify_device_registered
            notify_device_registered(
                device_id,
                roles=_roles,
                session_id=inbound_attachment_id,
                metadata={"registration_trigger": "android_device_register"},
            )
        except Exception as _ae_exc:
            logger.debug(
                "android_bridge: auto_enrollment notify non-fatal: device_id=%s error=%s",
                device_id, _ae_exc,
            )

        logger.info(
            "Android device registered: device_id=%s model=%s platform=%s "
            "runtime_attachment_session_id=%s",
            device_id, device.model, device.platform, inbound_attachment_id,
        )

        _gaps = get_registration_gaps(device_id)
        if _gaps:
            logger.warning(
                "Device registration partially attached: device_id=%s gaps=%s — "
                "device is registered at transport level but downstream steps failed; "
                "dispatch reliability may be reduced",
                device_id, _gaps,
            )

        _recovery_replay_buffered_count = 0
        _recovery_replay_scheduled = False
        if _reconnect_outcome == "continuity_resume":
            _recovery_replay_buffered_count = (
                _schedule_pending_delivery_replay_on_canonical_reconnect(
                    device_id=device_id,
                    websocket=websocket,
                )
            )
            _recovery_replay_scheduled = _recovery_replay_buffered_count > 0
        _pending_lifecycle_decisions = _apply_pending_lifecycle_reconnect_decisions(
            device_id=device_id,
            continuity_outcome=_reconnect_outcome,
            delivery_replay_scheduled=_recovery_replay_scheduled,
        )
        _pending_lifecycle_summary = _summarize_pending_lifecycle_decisions(
            _pending_lifecycle_decisions
        )

        ack = MessageBuilder.device_register_ack(
            device_id=device_id,
            success=True,
            session_id=str(uuid.uuid4()),
            message="Registration successful",
        )
        # PR-G: echo back the canonical runtime_attachment_session_id so the
        # client can confirm and persist it for reconnect continuity.
        ack["runtime_attachment_session_id"] = inbound_attachment_id
        # Surface the continuity outcome so callers can distinguish a reconnect
        # that resumed an existing session ("continuity_resume") from a fresh
        # new attachment ("new_attachment").  This is the server-side canonical
        # answer to "is this a reconnect or a brand-new connection?".
        ack["continuity_outcome"] = _reconnect_outcome
        ack["source_runtime_posture"] = _inbound_runtime_posture
        # ``_reg_entry`` is produced by guarded registry calls above; keep this
        # defensive lookup so ack construction still degrades safely if a
        # partial/mock entry without runtime_session_id reaches this path.
        if _reg_entry is not None and getattr(_reg_entry, "runtime_session_id", None) is not None:
            ack["runtime_session_id"] = _reg_entry.runtime_session_id
        ack["recovery_replay_buffered_count"] = _recovery_replay_buffered_count
        ack["recovery_replay_scheduled"] = _recovery_replay_scheduled
        ack["pending_lifecycle_decision_count"] = len(_pending_lifecycle_decisions)
        ack["pending_lifecycle_decision_summary"] = _pending_lifecycle_summary
        if _pending_lifecycle_decisions:
            ack["pending_lifecycle_decisions"] = _pending_lifecycle_decisions
        # Surface registration completeness so callers can assert the state.
        ack["registration_fully_attached"] = len(_gaps) == 0
        if _gaps:
            ack["registration_gaps"] = _gaps

        _network_participation_tier = "connected"

        # PR-1: Derive and surface the authoritative Android network participation
        # tier at the point of registration.  This is the first moment at which V2
        # can compute a meaningful tier: the device has a WebSocket connection and
        # has just received a registration ack.  Subsequent capability reports and
        # mode-gate updates will push the tier higher.
        try:
            from core.android_network_participation import (  # noqa: PLC0415
                build_android_network_participation_state,
                record_participation_state,
                AndroidParticipationTransitionSignal,
                list_participation_transition_history,
            )
            _reg_posture = ""
            if _reg_entry is not None:
                _reg_posture = getattr(_reg_entry, "posture", "") or ""
            if not _reg_posture:
                _reg_posture = _inbound_runtime_posture
            _is_fully_attached = len(_gaps) == 0
            _signal = (
                AndroidParticipationTransitionSignal.registration_fully_attached
                if _is_fully_attached
                else AndroidParticipationTransitionSignal.registration_partial_attached
            )
            _participation_state = build_android_network_participation_state(
                device_id,
                websocket_connected=True,
                registration_ack_success=True,
                registration_fully_attached=_is_fully_attached,
                registration_gaps=_gaps,
                session_posture=_reg_posture,
                active_session_count=1 if _reg_entry is not None else 0,
                # capability_visible, cross_device_enabled, readiness_satisfied,
                # and dispatch_gate_passed are all False at registration time;
                # they will be updated when capability_report and device_state_snapshot
                # messages arrive.
                last_signal=_signal,
            )
            record_participation_state(_participation_state)
            ack["network_participation_tier"] = _participation_state.tier.value
            _network_participation_tier = _participation_state.tier.value
            ack["network_participation_transition_history"] = (
                list_participation_transition_history(device_id, limit=5)
            )
        except Exception as _npe:
            logger.debug(
                "registration: network_participation_tier derivation non-fatal: "
                "device_id=%s error=%s",
                device_id, _npe,
            )

        # 统一设备生命周期状态：在注册 ack 成功时更新生命周期阶段。
        # 这是设备从 unregistered → registered（或更高）的权威转换点。
        try:
            from core.device_lifecycle_state import (  # noqa: PLC0415
                transition_device_lifecycle,
                DeviceLifecycleTransitionEvent,
            )
            _lc_is_fully_attached = len(_gaps) == 0
            _lc_event = (
                DeviceLifecycleTransitionEvent.registration_fully_attached
                if _lc_is_fully_attached
                else DeviceLifecycleTransitionEvent.register_ack_sent
            )
            _lc_record = transition_device_lifecycle(
                device_id,
                _lc_event,
                websocket_connected=True,
                registration_ack_success=True,
                registration_fully_attached=_lc_is_fully_attached,
                registration_gaps=_gaps,
            )
            ack["device_lifecycle_stage"] = _lc_record.stage.value
        except Exception as _lce:
            logger.debug(
                "registration: device_lifecycle_stage derivation non-fatal: "
                "device_id=%s error=%s",
                device_id, _lce,
            )

        _decorate_registration_boundary(
            ack=ack,
            websocket_device_id=websocket_device_id,
            auth_outcome=auth_outcome,
            identity_outcome=identity_outcome,
            registration_success=True,
            registration_fully_attached=len(_gaps) == 0,
            registration_gaps=_gaps,
            network_participation_tier=_network_participation_tier,
        )

        return ack

    except Exception as exc:
        _SENSITIVE_FIELDS = frozenset({
            "websocket", "image_base64", "token", "password",
            "credential", "secret", "auth", "api_key",
        })
        safe_payload = {k: v for k, v in message.items() if k not in _SENSITIVE_FIELDS}
        logger.error(
            "Device registration failed: device_id=%s error=%s payload=%s",
            device_id, exc, safe_payload,
        )
        return MessageBuilder.device_register_ack(
            device_id=device_id or "unknown",
            success=False,
            message=f"Registration failed: {exc}",
        )


async def handle_device_reconnect(
    bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]
) -> Dict[str, Any]:
    """Handle an explicit ``device_reconnect`` wire message.

    .. warning::

        **This is NOT the canonical Android production reconnect path.**

        Android clients reconnect by opening a new WebSocket and sending
        ``device_register`` with the same ``runtime_attachment_session_id``.
        That path goes through :func:`handle_device_register`, which calls
        :func:`~core.attached_runtime_session_registry.classify_reconnect_outcome`
        to determine continuity.  See
        :data:`DEVICE_REGISTER_IS_CANONICAL_RECONNECT_PATH`.

        This handler exists for backward-compat with any client that sends an
        explicit ``device_reconnect`` wire message.  In the current production
        system such messages are not sent by Android clients.  The handler is
        retained but is **not** the authoritative reconnect consumer.

    The handler classifies the inbound message as ``continuity_resume`` or
    ``new_attachment`` and updates the registry accordingly, mirroring the
    logic in :func:`handle_device_register`.

    Continuity resume
        The existing registry entry is reconnected via
        :func:`~core.attached_runtime_session_registry.reconnect_session`.
        The stable ``runtime_session_id`` and ``runtime_attachment_session_id``
        are preserved.

    New attachment
        The reconnect is treated as a fresh registration:
        :func:`~core.attached_runtime_session_registry.register_session` is
        called with the supplied ``runtime_attachment_session_id`` (or a
        generated fallback if absent).

    Backward compatibility
        Older clients that do not supply ``runtime_attachment_session_id`` are
        handled gracefully: the existing session is resumed when one exists,
        or a new attachment is created when no prior session is found.
    """
    device_id = message.get("device_id")

    try:
        # PR-G: extract canonical attachment identity from the reconnect message.
        inbound_attachment_id = _extract_runtime_attachment_session_id(message)
        inbound_durable_session_id, inbound_continuity_epoch = _extract_durable_continuity_fields(
            message
        )

        # Update local transport/session cache so the bridge sees the new socket.
        async with bridge._lock:
            if device_id in bridge._devices:
                bridge._devices[device_id].websocket = websocket
            else:
                device = AndroidDevice.from_registration(message)
                device.websocket = websocket
                bridge._devices[device_id] = device

        bridge._sync_device_router_session(device_id, websocket=websocket, connected=True)

        # PR-G: classify reconnect outcome
        outcome = "new_attachment"
        existing_entry = None
        try:
            from core.attached_runtime_session_registry import (
                classify_reconnect_outcome,
                reconnect_session,
                register_session,
            )
            outcome, existing_entry = classify_reconnect_outcome(
                device_id,
                runtime_attachment_session_id=inbound_attachment_id,
                durable_session_id=inbound_durable_session_id,
                continuity_epoch=inbound_continuity_epoch,
            )
        except Exception as _cls_exc:
            logger.debug(
                "handle_device_reconnect: classify_reconnect_outcome non-fatal: "
                "device_id=%s error=%s",
                device_id, _cls_exc,
            )

        resolved_attachment_id = inbound_attachment_id

        if outcome == "continuity_resume" and existing_entry is not None:
            logger.info(
                "handle_device_reconnect: continuity_resume: device_id=%s "
                "runtime_attachment_session_id=%s reconnect_count=%s",
                device_id,
                existing_entry.runtime_attachment_session_id,
                existing_entry.reconnect_count,
            )
            resolved_attachment_id = existing_entry.runtime_attachment_session_id
            try:
                reconnect_session(
                    existing_entry,
                    runtime_attachment_session_id=resolved_attachment_id,
                    metadata={"reconnect_trigger": "android_device_reconnect"},
                    durable_session_id=inbound_durable_session_id,
                    continuity_epoch=inbound_continuity_epoch,
                )
            except Exception as _rec_exc:
                logger.debug(
                    "handle_device_reconnect: reconnect_session non-fatal: "
                    "device_id=%s error=%s",
                    device_id, _rec_exc,
                )
        else:
            # new_attachment: treat as a fresh registration
            logger.info(
                "handle_device_reconnect: new_attachment: device_id=%s "
                "runtime_attachment_session_id=%s",
                device_id, resolved_attachment_id,
            )
            try:
                register_session(
                    device_id,
                    posture="join_runtime",
                    runtime_attachment_session_id=resolved_attachment_id,
                    metadata={"reconnect_trigger": "android_device_reconnect"},
                    durable_session_id=inbound_durable_session_id,
                    continuity_epoch=inbound_continuity_epoch,
                )
            except Exception as _reg_exc:
                logger.debug(
                    "handle_device_reconnect: register_session non-fatal: "
                    "device_id=%s error=%s",
                    device_id, _reg_exc,
                )

        # Also update the attached_runtime_session record so both stores align.
        try:
            from core.attached_runtime_session import attach_runtime_session
            attach_runtime_session(
                device_id,
                source_runtime_posture="join_runtime",
                runtime_attachment_session_id=resolved_attachment_id,
                attach_reason=f"android_device_reconnect:{outcome}",
                metadata={"reconnect_trigger": "android_device_reconnect"},
            )
        except Exception as _attach_exc:
            logger.debug(
                "handle_device_reconnect: attach_runtime_session non-fatal: "
                "device_id=%s error=%s",
                device_id, _attach_exc,
            )

        _pending_lifecycle_decisions = _apply_pending_lifecycle_reconnect_decisions(
            device_id=device_id,
            continuity_outcome=outcome,
            delivery_replay_scheduled=False,
        )

        ack = {
            "type": "reconnect_ack",
            "device_id": device_id,
            "success": True,
            "continuity_outcome": outcome,
            "runtime_attachment_session_id": resolved_attachment_id,
            "pending_lifecycle_decision_count": len(_pending_lifecycle_decisions),
            "pending_lifecycle_decision_summary": _summarize_pending_lifecycle_decisions(
                _pending_lifecycle_decisions
            ),
            "message": f"Reconnect processed: {outcome}",
        }
        if _pending_lifecycle_decisions:
            ack["pending_lifecycle_decisions"] = _pending_lifecycle_decisions
        return ack

    except Exception as exc:
        logger.error(
            "Device reconnect failed: device_id=%s error=%s",
            device_id, exc,
        )
        return {
            "type": "reconnect_ack",
            "device_id": device_id or "unknown",
            "success": False,
            "continuity_outcome": "error",
            "message": f"Reconnect failed: {exc}",
        }


async def handle_unregistered(
    bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]
) -> Dict[str, Any]:
    """通用处理器 — 记录日志并返回 ACK，防止消息被静默丢弃"""
    msg_type = message.get("type", "unknown")
    device_id = message.get("device_id", "unknown")
    logger.info(
        "Unhandled message type '%s' from device '%s', returning ACK",
        msg_type, device_id,
    )
    return {
        "type": "ack",
        "device_id": device_id,
        "original_type": msg_type,
        "status": "received",
        "note": "No specific handler registered for this message type",
    }
