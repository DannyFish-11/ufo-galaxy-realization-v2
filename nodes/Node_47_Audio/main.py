"""
Node 47: Audio - Audio Recording and Playback
"""
import os
import base64
import io
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from nodes.common.cors_config import get_cors_origins

try:
    from core.port_config import get_node_port
    PORT = get_node_port("Node_47_Audio")
except Exception as exc:
    logger.debug("Fallback triggered: %s", exc)
    PORT = int(os.getenv("PORT", "8047"))

try:
    import sounddevice as sd
    import numpy as np
    SD_AVAILABLE = True
except ImportError:
    sd = None
    np = None
    SD_AVAILABLE = False

try:
    from scipy.io import wavfile
    SCIPY_AVAILABLE = True
except ImportError:
    wavfile = None
    SCIPY_AVAILABLE = False

app = FastAPI(title="Node 47 - Audio", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=get_cors_origins(), allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# Recording state
recording_state: Dict[str, Any] = {"active": False, "data": [], "samplerate": 44100, "channels": 1}
playback_state: Dict[str, Any] = {"active": False}

class RecordStartRequest(BaseModel):
    device_id: Optional[int] = None
    samplerate: int = 44100
    channels: int = 1

class PlayRequest(BaseModel):
    audio_b64: Optional[str] = None  # base64 WAV data
    file_path: Optional[str] = None
    device_id: Optional[int] = None

@app.get("/health")
async def health():
    return {
        "status": "healthy" if SD_AVAILABLE else "degraded",
        "node_id": "47",
        "name": "Audio",
        "sounddevice_available": SD_AVAILABLE,
        "scipy_available": SCIPY_AVAILABLE,
        "degraded": not SD_AVAILABLE,
        "degraded_reason": None if SD_AVAILABLE else "sounddevice not installed",
        "recording": recording_state["active"],
        "timestamp": datetime.now().isoformat()
    }

@app.get("/status")
async def status():
    return {
        "status": "running",
        "node_id": "47",
        "name": "Audio",
        "sounddevice_available": SD_AVAILABLE,
        "recording": recording_state["active"],
        "playing": playback_state["active"],
        "timestamp": datetime.now().isoformat()
    }

@app.get("/devices")
async def list_devices():
    if not SD_AVAILABLE:
        return {"success": False, "error": "sounddevice not installed. Run: pip install sounddevice"}
    try:
        devices = sd.query_devices()
        result = []
        for i, d in enumerate(devices):
            result.append({
                "id": i,
                "name": d["name"],
                "max_input_channels": d["max_input_channels"],
                "max_output_channels": d["max_output_channels"],
                "default_samplerate": d["default_samplerate"],
                "is_input": d["max_input_channels"] > 0,
                "is_output": d["max_output_channels"] > 0
            })
        return {"success": True, "devices": result, "count": len(result)}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/record/start")
async def record_start(request: RecordStartRequest):
    if not SD_AVAILABLE:
        return {"success": False, "error": "sounddevice not installed. Run: pip install sounddevice"}
    if recording_state["active"]:
        return {"success": False, "error": "Recording already in progress"}
    try:
        recording_state["active"] = True
        recording_state["data"] = []
        recording_state["samplerate"] = request.samplerate
        recording_state["channels"] = request.channels

        def callback(indata, frames, time, status):
            if recording_state["active"]:
                recording_state["data"].append(indata.copy())

        kwargs = {"samplerate": request.samplerate, "channels": request.channels, "callback": callback}
        if request.device_id is not None:
            kwargs["device"] = request.device_id

        stream = sd.InputStream(**kwargs)
        stream.start()
        recording_state["stream"] = stream
        return {"success": True, "samplerate": request.samplerate, "channels": request.channels}
    except Exception as e:
        logger.debug("Fallback triggered: %s", e)
        recording_state["active"] = False
        return {"success": False, "error": str(e)}

@app.post("/record/stop")
async def record_stop():
    if not SD_AVAILABLE:
        return {"success": False, "error": "sounddevice not installed. Run: pip install sounddevice"}
    if not recording_state["active"]:
        return {"success": False, "error": "No active recording"}
    try:
        recording_state["active"] = False
        stream = recording_state.get("stream")
        if stream:
            stream.stop()
            stream.close()
            recording_state["stream"] = None

        if not recording_state["data"]:
            return {"success": False, "error": "No audio data recorded"}

        audio = np.concatenate(recording_state["data"], axis=0)
        samplerate = recording_state["samplerate"]

        buf = io.BytesIO()
        if SCIPY_AVAILABLE:
            audio_int16 = (audio * 32767).astype(np.int16)
            wavfile.write(buf, samplerate, audio_int16)
        else:
            # Simple WAV header
            import struct
            channels = audio.shape[1] if audio.ndim > 1 else 1
            audio_int16 = (audio * 32767).astype(np.int16).tobytes()
            buf.write(b"RIFF")
            buf.write(struct.pack("<I", 36 + len(audio_int16)))
            buf.write(b"WAVE")
            buf.write(b"fmt ")
            buf.write(struct.pack("<IHHIIHH", 16, 1, channels, samplerate, samplerate * channels * 2, channels * 2, 16))
            buf.write(b"data")
            buf.write(struct.pack("<I", len(audio_int16)))
            buf.write(audio_int16)

        audio_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        recording_state["data"] = []
        return {"success": True, "audio_b64": audio_b64, "samplerate": samplerate, "duration": len(audio) / samplerate}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/play")
async def play_audio(request: PlayRequest):
    if not SD_AVAILABLE:
        return {"success": False, "error": "sounddevice not installed. Run: pip install sounddevice"}
    try:
        if request.audio_b64:
            data = base64.b64decode(request.audio_b64)
            buf = io.BytesIO(data)
            if SCIPY_AVAILABLE:
                samplerate, audio = wavfile.read(buf)
            else:
                return {"success": False, "error": "scipy required for WAV playback. Run: pip install scipy"}
        elif request.file_path:
            if not os.path.exists(request.file_path):
                return {"success": False, "error": f"File not found: {request.file_path}"}
            if SCIPY_AVAILABLE:
                samplerate, audio = wavfile.read(request.file_path)
            else:
                return {"success": False, "error": "scipy required for WAV playback. Run: pip install scipy"}
        else:
            return {"success": False, "error": "Either audio_b64 or file_path required"}

        kwargs = {"samplerate": samplerate}
        if request.device_id is not None:
            kwargs["device"] = request.device_id

        def play():
            playback_state["active"] = True
            sd.play(audio, **kwargs)
            sd.wait()
            playback_state["active"] = False

        t = threading.Thread(target=play, daemon=True)
        t.start()
        return {"success": True, "samplerate": samplerate, "message": "Playback started"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/play/stop")
async def stop_playback():
    if not SD_AVAILABLE:
        return {"success": False, "error": "sounddevice not installed. Run: pip install sounddevice"}
    try:
        sd.stop()
        playback_state["active"] = False
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
