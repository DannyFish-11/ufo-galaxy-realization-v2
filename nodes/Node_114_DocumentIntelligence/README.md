# Node 114 - DocumentIntelligence

Document understanding and intelligence powered by OpenAI.

## Features

- **Parse** — clean text from plain text, Markdown, or HTML content
- **Summarize** — brief, detailed, or bullet-point summaries
- **Extract Info** — structured extraction of dates, entities, keywords, tables
- **Q&A** — answer questions grounded in a provided document
- **Classify** — classify documents into user-defined categories

## Port

`8114` (override with `NODE_114_PORT`)

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | *(required for AI)* | OpenAI API key |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | API base URL |
| `OPENAI_MODEL` | `gpt-4o-mini` | Model to use |
| `MAX_DOCUMENT_SIZE_MB` | `10` | Max upload size in MB |

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/status` | Detailed status |
| POST | `/parse` | Parse and clean document text |
| POST | `/summarize` | Summarize text |
| POST | `/extract_info` | Extract structured info |
| POST | `/qa` | Answer question from document |
| POST | `/classify` | Classify document |
| POST | `/mcp/call` | MCP tool dispatch |

## Quick Start

```bash
pip install -r requirements.txt
OPENAI_API_KEY=sk-... python main.py
```

## Docker

```bash
docker build -t node-114 .
docker run -e OPENAI_API_KEY=sk-... -p 8114:8114 node-114
```
