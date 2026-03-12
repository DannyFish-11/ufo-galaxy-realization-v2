# Node 89 - API Gateway

API gateway for routing, node registry management, rate limiting, and proxying requests to other Galaxy nodes.

## Port
Default port: **8089**

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GATEWAY_RATE_LIMIT` | `100` | Requests per minute per client |
| `GATEWAY_TIMEOUT` | `30` | Request timeout in seconds |
| `NODE_REGISTRY_URL` | `` | External node registry URL |
| `NODE_ID` | `89` | Node identifier |
| `LOG_LEVEL` | `INFO` | Logging level |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/status` | Gateway status and metrics |
| `GET` | `/routes` | List configured routes |
| `POST` | `/route/register` | Register a route |
| `DELETE` | `/route/{id}` | Remove a route |
| `ANY` | `/proxy/{node_id}/{path}` | Proxy request to a node |
| `GET` | `/nodes` | List registered nodes with health |
| `POST` | `/node/register` | Register a node |
| `DELETE` | `/node/{node_id}` | Unregister a node |
| `GET` | `/metrics` | Gateway metrics |
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
docker build -t galaxy-node-89-apigateway .
docker run -p 8089:8089 galaxy-node-89-apigateway
```
