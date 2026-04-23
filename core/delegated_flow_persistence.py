#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/delegated_flow_persistence.py
====================================
PR-2 (post-533 dual-repo runtime unification master plan, MAIN repo side):
Durable Persistence Foundation for Session / Contract / Binding / Flow Metadata.

Background
----------
The cross-device delegated flow chain depends on four categories of runtime
objects that are currently held exclusively in in-process ring buffers:

1. **Session** — :class:`~core.attached_runtime_session_registry.AttachedSessionRegistryEntry`
   records tracked by :class:`~core.attached_runtime_session_registry.AttachedSessionRegistry`.
2. **Contract** — :class:`~core.delegated_runtime_handoff_contract.DelegatedHandoffContractRecord`
   records tracked by :class:`~core.delegated_runtime_handoff_contract.DelegatedHandoffContractRuntime`.
3. **Binding** — :class:`~core.android_runtime_dispatch_binding.AndroidRuntimeDispatchBindingRecord`
   records tracked by :class:`~core.android_runtime_dispatch_binding.AndroidRuntimeDispatchBindingRuntime`.
4. **Flow entity** — :class:`~core.delegated_flow_entity.DelegatedFlowEntity` records tracked by
   :class:`~core.delegated_flow_entity.DelegatedFlowEntityRuntime`.

After a V2 process restart or crash the ring buffers are empty, meaning that
attachment state, handoff contract truth, dispatch binding truth, and flow
lineage metadata are all lost.  This directly undermines continuity, resume,
truth alignment, and operator diagnosis.

This module closes that durability gap by providing **four independent
file-backed durable stores** — one for each object category — following the
same production-grade design as
:class:`~core.task_lifecycle_persistence.TaskLifecyclePersistenceStore`:

* **Atomic writes** — payload is written to a temp file and then renamed so a
  partial write never corrupts the previous snapshot.
* **Thread-safe** — a per-store :class:`threading.Lock` guards every read and
  write.
* **Integrity checksum** — each snapshot carries a SHA-256 digest of the
  records payload so the loader can detect on-disk corruption.
* **Graceful degradation** — every function returns a valid (possibly empty)
  result when the backing store is absent or contains bad data.
* **Additive only** — no existing module is modified.
* **Pluggable store directory** — callers can supply an explicit path for test
  isolation.

Design: persistence ownership and schema organisation
------------------------------------------------------
The four stores share a common generic base class ``_GenericDurableStore``
that provides the atomic write/read/clear cycle.  Each concrete store wraps
one serialisable domain object and owns one JSON file:

===================  =============================================  ==============================================
Store class          Domain object                                  Default file
-------------------  ---------------------------------------------  ----------------------------------------------
SessionDurableStore  AttachedSessionRegistryEntry                  data/session_snapshot.json
ContractDurableStore DelegatedHandoffContractRecord                data/contract_snapshot.json
BindingDurableStore  AndroidRuntimeDispatchBindingRecord           data/binding_snapshot.json
FlowEntityDurableStore DelegatedFlowEntity                        data/flow_entity_snapshot.json
===================  =============================================  ==============================================

The ring buffers are **not** replaced; they remain the canonical in-process
runtime view.  The durable stores become the **continuity / recovery truth
source** so that V2 can rebuild the runtime view after a restart.

Restore paths
-------------
Each store provides a ``restore()`` method that deserialises the on-disk
snapshot and returns typed domain objects.  Callers (e.g. a restart-recovery
coordinator) can replay these records into the runtime ring buffers.

``DelegatedFlowPersistenceBundle`` wraps all four stores and exposes
``persist_all()`` / ``restore_all()`` convenience methods for checkpoint and
recovery.

Sentinels
---------
:data:`DELEGATED_FLOW_PERSISTENCE_IS_AUTHORITY`
    Affirms this module is the canonical durable persistence layer for the
    cross-device delegated flow chain.
:data:`DELEGATED_FLOW_PERSISTENCE_GAP_CLOSURE_SENTINEL`
    Affirms this module closes the in-memory-only persistence gap for session,
    contract, binding, and flow-entity objects.
:data:`SESSION_DURABLE_STORE_AUTHORITY`
    Affirms SessionDurableStore owns session snapshot persistence.
:data:`CONTRACT_DURABLE_STORE_AUTHORITY`
    Affirms ContractDurableStore owns contract snapshot persistence.
:data:`BINDING_DURABLE_STORE_AUTHORITY`
    Affirms BindingDurableStore owns binding snapshot persistence.
:data:`FLOW_ENTITY_DURABLE_STORE_AUTHORITY`
    Affirms FlowEntityDurableStore owns flow-entity snapshot persistence.
:data:`RING_BUFFER_IS_RUNTIME_VIEW_POLICY`
    Ring buffers remain the authoritative in-process runtime view; durable
    stores are the recovery source, not the runtime read path.
:data:`DURABLE_STORE_ATOMIC_WRITE_POLICY`
    All snapshot writes MUST use temp-file + rename atomicity.
:data:`DURABLE_STORE_INTEGRITY_CHECK_POLICY`
    All snapshots carry a SHA-256 digest; loaders MUST verify before restoring.

Public API
----------
Constants:
    :data:`DELEGATED_FLOW_PERSISTENCE_IS_AUTHORITY`
    :data:`DELEGATED_FLOW_PERSISTENCE_GAP_CLOSURE_SENTINEL`
    :data:`SESSION_DURABLE_STORE_AUTHORITY`
    :data:`CONTRACT_DURABLE_STORE_AUTHORITY`
    :data:`BINDING_DURABLE_STORE_AUTHORITY`
    :data:`FLOW_ENTITY_DURABLE_STORE_AUTHORITY`
    :data:`RING_BUFFER_IS_RUNTIME_VIEW_POLICY`
    :data:`DURABLE_STORE_ATOMIC_WRITE_POLICY`
    :data:`DURABLE_STORE_INTEGRITY_CHECK_POLICY`

Dataclasses:
    :class:`DurableSnapshotEnvelope`

Classes:
    :class:`SessionDurableStore`
    :class:`ContractDurableStore`
    :class:`BindingDurableStore`
    :class:`FlowEntityDurableStore`
    :class:`DelegatedFlowPersistenceBundle`

Functions:
    :func:`persist_session_snapshot`
    :func:`restore_sessions`
    :func:`persist_contract_snapshot`
    :func:`restore_contracts`
    :func:`persist_binding_snapshot`
    :func:`restore_bindings`
    :func:`persist_flow_entity_snapshot`
    :func:`restore_flow_entities`
    :func:`get_session_durable_store`
    :func:`reset_session_durable_store`
    :func:`get_contract_durable_store`
    :func:`reset_contract_durable_store`
    :func:`get_binding_durable_store`
    :func:`reset_binding_durable_store`
    :func:`get_flow_entity_durable_store`
    :func:`reset_flow_entity_durable_store`
    :func:`get_delegated_flow_persistence_bundle`
    :func:`reset_delegated_flow_persistence_bundle`
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Generic, List, Optional, Tuple, TypeVar

__all__ = [
    # Sentinels
    "DELEGATED_FLOW_PERSISTENCE_IS_AUTHORITY",
    "DELEGATED_FLOW_PERSISTENCE_GAP_CLOSURE_SENTINEL",
    "SESSION_DURABLE_STORE_AUTHORITY",
    "CONTRACT_DURABLE_STORE_AUTHORITY",
    "BINDING_DURABLE_STORE_AUTHORITY",
    "FLOW_ENTITY_DURABLE_STORE_AUTHORITY",
    "RING_BUFFER_IS_RUNTIME_VIEW_POLICY",
    "DURABLE_STORE_ATOMIC_WRITE_POLICY",
    "DURABLE_STORE_INTEGRITY_CHECK_POLICY",
    # Data class
    "DurableSnapshotEnvelope",
    # Stores
    "SessionDurableStore",
    "ContractDurableStore",
    "BindingDurableStore",
    "FlowEntityDurableStore",
    # Bundle
    "DelegatedFlowPersistenceBundle",
    # Convenience — session
    "persist_session_snapshot",
    "restore_sessions",
    # Convenience — contract
    "persist_contract_snapshot",
    "restore_contracts",
    # Convenience — binding
    "persist_binding_snapshot",
    "restore_bindings",
    # Convenience — flow entity
    "persist_flow_entity_snapshot",
    "restore_flow_entities",
    # Singleton accessors
    "get_session_durable_store",
    "reset_session_durable_store",
    "get_contract_durable_store",
    "reset_contract_durable_store",
    "get_binding_durable_store",
    "reset_binding_durable_store",
    "get_flow_entity_durable_store",
    "reset_flow_entity_durable_store",
    "get_delegated_flow_persistence_bundle",
    "reset_delegated_flow_persistence_bundle",
]

logger = logging.getLogger("Galaxy.DelegatedFlowPersistence")

# ---------------------------------------------------------------------------
# Sentinels
# ---------------------------------------------------------------------------

DELEGATED_FLOW_PERSISTENCE_IS_AUTHORITY: str = (
    "DELEGATED_FLOW_PERSISTENCE_IS_AUTHORITY: "
    "core/delegated_flow_persistence.py is the canonical durable persistence "
    "foundation for session, contract, binding, and flow-entity objects in the "
    "cross-device delegated flow chain.  It does not replace the ring-buffer "
    "runtime authorities; it provides file-backed recovery so these objects can "
    "be reconstructed after a V2 process restart or crash. (PR-2)"
)

DELEGATED_FLOW_PERSISTENCE_GAP_CLOSURE_SENTINEL: str = (
    "DELEGATED_FLOW_PERSISTENCE_GAP_CLOSURE::cross-device-flow-durability-pr2-v1: "
    "This module closes the in-memory-only persistence gap for the four core "
    "cross-device delegated flow object categories: session, contract, binding, "
    "and flow-entity.  These objects previously existed only in ring buffers and "
    "were silently lost on process restart. (PR-2)"
)

SESSION_DURABLE_STORE_AUTHORITY: str = (
    "SESSION_DURABLE_STORE_AUTHORITY: "
    "SessionDurableStore is the canonical durable snapshot layer for "
    "AttachedSessionRegistryEntry records.  The AttachedSessionRegistry ring "
    "buffer remains the runtime truth source; SessionDurableStore provides "
    "the recovery truth source after V2 restart. (PR-2)"
)

CONTRACT_DURABLE_STORE_AUTHORITY: str = (
    "CONTRACT_DURABLE_STORE_AUTHORITY: "
    "ContractDurableStore is the canonical durable snapshot layer for "
    "DelegatedHandoffContractRecord records.  The DelegatedHandoffContractRuntime "
    "ring buffer remains the runtime truth source. (PR-2)"
)

BINDING_DURABLE_STORE_AUTHORITY: str = (
    "BINDING_DURABLE_STORE_AUTHORITY: "
    "BindingDurableStore is the canonical durable snapshot layer for "
    "AndroidRuntimeDispatchBindingRecord records.  The "
    "AndroidRuntimeDispatchBindingRuntime ring buffer remains the runtime truth "
    "source. (PR-2)"
)

FLOW_ENTITY_DURABLE_STORE_AUTHORITY: str = (
    "FLOW_ENTITY_DURABLE_STORE_AUTHORITY: "
    "FlowEntityDurableStore is the canonical durable snapshot layer for "
    "DelegatedFlowEntity records.  The DelegatedFlowEntityRuntime ring buffer "
    "remains the runtime truth source. (PR-2)"
)

RING_BUFFER_IS_RUNTIME_VIEW_POLICY: str = (
    "POLICY::RING_BUFFER_IS_RUNTIME_VIEW: "
    "Ring buffers (AttachedSessionRegistry, DelegatedHandoffContractRuntime, "
    "AndroidRuntimeDispatchBindingRuntime, DelegatedFlowEntityRuntime) are the "
    "canonical in-process runtime view and MUST remain the read path during "
    "normal operation.  Durable stores are the recovery source only; they MUST "
    "NOT be used as the live runtime read path. (PR-2)"
)

DURABLE_STORE_ATOMIC_WRITE_POLICY: str = (
    "POLICY::DURABLE_STORE_ATOMIC_WRITE: "
    "All snapshot writes MUST write to a temp file in the same directory and "
    "then atomically rename it over the target path.  This guarantees that a "
    "partial write never corrupts the previous good snapshot. (PR-2)"
)

DURABLE_STORE_INTEGRITY_CHECK_POLICY: str = (
    "POLICY::DURABLE_STORE_INTEGRITY_CHECK: "
    "All snapshot envelopes carry a SHA-256 digest of the serialised records "
    "payload.  Loaders MUST verify the digest before restoring.  A digest "
    "mismatch MUST cause the load to fail gracefully (return None / empty list) "
    "rather than silently return potentially corrupted data. (PR-2)"
)

# ---------------------------------------------------------------------------
# Default store paths
# ---------------------------------------------------------------------------

_DATA_DIR = os.environ.get("GALAXY_DATA_DIR", "data")

_DEFAULT_SESSION_STORE_PATH = os.path.join(_DATA_DIR, "session_snapshot.json")
_DEFAULT_CONTRACT_STORE_PATH = os.path.join(_DATA_DIR, "contract_snapshot.json")
_DEFAULT_BINDING_STORE_PATH = os.path.join(_DATA_DIR, "binding_snapshot.json")
_DEFAULT_FLOW_ENTITY_STORE_PATH = os.path.join(_DATA_DIR, "flow_entity_snapshot.json")

# ---------------------------------------------------------------------------
# DurableSnapshotEnvelope
# ---------------------------------------------------------------------------


@dataclass
class DurableSnapshotEnvelope:
    """Generic envelope wrapping a list of serialised domain-object dicts.

    Carries metadata and an integrity digest so the loader can detect
    on-disk corruption before deserialising the payload.

    Attributes
    ----------
    snapshot_id
        Unique identifier for this snapshot instance.
    schema_kind
        String tag identifying the object category (e.g. ``"session"``).
    schema_version
        Version string for future schema evolution (currently ``"1"``).
    created_at
        Unix epoch seconds when the snapshot was written.
    process_pid
        PID of the writer process (informational).
    records
        List of JSON-safe dicts, each representing one domain object.
    records_digest
        SHA-256 hex digest of ``json.dumps(records, sort_keys=True)``.
        Used for integrity verification on load.
    """

    snapshot_id: str = field(
        default_factory=lambda: f"dfp_{uuid.uuid4().hex[:12]}"
    )
    schema_kind: str = ""
    schema_version: str = "1"
    created_at: float = field(default_factory=time.time)
    process_pid: int = field(default_factory=os.getpid)
    records: List[Dict[str, Any]] = field(default_factory=list)
    records_digest: str = ""

    # ------------------------------------------------------------------
    # Integrity helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_digest(records: List[Dict[str, Any]]) -> str:
        """Return SHA-256 hex digest of the canonical JSON representation."""
        payload = json.dumps(records, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def compute_and_set_digest(self) -> None:
        """Compute the digest from ``self.records`` and store it in-place."""
        self.records_digest = self._compute_digest(self.records)

    def verify_digest(self) -> bool:
        """Return True iff ``records_digest`` matches ``records``."""
        if not self.records_digest:
            return False
        return self.records_digest == self._compute_digest(self.records)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "snapshot_id": self.snapshot_id,
            "schema_kind": self.schema_kind,
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "process_pid": self.process_pid,
            "records": list(self.records),
            "records_digest": self.records_digest,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "DurableSnapshotEnvelope":
        """Reconstruct from a serialised dict; unknown fields are ignored."""
        return cls(
            snapshot_id=d.get("snapshot_id", f"dfp_{uuid.uuid4().hex[:12]}"),
            schema_kind=str(d.get("schema_kind", "")),
            schema_version=str(d.get("schema_version", "1")),
            created_at=float(d.get("created_at", time.time())),
            process_pid=int(d.get("process_pid", 0)),
            records=list(d.get("records", [])),
            records_digest=str(d.get("records_digest", "")),
        )


# ---------------------------------------------------------------------------
# Generic base store
# ---------------------------------------------------------------------------

_T = TypeVar("_T")


class _GenericDurableStore(Generic[_T]):
    """Thread-safe, file-backed atomic snapshot store.

    Subclasses specialise ``_SCHEMA_KIND``, ``_DEFAULT_PATH``, and the two
    abstract methods ``_to_dict`` / ``_from_dict``.

    Parameters
    ----------
    store_path:
        Absolute or relative path to the JSON snapshot file.
    """

    _SCHEMA_KIND: str = "unknown"
    _DEFAULT_PATH: str = ""

    def __init__(self, store_path: Optional[str] = None) -> None:
        self._store_path: str = store_path or self._DEFAULT_PATH
        self._lock = threading.Lock()
        try:
            os.makedirs(
                os.path.dirname(os.path.abspath(self._store_path)),
                exist_ok=True,
            )
        except Exception as exc:  # pragma: no cover
            logger.warning(
                "DurableStore[%s]: could not create store directory: %s",
                self._SCHEMA_KIND,
                exc,
            )

    # ------------------------------------------------------------------
    # Abstract interface (subclasses must implement)
    # ------------------------------------------------------------------

    def _to_dict(self, obj: _T) -> Dict[str, Any]:  # pragma: no cover
        raise NotImplementedError

    def _from_dict(self, d: Dict[str, Any]) -> _T:  # pragma: no cover
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def save(self, objects: List[_T]) -> bool:
        """Atomically persist *objects* to the durable snapshot file.

        Parameters
        ----------
        objects:
            List of domain objects to snapshot.

        Returns
        -------
        bool
            ``True`` on success; ``False`` if the write failed (error logged).
        """
        try:
            records = [self._to_dict(obj) for obj in objects]
            envelope = DurableSnapshotEnvelope(
                schema_kind=self._SCHEMA_KIND,
                records=records,
            )
            envelope.compute_and_set_digest()
            payload = json.dumps(envelope.to_dict(), indent=2, ensure_ascii=False)
            store_dir = os.path.dirname(os.path.abspath(self._store_path))
            with self._lock:
                fd, tmp_path = tempfile.mkstemp(dir=store_dir, suffix=".tmp")
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as fh:
                        fh.write(payload)
                    os.replace(tmp_path, self._store_path)
                except Exception:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
                    raise
            logger.debug(
                "DurableStore[%s]: saved snapshot %s (%d records)",
                self._SCHEMA_KIND,
                envelope.snapshot_id,
                len(records),
            )
            return True
        except Exception as exc:
            logger.warning(
                "DurableStore[%s]: failed to save snapshot: %s",
                self._SCHEMA_KIND,
                exc,
            )
            return False

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def load(self) -> Tuple[Optional[DurableSnapshotEnvelope], List[_T]]:
        """Load and deserialise the snapshot from disk.

        Returns
        -------
        tuple[DurableSnapshotEnvelope | None, list[T]]
            A ``(envelope, objects)`` pair.  Both are empty/None when no
            snapshot exists, when the file is corrupt, or when the digest
            does not match.
        """
        with self._lock:
            if not os.path.exists(self._store_path):
                return None, []
            try:
                with open(self._store_path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except Exception as exc:
                logger.warning(
                    "DurableStore[%s]: failed to read snapshot file: %s",
                    self._SCHEMA_KIND,
                    exc,
                )
                return None, []

        try:
            envelope = DurableSnapshotEnvelope.from_dict(data)
        except Exception as exc:
            logger.warning(
                "DurableStore[%s]: failed to parse snapshot envelope: %s",
                self._SCHEMA_KIND,
                exc,
            )
            return None, []

        if not envelope.verify_digest():
            logger.warning(
                "DurableStore[%s]: snapshot %s failed integrity check — "
                "digest mismatch; skipping restore",
                self._SCHEMA_KIND,
                envelope.snapshot_id,
            )
            return envelope, []

        objects: List[_T] = []
        for i, rec in enumerate(envelope.records):
            try:
                objects.append(self._from_dict(rec))
            except Exception as exc:
                logger.warning(
                    "DurableStore[%s]: failed to deserialise record %d: %s; skipping",
                    self._SCHEMA_KIND,
                    i,
                    exc,
                )

        logger.debug(
            "DurableStore[%s]: loaded snapshot %s (%d/%d records restored)",
            self._SCHEMA_KIND,
            envelope.snapshot_id,
            len(objects),
            len(envelope.records),
        )
        return envelope, objects

    # ------------------------------------------------------------------
    # Clear
    # ------------------------------------------------------------------

    def clear(self) -> bool:
        """Remove the snapshot file from disk.

        Returns
        -------
        bool
            ``True`` if the file was removed (or did not exist); ``False``
            on error.
        """
        with self._lock:
            if not os.path.exists(self._store_path):
                return True
            try:
                os.unlink(self._store_path)
                logger.debug(
                    "DurableStore[%s]: snapshot cleared", self._SCHEMA_KIND
                )
                return True
            except Exception as exc:
                logger.warning(
                    "DurableStore[%s]: failed to clear snapshot: %s",
                    self._SCHEMA_KIND,
                    exc,
                )
                return False

    @property
    def store_path(self) -> str:
        """Absolute path to the snapshot file."""
        return self._store_path


# ---------------------------------------------------------------------------
# SessionDurableStore
# ---------------------------------------------------------------------------


class SessionDurableStore(
    _GenericDurableStore["AttachedSessionRegistryEntry"]
):
    """Durable store for :class:`~core.attached_runtime_session_registry.AttachedSessionRegistryEntry`.

    Owns the snapshot file ``data/session_snapshot.json`` (by default).
    Follows :data:`SESSION_DURABLE_STORE_AUTHORITY`.
    """

    _SCHEMA_KIND = "session"
    _DEFAULT_PATH = _DEFAULT_SESSION_STORE_PATH

    def _to_dict(self, obj: Any) -> Dict[str, Any]:
        return obj.to_dict()

    def _from_dict(self, d: Dict[str, Any]) -> Any:
        from core.attached_runtime_session_registry import AttachedSessionRegistryEntry
        return AttachedSessionRegistryEntry.from_dict(d)


# ---------------------------------------------------------------------------
# ContractDurableStore
# ---------------------------------------------------------------------------


class ContractDurableStore(
    _GenericDurableStore["DelegatedHandoffContractRecord"]
):
    """Durable store for :class:`~core.delegated_runtime_handoff_contract.DelegatedHandoffContractRecord`.

    Owns the snapshot file ``data/contract_snapshot.json`` (by default).
    Follows :data:`CONTRACT_DURABLE_STORE_AUTHORITY`.
    """

    _SCHEMA_KIND = "contract"
    _DEFAULT_PATH = _DEFAULT_CONTRACT_STORE_PATH

    def _to_dict(self, obj: Any) -> Dict[str, Any]:
        return obj.to_dict()

    def _from_dict(self, d: Dict[str, Any]) -> Any:
        from core.delegated_runtime_handoff_contract import DelegatedHandoffContractRecord
        return DelegatedHandoffContractRecord.from_dict(d)


# ---------------------------------------------------------------------------
# BindingDurableStore
# ---------------------------------------------------------------------------


class BindingDurableStore(
    _GenericDurableStore["AndroidRuntimeDispatchBindingRecord"]
):
    """Durable store for :class:`~core.android_runtime_dispatch_binding.AndroidRuntimeDispatchBindingRecord`.

    Owns the snapshot file ``data/binding_snapshot.json`` (by default).
    Follows :data:`BINDING_DURABLE_STORE_AUTHORITY`.
    """

    _SCHEMA_KIND = "binding"
    _DEFAULT_PATH = _DEFAULT_BINDING_STORE_PATH

    def _to_dict(self, obj: Any) -> Dict[str, Any]:
        return obj.to_dict()

    def _from_dict(self, d: Dict[str, Any]) -> Any:
        from core.android_runtime_dispatch_binding import AndroidRuntimeDispatchBindingRecord
        return AndroidRuntimeDispatchBindingRecord.from_dict(d)


# ---------------------------------------------------------------------------
# FlowEntityDurableStore
# ---------------------------------------------------------------------------


class FlowEntityDurableStore(
    _GenericDurableStore["DelegatedFlowEntity"]
):
    """Durable store for :class:`~core.delegated_flow_entity.DelegatedFlowEntity`.

    Owns the snapshot file ``data/flow_entity_snapshot.json`` (by default).
    Follows :data:`FLOW_ENTITY_DURABLE_STORE_AUTHORITY`.
    """

    _SCHEMA_KIND = "flow_entity"
    _DEFAULT_PATH = _DEFAULT_FLOW_ENTITY_STORE_PATH

    def _to_dict(self, obj: Any) -> Dict[str, Any]:
        return obj.to_dict()

    def _from_dict(self, d: Dict[str, Any]) -> Any:
        from core.delegated_flow_entity import DelegatedFlowEntity
        return DelegatedFlowEntity.from_dict(d)


# ---------------------------------------------------------------------------
# DelegatedFlowPersistenceBundle
# ---------------------------------------------------------------------------


class DelegatedFlowPersistenceBundle:
    """Convenience wrapper that coordinates all four durable stores.

    Provides ``persist_all()`` / ``restore_all()`` for checkpoint and
    recovery across session, contract, binding, and flow-entity categories.

    Parameters
    ----------
    session_store:
        :class:`SessionDurableStore` instance.  Uses singleton if None.
    contract_store:
        :class:`ContractDurableStore` instance.  Uses singleton if None.
    binding_store:
        :class:`BindingDurableStore` instance.  Uses singleton if None.
    flow_entity_store:
        :class:`FlowEntityDurableStore` instance.  Uses singleton if None.
    """

    def __init__(
        self,
        *,
        session_store: Optional[SessionDurableStore] = None,
        contract_store: Optional[ContractDurableStore] = None,
        binding_store: Optional[BindingDurableStore] = None,
        flow_entity_store: Optional[FlowEntityDurableStore] = None,
    ) -> None:
        self.session_store: SessionDurableStore = (
            session_store or get_session_durable_store()
        )
        self.contract_store: ContractDurableStore = (
            contract_store or get_contract_durable_store()
        )
        self.binding_store: BindingDurableStore = (
            binding_store or get_binding_durable_store()
        )
        self.flow_entity_store: FlowEntityDurableStore = (
            flow_entity_store or get_flow_entity_durable_store()
        )

    # ------------------------------------------------------------------
    # Coordinated checkpoint
    # ------------------------------------------------------------------

    def persist_all(
        self,
        *,
        sessions: Optional[List[Any]] = None,
        contracts: Optional[List[Any]] = None,
        bindings: Optional[List[Any]] = None,
        flow_entities: Optional[List[Any]] = None,
    ) -> Dict[str, bool]:
        """Persist all four object categories in one call.

        Any argument that is ``None`` is sourced from the corresponding
        process-level ring-buffer singleton.

        Parameters
        ----------
        sessions:
            List of :class:`~core.attached_runtime_session_registry.AttachedSessionRegistryEntry`
            objects.  If None, the module singleton is queried.
        contracts:
            List of :class:`~core.delegated_runtime_handoff_contract.DelegatedHandoffContractRecord`
            objects.  If None, the module singleton is queried.
        bindings:
            List of :class:`~core.android_runtime_dispatch_binding.AndroidRuntimeDispatchBindingRecord`
            objects.  If None, the module singleton is queried.
        flow_entities:
            List of :class:`~core.delegated_flow_entity.DelegatedFlowEntity`
            objects.  If None, the module singleton is queried.

        Returns
        -------
        dict[str, bool]
            Mapping from category name to success flag.
        """
        if sessions is None:
            from core.attached_runtime_session_registry import get_session_registry
            sessions = get_session_registry().list_all()
        if contracts is None:
            from core.delegated_runtime_handoff_contract import get_handoff_contract_runtime
            contracts = get_handoff_contract_runtime().list_all()
        if bindings is None:
            from core.android_runtime_dispatch_binding import get_dispatch_binding_runtime
            bindings = get_dispatch_binding_runtime().list_all()
        if flow_entities is None:
            from core.delegated_flow_entity import get_delegated_flow_entity_runtime
            flow_entities = get_delegated_flow_entity_runtime().list_all()

        return {
            "session": self.session_store.save(sessions),
            "contract": self.contract_store.save(contracts),
            "binding": self.binding_store.save(bindings),
            "flow_entity": self.flow_entity_store.save(flow_entities),
        }

    # ------------------------------------------------------------------
    # Coordinated restore
    # ------------------------------------------------------------------

    def restore_all(self) -> Dict[str, List[Any]]:
        """Load all four categories from their durable stores.

        Returns
        -------
        dict[str, list]
            Keys are ``"session"``, ``"contract"``, ``"binding"``,
            ``"flow_entity"``; values are lists of restored domain objects
            (empty on load failure or digest mismatch).
        """
        _, sessions = self.session_store.load()
        _, contracts = self.contract_store.load()
        _, bindings = self.binding_store.load()
        _, flow_entities = self.flow_entity_store.load()
        return {
            "session": sessions,
            "contract": contracts,
            "binding": bindings,
            "flow_entity": flow_entities,
        }


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------

_session_store_instance: Optional[SessionDurableStore] = None
_session_store_lock = threading.Lock()

_contract_store_instance: Optional[ContractDurableStore] = None
_contract_store_lock = threading.Lock()

_binding_store_instance: Optional[BindingDurableStore] = None
_binding_store_lock = threading.Lock()

_flow_entity_store_instance: Optional[FlowEntityDurableStore] = None
_flow_entity_store_lock = threading.Lock()

_bundle_instance: Optional[DelegatedFlowPersistenceBundle] = None
_bundle_lock = threading.Lock()


def get_session_durable_store(
    store_path: Optional[str] = None,
) -> SessionDurableStore:
    """Return (or lazily create) the process-level :class:`SessionDurableStore`."""
    global _session_store_instance
    with _session_store_lock:
        if _session_store_instance is None:
            _session_store_instance = SessionDurableStore(store_path=store_path)
    return _session_store_instance


def reset_session_durable_store() -> None:
    """Reset the process-level singleton (for test isolation)."""
    global _session_store_instance
    with _session_store_lock:
        _session_store_instance = None


def get_contract_durable_store(
    store_path: Optional[str] = None,
) -> ContractDurableStore:
    """Return (or lazily create) the process-level :class:`ContractDurableStore`."""
    global _contract_store_instance
    with _contract_store_lock:
        if _contract_store_instance is None:
            _contract_store_instance = ContractDurableStore(store_path=store_path)
    return _contract_store_instance


def reset_contract_durable_store() -> None:
    """Reset the process-level singleton (for test isolation)."""
    global _contract_store_instance
    with _contract_store_lock:
        _contract_store_instance = None


def get_binding_durable_store(
    store_path: Optional[str] = None,
) -> BindingDurableStore:
    """Return (or lazily create) the process-level :class:`BindingDurableStore`."""
    global _binding_store_instance
    with _binding_store_lock:
        if _binding_store_instance is None:
            _binding_store_instance = BindingDurableStore(store_path=store_path)
    return _binding_store_instance


def reset_binding_durable_store() -> None:
    """Reset the process-level singleton (for test isolation)."""
    global _binding_store_instance
    with _binding_store_lock:
        _binding_store_instance = None


def get_flow_entity_durable_store(
    store_path: Optional[str] = None,
) -> FlowEntityDurableStore:
    """Return (or lazily create) the process-level :class:`FlowEntityDurableStore`."""
    global _flow_entity_store_instance
    with _flow_entity_store_lock:
        if _flow_entity_store_instance is None:
            _flow_entity_store_instance = FlowEntityDurableStore(
                store_path=store_path
            )
    return _flow_entity_store_instance


def reset_flow_entity_durable_store() -> None:
    """Reset the process-level singleton (for test isolation)."""
    global _flow_entity_store_instance
    with _flow_entity_store_lock:
        _flow_entity_store_instance = None


def get_delegated_flow_persistence_bundle(
    *,
    session_store: Optional[SessionDurableStore] = None,
    contract_store: Optional[ContractDurableStore] = None,
    binding_store: Optional[BindingDurableStore] = None,
    flow_entity_store: Optional[FlowEntityDurableStore] = None,
) -> DelegatedFlowPersistenceBundle:
    """Return (or lazily create) the process-level :class:`DelegatedFlowPersistenceBundle`."""
    global _bundle_instance
    with _bundle_lock:
        if _bundle_instance is None:
            _bundle_instance = DelegatedFlowPersistenceBundle(
                session_store=session_store,
                contract_store=contract_store,
                binding_store=binding_store,
                flow_entity_store=flow_entity_store,
            )
    return _bundle_instance


def reset_delegated_flow_persistence_bundle() -> None:
    """Reset the process-level singleton (for test isolation)."""
    global _bundle_instance
    with _bundle_lock:
        _bundle_instance = None


# ---------------------------------------------------------------------------
# Convenience functions — session
# ---------------------------------------------------------------------------


def persist_session_snapshot(
    sessions: List[Any],
    *,
    store: Optional[SessionDurableStore] = None,
) -> bool:
    """Persist *sessions* to the durable session store.

    Parameters
    ----------
    sessions:
        List of :class:`~core.attached_runtime_session_registry.AttachedSessionRegistryEntry`
        objects.
    store:
        Optional explicit store; uses singleton if None.

    Returns
    -------
    bool
        ``True`` on success.
    """
    _store = store if store is not None else get_session_durable_store()
    return _store.save(sessions)


def restore_sessions(
    *,
    store: Optional[SessionDurableStore] = None,
) -> List[Any]:
    """Restore session entries from the durable store.

    Parameters
    ----------
    store:
        Optional explicit store; uses singleton if None.

    Returns
    -------
    list
        Restored :class:`~core.attached_runtime_session_registry.AttachedSessionRegistryEntry`
        objects (empty on failure or missing snapshot).
    """
    _store = store if store is not None else get_session_durable_store()
    _, objects = _store.load()
    return objects


# ---------------------------------------------------------------------------
# Convenience functions — contract
# ---------------------------------------------------------------------------


def persist_contract_snapshot(
    contracts: List[Any],
    *,
    store: Optional[ContractDurableStore] = None,
) -> bool:
    """Persist *contracts* to the durable contract store.

    Parameters
    ----------
    contracts:
        List of :class:`~core.delegated_runtime_handoff_contract.DelegatedHandoffContractRecord`
        objects.
    store:
        Optional explicit store; uses singleton if None.

    Returns
    -------
    bool
        ``True`` on success.
    """
    _store = store if store is not None else get_contract_durable_store()
    return _store.save(contracts)


def restore_contracts(
    *,
    store: Optional[ContractDurableStore] = None,
) -> List[Any]:
    """Restore contract records from the durable store.

    Parameters
    ----------
    store:
        Optional explicit store; uses singleton if None.

    Returns
    -------
    list
        Restored :class:`~core.delegated_runtime_handoff_contract.DelegatedHandoffContractRecord`
        objects (empty on failure or missing snapshot).
    """
    _store = store if store is not None else get_contract_durable_store()
    _, objects = _store.load()
    return objects


# ---------------------------------------------------------------------------
# Convenience functions — binding
# ---------------------------------------------------------------------------


def persist_binding_snapshot(
    bindings: List[Any],
    *,
    store: Optional[BindingDurableStore] = None,
) -> bool:
    """Persist *bindings* to the durable binding store.

    Parameters
    ----------
    bindings:
        List of :class:`~core.android_runtime_dispatch_binding.AndroidRuntimeDispatchBindingRecord`
        objects.
    store:
        Optional explicit store; uses singleton if None.

    Returns
    -------
    bool
        ``True`` on success.
    """
    _store = store if store is not None else get_binding_durable_store()
    return _store.save(bindings)


def restore_bindings(
    *,
    store: Optional[BindingDurableStore] = None,
) -> List[Any]:
    """Restore binding records from the durable store.

    Parameters
    ----------
    store:
        Optional explicit store; uses singleton if None.

    Returns
    -------
    list
        Restored :class:`~core.android_runtime_dispatch_binding.AndroidRuntimeDispatchBindingRecord`
        objects (empty on failure or missing snapshot).
    """
    _store = store if store is not None else get_binding_durable_store()
    _, objects = _store.load()
    return objects


# ---------------------------------------------------------------------------
# Convenience functions — flow entity
# ---------------------------------------------------------------------------


def persist_flow_entity_snapshot(
    flow_entities: List[Any],
    *,
    store: Optional[FlowEntityDurableStore] = None,
) -> bool:
    """Persist *flow_entities* to the durable flow-entity store.

    Parameters
    ----------
    flow_entities:
        List of :class:`~core.delegated_flow_entity.DelegatedFlowEntity` objects.
    store:
        Optional explicit store; uses singleton if None.

    Returns
    -------
    bool
        ``True`` on success.
    """
    _store = store if store is not None else get_flow_entity_durable_store()
    return _store.save(flow_entities)


def restore_flow_entities(
    *,
    store: Optional[FlowEntityDurableStore] = None,
) -> List[Any]:
    """Restore flow-entity objects from the durable store.

    Parameters
    ----------
    store:
        Optional explicit store; uses singleton if None.

    Returns
    -------
    list
        Restored :class:`~core.delegated_flow_entity.DelegatedFlowEntity` objects
        (empty on failure or missing snapshot).
    """
    _store = store if store is not None else get_flow_entity_durable_store()
    _, objects = _store.load()
    return objects
