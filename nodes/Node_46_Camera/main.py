"""
Node 46: Camera - Computer Vision & Camera Control
"""
import os
import base64
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from nodes.common.cors_config import get_cors_origins

try:
    from core.port_config import get_node_port
    PORT = get_node_port("Node_46_Camera")
except Exception as exc:
    logger.debug("Fallback triggered: %s", exc)
    PORT = int(os.getenv("PORT", "8046"))

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    cv2 = None
    CV2_AVAILABLE = False

app = FastAPI(title="Node 46 - Camera", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=get_cors_origins(), allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# State
recording_state: Dict[str, Any] = {"active": False, "writer": None, "capture": None}
stream_capture: Optional[Any] = None

class CaptureRequest(BaseModel):
    device_id: int = 0
    width: Optional[int] = None
    height: Optional[int] = None

class RecordStartRequest(BaseModel):
    device_id: int = 0
    output_path: str = "recording.avi"
    fps: float = 20.0
    width: int = 640
    height: int = 480

class RecordStopRequest(BaseModel):
    pass

@app.get("/health")
async def health():
    return {
        "status": "healthy" if CV2_AVAILABLE else "degraded",
        "node_id": "46",
        "name": "Camera",
        "cv2_available": CV2_AVAILABLE,
        "degraded": not CV2_AVAILABLE,
        "degraded_reason": None if CV2_AVAILABLE else "opencv-python not installed",
        "recording": recording_state["active"],
        "timestamp": datetime.now().isoformat()
    }

@app.get("/status")
async def status():
    return {
        "status": "running",
        "node_id": "46",
        "name": "Camera",
        "cv2_available": CV2_AVAILABLE,
        "recording": recording_state["active"],
        "timestamp": datetime.now().isoformat()
    }

@app.get("/devices")
async def list_devices():
    if not CV2_AVAILABLE:
        return {"success": False, "error": "opencv-python not installed. Run: pip install opencv-python"}
    devices = []
    for i in range(10):
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            devices.append({
                "device_id": i,
                "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                "fps": cap.get(cv2.CAP_PROP_FPS)
            })
            cap.release()
    return {"success": True, "devices": devices, "count": len(devices)}

@app.post("/capture")
async def capture_photo(request: CaptureRequest):
    if not CV2_AVAILABLE:
        return {"success": False, "error": "opencv-python not installed. Run: pip install opencv-python"}
    try:
        cap = cv2.VideoCapture(request.device_id)
        if not cap.isOpened():
            return {"success": False, "error": f"Cannot open camera device {request.device_id}"}
        if request.width:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, request.width)
        if request.height:
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, request.height)
        ret, frame = cap.read()
        cap.release()
        if not ret:
            return {"success": False, "error": "Failed to capture frame"}
        _, buffer = cv2.imencode(".jpg", frame)
        image_b64 = base64.b64encode(buffer).decode("utf-8")
        return {
            "success": True,
            "device_id": request.device_id,
            "width": frame.shape[1],
            "height": frame.shape[0],
            "image": image_b64,
            "format": "jpeg",
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/record/start")
async def record_start(request: RecordStartRequest):
    if not CV2_AVAILABLE:
        return {"success": False, "error": "opencv-python not installed. Run: pip install opencv-python"}
    if recording_state["active"]:
        return {"success": False, "error": "Recording already in progress"}
    try:
        cap = cv2.VideoCapture(request.device_id)
        if not cap.isOpened():
            return {"success": False, "error": f"Cannot open camera device {request.device_id}"}
        fourcc = cv2.VideoWriter_fourcc(*"XVID")
        writer = cv2.VideoWriter(request.output_path, fourcc, request.fps, (request.width, request.height))
        recording_state["active"] = True
        recording_state["writer"] = writer
        recording_state["capture"] = cap
        recording_state["output_path"] = request.output_path

        def record_loop():
            while recording_state["active"]:
                ret, frame = cap.read()
                if ret:
                    writer.write(frame)

        t = threading.Thread(target=record_loop, daemon=True)
        t.start()
        return {"success": True, "output_path": request.output_path}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/record/stop")
async def record_stop():
    if not recording_state["active"]:
        return {"success": False, "error": "No active recording"}
    recording_state["active"] = False
    if recording_state["writer"]:
        recording_state["writer"].release()
        recording_state["writer"] = None
    if recording_state["capture"]:
        recording_state["capture"].release()
        recording_state["capture"] = None
    output_path = recording_state.get("output_path", "recording.avi")
    return {"success": True, "output_path": output_path}

@app.get("/stream/frame")
async def get_stream_frame(device_id: int = 0):
    if not CV2_AVAILABLE:
        return {"success": False, "error": "opencv-python not installed. Run: pip install opencv-python"}
    try:
        cap = cv2.VideoCapture(device_id)
        if not cap.isOpened():
            return {"success": False, "error": f"Cannot open camera device {device_id}"}
        ret, frame = cap.read()
        cap.release()
        if not ret:
            return {"success": False, "error": "Failed to capture frame"}
        _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        image_b64 = base64.b64encode(buffer).decode("utf-8")
        return {"success": True, "device_id": device_id, "image": image_b64, "format": "jpeg", "timestamp": datetime.now().isoformat()}
    except Exception as e:
        return {"success": False, "error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
