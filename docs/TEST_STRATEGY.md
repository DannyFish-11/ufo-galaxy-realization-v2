# Galaxy — Test Strategy

This document describes the test strategy, layout, and CI guardrails for the
Galaxy repository.  See also `tests/README.md` for running instructions.

---

## Principles

1. **All tests live under `tests/`.**  Source packages (`core/`, `galaxy_gateway/`,
   `nodes/`, `enhancements/`, etc.) must not contain test files.  CI enforces
   this with the `test-placement-guard` job.

2. **Tests are discoverable and runnable without a live server** unless
   explicitly marked `@pytest.mark.manual`.

3. **Markers control CI inclusion:**

   | Marker | CI behaviour |
   |--------|-------------|
   | *(none)* | Runs in standard `test` CI job |
   | `slow` | Excluded from fast CI (`-m "not slow"`) |
   | `manual` | Always skipped in CI; run explicitly with `-m manual` |
   | `s6_smoke` | Runs in dedicated `s6-compat-smoke` CI job |
   | `g7_smoke` | Runs in dedicated `g7-quick-smoke` CI job |

4. **Test hierarchy:**

   ```
   tests/unit/          Pure unit tests — no I/O, no live services
   tests/integration/   Multi-module tests; some require live services (mark manual)
   tests/e2e/           End-to-end flows
   tests/conformance/   Protocol/contract conformance
   tests/chaos/         Resilience/chaos tests
   tests/test_*.py      Flat unit/component tests
   ```

---

## CI jobs that run tests

| CI job | Scope | File(s) |
|--------|-------|---------|
| `test` | All non-slow, non-manual tests | `tests/` |
| `test-placement-guard` | Structural — no in-source test files | all source dirs |
| `s6-compat-smoke` | Legacy/compat guardrails | `tests/test_s6_regression_compat_guardrails.py` |
| `slo-metrics-check` | SLO metrics validation | `tests/test_slo_metrics.py` |
| `supply-chain-hash-gate` | Dependency supply-chain | `tests/test_supply_chain.py` |
| `config-preflight-dry-run` | Config governance | `tests/test_config_preflight.py` |
| `g7-quick-smoke` | Developer experience | `tests/test_g7_smoke.py` |
| `conformance-tests` | AIP v3 / gateway / NATS / UDM | `tests/conformance/` |
| `chaos-tests` | Resilience | `tests/chaos/` |
| `ssot-udm-conformance` | UDM SSOT write paths | `tests/conformance/test_udm_ssot_conformance.py` |
| `system-readiness-check` | System readiness report | `tests/test_pr7_final_consolidation.py` |
| `governance-tests` | Node audit / repo hygiene | `tests/test_pr6_node_audit.py`, `tests/test_repo_hygiene.py` |

---

## Adding new tests

### Unit test
```python
# tests/test_my_feature.py
def test_my_feature():
    from core.my_module import my_function
    assert my_function(1) == 2
```

### Integration test (no live service)
```python
# tests/integration/test_my_integration.py
def test_cross_module_flow():
    ...
```

### Manual / live-service test
```python
# tests/integration/test_my_live_test.py
import pytest

@pytest.mark.manual
@pytest.mark.skip(reason="Requires live <service> — run manually")
def test_my_live_service():
    ...
```

---

## Relocated in-source tests

The following test files were previously located inside source packages.
They have been moved to `tests/integration/` and the originals replaced with
stub redirect files:

| Original location | Canonical location | Notes |
|-------------------|--------------------|-------|
| `galaxy_gateway/test_gateway_v3.py` | `tests/integration/test_gateway_v3.py` | Manual — requires live gateway |
| `galaxy_gateway/test_nlu_v2.py` | `tests/integration/test_nlu_v2.py` | Manual — requires live NLU |
| `nodes/Node_95_WebRTC_Receiver/test_node95.py` | `tests/integration/test_node95_webrtc.py` | Manual — requires live Node_95 |
| `nodes/Node_108_MetaCognition/test_metacognition.py` | `tests/integration/test_node108_metacognition.py` | Skipped — requires node module |
| `enhancements/bridges/test_bridge.py` | `tests/integration/test_bridge.py` | Manual — requires bridge module |

---

## Related documents

- `tests/README.md` — running instructions and directory layout
- `docs/DEPLOYMENT_SURFACES.md` — deployment surface catalogue
- `.github/workflows/ci.yml` — CI pipeline definition
