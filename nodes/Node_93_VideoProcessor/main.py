#!/usr/bin/env python3
"""
Node 93: Video Processor
视频处理与分析节点

功能:
1. 视频帧分析（通过多模态 LLM）
2. 关键帧信息提取（基于视频 URL 元数据）
3. 视频内容摘要生成
4. 缩略图生成（Base64 图像处理）
5. 视频元数据提取
6. 支持格式查询
"""

import os
import base64
import logging
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx

# CORS origins - fall back to wildcard if module unavailable
try:
    from nodes.common.cors_config import get_cors_origins
    _cors_origins = get_cors_origins()
except Exception:
    _cors_origins = ["*"]

port = int(os.getenv("NODE_93_PORT", "8093"))

NODE_ID = "93"
NODE_NAME = "VideoProcessor"

# Environment variables
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
NODE_90_VISION_URL = os.getenv("NODE_90_VISION_URL", "http://localhost:8090")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Video Processor Node", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class AnalyzeFrameRequest(BaseModel):
    image_base64: str
    prompt: str = "Describe what is happening in this video frame in detail."
    model: str = "gpt-4o"
    detail: str = "auto"  # low | high | auto


class ExtractFramesRequest(BaseModel):
    video_url: str
    max_frames: int = 8
    strategy: str = "uniform"  # uniform | scene_change | first_last


class SummarizeVideoRequest(BaseModel):
    frames: List[str]  # list of base64-encoded frame images
    title: Optional[str] = None
    context: Optional[str] = None
    model: str = "gpt-4o"


class McpCallRequest(BaseModel):
    tool: str
    params: Dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Supported formats
# ---------------------------------------------------------------------------

SUPPORTED_VIDEO_FORMATS = [
    "mp4", "avi", "mov", "mkv", "webm",
    "flv", "wmv", "m4v", "3gp", "ts",
    "mts", "m2ts", "ogv", "rm", "rmvb",
]

SUPPORTED_IMAGE_FORMATS = ["jpg", "jpeg", "png", "webp", "gif", "bmp"]


# ---------------------------------------------------------------------------
# Business logic helpers
# ---------------------------------------------------------------------------

async def _openai_vision_call(
    image_base64: str,
    prompt: str,
    model: str = "gpt-4o",
    detail: str = "auto",
) -> str:
    """Call OpenAI vision API with a base64 image and return the text response."""
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is not configured")

    # Detect MIME type from base64 header if present, default to jpeg
    mime_type = "image/jpeg"
    raw_b64 = image_base64
    if image_base64.startswith("data:"):
        header, raw_b64 = image_base64.split(",", 1)
        mime_type = header.split(";")[0].replace("data:", "")

    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{raw_b64}",
                            "detail": detail,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        "max_tokens": 1024,
    }

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    url = f"{OPENAI_BASE_URL.rstrip('/')}/chat/completions"

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()

    data = response.json()
    return data["choices"][0]["message"]["content"]


async def _analyze_single_frame(
    image_base64: str,
    prompt: str,
    model: str,
    detail: str,
) -> Dict:
    """Analyze a single frame and return a structured result."""
    description = await _openai_vision_call(image_base64, prompt, model, detail)
    return {
        "description": description,
        "model": model,
        "prompt": prompt,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def _extract_frames_metadata(
    video_url: str,
    max_frames: int,
    strategy: str,
) -> Dict:
    """
    Extract frame metadata from a video URL.

    This implementation uses httpx to fetch HTTP headers and compute
    representative timestamps without requiring a local ffmpeg binary.
    For production deployments with ffmpeg available, this can be extended
    to perform real frame extraction.
    """
    metadata: Dict[str, Any] = {
        "video_url": video_url,
        "strategy": strategy,
        "max_frames": max_frames,
        "frames": [],
    }

    # Fetch HTTP headers to gather duration/size hints
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            head_resp = await client.head(video_url, follow_redirects=True)
        content_length = int(head_resp.headers.get("content-length", 0))
        content_type = head_resp.headers.get("content-type", "")
        metadata["content_type"] = content_type
        metadata["content_length_bytes"] = content_length
    except Exception as exc:
        logger.warning("Could not fetch video HEAD for %s: %s", video_url, exc)
        metadata["content_type"] = "unknown"
        metadata["content_length_bytes"] = 0

    # Generate representative timestamps based on strategy
    # Without ffmpeg we approximate using equal intervals over an assumed duration
    assumed_duration_s = 60  # default assumption when duration is unknown
    if strategy == "first_last":
        timestamps = [0.0, float(assumed_duration_s)]
    elif strategy == "scene_change":
        # Approximate scene boundaries at regular intervals
        step = assumed_duration_s / max(max_frames, 1)
        timestamps = [round(i * step, 2) for i in range(max_frames)]
    else:  # uniform
        if max_frames == 1:
            timestamps = [assumed_duration_s / 2]
        else:
            step = assumed_duration_s / (max_frames - 1)
            timestamps = [round(i * step, 2) for i in range(max_frames)]

    metadata["assumed_duration_s"] = assumed_duration_s
    metadata["frames"] = [
        {
            "index": idx,
            "timestamp_s": ts,
            "extraction_note": (
                "Timestamp computed analytically; "
                "real frame extraction requires ffmpeg."
            ),
        }
        for idx, ts in enumerate(timestamps)
    ]
    metadata["frame_count"] = len(metadata["frames"])
    return metadata


async def _summarize_video_from_frames(
    frames: List[str],
    title: Optional[str],
    context: Optional[str],
    model: str,
) -> Dict:
    """Generate a video summary by asking the LLM to analyze multiple frames."""
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is not configured")

    # Build a multi-image message
    content: List[Dict] = []

    system_context = "You are an expert video analyst."
    if context:
        system_context += f" Context: {context}"

    user_text = (
        f"The following {len(frames)} frames were extracted from a video"
        + (f' titled "{title}"' if title else "")
        + ". Please provide:\n"
        "1. A concise summary of the video content.\n"
        "2. Key events or scenes identified.\n"
        "3. An estimated overall topic or category.\n"
        "4. Any notable objects, people, or text visible."
    )

    for idx, frame_b64 in enumerate(frames):
        mime_type = "image/jpeg"
        raw_b64 = frame_b64
        if frame_b64.startswith("data:"):
            header, raw_b64 = frame_b64.split(",", 1)
            mime_type = header.split(";")[0].replace("data:", "")

        content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{mime_type};base64,{raw_b64}",
                    "detail": "low",
                },
            }
        )
        content.append({"type": "text", "text": f"[Frame {idx + 1}]"})

    content.append({"type": "text", "text": user_text})

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_context},
            {"role": "user", "content": content},
        ],
        "max_tokens": 2048,
    }

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    url = f"{OPENAI_BASE_URL.rstrip('/')}/chat/completions"

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()

    data = response.json()
    summary_text = data["choices"][0]["message"]["content"]

    return {
        "summary": summary_text,
        "frames_analyzed": len(frames),
        "model": model,
        "title": title,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# MCP tool dispatch
# ---------------------------------------------------------------------------

_MCP_TOOL_MAP = {
    "analyze_frame": "analyze_frame",
    "extract_frames": "extract_frames",
    "summarize_video": "summarize_video",
    "supported_formats": "supported_formats",
}


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "node": "Node_93_VideoProcessor",
        "version": "1.0.0",
        "openai_configured": bool(OPENAI_API_KEY),
        "openai_base_url": OPENAI_BASE_URL,
        "node_90_vision_url": NODE_90_VISION_URL,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/status")
async def node_status():
    return {
        "node_id": NODE_ID,
        "node_name": NODE_NAME,
        "port": port,
        "status": "running",
        "openai_configured": bool(OPENAI_API_KEY),
        "openai_base_url": OPENAI_BASE_URL,
        "node_90_vision_url": NODE_90_VISION_URL,
        "supported_video_formats": SUPPORTED_VIDEO_FORMATS,
        "supported_image_formats": SUPPORTED_IMAGE_FORMATS,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/analyze_frame")
async def analyze_frame(request: AnalyzeFrameRequest):
    """Analyze a single video frame (base64 image) using the OpenAI vision API."""
    try:
        result = await _analyze_single_frame(
            request.image_base64,
            request.prompt,
            request.model,
            request.detail,
        )
        return {"success": True, **result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except httpx.HTTPStatusError as exc:
        logger.error("OpenAI API error: %s", exc)
        raise HTTPException(status_code=502, detail=f"OpenAI API error: {exc.response.status_code}")
    except Exception as exc:
        logger.error("analyze_frame error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/extract_frames")
async def extract_frames(request: ExtractFramesRequest):
    """Extract keyframe metadata from a video URL."""
    try:
        result = await _extract_frames_metadata(
            request.video_url,
            request.max_frames,
            request.strategy,
        )
        return {"success": True, **result}
    except Exception as exc:
        logger.error("extract_frames error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/summarize_video")
async def summarize_video(request: SummarizeVideoRequest):
    """Summarize video content from a list of base64-encoded frames."""
    if not request.frames:
        raise HTTPException(status_code=400, detail="At least one frame is required")
    try:
        result = await _summarize_video_from_frames(
            request.frames,
            request.title,
            request.context,
            request.model,
        )
        return {"success": True, **result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except httpx.HTTPStatusError as exc:
        logger.error("OpenAI API error: %s", exc)
        raise HTTPException(status_code=502, detail=f"OpenAI API error: {exc.response.status_code}")
    except Exception as exc:
        logger.error("summarize_video error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/supported_formats")
async def supported_formats():
    """List all supported video and image formats."""
    return {
        "success": True,
        "video_formats": SUPPORTED_VIDEO_FORMATS,
        "image_formats": SUPPORTED_IMAGE_FORMATS,
    }


@app.post("/mcp/call")
async def mcp_call(request: McpCallRequest):
    """MCP tool dispatch endpoint."""
    tool = request.tool
    params = request.params

    try:
        if tool == "analyze_frame":
            req = AnalyzeFrameRequest(**params)
            result = await _analyze_single_frame(
                req.image_base64, req.prompt, req.model, req.detail
            )
            return {"success": True, "tool": tool, "data": result}

        elif tool == "extract_frames":
            req = ExtractFramesRequest(**params)
            result = await _extract_frames_metadata(
                req.video_url, req.max_frames, req.strategy
            )
            return {"success": True, "tool": tool, "data": result}

        elif tool == "summarize_video":
            req = SummarizeVideoRequest(**params)
            if not req.frames:
                return {"success": False, "error": "frames list is empty"}
            result = await _summarize_video_from_frames(
                req.frames, req.title, req.context, req.model
            )
            return {"success": True, "tool": tool, "data": result}

        elif tool == "supported_formats":
            return {
                "success": True,
                "tool": tool,
                "data": {
                    "video_formats": SUPPORTED_VIDEO_FORMATS,
                    "image_formats": SUPPORTED_IMAGE_FORMATS,
                },
            }

        else:
            available = list(_MCP_TOOL_MAP.keys())
            return {
                "success": False,
                "error": f"Unknown tool: {tool}",
                "available_tools": available,
            }

    except ValueError as exc:
        return {"success": False, "tool": tool, "error": str(exc)}
    except Exception as exc:
        logger.error("mcp/call error for tool '%s': %s", tool, exc)
        return {"success": False, "tool": tool, "error": str(exc)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=port)
