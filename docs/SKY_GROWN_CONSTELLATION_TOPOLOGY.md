# Sky-Grown Constellation Topology

> **Status:** Architecture-freeze canonical — established in PR-1; governing
> principle confirmed in PR-0 (unified native-multimodal-first architecture
> freeze).
> **Scope:** Defines the target visual grammar and semantic identity of the
> desktop model-topology display surface for the Galaxy system.
>
> Related: [`docs/RIGHT_STATUS_BOARD_MODEL_TOPOLOGY.md`](RIGHT_STATUS_BOARD_MODEL_TOPOLOGY.md) ·
> [`docs/STATUS_BOARD_V2.md`](STATUS_BOARD_V2.md) ·
> [`docs/MODEL_ROUTING_AUTHORITY.md`](MODEL_ROUTING_AUTHORITY.md) ·
> [`docs/ONEAPI_SYSTEM_POSITION.md`](ONEAPI_SYSTEM_POSITION.md) ·
> [`docs/DASHBOARD_RETIREMENT_AND_MIGRATION.md`](DASHBOARD_RETIREMENT_AND_MIGRATION.md) ·
> [`docs/ADR_STATUS_BOARD_CONFIG_AUTHORITY.md`](ADR_STATUS_BOARD_CONFIG_AUTHORITY.md)

---

## 1. Name and Identity

The desktop model-topology display is defined as a
**Native-Multimodal-First Sky-Grown Constellation Topology**
(星空一体化生长式星座拓扑树).

This name encodes four non-negotiable design commitments:

| Term | Commitment |
|---|---|
| **Native-Multimodal-First** | Native multimodal model paths anchor the primary layer; text-only paths are support unless no native-multimodal model is available |
| **Sky-Grown** | The topology is not drawn onto a neutral background; it grows from the operational state of the system — shape, depth, and brightness are data, not decoration |
| **Constellation** | Spatial relationships between nodes express routing relationships — distance, brightness, and grouping are semantically meaningful |
| **Topology** | Structure is determined by `TopologyRoutePlan` from `TopologyRouter`; the display never invents its own routing conclusions |

---

## 2. What It Is and What It Is Not

### What it IS

- A **projection-driven** rendering of canonical routing truth produced by
  `TopologyRouter` → `TopologyRoutePlan` → `RuntimeProjection`.
- A **depth-illusion / 2.5-D semantic structure**: spatial depth is expressed
  through visual layer priority, brightness, label prominence, and separator
  language — not through genuine 3-D geometry.
- A **growth-form**: the shape and population of the topology change as
  routing state changes.  Nodes appear, brighten, or dim based on routing plan
  output — not on static configuration.
- A **constellation-style concrete topology**: nodes are meaningfully placed
  relative to each other, not listed alphabetically or sorted by name.
- **Terminal/text-friendly**: must render legibly in a CLI/ANSI status board
  without requiring a graphical window or GPU-accelerated widget.

### What it is NOT

| ❌ Not this | Reason |
|---|---|
| Flat provider cards (dashboard-style) | Cards treat all providers as equal peers; the topology expresses hierarchy |
| A generic tree with labelled boxes | Generic trees do not capture weight, depth-illusion, or growth semantics |
| True 3-D visualization | True 3-D is not terminal-friendly and adds implementation complexity without semantic gain |
| A static layout | Layout must reflect live `TopologyRoutePlan` output |
| A dashboard screen replacement | The topology surface is part of `status_board_v2`; it is not a web page |
| An implementation of its own routing logic | The surface is read-only projection consumer — it never derives routing truth independently |

---

## 3. Visual Layers

The topology is composed of five defined layers rendered top-to-bottom.

### Layer 1 — Primary Core / Main Star (主星核)

The **primary model** selected by `TopologyRouter` as the top-ranked route.

Visual rules:
- Marked with `★` and positioned at the top of the topology field.
- Receives `[MM]` badge when `is_native_multimodal` is `True` in the projection.
- Labelled with `vendor_source` (e.g., `[OpenAI]`, `[Anthropic]`, `[local]`).
- Shown at maximum brightness / prominence relative to other nodes.
- Weight bar displayed at full scale as the reference weight.

Semantic rules:
- There is always exactly one Primary Core node when a valid `TopologyRoutePlan`
  is available.
- The Primary Core node is **never** a OneAPI aggregator entry; it must be a
  direct/native-multimodal provider or a local model.

### Layer 2 — Support Orbits (伴星轨道)

The **support models** listed in `TopologyRoutePlan.support_models`.

Visual rules:
- Rendered below the Primary Core, under a visual sub-separator.
- Each node marked with `✧` or `·` to indicate auxiliary status.
- Weight bars scaled relative to the primary model's weight.
- Labelled with `vendor_source` and optionally with capability role
  (e.g., `reasoning`, `code`, `vision-support`).
- Nodes with lower weight appear visually dimmer (smaller bar, lighter label)
  than nodes with higher weight.

Semantic rules:
- Support models are never promoted to the Primary Core layer even if weight
  is close; the layer boundary is determined by `TopologyRoutePlan` role, not
  by weight threshold.
- Support layer may be empty when the plan has no support models.

### Layer 3 — Background Supply Field (背景星场)

The **available-but-inactive** direct providers that are configured in the
system but not selected for the current route plan.

Visual rules:
- Rendered at significantly reduced brightness compared to Layers 1 and 2.
- Listed compactly, without weight bars, to avoid visual competition with the
  active topology.
- May be omitted entirely when display space is constrained.

Semantic rules:
- These nodes are candidates that could participate in a future plan but are
  not currently part of the active `TopologyRoutePlan`.
- They must never be mixed into Layers 1 or 2.
- They are informational only; no action can be triggered from this layer.

### Layer 4 — Route Annotations (路由注解)

Cross-cutting metadata displayed alongside the topology, not as a separate
cluster.

Includes:
- `route_reason` — human-readable explanation from `TopologyRoutePlan`.
- `routing_authority` — confirms whether the plan came from `TopologyRouter`
  (canonical) or a degraded fallback source.
- `phase` / `domain` context when space permits.

Visual rules:
- Rendered as compact label lines, visually distinct from node rows.
- Authority label must be present whenever `routing_authority` is not
  `"core.model_topology.topology_router.TopologyRouter"`, and must highlight
  the degraded state.

### Layer 5 — OneAPI Aggregator Horizon (OneAPI 聚合地平线)

The **OneAPI aggregator integration layer**, rendered unconditionally below a
full-width horizontal separator that visually represents the architectural
boundary between the direct-provider constellation and the aggregator tier.

Visual rules:
- Separated from Layers 1–4 by a full-width dashed or solid rule.
- Labelled `ONEAPI AGGREGATOR HORIZON` or equivalent language that makes the
  architectural tier explicit.
- Shows: configured/unconfigured status, health indicator, model count if
  available, base URL hint.
- Rendered at lower visual weight than the active topology layers above.

Semantic rules (hard constraints):
- **OneAPI is always in this layer and only in this layer.**  It must never
  appear in Layers 1, 2, or 3, regardless of weight or routing participation.
- When OneAPI is not configured, the Horizon row still appears but shows
  `not configured`.
- When OneAPI is configured, the row reflects its health/availability from the
  projection.
- The horizontal separator is mandatory; it may not be removed even when
  OneAPI is not configured.

---

## 4. Native-Multimodal-First Rule

The topology gives **structural priority** to native multimodal model paths.

Rules:
1. When a native-multimodal model is available and selected by `TopologyRouter`,
   it is placed in the Primary Core (Layer 1) with the `[MM]` badge.
2. When no native-multimodal model is selected as primary but one is present as
   a support model, the support orbit still labels it with `[MM]`.
3. Text-only model paths must not be elevated to Layer 1 when a
   native-multimodal candidate is available and healthy in the routing graph.
4. The `is_native_multimodal` field from the projection is the authoritative
   signal; the topology surface must not infer this from model ID prefixes
   unless the projection field is absent.

---

## 5. "Not Drawn on the Starfield but Grown from It"

The key difference between this topology and a conventional status-board widget
is that **layout is data, not template**.

A conventional widget has a fixed grid or list layout into which data is
inserted.  The Sky-Grown Constellation Topology inverts this: the data from
`TopologyRoutePlan` determines how many layers are populated, how many nodes
appear, how bright each node is, and how the depth separator is placed.

Concretely:
- If there are no support models, Layer 2 is absent (not an empty row).
- If there is no active route plan, the Primary Core layer shows a degraded
  `NO CANONICAL ROUTE PLAN` marker rather than a blank slot.
- Weight bars grow and shrink as weights change; they are not fixed-width
  decoration.
- The presence of the `[MM]` badge in Layer 1 reflects a live routing
  decision, not a static provider flag.

---

## 6. Hard Constraints

The following constraints are non-negotiable and must be preserved in all
future implementations of this surface.

| Constraint | Rule |
|---|---|
| **OneAPI lower horizon only** | OneAPI must always appear in Layer 5 (Aggregator Horizon), never in Layers 1–3 |
| **Authority visibility** | `routing_authority` must be displayed; degraded authority must be highlighted, not silently accepted |
| **Terminal/text-friendly rendering** | The topology must render correctly in a CLI/ANSI terminal without graphical dependencies |
| **No dashboard-card regression** | The topology must never degrade to a flat provider card list, regardless of available screen space |
| **Projection-only truth source** | The topology surface must not derive routing conclusions independently; all structure must come from the canonical projection |
| **No true 3-D** | The topology must not require a graphical 3-D rendering context; depth is expressed through 2.5-D visual layering only |
| **Growth-form on empty state** | An absent or degraded route plan must produce a degraded-state topology marker, not an empty/blank display |

---

## 7. Reference Rendering

```
┌─ MODEL CONSTELLATION TOPOLOGY ─────────────────────────────────────┐
│                                                                     │
│  ✦ PRIMARY CORE                                                     │
│                                                                     │
│      ★ gpt-4o  [MM]  [OpenAI]                                       │
│        weight  ██████████  0.920                                    │
│                                                                     │
│  ✧ SUPPORT ORBITS                                                   │
│      · claude-3-5-sonnet  [Anthropic]                               │
│        weight  ████████░░  0.740  reasoning                         │
│      · gemini-2.0-flash   [Google]                                  │
│        weight  ███████░░░  0.680  vision-support                    │
│                                                                     │
│  Route reason : native multimodal primary for live task             │
│  Authority    : topology_router  ✓                                  │
│                                                                     │
│  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─  │
│  ONEAPI AGGREGATOR HORIZON                                          │
│    http://oneapi.local:3000   configured · healthy · 18 models      │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

This rendering is the **target reference** for the topology surface.
It is not required to be pixel-identical in all implementations, but all
structural and semantic elements must be present.

---

## 8. Relationship to Existing Documents

| Document | Relationship |
|---|---|
| [`docs/RIGHT_STATUS_BOARD_MODEL_TOPOLOGY.md`](RIGHT_STATUS_BOARD_MODEL_TOPOLOGY.md) | Foundational topology semantics document; this document extends it with constellation/sky-grown visual identity |
| [`docs/STATUS_BOARD_V2.md`](STATUS_BOARD_V2.md) | `status_board_v2` is the sole canonical desktop surface and the canonical implementation surface for this topology (PR-0) |
| [`docs/MODEL_ROUTING_AUTHORITY.md`](MODEL_ROUTING_AUTHORITY.md) | Defines `TopologyRouter` / `TopologyRoutePlan` as the canonical routing truth source; unchanged in PR-0 |
| [`docs/ONEAPI_SYSTEM_POSITION.md`](ONEAPI_SYSTEM_POSITION.md) | Defines OneAPI's position as a lower aggregator horizon; this document operationalises that in the topology visual grammar |
| [`docs/DASHBOARD_RETIREMENT_AND_MIGRATION.md`](DASHBOARD_RETIREMENT_AND_MIGRATION.md) | Dashboard frontend is retired (PR-0); the topology defined here is the canonical replacement operator-visible surface |
| [`docs/ADR_STATUS_BOARD_CONFIG_AUTHORITY.md`](ADR_STATUS_BOARD_CONFIG_AUTHORITY.md) | ADR freezing `status_board_v2` as sole desktop config entry surface; native-multimodal-first remains governing routing/display principle |
