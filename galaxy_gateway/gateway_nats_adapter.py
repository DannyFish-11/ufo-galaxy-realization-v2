"""
Galaxy Gateway — NATS ↔ WebSocket Adapter (Phase B)
====================================================

Bridges the NATS JetStream control plane with the WebSocket / HTTP device
transport layer so that tasks dispatched by MasterBrain (or any NATS
publisher) are forwarded to the appropriate physical device and the result
is published back to NATS.

Subject layout (matches NATSBus / contracts):
  Subscribe : galaxy.tasks.dispatch.gateway   (durable consumer "gateway")
  Publish   : galaxy.tasks.result.{task_id}
  Events    : galaxy.events.gateway_success / gateway_failure / gateway_timeout

Usage (called from galaxy_gateway/app.py lifespan)::

    from galaxy_gateway.gateway_nats_adapter import GatewayNATSAdapter
    adapter = GatewayNATSAdapter(device_manager, websocket_manager)
    await adapter.start()
    # … on shutdown:
    await adapter.stop()

Configuration (env vars):
  GALAXY_NATS_URL               — NATS server URL (e.g. nats://localhost:4222)
  GALAXY_GW_ADAPTER_TIMEOUT     — per-task WebSocket timeout in seconds (default 30)
  GALAXY_GW_ADAPTER_RETRIES     — max delivery retries before DLQ (default 2)
  GALAXY_GW_ADAPTER_DLQ_SUBJECT — dead-letter subject (default galaxy.tasks.deadletter)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("gateway_nats_adapter")

_TASK_TIMEOUT_S = float(os.getenv("GALAXY_GW_ADAPTER_TIMEOUT", "30"))
_MAX_RETRIES = int(os.getenv("GALAXY_GW_ADAPTER_RETRIES", "2"))
_DLQ_SUBJECT = os.getenv("GALAXY_GW_ADAPTER_DLQ_SUBJECT", "galaxy.tasks.deadletter")
_SUBSCRIBE_SUBJECT = "galaxy.tasks.dispatch.gateway"
_DURABLE_NAME = "gateway"


class GatewayNATSAdapter:
    """Bridges NATS JetStream task dispatches to connected WebSocket devices.

    - Subscribes to ``galaxy.tasks.dispatch.gateway`` (durable "gateway").
    - For each :class:`~core.schemas.contracts.TaskDispatchModel`, locates the
      target device in *device_manager* / *websocket_manager* and forwards the
      task payload via WebSocket.
    - Awaits the device result (via :attr:`DeviceRouter.task_results` or an
      injected result-callback) and publishes it back to
      ``galaxy.tasks.result.{task_id}``.
    - On timeout or failure emits ``galaxy.events.gateway_failure`` and, after
      exceeding *max_retries*, publishes to the dead-letter subject.
    """

    def __init__(
        self,
        device_manager: Any = None,
        websocket_manager: Any = None,
        task_timeout: float = _TASK_TIMEOUT_S,
        max_retries: int = _MAX_RETRIES,
        dlq_subject: str = _DLQ_SUBJECT,
    ) -> None:
        self._device_manager = device_manager
        self._websocket_manager = websocket_manager
        self._task_timeout = task_timeout
        self._max_retries = max_retries
        self._dlq_subject = dlq_subject

        # Pending task futures: task_id -> asyncio.Future
        # PR-S5: this local dict is retained as a COMPAT SURFACE only.
        # Canonical pending-future tracking now uses
        # core.task_envelope_lifecycle_registry.TaskEnvelopeLifecycleRegistry.
        # New code must use the canonical registry; this dict is updated in
        # parallel so that legacy callers of resolve_task() continue to work.
        self._pending: Dict[str, asyncio.Future] = {}

        # PR-S5: reference to the canonical lifecycle registry (lazy-init).
        self._lifecycle_registry: Optional[Any] = None

        self._started = False
        self._stats = {
            "dispatched": 0,
            "succeeded": 0,
            "failed": 0,
            "timed_out": 0,
            "dlq": 0,
        }

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Subscribe to NATS and begin processing gateway task dispatches."""
        if self._started:
            return
        try:
            from core.nats_bus import nats_bus

            if not nats_bus.is_connected():
                logger.warning(
                    "GatewayNATSAdapter: NATS not connected — adapter is inactive"
                )
                return

            result = await nats_bus._subscribe(
                _SUBSCRIBE_SUBJECT,
                self._handle_task_dispatch,
                durable=_DURABLE_NAME,
            )
            if result.get("success"):
                self._started = True
                logger.info(
                    "GatewayNATSAdapter: subscribed to %s (durable=%s)",
                    _SUBSCRIBE_SUBJECT,
                    _DURABLE_NAME,
                )
                _try_emit_event("GATEWAY_ADAPTER_STARTED", {"subject": _SUBSCRIBE_SUBJECT})
            else:
                logger.error("GatewayNATSAdapter: subscription failed — %s", result)
        except Exception as exc:
            logger.error("GatewayNATSAdapter.start error: %s", exc)

    async def stop(self) -> None:
        """Cancel all pending tasks and unsubscribe."""
        self._started = False
        # PR-S5: cancel via the canonical registry first, then drain compat dict.
        try:
            reg = self._get_lifecycle_registry()
            if reg is not None:
                reg.cancel_all()
        except Exception:
            pass
        for fut in list(self._pending.values()):
            if not fut.done():
                fut.cancel()
        self._pending.clear()
        logger.info("GatewayNATSAdapter: stopped")

    # ── Task resolution (called by WebSocket handler when device returns result) ─

    def resolve_task(self, task_id: str, result: dict) -> None:
        """Resolve a pending task future with the device result.

        Called from the WebSocket message handler when a task_result message
        arrives from a device.

        PR-S5: result completion is now delegated to the canonical lifecycle
        registry.  The local ``_pending`` compat dict is also updated so that
        callers that hold a reference to the legacy future still see the result.
        """
        # PR-S5: canonical registry is the authoritative completer.
        try:
            reg = self._get_lifecycle_registry()
            if reg is not None:
                reg.complete(task_id, result)
        except Exception as _reg_exc:
            logger.debug("resolve_task: registry complete error — %s", _reg_exc)
        # Compat: also resolve the local future if still present.
        fut = self._pending.get(task_id)
        if fut and not fut.done():
            fut.set_result(result)

    # ── Lifecycle registry access ─────────────────────────────────────────────

    def _get_lifecycle_registry(self) -> Optional[Any]:
        """Lazily obtain the canonical TaskEnvelopeLifecycleRegistry (fail-soft)."""
        if self._lifecycle_registry is None:
            try:
                from core.task_envelope_lifecycle_registry import get_lifecycle_registry
                self._lifecycle_registry = get_lifecycle_registry()
            except Exception as _e:
                logger.debug("GatewayNATSAdapter: lifecycle registry unavailable — %s", _e)
        return self._lifecycle_registry

    # ── Internal handlers ────────────────────────────────────────────────────

    async def _handle_task_dispatch(self, data: dict) -> None:
        """Process a TaskDispatch (or TaskEnvelope) message from NATS.

        PR-3: Incoming NATS messages are normalised to a TaskEnvelope before
        entering the routing path:
          - If ``_nats_schema == "TaskEnvelope"``, the payload is validated
            directly as a TaskEnvelope.
          - Otherwise (legacy TaskDispatch) the dict is converted via
            ``envelope_from_task_dispatch()`` so that the rest of the handler
            always works with a unified envelope object.
        Old TaskDispatch callers remain fully supported through this bridge.
        """
        nats_schema = data.get("_nats_schema", "")

        if nats_schema == "TaskEnvelope":
            # ── Parse as TaskEnvelope (primary format) ──────────────────────
            _envelope_parsed = False
            try:
                from core.schemas.task_envelope import TaskEnvelope as _TaskEnvelope

                _envelope = _TaskEnvelope.model_validate(data)
                task_id = _envelope.task_id
                trace_id = _envelope.trace_id
                target_device = _envelope.target
                task_type = _envelope.tool_name
                payload = _envelope.args
                route_mode = _envelope.metadata.get("route_mode", "direct")
                # PR-7: extract remote_execution_mode from the substrate envelope
                # so that both command_only and agent_runtime dispatches carry the
                # same substrate metadata through the gateway transport layer.
                remote_execution_mode = (
                    _envelope.remote_execution_mode.value
                    if _envelope.remote_execution_mode is not None
                    else _envelope.metadata.get("remote_execution_mode", "")
                )
                _envelope_parsed = True
                logger.debug(
                    "GatewayNATSAdapter: parsed TaskEnvelope task_id=%s trace_id=%s mode=%s",
                    task_id,
                    trace_id,
                    remote_execution_mode or "unset",
                )
            except Exception as _parse_err:
                logger.warning(
                    "GatewayNATSAdapter: TaskEnvelope parse failed, falling back to legacy — %s",
                    _parse_err,
                )

            if not _envelope_parsed:
                # Fall back to legacy field extraction
                task_id = data.get("task_id") or str(uuid.uuid4())
                trace_id = data.get("trace_id") or f"trace_{uuid.uuid4().hex[:12]}"
                target_device = data.get("target_worker_id") or data.get("target_device_id", "")
                task_type = data.get("task_type", "command")
                payload = data.get("payload") or {}
                route_mode = data.get("route_mode", "direct")
                remote_execution_mode = data.get("remote_execution_mode", "")
        else:
            # ── Legacy TaskDispatch — extract fields and convert to envelope ─
            task_id = data.get("task_id") or str(uuid.uuid4())
            target_device = data.get("target_worker_id") or data.get("target_device_id", "")
            task_type = data.get("task_type", "command")
            payload = data.get("payload") or {}
            trace_id = (
                data.get("trace_id")
                or (data.get("context") or {}).get("trace_id", "")
                or f"trace_{uuid.uuid4().hex[:12]}"
            )
            route_mode = data.get("route_mode", "direct")
            remote_execution_mode = data.get("remote_execution_mode", "")

            # PR-3: Convert legacy TaskDispatch → TaskEnvelope so that internal
            # routing always sees a unified envelope; replace task_id/trace_id
            # with canonical values from the envelope.
            try:
                from core.schemas.contracts import (
                    envelope_from_task_dispatch as _env_from_dispatch,
                    TaskDispatchModel as _TDM,
                )

                _legacy = _TDM.model_validate({**data, "task_id": task_id})
                _envelope = _env_from_dispatch(_legacy)
                task_id = _envelope.task_id
                trace_id = _envelope.trace_id
                logger.debug(
                    "GatewayNATSAdapter: converted legacy TaskDispatch → TaskEnvelope "
                    "task_id=%s trace_id=%s",
                    task_id,
                    trace_id,
                )
            except Exception as _conv_err:
                logger.debug(
                    "GatewayNATSAdapter: TaskDispatch→Envelope conversion skipped — %s",
                    _conv_err,
                )

        logger.info(
            "GatewayNATSAdapter: received dispatch task_id=%s target=%s type=%s "
            "trace_id=%s mode=%s",
            task_id,
            target_device,
            task_type,
            trace_id,
            remote_execution_mode or "unset",
        )
        self._stats["dispatched"] += 1

        for attempt in range(self._max_retries + 1):
            try:
                result = await asyncio.wait_for(
                    self._forward_to_device(
                        task_id, target_device, task_type, payload,
                        remote_execution_mode=remote_execution_mode,
                    ),
                    timeout=self._task_timeout,
                )
                # Publish success result back to NATS
                await self._publish_result(
                    task_id, result, success=True, trace_id=trace_id,
                    remote_execution_mode=remote_execution_mode,
                )
                self._stats["succeeded"] += 1
                await _publish_event(
                    "gateway_success",
                    {"task_id": task_id, "target": target_device, "attempt": attempt},
                )
                # M2 并行发布 — task.lifecycle (completed)
                _publish_m2_event_safe(
                    "task.lifecycle",
                    "gateway",
                    {
                        "task_id": task_id,
                        "status": "completed",
                        "task_type": task_type,
                        "target_device": target_device,
                    },
                    node="gateway_nats_adapter",
                    task_id=task_id,
                )
                return
            except asyncio.TimeoutError:
                self._stats["timed_out"] += 1
                logger.warning(
                    "GatewayNATSAdapter: task %s timed out (attempt %d/%d)",
                    task_id,
                    attempt + 1,
                    self._max_retries + 1,
                )
                if attempt < self._max_retries:
                    await asyncio.sleep(1.0 * (attempt + 1))  # simple back-off
                    continue
                # Exhausted retries
                await self._publish_result(
                    task_id,
                    {"success": False, "error": "timeout"},
                    success=False,
                    trace_id=trace_id,
                )
                await self._publish_dlq(task_id, data, reason="timeout")
                await _publish_event(
                    "gateway_timeout",
                    {"task_id": task_id, "target": target_device, "retries": attempt},
                )
                # M2 并行发布 — task.lifecycle (failed/timeout)
                _publish_m2_event_safe(
                    "task.lifecycle",
                    "gateway",
                    {
                        "task_id": task_id,
                        "status": "failed",
                        "task_type": task_type,
                        "target_device": target_device,
                        "error": "timeout",
                    },
                    node="gateway_nats_adapter",
                    task_id=task_id,
                )
            except Exception as exc:
                self._stats["failed"] += 1
                logger.error("GatewayNATSAdapter: task %s error — %s", task_id, exc)
                await self._publish_result(
                    task_id,
                    {"success": False, "error": str(exc)},
                    success=False,
                    trace_id=trace_id,
                )
                await self._publish_dlq(task_id, data, reason=str(exc))
                await _publish_event(
                    "gateway_failure",
                    {"task_id": task_id, "target": target_device, "error": str(exc)},
                )
                # M2 并行发布 — task.lifecycle (failed)
                _publish_m2_event_safe(
                    "task.lifecycle",
                    "gateway",
                    {
                        "task_id": task_id,
                        "status": "failed",
                        "task_type": task_type,
                        "target_device": target_device,
                        "error": str(exc),
                    },
                    node="gateway_nats_adapter",
                    task_id=task_id,
                )
                return

    async def _forward_to_device(
        self,
        task_id: str,
        target_device: str,
        task_type: str,
        payload: dict,
        *,
        remote_execution_mode: str = "",
    ) -> dict:
        """Forward a task to the target device via WebSocket or HTTP fallback.

        PR-7: ``remote_execution_mode`` is forwarded alongside the task so
        that both ``command_only`` and ``agent_runtime`` dispatches carry the
        substrate mode label to the device layer.
        """
        # 1. Try DeviceRouter if available
        try:
            from galaxy_gateway.device_router import device_router

            if device_router and target_device:
                device = device_router.get_device(target_device)
                if device:
                    task = {
                        "task_id": task_id,
                        "task_type": task_type,
                        "payload": payload,
                    }
                    if remote_execution_mode:
                        task["remote_execution_mode"] = remote_execution_mode
                    result = await device_router.dispatch_task(task, device)
                    return result
        except Exception as exc:
            logger.debug("DeviceRouter dispatch failed, falling back: %s", exc)

        # 2. Try WebSocket manager directly
        if self._websocket_manager and target_device:
            # PR-S5: register with the canonical lifecycle registry so that
            # pending-future ownership and timeout semantics are unified.
            fut: asyncio.Future = asyncio.get_event_loop().create_future()
            # Compat surface: also update the local _pending dict so that
            # legacy callers of resolve_task() continue to work.
            self._pending[task_id] = fut
            try:
                from core.task_envelope_lifecycle_registry import (
                    get_lifecycle_registry,
                    LifecycleOwner as _Owner,
                )
                # Build a minimal envelope-like object for the registry.
                class _EnvProxy:
                    pass
                _ep = _EnvProxy()
                _ep.task_id = task_id
                _ep.trace_id = ""
                _ep.target = target_device
                _ep.tool_name = task_type
                _ep.timeout = self._task_timeout
                get_lifecycle_registry().register(
                    _ep,
                    future=fut,
                    owner=_Owner.DEVICE_DISPATCH,
                    metadata={"source": "gateway_nats_adapter"},
                )
            except Exception as _reg_exc:
                logger.debug(
                    "_forward_to_device: lifecycle registry register skipped — %s",
                    _reg_exc,
                )
            try:
                ws_message: dict = {
                    "type": "task_assign",
                    "task_id": task_id,
                    "task_type": task_type,
                    "device_id": target_device,
                    "payload": payload,
                }
                if remote_execution_mode:
                    ws_message["remote_execution_mode"] = remote_execution_mode
                message = json.dumps(ws_message)
                await self._websocket_manager.send_to_device(target_device, message)
                result = await asyncio.wait_for(fut, timeout=self._task_timeout)
                return result
            finally:
                self._pending.pop(task_id, None)

        # 3. No device available
        logger.warning(
            "GatewayNATSAdapter: no route to device '%s' for task %s",
            target_device,
            task_id,
        )
        return {"success": False, "error": f"no_route_to_device:{target_device}"}

    async def _publish_result(
        self,
        task_id: str,
        result: dict,
        success: bool,
        trace_id: str = "",
        remote_execution_mode: str = "",
    ) -> None:
        """Publish task result back to NATS.

        PR-3: Publishes a unified result payload that carries both the legacy
        ``status`` / ``worker_id`` fields (for backward-compatible consumers)
        and a ``_nats_schema: "TaskEnvelope"`` discriminator with
        ``metadata.success``, ``metadata.result``, and ``metadata.error`` so
        that new consumers can parse it as a TaskEnvelope result.

        PR-7: ``remote_execution_mode`` is included in the result metadata so
        that NATS consumers can identify the substrate mode without inspecting
        payload shapes.
        """
        try:
            from core.nats_bus import nats_bus
            from core.schemas.contracts import TaskStatus, TimestampModel
            from datetime import datetime, timezone

            status_val = TaskStatus.SUCCESS.value if success else TaskStatus.FAILED.value
            ts = int(datetime.now(timezone.utc).timestamp())

            result_metadata: dict = {
                "success": success,
                "status": status_val,
                "result": result if success else None,
                "error": result.get("error") if not success else None,
            }
            if remote_execution_mode:
                result_metadata["remote_execution_mode"] = remote_execution_mode

            unified = {
                # ── Legacy TaskResult fields (backward compat) ──────────────
                "task_id": task_id,
                "worker_id": "gateway",
                "status": status_val,
                "completed_at": {"seconds": ts, "nanos": 0},
                # ── TaskEnvelope discriminator (PR-3) ───────────────────────
                "_nats_schema": "TaskEnvelope",
                "trace_id": trace_id or "",
                "metadata": result_metadata,
            }
            await nats_bus._publish(f"galaxy.tasks.result.{task_id}", unified)
        except Exception as exc:
            logger.error("GatewayNATSAdapter: failed to publish result for %s: %s", task_id, exc)

    async def _publish_dlq(self, task_id: str, original: dict, reason: str) -> None:
        """Publish undeliverable task to dead-letter subject."""
        self._stats["dlq"] += 1
        try:
            from core.nats_bus import nats_bus

            dlq_payload = {
                "task_id": task_id,
                "original": original,
                "reason": reason,
                "gateway_ts": time.time(),
            }
            await nats_bus._publish(self._dlq_subject, dlq_payload)
            logger.warning(
                "GatewayNATSAdapter: task %s sent to DLQ (%s) — %s",
                task_id,
                self._dlq_subject,
                reason,
            )
        except Exception as exc:
            logger.error("GatewayNATSAdapter: DLQ publish failed: %s", exc)

    # ── Stats ────────────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Return adapter statistics."""
        # PR-S5: include canonical registry pending count alongside local compat dict.
        registry_pending = 0
        try:
            reg = self._get_lifecycle_registry()
            if reg is not None:
                registry_pending = reg.pending_count()
        except Exception:
            pass
        return {
            "started": self._started,
            "pending_tasks": len(self._pending),
            "registry_pending_tasks": registry_pending,
            **self._stats,
        }


# ── Module-level singleton ───────────────────────────────────────────────────

_adapter: Optional[GatewayNATSAdapter] = None


def get_gateway_nats_adapter() -> Optional[GatewayNATSAdapter]:
    """Return the module-level adapter instance (None if not yet created)."""
    return _adapter


def init_gateway_nats_adapter(
    device_manager: Any = None,
    websocket_manager: Any = None,
) -> GatewayNATSAdapter:
    """Create and store the module-level adapter singleton."""
    global _adapter
    _adapter = GatewayNATSAdapter(
        device_manager=device_manager,
        websocket_manager=websocket_manager,
    )
    return _adapter


# ── Helpers ──────────────────────────────────────────────────────────────────


def _try_emit_event(event_type_name: str, data: dict) -> None:
    try:
        from integration.event_bus import event_bus, EventType

        et = getattr(EventType, event_type_name, None)
        if et is not None:
            event_bus.publish_sync(et, "gateway_nats_adapter", data)
    except Exception:
        pass


async def _publish_event(event_type: str, data: dict) -> None:
    try:
        from core.nats_bus import nats_bus
        from core.schemas.contracts import AgentEventModel, EventDomain, EventSeverity

        evt = AgentEventModel(
            event_id=str(uuid.uuid4()),
            event_type=event_type,
            domain=EventDomain.UNSPECIFIED,
            severity=EventSeverity.INFO,
            source="gateway_nats_adapter",
            payload=data,
        )
        await nats_bus.publish_event(evt)
    except Exception:
        pass


def _publish_m2_event_safe(event_type: str, device_id: str, payload: dict, **kw) -> None:
    """发布 M2 统一事件的轻量辅助函数（失败不崩溃）。"""
    try:
        from integration.event_bus import build_m2_event, publish_m2_event
        evt = build_m2_event(event_type, device_id, payload, **kw)
        publish_m2_event(evt)
    except Exception as _exc:
        logger.debug("GatewayNATSAdapter: M2 发布失败（非致命）: %s", _exc)
