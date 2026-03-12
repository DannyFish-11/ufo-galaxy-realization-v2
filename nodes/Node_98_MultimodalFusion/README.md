# Node 98 — MultimodalFusion

> **Port:** 8098  
> **Purpose:** Fuse text, images, and audio transcripts into unified representations for downstream AI tasks.

## Overview

Node_98 acts as a multimodal orchestrator. It ingests content from multiple modalities and uses OpenAI to produce coherent, fused outputs. It can also delegate image understanding to **Node_90 (Vision)** and audio transcription to **Node_94 (Audio)**.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | *(required)* | OpenAI API key |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible base URL |
| `OPENAI_MODEL` | `gpt-4o-mini` | Chat model to use |
| `NODE_90_VISION_URL` | `http://localhost:8090` | URL of Node_90 Vision |
| `NODE_94_AUDIO_URL` | `http://localhost:8094` | URL of Node_94 Audio |
| `NODE_98_PORT` | `8098` | Override the listening port |

## API Endpoints

### `GET /health`
Returns service health and whether OpenAI is configured.

### `GET /status`
Detailed status including uptime, model, and connected node URLs.

### `POST /fuse`
Fuse multiple modalities into a single result.

**Request:**
```json
{
  "texts": ["..."],
  "images": ["<base64>"],
  "audio_transcripts": ["..."],
  "task": "summarize",
  "question": "optional for qa task"
}
```

**Supported tasks:** `summarize`, `qa`, `classify`

### `POST /embed_multimodal`
Produce a rich unified description from mixed inputs, suitable for downstream embedding via Node_99.

### `POST /cross_modal_search`
Rank a list of mixed-media items against a text query.

**Request:**
```json
{
  "query": "find the invoice",
  "items": [
    {"type": "text", "content": "..."},
    {"type": "image", "content": "<base64>"},
    {"type": "audio", "content": "transcript text"}
  ],
  "top_k": 5
}
```

### `POST /mcp/call`
MCP-compatible dispatcher. Set `"tool"` to one of: `fuse`, `embed_multimodal`, `cross_modal_search`, `health`.

## Docker

```bash
docker build -t node_98_multimodalfusion .
docker run -e OPENAI_API_KEY=sk-... -p 8098:8098 node_98_multimodalfusion
```

## Related Nodes

- **Node_90_VisionAnalysis** — image understanding
- **Node_94_AudioProcessor** — audio transcription
- **Node_99_EmbeddingService** — vector embedding of fused descriptions
