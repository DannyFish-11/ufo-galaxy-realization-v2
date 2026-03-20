# Unified Migration Matrix

**Version:** 1.0  
**Status:** Canonical — PR7 Final Consolidation (U1–U33)  
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

---

## 9. References

- `docs/architecture/unified_system_contract.md` — Master ingress/state/event rules
- `docs/architecture/module_ownership_map.md` — Module owners and legacy mapping
- `core/unified/entrypoint_router.py` — Canonical first-hop router
- `core/legacy_adapters/` — All legacy-to-canonical adapters
- `scripts/audit_udm_write_paths.py` — UDM SSOT write path auditor
- `scripts/audit_unified_paths.py` — Canonical ingress/egress path auditor (PR7)
- `tests/conformance/` — Conformance test suite
