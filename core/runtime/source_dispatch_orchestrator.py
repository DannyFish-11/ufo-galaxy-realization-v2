"""core/runtime/source_dispatch_orchestrator.py
================================================
Source Runtime Dispatch Orchestrator — PR-35.

This module implements the **canonical source-side execution orchestration
layer** that decides whether to execute locally, delegate to a target
runtime, or coordinate a staged multi-device dispatch using the contracts
established in PR-25 through PR-34.

It is the source-side counterpart to PR-34's ``target_takeover.py``:

- **PR-34** made the *target* runtime able to adopt and execute a handoff
  locally.
- **PR-35** makes the *source* runtime able to plan and orchestrate dispatch
  canonically.

This module answers the architectural question:

    *"On the source side, what canonical orchestration layer decides local
    execution vs remote handoff vs mesh-aware staged dispatch, and how is
    that decision expressed and traced?"*

Public surface
--------------
Mode selection:
    :func:`select_dispatch_mode` — given available context signals, choose
    a :class:`~contracts.source_dispatch.SourceDispatchMode`.

Target selection:
    :func:`select_dispatch_target` — given available mesh / device context,
    select a :class:`~contracts.source_dispatch.SourceDispatchTarget`.

Planning:
    :func:`build_source_dispatch_plan` — assemble a full
    :class:`~contracts.source_dispatch.SourceDispatchPlan` from available
    signals.

Orchestration entry point:
    :func:`orchestrate_source_runtime_dispatch` — end-to-end: select mode,
    build plan, execute (local path or remote handoff), return a
    :class:`~contracts.source_dispatch.SourceDispatchResult`.

Handler class:
    :class:`SourceDispatchOrchestrator` — stateless handler wrapping all
    of the above.

Design principles
-----------------
- **Additive only** — does not modify openclawd.py, agent_bridge.py, or any
  existing module.
- **Reuses execution path** — calls ``OpenClawd._run_execution()`` for local
  dispatch; calls ``galaxy_gateway.agent_bridge`` helpers for remote handoff.
- **Graceful degradation** — every function returns a valid result even when
  inputs are partial, None, or raise.
- **Governance/policy-aware** — consumes PR-27 and PR-28 context when
  available, degrades gracefully when unavailable.
- **Mesh-aware** — integrates PR-32/33 mesh membership/session context for
  staged mesh dispatch planning (full Mesh Session Coordinator deferred to a
  future PR).
- **Target takeover integration** — can invoke PR-34's
  :func:`~core.runtime.target_takeover.execute_local_takeover` when a
  remote target is selected.
- **No persistence / streaming** — in-scope for future PRs only.
- **No full Mesh Session Coordinator** — deferred to PR-37.

Usage::

    from core.runtime.source_dispatch_orchestrator import (
        orchestrate_source_runtime_dispatch,
        SourceDispatchOrchestrator,
    )

    # End-to-end convenience function
    result = orchestrate_source_runtime_dispatch(
        trace_id="trace_abc",
        task={"tool_name": "screenshot", "args": {}},
        task_id="task_001",
        session_id="sess_001",
    )
    payload = result.to_dict()

    # Or use the handler class
    handler = SourceDispatchOrchestrator()
    result = handler.dispatch(
        trace_id="trace_abc",
        task={"tool_name": "screenshot", "args": {}},
    )

See ``docs/SOURCE_RUNTIME_DISPATCH_ORCHESTRATOR.md`` for the full
specification.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PR-24 sentinels — dispatch selection truth consolidation
# ---------------------------------------------------------------------------

DISPATCH_SELECTION_TRUTH_CONSOLIDATED_PR24_SENTINEL: str = (
    "DISPATCH_SELECTION_TRUTH_CONSOLIDATED_PR24::source-dispatch-orchestrator::"
    "readiness+participation+registry+reuse-are-canonical-truth-for-target-selection::"
    "package=24::post-533-dual-repo-runtime-unification"
)

SELECTION_READINESS_IS_REQUIRED_TRUTH_PR24_POLICY: str = (
    "POLICY::SELECTION_READINESS_IS_REQUIRED_TRUTH_PR24: "
    "Dispatch target selection MUST consult device readiness (registered, routable) as a "
    "prerequisite truth gate.  A candidate that fails readiness MUST be rejected with a "
    "stable reason and MUST NOT be selected as a dispatch target."
)

SELECTION_PARTICIPATION_IS_REQUIRED_TRUTH_PR24_POLICY: str = (
    "POLICY::SELECTION_PARTICIPATION_IS_REQUIRED_TRUTH_PR24: "
    "Dispatch target selection MUST consult device participation (orchestration_eligible) "
    "as a prerequisite truth gate.  A candidate that fails participation MUST be rejected "
    "with a stable reason and MUST NOT be selected as a dispatch target."
)

SELECTION_REGISTRY_IS_CANONICAL_GATE_PR24_POLICY: str = (
    "POLICY::SELECTION_REGISTRY_IS_CANONICAL_GATE_PR24: "
    "The attached runtime session registry is the authoritative source for active session "
    "identity during target selection.  Only sessions in 'active' state from the registry "
    "are eligible as dispatch targets.  Non-active (replaced/detached/invalidated) sessions "
    "MUST be rejected.  This is consistent with the registry authority established in PR-19 "
    "through PR-23."
)

SELECTION_REUSE_CONTRIBUTES_PREFERENCE_PR24_POLICY: str = (
    "POLICY::SELECTION_REUSE_CONTRIBUTES_PREFERENCE_PR24: "
    "Reuse eligibility contributes to candidate scoring and preference ordering during "
    "multi-target selection.  A candidate with an eligible reuse binding is preferred over "
    "an otherwise equal candidate without one.  Reuse eligibility does NOT gate selection "
    "on its own — a candidate can still be selected without an eligible reuse binding if "
    "readiness and participation are satisfied."
)

SELECTION_FALLBACK_IS_STABLE_AND_EXPLAINABLE_PR24_POLICY: str = (
    "POLICY::SELECTION_FALLBACK_IS_STABLE_AND_EXPLAINABLE_PR24: "
    "Every dispatch target selection outcome (selected, rejected, fallback) MUST carry a "
    "stable, human-readable reason string.  The reason MUST identify the specific truth "
    "source that drove the outcome so that selection results are explainable without "
    "reading source code."
)

# ---------------------------------------------------------------------------
# PR-25 sentinels — mainline abnormal-path matrix + Phase A acceptance
# ---------------------------------------------------------------------------

MAINLINE_ABNORMAL_PATH_MATRIX_CLOSED_PR25_SENTINEL: str = (
    "MAINLINE_ABNORMAL_PATH_MATRIX_CLOSED_PR25::source-dispatch-orchestrator::"
    "delegated-execution+session-truth+fallback+selection-abnormal-paths-are-covered::"
    "package=25::post-533-dual-repo-runtime-unification"
)

REMOTE_TASK_BLOCKS_LOCAL_LOOP_ABNORMAL_PATH_PR25_POLICY: str = (
    "POLICY::REMOTE_TASK_BLOCKS_LOCAL_LOOP_ABNORMAL_PATH_PR25: "
    "When dispatch mode is remote_handoff and a target has been selected, the local "
    "execution loop MUST NOT run concurrently.  Local execution is only permitted after "
    "the remote handoff path has been fully resolved (success or failure).  This prevents "
    "duplicate execution and session-truth divergence between source and target runtimes."
)

LOCAL_FALLBACK_AFTER_REMOTE_FAILURE_ABNORMAL_PATH_PR25_POLICY: str = (
    "POLICY::LOCAL_FALLBACK_AFTER_REMOTE_FAILURE_ABNORMAL_PATH_PR25: "
    "When a remote handoff attempt fails (remote_handoff_failed or remote_handoff_error), "
    "the dispatch path MUST fall back to local execution with effective_mode=fallback_local "
    "and MUST record a stable decision_reason that identifies the failure origin.  The "
    "fallback MUST NOT silently swallow the remote failure — it MUST be recorded in the "
    "errors list so that the caller can distinguish a clean local dispatch from a "
    "fallback-after-remote-failure outcome."
)

DELEGATED_EXECUTION_FAILURE_SESSION_TRUTH_IS_PRESERVED_PR25_POLICY: str = (
    "POLICY::DELEGATED_EXECUTION_FAILURE_SESSION_TRUTH_IS_PRESERVED_PR25: "
    "Under delegated execution failure transitions (remote_handoff_failed, "
    "remote_handoff_error, no_target_or_envelope), the attached runtime session registry "
    "remains the single authoritative truth source for session state.  The dispatch layer "
    "MUST NOT alter registry state as a side-effect of a failed remote dispatch.  Session "
    "truth is preserved by only allowing registry mutations through the canonical registry "
    "API (register/reconnect/reattach/detach/invalidate)."
)

SELECTION_FALLBACK_UNDER_DEGRADED_CONDITIONS_IS_STABLE_PR25_POLICY: str = (
    "POLICY::SELECTION_FALLBACK_UNDER_DEGRADED_CONDITIONS_IS_STABLE_PR25: "
    "Dispatch target selection under degraded conditions (no active registry sessions, "
    "all candidates failing readiness or participation gates, readiness/participation "
    "subsystems unavailable) MUST produce a stable, deterministic fallback outcome. "
    "The fallback MUST carry a non-empty selection_reason so that observers can "
    "distinguish a degraded-condition fallback from a normal local dispatch.  No "
    "new selection authority or coordinator is introduced — the existing registry, "
    "readiness, participation, and reuse subsystems are the only truth sources."
)

PHASE_A_ACCEPTANCE_ABNORMAL_PATH_PR25_POLICY: str = (
    "POLICY::PHASE_A_ACCEPTANCE_ABNORMAL_PATH_PR25: "
    "Phase A acceptance for PR-25 requires that all of the following abnormal dispatch "
    "paths are exercised by stable regression tests and produce deterministic, "
    "explainable outcomes: "
    "(1) remote task blocks local loop (remote_handoff mode blocks concurrent local execution); "
    "(2) local fallback after remote failure (fallback_local with recorded error); "
    "(3) delegated execution failure preserves session truth (registry unchanged); "
    "(4) selection fallback under degraded conditions is stable and carries a reason; "
    "(5) session truth consistency under failure transitions (registry remains authoritative). "
    "Tests MUST import these sentinels to assert Phase A coverage and MUST NOT introduce "
    "a new abnormal-path coordinator or alternate dispatch authority."
)

# ---------------------------------------------------------------------------
# PR-26 sentinels — client-facing result surfacing normalization
# ---------------------------------------------------------------------------

CLIENT_FACING_RESULT_SURFACING_NORMALIZED_PR26_SENTINEL: str = (
    "CLIENT_FACING_RESULT_SURFACING_NORMALIZED_PR26::source-dispatch-orchestrator::"
    "local+cross-device+delegated+fallback-result-surface-is-coherent-and-uniform::"
    "package=26::post-533-dual-repo-runtime-unification"
)

RESULT_CONTRACT_IS_INVARIANT_ACROSS_DISPATCH_PATHS_PR26_POLICY: str = (
    "POLICY::RESULT_CONTRACT_IS_INVARIANT_ACROSS_DISPATCH_PATHS_PR26: "
    "The client-facing result contract (SourceDispatchResult) MUST be structurally "
    "identical regardless of which internal execution path produced the outcome — "
    "local, remote_handoff, fallback_local, staged_mesh, or blocked.  Every result "
    "MUST carry: result_id, dispatch_id, trace_id, task_id, mode, success, errors, "
    "and decision_reason.  No path-specific surface variant or alternate result "
    "authority is permitted.  Downstream clients MUST be able to consume any result "
    "through the same contract without inspecting the internal execution path."
)

RESULT_SEMANTICS_ARE_COHERENT_REGARDLESS_OF_PATH_PR26_POLICY: str = (
    "POLICY::RESULT_SEMANTICS_ARE_COHERENT_REGARDLESS_OF_PATH_PR26: "
    "Result semantics MUST remain coherent regardless of internal execution path. "
    "Specifically: (1) success=True implies the task was executed and an exec_result "
    "was produced; (2) success=False implies either execution failed or the path was "
    "blocked, and errors list MUST be non-empty explaining why; (3) decision_reason "
    "MUST identify the execution path and outcome ('local_execution:success', "
    "'remote_handoff:success', 'remote_handoff_failed:fallback_local', "
    "'dispatch_blocked_by_policy', etc.); (4) mode MUST reflect the effective "
    "execution path — fallback_local is distinct from local; (5) to_dict() MUST "
    "always return a JSON-serialisable dict with all required fields present."
)

RESULT_IDENTITY_IS_STABLE_ACROSS_EXECUTION_PATHS_PR26_POLICY: str = (
    "POLICY::RESULT_IDENTITY_IS_STABLE_ACROSS_EXECUTION_PATHS_PR26: "
    "Result identity fields (result_id, dispatch_id, trace_id, task_id) MUST be "
    "populated consistently across all execution paths.  result_id is always a new "
    "UUID4 unique to this result.  dispatch_id traces back to the SourceDispatchPlan. "
    "trace_id propagates the distributed trace through every path.  task_id identifies "
    "the task being dispatched.  No path MUST omit or reset these identity fields "
    "as a side-effect of its internal execution logic."
)

NO_PATH_SPECIFIC_RESULT_CONTRACT_DRIFT_PR26_POLICY: str = (
    "POLICY::NO_PATH_SPECIFIC_RESULT_CONTRACT_DRIFT_PR26: "
    "Path-specific result contract drift is explicitly prohibited.  This means: "
    "(1) remote_handoff results MUST NOT add fields not present in local results; "
    "(2) fallback_local results MUST NOT omit fields that local results carry; "
    "(3) blocked results MUST carry the same top-level field set as success results; "
    "(4) delegated execution results MUST surface through SourceDispatchResult, "
    "not through a separate client contract; "
    "(5) the to_dict() output MUST have the same top-level keys regardless of path. "
    "The SourceDispatchResult.to_dict() contract is the single stable client surface."
)

# ---------------------------------------------------------------------------
# PR-27 sentinels — gateway-facing registration and capability error semantics
# ---------------------------------------------------------------------------

GATEWAY_FACING_REGISTRATION_CAPABILITY_ERROR_SEMANTICS_HARDENED_PR27_SENTINEL: str = (
    "GATEWAY_FACING_REGISTRATION_CAPABILITY_ERROR_SEMANTICS_HARDENED_PR27::"
    "source-dispatch-orchestrator::registration+capability+readiness-failure-modes-are-"
    "distinguishable-through-stable-gateway-facing-semantics::"
    "package=27::post-533-dual-repo-runtime-unification"
)

REGISTRATION_FAILURE_IS_DISTINGUISHABLE_FROM_CAPABILITY_FAILURE_PR27_POLICY: str = (
    "POLICY::REGISTRATION_FAILURE_IS_DISTINGUISHABLE_FROM_CAPABILITY_FAILURE_PR27: "
    "Gateway-facing registration failures MUST be distinguishable from capability "
    "failures through stable error semantics.  Registration failures (device not "
    "registered, session absent, identity mismatch) MUST carry a failure_kind of "
    "'registration_failure' and expose a structured reason code.  Capability failures "
    "(required action unsupported, exec_mode mismatch, capability_not_satisfied) MUST "
    "carry failure_kind='capability_failure'.  Upstream Android product flows MUST be "
    "able to distinguish these failure modes without inspecting raw error strings.  "
    "No parallel error authority or registration coordinator is introduced."
)

READINESS_DEGRADED_BEHAVIOR_IS_REPORTED_THROUGH_STABLE_SIGNALS_PR27_POLICY: str = (
    "POLICY::READINESS_DEGRADED_BEHAVIOR_IS_REPORTED_THROUGH_STABLE_SIGNALS_PR27: "
    "Readiness-related degraded behavior MUST be reported through existing stable "
    "gateway-facing signals.  Specifically: (1) network/transport failures MUST set "
    "failure_kind='readiness_failure' with a routable=False or transport_unavailable "
    "reason; (2) configuration errors (missing credentials, bad config) MUST set "
    "failure_kind='config_error'; (3) readiness gate blocking MUST propagate the "
    "canonical BlockedBy reason code to the gateway-facing surface; (4) degraded "
    "readiness (recovering/degraded status) MUST be surfaced as a distinct signal "
    "that upstream retry/reconnect UX can consume.  Existing readiness and device "
    "readiness surfaces are the canonical source — no parallel readiness authority."
)

CAPABILITY_NOT_SATISFIED_FAILURE_IS_ACTIONABLE_PR27_POLICY: str = (
    "POLICY::CAPABILITY_NOT_SATISFIED_FAILURE_IS_ACTIONABLE_PR27: "
    "Capability-not-satisfied failures MUST produce actionable gateway-facing signals. "
    "When a required capability is absent or does not match the required exec_mode, "
    "the gateway response MUST identify: (1) which capability or action is missing; "
    "(2) why it failed (not_registered, exec_mode_mismatch, capability_absent); "
    "(3) whether the failure is transient (device temporarily offline) or permanent "
    "(capability structurally absent).  This enables upstream Android product UX to "
    "present a specific setup or retry prompt rather than a generic error."
)

GATEWAY_SETUP_CONNECTION_SIGNALS_ARE_DETERMINISTIC_PR27_POLICY: str = (
    "POLICY::GATEWAY_SETUP_CONNECTION_SIGNALS_ARE_DETERMINISTIC_PR27: "
    "Gateway-facing setup and connection signals MUST be deterministic for regression "
    "coverage.  The signal surface includes: device registration ack (success/failure "
    "with structured reason), capability report ack (accepted/rejected with reason), "
    "readiness gate outcome (ready/blocked/degraded with BlockedBy code).  Each signal "
    "MUST carry a stable failure_kind that upstream product flows can branch on.  "
    "Signal shape MUST NOT vary between paths — the same top-level fields are always "
    "present.  Retry and reconnect UX MUST be able to rely on these fields as a "
    "stable contract without defensive inspection of raw message payloads."
)

# ---------------------------------------------------------------------------
# PR-28: Integrated Regression Closure and Release-Readiness Tightening
# ---------------------------------------------------------------------------

INTEGRATED_REGRESSION_CLOSURE_RELEASE_READINESS_PR28_SENTINEL: str = (
    "INTEGRATED_REGRESSION_CLOSURE_RELEASE_READINESS_PR28::"
    "source-dispatch-orchestrator::end-to-end-dispatch-execution-result-coherence-"
    "integrated-selection-registry-reuse-fallback-registration-capability-readiness::"
    "package=28::post-533-dual-repo-runtime-unification"
)

END_TO_END_DISPATCH_EXECUTION_RESULT_COHERENCE_PR28_POLICY: str = (
    "POLICY::END_TO_END_DISPATCH_EXECUTION_RESULT_COHERENCE_PR28: "
    "The full client-facing and dispatch-facing chain MUST behave coherently across "
    "selection, delegated execution, session truth, fallback, and result surfacing.  "
    "A dispatch request MUST produce a result whose identity (trace_id, task_id, "
    "session_id) matches the originating request at every stage: selection, "
    "execution handoff, delegated signal ingress, reconciliation, and final "
    "result surface.  No stage may drop or rewrite identity fields.  Fallback "
    "results MUST carry the same identity as the primary path.  This policy is the "
    "authoritative statement of V2 end-to-end coherence for regression closure."
)

INTEGRATED_SELECTION_REGISTRY_REUSE_FALLBACK_BEHAVIOR_PR28_POLICY: str = (
    "POLICY::INTEGRATED_SELECTION_REGISTRY_REUSE_FALLBACK_BEHAVIOR_PR28: "
    "Integrated selection/registry/reuse/fallback behavior MUST be regression-closed "
    "across all combinations.  Selection (PR-24) MUST consult the authoritative "
    "registry (PR-19/PR-22), gate through readiness and participation, and prefer "
    "reuse-eligible sessions.  When no candidate passes the gates, the canonical "
    "fallback (PR-23 takeover/fallback route) MUST be invoked deterministically.  "
    "Reuse-binding state (PR-14/PR-17) MUST remain coherent after fallback.  "
    "Registry entries MUST not be silently mutated as a side-effect of selection "
    "or fallback.  The chain select → reuse-check → fallback route MUST be "
    "idempotent for the same input state."
)

REGISTRATION_CAPABILITY_READINESS_UNDER_INTEGRATED_SCENARIOS_PR28_POLICY: str = (
    "POLICY::REGISTRATION_CAPABILITY_READINESS_UNDER_INTEGRATED_SCENARIOS_PR28: "
    "Registration, capability, and readiness semantics (PR-27) MUST remain coherent "
    "when exercised through integrated scenarios that cross selection, delegated "
    "execution, and fallback.  A device that fails the readiness gate during "
    "selection MUST produce the same failure_kind signal as a device that fails "
    "the readiness gate during capability report.  A capability-not-satisfied "
    "failure encountered during delegated dispatch MUST surface the same actionable "
    "fields as a pre-dispatch capability check.  Registration state MUST be "
    "consistent across the registry, readiness, and gateway-facing ack surfaces "
    "throughout the lifecycle of a dispatch request."
)

REGRESSION_STABILIZATION_RELEASE_READINESS_TIGHTENING_PR28_POLICY: str = (
    "POLICY::REGRESSION_STABILIZATION_RELEASE_READINESS_TIGHTENING_PR28: "
    "Release-readiness tightening MUST address cross-feature interaction regressions "
    "discovered during integrated passes.  Specifically: (1) result surfacing (PR-26) "
    "MUST be stable when combined with selection fallback (PR-24/PR-23); "
    "(2) gateway-facing error semantics (PR-27) MUST be stable when readiness "
    "degradation occurs mid-dispatch; (3) session registry truth (PR-19/PR-22) "
    "MUST not diverge from reuse-binding state (PR-14) under concurrent "
    "register/replace/detach transitions; (4) delegated execution tracking (PR-10) "
    "MUST be consistent with ingress reconciliation (PR-13/PR-16/PR-21) across "
    "all terminal signal kinds.  No new release coordinator, orchestration "
    "authority, or parallel architecture is introduced by this tightening pass."
)


# ---------------------------------------------------------------------------
# PR-29: Post-Release Follow-Up Tightening Across Dispatch and Client Semantics
# ---------------------------------------------------------------------------

POST_RELEASE_DISPATCH_CLIENT_SEMANTICS_TIGHTENING_PR29_SENTINEL: str = (
    "POST_RELEASE_DISPATCH_CLIENT_SEMANTICS_TIGHTENING_PR29::"
    "source-dispatch-orchestrator::dispatch-selection-cohesion-registration-readiness-"
    "capability-stability-delegated-execution-fallback-client-gateway-result-alignment::"
    "package=29::post-533-dual-repo-runtime-unification"
)

DISPATCH_SELECTION_COHESION_POST_RELEASE_PR29_POLICY: str = (
    "POLICY::DISPATCH_SELECTION_COHESION_POST_RELEASE_PR29: "
    "Post-release dispatch selection MUST remain cohesive across the PR-24 selection "
    "truth, PR-19/PR-22 registry authority, PR-14/PR-17 reuse-binding, and PR-23 "
    "takeover/fallback route.  Any remaining gaps in selection scoring, candidate "
    "gating, or fallback triggering discovered after PR-28 regression closure MUST "
    "be addressed within the existing architecture.  Selection output MUST be "
    "deterministic for any given input registry state, readiness state, and "
    "participation state.  No new selection authority or parallel scoring model is "
    "introduced by this follow-up tightening pass."
)

REGISTRATION_READINESS_CAPABILITY_STABILITY_POST_RELEASE_PR29_POLICY: str = (
    "POLICY::REGISTRATION_READINESS_CAPABILITY_STABILITY_POST_RELEASE_PR29: "
    "Registration, readiness, and capability surfaces (PR-27) MUST remain stable "
    "across post-release edge cases discovered after PR-28.  Specifically: "
    "(1) registration state transitions MUST be idempotent under repeated "
    "register/reconnect/reattach sequences; (2) readiness degradation signals MUST "
    "carry a stable failure_kind across all degradation paths; "
    "(3) capability-not-satisfied failures encountered after partial delegated "
    "execution MUST be surfaced with the same actionable fields as pre-dispatch "
    "capability failures.  No new registration coordinator or capability model "
    "is introduced."
)

DELEGATED_EXECUTION_FALLBACK_SEMANTIC_CONSISTENCY_PR29_POLICY: str = (
    "POLICY::DELEGATED_EXECUTION_FALLBACK_SEMANTIC_CONSISTENCY_PR29: "
    "Delegated execution (PR-10/PR-16/PR-21) and fallback (PR-23) paths MUST "
    "remain semantically consistent after post-release tightening.  Fallback "
    "triggered by a delegated execution timeout, cancellation, or error MUST "
    "produce the same client-visible outcome shape as a pre-dispatch fallback.  "
    "Terminal signals (timeout/cancelled/error) received through the ingress-"
    "reconciliation path MUST update the execution tracker to a consistent "
    "terminal phase before fallback is invoked.  No new fallback coordinator or "
    "parallel delegated execution path is introduced."
)

CLIENT_GATEWAY_RESULT_CONTRACT_ALIGNMENT_POST_RELEASE_PR29_POLICY: str = (
    "POLICY::CLIENT_GATEWAY_RESULT_CONTRACT_ALIGNMENT_POST_RELEASE_PR29: "
    "Client-facing and gateway-facing result contracts (PR-26/PR-27) MUST remain "
    "aligned after post-release edge-case tightening.  Specifically: "
    "(1) the result identity fields (trace_id, task_id, session_id) MUST be "
    "preserved end-to-end regardless of whether the result originates from a "
    "primary dispatch path, a delegated execution path, or a fallback path; "
    "(2) failure_kind vocabulary MUST be exhaustive and stable — no unclassified "
    "failure kind MUST reach the client or gateway surface; "
    "(3) the registered runtime device contract (PR-29/PR-5) surfaces MUST be "
    "consistent with the dispatch registry state at all times.  No duplicate "
    "result contract or parallel client surface is introduced."
)


# ---------------------------------------------------------------------------
# PR-30: Post-Rollout Observability, Diagnostics, and Rollout Safety Hardening
# ---------------------------------------------------------------------------

POST_ROLLOUT_OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_PR30_SENTINEL: str = (
    "POST_ROLLOUT_OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_PR30::"
    "source-dispatch-orchestrator::dispatch-selection-observability-registration-"
    "readiness-capability-fallback-diagnostics-rollout-safety-signals::"
    "package=30::post-533-dual-repo-runtime-unification"
)

DISPATCH_SELECTION_OBSERVABILITY_PR30_POLICY: str = (
    "POLICY::DISPATCH_SELECTION_OBSERVABILITY_PR30: "
    "Post-rollout dispatch-path decisions and failures MUST emit deterministic "
    "diagnostic signals that allow operators and developers to identify which "
    "selection path was taken (local/delegated/fallback/mesh), the scoring "
    "inputs that led to that decision, and the reason any candidate was rejected "
    "or demoted.  Diagnostic signals MUST be emitted from the existing PR-24 "
    "selection truth layer (scoring, gating, fallback) without introducing a "
    "parallel diagnostic authority or new selection coordinator.  "
    "No new dispatch selection coordinator or alternate scoring model is introduced."
)

REGISTRATION_READINESS_CAPABILITY_FALLBACK_DIAGNOSTICS_PR30_POLICY: str = (
    "POLICY::REGISTRATION_READINESS_CAPABILITY_FALLBACK_DIAGNOSTICS_PR30: "
    "Registration failure, readiness degradation, capability mismatch, and "
    "fallback transition events MUST surface actionable diagnostic signals "
    "through the existing PR-19/PR-22 registry, PR-15/PR-18 readiness, "
    "PR-27 gateway-facing error semantics, and PR-23 fallback surfaces.  "
    "Each diagnostic signal MUST include a stable failure_kind drawn from the "
    "PR-27 exhaustive vocabulary (registration_failure/capability_failure/"
    "readiness_failure/config_error) and a traceable event context.  "
    "No new registration coordinator, readiness subsystem, or fallback authority "
    "is introduced by this observability hardening pass."
)

DELEGATED_EXECUTION_OBSERVABILITY_PR30_POLICY: str = (
    "POLICY::DELEGATED_EXECUTION_OBSERVABILITY_PR30: "
    "Delegated execution paths (PR-10/PR-16/PR-21/PR-23) MUST expose "
    "observable state transitions — pending_ack, acknowledged, in_progress, "
    "completed, failed, timed_out, cancelled — as diagnostic signals aligned "
    "with the existing DelegatedExecutionPhase enum.  Fallback transitions "
    "triggered by terminal delegated signals MUST be traceable end-to-end "
    "from ingress (PR-16/PR-21) through reconciliation (PR-13) to the fallback "
    "route (PR-23).  No new delegated execution tracker or parallel ingress "
    "path is introduced."
)

CLIENT_RESULT_OBSERVABILITY_ROLLOUT_SAFETY_PR30_POLICY: str = (
    "POLICY::CLIENT_RESULT_OBSERVABILITY_ROLLOUT_SAFETY_PR30: "
    "Client-facing and gateway-facing result contracts (PR-26/PR-27/PR-29) "
    "MUST include rollout-safety signals that allow rapid triage of degraded "
    "outcomes during incremental rollout.  Specifically: (1) result envelopes "
    "MUST carry a traceable dispatch_path field (local/delegated/fallback) so "
    "operators can correlate client-visible failures with internal dispatch "
    "decisions; (2) degraded readiness and capability-mismatch outcomes MUST "
    "expose a stable diagnostic_context that includes the failure_kind, "
    "rejection_reason, and selection_path; (3) rollout safety signals MUST "
    "be observable without requiring changes to the existing authority model.  "
    "No new client contract surface, parallel result pipeline, or duplicate "
    "diagnostics subsystem is introduced."
)

OPERATOR_DEVELOPER_DEBUG_CLARITY_PR30_POLICY: str = (
    "POLICY::OPERATOR_DEVELOPER_DEBUG_CLARITY_PR30: "
    "Operator-facing and developer-facing debug clarity MUST be improved "
    "across all rollout-critical paths: selection, registration, readiness, "
    "capability, delegated execution, fallback, and result surfacing.  "
    "Debug signals MUST be emitted through the existing V2 logging and "
    "projection surfaces (core/routes/projection.py) so that troubleshooting "
    "can be performed without a separate diagnostics coordinator.  "
    "Regression coverage MUST be added for any new observable state or "
    "diagnostic signal to ensure deterministic behavior under all "
    "failure conditions.  No alternate control authority, duplicate "
    "diagnostics subsystem, or parallel troubleshooting path is introduced."
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _try_governance_snapshot() -> Optional[Dict[str, Any]]:
    """Attempt to capture the current RuntimeGovernanceSnapshot (PR-27)."""
    try:
        from core.runtime_governance.snapshot import assemble_runtime_governance_snapshot

        snap = assemble_runtime_governance_snapshot()
        if snap is not None:
            if hasattr(snap, "to_dict"):
                return snap.to_dict()
            if isinstance(snap, dict):
                return snap
    except Exception:  # noqa: BLE001
        pass
    return None


def _try_policy_alignment() -> Optional[Dict[str, Any]]:
    """Attempt to capture the current ExecutionPolicyAlignmentSurface (PR-28)."""
    try:
        from core.routes.projection import _assemble_policy_alignment  # type: ignore[attr-defined]

        return _assemble_policy_alignment()
    except Exception:  # noqa: BLE001
        pass
    return None


def _try_mesh_session(mesh_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Attempt to capture the current MeshSession (PR-33)."""
    try:
        from core.mesh.body_mesh_registry import get_body_mesh_registry

        registry = get_body_mesh_registry()
        session = registry.get_mesh_session(mesh_id=mesh_id or "default_mesh")
        if session is None:
            from contracts.mesh_session import build_mesh_session

            session = build_mesh_session(mesh_id=mesh_id or "default_mesh")
        return session.to_dict() if hasattr(session, "to_dict") else dict(session)
    except Exception:  # noqa: BLE001
        pass
    return None


def _try_mesh_memberships(mesh_id: Optional[str] = None) -> Optional[List[Dict[str, Any]]]:
    """Attempt to capture the current MeshMembership list (PR-32)."""
    try:
        from core.mesh.body_mesh_registry import get_body_mesh_registry

        registry = get_body_mesh_registry()
        memberships = registry.get_mesh_memberships(mesh_id=mesh_id or "default_mesh")
        if memberships:
            return [
                m.to_dict() if hasattr(m, "to_dict") else dict(m)
                for m in memberships
            ]
    except Exception:  # noqa: BLE001
        pass
    return None


def _try_run_local_execution(
    state_continuum: Dict[str, Any],
    *,
    entry_mode: str = "local",
) -> Dict[str, Any]:
    """Invoke local execution via ``OpenClawd._run_execution()``.

    Degrades gracefully when OpenClawd is unavailable.
    """
    try:
        _openclawd_instance = None
        try:
            from core.openclawd import OpenClawd

            if hasattr(OpenClawd, "get_instance"):
                _openclawd_instance = OpenClawd.get_instance()
            elif hasattr(OpenClawd, "_instance"):
                _openclawd_instance = OpenClawd._instance
        except Exception:  # noqa: BLE001
            pass

        if _openclawd_instance is not None and hasattr(_openclawd_instance, "_run_execution"):
            return _openclawd_instance._run_execution(
                state_continuum,
                entry_mode=entry_mode,
            )

        logger.debug(
            "_try_run_local_execution: OpenClawd unavailable; returning skipped result"
        )
        return {
            "action_taken": "none",
            "success": False,
            "skipped_reason": "executor_unavailable:no_openclawd_instance",
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("_try_run_local_execution: execution raised: %s", exc)
        return {
            "action_taken": "error",
            "success": False,
            "skipped_reason": f"internal_error:{exc}",
        }


def _try_remote_handoff(
    envelope: Any,
) -> Dict[str, Any]:
    """Attempt to dispatch a HandoffEnvelopeV2 via ``galaxy_gateway.agent_bridge``.

    Returns a result dict on success; a minimal failure dict on any error.
    """
    try:
        from galaxy_gateway.agent_bridge import AgentBridge  # type: ignore[attr-defined]

        bridge = AgentBridge() if hasattr(AgentBridge, "__init__") else None
        if bridge is not None and hasattr(bridge, "forward_handoff"):
            resp = bridge.forward_handoff(envelope)
            if resp is None:
                return {"success": False, "skipped_reason": "bridge_returned_none"}
            if isinstance(resp, dict):
                return resp
            if hasattr(resp, "to_dict"):
                return resp.to_dict()
            return {"success": True, "bridge_response": str(resp)}
        # Fallback: no suitable bridge method
        return {
            "success": False,
            "skipped_reason": "agent_bridge_unavailable:no_forward_handoff",
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("_try_remote_handoff: bridge dispatch raised: %s", exc)
        return {
            "success": False,
            "skipped_reason": f"bridge_error:{exc}",
        }


# ---------------------------------------------------------------------------
# Mode selection logic
# ---------------------------------------------------------------------------


def select_dispatch_mode(
    *,
    policy_alignment: Optional[Dict[str, Any]] = None,
    governance_snapshot: Optional[Dict[str, Any]] = None,
    mesh_session: Optional[Dict[str, Any]] = None,
    mesh_memberships: Optional[List[Dict[str, Any]]] = None,
    target_device_id: Optional[str] = None,
    force_local: bool = False,
    force_remote: bool = False,
    source_runtime_posture: Optional[str] = None,
    coordination_role: Optional[str] = None,
) -> tuple[Any, str]:  # (SourceDispatchMode, reason_str)
    """Select a :class:`~contracts.source_dispatch.SourceDispatchMode`.

    Decision priority:
    1. ``force_local`` — unconditionally choose ``local``.
    2. ``force_remote`` — unconditionally choose ``remote_handoff`` (requires
       ``target_device_id``).
    3. Policy alignment (PR-28) — if ``blocked`` flag set, choose ``blocked``.
    4. Policy alignment — if ``can_expand_cross_device`` and a
       ``target_device_id`` is available, choose ``remote_handoff``.
    5. Governance snapshot (PR-27) — if ``execution_allowed`` is False,
       choose ``blocked``.
    6. **PR-2 posture/coordination-role gate** — if the combined eligibility
       check (posture + coordination role) determines the source device is
       ineligible for local execution: if a ``target_device_id`` is available,
       choose ``remote_handoff``; otherwise choose ``blocked``.
    7. Mesh session (PR-33) with multiple active participants and no explicit
       target → ``staged_mesh``.
    8. Explicit target device → ``remote_handoff``.
    9. Fallback → ``local``.

    Parameters
    ----------
    policy_alignment:
        Serialised ``ExecutionPolicyAlignmentSurface`` dict (PR-28).
    governance_snapshot:
        Serialised ``RuntimeGovernanceSnapshot`` dict (PR-27).
    mesh_session:
        Serialised :class:`~contracts.mesh_session.MeshSession` dict (PR-33).
    mesh_memberships:
        List of serialised :class:`~contracts.mesh_membership.MeshMembership`
        dicts (PR-32).
    target_device_id:
        Explicit remote target device ID, if provided by the caller.
    force_local:
        When ``True``, always return ``local`` mode (bypasses posture gate).
    force_remote:
        When ``True``, always return ``remote_handoff`` mode (requires
        ``target_device_id``).
    source_runtime_posture:
        PR-2: source-device runtime participation posture.  When
        ``"control_only"``, local execution on the source device is blocked
        and the decision redirects to remote handoff or blocked.  When
        ``"join_runtime"`` (or ``None``/unknown), no additional gate is
        applied and the standard priority chain continues.
    coordination_role:
        PR-2 (PR-538 alignment): canonical coordination role string for the
        source device (e.g. ``"observer_only"``, ``"joined_runtime_participant"``).
        When provided alongside ``source_runtime_posture``, the combined
        eligibility check uses
        :func:`~core.source_execution_eligibility.check_source_eligibility_with_coordination_role`
        so that ``observer_only`` blocks execution even when posture is
        ``"join_runtime"``.  ``None`` falls back to posture alone.

    Returns
    -------
    (SourceDispatchMode, str)
        A tuple of the selected mode and a human-readable reason string.
    """
    from contracts.source_dispatch import SourceDispatchMode

    if force_local:
        return SourceDispatchMode.local, "force_local_requested"

    if force_remote:
        if target_device_id:
            return SourceDispatchMode.remote_handoff, "force_remote_requested"
        return SourceDispatchMode.local, "force_remote_requested_but_no_target:fallback_local"

    # Policy alignment checks (PR-28)
    if policy_alignment and isinstance(policy_alignment, dict):
        if policy_alignment.get("blocked"):
            return SourceDispatchMode.blocked, "policy_alignment:blocked"
        hints = policy_alignment.get("alignment_hints") or {}
        if isinstance(hints, dict):
            if not hints.get("can_execute_locally", True):
                if target_device_id:
                    return SourceDispatchMode.remote_handoff, "policy_alignment:local_not_allowed:remote_handoff"
                return SourceDispatchMode.blocked, "policy_alignment:local_not_allowed:no_target"
            if hints.get("can_expand_cross_device") and target_device_id:
                return SourceDispatchMode.remote_handoff, "policy_alignment:can_expand_cross_device"

    # Governance snapshot checks (PR-27)
    if governance_snapshot and isinstance(governance_snapshot, dict):
        if not governance_snapshot.get("execution_allowed", True):
            return SourceDispatchMode.blocked, "governance_snapshot:execution_not_allowed"

    # PR-2: posture + coordination-role gate.
    # Applied when source_runtime_posture OR coordination_role is explicitly
    # provided.  Callers that supply neither get pre-PR-2 behaviour (backwards
    # safety).  When coordination_role is available the combined check
    # (check_source_eligibility_with_coordination_role) is used so that, e.g.,
    # observer_only overrides a join_runtime posture.  When only posture is
    # provided the posture-only check is used.
    # Evaluated after policy/governance hard blocks but before mesh/default
    # paths so that posture actively redirects to a remote target when available.
    if source_runtime_posture is not None or coordination_role is not None:
        _eligible: bool
        _eligibility_reason: str
        if coordination_role is not None:
            try:
                from core.source_execution_eligibility import (
                    check_source_eligibility_with_coordination_role as _role_check,
                )
                _result = _role_check(source_runtime_posture, coordination_role)
                _eligible = _result.eligible
                _eligibility_reason = (
                    f"posture:{_result.posture}:role:{coordination_role}"
                )
            except Exception:  # noqa: BLE001
                # Fallback: treat observer_only as ineligible, others by posture.
                _eligible = (
                    coordination_role != "observer_only"
                    and source_runtime_posture != "control_only"
                )
                _eligibility_reason = (
                    f"posture_role_fallback:{source_runtime_posture}:{coordination_role}"
                )
        else:
            try:
                from core.source_execution_eligibility import (
                    is_source_eligible_for_local_execution as _posture_eligible,
                )
                _eligible = _posture_eligible(source_runtime_posture)
            except Exception:  # noqa: BLE001
                _eligible = source_runtime_posture != "control_only"
            _eligibility_reason = f"posture:{source_runtime_posture}"

        if not _eligible:
            # Source is ineligible — redirect to remote or block.
            if target_device_id:
                return (
                    SourceDispatchMode.remote_handoff,
                    f"{_eligibility_reason}:source_ineligible_for_local:remote_handoff",
                )
            return (
                SourceDispatchMode.blocked,
                f"{_eligibility_reason}:source_ineligible_for_local:no_remote_target",
            )

    # Mesh session: staged dispatch when multiple participants are active (PR-33)
    if mesh_session and isinstance(mesh_session, dict) and not target_device_id:
        participants = mesh_session.get("participants") or []
        # If there are 2+ active participants and no explicit target, suggest staged
        active_count = sum(
            1
            for p in participants
            if isinstance(p, dict) and p.get("status") in ("active", "ready", "joined")
        )
        if active_count >= 2:
            return SourceDispatchMode.staged_mesh, "mesh_session:multi_device_active"

    # Explicit target device → remote handoff
    if target_device_id:
        return SourceDispatchMode.remote_handoff, "target_device_specified"

    # Default: local (join_runtime or unknown posture — no posture gate)
    return SourceDispatchMode.local, "default_local"


# ---------------------------------------------------------------------------
# Target selection logic
# ---------------------------------------------------------------------------


def _score_candidate(
    session_id: str,
    device_id: str,
    *,
    readiness: Any,
    participation: Any,
    reuse_eligible: bool,
) -> Tuple[int, str]:
    """Score a single dispatch candidate using consolidated truth inputs.

    Scoring (higher is better, baseline 100):
      +20  reuse_eligible == True  (established reuse surface)

    Gate failures (readiness / participation) immediately return score=0 and
    a stable rejection reason string; they are not treated as score deductions.
    A rejected candidate (score=0 with a non-empty reason) must NOT be
    selected as a dispatch target.

    Returns ``(score, rejection_reason)`` where *rejection_reason* is an
    empty string when the candidate passes all required gates, or a stable
    reason string when the candidate must be rejected.
    """
    score = 100
    rejection: str = ""

    # --- Readiness gate (required) ---
    routable = getattr(readiness, "routable", None)
    registered = getattr(readiness, "registered", None)
    if readiness is None:
        rejection = "readiness:unavailable"
        return 0, rejection
    if not registered:
        rejection = "readiness:not_registered"
        return 0, rejection
    if not routable:
        rejection = "readiness:not_routable"
        return 0, rejection

    # --- Participation gate (required) ---
    if participation is None:
        rejection = "participation:unavailable"
        return 0, rejection
    if not getattr(participation, "orchestration_eligible", False):
        rejection = "participation:not_orchestration_eligible"
        return 0, rejection

    # --- Reuse preference (optional, contributes to score) ---
    if reuse_eligible:
        score += 20

    return score, rejection


def _select_target_from_candidates(
    *,
    registry: Any = None,
    readiness_inputs: Optional[Dict[str, Any]] = None,
    participation_inputs: Optional[Dict[str, Any]] = None,
    reuse_inputs: Optional[Dict[str, Any]] = None,
    mesh_session_id: Optional[str] = None,
) -> Optional[Any]:  # Optional[SourceDispatchTarget]
    """Select the best dispatch target from consolidated truth inputs.

    Implements PR-24 selection-truth consolidation: consults the attached
    runtime session registry as the authoritative active-session source, then
    gates each candidate through device readiness and device participation,
    and uses reuse eligibility as a preference signal for ranking.

    Per :data:`SELECTION_REGISTRY_IS_CANONICAL_GATE_PR24_POLICY` only
    sessions in ``active`` state from the registry are evaluated.

    Per :data:`SELECTION_READINESS_IS_REQUIRED_TRUTH_PR24_POLICY` and
    :data:`SELECTION_PARTICIPATION_IS_REQUIRED_TRUTH_PR24_POLICY` a candidate
    that fails either gate is rejected with a stable reason and is never
    returned as the selected target.

    Per :data:`SELECTION_REUSE_CONTRIBUTES_PREFERENCE_PR24_POLICY` reuse
    eligibility only contributes to scoring; it does not gate selection.

    Parameters
    ----------
    registry:
        Optional :class:`~core.attached_runtime_session_registry.AttachedSessionRegistry`
        override for test isolation.  Uses the process singleton when ``None``.
    readiness_inputs:
        Optional ``{device_id: DeviceReadinessSummary}`` dict for test
        isolation.  When ``None`` or a device is absent, the live
        :func:`~core.device_readiness.get_device_readiness` is called.
    participation_inputs:
        Optional ``{device_id: ParticipationSummary}`` dict for test
        isolation.  When ``None`` or a device is absent, the live
        :func:`~core.device_participation.get_device_participation` is called.
    reuse_inputs:
        Optional ``{device_id: bool}`` dict mapping device_id → reuse
        eligibility flag for test isolation.  When ``None`` or a device is
        absent, :func:`~core.attached_runtime_reuse_dispatch.resolve_reuse_dispatch_surface`
        is called.
    mesh_session_id:
        Mesh session ID to propagate onto the returned target, if available.

    Returns
    -------
    Optional[SourceDispatchTarget]
        The selected target with ``selection_reason`` set; ``None`` when no
        active sessions are found or all candidates are rejected.
    """
    from contracts.source_dispatch import SourceDispatchTarget

    # --- Step 1: Enumerate active sessions from the registry ---
    active_sessions: List[Any] = []
    try:
        from core.attached_runtime_session_registry import list_active_sessions

        active_sessions = list_active_sessions(registry=registry) or []
    except Exception as exc:  # noqa: BLE001
        logger.debug("_select_target_from_candidates: registry unavailable: %s", exc)
        return None

    if not active_sessions:
        logger.debug("_select_target_from_candidates: no active sessions in registry")
        return None

    # --- Step 2: Evaluate each candidate ---
    best_score: int = -1
    best_target: Optional[SourceDispatchTarget] = None

    for entry in active_sessions:
        device_id: str = str(getattr(entry, "device_id", "") or "")
        session_id: str = str(getattr(entry, "session_id", "") or "")
        runtime_id: Optional[str] = getattr(entry, "runtime_session_id", None)

        if not device_id:
            continue

        # Readiness — from inputs map or live lookup
        readiness: Any = None
        if readiness_inputs is not None:
            readiness = readiness_inputs.get(device_id)
        if readiness is None:
            try:
                from core.device_readiness import get_device_readiness

                readiness = get_device_readiness(device_id)
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "_select_target_from_candidates: readiness unavailable for %s: %s",
                    device_id,
                    exc,
                )

        # Participation — from inputs map or live lookup
        participation: Any = None
        if participation_inputs is not None:
            participation = participation_inputs.get(device_id)
        if participation is None:
            try:
                from core.device_participation import get_device_participation

                participation = get_device_participation(device_id)
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "_select_target_from_candidates: participation unavailable for %s: %s",
                    device_id,
                    exc,
                )

        # Reuse eligibility — from inputs map or live resolution
        reuse_eligible: bool = False
        if reuse_inputs is not None:
            reuse_eligible = bool(reuse_inputs.get(device_id, False))
        elif session_id or device_id:
            try:
                from core.attached_runtime_reuse_dispatch import (
                    ReuseDispatchResolutionKind,
                    resolve_reuse_dispatch_surface,
                )

                resolution = resolve_reuse_dispatch_surface(
                    session_id or "",
                    device_id,
                    registry=registry,
                )
                reuse_eligible = (
                    resolution.resolution_kind == ReuseDispatchResolutionKind.reused
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "_select_target_from_candidates: reuse unavailable for %s: %s",
                    device_id,
                    exc,
                )

        # Score the candidate
        score, rejection_reason = _score_candidate(
            session_id,
            device_id,
            readiness=readiness,
            participation=participation,
            reuse_eligible=reuse_eligible,
        )

        if rejection_reason:
            logger.debug(
                "_select_target_from_candidates: rejected device=%s reason=%s",
                device_id,
                rejection_reason,
            )
            continue

        if score > best_score:
            best_score = score
            reuse_tag = ":reuse_eligible" if reuse_eligible else ""
            best_target = SourceDispatchTarget(
                target_device_id=device_id,
                target_runtime_id=str(runtime_id) if runtime_id else None,
                target_session_id=session_id or None,
                mesh_session_id=mesh_session_id,
                selection_reason=(
                    f"registry:readiness:participation{reuse_tag}:score={score}"
                ),
                metadata={
                    "pr24_selection": True,
                    "score": score,
                    "reuse_eligible": reuse_eligible,
                },
            )

    return best_target


def select_dispatch_target(
    *,
    target_device_id: Optional[str] = None,
    target_runtime_id: Optional[str] = None,
    mesh_session: Optional[Dict[str, Any]] = None,
    mesh_memberships: Optional[List[Dict[str, Any]]] = None,
    handoff_envelope_id: Optional[str] = None,
    mesh_session_id: Optional[str] = None,
    # PR-24: consolidated truth inputs
    registry: Any = None,
    readiness_inputs: Optional[Dict[str, Any]] = None,
    participation_inputs: Optional[Dict[str, Any]] = None,
    reuse_inputs: Optional[Dict[str, Any]] = None,
) -> Optional[Any]:  # Optional[SourceDispatchTarget]
    """Select a :class:`~contracts.source_dispatch.SourceDispatchTarget`.

    Returns ``None`` when no remote/mesh target is applicable (local mode).

    PR-24 consolidation
    -------------------
    When no explicit ``target_device_id`` is supplied this function now
    consults the consolidated truth inputs — readiness, participation,
    registry, and reuse — instead of relying on ad-hoc first-active
    behaviour.  The selection priority is:

    1. Explicit ``target_device_id`` → ``selection_reason="explicit_target_device_id"``
    2. Registry + readiness + participation + reuse candidate selection
       (PR-24) → ``selection_reason="registry:readiness:participation[:reuse_eligible]:score=<N>"``
    3. Mesh session first-active participant (legacy fallback when registry /
       readiness / participation subsystems are unavailable)
       → ``selection_reason="mesh_session:first_active_participant:fallback"``

    Per :data:`SELECTION_REGISTRY_IS_CANONICAL_GATE_PR24_POLICY`, only
    registry-active sessions are eligible in path 2.
    Per :data:`SELECTION_READINESS_IS_REQUIRED_TRUTH_PR24_POLICY` and
    :data:`SELECTION_PARTICIPATION_IS_REQUIRED_TRUTH_PR24_POLICY`, a
    candidate failing either gate is rejected with a stable reason.
    Per :data:`SELECTION_REUSE_CONTRIBUTES_PREFERENCE_PR24_POLICY`, reuse
    eligibility contributes to the score but does not gate selection.

    Parameters
    ----------
    target_device_id:
        Explicit target device ID.
    target_runtime_id:
        Explicit target runtime ID.
    mesh_session:
        Serialised MeshSession dict (PR-33) for mesh-aware selection.
    mesh_memberships:
        List of serialised MeshMembership dicts (PR-32).
    handoff_envelope_id:
        Pre-built HandoffEnvelopeV2 ID, if available.
    mesh_session_id:
        Mesh session ID to record on the target.
    registry:
        PR-24: Optional :class:`~core.attached_runtime_session_registry.AttachedSessionRegistry`
        override for test isolation.
    readiness_inputs:
        PR-24: Optional ``{device_id: DeviceReadinessSummary}`` map for test
        isolation.
    participation_inputs:
        PR-24: Optional ``{device_id: ParticipationSummary}`` map for test
        isolation.
    reuse_inputs:
        PR-24: Optional ``{device_id: bool}`` reuse-eligibility map for test
        isolation.
    """
    from contracts.source_dispatch import SourceDispatchTarget

    if target_device_id:
        return SourceDispatchTarget(
            target_device_id=target_device_id,
            target_runtime_id=target_runtime_id,
            handoff_envelope_id=handoff_envelope_id,
            mesh_session_id=mesh_session_id or (
                mesh_session.get("session_id") if (mesh_session and isinstance(mesh_session, dict)) else None
            ),
            selection_reason="explicit_target_device_id",
        )

    # PR-24: consolidated truth-driven selection
    _effective_mesh_session_id = mesh_session_id or (
        mesh_session.get("session_id")
        if (mesh_session and isinstance(mesh_session, dict))
        else None
    )
    candidate_target = _select_target_from_candidates(
        registry=registry,
        readiness_inputs=readiness_inputs,
        participation_inputs=participation_inputs,
        reuse_inputs=reuse_inputs,
        mesh_session_id=_effective_mesh_session_id,
    )
    if candidate_target is not None:
        return candidate_target

    # Legacy fallback: extract first active participant from mesh session (PR-33)
    # Used when registry / readiness / participation subsystems are unavailable
    # and no candidate was selected by the consolidated truth path.
    if mesh_session and isinstance(mesh_session, dict):
        participants = mesh_session.get("participants") or []
        for p in participants:
            if not isinstance(p, dict):
                continue
            if p.get("status") in ("active", "ready", "joined"):
                device_id = p.get("device_id")
                runtime_id = p.get("runtime_id")
                if device_id:
                    return SourceDispatchTarget(
                        target_device_id=device_id,
                        target_runtime_id=runtime_id,
                        mesh_session_id=_effective_mesh_session_id,
                        selection_reason="mesh_session:first_active_participant:fallback",
                    )

    return None


# ---------------------------------------------------------------------------
# Plan building
# ---------------------------------------------------------------------------


def build_source_dispatch_plan(
    *,
    trace_id: Optional[str] = None,
    task_id: Optional[str] = None,
    session_id: Optional[str] = None,
    task: Optional[Dict[str, Any]] = None,
    source_device_id: Optional[str] = None,
    source_runtime_id: Optional[str] = None,
    target_device_id: Optional[str] = None,
    target_runtime_id: Optional[str] = None,
    policy_alignment: Optional[Dict[str, Any]] = None,
    governance_snapshot: Optional[Dict[str, Any]] = None,
    mesh_session: Optional[Dict[str, Any]] = None,
    mesh_memberships: Optional[List[Dict[str, Any]]] = None,
    force_local: bool = False,
    force_remote: bool = False,
    source_runtime_posture: Optional[str] = None,
    coordination_role: Optional[str] = None,
    # PR-24: consolidated truth inputs for target selection
    registry: Any = None,
    readiness_inputs: Optional[Dict[str, Any]] = None,
    participation_inputs: Optional[Dict[str, Any]] = None,
    reuse_inputs: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Any:  # SourceDispatchPlan
    """Build a :class:`~contracts.source_dispatch.SourceDispatchPlan`.

    Evaluates available context signals, selects a dispatch mode and target,
    pre-builds a :class:`~contracts.handoff_envelope_v2.HandoffEnvelopeV2`
    when remote handoff is selected, and assembles the plan.

    Parameters
    ----------
    trace_id:
        Distributed trace identifier.
    task_id:
        Task identifier.
    session_id:
        Source-side session identifier.
    task:
        Task specification dict (``{"tool_name": ..., "args": ...}``).
    source_device_id:
        Source device identifier.
    source_runtime_id:
        Source runtime identifier.
    target_device_id:
        Explicit remote target device ID, if known.
    target_runtime_id:
        Explicit remote target runtime ID, if known.
    policy_alignment:
        Serialised policy alignment dict (PR-28).  Fetched automatically
        when ``None``.
    governance_snapshot:
        Serialised governance snapshot dict (PR-27).  Fetched automatically
        when ``None``.
    mesh_session:
        Serialised mesh session dict (PR-33).  Fetched automatically when
        ``None``.
    mesh_memberships:
        Serialised mesh membership list (PR-32).  Fetched automatically when
        ``None``.
    force_local:
        Force local dispatch regardless of policy (bypasses posture gate).
    force_remote:
        Force remote handoff regardless of policy.
    source_runtime_posture:
        PR-2: source-device participation posture (``"control_only"`` or
        ``"join_runtime"``).  ``control_only`` gates local execution off on
        the source device; ``join_runtime`` allows it.  Defaults to
        ``"control_only"`` (conservative safe default) when ``None``.
    registry:
        PR-24: Optional :class:`~core.attached_runtime_session_registry.AttachedSessionRegistry`
        override for test isolation.  Forwarded to :func:`select_dispatch_target`.
    readiness_inputs:
        PR-24: Optional ``{device_id: DeviceReadinessSummary}`` map for test
        isolation.  Forwarded to :func:`select_dispatch_target`.
    participation_inputs:
        PR-24: Optional ``{device_id: ParticipationSummary}`` map for test
        isolation.  Forwarded to :func:`select_dispatch_target`.
    reuse_inputs:
        PR-24: Optional ``{device_id: bool}`` reuse-eligibility map for test
        isolation.  Forwarded to :func:`select_dispatch_target`.
    metadata:
        Arbitrary extension metadata.

    Returns
    -------
    SourceDispatchPlan
        Always returns a valid plan; degrades gracefully on any error.
    """
    from contracts.source_dispatch import (
        SourceDispatchMode,
        SourceDispatchPlan,
        build_source_dispatch_plan as _contract_build_plan,
        build_source_dispatch_decision,
    )

    try:
        # Auto-fetch context signals when not supplied
        if policy_alignment is None:
            policy_alignment = _try_policy_alignment()
        if governance_snapshot is None:
            governance_snapshot = _try_governance_snapshot()
        if mesh_session is None:
            mesh_session = _try_mesh_session()
        if mesh_memberships is None:
            mesh_memberships = _try_mesh_memberships()

        # Select mode — PR-2: pass source_runtime_posture and coordination_role
        # so the posture + coordination-role gate is evaluated inside
        # select_dispatch_mode().
        mode, reason = select_dispatch_mode(
            policy_alignment=policy_alignment,
            governance_snapshot=governance_snapshot,
            mesh_session=mesh_session,
            mesh_memberships=mesh_memberships,
            target_device_id=target_device_id,
            force_local=force_local,
            force_remote=force_remote,
            source_runtime_posture=source_runtime_posture,
            coordination_role=coordination_role,
        )

        # Select target — PR-24: pass consolidated truth inputs
        selected_target = None
        if mode in (SourceDispatchMode.remote_handoff, SourceDispatchMode.staged_mesh):
            selected_target = select_dispatch_target(
                target_device_id=target_device_id,
                target_runtime_id=target_runtime_id,
                mesh_session=mesh_session,
                mesh_memberships=mesh_memberships,
                registry=registry,
                readiness_inputs=readiness_inputs,
                participation_inputs=participation_inputs,
                reuse_inputs=reuse_inputs,
            )

        # Pre-build HandoffEnvelopeV2 for remote handoff
        handoff_envelope_dict: Optional[Dict[str, Any]] = None
        if mode == SourceDispatchMode.remote_handoff and selected_target is not None:
            try:
                from contracts.handoff_envelope_v2 import build_handoff_envelope_v2

                envelope = build_handoff_envelope_v2(
                    trace_id=trace_id,
                    task=task or {},
                    task_id=task_id,
                    session_id=session_id,
                    source_device_id=source_device_id,
                    target_device_id=selected_target.target_device_id,
                )
                handoff_envelope_dict = envelope.to_dict() if hasattr(envelope, "to_dict") else {}
                # Propagate the envelope ID back onto the target record
                if handoff_envelope_dict and handoff_envelope_dict.get("envelope_id"):
                    from contracts.source_dispatch import SourceDispatchTarget as _Target
                    selected_target = _Target(
                        target_device_id=selected_target.target_device_id,
                        target_runtime_id=selected_target.target_runtime_id,
                        target_session_id=selected_target.target_session_id,
                        handoff_envelope_id=handoff_envelope_dict.get("envelope_id"),
                        mesh_session_id=selected_target.mesh_session_id,
                        selection_reason=selected_target.selection_reason,
                        metadata=selected_target.metadata,
                    )
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "build_source_dispatch_plan: failed to pre-build HandoffEnvelopeV2: %s", exc
                )

        # Assess plan readiness
        ready = True
        readiness_notes: List[str] = []
        if mode == SourceDispatchMode.blocked:
            ready = False
            readiness_notes.append("mode:blocked — dispatch is not permitted")
        elif mode == SourceDispatchMode.unknown:
            ready = False
            readiness_notes.append("mode:unknown — could not determine dispatch mode")
        elif mode == SourceDispatchMode.remote_handoff and selected_target is None:
            ready = False
            readiness_notes.append("remote_handoff:no_target_selected")
        elif mode == SourceDispatchMode.staged_mesh and mesh_session is None:
            ready = False
            readiness_notes.append("staged_mesh:no_mesh_session_available")

        # Build the canonical decision record — pass posture through so it is
        # visible in the plan and any downstream audit surfaces.
        decision = build_source_dispatch_decision(
            trace_id=trace_id,
            task_id=task_id,
            session_id=session_id,
            source_device_id=source_device_id,
            source_runtime_id=source_runtime_id,
            mode=mode,
            selected_target=selected_target,
            decision_reason=reason,
            policy_alignment=policy_alignment,
            governance_snapshot=governance_snapshot,
            mesh_session=mesh_session,
            handoff_envelope=handoff_envelope_dict,
            source_runtime_posture=source_runtime_posture,
            metadata=metadata,
        )

        return _contract_build_plan(
            decision=decision,
            handoff_envelope=handoff_envelope_dict,
            mesh_session=mesh_session,
            ready=ready,
            readiness_notes=readiness_notes,
            metadata=metadata,
        )

    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "build_source_dispatch_plan: unexpected error: %s", exc
        )
        from contracts.source_dispatch import SourceDispatchPlan as _Plan, SourceDispatchMode as _Mode

        return _Plan(
            trace_id=trace_id,
            task_id=task_id,
            session_id=session_id,
            mode=_Mode.unknown,
            ready=False,
            readiness_notes=[f"build_error:{exc}"],
            metadata=metadata or {},
        )


# ---------------------------------------------------------------------------
# Orchestration entry point
# ---------------------------------------------------------------------------


def orchestrate_source_runtime_dispatch(
    *,
    trace_id: Optional[str] = None,
    task_id: Optional[str] = None,
    session_id: Optional[str] = None,
    task: Optional[Dict[str, Any]] = None,
    source_device_id: Optional[str] = None,
    source_runtime_id: Optional[str] = None,
    target_device_id: Optional[str] = None,
    target_runtime_id: Optional[str] = None,
    policy_alignment: Optional[Dict[str, Any]] = None,
    governance_snapshot: Optional[Dict[str, Any]] = None,
    mesh_session: Optional[Dict[str, Any]] = None,
    mesh_memberships: Optional[List[Dict[str, Any]]] = None,
    force_local: bool = False,
    force_remote: bool = False,
    source_runtime_posture: Optional[str] = None,
    coordination_role: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Any:  # SourceDispatchResult
    """End-to-end source dispatch orchestration.

    This is the canonical source-side entry point.  It:

    1. Builds a :class:`~contracts.source_dispatch.SourceDispatchPlan` by
       evaluating available governance/policy/mesh context.
    2. Executes according to the selected mode:

       - **local / fallback_local** — invokes ``OpenClawd._run_execution()``
         via :func:`_try_run_local_execution`.  Only executed when
         ``source_runtime_posture`` is ``"join_runtime"`` (or the posture
         gate is not triggered by ``force_local``).
       - **remote_handoff** — invokes ``galaxy_gateway.agent_bridge`` via
         :func:`_try_remote_handoff`; falls back to local on failure.
       - **staged_mesh** — returns the plan with a summary (full coordinator
         deferred to PR-37).
       - **blocked** — returns a failed result with ``mode=blocked``.  Also
         used when ``source_runtime_posture="control_only"`` and no remote
         target is available.
       - **unknown** — falls back to local with a warning note.

    3. Returns a fully-populated
       :class:`~contracts.source_dispatch.SourceDispatchResult` with
       execution trace / takeover result / error list as available.

    Parameters
    ----------
    trace_id:
        Distributed trace identifier.
    task_id:
        Task identifier.
    session_id:
        Source-side session identifier.
    task:
        Task specification dict.
    source_device_id:
        Source device identifier.
    source_runtime_id:
        Source runtime identifier.
    target_device_id:
        Explicit remote target device ID.
    target_runtime_id:
        Explicit remote target runtime ID.
    policy_alignment:
        Serialised policy alignment dict (PR-28).
    governance_snapshot:
        Serialised governance snapshot dict (PR-27).
    mesh_session:
        Serialised mesh session dict (PR-33).
    mesh_memberships:
        Serialised mesh membership list (PR-32).
    force_local:
        Force local dispatch (bypasses posture gate).
    force_remote:
        Force remote handoff.
    source_runtime_posture:
        PR-2: source-device participation posture (``"control_only"`` or
        ``"join_runtime"``).  Passed through to
        :func:`build_source_dispatch_plan` which feeds it into
        :func:`select_dispatch_mode` for eligibility gating.
    metadata:
        Arbitrary extension metadata.

    Returns
    -------
    SourceDispatchResult
        Always returns a valid result; degrades gracefully on any error.
    """
    from contracts.source_dispatch import (
        SourceDispatchMode,
        SourceDispatchResult,
        build_source_dispatch_result,
        failure_dispatch_result,
    )

    errors: List[str] = []

    try:
        # ---- Step 1: Build the dispatch plan --------------------------------
        plan = build_source_dispatch_plan(
            trace_id=trace_id,
            task_id=task_id,
            session_id=session_id,
            task=task,
            source_device_id=source_device_id,
            source_runtime_id=source_runtime_id,
            target_device_id=target_device_id,
            target_runtime_id=target_runtime_id,
            policy_alignment=policy_alignment,
            governance_snapshot=governance_snapshot,
            mesh_session=mesh_session,
            mesh_memberships=mesh_memberships,
            force_local=force_local,
            force_remote=force_remote,
            source_runtime_posture=source_runtime_posture,
            coordination_role=coordination_role,
            metadata=metadata,
        )

        mode = plan.mode
        selected_target = plan.selected_target
        handoff_env_dict = plan.handoff_envelope
        reason = (
            plan.readiness_notes[0]
            if plan.readiness_notes and mode in (SourceDispatchMode.blocked, SourceDispatchMode.unknown)
            else None
        )
        # Retrieve decision reason from plan metadata if available
        decision_reason: Optional[str] = reason
        if decision_reason is None and plan.dispatch_id:
            # Attempt to extract from governance snapshot or policy alignment
            decision_reason = _extract_decision_reason(plan)

        # ---- Step 2: Execute ------------------------------------------------
        exec_result: Optional[Dict[str, Any]] = None
        takeover_result_dict: Optional[Dict[str, Any]] = None
        execution_trace: Optional[Dict[str, Any]] = None
        success = False
        effective_mode = mode

        if mode == SourceDispatchMode.blocked:
            # PR-2: blocked includes posture:control_only:no_remote_target case.
            _blocked_reason = decision_reason or "dispatch_blocked_by_policy"
            errors.append(_blocked_reason)
            return build_source_dispatch_result(
                dispatch_id=plan.dispatch_id,
                trace_id=trace_id,
                task_id=task_id,
                session_id=session_id,
                source_device_id=source_device_id,
                source_runtime_id=source_runtime_id,
                mode=mode,
                selected_target=selected_target,
                success=False,
                errors=errors + plan.readiness_notes,
                decision_reason=_blocked_reason,
                governance_snapshot=plan.governance_snapshot,
                policy_alignment=plan.policy_alignment,
                mesh_session=plan.mesh_session,
                source_runtime_posture=source_runtime_posture,
                metadata=metadata,
            )

        elif mode == SourceDispatchMode.remote_handoff:
            if selected_target is not None and handoff_env_dict is not None:
                # Attempt remote handoff
                try:
                    from contracts.handoff_envelope_v2 import HandoffEnvelopeV2

                    envelope_obj = HandoffEnvelopeV2.model_validate(handoff_env_dict)
                    bridge_resp = _try_remote_handoff(envelope_obj)
                    if bridge_resp.get("success"):
                        exec_result = bridge_resp
                        success = True
                        decision_reason = decision_reason or "remote_handoff:success"
                        # Extract takeover result if present
                        if "takeover_result" in bridge_resp:
                            takeover_result_dict = bridge_resp["takeover_result"]
                    else:
                        # Remote failed — fall back to local
                        errors.append(
                            "remote_handoff_failed:"
                            + bridge_resp.get("skipped_reason", "unknown")
                        )
                        effective_mode = SourceDispatchMode.fallback_local
                        decision_reason = "remote_handoff_failed:fallback_local"
                        logger.debug(
                            "orchestrate_source_runtime_dispatch: "
                            "remote handoff failed; falling back to local"
                        )
                        # Fall through to local execution below
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"remote_handoff_error:{exc}")
                    effective_mode = SourceDispatchMode.fallback_local
                    decision_reason = f"remote_handoff_error:fallback_local:{exc}"
            else:
                errors.append("remote_handoff:no_target_or_envelope")
                effective_mode = SourceDispatchMode.fallback_local
                decision_reason = "remote_handoff:no_target_or_envelope:fallback_local"

        elif mode == SourceDispatchMode.staged_mesh:
            # Staged mesh: return the plan summary; full coordinator deferred to PR-37
            success = True
            exec_result = {
                "action_taken": "staged_mesh_plan_prepared",
                "success": True,
                "mesh_session_id": (
                    plan.mesh_session.get("session_id") if plan.mesh_session else None
                ),
                "note": (
                    "Staged mesh dispatch plan prepared. "
                    "Full Mesh Session Coordinator execution deferred to PR-37."
                ),
            }
            decision_reason = decision_reason or "staged_mesh:plan_prepared"
            return build_source_dispatch_result(
                dispatch_id=plan.dispatch_id,
                trace_id=trace_id,
                task_id=task_id,
                session_id=session_id,
                source_device_id=source_device_id,
                source_runtime_id=source_runtime_id,
                mode=effective_mode,
                selected_target=selected_target,
                success=success,
                result=exec_result,
                governance_snapshot=plan.governance_snapshot,
                policy_alignment=plan.policy_alignment,
                mesh_session=plan.mesh_session,
                errors=errors,
                decision_reason=decision_reason,
                source_runtime_posture=source_runtime_posture,
                metadata=metadata,
            )

        # Local execution (local / fallback_local / unknown)
        if not success:
            state_continuum = _build_state_continuum(
                trace_id=trace_id,
                task_id=task_id,
                session_id=session_id,
                task=task,
                source_device_id=source_device_id,
            )
            exec_output = _try_run_local_execution(
                state_continuum,
                entry_mode="local",
            )
            exec_result = exec_output
            success = bool(exec_output.get("success", False))
            if not success and not errors:
                errors.append(
                    exec_output.get("skipped_reason", "local_execution_failed")
                )
            decision_reason = decision_reason or (
                "local_execution:success" if success else "local_execution:failed"
            )

        # ---- Step 3: Build result -------------------------------------------
        return build_source_dispatch_result(
            dispatch_id=plan.dispatch_id,
            trace_id=trace_id,
            task_id=task_id,
            session_id=session_id,
            source_device_id=source_device_id,
            source_runtime_id=source_runtime_id,
            mode=effective_mode,
            selected_target=selected_target,
            success=success,
            result=exec_result,
            execution_trace=execution_trace,
            takeover_result=takeover_result_dict,
            governance_snapshot=plan.governance_snapshot,
            policy_alignment=plan.policy_alignment,
            mesh_session=plan.mesh_session,
            errors=errors,
            decision_reason=decision_reason,
            source_runtime_posture=source_runtime_posture,
            metadata=metadata,
        )

    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "orchestrate_source_runtime_dispatch: unexpected error: %s", exc
        )
        return failure_dispatch_result(
            trace_id=trace_id,
            task_id=task_id,
            session_id=session_id,
            mode=SourceDispatchMode.unknown,
            reason=f"orchestration_error:{exc}",
            metadata=metadata,
        )


# ---------------------------------------------------------------------------
# Internal helpers for orchestration
# ---------------------------------------------------------------------------


def _build_state_continuum(
    *,
    trace_id: Optional[str] = None,
    task_id: Optional[str] = None,
    session_id: Optional[str] = None,
    task: Optional[Dict[str, Any]] = None,
    source_device_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a minimal state-continuum dict for local execution."""
    return {
        "trace_id": trace_id or str(uuid.uuid4()),
        "task_id": task_id,
        "session_id": session_id,
        "task": task or {},
        "source_device_id": source_device_id,
        "entry_mode": "local",
    }


def _extract_decision_reason(plan: Any) -> Optional[str]:
    """Extract a decision reason string from a plan object, if available."""
    try:
        # Check if plan has an associated decision reason via metadata
        meta = getattr(plan, "metadata", None)
        if meta and isinstance(meta, dict):
            return meta.get("decision_reason")
    except Exception:  # noqa: BLE001
        pass
    return None


# ---------------------------------------------------------------------------
# SourceDispatchOrchestrator — stateless handler class
# ---------------------------------------------------------------------------


class SourceDispatchOrchestrator:
    """Stateless source-side dispatch orchestrator.

    Wraps :func:`orchestrate_source_runtime_dispatch` in a reusable,
    testable class.  The orchestrator holds no mutable state; it is safe
    to instantiate multiple times and to call from multiple threads.

    Usage::

        from core.runtime.source_dispatch_orchestrator import SourceDispatchOrchestrator

        orchestrator = SourceDispatchOrchestrator()
        result = orchestrator.dispatch(
            trace_id="trace_abc",
            task={"tool_name": "screenshot", "args": {}},
            task_id="task_001",
        )
        payload = result.to_dict()
    """

    def dispatch(
        self,
        *,
        trace_id: Optional[str] = None,
        task_id: Optional[str] = None,
        session_id: Optional[str] = None,
        task: Optional[Dict[str, Any]] = None,
        source_device_id: Optional[str] = None,
        source_runtime_id: Optional[str] = None,
        target_device_id: Optional[str] = None,
        target_runtime_id: Optional[str] = None,
        policy_alignment: Optional[Dict[str, Any]] = None,
        governance_snapshot: Optional[Dict[str, Any]] = None,
        mesh_session: Optional[Dict[str, Any]] = None,
        mesh_memberships: Optional[List[Dict[str, Any]]] = None,
        force_local: bool = False,
        force_remote: bool = False,
        source_runtime_posture: Optional[str] = None,
        coordination_role: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Any:  # SourceDispatchResult
        """Execute the end-to-end source dispatch orchestration.

        Delegates to :func:`orchestrate_source_runtime_dispatch`.

        Parameters
        ----------
        See :func:`orchestrate_source_runtime_dispatch` for full parameter
        documentation.  ``source_runtime_posture`` is the PR-2 posture gate
        parameter: ``"control_only"`` blocks local execution; ``"join_runtime"``
        allows it.  ``coordination_role`` is the PR-2/PR-538 alignment
        parameter: ``"observer_only"`` blocks local execution regardless of
        posture; ``"joined_runtime_participant"`` grants eligibility.

        Returns
        -------
        SourceDispatchResult
            Always returns a valid result.
        """
        return orchestrate_source_runtime_dispatch(
            trace_id=trace_id,
            task_id=task_id,
            session_id=session_id,
            task=task,
            source_device_id=source_device_id,
            source_runtime_id=source_runtime_id,
            target_device_id=target_device_id,
            target_runtime_id=target_runtime_id,
            policy_alignment=policy_alignment,
            governance_snapshot=governance_snapshot,
            mesh_session=mesh_session,
            mesh_memberships=mesh_memberships,
            force_local=force_local,
            force_remote=force_remote,
            source_runtime_posture=source_runtime_posture,
            coordination_role=coordination_role,
            metadata=metadata,
        )

    def plan(
        self,
        *,
        trace_id: Optional[str] = None,
        task_id: Optional[str] = None,
        session_id: Optional[str] = None,
        task: Optional[Dict[str, Any]] = None,
        source_device_id: Optional[str] = None,
        source_runtime_id: Optional[str] = None,
        target_device_id: Optional[str] = None,
        target_runtime_id: Optional[str] = None,
        policy_alignment: Optional[Dict[str, Any]] = None,
        governance_snapshot: Optional[Dict[str, Any]] = None,
        mesh_session: Optional[Dict[str, Any]] = None,
        mesh_memberships: Optional[List[Dict[str, Any]]] = None,
        force_local: bool = False,
        force_remote: bool = False,
        source_runtime_posture: Optional[str] = None,
        coordination_role: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Any:  # SourceDispatchPlan
        """Build a dispatch plan without executing.

        Delegates to :func:`build_source_dispatch_plan`.

        Returns
        -------
        SourceDispatchPlan
            Always returns a valid plan.
        """
        return build_source_dispatch_plan(
            trace_id=trace_id,
            task_id=task_id,
            session_id=session_id,
            task=task,
            source_device_id=source_device_id,
            source_runtime_id=source_runtime_id,
            target_device_id=target_device_id,
            target_runtime_id=target_runtime_id,
            policy_alignment=policy_alignment,
            governance_snapshot=governance_snapshot,
            mesh_session=mesh_session,
            mesh_memberships=mesh_memberships,
            force_local=force_local,
            force_remote=force_remote,
            source_runtime_posture=source_runtime_posture,
            coordination_role=coordination_role,
            metadata=metadata,
        )
