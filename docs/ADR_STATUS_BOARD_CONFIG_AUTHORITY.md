# ADR: Status Board as Sole Desktop Configuration Entry Surface and Local Unified Configuration Authority

> **Type:** Architecture Decision Record (ADR)
> **Status:** Accepted — PR-0 architecture freeze
> **Scope:** Desktop operator surface model, configuration authority, routing
> authority, native-multimodal-first display principle
>
> Related:
> [`docs/STATUS_BOARD_V2.md`](STATUS_BOARD_V2.md) ·
> [`docs/CONFIGURATION_ENTRY_UNIFICATION.md`](CONFIGURATION_ENTRY_UNIFICATION.md) ·
> [`docs/DASHBOARD_RETIREMENT_AND_MIGRATION.md`](DASHBOARD_RETIREMENT_AND_MIGRATION.md) ·
> [`docs/MODEL_ROUTING_AUTHORITY.md`](MODEL_ROUTING_AUTHORITY.md) ·
> [`docs/SKY_GROWN_CONSTELLATION_TOPOLOGY.md`](SKY_GROWN_CONSTELLATION_TOPOLOGY.md) ·
> [`docs/RIGHT_STATUS_BOARD_MODEL_TOPOLOGY.md`](RIGHT_STATUS_BOARD_MODEL_TOPOLOGY.md) ·
> [`windows_client/status_board_v2/ACTIVE_SURFACE.md`](../windows_client/status_board_v2/ACTIVE_SURFACE.md)

---

## 1. Context

The Galaxy system has historically had two operator-facing surfaces competing
for canonical status:

1. **`dashboard/`** — a web-based dashboard (frontend + backend) providing
   provider status, routing summaries, config entry forms, and OneAPI state
   display.
2. **`windows_client/status_board_v2/`** — a terminal-native, projection-driven
   status board showing model topology, routing state, and provider status in a
   Sky-Grown Constellation Topology visual grammar.

PR-1 began formalising `status_board_v2` as the canonical desktop status
surface and placed the dashboard in retirement.  However, the following
questions remained open or ambiguous:

- Which surface is the sole canonical desktop operator surface?
- Where does configuration entry happen after the dashboard is retired?
- Which files are the canonical persistence targets for system configuration?
- Does adding a config entry surface to `status_board_v2` change the routing
  authority model?
- Is native-multimodal-first still the governing display principle?

This ADR answers all of these questions with explicit, binding decisions.

---

## 2. Decisions

### Decision 1 — `windows_client/status_board_v2/` is the sole canonical desktop operator surface

`windows_client/status_board_v2/` is formally declared the **sole canonical
desktop operator-facing surface** for the Galaxy system.

- All legacy desktop/operator surfaces are retired.  This includes (but is not
  limited to) `windows_client/status_board.py` (root-level legacy board) and
  `windows_client/ui_sidebar.py` (already hard-disabled).
- **No new operator-facing desktop UI work must target any surface other than
  `windows_client/status_board_v2/`.**
- Existing code in retired surfaces is not deleted by this PR.  Deletion is
  deferred to Phase E of the dashboard migration.

### Decision 2 — `dashboard/frontend/` is retired as an operator UI target

`dashboard/frontend/` is **retired** as a target operator UI surface.

- No new operator-facing UI features must be added to `dashboard/frontend/`.
- Dashboard backend functionality (`dashboard/backend/`) may be retained
  **temporarily** as a headless compatibility/capability source during the
  migration window.  It is not authoritative.
- The dashboard is not deleted by this PR.  Deletion and cleanup are Phase E.

### Decision 3 — Local unified configuration authority model

The system is adopting a **local unified configuration authority** model with
the following canonical persistence targets:

| Target | Content |
|--------|---------|
| `runtime/config.json` | Non-secret system configuration — provider profiles, routing preferences, topology overrides, feature flags |
| `runtime/secrets.env` | Secrets — provider API keys (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, OneAPI token, etc.) |

Constraints:

- `runtime/config.json` is loaded by `core/unified_config.py` (same reader as
  `config.json`; the `runtime/` path is the operator-entry target).
- `runtime/secrets.env` follows the same naming conventions as `.env`.
- Configuration changes written to these targets are **system-wide inputs** —
  they affect provider inventory, routing candidate pool, projection output,
  and status-board topology.  They are not surface-local state.
- Secrets must never be written to `runtime/config.json`.
- Non-secret structured configuration must never be mixed into
  `runtime/secrets.env`.

### Decision 4 — `status_board_v2` becomes the sole desktop configuration entry surface (future)

The future direction is that **interactive configuration entry for the Galaxy
system happens exclusively through `windows_client/status_board_v2/`**.

- This is the designated implementation target for Phase D of the dashboard
  migration.
- Configuration written through the status board must write to
  `runtime/config.json` / `runtime/secrets.env` and must have system-wide
  effect.
- Status-board-entered configuration must **not** be stored as per-surface
  local state — it is system configuration, not surface preferences.

> **This decision is a future architectural commitment.**  The interactive
> config entry UI is **not implemented in this PR**.  Implementation is
> deferred to Phase D.

### Decision 5 — Routing authority unchanged

`TopologyRouter` remains the **sole canonical routing authority**.
`TopologyRoutePlan` remains the **sole canonical routing output contract**.

- Adding a configuration entry surface to `status_board_v2` does not change
  this.  Configuration entry modifies routing *inputs* (provider inventory,
  model preferences); it never bypasses or replaces `TopologyRouter` as the
  routing decision-maker.
- The status board must not derive routing truth independently — not now, and
  not when the config entry surface is added.
- Any routing summary that does not originate from `TopologyRoutePlan` remains
  a degraded compatibility artefact, not an authoritative source.

The canonical authority sentinel is unchanged:

```python
# core/model_topology/topology_router.py
CANONICAL_ROUTING_AUTHORITY = "core.model_topology.topology_router.TopologyRouter"
```

### Decision 6 — Native-multimodal-first remains the governing routing and display principle

The **Native-Multimodal-First Sky-Grown Constellation Topology** remains the
canonical visual and semantic model for the desktop status board.

- Native multimodal paths anchor the primary layer whenever available.
- Text-only paths are support/fallback — they are not elevated to the primary
  layer unless no native-multimodal path is available.
- **OneAPI remains lower-horizon only** — it must never be represented as a
  top-layer direct peer of direct provider APIs.
- The `[MM]` badge, primary layer, support orbit, and OneAPI Aggregator Horizon
  layers defined in `docs/SKY_GROWN_CONSTELLATION_TOPOLOGY.md` remain in
  force.

---

## 3. Consequences

### What becomes true after this PR

1. The repository documentation unambiguously states that `status_board_v2` is
   the only canonical desktop operator surface.
2. The repository documentation unambiguously states that `dashboard/frontend/`
   is a retired target and no new operator UI work must go there.
3. The canonical persistence targets for system configuration are defined:
   `runtime/config.json` and `runtime/secrets.env`.
4. Future PRs implementing Phase D have a clear, binding contract to implement
   against.
5. The routing authority model is explicitly confirmed as unchanged.
6. The native-multimodal-first principle is explicitly confirmed as unchanged.

### What is deferred

- Deletion of `dashboard/frontend/` code (Phase E).
- Deletion of legacy desktop surfaces (Phase E).
- Implementation of interactive config entry UI in `status_board_v2` (Phase D).
- Implementation of `runtime/config.json` writer / `runtime/secrets.env` writer
  (Phase D).

### What is not changed by this PR

- Any existing code, routes, or runtime behaviour.
- `TopologyRouter` routing logic.
- `TopologyRoutePlan` output contract.
- The Sky-Grown Constellation Topology visual rendering.
- The projection pipeline (`RuntimeProjection`, `DesktopStatusProjection`,
  `DesktopStatusBoardIntegrationPayload`).
- The existing `config.json` + `.env` configuration loading behaviour.

---

## 4. Invariants that must not be violated in future PRs

| Invariant | Rule |
|-----------|------|
| Sole desktop surface | No new operator-facing desktop UI surface may be created; all work targets `status_board_v2` |
| Routing authority | `TopologyRouter` is the sole routing decision-maker; `TopologyRoutePlan` is the sole routing output contract |
| Config authority | System configuration persistence uses `runtime/config.json` (non-secret) and `runtime/secrets.env` (secrets) |
| Config scope | Status-board-entered config has system-wide effect; it is never surface-local state |
| Native-multimodal-first | MM paths are always primary; text-only paths never elevated when MM available; OneAPI stays lower-horizon |
| Dashboard retirement | No new features to `dashboard/frontend/`; no new routing truth in dashboard |

---

## 5. Related documents

| Document | Relationship |
|----------|-------------|
| [`docs/STATUS_BOARD_V2.md`](STATUS_BOARD_V2.md) | `status_board_v2` design guide; updated in PR-0 to reflect sole surface declaration |
| [`docs/CONFIGURATION_ENTRY_UNIFICATION.md`](CONFIGURATION_ENTRY_UNIFICATION.md) | Configuration entry unification contract; updated in PR-0 to add local unified config authority |
| [`docs/DASHBOARD_RETIREMENT_AND_MIGRATION.md`](DASHBOARD_RETIREMENT_AND_MIGRATION.md) | Dashboard retirement plan; updated in PR-0 to formalise frontend retirement and config migration direction |
| [`docs/MODEL_ROUTING_AUTHORITY.md`](MODEL_ROUTING_AUTHORITY.md) | Routing authority contract; PR-0 confirms it is unchanged |
| [`docs/SKY_GROWN_CONSTELLATION_TOPOLOGY.md`](SKY_GROWN_CONSTELLATION_TOPOLOGY.md) | Sky-Grown Constellation Topology visual grammar; PR-0 confirms it remains the governing principle |
| [`docs/RIGHT_STATUS_BOARD_MODEL_TOPOLOGY.md`](RIGHT_STATUS_BOARD_MODEL_TOPOLOGY.md) | Right-side status board topology semantics; updated in PR-0 to confirm sole surface status |
| [`windows_client/status_board_v2/ACTIVE_SURFACE.md`](../windows_client/status_board_v2/ACTIVE_SURFACE.md) | Surface-level marker file; updated in PR-0 to reflect sole surface and future config entry role |
