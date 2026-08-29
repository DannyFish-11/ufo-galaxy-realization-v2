"""
galaxy_gateway/android/handlers/reconciliation_signal.py

Canonical gateway handler for Android reconciliation signals
(message type ``reconciliation_signal``, introduced in PR-7-V2 / PR-06-Android).

This handler is the **single authoritative entry-point** for inbound
``reconciliation_signal`` messages.  It:

1. Delegates all lifecycle processing to the
   :class:`~core.android_delegated_runtime_lifecycle_coordinator.AndroidDelegatedRuntimeLifecycleCoordinator`
   via :func:`~core.android_delegated_runtime_lifecycle_coordinator.get_lifecycle_coordinator`.
2. Logs the reconciliation outcome at DEBUG level.
3. Returns an ACK response.

Responsibility boundary
-----------------------
``reconciliation_signal`` is an *explicit state reconciliation push* from the
Android RuntimeController; it is **not** a delegated execution lifecycle event.
Its handling MUST NOT duplicate terminal event processing already applied by
``delegated_execution_signal`` (``handle_delegated_execution_signal``).

All business logic (participant truth ingress, session state reduction, and
audit recording) is performed by the lifecycle coordinator in the correct order,
maintaining the ingress → state-update → audit contract.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:
    from galaxy_gateway.android_bridge import AndroidBridge

from galaxy_gateway.android.handlers import mesh_mirror

logger = logging.getLogger(__name__)

# PR-11-V2: lifecycle coordinator — all ingress, state, and audit logic now
# lives in the coordinator.  Handlers delegate to it rather than wiring
# individual modules directly.
try:
    from core.android_delegated_runtime_lifecycle_coordinator import (
        get_lifecycle_coordinator as _get_lifecycle_coordinator,
    )
except ImportError:  # pragma: no cover
    _get_lifecycle_coordinator = None  # type: ignore[assignment]


async def handle_reconciliation_signal(
    bridge: "AndroidBridge",
    websocket: Any,
    message: Dict[str, Any],
) -> Dict[str, Any]:
    """Handle inbound ``reconciliation_signal`` message.

    Delegates all lifecycle processing to
    :func:`~core.android_delegated_runtime_lifecycle_coordinator.get_lifecycle_coordinator`
    which invokes participant truth ingress, session state reduction, and
    audit recording in the correct order.

    Parameters
    ----------
    bridge:
        The :class:`~galaxy_gateway.android_bridge.AndroidBridge` instance.
    websocket:
        The WebSocket connection (unused; reserved for future use).
    message:
        Raw inbound ``reconciliation_signal`` message dict.

    Returns
    -------
    dict
        ACK response sent back to the Android runtime.
    """
    device_id = message.get("device_id", "unknown")
    message_id = message.get("message_id") or str(uuid.uuid4())

    # PR-46: Cross-repo schema/version gate enforcement (COMPAT mode).
    # reconciliation_signal is a compat-degrade type: mismatches are logged
    # and included in the ACK as diagnostics evidence, but reconciliation
    # processing continues so that continuity recovery is not blocked.
    _rs_gate_decision = None
    try:
        from contracts.cross_repo_schema_version_gate import (
            evaluate_android_uplink_schema_gate as _evaluate_schema_gate,
        )

        _rs_gate_decision = _evaluate_schema_gate(
            message_type="reconciliation_signal",
            message=message,
        )
        if _rs_gate_decision is not None and _rs_gate_decision.action in {"reject", "degrade"}:
            logger.warning(
                "reconciliation_signal: schema/version gate %s "
                "type=reconciliation_signal reason=%s observed_schema=%r device=%s "
                "— proceeding in degraded mode with diagnostics evidence",
                _rs_gate_decision.action.upper(),
                _rs_gate_decision.reason,
                _rs_gate_decision.observed_schema_version,
                device_id,
            )
    except Exception as _rs_gate_err:
        logger.debug(
            "reconciliation_signal: schema gate check skipped (non-fatal): %s",
            _rs_gate_err,
        )

    if _get_lifecycle_coordinator is not None:
        try:
            outcome = _get_lifecycle_coordinator().on_reconciliation_signal(
                message=message,
            )
            if outcome.was_handled:
                logger.debug(
                    "reconciliation_signal processed via coordinator: %s",
                    outcome.description,
                )
            else:
                logger.debug(
                    "reconciliation_signal coordinator outcome not handled: " "device_id=%s description=%s",
                    device_id,
                    outcome.description,
                )
        except Exception as exc:  # pragma: no cover  # noqa: BLE001
            logger.warning(
                "reconciliation_signal coordinator call failed (non-fatal): " "device_id=%s exc=%s",
                device_id,
                exc,
            )
    else:  # pragma: no cover
        logger.debug(
            "reconciliation_signal: lifecycle coordinator unavailable " "(import failed): device_id=%s",
            device_id,
        )

    # 网格镜像:对账信号带的就是设备侧的运行时真相快照。这正是网格里其它节点
    # 用来消解状态分歧的输入 —— 只回给发信设备等于对账做了一半。
    mesh_mirror.mirror_reconciliation_signal(device_id, message)

    # ── 谁说了算:把判定回给设备 ────────────────────────────────────────────
    #
    # 对账信号是设备侧**显式推上来的状态**。它该不该被当成真值,取决于此刻的作用域
    # (见 core/scope_authority.py 模块头):
    #   · local        —— 中心不在场,设备自己说了算 → 收
    #   · cross_device —— 真值链与受理裁决都在中心侧 → 不收,设备该发 delta 由中心裁决
    #   · 判不出来      —— 说不出归属,一律不收
    #
    # 这里**只回判定,不改协处理器的既有行为**,而且这一点必须说清楚:V2 侧现在做到的
    # 是"把权威归属如实告诉设备",让 Android 有依据切到 delta 模式;真正的
    # "中心裁决 + 设备发 delta" 还需要 ufo-galaxy-android 那一侧改协议,不是这个仓
    # 单独能闭环的(路线图 D6 自己也写了 Cross-repo coordination required)。
    #
    # 老客户端会忽略这个未知字段,所以是向后兼容的。
    _authority_evidence = None
    try:
        from core.scope_authority import current_authority  # noqa: PLC0415

        _sa = current_authority(str(message.get("session_id") or device_id))
        _authority_evidence = _sa.to_dict()
        if not _sa.accepts_local_writes:
            logger.info(
                "reconciliation_signal: 设备 %s 推上来的状态**不作为真值** "
                "(scope=%s authority=%s) —— 该走 delta 由中心裁决",
                device_id,
                _sa.scope,
                _sa.authority,
            )
    except Exception as _sa_err:  # noqa: BLE001 — 判不出来就不带这个证据,不影响 ACK
        logger.debug("reconciliation_signal: 作用域权威判定跳过: %s", _sa_err)

    return {
        "version": "3.0",
        "type": "reconciliation_signal_ack",
        "device_id": device_id,
        "message_id": str(uuid.uuid4()),
        "correlation_id": message_id,
        "schema_gate_evidence": (
            _rs_gate_decision.to_dict()
            if _rs_gate_decision is not None and _rs_gate_decision.action != "accept"
            else None
        ),
        # 此刻谁说了算。accepts_local_writes=false 时,设备应当把本地状态改成
        # delta 上报而不是当作权威快照 —— 见上面注释里那条残留限制。
        "scope_authority": _authority_evidence,
    }
