"""
Node 39: SSH - 安全远程执行
"""
import os
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node 39 - SSH", version="3.0.0", description="Secure Shell Remote Execution")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

try:
    import paramiko
    SSH_AVAILABLE = True
except ImportError:
    SSH_AVAILABLE = False

class SSHExecuteRequest(BaseModel):
    host: str
    port: int = 22
    username: str
    password: Optional[str] = None
    key_file: Optional[str] = None
    command: str

@app.get("/health")
async def health():
    return {
        "status": "healthy" if SSH_AVAILABLE else "degraded",
        "node_id": "39",
        "name": "SSH",
        "paramiko_available": SSH_AVAILABLE
    }

@app.post("/execute")
async def execute_command(request: SSHExecuteRequest):
    """通过 SSH 执行远程命令"""
    if not SSH_AVAILABLE:
        raise HTTPException(status_code=503, detail="paramiko not installed. Run: pip install paramiko")
    
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        if request.key_file:
            client.connect(request.host, port=request.port, username=request.username, key_filename=request.key_file)
        else:
            client.connect(request.host, port=request.port, username=request.username, password=request.password)
        
        stdin, stdout, stderr = client.exec_command(request.command)
        output = stdout.read().decode()
        error = stderr.read().decode()
        exit_status = stdout.channel.recv_exit_status()
        
        client.close()
        
        return {
            "success": exit_status == 0,
            "stdout": output,
            "stderr": error,
            "exit_status": exit_status
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/mcp/call")
async def mcp_call(request: dict):
    tool = request.get("tool", "")
    params = request.get("params", {})
    if tool == "execute": return await execute_command(SSHExecuteRequest(**params))
    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8039)
