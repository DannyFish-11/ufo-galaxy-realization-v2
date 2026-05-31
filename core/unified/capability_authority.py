from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

from core.capability_runtime.capability_state import (
    CapabilityAvailability,
    CapabilityRuntimeState,
)

from .capability_contract import CapabilityContract, CapabilitySource
from .capability_record import UnifiedCapabilityRecord

logger = logging.getLogger("Galaxy.Unified.CapabilityAuthority")

UNIFIED_CAPABILITY_PLANE_AUTHORITY = (
    "UNIFIED_CAPABILITY_PLANE_AUTHORITY::"
    "CapabilityAuthority::registry+runtime+lifecycle"
)


class CapabilityAuthority:
    """Single capability-plane mutation and projection authority."""

    _instance: Optional["CapabilityAuthority"] = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        self._lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "CapabilityAuthority":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @staticmethod
    def _get_registry() -> Any:
        from core.agent.capability_registry import CapabilityRegistry

        return CapabilityRegistry.get_instance()

    @staticmethod
    def _invalidate_resolver() -> None:
        try:
            from core.unified.capability_resolver import get_capability_resolver

            get_capability_resolver().invalidate_cache()
        except Exception as exc:
            logger.warning("Exception suppressed: %s", exc)

    @staticmethod
    def _coerce_contract(value: Any) -> CapabilityContract:
        from core.agent.capability_registry import CapabilityItem

        if isinstance(value, CapabilityContract):
            return value
        if isinstance(value, CapabilityItem):
            src_raw = value.source or "unknown"
            try:
                source = CapabilitySource(src_raw)
            except ValueError:
                source = CapabilitySource.UNKNOWN
            metadata = dict(value.metadata or {})
            return CapabilityContract(
                name=value.name,
                description=value.description,
                source=source,
                source_id=value.source_id,
                version=str(metadata.get("contract_version") or "1.0.0"),
                parameters=dict(value.parameters or {}),
                available=bool(value.available),
                tags=list(metadata.get("contract_tags") or []),
                metadata=metadata,
                created_at=float(metadata.get("contract_created_at") or time.time()),
            )
        if isinstance(value, dict):
            return CapabilityContract.from_dict(value)
        raise TypeError(f"Unsupported capability input type: {type(value).__name__}")

    @staticmethod
    def _build_runtime_state(name: str, runtime_payload: Dict[str, Any]) -> CapabilityRuntimeState:
        payload = {
            "name": name,
            "availability": runtime_payload.get("availability", CapabilityAvailability.UNKNOWN.value),
            "device_bindings": runtime_payload.get("device_bindings", []),
            "preferred_device_ids": runtime_payload.get("preferred_device_ids", []),
            "constraint_flags": runtime_payload.get("constraint_flags", {}),
            "reliability_flags": runtime_payload.get("reliability_flags", {}),
            "last_updated": runtime_payload.get("last_updated", time.time()),
            "metadata": runtime_payload.get("metadata", {}),
        }
        return CapabilityRuntimeState.from_dict(payload)

    def _sync_runtime_registry(
        self,
        state: CapabilityRuntimeState,
        *,
        deregister: bool = False,
    ) -> None:
        try:
            from core.capability_runtime.capability_registry_runtime import CapabilityRuntimeRegistry

            runtime_registry = CapabilityRuntimeRegistry.get_instance()
            if deregister:
                runtime_registry.deregister(state.name, _sync_authority=False)
            else:
                runtime_registry.register(state, _sync_authority=False)
        except Exception as exc:
            logger.debug("runtime registry projection sync skipped for %s: %s", state.name, exc)

    def upsert_contract(
        self,
        capability: Any,
        *,
        mutation_source: str = "unknown",
        publication_source: str = "",
        lifecycle_event: str = "capability_registered",
        sync_runtime_registry: bool = True,
    ) -> UnifiedCapabilityRecord:
        contract = self._coerce_contract(capability)
        registry = self._get_registry()
        existing = registry.get(contract.name)
        existing_metadata = dict(getattr(existing, "metadata", {}) or {})
        existing_plane = dict(existing_metadata.get("capability_plane") or {})
        runtime_payload = dict(existing_metadata.get("runtime_state") or {})
        record_version = int(existing_plane.get("record_version", 0) or 0) + 1

        merged_metadata = dict(existing_metadata)
        merged_metadata.update(dict(contract.metadata or {}))
        merged_metadata["capability_id"] = contract.name
        merged_metadata["authority_lineage"] = [
            "capability_authority",
            "capability_registry",
            "capability_resolver",
        ]
        merged_metadata["capability_plane"] = {
            "authority": UNIFIED_CAPABILITY_PLANE_AUTHORITY,
            "record_version": record_version,
            "lifecycle_event": lifecycle_event,
            "mutation_source": mutation_source,
            "publication_source": publication_source or merged_metadata.get("publication_source") or contract.source_id,
            "last_updated": time.time(),
            "authority_lineage": list(merged_metadata["authority_lineage"]),
        }
        if runtime_payload:
            merged_metadata["runtime_state"] = runtime_payload

        runtime_state = (
            self._build_runtime_state(contract.name, merged_metadata["runtime_state"])
            if merged_metadata.get("runtime_state")
            else None
        )
        effective_available = (
            runtime_state.is_routable() if runtime_state is not None else bool(contract.available)
        )
        updated_contract = CapabilityContract(
            name=contract.name,
            description=contract.description,
            source=contract.source,
            source_id=contract.source_id,
            version=contract.version,
            parameters=dict(contract.parameters or {}),
            available=effective_available,
            tags=list(contract.tags or []),
            metadata=merged_metadata,
            contract_id=contract.contract_id,
            created_at=contract.created_at,
        )
        registry.register(updated_contract)
        if runtime_state is not None and sync_runtime_registry:
            self._sync_runtime_registry(runtime_state)
        self._invalidate_resolver()
        return self.get_record(contract.name)  # type: ignore[return-value]

    def update_runtime(
        self,
        name: str,
        *,
        availability: Optional[str] = None,
        device_bindings: Optional[List[str]] = None,
        preferred_device_ids: Optional[List[str]] = None,
        constraint_flags: Optional[Dict[str, Any]] = None,
        reliability_flags: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        mutation_source: str = "runtime_update",
        lifecycle_event: str = "capability_updated",
        sync_runtime_registry: bool = True,
    ) -> Optional[UnifiedCapabilityRecord]:
        registry = self._get_registry()
        existing = registry.get(name)

        if existing is None:
            placeholder = CapabilityContract(
                name=name,
                description=f"Runtime-backed capability {name}",
                source=CapabilitySource.UNKNOWN,
                source_id=name,
                available=False,
                metadata={"runtime_only_placeholder": True},
            )
            self.upsert_contract(
                placeholder,
                mutation_source=mutation_source,
                publication_source="runtime",
                lifecycle_event="capability_runtime_placeholder_registered",
                sync_runtime_registry=False,
            )
            existing = registry.get(name)
            if existing is None:
                return None

        existing_metadata = dict(existing.metadata or {})
        plane = dict(existing_metadata.get("capability_plane") or {})
        runtime_payload = dict(existing_metadata.get("runtime_state") or {})
        runtime_payload.update(
            {
                k: v
                for k, v in {
                    "availability": availability,
                    "device_bindings": device_bindings,
                    "preferred_device_ids": preferred_device_ids,
                    "constraint_flags": constraint_flags,
                    "reliability_flags": reliability_flags,
                }.items()
                if v is not None
            }
        )
        runtime_payload["last_updated"] = time.time()
        runtime_payload["metadata"] = {
            **dict(runtime_payload.get("metadata") or {}),
            **dict(metadata or {}),
        }
        record_version = int(plane.get("record_version", 0) or 0) + 1

        item_source = getattr(existing, "source", "unknown") or "unknown"
        try:
            contract_source = CapabilitySource(item_source)
        except ValueError:
            contract_source = CapabilitySource.UNKNOWN

        merged_metadata = {
            **existing_metadata,
            "runtime_state": runtime_payload,
            "capability_plane": {
                "authority": UNIFIED_CAPABILITY_PLANE_AUTHORITY,
                "record_version": record_version,
                "lifecycle_event": lifecycle_event,
                "mutation_source": mutation_source,
                "publication_source": plane.get("publication_source") or existing_metadata.get("publication_source") or getattr(existing, "source_id", ""),
                "last_updated": runtime_payload["last_updated"],
                "authority_lineage": list(
                    existing_metadata.get("authority_lineage")
                    or plane.get("authority_lineage")
                    or ["capability_authority", "capability_registry", "capability_resolver"]
                ),
            },
        }
        runtime_state = self._build_runtime_state(name, runtime_payload)
        updated_contract = CapabilityContract(
            name=name,
            description=getattr(existing, "description", ""),
            source=contract_source,
            source_id=getattr(existing, "source_id", ""),
            version=str(merged_metadata.get("contract_version") or "1.0.0"),
            parameters=dict(getattr(existing, "parameters", {}) or {}),
            available=runtime_state.is_routable(),
            tags=list(merged_metadata.get("contract_tags") or []),
            metadata=merged_metadata,
        )
        registry.register(updated_contract)
        if sync_runtime_registry:
            self._sync_runtime_registry(runtime_state)
        self._invalidate_resolver()
        return self.get_record(name)

    def clear_runtime(
        self,
        name: str,
        *,
        mutation_source: str = "runtime_clear",
        sync_runtime_registry: bool = True,
    ) -> bool:
        registry = self._get_registry()
        existing = registry.get(name)
        if existing is None:
            return False

        existing_metadata = dict(existing.metadata or {})
        plane = dict(existing_metadata.get("capability_plane") or {})
        existing_metadata.pop("runtime_state", None)
        existing_metadata["capability_plane"] = {
            **plane,
            "authority": UNIFIED_CAPABILITY_PLANE_AUTHORITY,
            "record_version": int(plane.get("record_version", 0) or 0) + 1,
            "lifecycle_event": "capability_runtime_cleared",
            "mutation_source": mutation_source,
            "last_updated": time.time(),
        }
        try:
            source = CapabilitySource(getattr(existing, "source", "unknown") or "unknown")
        except ValueError:
            source = CapabilitySource.UNKNOWN
        registry.register(
            CapabilityContract(
                name=name,
                description=getattr(existing, "description", ""),
                source=source,
                source_id=getattr(existing, "source_id", ""),
                version=str(existing_metadata.get("contract_version") or "1.0.0"),
                parameters=dict(getattr(existing, "parameters", {}) or {}),
                available=bool(getattr(existing, "available", True)),
                tags=list(existing_metadata.get("contract_tags") or []),
                metadata=existing_metadata,
            )
        )
        if sync_runtime_registry:
            self._sync_runtime_registry(CapabilityRuntimeState(name=name), deregister=True)
        self._invalidate_resolver()
        return True

    def remove(
        self,
        name: str,
        *,
        mutation_source: str = "remove",
        sync_runtime_registry: bool = True,
    ) -> bool:
        registry = self._get_registry()
        existing = registry.get(name)
        registry.eject(name)
        if sync_runtime_registry:
            self._sync_runtime_registry(CapabilityRuntimeState(name=name), deregister=True)
        self._invalidate_resolver()
        if existing is not None:
            logger.debug("CapabilityAuthority.remove: %s via %s", name, mutation_source)
            return True
        return False

    def get_record(self, name: str) -> Optional[UnifiedCapabilityRecord]:
        from core.unified.capability_resolver import CapabilityResolver

        registry = self._get_registry()
        item = registry.get(name)
        if item is None:
            return None
        contract = CapabilityResolver._item_to_contract(item)
        metadata = dict(contract.metadata or {})
        runtime_state = (
            self._build_runtime_state(name, metadata.get("runtime_state") or {})
            if metadata.get("runtime_state")
            else None
        )
        return UnifiedCapabilityRecord.from_contract(contract, runtime_state=runtime_state)

    def list_records(self, source: Optional[CapabilitySource] = None) -> List[UnifiedCapabilityRecord]:
        registry = self._get_registry()
        items = list(getattr(registry, "_items", {}).values())
        names = sorted(getattr(item, "name", "") for item in items if getattr(item, "name", ""))
        records = [self.get_record(name) for name in names]
        filtered = [record for record in records if record is not None]
        if source is None:
            return filtered
        return [
            record
            for record in filtered
            if record.source_kind == (source.value if hasattr(source, "value") else str(source))
        ]
