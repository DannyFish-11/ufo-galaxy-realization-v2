"""
core/device_node_resolver.py
============================
PR-DEVICE-RESOLUTION: Device-to-Node Resolver

Reads ``registry/device_node_map.yaml`` and resolves a device description
to its canonical Node implementation via three match paths (in priority):

1. **device_type** — exact ``AIPDeviceType`` match
2. **transport**   — transport protocol match (ble, mqtt, serial, etc.)
3. **capabilities** — capability set match (fallback)

This is the anti-corruption layer between AIP v3 protocol semantics and
the concrete Node implementations.  No existing Node code is imported here;
only the YAML mapping is consulted.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

try:
    import yaml
except ImportError:
    yaml = None  # pragma: no cover

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sentinel
# ---------------------------------------------------------------------------
DEVICE_NODE_RESOLUTION_SENTINEL = (
    "DEVICE_NODE_RESOLUTION::AIP_TO_NODE_ANTI_CORRUPTION_LAYER"
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class NodeImplementation:
    """Concrete Node that implements a device pattern."""

    node: str
    transport: str
    port: int
    startup: str  # always_on | on_demand | lazy | shared
    healthcheck: str
    note: str = ""


@dataclass(frozen=True)
class CapabilityProfile:
    """Capabilities provided and required by a Node."""

    provides: List[str] = field(default_factory=list)
    requires: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class ResolvedMapping:
    """Result of resolving a device to its Node implementation."""

    match_type: str  # device_type | transport | capabilities
    match_key: str
    implementation: NodeImplementation
    capabilities: CapabilityProfile


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------
class DeviceNodeResolver:
    """Resolve AIP device descriptions to Node implementations.

    Usage::

        resolver = DeviceNodeResolver()
        result = resolver.resolve(device_type="android_phone")
        # ResolvedMapping(match_type="device_type", ...)
    """

    _DEFAULT_MAP_PATH = Path(__file__).parent.parent / "registry" / "device_node_map.yaml"

    def __init__(self, map_path: Optional[os.PathLike] = None) -> None:
        self._map_path = Path(map_path) if map_path else self._DEFAULT_MAP_PATH
        self._mappings: List[Dict[str, Any]] = []
        self._loaded = False

    # -- public API ----------------------------------------------------------

    def resolve(
        self,
        *,
        device_type: Optional[str] = None,
        transport: Optional[str] = None,
        capabilities: Optional[Sequence[str]] = None,
    ) -> Optional[ResolvedMapping]:
        """Resolve a device description to its Node implementation.

        Priority:
            1. device_type exact match
            2. transport match
            3. capabilities subset match

        Returns ``None`` if no mapping matches.
        """
        self._ensure_loaded()

        # 1. device_type exact match
        if device_type:
            result = self._resolve_by_device_type(device_type, transport)
            if result:
                return result

        # 2. transport match
        if transport:
            result = self._resolve_by_transport(transport)
            if result:
                return result

        # 3. capabilities subset match
        if capabilities:
            result = self._resolve_by_capabilities(list(capabilities))
            if result:
                return result

        logger.debug(
            "DeviceNodeResolver: no mapping for device_type=%s transport=%s caps=%s",
            device_type, transport, capabilities,
        )
        return None

    def resolve_all(
        self,
        *,
        device_type: Optional[str] = None,
        transport: Optional[str] = None,
        capabilities: Optional[Sequence[str]] = None,
    ) -> List[ResolvedMapping]:
        """Return ALL matching mappings (for capability-aggregation scenarios).

        Example: a device may need both ``COMM_BLUETOOTH`` (BLE node)
        and ``SENSOR_CAMERA`` (Camera node); this returns both.
        """
        self._ensure_loaded()
        results: List[ResolvedMapping] = []

        if device_type:
            r = self._resolve_by_device_type(device_type, transport)
            if r:
                results.append(r)

        if transport:
            r = self._resolve_by_transport(transport)
            if r and r not in results:
                results.append(r)

        if capabilities:
            r = self._resolve_by_capabilities(list(capabilities))
            if r and r not in results:
                results.append(r)

        return results

    def list_supported_device_types(self) -> List[str]:
        """Return all device types that have explicit mappings."""
        self._ensure_loaded()
        types: set = set()
        for m in self._mappings:
            dt = m.get("match", {}).get("device_type")
            if dt:
                types.add(dt)
        return sorted(types)

    def list_supported_transports(self) -> List[str]:
        """Return all transports that have explicit mappings."""
        self._ensure_loaded()
        transports: set = set()
        for m in self._mappings:
            t = m.get("match", {}).get("transport")
            if t:
                transports.add(t)
            # Also from implementation
            impl = m.get("implementation", {})
            if impl.get("transport"):
                transports.add(impl["transport"])
        return sorted(transports)

    # -- internal ------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self._load()
            self._loaded = True

    def _load(self) -> None:
        if not self._map_path.exists():
            logger.warning("Device node map not found: %s", self._map_path)
            return

        if yaml is None:
            logger.error("PyYAML is required for device_node_map.yaml")
            return

        try:
            data = yaml.safe_load(self._map_path.read_text(encoding="utf-8"))
            self._mappings = data.get("mappings", [])
            logger.info(
                "Loaded %d device-node mappings from %s",
                len(self._mappings), self._map_path,
            )
        except Exception as exc:
            logger.error("Failed to load device node map: %s", exc)

    def _resolve_by_device_type(
        self, device_type: str, transport: Optional[str] = None
    ) -> Optional[ResolvedMapping]:
        for m in self._mappings:
            match = m.get("match", {})
            if match.get("device_type") != device_type:
                continue
            # If transport also specified in match, check it
            if transport and match.get("transport"):
                if match["transport"] != transport:
                    continue
            return self._build_result(m, "device_type", device_type)
        return None

    def _resolve_by_transport(self, transport: str) -> Optional[ResolvedMapping]:
        for m in self._mappings:
            match = m.get("match", {})
            # Only match if there's NO device_type constraint
            # (device_type matches take priority and are handled above)
            if match.get("device_type"):
                continue
            if match.get("transport") == transport:
                return self._build_result(m, "transport", transport)
        return None

    def _resolve_by_capabilities(
        self, capabilities: List[str]
    ) -> Optional[ResolvedMapping]:
        cap_set = set(capabilities)
        for m in self._mappings:
            match = m.get("match", {})
            # Only use capability matches that have NO device_type or transport
            if match.get("device_type") or match.get("transport"):
                continue
            required_caps = set(match.get("capabilities", []))
            if required_caps and required_caps.issubset(cap_set):
                return self._build_result(
                    m, "capabilities", ",".join(sorted(required_caps))
                )
        return None

    @staticmethod
    def _build_result(
        mapping: Dict[str, Any], match_type: str, match_key: str
    ) -> ResolvedMapping:
        impl = mapping.get("implementation", {})
        caps = mapping.get("capabilities", {})
        return ResolvedMapping(
            match_type=match_type,
            match_key=match_key,
            implementation=NodeImplementation(
                node=impl["node"],
                transport=impl["transport"],
                port=impl["port"],
                startup=impl["startup"],
                healthcheck=impl["healthcheck"],
                note=mapping.get("note", ""),
            ),
            capabilities=CapabilityProfile(
                provides=caps.get("provides", []),
                requires=caps.get("requires", []),
            ),
        )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
_resolver_instance: Optional[DeviceNodeResolver] = None


def get_resolver() -> DeviceNodeResolver:
    """Return the module-level DeviceNodeResolver singleton."""
    global _resolver_instance
    if _resolver_instance is None:
        _resolver_instance = DeviceNodeResolver()
    return _resolver_instance


def resolve(
    *,
    device_type: Optional[str] = None,
    transport: Optional[str] = None,
    capabilities: Optional[Sequence[str]] = None,
) -> Optional[ResolvedMapping]:
    """Convenience: resolve using the module singleton."""
    return get_resolver().resolve(
        device_type=device_type, transport=transport, capabilities=capabilities
    )
