# Incremental Evolution Guardrails and Risk Boundaries

**Purpose:** Define the guardrails and risk boundaries that govern all future phases of V2 + Android system evolution. This document is NOT a rewrite charter, NOT a migration plan, and NOT a system redesign specification. It defines what must be protected, what enhancement patterns are allowed, and what changes are explicitly prohibited.

---

## 1. Purpose and Scope

These guardrails exist because the V2 + Android joint system is a real, running production system. Future evolution phases must add capability without breaking existing operational flows, operator observability, or device communication reliability.

**This document applies to:**
- All Phase 1 through Phase 4 work in V2 (ufo-galaxy-realization-v2)
- All Android-side changes that affect the V2↔Android protocol path
- Any new metadata, schema, annotation, or contract layer added to either repo

**This document does NOT apply to:**
- Pure documentation additions with no code impact
- Isolated test infrastructure changes with no production impact
- Hotfixes to existing bugs (subject to their own review process)

---

## 2. Mainlines to Protect

The following system components are **protected mainlines**. They must remain functional, observable, and reversible throughout all evolution phases. No phase work may cause these mainlines to degrade, lose observability, or require a non-trivial migration to restore.

### 2.1 Node_XX Capability Fabric
The 100+ `Node_XX` units are the primary capability surface of V2. They are invoked by name/capability string from the orchestrator and planner, and their initialization state gates task execution.

**Protection requirements:**
- Node initialization sequence must not be disrupted
- Capability registration in `capabilities.json` must remain the authoritative routing source until a replacement is validated end-to-end
- No node's primary execution logic may be modified as a side effect of adding semantic annotations, runtime profiles, or contract metadata
- Node startup failures must remain observable and recoverable

### 2.2 Android↔V2 Protocol Path
The WebSocket-based message exchange between Android and V2 is the only cross-device communication path. It carries capability reports, state snapshots, execution events, perception emissions, and task dispatches.

**Protection requirements:**
- WebSocket connection lifecycle must remain stable
- All existing message types (`capability_report`, `device_state_snapshot`, `device_execution_event`, `task_dispatch`, `goal_dispatch`, result uplinks) must continue to function
- Message schema extensions must be backward-compatible; new optional fields must not break existing parsers
- The Android bridge in `galaxy_gateway/android/bridge.py` must not be replaced without a validated parallel-run period

### 2.3 TaskGraphRuntime / Audit / Orchestration
The task graph runtime, audit log, and orchestration authority (residing in V2) are the execution backbone. They determine what runs, when, in what order, and what counts as success or failure.

**Protection requirements:**
- `TaskGraphRuntime` execution loop must not be modified without an explicit feature flag and parallel-run validation
- Audit log entries must not be dropped or reordered
- Orchestration authority remains on V2; no phase work may transfer orchestration decision-making to Android or to an external agent without a full authority boundary review
- Task graph state must remain inspectable through the operator dashboard at all times

### 2.4 Dashboard / Operator / Debug / Registry Surfaces
The operator dashboard, debug surfaces, and capability registry are the primary tools for system observability. If these surfaces lose signal, problems become invisible.

**Protection requirements:**
- Capability registry must continue to reflect real node state
- Dashboard surfaces must not be removed or replaced without a replacement being in production-equivalent operation
- Debug/inspect endpoints must remain functional throughout all phases
- Any new metadata added to nodes or devices must be surfaced in the operator dashboard within the same phase that introduces it

### 2.5 Lifecycle / Launcher / Config Authority
The launcher, startup sequencer, and configuration authority determine how the system comes up and what configuration is canonical.

**Protection requirements:**
- `main.py` and `unified_launcher.py` startup authority must not be fragmented across new entrypoints
- Configuration file authority (`config.json`, `.env`, `capabilities.json`) must not be silently superseded by new metadata files
- Any new config source must be explicitly registered and its authority boundary documented before it is used

---

## 3. Layers Allowed for Enhancement (Not Replacement)

The following layers may be enhanced incrementally. Enhancement means adding new fields, new metadata files, new annotation layers, or new parallel paths — without removing or replacing existing functionality.

| Layer | Allowed enhancement |
|-------|-------------------|
| **Node metadata / annotations** | Add `node_semantic_roles.json` or equivalent; annotate nodes with semantic role fields. Do NOT modify node execution code. |
| **capability_report message** | Add optional new fields for richer capability declaration. Existing fields must remain unchanged. |
| **device_state_snapshot message** | Add optional new fields for richer state reporting. Existing fields must remain unchanged. |
| **device_execution_event message** | Add optional new fields for richer truth publication. Existing fields must remain unchanged. |
| **capabilities.json** | Add new capability strings or new metadata fields. Do NOT remove or rename existing capability strings that are used in routing. |
| **Operator dashboard** | Add new panels, metrics, or metadata views. Do NOT remove existing status views. |
| **Android perception pipeline** | Add new perception emission types or enrich existing payloads. Do NOT change the WebSocket connection lifecycle. |
| **Audit log** | Add new event types. Do NOT modify the structure of existing event types. |

---

## 4. Explicitly Prohibited Destructive Changes

The following changes are explicitly prohibited in all phases unless a full authority boundary review is conducted and explicitly approved:

1. **Removing or renaming existing `Node_XX` files** without a validated replacement node in production-equivalent operation for at least one full release cycle.

2. **Changing the WebSocket message type strings** (`capability_report`, `device_state_snapshot`, `device_execution_event`, etc.) — these are de facto protocol constants used by both repos.

3. **Replacing `capabilities.json` as the routing source** without a parallel-run validation showing the new source produces identical routing decisions.

4. **Modifying `TaskGraphRuntime` execution loop logic** without a feature flag that allows instant rollback to prior behavior.

5. **Moving orchestration authority to Android** or to any external service without an explicit authority boundary review document and PR.

6. **Silently adding new config authority sources** (new JSON files, environment variables, remote config) that override existing config without documentation and operator visibility.

7. **Removing audit log entries** or restructuring audit log schemas in ways that break existing log consumers (dashboards, analysis scripts).

8. **Deleting or disabling operator debug endpoints** without a replacement that provides equivalent observability.

9. **Adding blocking I/O or synchronous network calls** to node initialization paths — this can silently delay or deadlock startup.

10. **Cross-repo breaking changes without a joint migration plan** — any change that requires coordinated deployment of both V2 and Android must be explicitly documented and have a rollback procedure.

---

## 5. Authority and Canonical Source Boundaries

| Domain | Authoritative source | Must NOT be superseded by |
|--------|---------------------|--------------------------|
| Task decomposition and planning | V2 `Node_56_Planning` + `TaskGraphRuntime` | Android local planner |
| Capability routing | `capabilities.json` | Semantic annotation JSON alone |
| Node startup order | Phase group config in `main.py` / `unified_launcher.py` | New metadata files |
| Device identity | V2 device registry | Android-side self-assignment |
| Execution truth | `device_execution_event` uplink from Android | V2-side inference alone |
| Configuration authority | `config.json` + `.env` | New phase-specific config files |
| Memory / context | `Node_80_MemorySystem` | Temporary per-request state |
| Operator observability | Dashboard + audit log | Logging-only side channels |

---

## 6. Fallback Rules

### 6.1 Old Path Retention
When a new execution path is introduced (new routing logic, new capability matching, new protocol fields), the old path must remain active and reachable. The new path is additive until validated.

### 6.2 Feature Flags
All new behaviors that change:
- Task dispatch routing
- Capability matching logic
- Protocol message handling
- Node invocation order

…must be introduced behind a feature flag. The flag default must be `disabled` (off by default) until end-to-end validation is complete.

### 6.3 Compatibility Switches
Message schema extensions must use optional fields with backward-compatible defaults. Receivers must not fail on unrecognized optional fields. Senders must not require receivers to understand new fields for correct baseline operation.

### 6.4 Graceful Degradation
If a new semantic layer (annotations, runtime profiles, contract enforcement) is unavailable at runtime, the system must fall back to the existing capability-string-based routing and name-based node invocation. The absence of a semantic layer must not cause task execution to fail.

---

## 7. PR Design Rules

All PRs that affect V2 or the Android↔V2 protocol must include an explicit statement of the following in their description:

### 7.1 Single Responsibility
Each PR must make exactly one type of change. Mixed PRs (code + docs + schema + test) are not allowed unless the changes are logically inseparable and their separation would leave the system in an invalid state.

### 7.2 Explicit Change Statement
Every PR description must state:
- **What changes:** The specific files, fields, or behaviors that are modified
- **What does NOT change:** Explicit confirmation that protected mainlines (Section 2) are unaffected
- **Fallback path:** How the system behaves if the new code is disabled or rolled back
- **Validation method:** How the author verified the change does not break existing flows (test, manual run, parallel validation)

### 7.3 Breaking Change Declaration
If a PR introduces any change that could break an existing consumer (dashboard, Android client, capability router, audit log consumer), it must:
1. Label the PR with `breaking-change`
2. Include a migration guide in the PR description
3. Include a rollback procedure

---

## 8. Risk List

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| Semantic annotation JSON silently supersedes capabilities.json routing | Medium | High | Explicitly document authority boundary; routing must not consume annotation JSON without a validated transition |
| Node_XX execution logic modified during annotation pass | Low | High | Annotation phase (Phase 1-1) must be documentation + config only; no node file edits |
| Android WebSocket client breaks on new optional message fields | Medium | High | Use optional fields with defaults; test against Android client before merging |
| Feature flag left enabled after validation; hard to disable | Medium | Medium | Feature flags must have an explicit sunset date and a disable procedure in the PR |
| Multiple PRs touch the same config file concurrently | High | Medium | Serialize config-authority PRs; no concurrent modifications to capabilities.json |
| Audit log schema change breaks dashboard query | Medium | High | Audit log schema changes must include a dashboard migration in the same PR |
| New metadata file creates ambiguous config authority | Medium | High | Any new config source must explicitly state its authority scope and override behavior |
| Phase 2+ runtime matching regresses routing performance | Low | High | Runtime matching must be benchmarked against baseline before enabling in production |
| Android runtime participant formalization breaks existing heartbeat flow | Low | High | Formalization changes must pass parallel-run validation before replacing existing flow |

---

## 9. Phase-by-Phase Usage Constraints

### Phase 1 (Annotation + Inventory)
- Allowed: New documentation, new metadata config files (`node_semantic_roles.json`, capability inventory docs)
- Allowed: Minimal registry exposure enhancements (read-only, not modifying node execution)
- NOT allowed: Modifying node execution logic, modifying WebSocket message structure, modifying startup sequence

### Phase 2 (Schema + Profile)
- Allowed: New schema files (`RuntimeCapabilityProfile`, `StateSurfacePack`), schema validation tooling
- Allowed: Extending `capability_report` with optional new fields (backward-compatible)
- NOT allowed: Making new fields mandatory in `capability_report`, replacing `capabilities.json` routing without parallel-run validation

### Phase 3 (Contract + Matching)
- Allowed: New `NodeContract` definitions, runtime matching logic (behind feature flag), contract validation tooling
- Allowed: Adding contract metadata to nodes (config-level, not code-level)
- NOT allowed: Enforcing contracts as execution gates without a full validation pass and explicit feature flag

### Phase 4 (Runtime Participant Formalization)
- Allowed: Formal Android runtime participant registration, `RuntimeCapabilityProfile` adoption, typed protocol extensions
- Allowed: Transitioning to schema-validated messages (with backward-compat fallback)
- NOT allowed: Removing old message types before all consumers have been validated on new types

---

## 10. Final Principles

1. **Enhance existing flows; do not fork them.** All evolution must travel through the existing node fabric, capability registry, and protocol path — enriched, not bypassed.

2. **Keep the system runnable at every step.** No intermediate state should require a non-trivial migration to reach a runnable system. Each phase boundary must be a shippable state.

3. **Keep the system observable at every step.** New behaviors must be visible in the operator dashboard and audit log before they are enabled in production.

4. **Keep the system reversible at every step.** Every new feature must have a documented rollback path. The default posture is: new behavior is off until explicitly enabled.

5. **Authority boundaries do not drift.** V2 owns orchestration and task graph. Android owns local execution truth and local perception. These boundaries are declared once and enforced throughout all phases. Any proposed authority boundary change requires an explicit architectural review, not a feature PR.
