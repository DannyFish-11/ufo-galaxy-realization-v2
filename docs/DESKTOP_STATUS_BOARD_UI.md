# Desktop Status Board UI — PR-10 First Usable Surface

> **PR-10 | First usable desktop status board UI after PR-9 merge**
>
> This document describes the first usable adapter-driven desktop status board
> UI surface introduced in PR-10.  It builds directly on the PR-9
> `DesktopClientViewModel` / `adapt_integration_payload` adapter layer.

---

## Overview

PR-10 introduces `AdapterSurface` — the first usable, operator-visible desktop
status board UI surface that is driven entirely by the PR-9 adapter layer.

Before PR-10, the repository had:

| PR | What was introduced |
|----|---------------------|
| PR-4 | OneAPI lower-horizon separation |
| PR-5 | Legacy routing demotion and canonicalization status signalling |
| PR-6 | Renderer-agnostic `DesktopTopologyProjection` + endpoint |
| PR-7 | Structured `projection_quality` readiness semantics |
| PR-8 | Final desktop status board integration payload + runtime/compiler bridge |
| PR-9 | Desktop client consumption adapter + flat `DesktopClientViewModel` |

PR-10 adds the **first usable UI layer** on top of that stable adapter
surface, without attempting full topology/constellation visual polish.

---

## Location

```
windows_client/status_board_v2/adapter_surface.py   ← new in PR-10
```

`AdapterSurface` is exported from the package `__init__.py`:

```python
from windows_client.status_board_v2 import AdapterSurface
```

---

## What the Surface Renders

`AdapterSurface` consumes a `DesktopClientViewModel` and renders a
multi-line text surface exposing:

| Section | Fields |
|---------|--------|
| **Readiness state** | `readiness_state` (canonical / degraded / partial / unavailable / unknown) with symbol and description |
| **Legacy fallback warning** | `topology_legacy_fallback_active`, `routing_legacy_fallback_active` — shown as a ⚠ banner |
| **Integration health** | `integration_health` (ok / degraded / advisory / critical / unknown) |
| **Topology / Provider** | `topology_provider_id`, `topology_primary_model_id`, `topology_route_reason`, `routing_authority_source` |
| **Provider / Routing Summary** | `provider_routing.selected_provider`, `.primary_model_id`, `.vendor_source`, `.provider_available`, `.legacy_routing_fallback_active` |
| **OneAPI lower-horizon** | `oneapi_horizon.system_layer`, `.provider_id`, `.available`, always labelled as lower-horizon |
| **Footer** | `adapter_authority`, `view_model_id` |

---

## State Rendering

### Canonical

```
  ●  CANONICAL — fully authoritative topology
  │  Health   :  ok
  │  ┌─ Topology / Provider ─────────────────────────┐
  │  │  Provider :  openai
  │  │  Model    :  gpt-4o
  │  │  Reason   :  canonical test route
```

### Degraded

```
  ◑  DEGRADED  — legacy fallback active (not authoritative)
  │  ⚠  LEGACY FALLBACK ACTIVE: topology-legacy, routing-legacy
  │  Health   :  degraded
```

### Partial

```
  ◔  PARTIAL   — canonical source present, some components missing
  │  Health   :  advisory
```

### Unavailable

```
  ○  UNAVAILABLE — no topology data available
```

### Loading / None

When `render_view_model(None)` is called, a safe fallback frame is rendered:

```
  ○  UNAVAILABLE — no view-model available
  │  (no DesktopClientViewModel available)
```

---

## OneAPI Lower-Horizon Semantics

The OneAPI block is always rendered in a **separate lower section** separated by
a horizontal rule.  It is never placed alongside canonical routing peers.

Every render includes:

```
  │  ONEAPI LOWER-HORIZON  (integration layer — not a canonical routing peer)
  │    Layer    :  aggregator_integration
  │    Status   :  available
  │    Horizon  :  lower-horizon only  [is_lower_horizon_only=True]
```

`is_lower_horizon_only` is always `True` — the surface enforces this explicitly.

---

## Usage

### From a live integrated payload

```python
from contracts.desktop_status_projection import (
    build_desktop_status_board_integration_payload,
)
from core.desktop_consumption_adapter import adapt_integration_payload
from windows_client.status_board_v2.adapter_surface import AdapterSurface

# Build the PR-8 payload and adapt it through the PR-9 adapter
payload = build_desktop_status_board_integration_payload(
    unified_control_plan=ucp,
    tristate="manifest",
)
vm = adapt_integration_payload(payload)

# Render the PR-10 UI surface
surface = AdapterSurface()
print(surface.render_view_model(vm))
```

### From a serialised view-model dict

```python
surface = AdapterSurface()
print(surface.render_dict(vm.to_dict()))
```

### Safe unavailable frame

```python
surface = AdapterSurface()
print(surface.render_view_model(None))  # always safe, never raises
```

---

## API Reference

### `AdapterSurface`

```python
class AdapterSurface:
    def render_view_model(self, vm: DesktopClientViewModel | None) -> str: ...
    def render_dict(self, vm_dict: dict) -> str: ...
```

Both methods are **read-only** and never raise.

---

## Design Constraints

- **Adapter-driven** — the surface only reads from `DesktopClientViewModel`;
  it never reconstructs truth from raw nested authority dicts or scattered
  endpoint responses.
- **OneAPI stays lower-horizon** — `is_lower_horizon_only` is always
  displayed as `True`; the OneAPI block is always in the lower section.
- **Read-only guarantee** — `AdapterSurface` has no `send_command`,
  `dispatch`, `execute`, or `trigger_action` methods.
- **Graceful degradation** — `render_view_model(None)` and
  `render_dict({})` both return safe frames without raising.

---

## Tests

Tests are in `tests/test_pr10_desktop_status_board_ui.py` (70 tests).

They verify:
- Canonical state renders as normal/healthy.
- Degraded state visibly indicates fallback/degraded authority.
- Partial and unavailable states are visibly distinct.
- OneAPI lower-horizon summary remains visually/semantically distinct.
- The UI is adapter-driven (not raw-payload-driven).

---

## Hierarchy

```
PR-9: DesktopClientViewModel  ←  adapt_integration_payload(payload)
               │
               ▼
PR-10: AdapterSurface.render_view_model(vm)
               │
               ▼
       Multi-line text status board (canonical / degraded / partial / unavailable)
```

---

## Relationship to Status Board V2

`AdapterSurface` is a new standalone surface in the `status_board_v2` package.
It renders a dedicated "Desktop Status Board" frame that is fully adapter-driven,
as distinct from the existing `TopologySurface` (which renders a `RuntimeProjection`
dict).  Full integration of `AdapterSurface` into the main polling loop is
deferred to a later PR.

---

## What PR-10 Does NOT Attempt

- Full topology / constellation visual polish (PR-11+)
- Interactive diagnostics or node click/hover (PR-13+)
- Observability history / timeline (PR-14+)

---

## See Also

- [`docs/DESKTOP_CONSUMPTION_ADAPTER.md`](DESKTOP_CONSUMPTION_ADAPTER.md) — PR-9 adapter guide
- [`docs/STATUS_BOARD_V2.md`](STATUS_BOARD_V2.md) — Status Board V2 design guide
- [`windows_client/status_board_v2/adapter_surface.py`](../windows_client/status_board_v2/adapter_surface.py) — implementation
- [`tests/test_pr10_desktop_status_board_ui.py`](../tests/test_pr10_desktop_status_board_ui.py) — test suite
