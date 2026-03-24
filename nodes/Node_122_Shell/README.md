# Node 122 - Shell

Shell command execution and process management service. Provides secure shell execution, process monitoring, environment inspection, and script running for the Galaxy node mesh.

## Port
Default port: **8122**

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `NODE_PORT` | `8122` | Listening port |
| `NODE_ID` | `122` | Node identifier |
| `LOG_LEVEL` | `INFO` | Logging level |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/execute` | Execute a shell command |
| `POST` | `/script` | Run a multi-line script |
| `POST` | `/background` | Execute a command in the background |
| `POST` | `/kill` | Terminate a process by PID |
| `GET` | `/processes` | List running processes |
| `GET` | `/env` | Inspect environment variables |
| `GET` | `/which` | Locate an executable on PATH |
| `GET` | `/cwd` | Get current working directory |
| `POST` | `/run` | Convenience alias for `/execute` |

## Dependencies

See `requirements.txt` for full dependency list.

## Running

```bash
pip install -r requirements.txt
python main.py
```

Or with Docker:

```bash
docker build -t galaxy-node-122-shell .
docker run -p 8122:8122 galaxy-node-122-shell
```

## Governance

`startup_policy: optional` — started if available; startup failure does not abort the system.
Promote to `active` after passing integration tests and health-check review (see `docs/NODE_ACTIVE_MANIFEST.md`).
