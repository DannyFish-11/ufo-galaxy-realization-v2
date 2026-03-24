# Status and Statistics Ownership

> **Canonical architectural contract** — this document clarifies where
> aggregate status information, statistics, and summaries live in the Galaxy
> desktop architecture.  All surfaces, tests, and future work must respect
> these ownership boundaries.

---

## 1. Ownership Summary

| Information class | Canonical owner | Surface |
|-------------------|-----------------|---------|
| Tri-state phase label | `DesktopPresenceRuntime` | `phase_surface.py` in status board |
| Model routing topology | `TopologyRouter` / `DesktopStatusProjection.ModelRoutingProjection` | `topology_surface.py` |
| Execution summary (stage, task) | `DesktopStatusProjection.ExecutionProjection` | `device_surface.py` |
| Perception / sensor status | `DesktopStatusProjection.PerceptionProjection` | status board |
| Explainability / decision trace | `DesktopStatusProjection.ExplainabilityProjection` | status board |
| Lifecycle aggregate | `DesktopStatusProjection.LifecycleProjection` | status board |
| Local execution chain stats | `LocalExecutionChainSingleton` | `liminal_surface.py` |
| Cross-device execution chain stats | `CrossDeviceChainSingleton` | `liminal_surface.py` |
| Sandbox / speculative summary | `SimulationSummary` (liminal space mapping) | `liminal_surface.py` |
| Architecture completion scorecard | `ArchitectureCompletionScorecard` | `docs/ARCHITECTURE_COMPLETION_SCORECARD.md` |
| Architecture live status | `ArchitectureLiveStatus` | `docs/ARCHITECTURE_STATUS_SURFACE.md` |
| Routing observability metrics | `ControlLoopMetrics` / `RoutingAnalyticsSnapshot` | internal; not surfaced as a primary panel |

---

## 2. Right-Side Status Board Statistics

The status board (`windows_client/status_board_v2/`) is the **canonical home
for all operator-visible structured statistics**.  This includes:

- **Phase statistics** — the current tri-state phase value and its colour
  annotation.
- **Routing statistics** — primary model, support models, weight bars,
  route reason, routing authority.
- **Execution statistics** — execution stage, current task summary, active
  device IDs.
- **Perception statistics** — active modalities, source health, native
  multimodal flag.
- **Explainability** — route decision context, decision timeline summary.

### Format rules

Statistics in the status board are rendered as **structured fields**, not as
free-form narrative text.  Each field has a label and a value.  Aggregate
counts (e.g., number of support models, number of active devices) appear as
plain numeric values or compact bar charts.

No status board surface should render a "dashboard widget" or "metrics card"
that duplicates information already present in another surface.

---

## 3. Liminal Space Statistics

The liminal space surfaces (`liminal_surface.py`, `manifest_surface.py`) carry
only **execution-chain and simulation statistics**:

| Panel | Statistics shown |
|-------|-----------------|
| Local execution chain | `total_executions`, `canonical_executions`, `legacy_executions`, `last_step`, `is_active` |
| Cross-device execution chain | `total_executions`, `canonical_executions`, `legacy_executions`, `last_step`, `is_active` |
| Sandbox / speculative | `simulation_kind`, `is_active`, `candidate_paths`, `committed_path`, `step_count` |

These are **execution-field statistics** — they describe the internal mechanics
of the transition from `liminal` to `manifest`.  They are not operator-level
status information.

---

## 4. Aggregate / Scorecard Statistics

Architecture-wide aggregate statistics live outside the runtime display
surfaces:

| Aggregate | Location |
|-----------|----------|
| Architecture maturity / completion | `core/architecture_completion.py` + `docs/ARCHITECTURE_COMPLETION_SCORECARD.md` |
| Architecture live status | `core/architecture_live_status.py` + `docs/ARCHITECTURE_STATUS_SURFACE.md` |
| Legacy zone inventory | `core/orchestration_authority/legacy_paths.py` |
| UI surface role registry | `core/ui_surface_authority.py` |

These aggregates are available via internal APIs and are not primary display
panels in the desktop status board.  They are consumed by diagnostics,
runbooks, and architecture governance tooling.

---

## 5. What Must Not Happen

- Do not add a "statistics dashboard" panel to the status board that flattens
  all aggregate counts into a single generic metrics view.  That would
  reintroduce dashboard-era semantics.
- Do not surface execution-chain statistics (local / cross-device counts) in
  the right-side status board.  They belong in the liminal space.
- Do not surface routing topology statistics (weight bars, model counts) in
  the liminal space.  They belong in the status board.
- Do not create a parallel statistics singleton that duplicates
  `DesktopStatusProjection` fields.  The projection contract is the single
  outward truth for status presentation.

---

## 6. Cross-References

- [`docs/DESKTOP_SEMANTIC_CLOSURE.md`](DESKTOP_SEMANTIC_CLOSURE.md) — tri-state desktop semantics
- [`docs/DESKTOP_DISPLAY_BOUNDARIES.md`](DESKTOP_DISPLAY_BOUNDARIES.md) — canonical display boundary contract
- [`docs/STATUS_BOARD_V2.md`](STATUS_BOARD_V2.md) — status board design and usage guide
- [`docs/LIMINAL_SPACE_MAPPING.md`](LIMINAL_SPACE_MAPPING.md) — canonical liminal space mapping
- [`docs/ARCHITECTURE_COMPLETION_SCORECARD.md`](ARCHITECTURE_COMPLETION_SCORECARD.md) — maturity scorecard
- [`docs/ARCHITECTURE_STATUS_SURFACE.md`](ARCHITECTURE_STATUS_SURFACE.md) — live status surface
- [`contracts/desktop_status_projection.py`](../contracts/desktop_status_projection.py) — canonical projection contract
- [`core/local_execution_chain.py`](../core/local_execution_chain.py) — local chain singleton
- [`core/cross_device_execution_chain.py`](../core/cross_device_execution_chain.py) — cross-device chain singleton
- [`core/liminal_space_mapping.py`](../core/liminal_space_mapping.py) — liminal space mapping structures
