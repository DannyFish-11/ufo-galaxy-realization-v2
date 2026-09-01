# V2 + Android System Reality Overview

**Purpose:** Record the current real operating shape of the V2 + Android joint system. This document is NOT an idealized architecture diagram, NOT a rewrite proposal, and NOT a future state specification. It captures what is actually running today so that later phases can plan incremental enrichment rather than replacement.

---

## 1. Dual-Repo Role Definition

### V2 (ufo-galaxy-realization-v2) — Central Host

| Role | Description |
|------|-------------|
| **Central capability fabric** | Hosts and registers all `Node_XX` capability providers; routes requests to the correct node |
| **Task graph / runtime spine** | Owns `TaskGraphRuntime`, task decomposition, audit trail, and execution scheduling |
| **Gateway / protocol ingestion** | Normalizes incoming events from Android, desktop, and external sources through `galaxy_gateway` |
| **Orchestration / memory / fusion center** | Runs `Node_81_Orchestrator`, `Node_80_MemorySystem`, fusion layer, and cross-device coordinator |

V2 is the authoritative host. It does not merely coordinate — it is the runtime backbone against which all capability consumption, state reconciliation, and truth merging happen.

### Android (ufo-galaxy-android) — Runtime Participant

| Role | Description |
|------|-------------|
| **Runtime participant** | Connects to V2 via WebSocket; sends heartbeats, capability reports, and execution events |
| **Capability producer** | Declares its local capabilities (screen capture, accessibility, VLM, local model) via `capability_report` |
| **State producer** | Emits `device_state_snapshot` messages reflecting UI state, execution lifecycle, and readiness |
| **Action executor** | Receives `task_dispatch` / `goal_dispatch` commands and executes them locally (tap, swipe, app launch, accessibility action) |
| **Local perception contributor** | Captures screenshots, runs local OCR / VLM inference, and forwards perception payloads |
| **Execution truth publisher** | Emits `device_execution_event` and result/truth uplinks to let V2 reconcile actual outcome |

Android is not a dumb client. It has genuine runtime intelligence: local model execution, accessibility-mediated state reading, and verified truth publication. However, Android does not own the task graph or orchestration authority — those remain on V2.

---

## 2. Current System Structure

### V2 Structure (Key Modules)

```
ufo-galaxy-realization-v2/
├── nodes/                     # Node_XX capability providers (100+ nodes)
├── galaxy_gateway/            # Protocol ingestion, WebSocket handler, Android bridge
│   ├── android/               # Android-specific models, message builder, capabilities
│   ├── protocol/              # AIP v3 ingress normalization
│   └── routing/               # Device selection, dispatch, routing policy
├── fusion/                    # Unified orchestrator, topology manager, node executor
├── core/                      # Agent factory, MCP loader, skill loader, device registry
├── runtime/                   # TaskGraphRuntime, audit, scheduler
├── contracts/                 # Execution contracts, capability contracts
├── config/                    # capabilities.json, node config, feature flags
└── docs/                      # Architecture documentation
```

Key operational units:
- `Node_XX` files in `nodes/` — each node exposes one or more capabilities
- `galaxy_gateway/app.py` — FastAPI gateway entry
- `fusion/unified_orchestrator.py` — cross-node task orchestration
- `galaxy_gateway/android/bridge.py` — Android↔V2 bridge

### Android Structure (Key Modules)

```
ufo-galaxy-android/
├── app/src/main/
│   ├── service/               # GalaxyService, execution service, accessibility service
│   ├── communication/         # WebSocket client, message dispatch
│   ├── capabilities/          # Capability reporter, local model runner
│   ├── executor/              # Action executor (tap, swipe, shell)
│   └── perception/            # Screenshot capture, VLM dispatch, OCR pipeline
├── docs/
└── config/
```

Key operational units:
- `GalaxyService` — long-running Android service managing V2 connection
- `CapabilityReporter` — publishes `capability_report` on connect/change
- `ActionExecutor` — receives dispatched actions and executes them
- `PerceptionEngine` — captures and forwards perception payloads

---

## 3. Cross-Repo Critical Flows

### 3.1 capability_report
- **Direction:** Android → V2
- **Trigger:** On connection established, device capability change, or explicit refresh request
- **Content:** Device identity, declared action capabilities, perception capabilities, local model readiness, platform version
- **Consumer:** `galaxy_gateway/android/capabilities.py`, stored in device registry on V2 side
- **Current state:** Operational. Message structure defined in `galaxy_gateway/android/models.py`

### 3.2 device_state_snapshot
- **Direction:** Android → V2
- **Trigger:** Periodic heartbeat, or after significant UI state change
- **Content:** Current foreground app, accessibility tree summary, readiness flags, execution lifecycle state
- **Consumer:** V2 state reconciliation, `SSoT` (Single Source of Truth) update
- **Current state:** Operational for basic readiness; richer UI state still partially inferred

### 3.3 device_execution_event
- **Direction:** Android → V2
- **Trigger:** After each executed action or at execution phase boundary
- **Content:** Action attempted, outcome (success/fail/partial), evidence payload (screenshot, accessibility snapshot)
- **Consumer:** `TaskGraphRuntime` audit log, truth reconciliation
- **Current state:** Operational. Truth reconciliation logic in V2 merges this with expected task graph state

### 3.4 device_perception_emission
- **Direction:** Android → V2
- **Trigger:** On screenshot capture, VLM inference, or grounding completion
- **Content:** Raw screenshot bytes or encoded image, OCR / VLM output, grounding annotations
- **Consumer:** `Node_90_MultimodalVision`, `Node_113_AndroidVLM`, perception pipeline on V2
- **Current state:** Partially implemented. Screenshot forwarding is active; VLM inline inference is capability-gated

### 3.5 task/goal dispatch and result/truth uplink
- **Direction:** V2 → Android (dispatch) and Android → V2 (result uplink)
- **Dispatch content:** Task goal, action sequence, execution context, timeout policy
- **Result content:** Execution result, success/failure flags, truth evidence
- **Current state:** Core dispatch operational. Result/truth uplink is active but verification-level truth still requires multi-source reconciliation

---

## 4. Real Boundaries

### Node_XX ≠ Future Semantic Task Node
Current `Node_XX` are **capability/provider units**. They expose a named capability (OCR, shell execution, file ops, planning inference) and are invoked by the orchestrator. They are NOT:
- Semantic task nodes in an autonomous agent graph
- Self-scheduling execution units
- Direct peers to Android runtime participants

A future "semantic overlay" will annotate Node_XX with semantic roles, but that annotation layer does not change the fundamental provider/runtime nature of each node.

### Android ≠ Dumb Client
Android actively:
- Reports structured capability state
- Runs local perception and inference
- Publishes verified execution truth
- Participates in readiness gating

However, Android does NOT own:
- Task decomposition
- Orchestration policy
- Memory / context management
- Cross-node capability routing

### Current Protocol Is Still Message-Centric
All cross-repo communication is currently message-based (WebSocket + JSON). There is no shared object model, no bidirectional RPC contract, and no typed stream. This means:
- State consistency depends on message ordering and replay
- Truth reconciliation is append-log style, not transactional
- Capability matching is name/tag-based, not schema-typed

---

## 5. Current Problems and Gaps

| Area | Problem | Severity |
|------|---------|----------|
| **State consistency** | `device_state_snapshot` is eventually consistent; V2 may act on stale state | Medium |
| **Truth verification** | `device_execution_event` contains attempted-action evidence, not verified success | High |
| **Capability schema** | `capability_report` has no enforced schema version; fields may drift | Medium |
| **Android perception** | VLM inline inference is capability-gated and not always available | Medium |
| **Node semantic gap** | Node_XX have no machine-readable semantic role annotations | Medium |
| **Protocol typing** | No typed protocol contract between V2 and Android; field names inferred | High |
| **Fallback coverage** | Not all dispatch paths have explicit fallback on Android execution failure | Medium |
| **Observability** | Execution audit trail exists but cross-repo correlation is incomplete | Medium |

---

## 6. Incremental Evolution Principles

These principles govern all future changes to the V2 + Android joint system:

1. **Attach, do not replace.** New capability layers (semantic annotations, runtime profiles, contract schemas) attach to existing nodes and message flows. They do not replace `Node_XX`, `capability_report`, or the Android execution service.

2. **Enrich existing flows, not fork them.** Cross-repo message flows (`capability_report`, `device_execution_event`, etc.) should be enriched with additional fields or parallel metadata paths — not replaced with a new protocol.

3. **Preserve runnable state at each step.** Every incremental change must leave the system in a runnable, observable state. No phase should require a big-bang migration.

4. **Authority boundaries are immutable.** V2 owns orchestration, task graph, and memory. Android owns local execution truth and local perception. These boundaries do not shift in Phase 1 or Phase 2.

5. **Semantic overlay is an annotation layer.** Adding semantic roles, runtime profiles, or contract metadata is additive. It does not require refactoring node execution logic or Android service internals.

6. **Feature flags first.** Any new behavior that changes dispatch, routing, or capability matching must be behind a feature flag until validated end-to-end.

---

## 7. Later Phases Dependency Mapping

| Phase | Depends On (from this document) |
|-------|---------------------------------|
| **Phase 1-1:** Node semantic capability annotations | Section 2 (Node_XX structure), Section 4 (Node_XX ≠ semantic task node) |
| **Phase 1-2:** Android runtime capability inventory | Section 2 (Android structure), Section 3 (capability_report flow) |
| **Phase 2:** RuntimeCapabilityProfile schema | Section 3 (all cross-repo flows), Section 5 (gaps) |
| **Phase 2/3:** StateSurfacePack | Section 3.2 (device_state_snapshot), Section 5 (state consistency gap) |
| **Phase 3:** NodeContract / runtime matching | Section 4 (real boundaries), Section 6 (principles) |
| **Phase 4:** Android runtime participant formalization | Section 1 (dual-repo role definition), Section 3 (all flows) |

---

## 8. Summary

The V2 + Android joint system is a real, running two-component architecture. V2 is the central capability fabric, task runtime, and orchestration authority. Android is a genuine runtime participant with local execution, perception, and truth publication capabilities.

The path forward is **incremental semantic enrichment**: annotate what exists, add typed metadata, fill in schema gaps, and extend verification coverage — without replacing the message-centric protocol, the Node_XX capability fabric, or the Android execution service.

Every later-phase feature (semantic overlay, runtime profiles, contract enforcement, runtime matching) must be planned as an attachment to this real operating shape, not as a ground-up redesign.
