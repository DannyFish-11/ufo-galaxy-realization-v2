# Node 87 - Image Analysis

Computer vision and image analysis service using OpenAI GPT-4o or Azure Computer Vision for captioning, object detection, OCR, and image comparison.

## Port
Default port: **8087**

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `VISION_PROVIDER` | `openai` | Vision API provider: openai or azure |
| `OPENAI_API_KEY` | `` | OpenAI API key |
| `AZURE_VISION_KEY` | `` | Azure Computer Vision API key |
| `AZURE_VISION_ENDPOINT` | `` | Azure Computer Vision endpoint URL |
| `NODE_ID` | `87` | Node identifier |
| `LOG_LEVEL` | `INFO` | Logging level |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/status` | Service status |
| `POST` | `/analyze` | Analyze image (caption, objects, tags, color, faces) |
| `POST` | `/describe` | Generate natural language description |
| `POST` | `/ocr` | Extract text from image |
| `POST` | `/classify` | Classify image into categories |
| `POST` | `/detect_objects` | Detect and locate objects |
| `POST` | `/compare` | Compare two images for similarity |
| `POST` | `/mcp/call` | MCP tool dispatch |

## Dependencies

See `requirements.txt` for full dependency list.

## Running

```bash
pip install -r requirements.txt
python main.py
```

Or with Docker:

```bash
docker build -t galaxy-node-87-imageanalysis .
docker run -p 8087:8087 galaxy-node-87-imageanalysis
```
