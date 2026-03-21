"""
core/contract_map/contract_descriptor.py
==========================================
Descriptor model for a single contract entry in the cross-plane contract map.

A :class:`ContractDescriptor` captures the *metadata* about a contract —
its plane, message kind, canonical Python type, identity fields, producers,
consumers, and any compatibility notes.  It does **not** replace or re-implement
the underlying schema; it acts as an annotated pointer to it.

Design notes
------------
- All fields are optional except ``plane`` and ``kind`` so descriptors can
  be registered before all metadata is known (graceful degradation).
- ``canonical_type`` is a string (dotted module path) rather than a live Python
  type to avoid import-time coupling and to keep the descriptor serialisable.
- Immutability: descriptors are frozen dataclasses consumed through the registry;
  the registry itself is the mutable surface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .plane_kind import PlaneKind
from .message_kind import MessageKind


@dataclass(frozen=True)
class ContractDescriptor:
    """Metadata descriptor for one contract in the Galaxy contract map.

    Parameters
    ----------
    plane:
        The :class:`PlaneKind` this contract belongs to.
    kind:
        The :class:`MessageKind` that identifies this contract family.
    canonical_type:
        Dotted Python import path for the primary schema / dataclass,
        e.g. ``"core.schemas.task_envelope.TaskEnvelope"``.
        ``None`` when the contract is informal or proto-only.
    source_module:
        Primary Python module (dotted path) that *owns* the definition.
    identity_fields:
        Field names that uniquely identify a message instance, e.g.
        ``["task_id", "trace_id"]``.  Used by consumers to correlate
        requests and responses.
    producer_modules:
        Modules / components that *emit* this message kind (best-effort).
    consumer_modules:
        Modules / components that *consume* this message kind (best-effort).
    notes:
        Free-text notes on compatibility, fallback behaviour, versioning,
        or anything else that helps future maintainers.
    """

    plane: PlaneKind
    kind: MessageKind
    canonical_type: Optional[str] = None
    source_module: Optional[str] = None
    identity_fields: List[str] = field(default_factory=list)
    producer_modules: List[str] = field(default_factory=list)
    consumer_modules: List[str] = field(default_factory=list)
    notes: Optional[str] = None

    def to_dict(self) -> dict:
        """Return a JSON-serialisable representation."""
        return {
            "plane": self.plane.value,
            "kind": self.kind.value,
            "canonical_type": self.canonical_type,
            "source_module": self.source_module,
            "identity_fields": list(self.identity_fields),
            "producer_modules": list(self.producer_modules),
            "consumer_modules": list(self.consumer_modules),
            "notes": self.notes,
        }

    def required_fields_summary(self) -> dict:
        """Return a concise summary of required identity fields.

        Useful for diagnostics and the introspection endpoint.
        """
        return {
            "kind": self.kind.value,
            "plane": self.plane.value,
            "identity_fields": list(self.identity_fields),
        }
