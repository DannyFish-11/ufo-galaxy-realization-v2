# Node 55 - MultiModal AI Processing

A multimodal AI processing node that handles text, images, and combined inputs using HuggingFace Transformers.

## Port
8055

## Endpoints

- `GET /health` - Health check
- `GET /status` - Service status
- `GET /models` - List available models
- `POST /process` - Process multimodal input (text + optional image)
- `POST /embed` - Create embeddings for text

## Dependencies

- `transformers>=4.36.0` - HuggingFace Transformers
- `Pillow>=10.0.0` - Image processing
- `torch>=2.1.0` - PyTorch backend

## Degraded Mode

If transformers/PIL/torch are not installed, the service runs in degraded mode returning clear error messages.
