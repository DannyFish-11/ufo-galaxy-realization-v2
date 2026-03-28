# Topology Rendering and Visual Semantics (PR-12)

This document describes the topology constellation renderer introduced in PR-12,
which builds on the PR-11 topology/constellation layout foundation to produce a
polished, readable ASCII/ANSI rendering surface with clear visual semantics.

---

## Overview

PR-12 adds a **topology renderer layer** on top of the PR-11 layout model.
Rather than exposing raw data structures, the renderer transforms a
`TopologyConstellationLayout` (produced by `build_constellation_layout`) into a
visually expressive terminal output surface where:

- readiness states (`canonical`, `degraded`, `partial`, `unavailable`) are
  unambiguously distinct at a glance;
- each node kind has a unique symbol: ★ primary, ✧ routing-peer, ◇ support,
  ⬡ OneAPI;
- each relation kind has a unique edge symbol: `━━▶` canonical route, `╌╌▷`
  fallback path, `──▷` support path, `╌╌⬡` lower-horizon link;
- OneAPI is always in a structurally isolated **LOWER-HORIZON** section, never
  elevated to look like a canonical routing peer;
- degraded/fallback nodes carry explicit **[NOT-auth]** tags so they can never
  be mistaken for canonical authority.

The renderer consumes a `TopologyConstellationLayout` (or its `to_dict()`
serialisation) and never bypasses the PR-11 layout model to access the
underlying view-model or raw integration payload directly.

---

## Visual Structure

```
  ╔═ Topology Constellation ══════════════════════════╗
  ║  ●  CANONICAL   — fully authoritative topology
  ╠═ PRIMARY ══════════════════════════════════════════╣
  ║  ★  primary (openai) openai  ●  [auth]
  ╠═ SUPPORT ══════════════════════════════════════════╣
  ║  ✧  routing peer (openai) openai  ●  [auth]
  ╟─ RELATIONS ────────────────────────────────────────╢
  ║  primary_provi…  ━━▶  routing_peer…  canonical route  ✓
  ║  primary_provi…  ╌╌⬡  oneapi_horiz…  lower-horizon in…  ✗
  ╟─ LOWER-HORIZON  ·  OneAPI  ·  not a routing peer ──╢
  ║  ⬡  OneAPI oneapi-provider [lower-horizon]  ⬡  [lower-horizon]
  ╚═══════════════════════════════════════════════════╝
  ║  Layout authority : windows_client.status_board_v2.topology_layout…
  ║  Layout ID        : <uuid>
  ║  Renderer         : windows_client.status_board_v2.topology_renderer…
```

---

## Readiness Visual Key

| Symbol | Label       | Colour  | Meaning                                          |
|--------|-------------|---------|--------------------------------------------------|
| `●`    | canonical   | green   | Fully authoritative topology                     |
| `◑`    | degraded    | yellow  | Legacy fallback active — **NOT authoritative**   |
| `◔`    | partial     | cyan    | Canonical source present; some components missing|
| `○`    | unavailable | red     | No topology data available                       |

Degraded and partial nodes are tagged `[NOT-auth]` or `[not-auth]` to make it
visually impossible to mistake them for canonical authority.

---

## Node-Kind Symbols

| Symbol | Kind              | Colour  | Layer            |
|--------|-------------------|---------|------------------|
| `★`    | primary_provider  | green   | PRIMARY          |
| `✧`    | routing_peer      | blue    | SUPPORT          |
| `◇`    | support_node      | blue    | SUPPORT          |
| `⬡`    | oneapi_horizon    | magenta | LOWER-HORIZON    |

---

## Relation-Kind Edge Symbols

| Edge   | Kind                | Colour  | Meaning                              |
|--------|---------------------|---------|--------------------------------------|
| `━━▶`  | canonical_route     | green   | Authoritative canonical routing path |
| `╌╌▷`  | fallback_path       | yellow  | Legacy fallback (not authoritative)  |
| `──▷`  | support_path        | blue    | Support / routing-peer path          |
| `╌╌⬡`  | lower_horizon_link  | magenta | Link to OneAPI lower-horizon block   |

---

## OneAPI Lower-Horizon Guarantee

The `LOWER-HORIZON · OneAPI · not a routing peer` section is always rendered
after the `PRIMARY` and `SUPPORT` sections. OneAPI nodes:

- carry the `⬡` symbol (magenta);
- are tagged `[lower-horizon]`;
- are **never** tagged `[auth]`;
- are **never** placed in the PRIMARY or SUPPORT sections;
- the lower-horizon link edge `╌╌⬡` is always used (never `━━▶`).

This structural isolation is guaranteed regardless of the underlying readiness
state (`canonical`, `degraded`, `partial`, `unavailable`).

---

## Usage

```python
from windows_client.status_board_v2.topology_renderer import TopologyRenderer
from windows_client.status_board_v2.topology_layout import build_constellation_layout
from core.desktop_consumption_adapter import adapt_integration_payload

# Build adapter view-model (PR-9)
vm = adapt_integration_payload(payload)

# Build topology/constellation layout (PR-11)
layout = build_constellation_layout(vm)

# Render with polished visual semantics (PR-12)
renderer = TopologyRenderer()
print(renderer.render_layout(layout))
```

### From a serialised layout dict

```python
layout_dict = layout.to_dict()
# (e.g. loaded from JSON / cache)

renderer = TopologyRenderer()
print(renderer.render_layout_dict(layout_dict))
```

---

## API Reference

### `TopologyRenderer`

Main renderer class.  READ-ONLY — produces display strings only.

| Method | Signature | Description |
|--------|-----------|-------------|
| `render_layout` | `(layout: Any) -> str` | Render from a `TopologyConstellationLayout` instance or plain dict. |
| `render_layout_dict` | `(layout_dict: dict) -> str` | Render from a plain dict (e.g. `layout.to_dict()`). |

### `TOPOLOGY_RENDERER_AUTHORITY`

```
"windows_client.status_board_v2.topology_renderer.TopologyRenderer"
```

Sentinel string identifying the canonical PR-12 renderer.  Appears in every
rendered output footer for provenance tracing.

---

## Authority Chain

```
DesktopStatusBoardIntegrationPayload  (PR-8 server contract)
  └─ adapt_integration_payload()      (PR-9 adapter)
       └─ DesktopClientViewModel
            └─ build_constellation_layout()  (PR-11 layout builder)
                 └─ TopologyConstellationLayout
                      └─ TopologyRenderer.render_layout()  (PR-12 renderer)
                           └─ rendered terminal output
```

Each layer only consumes the layer immediately above it; no layer bypasses
its predecessor to access raw nested payload dicts.

---

## Design Constraints

- **Layout-driven only** — the renderer always consumes a
  `TopologyConstellationLayout` (or its `to_dict()` equivalent); it never
  bypasses the PR-11 layout model.
- **Visually distinct readiness** — `canonical`, `degraded`, `partial`, and
  `unavailable` are rendered with distinct symbols, colours, and labels.
- **No false authority** — degraded/fallback nodes carry explicit `[NOT-auth]`
  tags; canonical authority indicators never appear on non-canonical nodes.
- **OneAPI isolation** — OneAPI nodes are always in the lower-horizon section
  with the `⬡` symbol and `[lower-horizon]` tag; they are never promoted.
- **Read-only** — the renderer never sends commands or modifies system state.
- **Graceful** — all rendering paths handle `None` and minimal layouts without
  raising.

---

## Related Documents

- [`docs/TOPOLOGY_CONSTELLATION_LAYOUT.md`](TOPOLOGY_CONSTELLATION_LAYOUT.md) —
  PR-11 topology/constellation layout foundation
- [`docs/DESKTOP_STATUS_BOARD_UI.md`](DESKTOP_STATUS_BOARD_UI.md) —
  PR-10 first usable adapter-driven status board UI surface
- [`docs/DESKTOP_CONSUMPTION_ADAPTER.md`](DESKTOP_CONSUMPTION_ADAPTER.md) —
  PR-9 desktop client consumption adapter and `DesktopClientViewModel`
- [`docs/STATUS_BOARD_V2.md`](STATUS_BOARD_V2.md) — Status Board V2 overview
- [`docs/RIGHT_STATUS_BOARD_MODEL_TOPOLOGY.md`](RIGHT_STATUS_BOARD_MODEL_TOPOLOGY.md)
  — canonical model topology semantics for the right-side board
