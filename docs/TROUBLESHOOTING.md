# Galaxy — Troubleshooting Guide

---

## Error: `[FATAL] NATS 不可用` / `[FATAL] NATS is required but not reachable`

**Cause:** NATS server is not running. NATS is the internal scheduling mainline and is required.

**Fix:**
```bash
# Start NATS
nats-server -p 4222

# Or via Docker
docker run -d --rm -p 4222:4222 nats:latest

# Verify
nc -z localhost 4222 && echo "NATS OK" || echo "NATS NOT listening"
```

---

## Error: `NATS Gateway Adapter init failed`

**Cause:** Gateway could not connect to NATS on startup.

**Fix:**
1. Ensure NATS is running on port 4222: `nats-server -p 4222`
2. Check `GALAXY_NATS_URL` env var is correct: `echo $GALAXY_NATS_URL`
3. Check firewall rules: `iptables -L | grep 4222`

---

## Error: Port already in use (`Address already in use`)

**Cause:** Another process is using port 9000 (Gateway), 8071 (Node_71), or 4222 (NATS).

**Fix:**
```bash
# Find which process is using the port
lsof -i :4222
lsof -i :9000
lsof -i :8071

# Kill the process (replace PID)
kill -9 <PID>

# Windows equivalent
netstat -ano | findstr :4222
taskkill /PID <PID> /F
```

---

## Error: `nats-server: command not found`

**Cause:** NATS server is not installed.

**Fix:**
```bash
# macOS
brew install nats-server

# Debian/Ubuntu
apt install nats-server

# Manual (see https://github.com/nats-io/nats-server/releases for latest version)
# Example for Linux amd64:
curl -L https://github.com/nats-io/nats-server/releases/download/v2.10.24/nats-server-v2.10.24-linux-amd64.zip \
     -o nats.zip
unzip nats.zip && sudo mv nats-server-v2.10.24-linux-amd64/nats-server /usr/local/bin/

# Windows: download from https://github.com/nats-io/nats-server/releases
```

---

## Error: `Node_71 /health: 不可达` (Node_71 unreachable)

**Cause:** Node_71 multi-device coordinator is not running.

**Fix:**
```bash
# Start Node_71 directly
cd nodes/Node_71_MultiDevice
python main.py

# Or via Docker Compose
docker compose up -d node-71
```

---

## Warning: `enhancements.multidevice is DISABLED by default`

**Cause:** The legacy multidevice compatibility layer is disabled (this is intentional).

**Fix (only if you need AIP v2 legacy clients):**
```bash
export GALAXY_ENABLE_LEGACY_MULTIDEVICE=true
bash start.sh
```

> **Note:** The canonical multi-device engine is Node_71. Enable the legacy layer only for AIP v2 backward compatibility.

---

## Error: `NATS status: disconnected` in `/health/nats` API

**Cause:** Gateway started but NATS connection dropped after startup.

**Fix:**
1. Check NATS process: `ps aux | grep nats-server`
2. Restart NATS: `nats-server -p 4222`
3. Check Galaxy logs for reconnect attempts
4. Run health check: `bash scripts/health_check.sh`

---

## Error: `pip install failed` / Dependency errors

**Cause:** Python dependencies missing or incompatible version.

**Fix:**
```bash
pip install -r requirements.txt

# If virtual environment is broken
rm -rf venv
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## Error: Docker container `galaxy-nats` exits immediately

**Cause:** Another NATS process is using port 4222, or the container name conflicts.

**Fix:**
```bash
# Remove stale container
docker rm galaxy-nats 2>/dev/null || true

# Start fresh
docker run -d --name galaxy-nats --rm -p 4222:4222 nats:latest

# Check logs
docker logs galaxy-nats
```

---

## Dashboard shows NATS as "disconnected" / "noop"

**Cause:** NATS was not running when Galaxy started, or connection was lost.

**Fix:**
1. Start NATS: `nats-server -p 4222`
2. Restart Galaxy: `bash start.sh`
3. NATS is now required — Galaxy will fail to start if NATS is unreachable

---

## Running the health check

```bash
# Linux / macOS (standalone)
bash scripts/health_check.sh

# Windows
.\scripts\health_check.ps1

# With custom endpoints
GALAXY_API_BASE=http://192.168.1.100:9000 bash scripts/health_check.sh
```

---

## Collecting diagnostics for a bug report

```bash
bash scripts/health_check.sh 2>&1 | tee /tmp/galaxy_health.txt
cat /tmp/galaxy_health.txt
```

Include the output when filing a bug report.

---

See also:
- [DEPLOYMENT_COMPLETE.md](DEPLOYMENT_COMPLETE.md) — Complete deployment guide
- [ACCEPTANCE_CHECKLIST.md](ACCEPTANCE_CHECKLIST.md) — Verification checklist
- [COMPATIBILITY_TOGGLES.md](COMPATIBILITY_TOGGLES.md) — Legacy feature toggles
