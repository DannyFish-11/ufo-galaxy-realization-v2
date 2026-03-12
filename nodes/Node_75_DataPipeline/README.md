# Node 75 - Data Pipeline

ETL data processing pipeline with async execution, supporting transform, filter, aggregate, and other operations.

## Port
Default port: **8075**

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PIPELINE_MAX_WORKERS` | `4` | Maximum concurrent pipeline workers |
| `PIPELINE_BATCH_SIZE` | `100` | Batch size for data processing |
| `NODE_ID` | `75` | Node identifier |
| `LOG_LEVEL` | `INFO` | Logging level |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/status` | Service status |
| `POST` | `/pipeline/create` | Create a new pipeline definition |
| `GET` | `/pipeline/list` | List all pipelines |
| `POST` | `/pipeline/run` | Execute a pipeline |
| `GET` | `/pipeline/status/{id}` | Get pipeline execution status |
| `DELETE` | `/pipeline/delete/{id}` | Delete a pipeline |
| `POST` | `/transform` | Apply a transformation to data |
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
docker build -t galaxy-node-75-datapipeline .
docker run -p 8075:8075 galaxy-node-75-datapipeline
```
