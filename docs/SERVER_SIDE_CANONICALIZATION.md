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
