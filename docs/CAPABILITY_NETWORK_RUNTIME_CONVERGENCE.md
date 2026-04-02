# PR-D: Capability + Network Runtime Convergence

## Overview

PR-D unifies the **capability assimilation layer** and the **network topology runtime** into a coherent **dual-graph chassis** that the planner, router, and policy subsystems can query together.

After PR-D, the system can simultaneously answer:
- *Why was this provider/executor selected?* (capability graph)
- *Why was this network/transport path chosen?* (network runtime)
- *How does fallback work when either side degrades?* (bridge layer)

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  PLANNER / ROUTER / POLICY  (consumers)                         │
│  "Why this provider?" + "Why this path?"                        │
└────────────────────────┬─────────────────────────────────────────┘
                         │  consumes
                         ▼
┌──────────────────────────────────────────────────────────────────┐
│  CAPABILITY ↔ NETWORK BRIDGE  (Layer 11)                        │
│  core/capability_network_bridge.py                               │
│  joint_select() / explain_joint_selection() / fallback_joint_select()│
└────────────┬──────────────────────────────┬──────────────────────┘
             │ capability side               │ network side
             ▼                               ▼
┌────────────────────────┐   ┌───────────────────────────────────┐
│  CAPABILITY SELECTION  │   │  NETWORK TOPOLOGY RUNTIME         │
│  PLANE  (Layer 10)     │   │  (Layer 8)                        │
│  core/capability_      │   │  core/network_topology_runtime.py  │
│  graph_selection.py    │   │                                    │
│  discover_providers()  │   │  absorb_device_connectivity()      │
│  select_best_provider()│   │  absorb_nats_state()               │
│  select_fallback_      │   │  absorb_gateway_state()            │
│  providers()           │   │  project_transport_path()          │
│  explain_selection()   │   │                                    │
└────────────┬───────────┘   └─────────────────────────────────┘
             │ reads                           ▲
             ▼                                 │ projected from
┌────────────────────────────────────────────────────────────────┐
│  CAPABILITY ASSIMILATION LAYER  (Layer 7)                       │
│  core/capability_assimilation.py                                │
│  NodeParticipantKind: CAPABILITY_PROVIDER, WORKER, SPECIALIST,  │
│    FABRIC_PARTICIPANT, LEGACY_FACADE, DEVICE, MCP_PROVIDER,     │
│    SKILL, UNKNOWN                                               │
│  assimilate_device() / assimilate_mcp_provider() /              │
│  assimilate_skill() / assimilate_node()                         │
└────────────────────────────────────────────────────────────────┘
```

---

## Module Authority Map

| Module | Authority Sentinel | Layer | Role |
|--------|-------------------|-------|------|
| `core/capability_assimilation.py` | `CAPABILITY_ASSIMILATION_AUTHORITY` | 7 | Absorbs all providers into unified capability registry |
| `core/network_topology_runtime.py` | `NETWORK_TOPOLOGY_RUNTIME_AUTHORITY` | 8 | Sole authority for network topology / transport path |
| `core/capability_graph_selection.py` | `CAPABILITY_GRAPH_SELECTION_AUTHORITY` | 10 | Capability selection plane (discovery, scoring, fallback) |
| `core/capability_network_bridge.py` | `CAPABILITY_NETWORK_BRIDGE_AUTHORITY` | 11 | Joint capability+network selection and explanation |
| `core/command_router.py` | `COMMAND_ROUTER_DUAL_GRAPH_INTEGRATED` | — | Dual-graph governance sentinel |

---

## Provider Classification (PR-D Extension)

PR-D extends `NodeParticipantKind` with three new values:

| Kind | Value | Description |
|------|-------|-------------|
| `DEVICE` | `"device"` | Physical/virtual device (Android, desktop, IoT). Registered via `assimilate_device()`. |
| `MCP_PROVIDER` | `"mcp_provider"` | MCP-protocol tool/skill server. Registered via `assimilate_mcp_provider()`. |
| `SKILL` | `"skill"` | Skill-based capability provider. Registered via `assimilate_skill()`. |

These join the existing kinds (`CAPABILITY_PROVIDER`, `WORKER`, `SPECIALIST`, `FABRIC_PARTICIPANT`, `LEGACY_FACADE`, `UNKNOWN`).

The `_arch_class_to_participant_kind()` mapping also covers:
- `"device"`, `"android_device"`, `"iot_device"`, `"desktop_device"` → `DEVICE`
- `"mcp_provider"`, `"mcp_server"`, `"mcp_tool"` → `MCP_PROVIDER`
- `"skill"`, `"skill_provider"` → `SKILL`
- `"worker_endpoint"` → `WORKER`
- `"specialist_executor"` → `SPECIALIST`

---

## Network Runtime Completion (PR-D Extension)

`core/network_topology_runtime.py` is extended with:

### Gateway path in device transport edges

`_register_device_transport_edges()` now handles `preferred_path="gateway"`:
```
direct_ws / ucm  →  DIRECT edge  +  PREFERRED state
gateway          →  GATEWAY edge +  PREFERRED state   ← NEW in PR-D
relay            →  RELAY edge   +  PREFERRED/FALLBACK state
mesh             →  MESH edge    +  LATENT state
```

---

## Capability Selection Plane

`core/capability_graph_selection.py` provides:

```python
# Discover all providers matching required capabilities
providers = discover_providers(
    capabilities=["screen", "touch"],
    kind_filter=["device"],          # optional: restrict to device kind
    require_online=True,             # default
)

# Select best single provider
best = select_best_provider(["web_search"], kind_filter=["skill"])

# Select fallback providers (excludes already-failed primary)
fallbacks = select_fallback_providers(
    ["web_search"],
    exclude_ids=["failed-skill-01"],
    max_results=3,
)

# Get human-readable explanation
explanation = explain_selection(best, ["web_search"], alternatives=fallbacks)
# → explanation.reason = "Provider 'skill-search-01' selected as skill: full capability match..."
```

### Scoring

The `score_provider()` function returns a `CapabilityFitScore`:
- `coverage_ratio` = matched_caps / required_caps  (0.0–1.0)
- `kind_priority` = from `_KIND_PRIORITY` table (higher = preferred)
- `total_score` = `coverage_ratio * 10.0 + kind_priority * 0.5 - degraded_penalty`

---

## Capability ↔ Network Bridge

`core/capability_network_bridge.py` provides joint selection:

```python
# Joint select: best provider + best path simultaneously
result = joint_select(
    required_capabilities=["screen", "touch"],
    kind_filter=["device"],
)
# result.selected_provider_id  → "android-pixel-01"
# result.path_availability.effective_path  → "direct"
# result.joint_score  → 9.5

# Full explanation
expl = explain_joint_selection(result)
# expl.provider_reason  → "Provider 'android-pixel-01' selected as device: full capability match..."
# expl.path_reason      → "Transport path to 'android-pixel-01': effective_path='direct' (state='preferred', score=1.00)."
# expl.fallback_reason  → "If path 'direct' degrades, fallback path 'relay' is available."

# Fallback select (when primary has failed)
fallback = fallback_joint_select(
    required_capabilities=["screen"],
    exclude_ids=["android-pixel-01"],
)
```

### Joint Score Formula

```
joint_score = (capability_score * 0.6 + path_score * 10.0 * 0.4) * degraded_factor
```
where `degraded_factor = 0.8` when degraded, `1.0` otherwise.

---

## Governance Policy

### `CAPABILITY_SELECTION_POLICY`
> Planner/router/policy MUST query capability candidates via `core.capability_graph_selection` rather than reading raw `AssimilationRecord` collections directly.

### `DUAL_GRAPH_SELECTION_POLICY`
> Planner/router/policy MUST perform joint capability + network routing decisions via `core.capability_network_bridge.joint_select()`. Direct cross-layer reads are prohibited.

### `COMMAND_ROUTER_DUAL_GRAPH_INTEGRATED`
> Asserts that CommandRouter is aware of and compliant with the dual-graph selection architecture.

---

## Observability

All three new modules maintain 256-entry ring buffers:

| Module | Log getter | Record type |
|--------|-----------|-------------|
| `capability_graph_selection` | `get_selection_log()` | `SelectionRecord` |
| `capability_network_bridge` | `get_bridge_log()` | `BridgeRecord` |
| `network_topology_runtime` | `runtime.get_topology_log()` | `TopologyRecord` |

Every selection decision is logged with:
- Required capabilities
- Selected provider(s)
- Effective path
- Joint score
- Degraded flag + reason

---

## Test Coverage

| Test file | Coverage |
|-----------|---------|
| `tests/test_network_runtime_completion.py` | Network runtime node kinds, edge kinds, device/NATS/gateway absorption, transport path projection, capability-arch_class mapping |
| `tests/test_capability_network_selection.py` | Capability selection plane (discovery, scoring, fallback, explain, new provider kinds) |
| `tests/test_transport_path_explainability.py` | Bridge module (joint select, explain, path availability, dual-graph sentinel) |
| `tests/test_fallback_provider_path_selection.py` | Fallback selection across all provider kinds, degraded mode, joint fallback, ring buffer continuity |

---

## Acceptance Criteria

- [x] Capability graph is a true selection plane (not just a registry)
- [x] Network runtime is the sole topology/path authority
- [x] Planner/router/policy can simultaneously explain "why this provider" and "why this path"
- [x] Fallback/degraded mode is observable and explainable on both sides
- [x] All provider types (device, node, worker, skill, MCP) are first-class capability providers
- [x] Gateway path is properly handled in device transport edges
- [x] 256-entry ring buffers in all three layers for operator observability
