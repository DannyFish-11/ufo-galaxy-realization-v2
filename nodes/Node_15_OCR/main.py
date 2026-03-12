"""
Node 15: OCR - 图像文字识别节点
=================================
支持 DeepSeek VL2（主引擎）和 Tesseract（备用引擎）双引擎 OCR
"""
import base64
import io
import os
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from nodes.common.cors_config import get_cors_origins

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import pytesseract
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False
    pytesseract = None  # type: ignore

# ── 配置 ──────────────────────────────────────────────────────────────────────
PORT = 8015
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/v1")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-vl2")
TESSERACT_CMD = os.getenv("TESSERACT_CMD", "")

if TESSERACT_CMD and TESSERACT_AVAILABLE:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

# ── 应用初始化 ────────────────────────────────────────────────────────────────
app = FastAPI(title="Node 15 - OCR", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 统计 ──────────────────────────────────────────────────────────────────────
_stats: Dict[str, int] = {"total_requests": 0, "success_count": 0}

# ── 辅助函数 ──────────────────────────────────────────────────────────────────

def _decode_image(image_base64: str) -> "Image.Image":
    if not PIL_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail={"error": "Pillow not installed", "success": False},
        )
    try:
        data = base64.b64decode(image_base64)
        return Image.open(io.BytesIO(data))
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": f"Invalid image data: {exc}", "success": False},
        )


async def _fetch_image_base64(url: str) -> str:
    if not HTTPX_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail={"error": "httpx not installed", "success": False},
        )
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url)
    if resp.status_code >= 400:
        raise HTTPException(
            status_code=resp.status_code,
            detail={"error": f"Failed to fetch image from URL: {resp.status_code}", "success": False},
        )
    return base64.b64encode(resp.content).decode()


async def _ocr_deepseek(image_base64: str, prompt: str) -> Dict[str, Any]:
    if not DEEPSEEK_API_KEY:
        raise HTTPException(
            status_code=503,
            detail={"error": "DEEPSEEK_API_KEY not configured", "success": False},
        )
    if not HTTPX_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail={"error": "httpx not installed", "success": False},
        )
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        "max_tokens": 4096,
    }
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(f"{DEEPSEEK_API_URL}/chat/completions", json=payload, headers=headers)
    if resp.status_code >= 400:
        raise HTTPException(
            status_code=resp.status_code,
            detail={"error": f"DeepSeek API error: {resp.text}", "success": False},
        )
    result = resp.json()
    text = result["choices"][0]["message"]["content"]
    return {"text": text, "engine_used": "deepseek", "model": DEEPSEEK_MODEL}


def _ocr_tesseract(image: "Image.Image") -> Dict[str, Any]:
    if not TESSERACT_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail={"error": "pytesseract not installed or Tesseract binary not found", "success": False},
        )
    try:
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
        text = pytesseract.image_to_string(image)
        confidences = [int(c) for c in data["conf"] if str(c).lstrip("-").isdigit() and int(c) >= 0]
        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
        return {"text": text.strip(), "engine_used": "tesseract", "confidence": round(avg_conf, 2)}
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"error": f"Tesseract error: {exc}", "success": False},
        )

# ── 请求模型 ──────────────────────────────────────────────────────────────────

class OcrRequest(BaseModel):
    image_base64: str
    engine: str = "auto"
    prompt: str = "Extract all text from this image. Return only the extracted text."


class OcrUrlRequest(BaseModel):
    url: str
    engine: str = "auto"
    prompt: str = "Extract all text from this image. Return only the extracted text."


class DetectLanguageRequest(BaseModel):
    image_base64: str

# ── 端点 ──────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "success": True,
        "status": "healthy",
        "node_id": "15",
        "name": "OCR",
        "port": PORT,
        "deepseek_configured": bool(DEEPSEEK_API_KEY),
        "tesseract_available": TESSERACT_AVAILABLE,
        "httpx_available": HTTPX_AVAILABLE,
        "pil_available": PIL_AVAILABLE,
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/status")
async def status():
    engines = []
    if DEEPSEEK_API_KEY and HTTPX_AVAILABLE:
        engines.append("deepseek")
    if TESSERACT_AVAILABLE:
        engines.append("tesseract")
    return {
        "success": True,
        "config": {
            "deepseek_api_url": DEEPSEEK_API_URL,
            "deepseek_model": DEEPSEEK_MODEL,
            "tesseract_cmd": TESSERACT_CMD or "system default",
        },
        "engines_available": engines,
        "stats": _stats,
        "timestamp": datetime.now().isoformat(),
    }


@app.post("/ocr")
async def ocr(request: OcrRequest):
    _stats["total_requests"] += 1
    engine = request.engine.lower()

    if engine == "deepseek":
        result = await _ocr_deepseek(request.image_base64, request.prompt)
    elif engine == "tesseract":
        image = _decode_image(request.image_base64)
        result = _ocr_tesseract(image)
    elif engine == "auto":
        if DEEPSEEK_API_KEY and HTTPX_AVAILABLE:
            result = await _ocr_deepseek(request.image_base64, request.prompt)
        elif TESSERACT_AVAILABLE:
            image = _decode_image(request.image_base64)
            result = _ocr_tesseract(image)
        else:
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "No OCR engine available. Configure DEEPSEEK_API_KEY or install pytesseract.",
                    "success": False,
                },
            )
    else:
        raise HTTPException(
            status_code=400,
            detail={"error": f"Unknown engine '{engine}'. Use 'auto', 'deepseek', or 'tesseract'.", "success": False},
        )

    _stats["success_count"] += 1
    return {"success": True, **result}


@app.post("/ocr/url")
async def ocr_url(request: OcrUrlRequest):
    image_base64 = await _fetch_image_base64(request.url)
    ocr_request = OcrRequest(
        image_base64=image_base64,
        engine=request.engine,
        prompt=request.prompt,
    )
    return await ocr(ocr_request)


@app.post("/ocr/detect-language")
async def detect_language(request: DetectLanguageRequest):
    _stats["total_requests"] += 1
    prompt = (
        "Detect the language(s) of the text in this image. "
        "Return a JSON object: {\"language\": \"<name>\", \"code\": \"<ISO 639-1>\", \"confidence\": <0-1>}. "
        "If multiple languages, return the primary one."
    )

    if DEEPSEEK_API_KEY and HTTPX_AVAILABLE:
        result = await _ocr_deepseek(request.image_base64, prompt)
        _stats["success_count"] += 1
        return {"success": True, "engine_used": result["engine_used"], "detection": result["text"]}
    elif TESSERACT_AVAILABLE:
        image = _decode_image(request.image_base64)
        try:
            osd = pytesseract.image_to_osd(image)
            _stats["success_count"] += 1
            return {"success": True, "engine_used": "tesseract", "detection": osd}
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail={"error": f"Language detection failed: {exc}", "success": False},
            )
    else:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "No OCR engine available for language detection.",
                "success": False,
            },
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
