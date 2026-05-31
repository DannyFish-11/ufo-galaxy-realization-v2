"""
Node 94: AudioAnalysis - 实时音频分析与语音转文字
=================================================
功能:
- 使用 OpenAI Whisper API 进行语音转文字
- 音频特征提取（时长、语言检测、置信度）
- 说话人检测
- 音频分类
- 支持格式: mp3, mp4, mpeg, mpga, m4a, wav, webm
"""
import os
import io
import base64
import time
import tempfile
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import math

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import timezone

try:
    from nodes.common.cors_config import get_cors_origins
except ImportError:
    def get_cors_origins():
        return ["*"]

try:
    from core.port_config import get_node_port
    _DEFAULT_PORT = get_node_port("Node_94_AudioAnalysis")
except Exception as exc:
    logger.debug("Fallback triggered: %s", exc)
    _DEFAULT_PORT = 8094

# ── Node identity ──────────────────────────────────────────────────────────────
NODE_ID = "94"
NODE_NAME = "AudioAnalysis"

# ── Environment variables ──────────────────────────────────────────────────────
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
NODE_86_SPEECH_URL = os.getenv("NODE_86_SPEECH_URL", "http://localhost:8086")

# ── Supported audio formats ────────────────────────────────────────────────────
SUPPORTED_FORMATS = ["mp3", "mp4", "mpeg", "mpga", "m4a", "wav", "webm"]

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(f"Node_{NODE_ID}_{NODE_NAME}")

# ── FastAPI app ────────────────────────────────────────────────────────────────
app = FastAPI(
    title=f"Node {NODE_ID} - {NODE_NAME}",
    description="Real-time audio analysis, speech-to-text (Whisper), feature extraction, speaker detection.",
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Pydantic models ────────────────────────────────────────────────────────────

class TranscribeRequest(BaseModel):
    audio_base64: str
    filename: str = "audio.wav"
    language: Optional[str] = None  # ISO-639-1 code; None = auto-detect
    response_format: str = "verbose_json"
    temperature: float = 0.0
    prompt: Optional[str] = None


class AnalyzeRequest(BaseModel):
    audio_base64: str
    filename: str = "audio.wav"
    language: Optional[str] = None


class DetectLanguageRequest(BaseModel):
    audio_base64: str
    filename: str = "audio.wav"


class MCPCallRequest(BaseModel):
    tool: str
    params: Dict[str, Any] = {}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _require_api_key() -> None:
    """Raise a clear HTTP 503 when the OpenAI key is missing."""
    if not OPENAI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "OPENAI_API_KEY not configured",
                "detail": (
                    "Set the OPENAI_API_KEY environment variable to enable "
                    "Whisper transcription features."
                ),
            },
        )


def _decode_audio(audio_base64: str, filename: str) -> bytes:
    """Decode base64 audio and return raw bytes."""
    try:
        return base64.b64decode(audio_base64)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid base64 audio data: {exc}")


def _get_format(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "wav"
    if ext not in SUPPORTED_FORMATS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format '{ext}'. Supported: {SUPPORTED_FORMATS}",
        )
    return ext


async def _whisper_transcribe(
    audio_bytes: bytes,
    filename: str,
    language: Optional[str],
    response_format: str,
    temperature: float,
    prompt: Optional[str],
) -> Dict[str, Any]:
    """Call OpenAI Whisper transcriptions endpoint via httpx."""
    url = f"{OPENAI_BASE_URL.rstrip('/')}/audio/transcriptions"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}

    form_data: Dict[str, Any] = {
        "model": "whisper-1",
        "response_format": response_format,
        "temperature": str(temperature),
    }
    if language:
        form_data["language"] = language
    if prompt:
        form_data["prompt"] = prompt

    files = {"file": (filename, audio_bytes, f"audio/{_get_format(filename)}")}

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(url, headers=headers, data=form_data, files=files)

    if resp.status_code != 200:
        raise HTTPException(
            status_code=resp.status_code,
            detail=f"Whisper API error: {resp.text}",
        )
    return resp.json()


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "node": f"Node_{NODE_ID}_{NODE_NAME}",
        "version": "1.0.0",
        "openai_configured": bool(OPENAI_API_KEY),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/status")
async def status():
    return {
        "node_id": NODE_ID,
        "node_name": NODE_NAME,
        "status": "running",
        "version": "1.0.0",
        "config": {
            "openai_configured": bool(OPENAI_API_KEY),
            "openai_base_url": OPENAI_BASE_URL,
            "node_86_speech_url": NODE_86_SPEECH_URL,
            "supported_formats": SUPPORTED_FORMATS,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/supported_formats")
async def supported_formats():
    return {
        "formats": SUPPORTED_FORMATS,
        "description": {
            "mp3": "MPEG Audio Layer III",
            "mp4": "MPEG-4 Audio",
            "mpeg": "MPEG Audio",
            "mpga": "MPEG Audio",
            "m4a": "MPEG-4 Audio (Apple)",
            "wav": "Waveform Audio File Format",
            "webm": "WebM Audio",
        },
        "max_file_size_mb": 25,
        "whisper_model": "whisper-1",
    }


@app.post("/transcribe")
async def transcribe(req: TranscribeRequest):
    """Transcribe audio using OpenAI Whisper API."""
    _require_api_key()

    audio_bytes = _decode_audio(req.audio_base64, req.filename)
    _get_format(req.filename)  # validate format early

    start = time.monotonic()
    result = await _whisper_transcribe(
        audio_bytes,
        req.filename,
        req.language,
        req.response_format,
        req.temperature,
        req.prompt,
    )
    elapsed = round(time.monotonic() - start, 3)

    text = result.get("text", "")
    detected_language = result.get("language", req.language or "unknown")
    duration = result.get("duration")
    segments = result.get("segments", [])

    return {
        "success": True,
        "text": text,
        "language": detected_language,
        "duration_seconds": duration,
        "segments": segments,
        "processing_time_seconds": elapsed,
        "model": "whisper-1",
        "filename": req.filename,
    }


@app.post("/analyze")
async def analyze(req: AnalyzeRequest):
    """Analyze audio characteristics: duration, language, confidence."""
    _require_api_key()

    audio_bytes = _decode_audio(req.audio_base64, req.filename)
    _get_format(req.filename)

    start = time.monotonic()
    # Use verbose_json to get rich metadata including segments & word timestamps
    result = await _whisper_transcribe(
        audio_bytes,
        req.filename,
        req.language,
        "verbose_json",
        0.0,
        None,
    )
    elapsed = round(time.monotonic() - start, 3)

    segments: List[Dict] = result.get("segments", [])
    duration: Optional[float] = result.get("duration")
    detected_language: str = result.get("language", req.language or "unknown")

    # Derive average log-probability as a proxy for confidence
    avg_logprob = None
    no_speech_prob = None
    if segments:
        logprobs = [s.get("avg_logprob") for s in segments if s.get("avg_logprob") is not None]
        no_speech_probs = [s.get("no_speech_prob") for s in segments if s.get("no_speech_prob") is not None]
        if logprobs:
            avg_logprob = round(sum(logprobs) / len(logprobs), 4)
        if no_speech_probs:
            no_speech_prob = round(sum(no_speech_probs) / len(no_speech_probs), 4)

    # Estimate confidence: map avg_logprob [-∞, 0] → [0, 1]
    confidence = None
    if avg_logprob is not None:
        confidence = round(max(0.0, min(1.0, math.exp(avg_logprob))), 4)

    # Simple speaker count heuristic: count segments with large silence gaps
    speaker_segments = _estimate_speakers(segments)

    return {
        "success": True,
        "filename": req.filename,
        "duration_seconds": duration,
        "language": detected_language,
        "confidence": confidence,
        "avg_logprob": avg_logprob,
        "no_speech_probability": no_speech_prob,
        "segment_count": len(segments),
        "estimated_speakers": speaker_segments["estimated_count"],
        "speaker_segments": speaker_segments["segments"],
        "text_preview": result.get("text", "")[:200],
        "processing_time_seconds": elapsed,
    }


@app.post("/detect_language")
async def detect_language(req: DetectLanguageRequest):
    """Detect the spoken language from an audio clip."""
    _require_api_key()

    audio_bytes = _decode_audio(req.audio_base64, req.filename)
    _get_format(req.filename)

    start = time.monotonic()
    result = await _whisper_transcribe(
        audio_bytes,
        req.filename,
        None,  # force auto-detection
        "verbose_json",
        0.0,
        None,
    )
    elapsed = round(time.monotonic() - start, 3)

    detected = result.get("language", "unknown")
    segments: List[Dict] = result.get("segments", [])

    # Collect per-segment language confidence if present
    lang_counts: Dict[str, int] = {}
    for seg in segments:
        lang = seg.get("language", detected)
        lang_counts[lang] = lang_counts.get(lang, 0) + 1

    return {
        "success": True,
        "detected_language": detected,
        "language_distribution": lang_counts,
        "segment_count": len(segments),
        "processing_time_seconds": elapsed,
        "filename": req.filename,
    }


@app.post("/mcp/call")
async def mcp_call(req: MCPCallRequest):
    """MCP tool dispatch endpoint."""
    tool = req.tool
    params = req.params

    tool_map = {
        "transcribe": transcribe,
        "analyze": analyze,
        "detect_language": detect_language,
        "supported_formats": supported_formats,
        "health": health,
        "status": status,
    }

    if tool not in tool_map:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown tool '{tool}'. Available: {list(tool_map.keys())}",
        )

    try:
        handler = tool_map[tool]
        if tool == "transcribe":
            return await handler(TranscribeRequest(**params))
        elif tool == "analyze":
            return await handler(AnalyzeRequest(**params))
        elif tool == "detect_language":
            return await handler(DetectLanguageRequest(**params))
        else:
            return await handler()
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"MCP tool '{tool}' error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


# ── Internal helpers ───────────────────────────────────────────────────────────

def _estimate_speakers(segments: List[Dict]) -> Dict[str, Any]:
    """
    Heuristic speaker estimation based on silence gaps between segments.
    A gap > 1.5 s suggests a potential speaker change.
    """
    if not segments:
        return {"estimated_count": 0, "segments": []}

    speaker_segments: List[Dict] = []
    current_speaker = 1
    prev_end = segments[0].get("end", 0)
    SPEAKER_CHANGE_GAP = 1.5  # seconds

    for i, seg in enumerate(segments):
        seg_start = seg.get("start", 0)
        gap = seg_start - prev_end if i > 0 else 0
        if gap > SPEAKER_CHANGE_GAP and i > 0:
            current_speaker += 1
        speaker_segments.append(
            {
                "speaker": f"SPEAKER_{current_speaker:02d}",
                "start": seg.get("start"),
                "end": seg.get("end"),
                "text": seg.get("text", "").strip(),
            }
        )
        prev_end = seg.get("end", prev_end)

    return {
        "estimated_count": current_speaker,
        "segments": speaker_segments,
    }


# ── Node instance (for fusion_entry.py) ───────────────────────────────────────

class Node:
    """Simple callable wrapper used by FusionNode."""

    async def process(self, command: str, **params):
        if command == "transcribe":
            return await transcribe(TranscribeRequest(**params))
        if command == "analyze":
            return await analyze(AnalyzeRequest(**params))
        if command == "detect_language":
            return await detect_language(DetectLanguageRequest(**params))
        if command == "health":
            return await health()
        return {"error": f"Unknown command: {command}"}


def get_instance() -> Node:
    return Node()


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("NODE_94_PORT", str(_DEFAULT_PORT)))
    logger.info(f"Starting Node_{NODE_ID}_{NODE_NAME} on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
