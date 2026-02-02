"""Node 14: FFmpeg - 音视频处理"""
import os, subprocess, shutil
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node 14 - FFmpeg", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

FFMPEG_PATH = shutil.which("ffmpeg") or "ffmpeg"

class ConvertRequest(BaseModel):
    input_path: str
    output_path: str
    options: Optional[str] = ""

class ExtractAudioRequest(BaseModel):
    input_path: str
    output_path: str
    format: str = "mp3"

class TrimRequest(BaseModel):
    input_path: str
    output_path: str
    start: str  # HH:MM:SS
    duration: Optional[str] = None
    end: Optional[str] = None

@app.get("/health")
async def health():
    ffmpeg_available = shutil.which("ffmpeg") is not None
    return {"status": "healthy" if ffmpeg_available else "degraded", "node_id": "14", "name": "FFmpeg", "ffmpeg_available": ffmpeg_available, "timestamp": datetime.now().isoformat()}

@app.post("/convert")
async def convert(request: ConvertRequest):
    try:
        cmd = f'{FFMPEG_PATH} -i "{request.input_path}" {request.options} -y "{request.output_path}"'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise Exception(result.stderr)
        return {"success": True, "output_path": request.output_path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/extract_audio")
async def extract_audio(request: ExtractAudioRequest):
    try:
        cmd = f'{FFMPEG_PATH} -i "{request.input_path}" -vn -acodec {"libmp3lame" if request.format == "mp3" else "copy"} -y "{request.output_path}"'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise Exception(result.stderr)
        return {"success": True, "output_path": request.output_path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/trim")
async def trim(request: TrimRequest):
    try:
        duration_opt = f'-t {request.duration}' if request.duration else (f'-to {request.end}' if request.end else '')
        cmd = f'{FFMPEG_PATH} -i "{request.input_path}" -ss {request.start} {duration_opt} -c copy -y "{request.output_path}"'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise Exception(result.stderr)
        return {"success": True, "output_path": request.output_path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/info")
async def get_info(input_path: str):
    try:
        cmd = f'ffprobe -v quiet -print_format json -show_format -show_streams "{input_path}"'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise Exception(result.stderr)
        import json
        return {"success": True, "info": json.loads(result.stdout)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/mcp/call")
async def mcp_call(request: dict):
    tool = request.get("tool", "")
    params = request.get("params", {})
    if tool == "convert": return await convert(ConvertRequest(**params))
    elif tool == "extract_audio": return await extract_audio(ExtractAudioRequest(**params))
    elif tool == "trim": return await trim(TrimRequest(**params))
    elif tool == "info": return await get_info(params.get("input_path"))
    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8014)
