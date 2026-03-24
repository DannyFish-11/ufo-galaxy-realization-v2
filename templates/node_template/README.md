# Node_XXX_YourNodeName

> Replace this line with a one-sentence description of what this node does.

---

## Purpose

<!-- Describe the responsibility of this node in 2–4 sentences.
     What problem does it solve?  Which other nodes depend on it? -->

## Port

| Env var / config key | Default | Notes |
|----------------------|---------|-------|
| `NODE_PORT`          | `XXXX`  | Declared in `node_dependencies.json` |

## Endpoints

| Method | Path      | Description |
|--------|-----------|-------------|
| GET    | `/health` | Liveness probe — always `{"status": "healthy", ...}` |
| GET    | `/status` | Readiness probe — operational state |
| …      | …         | Add your endpoints here |

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `NODE_PORT` | yes | `XXXX` | Listening port |
| …           | …   | …      | … |

## Dependencies

<!-- List other Galaxy nodes or external services this node requires. -->

Depends on:
- `Node_XX_Name` — reason

## Startup

### Local (development)

```bash
cd nodes/Node_XXX_YourNodeName
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port XXXX --reload
```

### Docker

```bash
docker build -t node-xxx-yourname .
docker run -p XXXX:XXXX node-xxx-yourname
```

### Via unified launcher

The node is started automatically by `unified_launcher.py` when it is listed
in `node_dependencies.json` with `"startup_policy": "auto"`.

## Development Notes

<!-- Architecture decisions, known limitations, links to relevant docs. -->

## Checklist (delete before merging)

- [ ] `main.py` implements `/health` and `/status` endpoints
- [ ] `fusion_entry.py` uses `importlib.util` (no `sys.path` mutation)
- [ ] Registered in `node_dependencies.json` with correct port and startup policy
- [ ] `requirements.txt` lists all Python dependencies
- [ ] `Dockerfile` builds and runs successfully
- [ ] `README.md` sections filled in (remove this checklist section)
