"""core.operator_override — Canonical Operator Override Layer (PR-33)
=====================================================================

**Unified-Subject Architecture — Operator Control Surfaces**
-------------------------------------------------------------
This module introduces a **structured override layer** that preserves
canonical authority while enabling deliberate operator intervention in key
runtime and routing decisions.

The architecture ownership rules are:

- **Runtime shell** (:class:`~core.desktop_presence_runtime.DesktopPresenceRuntime`)
  owns all operator-facing control surfaces.  Operators interact with overrides
  exclusively through shell-owned entry points.
- **OpenClawd core** (:mod:`core.openclawd`) remains the **final authority** that
  evaluates and applies override state within canonical control decisions.
  Overrides are *inputs* to canonical decisions, not a bypass around the core.
- **Projection / diagnostics / execution layers** consume override-aware canonical
  artifacts; they do not invent separate override logic.

**Override domains**

1. Primary audio source selection
2. Primary video source selection
3. Provider/model lock (preferred-model override)
4. Native multimodal force-on / force-off behaviour
5. Local-only / remote-disabled execution policy
6. Remote-action mode (``command_only``, ``full_agent``, or default)

**Behavioural guarantees**

1. **Automation remains the default** — an empty :class:`OperatorOverrideSet`
   is equivalent to no override at all; all canonical policies apply unchanged.
2. **OpenClawd is final authority** — overrides are inputs to the control core,
   not a bypass.  The core may further constrain override requests in the
   presence of degraded-operation or safety-gating state.
3. **Visibility and explainability** — every active override carries an
   explicit ``reason`` string.  Projection and diagnostics can expose overrides
   as first-class policy inputs.
4. **Serialisation-safe** — all public dataclasses expose ``to_dict()`` /
   ``from_dict()`` and store only plain Python primitives.

Usage::

    from core.operator_override import (
        get_operator_override_state,
        OperatorOverrideSet,
        OverrideMultimodalMode,
        OverrideExecutionLocality,
    )

    state = get_operator_override_state()
    overrides = OperatorOverrideSet(
        multimodal_mode=OverrideMultimodalMode.FORCE_OFF,
        execution_locality=OverrideExecutionLocality.LOCAL_ONLY,
        override_reason="maintenance_window",
    )
    state.commit(overrides)

    # In OpenClawd, read the active override set:
    active = state.active_override_set  # OperatorOverrideSet or None
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
# Enumerations
# ---------------------------------------------------------------------------


class OverrideMultimodalMode(str, Enum):
    """Operator override for native multimodal behaviour.

    This overrides the perception-driven native-multimodal routing decision
    inside :meth:`~core.openclawd.OpenClawd._select_multimodal_route`.
    """

    FORCE_ON = "force_on"
    """Force native multimodal routing regardless of perception confidence.
    OpenClawd may still degrade this if no native MM provider is available."""

    FORCE_OFF = "force_off"
    """Force text-only routing regardless of perception state.  Native
    multimodal providers will not be selected for this request."""

    AUTO = "auto"
    """Automation default — respect canonical perception and confidence policy.
    This is the no-op value; it represents *no override*."""

    @classmethod
    def from_string(cls, value: str) -> "OverrideMultimodalMode":
        """Return an :class:`OverrideMultimodalMode` from a raw string,
        defaulting to :attr:`AUTO` for unrecognised values."""
        try:
            return cls(value)
        except ValueError:
            return cls.AUTO


class OverrideExecutionLocality(str, Enum):
    """Operator override for execution locality policy.

    This overrides the cross-device expansion decision inside OpenClawd's
    execution-path determination.
    """

    LOCAL_ONLY = "local_only"
    """Constrain all execution to the local device.  Cross-device expansion
    is blocked regardless of the canonical execution policy."""

    REMOTE_DISABLED = "remote_disabled"
    """Disable remote action execution.  Equivalent to ``local_only`` from a
    cross-device policy perspective; kept as a distinct value for semantics."""

    DEFAULT = "default"
    """Automation default — respect canonical execution policy.
    This is the no-op value; it represents *no override*."""

    @classmethod
    def from_string(cls, value: str) -> "OverrideExecutionLocality":
        """Return an :class:`OverrideExecutionLocality` from a raw string,
        defaulting to :attr:`DEFAULT` for unrecognised values."""
        try:
            return cls(value)
        except ValueError:
            return cls.DEFAULT


class OverrideRemoteMode(str, Enum):
    """Operator override for remote-action execution mode.

    When remote execution is permitted, this restricts the remote execution
    mode to a safer subset.
    """

    COMMAND_ONLY = "command_only"
    """Restrict remote execution to ``command_only`` mode, avoiding full agent
    runtime deployment on remote devices."""

    FULL_AGENT = "full_agent"
    """Explicitly request full agent-runtime mode on remote devices (only
    effective when remote execution is permitted)."""

    DEFAULT = "default"
    """Automation default — respect canonical remote-execution mode selection.
    This is the no-op value; it represents *no override*."""

    @classmethod
    def from_string(cls, value: str) -> "OverrideRemoteMode":
        """Return an :class:`OverrideRemoteMode` from a raw string,
        defaulting to :attr:`DEFAULT` for unrecognised values."""
        try:
            return cls(value)
        except ValueError:
            return cls.DEFAULT


# ---------------------------------------------------------------------------
# Core dataclasses
# ---------------------------------------------------------------------------


@dataclass
class OperatorOverrideSet:
    """Canonical container for a complete set of operator overrides.

    An empty (all-default) :class:`OperatorOverrideSet` is a no-op.  Only
    fields set to non-default values represent active operator intentions.

    Attributes
    ----------
    override_id:
        Unique identifier for this override configuration, auto-generated.
    override_at:
        Wall-clock timestamp when this override set was created.
    primary_audio_source_id:
        When non-``None``, forces this source ID as the primary audio source.
        The runtime shell's source registry must contain a matching source.
    primary_video_source_id:
        When non-``None``, forces this source ID as the primary video source.
        The runtime shell's source registry must contain a matching source.
    preferred_provider:
        When non-``None``, locks the provider to this name (e.g. ``"openai"``).
        OpenClawd will attempt to route to this provider but may fall back if
        it is unavailable.
    preferred_model:
        When non-``None``, requests this specific model name.  Combined with
        ``preferred_provider`` for deterministic routing.
    multimodal_mode:
        Explicit multimodal behaviour override.  :attr:`OverrideMultimodalMode.AUTO`
        means no override.
    execution_locality:
        Explicit execution locality override.
        :attr:`OverrideExecutionLocality.DEFAULT` means no override.
    remote_mode:
        Explicit remote execution mode override.
        :attr:`OverrideRemoteMode.DEFAULT` means no override.
    override_reason:
        Human-readable provenance string for the override set (e.g.
        ``"maintenance_window"`` or ``"operator:alice"``) .  Always surfaced in
        projection and diagnostics.
    is_active:
        True when this override set is currently applied.  May be set to
        False by the singleton to record a historical record without removing it.
    """

    override_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    override_at: float = field(default_factory=time.time)
    primary_audio_source_id: Optional[str] = None
    primary_video_source_id: Optional[str] = None
    preferred_provider: Optional[str] = None
    preferred_model: Optional[str] = None
    multimodal_mode: OverrideMultimodalMode = OverrideMultimodalMode.AUTO
    execution_locality: OverrideExecutionLocality = OverrideExecutionLocality.DEFAULT
    remote_mode: OverrideRemoteMode = OverrideRemoteMode.DEFAULT
    override_reason: str = ""
    is_active: bool = True

    # --------------------------------------------------------------------------
    # Derived helpers
    # --------------------------------------------------------------------------

    @property
    def has_source_override(self) -> bool:
        """True when at least one source override is set."""
        return (
            self.primary_audio_source_id is not None
            or self.primary_video_source_id is not None
        )

    @property
    def has_model_override(self) -> bool:
        """True when provider or model preference is set."""
        return self.preferred_provider is not None or self.preferred_model is not None

    @property
    def has_multimodal_override(self) -> bool:
        """True when multimodal mode is explicitly overridden (not AUTO)."""
        return self.multimodal_mode != OverrideMultimodalMode.AUTO

    @property
    def has_locality_override(self) -> bool:
        """True when execution locality is explicitly overridden (not DEFAULT)."""
        return self.execution_locality != OverrideExecutionLocality.DEFAULT

    @property
    def has_remote_mode_override(self) -> bool:
        """True when remote mode is explicitly overridden (not DEFAULT)."""
        return self.remote_mode != OverrideRemoteMode.DEFAULT

    @property
    def is_noop(self) -> bool:
        """True when no domain carries an active override — this set is
        equivalent to automation default."""
        return (
            not self.has_source_override
            and not self.has_model_override
            and not self.has_multimodal_override
            and not self.has_locality_override
            and not self.has_remote_mode_override
        )

    # --------------------------------------------------------------------------
    # Serialisation
    # --------------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "override_id": self.override_id,
            "override_at": self.override_at,
            "primary_audio_source_id": self.primary_audio_source_id,
            "primary_video_source_id": self.primary_video_source_id,
            "preferred_provider": self.preferred_provider,
            "preferred_model": self.preferred_model,
            "multimodal_mode": self.multimodal_mode.value,
            "execution_locality": self.execution_locality.value,
            "remote_mode": self.remote_mode.value,
            "override_reason": self.override_reason,
            "is_active": self.is_active,
            # Derived summary fields for diagnostics / projection
            "has_source_override": self.has_source_override,
            "has_model_override": self.has_model_override,
            "has_multimodal_override": self.has_multimodal_override,
            "has_locality_override": self.has_locality_override,
            "has_remote_mode_override": self.has_remote_mode_override,
            "is_noop": self.is_noop,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OperatorOverrideSet":
        """Reconstruct an :class:`OperatorOverrideSet` from a serialised dict.

        Unknown or missing fields are silently defaulted so that older stored
        snapshots remain readable after schema additions.
        """
        return cls(
            override_id=str(data.get("override_id") or str(uuid.uuid4())),
            override_at=float(data.get("override_at", time.time())),
            primary_audio_source_id=data.get("primary_audio_source_id"),
            primary_video_source_id=data.get("primary_video_source_id"),
            preferred_provider=data.get("preferred_provider"),
            preferred_model=data.get("preferred_model"),
            multimodal_mode=OverrideMultimodalMode.from_string(
                str(data.get("multimodal_mode", OverrideMultimodalMode.AUTO.value))
            ),
            execution_locality=OverrideExecutionLocality.from_string(
                str(data.get("execution_locality", OverrideExecutionLocality.DEFAULT.value))
            ),
            remote_mode=OverrideRemoteMode.from_string(
                str(data.get("remote_mode", OverrideRemoteMode.DEFAULT.value))
            ),
            override_reason=str(data.get("override_reason", "")),
            is_active=bool(data.get("is_active", True)),
        )


@dataclass
class PolicyOverrideRecord:
    """Audit/provenance record for a committed or cleared override.

    Tracks the lifecycle of override state changes in the
    :class:`OperatorOverrideState` singleton so that diagnostics and
    explainability layers can reconstruct the override history.

    Attributes
    ----------
    record_id:
        Unique identifier for this audit record.
    recorded_at:
        Timestamp when this record was created.
    event_kind:
        ``"commit"`` when an override was applied, ``"clear"`` when cleared.
    override_set:
        The :class:`OperatorOverrideSet` associated with the event.  For
        ``"clear"`` events this is the override that was removed.
    applied_by:
        Optional identifier of the operator or automation component that
        triggered the event (for audit trails).
    context_trace_id:
        Optional correlation trace ID linking the event to a specific
        control-loop iteration.
    """

    record_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    recorded_at: float = field(default_factory=time.time)
    event_kind: str = "commit"  # "commit" | "clear"
    override_set: Optional[OperatorOverrideSet] = None
    applied_by: Optional[str] = None
    context_trace_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "recorded_at": self.recorded_at,
            "event_kind": self.event_kind,
            "override_set": self.override_set.to_dict() if self.override_set else None,
            "applied_by": self.applied_by,
            "context_trace_id": self.context_trace_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PolicyOverrideRecord":
        raw_set = data.get("override_set")
        return cls(
            record_id=str(data.get("record_id") or str(uuid.uuid4())),
            recorded_at=float(data.get("recorded_at", time.time())),
            event_kind=str(data.get("event_kind", "commit")),
            override_set=(
                OperatorOverrideSet.from_dict(raw_set)
                if isinstance(raw_set, dict)
                else None
            ),
            applied_by=data.get("applied_by"),
            context_trace_id=data.get("context_trace_id"),
        )


# ---------------------------------------------------------------------------
# Operator override state snapshot (for response embedding)
# ---------------------------------------------------------------------------


@dataclass
class OperatorOverrideSnapshot:
    """Immutable snapshot of the active override state for a single
    control-loop iteration.

    Embedded in response metadata so projection, diagnostics, and
    explainability layers can surface override-influenced decisions without
    accessing the singleton directly.

    Attributes
    ----------
    snapshot_id:
        Unique identifier for this snapshot.
    snapshot_at:
        Timestamp when the snapshot was captured.
    trace_id:
        Optional correlation trace ID.
    runtime_session_id:
        Optional runtime session identifier.
    has_active_override:
        True when there is a non-noop active :class:`OperatorOverrideSet`.
    active_override_set:
        The active :class:`OperatorOverrideSet`, or ``None`` if no override is set.
    applied_domains:
        List of override domain names that are currently active (e.g.
        ``["audio_source", "multimodal_mode", "execution_locality"]``).
    override_reason:
        The ``override_reason`` from the active set (or ``""``).
    """

    snapshot_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    snapshot_at: float = field(default_factory=time.time)
    trace_id: Optional[str] = None
    runtime_session_id: Optional[str] = None
    has_active_override: bool = False
    active_override_set: Optional[OperatorOverrideSet] = None
    applied_domains: List[str] = field(default_factory=list)
    override_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "snapshot_at": self.snapshot_at,
            "trace_id": self.trace_id,
            "runtime_session_id": self.runtime_session_id,
            "has_active_override": self.has_active_override,
            "active_override_set": (
                self.active_override_set.to_dict()
                if self.active_override_set is not None
                else None
            ),
            "applied_domains": list(self.applied_domains),
            "override_reason": self.override_reason,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OperatorOverrideSnapshot":
        raw_set = data.get("active_override_set")
        return cls(
            snapshot_id=str(data.get("snapshot_id") or str(uuid.uuid4())),
            snapshot_at=float(data.get("snapshot_at", time.time())),
            trace_id=data.get("trace_id"),
            runtime_session_id=data.get("runtime_session_id"),
            has_active_override=bool(data.get("has_active_override", False)),
            active_override_set=(
                OperatorOverrideSet.from_dict(raw_set)
                if isinstance(raw_set, dict)
                else None
            ),
            applied_domains=list(data.get("applied_domains") or []),
            override_reason=str(data.get("override_reason", "")),
        )


# ---------------------------------------------------------------------------
# Singleton state manager
# ---------------------------------------------------------------------------


class OperatorOverrideState:
    """Process-wide singleton that tracks the currently active operator override.

    The runtime shell commits/clears overrides via :meth:`commit` and
    :meth:`clear`.  OpenClawd reads the active set via
    :attr:`active_override_set` on each control-loop iteration.

    Thread safety: all mutations are guarded by a simple swap on the CPython
    GIL; no explicit lock is used because all operations are atomic attribute
    assignments.
    """

    def __init__(self) -> None:
        self._active: Optional[OperatorOverrideSet] = None
        self._history: List[PolicyOverrideRecord] = []
        self._max_history: int = 100  # Bounded rolling window to prevent unbounded growth

    # ── Public accessors ──────────────────────────────────────────────────────

    @property
    def active_override_set(self) -> Optional[OperatorOverrideSet]:
        """The currently active :class:`OperatorOverrideSet`, or ``None``."""
        return self._active

    @property
    def history(self) -> List[PolicyOverrideRecord]:
        """Ordered list of :class:`PolicyOverrideRecord` entries (oldest first)."""
        return list(self._history)

    # ── Mutation ──────────────────────────────────────────────────────────────

    def commit(
        self,
        override_set: OperatorOverrideSet,
        *,
        applied_by: Optional[str] = None,
        context_trace_id: Optional[str] = None,
    ) -> None:
        """Set *override_set* as the active operator override.

        The previous override (if any) is superseded; a :class:`PolicyOverrideRecord`
        is appended to :attr:`history` for audit/explainability.
        """
        self._active = override_set
        record = PolicyOverrideRecord(
            event_kind="commit",
            override_set=override_set,
            applied_by=applied_by,
            context_trace_id=context_trace_id,
        )
        self._history.append(record)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history :]
        logger.debug(
            "OperatorOverrideState.commit: override_id=%s reason=%r by=%s",
            override_set.override_id,
            override_set.override_reason,
            applied_by,
        )

    def clear(
        self,
        *,
        applied_by: Optional[str] = None,
        context_trace_id: Optional[str] = None,
    ) -> None:
        """Clear the active override, returning to automation default.

        The cleared override set (if any) is recorded as a ``"clear"`` event
        in :attr:`history`.
        """
        previous = self._active
        self._active = None
        record = PolicyOverrideRecord(
            event_kind="clear",
            override_set=previous,
            applied_by=applied_by,
            context_trace_id=context_trace_id,
        )
        self._history.append(record)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history :]
        logger.debug(
            "OperatorOverrideState.clear: previous_id=%s by=%s",
            previous.override_id if previous else "none",
            applied_by,
        )

    def snapshot(
        self,
        *,
        trace_id: Optional[str] = None,
        runtime_session_id: Optional[str] = None,
    ) -> OperatorOverrideSnapshot:
        """Return a point-in-time :class:`OperatorOverrideSnapshot`."""
        active = self._active
        if active is None or active.is_noop:
            return OperatorOverrideSnapshot(
                trace_id=trace_id,
                runtime_session_id=runtime_session_id,
                has_active_override=False,
                active_override_set=None,
                applied_domains=[],
                override_reason="",
            )
        domains = _collect_applied_domains(active)
        return OperatorOverrideSnapshot(
            trace_id=trace_id,
            runtime_session_id=runtime_session_id,
            has_active_override=True,
            active_override_set=active,
            applied_domains=domains,
            override_reason=active.override_reason,
        )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_state_instance: Optional[OperatorOverrideState] = None


def get_operator_override_state() -> OperatorOverrideState:
    """Return the process-wide :class:`OperatorOverrideState` singleton.

    Creates the instance on first call (lazy initialisation).
    """
    global _state_instance
    if _state_instance is None:
        _state_instance = OperatorOverrideState()
    return _state_instance


def reset_operator_override_state() -> None:
    """Reset the singleton — **tests only**.  Clears active override and history."""
    global _state_instance
    _state_instance = None


# ---------------------------------------------------------------------------
# Builder / helper functions
# ---------------------------------------------------------------------------


def _collect_applied_domains(override_set: OperatorOverrideSet) -> List[str]:
    """Return a list of domain names that carry an active override."""
    domains: List[str] = []
    if override_set.primary_audio_source_id is not None:
        domains.append("audio_source")
    if override_set.primary_video_source_id is not None:
        domains.append("video_source")
    if override_set.preferred_provider is not None:
        domains.append("provider")
    if override_set.preferred_model is not None:
        domains.append("model")
    if override_set.multimodal_mode != OverrideMultimodalMode.AUTO:
        domains.append("multimodal_mode")
    if override_set.execution_locality != OverrideExecutionLocality.DEFAULT:
        domains.append("execution_locality")
    if override_set.remote_mode != OverrideRemoteMode.DEFAULT:
        domains.append("remote_mode")
    return domains


def build_operator_override_snapshot(
    *,
    trace_id: Optional[str] = None,
    runtime_session_id: Optional[str] = None,
) -> OperatorOverrideSnapshot:
    """Return a :class:`OperatorOverrideSnapshot` from the process-wide singleton.

    Convenience builder that reads the singleton and produces an immutable
    snapshot suitable for embedding in response metadata.
    """
    return get_operator_override_state().snapshot(
        trace_id=trace_id,
        runtime_session_id=runtime_session_id,
    )


def apply_route_override(
    route_dict: Dict[str, Any],
    override_set: Optional[OperatorOverrideSet],
) -> Dict[str, Any]:
    """Apply multimodal routing overrides to an existing *route_dict*.

    This function is called by OpenClawd **after** the canonical routing
    decision has been made.  It modifies the dict in the following ways when
    a non-noop override is present:

    - ``multimodal_mode=FORCE_OFF`` → downgrades ``route_type`` to
      ``"text_only"`` and sets ``is_native_multimodal=False``.
    - ``multimodal_mode=FORCE_ON`` → upgrades ``route_type`` to
      ``"native_multimodal"`` and sets ``is_native_multimodal=True``
      (OpenClawd may still degrade this if no native MM provider exists; this
      function only stamps the *intent*).
    - ``preferred_provider`` / ``preferred_model`` → overrides the
      ``"provider"`` / ``"model"`` fields in the route dict.

    The original dict is **not** mutated; a shallow copy is returned with
    modifications applied.  An ``"operator_override_applied"`` key is added
    to signal downstream consumers that override logic has influenced the
    route.
    """
    if override_set is None or override_set.is_noop or not override_set.is_active:
        return dict(route_dict)  # Always return a copy for consistent semantics

    result = dict(route_dict)

    # ── Multimodal mode override ──────────────────────────────────────────────
    if override_set.multimodal_mode == OverrideMultimodalMode.FORCE_OFF:
        result["route_type"] = "text_only"
        result["is_native_multimodal"] = False
        result["route_reason"] = (
            f"operator_override:multimodal_mode=force_off "
            f"reason={override_set.override_reason!r}"
        )
        result["operator_override_applied"] = "multimodal_mode=force_off"
    elif override_set.multimodal_mode == OverrideMultimodalMode.FORCE_ON:
        if result.get("route_type") not in ("native_multimodal",):
            result["route_type"] = "native_multimodal"
            result["is_native_multimodal"] = True
            result["route_reason"] = (
                f"operator_override:multimodal_mode=force_on "
                f"reason={override_set.override_reason!r}"
            )
            result["operator_override_applied"] = "multimodal_mode=force_on"

    # ── Provider / model override ─────────────────────────────────────────────
    if override_set.preferred_provider is not None:
        result["provider"] = override_set.preferred_provider
        result.setdefault("operator_override_applied", "")
        if "provider" not in result.get("operator_override_applied", ""):
            result["operator_override_applied"] = (
                result.get("operator_override_applied", "") + " provider_lock"
            ).strip()
    if override_set.preferred_model is not None:
        result["model"] = override_set.preferred_model
        result.setdefault("operator_override_applied", "")
        if "model" not in result.get("operator_override_applied", ""):
            result["operator_override_applied"] = (
                result.get("operator_override_applied", "") + " model_lock"
            ).strip()

    return result


def apply_execution_policy_override(
    *,
    cross_device_allowed: bool,
    remote_mode: Optional[str],
    override_set: Optional[OperatorOverrideSet],
) -> Dict[str, Any]:
    """Apply execution-policy overrides and return a dict of effective values.

    OpenClawd calls this after computing the canonical execution policy to
    check whether the operator has requested more restrictive execution
    behaviour.

    Returns a dict with keys:

    ``effective_cross_device_allowed``
        ``False`` when ``execution_locality`` is ``LOCAL_ONLY`` or
        ``REMOTE_DISABLED``, otherwise equals *cross_device_allowed*.
    ``effective_remote_mode``
        ``"command_only"`` when ``remote_mode`` is ``COMMAND_ONLY``,
        ``"full_agent"`` when ``FULL_AGENT``, otherwise equals *remote_mode*.
    ``override_applied``
        ``True`` when at least one execution-domain value was changed by
        an active override.
    ``override_reason``
        The ``override_reason`` from the active set (or ``""``).
    """
    if override_set is None or override_set.is_noop or not override_set.is_active:
        return {
            "effective_cross_device_allowed": cross_device_allowed,
            "effective_remote_mode": remote_mode,
            "override_applied": False,
            "override_reason": "",
        }

    effective_cross_device = cross_device_allowed
    effective_remote = remote_mode
    override_applied = False

    if override_set.execution_locality in (
        OverrideExecutionLocality.LOCAL_ONLY,
        OverrideExecutionLocality.REMOTE_DISABLED,
    ):
        effective_cross_device = False
        override_applied = True

    if override_set.remote_mode == OverrideRemoteMode.COMMAND_ONLY:
        effective_remote = "command_only"
        override_applied = True
    elif override_set.remote_mode == OverrideRemoteMode.FULL_AGENT:
        effective_remote = "full_agent"
        override_applied = True

    return {
        "effective_cross_device_allowed": effective_cross_device,
        "effective_remote_mode": effective_remote,
        "override_applied": override_applied,
        "override_reason": override_set.override_reason,
    }


def apply_source_override(
    *,
    current_audio_source_id: Optional[str],
    current_video_source_id: Optional[str],
    override_set: Optional[OperatorOverrideSet],
) -> Dict[str, Any]:
    """Apply source selection overrides and return a dict of effective values.

    Returns a dict with keys:

    ``effective_audio_source_id``
        The overridden audio source ID, or *current_audio_source_id*.
    ``effective_video_source_id``
        The overridden video source ID, or *current_video_source_id*.
    ``audio_overridden``
        ``True`` when the audio source was changed by an active override.
    ``video_overridden``
        ``True`` when the video source was changed by an active override.
    ``override_reason``
        The ``override_reason`` from the active set (or ``""``).
    """
    if override_set is None or override_set.is_noop or not override_set.is_active:
        return {
            "effective_audio_source_id": current_audio_source_id,
            "effective_video_source_id": current_video_source_id,
            "audio_overridden": False,
            "video_overridden": False,
            "override_reason": "",
        }

    eff_audio = current_audio_source_id
    eff_video = current_video_source_id
    audio_overridden = False
    video_overridden = False

    if override_set.primary_audio_source_id is not None:
        eff_audio = override_set.primary_audio_source_id
        audio_overridden = True

    if override_set.primary_video_source_id is not None:
        eff_video = override_set.primary_video_source_id
        video_overridden = True

    return {
        "effective_audio_source_id": eff_audio,
        "effective_video_source_id": eff_video,
        "audio_overridden": audio_overridden,
        "video_overridden": video_overridden,
        "override_reason": override_set.override_reason,
    }


def build_override_summary(override_snapshot: OperatorOverrideSnapshot) -> Dict[str, Any]:
    """Return a shell-facing summary dict derived from an *override_snapshot*.

    This is the operator-facing summary suitable for display in diagnostics,
    status projections, and audit UIs.  It is derived from the canonical
    snapshot — never an independent truth source.
    """
    if not override_snapshot.has_active_override:
        return {
            "has_active_override": False,
            "applied_domains": [],
            "override_reason": "",
            "operator_message": "override=none automation_default_active",
        }

    domain_str = ", ".join(override_snapshot.applied_domains)
    reason = override_snapshot.override_reason or "unspecified"
    return {
        "has_active_override": True,
        "applied_domains": list(override_snapshot.applied_domains),
        "override_reason": reason,
        "operator_message": (
            f"override=active domains=[{domain_str}] reason={reason!r}"
        ),
    }
