# Node 115 - PluginManager

Galaxy system plugin registry and lifecycle management.

## Features

- **Registry** — persistent JSON-backed plugin registry
- **Lifecycle** — register, enable, disable, remove plugins
- **Health Checking** — probe plugin endpoints on demand
- **Capability Discovery** — aggregate capabilities across enabled plugins
- **Built-in Plugins** — pre-seeded with core Galaxy plugins

## Port

`8115` (override with `NODE_115_PORT`)

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `PLUGIN_REGISTRY_PATH` | `./plugins` | Directory to persist registry |
| `PLUGIN_STORE_URL` | *(empty)* | Optional remote plugin store |

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check with plugin counts |
| GET | `/status` | Detailed status |
| GET | `/plugins` | List plugins (`?status=enabled\|disabled\|all`) |
| POST | `/plugins/register` | Register a new plugin |
| GET | `/plugins/{id}` | Get plugin details |
| POST | `/plugins/{id}/enable` | Enable a plugin |
| POST | `/plugins/{id}/disable` | Disable a plugin |
| DELETE | `/plugins/{id}` | Remove a plugin |
| POST | `/plugins/{id}/check` | Health-check a plugin |
| GET | `/capabilities` | List capabilities of enabled plugins |
| POST | `/mcp/call` | MCP tool dispatch |

## Plugin Model

```json
{
  "id": "my-plugin",
  "name": "My Plugin",
  "version": "1.0.0",
  "description": "Does something useful",
  "status": "enabled",
  "endpoint": "http://localhost:9000",
  "capabilities": ["feature_a", "feature_b"],
  "installed_at": "2024-01-01T00:00:00Z",
  "last_check": "2024-01-01T00:00:00Z"
}
```

## Quick Start

```bash
pip install -r requirements.txt
python main.py
```

## Docker

```bash
docker build -t node-115 .
docker run -p 8115:8115 node-115
```
