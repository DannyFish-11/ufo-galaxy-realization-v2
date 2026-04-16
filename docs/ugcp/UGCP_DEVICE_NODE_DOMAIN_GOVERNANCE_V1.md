# UGCP Device/Node Domain Governance v1

> **Scope**: `DannyFish-11/ufo-galaxy-realization-v2` (center/control authority)
>
> **Status**: Canonical governance baseline.
> Defines device-domain vs node-domain responsibilities, bridge relationships,
> and registry surface classifications.
>
> **Introduced**: PR-5 (Define unified governance for the device domain and
> node domain without forcing false identity equivalence)
>
> **Authority module**: `core.device_node_domain_governance`
>
> Related documents:
> - `UGCP_CONSTITUTION_V1.md` — constitutional clauses
> - `CROSS_REPO_HOMOMORPHIC_MAPPING_V1.md` — device/node domain mapping overview (§3)
> - `UGCP_CANONICAL_AUTHORITY_CHAIN_V1.md` — authority chain
> - `../REGISTERED_RUNTIME_DEVICE_CONTRACT.md` — device contract

---

## 1) Governance statement

The Galaxy / OpenClawd center runtime contains two distinct governance domains:

- The **device domain** governs physical and virtual endpoint identity,
  runtime hosting, connectivity, registration, SSOT-aligned state, and
  presence-oriented lifecycle.

- The **node domain** governs executable units, capability hosting,
  orchestration targets, dispatch semantics, invocation governance, and
  execution-oriented lifecycle.

These two domains are **clearly related but not identical**.  A device is not a
node, and a node is not a device.  Treating them as equivalent would collapse
important governance distinctions and create authority ambiguity.

This document makes the governance model **explicit** so that:

- Future work can reason about device and node as part of one governed system
  without assuming they are identical.
- Bridge surfaces (capability assimilation, runtime-host selection, dispatch
  targeting) are explicitly identified as bridges rather than as domain members.
- The center runtime can govern both domains jointly without merging them.

---

## 2) Device domain

### 2.1 Definition

The device domain owns the following responsibilities:

| Responsibility | Description |
|---|---|
| `device_identity` | Maintaining stable, persistent device identifiers and hardware/software endpoint facts. |
| `runtime_hosting` | Tracking which devices currently host active runtimes (execution environments that can receive delegated tasks). |
| `connectivity` | Managing device transport connections (WebSocket, REST, address/port facts) and connection state. |
| `registration` | Canonical registration of new devices through the SSOT write path (UnifiedDeviceManager). |
| `ssot_aligned_state` | Maintaining mutable device state (status, capabilities, metadata, last-seen) as the single source of truth. |
| `presence_lifecycle` | Managing presence-oriented lifecycle transitions: online, offline, busy/idle, heartbeat-based timeout, reconnect. |
| `capability_evidence` | Collecting and normalizing capability evidence reported by devices. Capability evidence is device-domain input; capability routing is a node-domain or bridge concern. |

### 2.2 Lifecycle kind

The device domain governs a **presence lifecycle**: transitions are driven by
connectivity events (connect, disconnect, heartbeat timeout, reconnect) and
registration events (register, unregister).

### 2.3 Authority surfaces

| Surface | Module path | Role |
|---|---|---|
| UnifiedDeviceManager (UDM) | `core.unified.unified_device_manager.UnifiedDeviceManager` | **SSOT** — sole canonical write authority for device registration and mutable state |
| RegisteredRuntimeDevice contract | `contracts.registered_runtime_device.RegisteredRuntimeDevice` | Canonical external single-device read contract |
| DeviceRegistry | `core.device_registry.DeviceRegistry` | Canonical in-process registry; delegates writes to UDM |
| device readiness | `core.device_readiness` | Readiness verdict synthesis (projection; does not write canonical state) |
| device participation | `core.device_participation` | Participation hints and group membership (projection) |

### 2.4 What the device domain does NOT own

- Dispatch semantics → node domain
- Invocation governance → node domain
- Executable unit registration → node domain
- Capability routing surface (bus entries) → node domain / bridge
- Execution lifecycle (node health, architectural class) → node domain

---

## 3) Node domain

### 3.1 Definition

The node domain owns the following responsibilities:

| Responsibility | Description |
|---|---|
| `executable_unit_registration` | Registering and tracking executable units (nodes) that can perform tasks in the center runtime. |
| `capability_hosting` | Hosting named capability surfaces that can be discovered and invoked through the capability bus. |
| `orchestration_targeting` | Identifying eligible orchestration targets for task dispatch, including health, architectural class, and invocation governance evaluation. |
| `dispatch_semantics` | Defining and enforcing the semantics of task dispatch: local, remote handoff, fallback-local, staged mesh, and delegated dispatch paths. |
| `invocation_governance` | Enforcing eligibility rules at node invocation time (node governance, boundary enforcement, lifecycle-stage constraints). |
| `boundary_enforcement` | Classifying node surfaces as canonical, compat-only, internal-only, or deprecated, and enforcing that classification at runtime. |
| `execution_lifecycle` | Managing execution-oriented lifecycle transitions: node starting, healthy, unhealthy, suspended, archived, retired. |
| `capability_sync` | Synchronizing capability declarations from eligible nodes into the capability registry (OpenClawd capability bus). |

### 3.2 Lifecycle kind

The node domain governs an **execution lifecycle**: transitions are driven by
health checks, invocation outcomes, governance eligibility evaluation, and
explicit lifecycle stage changes (readiness gates, deprecation, archival).

### 3.3 Authority surfaces

| Surface | Module path | Role |
|---|---|---|
| NodeFabricRegistry | `core.nodes.node_fabric_registry.NodeFabricRegistry` | Canonical runtime node registry |
| node invocation governance | `core.node_invocation_governance` | Eligibility enforcement at invocation time |
| node governance runtime | `core.node_governance_runtime` | Runtime governance eligibility (architectural class, health, lifecycle-stage) |
| node boundary runtime | `core.node_boundary_runtime` | Canonical node boundary definitions and pathway classification |
| node lifecycle governor | `core.node_lifecycle_governor` | Lifecycle stage management |
| node cognition activation | `core.node_cognition_activation` | Cognition-oriented node activation state |
| node final boundary enforcement | `core.node_final_boundary_enforcement` | Finalized boundary classification for all node surfaces |
| fusion_entry adapter | `core.fusion_entry_adapter` | Canonical adapter contract for node execution (adapter; not registry/discovery) |

### 3.4 What the node domain does NOT own

- Device identity → device domain
- Device presence lifecycle → device domain
- SSOT-aligned mutable device state → device domain (UDM)
- Device connectivity → device domain
- Capability evidence collection → device domain

---

## 4) Bridge relationships

Bridge layers connect the two domains without collapsing them.  A device that
acts as a runtime host, capability host, or dispatch target remains a
**device-domain participant** — it is not reclassified as a node.

### 4.1 Runtime-host bridge

| Aspect | Description |
|---|---|
| **Kind** | `runtime_host` |
| **Center surface** | `contracts.RegisteredRuntimeDevice` + `core.attached_runtime_session_registry` + `core.runtime.source_dispatch_orchestrator` |
| **Device-domain role** | Provides device_id, connectivity facts, runtime-host status (maintained by UDM) |
| **Node-domain role** | Dispatch orchestrator uses runtime-host status to select the device as a valid execution target |
| **Android relevance** | Android is the primary non-center runtime-host participant. When Android's runtime session is active, it is a candidate dispatch target. Android does not participate in center-side node governance. |

**Semantics**: A device that hosts an active runtime may be selected as a
dispatch target.  The bridge is the primary device→node bridge.  The selection
decision is made by node-domain dispatch logic using device-domain runtime-host
facts.

### 4.2 Capability-host bridge

| Aspect | Description |
|---|---|
| **Kind** | `capability_host` |
| **Center surface** | `core.capability_assimilation.CapabilityAssimilationLayer` + `assimilate_device()` |
| **Device-domain role** | Reports capability evidence (e.g. camera, screen, microphone) via device_capability_report messages; evidence is normalized and stored in the device record by UDM |
| **Node-domain role** | Capability assimilation layer registers the device as `NodeParticipantKind.DEVICE` in the assimilation plane, making its capabilities discoverable through node-domain routing |
| **Android relevance** | Android capability reports are normalized at center ingress and may be assimilated as device capability evidence. Android-reported capabilities do not make Android a node-domain participant. |

**Semantics**: Device capability evidence (device domain) is bridged into
node-domain capability routing through the capability assimilation layer.  The
assimilation record is a bridge artifact — the device retains its device-domain
identity.

### 4.3 Dispatch-target bridge

| Aspect | Description |
|---|---|
| **Kind** | `dispatch_target` |
| **Center surface** | `core.runtime.source_dispatch_orchestrator` + `core.android_runtime_dispatch_binding` + `core.canonical_handoff_path` |
| **Device-domain role** | Available as a potential dispatch target if its runtime-host status is active; receives the delegated task through its device-domain transport; returns results through delegated_execution_signal |
| **Node-domain role** | Source dispatch orchestrator resolves dispatch mode and selects the execution target using node-domain eligibility logic; when the target is a device, the dispatch path bridges into the device domain for delivery |
| **Android relevance** | Android receives delegated tasks through this bridge when selected as the dispatch target. Android is a device-domain participant throughout; it is never a node-domain entity. |

**Interpreting a dispatch target**: if `target_device_id` is set and the device
is a registered runtime host, the dispatch is device-domain-bound.  Node-domain
dispatch logic selected it based on capability and runtime-host eligibility.

---

## 5) Registry surface authority matrix

This matrix classifies the major governance surfaces in the repository by
domain, authority role, and whether they can write truth.

| Surface | Domain | Role | Can write truth? |
|---|---|---|---|
| UnifiedDeviceManager (UDM) | device | **SSOT** | ✅ Yes — sole canonical write authority for device state |
| RegisteredRuntimeDevice contract | device | canonical_registry | ✅ Yes — canonical read contract (read-authoritative) |
| DeviceRegistry | device | canonical_registry | ✅ Yes — in-process registry; delegates writes to UDM |
| device readiness | device | projection | ❌ No — compiles readiness evidence; does not write canonical state |
| device participation | device | projection | ❌ No — projects from device-domain state |
| NodeFabricRegistry | node | canonical_registry | ✅ Yes — canonical runtime node registry |
| NodeRegistry (compat facade) | node | compat_facade | ❌ No — legacy compat facade; must not be extended as canonical architecture |
| node invocation governance | node | canonical_registry | ✅ Yes — eligibility enforcement authority |
| node governance runtime | node | canonical_registry | ✅ Yes — runtime governance eligibility authority |
| node boundary runtime | node | canonical_registry | ✅ Yes — boundary classification authority |
| fusion_entry adapter | node | adapter | ❌ No — execution adapter contract; not registry/discovery |
| capability assimilation layer | bridge | bridge | ❌ No — bridge surface; does not own device identity or node registry |
| source dispatch orchestrator | bridge | bridge | ❌ No — dispatch bridge surface; resolves targets but does not write domain state |
| projection routes | shared_projection | projection | ❌ No — read-only projection assembling facts from both domains |
| capability registry (OpenClawd bus) | shared_projection | canonical_registry | ✅ Yes — shared entries from both node domain (via capability sync) and device domain (via bridge assimilation) |

### 5.1 Authority summary

- **Only two surfaces can write device-domain truth**: UDM (write) and
  DeviceRegistry (write via UDM delegation).
- **Four node-domain surfaces are authoritative**: NodeFabricRegistry, node
  invocation governance, node governance runtime, and node boundary runtime.
- **NodeRegistry (compat facade) is explicitly non-authoritative** and must
  not be extended as canonical architecture.
- **Bridge surfaces (capability assimilation, dispatch orchestrator) are not
  truth owners** in either domain.
- **Projection surfaces are always read-only** and must not write canonical
  state.

---

## 6) Joint center governance

The center runtime governs both domains through separate authority chains
without asserting identity equivalence between devices and nodes.

### 6.1 Authority chain separation

```
Device domain authority chain:
  Registration path → UnifiedDeviceManager (SSOT) → DeviceRegistry → RegisteredRuntimeDevice

Node domain authority chain:
  Node startup → NodeFabricRegistry → node governance runtime → node invocation governance → node boundary runtime
```

### 6.2 Joint governance through bridges

The center runtime exercises joint governance through three bridge surfaces:

1. **Runtime-host bridge** (RegisteredRuntimeDevice + dispatch orchestrator):
   The center knows which devices are runtime-capable and can select them as
   execution targets.

2. **Capability-host bridge** (capability assimilation):
   The center can route tasks to device-domain capability providers by treating
   them as first-class participants in the capability selection plane.

3. **Dispatch-target bridge** (source dispatch orchestrator):
   The center can deliver tasks to device-domain participants when they are
   selected as dispatch targets by node-domain dispatch logic.

### 6.3 Governance invariants

- **Devices are not nodes.** A device may act as a runtime host or dispatch
  target, but it is never registered in NodeFabricRegistry.
- **Nodes are not devices.** A node may host capabilities, but it is never
  registered in UnifiedDeviceManager unless it also represents a physical
  device endpoint.
- **Bridge artifacts are not domain members.** AssimilationRecord entries for
  devices (`NodeParticipantKind.DEVICE`) are bridge artifacts — they are not
  node registrations.
- **The center is the sole governance authority for both domains.** Neither the
  device domain nor the node domain has a parallel authority outside the center.
  Android and other remote participants are subjects of center governance, not
  parallel governance authorities.

---

## 7) Future work guidance

This governance model should be treated as a stable baseline.  Future work
should:

- **Preserve domain separation** when adding new device-side or node-side
  surfaces.  Do not create new surfaces that conflate device identity with
  node identity.
- **Use bridge surfaces explicitly** when introducing new device-to-node or
  node-to-device interactions.  New bridge kinds should be added to
  `core.device_node_domain_governance.BridgeRelationshipKind`.
- **Classify new authority surfaces** in the registry surface catalogue
  (`core.device_node_domain_governance._REGISTRY_SURFACE_CATALOGUE`) when
  introducing new registries, caches, facades, or adapters.
- **Treat the capability assimilation layer as a bridge** in all architectural
  reviews.  It is not a device registry and not a node registry.
- **Do not extend NodeRegistry (compat facade)** as a canonical surface.  Use
  NodeFabricRegistry for all new node-domain consumers.
