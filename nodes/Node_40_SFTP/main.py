"""
Node 40: SFTP - 安全文件传输
"""
import os
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node 40 - SFTP", version="3.0.0", description="Secure File Transfer Protocol")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

try:
    import paramiko
    SFTP_AVAILABLE = True
except ImportError:
    SFTP_AVAILABLE = False

class SFTPRequest(BaseModel):
    host: str
    port: int = 22
    username: str
    password: Optional[str] = None
    key_file: Optional[str] = None

class SFTPUploadRequest(SFTPRequest):
    local_path: str
    remote_path: str

class SFTPDownloadRequest(SFTPRequest):
    remote_path: str
    local_path: str

@app.get("/health")
async def health():
    return {
        "status": "healthy" if SFTP_AVAILABLE else "degraded",
        "node_id": "40",
        "name": "SFTP",
        "paramiko_available": SFTP_AVAILABLE
    }

@app.post("/upload")
async def upload_file(request: SFTPUploadRequest):
    """上传文件到远程服务器"""
    if not SFTP_AVAILABLE:
        raise HTTPException(status_code=503, detail="paramiko not installed. Run: pip install paramiko")
    
    try:
        transport = paramiko.Transport((request.host, request.port))
        if request.key_file:
            key = paramiko.RSAKey.from_private_key_file(request.key_file)
            transport.connect(username=request.username, pkey=key)
        else:
            transport.connect(username=request.username, password=request.password)
        
        sftp = paramiko.SFTPClient.from_transport(transport)
        sftp.put(request.local_path, request.remote_path)
        sftp.close()
        transport.close()
        
        return {"success": True, "message": f"Uploaded {request.local_path} to {request.remote_path}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/download")
async def download_file(request: SFTPDownloadRequest):
    """从远程服务器下载文件"""
    if not SFTP_AVAILABLE:
        raise HTTPException(status_code=503, detail="paramiko not installed")
    
    try:
        transport = paramiko.Transport((request.host, request.port))
        if request.key_file:
            key = paramiko.RSAKey.from_private_key_file(request.key_file)
            transport.connect(username=request.username, pkey=key)
        else:
            transport.connect(username=request.username, password=request.password)
        
        sftp = paramiko.SFTPClient.from_transport(transport)
        sftp.get(request.remote_path, request.local_path)
        sftp.close()
        transport.close()
        
        return {"success": True, "message": f"Downloaded {request.remote_path} to {request.local_path}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/list")
async def list_directory(request: SFTPRequest, remote_path: str = "/"):
    """列出远程目录内容"""
    if not SFTP_AVAILABLE:
        raise HTTPException(status_code=503, detail="paramiko not installed")
    
    try:
        transport = paramiko.Transport((request.host, request.port))
        if request.key_file:
            key = paramiko.RSAKey.from_private_key_file(request.key_file)
            transport.connect(username=request.username, pkey=key)
        else:
            transport.connect(username=request.username, password=request.password)
        
        sftp = paramiko.SFTPClient.from_transport(transport)
        files = sftp.listdir(remote_path)
        sftp.close()
        transport.close()
        
        return {"success": True, "files": files}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/mcp/call")
async def mcp_call(request: dict):
    tool = request.get("tool", "")
    params = request.get("params", {})
    if tool == "upload": return await upload_file(SFTPUploadRequest(**params))
    elif tool == "download": return await download_file(SFTPDownloadRequest(**params))
    elif tool == "list": return await list_directory(SFTPRequest(**params), params.get("remote_path", "/"))
    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8040)
