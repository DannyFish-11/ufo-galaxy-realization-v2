# Node 120 - File

High-level file management and structured I/O service. Provides comprehensive file-system operations for the Galaxy node mesh.

## Port
Default port: **8120**

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `NODE_PORT` | `8120` | Listening port |
| `NODE_ID` | `120` | Node identifier |
| `LOG_LEVEL` | `INFO` | Logging level |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/read` | Read file contents |
| `POST` | `/write` | Write data to a file |
| `POST` | `/append` | Append data to a file |
| `POST` | `/delete` | Delete a file or directory |
| `POST` | `/copy` | Copy a file or directory |
| `POST` | `/move` | Move / rename a file or directory |
| `POST` | `/list` | List directory contents |
| `POST` | `/search` | Search for files by pattern |
| `GET` | `/info` | Get file metadata and permissions |
| `POST` | `/archive` | Create a zip/tar archive |
| `POST` | `/extract` | Extract an archive |
| `POST` | `/hash` | Compute file checksum |
| `GET` | `/download` | Download a file |

## Dependencies

See `requirements.txt` for full dependency list.

## Running

```bash
pip install -r requirements.txt
python main.py
```

Or with Docker:

```bash
docker build -t galaxy-node-120-file .
docker run -p 8120:8120 galaxy-node-120-file
```

## Governance

`startup_policy: optional` — started if available; startup failure does not abort the system.
Promote to `active` after passing integration tests and health-check review (see `docs/NODE_ACTIVE_MANIFEST.md`).
