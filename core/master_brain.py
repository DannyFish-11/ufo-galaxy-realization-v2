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
  C11 — loguru logger
"""

from __future__ import annotations

import os
import time
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

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
        from integration.event_bus import EventBus, EventType

        bus = EventBus()
        et = getattr(EventType, event_type_name, None)
        if et is not None:
            import asyncio

            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(bus.emit(et, data))
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
        if self._nats.is_connected():
            await self._nats.subscribe_heartbeats(self._on_heartbeat)
            await self._nats.subscribe_task_results(self._on_task_result)
            await self._nats.subscribe_events("worker_registered", self._on_worker_event)

        # Try connecting to Temporal
        try:
            from core.temporal_workflows import get_temporal_client

            self._temporal_client = await get_temporal_client()
        except Exception:
            logger.debug("MasterBrain: Temporal unavailable, workflow features disabled")

        self._started = True
        logger.info("MasterBrain: started (NATS={}, Temporal={})",
                     self._nats.is_connected(),
                     self._temporal_client is not None)
        return {"success": True}

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

        # Publish to NATS
        result = await self._nats.publish_task_dispatch(target, task)
        if result.get("success"):
            self._task_log[task.task_id] = {
                "task_id": task.task_id,
                "worker_id": target,
                "status": "dispatched",
                "dispatched_at": datetime.now().isoformat(),
            }
            _try_emit_event("TASK_DISPATCHED", {
                "task_id": task.task_id,
                "worker_id": target,
                "task_type": task.task_type.value,
            })
            result["task_id"] = task.task_id

        return result

    async def handle_task_result(self, result: TaskResultModel) -> dict:
        """Process worker result, update task log, emit event."""
        task_id = result.task_id
        if task_id in self._task_log:
            self._task_log[task_id]["status"] = result.status.value
            self._task_log[task_id]["completed_at"] = datetime.now().isoformat()

        _try_emit_event("TASK_RESULT_RECEIVED", {
            "task_id": task_id,
            "worker_id": result.worker_id,
            "status": result.status.value,
        })

        logger.info("MasterBrain: task {} completed with status {}", task_id, result.status.value)
        return {"success": True, "task_id": task_id, "status": result.status.value}

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
            logger.info("MasterBrain: started workflow {} (run={})", wf_name, run_id)
            return {"success": True, "workflow_id": handle.id, "run_id": run_id}
        except Exception as exc:
            logger.error("MasterBrain: workflow start failed — {}", exc)
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
        }
        _try_emit_event("WORKER_REGISTERED", {"worker_id": wid, "device_type": registration.device_type})
        logger.info("MasterBrain: worker registered — {} ({})", wid, registration.device_type)
        return {"success": True, "worker_id": wid}

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
        })
        return {"success": True}

    def get_worker_topology(self) -> dict:
        """Return current worker topology with liveness info."""
        now = time.time()
        topology = {}
        for wid, info in self._workers.items():
            alive = (now - info.get("last_heartbeat", 0)) < _HEARTBEAT_TIMEOUT_S
            topology[wid] = {**info, "alive": alive}
            if not alive and info.get("status") != "dead":
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

    # ── NATS callbacks ──────────────────────────────────────────────────────

    async def _on_heartbeat(self, data: dict) -> None:
        try:
            hb = WorkerHeartbeatModel.model_validate(data)
            await self.handle_heartbeat(hb)
        except Exception as exc:
            logger.debug("MasterBrain: heartbeat parse error — {}", exc)

    async def _on_task_result(self, data: dict) -> None:
        try:
            result_validated = await self._acl.validate_task_result(data)
            if result_validated["success"]:
                await self.handle_task_result(result_validated["data"])
        except Exception as exc:
            logger.error("MasterBrain: task result handling error — {}", exc)

    async def _on_worker_event(self, data: dict) -> None:
        try:
            reg = WorkerRegistrationModel.model_validate(data)
            await self.register_worker(reg)
        except Exception:
            pass

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
