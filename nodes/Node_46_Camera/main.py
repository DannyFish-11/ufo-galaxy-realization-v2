"""
Node 46: Camera - 摄像头控制
"""
import os, base64
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node 46 - Camera", version="3.0.0", description="Camera Control and Capture")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

try:
    import cv2
    CAMERA_AVAILABLE = True
except ImportError:
    CAMERA_AVAILABLE = False

class CaptureRequest(BaseModel):
    camera_id: int = 0
    format: str = "jpeg"

@app.get("/health")
async def health():
    return {
        "status": "healthy" if CAMERA_AVAILABLE else "degraded",
        "node_id": "46",
        "name": "Camera",
        "opencv_available": CAMERA_AVAILABLE
    }

@app.post("/capture")
async def capture_image(request: CaptureRequest):
    """拍摄照片"""
    if not CAMERA_AVAILABLE:
        raise HTTPException(status_code=503, detail="opencv-python not installed. Run: pip install opencv-python")
    
    try:
        cap = cv2.VideoCapture(request.camera_id)
        if not cap.isOpened():
            raise HTTPException(status_code=503, detail=f"Cannot open camera {request.camera_id}")
        
        ret, frame = cap.read()
        cap.release()
        
        if not ret:
            raise HTTPException(status_code=500, detail="Failed to capture image")
        
        _, buffer = cv2.imencode(f'.{request.format}', frame)
        image_base64 = base64.b64encode(buffer).decode()
        
        return {
            "success": True,
            "format": request.format,
            "image": image_base64,
            "width": frame.shape[1],
            "height": frame.shape[0]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/list")
async def list_cameras():
    """列出可用摄像头"""
    if not CAMERA_AVAILABLE:
        raise HTTPException(status_code=503, detail="opencv-python not installed")
    
    cameras = []
    for i in range(10):
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            cameras.append({"id": i, "name": f"Camera {i}"})
            cap.release()
    
    return {"success": True, "cameras": cameras}

@app.post("/mcp/call")
async def mcp_call(request: dict):
    tool = request.get("tool", "")
    params = request.get("params", {})
    if tool == "capture": return await capture_image(CaptureRequest(**params))
    elif tool == "list": return await list_cameras()
    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8046)
