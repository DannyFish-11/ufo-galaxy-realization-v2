# Node 78 - Data Validator

Data validation service supporting JSON Schema (Draft7) validation and built-in business rules.

## Port
Default port: **8078**

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `VALIDATOR_STRICT_MODE` | `false` | Enable strict validation mode |
| `NODE_ID` | `78` | Node identifier |
| `LOG_LEVEL` | `INFO` | Logging level |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/status` | Service status |
| `POST` | `/validate` | Validate data against a schema |
| `GET` | `/schema` | List all schemas |
| `POST` | `/schema` | Register a new schema |
| `GET` | `/schema/{name}` | Get schema by name |
| `DELETE` | `/schema/{name}` | Delete schema |
| `GET` | `/rules` | List built-in validation rules |
| `POST` | `/batch/validate` | Validate multiple items |
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
docker build -t galaxy-node-78-datavalidator .
docker run -p 8078:8078 galaxy-node-78-datavalidator
```
