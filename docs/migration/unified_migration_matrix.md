# Unified Migration Matrix

**Version:** 1.1
**Status:** Canonical — PR8 Final Closure (U1–U33 + PR-8 anti-drift)
**Owner:** core/unified/

---

## Purpose

This document provides the authoritative canonical-vs-legacy path mapping for the Galaxy Unified OpenClawd System.  
It covers all ingress/egress entry points, state mutation paths, and capability dispatch routes introduced across Blocks 1–6 (U1–U33).

---

## 1. Ingress Path Matrix

| Legacy Path | Canonical Path | Adapter | Status |
|---|---|---|---|
| `core/connection_manager.ConnectionManager` | `core/unified/connection_manager.UnifiedConnectionManager` | `core/legacy_adapters/connection_manager_adapter.py` | ✅ Adapted |
| `core/device_agent_manager.DeviceAgentManager` | `core/unified/device_manager.UnifiedDeviceManager` | `core/legacy_adapters/device_agent_manager_adapter.py` | ✅ Adapted |
| Direct `core/openclawd.handle_chat()` call | `EntrypointRouter.route_request()` → `core/openclawd.handle_chat()` | `core/unified/entrypoint_router.py` (first-hop) | ✅ Canonical |
| Direct WebSocket handler (raw WS message) | `galaxy_gateway/app.py` → `EntrypointRouter` | `galaxy_gateway/transport/websocket_server.py` | ✅ Canonical |
| `/api/v1/chat` HTTP endpoint | `core/routes/chat.py` → `EntrypointRouter` | `core/unified/entrypoint_router.py` (stamps `entry_path=canonical`) | ✅ Canonical |
| `DesktopPresenceRuntime.handle_request()` (internal) | `EntrypointRouter.route_request()` wraps handler | `core/unified/entrypoint_router.py` (`via_legacy_adapter=False`) | ✅ Canonical |
| `core/legacy_adapters/*` (legacy callers) | `EntrypointRouter.route_request()` with `via_legacy_adapter=True` | All adapters in `core/legacy_adapters/` | ✅ Adapted |

---

## 2. State Mutation Path Matrix

| Legacy Write Path | Canonical Write Path | Guarded By | Status |
|---|---|---|---|
| Direct `_devices[id] = ...` | `UnifiedDeviceManager.register_device()` / `upsert_device_state()` | `scripts/audit_udm_write_paths.py` (AST scan) | ✅ Audited |
| Direct `device.status = ...` | `UnifiedDeviceManager.update_device_status()` | `scripts/audit_udm_write_paths.py` | ✅ Audited |
| Direct `device.capabilities = ...` | `UnifiedDeviceManager.register_device_from_dict()` | `scripts/audit_udm_write_paths.py` | ✅ Audited |
| `TaskLifecycle` direct dict writes | `TaskLifecycleManager.transition()` + `StateEventBus.emit()` | `core/task_lifecycle.py` | ✅ Canonical |
| Raw heartbeat update | `UnifiedDeviceManager.heartbeat()` | `DeviceHealthScorer` consumer | ✅ Canonical |

---

## 3. Command/Envelope Path Matrix

| Legacy Format | Canonical Format | Transformer | Status |
|---|---|---|---|
| Raw AIP v2 dict (`galaxy_gateway/aip_protocol_v2.py`) | `AIPMessage` (`galaxy_gateway/protocol/aip_v3.py`) | `galaxy_gateway/protocol/compat.py` | ✅ Compat shim |
| Raw task dict | `CommandEnvelope` (`core/unified/command_envelope.py`) | `CommandEnvelope.from_aip_message()` / `from_task_envelope()` | ✅ Canonical |
| Legacy multi-device submission (individual `submit_task()`) | `run_multi_device_via_task_graph()` → DAG | `core/e2e_orchestrator.py` | ✅ Canonical |

---

## 4. Capability Dispatch Path Matrix

| Legacy Path | Canonical Path | Contract | Status |
|---|---|---|---|
| Direct `skill_registry.get_skill()` call | `CapabilityResolver.resolve()` | `core/unified/capability_contract.py` (validates contract) | ✅ Canonical |
| Direct MCP tool call (no registry) | `CapabilityRegistry.inject_mcp_tool()` → validated | `CapabilityContract` + `CapabilityRegistry` | ✅ Canonical |
| Node capability injection (legacy dict) | `NodeFabricRegistry.sync_capabilities_to_registry()` → `inject_item()` | `core/nodes/node_fabric_registry.py` | ✅ Canonical |

---

## 5. Transport/Event Path Matrix

| Legacy Topic/Event | Canonical Topic/Event | Transport | Status |
|---|---|---|---|
| Ad-hoc NATS publish (unstructured) | `NATSTopics.*` constants + `publish_*_event()` | `core/nats_bus.py` | ✅ Canonical |
| Raw state dict | `StateEvent` + `StateEventType` enum | `core/state_event_bus.py` | ✅ Canonical |
| Legacy AIP v2 envelope for device commands | AIP v3 envelope (`AIPMessage`) | `galaxy_gateway/protocol/aip_v3.py` | ✅ Canonical |

---

## 6. LLM Routing Path Matrix

| Legacy Path | Canonical Path | Policy File | Status |
|---|---|---|---|
| Direct `openai.ChatCompletion.create()` | `UnifiedLLMRouter.route()` | `config/llm_routing_policy.yaml` | ✅ Canonical |
| Hard-coded model selection | Policy-driven provider resolution + SLO filter + fallback | `core/unified/llm_router.py` | ✅ Canonical |
| No cost budget enforcement | `_check_cost_budget()` in LLMRouter | `config/llm_routing_policy.yaml` `global_slo` | ✅ Canonical |

---

## 7. Adapter Coverage Summary

| Adapter | Wraps | Delegates To | Legacy Compatibility |
|---|---|---|---|
| `core/legacy_adapters/connection_manager_adapter.py` | `ConnectionManager` | `UnifiedConnectionManager` | ✅ Full |
| `core/legacy_adapters/device_agent_manager_adapter.py` | `DeviceAgentManager` | `UnifiedDeviceManager` | ✅ Full |
| `galaxy_gateway/protocol/compat.py` | AIP v2 format | AIP v3 `AIPMessage` | ✅ Full |
| `galaxy_gateway/aip_protocol_v2.py` | AIP v2 legacy stub | Deprecated; import guard in CI | ✅ Guarded |

---

## 8. Known Bypass Paths (Flagged / Resolved)

| Bypass | Risk | Resolution |
|---|---|---|
| Direct `_devices` dict mutation | UDM SSOT violation | Blocked by `audit_udm_write_paths.py` (exit code 1) |
| `aip_protocol_v2` import outside stub | Protocol drift | Blocked by CI `v3-protocol-guard` job |
| `submit_task()` without DAG for multi-device | Ordering/dependency loss | Replaced by `run_multi_device_via_task_graph()` |
| New parallel single-device schema outside `registered_runtime_device.py` | Read contract fragmentation | Detected by `audit_udm_write_paths.py` PR-8 anti-drift (non-blocking warning) |
| New top-level multi-device read model outside `multi_device_runtime_projection.py` | Projection authority fragmentation | Detected by `audit_udm_write_paths.py` PR-8 anti-drift (non-blocking warning) |
| New `_devices`/`_device_map` field outside UDM SSOT | Parallel device registry | Detected by `audit_udm_write_paths.py` PR-8 anti-drift (non-blocking warning) |

---

## 8a. PR-8 Top-Level Read Closure (Anti-Drift)

PR-8 finalises the top-level multi-device runtime read closure.

### Read Projection Authority (final)

| Module | Classification | Role |
|--------|---------------|------|
| `contracts/registered_runtime_device.py` (`RegisteredRuntimeDevice`) | **Canonical sole** | Only canonical single-device read contract |
| `contracts/multi_device_runtime_projection.py` (`MultiDeviceRuntimeProjection`) | **Canonical sole** | Only canonical top-level multi-device read projection |

### PR-8 Additions

| Addition | Purpose |
|---|---|
| `CANONICAL_TOP_LEVEL_PROJECTION` sentinel (module-level `bool`) | Allows audit tooling to assert canonical status programmatically |
| `__canonical_authority__` string (module-level) | Human-readable canonical authority declaration |
| `from_registered_runtime_device()` adapter | Explicitly anchors device entries in the projection on `RegisteredRuntimeDevice` |
| `projection_from_registered_runtime_device` re-export in `contracts/__init__.py` | Discoverable canonical adapter for downstream consumers |
| PR-8 anti-drift guards in `audit_udm_write_paths.py` | Detects `parallel_single_device_schema`, `parallel_multi_device_projection`, `parallel_device_registry` patterns |
| `tests/test_pr8_top_level_projection_consolidation.py` (55 tests) | Regression coverage for canonical anchoring, anti-drift, and end-to-end unified flow |

---

## 9. References

- `docs/architecture/unified_system_contract.md` — Master ingress/state/event rules
- `docs/architecture/module_ownership_map.md` — Module owners and legacy mapping
- `docs/architecture/unified_device_registration_runtime_participation_v1.md` — V1 device registration authority spec
- `core/unified/entrypoint_router.py` — Canonical first-hop router
- `core/legacy_adapters/` — All legacy-to-canonical adapters
- `scripts/audit_udm_write_paths.py` — UDM SSOT write path auditor + PR-8 anti-drift guards
- `scripts/audit_unified_paths.py` — Canonical ingress/egress path auditor (PR7)
- `tests/conformance/` — Conformance test suite
- `docs/UNIFIED_MULTI_DEVICE_RUNTIME_PROJECTION.md` — Full specification including PR-8 closure

---

## 10. Device Registration Authority Matrix (PR-1)

> This section reflects the V1 authority model established in
> `docs/architecture/unified_device_registration_runtime_participation_v1.md`.
> It is the normative reference for all follow-up device-related PRs.

### 10.1 Canonical Write Authority

| Module | Classification | Write role |
|--------|---------------|------------|
| `core/unified/device_manager.py` (`UnifiedDeviceManager`) | **Canonical** | Only canonical write SSOT for device registration and mutable state |

All other modules must write device state through `UnifiedDeviceManager`. Direct mutation of device state outside UDM is prohibited.

### 10.2 Canonical Read Contracts

| Module | Classification | Read role |
|--------|---------------|-----------|
| `contracts/registered_runtime_device.py` (`RegisteredRuntimeDevice`) | **Canonical** | Only canonical single-device read contract |
| `contracts/multi_device_runtime_projection.py` (`MultiDeviceRuntimeProjection`) | **Canonical** | Only canonical top-level multi-device read projection; sits above `RegisteredRuntimeDevice` |

### 10.3 Registration Path Classification

| Path | Module | Classification |
|------|--------|---------------|
| HTTP REST registration | `core/routes/devices.py` | Canonical external registration entrypoint |
| Android WebSocket registration | `galaxy_gateway/android_bridge.py` | Adapted — transport registration adapter |
| Agent lifecycle registration | `core/device_agent_manager.py` | Adapted — agent lifecycle registration adapter |
| Runtime connection registration | `galaxy_gateway/device_router.py` | Runtime-only — runtime connection and routing layer |
| Legacy registry registration | `core/device_registry.py` | Legacy-compatible — indexing/persistence adapter |

### 10.4 Orchestration and Coordination Classification

| Module | Classification | Role |
|--------|---------------|------|
| `galaxy_gateway/cross_device_coordinator.py` | Orchestration-only | Cross-device dispatch and eligibility routing; reads canonical contracts |
| `core/swarm_coordinator.py` | Orchestration-only | Multi-agent orchestration; reads canonical contracts |
| `nodes/Node_71_MultiDeviceCoordination/` | Future normalization target | Multi-device coordination; targeted for progressive alignment to canonical contracts |

### 10.5 Migration Classification Legend (Device Domain)

| Classification | Meaning |
|---------------|---------|
| **Canonical** | The single source of truth or canonical contract; do not bypass |
| **Adapted** | Has a registered adapter that delegates to the canonical module; supported |
| **Legacy-compatible** | Retained for backward compatibility; must not shadow canonical state |
| **Runtime-only** | Tracks live runtime connections only; does not hold canonical device identity |
| **Orchestration-only** | Reads canonical contracts; does not hold canonical device state |
| **Future normalization target** | Targeted for progressive alignment to canonical contracts in a follow-up PR |
