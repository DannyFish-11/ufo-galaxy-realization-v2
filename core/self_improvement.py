"""
core/self_improvement.py
========================
PR-6 — Mediated Self-Healing Engineering Loop.

**Architecture**
----------------
This module provides the **single authoritative engineering path** through
which all self-healing and code-improvement actions must flow.  It is NOT a
parallel autonomous authority; it is a mediated loop that serves as the
coordination layer between OpenClawd and the lower-level coding/fixing nodes
(Node_112_SelfHealing, enhancements/coding, etc.).

All coding/self-improvement requests must enter the loop via OpenClawd
(``engineer__*`` built-in tools) and advance through the canonical staged
workflow before any code mutation can occur.

**Staged workflow**
-------------------
.. code-block:: text

    OpenClawd
      │  engineer__ built-in tools
      ▼
    SelfHealingLoop (this module)
      ├─ Stage 1: DIAGNOSE        — identify issue, create PatchProposal
      ├─ Stage 2: GATHER_CONTEXT  — attach code/repo context to proposal
      ├─ Stage 3: PLAN_PATCH      — produce a concrete patch plan
      ├─ Stage 4: APPLY           — apply through approved execution path
      ├─ Stage 5: VALIDATE        — harness runs the verification, reads the
      │                             exit code, classify_execution_evidence()
      │                             grades it; only ``trusted`` advances
      └─ Stage 6: RECORD_OUTCOME  — persist outcome to Knowledge Core

Each ``engineer__apply`` call is guarded so that only proposals that have
reached ``PLAN_PATCH`` stage may proceed.  A *validated* outcome passes through
every stage; an *unvalidated* outcome (verification failed or never produced
trusted evidence) may be recorded straight from ``APPLY``, but only with at
least one harness observation attached — so failures still become lessons,
and nothing reaches the Knowledge Core as "validated" on someone's word.

**Verdict independence (M1)**
-----------------------------
Whether a patch passed is never read from the proposer.  ``validate()`` runs a
recognised verifier through :mod:`core.engineering_verification` (observation:
exit code + archived raw output), then adjudicates with
:func:`~core.execution_evidence_model.classify_execution_evidence`.  A caller's
``passed`` is kept as ``claimed_passed`` — a claim, recorded for divergence
analysis, never a verdict.  Guarded by :mod:`core.verdict_independence`.

**Safety invariants**
---------------------
* Proposals begin at ``DIAGNOSE`` and may only advance forward.
* ``VALIDATE`` is reached only on ``EvidenceTrustLevel.trusted``.
* ``APPLY`` is only permitted after ``PLAN_PATCH``.
* All code mutations go through the loop; direct mutation bypasses are
  redirected here (see ``Node_112_SelfHealing`` update).
* Fix outcomes are written into the unified Knowledge Core
  (via :func:`~core.rag_memory.RAGMemory.ingest_knowledge`) rather than a
  separate fixer-only memory silo.

**Singletons**
--------------
Module-level singletons mirror the ``github_installer`` and
``academic_retriever`` patterns::

    self_healing_loop: SelfHealingLoop   # created at import time
    get_self_healing_loop() -> SelfHealingLoop
    reset_self_healing_loop() -> None     # test helper

**Constraints**
---------------
* C1  — module-level singleton ``self_healing_loop`` and
         ``get_self_healing_loop()`` accessor.
* C7  — all public methods return ``{"success": bool, ...}`` or dataclass
         with ``to_dict()``.
* C11 — uses stdlib ``logging``.
* No parallel/competing self-modification path is introduced.
* All knowledge persistence routes through
  :func:`~core.rag_memory.RAGMemory.ingest_knowledge`.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Union

from core.engineering_verification import evidence_for, verify
from core.execution_evidence_model import EvidenceTrustLevel, classify_execution_evidence

logger = logging.getLogger("Galaxy.SelfImprovement")

# ---------------------------------------------------------------------------
# Lazy accessor for RAGMemory — importable so tests can patch it
# ---------------------------------------------------------------------------

try:
    from core.rag_memory import get_rag_memory  # noqa: F401 — re-exported for patching
except ImportError:

    def get_rag_memory():  # type: ignore[misc]
        raise ImportError("core.rag_memory is not available")


# ---------------------------------------------------------------------------
# Source type used when recording fixes in the Knowledge Core
# ---------------------------------------------------------------------------

_ENGINEERING_SOURCE_TYPE = "engineering"
_MAX_RECENT_RECORDS = 200


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class EngineeringStage(str, Enum):
    """Ordered stages of the mediated self-healing engineering loop.

    Each :class:`PatchProposal` advances forward through these stages in
    order.  No stage may be skipped or reversed.
    """

    DIAGNOSE = "diagnose"
    """Initial stage: issue identified, proposal created."""

    GATHER_CONTEXT = "gather_context"
    """Code/repository context has been attached to the proposal."""

    PLAN_PATCH = "plan_patch"
    """Concrete patch plan has been produced and attached."""

    APPLY = "apply"
    """Patch has been applied through the approved execution path."""

    VALIDATE = "validate"
    """Validation checks have been run against the applied patch."""

    RECORD_OUTCOME = "record_outcome"
    """Outcome (success or failure) recorded to the Knowledge Core."""


# Stage ordering — used to enforce forward-only advancement
_STAGE_ORDER: List[EngineeringStage] = [
    EngineeringStage.DIAGNOSE,
    EngineeringStage.GATHER_CONTEXT,
    EngineeringStage.PLAN_PATCH,
    EngineeringStage.APPLY,
    EngineeringStage.VALIDATE,
    EngineeringStage.RECORD_OUTCOME,
]

# Authority label for each stage — for audit logging
ENGINEERING_STAGE_AUTHORITIES: Dict[EngineeringStage, str] = {
    EngineeringStage.DIAGNOSE: "OpenClawd/SelfHealingLoop",
    EngineeringStage.GATHER_CONTEXT: "OpenClawd/SelfHealingLoop",
    EngineeringStage.PLAN_PATCH: "OpenClawd/SelfHealingLoop",
    EngineeringStage.APPLY: "OpenClawd/SelfHealingLoop (approved path only)",
    EngineeringStage.VALIDATE: "OpenClawd/SelfHealingLoop",
    EngineeringStage.RECORD_OUTCOME: "OpenClawd/KnowledgeCore",
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class PatchProposal:
    """A staged patch proposal managed by the mediated engineering loop.

    Proposals advance through :class:`EngineeringStage` stages exactly once
    per stage, in order.
    """

    proposal_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    issue_summary: str = ""
    source: str = "unknown"
    """Who/what raised the proposal (e.g. 'Node_112', 'user', 'openclawd')."""
    stage: EngineeringStage = EngineeringStage.DIAGNOSE
    context: Dict[str, Any] = field(default_factory=dict)
    """Code/repository context attached at GATHER_CONTEXT stage."""
    patch_content: str = ""
    """Textual patch description / diff produced at PLAN_PATCH stage."""
    target_files: List[str] = field(default_factory=list)
    """Files targeted by the patch."""
    apply_result: Optional[Dict[str, Any]] = None
    """Result dict from the APPLY stage execution."""
    validation_passed: Optional[bool] = None
    """Whether validation succeeded — derived from ``trust_level``, never from a claim."""
    validation_notes: str = ""
    knowledge_entry_id: str = ""
    """Knowledge Core entry ID recorded at RECORD_OUTCOME stage."""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    claimed_passed: Optional[bool] = None
    """What the caller *said* about the outcome.  A claim, kept for divergence analysis."""
    trust_level: str = ""
    """``EvidenceTrustLevel`` of the latest harness verification ('' = never verified)."""
    verification_attempts: List[Dict[str, Any]] = field(default_factory=list)
    """Every harness verification: observation, evidence state, trust level, claim, divergence."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "issue_summary": self.issue_summary,
            "source": self.source,
            "stage": self.stage.value if isinstance(self.stage, EngineeringStage) else self.stage,
            "context": self.context,
            "patch_content": self.patch_content,
            "target_files": self.target_files,
            "apply_result": self.apply_result,
            "validation_passed": self.validation_passed,
            "validation_notes": self.validation_notes,
            "knowledge_entry_id": self.knowledge_entry_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
            "claimed_passed": self.claimed_passed,
            "trust_level": self.trust_level,
            "verification_attempts": list(self.verification_attempts),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PatchProposal":
        p = cls()
        p.proposal_id = data.get("proposal_id", p.proposal_id)
        p.issue_summary = data.get("issue_summary", "")
        p.source = data.get("source", "unknown")
        stage_raw = data.get("stage", EngineeringStage.DIAGNOSE.value)
        try:
            p.stage = EngineeringStage(stage_raw)
        except ValueError:
            p.stage = EngineeringStage.DIAGNOSE
        p.context = data.get("context", {})
        p.patch_content = data.get("patch_content", "")
        p.target_files = data.get("target_files", [])
        p.apply_result = data.get("apply_result")
        p.validation_passed = data.get("validation_passed")
        p.validation_notes = data.get("validation_notes", "")
        p.knowledge_entry_id = data.get("knowledge_entry_id", "")
        p.created_at = float(data.get("created_at", time.time()))
        p.updated_at = float(data.get("updated_at", time.time()))
        p.metadata = data.get("metadata", {})
        p.claimed_passed = data.get("claimed_passed")
        p.trust_level = data.get("trust_level", "")
        p.verification_attempts = list(data.get("verification_attempts", []))
        return p


@dataclass
class EngineeringRecord:
    """Immutable record of a completed engineering loop execution."""

    record_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    proposal_id: str = ""
    issue_summary: str = ""
    source: str = "unknown"
    stages_completed: List[str] = field(default_factory=list)
    patch_content: str = ""
    target_files: List[str] = field(default_factory=list)
    apply_result: Optional[Dict[str, Any]] = None
    validation_passed: Optional[bool] = None
    validation_notes: str = ""
    knowledge_entry_id: str = ""
    completed_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    outcome: str = ""
    """``validated`` (reached VALIDATE on trusted evidence) or ``unvalidated``."""
    trust_level: str = ""
    evidence_refs: List[str] = field(default_factory=list)
    """Archive references of the raw verification output, one per executed attempt."""
    claimed_passed: Optional[bool] = None
    divergences: List[Dict[str, Any]] = field(default_factory=list)
    """Attempts where the caller's claim disagreed with the evidence."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "proposal_id": self.proposal_id,
            "issue_summary": self.issue_summary,
            "source": self.source,
            "stages_completed": self.stages_completed,
            "patch_content": self.patch_content,
            "target_files": self.target_files,
            "apply_result": self.apply_result,
            "validation_passed": self.validation_passed,
            "validation_notes": self.validation_notes,
            "knowledge_entry_id": self.knowledge_entry_id,
            "completed_at": self.completed_at,
            "metadata": self.metadata,
            "outcome": self.outcome,
            "trust_level": self.trust_level,
            "evidence_refs": list(self.evidence_refs),
            "claimed_passed": self.claimed_passed,
            "divergences": list(self.divergences),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EngineeringRecord":
        r = cls()
        r.record_id = data.get("record_id", r.record_id)
        r.proposal_id = data.get("proposal_id", "")
        r.issue_summary = data.get("issue_summary", "")
        r.source = data.get("source", "unknown")
        r.stages_completed = data.get("stages_completed", [])
        r.patch_content = data.get("patch_content", "")
        r.target_files = data.get("target_files", [])
        r.apply_result = data.get("apply_result")
        r.validation_passed = data.get("validation_passed")
        r.validation_notes = data.get("validation_notes", "")
        r.knowledge_entry_id = data.get("knowledge_entry_id", "")
        r.completed_at = float(data.get("completed_at", time.time()))
        r.metadata = data.get("metadata", {})
        r.outcome = data.get("outcome", "")
        r.trust_level = data.get("trust_level", "")
        r.evidence_refs = list(data.get("evidence_refs", []))
        r.claimed_passed = data.get("claimed_passed")
        r.divergences = list(data.get("divergences", []))
        return r


@dataclass
class EngineeringLoopSnapshot:
    """Point-in-time snapshot of the engineering loop state."""

    pending_count: int = 0
    recent_record_count: int = 0
    pending_proposals: List[Dict[str, Any]] = field(default_factory=list)
    recent_records: List[Dict[str, Any]] = field(default_factory=list)
    authority: str = "OpenClawd/SelfHealingLoop"
    captured_at: float = field(default_factory=time.time)
    verdict_divergence_count: int = 0
    """Recorded outcomes in which a caller's claim disagreed with harness evidence."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pending_count": self.pending_count,
            "recent_record_count": self.recent_record_count,
            "pending_proposals": self.pending_proposals,
            "recent_records": self.recent_records,
            "authority": self.authority,
            "captured_at": self.captured_at,
            "verdict_divergence_count": self.verdict_divergence_count,
        }


# ---------------------------------------------------------------------------
# Core loop class
# ---------------------------------------------------------------------------


class SelfHealingLoop:
    """Mediated self-healing engineering loop — sole authority for staged code
    improvement/repair actions.

    All external entry-points (OpenClawd ``engineer__*`` tools, Node_112
    proposal delegation) use this class.  Direct code mutation bypassing this
    loop is not permitted.
    """

    def __init__(self, max_records: int = _MAX_RECENT_RECORDS) -> None:
        self._lock = threading.Lock()
        self._proposals: Dict[str, PatchProposal] = {}
        self._records: List[EngineeringRecord] = []
        self._max_records = max_records

    # ------------------------------------------------------------------
    # Stage 1 — DIAGNOSE
    # ------------------------------------------------------------------

    def submit_diagnosis(
        self,
        issue_summary: str,
        source: str = "unknown",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> PatchProposal:
        """Create a new :class:`PatchProposal` at the DIAGNOSE stage.

        This is the *only* way to introduce a new engineering issue into the
        mediated loop.

        Args:
            issue_summary: Human-readable description of the issue.
            source:        Origin of the diagnosis (e.g. ``"Node_112"``,
                           ``"openclawd"``, ``"user"``).
            metadata:      Optional extra data (e.g. metrics snapshot).

        Returns:
            A new :class:`PatchProposal` at ``DIAGNOSE`` stage.
        """
        proposal = PatchProposal(
            issue_summary=issue_summary,
            source=source,
            stage=EngineeringStage.DIAGNOSE,
            metadata=dict(metadata or {}),
        )
        with self._lock:
            self._proposals[proposal.proposal_id] = proposal
        logger.info(
            "SelfHealingLoop: new proposal %s from '%s' — %s",
            proposal.proposal_id,
            source,
            issue_summary[:80],
        )
        return proposal

    # ------------------------------------------------------------------
    # Stage 2 — GATHER_CONTEXT
    # ------------------------------------------------------------------

    def attach_context(
        self,
        proposal_id: str,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Attach code/repository context and advance proposal to
        ``GATHER_CONTEXT``.

        Args:
            proposal_id: ID of the :class:`PatchProposal` to update.
            context:     Context dict (file snippets, repo metadata, etc.).

        Returns:
            ``{"success": True, "proposal_id": ..., "stage": ...}`` or
            ``{"success": False, "error": ...}``.
        """
        with self._lock:
            proposal = self._proposals.get(proposal_id)
            if proposal is None:
                return {"success": False, "error": f"Proposal '{proposal_id}' not found"}
            if proposal.stage != EngineeringStage.DIAGNOSE:
                return {
                    "success": False,
                    "error": (
                        f"Proposal '{proposal_id}' is at stage '{proposal.stage.value}'; "
                        "attach_context requires DIAGNOSE stage"
                    ),
                }
            proposal.context = dict(context)
            proposal.stage = EngineeringStage.GATHER_CONTEXT
            proposal.updated_at = time.time()
        logger.info("SelfHealingLoop: proposal %s → GATHER_CONTEXT", proposal_id)
        return {"success": True, "proposal_id": proposal_id, "stage": EngineeringStage.GATHER_CONTEXT.value}

    # ------------------------------------------------------------------
    # Stage 3 — PLAN_PATCH
    # ------------------------------------------------------------------

    def plan_patch(
        self,
        proposal_id: str,
        patch_content: str,
        target_files: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Attach a concrete patch plan and advance to ``PLAN_PATCH``.

        Proposals that have not yet reached ``GATHER_CONTEXT`` cannot be
        planned — caller must first call :meth:`attach_context`.

        Args:
            proposal_id:   ID of the :class:`PatchProposal`.
            patch_content: Textual description or diff of the planned patch.
            target_files:  List of file paths targeted by the patch.

        Returns:
            ``{"success": bool, ...}``
        """
        with self._lock:
            proposal = self._proposals.get(proposal_id)
            if proposal is None:
                return {"success": False, "error": f"Proposal '{proposal_id}' not found"}
            if proposal.stage != EngineeringStage.GATHER_CONTEXT:
                return {
                    "success": False,
                    "error": (
                        f"Proposal '{proposal_id}' is at stage '{proposal.stage.value}'; "
                        "plan_patch requires GATHER_CONTEXT stage"
                    ),
                }
            proposal.patch_content = patch_content
            proposal.target_files = list(target_files or [])
            proposal.stage = EngineeringStage.PLAN_PATCH
            proposal.updated_at = time.time()
        logger.info(
            "SelfHealingLoop: proposal %s → PLAN_PATCH (files=%s)",
            proposal_id,
            target_files,
        )
        return {"success": True, "proposal_id": proposal_id, "stage": EngineeringStage.PLAN_PATCH.value}

    # ------------------------------------------------------------------
    # Stage 4 — APPLY
    # ------------------------------------------------------------------

    def apply_patch(
        self,
        proposal_id: str,
        apply_metadata: Optional[Dict[str, Any]] = None,
        verify_command: Union[str, Sequence[str], None] = None,
    ) -> Dict[str, Any]:
        """Mark the proposal as applied and advance to ``APPLY`` stage.

        **Safety guard**: only proposals at ``PLAN_PATCH`` stage may proceed.
        The actual code mutation (writing files, calling coding nodes, etc.)
        is performed by the caller *before* or *after* calling this method,
        but this gate ensures the proposal cannot be applied unless it has a
        completed patch plan.

        **Fused verification (R2).**  With ``verify_command`` the harness runs
        the verification immediately after applying and reads its exit code —
        apply → run → read in one step, with no point at which the proposer
        reports an outcome.  The result is attached under ``"verification"``.

        Args:
            proposal_id:    ID of the :class:`PatchProposal`.
            apply_metadata: Optional result dict from the execution layer.
            verify_command: Optional recognised verifier to run right after applying.

        Returns:
            ``{"success": bool, ...}``
        """
        with self._lock:
            proposal = self._proposals.get(proposal_id)
            if proposal is None:
                return {"success": False, "error": f"Proposal '{proposal_id}' not found"}
            if proposal.stage != EngineeringStage.PLAN_PATCH:
                return {
                    "success": False,
                    "error": (
                        f"Proposal '{proposal_id}' is at stage '{proposal.stage.value}'; "
                        "apply_patch requires PLAN_PATCH stage (safety gate)"
                    ),
                }
            raw_apply_metadata = dict(apply_metadata or {})
            operator_approved = bool(raw_apply_metadata.get("operator_approved", False))
            reported_mutation_applied = bool(raw_apply_metadata.get("repo_mutation_applied", False))
            # A repo mutation is treated as true only when both signals exist:
            # operator approval (authorization truth) + execution-layer mutation report (execution truth).
            mutation_applied = operator_approved and reported_mutation_applied
            proposal.apply_result = {
                "runtime_authority": "OpenClawd/SelfHealingLoop",
                "planner_intent_truth": {
                    "intent_layer": "planner",
                    "intent_stage": EngineeringStage.PLAN_PATCH.value,
                    "intent_only": True,
                },
                "tool_invocation_truth": {
                    "tool_name": "engineer__apply",
                    "invoked": True,
                },
                "side_effect_authorization": {
                    "stage_gate_passed": True,
                    "operator_approved": operator_approved,
                    "authorization_status": ("authorized" if operator_approved else "not_authorized"),
                },
                "repo_mutation_truth": {
                    "mutation_reported": reported_mutation_applied,
                    "mutation_applied": mutation_applied,
                },
                "raw_apply_metadata": raw_apply_metadata,
            }
            proposal.stage = EngineeringStage.APPLY
            proposal.updated_at = time.time()
        logger.info("SelfHealingLoop: proposal %s → APPLY", proposal_id)
        result: Dict[str, Any] = {
            "success": True,
            "proposal_id": proposal_id,
            "stage": EngineeringStage.APPLY.value,
            "runtime_authority": "OpenClawd/SelfHealingLoop",
            "planner_intent_truth": proposal.apply_result.get("planner_intent_truth", {}),
            "tool_invocation_truth": proposal.apply_result.get("tool_invocation_truth", {}),
            "side_effect_authorization": proposal.apply_result.get("side_effect_authorization", {}),
            "repo_mutation_truth": proposal.apply_result.get("repo_mutation_truth", {}),
        }
        if verify_command:
            verification = self.validate(proposal_id, command=verify_command)
            result["verification"] = verification
            result["stage"] = verification.get("stage", result["stage"])
        return result

    # ------------------------------------------------------------------
    # Stage 5 — VALIDATE
    # ------------------------------------------------------------------

    def validate(
        self,
        proposal_id: str,
        validation_notes: str = "",
        passed: Optional[bool] = None,
        *,
        command: Union[str, Sequence[str], None] = None,
        timeout_s: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Run the verification in the harness and adjudicate it from evidence.

        The harness executes ``command`` (recognised verifiers only, see
        :mod:`core.engineering_verification`), archives the raw output and
        reads the exit code.  The observation is graded by
        :func:`classify_execution_evidence`; the proposal advances to
        ``VALIDATE`` **only** on ``EvidenceTrustLevel.trusted``.  Otherwise it
        stays at ``APPLY`` so the patch can be corrected and verified again
        (or recorded as an unvalidated outcome).

        ``passed`` is the caller's *claim*.  It is stored as ``claimed_passed``
        and compared with the evidence — a disagreement is recorded as a
        divergence, the highest-value learning signal this loop produces — but
        it never decides anything.

        Args:
            proposal_id:      ID of the :class:`PatchProposal`.
            validation_notes: Human-readable notes.
            passed:           Optional claim about the outcome (not a verdict).
            command:          Verification to run, e.g. ``"pytest tests/test_x.py -q"``.
            timeout_s:        Override for the verification timeout.

        Returns:
            ``{"success": bool, ...}`` — ``success`` is true only when the
            verification produced trusted evidence of a pass.
        """
        with self._lock:
            proposal = self._proposals.get(proposal_id)
            if proposal is None:
                return {"success": False, "error": f"Proposal '{proposal_id}' not found"}
            if proposal.stage != EngineeringStage.APPLY:
                return {
                    "success": False,
                    "error": (
                        f"Proposal '{proposal_id}' is at stage '{proposal.stage.value}'; "
                        "validate requires APPLY stage"
                    ),
                }
            target_files = list(proposal.target_files)

        # 验证在锁外跑：它可能要几分钟，不能让别的提案跟着排队。
        # 普通命令跑一条（并判它跑的测试是否依赖 target_files）；ladder:Lx 按 target_files 跑一组。
        observations = verify(command, target_files=target_files, proposal_id=proposal_id, timeout_s=timeout_s)
        evidence_state, chain_complete, decisive = evidence_for(observations)
        observation = observations[decisive]
        trust = classify_execution_evidence(evidence_state, truth_chain_complete=chain_complete)
        verified = trust is EvidenceTrustLevel.trusted

        divergence: Optional[Dict[str, Any]] = None
        if passed is not None and bool(passed) != verified:
            divergence = {
                "claimed_passed": bool(passed),
                "evidence_verified": verified,
                "trust_level": trust.value,
                "exit_code": observation.exit_code,
                "evidence_ref": observation.evidence_ref,
            }
            logger.warning(
                "SelfHealingLoop: 声明与证据不一致 | proposal=%s claimed=%s evidence=%s trust=%s exit=%s",
                proposal_id,
                passed,
                verified,
                trust.value,
                observation.exit_code,
            )
        attempt: Dict[str, Any] = {
            "observation": observation.to_dict(),
            "observations": [o.to_dict() for o in observations],
            "evidence_state": evidence_state.value,
            "truth_chain_complete": chain_complete,
            "trust_level": trust.value,
            "verified": verified,
            "claimed_passed": passed,
            "notes": validation_notes,
            "divergence": divergence,
        }

        with self._lock:
            proposal = self._proposals.get(proposal_id)
            if proposal is None or proposal.stage != EngineeringStage.APPLY:
                return {"success": False, "error": f"Proposal '{proposal_id}' changed during verification"}
            proposal.verification_attempts.append(attempt)
            if passed is not None:
                proposal.claimed_passed = bool(passed)
            proposal.trust_level = trust.value
            proposal.validation_passed = verified
            proposal.validation_notes = validation_notes
            if verified:
                proposal.stage = EngineeringStage.VALIDATE
            proposal.updated_at = time.time()
            stage = proposal.stage.value

        logger.info(
            "SelfHealingLoop: proposal %s verification → trust=%s state=%s exit=%s stage=%s",
            proposal_id,
            trust.value,
            evidence_state.value,
            observation.exit_code,
            stage,
        )
        result: Dict[str, Any] = {
            "success": verified,
            "proposal_id": proposal_id,
            "stage": stage,
            "validation_passed": verified,
            "trust_level": trust.value,
            "evidence_state": evidence_state.value,
            "exit_code": observation.exit_code,
            "command": list(observation.command),
            "evidence_ref": observation.evidence_ref,
            "commands": [list(o.command) for o in observations],
            "evidence_refs": [o.evidence_ref for o in observations if o.evidence_ref],
            "divergence": divergence,
        }
        if not verified:
            result["error"] = _unverified_reason(observation, evidence_state.value, chain_complete)
        return result

    # ------------------------------------------------------------------
    # Stage 6 — RECORD_OUTCOME
    # ------------------------------------------------------------------

    def record_outcome(self, proposal_id: str) -> Dict[str, Any]:
        """Persist the fix outcome to the unified Knowledge Core and advance
        the proposal to ``RECORD_OUTCOME`` stage.

        Uses :func:`~core.rag_memory.RAGMemory.ingest_knowledge` so the fix
        pattern is discoverable through the same RAG retrieval pipeline as all
        other knowledge — no separate fixer-only memory silo is created.

        Args:
            proposal_id: ID of the :class:`PatchProposal` to finalise.

        Returns:
            ``{"success": bool, "record_id": ..., "knowledge_entry_id": ...}``
        """
        with self._lock:
            proposal = self._proposals.get(proposal_id)
            if proposal is None:
                return {"success": False, "error": f"Proposal '{proposal_id}' not found"}
            if proposal.stage == EngineeringStage.VALIDATE:
                outcome = "validated"
            elif proposal.stage == EngineeringStage.APPLY and proposal.verification_attempts:
                outcome = "unvalidated"
            else:
                return {
                    "success": False,
                    "error": (
                        f"Proposal '{proposal_id}' is at stage '{proposal.stage.value}'; "
                        "record_outcome requires VALIDATE stage, or APPLY with at least one "
                        "harness verification attempt (so the outcome carries evidence)"
                    ),
                }
            attempts = list(proposal.verification_attempts)

        evidence_refs = [
            o["evidence_ref"]
            for a in attempts
            for o in (a.get("observations") or [a.get("observation") or {}])
            if o.get("evidence_ref")
        ]
        divergences = [a["divergence"] for a in attempts if a.get("divergence")]

        # Compose knowledge content outside the lock (I/O may be slow)
        content_lines = [
            f"[Engineering Fix] issue={proposal.issue_summary}",
            f"source={proposal.source}",
            f"patch_content={proposal.patch_content[:500]}{'...' if len(proposal.patch_content) > 500 else ''}",
            f"target_files={', '.join(proposal.target_files)}",
            f"validation_passed={proposal.validation_passed}",
            f"validation_notes={proposal.validation_notes}",
            f"outcome={outcome}",
            f"trust_level={proposal.trust_level or 'unverified'}",
            f"verification_attempts={len(attempts)}",
            f"evidence_refs={', '.join(evidence_refs)}",
        ]
        if divergences:
            content_lines.append(f"claim_evidence_divergences={len(divergences)}")
        content = "\n".join(content_lines)
        source_uri = f"engineering://{proposal.source}/{proposal.proposal_id}"
        tags = ["engineering", "self-healing", "fix"]
        # 「validated」只由 trusted 证据挣来：走到 VALIDATE 阶段的前提就是 trusted。
        if outcome == "validated":
            tags.append("validated")
        else:
            tags.extend(["unvalidated", f"trust:{proposal.trust_level or 'unverified'}"])

        knowledge_entry_id = ""
        try:
            rag = get_rag_memory()
            knowledge_entry_id = rag.ingest_knowledge(
                content=content,
                source=source_uri,
                source_type=_ENGINEERING_SOURCE_TYPE,
                tags=tags,
                metadata={
                    "proposal_id": proposal.proposal_id,
                    "validation_passed": proposal.validation_passed,
                    "target_files": proposal.target_files,
                    "outcome": outcome,
                    "trust_level": proposal.trust_level,
                    "evidence_refs": evidence_refs,
                },
            )
            logger.info(
                "SelfHealingLoop: proposal %s recorded to Knowledge Core → %s",
                proposal_id,
                knowledge_entry_id,
            )
        except Exception as exc:
            logger.warning(
                "SelfHealingLoop: Knowledge Core ingestion failed for proposal %s: %s",
                proposal_id,
                exc,
            )

        stages_completed = [
            s.value for s in _STAGE_ORDER if outcome == "validated" or s is not EngineeringStage.VALIDATE
        ]

        with self._lock:
            proposal.knowledge_entry_id = knowledge_entry_id
            proposal.stage = EngineeringStage.RECORD_OUTCOME
            proposal.updated_at = time.time()

            record = EngineeringRecord(
                proposal_id=proposal.proposal_id,
                issue_summary=proposal.issue_summary,
                source=proposal.source,
                stages_completed=stages_completed,
                patch_content=proposal.patch_content,
                target_files=proposal.target_files,
                apply_result=proposal.apply_result,
                validation_passed=proposal.validation_passed,
                validation_notes=proposal.validation_notes,
                knowledge_entry_id=knowledge_entry_id,
                metadata=dict(proposal.metadata),
                outcome=outcome,
                trust_level=proposal.trust_level,
                evidence_refs=evidence_refs,
                claimed_passed=proposal.claimed_passed,
                divergences=divergences,
            )
            self._records.append(record)
            # trim oldest records if necessary
            if len(self._records) > self._max_records:
                self._records = self._records[-self._max_records :]
            # remove from pending proposals
            self._proposals.pop(proposal_id, None)

        return {
            "success": True,
            "proposal_id": proposal_id,
            "record_id": record.record_id,
            "stage": EngineeringStage.RECORD_OUTCOME.value,
            "knowledge_entry_id": knowledge_entry_id,
            "validation_passed": record.validation_passed,
            "outcome": outcome,
            "trust_level": record.trust_level,
            "evidence_refs": evidence_refs,
        }

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_proposal(self, proposal_id: str) -> Optional[PatchProposal]:
        """Return the :class:`PatchProposal` with the given ID, or ``None``."""
        with self._lock:
            return self._proposals.get(proposal_id)

    def pending_proposals(self) -> List[PatchProposal]:
        """Return all proposals that have not yet reached RECORD_OUTCOME."""
        with self._lock:
            return list(self._proposals.values())

    def recent_records(self, n: int = 20) -> List[EngineeringRecord]:
        """Return up to *n* most recent completed engineering records."""
        with self._lock:
            return list(self._records[-n:])

    def snapshot(self) -> EngineeringLoopSnapshot:
        """Return a :class:`EngineeringLoopSnapshot` of current state."""
        with self._lock:
            pending = [p.to_dict() for p in self._proposals.values()]
            recent = [r.to_dict() for r in self._records[-20:]]
            divergent = sum(1 for r in self._records if r.divergences)
        return EngineeringLoopSnapshot(
            pending_count=len(pending),
            recent_record_count=len(self._records),
            pending_proposals=pending,
            recent_records=recent,
            verdict_divergence_count=divergent,
        )


def _unverified_reason(observation: Any, evidence_state: str, chain_complete: bool) -> str:
    """告诉提案者这次为什么没算通过，以及接下来能做什么。"""
    if not observation.executed:
        why = observation.rejection or "验证没有运行"
    elif observation.timed_out:
        why = "验证超时被终止"
    elif evidence_state == "completed_degraded":
        why = "没有收集到任何测试用例 —— 什么都没测不算通过"
    elif observation.exit_code not in (0, None):
        why = f"验证未通过（退出码 {observation.exit_code}，原文见 {observation.evidence_ref or '未落盘'}）"
    elif getattr(observation, "relevant", None) is False:
        why = observation.relevance_note
    elif not chain_complete:
        why = "退出码 0，但验证原文没能落盘 —— 没有证据的通过不予受理"
    else:
        why = "验证没有产生可信证据"
    return (
        f"{why}。提案停在 APPLY：修正后可再次 validate；若要放弃，可直接 record_outcome "
        "记下这次未通过的结局（带着已有的验证证据）。"
    )


# ---------------------------------------------------------------------------
# Module-level singleton (mirrors github_installer / academic_retriever)
# ---------------------------------------------------------------------------

self_healing_loop: SelfHealingLoop = SelfHealingLoop()


def get_self_healing_loop() -> SelfHealingLoop:
    """Return the module-level :class:`SelfHealingLoop` singleton."""
    return self_healing_loop


def reset_self_healing_loop() -> None:
    """Reset the module-level singleton (test helper)."""
    global self_healing_loop
    self_healing_loop = SelfHealingLoop()
