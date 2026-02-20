"""
Node 17: EdgeTTS - 语音合成节点
=================================
提供文本转语音、语音合成、音频生成功能
"""
import os
import asyncio
from datetime import datetime
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

# 尝试导入edge-tts
try:
    import edge_tts
    EDGE_TTS_AVAILABLE = True
except ImportError:
    EDGE_TTS_AVAILABLE = False

app = FastAPI(title="Node 17 - EdgeTTS", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# 配置
OUTPUT_DIR = os.getenv("EDGETTS_OUTPUT_DIR", "/tmp/edge_tts")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 可用语音列表
VOICES = {
    "zh-CN-XiaoxiaoNeural": "中文-女声",
    "zh-CN-YunxiNeural": "中文-男声",
    "en-US-JennyNeural": "英文-女声",
    "en-US-GuyNeural": "英文-男声",
    "ja-JP-NanamiNeural": "日语-女声",
    "ko-KR-SunHiNeural": "韩语-女声",
}

class TTSRequest(BaseModel):
    text: str
    voice: str = "zh-CN-XiaoxiaoNeural"
    rate: str = "+0%"  # 语速调整
    volume: str = "+0%"  # 音量调整
    output_format: str = "mp3"

class TTSManager:
    def __init__(self):
        self.output_dir = OUTPUT_DIR

    async def synthesize(self, text: str, voice: str = "zh-CN-XiaoxiaoNeural",
                        rate: str = "+0%", volume: str = "+0%",
                        output_format: str = "mp3") -> str:
        """合成语音"""
        if not EDGE_TTS_AVAILABLE:
            raise RuntimeError("edge-tts not installed. Install with: pip install edge-tts")

        if voice not in VOICES:
            raise ValueError(f"Voice '{voice}' not available. Available: {list(VOICES.keys())}")

        output_file = os.path.join(self.output_dir, f"tts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{output_format}")

        communicate = edge_tts.Communicate(
            text=text,
            voice=voice,
            rate=rate,
            volume=volume
        )
        await communicate.save(output_file)

        return output_file

    def list_voices(self) -> Dict[str, str]:
        """列出可用语音"""
        return VOICES

    async def get_voices_from_edge(self) -> List[Dict]:
        """从Edge获取所有可用语音"""
        if not EDGE_TTS_AVAILABLE:
            return []

        voices = await edge_tts.list_voices()
        return [{"name": v["ShortName"], "locale": v["Locale"], "gender": v["Gender"]} for v in voices]

# 全局TTS管理器
tts_manager = TTSManager()

# ============ API 端点 ============

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "node_id": "17",
        "name": "EdgeTTS",
        "edge_tts_available": EDGE_TTS_AVAILABLE,
        "output_dir": OUTPUT_DIR,
        "timestamp": datetime.now().isoformat()
    }

@app.post("/synthesize")
async def synthesize(request: TTSRequest):
    """合成语音"""
    if not EDGE_TTS_AVAILABLE:
        raise HTTPException(status_code=503, detail="edge-tts not installed")

    try:
        output_file = await tts_manager.synthesize(
            text=request.text,
            voice=request.voice,
            rate=request.rate,
            volume=request.volume,
            output_format=request.output_format
        )
        return {"success": True, "output_file": output_file}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/voices")
async def list_voices():
    """列出可用语音"""
    return {"voices": tts_manager.list_voices()}

@app.get("/voices/all")
async def get_all_voices():
    """获取所有可用语音"""
    if not EDGE_TTS_AVAILABLE:
        raise HTTPException(status_code=503, detail="edge-tts not installed")

    try:
        voices = await tts_manager.get_voices_from_edge()
        return {"voices": voices}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8017)
