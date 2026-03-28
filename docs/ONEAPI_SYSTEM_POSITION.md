# OneAPI System Position

> **Status:** Canonical — formalised in this PR; strengthened in PR-1 (architecture freeze);
> further enforced in PR-4 (OneAPI horizon and global integration cleanup);
> canonicalization authority made machine-readable in PR-5 (server-side canonicalization).
> **PR-4 note:** This document supersedes prior PR-4 attempts, including PR #408 and
> any earlier replacement attempt related to OneAPI horizon cleanup.
> **PR-5 note:** PR-5 demotes the legacy UCP routing keys that previously could ambiguously
> represent OneAPI state and introduces the `legacy_routing_fallback_active` flag.  See
> [`docs/SERVER_SIDE_CANONICALIZATION.md`](SERVER_SIDE_CANONICALIZATION.md).
> **Scope:** Defines what OneAPI is, what it is not, and how its configuration
> and state must influence the broader Galaxy system.
>
> Related: [`docs/SKY_GROWN_CONSTELLATION_TOPOLOGY.md`](SKY_GROWN_CONSTELLATION_TOPOLOGY.md) ·
> [`docs/MODEL_ROUTING_AUTHORITY.md`](MODEL_ROUTING_AUTHORITY.md) ·
> [`docs/DASHBOARD_RETIREMENT_AND_MIGRATION.md`](DASHBOARD_RETIREMENT_AND_MIGRATION.md) ·
> [`docs/SERVER_SIDE_CANONICALIZATION.md`](SERVER_SIDE_CANONICALIZATION.md)

---

## PR-4: OneAPI Horizon Enforcement

PR-4 strengthens the OneAPI lower-horizon enforcement established in PR-1 with
the following additional architectural rules:

1. **OneAPI is always rendered in the lower aggregator horizon row** — it must
   never appear in the top-layer direct/native provider list or in the
   route-plan primary/support fields, regardless of configuration or routing
   weight.
2. **OneAPI configuration is system-wide** — `ONEAPI_BASE_URL` and
   `ONEAPI_API_KEY` are global system inputs, not dashboard-local config.
3. **The `oneapi_integration` top-level block** is added to
   `DesktopStatusProjection` (PR-4) and is **always present**, even when
   OneAPI is not configured.  When not configured, it shows `configured=False`
   and `health="skipped"`.
4. **The `oneapi_source` field in `ModelRoutingProjection`** is populated
   **only** when the selected route actually routes through OneAPI
   (`vendor_source == "oneapi"`).  It is `None` otherwise.  Using it to
   represent a top-layer provider peer is architecturally incorrect.
5. **Absence of OneAPI data** (not configured) must not cause fallback to
   top-layer rendering — the lower-horizon block simply shows the unconfigured
   state.

---

## PR-5: Server-Side Canonicalization Cross-Reference

PR-5 follows PR-4 and completes the server-side canonicalization of routing and
projection outputs.  The changes most relevant to the OneAPI system position are:

1. **Legacy UCP routing keys demoted** — the flat UCP keys `chosen_model`,
   `chosen_provider`, `is_native_multimodal`, `support_model_ids`,
   `route_reason`, and `multimodal_route` are now registered in
   `LEGACY_UCP_ROUTING_KEYS` (contracts module) and `LEGACY_PROJECTION_UCP_KEYS`
   (projection compiler) as compatibility-only fields.  They must not be used
   by downstream consumers to infer OneAPI state.

2. **`legacy_routing_fallback_active` flag** — `ModelRoutingProjection` gains
   a `legacy_routing_fallback_active: bool` field that is `True` when the
   projection was assembled from the legacy UCP keys rather than from a
   canonical `TopologyRoutePlan`.  Downstream consumers observing
   `legacy_routing_fallback_active == True` must not draw conclusions about
   the OneAPI integration state from the routing fields; instead they must
   consult the top-level `oneapi_integration` block.

3. **`server-canonicalization-status` endpoint** — a new read-only endpoint
   `GET /api/v1/projection/server-canonicalization-status` exposes a
   machine-readable summary of which fields are canonical and which are
   compatibility bridges.  It confirms `oneapi_lower_horizon_guaranteed: true`
   and `pr4_guarantees_intact: true` so monitoring tools can verify PR-4
   invariants in production.

4. **PR-4 guarantees remain intact** — PR-5 makes no changes to the
   `oneapi_integration` block shape or the lower-horizon rendering rule.
   See `docs/SERVER_SIDE_CANONICALIZATION.md §4` for the explicit guarantee
   table.

---

## 1. What OneAPI Is

In this repository, **OneAPI** refers to an **external aggregator integration
layer** — a unified model-gateway service that accepts requests in
OpenAI-compatible format and internally routes them to multiple upstream LLM
providers (OpenAI, Azure OpenAI, Anthropic, Google Gemini, Groq, and others).

Within the Galaxy system architecture, OneAPI occupies the following position:

```
┌──────────────────────────────────────────────────────────────────┐
│  Direct / Native-Multimodal Provider Layer  (top model layer)    │
│  ─────────────────────────────────────────                       │
│  OpenAI  │  Anthropic  │  Gemini  │  xAI  │  …direct vendors    │
└──────────────────────────────────────────────────────────────────┘
                              ▲
          primary/main model topology anchored here
                              │
┌──────────────────────────────────────────────────────────────────┐
│  OneAPI Aggregator Integration Layer  (separate lower row)       │
│  ──────────────────────────────────────────────────────────      │
│  nodes/Node_01_OneAPI  ← external aggregator; connects to        │
│  one or more upstream providers behind a single API endpoint     │
└──────────────────────────────────────────────────────────────────┘
```

The canonical system identifier for this position is:

```python
# core/oneapi_system_position.py
ONEAPI_SYSTEM_LAYER = "aggregator_integration"
```

See `core/oneapi_system_position.py` for the full sentinel and registry.

---

## 2. What OneAPI Is Not

| ❌ Incorrect interpretation | ✅ Correct interpretation |
|---|---|
| Just another direct vendor provider | An **external aggregator** that wraps many providers behind one endpoint |
| A local node implementation detail | A **system-wide aggregator source** whose config has global effect |
| A dashboard-local configuration surface | A **system-level integration input** that feeds provider pool, routing, and status |
| A peer of top-layer direct/native-multimodal models | A **distinct lower-layer aggregator horizon** in the model supply topology |
| An internally invented "new provider philosophy" | An **external open-source project** (one-api / new-api compatible gateway) integrated as a source |

OneAPI **must not** be conflated with direct/native-multimodal providers such
as OpenAI, Anthropic, or Gemini.  Those providers form the primary (top) model
layer.  OneAPI is a **separate aggregator horizon below them**.

**Any top-layer rendering of OneAPI — placing it at the same visual or
architectural level as direct/native-multimodal providers — is architecturally
incorrect and must not be introduced in any new code, documentation, or UI.**

This constraint applies equally to the desktop status board, any future
constellation topology surface, and any dashboard migration artefact.  The
OneAPI Aggregator Horizon separation is a hard architectural invariant.

---

## 3. Why OneAPI Is an Aggregator Integration Layer

OneAPI is structurally distinct from direct providers because:

1. **It speaks on behalf of multiple upstreams.**  A single OneAPI endpoint
   can route to OpenAI, Azure, Anthropic, Gemini, and other backends
   simultaneously.  This makes it an *aggregator*, not a single-vendor API.

2. **It is not a first-party model vendor.**  OneAPI is an open-source
   project (`one-api` / `new-api` family).  Galaxy integrates with it as a
   source, the same way it integrates with any external gateway.

3. **Its configuration is a system-wide input, not per-screen state.**
   When the operator fills in `ONEAPI_BASE_URL` and `ONEAPI_API_KEY`, those
   values enter the system's provider/model pool, routing logic, and
   projection-facing status.  There is no concept of "OneAPI config that
   only applies to one dashboard page".

4. **The `ProviderCategory.ONEAPI` enum value encodes this distinction.**
   In `core/model_topology/topology_types.py`, `ProviderCategory.ONEAPI` is
   explicitly separated from `ProviderCategory.DIRECT`.  The config bridge
   (`core/model_topology/config_bridge.py`) maps OneAPI node entries to
   `ROUTING` topology role — reflecting that it acts as an aggregator, not
   a native multimodal endpoint.

---

## 4. System-Wide Effect Semantics

OneAPI configuration and state **must** flow into the following system
dimensions.  This is not optional; it is a correctness requirement.

### 4.1 Provider / model source availability

When `ONEAPI_BASE_URL` and `ONEAPI_API_KEY` are set:

- `nodes/Node_01_OneAPI/main.py` adds `"oneapi"` to the cloud-provider list.
- `core/multi_llm_router.py` registers a `ProviderConfig(name="oneapi", …)` entry.
- The provider appears in `ProviderInventory` with category
  `ProviderCategory.ONEAPI`.

When not configured, OneAPI must be **absent from** (not just disabled in)
the routing candidate pool.

### 4.2 Routing candidate pool

`TopologyRouter` (`core/model_topology/topology_router.py`) is the canonical
routing authority.  Any `ProviderInventory` entry with category
`ProviderCategory.ONEAPI` participates in graph-based routing the same way as
other inventory entries.  The `ROUTING` topology role assigned by the config
bridge gives OneAPI an appropriate weight in the routing graph without
conflating it with a native multimodal primary provider.

### 4.3 Projection-facing source / model status

`DesktopStatusProjection` (`contracts/desktop_status_projection.py`) is built
from `TopologyRoutePlan` output.  Because OneAPI participates in the topology
graph, its availability and routing participation **will** surface via the
projection contract and therefore via the right-side desktop status board.

### 4.4 Downstream status-board semantics

On the right-side desktop status board (`status_board_v2/`), OneAPI **must**
appear as a **separate lower-layer row — the OneAPI Aggregator Horizon** —
distinct from the top-layer direct/native-multimodal providers.  See
`docs/DESKTOP_DISPLAY_BOUNDARIES.md` for the display-layer contract and
[`docs/SKY_GROWN_CONSTELLATION_TOPOLOGY.md`](SKY_GROWN_CONSTELLATION_TOPOLOGY.md)
§3 Layer 5 for the constellation topology specification.

The status board **must not** intermingle OneAPI status with direct vendor
provider rows.  This is a hard architectural constraint.  Any rendering that
places OneAPI at the same visual level as direct providers is architecturally
incorrect regardless of the surface it appears on.

---

## 5. How Later Status-Board / Model-Topology Work Should Represent OneAPI

When the full model-topology UI (right-side board topology graph) is
implemented in a later PR, the following rules apply.  These rules are
**non-negotiable architectural constraints** established in PR-1.

```
┌─ Model Supply Topology (right-side status board) ─────────────────┐
│                                                                    │
│  TOP LAYER — direct / native-multimodal providers                  │
│  ┌────────────┐  ┌───────────┐  ┌────────┐  ┌────────┐            │
│  │  OpenAI    │  │ Anthropic │  │ Gemini │  │  xAI   │  …        │
│  └────────────┘  └───────────┘  └────────┘  └────────┘            │
│       ↑ primary / support / weight bars displayed here             │
│                                                                     │
│  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─   │
│                                                                     │
│  ONEAPI AGGREGATOR HORIZON — architecturally lower layer            │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  OneAPI  [configured / not configured]  [health indicator]   │  │
│  └──────────────────────────────────────────────────────────────┘  │
│       ↑ distinct row; never interleaved with the top layer         │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

Rules for this representation:

1. **OneAPI is always in the Aggregator Horizon layer**, not interleaved with
   direct providers.  This is a hard architectural invariant.
2. **Clicking the OneAPI row opens a system-wide config surface**, not a
   dashboard-local settings pane.
3. **Configuring OneAPI from that surface must propagate globally** — it must
   update `ONEAPI_BASE_URL` / `ONEAPI_API_KEY` (or the equivalent runtime
   config), trigger a re-registration of the `oneapi` provider in
   `MultiLLMRouter` / `ProviderInventory`, and cause the projection to refresh.
4. **OneAPI health/availability** is shown in the Aggregator Horizon row, not
   in the direct-provider cluster.
5. **The horizontal separator and `ONEAPI AGGREGATOR HORIZON` label are
   mandatory** — they must be present even when OneAPI is not configured, to
   make the architectural boundary visible at all times.

---

## 6. Authority References

| Component | Role |
|---|---|
| `nodes/Node_01_OneAPI/main.py` | Node service that proxies requests to upstream providers via an external OneAPI-compatible gateway |
| `core/model_topology/topology_types.py` | `ProviderCategory.ONEAPI` — canonical category enum value |
| `core/model_topology/config_bridge.py` | Maps OneAPI entries to `ProviderCategory.ONEAPI` and `TopologyRole.ROUTING` |
| `core/model_topology/canonical_model_supply_state.py` | Maps `ProviderCategory.ONEAPI` to `ProviderLocalityClass.CLOUD` |
| `core/multi_llm_router.py` | Registers `oneapi` as a provider when `ONEAPI_BASE_URL`/`ONEAPI_API_KEY` are set |
| `core/oneapi_system_position.py` | Sentinel + registry module; canonical source of truth for OneAPI's system position |
| `contracts/desktop_status_projection.py` | Projection contract; OneAPI state surfaces here as part of `ModelRoutingProjection` |
| `docs/DESKTOP_DISPLAY_BOUNDARIES.md` | Display-layer contract; OneAPI status belongs on the right-side board, not liminal space |
| `docs/MODEL_ROUTING_AUTHORITY.md` | Routing authority contract; `TopologyRouter` is the sole canonical routing authority, and OneAPI participates as a `ProviderCategory.ONEAPI` inventory entry |

---

## 7. Migration Note

Prior to this PR, OneAPI's system-wide role was implicit and partially
expressed only in node-level code and dashboard UI fragments.  This document
and `core/oneapi_system_position.py` make it explicit and testable.

Any code or documentation that treats OneAPI as:
- merely a local-node implementation detail, **or**
- a peer direct/native-multimodal provider, **or**
- a dashboard-local configuration surface only

…is **incorrect** and should be updated to match this canonical position.

---

## 8. PR-4 Projection Contract Changes

PR-4 adds a distinct `oneapi_integration` top-level field to
`DesktopStatusProjection` in `contracts/desktop_status_projection.py`.

### `oneapi_integration` block (always present)

```json
{
  "system_layer": "aggregator_integration",
  "configured": true,
  "health": "healthy",
  "base_url_hint": "http://host:3000",
  "model_count": null,
  "gateway_identity": "oneapi-gateway"
}
```

- `system_layer` is always `"aggregator_integration"`.
- `configured` is `true` when `ONEAPI_BASE_URL` and `ONEAPI_API_KEY` are both set.
- `health` is one of `"healthy"`, `"degraded"`, `"skipped"`.
- `base_url_hint` is a sanitised (non-secret) hint of the base URL.
- `model_count` is the number of models available, or `null` if unknown.
- `gateway_identity` is a short identity string (e.g. `"oneapi-gateway"`).

### Separation from top-layer routing

The `oneapi_integration` block is **entirely separate** from
`model_routing.selected_provider`, `model_routing.selected_model`, and
`model_routing.support_model_hints`.  No code path should ever:

- Copy `oneapi_integration` fields into the top-layer provider list.
- Set `model_routing.vendor_source` to `"oneapi"` unless the primary route
  actually goes through the OneAPI node.
- Render the OneAPI aggregator horizon at the same visual level as top-layer
  direct/native providers.

Any such rendering is **architecturally incorrect**.
