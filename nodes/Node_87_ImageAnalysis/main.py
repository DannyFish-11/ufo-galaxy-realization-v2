"""
Node 87: Image Analysis - 图像分析服务
Computer vision: image captioning, object detection, OCR, classification,
color analysis and image comparison via multiple providers.
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
    _port_from_config = get_node_port("Node_87_ImageAnalysis")
except Exception:
    _port_from_config = None

try:
    from nodes.common.cors_config import get_cors_origins
except ImportError:
    def get_cors_origins(): return ["*"]

# =============================================================================
# Configuration
# =============================================================================

NODE_ID = "87"
NODE_NAME = "ImageAnalysis"
PORT = _port_from_config or int(os.getenv("NODE_PORT", "8087"))

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format=f"[Node {NODE_ID}] %(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

VISION_PROVIDER = os.getenv("VISION_PROVIDER", "openai").lower()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
AZURE_VISION_KEY = os.getenv("AZURE_VISION_KEY", "")
AZURE_VISION_ENDPOINT = os.getenv("AZURE_VISION_ENDPOINT", "")

START_TIME = datetime.now()

SUPPORTED_FEATURES = ["caption", "objects", "tags", "color", "faces"]

# =============================================================================
# Pydantic Models
# =============================================================================

class ImageInput(BaseModel):
    image_base64: Optional[str] = Field(None, description="Base64-encoded image data")
    image_url: Optional[str] = Field(None, description="URL of the image")

class AnalyzeRequest(ImageInput):
    features: Optional[List[str]] = Field(
        default=["caption", "objects", "tags"],
        description=f"Features to analyze: {SUPPORTED_FEATURES}"
    )

class DescribeRequest(ImageInput):
    detail: Optional[str] = Field("high", description="Detail level: low|high")
    language: Optional[str] = Field("en", description="Response language")

class OcrRequest(ImageInput):
    language: Optional[str] = Field(None, description="Expected text language hint")

class ClassifyRequest(ImageInput):
    categories: Optional[List[str]] = Field(None, description="Custom category list")
    top_k: Optional[int] = Field(5, ge=1, le=20, description="Number of top categories")

class DetectObjectsRequest(ImageInput):
    confidence_threshold: Optional[float] = Field(0.5, ge=0.0, le=1.0)

class CompareRequest(BaseModel):
    image1_base64: Optional[str] = None
    image1_url: Optional[str] = None
    image2_base64: Optional[str] = None
    image2_url: Optional[str] = None

class MCPCallRequest(BaseModel):
    tool: str
    parameters: Dict[str, Any] = {}

# =============================================================================
# Image Analysis Service
# =============================================================================

class ImageAnalysisService:

    def _check_provider(self):
        if VISION_PROVIDER == "openai":
            if not OPENAI_API_KEY:
                return False, "OpenAI API key not configured. Set OPENAI_API_KEY env var."
        elif VISION_PROVIDER == "azure":
            if not AZURE_VISION_KEY:
                return False, "Azure Vision key not configured. Set AZURE_VISION_KEY env var."
            if not AZURE_VISION_ENDPOINT:
                return False, "Azure Vision endpoint not configured. Set AZURE_VISION_ENDPOINT env var."
        elif VISION_PROVIDER == "google":
            pass  # Google uses ADC; will fail at call time with clear error
        else:
            return False, f"Unknown provider: {VISION_PROVIDER}"
        return True, None

    def _build_image_content(self, image_base64: Optional[str], image_url: Optional[str]) -> dict:
        """Build an OpenAI-style image_url content dict."""
        if image_url:
            return {"type": "image_url", "image_url": {"url": image_url, "detail": "high"}}
        if image_base64:
            if "," in image_base64:
                image_base64 = image_base64.split(",", 1)[1]
            data_url = f"data:image/jpeg;base64,{image_base64}"
            return {"type": "image_url", "image_url": {"url": data_url, "detail": "high"}}
        raise ValueError("Provide image_base64 or image_url")

    async def _openai_vision(self, prompt: str, image_base64: Optional[str], image_url: Optional[str]) -> str:
        image_content = self._build_image_content(image_base64, image_url)
        payload = {
            "model": "gpt-4o",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        image_content,
                    ],
                }
            ],
            "max_tokens": 1024,
        }
        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

    async def _azure_vision_analyze(self, features: List[str], image_base64: Optional[str], image_url: Optional[str]) -> dict:
        feature_map = {
            "caption": "captions",
            "objects": "objects",
            "tags": "tags",
            "color": "color",
            "faces": "faces",
        }
        azure_features = list({feature_map.get(f, f) for f in features if f in feature_map})
        params = {"features": ",".join(azure_features), "api-version": "2023-02-01-preview"}
        headers = {"Ocp-Apim-Subscription-Key": AZURE_VISION_KEY}
        endpoint = AZURE_VISION_ENDPOINT.rstrip("/")
        url = f"{endpoint}/computervision/imageanalysis:analyze"

        async with httpx.AsyncClient(timeout=60) as client:
            if image_url:
                headers["Content-Type"] = "application/json"
                resp = await client.post(url, headers=headers, params=params, json={"url": image_url})
            else:
                if image_base64 and "," in image_base64:
                    image_base64 = image_base64.split(",", 1)[1]
                img_bytes = base64.b64decode(image_base64)
                headers["Content-Type"] = "application/octet-stream"
                resp = await client.post(url, headers=headers, params=params, content=img_bytes)
            resp.raise_for_status()
            return resp.json()

    async def analyze(self, req: AnalyzeRequest) -> Dict[str, Any]:
        ok, err = self._check_provider()
        if not ok:
            return {"success": False, "error": err}
        if not req.image_base64 and not req.image_url:
            return {"success": False, "error": "Provide image_base64 or image_url"}

        features = req.features or ["caption", "objects", "tags"]
        invalid = [f for f in features if f not in SUPPORTED_FEATURES]
        if invalid:
            return {"success": False, "error": f"Invalid features: {invalid}. Supported: {SUPPORTED_FEATURES}"}

        try:
            if VISION_PROVIDER == "openai":
                prompt = (
                    f"Analyze this image and provide a structured JSON response with these sections: {features}. "
                    "For 'caption': a short description. For 'objects': list of detected objects with confidence. "
                    "For 'tags': relevant keyword tags. For 'color': dominant colors. For 'faces': face count and attributes. "
                    "Return ONLY valid JSON."
                )
                text = await self._openai_vision(prompt, req.image_base64, req.image_url)
                try:
                    parsed = json.loads(text)
                except Exception:
                    parsed = {"raw_analysis": text}
                return {"success": True, "provider": "openai", "features": features, "analysis": parsed}

            elif VISION_PROVIDER == "azure":
                result = await self._azure_vision_analyze(features, req.image_base64, req.image_url)
                analysis = {}
                if "captionResult" in result:
                    analysis["caption"] = result["captionResult"]
                if "objectsResult" in result:
                    analysis["objects"] = result["objectsResult"].get("values", [])
                if "tagsResult" in result:
                    analysis["tags"] = result["tagsResult"].get("values", [])
                if "colorResult" in result:
                    analysis["color"] = result["colorResult"]
                if "peopleResult" in result:
                    analysis["faces"] = result["peopleResult"].get("values", [])
                return {"success": True, "provider": "azure", "features": features, "analysis": analysis}

        except Exception as e:
            logger.error(f"analyze error: {e}")
            return {"success": False, "error": str(e)}

    async def describe(self, req: DescribeRequest) -> Dict[str, Any]:
        ok, err = self._check_provider()
        if not ok:
            return {"success": False, "error": err}
        if not req.image_base64 and not req.image_url:
            return {"success": False, "error": "Provide image_base64 or image_url"}

        try:
            lang = req.language or "en"
            prompt = (
                f"Describe this image in detail in {lang}. Include: what is shown, setting/context, "
                "notable elements, mood or atmosphere, any text visible. Be comprehensive."
            )
            if VISION_PROVIDER == "openai":
                description = await self._openai_vision(prompt, req.image_base64, req.image_url)
                return {"success": True, "description": description, "language": lang, "provider": "openai"}
            elif VISION_PROVIDER == "azure":
                result = await self._azure_vision_analyze(["caption", "tags"], req.image_base64, req.image_url)
                caption = result.get("captionResult", {}).get("text", "")
                tags = [t["name"] for t in result.get("tagsResult", {}).get("values", [])]
                description = f"{caption}. Tags: {', '.join(tags)}"
                return {"success": True, "description": description, "language": lang, "provider": "azure"}
        except Exception as e:
            logger.error(f"describe error: {e}")
            return {"success": False, "error": str(e)}

    async def ocr(self, req: OcrRequest) -> Dict[str, Any]:
        ok, err = self._check_provider()
        if not ok:
            return {"success": False, "error": err}
        if not req.image_base64 and not req.image_url:
            return {"success": False, "error": "Provide image_base64 or image_url"}

        try:
            if VISION_PROVIDER == "openai":
                prompt = (
                    "Extract ALL text from this image exactly as it appears. "
                    "Preserve line breaks and formatting. Return ONLY the extracted text, nothing else."
                )
                text = await self._openai_vision(prompt, req.image_base64, req.image_url)
                lines = [l for l in text.strip().splitlines() if l.strip()]
                return {
                    "success": True,
                    "text": text.strip(),
                    "lines": lines,
                    "word_count": len(text.split()),
                    "provider": "openai",
                }
            elif VISION_PROVIDER == "azure":
                endpoint = AZURE_VISION_ENDPOINT.rstrip("/")
                url = f"{endpoint}/computervision/imageanalysis:analyze"
                params = {"features": "read", "api-version": "2023-02-01-preview"}
                headers = {"Ocp-Apim-Subscription-Key": AZURE_VISION_KEY}
                async with httpx.AsyncClient(timeout=60) as client:
                    if req.image_url:
                        headers["Content-Type"] = "application/json"
                        resp = await client.post(url, headers=headers, params=params, json={"url": req.image_url})
                    else:
                        img_b64 = req.image_base64
                        if img_b64 and "," in img_b64:
                            img_b64 = img_b64.split(",", 1)[1]
                        headers["Content-Type"] = "application/octet-stream"
                        resp = await client.post(url, headers=headers, params=params, content=base64.b64decode(img_b64))
                    resp.raise_for_status()
                    result = resp.json()
                read_result = result.get("readResult", {})
                blocks = read_result.get("blocks", [])
                all_lines = []
                full_text_parts = []
                for block in blocks:
                    for line in block.get("lines", []):
                        all_lines.append(line.get("text", ""))
                        full_text_parts.append(line.get("text", ""))
                full_text = "\n".join(full_text_parts)
                return {
                    "success": True,
                    "text": full_text,
                    "lines": all_lines,
                    "word_count": len(full_text.split()),
                    "provider": "azure",
                }
        except Exception as e:
            logger.error(f"ocr error: {e}")
            return {"success": False, "error": str(e)}

    async def classify(self, req: ClassifyRequest) -> Dict[str, Any]:
        ok, err = self._check_provider()
        if not ok:
            return {"success": False, "error": err}
        if not req.image_base64 and not req.image_url:
            return {"success": False, "error": "Provide image_base64 or image_url"}

        try:
            top_k = req.top_k or 5
            if req.categories:
                prompt = (
                    f"Classify this image into the most relevant categories from this list: {req.categories}. "
                    f"Return the top {top_k} as JSON: {{\"classifications\": [{{\"category\": \"...\", \"confidence\": 0.0-1.0}}]}}"
                )
            else:
                prompt = (
                    f"Classify this image. Return the top {top_k} categories as JSON: "
                    "{\"classifications\": [{\"category\": \"...\", \"confidence\": 0.0-1.0}]}. "
                    "Return ONLY valid JSON."
                )

            if VISION_PROVIDER == "openai":
                text = await self._openai_vision(prompt, req.image_base64, req.image_url)
                try:
                    parsed = json.loads(text)
                    classifications = parsed.get("classifications", [])
                except Exception:
                    classifications = [{"category": text, "confidence": 1.0}]
                return {"success": True, "classifications": classifications, "provider": "openai"}
            elif VISION_PROVIDER == "azure":
                result = await self._azure_vision_analyze(["tags"], req.image_base64, req.image_url)
                tags = result.get("tagsResult", {}).get("values", [])[:top_k]
                classifications = [{"category": t["name"], "confidence": t.get("confidence", 0.0)} for t in tags]
                return {"success": True, "classifications": classifications, "provider": "azure"}
        except Exception as e:
            logger.error(f"classify error: {e}")
            return {"success": False, "error": str(e)}

    async def detect_objects(self, req: DetectObjectsRequest) -> Dict[str, Any]:
        ok, err = self._check_provider()
        if not ok:
            return {"success": False, "error": err}
        if not req.image_base64 and not req.image_url:
            return {"success": False, "error": "Provide image_base64 or image_url"}

        threshold = req.confidence_threshold or 0.5
        try:
            if VISION_PROVIDER == "openai":
                prompt = (
                    f"Detect and locate all objects in this image with confidence >= {threshold}. "
                    "Return JSON: {\"objects\": [{\"label\": \"...\", \"confidence\": 0.0-1.0, "
                    "\"bounding_box\": {\"x\": %, \"y\": %, \"width\": %, \"height\": %}}]}. "
                    "Bounding box values are percentages (0-100) of image dimensions. Return ONLY valid JSON."
                )
                text = await self._openai_vision(prompt, req.image_base64, req.image_url)
                try:
                    parsed = json.loads(text)
                    objects = parsed.get("objects", [])
                except Exception:
                    objects = []
                return {"success": True, "objects": objects, "count": len(objects), "provider": "openai"}
            elif VISION_PROVIDER == "azure":
                result = await self._azure_vision_analyze(["objects"], req.image_base64, req.image_url)
                raw_objects = result.get("objectsResult", {}).get("values", [])
                objects = [
                    {
                        "label": o.get("tags", [{}])[0].get("name", "") if o.get("tags") else "",
                        "confidence": o.get("tags", [{}])[0].get("confidence", 0.0) if o.get("tags") else 0.0,
                        "bounding_box": o.get("boundingBox", {}),
                    }
                    for o in raw_objects
                    if (o.get("tags", [{}])[0].get("confidence", 0.0) if o.get("tags") else 0.0) >= threshold
                ]
                return {"success": True, "objects": objects, "count": len(objects), "provider": "azure"}
        except Exception as e:
            logger.error(f"detect_objects error: {e}")
            return {"success": False, "error": str(e)}

    async def compare(self, req: CompareRequest) -> Dict[str, Any]:
        ok, err = self._check_provider()
        if not ok:
            return {"success": False, "error": err}
        if not (req.image1_base64 or req.image1_url):
            return {"success": False, "error": "Provide image1_base64 or image1_url"}
        if not (req.image2_base64 or req.image2_url):
            return {"success": False, "error": "Provide image2_base64 or image2_url"}

        try:
            if VISION_PROVIDER == "openai":
                img1_content = self._build_image_content(req.image1_base64, req.image1_url)
                img2_content = self._build_image_content(req.image2_base64, req.image2_url)
                prompt = (
                    "Compare these two images and return JSON: "
                    "{\"similarity_score\": 0.0-1.0, \"similarities\": [...], \"differences\": [...], "
                    "\"summary\": \"...\"}. Return ONLY valid JSON."
                )
                payload = {
                    "model": "gpt-4o",
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                img1_content,
                                img2_content,
                            ],
                        }
                    ],
                    "max_tokens": 1024,
                }
                headers = {
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                }
                async with httpx.AsyncClient(timeout=60) as client:
                    resp = await client.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
                    resp.raise_for_status()
                    text = resp.json()["choices"][0]["message"]["content"]
                try:
                    parsed = json.loads(text)
                except Exception:
                    parsed = {"raw_comparison": text}
                return {"success": True, "comparison": parsed, "provider": "openai"}
            else:
                return {
                    "success": False,
                    "error": f"Image comparison is only supported with the 'openai' provider. Current: {VISION_PROVIDER}"
                }
        except Exception as e:
            logger.error(f"compare error: {e}")
            return {"success": False, "error": str(e)}


image_service = ImageAnalysisService()

# =============================================================================
# App
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"🖼️  Node {NODE_ID} {NODE_NAME} starting on port {PORT}")
    logger.info(f"  Provider : {VISION_PROVIDER}")
    logger.info(f"  OpenAI   : {'configured' if OPENAI_API_KEY else 'not set'}")
    logger.info(f"  Azure    : {'configured' if AZURE_VISION_KEY else 'not set'}")
    yield
    logger.info(f"Node {NODE_ID} shutting down")


app = FastAPI(
    title=f"Node {NODE_ID} - {NODE_NAME}",
    description="Computer vision: analyze, describe, OCR, classify, detect objects, compare images",
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
        "provider": VISION_PROVIDER,
        "configuration": {
            "openai_configured": bool(OPENAI_API_KEY),
            "azure_configured": bool(AZURE_VISION_KEY) and bool(AZURE_VISION_ENDPOINT),
        },
        "supported_features": SUPPORTED_FEATURES,
        "capabilities": ["analyze", "describe", "ocr", "classify", "detect_objects", "compare"],
        "timestamp": datetime.now().isoformat(),
    }


@app.post("/analyze")
async def analyze(req: AnalyzeRequest):
    if not req.image_base64 and not req.image_url:
        raise HTTPException(status_code=400, detail="Provide image_base64 or image_url")
    result = await image_service.analyze(req)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@app.post("/describe")
async def describe(req: DescribeRequest):
    if not req.image_base64 and not req.image_url:
        raise HTTPException(status_code=400, detail="Provide image_base64 or image_url")
    result = await image_service.describe(req)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@app.post("/ocr")
async def ocr(req: OcrRequest):
    if not req.image_base64 and not req.image_url:
        raise HTTPException(status_code=400, detail="Provide image_base64 or image_url")
    result = await image_service.ocr(req)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@app.post("/classify")
async def classify(req: ClassifyRequest):
    if not req.image_base64 and not req.image_url:
        raise HTTPException(status_code=400, detail="Provide image_base64 or image_url")
    result = await image_service.classify(req)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@app.post("/detect_objects")
async def detect_objects(req: DetectObjectsRequest):
    if not req.image_base64 and not req.image_url:
        raise HTTPException(status_code=400, detail="Provide image_base64 or image_url")
    result = await image_service.detect_objects(req)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@app.post("/compare")
async def compare(req: CompareRequest):
    result = await image_service.compare(req)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@app.post("/mcp/call")
async def mcp_call(req: MCPCallRequest):
    tool = req.tool
    params = req.parameters

    async def _dispatch():
        if tool == "analyze":
            return await image_service.analyze(AnalyzeRequest(**params))
        elif tool == "describe":
            return await image_service.describe(DescribeRequest(**params))
        elif tool == "ocr":
            return await image_service.ocr(OcrRequest(**params))
        elif tool == "classify":
            return await image_service.classify(ClassifyRequest(**params))
        elif tool == "detect_objects":
            return await image_service.detect_objects(DetectObjectsRequest(**params))
        elif tool == "compare":
            return await image_service.compare(CompareRequest(**params))
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown tool '{tool}'. Available: analyze, describe, ocr, classify, detect_objects, compare"
            )

    return await _dispatch()


def get_instance():
    return image_service


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
