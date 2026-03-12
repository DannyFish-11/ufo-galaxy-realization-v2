# Node 93 - VideoProcessor

**Galaxy L4 System | Port 8093**

A video processing and analysis node that leverages multimodal LLMs for frame-level understanding, keyframe metadata extraction, and video summarization.

---

## 功能 / Features

| Feature | Description |
|---------|-------------|
| Frame Analysis | Analyze individual video frames via OpenAI vision API |
| Frame Extraction | Extract keyframe timestamps/metadata from a video URL |
| Video Summarization | Generate a narrative summary from multiple frames |
| Thumbnail Support | Accept base64-encoded images (JPEG/PNG/WebP) |
| Format Query | List all supported video and image formats |
| MCP Tool Dispatch | Unified `/mcp/call` endpoint for Galaxy integration |

---

## 环境变量 / Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `NODE_93_PORT` | `8093` | Listening port |
| `OPENAI_API_KEY` | *(required for vision)* | OpenAI API key |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible API base URL |
| `NODE_90_VISION_URL` | `http://localhost:8090` | Fallback vision node URL |
| `CORS_ALLOWED_ORIGINS` | Dashboard/gateway ports | Comma-separated allowed CORS origins |

---

## API 端点 / API Endpoints

### System
| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/status` | Node configuration and status |
| GET | `/supported_formats` | List supported video/image formats |

### Video Processing
| Method | Path | Description |
|--------|------|-------------|
| POST | `/analyze_frame` | Analyze a single video frame (base64) |
| POST | `/extract_frames` | Extract keyframe metadata from a video URL |
| POST | `/summarize_video` | Summarize video content from multiple frames |
| POST | `/mcp/call` | MCP tool dispatch |

---

## 示例请求 / Example Requests

### Analyze a frame
```bash
curl -X POST http://localhost:8093/analyze_frame \
  -H "Content-Type: application/json" \
  -d '{
    "image_base64": "<base64-encoded-image>",
    "prompt": "What is happening in this frame?",
    "model": "gpt-4o"
  }'
```

### Extract frames metadata
```bash
curl -X POST http://localhost:8093/extract_frames \
  -H "Content-Type: application/json" \
  -d '{
    "video_url": "https://example.com/video.mp4",
    "max_frames": 8,
    "strategy": "uniform"
  }'
```

### Summarize video
```bash
curl -X POST http://localhost:8093/summarize_video \
  -H "Content-Type: application/json" \
  -d '{
    "frames": ["<base64-frame-1>", "<base64-frame-2>"],
    "title": "Sample Video",
    "model": "gpt-4o"
  }'
```

### MCP call
```bash
curl -X POST http://localhost:8093/mcp/call \
  -H "Content-Type: application/json" \
  -d '{"tool": "supported_formats", "params": {}}'
```

---

## 快速启动 / Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Set API key
export OPENAI_API_KEY=sk-...

# Start the node
python main.py
```

Or with Docker:
```bash
docker build -t node-93-videoprocessor .
docker run -p 8093:8093 -e OPENAI_API_KEY=sk-... node-93-videoprocessor
```
