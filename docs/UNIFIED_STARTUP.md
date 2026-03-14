# Galaxy — Unified Startup & Port Registry

> **Single source of truth**: `config/unified_ports.yaml`

This document describes how to start the full Galaxy system (130 nodes + infrastructure), explains the port registry, and shows how to validate the configuration.

---

## Table of Contents

1. [Port Registry](#1-port-registry)
2. [Quick Start Commands](#2-quick-start-commands)
3. [Startup Modes](#3-startup-modes)
4. [Port Conflict Validation](#4-port-conflict-validation)
5. [Docker Compose Profiles](#5-docker-compose-profiles)
6. [Non-Docker (Local) Startup](#6-non-docker-local-startup)
7. [Dependency Graph](#7-dependency-graph)
8. [Troubleshooting](#8-troubleshooting)

---

## 1. Port Registry

All ports are defined in **`config/unified_ports.yaml`** — the single authoritative source.

### Port Ranges

| Range | Layer | Examples |
|-------|-------|---------|
| 7995–7999 | Kernel overflows | Node_01 OneAPI (7995), Node_09 Sandbox (7996) |
| 8000–8009 | Kernel / Core | StateMachine (8000), Tasker (8002) … |
| 8010–8049 | Tools | Slack (8010), GitHub (8011), SSH (8039) … |
| 8050–8068 | Intelligence | Transformer (8050), GraphLogic (8053) … |
| 8070–8099 | Advanced / Multimodal | LocalLLM (8079), EmbeddingService (8099) … |
| 8100–8130 | Academic | MemorySystem (8100), AutonomousCoding (8130) |
| 8160, 8163, 8180 | Intelligence overflows | RL (8160), Fuzzy (8163), MemSystem v2 (8180) |
| 8299 | Infrastructure | UnifiedLauncher Web UI |
| 8765 | Gateway | Galaxy API Gateway |
| 3001 | OneAPI Web | External LLM Gateway UI |
| 4222 / 8222 | NATS | Client / HTTP monitor |
| 6333 / 6334 | Qdrant | REST / gRPC |
| 6379 | Redis | Cache |
| 7233 / 8233 | Temporal | Workflow engine / UI |
| 7474 / 7687 | Neo4j | HTTP / Bolt |
| 8766 / 8767 | Device/UFO APIs | Device control API / UFO API |
| 9100 | Health Monitor | System health checks |
| 11434 | Ollama | Local LLM inference |
| 27017 | MongoDB | Document store |

### Reading Ports Programmatically

```python
from core.port_config import get_node_port, get_service_port

# Node port
port = get_node_port("Node_50_Transformer")   # → 8050
port = get_node_port("Node_50")               # prefix match → 8050

# Infrastructure port
redis_port = get_service_port("redis")         # → 6379
launcher_port = get_service_port("unified_launcher")  # → 8299
```

Environment variable overrides are also supported:
```bash
export GALAXY_PORT_NODE_50_TRANSFORMER=9050   # override Node_50 port
export GALAXY_REDIS_PORT=6380                 # override redis port
```

---

## 2. Quick Start Commands

### Docker — Recommended for Full System

```bash
# Infrastructure only (Redis, Qdrant, Neo4j, MongoDB, NATS, Temporal, Ollama)
docker compose -f docker-compose.full.yml up -d

# Core nodes (critical nodes + infra)
docker compose -f docker-compose.full.yml --profile core up -d

# Full system — all 130 nodes + all infra
docker compose -f docker-compose.full.yml --profile full up -d

# Stop everything
docker compose -f docker-compose.full.yml --profile full down
```

### Docker — Dev Core (existing docker-compose.yml)

```bash
# Development core services only
docker compose up -d

# All dev services
docker compose --profile full up -d
```

### Local (Non-Docker)

```bash
# Start unified launcher (manages all nodes)
python unified_launcher.py

# Minimal mode (core nodes only)
python unified_launcher.py --minimal

# Custom port
python unified_launcher.py --port 8299

# Check status
python unified_launcher.py --status
```

---

## 3. Startup Modes

### Mode 1 — Infrastructure Only (default, no profile)

Starts: Redis, Qdrant, Neo4j, MongoDB, NATS, Temporal, Ollama, Galaxy Core + Gateway

```bash
docker compose -f docker-compose.full.yml up -d
```

### Mode 2 — Core Profile

Adds all **critical** nodes to infrastructure:
- Node_00_StateMachine (8000)
- Node_01_OneAPI (7995)
- Node_02_Tasker (8002)
- Node_03_SecretVault (8003)
- Node_04_Router (8004)
- Node_05_Auth (8005)
- Node_06_Filesystem (8006)
- Node_64_LoggerCentral (8064) — renamed from Node_65
- Node_66_HealthMonitor (8066) — renamed from Node_67
- Node_67_Security (8067) — renamed from Node_68
- Node_79_LocalLLM (8079)
- Node_80_MemorySystem (8180)
- Galaxy Launcher (8299)

```bash
docker compose -f docker-compose.full.yml --profile core up -d
```

### Mode 3 — Full Profile

All 130 nodes + all infrastructure.

```bash
docker compose -f docker-compose.full.yml --profile full up -d
```

> ⚠️ Starting all 130 nodes at once is resource-intensive.
> Ensure at least **16 GB RAM** and **8 CPU cores** are available.
> The `start_period: 30s` health check gives each node time to initialize.

### Mode 4 — Worker Profile

Adds the Go edge worker alongside infrastructure.

```bash
docker compose -f docker-compose.full.yml --profile worker up -d
```

---

## 4. Port Conflict Validation

Run the validation script at any time to check for port conflicts and coverage:

```bash
# Standard check
python scripts/validate_ports.py

# With suggested fixes for missing entries
python scripts/validate_ports.py --fix-hints

# JSON output (for CI integration)
python scripts/validate_ports.py --json

# Check against a different compose file
python scripts/validate_ports.py --compose docker-compose.yml
```

Expected output when all is well:
```
======================================================================
Galaxy Port Registry Validation
======================================================================
  unified_ports.yaml nodes : 130
  nodes/ directories       : 130
  infrastructure services  : 19
  compose services checked : 144

  ✓  No issues found.

Result: PASS
======================================================================
```

### CI Integration

Add to your workflow:

```yaml
- name: Validate port registry
  run: python scripts/validate_ports.py --json
```

---

## 5. Docker Compose Profiles

| Profile | Services included |
|---------|------------------|
| *(none)* | Infrastructure (Redis, Qdrant, Neo4j, MongoDB, NATS, Temporal, Ollama) + Galaxy Core + Gateway |
| `core` | + Critical nodes + Galaxy Launcher |
| `full` | + All 130 nodes + OneAPI + MinIO + Coturn + Galaxy Launcher |
| `worker` | + Go Edge Worker |

Profiles can be combined:
```bash
docker compose -f docker-compose.full.yml --profile core --profile worker up -d
```

---

## 6. Non-Docker (Local) Startup

The `unified_launcher.py` reads all port assignments from `config/unified_ports.yaml` via `core.port_config` and starts all node processes.

```
unified_launcher.py
    └── SystemConfig.__post_init__()
            └── core.port_config.get_service_port("unified_launcher") → 8299
    └── NodeSystemLauncher.start_all()
            └── For each node in node_dependencies.json:
                    └── core.port_config.get_node_port(node_name) → port from yaml
                    └── subprocess: python nodes/<Node_Name>/main.py
```

Each node main.py also reads its port from `core.port_config`:
```python
from core.port_config import get_node_port
NODE_PORT = int(os.getenv("NODE_PORT", str(get_node_port("Node_50_Transformer"))))
```

---

## 7. Dependency Graph

```
Infrastructure (always starts first):
  Redis ──────────────────────────┐
  Qdrant ─────────────────────────┤
  Neo4j ──────────────────────────┤
  MongoDB ────────────────────────┤
  NATS ───────────────────────────┤
  Temporal (→ temporal-db) ───────┤
  Ollama ─────────────────────────┴─→ All Nodes

Kernel Layer (critical, profile: core):
  Node_00_StateMachine → Node_01_OneAPI → Node_02_Tasker
                                        → Node_03_SecretVault
                                        → Node_04_Router
                                        → Node_05_Auth
                                        → Node_06_Filesystem
  Node_64_LoggerCentral → Node_67_Security
  Node_66_HealthMonitor
  Node_79_LocalLLM
  Node_80_MemorySystem

All other nodes (profile: full):
  Depend on Redis + (indirectly) Node_01_OneAPI
```

---

## 8. Troubleshooting

### "Connection refused" on a node port

1. Check if the node container is running:
   ```bash
   docker ps | grep node-<XX>
   ```
2. Check the port is correctly assigned in `config/unified_ports.yaml`
3. Run the validator:
   ```bash
   python scripts/validate_ports.py
   ```

### Port conflict at startup

The validator will catch conflicts:
```bash
python scripts/validate_ports.py --fix-hints
```

### OpenClawd / Windows UI "connection refused"

The Windows client (`windows_client/ui/sidebar_ui.py`) connects to the Galaxy API. Verify the `api_base` URL matches the port shown in `runtime/entrypoint.json` (written by `unified_launcher.py` at startup).

```bash
cat runtime/entrypoint.json
# → { "api_base": "http://localhost:8299", ... }
```

If running in Docker, the Galaxy Core service is on port **8080** and the Launcher UI on **8299**.

### Adding a new node

1. Create `nodes/Node_NNN_NewNode/` with `main.py`, `requirements.txt`, `Dockerfile`.
2. Add an entry to `config/unified_ports.yaml` (choose an unused port).
3. Run `python scripts/validate_ports.py` to confirm no conflicts.
4. Regenerate (or manually add) the node service to `docker-compose.full.yml`.
5. Register in `node_dependencies.json` for the unified launcher.

---

## Key Files

| File | Purpose |
|------|---------|
| `config/unified_ports.yaml` | **Single source of truth** for all ports |
| `core/port_config.py` | Python API for reading port assignments |
| `docker-compose.full.yml` | Full system (all 130 nodes + infra) |
| `docker-compose.yml` | Dev core (infra + galaxy app) |
| `scripts/validate_ports.py` | Port conflict and coverage validator |
| `unified_launcher.py` | Non-Docker process launcher |
| `runtime/entrypoint.json` | Written at startup; clients read API base URL |
