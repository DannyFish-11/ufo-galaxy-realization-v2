# Node 121 - Web

Web browsing, scraping and HTTP interaction service. Provides HTTP requests, content extraction, API interactions, and download capabilities for the Galaxy node mesh.

## Port
Default port: **8121**

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `NODE_PORT` | `8121` | Listening port |
| `NODE_ID` | `121` | Node identifier |
| `LOG_LEVEL` | `INFO` | Logging level |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/request` | Generic HTTP request |
| `POST` | `/get` | HTTP GET request |
| `POST` | `/post` | HTTP POST request |
| `POST` | `/scrape` | Web page scraping and content extraction |
| `POST` | `/download` | File download |
| `POST` | `/api` | API endpoint call |
| `POST` | `/batch` | Batch HTTP requests |
| `GET` | `/parse-url` | Parse and validate a URL |

## Dependencies

See `requirements.txt` for full dependency list.

## Running

```bash
pip install -r requirements.txt
python main.py
```

Or with Docker:

```bash
docker build -t galaxy-node-121-web .
docker run -p 8121:8121 galaxy-node-121-web
```

## Governance

`startup_policy: optional` — started if available; startup failure does not abort the system.
Promote to `active` after passing integration tests and health-check review (see `docs/NODE_ACTIVE_MANIFEST.md`).
