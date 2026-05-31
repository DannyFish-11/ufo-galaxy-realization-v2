"""core/cross_device_candidates.py
==================================
PR-12 — Unified Cross-Device Execution Candidate Resolution.

This module provides a single, canonical location for resolving which devices
are eligible to participate in cross-device execution by combining:

1. **Canonical readiness** — via :mod:`core.device_readiness`
   (``is_device_cross_device_ready``)
2. **Orchestration-eligibility / participation** — via :mod:`core.device_participation`
   (``is_device_orchestration_ready``)
3. **Capability matching** — via :mod:`core.capability_registry`
   (``device_matches_capabilities``)

Design goals
------------
- **Additive only** — no existing module is modified.
- **Graceful degradation** — every subsystem import is wrapped in a
  ``try/except``; missing subsystems record a reason and continue.
- **Structured observability** — each exclusion decision is logged with a
  reason string so operators can understand why a device was skipped.
- **No circular imports** — all subsystem imports are performed lazily inside
  helper functions, not at module level.

Public API
----------
Models:
    CrossDeviceCandidate
    CrossDeviceCandidateResolution

Helpers:
    resolve_cross_device_candidates(required_capabilities, requested_target_device,
                                    require_orchestration_eligible)
    get_selected_cross_device_candidates(required_capabilities, requested_target_device,
                                         require_orchestration_eligible)

Authority sentinel:
    CROSS_DEVICE_CANDIDATES_AUTHORITY
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.CrossDeviceCandidates")

__all__ = [
    "CrossDeviceCandidate",
    "CrossDeviceCandidateResolution",
    "resolve_cross_device_candidates",
    "get_selected_cross_device_candidates",
    "CROSS_DEVICE_CANDIDATES_AUTHORITY",
]

# ---------------------------------------------------------------------------
# Authority sentinel
# ---------------------------------------------------------------------------

CROSS_DEVICE_CANDIDATES_AUTHORITY = (
    "core.cross_device_candidates"
    " — canonical cross-device execution candidate resolution layer (PR-12)"
)

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class CrossDeviceCandidate:
    """Serialisable record describing a single device's eligibility.

    Attributes
    ----------
    device_id:
        Unique device identifier.
    ready:
        ``True`` when the canonical readiness gate passes
        (registered + online + connected + routable).
    orchestration_eligible:
        ``True`` when the canonical participation gate passes.
    capability_match:
        ``True`` when every required capability is satisfied, or ``True`` when
        no capability requirements were specified.
    selected:
        ``True`` when all active gates pass and the device is included in
        the eligible/selected set.
    reasons:
        Human-readable notes explaining any exclusion that occurred.
    sources:
        Diagnostic dict forwarded from the underlying subsystem calls.
    """

    device_id: str
    ready: bool = False
    orchestration_eligible: bool = False
    capability_match: bool = True
    selected: bool = False
    reasons: List[str] = field(default_factory=list)
    sources: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable representation."""
        return {
            "device_id": self.device_id,
            "ready": self.ready,
            "orchestration_eligible": self.orchestration_eligible,
            "capability_match": self.capability_match,
            "selected": self.selected,
            "reasons": list(self.reasons),
            "sources": dict(self.sources),
        }


@dataclass
class CrossDeviceCandidateResolution:
    """Serialisable result of a full candidate-resolution pass.

    Attributes
    ----------
    required_capabilities:
        The capability requirements that were applied during resolution, or
        an empty list when no capability filter was requested.
    requested_target_device:
        Optional device ID that was explicitly requested by the caller.
    candidates:
        Per-device :class:`CrossDeviceCandidate` records for every enumerated
        device.
    selected_device_ids:
        Device IDs that passed all active gates (subset of
        ``eligible_device_ids`` after optional target prioritisation).
    eligible_device_ids:
        Device IDs that passed every gate but may not be the requested target.
    reasons:
        Resolution-level notes (e.g. why a requested target was excluded).
    """

    required_capabilities: List[str] = field(default_factory=list)
    requested_target_device: Optional[str] = None
    candidates: List[CrossDeviceCandidate] = field(default_factory=list)
    selected_device_ids: List[str] = field(default_factory=list)
    eligible_device_ids: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable representation."""
        return {
            "required_capabilities": list(self.required_capabilities),
            "requested_target_device": self.requested_target_device,
            "candidates": [c.to_dict() for c in self.candidates],
            "selected_device_ids": list(self.selected_device_ids),
            "eligible_device_ids": list(self.eligible_device_ids),
            "reasons": list(self.reasons),
        }


# ---------------------------------------------------------------------------
# Internal helpers — lazy subsystem access (all try/except for resilience)
# ---------------------------------------------------------------------------


def _enumerate_device_ids() -> List[str]:
    """Return all known device IDs from the device registry.

    Returns an empty list with a debug log if the registry is unavailable.
    """
    try:
        from core.device_registry import device_registry

        devices = device_registry.list_devices()
        return [str(getattr(d, "device_id", "") or "") for d in devices]
    except Exception as exc:
        logger.debug(
            "cross_device_candidates: device_registry unavailable for enumeration — %s",
            exc,
        )
        return []


def _check_readiness(device_id: str) -> tuple[bool, List[str]]:
    """Return ``(ready, reasons)`` from the canonical readiness layer.

    Degrades to ``(False, [reason])`` when the layer is unavailable.
    """
    try:
        from core.device_readiness import is_device_cross_device_ready

        ready = is_device_cross_device_ready(device_id)
        return ready, []
    except Exception as exc:
        logger.debug("Fallback triggered: %s", exc)
        reason = f"readiness layer unavailable for {device_id!r} — {exc}"
        logger.debug("cross_device_candidates: %s", reason)
        return False, [reason]


def _check_orchestration_eligible(device_id: str) -> tuple[bool, List[str]]:
    """Return ``(eligible, reasons)`` from the canonical participation layer.

    Degrades to ``(False, [reason])`` when the layer is unavailable.
    """
    try:
        from core.device_participation import is_device_orchestration_ready

        eligible = is_device_orchestration_ready(device_id)
        return eligible, []
    except Exception as exc:
        logger.debug("Fallback triggered: %s", exc)
        reason = f"participation layer unavailable for {device_id!r} — {exc}"
        logger.debug("cross_device_candidates: %s", reason)
        return False, [reason]


def _check_capabilities(
    device_id: str,
    required_capabilities: List[str],
) -> tuple[bool, Dict[str, Any], List[str]]:
    """Return ``(matched, sources, reasons)`` from the capability layer.

    If *required_capabilities* is empty, returns ``(True, {}, [])``
    immediately.  Degrades gracefully on import failure.
    """
    if not required_capabilities:
        return True, {}, []
    try:
        from core.capability_registry import device_matches_capabilities

        result = device_matches_capabilities(device_id, required_capabilities)
        extra_reasons: List[str] = []
        if not result.matched:
            extra_reasons.append(
                f"capability mismatch for {device_id!r} — "
                f"missing: {result.missing_capabilities}"
            )
        return result.matched, result.sources, result.reasons + extra_reasons
    except Exception as exc:
        logger.debug("Fallback triggered: %s", exc)
        reason = f"capability layer unavailable for {device_id!r} — {exc}"
        logger.debug("cross_device_candidates: %s", reason)
        return False, {}, [reason]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def resolve_cross_device_candidates(
    required_capabilities: Optional[List[str]] = None,
    requested_target_device: Optional[str] = None,
    require_orchestration_eligible: bool = True,
) -> CrossDeviceCandidateResolution:
    """Resolve the eligible set of devices for cross-device execution.

    Each device enumerated from the device registry is evaluated against up to
    three gates (applied in order):

    1. **Readiness gate** — ``is_device_cross_device_ready``
    2. **Orchestration-eligibility gate** — ``is_device_orchestration_ready``
       (skipped when *require_orchestration_eligible* is ``False``)
    3. **Capability gate** — ``device_matches_capabilities``
       (skipped when *required_capabilities* is empty or ``None``)

    A device is **selected** only when it passes every active gate.

    If *requested_target_device* is provided, the resolution validates that
    device against all gates.  When it is excluded, explicit reasons are
    appended to the resolution-level ``reasons`` list so callers understand
    why the preference cannot be honoured.  When valid, the requested target
    is listed first in ``selected_device_ids``.

    Parameters
    ----------
    required_capabilities:
        List of capability names that all candidates must satisfy.
        ``None`` or empty list skips the capability gate.
    requested_target_device:
        Optional device ID explicitly requested by the caller.  Will be
        validated and surfaced with reasons if excluded.
    require_orchestration_eligible:
        When ``True`` (default), devices must pass the orchestration-
        eligibility gate.  Set to ``False`` to skip this gate.

    Returns
    -------
    CrossDeviceCandidateResolution
        Full resolution record including per-device candidates, selected IDs,
        eligible IDs, and resolution-level reasons.  Never raises.
    """
    caps: List[str] = list(required_capabilities) if required_capabilities else []

    resolution = CrossDeviceCandidateResolution(
        required_capabilities=caps,
        requested_target_device=requested_target_device,
    )

    try:
        return _resolve_candidates_inner(resolution, caps, requested_target_device, require_orchestration_eligible)
    except Exception as exc:
        logger.warning("cross_device_candidates: unexpected error in resolution — %s", exc)
        return resolution


def _resolve_candidates_inner(
    resolution: CrossDeviceCandidateResolution,
    caps: List[str],
    requested_target_device: Optional[str],
    require_orchestration_eligible: bool,
) -> CrossDeviceCandidateResolution:
    """Inner resolution logic — separated for top-level exception isolation."""
    # ── Enumerate device IDs ──────────────────────────────────────────────
    all_ids = _enumerate_device_ids()

    # Ensure the requested target is included in the evaluation even if it
    # is not known to the registry (so we can produce explicit reasons).
    if requested_target_device and requested_target_device not in all_ids:
        all_ids = [requested_target_device] + all_ids
        resolution.reasons.append(
            f"requested_target_device {requested_target_device!r} not found "
            f"in device registry — evaluated anyway to surface exclusion reasons"
        )

    eligible_ids: List[str] = []

    for device_id in all_ids:
        if not device_id:
            continue

        candidate = CrossDeviceCandidate(device_id=device_id)

        # ── Gate 1: Readiness ─────────────────────────────────────────────
        ready, readiness_reasons = _check_readiness(device_id)
        candidate.ready = ready
        if not ready:
            candidate.reasons.append(
                f"excluded: not cross-device ready"
            )
            candidate.reasons.extend(readiness_reasons)
            logger.info(
                "cross_device_candidates | EXCLUDED | device_id=%s | reason=not_ready",
                device_id,
            )
            resolution.candidates.append(candidate)
            continue

        # ── Gate 2: Orchestration eligibility ─────────────────────────────
        if require_orchestration_eligible:
            eligible, participation_reasons = _check_orchestration_eligible(device_id)
            candidate.orchestration_eligible = eligible
            if not eligible:
                candidate.reasons.append(
                    f"excluded: not orchestration-eligible"
                )
                candidate.reasons.extend(participation_reasons)
                logger.info(
                    "cross_device_candidates | EXCLUDED | device_id=%s "
                    "| reason=not_orchestration_eligible",
                    device_id,
                )
                resolution.candidates.append(candidate)
                continue
        else:
            # Gate skipped; treat as eligible for logging purposes.
            candidate.orchestration_eligible = True

        # ── Gate 3: Capability matching ───────────────────────────────────
        cap_matched, cap_sources, cap_reasons = _check_capabilities(
            device_id, caps
        )
        candidate.capability_match = cap_matched
        candidate.sources.update(cap_sources)
        if not cap_matched:
            candidate.reasons.extend(cap_reasons)
            logger.info(
                "cross_device_candidates | EXCLUDED | device_id=%s "
                "| reason=capability_mismatch | missing=%s",
                device_id,
                cap_reasons,
            )
            resolution.candidates.append(candidate)
            continue

        # ── All gates passed ──────────────────────────────────────────────
        candidate.selected = True
        eligible_ids.append(device_id)
        logger.debug(
            "cross_device_candidates | SELECTED | device_id=%s",
            device_id,
        )
        resolution.candidates.append(candidate)

    resolution.eligible_device_ids = list(eligible_ids)

    # ── Apply requested-target prioritisation ─────────────────────────────
    if requested_target_device:
        if requested_target_device in eligible_ids:
            # Requested target is valid — put it first.
            ordered = [requested_target_device] + [
                d for d in eligible_ids if d != requested_target_device
            ]
            resolution.selected_device_ids = ordered
        else:
            # Requested target was excluded — surface clear reasons.
            target_candidate = next(
                (c for c in resolution.candidates if c.device_id == requested_target_device),
                None,
            )
            if target_candidate:
                excl_reasons = target_candidate.reasons or ["excluded by one or more gates"]
            else:
                excl_reasons = ["not evaluated — unknown device"]
            resolution.reasons.append(
                f"requested_target_device {requested_target_device!r} was excluded: "
                + "; ".join(excl_reasons)
            )
            logger.info(
                "cross_device_candidates | requested_target EXCLUDED | "
                "device_id=%s | reasons=%s",
                requested_target_device,
                excl_reasons,
            )
            # Fall back to all eligible devices (no specific target).
            resolution.selected_device_ids = list(eligible_ids)
    else:
        resolution.selected_device_ids = list(eligible_ids)

    logger.debug(
        "cross_device_candidates | resolution complete | "
        "selected=%s eligible=%s total_evaluated=%s",
        resolution.selected_device_ids,
        resolution.eligible_device_ids,
        len(resolution.candidates),
    )

    return resolution


def get_selected_cross_device_candidates(
    required_capabilities: Optional[List[str]] = None,
    requested_target_device: Optional[str] = None,
    require_orchestration_eligible: bool = True,
) -> List[CrossDeviceCandidate]:
    """Return only the selected :class:`CrossDeviceCandidate` records.

    Convenience wrapper around :func:`resolve_cross_device_candidates` that
    filters candidates to those with ``selected=True``.

    Parameters
    ----------
    required_capabilities:
        List of capability names all candidates must satisfy.
    requested_target_device:
        Optional preferred device ID (validated; surfaced with reasons if
        excluded).
    require_orchestration_eligible:
        When ``True`` (default), candidates must be orchestration-eligible.

    Returns
    -------
    list[CrossDeviceCandidate]
        Candidates that passed all active gates.  Empty list on error.
        Never raises.
    """
    resolution = resolve_cross_device_candidates(
        required_capabilities=required_capabilities,
        requested_target_device=requested_target_device,
        require_orchestration_eligible=require_orchestration_eligible,
    )
    return [c for c in resolution.candidates if c.selected]
