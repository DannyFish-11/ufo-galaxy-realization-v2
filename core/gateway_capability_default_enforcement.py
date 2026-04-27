#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/gateway_capability_default_enforcement.py
===============================================
Gateway-level default capability enforcement for ``send_gateway_command``.

Problem addressed
-----------------
``send_gateway_command()`` in :mod:`core.openclawd` already accepts a
``required_capabilities`` parameter, but the gate was only activated when the
caller explicitly passed capabilities.  When no capabilities were supplied —
which was the common case for most call sites — ``_effective_caps`` became
``None`` and the capability gate was silently skipped.  This meant that
explicit device routing could bypass capability reality with zero audit trail.

This module closes ``GAP_CAPABILITY_GATE_DEFAULT_ENFORCEMENT`` by providing:

1. A **command-to-capability inference table** that maps canonical command
   names to their minimum required capabilities, so the gate can activate even
   when callers omit ``required_capabilities``.
2. A **device capability lookup helper** that resolves live device capabilities
   from :class:`~core.device_registry.DeviceRegistry` (with graceful
   degradation when the registry is unavailable).
3. :func:`enforce_gateway_default_capability_gate` — the canonical gate
   function called by ``send_gateway_command`` before dispatching to any
   backend (``CommandRouter``, ``DeviceOrchestrator``, or WebSocket).  The
   gate:

   * Resolves effective required capabilities (explicit → inferred → none).
   * Resolves device capabilities from the registry when not pre-supplied.
   * Delegates to :func:`~core.capability_enforcement_hardener.enforce_mainline_capability_gate`
     for actual enforcement (STRICT mode → hard reject; AUDIT mode → audited
     mismatch).
   * Returns a :class:`~core.capability_enforcement_hardener.HardenedEnforcementRecord`
     so callers can attach the audit result to response metadata.

4. :func:`audit_gateway_override` — the explicit override path that requires
   a documented reason, ensuring capability bypasses are never silent.

Design principles
-----------------
- **Default ON** — the gate runs for every ``send_gateway_command`` call that
  resolves a non-empty effective capability set.  Empty → no-op (backward
  compatible with existing call sites that omit ``required_capabilities``).
- **Explicit routing is not exempt** — passing an explicit ``device_id`` does
  not bypass the gate.  The gate is applied before any backend is contacted.
- **Graceful degradation** — when device capability data is unavailable the
  gate returns ``INSUFFICIENT_DATA`` rather than raising, preserving uptime
  while leaving an audit trail.
- **Additive only** — does not modify ``capability_routing_gate.py``,
  ``mainline_routing_enforcement.py``, or ``capability_enforcement_hardener.py``.

Public API
----------
Sentinels::

    GATEWAY_DEFAULT_ENFORCEMENT_AUTHORITY
    GATEWAY_DEFAULT_ENFORCEMENT_PR_SENTINEL
    EXPLICIT_ROUTING_DOES_NOT_EXEMPT_CAPABILITY_GATE_POLICY
    DEFAULT_ENFORCEMENT_CLOSES_GAP_CAPABILITY_GATE_POLICY

Functions::

    infer_required_capabilities(command)             -> List[str]
    lookup_device_capabilities(device_id)            -> List[str]
    enforce_gateway_default_capability_gate(...)     -> HardenedEnforcementRecord
    audit_gateway_override(...)                      -> HardenedEnforcementRecord
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Sequence

logger = logging.getLogger("Galaxy.GatewayCapabilityDefaultEnforcement")

__all__ = [
    # Sentinels
    "GATEWAY_DEFAULT_ENFORCEMENT_AUTHORITY",
    "GATEWAY_DEFAULT_ENFORCEMENT_PR_SENTINEL",
    "EXPLICIT_ROUTING_DOES_NOT_EXEMPT_CAPABILITY_GATE_POLICY",
    "DEFAULT_ENFORCEMENT_CLOSES_GAP_CAPABILITY_GATE_POLICY",
    # Functions
    "infer_required_capabilities",
    "lookup_device_capabilities",
    "enforce_gateway_default_capability_gate",
    "audit_gateway_override",
]

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

GATEWAY_DEFAULT_ENFORCEMENT_AUTHORITY: str = (
    "GATEWAY_DEFAULT_ENFORCEMENT_AUTHORITY_V1: "
    "core.gateway_capability_default_enforcement is the canonical default "
    "capability enforcement layer for send_gateway_command().  It ensures "
    "that the capability gate runs on every canonical gateway dispatch, "
    "regardless of whether the caller explicitly supplies required_capabilities. "
    "All gateway-level capability enforcement must flow through this module."
)

GATEWAY_DEFAULT_ENFORCEMENT_PR_SENTINEL: str = (
    "PR::GAP_CAPABILITY_GATE_DEFAULT_ENFORCEMENT_CLOSURE_V1: "
    "This module was introduced to close GAP_CAPABILITY_GATE_DEFAULT_ENFORCEMENT. "
    "Prior to this module, send_gateway_command() silently skipped the capability "
    "gate when required_capabilities was None.  This module makes the gate the "
    "default invariant, not an optional caller-supplied switch."
)

EXPLICIT_ROUTING_DOES_NOT_EXEMPT_CAPABILITY_GATE_POLICY: str = (
    "POLICY::EXPLICIT_ROUTING_DOES_NOT_EXEMPT_CAPABILITY_GATE_V1: "
    "Supplying an explicit device_id to send_gateway_command() does NOT exempt "
    "the dispatch from capability reality checks.  The gate is enforced before "
    "contacting any backend (CommandRouter, DeviceOrchestrator, WebSocket).  "
    "Bypassing by supplying device_id without required_capabilities is not a "
    "supported path; the gate will infer capabilities from the command name."
)

DEFAULT_ENFORCEMENT_CLOSES_GAP_CAPABILITY_GATE_POLICY: str = (
    "POLICY::DEFAULT_ENFORCEMENT_CLOSES_GAP_CAPABILITY_GATE_V1: "
    "GAP_CAPABILITY_GATE_DEFAULT_ENFORCEMENT is closed by this module.  "
    "The canonical test for this closure is "
    "tests/test_gateway_capability_default_enforcement.py.  "
    "Removing this module or making enforce_gateway_default_capability_gate() "
    "a no-op reopens the bypass gap."
)


# ---------------------------------------------------------------------------
# Command → required capability inference table
# ---------------------------------------------------------------------------

#: Maps canonical command name prefixes / exact names to the minimum set of
#: capabilities a device must possess to execute that command.  Keys are
#: matched case-insensitively against the first path segment of the command.
#:
#: This table is intentionally conservative: it only asserts capabilities
#: that are *necessary* for the command to succeed.  Optional / enhancing
#: capabilities are not included here.
_COMMAND_CAPABILITY_MAP: Dict[str, List[str]] = {
    # Camera / imaging
    "take_photo": ["camera"],
    "capture_photo": ["camera"],
    "take_screenshot": ["screen"],
    "capture_screenshot": ["screen"],
    "record_video": ["camera"],
    "camera": ["camera"],
    # Audio
    "record_audio": ["microphone"],
    "listen": ["microphone"],
    "speak": ["microphone"],
    "transcribe": ["microphone"],
    # Screen / display
    "screen_click": ["screen", "touch"],
    "screen_tap": ["screen", "touch"],
    "screen_swipe": ["screen", "touch"],
    "tap": ["touch"],
    "swipe": ["touch"],
    "scroll": ["touch"],
    "click": ["touch"],
    "type_text": ["keyboard"],
    "press_key": ["keyboard"],
    # Location
    "gps_locate": ["gps"],
    "get_location": ["gps"],
    "location": ["gps"],
    "navigate": ["gps"],
    # NFC
    "nfc_read": ["nfc"],
    "nfc_write": ["nfc"],
    "nfc": ["nfc"],
    # Bluetooth
    "bluetooth_scan": ["bluetooth"],
    "bluetooth_connect": ["bluetooth"],
    "bluetooth": ["bluetooth"],
    # Local AI / intelligence
    "local_ai": ["local_ai"],
    "local_infer": ["local_ai"],
    "local_plan": ["local_ai"],
    "local_ground": ["local_ai"],
    "run_local_model": ["local_ai"],
    # Sensor
    "accelerometer_read": ["accelerometer"],
    "gyroscope_read": ["gyroscope"],
    # Network / connectivity
    "wifi_scan": ["wifi"],
    "cellular_send": ["cellular"],
}


def infer_required_capabilities(command: str) -> List[str]:
    """Infer the minimum required capabilities for *command*.

    Performs a two-pass lookup:

    1. Exact match (case-insensitive) against
       :data:`_COMMAND_CAPABILITY_MAP`.
    2. Prefix match — the command may contain a ``/`` or ``_`` separated
       qualifier (e.g. ``camera/front``).  The first segment is tried as a
       prefix match.

    Parameters
    ----------
    command:
        Canonical command name as supplied to ``send_gateway_command()``.

    Returns
    -------
    list[str]
        List of required capability strings, or an empty list when the
        command has no capability requirement in the inference table.
    """
    if not command:
        return []

    cmd_lower = command.lower().strip()

    # Exact match
    if cmd_lower in _COMMAND_CAPABILITY_MAP:
        return list(_COMMAND_CAPABILITY_MAP[cmd_lower])

    # Prefix match on the first segment (split by '/' or '_' only at start)
    first_segment = cmd_lower.split("/")[0].split("_")[0]
    for key, caps in _COMMAND_CAPABILITY_MAP.items():
        if cmd_lower.startswith(key + "_") or cmd_lower.startswith(key + "/"):
            return list(caps)

    # Try to match any table key as a substring prefix of the command
    for key, caps in _COMMAND_CAPABILITY_MAP.items():
        if cmd_lower.startswith(key):
            return list(caps)

    return []


def lookup_device_capabilities(device_id: str) -> List[str]:
    """Resolve the live capabilities for *device_id* from the registry.

    Attempts lookup via :class:`~core.device_registry.DeviceRegistry` (which
    itself reflects UDM-authoritative state when UDM is available).

    Parameters
    ----------
    device_id:
        Target device identifier.

    Returns
    -------
    list[str]
        List of capability strings reported by the device, or an empty list
        when the device is unknown or the registry is unavailable.
    """
    if not device_id:
        return []
    try:
        from core.device_registry import DeviceRegistry

        dr = DeviceRegistry.get_instance()
        device = dr.get(device_id)
        if device is None:
            logger.debug(
                "lookup_device_capabilities: device=%s not found in registry",
                device_id,
            )
            return []
        raw_caps = getattr(device, "capabilities", None) or []
        # DeviceCapabilityModel instances have a `.name` attribute; plain
        # strings are used directly.
        caps: List[str] = []
        for cap in raw_caps:
            if isinstance(cap, str):
                caps.append(cap)
            elif hasattr(cap, "name"):
                caps.append(str(cap.name))
            else:
                caps.append(str(cap))
        logger.debug(
            "lookup_device_capabilities: device=%s caps=%s",
            device_id,
            caps,
        )
        return caps
    except (ImportError, AttributeError, KeyError, TypeError) as exc:
        logger.debug(
            "lookup_device_capabilities: failed for device=%s — %s",
            device_id,
            exc,
        )
        return []


def enforce_gateway_default_capability_gate(
    device_id: str,
    command: str,
    *,
    required_capabilities: Optional[Sequence[str]] = None,
    device_capabilities: Optional[Sequence[str]] = None,
    calling_site: str = "send_gateway_command",
):
    """Enforce the capability gate for a ``send_gateway_command`` dispatch.

    This is the canonical default enforcement entry-point.  It is called
    before contacting any backend so that explicit routing cannot silently
    bypass capability reality.

    Resolution order for *required_capabilities*
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    1. Explicit ``required_capabilities`` argument (if non-empty).
    2. Inferred via :func:`infer_required_capabilities` from *command*.
    3. Empty list → gate is a no-op (returns ``NO_REQUIREMENTS`` record).

    Resolution order for *device_capabilities*
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    1. Explicit ``device_capabilities`` argument (if not None, even if empty).
    2. Live lookup via :func:`lookup_device_capabilities`.
    3. Empty list → gate returns ``INSUFFICIENT_DATA`` (not a hard reject).

    Parameters
    ----------
    device_id:
        Target device identifier.
    command:
        Canonical command name (used for capability inference).
    required_capabilities:
        Explicit required capabilities.  When ``None`` or empty, the
        inference table is consulted.
    device_capabilities:
        Pre-resolved device capabilities.  When ``None``, a live lookup is
        performed.  Pass an explicit empty list to signal "device has no
        capabilities" without triggering a lookup.
    calling_site:
        Human-readable label for the call site.

    Returns
    -------
    HardenedEnforcementRecord
        Gate decision record.  Callers should attach this to response
        metadata for observability.

    Raises
    ------
    CapabilityHardRejectError
        When the effective required capabilities are non-empty, the device
        capabilities are known, and one or more required capabilities are
        absent.  This is the canonical hard-reject path.
    """
    from core.capability_enforcement_hardener import (
        EnforcementMode,
        enforce_mainline_capability_gate,
    )

    # ── Step 1: Resolve effective required capabilities ──────────────────────
    eff_required: List[str] = []
    if required_capabilities:
        eff_required = [c for c in required_capabilities if c]
    if not eff_required:
        eff_required = infer_required_capabilities(command)

    # ── Step 2: Resolve device capabilities ──────────────────────────────────
    if device_capabilities is not None:
        eff_device_caps: List[str] = list(device_capabilities)
    else:
        eff_device_caps = lookup_device_capabilities(device_id)

    logger.debug(
        "[%s] gateway capability gate: device=%s command=%s "
        "effective_required=%s device_caps=%s",
        calling_site,
        device_id,
        command,
        eff_required,
        eff_device_caps,
    )

    # ── Step 3: Delegate to hardened enforcement ──────────────────────────────
    return enforce_mainline_capability_gate(
        device_id=device_id,
        required_capabilities=eff_required,
        device_capabilities=eff_device_caps,
        mode=EnforcementMode.STRICT,
        calling_site=calling_site,
    )


def audit_gateway_override(
    device_id: str,
    command: str,
    override_reason: str,
    *,
    required_capabilities: Optional[Sequence[str]] = None,
    device_capabilities: Optional[Sequence[str]] = None,
    calling_site: str = "send_gateway_command",
):
    """Record an explicit capability gate override with a mandatory audit token.

    Use this function when a dispatch must proceed despite a capability
    mismatch and the caller can provide a documented justification.

    Parameters
    ----------
    device_id:
        Target device.
    command:
        Command being dispatched (used for inference if ``required_capabilities``
        is not supplied).
    override_reason:
        **Mandatory** non-empty human-readable justification.
        Raises :exc:`ValueError` when empty.
    required_capabilities:
        Explicit required capabilities; inferred from *command* when ``None``.
    device_capabilities:
        Pre-resolved device capabilities; live lookup performed when ``None``.
    calling_site:
        Human-readable call-site label.

    Returns
    -------
    HardenedEnforcementRecord
        Record with ``verdict=AUDITED_OVERRIDE``.

    Raises
    ------
    ValueError
        When ``override_reason`` is empty.
    """
    from core.capability_enforcement_hardener import audit_capability_override

    eff_required: List[str] = []
    if required_capabilities:
        eff_required = [c for c in required_capabilities if c]
    if not eff_required:
        eff_required = infer_required_capabilities(command)

    if device_capabilities is not None:
        eff_device_caps: List[str] = list(device_capabilities)
    else:
        eff_device_caps = lookup_device_capabilities(device_id)

    return audit_capability_override(
        device_id=device_id,
        required_capabilities=eff_required,
        device_capabilities=eff_device_caps,
        override_reason=override_reason,
        calling_site=calling_site,
    )
