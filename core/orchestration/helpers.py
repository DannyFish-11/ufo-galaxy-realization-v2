"""core/orchestration/helpers.py — Orchestration helper services façade.

PR-7: Thin façade over OpenClawd's audit, fallback, and operator-override helpers.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("Galaxy.Orchestration.Helpers")

# ---------------------------------------------------------------------------
# Authority sentinel
# ---------------------------------------------------------------------------

ORCHESTRATION_HELPERS_AUTHORITY = "ORCHESTRATION_HELPERS_AUTHORITY"

# ---------------------------------------------------------------------------
# OrchestrationHelpers
# ---------------------------------------------------------------------------


class OrchestrationHelpers:
    """Façade over OpenClawd's audit, fallback, and policy-override helpers."""

    ORCHESTRATION_HELPERS_AUTHORITY = ORCHESTRATION_HELPERS_AUTHORITY

    @staticmethod
    def emit_audit(
        openclawd_instance: Any,
        event_type: str,
        **kwargs: Any,
    ) -> Optional[str]:
        """Delegate to ``openclawd_instance._emit_audit()``."""
        method = getattr(openclawd_instance, "_emit_audit", None)
        if method is None:
            return None
        try:
            return method(event_type, **kwargs)
        except Exception as exc:
            logger.warning("OrchestrationHelpers: emit_audit failed: %s", exc)
            return None

    @staticmethod
    def build_fallback_trace(
        openclawd_instance: Any,
        **kwargs: Any,
    ) -> Optional[Dict]:
        """Delegate to ``openclawd_instance._build_fallback_trace()``."""
        method = getattr(openclawd_instance, "_build_fallback_trace", None)
        if method is None:
            return None
        try:
            return method(**kwargs)
        except Exception as exc:
            logger.warning("OrchestrationHelpers: build_fallback_trace failed: %s", exc)
            return None

    @staticmethod
    def build_degraded_operation_envelope(
        openclawd_instance: Any,
        **kwargs: Any,
    ) -> Optional[Dict]:
        """Delegate to ``openclawd_instance._build_degraded_operation_envelope()``."""
        method = getattr(openclawd_instance, "_build_degraded_operation_envelope", None)
        if method is None:
            return None
        try:
            return method(**kwargs)
        except Exception as exc:
            logger.warning("OrchestrationHelpers: build_degraded_operation_envelope failed: %s", exc)
            return None
