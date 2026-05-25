"""
Galaxy Agentic OS — MasterBrain (Cloud Control Plane Orchestrator)
===================================================================

Central orchestrator that coordinates distributed task execution across
Edge Workers via NATS JetStream and Temporal workflows.

Constraints (see plan 强约束):
  C1  — module-level singleton (lazy, depends on GALAXY_MASTER_BRAIN_ENABLED)
  C2  — emits events through EventBus
  C5  — opt-in via ``GALAXY_MASTER_BRAIN_ENABLED=true``
  C7  — all methods return ``{"success": bool, "error": ...}``
  C8  — exposes ``get_status()`` matching GalaxyCore pattern
  C9  — integrates directly into GalaxyCore (no separate HTTP port)
  C11 — uses stdlib ``logging`` (matching codebase convention)
"""

from __future__ import annotations

import logging
import os
import time
import uuid
import asyncio
import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("master_brain")

from core.acl import AntiCorruptionLayer, acl
from core.nats_bus import NATSBus, nats_bus
from core.schemas.contracts import (
    AgentEventModel,
    EventDomain,
    EventSeverity,
    TaskDispatchModel,
    TaskResultModel,
    TaskStatus,
    WorkerHeartbeatModel,
    WorkerRegistrationModel,
    WorkerShutdownModel,
)


def _try_emit_event(event_type_name: str, data: dict) -> None:
    """Best-effort emit to EventBus.  Never raises."""
    try:
        from integration.event_bus import event_bus, EventType

        et = getattr(EventType, event_type_name, None)
        if et is not None:
            event_bus.publish_sync(et, "agentic_os", data)
    except Exception:
        pass


# Heartbeat timeout: 3 missed heartbeats (10s interval × 3 = 30s)
_HEARTBEAT_TIMEOUT_S = 30


def _env_flag(name: str) -> bool:
    """Parse common truthy environment values consistently across entry points."""
    return str(os.environ.get(name, "")).strip().lower() in {"1", "true", "yes", "on"}


def master_brain_enabled() -> bool:
    """Return whether the distributed MasterBrain runtime is explicitly enabled."""
    return _env_flag("GALAXY_MASTER_BRAIN_ENABLED")


class MasterBrain:
    """Cloud-side orchestrator using contracts + NATS + Temporal.

    Manages:
      - Worker topology (registration, heartbeat, eviction)
      - Task dispatch via NATS (with ACL validation)
      - Temporal workflow launching
      - Worker load balancing
    """

    _instance: Optional[MasterBrain] = None

    def __init__(
        self,
        nats: NATSBus | None = None,
        acl_layer: AntiCorruptionLayer | None = None,
        state_path: str | os.PathLike[str] | None = None,
    ) -> None:
        self._nats = nats or nats_bus
        self._acl = acl_layer or acl
        self._workers: Dict[str, Dict[str, Any]] = {}
        self._task_log: Dict[str, Dict[str, Any]] = {}
        self._task_waiters: Dict[str, asyncio.Future] = {}
        self._temporal_client: Any = None
        self._temporal_worker: Any = None
        self._temporal_worker_task: Optional[asyncio.Task[Any]] = None
        self._temporal_last_error: str = ""
        self._temporal_worker_state: str = "inactive"
        self._started = False
        self._persistence_degraded = False
        self._persistence_last_error = ""
        self._last_scaling_decision: Dict[str, Any] = {
            "action": "no_change",
            "reason": "not_evaluated",
        }
        self._state_path = Path(
            state_path
            or os.environ.get("GALAXY_MASTER_BRAIN_STATE_PATH")
            or (Path(tempfile.gettempdir()) / "galaxy_master_brain_state.json")
        )
        self._load_state()
        self._recover_incomplete_state()

    @classmethod
    def get_instance(cls) -> MasterBrain:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Lifecycle ───────────────────────────────────────────────────────────

    async def start(self) -> dict:
        """Initialize MasterBrain: connect NATS, subscribe to events."""
        if self._started:
            return {
                "success": True,
                "already_started": True,
                "temporal_runtime_available": self.is_temporal_runtime_available(),
                "temporal_worker_state": self._temporal_worker_state,
            }

        # Connect NATS
        conn_result = await self._nats.connect()
        if not conn_result.get("success"):
            logger.warning("MasterBrain: NATS connection failed, operating in local-only mode")

        # Subscribe to worker lifecycle events
        nats_connected = self._nats.is_connected()
        subscriptions_ok = True
        if nats_connected:
            subscription_calls: list[tuple[str, Callable[..., Any], Callable[[dict], None]]] = [
                ("heartbeats", self._nats.subscribe_heartbeats, self._on_heartbeat),
                ("task_results", self._nats.subscribe_task_results, self._on_task_result),
            ]
            if hasattr(self._nats, "subscribe_worker_registrations"):
                subscription_calls.append((
                    "worker_registrations",
                    self._nats.subscribe_worker_registrations,
                    self._on_worker_event,
                ))
            else:
                subscriptions_ok = False
                logger.warning(
                    "MasterBrain: NATS bus missing subscribe_worker_registrations; "
                    "worker registration subject consumption not active"
                )

            if hasattr(self._nats, "subscribe_worker_shutdowns"):
                subscription_calls.append((
                    "worker_shutdowns",
                    self._nats.subscribe_worker_shutdowns,
                    self._on_worker_shutdown,
                ))
            else:
                subscriptions_ok = False
                logger.warning(
                    "MasterBrain: NATS bus missing subscribe_worker_shutdowns; "
                    "worker shutdown visibility not active"
                )

            if hasattr(self._nats, "subscribe_task_deadletters"):
                subscription_calls.append((
                    "task_deadletters",
                    self._nats.subscribe_task_deadletters,
                    self._on_deadletter,
                ))
            else:
                subscriptions_ok = False
                logger.warning(
                    "MasterBrain: NATS bus missing subscribe_task_deadletters; "
                    "dead-letter recovery not active"
                )

            # Legacy compatibility: still accept event bus wrappers if published.
            if hasattr(self._nats, "subscribe_events"):
                subscription_calls.append((
                    "worker_registered_event",
                    lambda cb: self._nats.subscribe_events("worker_registered", cb),
                    self._on_worker_event,
                ))
                subscription_calls.append((
                    "worker_shutdown_event",
                    lambda cb: self._nats.subscribe_events("worker_shutdown", cb),
                    self._on_worker_shutdown,
                ))

            for name, subscribe_fn, callback in subscription_calls:
                result = await subscribe_fn(callback)
                if not result.get("success"):
                    subscriptions_ok = False
                    logger.warning("MasterBrain: failed to subscribe to %s: %s", name, result)
        else:
            logger.warning("MasterBrain: NATS not connected, distributed lifecycle subscriptions inactive")

        await self._start_temporal_runtime()

        self._started = True
        logger.info(
            "MasterBrain: started (NATS=%s, Temporal client=%s, worker=%s)",
            self._nats.is_connected(),
            self._temporal_client is not None,
            self._temporal_worker_active(),
        )
        return {
            "success": True,
            "nats_connected": nats_connected,
            "distributed_ready": bool(nats_connected and subscriptions_ok),
            "temporal_client_connected": self._temporal_client is not None,
            "temporal_worker_active": self._temporal_worker_active(),
            "temporal_runtime_available": self.is_temporal_runtime_available(),
            "temporal_worker_state": self._temporal_worker_state,
            "persistence_degraded": self._persistence_degraded,
            "master_brain_enabled": master_brain_enabled(),
        }

    async def stop(self) -> dict:
        """Stop MasterBrain runtime integrations owned by this process."""
        await self._stop_temporal_runtime()
        self._started = False
        return {"success": True}

    async def _start_temporal_runtime(self) -> None:
        """Start the Temporal client + worker as a single lifecycle unit."""
        self._temporal_last_error = ""
        self._temporal_worker_state = "starting"
        try:
            from core.temporal_workflows import get_temporal_client, start_temporal_worker

            self._temporal_client = await get_temporal_client()
            if self._temporal_client is None:
                self._temporal_worker_state = "inactive"
                self._temporal_last_error = "temporal_client_unavailable"
                return

            self._temporal_worker = await start_temporal_worker(self._temporal_client)
            if self._temporal_worker is None:
                self._temporal_worker_state = "failed"
                self._temporal_last_error = "temporal_worker_not_started"
                return

            self._temporal_worker_task = asyncio.create_task(
                self._temporal_worker.run(),
                name="galaxy-temporal-worker",
            )
            self._temporal_worker_task.add_done_callback(self._on_temporal_worker_exit)
            self._temporal_worker_state = "running"
        except Exception as exc:
            self._temporal_worker_state = "failed"
            self._temporal_last_error = str(exc)
            logger.debug("MasterBrain: Temporal unavailable, workflow features disabled: %s", exc)

    async def _stop_temporal_runtime(self) -> None:
        """Stop the Temporal client + worker as a single lifecycle unit."""
        worker = self._temporal_worker
        worker_task = self._temporal_worker_task
        self._temporal_worker = None
        self._temporal_worker_task = None
        self._temporal_client = None
        self._temporal_worker_state = "inactive"

        if worker is not None and hasattr(worker, "shutdown"):
            try:
                shutdown = worker.shutdown
                if asyncio.iscoroutinefunction(shutdown):
                    await shutdown()
                else:
                    shutdown()
            except Exception as exc:
                logger.warning("MasterBrain: Temporal worker shutdown failed: %s", exc)

        if worker_task is not None and not worker_task.done():
            worker_task.cancel()
            try:
                await worker_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.warning("MasterBrain: Temporal worker task stop failed: %s", exc)

    # ── Task Dispatch ───────────────────────────────────────────────────────

    async def dispatch_task(self, raw_task: dict) -> dict:
        """Validate via ACL, select worker, publish to NATS.

        Returns ``{"success": True, "task_id": ...}`` or error dict.
        """
        # ACL validation
        validated = await self._acl.validate_task_dispatch(raw_task)
        if not validated["success"]:
            return validated

        task: TaskDispatchModel = validated["data"]
        trace_id = str(
            raw_task.get("trace_id", "")
            or (task.context.get("trace_id") if isinstance(task.context, dict) else "")
        )
        self._register_task_graph_node(task=task, trace_id=trace_id)
        self._transition_task_graph(
            task.task_id,
            "admitted",
            reason="master_brain_validated",
        )

        # Worker selection
        target = task.target_worker_id
        selection_details = {
            "selected_by": "explicit_target",
            "selection_score": None,
            "selection_reason": "",
            "selection_fallback_reason": "",
        }
        if not target:
            selection_details = self._select_worker_for_task(task)
            target = selection_details.get("worker_id", "")
            if not target:
                self._mark_task_terminal(
                    task.task_id,
                    status="dispatch_failed",
                    completion_state="dispatch_failed",
                    lifecycle_state="failed",
                    error="No available worker for device type: " + task.target_device_type,
                    trace_id=trace_id,
                    terminal_source="worker_selection",
                    selected_by=selection_details.get("selected_by", ""),
                    selection_fallback_reason=selection_details.get("selection_fallback_reason", ""),
                )
                return {
                    "success": False,
                    "error": "No available worker for device type: " + task.target_device_type,
                    "task_id": task.task_id,
                    "selected_by": selection_details.get("selected_by", ""),
                    "selection_fallback_reason": selection_details.get("selection_fallback_reason", ""),
                }
            task.target_worker_id = target

        self._transition_task_graph(
            task.task_id,
            "routed",
            reason=f"master_brain_selected:{target}",
        )
        wait_for_completion = bool(raw_task.get("wait_for_completion", True))
        timeout_s = self._resolve_task_timeout_s(raw_task, task)
        record = self._upsert_task_record(
            task_id=task.task_id,
            worker_id=target,
            trace_id=trace_id,
            status="dispatching",
            completion_state="dispatch_attempted",
            lifecycle_state="dispatching",
            success=False,
            error="",
            closure_complete=False,
            task_outcome_known=False,
            dispatch_attempted=True,
            dispatch_accepted=False,
            execution_started=False,
            result_received=False,
            distributed_dispatch=False,
            execution_path="dispatch_in_progress",
            nats_publish_state=None,
        )
        dispatched_at = datetime.now().isoformat()
        record["dispatched_at"] = dispatched_at
        record["timeout_s"] = timeout_s
        record["deadline_at"] = (datetime.fromisoformat(dispatched_at) + timedelta(seconds=timeout_s)).isoformat()
        self._ensure_task_waiter(task.task_id)
        self._persist_state()
        scaling = self._evaluate_scaling_state(task=task)
        self._update_task_record(
            task.task_id,
            selected_by=selection_details.get("selected_by", ""),
            selection_score=selection_details.get("selection_score"),
            selection_reason=selection_details.get("selection_reason", ""),
            selection_fallback_reason=selection_details.get("selection_fallback_reason", ""),
            transport_state="publishing",
            degraded_mode=False,
            scaling_state=scaling,
        )

        # Publish to NATS
        result = await self._nats.publish_task_dispatch(target, task)
        if result.get("noop"):
            failure = self._update_task_record(
                task.task_id,
                status="dispatch_failed",
                completion_state="dispatch_failed",
                lifecycle_state="failed",
                success=False,
                error="distributed_transport_unavailable:nats_noop_transport",
                closure_complete=True,
                task_outcome_known=True,
                distributed_dispatch=False,
                execution_path="distributed_unavailable",
                nats_publish_state=result,
                transport_state="noop_unavailable",
                degraded_mode=True,
                terminal_source="nats_noop_transport",
            )
            self._transition_task_graph(
                task.task_id,
                "degraded",
                reason="nats_noop_transport",
                error="distributed_transport_unavailable:nats_noop_transport",
            )
            return {
                "success": False,
                "error": "distributed_transport_unavailable:nats_noop_transport",
                "task_id": task.task_id,
                "worker_id": target,
                "distributed_dispatch": False,
                "execution_path": "distributed_unavailable",
                "nats_publish_state": result,
                "completion_state": failure.get("completion_state"),
                "closure_complete": failure.get("closure_complete"),
                "selected_by": selection_details.get("selected_by", ""),
                "transport_state": "noop_unavailable",
                "degraded_mode": True,
            }
        if not result.get("success"):
            failure = self._update_task_record(
                task.task_id,
                status="dispatch_failed",
                completion_state="dispatch_failed",
                lifecycle_state="failed",
                success=False,
                error=result.get("error", "nats_publish_failed"),
                closure_complete=True,
                task_outcome_known=True,
                distributed_dispatch=False,
                execution_path="distributed_unavailable",
                nats_publish_state=result,
                transport_state="publish_failed",
                degraded_mode=True,
                terminal_source="nats_publish_failed",
            )
            self._transition_task_graph(
                task.task_id,
                "failed",
                reason="nats_publish_failed",
                error=result.get("error", "nats_publish_failed"),
            )
            return {
                "success": False,
                "error": result.get("error", "nats_publish_failed"),
                "task_id": task.task_id,
                "worker_id": target,
                "distributed_dispatch": False,
                "execution_path": "distributed_unavailable",
                "nats_publish_state": result,
                "completion_state": failure.get("completion_state"),
                "closure_complete": failure.get("closure_complete"),
                "selected_by": selection_details.get("selected_by", ""),
                "transport_state": "publish_failed",
                "degraded_mode": True,
            }

        if result.get("success"):
            dispatch_snapshot = self._update_task_record(
                task.task_id,
                status=TaskStatus.DISPATCHED.value,
                completion_state="dispatch_accepted",
                lifecycle_state="waiting_remote",
                success=not wait_for_completion,
                error="",
                closure_complete=False,
                task_outcome_known=False,
                dispatch_accepted=True,
                distributed_dispatch=True,
                execution_path="nats_distributed",
                nats_publish_state=result,
                dispatch_accepted_at=datetime.now().isoformat(),
                transport_state="active",
                degraded_mode=False,
            )
            self._transition_task_graph(
                task.task_id,
                "dispatch",
                reason="nats_dispatch_accepted",
                transport_path="nats_distributed",
            )
            _try_emit_event("TASK_DISPATCHED", {
                "task_id": task.task_id,
                "worker_id": target,
                "task_type": task.task_type.value,
            })
            if not wait_for_completion:
                return {
                    "success": True,
                    "task_id": task.task_id,
                    "worker_id": target,
                    "trace_id": trace_id,
                    "distributed_dispatch": True,
                    "execution_path": "nats_distributed",
                    "dispatch_attempted": True,
                    "dispatch_accepted": True,
                    "execution_started": False,
                    "result_received": False,
                    "result_pending_closure": False,
                    "closure_complete": False,
                    "task_outcome_known": False,
                    "completion_state": dispatch_snapshot.get("completion_state"),
                    "status": dispatch_snapshot.get("status"),
                    "lifecycle_state": dispatch_snapshot.get("lifecycle_state"),
                    "nats_publish_state": result,
                    "selected_by": selection_details.get("selected_by", ""),
                    "selection_score": selection_details.get("selection_score"),
                    "transport_state": "active",
                    "scaling_state": scaling,
                }

        return await self.wait_for_task_result(task.task_id, timeout_s=timeout_s)

    async def handle_task_result(self, result: TaskResultModel) -> dict:
        """Process worker result, update task state, and complete waiting callers."""
        task_id = result.task_id
        status = result.status.value
        record = self._task_log.get(task_id)
        if record is None:
            record = self._upsert_task_record(
                task_id=task_id,
                worker_id=result.worker_id,
                trace_id=(result.metadata or {}).get("trace_id", ""),
                status=status,
                completion_state="result_received_pending_closure",
                lifecycle_state="waiting_remote",
                success=False,
                error="",
                closure_complete=False,
                task_outcome_known=False,
                dispatch_attempted=False,
                dispatch_accepted=False,
                execution_started=False,
                result_received=True,
                distributed_dispatch=True,
                execution_path="nats_distributed",
                nats_publish_state=None,
            )

        result_dump = result.model_dump(mode="json", exclude_none=True)
        if record.get("closure_complete") and record.get("completion_state") in {
            "dead_lettered",
            "execution_abandoned",
            "execution_timed_out",
        }:
            late = self._update_task_record(
                task_id,
                late_result=result_dump,
                late_result_at=datetime.now().isoformat(),
                late_result_reason=f"late_after_{record.get('completion_state')}",
            )
            self._transition_task_graph(
                task_id,
                "replayed",
                reason=f"late_result_ignored:{record.get('completion_state')}",
            )
            return {
                "success": False,
                "task_id": task_id,
                "status": late.get("status"),
                "error": late.get("error", ""),
                "completion_state": late.get("completion_state"),
                "late_result_ignored": True,
                "terminal_source": late.get("terminal_source", ""),
            }

        correlation_error = self._validate_result_correlation(record, result)
        if correlation_error:
            mismatch = self._update_task_record(
                task_id,
                error=correlation_error,
                correlation_valid=False,
                last_result_at=datetime.now().isoformat(),
            )
            return {
                "success": False,
                "task_id": task_id,
                "status": mismatch.get("status"),
                "error": correlation_error,
                "completion_state": mismatch.get("completion_state"),
            }

        result_id = (result.metadata or {}).get("result_id", "")
        seen_result_ids = record.setdefault("_result_ids", set())
        if result_id and result_id in seen_result_ids:
            logger.debug("MasterBrain: duplicate task result ignored task_id=%s result_id=%s", task_id, result_id)
            duplicate = self.get_task_status(task_id) or {"task_id": task_id}
            duplicate["duplicate_result_ignored"] = True
            return duplicate
        if result_id:
            seen_result_ids.add(result_id)

        completion_state, lifecycle_state, closure_complete, task_success = self._classify_task_result(result.status)
        updates = {
            "worker_id": result.worker_id or record.get("worker_id", ""),
            "trace_id": record.get("trace_id") or (result.metadata or {}).get("trace_id", ""),
            "status": status,
            "completion_state": completion_state,
            "lifecycle_state": lifecycle_state,
            "success": task_success if closure_complete else False,
            "error": self._extract_task_error(result_dump),
            "closure_complete": closure_complete,
            "task_outcome_known": closure_complete,
            "dispatch_accepted": record.get("dispatch_accepted", False) or status in (
                TaskStatus.DISPATCHED.value,
                TaskStatus.RUNNING.value,
                TaskStatus.SUCCESS.value,
                TaskStatus.FAILED.value,
                TaskStatus.TIMEOUT.value,
                TaskStatus.CANCELLED.value,
                TaskStatus.LSP_FAILED.value,
            ),
            "execution_started": record.get("execution_started", False) or status in (
                TaskStatus.RUNNING.value,
                TaskStatus.SUCCESS.value,
                TaskStatus.FAILED.value,
                TaskStatus.TIMEOUT.value,
                TaskStatus.CANCELLED.value,
                TaskStatus.LSP_FAILED.value,
            ),
            "result_received": True,
            "result_pending_closure": not closure_complete,
            "last_result_at": datetime.now().isoformat(),
            "last_result_id": result_id,
            "result": result_dump,
            "correlation_valid": True,
        }
        if status == TaskStatus.DISPATCHED.value:
            updates.setdefault("dispatch_accepted_at", datetime.now().isoformat())
        if status == TaskStatus.RUNNING.value:
            updates["started_at"] = (
                self._timestamp_to_iso(result.started_at)
                or record.get("started_at")
                or datetime.now().isoformat()
            )
        if closure_complete:
            updates["completed_at"] = self._timestamp_to_iso(result.completed_at) or datetime.now().isoformat()
        snapshot = self._update_task_record(task_id, **updates)
        self._apply_task_graph_result(task_id, status=status, completion_state=snapshot.get("completion_state", ""))

        _try_emit_event("TASK_RESULT_RECEIVED", {
            "task_id": task_id,
            "worker_id": result.worker_id,
            "status": status,
        })

        if closure_complete:
            waiter = self._task_waiters.get(task_id)
            if waiter is not None and not waiter.done():
                waiter.set_result(snapshot)

        logger.info("MasterBrain: task %s result status=%s completion=%s", task_id, status, snapshot.get("completion_state"))
        return {
            "success": closure_complete and task_success,
            "task_id": task_id,
            "status": status,
            "completion_state": snapshot.get("completion_state"),
            "closure_complete": snapshot.get("closure_complete"),
        }

    # ── Workflow launch ─────────────────────────────────────────────────────

    async def execute_distributed_task(self, raw_task: dict) -> dict:
        """Dispatch via Temporal when the local workflow runtime is truly active."""
        if not self._should_use_temporal_workflow(raw_task):
            return await self.dispatch_task(raw_task)

        task_id = str(raw_task.get("task_id", "")).strip()
        worker_id = str(raw_task.get("target_worker_id", "")).strip()
        trace_id = str(raw_task.get("trace_id", "")).strip()
        try:
            validated = TaskDispatchModel.model_validate(raw_task)
            self._register_task_graph_node(task=validated, trace_id=trace_id)
        except Exception:
            pass
        self._transition_task_graph(task_id, "admitted", reason="temporal_workflow_requested")
        self._upsert_task_record(
            task_id=task_id,
            worker_id=worker_id,
            trace_id=trace_id,
            status=TaskStatus.QUEUED.value,
            completion_state="workflow_accepted",
            lifecycle_state="workflow_pending",
            success=False,
            error="",
            closure_complete=False,
            task_outcome_known=False,
            dispatch_attempted=True,
            dispatch_accepted=False,
            execution_started=False,
            result_received=False,
            distributed_dispatch=True,
            execution_path="temporal_workflow",
            nats_publish_state=None,
        )
        self._update_task_record(
            task_id,
            transport_state="temporal_runtime" if self._temporal_worker_active() else "temporal_unavailable",
            degraded_mode=not self._temporal_worker_active(),
        )
        self._ensure_task_waiter(task_id)

        started = await self.start_workflow(
            "code_execution",
            raw_task,
            wait_for_completion=True,
        )
        if not started.get("success"):
            failure = self._update_task_record(
                task_id,
                status="dispatch_failed",
                completion_state="dispatch_failed",
                lifecycle_state="failed",
                success=False,
                error=started.get("error", "temporal_workflow_start_failed"),
                closure_complete=True,
                task_outcome_known=True,
                workflow_id=started.get("workflow_id", ""),
                workflow_run_id=started.get("run_id", ""),
                temporal_workflow_type="code_execution",
                temporal_worker_active=self._temporal_worker_active(),
            )
            return {
                "success": False,
                "error": started.get("error", "temporal_workflow_start_failed"),
                "task_id": task_id,
                "worker_id": worker_id,
                "distributed_dispatch": False,
                "execution_path": "temporal_unavailable",
                "temporal_workflow_type": "code_execution",
                "temporal_worker_active": self._temporal_worker_active(),
                "completion_state": failure.get("completion_state"),
                "closure_complete": failure.get("closure_complete"),
            }

        self._update_task_record(
            task_id,
            workflow_id=started.get("workflow_id", ""),
            workflow_run_id=started.get("run_id", ""),
            temporal_workflow_type="code_execution",
            temporal_worker_active=self._temporal_worker_active(),
        )
        self._transition_task_graph(
            task_id,
            "dispatch",
            reason="temporal_workflow_started",
            transport_path="temporal_workflow",
        )
        await asyncio.sleep(0)
        snapshot = self.get_task_status(task_id)
        if snapshot is None or not snapshot.get("closure_complete"):
            snapshot = self._finalize_temporal_workflow_result(
                task_id=task_id,
                worker_id=worker_id,
                trace_id=trace_id,
                workflow_result=started.get("workflow_result", {}),
                workflow_id=started.get("workflow_id", ""),
                workflow_run_id=started.get("run_id", ""),
            )

        return {
            **snapshot,
            "workflow_id": started.get("workflow_id", ""),
            "run_id": started.get("run_id", ""),
            "distributed_dispatch": True,
            "execution_path": "temporal_workflow",
            "temporal_workflow_type": "code_execution",
            "temporal_worker_active": self._temporal_worker_active(),
        }

    async def start_workflow(
        self,
        workflow_type: str,
        params: dict,
        *,
        wait_for_completion: bool = False,
    ) -> dict:
        """Launch a Temporal workflow.

        Supported workflow types: ``code_execution``, ``multi_device``, ``tool_discovery``.
        """
        if not self.is_temporal_runtime_available():
            return {
                "success": False,
                "error": "Temporal runtime not active",
                "temporal_client_connected": self._temporal_client is not None,
                "temporal_worker_active": self._temporal_worker_active(),
            }

        _workflow_map = {
            "code_execution": "CodeExecutionWorkflow",
            "multi_device": "MultiDeviceTaskWorkflow",
            "tool_discovery": "ToolDiscoveryWorkflow",
        }

        wf_name = _workflow_map.get(workflow_type)
        if not wf_name:
            return {"success": False, "error": f"Unknown workflow type: {workflow_type}"}

        try:
            run_id = str(uuid.uuid4())
            handle = await self._temporal_client.start_workflow(
                wf_name,
                params,
                id=f"galaxy-{workflow_type}-{run_id}",
                task_queue="galaxy-tasks",
            )
            workflow_id = getattr(handle, "id", f"galaxy-{workflow_type}-{run_id}")
            if not isinstance(workflow_id, str) or not workflow_id:
                workflow_id = f"galaxy-{workflow_type}-{run_id}"
            workflow_run_id = run_id
            for candidate in (
                getattr(handle, "result_run_id", None),
                getattr(handle, "first_execution_run_id", None),
            ):
                if isinstance(candidate, str) and candidate:
                    workflow_run_id = candidate
                    break
            logger.info(
                "MasterBrain: started workflow %s (workflow_id=%s, run=%s)",
                wf_name,
                workflow_id,
                workflow_run_id,
            )
            result = {
                "success": True,
                "workflow_id": workflow_id,
                "run_id": workflow_run_id,
                "temporal_worker_active": self._temporal_worker_active(),
            }
            if wait_for_completion:
                result["workflow_result"] = await handle.result()
            return result
        except Exception as exc:
            logger.error(f"MasterBrain: workflow start failed — {exc}")
            return {"success": False, "error": str(exc)}

    # ── Worker topology ─────────────────────────────────────────────────────

    async def register_worker(self, registration: WorkerRegistrationModel) -> dict:
        """Register a new worker in the topology."""
        wid = registration.worker_id
        self._workers[wid] = {
            "worker_id": wid,
            "hostname": registration.hostname,
            "device_type": registration.device_type,
            "platform": registration.platform,
            "capabilities": [c.model_dump() for c in registration.capabilities],
            "supported_languages": [l.value for l in registration.supported_languages],
            "has_docker": registration.has_docker,
            "has_gpu": registration.has_gpu,
            "memory_total_mb": registration.memory_total_mb,
            "cpu_cores": registration.cpu_cores,
            "status": "idle",
            "last_heartbeat": time.time(),
            "registered_at": datetime.now().isoformat(),
            "force_offline": False,
        }
        self._persist_state()
        _try_emit_event("WORKER_REGISTERED", {"worker_id": wid, "device_type": registration.device_type})
        logger.info(f"MasterBrain: worker registered — {wid} ({registration.device_type})")
        return {"success": True, "worker_id": wid}

    async def handle_worker_shutdown(self, shutdown: WorkerShutdownModel) -> dict:
        """Reflect an explicit worker shutdown into topology state."""
        wid = shutdown.worker_id
        now_iso = datetime.now().isoformat()
        existing = self._workers.get(wid, {})
        entry = dict(existing)
        entry.setdefault("worker_id", wid)
        entry.setdefault("hostname", "")
        entry.setdefault("device_type", "unknown")
        entry.setdefault("platform", "")
        entry.setdefault("capabilities", [])
        entry.setdefault("supported_languages", [])
        entry.setdefault("has_docker", False)
        entry.setdefault("has_gpu", False)
        entry.setdefault("memory_total_mb", 0)
        entry.setdefault("cpu_cores", 0)
        entry.setdefault("last_heartbeat", 0.0)
        entry.setdefault("registered_at", now_iso)
        entry.update({
            "status": "offline",
            "force_offline": True,
            "shutdown_reason": shutdown.reason,
            "shutdown_at": now_iso,
            "drain_timeout_s": shutdown.drain_timeout_s,
        })
        self._workers[wid] = entry
        affected_tasks = self._mark_inflight_tasks_for_worker(
            wid,
            error=f"worker_shutdown:{shutdown.reason or 'unspecified'}",
        )
        self._persist_state()
        _try_emit_event(
            "WORKER_SHUTDOWN",
            {"worker_id": wid, "reason": shutdown.reason, "drain_timeout_s": shutdown.drain_timeout_s},
        )
        logger.info("MasterBrain: worker shutdown — %s (reason=%s)", wid, shutdown.reason)
        return {"success": True, "worker_id": wid, "status": "offline", "affected_tasks": affected_tasks}

    async def handle_heartbeat(self, heartbeat: WorkerHeartbeatModel) -> dict:
        """Update worker status from heartbeat."""
        wid = heartbeat.worker_id
        if wid not in self._workers:
            return {"success": False, "error": f"Unknown worker: {wid}"}

        self._workers[wid].update({
            "status": heartbeat.status.value,
            "last_heartbeat": time.time(),
            "active_tasks": heartbeat.active_tasks,
            "cpu_usage_percent": heartbeat.cpu_usage_percent,
            "memory_usage_percent": heartbeat.memory_usage_percent,
            "force_offline": False,
        })
        self._persist_state()
        return {"success": True}

    def get_worker_topology(self) -> dict:
        """Return current worker topology with liveness info."""
        now = time.time()
        topology = {}
        state_changed = False
        for wid, info in self._workers.items():
            alive = (now - info.get("last_heartbeat", 0)) < _HEARTBEAT_TIMEOUT_S
            if info.get("force_offline"):
                alive = False
            if not alive and info.get("status") not in ("dead", "offline"):
                info["status"] = "dead"
                info["dead_at"] = datetime.now().isoformat()
                self._mark_inflight_tasks_for_worker(wid, error=f"worker_lost:{wid}")
                state_changed = True
                _try_emit_event("WORKER_DEAD", {"worker_id": wid})
            topology[wid] = {**info, "alive": alive}
        if state_changed:
            self._persist_state()
        return topology

    # ── Worker selection (load balancing) ───────────────────────────────────

    def _select_worker(self, device_type: str) -> Optional[str]:
        """Select least-loaded alive worker matching device_type."""
        now = time.time()
        candidates = []
        for wid, info in self._workers.items():
            alive = (now - info.get("last_heartbeat", 0)) < _HEARTBEAT_TIMEOUT_S
            if not alive:
                continue
            if info.get("device_type", "") == device_type or device_type == "unknown":
                candidates.append((wid, info.get("active_tasks", 0)))

        if not candidates:
            return None

        # Sort by load (fewest active tasks first)
        candidates.sort(key=lambda x: x[1])
        return candidates[0][0]

    async def wait_for_task_result(self, task_id: str, timeout_s: Optional[float] = None) -> dict:
        """Wait for a distributed task to reach a terminal state."""
        self._recover_incomplete_state(task_id=task_id)
        snapshot = self.get_task_status(task_id)
        if not snapshot:
            return {"success": False, "error": "unknown_task_id", "task_id": task_id}
        if snapshot.get("closure_complete"):
            return snapshot

        waiter = self._ensure_task_waiter(task_id)
        try:
            # shield() prevents wait_for() from cancelling the shared waiter on
            # timeout, so the distributed task can continue and later callers
            # can still observe the eventual result even after one timeout.
            result = await asyncio.wait_for(asyncio.shield(waiter), timeout=timeout_s)
            return result if isinstance(result, dict) else self.get_task_status(task_id)
        except asyncio.TimeoutError:
            if self._task_deadline_expired(self._task_log.get(task_id, {})):
                timed_out = self._mark_task_terminal(
                    task_id,
                    status=TaskStatus.TIMEOUT.value,
                    completion_state="execution_timed_out",
                    lifecycle_state="timed_out",
                    error=f"task_result_timeout:{timeout_s}",
                )
            else:
                timed_out = self._update_task_record(
                    task_id,
                    success=False,
                    error=f"task_result_timeout:{timeout_s}",
                    completion_state="result_pending_timeout",
                    result_pending_closure=True,
                    closure_complete=False,
                    task_outcome_known=False,
                )
            timed_out["error"] = f"task_result_timeout:{timeout_s}"
            return timed_out

    def get_task_status(self, task_id: str) -> Optional[dict]:
        """Return the current distributed execution snapshot for *task_id*."""
        self._recover_incomplete_state(task_id=task_id)
        record = self._task_log.get(task_id)
        if record is None:
            return None
        return self._public_task_record(record)

    # ── NATS callbacks ──────────────────────────────────────────────────────

    async def _on_heartbeat(self, data: dict) -> None:
        try:
            hb = WorkerHeartbeatModel.model_validate(data)
            await self.handle_heartbeat(hb)
        except Exception as exc:
            logger.debug(f"MasterBrain: heartbeat parse error — {exc}")

    async def _on_task_result(self, data: dict) -> None:
        try:
            result_validated = await self._acl.validate_task_result(data)
            if result_validated["success"]:
                await self.handle_task_result(result_validated["data"])
        except Exception as exc:
            logger.error(f"MasterBrain: task result handling error — {exc}")

    async def _on_worker_event(self, data: dict) -> None:
        payload = self._extract_lifecycle_payload(
            data,
            payload_key="worker_register",
            event_type="worker_register",
            direct_required_key="device_type",
        )
        if payload is None:
            logger.warning("MasterBrain: unrecognized worker registration payload: %s", data)
            return
        try:
            reg = WorkerRegistrationModel.model_validate(payload)
            await self.register_worker(reg)
        except Exception as exc:
            logger.warning("MasterBrain: worker registration parse error — %s", exc)

    async def _on_worker_shutdown(self, data: dict) -> None:
        payload = self._extract_lifecycle_payload(
            data,
            payload_key="worker_shutdown",
            event_type="worker_shutdown",
            direct_required_key="reason",
        )
        if payload is None:
            logger.warning("MasterBrain: unrecognized worker shutdown payload: %s", data)
            return
        try:
            shutdown = WorkerShutdownModel.model_validate(payload)
            await self.handle_worker_shutdown(shutdown)
        except Exception as exc:
            logger.warning("MasterBrain: worker shutdown parse error — %s", exc)

    async def _on_deadletter(self, data: dict) -> None:
        payload = self._extract_deadletter_payload(data)
        if payload is None:
            logger.warning("MasterBrain: unrecognized dead-letter payload: %s", data)
            return
        task_id = str(payload.get("task_id") or "")
        if not task_id:
            logger.warning("MasterBrain: dead-letter payload missing task_id: %s", data)
            return

        original = payload.get("original") if isinstance(payload.get("original"), dict) else {}
        worker_id = (
            payload.get("worker_id")
            or original.get("target_worker_id")
            or original.get("target_device_id")
            or ""
        )
        trace_id = (
            payload.get("trace_id")
            or (original.get("context") or {}).get("trace_id", "")
            or original.get("trace_id", "")
        )
        reason = str(payload.get("reason") or "dead_lettered")
        snapshot = self._mark_task_terminal(
            task_id,
            status=TaskStatus.TIMEOUT.value if reason == "timeout" else TaskStatus.FAILED.value,
            completion_state="dead_lettered",
            lifecycle_state="dead_lettered",
            error=f"dead_letter:{reason}",
            worker_id=worker_id,
            trace_id=trace_id,
            dead_lettered=True,
            dead_letter_reason=reason,
            dead_letter_payload=payload,
            dead_lettered_at=datetime.now().isoformat(),
            distributed_dispatch=True,
            terminal_source="deadletter",
        )
        logger.warning(
            "MasterBrain: task %s marked dead-lettered (reason=%s state=%s)",
            task_id,
            reason,
            snapshot.get("completion_state"),
        )

    @staticmethod
    def _extract_lifecycle_payload(
        data: dict,
        *,
        payload_key: str,
        event_type: str,
        direct_required_key: str,
    ) -> Optional[dict]:
        """Extract worker lifecycle payload from direct or wrapped envelopes."""
        if not isinstance(data, dict):
            return None

        if MasterBrain._has_required_lifecycle_fields(data, direct_required_key=direct_required_key):
            return data
        if isinstance(data.get(payload_key), dict):
            nested = data[payload_key]
            if MasterBrain._has_required_lifecycle_fields(nested, direct_required_key=direct_required_key):
                return nested

        payload = data.get("payload")
        if isinstance(payload, dict):
            if MasterBrain._has_required_lifecycle_fields(payload, direct_required_key=direct_required_key):
                return payload
            if isinstance(payload.get(payload_key), dict):
                nested = payload[payload_key]
                if MasterBrain._has_required_lifecycle_fields(nested, direct_required_key=direct_required_key):
                    return nested

        if data.get("type") == event_type and isinstance(data.get(payload_key), dict):
            nested = data[payload_key]
            if MasterBrain._has_required_lifecycle_fields(nested, direct_required_key=direct_required_key):
                return nested
        return None

    @staticmethod
    def _extract_deadletter_payload(data: dict) -> Optional[dict]:
        """Extract task dead-letter payload from direct or wrapped envelopes."""
        if not isinstance(data, dict):
            return None
        if data.get("task_id"):
            return data
        payload = data.get("payload")
        if isinstance(payload, dict) and payload.get("task_id"):
            return payload
        deadletter = data.get("deadletter")
        if isinstance(deadletter, dict) and deadletter.get("task_id"):
            return deadletter
        return None

    @staticmethod
    def _has_required_lifecycle_fields(data: dict, *, direct_required_key: str) -> bool:
        """Validate minimal worker lifecycle payload required fields."""
        worker_id = data.get("worker_id")
        required = data.get(direct_required_key)
        return bool(worker_id) and required not in (None, "")

    # ── Health / Status (constraint C8) ─────────────────────────────────────

    def get_status(self) -> dict:
        """Return MasterBrain status matching GalaxyCore.get_status() pattern."""
        topology = self.get_worker_topology()
        alive_count = sum(1 for w in topology.values() if w.get("alive"))
        nats_stats = self._nats.get_stats() if hasattr(self._nats, "get_stats") else {}
        return {
            "started": self._started,
            "master_brain_enabled": master_brain_enabled(),
            "nats_connected": self._nats.is_connected(),
            "nats_stats": nats_stats,
            "temporal_connected": self.is_temporal_runtime_available(),
            "temporal_client_connected": self._temporal_client is not None,
            "temporal_worker_active": self._temporal_worker_active(),
            "temporal_worker_state": self._temporal_worker_state,
            "temporal_runtime_available": self.is_temporal_runtime_available(),
            "temporal_last_error": self._temporal_last_error,
            "persistence_degraded": self._persistence_degraded,
            "persistence_last_error": self._persistence_last_error,
            "scaling": dict(self._last_scaling_decision),
            "workers_total": len(self._workers),
            "workers_alive": alive_count,
            "tasks_tracked": len(self._task_log),
            "timestamp": datetime.now().isoformat(),
        }

    def _ensure_task_waiter(self, task_id: str) -> asyncio.Future:
        waiter = self._task_waiters.get(task_id)
        if waiter is None or waiter.cancelled():
            waiter = asyncio.get_running_loop().create_future()
            self._task_waiters[task_id] = waiter
        return waiter

    def _temporal_worker_active(self) -> bool:
        task = self._temporal_worker_task
        return bool(task is not None and not task.done())

    def is_temporal_runtime_available(self) -> bool:
        return self._temporal_client is not None and self._temporal_worker_active()

    def _on_temporal_worker_exit(self, task: asyncio.Task[Any]) -> None:
        if self._temporal_worker_task is task:
            self._temporal_worker_task = None
        self._temporal_worker = None
        if task.cancelled():
            self._temporal_worker_state = "stopped"
            logger.info("MasterBrain: Temporal worker stopped")
            return
        exc = task.exception()
        if exc is None:
            self._temporal_worker_state = "stopped"
            self._temporal_last_error = "temporal_worker_stopped"
            logger.warning("MasterBrain: Temporal worker exited")
            return
        self._temporal_worker_state = "failed"
        self._temporal_last_error = str(exc)
        logger.error("MasterBrain: Temporal worker exited with error: %s", exc)

    def _should_use_temporal_workflow(self, raw_task: dict) -> bool:
        return (
            self.is_temporal_runtime_available()
            and bool(raw_task.get("wait_for_completion", True))
            and bool(raw_task.get("task_id"))
            and bool(raw_task.get("target_worker_id"))
        )

    def _register_task_graph_node(self, *, task: TaskDispatchModel, trace_id: str) -> None:
        try:
            from core.task_graph_runtime import WorkflowContributorKind, get_task_graph_runtime

            runtime = get_task_graph_runtime()
            node = runtime.register_node_raw(
                task.task_id,
                tool_name=task.task_type.value,
                trace_id=trace_id,
                device_id=task.target_worker_id,
                contributor=WorkflowContributorKind.MASTER_BRAIN,
                metadata={
                    "execution_owner": "master_brain",
                    "target_device_type": task.target_device_type,
                },
            )
            if task.target_worker_id:
                node.device_id = task.target_worker_id
        except Exception as exc:
            logger.debug("MasterBrain: TaskGraph node registration skipped for %s: %s", task.task_id, exc)

    def _transition_task_graph(
        self,
        task_id: str,
        graph_state: str,
        *,
        reason: str,
        error: str = "",
        transport_path: str = "",
    ) -> None:
        try:
            from core.task_graph_runtime import GraphNodeState, WorkflowContributorKind, get_task_graph_runtime

            runtime = get_task_graph_runtime()
            runtime.transition(
                task_id,
                GraphNodeState(graph_state),
                reason=reason,
                error=error,
                transport_path=transport_path,
                contributor=WorkflowContributorKind.MASTER_BRAIN,
            )
        except Exception as exc:
            logger.debug("MasterBrain: TaskGraph transition skipped task_id=%s state=%s: %s", task_id, graph_state, exc)

    def _apply_task_graph_result(self, task_id: str, *, status: str, completion_state: str) -> None:
        if status == TaskStatus.DISPATCHED.value:
            self._transition_task_graph(task_id, "dispatch", reason="worker_acknowledged_dispatch")
            return
        if status == TaskStatus.RUNNING.value:
            self._transition_task_graph(task_id, "running", reason="worker_started_execution")
            return

        self._transition_task_graph(task_id, "result", reason=f"worker_reported:{status}")
        terminal_state = "completed" if status == TaskStatus.SUCCESS.value else "failed"
        if completion_state == "dead_lettered":
            terminal_state = "degraded"
        elif status == TaskStatus.CANCELLED.value:
            terminal_state = "cancelled"
        self._transition_task_graph(
            task_id,
            terminal_state,
            reason=f"terminal:{completion_state or status}",
        )

    def _select_worker_for_task(self, task: TaskDispatchModel) -> dict:
        """Select the best alive worker for *task* with truthful fallback metadata."""
        candidates: list[Any] = []
        fallback_candidates: list[tuple[str, int]] = []
        now = time.time()

        for wid, info in self._workers.items():
            alive = (now - info.get("last_heartbeat", 0)) < _HEARTBEAT_TIMEOUT_S
            if info.get("force_offline") or not alive:
                continue
            worker_device_type = info.get("device_type", "")
            if worker_device_type != task.target_device_type and task.target_device_type != "unknown":
                continue
            fallback_candidates.append((wid, int(info.get("active_tasks", 0) or 0)))
            try:
                from core.control_plane.smart_scheduler import DeviceScoreInput, DeviceStatus, SandboxLevel

                platform_name = str(info.get("platform", "")).lower()
                device_type = str(worker_device_type).lower()
                candidates.append(DeviceScoreInput(
                    device_id=wid,
                    status=DeviceStatus.DRAINING if info.get("status") == "draining" else DeviceStatus.ONLINE,
                    ping_latency_ms=float(info.get("heartbeat_latency_ms", 0.0) or 0.0),
                    load_pct=min(float(info.get("memory_usage_percent", 0.0) or 0.0), 100.0),
                    sandbox_level=(
                        SandboxLevel.STANDARD
                        if "android" in (platform_name, device_type)
                        else SandboxLevel.NONE
                    ),
                    capabilities=[str(c.get("name", c)) for c in info.get("capabilities", [])],
                    health_score=max(
                        0.0,
                        100.0 - float(info.get("cpu_usage_percent", 0.0) or 0.0),
                    ),
                    metadata={"worker_info": dict(info)},
                ))
            except Exception as exc:
                logger.debug("MasterBrain: candidate scoring input skipped for %s: %s", wid, exc)

        try:
            from core.control_plane._globals import get_scoring_engine

            best = get_scoring_engine().select_best_device(candidates, required_capabilities=None)
            if best is not None:
                return {
                    "worker_id": best.device_id,
                    "selected_by": "device_scoring_engine",
                    "selection_score": best.total,
                    "selection_reason": "highest_eligible_score",
                    "selection_fallback_reason": "",
                }
        except Exception as exc:
            logger.debug("MasterBrain: DeviceScoringEngine unavailable, falling back to load ordering: %s", exc)

        if not fallback_candidates:
            return {
                "worker_id": "",
                "selected_by": "fallback_load_order",
                "selection_score": None,
                "selection_reason": "",
                "selection_fallback_reason": "no_alive_worker_candidates",
            }

        fallback_candidates.sort(key=lambda item: (item[1], item[0]))
        worker_id, active_tasks = fallback_candidates[0]
        return {
            "worker_id": worker_id,
            "selected_by": "fallback_load_order",
            "selection_score": float(active_tasks),
            "selection_reason": "least_active_tasks",
            "selection_fallback_reason": "device_scoring_engine_unavailable_or_ineligible",
        }

    def _estimate_task_complexity(self, task: TaskDispatchModel) -> float:
        payload_weight = 0.2
        if task.code_payload is not None:
            payload_weight = 0.9
        elif task.mcp_payload is not None:
            payload_weight = 0.7
        elif task.shell_payload is not None:
            payload_weight = 0.6
        elif task.device_payload is not None:
            payload_weight = 0.5
        retry_weight = min(float(task.max_retries or 0) * 0.1, 0.3)
        timeout_weight = min(float(task.timeout_ms or 0) / 120000.0, 0.3)
        return min(1.0, payload_weight + retry_weight + timeout_weight)

    def _estimate_worker_load(self) -> float:
        topology = self.get_worker_topology()
        alive_workers = [info for info in topology.values() if info.get("alive")]
        if not alive_workers:
            return 0.0
        busy_workers = sum(1 for info in alive_workers if int(info.get("active_tasks", 0) or 0) > 0)
        return busy_workers / max(len(alive_workers), 1)

    def _evaluate_scaling_state(self, *, task: TaskDispatchModel) -> dict:
        try:
            from core.control_plane.swarm_scaler import SwarmScaler

            topology = self.get_worker_topology()
            alive_workers = [wid for wid, info in topology.items() if info.get("alive")]
            scaler = SwarmScaler()
            complexity = self._estimate_task_complexity(task)
            load = self._estimate_worker_load()
            action = scaler.evaluate(
                "master_brain",
                current_worker_count=len(alive_workers),
                complexity=complexity,
                load=load,
            )
            decision = {
                "action": action,
                "reason": "runtime_dispatch_evaluation",
                "trigger": "dispatch_task",
                "workers_alive": len(alive_workers),
                "complexity": complexity,
                "load": load,
            }
            self._last_scaling_decision = decision
            return decision
        except Exception as exc:
            decision = {
                "action": "no_change",
                "reason": f"scaler_unavailable:{exc}",
                "trigger": "dispatch_task",
            }
            self._last_scaling_decision = decision
            return decision

    def _finalize_temporal_workflow_result(
        self,
        *,
        task_id: str,
        worker_id: str,
        trace_id: str,
        workflow_result: dict,
        workflow_id: str,
        workflow_run_id: str,
    ) -> dict:
        task_data = workflow_result.get("data", {}) if isinstance(workflow_result, dict) else {}
        status = self._infer_temporal_workflow_status(workflow_result)
        try:
            status_enum = status if isinstance(status, TaskStatus) else TaskStatus(str(status))
        except ValueError:
            logger.warning("MasterBrain: invalid Temporal workflow status %r for task %s", status, task_id)
            status_enum = TaskStatus.FAILED
        completion_state, lifecycle_state, closure_complete, task_success = self._classify_task_result(status_enum)
        snapshot = self._update_task_record(
            task_id,
            worker_id=worker_id,
            trace_id=trace_id,
            status=status_enum.value,
            completion_state=completion_state,
            lifecycle_state=lifecycle_state,
            success=task_success if closure_complete else False,
            error=self._extract_temporal_workflow_error(workflow_result),
            closure_complete=closure_complete,
            task_outcome_known=closure_complete,
            dispatch_accepted=bool(workflow_result.get("success")),
            execution_started=bool(workflow_result.get("success")),
            result_received=bool(workflow_result),
            result_pending_closure=not closure_complete,
            result=task_data or workflow_result,
            workflow_id=workflow_id,
            workflow_run_id=workflow_run_id,
            temporal_workflow_type="code_execution",
            temporal_worker_active=self._temporal_worker_active(),
            distributed_dispatch=True,
            execution_path="temporal_workflow",
            completed_at=datetime.now().isoformat() if closure_complete else None,
            transport_state="temporal_runtime" if self._temporal_worker_active() else "temporal_unavailable",
        )
        self._apply_task_graph_result(
            task_id,
            status=status_enum.value,
            completion_state=snapshot.get("completion_state", ""),
        )
        waiter = self._task_waiters.get(task_id)
        if waiter is not None and not waiter.done() and closure_complete:
            waiter.set_result(snapshot)
        return snapshot

    @staticmethod
    def _infer_temporal_workflow_status(workflow_result: dict) -> str:
        if not isinstance(workflow_result, dict):
            return TaskStatus.FAILED.value
        task_data = workflow_result.get("data")
        if isinstance(task_data, dict) and task_data.get("status"):
            return str(task_data.get("status"))
        if workflow_result.get("error") == "timeout":
            return TaskStatus.TIMEOUT.value
        if workflow_result.get("success"):
            return TaskStatus.SUCCESS.value
        return TaskStatus.FAILED.value

    @staticmethod
    def _extract_temporal_workflow_error(workflow_result: dict) -> str:
        if not isinstance(workflow_result, dict):
            return "temporal_workflow_failed"
        if workflow_result.get("error"):
            return str(workflow_result.get("error"))
        test_result = workflow_result.get("test_result")
        if isinstance(test_result, dict) and test_result.get("error"):
            return str(test_result.get("error"))
        return ""

    def _upsert_task_record(
        self,
        *,
        task_id: str,
        worker_id: str,
        trace_id: str,
        status: str,
        completion_state: str,
        lifecycle_state: str,
        success: bool,
        error: str,
        closure_complete: bool,
        task_outcome_known: bool,
        dispatch_attempted: bool,
        dispatch_accepted: bool,
        execution_started: bool,
        result_received: bool,
        distributed_dispatch: bool,
        execution_path: str,
        nats_publish_state: Optional[dict],
    ) -> dict:
        record = self._task_log.setdefault(task_id, self._default_task_record(task_id))
        if dispatch_attempted and status == "dispatching":
            record["_result_ids"] = set()
            for reset_key in (
                "started_at",
                "completed_at",
                "result",
                "last_result_at",
                "last_result_id",
                "late_result",
                "late_result_at",
                "late_result_reason",
                "dead_letter_payload",
                "dead_lettered_at",
            ):
                record.pop(reset_key, None)
            record["dead_lettered"] = False
            record["dead_letter_reason"] = ""
            record["terminal_source"] = ""
        record.update({
            "task_id": task_id,
            "worker_id": worker_id,
            "trace_id": trace_id,
            "status": status,
            "success": success,
            "error": error,
            "distributed_dispatch": distributed_dispatch,
            "execution_path": execution_path,
            "dispatch_attempted": dispatch_attempted,
            "dispatch_accepted": dispatch_accepted,
            "execution_started": execution_started,
            "result_received": result_received,
            "result_pending_closure": False,
            "closure_complete": closure_complete,
            "task_outcome_known": task_outcome_known,
            "completion_state": completion_state,
            "lifecycle_state": lifecycle_state,
            "nats_publish_state": nats_publish_state,
            "correlation_valid": True,
        })
        record.setdefault("_result_ids", set())
        self._refresh_task_derived_fields(record)
        self._persist_state()
        return record

    def _update_task_record(self, task_id: str, **updates: Any) -> dict:
        record = self._task_log.setdefault(task_id, self._default_task_record(task_id))
        record.update({k: v for k, v in updates.items() if v is not None})
        self._refresh_task_derived_fields(record)
        self._persist_state()
        return self._public_task_record(record)

    @staticmethod
    def _default_task_record(task_id: str) -> dict:
        return {
            "task_id": task_id,
            "worker_id": "",
            "trace_id": "",
            "status": "",
            "success": False,
            "error": "",
            "distributed_dispatch": False,
            "execution_path": "",
            "dispatch_attempted": False,
            "dispatch_accepted": False,
            "execution_started": False,
            "result_received": False,
            "result_pending_closure": False,
            "closure_complete": False,
            "task_outcome_known": False,
            "completion_state": "",
            "lifecycle_state": "",
            "nats_publish_state": None,
            "correlation_valid": True,
            "dead_lettered": False,
            "dead_letter_reason": "",
            "selected_by": "",
            "selection_score": None,
            "selection_reason": "",
            "selection_fallback_reason": "",
            "transport_state": "",
            "degraded_mode": False,
            "terminal_source": "",
            "timeout_s": 0.0,
            "deadline_at": "",
            "_result_ids": set(),
        }

    @staticmethod
    def _derive_result_pending_closure(record: dict) -> bool:
        return bool(record.get("result_received")) and not bool(record.get("closure_complete"))

    @classmethod
    def _refresh_task_derived_fields(cls, record: dict) -> None:
        record["result_pending_closure"] = cls._derive_result_pending_closure(record)

    @staticmethod
    def _resolve_task_timeout_s(raw_task: dict, task: TaskDispatchModel) -> float:
        raw_timeout = raw_task.get("timeout")
        if isinstance(raw_timeout, (int, float)) and raw_timeout > 0:
            return float(raw_timeout)
        timeout_ms = getattr(task, "timeout_ms", 0) or 0
        return max(float(timeout_ms) / 1000.0, 0.1)

    @staticmethod
    def _timestamp_to_iso(timestamp: Any) -> str:
        if timestamp is None:
            return ""
        seconds = getattr(timestamp, "seconds", None)
        nanos = getattr(timestamp, "nanos", 0) or 0
        if seconds is None:
            return ""
        return datetime.fromtimestamp(seconds + (nanos / 1_000_000_000)).isoformat()

    @staticmethod
    def _extract_task_error(result_dump: dict) -> str:
        error = result_dump.get("error")
        if isinstance(error, dict):
            return error.get("message", "") or error.get("code", "")
        if isinstance(error, str):
            return error
        return ""

    @staticmethod
    def _classify_task_result(status: TaskStatus) -> tuple[str, str, bool, bool]:
        status_value = status.value
        if status_value == TaskStatus.DISPATCHED.value:
            return "dispatch_accepted", "waiting_remote", False, False
        if status_value == TaskStatus.RUNNING.value:
            return "execution_started", "running", False, False
        if status_value == TaskStatus.SUCCESS.value:
            return "execution_completed", "succeeded", True, True
        if status_value in (TaskStatus.FAILED.value, TaskStatus.LSP_FAILED.value):
            return "execution_failed", "failed", True, False
        if status_value == TaskStatus.TIMEOUT.value:
            return "execution_timed_out", "timed_out", True, False
        if status_value == TaskStatus.CANCELLED.value:
            return "execution_cancelled", "cancelled", True, False
        return "result_received_pending_closure", "waiting_remote", False, False

    @staticmethod
    def _validate_result_correlation(record: dict, result: TaskResultModel) -> str:
        expected_worker_id = record.get("worker_id", "")
        if expected_worker_id and result.worker_id and expected_worker_id != result.worker_id:
            return f"result_worker_id_mismatch:{expected_worker_id}!={result.worker_id}"
        expected_trace_id = record.get("trace_id", "")
        actual_trace_id = (result.metadata or {}).get("trace_id", "")
        if expected_trace_id and actual_trace_id and expected_trace_id != actual_trace_id:
            return f"result_trace_id_mismatch:{expected_trace_id}!={actual_trace_id}"
        return ""

    def _mark_inflight_tasks_for_worker(self, worker_id: str, *, error: str) -> list[str]:
        affected: list[str] = []
        for task_id, record in list(self._task_log.items()):
            if record.get("worker_id") != worker_id or record.get("closure_complete"):
                continue
            self._mark_task_terminal(
                task_id,
                status=TaskStatus.FAILED.value,
                completion_state="execution_abandoned",
                lifecycle_state="abandoned",
                error=error,
            )
            affected.append(task_id)
        return affected

    def _mark_task_terminal(
        self,
        task_id: str,
        *,
        status: str,
        completion_state: str,
        lifecycle_state: str,
        error: str,
        worker_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        **extra_updates: Any,
    ) -> dict:
        self._task_log.setdefault(task_id, self._default_task_record(task_id))
        updates = {
            "status": status,
            "completion_state": completion_state,
            "lifecycle_state": lifecycle_state,
            "success": False,
            "error": error,
            "closure_complete": True,
            "task_outcome_known": True,
            "result_pending_closure": False,
            "completed_at": datetime.now().isoformat(),
        }
        if worker_id:
            updates["worker_id"] = worker_id
        if trace_id:
            updates["trace_id"] = trace_id
        updates.update(extra_updates)
        snapshot = self._update_task_record(task_id, **updates)
        self._apply_task_graph_result(
            task_id,
            status=status,
            completion_state=completion_state,
        )
        waiter = self._task_waiters.get(task_id)
        if waiter is not None and not waiter.done():
            waiter.set_result(snapshot)
        return snapshot

    def _recover_incomplete_state(self, task_id: Optional[str] = None) -> None:
        target_records = (
            [(task_id, self._task_log[task_id])]
            if task_id and task_id in self._task_log
            else list(self._task_log.items())
        )
        state_changed = False
        now_iso = datetime.now().isoformat()

        for worker_id, info in self._workers.items():
            alive = (time.time() - info.get("last_heartbeat", 0)) < _HEARTBEAT_TIMEOUT_S
            if info.get("force_offline"):
                alive = False
            if not alive and info.get("status") not in ("dead", "offline"):
                info["status"] = "dead"
                info.setdefault("dead_at", now_iso)
                self._mark_inflight_tasks_for_worker(worker_id, error=f"worker_lost:{worker_id}")
                state_changed = True

        for current_task_id, record in target_records:
            if record.get("closure_complete"):
                continue
            if self._task_deadline_expired(record):
                self._mark_task_terminal(
                    current_task_id,
                    status=TaskStatus.TIMEOUT.value,
                    completion_state="execution_timed_out",
                    lifecycle_state="timed_out",
                    error=record.get("error") or "task_deadline_exceeded",
                )
                state_changed = True

        if state_changed:
            self._persist_state()

    @staticmethod
    def _task_deadline_expired(record: dict) -> bool:
        deadline_at = record.get("deadline_at")
        if not deadline_at:
            return False
        try:
            return datetime.now() >= datetime.fromisoformat(deadline_at)
        except ValueError:
            return False

    @staticmethod
    def _public_task_record(record: dict) -> dict:
        return {k: v for k, v in record.items() if not k.startswith("_")}

    def _persist_state(self) -> None:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._state_path.with_suffix(self._state_path.suffix + ".tmp")
            payload = {
                "version": 1,
                "saved_at": datetime.now().isoformat(),
                "workers": self._workers,
                "tasks": {
                    task_id: self._serialize_task_record(record)
                    for task_id, record in self._task_log.items()
                },
            }
            tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
            tmp_path.replace(self._state_path)
            self._persistence_degraded = False
            self._persistence_last_error = ""
        except Exception as exc:
            self._persistence_degraded = True
            self._persistence_last_error = str(exc)
            logger.warning("MasterBrain: failed to persist state to %s: %s", self._state_path, exc)

    def _load_state(self) -> None:
        if not self._state_path.exists():
            return
        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
            workers = payload.get("workers")
            tasks = payload.get("tasks")
            if isinstance(workers, dict):
                self._workers = {
                    str(worker_id): dict(worker_state)
                    for worker_id, worker_state in workers.items()
                    if isinstance(worker_state, dict)
                }
            if isinstance(tasks, dict):
                self._task_log = {
                    str(task_id): self._deserialize_task_record(record)
                    for task_id, record in tasks.items()
                    if isinstance(record, dict)
                }
        except Exception as exc:
            self._persistence_degraded = True
            self._persistence_last_error = str(exc)
            logger.warning("MasterBrain: failed to load persisted state from %s: %s", self._state_path, exc)

    @staticmethod
    def _serialize_task_record(record: dict) -> dict:
        serialized = dict(record)
        result_ids = serialized.get("_result_ids")
        if isinstance(result_ids, set):
            serialized["_result_ids"] = sorted(result_ids)
        return serialized

    @staticmethod
    def _deserialize_task_record(record: dict) -> dict:
        restored = dict(record)
        result_ids = restored.get("_result_ids")
        if isinstance(result_ids, list):
            restored["_result_ids"] = set(result_ids)
        else:
            restored["_result_ids"] = set()
        return restored


# ── Module-level singleton (constraint C1 — lazy, depends on env) ──────────
_master_brain: Optional[MasterBrain] = None


def get_master_brain() -> Optional[MasterBrain]:
    """Get MasterBrain singleton.  Returns None if not enabled."""
    global _master_brain
    if not master_brain_enabled():
        return None
    if _master_brain is None:
        _master_brain = MasterBrain.get_instance()
    return _master_brain
