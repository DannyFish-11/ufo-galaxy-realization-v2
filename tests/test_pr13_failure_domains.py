"""
tests/test_pr13_failure_domains.py
====================================
Tests for PR-13: Failure Domains, Retry Policies, and Fallback Execution Policies.

Coverage
--------
A) FailureDomain enum
   - all expected domain values present
   - string values are stable
   - enum is str subclass
   - values are distinct

B) DOMAIN_DESCRIPTIONS
   - all domains have a description
   - descriptions are non-empty strings

C) is_retryable_by_domain
   - retryable domains return True (TIMEOUT, GATEWAY_TRANSPORT, DEVICE_UNAVAILABLE)
   - non-retryable domains return False (LOCAL_RUNTIME, CAPABILITY_MISMATCH w/o alternate)
   - REMOTE_CAPABILITY_MISMATCH retryable with allow_alternate_target=True
   - CONTRACT_VALIDATION, SUBSTRATE_DISPATCH, ORCHESTRATION_PARTIAL, UNKNOWN not retryable

D) downgrade_hint_for_domain
   - REMOTE_CAPABILITY_MISMATCH → "agent_runtime_to_command_only"
   - REMOTE_DEVICE_UNAVAILABLE → "remote_to_local"
   - GATEWAY_TRANSPORT_FAILURE → "remote_to_local"
   - TIMEOUT_FAILURE → None
   - LOCAL_RUNTIME_FAILURE → None
   - CONTRACT_VALIDATION_FAILURE → None

E) FailureClassification
   - construction with all fields
   - to_dict() serialisation
   - to_dict() is JSON-safe
   - frozen / immutable

F) classify_from_error_code
   - "COMMAND_TIMEOUT" → TIMEOUT_FAILURE, retryable
   - "DISCONNECT" → GATEWAY_TRANSPORT_FAILURE, retryable
   - "EXECUTOR_ERROR" → GATEWAY_TRANSPORT_FAILURE, retryable
   - "DEVICE_NOT_FOUND" → REMOTE_DEVICE_UNAVAILABLE, retryable
   - "DEVICE_OFFLINE" → REMOTE_DEVICE_UNAVAILABLE, retryable
   - "INVALID_ENVELOPE" → SUBSTRATE_DISPATCH_FAILURE, not retryable
   - "INTERNAL_ERROR" → SUBSTRATE_DISPATCH_FAILURE, not retryable
   - "HITL_TIMEOUT" → TIMEOUT_FAILURE, retryable
   - "HITL_DENIED" → CONTRACT_VALIDATION_FAILURE, not retryable
   - "ACL_DENIED" → CONTRACT_VALIDATION_FAILURE, not retryable
   - None → UNKNOWN_FAILURE
   - unknown string → UNKNOWN_FAILURE
   - notes propagated into classification

G) classify_from_exception
   - TimeoutError → TIMEOUT_FAILURE, retryable
   - ConnectionError → GATEWAY_TRANSPORT_FAILURE, retryable
   - generic RuntimeError → LOCAL_RUNTIME_FAILURE, not retryable
   - exception with "capability" in message → REMOTE_CAPABILITY_MISMATCH

H) RetryPolicy
   - construction with all fields
   - to_dict() serialisation
   - to_dict() is JSON-safe
   - frozen / immutable
   - default construction (non-retryable)

I) FallbackPolicy
   - construction with all fields
   - to_dict() serialisation
   - to_dict() is JSON-safe
   - frozen / immutable
   - default construction (no fallback)

J) DEFAULT policy constants
   - DEFAULT_NO_RETRY_POLICY has is_retryable=False, max_attempts=1
   - DEFAULT_TRANSIENT_RETRY_POLICY has is_retryable=True, max_attempts=3
   - DEFAULT_NO_FALLBACK_POLICY has all allow_* False
   - DEFAULT_REMOTE_FALLBACK_POLICY has all allow_* True

K) FailureRecord
   - construction with all fields
   - failure_domain property returns domain value string
   - is_retryable property mirrors retry_policy
   - downgrade_hint property mirrors classification
   - to_dict() serialisation
   - to_dict() is JSON-safe

L) build_failure_record — from error code
   - COMMAND_TIMEOUT → TIMEOUT_FAILURE, is_retryable, fallback remote→local
   - DISCONNECT → GATEWAY_TRANSPORT_FAILURE, is_retryable
   - DEVICE_NOT_FOUND → REMOTE_DEVICE_UNAVAILABLE, is_retryable
   - INVALID_ENVELOPE → SUBSTRATE_DISPATCH_FAILURE, not retryable
   - ACL_DENIED → CONTRACT_VALIDATION_FAILURE, not retryable, no fallback
   - None → UNKNOWN_FAILURE, not retryable
   - retry_policy override respected
   - fallback_policy override respected

M) build_failure_record_from_exception
   - TimeoutError → TIMEOUT_FAILURE
   - RuntimeError → LOCAL_RUNTIME_FAILURE

N) failure_record_summary
   - None → empty dict
   - record → dict with all required keys
   - JSON-safe output
   - failure_domain key present
   - is_retryable key present
   - downgrade_hint key present

O) Specific domain policy assertions (retryable vs non-retryable guardrails)
   - timeout_failure surfaces correct failure domain
   - remote_device_unavailable surfaces correct failure domain
   - capability_mismatch surfaces correct failure domain with downgrade hint
   - contract_validation_failure not retryable
   - backward compatibility: callers not inspecting failure_domain unaffected

P) ModeResolutionResult failure_domain integration
   - failure_domain field exists and defaults to None
   - resolver fallback on capability mismatch → failure_domain="remote_capability_mismatch"
   - resolver fallback on missing profile → failure_domain="remote_device_unavailable"
   - non-fallback resolutions have failure_domain=None

Q) lifecycle_summary failure_domain integration
   - failure_domain=None → key not in summary
   - failure_domain="timeout_failure" → key in summary with correct value
   - other keys (lifecycle_state, is_terminal etc.) unaffected
   - backward compatibility: callers omitting failure_domain still work

R) command_router failure_domain stamp
   - route_envelope stamps failure_domain on failed results
   - route_envelope does NOT stamp failure_domain on success
   - failure_is_retryable stamped on failed results

S) swarm_coordinator failure_domain integration
   - no_target_device → failure_domain="remote_device_unavailable"
   - command_router_unavailable → failure_domain="substrate_dispatch_failure"
   - exception → failure_domain="gateway_transport_failure"
"""

from __future__ import annotations

import pytest


# ===========================================================================
# A) FailureDomain enum
# ===========================================================================


class TestFailureDomain:
    def test_all_expected_domains_present(self):
        from core.failure_domains import FailureDomain
        expected = {
            "LOCAL_RUNTIME_FAILURE",
            "REMOTE_CAPABILITY_MISMATCH",
            "REMOTE_DEVICE_UNAVAILABLE",
            "GATEWAY_TRANSPORT_FAILURE",
            "SUBSTRATE_DISPATCH_FAILURE",
            "ORCHESTRATION_PARTIAL_FAILURE",
            "CONTRACT_VALIDATION_FAILURE",
            "TIMEOUT_FAILURE",
            "UNKNOWN_FAILURE",
        }
        actual = {d.name for d in FailureDomain}
        assert expected.issubset(actual), f"Missing domains: {expected - actual}"

    def test_string_values_stable(self):
        from core.failure_domains import FailureDomain
        assert FailureDomain.LOCAL_RUNTIME_FAILURE.value == "local_runtime_failure"
        assert FailureDomain.REMOTE_CAPABILITY_MISMATCH.value == "remote_capability_mismatch"
        assert FailureDomain.REMOTE_DEVICE_UNAVAILABLE.value == "remote_device_unavailable"
        assert FailureDomain.GATEWAY_TRANSPORT_FAILURE.value == "gateway_transport_failure"
        assert FailureDomain.SUBSTRATE_DISPATCH_FAILURE.value == "substrate_dispatch_failure"
        assert FailureDomain.ORCHESTRATION_PARTIAL_FAILURE.value == "orchestration_partial_failure"
        assert FailureDomain.CONTRACT_VALIDATION_FAILURE.value == "contract_validation_failure"
        assert FailureDomain.TIMEOUT_FAILURE.value == "timeout_failure"
        assert FailureDomain.UNKNOWN_FAILURE.value == "unknown_failure"

    def test_enum_is_str_subclass(self):
        from core.failure_domains import FailureDomain
        assert issubclass(FailureDomain, str)
        assert isinstance(FailureDomain.TIMEOUT_FAILURE, str)

    def test_values_are_distinct(self):
        from core.failure_domains import FailureDomain
        values = [d.value for d in FailureDomain]
        assert len(values) == len(set(values))


# ===========================================================================
# B) DOMAIN_DESCRIPTIONS
# ===========================================================================


class TestDomainDescriptions:
    def test_all_domains_have_description(self):
        from core.failure_domains import FailureDomain, DOMAIN_DESCRIPTIONS
        for domain in FailureDomain:
            assert domain in DOMAIN_DESCRIPTIONS, f"Missing description for {domain}"

    def test_descriptions_are_non_empty_strings(self):
        from core.failure_domains import DOMAIN_DESCRIPTIONS
        for domain, desc in DOMAIN_DESCRIPTIONS.items():
            assert isinstance(desc, str) and desc, f"Empty description for {domain}"


# ===========================================================================
# C) is_retryable_by_domain
# ===========================================================================


class TestIsRetryableByDomain:
    def test_timeout_retryable(self):
        from core.failure_domains import FailureDomain, is_retryable_by_domain
        assert is_retryable_by_domain(FailureDomain.TIMEOUT_FAILURE) is True

    def test_gateway_transport_retryable(self):
        from core.failure_domains import FailureDomain, is_retryable_by_domain
        assert is_retryable_by_domain(FailureDomain.GATEWAY_TRANSPORT_FAILURE) is True

    def test_device_unavailable_retryable(self):
        from core.failure_domains import FailureDomain, is_retryable_by_domain
        assert is_retryable_by_domain(FailureDomain.REMOTE_DEVICE_UNAVAILABLE) is True

    def test_local_runtime_not_retryable(self):
        from core.failure_domains import FailureDomain, is_retryable_by_domain
        assert is_retryable_by_domain(FailureDomain.LOCAL_RUNTIME_FAILURE) is False

    def test_capability_mismatch_not_same_target_retryable(self):
        from core.failure_domains import FailureDomain, is_retryable_by_domain
        # Same-target retry won't fix capability mismatch
        assert is_retryable_by_domain(FailureDomain.REMOTE_CAPABILITY_MISMATCH) is False

    def test_capability_mismatch_retryable_on_alternate(self):
        from core.failure_domains import FailureDomain, is_retryable_by_domain
        assert is_retryable_by_domain(
            FailureDomain.REMOTE_CAPABILITY_MISMATCH, allow_alternate_target=True
        ) is True

    def test_contract_validation_not_retryable(self):
        from core.failure_domains import FailureDomain, is_retryable_by_domain
        assert is_retryable_by_domain(FailureDomain.CONTRACT_VALIDATION_FAILURE) is False

    def test_substrate_dispatch_not_retryable(self):
        from core.failure_domains import FailureDomain, is_retryable_by_domain
        assert is_retryable_by_domain(FailureDomain.SUBSTRATE_DISPATCH_FAILURE) is False

    def test_orchestration_partial_not_retryable(self):
        from core.failure_domains import FailureDomain, is_retryable_by_domain
        assert is_retryable_by_domain(FailureDomain.ORCHESTRATION_PARTIAL_FAILURE) is False

    def test_unknown_not_retryable(self):
        from core.failure_domains import FailureDomain, is_retryable_by_domain
        assert is_retryable_by_domain(FailureDomain.UNKNOWN_FAILURE) is False


# ===========================================================================
# D) downgrade_hint_for_domain
# ===========================================================================


class TestDowngradeHintForDomain:
    def test_capability_mismatch_hint(self):
        from core.failure_domains import FailureDomain, downgrade_hint_for_domain
        assert downgrade_hint_for_domain(FailureDomain.REMOTE_CAPABILITY_MISMATCH) == "agent_runtime_to_command_only"

    def test_device_unavailable_hint(self):
        from core.failure_domains import FailureDomain, downgrade_hint_for_domain
        assert downgrade_hint_for_domain(FailureDomain.REMOTE_DEVICE_UNAVAILABLE) == "remote_to_local"

    def test_gateway_transport_hint(self):
        from core.failure_domains import FailureDomain, downgrade_hint_for_domain
        assert downgrade_hint_for_domain(FailureDomain.GATEWAY_TRANSPORT_FAILURE) == "remote_to_local"

    def test_timeout_no_hint(self):
        from core.failure_domains import FailureDomain, downgrade_hint_for_domain
        assert downgrade_hint_for_domain(FailureDomain.TIMEOUT_FAILURE) is None

    def test_local_runtime_no_hint(self):
        from core.failure_domains import FailureDomain, downgrade_hint_for_domain
        assert downgrade_hint_for_domain(FailureDomain.LOCAL_RUNTIME_FAILURE) is None

    def test_contract_validation_no_hint(self):
        from core.failure_domains import FailureDomain, downgrade_hint_for_domain
        assert downgrade_hint_for_domain(FailureDomain.CONTRACT_VALIDATION_FAILURE) is None


# ===========================================================================
# E) FailureClassification
# ===========================================================================


class TestFailureClassification:
    def _make(self, **kwargs):
        from core.failure_domains import FailureClassification, FailureDomain
        defaults = dict(
            domain=FailureDomain.TIMEOUT_FAILURE,
            is_retryable=True,
            is_retryable_same_target=True,
            downgrade_hint=None,
            source_error_code="COMMAND_TIMEOUT",
            notes="test",
        )
        defaults.update(kwargs)
        return FailureClassification(**defaults)

    def test_construction(self):
        fc = self._make()
        from core.failure_domains import FailureDomain
        assert fc.domain == FailureDomain.TIMEOUT_FAILURE
        assert fc.is_retryable is True

    def test_to_dict_keys(self):
        fc = self._make()
        d = fc.to_dict()
        assert "domain" in d
        assert "is_retryable" in d
        assert "is_retryable_same_target" in d
        assert "downgrade_hint" in d
        assert "source_error_code" in d
        assert "notes" in d

    def test_to_dict_json_safe(self):
        import json
        fc = self._make()
        json.dumps(fc.to_dict())

    def test_frozen(self):
        fc = self._make()
        with pytest.raises((AttributeError, TypeError)):
            fc.is_retryable = False  # type: ignore[misc]


# ===========================================================================
# F) classify_from_error_code
# ===========================================================================


class TestClassifyFromErrorCode:
    def _classify(self, code):
        from core.failure_domains import classify_from_error_code
        return classify_from_error_code(code)

    def test_command_timeout(self):
        from core.failure_domains import FailureDomain
        fc = self._classify("COMMAND_TIMEOUT")
        assert fc.domain == FailureDomain.TIMEOUT_FAILURE
        assert fc.is_retryable is True

    def test_disconnect(self):
        from core.failure_domains import FailureDomain
        fc = self._classify("DISCONNECT")
        assert fc.domain == FailureDomain.GATEWAY_TRANSPORT_FAILURE
        assert fc.is_retryable is True

    def test_executor_error(self):
        from core.failure_domains import FailureDomain
        fc = self._classify("EXECUTOR_ERROR")
        assert fc.domain == FailureDomain.GATEWAY_TRANSPORT_FAILURE

    def test_device_not_found(self):
        from core.failure_domains import FailureDomain
        fc = self._classify("DEVICE_NOT_FOUND")
        assert fc.domain == FailureDomain.REMOTE_DEVICE_UNAVAILABLE
        assert fc.is_retryable is True

    def test_device_offline(self):
        from core.failure_domains import FailureDomain
        fc = self._classify("DEVICE_OFFLINE")
        assert fc.domain == FailureDomain.REMOTE_DEVICE_UNAVAILABLE

    def test_invalid_envelope(self):
        from core.failure_domains import FailureDomain
        fc = self._classify("INVALID_ENVELOPE")
        assert fc.domain == FailureDomain.SUBSTRATE_DISPATCH_FAILURE
        assert fc.is_retryable is False

    def test_internal_error(self):
        from core.failure_domains import FailureDomain
        fc = self._classify("INTERNAL_ERROR")
        assert fc.domain == FailureDomain.SUBSTRATE_DISPATCH_FAILURE

    def test_hitl_timeout(self):
        from core.failure_domains import FailureDomain
        fc = self._classify("HITL_TIMEOUT")
        assert fc.domain == FailureDomain.TIMEOUT_FAILURE

    def test_hitl_denied(self):
        from core.failure_domains import FailureDomain
        fc = self._classify("HITL_DENIED")
        assert fc.domain == FailureDomain.CONTRACT_VALIDATION_FAILURE
        assert fc.is_retryable is False

    def test_acl_denied(self):
        from core.failure_domains import FailureDomain
        fc = self._classify("ACL_DENIED")
        assert fc.domain == FailureDomain.CONTRACT_VALIDATION_FAILURE
        assert fc.is_retryable is False

    def test_none_input(self):
        from core.failure_domains import FailureDomain
        fc = self._classify(None)
        assert fc.domain == FailureDomain.UNKNOWN_FAILURE
        assert fc.source_error_code is None

    def test_unknown_string(self):
        from core.failure_domains import FailureDomain
        fc = self._classify("SOMETHING_WEIRD")
        assert fc.domain == FailureDomain.UNKNOWN_FAILURE

    def test_notes_propagated(self):
        from core.failure_domains import classify_from_error_code
        fc = classify_from_error_code("DISCONNECT", notes="test note")
        assert fc.notes == "test note"

    def test_source_error_code_preserved(self):
        fc = self._classify("COMMAND_TIMEOUT")
        assert fc.source_error_code == "COMMAND_TIMEOUT"


# ===========================================================================
# G) classify_from_exception
# ===========================================================================


class TestClassifyFromException:
    def test_timeout_error(self):
        from core.failure_domains import FailureDomain, classify_from_exception
        fc = classify_from_exception(TimeoutError("timed out"))
        assert fc.domain == FailureDomain.TIMEOUT_FAILURE
        assert fc.is_retryable is True

    def test_connection_error(self):
        from core.failure_domains import FailureDomain, classify_from_exception
        fc = classify_from_exception(ConnectionError("network failure"))
        assert fc.domain == FailureDomain.GATEWAY_TRANSPORT_FAILURE
        assert fc.is_retryable is True

    def test_generic_runtime_error(self):
        from core.failure_domains import FailureDomain, classify_from_exception
        fc = classify_from_exception(RuntimeError("something broke"))
        assert fc.domain == FailureDomain.LOCAL_RUNTIME_FAILURE

    def test_capability_message(self):
        from core.failure_domains import FailureDomain, classify_from_exception
        fc = classify_from_exception(RuntimeError("capability not supported on this device"))
        assert fc.domain == FailureDomain.REMOTE_CAPABILITY_MISMATCH

    def test_source_error_code_is_classname(self):
        from core.failure_domains import classify_from_exception
        fc = classify_from_exception(TimeoutError("t"))
        assert fc.source_error_code == "TimeoutError"


# ===========================================================================
# H) RetryPolicy
# ===========================================================================


class TestRetryPolicy:
    def _make(self, **kwargs):
        from core.schemas.execution_failure import RetryPolicy
        defaults = dict(
            is_retryable=True,
            max_attempts=3,
            backoff_base_ms=500,
            backoff_multiplier=2.0,
            same_target_only=False,
            allow_mode_downgrade=True,
            notes="test",
        )
        defaults.update(kwargs)
        return RetryPolicy(**defaults)

    def test_construction(self):
        rp = self._make()
        assert rp.is_retryable is True
        assert rp.max_attempts == 3
        assert rp.backoff_base_ms == 500
        assert rp.backoff_multiplier == 2.0

    def test_to_dict_keys(self):
        rp = self._make()
        d = rp.to_dict()
        for key in ("is_retryable", "max_attempts", "backoff_base_ms",
                    "backoff_multiplier", "same_target_only", "allow_mode_downgrade", "notes"):
            assert key in d

    def test_to_dict_json_safe(self):
        import json
        rp = self._make()
        json.dumps(rp.to_dict())

    def test_frozen(self):
        rp = self._make()
        with pytest.raises((AttributeError, TypeError)):
            rp.max_attempts = 10  # type: ignore[misc]

    def test_default_non_retryable(self):
        from core.schemas.execution_failure import RetryPolicy
        rp = RetryPolicy()
        assert rp.is_retryable is False
        assert rp.max_attempts == 1


# ===========================================================================
# I) FallbackPolicy
# ===========================================================================


class TestFallbackPolicy:
    def _make(self, **kwargs):
        from core.schemas.execution_failure import FallbackPolicy
        defaults = dict(
            allow_agent_to_command_downgrade=True,
            allow_remote_to_local=True,
            allow_alternate_target=True,
            degraded_completion_allowed=True,
            fallback_mode_hint="command_only",
            notes="test",
        )
        defaults.update(kwargs)
        return FallbackPolicy(**defaults)

    def test_construction(self):
        fp = self._make()
        assert fp.allow_agent_to_command_downgrade is True
        assert fp.allow_remote_to_local is True

    def test_to_dict_keys(self):
        fp = self._make()
        d = fp.to_dict()
        for key in ("allow_agent_to_command_downgrade", "allow_remote_to_local",
                    "allow_alternate_target", "degraded_completion_allowed",
                    "fallback_mode_hint", "notes"):
            assert key in d

    def test_to_dict_json_safe(self):
        import json
        fp = self._make()
        json.dumps(fp.to_dict())

    def test_frozen(self):
        fp = self._make()
        with pytest.raises((AttributeError, TypeError)):
            fp.allow_remote_to_local = False  # type: ignore[misc]

    def test_default_no_fallback(self):
        from core.schemas.execution_failure import FallbackPolicy
        fp = FallbackPolicy()
        assert fp.allow_agent_to_command_downgrade is False
        assert fp.allow_remote_to_local is False
        assert fp.allow_alternate_target is False


# ===========================================================================
# J) DEFAULT policy constants
# ===========================================================================


class TestDefaultPolicyConstants:
    def test_no_retry_policy(self):
        from core.schemas.execution_failure import DEFAULT_NO_RETRY_POLICY
        assert DEFAULT_NO_RETRY_POLICY.is_retryable is False
        assert DEFAULT_NO_RETRY_POLICY.max_attempts == 1

    def test_transient_retry_policy(self):
        from core.schemas.execution_failure import DEFAULT_TRANSIENT_RETRY_POLICY
        assert DEFAULT_TRANSIENT_RETRY_POLICY.is_retryable is True
        assert DEFAULT_TRANSIENT_RETRY_POLICY.max_attempts == 3
        assert DEFAULT_TRANSIENT_RETRY_POLICY.same_target_only is False

    def test_no_fallback_policy(self):
        from core.schemas.execution_failure import DEFAULT_NO_FALLBACK_POLICY
        assert DEFAULT_NO_FALLBACK_POLICY.allow_agent_to_command_downgrade is False
        assert DEFAULT_NO_FALLBACK_POLICY.allow_remote_to_local is False
        assert DEFAULT_NO_FALLBACK_POLICY.allow_alternate_target is False
        assert DEFAULT_NO_FALLBACK_POLICY.degraded_completion_allowed is False

    def test_remote_fallback_policy(self):
        from core.schemas.execution_failure import DEFAULT_REMOTE_FALLBACK_POLICY
        assert DEFAULT_REMOTE_FALLBACK_POLICY.allow_agent_to_command_downgrade is True
        assert DEFAULT_REMOTE_FALLBACK_POLICY.allow_remote_to_local is True
        assert DEFAULT_REMOTE_FALLBACK_POLICY.allow_alternate_target is True
        assert DEFAULT_REMOTE_FALLBACK_POLICY.degraded_completion_allowed is True


# ===========================================================================
# K) FailureRecord
# ===========================================================================


class TestFailureRecord:
    def _make_record(self, error_code="COMMAND_TIMEOUT"):
        from core.schemas.execution_failure import build_failure_record
        return build_failure_record(error_code)

    def test_failure_domain_property(self):
        record = self._make_record("COMMAND_TIMEOUT")
        assert record.failure_domain == "timeout_failure"

    def test_is_retryable_property(self):
        record = self._make_record("COMMAND_TIMEOUT")
        assert record.is_retryable is True

    def test_is_retryable_false_for_acl(self):
        record = self._make_record("ACL_DENIED")
        assert record.is_retryable is False

    def test_downgrade_hint_property(self):
        record = self._make_record("DEVICE_NOT_FOUND")
        assert record.downgrade_hint == "remote_to_local"

    def test_to_dict_keys(self):
        record = self._make_record()
        d = record.to_dict()
        assert "failure_domain" in d
        assert "classification" in d
        assert "retry_policy" in d
        assert "fallback_policy" in d

    def test_to_dict_json_safe(self):
        import json
        record = self._make_record()
        json.dumps(record.to_dict())


# ===========================================================================
# L) build_failure_record — from error code
# ===========================================================================


class TestBuildFailureRecord:
    def test_command_timeout_retryable(self):
        from core.schemas.execution_failure import build_failure_record
        record = build_failure_record("COMMAND_TIMEOUT")
        assert record.failure_domain == "timeout_failure"
        assert record.is_retryable is True
        assert record.fallback_policy.allow_remote_to_local is True

    def test_disconnect_retryable(self):
        from core.schemas.execution_failure import build_failure_record
        record = build_failure_record("DISCONNECT")
        assert record.failure_domain == "gateway_transport_failure"
        assert record.is_retryable is True

    def test_device_not_found_retryable(self):
        from core.schemas.execution_failure import build_failure_record
        record = build_failure_record("DEVICE_NOT_FOUND")
        assert record.failure_domain == "remote_device_unavailable"
        assert record.is_retryable is True
        assert record.fallback_policy.allow_alternate_target is True

    def test_invalid_envelope_not_retryable(self):
        from core.schemas.execution_failure import build_failure_record
        record = build_failure_record("INVALID_ENVELOPE")
        assert record.failure_domain == "substrate_dispatch_failure"
        assert record.is_retryable is False

    def test_acl_denied_not_retryable_no_fallback(self):
        from core.schemas.execution_failure import build_failure_record
        record = build_failure_record("ACL_DENIED")
        assert record.failure_domain == "contract_validation_failure"
        assert record.is_retryable is False
        assert record.fallback_policy.allow_remote_to_local is False

    def test_none_produces_unknown(self):
        from core.schemas.execution_failure import build_failure_record
        record = build_failure_record(None)
        assert record.failure_domain == "unknown_failure"
        assert record.is_retryable is False

    def test_retry_policy_override(self):
        from core.schemas.execution_failure import build_failure_record, RetryPolicy
        custom_retry = RetryPolicy(is_retryable=False, max_attempts=1, notes="override")
        record = build_failure_record("COMMAND_TIMEOUT", retry_policy=custom_retry)
        assert record.retry_policy.is_retryable is False
        assert record.retry_policy.notes == "override"

    def test_fallback_policy_override(self):
        from core.schemas.execution_failure import build_failure_record, FallbackPolicy
        custom_fallback = FallbackPolicy(allow_remote_to_local=False, notes="override")
        record = build_failure_record("COMMAND_TIMEOUT", fallback_policy=custom_fallback)
        assert record.fallback_policy.allow_remote_to_local is False


# ===========================================================================
# M) build_failure_record_from_exception
# ===========================================================================


class TestBuildFailureRecordFromException:
    def test_timeout_error(self):
        from core.schemas.execution_failure import build_failure_record_from_exception
        record = build_failure_record_from_exception(TimeoutError("timed out"))
        assert record.failure_domain == "timeout_failure"
        assert record.is_retryable is True

    def test_runtime_error(self):
        from core.schemas.execution_failure import build_failure_record_from_exception
        record = build_failure_record_from_exception(RuntimeError("something broke"))
        assert record.failure_domain == "local_runtime_failure"


# ===========================================================================
# N) failure_record_summary
# ===========================================================================


class TestFailureRecordSummary:
    def test_none_returns_empty_dict(self):
        from core.schemas.execution_failure import failure_record_summary
        assert failure_record_summary(None) == {}

    def test_record_returns_all_keys(self):
        from core.schemas.execution_failure import build_failure_record, failure_record_summary
        record = build_failure_record("COMMAND_TIMEOUT")
        summary = failure_record_summary(record)
        assert "failure_domain" in summary
        assert "is_retryable" in summary
        assert "downgrade_hint" in summary
        assert "retry_max_attempts" in summary
        assert "fallback_allow_remote_to_local" in summary
        assert "fallback_allow_alternate_target" in summary
        assert "fallback_allow_agent_to_command_downgrade" in summary

    def test_json_safe(self):
        import json
        from core.schemas.execution_failure import build_failure_record, failure_record_summary
        record = build_failure_record("DISCONNECT")
        json.dumps(failure_record_summary(record))

    def test_failure_domain_value(self):
        from core.schemas.execution_failure import build_failure_record, failure_record_summary
        record = build_failure_record("COMMAND_TIMEOUT")
        summary = failure_record_summary(record)
        assert summary["failure_domain"] == "timeout_failure"

    def test_is_retryable_value(self):
        from core.schemas.execution_failure import build_failure_record, failure_record_summary
        record = build_failure_record("ACL_DENIED")
        summary = failure_record_summary(record)
        assert summary["is_retryable"] is False


# ===========================================================================
# O) Specific domain policy guardrails
# ===========================================================================


class TestDomainPolicyGuardrails:
    """Acceptance-test style: specific failure kinds should surface the right domain."""

    def test_timeout_failure_domain(self):
        from core.failure_domains import classify_from_error_code, FailureDomain
        fc = classify_from_error_code("COMMAND_TIMEOUT")
        assert fc.domain == FailureDomain.TIMEOUT_FAILURE

    def test_device_unavailable_domain(self):
        from core.failure_domains import classify_from_error_code, FailureDomain
        fc = classify_from_error_code("DEVICE_OFFLINE")
        assert fc.domain == FailureDomain.REMOTE_DEVICE_UNAVAILABLE
        assert fc.is_retryable is True

    def test_capability_mismatch_domain_with_downgrade_hint(self):
        """Unsupported/insufficient capability surfaces remote_capability_mismatch."""
        from core.schemas.execution_failure import build_failure_record
        from core.failure_domains import FailureDomain, classify_from_exception
        # Capability mismatch typically comes from the resolver as a fallback
        # We can test via a synthetic exception
        fc = classify_from_exception(RuntimeError("capability not supported"))
        assert fc.domain == FailureDomain.REMOTE_CAPABILITY_MISMATCH
        assert fc.downgrade_hint == "agent_runtime_to_command_only"

    def test_contract_validation_not_retryable(self):
        from core.failure_domains import classify_from_error_code, FailureDomain
        fc = classify_from_error_code("ACL_DENIED")
        assert fc.domain == FailureDomain.CONTRACT_VALIDATION_FAILURE
        assert fc.is_retryable is False

    def test_retryable_vs_non_retryable_distinguishable(self):
        """Retryable and non-retryable failures must be distinguishable."""
        from core.failure_domains import classify_from_error_code
        retryable = classify_from_error_code("COMMAND_TIMEOUT")
        non_retryable = classify_from_error_code("ACL_DENIED")
        assert retryable.is_retryable is True
        assert non_retryable.is_retryable is False
        assert retryable.domain != non_retryable.domain

    def test_fallback_path_inspectable(self):
        """A representative downgrade/fallback path is explicit and inspectable."""
        from core.schemas.execution_failure import build_failure_record
        record = build_failure_record("DEVICE_OFFLINE")
        # Downgrade hint is explicit
        assert record.downgrade_hint is not None
        # Fallback policy is inspectable
        assert record.fallback_policy.allow_remote_to_local is True
        # Can read the policy fields without any special knowledge
        summary = record.to_dict()
        assert summary["fallback_policy"]["allow_remote_to_local"] is True

    def test_backward_compat_callers_unaffected(self):
        """Callers that ignore failure_domain should still get a working result."""
        from core.failure_domains import classify_from_error_code
        fc = classify_from_error_code("COMMAND_TIMEOUT")
        # Caller only checks success/failure — doesn't touch domain
        # This should not raise
        _ = fc.domain  # fine
        _ = fc.is_retryable  # fine
        # domain value is a plain string — safe to ignore
        assert isinstance(fc.domain.value, str)


# ===========================================================================
# P) ModeResolutionResult failure_domain integration
# ===========================================================================


class TestModeResolutionResultFailureDomain:
    def test_failure_domain_field_exists(self):
        from core.remote_execution_mode_resolver import ModeResolutionResult
        result = ModeResolutionResult(
            mode="command_only",
            resolution_source="fallback",
        )
        assert hasattr(result, "failure_domain")
        assert result.failure_domain is None

    def test_failure_domain_defaults_to_none(self):
        from core.remote_execution_mode_resolver import ModeResolutionResult
        result = ModeResolutionResult(mode="agent_runtime", resolution_source="forced")
        assert result.failure_domain is None

    def test_capability_mismatch_fallback_has_domain(self):
        """Resolver fallback due to capability mismatch should expose failure_domain."""
        from core.remote_execution_mode_resolver import ModeResolutionResult
        result = ModeResolutionResult(
            mode="command_only",
            resolution_source="fallback",
            failure_domain="remote_capability_mismatch",
            notes="test",
        )
        assert result.failure_domain == "remote_capability_mismatch"

    def test_non_fallback_resolution_no_domain(self):
        """Profile-preferred or task_required resolutions should have no failure_domain."""
        from core.remote_execution_mode_resolver import ModeResolutionResult
        result = ModeResolutionResult(
            mode="agent_runtime",
            resolution_source="profile_preferred",
        )
        assert result.failure_domain is None

    def test_resolver_capability_mismatch_fallback(self):
        """Resolver returns failure_domain when required mode is unsupported."""
        from core.remote_execution_mode_resolver import RemoteExecutionModeResolver
        from unittest.mock import MagicMock

        profile = MagicMock()
        profile.device_id = "test_device"
        profile.profile_class = "thin"
        # Device does NOT support agent_runtime
        profile.supports_mode.return_value = False

        resolver = RemoteExecutionModeResolver()
        result = resolver.resolve(profile=profile, required_mode="agent_runtime")

        assert result.resolution_source == "fallback"
        assert result.failure_domain == "remote_capability_mismatch"

    def test_resolver_no_profile_fallback_domain(self):
        """Resolver with no profile should expose remote_device_unavailable domain."""
        from core.remote_execution_mode_resolver import RemoteExecutionModeResolver
        resolver = RemoteExecutionModeResolver()
        result = resolver.resolve(profile=None)
        assert result.resolution_source == "fallback"
        assert result.failure_domain == "remote_device_unavailable"


# ===========================================================================
# Q) lifecycle_summary failure_domain integration
# ===========================================================================


class TestLifecycleSummaryFailureDomain:
    def test_no_failure_domain_key_absent(self):
        from core.schemas.execution_lifecycle import ExecutionLifecycleState, lifecycle_summary
        summary = lifecycle_summary(ExecutionLifecycleState.SUCCEEDED)
        assert "failure_domain" not in summary

    def test_failure_domain_present_when_passed(self):
        from core.schemas.execution_lifecycle import ExecutionLifecycleState, lifecycle_summary
        summary = lifecycle_summary(
            ExecutionLifecycleState.FAILED,
            failure_domain="timeout_failure",
        )
        assert summary["failure_domain"] == "timeout_failure"

    def test_other_keys_unaffected(self):
        from core.schemas.execution_lifecycle import ExecutionLifecycleState, lifecycle_summary
        summary = lifecycle_summary(
            ExecutionLifecycleState.FAILED,
            failure_domain="gateway_transport_failure",
        )
        assert summary["lifecycle_state"] == "failed"
        assert "is_terminal" in summary
        assert "transition_count" in summary

    def test_backward_compat_no_failure_domain_arg(self):
        """Calling lifecycle_summary without failure_domain should still work."""
        from core.schemas.execution_lifecycle import ExecutionLifecycleState, lifecycle_summary
        # Original call signature — no failure_domain kwarg
        summary = lifecycle_summary(ExecutionLifecycleState.SUCCEEDED)
        assert "lifecycle_state" in summary
        assert summary["lifecycle_state"] == "succeeded"

    def test_failure_domain_json_safe(self):
        import json
        from core.schemas.execution_lifecycle import ExecutionLifecycleState, lifecycle_summary
        summary = lifecycle_summary(
            ExecutionLifecycleState.TIMED_OUT,
            failure_domain="timeout_failure",
        )
        json.dumps(summary)


# ===========================================================================
# R) command_router failure_domain stamp
# ===========================================================================


class TestCommandRouterFailureDomainStamp:
    """Smoke tests to verify route_envelope stamps failure_domain on failed results."""

    def test_failure_result_gets_failure_domain(self):
        """A failed route_envelope result should carry failure_domain."""
        import asyncio
        from unittest.mock import AsyncMock, patch
        from core.schemas.task_envelope import TaskEnvelope

        envelope = TaskEnvelope(
            task_id="test-task",
            tool_name="test_cmd",
            targets=["device_1"],
            args={},
        )

        # Simulate _execute_command returning a failure
        failed_result = {
            "request_id": "test-task",
            "task_id": "test-task",
            "trace_id": None,
            "command_id": "test-task",
            "device_id": "device_1",
            "command": "test_cmd",
            "via": "command_router",
            "success": False,
            "result": None,
            "error_code": "DEVICE_OFFLINE",
            "error_message": "device is offline",
            "latency_ms": 10.0,
        }

        async def run():
            with patch(
                "core.command_router.CommandRouter._execute_command",
                new_callable=AsyncMock,
                return_value=failed_result,
            ):
                from core.command_router import CommandRouter
                router = CommandRouter()
                return await router.route_envelope(envelope)

        result = asyncio.get_event_loop().run_until_complete(run())

        assert "failure_domain" in result
        assert result["failure_domain"] == "remote_device_unavailable"

    def test_success_result_no_failure_domain(self):
        """A successful route_envelope result should NOT carry failure_domain."""
        import asyncio
        from unittest.mock import AsyncMock, patch
        from core.schemas.task_envelope import TaskEnvelope

        envelope = TaskEnvelope(
            task_id="test-task-success",
            tool_name="test_cmd",
            targets=["device_1"],
            args={},
        )

        success_result = {
            "request_id": "test-task-success",
            "task_id": "test-task-success",
            "trace_id": None,
            "command_id": "test-task-success",
            "device_id": "device_1",
            "command": "test_cmd",
            "via": "command_router",
            "success": True,
            "result": "ok",
            "error_code": None,
            "error_message": None,
            "latency_ms": 5.0,
        }

        async def run():
            with patch(
                "core.command_router.CommandRouter._execute_command",
                new_callable=AsyncMock,
                return_value=success_result,
            ):
                from core.command_router import CommandRouter
                router = CommandRouter()
                return await router.route_envelope(envelope)

        result = asyncio.get_event_loop().run_until_complete(run())

        assert result.get("failure_domain") is None

    def test_failure_is_retryable_stamped(self):
        """A retryable failure should carry failure_is_retryable=True."""
        import asyncio
        from unittest.mock import AsyncMock, patch
        from core.schemas.task_envelope import TaskEnvelope

        envelope = TaskEnvelope(
            task_id="retry-test",
            tool_name="cmd",
            targets=["dev_1"],
            args={},
        )
        failed_result = {
            "request_id": "retry-test", "task_id": "retry-test",
            "trace_id": None, "command_id": "retry-test",
            "device_id": "dev_1", "command": "cmd", "via": "command_router",
            "success": False, "result": None,
            "error_code": "COMMAND_TIMEOUT", "error_message": "timeout",
            "latency_ms": 30000.0,
        }

        async def run():
            with patch(
                "core.command_router.CommandRouter._execute_command",
                new_callable=AsyncMock,
                return_value=failed_result,
            ):
                from core.command_router import CommandRouter
                router = CommandRouter()
                return await router.route_envelope(envelope)

        result = asyncio.get_event_loop().run_until_complete(run())

        assert result.get("failure_is_retryable") is True


# ===========================================================================
# S) swarm_coordinator failure_domain integration
# ===========================================================================


class TestSwarmCoordinatorFailureDomain:
    """Unit tests for failure_domain in swarm_coordinator._dispatch_one results."""

    def test_no_target_device_domain(self):
        """Missing target_device_id → remote_device_unavailable."""
        import asyncio
        from unittest.mock import MagicMock
        from core.swarm_coordinator import SwarmCoordinator

        manifest = MagicMock()
        manifest.target_device_id = None
        manifest.agent_id = "agent_1"
        manifest.trace_id = "trace_1"
        manifest.task_id = "task_1"
        manifest.session_id = "sess_1"
        manifest.manifest_id = "mfst_1"

        coord = SwarmCoordinator()
        mock_ledger = MagicMock()
        mock_ledger.append = MagicMock(return_value="event_id")

        async def run():
            with __import__("unittest.mock", fromlist=["patch"]).patch.object(
                coord, "_get_ledger", return_value=mock_ledger
            ):
                return await coord._dispatch_one(manifest)

        result = asyncio.get_event_loop().run_until_complete(run())

        assert result["success"] is False
        assert result.get("failure_domain") == "remote_device_unavailable"

    def test_router_unavailable_domain(self):
        """CommandRouter unavailable → substrate_dispatch_failure."""
        import asyncio
        from unittest.mock import MagicMock, patch
        from core.swarm_coordinator import SwarmCoordinator

        manifest = MagicMock()
        manifest.target_device_id = "device_1"
        manifest.agent_id = "agent_1"
        manifest.trace_id = "trace_1"
        manifest.task_id = "task_1"
        manifest.session_id = "sess_1"
        manifest.manifest_id = "mfst_1"
        manifest.template = "base"
        manifest.subtask = "do something"
        manifest.task = "do something"
        manifest.member_name = "member_1"

        coord = SwarmCoordinator()
        mock_ledger = MagicMock()
        mock_ledger.append = MagicMock(return_value="event_id")

        async def run():
            with patch.object(coord, "_get_router", return_value=None), \
                 patch.object(coord, "_get_ledger", return_value=mock_ledger):
                return await coord._dispatch_one(manifest)

        result = asyncio.get_event_loop().run_until_complete(run())

        assert result["success"] is False
        assert result.get("failure_domain") == "substrate_dispatch_failure"

    def test_exception_in_dispatch_domain(self):
        """Exception during dispatch → gateway_transport_failure."""
        import asyncio
        from unittest.mock import MagicMock, patch, AsyncMock
        from core.swarm_coordinator import SwarmCoordinator

        manifest = MagicMock()
        manifest.target_device_id = "device_1"
        manifest.agent_id = "agent_1"
        manifest.trace_id = "trace_1"
        manifest.task_id = "task_1"
        manifest.session_id = "sess_1"
        manifest.manifest_id = "mfst_1"
        manifest.template = "base"
        manifest.subtask = "do something"
        manifest.task = "do something"
        manifest.member_name = "member_1"
        manifest.timeout_seconds = 30.0

        coord = SwarmCoordinator()
        mock_ledger = MagicMock()
        mock_ledger.append = MagicMock(return_value="event_id")

        mock_router = MagicMock()
        mock_router.dispatch_agent_remote = AsyncMock(
            side_effect=ConnectionError("network error")
        )

        async def run():
            with patch.object(coord, "_get_router", return_value=mock_router), \
                 patch.object(coord, "_get_ledger", return_value=mock_ledger):
                return await coord._dispatch_one(manifest)

        result = asyncio.get_event_loop().run_until_complete(run())

        assert result["success"] is False
        assert result.get("failure_domain") == "gateway_transport_failure"
