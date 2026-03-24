# Node 70 - Autonomous Learning

Autonomous continual-learning service that accumulates experiences, detects patterns, and updates knowledge over time without explicit retraining triggers.

## Port
Default port: **8070**

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `NODE_PORT` | `8070` | Listening port |
| `NODE_ID` | `70` | Node identifier |
| `LOG_LEVEL` | `INFO` | Logging level |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/status` | Service status |
| `POST` | `/experiences` | Record a new learning experience |
| `GET` | `/experiences` | List recorded experiences |
| `POST` | `/sessions` | Start a learning session |
| `GET` | `/sessions` | List active and past sessions |
| `GET` | `/knowledge` | Query accumulated knowledge base |
| `GET` | `/patterns` | Retrieve detected patterns |
| `POST` | `/predict` | Generate a prediction from current knowledge |
| `GET` | `/recommendations` | Get actionable recommendations |

## Dependencies

See `requirements.txt` for full dependency list.

Depends on:
- `Node_01_OneAPI` — model inference backend

## Running

```bash
pip install -r requirements.txt
python main.py
```

Or with Docker:

```bash
docker build -t galaxy-node-70-autonomouslearning .
docker run -p 8070:8070 galaxy-node-70-autonomouslearning
```

## Governance

`startup_policy: optional` — started if available; startup failure does not abort the system.
Promote to `active` after passing integration tests and health-check review (see `docs/NODE_ACTIVE_MANIFEST.md`).
