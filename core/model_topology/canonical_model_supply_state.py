"""
core/model_topology/canonical_model_supply_state.py
=====================================================
Canonical Model Supply State and Native Multimodal Capability Registry.

**Unified-Control Architecture — Model Supply Truth for OpenClawd**
--------------------------------------------------------------------
``CanonicalModelSupplyState`` is the single canonical object representing the
available model universe for the control core (:class:`~core.openclawd.OpenClawd`).

``NativeMultimodalCapabilityRegistry`` is the first-class registry of per-provider
and per-model native multimodal capabilities, making multimodal support an
explicit canonical contract rather than a scattered flag.

Architecture
------------

.. code-block:: text

    ProviderInventory  ──┐
                         ├──▶  build_canonical_model_supply_state()
    TopologyRoutePlan  ──┘              │
                                        ▼
                             CanonicalModelSupplyState
                               ├── NativeMultimodalCapabilityRegistry
                               ├── ProviderSupplyRecord[]  (available/unavailable)
                               ├── fallback_candidates[]
                               ├── support_model_candidates[]
                               └── to_dict()  ← serialisable / loggable

    MultiLLMRouter  ──▶  build_canonical_model_supply_state_from_router()
                              │
                              ▼
                         CanonicalModelSupplyState  (normalised from router state)

Design goals
------------
- Act as the **single source of truth** for model/provider supply that
  OpenClawd can consume for routing decisions.
- Preserve OpenClawd as the decision authority; this module provides stable
  supply input, not the selection logic.
- Make native multimodal capability a first-class, canonical concept with a
  clear per-modality matrix.
- Normalise capability information that already exists in ``ProviderConfig``
  (``multimodal`` flag) and ``NormalizedTopologyEntry`` (``ModalityCapability``)
  into one unified canonical representation.
- Remain fully serialisable for diagnostics, logging, testing, and desktop
  status projection.
- Be backward compatible: existing router functionality is unaffected.

Usage::

    from core.model_topology import (
        build_canonical_model_supply_state,
        CanonicalModelSupplyState,
        NativeMultimodalCapabilityRegistry,
    )

    # From topology inventory (primary path)
    state = build_canonical_model_supply_state(inventory)
    print(state.to_dict())

    # From MultiLLMRouter (bridge path for existing routing stack)
    from core.model_topology import build_canonical_model_supply_state_from_router
    state = build_canonical_model_supply_state_from_router(router)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.ModelTopology.CanonicalModelSupplyState")


# ---------------------------------------------------------------------------
# NativeMultimodalCapability — per-provider/model modality contract
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NativeMultimodalCapability:
    """First-class canonical capability record for one provider/model slot.

    This is the authoritative representation of native multimodal support.
    Downstream control logic (OpenClawd) should prefer models whose
    ``is_natively_multimodal`` flag is ``True`` when perception state includes
    images, audio, or video frames.

    Attributes
    ----------
    provider_id:
        Canonical provider identifier (e.g. ``"openai"``, ``"anthropic"``).
    model_id:
        Canonical model identifier within the provider.
    is_natively_multimodal:
        ``True`` when the provider/model can consume raw image, audio, or
        video inputs directly via its API without pre-summarisation.
    supports_image_input:
        ``True`` when image payloads (base64 / URL) can be passed natively.
    supports_audio_input:
        ``True`` when audio payloads can be consumed natively.
    supports_video_frame_input:
        ``True`` when video frame sequences / visual streams are supported.
    supports_streaming:
        ``True`` when the provider supports streaming token output.
    supports_tool_use:
        ``True`` when the provider supports tool/function-call semantics.
    extra_modalities:
        Any additional modality labels not covered by the above flags
        (e.g. ``"screen"``, ``"sensor"``).
    notes:
        Human-readable annotation (e.g. source of the capability claim).
    """

    provider_id: str
    model_id: str

    # Multimodal capability matrix
    is_natively_multimodal: bool = False
    supports_image_input: bool = False
    supports_audio_input: bool = False
    supports_video_frame_input: bool = False

    # API feature flags
    supports_streaming: bool = True
    supports_tool_use: bool = True

    # Forward-compatibility
    extra_modalities: tuple = field(default_factory=tuple)
    notes: str = ""

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    @property
    def active_modalities(self) -> List[str]:
        """Ordered list of modality labels that are active."""
        result: List[str] = []
        if self.supports_image_input:
            result.append("image")
        if self.supports_audio_input:
            result.append("audio")
        if self.supports_video_frame_input:
            result.append("video_frame")
        result.extend(self.extra_modalities)
        return result

    def to_dict(self) -> dict:
        return {
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "is_natively_multimodal": self.is_natively_multimodal,
            "supports_image_input": self.supports_image_input,
            "supports_audio_input": self.supports_audio_input,
            "supports_video_frame_input": self.supports_video_frame_input,
            "supports_streaming": self.supports_streaming,
            "supports_tool_use": self.supports_tool_use,
            "active_modalities": self.active_modalities,
            "extra_modalities": list(self.extra_modalities),
            "notes": self.notes,
        }

    @classmethod
    def from_multimodal_flag(
        cls,
        provider_id: str,
        model_id: str,
        multimodal: bool,
        supports_tools: bool = True,
        notes: str = "",
    ) -> "NativeMultimodalCapability":
        """Construct from the simple ``multimodal`` boolean used in the
        existing ``ProviderConfig`` / ``ModalityCapability`` definitions.

        When ``multimodal=True``, vision (image input) is implied.  Audio and
        video frame support default to ``False`` to avoid over-claiming.
        """
        return cls(
            provider_id=provider_id,
            model_id=model_id,
            is_natively_multimodal=multimodal,
            supports_image_input=multimodal,
            supports_audio_input=False,
            supports_video_frame_input=False,
            supports_tool_use=supports_tools,
            notes=notes,
        )

    @classmethod
    def from_modality_capability(
        cls,
        provider_id: str,
        model_id: str,
        modality: Any,  # ModalityCapability
        supports_tools: bool = True,
        notes: str = "",
    ) -> "NativeMultimodalCapability":
        """Construct from a ``ModalityCapability`` instance from the topology
        type system, preserving the per-modality detail already encoded there.
        """
        return cls(
            provider_id=provider_id,
            model_id=model_id,
            is_natively_multimodal=getattr(modality, "native_multimodal", False),
            supports_image_input=getattr(modality, "supports_vision", False),
            supports_audio_input=getattr(modality, "supports_audio", False),
            supports_video_frame_input=getattr(modality, "supports_video", False),
            supports_tool_use=supports_tools,
            notes=notes,
        )

    def __repr__(self) -> str:
        flags = []
        if self.is_natively_multimodal:
            flags.append("MM")
        if self.supports_image_input:
            flags.append("img")
        if self.supports_audio_input:
            flags.append("aud")
        if self.supports_video_frame_input:
            flags.append("vid")
        flag_str = "+".join(flags) if flags else "text-only"
        return f"<NativeMultimodalCapability {self.provider_id}/{self.model_id} [{flag_str}]>"


# ---------------------------------------------------------------------------
# NativeMultimodalCapabilityRegistry
# ---------------------------------------------------------------------------


class NativeMultimodalCapabilityRegistry:
    """Registry of native multimodal capabilities, keyed by provider_id.

    This is the authoritative first-class registry that answers:
    - which providers/models are natively multimodal
    - which specific modalities each supports
    - which provider/model should be preferred when multimodal perception is present

    The registry is additive: ``register()`` / ``register_many()`` can be
    called incrementally (e.g. as providers are discovered at runtime).

    Usage::

        registry = NativeMultimodalCapabilityRegistry()
        registry.register(NativeMultimodalCapability(
            provider_id="openai",
            model_id="gpt-4o",
            is_natively_multimodal=True,
            supports_image_input=True,
        ))

        mm_providers = registry.natively_multimodal_providers()
        vision_providers = registry.providers_supporting_modality("image")
    """

    def __init__(self) -> None:
        # Keyed by provider_id; last write wins for a given provider_id
        self._records: Dict[str, NativeMultimodalCapability] = {}

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def register(self, capability: NativeMultimodalCapability) -> None:
        """Register (or overwrite) a capability record for a provider."""
        if not capability.provider_id:
            raise ValueError("NativeMultimodalCapability.provider_id must not be empty")
        if capability.provider_id in self._records:
            logger.debug(
                "NativeMultimodalCapabilityRegistry: overwriting record for '%s'",
                capability.provider_id,
            )
        self._records[capability.provider_id] = capability
        logger.debug(
            "NativeMultimodalCapabilityRegistry: registered %r", capability
        )

    def register_many(self, capabilities: List[NativeMultimodalCapability]) -> None:
        """Register multiple capability records."""
        for cap in capabilities:
            self.register(cap)

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get(self, provider_id: str) -> Optional[NativeMultimodalCapability]:
        """Return the capability record for a provider, or ``None``."""
        return self._records.get(provider_id)

    def all_records(self) -> List[NativeMultimodalCapability]:
        """All registered capability records."""
        return list(self._records.values())

    def natively_multimodal_providers(self) -> List[NativeMultimodalCapability]:
        """Records for providers that are natively multimodal."""
        return [r for r in self._records.values() if r.is_natively_multimodal]

    def providers_supporting_modality(self, modality: str) -> List[NativeMultimodalCapability]:
        """Records for providers supporting a specific modality label.

        ``modality`` can be one of: ``"image"``, ``"audio"``, ``"video_frame"``,
        or any extra modality label registered.
        """
        result: List[NativeMultimodalCapability] = []
        for record in self._records.values():
            if modality in record.active_modalities:
                result.append(record)
        return result

    def preferred_multimodal_provider(
        self,
        required_modalities: Optional[List[str]] = None,
    ) -> Optional[NativeMultimodalCapability]:
        """Return the best candidate when multimodal perception is present.

        Selection preference (in order):
        1. Natively multimodal with all required modalities covered.
        2. Natively multimodal (any).
        3. ``None`` when no natively multimodal provider is available.

        When ``required_modalities`` is ``None`` or empty, any natively
        multimodal provider is accepted.
        """
        required = list(required_modalities or [])

        candidates = self.natively_multimodal_providers()
        if not candidates:
            return None

        if required:
            full_match = [
                c for c in candidates
                if all(m in c.active_modalities for m in required)
            ]
            if full_match:
                return full_match[0]

        return candidates[0]

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "records": {
                pid: cap.to_dict() for pid, cap in self._records.items()
            },
            "stats": {
                "total": len(self._records),
                "natively_multimodal": len(self.natively_multimodal_providers()),
                "image_capable": len(self.providers_supporting_modality("image")),
                "audio_capable": len(self.providers_supporting_modality("audio")),
                "video_frame_capable": len(self.providers_supporting_modality("video_frame")),
            },
        }

    # ------------------------------------------------------------------
    # Container protocol
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._records)

    def __contains__(self, provider_id: str) -> bool:
        return provider_id in self._records

    def __repr__(self) -> str:
        mm_count = len(self.natively_multimodal_providers())
        return (
            f"<NativeMultimodalCapabilityRegistry total={len(self)} "
            f"multimodal={mm_count}>"
        )


# ---------------------------------------------------------------------------
# ProviderSupplyRecord — per-provider slot in the canonical supply state
# ---------------------------------------------------------------------------


class ProviderHealthStatus(str, Enum):
    """Health/availability status of a provider in the canonical supply state."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"
    UNKNOWN = "unknown"


class ProviderLocalityClass(str, Enum):
    """Local vs cloud classification."""
    LOCAL = "local"
    CLOUD = "cloud"
    HYBRID = "hybrid"
    UNKNOWN = "unknown"


@dataclass
class ProviderSupplyRecord:
    """A single provider's supply record in the canonical model supply state.

    Combines identity, availability, capability, and routing hints into one
    stable canonical struct that OpenClawd can interrogate without further
    normalisation.

    Attributes
    ----------
    provider_id:
        Canonical provider identifier.
    models:
        List of model IDs available from this provider.
    default_model:
        The provider's default/preferred model.
    health_status:
        Current health classification.
    locality_class:
        Local vs cloud classification.
    capability:
        Native multimodal capability contract for this provider.
    topology_role_hints:
        Supply-role hints from the topology layer (e.g. ``"multimodal_core"``).
    cost_per_1k_input:
        Approximate cost per 1 k input tokens (0.0 when unknown).
    cost_per_1k_output:
        Approximate cost per 1 k output tokens (0.0 when unknown).
    latency_avg_ms:
        Average observed latency in ms (0.0 when unknown / unmeasured).
    is_fallback_candidate:
        ``True`` when this provider is a viable fallback for a degraded primary.
    is_support_model_candidate:
        ``True`` when this provider is suitable for support / auxiliary tasks.
    is_available:
        ``True`` when the provider's API key is present and status is not DOWN.
    raw_metadata:
        Pass-through of any upstream metadata for forward-compatibility.
    """

    provider_id: str
    models: List[str] = field(default_factory=list)
    default_model: str = ""
    health_status: ProviderHealthStatus = ProviderHealthStatus.UNKNOWN
    locality_class: ProviderLocalityClass = ProviderLocalityClass.UNKNOWN
    capability: Optional[NativeMultimodalCapability] = None
    topology_role_hints: List[str] = field(default_factory=list)
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0
    latency_avg_ms: float = 0.0
    is_fallback_candidate: bool = False
    is_support_model_candidate: bool = False
    is_available: bool = False
    raw_metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "provider_id": self.provider_id,
            "models": self.models,
            "default_model": self.default_model,
            "health_status": self.health_status.value,
            "locality_class": self.locality_class.value,
            "capability": self.capability.to_dict() if self.capability else None,
            "topology_role_hints": list(self.topology_role_hints),
            "cost_per_1k_input": self.cost_per_1k_input,
            "cost_per_1k_output": self.cost_per_1k_output,
            "latency_avg_ms": self.latency_avg_ms,
            "is_fallback_candidate": self.is_fallback_candidate,
            "is_support_model_candidate": self.is_support_model_candidate,
            "is_available": self.is_available,
        }

    def __repr__(self) -> str:
        avail = "✓" if self.is_available else "✗"
        mm = "MM" if (self.capability and self.capability.is_natively_multimodal) else "--"
        return (
            f"<ProviderSupplyRecord {self.provider_id} "
            f"{avail} {mm} {self.health_status.value} {self.locality_class.value}>"
        )


# ---------------------------------------------------------------------------
# CanonicalModelSupplyState
# ---------------------------------------------------------------------------


@dataclass
class CanonicalModelSupplyState:
    """Canonical, serialisable model supply state for the control core.

    This is the single source of truth for model/provider supply that
    :class:`~core.openclawd.OpenClawd` can consume for routing decisions.

    OpenClawd remains the decision authority; this object provides the stable
    supply input contract from which decisions are derived.

    Attributes
    ----------
    snapshot_id:
        Optional correlation ID for the snapshot (for diagnostics / logging).
    providers:
        Mapping of provider_id → ``ProviderSupplyRecord``.
    multimodal_registry:
        First-class registry of native multimodal capabilities.
    primary_provider_id:
        Provider recommended as the primary choice (may be ``None`` when no
        providers are available).
    fallback_candidates:
        Ordered list of provider_ids that are viable fallback options.
    support_model_candidates:
        Ordered list of provider_ids suitable for support / auxiliary tasks.
    natively_multimodal_provider_ids:
        Ordered list of provider_ids that are natively multimodal.
    available_provider_ids:
        Ordered list of provider_ids that are currently available (API key
        present, status not DOWN).
    unavailable_provider_ids:
        Ordered list of provider_ids that are NOT currently available.
    topology_route_reason:
        Human-readable explanation from the topology router, if available.
    supply_summary:
        Concise single-line summary for diagnostics and desktop projection.
    """

    snapshot_id: Optional[str] = None

    # Provider records
    providers: Dict[str, ProviderSupplyRecord] = field(default_factory=dict)

    # Native multimodal capability registry
    multimodal_registry: NativeMultimodalCapabilityRegistry = field(
        default_factory=NativeMultimodalCapabilityRegistry
    )

    # Derived routing hints (populated by builder)
    primary_provider_id: Optional[str] = None
    fallback_candidates: List[str] = field(default_factory=list)
    support_model_candidates: List[str] = field(default_factory=list)
    natively_multimodal_provider_ids: List[str] = field(default_factory=list)
    available_provider_ids: List[str] = field(default_factory=list)
    unavailable_provider_ids: List[str] = field(default_factory=list)

    # Explanation / diagnostics
    topology_route_reason: str = ""
    supply_summary: str = ""

    # ------------------------------------------------------------------
    # Convenience queries
    # ------------------------------------------------------------------

    def get_provider(self, provider_id: str) -> Optional[ProviderSupplyRecord]:
        """Return the supply record for a provider, or ``None``."""
        return self.providers.get(provider_id)

    def available_providers(self) -> List[ProviderSupplyRecord]:
        """Supply records for currently available providers."""
        return [r for r in self.providers.values() if r.is_available]

    def natively_multimodal_providers(self) -> List[ProviderSupplyRecord]:
        """Supply records for providers that are natively multimodal."""
        return [
            r for r in self.providers.values()
            if r.capability and r.capability.is_natively_multimodal
        ]

    def preferred_multimodal_provider_id(
        self, required_modalities: Optional[List[str]] = None
    ) -> Optional[str]:
        """Return the preferred provider_id for native multimodal routing.

        Delegates to the capability registry for modality matching, then
        verifies the returned provider is in the available set.
        """
        cap = self.multimodal_registry.preferred_multimodal_provider(required_modalities)
        if cap and cap.provider_id in self.available_provider_ids:
            return cap.provider_id
        # Fall back to any available natively multimodal provider
        for pid in self.natively_multimodal_provider_ids:
            if pid in self.available_provider_ids:
                return pid
        return None

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Serialise the full supply state to a plain dict.

        Safe to pass to ``json.dumps()``, log, or include in diagnostics /
        desktop status projection.
        """
        return {
            "snapshot_id": self.snapshot_id,
            "providers": {
                pid: record.to_dict() for pid, record in self.providers.items()
            },
            "multimodal_registry": self.multimodal_registry.to_dict(),
            "primary_provider_id": self.primary_provider_id,
            "fallback_candidates": list(self.fallback_candidates),
            "support_model_candidates": list(self.support_model_candidates),
            "natively_multimodal_provider_ids": list(self.natively_multimodal_provider_ids),
            "available_provider_ids": list(self.available_provider_ids),
            "unavailable_provider_ids": list(self.unavailable_provider_ids),
            "topology_route_reason": self.topology_route_reason,
            "supply_summary": self.supply_summary,
            "stats": {
                "total_providers": len(self.providers),
                "available": len(self.available_provider_ids),
                "unavailable": len(self.unavailable_provider_ids),
                "natively_multimodal": len(self.natively_multimodal_provider_ids),
                "fallback_candidates": len(self.fallback_candidates),
                "support_model_candidates": len(self.support_model_candidates),
            },
        }

    # ------------------------------------------------------------------
    # Container protocol
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self.providers)

    def __repr__(self) -> str:
        return (
            f"<CanonicalModelSupplyState "
            f"providers={len(self.providers)} "
            f"available={len(self.available_provider_ids)} "
            f"multimodal={len(self.natively_multimodal_provider_ids)} "
            f"primary={self.primary_provider_id!r}>"
        )


# ---------------------------------------------------------------------------
# Builder — from ProviderInventory (primary topology path)
# ---------------------------------------------------------------------------


def build_canonical_model_supply_state(
    inventory: Any,  # ProviderInventory
    snapshot_id: Optional[str] = None,
    topology_route_plan: Optional[Any] = None,  # TopologyRoutePlan
) -> CanonicalModelSupplyState:
    """Build a ``CanonicalModelSupplyState`` from a ``ProviderInventory``.

    This is the primary builder path, consuming the existing topology layer's
    normalised provider/model supply.  It does not modify the inventory or
    any existing routing logic.

    Parameters
    ----------
    inventory:
        A :class:`~core.model_topology.provider_inventory.ProviderInventory`
        instance, as produced by :class:`~core.model_topology.config_bridge.ConfigBridge`.
    snapshot_id:
        Optional correlation identifier for the produced snapshot.
    topology_route_plan:
        Optional :class:`~core.model_topology.topology_router.TopologyRoutePlan`
        to enrich the supply state with primary/support hints and route reason.

    Returns
    -------
    CanonicalModelSupplyState
    """
    state = CanonicalModelSupplyState(snapshot_id=snapshot_id)
    registry = state.multimodal_registry

    available_ids: List[str] = []
    unavailable_ids: List[str] = []
    mm_ids: List[str] = []

    # ------------------------------------------------------------------
    # Normalise each inventory entry into a ProviderSupplyRecord
    # ------------------------------------------------------------------
    for inv_entry in inventory:
        entry = inv_entry.entry

        # Capability record (normalised from ModalityCapability)
        cap = NativeMultimodalCapability.from_modality_capability(
            provider_id=entry.provider.provider_id,
            model_id=entry.model.model_id,
            modality=entry.modality,
            supports_tools=True,  # conservative default; override if known
            notes=f"normalized_from_topology_entry:{entry.category.value}",
        )
        registry.register(cap)

        # Locality classification
        from .topology_types import ProviderCategory
        _locality_map = {
            ProviderCategory.LOCAL: ProviderLocalityClass.LOCAL,
            ProviderCategory.ONEAPI: ProviderLocalityClass.CLOUD,
            ProviderCategory.DIRECT: ProviderLocalityClass.CLOUD,
            ProviderCategory.REMOTE: ProviderLocalityClass.CLOUD,
            ProviderCategory.NODE_BACKED: ProviderLocalityClass.HYBRID,
        }
        locality = _locality_map.get(entry.category, ProviderLocalityClass.UNKNOWN)

        # Health status
        _health_map = {
            "healthy": ProviderHealthStatus.HEALTHY,
            "degraded": ProviderHealthStatus.DEGRADED,
            "down": ProviderHealthStatus.DOWN,
        }
        health = _health_map.get(inv_entry.health_status, ProviderHealthStatus.UNKNOWN)

        # Role hints from topology
        role_hints = [r.value for r in entry.role_hints]

        pid = entry.provider.provider_id
        is_available = entry.is_available

        record = ProviderSupplyRecord(
            provider_id=pid,
            models=list(entry.model.alternatives) if entry.model.alternatives else [entry.model.model_id],
            default_model=entry.model.model_id,
            health_status=health,
            locality_class=locality,
            capability=cap,
            topology_role_hints=role_hints,
            latency_avg_ms=inv_entry.latency_avg_ms,
            is_available=is_available,
            raw_metadata=dict(entry.raw_metadata),
        )
        state.providers[pid] = record

        if is_available:
            available_ids.append(pid)
        else:
            unavailable_ids.append(pid)

        if cap.is_natively_multimodal:
            mm_ids.append(pid)

    state.available_provider_ids = available_ids
    state.unavailable_provider_ids = unavailable_ids
    state.natively_multimodal_provider_ids = mm_ids

    # ------------------------------------------------------------------
    # Enrichment from TopologyRoutePlan (if supplied)
    # ------------------------------------------------------------------
    if topology_route_plan is not None:
        primary = getattr(topology_route_plan, "primary_model", None)
        if primary is not None:
            state.primary_provider_id = primary.provider.provider_id
        support = getattr(topology_route_plan, "support_models", [])
        state.support_model_candidates = [
            n.provider.provider_id for n in support
        ]
        state.topology_route_reason = getattr(
            topology_route_plan, "route_reason", ""
        )
    elif available_ids:
        # No topology plan: prefer first available natively multimodal provider,
        # then first available provider.
        state.primary_provider_id = (
            mm_ids[0] if mm_ids and mm_ids[0] in available_ids
            else available_ids[0]
        )

    # ------------------------------------------------------------------
    # Fallback candidates
    # ------------------------------------------------------------------
    # All available providers except the primary are fallback candidates.
    fallback: List[str] = [
        pid for pid in available_ids
        if pid != state.primary_provider_id
    ]
    state.fallback_candidates = fallback

    # ------------------------------------------------------------------
    # Support model candidates (from topology plan or available non-primary)
    # ------------------------------------------------------------------
    if not state.support_model_candidates:
        state.support_model_candidates = fallback[:3]

    # Propagate to individual records
    for pid in state.fallback_candidates:
        if pid in state.providers:
            state.providers[pid].is_fallback_candidate = True
    for pid in state.support_model_candidates:
        if pid in state.providers:
            state.providers[pid].is_support_model_candidate = True

    # ------------------------------------------------------------------
    # Supply summary
    # ------------------------------------------------------------------
    state.supply_summary = _build_supply_summary(state)

    logger.info("build_canonical_model_supply_state: %r", state)
    return state


# ---------------------------------------------------------------------------
# Builder — from MultiLLMRouter (bridge path for existing routing stack)
# ---------------------------------------------------------------------------


def build_canonical_model_supply_state_from_router(
    router: Any,  # MultiLLMRouter
    snapshot_id: Optional[str] = None,
) -> CanonicalModelSupplyState:
    """Build a ``CanonicalModelSupplyState`` from a :class:`~core.multi_llm_router.MultiLLMRouter`.

    This is the bridge builder for the existing routing stack.  It normalises
    ``ProviderConfig`` objects (with their ``multimodal`` flag) into the same
    canonical contract produced by ``build_canonical_model_supply_state()``.

    The existing router functionality is unchanged; this is purely a read/
    normalisation path.

    Parameters
    ----------
    router:
        A :class:`~core.multi_llm_router.MultiLLMRouter` instance.
    snapshot_id:
        Optional correlation identifier for the produced snapshot.

    Returns
    -------
    CanonicalModelSupplyState
    """
    state = CanonicalModelSupplyState(snapshot_id=snapshot_id)
    registry = state.multimodal_registry

    available_ids: List[str] = []
    unavailable_ids: List[str] = []
    mm_ids: List[str] = []

    providers_dict = getattr(router, "providers", {})

    for pid, prov_config in providers_dict.items():
        # Normalise the simple boolean multimodal flag
        multimodal = getattr(prov_config, "multimodal", False)
        supports_tools = getattr(prov_config, "supports_tools", True)

        cap = NativeMultimodalCapability.from_multimodal_flag(
            provider_id=pid,
            model_id=getattr(prov_config, "default_model", ""),
            multimodal=multimodal,
            supports_tools=supports_tools,
            notes="normalized_from_multi_llm_router",
        )
        registry.register(cap)

        # Status normalisation
        from enum import Enum as _Enum
        status_raw = getattr(prov_config, "status", None)
        status_val = (
            status_raw.value if isinstance(status_raw, _Enum) else str(status_raw or "unknown")
        )
        _health_map = {
            "healthy": ProviderHealthStatus.HEALTHY,
            "degraded": ProviderHealthStatus.DEGRADED,
            "down": ProviderHealthStatus.DOWN,
        }
        health = _health_map.get(status_val, ProviderHealthStatus.UNKNOWN)
        is_available = health != ProviderHealthStatus.DOWN

        record = ProviderSupplyRecord(
            provider_id=pid,
            models=list(getattr(prov_config, "models", [])),
            default_model=getattr(prov_config, "default_model", ""),
            health_status=health,
            locality_class=ProviderLocalityClass.UNKNOWN,
            capability=cap,
            cost_per_1k_input=getattr(prov_config, "cost_per_1k_input", 0.0),
            cost_per_1k_output=getattr(prov_config, "cost_per_1k_output", 0.0),
            latency_avg_ms=getattr(prov_config, "latency_avg_ms", 0.0),
            is_available=is_available,
        )
        state.providers[pid] = record

        if is_available:
            available_ids.append(pid)
        else:
            unavailable_ids.append(pid)

        if multimodal:
            mm_ids.append(pid)

    state.available_provider_ids = available_ids
    state.unavailable_provider_ids = unavailable_ids
    state.natively_multimodal_provider_ids = mm_ids

    # Primary: prefer first available natively multimodal, else first available
    if available_ids:
        state.primary_provider_id = (
            mm_ids[0] if mm_ids and mm_ids[0] in available_ids
            else available_ids[0]
        )

    # Fallback candidates
    fallback = [pid for pid in available_ids if pid != state.primary_provider_id]
    state.fallback_candidates = fallback

    # Support model candidates
    state.support_model_candidates = fallback[:3]

    # Propagate
    for pid in state.fallback_candidates:
        if pid in state.providers:
            state.providers[pid].is_fallback_candidate = True
    for pid in state.support_model_candidates:
        if pid in state.providers:
            state.providers[pid].is_support_model_candidate = True

    state.supply_summary = _build_supply_summary(state)

    logger.info("build_canonical_model_supply_state_from_router: %r", state)
    return state


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_supply_summary(state: CanonicalModelSupplyState) -> str:
    """Build a concise single-line supply summary for diagnostics."""
    n_avail = len(state.available_provider_ids)
    n_total = len(state.providers)
    n_mm = len(state.natively_multimodal_provider_ids)
    parts: List[str] = []

    if n_total == 0:
        return "supply:empty"

    parts.append(f"avail={n_avail}/{n_total}")
    if n_mm:
        parts.append(f"multimodal={n_mm}")
    if state.primary_provider_id:
        parts.append(f"primary={state.primary_provider_id!r}")
    if state.fallback_candidates:
        parts.append(f"fallback={len(state.fallback_candidates)}")

    return "supply:" + " ".join(parts)
