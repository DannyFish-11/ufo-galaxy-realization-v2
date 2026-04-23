#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_prl_android_v2_joint_continuity.py
==============================================
PR-L — Android-V2 Joint Continuity Verification Suite — test suite.

Coverage
--------
A  — Module importable; authority sentinel and PR-L sentinel present.
B  — All 16 policy sentinels are non-empty strings with expected keywords.
C  — AndroidAttachOutcome enum has all four required values.
D  — ContinuityScenario enum has all seven required values.
E  — ContinuityVerificationResult enum has all four required values.
F  — AndroidAttachRecord dataclass has required fields; to_dict() works.
G  — ContinuityScenarioOutcome dataclass has required fields; to_dict() works.
H  — JointContinuityContractSnapshot dataclass has required fields; to_dict() works.
I  — to_json() produces valid JSON for all three data classes.
J  — classify_attach_outcome: no prior entry → new_registration.
K  — classify_attach_outcome: prior active entry + match → continuity_resume.
L  — classify_attach_outcome: prior replaced entry → new_attachment.
M  — classify_attach_outcome: registry_entry_created=False → failed.
N  — classify_reconnect_continuity_outcome: continuity_resume + preserved → pass.
O  — classify_reconnect_continuity_outcome: continuity_resume + NOT preserved → fail.
P  — classify_reconnect_continuity_outcome: continuity_resume + no increment → advisory.
Q  — classify_reconnect_continuity_outcome: new_attachment → pass.
R  — classify_reconnect_continuity_outcome: unknown outcome → fail.
S  — classify_reattach_process_recreation_outcome: active entry + match +
     continuity_resume → pass.
T  — classify_reattach_process_recreation_outcome: active entry + match +
     new_attachment → fail (contract violation).
U  — classify_reattach_process_recreation_outcome: mismatched ID +
     new_attachment → pass.
V  — classify_reattach_process_recreation_outcome: terminal entry + match +
     new_attachment → pass (stale attachment ID → new).
W  — verify_stale_identity_handling: was_reconciled=True → fail.
X  — verify_stale_identity_handling: v2_state_altered=True → fail.
Y  — verify_stale_identity_handling: phantom_record_created=True → fail.
Z  — verify_stale_identity_handling: reject_reason empty → advisory.
AA — verify_stale_identity_handling: all-clear → pass.
AB — verify_duplicate_signal_suppression: not suppressed → fail.
AC — verify_duplicate_signal_suppression: reconciler called 2× → fail.
AD — verify_duplicate_signal_suppression: suppressed, reconciler called once → pass.
AE — verify_duplicate_signal_suppression: suppressed, reconciler called zero times → pass.
AF — build_joint_continuity_contract_snapshot: no scenarios → all_pass=True, fail_count=0.
AG — build_joint_continuity_contract_snapshot: one fail → all_pass=False, fail_count=1.
AH — build_joint_continuity_contract_snapshot: policy_sentinels has 16 entries.
AI — get_joint_continuity_contract_snapshot: returns JointContinuityContractSnapshot.
AJ — is_android_v2_continuity_healthy: True for empty snapshot.
AK — is_android_v2_continuity_healthy: False when fail_count > 0.
AL — Snapshot to_dict() contains all expected top-level keys.
AM — Snapshot to_json() is valid JSON.
AN — JointContinuityContractSnapshot.prl_sentinel contains 'PR-L' and 'package=L'.
AO — Authority boundary: ANDROID_IS_DURABLE_PARTICIPANT policy mentions 'orchestration authority'.
AP — Authority boundary: V2_IS_CANONICAL_ORCHESTRATION_AUTHORITY policy mentions 'V2'.
AQ — Attach policy: ATTACH_MUST_CREATE_REGISTRY_ENTRY mentions 'AttachedSessionRegistry'.
AR — Reconnect policy: RECONNECT_CONTINUITY_RESUME mentions 'runtime_attachment_session_id'.
AS — Stale policy: STALE_IDENTITY_MUST_BE_REJECTED mentions 'non-destructive' or 'non_destructive'.
AT — Duplicate policy: DUPLICATE_SIGNAL_MUST_BE_SUPPRESSED mentions 'idempotency_key'.
AU — Partial result policy: PARTIAL_RESULT_MUST_BE_PRESERVED mentions 'partial result'.
AV — V2 restart policy: V2_RESTART_RECOVERY_MUST_ACCEPT mentions 'recovered task'.
AW — classify_attach_outcome: prior detached entry → continuity_resume.
AX — classify_attach_outcome: prior invalidated entry → new_attachment.
AY — Mixed scenario snapshot: pass + fail + advisory counted correctly.
AZ — Scenario outcomes are ordered by insertion in snapshot.scenarios_verified.
"""

from __future__ import annotations

import json
import uuid
from typing import List

import pytest


# ---------------------------------------------------------------------------
# A — Module importable; sentinels present
# ---------------------------------------------------------------------------


class TestModuleSentinels:
    def test_module_is_importable(self):
        import core.android_v2_continuity_contract  # noqa: F401

    def test_authority_sentinel_is_non_empty_string(self):
        from core.android_v2_continuity_contract import (
            ANDROID_V2_CONTINUITY_CONTRACT_AUTHORITY,
        )
        assert isinstance(ANDROID_V2_CONTINUITY_CONTRACT_AUTHORITY, str)
        assert len(ANDROID_V2_CONTINUITY_CONTRACT_AUTHORITY) > 0
        assert "PR-L" in ANDROID_V2_CONTINUITY_CONTRACT_AUTHORITY

    def test_prl_sentinel_is_non_empty_string(self):
        from core.android_v2_continuity_contract import (
            ANDROID_V2_CONTINUITY_CONTRACT_PRL_SENTINEL,
        )
        assert isinstance(ANDROID_V2_CONTINUITY_CONTRACT_PRL_SENTINEL, str)
        assert "PR-L" in ANDROID_V2_CONTINUITY_CONTRACT_PRL_SENTINEL
        assert "package=L" in ANDROID_V2_CONTINUITY_CONTRACT_PRL_SENTINEL


# ---------------------------------------------------------------------------
# B — Policy sentinels
# ---------------------------------------------------------------------------


class TestPolicySentinels:
    def _import_all_sentinels(self):
        from core.android_v2_continuity_contract import (
            ANDROID_IS_DURABLE_PARTICIPANT_NOT_ORCHESTRATION_AUTHORITY_POLICY,
            V2_IS_CANONICAL_ORCHESTRATION_AUTHORITY_POLICY,
            ATTACH_MUST_CREATE_REGISTRY_ENTRY_POLICY,
            ATTACH_ASSIGNS_CANONICAL_ATTACHMENT_ID_POLICY,
            RECONNECT_CONTINUITY_RESUME_PRESERVES_ATTACHMENT_ID_POLICY,
            RECONNECT_NEW_ATTACHMENT_DOES_NOT_INHERIT_PRIOR_CONTEXT_POLICY,
            REATTACH_AFTER_PROCESS_RECREATION_MUST_NOT_DUPLICATE_PARTICIPANT_POLICY,
            PROCESS_RECREATION_CONTINUITY_RESUME_REQUIRES_MATCHING_ID_POLICY,
            V2_RESTART_RECOVERY_MUST_ACCEPT_ANDROID_RESULT_AGAINST_RECOVERED_TASK_POLICY,
            INFLIGHT_TASK_CONTINUITY_REQUIRES_V2_RECOVERY_COOPERATION_POLICY,
            STALE_IDENTITY_MUST_BE_REJECTED_NON_DESTRUCTIVELY_POLICY,
            STALE_ATTACHMENT_ID_PRODUCES_NEW_ATTACHMENT_POLICY,
            DUPLICATE_SIGNAL_MUST_BE_SUPPRESSED_POLICY,
            DUPLICATE_REENTRY_MUST_NOT_CREATE_DUPLICATE_TASK_RECORD_POLICY,
            PARTIAL_RESULT_MUST_BE_PRESERVED_UNTIL_COMPLETION_POLICY,
            PARTIAL_RESULT_IS_SUPERSEDED_BY_TERMINAL_SIGNAL_POLICY,
        )
        return [
            ANDROID_IS_DURABLE_PARTICIPANT_NOT_ORCHESTRATION_AUTHORITY_POLICY,
            V2_IS_CANONICAL_ORCHESTRATION_AUTHORITY_POLICY,
            ATTACH_MUST_CREATE_REGISTRY_ENTRY_POLICY,
            ATTACH_ASSIGNS_CANONICAL_ATTACHMENT_ID_POLICY,
            RECONNECT_CONTINUITY_RESUME_PRESERVES_ATTACHMENT_ID_POLICY,
            RECONNECT_NEW_ATTACHMENT_DOES_NOT_INHERIT_PRIOR_CONTEXT_POLICY,
            REATTACH_AFTER_PROCESS_RECREATION_MUST_NOT_DUPLICATE_PARTICIPANT_POLICY,
            PROCESS_RECREATION_CONTINUITY_RESUME_REQUIRES_MATCHING_ID_POLICY,
            V2_RESTART_RECOVERY_MUST_ACCEPT_ANDROID_RESULT_AGAINST_RECOVERED_TASK_POLICY,
            INFLIGHT_TASK_CONTINUITY_REQUIRES_V2_RECOVERY_COOPERATION_POLICY,
            STALE_IDENTITY_MUST_BE_REJECTED_NON_DESTRUCTIVELY_POLICY,
            STALE_ATTACHMENT_ID_PRODUCES_NEW_ATTACHMENT_POLICY,
            DUPLICATE_SIGNAL_MUST_BE_SUPPRESSED_POLICY,
            DUPLICATE_REENTRY_MUST_NOT_CREATE_DUPLICATE_TASK_RECORD_POLICY,
            PARTIAL_RESULT_MUST_BE_PRESERVED_UNTIL_COMPLETION_POLICY,
            PARTIAL_RESULT_IS_SUPERSEDED_BY_TERMINAL_SIGNAL_POLICY,
        ]

    def test_all_16_policy_sentinels_importable(self):
        sentinels = self._import_all_sentinels()
        assert len(sentinels) == 16

    def test_all_sentinels_are_non_empty_strings(self):
        sentinels = self._import_all_sentinels()
        for s in sentinels:
            assert isinstance(s, str)
            assert len(s) > 0

    def test_all_sentinels_mention_pr_l(self):
        sentinels = self._import_all_sentinels()
        for s in sentinels:
            assert "PR-L" in s, f"sentinel missing 'PR-L': {s[:80]!r}"


# ---------------------------------------------------------------------------
# C — AndroidAttachOutcome enum
# ---------------------------------------------------------------------------


class TestAndroidAttachOutcomeEnum:
    def test_new_registration_value(self):
        from core.android_v2_continuity_contract import AndroidAttachOutcome
        assert AndroidAttachOutcome.new_registration.value == "new_registration"

    def test_continuity_resume_value(self):
        from core.android_v2_continuity_contract import AndroidAttachOutcome
        assert AndroidAttachOutcome.continuity_resume.value == "continuity_resume"

    def test_new_attachment_value(self):
        from core.android_v2_continuity_contract import AndroidAttachOutcome
        assert AndroidAttachOutcome.new_attachment.value == "new_attachment"

    def test_failed_value(self):
        from core.android_v2_continuity_contract import AndroidAttachOutcome
        assert AndroidAttachOutcome.failed.value == "failed"

    def test_all_four_values_present(self):
        from core.android_v2_continuity_contract import AndroidAttachOutcome
        expected = {"new_registration", "continuity_resume", "new_attachment", "failed"}
        actual = {v.value for v in AndroidAttachOutcome}
        assert expected == actual


# ---------------------------------------------------------------------------
# D — ContinuityScenario enum
# ---------------------------------------------------------------------------


class TestContinuityScenarioEnum:
    def test_seven_values_present(self):
        from core.android_v2_continuity_contract import ContinuityScenario
        expected = {
            "attach",
            "reconnect",
            "reattach_process_recreation",
            "v2_restart_inflight_task",
            "stale_identity",
            "duplicate_signal",
            "partial_result",
        }
        actual = {v.value for v in ContinuityScenario}
        assert expected == actual


# ---------------------------------------------------------------------------
# E — ContinuityVerificationResult enum
# ---------------------------------------------------------------------------


class TestContinuityVerificationResultEnum:
    def test_four_values_present(self):
        from core.android_v2_continuity_contract import ContinuityVerificationResult
        expected = {"pass", "fail", "advisory", "not_applicable"}
        actual = {v.value for v in ContinuityVerificationResult}
        assert expected == actual


# ---------------------------------------------------------------------------
# F — AndroidAttachRecord dataclass
# ---------------------------------------------------------------------------


class TestAndroidAttachRecord:
    def test_required_fields_present(self):
        from core.android_v2_continuity_contract import (
            AndroidAttachRecord,
            AndroidAttachOutcome,
        )
        rec = AndroidAttachRecord(
            device_id="dev_01",
            runtime_attachment_session_id="ras_001",
        )
        assert rec.device_id == "dev_01"
        assert rec.runtime_attachment_session_id == "ras_001"
        assert rec.attach_outcome == AndroidAttachOutcome.new_registration
        assert rec.prior_entry_state == ""
        assert rec.registry_entry_created is False

    def test_to_dict_contains_expected_keys(self):
        from core.android_v2_continuity_contract import AndroidAttachRecord
        rec = AndroidAttachRecord(
            device_id="dev_02",
            runtime_attachment_session_id="ras_002",
        )
        d = rec.to_dict()
        for key in (
            "device_id",
            "runtime_attachment_session_id",
            "attach_outcome",
            "prior_entry_state",
            "registry_entry_created",
            "timestamp",
        ):
            assert key in d, f"missing key: {key}"

    def test_to_dict_values_serialisable(self):
        from core.android_v2_continuity_contract import AndroidAttachRecord
        rec = AndroidAttachRecord(
            device_id="dev_03",
            runtime_attachment_session_id="ras_003",
        )
        json.dumps(rec.to_dict())


# ---------------------------------------------------------------------------
# G — ContinuityScenarioOutcome dataclass
# ---------------------------------------------------------------------------


class TestContinuityScenarioOutcome:
    def test_required_fields_present(self):
        from core.android_v2_continuity_contract import (
            ContinuityScenarioOutcome,
            ContinuityScenario,
            ContinuityVerificationResult,
        )
        outcome = ContinuityScenarioOutcome(
            scenario=ContinuityScenario.attach,
            result=ContinuityVerificationResult.pass_,
        )
        assert outcome.scenario == ContinuityScenario.attach
        assert outcome.result == ContinuityVerificationResult.pass_
        assert outcome.detail == ""
        assert outcome.policy_reference == ""

    def test_to_dict_contains_expected_keys(self):
        from core.android_v2_continuity_contract import (
            ContinuityScenarioOutcome,
            ContinuityScenario,
            ContinuityVerificationResult,
        )
        outcome = ContinuityScenarioOutcome(
            scenario=ContinuityScenario.reconnect,
            result=ContinuityVerificationResult.fail,
            detail="test detail",
            policy_reference="TEST_POLICY",
        )
        d = outcome.to_dict()
        for key in ("scenario", "result", "detail", "policy_reference", "timestamp"):
            assert key in d

    def test_to_dict_values_serialisable(self):
        from core.android_v2_continuity_contract import (
            ContinuityScenarioOutcome,
            ContinuityScenario,
            ContinuityVerificationResult,
        )
        outcome = ContinuityScenarioOutcome(
            scenario=ContinuityScenario.stale_identity,
            result=ContinuityVerificationResult.advisory,
        )
        json.dumps(outcome.to_dict())


# ---------------------------------------------------------------------------
# H — JointContinuityContractSnapshot dataclass
# ---------------------------------------------------------------------------


class TestJointContinuityContractSnapshot:
    def test_required_fields_present(self):
        from core.android_v2_continuity_contract import JointContinuityContractSnapshot
        snap = JointContinuityContractSnapshot()
        assert snap.authority
        assert snap.prl_sentinel
        assert isinstance(snap.scenarios_verified, list)
        assert isinstance(snap.all_pass, bool)
        assert isinstance(snap.fail_count, int)
        assert isinstance(snap.advisory_count, int)
        assert isinstance(snap.policy_sentinels, list)
        assert snap.snapshot_id

    def test_to_dict_contains_expected_top_level_keys(self):
        from core.android_v2_continuity_contract import JointContinuityContractSnapshot
        snap = JointContinuityContractSnapshot()
        d = snap.to_dict()
        for key in (
            "authority",
            "prl_sentinel",
            "scenarios_verified",
            "all_pass",
            "fail_count",
            "advisory_count",
            "policy_sentinels",
            "snapshot_id",
            "timestamp",
        ):
            assert key in d, f"missing key: {key}"

    def test_to_dict_is_json_serialisable(self):
        from core.android_v2_continuity_contract import JointContinuityContractSnapshot
        snap = JointContinuityContractSnapshot()
        json.dumps(snap.to_dict())


# ---------------------------------------------------------------------------
# I — to_json() valid JSON
# ---------------------------------------------------------------------------


class TestToJson:
    def test_android_attach_record_to_json(self):
        from core.android_v2_continuity_contract import AndroidAttachRecord
        rec = AndroidAttachRecord(device_id="d", runtime_attachment_session_id="r")
        parsed = json.loads(rec.to_json())
        assert parsed["device_id"] == "d"

    def test_continuity_scenario_outcome_to_json(self):
        from core.android_v2_continuity_contract import (
            ContinuityScenarioOutcome,
            ContinuityScenario,
            ContinuityVerificationResult,
        )
        outcome = ContinuityScenarioOutcome(
            scenario=ContinuityScenario.attach,
            result=ContinuityVerificationResult.pass_,
        )
        parsed = json.loads(outcome.to_json())
        assert parsed["scenario"] == "attach"
        assert parsed["result"] == "pass"

    def test_snapshot_to_json(self):
        from core.android_v2_continuity_contract import JointContinuityContractSnapshot
        snap = JointContinuityContractSnapshot()
        parsed = json.loads(snap.to_json())
        assert "prl_sentinel" in parsed


# ---------------------------------------------------------------------------
# J — classify_attach_outcome: no prior entry → new_registration
# ---------------------------------------------------------------------------


class TestClassifyAttachOutcomeNewRegistration:
    def test_no_prior_entry_is_new_registration(self):
        from core.android_v2_continuity_contract import (
            classify_attach_outcome,
            AndroidAttachOutcome,
        )
        result = classify_attach_outcome(
            "dev_01", "ras_001",
            prior_entry_state="",
            registry_entry_created=True,
        )
        assert result.attach_outcome == AndroidAttachOutcome.new_registration

    def test_device_id_and_attachment_id_propagated(self):
        from core.android_v2_continuity_contract import classify_attach_outcome
        result = classify_attach_outcome(
            "dev_99", "ras_xyz",
            prior_entry_state="",
            registry_entry_created=True,
        )
        assert result.device_id == "dev_99"
        assert result.runtime_attachment_session_id == "ras_xyz"
        assert result.registry_entry_created is True


# ---------------------------------------------------------------------------
# K — classify_attach_outcome: prior active entry → continuity_resume
# ---------------------------------------------------------------------------


class TestClassifyAttachOutcomeContinuityResume:
    def test_prior_active_entry_is_continuity_resume(self):
        from core.android_v2_continuity_contract import (
            classify_attach_outcome,
            AndroidAttachOutcome,
        )
        result = classify_attach_outcome(
            "dev_01", "ras_001",
            prior_entry_state="active",
            registry_entry_created=True,
        )
        assert result.attach_outcome == AndroidAttachOutcome.continuity_resume


# ---------------------------------------------------------------------------
# L — classify_attach_outcome: prior replaced entry → new_attachment
# ---------------------------------------------------------------------------


class TestClassifyAttachOutcomeNewAttachment:
    def test_prior_replaced_entry_is_new_attachment(self):
        from core.android_v2_continuity_contract import (
            classify_attach_outcome,
            AndroidAttachOutcome,
        )
        result = classify_attach_outcome(
            "dev_01", "ras_new",
            prior_entry_state="replaced",
            registry_entry_created=True,
        )
        assert result.attach_outcome == AndroidAttachOutcome.new_attachment


# ---------------------------------------------------------------------------
# M — classify_attach_outcome: registry_entry_created=False → failed
# ---------------------------------------------------------------------------


class TestClassifyAttachOutcomeFailed:
    def test_registry_not_created_is_failed(self):
        from core.android_v2_continuity_contract import (
            classify_attach_outcome,
            AndroidAttachOutcome,
        )
        result = classify_attach_outcome(
            "dev_01", "ras_001",
            prior_entry_state="",
            registry_entry_created=False,
        )
        assert result.attach_outcome == AndroidAttachOutcome.failed


# ---------------------------------------------------------------------------
# N — classify_reconnect_continuity_outcome: continuity_resume + preserved → pass
# ---------------------------------------------------------------------------


class TestClassifyReconnectPass:
    def test_continuity_resume_preserved_is_pass(self):
        from core.android_v2_continuity_contract import (
            classify_reconnect_continuity_outcome,
            ContinuityVerificationResult,
        )
        outcome = classify_reconnect_continuity_outcome(
            "continuity_resume",
            runtime_attachment_session_id_preserved=True,
            reconnect_count_incremented=True,
        )
        assert outcome.result == ContinuityVerificationResult.pass_


# ---------------------------------------------------------------------------
# O — continuity_resume + NOT preserved → fail
# ---------------------------------------------------------------------------


class TestClassifyReconnectContinuityResumeNotPreservedFail:
    def test_continuity_resume_not_preserved_is_fail(self):
        from core.android_v2_continuity_contract import (
            classify_reconnect_continuity_outcome,
            ContinuityVerificationResult,
        )
        outcome = classify_reconnect_continuity_outcome(
            "continuity_resume",
            runtime_attachment_session_id_preserved=False,
            reconnect_count_incremented=True,
        )
        assert outcome.result == ContinuityVerificationResult.fail


# ---------------------------------------------------------------------------
# P — continuity_resume + no increment → advisory
# ---------------------------------------------------------------------------


class TestClassifyReconnectNoIncrementAdvisory:
    def test_continuity_resume_no_increment_is_advisory(self):
        from core.android_v2_continuity_contract import (
            classify_reconnect_continuity_outcome,
            ContinuityVerificationResult,
        )
        outcome = classify_reconnect_continuity_outcome(
            "continuity_resume",
            runtime_attachment_session_id_preserved=True,
            reconnect_count_incremented=False,
        )
        assert outcome.result == ContinuityVerificationResult.advisory


# ---------------------------------------------------------------------------
# Q — new_attachment → pass
# ---------------------------------------------------------------------------


class TestClassifyReconnectNewAttachmentPass:
    def test_new_attachment_is_pass(self):
        from core.android_v2_continuity_contract import (
            classify_reconnect_continuity_outcome,
            ContinuityVerificationResult,
        )
        outcome = classify_reconnect_continuity_outcome(
            "new_attachment",
        )
        assert outcome.result == ContinuityVerificationResult.pass_


# ---------------------------------------------------------------------------
# R — unknown outcome → fail
# ---------------------------------------------------------------------------


class TestClassifyReconnectUnknownFail:
    def test_unknown_outcome_is_fail(self):
        from core.android_v2_continuity_contract import (
            classify_reconnect_continuity_outcome,
            ContinuityVerificationResult,
        )
        outcome = classify_reconnect_continuity_outcome("bogus_outcome")
        assert outcome.result == ContinuityVerificationResult.fail


# ---------------------------------------------------------------------------
# S — reattach process recreation: active + match + continuity_resume → pass
# ---------------------------------------------------------------------------


class TestReattachProcessRecreationPass:
    def test_active_match_continuity_resume_is_pass(self):
        from core.android_v2_continuity_contract import (
            classify_reattach_process_recreation_outcome,
            ContinuityVerificationResult,
        )
        outcome = classify_reattach_process_recreation_outcome(
            "continuity_resume",
            prior_entry_was_active_or_detached=True,
            attachment_id_matched=True,
        )
        assert outcome.result == ContinuityVerificationResult.pass_


# ---------------------------------------------------------------------------
# T — active + match + new_attachment → fail (contract violation)
# ---------------------------------------------------------------------------


class TestReattachProcessRecreationContractViolation:
    def test_active_match_new_attachment_is_fail(self):
        from core.android_v2_continuity_contract import (
            classify_reattach_process_recreation_outcome,
            ContinuityVerificationResult,
        )
        outcome = classify_reattach_process_recreation_outcome(
            "new_attachment",
            prior_entry_was_active_or_detached=True,
            attachment_id_matched=True,
        )
        assert outcome.result == ContinuityVerificationResult.fail


# ---------------------------------------------------------------------------
# U — mismatched ID + new_attachment → pass
# ---------------------------------------------------------------------------


class TestReattachProcessRecreationMismatchedId:
    def test_mismatched_id_new_attachment_is_pass(self):
        from core.android_v2_continuity_contract import (
            classify_reattach_process_recreation_outcome,
            ContinuityVerificationResult,
        )
        outcome = classify_reattach_process_recreation_outcome(
            "new_attachment",
            prior_entry_was_active_or_detached=True,
            attachment_id_matched=False,
        )
        assert outcome.result == ContinuityVerificationResult.pass_


# ---------------------------------------------------------------------------
# V — terminal entry + match + new_attachment → pass
# ---------------------------------------------------------------------------


class TestReattachProcessRecreationTerminalEntry:
    def test_terminal_entry_new_attachment_is_pass(self):
        from core.android_v2_continuity_contract import (
            classify_reattach_process_recreation_outcome,
            ContinuityVerificationResult,
        )
        # prior entry is terminal (not active/detached), ID matches;
        # new_attachment is correct
        outcome = classify_reattach_process_recreation_outcome(
            "new_attachment",
            prior_entry_was_active_or_detached=False,
            attachment_id_matched=True,
        )
        assert outcome.result == ContinuityVerificationResult.pass_


# ---------------------------------------------------------------------------
# W — verify_stale_identity_handling: was_reconciled=True → fail
# ---------------------------------------------------------------------------


class TestStaleIdentityWasReconciledFail:
    def test_was_reconciled_true_is_fail(self):
        from core.android_v2_continuity_contract import (
            verify_stale_identity_handling,
            ContinuityVerificationResult,
        )
        outcome = verify_stale_identity_handling(
            was_reconciled=True,
            reject_reason="",
            v2_state_altered=False,
            phantom_record_created=False,
        )
        assert outcome.result == ContinuityVerificationResult.fail


# ---------------------------------------------------------------------------
# X — verify_stale_identity_handling: v2_state_altered=True → fail
# ---------------------------------------------------------------------------


class TestStaleIdentityV2StateAlteredFail:
    def test_v2_state_altered_is_fail(self):
        from core.android_v2_continuity_contract import (
            verify_stale_identity_handling,
            ContinuityVerificationResult,
        )
        outcome = verify_stale_identity_handling(
            was_reconciled=False,
            reject_reason="stale_session",
            v2_state_altered=True,
            phantom_record_created=False,
        )
        assert outcome.result == ContinuityVerificationResult.fail


# ---------------------------------------------------------------------------
# Y — verify_stale_identity_handling: phantom_record_created=True → fail
# ---------------------------------------------------------------------------


class TestStaleIdentityPhantomRecordFail:
    def test_phantom_record_created_is_fail(self):
        from core.android_v2_continuity_contract import (
            verify_stale_identity_handling,
            ContinuityVerificationResult,
        )
        outcome = verify_stale_identity_handling(
            was_reconciled=False,
            reject_reason="stale_session",
            v2_state_altered=False,
            phantom_record_created=True,
        )
        assert outcome.result == ContinuityVerificationResult.fail


# ---------------------------------------------------------------------------
# Z — verify_stale_identity_handling: reject_reason empty → advisory
# ---------------------------------------------------------------------------


class TestStaleIdentityEmptyRejectReasonAdvisory:
    def test_empty_reject_reason_is_advisory(self):
        from core.android_v2_continuity_contract import (
            verify_stale_identity_handling,
            ContinuityVerificationResult,
        )
        outcome = verify_stale_identity_handling(
            was_reconciled=False,
            reject_reason="",
            v2_state_altered=False,
            phantom_record_created=False,
        )
        assert outcome.result == ContinuityVerificationResult.advisory


# ---------------------------------------------------------------------------
# AA — verify_stale_identity_handling: all-clear → pass
# ---------------------------------------------------------------------------


class TestStaleIdentityAllClearPass:
    def test_all_clear_is_pass(self):
        from core.android_v2_continuity_contract import (
            verify_stale_identity_handling,
            ContinuityVerificationResult,
        )
        outcome = verify_stale_identity_handling(
            was_reconciled=False,
            reject_reason="missing_lookup_key",
            v2_state_altered=False,
            phantom_record_created=False,
        )
        assert outcome.result == ContinuityVerificationResult.pass_
        assert "missing_lookup_key" in outcome.detail


# ---------------------------------------------------------------------------
# AB — verify_duplicate_signal_suppression: not suppressed → fail
# ---------------------------------------------------------------------------


class TestDuplicateSignalNotSuppressedFail:
    def test_not_suppressed_is_fail(self):
        from core.android_v2_continuity_contract import (
            verify_duplicate_signal_suppression,
            ContinuityVerificationResult,
        )
        outcome = verify_duplicate_signal_suppression(
            signal_suppressed=False,
            reconciler_called_count=2,
        )
        assert outcome.result == ContinuityVerificationResult.fail


# ---------------------------------------------------------------------------
# AC — verify_duplicate_signal_suppression: reconciler called 2× → fail
# ---------------------------------------------------------------------------


class TestDuplicateSignalReconcilerCalledTwiceFail:
    def test_reconciler_called_twice_is_fail(self):
        from core.android_v2_continuity_contract import (
            verify_duplicate_signal_suppression,
            ContinuityVerificationResult,
        )
        outcome = verify_duplicate_signal_suppression(
            signal_suppressed=True,
            reconciler_called_count=2,
        )
        assert outcome.result == ContinuityVerificationResult.fail


# ---------------------------------------------------------------------------
# AD — verify_duplicate_signal_suppression: suppressed, called once → pass
# ---------------------------------------------------------------------------


class TestDuplicateSignalSuppressedOncePass:
    def test_suppressed_called_once_is_pass(self):
        from core.android_v2_continuity_contract import (
            verify_duplicate_signal_suppression,
            ContinuityVerificationResult,
        )
        outcome = verify_duplicate_signal_suppression(
            signal_suppressed=True,
            reconciler_called_count=1,
        )
        assert outcome.result == ContinuityVerificationResult.pass_


# ---------------------------------------------------------------------------
# AE — suppressed, called zero times → pass
# ---------------------------------------------------------------------------


class TestDuplicateSignalSuppressedZeroTimesPass:
    def test_suppressed_called_zero_is_pass(self):
        from core.android_v2_continuity_contract import (
            verify_duplicate_signal_suppression,
            ContinuityVerificationResult,
        )
        outcome = verify_duplicate_signal_suppression(
            signal_suppressed=True,
            reconciler_called_count=0,
        )
        assert outcome.result == ContinuityVerificationResult.pass_


# ---------------------------------------------------------------------------
# AF — build_joint_continuity_contract_snapshot: no scenarios → all_pass=True
# ---------------------------------------------------------------------------


class TestBuildSnapshotNoScenarios:
    def test_empty_scenarios_all_pass_true(self):
        from core.android_v2_continuity_contract import (
            build_joint_continuity_contract_snapshot,
        )
        snap = build_joint_continuity_contract_snapshot()
        assert snap.all_pass is True
        assert snap.fail_count == 0
        assert snap.advisory_count == 0
        assert snap.scenarios_verified == []


# ---------------------------------------------------------------------------
# AG — build_joint_continuity_contract_snapshot: one fail → all_pass=False
# ---------------------------------------------------------------------------


class TestBuildSnapshotOneFail:
    def test_one_fail_sets_all_pass_false(self):
        from core.android_v2_continuity_contract import (
            build_joint_continuity_contract_snapshot,
            ContinuityScenarioOutcome,
            ContinuityScenario,
            ContinuityVerificationResult,
        )
        scenarios = [
            ContinuityScenarioOutcome(
                scenario=ContinuityScenario.attach,
                result=ContinuityVerificationResult.fail,
                detail="test failure",
            )
        ]
        snap = build_joint_continuity_contract_snapshot(scenarios)
        assert snap.all_pass is False
        assert snap.fail_count == 1


# ---------------------------------------------------------------------------
# AH — build_joint_continuity_contract_snapshot: policy_sentinels has 16 entries
# ---------------------------------------------------------------------------


class TestBuildSnapshotPolicySentinels:
    def test_policy_sentinels_count_is_16(self):
        from core.android_v2_continuity_contract import (
            build_joint_continuity_contract_snapshot,
        )
        snap = build_joint_continuity_contract_snapshot()
        assert len(snap.policy_sentinels) == 16


# ---------------------------------------------------------------------------
# AI — get_joint_continuity_contract_snapshot returns correct type
# ---------------------------------------------------------------------------


class TestGetJointContinuityContractSnapshot:
    def test_returns_snapshot_instance(self):
        from core.android_v2_continuity_contract import (
            get_joint_continuity_contract_snapshot,
            JointContinuityContractSnapshot,
        )
        snap = get_joint_continuity_contract_snapshot()
        assert isinstance(snap, JointContinuityContractSnapshot)

    def test_snapshot_has_non_empty_sentinel(self):
        from core.android_v2_continuity_contract import (
            get_joint_continuity_contract_snapshot,
        )
        snap = get_joint_continuity_contract_snapshot()
        assert "PR-L" in snap.prl_sentinel


# ---------------------------------------------------------------------------
# AJ — is_android_v2_continuity_healthy: True for empty snapshot
# ---------------------------------------------------------------------------


class TestIsContinuityHealthyEmpty:
    def test_empty_snapshot_is_healthy(self):
        from core.android_v2_continuity_contract import (
            is_android_v2_continuity_healthy,
        )
        assert is_android_v2_continuity_healthy() is True


# ---------------------------------------------------------------------------
# AK — is_android_v2_continuity_healthy: False when fail_count > 0
# ---------------------------------------------------------------------------


class TestIsContinuityHealthyWithFail:
    def test_snapshot_with_fail_is_not_healthy(self):
        from core.android_v2_continuity_contract import (
            is_android_v2_continuity_healthy,
            JointContinuityContractSnapshot,
        )
        snap = JointContinuityContractSnapshot(fail_count=1, all_pass=False)
        assert is_android_v2_continuity_healthy(snap) is False


# ---------------------------------------------------------------------------
# AL — Snapshot to_dict() contains all expected top-level keys
# ---------------------------------------------------------------------------


class TestSnapshotToDictKeys:
    def test_all_expected_keys_present(self):
        from core.android_v2_continuity_contract import (
            get_joint_continuity_contract_snapshot,
        )
        d = get_joint_continuity_contract_snapshot().to_dict()
        expected_keys = {
            "authority",
            "prl_sentinel",
            "scenarios_verified",
            "all_pass",
            "fail_count",
            "advisory_count",
            "policy_sentinels",
            "snapshot_id",
            "timestamp",
        }
        assert expected_keys.issubset(d.keys())


# ---------------------------------------------------------------------------
# AM — Snapshot to_json() is valid JSON
# ---------------------------------------------------------------------------


class TestSnapshotToJsonIsValidJson:
    def test_to_json_parseable(self):
        from core.android_v2_continuity_contract import (
            get_joint_continuity_contract_snapshot,
        )
        snap = get_joint_continuity_contract_snapshot()
        parsed = json.loads(snap.to_json())
        assert isinstance(parsed, dict)


# ---------------------------------------------------------------------------
# AN — prl_sentinel contains 'PR-L' and 'package=L'
# ---------------------------------------------------------------------------


class TestPrlSentinelContents:
    def test_prl_sentinel_contains_pr_l_and_package_l(self):
        from core.android_v2_continuity_contract import (
            ANDROID_V2_CONTINUITY_CONTRACT_PRL_SENTINEL,
        )
        assert "PR-L" in ANDROID_V2_CONTINUITY_CONTRACT_PRL_SENTINEL
        assert "package=L" in ANDROID_V2_CONTINUITY_CONTRACT_PRL_SENTINEL


# ---------------------------------------------------------------------------
# AO — Authority boundary: ANDROID_IS_DURABLE_PARTICIPANT mentions
#      'orchestration authority'
# ---------------------------------------------------------------------------


class TestAuthorityBoundaryAndroidPolicy:
    def test_android_policy_mentions_orchestration_authority(self):
        from core.android_v2_continuity_contract import (
            ANDROID_IS_DURABLE_PARTICIPANT_NOT_ORCHESTRATION_AUTHORITY_POLICY,
        )
        assert (
            "orchestration authority"
            in ANDROID_IS_DURABLE_PARTICIPANT_NOT_ORCHESTRATION_AUTHORITY_POLICY.lower()
        )


# ---------------------------------------------------------------------------
# AP — V2_IS_CANONICAL_ORCHESTRATION_AUTHORITY_POLICY mentions 'V2'
# ---------------------------------------------------------------------------


class TestAuthorityBoundaryV2Policy:
    def test_v2_policy_mentions_v2(self):
        from core.android_v2_continuity_contract import (
            V2_IS_CANONICAL_ORCHESTRATION_AUTHORITY_POLICY,
        )
        assert "V2" in V2_IS_CANONICAL_ORCHESTRATION_AUTHORITY_POLICY


# ---------------------------------------------------------------------------
# AQ — ATTACH_MUST_CREATE_REGISTRY_ENTRY mentions 'AttachedSessionRegistry'
# ---------------------------------------------------------------------------


class TestAttachPolicyMentionsRegistry:
    def test_attach_policy_mentions_registry(self):
        from core.android_v2_continuity_contract import (
            ATTACH_MUST_CREATE_REGISTRY_ENTRY_POLICY,
        )
        assert (
            "AttachedSessionRegistry"
            in ATTACH_MUST_CREATE_REGISTRY_ENTRY_POLICY
        )


# ---------------------------------------------------------------------------
# AR — RECONNECT_CONTINUITY_RESUME mentions 'runtime_attachment_session_id'
# ---------------------------------------------------------------------------


class TestReconnectPolicyMentionsAttachmentId:
    def test_reconnect_policy_mentions_attachment_id(self):
        from core.android_v2_continuity_contract import (
            RECONNECT_CONTINUITY_RESUME_PRESERVES_ATTACHMENT_ID_POLICY,
        )
        assert (
            "runtime_attachment_session_id"
            in RECONNECT_CONTINUITY_RESUME_PRESERVES_ATTACHMENT_ID_POLICY
        )


# ---------------------------------------------------------------------------
# AS — STALE_IDENTITY_MUST_BE_REJECTED mentions 'non-destructive'
# ---------------------------------------------------------------------------


class TestStaleIdentityPolicyMentionsNonDestructive:
    def test_stale_policy_mentions_non_destructive(self):
        from core.android_v2_continuity_contract import (
            STALE_IDENTITY_MUST_BE_REJECTED_NON_DESTRUCTIVELY_POLICY,
        )
        lower = STALE_IDENTITY_MUST_BE_REJECTED_NON_DESTRUCTIVELY_POLICY.lower()
        assert "non-destructive" in lower or "non_destructive" in lower or "was_reconciled=false" in lower


# ---------------------------------------------------------------------------
# AT — DUPLICATE_SIGNAL_MUST_BE_SUPPRESSED mentions 'idempotency_key'
# ---------------------------------------------------------------------------


class TestDuplicatePolicyMentionsIdempotencyKey:
    def test_duplicate_policy_mentions_idempotency_key(self):
        from core.android_v2_continuity_contract import (
            DUPLICATE_SIGNAL_MUST_BE_SUPPRESSED_POLICY,
        )
        assert "idempotency_key" in DUPLICATE_SIGNAL_MUST_BE_SUPPRESSED_POLICY


# ---------------------------------------------------------------------------
# AU — PARTIAL_RESULT_MUST_BE_PRESERVED mentions 'partial result'
# ---------------------------------------------------------------------------


class TestPartialResultPolicyMentionsPartialResult:
    def test_partial_result_policy_mentions_partial_result(self):
        from core.android_v2_continuity_contract import (
            PARTIAL_RESULT_MUST_BE_PRESERVED_UNTIL_COMPLETION_POLICY,
        )
        assert (
            "partial result"
            in PARTIAL_RESULT_MUST_BE_PRESERVED_UNTIL_COMPLETION_POLICY.lower()
        )


# ---------------------------------------------------------------------------
# AV — V2_RESTART_RECOVERY mentions 'recovered task'
# ---------------------------------------------------------------------------


class TestV2RestartPolicyMentionsRecoveredTask:
    def test_v2_restart_policy_mentions_recovered_task(self):
        from core.android_v2_continuity_contract import (
            V2_RESTART_RECOVERY_MUST_ACCEPT_ANDROID_RESULT_AGAINST_RECOVERED_TASK_POLICY,
        )
        assert (
            "recovered task"
            in V2_RESTART_RECOVERY_MUST_ACCEPT_ANDROID_RESULT_AGAINST_RECOVERED_TASK_POLICY.lower()
        )


# ---------------------------------------------------------------------------
# AW — classify_attach_outcome: prior detached → continuity_resume
# ---------------------------------------------------------------------------


class TestClassifyAttachOutcomeDetachedContinuityResume:
    def test_prior_detached_entry_is_continuity_resume(self):
        from core.android_v2_continuity_contract import (
            classify_attach_outcome,
            AndroidAttachOutcome,
        )
        result = classify_attach_outcome(
            "dev_05", "ras_005",
            prior_entry_state="detached",
            registry_entry_created=True,
        )
        assert result.attach_outcome == AndroidAttachOutcome.continuity_resume


# ---------------------------------------------------------------------------
# AX — classify_attach_outcome: prior invalidated → new_attachment
# ---------------------------------------------------------------------------


class TestClassifyAttachOutcomeInvalidatedNewAttachment:
    def test_prior_invalidated_entry_is_new_attachment(self):
        from core.android_v2_continuity_contract import (
            classify_attach_outcome,
            AndroidAttachOutcome,
        )
        result = classify_attach_outcome(
            "dev_06", "ras_006",
            prior_entry_state="invalidated",
            registry_entry_created=True,
        )
        assert result.attach_outcome == AndroidAttachOutcome.new_attachment


# ---------------------------------------------------------------------------
# AY — Mixed scenario snapshot counted correctly
# ---------------------------------------------------------------------------


class TestMixedScenarioSnapshotCounts:
    def _make_outcomes(self):
        from core.android_v2_continuity_contract import (
            ContinuityScenarioOutcome,
            ContinuityScenario,
            ContinuityVerificationResult,
        )
        return [
            ContinuityScenarioOutcome(
                scenario=ContinuityScenario.attach,
                result=ContinuityVerificationResult.pass_,
            ),
            ContinuityScenarioOutcome(
                scenario=ContinuityScenario.reconnect,
                result=ContinuityVerificationResult.fail,
            ),
            ContinuityScenarioOutcome(
                scenario=ContinuityScenario.stale_identity,
                result=ContinuityVerificationResult.advisory,
            ),
            ContinuityScenarioOutcome(
                scenario=ContinuityScenario.duplicate_signal,
                result=ContinuityVerificationResult.pass_,
            ),
        ]

    def test_fail_count_correct(self):
        from core.android_v2_continuity_contract import (
            build_joint_continuity_contract_snapshot,
        )
        snap = build_joint_continuity_contract_snapshot(self._make_outcomes())
        assert snap.fail_count == 1

    def test_advisory_count_correct(self):
        from core.android_v2_continuity_contract import (
            build_joint_continuity_contract_snapshot,
        )
        snap = build_joint_continuity_contract_snapshot(self._make_outcomes())
        assert snap.advisory_count == 1

    def test_all_pass_false_when_there_is_fail(self):
        from core.android_v2_continuity_contract import (
            build_joint_continuity_contract_snapshot,
        )
        snap = build_joint_continuity_contract_snapshot(self._make_outcomes())
        assert snap.all_pass is False


# ---------------------------------------------------------------------------
# AZ — Scenario outcomes ordered by insertion
# ---------------------------------------------------------------------------


class TestScenarioOutcomesOrder:
    def test_scenarios_ordered_by_insertion(self):
        from core.android_v2_continuity_contract import (
            build_joint_continuity_contract_snapshot,
            ContinuityScenarioOutcome,
            ContinuityScenario,
            ContinuityVerificationResult,
        )
        scenarios = [
            ContinuityScenarioOutcome(
                scenario=ContinuityScenario.attach,
                result=ContinuityVerificationResult.pass_,
            ),
            ContinuityScenarioOutcome(
                scenario=ContinuityScenario.stale_identity,
                result=ContinuityVerificationResult.pass_,
            ),
            ContinuityScenarioOutcome(
                scenario=ContinuityScenario.reconnect,
                result=ContinuityVerificationResult.pass_,
            ),
        ]
        snap = build_joint_continuity_contract_snapshot(scenarios)
        assert snap.scenarios_verified[0].scenario == ContinuityScenario.attach
        assert snap.scenarios_verified[1].scenario == ContinuityScenario.stale_identity
        assert snap.scenarios_verified[2].scenario == ContinuityScenario.reconnect
