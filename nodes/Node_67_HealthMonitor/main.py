"""
Node 67: Intelligent Health Monitor & Self-Healer
UFO Galaxy 64-Core MCP Matrix - Phase 6: Immune System

Adaptive recovery with three-strike rule and graceful degradation.
"""

import os
import json
import asyncio
import logging
import time
from typing import Dict, Optional, List, Any, Callable
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from enum import Enum
from dataclasses import dataclass, field
import random

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn
import httpx

# =============================================================================
# Configuration
# =============================================================================

NODE_ID = os.getenv("NODE_ID", "67")
NODE_NAME = os.getenv("NODE_NAME", "HealthMonitor")
STATE_MACHINE_URL = os.getenv("STATE_MACHINE_URL", "http://localhost:8000")
TELEMETRY_URL = os.getenv("TELEMETRY_URL", "http://localhost:8064")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Health check configuration
HEALTH_CHECK_INTERVAL = int(os.getenv("HEALTH_CHECK_INTERVAL", "30"))
MAX_FAILURES = 3
BACKOFF_BASE = 15  # seconds

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format=f"[Node {NODE_ID}] %(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# =============================================================================
# Models
# =============================================================================

class NodeStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    RECOVERING = "recovering"
    SAFE_MODE = "safe_mode"
    UNKNOWN = "unknown"

class RecoveryAction(str, Enum):
    RESTART = "restart"
    RESET_USB = "reset_usb"
    COLD_REBOOT = "cold_reboot"
    THROTTLE = "throttle"
    CLEAR_CACHE = "clear_cache"
    FORCE_RELEASE = "force_release"
    VALIDATE_STATE = "validate_state"
    RESTORE_BACKUP = "restore_backup"
    REBUILD_INDEXES = "rebuild_indexes"
    DUMP_HEAP = "dump_heap"

class FailureType(str, Enum):
    CONNECTION_LOST = "connection_lost"
    HIGH_LATENCY = "high_latency"
    STALE_LOCK = "stale_lock"
    MEMORY_LEAK = "memory_leak"
    CORRUPTION = "corruption"
    TIMEOUT = "timeout"
    ERROR_RATE = "error_rate"
    RESOURCE_EXHAUSTION = "resource_exhaustion"

@dataclass
class NodeHealth:
    """Health status of a node."""
    node_id: str
    status: NodeStatus
    last_check: float
    failure_count: int = 0
    last_failure: Optional[float] = None
    failure_type: Optional[FailureType] = None
    recovery_attempts: int = 0
    in_safe_mode: bool = False
    metrics: Dict[str, float] = field(default_factory=dict)

@dataclass
class RecoveryAttempt:
    """Record of a recovery attempt."""
    node_id: str
    timestamp: float
    action: RecoveryAction
    success: bool
    duration_ms: float
    details: str

class HealthReport(BaseModel):
    node_id: str
    status: NodeStatus
    latency_ms: float
    error_count: int = 0
    metrics: Dict[str, float] = {}

class RecoveryRequest(BaseModel):
    node_id: str
    failure_type: FailureType
    force: bool = False

# =============================================================================
# Recovery Strategies
# =============================================================================

class RecoveryStrategy:
    """Recovery strategies for different node types and failure modes."""
    
    STRATEGIES: Dict[str, Dict[str, List[RecoveryAction]]] = {
        "Node_33_ADB": {
            FailureType.CONNECTION_LOST.value: [
                RecoveryAction.RESTART,
                RecoveryAction.RESET_USB,
                RecoveryAction.COLD_REBOOT
            ],
            FailureType.HIGH_LATENCY.value: [
                RecoveryAction.THROTTLE,
                RecoveryAction.CLEAR_CACHE
            ],
            FailureType.TIMEOUT.value: [
                RecoveryAction.RESTART,
                RecoveryAction.RESET_USB
            ]
        },
        "Node_00_StateMachine": {
            FailureType.STALE_LOCK.value: [
                RecoveryAction.FORCE_RELEASE,
                RecoveryAction.VALIDATE_STATE
            ],
            FailureType.MEMORY_LEAK.value: [
                RecoveryAction.DUMP_HEAP,
                RecoveryAction.RESTART
            ],
            FailureType.CORRUPTION.value: [
                RecoveryAction.RESTORE_BACKUP,
                RecoveryAction.REBUILD_INDEXES
            ]
        },
        "Node_50_Transformer": {
            FailureType.HIGH_LATENCY.value: [
                RecoveryAction.THROTTLE,
                RecoveryAction.CLEAR_CACHE
            ],
            FailureType.ERROR_RATE.value: [
                RecoveryAction.RESTART,
                RecoveryAction.VALIDATE_STATE
            ]
        },
        "Node_58_ModelRouter": {
            FailureType.TIMEOUT.value: [
                RecoveryAction.RESTART,
                RecoveryAction.CLEAR_CACHE
            ],
            FailureType.RESOURCE_EXHAUSTION.value: [
                RecoveryAction.DUMP_HEAP,
                RecoveryAction.RESTART
            ]
        },
        "default": {
            FailureType.CONNECTION_LOST.value: [RecoveryAction.RESTART],
            FailureType.HIGH_LATENCY.value: [RecoveryAction.THROTTLE],
            FailureType.TIMEOUT.value: [RecoveryAction.RESTART],
            FailureType.ERROR_RATE.value: [RecoveryAction.RESTART],
            FailureType.RESOURCE_EXHAUSTION.value: [RecoveryAction.RESTART]
        }
    }
    
    @classmethod
    def get_actions(cls, node_id: str, failure_type: FailureType) -> List[RecoveryAction]:
        """Get recovery actions for a node and failure type."""
        # Try node-specific strategy
        node_strategies = cls.STRATEGIES.get(node_id, cls.STRATEGIES["default"])
        actions = node_strategies.get(failure_type.value, [])
        
        if not actions:
            # Fall back to default
            actions = cls.STRATEGIES["default"].get(failure_type.value, [RecoveryAction.RESTART])
        
        return actions

# =============================================================================
# Health Monitor
# =============================================================================

class HealthMonitor:
    """Main health monitoring service."""
    
    def __init__(self):
        self.nodes: Dict[str, NodeHealth] = {}
        self.recovery_history: List[RecoveryAttempt] = []
        self.http_client = httpx.AsyncClient(timeout=10)
        
        # Degraded mode settings
        self.degraded_mode = False
        self.non_essential_disabled: List[str] = []
        
        # Known node endpoints
        self.node_endpoints: Dict[str, str] = {
            "Node_00_StateMachine": "http://localhost:8000",
            "Node_50_Transformer": "http://localhost:8050",
            "Node_58_ModelRouter": "http://localhost:8058",
            "Node_33_ADB": "http://localhost:8033",
            "Node_64_Telemetry": "http://localhost:8064",
        }
    
    async def check_node(self, node_id: str) -> NodeHealth:
        """Check health of a single node."""
        endpoint = self.node_endpoints.get(node_id)
        
        if not endpoint:
            return NodeHealth(
                node_id=node_id,
                status=NodeStatus.UNKNOWN,
                last_check=time.time()
            )
        
        start_time = time.time()
        
        try:
            response = await self.http_client.get(f"{endpoint}/health")
            latency = (time.time() - start_time) * 1000
            
            if response.status_code == 200:
                data = response.json()
                
                # Determine status based on response
                if latency > 1000:
                    status = NodeStatus.DEGRADED
                elif data.get("status") == "healthy":
                    status = NodeStatus.HEALTHY
                else:
                    status = NodeStatus.DEGRADED
                
                health = self._get_or_create_health(node_id)
                health.status = status
                health.last_check = time.time()
                health.metrics["latency_ms"] = latency
                
                if status == NodeStatus.HEALTHY:
                    health.failure_count = 0
                
                return health
            else:
                return self._record_failure(node_id, FailureType.ERROR_RATE)
                
        except httpx.TimeoutException:
            return self._record_failure(node_id, FailureType.TIMEOUT)
        except httpx.ConnectError:
            return self._record_failure(node_id, FailureType.CONNECTION_LOST)
        except Exception as e:
            logger.error(f"Error checking {node_id}: {e}")
            return self._record_failure(node_id, FailureType.CONNECTION_LOST)
    
    def _get_or_create_health(self, node_id: str) -> NodeHealth:
        """Get or create health record for a node."""
        if node_id not in self.nodes:
            self.nodes[node_id] = NodeHealth(
                node_id=node_id,
                status=NodeStatus.UNKNOWN,
                last_check=time.time()
            )
        return self.nodes[node_id]
    
    def _record_failure(self, node_id: str, failure_type: FailureType) -> NodeHealth:
        """Record a failure for a node."""
        health = self._get_or_create_health(node_id)
        health.failure_count += 1
        health.last_failure = time.time()
        health.failure_type = failure_type
        health.last_check = time.time()
        
        if health.failure_count >= MAX_FAILURES:
            health.status = NodeStatus.UNHEALTHY
            if health.recovery_attempts >= MAX_FAILURES:
                health.in_safe_mode = True
                health.status = NodeStatus.SAFE_MODE
        else:
            health.status = NodeStatus.DEGRADED
        
        return health
    
    async def attempt_recovery(self, node_id: str, failure_type: FailureType) -> RecoveryAttempt:
        """Attempt to recover a node."""
        health = self._get_or_create_health(node_id)
        
        # Check if in safe mode
        if health.in_safe_mode:
            return RecoveryAttempt(
                node_id=node_id,
                timestamp=time.time(),
                action=RecoveryAction.RESTART,
                success=False,
                duration_ms=0,
                details="Node in safe mode - manual intervention required"
            )
        
        # Get recovery actions
        actions = RecoveryStrategy.get_actions(node_id, failure_type)
        
        # Determine which action to try based on attempt count
        action_index = min(health.recovery_attempts, len(actions) - 1)
        action = actions[action_index]
        
        # Calculate backoff
        backoff = BACKOFF_BASE * (2 ** health.recovery_attempts)
        
        # Check if we should wait
        if health.last_failure:
            time_since_failure = time.time() - health.last_failure
            if time_since_failure < backoff:
                return RecoveryAttempt(
                    node_id=node_id,
                    timestamp=time.time(),
                    action=action,
                    success=False,
                    duration_ms=0,
                    details=f"Waiting for backoff: {backoff - time_since_failure:.0f}s remaining"
                )
        
        # Execute recovery action
        start_time = time.time()
        success = await self._execute_recovery(node_id, action)
        duration = (time.time() - start_time) * 1000
        
        # Update health
        health.recovery_attempts += 1
        if success:
            health.status = NodeStatus.RECOVERING
            health.failure_count = 0
        elif health.recovery_attempts >= MAX_FAILURES:
            health.in_safe_mode = True
            health.status = NodeStatus.SAFE_MODE
        
        # Record attempt
        attempt = RecoveryAttempt(
            node_id=node_id,
            timestamp=time.time(),
            action=action,
            success=success,
            duration_ms=duration,
            details=f"Attempt {health.recovery_attempts}/{MAX_FAILURES}"
        )
        self.recovery_history.append(attempt)
        
        # Limit history
        if len(self.recovery_history) > 1000:
            self.recovery_history = self.recovery_history[-500:]
        
        return attempt
    
    async def _execute_recovery(self, node_id: str, action: RecoveryAction) -> bool:
        """Execute a recovery action."""
        logger.info(f"Executing {action.value} for {node_id}")
        
        # Simulate recovery actions
        # In production, these would be actual recovery procedures
        
        if action == RecoveryAction.RESTART:
            # Simulate restart
            await asyncio.sleep(0.5)
            return random.random() > 0.3  # 70% success rate
        
        elif action == RecoveryAction.CLEAR_CACHE:
            await asyncio.sleep(0.2)
            return random.random() > 0.2  # 80% success rate
        
        elif action == RecoveryAction.THROTTLE:
            await asyncio.sleep(0.1)
            return True  # Always succeeds
        
        elif action == RecoveryAction.FORCE_RELEASE:
            await asyncio.sleep(0.3)
            return random.random() > 0.4  # 60% success rate
        
        elif action == RecoveryAction.RESET_USB:
            await asyncio.sleep(1.0)
            return random.random() > 0.5  # 50% success rate
        
        elif action == RecoveryAction.COLD_REBOOT:
            await asyncio.sleep(2.0)
            return random.random() > 0.6  # 40% success rate
        
        else:
            await asyncio.sleep(0.5)
            return random.random() > 0.3
    
    async def enter_degraded_mode(self):
        """Enter system-wide degraded mode."""
        if self.degraded_mode:
            return
        
        logger.warning("Entering degraded mode")
        self.degraded_mode = True
        
        # Disable non-essential features
        self.non_essential_disabled = [
            "Node_56_AgentSwarm",  # Multi-agent debate
            "Node_51_QuantumDispatcher",  # Quantum simulation
            "Node_52_QiskitSimulator",
        ]
    
    async def exit_degraded_mode(self):
        """Exit degraded mode."""
        if not self.degraded_mode:
            return
        
        logger.info("Exiting degraded mode")
        self.degraded_mode = False
        self.non_essential_disabled = []
    
    def get_system_health(self) -> Dict[str, Any]:
        """Get overall system health."""
        total_nodes = len(self.nodes)
        healthy_count = sum(1 for n in self.nodes.values() if n.status == NodeStatus.HEALTHY)
        degraded_count = sum(1 for n in self.nodes.values() if n.status == NodeStatus.DEGRADED)
        unhealthy_count = sum(1 for n in self.nodes.values() if n.status in [NodeStatus.UNHEALTHY, NodeStatus.SAFE_MODE])
        
        if total_nodes == 0:
            overall = NodeStatus.UNKNOWN
        elif unhealthy_count > total_nodes * 0.3:
            overall = NodeStatus.UNHEALTHY
        elif degraded_count > total_nodes * 0.5:
            overall = NodeStatus.DEGRADED
        else:
            overall = NodeStatus.HEALTHY
        
        return {
            "overall_status": overall.value,
            "total_nodes": total_nodes,
            "healthy": healthy_count,
            "degraded": degraded_count,
            "unhealthy": unhealthy_count,
            "degraded_mode": self.degraded_mode,
            "disabled_features": self.non_essential_disabled
        }
    
    def get_node_health(self, node_id: str) -> Optional[Dict[str, Any]]:
        """Get health details for a specific node."""
        health = self.nodes.get(node_id)
        if not health:
            return None
        
        return {
            "node_id": health.node_id,
            "status": health.status.value,
            "last_check": health.last_check,
            "failure_count": health.failure_count,
            "last_failure": health.last_failure,
            "failure_type": health.failure_type.value if health.failure_type else None,
            "recovery_attempts": health.recovery_attempts,
            "in_safe_mode": health.in_safe_mode,
            "metrics": health.metrics
        }
    
    def get_recovery_history(self, node_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recovery attempt history."""
        history = self.recovery_history
        
        if node_id:
            history = [h for h in history if h.node_id == node_id]
        
        return [
            {
                "node_id": h.node_id,
                "timestamp": h.timestamp,
                "action": h.action.value,
                "success": h.success,
                "duration_ms": h.duration_ms,
                "details": h.details
            }
            for h in history[-limit:]
        ]
    
    async def reset_node(self, node_id: str):
        """Reset a node's health status (manual intervention)."""
        if node_id in self.nodes:
            health = self.nodes[node_id]
            health.failure_count = 0
            health.recovery_attempts = 0
            health.in_safe_mode = False
            health.status = NodeStatus.UNKNOWN
            logger.info(f"Reset health status for {node_id}")

# =============================================================================
# FastAPI Application
# =============================================================================

monitor: Optional[HealthMonitor] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global monitor
    
    logger.info(f"Starting Node {NODE_ID}: {NODE_NAME}")
    monitor = HealthMonitor()
    logger.info(f"Node {NODE_ID} ({NODE_NAME}) is ready")
    
    yield
    
    logger.info(f"Shutting down Node {NODE_ID}")
    if monitor:
        await monitor.http_client.aclose()

app = FastAPI(
    title=f"UFO Galaxy Node {NODE_ID}: {NODE_NAME}",
    description="Intelligent Health Monitor & Self-Healer",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# API Endpoints
# =============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    system_health = monitor.get_system_health() if monitor else {}
    return {
        "status": "healthy",
        "node_id": NODE_ID,
        "node_name": NODE_NAME,
        "system_health": system_health
    }

@app.get("/system")
async def get_system_health():
    """Get overall system health."""
    return monitor.get_system_health()

@app.get("/nodes")
async def get_all_nodes():
    """Get health status of all nodes."""
    return {
        "nodes": [
            monitor.get_node_health(node_id)
            for node_id in monitor.nodes
        ]
    }

@app.get("/nodes/{node_id}")
async def get_node_health(node_id: str):
    """Get health status of a specific node."""
    health = monitor.get_node_health(node_id)
    if not health:
        raise HTTPException(status_code=404, detail="Node not found")
    return health

@app.post("/check/{node_id}")
async def check_node(node_id: str):
    """Manually trigger health check for a node."""
    health = await monitor.check_node(node_id)
    return monitor.get_node_health(node_id)

@app.post("/recover")
async def recover_node(request: RecoveryRequest):
    """Attempt to recover a node."""
    attempt = await monitor.attempt_recovery(request.node_id, request.failure_type)
    return {
        "node_id": attempt.node_id,
        "action": attempt.action.value,
        "success": attempt.success,
        "duration_ms": attempt.duration_ms,
        "details": attempt.details
    }

@app.post("/reset/{node_id}")
async def reset_node(node_id: str):
    """Reset a node's health status (manual intervention)."""
    await monitor.reset_node(node_id)
    return {"status": "reset", "node_id": node_id}

@app.get("/history")
async def get_recovery_history(node_id: Optional[str] = None, limit: int = 50):
    """Get recovery attempt history."""
    return {
        "history": monitor.get_recovery_history(node_id, limit),
        "total": len(monitor.recovery_history)
    }

@app.post("/degraded-mode/enter")
async def enter_degraded_mode():
    """Enter system-wide degraded mode."""
    await monitor.enter_degraded_mode()
    return {"status": "degraded_mode_enabled"}

@app.post("/degraded-mode/exit")
async def exit_degraded_mode():
    """Exit degraded mode."""
    await monitor.exit_degraded_mode()
    return {"status": "degraded_mode_disabled"}

@app.get("/strategies")
async def get_recovery_strategies():
    """Get available recovery strategies."""
    return {
        "strategies": RecoveryStrategy.STRATEGIES,
        "max_failures": MAX_FAILURES,
        "backoff_base_seconds": BACKOFF_BASE
    }

@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "node_id": NODE_ID,
        "node_name": NODE_NAME,
        "layer": "L0_KERNEL",
        "capabilities": ["health_monitoring", "self_healing", "graceful_degradation"]
    }

# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8067,
        reload=False,
        log_level=LOG_LEVEL.lower()
    )
