"""
galaxy_gateway/legacy/capability_registry.py — Canonical legacy location.

.. deprecated:: Batch PR-3
    Deprecation level: D1 (SOFT_DEPRECATED)
    Canonical replacement: ``core.capability_bus``
    Removal target: **Batch PR-5**

    This module is a **compatibility shim only**.  New code must not import
    from this path.  Use :mod:`core.capability_bus` directly instead.

    Active callers: legacy paths that reference the old
    ``galaxy_gateway.capability_registry`` import path.
    Do not delete until all callers have been migrated.

Legacy capability registry. Use core.capability_runtime for new work.
"""
import warnings

warnings.warn(
    "galaxy_gateway.legacy.capability_registry is deprecated (D1).  "
    "Use core.capability_bus instead.  "
    "This shim will be removed in Batch PR-5.",
    DeprecationWarning,
    stacklevel=2,
)

from galaxy_gateway.capability_registry import *  # noqa: F401, F403, E402
try:
    from galaxy_gateway.capability_registry import __all__
except ImportError:
    pass
