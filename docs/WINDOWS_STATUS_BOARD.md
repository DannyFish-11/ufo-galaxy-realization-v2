# Windows Desktop Status Board

> The Windows desktop UI is a **tri-state status mapping panel**.
> It is NOT a chat input surface.

---

## Purpose

The Windows desktop status board provides a lightweight, read-only view of the
current OpenClawd tri-state phase and device execution state.  It maps the
public `TriStatePhase` to a visible indicator so operators can observe the
system at a glance without interacting with it directly.

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

## What the Status Board Is NOT

- It is **not** a chat window or conversational input surface.
- It does **not** send commands to OpenClawd directly.
- It does **not** replace or duplicate the AIP ingress pipeline.

All input to OpenClawd goes through the AIP ingress pipeline:
`windows_aip_client.py → WindowsExecutionArbiter`.

---

## Implementation Note

The status board reads `ContinuumState.tri_state_phase` from the server's
state stream (WebSocket event stream or REST polling) and renders the
appropriate indicator.  It requires no write access to the continuum engine.

```python
# Example: reading tri_state_phase from a ContinuumState dict
from core.continuum import TriStatePhase

phase_str = continuum_state_dict.get("tri_state_phase", "silent")
phase = TriStatePhase(phase_str)
```

---

## Related Documents

- [WINDOWS_EXECUTION_PIPELINE.md](windows_mcp_server.md) — active execution architecture
- [OPENCLAWD_STATE_CONTINUUM.md](OPENCLAWD_STATE_CONTINUUM.md) — full protocol overview
- [PHASE_TRANSITION_TABLE.md](PHASE_TRANSITION_TABLE.md) — internal transition rules
