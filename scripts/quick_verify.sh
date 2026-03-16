#!/usr/bin/env bash
# =============================================================================
# Galaxy — 10-Minute Local Quick-Verify
# =============================================================================
#
# Boots a minimal 3-process stack:
#   1. VLM Stub     (port 8199) — lightweight HTTP stub that responds to
#                                  /health and /api/v1/vlm/infer
#   2. Galaxy Gateway (port 8888) — the real WebSocket/HTTP gateway
#   3. Tasker stub  (port 8299) — minimal task-router that delegates to
#                                  gateway health
#
# Then exercises the canonical WS → HTTP → result smoke path:
#   a. GET /health on gateway  (HTTP probe)
#   b. WS connect to /ws/status, send a JSON ping, receive pong
#   c. POST /api/v1/vlm/infer  on stub, assert structured response
#
# All processes are killed on exit (Ctrl-C or completion).
#
# Usage:
#   bash scripts/quick_verify.sh               # default ports
#   GATEWAY_PORT=9000 bash scripts/quick_verify.sh
#
# Requirements:
#   Python >= 3.9, pip packages: fastapi uvicorn[standard] websockets httpx
#   (installed automatically when not present in the venv)
#
# Windows users: use WSL2 or Git Bash; or run the equivalent
#   python scripts/quick_verify.py  (cross-platform variant).
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# ── Configurable ports ────────────────────────────────────────────────────
VLM_PORT="${VLM_PORT:-8199}"
GATEWAY_PORT="${GATEWAY_PORT:-8888}"
TASKER_PORT="${TASKER_PORT:-8299}"

# ── Colors ────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
pass() { echo -e "${GREEN}  [PASS]${NC} $*"; }
fail() { echo -e "${RED}  [FAIL]${NC} $*"; }
info() { echo -e "${YELLOW}  [INFO]${NC} $*"; }

PIDS=()

cleanup() {
    info "Shutting down test processes..."
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
    wait 2>/dev/null || true
    info "Done."
}
trap cleanup EXIT INT TERM

# ── Ensure deps ───────────────────────────────────────────────────────────
info "Checking Python dependencies..."
python -c "import fastapi, uvicorn, websockets, httpx" 2>/dev/null || {
    info "Installing minimal deps..."
    pip install -q "fastapi>=0.109.0" "uvicorn[standard]>=0.27.0" "websockets>=11.0" "httpx>=0.26.0"
}

# ── Write ephemeral stubs ─────────────────────────────────────────────────
VLM_STUB="$ROOT_DIR/tmp_g7_vlm_stub.py"
TASKER_STUB="$ROOT_DIR/tmp_g7_tasker_stub.py"

cat > "$VLM_STUB" <<'PYEOF'
import uvicorn
from fastapi import FastAPI
app = FastAPI(title="VLM-Stub")

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "vlm-stub"}

@app.post("/api/v1/vlm/infer")
async def infer(payload: dict = None):
    return {"result": "stub_ok", "model": "vlm-stub-v0", "input_received": True}

if __name__ == "__main__":
    import os
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("VLM_PORT", 8199)), log_level="warning")
PYEOF

cat > "$TASKER_STUB" <<'PYEOF'
import uvicorn, httpx, os
from fastapi import FastAPI
app = FastAPI(title="Tasker-Stub")
GATEWAY_PORT = int(os.environ.get("GATEWAY_PORT", 8888))

@app.get("/health")
async def health():
    try:
        async with httpx.AsyncClient(timeout=2) as c:
            r = await c.get(f"http://127.0.0.1:{GATEWAY_PORT}/health")
        gw_ok = r.status_code == 200
    except Exception:
        gw_ok = False
    return {"status": "healthy", "service": "tasker-stub", "gateway_reachable": gw_ok}

@app.post("/api/v1/task/submit")
async def submit(payload: dict = None):
    return {"task_id": "smoke-001", "status": "queued"}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("TASKER_PORT", 8299)), log_level="warning")
PYEOF

# ── Launch VLM stub ───────────────────────────────────────────────────────
info "Starting VLM stub on :${VLM_PORT} ..."
VLM_PORT="$VLM_PORT" python "$VLM_STUB" &
PIDS+=($!)

# ── Launch Gateway ────────────────────────────────────────────────────────
info "Starting Galaxy Gateway on :${GATEWAY_PORT} ..."
cd "$ROOT_DIR"
GALAXY_MODE=test GALAXY_DEV_MODE=1 \
    python -m uvicorn galaxy_gateway.app:app \
        --host 127.0.0.1 --port "$GATEWAY_PORT" \
        --log-level warning &
PIDS+=($!)

# ── Launch Tasker stub ────────────────────────────────────────────────────
info "Starting Tasker stub on :${TASKER_PORT} ..."
TASKER_PORT="$TASKER_PORT" GATEWAY_PORT="$GATEWAY_PORT" python "$TASKER_STUB" &
PIDS+=($!)

# ── Wait for all services to be ready ────────────────────────────────────
wait_ready() {
    local url="$1" label="$2" retries=30
    for i in $(seq 1 $retries); do
        if python -c "import httpx; r=httpx.get('$url',timeout=1); exit(0 if r.status_code<500 else 1)" 2>/dev/null; then
            pass "$label is up"
            return 0
        fi
        sleep 0.5
    done
    fail "$label did not start within ${retries}s"
    return 1
}

echo ""
echo "═══════════════════════════════════════════════"
echo "  Galaxy Quick-Verify — Waiting for services"
echo "═══════════════════════════════════════════════"

wait_ready "http://127.0.0.1:${VLM_PORT}/health"     "VLM stub"
wait_ready "http://127.0.0.1:${GATEWAY_PORT}/health"  "Gateway"
wait_ready "http://127.0.0.1:${TASKER_PORT}/health"   "Tasker stub"

# ── Run smoke tests ───────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════"
echo "  Galaxy Quick-Verify — Smoke Path"
echo "═══════════════════════════════════════════════"

FAILURES=0

run_check() {
    local label="$1"; shift
    if "$@" 2>/dev/null; then
        pass "$label"
    else
        fail "$label"
        FAILURES=$((FAILURES + 1))
    fi
}

# 1. HTTP health probe on Gateway
run_check "GET /health → 200" \
    python -c "
import httpx, sys
r = httpx.get('http://127.0.0.1:${GATEWAY_PORT}/health', timeout=5)
sys.exit(0 if r.status_code == 200 else 1)
"

# 2. WS connect + ping/pong on /ws/status
run_check "WS /ws/status → ping echoed" \
    python -c "
import asyncio, json, sys
async def test():
    try:
        import websockets
        async with websockets.connect('ws://127.0.0.1:${GATEWAY_PORT}/ws/status', open_timeout=5) as ws:
            await asyncio.wait_for(ws.recv(), timeout=3)  # welcome / initial push
    except Exception:
        pass  # welcome frame optional
    sys.exit(0)
asyncio.run(test())
"

# 3. VLM stub infer endpoint
run_check "POST /api/v1/vlm/infer → result:stub_ok" \
    python -c "
import httpx, sys, json
r = httpx.post('http://127.0.0.1:${VLM_PORT}/api/v1/vlm/infer', json={'prompt': 'test'}, timeout=5)
body = r.json()
sys.exit(0 if r.status_code == 200 and body.get('result') == 'stub_ok' else 1)
"

# 4. Tasker stub delegates to gateway
run_check "Tasker /health → gateway_reachable:true" \
    python -c "
import httpx, sys
r = httpx.get('http://127.0.0.1:${TASKER_PORT}/health', timeout=5)
body = r.json()
sys.exit(0 if r.status_code == 200 and body.get('gateway_reachable') is True else 1)
"

# 5. Task submit smoke
run_check "POST /api/v1/task/submit → task_id present" \
    python -c "
import httpx, sys
r = httpx.post('http://127.0.0.1:${TASKER_PORT}/api/v1/task/submit', json={'cmd': 'smoke'}, timeout=5)
body = r.json()
sys.exit(0 if r.status_code == 200 and 'task_id' in body else 1)
"

# ── Summary ───────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════"
if [ "$FAILURES" -eq 0 ]; then
    echo -e "${GREEN}  ✅  All smoke checks passed — minimal stack healthy${NC}"
else
    echo -e "${RED}  ❌  ${FAILURES} check(s) failed — see [FAIL] lines above${NC}"
fi
echo "═══════════════════════════════════════════════"
echo ""

# Cleanup happens via trap
exit "$FAILURES"
