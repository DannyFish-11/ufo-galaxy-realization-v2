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

This is a hard architectural constraint, not a layout preference.  **Any
rendering that places OneAPI at the same visual level as direct/native-multimodal
providers is architecturally incorrect.**

### PR-4 enforcement

PR-4 further hardens this constraint with the following rules:

1. **OneAPI is always in the lower aggregator horizon row** and only there.
   It must never appear in the top-layer direct/native provider list or in
   route-plan primary/support fields, regardless of routing weight or
   configuration state.
2. **The `oneapi_integration` block** (added to `DesktopStatusProjection` in
   PR-4) is **always present** in the projection — even when OneAPI is not
   configured.  The block shows `configured=False` and `health="skipped"` in
   that case.
3. **The `oneapi_source` field in `ModelRoutingProjection`** is populated
   *only* when the selected route actually routes *through* OneAPI
   (`vendor_source == "oneapi"`).  It is `None` otherwise.
4. **Absence of OneAPI data** must not cause fallback to top-layer rendering.
   The horizon row shows the unconfigured state instead.
5. OneAPI is never mixed into the main direct-provider layer.
6. A horizontal rule separates the main-route and support layers from the
   OneAPI Aggregator Horizon.
7. The OneAPI Aggregator Horizon shows: base URL hint, health/configured
   status, model count if known, gateway identity if available.
8. When OneAPI is not configured, the Horizon row still appears but shows
   `not configured`.
9. The horizontal separator and the `ONEAPI AGGREGATOR HORIZON` label are
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

---

## 11. PR-6 Topology-Ready Projection Contract

PR-6 completes the canonical desktop topology projection delivery.  The
`DesktopTopologyProjection` block (available as `DesktopStatusProjection.topology_ready`)
is the **single canonical integration point** for desktop topology surfaces from
PR-6 onwards.

### What desktop topology surfaces should consume

```python
from contracts.desktop_status_projection import build_desktop_status_projection

proj = build_desktop_status_projection(unified_control_plan=ucp_dict)
topo = proj.topology_ready  # DesktopTopologyProjection

# Topology semantics
primary_model  = topo.primary_model_id
primary_vendor = topo.primary_vendor_source
support_models = topo.support_model_ids
route_reason   = topo.route_reason
route_phase    = topo.route_phase
route_domain   = topo.route_domain

# Authority check
is_canonical   = topo.canonical_source_present
is_degraded    = topo.legacy_fallback_active

# OneAPI (always separate, lower-horizon only)
oneapi_block   = topo.oneapi_integration
```

Or via the dedicated API endpoint:

```
GET /api/v1/projection/desktop-topology
```

### Why this replaces dashboard-era assembly

Before PR-6, a desktop topology surface had to reconstruct routing truth from a
combination of: raw UCP `chosen_model`/`chosen_provider` keys, dashboard-era
summaries, or ad-hoc multi-field inspection.  The `topology_ready` block
replaces all of this with a single, canonically assembled, renderer-agnostic
structure.

**When `topology_ready` is present, dashboard-era truth assembly is no longer
necessary and must not be used.**

### OneAPI as lower-horizon integration block

`topo.oneapi_integration` is always present and is a **lower-horizon-only**
block.  It must never be promoted to a top-layer provider peer in the topology
display.  See [`docs/ONEAPI_SYSTEM_POSITION.md`](ONEAPI_SYSTEM_POSITION.md).

---

## 12. PR-7 Readiness / Quality Semantics

PR-7 hardens the consumer contract for `DesktopTopologyProjection` by attaching
a structured `projection_quality` block (`TopologyProjectionQualityBlock`) to
every topology-ready projection.

### Consumer-facing readiness states

| `readiness` | `authoritative` | Meaning |
|-------------|-----------------|---------|
| `canonical` | `true` | Fully canonical — sourced from canonical `TopologyRoutePlan`. Treat as full routing truth. |
| `degraded` | `false` | Legacy fallback — sourced from UCP legacy keys. Must **not** treat as full routing truth. |
| `partial` | `false` | Canonical source but key components missing/unavailable. Topology present but not healthy. |
| `unavailable` | `false` | No routing data. Do not render constellation topology from this block. |

### Consuming `projection_quality`

```python
topo = proj.topology_ready  # DesktopTopologyProjection (PR-6)
pq   = topo.projection_quality  # TopologyProjectionQualityBlock (PR-7)

if pq is None or not pq.authoritative:
    # Do not treat topology data as ground truth.
    # Surface pq.readiness and pq.quality_note to the operator.
    show_degraded_indicator(pq.readiness, pq.quality_note)
else:
    # readiness == "canonical" — safe to render full constellation topology
    render_topology(topo)
```

### Separation of concerns

- `projection_quality` describes the **authority and trustworthiness** of the
  topology routing data within `DesktopTopologyProjection`.
- `oneapi_integration` (within `DesktopTopologyProjection`) remains a
  **lower-horizon** integration block — never promoted to top-layer peer.
- The quality block does **not** affect the OneAPI lower-horizon block.  One
  may be canonical while the other is in any state.

---

## PR-8: Final Integration Contract for Desktop Status Board Consumption

PR-8 completes the right-side status board contract by providing a single integration
endpoint that composes topology projection, model routing, provider health, and OneAPI
horizon into one stable payload.

### Preferred consumption pattern (post-PR-8)

Desktop status board clients should use the PR-8 integration payload rather than
combining the topology and routing endpoints separately:

```python
# Preferred (PR-8): single integration payload
payload = GET /api/v1/projection/desktop-status-board

topo_proj   = payload["topology_projection"]  # DesktopTopologyProjection (PR-6/7)
pq          = topo_proj["projection_quality"]  # quality/readiness semantics (PR-7)
routing     = payload["model_routing_summary"]  # compact routing summary
oneapi      = payload["oneapi_integration"]  # lower-horizon only (PR-4)
authority   = payload["authority_indicators"]  # machine-checkable authority block

# Check authority before rendering
if not authority["topology_authoritative"]:
    show_degraded_indicator(pq["readiness"], pq["quality_note"])
else:
    render_topology(topo_proj)
```

### Authority indicators block

The `authority_indicators` block in `DesktopStatusBoardIntegrationPayload` aggregates
all canonical-vs-legacy signals in one place:

| Key | Type | Description |
|-----|------|-------------|
| `topology_canonical_source_present` | `bool` | Topology sourced from canonical `TopologyRoutePlan` |
| `topology_legacy_fallback_active` | `bool` | Topology assembled from legacy keys (degraded) |
| `topology_readiness` | `str` | One of: `canonical`, `degraded`, `partial`, `unavailable` |
| `topology_authoritative` | `bool` | `true` only when `topology_readiness == "canonical"` |
| `model_routing_authority_source` | `str` | `"topology_router"`, `"legacy_ucp_keys"`, or `"none"` |
| `model_routing_legacy_fallback_active` | `bool` | PR-5 legacy routing fallback flag |
| `oneapi_is_lower_horizon_only` | `bool` | Always `true` — OneAPI must never be a top-layer peer |
| `integration_contract_authority` | `str` | PR-8 sentinel |
| `topology_delivery_contract_authority` | `str` | PR-6 sentinel |
| `topology_readiness_contract_authority` | `str` | PR-7 sentinel |

### Canonical authority layering (unchanged by PR-8)

- `TopologyRoutePlan` remains the sole authoritative routing contract.
- Legacy fields remain secondary/fallback-only.
- OneAPI remains lower-horizon only.
- PR-8 composes these structures without changing their authority.
