"""
Node 39: SSH - SSH连接节点
============================
提供SSH连接、命令执行、文件传输功能
"""
import os
import asyncssh
import asyncio
from datetime import datetime
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node 39 - SSH", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

class SSHConnection(BaseModel):
    host: str
    port: int = 22
    username: str
    password: Optional[str] = None
    private_key: Optional[str] = None
    timeout: int = 30

class SSHCommandRequest(BaseModel):
    connection: SSHConnection
    command: str
    timeout: int = 60

class SSHFileTransferRequest(BaseModel):
    connection: SSHConnection
    local_path: str
    remote_path: str
    direction: str = "upload"  # upload, download

class SSHManager:
    def __init__(self):
        self.connections: Dict[str, asyncssh.SSHClientConnection] = {}

    async def connect(self, conn_id: str, conn: SSHConnection) -> bool:
        """建立SSH连接"""
        try:
            client_keys = []
            if conn.private_key:
                client_keys = [asyncssh.import_private_key(conn.private_key)]

            connection = await asyncssh.connect(
                host=conn.host,
                port=conn.port,
                username=conn.username,
                password=conn.password,
                client_keys=client_keys,
                known_hosts=None
            )
            self.connections[conn_id] = connection
            return True
        except Exception as e:
            raise RuntimeError(f"SSH connection failed: {e}")

    async def disconnect(self, conn_id: str):
        """断开SSH连接"""
        if conn_id in self.connections:
            self.connections[conn_id].close()
            await self.connections[conn_id].wait_closed()
            del self.connections[conn_id]

    async def execute_command(self, conn_id: str, command: str, timeout: int = 60) -> Dict:
        """执行SSH命令"""
        if conn_id not in self.connections:
            raise RuntimeError("SSH connection not established")

        try:
            result = await asyncio.wait_for(
                self.connections[conn_id].run(command),
                timeout=timeout
            )

            return {
                "command": command,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.exit_status,
                "success": result.exit_status == 0
            }
        except asyncio.TimeoutError:
            raise RuntimeError(f"Command timed out after {timeout} seconds")

    async def upload_file(self, conn_id: str, local_path: str, remote_path: str):
        """上传文件"""
        if conn_id not in self.connections:
            raise RuntimeError("SSH connection not established")

        async with self.connections[conn_id].start_sftp_client() as sftp:
            await sftp.put(local_path, remote_path)

        return {"success": True, "local_path": local_path, "remote_path": remote_path}

    async def download_file(self, conn_id: str, remote_path: str, local_path: str):
        """下载文件"""
        if conn_id not in self.connections:
            raise RuntimeError("SSH connection not established")

        async with self.connections[conn_id].start_sftp_client() as sftp:
            await sftp.get(remote_path, local_path)

        return {"success": True, "remote_path": remote_path, "local_path": local_path}

# 全局SSH管理器
ssh_manager = SSHManager()

# ============ API 端点 ============

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "node_id": "39",
        "name": "SSH",
        "active_connections": len(ssh_manager.connections),
        "timestamp": datetime.now().isoformat()
    }

@app.post("/connect")
async def connect_ssh(conn: SSHConnection, conn_id: str = None):
    """建立SSH连接"""
    conn_id = conn_id or f"{conn.host}_{conn.username}"
    try:
        success = await ssh_manager.connect(conn_id, conn)
        return {"success": success, "connection_id": conn_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/disconnect")
async def disconnect_ssh(conn_id: str):
    """断开SSH连接"""
    try:
        await ssh_manager.disconnect(conn_id)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/execute")
async def execute_command(request: SSHCommandRequest):
    """执行SSH命令"""
    conn_id = f"{request.connection.host}_{request.connection.username}"
    try:
        # 自动连接
        if conn_id not in ssh_manager.connections:
            await ssh_manager.connect(conn_id, request.connection)

        result = await ssh_manager.execute_command(conn_id, request.command, request.timeout)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/upload")
async def upload_file(request: SSHFileTransferRequest):
    """上传文件"""
    conn_id = f"{request.connection.host}_{request.connection.username}"
    try:
        if conn_id not in ssh_manager.connections:
            await ssh_manager.connect(conn_id, request.connection)

        result = await ssh_manager.upload_file(conn_id, request.local_path, request.remote_path)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/download")
async def download_file(request: SSHFileTransferRequest):
    """下载文件"""
    conn_id = f"{request.connection.host}_{request.connection.username}"
    try:
        if conn_id not in ssh_manager.connections:
            await ssh_manager.connect(conn_id, request.connection)

        result = await ssh_manager.download_file(conn_id, request.remote_path, request.local_path)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8039)
