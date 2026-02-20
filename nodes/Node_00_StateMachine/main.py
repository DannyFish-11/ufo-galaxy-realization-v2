"""
Node 00: Global State Machine
UFO Galaxy 64-Core MCP Matrix - DeepSeek Audited Architecture

This is the central nervous system of UFO Galaxy.
All global state MUST sync through this node.
"""

import os
import json
import asyncio
import logging
import uuid
from typing import Dict, Optional, List, Any
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from enum import Enum

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

# Optional Redis import
try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

# =============================================================================
# Configuration
# =============================================================================

NODE_ID = os.getenv("NODE_ID", "00")
NODE_NAME = os.getenv("NODE_NAME", "StateMachine")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
USE_MEMORY_STORE = os.getenv("USE_MEMORY_STORE", "true").lower() == "true"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format=f"[Node {NODE_ID}] %(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# =============================================================================
# Models
# =============================================================================

class LockRequest(BaseModel):
    node_id: str = Field(..., description="ID of the requesting node")
    resource_id: str = Field(..., description="ID of the resource to lock")
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    reason: str = Field(default="", description="Reason for lock")

class LockResponse(BaseModel):
    success: bool
    token: Optional[str] = None
    message: str
    expires_at: Optional[str] = None

class ReleaseRequest(BaseModel):
    node_id: str
    resource_id: str
    token: str

class NodeRegistration(BaseModel):
    node_id: str
    node_name: str
    layer: str
    ip_address: str = ""
    capabilities: List[str] = []

class NodeStatus(BaseModel):
    node_id: str
    node_name: str
    status: str
    last_heartbeat: str
    layer: str

# =============================================================================
# In-Memory Store
# =============================================================================

class MemoryStore:
    """Thread-safe in-memory store for locks and state."""
    
    def __init__(self):
        self.locks: Dict[str, Dict] = {}
        self.nodes: Dict[str, Dict] = {}
        self.state: Dict[str, Any] = {}
        self._lock = asyncio.Lock()
    
    async def acquire_lock(self, resource_id: str, node_id: str, timeout_seconds: int) -> Optional[str]:
        """Acquire a lock on a resource."""
        async with self._lock:
            now = datetime.now()
            
            # Check existing lock
            if resource_id in self.locks:
                existing = self.locks[resource_id]
                expires_at = datetime.fromisoformat(existing["expires_at"])
                
                if expires_at > now:
                    # Lock still valid
                    return None
            
            # Create new lock
            token = str(uuid.uuid4())
            expires_at = now + timedelta(seconds=timeout_seconds)
            
            self.locks[resource_id] = {
                "token": token,
                "node_id": node_id,
                "expires_at": expires_at.isoformat(),
                "acquired_at": now.isoformat()
            }
            
            return token
    
    async def release_lock(self, resource_id: str, token: str) -> bool:
        """Release a lock."""
        async with self._lock:
            if resource_id not in self.locks:
                return False
            
            if self.locks[resource_id]["token"] != token:
                return False
            
            del self.locks[resource_id]
            return True
    
    async def get_locks(self) -> Dict[str, Dict]:
        """Get all active locks."""
        async with self._lock:
            now = datetime.now()
            active = {}
            
            for resource_id, lock in list(self.locks.items()):
                expires_at = datetime.fromisoformat(lock["expires_at"])
                if expires_at > now:
                    active[resource_id] = lock
                else:
                    del self.locks[resource_id]
            
            return active
    
    async def register_node(self, registration: NodeRegistration):
        """Register a node."""
        async with self._lock:
            self.nodes[registration.node_id] = {
                "node_id": registration.node_id,
                "node_name": registration.node_name,
                "layer": registration.layer,
                "ip_address": registration.ip_address,
                "capabilities": registration.capabilities,
                "status": "online",
                "last_heartbeat": datetime.now().isoformat()
            }
    
    async def get_nodes(self) -> Dict[str, Dict]:
        """Get all registered nodes."""
        async with self._lock:
            return dict(self.nodes)
    
    async def heartbeat(self, node_id: str) -> bool:
        """Update node heartbeat."""
        async with self._lock:
            if node_id in self.nodes:
                self.nodes[node_id]["last_heartbeat"] = datetime.now().isoformat()
                self.nodes[node_id]["status"] = "online"
                return True
            return False
    
    async def set_state(self, key: str, value: Any):
        """Set a state value."""
        async with self._lock:
            self.state[key] = value
    
    async def get_state(self, key: str) -> Any:
        """Get a state value."""
        async with self._lock:
            return self.state.get(key)

# =============================================================================
# FastAPI Application
# =============================================================================

store: Optional[MemoryStore] = None
redis_client = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global store, redis_client
    
    logger.info(f"Starting Node {NODE_ID}: {NODE_NAME}")
    
    # Initialize store
    use_memory = USE_MEMORY_STORE or not REDIS_AVAILABLE
    
    if not use_memory:
        try:
            redis_client = redis.from_url(REDIS_URL, decode_responses=True)
            await redis_client.ping()
            logger.info("Connected to Redis")
        except Exception as e:
            logger.warning(f"Redis not available ({e}), using memory store")
            redis_client = None
            use_memory = True
    
    if use_memory:
        logger.info("Using in-memory store")
        store = MemoryStore()
    
    # Register self
    await store.register_node(NodeRegistration(
        node_id=NODE_ID,
        node_name=NODE_NAME,
        layer="L0_KERNEL",
        ip_address="10.88.0.10",
        capabilities=["lock_management", "node_registry", "health_monitoring"]
    ))
    
    logger.info(f"Node {NODE_ID} ({NODE_NAME}) is ready")
    
    yield
    
    logger.info(f"Shutting down Node {NODE_ID}")
    if redis_client:
        await redis_client.close()

app = FastAPI(
    title=f"UFO Galaxy Node {NODE_ID}: {NODE_NAME}",
    description="Global State Machine - The Heart of UFO Galaxy",
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
    return {
        "status": "healthy",
        "node_id": NODE_ID,
        "node_name": NODE_NAME,
        "store_type": "redis" if redis_client else "memory"
    }

@app.post("/lock/acquire", response_model=LockResponse)
async def acquire_lock(request: LockRequest):
    """Acquire a lock on a resource."""
    token = await store.acquire_lock(
        resource_id=request.resource_id,
        node_id=request.node_id,
        timeout_seconds=request.timeout_seconds
    )
    
    if token:
        expires_at = datetime.now() + timedelta(seconds=request.timeout_seconds)
        logger.info(f"Lock acquired: {request.resource_id} by {request.node_id}")
        return LockResponse(
            success=True,
            token=token,
            message="Lock acquired",
            expires_at=expires_at.isoformat()
        )
    else:
        logger.warning(f"Lock denied: {request.resource_id} for {request.node_id}")
        return LockResponse(
            success=False,
            message="Resource is locked by another node"
        )

@app.post("/lock/release", response_model=LockResponse)
async def release_lock(request: ReleaseRequest):
    """Release a lock."""
    success = await store.release_lock(request.resource_id, request.token)
    
    if success:
        logger.info(f"Lock released: {request.resource_id}")
        return LockResponse(success=True, message="Lock released")
    else:
        return LockResponse(success=False, message="Invalid lock or token")

@app.get("/locks")
async def get_locks():
    """Get all active locks."""
    locks = await store.get_locks()
    return {"locks": locks, "count": len(locks)}

@app.post("/node/register")
async def register_node(registration: NodeRegistration):
    """Register a node."""
    await store.register_node(registration)
    logger.info(f"Node registered: {registration.node_id} ({registration.node_name})")
    return {"success": True, "message": f"Node {registration.node_id} registered"}

@app.post("/node/heartbeat/{node_id}")
async def heartbeat(node_id: str):
    """Update node heartbeat."""
    success = await store.heartbeat(node_id)
    return {"success": success}

@app.get("/nodes")
async def get_nodes():
    """Get all registered nodes."""
    nodes = await store.get_nodes()
    return {"nodes": nodes, "count": len(nodes)}

@app.get("/state/{key}")
async def get_state(key: str):
    """Get a state value."""
    value = await store.get_state(key)
    return {"key": key, "value": value}

@app.post("/state/{key}")
async def set_state(key: str, value: Any):
    """Set a state value."""
    await store.set_state(key, value)
    return {"success": True}

@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "node_id": NODE_ID,
        "node_name": NODE_NAME,
        "layer": "L0_KERNEL",
        "status": "running",
        "role": "Global State Machine - Central nervous system of UFO Galaxy"
    }

# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level=LOG_LEVEL.lower()
    )
