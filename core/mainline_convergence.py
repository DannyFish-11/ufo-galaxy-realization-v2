"""
core/mainline_convergence.py
============================
PR-8 — System Convergence and Final Mainline Integration.

**Purpose**
-----------
This module makes the **mainline execution model** explicit, consistent, and
inspectable.  It does NOT replace any subsystem; it provides the cross-cutting
normalization layer that lets all subsystems speak one coherent language.

After PR-1 through PR-7, Galaxy's subsystems are individually solid:

* OpenClawd      — subject-core orchestration authority
* CapabilityBus  — unified capability directory
* SystemResource — governed external resource layer
* RAGMemory      — unified Knowledge Core entry point
* SelfHealingLoop — mediated engineering loop
* GitHub / Academic — first-class integrated resources

The remaining architectural risk is that these subsystems still use
*slightly different* metadata shapes, trace semantics, and authority
declarations.  This module resolves that risk by providing:

1. **Canonical chain stages** — :class:`MainlineChainStage` names every hop
   in the mainline execution path (request → OpenClawd → capability/resource →
   execution → knowledge writeback) so logging and tracing use the same labels.

2. **Authority declarations** — :class:`MainlineChainAuthority` names which
   component owns each stage, making the architectural hierarchy inspectable.

3. **Normalised metadata frame** — :class:`MainlineMetadataFrame` carries the
   fields that matter for end-to-end traceability (``trace_id``, ``task_id``,
   ``session_id``, ``authority_role``, ``execution_path``, ``source``,
   ``resource_type``, ``capability_source``, ``knowledge_source``).
   :func:`normalize_cross_subsystem_metadata` coerces any raw metadata dict
   into this shape.

4. **Execution trace** — :class:`MainlineExecutionTrace` records one request's
   journey through the mainline chain so tests and diagnostics can verify
   coherence.

5. **Convergence registry** — :class:`MainlineConvergenceRegistry` (singleton)
   accumulates traces and classifies execution paths as
   ``mainline`` / ``compat`` / ``legacy`` so that compatibility code never
   silently becomes the primary path.

**Mainline execution chain**::

    Request
      │  ← stage: REQUEST_INGRESS
      ▼
    OpenClawd.process()
      │  ← stage: OPENCLAWD_AUTHORITY  [authority: OPENCLAWD]
      ├─ capability dispatch ──────────────────────────────────────────────────
      │    ├─ stage: CAPABILITY_DISPATCH  [authority: CAPABILITY_BUS]
      │    ├─ stage: RESOURCE_RESOLUTION  [authority: SYSTEM_RESOURCE_REGISTRY]
      │    └─ stage: EXECUTION            [authority: CANONICAL_DISPATCHER]
      ├─ knowledge flows ──────────────────────────────────────────────────────
      │    ├─ stage: KNOWLEDGE_RECALL      [authority: RAG_MEMORY]
      │    └─ stage: KNOWLEDGE_WRITEBACK   [authority: RAG_MEMORY]
      └─ engineering ──────────────────────────────────────────────────────────
           └─ stage: ENGINEERING_LOOP     [authority: SELF_HEALING_LOOP]

**Fallback / compatibility classification**::

    path_class = "mainline"  — follows the canonical chain above end-to-end
    path_class = "compat"    — uses a compatibility adapter but eventually
                               joins the mainline (secondary, intentional)
    path_class = "legacy"    — bypasses one or more mainline stages (must be
                               recorded and monitored)

**Singletons**::

    mainline_convergence_registry: MainlineConvergenceRegistry
    get_mainline_convergence_registry() -> MainlineConvergenceRegistry
    reset_mainline_convergence_registry() -> None   # test helper

**Constraints**
---------------
* C1  — module-level singleton and ``get_mainline_convergence_registry()``
         accessor.
* C7  — public methods return ``{"success": bool, ...}`` or dataclasses with
         ``to_dict()``.
* C11 — uses stdlib ``logging``.
* No parallel authority or routing is introduced; this is a *documentation and
  normalization layer* only.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.MainlineConvergence")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Canonical ``authority_role`` value stamped by OpenClawd on every response.
OPENCLAWD_AUTHORITY_ROLE: str = "subject_decision_authority"

#: Maximum execution traces kept in the registry before the oldest are evicted.
_MAX_TRACES: int = 200

#: Current PR tag — used for source attribution in metadata frames.
_PR_TAG: str = "pr8_mainline_convergence"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class MainlineChainStage(str, Enum):
    """Canonical hop labels for the mainline execution chain.

    Every significant architectural boundary in the request-to-writeback
    path maps to one of these stages.  Logging and tracing should use these
    labels (rather than ad-hoc strings) so that cross-subsystem comparisons
    are unambiguous.
    """

    REQUEST_INGRESS = "request_ingress"
    """External request arrives at OpenClawd (entry point)."""

    OPENCLAWD_AUTHORITY = "openclawd_authority"
    """OpenClawd acts as the top-level orchestration authority."""

    CAPABILITY_DISPATCH = "capability_dispatch"
    """CapabilityBus resolves which registered capability will handle the request."""

    RESOURCE_RESOLUTION = "resource_resolution"
    """SystemResourceRegistry resolves the governed resource for the capability."""

    EXECUTION = "execution"
    """CanonicalDispatcher / execution substrate performs the action."""

    KNOWLEDGE_RECALL = "knowledge_recall"
    """RAGMemory performs a recall query to enrich the request context."""

    KNOWLEDGE_WRITEBACK = "knowledge_writeback"
    """Execution result is written back into the unified Knowledge Core."""

    ENGINEERING_LOOP = "engineering_loop"
    """SelfHealingLoop mediates a code-modification or self-healing action."""

    RESPONSE_EMISSION = "response_emission"
    """Final response is assembled and returned to the caller."""


class MainlineChainAuthority(str, Enum):
    """Which component owns each mainline chain stage.

    This classification makes the architectural hierarchy inspectable and
    ensures that compatibility adapters are never confused with primary
    authorities.
    """

    OPENCLAWD = "openclawd"
    """OpenClawd is the top-level orchestration authority."""

    CAPABILITY_BUS = "capability_bus"
    """CapabilityBus is the canonical capability directory."""

    SYSTEM_RESOURCE_REGISTRY = "system_resource_registry"
    """SystemResourceRegistry governs all external system resources."""

    CANONICAL_DISPATCHER = "canonical_dispatcher"
    """CanonicalDispatcher is the single execution substrate."""

    RAG_MEMORY = "rag_memory"
    """RAGMemory is the unified Knowledge Core entry point."""

    SELF_HEALING_LOOP = "self_healing_loop"
    """SelfHealingLoop is the mediated engineering authority."""

    COMPAT_ADAPTER = "compat_adapter"
    """A backward-compatibility adapter — secondary, never primary."""

    LEGACY_PATH = "legacy_path"
    """A legacy bypass path — must remain secondary and monitored."""

    UNKNOWN = "unknown"
    """Authority could not be determined."""


# Map each stage to its canonical authority.
STAGE_AUTHORITY: Dict[MainlineChainStage, MainlineChainAuthority] = {
    MainlineChainStage.REQUEST_INGRESS: MainlineChainAuthority.OPENCLAWD,
    MainlineChainStage.OPENCLAWD_AUTHORITY: MainlineChainAuthority.OPENCLAWD,
    MainlineChainStage.CAPABILITY_DISPATCH: MainlineChainAuthority.CAPABILITY_BUS,
    MainlineChainStage.RESOURCE_RESOLUTION: MainlineChainAuthority.SYSTEM_RESOURCE_REGISTRY,
    MainlineChainStage.EXECUTION: MainlineChainAuthority.CANONICAL_DISPATCHER,
    MainlineChainStage.KNOWLEDGE_RECALL: MainlineChainAuthority.RAG_MEMORY,
    MainlineChainStage.KNOWLEDGE_WRITEBACK: MainlineChainAuthority.RAG_MEMORY,
    MainlineChainStage.ENGINEERING_LOOP: MainlineChainAuthority.SELF_HEALING_LOOP,
    MainlineChainStage.RESPONSE_EMISSION: MainlineChainAuthority.OPENCLAWD,
}


class MainlinePathClass(str, Enum):
    """Classification of an execution path relative to the mainline.

    Compatibility adapters must remain ``COMPAT``; they must never be promoted
    to ``MAINLINE`` unless the underlying subsystem is also updated.  Legacy
    paths must be explicitly declared and monitored.
    """

    MAINLINE = "mainline"
    """Follows the canonical chain end-to-end without bypass."""

    COMPAT = "compat"
    """Uses a compatibility adapter but eventually joins the mainline."""

    LEGACY = "legacy"
    """Bypasses one or more mainline stages; must be monitored."""


# ---------------------------------------------------------------------------
# Canonical metadata field names
# ---------------------------------------------------------------------------

#: The set of field names that constitute a fully normalized metadata frame.
#: Subsystems should emit all of these where applicable.
CANONICAL_METADATA_FIELDS: List[str] = [
    "authority_role",
    "execution_path",
    "trace_id",
    "task_id",
    "session_id",
    "source",
    "resource_type",
    "capability_source",
    "knowledge_source",
    "mainline_stage",
    "path_class",
]


# ---------------------------------------------------------------------------
# MainlineMetadataFrame — normalized metadata struct
# ---------------------------------------------------------------------------


@dataclass
class MainlineMetadataFrame:
    """Normalized metadata frame for cross-subsystem traceability.

    All fields have ``None`` as the default so partial frames are valid.
    :func:`normalize_cross_subsystem_metadata` fills as many fields as the
    raw input supports.

    Attributes
    ----------
    authority_role:
        Identifies which authority stamped this metadata.  Should be
        ``"subject_decision_authority"`` for OpenClawd responses.
    execution_path:
        ``"local"`` / ``"cross_device"`` / ``"hybrid"`` / ``"none"``.
    trace_id:
        Stable end-to-end correlation key for this request.
    task_id:
        Identifier for the discrete task within a session (if applicable).
    session_id:
        Caller-assigned session context.
    source:
        Human-readable source label (e.g. ``"openclawd"``, ``"github"``,
        ``"academic"``).
    resource_type:
        :class:`~core.system_resource.SystemResourceType` string value for
        the governed resource that handled this request (if any).
    capability_source:
        :class:`~core.capability_bus.CapabilityBusRole` string value for the
        capability bus entry used (if any).
    knowledge_source:
        Which knowledge backend was used for recall / writeback (if any).
    mainline_stage:
        The :class:`MainlineChainStage` at which this metadata was emitted.
    path_class:
        :class:`MainlinePathClass` classification for this execution path.
    """

    authority_role: Optional[str] = None
    execution_path: Optional[str] = None
    trace_id: Optional[str] = None
    task_id: Optional[str] = None
    session_id: Optional[str] = None
    source: Optional[str] = None
    resource_type: Optional[str] = None
    capability_source: Optional[str] = None
    knowledge_source: Optional[str] = None
    mainline_stage: Optional[str] = None
    path_class: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict (``None`` values included)."""
        return {
            "authority_role": self.authority_role,
            "execution_path": self.execution_path,
            "trace_id": self.trace_id,
            "task_id": self.task_id,
            "session_id": self.session_id,
            "source": self.source,
            "resource_type": self.resource_type,
            "capability_source": self.capability_source,
            "knowledge_source": self.knowledge_source,
            "mainline_stage": self.mainline_stage,
            "path_class": self.path_class,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "MainlineMetadataFrame":
        """Reconstruct a frame from a plain dict (unknown keys ignored)."""
        return cls(
            authority_role=d.get("authority_role"),
            execution_path=d.get("execution_path"),
            trace_id=d.get("trace_id"),
            task_id=d.get("task_id"),
            session_id=d.get("session_id"),
            source=d.get("source"),
            resource_type=d.get("resource_type"),
            capability_source=d.get("capability_source"),
            knowledge_source=d.get("knowledge_source"),
            mainline_stage=d.get("mainline_stage"),
            path_class=d.get("path_class"),
        )

    @property
    def is_mainline(self) -> bool:
        """``True`` when this frame carries the canonical authority role."""
        return self.authority_role == OPENCLAWD_AUTHORITY_ROLE

    @property
    def covered_fields(self) -> List[str]:
        """Return names of non-``None`` canonical fields in this frame."""
        return [f for f in CANONICAL_METADATA_FIELDS if getattr(self, f) is not None]

    @property
    def coverage_ratio(self) -> float:
        """Fraction of canonical fields that are populated (0.0 – 1.0)."""
        if not CANONICAL_METADATA_FIELDS:
            return 1.0
        return len(self.covered_fields) / len(CANONICAL_METADATA_FIELDS)


# ---------------------------------------------------------------------------
# MainlineExecutionTrace — per-request trace record
# ---------------------------------------------------------------------------


@dataclass
class MainlineExecutionTrace:
    """Record of a single request's journey through the mainline chain.

    Attributes
    ----------
    trace_id:
        Stable correlation key — typically ``runtime_session_id`` when routed
        through :class:`~core.desktop_presence_runtime.DesktopPresenceRuntime`,
        otherwise a fresh ``uuid4().hex``.
    session_id:
        Caller-provided session context.
    task_id:
        Optional task-level identifier.
    device_id:
        Device that originated or will execute the request.
    entry_stage:
        The first :class:`MainlineChainStage` recorded for this trace.
    stages_visited:
        Ordered list of stages visited, in call order.
    path_class:
        Classification of the overall path for this trace.
    authority_role:
        Authority role stamped by the primary handler.
    execution_path:
        Execution branch resolved by OpenClawd
        (``"local"`` / ``"cross_device"`` / ``"hybrid"`` / ``"none"``).
    capability_source:
        Capability bus role used (if any).
    knowledge_source:
        Knowledge backend used for recall or writeback (if any).
    resource_type:
        Governed resource type used (if any).
    started_at:
        ``time.time()`` when this trace was opened.
    completed_at:
        ``time.time()`` when this trace was closed (``None`` if still open).
    success:
        Whether the overall request was successful.
    notes:
        Free-form diagnostic notes appended during execution.
    """

    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    session_id: Optional[str] = None
    task_id: Optional[str] = None
    device_id: Optional[str] = None
    entry_stage: Optional[str] = None
    stages_visited: List[str] = field(default_factory=list)
    path_class: str = MainlinePathClass.MAINLINE.value
    authority_role: Optional[str] = None
    execution_path: Optional[str] = None
    capability_source: Optional[str] = None
    knowledge_source: Optional[str] = None
    resource_type: Optional[str] = None
    started_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    success: bool = True
    notes: List[str] = field(default_factory=list)

    def add_stage(self, stage: MainlineChainStage) -> None:
        """Record that *stage* was visited during this trace."""
        stage_val = stage.value if isinstance(stage, MainlineChainStage) else str(stage)
        if stage_val not in self.stages_visited:
            self.stages_visited.append(stage_val)
        if self.entry_stage is None:
            self.entry_stage = stage_val

    def close(self, success: bool = True) -> None:
        """Mark this trace as completed."""
        self.completed_at = time.time()
        self.success = success

    @property
    def elapsed_ms(self) -> Optional[float]:
        """Elapsed time in milliseconds, or ``None`` if not yet closed."""
        if self.completed_at is None:
            return None
        return round((self.completed_at - self.started_at) * 1000, 1)

    @property
    def is_open(self) -> bool:
        """``True`` while the trace has not been closed yet."""
        return self.completed_at is None

    @property
    def visits_openclawd(self) -> bool:
        """``True`` when the trace passed through the OpenClawd authority stage."""
        return MainlineChainStage.OPENCLAWD_AUTHORITY.value in self.stages_visited

    @property
    def visits_capability_dispatch(self) -> bool:
        """``True`` when capability dispatch was used."""
        return MainlineChainStage.CAPABILITY_DISPATCH.value in self.stages_visited

    @property
    def visits_knowledge(self) -> bool:
        """``True`` when any knowledge-core stage was visited."""
        return (
            MainlineChainStage.KNOWLEDGE_RECALL.value in self.stages_visited
            or MainlineChainStage.KNOWLEDGE_WRITEBACK.value in self.stages_visited
        )

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable representation."""
        return {
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "device_id": self.device_id,
            "entry_stage": self.entry_stage,
            "stages_visited": list(self.stages_visited),
            "path_class": self.path_class,
            "authority_role": self.authority_role,
            "execution_path": self.execution_path,
            "capability_source": self.capability_source,
            "knowledge_source": self.knowledge_source,
            "resource_type": self.resource_type,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "elapsed_ms": self.elapsed_ms,
            "success": self.success,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "MainlineExecutionTrace":
        """Reconstruct from a plain dict (unknown keys ignored)."""
        obj = cls(
            trace_id=d.get("trace_id", uuid.uuid4().hex),
            session_id=d.get("session_id"),
            task_id=d.get("task_id"),
            device_id=d.get("device_id"),
            entry_stage=d.get("entry_stage"),
            stages_visited=list(d.get("stages_visited") or []),
            path_class=d.get("path_class", MainlinePathClass.MAINLINE.value),
            authority_role=d.get("authority_role"),
            execution_path=d.get("execution_path"),
            capability_source=d.get("capability_source"),
            knowledge_source=d.get("knowledge_source"),
            resource_type=d.get("resource_type"),
            started_at=d.get("started_at", time.time()),
            completed_at=d.get("completed_at"),
            success=d.get("success", True),
            notes=list(d.get("notes") or []),
        )
        return obj


# ---------------------------------------------------------------------------
# MainlineConvergenceSnapshot
# ---------------------------------------------------------------------------


@dataclass
class MainlineConvergenceSnapshot:
    """Point-in-time snapshot of the convergence registry state.

    Attributes
    ----------
    total_traces:
        Total number of traces recorded since last reset.
    mainline_count:
        Traces classified as ``MAINLINE``.
    compat_count:
        Traces classified as ``COMPAT``.
    legacy_count:
        Traces classified as ``LEGACY``.
    recent_traces:
        Up to 10 most recent trace dicts (most recent first).
    stage_visit_counts:
        How many traces visited each stage.
    openclawd_coverage:
        Fraction of traces that visited ``OPENCLAWD_AUTHORITY`` stage.
    knowledge_coverage:
        Fraction of traces that visited at least one knowledge-core stage.
    snapshotted_at:
        ``time.time()`` when the snapshot was built.
    """

    total_traces: int = 0
    mainline_count: int = 0
    compat_count: int = 0
    legacy_count: int = 0
    recent_traces: List[Dict[str, Any]] = field(default_factory=list)
    stage_visit_counts: Dict[str, int] = field(default_factory=dict)
    openclawd_coverage: float = 0.0
    knowledge_coverage: float = 0.0
    snapshotted_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable representation."""
        return {
            "total_traces": self.total_traces,
            "mainline_count": self.mainline_count,
            "compat_count": self.compat_count,
            "legacy_count": self.legacy_count,
            "recent_traces": self.recent_traces,
            "stage_visit_counts": dict(self.stage_visit_counts),
            "openclawd_coverage": self.openclawd_coverage,
            "knowledge_coverage": self.knowledge_coverage,
            "snapshotted_at": self.snapshotted_at,
        }


# ---------------------------------------------------------------------------
# normalize_cross_subsystem_metadata
# ---------------------------------------------------------------------------


def normalize_cross_subsystem_metadata(raw: Dict[str, Any]) -> MainlineMetadataFrame:
    """Coerce a raw metadata dict from any subsystem into a canonical frame.

    This function is *lenient* — it never raises even if the input is empty or
    malformed.  Unknown keys are ignored; missing canonical keys remain as
    ``None`` in the output frame.

    The normalisation rules applied:

    * ``authority_role`` — accepted as-is; ``"openclawd"`` is promoted to
      :data:`OPENCLAWD_AUTHORITY_ROLE`.
    * ``execution_path`` — accepted as-is; validated to be one of the four
      known values (``"local"``, ``"cross_device"``, ``"hybrid"``,
      ``"none"``).  Unrecognised values are kept but flagged in ``notes``.
    * ``trace_id`` — accepted as-is; falls back to ``runtime_session_id`` or
      ``request_id`` if missing.
    * ``task_id`` — accepted as-is.
    * ``session_id`` — accepted as-is.
    * ``source`` — accepted as-is; ``"github__*"`` prefixes infer
      ``resource_type = "github"`` when not set.
    * ``resource_type`` — accepted as-is.
    * ``capability_source`` — accepted as-is.
    * ``knowledge_source`` — accepted as-is.
    * ``mainline_stage`` — accepted as-is; validated against
      :class:`MainlineChainStage` values.
    * ``path_class`` — accepted as-is; validated against
      :class:`MainlinePathClass` values.

    Parameters
    ----------
    raw:
        Arbitrary metadata dict from any subsystem response.

    Returns
    -------
    MainlineMetadataFrame
        A normalized, canonical metadata frame.
    """
    if not isinstance(raw, dict):
        return MainlineMetadataFrame()

    _VALID_EXEC_PATHS = {"local", "cross_device", "hybrid", "none"}
    _VALID_STAGES = {s.value for s in MainlineChainStage}
    _VALID_PATH_CLASSES = {p.value for p in MainlinePathClass}

    # authority_role
    authority_role = raw.get("authority_role")
    if authority_role == "openclawd":
        authority_role = OPENCLAWD_AUTHORITY_ROLE

    # execution_path
    execution_path = raw.get("execution_path")
    if execution_path is not None and execution_path not in _VALID_EXEC_PATHS:
        logger.debug(
            "normalize_cross_subsystem_metadata: unrecognised execution_path=%r (kept)",
            execution_path,
        )

    # trace_id — fallback chain
    trace_id = (
        raw.get("trace_id")
        or raw.get("runtime_session_id")
        or raw.get("request_id")
    )

    # task_id
    task_id = raw.get("task_id")

    # session_id
    session_id = raw.get("session_id")

    # source
    source = raw.get("source")

    # resource_type — infer from source prefix when absent.
    # Use delimiter check (__) to avoid matching substrings of longer names.
    resource_type = raw.get("resource_type")
    if resource_type is None and isinstance(source, str):
        for _prefix in ("github", "academic", "device", "local_tool", "engineering", "mcp", "skill", "node"):
            if source == _prefix or source.startswith(_prefix + "__"):
                resource_type = _prefix
                break

    # capability_source
    capability_source = raw.get("capability_source")

    # knowledge_source
    knowledge_source = raw.get("knowledge_source")

    # mainline_stage
    mainline_stage = raw.get("mainline_stage")
    if mainline_stage is not None and mainline_stage not in _VALID_STAGES:
        logger.debug(
            "normalize_cross_subsystem_metadata: unrecognised mainline_stage=%r (kept)",
            mainline_stage,
        )

    # path_class
    path_class = raw.get("path_class")
    if path_class is not None and path_class not in _VALID_PATH_CLASSES:
        logger.debug(
            "normalize_cross_subsystem_metadata: unrecognised path_class=%r (kept)",
            path_class,
        )

    return MainlineMetadataFrame(
        authority_role=authority_role,
        execution_path=execution_path,
        trace_id=trace_id,
        task_id=task_id,
        session_id=session_id,
        source=source,
        resource_type=resource_type,
        capability_source=capability_source,
        knowledge_source=knowledge_source,
        mainline_stage=mainline_stage,
        path_class=path_class,
    )


# ---------------------------------------------------------------------------
# build_mainline_trace
# ---------------------------------------------------------------------------


def build_mainline_trace(
    *,
    trace_id: Optional[str] = None,
    session_id: Optional[str] = None,
    task_id: Optional[str] = None,
    device_id: Optional[str] = None,
    entry_stage: Optional[MainlineChainStage] = None,
    execution_path: Optional[str] = None,
    authority_role: Optional[str] = None,
    path_class: Optional[MainlinePathClass] = None,
    capability_source: Optional[str] = None,
    knowledge_source: Optional[str] = None,
    resource_type: Optional[str] = None,
) -> MainlineExecutionTrace:
    """Convenience builder for a :class:`MainlineExecutionTrace`.

    Parameters
    ----------
    trace_id:
        Stable correlation key — defaults to a new ``uuid4().hex`` when absent.
    session_id:
        Caller-provided session context.
    task_id:
        Optional task-level identifier.
    device_id:
        Device that originated or will execute the request.
    entry_stage:
        First stage to record on the trace.
    execution_path:
        Execution branch resolved by OpenClawd.
    authority_role:
        Authority role — defaults to :data:`OPENCLAWD_AUTHORITY_ROLE` when
        *entry_stage* is ``OPENCLAWD_AUTHORITY``.
    path_class:
        Path classification — defaults to ``MAINLINE``.
    capability_source:
        Capability bus role used (if any).
    knowledge_source:
        Knowledge backend used (if any).
    resource_type:
        Governed resource type used (if any).

    Returns
    -------
    MainlineExecutionTrace
    """
    _trace_id = trace_id or uuid.uuid4().hex

    # Default authority_role for canonical mainline entry
    _authority_role = authority_role
    if _authority_role is None and entry_stage == MainlineChainStage.OPENCLAWD_AUTHORITY:
        _authority_role = OPENCLAWD_AUTHORITY_ROLE

    _path_class = (path_class or MainlinePathClass.MAINLINE).value

    trace = MainlineExecutionTrace(
        trace_id=_trace_id,
        session_id=session_id,
        task_id=task_id,
        device_id=device_id,
        path_class=_path_class,
        authority_role=_authority_role,
        execution_path=execution_path,
        capability_source=capability_source,
        knowledge_source=knowledge_source,
        resource_type=resource_type,
    )

    if entry_stage is not None:
        trace.add_stage(entry_stage)

    return trace


# ---------------------------------------------------------------------------
# MainlineConvergenceRegistry — singleton
# ---------------------------------------------------------------------------


class MainlineConvergenceRegistry:
    """Singleton registry that accumulates mainline execution traces.

    Responsibilities
    ----------------
    * Accept :class:`MainlineExecutionTrace` objects and store them up to
      ``max_traces`` (oldest evicted when full).
    * Classify the path of each trace (``mainline`` / ``compat`` / ``legacy``).
    * Expose aggregate statistics via :meth:`snapshot` so tests and dashboards
      can verify that the mainline is actually the dominant path.
    * Enforce that compatibility adapters never promote themselves to primary
      authority (``path_class != "mainline"`` traces are logged as warnings).

    Thread-safety
    -------------
    All mutating operations are guarded by a ``threading.Lock``.
    """

    def __init__(self, max_traces: int = _MAX_TRACES) -> None:
        self._lock = threading.Lock()
        self._max_traces = max_traces
        self._traces: List[MainlineExecutionTrace] = []
        self._stage_counters: Dict[str, int] = {}
        self._path_class_counters: Dict[str, int] = {
            MainlinePathClass.MAINLINE.value: 0,
            MainlinePathClass.COMPAT.value: 0,
            MainlinePathClass.LEGACY.value: 0,
        }

    # ------------------------------------------------------------------
    # record
    # ------------------------------------------------------------------

    def record(self, trace: MainlineExecutionTrace) -> None:
        """Record a completed (or in-progress) :class:`MainlineExecutionTrace`.

        If the trace's ``path_class`` is not ``MAINLINE``, a warning is
        emitted so that non-canonical paths remain visible and monitored.

        Parameters
        ----------
        trace:
            The trace to record.
        """
        if not isinstance(trace, MainlineExecutionTrace):
            logger.warning(
                "MainlineConvergenceRegistry.record: expected MainlineExecutionTrace, "
                "got %s — skipping",
                type(trace).__name__,
            )
            return

        with self._lock:
            # Evict oldest when full
            if len(self._traces) >= self._max_traces:
                self._traces.pop(0)
            self._traces.append(trace)

            # Update path-class counters
            pc = trace.path_class or MainlinePathClass.MAINLINE.value
            self._path_class_counters[pc] = self._path_class_counters.get(pc, 0) + 1

            # Update per-stage visit counters
            for stage in trace.stages_visited:
                self._stage_counters[stage] = self._stage_counters.get(stage, 0) + 1

        # Emit warning for non-mainline paths (outside lock for simplicity)
        if trace.path_class and trace.path_class != MainlinePathClass.MAINLINE.value:
            logger.warning(
                "MainlineConvergenceRegistry: non-mainline trace recorded "
                "trace_id=%s path_class=%s stages=%s",
                trace.trace_id,
                trace.path_class,
                trace.stages_visited,
            )
        else:
            logger.debug(
                "MainlineConvergenceRegistry: mainline trace recorded trace_id=%s",
                trace.trace_id,
            )

    # ------------------------------------------------------------------
    # record_from_response
    # ------------------------------------------------------------------

    def record_from_response(self, response: Dict[str, Any]) -> Optional[MainlineExecutionTrace]:
        """Extract and record a trace from an OpenClawd response dict.

        Convenience method — builds a :class:`MainlineExecutionTrace` from
        the ``metadata`` sub-dict of a typical ``OpenClawd.process()``
        response.  Returns the recorded trace (or ``None`` if the response
        is empty/malformed).

        Parameters
        ----------
        response:
            A dict as returned by ``OpenClawd.process()``.

        Returns
        -------
        MainlineExecutionTrace or None
        """
        if not isinstance(response, dict):
            return None

        meta: Dict[str, Any] = response.get("metadata") or {}
        frame = normalize_cross_subsystem_metadata(meta)

        trace = build_mainline_trace(
            trace_id=frame.trace_id,
            session_id=frame.session_id,
            task_id=frame.task_id,
            execution_path=frame.execution_path,
            authority_role=frame.authority_role,
            path_class=(
                MainlinePathClass(frame.path_class)
                if frame.path_class in {p.value for p in MainlinePathClass}
                else MainlinePathClass.MAINLINE
            ),
            capability_source=frame.capability_source,
            knowledge_source=frame.knowledge_source,
            resource_type=frame.resource_type,
            entry_stage=MainlineChainStage.OPENCLAWD_AUTHORITY,
        )
        trace.success = bool(response.get("success", True))
        trace.close(success=trace.success)

        # Stamp mainline_convergence in the response so callers can see it
        response["mainline_convergence"] = {
            "trace_id": trace.trace_id,
            "path_class": trace.path_class,
            "stages_visited": list(trace.stages_visited),
            "authority_role": trace.authority_role,
        }

        self.record(trace)
        return trace

    # ------------------------------------------------------------------
    # lookup
    # ------------------------------------------------------------------

    def lookup(self, trace_id: str) -> Optional[MainlineExecutionTrace]:
        """Return the trace for *trace_id*, or ``None`` if not found."""
        with self._lock:
            for t in reversed(self._traces):
                if t.trace_id == trace_id:
                    return t
        return None

    # ------------------------------------------------------------------
    # list_all
    # ------------------------------------------------------------------

    def list_all(self) -> List[MainlineExecutionTrace]:
        """Return a shallow copy of all recorded traces (oldest first)."""
        with self._lock:
            return list(self._traces)

    # ------------------------------------------------------------------
    # list_by_path_class
    # ------------------------------------------------------------------

    def list_by_path_class(self, path_class: MainlinePathClass) -> List[MainlineExecutionTrace]:
        """Return traces whose ``path_class`` matches *path_class*."""
        target = path_class.value
        with self._lock:
            return [t for t in self._traces if t.path_class == target]

    # ------------------------------------------------------------------
    # snapshot
    # ------------------------------------------------------------------

    def snapshot(self) -> MainlineConvergenceSnapshot:
        """Return a point-in-time :class:`MainlineConvergenceSnapshot`."""
        with self._lock:
            total = len(self._traces)
            mainline_count = self._path_class_counters.get(MainlinePathClass.MAINLINE.value, 0)
            compat_count = self._path_class_counters.get(MainlinePathClass.COMPAT.value, 0)
            legacy_count = self._path_class_counters.get(MainlinePathClass.LEGACY.value, 0)
            recent = [t.to_dict() for t in reversed(self._traces[-10:])]
            stage_counts = dict(self._stage_counters)
            openclawd_stage = MainlineChainStage.OPENCLAWD_AUTHORITY.value
            openclawd_hits = stage_counts.get(openclawd_stage, 0)
            knowledge_hits = (
                stage_counts.get(MainlineChainStage.KNOWLEDGE_RECALL.value, 0)
                + stage_counts.get(MainlineChainStage.KNOWLEDGE_WRITEBACK.value, 0)
            )

        openclawd_coverage = min(1.0, (openclawd_hits / total)) if total > 0 else 0.0
        # knowledge_coverage: fraction of traces that visited at least one
        # knowledge stage.  Bounded at 1.0 because a single trace may visit
        # both KNOWLEDGE_RECALL and KNOWLEDGE_WRITEBACK, making knowledge_hits
        # potentially exceed total.  openclawd_coverage uses the same bound
        # for consistency.
        knowledge_coverage = min(1.0, (knowledge_hits / total)) if total > 0 else 0.0

        return MainlineConvergenceSnapshot(
            total_traces=total,
            mainline_count=mainline_count,
            compat_count=compat_count,
            legacy_count=legacy_count,
            recent_traces=recent,
            stage_visit_counts=stage_counts,
            openclawd_coverage=openclawd_coverage,
            knowledge_coverage=knowledge_coverage,
        )

    # ------------------------------------------------------------------
    # assert_mainline_dominant
    # ------------------------------------------------------------------

    def assert_mainline_dominant(self, min_ratio: float = 0.5) -> bool:
        """Return ``True`` when mainline traces dominate.

        Parameters
        ----------
        min_ratio:
            Minimum fraction of total traces that must be classified as
            ``MAINLINE`` for the check to pass.  Defaults to ``0.5``.

        Returns
        -------
        bool
            ``True`` when the mainline fraction ≥ *min_ratio*.
        """
        snap = self.snapshot()
        if snap.total_traces == 0:
            return True  # vacuously true — no legacy paths recorded
        ratio = snap.mainline_count / snap.total_traces
        ok = ratio >= min_ratio
        if not ok:
            logger.warning(
                "MainlineConvergenceRegistry.assert_mainline_dominant FAILED: "
                "mainline_ratio=%.2f < min_ratio=%.2f",
                ratio,
                min_ratio,
            )
        return ok

    # ------------------------------------------------------------------
    # reset (test helper)
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Clear all recorded traces (test helper — do not call in production)."""
        with self._lock:
            self._traces.clear()
            self._stage_counters.clear()
            self._path_class_counters = {
                MainlinePathClass.MAINLINE.value: 0,
                MainlinePathClass.COMPAT.value: 0,
                MainlinePathClass.LEGACY.value: 0,
            }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

mainline_convergence_registry: MainlineConvergenceRegistry = MainlineConvergenceRegistry()
"""Module-level singleton.  Use :func:`get_mainline_convergence_registry` for
safe access (respects test resets)."""

_registry_lock = threading.Lock()


def get_mainline_convergence_registry() -> MainlineConvergenceRegistry:
    """Return the module-level :class:`MainlineConvergenceRegistry` singleton.

    Safe to call from any context.  The singleton is created once at import
    time; subsequent calls return the same object.
    """
    return mainline_convergence_registry


def reset_mainline_convergence_registry() -> None:
    """Reset the module-level singleton (test helper).

    Clears all recorded traces and resets counters.  Do **not** call this in
    production code.
    """
    mainline_convergence_registry.reset()
    logger.debug("MainlineConvergenceRegistry reset (test helper invoked)")


# ---------------------------------------------------------------------------
# record_mainline_execution — thin convenience wrapper
# ---------------------------------------------------------------------------


def record_mainline_execution(
    *,
    trace_id: Optional[str] = None,
    session_id: Optional[str] = None,
    task_id: Optional[str] = None,
    device_id: Optional[str] = None,
    stages: Optional[List[MainlineChainStage]] = None,
    execution_path: Optional[str] = None,
    path_class: Optional[MainlinePathClass] = None,
    authority_role: Optional[str] = None,
    capability_source: Optional[str] = None,
    knowledge_source: Optional[str] = None,
    resource_type: Optional[str] = None,
    success: bool = True,
    notes: Optional[List[str]] = None,
) -> MainlineExecutionTrace:
    """Build, close, and record a :class:`MainlineExecutionTrace` in one call.

    Convenience function for callers that want to log a completed execution
    without manually managing a trace object.  The trace is immediately
    recorded in the module-level registry.

    Parameters
    ----------
    trace_id … resource_type:
        As per :func:`build_mainline_trace`.
    success:
        Whether the execution was successful.
    notes:
        Optional free-form diagnostic notes.

    Returns
    -------
    MainlineExecutionTrace
        The recorded trace.
    """
    _entry = MainlineChainStage.OPENCLAWD_AUTHORITY
    if stages:
        _entry = stages[0]

    trace = build_mainline_trace(
        trace_id=trace_id,
        session_id=session_id,
        task_id=task_id,
        device_id=device_id,
        entry_stage=_entry,
        execution_path=execution_path,
        path_class=path_class,
        authority_role=authority_role,
        capability_source=capability_source,
        knowledge_source=knowledge_source,
        resource_type=resource_type,
    )

    if stages:
        for s in stages[1:]:
            trace.add_stage(s)

    if notes:
        trace.notes.extend(notes)

    trace.close(success=success)
    get_mainline_convergence_registry().record(trace)
    return trace
