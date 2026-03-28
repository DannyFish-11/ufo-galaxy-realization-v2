# Dashboard Retirement and Migration

> **Status:** Architecture-freeze canonical — established in PR-1; direction
> strengthened in PR-0 (unified native-multimodal-first status-board-centred
> architecture freeze).
> **Scope:** States the retirement intent for the dashboard UI surface, defines
> what migrates to the canonical desktop operator surface, and establishes the
> high-level migration sequence.
>
> Related: [`docs/SKY_GROWN_CONSTELLATION_TOPOLOGY.md`](SKY_GROWN_CONSTELLATION_TOPOLOGY.md) ·
> [`docs/STATUS_BOARD_V2.md`](STATUS_BOARD_V2.md) ·
> [`docs/MODEL_ROUTING_AUTHORITY.md`](MODEL_ROUTING_AUTHORITY.md) ·
> [`docs/ONEAPI_SYSTEM_POSITION.md`](ONEAPI_SYSTEM_POSITION.md) ·
> [`docs/CONFIGURATION_ENTRY_UNIFICATION.md`](CONFIGURATION_ENTRY_UNIFICATION.md) ·
> [`docs/ADR_STATUS_BOARD_CONFIG_AUTHORITY.md`](ADR_STATUS_BOARD_CONFIG_AUTHORITY.md)

---

## 1. Retirement Declaration

**The dashboard (`dashboard/`) is no longer the target primary UI surface for
the Galaxy system.**

As of this architecture-freeze baseline (PR-0):

- No new operator-facing features will be added to the dashboard frontend.
- **`dashboard/frontend/` is retired as an operator UI target.**  No new
  operator-facing UI work must target the dashboard frontend.
- No new routing-truth or model-topology semantics will be established in the
  dashboard backend.
- The desktop status board (`windows_client/status_board_v2/`) is the **sole
  canonical operator-facing desktop surface** for model topology, routing state,
  provider status, and — in the future — configuration entry.
- Dashboard backend functionality may be retained temporarily **only** as a
  headless compatibility / capability source during migration.  It is not an
  authoritative surface.
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

### 3.5 Config entry responsibilities → local unified configuration authority

| Migrates from | Migrates to |
|---|---|
| Dashboard OneAPI base URL / API key forms | Local unified configuration authority — `runtime/secrets.env` (keys) and `runtime/config.json` (non-secret settings) |
| Dashboard provider enable/disable controls | Local unified configuration authority |
| Dashboard model preference profiles | Operator override layer (`core/operator_override.py`) |

**Architecture-freeze direction (PR-0):**  Configuration entry is moving to a
**local unified configuration authority** with canonical persistence targets:

- `runtime/config.json` — non-secret system configuration (provider profiles,
  routing preferences, topology overrides).
- `runtime/secrets.env` — secrets such as provider API keys.

These are the canonical system-wide persistence targets.  Configuration changes
entered here must affect provider inventory, routing candidate pool, projection,
and status-board topology system-wide.

The **future operator-facing entry surface** for this configuration is
`windows_client/status_board_v2/`.  See
[`docs/ADR_STATUS_BOARD_CONFIG_AUTHORITY.md`](ADR_STATUS_BOARD_CONFIG_AUTHORITY.md)
and [`docs/CONFIGURATION_ENTRY_UNIFICATION.md`](CONFIGURATION_ENTRY_UNIFICATION.md).

Config entry UI implementation is **explicitly deferred** to a subsequent PR.
Until that PR lands, existing dashboard config forms remain the only interactive
entry point for those settings (headless compatibility use only).

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

Migration proceeds in five phases.  **PR-1 froze Phase A.  PR-0 strengthens
the direction and makes the full migration target explicit.  Phase E (frontend
deletion) has been executed in PR-1.**

### Phase A — Architecture freeze (PR-1 / PR-0) ✅ COMPLETE
- Mark dashboard as entering retirement in documentation.
- Establish `TopologyRouter` / `TopologyRoutePlan` as the sole canonical
  routing authority in all documentation.
- Define the Sky-Grown Constellation Topology as the target visual grammar.
- Prohibit new feature additions to the dashboard frontend.
- **PR-0 additions:**
  - Formally retire `dashboard/frontend/` as an operator UI target.
  - Establish `windows_client/status_board_v2/` as the sole canonical desktop
    operator surface and the future configuration-entry surface.
  - Establish local unified configuration authority
    (`runtime/config.json` / `runtime/secrets.env`) as the canonical
    persistence targets for system configuration.
  - Document that status-board-entered configuration must have system-wide
    effect (implementation deferred to Phase D).
  - Confirm that `TopologyRouter` and `TopologyRoutePlan` remain the sole
    routing authority and output contract — this is unchanged.

### Phase B — Data semantics extraction
- Extract provider status, route summary, OneAPI status, and orchestration
  summary data semantics from dashboard backend into canonical projection
  contracts (`core/projection/`, `contracts/`).
- Dashboard backend remains headless; do not delete backend yet.
- Target: all routing/model-topology data available via
  `GET /api/v1/projection/runtime` without needing the dashboard.

### Phase C — Desktop status board topology completion
- Complete the Sky-Grown Constellation Topology rendering in
  `status_board_v2/topology_surface.py`.
- All migrated data semantics (§3) rendered in the canonical topology surface.
- OneAPI Aggregator Horizon unconditionally present.

### Phase D — System-wide config entry
- Implement the **local unified configuration authority** surface inside
  `windows_client/status_board_v2/`, reading and writing
  `runtime/config.json` and `runtime/secrets.env`.
- Status-board-entered configuration must have system-wide effect: provider
  inventory, routing candidate pool, projection, and status-board topology
  must all reflect config changes without restart where possible.
- Decouple config entry from dashboard entirely.
- `TopologyRouter` continues to be the sole routing authority; the config
  entry surface only modifies inputs to the routing pipeline, not the
  routing logic itself.

### Phase E — Dashboard frontend retirement and cleanup ✅ COMPLETE (PR-1)
- **`dashboard/frontend/` has been fully deleted.**  No web operator-facing UI
  surface remains.
- `dashboard/backend/main.py` continues headless for migration compatibility
  only.  No static files are served.
- Retain any dashboard backend API endpoints that have active callers outside
  the dashboard as compatibility bridges, registering them in
  `core/orchestration_authority/legacy_paths.py`.
- Remove remaining dashboard-local routing truth / model state derivation
  (deferred to Phase B).

---

## 6. What Must Not Happen During the Migration Window

While Phases B–D are pending:

1. **Do not recreate the dashboard frontend.**  `dashboard/frontend/` has been
   permanently deleted.  No web operator-facing UI must be rebuilt here.
2. **Do not establish new routing-truth sources in the dashboard.**  All
   routing decisions must flow through `TopologyRouter`.
3. **Do not treat the dashboard as authoritative** for any operator-facing
   topology or routing data.  The dashboard backend may provide data, but it
   is not the source of truth.
4. **Do not render OneAPI at the same visual level as direct providers** in any
   new surface, even temporarily.
5. **Do not add new operator-facing UI work targeting dashboard.**  All new
   operator UI work must target `windows_client/status_board_v2/`.
6. **Do not write system-level configuration through ad-hoc paths.**  All
   system configuration must target `runtime/config.json` (non-secret) or
   `runtime/secrets.env` (secrets).  Surface-local config must remain
   surface-local and must not affect system state.

---

## 7. Relationship to Existing Architecture Documents

| Document | Relationship |
|---|---|
| [`docs/MODEL_ROUTING_AUTHORITY.md`](MODEL_ROUTING_AUTHORITY.md) | Defines `TopologyRouter` as the sole canonical routing authority; dashboard is explicitly not a routing-truth authority |
| [`docs/SKY_GROWN_CONSTELLATION_TOPOLOGY.md`](SKY_GROWN_CONSTELLATION_TOPOLOGY.md) | Defines the target visual grammar of the replacement topology surface |
| [`docs/STATUS_BOARD_V2.md`](STATUS_BOARD_V2.md) | Canonical desktop status board; the primary migration target for operator-visible model topology and future config entry |
| [`docs/ONEAPI_SYSTEM_POSITION.md`](ONEAPI_SYSTEM_POSITION.md) | Defines OneAPI's position; migration must not regress this position |
| [`docs/CONFIGURATION_ENTRY_UNIFICATION.md`](CONFIGURATION_ENTRY_UNIFICATION.md) | Canonical configuration entry unification contract; local unified config authority and persistence targets |
| [`docs/ADR_STATUS_BOARD_CONFIG_AUTHORITY.md`](ADR_STATUS_BOARD_CONFIG_AUTHORITY.md) | ADR freezing `status_board_v2` as sole desktop config entry surface and local unified config authority model |
| [`core/orchestration_authority/legacy_paths.py`](../core/orchestration_authority/legacy_paths.py) | Registry of legacy compatibility paths; dashboard-era paths registered here |
