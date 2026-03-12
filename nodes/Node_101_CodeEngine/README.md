# Node 101 - Code Engine / 代码引擎

## Overview / 概述

AI-powered code generation, review, refactoring, and execution engine. Supports multiple programming languages.

## Port / 端口

`8101`

## Environment Variables / 环境变量

| Variable | Default | Description |
|----------|---------|-------------|
| `NODE_101_PORT` | `8101` | Service port |
| `OPENAI_API_KEY` | `` | OpenAI API key |

## API Endpoints / 接口

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/status` | Node status |
| POST | `/generate` | Generate code from description |
| POST | `/review` | Review and improve code |
| POST | `/execute` | Execute code in sandbox |
| POST | `/mcp/call` | MCP tool dispatcher |

## Dependencies / 依赖

See `requirements.txt`

## Docker

```bash
docker build -t galaxy-node-101 .
docker run -p 8101:8101 galaxy-node-101
```
