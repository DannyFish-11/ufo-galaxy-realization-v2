"""
Node 42: CANbus - 汽车总线通信
"""
import os
from typing import Optional, List
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node 42 - CANbus", version="3.0.0", description="Controller Area Network Bus Communication")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

try:
    import can
    CAN_AVAILABLE = True
except ImportError:
    CAN_AVAILABLE = False

class CANSendRequest(BaseModel):
    channel: str = "can0"
    arbitration_id: int
    data: List[int]
    is_extended_id: bool = False

@app.get("/health")
async def health():
    return {
        "status": "healthy" if CAN_AVAILABLE else "degraded",
        "node_id": "42",
        "name": "CANbus",
        "python_can_available": CAN_AVAILABLE
    }

@app.post("/send")
async def send_message(request: CANSendRequest):
    """发送 CAN 消息"""
    if not CAN_AVAILABLE:
        raise HTTPException(status_code=503, detail="python-can not installed. Run: pip install python-can")
    
    try:
        bus = can.interface.Bus(channel=request.channel, bustype='socketcan')
        msg = can.Message(
            arbitration_id=request.arbitration_id,
            data=request.data,
            is_extended_id=request.is_extended_id
        )
        bus.send(msg)
        bus.shutdown()
        return {"success": True, "arbitration_id": request.arbitration_id, "data": request.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/mcp/call")
async def mcp_call(request: dict):
    tool = request.get("tool", "")
    params = request.get("params", {})
    if tool == "send": return await send_message(CANSendRequest(**params))
    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8042)
