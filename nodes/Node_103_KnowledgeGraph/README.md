# Node 103 - Knowledge Graph / 知识图谱

## Overview / 概述

Knowledge graph construction, querying, and reasoning. Supports entity extraction, relation mapping, and graph traversal.

## Port / 端口

`8103`

## Environment Variables / 环境变量

| Variable | Default | Description |
|----------|---------|-------------|
| `NODE_103_PORT` | `8103` | Service port |
| `OPENAI_API_KEY` | `` | OpenAI API key for extraction |

## API Endpoints / 接口

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/status` | Node status |
| POST | `/extract` | Extract entities and relations |
| POST | `/query` | Query the knowledge graph |
| POST | `/add_entity` | Add entity to graph |
| POST | `/mcp/call` | MCP tool dispatcher |

## Dependencies / 依赖

See `requirements.txt`

## Docker

```bash
docker build -t galaxy-node-103 .
docker run -p 8103:8103 galaxy-node-103
```
