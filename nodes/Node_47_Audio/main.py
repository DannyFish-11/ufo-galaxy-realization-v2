"""
Node 47: Audio - 音频录制与播放
"""
import os, base64, wave
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node 47 - Audio", version="3.0.0", description="Audio Recording and Playback")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

try:
    import pyaudio
    AUDIO_AVAILABLE = True
except ImportError:
    AUDIO_AVAILABLE = False

class RecordRequest(BaseModel):
    duration: int = 5
    sample_rate: int = 44100
    channels: int = 1

@app.get("/health")
async def health():
    return {
        "status": "healthy" if AUDIO_AVAILABLE else "degraded",
        "node_id": "47",
        "name": "Audio",
        "pyaudio_available": AUDIO_AVAILABLE
    }

@app.post("/record")
async def record_audio(request: RecordRequest):
    """录制音频"""
    if not AUDIO_AVAILABLE:
        raise HTTPException(status_code=503, detail="pyaudio not installed. Run: pip install pyaudio")
    
    try:
        p = pyaudio.PyAudio()
        stream = p.open(
            format=pyaudio.paInt16,
            channels=request.channels,
            rate=request.sample_rate,
            input=True,
            frames_per_buffer=1024
        )
        
        frames = []
        for _ in range(0, int(request.sample_rate / 1024 * request.duration)):
            data = stream.read(1024)
            frames.append(data)
        
        stream.stop_stream()
        stream.close()
        p.terminate()
        
        # 保存为 WAV 格式
        audio_data = b''.join(frames)
        audio_base64 = base64.b64encode(audio_data).decode()
        
        return {
            "success": True,
            "duration": request.duration,
            "sample_rate": request.sample_rate,
            "channels": request.channels,
            "audio": audio_base64
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/devices")
async def list_devices():
    """列出音频设备"""
    if not AUDIO_AVAILABLE:
        raise HTTPException(status_code=503, detail="pyaudio not installed")
    
    try:
        p = pyaudio.PyAudio()
        devices = []
        for i in range(p.get_device_count()):
            info = p.get_device_info_by_index(i)
            devices.append({
                "id": i,
                "name": info.get("name"),
                "channels": info.get("maxInputChannels")
            })
        p.terminate()
        return {"success": True, "devices": devices}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/mcp/call")
async def mcp_call(request: dict):
    tool = request.get("tool", "")
    params = request.get("params", {})
    if tool == "record": return await record_audio(RecordRequest(**params))
    elif tool == "devices": return await list_devices()
    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8047)
