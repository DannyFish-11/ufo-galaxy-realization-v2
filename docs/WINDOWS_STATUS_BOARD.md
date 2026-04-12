# Windows Desktop Status Board

> Canonical desktop status surface: `windows_client/status_board_v2/`  
> Launch command: `python -m windows_client.status_board_v2`

---

## Purpose

The Windows desktop status board is a **read-only** runtime projection panel.
It shows the operator what the system is doing now; it is **not** a chat input
surface and does not own execution authority.

Primary fields:

1. `tri_state_phase` — `silent` / `liminal` / `manifest`
2. `runtime_domain` — `local` / `cross_device` / `transition`

---

## Wake-up / Launch (clone → run)

1. Start Galaxy backend (canonical startup):

```bash
python main.py --host 127.0.0.1 --port 8299
```

2. In another terminal, wake the desktop status board:

```bash
python -m windows_client.status_board_v2 --host 127.0.0.1 --port 8299
```

The board then polls every interval and renders runtime projection snapshots.

---

## Data source

Status Board V2 polls the canonical projection endpoint:

```text
GET http://<host>:<port>/api/v1/projection/runtime
```

If the endpoint is unreachable, the board shows `OFFLINE` and keeps retrying.

---

## Tri-state mapping

| `tri_state_phase` | Meaning |
|---|---|
| `silent` | sensing / idle shell posture |
| `liminal` | intent formation / transition posture |
| `manifest` | active execution posture |

The lifecycle authority remains `DesktopPresenceRuntime` (`silent → liminal → manifest → silent`).

---

## Interaction boundary (truthful)

- ✅ Status board: projection display / operator observability
- ✅ Status board (bounded): optional config toggles (`--apply-toggle`, `--apply-routing-policy`) written through canonical config service
- ❌ Status board: chat input, command dispatch, execution control

Canonical user interaction path is API/adapter ingress (for example `POST /api/v1/chat`)
which then enters:

`DesktopPresenceRuntime.handle_request(...) → OpenClawd`

---

## Legacy status board note

`windows_client/status_board.py` is a retired legacy module and intentionally
raises at runtime. Do not use it for new runs.

---

## Related documents

- `docs/STATUS_BOARD_V2.md`
- `docs/DESKTOP_SEMANTIC_CLOSURE.md`
- `docs/architecture/CANONICAL_ENTRYPOINTS.md`
