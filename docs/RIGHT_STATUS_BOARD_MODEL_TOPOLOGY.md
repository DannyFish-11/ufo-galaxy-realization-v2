# Right-Side Desktop Status Board — Model Topology Semantics

> **Canonical reference** for how the right-side desktop status board structures
> and displays model routing/topology information.
>
> Related: [`docs/STATUS_BOARD_V2.md`](STATUS_BOARD_V2.md) ·
> [`docs/DESKTOP_DISPLAY_BOUNDARIES.md`](DESKTOP_DISPLAY_BOUNDARIES.md) ·
> [`docs/MODEL_ROUTING_AUTHORITY.md`](MODEL_ROUTING_AUTHORITY.md) ·
> [`docs/ONEAPI_SYSTEM_POSITION.md`](ONEAPI_SYSTEM_POSITION.md)

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

A topology representation captures these relationships faithfully:

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
│  ONEAPI (aggregator)                                                │
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

## 6. The Lower OneAPI Aggregator Row

OneAPI is a **system-level aggregator integration layer** that sits
architecturally below the direct-vendor tier.  It is therefore rendered as a
**separate, clearly labelled lower row** in the topology display.

Rules enforced by the topology surface:

1. OneAPI is never mixed into the main direct-provider layer.
2. When `oneapi_source` data is present in the projection, a horizontal rule
   separates the main-route and support layers from the OneAPI row.
3. The OneAPI row shows: base URL, health/configured status, and model count if
   known.
4. When OneAPI is not configured, the row still appears but shows
   `not configured`.

This mirrors the principle in [`docs/ONEAPI_SYSTEM_POSITION.md`](ONEAPI_SYSTEM_POSITION.md)
§4.4 and §5.

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

## 9. Non-Goals for This Document / Surface

- This document does **not** specify the liminal space — see
  [`docs/DESKTOP_DISPLAY_BOUNDARIES.md`](DESKTOP_DISPLAY_BOUNDARIES.md).
- This document does **not** redesign the `TopologyRouter` or routing policy.
- This document does **not** describe a graphical/3-D UI; the surface remains
  textual/CLI, but the topology structure must be visible from the text.
- OneAPI global config plumbing beyond projection/status semantics is out of
  scope here — see [`docs/ONEAPI_SYSTEM_POSITION.md`](ONEAPI_SYSTEM_POSITION.md).
