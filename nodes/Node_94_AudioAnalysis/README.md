# Node 94 - AudioAnalysis

Real-time audio analysis node for the Galaxy system. Provides speech-to-text
transcription via the OpenAI Whisper API, audio feature extraction, language
detection, and speaker segmentation.

## Port

**8094** (override with `NODE_94_PORT` env var)

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | *(required)* | OpenAI API key for Whisper |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible base URL |
| `NODE_86_SPEECH_URL` | `http://localhost:8086` | Upstream speech node URL |
| `NODE_94_PORT` | `8094` | Listening port |

## Endpoints

### `GET /health`
Liveness check.
```json
{"status": "healthy", "node": "Node_94_AudioAnalysis", "version": "1.0.0",
 "openai_configured": true, "timestamp": "..."}
```

### `GET /status`
Full node status including configuration.

### `GET /supported_formats`
Returns the list of accepted audio formats (`mp3`, `mp4`, `mpeg`, `mpga`,
`m4a`, `wav`, `webm`) and metadata.

### `POST /transcribe`
Transcribe audio using OpenAI Whisper (`whisper-1`).

**Request body:**
```json
{
  "audio_base64": "<base64-encoded audio>",
  "filename": "recording.wav",
  "language": "en",        // optional ISO-639-1; omit for auto-detect
  "response_format": "verbose_json",
  "temperature": 0.0,
  "prompt": null           // optional context hint
}
```

**Response:**
```json
{
  "success": true,
  "text": "Hello world ...",
  "language": "en",
  "duration_seconds": 4.2,
  "segments": [...],
  "processing_time_seconds": 1.23,
  "model": "whisper-1",
  "filename": "recording.wav"
}
```

### `POST /analyze`
Extract audio characteristics: duration, detected language, confidence score
(derived from Whisper segment log-probabilities), and a heuristic speaker
segmentation.

**Request body:** same shape as `/transcribe` (without `response_format` /
`temperature` / `prompt`).

### `POST /detect_language`
Auto-detect the spoken language and return a per-language segment distribution.

```json
{
  "audio_base64": "<base64-encoded audio>",
  "filename": "clip.mp3"
}
```

### `POST /mcp/call`
Generic MCP tool-dispatch endpoint.

```json
{"tool": "transcribe", "params": {"audio_base64": "...", "filename": "x.wav"}}
```

Available tools: `transcribe`, `analyze`, `detect_language`,
`supported_formats`, `health`, `status`.

## Running Locally

```bash
pip install -r requirements.txt
OPENAI_API_KEY=sk-... python main.py
```

## Docker

```bash
docker build -t node-94-audio-analysis .
docker run -e OPENAI_API_KEY=sk-... -p 8094:8094 node-94-audio-analysis
```

## Error Handling

When `OPENAI_API_KEY` is not set, all transcription endpoints return HTTP 503:

```json
{
  "error": "OPENAI_API_KEY not configured",
  "detail": "Set the OPENAI_API_KEY environment variable to enable Whisper transcription features."
}
```
