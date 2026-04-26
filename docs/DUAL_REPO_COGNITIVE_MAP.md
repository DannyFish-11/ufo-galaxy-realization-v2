# Dual-Repository System Cognitive Map

**Repositories:**
- `DannyFish-11/ufo-galaxy-realization-v2` (V2) — control/orchestration authority
- `DannyFish-11/ufo-galaxy-android` (Android) — persistent execution participant

**Document purpose:** Accurate, non-misleading reference for dual-repo system boundary,
layer classification, module semantic types, and high-priority workstream gaps.
Not a vague summary — every claim here corresponds to real code paths or registered
gaps in `core/dual_repo_system_map.py`.

---

## 1. System Role Boundary

| Dimension | V2 (`ufo-galaxy-realization-v2`) | Android (`ufo-galaxy-android`) |
|-----------|----------------------------------|-------------------------------|
| **Role** | Control / orchestration authority | Persistent execution participant |
| **Owns** | Task lifecycle, LLM routing, session truth, API surface | Local capability execution (screen, touch, keyboard, camera…) |
| **Initiates** | Commands, task assignments, capability queries | Results, heartbeats, capability reports |
| **Transport** | Hosts `galaxy_gateway` WebSocket server | Connects as WebSocket client, maintains persistent connection |
| **Persistence** | In-memory (gaps: no V2 restart recovery — see GAP_V2_TRUTH_PERSISTENCE) | Android Service survives app backgrounding |

---

## 2. Dual-Repo Main Chain (Canonical End-to-End Path)

This is the only path that counts as "main chain." Any module claiming main-chain
status should trace its position here.

```
[V2 side]
  main.py  (FastAPI startup)
    └─ core.openclawd.OpenClawd  (orchestration hub)
         └─ core.command_router.CommandRouter  (command dispatch)
              └─ galaxy_gateway.routing.device_router.DeviceRouter  (device selection)
                   └─ galaxy_gateway.websocket_handler.dispatch_to_websocket  (transport)

[Cross-repo boundary — WebSocket]
  galaxy_gateway /ws/device/{device_id}  ← CANONICAL ingress
  ──────────────────────────────────────────────────────────

[Android side — ufo-galaxy-android]
  GalaxyAndroidService  (persistent background service)
    └─ WebSocketClient  (maintains connection, implements reconnect + offline queue)
         └─ CommandDispatcher  (dispatches to local capability handlers)
              ├─ AccessibilityService  (screen / touch / keyboard — MAIN_CHAIN)
              ├─ CameraService        (QUASI_MAIN_CHAIN)
              └─ LocalAIService       (EXPERIMENTAL — not activated by default)

[Result path back to V2]
  Android → WebSocket result message → galaxy_gateway
    └─ core.canonical_completion_ingress.CanonicalCompletionIngress  (result ingress)
         └─ core.unified_runtime_truth_ingress  (UDM / session state update)
              └─ core.device_registry  (UDM — device state SSOT)
```

**What is NOT on this main chain** (additive/advisory/declarative):
- `core.final_cleanup_invariant_tightening` — importability guards and sentinel strings
- `core.governance_validation_gate` — advisory evaluation, does not block
- `core.architecture_completion` — status labels
- All `*_AUTHORITY` / `*_SENTINEL` / `*_POLICY` string constants without runtime callers

---

## 3. System Planes

The five planes and their module families:

### CONTROL_PLANE (V2 — orchestration and agent execution)
Key modules: `core.openclawd`, `core.command_router`, `core.agent_factory`,
`core.task_graph`, `core.api_routes`, `main`

- Owns task lifecycle from user request to command dispatch
- OpenClawd is a large, real execution hub — not a shell
- Task graph and agent factory are real; agent assignment is live

### EXECUTION_PLANE (Android — local capability delivery)
Key modules: `android:GalaxyAndroidService`, `android:CommandDispatcher`,
`android:AccessibilityService`, `android:OfflineQueue`

- All module names prefixed `android:` are in the Android repo
- OfflineQueue is real: commands queued during disconnection, replayed on reconnect
- V2 cannot unit-test Android execution — requires device/emulator (see GAP_JOINT_INTEGRATION_TEST)

### GATEWAY_TRANSPORT (V2 — V2/Android boundary)
Key modules: `galaxy_gateway.routes.websocket`, `galaxy_gateway.routing.device_router`,
`galaxy_gateway.protocol.aip_v3`, `core.android_bridge`

- **Canonical device ingress**: `galaxy_gateway /ws/device/{device_id}` (NOT `core/api_routes.py` WebSocket path)
- `core/api_routes.py` WebSocket route is a **compatibility-only** path for legacy/core-direct clients
- AIP v3 is the canonical cross-repo message envelope
- `core.android_bridge` handles registration/heartbeat/disconnect and writes to UDM

### PROVIDER_PLANE (V2 — LLM and model routing)
Key modules: `core.unified.llm_router.UnifiedLLMRouter`, `core.multi_llm_router.MultiLLMRouter`

- `UnifiedLLMRouter` is the sole legitimate model-access entry for OpenClawd and all orchestration paths
- `MultiLLMRouter` is the execution backend (provider selection, failover) — not a peer entry point
- PR-837 fixed a `SyntaxError` in `llm_router.py` that was blocking this path entirely
- Known gap: `OpenClawd._get_router()` fallback to `MultiLLMRouter` on unified router failure means strict single-entry is not yet enforced

### TRUTH_CONTINUITY_PLANE (V2 — session, UDM, task truth)
Key modules: `core.device_registry`, `core.canonical_completion_ingress`,
`core.unified_runtime_truth_ingress`, `core.canonical_session_truth`

- `core.device_registry` (UDM) is the runtime SSOT for device identity and state
- `core.canonical_completion_ingress` is live — called on task completion
- `core.unified_runtime_truth_ingress` is **NEAR_MAINLINE** (additive, not hard-replacing old paths)
- Known live bypass: `websocket_handler.py:588` writes device state without going through canonical ingress

---

## 4. Module Semantic Type Map

The key insight from the PR-837 review: module _names_ containing AUTHORITY/SENTINEL/POLICY/GATE/TRUTH
do **not** determine their runtime significance. Only their actual call pattern does.

| Semantic Type | What it means | Example modules |
|---------------|---------------|-----------------|
| **RUNTIME_CRITICAL** | Called on every real request or required for startup | `core.openclawd`, `core.command_router`, `galaxy_gateway.routes.websocket`, `core.unified.llm_router`, `core.android_bridge`, `core.device_registry` |
| **SEMI_EXECUTABLE** | Callable guards/gates, only invoked when explicitly called | `core.capability_routing_gate`, `core.capability_tier`, `core.unified.release_gate`, `core.cross_repo_consistency_gates`, `core.unified_runtime_truth_ingress` |
| **DECLARATIVE** | Sentinel strings, policy labels, posture snapshots — no runtime enforcement | `core.final_cleanup_invariant_tightening`, `core.architecture_completion`, `core.architecture_truth_guards`, `core.authority_boundary_classification` |

### Notable clarifications

**`core.final_cleanup_invariant_tightening`** (892 lines, PR-837):
- Contains: 9 policy sentinel strings, 5 `assert_*_is_canonical()` guards (importability only),
  `CapabilityTier` enum, posture snapshot builder
- Classification: **DECLARATIVE**
- The `assert_*_is_canonical()` functions prove modules are *importable*, not that bypass paths are closed
- `is_final_cleanup_posture_acceptable()` produces a snapshot report but does not block execution
- Absence of this module would not break any user-facing execution path

**`core.capability_routing_gate`**:
- Classification: **SEMI_EXECUTABLE**
- `evaluate_capability_gate()` is a real, correct function
- Critical gap: `send_gateway_command()` with explicit `device_id` and no `required_capabilities`
  sets `_effective_caps=None` → gate is silently skipped
- The gate is an *additive* constraint, not a *default-enforced* one

**`core.unified_runtime_truth_ingress`**:
- Classification: **SEMI_EXECUTABLE**
- Real ingress function exists and is correct
- Gap: additive, not hard-replacing old paths; `websocket_handler.py:588` is a live documented bypass
- Full convergence to single ingress is a P1 workstream item

---

## 5. Main-Chain / Layer Classification Summary

| Layer | Definition | Examples |
|-------|-----------|---------|
| **Main Chain** | Canonical path; verified end-to-end dispatch and completion | `openclawd → command_router → device_router → websocket → Android → canonical_completion_ingress` |
| **Quasi-Main-Chain** | Substantially integrated; known gaps (incomplete E2E, not default-on) | `session_migration`, `session_continuity`, `local_llm`, `camera`, `microphone`, `unified_runtime_truth_ingress` |
| **Extension Layer** | Architecturally present; NOT wired to main dispatch chain | `vlm`, `webrtc`, `live_mesh_runtime`, `desktop_projection`, `local AI on Android` |
| **Compatibility Layer** | Legacy path retained for backward compatibility | `core/api_routes.py /ws/device` route, `MultiLLMRouter` direct access |
| **Review/Audit Layer** | Declarative sentinels, policy labels, snapshot builders | Most `*_AUTHORITY`, `*_SENTINEL`, `*_POLICY` string constants; `final_cleanup_invariant_tightening` |

---

## 6. High-Priority Workstream Gaps

All gaps are registered in `core/dual_repo_system_map.WORKSTREAM_GAP_REGISTRY` and
verified by `tests/test_dual_repo_system_map.py`. Resolved status must not be set without
a concrete PR reference — declarative/sentinel PRs do not count.

### P0 — Directly affects reliability / correctness of main chain

| Gap ID | Title | Status |
|--------|-------|--------|
| `GAP_JOINT_INTEGRATION_TEST` | Dual-repo joint integration test framework missing | **Open** |
| `GAP_CAPABILITY_GATE_DEFAULT_ENFORCEMENT` | `capability_routing_gate` not enforced by default in `send_gateway_command` | **Open** |
| `GAP_V2_TRUTH_PERSISTENCE` | V2 task lifecycle / session truth has no persistence or restart recovery | **Open** |

### P1 — Significant verification or safety gap

| Gap ID | Title | Status |
|--------|-------|--------|
| `GAP_RUNTIME_TRUTH_SINGLE_INGRESS` | Runtime truth ingress convergence incomplete (live bypass exists) | **Open** |
| `GAP_ANDROID_CI` | Android repo has no CI pipeline | **Open** |
| `GAP_ANDROID_LOCAL_AI_DEFAULT_OFF` | Android local AI / on-device inference not activated by default | **Open** |

### P2 — Meaningful improvement, deferrable

| Gap ID | Title | Status |
|--------|-------|--------|
| `GAP_RELEASE_GATE_HARD_ENFORCEMENT` | Governance/release gate not wired to hard CI or deploy blocking | **Open** |

---

## 7. Machine-Checkable Layer: What This PR Provides

This PR does not just add documentation. It adds two code artifacts:

### `core/dual_repo_system_map.py`
- Importable Python module with registries, enumerations, data classes
- `build_system_map_snapshot()` → JSON-serialisable CI snapshot
- `get_plane()`, `get_semantic_type()` → queryable by test and tooling
- Gap registry with `resolved` flag enforced by tests

### `tests/test_dual_repo_system_map.py`
- 42 passing tests covering: registry completeness, classification consistency,
  declarative-vs-runtime boundary enforcement, gap registry integrity, snapshot validity
- **Anti-drift tests**: if `core.final_cleanup_invariant_tightening` is ever
  reclassified as RUNTIME_CRITICAL, tests fail immediately
- **Anti-premature-resolution tests**: P0 gaps cannot be marked resolved without
  a concrete `resolution_pr` reference

---

## 8. Honest System Maturity Assessment

Based on real code analysis (not declarative claims):

| Area | Honest Assessment |
|------|------------------|
| Main chain exists and runs | ✅ True — `main.py → OpenClawd → CommandRouter → DeviceRouter → WebSocket` is real |
| Android execution is real | ✅ True — GalaxyAndroidService, CommandDispatcher, offline queue, reconnect all exist |
| Unified LLM routing | ✅ Unblocked by PR-837 fix; `UnifiedLLMRouter` is now importable |
| Capability gate enforcement | ⚠️ Advisory, not default-enforced (GAP_CAPABILITY_GATE_DEFAULT_ENFORCEMENT) |
| Runtime truth single ingress | ⚠️ Near-mainline; live bypass exists (GAP_RUNTIME_TRUTH_SINGLE_INGRESS) |
| Dual-repo E2E verified | ❌ No joint integration test framework exists (GAP_JOINT_INTEGRATION_TEST) |
| V2 state persistence / restart recovery | ❌ Not implemented (GAP_V2_TRUTH_PERSISTENCE) |
| Android CI | ❌ Not set up (GAP_ANDROID_CI) |
| Android local AI | ❌ Not activated by default (GAP_ANDROID_LOCAL_AI_DEFAULT_OFF) |
| Governance/release gate hard enforcement | ❌ Advisory only (GAP_RELEASE_GATE_HARD_ENFORCEMENT) |

Overall honest stage: **Main chain operational + early system integration phase**
(not "pre-production ready", not "skeleton" — genuinely runnable but with significant
verification and gap closure work remaining)
