# Node 95 - WebRTC Receiver / WebRTC 接收器

## Overview / 概述

Receives real-time video/audio streams from devices via WebRTC signaling. Supports multi-device management, frame capture, and MJPEG streaming.

## Port / 端口

`8095`

## Environment Variables / 环境变量

| Variable | Default | Description |
|----------|---------|-------------|
| `NODE_95_PORT` | `8095` | Service port |
| `LOG_LEVEL` | `INFO` | Log level |

## API Endpoints / 接口

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/status` | Node status |
| WebSocket | `/signaling/{device_id}` | WebRTC signaling channel |
| GET | `/frame/{device_id}` | Get latest JPEG frame |
| GET | `/stream/{device_id}` | MJPEG stream |
| GET | `/devices` | List connected devices |
| POST | `/mcp/call` | MCP tool dispatcher |

## Dependencies / 依赖

See `requirements.txt`

## Docker

```bash
docker build -t galaxy-node-95 .
docker run -p 8095:8095 galaxy-node-95
```
