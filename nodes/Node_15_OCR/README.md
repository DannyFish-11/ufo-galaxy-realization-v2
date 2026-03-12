# Node 15 - OCR

FastAPI HTTP server providing dual-engine OCR (Optical Character Recognition) for the Galaxy system.

## Port
`8015`

## Engines

| Engine | Dependency | Notes |
|---|---|---|
| **DeepSeek VL2** | `DEEPSEEK_API_KEY` + `httpx` | Primary; cloud-based, high accuracy |
| **Tesseract** | `pytesseract` binary | Fallback; local, no API key needed |

`auto` mode selects DeepSeek if configured, otherwise Tesseract, otherwise returns 503.

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `DEEPSEEK_API_KEY` | No | DeepSeek API key (enables primary engine) |
| `DEEPSEEK_API_URL` | No | API base URL (default: `https://api.deepseek.com/v1`) |
| `DEEPSEEK_MODEL` | No | Model name (default: `deepseek-vl2`) |
| `TESSERACT_CMD` | No | Path to `tesseract` binary (uses system default if unset) |

## Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check + engine availability |
| GET | `/status` | Config, available engines, request stats |
| POST | `/ocr` | OCR from base64 image |
| POST | `/ocr/url` | OCR from image URL |
| POST | `/ocr/detect-language` | Detect text language in image |

## Request Bodies

### POST /ocr
```json
{
  "image_base64": "<base64-encoded image>",
  "engine": "auto",
  "prompt": "Extract all text from this image."
}
```
`engine`: `"auto"` | `"deepseek"` | `"tesseract"`

### POST /ocr/url
```json
{
  "url": "https://example.com/image.png",
  "engine": "auto",
  "prompt": "Extract all text from this image."
}
```

### POST /ocr/detect-language
```json
{"image_base64": "<base64-encoded image>"}
```

## Response Format

```json
{"success": true, "text": "extracted text", "engine_used": "deepseek"}
```
Tesseract responses also include `"confidence"` (0–100).

## Running

```bash
pip install -r requirements.txt
DEEPSEEK_API_KEY=sk-xxx python main.py
```
