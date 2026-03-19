# Module Ownership Map

**Version:** 1.0  
**Status:** Canonical (referenced by U2–U33)  
**See also:** `docs/architecture/unified_system_contract.md`

---

## 1. Purpose

This document maps every significant module in the Galaxy platform to its **canonical owner** (the unified core component that holds authoritative logic), lists its **legacy path** (the old module that still exists), and describes the **delegation rule** (how the legacy path routes into unified core).

---

## 2. Core Module Ownership Table

| Domain | Canonical Owner (unified) | Legacy Path(s) | Delegation Rule |
|--------|--------------------------|----------------|-----------------|
| **Ingress / Routing** | `core/unified/entrypoint_router.py` | `core/routes/chat.py`, `core/openclawd.py` direct callers | All ingress wraps `route_request()` first |
| **Primary Intelligence** | `core/openclawd.py` (PRIMARY role) | `core/master_brain.py`, `core/agent_kernel.py` | Legacy calls delegate to `OpenClawd.process()` |
| **Device Management (SSOT)** | `core/unified/device_manager.py` | `core/device_agent_manager.py`, `galaxy_gateway/handlers/device_manager.py`, `enhancements/multidevice/device_manager.py` | Adapters in `core/legacy_adapters/device_agent_manager_adapter.py` |
| **Connection Management** | `core/unified/connection_manager.py` | `core/connection_manager.py` | `core/legacy_adapters/connection_manager_adapter.py` |
| **LLM Routing** | `core/unified/llm_router.py` → `core/multi_llm_router.py` | `core/llm_manager.py` | `llm_manager.py` imports from `multi_llm_router.py` |
| **Skill / Capability** | `core/skill_registry.py` + `core/skill_contract.py` | `core/skill_loader.py`, `core/mcp_loader.py` | loaders register into registry on load |
| **Task Execution (DAG)** | `core/task_graph.py` + `core/e2e_orchestrator.py` | `core/orchestrator_engine.py`, legacy scheduler | orchestrators call `compile_and_run_dag()` |
| **Task Lifecycle** | `core/task_lifecycle.py` | direct status updates in older handlers | `mark_running/mark_done/mark_failed` API |
| **State / Event Bus** | `core/state_event_bus.py` | `integration/event_bus.py` | `_emit_lifecycle_event` bridges both |
| **State Schema** | `core/unified/state_schema.py` | ad-hoc dicts in individual modules | modules import typed dataclasses from schema |
| **Configuration** | `core/unified/config_manager.py` | `core/unified_config.py` | `unified_config.py` delegates to `UnifiedConfigManager` |
| **Transport / Gateway** | `galaxy_gateway/smart_transport_router.py` | `galaxy_gateway/aip_protocol_v2.py`, `galaxy_gateway/websocket_handler.py` | smart router selects transport; legacy kept for compat |
| **Protocol** | `galaxy_gateway/protocol/aip_v3.py` | `galaxy_gateway/aip_protocol_v2.py` | v2 messages normalised via `compat.py` |
| **Observability** | `galaxy_gateway/observability.py` + `core/continuum/metrics.py` | scattered `logger.info` calls | structured events emitted on StateEventBus |
| **Execution Policy** | `core/model_role_policy.py` | none (new in PR-2) | all executors call `assert_primary()` |
| **Resilience** | `core/resilience/` (circuit_breaker, adaptive_semaphore) | none | CommandRouter integrates resilience layer |

---

## 3. Legacy Adapter Index

| Adapter File | Wraps | Delegates To |
|---|---|---|
| `core/legacy_adapters/connection_manager_adapter.py` | `core/connection_manager.ConnectionManager` | `core/unified/connection_manager.UnifiedConnectionManager` |
| `core/legacy_adapters/device_agent_manager_adapter.py` | `core/device_agent_manager.DeviceAgentManager` | `core/unified/device_manager.UnifiedDeviceManager` |

---

## 4. Canonical Path Tags

Requests are stamped by `EntrypointRouter` with an `entry_path` tag:

| Tag | Meaning |
|-----|---------|
| `canonical` | Request entered via the unified entrypoint router directly |
| `legacy` | Request entered via a legacy module that delegated through an adapter |

The `via_legacy_adapter` boolean flag distinguishes calls that passed through a legacy adapter (`True`) from direct canonical callers (`False`).

---

## 5. Module Status Legend

| Status | Meaning |
|--------|---------|
| **canonical** | This is the single source of truth; do not bypass it |
| **legacy-delegating** | Still used externally; internally delegates to canonical owner |
| **deprecated** | Will be removed in a future phase; do not add new callers |
| **adapting** | Actively being migrated; dual-write or adapter in place |

---

## 6. Future Migration Notes

- `core/master_brain.py` → deprecated; route through `OpenClawd`
- `integration/event_bus.py` → adapting; new code should use `StateEventBus`
- `core/device_agent_manager.py` → legacy-delegating via adapter
- `core/connection_manager.py` → legacy-delegating via adapter
- `galaxy_gateway/aip_protocol_v2.py` → deprecated; migrate to AIP v3

---

## 7. References

- `docs/architecture/unified_system_contract.md` — System flow and rules
- `core/legacy_adapters/` — All adapter implementations
- `core/unified/` — All canonical unified modules
