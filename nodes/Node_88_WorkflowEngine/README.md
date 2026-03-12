# Node 88 - Workflow Engine

Async workflow automation engine with support for multi-step workflows including transform, condition, HTTP, delay, log, and set step types.

## Port
Default port: **8088**

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `WORKFLOW_MAX_STEPS` | `100` | Maximum steps per workflow |
| `WORKFLOW_TIMEOUT` | `300` | Workflow execution timeout in seconds |
| `NODE_ID` | `88` | Node identifier |
| `LOG_LEVEL` | `INFO` | Logging level |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/status` | Service status |
| `GET` | `/workflows` | List workflow definitions |
| `POST` | `/workflow/create` | Create workflow definition |
| `GET` | `/workflow/{id}` | Get workflow definition |
| `DELETE` | `/workflow/{id}` | Delete workflow |
| `POST` | `/workflow/{id}/execute` | Execute workflow |
| `GET` | `/execution/{id}` | Get execution status |
| `GET` | `/executions` | List recent executions |
| `POST` | `/execution/{id}/cancel` | Cancel execution |
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
docker build -t galaxy-node-88-workflowengine .
docker run -p 8088:8088 galaxy-node-88-workflowengine
```
