"""core/runtime/execution_target_policy_engine.py
==================================================
Execution Target Selection and Failure Handling Policy Engine — PR-I.

This module implements the **canonical policy engine** that applies
policy-driven target selection and failure handling decisions for
multi-device runtime execution.

It is the runtime counterpart to the contracts defined in
``contracts/execution_target_policy.py`` (PR-I):

- The contracts define *what* a policy decision looks like.
- This module implements *how* those decisions are made, given available
  runtime signals.

Architecture role
-----------------
::

    ┌─────────────────────────────────────────────────────────────────┐
    │  ROUTING LAYER                                                   │
    │  CommandRouter  ·  DeviceRouter  ·  SourceDispatchOrchestrator  │
    └───────────────────────────┬─────────────────────────────────────┘
                                │  POLICY DECISION REQUEST
                                ▼
    ┌─────────────────────────────────────────────────────────────────┐
    │  POLICY ENGINE  (this module, PR-I)                              │
    │  apply_target_selection_policy()                                 │
    │  apply_failure_handling_policy()                                 │
    │  apply_degraded_readiness_policy()                               │
    └───────────────────────────┬─────────────────────────────────────┘
                                │  PRODUCES
                                ▼
    ┌─────────────────────────────────────────────────────────────────┐
    │  POLICY CONTRACTS  (contracts/execution_target_policy.py)       │
    │  TargetSelectionDecision  ·  FailureHandlingDecision            │
    └─────────────────────────────────────────────────────────────────┘

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Graceful degradation** — every function returns a valid decision even
  when inputs are partial, None, or raise.
- **Backward compatible** — existing execution paths are not altered;
  the policy engine is consulted at new, explicit decision points.
- **Explicit and inspectable** — every decision carries a
  ``decision_reason`` string so that selection/failure rationale is
  inspectable in production logs without reading source code.
- **No side effects** — these functions are pure decision functions; they
  do not mutate routing state, session state, or registries.

Public surface
--------------
:func:`apply_target_selection_policy`
    Given an executor target type hint and available context signals,
    produce a :class:`~contracts.execution_target_policy.TargetSelectionDecision`.

:func:`apply_failure_handling_policy`
    Given a failure kind and available context signals, produce a
    :class:`~contracts.execution_target_policy.FailureHandlingDecision`.

:func:`apply_degraded_readiness_policy`
    Given a degraded-readiness context, produce a
    :class:`~contracts.execution_target_policy.FailureHandlingDecision`
    with the degraded_readiness_policy field populated.

Sentinels
---------
:data:`EXECUTION_TARGET_POLICY_ENGINE_IS_AUTHORITY`
:data:`POLICY_ENGINE_PR_I_SENTINEL`
:data:`TARGET_SELECTION_POLICY_ENGINE_APPLIES_EXPLICIT_TYPES_POLICY`
:data:`FAILURE_HANDLING_POLICY_ENGINE_CLASSIFIES_RECOVERABLE_POLICY`
:data:`DEGRADED_READINESS_POLICY_ENGINE_USES_THRESHOLD_POLICY`
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from contracts.execution_target_policy import (
    DegradedReadinessPolicyKind,
    FailureHandlingDecision,
    FailureHandlingPolicyKind,
    TargetSelectionDecision,
    TargetSelectionPolicyKind,
    build_failure_handling_decision,
    build_target_selection_decision,
)

logger = logging.getLogger("Galaxy.ExecutionTargetPolicyEngine")

# ---------------------------------------------------------------------------
# Sentinels
# ---------------------------------------------------------------------------

EXECUTION_TARGET_POLICY_ENGINE_IS_AUTHORITY: str = (
    "EXECUTION_TARGET_POLICY_ENGINE_IS_AUTHORITY: "
    "core/runtime/execution_target_policy_engine.py is the canonical policy engine "
    "for PR-I.  It implements apply_target_selection_policy(), "
    "apply_failure_handling_policy(), and apply_degraded_readiness_policy() as the "
    "explicit, inspectable decision points that routing modules consult when choosing "
    "an execution target or responding to a failure/degraded state.  PR-I."
)

POLICY_ENGINE_PR_I_SENTINEL: str = (
    "POLICY_ENGINE_PR_I_SENTINEL: "
    "PR-I policy engine is present and active.  Target selection and failure handling "
    "decisions can be produced for any executor target type or failure kind in the "
    "multi-device runtime."
)

TARGET_SELECTION_POLICY_ENGINE_APPLIES_EXPLICIT_TYPES_POLICY: str = (
    "POLICY::TARGET_SELECTION_POLICY_ENGINE_APPLIES_EXPLICIT_TYPES_PR-I: "
    "When an explicit executor_target_type is present in the task envelope, "
    "apply_target_selection_policy() MUST apply the explicit_executor_type policy "
    "strategy and produce a TargetSelectionDecision with the declared type without "
    "overriding it with heuristics.  Explicit type declarations take precedence over "
    "readiness-weighted or mesh-topology selection.  PR-I."
)

FAILURE_HANDLING_POLICY_ENGINE_CLASSIFIES_RECOVERABLE_POLICY: str = (
    "POLICY::FAILURE_HANDLING_POLICY_ENGINE_CLASSIFIES_RECOVERABLE_PR-I: "
    "apply_failure_handling_policy() MUST classify each failure_kind as recoverable "
    "or non-recoverable and choose the FailureHandlingPolicyKind accordingly.  "
    "Transient failures (transport errors, brief device unavailability) are recoverable "
    "and MUST produce a retry or fallback_local decision.  Structural failures "
    "(capability mismatch, policy rejection) are non-recoverable and MUST produce a "
    "reject_with_reason decision.  This classification is stable and does not require "
    "caller knowledge of the internal failure taxonomy.  PR-I."
)

DEGRADED_READINESS_POLICY_ENGINE_USES_THRESHOLD_POLICY: str = (
    "POLICY::DEGRADED_READINESS_POLICY_ENGINE_USES_THRESHOLD_PR-I: "
    "apply_degraded_readiness_policy() uses a readiness threshold to decide whether "
    "to accept a degraded target, fall back to local, or reject.  The default threshold "
    "behaviour accepts degraded targets when no alternative is available and falls back "
    "to local when an alternative is available.  Callers may override the threshold "
    "via the ``min_readiness_threshold`` parameter.  PR-I."
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Failure kinds classified as recoverable (transient)
_RECOVERABLE_FAILURE_KINDS = frozenset(
    {
        "transport_error",
        "network_timeout",
        "device_disconnect",
        "heartbeat_miss",
        "session_detached",
        "readiness_degraded",
        "readiness_recovering",
        "temporary_unavailable",
        "retry_pending",
    }
)

# Failure kinds classified as non-recoverable (structural/terminal)
_NON_RECOVERABLE_FAILURE_KINDS = frozenset(
    {
        "capability_mismatch",
        "exec_mode_mismatch",
        "policy_rejection",
        "registration_failure",
        "config_error",
        "terminal_loss",
        "aborted",
        "capability_absent",
    }
)

# Default mapping: failure_kind → FailureHandlingPolicyKind
_DEFAULT_FAILURE_POLICY_MAP: Dict[str, str] = {
    "transport_error": FailureHandlingPolicyKind.retry.value,
    "network_timeout": FailureHandlingPolicyKind.retry.value,
    "device_disconnect": FailureHandlingPolicyKind.fallback_local.value,
    "heartbeat_miss": FailureHandlingPolicyKind.retry.value,
    "session_detached": FailureHandlingPolicyKind.fallback_local.value,
    "readiness_degraded": FailureHandlingPolicyKind.fallback_local.value,
    "readiness_recovering": FailureHandlingPolicyKind.wait_and_requeue.value,
    "temporary_unavailable": FailureHandlingPolicyKind.wait_and_requeue.value,
    "retry_pending": FailureHandlingPolicyKind.retry.value,
    "capability_mismatch": FailureHandlingPolicyKind.reject_with_reason.value,
    "exec_mode_mismatch": FailureHandlingPolicyKind.reject_with_reason.value,
    "policy_rejection": FailureHandlingPolicyKind.reject_with_reason.value,
    "registration_failure": FailureHandlingPolicyKind.reject_with_reason.value,
    "config_error": FailureHandlingPolicyKind.reject_with_reason.value,
    "terminal_loss": FailureHandlingPolicyKind.reject_with_reason.value,
    "aborted": FailureHandlingPolicyKind.reject_with_reason.value,
    "capability_absent": FailureHandlingPolicyKind.reject_with_reason.value,
}

# Readiness strings that indicate a usable-but-degraded state
_DEGRADED_READINESS_VALUES = frozenset({"degraded", "recovering", "partial"})

# Readiness strings that indicate full readiness
_READY_READINESS_VALUES = frozenset({"ready", "routable"})


def _coerce_str(value: Any) -> Optional[str]:
    """Coerce a value to a plain string, or return None."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def _is_degraded_readiness(readiness: Optional[str]) -> bool:
    """Return True if the readiness string indicates a degraded state."""
    if readiness is None:
        return False
    return readiness.lower() in _DEGRADED_READINESS_VALUES


def _is_ready(readiness: Optional[str]) -> bool:
    """Return True if the readiness string indicates full readiness."""
    if readiness is None:
        return False
    return readiness.lower() in _READY_READINESS_VALUES


def _is_recoverable_failure(failure_kind: str) -> bool:
    """Return True if *failure_kind* is classified as transient/recoverable."""
    return failure_kind.lower() in _RECOVERABLE_FAILURE_KINDS


# ---------------------------------------------------------------------------
# apply_target_selection_policy
# ---------------------------------------------------------------------------


def apply_target_selection_policy(
    *,
    executor_target_type: Optional[str] = None,
    candidate_device_ids: Optional[List[str]] = None,
    mesh_session: Optional[Dict[str, Any]] = None,
    readiness_map: Optional[Dict[str, str]] = None,
    task_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    mesh_session_id: Optional[str] = None,
    prefer_mesh_topology: bool = False,
    metadata: Optional[Dict[str, Any]] = None,
) -> TargetSelectionDecision:
    """Apply the target selection policy and return a
    :class:`~contracts.execution_target_policy.TargetSelectionDecision`.

    Selection priority
    ------------------
    1. **Explicit executor target type** — when ``executor_target_type`` is
       provided and non-None, the policy applies
       :attr:`~contracts.execution_target_policy.TargetSelectionPolicyKind.explicit_executor_type`
       without further heuristics.
    2. **Mesh topology** — when ``prefer_mesh_topology=True`` and a valid
       ``mesh_session`` with active participants is present, the policy applies
       :attr:`~contracts.execution_target_policy.TargetSelectionPolicyKind.mesh_topology`.
    3. **Readiness-weighted** — when ``readiness_map`` is provided and at
       least one fully-ready candidate exists, the policy applies
       :attr:`~contracts.execution_target_policy.TargetSelectionPolicyKind.readiness_weighted`.
    4. **Fallback local** — when no remote candidate is available, the policy
       applies :attr:`~contracts.execution_target_policy.TargetSelectionPolicyKind.fallback_local`.

    Parameters
    ----------
    executor_target_type:
        Explicit executor target type string (from ``TaskEnvelope``).
    candidate_device_ids:
        List of candidate device IDs to consider for remote selection.
    mesh_session:
        Serialised ``MeshSession`` dict.  Used for mesh topology selection.
    readiness_map:
        Dict mapping device_id → readiness string.  Used for
        readiness-weighted selection.
    task_id:
        Task identifier for traceability.
    trace_id:
        Correlation trace ID.
    mesh_session_id:
        Active mesh session identifier.
    prefer_mesh_topology:
        When ``True``, attempt mesh topology selection before
        readiness-weighted selection.
    metadata:
        Extra metadata key-value pairs.

    Returns
    -------
    TargetSelectionDecision
        Always returns a valid decision; never raises.
    """
    try:
        return _apply_target_selection_policy_impl(
            executor_target_type=_coerce_str(executor_target_type),
            candidate_device_ids=list(candidate_device_ids or []),
            mesh_session=mesh_session or {},
            readiness_map=readiness_map or {},
            task_id=task_id,
            trace_id=trace_id,
            mesh_session_id=mesh_session_id,
            prefer_mesh_topology=prefer_mesh_topology,
            metadata=dict(metadata or {}),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "apply_target_selection_policy: error applying policy: %s", exc, exc_info=True
        )
        return build_target_selection_decision(
            policy_kind=TargetSelectionPolicyKind.default_local,
            selected_executor_type="local",
            decision_reason=f"apply_target_selection_policy: error; fallback to local: {exc}",
            trace_id=trace_id,
            task_id=task_id,
        )


def _apply_target_selection_policy_impl(
    *,
    executor_target_type: Optional[str],
    candidate_device_ids: List[str],
    mesh_session: Dict[str, Any],
    readiness_map: Dict[str, str],
    task_id: Optional[str],
    trace_id: Optional[str],
    mesh_session_id: Optional[str],
    prefer_mesh_topology: bool,
    metadata: Dict[str, Any],
) -> TargetSelectionDecision:
    """Internal implementation of apply_target_selection_policy."""

    # ------------------------------------------------------------------
    # 1. Explicit executor target type → highest priority
    # ------------------------------------------------------------------
    if executor_target_type is not None:
        logger.debug(
            "apply_target_selection_policy: explicit_executor_type=%s",
            executor_target_type,
        )
        return build_target_selection_decision(
            policy_kind=TargetSelectionPolicyKind.explicit_executor_type,
            selected_executor_type=executor_target_type,
            decision_reason=(
                f"explicit executor_target_type={executor_target_type!r} "
                "declared in TaskEnvelope; no heuristics applied"
            ),
            candidates_considered=list(candidate_device_ids),
            trace_id=trace_id,
            task_id=task_id,
            mesh_session_id=mesh_session_id,
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # 2. Mesh topology selection
    # ------------------------------------------------------------------
    if prefer_mesh_topology and mesh_session:
        mesh_participants = mesh_session.get("participants") or []
        active_participants = [
            p for p in mesh_participants
            if isinstance(p, dict) and p.get("status") == "active"
        ]
        if active_participants:
            first = active_participants[0]
            selected_device_id = first.get("device_id")
            readiness = readiness_map.get(selected_device_id or "", "unknown")
            logger.debug(
                "apply_target_selection_policy: mesh_topology selected device=%s",
                selected_device_id,
            )
            return build_target_selection_decision(
                policy_kind=TargetSelectionPolicyKind.mesh_topology,
                selected_executor_type="android_device",
                selected_device_id=selected_device_id,
                decision_reason=(
                    f"mesh_topology: {len(active_participants)} active participant(s); "
                    f"selected first active device={selected_device_id!r}"
                ),
                candidates_considered=[
                    p.get("device_id", "") for p in active_participants
                ],
                trace_id=trace_id,
                task_id=task_id,
                mesh_session_id=mesh_session_id or mesh_session.get("session_id"),
                readiness=readiness,
                metadata=metadata,
            )

    # ------------------------------------------------------------------
    # 3. Readiness-weighted selection
    # ------------------------------------------------------------------
    if candidate_device_ids and readiness_map:
        # Sort by: ready > degraded/recovering > unknown
        def _readiness_score(device_id: str) -> int:
            r = readiness_map.get(device_id, "unknown")
            if _is_ready(r):
                return 2
            if _is_degraded_readiness(r):
                return 1
            return 0

        sorted_candidates = sorted(
            candidate_device_ids,
            key=_readiness_score,
            reverse=True,
        )
        best = sorted_candidates[0]
        best_readiness = readiness_map.get(best, "unknown")
        if _readiness_score(best) > 0:  # at least degraded/recovering
            logger.debug(
                "apply_target_selection_policy: readiness_weighted selected device=%s readiness=%s",
                best,
                best_readiness,
            )
            return build_target_selection_decision(
                policy_kind=TargetSelectionPolicyKind.readiness_weighted,
                selected_executor_type="android_device",
                selected_device_id=best,
                decision_reason=(
                    f"readiness_weighted: selected device={best!r} "
                    f"readiness={best_readiness!r} from {len(candidate_device_ids)} candidates"
                ),
                candidates_considered=sorted_candidates,
                trace_id=trace_id,
                task_id=task_id,
                mesh_session_id=mesh_session_id,
                readiness=best_readiness,
                metadata=metadata,
            )

    # ------------------------------------------------------------------
    # 4. Fallback local — no remote candidates available
    # ------------------------------------------------------------------
    logger.debug(
        "apply_target_selection_policy: fallback_local (no suitable remote candidate)"
    )
    return build_target_selection_decision(
        policy_kind=TargetSelectionPolicyKind.fallback_local,
        selected_executor_type="local",
        decision_reason=(
            "fallback_local: no suitable remote executor found; "
            "candidates_count=%d readiness_entries=%d"
            % (len(candidate_device_ids), len(readiness_map))
        ),
        candidates_considered=list(candidate_device_ids),
        trace_id=trace_id,
        task_id=task_id,
        mesh_session_id=mesh_session_id,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# apply_failure_handling_policy
# ---------------------------------------------------------------------------


def apply_failure_handling_policy(
    *,
    failure_kind: str = "unknown",
    prior_executor_type: Optional[str] = None,
    prior_device_id: Optional[str] = None,
    allow_fallback_local: bool = True,
    allow_retry: bool = True,
    max_retry_count: int = 1,
    current_retry_count: int = 0,
    task_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    errors: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> FailureHandlingDecision:
    """Apply the failure handling policy and return a
    :class:`~contracts.execution_target_policy.FailureHandlingDecision`.

    Policy logic
    ------------
    1. If ``failure_kind`` is non-recoverable → ``reject_with_reason``.
    2. If recoverable and retry is allowed and retry budget remains →
       ``retry``.
    3. If recoverable, retry budget exhausted, and fallback_local is
       allowed → ``fallback_local``.
    4. If recoverable, retry budget exhausted, fallback_local not
       allowed → ``reject_with_reason``.
    5. If unrecognised failure_kind → classify as recoverable and apply
       the standard recoverable path.

    Parameters
    ----------
    failure_kind:
        The kind of failure or degradation.
    prior_executor_type:
        The executor type that failed.
    prior_device_id:
        The device ID that failed.
    allow_fallback_local:
        Whether the caller permits a local fallback after remote failure.
    allow_retry:
        Whether the caller permits a retry attempt.
    max_retry_count:
        Maximum number of retry attempts allowed.
    current_retry_count:
        Number of retry attempts already consumed.
    task_id:
        Task identifier.
    trace_id:
        Correlation trace ID.
    errors:
        Structured error descriptions from the failed attempt.
    metadata:
        Extra metadata key-value pairs.

    Returns
    -------
    FailureHandlingDecision
        Always returns a valid decision; never raises.
    """
    try:
        return _apply_failure_handling_policy_impl(
            failure_kind=str(failure_kind or "unknown").lower(),
            prior_executor_type=_coerce_str(prior_executor_type),
            prior_device_id=_coerce_str(prior_device_id),
            allow_fallback_local=bool(allow_fallback_local),
            allow_retry=bool(allow_retry),
            max_retry_count=int(max_retry_count),
            current_retry_count=int(current_retry_count),
            task_id=task_id,
            trace_id=trace_id,
            errors=list(errors or []),
            metadata=dict(metadata or {}),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "apply_failure_handling_policy: error applying policy: %s", exc, exc_info=True
        )
        return build_failure_handling_decision(
            policy_kind=FailureHandlingPolicyKind.reject_with_reason,
            failure_kind=str(failure_kind or "unknown"),
            is_recoverable=False,
            decision_reason=f"apply_failure_handling_policy: error; reject as safe default: {exc}",
            trace_id=trace_id,
            task_id=task_id,
        )


def _apply_failure_handling_policy_impl(
    *,
    failure_kind: str,
    prior_executor_type: Optional[str],
    prior_device_id: Optional[str],
    allow_fallback_local: bool,
    allow_retry: bool,
    max_retry_count: int,
    current_retry_count: int,
    task_id: Optional[str],
    trace_id: Optional[str],
    errors: List[str],
    metadata: Dict[str, Any],
) -> FailureHandlingDecision:
    """Internal implementation of apply_failure_handling_policy."""

    # ------------------------------------------------------------------
    # Determine recoverability
    # ------------------------------------------------------------------
    if failure_kind in _NON_RECOVERABLE_FAILURE_KINDS:
        is_recoverable = False
    elif failure_kind in _RECOVERABLE_FAILURE_KINDS:
        is_recoverable = True
    else:
        # Unknown failure_kind: treat as recoverable (conservative)
        is_recoverable = True

    # ------------------------------------------------------------------
    # Non-recoverable → always reject
    # ------------------------------------------------------------------
    if not is_recoverable:
        default_kind = _DEFAULT_FAILURE_POLICY_MAP.get(
            failure_kind, FailureHandlingPolicyKind.reject_with_reason.value
        )
        logger.debug(
            "apply_failure_handling_policy: non-recoverable failure_kind=%s → %s",
            failure_kind,
            default_kind,
        )
        return build_failure_handling_decision(
            policy_kind=FailureHandlingPolicyKind(default_kind),
            failure_kind=failure_kind,
            is_recoverable=False,
            decision_reason=(
                f"non-recoverable failure_kind={failure_kind!r}; "
                f"policy={default_kind!r}"
            ),
            prior_executor_type=prior_executor_type,
            prior_device_id=prior_device_id,
            trace_id=trace_id,
            task_id=task_id,
            errors=errors,
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # Recoverable: check retry budget
    # ------------------------------------------------------------------
    retry_budget_remaining = allow_retry and (current_retry_count < max_retry_count)

    if retry_budget_remaining:
        default_kind = _DEFAULT_FAILURE_POLICY_MAP.get(
            failure_kind, FailureHandlingPolicyKind.retry.value
        )
        # If the default policy for this failure_kind is not retry, honour it
        # but only if retry is consistent with the failure kind's semantics.
        # For clarity: if the default is wait_and_requeue, use that; otherwise retry.
        if default_kind == FailureHandlingPolicyKind.wait_and_requeue.value:
            policy_kind = FailureHandlingPolicyKind.wait_and_requeue
            reason = (
                f"recoverable failure_kind={failure_kind!r}; "
                f"retry_count={current_retry_count}/{max_retry_count}; "
                "wait_and_requeue policy applied"
            )
        else:
            policy_kind = FailureHandlingPolicyKind.retry
            reason = (
                f"recoverable failure_kind={failure_kind!r}; "
                f"retry_count={current_retry_count}/{max_retry_count}; "
                "retry budget available"
            )
        logger.debug(
            "apply_failure_handling_policy: recoverable retry_budget=%s → %s",
            retry_budget_remaining,
            policy_kind.value,
        )
        return build_failure_handling_decision(
            policy_kind=policy_kind,
            failure_kind=failure_kind,
            is_recoverable=True,
            decision_reason=reason,
            prior_executor_type=prior_executor_type,
            prior_device_id=prior_device_id,
            trace_id=trace_id,
            task_id=task_id,
            errors=errors,
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # Recoverable, retry budget exhausted: try fallback_local
    # ------------------------------------------------------------------
    if allow_fallback_local:
        logger.debug(
            "apply_failure_handling_policy: retry_budget_exhausted → fallback_local"
        )
        return build_failure_handling_decision(
            policy_kind=FailureHandlingPolicyKind.fallback_local,
            failure_kind=failure_kind,
            is_recoverable=True,
            decision_reason=(
                f"recoverable failure_kind={failure_kind!r}; "
                f"retry budget exhausted (retry_count={current_retry_count}); "
                "falling back to local execution"
            ),
            prior_executor_type=prior_executor_type,
            prior_device_id=prior_device_id,
            trace_id=trace_id,
            task_id=task_id,
            errors=errors,
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # Recoverable, retry budget exhausted, no fallback: reject
    # ------------------------------------------------------------------
    logger.debug(
        "apply_failure_handling_policy: retry_budget_exhausted fallback_disabled → reject"
    )
    return build_failure_handling_decision(
        policy_kind=FailureHandlingPolicyKind.reject_with_reason,
        failure_kind=failure_kind,
        is_recoverable=True,
        decision_reason=(
            f"recoverable failure_kind={failure_kind!r}; "
            f"retry budget exhausted (retry_count={current_retry_count}); "
            "fallback_local disabled; rejecting task"
        ),
        prior_executor_type=prior_executor_type,
        prior_device_id=prior_device_id,
        trace_id=trace_id,
        task_id=task_id,
        errors=errors,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# apply_degraded_readiness_policy
# ---------------------------------------------------------------------------


def apply_degraded_readiness_policy(
    *,
    readiness: Optional[str] = None,
    device_id: Optional[str] = None,
    executor_type: Optional[str] = None,
    alternative_available: bool = False,
    min_readiness_threshold: str = "ready",
    allow_degraded_execution: bool = True,
    task_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> FailureHandlingDecision:
    """Apply the degraded-readiness policy and return a
    :class:`~contracts.execution_target_policy.FailureHandlingDecision`
    with ``degraded_readiness_policy`` populated.

    Policy logic
    ------------
    1. If ``readiness`` is fully ready (``"ready"``, ``"routable"``) →
       this function should not normally be called, but returns a
       ``reject_with_reason`` with ``degraded_readiness_policy=None``
       (not degraded).
    2. If ``readiness`` is degraded and ``alternative_available`` and
       ``min_readiness_threshold="ready"`` → ``fallback_local``.
    3. If ``readiness`` is degraded and ``allow_degraded_execution=True``
       and no alternative available → ``accept_degraded`` via a
       FailureHandlingDecision with ``wait_and_requeue`` kind.
    4. If ``readiness`` is degraded and ``allow_degraded_execution=False``
       → ``reject_degraded``.

    Parameters
    ----------
    readiness:
        Readiness state string of the target device.
    device_id:
        Device identifier of the target with degraded readiness.
    executor_type:
        Executor type of the target.
    alternative_available:
        Whether a fully-ready alternative target is available.
    min_readiness_threshold:
        Minimum readiness level required.  Defaults to ``"ready"``
        (meaning degraded targets are not preferred if alternatives exist).
    allow_degraded_execution:
        Whether degraded-target execution is permitted when no alternative
        is available.
    task_id:
        Task identifier.
    trace_id:
        Correlation trace ID.
    metadata:
        Extra metadata key-value pairs.

    Returns
    -------
    FailureHandlingDecision
        Always returns a valid decision; never raises.
    """
    try:
        return _apply_degraded_readiness_policy_impl(
            readiness=_coerce_str(readiness),
            device_id=_coerce_str(device_id),
            executor_type=_coerce_str(executor_type),
            alternative_available=bool(alternative_available),
            min_readiness_threshold=str(min_readiness_threshold or "ready"),
            allow_degraded_execution=bool(allow_degraded_execution),
            task_id=task_id,
            trace_id=trace_id,
            metadata=dict(metadata or {}),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "apply_degraded_readiness_policy: error applying policy: %s", exc, exc_info=True
        )
        return build_failure_handling_decision(
            policy_kind=FailureHandlingPolicyKind.reject_with_reason,
            failure_kind="readiness_degraded",
            is_recoverable=True,
            decision_reason=f"apply_degraded_readiness_policy: error; reject as safe default: {exc}",
            trace_id=trace_id,
            task_id=task_id,
        )


def _apply_degraded_readiness_policy_impl(
    *,
    readiness: Optional[str],
    device_id: Optional[str],
    executor_type: Optional[str],
    alternative_available: bool,
    min_readiness_threshold: str,
    allow_degraded_execution: bool,
    task_id: Optional[str],
    trace_id: Optional[str],
    metadata: Dict[str, Any],
) -> FailureHandlingDecision:
    """Internal implementation of apply_degraded_readiness_policy."""

    # Not actually degraded
    if readiness is not None and _is_ready(readiness):
        return build_failure_handling_decision(
            policy_kind=FailureHandlingPolicyKind.reject_with_reason,
            failure_kind="readiness_not_degraded",
            is_recoverable=False,
            decision_reason=(
                f"apply_degraded_readiness_policy called for device={device_id!r} "
                f"but readiness={readiness!r} is not degraded; no degraded policy needed"
            ),
            degraded_readiness_policy=None,
            prior_device_id=device_id,
            prior_executor_type=executor_type,
            trace_id=trace_id,
            task_id=task_id,
            metadata=metadata,
        )

    # Degraded and alternative is available → fallback_local
    if alternative_available:
        logger.debug(
            "apply_degraded_readiness_policy: degraded + alternative_available → fallback_local"
        )
        return build_failure_handling_decision(
            policy_kind=FailureHandlingPolicyKind.fallback_local,
            failure_kind="readiness_degraded",
            is_recoverable=True,
            decision_reason=(
                f"readiness={readiness!r} for device={device_id!r}; "
                "alternative target available; applying fallback_local policy"
            ),
            degraded_readiness_policy=DegradedReadinessPolicyKind.fallback_local,
            prior_device_id=device_id,
            prior_executor_type=executor_type,
            trace_id=trace_id,
            task_id=task_id,
            metadata=metadata,
        )

    # Degraded, no alternative, degraded execution allowed → accept
    if allow_degraded_execution:
        logger.debug(
            "apply_degraded_readiness_policy: degraded + no_alternative + allow_degraded → accept"
        )
        return build_failure_handling_decision(
            policy_kind=FailureHandlingPolicyKind.wait_and_requeue,
            failure_kind="readiness_degraded",
            is_recoverable=True,
            recommended_action="accept_degraded",
            decision_reason=(
                f"readiness={readiness!r} for device={device_id!r}; "
                "no alternative available; allow_degraded_execution=True; "
                "accepting degraded target"
            ),
            degraded_readiness_policy=DegradedReadinessPolicyKind.accept_degraded,
            prior_device_id=device_id,
            prior_executor_type=executor_type,
            trace_id=trace_id,
            task_id=task_id,
            metadata=metadata,
        )

    # Degraded, no alternative, degraded execution not allowed → reject
    logger.debug(
        "apply_degraded_readiness_policy: degraded + no_alternative + no_allow_degraded → reject"
    )
    return build_failure_handling_decision(
        policy_kind=FailureHandlingPolicyKind.reject_with_reason,
        failure_kind="readiness_degraded",
        is_recoverable=True,
        decision_reason=(
            f"readiness={readiness!r} for device={device_id!r}; "
            "no alternative available; allow_degraded_execution=False; "
            "rejecting task per policy"
        ),
        degraded_readiness_policy=DegradedReadinessPolicyKind.reject_degraded,
        prior_device_id=device_id,
        prior_executor_type=executor_type,
        trace_id=trace_id,
        task_id=task_id,
        metadata=metadata,
    )


__all__ = [
    # Sentinels
    "EXECUTION_TARGET_POLICY_ENGINE_IS_AUTHORITY",
    "POLICY_ENGINE_PR_I_SENTINEL",
    "TARGET_SELECTION_POLICY_ENGINE_APPLIES_EXPLICIT_TYPES_POLICY",
    "FAILURE_HANDLING_POLICY_ENGINE_CLASSIFIES_RECOVERABLE_POLICY",
    "DEGRADED_READINESS_POLICY_ENGINE_USES_THRESHOLD_POLICY",
    # Public functions
    "apply_target_selection_policy",
    "apply_failure_handling_policy",
    "apply_degraded_readiness_policy",
]
