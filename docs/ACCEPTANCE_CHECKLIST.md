# Galaxy — System Acceptance Checklist

Use this checklist to verify that the Galaxy system is correctly deployed
according to the "Gateway + Node_71 + NATS mainline" architecture.

---

## A. Startup & Dependencies

- [ ] NATS server is running on port 4222 before Galaxy starts
- [ ] `start.sh` / `start.bat` auto-starts NATS if not already running
- [ ] If NATS fails to start, the startup script exits with a clear error message
- [ ] `GALAXY_NATS_URL` is set (or defaults to `nats://localhost:4222`)
- [ ] Galaxy startup fails with `[FATAL]` if NATS cannot be reached
- [ ] Key service ports are available: Gateway (9000), Node_71 (8071), NATS (4222)

---

## B. Unified Entry & Protocol

- [ ] All devices/clients connect only through Galaxy Gateway (port 9000)
- [ ] Gateway accepts AIP v3 protocol connections
- [ ] Legacy AIP v2 entry points (`/ws/ufo3` etc.) are disabled by default
- [ ] Enabling legacy requires explicit `GALAXY_ENABLE_LEGACY_MULTIDEVICE=true`
- [ ] `GET /health` on Gateway returns HTTP 200
- [ ] `GET /api/v1/system/info` returns HTTP 200

---

## C. NATS as Scheduling Mainline

- [ ] `GET /health/nats` returns `{ "status": "connected", "required": true }`
- [ ] `GET /api/v1/observability/nats` shows NATS bus topology
- [ ] NATS `noop_mode` is `false` (real connection, not stub)
- [ ] Internal routing uses NATS (command_router, proxy_relay publish to NATS subjects)
- [ ] If NATS goes down after startup, the system logs errors (not silently ignores)

---

## D. Multi-Device Coordination (Node_71)

- [ ] `GET http://localhost:8071/health` returns HTTP 200
- [ ] Multi-device tasks are routed to Node_71 (not legacy multidevice layer)
- [ ] Node_71 registers with NATS bus on startup
- [ ] Node_71 heartbeat visible in `GET /api/v1/observability/nats`
- [ ] If Node_71 is unreachable, the system logs a warning (does not silently route elsewhere)

---

## E. Legacy Compatibility Layer

- [ ] `enhancements/multidevice` is disabled by default (importing it shows a warning)
- [ ] `GALAXY_ENABLE_LEGACY_MULTIDEVICE=false` (or unset) — legacy layer inactive
- [ ] Setting `GALAXY_ENABLE_LEGACY_MULTIDEVICE=true` activates the layer
- [ ] Legacy layer does NOT maintain independent device state when enabled
- [ ] Legacy layer only performs AIP v2 protocol/message adaptation

---

## F. Observability & Dashboard

- [ ] Dashboard (port 9000) shows NATS status as "required"
- [ ] Dashboard shows NATS as ❌ "disconnected" (with error message) when NATS is down
- [ ] Dashboard shows NATS as ✅ "connected" when NATS is running
- [ ] `GET /health/nats` includes `"required": true` field
- [ ] Health check scripts pass: `bash scripts/health_check.sh`

---

## G. Startup Health Check

- [ ] After startup, Galaxy automatically runs health checks
- [ ] Health check output is visible in startup logs
- [ ] If any check fails, diagnostics are printed including:
  - [ ] Gateway reachability + HTTP status
  - [ ] Node_71 reachability + HTTP status
  - [ ] NATS port 4222 listening check
  - [ ] Key port availability (9000, 8071, 4222)
  - [ ] Docker container status (if Docker is available)

---

## H. Health Check Scripts (Standalone)

- [ ] `bash scripts/health_check.sh` runs without errors when system is healthy
- [ ] `.\scripts\health_check.ps1` runs without errors on Windows when system is healthy
- [ ] Scripts exit with code 0 on success, non-zero on failure
- [ ] Scripts accept environment variable overrides (`GALAXY_API_BASE`, `GALAXY_NATS_URL`, etc.)

---

## I. Documentation

- [ ] `docs/DEPLOYMENT_COMPLETE.md` covers Docker, local, and Windows deployments
- [ ] `docs/TROUBLESHOOTING.md` covers common errors and fixes
- [ ] `docs/ACCEPTANCE_CHECKLIST.md` (this file) is up to date
- [ ] `docs/COMPATIBILITY_TOGGLES.md` lists all legacy feature toggles

---

## Running the acceptance verification

```bash
# 1. Start NATS
nats-server -p 4222 &

# 2. Start Galaxy
bash start.sh &
sleep 10

# 3. Run health check
bash scripts/health_check.sh

# 4. Verify NATS is required
curl -s http://localhost:9000/health/nats | python3 -m json.tool

# 5. Verify legacy multidevice is disabled
python3 -c "import enhancements.multidevice" 2>&1 | grep -i "disabled"

# 6. Enable legacy multidevice (test only)
GALAXY_ENABLE_LEGACY_MULTIDEVICE=true python3 -c "
import enhancements.multidevice as m
print('Legacy layer version:', m.__version__)
"
```

---

See also:
- [DEPLOYMENT_COMPLETE.md](DEPLOYMENT_COMPLETE.md)
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
- [COMPATIBILITY_TOGGLES.md](COMPATIBILITY_TOGGLES.md)
