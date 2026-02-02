"""
Node 65: Centralized Audit & Forensic Logger
UFO Galaxy 64-Core MCP Matrix - Phase 6: Immune System

Security-first logging with immutable audit trail.
"""

import os
import json
import asyncio
import logging
import time
import hashlib
import hmac
import gzip
from typing import Dict, Optional, List, Any
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from enum import Enum
from dataclasses import dataclass, field
from pathlib import Path
import sqlite3
import threading

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

# =============================================================================
# Configuration
# =============================================================================

NODE_ID = os.getenv("NODE_ID", "65")
NODE_NAME = os.getenv("NODE_NAME", "LoggerCentral")
STATE_MACHINE_URL = os.getenv("STATE_MACHINE_URL", "http://localhost:8000")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
DATA_DIR = os.getenv("DATA_DIR", os.path.join(os.path.dirname(__file__), "data"))
HMAC_SECRET = os.getenv("HMAC_SECRET", "ufo-galaxy-audit-secret-key")

# Storage configuration
MAX_MEMORY_LOGS = 10000
COMPRESSION_THRESHOLD = 1000  # Compress after this many logs
RETENTION_DAYS = 30

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format=f"[Node {NODE_ID}] %(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# =============================================================================
# Models
# =============================================================================

class LogLevel(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"
    AUDIT = "audit"  # Special level for audit events

class LogCategory(str, Enum):
    SYSTEM = "system"
    SECURITY = "security"
    HARDWARE = "hardware"
    MODEL = "model"
    USER = "user"
    NETWORK = "network"
    RECOVERY = "recovery"

@dataclass
class AuditLog:
    """Immutable audit log entry."""
    timestamp: str
    node_id: str
    session_id: str
    action: str
    resource: Optional[str]
    caller: Optional[str]
    parameters: Dict[str, Any]
    result: Dict[str, Any]
    latency_ms: float
    trace_id: str
    level: LogLevel
    category: LogCategory
    signature: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "node_id": self.node_id,
            "session_id": self.session_id,
            "action": self.action,
            "resource": self.resource,
            "caller": self.caller,
            "parameters": self.parameters,
            "result": self.result,
            "latency_ms": self.latency_ms,
            "trace_id": self.trace_id,
            "level": self.level.value,
            "category": self.category.value,
            "signature": self.signature
        }

class LogEntry(BaseModel):
    node_id: str
    action: str
    session_id: Optional[str] = None
    resource: Optional[str] = None
    caller: Optional[str] = None
    parameters: Dict[str, Any] = {}
    result: Dict[str, Any] = {}
    latency_ms: float = 0
    trace_id: Optional[str] = None
    level: LogLevel = LogLevel.INFO
    category: LogCategory = LogCategory.SYSTEM

class LogQuery(BaseModel):
    node_id: Optional[str] = None
    action: Optional[str] = None
    level: Optional[LogLevel] = None
    category: Optional[LogCategory] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    trace_id: Optional[str] = None
    limit: int = 100
    offset: int = 0

# =============================================================================
# Merkle Tree for Tamper Detection
# =============================================================================

class MerkleTree:
    """Simple Merkle tree for tamper detection."""
    
    def __init__(self):
        self.leaves: List[str] = []
        self.root: Optional[str] = None
    
    def add_leaf(self, data: str) -> str:
        """Add a leaf and return its hash."""
        leaf_hash = hashlib.sha256(data.encode()).hexdigest()
        self.leaves.append(leaf_hash)
        self._update_root()
        return leaf_hash
    
    def _update_root(self):
        """Recalculate Merkle root."""
        if not self.leaves:
            self.root = None
            return
        
        current_level = self.leaves.copy()
        
        while len(current_level) > 1:
            next_level = []
            for i in range(0, len(current_level), 2):
                left = current_level[i]
                right = current_level[i + 1] if i + 1 < len(current_level) else left
                combined = hashlib.sha256((left + right).encode()).hexdigest()
                next_level.append(combined)
            current_level = next_level
        
        self.root = current_level[0] if current_level else None
    
    def verify(self, data: str, leaf_hash: str) -> bool:
        """Verify that data matches its leaf hash."""
        expected = hashlib.sha256(data.encode()).hexdigest()
        return expected == leaf_hash
    
    def get_root(self) -> Optional[str]:
        """Get current Merkle root."""
        return self.root

# =============================================================================
# Log Storage
# =============================================================================

class LogStorage:
    """Persistent log storage with SQLite."""
    
    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.db_path = self.data_dir / "audit_logs.db"
        self.merkle_tree = MerkleTree()
        
        self._init_db()
        self._lock = threading.Lock()
    
    def _init_db(self):
        """Initialize SQLite database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    session_id TEXT,
                    action TEXT NOT NULL,
                    resource TEXT,
                    caller TEXT,
                    parameters TEXT,
                    result TEXT,
                    latency_ms REAL,
                    trace_id TEXT,
                    level TEXT NOT NULL,
                    category TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    created_at REAL DEFAULT (strftime('%s', 'now'))
                )
            """)
            
            # Create indexes
            conn.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON logs(timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_node_id ON logs(node_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_action ON logs(action)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_level ON logs(level)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trace_id ON logs(trace_id)")
            
            conn.commit()
    
    def store(self, log: AuditLog) -> int:
        """Store a log entry."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    INSERT INTO logs (
                        timestamp, node_id, session_id, action, resource, caller,
                        parameters, result, latency_ms, trace_id, level, category, signature
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    log.timestamp,
                    log.node_id,
                    log.session_id,
                    log.action,
                    log.resource,
                    log.caller,
                    json.dumps(log.parameters),
                    json.dumps(log.result),
                    log.latency_ms,
                    log.trace_id,
                    log.level.value,
                    log.category.value,
                    log.signature
                ))
                conn.commit()
                
                # Add to Merkle tree
                self.merkle_tree.add_leaf(log.signature)
                
                return cursor.lastrowid
    
    def query(self, query: LogQuery) -> List[Dict[str, Any]]:
        """Query logs with filters."""
        conditions = []
        params = []
        
        if query.node_id:
            conditions.append("node_id = ?")
            params.append(query.node_id)
        
        if query.action:
            conditions.append("action LIKE ?")
            params.append(f"%{query.action}%")
        
        if query.level:
            conditions.append("level = ?")
            params.append(query.level.value)
        
        if query.category:
            conditions.append("category = ?")
            params.append(query.category.value)
        
        if query.trace_id:
            conditions.append("trace_id = ?")
            params.append(query.trace_id)
        
        if query.start_time:
            conditions.append("timestamp >= ?")
            params.append(query.start_time)
        
        if query.end_time:
            conditions.append("timestamp <= ?")
            params.append(query.end_time)
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(f"""
                SELECT * FROM logs
                WHERE {where_clause}
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
            """, params + [query.limit, query.offset])
            
            rows = cursor.fetchall()
            
            return [
                {
                    "id": row["id"],
                    "timestamp": row["timestamp"],
                    "node_id": row["node_id"],
                    "session_id": row["session_id"],
                    "action": row["action"],
                    "resource": row["resource"],
                    "caller": row["caller"],
                    "parameters": json.loads(row["parameters"]) if row["parameters"] else {},
                    "result": json.loads(row["result"]) if row["result"] else {},
                    "latency_ms": row["latency_ms"],
                    "trace_id": row["trace_id"],
                    "level": row["level"],
                    "category": row["category"],
                    "signature": row["signature"]
                }
                for row in rows
            ]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get storage statistics."""
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM logs").fetchone()[0]
            
            by_level = dict(conn.execute("""
                SELECT level, COUNT(*) FROM logs GROUP BY level
            """).fetchall())
            
            by_category = dict(conn.execute("""
                SELECT category, COUNT(*) FROM logs GROUP BY category
            """).fetchall())
            
            by_node = dict(conn.execute("""
                SELECT node_id, COUNT(*) FROM logs GROUP BY node_id
            """).fetchall())
            
            return {
                "total_logs": total,
                "by_level": by_level,
                "by_category": by_category,
                "by_node": by_node,
                "merkle_root": self.merkle_tree.get_root(),
                "db_size_bytes": self.db_path.stat().st_size if self.db_path.exists() else 0
            }
    
    def verify_integrity(self, log_id: int) -> Dict[str, Any]:
        """Verify integrity of a specific log entry."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM logs WHERE id = ?", (log_id,)).fetchone()
            
            if not row:
                return {"valid": False, "error": "Log not found"}
            
            # Reconstruct the data that was signed
            data = json.dumps({
                "timestamp": row["timestamp"],
                "node_id": row["node_id"],
                "action": row["action"],
                "parameters": row["parameters"],
                "result": row["result"]
            }, sort_keys=True)
            
            # Verify HMAC
            expected_sig = hmac.new(
                HMAC_SECRET.encode(),
                data.encode(),
                hashlib.sha256
            ).hexdigest()
            
            return {
                "valid": row["signature"] == expected_sig,
                "log_id": log_id,
                "stored_signature": row["signature"],
                "expected_signature": expected_sig[:16] + "..."
            }

# =============================================================================
# Logger Service
# =============================================================================

class LoggerService:
    """Main logging service."""
    
    def __init__(self, data_dir: str):
        self.storage = LogStorage(data_dir)
        self.memory_buffer: List[AuditLog] = []
        self.session_counter = 0
    
    def _generate_signature(self, log_data: Dict[str, Any]) -> str:
        """Generate HMAC signature for log entry."""
        data = json.dumps(log_data, sort_keys=True)
        return hmac.new(
            HMAC_SECRET.encode(),
            data.encode(),
            hashlib.sha256
        ).hexdigest()
    
    def _generate_trace_id(self) -> str:
        """Generate unique trace ID."""
        import uuid
        return f"trace_{uuid.uuid4().hex[:12]}"
    
    def _generate_session_id(self) -> str:
        """Generate session ID."""
        self.session_counter += 1
        return f"sess_{self.session_counter:08d}"
    
    def log(self, entry: LogEntry) -> AuditLog:
        """Create and store a log entry."""
        timestamp = datetime.utcnow().isoformat() + "Z"
        trace_id = entry.trace_id or self._generate_trace_id()
        session_id = entry.session_id or self._generate_session_id()
        
        # Create signature
        sign_data = {
            "timestamp": timestamp,
            "node_id": entry.node_id,
            "action": entry.action,
            "parameters": json.dumps(entry.parameters),
            "result": json.dumps(entry.result)
        }
        signature = self._generate_signature(sign_data)
        
        audit_log = AuditLog(
            timestamp=timestamp,
            node_id=entry.node_id,
            session_id=session_id,
            action=entry.action,
            resource=entry.resource,
            caller=entry.caller,
            parameters=entry.parameters,
            result=entry.result,
            latency_ms=entry.latency_ms,
            trace_id=trace_id,
            level=entry.level,
            category=entry.category,
            signature=signature
        )
        
        # Store in database
        self.storage.store(audit_log)
        
        # Keep in memory buffer
        self.memory_buffer.append(audit_log)
        if len(self.memory_buffer) > MAX_MEMORY_LOGS:
            self.memory_buffer = self.memory_buffer[-MAX_MEMORY_LOGS // 2:]
        
        return audit_log
    
    def query(self, query: LogQuery) -> List[Dict[str, Any]]:
        """Query logs."""
        return self.storage.query(query)
    
    def get_recent(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent logs from memory buffer."""
        return [log.to_dict() for log in self.memory_buffer[-limit:]]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get logging statistics."""
        storage_stats = self.storage.get_stats()
        return {
            **storage_stats,
            "memory_buffer_size": len(self.memory_buffer)
        }
    
    def verify_log(self, log_id: int) -> Dict[str, Any]:
        """Verify integrity of a log entry."""
        return self.storage.verify_integrity(log_id)
    
    def export_logs(
        self,
        query: LogQuery,
        format: str = "json"
    ) -> str:
        """Export logs in specified format."""
        logs = self.query(query)
        
        if format == "json":
            return json.dumps(logs, indent=2)
        elif format == "jsonl":
            return "\n".join(json.dumps(log) for log in logs)
        else:
            return json.dumps(logs)

# =============================================================================
# FastAPI Application
# =============================================================================

service: Optional[LoggerService] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global service
    
    logger.info(f"Starting Node {NODE_ID}: {NODE_NAME}")
    service = LoggerService(DATA_DIR)
    logger.info(f"Node {NODE_ID} ({NODE_NAME}) is ready")
    
    yield
    
    logger.info(f"Shutting down Node {NODE_ID}")

app = FastAPI(
    title=f"UFO Galaxy Node {NODE_ID}: {NODE_NAME}",
    description="Centralized Audit & Forensic Logger",
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
        "total_logs": stats.get("total_logs", 0)
    }

@app.post("/log")
async def create_log(entry: LogEntry):
    """Create a new log entry."""
    audit_log = service.log(entry)
    return {
        "status": "logged",
        "trace_id": audit_log.trace_id,
        "signature": audit_log.signature[:16] + "..."
    }

@app.post("/query")
async def query_logs(query: LogQuery):
    """Query logs with filters."""
    logs = service.query(query)
    return {
        "logs": logs,
        "count": len(logs),
        "query": query.dict()
    }

@app.get("/recent")
async def get_recent_logs(limit: int = 100):
    """Get recent logs from memory buffer."""
    return {
        "logs": service.get_recent(limit),
        "source": "memory_buffer"
    }

@app.get("/stats")
async def get_stats():
    """Get logging statistics."""
    return service.get_stats()

@app.get("/verify/{log_id}")
async def verify_log(log_id: int):
    """Verify integrity of a log entry."""
    return service.verify_log(log_id)

@app.get("/merkle-root")
async def get_merkle_root():
    """Get current Merkle root for audit verification."""
    return {
        "merkle_root": service.storage.merkle_tree.get_root(),
        "leaf_count": len(service.storage.merkle_tree.leaves)
    }

@app.post("/export")
async def export_logs(query: LogQuery, format: str = "json"):
    """Export logs in specified format."""
    data = service.export_logs(query, format)
    return {
        "format": format,
        "data": data[:10000] + "..." if len(data) > 10000 else data,
        "truncated": len(data) > 10000
    }

@app.get("/levels")
async def get_log_levels():
    """Get available log levels."""
    return {"levels": [l.value for l in LogLevel]}

@app.get("/categories")
async def get_log_categories():
    """Get available log categories."""
    return {"categories": [c.value for c in LogCategory]}

@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "node_id": NODE_ID,
        "node_name": NODE_NAME,
        "layer": "L0_KERNEL",
        "capabilities": ["audit_logging", "forensic_analysis", "tamper_detection"]
    }

# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8065,
        reload=False,
        log_level=LOG_LEVEL.lower()
    )
