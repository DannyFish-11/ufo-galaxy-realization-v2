"""core/ugcp_truth_event_model.py
===================================
UGCP Truth/Event Model v1 (realization-v2 side, PR-7 scope).

This module defines an incremental canonical backbone for relating:
- authoritative truth transitions,
- emitted canonical events,
- durable snapshot/read-model surfaces,
- replay/recovery reconstruction checkpoints,
- runtime-facing observational stream updates.

The model is additive: it does not claim a full event-sourced rewrite.  It
provides one canonical vocabulary and a small set of helpers that existing
profiles can share while preserving current runtime behavior.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Set

from core.schemas.ugcp.shared import TruthEvent

UGCP_TRUTH_EVENT_MODEL_AUTHORITY: str = (
    "UGCP_TRUTH_EVENT_MODEL_AUTHORITY::"
    "core.ugcp_truth_event_model is the canonical truth/event backbone authority "
    "for realization-v2 truth transitions, emitted events, durable snapshots, "
    "and replay/recovery checkpoints."
)

TRUTH_EVENT_VOCABULARY_IS_FROZEN_POLICY: str = (
    "TRUTH_EVENT_MODEL_POLICY::TRUTH_EVENT_VOCABULARY_IS_FROZEN: "
    "Major lifecycle transitions must use CanonicalTruthEventType values "
    "to avoid semantic drift across runtime/control-transfer/coordination/session "
    "surfaces."
)

AUTHORITATIVE_TRUTH_WRITES_EMIT_CANONICAL_EVENTS_POLICY: str = (
    "TRUTH_EVENT_MODEL_POLICY::AUTHORITATIVE_TRUTH_WRITES_EMIT_CANONICAL_EVENTS: "
    "Authoritative truth transitions should be represented as canonical TruthEvent "
    "payloads before distribution to observational layers."
)

EVENT_STREAM_IS_OBSERVATIONAL_NOT_AUTHORITY_POLICY: str = (
    "TRUTH_EVENT_MODEL_POLICY::EVENT_STREAM_IS_OBSERVATIONAL_NOT_AUTHORITY: "
    "Runtime-facing event streams are derived notifications; they do not replace "
    "authoritative truth writes."
)

SNAPSHOT_IS_DURABLE_READ_MODEL_POLICY: str = (
    "TRUTH_EVENT_MODEL_POLICY::SNAPSHOT_IS_DURABLE_READ_MODEL: "
    "Durable snapshots are read-model surfaces derived from canonical truth/event "
    "history and are not independent authority sources."
)

REPLAY_RECONSTRUCTION_AVOIDS_SEMANTIC_DRIFT_POLICY: str = (
    "TRUTH_EVENT_MODEL_POLICY::REPLAY_RECONSTRUCTION_AVOIDS_SEMANTIC_DRIFT: "
    "Replay/recovery checkpoints must preserve canonical event type, ordering key, "
    "and event sequence when present."
)

UGCP_TRUTH_EVENT_MODEL_PR7_SENTINEL: str = (
    "UGCP_TRUTH_EVENT_MODEL_PR7_SENTINEL::package=7::"
    "profile=ugcp-truth-event-model-v1::module=core.ugcp_truth_event_model"
)


class CanonicalTruthEventType(str, Enum):
    session_truth_recorded = "ugcp.truth.session.recorded.v1"
    session_truth_snapshot = "ugcp.truth.session.snapshot.v1"
    task_lifecycle_transition = "ugcp.task.lifecycle.transition.v1"
    runtime_lifecycle_transition = "ugcp.runtime.lifecycle.transition.v1"
    control_transfer_transition = "ugcp.control_transfer.transition.v1"
    coordination_transition = "ugcp.coordination.transition.v1"


class TruthSurfaceClass(str, Enum):
    authoritative_truth = "authoritative_truth"
    transient_event = "transient_event"
    durable_snapshot = "durable_snapshot"
    replay_checkpoint = "replay_checkpoint"
    observational_stream = "observational_stream"


_AUTHORITATIVE_TRANSITION_EVENTS: Set[CanonicalTruthEventType] = {
    CanonicalTruthEventType.session_truth_recorded,
    CanonicalTruthEventType.task_lifecycle_transition,
    CanonicalTruthEventType.runtime_lifecycle_transition,
    CanonicalTruthEventType.control_transfer_transition,
    CanonicalTruthEventType.coordination_transition,
}


@dataclass(frozen=True)
class CanonicalTruthEventEnvelope:
    event_type: str
    surface_class: TruthSurfaceClass
    authoritative_transition: bool
    ordering_key: str = ""
    event_sequence: Optional[int] = None
    trace_id: Optional[str] = None
    task_id: Optional[str] = None
    control_session_id: Optional[str] = None
    runtime_session_id: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_truth_event(self) -> TruthEvent:
        return TruthEvent(
            event_type=self.event_type,
            trace_id=self.trace_id,
            task_id=self.task_id,
            control_session_id=self.control_session_id,
            runtime_session_id=self.runtime_session_id,
            payload={
                **self.payload,
                "surface_class": self.surface_class.value,
                "authoritative_transition": self.authoritative_transition,
                "ordering_key": self.ordering_key,
                "event_sequence": self.event_sequence,
                "event_model_authority": UGCP_TRUTH_EVENT_MODEL_AUTHORITY,
            },
        )


def is_authoritative_transition_event(event_type: Any) -> bool:
    try:
        canonical = CanonicalTruthEventType(str(event_type))
    except Exception:
        return False
    return canonical in _AUTHORITATIVE_TRANSITION_EVENTS


def get_canonical_transition_event_types() -> Set[str]:
    return {item.value for item in CanonicalTruthEventType}


def _pick(obj: Any, *keys: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        for key in keys:
            value = obj.get(key)
            if value is not None:
                return value
        return default
    for key in keys:
        value = getattr(obj, key, None)
        if value is not None:
            return value
    return default


def build_session_truth_authoritative_event(
    record: Any,
    *,
    event_sequence: Optional[int] = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> CanonicalTruthEventEnvelope:
    runtime_session_id = _pick(record, "session_id", "runtime_session_id", default="")
    payload = {
        "profile": "ugcp_truth_event_model_v1",
        "record_id": _pick(record, "record_id"),
        "truth_source": _pick(record, "truth_source", default="unknown"),
        "merge_success": bool(_pick(record, "merge_success", default=False)),
        "primary_unit_id": _pick(record, "primary_unit_id"),
        "reason": _pick(record, "reason", default=""),
        "metadata": dict(metadata or {}),
    }
    return CanonicalTruthEventEnvelope(
        event_type=CanonicalTruthEventType.session_truth_recorded.value,
        surface_class=TruthSurfaceClass.authoritative_truth,
        authoritative_transition=True,
        ordering_key=str(runtime_session_id or _pick(record, "trace_id", default="")),
        event_sequence=event_sequence,
        trace_id=_pick(record, "trace_id"),
        task_id=_pick(record, "task_id"),
        runtime_session_id=runtime_session_id,
        payload=payload,
    )


def build_snapshot_projection_surface(
    snapshot: Any,
    *,
    source_event_sequence: Optional[int] = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    snapshot_id = _pick(snapshot, "snapshot_id", default="")
    return {
        "surface_class": TruthSurfaceClass.durable_snapshot.value,
        "event_type": CanonicalTruthEventType.session_truth_snapshot.value,
        "snapshot_id": snapshot_id,
        "source_event_sequence": source_event_sequence,
        "authoritative_transition": False,
        "event_model_authority": UGCP_TRUTH_EVENT_MODEL_AUTHORITY,
        "snapshot_read_model_policy": SNAPSHOT_IS_DURABLE_READ_MODEL_POLICY,
        "payload": {
            "total_records": int(_pick(snapshot, "total_records", default=0) or 0),
            "successful_merge_count": int(_pick(snapshot, "successful_merge_count", default=0) or 0),
            "control_only_session_count": int(_pick(snapshot, "control_only_session_count", default=0) or 0),
            "join_runtime_session_count": int(_pick(snapshot, "join_runtime_session_count", default=0) or 0),
            "metadata": dict(metadata or {}),
        },
    }


def build_replay_checkpoint(
    event: CanonicalTruthEventEnvelope,
    *,
    replay_epoch: str = "live",
    metadata: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "surface_class": TruthSurfaceClass.replay_checkpoint.value,
        "event_type": event.event_type,
        "ordering_key": event.ordering_key,
        "event_sequence": event.event_sequence,
        "authoritative_transition": event.authoritative_transition,
        "trace_id": event.trace_id,
        "task_id": event.task_id,
        "runtime_session_id": event.runtime_session_id,
        "replay_epoch": replay_epoch,
        "reconstruction_policy": REPLAY_RECONSTRUCTION_AVOIDS_SEMANTIC_DRIFT_POLICY,
        "dedupe_key": ":".join(
            [
                event.ordering_key or "-",
                event.event_type,
                str(event.event_sequence if event.event_sequence is not None else "-"),
                event.trace_id or "-",
                event.task_id or "-",
            ]
        ),
        "metadata": dict(metadata or {}),
    }


def build_runtime_observational_stream_event(
    event: CanonicalTruthEventEnvelope,
    *,
    stream_name: str = "runtime_truth_updates",
    metadata: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "surface_class": TruthSurfaceClass.observational_stream.value,
        "stream_name": stream_name,
        "event_type": event.event_type,
        "ordering_key": event.ordering_key,
        "event_sequence": event.event_sequence,
        "authoritative_transition": False,
        "derived_from_authoritative_transition": event.authoritative_transition,
        "event_stream_policy": EVENT_STREAM_IS_OBSERVATIONAL_NOT_AUTHORITY_POLICY,
        "payload": {
            "trace_id": event.trace_id,
            "task_id": event.task_id,
            "runtime_session_id": event.runtime_session_id,
            "metadata": dict(metadata or {}),
        },
    }


__all__ = [
    "UGCP_TRUTH_EVENT_MODEL_AUTHORITY",
    "TRUTH_EVENT_VOCABULARY_IS_FROZEN_POLICY",
    "AUTHORITATIVE_TRUTH_WRITES_EMIT_CANONICAL_EVENTS_POLICY",
    "EVENT_STREAM_IS_OBSERVATIONAL_NOT_AUTHORITY_POLICY",
    "SNAPSHOT_IS_DURABLE_READ_MODEL_POLICY",
    "REPLAY_RECONSTRUCTION_AVOIDS_SEMANTIC_DRIFT_POLICY",
    "UGCP_TRUTH_EVENT_MODEL_PR7_SENTINEL",
    "CanonicalTruthEventType",
    "TruthSurfaceClass",
    "CanonicalTruthEventEnvelope",
    "is_authoritative_transition_event",
    "get_canonical_transition_event_types",
    "build_session_truth_authoritative_event",
    "build_snapshot_projection_surface",
    "build_replay_checkpoint",
    "build_runtime_observational_stream_event",
]
