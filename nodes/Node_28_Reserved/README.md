# Node 28 - Plugin Manager

Port: **8028**

Dynamically loads, executes, and manages local Python plugins from a configurable directory.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `PLUGIN_DIR` | `./plugins` | Directory to scan for plugins |
| `NODE_28_NAME` | `PluginManager` | Display name |

## Plugin Format

Each plugin is a `.py` file in `PLUGIN_DIR/` with:

```python
PLUGIN_NAME = "MyPlugin"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "What this plugin does"

async def execute(params: dict) -> dict:
    return {"success": True, "result": "..."}
```

## Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/status` | Node stats |
| GET | `/plugins` | List all plugins |
| POST | `/plugins/load` | Scan and load plugins from directory |
| POST | `/plugins/reload` | Reload a specific plugin |
| POST | `/plugins/enable` | Enable a plugin |
| POST | `/plugins/disable` | Disable a plugin |
| DELETE | `/plugins/{name}` | Unload plugin |
| GET | `/plugins/{name}` | Get plugin details |
| POST | `/plugins/execute` | Execute plugin's `execute()` function |

## Quick Start

```bash
pip install -r requirements.txt
python main.py
```

## Example Usage

```bash
# Load plugins
curl -X POST http://localhost:8028/plugins/load

# Execute plugin
curl -X POST http://localhost:8028/plugins/execute \
  -H "Content-Type: application/json" \
  -d '{"plugin_name": "ExamplePlugin", "params": {"message": "Hello!"}}'
```
