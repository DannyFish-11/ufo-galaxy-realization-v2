# Node 77 - Task Scheduler

Cron-like task scheduler with asyncio-based execution supporting echo, HTTP, and python literal job types.

## Port
Default port: **8077**

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SCHEDULER_TIMEZONE` | `UTC` | Scheduler timezone |
| `MAX_CONCURRENT_JOBS` | `10` | Maximum concurrent job executions |
| `NODE_ID` | `77` | Node identifier |
| `LOG_LEVEL` | `INFO` | Logging level |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/status` | Service status |
| `GET` | `/jobs` | List all scheduled jobs |
| `POST` | `/job/create` | Create a new scheduled job |
| `GET` | `/job/{id}` | Get job details |
| `DELETE` | `/job/{id}` | Delete a job |
| `PUT` | `/job/{id}` | Update a job |
| `POST` | `/job/{id}/run` | Run job immediately |
| `POST` | `/job/{id}/pause` | Pause a job |
| `POST` | `/job/{id}/resume` | Resume a paused job |
| `GET` | `/history` | Get execution history |
| `POST` | `/mcp/call` | MCP tool dispatch |

## Dependencies

See `requirements.txt` for full dependency list.

## Running

```bash
pip install -r requirements.txt
python main.py
```

Or with Docker:

```bash
docker build -t galaxy-node-77-taskscheduler .
docker run -p 8077:8077 galaxy-node-77-taskscheduler
```
