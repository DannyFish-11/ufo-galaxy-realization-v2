"""tests/test_task3_distributed_subject_contract_v1.py
=======================================================
Regression tests for PR-Task3: Distributed Subject Contract v1 and
Participant Lifecycle Schema.

Coverage
--------
A.  All ten contract dimensions are present in the field registry.
B.  All six lifecycle labels are represented in the field registry.
C.  Field descriptors are consistent: name, dimension, label all set.
D.  ``build_contract_manifest()`` produces a valid, JSON-round-trippable dict.
E.  ``build_contract_version()`` reports version="v1" and correct field count.
F.  ``get_fields_by_dimension()`` returns correct subsets.
G.  ``get_fields_by_label()`` returns correct subsets.
H.  ``get_field()`` look-up by name finds known fields and returns None for
    unknown names.
I.  All participant lifecycle states are defined.
J.  All participant roles are defined.
K.  All transition triggers are defined.
L.  ``PARTICIPANT_STATE_TRANSITIONS`` table is non-empty and consistent.
M.  ``get_allowed_transitions()`` returns correct subsets.
N.  ``ParticipantRecord.apply_transition()`` correctly applies allowed
    transitions.
O.  ``ParticipantRecord.apply_transition()`` raises ValueError for disallowed
    transitions.
P.  ``build_participant_record()`` factory produces a valid record.
Q.  ``ParticipantRecord.to_dict()`` and ``to_json()`` are stable and
    round-trippable.
R.  ``build_lifecycle_schema_manifest()`` produces a valid JSON-round-trippable
    dict covering roles, states, triggers, and transitions.
S.  ``contracts/__init__.py`` re-exports the new public symbols from both
    modules.
T.  Key sentinel constants are non-empty strings.
U.  canonical / evidence_only labels are correctly applied to key fields
    that must NOT drift.
"""

from __future__ import annotations

import json

import pytest

# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------

from contracts.distributed_subject_contract_v1 import (
    CONTRACT_FIELD_LABEL_IS_EXPLICIT_POLICY,
    DISTRIBUTED_SUBJECT_CONTRACT_V1_FIELDS,
    DISTRIBUTED_SUBJECT_CONTRACT_V1_SENTINEL,
    PARTICIPANT_LIFECYCLE_IS_GOVERNED_BY_CENTER,
    SUBJECT_EVIDENCE_IS_NOT_CANONICAL_TRUTH,
    ContractFieldLabel,
    DistributedSubjectContractVersion,
    SubjectContractDimension,
    SubjectContractField,
    build_contract_manifest,
    build_contract_version,
    get_field,
    get_fields_by_dimension,
    get_fields_by_label,
)

from contracts.participant_lifecycle_schema import (
    PARTICIPANT_LIFECYCLE_SCHEMA_SENTINEL,
    PARTICIPANT_ROLE_IS_ASSIGNED_BY_CENTER,
    PARTICIPANT_STATE_TRANSITIONS,
    PARTICIPANT_STATE_TRANSITIONS_ARE_AUTHORITATIVE,
    ParticipantLifecycleState,
    ParticipantRecord,
    ParticipantRole,
    ParticipantStateTransition,
    ParticipantTransitionTrigger,
    build_lifecycle_schema_manifest,
    build_participant_record,
    get_allowed_transitions,
)


# ===========================================================================
# A. All ten contract dimensions present
# ===========================================================================


class TestContractDimensions:
    """All ten dimensions must be represented in the field registry."""

    REQUIRED_DIMENSIONS = {
        SubjectContractDimension.SUBJECT_IDENTITY,
        SubjectContractDimension.RUNTIME_ATTACHMENT,
        SubjectContractDimension.CONTINUITY,
        SubjectContractDimension.PARTICIPANT_TRUTH,
        SubjectContractDimension.EXECUTION_RESULT,
        SubjectContractDimension.HANDOFF_TAKEOVER,
        SubjectContractDimension.RECOVERY_REPLAY,
        SubjectContractDimension.DIAGNOSTICS,
        SubjectContractDimension.READINESS_POSTURE_CAPABILITY_BUSY,
        SubjectContractDimension.PARTICIPANT_LIFECYCLE,
    }

    def test_A1_all_dimensions_covered(self):
        present = {f.dimension for f in DISTRIBUTED_SUBJECT_CONTRACT_V1_FIELDS}
        missing = self.REQUIRED_DIMENSIONS - present
        assert not missing, f"Missing dimensions: {missing}"

    def test_A2_each_dimension_has_at_least_one_field(self):
        for dim in self.REQUIRED_DIMENSIONS:
            fields = get_fields_by_dimension(dim)
            assert fields, f"Dimension {dim.value!r} has no fields"


# ===========================================================================
# B. All six lifecycle labels represented
# ===========================================================================


class TestLifecycleLabels:
    REQUIRED_LABELS = {
        ContractFieldLabel.CANONICAL,
        ContractFieldLabel.COMPAT,
        ContractFieldLabel.TRANSITIONAL,
        ContractFieldLabel.EVIDENCE_ONLY,
    }

    def test_B1_required_labels_represented(self):
        present = {f.label for f in DISTRIBUTED_SUBJECT_CONTRACT_V1_FIELDS}
        missing = self.REQUIRED_LABELS - present
        assert not missing, f"Missing labels: {missing}"

    def test_B2_all_labels_in_enum(self):
        assert ContractFieldLabel.CANONICAL.value == "canonical"
        assert ContractFieldLabel.COMPAT.value == "compat"
        assert ContractFieldLabel.TRANSITIONAL.value == "transitional"
        assert ContractFieldLabel.EXPERIMENTAL.value == "experimental"
        assert ContractFieldLabel.DEPRECATED.value == "deprecated"
        assert ContractFieldLabel.EVIDENCE_ONLY.value == "evidence_only"


# ===========================================================================
# C. Field descriptor consistency
# ===========================================================================


class TestFieldDescriptors:
    def test_C1_all_fields_have_name(self):
        for f in DISTRIBUTED_SUBJECT_CONTRACT_V1_FIELDS:
            assert f.name, f"Empty name in field: {f}"

    def test_C2_all_fields_have_dimension(self):
        for f in DISTRIBUTED_SUBJECT_CONTRACT_V1_FIELDS:
            assert isinstance(f.dimension, SubjectContractDimension)

    def test_C3_all_fields_have_label(self):
        for f in DISTRIBUTED_SUBJECT_CONTRACT_V1_FIELDS:
            assert isinstance(f.label, ContractFieldLabel)

    def test_C4_to_dict_has_expected_keys(self):
        f = DISTRIBUTED_SUBJECT_CONTRACT_V1_FIELDS[0]
        d = f.to_dict()
        assert "name" in d
        assert "dimension" in d
        assert "label" in d
        assert "description" in d
        assert "v2_anchor" in d
        assert "android_anchor" in d
        assert "notes" in d

    def test_C5_field_names_unique(self):
        names = [f.name for f in DISTRIBUTED_SUBJECT_CONTRACT_V1_FIELDS]
        assert len(names) == len(set(names)), "Duplicate field names detected"


# ===========================================================================
# D. build_contract_manifest() round-trip
# ===========================================================================


class TestContractManifest:
    def test_D1_manifest_has_required_top_level_keys(self):
        m = build_contract_manifest()
        assert "version" in m
        assert "sentinel" in m
        assert "policies" in m
        assert "dimensions" in m
        assert "labels" in m
        assert "fields" in m

    def test_D2_manifest_json_round_trip(self):
        m = build_contract_manifest()
        serialised = json.dumps(m)
        recovered = json.loads(serialised)
        assert recovered["version"] == "v1"
        assert len(recovered["fields"]) == len(DISTRIBUTED_SUBJECT_CONTRACT_V1_FIELDS)

    def test_D3_manifest_dimensions_match_enum(self):
        m = build_contract_manifest()
        expected = {d.value for d in SubjectContractDimension}
        actual = set(m["dimensions"])
        assert expected == actual

    def test_D4_manifest_labels_match_enum(self):
        m = build_contract_manifest()
        expected = {l.value for l in ContractFieldLabel}
        actual = set(m["labels"])
        assert expected == actual


# ===========================================================================
# E. build_contract_version()
# ===========================================================================


class TestContractVersion:
    def test_E1_version_is_v1(self):
        v = build_contract_version()
        assert v.version == "v1"

    def test_E2_field_count_matches_registry(self):
        v = build_contract_version()
        assert v.field_count == len(DISTRIBUTED_SUBJECT_CONTRACT_V1_FIELDS)

    def test_E3_dimensions_list_matches_enum(self):
        v = build_contract_version()
        assert set(v.dimensions) == {d.value for d in SubjectContractDimension}

    def test_E4_to_dict_round_trippable(self):
        v = build_contract_version()
        d = v.to_dict()
        serialised = json.dumps(d)
        recovered = json.loads(serialised)
        assert recovered["version"] == "v1"


# ===========================================================================
# F. get_fields_by_dimension()
# ===========================================================================


class TestGetFieldsByDimension:
    def test_F1_returns_only_matching_dimension(self):
        fields = get_fields_by_dimension(SubjectContractDimension.CONTINUITY)
        for f in fields:
            assert f.dimension == SubjectContractDimension.CONTINUITY

    def test_F2_returns_non_empty_for_known_dimension(self):
        assert get_fields_by_dimension(SubjectContractDimension.SUBJECT_IDENTITY)

    def test_F3_participant_lifecycle_dimension_non_empty(self):
        assert get_fields_by_dimension(SubjectContractDimension.PARTICIPANT_LIFECYCLE)


# ===========================================================================
# G. get_fields_by_label()
# ===========================================================================


class TestGetFieldsByLabel:
    def test_G1_returns_only_matching_label(self):
        fields = get_fields_by_label(ContractFieldLabel.CANONICAL)
        for f in fields:
            assert f.label == ContractFieldLabel.CANONICAL

    def test_G2_evidence_only_fields_present(self):
        fields = get_fields_by_label(ContractFieldLabel.EVIDENCE_ONLY)
        assert fields, "No evidence_only fields found"

    def test_G3_compat_fields_present(self):
        fields = get_fields_by_label(ContractFieldLabel.COMPAT)
        assert fields, "No compat fields found"


# ===========================================================================
# H. get_field()
# ===========================================================================


class TestGetField:
    def test_H1_known_field_found(self):
        f = get_field("device_id")
        assert f is not None
        assert f.name == "device_id"

    def test_H2_unknown_field_returns_none(self):
        assert get_field("__nonexistent_field__") is None

    def test_H3_canonical_closure_is_canonical(self):
        f = get_field("canonical_closure")
        assert f is not None
        assert f.label == ContractFieldLabel.CANONICAL

    def test_H4_local_continuity_is_evidence_only(self):
        f = get_field("local_continuity_handling")
        assert f is not None
        assert f.label == ContractFieldLabel.EVIDENCE_ONLY


# ===========================================================================
# I–K. Participant lifecycle enums
# ===========================================================================


class TestParticipantEnums:
    def test_I1_all_lifecycle_states_defined(self):
        required = {
            "unregistered",
            "attaching",
            "attached",
            "dispatched",
            "executing",
            "waiting_result",
            "result_accepted",
            "suspended_state",
            "takeover_candidate_state",
            "taking_over",
            "degraded_state",
            "recovering",
            "detached",
            "terminal",
        }
        actual = {s.value for s in ParticipantLifecycleState}
        missing = required - actual
        assert not missing, f"Missing lifecycle states: {missing}"

    def test_J1_all_roles_defined(self):
        required = {
            "primary",
            "assistant",
            "fallback",
            "suspended",
            "takeover_candidate",
            "degraded",
        }
        actual = {r.value for r in ParticipantRole}
        missing = required - actual
        assert not missing, f"Missing roles: {missing}"

    def test_K1_required_triggers_defined(self):
        required = {
            "attach_success",
            "attach_failure",
            "dispatch_issued",
            "execution_started",
            "execution_completed",
            "result_accepted_by_center",
            "suspension_ordered",
            "takeover_candidate_nominated",
            "transport_disconnected",
            "reconnect_succeeded",
            "recovery_initiated",
            "recovery_completed",
            "terminal_loss",
            "task_closure",
        }
        actual = {t.value for t in ParticipantTransitionTrigger}
        missing = required - actual
        assert not missing, f"Missing triggers: {missing}"


# ===========================================================================
# L. PARTICIPANT_STATE_TRANSITIONS table
# ===========================================================================


class TestTransitionsTable:
    def test_L1_table_non_empty(self):
        assert PARTICIPANT_STATE_TRANSITIONS

    def test_L2_all_entries_have_from_to_trigger(self):
        for t in PARTICIPANT_STATE_TRANSITIONS:
            assert isinstance(t.from_state, ParticipantLifecycleState)
            assert isinstance(t.to_state, ParticipantLifecycleState)
            assert isinstance(t.trigger, ParticipantTransitionTrigger)

    def test_L3_to_dict_has_required_keys(self):
        t = PARTICIPANT_STATE_TRANSITIONS[0]
        d = t.to_dict()
        assert "from_state" in d
        assert "to_state" in d
        assert "trigger" in d

    def test_L4_attach_path_present(self):
        """UNREGISTERED → ATTACHING → ATTACHED path must exist."""
        triggers = {
            (t.from_state, t.to_state): t.trigger
            for t in PARTICIPANT_STATE_TRANSITIONS
        }
        assert (
            ParticipantLifecycleState.UNREGISTERED,
            ParticipantLifecycleState.ATTACHING,
        ) in triggers
        assert (
            ParticipantLifecycleState.ATTACHING,
            ParticipantLifecycleState.ATTACHED,
        ) in triggers

    def test_L5_terminal_path_present(self):
        """result_accepted → terminal must exist."""
        terminal_from_accepted = any(
            t.from_state == ParticipantLifecycleState.RESULT_ACCEPTED
            and t.to_state == ParticipantLifecycleState.TERMINAL
            for t in PARTICIPANT_STATE_TRANSITIONS
        )
        assert terminal_from_accepted


# ===========================================================================
# M. get_allowed_transitions()
# ===========================================================================


class TestGetAllowedTransitions:
    def test_M1_attached_has_dispatch_transition(self):
        transitions = get_allowed_transitions(ParticipantLifecycleState.ATTACHED)
        triggers = {t.trigger for t in transitions}
        assert ParticipantTransitionTrigger.DISPATCH_ISSUED in triggers

    def test_M2_unregistered_has_attach_transition(self):
        transitions = get_allowed_transitions(ParticipantLifecycleState.UNREGISTERED)
        assert transitions

    def test_M3_terminal_has_no_outgoing_transitions(self):
        transitions = get_allowed_transitions(ParticipantLifecycleState.TERMINAL)
        assert not transitions, "Terminal state must have no outgoing transitions"


# ===========================================================================
# N. ParticipantRecord.apply_transition() — allowed path
# ===========================================================================


class TestParticipantRecordTransitions:
    def _make_unregistered(self) -> ParticipantRecord:
        return build_participant_record("p1", "device_android_01")

    def test_N1_unregistered_to_attaching(self):
        r = self._make_unregistered()
        r2 = r.apply_transition(ParticipantTransitionTrigger.ATTACH_SUCCESS)
        assert r2.state == ParticipantLifecycleState.ATTACHING
        assert r2.last_transition_trigger == ParticipantTransitionTrigger.ATTACH_SUCCESS

    def test_N2_attaching_to_attached(self):
        r = self._make_unregistered()
        r2 = r.apply_transition(ParticipantTransitionTrigger.ATTACH_SUCCESS)
        r3 = r2.apply_transition(ParticipantTransitionTrigger.ATTACH_SUCCESS)
        assert r3.state == ParticipantLifecycleState.ATTACHED

    def test_N3_attached_to_dispatched(self):
        r = build_participant_record(
            "p1", "d1", state=ParticipantLifecycleState.ATTACHED
        )
        r2 = r.apply_transition(ParticipantTransitionTrigger.DISPATCH_ISSUED)
        assert r2.state == ParticipantLifecycleState.DISPATCHED

    def test_N4_executing_to_waiting_result(self):
        r = build_participant_record(
            "p1", "d1", state=ParticipantLifecycleState.EXECUTING
        )
        r2 = r.apply_transition(ParticipantTransitionTrigger.EXECUTION_COMPLETED)
        assert r2.state == ParticipantLifecycleState.WAITING_RESULT

    def test_N5_original_record_not_mutated(self):
        r = build_participant_record(
            "p1", "d1", state=ParticipantLifecycleState.ATTACHED
        )
        original_state = r.state
        r.apply_transition(ParticipantTransitionTrigger.DISPATCH_ISSUED)
        assert r.state == original_state, "apply_transition must not mutate the original"

    def test_N6_detached_to_attached_on_reconnect(self):
        r = build_participant_record(
            "p1", "d1", state=ParticipantLifecycleState.DETACHED
        )
        r2 = r.apply_transition(ParticipantTransitionTrigger.RECONNECT_SUCCEEDED)
        assert r2.state == ParticipantLifecycleState.ATTACHED


# ===========================================================================
# O. ParticipantRecord.apply_transition() — disallowed path
# ===========================================================================


class TestParticipantRecordDisallowedTransitions:
    def test_O1_unregistered_cannot_dispatch(self):
        r = build_participant_record("p1", "d1")
        with pytest.raises(ValueError):
            r.apply_transition(ParticipantTransitionTrigger.DISPATCH_ISSUED)

    def test_O2_terminal_cannot_transition(self):
        r = build_participant_record(
            "p1", "d1", state=ParticipantLifecycleState.TERMINAL
        )
        with pytest.raises(ValueError):
            r.apply_transition(ParticipantTransitionTrigger.ATTACH_SUCCESS)

    def test_O3_executing_cannot_directly_reach_result_accepted(self):
        """executing → result_accepted is not a direct transition."""
        r = build_participant_record(
            "p1", "d1", state=ParticipantLifecycleState.EXECUTING
        )
        with pytest.raises(ValueError):
            r.apply_transition(ParticipantTransitionTrigger.RESULT_ACCEPTED_BY_CENTER)


# ===========================================================================
# P. build_participant_record()
# ===========================================================================


class TestBuildParticipantRecord:
    def test_P1_defaults_are_sensible(self):
        r = build_participant_record("p2", "d2")
        assert r.participant_id == "p2"
        assert r.device_id == "d2"
        assert r.role == ParticipantRole.PRIMARY
        assert r.state == ParticipantLifecycleState.UNREGISTERED
        assert r.runtime_attachment_session_id is None

    def test_P2_custom_role_and_state(self):
        r = build_participant_record(
            "p3", "d3",
            role=ParticipantRole.FALLBACK,
            state=ParticipantLifecycleState.ATTACHED,
        )
        assert r.role == ParticipantRole.FALLBACK
        assert r.state == ParticipantLifecycleState.ATTACHED


# ===========================================================================
# Q. ParticipantRecord serialisation
# ===========================================================================


class TestParticipantRecordSerialisation:
    def test_Q1_to_dict_has_required_keys(self):
        r = build_participant_record("p1", "d1")
        d = r.to_dict()
        for key in (
            "participant_id",
            "device_id",
            "role",
            "state",
            "runtime_attachment_session_id",
            "last_transition_trigger",
            "last_updated",
            "diagnostics_visible",
            "metadata",
        ):
            assert key in d, f"Missing key: {key}"

    def test_Q2_to_json_round_trip(self):
        r = build_participant_record("p1", "d1")
        serialised = r.to_json()
        recovered = json.loads(serialised)
        assert recovered["participant_id"] == "p1"
        assert recovered["role"] == "primary"
        assert recovered["state"] == "unregistered"


# ===========================================================================
# R. build_lifecycle_schema_manifest()
# ===========================================================================


class TestLifecycleSchemaManifest:
    def test_R1_manifest_has_required_keys(self):
        m = build_lifecycle_schema_manifest()
        assert "sentinel" in m
        assert "policies" in m
        assert "roles" in m
        assert "states" in m
        assert "triggers" in m
        assert "transitions" in m

    def test_R2_json_round_trip(self):
        m = build_lifecycle_schema_manifest()
        serialised = json.dumps(m)
        recovered = json.loads(serialised)
        assert "roles" in recovered
        assert "transitions" in recovered

    def test_R3_roles_match_enum(self):
        m = build_lifecycle_schema_manifest()
        assert set(m["roles"]) == {r.value for r in ParticipantRole}

    def test_R4_states_match_enum(self):
        m = build_lifecycle_schema_manifest()
        assert set(m["states"]) == {s.value for s in ParticipantLifecycleState}

    def test_R5_triggers_match_enum(self):
        m = build_lifecycle_schema_manifest()
        assert set(m["triggers"]) == {t.value for t in ParticipantTransitionTrigger}

    def test_R6_transitions_count_matches_table(self):
        m = build_lifecycle_schema_manifest()
        assert len(m["transitions"]) == len(PARTICIPANT_STATE_TRANSITIONS)


# ===========================================================================
# S. contracts/__init__.py re-exports
# ===========================================================================


class TestContractsInitReexports:
    def test_S1_distributed_subject_contract_symbols(self):
        import contracts

        for sym in (
            "DISTRIBUTED_SUBJECT_CONTRACT_V1_SENTINEL",
            "PARTICIPANT_LIFECYCLE_IS_GOVERNED_BY_CENTER",
            "SUBJECT_EVIDENCE_IS_NOT_CANONICAL_TRUTH",
            "CONTRACT_FIELD_LABEL_IS_EXPLICIT_POLICY",
            "ContractFieldLabel",
            "SubjectContractDimension",
            "SubjectContractField",
            "DISTRIBUTED_SUBJECT_CONTRACT_V1_FIELDS",
            "DistributedSubjectContractVersion",
            "get_fields_by_dimension",
            "get_fields_by_label",
            "get_field",
            "build_contract_version",
            "build_contract_manifest",
        ):
            assert hasattr(contracts, sym), f"contracts missing {sym!r}"

    def test_S2_participant_lifecycle_schema_symbols(self):
        import contracts

        for sym in (
            "PARTICIPANT_LIFECYCLE_SCHEMA_SENTINEL",
            "PARTICIPANT_ROLE_IS_ASSIGNED_BY_CENTER",
            "PARTICIPANT_STATE_TRANSITIONS_ARE_AUTHORITATIVE",
            "ParticipantRole",
            "ParticipantLifecycleState",
            "ParticipantTransitionTrigger",
            "ParticipantStateTransition",
            "PARTICIPANT_STATE_TRANSITIONS",
            "ParticipantRecord",
            "build_participant_record",
            "get_allowed_transitions",
            "build_lifecycle_schema_manifest",
        ):
            assert hasattr(contracts, sym), f"contracts missing {sym!r}"


# ===========================================================================
# T. Sentinel constants
# ===========================================================================


class TestSentinelConstants:
    def test_T1_distributed_subject_sentinel_non_empty(self):
        assert DISTRIBUTED_SUBJECT_CONTRACT_V1_SENTINEL, "Sentinel must be non-empty"
        assert "contracts" in DISTRIBUTED_SUBJECT_CONTRACT_V1_SENTINEL, (
            "Sentinel must reference the contracts module path"
        )

    def test_T2_lifecycle_governed_by_center_sentinel(self):
        assert PARTICIPANT_LIFECYCLE_IS_GOVERNED_BY_CENTER, "Sentinel must be non-empty"
        assert "canonical" in PARTICIPANT_LIFECYCLE_IS_GOVERNED_BY_CENTER, (
            "Sentinel must reference canonical governance"
        )

    def test_T3_evidence_not_canonical_truth_sentinel(self):
        assert SUBJECT_EVIDENCE_IS_NOT_CANONICAL_TRUTH

    def test_T4_field_label_policy_sentinel(self):
        assert CONTRACT_FIELD_LABEL_IS_EXPLICIT_POLICY

    def test_T5_lifecycle_schema_sentinel(self):
        assert PARTICIPANT_LIFECYCLE_SCHEMA_SENTINEL

    def test_T6_role_assigned_by_center_sentinel(self):
        assert PARTICIPANT_ROLE_IS_ASSIGNED_BY_CENTER

    def test_T7_state_transitions_authoritative_sentinel(self):
        assert PARTICIPANT_STATE_TRANSITIONS_ARE_AUTHORITATIVE


# ===========================================================================
# U. Key fields must not drift from canonical / evidence_only labels
# ===========================================================================


class TestKeyFieldLabelsStable:
    """These fields carry critical boundary semantics; their labels must not
    drift silently.  Any intentional label change must be accompanied by a
    deliberate update to this test."""

    def test_U1_canonical_closure_is_canonical(self):
        f = get_field("canonical_closure")
        assert f is not None
        assert f.label == ContractFieldLabel.CANONICAL

    def test_U2_local_execution_result_is_evidence_only(self):
        f = get_field("local_execution_result")
        assert f is not None
        assert f.label == ContractFieldLabel.EVIDENCE_ONLY

    def test_U3_cross_device_continuity_legality_is_canonical(self):
        f = get_field("cross_device_continuity_legality")
        assert f is not None
        assert f.label == ContractFieldLabel.CANONICAL

    def test_U4_local_continuity_handling_is_evidence_only(self):
        f = get_field("local_continuity_handling")
        assert f is not None
        assert f.label == ContractFieldLabel.EVIDENCE_ONLY

    def test_U5_participant_truth_uplink_required_is_canonical(self):
        f = get_field("participant_truth_uplink_required")
        assert f is not None
        assert f.label == ContractFieldLabel.CANONICAL

    def test_U6_android_reported_mode_is_evidence_only(self):
        f = get_field("android_reported_mode")
        assert f is not None
        assert f.label == ContractFieldLabel.EVIDENCE_ONLY

    def test_U7_runtime_attachment_session_id_absent_fallback_is_compat(self):
        f = get_field("runtime_attachment_session_id_absent_fallback")
        assert f is not None
        assert f.label == ContractFieldLabel.COMPAT

    def test_U8_device_id_is_canonical(self):
        f = get_field("device_id")
        assert f is not None
        assert f.label == ContractFieldLabel.CANONICAL

    def test_U9_offline_task_queue_is_evidence_only(self):
        f = get_field("offline_task_queue")
        assert f is not None
        assert f.label == ContractFieldLabel.EVIDENCE_ONLY
