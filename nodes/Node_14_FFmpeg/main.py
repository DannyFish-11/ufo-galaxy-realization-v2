"""
Node 14: FFmpeg - 视频处理节点
=================================
提供视频转码、剪辑、合并、截图、格式转换功能
"""
import os
import json
import subprocess
import tempfile
from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI(title="Node 14 - FFmpeg", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# 配置
WORK_DIR = os.getenv("FFMPEG_WORK_DIR", "/tmp/ffmpeg")
os.makedirs(WORK_DIR, exist_ok=True)

class ConvertRequest(BaseModel):
    input_path: str
    output_path: str
    format: Optional[str] = None
    video_codec: Optional[str] = None
    audio_codec: Optional[str] = None
    resolution: Optional[str] = None
    bitrate: Optional[str] = None

class ClipRequest(BaseModel):
    input_path: str
    output_path: str
    start_time: str  # HH:MM:SS or seconds
    duration: str

class ExtractAudioRequest(BaseModel):
    input_path: str
    output_path: str
    audio_format: str = "mp3"

class FFmpegManager:
    def __init__(self):
        self.work_dir = Path(WORK_DIR)
        self._check_ffmpeg()

    def _check_ffmpeg(self):
        """检查FFmpeg是否可用"""
        try:
            result = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True)
            self.ffmpeg_available = result.returncode == 0
        except FileNotFoundError:
            self.ffmpeg_available = False

    def _run_ffmpeg(self, args: List[str]) -> Dict:
        """运行FFmpeg命令"""
        if not self.ffmpeg_available:
            raise RuntimeError("FFmpeg not found. Please install FFmpeg.")

        cmd = ["ffmpeg", "-y"] + args
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg error: {result.stderr}")

        return {"success": True, "command": " ".join(cmd)}

    def get_media_info(self, input_path: str) -> Dict:
        """获取媒体文件信息"""
        if not self.ffmpeg_available:
            raise RuntimeError("FFmpeg not found")

        cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", 
               "-show_format", "-show_streams", input_path]
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            raise RuntimeError(f"FFprobe error: {result.stderr}")

        return json.loads(result.stdout)

    def convert(self, input_path: str, output_path: str, **options) -> Dict:
        """转换视频格式"""
        args = ["-i", input_path]

        if options.get("video_codec"):
            args.extend(["-c:v", options["video_codec"]])
        if options.get("audio_codec"):
            args.extend(["-c:a", options["audio_codec"]])
        if options.get("resolution"):
            args.extend(["-s", options["resolution"]])
        if options.get("bitrate"):
            args.extend(["-b:v", options["bitrate"]])

        args.append(output_path)
        return self._run_ffmpeg(args)

    def clip(self, input_path: str, output_path: str, start_time: str, duration: str) -> Dict:
        """剪辑视频"""
        args = [
            "-ss", start_time,
            "-t", duration,
            "-i", input_path,
            "-c", "copy",
            output_path
        ]
        return self._run_ffmpeg(args)

    def extract_audio(self, input_path: str, output_path: str, audio_format: str = "mp3") -> Dict:
        """提取音频"""
        args = [
            "-i", input_path,
            "-vn",  # 无视频
            "-c:a", "libmp3lame" if audio_format == "mp3" else "copy",
            output_path
        ]
        return self._run_ffmpeg(args)

    def screenshot(self, input_path: str, output_path: str, timestamp: str = "00:00:01") -> Dict:
        """视频截图"""
        args = [
            "-ss", timestamp,
            "-i", input_path,
            "-vframes", "1",
            "-q:v", "2",
            output_path
        ]
        return self._run_ffmpeg(args)

    def merge_videos(self, input_paths: List[str], output_path: str) -> Dict:
        """合并视频"""
        # 创建临时文件列表
        list_file = self.work_dir / "merge_list.txt"
        with open(list_file, 'w') as f:
            for path in input_paths:
                f.write(f"file '{path}'\n")

        args = [
            "-f", "concat",
            "-safe", "0",
            "-i", str(list_file),
            "-c", "copy",
            output_path
        ]
        result = self._run_ffmpeg(args)
        list_file.unlink()
        return result

# 全局FFmpeg管理器
ffmpeg_manager = FFmpegManager()

# ============ API 端点 ============

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "node_id": "14",
        "name": "FFmpeg",
        "ffmpeg_available": ffmpeg_manager.ffmpeg_available,
        "work_dir": str(ffmpeg_manager.work_dir),
        "timestamp": datetime.now().isoformat()
    }

@app.post("/convert")
async def convert_video(request: ConvertRequest):
    """转换视频"""
    try:
        result = ffmpeg_manager.convert(
            request.input_path, 
            request.output_path,
            format=request.format,
            video_codec=request.video_codec,
            audio_codec=request.audio_codec,
            resolution=request.resolution,
            bitrate=request.bitrate
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/clip")
async def clip_video(request: ClipRequest):
    """剪辑视频"""
    try:
        result = ffmpeg_manager.clip(
            request.input_path,
            request.output_path,
            request.start_time,
            request.duration
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/extract-audio")
async def extract_audio(request: ExtractAudioRequest):
    """提取音频"""
    try:
        result = ffmpeg_manager.extract_audio(
            request.input_path,
            request.output_path,
            request.audio_format
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/screenshot")
async def screenshot(input_path: str, output_path: str, timestamp: str = "00:00:01"):
    """视频截图"""
    try:
        result = ffmpeg_manager.screenshot(input_path, output_path, timestamp)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/info")
async def get_media_info(input_path: str):
    """获取媒体信息"""
    try:
        info = ffmpeg_manager.get_media_info(input_path)
        return info
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/upload")
async def upload_video(file: UploadFile = File(...)):
    """上传视频"""
    file_path = ffmpeg_manager.work_dir / file.filename
    with open(file_path, 'wb') as f:
        content = await file.read()
        f.write(content)
    return {"path": str(file_path), "filename": file.filename}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8014)
