"""
Node 44: NFC - 近场通信
"""
import os
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node 44 - NFC", version="3.0.0", description="Near Field Communication")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

try:
    import nfc
    NFC_AVAILABLE = True
except ImportError:
    NFC_AVAILABLE = False

class NFCReadRequest(BaseModel):
    timeout: int = 10

@app.get("/health")
async def health():
    return {
        "status": "healthy" if NFC_AVAILABLE else "degraded",
        "node_id": "44",
        "name": "NFC",
        "nfcpy_available": NFC_AVAILABLE
    }

@app.post("/read")
async def read_tag(request: NFCReadRequest):
    """读取 NFC 标签"""
    if not NFC_AVAILABLE:
        raise HTTPException(status_code=503, detail="nfcpy not installed. Run: pip install nfcpy")
    
    try:
        clf = nfc.ContactlessFrontend('usb')
        if not clf:
            raise HTTPException(status_code=503, detail="No NFC reader found")
        
        tag = clf.connect(rdwr={'on-connect': lambda tag: False}, timeout=request.timeout)
        if tag:
            return {
                "success": True,
                "type": str(tag.type),
                "identifier": tag.identifier.hex(),
                "ndef": str(tag.ndef) if hasattr(tag, 'ndef') else None
            }
        else:
            return {"success": False, "error": "No tag detected"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/mcp/call")
async def mcp_call(request: dict):
    tool = request.get("tool", "")
    params = request.get("params", {})
    if tool == "read": return await read_tag(NFCReadRequest(**params))
    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8044)
