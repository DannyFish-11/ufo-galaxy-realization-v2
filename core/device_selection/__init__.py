#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.device_selection
======================

PR-6 — Canonical device selection helpers.

This package centralises the device-input authority model for cross-device
coordination and multi-device orchestration.

All cross-device / orchestration device selection must consume canonical
projected device views (``RegisteredRuntimeDevice``) as its base input.
Router/runtime state is accepted only as routing-feasibility enrichment.

Public API
----------
DeviceParticipationStatus
    Frozen dataclass with five explicit participation flags:
    ``registered``, ``runtime_present``, ``routable``,
    ``cross_device_eligible``, ``orchestration_eligible``.

CanonicalDeviceSelectionEntry
    Pairs a canonical ``RegisteredRuntimeDevice`` with its derived
    :class:`DeviceParticipationStatus`.

assess_device_participation(device, router_liveness) → DeviceParticipationStatus
    Derive participation status from a canonical device view.

select_cross_device_candidates(devices, router_liveness) → list[CanonicalDeviceSelectionEntry]
    Filter to devices eligible for cross-device coordination.

select_orchestration_candidates(devices, router_liveness, required_capabilities)
    → list[CanonicalDeviceSelectionEntry]
    Filter to devices eligible for orchestration (stricter than cross-device).

device_score_input_from_canonical(entry, …) → DeviceScoreInput
    Bridge a canonical entry to the scoring engine input type.
"""

from __future__ import annotations

from .canonical_device_selector import (
    DeviceParticipationStatus,
    CanonicalDeviceSelectionEntry,
    assess_device_participation,
    select_cross_device_candidates,
    select_orchestration_candidates,
    device_score_input_from_canonical,
)

__all__ = [
    "DeviceParticipationStatus",
    "CanonicalDeviceSelectionEntry",
    "assess_device_participation",
    "select_cross_device_candidates",
    "select_orchestration_candidates",
    "device_score_input_from_canonical",
]
