# Galaxy — Test Layout

This directory is the **single canonical home for all project tests**.
Do not add test files to source packages (`core/`, `galaxy_gateway/`,
`nodes/`, `enhancements/`, etc.) — all tests live here.

---

## Directory structure

```
tests/
├── README.md               ← this file
├── __init__.py
├── conftest.py             ← shared fixtures (pytest)
├── fixtures/               ← shared fixture data and helpers
│
├── unit/                   ← (future) pure unit tests with no I/O
│
├── integration/            ← tests that exercise multiple modules together
│   ├── __init__.py
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
└── test_*.py               ← all other unit/component tests (flat, alphabetical)
```

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

# Specific suite:
pytest tests/conformance/ -v --tb=short

# Manual integration tests (requires live services):
pytest tests/integration/test_gateway_v3.py -m manual

# Chaos tests:
pytest tests/chaos/ -v

# Single file:
pytest tests/test_canonical_execution_chain.py -v
```

---

## Adding new tests

1. **Unit tests** — add directly in `tests/` (flat) or `tests/unit/`.
2. **Integration tests** — add in `tests/integration/`.
3. **E2E tests** — add in `tests/e2e/`.
4. **Manual / live-service tests** — add in `tests/integration/` or `tests/e2e/`,
   mark with `@pytest.mark.manual` and `@pytest.mark.skip(reason="...")`.

**Never** add test files to source packages.  The CI workflow enforces this
with a structural check (see `.github/workflows/ci.yml` → `test-placement-guard`).
