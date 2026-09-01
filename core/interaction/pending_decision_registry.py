"""
core/interaction/pending_decision_registry.py
==============================================
PR-HITL: Human-in-the-Loop pending-decision registry (bounded blocking await).

Why this exists
---------------
V2 could *emit* a ``decision_request`` to devices (``android_bridge.
push_decision_to_wearos``) and WearOS could *reply* (``human_input`` command),
but the two ends were never connected: the ``decision_id`` was generated and
discarded, there was no registry keyed by it, and no agent suspend/resume
primitive — so a human reply could not be correlated back to whatever was
asking.  This module closes that loop.

Model (Approach A — bounded blocking await)
-------------------------------------------
The cognitive loop asks a question via :func:`request_human_decision`, which:

1. mints a ``decision_id`` and registers a :class:`PendingDecision` (holding an
   :class:`asyncio.Future` + the original options/context/timeout policy),
2. emits the ``decision_request`` to the target devices (caller-supplied emit
   callback — keeps this module transport-agnostic),
3. ``await``\\s the future with a bounded timeout (default 60 s).

When the device replies, the gateway calls :meth:`PendingDecisionRegistry.resolve`
(``decision_id`` → choice), which resolves the future; the asking coroutine
resumes **in its original context**.  No new suspend/resume machinery is needed
— this mirrors the existing :mod:`core.task_envelope_lifecycle_registry` pattern
which already blocks a coroutine awaiting a device task result.

Composite timeout fallback (依情况)
-----------------------------------
On timeout the outcome is resolved per the decision's :class:`OnTimeout` policy,
which is **chosen per decision** (composite, not one-size-fits-all):

* ``DEFAULT_OPTION`` — resolve to the pre-declared ``default_option``.
* ``CANCEL``         — abort; the asker should not proceed.
* ``PROCEED``        — continue without explicit confirmation.

When the caller does not pin a policy, :func:`derive_default_on_timeout` picks
one from ``urgency`` (high → CANCEL, normal → DEFAULT_OPTION if a default exists
else PROCEED, low → PROCEED).
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional

from core import upper_ports

logger = logging.getLogger("Galaxy.HITL")

_DEFAULT_TIMEOUT_S: float = 60.0


# ---------------------------------------------------------------------------
# Outcome / policy types
# ---------------------------------------------------------------------------
class OnTimeout(str, Enum):
    """What to do when no human replies before the timeout."""

    DEFAULT_OPTION = "default_option"  # resolve to the declared default option
    CANCEL = "cancel"  # abort — asker must not proceed
    PROCEED = "proceed"  # continue without confirmation

    @classmethod
    def from_string(cls, value: Optional[str]) -> Optional["OnTimeout"]:
        if not value:
            return None
        try:
            return cls(str(value).lower().strip())
        except ValueError:
            return None


class DecisionStatus(str, Enum):
    RESOLVED = "resolved"  # a human answered
    TIMEOUT_DEFAULT = "timeout_default"  # timed out → default option applied
    TIMEOUT_CANCEL = "timeout_cancel"  # timed out → cancelled
    TIMEOUT_PROCEED = "timeout_proceed"  # timed out → proceed unconfirmed
    CANCELLED = "cancelled"  # explicitly cancelled (e.g. shutdown)


@dataclass
class DecisionOutcome:
    """Result handed back to the asking coroutine."""

    decision_id: str
    status: DecisionStatus
    selected_option: Optional[str] = None
    voice_input: str = ""
    source: str = ""
    elapsed_s: float = 0.0

    @property
    def timed_out(self) -> bool:
        return self.status in (
            DecisionStatus.TIMEOUT_DEFAULT,
            DecisionStatus.TIMEOUT_CANCEL,
            DecisionStatus.TIMEOUT_PROCEED,
        )

    @property
    def should_proceed(self) -> bool:
        """True iff the asker may proceed (a choice exists or PROCEED policy)."""
        if self.status == DecisionStatus.RESOLVED:
            return True
        return self.status in (DecisionStatus.TIMEOUT_DEFAULT, DecisionStatus.TIMEOUT_PROCEED)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "status": self.status.value,
            "selected_option": self.selected_option,
            "voice_input": self.voice_input,
            "source": self.source,
            "elapsed_s": round(self.elapsed_s, 3),
            "timed_out": self.timed_out,
            "should_proceed": self.should_proceed,
        }


def derive_default_on_timeout(urgency: str, has_default: bool) -> OnTimeout:
    """Composite fallback selection when the caller does not pin a policy."""
    u = (urgency or "normal").lower().strip()
    if u == "high":
        # High-urgency / risky actions: never auto-proceed without a human.
        return OnTimeout.CANCEL
    if u == "low":
        return OnTimeout.PROCEED
    # normal: prefer a safe default option if one was declared, else proceed.
    return OnTimeout.DEFAULT_OPTION if has_default else OnTimeout.PROCEED


# ---------------------------------------------------------------------------
# Pending record
# ---------------------------------------------------------------------------
@dataclass
class PendingDecision:
    decision_id: str
    future: asyncio.Future
    options: List[str]
    default_option: Optional[str]
    on_timeout: OnTimeout
    urgency: str
    timeout_s: float
    session_id: str = ""
    runtime_session_id: str = ""
    devices: List[str] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def elapsed(self) -> float:
        return time.time() - self.created_at


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
class PendingDecisionRegistry:
    """Singleton registry of in-flight human decisions, keyed by ``decision_id``."""

    def __init__(self) -> None:
        self._pending: Dict[str, PendingDecision] = {}
        self._resolved: int = 0
        self._timed_out: int = 0

    # ── Registration ──────────────────────────────────────────────────────
    def register(
        self,
        *,
        options: Optional[List[str]] = None,
        default_option: Optional[str] = None,
        on_timeout: Optional[OnTimeout] = None,
        urgency: str = "normal",
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        session_id: str = "",
        runtime_session_id: str = "",
        devices: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
        decision_id: Optional[str] = None,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ) -> PendingDecision:
        """Register a pending decision and return the record (holding a Future)."""
        did = decision_id or uuid.uuid4().hex
        _loop = loop or asyncio.get_event_loop()
        future: asyncio.Future = _loop.create_future()
        opts = list(options or [])
        policy = on_timeout or derive_default_on_timeout(urgency, default_option is not None)
        record = PendingDecision(
            decision_id=did,
            future=future,
            options=opts,
            default_option=default_option,
            on_timeout=policy,
            urgency=urgency,
            timeout_s=float(timeout_s),
            session_id=session_id,
            runtime_session_id=runtime_session_id,
            devices=list(devices or []),
            context=dict(context or {}),
        )
        self._pending[did] = record
        logger.info(
            "HITL.register | decision_id=%s urgency=%s on_timeout=%s timeout=%.0fs devices=%s",
            did,
            urgency,
            policy.value,
            timeout_s,
            record.devices,
        )
        return record

    # ── Resolution (called by the gateway when a human replies) ───────────
    def resolve(
        self,
        decision_id: str,
        *,
        selected_option: Optional[str] = None,
        voice_input: str = "",
        source: str = "",
    ) -> bool:
        """Resolve a pending decision with a human reply.

        Returns ``True`` iff a matching pending decision was found and resolved.
        First reply wins; later replies for the same id are no-ops (e.g. when
        the same decision was fanned out to several devices).
        """
        record = self._pending.pop(decision_id, None)
        if record is None:
            logger.debug("HITL.resolve: no pending decision for id=%s", decision_id)
            return False
        self._resolved += 1
        outcome = DecisionOutcome(
            decision_id=decision_id,
            status=DecisionStatus.RESOLVED,
            selected_option=selected_option,
            voice_input=voice_input,
            source=source,
            elapsed_s=record.elapsed(),
        )
        logger.info(
            "HITL.resolve | decision_id=%s option=%r source=%s elapsed=%.2fs",
            decision_id,
            selected_option,
            source,
            outcome.elapsed_s,
        )
        if not record.future.done():
            record.future.set_result(outcome)
        return True

    def cancel(self, decision_id: str, reason: str = "cancelled") -> bool:
        """Explicitly cancel a pending decision (e.g. task aborted / shutdown)."""
        record = self._pending.pop(decision_id, None)
        if record is None:
            return False
        outcome = DecisionOutcome(
            decision_id=decision_id,
            status=DecisionStatus.CANCELLED,
            source=reason,
            elapsed_s=record.elapsed(),
        )
        if not record.future.done():
            record.future.set_result(outcome)
        return True

    # ── Bounded await with composite timeout fallback ─────────────────────
    async def await_decision(self, record: PendingDecision) -> DecisionOutcome:
        """Block (bounded) until the decision resolves, applying the timeout policy."""
        try:
            return await asyncio.wait_for(record.future, timeout=record.timeout_s)
        except asyncio.TimeoutError:
            # Remove if still pending and synthesise the policy-driven outcome.
            self._pending.pop(record.decision_id, None)
            self._timed_out += 1
            outcome = self._timeout_outcome(record)
            logger.info(
                "HITL.timeout | decision_id=%s policy=%s → status=%s after %.0fs",
                record.decision_id,
                record.on_timeout.value,
                outcome.status.value,
                record.timeout_s,
            )
            return outcome
        except asyncio.CancelledError:
            self._pending.pop(record.decision_id, None)
            return DecisionOutcome(
                decision_id=record.decision_id,
                status=DecisionStatus.CANCELLED,
                elapsed_s=record.elapsed(),
            )

    def _timeout_outcome(self, record: PendingDecision) -> DecisionOutcome:
        if record.on_timeout == OnTimeout.DEFAULT_OPTION:
            return DecisionOutcome(
                decision_id=record.decision_id,
                status=DecisionStatus.TIMEOUT_DEFAULT,
                selected_option=record.default_option,
                source="timeout",
                elapsed_s=record.elapsed(),
            )
        if record.on_timeout == OnTimeout.CANCEL:
            return DecisionOutcome(
                decision_id=record.decision_id,
                status=DecisionStatus.TIMEOUT_CANCEL,
                source="timeout",
                elapsed_s=record.elapsed(),
            )
        return DecisionOutcome(
            decision_id=record.decision_id,
            status=DecisionStatus.TIMEOUT_PROCEED,
            source="timeout",
            elapsed_s=record.elapsed(),
        )

    # ── Introspection / maintenance ───────────────────────────────────────
    def get(self, decision_id: str) -> Optional[PendingDecision]:
        return self._pending.get(decision_id)

    def pending_ids(self) -> List[str]:
        return list(self._pending.keys())

    def stats(self) -> Dict[str, Any]:
        return {
            "pending": len(self._pending),
            "resolved": self._resolved,
            "timed_out": self._timed_out,
        }

    def sweep_expired(self) -> List[str]:
        """Resolve any records whose wall-clock age exceeded their timeout.

        Safety net for callers that registered but are not actively awaiting
        (await_decision already handles its own timeout).  Returns swept ids.
        """
        now = time.time()
        expired = [did for did, rec in list(self._pending.items()) if now - rec.created_at > rec.timeout_s]
        for did in expired:
            rec = self._pending.pop(did, None)
            if rec is None:
                continue
            self._timed_out += 1
            if not rec.future.done():
                rec.future.set_result(self._timeout_outcome(rec))
        return expired


_registry: Optional[PendingDecisionRegistry] = None


def get_pending_decision_registry() -> PendingDecisionRegistry:
    """Return the process-wide singleton registry."""
    global _registry
    if _registry is None:
        _registry = PendingDecisionRegistry()
    return _registry


# ---------------------------------------------------------------------------
# High-level gate — the single entry the cognitive loop calls to ask a human
# ---------------------------------------------------------------------------
# Emit callback: given (device_id, decision_request_message) deliver it.
EmitCallback = Callable[[str, Dict[str, Any]], Awaitable[Any]]


async def request_human_decision(
    *,
    title: str,
    summary: str = "",
    options: Optional[List[Dict[str, str]]] = None,
    default_option: Optional[str] = None,
    urgency: str = "normal",
    timeout_s: float = _DEFAULT_TIMEOUT_S,
    on_timeout: Optional[OnTimeout] = None,
    devices: Optional[List[str]] = None,
    emit: Optional[EmitCallback] = None,
    session_id: str = "",
    runtime_session_id: str = "",
) -> DecisionOutcome:
    """Ask connected device(s) a question and block (bounded) for the answer.

    This is the canonical HITL entry point.  ``emit`` is the transport hook —
    if ``None``, the default gateway emitter (:func:`_default_emit`) is used,
    which sends a ``decision_request`` to each device via the gateway
    connection manager (works for WearOS and phones alike).

    Trigger policy ("when to ask") is intentionally left to the caller — this
    function is the mechanism, invoked 依实际情况 by whatever cognitive gate
    decides a human is needed.
    """
    option_ids = [str(o.get("id")) for o in (options or []) if o.get("id") is not None]
    registry = get_pending_decision_registry()
    record = registry.register(
        options=option_ids,
        default_option=default_option,
        on_timeout=on_timeout,
        urgency=urgency,
        timeout_s=timeout_s,
        session_id=session_id,
        runtime_session_id=runtime_session_id,
        devices=devices or [],
    )

    decision_request = {
        "type": "decision_request",
        "payload": {
            "decision_id": record.decision_id,
            "title": title,
            "summary": summary,
            "options": options or [],
            "urgency": urgency,
            "timeout_ms": int(timeout_s * 1000),
            "default_option": default_option,
            "source": "openclawd",
            "timestamp": time.time(),
        },
    }

    _emit = emit or _default_emit
    targets = devices if devices is not None else await _discover_target_devices()
    if not targets:
        logger.warning("HITL.request: no target devices for decision_id=%s", record.decision_id)
    for did in targets:
        try:
            await _emit(did, decision_request)
        except Exception as exc:  # noqa: BLE001
            logger.debug("HITL.request: emit to %s failed: %s", did, exc)

    return await registry.await_decision(record)


async def _default_emit(device_id: str, message: Dict[str, Any]) -> None:
    """Default transport: deliver via the gateway connection manager."""
    connection_manager = upper_ports.resolve("gateway.websocket_handler.connection_manager")

    await connection_manager.send_to_device(device_id, message)


async def _discover_target_devices() -> List[str]:
    """Auto-discover connected WearOS + phone device ids to ask."""
    try:
        connection_manager = upper_ports.resolve("gateway.websocket_handler.connection_manager")
    except Exception:  # noqa: BLE001
        return []
    try:
        from core.routes._shared import registered_devices  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        registered_devices = {}
    try:
        ids = await connection_manager.get_connected_devices()
    except Exception:  # noqa: BLE001
        return []
    targets: List[str] = []
    for did in ids:
        dtype = str((registered_devices.get(did) or {}).get("device_type", "")).lower()
        if dtype in ("wear_os", "wearos", "watch", "galaxy_watch") or "phone" in dtype:
            targets.append(did)
    return targets
