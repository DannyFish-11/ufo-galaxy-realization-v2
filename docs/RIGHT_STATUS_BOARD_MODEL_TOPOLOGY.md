# Right-Side Desktop Status Board — Model Topology Semantics

> **Canonical reference** for how the right-side desktop status board structures
> and displays model routing/topology information.  Extended in PR-1 to include
> the Sky-Grown Constellation Topology visual identity.
>
> Related: [`docs/STATUS_BOARD_V2.md`](STATUS_BOARD_V2.md) ·
> [`docs/SKY_GROWN_CONSTELLATION_TOPOLOGY.md`](SKY_GROWN_CONSTELLATION_TOPOLOGY.md) ·
> [`docs/DESKTOP_DISPLAY_BOUNDARIES.md`](DESKTOP_DISPLAY_BOUNDARIES.md) ·
> [`docs/MODEL_ROUTING_AUTHORITY.md`](MODEL_ROUTING_AUTHORITY.md) ·
> [`docs/ONEAPI_SYSTEM_POSITION.md`](ONEAPI_SYSTEM_POSITION.md) ·
> [`docs/DASHBOARD_RETIREMENT_AND_MIGRATION.md`](DASHBOARD_RETIREMENT_AND_MIGRATION.md)

---

## 1. Why the Right-Side Status Board Is the Canonical Model-Display Layer

The right-side desktop status board (`windows_client/status_board_v2/`) is the
**sole canonical structured-information display surface** for the Galaxy system.
It is the authoritative view of:

- which model is currently active and why;
- how models are structured (primary, support/auxiliary, source/vendor);
- the health and availability of the provider layer;
- the OneAPI aggregator integration status.

This surface is **projection-driven and read-only** — it consumes the canonical
`RuntimeProjection` from `GET /api/v1/projection/runtime` and renders it as
structured text.  It does not maintain its own state, does not issue commands,
and does not participate in routing decisions.

The liminal space (`liminal_surface.py`) is deliberately **excluded** from model
topology display.  All model/routing/topology cards belong here, not in liminal.

**The dashboard is not this surface and is not a routing-truth authority.**
The dashboard is in retirement per
[`docs/DASHBOARD_RETIREMENT_AND_MIGRATION.md`](DASHBOARD_RETIREMENT_AND_MIGRATION.md).
Any operator-visible model topology work must target `status_board_v2`, not the
dashboard.

---

## 2. Why Model Display Is a Topology, Not a Flat Provider List

A flat provider list ("OpenAI · Anthropic · Gemini · …") treats all providers
as equal peers.  This misrepresents the actual routing structure:

- Some models are the **primary route** for the active request — they are at the
  top of the decision hierarchy.
- Some models are **support/auxiliary** — they assist the primary without
  replacing it.
- Vendors/sources are **real distinctions** that affect capability, latency, and
  cost.
- **OneAPI** is an aggregator that sits at a different architectural level than
  direct vendor APIs.

A topology representation captures these relationships faithfully.

This topology is specifically defined as a **Native-Multimodal-First
Sky-Grown Constellation Topology** (星空一体化生长式星座拓扑树).  The visual
identity of this topology is defined in full in
[`docs/SKY_GROWN_CONSTELLATION_TOPOLOGY.md`](SKY_GROWN_CONSTELLATION_TOPOLOGY.md).

### What the topology is NOT

| ❌ Not this | Why it is incorrect |
|---|---|
| **Flat provider cards** | Cards treat all providers as equal peers; the topology expresses hierarchy |
| **Dashboard-style card grid** | Dashboard is in retirement; dashboard UI grammar must not be carried forward |
| **True 3-D visualization** | True 3-D is not terminal-friendly and adds complexity without semantic gain |
| **A generic tree with labelled boxes** | Generic trees do not capture weight, depth-illusion, or growth semantics |
| **A static layout** | Layout must reflect live `TopologyRoutePlan` output |

```
┌─ Model Topology — Native-Multimodal First ─────────────────────────┐
│                                                                     │
│  MAIN ROUTE (direct / native-multimodal)                            │
│  ★ gpt-4o  [MM]  [OpenAI]  weight ████████░░ 0.900  ← PRIMARY      │
│                                                                     │
│  SUPPORT                                                            │
│    claude-3-5-sonnet  [Anthropic]  weight █████░░░░░ 0.600          │
│    local-vlm          [local]      weight ███░░░░░░░ 0.400          │
│                                                                     │
│  Reason: Native multimodal preferred in liminal phase               │
│                                                                     │
│  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─  │
│                                                                     │
│  ONEAPI AGGREGATOR HORIZON                                          │
│    base_url: http://oneapi.local:3000   status: configured          │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. The Main/Top Layer — Direct Native-Multimodal Model Paths

The **main route layer** is always displayed first and most prominently.

Rules:
- The primary model is the **top entry** in the topology display, marked with ★.
- If the primary route is a native-multimodal API path, it carries the `[MM]`
  label to make this unambiguous.
- Native-multimodal paths are the **preferred/primary axis** of the routing
  hierarchy; text-only paths are support unless no native-multimodal model is
  available.
- The routing authority source (`routing_authority`) is shown so that operators
  can confirm whether the topology is sourced from the canonical
  `TopologyRouter`.

---

## 4. The Support / Auxiliary Model Layer

The **support layer** contains models that assist or back up the primary route:

- Listed after the primary model, under a clear visual separator.
- Weights are shown as bar charts so relative routing preference is visible.
- Roles expressed in this layer include: specialist, fallback, and auxiliary.

Support models are **not** promoted to the primary layer even if their weight is
close.  The topology structure is determined by the `TopologyRouter` and
reflected as-is.

---

## 5. The Vendor/Source Visibility Principle

Each model in the topology **must remain identifiable by vendor/source**.

- Direct API providers (OpenAI, Anthropic, Google, xAI, Mistral, …) are
  labelled by name.
- Local/embedded models are labelled as `[local]`.
- The `vendor_source` field in the projection dict is the canonical source for
  this label; when absent the surface falls back to inferring from model ID
  prefixes.

**Rationale**: flattening away vendor identity hides capability differences,
makes debugging routing decisions harder, and obscures cost/latency tradeoffs.

---

## 6. The Lower OneAPI Aggregator Horizon

OneAPI is a **system-level aggregator integration layer** that sits
architecturally below the direct-vendor tier.  It is therefore rendered as a
**separate, clearly labelled lower row — the OneAPI Aggregator Horizon** — in
the topology display.

This is a hard architectural constraint, not a layout preference.  Any rendering
that places OneAPI at the same visual level as direct/native-multimodal providers
is **architecturally incorrect**.

Rules enforced by the topology surface:

1. OneAPI is never mixed into the main direct-provider layer.
2. When `oneapi_source` data is present in the projection, a horizontal rule
   separates the main-route and support layers from the OneAPI Aggregator Horizon.
3. The OneAPI Aggregator Horizon shows: base URL, health/configured status, and
   model count if known.
4. When OneAPI is not configured, the Horizon row still appears but shows
   `not configured`.
5. The horizontal separator and the `ONEAPI AGGREGATOR HORIZON` label are
   mandatory; they must not be removed.

This mirrors the principle in [`docs/ONEAPI_SYSTEM_POSITION.md`](ONEAPI_SYSTEM_POSITION.md)
and is defined in detail in
[`docs/SKY_GROWN_CONSTELLATION_TOPOLOGY.md`](SKY_GROWN_CONSTELLATION_TOPOLOGY.md) §3 Layer 5.

---

## 7. Route Truth → Topology Display Relationship

The topology display is a **read-only projection** of the canonical routing
truth maintained by `core/model_topology/topology_router.py` (the
`TopologyRouter`).

```
TopologyRouter
    ↓  TopologyRoutePlan
build_runtime_projection()
    ↓  RuntimeProjection (primary_model_id, support_model_ids, active_weights,
    │                     route_reason, routing_authority, is_native_multimodal,
    │                     vendor_source, oneapi_source)
    ↓  GET /api/v1/projection/runtime
TopologySurface.render()
    ↓  structured text output (right-side status board)
```

Key invariants:

- The topology surface **never** derives its own routing conclusions — it only
  renders what the projection tells it.
- If `routing_authority` is `"none"`, the surface signals that no canonical
  route plan is available.
- If `is_native_multimodal` is `True`, the primary model receives the `[MM]`
  label; if it is absent/`False`, no label is shown.
- If `oneapi_source` is absent from the projection, the OneAPI row is omitted;
  if it is present (even as `{}`), the row is shown with whatever data is
  available.

---

## 8. Display Fields Reference

| Projection field | Layer | Purpose |
|---|---|---|
| `primary_model_id` | Main Route | ID of the top-ranked routing node |
| `is_native_multimodal` | Main Route | Whether the primary is a native-MM path |
| `vendor_source` | Main Route / Support | Vendor/provider label for a model |
| `support_model_ids` | Support | IDs of supporting/auxiliary models |
| `active_weights` | Both | Per-model combined weights (bar chart) |
| `route_reason` | Both | Human-readable routing rationale |
| `routing_authority` | Both | Which authority populated the routing fields |
| `topology_role` | Both | Role hint per model (primary/support/specialist) |
| `oneapi_source` | OneAPI row | Aggregator metadata (url, status, model count) |

---

## 9. Sky-Grown Constellation Topology Visual Identity

The topology defined in this document has a target visual identity established
in [`docs/SKY_GROWN_CONSTELLATION_TOPOLOGY.md`](SKY_GROWN_CONSTELLATION_TOPOLOGY.md):

**Native-Multimodal-First Sky-Grown Constellation Topology**
(星空一体化生长式星座拓扑树).

This is a **depth-illusion / 2.5-D semantic structure** — not true 3-D, not a
flat card grid, but a projection-driven constellation-style layout where spatial
relationships between nodes (position, brightness, separator depth) express
routing relationships.  Layout is determined by live `TopologyRoutePlan` data,
not by a static template.

Key commitments of this visual identity:

- Primary model = main star (★) at top, maximum brightness.
- Support models = support orbit (✧) below, weight-scaled brightness.
- Inactive available providers = background supply field, minimal visual weight.
- Route annotations = label lines, not large panels.
- OneAPI = Aggregator Horizon below a mandatory separator, always a lower layer.

This visual identity is the **target for all future topology surface work**.
Any implementation that regresses to flat provider cards, true 3-D geometry, or
dashboard-style card grids is architecturally incorrect.

---

## 10. Non-Goals for This Document / Surface

- This document does **not** specify the liminal space — see
  [`docs/DESKTOP_DISPLAY_BOUNDARIES.md`](DESKTOP_DISPLAY_BOUNDARIES.md).
- This document does **not** redesign the `TopologyRouter` or routing policy.
- This document does **not** describe a graphical/3-D UI; the surface remains
  textual/CLI, but the topology structure must be visible from the text.
- OneAPI global config plumbing beyond projection/status semantics is out of
  scope here — see [`docs/ONEAPI_SYSTEM_POSITION.md`](ONEAPI_SYSTEM_POSITION.md).
- This document does **not** define the dashboard as a topology surface; the
  dashboard is in retirement and is not a valid target for new topology work.
