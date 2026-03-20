"""
tests/test_pr5_block5_reliability.py
======================================
Block-5: Error Taxonomy + Idempotency + Global Arbiter + Chaos + Release Guardrails

Comprehensive test suite covering all Block-5 components:

1.  GalaxyErrorCode — taxonomy completeness, registry coverage
2.  ErrorPayload — construction, to_dict/from_dict, from_code
3.  ErrorMapper — exception mapping, legacy adapter mapping
4.  IdempotencyStore — check/record/conflict/eviction/stats
5.  GlobalArbiter — admit/release/preemption/quota/fairness
6.  ReleaseGate — is_enabled, require_enabled, overrides, rollback
7.  Integration — idempotency + command_envelope, arbiter + e2e_orchestrator
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_all() -> None:
    from core.unified.idempotency import reset_idempotency_store
    from core.unified.release_gate import reset_release_gate
    from core.orchestration.global_arbiter import reset_global_arbiter

    reset_idempotency_store()
    reset_release_gate()
    reset_global_arbiter()


# ===========================================================================
# 1. GalaxyErrorCode taxonomy
# ===========================================================================


class TestGalaxyErrorCodeTaxonomy:
    def test_all_codes_in_registry(self):
        from core.unified.error_codes import GalaxyErrorCode, ERROR_CODE_REGISTRY

        registry_keys = set()
        for k in ERROR_CODE_REGISTRY:
            registry_keys.add(k.value if hasattr(k, "value") else str(k))

        for code in GalaxyErrorCode:
            assert code.value in registry_keys, f"Missing registry entry for {code}"

    def test_code_values_are_unique(self):
        from core.unified.error_codes import GalaxyErrorCode

        values = [c.value for c in GalaxyErrorCode]
        assert len(values) == len(set(values)), "Duplicate code values found"

    def test_domain_coverage(self):
        from core.unified.error_codes import GalaxyErrorCode, ErrorDomain, _registry

        reg = _registry()
        domains_covered = {v.domain for v in reg.values()}
        required_domains = {
            ErrorDomain.PLANNER, ErrorDomain.EXECUTOR, ErrorDomain.GATEWAY,
            ErrorDomain.DEVICE, ErrorDomain.TRANSPORT, ErrorDomain.IDEMPOTENCY,
            ErrorDomain.ARBITER, ErrorDomain.RELEASE,
        }
        missing = required_domains - domains_covered
        assert not missing, f"Missing domain coverage: {missing}"

    def test_retryable_helper(self):
        from core.unified.error_codes import GalaxyErrorCode, is_retryable

        assert is_retryable(GalaxyErrorCode.TRANSPORT_DISCONNECT) is True
        assert is_retryable(GalaxyErrorCode.GW_AUTH_FAILED) is False
        assert is_retryable(GalaxyErrorCode.EXEC_TASK_TIMEOUT) is True
        assert is_retryable(GalaxyErrorCode.IDEMPOTENCY_DUPLICATE) is False

    def test_get_descriptor_returns_correct_domain(self):
        from core.unified.error_codes import GalaxyErrorCode, ErrorDomain, get_descriptor

        d = get_descriptor(GalaxyErrorCode.DEVICE_OFFLINE)
        assert d is not None
        assert d.domain == ErrorDomain.DEVICE


# ===========================================================================
# 2. ErrorPayload
# ===========================================================================


class TestErrorPayload:
    def test_from_code_basic_fields(self):
        from core.unified.error_codes import ErrorPayload, GalaxyErrorCode

        p = ErrorPayload.from_code(
            GalaxyErrorCode.DEVICE_TIMEOUT,
            message="device did not respond",
            trace_id="t-100",
            task_id="task-A",
        )
        assert p.code == "DV_002"
        assert p.domain == "device"
        assert p.trace_id == "t-100"
        assert p.task_id == "task-A"
        assert p.retryable is True

    def test_to_dict_from_dict_round_trip(self):
        from core.unified.error_codes import ErrorPayload, GalaxyErrorCode

        p = ErrorPayload.from_code(GalaxyErrorCode.GW_ENVELOPE_INVALID, message="bad envelope")
        restored = ErrorPayload.from_dict(p.to_dict())
        assert restored.code == p.code
        assert restored.description == p.description
        assert restored.retryable == p.retryable
        assert restored.severity == p.severity
        assert restored.message == p.message

    def test_each_payload_has_unique_error_id(self):
        from core.unified.error_codes import ErrorPayload, GalaxyErrorCode

        ids = {ErrorPayload.from_code(GalaxyErrorCode.EXEC_CANCELLED).error_id for _ in range(20)}
        assert len(ids) == 20

    def test_detail_dict_included(self):
        from core.unified.error_codes import ErrorPayload, GalaxyErrorCode

        p = ErrorPayload.from_code(
            GalaxyErrorCode.DEVICE_NOT_FOUND,
            detail={"device_id": "phone_01"},
        )
        assert p.detail["device_id"] == "phone_01"
        assert p.to_dict()["detail"]["device_id"] == "phone_01"

    def test_timestamp_is_recent(self):
        from core.unified.error_codes import ErrorPayload, GalaxyErrorCode

        before = time.time()
        p = ErrorPayload.from_code(GalaxyErrorCode.INTERNAL_UNKNOWN)
        after = time.time()
        assert before <= p.timestamp <= after


# ===========================================================================
# 3. ErrorMapper
# ===========================================================================


class TestErrorMapper:
    def test_map_stdlib_exceptions(self):
        from core.unified.error_mapper import ErrorMapper
        from core.unified.error_codes import GalaxyErrorCode

        cases = [
            (TimeoutError("t"), GalaxyErrorCode.EXEC_TASK_TIMEOUT),
            (PermissionError("p"), GalaxyErrorCode.GW_AUTH_FAILED),
            (ConnectionRefusedError("r"), GalaxyErrorCode.TRANSPORT_CONNECT_FAILED),
            (ConnectionResetError("rs"), GalaxyErrorCode.TRANSPORT_DISCONNECT),
        ]
        for exc, expected in cases:
            payload = ErrorMapper.from_exception(exc)
            assert payload.code == expected.value, f"Expected {expected} for {type(exc).__name__}"

    def test_map_unified_exception_by_name(self):
        from core.unified.error_mapper import ErrorMapper
        from core.unified.error_codes import GalaxyErrorCode

        class DeviceTimeoutError(Exception):
            pass

        payload = ErrorMapper.from_exception(DeviceTimeoutError("no reply"))
        assert payload.code == GalaxyErrorCode.DEVICE_TIMEOUT.value

    def test_map_exception_with_code_attr(self):
        from core.unified.error_mapper import ErrorMapper
        from core.unified.error_codes import GalaxyErrorCode

        class CustomErr(Exception):
            code = "DV_003"  # DEVICE_SEND_FAILED

        payload = ErrorMapper.from_exception(CustomErr("custom"))
        assert payload.code == GalaxyErrorCode.DEVICE_SEND_FAILED.value

    def test_unknown_exception_maps_to_internal(self):
        from core.unified.error_mapper import ErrorMapper
        from core.unified.error_codes import GalaxyErrorCode

        class WeirdError(Exception):
            pass

        payload = ErrorMapper.from_exception(WeirdError("?"))
        assert payload.code == GalaxyErrorCode.INTERNAL_UNKNOWN.value

    def test_from_legacy_gateway_error(self):
        from core.unified.error_mapper import ErrorMapper
        from core.unified.error_codes import GalaxyErrorCode

        p = ErrorMapper.from_legacy_gateway_error("auth_error", "token expired")
        assert p.code == GalaxyErrorCode.GW_AUTH_FAILED.value

    def test_from_legacy_device_error_capability(self):
        from core.unified.error_mapper import ErrorMapper
        from core.unified.error_codes import GalaxyErrorCode

        p = ErrorMapper.from_legacy_device_error(
            "dev_1", "device missing capability 'camera'"
        )
        assert p.code == GalaxyErrorCode.DEVICE_CAPABILITY_MISSING.value

    def test_from_legacy_executor_timeout(self):
        from core.unified.error_mapper import ErrorMapper
        from core.unified.error_codes import GalaxyErrorCode

        p = ErrorMapper.from_legacy_executor_error("task timed out after 30s")
        assert p.code == GalaxyErrorCode.EXEC_TASK_TIMEOUT.value

    def test_from_legacy_executor_preempt(self):
        from core.unified.error_mapper import ErrorMapper
        from core.unified.error_codes import GalaxyErrorCode

        p = ErrorMapper.from_legacy_executor_error("task was preempted by scheduler")
        assert p.code == GalaxyErrorCode.EXEC_PREEMPTED.value

    def test_from_dict_round_trip(self):
        from core.unified.error_mapper import ErrorMapper
        from core.unified.error_codes import GalaxyErrorCode, ErrorPayload

        orig = ErrorPayload.from_code(GalaxyErrorCode.ARBITER_QUOTA_EXCEEDED)
        restored = ErrorMapper.from_dict(orig.to_dict())
        assert restored.code == orig.code


# ===========================================================================
# 4. IdempotencyStore
# ===========================================================================


class TestIdempotencyStore:
    def setup_method(self):
        _reset_all()

    def test_new_key_returns_none(self):
        from core.unified.idempotency import check_idempotency, make_payload_hash

        h = make_payload_hash({"op": "new"})
        assert check_idempotency("new-key", h, raise_on_duplicate=False) is None

    def test_record_and_check_completed(self):
        from core.unified.idempotency import (
            check_idempotency, record_idempotency, make_payload_hash,
            IdempotencyStatus, DuplicateCommandError,
        )

        h = make_payload_hash("payload_x")
        record_idempotency("r-1", h, result={"done": True})

        try:
            check_idempotency("r-1", h)
        except DuplicateCommandError as e:
            assert e.cached_result == {"done": True}
        else:
            pytest.fail("Expected DuplicateCommandError")

    def test_in_flight_does_not_raise_duplicate(self):
        from core.unified.idempotency import (
            get_idempotency_store, check_idempotency, make_payload_hash, IdempotencyStatus
        )

        h = make_payload_hash("inflight")
        store = get_idempotency_store()
        store.record_in_flight("if-1", h)

        entry = check_idempotency("if-1", h, raise_on_duplicate=True)
        assert entry.status == IdempotencyStatus.IN_FLIGHT

    def test_failed_key_resubmittable(self):
        from core.unified.idempotency import (
            get_idempotency_store, check_idempotency, make_payload_hash, IdempotencyStatus
        )

        h = make_payload_hash("failed_op")
        store = get_idempotency_store()
        store.record_in_flight("fail-1", h)
        store.record_failed("fail-1")

        entry = check_idempotency("fail-1", h, raise_on_duplicate=True)
        assert entry.status == IdempotencyStatus.FAILED

    def test_conflict_detection(self):
        from core.unified.idempotency import (
            record_idempotency, check_idempotency, make_payload_hash, IdempotencyConflictError
        )

        h1 = make_payload_hash("payload_1")
        h2 = make_payload_hash("payload_2")
        record_idempotency("conf-1", h1)

        with pytest.raises(IdempotencyConflictError):
            check_idempotency("conf-1", h2, raise_on_conflict=True)

    def test_explicit_remove(self):
        from core.unified.idempotency import (
            get_idempotency_store, record_idempotency, make_payload_hash
        )

        h = make_payload_hash("rm_payload")
        record_idempotency("rm-1", h)

        store = get_idempotency_store()
        assert store.remove("rm-1") is True
        assert store.get("rm-1") is None

    def test_ttl_eviction(self):
        from core.unified.idempotency import (
            get_idempotency_store, make_payload_hash
        )

        store = get_idempotency_store()
        store.configure(ttl_seconds=0.01)

        h = make_payload_hash("ttl_test")
        store.record_in_flight("ttl-1", h)
        time.sleep(0.05)

        # Trigger eviction via next check
        store._evict_expired()
        assert store.get("ttl-1") is None

    def test_max_entries_eviction(self):
        from core.unified.idempotency import (
            get_idempotency_store, make_payload_hash
        )

        store = get_idempotency_store()
        store.configure(max_entries=5)

        for i in range(10):
            h = make_payload_hash(i)
            store.record_in_flight(f"max-key-{i}", h)

        assert len(store._store) <= 5


# ===========================================================================
# 5. GlobalArbiter
# ===========================================================================


class TestGlobalArbiter:
    def setup_method(self):
        _reset_all()

    def _fresh_arbiter(self, limit=10, quota=5):
        from core.orchestration.global_arbiter import get_global_arbiter, reset_global_arbiter

        reset_global_arbiter()
        arbiter = get_global_arbiter()
        arbiter.configure(global_limit=limit, per_origin_quota=quota)
        return arbiter

    def test_admit_within_limit(self):
        arbiter = self._fresh_arbiter(limit=5)
        d = arbiter.admit("t1", priority=3, origin="user:1")
        assert d.admitted is True
        assert d.outcome == "admitted"

    def test_reject_on_quota_exceeded(self):
        arbiter = self._fresh_arbiter(limit=10, quota=2)
        arbiter.admit("t1", priority=3, origin="user:1")
        arbiter.admit("t2", priority=3, origin="user:1")
        d3 = arbiter.admit("t3", priority=3, origin="user:1")
        assert d3.admitted is False
        assert "quota" in d3.reason

    def test_preemption_of_lower_priority(self):
        arbiter = self._fresh_arbiter(limit=1, quota=10)
        d_low = arbiter.admit("low", priority=1, origin="bg", preemptable=True)
        d_high = arbiter.admit("high", priority=10, origin="fg")
        assert d_low.admitted is True
        assert d_high.admitted is True
        assert d_high.preempted_task_id == "low"

    def test_non_preemptable_blocks_new_tasks(self):
        arbiter = self._fresh_arbiter(limit=1, quota=10)
        arbiter.admit("crit", priority=5, origin="sys", preemptable=False)
        d_new = arbiter.admit("new", priority=10, origin="user")
        assert d_new.admitted is False

    def test_release_frees_slot(self):
        arbiter = self._fresh_arbiter(limit=1, quota=10)
        arbiter.admit("t-a", priority=5, origin="u1")
        released = arbiter.release("t-a")
        assert released is True
        d_new = arbiter.admit("t-b", priority=5, origin="u2")
        assert d_new.admitted is True

    def test_disabled_arbiter_admits_all(self):
        arbiter = self._fresh_arbiter(limit=1, quota=1)
        arbiter.configure(enabled=False)
        for i in range(20):
            d = arbiter.admit(f"t{i}", priority=1, origin="u:any")
            assert d.admitted is True

    def test_stats_track_outcomes(self):
        arbiter = self._fresh_arbiter(limit=2, quota=10)
        arbiter.admit("s1", priority=1, origin="o1", preemptable=True)
        arbiter.admit("s2", priority=1, origin="o2", preemptable=True)
        arbiter.admit("s3", priority=9, origin="o3")  # preempts

        s = arbiter.stats()
        assert s["admitted"] >= 2

    def test_recent_decisions_returned(self):
        arbiter = self._fresh_arbiter()
        arbiter.admit("dec-1", priority=5, origin="u")
        decisions = arbiter.recent_decisions(n=5)
        assert len(decisions) >= 1
        assert decisions[-1]["task_id"] == "dec-1"

    def test_suggest_device_returns_least_loaded(self):
        arbiter = self._fresh_arbiter()
        arbiter.admit("t1", priority=5, origin="u", metadata={"device_id": "dev_A"})
        arbiter.admit("t2", priority=5, origin="u2", metadata={"device_id": "dev_A"})
        arbiter.admit("t3", priority=5, origin="u3", metadata={"device_id": "dev_B"})

        suggested = arbiter.suggest_device(["dev_A", "dev_B", "dev_C"])
        # dev_C has 0 tasks — should be preferred
        assert suggested == "dev_C"

    def test_list_running_reflects_state(self):
        arbiter = self._fresh_arbiter()
        arbiter.admit("run-1", priority=5, origin="o1")
        arbiter.admit("run-2", priority=3, origin="o2")
        running = arbiter.list_running()
        ids = {t["task_id"] for t in running}
        assert "run-1" in ids
        assert "run-2" in ids

    def test_fairness_different_origins_all_admitted(self):
        arbiter = self._fresh_arbiter(limit=5, quota=2)
        outcomes = [
            arbiter.admit(f"t{i}", priority=5, origin=f"user:{i}")
            for i in range(5)
        ]
        admitted_count = sum(1 for d in outcomes if d.admitted)
        assert admitted_count == 5


# ===========================================================================
# 6. ReleaseGate
# ===========================================================================


class TestReleaseGate:
    def setup_method(self):
        _reset_all()

    def _gate(self):
        from core.unified.release_gate import get_release_gate, reset_release_gate

        reset_release_gate()
        return get_release_gate()

    def test_override_false_disables(self):
        gate = self._gate()
        gate.override("my_feature", False)
        assert gate.is_enabled("my_feature") is False

    def test_override_true_enables(self):
        gate = self._gate()
        gate.override("my_feature", False)
        gate.override("my_feature", True)
        assert gate.is_enabled("my_feature") is True

    def test_clear_override_restores_default(self):
        gate = self._gate()
        gate.override("x", False)
        gate.clear_override("x")
        assert gate.is_enabled("x") is True  # unknown flags default to True

    def test_require_enabled_raises_feature_disabled(self):
        from core.unified.release_gate import FeatureDisabledError

        gate = self._gate()
        gate.override("feat_a", False)
        with pytest.raises(FeatureDisabledError) as exc_info:
            gate.require_enabled("feat_a")
        assert exc_info.value.flag == "feat_a"

    def test_require_enabled_passes_when_on(self):
        gate = self._gate()
        gate.override("feat_b", True)
        gate.require_enabled("feat_b")  # should not raise

    def test_stats_track_evaluations(self):
        gate = self._gate()
        gate.override("tracked", True)
        gate.is_enabled("tracked")
        gate.is_enabled("tracked")
        s = gate.stats()
        assert s["gate_stats"].get("tracked", {}).get("allowed", 0) >= 2

    def test_list_flags_includes_overrides(self):
        gate = self._gate()
        gate.override("listed_flag", False)
        flags = gate.list_flags()
        assert "listed_flag" in flags
        assert flags["listed_flag"]["override"] is False

    def test_clear_all_overrides(self):
        gate = self._gate()
        gate.override("a", False)
        gate.override("b", False)
        gate.clear_all_overrides()
        assert gate.is_enabled("a") is True
        assert gate.is_enabled("b") is True

    def test_bucket_is_deterministic(self):
        from core.unified.release_gate import ReleaseGate

        b1 = ReleaseGate._bucket("feat", "task-abc")
        b2 = ReleaseGate._bucket("feat", "task-abc")
        assert b1 == b2

    def test_bucket_varies_across_contexts(self):
        from core.unified.release_gate import ReleaseGate

        buckets = {ReleaseGate._bucket("feat", f"ctx-{i}") for i in range(100)}
        # Should produce a distribution (not all the same bucket)
        assert len(buckets) > 1


# ===========================================================================
# 7. Integration: idempotency + command_envelope
# ===========================================================================


class TestIdempotencyCommandEnvelopeIntegration:
    def setup_method(self):
        _reset_all()

    def test_envelope_idempotency_key_is_deduped(self):
        from core.unified.command_envelope import CommandEnvelope
        from core.unified.idempotency import (
            check_idempotency, record_idempotency, make_payload_hash, DuplicateCommandError
        )

        env = CommandEnvelope(
            payload={"action": "click", "x": 100, "y": 200},
            trace_id="trace-env-1",
            task_id="task-env-1",
        )

        h = make_payload_hash(env.payload)
        key = env.idempotency_key or env.task_id

        # First submission
        assert check_idempotency(key, h, raise_on_duplicate=False) is None
        record_idempotency(key, h, result={"status": "executed"})

        # Duplicate submission
        with pytest.raises(DuplicateCommandError):
            check_idempotency(key, h, raise_on_duplicate=True)

    def test_envelope_with_explicit_idempotency_key(self):
        from core.unified.command_envelope import CommandEnvelope
        from core.unified.idempotency import record_idempotency, check_idempotency, make_payload_hash

        ikey = "idem-abc-123"
        env = CommandEnvelope(
            payload={"cmd": "scroll", "direction": "down"},
            idempotency_key=ikey,
        )
        assert env.idempotency_key == ikey

        h = make_payload_hash(env.payload)
        record_idempotency(ikey, h, result={"done": True})

        from core.unified.idempotency import DuplicateCommandError

        try:
            check_idempotency(ikey, h)
        except DuplicateCommandError as e:
            assert e.cached_result == {"done": True}
        else:
            pytest.fail("Expected DuplicateCommandError")


# ===========================================================================
# 8. Integration: release gate + global arbiter
# ===========================================================================


class TestArbiterGateIntegration:
    def setup_method(self):
        _reset_all()

    def test_arbiter_disabled_via_gate(self):
        from core.unified.release_gate import get_release_gate, reset_release_gate
        from core.orchestration.global_arbiter import get_global_arbiter, reset_global_arbiter

        reset_release_gate()
        reset_global_arbiter()

        gate = get_release_gate()
        gate.override("global_arbiter", False)

        arbiter = get_global_arbiter()
        arbiter.configure(global_limit=0)  # Would block everything normally

        # Gate disabled: bypass arbiter entirely
        if not gate.is_enabled("global_arbiter"):
            admitted = True  # fallback: always admit
        else:
            d = arbiter.admit("t", priority=5, origin="u")
            admitted = d.admitted

        assert admitted is True

    def test_arbiter_enabled_enforces_quota(self):
        from core.unified.release_gate import get_release_gate, reset_release_gate
        from core.orchestration.global_arbiter import get_global_arbiter, reset_global_arbiter

        reset_release_gate()
        reset_global_arbiter()

        gate = get_release_gate()
        gate.override("global_arbiter", True)

        arbiter = get_global_arbiter()
        arbiter.configure(global_limit=1, per_origin_quota=1)

        if gate.is_enabled("global_arbiter"):
            arbiter.admit("t1", priority=5, origin="u")
            d2 = arbiter.admit("t2", priority=5, origin="u")  # quota exceeded
            assert d2.admitted is False
