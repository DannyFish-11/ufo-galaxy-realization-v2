# OneAPI System Position

> **Status:** Canonical — formalised in this PR.
> **Scope:** Defines what OneAPI is, what it is not, and how its configuration
> and state must influence the broader Galaxy system.

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
| A peer of top-layer direct/native-multimodal models | A **distinct lower-layer** row in the model supply topology |
| An internally invented "new provider philosophy" | An **external open-source project** (one-api / new-api compatible gateway) integrated as a source |

OneAPI **must not** be conflated with direct/native-multimodal providers such
as OpenAI, Anthropic, or Gemini.  Those providers form the primary (top) model
layer.  OneAPI is a separate row below them.

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
appear as a separate lower-layer row — distinct from the top-layer
direct/native-multimodal providers.  See
`docs/DESKTOP_DISPLAY_BOUNDARIES.md` for the display-layer contract.

The status board **must not** intermingle OneAPI status with direct vendor
provider rows.

---

## 5. How Later Status-Board / Model-Topology Work Should Represent OneAPI

When the full model-topology UI (right-side board topology graph) is
implemented in a later PR, the following rules apply:

```
┌─ Model Supply Topology (right-side status board) ─────────────────┐
│                                                                    │
│  TOP LAYER — direct / native-multimodal providers                  │
│  ┌────────────┐  ┌───────────┐  ┌────────┐  ┌────────┐            │
│  │  OpenAI    │  │ Anthropic │  │ Gemini │  │  xAI   │  …        │
│  └────────────┘  └───────────┘  └────────┘  └────────┘            │
│       ↑ primary / support / weight bars displayed here             │
│                                                                    │
│  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─   │
│                                                                    │
│  LOWER ROW — aggregator integration layer                          │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  OneAPI  [configured / not configured]  [health indicator]   │  │
│  └──────────────────────────────────────────────────────────────┘  │
│       ↑ distinct row; click opens system-wide config entry point   │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

Rules for this representation:

1. **OneAPI is always a separate row**, not interleaved with direct providers.
2. **Clicking the OneAPI row opens a system-wide config surface**, not a
   dashboard-local settings pane.
3. **Configuring OneAPI from that surface must propagate globally** — it must
   update `ONEAPI_BASE_URL` / `ONEAPI_API_KEY` (or the equivalent runtime
   config), trigger a re-registration of the `oneapi` provider in
   `MultiLLMRouter` / `ProviderInventory`, and cause the projection to refresh.
4. **OneAPI health/availability** is shown in this lower row, not in the
   direct-provider cluster.

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
