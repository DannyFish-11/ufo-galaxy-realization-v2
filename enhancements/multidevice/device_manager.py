"""
UFO Galaxy v5.0 - Device Manager Module
Multi-Device Coordination System

This module provides device registration, discovery, heartbeat monitoring,
and health tracking for the UFO Galaxy distributed system.

Features:
- Device registration and discovery (<3s response time)
- Heartbeat monitoring (5s interval)
- Device grouping and tagging
- Device health tracking
- Support for 500+ TPS
- Cross-platform support (Linux, Android)

FastAPI Endpoints:
- POST /devices/register - Register a new device
- POST /devices/unregister - Unregister a device
- GET /devices - List all devices
- GET /devices/{device_id} - Get device details
- POST /devices/{device_id}/heartbeat - Device heartbeat
- GET /devices/discover - Discover available devices
- GET /devices/groups/{group} - Get devices by group
- GET /devices/tags/{tag} - Get devices by tag

Author: UFO Galaxy Team
Version: 5.0.0
Port: 8056
"""

import asyncio
import time
import uuid
import logging
from typing import Dict, List, Optional, Set, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict
import json

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

from device_protocol import (
    DeviceInfo, DeviceCapabilities, DeviceType, DeviceStatus,
    MessageType, AIPMessage, MessageBuilder, ProtocolValidator
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================================
# Pydantic Models for API
# ============================================================================

class DeviceRegistrationRequest(BaseModel):
    """Device registration request"""
    device_type: DeviceType
    device_name: str
    device_model: str = "unknown"
    os_version: str = "unknown"
    app_version: str = "5.0.0"
    ip_address: str
    port: int = 8055
    capabilities: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)
    groups: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DeviceHeartbeatRequest(BaseModel):
    """Device heartbeat request"""
    device_id: str
    status: DeviceStatus = DeviceStatus.ONLINE
    metrics: Dict[str, Any] = Field(default_factory=dict)


class DeviceUpdateRequest(BaseModel):
    """Device update request"""
    device_name: Optional[str] = None
    capabilities: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None
    groups: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None


class DeviceResponse(BaseModel):
    """Device response model"""
    device_id: str
    device_type: int
    device_name: str
    device_model: str
    os_version: str
    app_version: str
    ip_address: str
    port: int
    status: int
    tags: List[str]
    groups: List[str]
    registered_at: float
    last_heartbeat: float
    health_score: float


class DeviceListResponse(BaseModel):
    """Device list response"""
    devices: List[DeviceResponse]
    total: int
    online_count: int
    offline_count: int


class HealthMetrics(BaseModel):
    """Device health metrics"""
    device_id: str
    health_score: float
    uptime_seconds: float
    heartbeat_interval_avg: float
    missed_heartbeats: int
    last_error: Optional[str] = None
    cpu_usage: Optional[float] = None
    memory_usage: Optional[float] = None
    network_latency_ms: Optional[float] = None


# ============================================================================
# Device Health Tracker
# ============================================================================

@dataclass
class DeviceHealthRecord:
    """Device health tracking record"""
    device_id: str
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    heartbeat_times: List[float] = field(default_factory=list)
    missed_heartbeats: int = 0
    consecutive_failures: int = 0
    errors: List[Dict[str, Any]] = field(default_factory=list)
    health_score: float = 100.0
    cpu_usage_history: List[float] = field(default_factory=list)
    memory_usage_history: List[float] = field(default_factory=list)
    network_latency_history: List[float] = field(default_factory=list)
    
    def update_heartbeat(self, metrics: Optional[Dict[str, Any]] = None) -> None:
        """Update device heartbeat"""
        current_time = time.time()
        self.heartbeat_times.append(current_time)
        
        # Keep only last 100 heartbeats
        if len(self.heartbeat_times) > 100:
            self.heartbeat_times = self.heartbeat_times[-100:]
        
        self.last_seen = current_time
        self.consecutive_failures = 0
        
        # Update metrics
        if metrics:
            if 'cpu_usage' in metrics:
                self.cpu_usage_history.append(metrics['cpu_usage'])
                self.cpu_usage_history = self.cpu_usage_history[-100:]
            if 'memory_usage' in metrics:
                self.memory_usage_history.append(metrics['memory_usage'])
                self.memory_usage_history = self.memory_usage_history[-100:]
            if 'network_latency_ms' in metrics:
                self.network_latency_history.append(metrics['network_latency_ms'])
                self.network_latency_history = self.network_latency_history[-100:]
        
        self._calculate_health_score()
    
    def record_missed_heartbeat(self) -> None:
        """Record a missed heartbeat"""
        self.missed_heartbeats += 1
        self.consecutive_failures += 1
        self._calculate_health_score()
    
    def record_error(self, error_message: str) -> None:
        """Record an error"""
        self.errors.append({
            'timestamp': time.time(),
            'message': error_message
        })
        # Keep only last 50 errors
        if len(self.errors) > 50:
            self.errors = self.errors[-50:]
        self._calculate_health_score()
    
    def _calculate_health_score(self) -> None:
        """Calculate device health score (0-100)"""
        score = 100.0
        
        # Deduct for missed heartbeats
        score -= min(self.missed_heartbeats * 5, 30)
        
        # Deduct for consecutive failures
        score -= min(self.consecutive_failures * 10, 40)
        
        # Deduct for errors
        score -= min(len(self.errors) * 2, 20)
        
        # Deduct for high resource usage
        if self.cpu_usage_history:
            avg_cpu = sum(self.cpu_usage_history[-10:]) / min(len(self.cpu_usage_history), 10)
            if avg_cpu > 90:
                score -= 10
        
        if self.memory_usage_history:
            avg_mem = sum(self.memory_usage_history[-10:]) / min(len(self.memory_usage_history), 10)
            if avg_mem > 90:
                score -= 10
        
        self.health_score = max(0.0, score)
    
    def get_average_heartbeat_interval(self) -> float:
        """Get average heartbeat interval"""
        if len(self.heartbeat_times) < 2:
            return 5.0  # Default 5 seconds
        
        intervals = [
            self.heartbeat_times[i] - self.heartbeat_times[i-1]
            for i in range(1, len(self.heartbeat_times))
        ]
        return sum(intervals) / len(intervals)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'device_id': self.device_id,
            'first_seen': self.first_seen,
            'last_seen': self.last_seen,
            'missed_heartbeats': self.missed_heartbeats,
            'consecutive_failures': self.consecutive_failures,
            'health_score': self.health_score,
            'uptime_seconds': self.last_seen - self.first_seen,
            'heartbeat_interval_avg': self.get_average_heartbeat_interval(),
            'last_error': self.errors[-1]['message'] if self.errors else None,
            'cpu_usage': self.cpu_usage_history[-1] if self.cpu_usage_history else None,
            'memory_usage': self.memory_usage_history[-1] if self.memory_usage_history else None,
            'network_latency_ms': self.network_latency_history[-1] if self.network_latency_history else None
        }


# ============================================================================
# Device Manager
# ============================================================================

class DeviceManager:
    """
    Device Manager for UFO Galaxy
    
    Manages device registration, discovery, heartbeat monitoring,
    and health tracking for distributed devices.
    """
    
    def __init__(
        self,
        heartbeat_interval: float = 5.0,
        heartbeat_timeout: float = 15.0,
        discovery_timeout: float = 3.0
    ):
        self.devices: Dict[str, DeviceInfo] = {}
        self.health_records: Dict[str, DeviceHealthRecord] = {}
        self.groups: Dict[str, Set[str]] = defaultdict(set)
        self.tags: Dict[str, Set[str]] = defaultdict(set)
        
        self.heartbeat_interval = heartbeat_interval
        self.heartbeat_timeout = heartbeat_timeout
        self.discovery_timeout = discovery_timeout
        
        self._lock = asyncio.Lock()
        self._callbacks: Dict[str, List[Callable]] = {
            'device_registered': [],
            'device_unregistered': [],
            'device_offline': [],
            'heartbeat_received': [],
            'health_changed': []
        }
        
        self._running = False
        self._monitor_task: Optional[asyncio.Task] = None
        
        logger.info("DeviceManager initialized")
    
    def register_callback(self, event: str, callback: Callable) -> None:
        """Register event callback"""
        if event in self._callbacks:
            self._callbacks[event].append(callback)
    
    async def _notify(self, event: str, *args, **kwargs) -> None:
        """Notify event callbacks"""
        for callback in self._callbacks.get(event, []):
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(*args, **kwargs)
                else:
                    callback(*args, **kwargs)
            except Exception as e:
                logger.error(f"Callback error for {event}: {e}")
    
    async def start(self) -> None:
        """Start device manager"""
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info("DeviceManager started")
    
    async def stop(self) -> None:
        """Stop device manager"""
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        logger.info("DeviceManager stopped")
    
    async def _monitor_loop(self) -> None:
        """Monitor loop for device health checks"""
        while self._running:
            try:
                await self._check_device_health()
                await asyncio.sleep(self.heartbeat_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Monitor loop error: {e}")
                await asyncio.sleep(1)
    
    async def _check_device_health(self) -> None:
        """Check device health status"""
        current_time = time.time()
        offline_devices = []
        
        async with self._lock:
            for device_id, device in self.devices.items():
                health = self.health_records.get(device_id)
                if not health:
                    continue
                
                time_since_last = current_time - health.last_seen
                
                if time_since_last > self.heartbeat_timeout:
                    # Device is offline
                    if device.status != DeviceStatus.OFFLINE:
                        device.status = DeviceStatus.OFFLINE
                        health.record_missed_heartbeat()
                        offline_devices.append(device_id)
                        logger.warning(f"Device {device_id} is offline")
                elif time_since_last > self.heartbeat_interval * 2:
                    # Device may be having issues
                    if device.status == DeviceStatus.ONLINE:
                        device.status = DeviceStatus.DEGRADED
                        health.record_missed_heartbeat()
                        logger.warning(f"Device {device_id} is degraded")
        
        # Notify callbacks
        for device_id in offline_devices:
            await self._notify('device_offline', device_id)
    
    async def register_device(
        self,
        request: DeviceRegistrationRequest
    ) -> DeviceInfo:
        """
        Register a new device
        
        Args:
            request: Device registration request
            
        Returns:
            Registered device info
            
        Raises:
            ValueError: If device already registered with different info
        """
        device_id = str(uuid.uuid4())
        
        async with self._lock:
            # Check if device with same IP:port exists
            for existing_id, existing in self.devices.items():
                if existing.ip_address == request.ip_address and existing.port == request.port:
                    logger.warning(f"Device {existing_id} already registered at {request.ip_address}:{request.port}")
                    # Update existing device
                    device_id = existing_id
                    break
            
            capabilities = DeviceCapabilities(**request.capabilities)
            
            device = DeviceInfo(
                device_id=device_id,
                device_type=request.device_type,
                device_name=request.device_name,
                device_model=request.device_model,
                os_version=request.os_version,
                app_version=request.app_version,
                ip_address=request.ip_address,
                port=request.port,
                capabilities=capabilities,
                tags=request.tags,
                groups=request.groups,
                metadata=request.metadata,
                status=DeviceStatus.ONLINE
            )
            
            self.devices[device_id] = device
            
            # Create health record
            self.health_records[device_id] = DeviceHealthRecord(device_id=device_id)
            
            # Update groups and tags
            for group in request.groups:
                self.groups[group].add(device_id)
            for tag in request.tags:
                self.tags[tag].add(device_id)
            
            logger.info(f"Device registered: {device_id} ({request.device_name})")
        
        await self._notify('device_registered', device)
        return device
    
    async def unregister_device(self, device_id: str) -> bool:
        """
        Unregister a device
        
        Args:
            device_id: Device ID to unregister
            
        Returns:
            True if unregistered, False if not found
        """
        async with self._lock:
            device = self.devices.pop(device_id, None)
            if not device:
                return False
            
            # Remove from groups
            for group in device.groups:
                self.groups[group].discard(device_id)
            
            # Remove from tags
            for tag in device.tags:
                self.tags[tag].discard(device_id)
            
            # Remove health record
            self.health_records.pop(device_id, None)
            
            logger.info(f"Device unregistered: {device_id}")
        
        await self._notify('device_unregistered', device)
        return True
    
    async def process_heartbeat(
        self,
        request: DeviceHeartbeatRequest
    ) -> Dict[str, Any]:
        """
        Process device heartbeat
        
        Args:
            request: Heartbeat request
            
        Returns:
            Response with coordinator info
        """
        device_id = request.device_id
        
        async with self._lock:
            device = self.devices.get(device_id)
            if not device:
                raise HTTPException(status_code=404, detail=f"Device {device_id} not found")
            
            # Update device status
            device.status = request.status
            device.last_heartbeat = time.time()
            
            # Update health record
            health = self.health_records.get(device_id)
            if health:
                health.update_heartbeat(request.metrics)
        
        await self._notify('heartbeat_received', device_id, request.metrics)
        
        return {
            'acknowledged': True,
            'server_time': time.time(),
            'next_heartbeat_interval': self.heartbeat_interval
        }
    
    async def get_device(self, device_id: str) -> Optional[DeviceInfo]:
        """Get device by ID"""
        async with self._lock:
            return self.devices.get(device_id)
    
    async def get_all_devices(
        self,
        status: Optional[DeviceStatus] = None,
        device_type: Optional[DeviceType] = None
    ) -> List[DeviceInfo]:
        """Get all devices with optional filtering"""
        async with self._lock:
            devices = list(self.devices.values())
            
            if status is not None:
                devices = [d for d in devices if d.status == status]
            
            if device_type is not None:
                devices = [d for d in devices if d.device_type == device_type]
            
            return devices
    
    async def discover_devices(
        self,
        capability: Optional[str] = None,
        min_health_score: float = 0.0,
        groups: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        max_results: int = 100
    ) -> List[DeviceInfo]:
        """
        Discover available devices
        
        Args:
            capability: Required capability
            min_health_score: Minimum health score
            groups: Required groups
            tags: Required tags
            max_results: Maximum results to return
            
        Returns:
            List of matching devices
        """
        async with self._lock:
            candidates = set(self.devices.keys())
            
            # Filter by groups
            if groups:
                group_devices = set()
                for group in groups:
                    group_devices.update(self.groups.get(group, set()))
                candidates = candidates & group_devices
            
            # Filter by tags
            if tags:
                tag_devices = set()
                for tag in tags:
                    tag_devices.update(self.tags.get(tag, set()))
                candidates = candidates & tag_devices
            
            # Get device info and apply additional filters
            results = []
            for device_id in candidates:
                device = self.devices.get(device_id)
                health = self.health_records.get(device_id)
                
                if not device or device.status == DeviceStatus.OFFLINE:
                    continue
                
                # Check health score
                if health and health.health_score < min_health_score:
                    continue
                
                # Check capability
                if capability:
                    caps = device.capabilities
                    if capability == 'gpu' and not caps.gpu_available:
                        continue
                    if capability == 'screen' and not caps.supports_screen:
                        continue
                    if capability == 'camera' and not caps.supports_camera:
                        continue
                
                results.append(device)
                
                if len(results) >= max_results:
                    break
            
            # Sort by health score (descending)
            results.sort(
                key=lambda d: self.health_records.get(d.device_id, DeviceHealthRecord(d.device_id)).health_score,
                reverse=True
            )
            
            return results
    
    async def get_devices_by_group(self, group: str) -> List[DeviceInfo]:
        """Get devices by group"""
        async with self._lock:
            device_ids = self.groups.get(group, set())
            return [self.devices[did] for did in device_ids if did in self.devices]
    
    async def get_devices_by_tag(self, tag: str) -> List[DeviceInfo]:
        """Get devices by tag"""
        async with self._lock:
            device_ids = self.tags.get(tag, set())
            return [self.devices[did] for did in device_ids if did in self.devices]
    
    async def update_device(
        self,
        device_id: str,
        request: DeviceUpdateRequest
    ) -> Optional[DeviceInfo]:
        """Update device information"""
        async with self._lock:
            device = self.devices.get(device_id)
            if not device:
                return None
            
            if request.device_name:
                device.device_name = request.device_name
            if request.capabilities:
                device.capabilities = DeviceCapabilities(**request.capabilities)
            if request.tags is not None:
                # Update tags
                for tag in device.tags:
                    self.tags[tag].discard(device_id)
                device.tags = request.tags
                for tag in request.tags:
                    self.tags[tag].add(device_id)
            if request.groups is not None:
                # Update groups
                for group in device.groups:
                    self.groups[group].discard(device_id)
                device.groups = request.groups
                for group in request.groups:
                    self.groups[group].add(device_id)
            if request.metadata:
                device.metadata.update(request.metadata)
            
            return device
    
    async def get_device_health(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Get device health metrics"""
        async with self._lock:
            health = self.health_records.get(device_id)
            if health:
                return health.to_dict()
            return None
    
    async def get_all_health_metrics(self) -> List[Dict[str, Any]]:
        """Get health metrics for all devices"""
        async with self._lock:
            return [h.to_dict() for h in self.health_records.values()]
    
    async def get_statistics(self) -> Dict[str, Any]:
        """Get device statistics"""
        async with self._lock:
            total = len(self.devices)
            online = sum(1 for d in self.devices.values() if d.status == DeviceStatus.ONLINE)
            offline = sum(1 for d in self.devices.values() if d.status == DeviceStatus.OFFLINE)
            busy = sum(1 for d in self.devices.values() if d.status == DeviceStatus.BUSY)
            error = sum(1 for d in self.devices.values() if d.status == DeviceStatus.ERROR)
            
            by_type = defaultdict(int)
            for d in self.devices.values():
                by_type[d.device_type.name] += 1
            
            avg_health = 0.0
            if self.health_records:
                avg_health = sum(h.health_score for h in self.health_records.values()) / len(self.health_records)
            
            return {
                'total_devices': total,
                'online': online,
                'offline': offline,
                'busy': busy,
                'error': error,
                'by_type': dict(by_type),
                'average_health_score': round(avg_health, 2),
                'group_count': len(self.groups),
                'tag_count': len(self.tags)
            }


# ============================================================================
# FastAPI Application
# ============================================================================

def create_app(device_manager: Optional[DeviceManager] = None) -> FastAPI:
    """Create FastAPI application"""
    
    app = FastAPI(
        title="UFO Galaxy Device Manager",
        description="Multi-device coordination system for UFO Galaxy v5.0",
        version="5.0.0"
    )
    
    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"]
    )
    
    # Device manager instance
    manager = device_manager or DeviceManager()
    
    @app.on_event("startup")
    async def startup():
        await manager.start()
    
    @app.on_event("shutdown")
    async def shutdown():
        await manager.stop()
    
    @app.post("/devices/register", response_model=DeviceResponse)
    async def register_device(request: DeviceRegistrationRequest):
        """Register a new device"""
        device = await manager.register_device(request)
        health = await manager.get_device_health(device.device_id)
        return DeviceResponse(
            device_id=device.device_id,
            device_type=device.device_type.value,
            device_name=device.device_name,
            device_model=device.device_model,
            os_version=device.os_version,
            app_version=device.app_version,
            ip_address=device.ip_address,
            port=device.port,
            status=device.status.value,
            tags=device.tags,
            groups=device.groups,
            registered_at=device.registered_at,
            last_heartbeat=device.last_heartbeat,
            health_score=health['health_score'] if health else 100.0
        )
    
    @app.post("/devices/unregister/{device_id}")
    async def unregister_device(device_id: str):
        """Unregister a device"""
        success = await manager.unregister_device(device_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"Device {device_id} not found")
        return {"success": True, "message": f"Device {device_id} unregistered"}
    
    @app.get("/devices", response_model=DeviceListResponse)
    async def list_devices(
        status: Optional[int] = None,
        device_type: Optional[int] = None
    ):
        """List all devices"""
        status_enum = DeviceStatus(status) if status is not None else None
        type_enum = DeviceType(device_type) if device_type is not None else None
        
        devices = await manager.get_all_devices(status_enum, type_enum)
        
        online_count = sum(1 for d in devices if d.status == DeviceStatus.ONLINE)
        offline_count = sum(1 for d in devices if d.status == DeviceStatus.OFFLINE)
        
        device_responses = []
        for device in devices:
            health = await manager.get_device_health(device.device_id)
            device_responses.append(DeviceResponse(
                device_id=device.device_id,
                device_type=device.device_type.value,
                device_name=device.device_name,
                device_model=device.device_model,
                os_version=device.os_version,
                app_version=device.app_version,
                ip_address=device.ip_address,
                port=device.port,
                status=device.status.value,
                tags=device.tags,
                groups=device.groups,
                registered_at=device.registered_at,
                last_heartbeat=device.last_heartbeat,
                health_score=health['health_score'] if health else 100.0
            ))
        
        return DeviceListResponse(
            devices=device_responses,
            total=len(devices),
            online_count=online_count,
            offline_count=offline_count
        )
    
    @app.get("/devices/{device_id}", response_model=DeviceResponse)
    async def get_device(device_id: str):
        """Get device details"""
        device = await manager.get_device(device_id)
        if not device:
            raise HTTPException(status_code=404, detail=f"Device {device_id} not found")
        
        health = await manager.get_device_health(device_id)
        return DeviceResponse(
            device_id=device.device_id,
            device_type=device.device_type.value,
            device_name=device.device_name,
            device_model=device.device_model,
            os_version=device.os_version,
            app_version=device.app_version,
            ip_address=device.ip_address,
            port=device.port,
            status=device.status.value,
            tags=device.tags,
            groups=device.groups,
            registered_at=device.registered_at,
            last_heartbeat=device.last_heartbeat,
            health_score=health['health_score'] if health else 100.0
        )
    
    @app.post("/devices/{device_id}/heartbeat")
    async def device_heartbeat(device_id: str, request: DeviceHeartbeatRequest):
        """Process device heartbeat"""
        if request.device_id != device_id:
            raise HTTPException(status_code=400, detail="Device ID mismatch")
        return await manager.process_heartbeat(request)
    
    @app.get("/devices/discover")
    async def discover_devices(
        capability: Optional[str] = None,
        min_health_score: float = 0.0,
        groups: Optional[str] = None,
        tags: Optional[str] = None,
        max_results: int = 100
    ):
        """Discover available devices"""
        group_list = groups.split(',') if groups else None
        tag_list = tags.split(',') if tags else None
        
        devices = await manager.discover_devices(
            capability=capability,
            min_health_score=min_health_score,
            groups=group_list,
            tags=tag_list,
            max_results=max_results
        )
        
        return {
            'devices': [d.to_dict() for d in devices],
            'count': len(devices)
        }
    
    @app.get("/devices/groups/{group}")
    async def get_devices_by_group(group: str):
        """Get devices by group"""
        devices = await manager.get_devices_by_group(group)
        return {
            'group': group,
            'devices': [d.to_dict() for d in devices],
            'count': len(devices)
        }
    
    @app.get("/devices/tags/{tag}")
    async def get_devices_by_tag(tag: str):
        """Get devices by tag"""
        devices = await manager.get_devices_by_tag(tag)
        return {
            'tag': tag,
            'devices': [d.to_dict() for d in devices],
            'count': len(devices)
        }
    
    @app.patch("/devices/{device_id}")
    async def update_device(device_id: str, request: DeviceUpdateRequest):
        """Update device information"""
        device = await manager.update_device(device_id, request)
        if not device:
            raise HTTPException(status_code=404, detail=f"Device {device_id} not found")
        return device.to_dict()
    
    @app.get("/devices/{device_id}/health")
    async def get_device_health(device_id: str):
        """Get device health metrics"""
        health = await manager.get_device_health(device_id)
        if not health:
            raise HTTPException(status_code=404, detail=f"Device {device_id} not found")
        return health
    
    @app.get("/health")
    async def get_all_health():
        """Get all device health metrics"""
        return await manager.get_all_health_metrics()
    
    @app.get("/statistics")
    async def get_statistics():
        """Get device statistics"""
        return await manager.get_statistics()
    
    @app.get("/")
    async def root():
        """Root endpoint"""
        return {
            "service": "UFO Galaxy Device Manager",
            "version": "5.0.0",
            "port": 8056,
            "endpoints": [
                "/devices/register",
                "/devices/unregister/{device_id}",
                "/devices",
                "/devices/{device_id}",
                "/devices/{device_id}/heartbeat",
                "/devices/discover",
                "/devices/groups/{group}",
                "/devices/tags/{tag}",
                "/devices/{device_id}/health",
                "/health",
                "/statistics"
            ]
        }
    
    return app


# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    app = create_app()
    uvicorn.run(app, host="0.0.0.0", port=8056, log_level="info")
