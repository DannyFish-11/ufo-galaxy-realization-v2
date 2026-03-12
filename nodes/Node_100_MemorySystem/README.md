# Node 100 - Memory System V2 / 记忆系统 V2

## Overview / 概述

Persistent AI memory management with short-term, long-term, and episodic memory support. Integrates with Qdrant for vector search.

## Port / 端口

`8100`

## Environment Variables / 环境变量

| Variable | Default | Description |
|----------|---------|-------------|
| `NODE_100_PORT` | `8100` | Service port |
| `QDRANT_URL` | `http://localhost:6333` | Qdrant vector database URL |
| `OPENAI_API_KEY` | `` | OpenAI API key for embeddings |

## API Endpoints / 接口

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/status` | Node status |
| POST | `/remember` | Store a memory |
| POST | `/recall` | Retrieve relevant memories |
| POST | `/mcp/call` | MCP tool dispatcher |

## Dependencies / 依赖

See `requirements.txt`

## Docker

```bash
docker build -t galaxy-node-100 .
docker run -p 8100:8100 galaxy-node-100
```
