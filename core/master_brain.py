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
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

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
    ) -> None:
        self._nats = nats or nats_bus
        self._acl = acl_layer or acl
        self._workers: Dict[str, Dict[str, Any]] = {}
        self._task_log: Dict[str, Dict[str, Any]] = {}
        self._task_waiters: Dict[str, asyncio.Future] = {}
        self._temporal_client: Any = None
        self._started = False

    @classmethod
    def get_instance(cls) -> MasterBrain:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Lifecycle ───────────────────────────────────────────────────────────

    async def start(self) -> dict:
        """Initialize MasterBrain: connect NATS, subscribe to events."""
        if self._started:
            return {"success": True, "already_started": True}

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

        # Try connecting to Temporal
        try:
            from core.temporal_workflows import get_temporal_client

            self._temporal_client = await get_temporal_client()
        except Exception:
            logger.debug("MasterBrain: Temporal unavailable, workflow features disabled")

        self._started = True
        logger.info(f"MasterBrain: started (NATS={self._nats.is_connected()}, Temporal={self._temporal_client is not None})")
        return {
            "success": True,
            "nats_connected": nats_connected,
            "distributed_ready": bool(nats_connected and subscriptions_ok),
        }

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

        # Worker selection
        target = task.target_worker_id
        if not target:
            target = self._select_worker(task.target_device_type)
            if not target:
                return {"success": False, "error": "No available worker for device type: " + task.target_device_type}
            task.target_worker_id = target

        task_trace_id = task.context.get("trace_id")
        trace_id = raw_task.get("trace_id", "") if task_trace_id in (None, "") else task_trace_id
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
        record.setdefault("dispatched_at", datetime.now().isoformat())
        self._ensure_task_waiter(task.task_id)

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
            return self.get_task_status(task_id)
        if result_id:
            seen_result_ids.add(result_id)

        result_dump = result.model_dump(mode="json", exclude_none=True)
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
            updates["started_at"] = self._timestamp_to_iso(result.started_at) or record.get("started_at") or datetime.now().isoformat()
        if closure_complete:
            updates["completed_at"] = self._timestamp_to_iso(result.completed_at) or datetime.now().isoformat()
        snapshot = self._update_task_record(task_id, **updates)

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

    async def start_workflow(self, workflow_type: str, params: dict) -> dict:
        """Launch a Temporal workflow.

        Supported workflow types: ``code_execution``, ``multi_device``, ``tool_discovery``.
        """
        if self._temporal_client is None:
            return {"success": False, "error": "Temporal not available"}

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
            logger.info(f"MasterBrain: started workflow {wf_name} (run={run_id})")
            return {"success": True, "workflow_id": handle.id, "run_id": run_id}
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
        _try_emit_event(
            "WORKER_SHUTDOWN",
            {"worker_id": wid, "reason": shutdown.reason, "drain_timeout_s": shutdown.drain_timeout_s},
        )
        logger.info("MasterBrain: worker shutdown — %s (reason=%s)", wid, shutdown.reason)
        return {"success": True, "worker_id": wid, "status": "offline"}

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
        return {"success": True}

    def get_worker_topology(self) -> dict:
        """Return current worker topology with liveness info."""
        now = time.time()
        topology = {}
        for wid, info in self._workers.items():
            alive = (now - info.get("last_heartbeat", 0)) < _HEARTBEAT_TIMEOUT_S
            if info.get("force_offline"):
                alive = False
            topology[wid] = {**info, "alive": alive}
            if not alive and info.get("status") not in ("dead", "offline"):
                info["status"] = "dead"
                _try_emit_event("WORKER_DEAD", {"worker_id": wid})
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
        record = self._task_log.get(task_id)
        if record is None:
            return None
        return {k: v for k, v in record.items() if not k.startswith("_")}

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
        return {
            "started": self._started,
            "nats_connected": self._nats.is_connected(),
            "temporal_connected": self._temporal_client is not None,
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
        return record

    def _update_task_record(self, task_id: str, **updates: Any) -> dict:
        record = self._task_log.setdefault(task_id, self._default_task_record(task_id))
        record.update({k: v for k, v in updates.items() if v is not None})
        self._refresh_task_derived_fields(record)
        return self.get_task_status(task_id) or {}

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
            return "execution_failed", "timed_out", True, False
        if status_value == TaskStatus.CANCELLED.value:
            return "execution_failed", "cancelled", True, False
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


# ── Module-level singleton (constraint C1 — lazy, depends on env) ──────────
_master_brain: Optional[MasterBrain] = None


def get_master_brain() -> Optional[MasterBrain]:
    """Get MasterBrain singleton.  Returns None if not enabled."""
    global _master_brain
    enabled = os.environ.get("GALAXY_MASTER_BRAIN_ENABLED", "").lower() == "true"
    if not enabled:
        return None
    if _master_brain is None:
        _master_brain = MasterBrain.get_instance()
    return _master_brain
