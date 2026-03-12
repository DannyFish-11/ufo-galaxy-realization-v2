"""
Node 40: SFTP - Secure File Transfer Protocol
"""
import os
from datetime import datetime
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from nodes.common.cors_config import get_cors_origins

try:
    from core.port_config import get_node_port
    PORT = get_node_port("Node_40_SFTP")
except Exception:
    PORT = int(os.getenv("PORT", "8040"))

try:
    import asyncssh
    ASYNCSSH_AVAILABLE = True
except ImportError:
    asyncssh = None
    ASYNCSSH_AVAILABLE = False

app = FastAPI(title="Node 40 - SFTP", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=get_cors_origins(), allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# Active connections: conn_id -> asyncssh connection
connections: Dict[str, Any] = {}

class ConnectRequest(BaseModel):
    host: str
    port: int = 22
    username: str
    password: Optional[str] = None
    private_key: Optional[str] = None
    conn_id: Optional[str] = None

class DisconnectRequest(BaseModel):
    conn_id: str

class UploadRequest(BaseModel):
    conn_id: str
    local_path: str
    remote_path: str

class DownloadRequest(BaseModel):
    conn_id: str
    remote_path: str
    local_path: str

class ListRequest(BaseModel):
    conn_id: str
    remote_path: str = "."

class MkdirRequest(BaseModel):
    conn_id: str
    remote_path: str

class DeleteRequest(BaseModel):
    conn_id: str
    remote_path: str

@app.get("/health")
async def health():
    return {
        "status": "healthy" if ASYNCSSH_AVAILABLE else "degraded",
        "node_id": "40",
        "name": "SFTP",
        "asyncssh_available": ASYNCSSH_AVAILABLE,
        "degraded": not ASYNCSSH_AVAILABLE,
        "degraded_reason": None if ASYNCSSH_AVAILABLE else "asyncssh not installed",
        "active_connections": len(connections),
        "timestamp": datetime.now().isoformat()
    }

@app.get("/status")
async def status():
    return {
        "status": "running",
        "node_id": "40",
        "name": "SFTP",
        "asyncssh_available": ASYNCSSH_AVAILABLE,
        "active_connections": list(connections.keys()),
        "timestamp": datetime.now().isoformat()
    }

@app.post("/connect")
async def connect(request: ConnectRequest):
    if not ASYNCSSH_AVAILABLE:
        return {"success": False, "error": "asyncssh not installed. Run: pip install asyncssh"}
    try:
        conn_id = request.conn_id or f"{request.username}@{request.host}:{request.port}"
        kwargs = {"host": request.host, "port": request.port, "username": request.username, "known_hosts": None}
        if request.password:
            kwargs["password"] = request.password
        if request.private_key:
            kwargs["client_keys"] = [asyncssh.import_private_key(request.private_key)]
        conn = await asyncssh.connect(**kwargs)
        connections[conn_id] = conn
        return {"success": True, "conn_id": conn_id}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/disconnect")
async def disconnect(request: DisconnectRequest):
    if request.conn_id not in connections:
        return {"success": False, "error": f"Connection '{request.conn_id}' not found"}
    try:
        connections[request.conn_id].close()
        await connections[request.conn_id].wait_closed()
        del connections[request.conn_id]
        return {"success": True, "conn_id": request.conn_id}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/upload")
async def upload(request: UploadRequest):
    if not ASYNCSSH_AVAILABLE:
        return {"success": False, "error": "asyncssh not installed. Run: pip install asyncssh"}
    if request.conn_id not in connections:
        return {"success": False, "error": f"Connection '{request.conn_id}' not found"}
    if not os.path.exists(request.local_path):
        return {"success": False, "error": f"Local file not found: {request.local_path}"}
    try:
        async with connections[request.conn_id].start_sftp_client() as sftp:
            await sftp.put(request.local_path, request.remote_path)
        return {"success": True, "local_path": request.local_path, "remote_path": request.remote_path}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/download")
async def download(request: DownloadRequest):
    if not ASYNCSSH_AVAILABLE:
        return {"success": False, "error": "asyncssh not installed. Run: pip install asyncssh"}
    if request.conn_id not in connections:
        return {"success": False, "error": f"Connection '{request.conn_id}' not found"}
    try:
        async with connections[request.conn_id].start_sftp_client() as sftp:
            await sftp.get(request.remote_path, request.local_path)
        return {"success": True, "remote_path": request.remote_path, "local_path": request.local_path}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/list")
async def list_directory(conn_id: str, remote_path: str = "."):
    if not ASYNCSSH_AVAILABLE:
        return {"success": False, "error": "asyncssh not installed. Run: pip install asyncssh"}
    if conn_id not in connections:
        return {"success": False, "error": f"Connection '{conn_id}' not found"}
    try:
        async with connections[conn_id].start_sftp_client() as sftp:
            entries = await sftp.readdir(remote_path)
        files = []
        for entry in entries:
            attrs = entry.attrs
            files.append({
                "name": entry.filename,
                "size": attrs.size if attrs.size is not None else 0,
                "permissions": oct(attrs.permissions) if attrs.permissions is not None else None,
                "mtime": attrs.mtime
            })
        return {"success": True, "path": remote_path, "entries": files, "count": len(files)}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/mkdir")
async def mkdir(request: MkdirRequest):
    if not ASYNCSSH_AVAILABLE:
        return {"success": False, "error": "asyncssh not installed. Run: pip install asyncssh"}
    if request.conn_id not in connections:
        return {"success": False, "error": f"Connection '{request.conn_id}' not found"}
    try:
        async with connections[request.conn_id].start_sftp_client() as sftp:
            await sftp.mkdir(request.remote_path)
        return {"success": True, "remote_path": request.remote_path}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.delete("/delete")
async def delete_file(conn_id: str, remote_path: str):
    if not ASYNCSSH_AVAILABLE:
        return {"success": False, "error": "asyncssh not installed. Run: pip install asyncssh"}
    if conn_id not in connections:
        return {"success": False, "error": f"Connection '{conn_id}' not found"}
    try:
        async with connections[conn_id].start_sftp_client() as sftp:
            await sftp.remove(remote_path)
        return {"success": True, "remote_path": remote_path}
    except Exception as e:
        return {"success": False, "error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
