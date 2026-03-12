# Node 86 - Speech Processor

Speech processing service supporting speech-to-text transcription, text-to-speech synthesis, and language detection via OpenAI, Azure, or Google speech APIs.

## Port
Default port: **8086**

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SPEECH_PROVIDER` | `openai` | Speech API provider: openai, azure, or google |
| `OPENAI_API_KEY` | `` | OpenAI API key |
| `AZURE_SPEECH_KEY` | `` | Azure Speech Services key |
| `AZURE_SPEECH_REGION` | `` | Azure Speech Services region |
| `GOOGLE_APPLICATION_CREDENTIALS` | `` | Path to Google Cloud credentials JSON |
| `NODE_ID` | `86` | Node identifier |
| `LOG_LEVEL` | `INFO` | Logging level |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/status` | Service status with provider info |
| `POST` | `/transcribe` | Transcribe audio to text (base64 or URL) |
| `POST` | `/synthesize` | Convert text to speech |
| `POST` | `/translate` | Translate speech to another language |
| `GET` | `/voices` | List available TTS voices |
| `GET` | `/models` | List available STT models |
| `POST` | `/detect_language` | Detect spoken language |
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
docker build -t galaxy-node-86-speechprocessor .
docker run -p 8086:8086 galaxy-node-86-speechprocessor
```
