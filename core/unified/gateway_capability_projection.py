from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.unified.capability_authority import CapabilityAuthority

from .capability_contract import CapabilitySource
from .capability_resolver import get_capability_resolver


def _normalize_exec_mode(value: Any) -> str:
    normalized = str(getattr(value, "value", value) or "both").lower()
    if normalized not in {"local", "remote", "both"}:
        return "both"
    return normalized


def normalize_gateway_exec_mode(value: Any) -> str:
    return _normalize_exec_mode(value)


@dataclass
class GatewayCapabilitySchema:
    canonical_name: str
    device_id: str
    action: str
    params: Dict[str, Any] = field(default_factory=dict)
    returns: Dict[str, Any] = field(default_factory=dict)
    version: str = "1.0"
    exec_mode: str = "both"
    tags: List[str] = field(default_factory=list)
    registered_at: float = 0.0


def _record_to_schema(record: Any) -> Optional[GatewayCapabilitySchema]:
    source_kind = getattr(record, "source_kind", "")
    normalized_source_kind = getattr(source_kind, "value", source_kind)
    if record is None or normalized_source_kind != CapabilitySource.GATEWAY.value:
        return None

    metadata = dict(getattr(record, "metadata", {}) or {})
    device_id = getattr(record, "provider_id", "") or metadata.get("device_id", "")
    action = metadata.get("action") or getattr(record, "canonical_name", "").split("__")[-1]
    if not device_id or not action:
        return None

    return GatewayCapabilitySchema(
        canonical_name=str(getattr(record, "canonical_name", "") or getattr(record, "name", "")),
        device_id=str(device_id),
        action=str(action),
        params=dict(getattr(record, "parameters", {}) or {}),
        returns=dict(getattr(record, "returns", {}) or metadata.get("returns") or {}),
        version=str(getattr(record, "version", None) or metadata.get("contract_version") or "1.0"),
        exec_mode=_normalize_exec_mode(getattr(record, "exec_mode", None) or metadata.get("exec_mode")),
        tags=list(getattr(record, "tags", []) or metadata.get("contract_tags") or metadata.get("tags") or []),
        registered_at=float(getattr(record, "last_seen", 0.0) or metadata.get("registered_at") or time.time()),
    )


def query_gateway_capabilities(
    *,
    action: Optional[str] = None,
    exec_mode: Optional[Any] = None,
    device_id: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> List[GatewayCapabilitySchema]:
    desired_exec_mode = _normalize_exec_mode(exec_mode) if exec_mode is not None else None
    candidates = [
        schema
        for schema in (
            _record_to_schema(record)
            for record in get_capability_resolver().resolve_all_records(source=CapabilitySource.GATEWAY)
        )
        if schema is not None
    ]

    if device_id is not None:
        candidates = [schema for schema in candidates if schema.device_id == device_id]

    results: List[GatewayCapabilitySchema] = []
    for schema in candidates:
        if action is not None and schema.action != action:
            continue
        if desired_exec_mode is not None and desired_exec_mode != "both":
            if desired_exec_mode == "local" and schema.exec_mode == "remote":
                continue
            if desired_exec_mode == "remote" and schema.exec_mode == "local":
                continue
        if tags and not all(tag in schema.tags for tag in tags):
            continue
        results.append(schema)
    return results


def get_gateway_capabilities_for_device(device_id: str) -> List[GatewayCapabilitySchema]:
    return query_gateway_capabilities(device_id=device_id)


def list_gateway_capability_device_ids() -> List[str]:
    return sorted({schema.device_id for schema in query_gateway_capabilities()})


def purge_gateway_capabilities_for_device(device_id: str) -> int:
    removed = 0
    authority = CapabilityAuthority.get_instance()
    for record in get_capability_resolver().resolve_all_records(source=CapabilitySource.GATEWAY):
        metadata = dict(getattr(record, "metadata", {}) or {})
        if getattr(record, "provider_id", "") != device_id and metadata.get("device_id") != device_id:
            continue
        if authority.remove(record.canonical_name, mutation_source="gateway_capability_projection.purge"):
            removed += 1
    return removed


class GatewayCapabilityProjectionView:
    def query(
        self,
        action: Optional[str] = None,
        exec_mode: Optional[Any] = None,
        device_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> List[GatewayCapabilitySchema]:
        return query_gateway_capabilities(
            action=action,
            exec_mode=exec_mode,
            device_id=device_id,
            tags=tags,
        )

    def get_by_device(self, device_id: str) -> List[GatewayCapabilitySchema]:
        return get_gateway_capabilities_for_device(device_id)

    def all_device_ids(self) -> List[str]:
        return list_gateway_capability_device_ids()

    def purge(self, device_id: str) -> int:
        return purge_gateway_capabilities_for_device(device_id)


_gateway_capability_projection_view = GatewayCapabilityProjectionView()


def get_gateway_capability_projection_view() -> GatewayCapabilityProjectionView:
    return _gateway_capability_projection_view
