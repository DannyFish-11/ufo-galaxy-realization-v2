# Node 119 - BenchmarkEval

AI model benchmarking and evaluation with pure-Python metrics.

## Features

- **Metrics** — BLEU, ROUGE-1, Exact Match, Token F1 (no external NLP deps)
- **LLM Eval** — OpenAI-powered criteria scoring (accuracy, fluency, relevance, …)
- **Batch Eval** — send prompts to any model endpoint and evaluate responses
- **Result Storage** — persisted JSON results with list/retrieve endpoints

## Port

`8119` (override with `NODE_119_PORT`)

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | *(required for llm_eval)* | OpenAI API key |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | API base URL |
| `OPENAI_MODEL` | `gpt-4o-mini` | Model for LLM evaluation |
| `EVAL_STORAGE_PATH` | `./eval_results` | Directory to store results |

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/status` | Detailed status |
| POST | `/evaluate` | Compute metrics for predictions vs references |
| POST | `/llm_eval` | OpenAI-powered scoring on criteria |
| POST | `/batch_eval` | Batch prompt → model → evaluate |
| GET | `/eval_results` | List stored evaluation results |
| GET | `/eval_results/{eval_id}` | Get a specific evaluation result |
| POST | `/mcp/call` | MCP tool dispatch |

## Supported Metrics

| Metric | Notes |
|---|---|
| `exact_match` | Case-insensitive string equality ratio |
| `f1` | Token-level F1 (whitespace tokenization) |
| `bleu` | 4-gram BLEU with brevity penalty |
| `rouge` | Unigram ROUGE-1 precision/recall/F1 |

## Quick Start

```bash
pip install -r requirements.txt
python main.py
# with OpenAI for llm_eval:
OPENAI_API_KEY=sk-... python main.py
```

## Docker

```bash
docker build -t node-119 .
docker run -e OPENAI_API_KEY=sk-... -p 8119:8119 node-119
```
