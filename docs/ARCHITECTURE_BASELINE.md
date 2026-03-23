# Architecture Baseline — Post-PR-009

> Produced by **PR-010 Consolidation**.  Summarises the Galaxy architecture
> baseline after the PR-001 through PR-009 sequence.  This document is the
> single authoritative reference for canonical paths, authority chain,
> legacy policy, and completion evaluation.

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

*This document was produced by PR-010 (Consolidate architecture invariants
after PR-001 through PR-009).*
