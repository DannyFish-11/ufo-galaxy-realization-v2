# Galaxy — Test Layout

This directory is the **single canonical home for all project tests**.
Do not add test files to source packages (`core/`, `galaxy_gateway/`,
`nodes/`, `enhancements/`, etc.) — all tests live here.

---

## Directory structure

Tests are organised by **capability domain**.  New tests should always land
in the appropriate domain directory rather than in the flat top-level.

```
tests/
├── README.md               ← this file
├── MIGRATION_MAP.md        ← old test_prXX_* → new canonical path mapping
├── __init__.py
├── conftest.py             ← shared fixtures (pytest)
├── fixtures/               ← shared fixture data and helpers
│
├── unit/                   ← pure unit tests with no live I/O
│   ├── gateway/            ← galaxy_gateway app, middleware, routes
│   │   └── test_gateway_slimming.py
│   ├── protocol/           ← AIP v3 message contracts and protocol helpers
│   ├── routing/            ← device selection, dispatch, session adapter
│   │   ├── test_device_pool_routing.py
│   │   ├── test_device_router_session_adapter.py
│   │   └── test_device_routing_dispatch_separation.py
│   ├── runtime/            ← OpenClawd, DesktopPresenceRuntime, AgentKernel
│   │   └── test_openclawd_subject_core.py
│   └── config/             ← ConfigStore, ConfigSchema, config_preflight
│       └── test_unified_local_config.py
│
├── integration/            ← tests that exercise multiple modules together
│   ├── android_bridge/     ← AndroidBridge modularization & handler tests
│   │   └── test_android_bridge_modularization.py
│   ├── chat/               ← /api/v1/chat adapter surface
│   │   └── test_chat_adapter_surface.py
│   ├── sessions/           ← session lifecycle and state management
│   ├── websocket/          ← AIP v3 WS contracts and WebSocket flows
│   │   └── test_aip_v3_ws_contracts.py
│   ├── test_gateway_v3.py          [manual] Gateway v3 end-to-end script
│   ├── test_nlu_v2.py              [manual] NLU v2 evaluation script
│   ├── test_node95_webrtc.py       [manual] Node_95 WebRTC live test
│   ├── test_node108_metacognition.py  [skip]  Node_108 unit tests
│   ├── test_bridge.py              [manual] Bridge compatibility test
│   └── runtime/            ← runtime integration scenarios
│
├── e2e/                    ← end-to-end flows (may require live services)
│   ├── __init__.py
│   └── test_e2e_runtime_scenarios.py
│
├── conformance/            ← protocol/contract conformance tests
│   ├── __init__.py
│   ├── test_aip_v3_envelope.py
│   ├── test_gateway_routing.py
│   ├── test_nats_trace.py
│   └── test_udm_ssot_conformance.py
│
├── chaos/                  ← chaos/resilience tests
│   ├── __init__.py
│   ├── test_disconnect_chaos.py
│   ├── test_latency_chaos.py
│   ├── test_duplicate_message_chaos.py
│   └── test_partial_failure_chaos.py
│
└── test_*.py               ← legacy flat tests (being migrated to domain dirs)
```

See `MIGRATION_MAP.md` for the mapping of old `test_prXX_*` names to their
new canonical locations.

---

## Pytest markers

| Marker | Meaning |
|--------|---------|
| `slow` | Long-running tests — skipped by default (`-m "not slow"`) |
| `manual` | Require live services — **always** skipped in CI; run with `-m manual` |
| `s6_smoke` | PR-S6 legacy/compat guardrail smoke suite |
| `g7_smoke` | PR-G7 developer-experience quick-verify smoke suite |

---

## Running tests

```bash
# Fast CI-safe run (excludes slow and manual):
pytest tests/ -m "not slow and not manual"

# All tests (excluding manual live-service tests):
pytest tests/ -m "not manual"

# Run a specific domain:
pytest tests/unit/routing/ -v --tb=short
pytest tests/integration/android_bridge/ -v --tb=short

# Conformance / protocol tests:
pytest tests/conformance/ -v --tb=short

# Chaos tests:
pytest tests/chaos/ -v

# Single file:
pytest tests/unit/gateway/test_gateway_slimming.py -v
```

---

## Adding new tests

1. **Unit tests** — add in the appropriate `tests/unit/<domain>/` directory.
2. **Integration tests** — add in `tests/integration/<domain>/`.
3. **E2E tests** — add in `tests/e2e/`.
4. **Manual / live-service tests** — add in `tests/integration/` or `tests/e2e/`,
   mark with `@pytest.mark.manual` and `@pytest.mark.skip(reason="...")`.

**Never** add test files to source packages.  The CI workflow enforces this
with a structural check (see `.github/workflows/ci.yml` → `test-placement-guard`).

### Domain guide

| Domain directory | What belongs there |
|---|---|
| `unit/gateway/` | `galaxy_gateway` app, routers, middleware, dependencies |
| `unit/protocol/` | AIP v3 message shapes, protocol helpers, envelope parsing |
| `unit/routing/` | Device selection, dispatch, routing policies, session adapter |
| `unit/runtime/` | OpenClawd, DesktopPresenceRuntime, AgentKernel, capability bus |
| `unit/config/` | ConfigStore, ConfigSchema, config_preflight, secrets handling |
| `integration/android_bridge/` | AndroidBridge handlers, modularization, transport cache |
| `integration/chat/` | Chat adapter surface, `/api/v1/chat` contract tests |
| `integration/sessions/` | Session lifecycle, state management, reconnect flows |
| `integration/websocket/` | AIP v3 WS contracts, WebSocket message flows |
