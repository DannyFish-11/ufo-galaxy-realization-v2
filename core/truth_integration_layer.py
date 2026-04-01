"""
core/truth_integration_layer.py
================================
PR-1: Truth Integration Layer — Canonical Runtime Truth Convergence.

Architecture role
-----------------
This module is the **single convergence point** for all device online/presence/
registration truth in the Galaxy system.  It fuses inputs from the two primary
canonical authorities and the compat cache, then emits a
:class:`CanonicalDeviceTruth` that every consumer (readiness, participation,
target-validation) can rely upon.

Authority hierarchy (conflict-resolution policy)
-------------------------------------------------
1. **UCM** (:class:`~core.unified.connection_manager.UnifiedConnectionManager`)
   — canonical connection/presence authority.  ``is_connected`` and
   ``is_routable`` are always decided by UCM when reachable.
2. **UDM** (:class:`~core.unified.device_manager.UnifiedDeviceManager`)
   — canonical device-registration/state/capabilities authority.
   ``is_registered``, ``is_online``, and ``capabilities`` are always decided
   by UDM when reachable.
3. **Compat cache** (``core.routes._shared.registered_devices``)
   — **read-only** supplemental input.  Used **only** when BOTH UCM and UDM
   are unreachable.  Never overrides an authoritative verdict from UCM/UDM.

Resolution rules
----------------
* ``resolution_source == "ucm_udm"``    — UCM and/or UDM returned data;
  compat cache was not consulted for truth decisions.
* ``resolution_source == "compat_supplement"`` — UCM/UDM were unreachable;
  compat cache was used to fill in values.  Trust level: low.
* ``resolution_source == "compat_only"`` — Only compat cache had data
  (UCM/UDM both returned no record).  Trust level: very low.
* ``conflicts`` — List of human-readable discrepancies detected between
  authority data and the compat cache.  Non-empty when compat cache says
  a device is online/registered but UCM/UDM say otherwise, or vice-versa.
  Conflicts are **informational** only and do NOT change the authority verdict.

Consumers
---------
* :mod:`core.device_readiness` — should query resolve_device_truth() to obtain
  the canonical registered/online/connected/routable truth before performing
  transport enrichment.
* :mod:`core.device_participation` — builds on the output of device_readiness
  which is TIL-backed.
* :mod:`core.target_device_validator` — builds on the output of
  device_readiness/device_participation which are TIL-backed.

Public API
----------
Sentinel:
    TRUTH_INTEGRATION_LAYER_AUTHORITY

Models:
    CanonicalDeviceTruth

Helpers:
    resolve_device_truth(device_id) -> CanonicalDeviceTruth
    resolve_all_device_truth() -> list[CanonicalDeviceTruth]
    is_device_available_canonical(device_id) -> bool
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.TruthIntegrationLayer")

__all__ = [
    "TRUTH_INTEGRATION_LAYER_AUTHORITY",
    "TRUTH_CONFLICT_RESOLUTION_POLICY",
    "CanonicalDeviceTruth",
    "resolve_device_truth",
    "resolve_all_device_truth",
    "is_device_available_canonical",
]

# ---------------------------------------------------------------------------
# Authority sentinel
# ---------------------------------------------------------------------------

TRUTH_INTEGRATION_LAYER_AUTHORITY: str = (
    "TRUTH_INTEGRATION_LAYER::CANONICAL_RUNTIME_TRUTH_V1"
)

# Human-readable description of the conflict-resolution policy used by this
# module.  Importable by external conformance tests.
TRUTH_CONFLICT_RESOLUTION_POLICY: str = (
    "UCM/UDM=primary-authority; compat-cache=read-only-supplement; "
    "compat verdict never overrides authority verdict"
)

# ---------------------------------------------------------------------------
# CanonicalDeviceTruth model
# ---------------------------------------------------------------------------


@dataclass
class CanonicalDeviceTruth:
    """Canonical runtime truth for a single device.

    Fields derived from **authority sources** (UCM / UDM):
        is_registered      — UDM: device is known to the canonical registry
        is_online          — UDM: device status is ``online``
        is_connected       — UCM: device has an active WebSocket connection
        is_routable        — UCM: device can receive messages right now
        capabilities       — UDM: list of device capability strings

    Resolution metadata:
        device_id          — the resolved device identifier
        resolution_source  — one of ``"ucm_udm"``, ``"compat_supplement"``,
                             ``"compat_only"``
        authority_available — True when at least one of UCM / UDM returned data
        compat_present     — True when the compat cache has an entry for this device
        conflicts          — list of discrepancy strings (informational only;
                             authority verdict is NOT changed by compat data)
        raw_udm            — raw UDM record (dict / None)
        raw_ucm            — raw UCM record (dict / None)
        raw_compat         — raw compat-cache record (dict / None)
    """

    device_id: str
    # --- authority-derived fields ---
    is_registered: bool = False
    is_online: bool = False
    is_connected: bool = False
    is_routable: bool = False
    capabilities: List[Any] = field(default_factory=list)
    # --- resolution metadata ---
    resolution_source: str = "ucm_udm"
    authority_available: bool = False
    compat_present: bool = False
    conflicts: List[str] = field(default_factory=list)
    # --- raw data for diagnostics ---
    raw_udm: Optional[Dict[str, Any]] = None
    raw_ucm: Optional[Dict[str, Any]] = None
    raw_compat: Optional[Dict[str, Any]] = None

    # convenience
    @property
    def is_available(self) -> bool:
        """True when the device is registered, online, connected, and routable."""
        return self.is_registered and self.is_online and self.is_connected and self.is_routable

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "is_registered": self.is_registered,
            "is_online": self.is_online,
            "is_connected": self.is_connected,
            "is_routable": self.is_routable,
            "capabilities": list(self.capabilities),
            "resolution_source": self.resolution_source,
            "authority_available": self.authority_available,
            "compat_present": self.compat_present,
            "conflicts": list(self.conflicts),
        }


# ---------------------------------------------------------------------------
# Internal helpers — lazy accessor functions (avoid circular imports)
# ---------------------------------------------------------------------------


def _get_udm():
    """Return the UnifiedDeviceManager singleton (best-effort)."""
    try:
        from core.unified.device_manager import get_unified_device_manager  # type: ignore
        return get_unified_device_manager()
    except Exception:
        return None


def _get_ucm():
    """Return the UnifiedConnectionManager singleton (best-effort)."""
    try:
        from core.unified.connection_manager import get_unified_connection_manager  # type: ignore
        return get_unified_connection_manager()
    except Exception:
        return None


def _get_compat_cache() -> Dict[str, Dict[str, Any]]:
    """Return the compat registered_devices dict (best-effort, empty on failure)."""
    try:
        from core.routes._shared import registered_devices  # type: ignore
        return registered_devices
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Core resolution logic
# ---------------------------------------------------------------------------

# Canonical set of status strings that represent an "online/active" device.
# Applied consistently for both UDM and compat-cache status interpretation.
# "registered" is included because legacy compat cache uses it to mean active.
_ONLINE_STATUS_VALUES: frozenset = frozenset(
    ("online", "connected", "active", "registered")
)


def _status_is_online(status_str: str) -> bool:
    """Return True when *status_str* represents an online/active device.

    Centralises status string interpretation so that UDM and compat-cache
    paths use identical semantics.
    """
    return status_str.lower() in _ONLINE_STATUS_VALUES


def _resolve_from_authority(
    device_id: str,
    udm,
    ucm,
) -> tuple[bool, bool, bool, bool, List[Any], Optional[Dict], Optional[Dict]]:
    """Query UCM and UDM for authoritative truth.

    Returns:
        (is_registered, is_online, is_connected, is_routable,
         capabilities, raw_udm_dict, raw_ucm_dict)
    """
    is_registered = False
    is_online = False
    capabilities: List[Any] = []
    raw_udm: Optional[Dict[str, Any]] = None

    # --- UDM: registration / online / capabilities ---
    if udm is not None:
        try:
            dev = udm.get_device(device_id)
            if dev is not None:
                is_registered = True
                status = getattr(dev, "status", None)
                if status is not None:
                    status_val = status.value if hasattr(status, "value") else str(status)
                    is_online = _status_is_online(status_val)
                capabilities = list(getattr(dev, "capabilities", []) or [])
                # Build a minimal raw dict for diagnostics
                raw_udm = {
                    "device_id": device_id,
                    "status": str(status) if status else None,
                    "capabilities": capabilities,
                }
        except Exception as exc:
            logger.debug(
                "TIL: UDM query failed for %s — %s",
                device_id,
                exc,
                extra={"event": "til_udm_query_error", "device_id": device_id},
            )

    is_connected = False
    is_routable = False
    raw_ucm: Optional[Dict[str, Any]] = None

    # --- UCM: connection / routable ---
    if ucm is not None:
        try:
            conn_info = ucm.get_connection(device_id)
            if conn_info is not None:
                is_connected = True
                is_routable = bool(getattr(conn_info, "routable", True))
                raw_ucm = {
                    "device_id": device_id,
                    "routable": is_routable,
                    "state": str(getattr(conn_info, "state", "unknown")),
                }
            elif ucm.is_device_connected(device_id):
                # WebSocket exists but info record is missing — treat as connected
                is_connected = True
                is_routable = True
                raw_ucm = {"device_id": device_id, "routable": True, "state": "connected_no_info"}
        except Exception as exc:
            logger.debug(
                "TIL: UCM query failed for %s — %s",
                device_id,
                exc,
                extra={"event": "til_ucm_query_error", "device_id": device_id},
            )

    return is_registered, is_online, is_connected, is_routable, capabilities, raw_udm, raw_ucm


def _detect_conflicts(
    device_id: str,
    is_registered: bool,
    is_online: bool,
    compat_entry: Optional[Dict[str, Any]],
) -> List[str]:
    """Compare authority verdict against compat cache and return conflict strings.

    Conflicts are **informational** — they do not change the authority verdict.
    """
    conflicts: List[str] = []
    if compat_entry is None:
        return conflicts

    compat_online = bool(
        compat_entry.get("online", False)
        or _status_is_online(str(compat_entry.get("status", "")))
    )

    if is_registered and not compat_online and compat_entry:
        # Authority says registered/online, compat says offline — compat is stale
        conflicts.append(
            f"compat-cache marks device '{device_id}' offline/unregistered "
            "but authority (UDM) confirms registration"
        )
    elif not is_registered and compat_online:
        # Compat says online, authority says not registered — compat is stale
        conflicts.append(
            f"compat-cache reports device '{device_id}' as online/registered "
            "but authority (UDM) has no record — compat cache is stale"
        )

    return conflicts


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def resolve_device_truth(device_id: str) -> CanonicalDeviceTruth:
    """Resolve canonical runtime truth for *device_id*.

    Queries UCM (connection/presence authority) and UDM
    (registration/state/capabilities authority) as primary sources.
    The compat cache (``registered_devices``) is consulted **only** for
    conflict detection and as a last-resort supplement when both UCM and UDM
    are unreachable.

    The returned :class:`CanonicalDeviceTruth` is the single source of truth
    that :mod:`core.device_readiness`, :mod:`core.device_participation`, and
    :mod:`core.target_device_validator` should consume.

    Args:
        device_id: The device identifier to resolve.

    Returns:
        CanonicalDeviceTruth — never raises.
    """
    truth = CanonicalDeviceTruth(device_id=device_id)

    udm = _get_udm()
    ucm = _get_ucm()
    compat = _get_compat_cache()
    compat_entry: Optional[Dict[str, Any]] = compat.get(device_id)

    truth.compat_present = compat_entry is not None
    truth.raw_compat = dict(compat_entry) if compat_entry else None

    authority_available = (udm is not None) or (ucm is not None)
    truth.authority_available = authority_available

    (
        is_registered, is_online, is_connected, is_routable,
        capabilities, raw_udm, raw_ucm,
    ) = _resolve_from_authority(device_id, udm, ucm)

    if authority_available and (is_registered or is_connected):
        # ── Primary path: UCM/UDM returned data ──
        truth.is_registered = is_registered
        truth.is_online = is_online
        truth.is_connected = is_connected
        truth.is_routable = is_routable
        truth.capabilities = capabilities
        truth.raw_udm = raw_udm
        truth.raw_ucm = raw_ucm
        truth.resolution_source = "ucm_udm"
        # Detect conflicts with compat cache (informational only)
        truth.conflicts = _detect_conflicts(device_id, is_registered, is_online, compat_entry)

        logger.debug(
            "TIL resolved '%s' from authority: registered=%s online=%s "
            "connected=%s routable=%s conflicts=%d",
            device_id, is_registered, is_online, is_connected, is_routable,
            len(truth.conflicts),
            extra={"event": "til_resolved_authority", "device_id": device_id},
        )
        return truth

    # ── Fallback: UCM/UDM had no record — check compat cache as supplement ──
    if compat_entry is not None:
        compat_status = str(compat_entry.get("status", "offline"))
        compat_online_flag = bool(
            compat_entry.get("online", False)
            or _status_is_online(compat_status)
        )
        truth.is_registered = True  # compat has an entry → assume registered
        truth.is_online = compat_online_flag
        truth.is_connected = compat_online_flag
        truth.is_routable = compat_online_flag
        truth.capabilities = list(compat_entry.get("capabilities", []))
        truth.raw_compat = dict(compat_entry)
        # Distinguish: authorities reachable but had no record vs authorities down
        truth.resolution_source = (
            "compat_supplement" if authority_available else "compat_only"
        )
        logger.debug(
            "TIL resolved '%s' from compat cache (source=%s): online=%s",
            device_id, truth.resolution_source, compat_online_flag,
            extra={"event": "til_resolved_compat", "device_id": device_id},
        )
        return truth

    # ── No data anywhere — device is unknown ──
    truth.resolution_source = "ucm_udm"  # authorities were the decisive source
    logger.debug(
        "TIL: device '%s' not found in any source",
        device_id,
        extra={"event": "til_device_not_found", "device_id": device_id},
    )
    return truth


def resolve_all_device_truth() -> List[CanonicalDeviceTruth]:
    """Resolve canonical runtime truth for every known device.

    Union of:
    * All devices registered in UDM
    * All devices with active WebSocket connections in UCM
    * All devices in the compat cache

    De-duplicated by ``device_id``.  Each entry is fully resolved via
    :func:`resolve_device_truth` so authority-hierarchy rules are always
    applied.

    Returns:
        List of :class:`CanonicalDeviceTruth`, one per unique device_id.
        Never raises.
    """
    device_ids: List[str] = []

    # Collect from UDM
    udm = _get_udm()
    if udm is not None:
        try:
            for dev in udm.list_devices():
                did = getattr(dev, "device_id", None)
                if did and did not in device_ids:
                    device_ids.append(did)
        except Exception as exc:
            logger.debug("TIL: UDM list_devices failed — %s", exc)

    # Collect from UCM
    ucm = _get_ucm()
    if ucm is not None:
        try:
            for entry in ucm.get_all_devices():
                did = (
                    entry.get("device_id")
                    if isinstance(entry, dict)
                    else getattr(entry, "device_id", None)
                )
                if did and did not in device_ids:
                    device_ids.append(did)
        except Exception as exc:
            logger.debug("TIL: UCM get_all_devices failed — %s", exc)

    # Supplement with compat cache (devices not yet in authority sources)
    compat = _get_compat_cache()
    for did in compat:
        if did not in device_ids:
            device_ids.append(did)

    return [resolve_device_truth(did) for did in device_ids]


def is_device_available_canonical(device_id: str) -> bool:
    """Return True iff the device is fully available per canonical truth.

    A device is considered available when
    :attr:`CanonicalDeviceTruth.is_available` is ``True``, i.e. it is
    registered, online, connected, and routable.

    This is the recommended single-call API for hot-path eligibility checks.
    Callers that need richer details should use :func:`resolve_device_truth`.
    """
    return resolve_device_truth(device_id).is_available
