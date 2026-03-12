# Node 102 - Debug Optimize / 调试优化

## Overview / 概述

AI-assisted debugging, performance optimization, and code analysis. Identifies bugs, suggests fixes, and optimizes code performance.

## Port / 端口

`8102`

## Environment Variables / 环境变量

| Variable | Default | Description |
|----------|---------|-------------|
| `NODE_102_PORT` | `8102` | Service port |
| `OPENAI_API_KEY` | `` | OpenAI API key |

## API Endpoints / 接口

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/status` | Node status |
| POST | `/debug` | Debug code and find issues |
| POST | `/optimize` | Optimize code performance |
| POST | `/analyze` | Analyze code complexity |
| POST | `/mcp/call` | MCP tool dispatcher |

## Dependencies / 依赖

See `requirements.txt`

## Docker

```bash
docker build -t galaxy-node-102 .
docker run -p 8102:8102 galaxy-node-102
```
