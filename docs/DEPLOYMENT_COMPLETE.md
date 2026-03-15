# Galaxy — Complete Deployment Guide

> Architecture: **Gateway (AIP v3) → NATS (mainline) → Node_71 (multi-device) → Core**

---

## Prerequisites

| Component      | Version    | Required |
|----------------|-----------|----------|
| Python         | 3.9+      | ✅ Yes   |
| NATS Server    | 2.x+      | ✅ Yes   |
| Docker         | 24+       | Optional |
| Docker Compose | 2.x+      | Optional |

---

## 1. Local Deployment (Linux / macOS)

### 1.1 Install NATS (required)

```bash
# macOS
brew install nats-server

# Debian/Ubuntu
apt install nats-server

# Direct binary download (see https://github.com/nats-io/nats-server/releases for latest version)
# Example for Linux amd64:
curl -L https://github.com/nats-io/nats-server/releases/download/v2.10.24/nats-server-v2.10.24-linux-amd64.zip \
     -o nats.zip
unzip nats.zip && sudo mv nats-server-v2.10.24-linux-amd64/nats-server /usr/local/bin/
```

### 1.2 Start NATS

```bash
nats-server -p 4222
```

### 1.3 Clone and start Galaxy

```bash
git clone https://github.com/DannyFish-11/ufo-galaxy-realization-v2.git
cd ufo-galaxy-realization-v2

# Set NATS URL (optional — defaults to nats://localhost:4222)
export GALAXY_NATS_URL=nats://localhost:4222

# Start (NATS is auto-started if nats-server is on PATH)
bash start.sh
```

### 1.4 Verify

```bash
bash scripts/health_check.sh
```

---

## 2. Windows Deployment

### 2.1 Install NATS

Download from: https://github.com/nats-io/nats-server/releases

Add `nats-server.exe` to your PATH.

### 2.2 Start Galaxy

```bat
start.bat
```

NATS is auto-started by `start.bat` if `nats-server.exe` is on PATH.

### 2.3 Verify

```powershell
.\scripts\health_check.ps1
```

---

## 3. Docker Compose Deployment

### 3.1 Start all services

```bash
docker compose -f docker-compose.yml up -d
```

The compose file starts:
- `nats` — NATS server (port 4222)
- `galaxy-gateway` — Galaxy Gateway (port 9000)
- `node-71` — Multi-device coordinator (port 8071)

### 3.2 Verify

```bash
bash scripts/health_check.sh
```

Or check container status:

```bash
docker compose ps
docker logs galaxy-nats
docker logs galaxy-gateway
```

### 3.3 Stop

```bash
docker compose down
```

---

## 4. Environment Variables

| Variable                          | Default                     | Description                                    |
|-----------------------------------|-----------------------------|------------------------------------------------|
| `GALAXY_NATS_URL`                 | `nats://localhost:4222`     | NATS server URL (required)                     |
| `GALAXY_NATS_PORT`                | `4222`                      | NATS port                                      |
| `GALAXY_API_BASE`                 | `http://localhost:9000`     | Galaxy gateway/core base URL                   |
| `GALAXY_MASTER_BRAIN_ENABLED`     | `false`                     | Enable MasterBrain orchestrator                |
| `GALAXY_ENABLE_LEGACY_MULTIDEVICE`| `false`                     | Enable legacy AIP v2 multidevice compat layer  |

### Enabling the legacy multidevice compatibility layer

The legacy multidevice layer (`enhancements/multidevice`) is **disabled by default**.
To enable it for legacy AIP v2 clients:

```bash
export GALAXY_ENABLE_LEGACY_MULTIDEVICE=true
bash start.sh
```

> **Note:** The canonical multi-device coordination engine is **Node_71**.
> Use the legacy layer only if you have existing AIP v2 binary clients.

---

## 5. Architecture Overview

```
Devices / Clients
       │ (HTTP / WebSocket)
       ▼
  Galaxy Gateway  (AIP v3)          ← Sole external entry point
       │
       ▼
  NATS  (port 4222)                 ← Internal scheduling mainline (REQUIRED)
       │
       ▼
  Node_71  (port 8071)              ← Multi-device coordination engine
       │
       ▼
  Core / UDM / Router  (port 9000)

Legacy compatibility (disabled by default):
  enhancements/multidevice          ← AIP v2 adapter only
```

---

## 6. Health Check

After startup, run:

```bash
# Linux / macOS
bash scripts/health_check.sh

# Windows
.\scripts\health_check.ps1
```

Expected output:
```
✅ NATS port 4222:    监听中
✅ Gateway /health:   HTTP 200
✅ system/info:       HTTP 200
✅ Node_71 /health:   HTTP 200
✅ 所有检查通过
```

---

## 7. Rollback

If you need to revert to the previous behavior where NATS was optional:

1. Set `GALAXY_NATS_URL=` (empty) — the system will still fail as NATS is now required
2. To fully revert: `git revert HEAD` on the PR commit
3. The legacy multidevice layer can be re-enabled at any time with `GALAXY_ENABLE_LEGACY_MULTIDEVICE=true`

---

See also:
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — Common errors and fixes
- [ACCEPTANCE_CHECKLIST.md](ACCEPTANCE_CHECKLIST.md) — Verification checklist
- [COMPATIBILITY_TOGGLES.md](COMPATIBILITY_TOGGLES.md) — Legacy feature toggles
