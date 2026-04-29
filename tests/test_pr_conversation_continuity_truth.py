"""tests/test_pr_conversation_continuity_truth.py
==================================================
PR-12: Automated tests for conversation continuity truth formalization.

Coverage:

  Policy sentinels
  1.  CONVERSATION_CONTINUITY_TRUTH_AUTHORITY is a non-empty string.
  2.  CONVERSATION_CONTINUITY_TRUTH_PR12_SENTINEL contains 'PR-12'.
  3.  HISTORY_VISIBLE_IS_NOT_CONTINUITY_RESTORED_POLICY is non-empty.
  4.  STATE_RESTORED_IS_NOT_CONVERSATION_CONTINUITY_POLICY is non-empty.
  5.  TASK_CONTINUITY_IS_NOT_CONVERSATION_CONTINUITY_POLICY is non-empty.
  6.  AUTHORITATIVE_CONTINUITY_REQUIRES_REBIND_AND_SESSION_POLICY is non-empty.
  7.  PARTIAL_RECOVERY_MUST_DOWNGRADE_CONTINUITY_POLICY is non-empty.
  8.  PROCESS_DEATH_REQUIRES_EXPLICIT_REBIND_POLICY is non-empty.
  9.  EVIDENCE_ABSENT_MUST_NOT_BE_OPTIMISTIC_POLICY is non-empty.

  ConversationContinuityClass — enum values
  10. All five expected values are present.
  11. authoritative_continuity_restored is a str enum member.
  12. partial_continuity is a str enum member.
  13. history_only_restored is a str enum member.
  14. state_restored_rebind_required is a str enum member.
  15. continuity_lost is a str enum member.

  ConversationContinuityClass — rank ordering
  16. authoritative_continuity_restored has the highest rank.
  17. continuity_lost has rank 0.
  18. state_restored_rebind_required rank > continuity_lost rank.
  19. partial_continuity rank > history_only_restored rank.
  20. authoritative_continuity_restored.is_authoritative is True.
  21. All other classes is_authoritative is False.
  22. state_restored_rebind_required.requires_rebind is True.
  23. continuity_lost.requires_rebind is True.
  24. authoritative_continuity_restored.requires_rebind is False.
  25. continuity_lost.is_terminal_loss is True.
  26. authoritative_continuity_restored.is_terminal_loss is False.
  27. from_string with unknown value returns continuity_lost.
  28. from_string with valid value returns correct member.

  ConversationContinuityEvidence — construction and to_dict
  29. Default construction yields all-False booleans.
  30. to_dict() keys match expected set.
  31. from_dict() round-trips session_confirmed.
  32. from_dict() round-trips history_visible.
  33. from_dict() round-trips state_present.
  34. from_dict() round-trips rebind_completed.
  35. from_dict() round-trips task_continuity_ok.
  36. from_dict() round-trips process_death_observed.
  37. from_dict() round-trips partial_recovery_only.
  38. from_dict() round-trips conversation_session_id.
  39. from_dict() defaults session_confirmed to False when absent.

  ConversationContinuityVerdict — construction and to_dict
  40. Default continuity_class is continuity_lost.
  41. to_dict() includes 'continuity_class'.
  42. to_dict() includes 'is_authoritative'.
  43. to_dict() includes 'requires_rebind'.
  44. to_dict() includes 'policy_references'.
  45. from_dict() round-trips continuity_class.
  46. from_dict() round-trips reason.
  47. from_dict() unknown continuity_class falls back to continuity_lost.
  48. is_authoritative property reflects continuity_class.
  49. requires_rebind property reflects continuity_class.

  ConversationContinuityContract — authoritative_continuity_restored
  50. All four evidence dimensions + no downgrade flags → authoritative.
  51. task_continuity_ok does not affect authoritative verdict when all required present.
  52. Missing session_confirmed prevents authoritative verdict.
  53. Missing rebind_completed prevents authoritative verdict.
  54. Missing history_visible prevents authoritative verdict.
  55. Missing state_present prevents authoritative verdict.

  ConversationContinuityContract — process_death downgrade
  56. All four required dims + process_death_observed → partial_continuity (not authoritative).
  57. process_death + state_present only → state_restored_rebind_required.
  58. process_death + history only → history_only_restored.
  59. process_death + no evidence → continuity_lost.
  60. process_death verdict reason mentions 'process_death_observed'.

  ConversationContinuityContract — partial_recovery_only downgrade
  61. All four required dims + partial_recovery_only → partial_continuity (not authoritative).
  62. partial_recovery_only + history + state → partial_continuity.

  ConversationContinuityContract — partial_continuity class
  63. history_visible + state_present + session_confirmed → partial_continuity.
  64. history_visible + state_present + rebind_completed → partial_continuity.
  65. history_visible + state_present + task_continuity_ok → partial_continuity.
  66. history_visible + state_present + no supporting dim → does NOT yield partial_continuity.

  ConversationContinuityContract — history_only_restored class
  67. history_visible alone → history_only_restored.
  68. history_visible + task_continuity_ok (no state, no rebind) → history_only_restored.
  69. history_only_restored verdict reason mentions 'history_visible'.
  70. history_only_restored policy references include HISTORY_VISIBLE_IS_NOT_CONTINUITY_RESTORED_POLICY.

  ConversationContinuityContract — state_restored_rebind_required class
  71. state_present alone → state_restored_rebind_required.
  72. state_present + task_continuity_ok → state_restored_rebind_required (no rebind).
  73. state_present + history_visible + no rebind + no session → state_restored_rebind_required (no supporting dim).
  74. state_restored_rebind_required reason mentions 'rebind_completed'.
  75. state_restored_rebind_required policy references include STATE_RESTORED_IS_NOT_CONVERSATION_CONTINUITY_POLICY.

  ConversationContinuityContract — continuity_lost class
  76. No evidence → continuity_lost.
  77. task_continuity_ok alone → continuity_lost.
  78. continuity_lost reason mentions 'Absent dimensions'.
  79. continuity_lost policy references include EVIDENCE_ABSENT_MUST_NOT_BE_OPTIMISTIC_POLICY.

  Critical invariants (crash / restart anti-regression)
  80. After restart, history-only restore MUST NOT produce authoritative_continuity_restored.
  81. After restart, state-only restore MUST NOT produce authoritative_continuity_restored.
  82. Task continuity alone MUST NOT produce authoritative_continuity_restored.
  83. rebind_completed=False MUST prevent authoritative_continuity_restored regardless of other dims.
  84. session_confirmed=False MUST prevent authoritative_continuity_restored regardless of other dims.
  85. Absent evidence MUST NOT be promoted above continuity_lost.
  86. partial_continuity MUST NOT be re-upgraded to authoritative by downstream consumers.

  build_conversation_continuity_verdict convenience function
  87. Returns a ConversationContinuityVerdict.
  88. No-evidence input → continuity_lost.
  89. Full evidence input → authoritative_continuity_restored.
  90. Verdict id starts with 'ccv_'.

  ConversationContinuityVerdict — durable round-trip
  91. to_dict() / from_dict() round-trips continuity_class enum value.
  92. to_dict() / from_dict() round-trips policy_references list.
  93. to_dict() / from_dict() round-trips session_confirmed.
  94. to_dict() / from_dict() preserves generated_at timestamp.

  AcceptanceDimensionId integration
  95. AcceptanceDimensionId has conversation_continuity member.
  96. all_dimensions() includes conversation_continuity.
  97. all_dimensions() returns nine dimensions.
  98. from_string('conversation_continuity') returns correct member.

  SystemFinalAcceptanceEvaluator integration
  99. evaluate() checklist contains conversation_continuity dimension key.
  100. Baseline probe does NOT produce authoritative_continuity_restored in acceptance report.
"""

from __future__ import annotations

import pytest

from core.conversation_continuity_truth import (
    CONVERSATION_CONTINUITY_TRUTH_AUTHORITY,
    CONVERSATION_CONTINUITY_TRUTH_PR12_SENTINEL,
    HISTORY_VISIBLE_IS_NOT_CONTINUITY_RESTORED_POLICY,
    STATE_RESTORED_IS_NOT_CONVERSATION_CONTINUITY_POLICY,
    TASK_CONTINUITY_IS_NOT_CONVERSATION_CONTINUITY_POLICY,
    AUTHORITATIVE_CONTINUITY_REQUIRES_REBIND_AND_SESSION_POLICY,
    PARTIAL_RECOVERY_MUST_DOWNGRADE_CONTINUITY_POLICY,
    PROCESS_DEATH_REQUIRES_EXPLICIT_REBIND_POLICY,
    EVIDENCE_ABSENT_MUST_NOT_BE_OPTIMISTIC_POLICY,
    ConversationContinuityClass,
    ConversationContinuityEvidence,
    ConversationContinuityVerdict,
    ConversationContinuityContract,
    build_conversation_continuity_verdict,
)
from core.system_final_acceptance_verdict import AcceptanceDimensionId


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _full_evidence(**overrides) -> ConversationContinuityEvidence:
    """Return evidence with all four required dims True unless overridden."""
    defaults = dict(
        session_confirmed=True,
        history_visible=True,
        state_present=True,
        rebind_completed=True,
        task_continuity_ok=False,
        process_death_observed=False,
        partial_recovery_only=False,
    )
    defaults.update(overrides)
    return ConversationContinuityEvidence(**defaults)


def _no_evidence(**overrides) -> ConversationContinuityEvidence:
    """Return evidence with all dims False unless overridden."""
    defaults = dict(
        session_confirmed=False,
        history_visible=False,
        state_present=False,
        rebind_completed=False,
        task_continuity_ok=False,
        process_death_observed=False,
        partial_recovery_only=False,
    )
    defaults.update(overrides)
    return ConversationContinuityEvidence(**defaults)


def _evaluate(evidence: ConversationContinuityEvidence) -> ConversationContinuityVerdict:
    return ConversationContinuityContract().evaluate(evidence)


# ---------------------------------------------------------------------------
# 1-9: Policy sentinels
# ---------------------------------------------------------------------------

def test_1_authority_sentinel_non_empty():
    assert isinstance(CONVERSATION_CONTINUITY_TRUTH_AUTHORITY, str)
    assert len(CONVERSATION_CONTINUITY_TRUTH_AUTHORITY) > 0


def test_2_pr12_sentinel_contains_pr12():
    assert "PR-12" in CONVERSATION_CONTINUITY_TRUTH_PR12_SENTINEL


def test_3_history_visible_policy_non_empty():
    assert len(HISTORY_VISIBLE_IS_NOT_CONTINUITY_RESTORED_POLICY) > 0


def test_4_state_restored_policy_non_empty():
    assert len(STATE_RESTORED_IS_NOT_CONVERSATION_CONTINUITY_POLICY) > 0


def test_5_task_continuity_policy_non_empty():
    assert len(TASK_CONTINUITY_IS_NOT_CONVERSATION_CONTINUITY_POLICY) > 0


def test_6_authoritative_requires_rebind_policy_non_empty():
    assert len(AUTHORITATIVE_CONTINUITY_REQUIRES_REBIND_AND_SESSION_POLICY) > 0


def test_7_partial_recovery_downgrade_policy_non_empty():
    assert len(PARTIAL_RECOVERY_MUST_DOWNGRADE_CONTINUITY_POLICY) > 0


def test_8_process_death_rebind_policy_non_empty():
    assert len(PROCESS_DEATH_REQUIRES_EXPLICIT_REBIND_POLICY) > 0


def test_9_evidence_absent_policy_non_empty():
    assert len(EVIDENCE_ABSENT_MUST_NOT_BE_OPTIMISTIC_POLICY) > 0


# ---------------------------------------------------------------------------
# 10-15: ConversationContinuityClass enum values
# ---------------------------------------------------------------------------

def test_10_all_five_values_present():
    expected = {
        "authoritative_continuity_restored",
        "partial_continuity",
        "history_only_restored",
        "state_restored_rebind_required",
        "continuity_lost",
    }
    actual = {m.value for m in ConversationContinuityClass}
    assert expected == actual


def test_11_authoritative_continuity_restored_is_str():
    assert isinstance(ConversationContinuityClass.authoritative_continuity_restored, str)


def test_12_partial_continuity_is_str():
    assert isinstance(ConversationContinuityClass.partial_continuity, str)


def test_13_history_only_restored_is_str():
    assert isinstance(ConversationContinuityClass.history_only_restored, str)


def test_14_state_restored_rebind_required_is_str():
    assert isinstance(ConversationContinuityClass.state_restored_rebind_required, str)


def test_15_continuity_lost_is_str():
    assert isinstance(ConversationContinuityClass.continuity_lost, str)


# ---------------------------------------------------------------------------
# 16-28: ConversationContinuityClass rank ordering
# ---------------------------------------------------------------------------

def test_16_authoritative_has_highest_rank():
    auth = ConversationContinuityClass.authoritative_continuity_restored
    for other in ConversationContinuityClass:
        if other != auth:
            assert auth.rank > other.rank


def test_17_continuity_lost_has_rank_0():
    assert ConversationContinuityClass.continuity_lost.rank == 0


def test_18_state_restored_rank_gt_continuity_lost():
    assert (
        ConversationContinuityClass.state_restored_rebind_required.rank
        > ConversationContinuityClass.continuity_lost.rank
    )


def test_19_partial_continuity_rank_gt_history_only():
    assert (
        ConversationContinuityClass.partial_continuity.rank
        > ConversationContinuityClass.history_only_restored.rank
    )


def test_20_authoritative_is_authoritative_true():
    assert ConversationContinuityClass.authoritative_continuity_restored.is_authoritative is True


def test_21_other_classes_not_authoritative():
    for cls in ConversationContinuityClass:
        if cls != ConversationContinuityClass.authoritative_continuity_restored:
            assert cls.is_authoritative is False


def test_22_state_restored_requires_rebind():
    assert ConversationContinuityClass.state_restored_rebind_required.requires_rebind is True


def test_23_continuity_lost_requires_rebind():
    assert ConversationContinuityClass.continuity_lost.requires_rebind is True


def test_24_authoritative_does_not_require_rebind():
    assert ConversationContinuityClass.authoritative_continuity_restored.requires_rebind is False


def test_25_continuity_lost_is_terminal():
    assert ConversationContinuityClass.continuity_lost.is_terminal_loss is True


def test_26_authoritative_is_not_terminal():
    assert ConversationContinuityClass.authoritative_continuity_restored.is_terminal_loss is False


def test_27_from_string_unknown_returns_continuity_lost():
    assert ConversationContinuityClass.from_string("not_a_real_value") == ConversationContinuityClass.continuity_lost


def test_28_from_string_valid_returns_correct():
    assert (
        ConversationContinuityClass.from_string("partial_continuity")
        == ConversationContinuityClass.partial_continuity
    )


# ---------------------------------------------------------------------------
# 29-39: ConversationContinuityEvidence
# ---------------------------------------------------------------------------

def test_29_default_evidence_all_false():
    e = ConversationContinuityEvidence()
    assert e.session_confirmed is False
    assert e.history_visible is False
    assert e.state_present is False
    assert e.rebind_completed is False
    assert e.task_continuity_ok is False
    assert e.process_death_observed is False
    assert e.partial_recovery_only is False


def test_30_to_dict_has_expected_keys():
    e = ConversationContinuityEvidence()
    d = e.to_dict()
    expected_keys = {
        "session_confirmed",
        "history_visible",
        "state_present",
        "rebind_completed",
        "task_continuity_ok",
        "process_death_observed",
        "partial_recovery_only",
        "conversation_session_id",
        "evaluated_context",
    }
    assert expected_keys == set(d.keys())


def test_31_from_dict_session_confirmed():
    e = ConversationContinuityEvidence.from_dict({"session_confirmed": True})
    assert e.session_confirmed is True


def test_32_from_dict_history_visible():
    e = ConversationContinuityEvidence.from_dict({"history_visible": True})
    assert e.history_visible is True


def test_33_from_dict_state_present():
    e = ConversationContinuityEvidence.from_dict({"state_present": True})
    assert e.state_present is True


def test_34_from_dict_rebind_completed():
    e = ConversationContinuityEvidence.from_dict({"rebind_completed": True})
    assert e.rebind_completed is True


def test_35_from_dict_task_continuity_ok():
    e = ConversationContinuityEvidence.from_dict({"task_continuity_ok": True})
    assert e.task_continuity_ok is True


def test_36_from_dict_process_death_observed():
    e = ConversationContinuityEvidence.from_dict({"process_death_observed": True})
    assert e.process_death_observed is True


def test_37_from_dict_partial_recovery_only():
    e = ConversationContinuityEvidence.from_dict({"partial_recovery_only": True})
    assert e.partial_recovery_only is True


def test_38_from_dict_conversation_session_id():
    e = ConversationContinuityEvidence.from_dict({"conversation_session_id": "sess-abc"})
    assert e.conversation_session_id == "sess-abc"


def test_39_from_dict_defaults_session_confirmed_false():
    e = ConversationContinuityEvidence.from_dict({})
    assert e.session_confirmed is False


# ---------------------------------------------------------------------------
# 40-49: ConversationContinuityVerdict
# ---------------------------------------------------------------------------

def test_40_default_class_is_continuity_lost():
    v = ConversationContinuityVerdict()
    assert v.continuity_class == ConversationContinuityClass.continuity_lost


def test_41_to_dict_includes_continuity_class():
    v = ConversationContinuityVerdict()
    assert "continuity_class" in v.to_dict()


def test_42_to_dict_includes_is_authoritative():
    v = ConversationContinuityVerdict()
    assert "is_authoritative" in v.to_dict()


def test_43_to_dict_includes_requires_rebind():
    v = ConversationContinuityVerdict()
    assert "requires_rebind" in v.to_dict()


def test_44_to_dict_includes_policy_references():
    v = ConversationContinuityVerdict()
    assert "policy_references" in v.to_dict()


def test_45_from_dict_round_trips_continuity_class():
    v = ConversationContinuityVerdict(
        continuity_class=ConversationContinuityClass.partial_continuity
    )
    v2 = ConversationContinuityVerdict.from_dict(v.to_dict())
    assert v2.continuity_class == ConversationContinuityClass.partial_continuity


def test_46_from_dict_round_trips_reason():
    v = ConversationContinuityVerdict(reason="test reason")
    v2 = ConversationContinuityVerdict.from_dict(v.to_dict())
    assert v2.reason == "test reason"


def test_47_from_dict_unknown_class_falls_back_to_continuity_lost():
    v = ConversationContinuityVerdict.from_dict({"continuity_class": "totally_made_up"})
    assert v.continuity_class == ConversationContinuityClass.continuity_lost


def test_48_is_authoritative_property():
    v = ConversationContinuityVerdict(
        continuity_class=ConversationContinuityClass.authoritative_continuity_restored
    )
    assert v.is_authoritative is True
    v2 = ConversationContinuityVerdict(
        continuity_class=ConversationContinuityClass.partial_continuity
    )
    assert v2.is_authoritative is False


def test_49_requires_rebind_property():
    v = ConversationContinuityVerdict(
        continuity_class=ConversationContinuityClass.state_restored_rebind_required
    )
    assert v.requires_rebind is True


# ---------------------------------------------------------------------------
# 50-55: ConversationContinuityContract — authoritative_continuity_restored
# ---------------------------------------------------------------------------

def test_50_all_required_dims_yields_authoritative():
    v = _evaluate(_full_evidence())
    assert v.continuity_class == ConversationContinuityClass.authoritative_continuity_restored


def test_51_task_continuity_ok_does_not_block_authoritative():
    v = _evaluate(_full_evidence(task_continuity_ok=True))
    assert v.continuity_class == ConversationContinuityClass.authoritative_continuity_restored


def test_52_missing_session_confirmed_prevents_authoritative():
    v = _evaluate(_full_evidence(session_confirmed=False))
    assert v.continuity_class != ConversationContinuityClass.authoritative_continuity_restored


def test_53_missing_rebind_completed_prevents_authoritative():
    v = _evaluate(_full_evidence(rebind_completed=False))
    assert v.continuity_class != ConversationContinuityClass.authoritative_continuity_restored


def test_54_missing_history_visible_prevents_authoritative():
    v = _evaluate(_full_evidence(history_visible=False))
    assert v.continuity_class != ConversationContinuityClass.authoritative_continuity_restored


def test_55_missing_state_present_prevents_authoritative():
    v = _evaluate(_full_evidence(state_present=False))
    assert v.continuity_class != ConversationContinuityClass.authoritative_continuity_restored


# ---------------------------------------------------------------------------
# 56-60: ConversationContinuityContract — process_death downgrade
# ---------------------------------------------------------------------------

def test_56_all_dims_plus_process_death_yields_partial_not_authoritative():
    v = _evaluate(_full_evidence(process_death_observed=True))
    assert v.continuity_class == ConversationContinuityClass.partial_continuity
    assert v.continuity_class != ConversationContinuityClass.authoritative_continuity_restored


def test_57_process_death_state_only_yields_state_restored_rebind_required():
    v = _evaluate(_no_evidence(state_present=True, process_death_observed=True))
    assert v.continuity_class == ConversationContinuityClass.state_restored_rebind_required


def test_58_process_death_history_only_yields_history_only_restored():
    v = _evaluate(_no_evidence(history_visible=True, process_death_observed=True))
    assert v.continuity_class == ConversationContinuityClass.history_only_restored


def test_59_process_death_no_evidence_yields_continuity_lost():
    v = _evaluate(_no_evidence(process_death_observed=True))
    assert v.continuity_class == ConversationContinuityClass.continuity_lost


def test_60_process_death_verdict_reason_mentions_process_death():
    v = _evaluate(_full_evidence(process_death_observed=True))
    assert "process_death_observed" in v.reason


# ---------------------------------------------------------------------------
# 61-62: partial_recovery_only downgrade
# ---------------------------------------------------------------------------

def test_61_all_dims_plus_partial_recovery_only_yields_partial():
    v = _evaluate(_full_evidence(partial_recovery_only=True))
    assert v.continuity_class == ConversationContinuityClass.partial_continuity


def test_62_partial_recovery_history_state_yields_partial():
    v = _evaluate(_no_evidence(
        history_visible=True,
        state_present=True,
        session_confirmed=True,
        partial_recovery_only=True,
    ))
    assert v.continuity_class == ConversationContinuityClass.partial_continuity


# ---------------------------------------------------------------------------
# 63-66: partial_continuity class
# ---------------------------------------------------------------------------

def test_63_history_state_session_yields_partial():
    v = _evaluate(_no_evidence(
        history_visible=True, state_present=True, session_confirmed=True
    ))
    assert v.continuity_class == ConversationContinuityClass.partial_continuity


def test_64_history_state_rebind_yields_partial():
    v = _evaluate(_no_evidence(
        history_visible=True, state_present=True, rebind_completed=True
    ))
    assert v.continuity_class == ConversationContinuityClass.partial_continuity


def test_65_history_state_task_continuity_yields_partial():
    v = _evaluate(_no_evidence(
        history_visible=True, state_present=True, task_continuity_ok=True
    ))
    assert v.continuity_class == ConversationContinuityClass.partial_continuity


def test_66_history_state_no_supporting_dim_does_not_yield_partial():
    # history + state but no session/rebind/task → not partial (no supporting dim)
    v = _evaluate(_no_evidence(history_visible=True, state_present=True))
    assert v.continuity_class != ConversationContinuityClass.partial_continuity


# ---------------------------------------------------------------------------
# 67-70: history_only_restored class
# ---------------------------------------------------------------------------

def test_67_history_visible_alone_yields_history_only():
    v = _evaluate(_no_evidence(history_visible=True))
    assert v.continuity_class == ConversationContinuityClass.history_only_restored


def test_68_history_plus_task_continuity_no_state_yields_history_only():
    v = _evaluate(_no_evidence(history_visible=True, task_continuity_ok=True))
    assert v.continuity_class == ConversationContinuityClass.history_only_restored


def test_69_history_only_reason_mentions_history_visible():
    v = _evaluate(_no_evidence(history_visible=True))
    assert "history_visible" in v.reason


def test_70_history_only_policy_references():
    v = _evaluate(_no_evidence(history_visible=True))
    assert "HISTORY_VISIBLE_IS_NOT_CONTINUITY_RESTORED_POLICY" in v.policy_references


# ---------------------------------------------------------------------------
# 71-75: state_restored_rebind_required class
# ---------------------------------------------------------------------------

def test_71_state_present_alone_yields_state_restored_rebind():
    v = _evaluate(_no_evidence(state_present=True))
    assert v.continuity_class == ConversationContinuityClass.state_restored_rebind_required


def test_72_state_plus_task_continuity_no_rebind_yields_state_restored():
    v = _evaluate(_no_evidence(state_present=True, task_continuity_ok=True))
    assert v.continuity_class == ConversationContinuityClass.state_restored_rebind_required


def test_73_state_history_no_rebind_no_session_no_task_yields_state_restored():
    # history + state but no rebind, no session, no task → state_restored_rebind_required
    # (no supporting dim to reach partial_continuity)
    v = _evaluate(_no_evidence(history_visible=True, state_present=True))
    assert v.continuity_class == ConversationContinuityClass.state_restored_rebind_required


def test_74_state_restored_reason_mentions_rebind():
    v = _evaluate(_no_evidence(state_present=True))
    assert "rebind_completed" in v.reason


def test_75_state_restored_policy_references():
    v = _evaluate(_no_evidence(state_present=True))
    assert "STATE_RESTORED_IS_NOT_CONVERSATION_CONTINUITY_POLICY" in v.policy_references


# ---------------------------------------------------------------------------
# 76-79: continuity_lost class
# ---------------------------------------------------------------------------

def test_76_no_evidence_yields_continuity_lost():
    v = _evaluate(_no_evidence())
    assert v.continuity_class == ConversationContinuityClass.continuity_lost


def test_77_task_continuity_only_yields_continuity_lost():
    v = _evaluate(_no_evidence(task_continuity_ok=True))
    assert v.continuity_class == ConversationContinuityClass.continuity_lost


def test_78_continuity_lost_reason_mentions_absent_dimensions():
    v = _evaluate(_no_evidence())
    assert "Absent dimensions" in v.reason or "absent" in v.reason.lower()


def test_79_continuity_lost_policy_references():
    v = _evaluate(_no_evidence())
    assert "EVIDENCE_ABSENT_MUST_NOT_BE_OPTIMISTIC_POLICY" in v.policy_references


# ---------------------------------------------------------------------------
# 80-86: Critical invariants — crash / restart anti-regression
# ---------------------------------------------------------------------------

def test_80_history_only_restart_must_not_produce_authoritative():
    """After restart, if only history visible: MUST NOT be authoritative."""
    restart_evidence = ConversationContinuityEvidence(
        history_visible=True,
        session_confirmed=False,
        state_present=False,
        rebind_completed=False,
    )
    v = _evaluate(restart_evidence)
    assert v.continuity_class != ConversationContinuityClass.authoritative_continuity_restored
    assert v.continuity_class == ConversationContinuityClass.history_only_restored


def test_81_state_only_restart_must_not_produce_authoritative():
    """After restart, if only state present (no rebind): MUST NOT be authoritative."""
    restart_evidence = ConversationContinuityEvidence(
        state_present=True,
        session_confirmed=False,
        history_visible=False,
        rebind_completed=False,
    )
    v = _evaluate(restart_evidence)
    assert v.continuity_class != ConversationContinuityClass.authoritative_continuity_restored
    assert v.continuity_class == ConversationContinuityClass.state_restored_rebind_required


def test_82_task_continuity_alone_must_not_produce_authoritative():
    """Task continuity alone MUST NOT be sufficient for authoritative conversation continuity."""
    evidence = ConversationContinuityEvidence(task_continuity_ok=True)
    v = _evaluate(evidence)
    assert v.continuity_class != ConversationContinuityClass.authoritative_continuity_restored


def test_83_rebind_false_must_prevent_authoritative():
    """rebind_completed=False MUST prevent authoritative regardless of other dims."""
    for session_conf in (True, False):
        evidence = ConversationContinuityEvidence(
            session_confirmed=session_conf,
            history_visible=True,
            state_present=True,
            rebind_completed=False,
        )
        v = _evaluate(evidence)
        assert v.continuity_class != ConversationContinuityClass.authoritative_continuity_restored


def test_84_session_false_must_prevent_authoritative():
    """session_confirmed=False MUST prevent authoritative regardless of other dims."""
    evidence = ConversationContinuityEvidence(
        session_confirmed=False,
        history_visible=True,
        state_present=True,
        rebind_completed=True,
    )
    v = _evaluate(evidence)
    assert v.continuity_class != ConversationContinuityClass.authoritative_continuity_restored


def test_85_absent_evidence_must_not_exceed_continuity_lost():
    """When no evidence dims are set, the verdict MUST be continuity_lost."""
    v = _evaluate(ConversationContinuityEvidence())
    assert v.continuity_class == ConversationContinuityClass.continuity_lost
    assert not v.is_authoritative


def test_86_partial_continuity_class_is_lower_than_authoritative():
    """partial_continuity rank < authoritative_continuity_restored rank."""
    assert (
        ConversationContinuityClass.partial_continuity.rank
        < ConversationContinuityClass.authoritative_continuity_restored.rank
    )


# ---------------------------------------------------------------------------
# 87-90: build_conversation_continuity_verdict convenience function
# ---------------------------------------------------------------------------

def test_87_returns_verdict_instance():
    v = build_conversation_continuity_verdict(ConversationContinuityEvidence())
    assert isinstance(v, ConversationContinuityVerdict)


def test_88_no_evidence_input_yields_continuity_lost():
    v = build_conversation_continuity_verdict(ConversationContinuityEvidence())
    assert v.continuity_class == ConversationContinuityClass.continuity_lost


def test_89_full_evidence_input_yields_authoritative():
    v = build_conversation_continuity_verdict(_full_evidence())
    assert v.continuity_class == ConversationContinuityClass.authoritative_continuity_restored


def test_90_verdict_id_starts_with_ccv():
    v = build_conversation_continuity_verdict(ConversationContinuityEvidence())
    assert v.verdict_id.startswith("ccv_")


# ---------------------------------------------------------------------------
# 91-94: ConversationContinuityVerdict durable round-trip
# ---------------------------------------------------------------------------

def test_91_round_trip_continuity_class():
    for cls in ConversationContinuityClass:
        v = ConversationContinuityVerdict(continuity_class=cls)
        v2 = ConversationContinuityVerdict.from_dict(v.to_dict())
        assert v2.continuity_class == cls


def test_92_round_trip_policy_references():
    policies = ["POLICY_A", "POLICY_B"]
    v = ConversationContinuityVerdict(policy_references=policies)
    v2 = ConversationContinuityVerdict.from_dict(v.to_dict())
    assert v2.policy_references == policies


def test_93_round_trip_session_confirmed():
    v = ConversationContinuityVerdict(session_confirmed=True)
    v2 = ConversationContinuityVerdict.from_dict(v.to_dict())
    assert v2.session_confirmed is True


def test_94_round_trip_preserves_generated_at():
    import time
    ts = time.time()
    v = ConversationContinuityVerdict(generated_at=ts)
    v2 = ConversationContinuityVerdict.from_dict(v.to_dict())
    assert abs(v2.generated_at - ts) < 0.001


# ---------------------------------------------------------------------------
# 95-98: AcceptanceDimensionId integration
# ---------------------------------------------------------------------------

def test_95_acceptance_dimension_has_conversation_continuity():
    assert hasattr(AcceptanceDimensionId, "conversation_continuity")
    assert AcceptanceDimensionId.conversation_continuity.value == "conversation_continuity"


def test_96_all_dimensions_includes_conversation_continuity():
    dims = AcceptanceDimensionId.all_dimensions()
    assert AcceptanceDimensionId.conversation_continuity in dims


def test_97_all_dimensions_returns_ten():
    assert len(AcceptanceDimensionId.all_dimensions()) == 10


def test_98_from_string_returns_conversation_continuity():
    assert (
        AcceptanceDimensionId.from_string("conversation_continuity")
        == AcceptanceDimensionId.conversation_continuity
    )


# ---------------------------------------------------------------------------
# 99-100: SystemFinalAcceptanceEvaluator integration
# ---------------------------------------------------------------------------

def test_99_evaluator_checklist_contains_conversation_continuity():
    from core.system_final_acceptance_verdict import (
        get_system_acceptance_evaluator,
        reset_system_acceptance_evaluator,
    )
    reset_system_acceptance_evaluator()
    try:
        evaluator = get_system_acceptance_evaluator()
        report = evaluator.evaluate()
        assert "conversation_continuity" in report.checklist
    finally:
        reset_system_acceptance_evaluator()


def test_100_baseline_probe_does_not_produce_authoritative():
    """Acceptance evaluator MUST NOT produce authoritative_continuity_restored
    for the conversation_continuity dimension in a baseline (no-evidence) probe."""
    from core.system_final_acceptance_verdict import (
        get_system_acceptance_evaluator,
        reset_system_acceptance_evaluator,
    )
    reset_system_acceptance_evaluator()
    try:
        evaluator = get_system_acceptance_evaluator()
        report = evaluator.evaluate()
        item = report.checklist.get("conversation_continuity")
        assert item is not None
        # The baseline probe class must NOT be authoritative_continuity_restored
        linkage = item.evidence_linkage or {}
        baseline_class = linkage.get("baseline_probe_class", "")
        assert baseline_class != "authoritative_continuity_restored", (
            "Baseline probe must not report authoritative_continuity_restored "
            "when no live recovery evidence is present."
        )
        baseline_is_auth = linkage.get("baseline_probe_is_authoritative", True)
        assert baseline_is_auth is False
    finally:
        reset_system_acceptance_evaluator()
