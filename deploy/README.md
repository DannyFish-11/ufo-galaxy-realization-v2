# deploy/ — Deployment Assets

This directory contains all non-development deployment assets for the Galaxy system.
The root `docker-compose.yml` remains the **canonical development entrypoint** and is
intentionally kept at repository root for convenience.

---

## Directory layout

```
deploy/
├── README.md                      ← This file
├── compose/
│   ├── full.yml                   ← Full system (all 130 nodes + infra, profile-driven)
│   ├── kimi.yml                   ← Legacy Kimi infrastructure surface
│   └── production.yml             ← Production deployment (24/7, monitoring, resource limits)
└── scripts/
    ├── deploy.sh                  ← Production deployment helper
    └── start_unified.sh           ← Extended dev bootstrap with env setup
```

---

## Quick reference

| Surface | File | When to use |
|---------|------|-------------|
| **Development** (canonical) | `docker-compose.yml` (root) | Daily local development |
| **Production** | `deploy/compose/production.yml` | Server deployment (24/7) |
| **Full system** | `deploy/compose/full.yml` | Complete integration testing (all 130 nodes) |
| **Kimi legacy** | `deploy/compose/kimi.yml` | Legacy Kimi infrastructure only |

---

## compose/

### `production.yml`

Production-grade Compose with restart policies, resource limits, and a full
observability stack (Prometheus, Grafana, Loki, Fluent-Bit, cAdvisor).

```bash
docker compose -f deploy/compose/production.yml up -d
docker compose -f deploy/compose/production.yml logs -f galaxy
```

### `full.yml`

Orchestrates all 130 Galaxy nodes plus the complete infrastructure stack.
Uses profiles for incremental bring-up.

```bash
# Infrastructure only
docker compose -f deploy/compose/full.yml up -d

# Infrastructure + critical nodes
docker compose -f deploy/compose/full.yml --profile core up -d

# Everything
docker compose -f deploy/compose/full.yml --profile full up -d
```

### `kimi.yml`

Legacy Kimi database/middleware surface. Retained for compatibility.

```bash
docker compose -f deploy/compose/kimi.yml up -d
```

---

## scripts/

### `deploy.sh`

Production deployment helper. Manages Docker Compose lifecycle, environment setup,
health checks, and optional systemd installation.

```bash
./deploy/scripts/deploy.sh up            # Deploy full stack via docker-compose
./deploy/scripts/deploy.sh local         # Run Galaxy locally (no Docker)
./deploy/scripts/deploy.sh status        # Show service status
./deploy/scripts/deploy.sh logs galaxy   # Tail galaxy logs
sudo ./deploy/scripts/deploy.sh install  # Install as systemd service
```

### `start_unified.sh`

Extended development bootstrap with Python environment detection, dependency
installation, and config validation. Delegates to `unified_launcher.py`.

```bash
./deploy/scripts/start_unified.sh           # Full start with env setup
./deploy/scripts/start_unified.sh --status  # Show system status
./deploy/scripts/start_unified.sh --setup   # Run config wizard
```

For daily development, prefer `start.sh` (root) or `python main.py` directly.

---

## Canonical startup chain

```
start.sh / start.bat  ──► python main.py ──► python unified_launcher.py ──► Galaxy runtime
```

See `docs/architecture/CANONICAL_ENTRYPOINTS.md` for the full entrypoint inventory.
