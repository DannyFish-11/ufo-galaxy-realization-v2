# Dashboard Retirement and Migration

> **Status:** Architecture-freeze canonical — established in PR-1.
> **Scope:** States the retirement intent for the dashboard UI surface, defines
> what migrates to the canonical desktop operator surface, and establishes the
> high-level migration sequence.
>
> Related: [`docs/SKY_GROWN_CONSTELLATION_TOPOLOGY.md`](SKY_GROWN_CONSTELLATION_TOPOLOGY.md) ·
> [`docs/STATUS_BOARD_V2.md`](STATUS_BOARD_V2.md) ·
> [`docs/MODEL_ROUTING_AUTHORITY.md`](MODEL_ROUTING_AUTHORITY.md) ·
> [`docs/ONEAPI_SYSTEM_POSITION.md`](ONEAPI_SYSTEM_POSITION.md)

---

## 1. Retirement Declaration

**The dashboard (`dashboard/`) is no longer the target primary UI surface for
the Galaxy system.**

As of this architecture-freeze baseline:

- No new operator-facing features will be added to the dashboard frontend.
- No new routing-truth or model-topology semantics will be established in the
  dashboard backend.
- The desktop status board (`windows_client/status_board_v2/`) is the canonical
  operator-visible surface for model topology, routing state, and provider
  status.
- Dashboard code is retained only for backward compatibility during the
  migration window; it is not authoritative.

---

## 2. What the Dashboard Currently Provides (Pre-Migration State)

The dashboard historically provided:

| Capability | Current location |
|---|---|
| Provider availability list | `dashboard/backend/` API endpoints |
| Model routing status summary | Dashboard frontend cards |
| OneAPI configuration state display | Dashboard frontend panel |
| Orchestration summary overview | Dashboard frontend overview section |
| Config entry for providers / API keys | Dashboard settings forms |
| Route explanation fragments | Dashboard routing section |

All of these capabilities have either already been superseded by canonical
replacements or are slated for migration per this document.

---

## 3. What Migrates (and Where)

The following capabilities and data semantics migrate away from the dashboard
and into canonical replacement surfaces.

### 3.1 Provider status and availability → `status_board_v2` / projection layer

| Migrates from | Migrates to |
|---|---|
| Dashboard provider availability list | `TopologyRoutePlan` → `RuntimeProjection` → `status_board_v2/topology_surface.py` |
| Dashboard model health cards | `DesktopStatusProjection.model_routing` field |
| Dashboard provider enabled/disabled flags | `ProviderInventory` → `TopologyRouter` → projection |

### 3.2 Route summaries → canonical projection

| Migrates from | Migrates to |
|---|---|
| Dashboard routing summary panels | `TopologyRoutePlan.route_reason` → `RuntimeProjection.route_reason` → topology surface |
| Dashboard "current model" display | `primary_model_id` in `RuntimeProjection` |
| Dashboard support model list | `support_model_ids` in `RuntimeProjection` |
| Dashboard weight/preference indicators | `active_weights` in `RuntimeProjection` |

### 3.3 OneAPI state display → canonical lower-row in topology surface

| Migrates from | Migrates to |
|---|---|
| Dashboard OneAPI configuration panel | `docs/ONEAPI_SYSTEM_POSITION.md` system-wide config model |
| Dashboard OneAPI health indicator | `oneapi_source` in `RuntimeProjection` → OneAPI Aggregator Horizon in `topology_surface.py` |
| Dashboard OneAPI model count display | `oneapi_source.model_count` in projection |

### 3.4 Orchestration summaries → projection layer

| Migrates from | Migrates to |
|---|---|
| Dashboard orchestration summary | `DesktopStatusProjection` orchestration fields |
| Dashboard execution overview panel | `status_board_v2/device_surface.py` and `metrics_surface.py` |

### 3.5 Config entry responsibilities → system-wide config surface

| Migrates from | Migrates to |
|---|---|
| Dashboard OneAPI base URL / API key forms | System-wide config entry (to be defined in a later PR) |
| Dashboard provider enable/disable controls | System-wide config entry |
| Dashboard model preference profiles | Operator override layer (`core/operator_override.py`) |

Config entry migration (§3.5) is **explicitly out of scope** for this PR.
A subsequent PR will define and implement the system-wide config surface.
Until that PR lands, existing dashboard config forms remain the only entry
point for those settings.

---

## 4. What Does NOT Migrate

The following items must not be carried forward into the replacement surface.

| Does NOT migrate | Reason |
|---|---|
| **Flat provider cards** (dashboard-style equal-peer card grid) | Architecturally incorrect representation; topology replaces it |
| **Dashboard-local routing truth** (dashboard deriving current model from its own state) | `TopologyRouter` is the sole canonical routing authority |
| **OneAPI as top-layer peer** (dashboard treating OneAPI as equal to OpenAI/Anthropic) | OneAPI is architecturally a lower aggregator horizon, never a top-layer direct provider |
| **Dashboard UI grammar** (card grid, sidebar nav, page routing) | The target surface is a terminal-native projection-driven topology board |
| **Dashboard-owned projection state** (dashboard maintaining its own authoritative model state) | Projection truth flows from `TopologyRouter` → `RuntimeProjection` → consumers |

---

## 5. Migration Sequence (High Level)

Migration proceeds in five phases.  **This PR freezes Phase A.**

### Phase A — Architecture freeze (this PR)
- Mark dashboard as entering retirement in documentation.
- Establish `TopologyRouter` / `TopologyRoutePlan` as the sole canonical
  routing authority in all documentation.
- Define the Sky-Grown Constellation Topology as the target visual grammar.
- Prohibit new feature additions to the dashboard frontend.

### Phase B — Data semantics extraction
- Extract provider status, route summary, OneAPI status, and orchestration
  summary data semantics from dashboard backend into canonical projection
  contracts (`core/projection/`, `contracts/`).
- Do not delete dashboard frontend or backend yet.
- Target: all routing/model-topology data available via
  `GET /api/v1/projection/runtime` without needing the dashboard.

### Phase C — Desktop status board topology completion
- Complete the Sky-Grown Constellation Topology rendering in
  `status_board_v2/topology_surface.py`.
- All migrated data semantics (§3) rendered in the canonical topology surface.
- OneAPI Aggregator Horizon unconditionally present.

### Phase D — System-wide config entry
- Define and implement a system-wide config surface for OneAPI / provider
  configuration that does not depend on the dashboard frontend.
- Decouple config entry from dashboard entirely.

### Phase E — Dashboard retirement and cleanup
- Deprecate and remove dashboard frontend code.
- Retain any dashboard backend API endpoints that have active callers outside
  the dashboard as compatibility bridges, registering them in
  `core/orchestration_authority/legacy_paths.py`.
- Remove remaining dashboard-local routing truth / model state derivation.

---

## 6. What Must Not Happen During the Migration Window

While Phases B–E are pending:

1. **Do not add new features to the dashboard frontend.**  The dashboard is
   frozen at its current state.
2. **Do not establish new routing-truth sources in the dashboard.**  All
   routing decisions must flow through `TopologyRouter`.
3. **Do not treat the dashboard as authoritative** for any operator-facing
   topology or routing data.  The dashboard may display data, but it is not
   the source of truth.
4. **Do not render OneAPI at the same visual level as direct providers** in any
   new surface, even temporarily.

---

## 7. Relationship to Existing Architecture Documents

| Document | Relationship |
|---|---|
| [`docs/MODEL_ROUTING_AUTHORITY.md`](MODEL_ROUTING_AUTHORITY.md) | Defines `TopologyRouter` as the sole canonical routing authority; dashboard is explicitly not a routing-truth authority |
| [`docs/SKY_GROWN_CONSTELLATION_TOPOLOGY.md`](SKY_GROWN_CONSTELLATION_TOPOLOGY.md) | Defines the target visual grammar of the replacement topology surface |
| [`docs/STATUS_BOARD_V2.md`](STATUS_BOARD_V2.md) | Canonical desktop status board; the primary migration target for operator-visible model topology |
| [`docs/ONEAPI_SYSTEM_POSITION.md`](ONEAPI_SYSTEM_POSITION.md) | Defines OneAPI's position; migration must not regress this position |
| [`core/orchestration_authority/legacy_paths.py`](../core/orchestration_authority/legacy_paths.py) | Registry of legacy compatibility paths; dashboard-era paths registered here |
