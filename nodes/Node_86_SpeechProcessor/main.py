"""
Node 86: Speech Processor - 语音处理服务
Handles speech-to-text transcription, text-to-speech synthesis,
speech translation and language detection via multiple providers.
"""

import os
import json
import logging
import base64
import time
from typing import Dict, List, Optional, Any
from datetime import datetime
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

try:
    from core.port_config import get_node_port
    _port_from_config = get_node_port("Node_86_SpeechProcessor")
except Exception:
    _port_from_config = None

try:
    from nodes.common.cors_config import get_cors_origins
except ImportError:
    def get_cors_origins(): return ["*"]

# =============================================================================
# Configuration
# =============================================================================

NODE_ID = "86"
NODE_NAME = "SpeechProcessor"
PORT = _port_from_config or int(os.getenv("NODE_PORT", "8086"))

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format=f"[Node {NODE_ID}] %(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

SPEECH_PROVIDER = os.getenv("SPEECH_PROVIDER", "openai").lower()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
AZURE_SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY", "")
AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION", "eastus")
GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")

START_TIME = datetime.now()

# =============================================================================
# Pydantic Models
# =============================================================================

class TranscribeRequest(BaseModel):
    audio_base64: Optional[str] = Field(None, description="Base64-encoded audio data")
    audio_url: Optional[str] = Field(None, description="URL to fetch audio from")
    language: Optional[str] = Field(None, description="BCP-47 language code, e.g. 'en-US'")
    model: Optional[str] = Field(None, description="STT model name (provider-specific)")
    prompt: Optional[str] = Field(None, description="Optional context hint for transcription")
    response_format: Optional[str] = Field("json", description="Output format: json|text|srt|vtt")

class SynthesizeRequest(BaseModel):
    text: str = Field(..., description="Text to synthesize")
    voice: Optional[str] = Field(None, description="Voice name (provider-specific)")
    speed: Optional[float] = Field(1.0, ge=0.25, le=4.0, description="Speech speed multiplier")
    format: Optional[str] = Field("mp3", description="Output audio format: mp3|opus|aac|flac|wav")
    language: Optional[str] = Field(None, description="Language hint")

class TranslateRequest(BaseModel):
    audio_base64: Optional[str] = Field(None, description="Base64-encoded audio data")
    audio_url: Optional[str] = Field(None, description="URL to fetch audio from")
    target_language: str = Field(..., description="Target language code, e.g. 'en'")
    model: Optional[str] = Field(None, description="Translation model (provider-specific)")

class DetectLanguageRequest(BaseModel):
    audio_base64: Optional[str] = Field(None, description="Base64-encoded audio sample")
    audio_url: Optional[str] = Field(None, description="URL to audio sample")

class MCPCallRequest(BaseModel):
    tool: str
    parameters: Dict[str, Any] = {}

# =============================================================================
# Provider definitions
# =============================================================================

OPENAI_VOICES = [
    {"id": "alloy", "name": "Alloy", "gender": "neutral", "language": "en"},
    {"id": "echo", "name": "Echo", "gender": "male", "language": "en"},
    {"id": "fable", "name": "Fable", "gender": "male", "language": "en"},
    {"id": "onyx", "name": "Onyx", "gender": "male", "language": "en"},
    {"id": "nova", "name": "Nova", "gender": "female", "language": "en"},
    {"id": "shimmer", "name": "Shimmer", "gender": "female", "language": "en"},
]

OPENAI_STT_MODELS = [
    {"id": "whisper-1", "name": "Whisper v1", "languages": "multilingual", "provider": "openai"},
]

AZURE_VOICES = [
    {"id": "en-US-JennyNeural", "name": "Jenny (US)", "gender": "female", "language": "en-US"},
    {"id": "en-US-GuyNeural", "name": "Guy (US)", "gender": "male", "language": "en-US"},
    {"id": "en-GB-SoniaNeural", "name": "Sonia (GB)", "gender": "female", "language": "en-GB"},
    {"id": "zh-CN-XiaoxiaoNeural", "name": "Xiaoxiao (CN)", "gender": "female", "language": "zh-CN"},
    {"id": "ja-JP-NanamiNeural", "name": "Nanami (JP)", "gender": "female", "language": "ja-JP"},
]

AZURE_STT_MODELS = [
    {"id": "latest", "name": "Azure Speech Latest", "languages": "multilingual", "provider": "azure"},
]

GOOGLE_VOICES = [
    {"id": "en-US-Standard-A", "name": "Standard A (US)", "gender": "female", "language": "en-US"},
    {"id": "en-US-Standard-B", "name": "Standard B (US)", "gender": "male", "language": "en-US"},
    {"id": "en-US-Wavenet-A", "name": "WaveNet A (US)", "gender": "female", "language": "en-US"},
    {"id": "zh-CN-Standard-A", "name": "Standard A (CN)", "gender": "female", "language": "zh-CN"},
]

GOOGLE_STT_MODELS = [
    {"id": "latest_long", "name": "Latest Long (Google)", "languages": "multilingual", "provider": "google"},
    {"id": "latest_short", "name": "Latest Short (Google)", "languages": "multilingual", "provider": "google"},
    {"id": "command_and_search", "name": "Command & Search (Google)", "languages": "en", "provider": "google"},
]

# =============================================================================
# Speech Service
# =============================================================================

class SpeechService:
    """Core speech processing logic"""

    def _check_openai_key(self):
        if not OPENAI_API_KEY:
            return False, "OpenAI API key not configured. Set OPENAI_API_KEY env var."
        return True, None

    def _check_azure_key(self):
        if not AZURE_SPEECH_KEY:
            return False, "Azure Speech key not configured. Set AZURE_SPEECH_KEY env var."
        return True, None

    def _check_google_creds(self):
        if not GOOGLE_APPLICATION_CREDENTIALS:
            return False, "Google credentials not configured. Set GOOGLE_APPLICATION_CREDENTIALS env var."
        return True, None

    def _check_provider(self):
        if SPEECH_PROVIDER == "openai":
            return self._check_openai_key()
        elif SPEECH_PROVIDER == "azure":
            return self._check_azure_key()
        elif SPEECH_PROVIDER == "google":
            return self._check_google_creds()
        return False, f"Unknown provider: {SPEECH_PROVIDER}"

    async def _fetch_audio_bytes(self, req_base64: Optional[str], req_url: Optional[str]) -> bytes:
        if req_base64:
            # Strip data URI prefix if present
            if "," in req_base64:
                req_base64 = req_base64.split(",", 1)[1]
            return base64.b64decode(req_base64)
        if req_url:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(req_url)
                resp.raise_for_status()
                return resp.content
        raise ValueError("Provide either audio_base64 or audio_url")

    async def transcribe(self, req: TranscribeRequest) -> Dict[str, Any]:
        ok, err = self._check_provider()
        if not ok:
            return {"success": False, "error": err}

        try:
            audio_bytes = await self._fetch_audio_bytes(req.audio_base64, req.audio_url)
        except Exception as e:
            return {"success": False, "error": f"Failed to load audio: {e}"}

        if SPEECH_PROVIDER == "openai":
            return await self._transcribe_openai(audio_bytes, req)
        elif SPEECH_PROVIDER == "azure":
            return await self._transcribe_azure(audio_bytes, req)
        elif SPEECH_PROVIDER == "google":
            return await self._transcribe_google(audio_bytes, req)
        return {"success": False, "error": f"Unsupported provider: {SPEECH_PROVIDER}"}

    async def _transcribe_openai(self, audio_bytes: bytes, req: TranscribeRequest) -> Dict[str, Any]:
        model = req.model or "whisper-1"
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
        files = {"file": ("audio.wav", audio_bytes, "audio/wav")}
        data = {"model": model, "response_format": req.response_format or "json"}
        if req.language:
            data["language"] = req.language
        if req.prompt:
            data["prompt"] = req.prompt

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers=headers, files=files, data=data
            )
            resp.raise_for_status()
            result = resp.json() if req.response_format == "json" else {"text": resp.text}
            return {
                "success": True,
                "text": result.get("text", ""),
                "language": result.get("language"),
                "duration": result.get("duration"),
                "segments": result.get("segments"),
                "provider": "openai",
                "model": model,
            }

    async def _transcribe_azure(self, audio_bytes: bytes, req: TranscribeRequest) -> Dict[str, Any]:
        region = AZURE_SPEECH_REGION
        language = req.language or "en-US"
        url = (
            f"https://{region}.stt.speech.microsoft.com/speech/recognition/conversation/cognitiveservices/v1"
            f"?language={language}&format=detailed"
        )
        headers = {
            "Ocp-Apim-Subscription-Key": AZURE_SPEECH_KEY,
            "Content-Type": "audio/wav",
        }
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(url, headers=headers, content=audio_bytes)
            resp.raise_for_status()
            result = resp.json()
            best = result.get("NBest", [{}])[0]
            return {
                "success": True,
                "text": best.get("Display", result.get("DisplayText", "")),
                "confidence": best.get("Confidence"),
                "language": language,
                "provider": "azure",
            }

    async def _transcribe_google(self, audio_bytes: bytes, req: TranscribeRequest) -> Dict[str, Any]:
        # Uses Google Speech-to-Text REST API with service-account JSON auth
        language = req.language or "en-US"
        audio_b64 = base64.b64encode(audio_bytes).decode()
        payload = {
            "config": {
                "encoding": "LINEAR16",
                "languageCode": language,
                "model": req.model or "latest_long",
            },
            "audio": {"content": audio_b64},
        }
        async with httpx.AsyncClient(timeout=120) as client:
            # Obtain access token via metadata server or service account
            token_resp = await client.get(
                "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
                headers={"Metadata-Flavor": "Google"}, timeout=5
            )
            access_token = token_resp.json().get("access_token", "")
            resp = await client.post(
                "https://speech.googleapis.com/v1/speech:recognize",
                headers={"Authorization": f"Bearer {access_token}"},
                json=payload
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
            text = " ".join(
                r["alternatives"][0]["transcript"] for r in results if r.get("alternatives")
            )
            return {"success": True, "text": text, "language": language, "provider": "google"}

    async def synthesize(self, req: SynthesizeRequest) -> Dict[str, Any]:
        ok, err = self._check_provider()
        if not ok:
            return {"success": False, "error": err}

        if SPEECH_PROVIDER == "openai":
            return await self._synthesize_openai(req)
        elif SPEECH_PROVIDER == "azure":
            return await self._synthesize_azure(req)
        elif SPEECH_PROVIDER == "google":
            return await self._synthesize_google(req)
        return {"success": False, "error": f"Unsupported provider: {SPEECH_PROVIDER}"}

    async def _synthesize_openai(self, req: SynthesizeRequest) -> Dict[str, Any]:
        voice = req.voice or "alloy"
        fmt = req.format or "mp3"
        payload = {
            "model": "tts-1",
            "input": req.text,
            "voice": voice,
            "speed": req.speed or 1.0,
            "response_format": fmt,
        }
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post("https://api.openai.com/v1/audio/speech", headers=headers, json=payload)
            resp.raise_for_status()
            audio_b64 = base64.b64encode(resp.content).decode()
            return {
                "success": True,
                "audio_base64": audio_b64,
                "format": fmt,
                "voice": voice,
                "provider": "openai",
                "size_bytes": len(resp.content),
            }

    async def _synthesize_azure(self, req: SynthesizeRequest) -> Dict[str, Any]:
        voice = req.voice or "en-US-JennyNeural"
        rate = f"+{int((req.speed - 1.0) * 100)}%" if req.speed else "+0%"
        ssml = (
            f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-US">'
            f'<voice name="{voice}"><prosody rate="{rate}">{req.text}</prosody></voice></speak>'
        )
        url = f"https://{AZURE_SPEECH_REGION}.tts.speech.microsoft.com/cognitiveservices/v1"
        headers = {
            "Ocp-Apim-Subscription-Key": AZURE_SPEECH_KEY,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3",
        }
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, headers=headers, content=ssml.encode())
            resp.raise_for_status()
            audio_b64 = base64.b64encode(resp.content).decode()
            return {
                "success": True,
                "audio_base64": audio_b64,
                "format": "mp3",
                "voice": voice,
                "provider": "azure",
                "size_bytes": len(resp.content),
            }

    async def _synthesize_google(self, req: SynthesizeRequest) -> Dict[str, Any]:
        voice_name = req.voice or "en-US-Standard-A"
        lang = req.language or "en-US"
        payload = {
            "input": {"text": req.text},
            "voice": {"languageCode": lang, "name": voice_name},
            "audioConfig": {"audioEncoding": req.format.upper() if req.format else "MP3"},
        }
        async with httpx.AsyncClient(timeout=60) as client:
            token_resp = await client.get(
                "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
                headers={"Metadata-Flavor": "Google"}, timeout=5
            )
            access_token = token_resp.json().get("access_token", "")
            resp = await client.post(
                "https://texttospeech.googleapis.com/v1/text:synthesize",
                headers={"Authorization": f"Bearer {access_token}"},
                json=payload
            )
            resp.raise_for_status()
            audio_b64 = resp.json().get("audioContent", "")
            audio_bytes = base64.b64decode(audio_b64)
            return {
                "success": True,
                "audio_base64": audio_b64,
                "format": req.format or "mp3",
                "voice": voice_name,
                "provider": "google",
                "size_bytes": len(audio_bytes),
            }

    async def translate(self, req: TranslateRequest) -> Dict[str, Any]:
        ok, err = self._check_provider()
        if not ok:
            return {"success": False, "error": err}

        try:
            audio_bytes = await self._fetch_audio_bytes(req.audio_base64, req.audio_url)
        except Exception as e:
            return {"success": False, "error": f"Failed to load audio: {e}"}

        if SPEECH_PROVIDER == "openai":
            return await self._translate_openai(audio_bytes, req)
        return {
            "success": False,
            "error": f"Speech translation not supported for provider: {SPEECH_PROVIDER}. Use 'openai'."
        }

    async def _translate_openai(self, audio_bytes: bytes, req: TranslateRequest) -> Dict[str, Any]:
        # OpenAI Whisper translation endpoint translates to English
        if req.target_language not in ("en", "en-US", "english"):
            return {
                "success": False,
                "error": "OpenAI Whisper translation only supports English as target language.",
            }
        model = req.model or "whisper-1"
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
        files = {"file": ("audio.wav", audio_bytes, "audio/wav")}
        data = {"model": model, "response_format": "json"}
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                "https://api.openai.com/v1/audio/translations",
                headers=headers, files=files, data=data
            )
            resp.raise_for_status()
            result = resp.json()
            return {
                "success": True,
                "text": result.get("text", ""),
                "target_language": "en",
                "provider": "openai",
                "model": model,
            }

    async def detect_language(self, req: DetectLanguageRequest) -> Dict[str, Any]:
        ok, err = self._check_provider()
        if not ok:
            return {"success": False, "error": err}

        try:
            audio_bytes = await self._fetch_audio_bytes(req.audio_base64, req.audio_url)
        except Exception as e:
            return {"success": False, "error": f"Failed to load audio: {e}"}

        if SPEECH_PROVIDER == "openai":
            # Transcribe with verbose_json to get language
            headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
            files = {"file": ("audio.wav", audio_bytes, "audio/wav")}
            data = {"model": "whisper-1", "response_format": "verbose_json"}
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers=headers, files=files, data=data
                )
                resp.raise_for_status()
                result = resp.json()
                return {
                    "success": True,
                    "detected_language": result.get("language"),
                    "confidence": None,
                    "provider": "openai",
                }
        elif SPEECH_PROVIDER == "azure":
            # Azure supports auto-detect
            url = (
                f"https://{AZURE_SPEECH_REGION}.stt.speech.microsoft.com/speech/recognition/conversation/cognitiveservices/v1"
                f"?language=en-US&format=detailed"
            )
            headers = {
                "Ocp-Apim-Subscription-Key": AZURE_SPEECH_KEY,
                "Content-Type": "audio/wav",
            }
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(url, headers=headers, content=audio_bytes)
                resp.raise_for_status()
                result = resp.json()
                return {
                    "success": True,
                    "detected_language": result.get("PrimaryLanguage", {}).get("Language"),
                    "confidence": result.get("PrimaryLanguage", {}).get("Confidence"),
                    "provider": "azure",
                }
        return {"success": False, "error": f"Language detection not implemented for provider: {SPEECH_PROVIDER}"}

    def get_voices(self) -> Dict[str, Any]:
        if SPEECH_PROVIDER == "openai":
            return {"success": True, "provider": "openai", "voices": OPENAI_VOICES}
        elif SPEECH_PROVIDER == "azure":
            return {"success": True, "provider": "azure", "voices": AZURE_VOICES}
        elif SPEECH_PROVIDER == "google":
            return {"success": True, "provider": "google", "voices": GOOGLE_VOICES}
        return {"success": False, "error": f"Unknown provider: {SPEECH_PROVIDER}"}

    def get_models(self) -> Dict[str, Any]:
        if SPEECH_PROVIDER == "openai":
            return {"success": True, "provider": "openai", "models": OPENAI_STT_MODELS}
        elif SPEECH_PROVIDER == "azure":
            return {"success": True, "provider": "azure", "models": AZURE_STT_MODELS}
        elif SPEECH_PROVIDER == "google":
            return {"success": True, "provider": "google", "models": GOOGLE_STT_MODELS}
        return {"success": False, "error": f"Unknown provider: {SPEECH_PROVIDER}"}


speech_service = SpeechService()

# =============================================================================
# App
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"🎙️ Node {NODE_ID} {NODE_NAME} starting on port {PORT}")
    logger.info(f"  Provider : {SPEECH_PROVIDER}")
    logger.info(f"  OpenAI   : {'configured' if OPENAI_API_KEY else 'not set'}")
    logger.info(f"  Azure    : {'configured' if AZURE_SPEECH_KEY else 'not set'}")
    logger.info(f"  Google   : {'configured' if GOOGLE_APPLICATION_CREDENTIALS else 'not set'}")
    yield
    logger.info(f"Node {NODE_ID} shutting down")


app = FastAPI(
    title=f"Node {NODE_ID} - {NODE_NAME}",
    description="Speech/audio processing: STT, TTS, translation and language detection",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# Routes
# =============================================================================

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "node_id": NODE_ID,
        "name": NODE_NAME,
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/status")
async def status():
    uptime = (datetime.now() - START_TIME).total_seconds()
    return {
        "node_id": NODE_ID,
        "name": NODE_NAME,
        "status": "running",
        "uptime_seconds": uptime,
        "provider": SPEECH_PROVIDER,
        "configuration": {
            "openai_configured": bool(OPENAI_API_KEY),
            "azure_configured": bool(AZURE_SPEECH_KEY),
            "azure_region": AZURE_SPEECH_REGION if AZURE_SPEECH_KEY else None,
            "google_configured": bool(GOOGLE_APPLICATION_CREDENTIALS),
        },
        "capabilities": ["transcribe", "synthesize", "translate", "detect_language"],
        "timestamp": datetime.now().isoformat(),
    }


@app.post("/transcribe")
async def transcribe(req: TranscribeRequest):
    if not req.audio_base64 and not req.audio_url:
        raise HTTPException(status_code=400, detail="Provide audio_base64 or audio_url")
    result = await speech_service.transcribe(req)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@app.post("/synthesize")
async def synthesize(req: SynthesizeRequest):
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="text must not be empty")
    result = await speech_service.synthesize(req)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@app.post("/translate")
async def translate(req: TranslateRequest):
    if not req.audio_base64 and not req.audio_url:
        raise HTTPException(status_code=400, detail="Provide audio_base64 or audio_url")
    result = await speech_service.translate(req)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@app.get("/voices")
async def voices():
    return speech_service.get_voices()


@app.get("/models")
async def models():
    return speech_service.get_models()


@app.post("/detect_language")
async def detect_language(req: DetectLanguageRequest):
    if not req.audio_base64 and not req.audio_url:
        raise HTTPException(status_code=400, detail="Provide audio_base64 or audio_url")
    result = await speech_service.detect_language(req)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@app.post("/mcp/call")
async def mcp_call(req: MCPCallRequest):
    tool = req.tool
    params = req.parameters

    dispatch = {
        "transcribe": lambda: speech_service.transcribe(TranscribeRequest(**params)),
        "synthesize": lambda: speech_service.synthesize(SynthesizeRequest(**params)),
        "translate": lambda: speech_service.translate(TranslateRequest(**params)),
        "detect_language": lambda: speech_service.detect_language(DetectLanguageRequest(**params)),
        "get_voices": lambda: speech_service.get_voices(),
        "get_models": lambda: speech_service.get_models(),
    }

    if tool not in dispatch:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown tool '{tool}'. Available: {list(dispatch.keys())}"
        )

    fn = dispatch[tool]()
    if asyncio.iscoroutine(fn):
        result = await fn
    else:
        result = fn
    return result


def get_instance():
    return speech_service


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
