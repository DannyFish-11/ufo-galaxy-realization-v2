# Cross-Repository Homomorphic Mapping v1

> **Scope**: `DannyFish-11/ufo-galaxy-realization-v2` (center/control authority, **center**)
> ↔ `DannyFish-11/ufo-galaxy-android` (Android runtime host participant, **android**)
>
> **Status**: Canonical mapping baseline — architecture-grounding only.
> Does not claim full protocol convergence is already implemented.
>
> **Introduced**: PR-2 (Define cross-repository homomorphic mapping)
>
> Related documents:
> - `UGCP_CANONICAL_VOCABULARY_V1.md` — frozen canonical vocabulary
> - `UGCP_ANDROID_ALIGNMENT_NOTES_V1.md` — incremental alignment notes
> - `UGCP_SHARED_SCHEMA_MAPPINGS_V1.md` — schema-level mapping shims
> - `UGCP_CONFORMANCE_SURFACES_V1.md` — conformance surface classifications
> - `../architecture/CANONICAL_CONCEPT_MODEL_V1.md` — architecture-level concept model

---

## 1) How to read this document

### 1.1 Mapping classifications

Every entry in this document is labeled with one of four classifications:

| Classification | Symbol | Meaning |
|---|---|---|
| **CANONICAL_MATCH** | `≡` | Exact conceptual equivalence. Both repositories use the same concept with compatible semantics and aligned naming. Safe to treat as identical across convergence work. |
| **PARTIAL_MATCH** | `≈` | Partial semantic overlap. The concept is semantically related and scope is broadly similar, but domain-specific differences exist. Treat as equivalent only within the described scope boundaries. |
| **TRANSITIONAL_ALIAS** | `→` | One or both sides currently use a local or compatibility alias for what is the same underlying concept. The canonical name is the long-term target; the alias is explicitly tolerated during convergence. |
| **UNRESOLVED_DIVERGENCE** | `≠` | No confirmed mapping. Concepts may be superficially related but have not been formally aligned, or alignment is blocked by unresolved semantic differences. Requires explicit convergence work before treating as equivalent. |

### 1.2 Column structure

Most mapping tables use:

| Column | Meaning |
|---|---|
| **center concept / surface** | The center-side (`realization-v2`) canonical or current name, including module reference where applicable. |
| **android concept / surface** | The android-side (`ufo-galaxy-android`) name or family as known from alignment notes and protocol surfaces. |
| **classification** | One of the four symbols above. |
| **notes** | Scope boundary, known divergences, or convergence notes. |

---

## 2) Participant / device / runtime / capability concepts

### 2.1 Core identity concepts

| center concept / surface | android concept / surface | cls | notes |
|---|---|---|---|
| `participant` (`core.schemas.ugcp.ParticipantModel`) | `participant` (UGCP-aligned naming target) | `≡` | Canonical concept shared by both repos. A real runtime/system actor in execution and coordination. Android side adopts this name under UGCP alignment. |
| `device` (`core.unified.device_manager`, `contracts.registered_runtime_device.RegisteredRuntimeDevice`) | `device` (device registration/identity surface) | `≡` | Hardware/software endpoint identity carrying platform facts, transport, and declared capabilities. Identity anchor in both repos. |
| `runtime` (`core.attached_runtime_session_registry`, runtime host surfaces) | `runtime` / `runtime host` (Android local execution host) | `≈` | Both repos treat runtime as an executable host surface. Center side governs runtime truth authority; Android side is a runtime-profile participant (not a parallel truth authority). |
| `capability` (`contracts.RuntimeCapabilityProfile`, `core.unified.capability_contract.CapabilityContract`) | `capability` (Android capability report surface) | `≈` | Both repos use capability as a declared ability surface. Center side governs capability-routing and readiness; Android side reports capabilities as evidence, not as identity replacement. |
| `runtime host participant` (`contracts.RegisteredRuntimeDevice.participant_identity`) | Android runtime host actor | `≈` | Center-side runtime host participant = Android-side runtime host. Android is the primary non-center runtime-host participant in the current system. |
| `device_id` | `device_id` | `≡` | Stable hardware/software endpoint identity. Preserved end-to-end. |
| `runtime_session_id` (`core.attached_runtime_session_registry`) | `runtime_session_id` / `attached_session_id` | `→` | `attached_session_id` is a transitional alias for `runtime_session_id`. Center registry is the authority for active/non-active resolution. |

### 2.2 Capability-provider and readiness

| center concept / surface | android concept / surface | cls | notes |
|---|---|---|---|
| `CapabilityContract` (`core.unified.capability_contract`) | Android capability report payload | `≈` | Center side has a canonical capability contract type; Android reports capability as a registration payload. Semantics are aligned but types are not yet unified. |
| `readiness_verdict` (`core.device_readiness`) | Android readiness checks (model/accessibility/overlay) | `→` | Android readiness reports are evidence for center-side `readiness_verdict` synthesis; they are not an independent readiness authority override. |
| `RuntimeCapabilityProfile` (`contracts.registered_runtime_device`) | Android capability surface | `≈` | Capability profile is the center-side canonical form; Android side contributes evidence fields. |
| `capability_refs` (participant capability references) | Android-reported capability list | `→` | Android capability list is normalized into `capability_refs` during mapping shim; direct equivalence only after normalization. |

---

## 3) Device-domain vs node-domain structures

### 3.1 Domain overview

The two domains are distinct by design. This section makes that distinction explicit.

| Domain | Primary responsibility | Center-side authority surfaces | Android-side relevance |
|---|---|---|---|
| **device domain** | Device identity, runtime hosting, connectivity, registration, SSOT-aligned state, presence-oriented lifecycle | `core.unified.device_manager`, `core.unified.unified_device_manager`, `contracts.registered_runtime_device` | Android is a device-domain participant (registers, sends heartbeats, capability reports) |
| **node domain** | Executable units, capability hosting, orchestration targets, dispatch semantics, execution-oriented lifecycle | `core.nodes.node_fabric_registry.NodeFabricRegistry`, `core.node_invocation_governance`, `core.node_boundary_runtime` | Android does not directly participate in center-side node-domain governance; dispatch targets are resolved by center-side node-domain |

### 3.2 Device-domain concept mapping

| center concept / surface | android concept / surface | cls | notes |
|---|---|---|---|
| `UnifiedDeviceManager` (UDM, `core.unified.unified_device_manager`) | No direct android equivalent | `≠` | UDM is the center-side SSOT write authority for device truth. Android does not have a parallel UDM; it is a subject of UDM writes. |
| `RegisteredRuntimeDevice` (`contracts.registered_runtime_device`) | Android device registration record | `≈` | Center side has a canonical typed registration contract; Android side sends registration payloads that map into this contract via `from_android_registration(...)`. |
| `device_register` message | `device_register` WebSocket message | `≡` | Registration protocol message is the same concept end-to-end. Center handles via `android_bridge` registration handler. |
| `device_heartbeat` message | `heartbeat` / `device_status` / `agent_status` | `→` | Android uses `heartbeat`, `device_status`, `agent_status` families; all normalize to `device_heartbeat` semantics on center side. |
| `device_capability_report` message | `capability_report` | `→` | `capability_report` is the android-side alias; normalized to `device_capability_report` plane on center side. |
| `RuntimeDeviceStatus` enum | Android device online/offline/busy states | `≈` | Similar semantics but not identical enum values. Android-side status reports are normalized at ingress. |

### 3.3 Node-domain concept mapping

| center concept / surface | android concept / surface | cls | notes |
|---|---|---|---|
| `NodeFabricRegistry` (`core.nodes.node_fabric_registry`) | No direct android equivalent | `≠` | The canonical runtime node registry is a center-side construct only. Android does not have a node fabric registry. |
| `NodeRegistry` (`core.node_registry`) | No direct android equivalent | `≠` | `NodeRegistry` is a **compat facade** (`LEGACY_NODE_REGISTRY_IS_COMPAT_FACADE_SENTINEL`). It is non-authoritative. Android has no equivalent. |
| node eligibility / governance (`core.node_invocation_governance`) | No direct android equivalent | `≠` | Node invocation governance (eligibility enforcement at invocation time) is purely center-side. Android dispatch targets are resolved by center-side governance before handoff. |
| node boundary classification (`core.node_boundary_runtime`) | No direct android equivalent | `≠` | Node boundary enforcement is a center-side concern. Android runtime participants are not classified as nodes. |
| `fusion_entry.py` execution adapter | No direct android equivalent | `≠` | `fusion_entry.py` is the center-side execution adapter contract for node execution. No android-side equivalent exists. |
| dispatch target (node selected for execution) | Android as execution target (receiving delegated task) | `≈` | When Android is selected as an execution target, it is a device-domain participant receiving a delegated task. It is not itself a node-domain entity. The dispatch mechanism bridges the two domains. |

### 3.4 Bridge relationships (device ↔ node domain)

| bridge concept | center surface | android relevance | cls | notes |
|---|---|---|---|---|
| Capability assimilation | `core.capability_assimilation_layer` (compat path) | Android capability reports as input | `≈` | Capability assimilation bridges device capability evidence into node-domain routing. Android-reported capabilities are one input source. |
| Runtime hosting | `contracts.RegisteredRuntimeDevice` + node dispatch | Android as runtime host | `≈` | A device that hosts a runtime may be selected as a dispatch target. This is the primary device→node bridge. |
| Dispatch targeting | `core.runtime.source_dispatch_orchestrator` | Android receives delegated dispatch | `≈` | When Android is selected as dispatch target, the center's source dispatch orchestrator initiates the delegation. Android receives and executes the delegated task. |

---

## 4) Session families and related identifiers

### 4.1 Session family mapping

| center session family | android session family | cls | notes |
|---|---|---|---|
| `control_session_id` (control-plane continuity session) | `session_id` (Android primary session field) | `→` | Android `session_id` maps to `control_session_id`. Transitional alias; canonical name is the convergence target. |
| `runtime_session_id` (runtime attachment session identity) | `runtime_session_id` / `attached_session_id` | `→` | `attached_session_id` is a transitional alias. Center registry (`core.attached_runtime_session_registry`) is the authority for active/non-active resolution. |
| `mesh_session_id` (`contracts.mesh_session`) | `mesh_session_id` (when mesh/staged coordination is active) | `≡` | Preserved end-to-end when mesh is active. Same semantics and name in both repos. |
| `task_id` (`core.schemas.task_envelope.TaskEnvelope`) | `task_id` | `≡` | Stable task work-unit identity. Preserved end-to-end. |
| `trace_id` (`TaskEnvelope`, runtime/session contracts) | `trace_id` | `≡` | End-to-end causal trace identity. Preserved end-to-end. |
| `execution_instance_id` (canonical execution attempt identity) | Android execution attempt identifier | `→` | Currently represented by `dispatch_id` / `dispatch_record_id` on center side. Android-side name is `execution_instance_id` as UGCP target; actual field alignment is in-progress. |
| `conversation_session` (conversation/history continuity) | Android conversation/chat session | `≈` | Semantically related but both sides currently express this differently. Not yet unified at protocol level. |
| `delegation_transfer_session` (handoff/transfer lifecycle) | Android transfer/delegation lifecycle context | `≈` | Android delegation/transfer events describe the same transfer lifecycle. Not yet unified under a single canonical session type. |

### 4.2 Session hierarchy (canonical, center-side authority)

```
trace_id → task_id → control_session_id → runtime_session_id → mesh_session_id (optional)
```

- Center side is the authoritative resolver for all session identities.
- Android side provides session identifiers as claims; center resolves canonicality.

---

## 5) Delegated execution signal and result structures

### 5.1 Signal kinds

| center concept / surface | android concept / surface | cls | notes |
|---|---|---|---|
| `DelegatedSignalKind` enum (`core.android_delegated_signal_ingress`) | Android `signal_kind` field | `→` | Android `signal_kind` is normalized to `DelegatedSignalKind` at center ingress. Canonical kinds: `ack`, `progress`, `result`, `timeout`, `cancelled`. |
| `delegated_execution_signal` message family | Android delegated execution signal | `≡` | Dedicated canonical ingress path on center side (`core.android_delegated_signal_ingress`). Both repos treat this as the primary delegated execution feedback channel. |
| `device_task_result` (`ResultEnvelope`, `core.unified.command_envelope`) | Android task result payload | `≈` | Same semantic intent; center has a canonical `ResultEnvelope` type. Android result payload is mapped into this contract at ingress. |
| execution tracking (`dispatch_id` / `dispatch_record_id`) | Android execution attempt identifier | `→` | Center uses `dispatch_id`/`dispatch_record_id` as execution instance identity; canonical target is `execution_instance_id`. |

### 5.2 Terminal states

| center terminal vocabulary | android terminal vocabulary | cls | notes |
|---|---|---|---|
| `terminal_state` (canonical terminal status label) | Android completion/failure/cancel outcomes | `→` | Android final outcomes are normalized into `terminal_state` vocabulary at center ingress. |
| `terminal_reason` (canonical terminal reason field) | Android `reason`/error fields | `→` | Android `reason`/error fields map to `terminal_reason`. |
| Canonical terminal set: `completed`, `partial`, `failed`, `cancelled`, `timed_out` | Android: success/failure/cancelled/timeout variants | `≈` | Semantically aligned; android-side naming variants are normalized at center conformance boundary. |

### 5.3 Dispatch path modes

| center concept / surface | android concept / surface | cls | notes |
|---|---|---|---|
| `dispatch_mode` (`SourceDispatchMode` enum, `contracts.source_dispatch`) | Android route tags (local/cross-device/delegated/fallback) | `→` | Android route tags are interpreted as `dispatch_mode` (intended mode) at center side. |
| `effective_mode` (actual mode after fallback/degradation) | Android fallback route tag | `→` | Android fallback route tag is treated as `effective_mode` evidence; center determines effective mode authoritatively. |
| `source_runtime_posture` (`control_only` / `join_runtime`) | Android participation posture | `≈` | Center-side posture governs contribution semantics. Android posture evidence is an input; center-side is the authority. |

---

## 6) Protocol alignment models and shared schema vocabulary

### 6.1 UGCP canonical vocabulary alignment

| canonical concept | center grounding | android grounding | cls | notes |
|---|---|---|---|---|
| `ParticipantModel` (`core.schemas.ugcp.shared`) | `core.schemas.ugcp.ParticipantModel` | UGCP-aligned participant concept (alignment target) | `≡` | Canonical participant model; both repos target this vocabulary. |
| `TaskEnvelope` (`core.schemas.ugcp`) | `core.schemas.task_envelope.TaskEnvelope` (center) | Task envelope / task payload (android) | `≈` | Center has a canonical schema type; Android aligns to this via UGCP vocabulary. Not yet fully unified at wire level. |
| `DispatchDecision` (`core.schemas.ugcp`) | `core.delegated_runtime_dispatch_intent.DelegatedRuntimeDispatchRecord` | Android dispatch intent record | `≈` | Center mapping shim: `map_from_delegated_dispatch_record(...)`. Android-side is partially aligned. |
| `HandoffRequest` (`core.schemas.ugcp`) | `core.delegated_runtime_handoff_contract.DelegatedHandoffContractRecord` | Android handoff event | `≈` | Center mapping shim: `map_from_delegated_handoff_contract(...)`. Android-side is partially aligned. |
| `RuntimeTruth` (`core.schemas.ugcp`) | `contracts.runtime_session_snapshot.RuntimeSessionSnapshot` | Android runtime truth surface | `≈` | Center mapping shim: `map_from_runtime_session_snapshot(...)`. Android-side runtime truth is an input to center authority. |
| `coordination_role` | center coordination role enum | Android participant role | `≈` | Same conceptual vocabulary; Android reports roles as registration metadata. Not yet unified at enum level. |
| `readiness_verdict` | `core.device_readiness` verdict | Android readiness check family | `→` | Android readiness checks are evidence; center synthesizes the authoritative `readiness_verdict`. |
| `coordination_outcome` | Mesh session/coordinator status + merged result/recovery | Android coordination result | `≈` | Android-side coordination outcomes are evidence inputs for center-side `coordination_outcome` authority. |

### 6.2 Wire-level protocol alignment

| center protocol surface | android protocol surface | cls | notes |
|---|---|---|---|
| AIP/WebSocket ingress profiles | Android WebSocket messages (UGCP Runtime WS Profile) | `≈` | Android ingress is explicitly classified as a **UGCP Runtime WS Profile** on the center gateway side. Canonically bounded but not fully wire-unified. |
| `device_register` POST / WS | Android `device_register` WS message | `≡` | Handled via `android_bridge` registration handler → UDM registration write. Canonical. |
| `heartbeat` / status | `heartbeat` / `device_status` / `agent_status` | `→` | Android variants are compat aliases; all normalize to center-side heartbeat/status semantics. |
| `capability_report` | `capability_report` | `≡` | Handled via capability handler → gateway capability registry + `CapabilityRegistry`. Canonical. |
| `delegated_execution_signal` | `delegated_execution_signal` | `≡` | Dedicated canonical ingress: `core.android_delegated_signal_ingress`. Canonical in both repos. |
| `file_transfer` family | Android `file_transfer` | `→` | Explicitly recognized as a runtime transfer-family ingress; currently compat-forwarded (bounded) through gateway generic-forward ACK path. Not yet canonically unified. |
| `peer_announce` / `peer_exchange` / `mesh_topology` | Android mesh-family messages | `→` | Explicitly recognized as runtime mesh-family ingress; currently compat-forwarded (bounded). Pending deeper canonical mesh-routing convergence. |

---

## 7) Registry, facade, cache, adapter, and authority surfaces

### 7.1 Registry surfaces

| center surface | role | android equivalent | cls | notes |
|---|---|---|---|---|
| `NodeFabricRegistry` (`core.nodes.node_fabric_registry`) | Canonical runtime node registry | None | `≠` | Center-side canonical authority (`CANONICAL_RUNTIME_NODE_REGISTRY_AUTHORITY`). No android equivalent. |
| `NodeRegistry` (`core.node_registry`) | **Compat facade** (non-authoritative) | None | `≠` | `LEGACY_NODE_REGISTRY_IS_COMPAT_FACADE_SENTINEL`. Must not be treated as canonical. |
| UDM (`UnifiedDeviceManager`) | SSOT device truth write authority | None (android is a subject) | `≠` | Center-side SSOT write authority. Android provides inputs; UDM is the resolver. |
| `CapabilityRegistry` (gateway) | Capability sync/projection surface | Android capability report target | `≈` | Android capability reports are synced into this registry at center ingress. Not an independent authority; derived from UDM and reported device capability evidence. |
| `AttachedRuntimeSessionRegistry` (`core.attached_runtime_session_registry`) | Runtime attachment session truth | Android runtime attachment state | `≈` | Center is the authoritative registry for active runtime session state. Android attachment events are inputs. |

### 7.2 Facade and adapter surfaces

| center surface | classification | android equivalent | cls | notes |
|---|---|---|---|---|
| `NodeRegistry` (`core.node_registry`) | **Compat facade** | None | `≠` | Non-authoritative. Must not be extended as canonical architecture. |
| `fusion_entry.py` (`templates/node_template/fusion_entry.py`) | **Execution adapter** only (`FUSION_ENTRY_IS_EXECUTION_ADAPTER`) | None | `≠` | Not a registry/discovery surface. No android equivalent. |
| `CommandRouter.route_command` | **Compat shim** (non-canonical entry path) | None | `≠` | Explicitly registered as `legacy_paths` in `core.orchestration_authority`. Not canonical for new work. |
| `core.routes.tasks.create_task` | **Compat route adapter** | None | `≠` | Explicitly registered as `legacy_paths`. Not canonical for new work. |
| `android_bridge` gateway handler | **Canonical ingress adapter** for android protocol | Android WebSocket client | `≡` | This adapter is explicitly canonical for android protocol ingress. It is the designated normalization point. |

### 7.3 Cache and projection surfaces

| center surface | classification | android equivalent | cls | notes |
|---|---|---|---|---|
| `node_status_cache` | **Compat-only** cache (`COMPAT_ONLY` per PR-13 boundary enforcement) | None | `≠` | Non-authoritative cache layer. Must not be treated as canonical node-count or node-status truth. |
| `core.routes.projection.py` (projection plane) | **Read-only compiled view** (non-authoritative) | None | `≠` | Projection is a read-only surface. Android does not have an equivalent projection plane; center projection outputs may be consumed by android UI surfaces. |
| `RuntimeSessionSnapshot` (`contracts.runtime_session_snapshot`) | **Durable read-model** (projection surface, not write authority) | Android runtime snapshot (evidence) | `≈` | Center snapshot is compiled from canonical session truth. Android runtime state may contribute to snapshot assembly as evidence, not as truth origin. |
| `OutwardRuntimeTruth` (`core.outward_runtime_truth`) | **Read-only projection output** | Android-facing truth surface | `≈` | Android may consume center-projected runtime truth via API. Not a write authority. |

### 7.4 Authority surfaces

| center surface | classification | android equivalent | cls | notes |
|---|---|---|---|---|
| `canonical_session_truth` (`core.canonical_session_truth`) | **SSOT write authority** for control-plane truth | None (android is a truth subject) | `≠` | Android provides events; center writes canonical session truth. |
| `runtime_truth_compiler` (`core.projection.runtime_truth_compiler`) | **Truth compilation surface** (read-only downstream) | None | `≠` | Compiles canonical truth into projection output. Not a write authority. |
| `ugcp_truth_event_model` (`core.ugcp_truth_event_model`) | **Truth event semantics backbone** | None | `≠` | Defines canonical event semantics for truth writes. Android side emits delegated execution signals that feed this backbone, but the backbone itself is center-side. |

---

## 8) Runtime identity and capability-provider structures

### 8.1 Runtime identity

| center concept / surface | android concept / surface | cls | notes |
|---|---|---|---|
| `RuntimeParticipantIdentity` (`contracts.registered_runtime_device`) | Android runtime actor identity | `≈` | Center contract type for participant identity linkage, kept separate from device identity. Android runtime actor identity maps into this field via `from_android_registration(...)`. |
| `runtime_session_id` (attachment session identity) | Android `attached_session_id` / `runtime_session_id` | `→` | `attached_session_id` is a transitional alias. Center registry is the resolution authority. |
| `source_node_id` / `target_node_id` (graph node identity) | No android equivalent | `≠` | These are graph-node identities (task graph / topology graph), not runtime-participant identities. Android has no graph-node concept. |
| `execution_instance_id` (canonical execution attempt identity) | Android execution attempt identifier (`dispatch_id` family) | `→` | Canonical target name; transitional alias `dispatch_id`/`dispatch_record_id` used on center side during convergence. |

### 8.2 Capability provider structures

| center concept / surface | android concept / surface | cls | notes |
|---|---|---|---|
| `RuntimeCapabilityProfile` (`contracts.registered_runtime_device`) | Android capability profile (reported at registration/sync) | `≈` | Same conceptual scope (declared capability surface), different implementation. Android reports capabilities as evidence; center canonical form is `RuntimeCapabilityProfile`. |
| `CapabilityContract` (`core.unified.capability_contract`) | Android capability report payload | `≈` | Center has a typed contract; Android sends capability data as payload fields. Canonical contract is the convergence target. |
| Capability assimilation (`core.capability_assimilation_layer`, compat path) | Android capability reports as assimilation input | `≈` | Compat assimilation path bridges android capability evidence into center-side routing. Not the canonical long-term path. |
| `node_cognition_activation` (`core.node_cognition_activation`) | No android equivalent | `≠` | Node-domain capability activation concept for cognition roles (PLANNING/ACTING/SENSING etc.). Purely center-side concept. |
| `RuntimeAutonomySummary` (`contracts.registered_runtime_device`) | Android local autonomy / remote handoff readiness | `≈` | Center contract surface capturing android-side autonomy and handoff readiness evidence. Derives from Android-reported state. |

---

## 9) Source dispatch and orchestration concepts

| center concept / surface | android concept / surface | cls | notes |
|---|---|---|---|
| `SourceDispatchOrchestrator` (`core.runtime.source_dispatch_orchestrator`) | No direct android equivalent | `≠` | Center-side dispatch orchestrator. Android is a dispatch *target*, not a dispatch orchestrator. |
| `SourceDispatchMode` enum (`contracts.source_dispatch`) | Android route tag family | `→` | Android route tags (local/cross-device/delegated/fallback) are interpreted as dispatch mode evidence at center ingress. |
| `LocalRuntimeHost` (`contracts.local_runtime_host`) | Android as execution participant from center perspective | `≈` | Center contract for the local runtime host role. Android participates as a remote runtime host in the cross-device execution chain; the local host contract governs the center-side participant. |
| `HandoffEnvelopeV2` (`contracts`) | Android handoff/delegation initiation event | `≈` | Center has a typed handoff envelope; Android side initiates or receives handoffs. Semantics are aligned but wire-level union is in-progress. |
| `MeshSession` (`contracts.mesh_session`) | Android mesh participation record | `≈` | Android participates as a `MeshSessionParticipant` with `device_id`, `roles`, and `authority_scope`. Semantics are aligned. |

---

## 10) Summary of unresolved divergences

The following concepts have no confirmed cross-repository mapping as of this baseline. They require explicit convergence work before being treated as equivalent.

| concept area | center surface | android surface | notes |
|---|---|---|---|
| Node-domain governance | `NodeFabricRegistry`, `NodeInvocationGovernance`, node boundary surfaces | No android equivalent | Android participates in device domain only. Node domain is center-side only. |
| Conversation session model | Center conversation session concept | Android conversation/chat session | Different local models; not yet unified at protocol level. |
| Graph-node identity (`source_node_id`, `target_node_id`) | Task graph / topology graph | No android equivalent | Topology graph node identity is not the same as runtime participant identity. |
| Cognition activation (`node_cognition_activation`, `InfluenceClass`, etc.) | Center cognitive runtime model | No android equivalent | Cognitive activation and runtime decision observability layers are center-side only. |
| Model routing / `multimodal_route` | `core.openclawd`, `ContinuumState` | No android equivalent | Multi-model intelligent routing supply is a center-side concern. |
| Transfer vs delegation session boundary | `delegation_transfer_session` concept | Android transfer/delegation lifecycle | Both repos describe transfer/delegation lifecycle; exact session-boundary semantics are not yet unified. |
| `peer_announce` / `peer_exchange` / `mesh_topology` | Compat-forwarded; pending canonical mesh-routing convergence | Android mesh topology messages | Deeper canonical mesh-routing convergence deferred to later PRs. |

---

## 11) Stability and non-overclaim note

This document freezes the **mapping model** — not the implementation state.

- `≡` (CANONICAL_MATCH) entries are safe to treat as equivalent for convergence work.
- `≈` (PARTIAL_MATCH) entries should be treated as equivalent only within the described scope boundaries.
- `→` (TRANSITIONAL_ALIAS) entries identify where local names remain valid during convergence but should not be extended as canonical architecture.
- `≠` (UNRESOLVED_DIVERGENCE) entries must not be assumed equivalent until a follow-up convergence PR explicitly resolves them.

This baseline is not a claim that all listed mappings are already implemented at the wire/protocol level. Incremental convergence PRs targeting specific families (session, protocol, registry, dispatch) should update this document as alignment matures.
