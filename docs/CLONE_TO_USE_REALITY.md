# Clone-to-Use Runtime Reality (Authoritative Quick Truth)

This document is the shortest truthful answer to:

- what can be run from a fresh clone
- how to start it
- how to interact with it
- what the desktop status board does today
- what cross-device/multi-device means in current runtime terms

---

## Readiness verdict (important)

Before presenting the desktop board as an operator product surface, read:
`docs/DESKTOP_STATUS_BOARD_READINESS_AUDIT.md`.

Current verdict: the board is a **partial operator surface** (read-mostly
observability with bounded config controls), **not yet** a fully presentable
desktop control plane.

---

## 1) Fresh clone → first run

```bash
git clone https://github.com/DannyFish-11/ufo-galaxy-realization-v2.git
cd ufo-galaxy-realization-v2
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Optional (dev lint/test tooling):

```bash
pip install -r requirements-dev.txt
```

---

## 2) Canonical backend startup path

Primary startup command:

```bash
python main.py --host 127.0.0.1 --port 8299
```

`main.py` is the top-level orchestrator and delegates to `unified_launcher.py`.

---

## 3) Canonical interaction surfaces

After startup, use these surfaces first:

- **Chat/API ingress**: `POST /api/v1/chat`
- **Runtime projection**: `GET /api/v1/projection/runtime`
- **Runtime truth snapshot**: `GET /api/v1/projection/runtime-truth`
- **Status WebSocket (optional observability)**: `GET /ws/status`

Minimal local interaction check:

```bash
curl -sS -X POST "http://127.0.0.1:8299/api/v1/chat" \
  -H "Content-Type: application/json" \
  -d '{"message":"你好","device_id":"local_cli"}'
```

---

## 4) Desktop status board reality

Wake command:

```bash
python -m windows_client.status_board_v2 --host 127.0.0.1 --port 8299
```

Truthful boundary:

- It is primarily **read-only** (projection display / observability).
- It does **not** accept chat input and does **not** dispatch commands.
- It includes **bounded optional config controls** (`--apply-toggle`,
  `--apply-routing-policy`) but this does not make it a full operator control plane.
- Tri-state displayed is `silent / liminal / manifest`, owned by `DesktopPresenceRuntime`.

---

## 5) Cross-device / multi-device reality

Current codebase contains active cross-device runtime layers and projections
(gateway, dispatch orchestration, multi-device projection surfaces).  
However, a fully production-like multi-device setup requires additional
environmental participants (real devices, gateway connectivity, network setup,
and matching runtime configs).

Practical expectation from fresh local clone:

- ✅ You can run single-host backend + status/projection/API surfaces.
- ⚠️ You may run bounded/simulated cross-device workflows locally.
- ⚠️ Full multi-device operation is environment-dependent and not guaranteed by clone alone.

---

## 6) Packaging / deployment truth

Source-run is a supported mode (`python main.py`).

Deployment/packaging options also exist (Docker/Compose and Windows packaging
helpers), but they are optional for first local use:

- development compose: `docker-compose.yml`
- production/full compose: `deploy/compose/*.yml`
- desktop packaging helper: `build_exe.py`

---

## 7) Validation path (recommended)

Use these in order:

```bash
# Structural/runtime consistency checks (no full external infra needed)
python scripts/validate_runtime.py

# Minimal stack smoke path (gateway + stubs)
bash scripts/quick_verify.sh
```

If both pass, you have a confirmed local baseline for supported clone-to-use flow.
