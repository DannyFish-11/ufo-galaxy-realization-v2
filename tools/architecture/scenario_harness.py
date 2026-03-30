"""tools/architecture/scenario_harness.py — Scenario Stress Harness and Control-Loop Simulation
Infrastructure (PR-35)

**Architectural Intent**
------------------------
This module provides a replayable, maintainable simulation harness for
exercising the unified control loop under realistic multi-step scenarios.  It
composes the canonical artifact layers—routing, degraded-operation envelopes,
decision timelines, operator overrides, permission/trust state, and source
recovery—into coherent end-to-end scenario flows.

**Architecture boundaries**
The harness is a *consumer* of canonical artifacts.  It:
- reads from and writes to the canonical state machines using their published
  builder APIs,
- validates outcomes via assertions against canonical artifacts only,
- never invents shadow state or duplicate truth paths.

**Components**
--------------
:class:`ScenarioStepKind`
    Enum of scenario step types (source health changes, route decisions,
    permission changes, operator overrides, recovery cycles, …).

:class:`ScenarioStep`
    A single named step specification with step kind, input params, and
    expected outcome declarations.

:class:`ScenarioState`
    Accumulated canonical state across a running scenario: source registry
    snapshot, current route dict, degraded-operation envelope, permission
    safety snapshot, operator override snapshot, decision timeline snapshot,
    and recovery snapshot.

:class:`ScenarioFixture`
    Static factory methods for common scenario configurations (healthy native
    multimodal, degraded fallback, source unavailable, …).

:class:`ScenarioSimulator`
    Executes a sequence of :class:`ScenarioStep` objects against the canonical
    state machines, accumulates :class:`ScenarioState` at each step, and
    returns a :class:`ScenarioResult`.

:class:`ScenarioResult`
    Ordered list of per-step state snapshots plus summary flags suitable for
    regression assertions.

:class:`ScenarioAssertions`
    Static assertion helpers targeting canonical artifacts (never log text).

Usage::

    from tools.architecture.scenario_harness import (
        ScenarioFixture,
        ScenarioSimulator,
        ScenarioAssertions,
    )

    steps = [
        ScenarioFixture.healthy_native_multimodal_step(),
        ScenarioFixture.provider_degradation_step("gpt4o"),
        ScenarioFixture.expect_text_only_fallback_step(),
    ]
    result = ScenarioSimulator().run(steps)
    ScenarioAssertions.assert_degraded_to_text_only(result.steps[-1].state)
    ScenarioAssertions.assert_timeline_ordered(result.steps[-1].state)
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module-file direct loader — bypasses package __init__ to avoid pulling in
# heavy optional dependencies (e.g. numpy) that live in
# core/multimodal/__init__.py but are not required by the modules we use.
# ---------------------------------------------------------------------------

def _load_module_from_file(dotted_name: str) -> Any:
    """Return the module object for *dotted_name* by loading it directly from
    the source file, completely bypassing any package-level ``__init__.py``.

    Falls back to a normal ``importlib.import_module`` call when the source
    file cannot be resolved (e.g., in an installed-package environment).
    """
    import importlib
    import importlib.util
    import os as _os
    import sys as _sys

    # Return immediately if already cached
    if dotted_name in _sys.modules:
        return _sys.modules[dotted_name]

    # Locate the .py source file relative to *this* file's directory.
    # This file lives at tools/architecture/scenario_harness.py, so the
    # project root is two levels up.
    parts = dotted_name.split(".")
    this_dir = _os.path.dirname(_os.path.abspath(__file__))
    project_root = _os.path.dirname(_os.path.dirname(this_dir))
    candidate = _os.path.join(project_root, *parts) + ".py"

    if not _os.path.isfile(candidate):
        # Fallback: standard import (may trigger package __init__)
        return importlib.import_module(dotted_name)

    spec = importlib.util.spec_from_file_location(dotted_name, candidate)
    if spec is None or spec.loader is None:
        return importlib.import_module(dotted_name)

    module = importlib.util.module_from_spec(spec)
    _sys.modules[dotted_name] = module
    try:
        spec.loader.exec_module(module)  # type: ignore[attr-defined]
    except Exception:
        # Remove from cache on failure so repeated calls can retry
        _sys.modules.pop(dotted_name, None)
        raise
    return module


# ---------------------------------------------------------------------------
# ScenarioStepKind
# ---------------------------------------------------------------------------


class ScenarioStepKind(str, Enum):
    """Taxonomy of operations that a scenario step can perform."""

    REGISTER_SOURCE = "register_source"
    """Register a new perception source in the registry."""

    MARK_SOURCE_HEALTHY = "mark_source_healthy"
    """Restore a previously degraded or unavailable source to healthy."""

    MARK_SOURCE_DEGRADED = "mark_source_degraded"
    """Simulate source degradation."""

    MARK_SOURCE_UNAVAILABLE = "mark_source_unavailable"
    """Simulate source hardware/network failure."""

    SELECT_MULTIMODAL_ROUTE = "select_multimodal_route"
    """Simulate a routing decision (native multimodal, partial, or text-only)."""

    PROVIDER_DEGRADATION = "provider_degradation"
    """Signal that a named provider is degraded, triggering failover."""

    PERMISSION_CHANGE = "permission_change"
    """Change the permission status of one or more modalities."""

    APPLY_OPERATOR_OVERRIDE = "apply_operator_override"
    """Commit an operator override set."""

    CLEAR_OPERATOR_OVERRIDE = "clear_operator_override"
    """Clear the active operator override."""

    RUN_SOURCE_RECOVERY_CYCLE = "run_source_recovery_cycle"
    """Run a full source recovery/re-election cycle."""

    BUILD_PERMISSION_SNAPSHOT = "build_permission_snapshot"
    """Rebuild the permission/trust safety snapshot from current state."""

    RECORD_TIMELINE_EVENT = "record_timeline_event"
    """Explicitly record a named decision event to the timeline."""

    BUILD_EXPLAINABILITY_SNAPSHOT = "build_explainability_snapshot"
    """Build an explainability snapshot from the current timeline."""

    ASSERT_CHECKPOINT = "assert_checkpoint"
    """Declarative assertion step — validates state without mutation."""


# ---------------------------------------------------------------------------
# ScenarioState
# ---------------------------------------------------------------------------


@dataclass
class ScenarioState:
    """Accumulated canonical state at a single point in a scenario run.

    All fields hold raw serialised dicts (the canonical ``to_dict()`` output)
    or ``None`` when the artifact has not yet been produced.  This makes the
    state JSON-serialisable and trivially comparable for regression detection.
    """

    step_index: int = 0
    step_name: str = ""
    step_kind: str = ""
    timestamp: float = field(default_factory=time.time)

    # Canonical artifact snapshots produced up to and including this step
    source_registry_snapshot: Optional[Dict[str, Any]] = None
    route_dict: Optional[Dict[str, Any]] = None
    degraded_operation_envelope: Optional[Dict[str, Any]] = None
    permission_safety_snapshot: Optional[Dict[str, Any]] = None
    operator_override_snapshot: Optional[Dict[str, Any]] = None
    decision_timeline_snapshot: Optional[Dict[str, Any]] = None
    source_recovery_snapshot: Optional[Dict[str, Any]] = None

    # Step outcome metadata
    outcome_notes: List[str] = field(default_factory=list)
    assertions_passed: List[str] = field(default_factory=list)
    assertions_failed: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_index": self.step_index,
            "step_name": self.step_name,
            "step_kind": self.step_kind,
            "timestamp": self.timestamp,
            "source_registry_snapshot": self.source_registry_snapshot,
            "route_dict": self.route_dict,
            "degraded_operation_envelope": self.degraded_operation_envelope,
            "permission_safety_snapshot": self.permission_safety_snapshot,
            "operator_override_snapshot": self.operator_override_snapshot,
            "decision_timeline_snapshot": self.decision_timeline_snapshot,
            "source_recovery_snapshot": self.source_recovery_snapshot,
            "outcome_notes": list(self.outcome_notes),
            "assertions_passed": list(self.assertions_passed),
            "assertions_failed": list(self.assertions_failed),
        }


# ---------------------------------------------------------------------------
# ScenarioStep
# ---------------------------------------------------------------------------


@dataclass
class ScenarioStep:
    """A single named, replayable step in a scenario.

    Parameters
    ----------
    name:
        Human-readable name used in assertion messages and logs.
    kind:
        :class:`ScenarioStepKind` enum value.
    params:
        Free-form dict of step-specific parameters consumed by the simulator.
    expected_route_type:
        When set, the simulator will assert that ``route_dict["route_type"]``
        matches this value after the step.
    expected_degraded:
        When ``True``, the simulator will assert that the degraded-operation
        envelope's ``is_degraded`` flag is ``True``.
    expected_timeline_min_events:
        Minimum number of timeline events expected after this step.
    expected_has_active_override:
        When not ``None``, asserts whether the override snapshot has an active
        override.
    """

    name: str
    kind: ScenarioStepKind
    params: Dict[str, Any] = field(default_factory=dict)

    # Declarative outcome assertions (all optional)
    expected_route_type: Optional[str] = None
    expected_degraded: Optional[bool] = None
    expected_timeline_min_events: Optional[int] = None
    expected_has_active_override: Optional[bool] = None


# ---------------------------------------------------------------------------
# ScenarioResult
# ---------------------------------------------------------------------------


@dataclass
class ScenarioResult:
    """Output of :meth:`ScenarioSimulator.run`.

    Attributes
    ----------
    steps:
        Ordered list of :class:`ScenarioState` objects — one per executed step.
    scenario_id:
        UUID for this scenario run (useful for log correlation).
    total_steps:
        Total number of steps executed (including assertion-only steps).
    degradation_occurred:
        ``True`` if any step produced an ``is_degraded=True`` envelope.
    recovery_occurred:
        ``True`` if any step's recovery cycle produced a re-election event.
    override_was_active:
        ``True`` if any step had an active operator override.
    timeline_event_count:
        Total timeline events emitted across all steps.
    failed_assertions:
        Flat list of all assertion failure messages across all steps.
    """

    steps: List[ScenarioState] = field(default_factory=list)
    scenario_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    total_steps: int = 0
    degradation_occurred: bool = False
    recovery_occurred: bool = False
    override_was_active: bool = False
    timeline_event_count: int = 0
    failed_assertions: List[str] = field(default_factory=list)

    @property
    def all_assertions_passed(self) -> bool:
        return len(self.failed_assertions) == 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "total_steps": self.total_steps,
            "degradation_occurred": self.degradation_occurred,
            "recovery_occurred": self.recovery_occurred,
            "override_was_active": self.override_was_active,
            "timeline_event_count": self.timeline_event_count,
            "failed_assertions": list(self.failed_assertions),
            "steps": [s.to_dict() for s in self.steps],
        }


# ---------------------------------------------------------------------------
# ScenarioFixture — static factory methods for common scenarios
# ---------------------------------------------------------------------------


class ScenarioFixture:
    """Static factory methods returning pre-configured :class:`ScenarioStep`
    lists for common scenario patterns.

    Using fixtures keeps individual test methods short and the scenario
    definitions reusable and understandable.
    """

    # -- Source registration helpers ----------------------------------------

    @staticmethod
    def register_audio_source(
        source_id: str = "mic_builtin",
        display_name: str = "System Microphone",
        healthy: bool = True,
    ) -> ScenarioStep:
        return ScenarioStep(
            name=f"register_audio_{source_id}",
            kind=ScenarioStepKind.REGISTER_SOURCE,
            params={
                "source_id": source_id,
                "source_type": "microphone",
                "modality": "audio",
                "display_name": display_name,
                "healthy": healthy,
            },
        )

    @staticmethod
    def register_video_source(
        source_id: str = "cam_builtin",
        display_name: str = "System Camera",
        healthy: bool = True,
    ) -> ScenarioStep:
        return ScenarioStep(
            name=f"register_video_{source_id}",
            kind=ScenarioStepKind.REGISTER_SOURCE,
            params={
                "source_id": source_id,
                "source_type": "webcam",
                "modality": "video",
                "display_name": display_name,
                "healthy": healthy,
            },
        )

    # -- Route selection helpers ---------------------------------------------

    @staticmethod
    def healthy_native_multimodal_step(
        provider: str = "gpt4o",
        trace_id: Optional[str] = None,
    ) -> ScenarioStep:
        return ScenarioStep(
            name="route_native_multimodal",
            kind=ScenarioStepKind.SELECT_MULTIMODAL_ROUTE,
            params={
                "route_type": "native_multimodal",
                "is_native_multimodal": True,
                "provider": provider,
                "model": f"{provider}-latest",
                "route_reason": "native_multimodal_capable",
                "fallback_reason": None,
                "trace_id": trace_id or f"trace_{uuid.uuid4().hex[:8]}",
            },
            expected_route_type="native_multimodal",
            expected_degraded=False,
        )

    @staticmethod
    def text_only_fallback_step(
        provider: str = "gpt4o",
        fallback_reason: str = "provider_degraded",
        trace_id: Optional[str] = None,
    ) -> ScenarioStep:
        return ScenarioStep(
            name="route_text_only_fallback",
            kind=ScenarioStepKind.SELECT_MULTIMODAL_ROUTE,
            params={
                "route_type": "text_only",
                "is_native_multimodal": False,
                "provider": provider,
                "model": f"{provider}-text",
                "route_reason": "native_multimodal_unavailable",
                "fallback_reason": fallback_reason,
                "trace_id": trace_id or f"trace_{uuid.uuid4().hex[:8]}",
            },
            expected_route_type="text_only",
            expected_degraded=True,
        )

    @staticmethod
    def partial_multimodal_step(
        provider: str = "claude3",
        trace_id: Optional[str] = None,
    ) -> ScenarioStep:
        return ScenarioStep(
            name="route_partial_multimodal",
            kind=ScenarioStepKind.SELECT_MULTIMODAL_ROUTE,
            params={
                "route_type": "partial_multimodal",
                "is_native_multimodal": False,
                "provider": provider,
                "model": f"{provider}-latest",
                "route_reason": "native_mm_degraded_partial_fallback",
                "fallback_reason": "provider_partial_capability",
                "trace_id": trace_id or f"trace_{uuid.uuid4().hex[:8]}",
            },
            expected_route_type="partial_multimodal",
            expected_degraded=True,
        )

    # -- Provider degradation helpers ----------------------------------------

    @staticmethod
    def provider_degradation_step(provider: str = "gpt4o") -> ScenarioStep:
        return ScenarioStep(
            name=f"provider_degraded_{provider}",
            kind=ScenarioStepKind.PROVIDER_DEGRADATION,
            params={"provider": provider, "degradation_reason": "health_check_failed"},
        )

    # -- Source failure/recovery helpers ------------------------------------

    @staticmethod
    def mark_source_unavailable_step(source_id: str) -> ScenarioStep:
        return ScenarioStep(
            name=f"source_unavailable_{source_id}",
            kind=ScenarioStepKind.MARK_SOURCE_UNAVAILABLE,
            params={"source_id": source_id},
        )

    @staticmethod
    def mark_source_degraded_step(source_id: str) -> ScenarioStep:
        return ScenarioStep(
            name=f"source_degraded_{source_id}",
            kind=ScenarioStepKind.MARK_SOURCE_DEGRADED,
            params={"source_id": source_id},
        )

    @staticmethod
    def mark_source_healthy_step(source_id: str) -> ScenarioStep:
        return ScenarioStep(
            name=f"source_recovered_{source_id}",
            kind=ScenarioStepKind.MARK_SOURCE_HEALTHY,
            params={"source_id": source_id},
        )

    @staticmethod
    def run_recovery_cycle_step() -> ScenarioStep:
        return ScenarioStep(
            name="run_source_recovery_cycle",
            kind=ScenarioStepKind.RUN_SOURCE_RECOVERY_CYCLE,
            params={},
        )

    # -- Permission helpers --------------------------------------------------

    @staticmethod
    def permission_denied_step(modality: str = "audio") -> ScenarioStep:
        return ScenarioStep(
            name=f"permission_denied_{modality}",
            kind=ScenarioStepKind.PERMISSION_CHANGE,
            params={"modality": modality, "permission_status": "denied"},
        )

    @staticmethod
    def permission_granted_step(modality: str = "audio") -> ScenarioStep:
        return ScenarioStep(
            name=f"permission_granted_{modality}",
            kind=ScenarioStepKind.PERMISSION_CHANGE,
            params={"modality": modality, "permission_status": "granted"},
        )

    @staticmethod
    def permission_unavailable_step(modality: str = "video") -> ScenarioStep:
        return ScenarioStep(
            name=f"permission_unavailable_{modality}",
            kind=ScenarioStepKind.PERMISSION_CHANGE,
            params={"modality": modality, "permission_status": "unavailable"},
        )

    # -- Operator override helpers -------------------------------------------

    @staticmethod
    def apply_force_text_only_override_step(reason: str = "operator_test") -> ScenarioStep:
        return ScenarioStep(
            name="operator_override_force_text_only",
            kind=ScenarioStepKind.APPLY_OPERATOR_OVERRIDE,
            params={
                "multimodal_mode": "force_off",
                "override_reason": reason,
            },
            expected_has_active_override=True,
        )

    @staticmethod
    def apply_provider_lock_override_step(
        provider: str = "claude3",
        model: Optional[str] = None,
    ) -> ScenarioStep:
        return ScenarioStep(
            name=f"operator_override_lock_{provider}",
            kind=ScenarioStepKind.APPLY_OPERATOR_OVERRIDE,
            params={
                "preferred_provider": provider,
                "preferred_model": model,
                "override_reason": "operator_provider_lock",
            },
            expected_has_active_override=True,
        )

    @staticmethod
    def clear_operator_override_step() -> ScenarioStep:
        return ScenarioStep(
            name="operator_override_clear",
            kind=ScenarioStepKind.CLEAR_OPERATOR_OVERRIDE,
            params={},
            expected_has_active_override=False,
        )

    # -- Explainability helpers ----------------------------------------------

    @staticmethod
    def build_explainability_snapshot_step() -> ScenarioStep:
        return ScenarioStep(
            name="build_explainability_snapshot",
            kind=ScenarioStepKind.BUILD_EXPLAINABILITY_SNAPSHOT,
            params={},
        )


# ---------------------------------------------------------------------------
# ScenarioSimulator
# ---------------------------------------------------------------------------


class ScenarioSimulator:
    """Executes a sequence of :class:`ScenarioStep` objects against the
    canonical state machines, accumulating :class:`ScenarioState` at each
    step.

    The simulator maintains lightweight in-process state (a
    :class:`~core.multimodal.perception_source_registry.PerceptionSourceRegistry`
    and a local permission-override table) so that successive steps observe
    each other's effects without requiring a live runtime.

    Usage::

        sim = ScenarioSimulator()
        result = sim.run(steps)
        assert result.all_assertions_passed
    """

    def __init__(self) -> None:
        # Load the module directly from file to avoid pulling in numpy via
        # core/multimodal/__init__.py (which imports audio_features.py).
        _psr = _load_module_from_file(
            "core.multimodal.perception_source_registry"
        )
        PerceptionSourceRegistry = _psr.PerceptionSourceRegistry
        PerceptionSourceType = _psr.PerceptionSourceType
        SourceModality = _psr.SourceModality

        self._registry = PerceptionSourceRegistry()
        self._PerceptionSourceType = PerceptionSourceType
        self._SourceModality = SourceModality

        # Soft permission table: {modality -> "granted" | "denied" | "unavailable"}
        self._permission_table: Dict[str, str] = {}

        # Current canonical state
        self._current_route: Optional[Dict[str, Any]] = None
        self._prior_envelope: Optional[Dict[str, Any]] = None
        self._current_override_snapshot: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, steps: List[ScenarioStep]) -> ScenarioResult:
        """Execute *steps* in order and return a :class:`ScenarioResult`."""
        from core.decision_timeline import (
            get_decision_timeline,
            reset_decision_timeline,
        )
        from core.operator_override import (
            get_operator_override_state,
            reset_operator_override_state,
        )
        _srp = _load_module_from_file("core.multimodal.source_recovery_policy")
        get_source_recovery_policy = _srp.get_source_recovery_policy
        reset_source_recovery_policy = _srp.reset_source_recovery_policy

        # Start with clean singletons for this scenario run
        reset_decision_timeline()
        reset_operator_override_state()
        reset_source_recovery_policy()

        result = ScenarioResult(total_steps=len(steps))
        accumulated_state = ScenarioState()

        for idx, step in enumerate(steps):
            state = ScenarioState(
                step_index=idx,
                step_name=step.name,
                step_kind=step.kind.value,
            )
            try:
                self._execute_step(step, state)
            except Exception as exc:
                logger.warning(
                    "ScenarioSimulator: step %d (%s) raised unexpectedly: %s",
                    idx,
                    step.name,
                    exc,
                )
                state.outcome_notes.append(f"step_error: {exc}")

            # Run declarative assertions
            self._run_step_assertions(step, state)

            # Collect failures into result
            result.failed_assertions.extend(
                f"step[{idx}] {step.name}: {msg}" for msg in state.assertions_failed
            )

            # Update result summary flags
            if state.degraded_operation_envelope:
                if state.degraded_operation_envelope.get("is_degraded"):
                    result.degradation_occurred = True
            if state.source_recovery_snapshot:
                for evt in state.source_recovery_snapshot.get("switch_events") or []:
                    result.recovery_occurred = True
            if state.operator_override_snapshot:
                if state.operator_override_snapshot.get("has_active_override"):
                    result.override_was_active = True
            if state.decision_timeline_snapshot:
                result.timeline_event_count = max(
                    result.timeline_event_count,
                    state.decision_timeline_snapshot.get("total_events", 0),
                )

            result.steps.append(state)

        return result

    # ------------------------------------------------------------------
    # Step execution
    # ------------------------------------------------------------------

    def _execute_step(self, step: ScenarioStep, state: ScenarioState) -> None:
        """Dispatch step execution to the appropriate handler."""
        kind = step.kind
        p = step.params

        if kind == ScenarioStepKind.REGISTER_SOURCE:
            self._handle_register_source(p, state)
        elif kind == ScenarioStepKind.MARK_SOURCE_HEALTHY:
            self._handle_mark_source_healthy(p, state)
        elif kind == ScenarioStepKind.MARK_SOURCE_DEGRADED:
            self._handle_mark_source_degraded(p, state)
        elif kind == ScenarioStepKind.MARK_SOURCE_UNAVAILABLE:
            self._handle_mark_source_unavailable(p, state)
        elif kind == ScenarioStepKind.SELECT_MULTIMODAL_ROUTE:
            self._handle_select_route(p, state)
        elif kind == ScenarioStepKind.PROVIDER_DEGRADATION:
            self._handle_provider_degradation(p, state)
        elif kind == ScenarioStepKind.PERMISSION_CHANGE:
            self._handle_permission_change(p, state)
        elif kind == ScenarioStepKind.APPLY_OPERATOR_OVERRIDE:
            self._handle_apply_override(p, state)
        elif kind == ScenarioStepKind.CLEAR_OPERATOR_OVERRIDE:
            self._handle_clear_override(p, state)
        elif kind == ScenarioStepKind.RUN_SOURCE_RECOVERY_CYCLE:
            self._handle_recovery_cycle(p, state)
        elif kind == ScenarioStepKind.BUILD_PERMISSION_SNAPSHOT:
            self._handle_build_permission_snapshot(p, state)
        elif kind == ScenarioStepKind.RECORD_TIMELINE_EVENT:
            self._handle_record_timeline_event(p, state)
        elif kind == ScenarioStepKind.BUILD_EXPLAINABILITY_SNAPSHOT:
            self._handle_build_explainability_snapshot(p, state)
        elif kind == ScenarioStepKind.ASSERT_CHECKPOINT:
            pass  # assertions handled outside this method
        else:
            logger.warning("ScenarioSimulator: unknown step kind %s", kind)

        # After every step, refresh shared canonical snapshots into state
        self._refresh_snapshots(state)

    # ------------------------------------------------------------------
    # Individual step handlers
    # ------------------------------------------------------------------

    def _handle_register_source(
        self, params: Dict[str, Any], state: ScenarioState
    ) -> None:
        _psr = _load_module_from_file("core.multimodal.perception_source_registry")
        PerceptionSourceType = _psr.PerceptionSourceType
        SourceModality = _psr.SourceModality

        source_id = params.get("source_id")
        raw_type = str(params.get("source_type") or "microphone").lower()
        raw_modality = str(params.get("modality") or "audio").lower()
        display_name = str(params.get("display_name") or source_id or "source")
        healthy = bool(params.get("healthy", True))

        # Map raw strings to enums
        type_map = {
            "microphone": PerceptionSourceType.MICROPHONE,
            "webcam": PerceptionSourceType.WEBCAM,
            "camera": PerceptionSourceType.WEBCAM,
            "webrtc": PerceptionSourceType.WEBRTC,
            "external": PerceptionSourceType.EXTERNAL_STREAM,
        }
        modality_map = {
            "audio": SourceModality.AUDIO,
            "video": SourceModality.VIDEO,
            "multi": SourceModality.MULTI,
        }
        src_type = type_map.get(raw_type, PerceptionSourceType.MICROPHONE)
        src_modality = modality_map.get(raw_modality, SourceModality.AUDIO)

        registered_id = self._registry.register(
            source_type=src_type,
            modality=src_modality,
            display_name=display_name,
            source_id=source_id,
        )
        self._registry.mark_active(registered_id)
        if src_modality == SourceModality.AUDIO and self._registry.primary_audio_id is None:
            self._registry.set_primary_audio(registered_id)
        elif src_modality == SourceModality.VIDEO and self._registry.primary_video_id is None:
            self._registry.set_primary_video(registered_id)

        if not healthy:
            self._registry.mark_degraded(registered_id, ["registered_unhealthy"])

        state.outcome_notes.append(
            f"registered source_id={registered_id} modality={raw_modality}"
        )

    def _handle_mark_source_healthy(
        self, params: Dict[str, Any], state: ScenarioState
    ) -> None:
        source_id = str(params.get("source_id") or "")
        if source_id and source_id in self._registry._sources:
            self._registry.mark_recovered(source_id)
            self._registry.mark_active(source_id)
            state.outcome_notes.append(f"source_recovered source_id={source_id}")

    def _handle_mark_source_degraded(
        self, params: Dict[str, Any], state: ScenarioState
    ) -> None:
        source_id = str(params.get("source_id") or "")
        if source_id and source_id in self._registry._sources:
            reasons = list(params.get("reasons") or ["simulated_degradation"])
            self._registry.mark_degraded(source_id, reasons)
            state.outcome_notes.append(f"source_degraded source_id={source_id}")

    def _handle_mark_source_unavailable(
        self, params: Dict[str, Any], state: ScenarioState
    ) -> None:
        source_id = str(params.get("source_id") or "")
        if source_id and source_id in self._registry._sources:
            self._registry.mark_unavailable(source_id)
            self._registry.mark_inactive(source_id)
            state.outcome_notes.append(f"source_unavailable source_id={source_id}")

    def _handle_select_route(
        self, params: Dict[str, Any], state: ScenarioState
    ) -> None:
        from core.degraded_operation_envelope import build_degraded_operation_envelope
        from core.decision_timeline import record_route_selection_event

        route_dict: Dict[str, Any] = {
            "route_type": params.get("route_type", "text_only"),
            "is_native_multimodal": params.get("is_native_multimodal", False),
            "provider": params.get("provider", "unknown"),
            "model": params.get("model", ""),
            "route_reason": params.get("route_reason", ""),
            "fallback_reason": params.get("fallback_reason"),
        }
        trace_id = params.get("trace_id")

        # Apply any active operator override to the route
        from core.operator_override import (
            get_operator_override_state,
            apply_route_override,
        )
        override_set = get_operator_override_state().active_override_set
        if override_set is not None:
            route_dict = apply_route_override(route_dict, override_set)

        self._current_route = route_dict

        # Build degraded-operation envelope
        envelope = build_degraded_operation_envelope(
            route_dict=route_dict,
            prior_envelope=self._prior_envelope,
            trace_id=trace_id,
        )
        state.degraded_operation_envelope = envelope.to_dict()
        self._prior_envelope = envelope.to_dict()

        # Record route selection on the decision timeline
        record_route_selection_event(
            route_dict=route_dict,
            trace_id=trace_id,
        )

        state.route_dict = route_dict
        state.outcome_notes.append(
            f"route_type={route_dict['route_type']} "
            f"is_degraded={envelope.is_degraded}"
        )

    def _handle_provider_degradation(
        self, params: Dict[str, Any], state: ScenarioState
    ) -> None:
        """Simulate a provider going degraded by injecting a degraded route."""
        from core.degraded_operation_envelope import build_degraded_operation_envelope
        from core.decision_timeline import record_route_selection_event

        provider = str(params.get("provider") or "unknown")
        degradation_reason = str(
            params.get("degradation_reason") or "provider_degraded"
        )
        route_dict: Dict[str, Any] = {
            "route_type": "text_only",
            "is_native_multimodal": False,
            "provider": provider,
            "model": "",
            "route_reason": "provider_degraded_fallback",
            "fallback_reason": degradation_reason,
        }
        self._current_route = route_dict
        envelope = build_degraded_operation_envelope(
            route_dict=route_dict,
            prior_envelope=self._prior_envelope,
        )
        state.degraded_operation_envelope = envelope.to_dict()
        self._prior_envelope = envelope.to_dict()
        record_route_selection_event(route_dict=route_dict)
        state.route_dict = route_dict
        state.outcome_notes.append(f"provider_degraded provider={provider}")

    def _handle_permission_change(
        self, params: Dict[str, Any], state: ScenarioState
    ) -> None:
        modality = str(params.get("modality") or "audio").lower()
        permission_status = str(
            params.get("permission_status") or "granted"
        ).lower()
        self._permission_table[modality] = permission_status
        state.outcome_notes.append(
            f"permission_change modality={modality} status={permission_status}"
        )
        # Rebuild the permission snapshot with the updated table
        self._handle_build_permission_snapshot(params, state)

    def _handle_apply_override(
        self, params: Dict[str, Any], state: ScenarioState
    ) -> None:
        from core.operator_override import (
            OperatorOverrideSet,
            OverrideMultimodalMode,
            OverrideExecutionLocality,
            get_operator_override_state,
            build_operator_override_snapshot,
        )

        raw_mm = str(params.get("multimodal_mode") or "auto").lower()
        mm_map = {
            "force_off": OverrideMultimodalMode.FORCE_OFF,
            "force_on": OverrideMultimodalMode.FORCE_ON,
            "auto": OverrideMultimodalMode.AUTO,
        }
        multimodal_mode = mm_map.get(raw_mm, OverrideMultimodalMode.AUTO)

        override_set = OperatorOverrideSet(
            multimodal_mode=multimodal_mode,
            preferred_provider=params.get("preferred_provider"),
            preferred_model=params.get("preferred_model"),
            override_reason=str(params.get("override_reason") or "scenario"),
            is_active=True,
        )
        ov_state = get_operator_override_state()
        ov_state.commit(override_set=override_set, applied_by="scenario_harness")
        snap = ov_state.snapshot()
        state.operator_override_snapshot = snap.to_dict()
        self._current_override_snapshot = snap.to_dict()
        state.outcome_notes.append(
            f"operator_override_applied mm={raw_mm} "
            f"provider={params.get('preferred_provider')}"
        )

    def _handle_clear_override(
        self, params: Dict[str, Any], state: ScenarioState
    ) -> None:
        from core.operator_override import (
            get_operator_override_state,
        )

        ov_state = get_operator_override_state()
        ov_state.clear(applied_by="scenario_harness")
        snap = ov_state.snapshot()
        state.operator_override_snapshot = snap.to_dict()
        self._current_override_snapshot = snap.to_dict()
        state.outcome_notes.append("operator_override_cleared")

    def _handle_recovery_cycle(
        self, params: Dict[str, Any], state: ScenarioState
    ) -> None:
        _srp = _load_module_from_file("core.multimodal.source_recovery_policy")
        get_source_recovery_policy = _srp.get_source_recovery_policy

        policy = get_source_recovery_policy()
        cycle_summary = policy.run_recovery_cycle(self._registry)
        snap = policy.snapshot(self._registry)
        state.source_recovery_snapshot = snap.to_dict()
        state.outcome_notes.append(
            f"recovery_cycle evicted={cycle_summary.get('evicted', [])} "
            f"audio_reelected={cycle_summary.get('audio_reelected')} "
            f"video_reelected={cycle_summary.get('video_reelected')}"
        )

    def _handle_build_permission_snapshot(
        self, params: Dict[str, Any], state: ScenarioState
    ) -> None:
        _pss = _load_module_from_file("core.multimodal.permission_safety_state")
        build_permission_safety_snapshot = _pss.build_permission_safety_snapshot

        registry_snap = self._registry.snapshot()

        # Apply soft permission overrides to the source registry snapshot
        if self._permission_table:
            sources = list(registry_snap.get("sources") or [])
            for src in sources:
                mod = str(src.get("modality") or "").lower()
                if mod in self._permission_table:
                    src["health"] = (
                        "healthy"
                        if self._permission_table[mod] == "granted"
                        else self._permission_table[mod]
                    )

        snap = build_permission_safety_snapshot(
            source_registry_snapshot=registry_snap,
            multimodal_route=self._current_route,
            degraded_operation_envelope=state.degraded_operation_envelope
            or self._prior_envelope,
            trace_id=params.get("trace_id"),
        )
        state.permission_safety_snapshot = snap.to_dict()
        state.outcome_notes.append(
            f"permission_snapshot trust={snap.overall_trust_label} "
            f"gated={snap.is_gated}"
        )

    def _handle_record_timeline_event(
        self, params: Dict[str, Any], state: ScenarioState
    ) -> None:
        from core.decision_timeline import record_decision_event, DecisionKind

        kind_str = str(params.get("kind") or "route_selection")
        try:
            kind = DecisionKind(kind_str)
        except ValueError:
            kind = DecisionKind.ROUTE_SELECTION
        record_decision_event(
            kind=kind,
            summary=str(params.get("summary") or f"scenario_step_{kind_str}"),
            trace_id=params.get("trace_id"),
        )

    def _handle_build_explainability_snapshot(
        self, params: Dict[str, Any], state: ScenarioState
    ) -> None:
        from core.decision_timeline import (
            build_explainability_snapshot,
            get_decision_timeline,
        )

        snap = build_explainability_snapshot(
            runtime_session_id=params.get("runtime_session_id"),
            trace_id=params.get("trace_id"),
        )
        tl = get_decision_timeline()
        tl_snap = tl.snapshot()
        state.decision_timeline_snapshot = tl_snap.to_dict()
        state.outcome_notes.append(
            f"explainability_snapshot events={tl_snap.event_count}"
        )

    # ------------------------------------------------------------------
    # Snapshot refresh after each step
    # ------------------------------------------------------------------

    def _refresh_snapshots(self, state: ScenarioState) -> None:
        """Refresh canonical snapshots into state after every step."""
        state.source_registry_snapshot = self._registry.snapshot()

        # Refresh timeline snapshot
        try:
            from core.decision_timeline import get_decision_timeline

            tl_snap = get_decision_timeline().snapshot()
            state.decision_timeline_snapshot = tl_snap.to_dict()
        except Exception:
            pass

        # Refresh operator override snapshot (keep previous if present)
        if state.operator_override_snapshot is None and self._current_override_snapshot:
            state.operator_override_snapshot = self._current_override_snapshot

        # Refresh override snapshot from singleton when it was set during this step
        try:
            from core.operator_override import get_operator_override_state

            ov_snap = get_operator_override_state().snapshot()
            state.operator_override_snapshot = ov_snap.to_dict()
        except Exception:
            pass

        # Refresh source recovery snapshot if recovery cycle ran
        if state.source_recovery_snapshot is None:
            try:
                _srp = _load_module_from_file("core.multimodal.source_recovery_policy")
                get_source_recovery_policy = _srp.get_source_recovery_policy

                policy = get_source_recovery_policy()
                snap = policy.snapshot(self._registry)
                state.source_recovery_snapshot = snap.to_dict()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Declarative step assertions
    # ------------------------------------------------------------------

    def _run_step_assertions(self, step: ScenarioStep, state: ScenarioState) -> None:
        if step.expected_route_type is not None:
            actual = (state.route_dict or {}).get("route_type")
            if actual != step.expected_route_type:
                state.assertions_failed.append(
                    f"expected route_type={step.expected_route_type!r} "
                    f"got {actual!r}"
                )
            else:
                state.assertions_passed.append(
                    f"route_type={step.expected_route_type!r}"
                )

        if step.expected_degraded is not None:
            actual_degraded = (state.degraded_operation_envelope or {}).get(
                "is_degraded", False
            )
            if bool(actual_degraded) != step.expected_degraded:
                state.assertions_failed.append(
                    f"expected is_degraded={step.expected_degraded} "
                    f"got {actual_degraded!r}"
                )
            else:
                state.assertions_passed.append(
                    f"is_degraded={step.expected_degraded}"
                )

        if step.expected_timeline_min_events is not None:
            actual_count = (state.decision_timeline_snapshot or {}).get(
                "total_events", 0
            )
            if actual_count < step.expected_timeline_min_events:
                state.assertions_failed.append(
                    f"expected timeline_events>={step.expected_timeline_min_events} "
                    f"got {actual_count}"
                )
            else:
                state.assertions_passed.append(
                    f"timeline_events>={step.expected_timeline_min_events}"
                )

        if step.expected_has_active_override is not None:
            actual_active = (state.operator_override_snapshot or {}).get(
                "has_active_override", False
            )
            if bool(actual_active) != step.expected_has_active_override:
                state.assertions_failed.append(
                    f"expected has_active_override="
                    f"{step.expected_has_active_override} got {actual_active!r}"
                )
            else:
                state.assertions_passed.append(
                    f"has_active_override={step.expected_has_active_override}"
                )


# ---------------------------------------------------------------------------
# ScenarioAssertions — canonical assertion helpers
# ---------------------------------------------------------------------------


class ScenarioAssertions:
    """Static assertion helpers for scenario test code.

    All helpers operate on :class:`ScenarioState` dicts / canonical artifact
    dicts, never on logs or incidental outputs.
    """

    @staticmethod
    def assert_degraded_to_text_only(state: ScenarioState) -> None:
        env = state.degraded_operation_envelope or {}
        level = env.get("current_level", "")
        assert level == "text_only", (
            f"Expected degraded level 'text_only', got {level!r}; "
            f"envelope={env}"
        )
        assert env.get("is_degraded") is True, (
            f"Expected is_degraded=True; envelope={env}"
        )

    @staticmethod
    def assert_route_is_native_multimodal(state: ScenarioState) -> None:
        route = state.route_dict or {}
        assert route.get("route_type") == "native_multimodal", (
            f"Expected native_multimodal route, got {route.get('route_type')!r}"
        )
        assert route.get("is_native_multimodal") is True, (
            "Expected is_native_multimodal=True"
        )
        env = state.degraded_operation_envelope or {}
        assert env.get("is_degraded") is False, (
            f"Expected is_degraded=False for native_multimodal; envelope={env}"
        )

    @staticmethod
    def assert_timeline_ordered(state: ScenarioState) -> None:
        """Assert that decision timeline events are monotonically ordered."""
        tl = state.decision_timeline_snapshot or {}
        events = list(tl.get("events") or [])
        sequences = [e.get("sequence", 0) for e in events]
        assert sequences == sorted(sequences), (
            f"Timeline events are not in ascending sequence order: {sequences}"
        )

    @staticmethod
    def assert_timeline_has_event_kind(
        state: ScenarioState, kind: str, min_count: int = 1
    ) -> None:
        tl = state.decision_timeline_snapshot or {}
        kind_counts = dict(tl.get("kind_counts") or {})
        actual = kind_counts.get(kind, 0)
        assert actual >= min_count, (
            f"Expected at least {min_count} timeline event(s) of kind={kind!r}, "
            f"got {actual}; kind_counts={kind_counts}"
        )

    @staticmethod
    def assert_has_active_operator_override(state: ScenarioState) -> None:
        ov = state.operator_override_snapshot or {}
        assert ov.get("has_active_override") is True, (
            f"Expected an active operator override; snapshot={ov}"
        )

    @staticmethod
    def assert_no_active_operator_override(state: ScenarioState) -> None:
        ov = state.operator_override_snapshot or {}
        assert ov.get("has_active_override") is not True, (
            f"Expected no active operator override; snapshot={ov}"
        )

    @staticmethod
    def assert_permission_is_gated(state: ScenarioState) -> None:
        perm = state.permission_safety_snapshot or {}
        assert perm.get("is_gated") is True, (
            f"Expected permission_safety_snapshot.is_gated=True; snapshot={perm}"
        )

    @staticmethod
    def assert_permission_not_gated(state: ScenarioState) -> None:
        perm = state.permission_safety_snapshot or {}
        # Treat None/missing permission snapshot as not gated
        if perm:
            assert perm.get("is_gated") is not True, (
                f"Expected permission_safety_snapshot.is_gated=False; snapshot={perm}"
            )

    @staticmethod
    def assert_source_registry_has_source(
        state: ScenarioState, modality: str
    ) -> None:
        registry = state.source_registry_snapshot or {}
        sources = list(registry.get("sources") or [])
        found = any(
            str(s.get("modality") or "").lower() == modality.lower()
            for s in sources
        )
        assert found, (
            f"Expected source with modality={modality!r} in registry; "
            f"sources={[s.get('modality') for s in sources]}"
        )

    @staticmethod
    def assert_transition_occurred(state: ScenarioState) -> None:
        env = state.degraded_operation_envelope or {}
        assert env.get("transition_occurred") is True, (
            f"Expected degradation transition_occurred=True; envelope={env}"
        )

    @staticmethod
    def assert_envelope_serialisable(state: ScenarioState) -> None:
        import json

        env = state.degraded_operation_envelope
        assert env is not None, "Expected a non-None degraded_operation_envelope"
        try:
            json.dumps(env)
        except (TypeError, ValueError) as exc:
            raise AssertionError(
                f"degraded_operation_envelope is not JSON-serialisable: {exc}"
            ) from exc

    @staticmethod
    def assert_state_fully_serialisable(state: ScenarioState) -> None:
        import json

        d = state.to_dict()
        try:
            json.dumps(d)
        except (TypeError, ValueError) as exc:
            raise AssertionError(
                f"ScenarioState.to_dict() is not JSON-serialisable: {exc}"
            ) from exc

    @staticmethod
    def assert_scenario_result_serialisable(result: ScenarioResult) -> None:
        import json

        d = result.to_dict()
        try:
            json.dumps(d)
        except (TypeError, ValueError) as exc:
            raise AssertionError(
                f"ScenarioResult.to_dict() is not JSON-serialisable: {exc}"
            ) from exc
