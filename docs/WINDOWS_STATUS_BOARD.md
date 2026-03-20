# Windows Desktop Status Board

> The Windows desktop status board is a **read-only** tri-state + runtime domain
> panel.  It does NOT accept chat input or send commands.

---

## Purpose

The Windows desktop status board provides a lightweight, read-only view of the
current OpenClawd two-dimensional system posture:

1. **`tri_state_phase`** — what the system is doing (`silent` / `liminal` / `manifest`)
2. **`runtime_domain`** — where execution is happening (`local` / `cross_device` / `transition`)

Operators can observe the system at a glance without interacting with it
directly.

---

## Tri-State Mapping

| `TriStatePhase` | Visual Indicator | Meaning |
|---|---|---|
| `silent` | ○ Dim / minimal | Native multimodal ingress; system is sensing but not acting |
| `liminal` | ◑ Transitioning | Intent forming; may be routing to local or cross-device execution |
| `manifest` | ● Active | Structure formed; execution in progress |

> **`receding` is an internal mechanism and is never shown on the status board.**
> When the internal phase is `receding`, the board shows `silent` (same as `formless`).

---

## Runtime Domain Mapping

| `RuntimeDomain` | Meaning |
|---|---|
| `local` | Execution is confined to this single device / process |
| `cross_device` | Execution spans multiple devices or remote nodes |
| `transition` | Actively deciding between local and cross-device routing |
| `null` / unknown | Domain not yet determined |

---

## What the Status Board Is NOT

- It is **not** a chat window or conversational input surface.
- It does **not** send commands to OpenClawd directly.
- It does **not** replace or duplicate the AIP ingress pipeline.

All input to OpenClawd goes through the AIP ingress pipeline:
`windows_aip_client.py → WindowsExecutionArbiter`.

---

## How to Run

The status board is implemented as a self-contained CLI tool at
`windows_client/status_board.py`.

### Requirements

- Python 3.9+ (standard library only — no extra dependencies needed)
- A running Galaxy / OpenClawd server

### Launch

```bash
# Poll the default server (http://127.0.0.1:8000)
python windows_client/status_board.py

# Specify server address
python windows_client/status_board.py --host 10.0.0.5 --port 8000

# Change poll interval (seconds, default: 1.0)
python windows_client/status_board.py --interval 2.0

# Disable ANSI colour (plain terminals / log redirection)
python windows_client/status_board.py --no-color

# Full help
python windows_client/status_board.py --help
```

Press **Ctrl-C** to stop.

---

## Data Source

The board polls the Galaxy REST endpoint::

    GET http://<host>:<port>/api/v1/continuum/state

Expected response schema (relevant subset):

```json
{
  "tri_state_phase": "silent" | "liminal" | "manifest",
  "runtime_domain":  "local" | "cross_device" | "transition" | null,
  "presence_intensity": 0.0,
  "coherence": 0.0
}
```

If the endpoint is unreachable the board displays `OFFLINE` and retries at
the configured poll interval.

---

## Reading State in Code

```python
from core.continuum import TriStatePhase, RuntimeDomain

# Both dimensions from a ContinuumState object
phase  = state.tri_state_phase   # TriStatePhase.SILENT | LIMINAL | MANIFEST
domain = state.runtime_domain    # RuntimeDomain.LOCAL | CROSS_DEVICE | TRANSITION | None

# From a raw dict (e.g. from an API response)
phase_str  = continuum_state_dict.get("tri_state_phase", "silent")
domain_str = continuum_state_dict.get("runtime_domain")  # may be None

phase  = TriStatePhase(phase_str)
domain = RuntimeDomain(domain_str) if domain_str else None
```

---

## Related Documents

- [OPENCLAWD_STATE_CONTINUUM.md](OPENCLAWD_STATE_CONTINUUM.md) — full two-dimensional protocol overview
- [windows_mcp_server.md](windows_mcp_server.md) — active Windows execution architecture
- [PHASE_TRANSITION_TABLE.md](PHASE_TRANSITION_TABLE.md) — internal transition rules
