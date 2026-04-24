"""core/flow_level_truth_ownership.py
=====================================
PR-5V2 (post-533 dual-repo truth alignment): Flow-Level Truth Ownership and
Local/Central Truth Alignment.

Background
----------
Android can report local execution facts to V2 via execution signals, truth
ingress messages, and result / failure / cancel / task_phase structures.
V2 already has ``android_participant_truth_ingress.py``,
``canonical_session_truth.py``, and ``filter_result_units_by_posture()`` to
absorb this information.  However, the system has not yet formally established
at the *flow level*:

- Which Android truths are authoritative upward (i.e. must be absorbed by V2
  as canonical).
- Which truths are only advisory (V2 may record but is not bound by them).
- Which truths are execution evidence (V2 records for audit; no state change).
- Which terminal states must be determined by V2's canonical decision rather
  than Android's local view.
- Where partial results are formally stored in canonical truth.
- How posture changes affect existing partial / final evidence.
- Whether compat fallback influence is blocked during runtime.

This module closes that gap by introducing a **flow-level truth ownership
coordinator** and a **local/central truth alignment** mechanism that:

1. Exposes canonical enums for truth semantic types and decision artifacts.
2. Provides a typed alignment decision dataclass that carries full context.
3. Implements ``evaluate_android_truth_alignment`` — the single entry-point
   that accepts an inbound Android truth envelope (or equivalent dict) and
   returns a structured alignment decision with the correct artifact.
4. Documents all alignment rules as policy sentinels that can be referenced
   by downstream modules.

Design principles
-----------------
- **Additive only** — does not modify any prior module.
- **Integrates with existing modules** — delegates to
  ``android_participant_truth_ingress``, ``canonical_session_truth``, and
  ``delegated_flow_entity`` where appropriate; provides clear integration
  points rather than reimplementing logic.
- **Policy-first** — all authority decisions are stated as policy sentinels.
- **Posture-aware** — posture changes are a first-class concern; the
  coordinator re-evaluates existing evidence when posture changes.
- **Compat-aware** — compat/legacy influence is explicitly modelled and can
  be blocked at the truth layer.

Integration points
------------------
``android_participant_truth_ingress.py``
    The ``AndroidParticipantTruthEnvelope`` and
    ``reconcile_android_participant_truth()`` are the upstream producers of
    the raw truth that this module classifies and routes.

``canonical_session_truth.py``
    ``filter_result_units_by_posture()`` and ``merge_session_truth()`` are
    the downstream consumers of the authoritative truth this module
    validates.  Partial results accepted here are forwarded to that path.

``delegated_flow_entity.py``
    ``DelegatedFlowPhase`` is consulted when checking whether a flow is
    already in a terminal phase (``TERMINAL_FLOW_PHASE_BLOCKS_ADVANCEMENT``).

PR package numbering
--------------------
PR-5V2 of the dual-repo truth alignment closure.
Companion Android-repo PR: ``PR5Android truth alignment``.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Tuple

# ---------------------------------------------------------------------------
# Module authority marker
# ---------------------------------------------------------------------------

FLOW_LEVEL_TRUTH_OWNERSHIP_AUTHORITY: str = (
    "core.flow_level_truth_ownership::PR5V2::"
    "flow-level-truth-ownership-and-local-central-truth-alignment"
)

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

FLOW_TRUTH_OWNERSHIP_IS_CENTRALLY_COORDINATED_POLICY: str = (
    "POLICY::FLOW_TRUTH_OWNERSHIP_IS_CENTRALLY_COORDINATED: "
    "All Android-originated truth that enters V2 MUST pass through the "
    "FlowLevelTruthOwnershipCoordinator (or evaluate_android_truth_alignment) "
    "before being absorbed into canonical V2 state.  No module may apply "
    "Android truth to V2 canonical state without first obtaining an explicit "
    "FlowTruthAlignmentDecision."
)

AUTHORITATIVE_TRUTH_MUST_BE_ABSORBED_POLICY: str = (
    "POLICY::AUTHORITATIVE_TRUTH_MUST_BE_ABSORBED: "
    "Android truths classified as authoritative (cancel, failure, final result) "
    "MUST be absorbed into V2 canonical state via the existing reconcile path "
    "(reconcile_android_participant_truth).  They may not be silently dropped "
    "or demoted to advisory without an explicit policy override."
)

ADVISORY_TRUTH_DOES_NOT_ALTER_CANONICAL_STATE_POLICY: str = (
    "POLICY::ADVISORY_TRUTH_DOES_NOT_ALTER_CANONICAL_STATE: "
    "Android truths classified as advisory (readiness_assessment, "
    "runtime_state, session_snapshot) do NOT materially alter V2 canonical "
    "orchestration state.  They are recorded for observability only."
)

EXECUTION_EVIDENCE_IS_AUDIT_ONLY_POLICY: str = (
    "POLICY::EXECUTION_EVIDENCE_IS_AUDIT_ONLY: "
    "Android truths classified as execution evidence (task_phase, status "
    "progress updates that do not reach terminal) are recorded to the audit "
    "trail (ReplayFoundation) but do not change V2 canonical flow phase "
    "unless they carry a terminal outcome."
)

CANONICAL_TERMINAL_DECISION_IS_V2_EXCLUSIVE_POLICY: str = (
    "POLICY::CANONICAL_TERMINAL_DECISION_IS_V2_EXCLUSIVE: "
    "Terminal flow state (completed / failed / cancelled) is determined by "
    "V2 canonical decision.  Android may report a terminal outcome, but V2 "
    "MUST evaluate that report and produce the canonical terminal decision "
    "before the flow is considered closed.  Android cannot unilaterally "
    "terminal-ise a flow from V2's perspective."
)

PARTIAL_RESULT_TRUTH_HAS_DEDICATED_STORE_POLICY: str = (
    "POLICY::PARTIAL_RESULT_TRUTH_HAS_DEDICATED_STORE: "
    "Partial results reported by Android are stored in the "
    "FlowTruthAlignmentDecision.partial_result_store field and forwarded to "
    "the canonical_session_truth merge path.  They are NOT merged directly "
    "into the final canonical result until a final result signal arrives and "
    "V2 issues a canonical terminal decision."
)

POSTURE_CHANGE_REQUIRES_EVIDENCE_REVALIDATION_POLICY: str = (
    "POLICY::POSTURE_CHANGE_REQUIRES_EVIDENCE_REVALIDATION: "
    "When source_runtime_posture changes mid-flow, any existing partial or "
    "final evidence that was accepted under the previous posture MUST be "
    "re-evaluated via filter_result_units_by_posture() before being accepted "
    "into the new canonical truth.  Evidence that no longer passes posture "
    "filtering is quarantined (FlowTruthDecisionArtifact.quarantine_due_to_posture_conflict)."
)

V2_TERMINAL_BLOCKS_ALL_SUBSEQUENT_ANDROID_TRUTH_POLICY: str = (
    "POLICY::V2_TERMINAL_BLOCKS_ALL_SUBSEQUENT_ANDROID_TRUTH: "
    "Once V2 has issued a canonical terminal decision for a flow, any "
    "subsequent Android truth for that flow MUST be rejected with artifact "
    "FlowTruthDecisionArtifact.reject_due_to_canonical_terminal.  V2 "
    "terminal truth is immutable from the Android perspective."
)

COMPAT_INFLUENCE_IS_BLOCKABLE_AT_TRUTH_LAYER_POLICY: str = (
    "POLICY::COMPAT_INFLUENCE_IS_BLOCKABLE_AT_TRUTH_LAYER: "
    "Truth entries that originate from or are influenced by a compat/legacy "
    "path (identified via the compat_influenced flag in the inbound envelope "
    "or via compat_fallback_authority_guard) MUST be classified with artifact "
    "FlowTruthDecisionArtifact.block_due_to_compat_influence when "
    "block_compat_influence=True is set on the coordinator.  Compat influence "
    "does not silently pass through the truth layer."
)

PARTIAL_THEN_FINAL_MERGE_RULE_POLICY: str = (
    "POLICY::PARTIAL_THEN_FINAL_MERGE_RULE: "
    "When a final result arrives for a flow that already has accepted "
    "partial results, the final result supersedes all partials in the "
    "canonical truth.  Partials are retained in the audit trail but are "
    "not included in the final canonical merge unless the final result is "
    "explicitly partial-inclusive."
)

ANDROID_TRUTH_ADVANCED_BUT_V2_UNCONFIRMED_POLICY: str = (
    "POLICY::ANDROID_TRUTH_ADVANCED_BUT_V2_UNCONFIRMED: "
    "When Android local truth has advanced the flow (e.g. Android reports "
    "execution completed) but V2 canonical state has not yet been confirmed, "
    "the decision artifact is accept_as_authoritative with "
    "pending_v2_confirmation=True.  This intermediate semantic is retained "
    "until V2 issues a canonical confirmation or override."
)

_ALL_POLICY_SENTINELS: Tuple[str, ...] = (
    FLOW_TRUTH_OWNERSHIP_IS_CENTRALLY_COORDINATED_POLICY,
    AUTHORITATIVE_TRUTH_MUST_BE_ABSORBED_POLICY,
    ADVISORY_TRUTH_DOES_NOT_ALTER_CANONICAL_STATE_POLICY,
    EXECUTION_EVIDENCE_IS_AUDIT_ONLY_POLICY,
    CANONICAL_TERMINAL_DECISION_IS_V2_EXCLUSIVE_POLICY,
    PARTIAL_RESULT_TRUTH_HAS_DEDICATED_STORE_POLICY,
    POSTURE_CHANGE_REQUIRES_EVIDENCE_REVALIDATION_POLICY,
    V2_TERMINAL_BLOCKS_ALL_SUBSEQUENT_ANDROID_TRUTH_POLICY,
    COMPAT_INFLUENCE_IS_BLOCKABLE_AT_TRUTH_LAYER_POLICY,
    PARTIAL_THEN_FINAL_MERGE_RULE_POLICY,
    ANDROID_TRUTH_ADVANCED_BUT_V2_UNCONFIRMED_POLICY,
)

# ---------------------------------------------------------------------------
# PR sentinel
# ---------------------------------------------------------------------------

FLOW_LEVEL_TRUTH_OWNERSHIP_PR5V2_SENTINEL: str = (
    "flow_level_truth_ownership::package=PR5V2::"
    "pr=flow-level-truth-ownership-and-local-central-truth-alignment::"
    "authority=FLOW_LEVEL_TRUTH_OWNERSHIP_AUTHORITY::"
    "closes=TRUTH-ALIGN-001"
)

# ---------------------------------------------------------------------------
# FlowTruthSemantics enum
# ---------------------------------------------------------------------------


class FlowTruthSemantics(str, Enum):
    """Canonical classification of the semantic role of an Android-originated truth.

    Values
    ------
    authoritative
        The truth is authoritative upward: V2 MUST absorb it into canonical
        state.  Applicable to cancel / failure / final result signals.
    advisory
        The truth is advisory: V2 records it for observability but is NOT
        bound by it.  Applicable to readiness_assessment / runtime_state /
        session_snapshot.
    execution_evidence
        The truth is evidence of execution activity: recorded to the audit
        trail (ReplayFoundation) but does not change canonical flow phase
        unless it carries a terminal outcome.  Applicable to task_phase
        progress updates and status signals.
    canonical_terminal_decision
        A terminal outcome that V2 has confirmed as the canonical terminal
        state for the flow.  Set by V2 after processing an authoritative
        terminal truth from Android.
    partial_result_truth
        An intermediate partial result: stored separately in the
        partial_result_store and not yet merged into the final canonical
        result.
    posture_sensitive
        A truth that requires posture re-evaluation because the source
        device posture has changed since the truth was originally accepted.
    """

    authoritative = "authoritative"
    advisory = "advisory"
    execution_evidence = "execution_evidence"
    canonical_terminal_decision = "canonical_terminal_decision"
    partial_result_truth = "partial_result_truth"
    posture_sensitive = "posture_sensitive"

    @classmethod
    def from_string(cls, value: Optional[str]) -> "FlowTruthSemantics":
        """Return the matching semantics or ``advisory`` for unrecognised values."""
        if not value:
            return cls.advisory
        normalised = str(value).strip().lower()
        for member in cls:
            if member.value == normalised:
                return member
        return cls.advisory


# ---------------------------------------------------------------------------
# FlowTruthDecisionArtifact enum
# ---------------------------------------------------------------------------


class FlowTruthDecisionArtifact(str, Enum):
    """Canonical disposition artifact for a flow-level truth alignment decision.

    Values
    ------
    accept_as_authoritative
        The truth is accepted as authoritative and must be absorbed into V2
        canonical state via the reconcile path.
    accept_as_advisory
        The truth is accepted as advisory: recorded for observability but
        does not alter canonical state.
    record_as_execution_evidence
        The truth is recorded to the audit trail as execution evidence but
        does not alter canonical flow phase.
    reject_due_to_canonical_terminal
        The truth is rejected because V2 has already reached a canonical
        terminal state for this flow.  V2 terminal truth is immutable.
    quarantine_due_to_posture_conflict
        The truth is quarantined because the source posture has changed and
        the truth no longer passes posture filtering.  It is retained in the
        audit trail but not applied to canonical state.
    block_due_to_compat_influence
        The truth is blocked because it originates from or is influenced by
        a compat/legacy path and block_compat_influence is enabled.
    """

    accept_as_authoritative = "accept_as_authoritative"
    accept_as_advisory = "accept_as_advisory"
    record_as_execution_evidence = "record_as_execution_evidence"
    reject_due_to_canonical_terminal = "reject_due_to_canonical_terminal"
    quarantine_due_to_posture_conflict = "quarantine_due_to_posture_conflict"
    block_due_to_compat_influence = "block_due_to_compat_influence"

    @classmethod
    def from_string(cls, value: Optional[str]) -> "FlowTruthDecisionArtifact":
        """Return the matching artifact or ``accept_as_advisory`` for unknown values."""
        if not value:
            return cls.accept_as_advisory
        normalised = str(value).strip().lower()
        for member in cls:
            if member.value == normalised:
                return member
        return cls.accept_as_advisory

    def is_accepted(self) -> bool:
        """Return True iff this artifact represents an accepted (not rejected/blocked) truth."""
        return self in (
            FlowTruthDecisionArtifact.accept_as_authoritative,
            FlowTruthDecisionArtifact.accept_as_advisory,
            FlowTruthDecisionArtifact.record_as_execution_evidence,
        )

    def is_rejected(self) -> bool:
        """Return True iff this artifact represents a rejected or blocked truth."""
        return not self.is_accepted()


# ---------------------------------------------------------------------------
# FlowTruthAlignmentDecision dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FlowTruthAlignmentDecision:
    """Typed, immutable result of a flow-level truth alignment evaluation.

    Attributes
    ----------
    decision_id
        UUID assigned to this decision for idempotency / audit purposes.
    flow_id
        Delegated flow identifier this decision applies to (may be empty if
        the flow entity was not yet resolved).
    session_id
        Attached runtime session identifier.
    contract_id
        Delegated execution contract identifier.
    truth_semantics
        Canonical :class:`FlowTruthSemantics` classification of the inbound
        Android truth.
    artifact
        Canonical :class:`FlowTruthDecisionArtifact` disposition for the
        inbound truth.
    reason
        Human-readable explanation of the alignment decision.
    evaluated_at
        Unix timestamp (float) when this decision was produced.
    pending_v2_confirmation
        True when Android has reported a terminal outcome that V2 has not yet
        confirmed canonically (ANDROID_TRUTH_ADVANCED_BUT_V2_UNCONFIRMED
        intermediate state).
    posture_changed
        True when the source posture changed mid-flow and posture
        re-evaluation was performed.
    compat_influenced
        True when the inbound truth was identified as originating from or
        influenced by a compat/legacy path.
    partial_result_store
        For partial_result_truth semantics: the partial result payload to be
        forwarded to the canonical_session_truth merge path.
    truth_kind
        String representation of the original Android truth kind (e.g.
        ``"cancel"``, ``"result"``, ``"task_phase"``).
    metadata
        Arbitrary extensibility bag.
    """

    decision_id: str = field(default_factory=lambda: f"ftad_{uuid.uuid4().hex[:12]}")
    flow_id: str = ""
    session_id: str = ""
    contract_id: str = ""
    truth_semantics: FlowTruthSemantics = FlowTruthSemantics.advisory
    artifact: FlowTruthDecisionArtifact = FlowTruthDecisionArtifact.accept_as_advisory
    reason: str = ""
    evaluated_at: float = field(default_factory=time.time)
    pending_v2_confirmation: bool = False
    posture_changed: bool = False
    compat_influenced: bool = False
    partial_result_store: Dict[str, Any] = field(default_factory=dict)
    truth_kind: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_accepted(self) -> bool:
        """Return True iff the artifact represents accepted truth."""
        return self.artifact.is_accepted()

    def is_rejected(self) -> bool:
        """Return True iff the artifact represents rejected or blocked truth."""
        return self.artifact.is_rejected()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "flow_id": self.flow_id,
            "session_id": self.session_id,
            "contract_id": self.contract_id,
            "truth_semantics": self.truth_semantics.value,
            "artifact": self.artifact.value,
            "reason": self.reason,
            "evaluated_at": self.evaluated_at,
            "pending_v2_confirmation": self.pending_v2_confirmation,
            "posture_changed": self.posture_changed,
            "compat_influenced": self.compat_influenced,
            "partial_result_store": dict(self.partial_result_store),
            "truth_kind": self.truth_kind,
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# FlowLevelTruthOwnershipCoordinator
# ---------------------------------------------------------------------------

# Internal constants for known Android truth kind strings (mirror the enum
# from android_participant_truth_ingress without creating a hard dependency).
_AUTHORITATIVE_TRUTH_KINDS = frozenset({"cancel", "failure", "result"})
_EXECUTION_EVIDENCE_KINDS = frozenset({"task_phase", "status"})
_ADVISORY_TRUTH_KINDS = frozenset(
    {"session_snapshot", "readiness_assessment", "runtime_state", "unknown"}
)
_PARTIAL_RESULT_PAYLOAD_KEY = "partial_result"

# Terminal phases from the delegated flow entity (string values).
_TERMINAL_FLOW_PHASES = frozenset({"completed", "failed", "cancelled"})


class FlowLevelTruthOwnershipCoordinator:
    """Coordinator that applies flow-level truth ownership rules to inbound
    Android truth and returns a typed :class:`FlowTruthAlignmentDecision`.

    This is the **single canonical authority** for classifying Android truth
    and determining whether it should be absorbed into V2 canonical state,
    treated as advisory, recorded as execution evidence, or rejected.

    Parameters
    ----------
    block_compat_influence:
        When True, truths identified as compat/legacy influenced are blocked
        with the ``block_due_to_compat_influence`` artifact.  Default: False
        (compat influence is recorded but not blocked, for backward
        compatibility during the migration period).

    Usage
    -----
    Instantiate once (or use the module-level convenience function
    :func:`evaluate_android_truth_alignment`) and call
    :meth:`evaluate` for each inbound Android truth envelope or dict.
    """

    def __init__(self, *, block_compat_influence: bool = False) -> None:
        self._block_compat_influence = block_compat_influence

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        truth_envelope_or_dict: Any,
        *,
        current_flow_phase: Optional[str] = None,
        current_posture: Optional[str] = None,
        previous_posture: Optional[str] = None,
        flow_id: str = "",
    ) -> FlowTruthAlignmentDecision:
        """Evaluate a single inbound Android truth and return an alignment decision.

        Parameters
        ----------
        truth_envelope_or_dict:
            An :class:`~core.android_participant_truth_ingress.AndroidParticipantTruthEnvelope`
            or a plain dict carrying the truth payload.  The coordinator
            extracts ``truth_kind``, ``session_id``, ``contract_id``,
            ``device_id``, and optional partial/compat fields from it.
        current_flow_phase:
            Optional string representation of the current
            :class:`~core.delegated_flow_entity.DelegatedFlowPhase` for the
            flow.  Used to detect whether V2 is already in a terminal state
            (``V2_TERMINAL_BLOCKS_ALL_SUBSEQUENT_ANDROID_TRUTH``).
        current_posture:
            Optional current source runtime posture (e.g. ``"join_runtime"``
            or ``"control_only"``).  Used for posture conflict detection.
        previous_posture:
            Optional previous posture before any mid-flow change.  When this
            differs from *current_posture* the coordinator sets
            ``posture_changed=True`` and may quarantine the truth.
        flow_id:
            Optional pre-resolved delegated flow identifier.  If empty the
            coordinator extracts it from the envelope/dict if available.

        Returns
        -------
        FlowTruthAlignmentDecision
        """
        # --- Extract fields from envelope / dict --------------------------
        truth_kind, session_id, contract_id, compat_influenced, partial_store = (
            self._extract_fields(truth_envelope_or_dict)
        )
        resolved_flow_id = flow_id or self._extract_flow_id(truth_envelope_or_dict)

        # --- Block compat influence if configured -------------------------
        if compat_influenced and self._block_compat_influence:
            return FlowTruthAlignmentDecision(
                flow_id=resolved_flow_id,
                session_id=session_id,
                contract_id=contract_id,
                truth_semantics=FlowTruthSemantics.advisory,
                artifact=FlowTruthDecisionArtifact.block_due_to_compat_influence,
                reason=(
                    "Truth blocked: compat/legacy influence detected and "
                    "block_compat_influence=True on coordinator.  "
                    "Policy: COMPAT_INFLUENCE_IS_BLOCKABLE_AT_TRUTH_LAYER."
                ),
                compat_influenced=True,
                truth_kind=truth_kind,
            )

        # --- Reject if V2 is already canonical terminal -------------------
        if self._is_flow_terminal(current_flow_phase):
            return FlowTruthAlignmentDecision(
                flow_id=resolved_flow_id,
                session_id=session_id,
                contract_id=contract_id,
                truth_semantics=FlowTruthSemantics.canonical_terminal_decision,
                artifact=FlowTruthDecisionArtifact.reject_due_to_canonical_terminal,
                reason=(
                    f"Truth rejected: V2 flow is already in canonical terminal "
                    f"phase '{current_flow_phase}'.  "
                    "Policy: V2_TERMINAL_BLOCKS_ALL_SUBSEQUENT_ANDROID_TRUTH."
                ),
                compat_influenced=compat_influenced,
                truth_kind=truth_kind,
            )

        # --- Detect posture change ----------------------------------------
        posture_changed = self._detect_posture_change(current_posture, previous_posture)

        # --- Quarantine on posture conflict for non-advisory truths -------
        if posture_changed and truth_kind not in _ADVISORY_TRUTH_KINDS:
            return FlowTruthAlignmentDecision(
                flow_id=resolved_flow_id,
                session_id=session_id,
                contract_id=contract_id,
                truth_semantics=FlowTruthSemantics.posture_sensitive,
                artifact=FlowTruthDecisionArtifact.quarantine_due_to_posture_conflict,
                reason=(
                    f"Truth quarantined: source posture changed from "
                    f"'{previous_posture}' to '{current_posture}'.  "
                    "Evidence must be re-evaluated via filter_result_units_by_posture().  "
                    "Policy: POSTURE_CHANGE_REQUIRES_EVIDENCE_REVALIDATION."
                ),
                posture_changed=True,
                compat_influenced=compat_influenced,
                truth_kind=truth_kind,
            )

        # --- Classify by truth kind ---------------------------------------
        semantics, artifact, reason, pending = self._classify(
            truth_kind=truth_kind,
            partial_store=partial_store,
            posture_changed=posture_changed,
        )

        return FlowTruthAlignmentDecision(
            flow_id=resolved_flow_id,
            session_id=session_id,
            contract_id=contract_id,
            truth_semantics=semantics,
            artifact=artifact,
            reason=reason,
            pending_v2_confirmation=pending,
            posture_changed=posture_changed,
            compat_influenced=compat_influenced,
            partial_result_store=partial_store,
            truth_kind=truth_kind,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_fields(
        envelope_or_dict: Any,
    ) -> Tuple[str, str, str, bool, Dict[str, Any]]:
        """Return (truth_kind, session_id, contract_id, compat_influenced, partial_store)."""
        if isinstance(envelope_or_dict, dict):
            truth_kind = str(envelope_or_dict.get("truth_kind", "unknown")).strip().lower()
            session_id = str(envelope_or_dict.get("session_id", ""))
            contract_id = str(envelope_or_dict.get("contract_id", ""))
            compat_influenced = bool(envelope_or_dict.get("compat_influenced", False))
            partial_store = dict(envelope_or_dict.get(_PARTIAL_RESULT_PAYLOAD_KEY, {}))
        else:
            # Assume AndroidParticipantTruthEnvelope-like object
            try:
                truth_kind_attr = getattr(envelope_or_dict, "truth_kind", None)
                if truth_kind_attr is not None:
                    truth_kind = str(getattr(truth_kind_attr, "value", truth_kind_attr)).strip().lower()
                else:
                    truth_kind = "unknown"
            except (AttributeError, TypeError):  # noqa: BLE001
                truth_kind = "unknown"
            session_id = str(getattr(envelope_or_dict, "session_id", "") or "")
            contract_id = str(getattr(envelope_or_dict, "contract_id", "") or "")
            payload = getattr(envelope_or_dict, "payload", {}) or {}
            compat_influenced = bool(
                getattr(envelope_or_dict, "compat_influenced", False)
                or (isinstance(payload, dict) and payload.get("compat_influenced", False))
            )
            result_payload = getattr(envelope_or_dict, "result_payload", {}) or {}
            partial_store = dict(result_payload.get(_PARTIAL_RESULT_PAYLOAD_KEY, {}))
        return truth_kind, session_id, contract_id, compat_influenced, partial_store

    @staticmethod
    def _extract_flow_id(envelope_or_dict: Any) -> str:
        """Extract delegated_flow_id from the envelope if available."""
        if isinstance(envelope_or_dict, dict):
            return str(envelope_or_dict.get("flow_id", "") or envelope_or_dict.get("delegated_flow_id", ""))
        return str(
            getattr(envelope_or_dict, "flow_id", "")
            or getattr(envelope_or_dict, "delegated_flow_id", "")
            or ""
        )

    @staticmethod
    def _is_flow_terminal(current_flow_phase: Optional[str]) -> bool:
        """Return True iff the current flow phase is a terminal phase."""
        if not current_flow_phase:
            return False
        normalised = str(current_flow_phase).strip().lower()
        return any(t in normalised for t in _TERMINAL_FLOW_PHASES)

    @staticmethod
    def _detect_posture_change(
        current_posture: Optional[str], previous_posture: Optional[str]
    ) -> bool:
        """Return True iff posture changed mid-flow."""
        if not current_posture or not previous_posture:
            return False
        return str(current_posture).strip().lower() != str(previous_posture).strip().lower()

    @staticmethod
    def _classify(
        truth_kind: str,
        partial_store: Dict[str, Any],
        posture_changed: bool,
    ) -> Tuple[FlowTruthSemantics, FlowTruthDecisionArtifact, str, bool]:
        """Return (semantics, artifact, reason, pending_v2_confirmation)."""
        if truth_kind in _AUTHORITATIVE_TRUTH_KINDS:
            # Authoritative truths: cancel, failure, result
            pending = truth_kind == "result"  # result needs V2 confirmation before terminal
            return (
                FlowTruthSemantics.authoritative,
                FlowTruthDecisionArtifact.accept_as_authoritative,
                (
                    f"Truth '{truth_kind}' is authoritative: MUST be absorbed "
                    "into V2 canonical state via reconcile path.  "
                    "Policy: AUTHORITATIVE_TRUTH_MUST_BE_ABSORBED."
                ),
                pending,
            )

        if truth_kind in _EXECUTION_EVIDENCE_KINDS:
            if partial_store:
                # Partial result embedded in a task_phase/status update
                return (
                    FlowTruthSemantics.partial_result_truth,
                    FlowTruthDecisionArtifact.accept_as_authoritative,
                    (
                        f"Truth '{truth_kind}' carries partial result: stored in "
                        "partial_result_store for canonical merge path.  "
                        "Policy: PARTIAL_RESULT_TRUTH_HAS_DEDICATED_STORE."
                    ),
                    True,  # pending until final result arrives
                )
            return (
                FlowTruthSemantics.execution_evidence,
                FlowTruthDecisionArtifact.record_as_execution_evidence,
                (
                    f"Truth '{truth_kind}' is execution evidence: recorded to "
                    "audit trail without altering canonical flow phase.  "
                    "Policy: EXECUTION_EVIDENCE_IS_AUDIT_ONLY."
                ),
                False,
            )

        # All other truth kinds (advisory)
        return (
            FlowTruthSemantics.advisory,
            FlowTruthDecisionArtifact.accept_as_advisory,
            (
                f"Truth '{truth_kind}' is advisory: recorded for observability "
                "only; does not alter V2 canonical state.  "
                "Policy: ADVISORY_TRUTH_DOES_NOT_ALTER_CANONICAL_STATE."
            ),
            False,
        )


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------

# Module-level default coordinator (block_compat_influence=False by default
# for backward compatibility; callers that want strict compat blocking should
# instantiate FlowLevelTruthOwnershipCoordinator(block_compat_influence=True)).
_DEFAULT_COORDINATOR: Optional[FlowLevelTruthOwnershipCoordinator] = None
_DEFAULT_COORDINATOR_LOCK_AVAILABLE: bool = False
try:
    import threading as _threading
    _DEFAULT_COORDINATOR_LOCK = _threading.Lock()
    _DEFAULT_COORDINATOR_LOCK_AVAILABLE = True
except Exception:
    _DEFAULT_COORDINATOR_LOCK = None  # type: ignore[assignment]  # pragma: no cover


def get_default_coordinator() -> FlowLevelTruthOwnershipCoordinator:
    """Return the module-level default :class:`FlowLevelTruthOwnershipCoordinator`."""
    global _DEFAULT_COORDINATOR  # noqa: PLW0603
    if _DEFAULT_COORDINATOR is None:
        if _DEFAULT_COORDINATOR_LOCK_AVAILABLE and _DEFAULT_COORDINATOR_LOCK is not None:
            with _DEFAULT_COORDINATOR_LOCK:
                if _DEFAULT_COORDINATOR is None:
                    _DEFAULT_COORDINATOR = FlowLevelTruthOwnershipCoordinator()
        else:
            _DEFAULT_COORDINATOR = FlowLevelTruthOwnershipCoordinator()
    return _DEFAULT_COORDINATOR


def reset_default_coordinator() -> None:
    """Reset the module-level default coordinator (test isolation only)."""
    global _DEFAULT_COORDINATOR  # noqa: PLW0603
    _DEFAULT_COORDINATOR = None


def evaluate_android_truth_alignment(
    truth_envelope_or_dict: Any,
    *,
    current_flow_phase: Optional[str] = None,
    current_posture: Optional[str] = None,
    previous_posture: Optional[str] = None,
    flow_id: str = "",
    block_compat_influence: bool = False,
) -> FlowTruthAlignmentDecision:
    """Evaluate an inbound Android truth against flow-level ownership rules.

    This is the **primary API** for determining how an Android-originated
    truth should be handled at the flow level.  It uses a
    :class:`FlowLevelTruthOwnershipCoordinator` configured with the provided
    options and returns a :class:`FlowTruthAlignmentDecision`.

    For repeated calls with the same policy configuration, prefer
    instantiating :class:`FlowLevelTruthOwnershipCoordinator` directly to
    avoid creating a new coordinator object per call.

    Parameters
    ----------
    truth_envelope_or_dict:
        An :class:`~core.android_participant_truth_ingress.AndroidParticipantTruthEnvelope`
        or a plain dict.
    current_flow_phase:
        Optional current flow phase string.  If in a terminal phase,
        subsequent Android truths are rejected.
    current_posture:
        Optional current source runtime posture.
    previous_posture:
        Optional previous source runtime posture.  When this differs from
        *current_posture*, posture conflict detection is triggered.
    flow_id:
        Optional pre-resolved delegated flow identifier.
    block_compat_influence:
        When True, truths from compat/legacy paths are blocked.

    Returns
    -------
    FlowTruthAlignmentDecision
    """
    coordinator = FlowLevelTruthOwnershipCoordinator(
        block_compat_influence=block_compat_influence
    )
    return coordinator.evaluate(
        truth_envelope_or_dict,
        current_flow_phase=current_flow_phase,
        current_posture=current_posture,
        previous_posture=previous_posture,
        flow_id=flow_id,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    # Authority / PR sentinel
    "FLOW_LEVEL_TRUTH_OWNERSHIP_AUTHORITY",
    "FLOW_LEVEL_TRUTH_OWNERSHIP_PR5V2_SENTINEL",
    # Policy sentinels
    "FLOW_TRUTH_OWNERSHIP_IS_CENTRALLY_COORDINATED_POLICY",
    "AUTHORITATIVE_TRUTH_MUST_BE_ABSORBED_POLICY",
    "ADVISORY_TRUTH_DOES_NOT_ALTER_CANONICAL_STATE_POLICY",
    "EXECUTION_EVIDENCE_IS_AUDIT_ONLY_POLICY",
    "CANONICAL_TERMINAL_DECISION_IS_V2_EXCLUSIVE_POLICY",
    "PARTIAL_RESULT_TRUTH_HAS_DEDICATED_STORE_POLICY",
    "POSTURE_CHANGE_REQUIRES_EVIDENCE_REVALIDATION_POLICY",
    "V2_TERMINAL_BLOCKS_ALL_SUBSEQUENT_ANDROID_TRUTH_POLICY",
    "COMPAT_INFLUENCE_IS_BLOCKABLE_AT_TRUTH_LAYER_POLICY",
    "PARTIAL_THEN_FINAL_MERGE_RULE_POLICY",
    "ANDROID_TRUTH_ADVANCED_BUT_V2_UNCONFIRMED_POLICY",
    # Enums
    "FlowTruthSemantics",
    "FlowTruthDecisionArtifact",
    # Dataclasses
    "FlowTruthAlignmentDecision",
    # Coordinator
    "FlowLevelTruthOwnershipCoordinator",
    # Functions
    "evaluate_android_truth_alignment",
    "get_default_coordinator",
    "reset_default_coordinator",
]
