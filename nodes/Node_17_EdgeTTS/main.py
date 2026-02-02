"""
Node 17: EdgeTTS - 微软 Edge 文本转语音
"""
import os, asyncio
from datetime import datetime
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node 17 - EdgeTTS", version="3.0.0", description="Microsoft Edge Text-to-Speech API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

try:
    import edge_tts
    EDGE_TTS_AVAILABLE = True
except ImportError:
    EDGE_TTS_AVAILABLE = False

class TTSRequest(BaseModel):
    text: str
    voice: str = "zh-CN-XiaoxiaoNeural"
    rate: str = "+0%"
    volume: str = "+0%"
    pitch: str = "+0Hz"

VOICES = {
    "zh-CN-XiaoxiaoNeural": "晓晓 (女声, 中文)",
    "zh-CN-YunxiNeural": "云希 (男声, 中文)",
    "zh-CN-YunyangNeural": "云扬 (男声, 中文)",
    "en-US-JennyNeural": "Jenny (Female, English)",
    "en-US-GuyNeural": "Guy (Male, English)",
    "ja-JP-NanamiNeural": "Nanami (Female, Japanese)",
    "ko-KR-SunHiNeural": "SunHi (Female, Korean)",
}

@app.get("/health")
async def health():
    return {
        "status": "healthy" if EDGE_TTS_AVAILABLE else "degraded",
        "node_id": "17",
        "name": "EdgeTTS",
        "edge_tts_available": EDGE_TTS_AVAILABLE,
        "supported_voices": len(VOICES)
    }

@app.post("/synthesize")
async def synthesize(request: TTSRequest):
    """合成语音"""
    if not EDGE_TTS_AVAILABLE:
        raise HTTPException(status_code=503, detail="edge-tts not installed. Run: pip install edge-tts")
    
    try:
        communicate = edge_tts.Communicate(
            text=request.text,
            voice=request.voice,
            rate=request.rate,
            volume=request.volume,
            pitch=request.pitch
        )
        
        audio_data = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data += chunk["data"]
        
        return Response(content=audio_data, media_type="audio/mpeg")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/voices")
async def list_voices():
    """列出所有可用的语音"""
    if not EDGE_TTS_AVAILABLE:
        return {"success": False, "voices": VOICES, "note": "edge-tts not installed"}
    
    try:
        voices = await edge_tts.list_voices()
        return {"success": True, "voices": [{"name": v["Name"], "locale": v["Locale"], "gender": v["Gender"]} for v in voices]}
    except Exception as e:
        return {"success": False, "error": str(e), "default_voices": VOICES}

@app.post("/mcp/call")
async def mcp_call(request: dict):
    tool = request.get("tool", "")
    params = request.get("params", {})
    if tool == "synthesize": return await synthesize(TTSRequest(**params))
    elif tool == "voices": return await list_voices()
    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8017)
