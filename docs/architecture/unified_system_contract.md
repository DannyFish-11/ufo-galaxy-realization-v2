# Unified System Contract

**Version:** 1.0  
**Status:** Canonical (referenced by U2–U33)  
**Owner:** core/unified/

---

## 1. Purpose

This document defines the **canonical system flow** for the Galaxy platform and establishes the rules that every module — including legacy modules — must follow when handling ingress requests, delegating execution, managing state, and emitting events.

All future PRs (U2–U33) must reference this contract and remain additive. No PR may violate the delegation rules described here.

---

## 2. Canonical System Flow

```
User / UI / Android App / Dashboard
          │
          ▼
  ┌─────────────────────┐
  │  Entrypoint Router  │  core/unified/entrypoint_router.py
  │  (first-hop, always)│  stamps: entry_path, via_legacy_adapter, trace_id
  └──────────┬──────────┘
             │
             ▼
  ┌─────────────────────┐
  │     OpenClawd        │  core/openclawd.py
  │  (primary authority) │  model-role: PRIMARY
  └──────────┬──────────┘
             │
     ┌───────┴────────┐
     │                │
     ▼                ▼
┌─────────┐    ┌──────────────┐
│Capability│    │  Task Graph  │  core/task_graph.py
│   Bus   │    │  (DAG exec)  │  galaxy_gateway/orchestrator/
└────┬────┘    └──────┬───────┘
     │                │
     ▼                ▼
┌──────────────────────────────┐
│  Galaxy Gateway / Device     │  galaxy_gateway/app.py
│  Transport (WS/WebRTC/NATS)  │  galaxy_gateway/smart_transport_router.py
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│  State / Event Bus           │  core/state_event_bus.py
│  (unified state schema)      │  core/unified/state_schema.py
└──────────────────────────────┘
```

---

## 3. Ingress Rules

1. **Every ingress request MUST pass through `EntrypointRouter.route_request()`** before reaching OpenClawd or any other handler. This applies to:
   - `/api/v1/chat` (HTTP)
   - WebSocket connections (device and UI)
   - Internal runtime calls (DesktopPresenceRuntime)
   - Legacy module entry points (via adapters)

2. The router stamps each request with:
   - `entry_path`: `"canonical"` or `"legacy"`
   - `via_legacy_adapter`: `True` when routed through a legacy adapter
   - `trace_id`: globally unique, used for end-to-end correlation

3. **OpenClawd is the sole PRIMARY decision authority.** All other modules (orchestrators, executors, transports) operate in EXECUTE or RELAY roles. See `core/model_role_policy.py`.

---

## 4. State Mutation Rules

1. **Device state** must be written exclusively via `UnifiedDeviceManager` (`core/unified/device_manager.py`). No module may write device state directly to any store.
2. **Task state** transitions must be emitted via `TaskLifecycleManager` (`core/task_lifecycle.py`).
3. **All state change events** must be published on `StateEventBus` (`core/state_event_bus.py`) using the canonical `StateEvent` dataclass and typed `StateEventType` enum values.
4. Event payloads should conform to the unified state schema (`core/unified/state_schema.py`) wherever possible. Legacy payloads are tolerated but deprecated.

---

## 5. Legacy Module Rules

1. Legacy modules **MUST NOT be deleted**. They are kept for backward compatibility.
2. Legacy modules **MUST delegate** to unified core modules via adapters in `core/legacy_adapters/`.
3. Adapters keep the old public API surface (same function/class signatures) but route logic through unified core.
4. The `via_legacy_adapter=True` stamp on requests enables observability of legacy-path usage so migration can be tracked over time.

---

## 6. Capability Bus Contract

1. Capabilities (MCP tools, Skills, Device actions) are discovered and dispatched via `core/skill_registry.py` and `core/capability_manager.py`.
2. New capability types must register with the skill registry before being callable.
3. Capability invocations are wrapped in `SkillRequest`/`SkillResponse` contracts (`core/skill_contract.py`).

---

## 7. Event Bus Contract

1. All significant state changes MUST produce a `StateEvent` on the bus.
2. Subscribers must be idempotent and must not mutate shared state inside a subscriber callback.
3. Async subscribers are dispatched via `asyncio.create_task` to avoid blocking the emitter.

---

## 8. Transport Contract

1. The canonical transport selection is handled by `galaxy_gateway/smart_transport_router.py`.
2. Fallback order: WebRTC → WebSocket → NATS → REST.
3. All commands sent to devices must use the AIP v3 envelope format (`galaxy_gateway/protocol/aip_v3.py`).

---

## 9. Non-Goals

- This contract does **not** prescribe internal implementation details of individual modules.
- This contract does **not** enforce versioning of internal APIs.
- This contract does **not** replace operational runbooks or deployment guides.

---

## 10. References

- `docs/architecture/module_ownership_map.md` — Module owners and legacy mapping
- `core/unified/entrypoint_router.py` — Canonical entrypoint router
- `core/unified/state_schema.py` — Unified state data structures
- `core/legacy_adapters/` — Legacy adapter layer
- `core/model_role_policy.py` — Model role policy (PRIMARY vs EXECUTE/RELAY)
- `core/state_event_bus.py` — State/event bus
- `core/task_lifecycle.py` — Task lifecycle management
- `galaxy_gateway/protocol/aip_v3.py` — AIP v3 protocol
