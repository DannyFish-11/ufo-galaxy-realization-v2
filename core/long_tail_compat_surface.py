#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/long_tail_compat_surface.py
=================================
PR-8 (UGCP convergence plan, realization-v2 side): Identification and
classification of long-tail capability/message-family paths that still
operate in minimal-compat or generic-forward mode, and replacement of the
highest-value flows with clearer canonical stateful handling.

Background
----------
The main dispatch chain is relatively mature, but several long-tail
multi-device capability and protocol paths still depend on:

* ``handle_generic_forward`` — placeholder ACK handler in
  ``galaxy_gateway.android.handlers.generic`` (returns a bare
  ``{type}_ack`` with no stateful semantics).
* ``_handle_forward_ack`` — analogous minimal-compat handler in the
  legacy chain-B ``galaxy_gateway.handlers.message_handler.MessageHandler``.
* ``compatibility-forwarded WS message handling`` — raw mesh types
  (``peer_announce``, ``peer_exchange``, ``mesh_topology``) dispatched
  outside the AIP v3 normalization pipeline.

The affected message families are:

* **File transfer** (``FILE_TRANSFER``) — highest value; stateful
  two-phase transfer (read → write) exists in ``DeviceOrchestrator``
  but is not wired into the Android-bridge ingress path.
* **Peer exchange** (``PEER_ANNOUNCE``, ``PEER_EXCHANGE``) — highest
  value; ``MeshCoordinator`` already handles these types correctly in
  the WS-transport pre-dispatch path, but the Android-bridge ingress
  path routes them through ``handle_generic_forward``.
* **Mesh topology** (``MESH_TOPOLOGY``) — highest value; same gap as
  peer exchange.
* **Remote control / action execution** (``UI_TREE_REQUEST``,
  ``ACTION_EXECUTE``, ``ACTION_SEQUENCE_EXECUTE``) — medium value;
  these commands are outbound (server → device) so Android-bridge ACK
  handling is intentionally minimal, but the ACK path should still
  carry transfer-state and correlation information.
* **App lifecycle** (``APP_START``, ``APP_STOP``) — medium value;
  same category as remote control.
* **System commands** (``SYSTEM_COMMAND``) — medium value.
* **Agent configuration** (``AGENT_CONFIG_UPDATE``, ``AGENT_RESTART``)
  — lower value; these are infrequent control-plane commands.
* **Task lifecycle queries** (``TASK_CANCEL``, ``TASK_STATUS``) —
  medium value; cancel/status should check actual task state rather
  than returning a bare ACK.

This module provides:

* An **explicit taxonomy** (``LongTailPathKind``, ``LongTailValueTier``)
  for long-tail paths.
* A **comprehensive catalog** (``_LONG_TAIL_CATALOG``) that classifies
  every affected path by kind, value tier, transition status, and
  canonical handler reference.
* Clear **policy sentinels** affirming the invariants that must hold.
* **Query helpers** for operator tools, diagnostic surfaces, and CI.

Design principles
-----------------
* **Additive only** — this module does not modify any existing module.
  It provides vocabulary and a queryable governance surface.
* **Honest about the long tail** — every generic-forward path is
  catalogued with its transition status; none are marked closed-loop
  unless a real stateful handler exists.
* **Machine-checkable** — all sentinels are importable strings that
  tests and diagnostic endpoints can assert.

Public surface
--------------
Sentinels
~~~~~~~~~
:data:`LONG_TAIL_COMPAT_SURFACE_IS_AUTHORITY`
:data:`LONG_TAIL_COMPAT_SURFACE_PR8_SENTINEL`
:data:`GENERIC_FORWARD_IS_TRANSITIONAL_POLICY`
:data:`MINIMAL_COMPAT_PATHS_MUST_BE_CATALOGUED_POLICY`
:data:`HIGHEST_VALUE_FLOWS_REQUIRE_STATEFUL_HANDLING_POLICY`
:data:`LONG_TAIL_HONESTY_POLICY`

Enums
~~~~~
:class:`LongTailPathKind`
:class:`LongTailValueTier`
:class:`LongTailTransitionStatus`

Data classes
~~~~~~~~~~~~
:class:`LongTailPathRecord`
:class:`LongTailCatalogSummary`

Functions
~~~~~~~~~
:func:`get_long_tail_catalog`
:func:`get_paths_by_tier`
:func:`get_generic_forward_paths`
:func:`get_closed_loop_paths`
:func:`get_transitional_paths`
:func:`build_catalog_summary`
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Sentinels
# ---------------------------------------------------------------------------

LONG_TAIL_COMPAT_SURFACE_IS_AUTHORITY: str = (
    "LONG_TAIL_COMPAT_SURFACE::IS_CANONICAL_AUTHORITY_PR8"
)
"""This module is the canonical authority for long-tail compat path inventory."""

LONG_TAIL_COMPAT_SURFACE_PR8_SENTINEL: str = (
    "LONG_TAIL_COMPAT_SURFACE::PR8_SENTINEL"
)
"""Machine-checkable sentinel confirming PR-8 long-tail compat surface wiring."""

GENERIC_FORWARD_IS_TRANSITIONAL_POLICY: str = (
    "LONG_TAIL_COMPAT_SURFACE::GENERIC_FORWARD_IS_TRANSITIONAL"
    " — handle_generic_forward / _handle_forward_ack are placeholder handlers."
    " They must not be extended as canonical architecture."
    " Every message family currently routed through generic-forward"
    " is catalogued here with a target transition status."
)
"""Policy: generic-forward handlers are explicitly transitional."""

MINIMAL_COMPAT_PATHS_MUST_BE_CATALOGUED_POLICY: str = (
    "LONG_TAIL_COMPAT_SURFACE::MINIMAL_COMPAT_PATHS_MUST_BE_CATALOGUED"
    " — every message-family path operating in minimal-compat or generic-forward"
    " mode must appear in the long-tail catalog maintained by this module."
)
"""Policy: minimal-compat paths must be explicitly catalogued."""

HIGHEST_VALUE_FLOWS_REQUIRE_STATEFUL_HANDLING_POLICY: str = (
    "LONG_TAIL_COMPAT_SURFACE::HIGHEST_VALUE_FLOWS_REQUIRE_STATEFUL_HANDLING"
    " — file transfer, peer exchange, and mesh topology paths are the highest-value"
    " long-tail flows.  They must have dedicated stateful handlers that carry"
    " transfer-state, correlation IDs, and structured lifecycle semantics."
    " Routing them through generic-forward is not acceptable."
)
"""Policy: highest-value flows must not use generic-forward."""

LONG_TAIL_HONESTY_POLICY: str = (
    "LONG_TAIL_COMPAT_SURFACE::LONG_TAIL_HONESTY"
    " — this module must accurately reflect which multi-device flows are"
    " truly closed-loop (CANONICAL) and which remain transitional or open."
    " Marking a path CANONICAL without a real stateful handler is prohibited."
)
"""Policy: the catalog must honestly reflect closed-loop status."""

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class LongTailPathKind(str, Enum):
    """Functional category of a long-tail message-family path."""

    FILE_TRANSFER = "file_transfer"
    """Cross-device file read/write transfer flow."""

    PEER_EXCHANGE = "peer_exchange"
    """Mesh P2P peer announcement and exchange flow."""

    MESH_TOPOLOGY = "mesh_topology"
    """Mesh topology query and broadcast flow."""

    REMOTE_CONTROL = "remote_control"
    """Server-initiated GUI / action execution on a device."""

    APP_LIFECYCLE = "app_lifecycle"
    """App start/stop commands sent to a device."""

    SYSTEM_COMMAND = "system_command"
    """Arbitrary system-level commands sent to a device."""

    AGENT_CONFIG = "agent_config"
    """Agent configuration update and restart commands."""

    TASK_LIFECYCLE = "task_lifecycle"
    """Task cancel and status query from a device."""


class LongTailValueTier(str, Enum):
    """Business value of promoting a path out of generic-forward mode."""

    HIGHEST = "highest"
    """File transfer, peer exchange, mesh topology."""

    MEDIUM = "medium"
    """Remote control, app lifecycle, system command, task lifecycle."""

    LOWER = "lower"
    """Agent config, infrequent control-plane commands."""


class LongTailTransitionStatus(str, Enum):
    """Current transition status of a long-tail path."""

    GENERIC_FORWARD = "generic_forward"
    """Path still routed through handle_generic_forward (placeholder ACK only)."""

    MINIMAL_COMPAT = "minimal_compat"
    """Path has a minimal-compat handler but no real stateful semantics."""

    CANONICAL = "canonical"
    """Path has a dedicated stateful handler with lifecycle semantics."""

    TRANSITIONAL = "transitional"
    """Path is in transition: canonical handler exists but not fully wired."""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class LongTailPathRecord:
    """Record for a single long-tail message-family path."""

    message_type: str
    """AIP v3 MessageType value (e.g. ``'file_transfer'``)."""

    kind: LongTailPathKind
    """Functional category."""

    value_tier: LongTailValueTier
    """Business value of promoting this path."""

    transition_status: LongTailTransitionStatus
    """Current transition status."""

    canonical_handler: Optional[str] = None
    """Dotted module path of the canonical handler, or ``None`` if missing."""

    compat_handler: Optional[str] = None
    """Dotted module path of the current compat/placeholder handler."""

    notes: str = ""
    """Human-readable notes on gap, migration status, and governance."""

    is_closed_loop: bool = False
    """True only when a real stateful handler is wired end-to-end."""


@dataclass
class LongTailCatalogSummary:
    """Aggregated summary of the long-tail catalog."""

    total: int = 0
    by_tier: Dict[str, int] = field(default_factory=dict)
    by_status: Dict[str, int] = field(default_factory=dict)
    closed_loop_count: int = 0
    generic_forward_count: int = 0
    canonical_message_types: List[str] = field(default_factory=list)
    generic_forward_message_types: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

_LONG_TAIL_CATALOG: List[LongTailPathRecord] = [
    # ── Highest-value flows ──────────────────────────────────────────────────
    LongTailPathRecord(
        message_type="file_transfer",
        kind=LongTailPathKind.FILE_TRANSFER,
        value_tier=LongTailValueTier.HIGHEST,
        transition_status=LongTailTransitionStatus.CANONICAL,
        canonical_handler=(
            "galaxy_gateway.android.handlers.file_transfer.handle_file_transfer"
        ),
        compat_handler="galaxy_gateway.android.handlers.generic.handle_generic_forward",
        notes=(
            "PR-8: Dedicated stateful handler created.  The handler records"
            " transfer_id, file_name, file_size, and checksum in its response."
            " Routes FILE_TRANSFER inbound (device → server) messages to the"
            " DeviceOrchestrator transfer pipeline.  Previously routed through"
            " handle_generic_forward with no stateful semantics."
        ),
        is_closed_loop=True,
    ),
    LongTailPathRecord(
        message_type="peer_announce",
        kind=LongTailPathKind.PEER_EXCHANGE,
        value_tier=LongTailValueTier.HIGHEST,
        transition_status=LongTailTransitionStatus.CANONICAL,
        canonical_handler=(
            "galaxy_gateway.android.handlers.peer_exchange.handle_peer_announce"
        ),
        compat_handler="galaxy_gateway.android.handlers.generic.handle_generic_forward",
        notes=(
            "PR-8: Dedicated stateful handler created.  Registers the peer in"
            " MeshCoordinator and returns the current peer list as peer_exchange."
            " Previously routed through handle_generic_forward with no mesh"
            " coordinator integration in the Android-bridge ingress path."
        ),
        is_closed_loop=True,
    ),
    LongTailPathRecord(
        message_type="peer_exchange",
        kind=LongTailPathKind.PEER_EXCHANGE,
        value_tier=LongTailValueTier.HIGHEST,
        transition_status=LongTailTransitionStatus.CANONICAL,
        canonical_handler=(
            "galaxy_gateway.android.handlers.peer_exchange.handle_peer_exchange"
        ),
        compat_handler="galaxy_gateway.android.handlers.generic.handle_generic_forward",
        notes=(
            "PR-8: Dedicated stateful handler created.  Returns the current"
            " peer list from MeshCoordinator.  Previously routed through"
            " handle_generic_forward with no mesh coordinator integration."
        ),
        is_closed_loop=True,
    ),
    LongTailPathRecord(
        message_type="mesh_topology",
        kind=LongTailPathKind.MESH_TOPOLOGY,
        value_tier=LongTailValueTier.HIGHEST,
        transition_status=LongTailTransitionStatus.CANONICAL,
        canonical_handler=(
            "galaxy_gateway.android.handlers.mesh_topology.handle_mesh_topology"
        ),
        compat_handler="galaxy_gateway.android.handlers.generic.handle_generic_forward",
        notes=(
            "PR-8: Dedicated stateful handler created.  Returns the full mesh"
            " topology from MeshCoordinator including peer count, connection"
            " types, and probe status.  Previously routed through"
            " handle_generic_forward with no MeshCoordinator integration in"
            " the Android-bridge ingress path."
        ),
        is_closed_loop=True,
    ),
    # ── Medium-value flows ───────────────────────────────────────────────────
    LongTailPathRecord(
        message_type="ui_tree_request",
        kind=LongTailPathKind.REMOTE_CONTROL,
        value_tier=LongTailValueTier.MEDIUM,
        transition_status=LongTailTransitionStatus.GENERIC_FORWARD,
        compat_handler="galaxy_gateway.android.handlers.generic.handle_generic_forward",
        notes=(
            "TRANSITIONAL: UI_TREE_REQUEST is an outbound command (server →"
            " device).  The Android bridge sees these only when a device echoes"
            " back an acknowledgement.  The current generic-forward ACK is"
            " acceptable short-term but should be replaced with a structured"
            " ACK that carries correlation_id and screen_capture reference."
        ),
        is_closed_loop=False,
    ),
    LongTailPathRecord(
        message_type="action_execute",
        kind=LongTailPathKind.REMOTE_CONTROL,
        value_tier=LongTailValueTier.MEDIUM,
        transition_status=LongTailTransitionStatus.GENERIC_FORWARD,
        compat_handler="galaxy_gateway.android.handlers.generic.handle_generic_forward",
        notes=(
            "TRANSITIONAL: ACTION_EXECUTE acknowledgements from the device"
            " should carry action_id, result_status, and elapsed_ms."
            " Current generic-forward returns only a bare status='received'."
        ),
        is_closed_loop=False,
    ),
    LongTailPathRecord(
        message_type="action_sequence_execute",
        kind=LongTailPathKind.REMOTE_CONTROL,
        value_tier=LongTailValueTier.MEDIUM,
        transition_status=LongTailTransitionStatus.GENERIC_FORWARD,
        compat_handler="galaxy_gateway.android.handlers.generic.handle_generic_forward",
        notes=(
            "TRANSITIONAL: ACTION_SEQUENCE_EXECUTE ACKs should carry"
            " sequence_id, step_count, and execution status.  Current"
            " generic-forward lacks these fields."
        ),
        is_closed_loop=False,
    ),
    LongTailPathRecord(
        message_type="app_start",
        kind=LongTailPathKind.APP_LIFECYCLE,
        value_tier=LongTailValueTier.MEDIUM,
        transition_status=LongTailTransitionStatus.GENERIC_FORWARD,
        compat_handler="galaxy_gateway.android.handlers.generic.handle_generic_forward",
        notes=(
            "TRANSITIONAL: APP_START ACKs should carry package_name and"
            " launch_time_ms.  Current generic-forward lacks these fields."
        ),
        is_closed_loop=False,
    ),
    LongTailPathRecord(
        message_type="app_stop",
        kind=LongTailPathKind.APP_LIFECYCLE,
        value_tier=LongTailValueTier.MEDIUM,
        transition_status=LongTailTransitionStatus.GENERIC_FORWARD,
        compat_handler="galaxy_gateway.android.handlers.generic.handle_generic_forward",
        notes=(
            "TRANSITIONAL: APP_STOP ACKs should carry package_name and"
            " exit_code.  Current generic-forward lacks these fields."
        ),
        is_closed_loop=False,
    ),
    LongTailPathRecord(
        message_type="system_command",
        kind=LongTailPathKind.SYSTEM_COMMAND,
        value_tier=LongTailValueTier.MEDIUM,
        transition_status=LongTailTransitionStatus.GENERIC_FORWARD,
        compat_handler="galaxy_gateway.android.handlers.generic.handle_generic_forward",
        notes=(
            "TRANSITIONAL: SYSTEM_COMMAND ACKs should carry command_name,"
            " exit_code, and stdout/stderr summary.  Current generic-forward"
            " lacks these fields."
        ),
        is_closed_loop=False,
    ),
    LongTailPathRecord(
        message_type="task_cancel",
        kind=LongTailPathKind.TASK_LIFECYCLE,
        value_tier=LongTailValueTier.MEDIUM,
        transition_status=LongTailTransitionStatus.CANONICAL,
        canonical_handler=(
            "galaxy_gateway.android.handlers.task_lifecycle.handle_task_cancel"
        ),
        compat_handler="galaxy_gateway.android.handlers.generic.handle_generic_forward",
        notes=(
            "CANONICAL: handle_task_cancel() looks up the pending Future in"
            " bridge._pending_responses[task_id], cancels it, clears"
            " current_task_id from the device cache, and returns a structured"
            " task_cancel_ack with cancelled=True/False and a reason field."
            " Previously routed through handle_generic_forward with no real"
            " task cancellation semantics."
        ),
        is_closed_loop=True,
    ),
    LongTailPathRecord(
        message_type="task_status",
        kind=LongTailPathKind.TASK_LIFECYCLE,
        value_tier=LongTailValueTier.MEDIUM,
        transition_status=LongTailTransitionStatus.CANONICAL,
        canonical_handler=(
            "galaxy_gateway.android.handlers.task_lifecycle.handle_task_status"
        ),
        compat_handler="galaxy_gateway.android.handlers.generic.handle_generic_forward",
        notes=(
            "CANONICAL: handle_task_status() reads current_task_id from"
            " bridge._devices[device_id] and checks bridge._pending_responses"
            " to determine the real task state, returning a structured"
            " task_status_response with status/progress fields."
            " Previously routed through handle_generic_forward with no real"
            " task state lookup."
        ),
        is_closed_loop=True,
    ),
    # ── Lower-value flows ────────────────────────────────────────────────────
    LongTailPathRecord(
        message_type="agent_config_update",
        kind=LongTailPathKind.AGENT_CONFIG,
        value_tier=LongTailValueTier.LOWER,
        transition_status=LongTailTransitionStatus.GENERIC_FORWARD,
        compat_handler="galaxy_gateway.android.handlers.generic.handle_generic_forward",
        notes=(
            "TRANSITIONAL: AGENT_CONFIG_UPDATE should apply the config diff"
            " to the agent state and confirm applied fields.  Current"
            " generic-forward is acceptable as a lower-priority placeholder."
        ),
        is_closed_loop=False,
    ),
    LongTailPathRecord(
        message_type="agent_restart",
        kind=LongTailPathKind.AGENT_CONFIG,
        value_tier=LongTailValueTier.LOWER,
        transition_status=LongTailTransitionStatus.GENERIC_FORWARD,
        compat_handler="galaxy_gateway.android.handlers.generic.handle_generic_forward",
        notes=(
            "TRANSITIONAL: AGENT_RESTART should trigger a controlled agent"
            " restart lifecycle and confirm the restart intent.  Current"
            " generic-forward is acceptable as a lower-priority placeholder."
        ),
        is_closed_loop=False,
    ),
]

# Keyed lookup: message_type → record
_CATALOG_INDEX: Dict[str, LongTailPathRecord] = {
    r.message_type: r for r in _LONG_TAIL_CATALOG
}


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


def get_long_tail_catalog() -> List[LongTailPathRecord]:
    """Return all long-tail path records in their defined order."""
    return list(_LONG_TAIL_CATALOG)


def get_paths_by_tier(tier: LongTailValueTier) -> List[LongTailPathRecord]:
    """Return all catalog entries with the given value tier."""
    return [r for r in _LONG_TAIL_CATALOG if r.value_tier == tier]


def get_generic_forward_paths() -> List[LongTailPathRecord]:
    """Return all catalog entries still routed through generic-forward."""
    return [
        r
        for r in _LONG_TAIL_CATALOG
        if r.transition_status == LongTailTransitionStatus.GENERIC_FORWARD
    ]


def get_closed_loop_paths() -> List[LongTailPathRecord]:
    """Return all catalog entries that have a real closed-loop handler."""
    return [r for r in _LONG_TAIL_CATALOG if r.is_closed_loop]


def get_transitional_paths() -> List[LongTailPathRecord]:
    """Return all catalog entries that are not yet closed-loop."""
    return [r for r in _LONG_TAIL_CATALOG if not r.is_closed_loop]


def get_path_record(message_type: str) -> Optional[LongTailPathRecord]:
    """Return the catalog record for *message_type*, or ``None`` if not found."""
    return _CATALOG_INDEX.get(message_type)


def build_catalog_summary() -> LongTailCatalogSummary:
    """Build a summary of the full long-tail catalog."""
    summary = LongTailCatalogSummary()
    summary.total = len(_LONG_TAIL_CATALOG)

    for record in _LONG_TAIL_CATALOG:
        tier_key = record.value_tier.value
        summary.by_tier[tier_key] = summary.by_tier.get(tier_key, 0) + 1

        status_key = record.transition_status.value
        summary.by_status[status_key] = summary.by_status.get(status_key, 0) + 1

        if record.is_closed_loop:
            summary.closed_loop_count += 1
            summary.canonical_message_types.append(record.message_type)

        if record.transition_status == LongTailTransitionStatus.GENERIC_FORWARD:
            summary.generic_forward_count += 1
            summary.generic_forward_message_types.append(record.message_type)

    return summary
