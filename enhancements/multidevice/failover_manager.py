"""
UFO Galaxy v5.0 - Failover Manager Module

This module provides recovery mechanisms and circuit breaker pattern
for multi-device system resilience.

Features:
- Circuit breaker pattern
- Automatic failover
- Health checking
- Recovery mechanisms

Author: UFO Galaxy Team
Version: 5.0.0
"""

import asyncio
import time
import logging
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from enum import Enum, auto
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = auto()  # Normal operation
    OPEN = auto()    # Failing, reject requests
    HALF_OPEN = auto()  # Testing recovery


class RecoveryType(Enum):
    """Recovery strategy types."""
    AUTOMATIC = auto()  # Automatic recovery
    MANUAL = auto()     # Manual intervention required
    FAILOVER = auto()   # Failover to backup
    RESTART = auto()    # Restart device/service
    ROLLBACK = auto()   # Rollback to previous state


class RecoveryStatus(Enum):
    """Recovery operation status."""
    PENDING = auto()     # Recovery pending
    IN_PROGRESS = auto() # Recovery in progress
    SUCCESS = auto()     # Recovery successful
    FAILED = auto()      # Recovery failed
    CANCELLED = auto()   # Recovery cancelled


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker."""
    failure_threshold: int = 5
    timeout_seconds: float = 60.0
    half_open_max_calls: int = 3
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'failure_threshold': self.failure_threshold,
            'timeout_seconds': self.timeout_seconds,
            'half_open_max_calls': self.half_open_max_calls
        }


@dataclass
class FailureRecord:
    """Record of a failure event."""
    timestamp: float
    device_id: str
    error_type: str
    error_message: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'timestamp': self.timestamp,
            'device_id': self.device_id,
            'error_type': self.error_type,
            'error_message': self.error_message
        }


@dataclass
class Checkpoint:
    """Checkpoint for state recovery."""
    checkpoint_id: str
    timestamp: float
    device_id: str
    state_data: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'checkpoint_id': self.checkpoint_id,
            'timestamp': self.timestamp,
            'device_id': self.device_id,
            'state_data': self.state_data,
            'metadata': self.metadata
        }


@dataclass
class RecoveryResult:
    """Result of a recovery operation."""
    recovery_id: str
    device_id: str
    recovery_type: RecoveryType
    status: RecoveryStatus
    started_at: float
    completed_at: Optional[float] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'recovery_id': self.recovery_id,
            'device_id': self.device_id,
            'recovery_type': self.recovery_type.name,
            'status': self.status.name,
            'started_at': self.started_at,
            'completed_at': self.completed_at,
            'error_message': self.error_message,
            'metadata': self.metadata
        }


class CircuitBreaker:
    """
    Circuit breaker for device operations.
    
    Prevents cascading failures by temporarily blocking requests
    to failing devices.
    """
    
    def __init__(
        self,
        failure_threshold: int = 5,
        timeout_seconds: float = 60.0,
        half_open_max_calls: int = 3
    ):
        self.failure_threshold = failure_threshold
        self.timeout_seconds = timeout_seconds
        self.half_open_max_calls = half_open_max_calls
        
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: Optional[float] = None
        self._half_open_calls = 0
        
        logger.info(f"CircuitBreaker initialized (threshold={failure_threshold})")
    
    @property
    def state(self) -> CircuitState:
        """Get current circuit state."""
        self._check_timeout()
        return self._state
    
    def _check_timeout(self) -> None:
        """Check if timeout has expired and transition to HALF_OPEN."""
        if self._state == CircuitState.OPEN:
            if self._last_failure_time:
                elapsed = time.time() - self._last_failure_time
                if elapsed >= self.timeout_seconds:
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_calls = 0
                    logger.info("Circuit breaker transitioning to HALF_OPEN")
    
    def record_success(self) -> None:
        """Record a successful operation."""
        if self._state == CircuitState.HALF_OPEN:
            self._half_open_calls += 1
            if self._half_open_calls >= self.half_open_max_calls:
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                logger.info("Circuit breaker transitioning to CLOSED")
        elif self._state == CircuitState.CLOSED:
            self._failure_count = max(0, self._failure_count - 1)
    
    def record_failure(self) -> None:
        """Record a failed operation."""
        self._failure_count += 1
        self._last_failure_time = time.time()
        
        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.OPEN
            logger.warning("Circuit breaker transitioning to OPEN (half-open failure)")
        elif self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN
            logger.warning(f"Circuit breaker transitioning to OPEN (threshold reached)")
    
    def can_execute(self) -> bool:
        """Check if operation can be executed."""
        self._check_timeout()
        return self._state != CircuitState.OPEN
    
    def reset(self) -> None:
        """Reset circuit breaker to CLOSED state."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = None
        self._half_open_calls = 0
        logger.info("Circuit breaker reset to CLOSED")


class RecoveryStrategy:
    """
    Strategy for device recovery.
    
    Defines how to recover from failures based on device type and error type.
    """
    
    def __init__(self, device_id: str):
        self.device_id = device_id
        self._recovery_handlers: Dict[str, Callable] = {}
        logger.info(f"RecoveryStrategy initialized for device {device_id}")
    
    def register_handler(self, error_type: str, handler: Callable) -> None:
        """Register a recovery handler for an error type."""
        self._recovery_handlers[error_type] = handler
    
    async def recover(self, error_type: str, context: Dict[str, Any]) -> RecoveryResult:
        """Execute recovery for an error type."""
        handler = self._recovery_handlers.get(error_type)
        
        recovery_id = f"recovery_{int(time.time()*1000)}"
        result = RecoveryResult(
            recovery_id=recovery_id,
            device_id=self.device_id,
            recovery_type=RecoveryType.AUTOMATIC,
            status=RecoveryStatus.IN_PROGRESS,
            started_at=time.time()
        )
        
        if not handler:
            result.status = RecoveryStatus.FAILED
            result.error_message = f"No handler for error type: {error_type}"
            result.completed_at = time.time()
            return result
        
        try:
            await handler(context)
            result.status = RecoveryStatus.SUCCESS
        except Exception as e:
            result.status = RecoveryStatus.FAILED
            result.error_message = str(e)
        finally:
            result.completed_at = time.time()
        
        return result


class RetryRecovery(RecoveryStrategy):
    """Retry-based recovery strategy."""
    
    def __init__(self, device_id: str, max_retries: int = 3, retry_delay: float = 1.0):
        super().__init__(device_id)
        self.max_retries = max_retries
        self.retry_delay = retry_delay


class FailoverRecovery(RecoveryStrategy):
    """Failover to backup device recovery strategy."""
    
    def __init__(self, device_id: str, backup_devices: List[str]):
        super().__init__(device_id)
        self.backup_devices = backup_devices


class StateRecovery(RecoveryStrategy):
    """State restoration recovery strategy."""
    
    def __init__(self, device_id: str):
        super().__init__(device_id)
        self._checkpoints: List[Checkpoint] = []


class GracefulDegradation(RecoveryStrategy):
    """Graceful degradation recovery strategy."""
    
    def __init__(self, device_id: str):
        super().__init__(device_id)
        self._degraded_mode = False


class FailoverManager:
    """
    Manages failover and recovery for multi-device system.
    
    Tracks device health, manages circuit breakers, and coordinates
    automatic failover to backup devices.
    """
    
    def __init__(
        self,
        health_check_interval: float = 30.0,
        failure_threshold: int = 5
    ):
        self.health_check_interval = health_check_interval
        self.failure_threshold = failure_threshold
        
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
        self._failure_history: List[FailureRecord] = []
        self._backup_devices: Dict[str, List[str]] = {}
        self._health_check_task: Optional[asyncio.Task] = None
        
        logger.info("FailoverManager initialized")
    
    def get_circuit_breaker(self, device_id: str) -> CircuitBreaker:
        """Get or create circuit breaker for device."""
        if device_id not in self._circuit_breakers:
            self._circuit_breakers[device_id] = CircuitBreaker(
                failure_threshold=self.failure_threshold
            )
        return self._circuit_breakers[device_id]
    
    def record_failure(
        self,
        device_id: str,
        error_type: str,
        error_message: str
    ) -> None:
        """Record a device failure."""
        record = FailureRecord(
            timestamp=time.time(),
            device_id=device_id,
            error_type=error_type,
            error_message=error_message
        )
        self._failure_history.append(record)
        
        # Update circuit breaker
        breaker = self.get_circuit_breaker(device_id)
        breaker.record_failure()
        
        logger.warning(f"Failure recorded for device {device_id}: {error_type}")
    
    def record_success(self, device_id: str) -> None:
        """Record a successful operation."""
        breaker = self.get_circuit_breaker(device_id)
        breaker.record_success()
    
    def can_use_device(self, device_id: str) -> bool:
        """Check if device can be used."""
        breaker = self.get_circuit_breaker(device_id)
        return breaker.can_execute()
    
    def register_backup(self, primary_device: str, backup_devices: List[str]) -> None:
        """Register backup devices for a primary device."""
        self._backup_devices[primary_device] = backup_devices
        logger.info(f"Registered {len(backup_devices)} backup devices for {primary_device}")
    
    def get_backup_device(self, primary_device: str) -> Optional[str]:
        """Get an available backup device."""
        backups = self._backup_devices.get(primary_device, [])
        for backup_id in backups:
            if self.can_use_device(backup_id):
                return backup_id
        return None
    
    def get_failure_stats(self, device_id: Optional[str] = None) -> Dict[str, Any]:
        """Get failure statistics."""
        if device_id:
            failures = [f for f in self._failure_history if f.device_id == device_id]
        else:
            failures = self._failure_history
        
        return {
            'total_failures': len(failures),
            'recent_failures': len([f for f in failures if time.time() - f.timestamp < 3600]),
            'devices_affected': len(set(f.device_id for f in failures))
        }
    
    async def start_health_checks(self, health_check_callback: Callable) -> None:
        """Start periodic health checks."""
        async def health_check_loop():
            while True:
                try:
                    await health_check_callback()
                    await asyncio.sleep(self.health_check_interval)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Health check error: {e}")
        
        self._health_check_task = asyncio.create_task(health_check_loop())
        logger.info("Health check loop started")
    
    async def stop_health_checks(self) -> None:
        """Stop health checks."""
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
            logger.info("Health check loop stopped")
    
    def reset_circuit_breaker(self, device_id: str) -> None:
        """Reset circuit breaker for a device."""
        if device_id in self._circuit_breakers:
            self._circuit_breakers[device_id].reset()
            logger.info(f"Circuit breaker reset for device {device_id}")
