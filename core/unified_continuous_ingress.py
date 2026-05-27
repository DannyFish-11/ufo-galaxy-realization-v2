"""core/unified_continuous_ingress.py — Unified Canonical Continuous Ingress Backbone

**Continuous Ingress Mainchain Unification**
---------------------------------------------
``UnifiedContinuousIngressModel`` is the single canonical structure that
collects *all* continuous-stream ingress families and promotes them into a
shared canonical ingress role so that downstream cognition/perception consumers
see a unified, family-aware continuous ingress truth rather than independent
transport-layer side paths.

Unified families
~~~~~~~~~~~~~~~~
Three ingress families are collected into a single structure:

1. **WebRTC stream ingress** — ``core.multimodal.WebRTCSessionManager``; was
   previously visible only as a transport-level session manager.  This module
   promotes it to ``canonical_cognition_ingress`` role.
2. **Android / device continuous stream** — continuous stream originated from
   an Android or remote device, detected from the desktop-native ingress
   backbone ``modalities.continuous_stream`` field or from Android cognition
   input signals.
3. **Desktop continuous perception session** — the ``MultimodalIngressBus``
   perception frame already flowing through the shell; surfaces here as an
   explicit named family so it can be compared and unified with the other two.

Consumer
~~~~~~~~
:meth:`~core.openclawd.OpenClawd._build_canonical_perception_state` consumes
the assembled model and merges each active family's canonical name into
``active_modalities``, sets ``multimodal_fusion_strategy`` (determined by the
number of active families), exposes ``planning_readiness``, and records
``cognition_promotion_evidence`` so callers can verify that at least one
transport-only path has been promoted.

Behavioral contract
~~~~~~~~~~~~~~~~~~~
The ``multimodal_fusion_strategy`` in canonical perception changes depending
on how many families are active:

* 0 active families → ``"discrete_request_bound"``
* 1 active family   → ``"single_stream_assisted_fusion"``
* 2+ active families → ``"continuous_multistream_cognition_fusion"``

This difference is machine-verifiable in tests and in the production canonical
perception dict without requiring a live stream connection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

UNIFIED_CONTINUOUS_INGRESS_AUTHORITY: str = (
    "UNIFIED_CONTINUOUS_INGRESS::CANONICAL_MULTISTREAM_COGNITION_BACKBONE_V1"
)
UNIFIED_CONTINUOUS_INGRESS_SENTINEL: str = (
    "UNIFIED_CONTINUOUS_INGRESS::FORMAL_MAINCHAIN_UNIFICATION_PASS_V1"
)

# ---------------------------------------------------------------------------
# Family identifiers — canonical names for each continuous ingress family
# ---------------------------------------------------------------------------

FAMILY_WEBRTC_STREAM: str = "webrtc_stream"
FAMILY_ANDROID_DEVICE_STREAM: str = "android_device_stream"
FAMILY_DESKTOP_PERCEPTION_SESSION: str = "desktop_perception_session"

# Families that were previously considered transport-only and are promoted here
# to canonical cognition role.
_TRANSPORT_PROMOTED_FAMILIES: frozenset = frozenset(
    {FAMILY_WEBRTC_STREAM, FAMILY_ANDROID_DEVICE_STREAM}
)

# Canonical cognition role string surfaced in promotion evidence
COGNITION_ROLE_CANONICAL_INGRESS: str = "canonical_cognition_ingress"

# ---------------------------------------------------------------------------
# fusion strategy constants (determine mainchain behavior)
# ---------------------------------------------------------------------------

FUSION_STRATEGY_DISCRETE: str = "discrete_request_bound"
FUSION_STRATEGY_SINGLE_STREAM: str = "single_stream_assisted_fusion"
FUSION_STRATEGY_MULTISTREAM: str = "continuous_multistream_cognition_fusion"

# ---------------------------------------------------------------------------
# Planning readiness constants
# ---------------------------------------------------------------------------

PLANNING_READINESS_NONE: str = "deferred"
PLANNING_READINESS_STREAM_ASSISTED: str = "stream_assisted"
PLANNING_READINESS_CONTINUOUS_MAINLINE: str = "continuous_mainline_ready"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ContinuousIngressEntry:
    """A single continuous ingress source from one ingress family.

    Attributes
    ----------
    family
        Canonical family identifier (one of the ``FAMILY_*`` constants).
    session_id
        Optional session/trace correlation ID for this stream.
    is_active
        ``True`` when the stream is currently providing live ingress.
    was_transport_promoted
        ``True`` when this entry was previously transport-only and has been
        promoted to canonical cognition ingress by this unification pass.
    cognition_role
        The canonical role string that downstream consumers should record.
    quality_hint
        Optional quality descriptor (e.g. ``"active"``, ``"degraded"``).
    """

    family: str
    session_id: Optional[str] = None
    is_active: bool = False
    was_transport_promoted: bool = False
    cognition_role: str = ""
    quality_hint: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "family": self.family,
            "session_id": self.session_id,
            "is_active": self.is_active,
            "was_transport_promoted": self.was_transport_promoted,
            "cognition_role": self.cognition_role,
            "quality_hint": self.quality_hint,
        }


@dataclass
class UnifiedContinuousIngressModel:
    """Canonical continuous ingress structure that unifies multiple stream families.

    Assembles entries from WebRTC stream, Android/device stream, and desktop
    continuous perception session into one structure so that downstream
    cognition/perception consumers have a single, authoritative continuous
    ingress truth.

    Attributes
    ----------
    entries
        All ingress entries regardless of active state.
    authority
        Authority sentinel for this model version.
    sentinel
        Formal convergence sentinel.
    """

    entries: List[ContinuousIngressEntry] = field(default_factory=list)
    authority: str = UNIFIED_CONTINUOUS_INGRESS_AUTHORITY
    sentinel: str = UNIFIED_CONTINUOUS_INGRESS_SENTINEL

    # ------------------------------------------------------------------
    # Computed properties (derived from entries; no stored state)
    # ------------------------------------------------------------------

    @property
    def active_entries(self) -> List[ContinuousIngressEntry]:
        """Entries where ``is_active`` is True."""
        return [e for e in self.entries if e.is_active]

    @property
    def active_families(self) -> List[str]:
        """Ordered list of family names that are currently active."""
        return [e.family for e in self.active_entries]

    @property
    def is_mainline_active(self) -> bool:
        """``True`` when at least one continuous ingress family is active."""
        return bool(self.active_entries)

    @property
    def active_family_count(self) -> int:
        return len(self.active_entries)

    @property
    def multimodal_fusion_strategy(self) -> str:
        """Fusion strategy keyed to number of active families.

        * 0 → ``"discrete_request_bound"``
        * 1 → ``"single_stream_assisted_fusion"``
        * 2+ → ``"continuous_multistream_cognition_fusion"``

        This field is the primary machine-verifiable behavioral signal that
        differentiates continuous-ingress-present from continuous-ingress-absent
        mainchain behavior.
        """
        n = self.active_family_count
        if n == 0:
            return FUSION_STRATEGY_DISCRETE
        if n == 1:
            return FUSION_STRATEGY_SINGLE_STREAM
        return FUSION_STRATEGY_MULTISTREAM

    @property
    def planning_readiness(self) -> str:
        """Planning readiness level based on active stream count.

        * 0 active → ``"deferred"``
        * 1 active → ``"stream_assisted"``
        * 2+ active → ``"continuous_mainline_ready"``
        """
        n = self.active_family_count
        if n == 0:
            return PLANNING_READINESS_NONE
        if n == 1:
            return PLANNING_READINESS_STREAM_ASSISTED
        return PLANNING_READINESS_CONTINUOUS_MAINLINE

    @property
    def cognition_promotion_evidence(self) -> List[Dict[str, Any]]:
        """Evidence records for families that were transport-only and are now
        promoted to canonical cognition ingress role.

        Each record contains the family name, cognition role, and whether the
        family is currently active — so callers can verify both the promotion
        and the current activity state.
        """
        return [
            {
                "family": e.family,
                "cognition_role": e.cognition_role,
                "is_active": e.is_active,
                "was_transport_promoted": e.was_transport_promoted,
            }
            for e in self.entries
            if e.was_transport_promoted
        ]

    def to_dict(self) -> Dict[str, Any]:
        """Serializable dict for embedding in canonical perception dicts."""
        return {
            "authority": self.authority,
            "sentinel": self.sentinel,
            "entries": [e.to_dict() for e in self.entries],
            "active_families": self.active_families,
            "is_mainline_active": self.is_mainline_active,
            "active_family_count": self.active_family_count,
            "multimodal_fusion_strategy": self.multimodal_fusion_strategy,
            "planning_readiness": self.planning_readiness,
            "cognition_promotion_evidence": self.cognition_promotion_evidence,
        }


# ---------------------------------------------------------------------------
# Assembly function
# ---------------------------------------------------------------------------


def assemble_unified_continuous_ingress(
    *,
    stream_runtime_status: Optional[Dict[str, Any]] = None,
    desktop_native_ingress_backbone: Optional[Dict[str, Any]] = None,
    desktop_perception_frame_available: bool = False,
) -> UnifiedContinuousIngressModel:
    """Assemble a :class:`UnifiedContinuousIngressModel` from available signals.

    This function is the canonical factory for the unified continuous ingress
    structure.  It reads from three independent signal sources — without
    introducing hard dependencies on them — and maps each to a
    :class:`ContinuousIngressEntry`.

    Parameters
    ----------
    stream_runtime_status:
        The dict produced by
        :func:`~core.realtime_streaming_backbone.build_realtime_stream_runtime_status`.
        Used to derive the WebRTC/desktop stream entry.
    desktop_native_ingress_backbone:
        The dict produced by
        :func:`~core.desktop_native_multimodal_ingress_contract.build_desktop_native_ingress_backbone`.
        Used to derive the Android/device continuous stream entry.
    desktop_perception_frame_available:
        ``True`` when the ``MultimodalIngressBus`` singleton has a live
        :class:`~core.multimodal.perception_frame.PerceptionFrame`.  Used for
        the desktop perception session entry.

    Returns
    -------
    UnifiedContinuousIngressModel
        A fully assembled model.  Empty entries are still included (with
        ``is_active=False``) so the model always contains all three family
        slots and the transport-promotion evidence is always present.
    """
    entries: List[ContinuousIngressEntry] = []

    # ------------------------------------------------------------------
    # 1. WebRTC stream ingress
    # Previously: transport-level session manager only.
    # Promoted here: canonical_cognition_ingress role.
    # ------------------------------------------------------------------
    _webrtc_active = False
    _webrtc_quality: Optional[str] = None
    _webrtc_session_id: Optional[str] = None
    if isinstance(stream_runtime_status, dict):
        _webrtc_active = bool(stream_runtime_status.get("stream_active_for_routing"))
        _webrtc_quality = str(stream_runtime_status.get("stream_state") or "")
        # Use the stream manager session ID when available
        _webrtc_session_id = stream_runtime_status.get("session_id") or None

    entries.append(
        ContinuousIngressEntry(
            family=FAMILY_WEBRTC_STREAM,
            session_id=_webrtc_session_id,
            is_active=_webrtc_active,
            was_transport_promoted=True,
            cognition_role=COGNITION_ROLE_CANONICAL_INGRESS,
            quality_hint=_webrtc_quality or None,
        )
    )

    # ------------------------------------------------------------------
    # 2. Android / device continuous stream
    # Previously: detected only in one-shot Android perception requests.
    # Promoted here: canonical_cognition_ingress role when detected as
    # continuous (via modalities.continuous_stream or android_cognition_input).
    # ------------------------------------------------------------------
    _android_stream_active = False
    _android_session_id: Optional[str] = None
    if isinstance(desktop_native_ingress_backbone, dict):
        _mods = (desktop_native_ingress_backbone.get("modalities") or {})
        _cont_stream_present = bool((_mods.get("continuous_stream") or {}).get("is_present"))
        _android_cognition = (desktop_native_ingress_backbone.get("android_cognition_input") or {})
        _android_originated = bool(
            isinstance(_android_cognition, dict)
            and _android_cognition.get("is_android_originated")
        )
        # Active when desktop backbone signals an Android-originated continuous stream
        _android_stream_active = _cont_stream_present and _android_originated
        if _android_stream_active:
            _android_session_id = (
                (desktop_native_ingress_backbone.get("control_session_id") or None)
                or (desktop_native_ingress_backbone.get("carrier_source") or None)
            )

    entries.append(
        ContinuousIngressEntry(
            family=FAMILY_ANDROID_DEVICE_STREAM,
            session_id=_android_session_id,
            is_active=_android_stream_active,
            was_transport_promoted=True,
            cognition_role=COGNITION_ROLE_CANONICAL_INGRESS,
            quality_hint="android_device_continuous" if _android_stream_active else None,
        )
    )

    # ------------------------------------------------------------------
    # 3. Desktop continuous perception session
    # Already flows through MultimodalIngressBus; included here to make the
    # unified structure account for all three families explicitly.
    # ------------------------------------------------------------------
    entries.append(
        ContinuousIngressEntry(
            family=FAMILY_DESKTOP_PERCEPTION_SESSION,
            session_id=None,
            is_active=desktop_perception_frame_available,
            was_transport_promoted=False,
            cognition_role=COGNITION_ROLE_CANONICAL_INGRESS if desktop_perception_frame_available else "",
            quality_hint="ingress_bus_frame" if desktop_perception_frame_available else None,
        )
    )

    return UnifiedContinuousIngressModel(entries=entries)
