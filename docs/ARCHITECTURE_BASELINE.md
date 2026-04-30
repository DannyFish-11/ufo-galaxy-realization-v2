# Architecture Baseline — Terminal State After PR-011

> Produced by **PR-010 Consolidation**.  Summarises the Galaxy architecture
> baseline after the PR-001 through PR-009 sequence.  This document is the
> single authoritative reference for canonical paths, authority chain,
> legacy policy, and completion evaluation.
>
> **PR-9 addendum**: Section 0 (Canonical Runtime Layer Model) was added by
> PR-9 (Normalize canonical runtime architecture declarations across layers)
> to resolve split-brain declarations and establish a single coherent
> architecture story across all layers.
>
> **PR-11 addendum**: Section 9 (Final Architecture Convergence) was added by
> PR-11 (Final architecture convergence — capstone convergence pass after
> PR-6 through PR-10).  PR-11 completes the architecture alignment sequence by
> consolidating residual edge inconsistencies, strengthening final boundary
> clarity, and confirming the repository presents one coherent terminal
> architecture state.  The machine-checkable convergence surface is
> `core.final_architecture_convergence`.

---

## 0. Canonical Runtime Layer Model (PR-9)

The Galaxy system defines **five canonical runtime layers**.  Each layer has a
distinct scope, a set of canonical modules, and one or more "NOT" boundary
invariants that prevent split-brain declarations.

```
┌─────────────────────────────────────────────────────────────────────┐
│  Layer 5 — Startup / Readiness / Health / Release Integrity (V6)    │
│  core.release_blocking_gate                                         │
│  NOT a per-request runtime gate                                     │
└────────────────────────────┬────────────────────────────────────────┘
                             │ CI / startup only
┌────────────────────────────▼────────────────────────────────────────┐
│  Layer 4 — Multi-Step Orchestration Spine (V4)                      │
│  core.unified_orchestration_spine                                   │
│  NOT the universal synchronous per-request gate                     │
└────────────────────────────┬────────────────────────────────────────┘
                             │ complex sessions only
┌────────────────────────────▼────────────────────────────────────────┐
│  Layer 3 — Per-Request Hot Path                                     │
│  core.openclawd → core.agent.kernel → core.command_router           │
│  Exercised on every synchronous request                             │
└────────────────────────────┬────────────────────────────────────────┘
                             │ LLM calls via UnifiedLLMRouter
┌────────────────────────────▼────────────────────────────────────────┐
│  Layer 2 — Router-Level Cognitive Authority (L1/L2/L3)              │
│  L1: core.llm.route_authority   (route selection)                   │
│  L2: core.llm.supply_authority  (supply/availability legality)      │
│  L3: core.llm.context_authority (context enrichment/governance)     │
│  Facade: core.unified.llm_router.UnifiedLLMRouter                  │
│  NOT a detached shadow stack                                        │
└────────────────────────────┬────────────────────────────────────────┘
                             │ completion truth enforced
┌────────────────────────────▼────────────────────────────────────────┐
│  Layer 1 — Completion Truth Backbone (V2/V5)                        │
│  core.canonical_completion_ingress                                  │
│  core.canonical_group_completion_closure (V5)                       │
│  core.durable_truth_authority_chain                                 │
│  NOT optional soft signaling                                        │
└─────────────────────────────────────────────────────────────────────┘
```

### Layer boundary invariants (split-brain prevention)

| Invariant | What it prevents |
|---|---|
| **V4 is NOT a per-request gate** | V4 (`unified_orchestration_spine`) governs multi-step orchestration sessions only.  Simple per-request execution remains on the per-request hot path (Layer 3). |
| **V6 is NOT a per-request gate** | V6 (`release_blocking_gate`) is evaluated at CI time and system startup, never inserted into the synchronous request path. |
| **L1/L2/L3 belongs to the router layer** | L1/L2/L3 is fused into `UnifiedLLMRouter`; it is NOT a detached shadow stack running independently alongside the hot path. |
| **Completion truth is enforced** | Completion truth (`CanonicalCompletionIngress` + V5 closure) is NOT optional soft signaling; callers must use the canonical backbone. |

The canonical layer model is machine-checkable via:
- `core.canonical_layer_model.run_layer_model_invariants()`
- `tools.architecture.architecture_invariants.check_canonical_layer_model_consistent()`
- `tools.architecture.architecture_invariants.run_consolidation_invariants()` (always includes the layer model check)

---

## 1. Primary Authority Chain

The canonical runtime authority chain is fixed and must not be violated:

```
DesktopPresenceRuntime   ← runtime_shell_authority
        │
        ▼
  OpenClawd              ← subject_decision_authority
        │
        ▼
  AgentKernel            ← cognition_planning_layer
        │
        ▼
  CommandRouter          ← execution_substrate
```

### Layer responsibilities

| Layer | Canonical module | Authority role label | Responsibility |
|---|---|---|---|
| Runtime shell | `core.desktop_presence_runtime` | `runtime_shell_authority` | Top-level entry; owns lifecycle, session, source registry |
| Subject / routing authority | `core.openclawd` | `subject_decision_authority` | **Primary subject/routing decision authority**; owns multimodal routing, operator overrides, projection assembly |
| Cognition / planning | `core.agent.kernel` | `cognition_planning_layer` | LLM planning only; **not** final authority |
| Execution substrate | `core.command_router` | `execution_substrate` | **Canonical router** for cross-device execution; owns remote-mode resolution |

> **Invariant**: OpenClawd is the primary subject/routing decision authority.
> AgentKernel is cognition/planning only — it does not have final authority.
> CommandRouter is the canonical router; it is not an authority layer.

---

## 2. Canonical Execution Paths

### Local execution
```
DesktopPresenceRuntime
  → OpenClawd._select_multimodal_route()
  → AgentKernel.run()
  → CommandRouter.route_envelope()   [LOCAL_MANIFESTATION]
```

### Remote / cross-device execution
```
DesktopPresenceRuntime
  → OpenClawd
  → CommandRouter                    [REMOTE_COMMAND | REMOTE_AGENT]
  → CrossDeviceChainSingleton        (records canonical 7-step chain)
```

Cross-device execution follows the canonical 7-step chain defined in
`core.cross_device_execution_chain.CanonicalChainStep`.

### Fallback / degraded execution
Fallback decisions flow through `UnifiedExecutionDecision` and
`FallbackDecisionRecord` (see `core.schemas.unified_control_plan`).
The fallback ladder is described in `core.degraded_operation_envelope`.

---

## 3. Projection-Only Outward Model

**Projection is the sole outward-facing truth for system status.**

```
core.routes.projection (GET /api/v1/projection/runtime)
        │
        ▼
contracts.desktop_status_projection (DesktopStatusProjection)
        │
        ▼
windows_client.status_board_v2      [PROJECTION_DRIVEN — canonical UI]
```

### Policy

- UI surfaces must consume projection output.
- UI surfaces must **not** maintain parallel state.
- UI surfaces must **not** reconstruct truth independently.
- `dashboard/` and `windows_client/` (other than `status_board_v2`) are
  **legacy compatibility surfaces**, not primary architecture.

This policy is enforced by:
- `core.ui_surface_authority.UISurfaceAuthorityRegistry`
- `core.architecture_truth_guards.CanonicalTruthOwnershipGuard
  .assert_projection_does_not_reconstruct_truth()`
- `core.architecture_diagnostics.ArchitectureDiagnostics
  .check_projection_metadata_coherent()` *(added PR-010)*

---

## 4. Addon / Package Contract Principles

GitHub-installable addons follow two canonical contract types:

| Type | Module | Description |
|---|---|---|
| `mcp_addon` | `core.mcp_addon_contract` | MCP server addon; GitHub-installable; carries `entry_point`, `required_capabilities` |
| `skill_package` | `core.skill_package_contract` | Skill package; GitHub-installable; carries `skill_id`, `version`, `capabilities` |

### Install flow
```
GitHub URL  →  installer/  →  core.mcp_loader / core.skill_loader
                            →  CapabilityManager (canonical catalog)
                            →  capability registration
```

All addon installs must flow through the canonical install contracts and
capability registration path.  Direct loader calls that bypass the capability
catalog are **legacy paths** and should be migrated.

---

## 5. Legacy Compatibility Policy

### What "legacy" means

A surface, module, or path is **legacy** when it:
- Was the primary entry point before a canonical successor was defined.
- Is kept only for backward compatibility.
- Carries a `legacy_compatibility`, `LEGACY_UI`, `LEGACY_SHELL`,
  `compatibility_fallback`, or `deprecated` label.

### Current legacy surfaces

| Surface | Role label | Superseded by |
|---|---|---|
| `dashboard/` | `LEGACY_UI` | `windows_client.status_board_v2` |
| `windows_client/` (except `status_board_v2`) | `LEGACY_SHELL` | `windows_client.status_board_v2` |
| `galaxy_gateway.orchestrator.GalaxyOrchestrator` | `legacy_compatibility` | `core.command_router` |
| `galaxy_gateway.orchestrator.TaskOrchestrator` | `legacy_compatibility` | `core.e2e_orchestrator` |
| `galaxy_gateway.device_router.DeviceRouter.route_task` | `legacy_compatibility` | `core.command_router` |
| `galaxy_gateway.cross_device_coordinator.CrossDeviceCoordinator` | `legacy_compatibility` | `core.cross_device_execution_chain` |

### Policy for legacy paths

1. Legacy paths must carry a `LEGACY PATH GUARDRAIL` log warning when called.
2. Legacy paths must carry a `superseded_by` pointer to the canonical replacement.
3. Legacy paths must not be called by new code.
4. Legacy paths may be removed once all callers have been migrated.

Legacy-path metadata is maintained in:
- `core.orchestration_authority.legacy_paths.LEGACY_PATH_REGISTRY`
- `core.ui_surface_authority.UISurfaceAuthorityRegistry`

---

## 6. Shared Architectural Constants (PR-010)

`core.architecture_invariants` is the **single source of truth** for the
canonical string labels, cross-cutting invariant checks, and vocabulary
definitions used across diagnostics, scorecards, projection metadata, and
capability registries.

Key constants:

| Constant | Description |
|---|---|
| `CANONICAL_AUTHORITY_LABELS` | Frozenset of valid authority-role string labels |
| `LEGACY_BOUNDARY_LABELS` | Frozenset of legacy/compatibility boundary labels |
| `PROJECTION_TRUTH_MARKERS` | Frozenset of canonical projection outward-truth markers |
| `AUTHORITY_CHAIN` | Ordered tuple of `(layer_key, expected_role)` pairs |
| `CANONICAL_ADDON_CONTRACT_TYPES` | Known canonical MCP/Skill contract type identifiers |

Cross-cutting invariant checks:
- `check_authority_labels_consistent()`
- `check_canonical_legacy_markers_uniform()`
- `check_projection_is_outward_truth()`
- `check_addon_contract_metadata_uniform()`
- `run_consolidation_invariants()` — aggregates all four checks

---

## 7. How to Evaluate Completion Using the Scorecard

The architecture completion scorecard is exposed by
`core.architecture_completion.get_architecture_completion_scorecard()`.

### 10 evaluation dimensions

| # | Dimension | Current maturity |
|---|---|---|
| 1 | `authority_clarity` | CANONICALIZED |
| 2 | `canonical_path_coverage` | CANONICALIZED |
| 3 | `legacy_surface_demotion` | CANONICALIZED |
| 4 | `contract_schema_normalization` | CANONICALIZED |
| 5 | `capability_integration_completeness` | PARTIAL *(legacy ambiguity)* |
| 6 | `projection_outward_truth_alignment` | CANONICALIZED |
| 7 | `cross_device_execution_consistency` | CANONICALIZED |
| 8 | `installability_ecosystem_readiness` | PARTIAL *(legacy ambiguity)* |
| 9 | `diagnostics_observability_maturity` | COMPLETE |
| 10 | `test_coverage_architecture_invariants` | COMPLETE |

### Maturity levels

| Level | Meaning | Blocks release? |
|---|---|---|
| `LEGACY_AMBIGUITY` | No canonical path; legacy still primary | Yes |
| `IN_PROGRESS` | Canonical path started; not yet complete | Yes |
| `PARTIAL` | Canonical path exists; legacy ambiguity remains | No |
| `CANONICALIZED` | Canonical path established; legacy demoted | No |
| `COMPLETE` | Fully canonicalized + validated + tested | No |

### How to use the scorecard

```python
from core.architecture_completion import get_architecture_completion_scorecard

scorecard = get_architecture_completion_scorecard()
print(scorecard.to_json())

# Summary
for line in scorecard.summary_lines():
    print(line)

# Blocking dimensions
for dim in scorecard.blocking_dimensions():
    print(dim.dimension, dim.maturity_level, dim.blockers)
```

---

## 8. Next Steps for Implementation Hardening

> **PR-10 (Final Legacy Purge) status**: The dead `_start_desktop()` /
> `run_ui.py` reference in `start_galaxy.py` has been removed, legacy wrapper
> scripts have been hardened, and the purge registry
> (`core/legacy_purge_registry.py`) now serves as the machine-readable audit
> log.  See `docs/LEGACY_PURGE_HARDENING.md` for the full list of purge
> decisions.

The following are the current blocking or partial dimensions and their
recommended next actions:

### capability_integration_completeness (PARTIAL)
- Audit all capability registration paths.
- Funnel remaining legacy-loader registrations through the canonical catalog.
- Add guardrail in legacy loaders pointing to the canonical catalog.

### installability_ecosystem_readiness (PARTIAL)
- Add a CI job that installs a minimal test addon from a GitHub URL.
- Enforce required contract fields at load time with a validation step.

### General hardening priorities
1. **Projection status board real integration** — wire `status_board_v2` to
   consume `GET /api/v1/projection/runtime` in all environments.
2. **Cross-device execution real-device validation** — run the canonical
   7-step chain against real connected devices.
3. **Capability catalog runtime sync** — ensure all nodes and addons register
   through the canonical catalog at startup.
4. **MCP/Skill addon installer hardening** — enforce contract field validation
   and add CI coverage for GitHub-installable packages.
5. **Cross-cutting architecture invariant monitoring** — run
   `run_consolidation_invariants()` and `run_architecture_diagnostics()` as
   part of health-check / observability endpoints.

---

## 9. Final Architecture Convergence (PR-11)

PR-11 is the capstone convergence pass for the architecture alignment sequence
(PR-6 through PR-10).  It completes the series without redesigning the runtime
by:

1. **Consolidating residual edge inconsistencies** — any naming drift, stale
   declarations, or weakly articulated boundaries left after PR-6–PR-10.
2. **Strengthening final boundary clarity** — five boundary sentinels that
   clearly name each architecture surface (per-request hot path, router
   cognitive authority, orchestration session scope, participant generic vs.
   Android concrete, startup/release integrity).
3. **Removing remaining split-brain terminology** — one coherent terminal
   architecture vocabulary enforced by importable sentinels.
4. **Refining existing validation surfaces** — the convergence checks delegate
   to `core.canonical_layer_model`, `core.terminal_architecture_audit_guards`,
   and `core.participant_authority_interfaces` rather than duplicating them.

### Five final boundary clarity sentinels (PR-11)

| Sentinel | Architecture surface |
|---|---|
| `PER_REQUEST_HOT_PATH_BOUNDARY_SENTINEL` | Every synchronous request; `OpenClawd → CommandRouter`; V4/V6 NOT inserted |
| `ROUTER_COGNITIVE_AUTHORITY_BOUNDARY_SENTINEL` | L1/L2/L3 fused into `UnifiedLLMRouter`; NOT a shadow stack |
| `ORCHESTRATION_SESSION_SCOPE_BOUNDARY_SENTINEL` | V4 = multi-step sessions only; NOT the universal per-request gate |
| `PARTICIPANT_GENERIC_VS_ANDROID_CONCRETE_BOUNDARY_SENTINEL` | `participant_authority_interfaces` above Android; Android NOT removed |
| `STARTUP_RELEASE_INTEGRITY_BOUNDARY_SENTINEL` | V6 = CI / startup; NEVER in per-request path |

### Three convergence policy sentinels (PR-11)

| Sentinel | Policy |
|---|---|
| `CONVERGENCE_PASS_DOES_NOT_REDESIGN_RUNTIME_POLICY` | PR-11 does not redesign runtime or create new layers |
| `SINGLE_COHERENT_ARCHITECTURE_STORY_POLICY` | Exactly one architecture story after PR-11 |
| `BOUNDARY_CLARITY_PRESERVED_POLICY` | All five boundary sentinels must remain importable and consistent |

### How to run the convergence checks

```python
from core.final_architecture_convergence import run_final_convergence_checks

report = run_final_convergence_checks()
print(report.overall_converged)    # True on a clean system
print(report.to_dict())
```

The convergence checks run four sub-checks:
- `BOUNDARY_SENTINEL_COMPLETENESS` — all five boundary and three policy sentinels present
- `TERMINAL_GUARD_INTEGRITY` — PR-10 terminal audit guards intact and passing
- `PARTICIPANT_LAYER_CONSISTENCY` — PR-8 participant-generic layer intact
- `CANONICAL_LAYER_MODEL_REACHABLE` — PR-9 five-layer model intact

---

*This document was produced by PR-010 (Consolidate architecture invariants
after PR-001 through PR-009), updated in PR-10 final purge/hardening
to reflect the legacy purge decisions catalogued in
`core/legacy_purge_registry.py` and `docs/LEGACY_PURGE_HARDENING.md`,
and finalized by PR-11 (Final architecture convergence — capstone convergence
pass after PR-6 through PR-10).*
