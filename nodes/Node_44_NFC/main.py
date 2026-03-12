"""
Node 44: NFC - Near Field Communication
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
    PORT = get_node_port("Node_44_NFC")
except Exception:
    PORT = int(os.getenv("PORT", "8044"))

try:
    import nfc
    NFC_AVAILABLE = True
except ImportError:
    nfc = None
    NFC_AVAILABLE = False

app = FastAPI(title="Node 44 - NFC", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=get_cors_origins(), allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

class ReadRequest(BaseModel):
    device: str = "usb"
    timeout: float = 10.0

class WriteRequest(BaseModel):
    device: str = "usb"
    data: str
    timeout: float = 10.0

@app.get("/health")
async def health():
    return {
        "status": "healthy" if NFC_AVAILABLE else "degraded",
        "node_id": "44",
        "name": "NFC",
        "nfc_available": NFC_AVAILABLE,
        "degraded": not NFC_AVAILABLE,
        "degraded_reason": None if NFC_AVAILABLE else "nfcpy not installed",
        "timestamp": datetime.now().isoformat()
    }

@app.get("/status")
async def status():
    return {
        "status": "running",
        "node_id": "44",
        "name": "NFC",
        "nfc_available": NFC_AVAILABLE,
        "timestamp": datetime.now().isoformat()
    }

@app.get("/devices")
async def list_devices():
    if not NFC_AVAILABLE:
        return {"success": False, "error": "nfcpy not installed. Run: pip install nfcpy"}
    try:
        devices = []
        for name in ["usb", "tty:S0", "tty:USB0", "udp"]:
            try:
                clf = nfc.ContactlessFrontend(name)
                clf.close()
                devices.append(name)
            except Exception:
                pass
        return {"success": True, "devices": devices}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/scan")
async def scan(timeout: float = 5.0, device: str = "usb"):
    if not NFC_AVAILABLE:
        return {"success": False, "error": "nfcpy not installed. Run: pip install nfcpy"}
    try:
        tag_info = {}
        def on_connect(tag):
            tag_info["type"] = str(type(tag).__name__)
            tag_info["identifier"] = tag.identifier.hex() if tag.identifier else None
            return False  # Don't keep connection

        clf = nfc.ContactlessFrontend(device)
        try:
            clf.connect(rdwr={"on-connect": on_connect, "targets": ["106A", "106B", "212F"]}, terminate=lambda: len(tag_info) > 0)
        finally:
            clf.close()

        if tag_info:
            return {"success": True, "tag": tag_info}
        return {"success": True, "tag": None, "message": "No tag found within timeout"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/read")
async def read_tag(request: ReadRequest):
    if not NFC_AVAILABLE:
        return {"success": False, "error": "nfcpy not installed. Run: pip install nfcpy"}
    try:
        tag_data = {}
        def on_connect(tag):
            tag_data["type"] = str(type(tag).__name__)
            tag_data["identifier"] = tag.identifier.hex() if tag.identifier else None
            if hasattr(tag, "ndef") and tag.ndef:
                records = []
                for record in tag.ndef.records:
                    records.append({
                        "type": record.type.decode() if isinstance(record.type, bytes) else str(record.type),
                        "data": record.data.decode("utf-8", errors="replace") if record.data else ""
                    })
                tag_data["ndef"] = records
            return False

        clf = nfc.ContactlessFrontend(request.device)
        try:
            clf.connect(rdwr={"on-connect": on_connect}, terminate=lambda: len(tag_data) > 0)
        finally:
            clf.close()

        if tag_data:
            return {"success": True, "data": tag_data}
        return {"success": False, "error": "No tag detected"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/write")
async def write_tag(request: WriteRequest):
    if not NFC_AVAILABLE:
        return {"success": False, "error": "nfcpy not installed. Run: pip install nfcpy"}
    try:
        result = {}
        def on_connect(tag):
            if hasattr(tag, "ndef") and tag.ndef and tag.ndef.is_writeable:
                import ndef
                tag.ndef.records = [ndef.TextRecord(request.data)]
                result["success"] = True
            else:
                result["success"] = False
                result["error"] = "Tag is not NDEF writable"
            return False

        clf = nfc.ContactlessFrontend(request.device)
        try:
            clf.connect(rdwr={"on-connect": on_connect}, terminate=lambda: len(result) > 0)
        finally:
            clf.close()

        return result if result else {"success": False, "error": "No tag detected"}
    except Exception as e:
        return {"success": False, "error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
