#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/unified/release_gate.py
=============================
Block-5: Release Guardrails — Staged Rollout & Fast Rollback

The :class:`ReleaseGate` reads ``config/feature_flags.yaml`` (or an in-process
override dict) and exposes a simple :meth:`is_enabled` check that every
critical code path uses before activating a feature.

Design goals
------------
* **Zero-downtime rollout** — ``rollout_percentage`` supports gradual exposure
  (0 = off, 100 = full).  Consistency is achieved by hashing the ``context_key``
  (e.g. ``task_id`` or ``session_id``) against the percentage threshold.
* **Fast rollback** — set ``enabled: false`` in ``feature_flags.yaml`` or call
  :meth:`ReleaseGate.override` to disable a feature immediately without redeploy.
* **Audit log** — every gate evaluation (allow/block) is logged at DEBUG level
  and tracked in an in-memory counter.

Usage::

    from core.unified.release_gate import get_release_gate

    gate = get_release_gate()

    if gate.is_enabled("global_arbiter", context_key=task_id):
        decision = arbiter.admit(task_id, priority=5, origin="planner")
    else:
        decision = _always_admit_fallback()

Exceptions
----------
:class:`FeatureDisabledError` — raised by :meth:`ReleaseGate.require_enabled`
when the feature is off.  Mapped to
:attr:`~core.unified.error_codes.GalaxyErrorCode.RELEASE_FEATURE_DISABLED`.

:class:`RolloutBlockedError` — raised by :meth:`ReleaseGate.require_enabled`
when the feature is on but the rollout percentage excludes the current context.
Mapped to :attr:`~core.unified.error_codes.GalaxyErrorCode.RELEASE_ROLLOUT_BLOCKED`.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("Galaxy.ReleaseGate")

_DEFAULT_FLAGS_PATH = Path(__file__).parent.parent.parent / "config" / "feature_flags.yaml"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class FeatureDisabledError(Exception):
    """Raised when a required feature is fully disabled."""

    def __init__(self, flag: str) -> None:
        super().__init__(f"Feature '{flag}' is disabled")
        self.flag = flag
        self.code = "RL_001"


class RolloutBlockedError(Exception):
    """Raised when a context_key is outside the rollout percentage."""

    def __init__(self, flag: str, percentage: int, context_key: str) -> None:
        super().__init__(
            f"Feature '{flag}' rollout {percentage}% excludes context '{context_key}'"
        )
        self.flag = flag
        self.percentage = percentage
        self.context_key = context_key
        self.code = "RL_002"


# ---------------------------------------------------------------------------
# Release gate implementation
# ---------------------------------------------------------------------------


class ReleaseGate:
    """Singleton release gate backed by ``config/feature_flags.yaml``.

    Thread-safe for reads.  Writes (``override``, ``reload``) are not
    concurrency-protected but are safe in CPython due to the GIL.
    """

    _instance: Optional["ReleaseGate"] = None

    def __new__(cls) -> "ReleaseGate":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self) -> None:
        self._flags: Dict[str, Dict[str, Any]] = {}
        self._overrides: Dict[str, bool] = {}
        self._stats: Dict[str, Dict[str, int]] = {}   # flag → {"allowed": N, "blocked": N}
        self._loaded_at: float = 0.0
        self._load_flags()

    # ------------------------------------------------------------------
    # Flag loading
    # ------------------------------------------------------------------

    def _load_flags(self) -> None:
        """Load flags from YAML file.  Falls back to empty dict on any error."""
        path = _DEFAULT_FLAGS_PATH
        env_override = os.environ.get("GALAXY_FEATURE_FLAGS_PATH")
        if env_override:
            path = Path(env_override)

        if not path.exists():
            logger.debug("feature_flags.yaml not found at %s — all flags default ON", path)
            self._flags = {}
            return

        try:
            import yaml  # optional dep; only loaded here
            with open(path, "r", encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
            self._flags = {k: v for k, v in raw.items() if isinstance(v, dict)}
            self._loaded_at = time.time()
            logger.info("ReleaseGate: loaded %d flags from %s", len(self._flags), path)
        except ImportError:
            logger.warning(
                "PyYAML not installed — ReleaseGate cannot load feature_flags.yaml; "
                "all features default to enabled."
            )
            self._flags = {}
        except Exception as exc:
            logger.error("ReleaseGate: failed to load flags: %s", exc)
            self._flags = {}

    def reload(self) -> int:
        """Reload flags from disk.  Returns number of flags loaded."""
        self._load_flags()
        return len(self._flags)

    # ------------------------------------------------------------------
    # Primary API
    # ------------------------------------------------------------------

    def is_enabled(self, flag: str, *, context_key: str = "") -> bool:
        """Return True if *flag* is enabled for the given *context_key*.

        Evaluation order:
        1. In-process override (set via :meth:`override`).
        2. ``enabled`` field in YAML (False → always blocked).
        3. ``rollout_percentage`` — hash-based consistency gate.
        4. Default: ``True`` (flags not present in YAML default to on).
        """
        # 1. In-process override
        if flag in self._overrides:
            result = self._overrides[flag]
            self._track(flag, result)
            return result

        defn = self._flags.get(flag)
        if defn is None:
            # Unknown flag: default enabled
            self._track(flag, True)
            return True

        # 2. enabled field
        if not defn.get("enabled", True):
            self._track(flag, False)
            logger.debug("ReleaseGate BLOCK flag=%s reason=disabled", flag)
            return False

        # 3. Rollout percentage
        pct = int(defn.get("rollout_percentage", 100))
        if pct >= 100:
            self._track(flag, True)
            return True
        if pct <= 0:
            self._track(flag, False)
            logger.debug("ReleaseGate BLOCK flag=%s reason=rollout_0", flag)
            return False

        # Hash-based bucketing for consistency
        bucket = self._bucket(flag, context_key)
        result = bucket < pct
        self._track(flag, result)
        if not result:
            logger.debug(
                "ReleaseGate BLOCK flag=%s pct=%d bucket=%d context=%s",
                flag, pct, bucket, context_key,
            )
        return result

    def require_enabled(self, flag: str, *, context_key: str = "") -> None:
        """Assert that *flag* is enabled; raise if not.

        Raises:
            :class:`FeatureDisabledError` if the flag is fully off.
            :class:`RolloutBlockedError` if rollout percentage excludes this context.
        """
        defn = self._flags.get(flag)
        if flag in self._overrides and not self._overrides[flag]:
            raise FeatureDisabledError(flag)
        if defn is not None and not defn.get("enabled", True):
            raise FeatureDisabledError(flag)

        if not self.is_enabled(flag, context_key=context_key):
            pct = int((defn or {}).get("rollout_percentage", 100))
            raise RolloutBlockedError(flag, pct, context_key)

    def override(self, flag: str, value: bool) -> None:
        """Set an in-process override for *flag* (survives reloads)."""
        self._overrides[flag] = value
        logger.info("ReleaseGate override flag=%s value=%s", flag, value)

    def clear_override(self, flag: str) -> None:
        """Remove in-process override for *flag*, deferring to YAML."""
        self._overrides.pop(flag, None)

    def clear_all_overrides(self) -> None:
        self._overrides.clear()

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    def stats(self) -> Dict[str, Any]:
        return {
            "flags_loaded": len(self._flags),
            "loaded_at": self._loaded_at,
            "overrides": dict(self._overrides),
            "gate_stats": dict(self._stats),
        }

    def list_flags(self) -> Dict[str, Any]:
        """Return the current flag state (YAML + overrides merged)."""
        result: Dict[str, Any] = {}
        for name, defn in self._flags.items():
            result[name] = {
                **defn,
                "override": self._overrides.get(name),
            }
        for name, val in self._overrides.items():
            if name not in result:
                result[name] = {"enabled": val, "override": val}
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _bucket(flag: str, context_key: str) -> int:
        """Return a deterministic integer 0-99 for (flag, context_key)."""
        raw = f"{flag}:{context_key}"
        try:
            # usedforsecurity=False is Python 3.9+; fall back for 3.8
            digest = hashlib.md5(raw.encode(), usedforsecurity=False).hexdigest()
        except TypeError:
            digest = hashlib.md5(raw.encode()).hexdigest()  # pragma: no cover
        return int(digest[:4], 16) % 100

    def _track(self, flag: str, allowed: bool) -> None:
        if flag not in self._stats:
            self._stats[flag] = {"allowed": 0, "blocked": 0}
        if allowed:
            self._stats[flag]["allowed"] += 1
        else:
            self._stats[flag]["blocked"] += 1


# ---------------------------------------------------------------------------
# Singleton accessor + reset
# ---------------------------------------------------------------------------


def get_release_gate() -> ReleaseGate:
    """Return the process-level :class:`ReleaseGate` singleton."""
    return ReleaseGate()


def reset_release_gate() -> None:
    """Reset the singleton (for testing)."""
    ReleaseGate._instance = None
