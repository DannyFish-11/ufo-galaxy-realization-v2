"""contracts/dispatch_contract_metadata.py
==========================================
Unified Dispatch Contract Metadata — PR-03 (post-533 dual-repo unification).

This module defines the **canonical unified dispatch contract metadata**
sub-contract shared by all three V2 dispatch paths:

- **goal_execution** — source-side local execution
  (:class:`~contracts.source_dispatch.SourceDispatchResult`)
- **handoff** — source sends a
  :class:`~contracts.handoff_envelope_v2.HandoffEnvelopeV2` to a remote target
- **takeover** — target receives the handoff and executes locally,
  returning a :class:`~contracts.local_takeover_result.LocalTakeoverResult`

It answers the architectural question:

    *"What stable metadata fields must every dispatch-originated envelope and
    result carry, regardless of which execution path produced it, so that the
    Android consumer can interpret dispatch semantics consistently?"*

Problems addressed
------------------
Previously, ``goal_execution`` and ``handoff`` paths accumulated richer
dispatch-level metadata (``plan_id``, ``dispatch_id``, ``mode``, etc.) via
:class:`~contracts.source_dispatch.SourceDispatchPlan`, while the
``takeover`` path's :class:`~contracts.local_takeover_result.LocalTakeoverResult`
carried none of this metadata.  ``executor_target_type`` was used by
``CommandRouter`` but not tied to a contract visible across all paths.
The resulting asymmetry prevented Android from stably interpreting dispatch
semantics.

Solution
--------
:class:`DispatchContractMetadata` is a lightweight, fully-optional sub-contract
that **every** dispatch-originated structure now carries.  It is:

- embedded as ``dispatch_contract_metadata`` in
  :class:`~contracts.handoff_envelope_v2.HandoffEnvelopeV2`,
  :class:`~contracts.local_takeover_result.LocalTakeoverResult`, and
  :class:`~contracts.source_dispatch.SourceDispatchResult`.
- built once by :func:`build_dispatch_contract_metadata` and then forwarded
  through every stage of the dispatch pipeline.

Authority sentinel
------------------
``UNIFIED_DISPATCH_CONTRACT_PR03_SENTINEL``

Design principles
-----------------
- **Additive only** — does not modify any existing module's primary contract.
- **Fully serialisable** — :meth:`DispatchContractMetadata.to_dict` produces
  stable, round-trippable JSON.
- **Graceful defaults** — all fields are optional; callers with partial
  context always produce a valid sub-contract.
- **Stable field names** — Android consumers rely on these names.
- **Single builder** — :func:`build_dispatch_contract_metadata` is the one
  authoritative construction point.

Usage::

    from contracts.dispatch_contract_metadata import (
        DispatchContractMetadata,
        build_dispatch_contract_metadata,
        UNIFIED_DISPATCH_CONTRACT_PR03_SENTINEL,
    )

    meta = build_dispatch_contract_metadata(
        dispatch_plan_id="plan_abc",
        source_dispatch_strategy="remote_handoff",
        executor_target_type="android_device",
        trace_id="trace_001",
        task_id="task_001",
    )
    payload = meta.to_dict()  # stable, JSON-serialisable

See ``docs/SOURCE_RUNTIME_DISPATCH_ORCHESTRATOR.md`` for context.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Authority sentinel
# ---------------------------------------------------------------------------

UNIFIED_DISPATCH_CONTRACT_PR03_SENTINEL: str = (
    "UNIFIED_DISPATCH_CONTRACT_PR03::dispatch-contract-metadata::"
    "goal_execution+handoff+takeover-share-single-metadata-sub-contract::"
    "package=PR03::post-533-dual-repo-runtime-unification"
)

DISPATCH_CONTRACT_METADATA_IS_STABLE_ANDROID_SURFACE_PR03_POLICY: str = (
    "POLICY::DISPATCH_CONTRACT_METADATA_IS_STABLE_ANDROID_SURFACE_PR03: "
    "DispatchContractMetadata.to_dict() is a stable Android-facing wire surface. "
    "Field names and types MUST NOT be renamed or removed without a schema_version "
    "bump and a coordinated cross-repo migration.  New optional fields may be "
    "added freely.  This policy applies to all three dispatch paths: "
    "goal_execution, handoff, and takeover."
)


# ---------------------------------------------------------------------------
# DispatchContractMetadata — unified sub-contract
# ---------------------------------------------------------------------------


class DispatchContractMetadata(BaseModel):
    """Unified dispatch contract metadata shared by all three V2 dispatch paths.

    This sub-contract is embedded in every dispatch-originated structure so
    that the Android consumer can stably interpret dispatch semantics without
    inspecting the enclosing payload shape.

    Fields
    ------
    dispatch_plan_id
        Identifier of the :class:`~contracts.source_dispatch.SourceDispatchPlan`
        that originated this dispatch.  ``None`` when no plan was built (e.g.
        legacy or error paths).
    dispatch_decision_id
        Identifier of the :class:`~contracts.source_dispatch.SourceDispatchDecision`
        that drove the dispatch.  ``None`` when unavailable.
    source_dispatch_strategy
        Human-stable string representing the dispatch strategy chosen at the
        source side.  Maps to :class:`~contracts.source_dispatch.SourceDispatchMode`
        values: ``"local"``, ``"remote_handoff"``, ``"staged_mesh"``,
        ``"blocked"``, ``"fallback_local"``, ``"unknown"``.  For target-side
        takeover results this reflects the *source*'s strategy (as carried in
        the incoming :class:`~contracts.handoff_envelope_v2.HandoffEnvelopeV2`).
    executor_target_type
        The executor target type that the ``CommandRouter`` used (or would use)
        to route this task.  Corresponds to
        :class:`~core.schemas.remote_execution.ExecutorTargetType` values:
        ``"android_device"``, ``"node_service"``, ``"go_worker"``,
        ``"local"``.  ``None`` when the routing has not been determined.
    trace_id
        Distributed trace identifier propagated from the originating request.
    task_id
        Task identifier, if available.
    session_id
        Session identifier, if available.
    source_device_id
        Stable identifier of the source device.
    target_device_id
        Stable identifier of the execution target device.  ``None`` for local
        execution.
    schema_version
        Version marker for this sub-contract.  Currently ``"v1"``.
    timestamp
        Unix timestamp when this metadata was created.
    metadata
        Arbitrary extension metadata for future use.
    """

    dispatch_plan_id: Optional[str] = Field(
        default=None,
        description="SourceDispatchPlan identifier that originated this dispatch.",
    )
    dispatch_decision_id: Optional[str] = Field(
        default=None,
        description="SourceDispatchDecision identifier that drove the dispatch.",
    )
    source_dispatch_strategy: Optional[str] = Field(
        default=None,
        description=(
            "Dispatch strategy string from the source side: local, remote_handoff, "
            "staged_mesh, blocked, fallback_local, unknown.  Stable Android-facing value."
        ),
    )
    executor_target_type: Optional[str] = Field(
        default=None,
        description=(
            "ExecutorTargetType value used for routing: android_device, node_service, "
            "go_worker, local.  None when routing is not yet determined."
        ),
    )
    trace_id: Optional[str] = Field(
        default=None,
        description="Distributed trace identifier propagated from the originating request.",
    )
    task_id: Optional[str] = Field(
        default=None,
        description="Task identifier, if available.",
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Session identifier, if available.",
    )
    source_device_id: Optional[str] = Field(
        default=None,
        description="Stable identifier of the source device.",
    )
    target_device_id: Optional[str] = Field(
        default=None,
        description="Stable identifier of the execution target device.  None for local execution.",
    )
    schema_version: str = Field(
        default="v1",
        description="Version marker for this sub-contract.  Currently 'v1'.",
    )
    timestamp: float = Field(
        default_factory=time.time,
        description="Unix timestamp when this metadata was created.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary extension metadata for future use.",
    )

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a stable, JSON-safe dictionary representation."""
        return self.model_dump(mode="json")

    def to_json(self, *, indent: Optional[int] = None) -> str:
        """Return a stable JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DispatchContractMetadata":
        """Construct from a dictionary.  Tolerates unknown extra fields."""
        return cls.model_validate(data)

    model_config = {"extra": "allow", "populate_by_name": True}


# ---------------------------------------------------------------------------
# Builder — unified construction point
# ---------------------------------------------------------------------------


def build_dispatch_contract_metadata(
    *,
    dispatch_plan_id: Optional[str] = None,
    dispatch_decision_id: Optional[str] = None,
    source_dispatch_strategy: Optional[str] = None,
    executor_target_type: Optional[str] = None,
    trace_id: Optional[str] = None,
    task_id: Optional[str] = None,
    session_id: Optional[str] = None,
    source_device_id: Optional[str] = None,
    target_device_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> DispatchContractMetadata:
    """Build a :class:`DispatchContractMetadata` instance.

    This is the single authoritative construction point for the unified
    dispatch contract metadata.  All dispatch paths (goal_execution, handoff,
    takeover) MUST use this function rather than constructing
    :class:`DispatchContractMetadata` directly.

    All parameters are optional; omitted fields fall back to ``None``.
    This function never raises — on any unexpected error it returns a
    minimal valid instance.

    Parameters
    ----------
    dispatch_plan_id:
        Identifier of the originating :class:`~contracts.source_dispatch.SourceDispatchPlan`.
    dispatch_decision_id:
        Identifier of the originating :class:`~contracts.source_dispatch.SourceDispatchDecision`.
    source_dispatch_strategy:
        Dispatch strategy string: "local", "remote_handoff", "staged_mesh",
        "blocked", "fallback_local", "unknown".
    executor_target_type:
        ExecutorTargetType routing value: "android_device", "node_service",
        "go_worker", "local".
    trace_id:
        Distributed trace identifier.
    task_id:
        Task identifier.
    session_id:
        Session identifier.
    source_device_id:
        Source device identifier.
    target_device_id:
        Target device identifier.
    metadata:
        Arbitrary extension metadata.

    Returns
    -------
    DispatchContractMetadata
        Always returns a valid instance; degrades gracefully on error.
    """
    try:
        return DispatchContractMetadata(
            dispatch_plan_id=dispatch_plan_id,
            dispatch_decision_id=dispatch_decision_id,
            source_dispatch_strategy=source_dispatch_strategy,
            executor_target_type=executor_target_type,
            trace_id=trace_id,
            task_id=task_id,
            session_id=session_id,
            source_device_id=source_device_id,
            target_device_id=target_device_id,
            metadata=dict(metadata) if metadata else {},
        )
    except Exception as _exc:  # noqa: BLE001
        logger.debug(
            "build_dispatch_contract_metadata: construction failed; "
            "returning degraded instance (trace_id=%r, task_id=%r): %s",
            trace_id,
            task_id,
            _exc,
        )
        return DispatchContractMetadata(
            trace_id=trace_id,
            task_id=task_id,
        )


def extract_dispatch_contract_metadata(
    source: Any,
) -> Optional[DispatchContractMetadata]:
    """Extract a :class:`DispatchContractMetadata` from any dispatch-originated object.

    Accepts a ``HandoffEnvelopeV2``, ``LocalTakeoverResult``,
    ``SourceDispatchResult``, or any object that carries a
    ``dispatch_contract_metadata`` attribute/key.

    Parameters
    ----------
    source:
        Any dispatch-originated object.

    Returns
    -------
    DispatchContractMetadata or None
        Returns ``None`` when no metadata is found or on any error.
    """
    try:
        # Try attribute access (Pydantic models)
        raw = getattr(source, "dispatch_contract_metadata", None)
        if raw is None and isinstance(source, dict):
            raw = source.get("dispatch_contract_metadata")
        if raw is None:
            return None
        if isinstance(raw, DispatchContractMetadata):
            return raw
        if isinstance(raw, dict):
            return DispatchContractMetadata.from_dict(raw)
        return None
    except Exception:  # noqa: BLE001
        return None
