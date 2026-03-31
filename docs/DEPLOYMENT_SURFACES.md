# Galaxy — Deployment Surfaces Reference

This document is the **canonical reference** for all Docker and Docker Compose
deployment surfaces in the Galaxy repository.  Consult it to understand which
surface to use for development, production, CI, and specialised workloads.

---

## Quick reference

| Surface | Purpose | When to use |
|---------|---------|-------------|
| `docker-compose.yml` | **Development** — core services + optional profiles | Daily local development |
| `deploy/compose/production.yml` | **Production** — 24/7 with restart policies + monitoring | Server deployment |
| `deploy/compose/full.yml` | **Full system** — all 130 nodes + infra, profile-driven | Complete system testing |
| `deploy/compose/kimi.yml` | **Legacy / special-purpose** — database/middleware only | Legacy Kimi integration |
| `Dockerfile` | Main Galaxy application image | Base for `docker-compose.yml` & production |
| `Dockerfile.gateway` | Lightweight API gateway image | Gateway-only deployments |
| `Dockerfile.node` | Generic per-node image (parameterised) | Building individual nodes |
| `Dockerfile.agentcpm` | AgentCPM-GUI inference service (GPU) | AI-model inference workloads |

All non-development Compose files and deployment scripts live under `deploy/`.
See `deploy/README.md` for the full directory layout.

---

## Canonical surfaces

### Development — `docker-compose.yml` + `Dockerfile`

The **default** surface for local development.

```bash
# Core services only
docker compose up -d

# All services (full profile)
docker compose --profile full up -d
```

**Services:**
- `galaxy` — Main Galaxy application (API + scheduler), port 9000
- `galaxy-gateway` — Lightweight API gateway
- `neo4j` — Graph database (MemOS), port 7474/7687
- `qdrant` — Vector database, port 6333/6334
- `redis` — Cache & message broker, port 6379
- `mongodb` — Document storage, port 27017
- `ollama` — Local LLM serving, port 11434
- `coturn` — WebRTC TURN server *(profile: full)*
- `minio` — Object storage *(profile: full)*
- `oneapi` — LLM API gateway *(profile: full)*
- `memos` — MemOS memory system *(profile: full)*
- `agentcpm` — AgentCPM-GUI *(profile: full)*

**Dockerfile:** `Dockerfile` — multi-stage build, non-root user, tini init.

---

### Production — `deploy/compose/production.yml` + `Dockerfile`

The **canonical production** surface.  Uses the same `Dockerfile` as
development but adds:

- `restart: unless-stopped` on all services
- Resource limits (`cpus`, `memory`)
- Full observability stack (Prometheus, Grafana, Loki, Fluent-Bit, cAdvisor)
- Separate named volumes for durability

```bash
docker compose -f deploy/compose/production.yml up -d
docker compose -f deploy/compose/production.yml logs -f galaxy
```

---

### Full system — `deploy/compose/full.yml`

Orchestrates **all 130 Galaxy nodes** plus the complete infrastructure stack.
Uses profiles to allow incremental bring-up:

```bash
# Infrastructure only (Redis, Qdrant, …)
docker compose -f deploy/compose/full.yml up -d

# Infrastructure + critical nodes
docker compose -f deploy/compose/full.yml --profile core up -d

# Everything
docker compose -f deploy/compose/full.yml --profile full up -d
```

All ports derive from `config/unified_ports.yaml` — the single source of truth
for port assignments.

**Use for:** comprehensive integration testing, full-system demo environments.

---

## Specialised / legacy surfaces

### `deploy/compose/kimi.yml` — Legacy Kimi infrastructure

Brings up the database and middleware layer originally used for the Kimi
integration:
- Neo4j, Qdrant, Redis, MongoDB — port assignments as per legacy convention

> **Status:** Legacy / special-purpose.  New deployments should use
> `docker-compose.yml` or `deploy/compose/production.yml`.  Retained for
> backward-compatibility with external Kimi tooling.

---

## Dockerfile catalogue

### `Dockerfile` — Main Galaxy application

Multi-stage (builder → runtime) image for the core Galaxy service.

- Base: `python:3.11-slim`
- Non-root user: `galaxy` (UID 1000)
- Init: `tini`
- Entrypoint: `python unified_launcher.py --host 0.0.0.0 --port 9000`
- Health check: `GET /health/live` on port 9000

### `Dockerfile.gateway` — API Gateway

Lightweight image running only the `galaxy_gateway` FastAPI application.

- Entrypoint: `uvicorn galaxy_gateway.app:app`
- Role: internal cross-device execution substrate (not the primary subject
  entry point — see `core/routes/` for canonical API endpoints)

### `Dockerfile.node` — Generic node

Parameterised build for any Galaxy node:

```bash
docker build \
  --build-arg NODE_NAME=Node_02_Tasker \
  --build-arg NODE_PORT=8002 \
  -f Dockerfile.node -t galaxy-node-02 .
```

### `Dockerfile.agentcpm` — AgentCPM-GUI

GPU-accelerated inference service.  Requires NVIDIA GPU runtime.
Special-purpose; not part of the standard development stack.

---

## Startup scripts

| Script | Role | Status |
|--------|------|--------|
| `start.sh` | Linux quick-start (dev) | Active — **canonical dev launcher** |
| `start.bat` | Windows quick-start (dev) | Active — **canonical dev launcher** |
| `deploy/scripts/start_unified.sh` | Extended bootstrap with env setup | Active |
| `deploy/scripts/deploy.sh` | Production deployment helper | Active |
| `unified_launcher.py` | Python entry point (preferred) | **Canonical** |
| `main.py` | Alternate Python entry point | Active |

For production, prefer `unified_launcher.py` or
`docker compose -f deploy/compose/production.yml`.

---

## Port assignments

All canonical port assignments are defined in `config/unified_ports.yaml`.
Do not hard-code ports outside that file.

---

## Related documents

- `deploy/README.md` — deploy/ directory layout and usage guide
- `DEPLOYMENT_GUIDE.md` — step-by-step deployment instructions
- `QUICKSTART.md` — five-minute quick-start for local development
- `docs/architecture/CANONICAL_ENTRYPOINTS.md` — authoritative entrypoint inventory
- `config/unified_ports.yaml` — canonical port registry
