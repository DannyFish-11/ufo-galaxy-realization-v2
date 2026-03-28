# Desktop Pipeline Architecture — Final Reference (PR-15)

> **This document is the authoritative post-PR-15 architecture reference for
> the desktop status board / topology pipeline.**  It supersedes any partial
> descriptions scattered across earlier PR-specific documents and describes
> the full consumption path from server contract to adapter, layout, rendering,
> inspection, and history.

---

## Overview

The Galaxy desktop topology / status board pipeline was built incrementally
across PR-4 through PR-14.  PR-15 closes this multi-PR initiative and
establishes the final, hardened, regression-protected state.

The pipeline has **seven layers**, each with a clearly-scoped responsibility:

```
Server contract           contracts/desktop_status_projection.py
        │
        ▼
Integration bridge        core/projection/projection_compiler.py
        │                 build_desktop_status_board_integration_from_runtime()
        ▼
Desktop consumption       core/desktop_consumption_adapter.py
adapter                   adapt_integration_payload() → DesktopClientViewModel
        │
        ▼
Topology layout           windows_client/status_board_v2/topology_layout.py
                          build_constellation_layout() → TopologyConstellationLayout
        │
        ▼
Topology renderer         windows_client/status_board_v2/topology_renderer.py
                          TopologyRenderer.render_layout()
        │
        ▼
Diagnostics inspector     windows_client/status_board_v2/topology_inspector.py
                          TopologyInspector.inspect_layout() → InspectionReport
        │
        ▼
Observability / history   windows_client/status_board_v2/topology_history.py
                          TopologyHistoryRecorder → TopologyHistoryEntry / TopologySnapshot
```

---

## Layer-by-layer reference

### Layer 0 — Server contract (PR-4 through PR-7)

**Module:** `contracts/desktop_status_projection.py`

| Symbol | Description |
|--------|-------------|
| `DesktopStatusProjection` | Top-level projection assembled by the server |
| `DesktopTopologyProjection` | Topology-specific sub-projection (PR-6) |
| `ModelRoutingProjection` | Routing/provider information (PR-5 demoted legacy flag) |
| `OneAPIStatusSummary` | OneAPI lower-horizon integration summary (PR-4) |
| `TOPOLOGY_PROJECTION_DELIVERY_AUTHORITY` | Server-side projection authority sentinel |
| `PROJECTION_CONTRACT_AUTHORITY` | Contract-layer authority sentinel |

**Key invariants:**
- `oneapi_integration` is always present and always lower-horizon only.
- `projection_quality.topology_readiness` carries readiness semantics.
- `legacy_routing_fallback_active` on `ModelRoutingProjection` is always
  explicit; never silently removed.

---

### Layer 1 — Integration bridge (PR-8)

**Module:** `core/projection/projection_compiler.py`

| Symbol | Description |
|--------|-------------|
| `build_desktop_status_board_integration_from_runtime()` | Bridge: `RuntimeProjection` → `DesktopStatusBoardIntegrationPayload` |
| `DesktopStatusBoardIntegrationPayload` | Integrated payload (in `contracts/desktop_status_projection.py`) |
| `.readiness` | Shorthand for `authority_indicators["topology_readiness"]` |
| `.is_canonical` | Shorthand for `authority_indicators["topology_authoritative"]` |
| `DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY` | Bridge authority sentinel |

**Key invariants:**
- The bridge never strips or promotes readiness semantics.
- `authority_indicators` keys are always present with explicit values.

---

### Layer 2 — Desktop consumption adapter (PR-9)

**Module:** `core/desktop_consumption_adapter.py`

| Symbol | Description |
|--------|-------------|
| `adapt_integration_payload()` | Converts payload → `DesktopClientViewModel` |
| `DesktopClientViewModel` | Flat, easy-to-consume desktop view model |
| `DesktopReadinessState` | Enum: `canonical` / `degraded` / `partial` / `unavailable` / `unknown` |
| `DesktopProviderRoutingSummary` | Flat routing/provider summary |
| `DesktopOneAPIHorizonSummary` | Flat OneAPI lower-horizon summary |
| `DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY` | Adapter authority sentinel |

**Key invariants:**
- `.is_canonical`, `.is_degraded`, `.is_partial`, `.is_unavailable` are always
  explicit; never derive one from another implicitly.
- `.topology_legacy_fallback_active` and `.routing_legacy_fallback_active` are
  never hidden.
- `.oneapi_is_lower_horizon_only` is **always `True`**.
- The adapter never raises on minimal or `None` input.

**Intended primary consumption path:**

```python
from core.desktop_consumption_adapter import adapt_integration_payload
from core.projection import build_desktop_status_board_integration_from_runtime

payload = build_desktop_status_board_integration_from_runtime(
    continuum_state=state, route_plan=plan
)
vm = adapt_integration_payload(payload)

if vm.is_canonical:
    print("Routing is fully canonical")
elif vm.is_degraded:
    print("WARNING: legacy fallback active — NOT authoritative")
elif vm.is_partial:
    print("INFO: partial data available")
else:
    print("Topology unavailable")
```

---

### Layer 3 — Topology layout (PR-11)

**Module:** `windows_client/status_board_v2/topology_layout.py`

| Symbol | Description |
|--------|-------------|
| `build_constellation_layout()` | Builds `TopologyConstellationLayout` from `DesktopClientViewModel` |
| `TopologyConstellationLayout` | Layered constellation layout |
| `TopologyLayoutLayer` | A single layer (primary / support / lower_horizon) |
| `TopologyLayoutNode` | A layout node (provider, peer, OneAPI, etc.) |
| `TopologyLayoutRelation` | A directed relation between nodes |
| `TopologyNodeKind` | Enum: node kinds (`primary_provider`, `peer_provider`, `support_path`, `oneapi_horizon`, `unknown`) |
| `TopologyRelationKind` | Enum: relation kinds (`canonical_route`, `support_link`, `fallback_path`, `lower_horizon_link`, `unknown`) |
| `TopologyLayerKind` | Enum: layer kinds (`primary`, `support`, `lower_horizon`) |
| `TOPOLOGY_LAYOUT_AUTHORITY` | Layout authority sentinel |

**Key invariants:**
- OneAPI nodes are **always** placed in the `lower_horizon` layer — never in
  `primary` or `support`.
- `lower_horizon_link` relations are **never** promoted to `canonical_route`.
- A degraded/partial/unavailable layout carries `is_authoritative = False`.
- `build_constellation_layout(None)` never raises.

---

### Layer 4 — Topology renderer (PR-12)

**Module:** `windows_client/status_board_v2/topology_renderer.py`

| Symbol | Description |
|--------|-------------|
| `TopologyRenderer` | Renders `TopologyConstellationLayout` to human-readable text |
| `render_layout()` | Full layout render |
| `render_layout_dict()` | Render from a plain dict snapshot |
| `TOPOLOGY_RENDERER_AUTHORITY` | Renderer authority sentinel |

**Key invariants:**
- Degraded / partial / unavailable layouts are **visually distinct** from
  canonical layouts — never rendered as authoritative.
- OneAPI is rendered in the lower-horizon section — never presented as a
  canonical routing peer.
- Node-kind symbols: `★` primary, `✧` peer, `◇` support, `⬡` OneAPI.
- Edge symbols: `━━▶` canonical, `╌╌▷` fallback, `──▷` support,
  `╌╌⬡` lower-horizon.
- `render_layout(None)` never raises and produces an "unavailable" string.

---

### Layer 5 — Diagnostics inspector (PR-13)

**Module:** `windows_client/status_board_v2/topology_inspector.py`

| Symbol | Description |
|--------|-------------|
| `TopologyInspector` | Main inspection surface |
| `inspect_layout()` | Full `InspectionReport` from a layout |
| `inspect_node()` | Drill into a specific node |
| `inspect_relation()` | Drill into a specific relation |
| `inspect_readiness()` | Readiness/authority detail only |
| `inspect_oneapi()` | OneAPI lower-horizon detail only |
| `inspect_routing_summary()` | Routing/provider summary |
| `inspect_from_view_model()` | Full report from `DesktopClientViewModel` |
| `NodeInspectionDetail` | Single-node diagnostic view |
| `RelationInspectionDetail` | Single-relation diagnostic view |
| `ReadinessInspectionDetail` | Readiness/authority interpretation |
| `RoutingInspectionDetail` | Routing/provider summary detail |
| `OneAPIInspectionDetail` | OneAPI lower-horizon diagnostics (always `is_lower_horizon_only=True`) |
| `InspectionReport` | Complete diagnostics report |
| `TOPOLOGY_INSPECTOR_AUTHORITY` | Inspector authority sentinel |

**Key invariants:**
- `OneAPIInspectionDetail.is_lower_horizon_only` is **always `True`**.
- Degraded nodes have `is_authoritative = False` in `NodeInspectionDetail`.
- `fallback_path` relations have `is_fallback = True` and
  `is_authoritative = False`.
- `inspect_layout(None)` never raises; returns an unavailable `InspectionReport`.
- `InspectionReport.to_dict()` / `.to_json()` are always JSON-serialisable.

---

### Layer 6 — Observability / history (PR-14)

**Module:** `windows_client/status_board_v2/topology_history.py`

| Symbol | Description |
|--------|-------------|
| `TopologyHistoryRecorder` | Main observability surface |
| `record_from_inspection_report()` | History entry from `InspectionReport` |
| `record_from_layout()` | History entry from `TopologyConstellationLayout` |
| `record_from_view_model()` | History entry from `DesktopClientViewModel` |
| `snapshot_from_inspection_report()` | Point-in-time snapshot from `InspectionReport` |
| `snapshot_from_layout()` | Snapshot from layout |
| `snapshot_from_view_model()` | Snapshot from view model |
| `compare_snapshots()` | Produce a diff between two snapshots |
| `stability_summary()` | Stability summary over a `TopologyHistoryBuffer` |
| `TopologyHistoryBuffer` | Bounded in-memory entry buffer |
| `TopologyHistoryEntry` | Single timestamped change record |
| `TopologySnapshot` | Point-in-time topology state snapshot |
| `ReadinessTransitionRecord` | Readiness state transition record |
| `AuthorityChangeRecord` | Authority change record |
| `RoutingChangeRecord` | Provider/routing change record |
| `OneAPIHistorySummary` | OneAPI lower-horizon historical summary |
| `TopologyChangeKind` | Observable change event type enum |
| `TOPOLOGY_HISTORY_AUTHORITY` | History authority sentinel |

**Key invariants:**
- `OneAPIHistorySummary.is_lower_horizon_only` is **always `True`** in all
  historical views.
- Degraded / fallback history entries are **never** re-promoted to
  authoritative truth (`is_authoritative` is preserved from the source record).
- `TopologySnapshot.stability_indicator` maps to `"stable"` / `"degraded"` /
  `"unavailable"` / `"partial"` based on the source readiness state.
- All recorder paths handle `None` / missing inputs gracefully (return `None`
  for entries, return an unavailable snapshot).
- `TopologyHistoryEntry.to_dict()` / `.to_json()` and
  `TopologySnapshot.to_dict()` / `.to_json()` are always JSON-serialisable.

---

## Semantic state reference

The four readiness states flow coherently across **all seven layers**:

| State | `is_authoritative` | Description |
|-------|--------------------|-------------|
| `canonical` | `True` | Routing is fully canonical; no legacy fallback active |
| `degraded` | `False` | Legacy fallback active; data is **not** authoritative truth |
| `partial` | `False` | Some components unavailable; limited data only |
| `unavailable` | `False` | No topology data available |

**Critical rule:** A `degraded`, `partial`, or `unavailable` state must never
be re-promoted to `canonical` / `is_authoritative = True` at any layer.

---

## OneAPI lower-horizon invariant

OneAPI is structurally distinct and lower-horizon only throughout the entire
pipeline:

| Layer | Enforcement |
|-------|-------------|
| Server contract | `oneapi_integration` is always a distinct sub-field, never a routing peer |
| Adapter | `oneapi_is_lower_horizon_only` is always `True` on `DesktopClientViewModel` |
| Layout | OneAPI node always in `lower_horizon` layer; never in `primary` or `support` |
| Renderer | OneAPI rendered in lower-horizon section only; never as canonical routing peer |
| Inspector | `OneAPIInspectionDetail.is_lower_horizon_only` is always `True` |
| History | `OneAPIHistorySummary.is_lower_horizon_only` is always `True` |

**Why:** OneAPI is a lower-horizon aggregation/integration point, not a
canonical routing peer.  Treating it as a peer would corrupt readiness
semantics and misrepresent the system's routing authority.

---

## How readiness and authority should be interpreted

1. **Always read `is_canonical` / `is_degraded` / `is_partial` /
   `is_unavailable` from the adapter** (`DesktopClientViewModel`) as the
   primary readiness signal.

2. **Never infer readiness from raw nested payload keys.**  Use the adapter
   output or the inspector's `ReadinessInspectionDetail` as your
   interpretation layer.

3. **Degraded data is explicitly marked and must never be treated as
   authoritative.**  Every layer carries explicit `is_authoritative` flags.

4. **Authority change is always visible** — `ReadinessTransitionRecord` in the
   history layer records every transition between authoritative and
   non-authoritative states.

5. **Stability over time** can be assessed using
   `TopologyHistoryRecorder.stability_summary()` over a
   `TopologyHistoryBuffer`.

---

## Intended consumption path (summary)

```python
# Step 1: Build integration payload (server-side or via bridge)
from core.projection import build_desktop_status_board_integration_from_runtime
payload = build_desktop_status_board_integration_from_runtime(
    continuum_state=state, route_plan=plan
)

# Step 2: Adapt to flat view model (PR-9)
from core.desktop_consumption_adapter import adapt_integration_payload
vm = adapt_integration_payload(payload)

# Step 3: Build constellation layout (PR-11)
from windows_client.status_board_v2 import build_constellation_layout
layout = build_constellation_layout(vm)

# Step 4: Render for display (PR-12)
from windows_client.status_board_v2 import TopologyRenderer
print(TopologyRenderer().render_layout(layout))

# Step 5: Inspect for diagnostics (PR-13)
from windows_client.status_board_v2 import TopologyInspector
report = TopologyInspector().inspect_layout(layout)
print(report.readiness.readiness_label)    # "canonical" / "degraded" / etc.

# Step 6: Record history and assess stability (PR-14)
from windows_client.status_board_v2 import (
    TopologyHistoryRecorder, TopologyHistoryBuffer,
)
recorder = TopologyHistoryRecorder()
buf = TopologyHistoryBuffer(max_size=50)
entry = recorder.record_from_inspection_report(report)
if entry:
    buf.add_entry(entry)
summary = recorder.stability_summary(buf)
print(summary["overall_stability"])  # "stable" / "mostly_stable" / "unstable"
```

---

## What is canonical vs degraded vs fallback

| Term | Meaning |
|------|---------|
| **Canonical** | The topology routing is authoritative; no legacy fallback is active; `is_canonical = True` and `is_authoritative = True` throughout all layers |
| **Degraded** | Legacy fallback is active; the routing data is **not** authoritative; `is_degraded = True`, `is_authoritative = False`; must never be promoted |
| **Partial** | Some components have data, others do not; `is_partial = True`, `is_authoritative = False` |
| **Unavailable** | No topology data is available; `is_unavailable = True`, `is_authoritative = False` |
| **Fallback relation** | A `TopologyLayoutRelation` of kind `fallback_path`; always `is_fallback = True` and `is_authoritative = False` |

---

## How future contributors should avoid bypassing the pipeline

1. **Never read raw nested payload dicts** directly from
   `DesktopStatusBoardIntegrationPayload` to determine readiness or authority.
   Always pass the payload through `adapt_integration_payload()` first.

2. **Never build layouts from anything other than `DesktopClientViewModel`.**
   The `build_constellation_layout()` function accepts only an adapter
   view-model (or `None`).

3. **Never promote `is_authoritative = False` data to authoritative status.**
   If the source has `is_degraded = True`, all downstream layers must also
   carry `is_authoritative = False`.

4. **Never place OneAPI in the primary or support layer.**  OneAPI always
   belongs in the `lower_horizon` layer.

5. **Never bypass the inspector or history layers for serialisation.**
   Use `InspectionReport.to_dict()` / `.to_json()` and
   `TopologyHistoryEntry.to_dict()` / `.to_json()` for all log/persistence use
   cases.  These paths are tested for JSON-serialisability.

6. **Always use the authority sentinels** to confirm that a record was
   produced by the canonical PR-14 recorder / PR-13 inspector / etc., not
   assembled ad-hoc.

---

## PR-15: Hardening and closure milestone

PR-15 completes the multi-PR initiative by adding:

1. **End-to-end test coverage** (`tests/test_pr15_e2e_hardening.py`, 100
   tests) — proves that the full pipeline works coherently for all four
   semantic states and that all semantic invariants hold end-to-end.

2. **Strong regression protection** — tests cover:
   - canonical / degraded / partial / unavailable semantics are consistent
     across all layers;
   - degraded/fallback data is never promoted to authoritative truth;
   - OneAPI is lower-horizon only at every layer;
   - historical/inspection/rendering outputs remain semantically aligned;
   - `None` / empty / unavailable paths are safe and serialisable.

3. **Documentation closure** — this document (`DESKTOP_PIPELINE_ARCHITECTURE.md`)
   consolidates the full post-PR-15 architecture description, intended
   consumption path, and contributor guidance.

4. **Package surface verification** — all PR-9 through PR-14 public symbols
   are confirmed as exported from `windows_client.status_board_v2`.

---

## Related documents

| Document | Description |
|----------|-------------|
| [`docs/STATUS_BOARD_V2.md`](STATUS_BOARD_V2.md) | Main Status Board V2 design and usage guide |
| [`docs/OBSERVABILITY_HISTORY.md`](OBSERVABILITY_HISTORY.md) | PR-14 observability and history layer |
| [`docs/DIAGNOSTICS_INSPECTION_INTERACTION.md`](DIAGNOSTICS_INSPECTION_INTERACTION.md) | PR-13 diagnostics and inspection interaction layer |
| [`docs/TOPOLOGY_RENDERING_VISUAL_SEMANTICS.md`](TOPOLOGY_RENDERING_VISUAL_SEMANTICS.md) | PR-12 topology rendering and visual semantics polish |
| [`docs/TOPOLOGY_CONSTELLATION_LAYOUT.md`](TOPOLOGY_CONSTELLATION_LAYOUT.md) | PR-11 topology / constellation layout foundation |
| [`docs/DESKTOP_STATUS_BOARD_UI.md`](DESKTOP_STATUS_BOARD_UI.md) | PR-10 first usable adapter-driven status board UI surface |
| [`docs/DESKTOP_CONSUMPTION_ADAPTER.md`](DESKTOP_CONSUMPTION_ADAPTER.md) | PR-9 desktop consumption adapter |
| [`docs/SERVER_SIDE_CANONICALIZATION.md`](SERVER_SIDE_CANONICALIZATION.md) | PR-5/PR-6 server-side canonicalization |
| [`docs/ONEAPI_SYSTEM_POSITION.md`](ONEAPI_SYSTEM_POSITION.md) | PR-4 OneAPI lower-horizon position rationale |
| [`docs/DESKTOP_DISPLAY_BOUNDARIES.md`](DESKTOP_DISPLAY_BOUNDARIES.md) | Canonical display boundary contract |
