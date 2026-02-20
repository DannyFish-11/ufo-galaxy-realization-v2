"""
Node 69: Backup & Disaster Recovery System
UFO Galaxy 64-Core MCP Matrix - Phase 6: Immune System

Automated backup with versioning and point-in-time recovery.
"""

import os
import json
import asyncio
import logging
import time
import hashlib
import gzip
import shutil
from typing import Dict, Optional, List, Any
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from enum import Enum
from dataclasses import dataclass, field
from pathlib import Path
import sqlite3

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn
import httpx

# =============================================================================
# Configuration
# =============================================================================

NODE_ID = os.getenv("NODE_ID", "69")
NODE_NAME = os.getenv("NODE_NAME", "BackupRestore")
STATE_MACHINE_URL = os.getenv("STATE_MACHINE_URL", "http://localhost:8000")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
BACKUP_DIR = os.getenv("BACKUP_DIR", os.path.join(os.path.dirname(__file__), "backups"))

# Backup configuration
MAX_BACKUPS = 10
BACKUP_INTERVAL_HOURS = 6
COMPRESSION_ENABLED = True

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format=f"[Node {NODE_ID}] %(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# =============================================================================
# Models
# =============================================================================

class BackupType(str, Enum):
    FULL = "full"
    INCREMENTAL = "incremental"
    SNAPSHOT = "snapshot"

class BackupStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CORRUPTED = "corrupted"

class RestoreStatus(str, Enum):
    PENDING = "pending"
    VALIDATING = "validating"
    RESTORING = "restoring"
    COMPLETED = "completed"
    FAILED = "failed"

@dataclass
class BackupMetadata:
    """Backup metadata."""
    backup_id: str
    timestamp: str
    backup_type: BackupType
    status: BackupStatus
    size_bytes: int
    checksum: str
    nodes_included: List[str]
    duration_seconds: float
    compression: bool
    path: str

@dataclass
class RestorePoint:
    """Point-in-time restore point."""
    restore_id: str
    backup_id: str
    timestamp: str
    status: RestoreStatus
    target_nodes: List[str]
    duration_seconds: float = 0
    error: Optional[str] = None

class BackupRequest(BaseModel):
    backup_type: BackupType = BackupType.FULL
    nodes: Optional[List[str]] = None  # None = all nodes
    compress: bool = True
    description: str = ""

class RestoreRequest(BaseModel):
    backup_id: str
    target_nodes: Optional[List[str]] = None  # None = all nodes in backup
    validate_only: bool = False

# =============================================================================
# Backup Storage
# =============================================================================

class BackupStorage:
    """Backup storage manager."""
    
    def __init__(self, backup_dir: str):
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        
        self.db_path = self.backup_dir / "backup_registry.db"
        self._init_db()
    
    def _init_db(self):
        """Initialize backup registry database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS backups (
                    backup_id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    backup_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    size_bytes INTEGER,
                    checksum TEXT,
                    nodes_included TEXT,
                    duration_seconds REAL,
                    compression INTEGER,
                    path TEXT,
                    description TEXT,
                    created_at REAL DEFAULT (strftime('%s', 'now'))
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS restores (
                    restore_id TEXT PRIMARY KEY,
                    backup_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    status TEXT NOT NULL,
                    target_nodes TEXT,
                    duration_seconds REAL,
                    error TEXT,
                    created_at REAL DEFAULT (strftime('%s', 'now'))
                )
            """)
            
            conn.commit()
    
    def register_backup(self, metadata: BackupMetadata, description: str = ""):
        """Register a new backup."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO backups (
                    backup_id, timestamp, backup_type, status, size_bytes,
                    checksum, nodes_included, duration_seconds, compression, path, description
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                metadata.backup_id,
                metadata.timestamp,
                metadata.backup_type.value,
                metadata.status.value,
                metadata.size_bytes,
                metadata.checksum,
                json.dumps(metadata.nodes_included),
                metadata.duration_seconds,
                1 if metadata.compression else 0,
                metadata.path,
                description
            ))
            conn.commit()
    
    def update_backup_status(self, backup_id: str, status: BackupStatus, **kwargs):
        """Update backup status."""
        updates = ["status = ?"]
        params = [status.value]
        
        for key, value in kwargs.items():
            updates.append(f"{key} = ?")
            params.append(value)
        
        params.append(backup_id)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(f"""
                UPDATE backups SET {', '.join(updates)} WHERE backup_id = ?
            """, params)
            conn.commit()
    
    def get_backup(self, backup_id: str) -> Optional[Dict[str, Any]]:
        """Get backup by ID."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM backups WHERE backup_id = ?",
                (backup_id,)
            ).fetchone()
            
            if not row:
                return None
            
            return {
                "backup_id": row["backup_id"],
                "timestamp": row["timestamp"],
                "backup_type": row["backup_type"],
                "status": row["status"],
                "size_bytes": row["size_bytes"],
                "checksum": row["checksum"],
                "nodes_included": json.loads(row["nodes_included"]) if row["nodes_included"] else [],
                "duration_seconds": row["duration_seconds"],
                "compression": bool(row["compression"]),
                "path": row["path"],
                "description": row["description"]
            }
    
    def list_backups(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List all backups."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT * FROM backups ORDER BY created_at DESC LIMIT ?
            """, (limit,)).fetchall()
            
            return [
                {
                    "backup_id": row["backup_id"],
                    "timestamp": row["timestamp"],
                    "backup_type": row["backup_type"],
                    "status": row["status"],
                    "size_bytes": row["size_bytes"],
                    "nodes_included": json.loads(row["nodes_included"]) if row["nodes_included"] else [],
                    "compression": bool(row["compression"]),
                    "description": row["description"]
                }
                for row in rows
            ]
    
    def register_restore(self, restore_point: RestorePoint):
        """Register a restore operation."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO restores (
                    restore_id, backup_id, timestamp, status, target_nodes, duration_seconds, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                restore_point.restore_id,
                restore_point.backup_id,
                restore_point.timestamp,
                restore_point.status.value,
                json.dumps(restore_point.target_nodes),
                restore_point.duration_seconds,
                restore_point.error
            ))
            conn.commit()
    
    def update_restore_status(self, restore_id: str, status: RestoreStatus, **kwargs):
        """Update restore status."""
        updates = ["status = ?"]
        params = [status.value]
        
        for key, value in kwargs.items():
            updates.append(f"{key} = ?")
            params.append(value)
        
        params.append(restore_id)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(f"""
                UPDATE restores SET {', '.join(updates)} WHERE restore_id = ?
            """, params)
            conn.commit()
    
    def cleanup_old_backups(self, keep_count: int = MAX_BACKUPS):
        """Remove old backups beyond retention limit."""
        with sqlite3.connect(self.db_path) as conn:
            # Get backups to delete
            rows = conn.execute("""
                SELECT backup_id, path FROM backups
                WHERE status = 'completed'
                ORDER BY created_at DESC
                LIMIT -1 OFFSET ?
            """, (keep_count,)).fetchall()
            
            deleted = []
            for row in rows:
                backup_id, path = row
                
                # Delete file
                if path and Path(path).exists():
                    try:
                        Path(path).unlink()
                    except Exception as e:
                        logger.error(f"Failed to delete backup file {path}: {e}")
                
                # Delete from registry
                conn.execute("DELETE FROM backups WHERE backup_id = ?", (backup_id,))
                deleted.append(backup_id)
            
            conn.commit()
            return deleted

# =============================================================================
# Backup Service
# =============================================================================

class BackupService:
    """Main backup and restore service."""
    
    def __init__(self, backup_dir: str):
        self.storage = BackupStorage(backup_dir)
        self.backup_dir = Path(backup_dir)
        self.http_client = httpx.AsyncClient(timeout=30)
        
        # Known nodes and their data endpoints
        self.node_data_endpoints = {
            "Node_00_StateMachine": "http://localhost:8000/state/export",
            "Node_58_ModelRouter": "http://localhost:8058/history",
            "Node_65_LoggerCentral": "http://localhost:8065/export",
        }
    
    def _generate_backup_id(self) -> str:
        """Generate unique backup ID."""
        import uuid
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        return f"backup_{timestamp}_{uuid.uuid4().hex[:8]}"
    
    def _generate_restore_id(self) -> str:
        """Generate unique restore ID."""
        import uuid
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        return f"restore_{timestamp}_{uuid.uuid4().hex[:8]}"
    
    def _calculate_checksum(self, file_path: Path) -> str:
        """Calculate SHA256 checksum of a file."""
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()
    
    async def create_backup(self, request: BackupRequest) -> BackupMetadata:
        """Create a new backup."""
        backup_id = self._generate_backup_id()
        timestamp = datetime.utcnow().isoformat() + "Z"
        start_time = time.time()
        
        # Determine nodes to backup
        nodes = request.nodes or list(self.node_data_endpoints.keys())
        
        # Create backup metadata
        metadata = BackupMetadata(
            backup_id=backup_id,
            timestamp=timestamp,
            backup_type=request.backup_type,
            status=BackupStatus.IN_PROGRESS,
            size_bytes=0,
            checksum="",
            nodes_included=nodes,
            duration_seconds=0,
            compression=request.compress,
            path=""
        )
        
        # Register backup
        self.storage.register_backup(metadata, request.description)
        
        try:
            # Collect data from nodes
            backup_data = {
                "backup_id": backup_id,
                "timestamp": timestamp,
                "backup_type": request.backup_type.value,
                "nodes": {}
            }
            
            for node_id in nodes:
                node_data = await self._collect_node_data(node_id)
                backup_data["nodes"][node_id] = node_data
            
            # Write backup file
            backup_path = self.backup_dir / f"{backup_id}.json"
            
            if request.compress:
                backup_path = self.backup_dir / f"{backup_id}.json.gz"
                with gzip.open(backup_path, "wt", encoding="utf-8") as f:
                    json.dump(backup_data, f)
            else:
                with open(backup_path, "w") as f:
                    json.dump(backup_data, f)
            
            # Calculate checksum and size
            checksum = self._calculate_checksum(backup_path)
            size_bytes = backup_path.stat().st_size
            duration = time.time() - start_time
            
            # Update metadata
            self.storage.update_backup_status(
                backup_id,
                BackupStatus.COMPLETED,
                checksum=checksum,
                size_bytes=size_bytes,
                duration_seconds=duration,
                path=str(backup_path)
            )
            
            metadata.status = BackupStatus.COMPLETED
            metadata.checksum = checksum
            metadata.size_bytes = size_bytes
            metadata.duration_seconds = duration
            metadata.path = str(backup_path)
            
            # Cleanup old backups
            self.storage.cleanup_old_backups()
            
            return metadata
            
        except Exception as e:
            logger.error(f"Backup failed: {e}")
            self.storage.update_backup_status(backup_id, BackupStatus.FAILED)
            metadata.status = BackupStatus.FAILED
            return metadata
    
    async def _collect_node_data(self, node_id: str) -> Dict[str, Any]:
        """Collect data from a node."""
        endpoint = self.node_data_endpoints.get(node_id)
        
        if not endpoint:
            # Return mock data for nodes without export endpoints
            return {
                "status": "no_export_endpoint",
                "timestamp": datetime.utcnow().isoformat()
            }
        
        try:
            response = await self.http_client.get(endpoint)
            if response.status_code == 200:
                return response.json()
            else:
                return {
                    "status": "error",
                    "code": response.status_code
                }
        except Exception as e:
            return {
                "status": "unreachable",
                "error": str(e)
            }
    
    async def restore_backup(self, request: RestoreRequest) -> RestorePoint:
        """Restore from a backup."""
        restore_id = self._generate_restore_id()
        timestamp = datetime.utcnow().isoformat() + "Z"
        start_time = time.time()
        
        # Get backup metadata
        backup = self.storage.get_backup(request.backup_id)
        if not backup:
            raise HTTPException(status_code=404, detail="Backup not found")
        
        if backup["status"] != "completed":
            raise HTTPException(status_code=400, detail="Backup is not in completed state")
        
        # Determine target nodes
        target_nodes = request.target_nodes or backup["nodes_included"]
        
        # Create restore point
        restore_point = RestorePoint(
            restore_id=restore_id,
            backup_id=request.backup_id,
            timestamp=timestamp,
            status=RestoreStatus.VALIDATING,
            target_nodes=target_nodes
        )
        
        # Register restore
        self.storage.register_restore(restore_point)
        
        try:
            # Load backup data
            backup_path = Path(backup["path"])
            
            if backup["compression"]:
                with gzip.open(backup_path, "rt", encoding="utf-8") as f:
                    backup_data = json.load(f)
            else:
                with open(backup_path, "r") as f:
                    backup_data = json.load(f)
            
            # Verify checksum
            actual_checksum = self._calculate_checksum(backup_path)
            if actual_checksum != backup["checksum"]:
                raise ValueError("Backup checksum mismatch - possible corruption")
            
            if request.validate_only:
                restore_point.status = RestoreStatus.COMPLETED
                restore_point.duration_seconds = time.time() - start_time
                self.storage.update_restore_status(
                    restore_id,
                    RestoreStatus.COMPLETED,
                    duration_seconds=restore_point.duration_seconds
                )
                return restore_point
            
            # Restore data to nodes
            self.storage.update_restore_status(restore_id, RestoreStatus.RESTORING)
            
            for node_id in target_nodes:
                if node_id in backup_data.get("nodes", {}):
                    await self._restore_node_data(node_id, backup_data["nodes"][node_id])
            
            # Complete restore
            duration = time.time() - start_time
            restore_point.status = RestoreStatus.COMPLETED
            restore_point.duration_seconds = duration
            
            self.storage.update_restore_status(
                restore_id,
                RestoreStatus.COMPLETED,
                duration_seconds=duration
            )
            
            return restore_point
            
        except Exception as e:
            logger.error(f"Restore failed: {e}")
            restore_point.status = RestoreStatus.FAILED
            restore_point.error = str(e)
            
            self.storage.update_restore_status(
                restore_id,
                RestoreStatus.FAILED,
                error=str(e)
            )
            
            return restore_point
    
    async def _restore_node_data(self, node_id: str, data: Dict[str, Any]):
        """Restore data to a node."""
        # In production, this would send data to node's restore endpoint
        logger.info(f"Restoring data to {node_id}")
        await asyncio.sleep(0.1)  # Simulate restore
    
    def verify_backup(self, backup_id: str) -> Dict[str, Any]:
        """Verify backup integrity."""
        backup = self.storage.get_backup(backup_id)
        if not backup:
            return {"valid": False, "error": "Backup not found"}
        
        backup_path = Path(backup["path"])
        if not backup_path.exists():
            return {"valid": False, "error": "Backup file not found"}
        
        # Verify checksum
        actual_checksum = self._calculate_checksum(backup_path)
        checksum_valid = actual_checksum == backup["checksum"]
        
        # Try to read the file
        try:
            if backup["compression"]:
                with gzip.open(backup_path, "rt", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                with open(backup_path, "r") as f:
                    data = json.load(f)
            readable = True
        except Exception as e:
            readable = False
        
        return {
            "valid": checksum_valid and readable,
            "backup_id": backup_id,
            "checksum_valid": checksum_valid,
            "readable": readable,
            "stored_checksum": backup["checksum"],
            "actual_checksum": actual_checksum
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """Get backup statistics."""
        backups = self.storage.list_backups(100)
        
        total_size = sum(b.get("size_bytes", 0) or 0 for b in backups)
        completed = sum(1 for b in backups if b["status"] == "completed")
        failed = sum(1 for b in backups if b["status"] == "failed")
        
        return {
            "total_backups": len(backups),
            "completed_backups": completed,
            "failed_backups": failed,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "backup_dir": str(self.backup_dir)
        }

# =============================================================================
# FastAPI Application
# =============================================================================

service: Optional[BackupService] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global service
    
    logger.info(f"Starting Node {NODE_ID}: {NODE_NAME}")
    service = BackupService(BACKUP_DIR)
    logger.info(f"Node {NODE_ID} ({NODE_NAME}) is ready")
    
    yield
    
    logger.info(f"Shutting down Node {NODE_ID}")
    if service:
        await service.http_client.aclose()

app = FastAPI(
    title=f"UFO Galaxy Node {NODE_ID}: {NODE_NAME}",
    description="Backup & Disaster Recovery System",
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
    stats = service.get_stats() if service else {}
    return {
        "status": "healthy",
        "node_id": NODE_ID,
        "node_name": NODE_NAME,
        "total_backups": stats.get("total_backups", 0)
    }

@app.post("/backup")
async def create_backup(request: BackupRequest):
    """Create a new backup."""
    metadata = await service.create_backup(request)
    return {
        "backup_id": metadata.backup_id,
        "status": metadata.status.value,
        "size_bytes": metadata.size_bytes,
        "duration_seconds": metadata.duration_seconds,
        "nodes_included": metadata.nodes_included
    }

@app.post("/restore")
async def restore_backup(request: RestoreRequest):
    """Restore from a backup."""
    restore_point = await service.restore_backup(request)
    return {
        "restore_id": restore_point.restore_id,
        "backup_id": restore_point.backup_id,
        "status": restore_point.status.value,
        "target_nodes": restore_point.target_nodes,
        "duration_seconds": restore_point.duration_seconds,
        "error": restore_point.error
    }

@app.get("/backups")
async def list_backups(limit: int = 50):
    """List all backups."""
    return {
        "backups": service.storage.list_backups(limit)
    }

@app.get("/backups/{backup_id}")
async def get_backup(backup_id: str):
    """Get backup details."""
    backup = service.storage.get_backup(backup_id)
    if not backup:
        raise HTTPException(status_code=404, detail="Backup not found")
    return backup

@app.get("/verify/{backup_id}")
async def verify_backup(backup_id: str):
    """Verify backup integrity."""
    return service.verify_backup(backup_id)

@app.delete("/backups/{backup_id}")
async def delete_backup(backup_id: str):
    """Delete a backup."""
    backup = service.storage.get_backup(backup_id)
    if not backup:
        raise HTTPException(status_code=404, detail="Backup not found")
    
    # Delete file
    if backup["path"] and Path(backup["path"]).exists():
        Path(backup["path"]).unlink()
    
    # Update status
    service.storage.update_backup_status(backup_id, BackupStatus.CORRUPTED)
    
    return {"status": "deleted", "backup_id": backup_id}

@app.get("/stats")
async def get_stats():
    """Get backup statistics."""
    return service.get_stats()

@app.post("/cleanup")
async def cleanup_old_backups(keep_count: int = MAX_BACKUPS):
    """Cleanup old backups."""
    deleted = service.storage.cleanup_old_backups(keep_count)
    return {
        "deleted_count": len(deleted),
        "deleted_backups": deleted
    }

@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "node_id": NODE_ID,
        "node_name": NODE_NAME,
        "layer": "L0_KERNEL",
        "capabilities": ["backup", "restore", "disaster_recovery"]
    }

# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8069,
        reload=False,
        log_level=LOG_LEVEL.lower()
    )
