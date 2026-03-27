# Server-Side Canonicalization

> **Status:** Canonical — formalised in PR-5 (server-side canonicalization after PR-4).
> **Scope:** Server-side projection and routing output canonicalization.
>
> Related: [`docs/MODEL_ROUTING_AUTHORITY.md`](MODEL_ROUTING_AUTHORITY.md) ·
> [`docs/ONEAPI_SYSTEM_POSITION.md`](ONEAPI_SYSTEM_POSITION.md) ·
> [`docs/RUNTIME_PROJECTION.md`](RUNTIME_PROJECTION.md)

---

## 1. Overview

PR-5 completes the **server-side canonicalization** phase that follows
PR-4 (OneAPI lower-horizon cleanup).  It removes remaining ambiguous and
non-canonical projection/routing outputs so that the backend emits a cleaner,
single source of truth for downstream desktop topology work.

### Prior PR chain summary

| PR | What it established |
|----|---------------------|
| PR-2 | `TopologyRoutePlan` as the sole canonical routing output contract |
| PR-3 | `vendor_source`/`oneapi_source` in `ModelRoutingProjection`; `canonical-routing` endpoint |
| PR-4 | OneAPI lower-horizon cleanup; `oneapi_integration` block always present in `DesktopStatusProjection` |
| **PR-5** | **Legacy UCP routing key demotion; `legacy_routing_fallback_active` flag; `server-canonicalization-status` endpoint** |

---

## 2. What PR-5 Changes

### 2.1 `LEGACY_UCP_ROUTING_KEYS` — demotion registry

`contracts/desktop_status_projection.py` now exports a
`frozenset` of top-level UCP keys that are retained as **compatibility bridges
only**:

```python
LEGACY_UCP_ROUTING_KEYS = frozenset({
    "chosen_model",
    "chosen_provider",
    "is_native_multimodal",
    "support_model_ids",
    "route_reason",
    "multimodal_route",
})
```

Downstream consumers **must not** rely on these keys when a
`topology_route_plan` block is present in the UCP.  The canonical routing
authority is always
`core.model_topology.topology_router.CANONICAL_ROUTING_AUTHORITY`.

### 2.2 `ModelRoutingProjection.legacy_routing_fallback_active`

A new boolean field `legacy_routing_fallback_active` was added to
`ModelRoutingProjection` (PR-5).

- `False` — routing fields were assembled from the canonical
  `TopologyRoutePlan` (`routing_authority_source == "topology_router"`).
- `True` — routing fields were assembled from legacy/compat UCP keys
  (`routing_authority_source == "legacy_ucp_keys"`).

Downstream consumers should treat a projection with
`legacy_routing_fallback_active == True` as **degraded** for routing fields and
prefer to source routing data from a canonical `TopologyRoutePlan` when possible.

### 2.3 `LEGACY_ROUTING_FIELDS` in `topology_router.py`

`core/model_topology/topology_router.py` now exports a tuple of routing-related
identifiers that are legacy/compatibility bridges:

```python
LEGACY_ROUTING_FIELDS = (
    "chosen_model",
    "chosen_provider",
    "chosen_provider_category",
    "MultiLLMRouter",
    "dashboard_provider_endpoint",
)
```

### 2.4 `LEGACY_PROJECTION_UCP_KEYS` in `projection_compiler.py`

`core/projection/projection_compiler.py` now exports a tuple of top-level UCP
keys that are legacy/compatibility-only:

```python
LEGACY_PROJECTION_UCP_KEYS = (
    "chosen_model",
    "chosen_provider",
    "is_native_multimodal",
    "support_model_ids",
    "route_reason",
    "multimodal_route",
)
```

### 2.5 New API endpoint

A new read-only endpoint was added in PR-5:

```
GET /api/v1/projection/server-canonicalization-status
```

This returns a machine-checkable summary of the current canonicalization state,
including:
- Canonical routing/projection authorities
- Legacy UCP keys demoted by PR-5
- PR-4 OneAPI lower-horizon guarantee status
- Consumer guidance for downstream surfaces

---

## 3. Canonical Server Output Hierarchy (post-PR-5)

```
┌──────────────────────────────────────────────────────────────────┐
│  CANONICAL OUTPUTS (always prefer these)                        │
│                                                                  │
│  TopologyRoutePlan.to_dict()          ← routing truth            │
│  DesktopStatusProjection.to_dict()    ← desktop status truth     │
│  RuntimeProjection.to_dict()          ← runtime state truth      │
│  oneapi_integration block             ← OneAPI lower-horizon     │
└──────────────────────────────────────────────────────────────────┘
                              │
              Fallback (compatibility-only — PR-5 demoted)
                              │
┌──────────────────────────────────────────────────────────────────┐
│  LEGACY COMPAT ONLY (use only when canonical unavailable)       │
│                                                                  │
│  chosen_model / chosen_provider       ← top-level UCP keys       │
│  is_native_multimodal / support_model_ids                        │
│  route_reason (top-level UCP key — distinct from the canonical  │
│    route_reason field inside TopologyRoutePlan)                  │
│  multimodal_route block                                          │
└──────────────────────────────────────────────────────────────────┘
```

---

## 4. PR-4 Guarantees Preserved

PR-5 does not undo any PR-4 guarantees:

- `DesktopStatusProjection.oneapi_integration` is **always present** (even when
  OneAPI is not configured).
- The `oneapi_integration` block is always a **separate lower-horizon block** and
  must never be merged into the top-layer provider list or route-plan
  primary/support fields.
- `ONEAPI_SYSTEM_LAYER == "aggregator_integration"` is unchanged.
- `model_routing.oneapi_source` is `None` when `vendor_source != "oneapi"`.

---

## 5. Consumer Guidance

Downstream consumers of server projection outputs should:

1. **Prefer `topology_route_plan`** in UCP for all routing decisions.  When
   present, it provides canonical `selected_model`, `selected_provider`,
   `vendor_source`, `route_reason`, `active_weights`.

2. **Use `oneapi_integration`** block for OneAPI status — never `oneapi_source`
   from `model_routing` for the system-level integration picture.

3. **Check `legacy_routing_fallback_active`** on `ModelRoutingProjection` to
   detect when the projection is in degraded mode for routing fields.

4. **Avoid top-level UCP keys** (`chosen_model`, `chosen_provider`, etc.) when
   the canonical `topology_route_plan` block is present.

5. **Use the machine-checkable endpoint**
   `GET /api/v1/projection/server-canonicalization-status` to introspect the
   current canonicalization state at runtime.

---

## 6. Machine-Checkable Exports

| Symbol | Module | Type | Description |
|--------|--------|------|-------------|
| `LEGACY_UCP_ROUTING_KEYS` | `contracts.desktop_status_projection` | `frozenset` | Legacy UCP routing keys |
| `PROJECTION_CONTRACT_AUTHORITY` | `contracts.desktop_status_projection` | `str` | Canonical projection contract authority sentinel |
| `LEGACY_ROUTING_FIELDS` | `core.model_topology.topology_router` | `tuple` | Legacy routing field names |
| `CANONICAL_ROUTING_AUTHORITY` | `core.model_topology.topology_router` | `str` | Canonical routing authority sentinel |
| `LEGACY_PROJECTION_UCP_KEYS` | `core.projection.projection_compiler` | `tuple` | Legacy UCP projection keys |
| `PROJECTION_COMPILER_AUTHORITY` | `core.projection.projection_compiler` | `str` | Canonical projection compiler sentinel |
| `legacy_routing_fallback_active` | `ModelRoutingProjection` | `bool` field | Degraded routing path indicator |

---

## 7. API Endpoints (post-PR-5)

| Endpoint | PR | Description |
|----------|-----|-------------|
| `GET /api/v1/projection/runtime` | PR-3 | Live `RuntimeProjection` |
| `GET /api/v1/projection/canonical-routing` | PR-3 | Canonical routing + provider status |
| `GET /api/v1/projection/server-canonicalization-status` | **PR-5** | Server-side canonicalization summary |

---

## 8. PR-6 Desktop Topology Projection Delivery

PR-6 delivers the final desktop topology-oriented projection layer on top of
the PR-5 canonicalization foundation.

### What PR-6 adds

| Addition | Location | Purpose |
|----------|----------|---------|
| `TOPOLOGY_PROJECTION_DELIVERY_AUTHORITY` | `contracts.desktop_status_projection` | Machine-checkable sentinel for PR-6 topology-ready block |
| `TOPOLOGY_PROJECTION_DELIVERY_AUTHORITY` | `core.projection.projection_compiler` | Mirror sentinel in the projection compiler namespace |
| `DesktopTopologyProjection` | `contracts.desktop_status_projection` | Renderer-agnostic structured block for desktop topology surfaces |
| `topology_ready` field | `DesktopStatusProjection` | PR-6 topology-ready block attached to the top-level projection |
| `GET /api/v1/projection/desktop-topology` | `core/routes/projection.py` | Dedicated endpoint returning the topology-ready block |

### Consumer guidance (post-PR-6)

1. **Desktop topology surfaces** should consume the `topology_ready` block from
   `DesktopStatusProjection` (or from `GET /api/v1/projection/desktop-topology`)
   as the single canonical topology-ready projection.  Legacy/dashboard-era
   assembly is no longer necessary when this block is present.

2. **`canonical_source_present == true`** confirms the block was derived from a
   canonical `TopologyRoutePlan`.  `legacy_fallback_active == true` signals a
   degraded projection (assembled from legacy UCP keys).

3. **`oneapi_integration`** inside `topology_ready` remains a lower-horizon
   integration block only — it must never be promoted to a top-layer provider peer.

4. **`contract_authority`** is the machine-checkable sentinel
   `"contracts.desktop_status_projection.DesktopTopologyProjection"` confirming
   the block was produced by the canonical builder.

### Machine-Checkable Exports (PR-6)

| Symbol | Module | Type | Description |
|--------|--------|------|-------------|
| `TOPOLOGY_PROJECTION_DELIVERY_AUTHORITY` | `contracts.desktop_status_projection` | `str` | PR-6 topology-ready delivery sentinel |
| `TOPOLOGY_PROJECTION_DELIVERY_AUTHORITY` | `core.projection.projection_compiler` | `str` | Mirror sentinel in compiler namespace |
| `DesktopTopologyProjection` | `contracts.desktop_status_projection` | Pydantic model | Topology-ready projection block |

### API Endpoints (post-PR-6)

| Endpoint | PR | Description |
|----------|-----|-------------|
| `GET /api/v1/projection/runtime` | PR-3 | Live `RuntimeProjection` |
| `GET /api/v1/projection/canonical-routing` | PR-3 | Canonical routing + provider status |
| `GET /api/v1/projection/server-canonicalization-status` | PR-5 | Server-side canonicalization summary |
| `GET /api/v1/projection/desktop-topology` | **PR-6** | Topology-ready projection block for desktop surfaces |

---

## 9. PR-7 Desktop Constellation Consumption Hardening

PR-7 hardens the consumer-facing robustness of the topology projection layer
by adding explicit readiness/quality semantics to `DesktopTopologyProjection`.
Downstream desktop/constellation consumers can now determine — in a structured,
machine-readable way — whether topology projection data is canonical,
degraded, partial, or unavailable.

### What PR-7 adds

| Addition | Location | Purpose |
|----------|----------|---------|
| `TOPOLOGY_READINESS_CONTRACT_AUTHORITY` | `contracts.desktop_status_projection` | Machine-checkable sentinel for PR-7 quality/readiness block |
| `TOPOLOGY_READINESS_CONTRACT_AUTHORITY` | `core.projection.projection_compiler` | Mirror sentinel in compiler namespace |
| `TopologyProjectionReadiness` | `contracts.desktop_status_projection` | Enum: `canonical` / `degraded` / `partial` / `unavailable` |
| `TopologyProjectionQualityBlock` | `contracts.desktop_status_projection` | Structured quality/readiness Pydantic model |
| `projection_quality` field | `DesktopTopologyProjection` | PR-7 quality block attached to the topology-ready projection |

### Readiness / quality states

| State | Meaning | `authoritative` | Consumer guidance |
|-------|---------|-----------------|-------------------|
| `canonical` | Sourced from canonical `TopologyRoutePlan`; all components healthy | `true` | May treat data as full routing truth |
| `degraded` | Sourced from legacy UCP keys (fallback path) | `false` | Must **not** treat as full routing truth; surface degraded state to operator |
| `partial` | Canonical source used but key components missing/unavailable | `false` | Topology available but not fully healthy; indicate partial state to operator |
| `unavailable` | No routing data at all | `false` | Must not render constellation topology from this block |

### Consumer guidance (post-PR-7)

1. **Always inspect `projection_quality` before treating topology data as
   authoritative.**  `projection_quality.authoritative == false` means the
   data **must not** be used as ground truth.

2. **`projection_quality.readiness`** is the primary discriminator:
   - `"canonical"` → fully authoritative; all systems go.
   - `"degraded"` → legacy fallback active; surface warning to operator.
   - `"partial"` → canonical source but components missing; surface partial state.
   - `"unavailable"` → no data; do not render topology.

3. **`projection_quality.degraded == true`** explicitly mirrors
   `legacy_fallback_active` inside the quality contract so it cannot be
   overlooked by consumers inspecting only the quality block.

4. **`projection_quality.quality_note`** provides a human-readable explanation
   suitable for diagnostic logs and operator-facing surfaces.

5. **OneAPI** (`oneapi_integration`) remains a lower-horizon block only — it
   is present within `DesktopTopologyProjection` and at the top-level
   `DesktopStatusProjection`, but must never be promoted to a top-layer
   provider peer.

### Machine-Checkable Exports (PR-7)

| Symbol | Module | Type | Description |
|--------|--------|------|-------------|
| `TOPOLOGY_READINESS_CONTRACT_AUTHORITY` | `contracts.desktop_status_projection` | `str` | PR-7 quality/readiness block sentinel |
| `TOPOLOGY_READINESS_CONTRACT_AUTHORITY` | `core.projection.projection_compiler` | `str` | Mirror sentinel in compiler namespace |
| `TopologyProjectionReadiness` | `contracts.desktop_status_projection` | `StrEnum` | Readiness state enum |
| `TopologyProjectionQualityBlock` | `contracts.desktop_status_projection` | Pydantic model | Structured quality/readiness block |

### API Endpoints (post-PR-7)

| Endpoint | PR | Description |
|----------|-----|-------------|
| `GET /api/v1/projection/runtime` | PR-3 | Live `RuntimeProjection` |
| `GET /api/v1/projection/canonical-routing` | PR-3 | Canonical routing + provider status |
| `GET /api/v1/projection/server-canonicalization-status` | PR-5 | Server-side canonicalization summary |
| `GET /api/v1/projection/desktop-topology` | PR-6 / **PR-7** | Topology-ready block with readiness/quality semantics |

---

## 10. PR-8 Final Desktop Status Board Integration Contract

PR-8 completes the server-side contract work by delivering a final integration-oriented
payload for the desktop status board / topology consumer boundary.  After PR-8, desktop
clients can consume **one stable server-provided payload** without re-deriving state from
multiple endpoints or legacy/dashboard-era assembly logic.

### What PR-8 adds

| Addition | Location | Purpose |
|----------|----------|---------|
| `DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY` | `contracts.desktop_status_projection` | Machine-checkable PR-8 sentinel |
| `DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY` | `core.projection.projection_compiler` | Mirror sentinel in compiler namespace |
| `DesktopStatusBoardIntegrationPayload` | `contracts.desktop_status_projection` | Final composed integration payload |
| `build_desktop_status_board_integration_payload()` | `contracts.desktop_status_projection` | Builder composing PR-4 through PR-7 structures |
| `GET /api/v1/projection/desktop-status-board` | `core.routes.projection` | Single stable integration endpoint |

### Canonical authority layering (unchanged)

PR-8 does **not** alter the canonical authority layering established by PR-2 through PR-7:

- `TopologyRoutePlan` remains the sole canonical routing output contract.
- `DesktopStatusProjection` (via `build_desktop_status_projection`) remains the canonical
  projection contract.
- Legacy UCP routing keys remain demoted (PR-5).
- OneAPI remains a lower-horizon integration block (PR-4).
- Topology readiness/quality semantics remain structured (PR-7).

The PR-8 integration payload **composes** these established structures; it does not
replace or duplicate them.

### Consumer guidance (post-PR-8)

Desktop clients should:

1. Consume `GET /api/v1/projection/desktop-status-board` as the single integration endpoint.
2. Inspect `authority_indicators` for a consolidated view of all canonical-vs-legacy signals.
3. Check `authority_indicators.topology_authoritative` before treating topology data as truth.
4. Verify `integration_authority == "contracts.desktop_status_projection.DesktopStatusBoardIntegrationPayload"`.
5. Stop assembling status board state from scattered legacy/dashboard-era sources.

### Machine-Checkable Exports (PR-8)

| Symbol | Module | Type | Description |
|--------|--------|------|-------------|
| `DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY` | `contracts.desktop_status_projection` | `str` | PR-8 integration payload sentinel |
| `DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY` | `core.projection.projection_compiler` | `str` | Mirror sentinel in compiler namespace |
| `DesktopStatusBoardIntegrationPayload` | `contracts.desktop_status_projection` | Pydantic model | Final integration-oriented payload |

### API Endpoints (post-PR-8)

| Endpoint | PR | Description |
|----------|-----|-------------|
| `GET /api/v1/projection/runtime` | PR-3 | Live `RuntimeProjection` |
| `GET /api/v1/projection/canonical-routing` | PR-3 | Canonical routing + provider status |
| `GET /api/v1/projection/server-canonicalization-status` | PR-5 | Server-side canonicalization summary |
| `GET /api/v1/projection/desktop-topology` | PR-6/7 | Topology-ready block with readiness/quality semantics |
| `GET /api/v1/projection/desktop-status-board` | **PR-8** | **Final integrated desktop status board payload** |
