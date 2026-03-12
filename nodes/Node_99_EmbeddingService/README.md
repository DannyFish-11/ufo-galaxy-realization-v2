# Node 99 — EmbeddingService

> **Port:** 8099  
> **Purpose:** Generate text/document embedding vectors using OpenAI's embedding API, with optional Redis caching.

## Overview

Node_99 provides a centralised embedding service for the Galaxy cluster. All other nodes that need semantic similarity, ranking, or RAG retrieval should call this node rather than calling OpenAI directly, benefiting from shared caching.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | *(required)* | OpenAI API key |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible base URL |
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-small` | Embedding model to use |
| `REDIS_URL` | `redis://localhost:6379` | Redis URL for caching (optional) |
| `NODE_99_PORT` | `8099` | Override the listening port |

## API Endpoints

### `GET /health`
Returns service health, configured model, and whether OpenAI is configured.

### `GET /status`
Detailed status including uptime, model, Redis connectivity, and local cache size.

### `POST /embed`
Embed a list of texts and return their vectors.

**Request:**
```json
{
  "texts": ["Hello world", "Galaxy AI"],
  "model": "text-embedding-3-small"
}
```

**Response:**
```json
{
  "success": true,
  "model": "text-embedding-3-small",
  "count": 2,
  "embeddings": [[...], [...]]
}
```

### `POST /embed_batch`
Same as `/embed` but with explicit chunking — ideal for large corpora (1000+ texts).

### `POST /similarity`
Compute cosine similarity between two texts (returns 0.0–1.0).

**Request:**
```json
{"text1": "cat", "text2": "kitten"}
```

### `POST /rank`
Rank a list of candidate strings by semantic similarity to a query.

**Request:**
```json
{
  "query": "machine learning frameworks",
  "candidates": ["PyTorch", "Django", "TensorFlow", "Flask"]
}
```

### `POST /mcp/call`
MCP-compatible dispatcher. Set `"tool"` to one of: `embed`, `embed_batch`, `similarity`, `rank`, `health`.

## Caching Strategy

1. **Redis** (when available) — 24-hour TTL per vector, keyed by `SHA256(model:text)`.
2. **In-process dict** — fallback when Redis is unreachable; persists for the lifetime of the process.

## Docker

```bash
docker build -t node_99_embeddingservice .
docker run -e OPENAI_API_KEY=sk-... -p 8099:8099 node_99_embeddingservice
```

## Related Nodes

- **Node_98_MultimodalFusion** — produces unified descriptions to embed
- **Node_103_KnowledgeGraph** — uses embeddings for entity linking
- **Node_105_UnifiedKnowledgeBase** — uses embeddings for RAG retrieval
