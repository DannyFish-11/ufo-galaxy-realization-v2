"""
UFO Galaxy v5.0 - Device Coordinator Module
WebSocket-based Real-time Coordination System

This module provides WebSocket server for real-time device coordination,
AIP v2.0 protocol implementation, message routing, and session management.

Features:
- WebSocket server for real-time communication
- AIP v2.0 protocol implementation
- Message routing and broadcasting
- Session management with authentication
- Support for 500+ TPS
- Cross-platform device support

FastAPI Endpoints:
- WS /ws - WebSocket endpoint for device communication
- POST /broadcast - Broadcast message to all devices
- POST /send/{device_id} - Send message to specific device
- GET /sessions - List active sessions
- GET /sessions/{session_id} - Get session details

Author: UFO Galaxy Team
Version: 5.0.0
Port: 8055
"""

import asyncio
import time
import uuid
import json
import logging
from typing import Dict, List, Optional, Set, Any, Callable, Union
from dataclasses import dataclass, field
from datetime import datetime
from collections import defaultdict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

from device_protocol import (
    AIPMessage, MessageType, DeviceInfo, DeviceStatus, ErrorCode,
    MessageBuilder, ProtocolValidator, ProtocolHandler, MessageRouter
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

class BroadcastRequest(BaseModel):
    """Broadcast message request"""
    msg_type: int
    payload: Dict[str, Any]
    exclude_devices: Optional[List[str]] = None
    require_ack: bool = False
    timeout: float = 5.0


class SendRequest(BaseModel):
    """Send message request"""
    msg_type: int
    payload: Dict[str, Any]
    require_ack: bool = True
    timeout: float = 5.0


class SessionInfo(BaseModel):
    """Session information"""
    session_id: str
    device_id: Optional[str]
    connected_at: float
    last_activity: float
    message_count: int
    ip_address: Optional[str]
    is_authenticated: bool


class CoordinatorStats(BaseModel):
    """Coordinator statistics"""
    total_sessions: int
    authenticated_sessions: int
    total_messages_sent: int
    total_messages_received: int
    messages_per_second: float
    active_devices: int


# ============================================================================
# Session Management
# ============================================================================

@dataclass
class DeviceSession:
    """Device WebSocket session"""
    session_id: str
    websocket: WebSocket
    connected_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    device_id: Optional[str] = None
    device_info: Optional[DeviceInfo] = None
    is_authenticated: bool = False
    message_count: int = 0
    ip_address: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    pending_acks: Dict[str, asyncio.Future] = field(default_factory=dict)
    
    def update_activity(self) -> None:
        """Update last activity timestamp"""
        self.last_activity = time.time()
        self.message_count += 1
    
    async def send_message(self, message: AIPMessage, require_ack: bool = False, timeout: float = 5.0) -> bool:
        """Send message to device"""
        try:
            if require_ack:
                ack_future = asyncio.Future()
                self.pending_acks[message.correlation_id or str(uuid.uuid4())] = ack_future
            
            await self.websocket.send_bytes(message.to_bytes())
            self.update_activity()
            
            if require_ack:
                try:
                    await asyncio.wait_for(ack_future, timeout=timeout)
                    return True
                except asyncio.TimeoutError:
                    logger.warning(f"Ack timeout for message to {self.device_id}")
                    return False
            
            return True
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            return False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'session_id': self.session_id,
            'device_id': self.device_id,
            'connected_at': self.connected_at,
            'last_activity': self.last_activity,
            'message_count': self.message_count,
            'ip_address': self.ip_address,
            'is_authenticated': self.is_authenticated
        }


class SessionManager:
    """Manages device WebSocket sessions"""
    
    def __init__(self, session_timeout: float = 300.0):
        self.sessions: Dict[str, DeviceSession] = {}
        self.device_sessions: Dict[str, str] = {}  # device_id -> session_id
        self.session_timeout = session_timeout
        self._lock = asyncio.Lock()
        self._callbacks: Dict[str, List[Callable]] = defaultdict(list)
        
        logger.info("SessionManager initialized")
    
    def register_callback(self, event: str, callback: Callable) -> None:
        """Register event callback"""
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
    
    async def create_session(self, websocket: WebSocket, ip_address: Optional[str] = None) -> DeviceSession:
        """Create new session"""
        session_id = str(uuid.uuid4())
        session = DeviceSession(
            session_id=session_id,
            websocket=websocket,
            ip_address=ip_address
        )
        
        async with self._lock:
            self.sessions[session_id] = session
        
        logger.info(f"Session created: {session_id}")
        await self._notify('session_created', session)
        
        return session
    
    async def remove_session(self, session_id: str) -> Optional[DeviceSession]:
        """Remove session"""
        async with self._lock:
            session = self.sessions.pop(session_id, None)
            if session:
                if session.device_id:
                    self.device_sessions.pop(session.device_id, None)
                logger.info(f"Session removed: {session_id}")
        
        if session:
            await self._notify('session_removed', session)
        
        return session
    
    async def authenticate_session(
        self,
        session_id: str,
        device_id: str,
        device_info: Optional[DeviceInfo] = None
    ) -> bool:
        """Authenticate session with device"""
        async with self._lock:
            session = self.sessions.get(session_id)
            if not session:
                return False
            
            # Remove old session for this device if exists
            old_session_id = self.device_sessions.get(device_id)
            if old_session_id and old_session_id != session_id:
                old_session = self.sessions.pop(old_session_id, None)
                if old_session:
                    logger.info(f"Replaced old session {old_session_id} for device {device_id}")
            
            session.device_id = device_id
            session.device_info = device_info
            session.is_authenticated = True
            self.device_sessions[device_id] = session_id
        
        logger.info(f"Session {session_id} authenticated for device {device_id}")
        await self._notify('session_authenticated', session)
        return True
    
    async def get_session(self, session_id: str) -> Optional[DeviceSession]:
        """Get session by ID"""
        return self.sessions.get(session_id)
    
    async def get_session_by_device(self, device_id: str) -> Optional[DeviceSession]:
        """Get session by device ID"""
        session_id = self.device_sessions.get(device_id)
        if session_id:
            return self.sessions.get(session_id)
        return None
    
    async def get_all_sessions(self) -> List[DeviceSession]:
        """Get all sessions"""
        return list(self.sessions.values())
    
    async def get_authenticated_sessions(self) -> List[DeviceSession]:
        """Get authenticated sessions"""
        return [s for s in self.sessions.values() if s.is_authenticated]
    
    async def send_to_device(
        self,
        device_id: str,
        message: AIPMessage,
        require_ack: bool = False,
        timeout: float = 5.0
    ) -> bool:
        """Send message to specific device"""
        session = await self.get_session_by_device(device_id)
        if not session:
            logger.warning(f"No session found for device {device_id}")
            return False
        
        return await session.send_message(message, require_ack, timeout)
    
    async def broadcast(
        self,
        message: AIPMessage,
        exclude_devices: Optional[List[str]] = None,
        require_ack: bool = False,
        timeout: float = 5.0
    ) -> Dict[str, bool]:
        """Broadcast message to all devices"""
        exclude = set(exclude_devices or [])
        results = {}
        
        sessions = await self.get_authenticated_sessions()
        
        # Create tasks for concurrent sending
        tasks = []
        for session in sessions:
            if session.device_id and session.device_id not in exclude:
                task = self._send_with_result(session, message, require_ack, timeout)
                tasks.append((session.device_id, task))
        
        # Wait for all sends to complete
        for device_id, task in tasks:
            try:
                results[device_id] = await task
            except Exception as e:
                logger.error(f"Broadcast error to {device_id}: {e}")
                results[device_id] = False
        
        return results
    
    async def _send_with_result(
        self,
        session: DeviceSession,
        message: AIPMessage,
        require_ack: bool,
        timeout: float
    ) -> bool:
        """Send message and return result"""
        return await session.send_message(message, require_ack, timeout)
    
    async def cleanup_stale_sessions(self) -> int:
        """Remove stale sessions"""
        current_time = time.time()
        stale_sessions = []
        
        async with self._lock:
            for session_id, session in self.sessions.items():
                if current_time - session.last_activity > self.session_timeout:
                    stale_sessions.append(session_id)
            
            for session_id in stale_sessions:
                session = self.sessions.pop(session_id, None)
                if session and session.device_id:
                    self.device_sessions.pop(session.device_id, None)
        
        for session_id in stale_sessions:
            logger.info(f"Cleaned up stale session: {session_id}")
            await self._notify('session_stale_removed', session_id)
        
        return len(stale_sessions)
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get session statistics"""
        total = len(self.sessions)
        authenticated = sum(1 for s in self.sessions.values() if s.is_authenticated)
        total_messages = sum(s.message_count for s in self.sessions.values())
        
        return {
            'total_sessions': total,
            'authenticated_sessions': authenticated,
            'total_messages': total_messages,
            'active_devices': len(self.device_sessions)
        }


# ============================================================================
# Message Handlers
# ============================================================================

class DeviceRegistrationHandler(ProtocolHandler):
    """Handle device registration messages"""
    
    def __init__(self, session_manager: SessionManager, coordinator: 'DeviceCoordinator'):
        self.session_manager = session_manager
        self.coordinator = coordinator
    
    async def handle_message(self, message: AIPMessage) -> Optional[AIPMessage]:
        """Handle device registration"""
        payload = message.payload
        device_id = payload.get('device_id')
        
        if not device_id:
            return await self.handle_error(
                ValueError("Missing device_id"),
                message
            )
        
        # Authenticate session
        session_id = message.source_device
        if session_id:
            await self.session_manager.authenticate_session(
                session_id=session_id,
                device_id=device_id,
                device_info=DeviceInfo.from_dict(payload) if 'device_type' in payload else None
            )
        
        # Send acknowledgment
        return await MessageBuilder.build_register(
            DeviceInfo.from_dict(payload),
            source_device="coordinator"
        )
    
    async def handle_error(self, error: Exception, message: Optional[AIPMessage] = None) -> AIPMessage:
        """Handle registration error"""
        return await MessageBuilder.build_error(
            ErrorCode.INVALID_MESSAGE,
            str(error),
            MessageType.DEVICE_REGISTER if message else None,
            source_device="coordinator"
        )


class HeartbeatHandler(ProtocolHandler):
    """Handle heartbeat messages"""
    
    def __init__(self, session_manager: SessionManager, coordinator: 'DeviceCoordinator'):
        self.session_manager = session_manager
        self.coordinator = coordinator
    
    async def handle_message(self, message: AIPMessage) -> Optional[AIPMessage]:
        """Handle heartbeat"""
        payload = message.payload
        device_id = payload.get('device_id')
        
        if device_id:
            session = await self.session_manager.get_session_by_device(device_id)
            if session:
                session.update_activity()
        
        # Return heartbeat acknowledgment
        return await MessageBuilder.build_heartbeat(
            device_id or "unknown",
            DeviceStatus.ONLINE,
            source_device="coordinator"
        )
    
    async def handle_error(self, error: Exception, message: Optional[AIPMessage] = None) -> AIPMessage:
        """Handle heartbeat error"""
        return await MessageBuilder.build_error(
            ErrorCode.INTERNAL_ERROR,
            str(error),
            MessageType.DEVICE_HEARTBEAT if message else None,
            source_device="coordinator"
        )


class TaskHandler(ProtocolHandler):
    """Handle task-related messages"""
    
    def __init__(self, session_manager: SessionManager, coordinator: 'DeviceCoordinator'):
        self.session_manager = session_manager
        self.coordinator = coordinator
    
    async def handle_message(self, message: AIPMessage) -> Optional[AIPMessage]:
        """Handle task message"""
        # Forward to scheduler
        if self.coordinator.scheduler_callback:
            await self.coordinator.scheduler_callback(message)
        
        return None
    
    async def handle_error(self, error: Exception, message: Optional[AIPMessage] = None) -> AIPMessage:
        """Handle task error"""
        return await MessageBuilder.build_error(
            ErrorCode.INTERNAL_ERROR,
            str(error),
            message.msg_type if message else None,
            source_device="coordinator"
        )


# ============================================================================
# Device Coordinator
# ============================================================================

class DeviceCoordinator:
    """
    Device Coordinator for UFO Galaxy
    
    Manages WebSocket connections, message routing, and coordination
    between devices using AIP v2.0 protocol.
    """
    
    def __init__(
        self,
        session_timeout: float = 300.0,
        cleanup_interval: float = 60.0
    ):
        self.session_manager = SessionManager(session_timeout)
        self.message_router = MessageRouter()
        self.cleanup_interval = cleanup_interval
        
        self.scheduler_callback: Optional[Callable] = None
        self._running = False
        self._cleanup_task: Optional[asyncio.Task] = None
        
        # Statistics
        self._messages_sent = 0
        self._messages_received = 0
        self._start_time = time.time()
        
        # Setup message handlers
        self._setup_handlers()
        
        logger.info("DeviceCoordinator initialized")
    
    def _setup_handlers(self) -> None:
        """Setup message handlers"""
        self.message_router.register_handler(
            MessageType.DEVICE_REGISTER,
            DeviceRegistrationHandler(self.session_manager, self)
        )
        self.message_router.register_handler(
            MessageType.DEVICE_HEARTBEAT,
            HeartbeatHandler(self.session_manager, self)
        )
        self.message_router.register_handler(
            MessageType.TASK_SUBMIT,
            TaskHandler(self.session_manager, self)
        )
        self.message_router.register_handler(
            MessageType.TASK_RESULT,
            TaskHandler(self.session_manager, self)
        )
    
    def set_scheduler_callback(self, callback: Callable) -> None:
        """Set callback for scheduler integration"""
        self.scheduler_callback = callback
    
    async def start(self) -> None:
        """Start coordinator"""
        self._running = True
        self._start_time = time.time()
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("DeviceCoordinator started")
    
    async def stop(self) -> None:
        """Stop coordinator"""
        self._running = False
        
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        logger.info("DeviceCoordinator stopped")
    
    async def _cleanup_loop(self) -> None:
        """Periodic cleanup loop"""
        while self._running:
            try:
                await asyncio.sleep(self.cleanup_interval)
                count = await self.session_manager.cleanup_stale_sessions()
                if count > 0:
                    logger.info(f"Cleaned up {count} stale sessions")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Cleanup error: {e}")
    
    async def handle_websocket(self, websocket: WebSocket, ip_address: Optional[str] = None) -> None:
        """Handle WebSocket connection"""
        await websocket.accept()
        
        # Create session
        session = await self.session_manager.create_session(websocket, ip_address)
        
        try:
            while True:
                # Receive message
                data = await websocket.receive_bytes()
                self._messages_received += 1
                
                try:
                    # Parse message
                    message = AIPMessage.from_bytes(data)
                    message.source_device = session.session_id
                    
                    # Validate message
                    valid, error = ProtocolValidator.validate_message(message)
                    if not valid:
                        error_response = await MessageBuilder.build_error(
                            ErrorCode.INVALID_MESSAGE,
                            error or "Validation failed",
                            message.msg_type,
                            source_device="coordinator"
                        )
                        await session.send_message(error_response)
                        continue
                    
                    # Route message
                    responses = await self.message_router.route(message)
                    
                    # Send responses
                    for response in responses:
                        if response:
                            await session.send_message(response)
                            self._messages_sent += 1
                
                except Exception as e:
                    logger.error(f"Message handling error: {e}")
                    error_response = await MessageBuilder.build_error(
                        ErrorCode.PROTOCOL_ERROR,
                        str(e),
                        source_device="coordinator"
                    )
                    await session.send_message(error_response)
        
        except WebSocketDisconnect:
            logger.info(f"WebSocket disconnected: {session.session_id}")
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
        finally:
            await self.session_manager.remove_session(session.session_id)
    
    async def send_to_device(
        self,
        device_id: str,
        msg_type: MessageType,
        payload: Dict[str, Any],
        require_ack: bool = True,
        timeout: float = 5.0
    ) -> bool:
        """Send message to specific device"""
        message = AIPMessage(
            msg_type=msg_type,
            payload=payload,
            source_device="coordinator"
        )
        
        result = await self.session_manager.send_to_device(
            device_id, message, require_ack, timeout
        )
        
        if result:
            self._messages_sent += 1
        
        return result
    
    async def broadcast(
        self,
        msg_type: MessageType,
        payload: Dict[str, Any],
        exclude_devices: Optional[List[str]] = None,
        require_ack: bool = False,
        timeout: float = 5.0
    ) -> Dict[str, bool]:
        """Broadcast message to all devices"""
        message = AIPMessage(
            msg_type=msg_type,
            payload=payload,
            source_device="coordinator"
        )
        
        results = await self.session_manager.broadcast(
            message, exclude_devices, require_ack, timeout
        )
        
        self._messages_sent += sum(1 for r in results.values() if r)
        
        return results
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get coordinator statistics"""
        uptime = time.time() - self._start_time
        mps = self._messages_received / uptime if uptime > 0 else 0
        
        session_stats = self.session_manager.get_statistics()
        
        return {
            **session_stats,
            'total_messages_sent': self._messages_sent,
            'total_messages_received': self._messages_received,
            'messages_per_second': round(mps, 2),
            'uptime_seconds': round(uptime, 2)
        }


# ============================================================================
# FastAPI Application
# ============================================================================

def create_app(coordinator: Optional[DeviceCoordinator] = None) -> FastAPI:
    """Create FastAPI application"""
    
    app = FastAPI(
        title="UFO Galaxy Device Coordinator",
        description="WebSocket-based real-time coordination system for UFO Galaxy v5.0",
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
    
    # Coordinator instance
    coord = coordinator or DeviceCoordinator()
    
    @app.on_event("startup")
    async def startup():
        await coord.start()
    
    @app.on_event("shutdown")
    async def shutdown():
        await coord.stop()
    
    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        """WebSocket endpoint for device communication"""
        client_host = websocket.client.host if websocket.client else None
        await coord.handle_websocket(websocket, client_host)
    
    @app.post("/broadcast")
    async def broadcast_message(request: BroadcastRequest):
        """Broadcast message to all devices"""
        results = await coord.broadcast(
            MessageType(request.msg_type),
            request.payload,
            request.exclude_devices,
            request.require_ack,
            request.timeout
        )
        return {
            'success': True,
            'results': results,
            'success_count': sum(1 for r in results.values() if r),
            'failure_count': sum(1 for r in results.values() if not r)
        }
    
    @app.post("/send/{device_id}")
    async def send_to_device(device_id: str, request: SendRequest):
        """Send message to specific device"""
        success = await coord.send_to_device(
            device_id,
            MessageType(request.msg_type),
            request.payload,
            request.require_ack,
            request.timeout
        )
        return {'success': success}
    
    @app.get("/sessions", response_model=List[SessionInfo])
    async def list_sessions():
        """List active sessions"""
        sessions = await coord.session_manager.get_all_sessions()
        return [
            SessionInfo(
                session_id=s.session_id,
                device_id=s.device_id,
                connected_at=s.connected_at,
                last_activity=s.last_activity,
                message_count=s.message_count,
                ip_address=s.ip_address,
                is_authenticated=s.is_authenticated
            )
            for s in sessions
        ]
    
    @app.get("/sessions/{session_id}")
    async def get_session(session_id: str):
        """Get session details"""
        session = await coord.session_manager.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        return session.to_dict()
    
    @app.get("/devices/{device_id}/session")
    async def get_device_session(device_id: str):
        """Get session for device"""
        session = await coord.session_manager.get_session_by_device(device_id)
        if not session:
            raise HTTPException(status_code=404, detail=f"No session for device {device_id}")
        return session.to_dict()
    
    @app.post("/devices/{device_id}/disconnect")
    async def disconnect_device(device_id: str):
        """Disconnect a device"""
        session = await coord.session_manager.get_session_by_device(device_id)
        if not session:
            raise HTTPException(status_code=404, detail=f"No session for device {device_id}")
        
        await coord.session_manager.remove_session(session.session_id)
        return {'success': True, 'message': f'Device {device_id} disconnected'}
    
    @app.get("/statistics", response_model=CoordinatorStats)
    async def get_statistics():
        """Get coordinator statistics"""
        stats = coord.get_statistics()
        return CoordinatorStats(
            total_sessions=stats['total_sessions'],
            authenticated_sessions=stats['authenticated_sessions'],
            total_messages_sent=stats['total_messages_sent'],
            total_messages_received=stats['total_messages_received'],
            messages_per_second=stats['messages_per_second'],
            active_devices=stats['active_devices']
        )
    
    @app.get("/")
    async def root():
        """Root endpoint"""
        return {
            "service": "UFO Galaxy Device Coordinator",
            "version": "5.0.0",
            "port": 8055,
            "websocket_endpoint": "/ws",
            "endpoints": [
                "/broadcast",
                "/send/{device_id}",
                "/sessions",
                "/sessions/{session_id}",
                "/devices/{device_id}/session",
                "/devices/{device_id}/disconnect",
                "/statistics"
            ]
        }
    
    return app


# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    app = create_app()
    uvicorn.run(app, host="0.0.0.0", port=8055, log_level="info")
