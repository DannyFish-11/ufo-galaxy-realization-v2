#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.execution_policy.policy_band
===================================

PR-11 (V4) — Execution Policy Schema

Defines :class:`PolicyBand` — the top-level execution tier enum that
classifies what class of execution the system is currently permitted to
perform.

Policy Band Semantics
----------------------
+-------------------+-----------------------------------------------------------+
| Band              | Permitted execution                                       |
+===================+===========================================================+
| ``observe_only``  | Sensing / read-only operations only.  No side-effectful   |
|                   | actions.  Matches ``silent`` phase or ``retreat_tendency``|
|                   | above threshold.                                          |
+-------------------+-----------------------------------------------------------+
| ``assistive``     | Suggestive / advisory output.  May emit recommendations   |
|                   | but must not trigger direct device actions.  Typical for  |
|                   | ``liminal`` phase in early intent-formation.              |
+-------------------+-----------------------------------------------------------+
| ``bounded_execute``| Constrained execution within an explicit risk/action      |
|                   | budget.  Cross-device expansion may be held back.         |
|                   | Confirmation may be required for high-risk steps.         |
+-------------------+-----------------------------------------------------------+
| ``full_execute``  | Full execution authority.  All executor levels and        |
|                   | cross-device expansion are eligible (subject to other     |
|                   | per-request constraints).  Typically ``manifest`` phase   |
|                   | with a healthy authority path.                            |
+-------------------+-----------------------------------------------------------+

The band is derived by :func:`~core.execution_policy.policy_resolver.resolve_policy`
from the combination of :class:`~core.continuum.types.TriStatePhase`,
:class:`~core.continuum.types.RuntimeDomain`, authority role, and return
pressure.  See :mod:`~core.execution_policy.policy_resolver` for the full
derivation logic.

Future PRs may enforce the band by gating execution in
``WindowsExecutionArbiter``, ``TaskGraph``, or ``ConstellationRuntime``.
This PR only defines and resolves the schema.
"""

from __future__ import annotations

from enum import Enum


__all__ = [
    "PolicyBand",
    "BAND_ORDER",
    "band_allows_execution",
    "band_allows_cross_device",
    "band_requires_confirmation",
]


class PolicyBand(str, Enum):
    """Top-level execution tier.

    The string values are stable serialisable identifiers safe for use in
    logs, API responses, and downstream projection surfaces.
    """

    OBSERVE_ONLY = "observe_only"
    """Read-only / sensing only.  No side-effectful actions permitted."""

    ASSISTIVE = "assistive"
    """Advisory output only.  No direct device or executor actions."""

    BOUNDED_EXECUTE = "bounded_execute"
    """Constrained execution within explicit risk/action budget."""

    FULL_EXECUTE = "full_execute"
    """Full execution authority within standard system constraints."""


# ---------------------------------------------------------------------------
# Ordering helpers
# ---------------------------------------------------------------------------

#: Ordered list from least to most permissive.  Used for comparisons such as
#: "is band A at least as permissive as band B?".
BAND_ORDER: list[PolicyBand] = [
    PolicyBand.OBSERVE_ONLY,
    PolicyBand.ASSISTIVE,
    PolicyBand.BOUNDED_EXECUTE,
    PolicyBand.FULL_EXECUTE,
]

#: Integer rank for each band.  Higher = more permissive.
_BAND_RANK: dict[PolicyBand, int] = {band: i for i, band in enumerate(BAND_ORDER)}


def band_rank(band: PolicyBand) -> int:
    """Return the numeric rank of *band* (0 = least permissive)."""
    return _BAND_RANK[band]


def band_allows_execution(band: PolicyBand) -> bool:
    """Return ``True`` if *band* permits at least some direct execution.

    ``observe_only`` and ``assistive`` do not permit execution of
    side-effectful steps.

    >>> band_allows_execution(PolicyBand.BOUNDED_EXECUTE)
    True
    >>> band_allows_execution(PolicyBand.OBSERVE_ONLY)
    False
    """
    return band_rank(band) >= band_rank(PolicyBand.BOUNDED_EXECUTE)


def band_allows_cross_device(band: PolicyBand) -> bool:
    """Return ``True`` if *band* is eligible for cross-device expansion.

    Only :attr:`~PolicyBand.FULL_EXECUTE` unconditionally allows cross-device.
    Lower bands may still allow cross-device if the resolver explicitly sets
    the flag, but the band-level hint is conservative.

    >>> band_allows_cross_device(PolicyBand.FULL_EXECUTE)
    True
    >>> band_allows_cross_device(PolicyBand.BOUNDED_EXECUTE)
    False
    """
    return band is PolicyBand.FULL_EXECUTE


def band_requires_confirmation(band: PolicyBand) -> bool:
    """Return ``True`` if the band level implies confirmation is advisable.

    ``bounded_execute`` always recommends confirmation for side-effectful
    steps.  ``full_execute`` does not require it at the band level (though
    individual policy objects may still set ``requires_confirmation=True``
    based on other signals).

    >>> band_requires_confirmation(PolicyBand.BOUNDED_EXECUTE)
    True
    >>> band_requires_confirmation(PolicyBand.FULL_EXECUTE)
    False
    """
    return band is PolicyBand.BOUNDED_EXECUTE
