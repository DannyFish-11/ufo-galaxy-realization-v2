"""
windows_client/status_board_v2/topology_history.py
===================================================
PR-14: Observability and history layer.

Provides a **history and observability surface** for the desktop topology /
status board that records and represents recent state changes over time —
readiness transitions, authority changes, provider/routing changes, and
OneAPI lower-horizon status summaries — safely and without breaking the
semantic guarantees established by PR-4 through PR-13.

Design constraints
------------------
- **Built on the PR-9 through PR-13 pipeline** — history entries and snapshots
  are always derived from a
  :class:`~windows_client.status_board_v2.topology_inspector.InspectionReport`
  (PR-13), a
  :class:`~windows_client.status_board_v2.topology_layout.TopologyConstellationLayout`
  (PR-11/12), or a
  :class:`~core.desktop_consumption_adapter.DesktopClientViewModel` (PR-9).
  The recorder never bypasses these layers to reconstruct truth from raw nested
  payload dicts.
- **Safe authority semantics over time** — history output preserves the same
  semantic guarantees as the live view.  Degraded / fallback history records
  are never re-promoted to authoritative truth.  Every
  :class:`TopologyHistoryEntry` and :class:`TopologySnapshot` carries an
  explicit ``is_authoritative`` flag that matches the source readiness state.
- **OneAPI stays lower-horizon in history** — all
  :class:`OneAPIHistorySummary` objects carry an explicit
  ``is_lower_horizon_only=True`` flag regardless of historical state.  OneAPI
  is never returned as a canonical routing peer in any historical view.
- **Read-only** — the history recorder never sends commands or modifies system
  state.
- **Graceful** — all recorder paths handle ``None`` / missing inputs without
  raising.

Key classes
-----------
:class:`TopologyChangeKind`
    Enumeration of recognisable topology change event types.
:class:`ReadinessTransitionRecord`
    Records a readiness state transition (e.g. ``canonical`` → ``degraded``).
:class:`AuthorityChangeRecord`
    Records a change in topology authority (authoritative → non-authoritative
    or vice-versa).
:class:`RoutingChangeRecord`
    Records a provider or routing selection change.
:class:`OneAPIHistorySummary`
    Historical OneAPI lower-horizon status summary (always
    ``is_lower_horizon_only=True``).
:class:`TopologyHistoryEntry`
    A single timestamped history entry capturing one observable change event.
:class:`TopologySnapshot`
    A point-in-time snapshot of the complete topology readiness/authority/
    routing state, suitable for diffing against a later snapshot.
:class:`TopologyHistoryBuffer`
    A bounded in-memory buffer that accumulates
    :class:`TopologyHistoryEntry` objects.
:class:`TopologyHistoryRecorder`
    The main observability surface.  Derives history entries and snapshots
    from the PR-9/PR-11/PR-12/PR-13 pipeline output.

Usage::

    from windows_client.status_board_v2.topology_history import (
        TopologyHistoryRecorder,
        TopologyHistoryBuffer,
        TOPOLOGY_HISTORY_AUTHORITY,
    )
    from windows_client.status_board_v2.topology_inspector import TopologyInspector
    from windows_client.status_board_v2.topology_layout import build_constellation_layout
    from core.desktop_consumption_adapter import adapt_integration_payload

    vm = adapt_integration_payload(payload)
    layout = build_constellation_layout(vm)
    inspector = TopologyInspector()
    report = inspector.inspect_layout(layout)

    recorder = TopologyHistoryRecorder()
    buf = TopologyHistoryBuffer(max_size=50)

    # Record a history entry from the current inspection report
    entry = recorder.record_from_inspection_report(report)
    if entry:
        buf.add_entry(entry)

    # Take a point-in-time snapshot
    snap = recorder.snapshot_from_inspection_report(report)
    print(snap.readiness_label)          # "canonical"
    print(snap.is_authoritative)         # True
    print(snap.oneapi_horizon_present)   # True/False

    # Compare two snapshots (same or different moments)
    diff = recorder.compare_snapshots(snap_before, snap_after)
    print(diff["readiness_changed"])     # True/False
    print(diff["authority_changed"])     # True/False

    # Inspect history buffer
    for e in buf.entries:
        print(e.change_kind, e.readiness_label, e.is_authoritative)

See ``docs/OBSERVABILITY_HISTORY.md`` for full design rationale.
"""

from __future__ import annotations

import json
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# PR-14: History / observability authority sentinel
# ---------------------------------------------------------------------------

#: Sentinel string that identifies the observability/history layer introduced
#: in PR-14.  Downstream consumers can check this value to confirm that a
#: :class:`TopologyHistoryEntry` or :class:`TopologySnapshot` was produced by
#: the canonical PR-14 recorder rather than assembled ad-hoc.
TOPOLOGY_HISTORY_AUTHORITY: str = (
    "windows_client.status_board_v2.topology_history.TopologyHistoryRecorder"
)


# ---------------------------------------------------------------------------
# TopologyChangeKind — enumeration of observable change event types
# ---------------------------------------------------------------------------

class TopologyChangeKind(str, Enum):
    """PR-14: Kind of observable topology change event.

    Values
    ------
    readiness_transition
        The readiness label changed (e.g. ``canonical`` → ``degraded``).
    authority_changed
        The ``is_authoritative`` flag flipped.
    provider_changed
        The primary provider / ``provider_id`` changed.
    routing_changed
        The routing authority source or active route selection changed.
    oneapi_status_changed
        The OneAPI lower-horizon summary changed.
    topology_degraded
        The topology entered a degraded, partial, or unavailable state.
    topology_recovered
        The topology recovered from a degraded/partial/unavailable state back
        to a canonical state.
    snapshot_only
        No specific change was detected; entry was produced as a periodic
        observability snapshot.
    """

    readiness_transition = "readiness_transition"
    authority_changed = "authority_changed"
    provider_changed = "provider_changed"
    routing_changed = "routing_changed"
    oneapi_status_changed = "oneapi_status_changed"
    topology_degraded = "topology_degraded"
    topology_recovered = "topology_recovered"
    snapshot_only = "snapshot_only"


# ---------------------------------------------------------------------------
# ReadinessTransitionRecord
# ---------------------------------------------------------------------------

class ReadinessTransitionRecord:
    """PR-14: Records a readiness state transition.

    Captures the ``from``/``to`` readiness labels and the corresponding
    authority flags, together with a human-readable ``transition_note``.

    Attributes
    ----------
    from_readiness:
        Readiness label before the transition (e.g. ``"canonical"``).
    to_readiness:
        Readiness label after the transition (e.g. ``"degraded"``).
    was_authoritative:
        Whether the *previous* state was authoritative.
    became_authoritative:
        Whether the *new* state is authoritative.
    transition_note:
        Human-readable description of the transition, including an explicit
        note when the new state is non-authoritative.
    """

    def __init__(
        self,
        *,
        from_readiness: str,
        to_readiness: str,
        was_authoritative: bool,
        became_authoritative: bool,
        transition_note: str,
    ) -> None:
        self.from_readiness: str = from_readiness
        self.to_readiness: str = to_readiness
        self.was_authoritative: bool = was_authoritative
        self.became_authoritative: bool = became_authoritative
        self.transition_note: str = transition_note

    def to_dict(self) -> Dict[str, Any]:
        return {
            "from_readiness": self.from_readiness,
            "to_readiness": self.to_readiness,
            "was_authoritative": self.was_authoritative,
            "became_authoritative": self.became_authoritative,
            "transition_note": self.transition_note,
        }

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"ReadinessTransitionRecord("
            f"from_readiness={self.from_readiness!r}, "
            f"to_readiness={self.to_readiness!r}, "
            f"was_authoritative={self.was_authoritative}, "
            f"became_authoritative={self.became_authoritative})"
        )


# ---------------------------------------------------------------------------
# AuthorityChangeRecord
# ---------------------------------------------------------------------------

class AuthorityChangeRecord:
    """PR-14: Records a change in topology authority.

    Attributes
    ----------
    from_authoritative:
        Whether the topology was authoritative before the change.
    to_authoritative:
        Whether the topology is authoritative after the change.
    from_label:
        Readiness label before the change.
    to_label:
        Readiness label after the change.
    change_note:
        Human-readable description.  Explicitly notes when the transition is
        into a non-authoritative / fallback state.
    """

    def __init__(
        self,
        *,
        from_authoritative: bool,
        to_authoritative: bool,
        from_label: str,
        to_label: str,
        change_note: str,
    ) -> None:
        self.from_authoritative: bool = from_authoritative
        self.to_authoritative: bool = to_authoritative
        self.from_label: str = from_label
        self.to_label: str = to_label
        self.change_note: str = change_note

    def to_dict(self) -> Dict[str, Any]:
        return {
            "from_authoritative": self.from_authoritative,
            "to_authoritative": self.to_authoritative,
            "from_label": self.from_label,
            "to_label": self.to_label,
            "change_note": self.change_note,
        }

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"AuthorityChangeRecord("
            f"from_authoritative={self.from_authoritative}, "
            f"to_authoritative={self.to_authoritative}, "
            f"from_label={self.from_label!r}, "
            f"to_label={self.to_label!r})"
        )


# ---------------------------------------------------------------------------
# RoutingChangeRecord
# ---------------------------------------------------------------------------

class RoutingChangeRecord:
    """PR-14: Records a provider or routing selection change.

    Attributes
    ----------
    from_provider:
        Provider identifier before the change (may be ``None`` if unknown).
    to_provider:
        Provider identifier after the change (may be ``None`` if unknown).
    from_source:
        Routing authority source string before the change.
    to_source:
        Routing authority source string after the change.
    change_note:
        Human-readable description of the routing change.
    """

    def __init__(
        self,
        *,
        from_provider: Optional[str],
        to_provider: Optional[str],
        from_source: Optional[str],
        to_source: Optional[str],
        change_note: str,
    ) -> None:
        self.from_provider: Optional[str] = from_provider
        self.to_provider: Optional[str] = to_provider
        self.from_source: Optional[str] = from_source
        self.to_source: Optional[str] = to_source
        self.change_note: str = change_note

    def to_dict(self) -> Dict[str, Any]:
        return {
            "from_provider": self.from_provider,
            "to_provider": self.to_provider,
            "from_source": self.from_source,
            "to_source": self.to_source,
            "change_note": self.change_note,
        }

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"RoutingChangeRecord("
            f"from_provider={self.from_provider!r}, "
            f"to_provider={self.to_provider!r})"
        )


# ---------------------------------------------------------------------------
# OneAPIHistorySummary
# ---------------------------------------------------------------------------

class OneAPIHistorySummary:
    """PR-14: Historical OneAPI lower-horizon status summary.

    This object is **always** ``is_lower_horizon_only=True``.  OneAPI is never
    represented as a canonical routing peer in any historical view.

    Attributes
    ----------
    horizon_status:
        Short status string describing the OneAPI lower-horizon state at the
        time of recording (e.g. ``"present"``, ``"absent"``, ``"degraded"``).
    is_lower_horizon_only:
        Always ``True`` — OneAPI is never a canonical routing peer.
    summary_note:
        Human-readable note about the OneAPI lower-horizon state.  Always
        explicitly states the lower-horizon-only constraint.
    """

    def __init__(
        self,
        *,
        horizon_status: str,
        summary_note: str,
    ) -> None:
        self.horizon_status: str = horizon_status
        self.is_lower_horizon_only: bool = True  # invariant — always True
        self.summary_note: str = summary_note

    def to_dict(self) -> Dict[str, Any]:
        return {
            "horizon_status": self.horizon_status,
            "is_lower_horizon_only": self.is_lower_horizon_only,
            "summary_note": self.summary_note,
        }

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"OneAPIHistorySummary("
            f"horizon_status={self.horizon_status!r}, "
            f"is_lower_horizon_only={self.is_lower_horizon_only})"
        )


# ---------------------------------------------------------------------------
# TopologyHistoryEntry
# ---------------------------------------------------------------------------

class TopologyHistoryEntry:
    """PR-14: A single timestamped history entry capturing one observable change.

    Each entry records the kind of change, the readiness/authority state at
    the time of recording, and optional sub-records for the specific change
    type (readiness transition, authority change, routing change, OneAPI
    summary).

    Attributes
    ----------
    entry_id:
        Unique identifier for this entry.
    change_kind:
        :class:`TopologyChangeKind` value describing the type of change.
    readiness_label:
        Readiness label at the time of recording (``"canonical"``,
        ``"degraded"``, ``"partial"``, or ``"unavailable"``).
    is_authoritative:
        Whether the topology was considered authoritative at the time of
        recording.  Degraded/fallback entries always have ``is_authoritative``
        set to ``False``.
    is_degraded:
        Whether the topology was in a degraded state.
    is_partial:
        Whether the topology was in a partial state.
    is_unavailable:
        Whether the topology was unavailable.
    readiness_transition:
        Optional :class:`ReadinessTransitionRecord` if this entry records a
        readiness transition.
    authority_change:
        Optional :class:`AuthorityChangeRecord` if this entry records an
        authority change.
    routing_change:
        Optional :class:`RoutingChangeRecord` if this entry records a routing
        or provider change.
    oneapi_summary:
        Optional :class:`OneAPIHistorySummary` — always lower-horizon only.
    source_authority:
        Authority sentinel of the recorder that produced this entry.
    """

    def __init__(
        self,
        *,
        change_kind: TopologyChangeKind,
        readiness_label: str,
        is_authoritative: bool,
        is_degraded: bool,
        is_partial: bool,
        is_unavailable: bool,
        readiness_transition: Optional[ReadinessTransitionRecord] = None,
        authority_change: Optional[AuthorityChangeRecord] = None,
        routing_change: Optional[RoutingChangeRecord] = None,
        oneapi_summary: Optional[OneAPIHistorySummary] = None,
        source_authority: str = TOPOLOGY_HISTORY_AUTHORITY,
    ) -> None:
        self.entry_id: str = str(uuid.uuid4())
        self.change_kind: TopologyChangeKind = change_kind
        self.readiness_label: str = readiness_label
        self.is_authoritative: bool = is_authoritative
        self.is_degraded: bool = is_degraded
        self.is_partial: bool = is_partial
        self.is_unavailable: bool = is_unavailable
        self.readiness_transition: Optional[ReadinessTransitionRecord] = readiness_transition
        self.authority_change: Optional[AuthorityChangeRecord] = authority_change
        self.routing_change: Optional[RoutingChangeRecord] = routing_change
        self.oneapi_summary: Optional[OneAPIHistorySummary] = oneapi_summary
        self.source_authority: str = source_authority

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "entry_id": self.entry_id,
            "change_kind": self.change_kind.value,
            "readiness_label": self.readiness_label,
            "is_authoritative": self.is_authoritative,
            "is_degraded": self.is_degraded,
            "is_partial": self.is_partial,
            "is_unavailable": self.is_unavailable,
            "source_authority": self.source_authority,
            "readiness_transition": (
                self.readiness_transition.to_dict()
                if self.readiness_transition is not None
                else None
            ),
            "authority_change": (
                self.authority_change.to_dict()
                if self.authority_change is not None
                else None
            ),
            "routing_change": (
                self.routing_change.to_dict()
                if self.routing_change is not None
                else None
            ),
            "oneapi_summary": (
                self.oneapi_summary.to_dict()
                if self.oneapi_summary is not None
                else None
            ),
        }
        return d

    def to_json(self, **kwargs: Any) -> str:
        return json.dumps(self.to_dict(), **kwargs)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"TopologyHistoryEntry("
            f"change_kind={self.change_kind.value!r}, "
            f"readiness_label={self.readiness_label!r}, "
            f"is_authoritative={self.is_authoritative})"
        )


# ---------------------------------------------------------------------------
# TopologySnapshot
# ---------------------------------------------------------------------------

class TopologySnapshot:
    """PR-14: A point-in-time snapshot of the topology readiness/authority/
    routing state.

    Snapshots are suitable for diffing against later snapshots to detect
    changes.  They carry the same semantic guarantees as the live inspection
    view: degraded/partial/unavailable snapshots are never marked as
    authoritative, and OneAPI presence is always structurally distinct.

    Attributes
    ----------
    snapshot_id:
        Unique identifier for this snapshot.
    readiness_label:
        Readiness label at snapshot time.
    is_authoritative:
        Whether the topology was authoritative at snapshot time.
    is_degraded:
        Whether the topology was in a degraded state.
    is_partial:
        Whether the topology was in a partial state.
    is_unavailable:
        Whether the topology was unavailable.
    provider_id:
        Primary provider identifier at snapshot time (may be ``None``).
    routing_authority_source:
        Routing authority source string at snapshot time (may be ``None``).
    oneapi_horizon_present:
        Whether the OneAPI lower-horizon node was present in the topology.
    oneapi_is_lower_horizon_only:
        Always ``True`` — OneAPI is never a canonical routing peer.
    stability_indicator:
        Qualitative stability indicator: ``"stable"`` when canonical and
        authoritative; ``"degraded"`` when in a degraded state; ``"partial"``
        when partial; ``"unavailable"`` when unavailable.
    source_authority:
        Authority sentinel of the recorder that produced this snapshot.
    """

    def __init__(
        self,
        *,
        readiness_label: str,
        is_authoritative: bool,
        is_degraded: bool,
        is_partial: bool,
        is_unavailable: bool,
        provider_id: Optional[str],
        routing_authority_source: Optional[str],
        oneapi_horizon_present: bool,
        source_authority: str = TOPOLOGY_HISTORY_AUTHORITY,
    ) -> None:
        self.snapshot_id: str = str(uuid.uuid4())
        self.readiness_label: str = readiness_label
        self.is_authoritative: bool = is_authoritative
        self.is_degraded: bool = is_degraded
        self.is_partial: bool = is_partial
        self.is_unavailable: bool = is_unavailable
        self.provider_id: Optional[str] = provider_id
        self.routing_authority_source: Optional[str] = routing_authority_source
        self.oneapi_horizon_present: bool = oneapi_horizon_present
        self.oneapi_is_lower_horizon_only: bool = True  # invariant — always True
        self.stability_indicator: str = _compute_stability_indicator(
            is_authoritative=is_authoritative,
            is_degraded=is_degraded,
            is_partial=is_partial,
            is_unavailable=is_unavailable,
        )
        self.source_authority: str = source_authority

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "readiness_label": self.readiness_label,
            "is_authoritative": self.is_authoritative,
            "is_degraded": self.is_degraded,
            "is_partial": self.is_partial,
            "is_unavailable": self.is_unavailable,
            "provider_id": self.provider_id,
            "routing_authority_source": self.routing_authority_source,
            "oneapi_horizon_present": self.oneapi_horizon_present,
            "oneapi_is_lower_horizon_only": self.oneapi_is_lower_horizon_only,
            "stability_indicator": self.stability_indicator,
            "source_authority": self.source_authority,
        }

    def to_json(self, **kwargs: Any) -> str:
        return json.dumps(self.to_dict(), **kwargs)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"TopologySnapshot("
            f"readiness_label={self.readiness_label!r}, "
            f"is_authoritative={self.is_authoritative}, "
            f"stability_indicator={self.stability_indicator!r})"
        )


# ---------------------------------------------------------------------------
# TopologyHistoryBuffer
# ---------------------------------------------------------------------------

class TopologyHistoryBuffer:
    """PR-14: Bounded in-memory buffer that accumulates
    :class:`TopologyHistoryEntry` objects.

    When the buffer reaches ``max_size``, the oldest entry is dropped to make
    room for the new one (FIFO eviction).

    Attributes
    ----------
    max_size:
        Maximum number of entries to retain (default 100).
    entries:
        List of :class:`TopologyHistoryEntry` objects in insertion order.
    """

    def __init__(self, max_size: int = 100) -> None:
        self.max_size: int = max(1, max_size)
        self.entries: List[TopologyHistoryEntry] = []

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def add_entry(self, entry: TopologyHistoryEntry) -> None:
        """Append *entry* to the buffer, evicting the oldest if full."""
        if len(self.entries) >= self.max_size:
            self.entries.pop(0)
        self.entries.append(entry)

    def clear(self) -> None:
        """Remove all entries from the buffer."""
        self.entries.clear()

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def latest(self) -> Optional[TopologyHistoryEntry]:
        """Most recently added entry, or ``None`` if buffer is empty."""
        return self.entries[-1] if self.entries else None

    @property
    def oldest(self) -> Optional[TopologyHistoryEntry]:
        """Oldest entry in the buffer, or ``None`` if empty."""
        return self.entries[0] if self.entries else None

    def __len__(self) -> int:
        return len(self.entries)

    def to_list(self) -> List[Dict[str, Any]]:
        """Return all entries as a list of dicts (safe for serialisation)."""
        return [e.to_dict() for e in self.entries]

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"TopologyHistoryBuffer("
            f"max_size={self.max_size}, "
            f"entries={len(self.entries)})"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compute_stability_indicator(
    *,
    is_authoritative: bool,
    is_degraded: bool,
    is_partial: bool,
    is_unavailable: bool,
) -> str:
    """Return a short qualitative stability indicator string."""
    if is_unavailable:
        return "unavailable"
    if is_degraded:
        return "degraded"
    if is_partial:
        return "partial"
    if is_authoritative:
        return "stable"
    return "degraded"


def _safe_readiness_label(obj: Any, fallback: str = "unavailable") -> str:
    """Extract a readiness label from an arbitrary object."""
    if obj is None:
        return fallback
    label = getattr(obj, "readiness_label", None)
    if callable(label):
        try:
            return str(label())
        except Exception:
            return fallback
    if isinstance(label, str) and label:
        return label
    return fallback


def _safe_bool(obj: Any, attr: str, fallback: bool = False) -> bool:
    val = getattr(obj, attr, None)
    if val is None:
        return fallback
    return bool(val)


def _safe_str(obj: Any, attr: str) -> Optional[str]:
    val = getattr(obj, attr, None)
    if val is None:
        return None
    return str(val) if val else None


# ---------------------------------------------------------------------------
# TopologyHistoryRecorder
# ---------------------------------------------------------------------------

class TopologyHistoryRecorder:
    """PR-14: Main observability / history surface.

    Derives :class:`TopologyHistoryEntry` objects and :class:`TopologySnapshot`
    objects from the PR-9/PR-11/PR-12/PR-13 pipeline output.

    All recorder methods are read-only and gracefully handle ``None`` or
    minimal inputs without raising.

    The recorder always builds on:
    - :class:`~windows_client.status_board_v2.topology_inspector.InspectionReport`
      (PR-13) as the richest source,
    - :class:`~windows_client.status_board_v2.topology_layout.TopologyConstellationLayout`
      (PR-11/12) as an intermediate source, or
    - :class:`~core.desktop_consumption_adapter.DesktopClientViewModel` (PR-9)
      as the base source.

    It never bypasses these layers to reconstruct truth from raw nested payload
    dicts.

    Usage::

        recorder = TopologyHistoryRecorder()

        # From a full inspection report (preferred)
        entry = recorder.record_from_inspection_report(report)
        snap  = recorder.snapshot_from_inspection_report(report)

        # From a topology layout
        entry = recorder.record_from_layout(layout)
        snap  = recorder.snapshot_from_layout(layout)

        # From the view-model directly
        entry = recorder.record_from_view_model(vm)
        snap  = recorder.snapshot_from_view_model(vm)

        # Compare two snapshots
        diff = recorder.compare_snapshots(snap_before, snap_after)
        print(diff["readiness_changed"])  # True/False

        # Stability summary over a buffer
        summary = recorder.stability_summary(buf)
    """

    # ------------------------------------------------------------------
    # record_from_inspection_report
    # ------------------------------------------------------------------

    def record_from_inspection_report(
        self, report: Any
    ) -> Optional[TopologyHistoryEntry]:
        """Derive a :class:`TopologyHistoryEntry` from an
        :class:`~windows_client.status_board_v2.topology_inspector.InspectionReport`.

        Returns ``None`` if *report* is ``None``.
        """
        if report is None:
            return None

        readiness = getattr(report, "readiness", None)
        readiness_label = _safe_readiness_label(readiness)
        is_authoritative = _safe_bool(readiness, "is_authoritative")
        is_degraded = _safe_bool(readiness, "is_degraded")
        is_partial = _safe_bool(readiness, "is_partial")
        is_unavailable = _safe_bool(readiness, "is_unavailable")

        # Determine change kind
        change_kind = _change_kind_from_readiness(
            readiness_label=readiness_label,
            is_degraded=is_degraded,
            is_partial=is_partial,
            is_unavailable=is_unavailable,
            is_authoritative=is_authoritative,
        )

        # OneAPI summary (always lower-horizon)
        oneapi = getattr(report, "oneapi", None)
        oneapi_summary = _build_oneapi_history_summary(oneapi)

        # Routing change record (non-None when routing detail is present)
        routing = getattr(report, "routing", None)
        routing_change = _build_routing_change_from_routing_detail(routing)

        return TopologyHistoryEntry(
            change_kind=change_kind,
            readiness_label=readiness_label,
            is_authoritative=is_authoritative,
            is_degraded=is_degraded,
            is_partial=is_partial,
            is_unavailable=is_unavailable,
            oneapi_summary=oneapi_summary,
            routing_change=routing_change,
            source_authority=TOPOLOGY_HISTORY_AUTHORITY,
        )

    # ------------------------------------------------------------------
    # record_from_layout
    # ------------------------------------------------------------------

    def record_from_layout(self, layout: Any) -> Optional[TopologyHistoryEntry]:
        """Derive a :class:`TopologyHistoryEntry` from a
        :class:`~windows_client.status_board_v2.topology_layout.TopologyConstellationLayout`.

        Returns ``None`` if *layout* is ``None``.
        """
        if layout is None:
            return None

        readiness_label = _safe_readiness_label(layout)
        is_authoritative = _safe_bool(layout, "is_authoritative")
        is_degraded = _safe_bool(layout, "is_degraded")
        is_partial = _safe_bool(layout, "is_partial")
        is_unavailable = _safe_bool(layout, "is_unavailable")

        change_kind = _change_kind_from_readiness(
            readiness_label=readiness_label,
            is_degraded=is_degraded,
            is_partial=is_partial,
            is_unavailable=is_unavailable,
            is_authoritative=is_authoritative,
        )

        # OneAPI — check lower_horizon_layer
        oneapi_horizon_present = _has_oneapi_node(layout)
        oneapi_summary = OneAPIHistorySummary(
            horizon_status="present" if oneapi_horizon_present else "absent",
            summary_note=(
                "OneAPI lower-horizon node present in topology layout. "
                "Always structurally distinct; never a canonical routing peer."
                if oneapi_horizon_present
                else "OneAPI lower-horizon node absent from topology layout. "
                "Always structurally distinct; never a canonical routing peer."
            ),
        )

        return TopologyHistoryEntry(
            change_kind=change_kind,
            readiness_label=readiness_label,
            is_authoritative=is_authoritative,
            is_degraded=is_degraded,
            is_partial=is_partial,
            is_unavailable=is_unavailable,
            oneapi_summary=oneapi_summary,
            source_authority=TOPOLOGY_HISTORY_AUTHORITY,
        )

    # ------------------------------------------------------------------
    # record_from_view_model
    # ------------------------------------------------------------------

    def record_from_view_model(self, vm: Any) -> Optional[TopologyHistoryEntry]:
        """Derive a :class:`TopologyHistoryEntry` from a
        :class:`~core.desktop_consumption_adapter.DesktopClientViewModel`.

        Returns ``None`` if *vm* is ``None``.
        """
        if vm is None:
            return None

        readiness_label = _safe_readiness_label(vm)
        is_authoritative = _safe_bool(vm, "is_canonical")
        is_degraded = _safe_bool(vm, "is_degraded")
        is_partial = _safe_bool(vm, "is_partial")
        is_unavailable = _safe_bool(vm, "is_unavailable")

        change_kind = _change_kind_from_readiness(
            readiness_label=readiness_label,
            is_degraded=is_degraded,
            is_partial=is_partial,
            is_unavailable=is_unavailable,
            is_authoritative=is_authoritative,
        )

        # OneAPI summary from DesktopOneAPIHorizonSummary
        oneapi_vm = getattr(vm, "oneapi_summary", None)
        if oneapi_vm is not None:
            oneapi_summary = OneAPIHistorySummary(
                horizon_status="present",
                summary_note=(
                    "OneAPI lower-horizon summary present in view-model. "
                    "Always structurally distinct; never a canonical routing peer."
                ),
            )
        else:
            oneapi_summary = OneAPIHistorySummary(
                horizon_status="absent",
                summary_note=(
                    "OneAPI lower-horizon summary absent from view-model. "
                    "Always structurally distinct; never a canonical routing peer."
                ),
            )

        # Routing change
        routing_vm = getattr(vm, "provider_routing", None)
        provider_id = _safe_str(vm, "provider_id")
        routing_source = _safe_str(vm, "routing_authority_source")
        if routing_vm is not None or provider_id is not None or routing_source is not None:
            routing_change = RoutingChangeRecord(
                from_provider=None,
                to_provider=provider_id,
                from_source=None,
                to_source=routing_source,
                change_note=(
                    f"Routing recorded from view-model: "
                    f"provider={provider_id!r}, "
                    f"source={routing_source!r}."
                ),
            )
        else:
            routing_change = None

        return TopologyHistoryEntry(
            change_kind=change_kind,
            readiness_label=readiness_label,
            is_authoritative=is_authoritative,
            is_degraded=is_degraded,
            is_partial=is_partial,
            is_unavailable=is_unavailable,
            oneapi_summary=oneapi_summary,
            routing_change=routing_change,
            source_authority=TOPOLOGY_HISTORY_AUTHORITY,
        )

    # ------------------------------------------------------------------
    # snapshot_from_inspection_report
    # ------------------------------------------------------------------

    def snapshot_from_inspection_report(
        self, report: Any
    ) -> TopologySnapshot:
        """Take a :class:`TopologySnapshot` from an
        :class:`~windows_client.status_board_v2.topology_inspector.InspectionReport`.

        Returns an unavailable snapshot if *report* is ``None``.
        """
        if report is None:
            return _unavailable_snapshot()

        readiness = getattr(report, "readiness", None)
        readiness_label = _safe_readiness_label(readiness)
        is_authoritative = _safe_bool(readiness, "is_authoritative")
        is_degraded = _safe_bool(readiness, "is_degraded")
        is_partial = _safe_bool(readiness, "is_partial")
        is_unavailable = _safe_bool(readiness, "is_unavailable")

        routing = getattr(report, "routing", None)
        provider_id = _safe_str(routing, "provider_id") if routing is not None else None
        routing_source = (
            _safe_str(routing, "routing_authority_source")
            if routing is not None
            else None
        )

        # OneAPI — check lower_horizon_nodes
        lower_horizon_nodes = getattr(report, "lower_horizon_nodes", None) or []
        oneapi_horizon_present = len(lower_horizon_nodes) > 0

        return TopologySnapshot(
            readiness_label=readiness_label,
            is_authoritative=is_authoritative,
            is_degraded=is_degraded,
            is_partial=is_partial,
            is_unavailable=is_unavailable,
            provider_id=provider_id,
            routing_authority_source=routing_source,
            oneapi_horizon_present=oneapi_horizon_present,
            source_authority=TOPOLOGY_HISTORY_AUTHORITY,
        )

    # ------------------------------------------------------------------
    # snapshot_from_layout
    # ------------------------------------------------------------------

    def snapshot_from_layout(self, layout: Any) -> TopologySnapshot:
        """Take a :class:`TopologySnapshot` from a
        :class:`~windows_client.status_board_v2.topology_layout.TopologyConstellationLayout`.

        Returns an unavailable snapshot if *layout* is ``None``.
        """
        if layout is None:
            return _unavailable_snapshot()

        readiness_label = _safe_readiness_label(layout)
        is_authoritative = _safe_bool(layout, "is_authoritative")
        is_degraded = _safe_bool(layout, "is_degraded")
        is_partial = _safe_bool(layout, "is_partial")
        is_unavailable = _safe_bool(layout, "is_unavailable")

        # Provider from primary layer nodes
        provider_id: Optional[str] = None
        primary_layer = getattr(layout, "primary_layer", None)
        if primary_layer is not None:
            nodes = getattr(primary_layer, "nodes", []) or []
            for node in nodes:
                pid = _safe_str(node, "provider_id")
                if pid:
                    provider_id = pid
                    break

        oneapi_horizon_present = _has_oneapi_node(layout)

        return TopologySnapshot(
            readiness_label=readiness_label,
            is_authoritative=is_authoritative,
            is_degraded=is_degraded,
            is_partial=is_partial,
            is_unavailable=is_unavailable,
            provider_id=provider_id,
            routing_authority_source=None,
            oneapi_horizon_present=oneapi_horizon_present,
            source_authority=TOPOLOGY_HISTORY_AUTHORITY,
        )

    # ------------------------------------------------------------------
    # snapshot_from_view_model
    # ------------------------------------------------------------------

    def snapshot_from_view_model(self, vm: Any) -> TopologySnapshot:
        """Take a :class:`TopologySnapshot` from a
        :class:`~core.desktop_consumption_adapter.DesktopClientViewModel`.

        Returns an unavailable snapshot if *vm* is ``None``.
        """
        if vm is None:
            return _unavailable_snapshot()

        readiness_label = _safe_readiness_label(vm)
        is_authoritative = _safe_bool(vm, "is_canonical")
        is_degraded = _safe_bool(vm, "is_degraded")
        is_partial = _safe_bool(vm, "is_partial")
        is_unavailable = _safe_bool(vm, "is_unavailable")

        provider_id = _safe_str(vm, "provider_id")
        routing_source = _safe_str(vm, "routing_authority_source")
        oneapi_vm = getattr(vm, "oneapi_summary", None)
        oneapi_horizon_present = oneapi_vm is not None

        return TopologySnapshot(
            readiness_label=readiness_label,
            is_authoritative=is_authoritative,
            is_degraded=is_degraded,
            is_partial=is_partial,
            is_unavailable=is_unavailable,
            provider_id=provider_id,
            routing_authority_source=routing_source,
            oneapi_horizon_present=oneapi_horizon_present,
            source_authority=TOPOLOGY_HISTORY_AUTHORITY,
        )

    # ------------------------------------------------------------------
    # compare_snapshots
    # ------------------------------------------------------------------

    def compare_snapshots(
        self,
        before: Any,
        after: Any,
    ) -> Dict[str, Any]:
        """Diff two :class:`TopologySnapshot` objects.

        Returns a dict with the following keys:

        - ``"readiness_changed"`` — ``True`` if ``readiness_label`` differs.
        - ``"authority_changed"`` — ``True`` if ``is_authoritative`` differs.
        - ``"provider_changed"`` — ``True`` if ``provider_id`` differs.
        - ``"routing_source_changed"`` — ``True`` if ``routing_authority_source``
          differs.
        - ``"oneapi_presence_changed"`` — ``True`` if ``oneapi_horizon_present``
          differs.
        - ``"stability_changed"`` — ``True`` if ``stability_indicator`` differs.
        - ``"readiness_transition"`` — optional ``ReadinessTransitionRecord``
          when readiness changed.
        - ``"authority_change"`` — optional ``AuthorityChangeRecord`` when
          authority changed.
        - ``"routing_change"`` — optional ``RoutingChangeRecord`` when provider
          or routing changed.
        - ``"any_change"`` — ``True`` if any of the above flags is ``True``.
        - ``"before_authority"`` — ``TOPOLOGY_HISTORY_AUTHORITY`` sentinel.

        Handles ``None`` gracefully — missing before/after are treated as
        unavailable/unknown snapshots.
        """
        before_label = getattr(before, "readiness_label", "unavailable") or "unavailable"
        after_label = getattr(after, "readiness_label", "unavailable") or "unavailable"
        before_auth = bool(getattr(before, "is_authoritative", False))
        after_auth = bool(getattr(after, "is_authoritative", False))
        before_provider = getattr(before, "provider_id", None)
        after_provider = getattr(after, "provider_id", None)
        before_source = getattr(before, "routing_authority_source", None)
        after_source = getattr(after, "routing_authority_source", None)
        before_oneapi = bool(getattr(before, "oneapi_horizon_present", False))
        after_oneapi = bool(getattr(after, "oneapi_horizon_present", False))
        before_stability = getattr(before, "stability_indicator", "unavailable") or "unavailable"
        after_stability = getattr(after, "stability_indicator", "unavailable") or "unavailable"

        readiness_changed = before_label != after_label
        authority_changed = before_auth != after_auth
        provider_changed = before_provider != after_provider
        routing_source_changed = before_source != after_source
        oneapi_presence_changed = before_oneapi != after_oneapi
        stability_changed = before_stability != after_stability

        # Build sub-records for changes
        readiness_transition: Optional[ReadinessTransitionRecord] = None
        if readiness_changed:
            readiness_transition = ReadinessTransitionRecord(
                from_readiness=before_label,
                to_readiness=after_label,
                was_authoritative=before_auth,
                became_authoritative=after_auth,
                transition_note=(
                    f"Readiness changed from {before_label!r} to {after_label!r}. "
                    + (
                        "New state is NOT authoritative — fallback/degraded history "
                        "must not be treated as authoritative truth."
                        if not after_auth
                        else "New state is authoritative."
                    )
                ),
            )

        authority_change_rec: Optional[AuthorityChangeRecord] = None
        if authority_changed:
            authority_change_rec = AuthorityChangeRecord(
                from_authoritative=before_auth,
                to_authoritative=after_auth,
                from_label=before_label,
                to_label=after_label,
                change_note=(
                    f"Authority changed: {before_auth} → {after_auth}. "
                    + (
                        "Topology is now NOT authoritative."
                        if not after_auth
                        else "Topology recovered to authoritative state."
                    )
                ),
            )

        routing_change_rec: Optional[RoutingChangeRecord] = None
        if provider_changed or routing_source_changed:
            routing_change_rec = RoutingChangeRecord(
                from_provider=before_provider,
                to_provider=after_provider,
                from_source=before_source,
                to_source=after_source,
                change_note=(
                    f"Routing changed: provider {before_provider!r} → {after_provider!r}, "
                    f"source {before_source!r} → {after_source!r}."
                ),
            )

        any_change = (
            readiness_changed
            or authority_changed
            or provider_changed
            or routing_source_changed
            or oneapi_presence_changed
            or stability_changed
        )

        return {
            "readiness_changed": readiness_changed,
            "authority_changed": authority_changed,
            "provider_changed": provider_changed,
            "routing_source_changed": routing_source_changed,
            "oneapi_presence_changed": oneapi_presence_changed,
            "stability_changed": stability_changed,
            "readiness_transition": readiness_transition,
            "authority_change": authority_change_rec,
            "routing_change": routing_change_rec,
            "any_change": any_change,
            "before_authority": TOPOLOGY_HISTORY_AUTHORITY,
        }

    # ------------------------------------------------------------------
    # stability_summary
    # ------------------------------------------------------------------

    def stability_summary(self, buf: Any) -> Dict[str, Any]:
        """Produce a stability summary over a :class:`TopologyHistoryBuffer`.

        Returns a dict with:

        - ``"total_entries"`` — number of entries in the buffer.
        - ``"canonical_count"`` — entries with ``readiness_label == "canonical"``.
        - ``"degraded_count"`` — entries with ``is_degraded == True``.
        - ``"partial_count"`` — entries with ``is_partial == True``.
        - ``"unavailable_count"`` — entries with ``is_unavailable == True``.
        - ``"authoritative_count"`` — entries with ``is_authoritative == True``.
        - ``"non_authoritative_count"`` — entries with ``is_authoritative == False``.
        - ``"stability_ratio"`` — fraction of authoritative entries (0.0–1.0).
        - ``"overall_stability"`` — ``"stable"`` when ``stability_ratio == 1.0``,
          ``"mostly_stable"`` when ≥ 0.75, ``"unstable"`` otherwise.
        - ``"source_authority"`` — ``TOPOLOGY_HISTORY_AUTHORITY`` sentinel.

        Handles ``None`` or empty buffers gracefully.
        """
        entries = []
        if buf is not None:
            entries = list(getattr(buf, "entries", []) or [])

        total = len(entries)
        canonical_count = sum(
            1 for e in entries if getattr(e, "readiness_label", None) == "canonical"
        )
        degraded_count = sum(
            1 for e in entries if _safe_bool(e, "is_degraded")
        )
        partial_count = sum(
            1 for e in entries if _safe_bool(e, "is_partial")
        )
        unavailable_count = sum(
            1 for e in entries if _safe_bool(e, "is_unavailable")
        )
        authoritative_count = sum(
            1 for e in entries if _safe_bool(e, "is_authoritative")
        )
        non_authoritative_count = total - authoritative_count

        stability_ratio = authoritative_count / total if total > 0 else 0.0

        if total == 0:
            overall_stability = "unknown"
        elif stability_ratio >= 1.0:
            overall_stability = "stable"
        elif stability_ratio >= 0.75:
            overall_stability = "mostly_stable"
        else:
            overall_stability = "unstable"

        return {
            "total_entries": total,
            "canonical_count": canonical_count,
            "degraded_count": degraded_count,
            "partial_count": partial_count,
            "unavailable_count": unavailable_count,
            "authoritative_count": authoritative_count,
            "non_authoritative_count": non_authoritative_count,
            "stability_ratio": stability_ratio,
            "overall_stability": overall_stability,
            "source_authority": TOPOLOGY_HISTORY_AUTHORITY,
        }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _change_kind_from_readiness(
    *,
    readiness_label: str,
    is_degraded: bool,
    is_partial: bool,
    is_unavailable: bool,
    is_authoritative: bool,
) -> TopologyChangeKind:
    """Infer the most appropriate :class:`TopologyChangeKind` from readiness."""
    if is_unavailable:
        return TopologyChangeKind.topology_degraded
    if is_degraded:
        return TopologyChangeKind.topology_degraded
    if is_partial:
        return TopologyChangeKind.topology_degraded
    if is_authoritative and readiness_label == "canonical":
        return TopologyChangeKind.snapshot_only
    return TopologyChangeKind.snapshot_only


def _build_oneapi_history_summary(oneapi: Any) -> OneAPIHistorySummary:
    """Build a :class:`OneAPIHistorySummary` from an
    :class:`~windows_client.status_board_v2.topology_inspector.OneAPIInspectionDetail`
    or ``None``."""
    if oneapi is None:
        return OneAPIHistorySummary(
            horizon_status="absent",
            summary_note=(
                "OneAPI lower-horizon detail absent. "
                "Always structurally distinct; never a canonical routing peer."
            ),
        )

    # Extract what we can without hard-importing topology_inspector
    status_label = getattr(oneapi, "oneapi_status_label", None) or "present"
    return OneAPIHistorySummary(
        horizon_status=str(status_label),
        summary_note=(
            "OneAPI lower-horizon detail present in inspection report. "
            "Always structurally distinct; never a canonical routing peer."
        ),
    )


def _build_routing_change_from_routing_detail(routing: Any) -> Optional[RoutingChangeRecord]:
    """Build a :class:`RoutingChangeRecord` from a
    :class:`~windows_client.status_board_v2.topology_inspector.RoutingInspectionDetail`
    or ``None``."""
    if routing is None:
        return None
    provider_id = _safe_str(routing, "provider_id")
    routing_source = _safe_str(routing, "routing_authority_source")
    if provider_id is None and routing_source is None:
        return None
    return RoutingChangeRecord(
        from_provider=None,
        to_provider=provider_id,
        from_source=None,
        to_source=routing_source,
        change_note=(
            f"Routing recorded from inspection report: "
            f"provider={provider_id!r}, "
            f"source={routing_source!r}."
        ),
    )


def _has_oneapi_node(layout: Any) -> bool:
    """Return ``True`` if *layout* contains a OneAPI lower-horizon node."""
    lower_horizon_layer = getattr(layout, "lower_horizon_layer", None)
    if lower_horizon_layer is None:
        return False
    nodes = getattr(lower_horizon_layer, "nodes", []) or []
    return len(nodes) > 0


def _unavailable_snapshot() -> TopologySnapshot:
    """Return a minimal unavailable :class:`TopologySnapshot`."""
    return TopologySnapshot(
        readiness_label="unavailable",
        is_authoritative=False,
        is_degraded=False,
        is_partial=False,
        is_unavailable=True,
        provider_id=None,
        routing_authority_source=None,
        oneapi_horizon_present=False,
        source_authority=TOPOLOGY_HISTORY_AUTHORITY,
    )
